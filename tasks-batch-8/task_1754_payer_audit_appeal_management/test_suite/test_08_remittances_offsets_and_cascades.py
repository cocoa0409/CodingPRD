"""Remittance offset accounting: the auto-waterfall (order, per-demand
rounding, ON_HOLD exclusion), manual offset ceilings, double-reverse
lockdown, the two conservation invariants, and the full-vindication reversal
cascade."""
from test_helpers import (
    ApiErrorId,
    allocate_remittance,
    assert_offset_transaction,
    create_remittance,
    decide_appeal,
    get_demand,
    get_line,
    get_remittance,
    get_case,
    get_success_data,
    manual_offset,
    manual_offset_payload,
    reverse_offset,
    setup_case_with_demand,
    setup_full_reversal_scenario,
    setup_waterfall_rounding_scenario,
    validate_error,
    validate_paginated,
    file_appeal,
    open_appeal,
)
from test_helpers import TEST_USERS

ACCOUNTANT = TEST_USERS["accountant_headers"]
READER = TEST_USERS["reader_headers"]


class TestWaterfallAllocation:
    def test_waterfall_order_and_per_demand_interest_rounding(self, api):
        """PRD §3.8: "Candidate demands are those of the same payer in
        `DEMANDED` or `PARTIALLY_RECOUPED` — `ON_HOLD` demands are excluded —
        visited in `issued_at` ascending order with `created_at` ascending as
        the tie-break."
        PRD §3.8: "it computes the demand's accrued interest and rounds it half
        up to whole cents for that demand before any portions are calculated"
        PRD §3.8: "Two demands each accruing a raw three hundred thirty-three
        and a third cents therefore contribute three hundred thirty-three cents
        each — six hundred sixty-six cents of interest in total, not six
        hundred sixty-seven."

        Design: Difficulty/combinatorial_formula/offset_waterfall_per_demand_rounding
        """
        scn = setup_waterfall_rounding_scenario()
        offsets = allocate_remittance(scn["remittance"]["id"])
        assert len(offsets) == 2
        first, second = offsets
        assert first["recoupment_demand_id"] == scn["d1"]["id"], (
            "issued_at ties break by created_at ascending: first-created "
            "demand is allocated first")
        assert first["interest_portion_cents"] == 333
        assert second["recoupment_demand_id"] == scn["d2"]["id"]
        assert second["interest_portion_cents"] == 333
        assert first["interest_portion_cents"] + second[
            "interest_portion_cents"] == 666, (
            "Per-demand round-half-up: 333 + 333, never round(666.66) = 667")

    def test_waterfall_principal_portions_and_remainder(self, api):
        """PRD §3.8: "the interest portion takes the smaller of the remaining
        funds and that interest figure; the principal portion then takes the
        smaller of what is left and the demand's outstanding principal; and
        whenever the combined application is positive, an `APPLIED` offset with
        `allocation_mode` `AUTO_WATERFALL` is created and the remainder is
        reduced by the applied amount."
        PRD §3.8: "A remittance's `available_cents` is derived as its gross
        amount minus the amounts of all `APPLIED` offsets drawn on it"

        Design: Difficulty/combinatorial_formula/offset_waterfall_per_demand_rounding
        """
        scn = setup_waterfall_rounding_scenario()
        offsets = allocate_remittance(scn["remittance"]["id"])
        for offset in offsets:
            assert_offset_transaction(offset)
            assert offset["allocation_mode"] == "AUTO_WATERFALL"
            assert offset["principal_portion_cents"] == 33333
        rem = get_remittance(scn["remittance"]["id"])
        assert rem["available_cents"] == 32668, (
            "100000 - 2 * (333 + 33333)")

    def test_waterfall_skips_on_hold_demands(self, api):
        """PRD §3.8: "Candidate demands are those of the same payer in
        `DEMANDED` or `PARTIALLY_RECOUPED` — `ON_HOLD` demands are excluded"

        Design: Corner/calculations/waterfall_skips_on_hold_demands
        """
        ctx, demand = setup_case_with_demand(
            billed=100000, principal=100000,
            payer_overrides={"hold_levels": ["LEVEL_1"]})
        appeal = open_appeal(ctx["lines"][0]["id"])
        file_appeal(appeal["id"])
        assert get_demand(demand["id"])["status"] == "ON_HOLD"
        rem = create_remittance(ctx["payer"]["id"], 50000)
        offsets = get_success_data(api.allocate_remittance(rem["id"],
                                                           ACCOUNTANT))
        assert offsets == [], "The only candidate is ON_HOLD, so none apply"
        rem = get_remittance(rem["id"])
        assert rem["available_cents"] == 50000
        assert rem["status"] == "RECEIVED"
        _data, meta = validate_paginated(
            api.list_demand_offsets(demand["id"], READER))
        assert meta["total_count"] == 0


