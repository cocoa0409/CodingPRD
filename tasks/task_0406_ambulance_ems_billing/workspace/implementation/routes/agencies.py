"""Agency + AgencyStaff endpoints (PRD §3.1)."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_ENUM, err
from middleware import authenticate, optional_authenticate, require_role
from response import success
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    paginate,
    parse_pagination,
    require_fields,
    resolve_fk,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("agencies", __name__)

STAFF_ROLES = {"Dispatcher", "Coder", "Biller", "ComplianceOfficer"}


# ---- Agency ----
@bp.route("/agencies", methods=["POST"])
def create_agency():
    # bootstrap-open: anonymous allowed; if auth supplied it must be valid.
    optional_authenticate()
    body = get_json_body()
    require_fields(body, ["name", "npi", "state_code"])
    rec = {
        "name": body["name"],
        "npi": body["npi"],
        "state_code": body["state_code"],
        "base_state_is_no_surprises": bool(body.get("base_state_is_no_surprises", False)),
        "charity_fpl_threshold_pct": (
            body["charity_fpl_threshold_pct"]
            if body.get("charity_fpl_threshold_pct") is not None
            else 200
        ),
        "status": "ACTIVE",
    }
    init_common(rec)
    store.agencies[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/agencies/<agency_id>", methods=["GET"])
def get_agency(agency_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher", "Coder", "Biller", "ComplianceOfficer"])
    rec = get_or_404(store.agencies, agency_id)
    return success(serialize(rec), 200)


@bp.route("/agencies/<agency_id>/staff", methods=["GET"])
def list_agency_staff(agency_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "ComplianceOfficer", "Biller"])
    get_or_404(store.agencies, agency_id)
    limit, offset = parse_pagination()
    items = [s for s in store.agency_staff.values() if s["agency_id"] == agency_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)


# ---- AgencyStaff ----
@bp.route("/staff", methods=["POST"])
def create_staff():
    principal = authenticate()
    require_role(principal, ["BillingAdmin"])
    body = get_json_body()
    # priority 4: body FK existence (only when the FK field is present).
    if body.get("agency_id") is not None:
        resolve_fk(store.agencies, body["agency_id"])
    # priority 5: required fields
    require_fields(body, ["agency_id", "full_name", "role"])
    # priority 6: enum validity
    if body["role"] not in STAFF_ROLES:
        raise err(ERR_INVALID_ENUM, "Invalid staff role")
    rec = {
        "agency_id": body["agency_id"],
        "full_name": body["full_name"],
        "role": body["role"],
        "pcs_signature_authority": bool(body.get("pcs_signature_authority", False)),
        "status": "ACTIVE",
    }
    init_common(rec)
    store.agency_staff[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/staff/<staff_id>", methods=["GET"])
def get_staff(staff_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "ComplianceOfficer", "Biller"])
    rec = get_or_404(store.agency_staff, staff_id)
    return success(serialize(rec), 200)
