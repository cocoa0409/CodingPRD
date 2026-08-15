"""Plan activation: pinned fields, derived dates, version side effects, and the
inclusive capacity boundary (PRD §2.8, §3.2, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_catalog_entry,
    add_interventionist,
    assert_student_plan,
    create_plan,
    create_plan_payload,
    get_student,
    setup_active_plan,
    setup_student_with_ratified_tier,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["team_lead_headers"]


class TestActivationPinsDerivedFields:
    def test_plan_create_returns_computed_fields_immediately(self, api):
        """PRD §3.5: "The `tier_at_start` copies the student's `current_tier` at
        that moment. The `started_on` records the activation date. The
        `weekly_minute_cost` is computed as the entry's `session_minutes`
        multiplied by its `sessions_per_week` and frozen on the plan, so later
        catalog edits never rewrite the history of running plans."
        PRD §3.5: "The plan's `fidelity_pct` begins at 100, and its `status`
        begins at `ACTIVE`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_consistency_on_plan_create
        """
        ctx = setup_active_plan(api, tier="TIER_2", session_minutes=30,
                                sessions_per_week=3)
        plan = ctx["plan"]  # the POST /plans response body itself
        assert_student_plan(plan)
        assert plan["weekly_minute_cost"] == 90, "30 minutes x 3 sessions per week"
        assert plan["tier_at_start"] == "TIER_2"
        assert plan["status"] == "ACTIVE"
        assert plan["fidelity_pct"] == 100
        assert plan["catalog_entry_id"] == ctx["catalog_entry"]["id"]
        assert plan["interventionist_id"] == ctx["interventionist"]["id"]

    def test_first_probe_due_date_by_frequency(self, api):
        """PRD §3.5: "The first `probe_due_on` is set to the activation date plus
        seven days for a `WEEKLY` probe frequency or fourteen days for
        `BIWEEKLY`."

        Both plans activate while the logical clock reads 2026-08-05.

        Design: Corner/cross_cutting/derived_field_plan_probe_due_on
        """
        weekly = setup_active_plan(api, tier="TIER_2", probe_frequency="WEEKLY",
                                   full_name="Weekly Student")
        assert weekly["plan"]["probe_due_on"] == "2026-08-12", (
            "WEEKLY: activation 2026-08-05 + 7 days")

        biweekly = setup_active_plan(api, tier="TIER_2", probe_frequency="BIWEEKLY",
                                     full_name="Biweekly Student")
        assert biweekly["plan"]["probe_due_on"] == "2026-08-19", (
            "BIWEEKLY: activation 2026-08-05 + 14 days")

    def test_plan_create_increments_student_version(self, api):
        """PRD §3.5: "Activation also adds the `weekly_minute_cost` to the
        interventionist's `committed_minutes_per_week` and increments the
        student's `version` by one."

        Design: Corner/endpoints/plan_create_cascades_student_version_bump
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        catalog_entry = add_catalog_entry(api, d_id, tier_target="TIER_2")
        interventionist = add_interventionist(api, d_id, s_id)
        before = get_student(api, d_id, s_id, ctx["student"]["id"])

        plan = create_plan(api, d_id, s_id, ctx["student"]["id"],
                           catalog_entry["id"], interventionist["id"])
        assert plan["status"] == "ACTIVE"

        after = get_student(api, d_id, s_id, ctx["student"]["id"])
        assert after["version"] == before["version"] + 1, (
            f"student version must advance by exactly 1 on plan create "
            f"({before['version']} -> {after['version']})")
        refreshed = validate_success(api.get_interventionist(
            d_id, s_id, interventionist["id"], LEAD))
        assert refreshed["committed_minutes_per_week"] == 90


