"""Revocation requests, execution and denial (PRD 3.8)."""

from flask import Blueprint

from db import db, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services import cascade
from services.lookup import get_certificate, get_incident, get_revocation_request
from validation import REVOCATION_REASONS, enum_value, opt_str, req_int, req_str

bp = Blueprint("revocations", __name__)


@bp.route("/ca/revocation-requests", methods=["POST"])
def create_revocation_request():
    user_id, _role = authenticate(("REVOCATION_OFFICER",))
    body = json_body()
    certificate_id = req_str(body, "certificate_id")
    reason_code = req_str(body, "reason_code")
    expected_version = req_int(body, "expected_certificate_version")
    incident_id = opt_str(body, "incident_id")
    evidence_ref = opt_str(body, "evidence_ref")
    if reason_code == "KEY_COMPROMISE" and evidence_ref is None:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'evidence_ref' is required when reason_code is KEY_COMPROMISE.",
        )
    enum_value(reason_code, REVOCATION_REASONS, "reason_code")

    cert = get_certificate(certificate_id)
    incident = get_incident(incident_id) if incident_id is not None else None

    if expected_version != cert["version"]:
        fail(
            "ERR_STALE_CERTIFICATE_VERSION",
            "Expected certificate version %s but found %s."
            % (expected_version, cert["version"]),
        )

    if (cert["lifecycle_status"] not in ("PREISSUANCE", "ISSUED")
            or cert["revocation_status"] != "NONE"):
        fail("ERR_CERTIFICATE_NOT_REVOCABLE", "The certificate is not revocable.")

    if incident is not None and cert["profile_id"] != incident["scope_profile_id"]:
        fail(
            "ERR_INCIDENT_CERTIFICATE_MISMATCH",
            "The certificate is outside the incident's scoped profile.",
        )

    profile = db.profiles.get(cert["profile_id"])
    record = cascade.new_revocation_request(
        cert,
        profile,
        reason_code,
        "COMPLIANCE" if incident is not None else "SUBSCRIBER",
        user_id,
        "REQUESTED",
        incident_id=incident["id"] if incident is not None else None,
        evidence_ref=evidence_ref,
    )

    cert["revocation_status"] = "REVOCATION_PENDING"
    touch(cert)
    cascade.adjust_pending_revocations(db.subscribers.get(cert["subscriber_id"]), 1)
    cascade.supersede_other_open_requests(cert, record["id"])

    return created(public(record))


@bp.route("/ca/revocation-requests", methods=["GET"])
def list_revocation_requests():
    read_only(ALL_ROLES)
    records = apply_filters(db.revocation_requests.values(), {
        "certificate_id": "str",
        "incident_id": "str",
        "state": "str",
        "origin": "str",
        "reason_code": "str",
    })
    return paginated(sort_records(records))


@bp.route("/ca/revocation-requests/<revocation_request_id>", methods=["GET"])
def get_one_revocation_request(revocation_request_id):
    read_only(ALL_ROLES)
    return ok(public(get_revocation_request(revocation_request_id)))


@bp.route("/ca/revocation-requests/<revocation_request_id>/execute", methods=["POST"])
def execute_revocation_request(revocation_request_id):
    authenticate(("REVOCATION_OFFICER",))
    rr = get_revocation_request(revocation_request_id)

    if rr["state"] != "REQUESTED":
        fail("ERR_REVOCATION_REQUEST_NOT_OPEN", "The revocation request is not open.")

    cert = db.certificates.get(rr["certificate_id"])
    if cert is not None and cert["lifecycle_status"] == "EXPIRED":
        fail(
            "ERR_CERTIFICATE_EXPIRED_NOT_REVOCABLE",
            "An expired certificate is never added to a revocation list.",
        )
    if cert is not None and cert["revocation_status"] != "REVOCATION_PENDING":
        fail("ERR_CERTIFICATE_NOT_REVOCABLE", "The certificate is not pending revocation.")

    now = db.now()
    rr["state"] = "EXECUTED"
    rr["executed_at"] = now
    rr["deadline_breached"] = now > rr["deadline_at"]
    touch(rr)

    # Hop one: the certificate is revoked.
    cert["revocation_status"] = "REVOKED"
    cert["revoked_at"] = now
    cert["revocation_reason_code"] = rr["reason_code"]
    refund = cert["lifecycle_status"] == "PREISSUANCE" and rr["reason_code"] == "SUPERSEDED"
    if refund:
        cert["refunded_at"] = now
    touch(cert)

    subscriber = db.subscribers.get(cert["subscriber_id"])
    if refund and subscriber is not None:
        subscriber["outstanding_balance_cents"] -= cert["charged_amount_cents"]
    cascade.adjust_pending_revocations(subscriber, -1)

    # Hops two and three: the profile ledger and the posture flip.
    cascade.record_revocation_on_profile(db.profiles.get(cert["profile_id"]))

    return ok(public(rr))


@bp.route("/ca/revocation-requests/<revocation_request_id>/deny", methods=["POST"])
def deny_revocation_request(revocation_request_id):
    authenticate(("REVOCATION_OFFICER",))
    body = json_body()
    denial_reason = req_str(body, "denial_reason")
    rr = get_revocation_request(revocation_request_id)

    if rr["state"] != "REQUESTED":
        fail("ERR_REVOCATION_REQUEST_NOT_OPEN", "The revocation request is not open.")
    if rr["origin"] == "SYSTEM_CASCADE":
        fail(
            "ERR_CASCADE_REVOCATION_NOT_DENIABLE",
            "A cascade-raised revocation may never be denied.",
        )

    rr["state"] = "DENIED"
    rr["denied_at"] = db.now()
    rr["denial_reason"] = denial_reason
    touch(rr)

    cert = db.certificates.get(rr["certificate_id"])
    if cert is not None and cert["revocation_status"] == "REVOCATION_PENDING":
        others = [
            r for r in db.revocation_requests.values()
            if r["certificate_id"] == cert["id"] and r["state"] == "REQUESTED"
        ]
        if not others:
            cert["revocation_status"] = "NONE"
            touch(cert)
            cascade.adjust_pending_revocations(db.subscribers.get(cert["subscriber_id"]), -1)

    return ok(public(rr))
