"""Mill scheduling: washdown-buffer window conflicts, capacity limits,
maintenance guards, and the reserve/release minutes identity."""

import test_helpers as fx
from test_helpers import ApiErrorId, PLANT_MANAGER, validate_error, validate_success


def test_same_family_adjacency_needs_no_buffer(api):
    """PRD §2.10: "Between two reservations on the same mill, the required
    turnaround gap depends on product family: when the existing and new
    batches share the same `base_family` they share a washdown and need no
    gap, while batches of different families require a thirty-minute washdown
    buffer between them."

    Design: Difficulty/resource_temporal_overlap/mill_washdown_buffer_conflict
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()

    b_a = fx.plan_batch(f1["id"], m1["id"], planned_gallons=10,
                        window=("2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z"))
    # Same base_family, touching back-to-back at 12:00 — no gap required.
    b_b = fx.plan_batch(f1["id"], m1["id"], planned_gallons=10,
                        window=("2026-06-10T12:00:00Z", "2026-06-10T14:00:00Z"))
    assert b_a["status"] == "PLANNED"
    assert b_b["status"] == "PLANNED"
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 240 + 120


def test_cross_family_washdown_buffer_boundary(api):
    """PRD §2.10: "A new window conflicts with an existing one — and is
    rejected with `ERR_MILL_WINDOW_CONFLICT` — unless it begins at or after
    the existing window's end plus the required gap, or the existing window
    begins at or after the new window's end plus the required gap. The
    boundary itself is permitted: a new window beginning exactly when the
    earlier window plus its gap ends is acceptable, and same-family windows
    may touch back-to-back with zero gap."
    PRD §2.10: "A mill's `reserved_minutes` is the sum of window minutes over
    all of its batches in `PLANNED`, `ON_HOLD`, `MILLING`, `TINTING`,
    `QC_PENDING`, `REWORK`, `QC_APPROVED`, or `FILLING` status."

    Design: Difficulty/resource_temporal_overlap/mill_washdown_buffer_conflict
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1 = fx.create_tb1()
    tb2 = fx.create_tb2()
    c1 = fx.create_c1()
    c2 = fx.create_c2()
    f1 = fx.create_f1(tb1["id"], c1["id"])
    fx.activate_formula(f1["id"])
    f2 = fx.create_f2(tb2["id"], c2["id"])
    fx.activate_formula(f2["id"])
    m1 = fx.create_mill()

    # LATEX_EXTERIOR reservation 08:00–12:00.
    fx.plan_batch(f1["id"], m1["id"], planned_gallons=10,
                  window=("2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z"))
    # Same-family neighbour 12:00–14:00 (zero gap allowed).
    fx.plan_batch(f1["id"], m1["id"], planned_gallons=10,
                  window=("2026-06-10T12:00:00Z", "2026-06-10T14:00:00Z"))

    # Cross-family start at 14:29 leaves only 29 of the 30 required minutes.
    too_close = api.create_batch(
        fx.create_batch_payload(
            f2["id"], m1["id"], planned_gallons=50,
            mill_window_start="2026-06-10T14:29:00Z",
            mill_window_end="2026-06-10T16:00:00Z",
        ),
        fx.PRODUCTION_OPERATOR,
    )
    validate_error(too_close, ApiErrorId.ERR_MILL_WINDOW_CONFLICT.value, 409)

    # Exactly end + 30 minutes passes (boundary inclusive).
    b_d = fx.plan_batch(f2["id"], m1["id"], planned_gallons=50,
                        window=("2026-06-10T14:30:00Z", "2026-06-10T16:00:00Z"))
    assert b_d["status"] == "PLANNED"

    # The rejected reservation consumed nothing: 240 + 120 + 90 = 450.
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 450


def test_mill_capacity_exact_boundary(api):
    """PRD §3.4: "The formula must be `ACTIVE` (`ERR_FORMULA_NOT_ACTIVE`),
    the planned size must not exceed the mill's capacity
    (`ERR_MILL_CAPACITY_EXCEEDED`), it must meet the formula's
    `min_batch_gallons` — 50 gallons for a custom formula, 1 otherwise
    (`ERR_CUSTOM_MINIMUM_NOT_MET`) — and the window must satisfy the conflict
    rules of §2.10 (`ERR_MILL_WINDOW_CONFLICT`)."

    Design: Corner/validations/mill_capacity_exact_boundary
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()

    # planned_gallons exactly at capacity passes ("must not exceed").
    b_ok = fx.plan_batch(f1["id"], m1["id"], planned_gallons=200)
    assert b_ok["status"] == "PLANNED"

    over = api.create_batch(
        fx.create_batch_payload(
            f1["id"], m1["id"], planned_gallons=201,
            mill_window_start="2026-06-11T08:00:00Z",
            mill_window_end="2026-06-11T12:00:00Z",
        ),
        fx.PRODUCTION_OPERATOR,
    )
    validate_error(over, ApiErrorId.ERR_MILL_CAPACITY_EXCEEDED.value, 422)


def test_mill_maintenance_blocks_start_mill(api):
    """PRD §3.5: "Starting the mill advances a `PLANNED` batch to `MILLING`,
    but only when three conditions hold together: the batch's formula is
    `ACTIVE` — a formula deprecated since planning blocks the start with
    `ERR_FORMULA_NOT_ACTIVE`; the mill is `ACTIVE`, not in maintenance —
    else `ERR_MILL_NOT_AVAILABLE`; and, for an order-serving batch, the order
    is `SCHEDULED` — any other order state is `ERR_INVALID_STATE`."
    PRD §3.4: "Taking a mill down is deliberately guarded: entering
    maintenance is rejected with `ERR_MILL_BUSY` while any batch on that mill
    sits in `MILLING`, `TINTING`, `QC_PENDING`, `REWORK`, `QC_APPROVED`, or
    `FILLING`, because those batches are physically in flight."

    Design: Corner/state_machines/mill_maintenance_blocks_start_mill
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)

    # A merely PLANNED batch is not in flight, so maintenance is allowed.
    mill = validate_success(api.enter_mill_maintenance(m1["id"], PLANT_MANAGER))
    assert mill["status"] == "MAINTENANCE"

    blocked = api.start_mill(b1["id"], fx.PRODUCTION_OPERATOR)
    validate_error(blocked, ApiErrorId.ERR_MILL_NOT_AVAILABLE.value, 409)
    assert fx.read_batch(b1["id"])["status"] == "PLANNED"

    validate_success(api.return_mill_to_service(m1["id"], PLANT_MANAGER))
    started = validate_success(api.start_mill(b1["id"], fx.PRODUCTION_OPERATOR))
    assert started["status"] == "MILLING"


