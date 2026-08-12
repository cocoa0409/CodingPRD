"""JSON representation of every entity.

Every field named on an entity in PRD section 3 is response-visible, including
the computed ones.  Instants always travel through core.iso, which is the only
renderer in the codebase.
"""

import calc
from core import NO_COMMON_FIELDS, iso

DATETIME_FIELDS = {
    "created_at", "updated_at", "scheduled_for", "completed_at", "sample_datetime",
    "analyzed_at", "expires_at", "estimated_start_at", "sent_at", "approved_at",
    "intake_at", "dispatched_at", "scheduled_start_at", "scheduled_end_at",
    "actual_start_at", "actual_end_at", "posted_at", "filed_at", "issued_at",
    "submitted_at", "overdue_latched_at", "performed_at", "starts_at",
    "last_service_date", "next_due_at", "last_filter_change_date",
    "filter_next_due_date", "last_salt_delivery_date", "salt_next_due_date",
    "last_inspection_completed_at",
}

FIELDS = {
    "Account": [
        "legal_name", "billing_jurisdiction_code", "membership_tier", "balance_cents",
        "lifetime_invoiced_cents", "lifetime_paid_cents", "credit_hold", "contact_email",
    ],
    "Property": [
        "account_id", "address_line", "jurisdiction_code", "distance_miles",
        "household_size", "has_vulnerable_occupant", "service_zone",
    ],
    "WellProfile": [
        "property_id", "jurisdiction_code", "well_type", "depth_feet",
        "measured_yield_gpm", "pressure_tank_drawdown_gallons", "duty_cycle_ratio",
        "duty_cycle_class", "treatment_media", "hardness_gpg", "potability_status",
        "last_inspection_completed_at", "advisory_reason",
    ],
    "SharedWellAgreement": ["well_profile_id", "account_id", "split_pct", "status"],
    "Technician": ["full_name", "tier", "status", "home_jurisdiction_code"],
    "PartCatalogItem": [
        "part_number", "category", "unit_cost_cents", "rated_gpm",
        "rated_drawdown_gallons", "grain_capacity", "media_kind", "on_hand_qty",
        "status",
    ],
    "Inspection": [
        "well_profile_id", "technician_id", "status", "scheduled_for",
        "measured_yield_gpm", "static_level_feet", "observed_drawdown_gallons",
        "completed_at",
    ],
    "WaterTest": [
        "well_profile_id", "collected_by_technician_id", "parent_test_id",
        "panel_type", "sample_datetime", "analyzed_at", "result_status",
        "coliform_present", "nitrate_mg_l", "arsenic_mg_l", "lead_mg_l", "iron_mg_l",
        "hardness_gpg", "recorded_by_user_id", "confirmed_by_user_id",
        "hold_time_valid",
    ],
    "TreatmentRecommendation": [
        "well_profile_id", "water_test_id", "superseded_by_id", "recommended_media",
        "design_grains", "selected_capacity", "salt_lbs_per_regen", "monthly_salt_lbs",
        "expires_at", "status", "status_effective",
    ],
    "Quote": [
        "property_id", "well_profile_id", "inspection_id", "scope", "status",
        "estimated_labor_minutes", "estimated_start_at", "quoted_technician_tier",
        "parts_subtotal_cents", "labor_subtotal_cents", "permit_fee_cents",
        "tax_cents", "total_cents", "sent_at", "approved_at", "approved_total_cents",
    ],
    "QuoteLine": [
        "quote_id", "part_catalog_item_id", "superseded_by_line_id", "quantity",
        "unit_cost_cents_pinned", "markup_pct_applied", "unit_price_cents",
        "extended_price_cents", "status", "origin",
    ],
    "EmergencyTicket": [
        "property_id", "well_profile_id", "account_id", "assigned_technician_id",
        "dispatch_status", "authorization_status", "intake_at", "dispatched_at",
        "reported_outage_hours", "cause_class", "membership_tier_at_intake",
        "severity_score", "dispatch_surcharge_cents", "membership_credit_cents",
        "net_dispatch_charge_cents", "onsite_estimate_cents", "preauth_cap_cents",
        "response_minutes",
    ],
    "WorkOrder": [
        "property_id", "well_profile_id", "quote_id", "emergency_ticket_id",
        "assigned_technician_id", "origin_callback_claim_id", "pipeline", "scope",
        "fulfillment_status", "billing_status", "scheduled_start_at",
        "scheduled_end_at", "actual_start_at", "actual_end_at", "actual_labor_minutes",
        "billable_minutes", "labor_rate_cents_per_hour", "labor_charge_cents",
        "parts_charge_cents", "callback_eligibility", "callback_attempt_count",
        "hold_reason",
    ],
    "Permit": [
        "well_profile_id", "work_order_id", "quote_id", "jurisdiction_code",
        "jurisdiction_tier", "scope", "expedited", "fee_cents", "status", "filed_at",
        "mandated_alternate_part_id", "superseded_quote_line_id", "condition_text",
        "post_hoc",
    ],
    "PartsConsumptionEntry": [
        "work_order_id", "part_catalog_item_id", "quantity",
        "unit_cost_cents_snapshot", "markup_pct_applied", "unit_price_cents",
        "extended_price_cents", "status", "posted_at",
    ],
    "WarrantyCoverage": [
        "work_order_id", "parts_consumption_entry_id", "superseded_by_id",
        "coverage_class", "starts_at", "expires_at", "status", "coverage_state",
        "claim_count",
    ],
    "CallbackClaim": [
        "warranty_coverage_id", "original_work_order_id", "remedy_work_order_id",
        "complaint_class", "description", "status", "submitted_at",
        "adjudicated_by_user_id", "days_since_coverage_start",
    ],
    "MaintenancePlan": [
        "well_profile_id", "account_id", "status", "compliance_state",
        "overdue_latched_at", "interval_days_as_designed", "interval_days_as_operated",
        "last_service_date", "next_due_at", "filter_media", "last_filter_change_date",
        "filter_next_due_date", "salt_remaining_lbs", "monthly_salt_lbs",
        "last_salt_delivery_date", "salt_next_due_date",
    ],
    "MaintenanceVisit": [
        "maintenance_plan_id", "work_order_id", "visit_kind", "performed_at",
        "salt_added_lbs", "filter_changed",
    ],
    "Invoice": [
        "account_id", "work_order_id", "variant", "status", "parts_subtotal_cents",
        "labor_subtotal_cents", "dispatch_subtotal_cents", "warranty_credit_cents",
        "loyalty_discount_cents", "taxable_subtotal_cents", "tax_cents", "total_cents",
        "amount_paid_cents", "issued_at", "shared_split_pct",
    ],
    "InvoiceLine": [
        "invoice_id", "parts_consumption_entry_id", "line_type", "description",
        "amount_cents", "sequence_no",
    ],
}


def _derived(row, kind):
    """Computed fields that are re-derived at read time."""
    if kind == "Property":
        return {"service_zone": calc.service_zone(row["distance_miles"])}
    if kind == "TreatmentRecommendation":
        return {"status_effective": calc.recommendation_status_effective(row)}
    if kind == "WarrantyCoverage":
        return {"coverage_state": calc.coverage_state(row)}
    if kind == "MaintenancePlan":
        return {
            "filter_next_due_date": calc.filter_next_due_date(row),
            "salt_next_due_date": calc.salt_next_due_date(row),
        }
    return {}


def dump(row):
    if row is None:
        return None
    kind = row["_kind"]
    derived = _derived(row, kind)
    out = {"id": row["id"]}
    for name in FIELDS[kind]:
        value = derived[name] if name in derived else row.get(name)
        out[name] = iso(value) if name in DATETIME_FIELDS and value is not None else value
    out["created_at"] = iso(row["created_at"])
    if kind not in NO_COMMON_FIELDS:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def dump_all(rows):
    return [dump(r) for r in rows]
