"""Entity assertions and domain invariant checkers.

Every check here traces to PRD prose: common resource properties (section
2.4), the append-only transaction exception, ledger/derived-field rules
(section 2.7), and the statement_suppression derivation (section 2.8).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ConversionStatus,
    CREDIT_TXN_TYPES,
    DEBIT_TXN_TYPES,
    DeceasedCaseStatus,
    DocType,
    DocumentStatus,
    ExemptionMethod,
    GarnishmentOrderType,
    GarnishmentStatus,
    LifecycleStatus,
    OwnershipType,
    ProductCode,
    SignerRole,
    SignerStatus,
    StatementCycleStatus,
    StatementSuppression,
    SuppressionReason,
    TitleChangeStatus,
)

_LIFECYCLE = [s.value for s in LifecycleStatus]
_RESTRICTION = ["NONE", "LEGAL_HOLD", "DECEASED_HOLD"]
_SUPPRESSION = [s.value for s in StatementSuppression]
_OWNERSHIP = [s.value for s in OwnershipType]
_PRODUCT = [s.value for s in ProductCode]
_TXN_TYPE = CREDIT_TXN_TYPES + DEBIT_TXN_TYPES
_SIGNER_ROLE = [s.value for s in SignerRole]
_SIGNER_STATUS = [s.value for s in SignerStatus]
_DOC_TYPE = [s.value for s in DocType]
_DOC_STATUS = [s.value for s in DocumentStatus]
_TITLE_STATUS = [s.value for s in TitleChangeStatus]
_CASE_STATUS = [s.value for s in DeceasedCaseStatus]
_ORDER_TYPE = [s.value for s in GarnishmentOrderType]
_EXEMPTION = [s.value for s in ExemptionMethod]
_GARN_STATUS = [s.value for s in GarnishmentStatus]
_CYCLE_STATUS = [s.value for s in StatementCycleStatus]
_SUPPRESSION_REASON = [s.value for s in SuppressionReason]
_CONV_STATUS = [s.value for s in ConversionStatus]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_deposit_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("account_number"), str) \
        and len(data["account_number"]) == 10 \
        and data["account_number"].isdigit(), \
        "account_number must be the server-minted ten-digit number"
    assert isinstance(data["primary_owner_name"], str) \
        and data["primary_owner_name"]
    assert isinstance(data["owner_tax_id"], str) and data["owner_tax_id"]
    assert data["ownership_type"] in _OWNERSHIP
    assert data["product_code"] in _PRODUCT
    assert isinstance(data["rate_bps"], int) and 0 <= data["rate_bps"] <= 2000
    assert data["lifecycle_status"] in _LIFECYCLE
    assert data["restriction_status"] in _RESTRICTION
    assert data["statement_suppression"] in _SUPPRESSION
    for field in ("balance_cents", "total_held_cents",
                  "available_balance_cents", "accrued_interest_cents",
                  "fees_assessed_count"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data.get("accrual_start_date"), str)
    assert isinstance(data.get("last_customer_activity_date"), str)


def assert_account_transaction(data: dict):
    # Append-only log: id + created_at only; updated_at and version absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, \
        "a posted transaction carries no updated_at"
    assert "version" not in data, "a posted transaction carries no version"
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["txn_type"] in _TXN_TYPE
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["balance_after_cents"], int)


def assert_authorized_signer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert data["signer_role"] in _SIGNER_ROLE
    assert isinstance(data["signature_card_reference"], str)
    assert data["status"] in _SIGNER_STATUS


def assert_account_document(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["doc_type"] in _DOC_TYPE
    assert isinstance(data["reference_number"], str) \
        and data["reference_number"]
    assert data["status"] in _DOC_STATUS


def assert_title_change_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["current_ownership_type"] in _OWNERSHIP
    assert data["requested_ownership_type"] in _OWNERSHIP
    assert data["requested_ownership_type"] != data["current_ownership_type"]
    assert isinstance(data["required_doc_types"], list)
    assert all(d in _DOC_TYPE for d in data["required_doc_types"])
    assert data["status"] in _TITLE_STATUS
    assert isinstance(data.get("created_by_user_id"), str)


def assert_deceased_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["decedent_name"], str) and data["decedent_name"]
    assert isinstance(data["date_of_death"], str)
    assert isinstance(data["reported_by"], str) and data["reported_by"]
    assert data["status"] in _CASE_STATUS


def assert_garnishment_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["order_type"] in _ORDER_TYPE
    assert isinstance(data["creditor_name"], str) and data["creditor_name"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["served_date"], str)
    assert isinstance(data.get("answer_deadline_date"), str)
    assert data["exemption_method"] in _EXEMPTION
    for field in ("held_amount_cents", "exempt_amount_cents",
                  "collectible_cents", "remitted_amount_cents",
                  "released_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in _GARN_STATUS


def assert_statement_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["cycle_start"], str)
    assert isinstance(data["cycle_end"], str)
    assert data["cycle_start"] < data["cycle_end"], \
        "cycle_start must fall strictly before cycle_end"
    assert data["status"] in _CYCLE_STATUS
    if data["status"] == "SUPPRESSED":
        assert data.get("suppression_reason") in _SUPPRESSION_REASON


def assert_product_conversion(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["from_product_code"] in _PRODUCT
    assert data["to_product_code"] in _PRODUCT
    assert data["from_product_code"] != data["to_product_code"]
    assert isinstance(data["new_rate_bps"], int) \
        and 0 <= data["new_rate_bps"] <= 2000
    assert isinstance(data["effective_date"], str)
    assert data["status"] in _CONV_STATUS


def assert_account_invariants(data: dict):
    """Ledger-derived invariants that must hold for any account read.

    PRD section 2.7: available_balance_cents is balance_cents minus
    total_held_cents. PRD section 2.8: statement_suppression derives from
    the two posture dimensions in strict precedence.
    """
    assert data["available_balance_cents"] == \
        data["balance_cents"] - data["total_held_cents"], (
        f"available {data['available_balance_cents']} != balance "
        f"{data['balance_cents']} - held {data['total_held_cents']}"
    )
    lifecycle = data["lifecycle_status"]
    restriction = data["restriction_status"]
    if lifecycle == "CLOSED":
        expected_suppression = "CLOSED"
    elif restriction == "DECEASED_HOLD":
        expected_suppression = "DECEASED"
    elif lifecycle in ("DORMANT", "ESCHEAT_PENDING"):
        expected_suppression = "DORMANT"
    else:
        expected_suppression = "NONE"
    assert data["statement_suppression"] == expected_suppression, (
        f"statement_suppression {data['statement_suppression']} != derived "
        f"{expected_suppression} for lifecycle={lifecycle} "
        f"restriction={restriction}"
    )
