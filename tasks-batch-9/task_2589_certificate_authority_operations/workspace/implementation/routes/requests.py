"""Certificate requests: the pipeline from DRAFT to ISSUED (PRD 3.5, 3.7)."""

import datetime

from flask import Blueprint

from db import db, make_record, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services import calc
from services.lookup import (get_ceremony, get_certificate, get_profile, get_request,
                             get_subscriber)
from validation import (CSR_KEY_SIZES, check_domain_name, in_range, one_of_range, opt_bool,
                        opt_str, req_int, req_list, req_str)

bp = Blueprint("requests", __name__)

MIN_KEY_BITS = {"DV": 2048, "OV": 2048, "EV": 3072}


@bp.route("/ca/certificate-requests", methods=["POST"])
def create_request():
    authenticate(("VALIDATION_OFFICER",))
    body = json_body()
    subscriber_id = req_str(body, "subscriber_id")
    profile_id = req_str(body, "profile_id")
    domains = req_list(body, "requested_domains")
    requested_validity_days = req_int(body, "requested_validity_days")
    csr_key_bits = req_int(body, "csr_key_bits")
    expedited = opt_bool(body, "expedited", False)

    in_range(requested_validity_days, 1, 398, "requested_validity_days")
    one_of_range(csr_key_bits, CSR_KEY_SIZES, "csr_key_bits")

    if len(domains) < 1 or len(domains) > 10:
        fail("ERR_INVALID_ARRAY_CONTENT", "requested_domains must hold between 1 and 10 names.")
    folded = []
    for domain in domains:
        if not isinstance(domain, str):
            fail("ERR_INVALID_ARRAY_CONTENT", "requested_domains must hold strings.")
        folded.append(domain.lower())
    if len(set(folded)) != len(folded):
        fail("ERR_INVALID_ARRAY_CONTENT", "requested_domains may not contain duplicates.")
    for domain in domains:
        check_domain_name(domain, "requested_domains")

    profile = get_profile(profile_id)
    subscriber = get_subscriber(subscriber_id)

    if subscriber["account_status"] != "ACTIVE":
        fail("ERR_SUBSCRIBER_NOT_ACTIVE", "The subscriber must be ACTIVE.")

    record = make_record({
        "subscriber_id": subscriber["id"],
        "profile_id": profile["id"],
        "requested_domains": list(domains),
        "requested_validity_days": requested_validity_days,
        "expedited": expedited,
        "csr_key_bits": csr_key_bits,
        "state": "DRAFT",
        "return_count": 0,
        "submitted_at": None,
        "validation_cleared_by_user_id": None,
        "validation_cleared_at": None,
        "consumed_authorization_ids": [],
        "projected_not_before": None,
        "projected_not_after": None,
        "projected_charge_cents": None,
        "issued_certificate_id": None,
        "rejected_reason": None,
        "blocked_reason": None,
    })
    db.requests[record["id"]] = record
    return created(public(record))


@bp.route("/ca/certificate-requests", methods=["GET"])
def list_requests():
    read_only(ALL_ROLES)
    records = apply_filters(db.requests.values(), {
        "subscriber_id": "str",
        "profile_id": "str",
        "issued_certificate_id": "str",
        "state": "str",
        "blocked_reason": "str",
    })
    return paginated(sort_records(records))


@bp.route("/ca/certificate-requests/<request_id>", methods=["GET"])
def get_one_request(request_id):
    read_only(ALL_ROLES)
    return ok(public(get_request(request_id)))


@bp.route("/ca/certificate-requests/<request_id>/submit", methods=["POST"])
def submit_request(request_id):
    authenticate(("VALIDATION_OFFICER",))
    req = get_request(request_id)
    profile = db.profiles.get(req["profile_id"])
    subscriber = db.subscribers.get(req["subscriber_id"])
    if profile is not None and profile["status"] != "ACTIVE":
        fail("ERR_PROFILE_NOT_ACTIVE", "The profile must be ACTIVE.")
    if subscriber is not None and subscriber["account_status"] != "ACTIVE":
        fail("ERR_SUBSCRIBER_NOT_ACTIVE", "The subscriber must be ACTIVE.")
    if req["state"] != "DRAFT":
        fail("ERR_REQUEST_NOT_DRAFT", "Only a DRAFT request may be submitted.")
    req["state"] = "SUBMITTED"
    req["submitted_at"] = db.now()
    touch(req)
    return ok(public(req))


@bp.route("/ca/certificate-requests/<request_id>/return", methods=["POST"])
def return_request(request_id):
    authenticate(("VALIDATION_OFFICER",))
    body = json_body()
    return_reason = req_str(body, "return_reason")
    req = get_request(request_id)
    if req["state"] != "SUBMITTED":
        fail("ERR_REQUEST_NOT_SUBMITTED", "Only a SUBMITTED request may be returned.")
    if req["return_count"] < 2:
        req["return_count"] += 1
        req["state"] = "DRAFT"
    else:
        req["return_count"] = 3
        req["state"] = "REJECTED"
        req["rejected_reason"] = return_reason
    touch(req)
    return ok(public(req))


