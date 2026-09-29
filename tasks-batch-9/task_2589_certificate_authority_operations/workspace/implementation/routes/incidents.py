"""Misissuance incidents, disclosure, mass revocation and closure (PRD 3.9)."""

import datetime

from flask import Blueprint

from db import db, make_record, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services import calc, cascade
from services.lookup import get_incident, get_profile, get_subscriber
from validation import (DCV_METHODS, INCIDENT_CATEGORIES, ROOT_PROGRAMS, enum_value, opt_str,
                        req_str, req_ts)

bp = Blueprint("incidents", __name__)

DISCLOSURE_WINDOW = datetime.timedelta(hours=24)
CLOSEABLE_STATES = ("DISCLOSED", "MASS_REVOCATION_IN_PROGRESS", "REMEDIATED")
DISCLOSED_STATES = ("DISCLOSED", "MASS_REVOCATION_IN_PROGRESS")


def _new_communication(incident_id, audit_id, root_program, kind, body, sent_by, within_deadline):
    record = make_record({
        "incident_id": incident_id,
        "audit_id": audit_id,
        "root_program": root_program,
        "kind": kind,
        "body": body,
        "sent_at": db.now(),
        "within_deadline": within_deadline,
        "sent_by_user_id": sent_by,
    }, versioned=False)
    db.communications[record["id"]] = record
    return record


@bp.route("/ca/misissuance-incidents", methods=["POST"])
def create_incident():
    authenticate(("COMPLIANCE_AUDITOR",))
    body = json_body()
    title = req_str(body, "title", 1, 120)
    category = req_str(body, "category")
    scope_profile_id = req_str(body, "scope_profile_id")
    scope_issued_from = req_ts(body, "scope_issued_from")
    scope_issued_to = req_ts(body, "scope_issued_to")
    subscriber_id = opt_str(body, "subscriber_id")
    scope_dcv_method = opt_str(body, "scope_dcv_method")
    enum_value(category, INCIDENT_CATEGORIES, "category")
    if scope_dcv_method is not None:
        enum_value(scope_dcv_method, DCV_METHODS, "scope_dcv_method")

    profile = get_profile(scope_profile_id)
    subscriber = get_subscriber(subscriber_id) if subscriber_id is not None else None

    if scope_issued_to <= scope_issued_from:
        fail("ERR_INVALID_SCOPE_WINDOW", "scope_issued_to must be strictly after scope_issued_from.")
    if scope_dcv_method is not None and scope_dcv_method not in profile["allowed_dcv_methods"]:
        fail(
            "ERR_SCOPE_METHOD_NOT_IN_PROFILE",
            "The scoped method is not approved by the scoped profile.",
        )

    now = db.now()
    record = make_record({
        "title": title,
        "category": category,
        "subscriber_id": subscriber["id"] if subscriber is not None else None,
        "scope_profile_id": profile["id"],
        "scope_dcv_method": scope_dcv_method,
        "scope_issued_from": scope_issued_from,
        "scope_issued_to": scope_issued_to,
        "discovered_at": now,
        "disclosure_due_at": now + DISCLOSURE_WINDOW,
        "disclosure_breached": False,
        "disclosed_at": None,
        "state": "OPEN",
        "revoked_certificate_count": 0,
        "remaining_scope_count": 0,
        "penalty_total_cents": 0,
        "closed_at": None,
    })
    db.incidents[record["id"]] = record
    cascade.refresh_risk_operational(record["subscriber_id"])
    return created(public(record))


@bp.route("/ca/misissuance-incidents", methods=["GET"])
def list_incidents():
    read_only(ALL_ROLES)
    records = apply_filters(db.incidents.values(), {
        "subscriber_id": "str",
        "scope_profile_id": "str",
        "state": "str",
        "category": "str",
        "disclosure_breached": "bool",
    })
    return paginated(sort_records(records))


@bp.route("/ca/misissuance-incidents/<incident_id>", methods=["GET"])
def get_one_incident(incident_id):
    read_only(ALL_ROLES)
    return ok(public(get_incident(incident_id)))


@bp.route("/ca/misissuance-incidents/<incident_id>/disclose", methods=["POST"])
def disclose_incident(incident_id):
    user_id, _role = authenticate(("COMPLIANCE_AUDITOR",))
    body = json_body()
    root_program = req_str(body, "root_program")
    narrative = req_str(body, "body")
    enum_value(root_program, ROOT_PROGRAMS, "root_program")

    incident = get_incident(incident_id)
    if incident["state"] != "OPEN":
        fail("ERR_INCIDENT_NOT_OPEN", "Only an OPEN incident may be disclosed.")

    now = db.now()
    incident["state"] = "DISCLOSED"
    incident["disclosed_at"] = now
    touch(incident)
    _new_communication(
        incident["id"], None, root_program, "INCIDENT_DISCLOSURE", narrative, user_id,
        now <= incident["disclosure_due_at"],
    )
    cascade.refresh_risk_operational(incident["subscriber_id"])
    return ok(public(incident))


