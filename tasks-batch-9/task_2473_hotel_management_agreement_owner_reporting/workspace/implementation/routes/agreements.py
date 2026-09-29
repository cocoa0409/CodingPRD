"""Management agreements, the reserve ledger, working capital calls and the
annual incentive true-up."""

from flask import Blueprint

import validate as v
from auth import READ_ROLES, authenticate
from db import by_seq, new_row, serialize, store, touch
from errors import ApiError
from response import ok
from routes.common import paged
from services import calc, core

bp = Blueprint("agreements", __name__)

EMPLOYEE_MODELS = ("OWNER_EMPLOYEES", "MANAGER_EMPLOYEES")
CALL_REASONS = ("FLOOR_RESTORATION", "DISTRIBUTION_SHORTFALL", "CLAIM_ALLOCATION")
ENTRY_TYPES = ("CONTRIBUTION", "DISBURSEMENT", "DISBURSEMENT_REVERSAL")
SOURCE_KINDS = ("DISTRIBUTION_EXECUTION", "BRAND_DISPUTE_FUNDING", "BRAND_DISPUTE_RESCISSION")


# ---------------------------------------------------------------------------
# POST /hotel-management/agreements
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements")
def create_agreement():
    authenticate(["PlatformAdmin"])
    body = v.body()

    hotel_name = v.req_str(body, "hotel_name")
    owner_entity_name = v.req_str(body, "owner_entity_name")
    base_fee_pct = v.req_number(body, "base_fee_pct", gt=0, le="0.10", max_dp=4)
    incentive_fee_pct = v.req_number(body, "incentive_fee_pct", gt=0, le="0.50")
    owner_priority_cents = v.req_int(body, "owner_priority_cents", ge=0)

    incentive_tier2_pct = v.opt_number(body, "incentive_tier2_pct", default=0.15)
    if incentive_tier2_pct is not None:
        v.opt_number(body, "incentive_tier2_pct", ge=incentive_fee_pct)
    incentive_tier2_threshold_cents = v.opt_int(
        body, "incentive_tier2_threshold_cents", default=5000000, ge=0
    )
    ffe_reserve_pct = v.opt_number(body, "ffe_reserve_pct", default=0.04, ge=0, le="0.10")
    centralized_services_cap_pct = v.opt_number(
        body, "centralized_services_cap_pct", default=0.015, ge=0, le="0.10"
    )
    working_capital_floor_cents = v.opt_int(body, "working_capital_floor_cents", default=0, ge=0)
    initial_working_capital_cents = v.opt_int(
        body, "initial_working_capital_cents", default=0, ge=0
    )
    owner_review_window_days = v.opt_int(body, "owner_review_window_days", default=30, ge=1)
    max_revision_rounds = v.opt_int(body, "max_revision_rounds", default=2, ge=0)
    gop_test_threshold_pct = v.opt_number(body, "gop_test_threshold_pct", default=0.85, gt=0, le=2)
    rpi_test_threshold = v.opt_number(body, "rpi_test_threshold", default=90.0, gt=0)
    min_benchmark_months = v.opt_int(body, "min_benchmark_months", default=10, ge=1)
    test_periods_expected = v.opt_int(body, "test_periods_expected", default=12, ge=1)
    consecutive_failure_limit = v.opt_int(body, "consecutive_failure_limit", default=2, ge=1)
    manager_indemnity_cap_cents = v.opt_int(body, "manager_indemnity_cap_cents", default=0, ge=0)
    cure_window_days = v.opt_int(body, "cure_window_days", default=60, ge=1)
    dispute_standstill_days = v.opt_int(body, "dispute_standstill_days", default=45, ge=1)
    max_dispute_rounds = v.opt_int(body, "max_dispute_rounds", default=2, ge=1)
    funding_due_days = v.opt_int(body, "funding_due_days", default=15, ge=1)
    termination_notice_days = v.opt_int(body, "termination_notice_days", default=90, ge=1)

    # rule 4 -- every enum after every rule-3 check
    employee_model = v.opt_str(body, "employee_model", default="MANAGER_EMPLOYEES")
    v.check_enum(employee_model, EMPLOYEE_MODELS, "employee_model")

    row = new_row(
        {
            "hotel_name": hotel_name,
            "owner_entity_name": owner_entity_name,
            "status": "DRAFT",
            "base_fee_pct": base_fee_pct,
            "incentive_fee_pct": incentive_fee_pct,
            "incentive_tier2_pct": incentive_tier2_pct,
            "incentive_tier2_threshold_cents": incentive_tier2_threshold_cents,
            "owner_priority_cents": owner_priority_cents,
            "ffe_reserve_pct": ffe_reserve_pct,
            "centralized_services_cap_pct": centralized_services_cap_pct,
            "working_capital_floor_cents": working_capital_floor_cents,
            "working_capital_balance_cents": 0,
            "initial_working_capital_cents": initial_working_capital_cents,
            "ffe_reserve_balance_cents": 0,
            "manager_liability_accrued_cents": 0,
            "owner_review_window_days": owner_review_window_days,
            "max_revision_rounds": max_revision_rounds,
            "gop_test_threshold_pct": gop_test_threshold_pct,
            "rpi_test_threshold": rpi_test_threshold,
            "min_benchmark_months": min_benchmark_months,
            "test_periods_expected": test_periods_expected,
            "consecutive_failure_limit": consecutive_failure_limit,
            "performance_failure_streak": 0,
            "employee_model": employee_model,
            "manager_indemnity_cap_cents": manager_indemnity_cap_cents,
            "cure_window_days": cure_window_days,
            "dispute_standstill_days": dispute_standstill_days,
            "max_dispute_rounds": max_dispute_rounds,
            "funding_due_days": funding_due_days,
            "termination_notice_days": termination_notice_days,
            "distribution_hold": False,
            "termination_effective_utc": None,
        }
    )
    store.agreements[row["id"]] = row
    return ok(serialize(row), 201)


