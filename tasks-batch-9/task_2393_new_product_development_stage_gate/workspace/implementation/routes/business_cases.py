"""Business cases, channel forecast lines and the financial recomputation."""

from flask import Blueprint

import calc
import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("business_cases", __name__)

CASE_ADMITTED_DEV = ("IDEA", "SCREENED", "PILOT_QUALIFIED", "LAUNCH_READY")

DEFAULT_FINANCIALS = {
    "annual_units": 0,
    "gross_revenue_usd": calc.money(0),
    "avg_list_price_usd": calc.price(0),
    "trade_spend_rate_pct": calc.money(0),
    "trade_spend_usd": calc.money(0),
    "net_revenue_usd": calc.money(0),
    "cogs_total_usd": calc.money(0),
    "gross_margin_usd": calc.money(0),
    "gross_margin_pct": calc.money(0),
    "npv_usd": calc.money(0),
    "payback_months": 0,
}


@bp.post("/innovation-projects/<project_id>/business-cases")
def create_business_case(project_id):
    M.authenticate("InnovationLead")
    project = common.project(project_id)
    data = V.body()
    expected_version = V.int_field(data, "expected_project_version")
    variant_mode = V.enum_field(data, "variant_mode", V.VARIANT_MODES)
    category_size = V.int_field(data, "category_size_units_year", minimum=0)
    target_share = V.number_field(data, "target_share_pct", minimum=0, maximum=100)
    cogs_per_unit = V.number_field(data, "cogs_per_unit_usd", minimum=0, places=4)
    slotting = V.number_field(data, "slotting_fees_usd", minimum=0)
    capex = V.number_field(data, "capex_usd", minimum=0)
    discount_rate = V.number_field(data, "discount_rate_pct", minimum=0, maximum=100)

    if project["dev_status"] not in CASE_ADMITTED_DEV:
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "dev_status %s does not admit business-case creation."
               % project["dev_status"])
    if expected_version != project["version"]:
        E.fail(E.ERR_PROJECT_VERSION_CONFLICT,
               "expected_project_version %s does not match stored version %s."
               % (expected_version, project["version"]))

    prior = core.project_cases(project["id"])
    case_type = "PRELIMINARY" if not prior else "FINAL"

    fields = {
        "project_id": project["id"],
        "variant_mode": variant_mode,
        "case_type": case_type,
        "category_size_units_year": category_size,
        "target_share_pct": target_share,
        "cogs_per_unit_usd": cogs_per_unit,
        "slotting_fees_usd": slotting,
        "capex_usd": capex,
        "discount_rate_pct": discount_rate,
        "status": "DRAFT",
    }
    fields.update(DEFAULT_FINANCIALS)
    row = core.new_row(db.business_cases, fields)

    for case in prior:
        if case["status"] in ("DRAFT", "COMPUTED"):
            core.apply(case, {"status": "SUPERSEDED"})

    core.touch(project)
    return R.object_response(row, 201)


@bp.get("/innovation-projects/<project_id>/business-cases")
def list_business_cases(project_id):
    M.reader()
    project = common.project(project_id)
    rows = core.project_cases(project["id"])
    rows = M.apply_filters(rows, {"status": "status", "variant_mode": "variant_mode"})
    rows = M.order(rows)
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/business-cases/<business_case_id>")
def read_business_case(business_case_id):
    M.reader()
    return R.object_response(common.business_case(business_case_id))


@bp.post("/business-cases/<business_case_id>/forecast-lines")
def create_forecast_line(business_case_id):
    M.authenticate("InnovationLead")
    case = common.business_case(business_case_id)
    data = V.body()
    channel = V.enum_field(data, "channel", V.CHANNELS)
    store_count = V.int_field(data, "store_count", minimum=0)
    velocity = V.number_field(data, "base_velocity_units_per_store_week", minimum=0)
    promo_weeks = V.int_field(data, "promo_weeks", minimum=0, maximum=52)
    promo_lift = V.number_field(data, "promo_lift_pct", minimum=0)
    list_price = V.number_field(data, "list_price_usd", minimum=0, places=4)

    if case["status"] not in ("DRAFT", "COMPUTED"):
        E.fail(E.ERR_BUSINESS_CASE_INVALID_STATE,
               "A %s case takes no further forecast lines." % case["status"])
    for line in core.case_lines(case["id"]):
        if line["channel"] == channel:
            E.fail(E.ERR_DUPLICATE_CHANNEL_LINE,
                   "Channel %s already has a line on this case." % channel)

    fields = {
        "business_case_id": case["id"],
        "channel": channel,
        "store_count": store_count,
        "base_velocity_units_per_store_week": velocity,
        "promo_weeks": promo_weeks,
        "promo_lift_pct": promo_lift,
        "list_price_usd": list_price,
    }
    # A line's own figures are part of its insert, not a later write to it:
    # `version` "starts at 1 on insert" (PRD §2.4), so the create must not
    # bump the row it just minted. The subsequent case recomputation is a
    # no-op against this line and touches nothing.
    units, revenue = calc.forecast_line_figures(fields)
    fields["line_units"] = units
    fields["line_revenue_usd"] = revenue
    row = core.new_row(db.forecast_lines, fields)

    core.recompute_case(case, {"status": "COMPUTED"})
    if case["case_type"] == "PRELIMINARY":
        core.auto_approve(case["project_id"], "PRELIM_BUSINESS_CASE")
    else:
        core.auto_approve(case["project_id"], "FINAL_BUSINESS_CASE")
    return R.object_response(row, 201)


@bp.get("/business-cases/<business_case_id>/forecast-lines")
def list_forecast_lines(business_case_id):
    M.reader()
    case = common.business_case(business_case_id)
    rows = M.order(core.case_lines(case["id"]))
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)
