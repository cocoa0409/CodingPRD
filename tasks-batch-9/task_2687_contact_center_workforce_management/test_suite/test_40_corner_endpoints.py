"""Endpoint-surface corners: partial updates, bulk writes, junction links and derived reads."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_agent_coaching,
    assert_coverage_summary_shape,
    assert_shift_adherence,
    assert_instant_equals,
    assert_shift_axes,
    assert_shift_hours,
)
from test_helpers.constants import (
    ADHERENCE_EXCUSED,
    ADHERENCE_OUT_OF_ADHERENCE,
    AGENT_STATUS_ACTIVE,
    ALLOCATION_PROPOSED,
    BILLING_DELIVERED_ONLY,
    CLASS_STATUS_GRADUATED,
    CLASS_STATUS_IN_TRAINING,
    COACHING_ACTIVE,
    COACHING_CLEARED,
    DECISION_APPROVE,
    EXCEPTION_STATUS_APPROVED,
    EXCEPTION_STATUS_SUBMITTED,
    POSTURE_OPEN,
    PUBLICATION_PUBLISHED,
)
from test_helpers.factories import (
    agent_patch_payload,
    exception_decision_payload,
    interval_grid_payload,
    partner_allocation_payload,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    build_exception_case,
    charter_class,
    generate_grid,
    make_agent,
    make_forecast_group,
    make_hiring_class,
    make_labor_agreement,
    make_outsource_partner,
    make_partner_forecast_group,
    make_planning_cycle,
    read_agent,
    read_agreement,
    read_coverage_summary,
    read_cycle,
    read_group,
    read_hiring_class,
    read_shift,
    set_clock,
    start_training,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    COACH_HEADERS,
    COACH_USER_ID,
    INTRADAY_USER_ID,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
    SOURCING_HEADERS,
    SOURCING_USER_ID,
)

FABRICATED_PARTNER_ID = "00000000-0000-4000-8000-00000000dead"
FABRICATED_INTERVAL_ID = "00000000-0000-4000-8000-00000000beef"


class TestAgentPartialUpdate:
    """The agent update surface is exactly its declared optional inputs."""

    def test_patch_replaces_attributes_and_leaves_identity_alone(self, api):
        """A patch of skills, rank and rate replaces those three and touches nothing else.

        "Employment state and a few mutable attributes travel through the same
        partial-update capability, which accepts an optional `target_status` plus
        optional replacement values for `skills`, `seniority_rank` and
        `hourly_rate_cents`."

        Design: Corner/endpoints/agent_patch_updates_attributes_without_touching_identity
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api)
        agent = make_agent(api, agreement["id"], employee_code="E-001")
        assert agent["version"] == 1
        assert agent["status"] == AGENT_STATUS_ACTIVE

        patched = validate_success(
            api.update_agent(
                agent["id"],
                agent_patch_payload(
                    skills=["VOICE_EN", "CHAT_EN"], seniority_rank=3, hourly_rate_cents=2600
                ),
                SCHEDULER_HEADERS,
            ),
            200,
        )

        assert patched["version"] == 2
        assert patched["skills"] == ["VOICE_EN", "CHAT_EN"]
        assert patched["seniority_rank"] == 3
        assert patched["hourly_rate_cents"] == 2600
        assert patched["status"] == AGENT_STATUS_ACTIVE
        assert patched["employee_code"] == "E-001"
        assert patched["weekly_contracted_hours"] == 37.5
        assert patched["labor_agreement_id"] == agreement["id"]

        assert read_agreement(api, agreement["id"])["enrolled_agent_count"] == 1

        rows, meta = validate_paginated(
            api.list_agents(SCHEDULER_HEADERS, {"skill_code": "CHAT_EN"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == agent["id"]


class TestExceptionApprovalCascade:
    """One decision endpoint moves an exception, a shift and an agent together."""

    def test_approval_excuses_the_shift_and_clears_the_coaching_ratchet(self, api):
        """Approving an exception excuses the shift and drops the agent's flag to cleared.

        "Approval stamps `decided_by_user_id` with the deciding coach's
        identifier, then reaches across into the shift and moves its adherence
        axis `OUT_OF_ADHERENCE → EXCUSED`, adding the exception's
        `duration_seconds` to the shift's `excused_seconds`."

        Design: Corner/endpoints/exception_approval_excuses_shift_and_clears_coaching
        """
        world = build_exception_case(api)
        shift = world["shift"]
        assert_shift_hours(shift, scheduled_seconds=27000)
        assert_shift_axes(
            shift,
            publication_status=PUBLICATION_PUBLISHED,
            adherence_status=ADHERENCE_OUT_OF_ADHERENCE,
        )
        assert_shift_adherence(
            shift, adherence_pct=0.8000, flagged_by_user_id=INTRADAY_USER_ID
        )
        assert world["exception"]["status"] == EXCEPTION_STATUS_SUBMITTED
        assert world["exception"]["info_requested_count"] == 0
        assert_agent_coaching(
            world["agent"], coaching_flag_count=1, coaching_status=COACHING_ACTIVE
        )

        decided = validate_success(
            api.decide_adherence_exception(
                world["exception"]["id"],
                exception_decision_payload(DECISION_APPROVE),
                COACH_HEADERS,
            ),
            200,
        )

        assert decided["status"] == EXCEPTION_STATUS_APPROVED
        assert decided["decided_by_user_id"] == COACH_USER_ID

        after = read_shift(api, shift["id"])
        assert_shift_axes(
            after,
            publication_status=PUBLICATION_PUBLISHED,
            adherence_status=ADHERENCE_EXCUSED,
        )
        assert_shift_adherence(
            after,
            out_of_adherence_seconds=5400,
            excused_seconds=2700,
            adherence_pct=0.9000,
        )

        agent_after = read_agent(api, world["agent"]["id"])
        assert_agent_coaching(
            agent_after,
            adherence_pct=0.9000,
            coaching_flag_count=0,
            coaching_status=COACHING_CLEARED,
        )


class TestIntervalGridBulkWrite:
    """Grid generation is one request that mints the whole operating window."""

    def test_generation_returns_the_whole_ascending_window_as_one_array(self, api):
        """One call mints four contiguous half-open rows and rolls both counters up.

        "A grid may be generated once per group and date: a repeat attempt for the
        same `forecast_group_id` and `service_date` is refused with
        `ERR_DUPLICATE_INTERVALS` (HTTP 409). Successful generation runs the whole
        forecasting chain on each new row and then recomputes the group's
        `interval_count` and the cycle's `short_interval_count`."

        Design: Corner/endpoints/interval_grid_generation_is_all_or_nothing
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        group = make_forecast_group(api, cycle["id"])
        assert group["interval_count"] == 0

        response = api.generate_interval_plans(
            group["id"], interval_grid_payload("2026-09-07"), ANALYST_HEADERS
        )
        rows = validate_success(response, 201)
        assert response.json()["response_type"] == "array"

        assert isinstance(rows, list)
        assert len(rows) == 4
        assert_instant_equals(
            rows[0]["interval_start"], "2026-09-07T08:00:00Z", "interval_start"
        )
        assert_instant_equals(
            rows[1]["interval_start"], "2026-09-07T08:30:00Z", "interval_start"
        )
        assert_instant_equals(
            rows[0]["interval_end"], rows[1]["interval_start"], "interval_end"
        )
        assert [row["interval_index"] for row in rows] == [0, 1, 2, 3]
        assert rows[0]["volume_forecast"] == 480
        assert rows[1]["volume_forecast"] == 360
        assert rows[0]["required_agents"] == 140

        assert read_group(api, group["id"])["interval_count"] == 4
        assert read_cycle(api, cycle["id"])["short_interval_count"] == 4

        listed, meta = validate_paginated(
            api.list_interval_plans(
                ANALYST_HEADERS,
                {"forecast_group_id": group["id"], "service_date": "2026-09-07"},
            )
        )
        assert meta["total_count"] == 4
        assert listed[0]["id"] == rows[0]["id"]


class TestPartnerAllocationLink:
    """The junction row resolves its two foreign keys in declaration order."""

    def test_each_side_of_the_link_reports_its_own_not_found(self, api):
        """A bad partner, a bad interval and both-bad each name the declared-first failure.

        "foreign keys supplied in a request body are resolved **in the field order
        in which they are declared for that entity in Section 3**, and the first
        unresolvable one produces its own not-found error."

        Design: Corner/endpoints/partner_allocation_link_requires_both_endpoints_to_exist
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        group = make_partner_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], "2026-09-07")
        partner = make_outsource_partner(
            api,
            rate_per_contact_millicents=10000,
            interval_max_volume=50,
            commitment_floor_volume=10,
            billing_basis=BILLING_DELIVERED_ONLY,
        )

        validate_error(
            api.create_partner_allocation(
                partner_allocation_payload(
                    FABRICATED_PARTNER_ID, intervals[0]["id"], 20
                ),
                SOURCING_HEADERS,
            ),
            ApiErrorId.OUTSOURCE_PARTNER_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_partner_allocation(
                partner_allocation_payload(
                    partner["id"], FABRICATED_INTERVAL_ID, 20
                ),
                SOURCING_HEADERS,
            ),
            ApiErrorId.INTERVAL_PLAN_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_partner_allocation(
                partner_allocation_payload(
                    FABRICATED_PARTNER_ID, FABRICATED_INTERVAL_ID, 20
                ),
                SOURCING_HEADERS,
            ),
            ApiErrorId.OUTSOURCE_PARTNER_NOT_FOUND,
            404,
        )

        created = validate_success(
            api.create_partner_allocation(
                partner_allocation_payload(partner["id"], intervals[0]["id"], 20),
                SOURCING_HEADERS,
            ),
            201,
        )
        assert created["outsource_partner_id"] == partner["id"]
        assert created["interval_plan_id"] == intervals[0]["id"]
        assert created["status"] == ALLOCATION_PROPOSED
        assert created["proposed_by_user_id"] == SOURCING_USER_ID

        by_partner, partner_meta = validate_paginated(
            api.list_partner_allocations(
                SOURCING_HEADERS, {"outsource_partner_id": partner["id"]}
            )
        )
        assert partner_meta["total_count"] == 1
        assert by_partner[0]["id"] == created["id"]

        by_interval, interval_meta = validate_paginated(
            api.list_partner_allocations(
                SOURCING_HEADERS, {"interval_plan_id": intervals[0]["id"]}
            )
        )
        assert interval_meta["total_count"] == 1
        assert by_interval[0]["id"] == created["id"]


class TestCoverageSummaryDerivedView:
    """The cycle rollup is recomputed per request and carries no persisted fields."""

    def test_the_rollup_narrows_to_a_service_date_without_being_stored(self, api):
        """The same cycle answers 4/40/328 unfiltered and 2/20/164 for one date.

        "A separate computed read rolls the whole cycle up: it returns
        `planning_cycle_id`, the current `posture`, `interval_count` as the number
        of interval plans in the cycle, `short_interval_count`, and cycle-wide sums
        named `total_required_agents`, `total_effective_scheduled_agents`,
        `total_coverage_gap`, `total_allocatable_volume`,
        `total_partner_committed_volume` and `total_unserved_volume`, each the
        arithmetic sum of the corresponding per-interval field. An optional
        `service_date` query parameter narrows the rollup to a single service date."

        Design: Corner/endpoints/coverage_summary_is_a_derived_view_not_a_stored_row
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        group = make_partner_forecast_group(api, cycle["id"])
        generate_grid(api, group["id"], "2026-09-07")
        generate_grid(api, group["id"], "2026-09-08")
        version_before = read_cycle(api, cycle["id"])["version"]

        whole = read_coverage_summary(api, cycle["id"], PLANNER_HEADERS)

        assert_coverage_summary_shape(whole)
        assert whole["planning_cycle_id"] == cycle["id"]
        assert whole["posture"] == POSTURE_OPEN
        assert whole["interval_count"] == 4
        assert whole["short_interval_count"] == 4
        assert whole["total_required_agents"] == 40
        assert whole["total_effective_scheduled_agents"] == 0
        assert whole["total_coverage_gap"] == 40
        assert whole["total_allocatable_volume"] == 328
        assert whole["total_partner_committed_volume"] == 0
        assert whole["total_unserved_volume"] == 328

        first_date = read_coverage_summary(
            api, cycle["id"], SOURCING_HEADERS, {"service_date": "2026-09-07"}
        )
        assert first_date["interval_count"] == 2
        assert first_date["total_required_agents"] == 20
        assert first_date["total_allocatable_volume"] == 164
        assert first_date["total_unserved_volume"] == 164

        empty_date = read_coverage_summary(
            api, cycle["id"], SOURCING_HEADERS, {"service_date": "2026-09-10"}
        )
        assert empty_date["interval_count"] == 0
        assert empty_date["total_required_agents"] == 0
        assert empty_date["total_allocatable_volume"] == 0

        assert read_cycle(api, cycle["id"])["version"] == version_before


class TestHiringClassGraduationClockGate:
    """Graduation is gated on the logical clock, not on the class status alone."""

    def test_graduating_before_the_nesting_date_is_refused_then_allowed(self, api):
        """The same call is refused at 2026-09-01 and mints twenty-one agents at 2026-09-07.

        "`IN_TRAINING → GRADUATED` requires that the cycle is not frozen and that
        the logical clock has reached or passed `nesting_from_date` at midnight UTC
        — graduates leave the classroom into nesting, so nesting is the earliest
        legal graduation."

        Design: Corner/endpoints/hiring_class_graduate_before_nesting_date_returns_invalid_state
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        agreement = make_labor_agreement(api)
        hiring_class = make_hiring_class(
            api, cycle["id"], agreement["id"], cohort_name="CLASS-A"
        )
        assert hiring_class["nesting_from_date"] == "2026-09-07"
        assert hiring_class["productive_from_date"] == "2026-09-21"
        assert hiring_class["expected_graduates"] == 21
        charter_class(api, hiring_class["id"])
        assert start_training(api, hiring_class["id"])["status"] == CLASS_STATUS_IN_TRAINING

        validate_error(
            api.graduate_hiring_class(hiring_class["id"], PLANNER_HEADERS),
            ApiErrorId.INVALID_STATE,
            409,
        )

        refused = read_hiring_class(api, hiring_class["id"])
        assert refused["status"] == CLASS_STATUS_IN_TRAINING
        assert refused["graduated_agent_count"] == 0
        _, before_meta = validate_paginated(
            api.list_agents(SCHEDULER_HEADERS, {"hiring_class_id": hiring_class["id"]})
        )
        assert before_meta["total_count"] == 0

        set_clock(api, "2026-09-07T00:00:00Z")
        graduated = validate_success(
            api.graduate_hiring_class(hiring_class["id"], PLANNER_HEADERS), 200
        )
        assert graduated["status"] == CLASS_STATUS_GRADUATED
        assert graduated["graduated_agent_count"] == 21

        minted, after_meta = validate_paginated(
            api.list_agents(
                SCHEDULER_HEADERS,
                {"hiring_class_id": hiring_class["id"], "limit": 100},
            )
        )
        assert after_meta["total_count"] == 21
        prefix = hiring_class["cohort_name"]
        assert sorted(row["employee_code"] for row in minted) == [
            f"{prefix}-{index:03d}" for index in range(1, 22)
        ]
