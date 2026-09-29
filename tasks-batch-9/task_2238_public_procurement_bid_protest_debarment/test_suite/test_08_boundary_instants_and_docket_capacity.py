"""Inclusive boundaries exercised from both sides.

Two independent ceilings are pinned here. The first is a datetime instant: the
earliest instant at which a debarred vendor may petition for reinstatement,
compared inclusively against the logical clock. The second is a cumulative
minutes ceiling: the eight hours of one hearing officer's time available inside
a single UTC calendar day. Each is tested at the exact boundary value, which
must be accepted, and one unit past it, which must be refused with the
catalogued error.
"""
from datetime import datetime, timezone
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
from test_helpers.test_users import (
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    OFFICER_HEADERS,
    make_vendor_headers,
)

# ---------------------------------------------------------------------------
# The reinstatement boundary: a twelve month debarment starting 2026-08-16
# admits a petition six calendar months later.
# ---------------------------------------------------------------------------
DEBARMENT_DECISION_INSTANT = "2026-08-16T00:00:00Z"
DEBARMENT_END_INSTANT = "2027-08-16T00:00:00Z"
EARLIEST_PETITION_INSTANT = "2027-02-16T00:00:00Z"
ONE_MILLISECOND_EARLIER = "2027-02-15T23:59:59.999Z"

# ---------------------------------------------------------------------------
# The docket boundary: 240 booked minutes plus a 240 minute candidate window.
# ---------------------------------------------------------------------------
FIRST_HEARING_START = "2026-08-28T09:00:00Z"
FIRST_HEARING_END = "2026-08-28T13:00:00Z"
SECOND_HEARING_START = "2026-08-28T14:00:00Z"
SECOND_HEARING_END_AT_CEILING = "2026-08-28T18:00:00Z"
SECOND_HEARING_END_ONE_MINUTE_PAST = "2026-08-28T18:01:00Z"

SOLICITATION_IMPROPRIETY_FEE_CENTS = 35638
BALANCE_AFTER_TWO_FILINGS_CENTS = 100000 - 2 * SOLICITATION_IMPROPRIETY_FEE_CENTS


