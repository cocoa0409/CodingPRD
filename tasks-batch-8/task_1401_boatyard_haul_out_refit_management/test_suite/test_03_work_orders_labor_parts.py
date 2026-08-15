"""Work-order estimating, the change-order cycle, labor costing, and parts."""
from test_helpers import (
    ApiErrorId,
    approve_work_order,
    create_part_payload,
    create_refit_job,
    create_vessel,
    create_work_order,
    create_work_order_payload,
    get_job,
    get_statement,
    get_work_order,
    list_ledger_entries,
    log_labor,
    make_owner_headers,
    set_clock,
    setup_job_on_hard,
    start_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, api_client

SW = TEST_USERS["service_writer_headers"]
YM = TEST_USERS["yard_manager_headers"]
AC = TEST_USERS["accountant_headers"]


class TestWorkOrderCreation:

    def test_work_order_created_in_estimate(self):
        """PRD section 3.5: "A new work order starts in `ESTIMATE` with
        `revision` 0 and `change_note` empty until a first change request.
        Its `quoted_total_cents` is computed at creation as the product of
        `quoted_hours` and `quoted_rate_cents` rounded half-up to whole
        cents, plus `quoted_parts_cents` — the rounding applies to the labor
        product only, before the parts allowance is added."

        Design: Corner/entities/work_order_created_in_estimate
        """
        vessel = create_vessel(name="MV Est", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        job = create_refit_job(vessel["id"])
        resp = api_client.create_work_order(
            create_work_order_payload(
                job["id"], type="RIGGING", description="Standing rigging",
                quoted_hours=2.5, quoted_rate_cents=9001,
                quoted_parts_cents=100),
            SW)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ESTIMATE"
        assert data["revision"] == 0
        # round_half_up(2.5 x 9001) = 22503, plus 100 parts = 22603
        assert data["quoted_total_cents"] == 22603

    def test_accountant_cannot_create_work_order(self):
        """PRD section 2.1: "A request whose role is authenticated but not
        permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403); this also covers the kind-conditional segregation on
        compliance holds described below."
        PRD section 4: "| POST | /yard/work-orders | Create a work order on a
        job | ServiceWriter |"

        Design: Corner/rbac/accountant_cannot_create_work_order
        """
        vessel = create_vessel(name="MV Rbac", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        job = create_refit_job(vessel["id"])
        resp = api_client.create_work_order(
            create_work_order_payload(
                job["id"], type="MECHANICAL", description="Engine",
                quoted_hours=1, quoted_rate_cents=8000, quoted_parts_cents=0),
            AC)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_winterization_window_enforced(self):
        """PRD section 3.5: "A seasonal gate applies to winter work: a
        `WINTERIZATION` or `SHRINK_WRAP` work order may be created only when
        the current month-and-day falls within September 15 through December
        15, inclusive; outside that window creation is rejected with
        `ERR_WINTERIZATION_WINDOW`."
        PRD section 2.6: "At server startup the logical clock is exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/validations/winterization_window_enforced
        """
        vessel = create_vessel(name="MV Winter", owner_user_id="owner-1",
                               loa_ft=34, beam_ft=11, hull_type="SAIL",
                               displacement_tons=14)
        job = create_refit_job(vessel["id"])

        # Startup clock is 2026-08-01: outside the seasonal window.
        resp = api_client.create_work_order(
            create_work_order_payload(
                job["id"], type="WINTERIZATION", description="Fog engine",
                quoted_hours=2, quoted_rate_cents=8500,
                quoted_parts_cents=5000),
            SW)
        validate_error(resp, ApiErrorId.ERR_WINTERIZATION_WINDOW)

        set_clock("2026-10-15T09:00:00Z")
        ok = api_client.create_work_order(
            create_work_order_payload(
                job["id"], type="SHRINK_WRAP", description="Shrink wrap",
                quoted_hours=4, quoted_rate_cents=8500,
                quoted_parts_cents=12000),
            SW)
        data = validate_success(ok, expected_status=201)
        assert data["status"] == "ESTIMATE"


class TestChangeOrderCycle:

    def test_change_request_then_requote_returns_to_estimate(self):
        """PRD section 3.5: "A `ServiceWriter` then re-quotes the
        change-requested work order with a fresh `quoted_hours`,
        `quoted_rate_cents`, and `quoted_parts_cents`: the quoted fields are
        replaced, `quoted_total_cents` is recomputed by the same formula as
        at creation, the `revision` increments by one, and the work order
        returns to `ESTIMATE` to await a fresh owner approval."

        Design: Difficulty/non_linear_state_machine/work_order_change_order_cycle
        """
        ctx = setup_job_on_hard(vessel_name="MV Cycle", loa_ft=32,
                                beam_ft=11, displacement_tons=12,
                                row_code="C", total_stands=6, stands_used=3)
        owner_id = ctx["vessel"]["owner_user_id"]
        wo = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                               description="Engine", quoted_hours=10,
                               quoted_rate_cents=8000, quoted_parts_cents=5000)
        assert wo["quoted_total_cents"] == 85000
        approve_work_order(wo["id"], owner_id)
        start_work_order(wo["id"])

        requested = validate_success(api_client.request_change_work_order(
            wo["id"], {"change_note": "Add raw-water pump"},
            make_owner_headers(owner_id)))
        assert requested["status"] == "CHANGE_REQUESTED"
        assert requested["change_note"] == "Add raw-water pump"

        requoted = validate_success(api_client.requote_work_order(
            wo["id"],
            {"quoted_hours": 12, "quoted_rate_cents": 8000,
             "quoted_parts_cents": 5000},
            SW))
        assert requoted["status"] == "ESTIMATE"
        assert requoted["revision"] == 1
        assert requoted["quoted_total_cents"] == 101000, \
            "12 x 8000 + 5000 recomputed by the creation formula"

    def test_requoted_work_order_can_be_reapproved(self):
        """PRD section 3.5: "This is the change-order cycle: `ESTIMATE →
        APPROVED → IN_PROGRESS → CHANGE_REQUESTED → ESTIMATE`, repeatable as
        scope evolves."

        Design: Difficulty/non_linear_state_machine/work_order_change_order_cycle
        """
        ctx = setup_job_on_hard(vessel_name="MV Cycle2", loa_ft=32,
                                beam_ft=11, displacement_tons=12,
                                row_code="C", total_stands=6, stands_used=3)
        owner_id = ctx["vessel"]["owner_user_id"]
        wo = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                               description="Engine", quoted_hours=10,
                               quoted_rate_cents=8000, quoted_parts_cents=5000)
        approve_work_order(wo["id"], owner_id)
        start_work_order(wo["id"])
        validate_success(api_client.request_change_work_order(
            wo["id"], {"change_note": "Add raw-water pump"},
            make_owner_headers(owner_id)))
        validate_success(api_client.requote_work_order(
            wo["id"],
            {"quoted_hours": 12, "quoted_rate_cents": 8000,
             "quoted_parts_cents": 5000},
            SW))

        reapproved = validate_success(
            api_client.approve_work_order(wo["id"],
                                          make_owner_headers(owner_id)))
        assert reapproved["status"] == "APPROVED", \
            "the cycle closes: the requoted estimate can be approved again"


class TestReadinessDependency:

    def _two_started_work_orders(self):
        ctx = setup_job_on_hard(vessel_name="MV Duo", loa_ft=34, beam_ft=11,
                                displacement_tons=14, row_code="D",
                                total_stands=8, stands_used=3)
        owner_id = ctx["vessel"]["owner_user_id"]
        wo1 = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                                description="Engine", quoted_hours=1,
                                quoted_rate_cents=8000, quoted_parts_cents=0)
        wo2 = create_work_order(ctx["job"]["id"], type="ELECTRICAL",
                                description="Wiring", quoted_hours=1,
                                quoted_rate_cents=9000, quoted_parts_cents=0)
        approve_work_order(wo1["id"], owner_id)
        approve_work_order(wo2["id"], owner_id)
        start_work_order(wo1["id"])
        start_work_order(wo2["id"])
        return ctx, wo1, wo2

    def test_completing_first_of_two_work_orders_keeps_job_in_progress(self):
        """PRD section 3.10: "A job becomes `READY_FOR_SPLASH` — from either
        `ON_HARD` or `WORK_IN_PROGRESS` — when three conditions hold
        simultaneously: at least one of the job's work orders is `COMPLETE`;
        every work order of the job is in `COMPLETE` or `CANCELLED`; and the
        job's `open_hold_count` is zero."

        Design: Difficulty/cross_entity_state_dependency/readiness_requires_all_work_orders_terminal
        """
        ctx, wo1, _wo2 = self._two_started_work_orders()
        from test_helpers import complete_work_order
        complete_work_order(wo1["id"])
        assert get_job(ctx["job"]["id"])["status"] == "WORK_IN_PROGRESS", \
            "one non-terminal work order keeps the job out of READY_FOR_SPLASH"

    def test_completing_last_work_order_makes_job_ready_for_splash(self):
        """PRD section 3.10: "A job becomes `READY_FOR_SPLASH` — from either
        `ON_HARD` or `WORK_IN_PROGRESS` — when three conditions hold
        simultaneously: at least one of the job's work orders is `COMPLETE`;
        every work order of the job is in `COMPLETE` or `CANCELLED`; and the
        job's `open_hold_count` is zero."
        PRD section 3.10: "Readiness for splash is a computed job property,
        re-evaluated on every work-order completion and every hold release."

        Design: Difficulty/cross_entity_state_dependency/readiness_requires_all_work_orders_terminal
        """
        ctx, wo1, wo2 = self._two_started_work_orders()
        from test_helpers import complete_work_order
        complete_work_order(wo1["id"])
        complete_work_order(wo2["id"])
        assert get_job(ctx["job"]["id"])["status"] == "READY_FOR_SPLASH"


