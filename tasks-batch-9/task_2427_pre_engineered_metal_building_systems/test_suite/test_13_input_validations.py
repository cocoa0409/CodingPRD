"""Validations that read the request against stored state.

Uniqueness within a table, a temporal comparison whose boundary is inclusive,
window ranges that must be sane and not historical, a colour rule that applies to
one lot type only, and two manifest failures whose reporting order is fixed.
"""

from test_helpers import (
    ADMIN,
    LOGISTICS,
    PLANNER,
    accept_quote,
    anchored_bom,
    assert_order_dimensions,
    assert_weight,
    chain_locked_configuration,
    chain_released_order,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_production_line,
    create_production_line_payload,
    create_production_lot_payload,
    create_quote,
    create_shipment_load_payload,
    get_builder,
    get_jurisdiction,
    get_order,
    get_production_line,
    get_quote,
    issue_quote,
    minimal_bom,
    plan_load,
    schedule_lot,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The window a lot may occupy on the plate line, well after the working day.
FUTURE_LOT_WINDOW = {
    "window_start": "2026-08-10T08:00:00Z",
    "window_end": "2026-08-10T12:00:00Z",
}


def _released_order_and_a_plate_line(components):
    """A released order plus a plate line to schedule frame fabrication on."""
    chain = chain_released_order(components=components)
    chain["plate"] = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )
    return chain


def test_01_a_code_is_unique_within_its_own_table_only(api):
    """Two tables each police their own code, and neither sees the other's.

    PRD §3.1: "A registration whose ``code`` already exists is rejected with
    ``ERR_DUPLICATE_CODE``; the same code guards production line registration,
    where the line's own ``code`` must be unique across all lines."

    PRD §2.5: "Checks are evaluated in a fixed global precedence, and the first
    failure short-circuits the request: no later check runs and no state
    changes."

    Design: Corner/validations/duplicate_jurisdiction_and_line_codes_are_rejected
    """
    jurisdiction = create_jurisdiction()
    line = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )

    duplicate_jurisdiction = api.create_jurisdiction(
        create_jurisdiction_payload(
            code="TX-HARRIS",
            name="Harris County Duplicate",
            territory_code="TX-OTHER",
            freight_zone=2,
            exposure_category="B",
            design_wind_speed_mph=115,
            ground_snow_load_psf=0,
            max_authorized_builders=1,
        ),
        ADMIN,
    )
    duplicate_line = api.create_production_line(
        create_production_line_payload(
            code="PL-1", name="Plate Line 1 Duplicate", line_type="ROLL_FORM"
        ),
        ADMIN,
    )
    borrowed_code = api.create_production_line(
        create_production_line_payload(
            code="TX-HARRIS", name="Oddly Named Line", line_type="PANEL_ROLL"
        ),
        ADMIN,
    )

    validate_error(duplicate_jurisdiction, "ERR_DUPLICATE_CODE", expected_status=409)
    validate_error(duplicate_line, "ERR_DUPLICATE_CODE", expected_status=409)
    # A line may carry a code that a jurisdiction already uses.
    odd_line = validate_success(borrowed_code, expected_status=201)
    assert odd_line["code"] == "TX-HARRIS"
    _, meta = validate_paginated(api.list_jurisdictions(ADMIN))
    assert meta["total_count"] == 1
    assert get_jurisdiction(jurisdiction["id"])["territory_code"] == "TX-GULF"
    assert get_production_line(line["id"])["line_type"] == "PLATE_CUT_WELD"


