"""CapitalDistributionRequest endpoints (PRD 3.6)."""

from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint

from db import (
    distribution_requests, capital_plans, reporting_periods, stamp_new, touch,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_CROSS_BANK_REFERENCE, ERR_PCA_BLOCKS_DISTRIBUTION,
    ERR_TEMPORAL_VIOLATION, ERR_DISTRIBUTION_EXCEEDS_MDBA,
    ERR_DISTRIBUTION_NOT_YET_PAYABLE,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_distribution, get_bank, get_distribution, bump_bank, clock_today,
    PCA_PASSING, DISTRIBUTION_WINDOW_DAYS,
    release_distribution_reservation, recompute_mdba,
)
from util import (
    get_body, req_int, req_date, req_enum, apply_filters, sorted_page,
    require_occ_field, check_occ_matches,
)

bp = Blueprint("distributions", __name__)

QUARTER_MONTHS = {"Q1": (1, 3), "Q2": (4, 6), "Q3": (7, 9), "Q4": (10, 12)}
PLAN_STATES_ALLOWING_PROPOSALS = {"DRAFT", "BOARD_REVIEW", "SUBMITTED", "SUPERVISORY_REVIEW", "APPROVED"}


def _quarter_bounds(period: dict) -> tuple[date, date]:
    m_start, m_end = QUARTER_MONTHS[period["period_quarter"]]
    start = date(period["period_year"], m_start, 1)
    if m_end == 12:
        end = date(period["period_year"], 12, 31)
    else:
        end = date(period["period_year"], m_end + 1, 1) - timedelta(days=1)
    return start, end


