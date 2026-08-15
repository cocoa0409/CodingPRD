"""Business-logic services: calculations, cascades, serializers (PRD §3)."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

import db
from db import STORE, touch

getcontext().prec = 60

NONACCRUAL_DPD = 90
STALE_APPRAISAL_DAYS = 365
FORGIVENESS_CAP_BPS = 2500
BPS_DENOM = 10000
BPS_SQUARED_DENOM = 100000000
MONTHS_PER_YEAR = 12
COST_TIER_BPS = 1000  # 10% costs tier in the WATERFALL variant

CASES_NEVER_COVER = ("RELEASED", "LIQUIDATED")


# ---------------------------------------------------------------------------
# Integer rounding helpers (PRD §2.6: round half up to whole cents)
# ---------------------------------------------------------------------------

def round_half_up_div(numer, denom):
    """round_half_up(numer / denom) for non-negative integers, exact."""
    return (2 * numer + denom) // (2 * denom)


def liquidation_value(appraised_value_cents, liquidation_discount_bps):
    """multiply first, divide once by 10000, round once (half up)."""
    numer = appraised_value_cents * (BPS_DENOM - liquidation_discount_bps)
    return round_half_up_div(numer, BPS_DENOM)


def cecl_reserve(current_principal_cents, pd_bps, lgd_bps):
    """current * PD * LGD / 10^8, one chain, one division, round half up."""
    numer = current_principal_cents * pd_bps * lgd_bps
    return round_half_up_div(numer, BPS_SQUARED_DENOM)


def tdr_dcf_reserve(current_principal_cents, contractual_rate_bps, cash_flows):
    """Discount at the ORIGINAL contractual rate, monthly compounding.

    Per-period PVs are summed at full precision and rounded half-up exactly
    once after summation (PRD §2.6 / SCAFFOLD tdr_dcf_reserve).
    """
    r_monthly = Decimal(contractual_rate_bps) / Decimal(BPS_DENOM) / Decimal(MONTHS_PER_YEAR)
    pv = Decimal(0)
    for cf in sorted(cash_flows, key=lambda c: c["period_index"]):
        pv += Decimal(cf["amount_cents"]) / (Decimal(1) + r_monthly) ** cf["period_index"]
    pv_rounded = int(pv.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(0, current_principal_cents - pv_rounded)


def forgiveness_cap_exceeded(original_principal_cents, charged_off_cents, new_forgiveness_cents):
    """Cap = floor(original * 2500 / 10000); reject iff cumulative > cap."""
    cap = (original_principal_cents * FORGIVENESS_CAP_BPS) // BPS_DENOM
    return (charged_off_cents + new_forgiveness_cents) > cap


# ---------------------------------------------------------------------------
# Lookup helpers (nested path resolution is left-to-right, PRD §2.7)
# ---------------------------------------------------------------------------

def get_borrower(borrower_id):
    return STORE["borrowers"].get(borrower_id)


def get_loan(loan_id):
    return STORE["loans"].get(loan_id)


def get_case(case_id):
    return STORE["cases"].get(case_id)


def get_plan(plan_id):
    return STORE["plans"].get(plan_id)


def get_proposal(proposal_id):
    return STORE["proposals"].get(proposal_id)


def get_collateral(collateral_id):
    return STORE["collateral"].get(collateral_id)


def get_appraisal(appraisal_id):
    return STORE["appraisals"].get(appraisal_id)


def get_impairment(assessment_id):
    return STORE["impairments"].get(assessment_id)


def get_referral(referral_id):
    return STORE["referrals"].get(referral_id)


def get_charge_off(event_id):
    return STORE["charge_offs"].get(event_id)


def get_recovery(event_id):
    return STORE["recoveries"].get(event_id)


def get_exit_decision(decision_id):
    return STORE["exit_decisions"].get(decision_id)


def cases_of_loan(loan_id):
    return [c for c in STORE["cases"].values() if c["loan_id"] == loan_id]


def loans_of_borrower(borrower_id):
    return [l for l in STORE["loans"].values() if l["borrower_id"] == borrower_id]


def plans_of_case(case_id):
    return [p for p in STORE["plans"].values() if p["case_id"] == case_id]


def proposals_of_case(case_id):
    return [p for p in STORE["proposals"].values() if p["case_id"] == case_id]


def collateral_of_loan(loan_id):
    return [c for c in STORE["collateral"].values() if c["loan_id"] == loan_id]


def appraisals_of_collateral(collateral_id):
    return [a for a in STORE["appraisals"].values() if a["collateral_id"] == collateral_id]


def impairments_of_case(case_id):
    return [a for a in STORE["impairments"].values() if a["case_id"] == case_id]


def referrals_of_case(case_id):
    return [r for r in STORE["referrals"].values() if r["case_id"] == case_id]


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Derived-balance cascades (PRD §2.9)
# ---------------------------------------------------------------------------

def _lgd_target_case(loan_id):
    """The loan's single non-CLOSED case; else the most recent case."""
    cases = sorted_rows(cases_of_loan(loan_id))
    for case in reversed(cases):
        if case["status"] != "CLOSED":
            return case
    return cases[-1] if cases else None


