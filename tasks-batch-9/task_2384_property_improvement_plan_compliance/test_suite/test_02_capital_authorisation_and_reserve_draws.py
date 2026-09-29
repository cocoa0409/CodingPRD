"""Authorising capital, the lock that opens execution, and the conserved reserve corpus."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    approve_budget,
    assert_field_equals,
    assert_ledger_contains,
    assert_reserve_corpus_conserved,
    authorize_budget,
    consent_draw,
    credit_reserve_contribution,
    current_plan_version,
    disburse_draw,
    ledger_entries,
    list_rows,
    lock_budget,
    locked_budget,
    read_budget,
    read_cost_summary,
    read_draw,
    read_item,
    read_plan,
    read_property,
    request_draw,
    validate_error,
    validate_success,
)


@pytest.fixture
def under_authorized_draft_budget(api):
    """A budget authorising less than the escalated scope needs, still sitting in draft."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "atrium",
                "category": "GUEST_FACING",
                "standards_reference": "GF-9.2.2",
                "brand_estimated_cost_cents": 4000000,
            }
        ],
        legal_name="Wheatfield Inns Co",
        contact_email="finance@wheatfieldinns.example",
    )
    budget = authorize_budget(api, scenario, 4000000, financing_source="TERM_LOAN")
    return scenario, budget


class TestLockStateCheckOutranksTheFundingGapCheck:
    def test_locking_a_draft_budget_reports_the_state_failure(
        self, api, under_authorized_draft_budget
    ):
        """"a lock attempted on a budget still in `DRAFT` reports `ERR_BUDGET_NOT_LOCKABLE`, not
        `ERR_BUDGET_UNDERFUNDED`, even when the plan also carries a gap."

        Design: Difficulty/priority_pair_validation_conflict/lock_state_check_outranks_funding_gap_check
        """
        scenario, budget = under_authorized_draft_budget

        response = api.lock_capital_budget(budget["id"], scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_BUDGET_NOT_LOCKABLE, 409)
        assert_field_equals(read_budget(api, budget["id"]), "status", "DRAFT", "budget")

    def test_the_funding_gap_surfaces_only_once_the_state_precondition_holds(
        self, api, under_authorized_draft_budget
    ):
        """"the lock is refused unless the budget is in `APPROVED` (`ERR_BUDGET_NOT_LOCKABLE`),
        unless the acting `X-User-ID` is the property's `franchisee_id`
        (`ERR_NOT_PROPERTY_FRANCHISEE`), and unless the plan's `funding_gap_cents` is exactly 0
        (`ERR_BUDGET_UNDERFUNDED`)".

        Design: Difficulty/priority_pair_validation_conflict/lock_state_check_outranks_funding_gap_check
        """
        scenario, budget = under_authorized_draft_budget

        approved = approve_budget(api, budget["id"])
        assert_field_equals(approved, "status", "APPROVED", "budget")

        response = api.lock_capital_budget(budget["id"], scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_BUDGET_UNDERFUNDED, 409)
        assert_field_equals(read_budget(api, budget["id"]), "status", "APPROVED", "budget")

    def test_the_gap_is_the_escalated_requirement_less_the_authorisation(
        self, api, under_authorized_draft_budget
    ):
        """"it is the funding requirement minus the active budget's `total_authorized_cents`,
        floored at 0 — a requirement below the authorisation leaves no gap rather than a negative
        one."

        Design: Difficulty/priority_pair_validation_conflict/lock_state_check_outranks_funding_gap_check
        """
        scenario, _budget = under_authorized_draft_budget

        summary = read_cost_summary(api, scenario.plan_id)

        assert_field_equals(summary, "funding_requirement_cents", 4730000, "cost summary")
        assert_field_equals(summary, "authorized_cents", 4000000, "cost summary")
        assert_field_equals(summary, "funding_gap_cents", 730000, "cost summary")


