"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_intended_parent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["intake_status"] in ["DRAFT", "SUBMITTED", "SCREENING", "CLEARED", "REJECTED"]
    assert data["psych_clearance"] in ["PENDING", "PASSED", "FAILED"]
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 0


def assert_carrier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["intake_status"] in ["DRAFT", "SUBMITTED", "SCREENING", "CLEARED", "REJECTED"]
    assert data["psych_clearance"] in ["PENDING", "PASSED", "FAILED"]
    assert isinstance(data["prior_deliveries"], int) and data["prior_deliveries"] >= 0
    assert isinstance(data["base_compensation_cents"], int) and data["base_compensation_cents"] >= 0


def assert_egg_donor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["donor_code"], str)
    assert data["intake_status"] in ["DRAFT", "SUBMITTED", "SCREENING", "CLEARED", "REJECTED"]
    assert isinstance(data["donor_compensation_cents"], int) and data["donor_compensation_cents"] >= 0


def assert_match(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["intended_parent_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert data["status"] in ["PROPOSED", "COUNTERED", "ACCEPTED", "PSYCH_CLEARED", "VOID"]
    assert isinstance(data["offer_round"], int) and data["offer_round"] >= 0
    assert isinstance(data["proposed_carrier_comp_cents"], int)


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["match_id"])
    assert data["status"] in ["DRAFTED", "IP_SIGNED", "EXECUTED", "VOID"]
    assert isinstance(data["cooling_off_days"], int)


def assert_escrow_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["journey_id"])
    assert data["status"] in ["OPEN", "FROZEN", "CLOSED"]
    for f in ("deposited_cents", "disbursed_cents", "reserved_cents", "available_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert_escrow_invariants(data)


def assert_escrow_invariants(data: dict):
    """PRD §2.9: available = deposited - disbursed - reserved, never negative."""
    expected = data["deposited_cents"] - data["disbursed_cents"] - data["reserved_cents"]
    assert data["available_cents"] == expected, (
        f"available_cents {data['available_cents']} != deposited - disbursed - reserved "
        f"({data['deposited_cents']} - {data['disbursed_cents']} - {data['reserved_cents']} = {expected})"
    )
    assert data["available_cents"] >= 0, "available_cents must never go negative"


def assert_journey(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["match_id"])
    assert data["status"] in ["ACTIVE", "ON_HOLD", "COMPLETED", "TERMINATED"]
    assert data["current_phase"] in ["PRE_TRANSFER", "TRANSFERRED", "HEARTBEAT_CONFIRMED", "BORN"]
    assert data["parentage_order_status"] in ["NOT_FILED", "FILED", "GRANTED", "DENIED"]


def assert_milestone(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["journey_id"])
    assert data["milestone_type"] in ["EMBRYO_TRANSFER", "HEARTBEAT", "BIRTH"]
    assert data["status"] in ["SCHEDULED", "ACHIEVED", "FAILED"]


def assert_comp_schedule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["journey_id"])
    assert data["trigger_milestone_type"] in ["EMBRYO_TRANSFER", "HEARTBEAT", "BIRTH"]
    assert data["recipient"] in ["CARRIER", "DONOR"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_disbursement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["journey_id"])
    assert data["status"] in ["REQUESTED", "APPROVED", "RELEASED", "REJECTED"]
    assert isinstance(data["amount_cents"], int)


def assert_insurance_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["carrier_id"])
    assert data["policy_kind"] in ["SURROGACY_FRIENDLY", "EXCLUSION", "NONE"]
    assert data["status"] in ["PENDING", "APPROVED", "GAP_IDENTIFIED", "REJECTED"]
    assert isinstance(data["gap_premium_cents"], int)
