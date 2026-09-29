"""Licensee registration, financials and the computed coverage reads (§3.1, §3.5, §3.7)."""

import re

from flask import Blueprint

import calculations as calc
from db import base_row, db, serialize, set_input_dt, touch
from errors import ApiError
from middleware import authorize
from response import created, ok
from routes.common import filter_rows, get_licensee, paginate
from services import engine
from validators import bad, get_body, pagination, q_enum, v_dt, v_int, v_str

bp = Blueprint("licensees", __name__)

EIN_RE = re.compile(r"^\d{9}$")


@bp.post("/licensees")
def create_licensee():
    authorize("LicensingManager")
    body = get_body()
    legal_name = v_str(body, "legal_name")
    ein = v_str(body, "ein")
    if not EIN_RE.match(ein):
        bad("ein must be exactly nine digits")
    net_worth = v_int(
        body, "reported_tangible_net_worth_cents", required=False, minimum=None, default=0
    )
    raw_date, parsed_date = v_dt(body, "net_worth_statement_date", required=False)

    for existing in db.licensees.values():
        if existing["ein"] == ein:
            raise ApiError("ERR_DUPLICATE_EIN", "A licensee with ein %s already exists" % ein)

    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "ein": ein,
            "reported_tangible_net_worth_cents": net_worth,
            "aggregate_outstanding_obligations_cents": 0,
            "eligible_investment_value_cents": 0,
            "book_investment_value_cents": 0,
            "coverage_ratio_bps": 10000,
            "coverage_posture": "COMPLIANT",
            "consecutive_failed_test_count": 0,
            "control_chain_status": "VERIFIED",
            "active_license_count": 0,
        }
    )
    set_input_dt(row, "net_worth_statement_date", raw_date, parsed_date)
    db.licensees[row["id"]] = row
    return created(serialize(row))


@bp.get("/licensees/<licensee_id>")
def get_one(licensee_id):
    authorize(
        "LicensingManager", "ComplianceOfficer", "ChiefComplianceOfficer", "StateRegulator"
    )
    return ok(serialize(get_licensee(licensee_id)))


@bp.patch("/licensees/<licensee_id>/financials")
def update_financials(licensee_id):
    authorize("LicensingManager")
    body = get_body()
    net_worth = v_int(body, "reported_tangible_net_worth_cents", minimum=None)
    raw_date, parsed_date = v_dt(body, "net_worth_statement_date", required=True)
    licensee = get_licensee(licensee_id)
    licensee["reported_tangible_net_worth_cents"] = net_worth
    set_input_dt(licensee, "net_worth_statement_date", raw_date, parsed_date)
    touch(licensee)
    return ok(serialize(licensee))


@bp.get("/licensees/<licensee_id>/coverage-summary")
def coverage_summary(licensee_id):
    authorize(
        "LicensingManager", "ComplianceOfficer", "ChiefComplianceOfficer", "StateRegulator"
    )
    licensee = get_licensee(licensee_id)
    holdings = engine.holdings_of(licensee_id)
    obligations = calc.licensee_obligation_aggregate(engine.licenses_of(licensee_id))
    book_value = calc.book_value_total(holdings)
    eligible_value = calc.eligible_market_total(holdings, obligations)
    return ok(
        {
            "obligations_cents": obligations,
            "book_investment_value_cents": book_value,
            "book_coverage_ratio_bps": calc.ratio_bps(book_value, obligations),
            "eligible_investment_value_cents": eligible_value,
            "coverage_ratio_bps": calc.ratio_bps(eligible_value, obligations),
            "concentration_cap_cents": calc.concentration_cap_cents(obligations),
            "coverage_posture": licensee["coverage_posture"],
            "consecutive_failed_test_count": licensee["consecutive_failed_test_count"],
        }
    )


@bp.get("/licensees/<licensee_id>/assessment-summary")
def assessment_summary(licensee_id):
    authorize("LicensingManager", "StateRegulator")
    get_licensee(licensee_id)
    lines = []
    for lic in engine.licenses_of(licensee_id):
        if lic["license_status"] != "ACTIVE":
            continue
        jur = db.jurisdictions.get(lic["jurisdiction_id"])
        if jur is None:
            continue
        lines.append((lic, jur))
    count, unrounded, total = calc.aggregate_assessment_invoice(lines)
    return ok(
        {
            "line_item_count": count,
            "unrounded_sum_cents": unrounded,
            "annual_assessment_total_cents": total,
        }
    )


@bp.get("/licensees/<licensee_id>/investment-holdings")
def list_holdings(licensee_id):
    authorize(
        "LicensingManager", "ComplianceOfficer", "ChiefComplianceOfficer", "StateRegulator"
    )
    limit, offset = pagination()
    status = q_enum("status", ("HELD", "DISPOSED"))
    asset_class = q_enum("asset_class", calc.ASSET_CLASSES)
    get_licensee(licensee_id)
    rows = filter_rows(
        engine.holdings_of(licensee_id), {"status": status, "asset_class": asset_class}
    )
    return paginate(rows, limit, offset)
