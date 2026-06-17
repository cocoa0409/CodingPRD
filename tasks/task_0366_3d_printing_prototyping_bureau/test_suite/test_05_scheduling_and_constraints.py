"""Scheduling boundaries, temporal overlap, capacity/stock gates, and
cross-entity state dependencies.

Covers:
  Difficulty/boundary_precision_check/machine_capacity_exact_boundary
  Difficulty/boundary_precision_check/quote_empty_order_zero_active_lines
  Difficulty/resource_temporal_overlap/machine_slot_half_open_back_to_back
  Difficulty/resource_temporal_overlap/station_closed_interval_cooldown_buffer
  Difficulty/cross_entity_state_dependency/run_start_requires_order_escrowed
  Difficulty/cross_entity_state_dependency/line_create_requires_material_active
  Corner/validations/spool_insufficient_grams_returns_error
  Corner/validations/run_create_process_mismatch_returns_error
  Corner/validations/run_start_machine_busy_returns_error
  Corner/validations/run_start_machine_offline_returns_error
  Corner/validations/confirm_insufficient_wallet_returns_402
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client,
    setup_catalogue, setup_confirmed_order, setup_order_with_line, create_run,
    refresh_machine, upload_and_check_file, upload_file, quote_order,
    create_order_payload, create_order_line_payload, create_machine_payload,
    create_finishing_task_payload, FILE_A, FILE_B, TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
QA = TEST_USERS["qa_reviewer_headers"]
ADMIN = TEST_USERS["bureau_admin_headers"]


# ─── boundary_precision_check ─────────────────────────

def test_machine_capacity_exact_boundary_allowed_then_excess_rejected(api):
    """PRD §3.6: "Capacity is bounded: the machine's existing `scheduled_minutes`
    plus this run's `duration_min` must not exceed the bureau's
    `shift_capacity_minutes` — equality is allowed, only a strict excess is
    rejected, with `ERR_MACHINE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/machine_capacity_exact_boundary
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000, shift_capacity_minutes=480)
    create_run(env, start_min=0, duration_min=460)  # scheduled_minutes -> 460
    # 460 + 20 == 480 boundary: allowed.
    res_ok = api.create_print_run(
        {"order_line_id": env["line"]["id"], "machine_id": env["machine"]["id"],
         "spool_id": env["spool"]["id"], "start_min": 460, "duration_min": 20}, OPERATOR)
    created = validate_success(res_ok, 201)
    assert created["status"] == "QUEUED"
    m = refresh_machine(env)
    assert m["utilization_pct"] == 100, m["utilization_pct"]  # 480/480

    # 460 + 21 == 481 > 480: rejected.
    res_bad = api.create_print_run(
        {"order_line_id": env["line"]["id"], "machine_id": env["machine"]["id"],
         "spool_id": env["spool"]["id"], "start_min": 480, "duration_min": 21}, OPERATOR)
    validate_error(res_bad, "ERR_MACHINE_CAPACITY_EXCEEDED")


def test_machine_capacity_well_below_boundary_accepted(api):
    """PRD §3.6: "Capacity is bounded: the machine's existing `scheduled_minutes`
    plus this run's `duration_min` must not exceed the bureau's
    `shift_capacity_minutes` — equality is allowed, only a strict excess is
    rejected, with `ERR_MACHINE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/machine_capacity_exact_boundary
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000, shift_capacity_minutes=480)
    create_run(env, start_min=0, duration_min=460)  # scheduled 460
    # 460 + 19 == 479 < 480: well below the cap, accepted.
    res = api.create_print_run(
        {"order_line_id": env["line"]["id"], "machine_id": env["machine"]["id"],
         "spool_id": env["spool"]["id"], "start_min": 460, "duration_min": 19}, OPERATOR)
    created = validate_success(res, 201)
    assert created["status"] == "QUEUED"


