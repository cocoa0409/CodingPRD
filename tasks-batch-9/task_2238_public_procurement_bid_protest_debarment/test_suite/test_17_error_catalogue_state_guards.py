"""State guards that refuse a write and leave the target row exactly where it was.

Every test walks the workflow forward through the public API against an empty
database, drives the logical clock explicitly, provokes one refusal, and then
re-reads the rows the refused write would have moved to prove nothing was
written. Where a neighbouring rule would plausibly have produced a different
error id, the returned id is asserted to differ from it, and where the refusal
is only a matter of ordering the control call that does succeed is exercised
too.
"""
from typing import Any, Dict, List, Optional, Tuple

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
    DEBARMENT_AUTHORITY_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    make_vendor_headers,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _requirement(code: str, description: str) -> Dict[str, Any]:
    """One MATERIAL, non-waivable original requirement."""
    return fac.requirement_payload(
        requirement_code=code,
        description=description,
        materiality="MATERIAL",
        is_waivable=False,
    )


def _issued_solicitation(
    solicitation_number: str,
    title: str,
    requirement_code: str,
    requirement_description: str,
    estimated_value_cents: int = 10000000,
) -> Dict[str, Any]:
    """A solicitation drafted with one material requirement and advertised."""
    solicitation = fx.create_solicitation(
        solicitation_number=solicitation_number,
        title=title,
        issuing_agency_code="DOT",
        estimated_value_cents=estimated_value_cents,
        original_bid_due_utc="2026-08-27T00:00:00Z",
        original_question_deadline_utc="2026-08-20T00:00:00Z",
        mandatory_requirements=[
            _requirement(requirement_code, requirement_description)
        ],
    )
    return fx.issue_solicitation(solicitation["id"])


def _rows_and_total(response) -> Tuple[List[Dict[str, Any]], int]:
    rows, meta = validate_paginated(response)
    return rows, meta["total_count"]


def _prospective_bidder_protest(
    vendor_legal_name: str,
    vendor_tax_id: str,
    vendor_email: str,
    solicitation_number: str,
    solicitation_title: str,
    requirement_code: str,
    requirement_description: str,
    question_text: str,
    narrative: str,
    fee_balance_cents: int = 100000,
) -> Dict[str, Any]:
    """A funded vendor that asked a written question on an advertised
    solicitation and then protested the solicitation itself, which gives it
    standing as a prospective bidder and leaves the protest in FILED."""
    vendor = fx.create_vendor(
        legal_name=vendor_legal_name,
        tax_id=vendor_tax_id,
        contact_email=vendor_email,
    )
    vendor_id = vendor["id"]
    fx.fund_vendor(vendor_id, fee_balance_cents)

    solicitation = _issued_solicitation(
        solicitation_number,
        solicitation_title,
        requirement_code,
        requirement_description,
    )
    solicitation_id = solicitation["id"]
    fx.submit_question(solicitation_id, vendor_id, question_text=question_text)
    protest = fx.file_protest(
        solicitation_id,
        vendor_id,
        grounds_code="SOLICITATION_IMPROPRIETY",
        narrative=narrative,
    )
    return {
        "vendor_id": vendor_id,
        "solicitation_id": solicitation_id,
        "protest": protest,
        "protest_id": protest["id"],
    }