def _instant(value: Any) -> datetime:
    """Parse an ISO-8601 UTC instant so two spellings of one instant compare
    equal regardless of how many fractional digits the server emits."""
    assert isinstance(value, str) and value, (
        "expected an ISO-8601 instant, got {!r}".format(value)
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


# ---------------------------------------------------------------------------
# State builders
# ---------------------------------------------------------------------------
def _debar_a_vendor_on_the_default_branch() -> Dict[str, Any]:
    """A vendor carried to DEBARRED for twelve months from 2026-08-16, through
    the branch where the respondent never answers the notice."""
    vendor = fx.create_vendor(
        legal_name="Havenridge Bridge Works",
        tax_id="100000015",
        contact_email="v15@example.gov",
    )
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="REPEATED_NONPERFORMANCE",
        aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    fx.set_clock(DEBARMENT_DECISION_INSTANT)
    fx.hold_debarment_hearing(
        proceeding["id"],
        hearing_summary=(
            "no response filed within the notice window; default branch recorded"
        ),
    )
    proceeding = fx.decide_debarment(
        proceeding["id"],
        outcome="DEBARRED",
        rationale="repeated nonperformance with an uncorrected safety finding",
    )
    return {
        "vendor_id": vendor["id"],
        "proceeding": proceeding,
        "proceeding_id": proceeding["id"],
    }


def _petition_response(proceeding_id: str, vendor_id: str):
    """The respondent's own petition, pinned to the proceeding version it just
    read, returned unvalidated so either polarity can be asserted."""
    return api_client.create_reinstatement_petition(
        proceeding_id,
        fac.petition_payload(
            remediation_evidence_codes=[
                "MANAGEMENT_REPLACED",
                "COMPLIANCE_AUDIT_PASSED",
            ],
            narrative=(
                "ownership replaced the responsible managers and passed an "
                "independent compliance audit"
            ),
            expected_proceeding_version=fx.proceeding_version(proceeding_id),
        ),
        make_vendor_headers(vendor_id),
    )


def _two_protests_under_review_with_240_minutes_booked() -> Dict[str, Any]:
    """One prospective bidder protesting two sibling solicitations, with the
    first protest's hearing already occupying four hours of U-HEARING-1's
    2026-08-28 docket."""
    vendor = fx.create_vendor(
        legal_name="Cordell Utility Boring",
        tax_id="100000016",
        contact_email="v16@example.gov",
    )
    fx.fund_vendor(vendor["id"], 100000)

    protest_ids = []
    for number, title in (
        ("SOL-2238-BP2A", "Conduit Boring East Corridor"),
        ("SOL-2238-BP2B", "Conduit Boring West Corridor"),
    ):
        solicitation = fx.create_solicitation(
            solicitation_number=number,
            title=title,
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc="2026-08-27T00:00:00Z",
            original_question_deadline_utc="2026-08-20T00:00:00Z",
            mandatory_requirements=[
                fac.requirement_payload(
                    requirement_code="REQ-LOCATE",
                    description="utility locate protocol",
                    materiality="MATERIAL",
                    is_waivable=False,
                )
            ],
        )
        fx.issue_solicitation(solicitation["id"])
        fx.submit_question(
            solicitation["id"],
            vendor["id"],
            question_text=(
                "is the locate protocol the owner's or the contractor's obligation?"
            ),
        )
        protest = fx.file_protest(
            solicitation["id"],
            vendor["id"],
            grounds_code="SOLICITATION_IMPROPRIETY",
            narrative="the locate protocol shifts an unquantifiable risk to bidders",
        )
        fx.add_record_item(
            protest["id"],
            item_type="AGENCY_REPORT",
            document_ref="AR-{}-001".format(number.rsplit("-", 1)[-1]),
        )
        protest_ids.append(protest["id"])

    booked_hearing = fx.schedule_hearing(
        protest_ids[0],
        hearing_officer_user_id=HEARING_OFFICER_USER_ID,
        scheduled_start_utc=FIRST_HEARING_START,
        scheduled_end_utc=FIRST_HEARING_END,
        room_code="ROOM-A",
    )
    return {
        "vendor_id": vendor["id"],
        "first_protest_id": protest_ids[0],
        "second_protest_id": protest_ids[1],
        "booked_hearing": booked_hearing,
        "booked_hearing_id": booked_hearing["id"],
    }


def _second_hearing_response(protest_id: str, scheduled_end_utc: str):
    """The candidate window on the same officer's docket, in a different room
    so only the docket ceiling can bite."""
    return api_client.create_hearing(
        protest_id,
        fac.hearing_payload(
            HEARING_OFFICER_USER_ID,
            scheduled_start_utc=SECOND_HEARING_START,
            scheduled_end_utc=scheduled_end_utc,
            room_code="ROOM-B",
        ),
        HEARING_OFFICER_HEADERS,
    )


class TestReinstatementPetitionEarliestInstant:
    """The clock compared inclusively against the earliest petition instant."""

    def test_petition_filed_at_exactly_the_earliest_instant_is_accepted(self):
        """A petition filed with the clock parked on the earliest permitted
        instant itself is created rather than refused as premature.

        "And the logical clock must have reached or passed `reinstatement_earliest_petition_utc` — the boundary is inclusive, so filing at exactly that instant is accepted — otherwise the filing is refused with `ERR_PETITION_PREMATURE`."

        Design: Difficulty/boundary_precision_check/reinstatement_petition_accepted_at_exactly_the_earliest_petition_instant
        """
        state = _debar_a_vendor_on_the_default_branch()
        proceeding = state["proceeding"]

        assert proceeding["severity_score"] == pytest.approx(35.00, abs=0.01)
        assert proceeding["debarment_period_months"] == 12
        assert _instant(proceeding["debarment_start_utc"]) == _instant(
            DEBARMENT_DECISION_INSTANT
        )
        assert _instant(proceeding["debarment_end_utc"]) == _instant(
            DEBARMENT_END_INSTANT
        )

        vendor_before = fx.read_vendor(state["vendor_id"])
        assert _instant(
            vendor_before["reinstatement_earliest_petition_utc"]
        ) == _instant(EARLIEST_PETITION_INSTANT)

        fx.set_clock(EARLIEST_PETITION_INSTANT)
        response = _petition_response(state["proceeding_id"], state["vendor_id"])
        petition = validate_success(response, expected_status=201)

        assert petition["status"] == "FILED"
        assert petition["proceeding_id"] == state["proceeding_id"]
        assert _instant(petition["filed_at_utc"]) == _instant(
            EARLIEST_PETITION_INSTANT
        )
        assert petition["months_served_at_filing"] == 6

        vendor_after = fx.read_vendor(state["vendor_id"])
        assert _instant(
            vendor_after["reinstatement_earliest_petition_utc"]
        ) == _instant(petition["filed_at_utc"])
        assert vendor_after["eligibility_status"] == "DEBARRED"

    def test_petition_filed_one_millisecond_before_the_earliest_instant_is_refused(
        self,
    ):
        """A petition filed one millisecond short of the earliest permitted
        instant is refused as premature and no petition row is created.

        "And the logical clock must have reached or passed `reinstatement_earliest_petition_utc` — the boundary is inclusive, so filing at exactly that instant is accepted — otherwise the filing is refused with `ERR_PETITION_PREMATURE`."

        Design: Difficulty/boundary_precision_check/reinstatement_petition_accepted_at_exactly_the_earliest_petition_instant
        """
        state = _debar_a_vendor_on_the_default_branch()

        vendor_before = fx.read_vendor(state["vendor_id"])
        assert _instant(
            vendor_before["reinstatement_earliest_petition_utc"]
        ) == _instant(EARLIEST_PETITION_INSTANT)

        fx.set_clock(ONE_MILLISECOND_EARLIER)
        response = _petition_response(state["proceeding_id"], state["vendor_id"])
        validate_error(
            response,
            ApiErrorId.ERR_PETITION_PREMATURE.value,
            expected_status=409,
        )

        petitions, meta = validate_paginated(
            api_client.list_reinstatement_petitions(
                state["proceeding_id"], OFFICER_HEADERS
            )
        )
        assert petitions == []
        assert meta["total_count"] == 0

        vendor_after = fx.read_vendor(state["vendor_id"])
        assert vendor_after["eligibility_status"] == "DEBARRED"


class TestHearingOfficerDailyDocketCeiling:
    """Cumulative booked minutes inside one UTC calendar day."""

    def test_docket_total_of_exactly_four_hundred_eighty_minutes_is_accepted(self):
        """Two four hour hearings on one officer's docket for the same UTC day
        sum to the ceiling itself and the second booking is created.

        "A total of exactly 480 minutes is permitted; only a strictly greater total is refused."

        Design: Difficulty/boundary_precision_check/hearing_officer_docket_accepted_at_exactly_four_hundred_eighty_minutes
        """
        state = _two_protests_under_review_with_240_minutes_booked()

        response = _second_hearing_response(
            state["second_protest_id"], SECOND_HEARING_END_AT_CEILING
        )
        hearing = validate_success(response, expected_status=201)

        assert hearing["status"] == "SCHEDULED"
        assert hearing["room_code"] == "ROOM-B"
        assert _instant(hearing["scheduled_start_utc"]) == _instant(
            SECOND_HEARING_START
        )
        assert _instant(hearing["scheduled_end_utc"]) == _instant(
            SECOND_HEARING_END_AT_CEILING
        )

        second_protest = fx.read_protest(state["second_protest_id"])
        assert second_protest["status"] == "HEARING_SCHEDULED"

        booked = fx.read_hearing(state["booked_hearing_id"])
        assert booked["status"] == "SCHEDULED"
        assert booked["room_code"] == "ROOM-A"

        for protest_id in (state["first_protest_id"], state["second_protest_id"]):
            rows, meta = validate_paginated(
                api_client.list_hearings(protest_id, OFFICER_HEADERS)
            )
            assert len(rows) == 1
            assert meta["total_count"] == 1

        vendor = fx.read_vendor(state["vendor_id"])
        assert (
            vendor["protest_fee_balance_cents"] == BALANCE_AFTER_TWO_FILINGS_CENTS
        )

    def test_docket_total_of_four_hundred_eighty_one_minutes_is_refused(self):
        """A candidate window one minute longer carries the officer's day to
        481 minutes and the booking is refused.

        "The candidate's own window length in whole minutes is added to that sum, and if the total exceeds 480 minutes the request is refused with `ERR_OFFICER_DOCKET_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/hearing_officer_docket_accepted_at_exactly_four_hundred_eighty_minutes
        """
        state = _two_protests_under_review_with_240_minutes_booked()

        response = _second_hearing_response(
            state["second_protest_id"], SECOND_HEARING_END_ONE_MINUTE_PAST
        )
        validate_error(
            response,
            ApiErrorId.ERR_OFFICER_DOCKET_CAPACITY_EXCEEDED.value,
            expected_status=409,
        )

        second_protest = fx.read_protest(state["second_protest_id"])
        assert second_protest["status"] == "UNDER_REVIEW"

        rows, meta = validate_paginated(
            api_client.list_hearings(state["second_protest_id"], OFFICER_HEADERS)
        )
        assert rows == []
        assert meta["total_count"] == 0

        booked = fx.read_hearing(state["booked_hearing_id"])
        assert booked["status"] == "SCHEDULED"
        assert booked["room_code"] == "ROOM-A"
        assert _instant(booked["scheduled_end_utc"]) == _instant(FIRST_HEARING_END)

        vendor = fx.read_vendor(state["vendor_id"])
        assert (
            vendor["protest_fee_balance_cents"] == BALANCE_AFTER_TWO_FILINGS_CENTS
        )
