"""Point budgets: half-open window overlap, posture derivation, cross-entity
gating of nominations, auto-close on clock advance, and OCC-guarded adjustments."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_point_budget,
    create_budget,
    create_budget_payload,
    create_department,
    create_nomination_payload,
    create_program_payload,
    get_success_data,
    make_employee_headers,
    setup_program_with_budget,
    submit_and_approve_nomination,
    submit_nomination,
    validate_error,
    validate_paginated,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]


class TestBudgetWindowOverlap:
    def test_half_open_adjacency_allowed_and_intersection_rejected(
        self, api, finance_admin_headers
    ):
        """PRD §3.2: "Windows for the same program-and-department pair must
        not overlap: any intersection is rejected with
        `ERR_BUDGET_PERIOD_OVERLAP`, though pure adjacency — one window
        starting exactly where another ends — is allowed."

        Design: Difficulty/resource_temporal_overlap/budget_period_half_open_overlap
        """
        ctx = setup_program_with_budget(
            allocated_points=10000,
            budget_overrides={"period_start_date": "2028-01-01",
                              "period_end_date": "2029-01-01"},
        )
        program_id, dept_id = ctx["program"]["id"], ctx["dept"]["id"]

        b1 = get_success_data(api.create_budget(
            create_budget_payload(
                program_id, dept_id, period_start_date="2026-08-01",
                period_end_date="2027-02-01", allocated_points=10000,
            ), finance_admin_headers,
        ))
        # Adjacent successor: start == B1.end is allowed.
        b2_res = api.create_budget(
            create_budget_payload(
                program_id, dept_id, period_start_date="2027-02-01",
                period_end_date="2027-08-01", allocated_points=10000,
            ), finance_admin_headers,
        )
        b2 = validate_success(b2_res, 201)
        assert_point_budget(b2)

        # Intersecting window is rejected.
        overlap_res = api.create_budget(
            create_budget_payload(
                program_id, dept_id, period_start_date="2027-01-15",
                period_end_date="2027-03-01", allocated_points=5000,
            ), finance_admin_headers,
        )
        validate_error(overlap_res, ApiErrorId.ERR_BUDGET_PERIOD_OVERLAP)

        # Adjacent predecessor: end == B1.start is allowed.
        b4_res = api.create_budget(
            create_budget_payload(
                program_id, dept_id, period_start_date="2026-07-01",
                period_end_date="2026-08-01", allocated_points=5000,
            ), finance_admin_headers,
        )
        validate_success(b4_res, 201)

        _, meta = validate_paginated(api.list_budgets(
            finance_admin_headers,
            params={"program_id": program_id, "department_id": dept_id},
        ))
        # The ctx fixture budget plus the three created above.
        assert meta["total_count"] == 4

    def test_overlap_window_creates_no_budget_row(self, api, finance_admin_headers):
        """PRD §3.2: "Windows for the same program-and-department pair must
        not overlap: any intersection is rejected with
        `ERR_BUDGET_PERIOD_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/budget_period_half_open_overlap
        """
        program = get_success_data(api.create_program(create_program_payload(), HR))
        get_success_data(api.activate_program(program["id"], HR))
        dept = create_department()
        create_budget(program["id"], dept["id"], period_start_date="2026-08-01",
                      period_end_date="2027-02-01", allocated_points=10000)
        res = api.create_budget(
            create_budget_payload(
                program["id"], dept["id"], period_start_date="2026-12-01",
                period_end_date="2027-06-01", allocated_points=5000,
            ), finance_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_PERIOD_OVERLAP)
        _, meta = validate_paginated(api.list_budgets(
            finance_admin_headers,
            params={"program_id": program["id"], "department_id": dept["id"]},
        ))
        assert meta["total_count"] == 1


class TestPostureCompoundGating:
    def test_posture_tracks_aggregate_counters_through_review_decisions(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.2: "Otherwise, utilization at or above 10000 basis points
        makes the budget `EXHAUSTED`; at or above 8500 basis points,
        `RESTRICTED`; below that, `OPEN`. Boundaries are inclusive: exactly
        85.00 percent utilization is `RESTRICTED`, and exactly 100.00 percent
        is `EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/budget_posture_compound_gating
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 10000},
            allocated_points=10000, num_extra_employees=1,
        )
        program_id = ctx["program"]["id"]
        budget_id = ctx["budget"]["id"]
        nominee, nominator = ctx["employee"], ctx["extras"][0]
        nom1 = submit_nomination(program_id, nominee["id"], nominator, 8400,
                                 type="PEER", reason_code="TEAMWORK",
                                 idempotency_key="nl3-n1")
        nom2 = submit_nomination(program_id, nominee["id"], nominator, 100,
                                 type="PEER", reason_code="INNOVATION",
                                 idempotency_key="nl3-n2")

        # reserved 8500 of 10000 -> exactly 8500 bp -> RESTRICTED.
        p1 = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert p1["posture"] == "RESTRICTED"

        # Approve the 8400: reserved 100 + committed 8400 -> still 8500 bp.
        get_success_data(api.approve_nomination(nom1["id"], nom1["version"], hr_admin_headers))
        p2 = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert p2["posture"] == "RESTRICTED"

        # Reject the 100: committed 8400 alone -> 8400 bp -> OPEN.
        get_success_data(api.reject_nomination(nom2["id"], hr_admin_headers, reason="not now"))
        p3 = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert p3["posture"] == "OPEN"

    def test_released_reservation_drops_posture_below_restricted_boundary(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.2: "Posture moves freely in both directions as counters
        change: rejections, cancellations, and expiries release reservations
        and can walk a budget from `EXHAUSTED` back through `RESTRICTED` to
        `OPEN`".

        Design: Difficulty/non_linear_state_machine/budget_posture_compound_gating
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 10000},
            allocated_points=10000, num_extra_employees=1,
        )
        program_id = ctx["program"]["id"]
        budget_id = ctx["budget"]["id"]
        nominee, nominator = ctx["employee"], ctx["extras"][0]
        big = submit_nomination(program_id, nominee["id"], nominator, 10000,
                                type="PEER", reason_code="TEAMWORK",
                                idempotency_key="nl3b-n1")
        exhausted = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert exhausted["posture"] == "EXHAUSTED"

        get_success_data(api.cancel_nomination(
            big["id"], make_employee_headers(nominator["id"])
        ))
        reopened = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert reopened["posture"] == "OPEN"
        assert reopened["reserved_points"] == 0


