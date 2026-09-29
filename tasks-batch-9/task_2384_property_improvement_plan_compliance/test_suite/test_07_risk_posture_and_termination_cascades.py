"""The two risk variants, the cost-revision cascade, and the termination cascade."""

from __future__ import annotations

import pytest

from test_helpers import (
    acknowledged_plan,
    activate_phase,
    assert_field_equals,
    assert_ledger_contains,
    assert_plan_dimensions,
    assert_posture,
    assert_priority_ranks,
    book_crew,
    escalate_default_notice,
    file_dispute,
    issue_default_notice,
    issued_plan,
    ledger_entries,
    locked_budget,
    read_booking,
    read_budget,
    read_cost_summary,
    read_franchisee,
    read_item,
    read_phase,
    read_plan,
    read_property,
    read_risk_summary,
    register_contractor,
    resolve_dispute,
    run_compliance_sweep,
    schedule_phase,
    set_clock,
)


@pytest.fixture
def life_safety_item_due_inside_the_horizon(api):
    """An issued life-safety item five days short of its date, with the clock moved up to it."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "sprinklers",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-2.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Cascade Hospitality Partners",
        contact_email="compliance@cascadehp.example",
        trigger_type="RELICENSING",
    )
    set_clock(api, "2026-10-25T00:00:00Z")
    return scenario


class TestSnapshotAndProjectedRiskVariants:
    def test_the_snapshot_variant_reads_only_the_recorded_overdue_flag(
        self, api, life_safety_item_due_inside_the_horizon
    ):
        """"The **snapshot** variant treats an item as overdue exactly when its own overdue flag
        is true — that is, strictly past its `deadline_date`." "Moving the clock changes how
        subsequent requests evaluate date comparisons, but it does not itself recompute anything
        already stored."

        Design: Difficulty/dual_variant_calc/property_risk_score_snapshot_vs_projected
        """
        scenario = life_safety_item_due_inside_the_horizon

        risk = read_risk_summary(api, scenario.property_id)

        assert_field_equals(risk, "snapshot_score", 100, "risk summary")
        assert_field_equals(risk, "snapshot_posture", "COMPLIANT", "risk summary")
        assert_field_equals(risk, "overdue_life_safety_count", 0, "risk summary")
        item = read_item(api, scenario.item_id("sprinklers"))
        assert_field_equals(item, "deadline_date", "2026-10-30", "item")
        assert item["is_overdue"] is False, "an item is not overdue before its deadline date"

    def test_the_projected_variant_counts_unstarted_work_due_inside_the_horizon(
        self, api, life_safety_item_due_inside_the_horizon
    ):
        """"The **projected** variant treats an item as overdue when its overdue flag is true *or*
        when its `status` is `SCOPED` or `DEFERRED_PENDING_EXTENSION` and its `deadline_date` falls
        at or before the clock date advanced by 30 days: unstarted work due inside that horizon is
        treated as already missed." "Overdue life-safety items cost 25 points each".

        Design: Difficulty/dual_variant_calc/property_risk_score_snapshot_vs_projected
        """
        scenario = life_safety_item_due_inside_the_horizon

        risk = read_risk_summary(api, scenario.property_id)

        assert_field_equals(risk, "projected_score", 75, "risk summary")
        assert_field_equals(risk, "projected_posture", "AT_RISK", "risk summary")
        assert_field_equals(risk, "projected_life_safety_count", 1, "risk summary")
        assert_field_equals(risk, "projection_horizon_days", 30, "risk summary")

    def test_the_projected_variant_is_never_persisted(
        self, api, life_safety_item_due_inside_the_horizon
    ):
        """"The projected variant is never persisted; it is returned only by the property's risk
        read, and because it counts a superset of items it yields a strictly lower figure than the
        snapshot variant whenever such an item exists." "The penalty is 0 points when the total gap
        is 0".

        Design: Difficulty/dual_variant_calc/property_risk_score_snapshot_vs_projected
        """
        scenario = life_safety_item_due_inside_the_horizon

        prop = read_property(api, scenario.property_id)
        risk = read_risk_summary(api, scenario.property_id)

        assert_posture(prop, 100, "COMPLIANT")
        assert_field_equals(risk, "funding_gap_penalty", 0, "risk summary")
        assert risk["projected_score"] < risk["snapshot_score"], (
            "the projected variant counts a superset and must read strictly lower here: "
            f"{risk['projected_score']} vs {risk['snapshot_score']}"
        )


@pytest.fixture
def revised_cost_on_a_locked_plan(api):
    """A locked, exactly funded plan whose cheaper item is revised up beyond the authorisation."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "alpha",
                "category": "GUEST_FACING",
                "standards_reference": "GF-8.1.1",
                "brand_estimated_cost_cents": 4000000,
            },
            {
                "key": "beta",
                "category": "GUEST_FACING",
                "standards_reference": "GF-8.1.2",
                "brand_estimated_cost_cents": 5000000,
            },
        ],
        legal_name="Ironwood Hospitality LLC",
        contact_email="capital@ironwoodhospitality.example",
    )
    budget = locked_budget(api, scenario, 10642500, financing_source="MIXED")
    dispute = file_dispute(
        api,
        scenario,
        scenario.item_id("alpha"),
        claimed_cost_cents=9000000,
        dispute_basis="COST_ESTIMATE",
    )
    resolve_dispute(api, dispute["id"], "REVISE", revised_cost_cents=9000000)
    return scenario, budget


