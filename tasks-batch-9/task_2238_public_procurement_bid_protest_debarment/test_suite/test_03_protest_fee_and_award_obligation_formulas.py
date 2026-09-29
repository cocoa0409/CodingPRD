"""Protest filing fee and award obligation: the two pinned money formulas.

Both formulas in this file are multi-component computations whose per-component
rounding order and whose tier-selection input are contract rather than
convenience (PRD 2.7), so each test pins the exact integer cents the server must
return and, where an alternative ordering would differ, pins that the
alternative was not used.
"""
from typing import Any, Dict

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    make_vendor_headers,
)

# --------------------------------------------------------------------------
# Scenario builders — every row is created through the public API.
# --------------------------------------------------------------------------
BOND_REQUIREMENT = {
    "requirement_code": "REQ-BOND",
    "description": "five percent bid bond",
    "materiality": "MATERIAL",
    "is_waivable": False,
}

QUESTION_DEADLINE_CLOCK = "2026-08-20T00:00:00Z"
BID_DUE_CLOCK = "2026-08-27T00:00:00Z"


def _nonresponsive_bidder_on_high_value_solicitation() -> Dict[str, Any]:
    """A funded vendor whose own bid on a 400,002,000-cent solicitation has just
    been determined NONRESPONSIVE, which is the trigger event a
    RESPONSIVENESS_DETERMINATION protest names."""
    vendor = fx.create_vendor(
        legal_name="Harbison Bridge Co",
        tax_id="100000003",
        contact_email="v3@example.gov",
    )
    fx.fund_vendor(vendor["id"], 200000)

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-CF1",
        title="Bridge Deck Rehabilitation",
        issuing_agency_code="DOT",
        estimated_value_cents=400002000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[dict(BOND_REQUIREMENT)],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    bid = fx.submit_bid(solicitation_id, vendor["id"], total_price_cents=390000000)

    fx.set_clock(QUESTION_DEADLINE_CLOCK)
    fx.close_question_period(solicitation_id)
    fx.set_clock(BID_DUE_CLOCK)
    fx.open_bids(solicitation_id)

    fx.determine_responsiveness(
        bid["id"],
        determination="NONRESPONSIVE",
        reason_codes=["OFFICER_DETERMINATION"],
    )

    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation_id,
        "bid_id": bid["id"],
    }


def _file_responsiveness_protest(state: Dict[str, Any]) -> Dict[str, Any]:
    response = api_client.create_protest(
        fac.protest_payload(
            state["solicitation_id"],
            state["vendor_id"],
            grounds_code="RESPONSIVENESS_DETERMINATION",
            narrative="the deviation cited was a waivable informality",
            challenged_bid_id=state["bid_id"],
        ),
        make_vendor_headers(state["vendor_id"]),
    )
    return validate_success(response, expected_status=201)


def _award_pending_at_first_fee_tier_top(
    with_resolved_protest: bool = True,
) -> Dict[str, Any]:
    """A solicitation whose apparent low bid is evaluated at exactly
    100,000,000 cents — the inclusive top of the first administrative-fee tier —
    reviewed RESPONSIBLE and therefore sitting in AWARD_PENDING. When
    `with_resolved_protest` is true the vendor also filed and withdrew a protest,
    so one resolved protest exists on the solicitation and no stay is active."""
    vendor = fx.create_vendor(
        legal_name="Marchetti Earthworks",
        tax_id="100000004",
        contact_email="v4@example.gov",
    )
    fx.fund_vendor(vendor["id"], 100000)

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-CF2",
        title="Culvert Replacement Program",
        issuing_agency_code="DOT",
        estimated_value_cents=100000000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[dict(BOND_REQUIREMENT)],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    bid = fx.submit_bid(solicitation_id, vendor["id"], total_price_cents=100000000)

    fx.set_clock(QUESTION_DEADLINE_CLOCK)
    fx.close_question_period(solicitation_id)
    fx.set_clock(BID_DUE_CLOCK)
    fx.open_bids(solicitation_id)

    protest = None
    if with_resolved_protest:
        protest = fx.file_protest(
            solicitation_id,
            vendor["id"],
            grounds_code="EVALUATION_ERROR",
            narrative="the bid abstract omitted an alternate line item",
        )
        protest = fx.withdraw_protest(
            protest["id"],
            vendor["id"],
            withdrawal_reason="resolved informally with the agency",
        )

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
        notes="audited statements and three comparable projects",
    )

    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation_id,
        "bid_id": bid["id"],
        "protest": protest,
    }


def _create_award(state: Dict[str, Any]) -> Dict[str, Any]:
    response = api_client.create_award(
        fac.award_payload(state["solicitation_id"], state["bid_id"]), OFFICER_HEADERS
    )
    return validate_success(response, expected_status=201)