def test_quote_empty_order_zero_active_lines_rejected(api):
    """PRD §3.5: "the order must have at least one `ACTIVE` line, otherwise it is
    rejected with `ERR_ORDER_EMPTY`".

    Design: Difficulty/boundary_precision_check/quote_empty_order_zero_active_lines
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    res = api.quote_order(order["id"], env["cust_headers"])
    validate_error(res, "ERR_ORDER_EMPTY")


def test_quote_one_active_line_succeeds_just_above_empty_boundary(api):
    """PRD §3.5: "Once a draft order has at least one active line whose file is
    printable, the customer requests a quote. Quoting recomputes all totals (the
    same aggregation as §3.3) and advances `fulfillment_status` from `DRAFT` to
    `QUOTED`."

    Design: Difficulty/boundary_precision_check/quote_empty_order_zero_active_lines
    """
    # Exactly one ACTIVE printable line: count==1 is the just-above-empty boundary.
    env = setup_order_with_line(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                check_file=True)
    res = api.quote_order(env["order"]["id"], env["cust_headers"])
    quoted = validate_success(res, 200)
    assert quoted["fulfillment_status"] == "QUOTED"


# ─── resource_temporal_overlap ────────────────────────

def test_machine_slot_half_open_back_to_back_allowed_overlap_rejected(api):
    """PRD §3.6: "The requested slot must not overlap any existing `QUEUED` or
    `PRINTING` run on the same machine: the interval is half-open, running from
    `start_min` up to but not including `start_min` plus `duration_min`, so two runs
    may sit exactly back-to-back, but any genuine overlap is rejected with
    `ERR_MACHINE_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/machine_slot_half_open_back_to_back
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000)
    create_run(env, start_min=100, duration_min=140)  # occupies [100,240)
    # [240,300): back-to-back, 240 not < 240, accepted.
    res_ok = api.create_print_run(
        {"order_line_id": env["line"]["id"], "machine_id": env["machine"]["id"],
         "spool_id": env["spool"]["id"], "start_min": 240, "duration_min": 60}, OPERATOR)
    created = validate_success(res_ok, 201)
    assert created["status"] == "QUEUED"
    # [239,260): overlaps by 1 minute, rejected.
    res_bad = api.create_print_run(
        {"order_line_id": env["line"]["id"], "machine_id": env["machine"]["id"],
         "spool_id": env["spool"]["id"], "start_min": 239, "duration_min": 21}, OPERATOR)
    validate_error(res_bad, "ERR_MACHINE_SLOT_CONFLICT")


def test_machine_slot_exact_overlap_start_rejected(api):
    """PRD §3.6: "The requested slot must not overlap any existing `QUEUED` or
    `PRINTING` run on the same machine: the interval is half-open, running from
    `start_min` up to but not including `start_min` plus `duration_min`, so two runs
    may sit exactly back-to-back, but any genuine overlap is rejected with
    `ERR_MACHINE_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/machine_slot_half_open_back_to_back
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000)
    create_run(env, start_min=100, duration_min=140)  # occupies [100,240)
    # [100,160): same start, a genuine overlap inside [100,240) -> rejected.
    res = api.create_print_run(
        {"order_line_id": env["line"]["id"], "machine_id": env["machine"]["id"],
         "spool_id": env["spool"]["id"], "start_min": 100, "duration_min": 60}, OPERATOR)
    validate_error(res, "ERR_MACHINE_SLOT_CONFLICT")


