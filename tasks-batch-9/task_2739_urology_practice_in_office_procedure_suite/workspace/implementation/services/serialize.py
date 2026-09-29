"""Resource serialisers. Only declared fields are exposed; internals stay private."""

import util
from services import calc

INSTANT_FIELDS = set(
    [
        "created_at",
        "updated_at",
        "scheduled_start_at",
        "scheduled_end_at",
        "block_end_at",
        "checked_in_at",
        "completed_at",
        "prophylaxis_window_start_at",
        "administered_at",
        "hld_pass_at",
        "reprocess_due_at",
        "started_at",
        "collected_at",
        "received_at",
        "result_at",
        "escalation_due_at",
    ]
)

DATE_FIELDS = set(
    [
        "ultrasound_accreditation_expires_on",
        "date_of_birth",
        "accreditation_expires_on",
        "lot_expires_on",
        "anchor_date",
        "due_on",
        "therapy_start_by",
        "first_visit_date",
        "visit_date",
    ]
)

COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "providers": [
        "full_name",
        "npi",
        "role_type",
        "credential_status",
        "hld_certified",
        "ultrasound_accreditation_expires_on",
    ],
    "patients": [
        "mrn",
        "full_name",
        "date_of_birth",
        "primary_urologist_id",
        "egfr",
        "anticoagulant_flag",
        "antibiotic_allergy_class",
    ],
    "rooms": [
        "name",
        "room_type",
        "turnover_minutes",
        "room_status",
        "accreditation_body",
        "accreditation_expires_on",
    ],
    "procedure_types": [
        "code",
        "base_minutes",
        "cleanup_class",
        "allowed_room_type",
        "requires_scope",
        "requires_specimen",
        "requires_antibiotic",
        "consignment_required",
        "single_use_device_sku",
        "required_prep_codes",
    ],
    "cases": [
        "patient_id",
        "procedure_type_id",
        "room_id",
        "primary_provider_id",
        "scheduled_start_at",
        "procedure_minutes",
        "turnover_minutes",
        "scheduled_end_at",
        "block_end_at",
        "schedule_status",
        "clearance_status",
        "acknowledged_prep_codes",
        "clearance_block_reason",
        "scope_asset_id",
        "device_lot_id",
        "device_quantity",
        "device_state",
        "checked_in_at",
        "completed_at",
        "cancel_reason_code",
        "indication_note",
    ],
    "antibiotic_orders": [
        "case_id",
        "ordered_by_provider_id",
        "requested_agent",
        "agent",
        "dose_mg",
        "route",
        "prophylaxis_window_start_at",
        "administered_at",
        "status",
    ],
    "scopes": [
        "serial_number",
        "scope_model",
        "channel_count",
        "status",
        "cycles_since_leak_test",
        "leak_test_required",
        "hld_pass_at",
        "reprocess_due_at",
    ],
    "reprocessing_logs": [
        "scope_asset_id",
        "case_id",
        "stage",
        "performed_by_provider_id",
        "attested_by_provider_id",
        "started_at",
        "completed_at",
        "outcome",
        "log_status",
    ],
    "specimens": [
        "case_id",
        "collected_by_provider_id",
        "container_label",
        "specimen_type",
        "site_code",
        "collected_at",
        "accession_number",
        "received_at",
        "condition_on_receipt",
        "chain_status",
        "pathology_result",
        "result_at",
        "notification_status",
        "notification_attempt_count",
        "escalation_due_at",
    ],
    "recalls": [
        "patient_id",
        "protocol",
        "risk_tier",
        "anchor_date",
        "interval_months",
        "due_on",
        "due_basis",
        "status",
        "lapse_days",
        "predecessor_recall_id",
        "source_specimen_id",
        "satisfying_case_id",
        "closed_reason",
    ],
    "referrals": [
        "patient_id",
        "source_case_id",
        "program",
        "requested_visits",
        "visits_authorized",
        "visits_used",
        "visits_remaining",
        "visits_forfeited",
        "status",
        "waitlist_position",
        "therapy_start_by",
        "first_visit_date",
        "decline_reason",
    ],
    "lots": [
        "supplier_name",
        "sku",
        "device_class",
        "quantity_received",
        "quantity_available",
        "quantity_reserved",
        "quantity_consumed",
        "quantity_returned",
        "quantity_wasted",
        "unit_price_cents",
        "lot_expires_on",
        "billed_amount_cents",
        "billing_basis",
        "billing_status",
    ],
}


def _render(key, value):
    if value is None:
        return None
    if key in INSTANT_FIELDS:
        return util.format_instant(value)
    if key in DATE_FIELDS:
        return util.format_date(value)
    return value


def dump(table_name, row):
    out = {}
    for key in COMMON + FIELDS[table_name]:
        out[key] = _render(key, row.get(key))
    if table_name == "patients":
        out["outstanding_recall_count"] = calc.outstanding_recall_count(row["id"])
        out["open_notification_count"] = calc.open_notification_count(row["id"])
    elif table_name == "rooms":
        out["occupied_block_count"] = calc.occupied_block_count(row["id"])
    elif table_name == "cases":
        out["blocking_reason_codes"] = calc.blocking_reason_codes(row)
    return out


def dump_many(table_name, rows):
    return [dump(table_name, row) for row in rows]
