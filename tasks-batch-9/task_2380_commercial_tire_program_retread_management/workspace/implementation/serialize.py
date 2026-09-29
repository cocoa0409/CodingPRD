"""Entity serialization. Every `computed` field is recomputed here, never cached."""

import derive
from util import num_out


def _base(row, versioned=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def _copy(row, out, keys):
    for key in keys:
        out[key] = num_out(row.get(key))
    return out


_LOCATION_FIELDS = (
    "name",
    "location_code",
    "state_code",
    "road_service_response_minutes_committed",
    "scrap_permit_number",
    "scrap_permit_expires_on",
    "is_retread_plant",
)


def service_location(row):
    out = _copy(row, _base(row), _LOCATION_FIELDS)
    out["casings_in_holding_count"] = derive.location_holding_count(row["id"])
    return out


_FLEET_FIELDS = ("name", "account_type", "home_location_id", "billing_mode", "status", "status_reason")


def fleet_account(row):
    out = _copy(row, _base(row), _FLEET_FIELDS)
    out["casing_credit_balance_cents"] = derive.fleet_balance_cents(row["id"])
    return out


_AGREEMENT_FIELDS = (
    "fleet_account_id",
    "agreement_code",
    "effective_from",
    "effective_to",
    "tier_discount_pct",
    "casing_credit_rate_cents",
    "emergency_response_minutes",
    "emergency_labor_rate_cents_per_hour",
    "status",
    "activated_at",
    "terminated_reason",
)


def national_agreement(row):
    return _copy(row, _base(row), _AGREEMENT_FIELDS)


_POLICY_FIELDS = (
    "fleet_account_id",
    "position",
    "target_pressure_psi",
    "pressure_tolerance_pct",
    "min_tread_depth_32nds",
    "pull_point_32nds",
    "max_retread_count",
    "new_tire_tread_depth_32nds",
    "casing_spec_code",
)


def tire_policy(row):
    out = _copy(row, _base(row), _POLICY_FIELDS)
    out["approved_brands"] = list(row["approved_brands"])
    return out


_VEHICLE_FIELDS = (
    "fleet_account_id",
    "unit_number",
    "vehicle_type",
    "current_odometer_miles",
    "last_odometer_reading_at",
    "status",
)


def vehicle(row):
    return _copy(row, _base(row), _VEHICLE_FIELDS)


_CASING_FIELDS = (
    "fleet_account_id",
    "casing_serial",
    "brand",
    "casing_spec_code",
    "intended_position",
    "retread_count",
    "scrap_weight_lbs",
    "status",
    "inspection_grade",
    "inspected_by_user_id",
    "collected_at_location_id",
    "scrap_manifest_id",
    "rejection_reason",
)


def casing(row):
    out = _copy(row, _base(row), _CASING_FIELDS)
    out["provisional_credit_cents"] = derive.casing_provisional_credit_cents(row["id"])
    return out


_ASSET_FIELDS = (
    "fleet_account_id",
    "casing_id",
    "brand",
    "cost_basis_cents",
    "vehicle_id",
    "position",
    "status",
    "mounted_at",
    "odometer_at_mount",
    "tread_depth_at_mount_32nds",
    "replaced_tire_asset_id",
    "pull_reason",
)


def tire_asset(row):
    out = _copy(row, _base(row), _ASSET_FIELDS)
    out["current_tread_depth_32nds"] = derive.asset_current_tread_depth(row)
    out["accumulated_miles"] = derive.asset_accumulated_miles(row)
    return out


_SURVEY_FIELDS = (
    "tire_asset_id",
    "surveyed_at",
    "pressure_psi",
    "tread_depth_32nds",
    "odometer_miles",
    "surveyed_by_user_id",
    "pressure_deviation_pct",
    "finding_code",
    "pull_recommended",
)


def tire_survey(row):
    return _copy(row, _base(row, versioned=False), _SURVEY_FIELDS)


_ENTRY_FIELDS = (
    "fleet_account_id",
    "casing_id",
    "entry_type",
    "amount_cents",
    "source_entity_type",
    "source_entity_id",
    "posted_at",
    "memo",
)


def casing_credit_entry(row):
    return _copy(row, _base(row, versioned=False), _ENTRY_FIELDS)


_LINE_FIELDS = ("service_location_id", "line_code", "cure_cooldown_minutes", "status")


def retread_line(row):
    out = _copy(row, _base(row), _LINE_FIELDS)
    out["booked_minutes"] = derive.line_booked_minutes(row)
    return out


_JOB_FIELDS = (
    "casing_id",
    "retread_line_id",
    "tread_design_code",
    "scheduled_start_at",
    "scheduled_end_at",
    "slot_minutes",
    "status",
    "grade_at_scheduling",
    "retread_count_at_scheduling",
    "warranty_months",
    "warranty_expires_on",
    "produced_tire_asset_id",
    "completed_at",
    "failure_reason",
    "reschedule_count",
)


def retread_job(row):
    return _copy(row, _base(row), _JOB_FIELDS)


_TECH_FIELDS = ("service_location_id", "name", "certification_level", "status")


def technician(row):
    out = _copy(row, _base(row), _TECH_FIELDS)
    out["completed_call_count"] = derive.technician_completed_call_count(row["id"])
    return out


_CALL_FIELDS = (
    "fleet_account_id",
    "vehicle_id",
    "service_location_id",
    "technician_id",
    "priority",
    "complaint",
    "reported_at",
    "dispatched_at",
    "arrived_at",
    "closed_at",
    "dispatch_miles",
    "labor_hours",
    "dispatch_status",
    "billing_status",
    "committed_response_minutes",
    "actual_response_minutes",
    "sla_met",
    "gross_cents",
    "sla_credit_cents",
    "invoice_total_cents",
    "cancel_reason",
    "cross_location_invoice_id",
)


def road_service_call(row):
    return _copy(row, _base(row), _CALL_FIELDS)


_MANIFEST_FIELDS = (
    "service_location_id",
    "hauler_permit_number",
    "hauler_capacity_lbs",
    "manifest_number",
    "status",
    "signed_by_user_id",
    "signed_at",
    "transported_at",
    "hauler_vehicle_id",
    "certified_by_user_id",
    "certified_at",
    "destruction_facility_code",
    "void_reason",
)


def scrap_manifest(row):
    out = _copy(row, _base(row), _MANIFEST_FIELDS)
    count, weight = derive.manifest_totals(row["id"])
    out["tire_count"] = count
    out["total_weight_lbs"] = weight
    return out


_INVOICE_FIELDS = (
    "fleet_account_id",
    "national_agreement_id",
    "billing_period_start",
    "billing_period_end",
    "status",
    "subtotal_cents",
    "discount_cents",
    "net_before_credit_cents",
    "credit_applied_cents",
    "total_cents",
    "paid_amount_cents",
    "dispute_reason",
)


def cross_location_invoice(row):
    out = _copy(row, _base(row), _INVOICE_FIELDS)
    out["line_count"] = derive.invoice_line_count(row["id"])
    return out
