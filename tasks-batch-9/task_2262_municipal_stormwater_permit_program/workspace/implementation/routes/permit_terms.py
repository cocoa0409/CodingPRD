"""Permit terms: creation, activation, expiry, nested reads and billing runs."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, CLOCK, new_row, touch
from errors import ApiError
from middleware import (
    body,
    get_bool,
    get_date,
    get_enum,
    get_int,
    get_number,
    get_str,
    require,
)
from response import object_response
from routes.common import find, listing, one, require_active, settle
from services import calc, derive

bp = Blueprint("permit_terms", __name__)

READERS = mw.OPERATIONAL_ROLES


@bp.post("/permit-terms")
def create_permit_term():
    require([mw.MANAGER])
    payload = body()
    permit_number = get_str(payload, "permit_number", min_len=1, max_len=64)
    start = get_date(payload, "term_start_date")
    end = get_date(payload, "term_end_date")
    if end <= start:
        raise ApiError("ERR_VALIDATION", "term_end_date must be later than term_start_date.")
    tmdl_applicable = get_bool(payload, "tmdl_applicable", required=False, default=False)
    pollutant = get_enum(
        payload, "tmdl_pollutant", enums.TMDL_POLLUTANT, required=False, default=None
    )
    wla = get_number(payload, "tmdl_wla_lb_per_year", required=False, default=None, minimum=0)
    if tmdl_applicable and (pollutant is None or wla is None):
        raise ApiError(
            "ERR_VALIDATION",
            "tmdl_pollutant and tmdl_wla_lb_per_year are required when tmdl_applicable is true.",
        )
    eru_sqft = get_int(payload, "eru_sqft", required=False, default=3000, minimum=100)
    funding_target = get_int(
        payload, "funding_target_cents", required=False, default=0, minimum=0
    )

    for term in DB.permit_terms.values():
        if term["permit_number"] == permit_number:
            raise ApiError("ERR_DUPLICATE_PERMIT_NUMBER")

    row = new_row(
        {
            "permit_number": permit_number,
            "term_start_date": start.isoformat(),
            "term_end_date": end.isoformat(),
            "status": "DRAFT",
            "tmdl_applicable": tmdl_applicable,
            "tmdl_pollutant": pollutant,
            "tmdl_wla_lb_per_year": None if wla is None else calc.num(wla, 2),
            "eru_sqft": eru_sqft,
            "funding_target_cents": funding_target,
            "compliance_posture": "COMPLIANT",
            "behind_measure_count": 0,
            "exceeding_outfall_count": 0,
            "total_assessed_penalty_cents": 0,
            "projected_annual_revenue_cents": 0,
            "funding_adequacy_status": "ADEQUATE",
            "activated_at": None,
            "expired_at": None,
            "last_compiled_at": None,
        }
    )
    DB.permit_terms[row["id"]] = row
    return one(row, 201)


@bp.get("/permit-terms")
def list_permit_terms():
    require(READERS)
    spec = {
        "status": ("status", enums.TERM_STATUS),
        "compliance_posture": ("compliance_posture", enums.COMPLIANCE_POSTURE),
    }
    return listing(spec, lambda: list(DB.permit_terms.values()))


@bp.get("/permit-terms/<term_id>")
def read_permit_term(term_id):
    require(READERS)
    return one(find("permit_terms", term_id))


@bp.post("/permit-terms/<term_id>/activate")
def activate_permit_term(term_id):
    require([mw.MANAGER])
    term = find("permit_terms", term_id)
    if term["status"] != "DRAFT":
        raise ApiError("ERR_PERMIT_TERM_NOT_ACTIVE")

    present = {
        m["measure_code"]
        for m in derive.measures_of_term(term_id)
        if m["status"] == "ACTIVE"
    }
    if not set(enums.MEASURE_CODES).issubset(present):
        raise ApiError("ERR_MEASURE_SET_INCOMPLETE")
    if term.get("tmdl_applicable"):
        active_outfalls = [
            o for o in derive.outfalls_of_term(term_id) if o["status"] == "ACTIVE"
        ]
        if not active_outfalls:
            raise ApiError("ERR_MEASURE_SET_INCOMPLETE")

    term["status"] = "ACTIVE"
    term["activated_at"] = CLOCK.stamp()
    touch(term)
    settle(term)
    return one(term)


@bp.post("/permit-terms/<term_id>/expire")
def expire_permit_term(term_id):
    require([mw.MANAGER])
    term = find("permit_terms", term_id)
    if term["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_TERM_NOT_ACTIVE")
    for report in derive.reports_of_term(term_id):
        if report["status"] in ("DRAFT", "COMPILED", "CERTIFIED"):
            raise ApiError("ERR_OPEN_REPORTS_EXIST")
    if CLOCK.now().date() < calc.date.fromisoformat(term["term_end_date"]):
        raise ApiError("ERR_TERM_END_NOT_REACHED")

    term["status"] = "EXPIRED"
    term["expired_at"] = CLOCK.stamp()
    touch(term)
    for measure in derive.measures_of_term(term_id):
        if measure["status"] == "ACTIVE":
            measure["status"] = "RETIRED"
            touch(measure)
    for outfall in derive.outfalls_of_term(term_id):
        if outfall["status"] == "ACTIVE":
            outfall["status"] = "RETIRED"
            touch(outfall)
    settle(term)
    return one(term)


@bp.get("/permit-terms/<term_id>/control-measures")
def list_term_measures(term_id):
    require(READERS)
    spec = {
        "measure_code": ("measure_code", enums.MEASURE_CODE_SET),
        "status": ("status", enums.MEASURE_STATUS),
        "goal_status": ("goal_status", enums.GOAL_STATUS),
    }
    return listing(
        spec,
        lambda: derive.measures_of_term(find("permit_terms", term_id)["id"]),
    )


@bp.get("/permit-terms/<term_id>/outfalls")
def list_term_outfalls(term_id):
    require(READERS)
    spec = {
        "screening_status": ("screening_status", enums.SCREENING_STATUS),
        "tmdl_status": ("tmdl_status", enums.TMDL_STATUS),
        "status": ("status", enums.OUTFALL_STATUS),
        "priority_tier": ("priority_tier", enums.PRIORITY_TIER),
    }
    return listing(
        spec,
        lambda: derive.outfalls_of_term(find("permit_terms", term_id)["id"]),
    )


@bp.get("/permit-terms/<term_id>/construction-sites")
def list_term_sites(term_id):
    require(READERS)
    spec = {
        "plan_status": ("plan_status", enums.PLAN_STATUS),
        "field_status": ("field_status", enums.FIELD_STATUS),
    }
    return listing(
        spec,
        lambda: derive.sites_of_term(find("permit_terms", term_id)["id"]),
    )


@bp.get("/permit-terms/<term_id>/accounts")
def list_term_accounts(term_id):
    require([mw.MANAGER, mw.CLERK])
    spec = {"parcel_class": ("parcel_class", enums.PARCEL_CLASS)}
    return listing(
        spec,
        lambda: derive.accounts_of_term(find("permit_terms", term_id)["id"]),
    )


@bp.get("/permit-terms/<term_id>/annual-reports")
def list_term_reports(term_id):
    require(READERS)
    spec = {"status": ("status", enums.REPORT_STATUS)}
    return listing(
        spec,
        lambda: derive.reports_of_term(find("permit_terms", term_id)["id"]),
    )


@bp.post("/permit-terms/<term_id>/billing-runs")
def billing_run(term_id):
    require([mw.CLERK])
    payload = body()
    run_type = get_enum(payload, "run_type", enums.RUN_TYPE)
    period_start = get_date(payload, "period_start")
    period_end = get_date(payload, "period_end")
    term = find("permit_terms", term_id)
    require_active(term)

    stamp = CLOCK.stamp()
    accounts = sorted(
        derive.accounts_of_term(term_id), key=lambda a: (a["created_at"], a["_seq"])
    )
    total_gross = 0
    total_credit = 0
    total_net = 0
    for account in accounts:
        fee = calc.tiered_fee(
            account["impervious_area_sqft"], term.get("eru_sqft"), account["parcel_class"]
        )
        pct = calc.credit_pool(derive.applications_of_account(account["id"]), run_type)
        credit, net = calc.apply_credit(fee["gross_billable_cents"], pct)
        account.update(fee)
        account["last_billed_run_type"] = run_type
        account["last_billed_credit_pct"] = float(pct)
        account["last_billed_net_cents"] = net
        account["last_billed_at"] = stamp
        touch(account)
        total_gross += fee["gross_billable_cents"]
        total_credit += credit
        total_net += net

    settle(term)
    return object_response(
        {
            "run_type": run_type,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "billed_account_count": len(accounts),
            "total_gross_billable_cents": total_gross,
            "total_credit_cents": total_credit,
            "total_net_billed_cents": total_net,
        }
    )
