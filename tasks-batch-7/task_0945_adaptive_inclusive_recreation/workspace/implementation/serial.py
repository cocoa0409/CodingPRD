"""Response projection (PRD 2.6): every field the document attributes to an
entity -- inputs, system-managed fields and computed figures alike -- plus id,
created_at and (except for FeeScaleBand and GoalRating) updated_at and version.
"""

import calc

FIELDS = {
    "operating_periods": ("name", "starts_on", "ends_on", "status"),
    "fee_scale_bands": (
        "household_size_min",
        "household_size_max",
        "income_band",
        "per_session_cents",
        "series_cents",
    ),
    "participants": (
        "legal_name",
        "date_of_birth",
        "household_id",
        "household_size",
        "income_band",
        "weight_kg",
        "mobility_profile",
        "guardianship_status",
        "status",
    ),
    "caregivers": (
        "participant_id",
        "full_name",
        "relationship",
        "is_legal_guardian",
        "contact_phone",
    ),
    "support_assessments": (
        "participant_id",
        "assessed_on",
        "effective_from",
        "support_tier",
        "support_points",
        "status",
    ),
    "consents": (
        "participant_id",
        "consent_type",
        "signed_by_caregiver_id",
        "signer_role",
        "signed_on",
        "expires_on",
        "status",
    ),
    "activity_programs": (
        "name",
        "activity_type",
        "risk_tier",
        "pricing_mode",
        "rounding_policy",
        "waitlist_policy",
        "fee_multiplier_bp",
        "scheduled_session_count",
        "required_consent_types",
        "required_certification_types",
        "requires_medication_admin",
        "required_equipment_model_code",
        "required_equipment_size_code",
        "session_count_created",
    ),
    "program_sessions": (
        "program_id",
        "sequence_number",
        "start_at",
        "end_at",
        "slot_capacity",
        "slots_committed",
        "slots_available",
        "one_to_one_pool_size",
        "one_to_one_committed",
        "one_to_one_available",
        "one_to_one_staffed",
        "assigned_group_staff_count",
        "required_group_staff_planned",
        "required_group_staff_delivered",
        "staffing_gap",
        "unlock_count",
        "status",
    ),
    "enrollments": (
        "participant_id",
        "session_id",
        "transport_requested",
        "enrollment_status",
        "funding_status",
        "waitlist_score",
        "promoted_at",
        "effective_support_tier_at_session",
    ),
    "enrollment_charges": (
        "enrollment_id",
        "fee_scale_band_id",
        "program_fee_cents",
        "scholarship_applied_cents",
        "copay_cents",
        "transport_fee_cents",
        "sibling_discount_bp",
        "family_responsibility_cents",
        "amount_paid_cents",
        "balance_cents",
        "status",
    ),
    "staff_members": ("full_name", "role_title"),
    "staff_certifications": (
        "staff_member_id",
        "certification_type",
        "issued_on",
        "expires_on",
        "status",
    ),
    "staff_assignments": (
        "session_id",
        "staff_member_id",
        "dedicated_participant_id",
        "assignment_role",
        "qualified_at_assignment",
        "qualified_at_session_date",
        "status",
    ),
    "equipment_items": (
        "item_kind",
        "model_code",
        "size_code",
        "weight_capacity_kg",
        "serial_number",
        "inspection_due_date",
        "condition_status",
        "pooled_total",
        "pooled_available",
        "pooled_held",
        "pooled_checked_out",
    ),
    "equipment_reservations": (
        "enrollment_id",
        "equipment_item_id",
        "return_condition",
        "status",
    ),
    "transport_runs": (
        "session_id",
        "pickup_start_at",
        "pickup_end_at",
        "fare_mode",
        "flat_fare_cents",
        "route_miles_x10",
        "accessible_positions",
        "accessible_committed",
        "accessible_available",
        "ambulatory_seats",
        "ambulatory_committed",
        "ambulatory_available",
        "status",
    ),
    "transport_bookings": (
        "transport_run_id",
        "enrollment_id",
        "position_type",
        "fare_cents",
        "status",
    ),
    "funding_sources": (
        "operating_period_id",
        "name",
        "source_kind",
        "priority_rank",
        "award_mode",
        "award_pct_bp",
        "flat_award_cents",
        "total_budget_cents",
        "available_cents",
        "encumbered_cents",
        "disbursed_cents",
        "status",
    ),
    "scholarship_awards": (
        "enrollment_id",
        "funding_source_id",
        "awarded_by_user_id",
        "disbursed_by_user_id",
        "amount_cents",
        "encumbered_cents",
        "disbursed_cents",
        "status",
    ),
    "goals": (
        "participant_id",
        "title",
        "measure",
        "baseline_value",
        "target_value",
        "mastery_mode",
        "mastery_criterion_score",
        "mastery_window_m",
        "mastery_hits_n",
        "review_due_on",
        "rating_count",
        "status",
    ),
    "goal_ratings": (
        "goal_id",
        "session_id",
        "rated_by_staff_id",
        "score",
        "rated_session_start_at",
        "note",
    ),
}

NO_COMMON_FIELDS = ("fee_scale_bands", "goal_ratings")


def dump(row):
    if row is None:
        return None
    table = row["_table"]
    out = {"id": row["id"], "created_at": row["created_at"]}
    for field in FIELDS[table]:
        out[field] = row.get(field)
    if table not in NO_COMMON_FIELDS:
        out["updated_at"] = row.get("updated_at")
        out["version"] = row.get("version")
    if table == "participants":
        out["age_years"] = calc.age_years(row)
        out["effective_support_tier"] = row.get("effective_support_tier")
        out["enrollment_posture"] = calc.participant_enrollment_posture(row, None)[
            "enrollment_posture"
        ]
    return out


def dump_all(rows):
    return [dump(row) for row in rows]
