"""Cascades in which each hop is caused by the one before it.

Suspending an investor reaches all the way down to the facility's posture, and a
second consecutive covenant breach reaches all the way out to a funding wire.
"""

import pytest

from test_helpers import CREDIT_OFFICER, api_client, validate_paginated
from test_helpers import assertions as asserts
from test_helpers import fixtures as fx


# ─── Investor suspension, four hops deep ──────────────────────────────────────

def _suspend_the_investor_behind_a_shipped_advance():
    scenario = fx.setup_shipped_advance(ship_clock_utc="2026-08-05T00:00:00Z")
    scenario.investor = fx.suspend_investor(
        scenario.investor["id"],
        reason="Counterparty downgraded below investment grade",
    )
    scenario.commitment = fx.read_commitment(scenario.commitment["id"])
    scenario.advance = fx.read_advance(scenario.advance["id"])
    scenario.facility = fx.read_facility(scenario.facility["id"])
    scenario.calls = fx.advance_margin_calls(scenario.advance["id"])
    scenario.letters = fx.advance_bailee_letters(scenario.advance["id"])
    return scenario


class TestInvestorSuspensionCascade:
    def test_the_suspension_reaches_the_facility_posture_in_four_hops(self):
        """Withdrawn commitment, orphan re-valuation, margin call, restriction.

        PRD 3.2: "In the second hop, because those commitments are now
        withdrawn, every advance pointing at them whose `funding_status` is
        `FUNDED` or `SHIPPED` is re-valued as orphaned collateral, its rate
        capped at the orphan ceiling of 0.85, which lowers
        `eligible_collateral_value_cents` and raises `required_paydown_cents`."

        Design: Difficulty/transitive_cascade/cascade_investor_suspension_to_facility_restriction
        """
        scenario = _suspend_the_investor_behind_a_shipped_advance()

        # Hop zero: the investor itself.
        assert scenario.investor["status"] == "SUSPENDED"

        # Hop one: its commitments.
        assert scenario.commitment["status"] == "WITHDRAWN"
        assert scenario.commitment["remaining_amount_cents"] == 0

        # Hop two: the orphan cap replaces the 0.98 product rate.
        advance = scenario.advance
        assert advance["effective_advance_rate"] == pytest.approx(0.85, abs=1e-6)
        assert advance["eligible_collateral_value_cents"] == 1_700_000_000
        assert advance["required_paydown_cents"] == 260_000_000

        # Hop three: the call the shortfall produces.
        withdrawal_calls = [
            call
            for call in scenario.calls
            if call["trigger_reason"] == "COMMITMENT_WITHDRAWN"
        ]
        assert len(withdrawal_calls) == 1
        asserts.assert_margin_call(withdrawal_calls[0])
        assert withdrawal_calls[0]["status"] == "ISSUED"
        assert withdrawal_calls[0]["call_amount_cents"] == 260_000_000

        # Hop four: the facility posture.
        assert scenario.facility["status"] == "RESTRICTED"
        assert scenario.facility["open_margin_call_count"] == 1

    def test_the_live_bailee_letter_is_revoked_without_unwinding_the_shipment(self):
        """The paper comes back; the money stays exactly where it was.

        PRD 3.2: "Separately, every bailee letter still in `ISSUED` that names
        the suspended investor moves to `REVOKED`."

        Design: Difficulty/transitive_cascade/cascade_investor_suspension_to_facility_restriction
        """
        scenario = _suspend_the_investor_behind_a_shipped_advance()

        assert len(scenario.letters) == 1
        asserts.assert_bailee_letter(scenario.letters[0])
        assert scenario.letters[0]["status"] == "REVOKED"

        # Neither axis of the advance rolls back.
        assert scenario.advance["funding_status"] == "SHIPPED"
        assert scenario.advance["custody_status"] == "RELEASED_TO_INVESTOR"
        assert scenario.advance["outstanding_balance_cents"] == 1_960_000_000

        assert scenario.facility["outstanding_principal_cents"] == 1_960_000_000
        summary = fx.read_exposure_summary(scenario.facility["id"])
        asserts.assert_both_conservation_invariants(summary)


# ─── Second consecutive breach, out to the wire ───────────────────────────────

def _breach_the_covenant_twice_in_a_row():
    scenario = fx.setup_requested_advance(
        advance_overrides={"loan_amount_cents": 800_000_000, "note_rate": 0.0675}
    )
    scenario.first_test = fx.certify_covenants(
        scenario.facility["id"], "2026-03-31", net_income_cents=15_000_000
    )
    scenario.second_test = fx.certify_covenants(
        scenario.facility["id"], "2026-06-30", net_income_cents=15_000_000
    )
    scenario.facility = fx.read_facility(scenario.facility["id"])
    scenario.advance = fx.read_advance(scenario.advance["id"])
    scenario.wire = fx.wire_for_advance(scenario.advance["id"])
    return scenario


class TestSecondBreachToWireBlockCascade:
    def test_the_second_consecutive_breach_suspends_the_line(self):
        """One breach restricts; the next one suspends.

        PRD 3.8: "When the breach brings `consecutive_breach_count` to two, the
        facility goes further and lands in `SUSPENDED`, which forcibly rejects
        every advance of the facility still in `REQUESTED` with a
        `rejected_reason` of `FACILITY_SUSPENDED` and blocks each of their wire
        instructions still in `PENDING_VERIFICATION` with a `block_reason` of
        `FACILITY_SUSPENDED`."

        Design: Difficulty/transitive_cascade/cascade_second_covenant_breach_to_wire_block
        """
        scenario = _breach_the_covenant_twice_in_a_row()

        second = scenario.second_test
        asserts.assert_covenant_test(second)
        # One stored prior only, so the annualised variant still applies.
        assert second["profitability_variant"] == "ANNUALIZED_QUARTER"
        assert second["profitability_metric_cents"] == 60_000_000
        assert second["breach_codes"] == ["PROFITABILITY"]
        assert second["status"] == "BREACH"

        assert scenario.facility["consecutive_breach_count"] == 2
        assert scenario.facility["status"] == "SUSPENDED"
        assert scenario.facility["last_covenant_status"] == "BREACH"

    def test_suspension_rejects_the_requested_advance_and_blocks_its_wire(self):
        """The collateral damage lands on rows nobody addressed.

        PRD 3.3: "There is a second, system-driven route into `BLOCKED`: when
        the owning facility is suspended, every wire of that facility's
        requested advances that is still `PENDING_VERIFICATION` moves to
        `BLOCKED` with `block_reason` of `FACILITY_SUSPENDED`,
        `decided_by_user_id` left null because no operator decided it, and its
        `version` incremented; the matching advances move `REQUESTED →
        REJECTED` with `rejected_reason` of `FACILITY_SUSPENDED`."

        Design: Difficulty/transitive_cascade/cascade_second_covenant_breach_to_wire_block
        """
        scenario = _breach_the_covenant_twice_in_a_row()

        assert scenario.advance["funding_status"] == "REJECTED"
        assert scenario.advance["rejected_reason"] == "FACILITY_SUSPENDED"

        assert scenario.wire["status"] == "BLOCKED"
        assert scenario.wire["block_reason"] == "FACILITY_SUSPENDED"
        assert scenario.wire["decided_by_user_id"] is None

        # Nothing was ever drawn, so the covenant call sized to zero and was
        # skipped rather than created.
        _calls, meta = validate_paginated(
            api_client.list_facility_margin_calls(
                scenario.facility["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 0
        assert scenario.facility["outstanding_principal_cents"] == 0
        assert scenario.facility["open_margin_call_count"] == 0
