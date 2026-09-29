"""Household recruitment, enumeration, retirement and the incentive ledger."""
from flask import Blueprint

from auth import ALL_ROLES, FIELD_TECHNICIAN, PANEL_OPERATIONS_MANAGER, roles
from calculations import (RECRUITMENT_SOURCES, enumeration_verdict,
                          incentive_period_amount, tenure_months,
                          whole_days as floor_days)
from common import must
from errors import ApiError
from response import apply_filters, created, listing, ok
from services import recompute_market, refresh_household_rollups
from store import db
from util import (D, get_body, parse_iso, require_fields, seconds_between,
                  want_enum, want_int, want_str)

bp = Blueprint("households", __name__)


@bp.post("/households")
@roles(PANEL_OPERATIONS_MANAGER)
def recruit_household():
    body = get_body()
    market = None
    cell = None
    if body.get("market_id") is not None:
        market = must("markets", body["market_id"])
    if body.get("quota_cell_id") is not None:
        cell = must("quota_cells", body["quota_cell_id"])
    require_fields(body, ["market_id", "quota_cell_id", "recruitment_source",
                          "persons_count"])
    source = want_enum(body, "recruitment_source", RECRUITMENT_SOURCES)
    persons = want_int(body, "persons_count", minimum=1)
    if market["recruitment_posture"] in ("CLOSED", "FROZEN"):
        raise ApiError("ERR_RECRUITMENT_CLOSED",
                       "the market is not accepting recruits")
    if cell["market_id"] != market["id"]:
        raise ApiError("ERR_QUOTA_CELL_MARKET_MISMATCH",
                       "the quota cell belongs to another market")
    if cell["quota_status"] == "FILLED":
        raise ApiError("ERR_QUOTA_CELL_FILLED", "the quota cell is full")
    household = db.insert("households", {
        "market_id": market["id"],
        "quota_cell_id": cell["id"],
        "recruitment_source": source,
        "persons_count": persons,
        "recruited_at": db.now_iso(),
        "status": "RECRUITED",
        "roster_persons_count": None,
        "tv_sets_count": None,
        "enumeration_count": 0,
        "enumeration_verdict": "PENDING",
        "last_enumeration_at": None,
        "compliance_rate_rolling_30": D("0.0000"),
        "incentive_accrued_cents": 0,
        "accrual_periods": [],
        "retired_reason": None,
    })
    return created(household)


@bp.post("/households/<household_id>/enumerations")
@roles(FIELD_TECHNICIAN)
def enumerate_household(household_id):
    household = must("households", household_id)
    body = get_body()
    require_fields(body, ["roster_persons_count", "tv_sets_count"])
    roster = want_int(body, "roster_persons_count", minimum=1, maximum=12)
    tv_sets = want_int(body, "tv_sets_count", minimum=0, maximum=8)
    if household["status"] not in ("ENUM_PENDING", "ACTIVE", "NONCOMPLIANT_HOLD"):
        raise ApiError("ERR_HOUSEHOLD_NOT_ENUMERABLE",
                       "this household cannot be enumerated")
    tuners = [m for m in db.where("meters", household_id=household["id"])
              if m["meter_type"] == "TV_TUNER" and m["install_status"] == "INSTALLED"]
    if not tuners:
        raise ApiError("ERR_NO_INSTALLED_METER",
                       "an installed TV_TUNER is required")
    if not [m for m in tuners if m["health_status"] == "HEALTHY"]:
        raise ApiError("ERR_METER_FAULTED",
                       "at least one installed tuner must be HEALTHY")
    market = db.get("markets", household["market_id"])
    if market is not None and market["recruitment_posture"] == "FROZEN":
        raise ApiError("ERR_MARKET_FROZEN", "the market is frozen")
    sequence = household["enumeration_count"] + 1
    age_days = floor_days(seconds_between(parse_iso(household["recruited_at"]),
                                          db.clock))
    verdict = enumeration_verdict(sequence, roster, household["persons_count"],
                                  tv_sets, age_days)
    previous_status = household["status"]
    household["enumeration_count"] = sequence
    household["roster_persons_count"] = roster
    household["tv_sets_count"] = tv_sets
    household["enumeration_verdict"] = verdict
    household["last_enumeration_at"] = db.now_iso()
    if previous_status == "ENUM_PENDING" and verdict == "COMPLIANT":
        household["status"] = "ACTIVE"
    elif previous_status == "ENUM_PENDING" and verdict == "NONCOMPLIANT":
        household["status"] = "NONCOMPLIANT_HOLD"
    elif previous_status == "ACTIVE" and verdict == "NONCOMPLIANT":
        household["status"] = "NONCOMPLIANT_HOLD"
    elif previous_status == "NONCOMPLIANT_HOLD" and verdict == "COMPLIANT":
        household["status"] = "ACTIVE"
    db.touch(household)
    refresh_household_rollups(household)
    return ok(household)