@bp.route("/ca/certificate-requests/<request_id>/reject", methods=["POST"])
def reject_request(request_id):
    authenticate(("VALIDATION_OFFICER",))
    body = json_body()
    rejected_reason = req_str(body, "rejected_reason")
    req = get_request(request_id)
    if req["state"] not in ("DRAFT", "SUBMITTED"):
        fail("ERR_REQUEST_NOT_REJECTABLE", "Only a DRAFT or SUBMITTED request may be rejected.")
    req["state"] = "WITHDRAWN" if req["state"] == "DRAFT" else "REJECTED"
    req["rejected_reason"] = rejected_reason
    touch(req)
    return ok(public(req))


@bp.route("/ca/certificate-requests/<request_id>/clear-validation", methods=["POST"])
def clear_validation(request_id):
    user_id, _role = authenticate(("VALIDATION_OFFICER",))
    req = get_request(request_id)
    profile = db.profiles.get(req["profile_id"])
    subscriber = db.subscribers.get(req["subscriber_id"])

    if profile is not None and profile["status"] != "ACTIVE":
        fail("ERR_PROFILE_NOT_ACTIVE", "The profile must be ACTIVE.")
    if subscriber is not None and subscriber["account_status"] != "ACTIVE":
        fail("ERR_SUBSCRIBER_NOT_ACTIVE", "The subscriber must be ACTIVE.")
    if req["state"] != "SUBMITTED":
        fail("ERR_REQUEST_NOT_SUBMITTED", "Only a SUBMITTED request may be cleared.")

    now = db.now()
    domains = list(req["requested_domains"])
    related = {}
    for domain in domains:
        related[domain] = [
            a for a in db.authorizations.values()
            if a["subscriber_id"] == req["subscriber_id"]
            and a["profile_id"] == req["profile_id"]
            and a["domain_name"] == domain
        ]

    for domain in domains:
        if not any(a["state"] in ("VALIDATED", "EXPIRED") for a in related[domain]):
            fail(
                "ERR_DOMAIN_AUTHORIZATION_MISSING",
                "No domain authorization exists for '%s'." % domain,
            )
    for domain in domains:
        if not any(
            a["state"] == "VALIDATED" and a["expires_at"] is not None and a["expires_at"] > now
            for a in related[domain]
        ):
            fail(
                "ERR_DOMAIN_AUTHORIZATION_EXPIRED",
                "The domain authorization for '%s' has lapsed." % domain,
            )

    selected = []
    for domain in domains:
        fresh = [
            a for a in related[domain]
            if a["state"] == "VALIDATED" and a["expires_at"] is not None and a["expires_at"] > now
        ]
        candidates = [a for a in fresh if a["reuse_count"] < profile["max_dcv_reuse_count"]]
        if not candidates:
            fail(
                "ERR_DCV_REUSE_LIMIT_EXCEEDED",
                "Every authorization for '%s' has exhausted its reuse budget." % domain,
            )
        candidates.sort(
            key=lambda a: (a["validated_at"], a["created_at"], a["reuse_count"], a["_seq"]),
            reverse=True,
        )
        selected.append(candidates[0])

    if profile["required_vetting_level"] != "NONE":
        approved = [
            v for v in db.vettings.values()
            if v["subscriber_id"] == req["subscriber_id"] and v["vetting_state"] == "APPROVED"
        ]
        if not approved:
            fail("ERR_ORG_VETTING_REQUIRED", "The subscriber holds no approved vetting file.")
        needed = calc.VETTING_LEVEL_RANK[profile["required_vetting_level"]]
        covering = [
            v for v in approved if calc.VETTING_LEVEL_RANK[v["required_level"]] >= needed
        ]
        if not covering:
            fail(
                "ERR_ORG_VETTING_LEVEL_INSUFFICIENT",
                "The approved vetting does not cover %s." % profile["required_vetting_level"],
            )
        floor = now - datetime.timedelta(days=profile["org_vetting_reuse_days"])
        if not any(v["approved_at"] is not None and v["approved_at"] > floor for v in covering):
            fail("ERR_ORG_VETTING_REUSE_EXPIRED", "The approved vetting has lapsed.")

    if req["csr_key_bits"] < MIN_KEY_BITS[profile["validation_type"]]:
        fail(
            "ERR_CSR_KEY_TOO_WEAK",
            "A %s profile requires at least %d key bits."
            % (profile["validation_type"], MIN_KEY_BITS[profile["validation_type"]]),
        )

    for auth in selected:
        auth["reuse_count"] += 1
        touch(auth)

    capped = calc.capped_days(req["requested_validity_days"], profile)
    req["validation_cleared_by_user_id"] = user_id
    req["validation_cleared_at"] = now
    req["consumed_authorization_ids"] = [a["id"] for a in selected]
    req["projected_not_before"] = now
    req["projected_not_after"] = now + datetime.timedelta(days=capped)
    req["projected_charge_cents"] = calc.issuance_charge(profile, len(domains), req["expedited"])
    req["state"] = "READY_TO_ISSUE"
    touch(req)
    return ok(public(req))


