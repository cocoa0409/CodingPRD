from flask import Blueprint, request

from auth import auth
from envelope import created, list_response, success
from errors import err
from services import full_years, lease_buyouts
from store import db, new_entity, now, now_iso, parse_date, pub, touch
from validate import (PACKAGE_GEAR, PACKAGE_TIERS, body, get_or_404,
                      is_date_str, req_date, req_enum, req_int, req_str)

bp = Blueprint("leases", __name__)

READ_ROLES = ("FrontDesk", "Technician", "Manager")


def _junior_age_ok(junior, season_start):
    return full_years(parse_date(junior["date_of_birth"]),
                      parse_date(season_start)) <= 12


def _check_unit_for_lease(unit, package_tier):
    """PRD §3.6 order: tier/gear match first, then rentable status."""
    if (unit["tier"] != "JUNIOR"
            or unit["gear_type"] != PACKAGE_GEAR[package_tier]):
        raise err("ERR_NOT_JUNIOR_TIER",
                  "Leased unit must be tier JUNIOR and match the package gear")
    if unit["status"] != "AVAILABLE":
        raise err("ERR_EQUIPMENT_NOT_AVAILABLE",
                  "Leased unit must be AVAILABLE")


@bp.post("/shop/season-leases")
def create_lease():
    auth("FrontDesk", "Manager")
    b = body()
    junior_id = b.get("junior_customer_id")
    guardian_id = b.get("guardian_customer_id")
    if junior_id is not None:
        get_or_404(db.customers, junior_id, "Junior customer")
    if guardian_id is not None:
        get_or_404(db.customers, guardian_id, "Guardian customer")
    # generic date-range check first: season end must fall after season start
    sd, ed = b.get("season_start_date"), b.get("season_end_date")
    if is_date_str(sd) and is_date_str(ed) and parse_date(ed) <= parse_date(sd):
        raise err("ERR_DATE_RANGE_INVALID",
                  "season_end_date must be after season_start_date")
    junior_id = req_str(b, "junior_customer_id")
    guardian_id = req_str(b, "guardian_customer_id")
    season_start = req_date(b, "season_start_date")
    season_end = req_date(b, "season_end_date")
    package_tier = req_enum(b, "package_tier", PACKAGE_TIERS)
    deposit = req_int(b, "deposit_cents", minimum=0)
    junior = db.customers[junior_id]
    guardian = db.customers[guardian_id]
    if not _junior_age_ok(junior, season_start):
        raise err("ERR_JUNIOR_AGE_EXCEEDED",
                  "Junior is older than 12 full years at season_start_date")
    if (guardian_id == junior_id
            or full_years(parse_date(guardian["date_of_birth"]),
                          parse_date(season_start)) < 18):
        raise err("ERR_GUARDIAN_INVALID",
                  "Guardian must differ from the junior and be at least 18")
    lease = new_entity({
        "junior_customer_id": junior_id,
        "guardian_customer_id": guardian_id,
        "season_start_date": season_start,
        "season_end_date": season_end,
        "package_tier": package_tier,
        "deposit_cents": deposit,
        "equipment_item_id": None,
        "status": "DRAFT",
        "swap_count": 0,
        "activated_at": None,
        "buyout_price_straight_line_cents": None,
        "buyout_price_usage_cents": None,
    })
    db.season_leases[lease["id"]] = lease
    return created(pub(lease))


@bp.get("/shop/season-leases/<lid>")
def get_lease(lid):
    auth(*READ_ROLES)
    lease = get_or_404(db.season_leases, lid, "Season lease")
    return success(pub(lease))


@bp.get("/shop/season-leases")
def list_leases():
    auth(*READ_ROLES)
    items = list(db.season_leases.values())
    junior = request.args.get("junior_customer_id")
    guardian = request.args.get("guardian_customer_id")
    equipment = request.args.get("equipment_item_id")
    status = request.args.get("status")
    if junior is not None:
        items = [l for l in items if l["junior_customer_id"] == junior]
    if guardian is not None:
        items = [l for l in items if l["guardian_customer_id"] == guardian]
    if equipment is not None:
        items = [l for l in items if l["equipment_item_id"] == equipment]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(items)


