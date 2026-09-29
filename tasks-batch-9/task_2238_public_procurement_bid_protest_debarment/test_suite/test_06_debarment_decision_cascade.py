"""Cascade B: the chain a final debarment decision sets off.

One merits decision debarring a respondent walks outward through four hops and
four entity types — the proceeding and its respondent vendor, that vendor's live
bids, the solicitations those bids sit on, and the notices of award pending on
them. The distinguishing feature of this chain is that the apparent low bidder
actually changes, which is the only thing that can void the pending award with
the changed-bidder reason code rather than the sustained-protest one.

Every row is built from scratch through the public API against an empty
database, and the logical clock is driven explicitly because the decision
instant anchors the debarment period, its end and the reinstatement date.
"""
from datetime import datetime
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import DEBARMENT_AUTHORITY_HEADERS

# --------------------------------------------------------------------------
# The calendar this chain runs on
# --------------------------------------------------------------------------
QUESTION_DEADLINE_UTC = "2026-08-20T00:00:00Z"
BID_DUE_UTC = "2026-08-27T00:00:00Z"
NOTICE_ISSUED_UTC = "2026-08-27T00:00:00Z"
RESPONSE_DEADLINE_UTC = "2026-09-10T00:00:00Z"
DECISION_UTC = "2026-09-11T00:00:00Z"

# --------------------------------------------------------------------------
# The pinned figures of this procurement and this proceeding
# --------------------------------------------------------------------------
ESTIMATED_VALUE_CENTS = 100000000
LOW_BID_CENTS = 100000000
SECOND_BID_CENTS = 100000001

# BID_RIGGING (35) + FALSE_CERTIFICATION (25), no mitigation, no prior strikes.
AGGRAVATING_TOTAL_POINTS = 60.00
MITIGATING_CREDIT_POINTS = 0
SEVERITY_SCORE = 60.00
DEBARMENT_PERIOD_MONTHS = 36
DEBARMENT_END_UTC = "2029-09-11T00:00:00Z"
# CEIL(36 / 2) == 18 calendar months served before a petition is ripe.
EARLIEST_PETITION_UTC = "2028-03-11T00:00:00Z"

AWARD_TOTAL_OBLIGATION_CENTS = 101500000


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


