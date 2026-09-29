"""Resource payloads.  Every record carries the four common properties."""
from calc import registry_completeness_score
from derive import effective_charge_cents

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "vendor": (
        "name",
        "vendor_code",
        "standing",
        "open_consignment_liability_cents",
        "recall_open_count",
    ),
    "agreement": (
        "vendor_id",
        "agreement_code",
        "status",
        "billing_trigger",
        "reconciliation_method",
        "invoice_tolerance_bps",
        "price_list_version",
        "period_start_utc",
        "period_end_utc",
        "replenishment_days",
    ),
    "catalog_item": (
        "vendor_id",
        "device_identifier",
        "description",
        "category",
        "list_charge_cents",
        "charge_code",
        "registry_required",
        "shelf_life_days",
        "on_hand_available_qty",
    ),
    "lot": (
        "catalog_item_id",
        "lot_number",
        "expiration_date",
        "status",
        "received_at_utc",
        "received_by_user_id",
        "released_by_user_id",
        "received_qty",
        "on_hand_qty",
        "consumed_qty",
    ),
    "device_unit": (
        "lot_id",
        "consignment_agreement_id",
        "vendor_invoice_id",
        "reserved_case_id",
        "replaced_unit_id",
        "udi_serial",
        "udi_di_snapshot",
        "custody_state",
        "billing_state",
        "ownership",
        "acquisition_cost_cents",
        "contract_price_cents",
        "price_list_version_at_billing",
        "implanted_at_utc",
        "expired_at_utc",
    ),
    "patient": ("mrn", "display_name", "registry_consent", "implant_count"),
    "case": (
        "patient_id",
        "case_number",
        "or_room_code",
        "scheduled_start_utc",
        "scheduled_end_utc",
        "surgeon_code",
        "status",
        "readiness_status",
        "blocked_reservation_count",
        "total_posted_charge_cents",
        "implant_record_count",
    ),
    "implant_record": (
        "surgical_case_id",
        "device_unit_id",
        "patient_id",
        "status",
        "udi_di",
        "udi_pi_serial",
        "anatomic_site",
        "laterality",
        "documented_by_user_id",
        "verified_by_user_id",
        "documented_at_utc",
        "verified_at_utc",
        "amendment_count",
    ),
    "charge": (
        "implant_record_id",
        "charge_code",
        "quantity",
        "status",
        "provisional_charge_cents",
        "final_charge_cents",
        "variance_cents",
        "capture_variant",
    ),
    "registry_submission": (
        "implant_record_id",
        "status",
        "registry_code",
        "submitted_at_utc",
        "adjudicated_at_utc",
        "rejection_reason",
        "resubmission_count",
        "deadline_utc",
    ),
    "field_action": (
        "vendor_id",
        "catalog_item_id",
        "action_code",
        "action_class",
        "scope_type",
        "lot_numbers",
        "serial_low",
        "serial_high",
        "status",
        "effective_from_utc",
        "published_at_utc",
        "implanted_cohort_size",
        "on_hand_cohort_size",
        "notification_open_count",
    ),
    "recall_notification": (
        "field_action_id",
        "implant_record_id",
        "patient_id",
        "status",
        "due_utc",
        "outcome_note",
        "escalation_level",
    ),
    "invoice": (
        "vendor_id",
        "consignment_agreement_id",
        "invoice_number",
        "submitted_total_cents",
        "device_unit_ids",
        "status",
        "expected_total_cents",
        "variance_cents",
        "variance_bps",
        "reconciliation_variant",
        "credit_applied_cents",
        "net_payable_cents",
        "matched_by_user_id",
        "approved_by_user_id",
        "override_reason",
    ),
    "explant_record": (
        "implant_record_id",
        "replacement_device_unit_id",
        "status",
        "reason",
        "explanted_at_utc",
        "return_authorization_no",
        "credit_expected_cents",
        "credit_issued_cents",
    ),
}


def _base(record, kind):
    out = {}
    for key in COMMON:
        out[key] = record.get(key)
    for key in FIELDS[kind]:
        value = record.get(key)
        if isinstance(value, list):
            value = list(value)
        out[key] = value
    return out


def vendor(record):
    return _base(record, "vendor")


def agreement(record):
    return _base(record, "agreement")


def catalog_item(record):
    return _base(record, "catalog_item")


def lot(record):
    return _base(record, "lot")


def device_unit(record):
    return _base(record, "device_unit")


def patient(record):
    return _base(record, "patient")


def case(record):
    return _base(record, "case")


def implant_record(record):
    return _base(record, "implant_record")


def charge(record):
    out = _base(record, "charge")
    out["effective_charge_cents"] = effective_charge_cents(record)
    return out


def registry_submission(record):
    out = _base(record, "registry_submission")
    out["completeness_score"] = registry_completeness_score(record)
    return out


def field_action(record):
    return _base(record, "field_action")


def recall_notification(record):
    return _base(record, "recall_notification")


def invoice(record):
    return _base(record, "invoice")


def explant_record(record):
    return _base(record, "explant_record")
