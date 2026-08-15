"""AtmMachine endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope
from response import ok, ok_list
from services import stamp_new, touch, public, derive_atm_posture
from util import body, required, as_int, as_str, as_enum, pagination_args

bp = Blueprint("atms", __name__)

SERVICE_STATUSES = {"ACTIVE", "OUT_OF_SERVICE"}


def _get_atm_or_404(atm_id):
    atm = DB["atm_machines"].get(atm_id)
    if atm is None:
        raise ApiError("ERR_ATM_NOT_FOUND", 404, "ATM not found")
    return atm


@bp.post("/vault-cash/atm-machines")
def create_atm():
    auth(["CashOperationsAdmin"])
    data = body()
    site_id = as_str(required(data, "site_id"), "site_id")
    if site_id not in DB["vault_sites"]:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    terminal_code = as_str(required(data, "terminal_code"), "terminal_code")
    capacity = as_int(required(data, "cash_capacity_cents"), "cash_capacity_cents")
    opening = as_int(data.get("opening_balance_cents", 0), "opening_balance_cents")

    atm = stamp_new({
        "id": new_id(),
        "site_id": site_id,
        "terminal_code": terminal_code,
        "cash_capacity_cents": capacity,
        "current_balance_cents": opening,
        "cash_posture": "NORMAL",
        "service_status": "ACTIVE",
        "current_forecast_id": None,
    })
    derive_atm_posture(atm)
    DB["atm_machines"][atm["id"]] = atm
    return ok(public(atm), status=201)


@bp.get("/vault-cash/atm-machines")
def list_atms():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    site_id = request.args.get("site_id")
    service_status = request.args.get("service_status")
    rows = list(DB["atm_machines"].values())
    if site_id is not None:
        rows = [a for a in rows if a["site_id"] == site_id]
    if service_status is not None:
        rows = [a for a in rows if a["service_status"] == service_status]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        rows = [a for a in rows if a["site_id"] == principal.home_site_id]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(rows)
    return ok_list([public(a) for a in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/atm-machines/<atmId>")
def get_atm(atmId):
    principal = auth(ALL_ROLES)
    atm = _get_atm_or_404(atmId)
    require_site_scope(principal, atm["site_id"])
    return ok(public(atm))


@bp.post("/vault-cash/atm-machines/<atmId>/set-service-status")
def set_service_status(atmId):
    principal = auth(["AtmAnalyst", "CashOperationsAdmin"])
    atm = _get_atm_or_404(atmId)
    require_site_scope(principal, atm["site_id"])
    data = body()
    target = as_enum(
        required(data, "service_status"), "service_status", SERVICE_STATUSES
    )
    current = atm["service_status"]
    # Parallel axes: toggling requires the opposite current state.
    if target == "OUT_OF_SERVICE":
        if current != "ACTIVE":
            raise ApiError(
                "ERR_ATM_INVALID_STATE", 409, "ATM is not ACTIVE"
            )
    else:  # ACTIVE
        if current != "OUT_OF_SERVICE":
            raise ApiError(
                "ERR_ATM_INVALID_STATE", 409, "ATM is not OUT_OF_SERVICE"
            )
    atm["service_status"] = target
    # cash_posture UNCHANGED (parallel axes)
    touch(atm)
    return ok(public(atm))