@bp.get("/hotel-management/agreements/<agreement_id>")
def read_agreement(agreement_id):
    authenticate(READ_ROLES)
    return ok(serialize(core.find_agreement(agreement_id)))


# ---------------------------------------------------------------------------
# POST /hotel-management/agreements/{id}/activate
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate(["PlatformAdmin"])
    v.body()
    agreement = core.find_agreement(agreement_id)
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "Only a DRAFT agreement can be activated.")

    agreement["status"] = "ACTIVE"
    agreement["working_capital_balance_cents"] = agreement["initial_working_capital_cents"]
    agreement["distribution_hold"] = False
    touch(agreement)
    return ok(serialize(agreement))


# ---------------------------------------------------------------------------
# GET /hotel-management/agreements/{id}/reserve-ledger
# ---------------------------------------------------------------------------

@bp.get("/hotel-management/agreements/<agreement_id>/reserve-ledger")
def list_reserve_ledger(agreement_id):
    authenticate(READ_ROLES)
    agreement = core.find_agreement(agreement_id)
    rows = core.reserve_entries_of(agreement["id"])
    entry_type = v.query_str("entry_type")
    source_kind = v.query_str("source_kind")
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    if source_kind is not None:
        rows = [r for r in rows if r["source_kind"] == source_kind]
    return paged(rows)


# ---------------------------------------------------------------------------
# Working capital calls
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements/<agreement_id>/working-capital-calls")
def create_call(agreement_id):
    authenticate(["HotelManagerOps"])
    body = v.body()
    amount_cents = v.req_int(body, "amount_cents", gt=0)
    reason = v.req_str(body, "reason")
    v.check_enum(reason, CALL_REASONS, "reason")

    agreement = core.find_agreement(agreement_id)
    core.require_active(agreement)

    call = core.create_working_capital_call(agreement, amount_cents, reason, False)
    return ok(serialize(call), 201)


@bp.get("/hotel-management/agreements/<agreement_id>/working-capital-calls")
def list_calls(agreement_id):
    authenticate(READ_ROLES)
    agreement = core.find_agreement(agreement_id)
    rows = core.calls_of(agreement["id"])
    status = v.query_str("status")
    reason = v.query_str("reason")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reason is not None:
        rows = [r for r in rows if r["reason"] == reason]
    return paged(rows)


