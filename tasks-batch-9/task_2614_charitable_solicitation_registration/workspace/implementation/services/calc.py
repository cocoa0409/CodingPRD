"""Every derived quantity in the system (PRD 2.6, 3.2, 3.3, 3.5, 3.6, 3.7, 3.9).

Clients supply facts; this module supplies consequences.  Rounding order is
observable in this domain, so each function performs its rounding exactly at the
step the PRD pins it to.
"""
import math

import clock
from dates import (add_days, add_months, fiscal_year_end, fmt, midnight, parse_iso,
                   whole_days_between)
from db import db
from money import dec, round_half_up_cents, round_half_up_ratio

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
INITIAL_FILING_MULTIPLIER = dec("1.5")
TIER_1_UPPER_EXCLUSIVE_CENTS = 2500000
TIER_2_UPPER_EXCLUSIVE_CENTS = 10000000
TIER_3_UPPER_EXCLUSIVE_CENTS = 50000000
TIER_1_BASE_CENTS = 2500
TIER_2_BASE_CENTS = 5000
TIER_3_BASE_CENTS = 15000
TIER_4_BASE_CENTS = 40000

DAYS_PER_ACCRUAL_MONTH = 30

DISCOUNT_TIER_2_MIN_CENTS = 20000
DISCOUNT_TIER_3_MIN_CENTS = 50000
DISCOUNT_TIER_2_PCT = dec("0.10")
DISCOUNT_TIER_3_PCT = dec("0.20")

IRS_990_EXTENSION_DAYS = 180

CONTRACT_FILING_HARD_STOP_DAYS = 60
LATE_CONTRACT_SURCHARGE_CENTS = 10000

# NONE is weakest, REVIEW sits above it, AUDIT is strongest.
ASSURANCE_RANK = {"NONE": 0, "REVIEW": 1, "AUDIT": 2}


# ---------------------------------------------------------------------------
# renewal_deadline_derivation
# ---------------------------------------------------------------------------
def renewal_due_date(fiscal_year, fiscal_year_end_month, renewal_due_rule):
    """Derive the unextended renewal deadline (PRD 3.3).

    Month arithmetic runs FIRST and clamps an overflowing day-of-month down to
    the last day of the target month; day arithmetic runs SECOND.  The order is
    observable: a December 2025 fiscal year end under FYE_PLUS_4M_15D advances to
    2026-04-30 (day clamped from 31 to 30) and only then adds fifteen days,
    reaching 2026-05-15.
    """
    fye_end = fiscal_year_end(fiscal_year, fiscal_year_end_month)
    if renewal_due_rule == "FYE_PLUS_4M_15D":
        anchor = add_months(fye_end, 4)
        return add_days(anchor, 15)
    if renewal_due_rule == "FYE_PLUS_6M":
        return add_months(fye_end, 6)
    # CALENDAR_MAY_15 ignores the fiscal month entirely.
    return midnight(fye_end.year + 1, 5, 15)


def granted_extension_days(registration_id):
    """The granted_days of the one GRANTED extension request on this filing.

    At most one request per filing can hold GRANTED, because creating a new
    request supersedes every earlier one.
    """
    for row in db.extension_requests.values():
        if row["registration_id"] == registration_id and row["status"] == "GRANTED":
            return row["granted_days"]
    return None


def recompute_deadlines(registration):
    """Recompute renewal_due_date, extended_due_date and effective_due_date."""
    organization = db.organizations[registration["organization_id"]]
    profile = db.state_profiles[registration["state_code"]]
    base = renewal_due_date(
        registration["fiscal_year"],
        organization["fiscal_year_end_month"],
        profile["renewal_due_rule"],
    )
    registration["renewal_due_date"] = fmt(base)
    days = granted_extension_days(registration["id"])
    if days is None:
        registration["extended_due_date"] = None
    else:
        registration["extended_due_date"] = fmt(add_days(base, days))
    registration["effective_due_date"] = (
        registration["extended_due_date"] or registration["renewal_due_date"]
    )
    return registration


