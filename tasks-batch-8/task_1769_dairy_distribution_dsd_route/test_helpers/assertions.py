"""Entity assertions and domain invariant checkers (PRD §2.4 common fields).

Primary resources carry id / created_at / updated_at / version (§2.4); the two
event-log entities (TemperatureReading, CrateTransaction) carry only id and
created_at — both updated_at and version are absent from them.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an int"


def _assert_event_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_distributor(data: dict):
    _assert_common_fields(data, "Distributor")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["credit_terms_days"], int)


def assert_route(data: dict):
    _assert_common_fields(data, "Route")
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "RETIRED")
    assert data["credit_price_basis"] in ("ORIGINAL", "CURRENT")


def assert_driver(data: dict):
    _assert_common_fields(data, "Driver")
    assert data["cdl_class"] in ("A", "B")


def assert_store(data: dict):
    _assert_common_fields(data, "Store")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["crate_balance"], int)
    assert isinstance(data["open_ar_cents"], int)
    assert isinstance(data["deposit_liability_cents"], int)


def assert_product(data: dict):
    _assert_common_fields(data, "Product")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["units_per_case"], int)


def assert_standing_par(data: dict):
    _assert_common_fields(data, "StandingPar")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_pricing_period(data: dict):
    _assert_common_fields(data, "PricingPeriod")
    assert data["status"] in ("OPEN", "CLOSED")


def assert_price_announcement(data: dict):
    _assert_common_fields(data, "PriceAnnouncement")
    assert data["kind"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_truck_trip(data: dict):
    _assert_common_fields(data, "TruckTrip")
    assert data["status"] in (
        "PLANNED", "DEPARTED", "COMPLETED", "QA_REVIEW",
        "BREACH_CONFIRMED", "RECONCILED", "CANCELLED",
    )
    assert isinstance(data["cold_chain_breach"], bool)


def assert_temperature_reading(data: dict):
    _assert_event_fields(data, "TemperatureReading")
    assert data["zone"] in ("CAB", "BOX")
    assert isinstance(data["temp_tenths_f"], int)


def assert_route_order(data: dict):
    _assert_common_fields(data, "RouteOrder")
    assert data["fulfillment_status"] in (
        "PLANNED", "CONFIRMED", "DELIVERED", "CANCELLED"
    )
    assert data["payment_status"] in (
        "UNINVOICED", "INVOICED", "PARTIALLY_PAID", "PAID"
    )
    assert data["source"] in ("PAR_GENERATED", "MANUAL")


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert data["status"] in ("OPEN", "SETTLED", "VOID")
    assert data["pricing_basis"] in ("PROVISIONAL", "FINAL")
    assert_invoice_invariants(data)


def assert_return(data: dict):
    _assert_common_fields(data, "Return")
    assert data["status"] in (
        "UNDER_REVIEW", "APPROVED", "CREDITED", "REJECTED", "DISPUTED"
    )
    assert data["reason_code"] in (
        "OUT_OF_CODE", "PULL_POLICY", "DAMAGED", "COLD_CHAIN"
    )


def assert_credit_memo(data: dict):
    _assert_common_fields(data, "CreditMemo")
    assert data["status"] in ("ISSUED", "PARTIALLY_APPLIED", "APPLIED", "VOID")
    assert_credit_memo_invariants(data)


def assert_crate_transaction(data: dict):
    _assert_event_fields(data, "CrateTransaction")
    assert data["kind"] in ("DROP", "PICKUP", "ADJUSTMENT")


def assert_merchandising_session(data: dict):
    _assert_common_fields(data, "MerchandisingSession")
    assert data["status"] in ("OPEN", "CLOSED")


def assert_route_sale_listing(data: dict):
    _assert_common_fields(data, "RouteSaleListing")
    assert data["status"] in (
        "DRAFT", "LISTED", "OFFER_PENDING", "UNDER_CONTRACT",
        "CLOSED", "WITHDRAWN",
    )


def assert_invoice_invariants(data: dict):
    """Money conservation on an invoice (PRD §3.5):
    amount_due == total - credits_applied - payments_applied."""
    total = data["total_cents"]
    assert data["subtotal_cents"] - data["discount_cents"] == total, (
        "total_cents must equal subtotal_cents - discount_cents"
    )
    due = total - data["credits_applied_cents"] - data["payments_applied_cents"]
    assert data["amount_due_cents"] == due, (
        f"amount_due_cents {data['amount_due_cents']} != expected {due}"
    )


def assert_credit_memo_invariants(data: dict):
    """remaining == amount - applied (PRD §3.6)."""
    remaining = data["amount_cents"] - data["applied_cents"]
    assert data["remaining_cents"] == remaining, (
        f"remaining_cents {data['remaining_cents']} != expected {remaining}"
    )


def assert_store_crate_invariants(data: dict):
    """deposit_liability == crate_balance * crate_deposit_cents (PRD §2.8)."""
    liability = data["crate_balance"] * data["crate_deposit_cents"]
    assert data["deposit_liability_cents"] == liability, (
        f"deposit_liability_cents {data['deposit_liability_cents']} != {liability}"
    )
    assert data["crate_balance"] >= 0, "crate_balance may never go negative"
