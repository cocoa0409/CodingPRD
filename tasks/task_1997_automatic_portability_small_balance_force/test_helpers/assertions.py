"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be int"


def assert_recordkeeper(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["recordkeeper_code"], str)
    assert isinstance(data["legal_name"], str)
    assert data["network_status"] in [
        "PENDING_ONBOARD", "ACTIVE", "SUSPENDED", "EXITED",
    ]


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_name"], str)
    assert isinstance(data["sponsor_ein"], str)
    assert isinstance(data["recordkeeper_id"], str)
    assert isinstance(data["cash_out_threshold_cents"], int)
    assert isinstance(data["rollover_threshold_cents"], int)
    assert isinstance(data["state_withholding_rate"], (int, float))
    assert data["valuation_basis"] in ["SEPARATION_DATE", "PROCESSING_DATE"]
    assert isinstance(data["auto_portability_enabled"], bool)
    assert isinstance(data["accepts_incoming_transfers"], bool)
    assert isinstance(data["network_reachable"], bool)
    assert data["plan_status"] in ["ACTIVE", "TERMINATED"]


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ssn_hash"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert data["address_quality"] in ["UNVERIFIED", "VALID", "BAD_ADDRESS"]


def assert_distribution_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert data["batch_status"] in [
        "OPEN", "LOCKED", "EXECUTED", "RECON_EXCEPTION", "RECONCILED", "REVIEWED",
    ]
    assert isinstance(data["case_count"], int)
    assert isinstance(data["settled_case_count"], int)
    assert isinstance(data["total_forced_out_cents"], int)


def assert_distribution_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["distribution_batch_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["separation_date_balance_cents"], int)
    assert isinstance(data["processing_date_balance_cents"], int)
    assert isinstance(data["vesting_percent"], int)
    assert data["case_status"] in [
        "IDENTIFIED", "NOTIFIED", "ELECTED", "WINDOW_EXPIRED",
        "EXECUTED", "SETTLED", "ESCHEATED", "CANCELLED",
    ]


def assert_notice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["distribution_case_id"], str)
    assert data["notice_type"] in [
        "FORCE_OUT_ELECTION", "FEE_DISCLOSURE",
        "AUTO_PORTABILITY_PRENOTICE", "ESCHEAT_WARNING",
    ]
    assert data["delivery_status"] in ["SENT", "DELIVERED", "BOUNCED", "RETURNED_MAIL"]
    assert is_iso8601_timestamp(data["sent_at"])


def assert_election(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["distribution_case_id"], str)
    assert isinstance(data["participant_id"], str)
    assert data["election_type"] in [
        "LUMP_SUM_CASH", "SAFE_HARBOR_IRA", "DIRECT_ROLLOVER_NEW_PLAN",
    ]
    assert data["election_status"] in ["SUBMITTED", "SUPERSEDED", "EXECUTED", "VOIDED"]


def assert_safe_harbor_ira(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["distribution_case_id"], str)
    assert isinstance(data["participant_id"], str)
    assert data["ira_origin"] in ["AUTO_FORCE_OUT", "ELECTED"]
    assert data["ira_status"] in [
        "OPEN", "MATCHED", "TRANSFER_PENDING",
        "TRANSFERRED_OUT", "CLOSED_BY_PARTICIPANT", "ESCHEATED",
    ]
    assert isinstance(data["funded_amount_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["in_flight_cents"], int)
    assert isinstance(data["total_fees_cents"], int)
    assert isinstance(data["total_transferred_out_cents"], int)
    assert data["fee_day_count_convention"] in ["ACTUAL_365", "THIRTY_360"]
    assert data["default_investment"] == "MONEY_MARKET_FDIC_INSURED"


def assert_ira_fee_assessment(data: dict):
    # Append-only ledger entry: id + created_at, NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "IRAFeeAssessment must not carry updated_at"
    assert "version" not in data, "IRAFeeAssessment must not carry version"
    assert isinstance(data["safe_harbor_ira_id"], str)
    assert isinstance(data["days_in_period"], int)
    assert data["day_count_convention"] in ["ACTUAL_365", "THIRTY_360"]
    assert isinstance(data["amount_cents"], int)


def assert_check(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["distribution_case_id"], str)
    assert data["origin"] in ["CASE_CASH_OUT", "IRA_CLOSE"]
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["fed_withholding_cents"], int)
    assert isinstance(data["state_withholding_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["check_status"] in ["ISSUED", "CASHED", "STALE_DATED", "VOIDED"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["stale_after"])


def assert_match_candidate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["safe_harbor_ira_id"], str)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["new_plan_id"], str)
    assert isinstance(data["new_recordkeeper_id"], str)
    assert isinstance(data["ssn_exact"], bool)
    assert isinstance(data["name_similarity"], (int, float))
    assert isinstance(data["dob_match"], bool)
    assert data["match_status"] in [
        "CANDIDATE", "CONFIRMED", "REJECTED", "EXPIRED", "EXECUTED",
    ]


def assert_transfer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["safe_harbor_ira_id"], str)
    assert isinstance(data["match_candidate_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["accrued_fee_offset_cents"], int)
    assert data["transfer_status"] in ["SENT", "RECONCILED", "RETURNED"]


def assert_fiduciary_review(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["distribution_batch_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["reviewer_user_id"], str)
    assert data["review_status"] in ["OPEN", "REMEDIATION_OPEN", "CLOSED"]
    assert isinstance(data["findings_count"], int)


def assert_ira_money_conservation(ira: dict):
    """PRD §3.6 invariant: balance_cents == funded - fees - transferred - in_flight."""
    expected = (
        ira["funded_amount_cents"]
        - ira["total_fees_cents"]
        - ira["total_transferred_out_cents"]
        - ira["in_flight_cents"]
    )
    assert ira["balance_cents"] == expected, (
        f"IRA money conservation violated: balance {ira['balance_cents']} != "
        f"funded {ira['funded_amount_cents']} - fees {ira['total_fees_cents']} "
        f"- transferred {ira['total_transferred_out_cents']} - in_flight {ira['in_flight_cents']}"
    )
