"""Consistency corner: the widest write in the system, observed once.

Funding touches the advance, its wire, the commitment, the investor, the ledger
and five facility rollups. Every one of those effects is asserted on the writing
response itself or on the very first read that follows it, with the logical clock
untouched and no intervening write of any kind.
"""

import pytest

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    WIRE_OPERATOR,
    api_client,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import fixtures as fx


class TestImmediateVisibilityOfTheFundingCascade:
    def test_one_funding_settles_six_rows_before_it_answers(self):
        """Nothing is deferred to a sweep, a batch or a second read.

        PRD 2.10: "When one operation mutates several rows, every mutated row has
        its `version` incremented by 1 and its `updated_at` refreshed, and the
        response reflects the fully settled state — there is no eventual
        consistency and no deferred queue."

        PRD 3.3: "One ledger entry of type `ADVANCE_FUNDED` and direction `DEBIT`
        is appended for `advance_amount_cents`, attributed to this advance, which
        is what makes `outstanding_principal_cents`, `availability_cents`,
        `wet_outstanding_cents`, `aged_outstanding_cents` and
        `scratch_and_dent_outstanding_cents` move."

        PRD 3.3: "The named commitment's `allocated_amount_cents` rises by the
        funded amount, its `remaining_amount_cents` and status are re-derived, and
        the investor's `exposure_cents` is re-projected."

        PRD 3.3: "The wire moves `VERIFIED → RELEASED`, which is terminal for it."

        PRD 2.6: "Two invariants follow, and the reconciliation view exposes both
        sides of each so that they can be asserted in a single call."

        Design: Corner/consistency_model/corner_consistency_immediate_visibility_of_the_whole_funding_cascade
        """
        scenario = fx.setup_advance_ready_to_fund()
        facility_id = scenario.facility["id"]
        advance_id = scenario.advance["id"]

        funded = validate_success(
            api_client.fund_advance(advance_id, COLLATERAL_ANALYST)
        )
        # The writing response alone carries every recomputed derived field.
        asserts.assert_advance(funded)
        assert funded["funding_status"] == "FUNDED"
        assert funded["advance_amount_cents"] == 1_960_000_000
        assert funded["provisional_advance_amount_cents"] == 1_960_000_000
        assert funded["concentration_capped"] is False
        assert funded["effective_advance_rate"] == pytest.approx(0.98, abs=1e-6)
        assert funded["eligible_collateral_value_cents"] == 1_960_000_000
        assert funded["required_paydown_cents"] == 0
        assert funded["dwell_days"] == 0
        asserts.assert_instant(funded["funded_at"], "2026-08-01T00:00:00Z")

        # First read after the write, clock untouched, no write in between.
        summary = fx.read_exposure_summary(facility_id)
        assert summary["outstanding_principal_cents"] == 1_960_000_000
        assert summary["availability_cents"] == 18_040_000_000
        asserts.assert_availability_projection(summary)
        assert summary["wet_outstanding_cents"] == 0
        assert summary["aged_outstanding_cents"] == 0
        assert summary["scratch_and_dent_outstanding_cents"] == 0
        assert summary["accrued_fee_balance_cents"] == 0
        assert summary["open_margin_call_count"] == 0
        assert summary["ledger_debit_total_cents"] == 1_960_000_000
        assert summary["ledger_credit_total_cents"] == 0
        assert summary["advance_outstanding_sum_cents"] == 1_960_000_000
        asserts.assert_both_conservation_invariants(summary)
        assert len(summary["investor_exposures"]) == 1
        exposure = summary["investor_exposures"][0]
        assert exposure["investor_id"] == scenario.investor["id"]
        assert exposure["exposure_cents"] == 1_960_000_000

        commitment = fx.read_commitment(scenario.commitment["id"])
        assert commitment["allocated_amount_cents"] == 1_960_000_000
        assert commitment["settled_amount_cents"] == 0
        assert commitment["remaining_amount_cents"] == 3_040_000_000
        assert commitment["status"] == "PARTIALLY_ALLOCATED"
        asserts.assert_commitment_capacity_conserved(commitment)

        investor = fx.read_investor(scenario.investor["id"])
        assert investor["exposure_cents"] == 1_960_000_000

        wires, wire_meta = validate_paginated(
            api_client.list_advance_wire_instructions(advance_id, WIRE_OPERATOR)
        )
        assert wire_meta["total_count"] == 1
        # The wire's own transition belongs to the funding request.
        assert wires[0]["status"] == "RELEASED"

        entries, entry_meta = validate_paginated(
            api_client.list_facility_ledger_entries(
                facility_id, CREDIT_OFFICER, {"entry_type": "ADVANCE_FUNDED"}
            )
        )
        assert entry_meta["total_count"] == 1
        asserts.assert_ledger_entry(entries[0])
        assert entries[0]["entry_type"] == "ADVANCE_FUNDED"
        assert entries[0]["direction"] == "DEBIT"
        assert entries[0]["amount_cents"] == 1_960_000_000
        assert entries[0]["advance_id"] == advance_id
        asserts.assert_instant(entries[0]["posted_at"], "2026-08-01T00:00:00Z")