# --------------------------------------------------------------------------
# The protest filing fee
# --------------------------------------------------------------------------
class TestProtestFilingFeeRoundingOrder:
    def test_filing_fee_rounds_each_component_before_adding_them(self):
        """The rounding order is pinned and is part of the contract: each of the three components is individually rounded half-up to a whole cent, and only then are the three rounded components added together.

        On a 400,002,000-cent solicitation the ad valorem component is
        400002000 * 0.00025 = 100000.50 and the RESPONSIVENESS_DETERMINATION
        surcharge is 25000 * 0.3335 = 8337.50, so both carry a fractional part
        of exactly one half: rounding each and then adding gives
        25000 + 100001 + 8338 = 133339, while adding first and rounding once
        would give 133338.

        Design: Difficulty/combinatorial_formula/protest_filing_fee_per_component_rounding_order_pinned
        """
        state = _nonresponsive_bidder_on_high_value_solicitation()

        protest = _file_responsiveness_protest(state)

        assert protest["filing_fee_cents"] == 133339
        assert protest["filing_fee_cents"] != 133338, (
            "the fee must not be computed by summing the unrounded components "
            "and rounding the sum once"
        )
        assert protest["standing_basis"] == "ACTUAL_BIDDER"
        assert protest["timeliness_deadline_utc"].startswith("2026-09-03T00:00:00")
        assert protest["status"] == "FILED"
        assert protest["stay_status"] == "ACTIVE"

    def test_filing_fee_moves_from_the_vendor_purse_into_solicitation_escrow(self):
        """On success the fee is subtracted from the protester's `protest_fee_balance_cents` and added to the solicitation's `protest_escrow_cents`, and both the vendor's `version` and the solicitation's `version` increment by 1.

        The purse held 200000 cents before the filing, so the pinned fee of
        133339 cents leaves 66661 cents unencumbered and escrows 133339 cents
        against the solicitation.

        Design: Difficulty/combinatorial_formula/protest_filing_fee_per_component_rounding_order_pinned
        """
        state = _nonresponsive_bidder_on_high_value_solicitation()

        protest = _file_responsiveness_protest(state)

        vendor = fx.read_vendor(state["vendor_id"])
        solicitation = fx.read_solicitation(state["solicitation_id"])

        assert protest["filing_fee_cents"] == 133339
        assert vendor["protest_fee_balance_cents"] == 66661
        assert solicitation["protest_escrow_cents"] == 133339
        assert (
            vendor["protest_fee_balance_cents"] + solicitation["protest_escrow_cents"]
            == 200000
        ), "the debit and the escrow credit must be the same number of cents"


# --------------------------------------------------------------------------
# The award total obligation
# --------------------------------------------------------------------------
class TestAwardTotalObligationTierSelection:
    def test_administrative_fee_rate_is_selected_on_the_base_obligation_alone(self):
        """The rate is selected once, on the base obligation, and is never re-selected on the final total even though that total is larger and may fall in a different tier; pinning the selection this way is what stops the definition being circular.

        The base obligation is exactly 100,000,000 cents, the inclusive top of
        the first tier, so the rate stays 0.0150 and the fee is 1500000 cents.
        The resulting total of 102007500 cents falls in the second tier, but
        re-selecting 0.0110 on that total would have produced 101605500 cents
        instead.

        Design: Difficulty/combinatorial_formula/award_total_obligation_tier_selected_on_base_only
        """
        state = _award_pending_at_first_fee_tier_top()

        award = _create_award(state)

        assert award["base_obligation_cents"] == 100000000
        assert award["administrative_fee_rate"] == pytest.approx(0.0150, abs=1e-9)
        assert award["administrative_fee_cents"] == 1500000
        assert award["award_total_obligation_cents"] == 102007500
        assert award["award_total_obligation_cents"] != 101605500, (
            "the administrative fee rate must not be re-selected on the final "
            "total obligation"
        )
        assert award["status"] == "PENDING_STAY"
        assert award["vendor_id"] == state["vendor_id"]

    def test_reserve_is_taken_on_the_base_plus_the_already_rounded_fee(self):
        """Step four computes the `protest_risk_reserve_cents`: the solicitation is examined for the existence of any protest whose `status` is `SUSTAINED`, `DENIED` or `WITHDRAWN`, and if at least one such resolved protest exists, the reserve is half of one tenth of one percent — 0.0050 — of the sum of the base obligation and the already-rounded administrative fee, rounded half-up to a whole cent.

        One protest on the solicitation is WITHDRAWN, so the reserve is
        0.0050 * (100000000 + 1500000) = 507500 cents, and the total obligation
        is the additive sum of the base, the fee and that reserve.

        Design: Difficulty/combinatorial_formula/award_total_obligation_tier_selected_on_base_only
        """
        state = _award_pending_at_first_fee_tier_top()
        assert state["protest"]["status"] == "WITHDRAWN"
        assert state["protest"]["stay_status"] == "LIFTED"

        award = _create_award(state)

        assert award["protest_risk_reserve_cents"] == 507500
        assert award["award_total_obligation_cents"] == 102007500
        assert (
            award["award_total_obligation_cents"]
            == award["base_obligation_cents"]
            + award["administrative_fee_cents"]
            + award["protest_risk_reserve_cents"]
        ), "the total obligation must be base plus fee plus reserve"

    def test_reserve_is_zero_when_the_solicitation_carries_no_resolved_protest(self):
        """Protests still open, in `FILED`, `UNDER_REVIEW` or `HEARING_SCHEDULED`, do not trigger the reserve, and when no resolved protest exists the reserve is 0.

        With no protest at all on the solicitation the reserve component drops
        out, while the rate still comes off the base obligation of exactly
        100,000,000 cents, leaving a total of 100000000 + 1500000 cents.

        Design: Difficulty/combinatorial_formula/award_total_obligation_tier_selected_on_base_only
        """
        state = _award_pending_at_first_fee_tier_top(with_resolved_protest=False)

        award = _create_award(state)

        assert award["base_obligation_cents"] == 100000000
        assert award["administrative_fee_rate"] == pytest.approx(0.0150, abs=1e-9)
        assert award["administrative_fee_cents"] == 1500000
        assert award["protest_risk_reserve_cents"] == 0
        assert award["award_total_obligation_cents"] == 101500000
