"""Supersession is a compensating movement: totals must land, not drift."""
import pytest

from test_helpers import fixtures as fx


#: A property whose first-party capacity is smaller than the mobilization charge,
#: so every rewrite of the cost is visible in more than one bucket.
NARROW_COVERAGE = {
    "first_party_coverage_limit_cents": 100000,
    "third_party_sublimit_cents": 5000000,
}


class TestExcavationScopeConservedAcrossSupersession:
    def test_first_approval_adds_its_own_scope_and_line_amount(self, api):
        """PRD §3.7: "The project's `approved_scope_cubic_yards` is always its `baseline_scope_cubic_yards` plus the sum of `additional_cubic_yards` over the project's change orders whose `status` is `APPROVED`. Rows in `DRAFT`, `SUBMITTED`, `REJECTED` or `SUPERSEDED` contribute nothing."
        PRD §3.7: "Once the latch is true, `remediation_cost_cents` is the flat mobilization charge of 185,000 cents — one thousand eight hundred fifty dollars — plus the line total from step two."
        PRD §2.9: "A change order's `line_amount_cents` is rounded half up to whole cents *per line, before any summation*."

        Design: Difficulty/compensating_invariant/excavation_scope_conserved_when_change_order_is_superseded
        """
        ctx = fx.project_remediation_active_gross()
        first = fx.approved_change_order(ctx, 3.5, 1001)

        assert first["line_amount_cents"] == 3504, (
            "3.5 cubic yards at 1001 cents on ordinary soil is 3503.5, which rounds "
            f"half up to 3504, got {first['line_amount_cents']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["approved_scope_cubic_yards"] == pytest.approx(11.5, abs=0.01), (
            "the 8.0-cubic-yard baseline plus 3.5 approved is 11.5, got "
            f"{project['approved_scope_cubic_yards']}"
        )
        assert project["remediation_cost_cents"] == 188504, (
            "185,000 cents of mobilization plus the 3504-cent line is 188,504, got "
            f"{project['remediation_cost_cents']}"
        )

    def test_supersession_removes_the_old_scope_exactly_as_it_adds_the_new(self, api):
        """PRD §3.7: "When `supersedes_change_order_id` was supplied, that prior row transitions `APPROVED → SUPERSEDED` and its `decided_at` is cleared to null, which is how its `additional_cubic_yards` leaves the approved-scope sum."
        PRD §3.7: "*Step one* computes each line amount, iterating the project's change orders whose `status` is `APPROVED` in ascending `created_at` order — never in identifier order."
        PRD §3.7: "`REJECTED` and `SUPERSEDED` are both terminal for a change-order row."

        Design: Difficulty/compensating_invariant/excavation_scope_conserved_when_change_order_is_superseded
        """
        ctx = fx.project_remediation_active_gross()
        first = fx.approved_change_order(ctx, 3.5, 1001)
        second = fx.approved_change_order(
            ctx, 2.5, 1001, supersedes_change_order_id=first["id"]
        )

        superseded = fx.read_change_order(first["id"])
        assert superseded["status"] == "SUPERSEDED", (
            f"the replaced row must leave APPROVED, got {superseded['status']}"
        )
        assert superseded["decided_at"] is None, (
            "the supersession clears the decision instant, got "
            f"{superseded['decided_at']}"
        )
        assert superseded["line_amount_cents"] == 3504, (
            "the replaced row keeps the line amount it was approved with, because the "
            f"cost rebuild only iterates approved rows, got {superseded['line_amount_cents']}"
        )

        assert second["status"] == "APPROVED", (
            f"the replacing row must be approved, got {second['status']}"
        )
        assert second["line_amount_cents"] == 2503, (
            "2.5 cubic yards at 1001 cents is 2502.5, which rounds half up to 2503, "
            f"got {second['line_amount_cents']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["approved_scope_cubic_yards"] == pytest.approx(10.5, abs=0.01), (
            "only the replacing row's 2.5 cubic yards remain on top of the baseline, "
            f"got {project['approved_scope_cubic_yards']}"
        )
        assert project["remediation_cost_cents"] == 187503, (
            "185,000 cents of mobilization plus the single 2503-cent line is 187,503, "
            f"got {project['remediation_cost_cents']}"
        )


