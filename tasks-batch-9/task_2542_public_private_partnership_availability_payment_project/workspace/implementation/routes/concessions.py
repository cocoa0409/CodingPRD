"""Sponsor vehicles, concession drafting, financial close, commencement, handback."""

from flask import Blueprint

import calc
from db import db, insert, public, setf, touch
from errors import fail
from middleware import (ROLE_AUTHORITY_OFFICER, ROLE_INDEPENDENT_CERTIFIER,
                        ROLE_PLATFORM_ADMIN, actor, as_instant, body, get_concession,
                        get_concessionaire, req_enum, req_instant, req_int, req_ratio,
                        req_str, require_auth, role)
from response import created, ok

bp = Blueprint("concessions", __name__)


def sponsor_of(concession):
    return db.tables["concessionaires"][concession["concessionaire_id"]]


def refresh_concessions_count(sponsor):
    count = len([c for c in db.all("concessions")
                 if c["concessionaire_id"] == sponsor["id"]])
    setf(sponsor, "concessions_count", count)


# ------------------------------------------------------------------ sponsors
@bp.post("/ppp/concessionaires")
def create_concessionaire():
    require_auth(ROLE_PLATFORM_ADMIN)
    data = body()
    legal_name = req_str(data, "legal_name", max_len=200)
    commitment = req_int(data, "sponsor_equity_commitment_cents", minimum=0)
    row = insert("concessionaires", {
        "legal_name": legal_name,
        "sponsor_equity_commitment_cents": commitment,
        "status": "ACTIVE",
        "concessions_count": 0,
    })
    return created(public(row))


# ------------------------------------------------------------------ concessions
@bp.post("/ppp/concessions")
def create_concession():
    require_auth(ROLE_PLATFORM_ADMIN, ROLE_AUTHORITY_OFFICER)
    data = body()
    # body-referenced id existence precedes schema conformance (PRD 2.9)
    raw_sponsor_id = data.get("concessionaire_id")
    if isinstance(raw_sponsor_id, str) and raw_sponsor_id != "":
        sponsor = db.tables["concessionaires"].get(raw_sponsor_id)
        if sponsor is None:
            fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    else:
        sponsor = None

    concessionaire_id = req_str(data, "concessionaire_id")
    project_name = req_str(data, "project_name", max_len=200)
    masp_cents = req_int(data, "masp_cents", minimum=1)
    indexation_pct = req_ratio(data, "indexation_pct", 0, 1, 6, required=False, default=0)
    deduction_cap_pct = req_ratio(data, "deduction_cap_pct", 0, 1, 4, exclusive_min=True)
    total_project_cost_cents = req_int(data, "total_project_cost_cents", minimum=1)
    senior_debt_committed_cents = req_int(data, "senior_debt_committed_cents", minimum=0)
    equity_committed_cents = req_int(data, "equity_committed_cents", minimum=0)
    base_case_equity_irr_bps = req_int(data, "base_case_equity_irr_bps", minimum=0, maximum=5000)
    scheduled, _ = req_instant(data, "scheduled_service_commencement")
    ld_daily_rate_cents = req_int(data, "ld_daily_rate_cents", minimum=0)
    ld_cap_cents = req_int(data, "ld_cap_cents", minimum=0)
    lifecycle_reserve_target_cents = req_int(data, "lifecycle_reserve_target_cents", minimum=0)

    if sponsor is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")

    if total_project_cost_cents > senior_debt_committed_cents + equity_committed_cents:
        fail("ERR_COMMITMENT_EXCEEDED")

    row = insert("concessions", {
        "project_name": project_name,
        "concessionaire_id": concessionaire_id,
        "status": "DRAFTED",
        "masp_cents": masp_cents,
        "indexation_pct": indexation_pct,
        "deduction_cap_pct": deduction_cap_pct,
        "total_project_cost_cents": total_project_cost_cents,
        "senior_debt_committed_cents": senior_debt_committed_cents,
        "equity_committed_cents": equity_committed_cents,
        "base_case_equity_irr_bps": base_case_equity_irr_bps,
        "scheduled_service_commencement": scheduled,
        "ld_daily_rate_cents": ld_daily_rate_cents,
        "ld_cap_cents": ld_cap_cents,
        "lifecycle_reserve_target_cents": lifecycle_reserve_target_cents,
        "financial_close_date": None,
        "monthly_unitary_charge_cents": None,
        "senior_debt_drawn_cents": 0,
        "equity_drawn_cents": 0,
        "cumulative_drawn_pct": 0,
        "actual_service_commencement": None,
        "ld_accrued_cents": 0,
        "lifecycle_reserve_balance_cents": 0,
        "availability_deduction_ytd_cents": 0,
        "deduction_points_ytd": 0,
        "persistent_breach_flag": False,
        "handback_survey_date": None,
        "handback_rectification_cost_cents": None,
        "handback_required_reserve_cents": None,
        "handback_shortfall_cents": None,
        "handback_status": "NOT_SURVEYED",
    })
    refresh_concessions_count(sponsor)
    return created(public(row))


