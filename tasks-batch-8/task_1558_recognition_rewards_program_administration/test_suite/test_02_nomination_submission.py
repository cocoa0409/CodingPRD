"""Nomination submission: schema gates, scope/self-dealing, duplicates,
velocity, and the budget gate (capacity + restricted posture policy cap)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_nomination,
    create_budget,
    create_department,
    create_employee,
    create_nomination_payload,
    create_program,
    get_success_data,
    make_employee_headers,
    setup_program_with_budget,
    submit_nomination,
    suspend_employee,
    validate_error,
    validate_paginated,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]


def _ctx(program_overrides=None, allocated_points=10000, num_extra_employees=1):
    return setup_program_with_budget(
        program_overrides=program_overrides,
        allocated_points=allocated_points,
        num_extra_employees=num_extra_employees,
    )


class TestNominationInitialState:
    def test_new_nomination_pending_review_with_sla_deadline(
        self, api, hr_admin_headers
    ):
        """PRD §3.3: "On success the submission reserves its points:
        `reserved_points` grows by `points_requested`, posture is recomputed,
        and the nomination lands in `PENDING_REVIEW` with a `review_deadline`
        of the submission instant plus the program's
        `nomination_review_sla_days`."
        PRD §2.5: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and the server must never fall back to
        wall-clock time."

        Design: Corner/state_machines/nomination_initial_state_pending_review
        """
        ctx = _ctx()
        nominator = ctx["extras"][0]
        nomination = submit_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], nominator, 100,
            type="PEER", reason_code="TEAMWORK", idempotency_key="sm-init-1",
        )
        assert_nomination(nomination)
        assert nomination["status"] == "PENDING_REVIEW"
        assert nomination["revision_count"] == 0
        # Default clock 2026-08-01T00:00:00Z + 14 days SLA.
        assert nomination["review_deadline"].startswith("2026-08-15T00:00:00")


class TestNominationSchemaGates:
    def test_invalid_reason_code_rejected(self, api, hr_admin_headers):
        """PRD §2.8 stage 4: "Required fields are present, types are valid,
        enum members are valid, and integers are in range — including
        `points_requested` being at least 1 and at most the program's
        `max_points_per_nomination`, redemption `quantity` between 1 and 5
        inclusive (`ERR_INVALID_QUANTITY`), `period_month` between 1 and 12
        inclusive, and `tax_year` between 2000 and 2100 inclusive
        (`ERR_INVALID_TAX_YEAR`) — on all mutating endpoints
        (`ERR_INVALID_REQUEST` unless a more specific error applies)."
        PRD §3.3: "a `reason_code` drawn from `TEAMWORK`, `INNOVATION`,
        `CUSTOMER_SAVE`, `DELIVERY`, `MENTORSHIP`, or `OTHER`".

        Design: Corner/entities/nomination_invalid_enum_reason_code_rejected
        """
        ctx = _ctx()
        nominator = ctx["extras"][0]
        payload = create_nomination_payload(
            ctx["program"]["id"], ctx["employee"]["id"], type="PEER",
            points_requested=100, reason_code="HEROISM",
            idempotency_key="ent-enum-1",
        )
        res = api.create_nomination(payload, make_employee_headers(nominator["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestSelfDealing:
    def test_self_nomination_rejected(self, api, hr_admin_headers):
        """PRD §3.3: "Nominating oneself — `nominee_id` equal to the caller —
        is rejected with `ERR_SELF_NOMINATION` (HTTP 422)."

        Design: Corner/validations/self_nomination_rejected
        """
        ctx = _ctx()
        employee = ctx["employee"]
        payload = create_nomination_payload(
            ctx["program"]["id"], employee["id"], type="PEER",
            points_requested=100, reason_code="TEAMWORK",
            idempotency_key="val-self-1",
        )
        res = api.create_nomination(payload, make_employee_headers(employee["id"]))
        validate_error(res, ApiErrorId.ERR_SELF_NOMINATION)


class TestNominationTypeConfig:
    def test_peer_nomination_rejected_when_type_disabled(
        self, api, hr_admin_headers
    ):
        """PRD §3.1: "`peer_nomination_enabled` and `manager_nomination_enabled`,
        both defaulting to true, decide which nomination types the program
        accepts; submitting a nomination of a disabled type is rejected with
        `ERR_NOMINATION_TYPE_DISABLED`."

        Design: Corner/validations/peer_nomination_type_disabled
        """
        ctx = _ctx(program_overrides={"peer_nomination_enabled": False})
        employee, peer = ctx["employee"], ctx["extras"][0]
        res = api.create_nomination(
            create_nomination_payload(
                ctx["program"]["id"], peer["id"], type="PEER",
                points_requested=100, reason_code="TEAMWORK",
                idempotency_key="val-cfg-1",
            ),
            make_employee_headers(employee["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOMINATION_TYPE_DISABLED)

        # A MANAGER nomination still passes the config gate.
        ok = submit_nomination(
            ctx["program"]["id"], employee["id"], ctx["manager"], 100,
            type="MANAGER", reason_code="TEAMWORK", idempotency_key="val-cfg-2",
        )
        assert ok["status"] == "PENDING_REVIEW"


class TestDuplicateDefenses:
    def test_business_duplicate_within_window_rejected(self, api, hr_admin_headers):
        """PRD §3.3: "a nomination with the same nominator, the same nominee,
        and the same `reason_code` as an existing non-terminal nomination
        created within the program's `duplicate_window_days` is rejected with
        `ERR_DUPLICATE_NOMINATION`."

        Design: Corner/validations/duplicate_nomination_window_rejected
        """
        ctx = _ctx()
        nominator = ctx["extras"][0]
        program_id, nominee_id = ctx["program"]["id"], ctx["employee"]["id"]
        submit_nomination(program_id, nominee_id, nominator, 100,
                          type="PEER", reason_code="TEAMWORK",
                          idempotency_key="val-dup-1")

        dupe = api.create_nomination(
            create_nomination_payload(
                program_id, nominee_id, type="PEER", points_requested=200,
                reason_code="TEAMWORK", message="dupe", idempotency_key="val-dup-2",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(dupe, ApiErrorId.ERR_DUPLICATE_NOMINATION)

        # A different reason_code is not a business duplicate.
        ok = submit_nomination(program_id, nominee_id, nominator, 200,
                               type="PEER", reason_code="INNOVATION",
                               idempotency_key="val-dup-3")
        assert ok["status"] == "PENDING_REVIEW"

    def test_idempotency_replay_returns_original_and_conflict_on_change(
        self, api, finance_admin_headers
    ):
        """PRD §3.3: "The idempotency defense is exact: a replay with the same
        nominator, the same `idempotency_key`, and an identical payload returns
        the original nomination with HTTP 201 and creates no new row, while the
        same key with a different payload is rejected with
        `ERR_IDEMPOTENCY_CONFLICT`."

        Design: Corner/validations/idempotency_replay_returns_original
        """
        ctx = _ctx()
        nominator = ctx["extras"][0]
        program_id, nominee_id = ctx["program"]["id"], ctx["employee"]["id"]
        headers = make_employee_headers(nominator["id"])
        payload = create_nomination_payload(
            program_id, nominee_id, type="PEER", points_requested=100,
            reason_code="TEAMWORK", message="orig", idempotency_key="K1",
        )
        original = validate_success(api.create_nomination(payload, headers), 201)

        replay = validate_success(api.create_nomination(dict(payload), headers), 201)
        assert replay["id"] == original["id"]

        changed = dict(payload, points_requested=200, message="changed")
        conflict = api.create_nomination(changed, headers)
        validate_error(conflict, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)

        # Exactly one reservation of 100 and one nomination row exist.
        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["reserved_points"] == 100
        _, meta = validate_paginated(api.list_nominations(
            headers, params={"nominator_id": nominator["id"]}
        ))
        assert meta["total_count"] == 1


class TestVelocityLimit:
    def test_sixth_nomination_rejected_and_flagged(self, api, hr_admin_headers):
        """PRD §3.3: "When the count already equals the program's
        `velocity_limit_per_7_days`, the next submission is rejected with
        `ERR_VELOCITY_LIMIT_EXCEEDED` and the system raises an `OPEN` abuse
        flag with `rule_code` `VELOCITY_EXCEEDED` — so the fifth submission
        under a default limit of 5 succeeds, and the sixth is rejected and
        flagged."

        Design: Difficulty/boundary_precision_check/velocity_sixth_nomination_flagged
        """
        ctx = _ctx(
            program_overrides={"velocity_limit_per_7_days": 5,
                               "max_points_per_nomination": 1000},
            allocated_points=100000,
            num_extra_employees=7,
        )
        nominator = ctx["extras"][0]
        nominees = ctx["extras"][1:]
        program_id = ctx["program"]["id"]
        for i, nominee in enumerate(nominees[:5]):
            nomination = submit_nomination(
                program_id, nominee["id"], nominator, 100, type="PEER",
                reason_code="TEAMWORK", idempotency_key=f"bp4-n{i + 1}",
            )
            assert nomination["status"] == "PENDING_REVIEW"

        res = api.create_nomination(
            create_nomination_payload(
                program_id, nominees[5]["id"], type="PEER", points_requested=100,
                reason_code="TEAMWORK", message="6", idempotency_key="bp4-n6",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VELOCITY_LIMIT_EXCEEDED)

        flags, meta = validate_paginated(api.list_abuse_flags(
            hr_admin_headers,
            params={"employee_id": nominator["id"], "rule_code": "VELOCITY_EXCEEDED"},
        ))
        assert meta["total_count"] == 1
        assert flags[0]["status"] == "OPEN"
        assert flags[0]["rule_code"] == "VELOCITY_EXCEEDED"

    def test_five_in_window_nominations_survive_the_flagged_sixth(
        self, api, hr_admin_headers
    ):
        """PRD §3.3: "nominations created at or after the instant seven days
        before now are counted, in any status except `CANCELLED`."

        Design: Difficulty/boundary_precision_check/velocity_sixth_nomination_flagged
        """
        ctx = _ctx(
            program_overrides={"velocity_limit_per_7_days": 5,
                               "max_points_per_nomination": 1000},
            allocated_points=100000,
            num_extra_employees=7,
        )
        nominator = ctx["extras"][0]
        nominees = ctx["extras"][1:]
        program_id = ctx["program"]["id"]
        for i, nominee in enumerate(nominees[:5]):
            submit_nomination(program_id, nominee["id"], nominator, 100,
                              type="PEER", reason_code="TEAMWORK",
                              idempotency_key=f"bp4b-n{i + 1}")
        res = api.create_nomination(
            create_nomination_payload(
                program_id, nominees[5]["id"], type="PEER", points_requested=100,
                reason_code="TEAMWORK", message="6", idempotency_key="bp4b-n6",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VELOCITY_LIMIT_EXCEEDED)

        # The five in-window nominations remain PENDING_REVIEW (no cascade).
        nominations, meta = validate_paginated(api.list_nominations(
            hr_admin_headers, params={"nominator_id": nominator["id"]}
        ))
        assert meta["total_count"] == 5
        assert all(n["status"] == "PENDING_REVIEW" for n in nominations)


class TestBudgetCapacityBoundary:
    def test_reservations_reaching_exact_allocation_accepted_then_exhausted(
        self, api, finance_admin_headers
    ):
        """PRD §3.3: "the sum of `reserved_points`, `committed_points`, and
        `points_requested` must not exceed `allocated_points` — a sum landing
        exactly on `allocated_points` is accepted, anything larger is rejected
        with `ERR_BUDGET_EXHAUSTED`."
        PRD §3.2: "Otherwise, utilization at or above 10000 basis points makes
        the budget `EXHAUSTED`; at or above 8500 basis points, `RESTRICTED`;
        below that, `OPEN`."

        Design: Difficulty/boundary_precision_check/budget_full_at_exact_allocation
        """
        ctx = _ctx(allocated_points=10000)
        nominator, nominee = ctx["extras"][0], ctx["employee"]
        program_id = ctx["program"]["id"]
        n1 = submit_nomination(program_id, nominee["id"], nominator, 6000,
                               type="PEER", reason_code="TEAMWORK",
                               idempotency_key="bp1-n1")
        n2 = submit_nomination(program_id, nominee["id"], nominator, 4000,
                               type="PEER", reason_code="INNOVATION",
                               idempotency_key="bp1-n2")
        assert n1["status"] == "PENDING_REVIEW"
        assert n2["status"] == "PENDING_REVIEW"

        res = api.create_nomination(
            create_nomination_payload(
                program_id, nominee["id"], type="PEER", points_requested=1,
                reason_code="DELIVERY", message="b3 over", idempotency_key="bp1-n3",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_EXHAUSTED)

        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["reserved_points"] == 10000
        assert budget["posture"] == "EXHAUSTED"

    def test_one_point_over_full_allocation_rejected(self, api, finance_admin_headers):
        """PRD §3.2: "while `EXHAUSTED`, every new submission against the
        budget is rejected with `ERR_BUDGET_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/budget_full_at_exact_allocation
        """
        ctx = _ctx(allocated_points=10000)
        nominator, nominee = ctx["extras"][0], ctx["employee"]
        program_id = ctx["program"]["id"]
        submit_nomination(program_id, nominee["id"], nominator, 10000,
                          type="PEER", reason_code="TEAMWORK",
                          idempotency_key="bp1b-n1")
        res = api.create_nomination(
            create_nomination_payload(
                program_id, nominee["id"], type="PEER", points_requested=1,
                reason_code="INNOVATION", message="over", idempotency_key="bp1b-n2",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_EXHAUSTED)
        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["posture"] == "EXHAUSTED"


class TestRestrictedPostureCap:
    def test_over_cap_rejected_at_cap_accepted_while_restricted(
        self, api, finance_admin_headers
    ):
        """PRD §3.3: "First the posture policy cap: if the budget's posture is
        `RESTRICTED` and `points_requested` exceeds 500, the submission is
        rejected with `ERR_BUDGET_RESTRICTED_AMOUNT`."

        Design: Difficulty/combinatorial_formula/restricted_posture_nested_min_cap
        """
        ctx = _ctx(allocated_points=10000)
        nominator, nominee = ctx["extras"][0], ctx["employee"]
        program_id = ctx["program"]["id"]
        submit_nomination(program_id, nominee["id"], nominator, 8000,
                          type="PEER", reason_code="TEAMWORK",
                          idempotency_key="cf3-n1")
        submit_nomination(program_id, nominee["id"], nominator, 500,
                          type="PEER", reason_code="INNOVATION",
                          idempotency_key="cf3-n2")
        # 8500/10000 bp -> RESTRICTED; raw capacity (1500) exceeds the request.
        over = api.create_nomination(
            create_nomination_payload(
                program_id, nominee["id"], type="PEER", points_requested=501,
                reason_code="CUSTOMER_SAVE", message="n3 over cap",
                idempotency_key="cf3-n3",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(over, ApiErrorId.ERR_BUDGET_RESTRICTED_AMOUNT)

        at_cap = submit_nomination(program_id, nominee["id"], nominator, 500,
                                   type="PEER", reason_code="DELIVERY",
                                   idempotency_key="cf3-n4")
        assert at_cap["status"] == "PENDING_REVIEW"

        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["reserved_points"] == 9000
        assert budget["posture"] == "RESTRICTED"

    def test_restricted_cap_wins_over_spare_capacity(self, api, finance_admin_headers):
        """PRD §3.3: "The selected budget then applies its two-stage gate, in
        order. First the posture policy cap: if the budget's posture is
        `RESTRICTED` and `points_requested` exceeds 500, the submission is
        rejected with `ERR_BUDGET_RESTRICTED_AMOUNT`. Second the capacity
        check: the sum of `reserved_points`, `committed_points`, and
        `points_requested` must not exceed `allocated_points`".

        Design: Difficulty/combinatorial_formula/restricted_posture_nested_min_cap
        """
        ctx = _ctx(allocated_points=10000)
        nominator, nominee = ctx["extras"][0], ctx["employee"]
        program_id = ctx["program"]["id"]
        # Land exactly on the inclusive 8500 bp RESTRICTED boundary.
        submit_nomination(program_id, nominee["id"], nominator, 8500,
                          type="PEER", reason_code="TEAMWORK",
                          idempotency_key="cf3b-n1")
        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["posture"] == "RESTRICTED"

        # 600 <= remaining capacity (1500) but > 500 -> cap rejects.
        over = api.create_nomination(
            create_nomination_payload(
                program_id, nominee["id"], type="PEER", points_requested=600,
                reason_code="INNOVATION", message="over cap",
                idempotency_key="cf3b-n2",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(over, ApiErrorId.ERR_BUDGET_RESTRICTED_AMOUNT)


class TestValidationPriorityPairs:
    def test_program_state_beats_budget_fiscal_on_submit(self, api, hr_admin_headers):
        """PRD §2.8: "Incoming requests are validated against an ordered
        pipeline; when several checks would fail, the earliest one in this
        order wins, and its error is the one returned."
        PRD §2.8: "The program's `status` is `ACTIVE` for
        nomination submission and resubmission, redemption creation, budget
        creation, anniversary scans, and catalog item creation
        (`ERR_PROGRAM_NOT_ACTIVE`)."
        PRD §2.8: "Reserved plus committed plus requested
        points fit within `allocated_points`, and a budget window containing
        the relevant date exists at all (`ERR_BUDGET_EXHAUSTED`,
        `ERR_BUDGET_NOT_FOUND`)."

        Design: Difficulty/priority_pair_validation_conflict/program_state_beats_budget_fiscal_on_submit
        """
        ctx = _ctx(allocated_points=100, program_overrides={"max_points_per_nomination": 1000})
        nominator, nominee = ctx["extras"][0], ctx["employee"]
        program_id = ctx["program"]["id"]
        submit_nomination(program_id, nominee["id"], nominator, 100,
                          type="PEER", reason_code="TEAMWORK",
                          idempotency_key="pp1-n1")
        # Budget now EXHAUSTED; then suspend the program (stage 7 < stage 16).
        get_success_data(api.suspend_program(program_id, hr_admin_headers))

        res = api.create_nomination(
            create_nomination_payload(
                program_id, nominee["id"], type="PEER", points_requested=1,
                reason_code="INNOVATION", message="blocked twice",
                idempotency_key="pp1-n2",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)

        _, meta = validate_paginated(api.list_nominations(
            hr_admin_headers, params={"nominee_id": nominee["id"]}
        ))
        assert meta["total_count"] == 1

    def test_program_gate_rejects_before_capacity_even_with_room(
        self, api, hr_admin_headers
    ):
        """PRD §2.8 stage 7: "The program's `status` is `ACTIVE` for
        nomination submission and resubmission, redemption creation, budget
        creation, anniversary scans, and catalog item creation
        (`ERR_PROGRAM_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/program_state_beats_budget_fiscal_on_submit
        """
        ctx = _ctx()
        nominator, nominee = ctx["extras"][0], ctx["employee"]
        program_id = ctx["program"]["id"]
        get_success_data(api.suspend_program(program_id, hr_admin_headers))
        res = api.create_nomination(
            create_nomination_payload(
                program_id, nominee["id"], type="PEER", points_requested=1,
                reason_code="TEAMWORK", message="suspended program",
                idempotency_key="pp1b-n1",
            ),
            make_employee_headers(nominator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)

    def test_suspension_beats_scope_on_nominate(self, api, hr_admin_headers):
        """PRD §2.8: "when several checks would fail, the earliest one in this
        order wins, and its error is the one returned."
        PRD §2.8: "The acting employee's `program_status`
        is `ELIGIBLE` when nominating as a nominator or redeeming
        (`ERR_EMPLOYEE_SUSPENDED`)."
        PRD §2.8: "A `PEER` nomination stays within one
        department; a `MANAGER` nomination comes from within the nominee's
        manager chain; a `Manager`-role approver sits in the nominee's chain
        (`ERR_NOMINEE_NOT_IN_SCOPE`); order submission and catalog item
        creation require an `ACTIVE` vendor (`ERR_VENDOR_SUSPENDED`)."
        PRD §3.3: "Any `Employee` or `Manager` may submit a nomination,
        provided the acting employee is `ELIGIBLE` — a `SUSPENDED` nominator
        is refused with `ERR_EMPLOYEE_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/suspension_beats_scope_on_nominate
        """
        program = create_program()
        get_success_data(api.activate_program(program["id"], HR))
        dept_a = create_department(name="Eng", chargeback_account_code="GL-ENG")
        dept_b = create_department(name="Sales", chargeback_account_code="GL-SALES")
        create_budget(program["id"], dept_a["id"], allocated_points=10000)
        create_budget(program["id"], dept_b["id"], allocated_points=10000)
        bad_actor = create_employee(dept_a["id"], employee_ref="BAD1")
        nominee = create_employee(dept_b["id"], employee_ref="NOM1")
        suspend_employee(bad_actor["id"], program["id"])

        # SUSPENDED nominator (stage 8) + cross-department PEER (stage 11).
        res = api.create_nomination(
            create_nomination_payload(
                program["id"], nominee["id"], type="PEER", points_requested=100,
                reason_code="TEAMWORK", message="cross dept", idempotency_key="pp2-n1",
            ),
            make_employee_headers(bad_actor["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EMPLOYEE_SUSPENDED)

    def test_suspended_nominator_blocked_even_in_scope(self, api):
        """PRD §3.3: "Any `Employee` or `Manager` may submit a nomination,
        provided the acting employee is `ELIGIBLE` — a `SUSPENDED` nominator
        is refused with `ERR_EMPLOYEE_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/suspension_beats_scope_on_nominate
        """
        ctx = _ctx()
        bad_actor = ctx["extras"][0]
        suspend_employee(bad_actor["id"], ctx["program"]["id"])
        # Same-department PEER (scope would pass); only suspension can fail.
        res = api.create_nomination(
            create_nomination_payload(
                ctx["program"]["id"], ctx["employee"]["id"], type="PEER",
                points_requested=100, reason_code="TEAMWORK",
                message="suspended", idempotency_key="pp2b-n1",
            ),
            make_employee_headers(bad_actor["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EMPLOYEE_SUSPENDED)