class TestCapacityBoundary:
    def test_plan_at_exact_capacity_accepted(self, api):
        """PRD §2.8: "The capacity check itself is inclusive. A proposed plan is
        acceptable when the interventionist's current
        `committed_minutes_per_week` plus the plan's `weekly_minute_cost` does not
        exceed the interventionist's `weekly_minute_capacity`; a proposal that
        lands exactly on capacity is accepted."

        weekly_minute_cost is 30 x 3 = 90 against a capacity of exactly 90.

        Design: Difficulty/boundary_precision_check/capacity_inclusive_boundary_plan_create
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        catalog_entry = add_catalog_entry(api, d_id, tier_target="TIER_2",
                                          session_minutes=30, sessions_per_week=3)
        interventionist = add_interventionist(api, d_id, s_id,
                                              weekly_minute_capacity=90)
        plan = create_plan(api, d_id, s_id, ctx["student"]["id"],
                           catalog_entry["id"], interventionist["id"])
        assert plan["status"] == "ACTIVE", "90 <= 90: boundary is inclusive"
        refreshed = validate_success(api.get_interventionist(
            d_id, s_id, interventionist["id"], LEAD))
        assert refreshed["committed_minutes_per_week"] == 90

    def test_plan_one_minute_over_capacity_rejected(self, api):
        """PRD §2.8: "A proposal whose total would exceed capacity is rejected
        with `ERR_CAPACITY_EXCEEDED` (HTTP 422)."

        weekly_minute_cost is 30 x 3 = 90 against a capacity of 89.

        Design: Difficulty/boundary_precision_check/capacity_inclusive_boundary_plan_create
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        catalog_entry = add_catalog_entry(api, d_id, tier_target="TIER_2",
                                          session_minutes=30, sessions_per_week=3)
        interventionist = add_interventionist(api, d_id, s_id,
                                              weekly_minute_capacity=89)
        student = get_student(api, d_id, s_id, ctx["student"]["id"])
        resp = api.create_plan(
            d_id, s_id, student["id"],
            create_plan_payload(catalog_entry["id"], interventionist["id"],
                                student["version"]),
            LEAD)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)
        # The ledger is untouched by the rejected proposal.
        refreshed = validate_success(api.get_interventionist(
            d_id, s_id, interventionist["id"], LEAD))
        assert refreshed["committed_minutes_per_week"] == 0
        plans = validate_success(api.list_plans(d_id, s_id, student["id"], LEAD))
        assert plans == [], "no plan may be created when capacity is exceeded"


class TestMatchingBeforeCapacity:
    def test_tier_mismatch_masks_capacity_error(self, api):
        """PRD §3.5: "Matching rules then decide whether the pairing is
        admissible, and a failure on any of them is rejected with
        `ERR_CATALOG_MISMATCH` (HTTP 422): the catalog entry's `is_active` flag
        must be true; the entry's `subject` must be among the interventionist's
        `subjects`; the student's `grade_level` must fall within the entry's
        `grade_min` to `grade_max` range, inclusive; and the entry's
        `tier_target` must equal the student's `current_tier`."
        PRD §3.5: "The capacity check of §2.8 runs after matching, per the
        pipeline order."

        The request violates both rules — the TIER_3 entry does not match the
        TIER_2 student, and the 60 x 5 = 300 weekly cost would exceed the 200
        minute capacity — and the matching failure is reported.

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_plan_create
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        catalog_entry = add_catalog_entry(api, d_id, tier_target="TIER_3",
                                          session_minutes=60,
                                          sessions_per_week=5)
        interventionist = add_interventionist(api, d_id, s_id,
                                              weekly_minute_capacity=200)
        student = get_student(api, d_id, s_id, ctx["student"]["id"])
        resp = api.create_plan(
            d_id, s_id, student["id"],
            create_plan_payload(catalog_entry["id"], interventionist["id"],
                                student["version"]),
            LEAD)
        validate_error(resp, ApiErrorId.ERR_CATALOG_MISMATCH, 422)

    def test_subject_mismatch_masks_capacity_error(self, api):
        """PRD §3.5: "Matching rules then decide whether the pairing is
        admissible, and a failure on any of them is rejected with
        `ERR_CATALOG_MISMATCH` (HTTP 422): the catalog entry's `is_active` flag
        must be true; the entry's `subject` must be among the interventionist's
        `subjects`; the student's `grade_level` must fall within the entry's
        `grade_min` to `grade_max` range, inclusive; and the entry's
        `tier_target` must equal the student's `current_tier`."
        PRD §3.5: "The capacity check of §2.8 runs after matching, per the
        pipeline order."

        The MATH entry is outside the interventionist's READING-only subjects and
        the 300-minute weekly cost would exceed the 200-minute capacity; the
        matching failure is reported.

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_plan_create
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        catalog_entry = add_catalog_entry(api, d_id, subject="MATH",
                                          tier_target="TIER_2",
                                          session_minutes=60,
                                          sessions_per_week=5)
        interventionist = add_interventionist(api, d_id, s_id,
                                              weekly_minute_capacity=200,
                                              subjects=("READING",))
        student = get_student(api, d_id, s_id, ctx["student"]["id"])
        resp = api.create_plan(
            d_id, s_id, student["id"],
            create_plan_payload(catalog_entry["id"], interventionist["id"],
                                student["version"]),
            LEAD)
        validate_error(resp, ApiErrorId.ERR_CATALOG_MISMATCH, 422)