@bp.route("/banks/<bankId>/distribution-requests", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_distribution(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    body = get_body()
    plan_id = body.get("capital_plan_id")
    period_id = body.get("reporting_period_id")
    kind = req_enum(body, "distribution_kind", {"DIVIDEND", "BUYBACK"})
    amount = req_int(body, "distribution_amount_cents")
    if amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "distribution_amount_cents must be positive")
    payment = req_date(body, "proposed_payment_date")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: capital_plan_id")
    if not isinstance(period_id, str) or not period_id:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: reporting_period_id")
    # Cross-bank referential integrity (priority 4).
    plan = capital_plans.get(plan_id)
    if plan is None or plan["bank_id"] != bank["id"]:
        raise_err(ERR_CROSS_BANK_REFERENCE, "capital_plan_id not owned by this bank")
    period = reporting_periods.get(period_id)
    if period is None or period["bank_id"] != bank["id"]:
        raise_err(ERR_CROSS_BANK_REFERENCE, "reporting_period_id not owned by this bank")
    # State (priority 5): plan must be in a proposal-accepting state.
    if plan["status"] not in PLAN_STATES_ALLOWING_PROPOSALS:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Attached CapitalPlan does not accept new distribution requests in its state")
    # Temporal window (priority 9): payment within the period's quarter, >= today.
    q_start, q_end = _quarter_bounds(period)
    if payment < q_start or payment > q_end:
        raise_err(ERR_TEMPORAL_VIOLATION,
                  "proposed_payment_date must fall within the reporting period's quarter")
    if payment < clock_today():
        raise_err(ERR_TEMPORAL_VIOLATION, "proposed_payment_date must not precede the current date")

    dist = {
        "bank_id": bank["id"],
        "capital_plan_id": plan["id"],
        "reporting_period_id": period["id"],
        "distribution_kind": kind,
        "distribution_amount_cents": amount,
        "capacity_reserved_cents": 0,
        "executed_amount_cents": 0,
        "status": "PROPOSED",
        "_proposed_payment_date": payment,
    }
    stamp_new(dist)
    distribution_requests[dist["id"]] = dist
    return success_object(ser_distribution(dist), 201)


@bp.route("/banks/<bankId>/distribution-requests/<requestId>", methods=["GET"])
@require_roles("Any")
def get_one_distribution(bankId: str, requestId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    return success_object(ser_distribution(get_distribution(bank, requestId)))


@bp.route("/banks/<bankId>/distribution-requests", methods=["GET"])
@require_roles("Any")
def list_distributions(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [d for d in distribution_requests.values() if d["bank_id"] == bank["id"]]
    items = apply_filters(items, {
        "capital_plan_id": "capital_plan_id",
        "reporting_period_id": "reporting_period_id",
        "status": "status",
        "distribution_kind": "distribution_kind",
    })
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_distribution(d) for d in page], limit, offset, total)


@bp.route("/banks/<bankId>/distribution-requests/<requestId>/approve", methods=["POST"])
@require_roles("CapitalAnalyst")
def approve_distribution(bankId: str, requestId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    dist = get_distribution(bank, requestId)
    # Envelope-level: expected_bank_version presence/type (PRD 2.8 requires it).
    body = get_body()
    expected = require_occ_field(body)
    # State (priority 5).
    if dist["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PROPOSED request can be approved")
    plan = capital_plans.get(dist["capital_plan_id"])
    # PRD 3.6: "The attached plan must have reached APPROVED" — EFFECTIVE has
    # passed through APPROVED and also qualifies.
    if plan is None or plan["status"] not in ("APPROVED", "EFFECTIVE"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Attached CapitalPlan must have reached APPROVED")
    # PCA gate (priority 6).
    if bank["pca_bucket"] not in PCA_PASSING:
        raise_err(ERR_PCA_BLOCKS_DISTRIBUTION, "PCA bucket blocks distribution approval")
    # Temporal (priority 9).
    if dist["_proposed_payment_date"] < clock_today():
        raise_err(ERR_TEMPORAL_VIOLATION, "proposed_payment_date precedes the current date")
    # Capacity (priority 10): mdba_cents - pending_distribution_cents >= amount (PRD 3.6).
    if bank["mdba_cents"] - bank["pending_distribution_cents"] < dist["distribution_amount_cents"]:
        raise_err(ERR_DISTRIBUTION_EXCEEDS_MDBA,
                  "Distribution exceeds the uncommitted maximum distributable amount")
    # OCC (priority 19).
    check_occ_matches(expected, bank)

    dist["status"] = "APPROVED_NOT_EXECUTED"
    dist["capacity_reserved_cents"] = dist["distribution_amount_cents"]
    touch(dist)
    bank["pending_distribution_cents"] = bank.get("pending_distribution_cents", 0) + dist["distribution_amount_cents"]
    recompute_mdba(bank)
    bump_bank(bank)
    return success_object(ser_distribution(dist))


@bp.route("/banks/<bankId>/distribution-requests/<requestId>/execute", methods=["POST"])
@require_roles("CapitalAnalyst")
def execute_distribution(bankId: str, requestId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    dist = get_distribution(bank, requestId)
    if dist["status"] != "APPROVED_NOT_EXECUTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an APPROVED_NOT_EXECUTED request can be executed")
    # PCA re-check (priority 6).
    if bank["pca_bucket"] not in PCA_PASSING:
        raise_err(ERR_PCA_BLOCKS_DISTRIBUTION, "PCA bucket blocks distribution execution")
    # Temporal window (priority 9).
    today = clock_today()
    pay = dist["_proposed_payment_date"]
    if today < pay:
        raise_err(ERR_DISTRIBUTION_NOT_YET_PAYABLE, "Current time is before proposed_payment_date")
    if today > pay + timedelta(days=DISTRIBUTION_WINDOW_DAYS):
        # Window closed: the clock should have expired it; guard anyway.
        release_distribution_reservation(dist, bank)
        dist["status"] = "EXPIRED"
        touch(dist)
        recompute_mdba(bank)
        bump_bank(bank)
        raise_err(ERR_TEMPORAL_VIOLATION, "Distribution payment window has closed")

    amount = dist["distribution_amount_cents"]
    dist["executed_amount_cents"] = amount
    dist["status"] = "EXECUTED"
    touch(dist)
    bank["pending_distribution_cents"] = max(0, bank.get("pending_distribution_cents", 0) - amount)
    # Capacity is consumed, not merely reserved: debit mdba directly (PRD 3.6).
    bank["mdba_cents"] = bank["mdba_cents"] - amount
    bump_bank(bank)
    return success_object(ser_distribution(dist))


@bp.route("/banks/<bankId>/distribution-requests/<requestId>/reject", methods=["POST"])
@require_roles("CapitalAnalyst")
def reject_distribution(bankId: str, requestId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    dist = get_distribution(bank, requestId)
    if dist["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PROPOSED request can be rejected")
    dist["status"] = "REJECTED"
    touch(dist)
    return success_object(ser_distribution(dist))


@bp.route("/banks/<bankId>/distribution-requests/<requestId>/withdraw", methods=["POST"])
@require_roles("CapitalAnalyst")
def withdraw_distribution(bankId: str, requestId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    dist = get_distribution(bank, requestId)
    if dist["status"] != "APPROVED_NOT_EXECUTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an APPROVED_NOT_EXECUTED request can be withdrawn")
    release_distribution_reservation(dist, bank)
    dist["status"] = "WITHDRAWN"
    touch(dist)
    recompute_mdba(bank)
    bump_bank(bank)
    return success_object(ser_distribution(dist))
