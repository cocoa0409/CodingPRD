"""Buildings and building budgets."""
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_BUDGET_HAS_ENCUMBRANCES, ERR_BUDGET_ALREADY_EXISTS
from serializers import ser_building, ser_budget, budget_available
from validate import req_str, opt_enum, req_int

bp = Blueprint("buildings", __name__)


def get_building_or_404(bid):
    b = store.buildings.get(bid)
    if b is None:
        raise err(ERR_NOT_FOUND, "building not found")
    return b


def get_budget_or_404(bid):
    b = store.budgets.get(bid)
    if b is None:
        raise err(ERR_NOT_FOUND, "budget not found")
    return b


@bp.post("/pd/buildings")
def create_building():
    require_role("PDCoordinator")
    body = get_body()
    name = req_str(body, "name")
    code = req_str(body, "building_code")
    status = opt_enum(body, "status", ("ACTIVE", "CLOSED"), default="ACTIVE")
    for b in store.buildings.values():
        if b["building_code"] == code:
            raise err(ERR_INVALID_REQUEST, "building_code must be unique")
    b = new_resource()
    b.update({"name": name, "building_code": code, "status": status})
    store.buildings[b["id"]] = b
    return ok(ser_building(b), 201)


@bp.get("/pd/buildings/<bid>")
def get_building(bid):
    require_any_role()
    return ok(ser_building(get_building_or_404(bid)), 200)


@bp.get("/pd/buildings")
def list_buildings():
    require_any_role()
    items = store.buildings.values()
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate([ser_building(b) for b in sort_by_created(items)])


@bp.post("/pd/budgets")
def create_budget():
    require_role("BusinessOfficer")
    body = get_body()
    building_id = req_str(body, "building_id")
    fy = req_int(body, "fiscal_year")
    allocated = req_int(body, "allocated_cents", minimum=0)
    get_building_or_404(building_id)  # body FK existence (step 5)
    for b in store.budgets.values():
        if b["building_id"] == building_id and b["fiscal_year"] == fy:
            raise err(ERR_BUDGET_ALREADY_EXISTS,
                      "budget already exists for (building_id, fiscal_year)")
    b = new_resource()
    b.update({
        "building_id": building_id,
        "fiscal_year": fy,
        "allocated_cents": allocated,
        "status": "DRAFT",
        "encumbered_cents": 0,
        "spent_cents": 0,
    })
    store.budgets[b["id"]] = b
    return ok(ser_budget(b), 201)


@bp.get("/pd/budgets/<bid>")
def get_budget(bid):
    require_any_role()
    return ok(ser_budget(get_budget_or_404(bid)), 200)


@bp.get("/pd/budgets")
def list_budgets():
    require_any_role()
    items = store.budgets.values()
    building_id = request.args.get("building_id")
    if building_id is not None:
        items = [b for b in items if b["building_id"] == building_id]
    fy = request.args.get("fiscal_year")
    if fy is not None:
        try:
            fy_i = int(fy)
            items = [b for b in items if b["fiscal_year"] == fy_i]
        except ValueError:
            items = []
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate([ser_budget(b) for b in sort_by_created(items)])


@bp.post("/pd/budgets/<bid>/open")
def open_budget(bid):
    require_role("BusinessOfficer")
    get_body()
    b = get_budget_or_404(bid)
    if b["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "only a DRAFT budget can be opened")
    b["status"] = "OPEN"
    touch(b)
    return ok(ser_budget(b), 200)


@bp.post("/pd/budgets/<bid>/close")
def close_budget(bid):
    require_role("BusinessOfficer")
    get_body()
    b = get_budget_or_404(bid)
    if b["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "only an OPEN budget can be closed")
    if b["encumbered_cents"] != 0:
        raise err(ERR_BUDGET_HAS_ENCUMBRANCES,
                  "budget has outstanding encumbrances")
    b["status"] = "CLOSED"
    touch(b)
    return ok(ser_budget(b), 200)


@bp.get("/pd/budgets/<bid>/summary")
def budget_summary(bid):
    require_any_role()
    b = get_budget_or_404(bid)
    return ok({
        "allocated_cents": b["allocated_cents"],
        "encumbered_cents": b["encumbered_cents"],
        "spent_cents": b["spent_cents"],
        "available_cents": budget_available(b),
        "cash_basis_available_cents": b["allocated_cents"] - b["spent_cents"],
    }, 200)