class TestEstimateActualDivergence:

    def _started_mechanical_order(self):
        ctx = setup_job_on_hard(vessel_name="MV Diverge")
        owner_id = ctx["vessel"]["owner_user_id"]
        wo = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                               description="Engine service", quoted_hours=10,
                               quoted_rate_cents=8000, quoted_parts_cents=5000)
        approve_work_order(wo["id"], owner_id)
        start_work_order(wo["id"])
        return ctx, wo

    def test_estimate_variant_ignores_subcontractor_markup(self):
        """PRD section 3.5: "Its `quoted_total_cents` is computed at creation
        as the product of `quoted_hours` and `quoted_rate_cents` rounded
        half-up to whole cents, plus `quoted_parts_cents` — the rounding
        applies to the labor product only, before the parts allowance is
        added."
        PRD section 3.6: "The estimate and actual variants intentionally
        diverge: the subcontractor markup exists only in the actual variant,
        and quoted hours and parts need not match logged lines."

        Design: Difficulty/dual_variant_calc/work_order_estimate_vs_actual_divergence
        """
        _ctx, wo = self._started_mechanical_order()
        log_labor(wo["id"], worker_type="YARD_CREW", hours=6, rate_cents=8000)
        log_labor(wo["id"], worker_type="SUBCONTRACTOR", hours=4,
                  rate_cents=9000, subcontractor_name="Coastal Marine LLC")

        current = get_work_order(wo["id"])
        assert current["quoted_total_cents"] == 85000, \
            "the estimate variant stays the creation-time quote"
        assert current["actual_cost_cents"] != current["quoted_total_cents"]

    def test_actual_variant_sums_per_line_with_markup(self):
        """PRD section 3.6: "Each line's `line_cost_cents` is the product of
        `hours`, `rate_cents`, and a markup factor, rounded half-up to whole
        cents per line. The markup is 1.15 for `SUBCONTRACTOR` lines and 1.0
        for `YARD_CREW` lines — the yard's fifteen percent subcontractor
        uplift. The work order's `actual_cost_cents` is the sum of
        `line_cost_cents` over all of its labor lines, with no state filter
        because lines are append-only; the rounding order is pinned — round
        each line first, then sum, never the reverse."

        Design: Difficulty/dual_variant_calc/work_order_estimate_vs_actual_divergence
        """
        _ctx, wo = self._started_mechanical_order()
        line1 = log_labor(wo["id"], worker_type="YARD_CREW", hours=6,
                          rate_cents=8000)
        line2 = log_labor(wo["id"], worker_type="SUBCONTRACTOR", hours=4,
                          rate_cents=9000,
                          subcontractor_name="Coastal Marine LLC")
        assert line1["line_cost_cents"] == 48000
        # round_half_up(4 x 9000 x 1.15) = 41400
        assert line2["line_cost_cents"] == 41400
        assert get_work_order(wo["id"])["actual_cost_cents"] == 89400


