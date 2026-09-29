"""Row -> JSON serializers.

`created_at` / `updated_at` always carry three fractional digits (PRD 2.4);
domain datetimes echo back in the same shape they were supplied, so a value
given as `2026-09-01T00:00:00Z` reads back identically.
"""
from decimal import Decimal

import util

# field name -> ("dt" clock datetime | "num" 2dp number)
_SPECIAL = {
    "target_opening_date": "dt",
    "supervision_started_at": "dt",
    "management_composite_score": "num",
    "filed_at": "dt",
    "decision_at": "dt",
    "deadline_utc": "dt",
    "adopted_at": "dt",
    "window_start_utc": "dt",
    "window_end_utc": "dt",
    "buffer_end_utc": "dt",
    "duration_hours": "num",
}


def _value(name, raw):
    kind = _SPECIAL.get(name)
    if kind == "dt":
        return util.iso_clock(raw)
    if kind == "num":
        if raw is None:
            return None
        return float(raw if isinstance(raw, Decimal) else Decimal(str(raw)))
    return raw


def _row(row, fields):
    out = {"id": row["id"]}
    for name in fields:
        out[name] = _value(name, row.get(name))
    out["created_at"] = util.iso_ms(row["created_at"])
    out["updated_at"] = util.iso_ms(row["updated_at"])
    out["version"] = row["version"]
    return out


GROUP_FIELDS = (
    "proposed_bank_name",
    "home_state_code",
    "charter_type",
    "target_opening_date",
    "stage",
    "composition_status",
    "organizer_count",
    "independent_organizer_count",
    "max_affiliation_count",
    "management_composite_score",
    "opening_blocked_reason",
    "supervision_started_at",
    "supervision_year_index",
)

ORGANIZER_FIELDS = (
    "group_id",
    "full_name",
    "role_on_board",
    "is_independent",
    "affiliation_code",
    "banking_years",
    "regulatory_experience_score",
    "fingerprint_state",
    "credit_state",
    "adverse_finding_type",
    "qualification_subscore",
    "waiver_granted",
    "waiver_rationale",
    "qualification_status",
)

PLAN_FIELDS = (
    "group_id",
    "supersedes_plan_id",
    "plan_revision_index",
    "status",
    "opening_tier1_capital_cents",
    "projected_assets_y1_cents",
    "projected_assets_y2_cents",
    "projected_assets_y3_cents",
    "projected_loans_y1_cents",
    "projected_loans_y2_cents",
    "projected_loans_y3_cents",
    "projected_deposits_y1_cents",
    "projected_deposits_y2_cents",
    "projected_deposits_y3_cents",
    "projected_net_income_y1_cents",
    "projected_net_income_y2_cents",
    "projected_net_income_y3_cents",
    "projected_branch_count",
    "stress_scenario_count",
    "breach_scenario_count",
    "worst_governing_min_leverage_ratio_bps",
)

SCENARIO_FIELDS = (
    "business_plan_id",
    "scenario_code",
    "credit_loss_rate_bps",
    "nim_compression_bps",
    "expense_overrun_cents",
    "static_min_leverage_ratio_bps",
    "static_breach_year_index",
    "dynamic_min_leverage_ratio_bps",
    "dynamic_breach_year_index",
    "governing_variant",
    "governing_min_leverage_ratio_bps",
    "governing_breach_year_index",
)

RAISE_FIELDS = (
    "group_id",
    "status",
    "target_gross_cents",
    "minimum_gross_cents",
    "offering_price_cents_per_share",
    "max_shares",
    "organizational_expense_claim_cents",
    "subscribed_shares",
    "pledged_gross_cents",
    "funded_gross_cents",
    "cleared_escrow_cents",
    "projected_reimbursement_cents",
    "projected_net_release_cents",
    "released_net_cents",
    "refunded_gross_cents",
)

SUBSCRIPTION_FIELDS = (
    "capital_raise_id",
    "organizer_id",
    "subscriber_name",
    "shares",
    "amount_cents",
    "funding_state",
    "clearance_state",
    "counts_toward_escrow",
)

FILING_FIELDS = (
    "group_id",
    "authority",
    "pinned_business_plan_id",
    "status",
    "info_request_round",
    "filed_at",
    "decision_at",
    "condition_total_count",
    "open_blocking_condition_count",
    "settled_condition_count",
    "pre_opening_clearance",
)

CONDITION_FIELDS = (
    "filing_id",
    "condition_code",
    "category",
    "is_pre_opening_blocking",
    "deadline_utc",
    "status",
    "evidence_reference",
    "adjudication_count",
)

POLICY_FIELDS = (
    "group_id",
    "domain",
    "drafted_by_organizer_id",
    "adopted_by_organizer_id",
    "document_title",
    "status",
    "adopted_at",
    "finding_note",
)

CONTRACT_FIELDS = (
    "group_id",
    "service_domain",
    "vendor_name",
    "annual_cost_cents",
    "contract_term_months",
    "due_diligence_score",
    "criticality",
    "status",
    "active_window_count",
)

WINDOW_FIELDS = (
    "vendor_contract_id",
    "window_start_utc",
    "window_end_utc",
    "status",
    "duration_hours",
)

EXAM_FIELDS = (
    "group_id",
    "window_start_utc",
    "window_end_utc",
    "exam_scope",
    "status",
    "buffer_end_utc",
    "finding_count",
)

DEVIATION_FIELDS = (
    "group_id",
    "baseline_plan_id",
    "metric",
    "actual_value",
    "narrative",
    "supervision_year_index_at_request",
    "baseline_value",
    "deviation_bps",
    "requires_regulator_approval",
    "status",
    "decision_note",
)


def group(row):
    return _row(row, GROUP_FIELDS)


def organizer(row):
    return _row(row, ORGANIZER_FIELDS)


def plan(row):
    return _row(row, PLAN_FIELDS)


def scenario(row):
    return _row(row, SCENARIO_FIELDS)


def capital_raise(row):
    return _row(row, RAISE_FIELDS)


def subscription(row):
    return _row(row, SUBSCRIPTION_FIELDS)


def filing(row):
    return _row(row, FILING_FIELDS)


def condition(row):
    return _row(row, CONDITION_FIELDS)


def policy(row):
    return _row(row, POLICY_FIELDS)


def contract(row):
    return _row(row, CONTRACT_FIELDS)


def window(row):
    return _row(row, WINDOW_FIELDS)


def exam(row):
    return _row(row, EXAM_FIELDS)


def deviation(row):
    return _row(row, DEVIATION_FIELDS)
