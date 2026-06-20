"""Serializers — produce the public JSON representation of each entity.

We return copies so callers cannot mutate the store, and so the field set is
exactly the documented schema.
"""

COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(obj, fields):
    return {f: obj.get(f) for f in fields}


def facility(o):
    return _pick(o, COMMON + [
        "name", "state_code", "license_number", "care_point_rate_cents",
        "license_status", "bed_count", "occupied_bed_count",
        "occupancy_rate_bps", "open_deficiency_count",
    ])


def unit(o):
    return _pick(o, COMMON + [
        "facility_id", "unit_number", "wing", "monthly_base_rent_cents",
        "current_resident_id", "status",
    ])


def resident(o):
    return _pick(o, COMMON + [
        "facility_id", "full_name", "date_of_birth", "stay_type",
        "respite_end_date", "current_care_level", "current_care_points",
        "assigned_unit_id", "open_balance_cents", "status",
        "discharge_disposition",
    ])


def assessment(o):
    return _pick(o, COMMON + [
        "resident_id", "adl_bathing", "adl_dressing", "adl_toileting",
        "adl_transferring", "adl_eating", "cognition_score", "behavior_flags",
        "care_points_total", "care_level", "status",
    ])


def care_plan(o):
    return _pick(o, COMMON + [
        "resident_id", "source_assessment_id", "supersedes_care_plan_id",
        "adl_support_items", "status",
    ])


def medication_order(o):
    return _pick(o, COMMON + [
        "resident_id", "drug_name", "dose", "schedule_times",
        "is_controlled", "status",
    ])


def administration(o):
    # Append-only immutable event: only id + created_at as common fields.
    return _pick(o, ["id", "created_at"] + [
        "medication_order_id", "resident_id", "scheduled_time", "outcome",
        "witness_user_id", "administered_by_user_id",
    ])


def move_in_agreement(o):
    return _pick(o, COMMON + [
        "resident_id", "unit_id", "move_in_date", "monthly_base_rent_cents",
        "community_fee_cents", "status",
    ])


def billing_statement(o):
    return _pick(o, COMMON + [
        "resident_id", "period_year", "period_month", "is_first_statement",
        "rent_charge_cents", "care_points_charge_cents",
        "community_fee_charge_cents", "total_charge_cents", "paid_cents",
        "status",
    ])


def incident_report(o):
    return _pick(o, COMMON + [
        "resident_id", "incident_type", "occurred_at", "severity",
        "requires_state_report", "linked_deficiency_id", "status",
    ])


def survey_deficiency(o):
    return _pick(o, COMMON + [
        "facility_id", "tag_code", "scope_severity", "cited_at",
        "poc_due_date", "poc_text", "status",
    ])
