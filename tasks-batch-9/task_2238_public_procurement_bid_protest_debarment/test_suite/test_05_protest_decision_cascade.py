"""Cascade A: the chain a corrective-action protest decision sets off.

One sustained decision on corrective-action grounds walks outward through five
distinct entity types — the protest itself, the notice of award on the protested
solicitation, the solicitation, the bids on it, and the responsibility reviews
recorded against those bids. Every row is built from scratch through the public
API against an empty database, and the logical clock is driven explicitly
because the decision instant is what several of the stamped fields carry.

The whole chain must be observable in the single decision response and in reads
taken immediately afterwards, since consistency in this system is immediate.
"""
from datetime import datetime
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    OFFICER_HEADERS,
    make_vendor_headers,
)

# --------------------------------------------------------------------------
# The calendar this chain runs on
# --------------------------------------------------------------------------
QUESTION_DEADLINE_UTC = "2026-08-20T00:00:00Z"
BID_DUE_UTC = "2026-08-27T00:00:00Z"
HEARING_START_UTC = "2026-08-28T09:00:00Z"
HEARING_END_UTC = "2026-08-28T11:00:00Z"

# --------------------------------------------------------------------------
# The pinned figures of this procurement
# --------------------------------------------------------------------------
ESTIMATED_VALUE_CENTS = 100000000
LOW_BID_CENTS = 100000000
SECOND_BID_CENTS = 100000001
PURSE_CENTS = 200000

# 25,000 flat base + 50,000 ad valorem (100,000,000 x 0.00050) + 12,538
# grounds surcharge (25,000 x 0.5015 = 12,537.5, rounded half-up).
FILING_FEE_CENTS = 87538

# 80 x 0.3 + 85 x 0.4 + 90 x 0.3 under the STANDARD profile, no strike penalty.
COMPOSITE_SCORE = 85.00