def recompute_lgd(loan):
    """LGD = max(0, current_principal - cover) on the loan's target case.

    Cover = sum of current_liquidation_value_cents over items whose status is
    PLEDGED or UNDER_REVALUATION. Touches the case only when the value moves.
    """
    case = _lgd_target_case(loan["id"])
    if case is None:
        return
    cover = sum(
        item["current_liquidation_value_cents"]
        for item in collateral_of_loan(loan["id"])
        if item["status"] not in CASES_NEVER_COVER
    )
    new_lgd = max(0, loan["current_principal_cents"] - cover)
    if case["loss_given_default_cents"] != new_lgd:
        case["loss_given_default_cents"] = new_lgd
        touch(case)


def recompute_nonaccrual(loan):
    """nonaccrual = days_past_due >= 90 OR any case on the loan in LEGAL."""
    value = loan["days_past_due"] >= NONACCRUAL_DPD or any(
        c["status"] == "LEGAL" for c in cases_of_loan(loan["id"])
    )
    if loan["nonaccrual"] != value:
        loan["nonaccrual"] = value
        touch(loan)


def force_nonaccrual(loan):
    if not loan["nonaccrual"]:
        loan["nonaccrual"] = True
        touch(loan)


def book_charge_off(loan, case, amount_cents, reason_code):
    """Internal charge-off machinery (also used by the forgiveness cascade).

    Creates the immutable event, moves principal buckets, recomputes LGD.
    """
    is_partial = amount_cents < loan["current_principal_cents"]
    event = {
        "id": db.new_id(),
        "case_id": case["id"],
        "amount_cents": amount_cents,
        "reason_code": reason_code,
        "booked_at": db.fmt_clock(db.logical_now()),
        "is_partial": is_partial,
    }
    db.stamp_ledger(event)
    STORE["charge_offs"][event["id"]] = event
    loan["current_principal_cents"] -= amount_cents
    loan["charged_off_principal_cents"] += amount_cents
    touch(loan)
    recompute_lgd(loan)
    return event


def allocate_recovery(loan, case, amount_cents, allocation_mode):
    """Two sanctioned allocation orders (SCAFFOLD recovery_allocation).

    Returns (to_costs, to_charged_off, to_current, excess). Applies the bucket
    movements to the loan and the case's unapplied cash.
    """
    if allocation_mode == "CHRONOLOGICAL":
        to_costs = 0
        to_charged_off = min(amount_cents, loan["charged_off_principal_cents"])
        to_current = min(amount_cents - to_charged_off, loan["current_principal_cents"])
        excess = amount_cents - to_charged_off - to_current
    else:  # WATERFALL — costs tier first, 10% cap rounded half up
        to_costs = min(amount_cents, round_half_up_div(amount_cents, 10))
        remainder = amount_cents - to_costs
        to_charged_off = min(remainder, loan["charged_off_principal_cents"])
        to_current = min(remainder - to_charged_off, loan["current_principal_cents"])
        excess = remainder - to_charged_off - to_current

    loan["charged_off_principal_cents"] -= to_charged_off
    loan["current_principal_cents"] -= to_current
    touch(loan)

    if excess > 0:
        case["unapplied_cash_cents"] += excess
        touch(case)
    recompute_lgd(loan)
    return to_costs, to_charged_off, to_current, excess


def book_recovery(loan, case, amount_cents, recovery_source, allocation_mode):
    event = {
        "id": db.new_id(),
        "case_id": case["id"],
        "amount_cents": amount_cents,
        "recovery_source": recovery_source,
        "allocation_mode": allocation_mode,
        "booked_at": db.fmt_clock(db.logical_now()),
    }
    db.stamp_ledger(event)
    STORE["recoveries"][event["id"]] = event
    allocate_recovery(loan, case, amount_cents, allocation_mode)
    return event


def compute_tdr_flag(loan, case, proposal):
    concession = (
        proposal["concession_rate_bps"] < loan["contractual_rate_bps"]
        or proposal["principal_forgiveness_cents"] > 0
    )
    difficulty = case["risk_rating_at_entry"] >= 6 or loan["days_past_due"] >= 60
    return concession and difficulty


def exit_argmax(npv_foreclosure_cents, npv_deed_in_lieu_cents):
    """Higher NPV wins; an exact tie always resolves to DEED_IN_LIEU."""
    if npv_deed_in_lieu_cents >= npv_foreclosure_cents:
        return "DEED_IN_LIEU"
    return "FORECLOSURE"


