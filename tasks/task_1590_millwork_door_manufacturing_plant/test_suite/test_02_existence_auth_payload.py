"""Existence, authentication, payload well-formedness, and validation-ladder ordering."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error,
    make_project, make_order, make_opening, configure_order, make_drawing,
    submit_drawing, approve_drawing, make_program, make_machine, make_booth,
    create_order_payload, create_punch_item_payload,
)

PM_H = TEST_USERS["plant_manager_headers"]
EST_H = TEST_USERS["estimator_headers"]
ANY_H = TEST_USERS["any_headers"]
PL_H = TEST_USERS["production_lead_headers"]


class TestNotFoundSweep:
    def test_error_sweep_not_found(self, api):
        """PRD §2.5: "each missing resource returns its own
        `ERR_{RESOURCE}_NOT_FOUND` (HTTP 404) — concretely
        `ERR_PROJECT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_OPENING_NOT_FOUND`,
        `ERR_DRAWING_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
        `ERR_ROLL_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`,
        `ERR_PUNCH_NOT_FOUND`, or `ERR_TEMPLATE_NOT_FOUND`."

        Design: Corner/errors/error_sweep_not_found
        """
        cases = [
            (api.get_project, "11111111-1111-4111-8111-111111111111", ApiErrorId.ERR_PROJECT_NOT_FOUND),
            (api.get_order, "22222222-2222-4222-8222-222222222222", ApiErrorId.ERR_ORDER_NOT_FOUND),
            (api.get_opening, "33333333-3333-4333-8333-333333333333", ApiErrorId.ERR_OPENING_NOT_FOUND),
            (api.get_shop_drawing, "44444444-4444-4444-8444-444444444444", ApiErrorId.ERR_DRAWING_NOT_FOUND),
            (api.get_machining_program, "55555555-5555-4555-8555-555555555555", ApiErrorId.ERR_PROGRAM_NOT_FOUND),
            (api.get_moulder_machine, "66666666-6666-4666-8666-666666666666", ApiErrorId.ERR_MACHINE_NOT_FOUND),
            (api.get_moulder_setup_slot, "77777777-7777-4777-8777-777777777777", ApiErrorId.ERR_SLOT_NOT_FOUND),
            (api.get_spray_booth, "88888888-8888-4888-8888-888888888888", ApiErrorId.ERR_BOOTH_NOT_FOUND),
            (api.get_finishing_batch, "99999999-9999-4999-8999-999999999999", ApiErrorId.ERR_BATCH_NOT_FOUND),
            (api.get_fire_label_roll, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", ApiErrorId.ERR_ROLL_NOT_FOUND),
            (api.get_label_allocation, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
            (api.get_delivery_trip, "cccccccc-cccc-4ccc-8ccc-cccccccccccc", ApiErrorId.ERR_TRIP_NOT_FOUND),
            (api.get_punch_item, "dddddddd-dddd-4ddd-8ddd-dddddddddddd", ApiErrorId.ERR_PUNCH_NOT_FOUND),
            (api.get_hardware_template, "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", ApiErrorId.ERR_TEMPLATE_NOT_FOUND),
        ]
        for getter, resource_id, expected_error in cases:
            resp = getter(resource_id, ANY_H)
            validate_error(resp, expected_error, 404)


class TestAuthAndPayloadOrdering:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        # Sent with both auth headers omitted.
        resp = api.create_project(
            {"name": "P", "site_address": "1 Main St", "contract_code": "CV-1"}, {},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_existence_beats_payload_on_missing_drawing(self, api):
        """PRD §2.5: "Every request is evaluated against a fixed ladder of
        checks. Evaluation stops at the first rung that fails, and that rung's
        error is the one returned — a later rung never masks an earlier one."
        Existence (rung 3) precedes payload well-formedness (rung 4).

        Design: Corner/validations/existence_beats_payload_on_missing_drawing
        """
        # Nonexistent drawing id AND malformed payload (missing target_status):
        # the 404 must win over the 400.
        resp = api.set_shop_drawing_status(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", {}, EST_H,
        )
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_FOUND, 404)


class TestWindowPayloads:
    def test_invalid_window_inputs_rejected(self, api):
        """PRD §2.8: "a slot whose `end_hour` is not strictly later than its
        `start_hour` is rejected with `ERR_INVALID_SLOT_HOURS` (HTTP 400), and
        a cure window spanning fewer than four shop-hours is rejected with
        `ERR_INVALID_CURE_WINDOW` (HTTP 400)." PRD §3.7: "An arrival date
        earlier than the departure date is rejected with `ERR_INVALID_TRIP_DATES`
        (HTTP 400)."

        Design: Corner/validations/invalid_window_inputs_rejected
        """
        project = make_project(name="P", contract_code="CV-8")
        ctx_order = make_order(project["id"], order_code="O-A8")
        make_opening(ctx_order["id"], opening_no="1")
        configure_order(ctx_order["id"])
        drawing = make_drawing(ctx_order["id"])
        submit_drawing(drawing["id"])
        approve_drawing(drawing["id"])
        program = make_program(drawing["id"], ctx_order["id"], estimated_minutes=30)
        machine = make_machine(machine_code="M-V8", supported_species=["OAK"])

        # Slot with end_hour == start_hour (not strictly later).
        resp = api.create_moulder_setup_slot(
            {"program_id": program["id"], "machine_id": machine["id"],
             "start_hour": 10, "end_hour": 10}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_HOURS, 400)

        # Batch with a 2-hour cure window against a DRAFT order — the payload
        # error (rung 4) fires before the state gate (rung 6).
        order_b = make_order(project["id"], order_code="O-B8", species="MAPLE")
        booth = make_booth(booth_code="B-V8")
        resp = api.create_finishing_batch(
            {"order_id": order_b["id"], "booth_id": booth["id"],
             "cure_start_hour": 10, "cure_end_hour": 12}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CURE_WINDOW, 400)

        # Trip with arrival earlier than departure.
        resp = api.create_delivery_trip(
            {"project_id": project["id"], "trip_code": "T-V8", "truck_capacity_leaves": 4,
             "departure_date": "2026-10-05", "site_arrival_date": "2026-10-04"}, PM_H,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRIP_DATES, 400)
