"""ExemptionCertificate + CertificateVersion endpoints (PRD §3.3, §3.4)."""

from flask import Blueprint, request

import db
import services.domain as domain
from errors import ApiError
from middleware import bump, require_role, touch_updated_at
from response import created, ok, ok_list

bp = Blueprint("certificates", __name__)

CO = "ComplianceOfficer"
READ_ROLES = ("TenantAdmin", "ComplianceOfficer", "Auditor")


def _current_version(cert):
    vid = cert.get("current_version_id")
    if not vid:
        return None
    return db.stores["certificate_versions"].get(vid)


def _sod_reviewer_is_uploader(cert):
    """Priority 7: acting X-User-ID vs the current version's uploader."""
    version = _current_version(cert)
    if version is not None and version["uploaded_by_user_id"] == domain_actor():
        raise ApiError(
            "ERR_SOD_REVIEWER_IS_UPLOADER",
            "Reviewer must differ from the uploader of the current certificate version",
            409,
        )


def domain_actor():
    from flask import g
    return g.user_id


@bp.route("/tenants/<tid>/customers/<cid>/certificates", methods=["POST"])
def create_certificate(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cust = domain.get_scoped("customers", cid, tenant["id"])
    body = request.get_json(silent=True) or {}
    # Priority 4: body FKs resolve within the tenant.
    domain.require_reason(tenant["id"], body.get("exemption_reason_code"))
    old_id = body.get("supersedes_certificate_id")
    if old_id is not None:
        old = db.stores["certificates"].get(old_id)
        if not old or old["tenant_id"] != tenant["id"]:
            raise ApiError(
                "ERR_CROSS_TENANT_REFERENCE",
                "supersedes_certificate_id does not resolve to a record of this tenant",
                404,
            )
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "customer_id": cust["id"],
        "ship_to_state": body.get("ship_to_state"),
        "form_type": body.get("form_type"),
        "exemption_reason_code": body.get("exemption_reason_code"),
        "state_registration_number": body.get("state_registration_number"),
        "signed_date": body.get("signed_date"),
        "effective_date": body.get("effective_date"),
        "expiration_date": None,
        "current_version_id": None,
        "superseded_by_certificate_id": None,
        "supersedes_certificate_id": old_id,
        "status": "DRAFT",
        "reviewed_by_user_id": None,
        "review_decision_at": None,
    })
    db.stores["certificates"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/customers/<cid>/certificates", methods=["GET"])
def list_certificates(tid, cid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    cust = domain.get_scoped("customers", cid, tenant["id"])
    items = [c for c in db.stores["certificates"].values() if c["customer_id"] == cust["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    state = request.args.get("ship_to_state")
    if state is not None:
        items = [c for c in items if c["ship_to_state"] == state]
    items.sort(key=lambda c: c["_seq"])
    return ok_list([db.pub(c) for c in items])


@bp.route("/tenants/<tid>/certificates/<cid>", methods=["GET"])
def get_certificate(tid, cid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    return ok(db.pub(cert))


@bp.route("/tenants/<tid>/certificates/<cid>/versions", methods=["POST"])
def upload_version(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    body = request.get_json(silent=True) or {}
    prior = [
        v for v in db.stores["certificate_versions"].values()
        if v["certificate_id"] == cert["id"]
    ]
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "certificate_id": cert["id"],
        "version_index": len(prior) + 1,
        "file_uri": body.get("file_uri"),
        "form_type": body.get("form_type"),
        "signed_date": body.get("signed_date"),
        "effective_date": body.get("effective_date"),
        "uploaded_by_user_id": domain_actor(),
    })
    db.stores["certificate_versions"][rec["id"]] = rec
    cert["current_version_id"] = rec["id"]
    # A new upload against a REJECTED certificate re-opens it to DRAFT.
    if cert["status"] == "REJECTED":
        cert["status"] = "DRAFT"
    bump(cert)
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/certificates/<cid>/versions", methods=["GET"])
def list_versions(tid, cid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    items = [
        v for v in db.stores["certificate_versions"].values()
        if v["certificate_id"] == cert["id"]
    ]
    items.sort(key=lambda v: v["_seq"])
    return ok_list([db.pub(v) for v in items])


@bp.route("/tenants/<tid>/certificates/<cid>/submit", methods=["POST"])
def submit_certificate(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    # Priority 5: state check.
    if cert["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT certificate can be submitted", 409)
    rule = domain.find_rule(tenant["id"], cert["ship_to_state"])
    # Priority 10: form acceptance against the governing jurisdiction rule.
    if not rule or cert["form_type"] not in (rule["accepted_form_types"] or []):
        raise ApiError(
            "ERR_FORM_NOT_ACCEPTED_IN_STATE",
            "Certificate form_type is not accepted by the jurisdiction rule for its ship_to_state",
            422,
        )
    # Priority 11: state registration number when the rule requires one.
    if rule["requires_state_registration_number"] and not cert.get("state_registration_number"):
        raise ApiError(
            "ERR_MISSING_STATE_REGISTRATION",
            "Jurisdiction rule requires a state_registration_number on the certificate",
            422,
        )
    # Priority 25: at least one uploaded version.
    if not cert.get("current_version_id"):
        raise ApiError(
            "ERR_NO_CERT_VERSION",
            "Certificate has no uploaded CertificateVersion",
            422,
        )
    cert["status"] = "SUBMITTED"
    bump(cert)
    touch_updated_at(tenant)
    return ok(db.pub(cert))


@bp.route("/tenants/<tid>/certificates/<cid>/begin_review", methods=["POST"])
def begin_review(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    if cert["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED certificate can enter review", 409)
    _sod_reviewer_is_uploader(cert)
    cert["status"] = "UNDER_REVIEW"
    bump(cert)
    return ok(db.pub(cert))


@bp.route("/tenants/<tid>/certificates/<cid>/approve", methods=["POST"])
def approve_certificate(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    cust = domain.get_scoped("customers", cert["customer_id"], tenant["id"])
    body = request.get_json(silent=True) or {}
    # Priority 5: state check.
    if cert["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an UNDER_REVIEW certificate can be approved", 409)
    # Priority 6: OCC on the parent customer (PRD §2.8).
    expected = body.get("expected_customer_version")
    if expected is not None and expected != cust["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_customer_version does not match the customer's current version", 412)
    # Priority 7: reviewer vs uploader.
    _sod_reviewer_is_uploader(cert)
    version = _current_version(cert)
    # Consistency: current version's form_type must match the declared one.
    if version is not None and version["form_type"] != cert["form_type"]:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Current version's form_type diverges from the certificate's declared form_type",
            409,
        )
    # Priority 12: effective date not in the future (tenant logical clock).
    if version is not None and version.get("effective_date"):
        if domain.parse_day(version["effective_date"]) > domain.current_date(tenant):
            raise ApiError(
                "ERR_EFFECTIVE_DATE_IN_FUTURE",
                "Current version's effective_date is later than today",
                422,
            )
    cert["status"] = "APPROVED"
    cert["reviewed_by_user_id"] = domain_actor()
    cert["review_decision_at"] = db.now_iso()
    cert["expiration_date"] = domain.compute_expiration(cert, tenant)
    bump(cert)
    domain.approval_cascade(cert, tenant, cust)
    return ok(db.pub(cert))


@bp.route("/tenants/<tid>/certificates/<cid>/reject", methods=["POST"])
def reject_certificate(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    if cert["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an UNDER_REVIEW certificate can be rejected", 409)
    _sod_reviewer_is_uploader(cert)
    cert["status"] = "REJECTED"
    cert["reviewed_by_user_id"] = domain_actor()
    cert["review_decision_at"] = db.now_iso()
    bump(cert)
    return ok(db.pub(cert))


@bp.route("/tenants/<tid>/certificates/<cid>/suspend", methods=["POST"])
def suspend_certificate(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    if cert["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED certificate can be suspended", 409)
    cert["status"] = "SUSPENDED"
    bump(cert)
    cust = domain.get_scoped("customers", cert["customer_id"], tenant["id"])
    domain.regate_cascade(tenant, cust)
    return ok(db.pub(cert))


@bp.route("/tenants/<tid>/certificates/<cid>/reinstate", methods=["POST"])
def reinstate_certificate(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    if cert["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a SUSPENDED certificate can be reinstated", 409)
    # Priority 13: reinstate only on or before expiration_date.
    if cert["expiration_date"] is not None:
        if domain.current_date(tenant) > domain.parse_day(cert["expiration_date"]):
            raise ApiError("ERR_CERT_EXPIRED", "Cannot reinstate an expired certificate", 409)
    cert["status"] = "APPROVED"
    bump(cert)
    cust = domain.get_scoped("customers", cert["customer_id"], tenant["id"])
    domain.approval_cascade(cert, tenant, cust)
    return ok(db.pub(cert))


@bp.route("/tenants/<tid>/certificates/<cid>/revoke", methods=["POST"])
def revoke_certificate(tid, cid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    cert = domain.get_scoped("certificates", cid, tenant["id"])
    if cert["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED certificate can be revoked", 409)
    # Priority 22: no non-terminal audit sample may reference the certificate.
    under_audit = any(
        s["certificate_id"] == cert["id"] and s["outcome"] in domain.SAMPLE_NONTERMINAL_OUTCOMES
        for s in db.stores["audit_samples"].values()
    )
    if under_audit:
        raise ApiError("ERR_CERT_UNDER_AUDIT", "Certificate is referenced by a non-terminal audit sample", 409)
    cert["status"] = "REVOKED"
    bump(cert)
    cust = domain.get_scoped("customers", cert["customer_id"], tenant["id"])
    domain.regate_cascade(tenant, cust)
    return ok(db.pub(cert))
