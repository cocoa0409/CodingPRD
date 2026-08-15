"""RBAC denial and segregation-of-duties on controlled steps (PRD §2.1, §2.10)."""
from test_helpers import (
    TEST_USERS,
    create_batch,
    create_cycle,
    create_driver,
    create_line,
    create_plan,
    create_plant,
    create_product,
    create_product_payload,
    create_stale_return,
    create_store,
    lock_plan,
    make_driver_headers,
    make_operator_headers,
    make_qa_headers,
    make_store_receiver_headers,
    release_plan,
    set_clock,
    setup_delivered_stop_scenario,
    setup_dispatched_route_scenario,
    setup_line_dirty_with_sesame,
    validate_error,
    validate_success,
)


class TestRoleExclusiveDenied:
    def test_store_receiver_cannot_create_product_forbidden(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD §4 authorizes
        only PlantAdmin for `POST /bakery/products`.

        Design: Corner/rbac/store_receiver_cannot_create_product_forbidden
        """
        plant = create_plant()
        store = create_store(plant["id"])
        resp = api.create_product(
            create_product_payload(plant["id"], sku="SKU-X", name="X"),
            make_store_receiver_headers(store["id"]),
        )
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


class TestDriverOwnershipMismatch:
    def test_driver_ownership_mismatch_forbidden(self, api):
        """PRD §3.6: "Delivering requires the route to be `DISPATCHED`, the
        caller to be the route's driver, and every batch in `batch_ids` to
        still be `RELEASED` (violations are `ERR_INVALID_STATE`,
        `ERR_FORBIDDEN_FOR_ROLE`, and `ERR_INVALID_STATE` respectively)."
        PRD §2.1: "When `X-User-Role` is `Driver`, `X-User-ID` is the `id`
        of the acting Driver entity; ownership checks on any resource that
        references a driver compare the resource's `driver_id` field to
        `X-User-ID`."

        Design: Corner/rbac/driver_ownership_mismatch_forbidden
        """
        # Build the full dispatched chain, then attempt deliver with a
        # DIFFERENT Driver id.
        ctx = setup_dispatched_route_scenario(plant_name="Plant P", order_qty=100)
        plant = ctx["plant"]
        stop = ctx["stop"]

        drv2 = create_driver(plant["id"], name="Driver Two")

        resp = api.deliver_route_stop(
            stop["id"],
            {"delivered_units": 100, "on_shelf_units_observed": 0},
            make_driver_headers(drv2["id"]),
        )
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)
        after = validate_success(
            api.get_route_stop(stop["id"], TEST_USERS["planner_headers"])
        )
        assert after["status"] == "PENDING"


class TestSanitationVerifyByStarterForbidden:
    def test_sanitation_verify_by_starter_forbidden(self, api):
        """PRD §2.10: "The operator who starts a sanitation cycle may not
        verify it: the verifying `QALead`'s `X-User-ID` must differ from the
        cycle's recorded `started_by_user_id`." Any violation is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/rbac/sanitation_verify_by_starter_forbidden
        """
        ctx = setup_line_dirty_with_sesame(plant_name="Plant P SoD San")
        line = ctx["line"]

        op_id = "op-1"
        cycle = create_cycle(line["id"], to_allergen_class="NONE", operator_id=op_id)
        validate_success(
            api.start_sanitation_cycle(cycle["id"], make_operator_headers(op_id))
        )
        # Dwell satisfied: 120 minutes elapsed (SESAME -> NONE row).
        set_clock("2026-08-09T10:10:00Z")

        # The verifier's X-User-ID equals the cycle's started_by_user_id.
        resp = api.verify_sanitation_cycle(cycle["id"], make_qa_headers(op_id))
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        after = validate_success(
            api.get_sanitation_cycle(cycle["id"], TEST_USERS["planner_headers"])
        )
        assert after["status"] == "IN_PROGRESS"


class TestBatchReleaseByCompletingOperatorForbidden:
    def test_batch_release_by_completing_operator_forbidden(self, api):
        """PRD §2.10: "The operator who completes a bake may not QA-release
        that batch: the releasing `QALead`'s `X-User-ID` must differ from the
        batch's recorded `completed_by_user_id`." Any violation is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/rbac/batch_release_by_completing_operator_forbidden
        """
        plant = create_plant(name="Plant P SoD Bake")
        product_a = create_product(plant["id"])
        line = create_line(plant["id"])
        set_clock("2026-08-09T07:50:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        batch = create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=locked_plan["version"], qty_units=100,
        )
        release_plan(plan["id"])

        op_id = "op-1"
        op = make_operator_headers(op_id)
        validate_success(api.start_mix(batch["id"], op))
        validate_success(api.start_proof(batch["id"], op))
        set_clock("2026-08-09T09:00:00Z")
        validate_success(api.start_bake(batch["id"], op))
        validate_success(api.complete_bake(batch["id"], op))

        # Releasing QALead's X-User-ID equals the batch's completed_by_user_id.
        resp = api.release_batch(batch["id"], make_qa_headers(op_id))
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        after = validate_success(api.get_batch(batch["id"], TEST_USERS["planner_headers"]))
        assert after["status"] == "COOLING"


class TestStaleVerifyByRecordingDriverForbidden:
    def test_stale_verify_by_recording_driver_forbidden(self, api):
        """PRD §2.10: "The driver who records a stale return may not verify
        it: the verifying `QALead`'s `X-User-ID` must differ from the
        return's recorded `recorded_by_driver_id`." Any violation is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/rbac/stale_verify_by_recording_driver_forbidden
        """
        ctx = setup_delivered_stop_scenario(plant_name="Plant P SoD Stale", order_qty=100)
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch = ctx["batch"]

        set_clock("2026-08-10T15:00:00Z")
        sre = create_stale_return(
            store["id"], stop["id"],
            [{"batch_id": batch["id"], "qty": 2}],
            driver["id"],
        )
        # Verifier's X-User-ID equals the return's recorded_by_driver_id.
        resp = api.verify_stale_return(
            sre["id"],
            {"verified_lines": [{"batch_id": batch["id"], "qty": 2}]},
            make_qa_headers(driver["id"]),
        )
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        after = validate_success(
            api.get_stale_return(sre["id"], TEST_USERS["planner_headers"])
        )
        assert after["status"] == "PENDING_VERIFICATION"
