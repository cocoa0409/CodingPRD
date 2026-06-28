"""Additional-insured certificate routes (PRD §3.8; scaffold §1.5)."""
from flask import Blueprint

from db import db, new_common, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_success
from serializers import public
from services.lookups import (
    children_by_policy,
    get_certificate,
    get_policy,
)
from validators import get_body, get_pagination, query_str, req_str

bp = Blueprint("certificates", __name__)


def _paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return [public(x) for x in page], limit, offset, total


@bp.route("/policies/<policy_id>/certificates", methods=["POST"])
def request_certificate(policy_id):
    _, role = get_user_context()
    require_role(role, {"Policyholder", "UnderwritingAgent"})
    get_policy(policy_id)
    body = get_body()

    vendor_id = req_str(body, "vendor_id")
    additional_insured_name = req_str(body, "additional_insured_name")

    if vendor_id not in db.vendors:
        raise err("ERR_REFERENCE_NOT_FOUND", "vendor_id does not resolve")

    cert = new_common()
    cert.update({
        "policy_id": policy_id,
        "vendor_id": vendor_id,
        "additional_insured_name": additional_insured_name,
        "certificate_number": None,
        "status": "REQUESTED",
    })
    db.certificates[cert["id"]] = cert
    return success(public(cert), status=201)


@bp.route("/policies/<policy_id>/certificates", methods=["GET"])
def list_certificates(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    f_status = query_str("status")
    items = children_by_policy(db.certificates, policy_id)
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)


@bp.route("/policies/<policy_id>/certificates/<certificate_id>/issue", methods=["POST"])
def issue_certificate(policy_id, certificate_id):
    _, role = get_user_context()
    require_role(role, {"UnderwritingAgent"})
    policy = get_policy(policy_id)
    cert = get_certificate(policy_id, certificate_id)

    if cert["status"] != "REQUESTED":
        raise err("ERR_CERTIFICATE_NOT_REQUESTED", "certificate is not REQUESTED")
    if policy["lifecycle_status"] not in ("BOUND", "IN_FORCE"):
        raise err("ERR_POLICY_NOT_BOUND", "policy is not BOUND/IN_FORCE")

    has_active_liability = False
    for c in children_by_policy(db.coverages, policy_id):
        if c["status"] == "ACTIVE":
            product = db.coverage_products[c["coverage_product_id"]]
            if product["coverage_type"] == "LIABILITY":
                has_active_liability = True
                break
    if not has_active_liability:
        raise err("ERR_NO_LIABILITY_COVERAGE", "policy has no ACTIVE LIABILITY coverage")

    cert["certificate_number"] = "CERT-" + cert["id"].replace("-", "")[:12].upper()
    cert["status"] = "ISSUED"
    touch(cert)
    return success(public(cert), status=200)


@bp.route("/policies/<policy_id>/certificates/<certificate_id>/revoke", methods=["POST"])
def revoke_certificate(policy_id, certificate_id):
    _, role = get_user_context()
    require_role(role, {"UnderwritingAgent"})
    get_policy(policy_id)
    cert = get_certificate(policy_id, certificate_id)
    if cert["status"] != "ISSUED":
        raise err("ERR_CERTIFICATE_NOT_ISSUED", "certificate is not ISSUED")
    cert["status"] = "REVOKED"
    touch(cert)
    return success(public(cert), status=200)