def test_station_closed_interval_cooldown_buffer_gap_strictly_greater(api):
    """PRD §3.4: "a new task occupying its station from `station_start_min` through
    `station_start_min` plus `station_duration_min` must leave a gap strictly
    greater than the bureau's `cooldown_buffer_min` from any already-`SCHEDULED`
    task of the same `kind`. If the gap is not strictly greater than the buffer,
    the schedule attempt is rejected with `ERR_STATION_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/station_closed_interval_cooldown_buffer
    """
    # Bureau cooldown_buffer_min defaults to 15 (PRD §3.1).
    env = setup_order_with_line(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                check_file=True)
    base = api_client.create_finishing_task(
        create_finishing_task_payload(env["line"]["id"], kind="UV_CURE", addon_cents=300,
                                      station_start_min=400, station_duration_min=60),
        OPERATOR)
    base_task = validate_success(base, 201)
    get_success_data(api_client.schedule_finishing_task(base_task["id"], OPERATOR))  # [400,460]

    close = validate_success(api_client.create_finishing_task(
        create_finishing_task_payload(env["line"]["id"], kind="UV_CURE", addon_cents=300,
                                      station_start_min=475, station_duration_min=25),
        OPERATOR), 201)
    far = validate_success(api_client.create_finishing_task(
        create_finishing_task_payload(env["line"]["id"], kind="UV_CURE", addon_cents=300,
                                      station_start_min=476, station_duration_min=24),
        OPERATOR), 201)
    # [475,500]: gap 15 from [400,460], not > 15 -> rejected.
    res_close = api.schedule_finishing_task(close["id"], OPERATOR)
    validate_error(res_close, "ERR_STATION_SLOT_CONFLICT")
    # [476,500]: gap 16 > 15 -> accepted.
    res_far = api.schedule_finishing_task(far["id"], OPERATOR)
    scheduled = validate_success(res_far, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_station_first_scheduled_task_succeeds_no_prior_conflict(api):
    """PRD §3.4: "An `Operator` schedules a pending task onto its station, moving
    it from `PENDING` to `SCHEDULED`."

    The first task on an empty station has no already-`SCHEDULED` peer to clear the
    cooldown buffer against, so scheduling succeeds.

    Design: Difficulty/resource_temporal_overlap/station_closed_interval_cooldown_buffer
    """
    env = setup_order_with_line(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                check_file=True)
    first = validate_success(api_client.create_finishing_task(
        create_finishing_task_payload(env["line"]["id"], kind="UV_CURE", addon_cents=300,
                                      station_start_min=400, station_duration_min=60),
        OPERATOR), 201)
    res = api.schedule_finishing_task(first["id"], OPERATOR)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


# ─── cross_entity_state_dependency ────────────────────

def test_run_start_succeeds_when_owning_order_escrowed(api):
    """PRD §3.6: "An `Operator` starts a queued run, advancing it from `QUEUED` to
    `PRINTING`. Starting requires the machine to be `ONLINE` (else
    `ERR_MACHINE_OFFLINE`), requires that no other run on the same machine is
    already `PRINTING` (else `ERR_MACHINE_BUSY`), and requires the owning order's
    `payment_status` to be `ESCROWED` (else `ERR_ORDER_NOT_ESCROWED`)."

    Design: Difficulty/cross_entity_state_dependency/run_start_requires_order_escrowed
    """
    # Confirmed order (payment ESCROWED) -> start succeeds, the satisfied branch.
    env = setup_confirmed_order(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                spool_grams=1000)
    run = create_run(env, start_min=0, duration_min=24)
    res = api.start_print_run(run["id"], OPERATOR)
    started = validate_success(res, 200)
    assert started["status"] == "PRINTING"


def test_run_start_requires_owning_order_escrowed(api):
    """PRD §3.6: "Starting requires the machine to be `ONLINE` (else
    `ERR_MACHINE_OFFLINE`), requires that no other run on the same machine is
    already `PRINTING` (else `ERR_MACHINE_BUSY`), and requires the owning order's
    `payment_status` to be `ESCROWED` (else `ERR_ORDER_NOT_ESCROWED`)."

    Design: Difficulty/cross_entity_state_dependency/run_start_requires_order_escrowed
    """
    # Quoted (UNPAID) order — not confirmed — with a QUEUED run for its line.
    env = setup_order_with_line(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                check_file=True, spool_grams=1000)
    quote_order(env)  # QUOTED, payment UNPAID
    run = create_run(env, start_min=0, duration_min=24)
    res = api.start_print_run(run["id"], OPERATOR)
    validate_error(res, "ERR_ORDER_NOT_ESCROWED")


def test_order_line_create_requires_material_active(api):
    """PRD §3.3: "Creating a line against a retired material is rejected with
    `ERR_MATERIAL_RETIRED`."

    Design: Difficulty/cross_entity_state_dependency/line_create_requires_material_active
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=FILE_B)
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    get_success_data(api.retire_material(env["material"]["id"], ADMIN))
    res = api.create_order_line(
        create_order_line_payload(order["id"], f["id"], env["material"]["id"],
                                  layer_height_mm=0.10, quantity=1),
        env["cust_headers"])
    validate_error(res, "ERR_MATERIAL_RETIRED")


def test_order_line_create_succeeds_with_active_material(api):
    """PRD §3.3: "A material is born `ACTIVE` and can later be retired".
    PRD §3.3: "Creating a line against a retired material is rejected with
    `ERR_MATERIAL_RETIRED`."

    The satisfied branch: a line backed by an ACTIVE (never-retired) material is
    created normally.

    Design: Difficulty/cross_entity_state_dependency/line_create_requires_material_active
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    assert env["material"]["status"] == "ACTIVE"
    f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=FILE_B)
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    res = api.create_order_line(
        create_order_line_payload(order["id"], f["id"], env["material"]["id"],
                                  layer_height_mm=0.10, quantity=1),
        env["cust_headers"])
    line = validate_success(res, 201)
    assert line["status"] == "ACTIVE"