def _submit_sealed_bid(
    vendor: Dict[str, Any],
    solicitation_id: str,
    total_price_cents: int,
    acknowledged_addendum_sequences: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """File one sealed bid before the deadline; the caller opens the bids later."""
    return fx.submit_bid(
        solicitation_id,
        vendor["id"],
        total_price_cents=total_price_cents,
        acknowledged_addendum_sequences=(
            acknowledged_addendum_sequences
            if acknowledged_addendum_sequences is not None
            else []
        ),
    )


def _close_and_open(solicitation_id: str) -> Dict[str, Any]:
    """Advance the calendar to the question deadline, close the question
    period, advance to the bid due instant and open the bids."""
    fx.set_clock("2026-08-20T00:00:00Z")
    fx.close_question_period(solicitation_id)
    fx.set_clock("2026-08-27T00:00:00Z")
    return fx.open_bids(solicitation_id)


# ---------------------------------------------------------------------------
# The responsiveness determination is recorded once and only once
# ---------------------------------------------------------------------------
class TestResponsivenessDeterminationIsOnceOnly:
    def test_second_determination_on_an_already_responsive_bid_is_refused(self):
        """The bid's `responsiveness_status` must be `UNREVIEWED` — a bid that is `WITHDRAWN` or already determined is refused with `ERR_INVALID_BID_STATE` — and the owning solicitation must be in `BIDS_OPENED` or `EVALUATION`, else `ERR_INVALID_SOLICITATION_STATE`.

        Design: Corner/errors/corner_second_responsiveness_determination_on_a_bid_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        vendor = fx.create_vendor(
            legal_name="Pemberton Milling",
            tax_id="100000070",
            contact_email="v70@example.gov",
        )
        solicitation = _issued_solicitation(
            "SOL-2238-C31",
            "Pavement Milling District Two",
            "REQ-MILL",
            "milling machine width",
        )
        solicitation_id = solicitation["id"]
        bid = _submit_sealed_bid(vendor, solicitation_id, 8000000)
        _close_and_open(solicitation_id)
        fx.determine_responsiveness(
            bid["id"], determination="RESPONSIVE", reason_codes=[]
        )

        response = api_client.determine_responsiveness(
            bid["id"],
            fac.responsiveness_payload(
                determination="NONRESPONSIVE",
                reason_codes=["OFFICER_DETERMINATION"],
                corrected_total_price_cents=8100000,
            ),
            OFFICER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_INVALID_BID_STATE.value, expected_status=409
        )

        stored_bid = fx.read_bid(bid["id"])
        assert stored_bid["responsiveness_status"] == "RESPONSIVE"
        assert stored_bid["nonresponsive_reason_codes"] == []
        assert stored_bid["corrected_total_price_cents"] is None
        assert stored_bid["total_price_cents"] == 8000000
        assert stored_bid["evaluated_price_cents"] == 8000000
        assert stored_bid["informality_loading_cents"] == 0

        stored_solicitation = fx.read_solicitation(solicitation_id)
        assert stored_solicitation["apparent_low_bid_id"] == bid["id"]
        assert stored_solicitation["status"] == "EVALUATION"


# ---------------------------------------------------------------------------
# A hearing may only be docketed once the agency report has opened the review
# ---------------------------------------------------------------------------
class TestHearingSchedulingRequiresAProtestUnderReview:
    def test_scheduling_a_hearing_on_a_freshly_filed_protest_is_refused(self):
        """Scheduling a hearing is a `HearingOfficer` action that advances the protest `UNDER_REVIEW → HEARING_SCHEDULED` and creates a `ProtestHearing` in `status` `SCHEDULED`. Protest state admissibility, on hearing scheduling, decision issuance, withdrawal, stay override and record-item filing — `ERR_INVALID_PROTEST_STATE`.

        Design: Corner/errors/corner_hearing_scheduling_on_a_filed_protest_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        state = _prospective_bidder_protest(
            vendor_legal_name="Quarryside Aggregates",
            vendor_tax_id="100000071",
            vendor_email="v71@example.gov",
            solicitation_number="SOL-2238-C32",
            solicitation_title="Aggregate Supply Term Contract",
            requirement_code="REQ-SOURCE",
            requirement_description="approved quarry source",
            question_text="may an unlisted quarry be approved?",
            narrative="the approved source list is closed",
        )
        protest_id = state["protest_id"]
        assert state["protest"]["status"] == "FILED"
        assert state["protest"]["record_item_count"] == 0

        response = api_client.create_hearing(
            protest_id,
            fac.hearing_payload(
                HEARING_OFFICER_USER_ID,
                scheduled_start_utc="2026-08-28T09:00:00Z",
                scheduled_end_utc="2026-08-28T11:00:00Z",
                room_code="ROOM-A",
            ),
            HEARING_OFFICER_HEADERS,
        )
        error = validate_error(
            response, ApiErrorId.ERR_INVALID_PROTEST_STATE.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_AGENCY_RECORD_INCOMPLETE.value

        stored_protest = fx.read_protest(protest_id)
        assert stored_protest["status"] == "FILED"
        assert stored_protest["record_item_count"] == 0

        _, total = _rows_and_total(
            api_client.list_hearings(protest_id, OFFICER_HEADERS)
        )
        assert total == 0


# ---------------------------------------------------------------------------
# The hearing record closes only from the convened bench
# ---------------------------------------------------------------------------
class TestConcludingRequiresAConvenedHearing:
    def test_concluding_a_hearing_that_was_never_convened_is_refused(self):
        """Concluding moves the hearing `CONVENED → CONCLUDED`, requires the protest's `record_item_count` to be at least 2 (else `ERR_AGENCY_RECORD_INCOMPLETE`), stamps `concluded_at_utc` from the logical clock, snapshots `record_items_reviewed_count` as the protest's `record_item_count` at that moment, and drives the protest `HEARING_SCHEDULED → UNDER_REVIEW`. Hearing state admissibility, on convening, continuing and concluding — `ERR_INVALID_HEARING_STATE`.

        Design: Corner/errors/corner_conclude_on_a_scheduled_hearing_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        state = _prospective_bidder_protest(
            vendor_legal_name="Ridgeline Guardrail",
            vendor_tax_id="100000072",
            vendor_email="v72@example.gov",
            solicitation_number="SOL-2238-C33",
            solicitation_title="Guardrail Term Maintenance",
            requirement_code="REQ-CREW",
            requirement_description="two certified crews",
            question_text="is one crew acceptable in the first year?",
            narrative="the two crew minimum excludes small firms",
        )
        protest_id = state["protest_id"]
        fx.add_record_item(
            protest_id, item_type="AGENCY_REPORT", document_ref="AR-C33-001"
        )
        hearing = fx.schedule_hearing(
            protest_id,
            hearing_officer_user_id=HEARING_OFFICER_USER_ID,
            scheduled_start_utc="2026-08-28T09:00:00Z",
            scheduled_end_utc="2026-08-28T11:00:00Z",
            room_code="ROOM-A",
        )
        hearing_id = hearing["id"]
        assert fx.read_protest(protest_id)["record_item_count"] == 1

        response = api_client.conclude_hearing(hearing_id, HEARING_OFFICER_HEADERS)
        error = validate_error(
            response, ApiErrorId.ERR_INVALID_HEARING_STATE.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_AGENCY_RECORD_INCOMPLETE.value

        stored_hearing = fx.read_hearing(hearing_id)
        assert stored_hearing["status"] == "SCHEDULED"
        assert stored_hearing["convened_at_utc"] is None
        assert stored_hearing["concluded_at_utc"] is None
        assert stored_hearing["record_items_reviewed_count"] == 0
        assert fx.read_protest(protest_id)["status"] == "HEARING_SCHEDULED"


# ---------------------------------------------------------------------------
# The merits decision of a debarment starts only from the held hearing
# ---------------------------------------------------------------------------
class TestDebarmentDecisionRequiresAHeldHearing:
    def test_decision_issued_straight_from_the_notice_is_refused(self):
        """**The merits decision** is issued by the `DebarmentAuthority` from `HEARING_HELD`, supplying the `outcome` and a `rationale`. Proceeding state admissibility, on the response, the hearing, the decision and petition filing — `ERR_INVALID_PROCEEDING_STATE`.

        Design: Corner/errors/corner_debarment_decision_without_a_hearing_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        vendor = fx.create_vendor(
            legal_name="Stonebridge Paving",
            tax_id="100000073",
            contact_email="v73@example.gov",
        )
        vendor_id = vendor["id"]
        proceeding = fx.open_proceeding(
            vendor_id,
            cause_code="BID_RIGGING",
            aggravating_factor_codes=["BID_RIGGING", "FALSE_CERTIFICATION"],
            mitigating_factor_codes=[],
            interim_suspension=False,
        )
        proceeding_id = proceeding["id"]
        fx.set_clock("2026-08-16T00:00:00Z")

        decision_payload = fac.debarment_decision_payload(
            outcome="DEBARRED", rationale="skipping the hearing step"
        )
        response = api_client.decide_debarment(
            proceeding_id, decision_payload, DEBARMENT_AUTHORITY_HEADERS
        )
        error = validate_error(
            response,
            ApiErrorId.ERR_INVALID_PROCEEDING_STATE.value,
            expected_status=409,
        )
        assert (
            error["error_id"]
            != ApiErrorId.ERR_DEBARMENT_HEARING_RIGHTS_NOT_EXHAUSTED.value
        )
        assert error["error_id"] != ApiErrorId.ERR_SEVERITY_BELOW_DEBARMENT_FLOOR.value

        stored = fx.read_proceeding(proceeding_id)
        assert stored["status"] == "NOTICE_ISSUED"
        assert stored["decided_at_utc"] is None
        assert stored["debarment_period_months"] == 0
        assert stored["strikes_applied"] == 0
        assert fx.read_vendor(vendor_id)["eligibility_status"] == "ELIGIBLE"

        # The identical decision succeeds once the default-branch hearing is on
        # the record, which is what makes the refusal one of ordering alone.
        fx.hold_debarment_hearing(
            proceeding_id,
            hearing_summary="no response filed; default branch recorded",
        )
        decided = validate_success(
            api_client.decide_debarment(
                proceeding_id, decision_payload, DEBARMENT_AUTHORITY_HEADERS
            ),
            expected_status=200,
        )
        assert decided["status"] == "DEBARRED"
        assert decided["severity_score"] == pytest.approx(60.00, abs=0.01)
        assert decided["debarment_period_months"] == 36


# ---------------------------------------------------------------------------
# A granted reinstatement petition is decided once, and the strike is returned once
# ---------------------------------------------------------------------------
class TestGrantedPetitionIsTerminal:
    def test_second_decision_on_a_granted_petition_is_refused(self):
        """A petition already `GRANTED` or `DENIED` cannot be decided again and the attempt is refused with `ERR_INVALID_PETITION_STATE`.

        Design: Corner/errors/corner_second_decision_on_a_granted_petition_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        vendor = fx.create_vendor(
            legal_name="Thornbury Fencing",
            tax_id="100000074",
            contact_email="v74@example.gov",
        )
        vendor_id = vendor["id"]
        proceeding = fx.open_proceeding(
            vendor_id,
            cause_code="REPEATED_NONPERFORMANCE",
            aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
            mitigating_factor_codes=[],
            interim_suspension=False,
        )
        proceeding_id = proceeding["id"]
        fx.set_clock("2026-08-16T00:00:00Z")
        fx.hold_debarment_hearing(
            proceeding_id,
            hearing_summary="no response filed; default branch recorded",
        )
        fx.decide_debarment(
            proceeding_id,
            outcome="DEBARRED",
            rationale="repeated nonperformance established",
        )

        fx.set_clock("2027-03-01T00:00:00Z")
        petition = fx.file_petition(
            proceeding_id,
            vendor_id,
            remediation_evidence_codes=["MANAGEMENT_REPLACED", "TRAINING_COMPLETED"],
            narrative="new management and full retraining",
        )
        petition_id = petition["id"]
        fx.decide_petition(
            petition_id, outcome="GRANTED", decision_rationale="remediation documented"
        )

        response = api_client.decide_reinstatement_petition(
            petition_id,
            fac.petition_decision_payload(
                outcome="DENIED",
                decision_rationale="attempting to reverse the grant",
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_INVALID_PETITION_STATE.value, expected_status=409
        )

        stored_petition = fx.read_petition(petition_id)
        assert stored_petition["status"] == "GRANTED"
        assert stored_petition["decision_rationale"] == "remediation documented"

        stored_vendor = fx.read_vendor(vendor_id)
        assert stored_vendor["eligibility_status"] == "ELIGIBLE"
        assert stored_vendor["debarment_strike_count"] == 0

        stored_proceeding = fx.read_proceeding(proceeding_id)
        assert stored_proceeding["strikes_applied"] == 0
        assert stored_proceeding["status"] == "DEBARRED"


# ---------------------------------------------------------------------------
# A protest is decided on a hearing that actually closed
# ---------------------------------------------------------------------------
class TestProtestDecisionRequiresAConcludedHearing:
    def test_decision_on_a_paper_record_with_no_hearing_is_refused(self):
        """Four preconditions apply identically to both outcomes: the protest must be in `UNDER_REVIEW`; at least one hearing on the protest must have `status` `CONCLUDED`, else `ERR_HEARING_NOT_CONCLUDED`; the protest's `record_item_count` must be at least 2, else `ERR_AGENCY_RECORD_INCOMPLETE`; and the deciding `X-User-ID` must differ from the solicitation's `issued_by_user_id`, else `ERR_HEARING_OFFICER_CONFLICT`.

        Design: Corner/errors/corner_protest_decision_without_a_concluded_hearing_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        state = _prospective_bidder_protest(
            vendor_legal_name="Ullswater Sealcoating",
            vendor_tax_id="100000075",
            vendor_email="v75@example.gov",
            solicitation_number="SOL-2238-C34",
            solicitation_title="Parking Lot Sealcoating",
            requirement_code="REQ-SEAL",
            requirement_description="coal tar free sealant",
            question_text="which sealant products qualify?",
            narrative="the sealant restriction is proprietary",
        )
        protest_id = state["protest_id"]
        vendor_id = state["vendor_id"]
        solicitation_id = state["solicitation_id"]

        fx.add_record_item(
            protest_id, item_type="AGENCY_REPORT", document_ref="AR-C34-001"
        )
        fx.add_record_item(
            protest_id,
            headers=make_vendor_headers(vendor_id),
            item_type="PROTESTER_SUBMISSION",
            document_ref="PS-C34-001",
        )
        assert fx.read_protest(protest_id)["record_item_count"] == 2

        response = api_client.decide_protest(
            protest_id,
            fac.protest_decision_payload(
                outcome="DENIED",
                rationale="deciding on the paper record alone",
                remedy_code="NONE",
            ),
            HEARING_OFFICER_HEADERS,
        )
        error = validate_error(
            response, ApiErrorId.ERR_HEARING_NOT_CONCLUDED.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_AGENCY_RECORD_INCOMPLETE.value

        stored_protest = fx.read_protest(protest_id)
        assert stored_protest["status"] == "UNDER_REVIEW"
        assert stored_protest["stay_status"] == "ACTIVE"
        assert stored_protest["decision_outcome"] is None
        assert stored_protest["decided_at_utc"] is None
        assert stored_protest["fee_refunded_cents"] == 0
        assert stored_protest["filing_fee_cents"] == 35638

        assert fx.read_solicitation(solicitation_id)["protest_escrow_cents"] == 35638
        assert fx.read_vendor(vendor_id)["protest_fee_balance_cents"] == 64362


# ---------------------------------------------------------------------------
# An unacknowledged material addendum bars responsiveness rather than pricing it
# ---------------------------------------------------------------------------
class TestMaterialAddendumMustBeAcknowledged:
    def test_responsive_finding_on_an_unacknowledged_material_addendum_is_refused(self):
        """If any such requirement is unacknowledged, the bid cannot be found responsive and the request is refused with `ERR_MATERIAL_REQUIREMENT_UNMET` (HTTP 422).

        Design: Corner/errors/corner_responsive_determination_with_an_unacknowledged_material_addendum_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        vendor = fx.create_vendor(
            legal_name="Vestry Lane Builders",
            tax_id="100000076",
            contact_email="v76@example.gov",
        )
        solicitation = _issued_solicitation(
            "SOL-2238-C35",
            "Maintenance Garage Addition",
            "REQ-SEAL-ENG",
            "engineer of record seal",
        )
        solicitation_id = solicitation["id"]

        addendum = fx.add_addendum(
            solicitation_id,
            summary="adds a fire suppression requirement",
            extends_bid_due_by_days=0,
            acknowledgment_required=True,
            new_requirement_codes=[
                fac.requirement_payload(
                    requirement_code="REQ-FIRE",
                    description="wet pipe suppression system",
                    materiality="MATERIAL",
                    is_waivable=False,
                )
            ],
        )
        assert addendum["sequence_number"] == 1
        assert addendum["adds_material_requirement"] is True

        bid = _submit_sealed_bid(
            vendor, solicitation_id, 8000000, acknowledged_addendum_sequences=[]
        )
        _close_and_open(solicitation_id)

        response = api_client.determine_responsiveness(
            bid["id"],
            fac.responsiveness_payload(determination="RESPONSIVE", reason_codes=[]),
            OFFICER_HEADERS,
        )
        validate_error(
            response,
            ApiErrorId.ERR_MATERIAL_REQUIREMENT_UNMET.value,
            expected_status=422,
        )

        stored_bid = fx.read_bid(bid["id"])
        assert stored_bid["responsiveness_status"] == "UNREVIEWED"
        assert stored_bid["evaluated_price_cents"] == 8000000
        assert stored_bid["informality_loading_cents"] == 0
        assert stored_bid["responsiveness_decided_by_user_id"] is None

        # The same defect recorded as the nonresponsiveness it is does land.
        determined = validate_success(
            api_client.determine_responsiveness(
                bid["id"],
                fac.responsiveness_payload(
                    determination="NONRESPONSIVE",
                    reason_codes=["ADDENDUM_NOT_ACKNOWLEDGED"],
                ),
                OFFICER_HEADERS,
            ),
            expected_status=200,
        )
        assert determined["responsiveness_status"] == "NONRESPONSIVE"
        assert "ADDENDUM_NOT_ACKNOWLEDGED" in determined["nonresponsive_reason_codes"]


# ---------------------------------------------------------------------------
# The sealed-bid cutoff is strict to the millisecond
# ---------------------------------------------------------------------------
class TestBidCutoffIsStrict:
    def test_bid_one_millisecond_after_the_effective_due_instant_is_refused(self):
        """The clock must not yet have passed the current `effective_bid_due_utc`; a bid arriving strictly after that instant is refused with `ERR_BID_DEADLINE_PASSED`.

        Design: Corner/errors/corner_bid_submitted_after_the_effective_bid_due_instant_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        vendor = fx.create_vendor(
            legal_name="Whitlock Bridge Painting",
            tax_id="100000077",
            contact_email="v77@example.gov",
        )
        vendor_id = vendor["id"]
        solicitation = _issued_solicitation(
            "SOL-2238-C36",
            "Overpass Painting",
            "REQ-SSPC",
            "SSPC QP1 certification",
        )
        solicitation_id = solicitation["id"]
        pinned_version = fx.solicitation_version(solicitation_id)

        bid_payload = fac.bid_payload(
            solicitation_id,
            vendor_id,
            total_price_cents=8000000,
            acknowledged_addendum_sequences=[],
            expected_solicitation_version=pinned_version,
        )

        fx.set_clock("2026-08-27T00:00:00.001Z")
        response = api_client.create_bid(bid_payload, make_vendor_headers(vendor_id))
        error = validate_error(
            response, ApiErrorId.ERR_BID_DEADLINE_PASSED.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_SOLICITATION_STATE.value

        stored_solicitation = fx.read_solicitation(solicitation_id)
        assert stored_solicitation["status"] == "ISSUED"
        assert stored_solicitation["version"] == pinned_version

        _, total = _rows_and_total(
            api_client.list_bids(
                OFFICER_HEADERS, params={"solicitation_id": solicitation_id}
            )
        )
        assert total == 0

        # At exactly the advertised instant the same bid is on time.
        fx.set_clock("2026-08-27T00:00:00Z")
        created = validate_success(
            api_client.create_bid(bid_payload, make_vendor_headers(vendor_id)),
            expected_status=201,
        )
        assert created["responsiveness_status"] == "UNREVIEWED"
        assert created["total_price_cents"] == 8000000


# ---------------------------------------------------------------------------
# Responsibility is reviewed against the apparent low bidder and no other
# ---------------------------------------------------------------------------
class TestResponsibilityReviewTargetsTheApparentLowBidder:
    def test_review_of_the_second_lowest_responsive_bid_is_refused(self):
        """The bid must be the one named by the solicitation's `apparent_low_bid_id`, else `ERR_NOT_APPARENT_LOW_BIDDER`.

        Design: Corner/errors/corner_responsibility_review_of_a_non_apparent_low_bidder_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        vendor_a = fx.create_vendor(
            legal_name="Amberton Concrete",
            tax_id="100000079",
            contact_email="v79@example.gov",
        )
        vendor_b = fx.create_vendor(
            legal_name="Brightwater Concrete",
            tax_id="100000080",
            contact_email="v80@example.gov",
        )
        solicitation = _issued_solicitation(
            "SOL-2238-C38",
            "Approach Slab Replacement",
            "REQ-CURE",
            "accelerated curing plan",
        )
        solicitation_id = solicitation["id"]

        low_bid = _submit_sealed_bid(vendor_a, solicitation_id, 7000000)
        high_bid = _submit_sealed_bid(vendor_b, solicitation_id, 9000000)
        _close_and_open(solicitation_id)
        fx.determine_responsiveness(
            low_bid["id"], determination="RESPONSIVE", reason_codes=[]
        )
        fx.determine_responsiveness(
            high_bid["id"], determination="RESPONSIVE", reason_codes=[]
        )

        before = fx.read_bid(high_bid["id"])
        assert before["responsiveness_status"] == "RESPONSIVE"
        assert before["responsibility_status"] == "NOT_REVIEWED"

        response = api_client.create_responsibility_review(
            high_bid["id"],
            fac.responsibility_review_payload(
                financial_capacity_score=90,
                past_performance_score=90,
                integrity_score=90,
                determination="RESPONSIBLE",
                notes="reviewing the second lowest bidder",
            ),
            REVIEWER_HEADERS,
        )
        error = validate_error(
            response, ApiErrorId.ERR_NOT_APPARENT_LOW_BIDDER.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_BID_STATE.value

        stored_solicitation = fx.read_solicitation(solicitation_id)
        assert stored_solicitation["apparent_low_bid_id"] == low_bid["id"]
        assert stored_solicitation["status"] == "EVALUATION"

        _, total = _rows_and_total(
            api_client.list_responsibility_reviews(high_bid["id"], OFFICER_HEADERS)
        )
        assert total == 0
        assert fx.read_bid(high_bid["id"])["responsibility_status"] == "NOT_REVIEWED"


# ---------------------------------------------------------------------------
# An addendum answers only the questions of its own solicitation
# ---------------------------------------------------------------------------
class TestAddendumAnswersOnlyItsOwnQuestions:
    def test_addendum_citing_a_question_from_another_solicitation_is_refused(self):
        """A named question must belong to the same solicitation as the addendum, else `ERR_QUESTION_NOT_ON_SOLICITATION`, and must resolve at all, else `ERR_QUESTION_NOT_FOUND`.

        Design: Corner/errors/corner_addendum_answering_a_question_from_another_solicitation_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        vendor = fx.create_vendor(
            legal_name="Cranfield Signals",
            tax_id="100000081",
            contact_email="v81@example.gov",
        )
        amended = _issued_solicitation(
            "SOL-2238-C39",
            "Signal Timing Study",
            "REQ-PE",
            "licensed traffic engineer",
        )
        other = _issued_solicitation(
            "SOL-2238-C40",
            "Signal Detection Retrofit",
            "REQ-DETECT",
            "radar detection units",
        )
        amended_id = amended["id"]
        other_id = other["id"]
        question = fx.submit_question(
            other_id, vendor["id"], question_text="are video detection units acceptable?"
        )

        response = api_client.create_addendum(
            amended_id,
            fac.addendum_payload(
                summary="answers the detection question",
                extends_bid_due_by_days=0,
                acknowledgment_required=True,
                new_requirement_codes=[],
                answers_question_ids=[question["id"]],
            ),
            OFFICER_HEADERS,
        )
        error = validate_error(
            response,
            ApiErrorId.ERR_QUESTION_NOT_ON_SOLICITATION.value,
            expected_status=422,
        )
        assert error["error_id"] != ApiErrorId.ERR_QUESTION_NOT_FOUND.value

        assert fx.read_solicitation(amended_id)["addendum_count"] == 0
        assert fx.read_solicitation(other_id)["addendum_count"] == 0

        addenda, total = _rows_and_total(
            api_client.list_addenda(amended_id, OFFICER_HEADERS)
        )
        assert total == 0
        assert addenda == []

        questions, _ = _rows_and_total(
            api_client.list_questions(other_id, OFFICER_HEADERS)
        )
        stored_question = fx.find_by_id(questions, question["id"])
        assert stored_question["status"] == "PENDING"
        assert stored_question["answered_via_addendum_sequence"] is None
        assert stored_question["answer_summary"] is None
