"""Entity assertions and small lookup helpers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

POSTURES = ["OPEN", "SURGE_CONSTRAINED", "FROZEN"]
FULFILLMENT_STATUSES = [
    "DRAFT", "QUOTED", "CONFIRMED", "WAITLISTED", "STAGED", "READY_FOR_PICKUP",
    "IN_TRANSIT", "DELIVERED", "PICKED_UP", "NO_SHOW", "CANCELLED",
]
BILLING_STATUSES = ["UNBILLED", "INVOICED", "PAID"]
INVOICE_STATUSES = ["DRAFT", "ISSUED", "PARTIALLY_PAID", "OVERDUE", "PAID", "VOID"]
HOLD_STATUSES = ["RESERVED", "OCCUPIED", "RELEASED", "EXPIRED"]
SLOT_STATUSES = ["OPEN", "FULL", "CLOSED"]
RUN_STATUSES = ["PLANNED", "LOCKED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
ROUTE_STATUSES = ["ACTIVE", "PAUSED", "TERMINATED"]
CERT_STATUSES = ["ACTIVE", "SUSPENDED", "EXPIRED"]
WAITLIST_STATUSES = ["QUEUED", "PROMOTED", "WITHDRAWN", "EXPIRED"]
BOOK_STATUSES = ["SCHEDULED", "ACTIVE", "SUPERSEDED"]


def _assert_common(data, entity):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_depot(data):
    _assert_common(data, "Depot")
    assert data["posture"] in POSTURES
    assert isinstance(data["freezer_capacity_pallets"], int)
    assert isinstance(data["freezer_reserved_pallets"], int)
    assert isinstance(data["freezer_free_pallets"], int)
    assert isinstance(data["ops_run_index"], int)


def assert_customer(data):
    _assert_common(data, "Customer")
    assert data["standing"] in ["GOOD", "HOLD"]
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["outstanding_exposure_cents"], int)


def assert_certification(data):
    _assert_common(data, "HandlerCertification")
    assert data["status"] in CERT_STATUSES


def assert_price_book(data):
    _assert_common(data, "PriceBook")
    assert data["status"] in BOOK_STATUSES


def assert_surge_window(data):
    _assert_common(data, "SurgeWindow")
    assert data["status"] in ["SCHEDULED", "ACTIVE", "ENDED"]


def assert_route(data):
    _assert_common(data, "RecurringRoute")
    assert data["status"] in ROUTE_STATUSES


def assert_order(data):
    _assert_common(data, "Order")
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    assert data["billing_status"] in BILLING_STATUSES


def assert_order_line(data):
    _assert_common(data, "OrderLine")
    assert isinstance(data["quantity_units"], int)
    assert isinstance(data["unit_weight_lbs"], int)


def assert_delivery_slot(data):
    _assert_common(data, "DeliverySlot")
    assert data["status"] in SLOT_STATUSES
    assert isinstance(data["reserved_pallets"], int)
    assert isinstance(data["capacity_pallets"], int)


def assert_cold_storage_hold(data):
    _assert_common(data, "ColdStorageHold")
    assert data["status"] in HOLD_STATUSES
    assert data["zone"] in ["GENERAL_FREEZER", "DRY_ICE_BUNKER"]


def assert_dispatch_run(data):
    _assert_common(data, "DispatchRun")
    assert data["status"] in RUN_STATUSES


def assert_invoice(data):
    _assert_common(data, "Invoice")
    assert data["status"] in INVOICE_STATUSES
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_payment(data):
    """Payments are append-only ledger rows (PRD §2.5): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "Payment.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Payment.created_at must be ISO 8601"
    )
    assert "version" not in data, "Payment must not carry version"
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["applied_cents"], int)
    assert isinstance(data["overpayment_cents"], int)


def assert_waitlist_entry(data):
    """Waitlist entries are transient queue records (PRD §2.5): id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "WaitlistEntry.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "WaitlistEntry.created_at must be ISO 8601"
    )
    assert "version" not in data, "WaitlistEntry must not carry version"
    assert "updated_at" not in data, "WaitlistEntry must not carry updated_at"
    assert data["status"] in WAITLIST_STATUSES


def find_line_by_quantity(lines, quantity_units):
    """Locate an order line by its (unique-in-test) quantity."""
    matches = [l for l in lines if l.get("quantity_units") == quantity_units]
    assert len(matches) == 1, (
        f"Expected exactly one line with quantity_units={quantity_units}, "
        f"got {len(matches)}"
    )
    return matches[0]
