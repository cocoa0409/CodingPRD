"""Row -> JSON projection. Money is emitted as a JSON number at 2 dp,
percentages at 4 dp, timestamps as ISO 8601 UTC with three fractional digits.
"""

from core import iso, num

M = "money"
P = "pct"
D = "datetime"
S = "scalar"
SCHED = "schedule"

SPECS = {
    "investors": [
        ("legal_name", S), ("taxpayer_type", S), ("tax_year_end_month", S),
        ("compliance_attestation_status", S), ("eligible_gain_total", M),
        ("deferred_gain_outstanding", M), ("included_gain_total", M),
    ],
    "funds": [
        ("name", S), ("entity_type", S), ("manager_user_id", S),
        ("asset_test_valuation_method", S), ("certification_status", S),
        ("compliance_posture", S), ("first_taxable_month_iso8601", D),
        ("self_certification_date", D), ("aggregate_asset_basis", M),
        ("aggregate_qualified_basis", M), ("aggregate_afs_value", M),
        ("aggregate_qualified_afs_value", M), ("deferred_gain_committed", M),
        ("cumulative_penalty_months", S), ("consecutive_failed_tests", S),
        ("last_test_measurement_date", D),
    ],
    "eligible_gains": [
        ("investor_id", S), ("gain_character", S), ("eligible_amount", M),
        ("realization_date", D), ("deadline_basis", S),
        ("pass_through_year_end", D), ("window_basis_date", D),
        ("investment_deadline", D), ("elected_amount", M),
        ("unelected_amount", M), ("status", S), ("expired_at", D),
    ],
    "deferral_elections": [
        ("eligible_gain_id", S), ("fund_id", S), ("investor_id", S),
        ("elected_amount", M), ("investment_date", D), ("days_from_basis", S),
        ("initial_basis", M), ("current_basis", M), ("step_up_applied_pct", P),
        ("holding_tier", S), ("included_amount", M),
        ("included_fraction_total", P), ("deferred_remaining", M),
        ("status", S), ("revoked_reason_code", S),
    ],
    "fund_assets": [
        ("fund_id", S), ("qoz_business_id", S), ("asset_class", S),
        ("acquisition_date", D), ("acquired_from_related_party", S),
        ("original_use_in_zone", S), ("unadjusted_cost_basis", M),
        ("afs_fair_value", M), ("adjusted_basis", M), ("qualification", S),
        ("status", S), ("disposed_at", D), ("disposition_sequence_index", S),
        ("proceeds_amount", M),
    ],
    "qoz_businesses": [
        ("fund_id", S), ("legal_name", S), ("zone_tract_code", S),
        ("declared_nqfp_amount", M), ("total_asset_value", M),
        ("total_tangible_property_basis", M), ("wcsh_protected_amount", M),
        ("blown_unspent_amount", M), ("nqfp_amount", M),
        ("qualification_status", S), ("consecutive_failed_business_tests", S),
    ],
    "business_tests": [
        ("qoz_business_id", S), ("testing_date", D), ("safe_harbor_used", S),
        ("hours_zone_pct", P), ("amounts_paid_zone_pct", P),
        ("gross_income_zone_amount", M), ("gross_income_total_amount", M),
        ("intangibles_zone_use_amount", M), ("intangibles_total_amount", M),
        ("total_asset_value_measured", M), ("nqfp_amount_measured", M),
        ("gross_income_pct", P), ("intangibles_pct", P), ("nqfp_pct", P),
        ("gross_income_prong", S), ("intangibles_prong", S),
        ("nqfp_prong", S), ("status", S), ("measured_by_user_id", S),
        ("certified_by_user_id", S),
    ],
    "asset_tests": [
        ("fund_id", S), ("measurement_date", D), ("period_start", D),
        ("period_end", D), ("valuation_method", S),
        ("qualified_numerator", M), ("total_denominator", M),
        ("ratio_pct", P), ("included_asset_count", S), ("result", S),
        ("shortfall_amount", M), ("failed_month_count", S), ("status", S),
        ("measured_by_user_id", S), ("certified_by_user_id", S),
    ],
    "improvement_projects": [
        ("fund_asset_id", S), ("window_start", D), ("window_end", D),
        ("aggregation_method", S), ("group_key", S),
        ("basis_at_acquisition", M), ("qualified_additions_total", M),
        ("improvement_ratio_pct", P), ("status", S), ("evaluated_at", D),
    ],
    "wcsh_plans": [
        ("qoz_business_id", S), ("window_start", D), ("window_end", D),
        ("covered_amount", M), ("written_plan_reference", S),
        ("schedule_month_count", S), ("spend_schedule", SCHED),
        ("documentation_complete", S), ("spent_total", M),
        ("unspent_amount", M), ("last_checkpoint_month_index", S),
        ("pacing_shortfall", M), ("overspill_amount", M), ("status", S),
    ],
    "capital_expenditures": [
        ("improvement_project_id", S), ("wcsh_plan_id", S), ("amount", M),
        ("expenditure_kind", S), ("spend_date", D),
        ("counts_toward_basis", S), ("schedule_month_index", S),
    ],
    "penalty_assessments": [
        ("fund_id", S), ("asset_test_id", S), ("failed_month_count", S),
        ("shortfall_amount", M), ("monthly_penalty_amount", M),
        ("gross_penalty_amount", M), ("cure_credit_amount", M),
        ("net_penalty_amount", M), ("cure_attempt_count", S),
        ("cure_basis", S), ("narrative_reference", S), ("status", S),
        ("requested_by_user_id", S), ("decided_by_user_id", S),
    ],
    "inclusion_events": [
        ("deferral_election_id", S), ("event_type", S), ("event_date", D),
        ("included_fraction", P), ("holding_days", S),
        ("holding_tier_applied", S), ("gross_inclusion_amount", M),
        ("basis_offset_amount", M), ("net_inclusion_amount", M),
        ("is_full", S),
    ],
    "step_up_elections": [
        ("deferral_election_id", S), ("election_date", D), ("claimed_fmv", M),
        ("disposition_sequence", S), ("holding_period_days", S),
        ("stepped_up_basis", M), ("status", S), ("denial_reason", S),
    ],
}

# CapitalExpenditure is the one entity without updated_at / version (PRD 2.5).
NO_COMMON = ("capital_expenditures",)


def _value(kind, raw):
    if raw is None:
        return None
    if kind in (M, P):
        return num(raw)
    if kind == D:
        return iso(raw)
    if kind == SCHED:
        return [{"month_index": b["month_index"],
                 "planned_amount": num(b["planned_amount"])} for b in raw]
    return raw


def dump(row):
    kind = row["_kind"]
    out = {"id": row["id"]}
    for name, field_kind in SPECS[kind]:
        out[name] = _value(field_kind, row.get(name))
    out["created_at"] = iso(row["created_at"])
    if kind not in NO_COMMON:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def dump_all(items):
    return [dump(r) for r in items]
