"""Pen occupancy, drover crews, booked moves and the completion cascade."""

from test_helpers import (
    ApiErrorId,
    YARD_OPERATOR,
    assert_same_instant,
    assign_pen,
    book_pen_move,
    check_in_consignment,
    create_consignment,
    create_crew,
    create_lot,
    create_pen,
    create_pen_move_payload,
    open_weigh_ticket,
    read_consignment,
    read_crew,
    read_lot,
    read_pen,
    read_pen_move,
    read_weigh_ticket,
    report_loss,
    set_crew_duty,
    set_pen_move_status,
    set_pen_status,
    setup_checked_in_consignment,
    setup_yard,
    validate_error,
    validate_paginated,
    validate_success,
)


def _pen_capacity_scenario():
    """A 12-head pen holding lots of 10 and 2 head, with a 5-head lot waiting."""
    scn = setup_yard(pen_capacity=12)
    scn.consignment = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=17
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot_a = create_lot(scn.consignment["id"], head_count=10)
    scn.lot_c = create_lot(
        scn.consignment["id"],
        head_count=2,
        livestock_class="CALF",
        bid_basis="PER_HEAD",
        opening_bid=40.00,
        reserve_price=45.00,
    )
    scn.lot_b = create_lot(
        scn.consignment["id"], head_count=5, livestock_class="FEEDER_HEIFER"
    )
    assign_pen(scn.lot_a["id"], scn.pen["id"])
    assign_pen(scn.lot_c["id"], scn.pen["id"])
    return scn


def test_pen_admits_lots_up_to_capacity_and_refuses_the_head_that_would_bust_it(api):
    """PRD §2.5: "A pen admits a lot when the resulting head count is less than or
    equal to capacity."
    PRD §3.5: "and the pen's `current_head` plus the lot's `head_count` must be less
    than or equal to the pen's `head_capacity`, or the answer is
    `ERR_PEN_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/pen_aggregate_head_capacity_over_half_open_occupancy_interval
    """
    scn = _pen_capacity_scenario()

    pen = read_pen(scn.pen["id"])
    assert pen["current_head"] == 12, "10 + 2 lands exactly on capacity and is admitted"

    response = api.assign_pen(scn.lot_b["id"], {"pen_id": scn.pen["id"]}, YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_PEN_CAPACITY_EXCEEDED.value)

    assert read_lot(scn.lot_b["id"])["pen_id"] is None
    assert read_pen(scn.pen["id"])["current_head"] == 12


def test_head_leaving_a_pen_frees_capacity_at_the_very_same_instant(api):
    """PRD §2.10: "The occupancy interval is half-open from `penned_at` up to but not
    including `released_at`, so a lot released at a given instant frees capacity for a
    lot penned at that same instant."
    PRD §2.10: "A pen's `current_head` equals the total `head_count` of the lots whose
    `pen_id` is that pen, whose `sale_status` is `PENNED`, `READY`, `IN_RING`, `SOLD`
    or `NO_SALE`, and whose `custody_status` is `BARN` or `BUYER_PEN`; and
    `current_head` never exceeds the pen's `head_capacity`."

    Design: Difficulty/resource_temporal_overlap/pen_aggregate_head_capacity_over_half_open_occupancy_interval
    """
    scn = _pen_capacity_scenario()

    report_loss(
        scn.consignment["id"],
        scn.consignor["id"],
        loss_type="WITHDRAWN",
        head=10,
        lot_id=scn.lot_a["id"],
    )
    assert read_lot(scn.lot_a["id"])["sale_status"] == "WITHDRAWN"
    assert read_pen(scn.pen["id"])["current_head"] == 2

    data = validate_success(
        api.assign_pen(scn.lot_b["id"], {"pen_id": scn.pen["id"]}, YARD_OPERATOR)
    )
    assert data["pen_id"] == scn.pen["id"]

    pen = read_pen(scn.pen["id"])
    assert pen["current_head"] == 7
    assert pen["status"] == "OCCUPIED"
    assert read_consignment(scn.consignment["id"])["head_balance_ok"] is True