# ---------------------------------------------------------------------------
# assurance_requirement_derivation
# ---------------------------------------------------------------------------
def assurance_requirement(statement, profile):
    """Ladder the state's measured metric against its two thresholds (PRD 3.2).

    Both comparisons are inclusive at the threshold.  The statement is read
    regardless of its statement_status, and no sibling statement participates.
    """
    if profile["assurance_basis"] == "CONTRIBUTIONS_ONLY":
        metric = statement["contributions_cents"]
    else:  # GROSS_REVENUE
        metric = statement["total_revenue_cents"]
    if metric >= profile["audit_threshold_cents"]:
        return "AUDIT"
    if metric >= profile["review_threshold_cents"]:
        return "REVIEW"
    return "NONE"


def recompute_attestation(registration):
    statement = db.financial_statements[registration["financial_statement_id"]]
    profile = db.state_profiles[registration["state_code"]]
    registration["required_financial_attestation"] = assurance_requirement(statement, profile)
    return registration["required_financial_attestation"]


# ---------------------------------------------------------------------------
# filing_fee_assessment
# ---------------------------------------------------------------------------
def _contributions_tier_base(contributions_cents):
    if contributions_cents < TIER_1_UPPER_EXCLUSIVE_CENTS:
        return TIER_1_BASE_CENTS
    if contributions_cents < TIER_2_UPPER_EXCLUSIVE_CENTS:
        return TIER_2_BASE_CENTS
    if contributions_cents < TIER_3_UPPER_EXCLUSIVE_CENTS:
        return TIER_3_BASE_CENTS
    return TIER_4_BASE_CENTS


def filed_contract_count_in_state(organization_id, state_code):
    """Contracts of this charity in FILED or LATE_FILED naming this state.

    Contracts still in DRAFT and contracts already VOIDED are excluded, and the
    count is taken at the moment of evaluation with no time window.
    """
    total = 0
    for contract in db.fundraising_contracts.values():
        if contract["organization_id"] != organization_id:
            continue
        if contract["status"] not in ("FILED", "LATE_FILED"):
            continue
        if state_code in contract["state_codes"]:
            total += 1
    return total


def filing_fee(registration):
    """Four components combined non-linearly (PRD 3.3).

    The three additive components are summed into a raw amount; only then is the
    INITIAL multiplier applied and rounded half up; only then is the clamp
    applied.  Clamping before the multiplier would produce a different fee
    whenever the cap binds.
    """
    statement = db.financial_statements[registration["financial_statement_id"]]
    profile = db.state_profiles[registration["state_code"]]
    organization = db.organizations[registration["organization_id"]]

    tier_base = _contributions_tier_base(statement["contributions_cents"])

    if organization["has_online_donation_page"] and profile["online_presence_counts"]:
        online_surcharge = profile["online_surcharge_cents"]
    else:
        online_surcharge = 0

    contract_component = profile["per_contract_fee_cents"] * filed_contract_count_in_state(
        organization["id"], profile["state_code"]
    )

    raw = tier_base + online_surcharge + contract_component
    if registration["registration_type"] == "INITIAL":
        raw = round_half_up_cents(dec(raw) * INITIAL_FILING_MULTIPLIER)
    return min(profile["filing_fee_cap_cents"], max(profile["base_filing_fee_cents"], raw))


def recompute_filing_fee(registration):
    registration["filing_fee_cents"] = filing_fee(registration)
    return registration["filing_fee_cents"]


# ---------------------------------------------------------------------------
# late_penalty_accrual
# ---------------------------------------------------------------------------
def late_penalty_accrual(registration, profile, now):
    """Escalating monthly late fee (PRD 3.9).

    Each month's charge is rounded half up to whole cents individually, before
    any summation, and only the summed total is capped.  The order is observable
    and must not be re-arranged.
    """
    due = parse_iso(registration["effective_due_date"])
    if due is None:
        return 0
    days_late = whole_days_between(due, now)
    if days_late <= 0:
        return 0
    months_late = int(math.ceil(days_late / float(DAYS_PER_ACCRUAL_MONTH)))
    base = dec(profile["late_fee_base_cents"])
    escalation = dec(profile["late_fee_escalation_pct"])
    subtotal = 0
    for index in range(1, months_late + 1):
        subtotal += round_half_up_cents(base * (dec(1) + escalation * dec(index - 1)))
    return min(subtotal, profile["late_fee_cap_cents"])


