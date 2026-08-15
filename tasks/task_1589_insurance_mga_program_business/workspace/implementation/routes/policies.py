"""Policies: quote/bind/issue/cancel/reinstate/final-audit plus premium
collections (PRD sections 3.4, 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch, now_dt
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_PROGRAM_NOT_ACTIVE, ERR_INVALID_REQUEST,
    ERR_POLICY_WINDOW_OUTSIDE_FILING, ERR_QUOTE_EXPIRED, ERR_STATE_NOT_COVERED,
    ERR_CLASS_NOT_ELIGIBLE, ERR_GUIDELINE_PREMIUM_LIMIT,
    ERR_GUIDELINE_LIMIT_EXCEEDED, ERR_NO_EFFECTIVE_FILING, ERR_CLASS_NOT_FILED,
    ERR_NO_ACTIVE_ALLOCATION, ERR_TRANCHE_EXHAUSTED, ERR_CAPACITY_EXCEEDED,
    ERR_PREMIUM_NOT_COLLECTED, ERR_REINSTATE_WINDOW_CLOSED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.guidelines import active_guideline
from routes.programs import require_program_not_terminal
from services import capacity, trust
from services.pricing import compute_premium_cents
from validation import (
    get_body, req_str, req_int, req_int_pos, req_datetime, opt_number, opt_str,
    req_enum, req_number,
)

bp = Blueprint("policies", __name__)

QUOTE_VALID_DAYS = 30
REINSTATE_WINDOW_DAYS = 30
CANCELLATION_REASONS = {"INSURED_REQUEST", "CARRIER_REQUEST", "NON_PAYMENT"}


def _require_program_active_for_policy(program):
    """Terminal check is always evaluated before the merely-not-active check."""
    require_program_not_terminal(program)
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Operation requires program status ACTIVE (current: %s)." % program["status"])


@bp.post("/mga/programs/<programId>/policies")
def quote_policy(programId):
    require_roles("MGAUnderwriter")
    program = get_or_404(STORE.programs, programId, "Program")
    body = get_body()
    insured_name = req_str(body, "insured_name")
    state_code = req_str(body, "state_code")
    class_code = req_str(body, "class_code")
    exposure_units = req_int(body, "exposure_units")
    if exposure_units < 1:
        raise_err(ERR_INVALID_REQUEST, "Field 'exposure_units' must be at least 1.")
    coverage_limit_cents = req_int_pos(body, "coverage_limit_cents")
    effective_from = req_datetime(body, "effective_from")
    effective_to = req_datetime(body, "effective_to")
    if effective_from >= effective_to:
        raise_err(ERR_INVALID_REQUEST, "effective_from must be strictly before effective_to.")
    experience_mod = opt_number(body, "experience_mod", 1.0)
    clock = now_dt()

    # Stage 7: state legality (terminal before not-active).
    _require_program_active_for_policy(program)

    # Stage 9: temporal — policy window must sit inside the half-open window
    # of an EFFECTIVE filing for program+state; effective_from may not precede
    # the clock.
    if effective_from < clock:
        raise_err(ERR_POLICY_WINDOW_OUTSIDE_FILING, "Policy effective_from precedes the current clock.")
    effective_filings = [
        f for f in STORE.rate_filings.values()
        if f["program_id"] == program["id"]
        and f["state_code"] == state_code
        and f["status"] == "EFFECTIVE"
    ]
    covering = [
        f for f in effective_filings
        if f["effective_from"] <= effective_from and effective_to <= f["effective_to"]
    ]
    if effective_filings and not covering:
        raise_err(
            ERR_POLICY_WINDOW_OUTSIDE_FILING,
            "Policy window is not inside any EFFECTIVE filing's half-open window.",
        )

    # Stage 10: business constraints.
    if state_code not in program["states_covered"]:
        raise_err(ERR_STATE_NOT_COVERED, "State '%s' is not in the program's states_covered." % state_code)
    guideline = active_guideline(program["id"], state_code, class_code)
    if guideline is None:
        raise_err(ERR_CLASS_NOT_ELIGIBLE, "No ACTIVE guideline for (%s, %s)." % (state_code, class_code))
    filing = covering[0] if covering else None
    gross = commission = None
    if filing is not None and class_code in filing["base_rates"]:
        gross, commission = compute_premium_cents(
            exposure_units,
            filing["base_rates"][class_code],
            experience_mod,
            filing["policy_fee_cents"],
            guideline["min_policy_premium_cents"],
            program["commission_rate_pct"],
        )
        if gross > guideline["max_policy_premium_cents"]:
            raise_err(
                ERR_GUIDELINE_PREMIUM_LIMIT,
                "Computed gross premium %d exceeds the guideline cap %d."
                % (gross, guideline["max_policy_premium_cents"]),
            )
    if coverage_limit_cents > guideline["max_policy_limit_cents"]:
        raise_err(
            ERR_GUIDELINE_LIMIT_EXCEEDED,
            "coverage_limit_cents %d exceeds the guideline limit %d."
            % (coverage_limit_cents, guideline["max_policy_limit_cents"]),
        )

    # Stage 11: referential availability.
    if filing is None:
        raise_err(ERR_NO_EFFECTIVE_FILING, "No EFFECTIVE rate filing for program+state '%s'." % state_code)
    if class_code not in filing["base_rates"]:
        raise_err(ERR_CLASS_NOT_FILED, "Class '%s' is not present in the EFFECTIVE filing's base_rates." % class_code)

    p = new_entity()
    p.update({
        "program_id": program["id"],
        "filing_id": filing["id"],
        "insured_name": insured_name,
        "state_code": state_code,
        "class_code": class_code,
        "exposure_units": exposure_units,
        "coverage_limit_cents": coverage_limit_cents,
        "experience_mod": experience_mod,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "QUOTED",
        "audit_status": "NOT_AUDITED",
        "gross_premium_cents": gross,
        "final_premium_cents": None,
        "mga_commission_cents": commission,
        "collected_cents": 0,
        "earned_premium_cents": 0,
        "quote_valid_until": clock + timedelta(days=QUOTE_VALID_DAYS),
        "bound_at": None,
        "issued_at": None,
        "cancelled_at": None,
        "cancellation_date": None,
        "cancellation_reason": None,
        "pre_cancel_status": None,
        "capacity_released_cents": 0,
        "reported_premium_bordereau_id": None,
    })
    STORE.policies[p["id"]] = p
    return success_object(serialize.policy(p), status=201)


@bp.get("/mga/programs/<programId>/policies")
def list_program_policies(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = filter_query(
        [p for p in STORE.policies.values() if p["program_id"] == programId],
        status=request.args.get("status"),
    )
    return render_list(items, serialize.policy)


@bp.get("/mga/policies/<policyId>")
def get_policy(policyId):
    require_roles(*ALL_ROLES)
    p = get_or_404(STORE.policies, policyId, "Policy")
    return success_object(serialize.policy(p))


@bp.get("/mga/policies")
def list_policies():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.policies.values()),
        program_id=request.args.get("program_id"),
        filing_id=request.args.get("filing_id"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.policy)


@bp.post("/mga/policies/<policyId>/bind")
def bind_policy(policyId):
    require_roles("MGAUnderwriter")
    p = get_or_404(STORE.policies, policyId, "Policy")
    program = STORE.programs[p["program_id"]]
    if p["status"] != "QUOTED":
        raise_err(ERR_INVALID_STATE, "Only a QUOTED policy can be bound.")
    _require_program_active_for_policy(program)
    if now_dt() > p["quote_valid_until"]:
        raise_err(ERR_QUOTE_EXPIRED, "The quote validity window has lapsed.")
    guideline = active_guideline(program["id"], p["state_code"], p["class_code"])
    if guideline is None or p["gross_premium_cents"] > guideline["max_policy_premium_cents"]:
        raise_err(ERR_GUIDELINE_PREMIUM_LIMIT, "Gross premium no longer fits the ACTIVE guideline's premium cap.")
    tranche = capacity.current_tranche(program["id"])
    if tranche is None:
        raise_err(ERR_NO_ACTIVE_ALLOCATION, "No non-terminal capacity allocation exists for the program.")
    gross = p["gross_premium_cents"]
    if tranche["allocated_cents"] - tranche["consumed_cents"] < gross:
        raise_err(ERR_TRANCHE_EXHAUSTED, "Tranche available capacity is below the gross premium.")
    if capacity.aggregate_available(program) < gross:
        raise_err(ERR_CAPACITY_EXCEEDED, "Program aggregate headroom is below the gross premium.")
    p["status"] = "BOUND"
    p["bound_at"] = now_dt()
    capacity.consume(tranche, gross)
    program["consumed_aggregate_cents"] += gross
    touch(p)
    return success_object(serialize.policy(p))


@bp.post("/mga/policies/<policyId>/issue")
def issue_policy(policyId):
    require_roles("MGAUnderwriter")
    p = get_or_404(STORE.policies, policyId, "Policy")
    if p["status"] != "BOUND":
        raise_err(ERR_INVALID_STATE, "Only a BOUND policy can be issued.")
    if p["collected_cents"] < p["gross_premium_cents"]:
        raise_err(ERR_PREMIUM_NOT_COLLECTED, "Issuance requires collected_cents >= gross_premium_cents.")
    p["status"] = "ISSUED"
    p["issued_at"] = now_dt()
    touch(p)
    return success_object(serialize.policy(p))


@bp.post("/mga/policies/<policyId>/cancel")
def cancel_policy(policyId):
    require_roles("MGAUnderwriter")
    p = get_or_404(STORE.policies, policyId, "Policy")
    body = get_body()
    cancellation_date = req_datetime(body, "cancellation_date")
    reason = req_enum(body, "reason", CANCELLATION_REASONS)
    if cancellation_date > p["effective_to"]:
        raise_err(ERR_INVALID_REQUEST, "cancellation_date may not fall after the policy's effective_to.")
    if p["status"] not in ("BOUND", "ISSUED"):
        raise_err(ERR_INVALID_STATE, "Only a BOUND or ISSUED policy can be cancelled.")
    p["pre_cancel_status"] = p["status"]
    p["status"] = "PENDING_CANCELLATION"
    p["cancellation_date"] = cancellation_date
    p["cancellation_reason"] = reason
    touch(p)
    return success_object(serialize.policy(p))


@bp.post("/mga/policies/<policyId>/reinstate")
def reinstate_policy(policyId):
    require_roles("MGAUnderwriter")
    p = get_or_404(STORE.policies, policyId, "Policy")
    program = STORE.programs[p["program_id"]]
    if p["status"] != "CANCELLED":
        raise_err(ERR_INVALID_STATE, "Only a CANCELLED policy can be reinstated.")
    _require_program_active_for_policy(program)
    if now_dt() - p["cancelled_at"] > timedelta(days=REINSTATE_WINDOW_DAYS):
        raise_err(ERR_REINSTATE_WINDOW_CLOSED, "More than 30 days have passed since cancellation.")
    tranche = capacity.current_tranche(program["id"])
    if tranche is None:
        raise_err(ERR_NO_ACTIVE_ALLOCATION, "No non-terminal capacity allocation exists for the program.")
    amount = p["capacity_released_cents"]
    if tranche["allocated_cents"] - tranche["consumed_cents"] < amount:
        raise_err(ERR_TRANCHE_EXHAUSTED, "Tranche available capacity is below the released amount to re-consume.")
    if capacity.aggregate_available(program) < amount:
        raise_err(ERR_CAPACITY_EXCEEDED, "Program aggregate headroom is below the released amount to re-consume.")
    target = p["pre_cancel_status"]
    if target == "ISSUED" and p["collected_cents"] < p["gross_premium_cents"]:
        raise_err(ERR_PREMIUM_NOT_COLLECTED, "Reinstatement to ISSUED requires collected_cents >= gross_premium_cents.")
    capacity.consume(tranche, amount)
    program["consumed_aggregate_cents"] += amount
    # No reinstatement premium is repaid through this endpoint, so no ledger
    # entry is posted; the cancellation refund stands.
    p["status"] = target
    p["cancelled_at"] = None
    p["cancellation_date"] = None
    p["cancellation_reason"] = None
    p["pre_cancel_status"] = None
    p["capacity_released_cents"] = 0
    touch(p)
    return success_object(serialize.policy(p))


@bp.post("/mga/policies/<policyId>/final-audit")
def final_audit_policy(policyId):
    require_roles("MGAUnderwriter")
    p = get_or_404(STORE.policies, policyId, "Policy")
    body = get_body()
    actual_exposure_units = req_int(body, "actual_exposure_units")
    if actual_exposure_units < 1:
        raise_err(ERR_INVALID_REQUEST, "Field 'actual_exposure_units' must be at least 1.")
    actual_experience_mod = req_number(body, "actual_experience_mod")
    if p["status"] not in ("ISSUED", "EXPIRED"):
        raise_err(ERR_INVALID_STATE, "Final audit requires policy status ISSUED or EXPIRED.")
    if p["audit_status"] != "NOT_AUDITED":
        raise_err(ERR_INVALID_STATE, "Policy has already been final-audited.")
    program = STORE.programs[p["program_id"]]
    filing = STORE.rate_filings[p["filing_id"]]
    base_rate = filing["base_rates"].get(p["class_code"], 0)
    guideline = active_guideline(program["id"], p["state_code"], p["class_code"])
    min_floor = guideline["min_policy_premium_cents"] if guideline is not None else 0
    final_premium, _ = compute_premium_cents(
        actual_exposure_units,
        base_rate,
        actual_experience_mod,
        filing["policy_fee_cents"],
        min_floor,
        program["commission_rate_pct"],
    )
    p["final_premium_cents"] = final_premium
    delta = final_premium - p["gross_premium_cents"]
    if delta > 0:
        trust.post_entry(program, "COLLECTION", delta, policy=p)
    elif delta < 0:
        trust.post_entry(program, "REFUND", delta, policy=p)
    tranche = capacity.current_tranche(program["id"])
    if tranche is not None:
        tranche["consumed_cents"] = max(0, tranche["consumed_cents"] + delta)
        capacity.reconcile_tranche(tranche)
        touch(tranche)
    program["consumed_aggregate_cents"] = max(0, program["consumed_aggregate_cents"] + delta)
    p["audit_status"] = "AUDITED"
    touch(p)
    return success_object(serialize.policy(p))


@bp.post("/mga/policies/<policyId>/collections")
def record_collection(policyId):
    require_roles("MGAFinance")
    p = get_or_404(STORE.policies, policyId, "Policy")
    body = get_body()
    amount_cents = req_int_pos(body, "amount_cents")
    memo = opt_str(body, "memo")
    program = STORE.programs[p["program_id"]]
    entry = trust.post_entry(program, "COLLECTION", amount_cents, policy=p, memo=memo)
    touch(p)
    return success_object(serialize.ledger_entry(entry), status=201)