@bp.route("/ca/misissuance-incidents/<incident_id>/communications", methods=["POST"])
def create_incident_communication(incident_id):
    user_id, _role = authenticate(("COMPLIANCE_AUDITOR",))
    body = json_body()
    root_program = req_str(body, "root_program")
    narrative = req_str(body, "body")
    enum_value(root_program, ROOT_PROGRAMS, "root_program")

    incident = get_incident(incident_id)
    if incident["state"] not in DISCLOSED_STATES:
        fail("ERR_INCIDENT_NOT_DISCLOSED", "The incident has not been disclosed.")

    record = _new_communication(
        incident["id"], None, root_program, "BREACH_ESCALATION", narrative, user_id, False
    )
    return created(public(record))


@bp.route("/ca/misissuance-incidents/<incident_id>/communications", methods=["GET"])
def list_incident_communications(incident_id):
    read_only(ALL_ROLES)
    incident = get_incident(incident_id)
    records = [c for c in db.communications.values() if c["incident_id"] == incident["id"]]
    records = apply_filters(records, {"kind": "str"})
    records = sorted(records, key=lambda c: (c["sent_at"], c["_seq"]))
    return paginated(records)


@bp.route("/ca/misissuance-incidents/<incident_id>/mass-revoke", methods=["POST"])
def mass_revoke(incident_id):
    user_id, _role = authenticate(("REVOCATION_OFFICER",))
    incident = get_incident(incident_id)

    if incident["state"] not in DISCLOSED_STATES:
        fail("ERR_INCIDENT_NOT_DISCLOSED", "The incident has not been disclosed.")

    if incident["disclosure_breached"]:
        escalated = any(
            c["incident_id"] == incident["id"] and c["kind"] == "BREACH_ESCALATION"
            for c in db.communications.values()
        )
        if not escalated:
            fail(
                "ERR_INCIDENT_DISCLOSURE_BREACHED",
                "A breach escalation must be filed before remediation may run.",
            )

    pool = [
        c for c in db.certificates.values()
        if c["profile_id"] == incident["scope_profile_id"]
        and c["revocation_status"] == "NONE"
        and c["lifecycle_status"] in ("PREISSUANCE", "ISSUED")
        and incident["scope_issued_from"] <= c["not_before"] < incident["scope_issued_to"]
        and (incident["scope_dcv_method"] is None
             or incident["scope_dcv_method"] in (c["dcv_methods_used"] or []))
    ]
    if not pool:
        fail("ERR_NO_CERTIFICATES_IN_SCOPE", "No certificate falls in the incident's scope.")

    pool = sorted(pool, key=lambda c: (c["created_at"], c["serial_number"]))
    batch = pool[:calc.MASS_REVOKE_BATCH_SIZE]
    remaining = len(pool) - len(batch)

    now = db.now()
    reason_code = calc.CATEGORY_REASON[incident["category"]]
    profile = db.profiles.get(incident["scope_profile_id"])
    penalty_total = 0
    touched_attributed = False
    for cert in batch:
        penalty_total += calc.certificate_penalty_cents(cert, incident["category"], now)
        cert["revocation_status"] = "REVOKED"
        cert["revoked_at"] = now
        cert["revocation_reason_code"] = reason_code
        touch(cert)
        cascade.new_revocation_request(
            cert, profile, reason_code, "MASS_REVOCATION", user_id, "EXECUTED",
            incident_id=incident["id"], evidence_ref=None, executed_at=now,
        )
        cascade.record_revocation_on_profile(profile)
        if incident["subscriber_id"] is not None and cert["subscriber_id"] == incident["subscriber_id"]:
            touched_attributed = True

    incident["revoked_certificate_count"] += len(batch)
    incident["remaining_scope_count"] = remaining
    incident["penalty_total_cents"] += penalty_total
    incident["state"] = "MASS_REVOCATION_IN_PROGRESS" if remaining > 0 else "REMEDIATED"
    touch(incident)

    if (incident["category"] == "KEY_COMPROMISE" and incident["subscriber_id"] is not None
            and touched_attributed):
        subscriber = db.subscribers.get(incident["subscriber_id"])
        if subscriber is not None and subscriber["account_status"] != "TERMINATED":
            subscriber["account_status"] = "TERMINATED"
            subscriber["suspended_at"] = now
            touch(subscriber)

    cascade.refresh_risk_operational(incident["subscriber_id"])
    return ok(public(incident))


@bp.route("/ca/misissuance-incidents/<incident_id>/close", methods=["POST"])
def close_incident(incident_id):
    authenticate(("COMPLIANCE_AUDITOR",))
    incident = get_incident(incident_id)

    if incident["state"] not in CLOSEABLE_STATES:
        fail("ERR_INCIDENT_NOT_CLOSEABLE", "The incident is not closeable.")

    outstanding = [
        r for r in db.revocation_requests.values()
        if r["incident_id"] == incident["id"] and r["state"] not in ("EXECUTED", "DENIED")
    ]
    if incident["remaining_scope_count"] != 0 or outstanding:
        fail(
            "ERR_INCIDENT_REVOCATIONS_OUTSTANDING",
            "The incident still has unfinished revocation work.",
        )

    incident["state"] = "CLOSED"
    incident["closed_at"] = db.now()
    touch(incident)
    cascade.refresh_risk_operational(incident["subscriber_id"])
    return ok(public(incident))
