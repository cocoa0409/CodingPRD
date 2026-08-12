"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_resource(data: dict):
    """Standard system-managed fields every resource carries (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_circle(data: dict):
    assert_common_resource(data)
    assert data["vetting_profile"] in ("BALANCED", "EQUITY_FIRST")
    assert isinstance(data["active_member_count"], int)
    assert isinstance(data["renewed_member_count"], int)


def assert_cycle(data: dict):
    assert_common_resource(data)
    assert data["phase"] in (
        "DRAFT",
        "RECRUITMENT",
        "POOLING",
        "NOMINATION",
        "VETTING",
        "VOTING",
        "AWARD",
        "REPORTING",
        "CLOSED",
    )


def assert_member(data: dict):
    assert_common_resource(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_membership(data: dict):
    assert_common_resource(data)
    assert data["status"] in (
        "INVITED",
        "ACTIVE",
        "RENEWAL_DUE",
        "LAPSED",
        "WITHDRAWN",
    )
    assert data["tier"] in ("STANDARD", "LEADER")
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["credit_balance_cents"], int)


def assert_contribution(data: dict):
    assert_common_resource(data)
    assert data["status"] in (
        "PLEDGED",
        "RECEIVED",
        "REFUND_REQUESTED",
        "REFUNDED",
        "VOIDED",
    )
    assert isinstance(data["amount_cents"], int)


def assert_nonprofit(data: dict):
    assert_common_resource(data)
    assert data["standing"] in ("GOOD", "SUSPENDED")
    assert isinstance(data["ein"], str) and data["ein"]


def assert_nomination(data: dict):
    assert_common_resource(data)
    assert data["status"] in (
        "SUBMITTED",
        "VETTING",
        "NEEDS_INFO",
        "FINALIST",
        "AWARDED",
        "NOT_SELECTED",
        "REJECTED",
        "WITHDRAWN",
    )
    assert isinstance(data["info_rounds_used"], int)


def assert_site_visit(data: dict):
    assert_common_resource(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_learning_session(data: dict):
    assert_common_resource(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["seats_taken"], int)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["rsvp_membership_ids"], list)


def assert_ballot(data: dict):
    assert_common_resource(data)
    assert data["status"] == "CAST"
    assert isinstance(data["allocations"], list)


def assert_award(data: dict):
    assert_common_resource(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["winner_points"], int)
    assert data["payout_status"] in ("UNPAID", "PARTIALLY_PAID", "PAID")
    assert data["reporting_status"] in ("AWAITING_REPORTS", "REPORTS_COMPLETE")


def assert_payout(data: dict):
    assert_common_resource(data)
    assert data["status"] in ("SCHEDULED", "APPROVED", "RELEASED", "FAILED")
    assert data["tranche"] in (1, 2)
    assert isinstance(data["amount_cents"], int)


def assert_report(data: dict):
    assert_common_resource(data)
    assert data["report_type"] in ("INTERIM", "FINAL")
    assert data["status"] in ("DUE", "OVERDUE", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_rollover_decision(data: dict):
    assert_common_resource(data)
    assert data["mode"] in ("CARRY_FORWARD", "RETURN_PRO_RATA")
    assert data["status"] in ("PROPOSED", "APPROVED", "EXECUTED")


def assert_ledger(data: dict):
    """The ledger read returns exactly these ten figures (PRD §2.6)."""
    for key in (
        "received_total_cents",
        "pledged_outstanding_cents",
        "refunded_total_cents",
        "released_total_cents",
        "admin_fee_transferred_cents",
        "rollover_in_cents",
        "rollover_out_cents",
        "pooled_balance_cents",
        "grant_budget_provisional_cents",
        "grant_budget_final_cents",
    ):
        assert isinstance(data.get(key), int), f"ledger.{key} must be an integer"


def assert_tally(data: dict):
    """The tally read exposes these computed fields (PRD §3.6)."""
    assert isinstance(data.get("ballots_cast_count"), int)
    assert isinstance(data.get("quorum_required"), int)
    assert isinstance(data.get("quorum_met"), bool)
    assert isinstance(data.get("finalist_points"), list)
    assert isinstance(data.get("total_points_cast"), int)