# ─── validation corner instances ──────────────────────

def test_run_create_spool_insufficient_rejected(api):
    """PRD §3.6: "the computed `run_grams` must not exceed the spool's
    `grams_remaining`, otherwise the create is rejected with
    `ERR_SPOOL_INSUFFICIENT`."

    Design: Corner/validations/spool_insufficient_grams_returns_error
    """
    # Line A run_grams 28; spool only 10.
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=10)
    res = api.create_print_run(
        {"order_line_id": env["line"]["id"], "machine_id": env["machine"]["id"],
         "spool_id": env["spool"]["id"], "start_min": 0, "duration_min": 140}, OPERATOR)
    validate_error(res, "ERR_SPOOL_INSUFFICIENT")


def test_run_create_process_mismatch_rejected(api):
    """PRD §3.6: "the chosen machine's `process` must equal the line material's
    `process` (else `ERR_PROCESS_MISMATCH`)".

    Design: Corner/validations/run_create_process_mismatch_returns_error
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000)
    # The line material is SLA; create an FDM machine and run against it.
    fdm = get_success_data(api.create_machine(
        create_machine_payload(env["bureau"]["id"], process="FDM", label="FDM-A",
                               build_x_mm=200, build_y_mm=200, build_z_mm=200), ADMIN))
    res = api.create_print_run(
        {"order_line_id": env["line"]["id"], "machine_id": fdm["id"],
         "spool_id": env["spool"]["id"], "start_min": 0, "duration_min": 140}, OPERATOR)
    validate_error(res, "ERR_PROCESS_MISMATCH")


def test_run_start_machine_busy_rejected(api):
    """PRD §3.6: "requires that no other run on the same machine is already
    `PRINTING` (else `ERR_MACHINE_BUSY`)".

    Design: Corner/validations/run_start_machine_busy_returns_error
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000)
    run1 = create_run(env, start_min=0, duration_min=100)
    run2 = create_run(env, start_min=100, duration_min=100)
    get_success_data(api.start_print_run(run1["id"], OPERATOR))  # PRINTING
    res = api.start_print_run(run2["id"], OPERATOR)
    validate_error(res, "ERR_MACHINE_BUSY")


def test_run_start_machine_offline_rejected(api):
    """PRD §3.6: "Starting requires the machine to be `ONLINE` (else
    `ERR_MACHINE_OFFLINE`)".
    PRD §2.7: "a machine in `MAINTENANCE` blocks queueing and starting of runs."

    Design: Corner/validations/run_start_machine_offline_returns_error
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000)
    run = create_run(env, start_min=0, duration_min=140)
    get_success_data(api.set_maintenance(env["machine"]["id"], {"status": "MAINTENANCE"}, OPERATOR))
    res = api.start_print_run(run["id"], OPERATOR)
    validate_error(res, "ERR_MACHINE_OFFLINE")


def test_confirm_insufficient_wallet_rejected_402(api):
    """PRD §3.5: "the customer's `wallet_balance_cents` must be greater than or
    equal to the order's `grand_total_cents`, otherwise the confirm is rejected with
    `ERR_INSUFFICIENT_WALLET` (HTTP 402)".

    Design: Corner/validations/confirm_insufficient_wallet_returns_402
    """
    # grand 2928, wallet only 1000.
    env = setup_order_with_line(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                check_file=True, deposit=1000)
    quoted = quote_order(env)
    res = api.confirm_order(quoted["id"], {"expected_order_version": quoted["version"]},
                            env["cust_headers"])
    validate_error(res, "ERR_INSUFFICIENT_WALLET")