@bp.route("/ca/certificate-requests/<request_id>/issue", methods=["POST"])
def issue_certificate(request_id):
    user_id, _role = authenticate(("ISSUANCE_OPERATOR",))
    body = json_body()
    ceremony_id = req_str(body, "ceremony_id")
    supersedes_id = opt_str(body, "supersedes_certificate_id")

    req = get_request(request_id)
    superseded = get_certificate(supersedes_id) if supersedes_id is not None else None
    ceremony = get_ceremony(ceremony_id)
    profile = db.profiles.get(req["profile_id"])
    subscriber = db.subscribers.get(req["subscriber_id"])
    partition = db.partitions.get(ceremony["partition_id"])

    if profile is not None and profile["status"] != "ACTIVE":
        fail("ERR_PROFILE_NOT_ACTIVE", "The profile must be ACTIVE.")
    if profile is not None and profile["status_service_posture"] != "NOMINAL":
        fail(
            "ERR_PROFILE_STATUS_SERVICE_OVERDUE",
            "The profile's revocation status service is overdue.",
        )
    if subscriber is not None and subscriber["account_status"] != "ACTIVE":
        fail("ERR_SUBSCRIBER_NOT_ACTIVE", "The subscriber must be ACTIVE.")
    if req["state"] != "READY_TO_ISSUE":
        fail("ERR_REQUEST_NOT_READY", "The request is not READY_TO_ISSUE.")
    if partition is not None and partition["state"] != "OPERATIONAL":
        fail("ERR_PARTITION_QUARANTINED", "The signing partition is quarantined.")

    if user_id == req["validation_cleared_by_user_id"]:
        fail(
            "ERR_ISSUANCE_SOD_VIOLATION",
            "The issuing operator may not be the officer who cleared validation.",
        )

    now = db.now()
    if ceremony["state"] != "ATTESTED":
        fail("ERR_CEREMONY_NOT_ATTESTED_FOR_ISSUANCE", "The ceremony is not ATTESTED.")
    if ceremony["attestation_expires_at"] is None or ceremony["attestation_expires_at"] <= now:
        fail("ERR_CEREMONY_ATTESTATION_EXPIRED", "The ceremony attestation has expired.")

    consumed = []
    for auth_id in req["consumed_authorization_ids"] or []:
        auth = db.authorizations.get(auth_id)
        if (auth is None or auth["state"] != "VALIDATED" or auth["expires_at"] is None
                or auth["expires_at"] <= now):
            fail(
                "ERR_DOMAIN_AUTHORIZATION_EXPIRED",
                "A consumed domain authorization is no longer valid.",
            )
        consumed.append(auth)

    if superseded is not None and superseded["subscriber_id"] != req["subscriber_id"]:
        fail(
            "ERR_SUPERSEDES_SUBSCRIBER_MISMATCH",
            "The superseded certificate belongs to another subscriber.",
        )

    charge = calc.issuance_charge(profile, len(req["requested_domains"]), req["expedited"])
    if subscriber["outstanding_balance_cents"] + charge > subscriber["credit_limit_cents"]:
        fail(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            "The issuance would exceed the subscriber's credit limit.",
        )

    capped = calc.capped_days(req["requested_validity_days"], profile)
    not_after = now + datetime.timedelta(days=capped)
    for auth in consumed:
        if auth["expires_at"] < not_after:
            not_after = auth["expires_at"]
    if ceremony["attestation_expires_at"] < not_after:
        not_after = ceremony["attestation_expires_at"]
    validity_days_final = int((not_after - now).total_seconds() // 86400)

    cert = make_record({
        "serial_number": db.next_serial(),
        "request_id": req["id"],
        "subscriber_id": req["subscriber_id"],
        "profile_id": req["profile_id"],
        "ceremony_id": ceremony["id"],
        "supersedes_certificate_id": supersedes_id,
        "lifecycle_status": "PREISSUANCE",
        "revocation_status": "NONE",
        "not_before": now,
        "not_after": not_after,
        "validity_days_final": validity_days_final,
        "dcv_methods_used": sorted(set(a["method"] for a in consumed)),
        "sct_count": 0,
        "charged_amount_cents": charge,
        "refunded_at": None,
        "activated_at": None,
        "revoked_at": None,
        "revocation_reason_code": None,
        "crl_number": None,
        "crl_published_at": None,
    })
    db.certificates[cert["id"]] = cert

    subscriber["outstanding_balance_cents"] += charge
    subscriber["issued_certificate_count"] += 1
    touch(subscriber)

    req["state"] = "ISSUED"
    req["issued_certificate_id"] = cert["id"]
    touch(req)

    ceremony["issued_certificate_count"] += 1
    touch(ceremony)

    return created(public(cert))
