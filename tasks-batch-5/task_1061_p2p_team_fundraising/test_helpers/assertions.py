"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Every resource carries a UUID id, both timestamps and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_organization(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ein"], str) and data["ein"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["payout_account_status"] in ("UNVERIFIED", "VERIFIED", "SUSPENDED")


def assert_campaign(data: dict):
    assert_common_fields(data)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["goal_amount_cents"], int) and data["goal_amount_cents"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "CLOSED")
    for field in (
        "raised_credited_cents",
        "lifetime_net_cents",
        "reserved_payout_cents",
        "paid_out_cents",
        "available_balance_cents",
        "donor_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_event(data: dict):
    assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["registered_count"], int) and data["registered_count"] >= 0
    assert data["status"] in ("OPEN", "FULL", "CLOSED")


def assert_team(data: dict):
    assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["goal_amount_cents"], int) and data["goal_amount_cents"] >= 1
    assert data["status"] in ("ACTIVE", "DISBANDED")
    assert isinstance(data["credited_cents"], int)
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0


def assert_participant(data: dict):
    assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["status"] in ("PENDING", "ACTIVE", "WITHDRAWN")
    assert isinstance(data["credited_cents"], int)
    assert isinstance(data["projected_cents"], int)
    assert isinstance(data["recruit_count"], int)
    assert isinstance(data["minimum_met"], bool)


def assert_registration(data: dict):
    assert_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["fee_charged_cents"], int)
    assert data["status"] in (
        "RESERVED",
        "CONFIRMED",
        "CHECKED_IN",
        "CANCELLED",
        "NO_SHOW",
    )


def assert_donor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["is_anonymous"], bool)


def assert_donation(data: dict):
    assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["donor_id"], str)
    assert data["designation_type"] in ("CAMPAIGN", "TEAM", "PARTICIPANT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 100
    for field in ("fee_cents", "net_cents", "charged_amount_cents", "matched_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["payment_status"] in ("PENDING", "SETTLED", "REFUNDED", "FAILED")
    assert data["match_status"] in ("UNMATCHED", "MATCHED", "NOT_ELIGIBLE", "REVERSED")


def assert_match_pool(data: dict):
    assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["pool_amount_cents"], int) and data["pool_amount_cents"] >= 1
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert data["remaining_cents"] >= 0, "remaining_cents never goes below zero"
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "CLOSED")


def assert_incentive_tier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["threshold_cents"], int) and data["threshold_cents"] >= 1
    assert isinstance(data["reward_description"], str)


def assert_incentive_award(data: dict):
    assert_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["tier_id"], str)
    assert data["status"] in ("EARNED", "FULFILLED", "REVOKED")


def assert_receipt(data: dict):
    assert_common_fields(data)
    assert isinstance(data["donation_id"], str)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["receipt_number"], str)
    assert isinstance(data["deductible_amount_cents"], int)
    assert data["deductible_amount_cents"] >= 0, "deductible amount is floored at 0"
    assert isinstance(data["tax_year"], int)
    assert data["status"] in ("ISSUED", "VOIDED")
    assert isinstance(data["reissue_count"], int)


def assert_payout(data: dict):
    assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in (
        "REQUESTED",
        "UNDER_REVIEW",
        "CHANGES_REQUESTED",
        "APPROVED",
        "REJECTED",
        "RELEASED",
        "VOIDED",
        "SUPERSEDED",
    )


# ---- Domain invariants ---------------------------------------------------


def assert_fund_conservation(campaign: dict):
    """available_balance + reserved_payout + paid_out == lifetime_net (PRD §2.10)."""
    total = (
        campaign["available_balance_cents"]
        + campaign["reserved_payout_cents"]
        + campaign["paid_out_cents"]
    )
    assert total == campaign["lifetime_net_cents"], (
        "Fund conservation identity broken: "
        f"{campaign['available_balance_cents']} + {campaign['reserved_payout_cents']} "
        f"+ {campaign['paid_out_cents']} != {campaign['lifetime_net_cents']}"
    )


def assert_pool_cents_conserved(pool: dict):
    """allocated_cents + remaining_cents == pool_amount_cents (PRD §2.11, §3.5)."""
    assert pool["allocated_cents"] + pool["remaining_cents"] == pool["pool_amount_cents"], (
        "Sponsor pool cents not conserved: "
        f"{pool['allocated_cents']} + {pool['remaining_cents']} "
        f"!= {pool['pool_amount_cents']}"
    )


def assert_receipt_number_format(receipt_number: str, sequence_value: int):
    """RCPT- followed by the counter left-padded with zeros to six digits."""
    expected = f"RCPT-{sequence_value:06d}"
    assert receipt_number == expected, (
        f"Expected receipt_number {expected}, got {receipt_number}"
    )
