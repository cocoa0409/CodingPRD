"""Lifecycle transitions: the guarded edges of the solicitation, protest,
hearing, award and vendor machines.

Every scenario here is built from scratch through the public API against an
empty database, walked to the exact state whose next edge is under examination,
and then driven one step further — either into the edge's guard, where the
rejection and the untouched state are pinned, or across the edge, where the
resulting fields and the rows the transition carries with it are pinned.
"""
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
    ADMIN_HEADERS,
    DEBARMENT_AUTHORITY_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    make_vendor_headers,
)

# --------------------------------------------------------------------------
# Canonical instants of the procurement calendar used throughout this file.
# --------------------------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"
QUESTION_DEADLINE = "2026-08-20T00:00:00Z"
ONE_SECOND_BEFORE_QUESTION_DEADLINE = "2026-08-19T23:59:59Z"
BID_DUE = "2026-08-27T00:00:00Z"
ONE_SECOND_BEFORE_BID_DUE = "2026-08-26T23:59:59Z"
HEARING_START = "2026-08-28T09:00:00Z"
HEARING_END = "2026-08-28T11:00:00Z"
ONE_SECOND_BEFORE_HEARING_START = "2026-08-27T23:59:59Z"


# --------------------------------------------------------------------------
# Scenario builders. Each one reproduces one advertised procurement exactly,
# so that the instant, the money and the row counts under examination are all
# pinned rather than inherited from a shared default.
# --------------------------------------------------------------------------
def _requirement(code: str, description: str) -> Dict[str, Any]:
    return {
        "requirement_code": code,
        "description": description,
        "materiality": "MATERIAL",
        "is_waivable": False,
    }


def _draft_without_any_requirement() -> Dict[str, Any]:
    """A DRAFT solicitation whose `mandatory_requirements` list was empty."""
    fx.set_clock(CLOCK_START)
    return fx.create_solicitation(
        solicitation_number="SOL-2238-C07",
        title="Salt Brine Delivery",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc=BID_DUE,
        original_question_deadline_utc=QUESTION_DEADLINE,
        mandatory_requirements=[],
    )


def _issued_solicitation(
    solicitation_number: str,
    title: str,
    requirement_code: str,
    requirement_description: str,
    estimated_value_cents: int = 10000000,
) -> Dict[str, Any]:
    """One advertised solicitation, question period open, nothing filed on it."""
    fx.set_clock(CLOCK_START)
    solicitation = fx.create_solicitation(
        solicitation_number=solicitation_number,
        title=title,
        issuing_agency_code="DOT",
        estimated_value_cents=estimated_value_cents,
        original_bid_due_utc=BID_DUE,
        original_question_deadline_utc=QUESTION_DEADLINE,
        mandatory_requirements=[
            _requirement(requirement_code, requirement_description)
        ],
    )
    return fx.issue_solicitation(solicitation["id"])


def _question_period_closed_without_bids() -> Dict[str, Any]:
    """A solicitation whose question period has closed and which received no
    bid at all, with the clock standing at the bid due instant."""
    solicitation = _issued_solicitation(
        "SOL-2238-C09",
        "Culvert Cleaning Services",
        "REQ-VAC",
        "vacuum truck capacity",
    )
    fx.set_clock(QUESTION_DEADLINE)
    fx.close_question_period(solicitation["id"])
    fx.set_clock(BID_DUE)
    return fx.read_solicitation(solicitation["id"])


def _question_period_closed_with_one_bid_before_due() -> Dict[str, Any]:
    """One sealed bid on file, the question period closed, and the clock one
    second short of the effective bid due instant."""
    vendor = fx.create_vendor(
        legal_name="Meriden Pipe Services",
        tax_id="100000042",
        contact_email="v42@example.gov",
    )
    solicitation = _issued_solicitation(
        "SOL-2238-C10",
        "Storm Sewer Lining",
        "REQ-CIPP",
        "cured in place pipe certification",
    )
    bid = fx.submit_bid(solicitation["id"], vendor["id"], total_price_cents=8000000)

    fx.set_clock(QUESTION_DEADLINE)
    fx.close_question_period(solicitation["id"])
    fx.set_clock(ONE_SECOND_BEFORE_BID_DUE)
    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation["id"],
        "bid_id": bid["id"],
    }


def _already_cancelled_solicitation() -> Dict[str, Any]:
    """An advertised solicitation that has already been cancelled once."""
    solicitation = _issued_solicitation(
        "SOL-2238-C11",
        "Weigh Station Repaving",
        "REQ-MIX",
        "approved asphalt mix design",
    )
    cancelled = fx.cancel_solicitation(
        solicitation["id"],
        cancellation_reason="scope consolidated into a district-wide contract",
    )
    return cancelled


