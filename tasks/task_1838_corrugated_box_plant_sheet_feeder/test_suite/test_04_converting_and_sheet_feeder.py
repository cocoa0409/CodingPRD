"""Converting bookings: routing fork, ink changeover gaps, shift-state
gating, overrun tolerance, and the sheet-feeder bypass."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_order_to_awaiting_converting,
    api_client,
    assert_money,
    assert_msf,
    assert_shift_minutes_invariant,
    attach_order,
    book_order,
    create_accepted_order,
    create_awaiting_sheet_feeder_order,
    create_converting_booking_payload,
    create_corrugator_run,
    create_draft_order,
    create_work_shift,
    schedule_order_on_run,
    setup_customer_and_grade,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def _three_die_cut_orders_awaiting(customer, grade):
    """Three DIE_CUT INTERNAL orders (A and B with inks [BLACK, RED], C with
    [BLUE]) all attached outs 1 to one run and advanced to
    AWAITING_CONVERTING."""
    order_a, _ = create_accepted_order(
        customer["id"], grade["id"], quantity=2000
    )  # canonical inks [BLACK, RED]
    order_b, _ = create_accepted_order(
        customer["id"], grade["id"], quantity=1000
    )
    order_c, _ = create_accepted_order(
        customer["id"], grade["id"], quantity=1000, ink_colors=["BLUE"]
    )
    shift = create_work_shift(machine_code="CORRUGATOR")
    run = create_corrugator_run(shift["id"], grade["id"], 480, 720)
    for order in (order_a, order_b, order_c):
        attach_order(run["id"], order["id"], 1)
    validate_success(api_client.complete_corrugator_run(run["id"], PLANNER))
    return [
        validate_success(api_client.get_box_order(o["id"], PLANNER))
        for o in (order_a, order_b, order_c)
    ]


def test_same_ink_booking_allowed_at_fifteen_minute_gap(api, production_planner_headers):
    """PRD 3.5: "A new booking must start at or after the end of the latest
    existing non-`CANCELLED` booking on the shift, plus a changeover gap: 15
    minutes when the new booking's ink set equals the previous booking's ink
    set, 45 minutes when it differs. On a shift with no prior bookings, any
    in-window start is acceptable. A violation is rejected with
    `ERR_BOOKING_CHANGEOVER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/converting_booking_append_with_ink_changeover_gap
    """
    customer, grade = setup_customer_and_grade()
    order_a, order_b, _order_c = _three_die_cut_orders_awaiting(customer, grade)
    die_shift = create_work_shift(machine_code="DIE_CUTTER")

    booking_a = validate_success(
        api.create_converting_booking(
            create_converting_booking_payload(
                order_a["id"], die_shift["id"], start_minute=480, end_minute=600
            ),
            production_planner_headers,
        ),
        201,
    )
    assert booking_a["status"] == "QUEUED"

    # Same ink set: start exactly at 600 + 15
    booking_b = validate_success(
        api.create_converting_booking(
            create_converting_booking_payload(
                order_b["id"], die_shift["id"], start_minute=615, end_minute=720
            ),
            production_planner_headers,
        ),
        201,
    )
    assert booking_b["status"] == "QUEUED"
    assert booking_b["ink_colors"] == ["BLACK", "RED"]


def test_different_ink_booking_requires_forty_five_minute_gap(
    api, production_planner_headers
):
    """PRD 3.5: "A new booking must start at or after the end of the latest
    existing non-`CANCELLED` booking on the shift, plus a changeover gap: 15
    minutes when the new booking's ink set equals the previous booking's ink
    set, 45 minutes when it differs. On a shift with no prior bookings, any
    in-window start is acceptable. A violation is rejected with
    `ERR_BOOKING_CHANGEOVER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/converting_booking_append_with_ink_changeover_gap
    """
    customer, grade = setup_customer_and_grade()
    order_a, order_b, order_c = _three_die_cut_orders_awaiting(customer, grade)
    die_shift = create_work_shift(machine_code="DIE_CUTTER")
    validate_success(
        api.create_converting_booking(
            create_converting_booking_payload(
                order_a["id"], die_shift["id"], start_minute=480, end_minute=600
            ),
            production_planner_headers,
        ),
        201,
    )
    validate_success(
        api.create_converting_booking(
            create_converting_booking_payload(
                order_b["id"], die_shift["id"], start_minute=615, end_minute=720
            ),
            production_planner_headers,
        ),
        201,
    )

    # Different ink set [BLUE]: 730 < 720 + 45 -> conflict
    conflict = api.create_converting_booking(
        create_converting_booking_payload(
            order_c["id"], die_shift["id"], start_minute=730, end_minute=800
        ),
        production_planner_headers,
    )
    validate_error(
        conflict, ApiErrorId.ERR_BOOKING_CHANGEOVER_CONFLICT, expected_status=409
    )

    # Exactly 720 + 45 = 765 -> allowed
    booking_c = validate_success(
        api.create_converting_booking(
            create_converting_booking_payload(
                order_c["id"], die_shift["id"], start_minute=765, end_minute=840
            ),
            production_planner_headers,
        ),
        201,
    )
    assert booking_c["status"] == "QUEUED"
    assert booking_c["ink_colors"] == ["BLUE"]

    shift_after = validate_success(
        api.get_work_shift(die_shift["id"], production_planner_headers)
    )
    assert shift_after["scheduled_minutes"] == 300  # 120 + 105 + 75
    assert_shift_minutes_invariant(shift_after)


def test_booking_on_cancelled_shift_rejected_invalid_state(
    api, production_planner_headers
):
    """PRD 3.5: "The order must be `AWAITING_CONVERTING` and the shift `OPEN`
    (otherwise `ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/booking_blocked_when_work_shift_cancelled
    """
    customer, grade = setup_customer_and_grade()
    order, _ = create_accepted_order(customer["id"], grade["id"])
    order = advance_order_to_awaiting_converting(order["id"], grade["id"], outs=3)
    assert order["status"] == "AWAITING_CONVERTING"

    die_shift = create_work_shift(machine_code="DIE_CUTTER")
    validate_success(api.cancel_work_shift(die_shift["id"], production_planner_headers))

    res = api.create_converting_booking(
        create_converting_booking_payload(
            order["id"], die_shift["id"], start_minute=480, end_minute=600
        ),
        production_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_rejected_booking_leaves_order_awaiting_converting_and_no_booking(
    api, production_planner_headers
):
    """PRD 3.5: "The order must be `AWAITING_CONVERTING` and the shift `OPEN`
    (otherwise `ERR_INVALID_STATE`)". A rejected booking mutates nothing.
    PRD 4 lists GET /api/converting-bookings ("List converting bookings with
    optional filters").

    Design: Difficulty/cross_entity_state_dependency/booking_blocked_when_work_shift_cancelled
    """
    customer, grade = setup_customer_and_grade()
    order, _ = create_accepted_order(customer["id"], grade["id"])
    order = advance_order_to_awaiting_converting(order["id"], grade["id"], outs=3)

    die_shift = create_work_shift(machine_code="DIE_CUTTER")
    validate_success(api.cancel_work_shift(die_shift["id"], production_planner_headers))
    res = api.create_converting_booking(
        create_converting_booking_payload(
            order["id"], die_shift["id"], start_minute=480, end_minute=600
        ),
        production_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    order_after = validate_success(
        api.get_box_order(order["id"], production_planner_headers)
    )
    assert order_after["status"] == "AWAITING_CONVERTING"
    _, meta = validate_paginated(
        api.list_converting_bookings(
            production_planner_headers, params={"box_order_id": order["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_slotted_order_rejected_on_die_cutter_shift(api, production_planner_headers):
    """PRD 3.5: "Machine compatibility forks with the order's `routing_type`: a
    `DIE_CUT` order books only onto a `DIE_CUTTER` shift, and a `SLOTTED` order
    books only onto an `FFG` shift — any other pairing is
    `ERR_MACHINE_TYPE_MISMATCH`."

    Design: Difficulty/non_linear_state_machine/box_order_routing_fork_die_cut_vs_slotted_divergent_branches
    """
    customer, grade = setup_customer_and_grade()
    order_d, _ = create_accepted_order(customer["id"], grade["id"])
    advance_order_to_awaiting_converting(order_d["id"], grade["id"], outs=3)
    order_s, _ = create_awaiting_sheet_feeder_order(customer["id"], grade["id"])

    die_shift = create_work_shift(machine_code="DIE_CUTTER")
    res = api.create_converting_booking(
        create_converting_booking_payload(
            order_s["id"], die_shift["id"], start_minute=480, end_minute=600
        ),
        production_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_MACHINE_TYPE_MISMATCH, expected_status=422)


def test_routing_fork_places_orders_on_matching_machines(
    api, production_planner_headers
):
    """PRD 3.5: "Machine compatibility forks with the order's `routing_type`: a
    `DIE_CUT` order books only onto a `DIE_CUTTER` shift, and a `SLOTTED` order
    books only onto an `FFG` shift — any other pairing is
    `ERR_MACHINE_TYPE_MISMATCH`."
    PRD 3.5: "A created booking lands in `QUEUED`, its order moves to
    `DIE_CUT_QUEUED` or `SLOTTED_QUEUED` according to `routing_type`, the shift
    rollup recomputes, and the order's `version` increments."

    Design: Difficulty/non_linear_state_machine/box_order_routing_fork_die_cut_vs_slotted_divergent_branches
    """
    customer, grade = setup_customer_and_grade()
    order_d, _ = create_accepted_order(customer["id"], grade["id"])
    order_d = advance_order_to_awaiting_converting(
        order_d["id"], grade["id"], outs=3
    )
    order_s, _ = create_awaiting_sheet_feeder_order(customer["id"], grade["id"])

    die_shift = create_work_shift(machine_code="DIE_CUTTER")
    ffg_shift = create_work_shift(machine_code="FFG")

    booking_d = validate_success(
        api.create_converting_booking(
            create_converting_booking_payload(
                order_d["id"], die_shift["id"], start_minute=480, end_minute=600
            ),
            production_planner_headers,
        ),
        201,
    )
    assert booking_d["work_shift_id"] == die_shift["id"]
    assert booking_d["ink_colors"] == ["BLACK", "RED"]
    order_d_after = validate_success(
        api.get_box_order(order_d["id"], production_planner_headers)
    )
    assert order_d_after["status"] == "DIE_CUT_QUEUED"

    booking_s = validate_success(
        api.create_converting_booking(
            create_converting_booking_payload(
                order_s["id"], ffg_shift["id"], start_minute=480, end_minute=600
            ),
            production_planner_headers,
        ),
        201,
    )
    assert booking_s["work_shift_id"] == ffg_shift["id"]
    assert booking_s["ink_colors"] == ["BLACK"]
    order_s_after = validate_success(
        api.get_box_order(order_s["id"], production_planner_headers)
    )
    assert order_s_after["status"] == "SLOTTED_QUEUED"


def test_sheet_feeder_order_skips_corrugator_via_mark_sheets_received(
    api, production_planner_headers
):
    """PRD 3.5: "A `SHEET_FEEDER` order skips it entirely: purchased sheets
    arrive pre-combined, and when the feeder delivers, a `ProductionPlanner`
    marks sheets received on an `ACCEPTED` order whose `board_source` is
    `SHEET_FEEDER` (an `INTERNAL` order on this operation is rejected with
    `ERR_BOARD_SOURCE_MISMATCH`; a non-`ACCEPTED` order with
    `ERR_INVALID_STATE`). The order moves `ACCEPTED → AWAITING_CONVERTING` and
    its `version` increments."

    Design: Corner/state_machines/sheet_feeder_order_bypasses_corrugator
    """
    customer, grade = setup_customer_and_grade()
    # Quote math pinned at acceptance (SLOTTED 30x40 qty 4000, 1 ink, LOCAL):
    # area 8.3333, billable 33.3332, rate 91.50
    order, quote = create_awaiting_sheet_feeder_order(
        customer["id"], grade["id"], unit_price=90.00
    )
    assert order["status"] == "AWAITING_CONVERTING"
    assert order["corrugator_run_id"] is None

    assert_msf(quote["billable_msf"], 33.3332)
    assert_money(quote["merchandise_total_dollars"], 3049.99)  # 33.3332 * 91.50
    assert_money(quote["freight_charge_dollars"], 600.00)  # 33.3332 * 18.00
    assert_money(quote["quote_total_dollars"], 3649.99)


def test_overrun_band_upper_bound_inclusive(api, production_planner_headers):
    """PRD 3.5: "the planner supplies `produced_qty`, which must fall within
    the inclusive band from the ordered `quantity` times 0.90 rounded down to
    the nearest integer, up to the ordered `quantity` times 1.10 rounded up to
    the nearest integer — a 900–1100 band on a 1000-box order. A quantity
    outside the band rejects with `ERR_OVERRUN_TOLERANCE_EXCEEDED`."

    Design: Corner/calculations/overrun_tolerance_inclusive_band
    """
    customer, grade = setup_customer_and_grade()
    order, _ = create_accepted_order(customer["id"], grade["id"])  # qty 2000
    order = advance_order_to_awaiting_converting(order["id"], grade["id"], outs=3)
    booking, _ = book_order(order)
    validate_success(
        api.start_converting_booking(booking["id"], production_planner_headers)
    )

    over = api.complete_converting_booking(
        booking["id"], {"produced_qty": 2201}, production_planner_headers
    )
    validate_error(
        over, ApiErrorId.ERR_OVERRUN_TOLERANCE_EXCEEDED, expected_status=422
    )
    booking_after = validate_success(
        api.get_converting_booking(booking["id"], production_planner_headers)
    )
    assert booking_after["status"] == "RUNNING"

    at_bound = api.complete_converting_booking(
        booking["id"], {"produced_qty": 2200}, production_planner_headers
    )
    completed = validate_success(at_bound)
    assert completed["status"] == "COMPLETED"
    order_after = validate_success(
        api.get_box_order(order["id"], production_planner_headers)
    )
    assert order_after["status"] == "PRODUCED"
    assert order_after["produced_qty"] == 2200


def test_booking_machine_mismatch_precedes_window_check(
    api, production_planner_headers
):
    """PRD 2.7: "When a request trips multiple rules, the first applicable rule
    by the following priority order determines the error."
    PRD 2.7: "General business constraints are sixth: well-formedness
    (`ERR_INVALID_REQUEST`), quantity ranges (`ERR_INVALID_QUANTITY`),
    supplier-name consistency (`ERR_SUPPLIER_REQUIRED`), board-source
    consistency (`ERR_BOARD_SOURCE_MISMATCH`), grade-code uniqueness
    (`ERR_DUPLICATE_CODE`), machine compatibility (`ERR_MACHINE_TYPE_MISMATCH`),
    order-grade equality (`ERR_ORDER_GRADE_MISMATCH`), trim-width fit
    (`ERR_TRIM_WIDTH_EXCEEDS_WEB`), trim-waste at completion
    (`ERR_TRIM_WASTE_EXCESSIVE`), overrun tolerance
    (`ERR_OVERRUN_TOLERANCE_EXCEEDED`), and claim self-adjudication
    (`ERR_SOD_CLAIM_SELF_ADJUDICATION`)."
    PRD 2.7: "Temporal rules are eighth: window containment
    (`ERR_OUTSIDE_SHIFT_WINDOW`), run overlap (`ERR_RUN_WINDOW_OVERLAP`),
    booking changeover (`ERR_BOOKING_CHANGEOVER_CONFLICT`), and quote expiry
    (`ERR_QUOTE_EXPIRED`)."
    PRD 3.5: "a `DIE_CUT` order books only onto a `DIE_CUTTER` shift, and a
    `SLOTTED` order books only onto an `FFG` shift — any other pairing is
    `ERR_MACHINE_TYPE_MISMATCH`."

    Design: Corner/validations/booking_machine_mismatch_beats_outside_window
    """
    customer, grade = setup_customer_and_grade()
    order_s, _ = create_awaiting_sheet_feeder_order(
        customer["id"], grade["id"], ink_colors=[]
    )
    corr_shift = create_work_shift(machine_code="CORRUGATOR")
    res = api.create_converting_booking(
        create_converting_booking_payload(
            order_s["id"], corr_shift["id"], start_minute=0, end_minute=10
        ),
        production_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_MACHINE_TYPE_MISMATCH, expected_status=422)
    order_after = validate_success(
        api.get_box_order(order_s["id"], production_planner_headers)
    )
    assert order_after["status"] == "AWAITING_CONVERTING"


def test_order_cancel_from_die_cut_queued_cancels_booking_and_frees_minutes(
    api, sales_rep_headers, production_planner_headers
):
    """PRD 3.6: "If the order was `DIE_CUT_QUEUED` or `SLOTTED_QUEUED`, its
    `QUEUED` booking is cancelled and that booking's shift rollup recomputes."
    PRD 3.4: "The shift's `scheduled_minutes` is the sum of window lengths
    (`end_minute` minus `start_minute`) over its corrugator runs in `SCHEDULED`
    or `COMPLETED` status plus its converting bookings in `QUEUED`, `RUNNING`,
    or `COMPLETED` status; cancelled runs and bookings contribute nothing".

    Design: Corner/state_machines/order_cancel_from_die_cut_queued_cancels_booking_and_frees_minutes
    """
    customer, grade = setup_customer_and_grade()
    order, _ = create_accepted_order(customer["id"], grade["id"])
    order = advance_order_to_awaiting_converting(order["id"], grade["id"], outs=3)
    booking, die_shift = book_order(order)

    shift_mid = validate_success(
        api.get_work_shift(die_shift["id"], production_planner_headers)
    )
    assert shift_mid["scheduled_minutes"] == 120

    cancelled = validate_success(
        api.cancel_box_order(order["id"], sales_rep_headers)
    )
    assert cancelled["status"] == "CANCELLED"

    booking_after = validate_success(
        api.get_converting_booking(booking["id"], production_planner_headers)
    )
    assert booking_after["status"] == "CANCELLED"

    shift_after = validate_success(
        api.get_work_shift(die_shift["id"], production_planner_headers)
    )
    assert shift_after["scheduled_minutes"] == 0
    assert shift_after["available_minutes"] == 480