@bp.post("/hotel-management/working-capital-calls/<call_id>/fund")
def fund_call(call_id):
    authenticate(["OwnerRep"])
    body = v.body()
    # rule 3 declares no bound for funded_amount_cents; any mismatch, including a
    # negative amount, is rule 47's business.
    funded_amount_cents = v.req_int(body, "funded_amount_cents")

    call = core.find_call(call_id)
    if call["status"] not in ("REQUESTED", "OVERDUE"):
        raise ApiError("ERR_INVALID_CALL_STATE")
    if funded_amount_cents != call["amount_cents"]:
        raise ApiError("ERR_FUNDING_AMOUNT_MISMATCH")

    agreement = core.find_agreement(call["agreement_id"])
    was_overdue = call["status"] == "OVERDUE"
    call["status"] = "FUNDED"
    call["funded_amount_cents"] = funded_amount_cents
    if was_overdue:
        call["late_funded"] = True
    touch(call)

    agreement["working_capital_balance_cents"] = (
        agreement["working_capital_balance_cents"] + call["amount_cents"]
    )
    touch(agreement)
    return ok(serialize(call))


# ---------------------------------------------------------------------------
# POST /hotel-management/agreements/{id}/annual-true-up
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements/<agreement_id>/annual-true-up")
def annual_true_up(agreement_id):
    authenticate(["HotelManagerOps"])
    body = v.body()
    fiscal_year = v.req_int(body, "fiscal_year", ge=2000, le=2100)
    expected_version = v.req_int(body, "expected_agreement_version")

    agreement = core.find_agreement(agreement_id)
    if expected_version != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION")
    core.require_active(agreement)

    accepted = [
        p
        for p in core.packages_of(agreement["id"])
        if p["fiscal_year"] == fiscal_year and p["financial_status"] == "ACCEPTED"
    ]
    if not accepted:
        raise ApiError("ERR_NO_ACCEPTED_PERIODS")

    annual_agop = sum(p["agop_cents"] for p in accepted)
    final_fee, _excess = calc.final_incentive_fee_cents(
        annual_agop,
        agreement["owner_priority_cents"],
        agreement["incentive_tier2_threshold_cents"],
        agreement["incentive_fee_pct"],
        agreement["incentive_tier2_pct"],
    )

    package_ids = {p["id"] for p in core.packages_of(agreement["id"])}
    agreement_accruals = by_seq(
        [a for a in store.fee_accruals.values() if a["report_package_id"] in package_ids]
    )
    provisional_total = sum(
        a["amount_cents"]
        for a in agreement_accruals
        if a["fiscal_year"] == fiscal_year
        and a["fee_type"] == "INCENTIVE"
        and a["variant"] == "PROVISIONAL"
        and a["status"] in ("ACCRUED", "INVOICED", "PAID")
    )
    delta = final_fee - provisional_total

    # reverse, then post -- exactly one live FINAL accrual per fiscal year
    for accrual in agreement_accruals:
        if (
            accrual["fiscal_year"] == fiscal_year
            and accrual["fee_type"] == "INCENTIVE"
            and accrual["variant"] == "FINAL"
            and accrual["status"] != "REVERSED"
        ):
            accrual["status"] = "REVERSED"
            touch(accrual)

    target = sorted(accepted, key=lambda p: (p["period_month"], p["_seq"]))[-1]
    new_accrual = core._new_accrual(target, "INCENTIVE", "FINAL", delta)

    touch(agreement)

    return ok(
        {
            "fiscal_year": fiscal_year,
            "accepted_period_count": len(accepted),
            "annual_agop_cents": annual_agop,
            "final_incentive_fee_cents": final_fee,
            "provisional_incentive_total_cents": provisional_total,
            "true_up_delta_cents": delta,
            "true_up_accrual_id": new_accrual["id"],
            "attached_report_package_id": target["id"],
        }
    )
