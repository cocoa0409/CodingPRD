"""Which single error comes back when two independent rules are broken at once.

Every scenario below is built so that both defects genuinely hold in the same
request, and the fixed evaluation order of PRD §2.10 decides the one error_id the
server may return. Each pair is accompanied by tests that isolate one defect at a
time, so a passing conflict test cannot be explained by a one-sided failure.
"""
from typing import Any, Dict, List

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import (
    HEARING_OFFICER_2_USER_ID,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    OFFICER_2_HEADERS,
    OFFICER_2_USER_ID,
    OFFICER_HEADERS,
    make_vendor_headers,
)

# --------------------------------------------------------------------------
# The shared procurement calendar of this file, all read against the logical
# clock whose default instant is 2026-08-01T00:00:00Z.
# --------------------------------------------------------------------------
QUESTION_DEADLINE_UTC = "2026-08-20T00:00:00Z"
BID_DUE_UTC = "2026-08-27T00:00:00Z"
PAST_EVALUATION_ERROR_DEADLINE_UTC = "2026-09-10T00:00:00Z"

ESTIMATED_VALUE_CENTS = 10000000
FUNDED_BALANCE_CENTS = 100000
# 25,000 base + 7,500 ad valorem + 3,138 grounds surcharge, each rounded first.
IMPROPRIETY_FEE_CENTS = 35638


# --------------------------------------------------------------------------
# Private composition helpers
# --------------------------------------------------------------------------
def _protests_on(solicitation_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api_client.list_protests(
            OFFICER_HEADERS, params={"solicitation_id": solicitation_id}
        )
    )
    return rows


def _hearings_on(protest_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api_client.list_hearings(protest_id, OFFICER_HEADERS)
    )
    return rows


def _build_evaluation_error_state(
    cancelled: bool, filing_clock: str = PAST_EVALUATION_ERROR_DEADLINE_UTC
) -> Dict[str, Any]:
    """A funded bidder on a solicitation whose bids have been opened and whose
    single bid has been determined, optionally cancelled afterwards, with the
    clock finally placed at `filing_clock`."""
    fx.set_clock(DEFAULT_CLOCK_UTC)
    vendor = fx.create_vendor(
        legal_name="Stagg Line Striping",
        tax_id="100000010",
        contact_email="v10@example.gov",
    )
    fx.fund_vendor(vendor["id"], FUNDED_BALANCE_CENTS)
    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-PP1",
        title="Pavement Marking Retrofit",
        issuing_agency_code="DOT",
        estimated_value_cents=ESTIMATED_VALUE_CENTS,
        original_bid_due_utc=BID_DUE_UTC,
        original_question_deadline_utc=QUESTION_DEADLINE_UTC,
        mandatory_requirements=[
            {
                "requirement_code": "REQ-MUTCD",
                "description": "MUTCD compliance statement",
                "materiality": "MATERIAL",
                "is_waivable": False,
            }
        ],
    )
    solicitation_id = solicitation["id"]
    fx.issue_solicitation(solicitation_id)
    bid = fx.submit_bid(solicitation_id, vendor["id"], total_price_cents=5000000)

    fx.set_clock(QUESTION_DEADLINE_UTC)
    fx.close_question_period(solicitation_id)
    fx.set_clock(BID_DUE_UTC)
    fx.open_bids(solicitation_id)
    fx.determine_responsiveness(bid["id"], determination="RESPONSIVE")
    if cancelled:
        fx.cancel_solicitation(
            solicitation_id, cancellation_reason="appropriation lapsed before award"
        )

    fx.set_clock(filing_clock)
    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation_id,
        "bid_id": bid["id"],
    }


def _file_evaluation_error_protest(state: Dict[str, Any]):
    return api_client.create_protest(
        fac.protest_payload(
            state["solicitation_id"],
            state["vendor_id"],
            grounds_code="EVALUATION_ERROR",
            narrative="the bid abstract mis-extended the unit prices",
        ),
        make_vendor_headers(state["vendor_id"]),
    )


