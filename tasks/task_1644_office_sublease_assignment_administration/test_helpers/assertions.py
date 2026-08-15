"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PARTY_KINDS = {"LANDLORD", "TENANT", "SUBTENANT", "ASSIGNEE"}
TRANSFER_STATUSES = {
    "DRAFT", "SUBMITTED", "CONSENT_PENDING", "CONSENT_GRANTED", "CONSENT_DENIED",
    "DEEMED_APPROVED", "DOCUMENTED", "EFFECTIVE", "WITHDRAWN", "RESCINDED",
}
CONSENT_DECISIONS = {
    "PENDING", "GRANTED", "GRANTED_WITH_CONDITIONS", "DENIED", "RESCINDED",
}
CONDITION_STATUSES = {"PENDING", "ACCEPTED", "REJECTED"}
CREDIT_OUTCOMES = {"PENDING", "PASS", "FAIL"}
MEASUREMENT_STATUSES = {"DRAFT", "CERTIFIED", "SUPERSEDED"}
MEASUREMENT_STANDARDS = {"METHOD_A", "METHOD_B"}
INSTRUMENT_STATUSES = {"EXECUTED", "RECOGNIZED", "TERMINATED"}
RECOGNITION_STATUSES = {"DRAFTED", "PARTIALLY_SIGNED", "FULLY_EXECUTED", "VOIDED"}
SETTLEMENT_STATUSES = {"DRAFT", "FINALIZED", "VOID"}
RESTORATION_STATUSES = {"OPEN", "ESCROW_POSTED", "COMPLETED", "WAIVED"}


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an int"


def assert_party(data: dict):
    _assert_common(data, "Party")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["party_kind"] in PARTY_KINDS
    assert isinstance(data["credit_rating_bps"], int)
    assert 0 <= data["credit_rating_bps"] <= 10000


def assert_building(data: dict):
    _assert_common(data, "Building")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["total_rentable_sf"], int) and data["total_rentable_sf"] > 0
    assert isinstance(data["loss_factor_bps"], int)
    assert 0 <= data["loss_factor_bps"] <= 5000


def assert_lease(data: dict):
    _assert_common(data, "Lease")
    assert is_valid_uuid(data["building_id"])
    assert is_valid_uuid(data["tenant_party_id"])
    assert is_valid_uuid(data["landlord_party_id"])
    assert data["status"] == "ACTIVE"
    assert isinstance(data["open_transfer_count"], int) and data["open_transfer_count"] >= 0
    assert isinstance(data["cumulative_profit_share_cents"], int)
    assert data["cumulative_profit_share_cents"] >= 0


def assert_transfer(data: dict):
    _assert_common(data, "TransferRequest")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["counterparty_id"])
    assert data["transfer_type"] in ("SUBLEASE", "ASSIGNMENT")
    assert data["status"] in TRANSFER_STATUSES
    assert isinstance(data["proposed_rent_per_rsf_annual_cents"], int)
    assert data["proposed_rent_per_rsf_annual_cents"] > 0
    assert isinstance(data["marketing_period_days"], int)
    assert isinstance(data["broker_user_id"], str) and data["broker_user_id"]


def assert_demised_area(data: dict):
    _assert_common(data, "DemisedArea")
    assert data["measurement_standard"] in MEASUREMENT_STANDARDS
    assert isinstance(data["usable_sf"], int) and data["usable_sf"] > 0
    assert isinstance(data["rentable_sf"], int) and data["rentable_sf"] > 0
    assert isinstance(data["prorata_share_bps"], int)
    assert isinstance(data["is_partial_floor"], bool)
    assert data["status"] in MEASUREMENT_STATUSES


def assert_consent_review(data: dict):
    _assert_common(data, "ConsentReview")
    assert is_valid_uuid(data["transfer_request_id"])
    assert data["decision"] in CONSENT_DECISIONS
    assert isinstance(data["conditions_imposed_count"], int)
    assert data["conditions_imposed_count"] >= 0


def assert_consent_condition(data: dict):
    _assert_common(data, "ConsentCondition")
    assert is_valid_uuid(data["consent_review_id"])
    assert data["condition_kind"] in (
        "RESTORATION_REQUIRED", "ADDITIONAL_SECURITY",
        "RENT_RESET_TO_MARKET", "RECAPTURE_RIGHT",
    )
    assert data["status"] in CONDITION_STATUSES


def assert_credit_review(data: dict):
    _assert_common(data, "CreditReview")
    assert is_valid_uuid(data["transfer_request_id"])
    assert data["outcome"] in CREDIT_OUTCOMES
    assert data["minimum_pass_bps"] == 6000


def assert_sublease_agreement(data: dict):
    _assert_common(data, "SubleaseAgreement")
    assert is_valid_uuid(data["transfer_request_id"])
    assert is_valid_uuid(data["demised_area_id"])
    assert data["status"] in INSTRUMENT_STATUSES
    assert isinstance(data["executed_rent_per_rsf_annual_cents"], int)


def assert_recognition_agreement(data: dict):
    _assert_common(data, "RecognitionAgreement")
    assert is_valid_uuid(data["transfer_request_id"])
    assert data["status"] in RECOGNITION_STATUSES


def assert_settlement(data: dict):
    _assert_common(data, "Settlement")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["transfer_request_id"])
    assert data["status"] in SETTLEMENT_STATUSES
    assert isinstance(data["subrent_collected_cents"], int)
    assert data["subrent_collected_cents"] >= 0
    for field in (
        "passthrough_rent_cents", "net_profit_cents",
        "landlord_share_cents", "tenant_share_cents",
    ):
        assert isinstance(data[field], int), f"Settlement.{field} must be int cents"
    assert data["net_profit_cents"] >= 0


def assert_restoration_obligation(data: dict):
    _assert_common(data, "RestorationObligation")
    assert is_valid_uuid(data["transfer_request_id"])
    assert data["responsible_party"] in ("TENANT", "SUBTENANT_OR_ASSIGNEE", "SHARED")
    assert isinstance(data["escrow_amount_cents"], int)
    assert data["escrow_amount_cents"] >= 0
    assert data["status"] in RESTORATION_STATUSES


def assert_lease_ledger_invariants(lease: dict):
    """Domain invariants that must hold for the lease ledger at all times."""
    assert lease["open_transfer_count"] >= 0
    assert lease["cumulative_profit_share_cents"] >= 0
    assert isinstance(lease["version"], int)
