"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract. Append-only
artifacts (EscrowTransaction, TaxRecord) are checked to carry only id + created_at among
the common fields — they must NOT expose updated_at or version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_COMMON_VERSIONED = ("id", "created_at", "updated_at", "version")


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["wallet_balance_cents"], int)
    assert data["wallet_balance_cents"] >= 0, "wallet_balance_cents may never go negative"
    assert isinstance(data["escrow_held_cents"], int)
    assert isinstance(data["lifetime_funded_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_freelancer(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["skills"], list)
    assert isinstance(data["tax_id_on_file"], bool)
    assert isinstance(data["lifetime_earnings_cents"], int)
    assert isinstance(data["lifetime_gross_billed_cents"], int)
    assert isinstance(data["completed_contract_count"], int)
    assert isinstance(data["dispute_loss_count"], int)
    assert isinstance(data["reputation_score"], (int, float))
    assert 0 <= data["reputation_score"] <= 100, "reputation_score is on a 0..100 scale"
    assert data["fee_tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_job_posting(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert isinstance(data["title"], str)
    assert data["billing_type"] in ("FIXED", "HOURLY")
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["required_skills"], list)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "AWARDED", "CLOSED", "CANCELLED")
    assert isinstance(data["proposal_count"], int)


def assert_proposal(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data.get("job_posting_id", ""))
    assert is_valid_uuid(data.get("freelancer_id", ""))
    assert isinstance(data["bid_amount_cents"], int)
    assert isinstance(data["round_count"], int)
    assert data["last_actor"] in ("FREELANCER", "CLIENT")
    assert data["status"] in ("SUBMITTED", "COUNTERED", "ACCEPTED", "DECLINED", "WITHDRAWN")


def assert_contract(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("freelancer_id", ""))
    assert data["billing_type"] in ("FIXED", "HOURLY")
    assert isinstance(data["agreed_amount_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED", "COMPLETED")
    assert isinstance(data["total_released_cents"], int)
    assert isinstance(data["total_refunded_cents"], int)
    assert isinstance(data["open_milestone_count"], int)
    assert isinstance(data["open_dispute_count"], int)


def assert_milestone(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["funded_cents"], int)
    assert isinstance(data["released_gross_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["ordinal"], int)
    assert data["status"] in (
        "DRAFT", "FUNDED", "SUBMITTED", "APPROVED", "DISPUTED",
        "RELEASED", "REFUNDED", "CANCELLED",
    )


def assert_timelog(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("milestone_id", ""))
    assert isinstance(data["work_date"], str)
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert isinstance(data["billable_minutes"], int)
    assert data["billable_minutes"] == data["end_minute"] - data["start_minute"]
    assert data["status"] in ("LOGGED", "VERIFIED", "REJECTED")


def assert_dispute(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("milestone_id", ""))
    assert data["raised_by"] in ("CLIENT", "FREELANCER")
    assert data["status"] in ("OPEN", "UNDER_ARBITRATION", "RESOLVED", "WITHDRAWN")


def assert_payout(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data.get("freelancer_id", ""))
    assert is_valid_uuid(data.get("milestone_id", ""))
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["platform_fee_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["net_cents"] == data["gross_cents"] - data["platform_fee_cents"]
    assert isinstance(data["tax_year"], int)
    assert data["status"] in ("PENDING", "PAID", "HELD_NO_TAX_ID")


def assert_review(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["author_role"] in ("CLIENT", "FREELANCER")
    assert 1 <= data["rating"] <= 5


def assert_escrow_transaction(data: dict):
    """Append-only ledger row: only id + created_at among common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "EscrowTransaction must not expose updated_at"
    assert "version" not in data, "EscrowTransaction must not expose version"
    assert data["txn_type"] in ("FUND", "RELEASE", "REFUND")
    assert data["status"] in ("HELD", "SETTLED", "REVERSED")
    assert isinstance(data["amount_cents"], int)


def assert_tax_record(data: dict):
    """Generated artifact: only id + created_at among common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TaxRecord must not expose updated_at"
    assert "version" not in data, "TaxRecord must not expose version"
    assert is_valid_uuid(data.get("freelancer_id", ""))
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["reportable_gross_cents"], int)
    assert isinstance(data["is_reportable"], bool)
    assert data["form_status"] in ("BELOW_THRESHOLD", "GENERATED")


def assert_escrow_conserved(milestone: dict, fund_total: int):
    """PRD §2.9 conservation law for a single milestone:
    sum(all FUND amounts) == released_gross + refunded + held(funded_cents).
    Pass the known total of FUND amounts for the milestone."""
    held = milestone["funded_cents"]
    released = milestone["released_gross_cents"]
    refunded = milestone["refunded_cents"]
    assert fund_total == released + refunded + held, (
        f"escrow not conserved: FUND total {fund_total} != "
        f"released {released} + refunded {refunded} + held {held}"
    )
