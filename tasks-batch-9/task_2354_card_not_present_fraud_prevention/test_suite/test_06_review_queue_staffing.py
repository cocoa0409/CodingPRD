"""Staffing the review queue: assignment side effects and the shift-release cascade."""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    AnalystStatus,
    ApiClient,
    ApiErrorId,
    AssessmentState,
    CaseState,
    NON_EXISTENT_UUID,
    STANDARD_ORDER_CENTS,
    Seniority,
    SignalFamily,
    assign_case,
    assign_case_payload,
    assert_review_capacity_ledger,
    assert_score,
    auto_assign_case,
    build_reviewed_assessment,
    build_scoring_env,
    create_analyst,
    make_review_lead_headers,
    move_analyst_off_shift,
    read_analyst,
    read_assessment,
    read_case,
    validate_error,
    validate_paginated,
)


class TestShiftReleaseCascade:
    """Taking an analyst off shift returns every case they hold to the queue."""

    def test_moving_the_holder_off_shift_requeues_the_case_and_zeroes_the_count(
        self, api: ApiClient
    ) -> None:
        """The case returns to QUEUED at requeue_count 1, priced exactly as before.

        PRD: "Moving an analyst away from `AVAILABLE` triggers the **shift-release
        cascade**, whose links are: every review case in state `ASSIGNED` held by that
        analyst moves `ASSIGNED → QUEUED`, with its `assigned_analyst_id` and
        `assigned_at` cleared and its `requeue_count` incremented by one; the analyst's
        `open_case_count` is set outright to 0, restoring the review-capacity ledger of
        §2.9; and the analyst's `version` increments by one."
        PRD: "`priority_score` is recomputed at case creation, on every `ASSIGNED →
        ESCALATED` transition, and by the chargeback cascade of §3.8."

        Design: Corner/state_machines/analyst_shift_change_requeues_the_held_case
        """
        env = build_scoring_env(api)
        analyst = create_analyst(
            api,
            display_name="AN1",
            seniority=Seniority.JUNIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=2,
        )
        assert analyst["status"] == AnalystStatus.AVAILABLE
        assert analyst["open_case_count"] == 0

        assessment, case = build_reviewed_assessment(api, env, STANDARD_ORDER_CENTS)
        assert_score(assessment["blended_score"], 50.00, "blended_score")
        assert case["state"] == CaseState.QUEUED
        assert case["primary_signal_family"] == SignalFamily.BEHAVIORAL
        assert_score(case["priority_score"], 27.00, "priority_score at creation")

        assigned = assign_case(
            api, case["id"], analyst["id"], int(analyst["version"]), analyst["id"]
        )
        assert assigned["state"] == CaseState.ASSIGNED
        assert read_analyst(api, analyst["id"])["open_case_count"] == 1

        released = move_analyst_off_shift(api, analyst["id"])
        assert released["status"] == AnalystStatus.OFF_SHIFT
        assert released["open_case_count"] == 0, (
            "open_case_count is set outright to 0, not merely decremented"
        )
        assert released["resolved_case_count"] == 0, (
            "a requeue is not a resolution and credits the analyst nothing"
        )
        assert int(released["version"]) > int(analyst["version"]), (
            "the analyst's version increments by one on the release"
        )

        requeued = read_case(api, case["id"])
        assert requeued["state"] == CaseState.QUEUED
        assert requeued["assigned_analyst_id"] is None
        assert requeued["assigned_at"] is None
        assert requeued["requeue_count"] == 1
        assert_score(
            requeued["priority_score"], 27.00, "priority_score after the requeue"
        )

        assert assert_review_capacity_ledger(api, analyst["id"], ADMIN) == 0, (
            "the review-capacity ledger is restored by the release"
        )

        assert read_assessment(api, assessment["id"])["state"] == (
            AssessmentState.IN_REVIEW
        ), "the assessment is untouched by the requeue"


