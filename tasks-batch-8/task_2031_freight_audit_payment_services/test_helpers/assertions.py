"""Entity assertions and domain invariant checkers.

Each assert_{entity}() verifies the common resource properties of PRD §2.5
(id UUID, ISO-8601 created_at/updated_at, integer version) plus the entity's
declared status vocabulary. Optional/nullable fields are only type-checked
when present.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["home_currency"], str) and len(data["home_currency"]) == 3


def assert_carrier(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_ONBOARD", "ACTIVE", "SUSPENDED", "OFFBOARDED")
    assert isinstance(data["scac_code"], str) and data["scac_code"]
    assert isinstance(data["billing_currency"], str)


def assert_rate_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "EXPIRED", "DISCARDED")
    assert isinstance(data["lanes"], list) and len(data["lanes"]) > 0
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ("REGISTERED", "INVOICED", "CLOSED", "VOIDED")
    assert data["mode"] in ("PARCEL", "LTL", "FTL", "AIR", "OCEAN")
    assert isinstance(data["pro_number"], str) and data["pro_number"]


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["audit_status"] in (
        "RECEIVED", "CAPTURED", "RATED", "CLEARED", "EXCEPTION", "VOIDED",
    )
    assert data["payment_status"] in (
        "UNPAID", "SCHEDULED", "PAID", "SHORT_PAID", "WRITTEN_OFF",
    )
    assert isinstance(data["billed_total_minor"], int)
    assert isinstance(data["invoice_number"], str) and data["invoice_number"]


def assert_invoice_line(data: dict):
    _assert_common(data)
    assert data["charge_code"] in (
        "BASE_FREIGHT", "FUEL_SURCHARGE", "LIFTGATE", "RESIDENTIAL",
        "INSIDE_DELIVERY", "DETENTION", "STORAGE", "OTHER",
    )
    assert isinstance(data["billed_amount_minor"], int)


def assert_audit_exception(data: dict):
    _assert_common(data)
    assert data["code"] in (
        "RATE_MISMATCH", "DUPLICATE_FUZZY", "INVALID_ACCESSORIAL", "NO_CONTRACT",
    )
    assert data["status"] in (
        "OPEN", "CARRIER_NOTIFIED", "CARRIER_RESPONDED", "RESOLVED_ACCEPTED",
        "RESOLVED_CONCEDED", "ESCALATED", "EXPIRED",
    )
    assert data["routed_queue"] in ("AUDIT_TEAM", "CARRIER", "FINANCE")
    assert isinstance(data["disputed_amount_minor"], int)
    assert isinstance(data["round_count"], int)


def assert_gl_account(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["active"], bool)


def assert_cost_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["percentage_bp"], int)
    assert isinstance(data["allocated_minor"], int)


def assert_payment_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "LOCKED", "RELEASED", "SETTLED", "CANCELLED")
    assert isinstance(data["run_date"], str)
    assert isinstance(data["currency"], str)


def assert_payment_run_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "RELEASED", "PAID")
    assert isinstance(data["scheduled_amount_minor"], int)


def assert_remittance_advice(data: dict):
    _assert_common(data)
    assert data["status"] in ("GENERATED", "SENT", "ACKNOWLEDGED")
    assert isinstance(data["total_minor"], int)
    assert isinstance(data["item_count"], int)


def assert_fx_rate(data: dict):
    _assert_common(data)
    assert isinstance(data["rate_ppm"], int)
    assert data["source"] in ("ECB", "MANUAL")


def assert_recovery_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFTED", "FILED", "ACKNOWLEDGED", "REBUTTED", "COLLECTED", "ABANDONED",
    )
    assert data["channel"] in ("CREDIT_MEMO", "REFUND", "OFFSET")
    assert isinstance(data["claimed_amount_minor"], int)


def assert_analytics_export(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "COMPLETED", "FAILED")
    assert isinstance(data["row_count"], int)
    assert isinstance(data["checksum"], str)


def assert_invoice_money_invariant(invoice: dict):
    """Payment-dimension conservation (PRD §3.8): what has been paid plus what
    is scheduled never exceeds the approved amount, and both accumulators are
    non-negative."""
    paid = invoice.get("paid_minor", 0)
    scheduled = invoice.get("scheduled_minor", 0)
    assert paid >= 0 and scheduled >= 0
    approved = invoice.get("approved_amount_minor")
    if approved is not None:
        assert paid + scheduled <= approved, (
            f"paid {paid} + scheduled {scheduled} exceeds approved {approved}"
        )
