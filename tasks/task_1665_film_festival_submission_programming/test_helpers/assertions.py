"""Entity assertions and domain invariant checkers (PRD §2.2, §2.6, §2.8)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp (accepting a trailing Z) for comparison."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_edition(data: dict):
    _assert_common(data, "FestivalEdition")
    assert isinstance(data["year"], int)
    assert data["status"] in [
        "SETUP", "INTAKE_OPEN", "INTAKE_CLOSED", "SCREENING", "DELIBERATION",
        "SLATE_LOCKED", "NOTIFICATION", "SCHEDULING", "FESTIVAL_LIVE",
        "AWARDS_NIGHT", "CLOSED",
    ]
    for f in (
        "total_fees_collected_cents", "total_refunded_cents",
        "hotel_nights_allocated", "hotel_nights_remaining",
        "travel_committed_cents", "travel_penalty_sink_cents",
        "travel_budget_remaining", "prize_committed_cents",
        "prize_disbursed_cents",
    ):
        assert isinstance(data[f], int), f"FestivalEdition.{f} must be int"


def assert_category_config(data: dict):
    _assert_common(data, "CategoryConfig")
    assert data["category"] in [
        "NARRATIVE_FEATURE", "DOCUMENTARY_FEATURE", "SHORT_FILM", "EPISODIC",
    ]


def assert_submitter(data: dict):
    _assert_common(data, "Submitter")
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_programmer(data: dict):
    _assert_common(data, "Programmer")
    assert data["seniority"] in ["STAFF", "SENIOR", "LEAD"]
    assert isinstance(data["active"], bool)
    assert isinstance(data["active_assignment_count"], int)


def assert_submission(data: dict):
    _assert_common(data, "Submission")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "NEEDS_INFO", "ELIGIBLE", "IN_SCREENING",
        "ADVANCED", "INVITED", "WAITLISTED", "CONFIRMED", "PROGRAMMED",
        "INELIGIBLE", "DECLINED", "DECLINED_BY_FILMMAKER", "EXPIRED", "WITHDRAWN",
    ]
    assert data["payment_status"] in [
        "UNPAID", "PAID", "PARTIALLY_REFUNDED", "REFUNDED",
    ]


def assert_fee_payment(data: dict):
    _assert_common(data, "FeePayment")
    assert data["status"] in [
        "INITIATED", "SUCCEEDED", "FAILED", "PARTIALLY_REFUNDED", "REFUNDED",
    ]
    assert isinstance(data["amount_cents"], int)


def assert_assignment(data: dict):
    _assert_common(data, "ScreenerAssignment")
    assert data["status"] in ["ASSIGNED", "SCORED", "RECUSED", "EXPIRED"]


def assert_score(data: dict):
    _assert_common(data, "Score")
    for f in ("originality", "craft", "story", "overall"):
        assert 1 <= data[f] <= 10, f"Score.{f} must be within 1..10"


def assert_slate(data: dict):
    _assert_common(data, "Slate")
    assert data["status"] in ["OPEN", "DELIBERATING", "LOCKED"]
    assert isinstance(data["entry_count"], int)


def assert_slate_entry(data: dict):
    _assert_common(data, "SlateEntry")
    assert data["status"] in [
        "NOMINATED", "INVITED", "CONFIRMED", "PROGRAMMED", "DECLINED",
        "EXPIRED", "DROPPED", "RELEASED",
    ]
    assert data["lane"] in ["UNASSIGNED", "MAIN", "WAITLIST"]


def assert_venue(data: dict):
    _assert_common(data, "Venue")
    assert isinstance(data["formats_supported"], list)


def assert_slot(data: dict):
    _assert_common(data, "ScreeningSlot")
    assert data["status"] in ["OPEN", "HELD", "CONFIRMED", "PLAYED", "CANCELLED"]
    assert data["slot_type"] in [
        "PREMIERE", "PUBLIC", "PRESS_INDUSTRY", "AWARDS_ENCORE",
    ]


def assert_travel_package(data: dict):
    _assert_common(data, "TravelPackage")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "BOOKED",
        "RECONCILED", "CANCELLED",
    ]


def assert_agreement(data: dict):
    _assert_common(data, "ExhibitionAgreement")
    assert data["status"] in ["DRAFT", "ISSUED", "SIGNED", "ACTIVE", "TERMINATED"]


def assert_juror(data: dict):
    _assert_common(data, "Juror")


def assert_award(data: dict):
    _assert_common(data, "Award")
    assert data["status"] in [
        "SETUP", "VOTING_OPEN", "TALLIED", "ANNOUNCED", "DISBURSED",
    ]


def assert_jury_vote(data: dict):
    """A ballot is immutable: id + created_at only, no updated_at/version (§2.6)."""
    assert is_valid_uuid(str(data.get("id", ""))), "JuryVote.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        "JuryVote.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "JuryVote must not carry updated_at"
    assert "version" not in data, "JuryVote must not carry version"


def assert_inv_hotel(edition: dict):
    """INV-HOTEL: allocated + remaining == pool (PRD §2.8)."""
    assert edition["hotel_nights_allocated"] + edition["hotel_nights_remaining"] == \
        edition["hotel_nights_pool"], (
            f"INV-HOTEL violated: {edition['hotel_nights_allocated']} + "
            f"{edition['hotel_nights_remaining']} != {edition['hotel_nights_pool']}"
        )


def assert_inv_travel(edition: dict):
    """INV-TRAVEL: remaining + committed + sink == budget (PRD §2.8)."""
    assert (
        edition["travel_budget_remaining"]
        + edition["travel_committed_cents"]
        + edition["travel_penalty_sink_cents"]
        == edition["travel_budget_cents"]
    ), (
        f"INV-TRAVEL violated: {edition['travel_budget_remaining']} + "
        f"{edition['travel_committed_cents']} + "
        f"{edition['travel_penalty_sink_cents']} != {edition['travel_budget_cents']}"
    )