# ---------------------------------------------------------------------------
# Serializers (explicit field lists — internal keys never leak)
# ---------------------------------------------------------------------------

def borrower_out(b):
    return {
        "id": b["id"],
        "legal_name": b["legal_name"],
        "tax_id": b["tax_id"],
        "naics_code": b["naics_code"],
        "internal_risk_rating": b["internal_risk_rating"],
        "guarantor_name": b["guarantor_name"],
        "guarantor_net_worth_cents": b["guarantor_net_worth_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def loan_out(l):
    return {
        "id": l["id"],
        "borrower_id": l["borrower_id"],
        "loan_number": l["loan_number"],
        "original_principal_cents": l["original_principal_cents"],
        "current_principal_cents": l["current_principal_cents"],
        "contractual_rate_bps": l["contractual_rate_bps"],
        "days_past_due": l["days_past_due"],
        "is_tdr": l["is_tdr"],
        "nonaccrual": l["nonaccrual"],
        "charged_off_principal_cents": l["charged_off_principal_cents"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def case_out(c):
    return {
        "id": c["id"],
        "loan_id": c["loan_id"],
        "entry_trigger": c["entry_trigger"],
        "risk_rating_at_entry": c["risk_rating_at_entry"],
        "case_officer_id": c["case_officer_id"],
        "loss_given_default_cents": c["loss_given_default_cents"],
        "impairment_reserve_cents": c["impairment_reserve_cents"],
        "tdr_status": c["tdr_status"],
        "unapplied_cash_cents": c["unapplied_cash_cents"],
        "resolution_path": c["resolution_path"],
        "status": c["status"],
        "version_anchor": c["version"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def plan_out(p):
    return {
        "id": p["id"],
        "case_id": p["case_id"],
        "plan_text": p["plan_text"],
        "target_resolution_date": p["target_resolution_date"],
        "milestone_count": p["milestone_count"],
        "supersedes_plan_id": p["supersedes_plan_id"],
        "approval_round": p["approval_round"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def proposal_out(p):
    return {
        "id": p["id"],
        "case_id": p["case_id"],
        "proposal_kind": p["proposal_kind"],
        "concession_rate_bps": p["concession_rate_bps"],
        "term_extension_months": p["term_extension_months"],
        "principal_forgiveness_cents": p["principal_forgiveness_cents"],
        "borrower_concession_cents": p["borrower_concession_cents"],
        "tdr_flag": p["tdr_flag"],
        "negotiation_round": p["negotiation_round"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def collateral_out(c):
    return {
        "id": c["id"],
        "loan_id": c["loan_id"],
        "collateral_type": c["collateral_type"],
        "description": c["description"],
        "liquidation_discount_bps": c["liquidation_discount_bps"],
        "current_appraised_value_cents": c["current_appraised_value_cents"],
        "current_liquidation_value_cents": c["current_liquidation_value_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def appraisal_out(a):
    return {
        "id": a["id"],
        "collateral_id": a["collateral_id"],
        "appraised_value_cents": a["appraised_value_cents"],
        "effective_date": a["effective_date"],
        "appraiser_id": a["appraiser_id"],
        "staleness_days": a["staleness_days"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def impairment_out(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "method": a["method"],
        "probability_of_default_bps": a["probability_of_default_bps"],
        "loss_given_default_bps": a["loss_given_default_bps"],
        "expected_cash_flows": a["expected_cash_flows"],
        "computed_reserve_cents": a["computed_reserve_cents"],
        "is_active": a["is_active"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def referral_out(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "referral_kind": r["referral_kind"],
        "target_guarantor_name": r["target_guarantor_name"],
        "demand_amount_cents": r["demand_amount_cents"],
        "statute_deadline": r["statute_deadline"],
        "decision_rationale": r["decision_rationale"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def charge_off_out(e):
    return {
        "id": e["id"],
        "case_id": e["case_id"],
        "amount_cents": e["amount_cents"],
        "reason_code": e["reason_code"],
        "booked_at": e["booked_at"],
        "is_partial": e["is_partial"],
        "created_at": e["created_at"],
    }


def recovery_out(e):
    return {
        "id": e["id"],
        "case_id": e["case_id"],
        "amount_cents": e["amount_cents"],
        "recovery_source": e["recovery_source"],
        "allocation_mode": e["allocation_mode"],
        "booked_at": e["booked_at"],
        "created_at": e["created_at"],
    }


def exit_decision_out(d):
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "chosen_path": d["chosen_path"],
        "npv_foreclosure_cents": d["npv_foreclosure_cents"],
        "npv_deed_in_lieu_cents": d["npv_deed_in_lieu_cents"],
        "decision_rule_outcome": d["decision_rule_outcome"],
        "override_justification": d["override_justification"],
        "decided_at": d["decided_at"],
        "created_at": d["created_at"],
    }