def _prospective_bidder_on_an_issued_solicitation(
    solicitation_number: str,
    title: str,
    requirement_code: str,
    requirement_description: str,
    tax_id: str,
    legal_name: str,
    question_text: str,
) -> Dict[str, Any]:
    """A funded vendor whose only nexus with an advertised solicitation is one
    pending written question — the prospective-bidder posture."""
    vendor = fx.create_vendor(
        legal_name=legal_name,
        tax_id=tax_id,
        contact_email="v{}@example.gov".format(tax_id[-2:]),
    )
    fx.fund_vendor(vendor["id"], 100000)
    solicitation = _issued_solicitation(
        solicitation_number, title, requirement_code, requirement_description
    )
    question = fx.submit_question(
        solicitation["id"], vendor["id"], question_text=question_text
    )
    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation["id"],
        "question": question,
    }


def _protest_with_scheduled_hearing(
    solicitation_number: str,
    title: str,
    requirement_code: str,
    requirement_description: str,
    tax_id: str,
    legal_name: str,
    question_text: str,
    narrative: str,
    document_ref: str,
) -> Dict[str, Any]:
    """A solicitation-impropriety protest carried to HEARING_SCHEDULED on a
    record holding exactly one agency report."""
    state = _prospective_bidder_on_an_issued_solicitation(
        solicitation_number,
        title,
        requirement_code,
        requirement_description,
        tax_id,
        legal_name,
        question_text,
    )
    protest = fx.file_protest(
        state["solicitation_id"],
        state["vendor_id"],
        grounds_code="SOLICITATION_IMPROPRIETY",
        narrative=narrative,
    )
    fx.add_record_item(
        protest["id"], item_type="AGENCY_REPORT", document_ref=document_ref
    )
    hearing = fx.schedule_hearing(
        protest["id"],
        hearing_officer_user_id=HEARING_OFFICER_USER_ID,
        scheduled_start_utc=HEARING_START,
        scheduled_end_utc=HEARING_END,
        room_code="ROOM-A",
    )
    state["protest_id"] = protest["id"]
    state["hearing_id"] = hearing["id"]
    return state


def _award_pending_with_notice_of_award() -> Dict[str, Any]:
    """A single-bid procurement found responsive and responsible, sitting in
    AWARD_PENDING behind a notice of award in PENDING_STAY."""
    vendor = fx.create_vendor(
        legal_name="Quailfield Paving",
        tax_id="100000046",
        contact_email="v46@example.gov",
    )
    solicitation = _issued_solicitation(
        "SOL-2238-C15",
        "Interchange Ramp Widening",
        "REQ-BOND",
        "five percent bid bond",
        estimated_value_cents=100000000,
    )
    bid = fx.submit_bid(
        solicitation["id"], vendor["id"], total_price_cents=100000000
    )

    fx.set_clock(QUESTION_DEADLINE)
    fx.close_question_period(solicitation["id"])
    fx.set_clock(BID_DUE)
    fx.open_bids(solicitation["id"])

    fx.determine_responsiveness(
        bid["id"], headers=OFFICER_HEADERS, determination="RESPONSIVE", reason_codes=[]
    )
    fx.review_responsibility(
        bid["id"],
        headers=REVIEWER_HEADERS,
        financial_capacity_score=80,
        past_performance_score=85,
        integrity_score=90,
        determination="RESPONSIBLE",
        notes="bonding and references verified",
    )
    award = fx.create_award(solicitation["id"], bid["id"])
    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation["id"],
        "bid_id": bid["id"],
        "award_id": award["id"],
        "award": award,
    }


def _debarred_vendor_with_a_filed_petition() -> Dict[str, Any]:
    """A vendor debarred for twelve months on the default branch, which has
    served past the reinstatement instant and filed a petition."""
    fx.set_clock(CLOCK_START)
    vendor = fx.create_vendor(
        legal_name="Rushmere Bridge Repair",
        tax_id="100000047",
        contact_email="v47@example.gov",
    )
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="REPEATED_NONPERFORMANCE",
        aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    fx.set_clock("2026-08-16T00:00:00Z")
    fx.hold_debarment_hearing(
        proceeding["id"], hearing_summary="no response filed; default branch recorded"
    )
    proceeding = fx.decide_debarment(
        proceeding["id"],
        outcome="DEBARRED",
        rationale="repeated nonperformance established",
    )

    fx.set_clock("2027-03-01T00:00:00Z")
    petition = fx.file_petition(
        proceeding["id"],
        vendor["id"],
        remediation_evidence_codes=["TRAINING_COMPLETED", "COMPLIANCE_AUDIT_PASSED"],
        narrative="field supervisors retrained and an independent audit passed",
    )
    return {
        "vendor_id": vendor["id"],
        "proceeding_id": proceeding["id"],
        "proceeding": proceeding,
        "petition_id": petition["id"],
        "petition": petition,
    }


def _grant_the_petition(petition_id: str) -> Dict[str, Any]:
    response = api_client.decide_reinstatement_petition(
        petition_id,
        fac.petition_decision_payload(
            outcome="GRANTED",
            decision_rationale=(
                "remediation is documented and the required portion of the "
                "period has been served"
            ),
        ),
        DEBARMENT_AUTHORITY_HEADERS,
    )
    return validate_success(response)


