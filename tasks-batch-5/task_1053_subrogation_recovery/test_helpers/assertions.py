"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CLAIM_STATUSES = [
    "REFERRED", "LIABILITY_ASSESSED", "DEMAND_ISSUED", "ARBITRATION",
    "SETTLED", "RECOVERED", "WITHDRAWN", "STATUTE_EXPIRED",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["naic_code"], str)
    assert isinstance(data["commission_rate_bps"], int)
    assert data["commission_basis"] in ("GROSS", "NET")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_adverse_party(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["adverse_carrier_name"], str)
    assert isinstance(data["is_arbitration_eligible"], bool)
    assert isinstance(data["policy_limit_cents"], int) and data["policy_limit_cents"] >= 0


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["adverse_party_id"], str)
    assert data["status"] in CLAIM_STATUSES
    assert isinstance(data["paid_loss_cents"], int)
    assert isinstance(data["deductible_cents"], int)
    assert isinstance(data["total_damages_cents"], int)
    for f in ("final_recovered_cents", "deductible_reimbursed_cents",
              "carrier_recovered_cents", "accrued_commission_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_ledger_conserved(claim: dict):
    """Ledger totals never drift below zero (PRD §2.8 conservation)."""
    for f in ("final_recovered_cents", "deductible_reimbursed_cents",
              "carrier_recovered_cents", "accrued_commission_cents"):
        assert claim[f] >= 0, f"{f} must never be negative, got {claim[f]}"


def assert_demand(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["amount_demanded_cents"], int)
    assert data["status"] in ("ISSUED", "HONORED", "DISPUTED", "EXPIRED", "WITHDRAWN")


def assert_arbitration(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["forum"], str)
    assert isinstance(data["round_count"], int)
    assert data["status"] in ("FILED", "AWAITING_RESPONSE", "RESPONSE_FILED", "DECIDED", "WITHDRAWN")


def assert_settlement(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["settled_amount_cents"], int)
    assert isinstance(data["proposed_by_user_id"], str)
    assert data["status"] in ("PROPOSED", "APPROVED", "ACCEPTED", "REJECTED", "SUPERSEDED")


def assert_recovery_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("RECEIVED", "CLEARED", "REVERSED", "BOUNCED")


def assert_allocation_conserved(payment: dict):
    """PRD §3.6 — the three waterfall buckets sum exactly to the gross amount."""
    total = (payment["alloc_deductible_cents"]
             + payment["alloc_commission_cents"]
             + payment["alloc_carrier_cents"])
    assert total == payment["amount_cents"], (
        f"Allocation buckets must sum to amount_cents {payment['amount_cents']}, got {total}"
    )


def assert_deductible_reimbursement(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["recovery_payment_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "DISBURSED", "CLAWED_BACK")


def assert_commission_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["lines"], list)
    assert isinstance(data["total_commission_cents"], int)
    assert data["status"] in ("OPEN", "FINALIZED", "VOID")


def assert_claim_document(data: dict):
    """PRD §2.4 — append-only: carries id + created_at, no version/updated_at."""
    _assert_common(data)
    assert "version" not in data, "ClaimDocument must not carry a version field"
    assert "updated_at" not in data, "ClaimDocument must not carry an updated_at field"
    assert isinstance(data["claim_id"], str)
    assert data["doc_type"] in ("POLICE_REPORT", "ESTIMATE", "POLICY", "CORRESPONDENCE", "OTHER")