def test_mill_busy_blocks_maintenance(api):
    """PRD §3.4: "Taking a mill down is deliberately guarded: entering
    maintenance is rejected with `ERR_MILL_BUSY` while any batch on that mill
    sits in `MILLING`, `TINTING`, `QC_PENDING`, `REWORK`, `QC_APPROVED`, or
    `FILLING`, because those batches are physically in flight."
    PRD §3.7: "The dispose action moves a batch from `MILLING`, `TINTING`,
    `QC_PENDING`, `REWORK`, or `QC_APPROVED` into `DISPOSAL_PENDING`."

    Design: Corner/state_machines/mill_busy_blocks_maintenance
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.start_batch(b1["id"])
    assert fx.read_batch(b1["id"])["status"] == "MILLING"

    busy = api.enter_mill_maintenance(m1["id"], PLANT_MANAGER)
    validate_error(busy, ApiErrorId.ERR_MILL_BUSY.value, 409)
    assert fx.read_mill(m1["id"])["status"] == "ACTIVE"

    # Condemning the batch takes it out of the in-flight set.
    disposed = validate_success(api.dispose_batch(b1["id"], fx.PRODUCTION_OPERATOR))
    assert disposed["status"] == "DISPOSAL_PENDING"
    mill = validate_success(api.enter_mill_maintenance(m1["id"], PLANT_MANAGER))
    assert mill["status"] == "MAINTENANCE"


def test_mill_reserve_release_minutes_identity(api):
    """PRD §2.10: "Reservations are placed when a batch is planned; neither
    starting the mill nor resuming a held batch moves a window, and the daily
    sweep never moves windows. The reservation is released — its minutes
    subtracted from `reserved_minutes` — when the batch is cancelled or
    reaches `DISPOSED`."
    PRD §3.4: "Alternatively, a batch in `PLANNED` or `ON_HOLD` can be
    cancelled outright, landing in the terminal `CANCELLED` state and
    releasing its mill reservation."

    Design: Difficulty/compensating_invariant/mill_reserve_release_minutes_identity
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 0

    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3,
                       window=("2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z"))
    b2 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3,
                       window=("2026-06-11T08:00:00Z", "2026-06-11T10:00:00Z"))
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 360

    cancelled1 = validate_success(api.cancel_batch(b1["id"], fx.PRODUCTION_OPERATOR))
    assert cancelled1["status"] == "CANCELLED"
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 120, (
        "release subtracts exactly the cancelled window"
    )

    cancelled2 = validate_success(api.cancel_batch(b2["id"], fx.PRODUCTION_OPERATOR))
    assert cancelled2["status"] == "CANCELLED"
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 0, (
        "reserve/release composes to the identity on machine-time"
    )


def test_mill_reservation_released_only_at_terminal(api):
    """PRD §2.10: "Reservations are placed when a batch is planned; neither
    starting the mill nor resuming a held batch moves a window, and the daily
    sweep never moves windows. The reservation is released — its minutes
    subtracted from `reserved_minutes` — when the batch is cancelled or
    reaches `DISPOSED`."
    PRD §3.7: "A condemned batch waits in `DISPOSAL_PENDING` until a disposal
    request referencing it completes (§3.9), at which point the batch becomes
    `DISPOSED` — terminal — and its mill reservation is finally released."

    Design: Difficulty/compensating_invariant/mill_reserve_release_minutes_identity
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3,
                       window=("2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z"))
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 240

    # Starting the mill does not move the reservation.
    fx.start_batch(b1["id"])
    assert fx.read_batch(b1["id"])["status"] == "MILLING"
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 240

    # DISPOSAL_PENDING still holds the reservation; only DISPOSED releases.
    validate_success(api.dispose_batch(b1["id"], fx.PRODUCTION_OPERATOR))
    assert fx.read_batch(b1["id"])["status"] == "DISPOSAL_PENDING"
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 240

    dr1 = fx.create_disposal_request(reason="BATCH_REJECT", container_ids=[],
                                     batch_ids=[b1["id"]])
    validate_success(
        api.complete_disposal_request(dr1["id"], {"actual_destroyed_kg": 0},
                                      PLANT_MANAGER)
    )
    assert fx.read_batch(b1["id"])["status"] == "DISPOSED"
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 0