class TestManualOffsetCeiling:
    def test_amount_over_outstanding_rejected(self, api):
        """PRD §3.8: "the amount may not exceed the smaller of the remittance's
        `available_cents` and the demand's outstanding principal plus its
        accrued interest, else `ERR_OFFSET_EXCEEDS_OUTSTANDING` (HTTP 409)."

        Design: Corner/validations/offset_exceeds_outstanding_rejected
        """
        ctx, demand = setup_case_with_demand(billed=100000, principal=100000)
        rem = create_remittance(ctx["payer"]["id"], 200000)
        resp = api.create_manual_offset(
            demand["id"], manual_offset_payload(rem["id"], 100001),
            ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_OFFSET_EXCEEDS_OUTSTANDING)


class TestOffsetReversal:
    def test_double_reverse_rejected_and_no_double_credit(self, api):
        """PRD §3.8: "Reversal unwinds an offset. A `PFSAccountant` — or the
        system itself, inside the full-vindication cascade of §3.5 — moves an
        `APPLIED` offset to `REVERSED`, its terminal state"
        PRD §2.9: "State guards — the target must be in a state that permits
        the requested transition, else `ERR_INVALID_STATE_TRANSITION` (409)"

        Design: Corner/state_machines/offset_double_reverse_rejected
        """
        ctx, demand = setup_case_with_demand(billed=100000, principal=100000)
        rem = create_remittance(ctx["payer"]["id"], 40000)
        offset = manual_offset(demand["id"], rem["id"], 40000)
        reverse_offset(offset["id"])
        resp = api.reverse_offset(offset["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_demand(demand["id"])["outstanding_principal_cents"] == 100000, (
            "The demand is credited exactly once")


class TestConservationInvariants:
    def test_demand_principal_conserved_when_offset_applied(self, api):
        """PRD §3.7: "`outstanding_principal_cents` is the `principal_cents`
        minus the principal portions of all `APPLIED` offsets minus
        `written_off_cents`"

        Design: Difficulty/compensating_invariant/demand_principal_conservation
        """
        ctx, demand = setup_case_with_demand(billed=500000, principal=500000)
        rem = create_remittance(ctx["payer"]["id"], 300000)
        offset = manual_offset(demand["id"], rem["id"], 200000)
        assert offset["principal_portion_cents"] == 200000
        mid = get_demand(demand["id"])
        assert mid["outstanding_principal_cents"] == 300000
        assert mid["written_off_cents"] == 0, (
            "500000 == 200000 applied + 0 written off + 300000 outstanding")

    def test_demand_principal_conserved_after_compensating_reversal(self, api):
        """PRD §3.8: "The demand's `outstanding_principal_cents` is increased
        by the offset's `principal_portion_cents` and its status recomputed:
        reversed offsets are never counted, so a `FULLY_RECOUPED` demand falls
        back to `PARTIALLY_RECOUPED` or `DEMANDED` as the arithmetic dictates."

        Design: Difficulty/compensating_invariant/demand_principal_conservation
        """
        ctx, demand = setup_case_with_demand(billed=500000, principal=500000)
        rem = create_remittance(ctx["payer"]["id"], 300000)
        offset = manual_offset(demand["id"], rem["id"], 200000)
        reverse_offset(offset["id"])
        end = get_demand(demand["id"])
        assert end["outstanding_principal_cents"] == 500000
        assert end["status"] == "DEMANDED", (
            "500000 == 0 applied + 0 written off + 500000 outstanding: the "
            "reversal restores principal exactly, with zero drift")

    def test_remittance_gross_conserved_when_offset_applied(self, api):
        """PRD §3.8: "A remittance's `available_cents` is derived as its gross
        amount minus the amounts of all `APPLIED` offsets drawn on it, and its
        status follows from that figure: equal to the gross amount means
        `RECEIVED`, exactly zero means `FULLY_ALLOCATED`, and anything in
        between means `PARTIALLY_ALLOCATED`."

        Design: Difficulty/compensating_invariant/remittance_gross_conservation
        """
        ctx, demand = setup_case_with_demand(billed=500000, principal=500000)
        rem = create_remittance(ctx["payer"]["id"], 300000)
        assert rem["available_cents"] == 300000
        assert rem["status"] == "RECEIVED"
        offset = manual_offset(demand["id"], rem["id"], 200000)
        assert offset["amount_cents"] == 200000
        mid = get_remittance(rem["id"])
        assert mid["available_cents"] == 100000
        assert mid["status"] == "PARTIALLY_ALLOCATED", (
            "300000 == 200000 applied + 100000 available")

    def test_remittance_gross_conserved_after_compensating_reversal(self, api):
        """PRD §3.8: "Reversals flow backward through the same derivation: a
        `FULLY_ALLOCATED` remittance whose offset is reversed returns to
        `PARTIALLY_ALLOCATED`, and a `PARTIALLY_ALLOCATED` remittance restored
        to its full gross returns to `RECEIVED`."
        PRD §3.8: "The remittance's `available_cents` is increased by the
        offset's `amount_cents` and its status recomputed by the same
        derivation."

        Design: Difficulty/compensating_invariant/remittance_gross_conservation
        """
        ctx, demand = setup_case_with_demand(billed=500000, principal=500000)
        rem = create_remittance(ctx["payer"]["id"], 300000)
        offset = manual_offset(demand["id"], rem["id"], 200000)
        reverse_offset(offset["id"])
        end = get_remittance(rem["id"])
        assert end["available_cents"] == 300000
        assert end["status"] == "RECEIVED", (
            "300000 == 0 applied + 300000 available after the compensating "
            "reversal")


class TestFullVindicationCascade:
    def test_favorable_decision_overturns_line_and_bubbles_totals(self, api):
        """PRD §3.5: "An `outcome` of `FAVORABLE` requires `upheld_cents` to be
        exactly zero. The appeal lands `DECIDED_FAVORABLE`; the claim line
        moves to `OVERTURNED`; the line's `denied_amount_cents` is added to the
        case's `total_overturned_cents` and then zeroed."

        Design: Difficulty/transitive_cascade/favorable_decision_full_reversal_cascade
        """
        scn = setup_full_reversal_scenario()
        decide_appeal(scn["appeal"]["id"], scn["ctx"]["payer"]["id"],
                      "FAVORABLE", 0)
        line = get_line(scn["ctx"]["lines"][0]["id"])
        assert line["status"] == "OVERTURNED"
        assert line["denied_amount_cents"] == 0
        case = get_case(scn["ctx"]["case"]["id"])
        assert case["total_overturned_cents"] == 500000
        assert case["total_denied_active_cents"] == 0

    def test_full_vindication_reverses_demand_offset_and_credits_remittance(
            self, api):
        """PRD §3.5: "When a decision leaves the case's
        `total_denied_active_cents` at zero, every recoupment demand of the
        case in `DEMANDED`, `ON_HOLD`, `PARTIALLY_RECOUPED`, or
        `FULLY_RECOUPED` moves to `REVERSED` — the last of these modeling a
        post-recoupment refund. Each reversed demand's `APPLIED` offsets move
        to `REVERSED` with `reversed_at` stamped; each reversed offset credits
        its `amount_cents` back to its remittance's `available_cents` with the
        remittance's status recomputed; and each reversed demand's
        `outstanding_principal_cents` is restored to its `principal_cents`
        minus any `written_off_cents`."

        Design: Difficulty/transitive_cascade/favorable_decision_full_reversal_cascade
        """
        scn = setup_full_reversal_scenario()
        decide_appeal(scn["appeal"]["id"], scn["ctx"]["payer"]["id"],
                      "FAVORABLE", 0)
        demand = get_demand(scn["demand"]["id"])
        assert demand["status"] == "REVERSED"
        assert demand["outstanding_principal_cents"] == 500000
        offsets, _meta = validate_paginated(
            api.list_demand_offsets(scn["demand"]["id"], READER))
        assert offsets[0]["status"] == "REVERSED"
        rem = get_remittance(scn["remittance"]["id"])
        assert rem["available_cents"] == 200000
        assert rem["status"] == "RECEIVED"