class TestInsuranceWaterfallConservedAcrossSupersession:
    def _tendered_project_with_a_first_change_order(self):
        ctx = fx.project_at_sampling(property_overrides=NARROW_COVERAGE)
        ctx["first_party_notification"] = fx.create_notification(
            ctx["project"]["id"], "FIRST_PARTY"
        )
        ctx["third_party_notification"] = fx.create_notification(
            ctx["project"]["id"], "THIRD_PARTY_LIABILITY"
        )
        ctx["sample"] = fx.collect_sample_with_result(ctx, 6200.0, 1.2, "TANK_BOTTOM", 96)
        ctx["first_order"] = fx.approved_change_order(ctx, 3.5, 1001)
        return ctx

    def test_waterfall_totals_sum_to_the_cost_after_the_first_approval(self, api):
        """PRD §3.8: "Bucket three is the homeowner, and it is unbounded. `homeowner_out_of_pocket_cents` is the project's `remediation_cost_cents` less `first_party_allocated_cents` less `third_party_allocated_cents`. Finally `reserve_amount_cents` is `first_party_allocated_cents` plus `third_party_allocated_cents` — the carrier's total exposure. Every non-closed notification on the project carries the identical triple, and the three parts always sum exactly to the project's `remediation_cost_cents`."
        PRD §3.8: "The waterfall re-runs on every occasion the project's `remediation_cost_cents` moves — the project entering `REMEDIATION_ACTIVE`, a change order being approved, a change order being superseded, and a closure letter being rescinded — as well as on the creation of a notification."

        Design: Difficulty/compensating_invariant/insurance_waterfall_totals_conserved_across_change_order_supersession
        """
        ctx = self._tendered_project_with_a_first_change_order()

        assert fx.read_project(ctx["project"]["id"])["remediation_cost_cents"] == 188504, (
            "the cost under test is the mobilization charge plus one 3504-cent line"
        )

        tender = fx.read_notification(ctx["first_party_notification"]["id"])
        assert tender["first_party_allocated_cents"] == 100000, (
            "bucket one fills to the 100,000-cent first-party capacity, got "
            f"{tender['first_party_allocated_cents']}"
        )
        assert tender["third_party_allocated_cents"] == 88504, (
            "the 88,504-cent remainder falls inside the liability sublimit, got "
            f"{tender['third_party_allocated_cents']}"
        )
        assert tender["homeowner_out_of_pocket_cents"] == 0, (
            "the two carrier buckets absorb the whole cost, got "
            f"{tender['homeowner_out_of_pocket_cents']}"
        )
        assert tender["reserve_amount_cents"] == 188504, (
            "the reserve is the sum of the first two buckets, got "
            f"{tender['reserve_amount_cents']}"
        )
        assert (
            tender["first_party_allocated_cents"]
            + tender["third_party_allocated_cents"]
            + tender["homeowner_out_of_pocket_cents"]
        ) == 188504, "the three parts must sum exactly to the remediation cost"

    def test_supersession_rewrites_every_live_tender_to_the_new_total(self, api):
        """PRD §3.8: "It is pure integer-cent arithmetic with no rounding anywhere."
        PRD §3.8: "It equals the property's `third_party_sublimit_cents` **only if** the project has at least one notification whose `notification_kind` is `THIRD_PARTY_LIABILITY` and whose `status` is `OPEN`, `RESERVED` or `THIRD_PARTY_REVIEW`; with no such live tender on the project, bucket two's capacity is zero."
        PRD §3.7: "The project's `approved_scope_cubic_yards` and `remediation_cost_cents` are then recomputed, the cost change re-runs the insurance waterfall over every non-closed notification of the project and re-derives each notification's `status`, and the blocker list is recomputed."

        Design: Difficulty/compensating_invariant/insurance_waterfall_totals_conserved_across_change_order_supersession
        """
        ctx = self._tendered_project_with_a_first_change_order()
        fx.approved_change_order(
            ctx, 2.5, 1001, supersedes_change_order_id=ctx["first_order"]["id"]
        )

        assert fx.read_project(ctx["project"]["id"])["remediation_cost_cents"] == 187503, (
            "the supersession leaves a single 2503-cent line on top of mobilization"
        )

        liability = fx.read_notification(ctx["third_party_notification"]["id"])
        assert liability["first_party_allocated_cents"] == 100000, (
            "bucket one is still capped at 100,000 cents, got "
            f"{liability['first_party_allocated_cents']}"
        )
        assert liability["third_party_allocated_cents"] == 87503, (
            "the remainder shrinks by exactly the 1001-cent difference between the "
            f"two lines, got {liability['third_party_allocated_cents']}"
        )
        assert liability["homeowner_out_of_pocket_cents"] == 0, (
            "nothing overflows to the homeowner, got "
            f"{liability['homeowner_out_of_pocket_cents']}"
        )
        assert liability["reserve_amount_cents"] == 187503, (
            "the reserve tracks the lowered cost exactly, got "
            f"{liability['reserve_amount_cents']}"
        )

        property_tender = fx.read_notification(ctx["first_party_notification"]["id"])
        assert property_tender["third_party_allocated_cents"] == 87503, (
            "every non-closed notification carries the identical triple, got "
            f"{property_tender['third_party_allocated_cents']}"
        )