def _crew_booking_scenario():
    """One on-duty crew already booked 09:00–09:30, so blocked until 09:45."""
    scn = setup_yard(pen_capacity=60)
    scn.pen_two = create_pen(pen_code="P-02", head_capacity=60)
    scn.crew = create_crew(on_duty=True)
    scn.consignment = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=15
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot_a = create_lot(scn.consignment["id"], head_count=10)
    scn.lot_b = create_lot(
        scn.consignment["id"], head_count=5, livestock_class="FEEDER_HEIFER"
    )
    assign_pen(scn.lot_a["id"], scn.pen["id"])
    assign_pen(scn.lot_b["id"], scn.pen["id"])
    scn.move_one = book_pen_move(
        scn.lot_a["id"], scn.pen_two["id"], scn.crew["id"], "2026-06-01T09:00:00Z"
    )
    return scn


def test_crew_booking_one_minute_inside_the_cool_down_is_refused(api):
    """PRD §3.5: "Each such move blocks the crew until fifteen minutes after its own
    `scheduled_end_at`."
    PRD §3.5: "The new move conflicts when its start is earlier than that blocked-until
    instant **and** its end — thirty minutes after its start — is later than the
    existing move's `scheduled_start_at`."
    PRD §3.5: "A move that starts exactly at the blocked-until instant is therefore
    accepted, while one starting a minute earlier is refused with
    `ERR_CREW_MOVE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/crew_booking_closed_window_with_trailing_cooldown_buffer
    """
    scn = _crew_booking_scenario()

    assert_same_instant(
        read_pen_move(scn.move_one["id"])["scheduled_end_at"],
        "2026-06-01T09:30:00Z",
        "a booked move runs thirty minutes:",
    )

    response = api.create_pen_move(
        create_pen_move_payload(
            scn.lot_b["id"], scn.pen_two["id"], scn.crew["id"], "2026-06-01T09:44:00Z"
        ),
        YARD_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_CREW_MOVE_OVERLAP.value)


def test_crew_booking_exactly_at_the_blocked_until_instant_is_accepted(api):
    """PRD §3.5: "A move that starts exactly at the blocked-until instant is therefore
    accepted, while one starting a minute earlier is refused with
    `ERR_CREW_MOVE_OVERLAP`."
    PRD §3.5: "the server copies `from_pen_id` from the lot's current pen and
    `head_moved` from the lot's head count, and derives `scheduled_end_at` as thirty
    minutes after the scheduled start."

    Design: Difficulty/resource_temporal_overlap/crew_booking_closed_window_with_trailing_cooldown_buffer
    """
    scn = _crew_booking_scenario()

    data = validate_success(
        api.create_pen_move(
            create_pen_move_payload(
                scn.lot_b["id"], scn.pen_two["id"], scn.crew["id"], "2026-06-01T09:45:00Z"
            ),
            YARD_OPERATOR,
        ),
        201,
    )
    assert data["status"] == "REQUESTED"
    assert_same_instant(
        data["scheduled_end_at"],
        "2026-06-01T10:15:00Z",
        "the second booking also runs thirty minutes:",
    )

    _, meta = validate_paginated(
        api.list_pen_moves(YARD_OPERATOR, params={"crew_id": scn.crew["id"]})
    )
    assert meta["total_count"] == 2


def _off_duty_crew_scenario():
    scn = setup_yard(pen_capacity=60)
    scn.pen_two = create_pen(pen_code="P-02", head_capacity=60)
    scn.crew = create_crew(on_duty=False)
    scn.consignment = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=10
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot = create_lot(scn.consignment["id"], head_count=10)
    assign_pen(scn.lot["id"], scn.pen["id"])
    return scn


