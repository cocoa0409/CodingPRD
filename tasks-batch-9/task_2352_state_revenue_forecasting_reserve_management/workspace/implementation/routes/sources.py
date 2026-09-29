"""Revenue sources, their policy adjustments and the error-history view."""

from flask import Blueprint

from db import db, make_record, ordered, touch
from errors import fail
from middleware import authorize, body, opt_date, opt_enum, opt_int, req_date, req_enum, req_int, req_str
from response import object_response, raw_object_response
from routes.helpers import adjustment_or_404, listing, source_or_404
from services import calc
from util import parse_date_str

bp = Blueprint("sources", __name__)

TAX_TYPES = ("PIT", "CIT", "SALES", "CAPITAL_GAINS", "EXCISE", "OTHER")
VOLATILITY = ("LOW", "MEDIUM", "HIGH")
SOURCE_STATUS = ("ACTIVE", "RETIRED")
CATEGORIES = ("RATE_CHANGE", "BASE_CHANGE", "CREDIT", "COMPLIANCE")
KINDS = ("INCREASE", "DECREASE")
PHASE_IN = ("FULL", "PRORATED", "TIERED")

READ_ROLES = ("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist",
              "ReserveTreasurer", "RatingAnalyst")
ADJ_ROLES = ("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist")


# ------------------------------------------------------------------ reads ----
@bp.get("/revenue-sources")
@authorize(*READ_ROLES)
def list_sources():
    return listing(
        ordered(db.sources),
        {
            "status": ("status", str),
            "tax_type": ("tax_type", str),
            "volatility_class": ("volatility_class", str),
            "methodology_flag": ("methodology_flag", bool),
        },
    )


@bp.get("/revenue-sources/<source_id>")
@authorize(*READ_ROLES)
def get_source(source_id):
    return object_response(source_or_404(source_id))


@bp.get("/revenue-sources/<source_id>/policy-adjustments")
@authorize(*ADJ_ROLES)
def list_source_adjustments(source_id):
    source = source_or_404(source_id)
    return listing(calc.adjustments_of(source["id"]),
                   {"policy_category": ("policy_category", str)})


@bp.get("/revenue-sources/<source_id>/error-history")
@authorize("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist", "RatingAnalyst")
def error_history(source_id):
    source = source_or_404(source_id)
    window = calc.error_window(source["id"])
    mape = calc.mape_for(source["id"])
    return raw_object_response(
        {
            "source_id": source["id"],
            "window_fiscal_years": [r["fiscal_year"] for r in window],
            "window_error_bps": [r["abs_pct_error_bps"] for r in window],
            "window_count": len(window),
            "mape_bps": mape,
            "methodology_flag": mape >= calc.METHODOLOGY_FLAG_BPS,
            "posted_actual_count": source["posted_actual_count"],
        }
    )


@bp.get("/policy-adjustments/<adjustment_id>")
@authorize(*ADJ_ROLES)
def get_adjustment(adjustment_id):
    return object_response(adjustment_or_404(adjustment_id))


# ----------------------------------------------------------------- writes ----
@bp.post("/revenue-sources")
@authorize("ForecastDirector")
def create_source():
    data = body()
    rec = make_record(
        {
            "name": req_str(data, "name"),
            "tax_type": req_enum(data, "tax_type", TAX_TYPES),
            "base_year_receipts_cents": req_int(data, "base_year_receipts_cents", minimum=1),
            "elasticity_employment_bps": req_int(data, "elasticity_employment_bps",
                                                 allow_negative=True),
            "elasticity_wage_income_bps": req_int(data, "elasticity_wage_income_bps",
                                                  allow_negative=True),
            "elasticity_retail_bps": req_int(data, "elasticity_retail_bps", allow_negative=True),
            "elasticity_asset_bps": req_int(data, "elasticity_asset_bps", allow_negative=True),
            "volatility_class": req_enum(data, "volatility_class", VOLATILITY),
            "status": "ACTIVE",
            "mape_bps": 0,
            "methodology_flag": False,
            "posted_actual_count": 0,
        }
    )
    db.sources[rec["id"]] = rec
    return object_response(rec, 201)


