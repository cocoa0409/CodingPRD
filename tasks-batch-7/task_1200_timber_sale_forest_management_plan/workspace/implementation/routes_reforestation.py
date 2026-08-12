"""Reforestation obligations and survival surveys (replant loop)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_int, f_date, err, paginate, get_contract, get_obligation, get_survey,
    bond_of_contract, sale_of_contract, stand_of_sale, check_transition,
    today, parse_date_str, D, rhu,
)
from routes_contracts import reforestation_hold

bp = Blueprint("reforestation", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

OBLIGATION_TERMINAL = {"SATISFIED"}
SURVEY_TERMINAL = {"FINALIZED", "VOID"}

REQUIRED_SURVIVAL_PCT = Decimal("85.00")
SURVEY_MIN_DAYS_AFTER_PLANTING = 365
PLANTING_WINDOW_DAYS = 365
REPLANT_HOLD_PER_ACRE_CENTS = 45000


# ---------------------------- obligations -------------------------

@bp.route("/forestry/obligations/<oid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_obligation_ep(oid):
    return success(pub(get_obligation(oid)), 200)


@bp.route("/forestry/obligations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_obligations():
    page, meta = paginate(db["obligations"].values(), {
        "contract_id": "contract_id",
        "status": "status",
    })
    return success([pub(o) for o in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/obligations/<oid>/record-planting", methods=["POST"])
@require_roles("Contractor")
def record_planting(oid):
    o = get_obligation(oid)
    contract = get_contract(o["contract_id"])
    if contract["contractor_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "contract is not assigned to this contractor")
    body = get_body()
    check_known(body, {"planted_date", "seedlings_planted"})
    planted_date = f_date(body, "planted_date")
    seedlings = f_int(body, "seedlings_planted", minv=0)
    check_transition(o, {"IMPOSED", "REPLANT_REQUIRED"}, OBLIGATION_TERMINAL,
                     "obligation")
    if today() > parse_date_str(o["plant_by_date"]):
        err("ERR_PLANTING_DEADLINE_PASSED", 422,
            "clock date is past plant_by_date")
    o["status"] = "PLANTED"
    o["current_planted_count"] = seedlings
    o["planted_date"] = planted_date
    bump(o)
    return success(pub(o), 200)


@bp.route("/forestry/obligations/<oid>/declare-delinquent", methods=["POST"])
@require_roles("Forester")
def declare_delinquent(oid):
    o = get_obligation(oid)
    body = get_body()
    check_known(body, set())
    check_transition(o, {"IMPOSED"}, OBLIGATION_TERMINAL, "obligation")
    if today() <= parse_date_str(o["plant_by_date"]):
        err("ERR_INVALID_TRANSITION", 409,
            "planting deadline has not passed")
    o["status"] = "DELINQUENT"
    bump(o)
    bond = bond_of_contract(o["contract_id"])
    if bond is not None and bond["status"] == "POSTED":
        bond["status"] = "FORFEIT_CLAIMED"
        bump(bond)
    return success(pub(o), 200)


@bp.route("/forestry/obligations/<oid>/surveys", methods=["POST"])
@require_roles("Forester")
def create_survey(oid):
    o = get_obligation(oid)
    body = get_body()
    check_known(body, {"survey_date", "live_seedlings_count"})
    survey_date = f_date(body, "survey_date")
    live = f_int(body, "live_seedlings_count", minv=0)
    check_transition(o, {"PLANTED"}, OBLIGATION_TERMINAL, "obligation")
    earliest = parse_date_str(o["planted_date"]) + timedelta(
        days=SURVEY_MIN_DAYS_AFTER_PLANTING)
    if parse_date_str(survey_date) < earliest:
        err("ERR_SURVEY_TOO_EARLY", 422,
            "survey is earlier than planted_date + 365 days")
    ent = new_common({
        "obligation_id": o["id"],
        "survey_date": survey_date,
        "live_seedlings_count": live,
        "survival_pct": None,
        "result": None,
        "status": "RECORDED",
    })
    db["surveys"][ent["id"]] = ent
    o["status"] = "SURVEYED"
    bump(o)
    return success(pub(ent), 201)


# ----------------------------- surveys ----------------------------

@bp.route("/forestry/surveys/<sid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_survey_ep(sid):
    return success(pub(get_survey(sid)), 200)


@bp.route("/forestry/surveys", methods=["GET"])
@require_roles(*READ_ROLES)
def list_surveys():
    page, meta = paginate(db["surveys"].values(), {
        "obligation_id": "obligation_id",
        "status": "status",
    })
    return success([pub(s) for s in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/surveys/<sid>/finalize", methods=["POST"])
@require_roles("Forester")
def finalize_survey(sid):
    s = get_survey(sid)
    body = get_body()
    check_known(body, set())
    check_transition(s, {"RECORDED"}, SURVEY_TERMINAL, "survey")
    o = get_obligation(s["obligation_id"])
    if o["status"] != "SURVEYED":
        err("ERR_INVALID_TRANSITION", 409,
            "obligation is not SURVEYED")
    planted = o["current_planted_count"]
    if planted <= 0:
        err("ERR_INVALID_TRANSITION", 409,
            "no seedlings recorded on the current planting")
    pct = (D(s["live_seedlings_count"]) * D(100) / D(planted)).quantize(
        Decimal("0.01"), rounding="ROUND_HALF_UP")
    result = "PASS" if pct >= REQUIRED_SURVIVAL_PCT else "FAIL"
    s["survival_pct"] = float(pct)
    s["result"] = result
    s["status"] = "FINALIZED"
    bump(s)
    if result == "PASS":
        o["status"] = "SATISFIED"
        bump(o)
    else:
        o["status"] = "REPLANT_REQUIRED"
        o["plant_by_date"] = (parse_date_str(s["survey_date"]) + timedelta(
            days=PLANTING_WINDOW_DAYS)).isoformat()
        bump(o)
        # cascade: recompute the bond's reforestation hold upward
        bond = bond_of_contract(o["contract_id"])
        if bond is not None:
            contract = get_contract(o["contract_id"])
            sale = sale_of_contract(contract)
            stand = stand_of_sale(sale)
            bond["reforestation_hold_cents"] = reforestation_hold(
                bond["amount_cents"], stand["acres"],
                REPLANT_HOLD_PER_ACRE_CENTS)
            bump(bond)
    return success(pub(s), 200)


@bp.route("/forestry/surveys/<sid>/void", methods=["POST"])
@require_roles("Forester")
def void_survey(sid):
    s = get_survey(sid)
    body = get_body()
    check_known(body, set())
    check_transition(s, {"RECORDED"}, SURVEY_TERMINAL, "survey")
    s["status"] = "VOID"
    bump(s)
    o = get_obligation(s["obligation_id"])
    if o["status"] == "SURVEYED":
        o["status"] = "PLANTED"
    return success(pub(s), 200)
