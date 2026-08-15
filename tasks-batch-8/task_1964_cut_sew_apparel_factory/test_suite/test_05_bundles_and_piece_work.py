"""The sewing floor: bundles and piece work (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_operation_spec,
    api_client,
    create_available_fabric_roll,
    create_draft_tech_pack,
    create_line_assignment,
    create_marker_payload,
    create_operator,
    create_production_order,
    create_sewing_line,
    get_success_data,
    log_piece_work,
    make_sewing_operator_headers,
    plan_order,
    setup_planned_order_with_bundle,
    setup_released_bundle_with_operator,
    setup_style_with_approved_pack,
    validate_error,
    validate_paginated,
    validate_success,
    verify_entry,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
CUTMGR = TEST_USERS["cutting_manager_headers"]
SUPER = TEST_USERS["line_supervisor_headers"]
ANY = TEST_USERS["any_headers"]


def _cut_bundles_for_order(order_qty=4, size="M"):
    """Approved pack -> planned order -> approved marker -> CUTTING ->
    cut -> bundles. Returns (ctx-dict) via the composite fixture."""
    return setup_planned_order_with_bundle(order_qty=order_qty, size=size)


class TestBundleCreation:
    def test_bundle_created_in_ticketed_initial_state(self):
        """PRD §3.5: "starts in `TICKETED` status with `pre_rework_status`
        null and `completed_through_seq` zero, and receives a sequential
        `ticket_no` of the form `{order_seq}-{size}-{n}`".

        Design: Corner/state_machines/bundle_created_in_ticketed_initial_state
        """
        ctx = _cut_bundles_for_order(order_qty=4)
        bundle = ctx["bundles"][0]
        assert bundle["status"] == "TICKETED"
        assert bundle["qty"] == 4
        assert bundle["size"] == "M"
        assert isinstance(bundle["ticket_no"], str) and bundle["ticket_no"]
        assert bundle["completed_through_seq"] == 0
        assert bundle["pre_rework_status"] is None
        assert bundle["marker_id"] == ctx["marker"]["id"]
        assert bundle["production_order_id"] == ctx["order"]["id"]

    def test_bundle_ticket_nos_unique_across_sizes(self):
        """PRD §3.5: "receives a sequential `ticket_no` of the form
        `{order_seq}-{size}-{n}`, where `order_seq` is the production order's
        creation ordinal and `n` is a one-based counter running across the
        cut's size lines in supplied order."

        Design: Corner/state_machines/bundle_created_in_ticketed_initial_state
        """
        style, pack, _ops = setup_style_with_approved_pack(
            style_overrides={"size_run": ["S", "M"]},
        )
        order = create_production_order(
            style["id"], PLANNER,
            size_quantities=[{"size": "M", "qty": 3}, {"size": "S", "qty": 2}],
        )
        plan_order(order["id"], pack["id"], PLANNER)
        roll = create_available_fabric_roll(TEST_USERS["materials_planner_headers"])
        marker = get_success_data(api_client.create_marker(
            create_marker_payload(
                production_order_id=order["id"], fabric_roll_id=roll["id"],
                planned_pieces=5,
            ),
            CUTMGR,
        ))
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        get_success_data(api_client.start_cutting(order["id"], PLANNER))
        get_success_data(api_client.cut_marker(
            marker["id"],
            {"size_quantities": [{"size": "M", "qty": 3}, {"size": "S", "qty": 2}]},
            CUTMGR,
        ))
        bundles, _ = validate_paginated(
            api_client.list_bundles(ANY, params={"marker_id": marker["id"]})
        )
        assert len(bundles) == 2
        ticket_nos = {b["ticket_no"] for b in bundles}
        assert len(ticket_nos) == 2, "ticket_no must be unique per bundle"
        assert all(t for t in ticket_nos)


class TestBundleProgression:
    def test_bundle_auto_in_progress_on_first_piece_work_log(self):
        """PRD §3.6: "The first entry logged against a `RELEASED` bundle
        automatically moves the bundle to `IN_PROGRESS`, incrementing the
        bundle's `version`."

        Design: Corner/state_machines/bundle_auto_in_progress_on_first_piece_work_log
        """
        ctx = setup_released_bundle_with_operator(order_qty=4)
        assert ctx["bundle"]["status"] == "RELEASED"
        entry = log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=1,
        )
        assert entry["status"] == "LOGGED"
        bundle = get_success_data(api_client.get_bundle(ctx["bundle"]["id"], ANY))
        assert bundle["status"] == "IN_PROGRESS"

    def test_release_moves_order_cutting_to_sewing(self):
        """PRD §3.6: "Releasing moves the bundle to `RELEASED` and increments
        its `version`; when the order was still `CUTTING`, this first release
        also moves the order into `SEWING` and increments the order's
        `version`."

        Design: Corner/state_machines/bundle_auto_in_progress_on_first_piece_work_log
        """
        ctx = _cut_bundles_for_order(order_qty=4)
        order_mid = get_success_data(
            api_client.get_production_order(ctx["order"]["id"], ANY)
        )
        assert order_mid["production_status"] == "CUTTING"
        bundle = get_success_data(
            api_client.release_bundle(ctx["bundles"][0]["id"], SUPER)
        )
        assert bundle["status"] == "RELEASED"
        order_after = get_success_data(
            api_client.get_production_order(ctx["order"]["id"], ANY)
        )
        assert order_after["production_status"] == "SEWING"

    def test_bundle_auto_completed_when_all_operations_verified(self):
        """PRD §3.6: "when every operation of the pinned pack shows
        verified-or-paid quantities summing to the bundle's `qty`, the bundle
        automatically moves from `IN_PROGRESS` to `COMPLETED` —
        `completed_through_seq` settling at the pack's maximum `sequence_no`".

        Design: Corner/state_machines/bundle_auto_completed_when_all_operations_verified
        """
        ctx = setup_released_bundle_with_operator(order_qty=4)
        entry = log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=4,
        )
        bundle = get_success_data(api_client.get_bundle(ctx["bundle"]["id"], ANY))
        assert bundle["status"] == "IN_PROGRESS"
        assert bundle["completed_through_seq"] == 0
        entry = verify_entry(entry["id"], SUPER)
        assert entry["status"] == "VERIFIED"
        assert entry["reviewed_by_user_id"] is not None
        bundle = get_success_data(api_client.get_bundle(ctx["bundle"]["id"], ANY))
        assert bundle["status"] == "COMPLETED"
        assert bundle["completed_through_seq"] == 1


class TestBundleReleaseGate:
    def test_release_released_bundle_rejected(self):
        """PRD §3.6: "The bundle must be `TICKETED` (otherwise
        `ERR_BUNDLE_NOT_RELEASABLE`, HTTP 409)".

        Design: Corner/errors/release_released_bundle_rejected
        """
        ctx = setup_released_bundle_with_operator(order_qty=4)
        resp = api_client.release_bundle(ctx["bundle"]["id"], SUPER)
        validate_error(resp, ApiErrorId.ERR_BUNDLE_NOT_RELEASABLE)

    # NOTE on the release-side trim-hold gate: PRD §3.4 states the gate guards
    # bundle release, but a bundle can only exist after start-cutting, which
    # itself is blocked on TRIM_HOLD — so no PRD-declared flow produces a
    # TICKETED bundle on a held order. The release-side assertion is a gap and
    # is not tested here (the start-cutting half is covered in
    # test_04_production_orders_and_trim.py).


class TestPieceWorkGuards:
    def test_log_on_ticketed_bundle_rejected(self):
        """PRD §3.6: "the bundle must be `RELEASED` or `IN_PROGRESS`
        (otherwise `ERR_BUNDLE_NOT_LOGGABLE`, HTTP 409)".

        Design: Corner/errors/log_on_ticketed_bundle_rejected
        """
        ctx = _cut_bundles_for_order(order_qty=4)  # bundle left TICKETED
        operator = create_operator(SUPER)
        line = create_sewing_line(PLANNER)
        create_line_assignment(
            line["id"], ctx["order"]["id"], ctx["ops"][0]["id"], operator["id"],
            SUPER, assigned_pieces=4,
        )
        resp = api_client.create_piece_work_entry(
            {
                "bundle_id": ctx["bundles"][0]["id"],
                "operation_spec_id": ctx["ops"][0]["id"],
                "work_date": "2026-08-03",
                "qty": 1,
            },
            make_sewing_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUNDLE_NOT_LOGGABLE)

    def test_piece_work_without_line_assignment_rejected(self):
        """PRD §3.6: "a matching `LineAssignment` must exist for this operator,
        this operation, this order, and a `shift_date` equal to the entry's
        `work_date` (otherwise `ERR_NO_LINE_ASSIGNMENT`, HTTP 422)".

        Design: Corner/validations/piece_work_without_line_assignment_rejected
        """
        ctx = _cut_bundles_for_order(order_qty=4)
        get_success_data(api_client.release_bundle(ctx["bundles"][0]["id"], SUPER))
        operator = create_operator(SUPER)  # no assignment created
        resp = api_client.create_piece_work_entry(
            {
                "bundle_id": ctx["bundles"][0]["id"],
                "operation_spec_id": ctx["ops"][0]["id"],
                "work_date": "2026-08-03",
                "qty": 1,
            },
            make_sewing_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_LINE_ASSIGNMENT)

    def test_operation_sequence_gate_blocks_out_of_order_logging(self):
        """PRD §3.6: "an entry for the operation at route position N greater
        than 1 is loggable only once the operation at position N−1 is fully
        logged on the same bundle, meaning the quantities across its
        non-`REJECTED` entries sum to the bundle's `qty` (otherwise
        `ERR_OPERATION_SEQUENCE_VIOLATION`, HTTP 409)".

        Design: Corner/validations/operation_sequence_gate_blocks_out_of_order_logging
        """
        ops = [
            {"sequence_no": 1, "name": "join", "machine_type": "OVERLOCK",
             "sam_seconds": 54, "piece_rate_cents": 12},
            {"sequence_no": 2, "name": "topstitch", "machine_type": "SINGLE_NEEDLE",
             "sam_seconds": 66, "piece_rate_cents": 12},
        ]
        ctx = setup_planned_order_with_bundle(order_qty=3, ops=ops)
        bundle = get_success_data(
            api_client.release_bundle(ctx["bundles"][0]["id"], SUPER)
        )
        operator = create_operator(SUPER)
        line = create_sewing_line(PLANNER, station_count=3)
        create_line_assignment(
            line["id"], ctx["order"]["id"], ctx["ops"][0]["id"], operator["id"],
            SUPER, start_minute=480, end_minute=530, assigned_pieces=3,
        )
        create_line_assignment(
            line["id"], ctx["order"]["id"], ctx["ops"][1]["id"], operator["id"],
            SUPER, start_minute=545, end_minute=600, assigned_pieces=3,
        )
        # Logging seq 2 while seq 1 is not fully logged -> violation.
        resp = api_client.create_piece_work_entry(
            {
                "bundle_id": bundle["id"],
                "operation_spec_id": ctx["ops"][1]["id"],
                "work_date": "2026-08-03",
                "qty": 1,
            },
            make_sewing_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPERATION_SEQUENCE_VIOLATION)
        # Fully log seq 1, then seq 2 logs fine.
        log_piece_work(bundle["id"], ctx["ops"][0]["id"], operator["id"], qty=3)
        entry2 = log_piece_work(bundle["id"], ctx["ops"][1]["id"], operator["id"], qty=1)
        assert entry2["status"] == "LOGGED"

    def test_piece_work_qty_over_remaining_rejected(self):
        """PRD §3.6: "the logged `qty` must not exceed the bundle's `qty`
        minus the quantities already logged for this operation across
        non-`REJECTED` entries (otherwise `ERR_QTY_EXCEEDS_REMAINING`,
        HTTP 422)".

        Design: Corner/validations/piece_work_qty_over_remaining_rejected
        """
        ctx = setup_released_bundle_with_operator(order_qty=3)
        log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=2,
        )
        resp = api_client.create_piece_work_entry(
            {
                "bundle_id": ctx["bundle"]["id"],
                "operation_spec_id": ctx["ops"][0]["id"],
                "work_date": "2026-08-03",
                "qty": 2,
            },
            make_sewing_operator_headers(ctx["operator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QTY_EXCEEDS_REMAINING)

    def test_operation_from_other_pack_rejected(self):
        """PRD §3.6: "the operation must belong to the tech pack pinned on the
        bundle's order (otherwise `ERR_OPERATION_NOT_IN_TECH_PACK`, HTTP 422)".

        Design: Corner/validations/operation_from_other_pack_rejected
        """
        ctx = setup_released_bundle_with_operator(order_qty=4)
        # A second, unrelated pack carries the foreign operation.
        pack_b = create_draft_tech_pack(ctx["style"]["id"], MERCH, version_no=2)
        op_b = add_operation_spec(pack_b["id"], MERCH, name="other-op")
        resp = api_client.create_piece_work_entry(
            {
                "bundle_id": ctx["bundle"]["id"],
                "operation_spec_id": op_b["id"],
                "work_date": "2026-08-03",
                "qty": 1,
            },
            make_sewing_operator_headers(ctx["operator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPERATION_NOT_IN_TECH_PACK)


class TestSewingOperatorIdentity:
    def test_sewing_operator_identity_is_entity_backed(self):
        """PRD §3.6: "The entry's `operator_id` is always taken from the
        caller's `X-User-ID` under the entity-backed identity of §2.1 — a
        body-supplied operator id is ignored."

        Design: Corner/rbac/sewing_operator_identity_is_entity_backed
        """
        ctx = setup_released_bundle_with_operator(order_qty=4)
        entry = log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=1,
        )
        assert entry["operator_id"] == ctx["operator"]["id"]
        assert entry["status"] == "LOGGED"

    def test_body_supplied_operator_id_ignored(self):
        """PRD §3.6: "a body-supplied operator id is ignored".

        Design: Corner/rbac/sewing_operator_identity_is_entity_backed
        """
        ctx = setup_released_bundle_with_operator(order_qty=4)
        other = create_operator(SUPER, employee_no="E-99", full_name="Other")
        resp = api_client.create_piece_work_entry(
            {
                "bundle_id": ctx["bundle"]["id"],
                "operation_spec_id": ctx["ops"][0]["id"],
                "work_date": "2026-08-03",
                "qty": 1,
                "operator_id": other["id"],
            },
            make_sewing_operator_headers(ctx["operator"]["id"]),
        )
        entry = validate_success(resp, 201)
        assert entry["operator_id"] == ctx["operator"]["id"]
