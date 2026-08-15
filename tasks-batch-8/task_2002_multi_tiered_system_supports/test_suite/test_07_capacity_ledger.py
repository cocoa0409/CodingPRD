"""The interventionist capacity ledger: additive minutes across plans and
conservation across create/terminate pairs (PRD §2.8, §3.2, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_catalog_entry,
    add_interventionist,
    committed_minutes,
    create_plan,
    create_plan_payload,
    get_plan,
    get_student,
    pause_plan,
    setup_active_plan,
    setup_students_with_ratified_tiers,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["team_lead_headers"]


class TestAdditiveMinutesAcrossPlans:
    def test_second_plan_over_combined_capacity_rejected(self, api):
        """PRD §3.2: "When a plan is proposed against an interventionist, the
        system adds the plan's weekly demand to the interventionist's current
        commitments and compares the total against `weekly_minute_capacity`; the
        boundary is inclusive, so a proposal that consumes the final available
        minute succeeds. Anything beyond capacity is refused with
        `ERR_CAPACITY_EXCEEDED`."

        Two plans costing 90 minutes each against a capacity of 120: the first
        fits (90 <= 120), the second would total 180 > 120 and is refused.

        Design: Difficulty/resource_temporal_overlap/interventionist_minutes_budget_overlap
        """
        ctx = setup_students_with_ratified_tiers(api, raw_scores=[80, 82])
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        e1, e2 = ctx["students"]
        catalog_entry = add_catalog_entry(api, d_id, tier_target="TIER_2",
                                          session_minutes=30, sessions_per_week=3)
        interventionist = add_interventionist(api, d_id, s_id,
                                              weekly_minute_capacity=120)

        plan1 = create_plan(api, d_id, s_id, e1["id"], catalog_entry["id"],
                            interventionist["id"])
        assert plan1["status"] == "ACTIVE"
        assert committed_minutes(api, {"district": ctx["district"],
                                       "school": ctx["school"],
                                       "interventionist": interventionist}) == 90

        e2_now = get_student(api, d_id, s_id, e2["id"])
        resp = api.create_plan(
            d_id, s_id, e2["id"],
            create_plan_payload(catalog_entry["id"], interventionist["id"],
                                e2_now["version"]),
            LEAD)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)
        # The first plan is untouched and the ledger still reads 90.
        assert committed_minutes(api, {"district": ctx["district"],
                                       "school": ctx["school"],
                                       "interventionist": interventionist}) == 90
        plan1_after = get_plan(api, d_id, s_id, e1["id"], plan1["id"])
        assert plan1_after["status"] == "ACTIVE"

    def test_two_plans_landing_exactly_on_capacity_accepted(self, api):
        """PRD §2.8: "The capacity check itself is inclusive. A proposed plan is
        acceptable when the interventionist's current
        `committed_minutes_per_week` plus the plan's `weekly_minute_cost` does not
        exceed the interventionist's `weekly_minute_capacity`; a proposal that
        lands exactly on capacity is accepted."

        Two plans costing 90 minutes each against a capacity of 180: the second
        proposal lands exactly on capacity and succeeds.

        Design: Difficulty/resource_temporal_overlap/interventionist_minutes_budget_overlap
        """
        ctx = setup_students_with_ratified_tiers(api, raw_scores=[80, 82])
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        e1, e2 = ctx["students"]
        catalog_entry = add_catalog_entry(api, d_id, tier_target="TIER_2",
                                          session_minutes=30, sessions_per_week=3)
        interventionist = add_interventionist(api, d_id, s_id,
                                              weekly_minute_capacity=180)

        plan1 = create_plan(api, d_id, s_id, e1["id"], catalog_entry["id"],
                            interventionist["id"])
        plan2 = create_plan(api, d_id, s_id, e2["id"], catalog_entry["id"],
                            interventionist["id"])
        assert plan1["status"] == "ACTIVE" and plan2["status"] == "ACTIVE"
        assert committed_minutes(api, {"district": ctx["district"],
                                       "school": ctx["school"],
                                       "interventionist": interventionist}) == 180


class TestLedgerConservation:
    def test_create_then_cancel_restores_committed_minutes(self, api):
        """PRD §2.8: "Starting a plan adds the plan's `weekly_minute_cost` to the
        ledger; resuming a paused plan adds it again. Pausing a plan subtracts
        it, and so does every form of plan termination — a team-lead exit, a
        cancellation of a previously active plan, a ratification cascade that
        ends the plan, and the referral cascade."
        PRD §3.8: "A `TeamLead` may cancel an `ACTIVE` plan only while no
        progress probe exists on it yet; the cancellation releases its committed
        minutes."

        Forward (+90) then compensating cancel (-90) returns the ledger to its
        pre-create baseline with no drift.

        Design: Difficulty/compensating_invariant/interventionist_minutes_conservation
        """
        ctx = setup_active_plan(api, tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        assert committed_minutes(api, ctx) == 90

        plan = get_plan(api, d_id, s_id, ctx["student"]["id"], ctx["plan"]["id"])
        cancelled = validate_success(api.cancel_plan(
            d_id, s_id, ctx["student"]["id"], plan["id"],
            {"expected_plan_version": plan["version"]}, LEAD))
        assert cancelled["status"] == "CANCELLED"
        assert committed_minutes(api, ctx) == 0, (
            "create (+90) then cancel (-90) must restore the baseline")

    def test_pause_then_cancel_paused_plan_releases_nothing_twice(self, api):
        """PRD §3.8: "A `PAUSED` plan may be cancelled without that restriction,
        and because its minutes were already released at pause time, no further
        ledger adjustment occurs."

        Create (+90), pause (-90), then cancel the PAUSED plan: the ledger stays
        at 0 rather than subtracting a second time.

        Design: Difficulty/compensating_invariant/interventionist_minutes_conservation
        """
        ctx = setup_active_plan(api, tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        assert committed_minutes(api, ctx) == 90

        paused = pause_plan(api, ctx)
        assert paused["status"] == "PAUSED"
        assert committed_minutes(api, ctx) == 0

        cancelled = validate_success(api.cancel_plan(
            d_id, s_id, ctx["student"]["id"], paused["id"],
            {"expected_plan_version": paused["version"]}, LEAD))
        assert cancelled["status"] == "CANCELLED"
        assert committed_minutes(api, ctx) == 0, (
            "cancelling a PAUSED plan must not subtract minutes a second time")