def test_move_booked_on_an_off_duty_crew_is_refused(api):
    """PRD §3.5: "The crew must be `ON_DUTY` at the moment of booking or the answer is
    `ERR_CREW_OFF_DUTY`."
    PRD §3.1: "A `YardOperator` registers a crew with its `crew_code` and a
    `member_count` of at least one; a new crew is `OFF_DUTY` with no
    `last_move_completed_at` yet recorded."

    Design: Difficulty/cross_entity_state_dependency/pen_move_creation_depends_on_drover_crew_duty_state
    """
    scn = _off_duty_crew_scenario()

    response = api.create_pen_move(
        create_pen_move_payload(
            scn.lot["id"], scn.pen_two["id"], scn.crew["id"], "2026-06-01T09:00:00Z"
        ),
        YARD_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_CREW_OFF_DUTY.value)

    _, meta = validate_paginated(
        api.list_pen_moves(YARD_OPERATOR, params={"crew_id": scn.crew["id"]})
    )
    assert meta["total_count"] == 0


def test_the_identical_move_is_accepted_once_the_crew_clocks_on(api):
    """PRD §3.1: "Duty standing cycles freely: `OFF_DUTY → ON_DUTY`, `ON_DUTY →
    ON_BREAK`, `ON_BREAK → ON_DUTY`, `ON_DUTY → OFF_DUTY` and `ON_BREAK → OFF_DUTY`
    are all legal, each requested by naming the target in `to_status`."
    PRD §3.5: "the server copies `from_pen_id` from the lot's current pen and
    `head_moved` from the lot's head count, and derives `scheduled_end_at` as thirty
    minutes after the scheduled start."
    PRD §3.5: "A move opens in `REQUESTED`."

    Design: Difficulty/cross_entity_state_dependency/pen_move_creation_depends_on_drover_crew_duty_state
    """
    scn = _off_duty_crew_scenario()
    set_crew_duty(scn.crew["id"], "ON_DUTY")
    assert read_crew(scn.crew["id"])["duty_status"] == "ON_DUTY"

    data = validate_success(
        api.create_pen_move(
            create_pen_move_payload(
                scn.lot["id"], scn.pen_two["id"], scn.crew["id"], "2026-06-01T09:00:00Z"
            ),
            YARD_OPERATOR,
        ),
        201,
    )
    assert data["status"] == "REQUESTED"
    assert data["from_pen_id"] == scn.pen["id"]
    assert data["head_moved"] == 10
    assert_same_instant(
        data["scheduled_end_at"],
        "2026-06-01T09:30:00Z",
        "scheduled_end_at is thirty minutes after the scheduled start:",
    )