class TestCostRevisionCascade:
    def test_the_revision_rewrites_the_approved_cost_alone(self, api, revised_cost_on_a_locked_plan):
        """"Link one stores `revised_cost_cents` on the dispute and sets the contested item's
        `approved_cost_cents` to that value." "A ledger entry of type `COST_REVISED` is appended,
        carrying the disputed `item_id` and a `delta_cents` equal to the new revised cost less the
        item's previous `approved_cost_cents`".

        Design: Difficulty/transitive_cascade/cost_revision_cascade_five_links_to_franchisee_standing
        """
        scenario, _budget = revised_cost_on_a_locked_plan

        item = read_item(api, scenario.item_id("alpha"))

        assert_field_equals(item, "approved_cost_cents", 9000000, "revised item")
        assert_field_equals(item, "brand_estimated_cost_cents", 4000000, "revised item")
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "COST_REVISED",
            delta_cents=5000000,
            item_id=scenario.item_id("alpha"),
        )

    def test_the_requirement_and_the_ranking_are_both_recomputed(
        self, api, revised_cost_on_a_locked_plan
    ):
        """"Link two follows from the item's cost having changed: the plan's
        `funding_requirement_cents` is recomputed by the per-item-then-sum rule of §3.3, the
        priority ranking re-runs and rewrites `priority_rank` on every item of the plan". Within a
        category candidates are ordered "by `approved_cost_cents` descending, so the most expensive
        work in a band ranks first".

        Design: Difficulty/transitive_cascade/cost_revision_cascade_five_links_to_franchisee_standing
        """
        scenario, _budget = revised_cost_on_a_locked_plan

        alpha = read_item(api, scenario.item_id("alpha"))
        beta = read_item(api, scenario.item_id("beta"))

        assert_field_equals(alpha, "item_funding_cents", 10642500, "revised item")
        assert_field_equals(beta, "item_funding_cents", 5912500, "untouched item")
        assert_field_equals(
            read_plan(api, scenario.plan_id), "funding_requirement_cents", 16555000, "plan"
        )
        assert_priority_ranks([alpha, beta], {alpha["id"]: 1, beta["id"]: 2})

    def test_the_gap_knocks_the_locked_budget_underfunded(
        self, api, revised_cost_on_a_locked_plan
    ):
        """"Link three follows from the requirement having changed: `funding_gap_cents` is
        recomputed, and if the gap has become strictly positive the plan's active capital budget
        moves `LOCKED → UNDERFUNDED`, which silently closes the item-start gate until a replacement
        budget is authorised and locked."

        Design: Difficulty/transitive_cascade/cost_revision_cascade_five_links_to_franchisee_standing
        """
        scenario, budget = revised_cost_on_a_locked_plan

        assert_field_equals(read_budget(api, budget["id"]), "status", "UNDERFUNDED", "budget")
        assert_field_equals(
            read_cost_summary(api, scenario.plan_id), "funding_gap_cents", 5912500, "cost summary"
        )

    def test_the_cascade_reaches_the_property_and_then_the_franchisee(
        self, api, revised_cost_on_a_locked_plan
    ):
        """"Link four follows from the budget having gone `UNDERFUNDED`: the property's
        `compliance_risk_score` is recomputed with the tiered funding-gap penalty and its
        `compliance_posture` is re-derived. Link five follows from the posture having changed: the
        franchisee's `standing` is recomputed from the postures of all of that franchisee's
        properties."

        Design: Difficulty/transitive_cascade/cost_revision_cascade_five_links_to_franchisee_standing
        """
        scenario, _budget = revised_cost_on_a_locked_plan

        assert_posture(read_property(api, scenario.property_id), 75, "AT_RISK")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "WATCH", "franchisee"
        )
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id),
            status="OWNER_ACKNOWLEDGED",
            dispute_state="DISPUTE_RESOLVED_REVISED",
        )