# ---------------------------------------------------------------------------
# remediation_settlement_total
# ---------------------------------------------------------------------------
def remediation_settlement_total(action, profile):
    """Pinned four-step order (PRD 3.9).

    The discount tier is keyed on the penalty subtotal, never on the final
    total.  Rounding happens once, at the reinstatement-charge step.
    """
    subtotal = 0
    for other in db.enforcement_actions.values():
        if other["registration_id"] != action["registration_id"]:
            continue
        if other["status"] not in ("OPEN", "REMEDIATION_SUBMITTED", "ESCALATED"):
            continue
        subtotal += other["penalty_cents"]

    if subtotal >= DISCOUNT_TIER_3_MIN_CENTS:
        discount = DISCOUNT_TIER_3_PCT
    elif subtotal >= DISCOUNT_TIER_2_MIN_CENTS:
        discount = DISCOUNT_TIER_2_PCT
    else:
        discount = dec(0)

    reinstatement = round_half_up_cents(
        dec(profile["reinstatement_fee_cents"]) * (dec(1) - discount)
    )
    return subtotal + reinstatement


# ---------------------------------------------------------------------------
# coventure_benefit_determination
# ---------------------------------------------------------------------------
def coventure_benefit(promotion, units):
    """max(guaranteed_minimum_cents, per_unit_cents * units).

    The projected variant passes projected_units; the actual settlement variant
    passes actual_units, which is why the guarantee can bind at settlement where
    it never bound at filing.
    """
    return max(promotion["guaranteed_minimum_cents"], promotion["per_unit_cents"] * units)


def recompute_projected_benefit(promotion):
    promotion["projected_benefit_cents"] = coventure_benefit(
        promotion, promotion["projected_units"]
    )
    return promotion["projected_benefit_cents"]


# ---------------------------------------------------------------------------
# registration_trigger_evaluation
# ---------------------------------------------------------------------------
def registration_trigger_evaluation(donor_count, contributions_cents, channels, profile):
    """Score one solicitation-activity row against the state's triggers (PRD 3.1).

    All three comparisons are inclusive at the trigger value, and the reasons are
    emitted in the canonical order regardless of evaluation or channel order.
    """
    if not profile["registration_required"]:
        return False, []
    reasons = []
    if donor_count >= profile["donor_count_trigger"]:
        reasons.append("DONOR_COUNT")
    if contributions_cents >= profile["contribution_trigger_cents"]:
        reasons.append("CONTRIBUTION_TOTAL")
    if profile["online_presence_counts"] and "WEB_TARGETED" in channels:
        reasons.append("TARGETED_ONLINE_PRESENCE")
    return len(reasons) > 0, reasons


# ---------------------------------------------------------------------------
# extension_grant_length
# ---------------------------------------------------------------------------
def extension_grant_length(basis, requested_days, profile):
    """requested_days is ignored entirely under the IRS_990_EXTENSION basis."""
    if basis == "IRS_990_EXTENSION":
        return min(IRS_990_EXTENSION_DAYS, profile["extension_max_days"])
    return min(requested_days, profile["extension_max_days"])


# ---------------------------------------------------------------------------
# contract_filing_deadline
# ---------------------------------------------------------------------------
def contract_filing_due(contract_start, profiles):
    """contract_start plus the SMALLEST filing window among the listed states."""
    candidate_days = [p["fundraiser_contract_filing_days"] for p in profiles]
    return add_days(contract_start, min(candidate_days))


# ---------------------------------------------------------------------------
# financial statement derivations
# ---------------------------------------------------------------------------
def functional_expense_total(program, fundraising, management):
    return program + fundraising + management


def program_ratio(program_expense_cents, functional_total_cents):
    """Rounded half up to four decimals; 0.0 when the functional total is zero."""
    if functional_total_cents == 0:
        return 0.0
    return round_half_up_ratio(dec(program_expense_cents) / dec(functional_total_cents))