@bp.post("/shop/season-leases/<lid>/activate")
def activate_lease(lid):
    auth("FrontDesk", "Manager")
    lease = get_or_404(db.season_leases, lid, "Season lease")
    unit_id = body().get("equipment_item_id")
    if unit_id is None:
        raise err("ERR_INVALID_REQUEST", "equipment_item_id is required")
    unit = get_or_404(db.equipment_items, unit_id, "Equipment item")
    if lease["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT lease can be activated")
    _check_unit_for_lease(unit, lease["package_tier"])
    junior = db.customers[lease["junior_customer_id"]]
    if not _junior_age_ok(junior, lease["season_start_date"]):
        raise err("ERR_JUNIOR_AGE_EXCEEDED",
                  "Junior is older than 12 full years at season_start_date")
    unit["status"] = "OUT"
    touch(unit)
    lease["equipment_item_id"] = unit["id"]
    lease["activated_at"] = now_iso()
    lease["status"] = "ACTIVE"
    touch(lease)
    return success(pub(lease))


@bp.post("/shop/season-leases/<lid>/swap")
def swap_lease(lid):
    auth("FrontDesk", "Manager")
    lease = get_or_404(db.season_leases, lid, "Season lease")
    b = body()
    new_id_ = b.get("new_equipment_item_id")
    if new_id_ is None:
        raise err("ERR_INVALID_REQUEST", "new_equipment_item_id is required")
    expected = b.get("expected_season_lease_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST",
                  "expected_season_lease_version is required")
    unit = get_or_404(db.equipment_items, new_id_, "Equipment item")
    # OCC gate (priority 5), then state (6), then the swap limit
    if expected != lease["version"]:
        raise err("ERR_STALE_VERSION",
                  "The lease version has advanced since the observed state")
    if lease["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE lease can be swapped")
    if lease["swap_count"] >= 2:
        raise err("ERR_SWAP_LIMIT_EXCEEDED",
                  "swap_count has reached the hard limit of 2")
    _check_unit_for_lease(unit, lease["package_tier"])
    old = db.equipment_items[lease["equipment_item_id"]]
    old["status"] = "IN_SERVICE"  # old unit goes straight to the workshop
    touch(old)
    unit["status"] = "OUT"
    touch(unit)
    lease["equipment_item_id"] = unit["id"]
    lease["swap_count"] += 1
    touch(lease)
    return success(pub(lease))


@bp.post("/shop/season-leases/<lid>/close")
def close_lease(lid):
    auth("FrontDesk", "Manager")
    lease = get_or_404(db.season_leases, lid, "Season lease")
    if lease["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE",
                  "Only an ACTIVE or SUSPENDED lease can be closed")
    unit = db.equipment_items[lease["equipment_item_id"]]
    straight, usage, elapsed = lease_buyouts(lease, unit)
    unit["status"] = "AWAITING_INSPECTION"
    unit["accrued_rental_days"] += elapsed
    touch(unit)
    lease["buyout_price_straight_line_cents"] = straight
    lease["buyout_price_usage_cents"] = usage
    lease["status"] = "SETTLED"
    touch(lease)
    return success(pub(lease))


@bp.post("/shop/season-leases/<lid>/reinstate")
def reinstate_lease(lid):
    auth("Manager")
    lease = get_or_404(db.season_leases, lid, "Season lease")
    if lease["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Only a SUSPENDED lease can be reinstated")
    junior = db.customers[lease["junior_customer_id"]]
    if junior["standing"] == "BARRED":
        raise err("ERR_INVALID_STATE",
                  "Cannot reinstate while the junior's standing is BARRED")
    lease["status"] = "ACTIVE"
    touch(lease)
    return success(pub(lease))