def _setup_award_pending_with_hearing_held_proceeding() -> Dict[str, Any]:
    """A solicitation in AWARD_PENDING whose apparent low bidder is the
    respondent of a debarment proceeding that has reached HEARING_HELD on the
    default branch, with the notice of award still sitting in PENDING_STAY."""
    fx.reset_clock()

    respondent = fx.create_vendor(
        legal_name="Fenwick Aggregate Supply",
        tax_id="100000013",
        contact_email="v13@example.gov",
    )
    runner_up = fx.create_vendor(
        legal_name="Bramwell Paving Partners",
        tax_id="100000014",
        contact_email="v14@example.gov",
    )
    respondent_id = respondent["id"]
    runner_up_id = runner_up["id"]
    assert respondent["eligibility_status"] == "ELIGIBLE"
    assert respondent["debarment_strike_count"] == 0

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-TC2",
        title="District Aggregate Term Contract",
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
        solicitation_id, respondent_id, total_price_cents=LOW_BID_CENTS
    )
    second_bid = fx.submit_bid(
        solicitation_id, runner_up_id, total_price_cents=SECOND_BID_CENTS
    )

    fx.set_clock(QUESTION_DEADLINE_UTC)
    fx.close_question_period(solicitation_id)
    fx.set_clock(BID_DUE_UTC)
    fx.open_bids(solicitation_id)

    fx.determine_responsiveness(low_bid["id"], determination="RESPONSIVE")
    fx.determine_responsiveness(second_bid["id"], determination="RESPONSIVE")

    fx.review_responsibility(
        low_bid["id"],
        financial_capacity_score=80,
        past_performance_score=85,
        integrity_score=90,
        determination="RESPONSIBLE",
        notes="no adverse findings of record at review time",
    )

    award = fx.create_award(solicitation_id, low_bid["id"])

    proceeding = fx.open_proceeding(
        respondent_id,
        cause_code="BID_RIGGING",
        aggravating_factor_codes=["BID_RIGGING", "FALSE_CERTIFICATION"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    proceeding_id = proceeding["id"]
    assert proceeding["status"] == "NOTICE_ISSUED"
    assert proceeding["interim_status"] == "NONE"
    _assert_same_instant(
        proceeding["response_deadline_utc"],
        RESPONSE_DEADLINE_UTC,
        "response_deadline_utc",
    )

    # No response is ever filed, so the hearing may only be taken once the
    # notice window has actually expired.
    fx.set_clock(DECISION_UTC)
    fx.hold_debarment_hearing(
        proceeding_id,
        hearing_summary=(
            "respondent filed no response within the notice window; hearing "
            "rights exhausted by default"
        ),
    )

    return {
        "respondent_id": respondent_id,
        "runner_up_id": runner_up_id,
        "solicitation_id": solicitation_id,
        "low_bid_id": low_bid["id"],
        "second_bid_id": second_bid["id"],
        "award_id": award["id"],
        "proceeding_id": proceeding_id,
    }


def _decide_debarred(proceeding_id: str) -> Dict[str, Any]:
    """The single trigger call: one debarment on the merits, whose response must
    already reflect hop 1 of the chain."""
    return validate_success(
        api_client.decide_debarment(
            proceeding_id,
            fac.debarment_decision_payload(
                outcome="DEBARRED",
                rationale="collusive bidding established by a preponderance of the record",
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
    )


# ===========================================================================
# Hop 1 — the proceeding and its respondent
# ===========================================================================
class TestDebarmentCascadeFirstHop:
    def test_hop_one_scores_the_merits_and_sets_the_period_and_its_end(self):
        """Hop 1 recomputes `severity_score` and `mitigating_credit_points` under the final-debarment variant, sets `debarment_period_months` from the severity tier, stamps `debarment_start_utc` and `decided_at_utc` from the logical clock, computes `debarment_end_utc` as the start instant plus `debarment_period_months` calendar months, sets `strikes_applied` to 1, and drives the respondent to `DEBARRED` — recomputing that vendor's `debarment_strike_count`, `active_debarment_id`, `suspension_reason_code` and `reinstatement_earliest_petition_utc`.

        Design: Difficulty/transitive_cascade/vendor_debarment_decision_cascade_depth_four
        """
        state = _setup_award_pending_with_hearing_held_proceeding()

        before = fx.read_proceeding(state["proceeding_id"])
        assert before["status"] == "HEARING_HELD"
        assert before["debarment_period_months"] == 0
        assert before["debarment_start_utc"] is None
        assert before["strikes_applied"] == 0

        decided = _decide_debarred(state["proceeding_id"])

        assert decided["status"] == "DEBARRED"
        assert decided["aggravating_total_points"] == pytest.approx(
            AGGRAVATING_TOTAL_POINTS, abs=0.01
        )
        assert decided["mitigating_credit_points"] == pytest.approx(
            MITIGATING_CREDIT_POINTS, abs=0.01
        )
        assert decided["severity_score"] == pytest.approx(SEVERITY_SCORE, abs=0.01)
        assert decided["debarment_period_months"] == DEBARMENT_PERIOD_MONTHS
        assert decided["strikes_applied"] == 1
        _assert_same_instant(
            decided["debarment_start_utc"], DECISION_UTC, "debarment_start_utc"
        )
        _assert_same_instant(
            decided["debarment_end_utc"], DEBARMENT_END_UTC, "debarment_end_utc"
        )
        _assert_same_instant(decided["decided_at_utc"], DECISION_UTC, "decided_at_utc")

        # The same values are readable immediately, not eventually.
        persisted = fx.read_proceeding(state["proceeding_id"])
        assert persisted["status"] == "DEBARRED"
        assert persisted["severity_score"] == pytest.approx(SEVERITY_SCORE, abs=0.01)
        assert persisted["debarment_period_months"] == DEBARMENT_PERIOD_MONTHS

    def test_hop_one_debars_the_respondent_and_charges_it_one_strike(self):
        """The strike bookkeeping differs by the vendor's prior posture, and the difference is deliberate: a vendor moving `SUSPENDED → DEBARRED` was already carrying this proceeding's strike, so `interim_status` moves `INTERIM_SUSPENDED → INTERIM_LIFTED` while `strikes_applied` stays 1 and `debarment_strike_count` is unchanged; a vendor moving `ELIGIBLE → DEBARRED` with no interim suspension in force has this proceeding's `strikes_applied` move from 0 to 1, so `debarment_strike_count` increases by 1.

        Design: Difficulty/transitive_cascade/vendor_debarment_decision_cascade_depth_four
        """
        state = _setup_award_pending_with_hearing_held_proceeding()

        before = fx.read_vendor(state["respondent_id"])
        assert before["eligibility_status"] == "ELIGIBLE"
        assert before["debarment_strike_count"] == 0
        assert before["active_debarment_id"] is None

        _decide_debarred(state["proceeding_id"])

        respondent = fx.read_vendor(state["respondent_id"])
        assert respondent["eligibility_status"] == "DEBARRED"
        assert respondent["debarment_strike_count"] == 1
        assert respondent["active_debarment_id"] == state["proceeding_id"]
        assert respondent["suspension_reason_code"] == "BID_RIGGING"

        runner_up = fx.read_vendor(state["runner_up_id"])
        assert runner_up["eligibility_status"] == "ELIGIBLE", (
            "the cascade reaches the respondent only, never another bidder"
        )
        assert runner_up["debarment_strike_count"] == 0

    def test_hop_one_dates_the_earliest_reinstatement_petition(self):
        """When a debarment is decided, the respondent's `reinstatement_earliest_petition_utc` is stamped as the proceeding's `debarment_start_utc` plus a number of calendar months equal to half the `debarment_period_months`, rounded up to a whole month.

        Design: Difficulty/transitive_cascade/vendor_debarment_decision_cascade_depth_four
        """
        state = _setup_award_pending_with_hearing_held_proceeding()

        assert (
            fx.read_vendor(state["respondent_id"])[
                "reinstatement_earliest_petition_utc"
            ]
            is None
        )

        _decide_debarred(state["proceeding_id"])

        respondent = fx.read_vendor(state["respondent_id"])
        _assert_same_instant(
            respondent["reinstatement_earliest_petition_utc"],
            EARLIEST_PETITION_UTC,
            "reinstatement_earliest_petition_utc",
        )


# ===========================================================================
# Hops 2, 3 and 4 — the bids, the solicitation and the pending award
# ===========================================================================
class TestDebarmentCascadeOuterHops:
    def test_hop_two_makes_the_debarred_vendor_bid_nonresponsive(self):
        """Hop 2 follows from hop 1: because the vendor's `eligibility_status` became `DEBARRED`, every bid of that vendor whose solicitation is in `BIDS_OPENED`, `EVALUATION` or `AWARD_PENDING` and whose `responsiveness_status` is `UNREVIEWED` or `RESPONSIVE` becomes `NONRESPONSIVE` with `VENDOR_DEBARRED` appended.

        Design: Difficulty/transitive_cascade/vendor_debarment_decision_cascade_depth_four
        """
        state = _setup_award_pending_with_hearing_held_proceeding()

        before = fx.read_bid(state["low_bid_id"])
        assert before["responsiveness_status"] == "RESPONSIVE"
        assert before["nonresponsive_reason_codes"] == []

        _decide_debarred(state["proceeding_id"])

        low_bid = fx.read_bid(state["low_bid_id"])
        assert low_bid["responsiveness_status"] == "NONRESPONSIVE"
        assert "VENDOR_DEBARRED" in low_bid["nonresponsive_reason_codes"], (
            "expected VENDOR_DEBARRED among {}".format(
                low_bid["nonresponsive_reason_codes"]
            )
        )

        second_bid = fx.read_bid(state["second_bid_id"])
        assert second_bid["responsiveness_status"] == "RESPONSIVE", (
            "the untouched vendor's bid keeps its responsiveness determination"
        )
        assert second_bid["responsibility_status"] == "NOT_REVIEWED"
        assert second_bid["nonresponsive_reason_codes"] == []

    def test_hop_three_reranks_the_solicitation_and_reverts_its_reviewed_bids(self):
        """Hop 3 follows from hop 2: each affected solicitation recomputes `apparent_low_bid_id`, and a solicitation in `AWARD_PENDING` whose apparent low bidder changed transitions to `EVALUATION` — which in turn reverts that solicitation's bids from `RESPONSIBLE` or `NONRESPONSIBLE` back to `NOT_REVIEWED` and stamps `superseded_at_utc` on their responsibility reviews, exactly as in Cascade A.

        Design: Difficulty/transitive_cascade/vendor_debarment_decision_cascade_depth_four
        """
        state = _setup_award_pending_with_hearing_held_proceeding()

        before = fx.read_solicitation(state["solicitation_id"])
        assert before["status"] == "AWARD_PENDING"
        assert before["apparent_low_bid_id"] == state["low_bid_id"]
        assert fx.read_bid(state["low_bid_id"])["responsibility_status"] == "RESPONSIBLE"

        _decide_debarred(state["proceeding_id"])

        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["apparent_low_bid_id"] == state["second_bid_id"], (
            "the nonresponsive bid leaves the candidate set permanently, so the "
            "next-lowest candidate becomes the apparent low bidder"
        )
        assert solicitation["status"] == "EVALUATION"

        assert (
            fx.read_bid(state["low_bid_id"])["responsibility_status"] == "NOT_REVIEWED"
        ), "re-entering EVALUATION reverts the responsibility dimension"

    def test_hop_four_voids_the_award_on_the_changed_apparent_low_bidder(self):
        """Hop 4 follows from hop 3: because that solicitation left `AWARD_PENDING`, its award in `PENDING_STAY` becomes `VOID` with `void_reason_code` `APPARENT_LOW_BIDDER_CHANGED`.

        Design: Difficulty/transitive_cascade/vendor_debarment_decision_cascade_depth_four
        """
        state = _setup_award_pending_with_hearing_held_proceeding()

        before = fx.read_award(state["award_id"])
        assert before["status"] == "PENDING_STAY"
        assert before["void_reason_code"] is None
        assert before["award_total_obligation_cents"] == AWARD_TOTAL_OBLIGATION_CENTS

        _decide_debarred(state["proceeding_id"])

        award = fx.read_award(state["award_id"])
        assert award["status"] == "VOID"
        assert award["void_reason_code"] == "APPARENT_LOW_BIDDER_CHANGED", (
            "the ranking change is what voided this award, so neither "
            "PROTEST_SUSTAINED nor SOLICITATION_CANCELLED is the reason code, "
            "got {!r}".format(award["void_reason_code"])
        )
        assert award["executed_at_utc"] is None