class TestCrossEntityPostureGate:
    def test_same_submission_rejected_while_restricted_accepted_when_open(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.2: "While `RESTRICTED`, a nomination may request at most 500
        points; while `EXHAUSTED`, every new submission against the budget is
        rejected with `ERR_BUDGET_EXHAUSTED`."

        Design: Difficulty/cross_entity_state_dependency/nomination_submit_gated_by_budget_posture
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 10000},
            allocated_points=10000, num_extra_employees=1,
        )
        program_id = ctx["program"]["id"]
        budget_id = ctx["budget"]["id"]
        nominee, nominator = ctx["employee"], ctx["extras"][0]
        submit_nomination(program_id, nominee["id"], nominator, 8000,
                          type="PEER", reason_code="TEAMWORK",
                          idempotency_key="ce1-n1")
        small = submit_nomination(program_id, nominee["id"], nominator, 500,
                                  type="PEER", reason_code="INNOVATION",
                                  idempotency_key="ce1-n2")
        # 8500 bp -> RESTRICTED: a 600-point request exceeds the 500 cap.
        blocked = api.create_nomination(
            create_nomination_payload(
                program_id, nominee["id"], type="PEER", points_requested=600,
                reason_code="CUSTOMER_SAVE", message="n3 blocked",
                idempotency_key="ce1-n3",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_BUDGET_RESTRICTED_AMOUNT)

        # Rejecting the 500-point nomination drops utilization to 8000 bp (OPEN).
        get_success_data(api.reject_nomination(
            small["id"], hr_admin_headers, reason="free the pool"
        ))
        allowed = submit_nomination(program_id, nominee["id"], nominator, 600,
                                    type="PEER", reason_code="CUSTOMER_SAVE",
                                    idempotency_key="ce1-n4")
        assert allowed["status"] == "PENDING_REVIEW"

        budget = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert budget["reserved_points"] == 8600
        assert budget["posture"] == "RESTRICTED"

    def test_submission_after_posture_recovery_reserves_against_same_budget(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.3: "the sum of `reserved_points`, `committed_points`, and
        `points_requested` must not exceed `allocated_points` — a sum landing
        exactly on `allocated_points` is accepted, anything larger is rejected
        with `ERR_BUDGET_EXHAUSTED`."

        Design: Difficulty/cross_entity_state_dependency/nomination_submit_gated_by_budget_posture
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 10000},
            allocated_points=10000, num_extra_employees=1,
        )
        program_id = ctx["program"]["id"]
        budget_id = ctx["budget"]["id"]
        nominee, nominator = ctx["employee"], ctx["extras"][0]
        big = submit_nomination(program_id, nominee["id"], nominator, 9000,
                                type="PEER", reason_code="TEAMWORK",
                                idempotency_key="ce1b-n1")
        # 9000 bp RESTRICTED: reject it, then 600 fits under an OPEN posture.
        get_success_data(api.reject_nomination(big["id"], hr_admin_headers))
        posture = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert posture["posture"] == "OPEN"

        ok = submit_nomination(program_id, nominee["id"], nominator, 600,
                               type="PEER", reason_code="DELIVERY",
                               idempotency_key="ce1b-n2")
        assert ok["status"] == "PENDING_REVIEW"
        assert ok["budget_id"] == budget_id


