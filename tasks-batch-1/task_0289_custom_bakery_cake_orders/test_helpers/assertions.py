"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the server-managed fields and enum membership
for a resource payload. Domain invariant checkers verify cross-field rules that
must hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

PRODUCTION_STATUSES = [
    "DRAFT", "QUOTED", "PROOF_PENDING", "CHANGES_REQUESTED", "PROOF_APPROVED",
    "IN_PRODUCTION", "READY", "FULFILLED", "CANCELLED",
]
PAYMENT_STATUSES = ["UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED"]
PROOF_STATUSES = ["AWAITING_REVIEW", "APPROVED", "SUPERSEDED", "REJECTED"]
RESERVATION_STATUSES = ["HELD", "COMMITTED", "RELEASED"]
LOYALTY_TIERS = ["STANDARD", "SILVER", "GOLD"]
PAYMENT_KINDS = ["DEPOSIT", "BALANCE", "REFUND"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_order(data: dict):
    _assert_common(data)
    assert data["production_status"] in PRODUCTION_STATUSES, \
        f"unexpected production_status {data.get('production_status')!r}"
    assert data["payment_status"] in PAYMENT_STATUSES, \
        f"unexpected payment_status {data.get('payment_status')!r}"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert is_valid_uuid(data.get("production_day_id", "")), "production_day_id must be a UUID"
    for f in ("estimate_total_cents", "deposit_due_cents", "balance_due_cents"):
        assert isinstance(data.get(f), int), f"{f} must be an integer"


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data.get("units"), int) and data["units"] >= 1, "units must be >= 1"
    assert isinstance(data.get("line_surcharge_cents"), int), "line_surcharge_cents must be int"
    assert isinstance(data.get("selected_option_codes"), list)
    assert isinstance(data.get("requested_dietary_codes"), list)
    assert isinstance(data.get("effective_allergen_codes"), list)


def assert_design_proof(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data.get("revision_number"), int) and data["revision_number"] >= 1
    assert data["proof_status"] in PROOF_STATUSES, f"unexpected proof_status {data.get('proof_status')!r}"


def assert_slot_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert data["fulfillment_mode"] in ("PICKUP", "DELIVERY")
    assert data["status"] in RESERVATION_STATUSES, f"unexpected status {data.get('status')!r}"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data.get("email"), str) and len(data["email"]) > 0
    assert isinstance(data.get("store_credit_cents"), int)
    assert isinstance(data.get("lifetime_spend_cents"), int)
    assert data["loyalty_tier"] in LOYALTY_TIERS, f"unexpected loyalty_tier {data.get('loyalty_tier')!r}"


def assert_payment(data: dict):
    """Payment is an immutable ledger entry: id + created_at, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in PAYMENT_KINDS, f"unexpected kind {data.get('kind')!r}"
    assert isinstance(data.get("amount_cents"), int), "amount_cents must be an integer"


def assert_payment_is_immutable_ledger(data: dict):
    """A Payment carries only id and created_at; it has no version and no updated_at."""
    assert "version" not in data, "Payment must not expose a version field"
    assert "updated_at" not in data, "Payment must not expose an updated_at field"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("base_price_cents"), int) and data["base_price_cents"] >= 0
    assert isinstance(data.get("base_lead_days"), int) and data["base_lead_days"] >= 0
    assert data.get("status") in ("ACTIVE", "RETIRED")


def assert_production_day(data: dict):
    _assert_common(data)
    assert isinstance(data.get("unit_capacity"), int) and data["unit_capacity"] >= 0
    assert isinstance(data.get("units_committed"), int) and data["units_committed"] >= 0


def assert_units_committed(pday: dict, expected: int):
    actual = pday.get("units_committed")
    assert actual == expected, f"Expected units_committed == {expected}, got {actual}"