class TestPerLineRounding:

    def test_per_line_rounding_then_sum(self):
        """PRD section 3.6: "The work order's `actual_cost_cents` is the sum
        of `line_cost_cents` over all of its labor lines, with no state
        filter because lines are append-only; the rounding order is pinned —
        round each line first, then sum, never the reverse."
        PRD section 2.7: "Every monetary multiplication is rounded half-up to
        zero decimal places, and the rounding point is pinned per rule:
        quoted totals round the labor product only, before adding the parts
        allowance; labor lines round each line individually before any
        summation — never sum-then-round; daily storage rounds each calendar
        day's charge individually before any accumulation."

        Design: Difficulty/combinatorial_formula/labor_per_line_rounding_then_sum
        """
        ctx = setup_job_on_hard(vessel_name="MV Round", loa_ft=32, beam_ft=11,
                                displacement_tons=12, row_code="R",
                                total_stands=6, stands_used=3)
        owner_id = ctx["vessel"]["owner_user_id"]
        wo = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                               description="Sub work", quoted_hours=1,
                               quoted_rate_cents=1000, quoted_parts_cents=0)
        approve_work_order(wo["id"], owner_id)
        start_work_order(wo["id"])

        line1 = log_labor(wo["id"], worker_type="SUBCONTRACTOR", hours=2.5,
                          rate_cents=6100, subcontractor_name="Sub A")
        line2 = log_labor(wo["id"], worker_type="SUBCONTRACTOR", hours=1.5,
                          rate_cents=7700, subcontractor_name="Sub A")
        # 2.5 x 6100 x 1.15 = 17537.5 -> 17538; 1.5 x 7700 x 1.15 = 13282.5
        # -> 13283; per-line sum = 30821 (sum-then-round would be 30820).
        assert line1["line_cost_cents"] == 17538
        assert line2["line_cost_cents"] == 13283
        current = get_work_order(wo["id"])
        assert current["actual_cost_cents"] == 30821
        assert current["actual_cost_cents"] != 30820

    def test_per_line_rounding_flows_to_completion_charge(self):
        """PRD section 3.6: "When the work order's `actual_cost_cents` is
        greater than zero, completion posts a system ledger charge of kind
        `CHARGE`, category `LABOR`, amount equal to `actual_cost_cents`,
        status `POSTED`, with `source_work_order_id` pointing at the
        completed work order."

        Design: Difficulty/combinatorial_formula/labor_per_line_rounding_then_sum
        """
        ctx = setup_job_on_hard(vessel_name="MV Round2", loa_ft=32,
                                beam_ft=11, displacement_tons=12, row_code="R",
                                total_stands=6, stands_used=3)
        owner_id = ctx["vessel"]["owner_user_id"]
        wo = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                               description="Sub work", quoted_hours=1,
                               quoted_rate_cents=1000, quoted_parts_cents=0)
        approve_work_order(wo["id"], owner_id)
        start_work_order(wo["id"])
        log_labor(wo["id"], worker_type="SUBCONTRACTOR", hours=2.5,
                  rate_cents=6100, subcontractor_name="Sub A")
        log_labor(wo["id"], worker_type="SUBCONTRACTOR", hours=1.5,
                  rate_cents=7700, subcontractor_name="Sub A")

        from test_helpers import complete_work_order
        complete_work_order(wo["id"])
        statement = get_statement(ctx["job"]["id"])
        assert statement["labor_charges_cents"] == 30821, \
            "the LABOR charge carries the per-line-rounded actual cost"
        charges = list_ledger_entries(ctx["job"]["id"],
                                      params={"kind": "CHARGE"})
        assert len(charges) == 1
        assert charges[0]["category"] == "LABOR"
        assert charges[0]["amount_cents"] == 30821
        assert charges[0]["source_work_order_id"] == wo["id"]


