"""Build spec lifecycle (activation supersession, retirement) and work-order
opening/pipeline gating."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_work_order,
    assert_build_spec,
    assert_work_order,
    build_engine_in_dyno_test,
    create_active_spec,
    create_build_spec,
    create_distributor,
    create_graded_return,
    create_received_return,
    create_work_order_payload,
    declare_route,
    get_build_spec,
    get_work_order,
    grade_core_return,
    open_work_order,
    record_dyno_test,
    respond_to_grading,
    set_logical_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
TECH = TEST_USERS["shop_technician_headers"]


class TestBuildSpecLifecycle:
    def test_spec_activation_supersedes_active_sibling(self, api):
        """PRD §3.2: "Every remanufactured engine is produced under a **build
        specification**, created by a `PlantAdmin` in `DRAFT` status."
        PRD §3.2: "Activation is also a supersession event — every other spec
        sharing the same combination of `engine_family`, `application_code`,
        and `emissions_tier` that is currently `ACTIVE` is retired in the same
        transaction, moving from `ACTIVE` to `RETIRED` with its retirement
        time stamped."

        Design: Corner/state_machines/spec_activation_supersedes_active_sibling
        """
        spec_a = create_build_spec(application_code="BLAZER-1996")
        assert spec_a["status"] == "DRAFT", "a spec is created in DRAFT status"
        spec_b = create_build_spec(application_code="BLAZER-1996",
                                   list_price_cents=260000,
                                   core_deposit_cents=210000)
        spec_c = create_build_spec(application_code="JIMMY-1996")
        activate = validate_success(
            api.activate_build_spec(spec_a["id"], ADMIN), 200)
        assert activate["status"] == "ACTIVE"

        activated_b = validate_success(
            api.activate_build_spec(spec_b["id"], ADMIN), 200)
        assert_build_spec(activated_b)
        assert activated_b["status"] == "ACTIVE"

        assert get_build_spec(spec_a["id"])["status"] == "RETIRED", (
            "supersede cascade retires the ACTIVE sibling with the same key")
        assert get_build_spec(spec_c["id"])["status"] == "DRAFT", (
            "a spec with a different application_code is untouched")

    def test_retire_blocked_by_open_work_order(self, api):
        """PRD §3.2: "A spec may also be retired explicitly from `ACTIVE`;
        explicit retirement is refused while any work order referencing the
        spec sits in `QUEUED`, `TEARDOWN`, `MACHINING`, `ASSEMBLY`, or
        `DYNO_TEST` status. `RETIRED` is terminal."

        Design: Corner/state_machines/retire_blocked_by_open_work_order
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-RET",
                                         name="Retire Cores")
        spec = create_active_spec(application_code="SONOMA-1996")
        ret = create_graded_return(distributor, spec)
        wo = open_work_order(ret)
        assert wo["status"] == "QUEUED"

        resp = api.retire_build_spec(spec["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_build_spec(spec["id"])["status"] == "ACTIVE"


class TestWorkOrderOpening:
    def test_work_order_rejected_for_received_and_reject_returns(self, api):
        """PRD §3.5: "The source return must already be `GRADED` or `CLOSED`,
        and its grade must be something other than `REJECT`; a return that is
        still `RECEIVED` or `DISPUTED`, or that was graded `REJECT`, is
        rejected with `ERR_CORE_RETURN_NOT_GRADED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/work_order_requires_graded_non_reject_core
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-GATE",
                                         name="Gate Cores")
        spec = create_active_spec(application_code="C1500-1999")
        ret_received = create_received_return(distributor, spec)
        ret_reject = create_received_return(distributor, spec)
        rejected = grade_core_return(ret_reject["id"], "REJECT",
                                     ["ENGINE_BLOCK"])
        assert rejected["final_credit_cents"] == 0, "REJECT multiplier is 0.00"

        resp1 = api.create_work_order(
            create_work_order_payload(ret_received["id"]), ADMIN)
        validate_error(resp1, ApiErrorId.ERR_CORE_RETURN_NOT_GRADED)

        resp2 = api.create_work_order(
            create_work_order_payload(ret_reject["id"]), ADMIN)
        validate_error(resp2, ApiErrorId.ERR_CORE_RETURN_NOT_GRADED)

    def test_work_order_created_from_graded_or_closed_return(self, api):
        """PRD §3.5: "The source return must already be `GRADED` or `CLOSED`,
        and its grade must be something other than `REJECT`".
        PRD §3.5: "The new work order copies `build_spec_id` from the return,
        enters in `QUEUED` status, and starts with `reman_engine_id` null and
        `rework_count` at 0."

        Design: Difficulty/cross_entity_state_dependency/work_order_requires_graded_non_reject_core
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-GATE",
                                         name="Gate Cores")
        spec = create_active_spec(application_code="C1500-1999")

        ret_graded = create_received_return(distributor, spec)
        grade_core_return(ret_graded["id"], "GRADE_B", [])
        resp = api.create_work_order(
            create_work_order_payload(ret_graded["id"]), ADMIN)
        wo = validate_success(resp, 201)
        assert_work_order(wo)
        assert wo["status"] == "QUEUED"
        assert wo["build_spec_id"] == spec["id"], "spec copied from the return"
        assert wo["reman_engine_id"] is None
        assert wo["rework_count"] == 0

        ret_closed = create_received_return(distributor, spec)
        grade_core_return(ret_closed["id"], "GRADE_C", [])
        respond_to_grading(ret_closed, distributor, "ACCEPT")
        resp2 = api.create_work_order(
            create_work_order_payload(ret_closed["id"]), ADMIN)
        wo2 = validate_success(resp2, 201)
        assert wo2["status"] == "QUEUED", "a CLOSED return also unlocks opening"

    def test_work_order_create_with_draft_spec_rejected(self, api):
        """PRD §3.5: "The build spec carried on the return must be `ACTIVE` at
        this moment; a spec in `DRAFT` or `RETIRED` is rejected with
        `ERR_SPEC_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/validations/work_order_create_with_draft_spec_rejected
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-DRAFT",
                                         name="Draft Spec Cores")
        spec = create_build_spec(application_code="CORSICA-1996")  # stays DRAFT
        ret = create_received_return(distributor, spec)
        grade_core_return(ret["id"], "GRADE_A", [])

        resp = api.create_work_order(
            create_work_order_payload(ret["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_SPEC_NOT_ACTIVE)


class TestPipelineAdvance:
    def test_advance_cannot_skip_pipeline_stage(self, api):
        """PRD §3.5: "The forward path is `QUEUED` → `TEARDOWN` → `MACHINING`
        → `ASSEMBLY` → `DYNO_TEST`, and the pipeline also admits a rework loop
        and a system-driven close."

        Design: Corner/state_machines/advance_cannot_skip_pipeline_stage
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-SKIP",
                                         name="Skip Cores")
        spec = create_active_spec(application_code="CAVALIER-1996")
        ret = create_graded_return(distributor, spec)
        wo = open_work_order(ret)
        assert wo["status"] == "QUEUED"

        resp = api.advance_work_order(wo["id"], {"target": "MACHINING"}, TECH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_work_order(wo["id"])["status"] == "QUEUED"

    def test_assembly_blocked_until_operations_complete(self, api):
        """PRD §3.5: "Entry into `ASSEMBLY` requires that every machining
        operation on the order stands in `COMPLETED` status; advancing with
        any operation still `PENDING` or `FAILED` is rejected with
        `ERR_OPERATIONS_INCOMPLETE` (HTTP 422)."

        Design: Corner/state_machines/assembly_blocked_until_operations_complete
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-ASM",
                                         name="Assembly Cores")
        spec = create_active_spec(application_code="TRACKER-1996")
        ret = create_graded_return(distributor, spec)
        wo = open_work_order(ret)
        wo = advance_work_order(wo["id"], "TEARDOWN")
        declare_route(wo, spec)  # one PENDING operation
        wo = advance_work_order(wo["id"], "MACHINING")

        resp = api.advance_work_order(wo["id"], {"target": "ASSEMBLY"}, TECH)
        validate_error(resp, ApiErrorId.ERR_OPERATIONS_INCOMPLETE)

        after = get_work_order(wo["id"])
        assert after["status"] == "MACHINING"
        assert after["reman_engine_id"] is None, "no engine may be minted"

    def test_rework_requires_failed_latest_dyno(self, api):
        """PRD §3.8: "advancing from `DYNO_TEST` back to `MACHINING` is
        permitted only when the referenced engine's `latest_dyno_result` is
        `FAIL`."

        Design: Corner/state_machines/rework_requires_failed_latest_dyno
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-RW",
                                         name="Rework Cores")
        spec = create_active_spec(application_code="PRIZM-1996")
        ctx = build_engine_in_dyno_test(spec, distributor, slot=0)
        dyno = record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"],
                                slot=0)  # PASS measurements
        assert dyno["result"] == "PASS"
        assert get_work_order(ctx["work_order"]["id"])["status"] == "DYNO_TEST"

        resp = api.advance_work_order(ctx["work_order"]["id"],
                                      {"target": "MACHINING"}, TECH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_work_order(ctx["work_order"]["id"])
        assert after["status"] == "DYNO_TEST"
        assert after["rework_count"] == 0
