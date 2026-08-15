"""Lot state gates: presize, diversion terminal lockdown, the RELEASED gate on
run creation, and temporal rejections (storage life, seal open date)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_spec,
    create_allocation_payload,
    create_grower_with_block,
    create_open_pool,
    create_packing_run_payload,
    create_room,
    get_success_data,
    open_room,
    presize_lot,
    presize_payload,
    receive_lot,
    record_o2_reading,
    release_allocation,
    seal_payload,
    set_logical_clock,
    setup_packable_lot,
    setup_sealed_storage,
    setup_stored_lot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
STORAGE = TEST_USERS["storage_operator_headers"]
SUPERVISOR = TEST_USERS["packing_supervisor_headers"]


class TestPresizeGate:
    def test_presize_from_in_storage_rejected(self, api):
        """PRD §3.1: "Presizing a lot that is not `RECEIVED` is rejected with
        `ERR_LOT_INVALID_STATE`."

        Design: Corner/state_machines/c_presize_from_in_storage_rejected
        """
        ctx = setup_stored_lot()
        lot = get_success_data(api.get_lot(ctx["lot"]["id"], ADMIN))
        assert lot["status"] == "IN_STORAGE"
        # The profile sums exactly to the received weight, so only the state
        # gate can fail.
        resp = api.presize_lot(ctx["lot"]["id"], presize_payload(), CLERK)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE)


class TestDiversionLockdown:
    def test_diverted_lot_terminal_lockdown(self, api):
        """PRD §3.3: "Diversion sets the lot's `diverted_weight_lbs` to its entire
        current `weight_balance_lbs`, taking the balance to zero, and moves the
        lot to the terminal `DIVERTED` state."
        PRD §3.1: "Presizing a lot that is not `RECEIVED` is rejected with
        `ERR_LOT_INVALID_STATE`."
        PRD §3.2: "The lot must be `RECEIVED` or `PRESIZED` (else
        `ERR_LOT_INVALID_STATE`)"

        Design: Corner/state_machines/c_diverted_lot_terminal_lockdown
        """
        grower, block = create_grower_with_block()
        lot = receive_lot(grower["id"], block["id"], 5, 4000, 80)
        room = create_room()

        diverted = validate_success(api.divert_lot(lot["id"], STORAGE))
        assert diverted["status"] == "DIVERTED"
        assert diverted["diverted_weight_lbs"] == 4000, "full balance diverted"
        assert diverted["weight_balance_lbs"] == 0

        resp1 = api.presize_lot(lot["id"], presize_payload(), CLERK)
        validate_error(resp1, ApiErrorId.ERR_LOT_INVALID_STATE)

        resp2 = api.create_allocation(
            room["id"], create_allocation_payload(lot["id"], 5), STORAGE)
        validate_error(resp2, ApiErrorId.ERR_LOT_INVALID_STATE)


class TestRunCreationLotGate:
    def test_run_create_rejected_while_lot_in_storage(self, api):
        """PRD §3.4: "the lot must be `RELEASED` (else `ERR_LOT_INVALID_STATE`)"
        PRD §3.3: "meanwhile, if this is the lot's first release, the lot
        transitions `IN_STORAGE → RELEASED`."

        Design: Difficulty/cross_entity_state_dependency/run_create_requires_released_lot
        """
        ctx = setup_sealed_storage()
        ctx["spec"] = create_active_spec()
        ctx["pool"] = create_open_pool()

        # Lot is IN_STORAGE behind a SEALED room: the lot gate fires.
        resp = api.create_packing_run(
            create_packing_run_payload(ctx["lot"]["id"], ctx["spec"]["id"],
                                       ctx["pool"]["id"], input_weight_lbs=2000),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE)

        # After the room opens and the allocation releases, the identical
        # request succeeds — the gate is the lot's state, not the run's fields.
        open_room(ctx["room"]["id"])
        release_allocation(ctx["allocation"]["id"])
        lot = get_success_data(api.get_lot(ctx["lot"]["id"], ADMIN))
        assert lot["status"] == "RELEASED"

        run = validate_success(api.create_packing_run(
            create_packing_run_payload(ctx["lot"]["id"], ctx["spec"]["id"],
                                       ctx["pool"]["id"], input_weight_lbs=2000),
            SUPERVISOR), 201)
        assert run["status"] == "SCHEDULED"

    def test_run_create_rejected_for_received_and_presized_lot(self, api):
        """PRD §3.4: "the lot must be `RELEASED` (else `ERR_LOT_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/run_create_requires_released_lot
        """
        grower, block = create_grower_with_block()
        lot = receive_lot(grower["id"], block["id"], 5, 4000, 80)
        spec = create_active_spec()
        pool = create_open_pool()

        # RECEIVED: never stored.
        resp = api.create_packing_run(
            create_packing_run_payload(lot["id"], spec["id"], pool["id"],
                                       input_weight_lbs=2000),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE)

        # PRESIZED: grading does not make the lot packable either.
        presize_lot(lot["id"], 500, 2000, 1000, 500)
        resp2 = api.create_packing_run(
            create_packing_run_payload(lot["id"], spec["id"], pool["id"],
                                       input_weight_lbs=2000),
            SUPERVISOR)
        validate_error(resp2, ApiErrorId.ERR_LOT_INVALID_STATE)


class TestTemporalGates:
    def test_storage_life_exceeded_rejected(self, api):
        """PRD §3.4: "the run may not be scheduled once the fruit is too old —
        when the current logical clock has passed the lot's `received_at` plus the
        block's `storage_life_days`, creation is rejected with
        `ERR_LOT_STORAGE_LIFE_EXCEEDED`."

        Design: Corner/validations/c_storage_life_exceeded_rejected
        """
        ctx = setup_packable_lot(storage_life_days=30,
                                 planned_open_date="2026-09-01T00:00:00Z")
        # Received at the 2026-08-01 default with a 30-day life: the deadline is
        # 2026-08-31; advancing the clock past it blocks new runs.
        set_logical_clock("2026-09-15T00:00:00Z")
        resp = api.create_packing_run(
            create_packing_run_payload(
                ctx["lot"]["id"], ctx["spec"]["id"], ctx["pool"]["id"],
                scheduled_start="2026-09-16T08:00:00Z",
                scheduled_end="2026-09-16T12:00:00Z", input_weight_lbs=500),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_LOT_STORAGE_LIFE_EXCEEDED)

    def test_open_date_past_rejected(self, api):
        """PRD §3.2: "the temporal gate requires the supplied `planned_open_date`
        to lie strictly after the current logical clock, else
        `ERR_OPEN_DATE_NOT_FUTURE`."

        Design: Corner/validations/c_open_date_past_rejected
        """
        ctx = setup_stored_lot()
        # Oxygen sits exactly at the setpoint, so only the temporal gate can fail.
        record_o2_reading(ctx["room"]["id"], ctx["room"]["o2_setpoint_pct"])
        resp = api.seal_ca_room(
            ctx["room"]["id"],
            seal_payload(planned_open_date="2026-07-01T00:00:00Z"), STORAGE)
        validate_error(resp, ApiErrorId.ERR_OPEN_DATE_NOT_FUTURE)