def _build_standing_and_fee_state(
    tax_id: str,
    solicitation_number: str,
    with_question: bool,
    fee_balance_cents: int,
) -> Dict[str, Any]:
    """A vendor and a freshly advertised solicitation, where the vendor either
    has asked a question on it or has touched it in no way at all, and whose
    purse holds `fee_balance_cents`."""
    fx.set_clock(DEFAULT_CLOCK_UTC)
    vendor = fx.create_vendor(
        legal_name="Pellworth Fencing",
        tax_id=tax_id,
        contact_email="v{}@example.gov".format(tax_id),
    )
    if fee_balance_cents:
        fx.fund_vendor(vendor["id"], fee_balance_cents)
    solicitation = fx.create_solicitation(
        solicitation_number=solicitation_number,
        title="Right-of-Way Fencing Replacement",
        issuing_agency_code="DOT",
        estimated_value_cents=ESTIMATED_VALUE_CENTS,
        original_bid_due_utc=BID_DUE_UTC,
        original_question_deadline_utc=QUESTION_DEADLINE_UTC,
        mandatory_requirements=[
            {
                "requirement_code": "REQ-FENCE-SPEC",
                "description": "galvanized fabric specification",
                "materiality": "MATERIAL",
                "is_waivable": False,
            }
        ],
    )
    solicitation_id = solicitation["id"]
    fx.issue_solicitation(solicitation_id)
    if with_question:
        fx.submit_question(
            solicitation_id,
            vendor["id"],
            question_text="may an equivalent coating be offered?",
        )
    return {"vendor_id": vendor["id"], "solicitation_id": solicitation_id}


def _file_impropriety_protest(state: Dict[str, Any]):
    return api_client.create_protest(
        fac.protest_payload(
            state["solicitation_id"],
            state["vendor_id"],
            grounds_code="SOLICITATION_IMPROPRIETY",
            narrative="the fabric specification names a sole source",
        ),
        make_vendor_headers(state["vendor_id"]),
    )


def _build_two_protests_with_one_booked_room() -> Dict[str, Any]:
    """Two protests under review, one on a solicitation issued by U-OFFICER-1 and
    one on a solicitation issued by U-OFFICER-2, with a hearing already occupying
    ROOM-A from 09:00 to 11:00 on 2026-08-28."""
    fx.set_clock(DEFAULT_CLOCK_UTC)
    vendor = fx.create_vendor(
        legal_name="Larkspur Traffic Systems",
        tax_id="100000012",
        contact_email="v12@example.gov",
    )
    vendor_id = vendor["id"]
    fx.fund_vendor(vendor_id, FUNDED_BALANCE_CENTS)

    first = fx.create_solicitation(
        solicitation_number="SOL-2238-PP3A",
        title="Signal Cabinet Upgrade North",
        issuing_agency_code="DOT",
        estimated_value_cents=ESTIMATED_VALUE_CENTS,
        original_bid_due_utc=BID_DUE_UTC,
        original_question_deadline_utc=QUESTION_DEADLINE_UTC,
        mandatory_requirements=[
            {
                "requirement_code": "REQ-IMSA",
                "description": "IMSA level II technician",
                "materiality": "MATERIAL",
                "is_waivable": False,
            }
        ],
    )
    first_id = first["id"]
    fx.issue_solicitation(first_id, headers=OFFICER_HEADERS)

    second = fx.create_solicitation(
        headers=OFFICER_2_HEADERS,
        solicitation_number="SOL-2238-PP3B",
        title="Signal Cabinet Upgrade South",
        issuing_agency_code="DOT",
        estimated_value_cents=ESTIMATED_VALUE_CENTS,
        original_bid_due_utc=BID_DUE_UTC,
        original_question_deadline_utc=QUESTION_DEADLINE_UTC,
        mandatory_requirements=[
            {
                "requirement_code": "REQ-IMSA",
                "description": "IMSA level II technician",
                "materiality": "MATERIAL",
                "is_waivable": False,
            }
        ],
    )
    second_id = second["id"]
    fx.issue_solicitation(second_id, headers=OFFICER_2_HEADERS)

    for solicitation_id in (first_id, second_id):
        fx.submit_question(
            solicitation_id,
            vendor_id,
            question_text="may the IMSA certification be held by a subcontractor?",
        )

    first_protest = fx.file_protest(
        first_id,
        vendor_id,
        grounds_code="SOLICITATION_IMPROPRIETY",
        narrative="the certification clause excludes qualified integrators",
    )
    second_protest = fx.file_protest(
        second_id,
        vendor_id,
        grounds_code="SOLICITATION_IMPROPRIETY",
        narrative="the certification clause excludes qualified integrators",
    )

    fx.add_record_item(
        first_protest["id"],
        headers=OFFICER_HEADERS,
        item_type="AGENCY_REPORT",
        document_ref="AR-PP3A-001",
    )
    fx.add_record_item(
        second_protest["id"],
        headers=OFFICER_2_HEADERS,
        item_type="AGENCY_REPORT",
        document_ref="AR-PP3B-001",
    )

    booked = fx.schedule_hearing(
        first_protest["id"],
        hearing_officer_user_id=HEARING_OFFICER_USER_ID,
        scheduled_start_utc="2026-08-28T09:00:00Z",
        scheduled_end_utc="2026-08-28T11:00:00Z",
        room_code="ROOM-A",
    )
    return {
        "vendor_id": vendor_id,
        "first_solicitation_id": first_id,
        "second_solicitation_id": second_id,
        "first_protest_id": first_protest["id"],
        "second_protest_id": second_protest["id"],
        "booked_hearing_id": booked["id"],
    }