def test_02_an_acceptance_at_the_last_valid_instant_is_still_in_time():
    """The expiry comparison is at-or-before, so the boundary instant passes.

    PRD §3.5: "The current logical clock must be at or before ``valid_until`` — an
    acceptance exactly at ``valid_until`` is still in time, one instant later is
    not — and a late acceptance fails with ``ERR_QUOTE_EXPIRED``."

    PRD §3.5: "On success ``issued_at`` is stamped with the current logical clock,
    ``valid_until`` is set to ``issued_at`` plus a validity window of thirty days,
    ``status`` becomes ``ISSUED``, and the quote's ``version`` increments."

    PRD §3.5: "In the same request the builder's ``credit_used_cents`` increases by
    the quote's ``quoted_price_cents`` and ``credit_available_cents`` is
    recomputed, the quote's ``status`` becomes ``ACCEPTED``, and both the quote's
    ``version`` and the builder's ``version`` increment."

    Design: Corner/validations/quote_accepted_on_and_before_valid_until_passes_the_expiry_check
    """
    chain = chain_locked_configuration()
    builder_id = chain["builder"]["id"]
    first = create_quote(builder_id, chain["configuration"]["id"])
    second = create_quote(builder_id, chain["configuration"]["id"])
    issue_quote(first["id"])
    issue_quote(second["id"])
    assert get_quote(first["id"])["valid_until"] == "2026-09-04T00:00:00.000Z"
    assert get_quote(second["id"])["valid_until"] == "2026-09-04T00:00:00.000Z"

    set_clock("2026-09-03T00:00:00Z")
    day_before = accept_quote(
        first["id"], builder_id,
        job_site_code="SITE-A",
        requested_erection_start_date="2026-10-01T00:00:00Z",
    )
    set_clock("2026-09-04T00:00:00Z")
    on_the_instant = accept_quote(
        second["id"], builder_id,
        job_site_code="SITE-B",
        requested_erection_start_date="2026-10-08T00:00:00Z",
    )

    assert get_quote(first["id"])["status"] == "ACCEPTED"
    assert get_quote(second["id"])["status"] == "ACCEPTED"
    assert get_quote(first["id"])["quoted_price_cents"] == 8589227
    assert get_quote(second["id"])["quoted_price_cents"] == 8589227
    builder = get_builder(builder_id)
    assert builder["credit_used_cents"] == 17178454
    assert builder["credit_available_cents"] == 182821546
    assert day_before["job_site_code"] == "SITE-A"
    assert on_the_instant["job_site_code"] == "SITE-B"
    for order in (day_before, on_the_instant):
        assert_order_dimensions(order, "ENG_PENDING", "PROD_NOT_RELEASED")


