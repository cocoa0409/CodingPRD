"""Shipments, FEFO inventory allocation, dispensing, and reconciliation
(PRD §2.6, §2.9, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_dispense_event,
    assert_lot_units_conserved,
    create_lot_payload,
    create_reconciliation_payload,
    create_shipment_payload,
    fixtures as fx,
    make_patient_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_shipment_against_suspended_enrollment_rejected():
    """PRD §3.7: "Shipments against a `SUSPENDED` enrollment are rejected with
    `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/shipment_requires_active_enrollment
    """
    ctx = fx.setup_approved_enrollment()
    lot = fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-S1")
    fx.setup_suspended_enrollment(ctx)
    assert ctx["enrollment"]["status"] == "SUSPENDED"

    resp = api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=5,
                                idempotency_key="ship-susp"),
        fx.CW)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, expected_status=409)


def test_suspended_enrollment_blocks_reservation_side_effects():
    """PRD §3.7: "Shipments against a `SUSPENDED` enrollment are rejected with
    `ERR_ENROLLMENT_NOT_ACTIVE`." — a rejected creation reserves nothing.

    Design: Difficulty/cross_entity_state_dependency/shipment_requires_active_enrollment
    """
    ctx = fx.setup_approved_enrollment()
    lot = fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-S1")
    fx.setup_suspended_enrollment(ctx)

    api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=5,
                                idempotency_key="ship-susp"),
        fx.CW)
    shipments, meta = validate_paginated(api_client.list_shipments(
        fx.CW, params={"enrollment_id": ctx["enrollment"]["id"]}))
    assert shipments == [] and meta["total_count"] == 0, "no Shipment is created"
    current_lot = fx.refresh_lot(lot["id"])
    assert current_lot["quantity_on_hand"] == 100, "the lot's on_hand stays 100"
    assert current_lot["quantity_reserved"] == 0


def test_lot_expiring_on_buffered_date_excluded():
    """PRD §3.7: "a lot is eligible when it belongs to the enrollment's program,
    is `ACTIVE`, has `quantity_on_hand` greater than zero, and has an
    `expiry_date` strictly later than today plus the program's
    `lot_expiry_buffer_days` — a lot expiring exactly on the buffered date is
    excluded."

    Design: Difficulty/resource_temporal_overlap/lot_expiry_buffer_exclusion
    """
    ctx = fx.setup_approved_enrollment()
    lot_bad = fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-BAD",
                                   quantity_received=50, expiry_date="2026-05-31")
    lot_good = fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-GOOD",
                                    quantity_received=5, expiry_date="2026-06-01")

    shipment = fx.create_shipment_record(ctx["enrollment"]["id"], quantity_units=5,
                                         idempotency_key="ship-b1")
    lines, _meta = validate_paginated(api_client.list_shipment_lines(shipment["id"], fx.CW))
    assert len(lines) == 1
    assert lines[0]["lot_id"] == lot_good["id"], (
        "expiry exactly on today + 30d buffer (2026-05-31) is excluded by the strict > rule")
    assert lines[0]["quantity"] == 5
    bad_now = fx.refresh_lot(lot_bad["id"])
    assert bad_now["quantity_on_hand"] == 50, "the buffer-blocked lot is never allocated"


def test_drained_pool_rejects_with_no_eligible_inventory():
    """PRD §3.7: "When no lot qualifies, creation is rejected with
    `ERR_NO_ELIGIBLE_INVENTORY`."

    Design: Difficulty/resource_temporal_overlap/lot_expiry_buffer_exclusion
    """
    ctx = fx.setup_approved_enrollment()
    fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-BAD",
                         quantity_received=50, expiry_date="2026-05-31")
    fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-GOOD",
                         quantity_received=5, expiry_date="2026-06-01")
    fx.create_shipment_record(ctx["enrollment"]["id"], quantity_units=5,
                              idempotency_key="ship-b1")

    resp = api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=5,
                                idempotency_key="ship-b2"),
        fx.CW)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_INVENTORY, expected_status=409)


def test_reserve_moves_units_to_reserved_bucket():
    """PRD §3.7: "On receipt, `quantity_on_hand` equals `quantity_received`" and
    "the on-hand figure is always what remains after subtracting reserved,
    shipped, dispensed, and quarantined units from what was received." and "Each
    line's lot has its `quantity_on_hand` moved into `quantity_reserved`"

    Design: Difficulty/compensating_invariant/lot_units_reserve_cancel_conservation
    """
    ctx = fx.setup_reserved_shipment(quantity_units=10, lot_number="LOT-INV",
                                     idempotency_key="ship-inv1")
    lot = fx.refresh_lot(ctx["lot"]["id"])
    assert lot["quantity_on_hand"] == 90
    assert lot["quantity_reserved"] == 10
    assert_lot_units_conserved(lot)
    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert enrollment["remaining_units"] == 90


def test_cancel_restores_every_bucket():
    """PRD §3.7: "Cancelling a `RESERVED` shipment — by a `CaseWorker`, or by the
    system during an enrollment suspend, terminate, or expire cascade — requires
    the `RESERVED` state (`ERR_SHIPMENT_NOT_CANCELLABLE` otherwise) and fully
    compensates the reservation: per line, the lot's `quantity_reserved` returns
    to `quantity_on_hand`, and the enrollment's `remaining_units` is restored by
    `quantity_units`."

    Design: Difficulty/compensating_invariant/lot_units_reserve_cancel_conservation
    """
    ctx = fx.setup_reserved_shipment(quantity_units=10, lot_number="LOT-INV",
                                     idempotency_key="ship-inv1")
    cancelled = validate_success(api_client.cancel_shipment(
        ctx["shipment"]["id"], {"reason": "patient declined"}, fx.CW))
    assert cancelled["status"] == "CANCELLED"

    lot = fx.refresh_lot(ctx["lot"]["id"])
    assert lot["quantity_on_hand"] == 100, "compensating cancel returns on_hand to 100"
    assert lot["quantity_reserved"] == 0
    assert lot["quantity_shipped"] == 0
    assert lot["quantity_dispensed"] == 0
    assert lot["quantity_quarantined"] == 0
    assert_lot_units_conserved(lot)
    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert enrollment["remaining_units"] == 100, "unit commitment restored with zero drift"


def test_shipment_value_rounds_per_line():
    """PRD §2.6: "A shipment's `value_cents` is the sum of its lines'
    individually rounded values" and §3.7: "a per-line `value_cents` computed as
    the quantity multiplied by the lot's `unit_cost_per_unit` and by 100, rounded
    half up to whole cents" — 6 units at '12.3456' round once per line to 7407.

    Design: Difficulty/combinatorial_formula/per_event_vs_per_line_rounding_order
    """
    ctx = fx.setup_reserved_shipment(quantity_units=6, unit_cost="12.3456",
                                     lot_quantity=100, lot_number="LOT-A",
                                     idempotency_key="ship-r1")
    shipment = validate_success(api_client.get_shipment(ctx["shipment"]["id"], fx.CW))
    assert shipment["value_cents"] == 7407, (
        "per-line rounding of 6 x 12.3456 x 100 = 7407.36 -> 7407")
    lines, _meta = validate_paginated(api_client.list_shipment_lines(shipment["id"], fx.CW))
    assert len(lines) == 1 and lines[0]["value_cents"] == 7407


def test_dispensed_value_rounds_per_event():
    """PRD §2.6: "for a lot with unit cost `'12.3456'`, two dispense events of 3
    units each yield 3704 cents plus 3704 cents, totalling 7408 cents, whereas
    valuing 6 units at once would round to 7407 cents. The per-event order is the
    pinned one, and the two values deliberately differ."

    Design: Difficulty/combinatorial_formula/per_event_vs_per_line_rounding_order
    """
    ctx = fx.setup_delivered_shipment(quantity_units=6, unit_cost="12.3456",
                                      lot_quantity=100, lot_number="LOT-A",
                                      idempotency_key="ship-r1")
    event1 = fx.create_dispense_event_record(ctx["shipment"]["id"], ctx["lot"]["id"], 3)
    event2 = fx.create_dispense_event_record(ctx["shipment"]["id"], ctx["lot"]["id"], 3)
    assert_dispense_event(event1)
    assert event1["value_cents"] == 3704, "per-event rounding of 3 x 12.3456 x 100 = 3703.68 -> 3704"
    assert event2["value_cents"] == 3704

    shipment = validate_success(api_client.get_shipment(ctx["shipment"]["id"], fx.CW))
    assert shipment["dispensed_value_cents"] == 7408, "sum of per-event rounds"
    assert shipment["dispensed_value_cents"] != shipment["value_cents"], (
        "the two pinned rounding orders diverge by exactly one cent for identical units")


def test_shipment_quantity_limits():
    """PRD §3.7: "The request names the `enrollment_id`, a `destination` of
    `PROVIDER` or `PATIENT`, and a `quantity_units` of at least 1 (zero or less
    fails as `ERR_INVALID_QUANTITY`)." and "The quantity must satisfy both hard
    caps: it may not exceed the program's `max_units_per_shipment` nor the
    enrollment's `remaining_units`, with violations rejected as
    `ERR_SHIPMENT_QUANTITY_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/shipment_quantity_limits_and_zero_rejection
    """
    ctx = fx.setup_approved_enrollment()
    fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-Q", quantity_received=200)

    zero = api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=0,
                                idempotency_key="q-zero"), fx.CW)
    validate_error(zero, ApiErrorId.ERR_INVALID_QUANTITY, expected_status=400)

    over_max = api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=31,
                                idempotency_key="q-31"), fx.CW)
    validate_error(over_max, ApiErrorId.ERR_SHIPMENT_QUANTITY_LIMIT_EXCEEDED,
                   expected_status=422)

    fx.create_shipment_record(ctx["enrollment"]["id"], quantity_units=30,
                              idempotency_key="q-30")
    over_remaining = api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=71,
                                idempotency_key="q-71"), fx.CW)
    validate_error(over_remaining, ApiErrorId.ERR_SHIPMENT_QUANTITY_LIMIT_EXCEEDED,
                   expected_status=422)

    for key in ("q-30b", "q-30c"):
        fx.create_shipment_record(ctx["enrollment"]["id"], quantity_units=30,
                                  idempotency_key=key)
    fx.create_shipment_record(ctx["enrollment"]["id"], quantity_units=10,
                              idempotency_key="q-10")
    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert enrollment["remaining_units"] == 0, "100 - (30+30+30+10) drains the pool"


def test_fefo_ordering_expiry_then_created_at():
    """PRD §3.7: "Eligible lots are ranked by `expiry_date` ascending with ties
    broken by `created_at` ascending (never by id), and the allocation fills
    greedily from the earliest-expiry lot, overflowing to the next."

    Design: Corner/calculations/fefo_ordering_expiry_then_created_at
    """
    ctx = fx.setup_approved_enrollment()
    lot_a = fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-A",
                                 quantity_received=10, expiry_date="2026-08-01")
    lot_b = fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-B",
                                 quantity_received=10, expiry_date="2026-07-01")
    lot_c = fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-C",
                                 quantity_received=10, expiry_date="2026-07-01")

    shipment = fx.create_shipment_record(ctx["enrollment"]["id"], quantity_units=12,
                                         idempotency_key="fefo-1")
    lines, _meta = validate_paginated(api_client.list_shipment_lines(shipment["id"], fx.CW))
    assert len(lines) == 2, "12 units span exactly two lots"
    assert lines[0]["lot_id"] == lot_b["id"] and lines[0]["quantity"] == 10, (
        "earliest expiry lot fills first")
    assert lines[1]["lot_id"] == lot_c["id"] and lines[1]["quantity"] == 2, (
        "same-expiry tie breaks by created_at — B before C — and overflow spills to C")

    untouched = fx.refresh_lot(lot_a["id"])
    assert untouched["quantity_on_hand"] == 10 and untouched["quantity_reserved"] == 0, (
        "the latest-expiry lot is never touched")


def test_duplicate_lot_number_rejected():
    """PRD §3.7: "Physical product enters the system as **InventoryLot** records
    received by a `ProgramAdministrator`: the owning `program_id`, a `lot_number`
    unique within its program (a repeat draws `ERR_LOT_NUMBER_DUPLICATE`)"

    Design: Corner/entities/lot_duplicate_number_rejected
    """
    ctx = fx.setup_program_with_period()
    fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-1", quantity_received=10)
    resp = api_client.create_inventory_lot(
        create_lot_payload(ctx["program"]["id"], lot_number="LOT-1",
                           quantity_received=5, unit_cost_per_unit="90.0000",
                           expiry_date="2027-06-01"),
        fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_LOT_NUMBER_DUPLICATE, expected_status=409)
    lots, meta = validate_paginated(api_client.list_inventory_lots(
        fx.ADMIN, params={"program_id": ctx["program"]["id"]}))
    assert meta["total_count"] == 1, "the duplicate lot is not persisted"


def test_second_dispatch_rejected():
    """PRD §3.7: "From `RESERVED`, a `CaseWorker` may dispatch the shipment — any
    other state draws `ERR_SHIPMENT_NOT_RESERVED`"

    Design: Corner/state_machines/shipment_dispatch_twice_rejected
    """
    ctx = fx.setup_dispatched_shipment(quantity_units=10, lot_number="LOT-D1",
                                       idempotency_key="disp-twice")
    resp = api_client.dispatch_shipment(ctx["shipment"]["id"], fx.CW)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_RESERVED, expected_status=409)
    current = validate_success(api_client.get_shipment(ctx["shipment"]["id"], fx.CW))
    assert current["status"] == "DISPATCHED"


def test_cancel_dispatched_shipment_rejected():
    """PRD §3.7: "Cancelling a `RESERVED` shipment — by a `CaseWorker`, or by the
    system during an enrollment suspend, terminate, or expire cascade — requires
    the `RESERVED` state (`ERR_SHIPMENT_NOT_CANCELLABLE` otherwise)"

    Design: Corner/state_machines/shipment_cancel_after_dispatch_rejected
    """
    ctx = fx.setup_dispatched_shipment(quantity_units=10, lot_number="LOT-C2",
                                       idempotency_key="cancel-late")
    resp = api_client.cancel_shipment(ctx["shipment"]["id"], {"reason": "too late"}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_CANCELLABLE, expected_status=409)
    current = validate_success(api_client.get_shipment(ctx["shipment"]["id"], fx.CW))
    assert current["status"] == "DISPATCHED"
    lot = fx.refresh_lot(ctx["lot"]["id"])
    assert lot["quantity_reserved"] == 0 and lot["quantity_shipped"] == 10, (
        "the failed cancel releases nothing")


def test_patient_deliver_ownership_enforced():
    """PRD §3.7: "a `Patient` may confirm only their own `PATIENT`-destination
    shipment (`ERR_OWNERSHIP_VIOLATION` otherwise)."

    Design: Corner/state_machines/shipment_patient_deliver_ownership_enforced
    """
    ctx = fx.setup_dispatched_shipment(quantity_units=10, lot_number="LOT-O1",
                                       idempotency_key="own-deliv")
    other_patient = fx.create_patient_record(full_name="Rae Rill")
    resp = api_client.deliver_shipment(
        ctx["shipment"]["id"], make_patient_headers(other_patient["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION, expected_status=403)
    current = validate_success(api_client.get_shipment(ctx["shipment"]["id"], fx.CW))
    assert current["status"] == "DISPATCHED"

    delivered = validate_success(api_client.deliver_shipment(
        ctx["shipment"]["id"], make_patient_headers(ctx["patient"]["id"])))
    assert delivered["status"] == "DELIVERED", "the owning patient can confirm"


def test_dispense_before_delivery_rejected():
    """PRD §3.8: "Once a shipment is `DELIVERED` — dispensing against any other
    state is rejected with `ERR_SHIPMENT_NOT_DELIVERED` — a `PharmacyDispenser`
    records **DispenseEvent** records beneath it, one per lot actually
    dispensed."

    Design: Corner/state_machines/shipment_dispense_before_deliver_rejected
    """
    ctx = fx.setup_dispatched_shipment(quantity_units=10, lot_number="LOT-DP",
                                       idempotency_key="disp-early")
    resp = api_client.create_dispense_event(
        ctx["shipment"]["id"], {"lot_id": ctx["lot"]["id"], "quantity": 4}, fx.DISPENSER)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_DELIVERED, expected_status=409)
    events, meta = validate_paginated(api_client.list_shipment_dispense_events(
        ctx["shipment"]["id"], fx.CW))
    assert events == [] and meta["total_count"] == 0, "no DispenseEvent persisted"


def test_shipment_idempotency_replay_and_conflict():
    """PRD §2.9: "When a key arrives that the server has seen before, the request
    bodies are compared. An identical body replays the original `201 Created`
    response verbatim with no side effects — no new shipment, no new reservation.
    The same key with a different body is rejected with `ERR_IDEMPOTENCY_CONFLICT`
    (HTTP 409)."

    Design: Corner/endpoints/shipment_idempotency_replay_and_conflict
    """
    ctx = fx.setup_approved_enrollment()
    lot = fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-IDEM")

    first = validate_success(api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=5,
                                idempotency_key="K1"), fx.CW), expected_status=201)
    replay = validate_success(api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=5,
                                idempotency_key="K1"), fx.CW), expected_status=201)
    assert replay["id"] == first["id"], "the replay returns the same shipment id"

    conflict = api_client.create_shipment(
        create_shipment_payload(ctx["enrollment"]["id"], quantity_units=6,
                                idempotency_key="K1"), fx.CW)
    validate_error(conflict, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT, expected_status=409)

    lot_now = fx.refresh_lot(lot["id"])
    assert lot_now["quantity_reserved"] == 5, "exactly one reservation happened"
    shipments, meta = validate_paginated(api_client.list_shipments(
        fx.CW, params={"enrollment_id": ctx["enrollment"]["id"]}))
    assert meta["total_count"] == 1


def test_dispenser_cannot_dispatch():
    """PRD §3.7: "From `RESERVED`, a `CaseWorker` may dispatch the shipment" —
    dispatch is not among the dispensing pharmacist's capabilities.
    PRD §2.1: "A request whose role is valid but not permitted on the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/dispenser_cannot_dispatch_shipment
    """
    ctx = fx.setup_reserved_shipment(quantity_units=5, lot_number="LOT-RB",
                                     idempotency_key="rbac-1")
    resp = api_client.dispatch_shipment(ctx["shipment"]["id"], fx.DISPENSER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    current = validate_success(api_client.get_shipment(ctx["shipment"]["id"], fx.CW))
    assert current["status"] == "RESERVED"


def _reconcilable_program():
    """Enrollment + lot of 10; a 6-unit shipment dispatched, delivered, and
    fully dispensed (book on_hand 4); the budget period then CLOSED."""
    ctx = fx.setup_delivered_shipment(quantity_units=6, lot_quantity=10,
                                      lot_number="LOT-R1", idempotency_key="recon-1")
    fx.create_dispense_event_record(ctx["shipment"]["id"], ctx["lot"]["id"], 6)
    validate_success(api_client.close_budget_period(ctx["budget_period"]["id"], fx.ADMIN))
    return ctx


def test_reconciliation_variance_flags_lot():
    """PRD §3.8: "For each counted lot the run computes `book_on_hand` from the
    lot's `quantity_on_hand`, a `variance_units` of actual minus book, and a
    `variance_value_cents` as the variance multiplied by the lot's
    `unit_cost_per_unit` and by 100, rounded half up per lot." and "The run's
    outcome is computed atomically at creation: `CLEAN` if and only if every
    line's variance is zero, otherwise `VARIANCE_FLAGGED`, and every lot with a
    non-zero variance is moved to `UNDER_INVESTIGATION` and thereby excluded from
    further allocation."

    Design: Corner/calculations/reconciliation_variance_flags_lot
    """
    ctx = _reconcilable_program()
    run = validate_success(api_client.create_reconciliation_run(
        create_reconciliation_payload(
            ctx["program"]["id"], ctx["budget_period"]["id"],
            [{"lot_id": ctx["lot"]["id"], "actual_on_hand": 2}]),
        fx.ADMIN), expected_status=201)
    assert run["status"] == "VARIANCE_FLAGGED"
    assert len(run["lines"]) == 1
    line = run["lines"][0]
    assert line["lot_id"] == ctx["lot"]["id"]
    assert line["book_on_hand"] == 4, "10 received - 6 dispensed"
    assert line["actual_on_hand"] == 2
    assert line["variance_units"] == -2
    assert line["variance_value_cents"] == -20000, "-2 x 100.0000 x 100"

    lot = fx.refresh_lot(ctx["lot"]["id"])
    assert lot["status"] == "UNDER_INVESTIGATION", "the flagged lot leaves ACTIVE"


def test_reconciliation_clean_run():
    """PRD §3.8: "The run's outcome is computed atomically at creation: `CLEAN`
    if and only if every line's variance is zero, otherwise `VARIANCE_FLAGGED`"

    Design: Corner/calculations/reconciliation_clean_run
    """
    ctx = _reconcilable_program()
    run = validate_success(api_client.create_reconciliation_run(
        create_reconciliation_payload(
            ctx["program"]["id"], ctx["budget_period"]["id"],
            [{"lot_id": ctx["lot"]["id"], "actual_on_hand": 4}]),
        fx.ADMIN), expected_status=201)
    assert run["status"] == "CLEAN", "count matches book (4 == 4)"
    lot = fx.refresh_lot(ctx["lot"]["id"])
    assert lot["status"] == "ACTIVE", "a zero variance leaves the lot ACTIVE"


def test_reconciliation_missing_counts_returns_422():
    """PRD §3.8: "The submitted `counts` — one entry per lot carrying
    `actual_on_hand` — must cover every `ACTIVE` lot of the program whose book
    units (on-hand plus reserved plus shipped) exceed zero, else
    `ERR_RECONCILIATION_COUNTS_MISSING` (HTTP 422)"

    Design: Corner/calculations/reconciliation_missing_counts_returns_422
    """
    ctx = fx.setup_program_with_period()
    fx.create_lot_record(ctx["program"]["id"], lot_number="LOT-R3", quantity_received=10)
    validate_success(api_client.close_budget_period(ctx["budget_period"]["id"], fx.ADMIN))
    resp = api_client.create_reconciliation_run(
        create_reconciliation_payload(ctx["program"]["id"], ctx["budget_period"]["id"], []),
        fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_RECONCILIATION_COUNTS_MISSING, expected_status=422)
    runs, meta = validate_paginated(api_client.list_reconciliation_runs(
        fx.ADMIN, params={"program_id": ctx["program"]["id"]}))
    assert runs == [] and meta["total_count"] == 0, "no run persisted"


def test_reconciliation_requires_closed_period():
    """PRD §3.8: "a `ProgramAdministrator` runs a **ReconciliationRun** against a
    `program_id` and a `budget_period_id` that must be `CLOSED` — reconciling an
    open period is rejected with `ERR_BUDGET_PERIOD_NOT_CLOSED`."

    Design: Corner/calculations/reconciliation_requires_closed_period
    """
    ctx = fx.setup_program_with_period()
    resp = api_client.create_reconciliation_run(
        create_reconciliation_payload(ctx["program"]["id"], ctx["budget_period"]["id"], []),
        fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_BUDGET_PERIOD_NOT_CLOSED, expected_status=409)
