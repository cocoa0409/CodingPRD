"""Load building, the oversize permit envelope, dispatch, delivery and erection."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_shipment_line,
    apply_permit,
    assert_exact_sum,
    assert_project_counters,
    assert_shipment,
    assert_shipment_line,
    assert_slot_occupancy,
    assert_whole_cents,
    create_issued_permit,
    create_project,
    create_shipment,
    create_shipment_line_payload,
    dispatch_shipment,
    issue_permit,
    list_shipment_lines,
    make_project_owner_headers,
    open_ncr,
    read_haul_permit,
    read_piece,
    read_project,
    read_shipment,
    read_shipment_line,
    read_yard_slot,
    set_clock,
    setup_production_line,
    setup_yarded_load,
    validate_error,
    validate_paginated,
    validate_success,
)

FOREMAN = TEST_USERS["yard_foreman_headers"]
PERMITS = TEST_USERS["permit_coordinator_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]

LEGAL_PIECE = {
    "length_ft": 53.00,
    "width_ft": 8.50,
    "height_ft": 13.50,
    "weight_lb": 22000,
    "concrete_volume_cy": 8.00,
}


def test_each_line_surcharge_is_rounded_before_the_fee_is_summed(api):
    """PRD §3.8: "Those three overhangs are priced at 12.75 dollars per foot of
    width, 21.40 dollars per foot of height and 3.66 dollars per foot of length;
    the three products are added, converted from dollars to cents by multiplying
    by 100, and rounded half up to whole cents to give that line's
    `line_surcharge_cents`. The rounding order is pinned: each line is rounded to
    whole cents first and the rounded lines are then summed. Summing the raw
    dollar amounts and rounding once at the end is the wrong reading and differs
    by whole cents on real loads."
    PRD §3.8: "`permit_fee_cents` is finally the permit base of 8500 cents, plus
    the sum of the rounded `line_surcharge_cents` of every line, plus 27500 cents
    for each escort the linked permit mandates in its `escort_count` — and the
    escort count is taken as zero when `haul_permit_id` is null."

    Design: Difficulty/combinatorial_formula/permit_fee_rounds_each_line_before_summing
    """
    ctx = setup_yarded_load(
        piece_specs=[{}, {}],
        slot_overrides={"capacity_weight_lb": 120000, "max_stack_count": 3},
        permit_overrides={"escort_count": 1},
        shipment_overrides={"scheduled_departure": "2026-08-05T13:00:00Z"},
    )
    first, second = ctx["pieces"]

    line_one = validate_success(
        api.create_shipment_line(
            ctx["shipment"]["id"], create_shipment_line_payload(second["id"], 1), FOREMAN
        ),
        201,
    )
    line_two = validate_success(
        api.create_shipment_line(
            ctx["shipment"]["id"], create_shipment_line_payload(first["id"], 2), FOREMAN
        ),
        201,
    )

    assert_shipment_line(line_one)
    assert_whole_cents(
        line_one["line_surcharge_cents"], 1740, "shipment_line.line_surcharge_cents"
    )
    assert_whole_cents(
        line_two["line_surcharge_cents"], 1740, "shipment_line.line_surcharge_cents"
    )

    shipment = read_shipment(ctx["shipment"]["id"])
    assert_whole_cents(shipment["permit_fee_cents"], 39480, "shipment.permit_fee_cents")
    assert shipment["permit_fee_cents"] != 39479, (
        "39479 cents is what summing the raw 1739.60 cent amounts before rounding gives"
    )


def test_load_metrics_grow_with_every_line(api):
    """PRD §3.8: "`gross_weight_lb` is the tractor tare of 32000 pounds plus the
    exact sum of `weight_lb` over the pieces of every line, with no rounding.
    `max_width_ft`, `max_height_ft` and `max_length_ft` are the largest
    `width_ft`, `height_ft` and `length_ft` among those pieces, and each is 0
    when the shipment has no lines."
    PRD §3.8: "`is_oversize` is true when `max_width_ft` is greater than 8.50
    feet, or `max_height_ft` is greater than 13.50 feet, or `max_length_ft` is
    greater than 53.00 feet, or `gross_weight_lb` is greater than 80000 pounds."

    Design: Difficulty/combinatorial_formula/permit_fee_rounds_each_line_before_summing
    """
    ctx = setup_yarded_load(
        piece_specs=[{}, {}],
        slot_overrides={"capacity_weight_lb": 120000, "max_stack_count": 3},
        permit_overrides={"escort_count": 1},
        shipment_overrides={"scheduled_departure": "2026-08-05T13:00:00Z"},
    )
    first, second = ctx["pieces"]
    empty = read_shipment(ctx["shipment"]["id"])
    assert empty["max_width_ft"] == 0 and empty["line_count"] == 0

    add_shipment_line(ctx["shipment"]["id"], second["id"], 1)
    add_shipment_line(ctx["shipment"]["id"], first["id"], 2)

    shipment = read_shipment(ctx["shipment"]["id"])
    assert_shipment(shipment)
    assert_exact_sum(shipment["gross_weight_lb"], 128400, "shipment.gross_weight_lb")
    assert shipment["is_oversize"] is True
    assert shipment["max_width_ft"] == 9.50
    assert shipment["line_count"] == 2


def test_load_exactly_on_the_legal_width_dispatches_without_a_permit(api):
    """PRD §3.8: "`is_oversize` is true when `max_width_ft` is greater than 8.50
    feet, or `max_height_ft` is greater than 13.50 feet, or `max_length_ft` is
    greater than 53.00 feet, or `gross_weight_lb` is greater than 80000 pounds.
    Every one of those four comparisons is strictly greater: a piece measuring
    exactly 8.50 feet wide is legal and needs no permit, while 8.51 feet does."
    PRD §3.8: "While `is_oversize` is false, `permit_fee_cents` is 0 and every
    line's `line_surcharge_cents` is 0, even when a permit happens to be linked —
    a legal load never accrues a fee."

    Design: Difficulty/boundary_precision_check/oversize_width_strictly_above_legal_limit_requires_permit
    """
    ctx = setup_production_line(
        stage="yarded",
        piece_specs=[
            {**LEGAL_PIECE, "piece_mark": "EDGE-A"},
            {**LEGAL_PIECE, "piece_mark": "EDGE-B", "width_ft": 8.51},
        ],
        slot_overrides={"capacity_weight_lb": 120000, "max_stack_count": 3},
    )
    legal_piece, wide_piece = ctx["pieces"]
    shipment = create_shipment(
        ctx["project"]["id"], scheduled_departure="2026-08-04T13:00:00Z"
    )
    add_shipment_line(shipment["id"], legal_piece["id"], 1)

    dispatched = validate_success(api.dispatch_shipment(shipment["id"], FOREMAN))

    assert read_piece(legal_piece["id"])["requires_haul_permit"] is False
    assert read_piece(wide_piece["id"])["requires_haul_permit"] is True
    assert dispatched["max_width_ft"] == 8.50
    assert dispatched["is_oversize"] is False
    assert_whole_cents(dispatched["permit_fee_cents"], 0, "shipment.permit_fee_cents")
    assert_exact_sum(dispatched["gross_weight_lb"], 54000, "shipment.gross_weight_lb")
    assert dispatched["status"] == "DISPATCHED"


def test_one_hundredth_of_a_foot_over_legal_width_requires_a_permit(api):
    """PRD §3.8: "Last the permit envelope gates: an oversize load with
    `haul_permit_id` null is rejected with `ERR_PERMIT_REQUIRED`; a load whose
    `max_width_ft`, `max_height_ft` or `max_length_ft` exceeds the corresponding
    permit maximum is rejected with `ERR_PERMIT_ENVELOPE_EXCEEDED`; and a load
    whose `gross_weight_lb` exceeds the permit's `max_gross_weight_lb` is
    rejected with `ERR_PERMIT_WEIGHT_EXCEEDED`."
    PRD §3.8: "Every one of those four comparisons is strictly greater: a piece
    measuring exactly 8.50 feet wide is legal and needs no permit, while 8.51
    feet does."

    Design: Difficulty/boundary_precision_check/oversize_width_strictly_above_legal_limit_requires_permit
    """
    ctx = setup_production_line(
        stage="yarded",
        piece_specs=[
            {**LEGAL_PIECE, "piece_mark": "EDGE-A"},
            {**LEGAL_PIECE, "piece_mark": "EDGE-B", "width_ft": 8.51},
        ],
        slot_overrides={"capacity_weight_lb": 120000, "max_stack_count": 3},
    )
    wide_piece = ctx["pieces"][1]
    shipment = create_shipment(
        ctx["project"]["id"], scheduled_departure="2026-08-04T15:00:00Z"
    )
    add_shipment_line(shipment["id"], wide_piece["id"], 1)

    response = api.dispatch_shipment(shipment["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_PERMIT_REQUIRED.value, 422)

    reread = read_shipment(shipment["id"])
    assert reread["max_width_ft"] == 8.51
    assert reread["is_oversize"] is True
    assert reread["status"] == "BUILDING"


def test_dispatch_is_refused_while_the_permit_is_only_applied(api):
    """PRD §3.8: "Separately, and earlier in the ladder of §2.8, an oversize load
    whose linked permit is not in `ISSUED` is refused with
    `ERR_PERMIT_NOT_ISSUED`."
    PRD §3.8: "A new permit begins in `APPLIED`. Issuing it moves it `APPLIED →
    ISSUED`, and an issue attempt from any other status is refused with
    `ERR_HAUL_PERMIT_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_gated_on_haul_permit_issued_state
    """
    ctx = setup_yarded_load(piece_specs=[{}], issue=False)
    add_shipment_line(ctx["shipment"]["id"], ctx["pieces"][0]["id"], 1)

    response = api.dispatch_shipment(ctx["shipment"]["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_PERMIT_NOT_ISSUED.value, 409)

    assert read_shipment(ctx["shipment"]["id"])["status"] == "BUILDING"
    assert read_haul_permit(ctx["permit"]["id"])["status"] == "APPLIED"


def test_issuing_the_permit_lets_the_load_dispatch_and_consume_it(api):
    """PRD §3.8: "Separately, and earlier in the ladder of §2.8, an oversize load
    whose linked permit is not in `ISSUED` is refused with
    `ERR_PERMIT_NOT_ISSUED`. On success the linked permit moves `ISSUED →
    ACTIVE`."
    PRD §3.8: "**Delivering** the load moves the shipment `DISPATCHED →
    DELIVERED`, and delivery from any other status is refused with
    `ERR_SHIPMENT_INVALID_STATE`. Every piece carried on a line of the shipment
    moves `production_status` `LOADED → SHIPPED`, and the linked permit moves
    `ACTIVE → CONSUMED`."
    PRD §3.8: "`permit_fee_cents` is finally the permit base of 8500 cents, plus
    the sum of the rounded `line_surcharge_cents` of every line, plus 27500 cents
    for each escort the linked permit mandates in its `escort_count` — and the
    escort count is taken as zero when `haul_permit_id` is null."

    Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_gated_on_haul_permit_issued_state
    """
    ctx = setup_yarded_load(piece_specs=[{}], issue=False)
    add_shipment_line(ctx["shipment"]["id"], ctx["pieces"][0]["id"], 1)

    issued = issue_permit(ctx["permit"]["id"])
    assert issued["status"] == "ISSUED"

    dispatched = validate_success(api.dispatch_shipment(ctx["shipment"]["id"], FOREMAN))
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatched_at"].startswith("2026-08-03T06:00:00")
    assert read_haul_permit(ctx["permit"]["id"])["status"] == "ACTIVE"
    assert dispatched["is_oversize"] is True
    assert_whole_cents(dispatched["permit_fee_cents"], 37740, "shipment.permit_fee_cents")

    delivered = validate_success(api.deliver_shipment(ctx["shipment"]["id"], FOREMAN))
    assert delivered["status"] == "DELIVERED"
    assert read_haul_permit(ctx["permit"]["id"])["status"] == "CONSUMED"
    assert read_piece(ctx["pieces"][0]["id"])["production_status"] == "SHIPPED"


def test_permit_expiry_outranks_the_gross_weight_gate(api):
    """PRD §2.8: "When a request would fail more than one check, the response is
    decided by the **first** failing check in the following fixed order, and no
    later check runs."
    PRD §3.8: "First the permit's temporal window: when the load is oversize and a
    permit is linked, the logical clock must lie inside that permit's inclusive
    window from `valid_from` to `valid_to`. A permit whose `valid_to` has already
    passed is moved `ISSUED → EXPIRED` and the dispatch is rejected with
    `ERR_PERMIT_EXPIRED`."
    PRD §3.8: "and a load whose `gross_weight_lb` exceeds the permit's
    `max_gross_weight_lb` is rejected with `ERR_PERMIT_WEIGHT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/permit_expiry_beats_permit_gross_weight
    """
    ctx = setup_yarded_load(
        piece_specs=[{}, {}],
        slot_overrides={"capacity_weight_lb": 120000, "max_stack_count": 3},
        permit_overrides={
            "permit_number": "TN-9002",
            "max_gross_weight_lb": 100000,
            "valid_to": "2026-08-02T00:00:00Z",
        },
        shipment_overrides={"scheduled_departure": "2026-08-03T13:00:00Z"},
    )
    first, second = ctx["pieces"]
    add_shipment_line(ctx["shipment"]["id"], second["id"], 1)
    add_shipment_line(ctx["shipment"]["id"], first["id"], 2)
    assert read_shipment(ctx["shipment"]["id"])["gross_weight_lb"] == 128400

    response = api.dispatch_shipment(ctx["shipment"]["id"], FOREMAN)
    error = validate_error(response, ApiErrorId.ERR_PERMIT_EXPIRED.value, 422)

    assert error["error_id"] != ApiErrorId.ERR_PERMIT_WEIGHT_EXCEEDED.value, (
        "the load is 28400 lb over the permit, but the window gate is checked first"
    )


def test_expired_permit_moves_to_expired_and_leaves_the_load_building(api):
    """PRD §3.8: "A permit whose `valid_to` has already passed is moved `ISSUED →
    EXPIRED` and the dispatch is rejected with `ERR_PERMIT_EXPIRED`."
    PRD §3.8: "**Dispatching** the load moves the shipment `BUILDING →
    DISPATCHED` and stamps `dispatched_at`; dispatch from any other status is
    refused with `ERR_SHIPMENT_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/permit_expiry_beats_permit_gross_weight
    """
    ctx = setup_yarded_load(
        piece_specs=[{}, {}],
        slot_overrides={"capacity_weight_lb": 120000, "max_stack_count": 3},
        permit_overrides={
            "permit_number": "TN-9002",
            "max_gross_weight_lb": 100000,
            "valid_to": "2026-08-02T00:00:00Z",
        },
        shipment_overrides={"scheduled_departure": "2026-08-03T13:00:00Z"},
    )
    first, second = ctx["pieces"]
    add_shipment_line(ctx["shipment"]["id"], second["id"], 1)
    add_shipment_line(ctx["shipment"]["id"], first["id"], 2)

    validate_error(
        api.dispatch_shipment(ctx["shipment"]["id"], FOREMAN),
        ApiErrorId.ERR_PERMIT_EXPIRED.value,
        422,
    )

    assert read_haul_permit(ctx["permit"]["id"])["status"] == "EXPIRED"
    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["status"] == "BUILDING"
    assert shipment["dispatched_at"] is None


def test_envelope_and_weight_gates_fire_in_order(api):
    """PRD §3.8: "Last the permit envelope gates: an oversize load with
    `haul_permit_id` null is rejected with `ERR_PERMIT_REQUIRED`; a load whose
    `max_width_ft`, `max_height_ft` or `max_length_ft` exceeds the corresponding
    permit maximum is rejected with `ERR_PERMIT_ENVELOPE_EXCEEDED`; and a load
    whose `gross_weight_lb` exceeds the permit's `max_gross_weight_lb` is
    rejected with `ERR_PERMIT_WEIGHT_EXCEEDED`."
    PRD §3.8: "`permit_fee_cents` is finally the permit base of 8500 cents, plus
    the sum of the rounded `line_surcharge_cents` of every line, plus 27500 cents
    for each escort the linked permit mandates in its `escort_count` — and the
    escort count is taken as zero when `haul_permit_id` is null."

    Design: Corner/validations/permit_envelope_and_gross_weight_gates
    """
    ctx = setup_production_line(
        stage="yarded",
        piece_specs=[{}, {}, {}],
        slot_overrides={"capacity_weight_lb": 200000, "max_stack_count": 5},
    )
    narrow_permit = create_issued_permit(
        ctx["project"]["id"],
        permit_number="TN-NARROW",
        max_width_ft=9.00,
        max_gross_weight_lb=140000,
        escort_count=0,
    )
    light_permit = create_issued_permit(
        ctx["project"]["id"],
        permit_number="TN-LIGHT",
        max_width_ft=10.00,
        max_gross_weight_lb=100000,
        escort_count=0,
    )
    envelope_load = create_shipment(
        ctx["project"]["id"],
        scheduled_departure="2026-08-04T13:00:00Z",
        haul_permit_id=narrow_permit["id"],
    )
    weight_load = create_shipment(
        ctx["project"]["id"],
        scheduled_departure="2026-08-04T15:00:00Z",
        haul_permit_id=light_permit["id"],
    )
    add_shipment_line(envelope_load["id"], ctx["pieces"][0]["id"], 1)
    add_shipment_line(weight_load["id"], ctx["pieces"][2]["id"], 1)
    add_shipment_line(weight_load["id"], ctx["pieces"][1]["id"], 2)

    validate_error(
        api.dispatch_shipment(envelope_load["id"], FOREMAN),
        ApiErrorId.ERR_PERMIT_ENVELOPE_EXCEEDED.value,
        422,
    )
    validate_error(
        api.dispatch_shipment(weight_load["id"], FOREMAN),
        ApiErrorId.ERR_PERMIT_WEIGHT_EXCEEDED.value,
        422,
    )

    envelope = read_shipment(envelope_load["id"])
    assert envelope["max_width_ft"] == 9.50
    assert envelope["is_oversize"] is True
    assert_exact_sum(envelope["gross_weight_lb"], 80200, "shipment.gross_weight_lb")
    assert_whole_cents(envelope["permit_fee_cents"], 10240, "shipment.permit_fee_cents")

    heavy = read_shipment(weight_load["id"])
    assert_exact_sum(heavy["gross_weight_lb"], 128400, "shipment.gross_weight_lb")
    assert_whole_cents(heavy["permit_fee_cents"], 11980, "shipment.permit_fee_cents")

    for shipment in (envelope, heavy):
        assert shipment["status"] == "BUILDING"
        assert shipment["dispatched_at"] is None
    assert read_haul_permit(narrow_permit["id"])["status"] == "ISSUED"
    assert read_haul_permit(light_permit["id"])["status"] == "ISSUED"


def test_line_and_dispatch_composition_gates(api):
    """PRD §3.8: "The `YardForeman` names the `piece_id` and the 1-based
    `load_position`, which must be at least 1 and must be unique within the
    shipment; a repeat position is rejected with `ERR_DUPLICATE_LOAD_POSITION`."
    PRD §3.8: "And the piece's `project_id` must equal the shipment's
    `project_id`, or the request is rejected with `ERR_PIECE_PROJECT_MISMATCH`."
    PRD §3.8: "Next the load composition gates: a shipment with a `line_count` of
    0 is rejected with `ERR_EMPTY_LOAD`; and the lines taken in order of
    `load_position` ascending must carry strictly descending
    `erection_sequence_no`, so that the piece at position 1 — loaded first,
    buried deepest — carries the highest erection sequence number on the trailer,
    because it comes off last. Any pair that breaks that ordering is rejected
    with `ERR_ERECTION_SEQUENCE_VIOLATION`."

    Design: Corner/validations/shipment_line_and_dispatch_composition_gates
    """
    ctx = setup_production_line(
        stage="yarded",
        project_count=2,
        piece_specs=[
            {**LEGAL_PIECE, "piece_mark": "DT-101", "erection_sequence_no": 10},
            {**LEGAL_PIECE, "piece_mark": "DT-102", "erection_sequence_no": 20},
            {
                **LEGAL_PIECE,
                "piece_mark": "SD-301",
                "erection_sequence_no": 10,
                "project_index": 1,
            },
        ],
        slot_overrides={"capacity_weight_lb": 200000, "max_stack_count": 5},
    )
    own_first, own_second, other_project_piece = ctx["pieces"]
    ours = create_shipment(ctx["projects"][0]["id"], scheduled_departure="2026-08-04T13:00:00Z")
    theirs = create_shipment(
        ctx["projects"][1]["id"], scheduled_departure="2026-08-04T15:00:00Z"
    )

    line_one = add_shipment_line(ours["id"], own_first["id"], 1)

    validate_error(
        api.create_shipment_line(
            ours["id"], create_shipment_line_payload(own_second["id"], 1), FOREMAN
        ),
        ApiErrorId.ERR_DUPLICATE_LOAD_POSITION.value,
        409,
    )
    validate_error(
        api.create_shipment_line(
            ours["id"], create_shipment_line_payload(other_project_piece["id"], 2), FOREMAN
        ),
        ApiErrorId.ERR_PIECE_PROJECT_MISMATCH.value,
        409,
    )
    validate_error(
        api.dispatch_shipment(theirs["id"], FOREMAN), ApiErrorId.ERR_EMPTY_LOAD.value, 422
    )

    line_two = add_shipment_line(ours["id"], own_second["id"], 2)
    validate_error(
        api.dispatch_shipment(ours["id"], FOREMAN),
        ApiErrorId.ERR_ERECTION_SEQUENCE_VIOLATION.value,
        422,
    )

    shipment = read_shipment(ours["id"])
    assert shipment["line_count"] == 2
    assert shipment["status"] == "BUILDING"
    assert_exact_sum(shipment["gross_weight_lb"], 76000, "shipment.gross_weight_lb")
    assert shipment["is_oversize"] is False
    assert_whole_cents(shipment["permit_fee_cents"], 0, "shipment.permit_fee_cents")
    assert read_piece(other_project_piece["id"])["production_status"] == "YARDED"
    assert read_shipment_line(ours["id"], line_one["id"])["line_surcharge_cents"] == 0
    assert read_shipment_line(ours["id"], line_two["id"])["line_surcharge_cents"] == 0


def test_issuing_an_issued_permit_is_refused(api):
    """PRD §3.8: "A new permit begins in `APPLIED`. Issuing it moves it `APPLIED →
    ISSUED`, and an issue attempt from any other status is refused with
    `ERR_HAUL_PERMIT_INVALID_STATE`."
    PRD §2.3: "Haul permits may be narrowed by `project_id` and by `status`"

    Design: Corner/state_machines/haul_permit_issue_twice_returns_invalid_state
    """
    set_clock()
    project = create_project()
    permit = apply_permit(project["id"])
    issue_permit(permit["id"])

    response = api.issue_haul_permit(permit["id"], PERMITS)
    validate_error(response, ApiErrorId.ERR_HAUL_PERMIT_INVALID_STATE.value, 409)

    assert read_haul_permit(permit["id"])["status"] == "ISSUED"
    rows, meta = validate_paginated(
        api.list_haul_permits(PERMITS, {"project_id": project["id"], "status": "ISSUED"})
    )
    assert meta["total_count"] == 1
    assert [p["id"] for p in rows] == [permit["id"]]


def test_delivering_a_building_shipment_is_refused(api):
    """PRD §3.8: "**Delivering** the load moves the shipment `DISPATCHED →
    DELIVERED`, and delivery from any other status is refused with
    `ERR_SHIPMENT_INVALID_STATE`."
    PRD §3.8: "The new shipment begins in `BUILDING` with `line_count` 0,
    `is_oversize` false, `permit_fee_cents` 0, `max_width_ft`, `max_height_ft`
    and `max_length_ft` all 0, `dispatched_at` null, and `gross_weight_lb` at the
    tractor tare of 32000 pounds."

    Design: Corner/state_machines/deliver_before_dispatch_returns_shipment_invalid_state
    """
    set_clock()
    project = create_project()
    shipment = create_shipment(project["id"], scheduled_departure="2026-08-05T13:00:00Z")

    response = api.deliver_shipment(shipment["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_SHIPMENT_INVALID_STATE.value, 409)

    reread = read_shipment(shipment["id"])
    assert reread["status"] == "BUILDING"
    assert_exact_sum(reread["gross_weight_lb"], 32000, "shipment.gross_weight_lb")
    assert reread["line_count"] == 0
    assert reread["is_oversize"] is False

    rows, meta = validate_paginated(
        api.list_shipments(FOREMAN, {"project_id": project["id"], "status": "BUILDING"})
    )
    assert meta["total_count"] == 1
    assert [s["id"] for s in rows] == [shipment["id"]]


def test_delivery_ships_every_piece_and_erection_follows_sequence(api):
    """PRD §3.8: "Every piece carried on a line of the shipment moves
    `production_status` `LOADED → SHIPPED`, and the linked permit moves `ACTIVE →
    CONSUMED`."
    PRD §3.8: "And the erector may not set out of order: every piece of the same
    project whose `erection_sequence_no` is lower than this piece's must already
    be in `ERECTED` or `SCRAPPED`, counting all of the project's pieces
    regardless of which shipment carried them. A single lower-sequence sibling
    still in any other production status rejects the confirmation with
    `ERR_ERECTION_PREDECESSOR_PENDING`. On success the owning project recomputes
    `erected_piece_count`."
    PRD §2.5: "A `ShipmentLine` is written once and never modified, so it carries
    only `id` and `created_at`; both `updated_at` and `version` are absent from a
    shipment line."

    Design: Corner/endpoints/deliver_then_erect_in_sequence_order
    """
    ctx = setup_production_line(
        stage="yarded",
        piece_specs=[
            {**LEGAL_PIECE, "piece_mark": "DT-101", "erection_sequence_no": 10},
            {**LEGAL_PIECE, "piece_mark": "DT-102", "erection_sequence_no": 20},
        ],
        slot_overrides={"capacity_weight_lb": 200000, "max_stack_count": 5},
    )
    first, second = ctx["pieces"]
    shipment = create_shipment(
        ctx["project"]["id"], scheduled_departure="2026-08-04T13:00:00Z"
    )
    line_one = add_shipment_line(shipment["id"], second["id"], 1)
    add_shipment_line(shipment["id"], first["id"], 2)
    dispatch_shipment(shipment["id"])
    owner = make_project_owner_headers(ctx["project"]["id"])

    delivered = validate_success(api.deliver_shipment(shipment["id"], FOREMAN))
    assert delivered["status"] == "DELIVERED"
    assert read_piece(first["id"])["production_status"] == "SHIPPED"
    assert read_piece(second["id"])["production_status"] == "SHIPPED"

    out_of_order = api.confirm_piece_erected(second["id"], owner)
    validate_error(out_of_order, ApiErrorId.ERR_ERECTION_PREDECESSOR_PENDING.value, 422)

    validate_success(api.confirm_piece_erected(first["id"], owner))
    validate_success(api.confirm_piece_erected(second["id"], owner))

    assert read_piece(first["id"])["production_status"] == "ERECTED"
    assert read_piece(second["id"])["production_status"] == "ERECTED"
    assert_project_counters(read_project(ctx["project"]["id"]), erected_piece_count=2)

    lines, meta = validate_paginated(api.list_shipment_lines(shipment["id"], FOREMAN))
    assert meta["total_count"] == 2
    assert_shipment_line(read_shipment_line(shipment["id"], line_one["id"]))

    carried, carried_meta = validate_paginated(
        api.list_piece_shipment_lines(first["id"], FOREMAN)
    )
    assert carried_meta["total_count"] == 1
    assert carried[0]["shipment_id"] == shipment["id"]
    assert_slot_occupancy(read_yard_slot(ctx["slot"]["id"]), 0, 0, "EMPTY")
    assert len(list_shipment_lines(shipment["id"])) == 2


def test_qc_hold_outranks_the_duplicate_load_position(api):
    """PRD §2.8: "When a request would fail more than one check, the response is
    decided by the **first** failing check in the following fixed order, and no
    later check runs."
    PRD §2.8: "**Quality and safety gates.** These guard four operations —
    casting a run, tensioning a run, requesting a release and adding a line to a
    shipment — and within this step the order is itself fixed:
    `ERR_NO_PIECES_ASSIGNED` first, then `ERR_ELONGATION_OUT_OF_TOLERANCE`, then
    `ERR_RELEASE_SET_MISSING`, then `ERR_CURING_NOT_COMPLETE`, then
    `ERR_NO_VALID_SPECIMENS`, then `ERR_RELEASE_STRENGTH_NOT_MET`, then
    `ERR_PIECE_QC_HOLD`."
    PRD §2.8: "**Uniqueness and linkage.** These guard mix design creation,
    boiler zone creation, casting bed creation, yard slot creation, haul permit
    application, piece creation, run assignment of a piece and shipment line
    creation, and within this step the order is fixed: `ERR_DUPLICATE_MIX_CODE`
    first, then `ERR_DUPLICATE_RESOURCE_CODE`, then `ERR_DUPLICATE_PIECE_MARK`,
    then `ERR_DUPLICATE_LOAD_POSITION`, then `ERR_MIX_CLASS_MISMATCH`, then
    `ERR_PIECE_PROJECT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/qc_hold_beats_duplicate_load_position
    """
    ctx = setup_yarded_load(
        piece_specs=[{}, {}],
        slot_overrides={"capacity_weight_lb": 120000, "max_stack_count": 3},
        shipment_overrides={"scheduled_departure": "2026-08-05T13:00:00Z"},
    )
    loaded, nonconforming = ctx["pieces"]
    add_shipment_line(ctx["shipment"]["id"], loaded["id"], 1)
    open_ncr(
        nonconforming["id"],
        defect_type="FINISH",
        severity="MINOR",
        description="Form line offset on the exposed face",
    )

    response = api.create_shipment_line(
        ctx["shipment"]["id"], create_shipment_line_payload(nonconforming["id"], 1), FOREMAN
    )
    error = validate_error(response, ApiErrorId.ERR_PIECE_QC_HOLD.value, 409)

    assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_LOAD_POSITION.value, (
        "load_position 1 is already taken, but the quality gate is checked first"
    )


def test_rejected_line_leaves_the_shipment_and_piece_untouched(api):
    """PRD §3.8: "Its `qc_status` must be either `CLEARED` or `REPAIRED`; a piece
    in any other quality standing is refused with `ERR_PIECE_QC_HOLD`."
    PRD §3.8: "On success the piece moves `production_status` `YARDED → LOADED`;
    then, as a consequence of that move, its `ACTIVE` yard placement moves
    `ACTIVE → RELEASED` with `release_reason` `LOAD`; then, as a consequence of
    that release, its yard slot decrements `occupied_weight_lb` and
    `stacked_count` and recomputes its `status`."

    Design: Difficulty/priority_pair_validation_conflict/qc_hold_beats_duplicate_load_position
    """
    ctx = setup_yarded_load(
        piece_specs=[{}, {}],
        slot_overrides={"capacity_weight_lb": 120000, "max_stack_count": 3},
        shipment_overrides={"scheduled_departure": "2026-08-05T13:00:00Z"},
    )
    loaded, nonconforming = ctx["pieces"]
    add_shipment_line(ctx["shipment"]["id"], loaded["id"], 1)
    open_ncr(
        nonconforming["id"],
        defect_type="FINISH",
        severity="MINOR",
        description="Form line offset on the exposed face",
    )

    validate_error(
        api.create_shipment_line(
            ctx["shipment"]["id"], create_shipment_line_payload(nonconforming["id"], 1), FOREMAN
        ),
        ApiErrorId.ERR_PIECE_QC_HOLD.value,
        409,
    )

    assert read_shipment(ctx["shipment"]["id"])["line_count"] == 1, "no line was created"
    assert read_piece(nonconforming["id"])["production_status"] == "YARDED"
    assert read_piece(loaded["id"])["production_status"] == "LOADED"
    assert_slot_occupancy(read_yard_slot(ctx["slot"]["id"]), 48200, 1, "PARTIAL")
