"""Occupancy of two contended resources: the hearing room and the respondent
vendor's compliance docket.

Each group pins the same boundary from both sides — the instant at which a
second booking is still refused, and the nearest instant at which it is taken.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import ROOM_CHANGEOVER_BUFFER_MINUTES
from test_helpers.test_users import (
    DEBARMENT_AUTHORITY_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
)

# --------------------------------------------------------------------------
# Pinned instants of the hearing calendar
# --------------------------------------------------------------------------
ROOM_A = "ROOM-A"
ROOM_B = "ROOM-B"

INCUMBENT_START = "2026-08-28T09:00:00Z"
INCUMBENT_END = "2026-08-28T11:00:00Z"

# Pinned instants of the compliance-docket calendar
NOTICE_INSTANT = "2026-08-01T00:00:00Z"
HEARING_INSTANT = "2026-08-16T00:00:00Z"
DISMISSAL_INSTANT = "2026-08-20T00:00:00Z"


# --------------------------------------------------------------------------
# Private helpers
# --------------------------------------------------------------------------
def _instant(value: Any) -> datetime:
    """Parse a rendered UTC instant so comparisons ignore fractional padding."""
    assert isinstance(value, str) and value, "expected an ISO-8601 instant, got {!r}".format(
        value
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _plus_minutes(value: str, minutes: int) -> str:
    return _iso(_instant(value) + timedelta(minutes=minutes))


# The changeover buffer is applied on both sides, so the earliest start that
# clears an incumbent ending at 11:00 is 11:00 plus thirty minutes.
FIRST_FREE_START = _plus_minutes(INCUMBENT_END, ROOM_CHANGEOVER_BUFFER_MINUTES)
LAST_BUFFERED_START = _plus_minutes(FIRST_FREE_START, -1)
LAST_BUFFERED_END = _plus_minutes(LAST_BUFFERED_START, 60)


def _requirement() -> Dict[str, Any]:
    return fac.requirement_payload(
        requirement_code="REQ-SWPPP",
        description="stormwater pollution prevention plan",
        materiality="MATERIAL",
        is_waivable=False,
    )


def _two_protests_with_one_hearing_booked() -> Dict[str, Any]:
    """Two solicitation-impropriety protests by one funded vendor, both under
    review, with a 09:00-11:00 hearing already sitting in ROOM-A on the first."""
    fx.reset_clock()
    vendor = fx.create_vendor(
        legal_name="Vellmont Earthworks",
        tax_id="100000020",
        contact_email="v20@example.gov",
    )
    vendor_id = vendor["id"]
    fx.fund_vendor(vendor_id, 100000)

    solicitation_ids = []
    for number, title in (
        ("SOL-2238-RT1A", "Detention Basin Grading North"),
        ("SOL-2238-RT1B", "Detention Basin Grading South"),
    ):
        solicitation = fx.create_solicitation(
            solicitation_number=number,
            title=title,
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc="2026-08-27T00:00:00Z",
            original_question_deadline_utc="2026-08-20T00:00:00Z",
            mandatory_requirements=[_requirement()],
        )
        fx.issue_solicitation(solicitation["id"])
        solicitation_ids.append(solicitation["id"])

    protest_ids = []
    for index, solicitation_id in enumerate(solicitation_ids):
        fx.submit_question(
            solicitation_id,
            vendor_id,
            question_text="who holds the SWPPP permit of record?",
        )
        protest = fx.file_protest(
            solicitation_id,
            vendor_id,
            grounds_code="SOLICITATION_IMPROPRIETY",
            narrative="the permit-of-record clause is internally contradictory",
        )
        protest_ids.append(protest["id"])
        fx.add_record_item(
            protest["id"],
            item_type="AGENCY_REPORT",
            document_ref="AR-RT1{}-001".format("AB"[index]),
        )

    incumbent = fx.schedule_hearing(
        protest_ids[0],
        hearing_officer_user_id=HEARING_OFFICER_USER_ID,
        scheduled_start_utc=INCUMBENT_START,
        scheduled_end_utc=INCUMBENT_END,
        room_code=ROOM_A,
    )
    return {
        "vendor_id": vendor_id,
        "solicitation_ids": solicitation_ids,
        "first_protest_id": protest_ids[0],
        "second_protest_id": protest_ids[1],
        "incumbent_hearing_id": incumbent["id"],
    }


def _book(protest_id: str, start_utc: str, end_utc: str, room_code: str):
    return api_client.create_hearing(
        protest_id,
        fac.hearing_payload(
            HEARING_OFFICER_USER_ID,
            scheduled_start_utc=start_utc,
            scheduled_end_utc=end_utc,
            room_code=room_code,
        ),
        HEARING_OFFICER_HEADERS,
    )


def _dismissed_proceeding_on_a_returned_vendor() -> Dict[str, Any]:
    """One respondent whose interim-suspended proceeding was dismissed at
    exactly 2026-08-20T00:00:00Z, with the clock left standing on that instant."""
    fx.reset_clock()
    vendor = fx.create_vendor(
        legal_name="Ironwood Signal Contractors",
        tax_id="100000021",
        contact_email="v21@example.gov",
    )
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="FRAUD",
        aggravating_factor_codes=["FRAUD"],
        mitigating_factor_codes=[],
        interim_suspension=True,
    )
    fx.set_clock(HEARING_INSTANT)
    fx.hold_debarment_hearing(
        proceeding["id"],
        hearing_summary=(
            "respondent did not appear; record closed on the documentary submissions"
        ),
    )
    fx.set_clock(DISMISSAL_INSTANT)
    proceeding = fx.decide_debarment(
        proceeding["id"],
        outcome="DISMISSED",
        rationale=(
            "the invoicing discrepancy was a clerical error, not a misrepresentation"
        ),
    )
    return {
        "vendor_id": vendor["id"],
        "proceeding_id": proceeding["id"],
        "proceeding": proceeding,
    }


def _second_notice(vendor_id: str):
    return api_client.create_debarment_proceeding(
        fac.proceeding_payload(
            vendor_id,
            cause_code="REPEATED_NONPERFORMANCE",
            aggravating_factor_codes=["REPEATED_NONPERFORMANCE"],
            mitigating_factor_codes=[],
            interim_suspension=False,
        ),
        DEBARMENT_AUTHORITY_HEADERS,
    )


# ==========================================================================
# The hearing room
# ==========================================================================
class TestHearingRoomOccupancy:
    """One room, one incumbent 09:00-11:00 booking, and the buffered boundary."""

    @pytest.mark.parametrize(
        "candidate_start,candidate_end",
        [
            (INCUMBENT_END, "2026-08-28T12:00:00Z"),
            (LAST_BUFFERED_START, LAST_BUFFERED_END),
        ],
        ids=["exactly_adjacent", "one_minute_inside_the_buffer"],
    )
    def test_second_booking_inside_the_changeover_buffer_is_refused(
        self, candidate_start, candidate_end
    ):
        """Because the buffer is applied on both sides in this form, two exactly adjacent bookings in the same room *do* conflict, and so does any booking that comes within half an hour of another.

        Design: Difficulty/resource_temporal_overlap/hearing_room_rejects_an_exactly_adjacent_booking_inside_the_changeover_buffer
        """
        state = _two_protests_with_one_hearing_booked()

        response = _book(
            state["second_protest_id"], candidate_start, candidate_end, ROOM_A
        )
        validate_error(
            response, ApiErrorId.ERR_HEARING_ROOM_CONFLICT.value, expected_status=409
        )

        # Nothing was written: the second protest still has no hearing at all.
        rows, meta = validate_paginated(
            api_client.list_hearings(state["second_protest_id"], HEARING_OFFICER_HEADERS)
        )
        assert rows == [], "the refused booking must leave no hearing row: {}".format(rows)
        assert meta["total_count"] == 0

        assert fx.read_protest(state["second_protest_id"])["status"] == "UNDER_REVIEW"

        incumbent = fx.read_hearing(state["incumbent_hearing_id"])
        assert incumbent["status"] == "SCHEDULED"
        assert incumbent["room_code"] == ROOM_A
        assert _instant(incumbent["scheduled_end_utc"]) == _instant(INCUMBENT_END)

    def test_booking_starting_exactly_one_buffer_after_the_incumbent_is_taken(self):
        """For the same `room_code`, the candidate conflicts with any *other* hearing whose `status` is `SCHEDULED` or `CONVENED` when the candidate's start is earlier than that hearing's end extended by thirty minutes *and* that hearing's start is earlier than the candidate's end extended by thirty minutes.

        Design: Difficulty/resource_temporal_overlap/hearing_room_rejects_an_exactly_adjacent_booking_inside_the_changeover_buffer
        """
        state = _two_protests_with_one_hearing_booked()

        response = _book(
            state["second_protest_id"],
            FIRST_FREE_START,
            _plus_minutes(FIRST_FREE_START, 60),
            ROOM_A,
        )
        hearing = validate_success(response, expected_status=201)

        assert hearing["status"] == "SCHEDULED"
        assert hearing["room_code"] == ROOM_A
        assert _instant(hearing["scheduled_start_utc"]) == _instant(FIRST_FREE_START)
        assert hearing["continuance_count"] == 0
        assert hearing["convened_at_utc"] is None

        assert fx.read_protest(state["second_protest_id"])["status"] == "HEARING_SCHEDULED"

        # The incumbent keeps its own window and room.
        incumbent = fx.read_hearing(state["incumbent_hearing_id"])
        assert incumbent["status"] == "SCHEDULED"
        assert _instant(incumbent["scheduled_end_utc"]) == _instant(INCUMBENT_END)

    def test_the_same_adjacent_window_is_taken_in_a_different_room(self):
        """For the same `room_code`, the candidate conflicts with any *other* hearing whose `status` is `SCHEDULED` or `CONVENED` when the candidate's start is earlier than that hearing's end extended by thirty minutes *and* that hearing's start is earlier than the candidate's end extended by thirty minutes.

        Design: Difficulty/resource_temporal_overlap/hearing_room_rejects_an_exactly_adjacent_booking_inside_the_changeover_buffer
        """
        state = _two_protests_with_one_hearing_booked()

        response = _book(
            state["second_protest_id"], INCUMBENT_END, "2026-08-28T12:00:00Z", ROOM_B
        )
        hearing = validate_success(response, expected_status=201)

        assert hearing["room_code"] == ROOM_B
        assert hearing["status"] == "SCHEDULED"
        assert _instant(hearing["scheduled_start_utc"]) == _instant(INCUMBENT_END)

        rows, meta = validate_paginated(
            api_client.list_hearings(state["second_protest_id"], HEARING_OFFICER_HEADERS)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [hearing["id"]]


# ==========================================================================
# The respondent vendor's compliance docket
# ==========================================================================
class TestComplianceDocketOccupancy:
    """One dismissed proceeding and the closed interval it still occupies."""

    def test_notice_at_exactly_the_dismissal_instant_is_refused(self):
        """Each proceeding occupies a closed interval on its respondent's compliance docket, running from its `notice_issued_at_utc` to an occupancy end that depends on its `status`: `debarment_end_utc` once the proceeding is `DEBARRED`, `decided_at_utc` once it is `DISMISSED`, and its own `notice_issued_at_utc` plus ten years — 3,650 days — while it is still live in `NOTICE_ISSUED`, `RESPONSE_RECEIVED` or `HEARING_HELD`.

        Design: Difficulty/resource_temporal_overlap/vendor_compliance_docket_rejects_a_notice_at_exactly_the_prior_resolution_instant
        """
        state = _dismissed_proceeding_on_a_returned_vendor()

        response = _second_notice(state["vendor_id"])
        validate_error(
            response, ApiErrorId.ERR_ACTIVE_PROCEEDING_EXISTS.value, expected_status=409
        )

        rows, meta = validate_paginated(
            api_client.list_debarment_proceedings(
                DEBARMENT_AUTHORITY_HEADERS, params={"vendor_id": state["vendor_id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [state["proceeding_id"]]

        proceeding = fx.read_proceeding(state["proceeding_id"])
        assert proceeding["status"] == "DISMISSED"
        assert _instant(proceeding["decided_at_utc"]) == _instant(DISMISSAL_INSTANT)
        assert _instant(proceeding["notice_issued_at_utc"]) == _instant(NOTICE_INSTANT)
        assert proceeding["interim_status"] == "INTERIM_LIFTED"
        assert proceeding["strikes_applied"] == 0

        # The respondent is back in good standing, so it is the docket interval
        # and not the vendor's status that refused the notice.
        vendor = fx.read_vendor(state["vendor_id"])
        assert vendor["eligibility_status"] == "ELIGIBLE"
        assert vendor["debarment_strike_count"] == 0
        assert vendor["active_debarment_id"] is None

    @pytest.mark.parametrize(
        "notice_clock",
        ["2026-08-20T00:00:00.001Z", "2026-08-20T00:00:01Z"],
        ids=["one_millisecond_after", "one_second_after"],
    )
    def test_notice_strictly_after_the_dismissal_instant_is_accepted(self, notice_clock):
        """If the new notice instant falls inside any other proceeding's occupancy interval for the same vendor, the proceeding is refused with `ERR_ACTIVE_PROCEEDING_EXISTS`.

        Design: Difficulty/resource_temporal_overlap/vendor_compliance_docket_rejects_a_notice_at_exactly_the_prior_resolution_instant
        """
        state = _dismissed_proceeding_on_a_returned_vendor()
        fx.set_clock(notice_clock)

        response = _second_notice(state["vendor_id"])
        second = validate_success(response, expected_status=201)

        assert second["status"] == "NOTICE_ISSUED"
        assert second["interim_status"] == "NONE"
        assert second["strikes_applied"] == 0
        assert second["vendor_id"] == state["vendor_id"]
        assert _instant(second["notice_issued_at_utc"]) > _instant(DISMISSAL_INSTANT)

        rows, meta = validate_paginated(
            api_client.list_debarment_proceedings(
                DEBARMENT_AUTHORITY_HEADERS, params={"vendor_id": state["vendor_id"]}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in rows) == sorted(
            [state["proceeding_id"], second["id"]]
        )

        # The earlier proceeding is untouched by the new notice.
        earlier = fx.read_proceeding(state["proceeding_id"])
        assert earlier["status"] == "DISMISSED"
        assert _instant(earlier["decided_at_utc"]) == _instant(DISMISSAL_INSTANT)