@pytest.fixture
def two_item_plan_with_approved_budget(api):
    """Two guest-facing items and a fully funded budget that has been approved but not locked."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "lobby",
                "category": "GUEST_FACING",
                "standards_reference": "GF-2.1.1",
                "brand_estimated_cost_cents": 1000000,
            },
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-2.1.2",
                "brand_estimated_cost_cents": 1000000,
            },
        ],
        legal_name="Westmark Hotels Inc",
        contact_email="projects@westmarkhotels.example",
    )
    budget = authorize_budget(api, scenario, 2365000, financing_source="OWNER_EQUITY")
    approve_budget(api, budget["id"])
    return scenario, budget


class TestItemStartReadsTheBudgetLockState:
    def test_an_approved_but_unlocked_budget_does_not_open_execution(
        self, api, two_item_plan_with_approved_budget
    ):
        """"The plan's active capital budget must exist and be `LOCKED`, or
        `ERR_BUDGET_NOT_LOCKED` — a budget never locked, one superseded by a replacement, or one
        knocked to `UNDERFUNDED` by a cost revision all fail this gate identically."

        Design: Difficulty/cross_entity_state_dependency/item_start_gated_by_capital_budget_lock_state
        """
        scenario, _budget = two_item_plan_with_approved_budget

        response = api.start_item(scenario.item_id("lobby"), scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_BUDGET_NOT_LOCKED, 409)
        assert_field_equals(read_item(api, scenario.item_id("lobby")), "status", "SCOPED", "item")

    def test_locking_the_budget_opens_execution_and_advances_the_plan(
        self, api, two_item_plan_with_approved_budget
    ):
        """"Locking is what opens item execution, since a locked active budget is the gate every
        item start reads." "The item moves `SCOPED → IN_PROGRESS` and its `version` increments.
        Because the item left `SCOPED`, if the plan's `status` was `OWNER_ACKNOWLEDGED` the plan
        advances `OWNER_ACKNOWLEDGED → IN_EXECUTION`".

        Design: Difficulty/cross_entity_state_dependency/item_start_gated_by_capital_budget_lock_state
        """
        scenario, budget = two_item_plan_with_approved_budget
        lock_budget(api, scenario, budget["id"])

        started = validate_success(
            api.start_item(scenario.item_id("lobby"), scenario.owner_headers)
        )

        assert_field_equals(started, "status", "IN_PROGRESS", "item")
        assert_field_equals(read_plan(api, scenario.plan_id), "status", "IN_EXECUTION", "plan")

    def test_superseding_the_locked_budget_closes_the_gate_for_the_next_item(
        self, api, two_item_plan_with_approved_budget
    ):
        """"superseding a `LOCKED` budget removes the gate every item start reads, so no further
        item of that plan may start until the replacement budget is itself locked". "Any existing
        budget of the same plan whose `status` is `DRAFT`, `APPROVED`, `LOCKED` or `UNDERFUNDED`
        becomes `SUPERSEDED` and stops being the plan's active budget".

        Design: Difficulty/cross_entity_state_dependency/item_start_gated_by_capital_budget_lock_state
        """
        scenario, first_budget = two_item_plan_with_approved_budget
        lock_budget(api, scenario, first_budget["id"])
        validate_success(api.start_item(scenario.item_id("lobby"), scenario.owner_headers))

        replacement = authorize_budget(
            api,
            scenario,
            2365000,
            financing_source="TERM_LOAN",
            expected_plan_version=current_plan_version(api, scenario.plan_id),
        )

        response = api.start_item(scenario.item_id("corridors"), scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_BUDGET_NOT_LOCKED, 409)
        assert_field_equals(
            read_budget(api, first_budget["id"]), "status", "SUPERSEDED", "first budget"
        )
        assert_field_equals(read_budget(api, replacement["id"]), "status", "DRAFT", "replacement")
        assert_field_equals(
            read_item(api, scenario.item_id("corridors")), "status", "SCOPED", "second item"
        )
        assert_field_equals(
            read_item(api, scenario.item_id("lobby")), "status", "IN_PROGRESS", "first item"
        )


@pytest.fixture
def disbursed_reserve_draw(api):
    """A contribution, a locked reserve-financed budget, and one draw already paid out."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "ffe",
                "category": "GUEST_FACING",
                "standards_reference": "GF-4.4.4",
                "brand_estimated_cost_cents": 4000000,
            }
        ],
        legal_name="Sablepoint Hospitality LLC",
        contact_email="treasury@sablepoint.example",
    )
    credit_reserve_contribution(api, scenario.portfolio, 1000000)
    budget = locked_budget(api, scenario, 4730000, financing_source="RESERVE_DRAW")
    draw = request_draw(api, scenario, budget["id"], scenario.item_id("ffe"), 4000000)
    consent_draw(api, draw["id"], "CONSENT")
    draw = disburse_draw(api, scenario, draw["id"])
    return scenario, budget, draw


