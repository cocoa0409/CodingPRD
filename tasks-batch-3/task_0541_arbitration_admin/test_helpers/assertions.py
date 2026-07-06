"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_case(data: dict):
    _common(data)
    assert data["case_type"] in ("ARBITRATION", "MEDIATION")
    assert data["status"] in (
        "FILED", "SELECTION", "APPOINTED", "HEARING",
        "AWARD_ISSUED", "CLOSED", "WITHDRAWN",
    )
    assert data["fee_tier"] in ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
    assert isinstance(data["claim_amount_cents"], int)
    assert data["panel_size"] in (1, 3)
    assert isinstance(data["filing_fee_cents"], int)
    assert isinstance(data["final_admin_fee_cents"], int)
    assert isinstance(data["deposit_balance_cents"], int)


def assert_party(data: dict):
    _common(data)
    assert data["role"] in ("CLAIMANT", "RESPONDENT")
    assert 0 <= data["share_pct"] <= 100
    assert isinstance(data["strikes_used"], int)
    assert isinstance(data["strikes_remaining"], int)


def assert_neutral(data: dict):
    _common(data)
    assert data["neutral_type"] in ("ARBITRATOR", "MEDIATOR", "BOTH")
    assert data["roster_status"] in ("ACTIVE", "SUSPENDED", "RETIRED")
    assert data["hourly_rate_cents"] > 0


def assert_candidate(data: dict):
    _common(data)
    assert data["status"] in (
        "PROPOSED", "DISCLOSED", "CLEARED", "OBJECTED",
        "DISQUALIFIED", "APPOINTED", "NOT_SELECTED",
    )
    assert isinstance(data["is_struck"], bool)
    assert isinstance(data["aggregate_rank_score"], int)


def assert_ranking(data: dict):
    _common(data)
    assert data["action"] in ("STRIKE", "RANK")
    assert data["status"] in ("ACTIVE", "WITHDRAWN")


def assert_hearing(data: dict):
    _common(data)
    assert data["hearing_type"] in ("PREHEARING", "EVIDENTIARY", "MEDIATION_SESSION")
    assert data["status"] in ("SCHEDULED", "HELD", "CANCELLED")


def assert_exchange(data: dict):
    _common(data)
    assert data["exchange_type"] in ("EXHIBITS", "WITNESS_LIST", "BRIEFS")
    assert data["status"] in ("PENDING", "SUBMITTED", "LATE")


def assert_deposit(data: dict):
    _common(data)
    assert data["status"] in ("REQUESTED", "PAID", "REFUNDED")
    assert data["amount_cents"] > 0


def assert_fee_charge(data: dict):
    _common(data)
    assert data["status"] in ("POSTED", "REVERSED")
    assert isinstance(data["amount_cents"], int)


def assert_award(data: dict):
    _common(data)
    assert data["award_type"] in ("MONETARY", "SETTLEMENT", "DISMISSAL")
    assert data["status"] in ("DRAFT", "ISSUED", "FINAL", "VACATED")


def assert_appeal(data: dict):
    _common(data)
    assert data["ground"] in ("EVIDENT_PARTIALITY", "EXCEEDED_POWERS", "PROCEDURAL")
    assert data["status"] in ("FILED", "UNDER_REVIEW", "GRANTED", "DENIED")
