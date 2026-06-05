"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Generic envelope-side assertions (PRD §2.4) ─────────────────


def assert_common_fields(data: dict):
    """Mutable entities carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_append_only_fields(data: dict):
    """Append-only entities (CCRReview, User) carry id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ─── Per-entity assertions ───────────────────────────────────────


_AGREEMENT_STATUSES = {
    "DRAFT", "ACTIVE", "UNDER_CONTRACT", "CLEARED_TO_CLOSE", "CLOSED", "TERMINATED",
}


def assert_purchase_agreement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["buyer_name"], str) and len(data["buyer_name"]) > 0
    assert isinstance(data["seller_name"], str) and len(data["seller_name"]) > 0
    assert isinstance(data["property_address"], str)
    assert isinstance(data["purchase_price_cents"], int)
    assert data["purchase_price_cents"] >= 100_000
    assert data["purchase_price_cents"] <= 1_000_000_000_000
    assert isinstance(data["earnest_money_required_cents"], int)
    assert isinstance(data["earnest_money_received_cents"], int)
    assert data["earnest_money_received_cents"] >= 0
    assert data["status"] in _AGREEMENT_STATUSES, \
        f"unexpected status {data['status']!r}"
    assert is_iso8601_timestamp(data["scheduled_closing_date"])


_ESCROW_STATUSES = {"OPEN", "FUNDED", "DISBURSED", "CLOSED"}


def assert_escrow_account(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["balance_cents"], int)
    assert data["balance_cents"] >= 0
    assert data["status"] in _ESCROW_STATUSES, \
        f"unexpected status {data['status']!r}"


_EMD_STATUSES = {"PENDING", "CONFIRMED", "REFUNDED", "FORFEITED"}


def assert_earnest_money_deposit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["escrow_account_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert data["depositor_role"] in {"BUYER", "BUYERS_AGENT"}
    assert data["status"] in _EMD_STATUSES, \
        f"unexpected status {data['status']!r}"


_TITLE_SEARCH_STATUSES = {"ORDERED", "COMPLETED", "RESOLVED"}


def assert_title_search(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["defects"], list)
    assert isinstance(data["has_material_defect"], bool)
    assert data["status"] in _TITLE_SEARCH_STATUSES, \
        f"unexpected status {data['status']!r}"


_TITLE_POLICY_STATUSES = {"PENDING", "ISSUED", "VOIDED"}


def assert_title_insurance_policy(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["title_search_id"])
    assert isinstance(data["coverage_amount_cents"], int)
    assert data["coverage_amount_cents"] >= 0
    assert isinstance(data["premium_cents"], int)
    assert data["premium_cents"] >= 0
    assert data["status"] in _TITLE_POLICY_STATUSES, \
        f"unexpected status {data['status']!r}"


def assert_ccr_review(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["restrictions_summary"], str)
    assert isinstance(data["buyer_acknowledged"], bool)


_CD_STATUSES = {"DRAFT", "DELIVERED", "REISSUED", "ACKNOWLEDGED", "EXPIRED"}
_CD_PRODUCT_TYPES = {"FIXED", "ARM", "IO", "BALLOON"}


def assert_closing_disclosure(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["cd_apr_bps"], int)
    assert isinstance(data["cd_total_loan_amount_cents"], int)
    assert isinstance(data["cd_monthly_payment_cents"], int)
    assert data["cd_product_type"] in _CD_PRODUCT_TYPES
    assert isinstance(data["cd_prepayment_penalty"], bool)
    assert data["status"] in _CD_STATUSES, \
        f"unexpected status {data['status']!r}"


_WIRE_STATUSES = {"PROVIDED", "VERIFIED", "LOCKED", "REJECTED"}
_WIRE_PARTIES = {"BUYER", "SELLER", "LENDER", "EXCHANGE_ACCOMMODATOR"}


def assert_wire_instruction(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["party"] in _WIRE_PARTIES
    assert isinstance(data["beneficiary_bank_name"], str)
    assert isinstance(data["beneficiary_account_last4"], str)
    assert isinstance(data["routing_number"], str)
    assert isinstance(data["voice_callback_completed"], bool)
    assert data["status"] in _WIRE_STATUSES, \
        f"unexpected status {data['status']!r}"


_DISBURSEMENT_STATUSES = {"QUEUED", "DISBURSED", "REVERSED"}
_DISBURSEMENT_PURPOSES = {
    "SELLER_PROCEEDS", "LENDER_PAYOFF", "TITLE_PREMIUM",
    "EXCHANGE_FUNDS", "EARNEST_REFUND",
}


def assert_disbursement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["escrow_account_id"])
    assert is_valid_uuid(data["wire_instruction_id"])
    assert data["purpose"] in _DISBURSEMENT_PURPOSES
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert data["status"] in _DISBURSEMENT_STATUSES, \
        f"unexpected status {data['status']!r}"


_EXCHANGE_STATUSES = {"OPEN", "IDENTIFIED", "COMPLETED", "FAILED"}


def assert_exchange_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["taxpayer_name"], str)
    assert isinstance(data["qualified_intermediary_name"], str)
    assert is_iso8601_timestamp(data["relinquished_closing_date"])
    assert is_iso8601_timestamp(data["identification_deadline"])
    assert is_iso8601_timestamp(data["exchange_deadline"])
    assert isinstance(data["replacement_property_identified"], bool)
    assert data["status"] in _EXCHANGE_STATUSES, \
        f"unexpected status {data['status']!r}"


def assert_user(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role"] in {"EscrowOfficer", "TitleAgent", "ComplianceOfficer"}
