"""Boundaries that are one unit wide.

The dwell limit is a strictly-greater-than comparison, so the day it is reached
and the day after it behave completely differently; and cardinality zero is
fatal at one site while being a perfectly good answer at another.
"""

import pytest

from test_helpers import (
    CREDIT_OFFICER,
    SECOND_CREDIT_OFFICER,
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import fixtures as fx


# ─── Dwell day 30 against dwell day 31 ────────────────────────────────────────

def _carry_the_advance_across_the_dwell_boundary():
    """An aging run on the limit day and another one day past it."""
    scenario = fx.setup_funded_dry_advance()

    fx.set_clock("2026-08-31T00:00:00Z")
    scenario.run_at_limit = fx.run_aging(scenario.facility["id"])
    scenario.advance_at_limit = fx.read_advance(scenario.advance["id"])
    scenario.facility_at_limit = fx.read_facility(scenario.facility["id"])

    fx.set_clock("2026-09-01T00:00:00Z")
    scenario.run_past_limit = fx.run_aging(scenario.facility["id"])
    scenario.advance_past_limit = fx.read_advance(scenario.advance["id"])
    scenario.facility_past_limit = fx.read_facility(scenario.facility["id"])
    scenario.calls = fx.advance_margin_calls(scenario.advance["id"])
    return scenario


class TestDwellLimitBoundary:
    def test_dwelling_exactly_to_the_limit_curtails_nothing(self):
        """Thirty days of dwell against a thirty-day limit is not aging.

        PRD 3.6: "A loan that has dwelt exactly to its limit is not curtailed at
        all; a loan one day past its limit already incurs a full step."

        Design: Difficulty/boundary_precision_check/boundary_dwell_limit_thirty_versus_thirty_one_days
        """
        scenario = _carry_the_advance_across_the_dwell_boundary()
        advance = scenario.advance_at_limit

        assert advance["dwell_days"] == 30
        assert advance["is_aged"] is False
        assert advance["effective_advance_rate"] == pytest.approx(0.98, abs=1e-6)
        assert advance["eligible_collateral_value_cents"] == 1_960_000_000
        assert advance["required_paydown_cents"] == 0

        run = scenario.run_at_limit
        asserts.assert_aging_run_summary(run)
        assert run["advances_evaluated"] == 1
        assert run["margin_calls_issued"] == 0
        assert run["curtailed_advance_ids"] == []

        assert scenario.facility_at_limit["status"] == "ACTIVE"
        assert scenario.facility_at_limit["aged_outstanding_cents"] == 0

    def test_one_day_past_the_limit_takes_a_whole_curtailment_step(self):
        """Day 31 is a full step, never a fifteenth of one.

        PRD 3.6: "When the advance's `dwell_days` is **strictly** greater than
        the rate row's `dwell_limit_days`, the number of curtailment steps is
        the excess of `dwell_days` over `dwell_limit_days`, divided by
        `aging_step_days` and rounded **up** to a whole number; otherwise the
        number of steps is zero."

        Design: Difficulty/boundary_precision_check/boundary_dwell_limit_thirty_versus_thirty_one_days
        """
        scenario = _carry_the_advance_across_the_dwell_boundary()
        advance = scenario.advance_past_limit

        assert advance["dwell_days"] == 31
        assert advance["is_aged"] is True
        # One step of 0.005 off the 0.98 base rate, not two.
        assert advance["effective_advance_rate"] == pytest.approx(0.975, abs=1e-6)
        assert advance["eligible_collateral_value_cents"] == 1_950_000_000
        assert advance["required_paydown_cents"] == 10_000_000

        run = scenario.run_past_limit
        assert run["margin_calls_issued"] == 1
        assert run["curtailed_advance_ids"] == [scenario.advance["id"]]

        assert len(scenario.calls) == 1
        call = scenario.calls[0]
        asserts.assert_margin_call(call)
        assert call["trigger_reason"] == "DWELL_EXCEEDED"
        assert call["status"] == "ISSUED"
        assert call["call_amount_cents"] == 10_000_000

        assert scenario.facility_past_limit["status"] == "RESTRICTED"
        # The whole outstanding balance moves into the aged bucket at once.
        assert scenario.facility_past_limit["aged_outstanding_cents"] == 1_960_000_000


# ─── Cardinality zero at two different sites ─────────────────────────────────

class TestEmptyCollectionBoundaries:
    def test_a_facility_with_no_priced_product_cannot_be_approved(self):
        """Zero rate rows is fatal to approval; exactly one is sufficient.

        PRD 2.8: "The facility has at least one `ProductAdvanceRate` row,
        failing approval with `ERR_NO_ADVANCE_RATES_CONFIGURED` (422). A facility
        with zero configured rates cannot be approved because every subsequent
        advance would be unpriceable; exactly one rate row is sufficient."

        Design: Difficulty/boundary_precision_check/boundary_empty_collection_blocks_approval_and_zeroes_rollup
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        facility = fx.book_facility()

        validate_error(
            api_client.approve_facility(facility["id"], SECOND_CREDIT_OFFICER),
            ApiErrorId.ERR_NO_ADVANCE_RATES_CONFIGURED,
        )

        rates, meta = validate_paginated(
            api_client.list_product_advance_rates(facility["id"], CREDIT_OFFICER)
        )
        assert meta["total_count"] == 0
        assert rates == []
        assert fx.read_facility(facility["id"])["status"] == "PENDING_APPROVAL"

        fx.add_rate_row(facility["id"])
        approved = validate_success(
            api_client.approve_facility(facility["id"], SECOND_CREDIT_OFFICER)
        )
        asserts.assert_facility(approved)
        assert approved["status"] == "ACTIVE"

    def test_a_facility_with_no_advances_rolls_every_aggregate_up_to_zero(self):
        """An empty book reports literal zeroes and an empty exposure array.

        PRD 2.6: "The reconciliation view also republishes `facility_id`,
        `committed_amount_cents`, `availability_cents`,
        `accrued_fee_balance_cents`, `wet_outstanding_cents`,
        `aged_outstanding_cents`, `scratch_and_dent_outstanding_cents`,
        `open_margin_call_count` and an `investor_exposures` array carrying one
        entry per take-out investor of the facility with that investor's
        identifier and its `exposure_cents`."

        Design: Difficulty/boundary_precision_check/boundary_empty_collection_blocks_approval_and_zeroes_rollup
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        facility = fx.book_facility()
        fx.add_rate_row(facility["id"])
        fx.approve_facility(facility["id"])

        summary = fx.read_exposure_summary(facility["id"])

        assert summary["facility_id"] == facility["id"]
        assert summary["committed_amount_cents"] == 20_000_000_000
        assert summary["outstanding_principal_cents"] == 0
        assert summary["availability_cents"] == 20_000_000_000
        assert summary["accrued_fee_balance_cents"] == 0
        assert summary["wet_outstanding_cents"] == 0
        assert summary["aged_outstanding_cents"] == 0
        assert summary["scratch_and_dent_outstanding_cents"] == 0
        assert summary["ledger_debit_total_cents"] == 0
        assert summary["ledger_credit_total_cents"] == 0
        assert summary["advance_outstanding_sum_cents"] == 0
        assert summary["investor_exposures"] == []
        assert summary["open_margin_call_count"] == 0

        # Both conservation invariants hold trivially on an empty book.
        asserts.assert_both_conservation_invariants(summary)
        asserts.assert_availability_projection(summary)