# ==========================================================================
# Advertising a solicitation
# ==========================================================================
class TestAdvertisingRequiresAtLeastOneMandatoryRequirement:
    def test_issuance_is_refused_when_the_solicitation_carries_no_requirement(self):
        """Two preconditions guard it: the solicitation must carry at least one mandatory requirement, otherwise `ERR_NO_MANDATORY_REQUIREMENTS`; and the `original_question_deadline_utc` must still lie strictly in the future relative to the logical clock, otherwise `ERR_INVALID_SOLICITATION_STATE` — there is no point advertising a question period that has already expired.

        The draft was created with an empty requirements list, so the first of
        those two preconditions fails and none of the fields that advertising
        would have stamped are populated.

        Design: Corner/state_machines/corner_solicitation_issue_rejected_without_any_mandatory_requirement
        """
        solicitation = _draft_without_any_requirement()

        response = api_client.issue_solicitation(solicitation["id"], OFFICER_HEADERS)
        validate_error(response, ApiErrorId.ERR_NO_MANDATORY_REQUIREMENTS.value, 422)

        stored = fx.read_solicitation(solicitation["id"])
        assert stored["status"] == "DRAFT"
        assert stored.get("issued_by_user_id") is None
        assert stored.get("effective_bid_due_utc") is None

    def test_the_refused_issuance_writes_nothing_at_all(self):
        """Third, a cascade never partially applies: if any step of the originating operation fails a check, nothing is written at all.

        The draft's `version` is the value it carried before the refused
        attempt, and a second solicitation that does carry a requirement is
        advertised from the very same clock instant, which shows the refusal
        was about the requirements list and not about the calendar.

        Design: Corner/state_machines/corner_solicitation_issue_rejected_without_any_mandatory_requirement
        """
        solicitation = _draft_without_any_requirement()
        version_before = solicitation["version"]

        response = api_client.issue_solicitation(solicitation["id"], OFFICER_HEADERS)
        validate_error(response, ApiErrorId.ERR_NO_MANDATORY_REQUIREMENTS.value, 422)

        stored = fx.read_solicitation(solicitation["id"])
        assert stored["version"] == version_before
        assert stored["status"] == "DRAFT"
        assert stored.get("issued_by_user_id") is None

        comparison = _issued_solicitation(
            "SOL-2238-C07B",
            "Salt Brine Delivery Comparison Lot",
            "REQ-BRINE",
            "brine concentration certificate",
        )
        assert comparison["status"] == "ISSUED"


# ==========================================================================
# Closing the question period
# ==========================================================================
class TestClosingTheQuestionPeriodWaitsForTheDeadline:
    def test_closing_one_second_early_is_refused(self):
        """Closing the question period moves the solicitation `ISSUED → QUESTION_PERIOD_CLOSED` on an officer's action, and requires the logical clock to have reached or passed `question_deadline_utc`; an attempt made too early is refused with `ERR_QUESTION_PERIOD_OPEN`.

        The clock stands at 2026-08-19T23:59:59Z, one second short of the
        2026-08-20T00:00:00Z deadline, so the window is still open and the
        solicitation stays advertised.

        Design: Corner/state_machines/corner_close_question_period_rejected_while_the_window_is_still_open
        """
        solicitation = _issued_solicitation(
            "SOL-2238-C08",
            "Winter Sand Stockpile",
            "REQ-GRAD",
            "gradation certificate",
        )
        fx.set_clock(ONE_SECOND_BEFORE_QUESTION_DEADLINE)

        response = api_client.close_question_period(
            solicitation["id"], OFFICER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_QUESTION_PERIOD_OPEN.value, 409)

        stored = fx.read_solicitation(solicitation["id"])
        assert stored["status"] == "ISSUED"
        assert stored["question_deadline_utc"].startswith("2026-08-20T00:00:00")

    def test_closing_at_exactly_the_deadline_instant_succeeds(self):
        """Closing the question period moves the solicitation `ISSUED → QUESTION_PERIOD_CLOSED` on an officer's action, and requires the logical clock to have reached or passed `question_deadline_utc`; an attempt made too early is refused with `ERR_QUESTION_PERIOD_OPEN`.

        The same call that was refused one second early is accepted once the
        clock reads exactly 2026-08-20T00:00:00Z, which is what makes the
        comparison inclusive of the deadline instant itself.

        Design: Corner/state_machines/corner_close_question_period_rejected_while_the_window_is_still_open
        """
        solicitation = _issued_solicitation(
            "SOL-2238-C08",
            "Winter Sand Stockpile",
            "REQ-GRAD",
            "gradation certificate",
        )
        fx.set_clock(ONE_SECOND_BEFORE_QUESTION_DEADLINE)
        early = api_client.close_question_period(solicitation["id"], OFFICER_HEADERS)
        validate_error(early, ApiErrorId.ERR_QUESTION_PERIOD_OPEN.value, 409)

        fx.set_clock(QUESTION_DEADLINE)
        response = api_client.close_question_period(
            solicitation["id"], OFFICER_HEADERS
        )
        closed = validate_success(response)

        assert closed["status"] == "QUESTION_PERIOD_CLOSED"
        assert closed["question_deadline_utc"].startswith("2026-08-20T00:00:00")


