"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_department(data: dict):
    _assert_common_fields(data, "Department")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cost_center"], str)
    assert isinstance(data["default_approval_limit_cents"], int)


def assert_vendor(data: dict):
    _assert_common_fields(data, "Vendor")
    assert isinstance(data["legal_name"], str)
    assert data["diversity_certification"] in ["NONE", "WBE", "MBE", "DBE", "VBE", "SBE"]
    assert data["sustainability_tier"] in ["NONE", "BRONZE", "SILVER", "GOLD"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_grant(data: dict):
    _assert_common_fields(data, "Grant")
    assert isinstance(data["grant_code"], str)
    assert isinstance(data["total_award_cents"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    for field in ("spent_cents", "encumbered_cents",
                  "provisional_remaining_cents", "settled_remaining_cents"):
        assert isinstance(data[field], int), f"Grant.{field} must be int"


def assert_contract(data: dict):
    _assert_common_fields(data, "Contract")
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "IN_NEGOTIATION", "REVIEW_APPROVED",
        "EXECUTED", "TERMINATED", "SUPERSEDED",
    ]
    assert isinstance(data["negotiation_round"], int)


def assert_requisition(data: dict):
    _assert_common_fields(data, "Requisition")
    assert isinstance(data["requisition_number"], str)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "PO_ISSUED", "CANCELLED",
    ]
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    assert isinstance(data["required_chain"], list)
    assert isinstance(data["current_step_index"], int)
    assert data["sourcing_method"] in [
        "UNDETERMINED", "EXISTING_CONTRACT", "SOLE_SOURCE", "COMPETITIVE_BID",
    ]


def assert_approval_record(data: dict):
    """Immutable audit record: only id + created_at from the common set (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "ApprovalRecord.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ApprovalRecord.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ApprovalRecord must not expose updated_at"
    assert "version" not in data, "ApprovalRecord must not expose version"
    assert data["decision"] in ["APPROVED", "RETURNED"]
    assert data["step_role"] in [
        "DEPARTMENT", "GRANT_COMPLIANCE", "SOLE_SOURCE",
        "PURCHASING", "DIRECTOR", "CONTRACT_REVIEW",
    ]
    assert isinstance(data["step_index"], int)
    assert isinstance(data["actor_id"], str)


def assert_solicitation(data: dict):
    _assert_common_fields(data, "BidSolicitation")
    assert data["status"] in ["OPEN", "CLOSED", "AWARDED", "CANCELLED"]
    assert isinstance(data["requisition_id"], str)
    assert isinstance(data["min_quotes"], int)


def assert_quote(data: dict):
    _assert_common_fields(data, "Quote")
    assert data["status"] in ["SUBMITTED", "AWARDED", "NOT_AWARDED", "DISQUALIFIED"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0


def assert_purchase_order(data: dict):
    _assert_common_fields(data, "PurchaseOrder")
    assert isinstance(data["po_number"], str)
    assert data["fulfillment_status"] in [
        "ISSUED", "PARTIALLY_RECEIVED", "FULLY_RECEIVED", "CANCELLED",
    ]
    assert data["match_status"] in ["UNMATCHED", "MATCHED", "EXCEPTION", "CLOSED"]
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["charge_cents"], int)
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0


def assert_receipt(data: dict):
    _assert_common_fields(data, "Receipt")
    assert data["status"] in ["POSTED", "VOIDED"]
    assert isinstance(data["po_id"], str)
    assert isinstance(data["lines"], list)


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert data["status"] in ["PAYABLE", "EXCEPTION", "PAID", "REJECTED"]
    assert data["exception_reason"] in [
        "NONE", "NO_RECEIPT", "QTY_OVER_RECEIPT",
        "PRICE_VARIANCE", "CONTRACT_TERMINATED", "RECEIPT_VOIDED",
    ]
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["total_variance_cents"], int)
    assert isinstance(data["total_tolerance_cents"], int)


def assert_pcard(data: dict):
    _assert_common_fields(data, "PCard")
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["cycle_index"], int)
    assert isinstance(data["consecutive_unreconciled_cycles"], int)
    assert isinstance(data["utilization_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert isinstance(data["allowed_mccs"], list)


def assert_elevation(data: dict):
    _assert_common_fields(data, "LimitElevation")
    assert data["status"] in ["SCHEDULED", "CANCELLED"]
    assert isinstance(data["elevated_single_txn_limit_cents"], int)


def assert_pcard_transaction(data: dict):
    _assert_common_fields(data, "PCardTransaction")
    assert data["entry_type"] in ["DEBIT", "CREDIT"]
    assert data["status"] in ["POSTED", "RECONCILED", "DISPUTED", "REVERSED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["cycle_index"], int)


def assert_surplus_asset(data: dict):
    _assert_common_fields(data, "SurplusAsset")
    assert data["condition"] in ["NEW", "GOOD", "FAIR", "POOR"]
    assert data["status"] in [
        "DECLARED", "LISTED", "TRANSFERRED", "SOLD", "DONATED", "SCRAPPED",
    ]
    assert isinstance(data["estimated_value_cents"], int)


# --- Domain invariants (PRD §3.1, §3.7, §3.9) --------------------------------

def assert_grant_ledger_conservation(ledger: dict, total_award_cents: int):
    """spent + encumbered + provisional_remaining == total_award (PRD §3.1)."""
    total = (
        ledger["spent_cents"]
        + ledger["encumbered_cents"]
        + ledger["provisional_remaining_cents"]
    )
    assert total == total_award_cents, (
        f"Grant ledger not conserved: {total} != award {total_award_cents}"
    )
    assert ledger["settled_remaining_cents"] == (
        total_award_cents - ledger["spent_cents"]
    ), "settled_remaining_cents must be award minus spent"


def assert_card_credit_invariant(card: dict):
    """utilization + available == monthly_limit (PRD §3.7)."""
    total = card["utilization_cents"] + card["available_credit_cents"]
    assert total == card["monthly_limit_cents"], (
        f"Card credit decomposition not conserved: {total} != "
        f"monthly limit {card['monthly_limit_cents']}"
    )


def assert_proceeds_conservation(asset: dict):
    """cost_recovery + dept_share + central_share == sale_price (PRD §3.9)."""
    total = (
        asset["proceeds_cost_recovery_cents"]
        + asset["proceeds_dept_share_cents"]
        + asset["proceeds_central_share_cents"]
    )
    assert total == asset["sale_price_cents"], (
        f"Proceeds buckets {total} do not sum to sale price "
        f"{asset['sale_price_cents']}"
    )
