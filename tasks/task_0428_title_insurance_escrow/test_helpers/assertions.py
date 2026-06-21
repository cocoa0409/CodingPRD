"""Entity assertions and domain invariant checkers for the Title Insurance Escrow API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_triple(data: dict):
    """Every entity except TitlePlantRecord carries id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_agency(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["remit_split_pct"], (int, float))
    assert 0 <= data["remit_split_pct"] <= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_plant_record(data: dict):
    """TitlePlantRecord is immutable reference data: id + created_at only,
    no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TitlePlantRecord must NOT carry updated_at"
    assert "version" not in data, "TitlePlantRecord must NOT carry version"
    assert data["instrument_type"] in ("DEED", "MORTGAGE", "LIEN", "EASEMENT", "RELEASE")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_order(data: dict):
    _assert_audit_triple(data)
    assert data["status"] in (
        "OPENED", "IN_TITLE", "COMMITTED", "CLEAR_TO_CLOSE", "CLOSED", "CANCELLED",
    )
    assert data["transaction_type"] in ("PURCHASE", "REFINANCE", "REISSUE")
    assert isinstance(data["sales_price_cents"], int) and data["sales_price_cents"] >= 0
    assert isinstance(data["loan_amount_cents"], int) and data["loan_amount_cents"] >= 0
    assert isinstance(data["escrow_deposit_total_cents"], int)
    assert isinstance(data["escrow_disbursed_total_cents"], int)
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["gap_open"], bool)
    assert_escrow_invariants(data)


def assert_escrow_invariants(data: dict):
    """The trust ledger identity: balance == deposit_total - disbursed_total (PRD §3.7)."""
    assert (
        data["escrow_balance_cents"]
        == data["escrow_deposit_total_cents"] - data["escrow_disbursed_total_cents"]
    ), "escrow_balance_cents must equal deposit_total - disbursed_total"


def assert_title_search(data: dict):
    _assert_audit_triple(data)
    assert data["status"] in ("ORDERED", "IN_EXAM", "COMPLETED", "CANCELLED")
    assert isinstance(data["chain_verified"], bool)


def assert_commitment(data: dict):
    _assert_audit_triple(data)
    assert data["status"] in ("DRAFT", "ISSUED", "UPDATED", "EXPIRED", "CANCELLED")
    assert data["schedule_a_estate"] in ("FEE_SIMPLE", "LEASEHOLD")
    assert isinstance(data["insured_amount_cents"], int) and data["insured_amount_cents"] > 0
    assert isinstance(data["open_exception_count"], int) and data["open_exception_count"] >= 0
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 0


def assert_exception(data: dict):
    _assert_audit_triple(data)
    assert data["exception_type"] in ("STANDARD", "SPECIAL", "SUBORDINATE_LIEN")
    assert isinstance(data["curative_required"], bool)
    assert data["status"] in ("RAISED", "CURATIVE_PENDING", "WAIVED", "CLEARED", "VOID")


def assert_policy(data: dict):
    _assert_audit_triple(data)
    assert data["policy_type"] in ("OWNER", "LENDER")
    assert isinstance(data["coverage_amount_cents"], int) and data["coverage_amount_cents"] > 0
    assert data["status"] in ("PENDING", "ISSUED", "VOID")


def assert_endorsement(data: dict):
    _assert_audit_triple(data)
    assert data["form_code"] in ("ENV_PROTECTION", "ZONING", "SURVEY", "RESTRICTIONS")
    assert data["status"] in ("REQUESTED", "ATTACHED", "REMOVED")


def assert_deposit(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("RECEIVED", "POSTED", "REVERSED")


def assert_disbursement(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["purpose"] in (
        "SELLER_PROCEEDS", "PAYOFF", "PREMIUM", "RECORDING_FEE", "CLAIM_PAYOUT",
    )
    assert data["status"] in ("REQUESTED", "APPROVED", "WIRED", "VOID")


def assert_remittance(data: dict):
    _assert_audit_triple(data)
    assert data["status"] in ("PENDING", "REMITTED", "REVERSED")


def assert_premium_split_conserves(data: dict):
    """PRD §3.8: agency_retained_cents + underwriter_remit_cents == gross_premium_cents,
    with zero drift (agency share rounded first, underwriter share by subtraction)."""
    assert (
        data["agency_retained_cents"] + data["underwriter_remit_cents"]
        == data["gross_premium_cents"]
    ), "premium split must conserve gross with zero drift"


def assert_claim(data: dict):
    _assert_audit_triple(data)
    assert data["claim_type"] in (
        "UNDISCLOSED_LIEN", "BOUNDARY_DISPUTE", "FORGERY", "ACCESS_DEFECT",
    )
    assert data["status"] in ("FNOL", "INVESTIGATING", "CURATIVE", "PAID", "DENIED")
    assert isinstance(data["reserve_cents"], int) and data["reserve_cents"] >= 0


def assert_curative_action(data: dict):
    _assert_audit_triple(data)
    assert data["subject_type"] in ("EXCEPTION", "CLAIM")
    assert data["action_type"] in ("PAYOFF", "RELEASE_FILED", "QUIET_TITLE", "INDEMNITY")
    assert data["status"] in ("OPEN", "RESOLVED", "ABANDONED")