@bp.patch("/revenue-sources/<source_id>")
@authorize("ForecastDirector")
def patch_source(source_id):
    source = source_or_404(source_id)
    data = body()
    status = opt_enum(data, "status", SOURCE_STATUS)
    volatility = opt_enum(data, "volatility_class", VOLATILITY)
    base = opt_int(data, "base_year_receipts_cents", minimum=1)
    if status is not None:
        source["status"] = status
    if volatility is not None:
        source["volatility_class"] = volatility
    if base is not None:
        source["base_year_receipts_cents"] = base
    touch(source)
    return object_response(source)


def _window_checks(start, end, source_id, category, exclude_id=None):
    if end is not None and end <= start:
        fail("ERR_INVALID_EFFECTIVE_WINDOW",
             "effective_end_date must be strictly after effective_start_date")
    for other in calc.adjustments_of(source_id):
        if other["id"] == exclude_id:
            continue
        if other["policy_category"] != category:
            continue
        o_start = parse_date_str(other["effective_start_date"])
        o_end = (parse_date_str(other["effective_end_date"])
                 if other.get("effective_end_date") else None)
        if calc.windows_overlap(start, end, o_start, o_end):
            fail("ERR_POLICY_WINDOW_OVERLAP",
                 "an adjustment of this category already occupies that window")


@bp.post("/revenue-sources/<source_id>/policy-adjustments")
@authorize("ForecastDirector", "ExecutiveEconomist")
def create_adjustment(source_id):
    source = source_or_404(source_id)
    data = body()
    statute = req_str(data, "statute_code")
    category = req_enum(data, "policy_category", CATEGORIES)
    kind = req_enum(data, "adjustment_kind", KINDS)
    amount = req_int(data, "annualized_amount_cents", minimum=1)
    start_raw = req_date(data, "effective_start_date")
    end_raw = opt_date(data, "effective_end_date")
    phase_in = req_enum(data, "phase_in_type", PHASE_IN)
    first_fy = req_int(data, "first_effective_fiscal_year", minimum=2000, maximum=2100)
    cap = opt_int(data, "cap_amount_cents", default=0, minimum=0)

    start = parse_date_str(start_raw)
    end = parse_date_str(end_raw) if end_raw else None
    _window_checks(start, end, source["id"], category)

    if source["status"] != "ACTIVE":
        fail("ERR_SOURCE_RETIRED", "a RETIRED source may not receive policy adjustments")

    rec = make_record(
        {
            "source_id": source["id"],
            "statute_code": statute,
            "policy_category": category,
            "adjustment_kind": kind,
            "annualized_amount_cents": amount,
            "effective_start_date": start_raw,
            "effective_end_date": end_raw,
            "phase_in_type": phase_in,
            "first_effective_fiscal_year": first_fy,
            "cap_amount_cents": cap,
        }
    )
    db.adjustments[rec["id"]] = rec
    return object_response(rec, 201)


@bp.patch("/policy-adjustments/<adjustment_id>")
@authorize("ForecastDirector", "ExecutiveEconomist")
def patch_adjustment(adjustment_id):
    adj = adjustment_or_404(adjustment_id)
    data = body()
    amount = opt_int(data, "annualized_amount_cents", minimum=1)
    start_raw = opt_date(data, "effective_start_date")
    phase_in = opt_enum(data, "phase_in_type", PHASE_IN)
    cap = opt_int(data, "cap_amount_cents", minimum=0)
    end_supplied = "effective_end_date" in data
    end_raw = opt_date(data, "effective_end_date")

    new_start_raw = start_raw if start_raw is not None else adj["effective_start_date"]
    if end_supplied:
        new_end_raw = end_raw
    else:
        new_end_raw = adj["effective_end_date"]

    start = parse_date_str(new_start_raw)
    end = parse_date_str(new_end_raw) if new_end_raw else None
    _window_checks(start, end, adj["source_id"], adj["policy_category"], adj["id"])

    if amount is not None:
        adj["annualized_amount_cents"] = amount
    adj["effective_start_date"] = new_start_raw
    adj["effective_end_date"] = new_end_raw
    if phase_in is not None:
        adj["phase_in_type"] = phase_in
    if cap is not None:
        adj["cap_amount_cents"] = cap
    touch(adj)
    return object_response(adj)


@bp.delete("/policy-adjustments/<adjustment_id>")
@authorize("ForecastDirector")
def delete_adjustment(adjustment_id):
    adj = adjustment_or_404(adjustment_id)
    del db.adjustments[adj["id"]]
    return "", 204
