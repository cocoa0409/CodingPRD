"""Partner agency endpoints (PRD §3.1)."""

from flask import request

from db import store, base_fields, touch
from errors import (ERR_NOT_FOUND, ERR_DUPLICATE_CODE, ERR_VALIDATION,
                    raise_err)
from middleware import authenticate, require_role, forbid
from response import success_object, get_body, paginate
from serialize import agency_json, line_json
from validate import req_str, req_int, opt_int, opt_str
from . import make_blueprint

bp = make_blueprint("agencies")

READ_ROLES = ["BankAdmin", "FinanceManager", "WarehouseManager",
              "AgencyCoordinator", "PrivacyOfficer", "VolunteerCoordinator"]
GET_ONE_ROLES = ["BankAdmin", "FinanceManager", "WarehouseManager", "AgencyCoordinator"]


def _get_agency_or_404(agency_id):
    a = store.partner_agencies.get(agency_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Partner agency not found.")
    return a


def _coordinator_self_check(uid, role, agency_id):
    """AgencyCoordinator path-id scoping: the id IS the agency id (PRD §2.1)."""
    if role == "AgencyCoordinator" and uid != agency_id:
        forbid()


@bp.route("/partner-agencies", methods=["POST"])
def create_agency():
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    body = get_body()
    # Uniqueness (pipeline category 6) precedes full body validation (10).
    code = body.get("agency_code")
    if isinstance(code, str) and any(a["agency_code"] == code
                                     for a in store.partner_agencies.values()):
        raise_err(ERR_DUPLICATE_CODE, "agency_code is already in use.")
    name = req_str(body, "name")
    code = req_str(body, "agency_code")
    email = req_str(body, "contact_email")
    csm = req_int(body, "children_served_monthly", minimum=0)
    cap = req_int(body, "storage_capacity_units", minimum=0)
    a = base_fields()
    a.update({
        "name": name, "agency_code": code, "contact_email": email,
        "children_served_monthly": csm, "storage_capacity_units": cap,
        "status": "ACTIVE",
    })
    store.partner_agencies[a["id"]] = a
    return success_object(agency_json(a), status=201)


@bp.route("/partner-agencies", methods=["GET"])
def list_agencies():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    status = request.args.get("status")
    items = [a for a in store.partner_agencies.values()
             if status is None or a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    return paginate([agency_json(a) for a in items])


@bp.route("/partner-agencies/<agency_id>", methods=["GET"])
def get_agency(agency_id):
    uid, role = authenticate()
    require_role(role, GET_ONE_ROLES)
    _coordinator_self_check(uid, role, agency_id)
    return success_object(agency_json(_get_agency_or_404(agency_id)))


@bp.route("/partner-agencies/<agency_id>", methods=["PATCH"])
def patch_agency(agency_id):
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    a = _get_agency_or_404(agency_id)
    body = get_body()
    csm = opt_int(body, "children_served_monthly", minimum=0)
    cap = opt_int(body, "storage_capacity_units", minimum=0)
    email = opt_str(body, "contact_email")
    if csm is not None:
        a["children_served_monthly"] = csm
    if cap is not None:
        a["storage_capacity_units"] = cap
    if email is not None:
        a["contact_email"] = email
    touch(a)
    return success_object(agency_json(a))


@bp.route("/partner-agencies/<agency_id>/suspend", methods=["POST"])
def suspend_agency(agency_id):
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    a = _get_agency_or_404(agency_id)
    if a["status"] != "ACTIVE":
        raise_err(ERR_VALIDATION, "Only an ACTIVE agency can be suspended.")
    # Cascade: release every unfulfilled allocation line back to the pool
    # (PRD §3.1). Inventory version is NOT advanced by suspension (§2.5 lists
    # the stock mutations that advance it; suspension is not among them).
    inv = store.inventory
    for ln in store.allocation_lines.values():
        if ln["agency_id"] != a["id"]:
            continue
        if ln["status"] in ("ALLOCATED", "PARTIALLY_FULFILLED"):
            released = ln["allocated_units"] - ln["fulfilled_units"]
            ln["released_units"] = released
            ln["status"] = "RELEASED"
            touch(ln)
            if inv is not None:
                inv["sizes"][ln["size_code"]]["reserved_units"] -= released
    a["status"] = "SUSPENDED"
    touch(a)
    return success_object(agency_json(a))


@bp.route("/partner-agencies/<agency_id>/allocation-lines", methods=["GET"])
def agency_allocation_lines(agency_id):
    uid, role = authenticate()
    require_role(role, ["BankAdmin", "AgencyCoordinator"])
    _coordinator_self_check(uid, role, agency_id)
    _get_agency_or_404(agency_id)
    status = request.args.get("status")
    items = [ln for ln in store.allocation_lines.values()
             if ln["agency_id"] == agency_id
             and (status is None or ln["status"] == status)]
    items.sort(key=lambda ln: ln["created_at"])
    return paginate([line_json(ln) for ln in items])
