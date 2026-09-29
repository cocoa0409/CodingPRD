"""Certificates, transparency-log submissions and activation (PRD 3.7)."""

from flask import Blueprint

from db import db, make_record, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services.lookup import get_certificate
from validation import CT_OUTCOMES, LOG_OPERATORS, enum_value, opt_str, req_str

bp = Blueprint("certificates", __name__)


@bp.route("/ca/certificates", methods=["GET"])
def list_certificates():
    read_only(ALL_ROLES)
    records = apply_filters(db.certificates.values(), {
        "subscriber_id": "str",
        "profile_id": "str",
        "request_id": "str",
        "ceremony_id": "str",
        "supersedes_certificate_id": "str",
        "lifecycle_status": "str",
        "revocation_status": "str",
    })
    return paginated(sort_records(records))


@bp.route("/ca/certificates/<certificate_id>", methods=["GET"])
def get_one_certificate(certificate_id):
    read_only(ALL_ROLES)
    return ok(public(get_certificate(certificate_id)))


@bp.route("/ca/certificates/<certificate_id>/ct-submissions", methods=["POST"])
def create_ct_submission(certificate_id):
    authenticate(("ISSUANCE_OPERATOR",))
    body = json_body()
    log_operator = req_str(body, "log_operator")
    outcome = req_str(body, "outcome")
    rejection_reason = opt_str(body, "rejection_reason")
    enum_value(log_operator, LOG_OPERATORS, "log_operator")
    enum_value(outcome, CT_OUTCOMES, "outcome")

    cert = get_certificate(certificate_id)

    if (cert["lifecycle_status"] not in ("PREISSUANCE", "ISSUED")
            or cert["revocation_status"] != "NONE"):
        fail("ERR_CERTIFICATE_NOT_REVOCABLE", "The certificate is not in a submittable state.")

    if outcome == "REJECTED" and rejection_reason is None:
        fail(
            "ERR_REJECTION_REASON_MISMATCH",
            "A rejection_reason is required when the outcome is REJECTED.",
        )
    if outcome == "ACCEPTED" and rejection_reason is not None:
        fail(
            "ERR_REJECTION_REASON_MISMATCH",
            "A rejection_reason must be omitted when the outcome is ACCEPTED.",
        )

    already = set(
        s["log_operator"] for s in db.ct_submissions.values()
        if s["certificate_id"] == cert["id"] and s["outcome"] == "ACCEPTED"
    )
    counted = outcome == "ACCEPTED" and log_operator not in already

    record = make_record({
        "certificate_id": cert["id"],
        "log_operator": log_operator,
        "outcome": outcome,
        "rejection_reason": rejection_reason,
        "sct_timestamp": db.now(),
        "counted_toward_sct": counted,
    }, versioned=False)
    db.ct_submissions[record["id"]] = record

    accepted = set(
        s["log_operator"] for s in db.ct_submissions.values()
        if s["certificate_id"] == cert["id"] and s["outcome"] == "ACCEPTED"
    )
    cert["sct_count"] = len(accepted)
    touch(cert)

    return created(public(record))


@bp.route("/ca/certificates/<certificate_id>/ct-submissions", methods=["GET"])
def list_ct_submissions(certificate_id):
    read_only(ALL_ROLES)
    cert = get_certificate(certificate_id)
    records = [s for s in db.ct_submissions.values() if s["certificate_id"] == cert["id"]]
    records = apply_filters(records, {"outcome": "str"})
    return paginated(sort_records(records))


@bp.route("/ca/certificates/<certificate_id>/activate", methods=["POST"])
def activate_certificate(certificate_id):
    authenticate(("ISSUANCE_OPERATOR",))
    cert = get_certificate(certificate_id)
    profile = db.profiles.get(cert["profile_id"])

    if cert["lifecycle_status"] == "EXPIRED":
        fail("ERR_CERTIFICATE_ALREADY_EXPIRED", "The certificate has already expired.")
    if cert["lifecycle_status"] != "PREISSUANCE" or cert["revocation_status"] != "NONE":
        fail("ERR_CERTIFICATE_NOT_PREISSUANCE", "The certificate is not in PREISSUANCE.")
    required = profile["required_sct_count"] if profile is not None else 0
    if cert["sct_count"] < required:
        fail(
            "ERR_INSUFFICIENT_SCTS",
            "The certificate needs %d signed certificate timestamps." % required,
        )

    cert["lifecycle_status"] = "ISSUED"
    cert["activated_at"] = db.now()
    touch(cert)
    return ok(public(cert))
