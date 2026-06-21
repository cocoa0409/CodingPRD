"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the structural contract the PRD promises for
that resource (UUID id, ISO-8601 timestamps, status membership, cent-integer
money fields). Domain invariant checkers verify cross-field identities that must
hold after any operation (notably the job ledger conservation identity).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


MOVE_JOB_STATUSES = ["QUOTING", "BOOKED", "IN_TRANSIT", "DELIVERED", "CLOSED", "CANCELLED"]
PAYMENT_STATUSES = ["UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED"]
ESTIMATE_STATUSES = ["DRAFT", "REVISED", "ACCEPTED", "SUPERSEDED", "EXPIRED"]
DISPATCH_STATUSES = ["SCHEDULED", "EN_ROUTE", "COMPLETED", "CANCELLED"]
STORAGE_LOT_STATUSES = ["IN_STORAGE", "RELEASED", "WAIVED"]
DAMAGE_CLAIM_STATUSES = ["UNDER_REVIEW", "APPROVED", "DENIED"]


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_line_item_fields(data: dict):
    """id + created_at ONLY for append-only line items (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["origin_state_code"], str)


def assert_move_job(data: dict):
    _assert_common_fields(data)
    assert data["job_status"] in MOVE_JOB_STATUSES, f"unexpected job_status {data['job_status']}"
    assert data["payment_status"] in PAYMENT_STATUSES, f"unexpected payment_status {data['payment_status']}"
    assert data["service_type"] in ("LOCAL", "LONG_HAUL")
    for fld in ("final_charge_cents", "gross_charges_cents", "balance_due_cents",
                "paid_cents", "waived_cents", "refunded_cents"):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"


def assert_survey(data: dict):
    _assert_common_fields(data)
    assert data["survey_method"] in ("IN_HOME", "VIRTUAL", "SELF_REPORTED")
    assert isinstance(data["estimated_weight_lbs"], int)
    assert isinstance(data["locked"], bool)


def assert_survey_item(data: dict):
    _assert_line_item_fields(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_estimate(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ESTIMATE_STATUSES, f"unexpected estimate status {data['status']}"
    assert data["binding_type"] in ("BINDING", "NON_BINDING")
    assert data["valuation_coverage"] in ("RELEASED", "FULL_VALUE")
    for fld in ("linehaul_cents", "labor_cents", "fuel_surcharge_cents", "packing_cents",
                "valuation_premium_cents", "accessorial_cents", "estimate_total_cents"):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"


def assert_packing_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["packing_total_cents"], int)
    assert isinstance(data["crate_count"], int) and data["crate_count"] >= 0


def assert_truck(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plate"], str) and len(data["plate"]) > 0
    assert isinstance(data["capacity_cubic_feet"], int) and data["capacity_cubic_feet"] > 0


def assert_crew(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["head_count"], int) and data["head_count"] >= 2


def assert_dispatch(data: dict):
    _assert_common_fields(data)
    assert data["status"] in DISPATCH_STATUSES, f"unexpected dispatch status {data['status']}"
    assert isinstance(data["required_crew_size"], int) and data["required_crew_size"] >= 2


def assert_storage_lot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in STORAGE_LOT_STATUSES
    assert isinstance(data["billable_days"], int)
    assert isinstance(data["sit_charge_cents"], int)


def assert_damage_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in DAMAGE_CLAIM_STATUSES
    assert data["coverage_snapshot"] in ("RELEASED", "FULL_VALUE")
    assert isinstance(data["settlement_cents"], int)


def assert_claim_item(data: dict):
    _assert_line_item_fields(data)
    assert isinstance(data["item_weight_lbs"], int) and data["item_weight_lbs"] >= 1


# ─── Domain invariant checkers ────────────────────────────────────────────────
def assert_ledger_identity(job: dict):
    """PRD §2.7: balance_due_cents == gross - paid - waived - refunded."""
    expected = (job["gross_charges_cents"] - job["paid_cents"]
                - job["waived_cents"] - job["refunded_cents"])
    assert job["balance_due_cents"] == expected, (
        f"ledger identity violated: balance_due {job['balance_due_cents']} != "
        f"gross {job['gross_charges_cents']} - paid {job['paid_cents']} - "
        f"waived {job['waived_cents']} - refunded {job['refunded_cents']} = {expected}"
    )