@bp.post("/households/<household_id>/retire")
@roles(PANEL_OPERATIONS_MANAGER)
def retire_household(household_id):
    household = must("households", household_id)
    body = get_body()
    require_fields(body, ["retired_reason"])
    reason = want_str(body, "retired_reason", min_len=1, max_len=400)
    if household["status"] == "RETIRED":
        raise ApiError("ERR_HOUSEHOLD_ALREADY_RETIRED",
                       "this household is already retired")
    household["status"] = "RETIRED"
    household["retired_reason"] = reason
    db.touch(household)
    for meter in db.where("meters", household_id=household["id"]):
        if meter["install_status"] == "INSTALLED":
            meter["install_status"] = "REMOVED"
            db.touch(meter)
    refresh_household_rollups(household)
    return ok(household)


@bp.post("/households/<household_id>/accrue-incentive")
@roles(PANEL_OPERATIONS_MANAGER)
def accrue_incentive(household_id):
    household = must("households", household_id)
    body = get_body()
    require_fields(body, ["period_label"])
    label = want_str(body, "period_label", min_len=1, max_len=40)
    cell = db.get("quota_cells", household["quota_cell_id"])
    market = db.get("markets", household["market_id"])
    meters = db.where("meters", household_id=household["id"])
    has_ooh = any(m["meter_type"] == "PORTABLE_OOH"
                  and m["install_status"] == "INSTALLED" for m in meters)
    has_faulted = any(m["health_status"] == "FAULTED" for m in meters)
    months = tenure_months(seconds_between(parse_iso(household["recruited_at"]),
                                           db.clock))
    amount = incentive_period_amount(
        cell["base_incentive_cents"], cell["effective_incentive_multiplier"],
        months, household["compliance_rate_rolling_30"], has_ooh, has_faulted)
    spoken_for = (market["incentive_budget_committed_cents"]
                  + market["incentive_budget_reserved_cents"] + amount)
    if spoken_for > market["incentive_budget_cents"]:
        raise ApiError("ERR_INCENTIVE_BUDGET_EXCEEDED",
                       "the accrual exceeds the market budget")
    if household["status"] != "ACTIVE":
        raise ApiError("ERR_HOUSEHOLD_NOT_ACTIVE", "only ACTIVE homes earn")
    for entry in household["accrual_periods"]:
        if entry["period_label"] == label and not entry["reversed"]:
            raise ApiError("ERR_INCENTIVE_PERIOD_ALREADY_ACCRUED",
                           "this period is already accrued")
    household["accrual_periods"].append({"period_label": label,
                                         "accrued_cents": amount,
                                         "reversed": False})
    household["incentive_accrued_cents"] = (household["incentive_accrued_cents"]
                                            + amount)
    db.touch(household)
    recompute_market(market)
    return ok(household)


@bp.post("/households/<household_id>/reverse-accrual")
@roles(PANEL_OPERATIONS_MANAGER)
def reverse_accrual(household_id):
    household = must("households", household_id)
    body = get_body()
    require_fields(body, ["period_label", "memo"])
    label = want_str(body, "period_label", min_len=1, max_len=40)
    want_str(body, "memo", min_len=1, max_len=400)
    target = None
    for entry in household["accrual_periods"]:
        if entry["period_label"] == label and not entry["reversed"]:
            target = entry
            break
    if target is None:
        raise ApiError("ERR_INCENTIVE_PERIOD_NOT_ACCRUED",
                       "no unreversed accrual carries that period_label")
    target["reversed"] = True
    household["incentive_accrued_cents"] = (household["incentive_accrued_cents"]
                                            - target["accrued_cents"])
    db.touch(household)
    market = db.get("markets", household["market_id"])
    if market is not None:
        recompute_market(market)
    return ok(household)


@bp.get("/households/<household_id>")
@roles(*ALL_ROLES)
def read_household(household_id):
    return ok(must("households", household_id))


@bp.get("/households")
@roles(*ALL_ROLES)
def list_households():
    rows = apply_filters(db.all("households"), {
        "market_id": ("market_id", "str"),
        "quota_cell_id": ("quota_cell_id", "str"),
        "status": ("status", "str"),
        "enumeration_verdict": ("enumeration_verdict", "str"),
    })
    return listing("households", rows)
