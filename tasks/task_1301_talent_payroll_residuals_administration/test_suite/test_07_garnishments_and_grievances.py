"""Garnishment order administration and grievance case lifecycle."""
from test_helpers import (
    ADMIN,
    AUDITOR,
    SUPERVISOR,
    ApiErrorId,
    assert_garnishment_order,
    assert_grievance_case,
    assert_pay_line,
    create_garnishment,
    create_garnishment_order_payload,
    create_open_batch,
    create_under_review_grievance,
    get_engagement,
    get_garnishment_order,
    get_grievance,
    get_success_data,
    list_pay_lines,
    setup_standard,
    validate_error,
    validate_success,
)


class TestGarnishmentOrders:
    def test_create_defaults_applied(self, api):
        """PRD §3.10: "The order is created in `ACTIVE` status with
        `total_withheld_cents` starting at zero."

        Design: Corner/entities/garnishment_order_defaults_applied
        """
        ctx_perf = setup_standard()["perf"]
        resp = api.create_garnishment_order(
            create_garnishment_order_payload(ctx_perf["id"]), ADMIN)
        order = validate_success(resp, expected_status=201)
        assert_garnishment_order(order)
        assert order["status"] == "ACTIVE"
        assert order["total_withheld_cents"] == 0

    def test_both_spec_fields_rejected(self, api):
        """PRD §3.10: "A `PayrollAdmin` enters a garnishment order against a
        performer by supplying ... exactly one of `pct_of_disposable` or
        `fixed_amount_cents`. Setting both, or neither, is rejected with
        `ERR_GARNISHMENT_SPEC_INVALID`."

        Design: Corner/validations/garnishment_both_spec_fields_rejected
        """
        perf = setup_standard()["perf"]
        payload = create_garnishment_order_payload(
            perf["id"], creditor_name="Greedy Creditor",
            order_type="CREDITOR_JUDGMENT", priority_rank=1,
            pct_of_disposable=0.20, fixed_amount_cents=5000)
        resp = api.create_garnishment_order(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_GARNISHMENT_SPEC_INVALID)

    def test_release_from_released_rejected(self, api):
        """PRD §3.10: "Release by a `PayrollAdmin` transitions an `ACTIVE` order to
        `RELEASED` and increments its `version`." — `RELEASED` is terminal, and
        PRD §2.7 routes small-entity lifecycle gate failures to
        `ERR_RESOURCE_INVALID_STATE`: "4. State gates on the target resource:
        batch lifecycle (`ERR_BATCH_INVALID_STATE`), timecard review
        (`ERR_TIMECARD_INVALID_STATE`), engagement lifecycle
        (`ERR_ENGAGEMENT_INVALID_STATE`), residual lifecycle
        (`ERR_RESIDUAL_INVALID_STATE`), small-entity lifecycle
        (`ERR_RESOURCE_INVALID_STATE`), agreement ratification
        (`ERR_AGREEMENT_INVALID_STATE`)".

        Design: Corner/state_machines/garnishment_release_from_released_rejected
        """
        perf = setup_standard()["perf"]
        order = create_garnishment(perf["id"])
        get_success_data(api.release_garnishment_order(order["id"], ADMIN))
        resp = api.release_garnishment_order(order["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_INVALID_STATE)
        assert get_garnishment_order(order["id"])["status"] == "RELEASED"


class TestGrievanceAdjustmentCascade:
    def test_resolve_with_award_creates_adjustment_line(self, api):
        """PRD §3.17: "A positive award creates a `GRIEVANCE_ADJUSTMENT` pay line
        in the open batch, with `source_id` pointing at the grievance, `status` =
        `UNPAID`, and `gross_cents` equal to the award."
        PRD §3.12: "for `RESIDUAL` and `GRIEVANCE_ADJUSTMENT` lines it is the
        performer's `tax_residency_state`".
        PRD §3.14: "`GRIEVANCE_ADJUSTMENT` lines are exempt regardless of payee
        type. Exempt lines always carry `garnished_cents` = 0."

        Design: Difficulty/transitive_cascade/grievance_resolve_adjustment_two_link_cascade
        """
        ctx = setup_standard()
        batch = create_open_batch()
        grv = create_under_review_grievance(ctx["eng"]["id"])
        resolved = get_success_data(api.resolve_grievance_case(grv["id"], 10000,
                                                               SUPERVISOR))
        assert_grievance_case(resolved)
        assert resolved["status"] == "RESOLVED"
        assert resolved["awarded_amount_cents"] == 10000

        lines = list_pay_lines()
        assert len(lines) == 1, "link 1: exactly one adjustment line in the batch"
        line = lines[0]
        assert_pay_line(line)
        assert line["pay_batch_id"] == batch["id"]
        assert line["source_type"] == "GRIEVANCE_ADJUSTMENT"
        assert line["source_id"] == grv["id"]
        assert line["gross_cents"] == 10000
        assert line["jurisdiction_code"] == "CA", "performer tax_residency_state"
        assert line["tax_cents"] == 1000, "round_half_up(10000 x 0.10)"
        assert line["garnished_cents"] == 0, "adjustment lines are exempt"
        assert line["phw_cents"] == 1570, "600 + 850 + 120 per-component rounding"
        assert line["net_cents"] == 9000
        assert line["status"] == "UNPAID"

    def test_adjustment_line_recomputes_engagement_accrual(self, api):
        """PRD §3.17: "The creation of this line recomputes the engagement's
        `accrued_adjustment_cents` as the sum of `gross_cents` over its
        `GRIEVANCE_ADJUSTMENT` pay lines."

        Design: Difficulty/transitive_cascade/grievance_resolve_adjustment_two_link_cascade
        """
        ctx = setup_standard()
        create_open_batch()
        grv = create_under_review_grievance(ctx["eng"]["id"])
        assert get_engagement(ctx["eng"]["id"])["accrued_adjustment_cents"] == 0
        get_success_data(api.resolve_grievance_case(grv["id"], 10000, SUPERVISOR))
        eng_after = get_engagement(ctx["eng"]["id"])
        assert eng_after["accrued_adjustment_cents"] == 10000, (
            "link 2: line creation recomputes the engagement accrual")


class TestGrievanceLifecycle:
    def test_escalated_branch_resolves_with_zero_award(self, api):
        """PRD §3.17: "Escalation by a `UnionAuditor` moves a grievance from
        `UNDER_REVIEW` to `ESCALATED` and increments `version`."
        PRD §3.17: "Resolution by a `PayrollSupervisor` moves a grievance from
        either `UNDER_REVIEW` or `ESCALATED` to `RESOLVED` and increments
        `version`". "A positive award creates a `GRIEVANCE_ADJUSTMENT` pay line in
        the open batch" — a zero award creates no line.

        Design: Corner/state_machines/grievance_escalated_branch_resolves
        """
        ctx = setup_standard()
        grv = create_under_review_grievance(ctx["eng"]["id"],
                                            category="PENALTY_OMITTED",
                                            claimed_amount_cents=2500,
                                            description="meal penalty missing")
        escalated = get_success_data(api.escalate_grievance_case(grv["id"], AUDITOR))
        assert escalated["status"] == "ESCALATED"
        resolved = get_success_data(api.resolve_grievance_case(grv["id"], 0,
                                                               SUPERVISOR))
        assert resolved["status"] == "RESOLVED"
        assert resolved["awarded_amount_cents"] == 0
        assert list_pay_lines() == [], "zero award creates no adjustment line"

    def test_resolve_with_award_without_open_batch_rejected(self, api):
        """PRD §3.17: "When the awarded amount is greater than zero, exactly one
        pay batch must currently be `OPEN` — otherwise the resolution is rejected
        with `ERR_NO_OPEN_BATCH`."

        Design: Corner/validations/grievance_resolve_award_without_open_batch_rejected
        """
        ctx = setup_standard()
        grv = create_under_review_grievance(ctx["eng"]["id"])
        resp = api.resolve_grievance_case(grv["id"], 10000, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_BATCH)
        assert get_grievance(grv["id"])["status"] == "UNDER_REVIEW"
