"""Operations gated by the state of an entity other than the write target.

Two dependency pairs are exercised, each from both polarities. A bid create is
legal in every respect on its own row and is refused only because the vendor it
names sits outside ELIGIBLE. An award execution is legal in every respect on its
own row and is refused only because a protest on the same solicitation holds an
active stay; once that stay moves, the identical execution succeeds without the
award itself having changed.
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
from test_helpers.test_users import OFFICER_HEADERS, make_vendor_headers

QUESTION_DEADLINE_CLOCK = "2026-08-20T00:00:00Z"
BID_DUE_CLOCK = "2026-08-27T00:00:00Z"

CANDIDATE_BID_PRICE_CENTS = 9000000

WINNING_BID_PRICE_CENTS = 100000000
LOSING_BID_PRICE_CENTS = 100000001
AWARD_BASE_OBLIGATION_CENTS = 100000000
AWARD_ADMINISTRATIVE_FEE_CENTS = 1500000
AWARD_TOTAL_OBLIGATION_CENTS = 101500000
AWARD_IMPROPRIETY_FEE_CENTS = 87538
PROTESTER_DEPOSIT_CENTS = 100000
PROTESTER_BALANCE_AFTER_FILING_CENTS = (
    PROTESTER_DEPOSIT_CENTS - AWARD_IMPROPRIETY_FEE_CENTS
)
URGENCY_JUSTIFICATION = (
    "the culvert failure presents an imminent hazard to the travelling public"
)


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
# Bid -> Vendor
# ---------------------------------------------------------------------------
def _issued_solicitation_and_respondent_vendor(
    interim_suspension: bool,
) -> Dict[str, Any]:
    """An advertised solicitation whose bid window is wide open, plus a vendor
    against whom a debarment notice has issued — with or without the interim
    suspension that moves the vendor out of ELIGIBLE."""
    vendor = fx.create_vendor(
        legal_name="Marberry Structural Steel",
        tax_id="100000017",
        contact_email="v17@example.gov",
    )
    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-CE1",
        title="Overhead Sign Structure Fabrication",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-AISC",
                description="AISC certified fabricator",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="FRAUD",
        aggravating_factor_codes=["FRAUD"],
        mitigating_factor_codes=[],
        interim_suspension=interim_suspension,
    )
    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation["id"],
        "proceeding_id": proceeding["id"],
        "proceeding": proceeding,
    }


def _bid_response(solicitation_id: str, vendor_id: str):
    """A bid whose own preconditions are all satisfied: the solicitation is
    ISSUED, the clock is inside the window and the version pin is fresh."""
    return api_client.create_bid(
        fac.bid_payload(
            solicitation_id,
            vendor_id,
            total_price_cents=CANDIDATE_BID_PRICE_CENTS,
            acknowledged_addendum_sequences=[],
            expected_solicitation_version=fx.solicitation_version(solicitation_id),
        ),
        make_vendor_headers(vendor_id),
    )


# ---------------------------------------------------------------------------
# Award -> Protest
# ---------------------------------------------------------------------------
def _award_pending_stay_with_a_protest_on_file() -> Dict[str, Any]:
    """A notice of award sitting in PENDING_STAY on a solicitation whose losing
    bidder has just filed an award-impropriety protest."""
    winner = fx.create_vendor(
        legal_name="Quarry Bend Concrete",
        tax_id="100000018",
        contact_email="v18@example.gov",
    )
    protester = fx.create_vendor(
        legal_name="Northgate Civil Builders",
        tax_id="100000019",
        contact_email="v19@example.gov",
    )
    fx.fund_vendor(protester["id"], PROTESTER_DEPOSIT_CENTS)

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-CE2",
        title="Emergency Culvert Replacement",
        issuing_agency_code="DOT",
        estimated_value_cents=100000000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-BOND",
                description="five percent bid bond",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    winning_bid = fx.submit_bid(
        solicitation_id, winner["id"], total_price_cents=WINNING_BID_PRICE_CENTS
    )
    losing_bid = fx.submit_bid(
        solicitation_id, protester["id"], total_price_cents=LOSING_BID_PRICE_CENTS
    )

    fx.set_clock(QUESTION_DEADLINE_CLOCK)
    fx.close_question_period(solicitation_id)
    fx.set_clock(BID_DUE_CLOCK)
    fx.open_bids(solicitation_id)

    fx.determine_responsiveness(
        winning_bid["id"], determination="RESPONSIVE", reason_codes=[]
    )
    fx.determine_responsiveness(
        losing_bid["id"], determination="RESPONSIVE", reason_codes=[]
    )
    fx.review_responsibility(
        winning_bid["id"],
        financial_capacity_score=80,
        past_performance_score=85,
        integrity_score=90,
        determination="RESPONSIBLE",
        notes="bonding capacity and references verified",
    )

    award = fx.create_award(solicitation_id, winning_bid["id"])
    protest = fx.file_protest(
        solicitation_id,
        protester["id"],
        grounds_code="AWARD_IMPROPRIETY",
        narrative="the award ignored a mathematically unbalanced bid",
    )
    return {
        "winner_vendor_id": winner["id"],
        "protester_vendor_id": protester["id"],
        "solicitation_id": solicitation_id,
        "winning_bid_id": winning_bid["id"],
        "losing_bid_id": losing_bid["id"],
        "award_id": award["id"],
        "award": award,
        "protest_id": protest["id"],
        "protest": protest,
    }


class TestBidCreationDependsOnVendorEligibility:
    """The write target is a new bid; the controlling entity is the vendor."""

    def test_bid_is_refused_while_the_named_vendor_is_interim_suspended(self):
        """The bid's own preconditions all hold and the create is refused only
        because the vendor it names has been suspended by a debarment notice.

        "A vendor whose `eligibility_status` is anything other than `ELIGIBLE` cannot bid at all, and is refused with `ERR_VENDOR_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/bid_creation_rejected_because_vendor_is_interim_suspended
        """
        state = _issued_solicitation_and_respondent_vendor(interim_suspension=True)

        response = _bid_response(state["solicitation_id"], state["vendor_id"])
        validate_error(
            response,
            ApiErrorId.ERR_VENDOR_NOT_ELIGIBLE.value,
            expected_status=409,
        )

        vendor = fx.read_vendor(state["vendor_id"])
        assert vendor["eligibility_status"] == "SUSPENDED"
        assert vendor["suspension_reason_code"] == "FRAUD"
        assert vendor["active_debarment_id"] == state["proceeding_id"]
        assert vendor["debarment_strike_count"] == 1

        proceeding = fx.read_proceeding(state["proceeding_id"])
        assert proceeding["interim_status"] == "INTERIM_SUSPENDED"
        assert proceeding["severity_score"] == pytest.approx(40.00, abs=0.01)
        assert proceeding["strikes_applied"] == 1
        assert proceeding["status"] == "NOTICE_ISSUED"

        bids, meta = validate_paginated(
            api_client.list_bids(
                OFFICER_HEADERS, params={"solicitation_id": state["solicitation_id"]}
            )
        )
        assert bids == []
        assert meta["total_count"] == 0

        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["status"] == "ISSUED"

    def test_identical_bid_succeeds_while_the_named_vendor_stays_eligible(self):
        """The same bid on the same solicitation is created when the notice of
        proposed debarment left the vendor's eligibility untouched.

        "A vendor whose `eligibility_status` is anything other than `ELIGIBLE` cannot bid at all, and is refused with `ERR_VENDOR_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/bid_creation_rejected_because_vendor_is_interim_suspended
        """
        state = _issued_solicitation_and_respondent_vendor(interim_suspension=False)

        vendor_before = fx.read_vendor(state["vendor_id"])
        assert vendor_before["eligibility_status"] == "ELIGIBLE"
        assert vendor_before["debarment_strike_count"] == 0
        assert vendor_before["active_debarment_id"] is None

        proceeding = fx.read_proceeding(state["proceeding_id"])
        assert proceeding["interim_status"] == "NONE"
        assert proceeding["strikes_applied"] == 0
        assert proceeding["status"] == "NOTICE_ISSUED"

        response = _bid_response(state["solicitation_id"], state["vendor_id"])
        bid = validate_success(response, expected_status=201)

        assert bid["solicitation_id"] == state["solicitation_id"]
        assert bid["vendor_id"] == state["vendor_id"]
        assert bid["total_price_cents"] == CANDIDATE_BID_PRICE_CENTS
        assert bid["responsiveness_status"] == "UNREVIEWED"
        assert bid["responsibility_status"] == "NOT_REVIEWED"

        bids, meta = validate_paginated(
            api_client.list_bids(
                OFFICER_HEADERS, params={"solicitation_id": state["solicitation_id"]}
            )
        )
        assert [row["id"] for row in bids] == [bid["id"]]
        assert meta["total_count"] == 1

        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["status"] == "ISSUED"


class TestAwardExecutionDependsOnTheProtestStay:
    """The write target is the award; the controlling entity is the protest."""

    def test_award_execution_is_refused_while_the_protest_stay_is_active(self):
        """The award is in PENDING_STAY on an AWARD_PENDING solicitation and
        execution is refused only because a protest holds an active stay.

        "It requires the award to be in `PENDING_STAY`, the solicitation to be in `AWARD_PENDING`, and again that no protest on the solicitation has an active stay, else `ERR_AWARD_STAYED`."

        Design: Difficulty/cross_entity_state_dependency/award_execution_unblocked_only_because_the_protest_stay_was_overridden
        """
        state = _award_pending_stay_with_a_protest_on_file()

        award_before = fx.read_award(state["award_id"])
        assert award_before["status"] == "PENDING_STAY"
        assert award_before["base_obligation_cents"] == AWARD_BASE_OBLIGATION_CENTS
        assert (
            award_before["administrative_fee_cents"]
            == AWARD_ADMINISTRATIVE_FEE_CENTS
        )
        assert (
            award_before["award_total_obligation_cents"]
            == AWARD_TOTAL_OBLIGATION_CENTS
        )

        solicitation_before = fx.read_solicitation(state["solicitation_id"])
        assert solicitation_before["status"] == "AWARD_PENDING"

        protest_before = fx.read_protest(state["protest_id"])
        assert protest_before["stay_status"] == "ACTIVE"
        assert protest_before["status"] == "FILED"
        assert protest_before["filing_fee_cents"] == AWARD_IMPROPRIETY_FEE_CENTS

        response = api_client.execute_award(state["award_id"], OFFICER_HEADERS)
        validate_error(
            response, ApiErrorId.ERR_AWARD_STAYED.value, expected_status=409
        )

        award_after = fx.read_award(state["award_id"])
        assert award_after["status"] == "PENDING_STAY"
        assert award_after["executed_at_utc"] is None
        assert (
            award_after["award_total_obligation_cents"]
            == AWARD_TOTAL_OBLIGATION_CENTS
        )

        solicitation_after = fx.read_solicitation(state["solicitation_id"])
        assert solicitation_after["status"] == "AWARD_PENDING"

        protest_after = fx.read_protest(state["protest_id"])
        assert protest_after["stay_status"] == "ACTIVE"
        assert protest_after["status"] == "FILED"

    def test_award_execution_succeeds_once_the_protest_stay_is_overridden(self):
        """The identical execution on the identical award succeeds after the
        officer moves the protest's stay to OVERRIDDEN.

        "A `ProcurementOfficer` may override an active stay on written urgency findings by supplying an `urgency_justification`; the override moves `stay_status` `ACTIVE → OVERRIDDEN`, which re-permits award creation and execution while the merits track continues untouched, requires the protest's `status` to be `FILED`, `UNDER_REVIEW` or `HEARING_SCHEDULED`, and increments the protest's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/award_execution_unblocked_only_because_the_protest_stay_was_overridden
        """
        state = _award_pending_stay_with_a_protest_on_file()

        overridden = fx.override_stay(
            state["protest_id"], urgency_justification=URGENCY_JUSTIFICATION
        )
        assert overridden["stay_status"] == "OVERRIDDEN"
        assert overridden["status"] == "FILED"
        assert overridden["version"] == state["protest"]["version"] + 1

        award_before = fx.read_award(state["award_id"])
        assert award_before["status"] == "PENDING_STAY"

        response = api_client.execute_award(state["award_id"], OFFICER_HEADERS)
        award = validate_success(response, expected_status=200)

        assert award["status"] == "EXECUTED"
        assert award["award_total_obligation_cents"] == AWARD_TOTAL_OBLIGATION_CENTS
        assert _instant(award["executed_at_utc"]) == _instant(BID_DUE_CLOCK)

        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["status"] == "AWARDED"
        assert solicitation["protest_escrow_cents"] == AWARD_IMPROPRIETY_FEE_CENTS

        protest = fx.read_protest(state["protest_id"])
        assert protest["stay_status"] == "OVERRIDDEN"
        assert protest["status"] == "FILED"
        assert protest["fee_refunded_cents"] == 0

        protester = fx.read_vendor(state["protester_vendor_id"])
        assert (
            protester["protest_fee_balance_cents"]
            == PROTESTER_BALANCE_AFTER_FILING_CENTS
        )

        winning_bid = fx.read_bid(state["winning_bid_id"])
        losing_bid = fx.read_bid(state["losing_bid_id"])
        assert winning_bid["responsibility_status"] == "RESPONSIBLE"
        assert losing_bid["responsibility_status"] == "NOT_REVIEWED"