# --------------------------------------------------------------------------
# Local helpers
# --------------------------------------------------------------------------
def _instant(value: Any) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating either a fractional-second or
    a whole-second rendering."""
    assert isinstance(value, str), "expected an ISO 8601 string, got {!r}".format(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_same_instant(actual: Any, expected: str, label: str) -> None:
    assert _instant(actual) == _instant(expected), "{}: expected {}, got {!r}".format(
        label, expected, actual
    )


def _read_review(bid_id: str, review_id: str) -> Dict[str, Any]:
    """The one responsibility review recorded against a bid, read back through
    the list endpoint."""
    rows, _meta = validate_paginated(
        api_client.list_responsibility_reviews(bid_id, OFFICER_HEADERS)
    )
    return fx.find_by_id(rows, review_id)


def _setup_award_pending_protest_ready_for_decision() -> Dict[str, Any]:
    """A solicitation in AWARD_PENDING with a notice of award in PENDING_STAY,
    against which the second-lowest bidder has filed an award-impropriety
    protest whose hearing has already been convened and concluded."""
    fx.reset_clock()

    low_vendor = fx.create_vendor(
        legal_name="Trenholm Grading Co",
        tax_id="100000008",
        contact_email="v8@example.gov",
    )
    protester = fx.create_vendor(
        legal_name="Ashgrove Site Services",
        tax_id="100000009",
        contact_email="v9@example.gov",
    )
    low_vendor_id = low_vendor["id"]
    protester_vendor_id = protester["id"]
    fx.fund_vendor(protester_vendor_id, PURSE_CENTS)

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-TC1",
        title="Regional Salt Storage Domes",
        issuing_agency_code="DOT",
        estimated_value_cents=ESTIMATED_VALUE_CENTS,
        original_bid_due_utc=BID_DUE_UTC,
        original_question_deadline_utc=QUESTION_DEADLINE_UTC,
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-BOND",
                description="five percent bid bond",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    low_bid = fx.submit_bid(
        solicitation_id, low_vendor_id, total_price_cents=LOW_BID_CENTS
    )
    second_bid = fx.submit_bid(
        solicitation_id, protester_vendor_id, total_price_cents=SECOND_BID_CENTS
    )

    fx.set_clock(QUESTION_DEADLINE_UTC)
    fx.close_question_period(solicitation_id)
    fx.set_clock(BID_DUE_UTC)
    fx.open_bids(solicitation_id)

    fx.determine_responsiveness(low_bid["id"], determination="RESPONSIVE")
    fx.determine_responsiveness(second_bid["id"], determination="RESPONSIVE")

    review = fx.review_responsibility(
        low_bid["id"],
        financial_capacity_score=80,
        past_performance_score=85,
        integrity_score=90,
        determination="RESPONSIBLE",
        notes="audited statements and three comparable projects",
    )

    award = fx.create_award(solicitation_id, low_bid["id"])

    protest = fx.file_protest(
        solicitation_id,
        protester_vendor_id,
        grounds_code="AWARD_IMPROPRIETY",
        narrative="the notice of award rested on an unbalanced unit price analysis",
    )
    protest_id = protest["id"]

    fx.add_record_item(
        protest_id,
        headers=OFFICER_HEADERS,
        item_type="AGENCY_REPORT",
        document_ref="AR-TC1-001",
    )
    fx.add_record_item(
        protest_id,
        headers=make_vendor_headers(protester_vendor_id),
        item_type="PROTESTER_SUBMISSION",
        document_ref="PS-TC1-001",
    )

    hearing = fx.schedule_hearing(
        protest_id,
        hearing_officer_user_id=HEARING_OFFICER_USER_ID,
        scheduled_start_utc=HEARING_START_UTC,
        scheduled_end_utc=HEARING_END_UTC,
        room_code="ROOM-A",
    )
    fx.set_clock(HEARING_START_UTC)
    fx.convene_hearing(hearing["id"])
    fx.conclude_hearing(hearing["id"])

    return {
        "low_vendor_id": low_vendor_id,
        "protester_vendor_id": protester_vendor_id,
        "solicitation_id": solicitation_id,
        "low_bid_id": low_bid["id"],
        "second_bid_id": second_bid["id"],
        "review_id": review["id"],
        "award_id": award["id"],
        "protest_id": protest_id,
        "hearing_id": hearing["id"],
    }


def _sustain_on_corrective_action(protest_id: str) -> Dict[str, Any]:
    """The single trigger call: one sustained decision ordering corrective
    action, whose response must already reflect hop 1 of the chain."""
    return validate_success(
        api_client.decide_protest(
            protest_id,
            fac.protest_decision_payload(
                outcome="SUSTAINED",
                rationale="the unit price analysis was not documented in the record",
                remedy_code="CORRECTIVE_ACTION",
            ),
            HEARING_OFFICER_HEADERS,
        )
    )


# ===========================================================================
# Hops 1 and 2 — the protest, the fee ledger and the notice of award
# ===========================================================================
class TestCorrectiveActionCascadeFirstHops:
    def test_hop_one_records_the_outcome_and_returns_the_whole_filing_fee(self):
        """Hop 1 records the outcome: `status` and `decision_outcome` both become `SUSTAINED`, `remedy_code` takes the supplied remedy, `decided_at_utc` is stamped, `stay_status` moves to `LIFTED` from `ACTIVE` or `OVERRIDDEN`, and the fee is returned in full — `fee_refunded_cents` is set to the whole `filing_fee_cents`, that amount is subtracted from the solicitation's `protest_escrow_cents` and added back to the protester's `protest_fee_balance_cents`.

        Design: Difficulty/transitive_cascade/corrective_action_protest_decision_cascade_depth_five
        """
        state = _setup_award_pending_protest_ready_for_decision()

        # The stay was live and the fee escrowed before the decision issued.
        before = fx.read_protest(state["protest_id"])
        assert before["stay_status"] == "ACTIVE"
        assert before["filing_fee_cents"] == FILING_FEE_CENTS
        assert before["fee_refunded_cents"] == 0
        assert (
            fx.read_vendor(state["protester_vendor_id"])["protest_fee_balance_cents"]
            == PURSE_CENTS - FILING_FEE_CENTS
        )
        assert (
            fx.read_solicitation(state["solicitation_id"])["protest_escrow_cents"]
            == FILING_FEE_CENTS
        )

        decided = _sustain_on_corrective_action(state["protest_id"])

        assert decided["status"] == "SUSTAINED"
        assert decided["decision_outcome"] == "SUSTAINED"
        assert decided["remedy_code"] == "CORRECTIVE_ACTION"
        assert decided["stay_status"] == "LIFTED"
        assert decided["fee_refunded_cents"] == FILING_FEE_CENTS
        _assert_same_instant(
            decided["decided_at_utc"], HEARING_START_UTC, "decided_at_utc"
        )

        # The same values are readable immediately, not eventually.
        persisted = fx.read_protest(state["protest_id"])
        assert persisted["status"] == "SUSTAINED"
        assert persisted["stay_status"] == "LIFTED"
        assert persisted["fee_refunded_cents"] == FILING_FEE_CENTS

        assert (
            fx.read_vendor(state["protester_vendor_id"])["protest_fee_balance_cents"]
            == PURSE_CENTS
        ), "the whole filing fee returns to the protester's purse"
        assert (
            fx.read_solicitation(state["solicitation_id"])["protest_escrow_cents"] == 0
        ), "the solicitation's escrow is emptied by the refund"

    def test_hop_two_voids_the_pending_award_for_the_sustained_protest(self):
        """With `remedy_code` `CORRECTIVE_ACTION`, hop 2 follows from hop 1: the award on the same solicitation leaves its current state, moving `PENDING_STAY → VOID` with `void_reason_code` `PROTEST_SUSTAINED`, or `EXECUTED → RESCINDED` with the same reason code when the award had already been executed.

        Design: Difficulty/transitive_cascade/corrective_action_protest_decision_cascade_depth_five
        """
        state = _setup_award_pending_protest_ready_for_decision()

        before = fx.read_award(state["award_id"])
        assert before["status"] == "PENDING_STAY"
        assert before["void_reason_code"] is None

        _sustain_on_corrective_action(state["protest_id"])

        award = fx.read_award(state["award_id"])
        assert award["status"] == "VOID"
        assert award["void_reason_code"] == "PROTEST_SUSTAINED"
        assert award["executed_at_utc"] is None, (
            "an award voided out of PENDING_STAY was never executed"
        )

    def test_the_concluded_hearing_snapshot_survives_the_decision(self):
        """Concluding moves the hearing `CONVENED → CONCLUDED`, requires the protest's `record_item_count` to be at least 2 (else `ERR_AGENCY_RECORD_INCOMPLETE`), stamps `concluded_at_utc` from the logical clock, snapshots `record_items_reviewed_count` as the protest's `record_item_count` at that moment, and drives the protest `HEARING_SCHEDULED → UNDER_REVIEW`.

        Design: Difficulty/transitive_cascade/corrective_action_protest_decision_cascade_depth_five
        """
        state = _setup_award_pending_protest_ready_for_decision()

        assert fx.read_protest(state["protest_id"])["record_item_count"] == 2

        _sustain_on_corrective_action(state["protest_id"])

        hearing = fx.read_hearing(state["hearing_id"])
        assert hearing["status"] == "CONCLUDED"
        assert hearing["record_items_reviewed_count"] == 2


# ===========================================================================
# Hops 3, 4 and 5 — the solicitation, its bids and their reviews
# ===========================================================================
class TestCorrectiveActionCascadeOuterHops:
    def test_hop_three_returns_the_solicitation_to_evaluation_and_reranks(self):
        """Hop 3 follows from hop 2: because the award left `PENDING_STAY` or `EXECUTED`, the solicitation transitions `AWARD_PENDING → EVALUATION` or `AWARDED → EVALUATION` respectively, and recomputes `apparent_low_bid_id`.

        Design: Difficulty/transitive_cascade/corrective_action_protest_decision_cascade_depth_five
        """
        state = _setup_award_pending_protest_ready_for_decision()

        before = fx.read_solicitation(state["solicitation_id"])
        assert before["status"] == "AWARD_PENDING"
        assert before["apparent_low_bid_id"] == state["low_bid_id"]

        _sustain_on_corrective_action(state["protest_id"])

        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["status"] == "EVALUATION"
        assert solicitation["apparent_low_bid_id"] == state["low_bid_id"], (
            "the recomputed ranking still names the cheapest responsive bid, "
            "because reverting a responsibility status does not exclude a bid "
            "from the candidate set"
        )

    def test_hop_four_reverts_the_reviewed_bid_without_touching_responsiveness(self):
        """Hop 4 follows from hop 3: because the solicitation re-entered `EVALUATION`, every bid on it whose `responsibility_status` is `RESPONSIBLE` or `NONRESPONSIBLE` reverts to `NOT_REVIEWED`.

        Design: Difficulty/transitive_cascade/corrective_action_protest_decision_cascade_depth_five
        """
        state = _setup_award_pending_protest_ready_for_decision()

        before = fx.read_bid(state["low_bid_id"])
        assert before["responsibility_status"] == "RESPONSIBLE"
        assert before["responsiveness_status"] == "RESPONSIVE"

        _sustain_on_corrective_action(state["protest_id"])

        low_bid = fx.read_bid(state["low_bid_id"])
        assert low_bid["responsibility_status"] == "NOT_REVIEWED"
        assert low_bid["responsiveness_status"] == "RESPONSIVE", (
            "the two dimensions are independent: reverting responsibility never "
            "disturbs the responsiveness determination"
        )

        second_bid = fx.read_bid(state["second_bid_id"])
        assert second_bid["responsibility_status"] == "NOT_REVIEWED", (
            "the never-reviewed bid stays where it always was"
        )
        assert second_bid["responsiveness_status"] == "RESPONSIVE"

    def test_hop_five_supersedes_the_review_without_rewriting_its_findings(self):
        """Hop 5 follows from hop 4: because those bids reverted, every responsibility review whose reviewed bid is one of them has its `superseded_at_utc` stamped with the logical clock, which is exactly what removes it from consideration as a protest trigger event.

        Design: Difficulty/transitive_cascade/corrective_action_protest_decision_cascade_depth_five
        """
        state = _setup_award_pending_protest_ready_for_decision()

        before = _read_review(state["low_bid_id"], state["review_id"])
        assert before["superseded_at_utc"] is None
        assert before["composite_score"] == pytest.approx(COMPOSITE_SCORE, abs=0.01)
        assert before["determination"] == "RESPONSIBLE"

        _sustain_on_corrective_action(state["protest_id"])

        review = _read_review(state["low_bid_id"], state["review_id"])
        _assert_same_instant(
            review["superseded_at_utc"], HEARING_START_UTC, "superseded_at_utc"
        )
        assert review["composite_score"] == pytest.approx(COMPOSITE_SCORE, abs=0.01), (
            "superseding a review does not rewrite the score it recorded"
        )
        assert review["determination"] == "RESPONSIBLE", (
            "superseding a review does not rewrite the determination it recorded"
        )
        assert review["weight_profile"] == "STANDARD"
