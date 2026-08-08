"""Entity serializers (PRD §2.4 common fields plus each entity's own fields)."""

FIELDS = {
    "worker": ["full_name", "employee_code", "credential_level", "employment_status"],
    "patient": [
        "mrn", "full_name", "household_size", "monthly_income_cents", "residence_zip",
        "program_enrollments", "categorical_exclusions", "child_in_household",
        "address_safety_flag", "enrollment_status", "gate_status", "gate_reason",
        "risk_score", "risk_tier", "risk_tier_effective_at", "unfulfilled_referral_count",
    ],
    "instrument": [
        "name", "version_label", "domain_weights", "rescreen_cadence_days",
        "effective_from", "status",
    ],
    "screening": [
        "patient_id", "instrument_id", "domain_scores", "anchor_screened_at",
        "latest_response_at", "weighted_score", "risk_tier", "amendment_count", "status",
    ],
    "org": ["name", "org_type", "service_zips", "contact_email", "status"],
    "offering": [
        "resource_org_id", "unit_type", "capacity_total", "available_units",
        "allocated_units", "delivered_units", "released_units", "expired_units",
        "lifetime_allocated_units", "availability_state", "exhausted_since",
    ],
    "criterion": [
        "offering_id", "criterion_type", "evaluation_rank", "max_monthly_income_cents",
        "allowed_zips", "min_household_size", "max_household_size",
        "required_program_code", "excluded_flag_code",
    ],
    "referral": [
        "patient_id", "offering_id", "opened_by_chw_id", "parent_referral_id",
        "root_referral_id", "urgency", "units_requested", "status", "sent_at",
        "ack_deadline_at", "hold_expires_at", "reroute_count", "decline_reason",
        "lapse_reason", "delivered_at", "closed_at", "outcome_note",
    ],
    "visit": [
        "patient_id", "assigned_chw_id", "second_chw_id", "scheduled_start",
        "scheduled_end", "two_person_required", "scheduling_status",
        "documentation_status", "completed_at", "attested_at", "amendment_count",
        "visit_note",
    ],
    "goal": [
        "patient_id", "domain", "direction", "baseline_value", "target_value",
        "current_value", "progress_pct", "status", "review_cycle_days",
        "review_due_at", "reopen_count", "closed_at",
    ],
    "encounter": [
        "patient_id", "chw_id", "home_visit_id", "funding_claim_id", "encounter_date",
        "service_month", "direct_minutes", "indirect_minutes", "travel_minutes",
        "documentation_minutes", "travel_miles", "total_minutes",
        "raw_billable_minutes", "billable_minutes", "travel_reimbursement_cents",
        "funding_source", "status", "submitted_at",
    ],
    "claim": [
        "patient_id", "service_month", "basis", "claimed_minutes",
        "claimed_encounter_count", "billing_code", "units", "allowed_amount_cents",
        "status", "denial_reason", "denied_at", "appealed_at",
    ],
    "award": [
        "funder_name", "period_start", "period_end", "budget_cap_cents",
        "indirect_rate_pct", "allowable_cost_categories", "committed_cents",
        "remaining_budget_cents", "status",
    ],
    "chargeline": [
        "grant_award_id", "encounter_id", "charged_minutes", "hourly_rate_cents",
        "direct_amount_cents", "indirect_amount_cents", "total_amount_cents",
        "reversed_at", "reversal_reason", "status",
    ],
    "escalation": [
        "patient_id", "source_flag", "source_referral_id", "source_screening_id",
        "blocking_offering_id", "status", "current_tier", "opened_by_user_id",
        "acknowledged_by_user_id", "tier_entered_at", "ack_deadline_at",
        "promotion_count", "resolution_reason", "note",
    ],
}


def dump(row):
    kind = row.get("_kind")
    out = {"id": row["id"]}
    for field in FIELDS.get(kind, []):
        out[field] = row.get(field)
    out["created_at"] = row.get("created_at")
    out["updated_at"] = row.get("updated_at")
    out["version"] = row.get("version")
    return out


def dump_all(rows):
    return [dump(row) for row in rows]