@pytest.fixture
def noticed_plan_past_its_cure_deadline(api):
    """An overdue life-safety breach under notice, with the cure period already run out."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "alarm",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-4.4.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Redstone Lodging Trust",
        contact_email="trustee@redstonelodging.example",
    )
    budget = locked_budget(api, scenario, 1100000, financing_source="RESERVE_DRAW")
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=50,
    )
    contractor = register_contractor(
        api,
        name="Meridian Fire Systems",
        trade="FIRE_PROTECTION",
        brand_approved=True,
        max_concurrent_bookings=2,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    phase = activate_phase(api, scenario, phase["id"])
    booking = book_crew(
        api,
        scenario,
        contractor["id"],
        phase["id"],
        start_datetime="2026-09-02T08:00:00Z",
        end_datetime="2026-09-05T17:00:00Z",
        crew_size=6,
    )
    set_clock(api, "2026-10-31T00:00:00Z")
    run_compliance_sweep(api, scenario.plan_id)
    notice = issue_default_notice(api, scenario, cure_period_days=10)
    set_clock(api, "2026-11-11T00:00:00Z")
    return {
        "scenario": scenario,
        "budget": budget,
        "phase": phase,
        "booking": booking,
        "notice": notice,
    }


class TestTerminationCascade:
    def test_the_notice_snapshots_the_breach_and_prices_it(
        self, api, noticed_plan_past_its_cure_deadline
    ):
        """"It snapshots `breached_item_ids` as the ids of every item of the plan whose overdue
        flag is true at that instant, ordered by `priority_rank` ascending". "each item's
        `approved_cost_cents` is multiplied by its category's damages rate — 0.15 for
        `LIFE_SAFETY`, 0.08 for `GUEST_FACING`, 0.03 for `BACK_OF_HOUSE` — the exact per-item
        products are summed, and the total is rounded half up to whole cents **once, at the end**."

        Design: Difficulty/transitive_cascade/termination_cascade_from_notice_escalation
        """
        built = noticed_plan_past_its_cure_deadline
        scenario = built["scenario"]
        notice = built["notice"]

        assert_field_equals(notice, "status", "ISSUED", "notice")
        assert_field_equals(notice, "cure_deadline_date", "2026-11-10", "notice")
        assert_field_equals(notice, "liquidated_damages_cents", 150000, "notice")
        assert notice["breached_item_ids"] == [scenario.item_id("alarm")], (
            "the only overdue item should be snapshotted as the breach, got "
            f"{notice['breached_item_ids']!r}"
        )

    def test_escalation_terminates_the_plan_and_voids_its_children(
        self, api, noticed_plan_past_its_cure_deadline
    ):
        """"Link one moves the plan's `status` to `TERMINATED` and increments the plan's `version`
        by one. Link two, caused by link one, voids and cancels the plan's children: every item of
        the plan whose `status` is `SCOPED`, `DEFERRED_PENDING_EXTENSION`, `IN_PROGRESS`,
        `WORK_COMPLETE` or `PUNCH_FAIL` becomes `VOIDED` and thereby leaves every plan aggregate;
        every renovation phase whose `status` is `PLANNED` or `ACTIVE` becomes `CANCELLED`; and the
        plan's active capital budget becomes `CLOSED`."

        Design: Difficulty/transitive_cascade/termination_cascade_from_notice_escalation
        """
        built = noticed_plan_past_its_cure_deadline
        scenario = built["scenario"]

        escalated = escalate_default_notice(api, built["notice"]["id"])

        assert_field_equals(escalated, "status", "ESCALATED_TO_TERMINATION", "notice")
        assert_field_equals(read_plan(api, scenario.plan_id), "status", "TERMINATED", "plan")
        assert_field_equals(read_item(api, scenario.item_id("alarm")), "status", "VOIDED", "item")
        assert_field_equals(read_phase(api, built["phase"]["id"]), "status", "CANCELLED", "phase")
        assert_field_equals(read_budget(api, built["budget"]["id"]), "status", "CLOSED", "budget")

    def test_the_cancelled_phase_releases_its_crews_and_its_keys(
        self, api, noticed_plan_past_its_cure_deadline
    ):
        """"Link three, caused by link two, follows each cancelled phase: its still-`BOOKED`
        engagements become `CANCELLED`, and for any phase that had been `ACTIVE`, its
        `rooms_out_of_service` is subtracted from the property's `rooms_out_of_service_current`,
        restoring the key-inventory invariant."

        Design: Difficulty/transitive_cascade/termination_cascade_from_notice_escalation
        """
        built = noticed_plan_past_its_cure_deadline
        scenario = built["scenario"]

        escalate_default_notice(api, built["notice"]["id"])

        assert_field_equals(
            read_booking(api, built["booking"]["id"]), "status", "CANCELLED", "booking"
        )
        assert_field_equals(
            read_property(api, scenario.property_id),
            "rooms_out_of_service_current",
            0,
            "property",
        )

    def test_termination_reaches_the_property_and_the_whole_portfolio(
        self, api, noticed_plan_past_its_cure_deadline
    ):
        """"Link four, caused by link one, sets the property's `franchise_agreement_status` to
        `TERMINATED`. Link five, caused by link four, sets the property's `compliance_posture` to
        `TERMINATED` and the franchisee's `standing` to `TERMINATED_PORTFOLIO`. A ledger entry of
        type `PLAN_TERMINATED` is appended with a null item reference and a `delta_cents` of 0."

        Design: Difficulty/transitive_cascade/termination_cascade_from_notice_escalation
        """
        built = noticed_plan_past_its_cure_deadline
        scenario = built["scenario"]

        escalate_default_notice(api, built["notice"]["id"])

        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "franchise_agreement_status", "TERMINATED", "property")
        assert_field_equals(prop, "compliance_posture", "TERMINATED", "property")
        assert_field_equals(prop, "open_plan_count", 0, "property")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id),
            "standing",
            "TERMINATED_PORTFOLIO",
            "franchisee",
        )
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "PLAN_TERMINATED",
            delta_cents=0,
            item_id=None,
        )