class TestBudgetAutoClose:
    def test_budget_auto_closes_at_period_end_and_selector_misses_afterwards(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.2: "When the logical clock reaches a budget's
        `period_end_date`, the auto-close runs — always after the nomination
        auto-expiry step of the same sweep, so expiring nominations release
        their reservations first. The closing budget's `reserved_points`
        settles to zero, its `version` increments by one, and from then on any
        nomination or grant whose selector would have picked this window
        receives `ERR_BUDGET_NOT_FOUND`, because the window no longer contains
        the current date."

        Design: Corner/state_machines/budget_auto_close_after_period_end
        """
        ctx = setup_program_with_budget(
            program_overrides={"nomination_review_sla_days": 14,
                               "max_points_per_nomination": 1000},
            allocated_points=10000, num_extra_employees=1,
            budget_overrides={"period_start_date": "2026-01-01",
                              "period_end_date": "2026-09-01"},
        )
        program_id = ctx["program"]["id"]
        budget_id = ctx["budget"]["id"]
        nominee, nominator = ctx["employee"], ctx["extras"][0]
        nomination = submit_nomination(
            program_id, nominee["id"], nominator, 100, type="PEER",
            reason_code="TEAMWORK", idempotency_key="sm-bc-1",
        )
        # The nomination's review deadline (2026-08-15) passes before the
        # budget window ends (2026-09-01): the sweep expires it, then closes.
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", hr_admin_headers))

        budget = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert budget["posture"] == "CLOSED"
        assert budget["reserved_points"] == 0

        expired = validate_success(
            api.get_nomination(nomination["id"], hr_admin_headers), 200
        )
        assert expired["status"] == "EXPIRED"

        res = api.create_nomination(
            create_nomination_payload(
                program_id, nominee["id"], type="PEER", points_requested=100,
                reason_code="INNOVATION", message="after close",
                idempotency_key="sm-bc-2",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_NOT_FOUND)


class TestBudgetAdjustments:
    def test_adjustment_on_closed_budget_rejected(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.2: "Adjustments against a `CLOSED` budget are rejected with
        `ERR_BUDGET_CLOSED`."

        Design: Corner/errors/budget_adjustment_on_closed_budget_rejected
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 1000},
            allocated_points=10000,
            budget_overrides={"period_start_date": "2026-01-01",
                              "period_end_date": "2026-09-01"},
        )
        budget_id = ctx["budget"]["id"]
        get_success_data(api.set_clock("2026-09-02T00:00:00Z", hr_admin_headers))
        closed = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert closed["posture"] == "CLOSED"

        res = api.create_budget_adjustment(
            budget_id,
            {"delta_allocated_points": 5000, "reason": "top up",
             "expected_budget_version": closed["version"]},
            finance_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_CLOSED)

    def test_occ_budget_adjustment_stale_version(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §2.7: "Posting an allocation adjustment through
        `POST /api/budgets/{budgetId}/adjustments` requires
        `expected_budget_version`, matching the budget's current `version`.
        Another adjustment, or an approval-driven commit that moved the
        counters and advanced the version, invalidates the pool figures the
        adjustment decision was made against."
        PRD §2.7: "In all three cases, a mismatch between the supplied version
        and the resource's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_budget_adjustment_stale_version
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 10000},
            allocated_points=10000,
        )
        budget_id = ctx["budget"]["id"]
        stale_version = ctx["budget"]["version"]

        # A submit+approve cycle mutates the budget counters and bumps version.
        submit_and_approve_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], 700,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="occ-bud-1",
        )

        res = api.create_budget_adjustment(
            budget_id,
            {"delta_allocated_points": 5000, "reason": "stale topup",
             "expected_budget_version": stale_version},
            finance_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert fresh["version"] > stale_version

        adjusted = validate_success(api.create_budget_adjustment(
            budget_id,
            {"delta_allocated_points": 5000, "reason": "fresh topup",
             "expected_budget_version": fresh["version"]},
            finance_admin_headers,
        ), 200)
        assert adjusted["allocated_points"] == 15000
