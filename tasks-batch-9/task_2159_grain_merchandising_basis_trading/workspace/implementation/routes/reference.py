"""Trading desks, elevators, discount schedules, risk limits, rail fleets, clock."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from aggregates import recompute_desk
from auth import ALL_ROLES, endpoint
from calc import CONTRACT_UNIT_BUSHELS, side_sign
from errors import fail
from response import ok, paged
from serializers import (desk_out, fleet_out, location_out, risk_limit_out,
                         schedule_out)
from store import (D, apply_changes, db, fmt_ts, new_row, r0, r2, r4, sort_rows,
                   parse_ts, touch)
from validate import (COMMODITIES, TIER_DIRECTIONS, TIER_FACTORS, body,
                      guard_payload, lookup, lookup_fk, opt_bool, opt_num,
                      req_enum, req_int, req_num, req_str, req_ts)

bp = Blueprint("reference", __name__)


# --------------------------------------------------------------------------
# TradingDesk
# --------------------------------------------------------------------------
@bp.post("/grain/trading-desks")
@endpoint(["DeskAdmin"])
def create_desk(actor):
    payload = guard_payload(body())
    desk_code = req_str(payload, "desk_code")
    name = req_str(payload, "name")
    credit_line = req_num(payload, "credit_line_usd", minimum=0, exclusive_min=True)
    for existing in db.trading_desks.values():
        if existing["desk_code"] == desk_code:
            fail("ERR_INVALID_REQUEST", "desk_code must be unique across all desks.")

    row = new_row()
    row.update({
        "desk_code": desk_code,
        "name": name,
        "credit_line_usd": r2(credit_line),
        "margin_requirement_usd": Decimal("0.00"),
        "open_margin_call_usd": Decimal("0.00"),
        "credit_utilization": Decimal("0.0000"),
        "available_credit_usd": r2(credit_line),
        "posture": "NORMAL",
        "committed_hedge_lots": 0,
        "open_bushel_commitment": Decimal("0.00"),
        "unpriced_bushels": Decimal("0.00"),
        "realized_hedge_pnl_usd": Decimal("0.00"),
    })
    db.trading_desks[row["id"]] = row
    return ok(desk_out(row), 201)


@bp.get("/grain/trading-desks")
@endpoint(ALL_ROLES)
def list_desks(actor):
    return paged(sort_rows(db.trading_desks.values()), desk_out)


@bp.get("/grain/trading-desks/<desk_id>")
@endpoint(ALL_ROLES)
def read_desk(actor, desk_id):
    return ok(desk_out(lookup("trading_desks", desk_id)))


@bp.get("/grain/trading-desks/<desk_id>/position-report")
@endpoint(["DeskAdmin", "Merchandiser", "FuturesTrader", "RiskOfficer"])
def position_report(actor, desk_id):
    desk = lookup("trading_desks", desk_id)
    commodity = request.args.get("commodity_code")

    contracts = [c for c in db.purchase_contracts.values()
                 if c["desk_id"] == desk["id"] and c["status"] == "ACTIVE"]
    positions = [p for p in db.hedge_positions.values()
                 if p["desk_id"] == desk["id"]
                 and p["status"] in ("OPEN", "MARGIN_CALL")]
    if commodity:
        contracts = [c for c in contracts if c["commodity_code"] == commodity]
        positions = [p for p in positions if p["commodity_code"] == commodity]

    cash_long = r2(sum((D(c["bushels"]) - D(c["delivered_bushels"])
                        for c in contracts), Decimal(0)))
    unpriced = r2(sum((D(c["unpriced_bushels"]) for c in contracts), Decimal(0)))
    net_lots = int(sum((side_sign(p["side"]) * D(p["lots_open"])
                        for p in positions), Decimal(0)))
    required_lots = r0(cash_long / CONTRACT_UNIT_BUSHELS)
    if required_lots == 0:
        coverage = Decimal("0.0000")
    else:
        coverage = r4(abs(D(net_lots)) / D(required_lots))

    limit_row = None
    if commodity:
        for row in db.risk_limits.values():
            if row["desk_id"] == desk["id"] and row["commodity_code"] == commodity \
                    and row["status"] == "ACTIVE":
                limit_row = row
                break

    if limit_row is None:
        risk_limit_status = "NO_LIMIT"
    else:
        net_short = abs(net_lots) if net_lots < 0 else 0
        breach = (unpriced > D(limit_row["max_unpriced_bushels"])
                  or net_short > limit_row["max_net_short_lots"])
        risk_limit_status = "BREACH" if breach else "WITHIN"

    return ok({
        "desk_id": desk["id"],
        "commodity_code": commodity if commodity else None,
        "cash_long_bushels": float(cash_long),
        "unpriced_bushels": float(unpriced),
        "net_futures_lots": net_lots,
        "required_hedge_lots": required_lots,
        "hedge_coverage_ratio": float(coverage),
        "margin_requirement_usd": float(D(desk["margin_requirement_usd"])),
        "open_margin_call_usd": float(D(desk["open_margin_call_usd"])),
        "credit_utilization": float(D(desk["credit_utilization"])),
        "posture": desk["posture"],
        "risk_limit_status": risk_limit_status,
    })


# --------------------------------------------------------------------------
# ElevatorLocation
# --------------------------------------------------------------------------
@bp.post("/grain/elevator-locations")
@endpoint(["DeskAdmin"])
def create_location(actor):
    payload = guard_payload(body())
    desk = lookup_fk(payload, "desk_id", "trading_desks")
    if desk is None:
        fail("ERR_INVALID_REQUEST")
    location_code = req_str(payload, "location_code")
    name = req_str(payload, "name")
    capacity = req_int(payload, "intake_capacity_bushels", minimum=0,
                       exclusive_min=True)
    rail_served = opt_bool(payload, "rail_served", False)
    for existing in db.elevator_locations.values():
        if existing["location_code"] == location_code:
            fail("ERR_INVALID_REQUEST",
                 "location_code must be unique across all elevators.")

    row = new_row()
    row.update({
        "desk_id": desk["id"],
        "location_code": location_code,
        "name": name,
        "intake_capacity_bushels": capacity,
        "rail_served": rail_served,
        "committed_intake_bushels": Decimal("0.00"),
    })
    db.elevator_locations[row["id"]] = row
    return ok(location_out(row), 201)


@bp.get("/grain/elevator-locations")
@endpoint(ALL_ROLES)
def list_locations(actor):
    rows = list(db.elevator_locations.values())
    desk_id = request.args.get("desk_id")
    if desk_id:
        rows = [r for r in rows if r["desk_id"] == desk_id]
    return paged(sort_rows(rows), location_out)


@bp.get("/grain/elevator-locations/<location_id>")
@endpoint(ALL_ROLES)
def read_location(actor, location_id):
    return ok(location_out(lookup("elevator_locations", location_id)))


# --------------------------------------------------------------------------
# DiscountSchedule
# --------------------------------------------------------------------------
def _parse_tiers(payload):
    tiers = payload.get("tiers")
    if not isinstance(tiers, list) or len(tiers) == 0:
        fail("ERR_INVALID_REQUEST")
    seen = set()
    parsed = []
    for tier in tiers:
        if not isinstance(tier, dict):
            fail("ERR_INVALID_REQUEST")
        factor = req_enum(tier, "factor", TIER_FACTORS)
        if factor in seen:
            fail("ERR_INVALID_REQUEST", "at most one tier row per factor.")
        seen.add(factor)
        parsed.append({
            "factor": factor,
            "direction": req_enum(tier, "direction", TIER_DIRECTIONS),
            "threshold_value": req_num(tier, "threshold_value"),
            "unit_step": req_num(tier, "unit_step", minimum=0, exclusive_min=True),
            "rate_cents_per_bushel_per_step":
                req_num(tier, "rate_cents_per_bushel_per_step"),
        })
    return parsed


@bp.post("/grain/discount-schedules")
@endpoint(["DeskAdmin"])
def create_schedule(actor):
    payload = guard_payload(body())
    commodity = req_enum(payload, "commodity_code", COMMODITIES)
    effective_from = req_ts(payload, "effective_from")
    tiers = _parse_tiers(payload)
    moisture_standard = opt_num(payload, "moisture_standard_pct", D("15.0"))
    shrink_factor = opt_num(payload, "shrink_factor_pct_per_point", D("1.18"))

    row = new_row()
    row.update({
        "commodity_code": commodity,
        "effective_from": effective_from,
        "moisture_standard_pct": moisture_standard,
        "shrink_factor_pct_per_point": shrink_factor,
        "tiers": tiers,
        "status": "DRAFT",
    })
    db.discount_schedules[row["id"]] = row
    return ok(schedule_out(row), 201)


@bp.post("/grain/discount-schedules/<schedule_id>/activate")
@endpoint(["DeskAdmin"])
def activate_schedule(actor, schedule_id):
    schedule = lookup("discount_schedules", schedule_id)
    if schedule["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    if db.now < schedule["effective_from"]:
        fail("ERR_INVALID_STATE", "the logical clock has not reached effective_from.")

    for other in db.discount_schedules.values():
        if other["id"] != schedule["id"] \
                and other["commodity_code"] == schedule["commodity_code"] \
                and other["status"] == "ACTIVE":
            apply_changes(other, {"status": "SUPERSEDED"})
    apply_changes(schedule, {"status": "ACTIVE"})
    return ok(schedule_out(schedule))


@bp.get("/grain/discount-schedules")
@endpoint(ALL_ROLES)
def list_schedules(actor):
    rows = list(db.discount_schedules.values())
    commodity = request.args.get("commodity_code")
    status = request.args.get("status")
    if commodity:
        rows = [r for r in rows if r["commodity_code"] == commodity]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paged(sort_rows(rows), schedule_out)


@bp.get("/grain/discount-schedules/<schedule_id>")
@endpoint(ALL_ROLES)
def read_schedule(actor, schedule_id):
    return ok(schedule_out(lookup("discount_schedules", schedule_id)))


# --------------------------------------------------------------------------
# RiskLimit
# --------------------------------------------------------------------------
@bp.post("/grain/risk-limits")
@endpoint(["RiskOfficer"])
def create_risk_limit(actor):
    payload = guard_payload(body())
    desk = lookup_fk(payload, "desk_id", "trading_desks")
    if desk is None:
        fail("ERR_INVALID_REQUEST")
    commodity = req_enum(payload, "commodity_code", COMMODITIES)
    max_unpriced = req_int(payload, "max_unpriced_bushels", minimum=0)
    max_net_short = req_int(payload, "max_net_short_lots", minimum=0)
    expected = req_int(payload, "expected_desk_version")
    if expected != desk["version"]:
        fail("ERR_STALE_DESK_VERSION")

    for other in db.risk_limits.values():
        if other["desk_id"] == desk["id"] \
                and other["commodity_code"] == commodity \
                and other["status"] == "ACTIVE":
            apply_changes(other, {"status": "SUPERSEDED"})

    row = new_row()
    row.update({
        "desk_id": desk["id"],
        "commodity_code": commodity,
        "max_unpriced_bushels": max_unpriced,
        "max_net_short_lots": max_net_short,
        "status": "ACTIVE",
    })
    db.risk_limits[row["id"]] = row
    touch(desk)
    return ok(risk_limit_out(row), 201)


@bp.get("/grain/risk-limits")
@endpoint(ALL_ROLES)
def list_risk_limits(actor):
    rows = list(db.risk_limits.values())
    for field in ("desk_id", "commodity_code", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paged(sort_rows(rows), risk_limit_out)


@bp.get("/grain/risk-limits/<risk_limit_id>")
@endpoint(ALL_ROLES)
def read_risk_limit(actor, risk_limit_id):
    return ok(risk_limit_out(lookup("risk_limits", risk_limit_id)))


# --------------------------------------------------------------------------
# RailFleet
# --------------------------------------------------------------------------
@bp.post("/grain/rail-fleets")
@endpoint(["FreightCoordinator"])
def create_fleet(actor):
    payload = guard_payload(body())
    location = lookup_fk(payload, "home_location_id", "elevator_locations")
    if location is None:
        fail("ERR_INVALID_REQUEST")
    fleet_code = req_str(payload, "fleet_code")
    car_count = req_int(payload, "car_count", minimum=0, exclusive_min=True)
    for existing in db.rail_fleets.values():
        if existing["fleet_code"] == fleet_code:
            fail("ERR_INVALID_REQUEST",
                 "fleet_code must be unique across all rail fleets.")

    row = new_row()
    row.update({
        "home_location_id": location["id"],
        "fleet_code": fleet_code,
        "car_count": car_count,
    })
    db.rail_fleets[row["id"]] = row
    return ok(fleet_out(row), 201)


@bp.get("/grain/rail-fleets")
@endpoint(ALL_ROLES)
def list_fleets(actor):
    rows = list(db.rail_fleets.values())
    home = request.args.get("home_location_id")
    if home:
        rows = [r for r in rows if r["home_location_id"] == home]
    return paged(sort_rows(rows), fleet_out)


@bp.get("/grain/rail-fleets/<fleet_id>")
@endpoint(ALL_ROLES)
def read_fleet(actor, fleet_id):
    return ok(fleet_out(lookup("rail_fleets", fleet_id)))


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint(["DeskAdmin"])
def set_clock(actor):
    payload = guard_payload(body())
    target = req_ts(payload, "to_iso8601")
    db.now = target

    expired = []
    for bid in sort_rows(db.bids.values()):
        if bid["status"] in ("ACTIVE", "SUSPENDED") and bid["expires_at"] <= target:
            apply_changes(bid, {"status": "EXPIRED"})
            expired.append(bid["id"])

    return ok({"current_utc": fmt_ts(target), "expired_bid_ids": expired})
