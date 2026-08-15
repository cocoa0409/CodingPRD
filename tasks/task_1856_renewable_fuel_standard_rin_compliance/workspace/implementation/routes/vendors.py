"""Vendor endpoints: onboard, get, list, diligence."""
from flask import Blueprint, request

import db
from errors import invalid_request, not_found, reference_not_found, invalid_state
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import vendor_view
from services import cascade

bp = Blueprint("vendors", __name__)


def _get_vendor(vendor_id):
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise not_found("Vendor not found")
    return vendor


@bp.route("/rfs/vendors", methods=["POST"])
def create_vendor():
    require_roles("Trader")
    body = json_body()
    account_id = body.get("account_id")
    vendor_name = body.get("vendor_name")
    qap_audited = body.get("qap_audited")

    if account_id is None:
        raise invalid_request("account_id is required")
    if not vendor_name or not isinstance(vendor_name, str):
        raise invalid_request("vendor_name is required")
    if not isinstance(qap_audited, bool):
        raise invalid_request("qap_audited must be a boolean")

    if db.compliance_accounts.get(account_id) is None:
        raise reference_not_found("Referenced account does not exist")

    now = db.now_utc()
    vendor = {
        "id": db.new_id(),
        "account_id": account_id,
        "vendor_name": vendor_name,
        "qap_audited": qap_audited,
        "diligence_status": "UNVETTED",
        "last_diligence_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.vendors[vendor["id"]] = vendor
    return ok_object(vendor_view(vendor), status=201)


@bp.route("/rfs/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    return ok_object(vendor_view(_get_vendor(vendor_id)))


@bp.route("/rfs/vendors", methods=["GET"])
def list_vendors():
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    rows = list(db.vendors.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([vendor_view(r) for r in page], limit, offset, total)


# Declared diligence transitions: (from_status, outcome) allowed
_DILIGENCE_TRANSITIONS = {
    ("UNVETTED", "APPROVED"),
    ("UNVETTED", "REJECTED"),
    ("REJECTED", "APPROVED"),
    ("APPROVED", "REVOKED"),
}


@bp.route("/rfs/vendors/<vendor_id>/diligence", methods=["POST"])
def diligence(vendor_id):
    require_roles("ComplianceManager")
    vendor = _get_vendor(vendor_id)
    body = json_body()
    outcome = body.get("outcome")
    if outcome not in ("APPROVED", "REJECTED", "REVOKED"):
        raise invalid_request("outcome must be APPROVED, REJECTED, or REVOKED")

    if (vendor["diligence_status"], outcome) not in _DILIGENCE_TRANSITIONS:
        raise invalid_state(f"Cannot apply outcome {outcome} from status {vendor['diligence_status']}")

    now = db.now_utc()
    vendor["diligence_status"] = outcome
    vendor["last_diligence_at"] = now
    vendor["version"] += 1
    vendor["updated_at"] = now

    if outcome == "REVOKED":
        cascade.revoke_vendor_cascade(vendor)

    return ok_object(vendor_view(vendor))