# ==========================================================================
# Protestability of the solicitation against protest timeliness
# ==========================================================================
class TestNotProtestableOutranksUntimely:
    def test_cancelled_solicitation_beats_expired_evaluation_error_window(self):
        """A cancelled solicitation and a filing made after the seven-day
        evaluation-error window has run are both defects of the same request, and
        the protestability check at step 11 of the ladder is the one that answers.

        "When a request violates more than one rule, exactly one error is returned, and which one is determined by a fixed evaluation order rather than by the order the checks happen to appear in an implementation."
        "Protestability of the solicitation: a protest is accepted only when the solicitation's `status` is one of `ISSUED`, `QUESTION_PERIOD_CLOSED`, `BIDS_OPENED`, `EVALUATION`, `AWARD_PENDING` or `AWARDED`; a `DRAFT`, `CANCELLED` or `RESOLICITED` solicitation accepts no protest — `ERR_SOLICITATION_NOT_PROTESTABLE`."

        Design: Difficulty/priority_pair_validation_conflict/cancelled_solicitation_state_error_precedes_untimely_protest_temporal_error
        """
        state = _build_evaluation_error_state(cancelled=True)

        response = _file_evaluation_error_protest(state)
        error = validate_error(
            response,
            ApiErrorId.ERR_SOLICITATION_NOT_PROTESTABLE.value,
            expected_status=409,
        )
        assert error["error_id"] != ApiErrorId.ERR_PROTEST_UNTIMELY.value, (
            "the temporal defect must not be reported ahead of the state defect"
        )
        assert response.status_code == 409

        assert _protests_on(state["solicitation_id"]) == []
        vendor = fx.read_vendor(state["vendor_id"])
        assert vendor["protest_fee_balance_cents"] == FUNDED_BALANCE_CENTS
        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["protest_escrow_cents"] == 0
        assert solicitation["status"] == "CANCELLED"

    def test_expired_evaluation_error_window_alone_is_reported_as_untimely(self):
        """With the solicitation left in EVALUATION and therefore protestable, the
        stale filing instant is the only defect left and the timeliness rule is
        what refuses the filing on its own.

        "A filing after it is refused with `ERR_PROTEST_UNTIMELY`."

        Design: Difficulty/priority_pair_validation_conflict/cancelled_solicitation_state_error_precedes_untimely_protest_temporal_error
        """
        state = _build_evaluation_error_state(cancelled=False)

        response = _file_evaluation_error_protest(state)
        error = validate_error(
            response, ApiErrorId.ERR_PROTEST_UNTIMELY.value, expected_status=409
        )
        assert error["error_id"] == ApiErrorId.ERR_PROTEST_UNTIMELY.value

        assert _protests_on(state["solicitation_id"]) == []
        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["status"] == "EVALUATION"
        assert solicitation["protest_escrow_cents"] == 0
        assert (
            fx.read_vendor(state["vendor_id"])["protest_fee_balance_cents"]
            == FUNDED_BALANCE_CENTS
        )

    def test_cancelled_solicitation_alone_is_reported_as_not_protestable(self):
        """Filed well inside the evaluation-error window, the cancellation is the
        only defect and produces the same refusal the conflicting request did.

        "The solicitation must be protestable per §2.10, else `ERR_SOLICITATION_NOT_PROTESTABLE`."

        Design: Difficulty/priority_pair_validation_conflict/cancelled_solicitation_state_error_precedes_untimely_protest_temporal_error
        """
        state = _build_evaluation_error_state(
            cancelled=True, filing_clock=BID_DUE_UTC
        )

        response = _file_evaluation_error_protest(state)
        validate_error(
            response,
            ApiErrorId.ERR_SOLICITATION_NOT_PROTESTABLE.value,
            expected_status=409,
        )

        assert _protests_on(state["solicitation_id"]) == []
        assert fx.read_solicitation(state["solicitation_id"])["status"] == "CANCELLED"