class TestAutomaticStaffingSelector:
    """The selector filters first, then orders by headroom before seniority."""

    def test_the_senior_with_the_most_headroom_wins_over_a_junior_and_a_lead(
        self, api: ApiClient
    ) -> None:
        """The wrong-family JUNIOR is filtered out, and headroom outranks seniority.

        PRD: "It filters the roster to analysts whose `status` is `AVAILABLE`, whose
        `skill_families` include the case's `primary_signal_family`, whose
        `open_case_count` is strictly below their `shift_capacity_cases`, and — when the
        case is `ESCALATED` — whose `seniority` is `LEAD` and whose identity differs
        from the case's `escalated_by_analyst_id`."
        PRD: "The surviving pool is then ordered by a pinned key sequence, first key
        winning: remaining headroom, defined as `shift_capacity_cases` minus
        `open_case_count`, **descending**; then seniority rank **ascending**, treating
        `JUNIOR` as lower than `SENIOR` and `SENIOR` as lower than `LEAD`, so the
        cheapest qualified analyst is taken first; then `created_at` ascending; then `id`
        ascending, which makes the order total and leaves no ties."

        Design: Corner/calculations/auto_assign_prefers_most_headroom_then_cheapest_seniority
        """
        env = build_scoring_env(api)
        junior_small = create_analyst(
            api,
            display_name="AN_A",
            seniority=Seniority.JUNIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=2,
        )
        senior_roomy = create_analyst(
            api,
            display_name="AN_B",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=3,
        )
        wrong_family = create_analyst(
            api,
            display_name="AN_C",
            seniority=Seniority.JUNIOR,
            skill_families=[SignalFamily.DEVICE],
            shift_capacity_cases=5,
        )
        lead = create_analyst(
            api,
            display_name="AN_D",
            seniority=Seniority.LEAD,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=3,
        )

        _assessment, case = build_reviewed_assessment(api, env, STANDARD_ORDER_CENTS)
        assert case["primary_signal_family"] == SignalFamily.BEHAVIORAL

        staffed = auto_assign_case(api, case["id"], lead["id"])
        assert staffed["state"] == CaseState.ASSIGNED
        assert staffed["assigned_analyst_id"] == senior_roomy["id"], (
            "headroom 3 beats headroom 2, and SENIOR is cheaper than LEAD at a tie"
        )
        assert staffed["assigned_at"] is not None

        chosen = read_analyst(api, senior_roomy["id"])
        assert chosen["open_case_count"] == 1
        assert int(chosen["version"]) == 2

        for passed_over in (junior_small, wrong_family, lead):
            row = read_analyst(api, passed_over["id"])
            assert row["open_case_count"] == 0, (
                "only the head of the pinned order receives the case"
            )
            assert int(row["version"]) == 1

    def test_an_empty_eligible_pool_is_an_error_and_leaves_the_case_queued(
        self, api: ApiClient
    ) -> None:
        """With no AVAILABLE analyst of the right family, auto-assign refuses outright.

        PRD: "An empty pool is an error — `ERR_NO_ELIGIBLE_ANALYST` — never a silent
        no-op."
        PRD: "The roster's `status` axis moves among `AVAILABLE`, `OFF_SHIFT` and
        `SUSPENDED`, and only `AVAILABLE` analysts are assignment-eligible."

        Design: Corner/calculations/auto_assign_with_empty_eligible_pool_rejected
        """
        env = build_scoring_env(api)
        device_only = create_analyst(
            api,
            display_name="AN_C",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.DEVICE],
            shift_capacity_cases=5,
        )
        off_shift = create_analyst(
            api,
            display_name="AN_E",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=5,
        )
        assert move_analyst_off_shift(api, off_shift["id"])["status"] == (
            AnalystStatus.OFF_SHIFT
        )

        _assessment, case = build_reviewed_assessment(api, env, STANDARD_ORDER_CENTS)
        assert case["primary_signal_family"] == SignalFamily.BEHAVIORAL

        response = api.auto_assign_case(
            case["id"], make_review_lead_headers(device_only["id"])
        )
        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ANALYST, 422)

        unchanged = read_case(api, case["id"])
        assert unchanged["state"] == CaseState.QUEUED
        assert unchanged["assigned_analyst_id"] is None
        assert unchanged["requeue_count"] == 0, (
            "a refused staffing attempt is not a requeue"
        )
        assert read_analyst(api, device_only["id"])["open_case_count"] == 0
        assert read_analyst(api, off_shift["id"])["open_case_count"] == 0


