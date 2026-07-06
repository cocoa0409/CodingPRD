"""Prior Authorizations: revision cycle + adjudication (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object, ok_array
from validation import get_json_body, lookup, parse_pagination, paginate
from clock import parse_iso, add_days, to_iso_z
from services import touch
from serializers import prior_auth_out, supplier_accreditation_status

bp = Blueprint("prior_auths", __name__)


def _bubble_order(order):
    """CASCADE on APPROVED: AUTH_PENDING->FABRICATION when a milestone exists."""
    if order["status"] != "AUTH_PENDING":
        return
    has_milestone = any(m["device_order_id"] == order["id"] for m in db.fabrication_milestones.values())
    if has_milestone:
        order["status"] = "FABRICATION"
        touch(order)


@bp.route("/op/prior-auths/<rid>", methods=["GET"])
def get_prior_auth(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer", "BillingSpecialist"})
    auth = lookup(db.prior_auths, rid)
    return ok_object(prior_auth_out(auth), 200)


@bp.route("/op/prior-auths", methods=["GET"])
def list_prior_auths():
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer", "BillingSpecialist"})
    limit, offset = parse_pagination()

    items = list(db.prior_auths.values())
    device_order_id = request.args.get("device_order_id")
    if device_order_id is not None:
        items = [a for a in items if a["device_order_id"] == device_order_id]
    page, total = paginate(items, limit, offset)
    return ok_array([prior_auth_out(a) for a in page], limit, offset, total, 200)


@bp.route("/op/prior-auths/<rid>/pend", methods=["POST"])
def pend(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    auth = lookup(db.prior_auths, rid)
    if auth["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "PriorAuth is not in SUBMITTED.")
    auth["status"] = "PENDED"
    touch(auth)
    return ok_object(prior_auth_out(auth), 200)


@bp.route("/op/prior-auths/<rid>/resubmit", methods=["POST"])
def resubmit(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    auth = lookup(db.prior_auths, rid)
    body = get_json_body()

    # State legality (priority 5): resubmit defined only from PENDED.
    if auth["status"] != "PENDED":
        raise ApiError("ERR_INVALID_STATE", "PriorAuth is not in PENDED.")

    # OCC (priority 15): expected_prior_auth_version must match.
    expected = body.get("expected_prior_auth_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_prior_auth_version is required and must be an integer.")
    if expected != auth["version"]:
        raise ApiError("ERR_STALE_AUTH_VERSION", "expected_prior_auth_version does not match current version.")

    auth["status"] = "SUBMITTED"
    auth["submission_round"] = auth["submission_round"] + 1
    clock = parse_iso(db.current_utc)
    auth["decision_deadline"] = to_iso_z(add_days(clock, 14))
    touch(auth)
    return ok_object(prior_auth_out(auth), 200)


@bp.route("/op/prior-auths/<rid>/approve", methods=["POST"])
def approve(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    auth = lookup(db.prior_auths, rid)

    if auth["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "PriorAuth is not in SUBMITTED.")

    order = db.device_orders.get(auth["device_order_id"])
    supplier = db.suppliers.get(order["supplier_id"]) if order else None
    status = supplier_accreditation_status(supplier, db.current_utc) if supplier else "UNACCREDITED"
    if status != "ACCREDITED":
        raise ApiError("ERR_SUPPLIER_NOT_ACCREDITED", "Covering order's supplier is not ACCREDITED.")

    auth["status"] = "APPROVED"
    auth["auth_number"] = "AUTH-" + auth["id"][:8].upper()
    touch(auth)

    # CASCADE: bubble order AUTH_PENDING -> FABRICATION (if milestones exist).
    if order is not None:
        _bubble_order(order)

    return ok_object(prior_auth_out(auth), 200)


@bp.route("/op/prior-auths/<rid>/deny", methods=["POST"])
def deny(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    auth = lookup(db.prior_auths, rid)
    if auth["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "PriorAuth is not in SUBMITTED.")
    auth["status"] = "DENIED"
    touch(auth)
    return ok_object(prior_auth_out(auth), 200)
