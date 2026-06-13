"""State-machine and cascade tests: the RO cyclic hold/resume loop, the
recommended-job branching fork + deferred revisit, the depth-3 approve cascade,
and the depth-2 completion -> technician credit cascade.

Covers difficulty queue rules: non_linear_state_machine, transitive_cascade.
"""
from test_helpers import (
    validate_success,
    fixtures as fx,
)
from test_helpers.test_users import TEST_USERS, make_customer_headers, make_technician_headers
from test_helpers import factories as f

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]
PM = TEST_USERS["parts_manager_headers"]


# ===========================================================================
# non_linear_state_machine — RO cyclic IN_PROGRESS <-> ON_HOLD
# ===========================================================================
class TestRepairOrderHoldResumeLoop:
    def test_hold_moves_in_progress_to_on_hold(self, api):
        """PRD §3.3: "Placing work on hold advances an `IN_PROGRESS` order to
        `ON_HOLD`".

        Design: Difficulty/non_linear_state_machine/repair_order_cyclic_in_progress_on_hold_loop
        """
        state = fx.setup_ro_in_progress(
            api, bay_start="2026-06-02T08:00:00Z", bay_end="2026-06-02T12:00:00Z"
        )
        held = validate_success(
            api.transition_repair_order(state["ro"]["id"], {"action": "HOLD"}, SA), 200
        )
        assert held["status"] == "ON_HOLD"

    def test_resume_returns_on_hold_to_in_progress(self, api):
        """PRD §3.3: "Resuming returns an `ON_HOLD` order to `IN_PROGRESS`".

        Design: Difficulty/non_linear_state_machine/repair_order_cyclic_in_progress_on_hold_loop
        """
        state = fx.setup_ro_in_progress(
            api, bay_start="2026-06-02T08:00:00Z", bay_end="2026-06-02T12:00:00Z"
        )
        ro_id = state["ro"]["id"]
        validate_success(api.transition_repair_order(ro_id, {"action": "HOLD"}, SA), 200)
        resumed = validate_success(
            api.transition_repair_order(ro_id, {"action": "RESUME"}, SA), 200
        )
        assert resumed["status"] == "IN_PROGRESS", (
            "RESUME must return the order to the previously occupied IN_PROGRESS state"
        )


