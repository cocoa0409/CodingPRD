"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CUSTOMER_STATUSES = {"ACTIVE", "ELEVATED_DEPOSIT", "BLOCKED"}
CAPACITY_DAY_STATUSES = {"OPEN", "FULL"}
APPOINTMENT_STATUSES = {
    "PENDING_DEPOSIT", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW", "EXPIRED",
}
ANIMAL_STATUSES = {
    "EXPECTED", "RECEIVED", "SLAUGHTERED", "HANGING",
    "CUTTING", "READY", "COMPLETE", "VOIDED",
}
SHARE_STATUSES = {"PENDING", "CONFIRMED", "READY", "PICKED_UP", "FORFEITED"}
CUT_SHEET_STATUSES = {"DRAFT", "SUBMITTED", "LOCKED"}
INVOICE_STATUSES = {"OPEN", "PARTIALLY_PAID", "PAID", "COLLECTIONS"}
STORAGE_STATUSES = {"STORED", "PICKED_UP", "ABANDONED"}
LABEL_STATUSES = {"PENDING", "APPROVED"}
SPECIES = {"BEEF", "HOG", "LAMB", "GOAT"}
INTENDED_USES = {"OWNER_USE", "RESALE"}


def _assert_common(data: dict, what: str):
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{what}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{what}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), f"{what}.version must be int"


def _assert_optional_ts(data: dict, field: str, what: str):
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), f"{what}.{field} must be ISO 8601 UTC"


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["status"] in CUSTOMER_STATUSES


def assert_capacity_day(data: dict):
    _assert_common(data, "CapacityDay")
    assert isinstance(data["date"], str) and data["date"]
    assert isinstance(data["capacity_head"], int) and data["capacity_head"] >= 1
    assert isinstance(data["booked_head"], int) and data["booked_head"] >= 0
    assert data["status"] in CAPACITY_DAY_STATUSES
    assert data["booked_head"] <= data["capacity_head"], (
        "booked_head may never exceed capacity_head"
    )


def assert_appointment(data: dict):
    _assert_common(data, "Appointment")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("capacity_day_id", ""))
    assert data["species"] in SPECIES
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert isinstance(data["appointment_date"], str) and data["appointment_date"]
    assert isinstance(data["deposit_amount_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)
    assert isinstance(data["refund_cents"], int)
    assert data["status"] in APPOINTMENT_STATUSES
    _assert_optional_ts(data, "deposit_due_at", "Appointment")


def assert_animal(data: dict):
    _assert_common(data, "Animal")
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert data["species"] in SPECIES
    assert data["status"] in ANIMAL_STATUSES
    _assert_optional_ts(data, "received_at", "Animal")
    _assert_optional_ts(data, "slaughtered_at", "Animal")
    _assert_optional_ts(data, "weighed_at", "Animal")


def assert_carcass_share(data: dict):
    _assert_common(data, "CarcassShare")
    assert is_valid_uuid(data.get("animal_id", ""))
    assert is_valid_uuid(data.get("owner_customer_id", ""))
    fraction = data["share_fraction"]
    assert isinstance(fraction, (int, float)) and 0 < fraction <= 1.0
    assert data["intended_use"] in INTENDED_USES
    assert data["status"] in SHARE_STATUSES


def assert_cut_sheet(data: dict):
    _assert_common(data, "CutSheet")
    assert is_valid_uuid(data.get("share_id", ""))
    assert isinstance(data["grind_pct"], int) and 0 <= data["grind_pct"] <= 100
    package_weight = data["package_weight_lbs"]
    assert isinstance(package_weight, (int, float)) and package_weight >= 1.0
    assert data["status"] in CUT_SHEET_STATUSES


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data.get("share_id", ""))
    assert data["species"] in SPECIES
    for field in (
        "processing_fee_cents", "slaughter_share_cents", "storage_cents",
        "surcharge_cents", "deposit_credit_cents", "provisional_total_cents",
        "total_cents", "amount_paid_cents", "amount_due_cents",
    ):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"
    assert isinstance(data["storage_waived"], bool)
    assert data["status"] in INVOICE_STATUSES


def assert_invoice_invariants(data: dict):
    """amount_due is total minus paid, floored at zero (PRD §3.6)."""
    assert data["amount_due_cents"] == max(
        0, data["total_cents"] - data["amount_paid_cents"]
    ), (
        f"amount_due_cents {data['amount_due_cents']} != "
        f"max(0, {data['total_cents']} - {data['amount_paid_cents']})"
    )


def assert_storage_record(data: dict):
    _assert_common(data, "StorageRecord")
    assert is_valid_uuid(data.get("share_id", ""))
    _assert_optional_ts(data, "ready_at", "StorageRecord")
    _assert_optional_ts(data, "picked_up_at", "StorageRecord")
    assert isinstance(data["freezer_units"], int) and data["freezer_units"] >= 1
    assert isinstance(data["days_stored"], int) and data["days_stored"] >= 0
    assert isinstance(data["accrued_fee_cents"], int) and data["accrued_fee_cents"] >= 0
    assert data["status"] in STORAGE_STATUSES


def assert_label_record(data: dict):
    _assert_common(data, "LabelRecord")
    assert is_valid_uuid(data.get("share_id", ""))
    assert data["program"] == "CUSTOM_EXEMPT"
    assert isinstance(data["label_text"], str)
    assert data["label_text"].startswith("NOT FOR SALE"), (
        "label_text must begin with the exact string 'NOT FOR SALE' (PRD §3.7)"
    )
    assert data["status"] in LABEL_STATUSES