# ==========================================================================
# Protester standing against sufficiency of the fee balance
# ==========================================================================
class TestLacksStandingOutranksInsufficientFeeBalance:
    def test_absent_standing_beats_an_empty_protest_purse(self):
        """A vendor that neither bid nor asked a question, filing against a purse
        that could not pay the fee either, is answered on standing at step 23
        rather than on the fiscal check at step 48.

        "When a request violates more than one rule, exactly one error is returned, and which one is determined by a fixed evaluation order rather than by the order the checks happen to appear in an implementation."
        "Where neither basis is satisfied, the filing is refused with `ERR_PROTESTER_LACKS_STANDING` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/absent_standing_safety_error_precedes_insufficient_fee_fiscal_error
        """
        state = _build_standing_and_fee_state(
            tax_id="100000011",
            solicitation_number="SOL-2238-PP2",
            with_question=False,
            fee_balance_cents=0,
        )

        response = _file_impropriety_protest(state)
        error = validate_error(
            response,
            ApiErrorId.ERR_PROTESTER_LACKS_STANDING.value,
            expected_status=403,
        )
        assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_FEE_BALANCE.value, (
            "the fiscal defect must not be reported ahead of the standing defect"
        )
        assert response.status_code != 402

        assert _protests_on(state["solicitation_id"]) == []
        assert fx.read_vendor(state["vendor_id"])["protest_fee_balance_cents"] == 0
        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["protest_escrow_cents"] == 0
        assert solicitation["status"] == "ISSUED"

    def test_empty_protest_purse_alone_is_reported_as_insufficient_balance(self):
        """Give the same vendor a pending question and it acquires prospective-bidder
        standing, leaving the unfunded purse as the only defect, which the fiscal
        rule then reports on its own.

        "The protester's `protest_fee_balance_cents` must be at least the computed `filing_fee_cents`, otherwise the filing is refused with `ERR_INSUFFICIENT_FEE_BALANCE` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/absent_standing_safety_error_precedes_insufficient_fee_fiscal_error
        """
        state = _build_standing_and_fee_state(
            tax_id="100000013",
            solicitation_number="SOL-2238-PP2B",
            with_question=True,
            fee_balance_cents=0,
        )

        response = _file_impropriety_protest(state)
        validate_error(
            response,
            ApiErrorId.ERR_INSUFFICIENT_FEE_BALANCE.value,
            expected_status=402,
        )

        assert _protests_on(state["solicitation_id"]) == []
        assert fx.read_vendor(state["vendor_id"])["protest_fee_balance_cents"] == 0
        assert fx.read_solicitation(state["solicitation_id"])["protest_escrow_cents"] == 0

    def test_absent_standing_alone_is_reported_with_a_funded_purse(self):
        """Funding the purse well past the fee removes the fiscal defect, and the
        missing standing basis still refuses the filing by itself.

        "Where neither basis is satisfied, the filing is refused with `ERR_PROTESTER_LACKS_STANDING` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/absent_standing_safety_error_precedes_insufficient_fee_fiscal_error
        """
        state = _build_standing_and_fee_state(
            tax_id="100000014",
            solicitation_number="SOL-2238-PP2C",
            with_question=False,
            fee_balance_cents=FUNDED_BALANCE_CENTS,
        )
        assert FUNDED_BALANCE_CENTS > IMPROPRIETY_FEE_CENTS

        response = _file_impropriety_protest(state)
        validate_error(
            response,
            ApiErrorId.ERR_PROTESTER_LACKS_STANDING.value,
            expected_status=403,
        )

        assert _protests_on(state["solicitation_id"]) == []
        assert (
            fx.read_vendor(state["vendor_id"])["protest_fee_balance_cents"]
            == FUNDED_BALANCE_CENTS
        )


