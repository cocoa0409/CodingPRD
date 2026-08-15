"""ScopeGap endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    GAP_CATEGORIES,
    RESOLUTION_KINDS,
    gaps_of,
    get_gap,
    get_package,
    ser_gap,
    sorted_created,
    stamp,
    touch,
)
from util import as_enum, as_int, as_str, body, pagination_args, required

bp = Blueprint("gaps", __name__)


@bp.post("/trade-packages/<pkg_id>/gaps")
def create_gap(pkg_id):
    auth(["BuyoutLead", "OperationsManager"])
    pkg = get_package(pkg_id)
    data = body()
    category = as_enum(required(data, "category"), "category", GAP_CATEGORIES)
    description = as_str(required(data, "description"), "description")
    estimated_impact_cents = data.get("estimated_impact_cents")
    if estimated_impact_cents is not None:
        as_int(estimated_impact_cents, "estimated_impact_cents")
    if pkg["status"] not in ("PUBLISHED", "UNDER_LEVELING"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            409,
            "Package not in PUBLISHED or UNDER_LEVELING",
        )
    rec = {
        "id": new_id(),
        "trade_package_id": pkg["id"],
        "category": category,
        "description": description,
        "estimated_impact_cents": estimated_impact_cents,
        "resolution_kind": None,
        "priced_amount_cents": None,
        "waived_by_role": None,
        "status": "OPEN",
    }
    stamp(rec)
    DB["scope_gaps"][rec["id"]] = rec
    return ok(ser_gap(rec), status=201)


@bp.get("/trade-packages/<pkg_id>/gaps")
def list_gaps(pkg_id):
    auth(ALL_ROLES)
    pkg = get_package(pkg_id)
    limit, offset = pagination_args()
    status = request.args.get("status")
    category = request.args.get("category")
    items = sorted_created(gaps_of(pkg))
    if status is not None:
        items = [g for g in items if g["status"] == status]
    if category is not None:
        items = [g for g in items if g["category"] == category]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_gap(g) for g in page], total, limit, offset)


@bp.get("/gaps/<gap_id>")
def get_one_gap(gap_id):
    auth(ALL_ROLES)
    return ok(ser_gap(get_gap(gap_id)))


@bp.post("/gaps/<gap_id>/resolve")
def resolve_gap(gap_id):
    auth(["BuyoutLead", "OperationsManager", "VicePresident"])
    gap = get_gap(gap_id)
    data = body()
    resolution_kind = as_enum(
        required(data, "resolution_kind"), "resolution_kind", RESOLUTION_KINDS
    )
    priced_amount_cents = data.get("priced_amount_cents")
    if priced_amount_cents is not None:
        as_int(priced_amount_cents, "priced_amount_cents")
    waived_by_role = data.get("waived_by_role")
    if waived_by_role is not None:
        as_str(waived_by_role, "waived_by_role")
    if gap["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ScopeGap is not OPEN"
        )
    if resolution_kind == "ALLOWANCE_WITH_QUALIFICATION" and waived_by_role not in (
        "OperationsManager",
        "VicePresident",
    ):
        raise ApiError(
            "ERR_VALIDATION",
            422,
            "ALLOWANCE_WITH_QUALIFICATION requires waived_by_role in {OperationsManager, VicePresident}",
        )
    if resolution_kind == "CONTINGENCY_DRAW" and priced_amount_cents is None:
        raise ApiError(
            "ERR_VALIDATION",
            422,
            "CONTINGENCY_DRAW requires priced_amount_cents",
        )
    gap["resolution_kind"] = resolution_kind
    if priced_amount_cents is not None:
        gap["priced_amount_cents"] = priced_amount_cents
    if waived_by_role is not None:
        gap["waived_by_role"] = waived_by_role
    gap["status"] = "RESOLVED"
    touch(gap)
    return ok(ser_gap(gap))


@bp.post("/gaps/<gap_id>/defer")
def defer_gap(gap_id):
    auth(["BuyoutLead"])
    gap = get_gap(gap_id)
    if gap["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ScopeGap is not OPEN"
        )
    if gap["category"] == "LIFE_SAFETY":
        raise ApiError(
            "ERR_UNRESOLVED_LIFE_SAFETY_GAP",
            409,
            "LIFE_SAFETY gaps cannot be deferred",
        )
    gap["status"] = "DEFERRED"
    touch(gap)
    return ok(ser_gap(gap))


@bp.post("/gaps/<gap_id>/reopen")
def reopen_gap(gap_id):
    auth(["BuyoutLead"])
    gap = get_gap(gap_id)
    if gap["status"] != "DEFERRED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ScopeGap is not DEFERRED"
        )
    gap["status"] = "OPEN"
    touch(gap)
    return ok(ser_gap(gap))