# ==========================================================================
# Opening the bids
# ==========================================================================
class TestOpeningBidsWithAnEmptyBidField:
    def test_opening_bids_is_refused_when_not_one_bid_was_received(self):
        """It requires the logical clock to have reached or passed `effective_bid_due_utc`, else `ERR_BID_PERIOD_OPEN`, and it requires at least one bid on the solicitation whose `responsiveness_status` is not `WITHDRAWN`, else `ERR_NO_BIDS_RECEIVED` — the empty-collection edge is a hard stop, not a no-op.

        The bid due instant has arrived and the question period is closed, so
        the only failing precondition is the empty bid field, and the public
        opening leaves no trace on the solicitation.

        Design: Corner/state_machines/corner_open_bids_rejected_when_no_bids_were_received
        """
        solicitation = _question_period_closed_without_bids()

        response = api_client.open_bids(solicitation["id"], OFFICER_HEADERS)
        validate_error(response, ApiErrorId.ERR_NO_BIDS_RECEIVED.value, 409)

        stored = fx.read_solicitation(solicitation["id"])
        assert stored["status"] == "QUESTION_PERIOD_CLOSED"
        assert stored.get("bids_opened_at_utc") is None
        assert stored.get("apparent_low_bid_id") is None


class TestOpeningBidsBeforeTheBidDueInstant:
    def test_opening_bids_one_second_early_names_the_open_bid_period(self):
        """It requires the logical clock to have reached or passed `effective_bid_due_utc`, else `ERR_BID_PERIOD_OPEN`, and it requires at least one bid on the solicitation whose `responsiveness_status` is not `WITHDRAWN`, else `ERR_NO_BIDS_RECEIVED` — the empty-collection edge is a hard stop, not a no-op.

        One sealed bid is on file, so the empty-collection stop cannot be the
        reason for the refusal; the clock standing at 2026-08-26T23:59:59Z is,
        and the solicitation stays in the state it was in.

        Design: Corner/state_machines/corner_open_bids_rejected_before_the_effective_bid_due_instant
        """
        state = _question_period_closed_with_one_bid_before_due()

        response = api_client.open_bids(state["solicitation_id"], OFFICER_HEADERS)
        error = validate_error(response, ApiErrorId.ERR_BID_PERIOD_OPEN.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_NO_BIDS_RECEIVED.value

        stored = fx.read_solicitation(state["solicitation_id"])
        assert stored["status"] == "QUESTION_PERIOD_CLOSED"
        assert stored.get("bids_opened_at_utc") is None

    def test_the_sealed_bid_is_left_unpriced_by_the_refused_opening(self):
        """Opening stamps `bids_opened_at_utc` from the logical clock, which becomes the trigger event for one flavour of protest timeliness, and prices every non-withdrawn bid under the **as-read variant** of the evaluated-price rule: each such bid's `evaluated_price_cents` is set to exactly its `total_price_cents`, and its `informality_loading_cents` is set to 0.

        Because the opening was refused, none of that pricing ran: the bid's
        `evaluated_price_cents` is still the null it was created with and its
        responsiveness dimension is untouched.

        Design: Corner/state_machines/corner_open_bids_rejected_before_the_effective_bid_due_instant
        """
        state = _question_period_closed_with_one_bid_before_due()

        response = api_client.open_bids(state["solicitation_id"], OFFICER_HEADERS)
        validate_error(response, ApiErrorId.ERR_BID_PERIOD_OPEN.value, 409)

        bid = fx.read_bid(state["bid_id"])
        assert bid.get("evaluated_price_cents") is None
        assert bid["total_price_cents"] == 8000000
        assert bid["responsiveness_status"] == "UNREVIEWED"
        assert bid["informality_loading_cents"] == 0


# ==========================================================================
# Cancelling a procurement
# ==========================================================================
class TestCancellingAnAlreadyCancelledProcurement:
    def test_a_second_cancellation_is_refused(self):
        """A `ProcurementOfficer` may cancel a live procurement, supplying a `cancellation_reason`, from any of `ISSUED`, `QUESTION_PERIOD_CLOSED`, `BIDS_OPENED`, `EVALUATION` and `AWARD_PENDING`; from any other state there is no such transition and the attempt fails with `ERR_INVALID_SOLICITATION_STATE`.

        A solicitation already in `CANCELLED` is in none of those five live
        states, so the repeat attempt has no edge to travel and the recorded
        reason stays the one given the first time.

        Design: Corner/state_machines/corner_cancel_on_an_already_cancelled_solicitation_is_rejected
        """
        cancelled = _already_cancelled_solicitation()
        assert cancelled["status"] == "CANCELLED"

        response = api_client.cancel_solicitation(
            cancelled["id"],
            fac.cancel_payload(cancellation_reason="duplicate cancellation attempt"),
            OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_SOLICITATION_STATE.value, 409)

        stored = fx.read_solicitation(cancelled["id"])
        assert stored["status"] == "CANCELLED"

    def test_the_refused_second_cancellation_does_not_advance_the_version(self):
        """Third, a cascade never partially applies: if any step of the originating operation fails a check, nothing is written at all.

        The version the solicitation carried after the accepted cancellation is
        the version it still carries after the refused one.

        Design: Corner/state_machines/corner_cancel_on_an_already_cancelled_solicitation_is_rejected
        """
        cancelled = _already_cancelled_solicitation()
        version_after_cancel = cancelled["version"]

        response = api_client.cancel_solicitation(
            cancelled["id"],
            fac.cancel_payload(cancellation_reason="duplicate cancellation attempt"),
            OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_SOLICITATION_STATE.value, 409)

        stored = fx.read_solicitation(cancelled["id"])
        assert stored["version"] == version_after_cancel


# ==========================================================================
# Filing a protest
# ==========================================================================
class TestProtestOpensFiledBehindAnActiveStay:
    def test_a_newly_filed_protest_opens_in_filed_with_every_outcome_field_empty(self):
        """The server stamps `filed_at_utc` from the logical clock and creates the protest with `status` `FILED`, `stay_status` `NONE`, `decision_outcome` null, `remedy_code` null, `decided_at_utc` null, `record_item_count` 0 and `fee_refunded_cents` 0.

        Nothing has been filed into the agency record yet and no officer has
        ruled, so every field the decision would later populate is still empty.

        Design: Corner/state_machines/corner_protest_initial_state_is_filed_with_an_active_stay
        """
        state = _prospective_bidder_on_an_issued_solicitation(
            "SOL-2238-C12",
            "Flashing Beacon Installation",
            "REQ-RRFB",
            "rectangular rapid flashing beacon model",
            "100000043",
            "Northvale Signals",
            "will an alternate beacon model be considered equal?",
        )

        response = api_client.create_protest(
            fac.protest_payload(
                state["solicitation_id"],
                state["vendor_id"],
                grounds_code="SOLICITATION_IMPROPRIETY",
                narrative="the named beacon model is a sole source",
            ),
            make_vendor_headers(state["vendor_id"]),
        )
        protest = validate_success(response, expected_status=201)

        assert protest["status"] == "FILED"
        assert protest.get("decision_outcome") is None
        assert protest.get("remedy_code") is None
        assert protest.get("decided_at_utc") is None
        assert protest["record_item_count"] == 0
        assert protest["fee_refunded_cents"] == 0
        assert protest["filed_at_utc"].startswith("2026-08-01T00:00:00")

    def test_the_stay_arms_itself_on_a_solicitation_that_is_still_advertised(self):
        """When the protest is filed while the solicitation is in `ISSUED`, `QUESTION_PERIOD_CLOSED`, `BIDS_OPENED`, `EVALUATION` or `AWARD_PENDING` and no award on that solicitation is `EXECUTED`, `stay_status` moves `NONE → ACTIVE`, and while it is `ACTIVE` both award creation and award execution on that solicitation are refused with `ERR_AWARD_STAYED`.

        The protested solicitation is `ISSUED` and carries no award at all, so
        the stay arms itself in the same request that creates the protest.

        Design: Corner/state_machines/corner_protest_initial_state_is_filed_with_an_active_stay
        """
        state = _prospective_bidder_on_an_issued_solicitation(
            "SOL-2238-C12",
            "Flashing Beacon Installation",
            "REQ-RRFB",
            "rectangular rapid flashing beacon model",
            "100000043",
            "Northvale Signals",
            "will an alternate beacon model be considered equal?",
        )

        protest = fx.file_protest(
            state["solicitation_id"],
            state["vendor_id"],
            grounds_code="SOLICITATION_IMPROPRIETY",
            narrative="the named beacon model is a sole source",
        )

        assert protest["stay_status"] == "ACTIVE"
        assert fx.read_protest(protest["id"])["stay_status"] == "ACTIVE"

    def test_a_pending_question_confers_prospective_bidder_standing(self):
        """Alternatively, and only for the `SOLICITATION_IMPROPRIETY` ground, a protester that filed a question submission on the solicitation whose `status` is `PENDING` or `ANSWERED` has standing as a `PROSPECTIVE_BIDDER`.

        The protester never bid; its whole nexus with the procurement is the one
        pending written question, and the impropriety ground is the one ground
        that basis reaches. The deadline is one day before the 2026-08-27
        effective bid due instant, and no challenged bid is named.

        Design: Corner/state_machines/corner_protest_initial_state_is_filed_with_an_active_stay
        """
        state = _prospective_bidder_on_an_issued_solicitation(
            "SOL-2238-C12",
            "Flashing Beacon Installation",
            "REQ-RRFB",
            "rectangular rapid flashing beacon model",
            "100000043",
            "Northvale Signals",
            "will an alternate beacon model be considered equal?",
        )
        assert state["question"]["status"] == "PENDING"

        protest = fx.file_protest(
            state["solicitation_id"],
            state["vendor_id"],
            grounds_code="SOLICITATION_IMPROPRIETY",
            narrative="the named beacon model is a sole source",
        )

        assert protest["standing_basis"] == "PROSPECTIVE_BIDDER"
        assert protest.get("challenged_bid_id") is None
        assert protest["timeliness_deadline_utc"].startswith("2026-08-26T00:00:00")

    def test_the_filing_fee_moves_from_the_purse_into_the_solicitation_escrow(self):
        """On success the fee is subtracted from the protester's `protest_fee_balance_cents` and added to the solicitation's `protest_escrow_cents`, and both the vendor's `version` and the solicitation's `version` increment by 1.

        On a 10,000,000-cent solicitation the impropriety fee is 25000 base
        plus 7500 ad valorem at 0.00075 plus a 3138-cent grounds surcharge,
        which is 35638 cents; the purse held 100000 cents, so 64362 cents are
        left unencumbered.

        Design: Corner/state_machines/corner_protest_initial_state_is_filed_with_an_active_stay
        """
        state = _prospective_bidder_on_an_issued_solicitation(
            "SOL-2238-C12",
            "Flashing Beacon Installation",
            "REQ-RRFB",
            "rectangular rapid flashing beacon model",
            "100000043",
            "Northvale Signals",
            "will an alternate beacon model be considered equal?",
        )

        protest = fx.file_protest(
            state["solicitation_id"],
            state["vendor_id"],
            grounds_code="SOLICITATION_IMPROPRIETY",
            narrative="the named beacon model is a sole source",
        )

        assert protest["filing_fee_cents"] == 35638
        assert fx.read_vendor(state["vendor_id"])["protest_fee_balance_cents"] == 64362
        assert (
            fx.read_solicitation(state["solicitation_id"])["protest_escrow_cents"]
            == 35638
        )


# ==========================================================================
# Convening a protest hearing
# ==========================================================================
class TestConveningWaitsForTheScheduledStart:
    def test_convening_one_second_early_is_refused(self):
        """Convening moves the hearing `SCHEDULED → CONVENED`, requires the logical clock to have reached or passed `scheduled_start_utc` (else `ERR_HEARING_NOT_YET_STARTED`), requires the protest's `record_item_count` to be at least 1 (else `ERR_AGENCY_RECORD_INCOMPLETE`), stamps `convened_at_utc` from the logical clock, and increments the hearing's `version` by 1.

        The record already holds the agency report, so the only unmet
        precondition is the calendar: the clock stands at 2026-08-27T23:59:59Z
        against a 2026-08-28T09:00:00Z start, and both the hearing and the
        protest are left where they were.

        Design: Corner/state_machines/corner_convene_rejected_before_the_scheduled_start_instant
        """
        state = _protest_with_scheduled_hearing(
            "SOL-2238-C13",
            "Perimeter Fence Rehabilitation",
            "REQ-GALV",
            "galvanizing thickness",
            "100000044",
            "Oakbridge Fence",
            "is hot-dip galvanizing mandatory?",
            "the galvanizing thickness exceeds any commercially available product",
            "AR-C13-001",
        )
        fx.set_clock(ONE_SECOND_BEFORE_HEARING_START)

        response = api_client.convene_hearing(
            state["hearing_id"], HEARING_OFFICER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_HEARING_NOT_YET_STARTED.value, 409)

        hearing = fx.read_hearing(state["hearing_id"])
        assert hearing["status"] == "SCHEDULED"
        assert hearing.get("convened_at_utc") is None
        assert fx.read_protest(state["protest_id"])["status"] == "HEARING_SCHEDULED"


# ==========================================================================
# Concluding a protest hearing
# ==========================================================================
class TestConcludingNeedsATwoItemAgencyRecord:
    def test_concluding_on_a_single_item_record_is_refused(self):
        """Concluding moves the hearing `CONVENED → CONCLUDED`, requires the protest's `record_item_count` to be at least 2 (else `ERR_AGENCY_RECORD_INCOMPLETE`), stamps `concluded_at_utc` from the logical clock, snapshots `record_items_reviewed_count` as the protest's `record_item_count` at that moment, and drives the protest `HEARING_SCHEDULED → UNDER_REVIEW`.

        Exactly one agency report was filed, which was enough to convene at the
        scheduled start instant but is one item short of what closing the
        hearing record demands.

        Design: Corner/state_machines/corner_conclude_rejected_when_the_agency_record_holds_only_one_item
        """
        state = _protest_with_scheduled_hearing(
            "SOL-2238-C14",
            "Rest Area Site Grading",
            "REQ-EROS",
            "erosion control plan",
            "100000045",
            "Pinehollow Grading",
            "who obtains the erosion control permit?",
            "the permit responsibility is unassigned",
            "AR-C14-001",
        )
        fx.set_clock(HEARING_START)
        convened = fx.convene_hearing(state["hearing_id"])
        assert convened["status"] == "CONVENED"

        response = api_client.conclude_hearing(
            state["hearing_id"], HEARING_OFFICER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_AGENCY_RECORD_INCOMPLETE.value, 409)

        hearing = fx.read_hearing(state["hearing_id"])
        assert hearing["status"] == "CONVENED"
        assert hearing["convened_at_utc"].startswith("2026-08-28T09:00:00")
        assert hearing.get("concluded_at_utc") is None
        assert hearing["record_items_reviewed_count"] == 0

    def test_the_protest_stays_on_the_hearing_docket_after_the_refusal(self):
        """Concluding moves the hearing `CONVENED → CONCLUDED`, requires the protest's `record_item_count` to be at least 2 (else `ERR_AGENCY_RECORD_INCOMPLETE`), stamps `concluded_at_utc` from the logical clock, snapshots `record_items_reviewed_count` as the protest's `record_item_count` at that moment, and drives the protest `HEARING_SCHEDULED → UNDER_REVIEW`.

        Because the conclusion was refused, the return of the merits dimension
        to review never happened: the protest is still on the hearing docket
        with its single record item.

        Design: Corner/state_machines/corner_conclude_rejected_when_the_agency_record_holds_only_one_item
        """
        state = _protest_with_scheduled_hearing(
            "SOL-2238-C14",
            "Rest Area Site Grading",
            "REQ-EROS",
            "erosion control plan",
            "100000045",
            "Pinehollow Grading",
            "who obtains the erosion control permit?",
            "the permit responsibility is unassigned",
            "AR-C14-001",
        )
        fx.set_clock(HEARING_START)
        fx.convene_hearing(state["hearing_id"])

        response = api_client.conclude_hearing(
            state["hearing_id"], HEARING_OFFICER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_AGENCY_RECORD_INCOMPLETE.value, 409)

        protest = fx.read_protest(state["protest_id"])
        assert protest["record_item_count"] == 1
        assert protest["status"] == "HEARING_SCHEDULED"


# ==========================================================================
# Cancelling a procurement that already carries a notice of award
# ==========================================================================
class TestCancellationClearsTheFieldAndVoidsThePendingAward:
    def test_the_pending_award_is_voided_for_the_cancellation_reason(self):
        """Every award on the solicitation whose `status` is `PENDING_STAY` becomes `VOID` with `void_reason_code` `SOLICITATION_CANCELLED`, its `version` incrementing by 1.

        The award was sitting in `PENDING_STAY` behind no protest at all, so the
        reason recorded on it is the cancellation and neither of the other two
        void reasons; the money already computed on the notice of award — a
        100,000,000-cent base, a 1,500,000-cent administrative fee and no
        reserve — is preserved on the voided row, which was never executed.

        Design: Corner/state_machines/corner_solicitation_cancel_cascades_bids_nonresponsive_and_voids_pending_award
        """
        state = _award_pending_with_notice_of_award()
        assert state["award"]["status"] == "PENDING_STAY"

        response = api_client.cancel_solicitation(
            state["solicitation_id"],
            fac.cancel_payload(cancellation_reason="federal participation withdrawn"),
            OFFICER_HEADERS,
        )
        cancelled = validate_success(response)
        assert cancelled["status"] == "CANCELLED"

        award = fx.read_award(state["award_id"])
        assert award["status"] == "VOID"
        assert award["void_reason_code"] == "SOLICITATION_CANCELLED"
        assert award["void_reason_code"] != "PROTEST_SUSTAINED"
        assert award["void_reason_code"] != "APPARENT_LOW_BIDDER_CHANGED"
        assert award["award_total_obligation_cents"] == 101500000
        assert award.get("executed_at_utc") is None

    def test_the_responsive_bid_is_marked_nonresponsive_on_an_officer_determination(
        self,
    ):
        """Every bid on the solicitation whose `responsiveness_status` is `UNREVIEWED` or `RESPONSIVE` becomes `NONRESPONSIVE` with `OFFICER_DETERMINATION` appended to its `nonresponsive_reason_codes`, each bid's `version` incrementing by 1.

        Cancellation clears the field in three moves, and reverting the
        responsibility dimension is not one of them: the bid that had been
        reviewed responsible is still recorded as responsible after the
        procurement is cancelled.

        Design: Corner/state_machines/corner_solicitation_cancel_cascades_bids_nonresponsive_and_voids_pending_award
        """
        state = _award_pending_with_notice_of_award()

        response = api_client.cancel_solicitation(
            state["solicitation_id"],
            fac.cancel_payload(cancellation_reason="federal participation withdrawn"),
            OFFICER_HEADERS,
        )
        validate_success(response)

        bid = fx.read_bid(state["bid_id"])
        assert bid["responsiveness_status"] == "NONRESPONSIVE"
        assert "OFFICER_DETERMINATION" in bid["nonresponsive_reason_codes"]
        assert bid["responsibility_status"] == "RESPONSIBLE"

    def test_the_apparent_low_bidder_is_cleared_from_the_solicitation(self):
        """The solicitation's `apparent_low_bid_id` is set to null and its own `version` increments by 1.

        The single bid was the apparent low bidder right up to the cancellation,
        so the cleared pointer is visible only because the field was populated
        before the officer cancelled.

        Design: Corner/state_machines/corner_solicitation_cancel_cascades_bids_nonresponsive_and_voids_pending_award
        """
        state = _award_pending_with_notice_of_award()
        before = fx.read_solicitation(state["solicitation_id"])
        assert before["apparent_low_bid_id"] == state["bid_id"]

        response = api_client.cancel_solicitation(
            state["solicitation_id"],
            fac.cancel_payload(cancellation_reason="federal participation withdrawn"),
            OFFICER_HEADERS,
        )
        cancelled = validate_success(response)

        assert cancelled["status"] == "CANCELLED"
        assert cancelled.get("apparent_low_bid_id") is None
        assert cancelled["version"] == before["version"] + 1


# ==========================================================================
# The vendor cycle: eligible, debarred, eligible again
# ==========================================================================
class TestReinstatementClosesTheVendorCycle:
    def test_a_granted_petition_returns_the_vendor_to_eligible(self):
        """A grant moves the petition `FILED → GRANTED`, stamps the same two fields, and drives the vendor `DEBARRED → ELIGIBLE`: the proceeding's `strikes_applied` moves from 1 back to 0 so the vendor's `debarment_strike_count` decreases by 1, and `active_debarment_id`, `suspension_reason_code` and `reinstatement_earliest_petition_utc` are all cleared to null.

        The vendor was debarred for twelve months on a severity of 35 and has
        served past the reinstatement instant; the grant therefore returns it to
        exactly the posture it was registered in, strike included.

        Design: Corner/state_machines/corner_vendor_cycle_returns_to_eligible_on_a_granted_reinstatement
        """
        state = _debarred_vendor_with_a_filed_petition()
        assert state["petition"]["status"] == "FILED"
        assert fx.read_vendor(state["vendor_id"])["eligibility_status"] == "DEBARRED"
        assert fx.read_vendor(state["vendor_id"])["debarment_strike_count"] == 1

        petition = _grant_the_petition(state["petition_id"])

        assert petition["status"] == "GRANTED"
        assert petition["decided_at_utc"].startswith("2027-03-01T00:00:00")

        vendor = fx.read_vendor(state["vendor_id"])
        assert vendor["eligibility_status"] == "ELIGIBLE"
        assert vendor["debarment_strike_count"] == 0
        assert vendor.get("active_debarment_id") is None
        assert vendor.get("suspension_reason_code") is None
        assert vendor.get("reinstatement_earliest_petition_utc") is None

    def test_months_served_at_filing_counts_whole_calendar_months(self):
        """The petition is created in `status` `FILED`, with `filed_at_utc` stamped from the logical clock, `months_served_at_filing` computed as the number of whole calendar months elapsed from the proceeding's `debarment_start_utc` to that filing instant, and `decided_at_utc` and `decision_rationale` both null.

        The debarment began at 2026-08-16T00:00:00Z and the petition was filed
        at 2027-03-01T00:00:00Z, which is six whole calendar months plus a part
        month, so the served count is six and the grant does not disturb it.

        Design: Corner/state_machines/corner_vendor_cycle_returns_to_eligible_on_a_granted_reinstatement
        """
        state = _debarred_vendor_with_a_filed_petition()
        assert state["petition"]["months_served_at_filing"] == 6
        assert state["petition"].get("decided_at_utc") is None
        assert state["petition"].get("decision_rationale") is None

        petition = _grant_the_petition(state["petition_id"])

        assert petition["months_served_at_filing"] == 6
        assert petition["filed_at_utc"].startswith("2027-03-01T00:00:00")

    def test_the_proceeding_stays_debarred_while_its_strike_is_returned(self):
        """A **debarment** outcome moves the proceeding `HEARING_HELD → DEBARRED`, which is terminal, and begins Cascade B.

        Reinstatement does not rewrite the history of the debarment: the
        proceeding keeps its terminal status, its twelve-month period and its
        2027-08-16 end instant, and only the strike it was carrying is returned.

        Design: Corner/state_machines/corner_vendor_cycle_returns_to_eligible_on_a_granted_reinstatement
        """
        state = _debarred_vendor_with_a_filed_petition()
        assert state["proceeding"]["strikes_applied"] == 1
        assert state["proceeding"]["severity_score"] == pytest.approx(35.00, abs=0.01)
        assert state["proceeding"]["debarment_period_months"] == 12

        _grant_the_petition(state["petition_id"])

        proceeding = fx.read_proceeding(state["proceeding_id"])
        assert proceeding["status"] == "DEBARRED"
        assert proceeding["strikes_applied"] == 0
        assert proceeding["debarment_period_months"] == 12
        assert proceeding["debarment_end_utc"].startswith("2027-08-16T00:00:00")

    def test_the_reinstated_vendor_drops_off_the_debarred_vendor_list(self):
        """The reader may also supply `include_suspended`: when it is false or omitted, only vendors whose `eligibility_status` is `DEBARRED` are in scope; when it is true, vendors whose `eligibility_status` is `SUSPENDED` are in scope as well.

        The reinstated vendor is `ELIGIBLE`, which is neither of those two
        scopes, so the public list that named it while it was debarred no
        longer does.

        Design: Corner/state_machines/corner_vendor_cycle_returns_to_eligible_on_a_granted_reinstatement
        """
        state = _debarred_vendor_with_a_filed_petition()
        listed_before, _ = validate_paginated(
            api_client.list_debarred_vendors(ADMIN_HEADERS)
        )
        assert state["vendor_id"] in [row["id"] for row in listed_before]

        _grant_the_petition(state["petition_id"])

        listed_after, meta_after = validate_paginated(
            api_client.list_debarred_vendors(ADMIN_HEADERS)
        )
        assert state["vendor_id"] not in [row["id"] for row in listed_after]
        assert meta_after["total_count"] == 0