# ==========================================================================
# Hearing-officer segregation of duties against hearing-room occupancy
# ==========================================================================
class TestHearingOfficerConflictOutranksRoomConflict:
    def test_conflicted_presider_beats_an_overlapping_room_booking(self):
        """Naming the official who advertised the protested solicitation as the
        presiding officer, in a window that also collides with an existing ROOM-A
        booking inside the changeover buffer, is answered at step 21 of the ladder.

        "When a request violates more than one rule, exactly one error is returned, and which one is determined by a fixed evaluation order rather than by the order the checks happen to appear in an implementation."
        "The `hearing_officer_user_id` supplied when a hearing is scheduled must differ from the `issued_by_user_id` recorded on the protested solicitation, and the `X-User-ID` of the `HearingOfficer` who issues the decision must likewise differ from it."

        Design: Difficulty/priority_pair_validation_conflict/hearing_officer_conflict_safety_error_precedes_room_conflict_constraint_error
        """
        state = _build_two_protests_with_one_booked_room()

        response = api_client.create_hearing(
            state["second_protest_id"],
            fac.hearing_payload(
                OFFICER_2_USER_ID,
                scheduled_start_utc="2026-08-28T09:30:00Z",
                scheduled_end_utc="2026-08-28T10:30:00Z",
                room_code="ROOM-A",
            ),
            HEARING_OFFICER_HEADERS,
        )
        error = validate_error(
            response,
            ApiErrorId.ERR_HEARING_OFFICER_CONFLICT.value,
            expected_status=403,
        )
        assert error["error_id"] != ApiErrorId.ERR_HEARING_ROOM_CONFLICT.value, (
            "the occupancy defect must not be reported ahead of the authority defect"
        )
        assert response.status_code == 403

        assert _hearings_on(state["second_protest_id"]) == []
        assert fx.read_protest(state["second_protest_id"])["status"] == "UNDER_REVIEW"
        booked = fx.read_hearing(state["booked_hearing_id"])
        assert booked["status"] == "SCHEDULED"
        assert booked["room_code"] == "ROOM-A"
        assert (
            fx.read_vendor(state["vendor_id"])["protest_fee_balance_cents"]
            == FUNDED_BALANCE_CENTS - 2 * IMPROPRIETY_FEE_CENTS
        )

    def test_overlapping_room_booking_alone_is_reported_as_a_room_conflict(self):
        """With an unconflicted presider named, the same window is refused purely
        for the ROOM-A collision, which proves the occupancy rule was live in the
        conflicting request too.

        "For the same `room_code`, the candidate conflicts with any *other* hearing whose `status` is `SCHEDULED` or `CONVENED` when the candidate's start is earlier than that hearing's end extended by thirty minutes *and* that hearing's start is earlier than the candidate's end extended by thirty minutes."

        Design: Difficulty/priority_pair_validation_conflict/hearing_officer_conflict_safety_error_precedes_room_conflict_constraint_error
        """
        state = _build_two_protests_with_one_booked_room()

        response = api_client.create_hearing(
            state["second_protest_id"],
            fac.hearing_payload(
                HEARING_OFFICER_2_USER_ID,
                scheduled_start_utc="2026-08-28T09:30:00Z",
                scheduled_end_utc="2026-08-28T10:30:00Z",
                room_code="ROOM-A",
            ),
            HEARING_OFFICER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_HEARING_ROOM_CONFLICT.value, expected_status=409
        )

        assert _hearings_on(state["second_protest_id"]) == []
        assert fx.read_protest(state["second_protest_id"])["status"] == "UNDER_REVIEW"

    def test_conflicted_presider_alone_is_reported_in_a_free_room(self):
        """Moved to an unoccupied room, the same presider is still the official who
        issued the protested solicitation, and the segregation-of-duties rule
        refuses the scheduling by itself.

        "The protest must be in `UNDER_REVIEW`, its `record_item_count` must be at least 1, and the presiding officer must not be the official who issued the solicitation, else `ERR_HEARING_OFFICER_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/hearing_officer_conflict_safety_error_precedes_room_conflict_constraint_error
        """
        state = _build_two_protests_with_one_booked_room()

        response = api_client.create_hearing(
            state["second_protest_id"],
            fac.hearing_payload(
                OFFICER_2_USER_ID,
                scheduled_start_utc="2026-08-28T09:30:00Z",
                scheduled_end_utc="2026-08-28T10:30:00Z",
                room_code="ROOM-B",
            ),
            HEARING_OFFICER_HEADERS,
        )
        validate_error(
            response,
            ApiErrorId.ERR_HEARING_OFFICER_CONFLICT.value,
            expected_status=403,
        )

        assert _hearings_on(state["second_protest_id"]) == []
        assert fx.read_hearing(state["booked_hearing_id"])["status"] == "SCHEDULED"
