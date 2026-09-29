"""The hearing continuance cycle and the two parallel state dimensions of a bid.

Both groups of tests build every row through the public API against an empty
database, driving the logical clock explicitly because every window and
occupancy comparison in the specification is evaluated against it.
"""
from datetime import datetime
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    make_vendor_headers,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _instant(value: Any) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the three-fractional-digit
    rendering the envelope uses as well as a whole-second rendering."""
    assert isinstance(value, str), "expected an ISO 8601 string, got {!r}".format(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_same_instant(actual: Any, expected: str, label: str) -> None:
    assert _instant(actual) == _instant(expected), "{}: expected {}, got {!r}".format(
        label, expected, actual
    )


def _setup_protest_with_hearing_on_docket() -> Dict[str, Any]:
    """A prospective bidder's solicitation-impropriety protest whose agency
    record holds two items and whose hearing sits on the docket in ROOM-A."""
    vendor = fx.create_vendor(
        legal_name="Delacroix Signage",
        tax_id="100000005",
        contact_email="v5@example.gov",
    )
    vendor_id = vendor["id"]
    fx.fund_vendor(vendor_id, 100000)

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-NL1",
        title="Overhead Sign Structure Inspection",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc="2026-08-27T00:00:00Z",
        original_question_deadline_utc="2026-08-20T00:00:00Z",
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-INSP-CERT",
                description="certified bridge inspector on staff",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    fx.submit_question(
        solicitation_id,
        vendor_id,
        question_text=(
            "is the inspector certification transferable from a parent company?"
        ),
    )

    protest = fx.file_protest(
        solicitation_id,
        vendor_id,
        grounds_code="SOLICITATION_IMPROPRIETY",
        narrative="the certification clause is unduly restrictive of competition",
    )
    protest_id = protest["id"]

    fx.add_record_item(
        protest_id,
        headers=OFFICER_HEADERS,
        item_type="AGENCY_REPORT",
        document_ref="AR-NL1-001",
    )
    fx.add_record_item(
        protest_id,
        headers=make_vendor_headers(vendor_id),
        item_type="PROTESTER_SUBMISSION",
        document_ref="PS-NL1-001",
    )

    hearing = fx.schedule_hearing(
        protest_id,
        hearing_officer_user_id=HEARING_OFFICER_USER_ID,
        scheduled_start_utc="2026-08-28T09:00:00Z",
        scheduled_end_utc="2026-08-28T11:00:00Z",
        room_code="ROOM-A",
    )

    return {
        "vendor_id": vendor_id,
        "solicitation_id": solicitation_id,
        "protest_id": protest_id,
        "hearing_id": hearing["id"],
        "hearing": hearing,
    }


def _walk_cycle_to_second_continuance(state: Dict[str, Any]) -> None:
    """Convene, continue, re-convene and continue again, so the hearing has had
    the two continuances the regime allows and sits back in SCHEDULED."""
    hearing_id = state["hearing_id"]
    fx.set_clock("2026-08-28T09:00:00Z")
    fx.convene_hearing(hearing_id)
    fx.continue_hearing(
        hearing_id,
        "2026-08-29T09:00:00Z",
        "2026-08-29T11:00:00Z",
        room_code="ROOM-A",
        continuance_reason="protester counsel unavailable",
    )
    fx.set_clock("2026-08-29T09:00:00Z")
    fx.convene_hearing(hearing_id)
    fx.continue_hearing(
        hearing_id,
        "2026-08-30T09:00:00Z",
        "2026-08-30T11:00:00Z",
        room_code="ROOM-A",
        continuance_reason="agency record supplement ordered",
    )


def _setup_two_responsive_bids_in_evaluation() -> Dict[str, Any]:
    """Two responsive bids one cent apart on a solicitation in EVALUATION, the
    cheaper of the two standing as the apparent low bidder."""
    vendor_a = fx.create_vendor(
        legal_name="Ostrander Utility Boring",
        tax_id="100000006",
        contact_email="v6@example.gov",
    )
    vendor_b = fx.create_vendor(
        legal_name="Quill Valley Constructors",
        tax_id="100000007",
        contact_email="v7@example.gov",
    )

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-NL2",
        title="Fiber Conduit Boring",
        issuing_agency_code="DIT",
        estimated_value_cents=100000000,
        original_bid_due_utc="2026-08-27T00:00:00Z",
        original_question_deadline_utc="2026-08-20T00:00:00Z",
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-LOCATE",
                description="utility locate protocol acknowledgment",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    bid_low = fx.submit_bid(
        solicitation_id,
        vendor_a["id"],
        total_price_cents=100000000,
        acknowledged_addendum_sequences=[],
    )
    bid_high = fx.submit_bid(
        solicitation_id,
        vendor_b["id"],
        total_price_cents=100000001,
        acknowledged_addendum_sequences=[],
    )

    fx.set_clock("2026-08-20T00:00:00Z")
    fx.close_question_period(solicitation_id)
    fx.set_clock("2026-08-27T00:00:00Z")
    opened = fx.open_bids(solicitation_id)
    assert opened["apparent_low_bid_id"] == bid_low["id"], (
        "the cheaper as-read bid must be the apparent low bidder at opening"
    )

    fx.determine_responsiveness(
        bid_low["id"], determination="RESPONSIVE", reason_codes=[]
    )
    fx.determine_responsiveness(
        bid_high["id"], determination="RESPONSIVE", reason_codes=[]
    )

    return {
        "solicitation_id": solicitation_id,
        "low_bid_id": bid_low["id"],
        "high_bid_id": bid_high["id"],
        "low_vendor_id": vendor_a["id"],
        "high_vendor_id": vendor_b["id"],
    }


# ===========================================================================
# The continuance cycle on a protest hearing
# ===========================================================================
class TestHearingContinuanceCycle:
    def test_two_continuances_return_the_hearing_to_scheduled_and_count_up(self):
        """On success the hearing's window and room are replaced by the supplied values, `continuance_count` increases by 1, `convened_at_utc` is cleared back to null, and the hearing's `version` increments by 1.

        Design: Difficulty/non_linear_state_machine/hearing_convene_continue_reconvene_then_third_continuance_refused
        """
        state = _setup_protest_with_hearing_on_docket()
        hearing_id = state["hearing_id"]

        assert state["hearing"]["status"] == "SCHEDULED"
        assert state["hearing"]["continuance_count"] == 0
        assert state["hearing"]["convened_at_utc"] is None

        fx.set_clock("2026-08-28T09:00:00Z")
        convened = fx.convene_hearing(hearing_id)
        assert convened["status"] == "CONVENED"
        assert convened["continuance_count"] == 0
        _assert_same_instant(
            convened["convened_at_utc"], "2026-08-28T09:00:00Z", "convened_at_utc"
        )

        first_grant = validate_success(
            api_client.continue_hearing(
                hearing_id,
                fac.continuance_payload(
                    "2026-08-29T09:00:00Z",
                    "2026-08-29T11:00:00Z",
                    room_code="ROOM-A",
                    continuance_reason="protester counsel unavailable",
                ),
                HEARING_OFFICER_HEADERS,
            )
        )
        assert first_grant["status"] == "SCHEDULED"
        assert first_grant["continuance_count"] == 1
        assert first_grant["convened_at_utc"] is None
        _assert_same_instant(
            first_grant["scheduled_start_utc"],
            "2026-08-29T09:00:00Z",
            "scheduled_start_utc after the first continuance",
        )
        _assert_same_instant(
            first_grant["scheduled_end_utc"],
            "2026-08-29T11:00:00Z",
            "scheduled_end_utc after the first continuance",
        )

        fx.set_clock("2026-08-29T09:00:00Z")
        reconvened = fx.convene_hearing(hearing_id)
        assert reconvened["status"] == "CONVENED"
        assert reconvened["continuance_count"] == 1
        _assert_same_instant(
            reconvened["convened_at_utc"],
            "2026-08-29T09:00:00Z",
            "convened_at_utc on the second convening",
        )

        second_grant = validate_success(
            api_client.continue_hearing(
                hearing_id,
                fac.continuance_payload(
                    "2026-08-30T09:00:00Z",
                    "2026-08-30T11:00:00Z",
                    room_code="ROOM-A",
                    continuance_reason="agency record supplement ordered",
                ),
                HEARING_OFFICER_HEADERS,
            )
        )
        assert second_grant["status"] == "SCHEDULED"
        assert second_grant["continuance_count"] == 2
        assert second_grant["convened_at_utc"] is None
        _assert_same_instant(
            second_grant["scheduled_start_utc"],
            "2026-08-30T09:00:00Z",
            "scheduled_start_utc after the second continuance",
        )
        _assert_same_instant(
            second_grant["scheduled_end_utc"],
            "2026-08-30T11:00:00Z",
            "scheduled_end_utc after the second continuance",
        )

        fx.set_clock("2026-08-30T09:00:00Z")
        third_convening = fx.convene_hearing(hearing_id)
        assert third_convening["status"] == "CONVENED"
        assert third_convening["continuance_count"] == 2
        _assert_same_instant(
            third_convening["convened_at_utc"],
            "2026-08-30T09:00:00Z",
            "convened_at_utc on the third convening",
        )

    def test_third_continuance_is_refused_and_freezes_the_hearing(self):
        """It moves the hearing `CONVENED → SCHEDULED`, requires `continuance_count` to be strictly less than 2 (else `ERR_CONTINUANCE_LIMIT_EXCEEDED`, so at most two continuances are ever granted and a third attempt fails), and requires the new window to pass the same room and docket checks as an original scheduling.

        Design: Difficulty/non_linear_state_machine/hearing_convene_continue_reconvene_then_third_continuance_refused
        """
        state = _setup_protest_with_hearing_on_docket()
        hearing_id = state["hearing_id"]

        _walk_cycle_to_second_continuance(state)
        fx.set_clock("2026-08-30T09:00:00Z")
        fx.convene_hearing(hearing_id)

        validate_error(
            api_client.continue_hearing(
                hearing_id,
                fac.continuance_payload(
                    "2026-08-31T09:00:00Z",
                    "2026-08-31T11:00:00Z",
                    room_code="ROOM-A",
                    continuance_reason="third request",
                ),
                HEARING_OFFICER_HEADERS,
            ),
            ApiErrorId.ERR_CONTINUANCE_LIMIT_EXCEEDED.value,
            expected_status=409,
        )

        frozen = fx.read_hearing(hearing_id)
        assert frozen["status"] == "CONVENED"
        assert frozen["continuance_count"] == 2
        _assert_same_instant(
            frozen["scheduled_start_utc"],
            "2026-08-30T09:00:00Z",
            "scheduled_start_utc after the refused continuance",
        )
        _assert_same_instant(
            frozen["scheduled_end_utc"],
            "2026-08-30T11:00:00Z",
            "scheduled_end_utc after the refused continuance",
        )
        _assert_same_instant(
            frozen["convened_at_utc"],
            "2026-08-30T09:00:00Z",
            "convened_at_utc after the refused continuance",
        )

    def test_protest_stays_hearing_scheduled_across_the_whole_cycle(self):
        """Concluding moves the hearing `CONVENED → CONCLUDED`, requires the protest's `record_item_count` to be at least 2 (else `ERR_AGENCY_RECORD_INCOMPLETE`), stamps `concluded_at_utc` from the logical clock, snapshots `record_items_reviewed_count` as the protest's `record_item_count` at that moment, and drives the protest `HEARING_SCHEDULED → UNDER_REVIEW`.

        Design: Difficulty/non_linear_state_machine/hearing_convene_continue_reconvene_then_third_continuance_refused
        """
        state = _setup_protest_with_hearing_on_docket()
        hearing_id = state["hearing_id"]
        protest_id = state["protest_id"]

        assert fx.read_protest(protest_id)["status"] == "HEARING_SCHEDULED"
        assert fx.read_protest(protest_id)["record_item_count"] == 2

        fx.set_clock("2026-08-28T09:00:00Z")
        fx.convene_hearing(hearing_id)
        assert fx.read_protest(protest_id)["status"] == "HEARING_SCHEDULED"

        fx.continue_hearing(
            hearing_id,
            "2026-08-29T09:00:00Z",
            "2026-08-29T11:00:00Z",
            room_code="ROOM-A",
            continuance_reason="protester counsel unavailable",
        )
        assert fx.read_protest(protest_id)["status"] == "HEARING_SCHEDULED"

        fx.set_clock("2026-08-29T09:00:00Z")
        fx.convene_hearing(hearing_id)
        fx.continue_hearing(
            hearing_id,
            "2026-08-30T09:00:00Z",
            "2026-08-30T11:00:00Z",
            room_code="ROOM-A",
            continuance_reason="agency record supplement ordered",
        )
        fx.set_clock("2026-08-30T09:00:00Z")
        fx.convene_hearing(hearing_id)

        validate_error(
            api_client.continue_hearing(
                hearing_id,
                fac.continuance_payload(
                    "2026-08-31T09:00:00Z",
                    "2026-08-31T11:00:00Z",
                    room_code="ROOM-A",
                    continuance_reason="third request",
                ),
                HEARING_OFFICER_HEADERS,
            ),
            ApiErrorId.ERR_CONTINUANCE_LIMIT_EXCEEDED.value,
            expected_status=409,
        )

        assert fx.read_protest(protest_id)["status"] == "HEARING_SCHEDULED", (
            "the protest cannot revert to UNDER_REVIEW while no hearing on it "
            "has been concluded"
        )


# ===========================================================================
# The two parallel state dimensions of a bid
# ===========================================================================
class TestBidResponsivenessAndResponsibilityDimensions:
    def test_responsibility_moves_while_responsiveness_stays_put(self):
        """These two dimensions evolve independently of one another for the entire life of the bid, which is why a bid can be `RESPONSIVE` and still `NOT_REVIEWED`, or `RESPONSIVE` and `NONRESPONSIBLE`.

        Design: Difficulty/non_linear_state_machine/bid_responsiveness_and_responsibility_dimensions_advance_independently
        """
        state = _setup_two_responsive_bids_in_evaluation()
        low_bid_id = state["low_bid_id"]
        high_bid_id = state["high_bid_id"]
        solicitation_id = state["solicitation_id"]

        before = fx.read_bid(low_bid_id)
        assert before["responsiveness_status"] == "RESPONSIVE"
        assert before["responsibility_status"] == "NOT_REVIEWED"

        review = validate_success(
            api_client.create_responsibility_review(
                low_bid_id,
                fac.responsibility_review_payload(
                    financial_capacity_score=55,
                    past_performance_score=50,
                    integrity_score=60,
                    determination="NONRESPONSIBLE",
                    notes="two terminated contracts in the look-back period",
                ),
                REVIEWER_HEADERS,
            ),
            expected_status=201,
        )

        assert review["composite_score"] == pytest.approx(54.50, abs=0.01)
        assert review["weight_profile"] == "STANDARD"

        after = fx.read_bid(low_bid_id)
        assert after["responsibility_status"] == "NONRESPONSIBLE"
        assert after["responsiveness_status"] == "RESPONSIVE", (
            "a responsibility determination must not touch the responsiveness "
            "dimension"
        )

        solicitation = fx.read_solicitation(solicitation_id)
        assert solicitation["status"] == "EVALUATION"
        assert solicitation["apparent_low_bid_id"] == high_bid_id, (
            "the cheapest bid is excluded from the candidate set by its "
            "NONRESPONSIBLE responsibility status even though it is still "
            "RESPONSIVE"
        )

    def test_second_review_advances_the_solicitation_and_leaves_the_pair_intact(self):
        """A `NONRESPONSIBLE` determination moves `NOT_REVIEWED → NONRESPONSIBLE`, creates the review row with its determination recorded, and leaves the solicitation in `EVALUATION` — it does *not* advance to `AWARD_PENDING`.

        Design: Difficulty/non_linear_state_machine/bid_responsiveness_and_responsibility_dimensions_advance_independently
        """
        state = _setup_two_responsive_bids_in_evaluation()
        low_bid_id = state["low_bid_id"]
        high_bid_id = state["high_bid_id"]
        solicitation_id = state["solicitation_id"]

        validate_success(
            api_client.create_responsibility_review(
                low_bid_id,
                fac.responsibility_review_payload(
                    financial_capacity_score=55,
                    past_performance_score=50,
                    integrity_score=60,
                    determination="NONRESPONSIBLE",
                    notes="two terminated contracts in the look-back period",
                ),
                REVIEWER_HEADERS,
            ),
            expected_status=201,
        )
        assert fx.read_solicitation(solicitation_id)["status"] == "EVALUATION"

        second_review = validate_success(
            api_client.create_responsibility_review(
                high_bid_id,
                fac.responsibility_review_payload(
                    financial_capacity_score=80,
                    past_performance_score=85,
                    integrity_score=90,
                    determination="RESPONSIBLE",
                    notes="clean record",
                ),
                REVIEWER_HEADERS,
            ),
            expected_status=201,
        )
        assert second_review["composite_score"] == pytest.approx(85.00, abs=0.01)

        successor = fx.read_bid(high_bid_id)
        assert successor["responsibility_status"] == "RESPONSIBLE"
        assert successor["responsiveness_status"] == "RESPONSIVE"

        excluded = fx.read_bid(low_bid_id)
        assert excluded["responsiveness_status"] == "RESPONSIVE"
        assert excluded["responsibility_status"] == "NONRESPONSIBLE"

        solicitation = fx.read_solicitation(solicitation_id)
        assert solicitation["status"] == "AWARD_PENDING"
        assert solicitation["apparent_low_bid_id"] == high_bid_id
