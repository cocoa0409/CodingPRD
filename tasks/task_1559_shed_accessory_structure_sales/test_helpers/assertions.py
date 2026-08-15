"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ORDER_STATUSES = [
    "DRAFT", "SITE_REVIEW", "PERMIT_REVIEW", "READY_TO_SCHEDULE", "SCHEDULED",
    "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED",
]
STRUCTURE_STATES = ["NOT_INSTALLED", "INSTALLED", "REPOSSESSION_PENDING", "REPOSSESSED"]
ASSESSMENT_STATUSES = ["REQUESTED", "REPORTED", "CANCELLED"]
VERDICTS = ["SUITABLE", "SUITABLE_WITH_PREP", "UNSUITABLE"]
PERMIT_STATUSES = ["SUBMITTED", "APPROVED", "DENIED", "NOT_REQUIRED", "WITHDRAWN"]
CONTRACT_STATUSES = ["ACTIVE", "DELINQUENT", "DEFAULTED", "PAID_OFF"]
PAYMENT_KINDS = ["DEPOSIT", "BALANCE", "RTO_PAYMENT", "REFUND"]
PAYMENT_METHODS = ["CASH", "CARD", "CHECK"]
TICKET_STATUSES = ["OPEN", "SCHEDULED", "RESOLVED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_jurisdiction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["county_name"], str)
    assert isinstance(data["permit_threshold_sqft"], int)
    assert isinstance(data["anchoring_required"], bool)
    assert isinstance(data["permit_base_fee_cents"], int)
    assert isinstance(data["permit_per_sqft_cents"], int)
    assert isinstance(data["tax_rate_bp"], int)


def assert_structure_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["supported_delivery_modes"], list)
    assert set(data["supported_delivery_modes"]) <= {"PRE_BUILT", "ON_SITE_BUILD"}
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["overage_rate_tier1_cents"], int)
    assert isinstance(data["overage_rate_tier2_cents"], int)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str)
    assert isinstance(data["zip"], str)


def assert_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ORDER_STATUSES
    assert data["structure_state"] in STRUCTURE_STATES
    assert data["delivery_mode"] in ("PRE_BUILT", "ON_SITE_BUILD")
    assert data["foundation_type"] in ("GRAVEL_PAD", "CONCRETE_SLAB", "PIERS", "NONE")
    assert data["anchor_type"] in ("AUGER_STRAP", "NONE")
    assert data["purchase_type"] in ("CASH", "RTO")
    assert isinstance(data["options"], list)
    assert isinstance(data["area_sqft"], (int, float))
    assert isinstance(data["structure_price_cents"], int)
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["collected_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["retained_cents"], int)
    assert isinstance(data["site_prep_required"], bool)
    assert isinstance(data["site_prep_fee_cents"], int)
    assert isinstance(data["removal_requested"], bool)


def assert_site_assessment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ASSESSMENT_STATUSES
    assert isinstance(data["order_id"], str)
    assert isinstance(data["assessor_id"], str)
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["window_start_hour"], int)
    assert 6 <= data["window_start_hour"] <= 20
    if data.get("verdict") is not None:
        assert data["verdict"] in VERDICTS


def assert_permit_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in PERMIT_STATUSES
    assert isinstance(data["order_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["jurisdiction_version"], int)
    assert isinstance(data["area_sqft"], (int, float))
    assert isinstance(data["permit_required"], bool)
    assert isinstance(data["fee_cents"], int)


def assert_rto_contract(data: dict):
    _assert_common_fields(data)
    assert data["status"] in CONTRACT_STATUSES
    assert isinstance(data["order_id"], str)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["total_contract_cents"], int)
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["final_payment_cents"], int)
    assert isinstance(data["amount_applied_cents"], int)
    assert isinstance(data["remaining_balance_cents"], int)
    assert isinstance(data["accrued_late_fees_cents"], int)
    assert isinstance(data["written_off_cents"], int)
    assert isinstance(data["delinquency_episodes"], int)


def assert_payment(data: dict):
    # Payments are immutable records: id + created_at only (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert data["kind"] in PAYMENT_KINDS
    assert data["method"] in PAYMENT_METHODS
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["idempotency_key"], str)
    assert isinstance(data["order_id"], str)


def assert_service_ticket(data: dict):
    _assert_common_fields(data)
    assert data["status"] in TICKET_STATUSES
    assert isinstance(data["order_id"], str)
    assert isinstance(data["issue_description"], str)
    assert isinstance(data["reopen_count"], int)
    assert isinstance(data["parts_cents"], int)


def assert_rto_receivable_conservation(contract: dict):
    """Invariant (PRD §3.7): applied + remaining + written_off == total."""
    total = (
        contract["amount_applied_cents"]
        + contract["remaining_balance_cents"]
        + contract["written_off_cents"]
    )
    assert total == contract["total_contract_cents"], (
        f"receivable conservation broken: {contract['amount_applied_cents']} + "
        f"{contract['remaining_balance_cents']} + {contract['written_off_cents']} "
        f"!= {contract['total_contract_cents']}"
    )


def assert_rto_schedule_sums(contract: dict):
    """Invariant (PRD §3.7): monthly*(term-1) + final == total exactly."""
    lhs = contract["monthly_payment_cents"] * (contract["term_months"] - 1) + contract[
        "final_payment_cents"
    ]
    assert lhs == contract["total_contract_cents"], (
        f"installment schedule does not sum to contract total: {lhs} != "
        f"{contract['total_contract_cents']}"
    )


def assert_cancellation_cash_conservation(order: dict):
    """Invariant (PRD §3.6): refund + retained == collected exactly."""
    lhs = order["refunded_cents"] + order["retained_cents"]
    assert lhs == order["collected_cents"], (
        f"cash conservation broken: {order['refunded_cents']} + "
        f"{order['retained_cents']} != {order['collected_cents']}"
    )
