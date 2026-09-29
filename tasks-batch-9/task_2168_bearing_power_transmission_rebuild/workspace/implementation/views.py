"""Public field projections and ownership resolution."""

import store
from errors import fail

CUSTOMER_FIELDS = [
    "id", "name", "account_code", "contact_email",
    "core_credit_balance_cents", "warranty_credit_balance_cents",
    "manual_credit_balance_cents", "total_credit_balance_cents",
    "created_at", "updated_at", "version",
]

ASSET_FIELDS = [
    "id", "customer_id", "asset_tag", "criticality", "duty_class", "site_code",
    "created_at", "updated_at", "version",
]

STANDARD_FIELDS = [
    "id", "model_code", "base_core_value_cents", "max_rebuild_count",
    "warranty_hours", "warranty_months", "cleanroom_required",
    "required_feature_codes", "feature_bands",
    "created_at", "updated_at", "version",
]

BENCH_FIELDS = [
    "id", "bench_code", "parallel_slots", "cleanroom", "committed_minutes",
    "created_at", "updated_at", "version",
]

CORE_FIELDS = [
    "id", "customer_id", "clearance_standard_id", "serial_no", "model_code",
    "rebuild_count", "declared_condition_grade", "condition_grade", "status",
    "provisional_core_credit_cents", "final_core_credit_cents",
    "replacement_core_unit_id",
    "created_at", "updated_at", "version",
]

ORDER_FIELDS = [
    "id", "customer_id", "core_unit_id", "customer_asset_id", "labor_hours",
    "work_status", "approval_status", "expedited", "expedite_reason",
    "emergency_ref", "part_revision_counter", "quoted_part_revision",
    "parts_subtotal_cents", "labor_cents", "pre_credit_subtotal_cents",
    "expedite_surcharge_cents", "gross_total_cents", "core_credit_applied_cents",
    "quote_total_cents", "covered_base_cents", "cancel_reason",
    "created_at", "updated_at", "version",
]

INSPECTION_FIELDS = [
    "id", "rebuild_order_id", "linked_vibration_reading_id", "status",
    "inspector_note", "cause_code_override", "submitted_by_user_id",
    "accepted_by_user_id", "revision_count", "life_score_variant",
    "remaining_life_score", "remaining_life_grade", "failure_cause_code",
    "cause_confidence", "return_reason",
    "created_at", "updated_at", "version",
]

MEASUREMENT_FIELDS = [
    "id", "inspection_id", "feature_code", "measured_um", "sequence_no",
    "band_result", "deviation_ratio", "feature_score", "created_at",
]

PART_LINE_FIELDS = [
    "id", "rebuild_order_id", "part_no", "source_class", "qty",
    "unit_cost_cents", "engineering_waiver_ref", "approval_status",
    "revision_count", "decision_note", "line_total_cents",
    "created_at", "updated_at", "version",
]

READING_FIELDS = [
    "id", "customer_asset_id", "reading_at", "overall_velocity_mm_s",
    "bpfo_amplitude_g", "bpfi_amplitude_g", "baseline_amplitude_g",
    "iso_zone", "defect_ratio_outer", "defect_ratio_inner", "created_at",
]

RESERVATION_FIELDS = [
    "id", "rebuild_order_id", "bench_id", "window_start_at", "window_end_at",
    "queue_if_full", "status", "window_minutes", "promoted_at",
    "created_at", "updated_at", "version",
]

INSTALLATION_FIELDS = [
    "id", "core_unit_id", "customer_asset_id", "rebuild_order_id",
    "in_service_start_at", "run_hours", "status", "removed_at", "failed_at",
    "warranty_hours_snapshot", "warranty_months_snapshot",
    "covered_base_cents_snapshot",
    "created_at", "updated_at", "version",
]

CLAIM_FIELDS = [
    "id", "installation_id", "claimed_reason", "status", "submitted_at",
    "elapsed_days", "hours_consumed_fraction", "calendar_consumed_fraction",
    "governing_basis", "remaining_fraction", "pro_rata_credit_cents",
    "adjudication_note", "adjudicated_by_user_id", "info_note",
    "created_at", "updated_at", "version",
]

NOTE_FIELDS = [
    "id", "customer_id", "kind", "amount_cents", "status", "core_unit_id",
    "warranty_claim_id", "memo", "voided_at", "void_reason",
    "created_at", "updated_at", "version",
]

FIELDS = {
    "customers": CUSTOMER_FIELDS,
    "assets": ASSET_FIELDS,
    "standards": STANDARD_FIELDS,
    "benches": BENCH_FIELDS,
    "core_units": CORE_FIELDS,
    "orders": ORDER_FIELDS,
    "inspections": INSPECTION_FIELDS,
    "measurements": MEASUREMENT_FIELDS,
    "part_lines": PART_LINE_FIELDS,
    "readings": READING_FIELDS,
    "reservations": RESERVATION_FIELDS,
    "installations": INSTALLATION_FIELDS,
    "claims": CLAIM_FIELDS,
    "credit_notes": NOTE_FIELDS,
}


def render(table, rec):
    return store.public(rec, FIELDS[table])


def render_many(table, rows):
    return [store.public(r, FIELDS[table]) for r in rows]


# ---------------------------------------------------------------------------
# ownership
# ---------------------------------------------------------------------------
def owner_of(table, rec):
    """Return the owning customer_id of a record, or None when it has no owner."""
    if rec is None:
        return None
    if table == "customers":
        return rec["id"]
    if table in ("assets", "core_units", "orders", "credit_notes"):
        return rec.get("customer_id")
    if table in ("standards", "benches"):
        return None
    if table == "inspections":
        return owner_of("orders", store.get("orders", rec["rebuild_order_id"]))
    if table == "measurements":
        return owner_of("inspections", store.get("inspections", rec["inspection_id"]))
    if table == "part_lines":
        return owner_of("orders", store.get("orders", rec["rebuild_order_id"]))
    if table == "readings":
        return owner_of("assets", store.get("assets", rec["customer_asset_id"]))
    if table == "reservations":
        return owner_of("orders", store.get("orders", rec["rebuild_order_id"]))
    if table == "installations":
        return owner_of("orders", store.get("orders", rec["rebuild_order_id"]))
    if table == "claims":
        return owner_of("installations", store.get("installations", rec["installation_id"]))
    return None


def require_owner(role, user_id, table, rec):
    """Ladder step 7 — Customer scoping."""
    if role != "Customer":
        return
    owner = owner_of(table, rec)
    if owner is not None and owner != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Resource does not belong to the calling account")


def scope_rows(role, user_id, table, rows):
    """Confine a Customer's list read to its own resources."""
    if role != "Customer":
        return rows
    return [r for r in rows if owner_of(table, r) == user_id]
