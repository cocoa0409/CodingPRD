"""Receiving lots, the earliest-expiry planner, and pellet conservation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lot_buckets,
    assert_pellet_allocation,
    assert_pellet_lot,
    attach_consent_to,
    book_procedure,
    procedure_allocations,
    procedure_version,
    read_lot,
    read_procedure,
    receive_lot,
    run_allocation_for,
    setup_clinic,
    setup_consented_procedure,
    validate_error,
    validate_success,
)

INVENTORY = TEST_USERS["inventory_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

SLOT_ON_THE_EDGE = "2026-05-10T09:00:00Z"


def _consented_procedure_awaiting_allocation(api, *, lot_specs, release_lots=True,
                                             scheduled_start=SLOT_ON_THE_EDGE,
                                             prescribed_dose_mg=1000, room_code="RM13"):
    """Clinic + a CONSENTED procedure whose allocation has not yet been run."""
    ctx = setup_clinic(
        api, prescribed_dose_mg=prescribed_dose_mg,
        lot_specs=lot_specs, release_lots=release_lots,
    )
    procedure = book_procedure(
        api, ctx["patient_id"], ctx["physician_id"], ctx["consult_id"],
        ctx["standing_order_id"], room_code=room_code, scheduled_start=scheduled_start,
    )
    attach_consent_to(api, procedure["id"], ctx["consent"]["id"])
    ctx["procedure"] = procedure
    ctx["procedure_id"] = procedure["id"]
    return ctx


def test_lot_expiring_exactly_at_the_slot_start_is_not_a_candidate(api):
    """PRD §3.5: "the candidate set is every lot whose `hormone_type` matches the procedure's,
    whose `strength_mg` equals that leg's strength exactly, whose `sterility_status` is
    `RELEASED`, whose `expiry_date` falls **strictly after** the procedure's `scheduled_start`
    (a lot expiring exactly at the slot start is not a candidate), and whose `qty_on_hand` is
    greater than zero."

    Design: Difficulty/boundary_precision_check/fefo_lot_expiring_exactly_at_slot_start_is_not_a_candidate
    """
    ctx = _consented_procedure_awaiting_allocation(
        api,
        lot_specs=[
            {"lot_code": "T200-EDGE", "strength_mg": 200, "qty_received": 10,
             "expiry_date": SLOT_ON_THE_EDGE},
            {"lot_code": "T200-LATE", "strength_mg": 200, "qty_received": 10,
             "expiry_date": "2026-09-01T00:00:00Z"},
        ],
    )
    edge, late = ctx["lots"]["T200-EDGE"], ctx["lots"]["T200-LATE"]

    run_allocation_for(api, ctx["procedure_id"])

    edge_after = read_lot(api, edge["id"])
    assert_lot_buckets(edge_after, on_hand=10, reserved=0, consumed=0, wasted=0, returned=0)
    late_after = read_lot(api, late["id"])
    assert_lot_buckets(late_after, on_hand=5, reserved=5, consumed=0, wasted=0, returned=0)
    assert_pellet_lot(edge_after)


def test_whole_draw_lands_on_the_later_expiring_lot_at_rank_one(api):
    """PRD §3.5: "On success, one `PelletAllocation` row is written per lot draw. Each carries
    the `procedure_id` it serves and the `lot_id` it drew from — both chosen by the server,
    never supplied by the client — the `strength_mg` copied from the chosen lot, the
    `quantity` drawn, an `allocation_rank` assigned 1, 2, 3 and onward across the concatenated
    walk order with the large-strength leg's draws numbered before the small-strength leg's,
    and a `status` of `RESERVED`."
    PRD §3.5: "Each drawn lot moves that quantity from `qty_on_hand` into `qty_reserved`, and
    the procedure's `pellets_allocated` is recomputed as the sum of `quantity` over its
    allocation rows whose status is `RESERVED`, `OPENED`, `CONSUMED`, `WASTED` or
    `RECALL_FLAGGED`."

    Design: Difficulty/boundary_precision_check/fefo_lot_expiring_exactly_at_slot_start_is_not_a_candidate
    """
    ctx = _consented_procedure_awaiting_allocation(
        api,
        lot_specs=[
            {"lot_code": "T200-EDGE", "strength_mg": 200, "qty_received": 10,
             "expiry_date": SLOT_ON_THE_EDGE},
            {"lot_code": "T200-LATE", "strength_mg": 200, "qty_received": 10,
             "expiry_date": "2026-09-01T00:00:00Z"},
        ],
    )
    late = ctx["lots"]["T200-LATE"]

    response = api.run_allocation(
        ctx["procedure_id"],
        {"expected_procedure_version": procedure_version(api, ctx["procedure_id"])},
        INVENTORY,
    )
    rows = validate_success(response, 201)

    assert len(rows) == 1, f"Only the later lot is a candidate, so exactly one draw: {rows}"
    row = rows[0]
    assert row["lot_id"] == late["id"], "The earlier-expiring lot expires exactly at the slot"
    assert row["quantity"] == 5
    assert row["allocation_rank"] == 1
    assert row["status"] == "RESERVED"
    assert_pellet_allocation(row)

    assert read_procedure(api, ctx["procedure_id"])["pellets_allocated"] == 5


def test_quarantined_only_inventory_rejects_the_allocation(api):
    """PRD §3.5: "Two failure modes land in the same place. If a leg's candidate set is empty,
    or if the walk exhausts the candidates with pellets still needed, the **whole** request
    fails with `ERR_INSUFFICIENT_PELLET_INVENTORY` and neither a lot bucket nor an allocation
    row is touched — including the leg that had already succeeded."
    PRD §3.5: "The plan is strength-exact and never substitutes two small pellets for one
    large; quarantined and recalled lots are never candidates at all."

    Design: Difficulty/boundary_precision_check/fefo_empty_candidate_set_rejects_and_mutates_nothing
    """
    ctx = _consented_procedure_awaiting_allocation(
        api,
        lot_specs=[{"lot_code": "T200-Q", "strength_mg": 200, "qty_received": 10,
                    "expiry_date": "2026-09-01T00:00:00Z"}],
        release_lots=False,
        scheduled_start="2026-05-12T09:00:00Z",
        room_code="RM14",
    )

    response = api.run_allocation(
        ctx["procedure_id"],
        {"expected_procedure_version": procedure_version(api, ctx["procedure_id"])},
        INVENTORY,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PELLET_INVENTORY.value)
    assert response.status_code == 409

    quarantined = read_lot(api, ctx["lots"]["T200-Q"]["id"])
    assert quarantined["sterility_status"] == "QUARANTINED"


def test_rejected_allocation_leaves_the_lot_and_the_procedure_untouched(api):
    """PRD §3.5: "Two failure modes land in the same place. If a leg's candidate set is empty,
    or if the walk exhausts the candidates with pellets still needed, the **whole** request
    fails with `ERR_INSUFFICIENT_PELLET_INVENTORY` and neither a lot bucket nor an allocation
    row is touched — including the leg that had already succeeded."

    Design: Difficulty/boundary_precision_check/fefo_empty_candidate_set_rejects_and_mutates_nothing
    """
    ctx = _consented_procedure_awaiting_allocation(
        api,
        lot_specs=[{"lot_code": "T200-Q", "strength_mg": 200, "qty_received": 10,
                    "expiry_date": "2026-09-01T00:00:00Z"}],
        release_lots=False,
        scheduled_start="2026-05-12T09:00:00Z",
        room_code="RM14",
    )

    response = api.run_allocation(
        ctx["procedure_id"],
        {"expected_procedure_version": procedure_version(api, ctx["procedure_id"])},
        INVENTORY,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PELLET_INVENTORY.value)

    lot = read_lot(api, ctx["lots"]["T200-Q"]["id"])
    assert_lot_buckets(lot, on_hand=10, reserved=0, consumed=0, wasted=0, returned=0)

    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["pellets_allocated"] == 0
    assert procedure["status"] == "CONSENTED"
    assert procedure_allocations(api, ctx["procedure_id"]) == []


def test_allocation_moves_pellets_from_on_hand_into_reserved(api):
    """PRD §2.10: "For every `PelletLot`, `qty_received` always equals the sum of
    `qty_on_hand`, `qty_reserved`, `qty_consumed`, `qty_wasted` and `qty_returned`."
    PRD §3.5: "Each drawn lot moves that quantity from `qty_on_hand` into `qty_reserved`, and
    the procedure's `pellets_allocated` is recomputed as the sum of `quantity` over its
    allocation rows whose status is `RESERVED`, `OPENED`, `CONSUMED`, `WASTED` or
    `RECALL_FLAGGED`."

    Design: Difficulty/compensating_invariant/allocate_then_cancel_restores_lot_pellet_conservation
    """
    ctx = setup_consented_procedure(
        api, prescribed_dose_mg=1150, room_code="RM22", scheduled_start="2026-06-05T09:00:00Z",
    )
    large = read_lot(api, ctx["lots"]["T200-A"]["id"])
    small = read_lot(api, ctx["lots"]["T100-B"]["id"])

    assert_lot_buckets(large, on_hand=15, reserved=5, consumed=0, wasted=0, returned=0)
    assert_lot_buckets(small, on_hand=18, reserved=2, consumed=0, wasted=0, returned=0)
    assert read_procedure(api, ctx["procedure_id"])["pellets_allocated"] == 7


def test_cancelling_from_consented_returns_every_bucket_to_its_pre_allocation_value(api):
    """PRD §2.10: "The compensating pair is exact — running an allocation moves pellets from
    `qty_on_hand` to `qty_reserved`, and cancelling that procedure while it is still
    `CONSENTED` moves them straight back, leaving all five buckets at their pre-allocation
    values."
    PRD §3.6: "From `SCHEDULED` or `CONSENTED`, every allocation in `RESERVED` moves to
    `RELEASED` and its quantity returns from `qty_reserved` to `qty_on_hand`; a consent
    attached before the cancel stays `ACTIVE` and remains reusable."
    PRD §3.6: "When the lead is 48 hours or more, `cancel_tier` is `NONE` and the base fee is 0."

    Design: Difficulty/compensating_invariant/allocate_then_cancel_restores_lot_pellet_conservation
    """
    ctx = setup_consented_procedure(
        api, prescribed_dose_mg=1150, room_code="RM22", scheduled_start="2026-06-05T09:00:00Z",
    )

    cancelled = validate_success(
        api.cancel_procedure(ctx["procedure_id"], {"reason": "Patient rescheduled"}, FRONT_DESK),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_tier"] == "NONE"
    assert cancelled["cancel_fee_cents"] == 0

    large = read_lot(api, ctx["lots"]["T200-A"]["id"])
    small = read_lot(api, ctx["lots"]["T100-B"]["id"])
    assert_lot_buckets(large, on_hand=20, reserved=0, consumed=0, wasted=0, returned=0)
    assert_lot_buckets(small, on_hand=20, reserved=0, consumed=0, wasted=0, returned=0)

    statuses = {row["status"] for row in procedure_allocations(api, ctx["procedure_id"])}
    assert statuses == {"RELEASED"}, f"Every allocation must read RELEASED, got {statuses}"


def test_lot_receipt_sets_on_hand_from_qty_received_and_zeroes_the_rest(api):
    """PRD §3.5: "On receipt, `qty_on_hand` is set equal to `qty_received` while
    `qty_reserved`, `qty_consumed`, `qty_wasted` and `qty_returned` are all set to 0,
    satisfying the pellet conservation identity from the first instant. `sterility_status`
    starts at `QUARANTINED`, and `recall_severity`, `recalled_at` and `recall_reason` are all
    null."

    Design: Corner/entities/pellet_lot_buckets_initialised_from_qty_received
    """
    response = api.create_pellet_lot(
        {
            "lot_code": "T200-CORNER",
            "hormone_type": "TESTOSTERONE",
            "strength_mg": 200,
            "expiry_date": "2026-12-01T00:00:00Z",
            "qty_received": 12,
        },
        INVENTORY,
    )
    lot = validate_success(response, 201)

    assert_lot_buckets(lot, on_hand=12, reserved=0, consumed=0, wasted=0, returned=0)
    assert lot["sterility_status"] == "QUARANTINED"
    assert lot["recall_severity"] is None
    assert lot["recalled_at"] is None
    assert lot["recall_reason"] is None
    assert_pellet_lot(lot)


def test_releasing_an_already_released_lot_reports_invalid_state(api):
    """PRD §3.5: "Releasing it — again an `InventoryManager` action — moves
    `QUARANTINED → RELEASED`, increments the lot's `version` by 1, and makes it a candidate
    for allocation."
    PRD §2.9: "**Rung 10** — the target row is in a state from which the requested transition
    is declared on the relevant axis, on every action endpoint. Otherwise `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/release_an_already_released_lot_returns_invalid_state
    """
    lot = receive_lot(api, "T200-REL", strength_mg=200, qty_received=10)
    validate_success(api.release_pellet_lot(lot["id"], INVENTORY), 200)

    response = api.release_pellet_lot(lot["id"], INVENTORY)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409

    after = read_lot(api, lot["id"])
    assert after["sterility_status"] == "RELEASED"
    assert_lot_buckets(after, on_hand=10, reserved=0, consumed=0, wasted=0, returned=0)


def test_recalling_an_already_recalled_lot_reports_already_terminal(api):
    """PRD §2.9: "**Rung 11** — the target row is not already in a terminal state for the axis
    being moved, on every action endpoint. The terminal sets are: a procedure's `status` in
    `CANCELLED` or `VOIDED`; a lot's `sterility_status` at `RECALLED`; a standing order's
    `status` at `REVOKED`; a series pack's `status` in `EXPIRED` or `REFUNDED`; an injection
    visit's `status` in `CANCELLED` or `VOIDED`; a membership's `status` at `CANCELLED`; a
    financing plan's `status` in `DEFAULTED`, `PAID_OFF` or `CANCELLED`; an adverse event's
    `status` at `CLOSED`; and a notification's `status` at `ACKNOWLEDGED`. Otherwise
    `ERR_ALREADY_TERMINAL` (409)."
    PRD §3.8: "Hop one moves `sterility_status` to the terminal `RECALLED`, increases
    `qty_returned` by whatever `qty_on_hand` held and then sets `qty_on_hand` to 0, and
    records `recall_severity`, `recall_reason` and `recalled_at` from the logical clock."

    Design: Corner/state_machines/recall_an_already_recalled_lot_returns_already_terminal
    """
    lot = receive_lot(api, "T200-RCL", strength_mg=200, qty_received=10)
    validate_success(api.release_pellet_lot(lot["id"], INVENTORY), 200)
    validate_success(
        api.recall_pellet_lot(
            lot["id"], {"severity_class": "CLASS_II", "recall_reason": "Labelling defect"},
            COMPLIANCE,
        ),
        200,
    )

    response = api.recall_pellet_lot(
        lot["id"], {"severity_class": "CLASS_I", "recall_reason": "Escalated finding"}, COMPLIANCE
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)
    assert response.status_code == 409

    after = read_lot(api, lot["id"])
    assert after["recall_severity"] == "CLASS_II", "The first recall's severity stands"
    assert_lot_buckets(after, on_hand=0, reserved=0, consumed=0, wasted=0, returned=10)


def test_lot_strength_outside_the_hormone_ladder_is_refused(api):
    """PRD §3.5: "The strength must be a rung of the ladder for that hormone — 200 mg or
    100 mg for testosterone, 25 mg or 10 mg for estradiol — and anything else is rejected with
    `ERR_LOT_NOT_ELIGIBLE`."

    Design: Corner/validations/lot_strength_outside_the_hormone_ladder_is_rejected
    """
    response = api.create_pellet_lot(
        {
            "lot_code": "T150-BAD",
            "hormone_type": "TESTOSTERONE",
            "strength_mg": 150,
            "expiry_date": "2026-12-01T00:00:00Z",
            "qty_received": 10,
        },
        INVENTORY,
    )
    validate_error(response, ApiErrorId.ERR_LOT_NOT_ELIGIBLE.value)
    assert response.status_code == 409


def test_rerunning_the_planner_supersedes_the_prior_reserved_set(api):
    """PRD §3.5: "Re-running the planner supersedes rather than adds. Any allocation row this
    procedure already holds in `RESERVED` or `OPENED` is first moved to `RELEASED` with its
    quantity credited back from `qty_reserved` to `qty_on_hand`, and only then is the new plan
    computed against the refreshed inventory."

    Design: Corner/endpoints/reallocating_supersedes_the_prior_reserved_set
    """
    ctx = setup_consented_procedure(
        api, prescribed_dose_mg=1000, room_code="RM60", scheduled_start="2026-06-20T09:00:00Z",
        lot_specs=[{"lot_code": "T200-A", "strength_mg": 200, "qty_received": 20}],
    )

    run_allocation_for(api, ctx["procedure_id"])

    lot = read_lot(api, ctx["lots"]["T200-A"]["id"])
    assert_lot_buckets(lot, on_hand=15, reserved=5, consumed=0, wasted=0, returned=0)

    rows = procedure_allocations(api, ctx["procedure_id"])
    assert len(rows) == 2, f"The prior row is superseded, not replaced in place: {rows}"
    by_status = sorted((row["status"], row["quantity"]) for row in rows)
    assert by_status == [("RELEASED", 5), ("RESERVED", 5)]
    assert read_procedure(api, ctx["procedure_id"])["pellets_allocated"] == 5