def _in_progress_move_scenario():
    """A 10-head lot in P-01 with an OPEN draft and an in-progress move to P-02."""
    scn = setup_yard(pen_capacity=60)
    scn.pen_two = create_pen(pen_code="P-02", head_capacity=60)
    scn.crew = create_crew(on_duty=True)
    scn.consignment = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=10
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot = create_lot(scn.consignment["id"], head_count=10)
    assign_pen(scn.lot["id"], scn.pen["id"])
    scn.ticket = open_weigh_ticket(
        scn.lot["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200
    )
    scn.move = book_pen_move(
        scn.lot["id"], scn.pen_two["id"], scn.crew["id"], "2026-06-01T09:00:00Z"
    )
    set_pen_move_status(scn.move["id"], "IN_PROGRESS")
    return scn


def test_completing_a_move_stamps_the_crew_and_walks_the_lot_to_its_new_pen(api):
    """PRD §3.5: "Completing it, `IN_PROGRESS → COMPLETED`, runs a three-hop cascade:
    first `completed_at` is stamped from the logical clock and the crew's
    `last_move_completed_at` is set to the same instant; that in turn changes the lot's
    `pen_id` from the origin pen to the destination pen and resets `penned_at` to the
    current clock; and that in turn makes both the origin and destination pens
    recompute `current_head` and flip between `AVAILABLE` and `OCCUPIED` as their
    occupancy dictates, while every `OPEN` weigh ticket on the moved lot transitions
    to `VOIDED`."

    Design: Difficulty/transitive_cascade/pen_move_completion_three_hop_cascade_to_pens_and_open_ticket
    """
    scn = _in_progress_move_scenario()

    data = validate_success(
        api.set_pen_move_status(scn.move["id"], {"to_status": "COMPLETED"}, YARD_OPERATOR)
    )
    assert data["status"] == "COMPLETED"
    assert data["completed_at"] is not None

    crew = read_crew(scn.crew["id"])
    assert crew["last_move_completed_at"] is not None
    assert_same_instant(
        crew["last_move_completed_at"],
        data["completed_at"],
        "the crew's last_move_completed_at is the move's completed_at:",
    )

    assert read_lot(scn.lot["id"])["pen_id"] == scn.pen_two["id"]


def test_completing_a_move_repens_both_pens_and_voids_the_open_draft(api):
    """PRD §3.4: "There is one system-driven void as well: completing a pen move on a
    lot voids every `OPEN` ticket on it, on the theory that a draft interrupted by a
    walk across the yard is no longer the draft that was opened."
    PRD §3.1: "Occupancy drives the pen's status automatically: the first lot to land
    in an empty pen flips it `AVAILABLE → OCCUPIED`, and the departure of the last lot
    — by a completed move away, by withdrawal, or by release at the gate — flips it
    `OCCUPIED → AVAILABLE`."
    PRD §3.4: "If no captured ticket remains on the lot, `settle_weight_lb` is null."

    Design: Difficulty/transitive_cascade/pen_move_completion_three_hop_cascade_to_pens_and_open_ticket
    """
    scn = _in_progress_move_scenario()
    set_pen_move_status(scn.move["id"], "COMPLETED")

    origin = read_pen(scn.pen["id"])
    assert origin["current_head"] == 0
    assert origin["status"] == "AVAILABLE"

    destination = read_pen(scn.pen_two["id"])
    assert destination["current_head"] == 10
    assert destination["status"] == "OCCUPIED"

    assert read_weigh_ticket(scn.ticket["id"])["status"] == "VOIDED"
    lot = read_lot(scn.lot["id"])
    assert lot["settle_weight_lb"] is None
    assert lot["weight_class"] == "NONE"


def test_out_of_service_pen_is_not_a_legal_destination_until_returned_to_service(api):
    """PRD §3.1: "A pen that is out of service is not a legal destination for either a
    pen assignment or a pen move, and an attempt to use one is refused with
    `ERR_INVALID_STATE`."
    PRD §3.1: "An administrator may also take a pen out of the rotation entirely,
    `AVAILABLE → OUT_OF_SERVICE`, but only while it stands empty, and may return it
    `OUT_OF_SERVICE → AVAILABLE` at any time."

    Design: Corner/state_machines/corner_assign_pen_to_out_of_service_pen_is_rejected
    """
    scn = setup_checked_in_consignment(head_received=10)
    set_pen_status(scn.pen["id"], "OUT_OF_SERVICE")
    lot = create_lot(scn.consignment["id"], head_count=10)

    response = api.assign_pen(lot["id"], {"pen_id": scn.pen["id"]}, YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert set_pen_status(scn.pen["id"], "AVAILABLE")["status"] == "AVAILABLE"

    data = validate_success(api.assign_pen(lot["id"], {"pen_id": scn.pen["id"]}, YARD_OPERATOR))
    assert data["sale_status"] == "PENNED"

    pen = read_pen(scn.pen["id"])
    assert pen["current_head"] == 10
    assert pen["status"] == "OCCUPIED"


def test_pen_rigged_for_another_species_refuses_the_lot(api):
    """PRD §3.5: "Four conditions must hold and they are checked in ladder order: the
    destination pen's `species_class` must equal the species class of the lot's
    consignment, or the answer is `ERR_PEN_SPECIES_MISMATCH`"

    Design: Corner/validations/corner_assign_pen_of_wrong_species_class_is_rejected
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False)
    hog_pen = create_pen(pen_code="P-HOG", species_class="SWINE", head_capacity=60)
    lot = create_lot(scn.consignment["id"], head_count=10)

    response = api.assign_pen(lot["id"], {"pen_id": hog_pen["id"]}, YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_PEN_SPECIES_MISMATCH.value)

    fresh = read_lot(lot["id"])
    assert fresh["pen_id"] is None
    assert fresh["sale_status"] == "DRAFT"
    assert read_pen(hog_pen["id"])["current_head"] == 0