class TestReserveCorpusConservation:
    def test_a_contribution_raises_both_the_balance_and_the_contributed_total(self, api):
        """"the contribution adds that amount to both `reserve_balance_cents` and
        `reserve_contributed_total_cents`, so the reserve corpus of §2.10 still balances".
        "`initial_reserve_balance_cents` is set to the supplied `reserve_balance_cents` and
        becomes the immutable anchor of the reserve-corpus invariant".

        Design: Difficulty/compensating_invariant/reserve_corpus_conserved_across_draw_and_reversal
        """
        scenario = acknowledged_plan(
            api,
            [
                {
                    "key": "ffe",
                    "category": "GUEST_FACING",
                    "standards_reference": "GF-4.4.4",
                    "brand_estimated_cost_cents": 4000000,
                }
            ],
            legal_name="Sablepoint Hospitality LLC",
            contact_email="treasury@sablepoint.example",
        )
        credit_reserve_contribution(api, scenario.portfolio, 1000000)

        prop = read_property(api, scenario.property_id)

        assert_field_equals(prop, "initial_reserve_balance_cents", 50000000, "property")
        assert_field_equals(prop, "reserve_contributed_total_cents", 1000000, "property")
        assert_field_equals(prop, "reserve_balance_cents", 51000000, "property")
        assert_reserve_corpus_conserved(prop, [])

    def test_disbursement_moves_cash_out_of_the_balance_and_commits_the_budget(
        self, api, disbursed_reserve_draw
    ):
        """"the draw's `amount_cents` is subtracted from `reserve_balance_cents` and the
        property's `version` increments; `disbursed_at` is stamped with the logical clock; the
        funding budget's `committed_cents` increases by the same amount".

        Design: Difficulty/compensating_invariant/reserve_corpus_conserved_across_draw_and_reversal
        """
        scenario, budget, draw = disbursed_reserve_draw

        prop = read_property(api, scenario.property_id)

        assert_field_equals(draw, "status", "DISBURSED", "draw")
        assert_field_equals(prop, "reserve_balance_cents", 47000000, "property")
        assert_field_equals(read_budget(api, budget["id"]), "committed_cents", 4000000, "budget")
        assert_reserve_corpus_conserved(prop, [read_draw(api, draw["id"])])

    def test_reversal_restores_the_balance_and_the_budget_commitment(
        self, api, disbursed_reserve_draw
    ):
        """"Reversal adds the `amount_cents` back to `reserve_balance_cents` and increments the
        property's `version`, subtracts the same amount from the budget's `committed_cents`".
        "After the disbursement-and-reversal pair, the reserve corpus of §2.10 balances exactly
        as it did before."

        Design: Difficulty/compensating_invariant/reserve_corpus_conserved_across_draw_and_reversal
        """
        scenario, budget, draw = disbursed_reserve_draw

        reversed_draw = validate_success(
            api.reverse_reserve_draw(draw["id"], scenario.owner_headers)
        )

        prop = read_property(api, scenario.property_id)
        assert_field_equals(reversed_draw, "status", "REVERSED", "draw")
        assert_field_equals(prop, "reserve_balance_cents", 51000000, "property")
        assert_field_equals(read_budget(api, budget["id"]), "committed_cents", 0, "budget")
        assert_reserve_corpus_conserved(prop, [reversed_draw])

    def test_the_reversed_draw_leaves_the_outstanding_disbursed_set(
        self, api, disbursed_reserve_draw
    ):
        """"A disbursement moves money from the balance into the outstanding-disbursed set; the
        compensating reversal moves it back and drops the draw out of that set, so the pair leaves
        the conserved total exactly unchanged and no cent drifts."

        Design: Difficulty/compensating_invariant/reserve_corpus_conserved_across_draw_and_reversal
        """
        scenario, _budget, draw = disbursed_reserve_draw
        validate_success(api.reverse_reserve_draw(draw["id"], scenario.owner_headers))

        rows, _meta = list_rows(
            api, "list_reserve_draws", property_id=scenario.property_id, status="DISBURSED"
        )

        assert rows == [], f"no draw of the property should remain DISBURSED, got {rows}"

    def test_both_cash_movements_are_recorded_in_the_ledger(self, api, disbursed_reserve_draw):
        """"a ledger entry of type `DRAW_DISBURSED` is appended, carrying the draw's
        `purpose_item_id` as its item reference and the draw amount as a positive `delta_cents`".
        Reversal "appends a `DRAW_REVERSED` ledger entry carrying the `purpose_item_id` and the
        draw amount negated as `delta_cents`".

        Design: Difficulty/compensating_invariant/reserve_corpus_conserved_across_draw_and_reversal
        """
        scenario, _budget, draw = disbursed_reserve_draw
        validate_success(api.reverse_reserve_draw(draw["id"], scenario.owner_headers))

        entries = ledger_entries(api, plan_id=scenario.plan_id)

        assert_ledger_contains(
            entries,
            "DRAW_DISBURSED",
            delta_cents=4000000,
            item_id=scenario.item_id("ffe"),
            count=1,
        )
        assert_ledger_contains(
            entries,
            "DRAW_REVERSED",
            delta_cents=-4000000,
            item_id=scenario.item_id("ffe"),
            count=1,
        )
