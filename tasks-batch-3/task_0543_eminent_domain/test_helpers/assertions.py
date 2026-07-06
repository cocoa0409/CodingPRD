"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_project(data: dict):
    _assert_common(data)
    for f in ("committed_cents", "disbursed_cents", "acquired_area_sqft",
              "available_cents", "total_budget_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["available_cents"] == (
        data["total_budget_cents"] - data["committed_cents"] - data["disbursed_cents"]
    ), "available_cents must equal total - committed - disbursed"


def assert_parcel(data: dict):
    _assert_common(data)
    assert data["research_status"] in ("RESEARCHING", "OWNERSHIP_CLEARED")
    assert data["acquisition_status"] in (
        "PENDING", "IN_NEGOTIATION", "AGREED", "IN_CONDEMNATION", "POSSESSED", "ACQUIRED")
    assert data["take_type"] in ("FULL", "PARTIAL")
    assert data["take_area_sqft"] <= data["total_area_sqft"]
    assert isinstance(data["appraised_value_cents"], int)


def assert_ownership_interest(data: dict):
    _assert_common(data)
    assert data["interest_type"] in (
        "FEE_OWNER", "LIENHOLDER", "TENANT", "EASEMENT_HOLDER")
    assert isinstance(data["is_occupant"], bool)


def assert_appraisal(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")
    assert isinstance(data["just_compensation_cents"], int)
    assert isinstance(data["condemnation_basis_cents"], int)


def assert_negotiation(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "AGENCY_OFFERED", "OWNER_COUNTERED", "AGREED", "IMPASSE")
    assert isinstance(data["round_count"], int)
    assert isinstance(data["current_amount_cents"], int)


def assert_offer_round(data: dict):
    """OfferRound is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "OfferRound must not expose a version field"
    assert "updated_at" not in data, "OfferRound must not expose an updated_at field"
    assert data["party"] in ("AGENCY", "OWNER")
    assert data["action"] in ("OFFER", "COUNTER", "ACCEPT", "REJECT")


def assert_relocation_benefit(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "PAID")
    assert data["occupant_type"] in ("RESIDENTIAL", "BUSINESS")
    assert isinstance(data["benefit_amount_cents"], int)


def assert_condemnation(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "DEPOSIT_MADE", "POSSESSED", "AWARDED")
    assert isinstance(data["just_compensation_snapshot_cents"], int)


def assert_utility_relocation(data: dict):
    _assert_common(data)
    assert data["status"] in ("IDENTIFIED", "SCHEDULED", "RELOCATED")
    assert isinstance(data["possession_cleared"], bool)


def assert_escrow(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPENED", "FUNDED", "CLOSED", "CANCELLED")
    assert isinstance(data["agreed_amount_cents"], int)


def assert_disbursements_conserve(escrow: dict):
    """The waterfall payout sums exactly to agreed_amount_cents (PRD §3.8)."""
    total = sum(d["amount_cents"] for d in escrow["disbursements"])
    assert total == escrow["agreed_amount_cents"], (
        f"disbursements sum {total} must equal agreed_amount_cents "
        f"{escrow['agreed_amount_cents']}")
