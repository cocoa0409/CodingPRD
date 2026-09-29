"""What each endpoint accepts, returns and refuses.

Declared defaults on a create, a read that reproduces the create response, two
action endpoints that take no body at all, a create that computes its own numbers
from a neighbouring design, a computed read over an empty population, and a
compensating action that is conditional on there being no work in flight.
"""

from test_helpers import (
    ADMIN,
    CLOCK_STARTUP_UTC,
    DEFAULT_CHANGEOVER_BUFFER_MINUTES,
    LOGISTICS,
    NON_EXISTENT_UUID,
    PLANNER,
    anchored_bom,
    assert_erection_sequence,
    assert_weight,
    authorize_builder,
    cancel_lot,
    chain_authorized_builder,
    chain_released_order,
    create_production_line,
    create_production_line_payload,
    create_shipment_load_payload,
    dispatch_load,
    get_builder,
    get_erection_sequence,
    get_jurisdiction,
    get_order,
    get_shipment_load,
    list_design_components,
    make_builder_headers,
    minimal_bom,
    plan_load,
    release_payload,
    schedule_lot,
    set_clock,
    suspend_builder,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The window the frame lot occupies on the plate line.
FRAME_LOT_WINDOW = {
    "window_start": "2026-08-10T08:00:00Z",
    "window_end": "2026-08-10T12:00:00Z",
}


def test_01_a_line_takes_the_declared_buffer_default_or_the_supplied_one(api):
    """Registration is a create, so both lines start at version 1.

    PRD §3.8: "A line carries a ``code`` unique across all lines and between 2 and
    16 characters, a display ``name``, a ``line_type`` declaring its fabrication
    capability, and a ``changeover_buffer_minutes`` that defaults to 120 and must
    be at least 0."

    PRD §2.4: "Most resources additionally carry ``updated_at``, an ISO 8601 UTC
    timestamp with the same three-fractional-digit format that is refreshed on
    every mutation, and ``version``, an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row."

    PRD §2.4: "At server startup the logical clock reads exactly
    ``2026-08-01T00:00:00Z``, and it never falls back to real time."

    Design: Corner/endpoints/production_line_create_read_and_default_buffer_roundtrip
    """
    defaulted = validate_success(
        api.create_production_line(
            create_production_line_payload(
                code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    supplied = validate_success(
        api.create_production_line(
            create_production_line_payload(
                code="PL-2", name="Roll Former 1", line_type="ROLL_FORM",
                changeover_buffer_minutes=45,
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    assert defaulted["changeover_buffer_minutes"] == DEFAULT_CHANGEOVER_BUFFER_MINUTES
    assert defaulted["changeover_buffer_minutes"] == 120
    assert supplied["changeover_buffer_minutes"] == 45
    for line in (defaulted, supplied):
        assert line["version"] == 1
        assert line["created_at"] == CLOCK_STARTUP_UTC


def test_02_reading_a_line_reproduces_the_create_response(api):
    """The read is the same row, and an unknown id has the line's own code.

    PRD §2.6: "The codes are: ``ERR_JURISDICTION_NOT_FOUND`` when no jurisdiction
    matches (used by jurisdiction read, loading-criteria publication, builder
    creation, configuration drafting and drawing-package opening);
    ``ERR_BUILDER_NOT_FOUND`` when no builder matches (builder read, builder
    authorization, builder suspension, configuration drafting and quote creation);
    ``ERR_CONFIGURATION_NOT_FOUND`` when no building configuration matches
    (configuration read, configuration lock, accessory-kit creation, accessory-kit
    list, quote creation and design creation); ``ERR_QUOTE_NOT_FOUND`` (quote read,
    quote issue, quote acceptance); ``ERR_DESIGN_NOT_FOUND`` (design read,
    component append, component list, design submit, design review, design revise
    and drawing-package opening); ``ERR_DRAWING_PACKAGE_NOT_FOUND`` (package read
    and package seal); ``ERR_ORDER_NOT_FOUND`` (order read, erection-sequence read,
    release to fabrication, cancel of release, lot scheduling and load planning);
    ``ERR_LINE_NOT_FOUND`` (line read and lot scheduling); ``ERR_LOT_NOT_FOUND``
    (lot read, lot completion and lot cancellation); and ``ERR_LOAD_NOT_FOUND``
    (load read, load dispatch and load cancellation). All ten carry HTTP 404."

    PRD §4: "Every other successful operation, including all state transitions, all
    reads and the publication of revised loading criteria, returns ``200 OK``."

    Design: Corner/endpoints/production_line_create_read_and_default_buffer_roundtrip
    """
    created = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )

    read_back = validate_success(
        api.get_production_line(created["id"], PLANNER), expected_status=200
    )
    unknown = api.get_production_line(NON_EXISTENT_UUID, PLANNER)

    assert read_back["code"] == "PL-1"
    assert read_back["name"] == "Plate Line 1"
    assert read_back["line_type"] == "PLATE_CUT_WELD"
    assert read_back["changeover_buffer_minutes"] == created["changeover_buffer_minutes"]
    assert read_back["version"] == created["version"]
    validate_error(unknown, "ERR_LINE_NOT_FOUND", expected_status=404)


def test_03_suspension_and_reauthorization_are_two_separate_bodiless_actions(api):
    """Each action is its own endpoint, and each takes no input at all.

    PRD §3.2: "Suspension is the transition out of ``AUTHORIZED`` into
    ``SUSPENDED``, and it is the most destructive operation a ``PlatformAdmin`` can
    perform."

    PRD §3.2: "Authorization is the transition into ``AUTHORIZED``, and it is
    available from both ``PENDING_AUTHORIZATION`` and ``SUSPENDED`` — the same
    operation onboards a new builder and rehabilitates a suspended one."

    PRD §2.5: "Ninth is the target resource's own from-state,
    ``ERR_INVALID_STATE_TRANSITION``."

    Design: Corner/endpoints/suspend_and_reauthorize_are_separate_action_endpoints
    """
    chain = chain_authorized_builder()
    builder_id = chain["builder"]["id"]
    jurisdiction_id = chain["jurisdiction"]["id"]

    # Neither endpoint declares any input, so both are called with no body.
    suspended = suspend_builder(builder_id)
    assert suspended["status"] == "SUSPENDED"
    assert get_jurisdiction(jurisdiction_id)["authorized_builder_count"] == 0

    set_clock("2026-08-25T00:00:00Z")
    reauthorized = authorize_builder(builder_id)
    assert reauthorized["status"] == "AUTHORIZED"
    # The fresh stamp replaces the one written on the working day.
    assert reauthorized["authorized_at"] == "2026-08-25T00:00:00.000Z"
    assert reauthorized["version"] == suspended["version"] + 1
    assert get_jurisdiction(jurisdiction_id)["authorized_builder_count"] == 1

    suspended_again = suspend_builder(builder_id)
    assert suspended_again["version"] == reauthorized["version"] + 1

    response = api.suspend_builder(builder_id, ADMIN)

    validate_error(response, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    assert get_builder(builder_id)["version"] == suspended_again["version"]


def test_04_planning_a_load_links_the_order_to_the_marks_of_its_design(api):
    """The load's weight and sequence are read off the design, not off the request.

    PRD §3.9: "On success the load's ``gross_weight_lbs`` is computed as the sum of
    ``line_weight_lbs`` over the resolved components, rounded half up to two
    decimal places; its ``stage_sequence`` is set from the erection stage ordering
    of §2.12; its ``status`` is set to ``PLANNED``; the order's pounds ledger is
    recomputed, raising ``assigned_weight_lbs`` and lowering
    ``unassigned_weight_lbs`` by the same amount; and the order's ``version``
    increments."

    PRD §2.12: "Any resource that records an ``erection_stage`` — a design
    component, an accessory kit, a shipment load — draws from this list, and a
    load's ``stage_sequence`` is the number the list assigns to its stage."

    PRD §2.3: "The production-lot list filters on ``order_id``, ``line_id`` and
    ``status``, and the shipment-load list filters on ``order_id``, ``status`` and
    ``erection_stage``."

    Design: Corner/endpoints/shipment_load_links_the_order_to_design_marks
    """
    chain = chain_released_order(components=anchored_bom())
    released = chain["order"]
    column = next(
        component
        for component in list_design_components(chain["design"]["id"])
        if component["mark"] == "C-1"
    )

    load = validate_success(
        api.create_shipment_load(
            create_shipment_load_payload(
                released["id"], released["version"],
                component_marks=["C-1"],
                erection_stage="PRIMARY_FRAME",
                unload_window_start="2026-09-16T08:00:00Z",
                unload_window_end="2026-09-16T12:00:00Z",
            ),
            LOGISTICS,
        ),
        expected_status=201,
    )

    assert load["order_id"] == released["id"]
    assert_weight(load["gross_weight_lbs"], column["line_weight_lbs"])
    assert_weight(load["gross_weight_lbs"], 15275.80)
    assert load["stage_sequence"] == 2
    assert load["component_marks"] == ["C-1"]
    assert load["status"] == "PLANNED"
    read_back = get_shipment_load(load["id"])
    assert_weight(read_back["gross_weight_lbs"], 15275.80)
    assert read_back["stage_sequence"] == 2
    order = get_order(released["id"])
    assert_weight(order["assigned_weight_lbs"], 15275.80)
    assert_weight(order["unassigned_weight_lbs"], 33.00)
    rows, meta = validate_paginated(
        api.list_shipment_loads(
            LOGISTICS,
            params={"order_id": released["id"], "erection_stage": "PRIMARY_FRAME"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == load["id"]


def test_05_the_erection_read_reports_none_with_no_load_and_after_the_last_one():
    """An empty projection and a fully dispatched one both report NONE.

    PRD §3.9: "The response carries the ``order_id``; ``sequence``, the ordered
    ``erection_stage`` values joined with the ">" character;
    ``next_dispatchable_stage``, the ``erection_stage`` of the first load in that
    ordering whose ``status`` is ``PLANNED``, or the literal string "NONE" when no
    load is still planned; ``planned_load_count``, the number of loads whose
    ``status`` is ``PLANNED``; ``dispatched_load_count``, the number whose
    ``status`` is ``DISPATCHED``; and ``blocked_load_count``, the number of
    ``PLANNED`` loads whose ``stage_sequence`` is strictly greater than the smallest
    ``stage_sequence`` found among the ``PLANNED`` loads."

    PRD §3.9: "A computed read projects an order's active loads into erection
    order."

    PRD §4: "In the Authorized Role(s) column, "Any" means all eight roles listed
    in §2.1 may call the endpoint."

    Design: Corner/endpoints/erection_sequence_read_reports_none_when_no_load_is_planned
    """
    chain = chain_released_order(components=anchored_bom())
    released = chain["order"]

    empty = get_erection_sequence(
        released["id"], headers=make_builder_headers(chain["builder"]["id"])
    )

    assert_erection_sequence(
        empty,
        order_id=released["id"],
        sequence="",
        next_dispatchable_stage="NONE",
        planned_load_count=0,
        dispatched_load_count=0,
        blocked_load_count=0,
    )
    # The read wrote nothing.
    assert get_order(released["id"])["version"] == released["version"]

    load = plan_load(
        released["id"],
        expected_order_version=released["version"],
        component_marks=["AB-1"],
        erection_stage="ANCHORAGE",
        unload_window_start="2026-09-15T08:00:00Z",
        unload_window_end="2026-09-15T12:00:00Z",
    )
    dispatch_load(load["id"])
    before_second_read = get_order(released["id"])["version"]
    assert before_second_read == released["version"] + 1

    done = get_erection_sequence(released["id"])

    assert_erection_sequence(
        done,
        order_id=released["id"],
        sequence="ANCHORAGE",
        next_dispatchable_stage="NONE",
        planned_load_count=0,
        dispatched_load_count=1,
        blocked_load_count=0,
    )
    assert get_order(released["id"])["version"] == before_second_read


def test_06_cancelling_a_release_is_refused_while_any_work_is_live(api):
    """A scheduled lot blocks the compensation until it is itself cancelled.

    PRD §3.8: "Additionally the order must carry no active work at all: no
    fabrication lot whose ``status`` is ``SCHEDULED`` or ``COMPLETE``, and no
    shipment load whose ``status`` is ``PLANNED`` or ``DISPATCHED``."

    PRD §3.8: "If any such row exists the request is refused with
    ``ERR_ORDER_HAS_ACTIVE_WORK`` — note that a ``COMPLETE`` lot blocks
    cancellation just as a ``SCHEDULED`` one does, and a ``DISPATCHED`` load blocks
    it just as a ``PLANNED`` one does; only ``CANCELLED`` lots and loads are
    ignored."

    PRD §3.8: "On success the builder's ``credit_used_cents`` moves by the negation
    of ``price_delta_cents``, restoring exactly the value the ledger held
    immediately after quote acceptance; ``final_price_cents`` and
    ``price_delta_cents`` are cleared to null; ``total_shippable_weight_lbs``,
    ``assigned_weight_lbs`` and ``unassigned_weight_lbs`` all reset to 0;
    ``released_at`` is cleared to null; ``production_status`` returns to
    ``PROD_NOT_RELEASED``; and both the order's and the builder's ``version``
    increment."

    Design: Corner/endpoints/cancel_release_is_conditional_on_the_absence_of_active_work
    """
    chain = chain_released_order(components=minimal_bom())
    order_id = chain["order"]["id"]
    line = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )
    lot = schedule_lot(
        order_id, line["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        **FRAME_LOT_WINDOW,
    )
    in_fabrication = get_order(order_id)

    refused = api.cancel_order_release(
        order_id, release_payload(in_fabrication["version"]), PLANNER
    )

    validate_error(refused, "ERR_ORDER_HAS_ACTIVE_WORK", expected_status=409)
    blocked = get_order(order_id)
    assert blocked["production_status"] == "PROD_IN_FABRICATION"
    assert blocked["released_at"] is not None

    cancel_lot(lot["id"])
    rolled_back = get_order(order_id)
    assert rolled_back["production_status"] == "PROD_RELEASED"

    cancelled = validate_success(
        api.cancel_order_release(
            order_id, release_payload(rolled_back["version"]), PLANNER
        )
    )

    assert cancelled["production_status"] == "PROD_NOT_RELEASED"
    assert cancelled["released_at"] is None
    assert cancelled["final_price_cents"] is None
    assert cancelled["price_delta_cents"] is None
    assert_weight(cancelled["total_shippable_weight_lbs"], 0)
    assert_weight(cancelled["assigned_weight_lbs"], 0)
    assert_weight(cancelled["unassigned_weight_lbs"], 0)