def test_03_a_lot_may_start_at_the_clock_but_never_before_it(api):
    """The window may open on the current instant and not one instant earlier.

    PRD §3.8: "The window must be sane — ``window_end`` strictly after
    ``window_start``, otherwise ``ERR_INVALID_WINDOW_RANGE`` — and it must not be
    in the past: ``window_start`` must be at or after the current logical clock,
    and an earlier start is refused with ``ERR_LOT_WINDOW_IN_PAST``."

    PRD §3.8: "A successfully scheduled lot sets ``status`` to ``SCHEDULED`` and
    then re-runs the production rollup on its order, which typically advances the
    order from ``PROD_RELEASED`` to ``PROD_IN_FABRICATION``; the order's
    ``version`` increments."

    Design: Corner/validations/lot_window_in_past_and_inverted_ranges_are_rejected
    """
    chain = _released_order_and_a_plate_line(anchored_bom())
    released = chain["order"]

    yesterday = api.create_production_lot(
        create_production_lot_payload(
            released["id"], chain["plate"]["id"],
            lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
            window_start="2026-08-04T08:00:00Z", window_end="2026-08-04T12:00:00Z",
        ),
        PLANNER,
    )
    at_the_clock = schedule_lot(
        released["id"], chain["plate"]["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-05T00:00:00Z", window_end="2026-08-05T04:00:00Z",
    )

    validate_error(yesterday, "ERR_LOT_WINDOW_IN_PAST", expected_status=422)
    assert at_the_clock["status"] == "SCHEDULED"
    after = get_order(released["id"])
    # Only the accepted lot moved the order, and it moved it through the rollup.
    assert after["version"] == released["version"] + 1
    assert after["production_status"] == "PROD_IN_FABRICATION"
    assert_weight(after["assigned_weight_lbs"], 0)


def test_04_an_inverted_or_empty_window_is_refused_on_both_bookings(api):
    """A lot window must be strictly ordered and an unload window must not invert.

    PRD §3.8: "The window must be sane — ``window_end`` strictly after
    ``window_start``, otherwise ``ERR_INVALID_WINDOW_RANGE`` — and it must not be
    in the past: ``window_start`` must be at or after the current logical clock,
    and an earlier start is refused with ``ERR_LOT_WINDOW_IN_PAST``."

    PRD §3.9: "The unload window must satisfy ``unload_window_end`` at or after
    ``unload_window_start`` — equal bounds describe a valid instantaneous window —
    and a reversed window is refused with ``ERR_INVALID_WINDOW_RANGE``."

    Design: Corner/validations/lot_window_in_past_and_inverted_ranges_are_rejected
    """
    chain = _released_order_and_a_plate_line(anchored_bom())
    released = chain["order"]

    inverted_lot = api.create_production_lot(
        create_production_lot_payload(
            released["id"], chain["plate"]["id"],
            lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
            window_start="2026-08-10T12:00:00Z", window_end="2026-08-10T08:00:00Z",
        ),
        PLANNER,
    )
    instantaneous_lot = api.create_production_lot(
        create_production_lot_payload(
            released["id"], chain["plate"]["id"],
            lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
            window_start="2026-08-11T08:00:00Z", window_end="2026-08-11T08:00:00Z",
        ),
        PLANNER,
    )
    inverted_unload = api.create_shipment_load(
        create_shipment_load_payload(
            released["id"], released["version"],
            component_marks=["AB-1"],
            erection_stage="ANCHORAGE",
            unload_window_start="2026-09-15T12:00:00Z",
            unload_window_end="2026-09-15T08:00:00Z",
        ),
        LOGISTICS,
    )

    validate_error(inverted_lot, "ERR_INVALID_WINDOW_RANGE", expected_status=400)
    # A lot window whose end equals its start encloses nothing, so it is refused
    # by the same rule.
    validate_error(instantaneous_lot, "ERR_INVALID_WINDOW_RANGE", expected_status=400)
    validate_error(inverted_unload, "ERR_INVALID_WINDOW_RANGE", expected_status=400)
    _, lot_meta = validate_paginated(
        api.list_production_lots(PLANNER, params={"order_id": released["id"]})
    )
    assert lot_meta["total_count"] == 0
    assert get_order(released["id"])["version"] == released["version"]


def test_05_the_colour_rule_binds_panel_runs_and_leaves_frame_lots_alone(api):
    """Only a PANEL_RUN lot is measured against the configuration's panel colour.

    PRD §3.8: "For a lot whose ``lot_type`` is ``PANEL_RUN``, the ``paint_color``
    must equal the ``panel_color`` of the order's configuration, otherwise
    ``ERR_PAINT_COLOR_MISMATCH``; lots of type ``PRIMARY_FRAME_FAB`` and
    ``SECONDARY_ROLL_FORM`` carry an unconstrained shop finish colour and are never
    checked against the configuration."

    PRD §2.5: "Checks are evaluated in a fixed global precedence, and the first
    failure short-circuits the request: no later check runs and no state
    changes."

    Design: Corner/validations/paint_color_match_is_required_only_for_panel_run_lots
    """
    chain = _released_order_and_a_plate_line(minimal_bom())
    order_id = chain["order"]["id"]
    panel_line = create_production_line(
        code="PL-3", name="Panel Line 1", line_type="PANEL_ROLL"
    )
    panel_window = {
        "window_start": "2026-08-12T08:00:00Z",
        "window_end": "2026-08-12T12:00:00Z",
    }

    red_frame_lot = schedule_lot(
        order_id, chain["plate"]["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="BRIGHT_RED",
        **FUTURE_LOT_WINDOW,
    )
    red_panel_lot = api.create_production_lot(
        create_production_lot_payload(
            order_id, panel_line["id"],
            lot_type="PANEL_RUN", paint_color="BRIGHT_RED", **panel_window,
        ),
        PLANNER,
    )
    white_panel_lot = schedule_lot(
        order_id, panel_line["id"],
        lot_type="PANEL_RUN", paint_color="POLAR_WHITE", **panel_window,
    )

    assert red_frame_lot["paint_color"] == "BRIGHT_RED"
    assert red_frame_lot["status"] == "SCHEDULED"
    validate_error(red_panel_lot, "ERR_PAINT_COLOR_MISMATCH", expected_status=422)
    # The refused attempt reserved nothing on the panel line, so the matching lot
    # takes the identical window.
    assert white_panel_lot["paint_color"] == "POLAR_WHITE"
    assert white_panel_lot["status"] == "SCHEDULED"
    _, meta = validate_paginated(
        api.list_production_lots(PLANNER, params={"order_id": order_id})
    )
    assert meta["total_count"] == 2


def test_06_an_unknown_mark_is_reported_before_a_mark_at_the_wrong_stage(api):
    """Resolution runs before the stage comparison, so the manifest fails on it.

    PRD §3.9: "Then every mark in ``component_marks`` is resolved against the
    design at the order's ``engineering_design_id``, matched one to one; a mark
    with no matching component on that design is refused with
    ``ERR_MARK_NOT_FOUND``."

    PRD §3.9: "Every resolved component's own ``erection_stage`` must equal the
    load's ``erection_stage``, or the request is refused with
    ``ERR_LOAD_ITEM_STAGE_MISMATCH`` — a load is a single-stage vehicle, and mixing
    a purlin into a primary-frame load is not permitted."

    PRD §3.9: "On success the load's ``gross_weight_lbs`` is computed as the sum of
    ``line_weight_lbs`` over the resolved components, rounded half up to two
    decimal places; its ``stage_sequence`` is set from the erection stage ordering
    of §2.12; its ``status`` is set to ``PLANNED``; the order's pounds ledger is
    recomputed, raising ``assigned_weight_lbs`` and lowering
    ``unassigned_weight_lbs`` by the same amount; and the order's ``version``
    increments."

    Design: Corner/validations/unresolvable_mark_is_reported_before_the_stage_mismatch
    """
    chain = chain_released_order(components=anchored_bom())
    released = chain["order"]

    unknown_mark = api.create_shipment_load(
        create_shipment_load_payload(
            released["id"], released["version"],
            component_marks=["C-1", "NOPE-9"],
            erection_stage="ANCHORAGE",
            unload_window_start="2026-09-15T08:00:00Z",
            unload_window_end="2026-09-15T12:00:00Z",
        ),
        LOGISTICS,
    )
    wrong_stage = api.create_shipment_load(
        create_shipment_load_payload(
            released["id"], released["version"],
            component_marks=["C-1"],
            erection_stage="ANCHORAGE",
            unload_window_start="2026-09-15T08:00:00Z",
            unload_window_end="2026-09-15T12:00:00Z",
        ),
        LOGISTICS,
    )

    validate_error(unknown_mark, "ERR_MARK_NOT_FOUND", expected_status=422)
    validate_error(wrong_stage, "ERR_LOAD_ITEM_STAGE_MISMATCH", expected_status=422)
    _, meta = validate_paginated(
        api.list_shipment_loads(LOGISTICS, params={"order_id": released["id"]})
    )
    assert meta["total_count"] == 0
    # Neither rejection moved the order, so the same version pin is still current.
    assert get_order(released["id"])["version"] == released["version"]

    accepted = plan_load(
        released["id"],
        expected_order_version=released["version"],
        component_marks=["AB-1"],
        erection_stage="ANCHORAGE",
        unload_window_start="2026-09-15T08:00:00Z",
        unload_window_end="2026-09-15T12:00:00Z",
    )

    assert_weight(accepted["gross_weight_lbs"], 33.00)
    after = get_order(released["id"])
    assert_weight(after["assigned_weight_lbs"], 33.00)
    assert_weight(after["unassigned_weight_lbs"], 15275.80)