@bp.patch("/ppp/concessions/<row_id>")
def patch_concession(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    concession = get_concession(row_id)
    data = body()
    masp_cents = req_int(data, "masp_cents", minimum=1, required=False)
    indexation_pct = req_ratio(data, "indexation_pct", 0, 1, 6, required=False)
    deduction_cap_pct = req_ratio(data, "deduction_cap_pct", 0, 1, 4, required=False,
                                  exclusive_min=True)
    ld_daily_rate_cents = req_int(data, "ld_daily_rate_cents", minimum=0, required=False)
    ld_cap_cents = req_int(data, "ld_cap_cents", minimum=0, required=False)
    lifecycle_reserve_target_cents = req_int(data, "lifecycle_reserve_target_cents",
                                             minimum=0, required=False)
    if concession["status"] != "DRAFTED":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")

    for field, value in (
        ("masp_cents", masp_cents),
        ("indexation_pct", indexation_pct),
        ("deduction_cap_pct", deduction_cap_pct),
        ("ld_daily_rate_cents", ld_daily_rate_cents),
        ("ld_cap_cents", ld_cap_cents),
        ("lifecycle_reserve_target_cents", lifecycle_reserve_target_cents),
    ):
        if value is not None:
            setf(concession, field, value)
    return ok(public(concession))


@bp.post("/ppp/concessions/<row_id>/financial-close")
def financial_close(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    concession = get_concession(row_id)
    data = body()
    close_date, _ = req_instant(data, "close_date")
    if concession["status"] != "DRAFTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if (concession["senior_debt_committed_cents"] + concession["equity_committed_cents"]
            < concession["total_project_cost_cents"]):
        fail("ERR_COMMITMENT_EXCEEDED")
    setf(concession, "financial_close_date", close_date)
    setf(concession, "monthly_unitary_charge_cents",
         calc.monthly_unitary_charge_cents(concession))
    setf(concession, "status", "FINANCIAL_CLOSE")
    return ok(public(concession))


@bp.post("/ppp/concessions/<row_id>/certify-service-commencement")
def certify_service_commencement(row_id):
    require_auth(ROLE_INDEPENDENT_CERTIFIER)
    concession = get_concession(row_id)
    data = body()
    raw_date, actual_dt = req_instant(data, "actual_commencement_date")
    if concession["status"] != "CONSTRUCTION":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    if concession["actual_service_commencement"] is not None:
        fail("ERR_INVALID_STATE_TRANSITION")
    close_dt = as_instant(concession["financial_close_date"])
    if close_dt is not None and actual_dt.date() < close_dt.date():
        fail("ERR_INVALID_INTERVAL")
    setf(concession, "actual_service_commencement", raw_date)
    setf(concession, "ld_accrued_cents", calc.liquidated_damages(concession, actual_dt))
    setf(concession, "status", "OPERATIONS")
    return ok(public(concession))


@bp.post("/ppp/concessions/<row_id>/handback-survey")
def handback_survey(row_id):
    require_auth(ROLE_INDEPENDENT_CERTIFIER)
    concession = get_concession(row_id)
    data = body()
    raw_date, _ = req_instant(data, "handback_survey_date")
    rectification = req_int(data, "handback_rectification_cost_cents", minimum=0)
    if concession["status"] != "OPERATIONS":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    calc.enforcement_freeze_guard(concession)

    required, shortfall, status = calc.handback_assessment(concession, rectification)
    setf(concession, "handback_survey_date", raw_date)
    setf(concession, "handback_rectification_cost_cents", rectification)
    setf(concession, "handback_required_reserve_cents", required)
    setf(concession, "handback_shortfall_cents", shortfall)
    setf(concession, "handback_status", status)

    if status == "FAILED":
        period = calc.latest_verified_period(concession["id"])
        if period is not None:
            points = calc.rhu(
                calc.Decimal(shortfall) / calc.Decimal(calc.DEDUCTION_POINT_VALUE_CENTS))
            calc.issue_deduction_event(period, "HANDBACK_SHORTFALL", points, "SYSTEM")
            calc.price_period(period)
            calc.recompute_ytd(concession)
            calc.recompute_points_and_breach(concession)
    return ok(public(concession))