class TestLaborRules:

    def test_labor_entry_immutable_no_version(self):
        """PRD section 2.4: "Two entity families are leaner by design:
        `LaborEntry` and `LedgerEntry` are append-only records that carry
        only `id` and `created_at` — neither `updated_at` nor `version`
        exists on them, because they are never mutated after creation (a
        ledger correction voids and re-posts rather than editing in place)."

        Design: Corner/entities/labor_entry_immutable_no_version
        """
        ctx = setup_job_on_hard(vessel_name="MV Imm", loa_ft=30, beam_ft=10,
                                displacement_tons=10, row_code="I",
                                total_stands=6, stands_used=3)
        owner_id = ctx["vessel"]["owner_user_id"]
        wo = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                               description="Engine", quoted_hours=2,
                               quoted_rate_cents=8000, quoted_parts_cents=0)
        approve_work_order(wo["id"], owner_id)
        start_work_order(wo["id"])

        resp = api_client.create_labor_entry(
            {"work_order_id": wo["id"], "worker_type": "YARD_CREW",
             "hours": 1, "rate_cents": 8000},
            SW)
        data = validate_success(resp, expected_status=201)
        assert data["line_cost_cents"] == 8000
        assert "version" not in data, "append-only record carries no version"
        assert "updated_at" not in data
        assert data.get("id") and data.get("created_at")

    def test_work_order_complete_from_estimate_rejected(self):
        """PRD section 3.6: "Completing an `IN_PROGRESS` work order — a
        `ServiceWriter` action — moves it to `COMPLETE`."
        PRD section 2.9: "State legality comes seventh — a wrong from-state
        yields `ERR_INVALID_STATE`, an entity already in a terminal state
        yields `ERR_ALREADY_TERMINAL`, and a splash booking against a job
        that is not ready yields `ERR_JOB_NOT_READY_FOR_SPLASH`."

        Design: Corner/state_machines/work_order_complete_from_estimate_rejected
        """
        vessel = create_vessel(name="MV BadTrans", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        job = create_refit_job(vessel["id"])
        wo = create_work_order(job["id"], type="ELECTRICAL",
                               description="Panel", quoted_hours=2,
                               quoted_rate_cents=9000, quoted_parts_cents=0)

        resp = api_client.complete_work_order(wo["id"], SW)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_work_order(wo["id"])["status"] == "ESTIMATE"
        assert list_ledger_entries(job["id"]) == [], \
            "a rejected completion must not post a LABOR charge"

    def test_labor_state_beats_subcontractor_policy(self):
        """PRD section 2.9: "State legality comes seventh — a wrong
        from-state yields `ERR_INVALID_STATE`, an entity already in a
        terminal state yields `ERR_ALREADY_TERMINAL`, and a splash booking
        against a job that is not ready yields `ERR_JOB_NOT_READY_FOR_SPLASH`.
        Only after all seven generic gates pass do the business rules of
        Section 3 apply, in the order each workflow narrative states them."
        PRD section 3.6: "Logging labor against a work order in any other
        state is rejected with `ERR_INVALID_STATE`; a missing
        `subcontractor_name` on subcontractor labor is rejected with
        `ERR_VALIDATION`. Yard policy prohibits subcontractor labor on
        `BOTTOM_PAINT` work orders outright, for environmental-liability
        reasons; such a line is rejected with
        `ERR_SUBCONTRACTOR_NOT_ALLOWED`."

        Design: Corner/validations/labor_state_beats_subcontractor_policy
        """
        ctx = setup_job_on_hard(vessel_name="MV Prio2", loa_ft=30, beam_ft=10,
                                displacement_tons=10, row_code="P2",
                                total_stands=6, stands_used=3)
        wo = create_work_order(ctx["job"]["id"], type="BOTTOM_PAINT",
                               description="Bottom paint", quoted_hours=8,
                               quoted_rate_cents=7500,
                               quoted_parts_cents=20000)
        # Work order is still ESTIMATE: both the IN_PROGRESS state gate and
        # the subcontractor-on-BOTTOM_PAINT policy are violated.
        resp = api_client.create_labor_entry(
            {"work_order_id": wo["id"], "worker_type": "SUBCONTRACTOR",
             "hours": 2, "rate_cents": 9000, "subcontractor_name": "Sub X"},
            SW)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_subcontractor_name_missing_rejected(self):
        """PRD section 3.6: "Each line carries the `work_order_id`, the
        `worker_type` (`YARD_CREW` or `SUBCONTRACTOR`), the `hours` worked
        (greater than zero), the `rate_cents` per hour (greater than zero),
        and — required exactly when the `worker_type` is `SUBCONTRACTOR` —
        the `subcontractor_name`. Logging labor against a work order in any
        other state is rejected with `ERR_INVALID_STATE`; a missing
        `subcontractor_name` on subcontractor labor is rejected with
        `ERR_VALIDATION`."

        Design: Corner/validations/subcontractor_name_missing_rejected
        """
        ctx = setup_job_on_hard(vessel_name="MV Sub", loa_ft=30, beam_ft=10,
                                displacement_tons=10, row_code="SB",
                                total_stands=6, stands_used=3)
        owner_id = ctx["vessel"]["owner_user_id"]
        wo = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                               description="Engine", quoted_hours=2,
                               quoted_rate_cents=8000, quoted_parts_cents=0)
        approve_work_order(wo["id"], owner_id)
        start_work_order(wo["id"])

        resp = api_client.create_labor_entry(
            {"work_order_id": wo["id"], "worker_type": "SUBCONTRACTOR",
             "hours": 1, "rate_cents": 9000},
            SW)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestPartsPolicy:

    def _intake_job(self, name="MV Paint"):
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import (create_submitted_job,
                                  create_vessel_with_insurance)
        vessel, _c = create_vessel_with_insurance(
            name=name, owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="SAIL", displacement_tons=10, policy_no=f"POL-{name}")
        return vessel, create_submitted_job(vessel["id"])

    def test_owner_supplied_bottom_paint_rejected(self):
        """PRD section 3.7: "Yard policy prohibits owner-supplied bottom
        paint: a part with `owner_supplied` true and `category`
        `BOTTOM_PAINT` is rejected with `ERR_OWNER_PARTS_PROHIBITED`."

        Design: Corner/validations/owner_supplied_bottom_paint_rejected
        """
        vessel, job = self._intake_job()
        resp = api_client.create_part(
            create_part_payload(
                job["id"], description="Owner bottom paint",
                category="BOTTOM_PAINT", owner_supplied=True,
                declared_value_cents=40000),
            make_owner_headers("owner-1"))
        validate_error(resp, ApiErrorId.ERR_OWNER_PARTS_PROHIBITED)

        ok = api_client.create_part(
            create_part_payload(
                job["id"], description="Yard bottom paint",
                category="BOTTOM_PAINT", owner_supplied=False,
                declared_value_cents=40000),
            SW)
        data = validate_success(ok, expected_status=201)
        assert data["status"] == "EXPECTED"

    def test_owner_part_handling_fee_rounding(self):
        """PRD section 3.7: "Inspecting with outcome `RECEIVED` moves the
        part to `RECEIVED`; when the part is owner-supplied, inspection posts
        a system ledger charge of kind `CHARGE`, category `PARTS_HANDLING`,
        status `POSTED`, whose amount is ten percent of
        `declared_value_cents` rounded half-up to whole cents, with
        `source_part_id` pointing at the part."

        Design: Corner/calculations/owner_part_handling_fee_rounding
        """
        vessel, job = self._intake_job(name="MV Parts")
        p_owner = validate_success(api_client.create_part(
            create_part_payload(
                job["id"], description="Owner alternator",
                category="ELECTRICAL", owner_supplied=True,
                declared_value_cents=33333),
            make_owner_headers("owner-1")), expected_status=201)
        p_yard = validate_success(api_client.create_part(
            create_part_payload(
                job["id"], description="Yard filter", category="MECHANICAL",
                owner_supplied=False, declared_value_cents=50000),
            SW), expected_status=201)

        r1 = validate_success(api_client.inspect_part(
            p_owner["id"], {"outcome": "RECEIVED", "inspect_note": "OK"}, SW))
        r2 = validate_success(api_client.inspect_part(
            p_yard["id"], {"outcome": "RECEIVED"}, SW))
        assert r1["status"] == "RECEIVED"
        assert r2["status"] == "RECEIVED"

        charges = list_ledger_entries(job["id"], params={"kind": "CHARGE"})
        assert len(charges) == 1, "only the owner-supplied part posts a fee"
        assert charges[0]["category"] == "PARTS_HANDLING"
        # round_half_up(0.10 x 33333) = 3333
        assert charges[0]["amount_cents"] == 3333
        assert charges[0]["source_part_id"] == p_owner["id"]

    def test_parts_filtered_list_by_status(self):
        """PRD section 3.7: "Parts of a job are listed with pagination and an
        optional `status` filter."

        Design: Corner/endpoints/parts_filtered_list_by_status
        """
        _vessel, job = self._intake_job(name="MV Filter")
        p_a = validate_success(api_client.create_part(
            create_part_payload(job["id"], description="Filter A",
                                category="MECHANICAL", owner_supplied=False,
                                declared_value_cents=1000),
            SW), expected_status=201)
        p_b = validate_success(api_client.create_part(
            create_part_payload(job["id"], description="Filter B",
                                category="ELECTRICAL", owner_supplied=False,
                                declared_value_cents=2000),
            SW), expected_status=201)
        validate_success(api_client.inspect_part(
            p_a["id"], {"outcome": "RECEIVED"}, SW))

        received, _m1 = validate_paginated(api_client.list_parts(
            job["id"], SW, params={"status": "RECEIVED"}))
        assert [p["id"] for p in received] == [p_a["id"]]

        expected, _m2 = validate_paginated(api_client.list_parts(
            job["id"], SW, params={"status": "EXPECTED"}))
        assert [p["id"] for p in expected] == [p_b["id"]]


class TestOwnerScope:

    def test_owner_cannot_approve_others_vessel_work_order(self):
        """PRD section 3.5: "Approval is ownership-scoped: the acting owner's
        `X-User-ID` must equal the vessel's `owner_user_id`, else the
        approval is rejected with `ERR_OWNERSHIP_MISMATCH`."
        PRD section 2.1: "An owner attempting to approve a work order,
        request a change, register a part, or read a vessel-scoped resource
        (job, statement, work order, part) belonging to a different
        `owner_user_id` is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/owner_cannot_approve_others_vessel_work_order
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_vessel_with_insurance
        vessel, _c = create_vessel_with_insurance(
            name="MV Scope", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-S5")
        job = create_refit_job(vessel["id"])
        wo = create_work_order(job["id"], type="MECHANICAL",
                               description="Engine", quoted_hours=1,
                               quoted_rate_cents=8000, quoted_parts_cents=0)

        resp = api_client.approve_work_order(
            wo["id"], make_owner_headers("owner-2"))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        assert get_work_order(wo["id"])["status"] == "ESTIMATE"