class TestShiftBudgetIsAnAggregateCheck:
    """A current analyst version does not buy a second case past the shift budget."""

    def test_the_second_assignment_to_a_one_case_analyst_is_refused(
        self, api: ApiClient
    ) -> None:
        """The capacity failure is reported even though the supplied version is current.

        PRD: "and finally the analyst's `open_case_count` must be strictly below their
        `shift_capacity_cases` (`ERR_ANALYST_CAPACITY_EXCEEDED`)."
        PRD: "A successful assignment — `QUEUED → ASSIGNED` or `ESCALATED → ASSIGNED`,
        the latter closing the escalation cycle — sets `assigned_analyst_id` and stamps
        `assigned_at` at the current instant, increments the analyst's `open_case_count`
        by one and the analyst's `version` by one, and increments the case's own
        `version` by one."

        Design: Corner/validations/analyst_capacity_exceeded_on_second_assignment_rejected
        """
        env = build_scoring_env(api)
        analyst = create_analyst(
            api,
            display_name="AN1",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=1,
        )
        assert int(analyst["version"]) == 1

        _first_assessment, first_case = build_reviewed_assessment(
            api, env, STANDARD_ORDER_CENTS
        )
        _second_assessment, second_case = build_reviewed_assessment(
            api, env, STANDARD_ORDER_CENTS
        )
        assert second_case["id"] != first_case["id"]

        held = assign_case(
            api,
            first_case["id"],
            analyst["id"],
            int(analyst["version"]),
            analyst["id"],
        )
        assert held["state"] == CaseState.ASSIGNED

        current = read_analyst(api, analyst["id"])
        assert current["open_case_count"] == 1
        assert int(current["version"]) == 2

        response = api.assign_case(
            second_case["id"],
            assign_case_payload(analyst["id"], int(current["version"])),
            make_review_lead_headers(analyst["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ANALYST_CAPACITY_EXCEEDED, 409)
        assert response.json()["data"]["error_id"] != (
            ApiErrorId.ERR_STALE_ANALYST_VERSION
        ), "the supplied analyst version was the current one"

        refused = read_case(api, second_case["id"])
        assert refused["state"] == CaseState.QUEUED
        assert refused["assigned_analyst_id"] is None

        assert read_case(api, first_case["id"])["assigned_analyst_id"] == analyst["id"]
        after = read_analyst(api, analyst["id"])
        assert after["open_case_count"] == 1, "the refused assignment cost no capacity"
        assert int(after["version"]) == 2


class TestAssignmentIsATwoSidedLink:
    """The named analyst must exist before any version or capacity work happens."""

    def test_an_unknown_analyst_is_a_404_and_the_real_one_links_both_rows(
        self, api: ApiClient
    ) -> None:
        """The refused link leaves the case QUEUED; the accepted one writes both sides.

        PRD: "Foreign keys arriving in a request body are resolved in the order the
        body's fields are documented, and each resolves to the target entity's own
        not-found code"
        PRD: "A successful assignment — `QUEUED → ASSIGNED` or `ESCALATED → ASSIGNED`,
        the latter closing the escalation cycle — sets `assigned_analyst_id` and stamps
        `assigned_at` at the current instant, increments the analyst's `open_case_count`
        by one and the analyst's `version` by one, and increments the case's own
        `version` by one."

        Design: Corner/endpoints/case_assign_links_case_to_analyst_and_needs_both_rows
        """
        env = build_scoring_env(api)
        analyst = create_analyst(
            api,
            display_name="AN1",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=2,
        )
        _assessment, case = build_reviewed_assessment(api, env, STANDARD_ORDER_CENTS)

        response = api.assign_case(
            case["id"],
            assign_case_payload(NON_EXISTENT_UUID, int(analyst["version"])),
            make_review_lead_headers(analyst["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ANALYST_NOT_FOUND, 404)
        assert read_case(api, case["id"])["state"] == CaseState.QUEUED
        assert read_analyst(api, analyst["id"])["open_case_count"] == 0

        linked = assign_case(
            api, case["id"], analyst["id"], int(analyst["version"]), analyst["id"]
        )
        assert linked["state"] == CaseState.ASSIGNED
        assert linked["assigned_analyst_id"] == analyst["id"]
        assert linked["assigned_at"] is not None
        assert int(linked["version"]) == int(case["version"]) + 1

        held = read_analyst(api, analyst["id"])
        assert held["open_case_count"] == 1
        assert int(held["version"]) == int(analyst["version"]) + 1

        rows, meta = validate_paginated(
            api.list_review_cases(ADMIN, params={"assigned_analyst_id": analyst["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == case["id"]


class TestStaleAnalystVersionOnAssignment:
    """The version token guards the parent analyst row, not the case."""

    def test_replaying_the_first_token_is_a_412_and_the_fresh_one_succeeds(
        self, api: ApiClient
    ) -> None:
        """A legal first assignment invalidates the token the client is still holding.

        PRD: "`POST /fraud/review-cases/{id}/assign` requires `expected_analyst_version`
        as a non-optional field of the request body, carrying the client's last observed
        `version` of the `Analyst` named by `analyst_id`. If it does not equal that
        analyst's current `version`, the assignment is rejected with
        `ERR_STALE_ANALYST_VERSION` (HTTP 412)."
        PRD: "This is the guard against acting on a stale reading of the analyst's
        capacity: an earlier assignment may already have consumed the headroom the client
        believed was free, and because that earlier assignment was itself perfectly
        legal, no state precondition would catch the second one — the case is still
        `QUEUED`, the analyst is still `AVAILABLE` and still under capacity."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_analyst_version_on_case_assign
        """
        env = build_scoring_env(api)
        analyst = create_analyst(
            api,
            display_name="AN1",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=2,
        )
        observed_version = int(analyst["version"])
        assert observed_version == 1

        _first_assessment, first_case = build_reviewed_assessment(
            api, env, STANDARD_ORDER_CENTS
        )
        _second_assessment, second_case = build_reviewed_assessment(
            api, env, STANDARD_ORDER_CENTS
        )

        assign_case(
            api, first_case["id"], analyst["id"], observed_version, analyst["id"]
        )
        moved_on = read_analyst(api, analyst["id"])
        assert int(moved_on["version"]) == observed_version + 1
        assert moved_on["status"] == AnalystStatus.AVAILABLE
        assert moved_on["open_case_count"] == 1, "the analyst is still under capacity"

        stale = api.assign_case(
            second_case["id"],
            assign_case_payload(analyst["id"], observed_version),
            make_review_lead_headers(analyst["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_ANALYST_VERSION, 412)

        assert read_case(api, second_case["id"])["state"] == CaseState.QUEUED
        assert read_analyst(api, analyst["id"])["open_case_count"] == 1, (
            "the refused assignment consumed no headroom"
        )

        fresh = assign_case(
            api,
            second_case["id"],
            analyst["id"],
            observed_version + 1,
            analyst["id"],
        )
        assert fresh["state"] == CaseState.ASSIGNED
        assert fresh["assigned_analyst_id"] == analyst["id"]

        final = read_analyst(api, analyst["id"])
        assert final["open_case_count"] == 2
        assert int(final["version"]) == observed_version + 2