# ===========================================================================
# non_linear_state_machine — RecommendedJob fork + DEFERRED revisit
# ===========================================================================
class TestRecommendedJobForkAndDeferredRevisit:
    def test_pending_job_defers(self, api):
        """PRD §3.11: "Deferring moves a `PENDING` job to `DEFERRED` with no further
        effect."

        Design: Difficulty/non_linear_state_machine/recommended_job_branching_fork_and_deferred_revisit
        """
        s = fx.setup_inspection_with_pending_job(api, item_severity="YELLOW")
        deferred = validate_success(
            api.decide_recommended_job(
                s["recommended_job"]["id"], {"decision": "DEFER"},
                make_customer_headers(s["customer"]["id"]),
            ),
            200,
        )
        assert deferred["status"] == "DEFERRED"

    def test_deferred_job_revisited_to_approved_materialises_labor_line(self, api):
        """PRD §3.11: "a `DEFERRED` job may later be revisited to `APPROVED` or
        `DECLINED`".
        PRD §3.11: "the same cascade runs whether the job was approved out of
        `PENDING` or out of `DEFERRED`. First, a labor line is created on the order
        from the job's `labor_operation_id`, and its identifier is recorded on the
        job as `created_labor_line_id`."

        Design: Difficulty/non_linear_state_machine/recommended_job_branching_fork_and_deferred_revisit
        """
        s = fx.setup_inspection_with_pending_job(api, item_severity="YELLOW")
        cust_headers = make_customer_headers(s["customer"]["id"])
        validate_success(
            api.decide_recommended_job(s["recommended_job"]["id"], {"decision": "DEFER"}, cust_headers),
            200,
        )
        approved = validate_success(
            api.decide_recommended_job(s["recommended_job"]["id"], {"decision": "APPROVE"}, cust_headers),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["created_labor_line_id"] is not None, (
            "DEFERRED->APPROVE revisit must materialise a labor line"
        )


# ===========================================================================
# transitive_cascade — approve -> PartLine -> CoreCharge -> RO deposit (depth 3)
# ===========================================================================
class TestApproveCascadeDepth3:
    def test_approve_cascades_part_line(self, api):
        """PRD §3.11: "if the job carries a `part_number`, a part line is created on
        the order and its identifier is recorded on the job as
        `created_part_line_id`; this part line creation recomputes the order's parts
        total."

        Design: Difficulty/transitive_cascade/approve_job_cascades_partline_corecharge_ro_deposit_depth3
        """
        fx.setup_markup_matrix(api, [(0, 0, 5000, 0.50), (1, 5000, 20000, 0.40)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        technician = fx.create_technician(api)
        operation = fx.create_labor_operation(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        insp = fx.create_inspection(api, ro["id"], technician["id"])
        fx.add_item(api, insp["id"], technician["id"], "Starter", "RED")
        job = fx.create_recommended_job(
            api, insp["id"], technician["id"], ro["id"], operation["id"],
            part_number="ST-9", part_quantity=1, part_unit_cost_cents=8000,
            has_core=True, core_deposit_cents=3000, severity="RED",
        )
        approved = validate_success(
            api.decide_recommended_job(job["id"], {"decision": "APPROVE"},
                                       make_customer_headers(customer["id"])),
            200,
        )
        assert approved["created_part_line_id"] is not None, (
            "approving a job with a part_number must materialise a part line"
        )

    def test_approve_cascades_corecharge_to_ro_deposit_total(self, api):
        """PRD §3.11: "if that created part line carries a core (`has_core` true),
        its creation in turn cascades a core charge in `CHARGED` status, which adds
        its deposit to the order's `core_deposit_total_cents`."
        PRD §3.12: "Its `deposit_cents` is computed at creation as the part line's
        `quantity` multiplied by the part line's per-unit `core_deposit_cents`".

        Design: Difficulty/transitive_cascade/approve_job_cascades_partline_corecharge_ro_deposit_depth3
        """
        fx.setup_markup_matrix(api, [(0, 0, 5000, 0.50), (1, 5000, 20000, 0.40)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        technician = fx.create_technician(api)
        operation = fx.create_labor_operation(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        insp = fx.create_inspection(api, ro["id"], technician["id"])
        fx.add_item(api, insp["id"], technician["id"], "Starter", "RED")
        job = fx.create_recommended_job(
            api, insp["id"], technician["id"], ro["id"], operation["id"],
            part_number="ST-9", part_quantity=1, part_unit_cost_cents=8000,
            has_core=True, core_deposit_cents=3000, severity="RED",
        )
        validate_success(
            api.decide_recommended_job(job["id"], {"decision": "APPROVE"},
                                       make_customer_headers(customer["id"])),
            200,
        )
        ro_now = validate_success(api.get_repair_order(ro["id"], SM), 200)
        # deposit = quantity(1) * core_deposit_cents(3000) = 3000.
        assert ro_now["core_deposit_total_cents"] == 3000, (
            f"core_deposit_total must be 3000 after cascade, got {ro_now['core_deposit_total_cents']}"
        )


# ===========================================================================
# transitive_cascade — RO complete -> tech banked hours -> efficiency (depth 2)
# ===========================================================================
class TestCompleteCascadeCreditsTechnician:
    def test_complete_credits_banked_hours(self, api):
        """PRD §3.7: "On completion of an order, for each of its `COMPLETED`
        non-warranty labor lines that has an assigned technician, that technician's
        `banked_flat_hours` is increased by the line's `book_hours` and their
        `banked_actual_hours` is increased by the line's `actual_hours`".

        Design: Difficulty/transitive_cascade/complete_ro_cascades_labor_credit_to_technician_depth2
        """
        result = _complete_ro_with_flat_line(api)
        tech = validate_success(api.get_technician(result["technician"]["id"], SM), 200)
        assert tech["banked_flat_hours"] == 2.0
        assert tech["banked_actual_hours"] == 1.5

    def test_complete_recomputes_efficiency_pct(self, api):
        """PRD §3.7: "The `efficiency_pct` is one hundred multiplied by
        `banked_flat_hours` divided by `banked_actual_hours`, rounded half up to one
        decimal place."

        Design: Difficulty/transitive_cascade/complete_ro_cascades_labor_credit_to_technician_depth2
        """
        result = _complete_ro_with_flat_line(api)
        tech = validate_success(api.get_technician(result["technician"]["id"], SM), 200)
        # 100 * 2.0 / 1.5 = 133.33... -> 133.3.
        assert tech["efficiency_pct"] == 133.3, (
            f"efficiency_pct must be 133.3, got {tech['efficiency_pct']}"
        )


def _complete_ro_with_flat_line(api):
    """Helper: RO with one technician-assigned FLAT_RATE line (book 2.0 rate 12000),
    clocked 1.5h, line completed, then RO completed."""
    operation = fx.create_labor_operation(api, book_hours=2.0, default_rate_cents=12000)
    technician = fx.create_technician(api)
    customer, vehicle = fx.create_customer_and_vehicle(api)
    bay = fx.create_service_bay(api)
    ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
    ll = validate_success(
        api.create_labor_line(
            ro["id"],
            f.create_labor_line_payload(
                operation["id"], technician_id=technician["id"], billing_method="FLAT_RATE"
            ),
            SM,
        ),
        201,
    )
    fx.authorize_ro(api, ro["id"], customer["id"])
    fx.schedule_ro(api, ro["id"], bay["id"], "2026-06-03T08:00:00Z", "2026-06-03T12:00:00Z")
    fx.transition_ro(api, ro["id"], "START")
    fx.clock_session_and_complete(api, ll["id"], technician["id"],
                                  "2026-06-03T09:00:00Z", "2026-06-03T10:30:00Z")
    validate_success(
        api.complete_repair_order(ro["id"], make_technician_headers(technician["id"])), 200
    )
    return {"technician": technician, "ro": ro}
