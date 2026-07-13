"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Every entity carries the four
common system fields (id/created_at/updated_at/version).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_corporate_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]


def assert_rate_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    for f in ("monthly_rate_cents", "utility_monthly_cents",
              "cleaning_fee_cents", "occupancy_tax_rate_bps"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["property_name"], str)
    assert isinstance(data["bedrooms"], int) and data["bedrooms"] >= 0
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "TURNOVER")


def assert_master_lease(data: dict):
    _assert_common(data)
    assert isinstance(data["committed_units"], int) and data["committed_units"] >= 1
    assert isinstance(data["negotiated_monthly_rate_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")
    assert_master_lease_capacity_invariant(data)


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)


def assert_stay(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["rate_plan_id"], str)
    assert data["status"] in (
        "RESERVED", "ACTIVE", "COMPLETED", "COMPLETED_EARLY", "CANCELLED"
    )
    assert isinstance(data["planned_nights"], int)
    assert_deposit_conservation_invariant(data)


def assert_housekeeping_visit(data: dict):
    _assert_common(data)
    assert isinstance(data["stay_id"], str)
    assert data["visit_type"] in ("STANDARD", "DEEP")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_damage_charge(data: dict):
    _assert_common(data)
    assert isinstance(data["stay_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("ASSESSED", "DISPUTED", "CHARGED", "WAIVED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["stay_id"], str)
    assert data["invoice_kind"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("DRAFT", "ISSUED", "PAID")
    for f in ("nights_billed", "rate_subtotal_cents", "cleaning_fee_cents",
              "occupancy_tax_cents", "amount_due_cents", "damage_total_cents",
              "total_settlement_cents", "deposit_refund_cents"):
        assert isinstance(data[f], int), f"{f} must be an int"


def assert_turnover(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["stay_id"], str)
    assert data["status"] in ("SCHEDULED", "COMPLETED")


# --- Domain invariants ---

def assert_deposit_conservation_invariant(stay: dict):
    """PRD §3.8: deposit_held_cents = deposit_refundable_cents + deposit_charged_cents."""
    held = stay["deposit_held_cents"]
    charged = stay["deposit_charged_cents"]
    refundable = stay["deposit_refundable_cents"]
    assert refundable >= 0, "deposit_refundable_cents must never be negative"
    assert held == refundable + charged, (
        f"deposit conservation violated: held={held} != "
        f"refundable={refundable} + charged={charged}"
    )


def assert_master_lease_capacity_invariant(lease: dict):
    """PRD §3.2: committed_units = units_consumed + units_free (units_free >= 0)."""
    committed = lease["committed_units"]
    consumed = lease["units_consumed"]
    free = lease["units_free"]
    assert free >= 0, "units_free must never be negative"
    assert committed == consumed + free, (
        f"capacity conservation violated: committed={committed} != "
        f"consumed={consumed} + free={free}"
    )
