"""The refusals each write is capable of, and what survives them.

One test per family of refusal: the per-entity not-found codes, the two guards on
submitting a design, the two guards on sealing a permit set, the structural
capacity gate, the release gate the plant waits on, the lot-to-line map, the two
mark-exclusivity codes, the erection-order gate on dispatch, and the credit
ceiling on acceptance.
"""

from test_helpers import (
    ADMIN,
    ENGINEER,
    ENGINEER_USER_ID,
    LOGISTICS,
    NON_EXISTENT_UUID,
    PLANNER,
    SALES,
    SEALER,
    accept_quote_payload,
    add_connection_component,
    add_member_component,
    append_components,
    assert_credit_ledger_conserved,
    assert_erection_sequence,
    assert_error_envelope,
    assert_order_dimensions,
    assert_pounds_ledger_conserved,
    assert_rate,
    assert_weight,
    authorize_builder,
    cancel_load,
    chain_authorized_builder,
    chain_locked_configuration,
    chain_released_order,
    chain_sealed_order,
    complete_lot,
    connection_component_payload,
    create_builder,
    create_design,
    create_drawing_package,
    create_drawing_package_payload,
    create_jurisdiction,
    create_locked_configuration,
    create_production_line,
    create_production_lot_payload,
    create_quote,
    create_shipment_load_payload,
    dispatch_load,
    get_design,
    get_drawing_package,
    get_erection_sequence,
    get_builder,
    get_order,
    get_quote,
    get_shipment_load,
    issue_quote,
    make_builder_headers,
    member_component_payload,
    minimal_bom,
    plan_load,
    review_design,
    schedule_lot,
    seal_drawing_package,
    submit_design,
    two_frame_marks_bom,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The window the primary-frame fabrication lot occupies on the plate line.
FRAME_LOT_WINDOW = {
    "window_start": "2026-08-10T08:00:00Z",
    "window_end": "2026-08-10T16:00:00Z",
}

#: The window a panel run books, and the window the mismatched lot asks for.
PANEL_LOT_WINDOW = {
    "window_start": "2026-08-12T08:00:00Z",
    "window_end": "2026-08-12T12:00:00Z",
}


def _approved_design_and_package(builder_id, jurisdiction_id, knee_capacity_kip_ft):
    """One locked configuration, one approved design, one PENDING permit set."""
    configuration = create_locked_configuration(builder_id, jurisdiction_id)
    design = create_design(configuration["id"], configuration["version"])
    append_components(
        design["id"],
        [
            member_component_payload(),
            connection_component_payload(
                mark="K-1",
                connection_type="KNEE",
                capacity_moment_kip_ft=knee_capacity_kip_ft,
            ),
            connection_component_payload(
                mark="B-1",
                connection_type="BASE",
                capacity_moment_kip_ft=900,
                erection_stage="ANCHORAGE",
            ),
        ],
    )
    submit_design(design["id"])
    return {
        "design": review_design(design["id"], "APPROVE"),
        "package": create_drawing_package(design["id"], jurisdiction_id),
    }


def _released_order_with_two_frame_marks():
    """A released order whose design carries two primary-frame marks and anchors."""
    return chain_released_order(components=two_frame_marks_bom())


def test_01_every_addressable_entity_reports_its_own_not_found_code(api):
    """Ten reads against an unknown id give ten different codes, all 404.

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

    PRD §2.6: "This matters because each entity type has its own not-found code,
    and the leftmost unresolvable segment is the one reported."

    PRD §2.2: "The ``meta`` object for error responses contains only
    ``api_request_id`` and ``api_request_timestamp``."

    Design: Corner/errors/every_addressable_entity_has_its_own_not_found_code
    """
    create_jurisdiction()

    attempts = [
        (api.get_jurisdiction(NON_EXISTENT_UUID, ADMIN), "ERR_JURISDICTION_NOT_FOUND"),
        (api.get_builder(NON_EXISTENT_UUID, SALES), "ERR_BUILDER_NOT_FOUND"),
        (
            api.get_configuration(NON_EXISTENT_UUID, SALES),
            "ERR_CONFIGURATION_NOT_FOUND",
        ),
        (api.get_quote(NON_EXISTENT_UUID, SALES), "ERR_QUOTE_NOT_FOUND"),
        (api.get_design(NON_EXISTENT_UUID, ENGINEER), "ERR_DESIGN_NOT_FOUND"),
        (
            api.get_drawing_package(NON_EXISTENT_UUID, SEALER),
            "ERR_DRAWING_PACKAGE_NOT_FOUND",
        ),
        (api.get_order(NON_EXISTENT_UUID, PLANNER), "ERR_ORDER_NOT_FOUND"),
        (api.get_production_line(NON_EXISTENT_UUID, PLANNER), "ERR_LINE_NOT_FOUND"),
        (api.get_production_lot(NON_EXISTENT_UUID, PLANNER), "ERR_LOT_NOT_FOUND"),
        (api.get_shipment_load(NON_EXISTENT_UUID, LOGISTICS), "ERR_LOAD_NOT_FOUND"),
    ]

    reported = []
    for response, expected_error_id in attempts:
        validate_error(response, expected_error_id, expected_status=404)
        assert_error_envelope(response.json(), expected_error_id)
        reported.append(response.json()["data"]["error_id"])
    # Ten distinct codes, and never a single undifferentiated one.
    assert len(set(reported)) == 10
    assert "ERR_NOT_FOUND" not in reported


def test_02_a_submit_needs_frame_steel_and_a_mark_may_not_repeat(api):
    """A detail-only design cannot be submitted, and C-1 may exist only once.

    PRD §3.6: "The configuration behind it must still be ``LOCKED``, and the design
    must carry at least one component whose ``component_class`` is
    ``PRIMARY_FRAME_MEMBER`` — a design with no primary frame member is refused
    with ``ERR_PRIMARY_FRAME_MEMBERS_MISSING``."

    PRD §3.6: "A ``mark`` that already exists on the design is rejected with
    ``ERR_DUPLICATE_COMPONENT_MARK``."

    PRD §3.6: "``component_count`` is the plain count of component rows on the
    design."

    PRD §3.6: "On success ``submitted_by_user_id`` records the acting
    ``X-User-ID``, ``status`` becomes ``SUBMITTED``, and ``version`` increments."

    Design: Corner/errors/submit_requires_a_primary_frame_member_and_component_marks_are_unique
    """
    chain = chain_locked_configuration()
    configuration = chain["configuration"]
    design = create_design(configuration["id"], configuration["version"])
    add_connection_component(
        design["id"], mark="K-1", connection_type="KNEE", capacity_moment_kip_ft=1100
    )

    detail_only_submit = api.submit_design(design["id"], ENGINEER)

    validate_error(
        detail_only_submit, "ERR_PRIMARY_FRAME_MEMBERS_MISSING", expected_status=422
    )
    assert get_design(design["id"])["status"] == "DRAFT"

    add_member_component(design["id"], mark="C-1")
    repeated_mark = api.create_design_component(
        design["id"],
        member_component_payload(
            mark="C-1", member_type="RAFTER", quantity=4, length_ft=51.25,
            weight_per_ft=48.7,
        ),
        ENGINEER,
    )

    validate_error(repeated_mark, "ERR_DUPLICATE_COMPONENT_MARK", expected_status=409)
    before_submit = get_design(design["id"])
    assert before_submit["component_count"] == 2
    # The rejected rafter never joined the rollup.
    assert_weight(before_submit["frame_weight_lbs"], 15275.80)

    submitted = submit_design(design["id"])

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == ENGINEER_USER_ID


def test_03_a_seal_needs_an_approved_design_and_a_local_licence(api):
    """Approval is checked before the licence, and the licence only at seal time.

    PRD §3.7: "The design at the package's ``design_id`` must be ``APPROVED``, or
    the request fails with ``ERR_DESIGN_NOT_APPROVED`` — a design that is
    ``DRAFT``, ``SUBMITTED``, ``REVISION_REQUIRED``, ``SUPERSEDED`` or ``VOIDED``
    cannot be sealed against."

    PRD §3.7: "Finally, the package's ``sealing_license_state`` must equal the
    ``state_code`` of the jurisdiction at the package's ``jurisdiction_id``; a
    mismatch fails with ``ERR_SEAL_LICENSE_STATE_MISMATCH``."

    PRD §3.7: "A new package is ``PENDING``, with ``criteria_revision_at_seal``,
    ``sealed_at`` and ``sealed_by_user_id`` all null."

    PRD §3.7: "A successful seal stamps ``sealed_at`` with the current logical
    clock, records the acting ``X-User-ID`` as ``sealed_by_user_id``, captures the
    jurisdiction's current ``criteria_revision`` as ``criteria_revision_at_seal``,
    and sets ``status`` to ``SEALED``."

    Design: Corner/errors/seal_refuses_an_unapproved_design_and_a_foreign_licence_state
    """
    chain = chain_locked_configuration()
    configuration = chain["configuration"]
    jurisdiction_id = chain["jurisdiction"]["id"]
    design = create_design(configuration["id"], configuration["version"])
    append_components(design["id"], minimal_bom())
    texan = create_drawing_package(design["id"], jurisdiction_id)

    early_seal = api.seal_drawing_package(texan["id"], SEALER)

    validate_error(early_seal, "ERR_DESIGN_NOT_APPROVED", expected_status=409)

    submit_design(design["id"])
    review_design(design["id"], "APPROVE")
    louisianan = validate_success(
        api.create_drawing_package(
            create_drawing_package_payload(
                design["id"], jurisdiction_id, sealing_license_state="LA"
            ),
            SEALER,
        ),
        expected_status=201,
    )
    # The licence state is only measured against the jurisdiction at seal time.
    assert louisianan["sealing_license_state"] == "LA"
    assert louisianan["status"] == "PENDING"

    foreign_seal = api.seal_drawing_package(louisianan["id"], SEALER)

    validate_error(
        foreign_seal, "ERR_SEAL_LICENSE_STATE_MISMATCH", expected_status=422
    )
    refused = get_drawing_package(louisianan["id"])
    assert refused["status"] == "PENDING"
    assert refused["sealed_at"] is None
    assert refused["criteria_revision_at_seal"] is None

    sealed = seal_drawing_package(texan["id"])

    assert sealed["status"] == "SEALED"
    assert sealed["sealed_by_user_id"] == "u_seal_1"
    assert sealed["criteria_revision_at_seal"] == 1


def test_04_a_knee_below_the_required_moment_blocks_the_seal(api):
    """Two identical designs part company on one knee capacity.

    PRD §3.7: "Every connection detail whose ``connection_type`` is ``KNEE`` must
    have a ``capacity_moment_kip_ft`` of at least the design's
    ``required_moment_kip_ft`` — a single under-capacity knee, even among several
    adequate ones, fails the seal with ``ERR_CONNECTION_CAPACITY_INSUFFICIENT``,
    and a knee whose capacity exactly equals the required moment passes."

    PRD §3.6: "``governing_load_psf`` is the largest of the three rounded candidate
    pressures, and ``governing_combination`` is the name of the candidate that
    produced it."

    PRD §3.6: "From the governing pressure the system derives
    ``tributary_load_kip_per_ft`` as ``governing_load_psf`` multiplied by the
    configuration's ``bay_spacing_ft`` divided by 1000, rounded half up to six
    decimal places, and then ``required_moment_kip_ft`` as
    ``tributary_load_kip_per_ft`` multiplied by the square of the configuration's
    ``clear_span_ft`` divided by 8, rounded half up to two decimal places."

    Design: Corner/errors/knee_capacity_below_the_required_moment_blocks_the_seal
    """
    chain = chain_authorized_builder()
    builder_id = chain["builder"]["id"]
    jurisdiction_id = chain["jurisdiction"]["id"]
    under = _approved_design_and_package(builder_id, jurisdiction_id, 1000.0)
    exact = _approved_design_and_package(builder_id, jurisdiction_id, 1010.94)

    assert under["design"]["required_moment_kip_ft"] == 1010.94
    assert under["design"]["governing_combination"] == "ASD_D_PLUS_0_6W"
    assert exact["design"]["required_moment_kip_ft"] == 1010.94

    refused = api.seal_drawing_package(under["package"]["id"], SEALER)

    validate_error(
        refused, "ERR_CONNECTION_CAPACITY_INSUFFICIENT", expected_status=422
    )
    assert get_drawing_package(under["package"]["id"])["status"] == "PENDING"

    accepted = validate_success(
        api.seal_drawing_package(exact["package"]["id"], SEALER)
    )

    # A knee exactly at the required moment satisfies the gate.
    assert accepted["status"] == "SEALED"


def test_05_lots_and_loads_are_refused_until_the_order_is_released(api):
    """A sealed order is still paper: the plant may not book work against it.

    PRD §3.8: "The order's ``production_status`` must be ``PROD_RELEASED`` or
    ``PROD_IN_FABRICATION``, otherwise ``ERR_ORDER_NOT_RELEASED``."

    PRD §3.9: "The order's ``production_status`` must be ``PROD_RELEASED``,
    ``PROD_IN_FABRICATION`` or ``PROD_COMPLETE``, otherwise
    ``ERR_ORDER_NOT_RELEASED``; note that a load may be planned against an order
    whose fabrication is already finished."

    PRD §3.8: "It opens the pounds ledger: ``total_shippable_weight_lbs`` is set to
    the design's ``shippable_weight_lbs`` plus the sum of ``extended_weight_lbs``
    over every accessory kit of the order's configuration, rounded half up to two
    decimal places; ``assigned_weight_lbs`` is set to 0; and
    ``unassigned_weight_lbs`` is set equal to the total."

    Design: Corner/errors/lots_and_loads_are_refused_until_the_order_is_released
    """
    chain = chain_sealed_order(components=minimal_bom())
    sealed = chain["order"]
    line = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )

    early_lot = api.create_production_lot(
        create_production_lot_payload(
            sealed["id"], line["id"],
            lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
            window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T12:00:00Z",
        ),
        PLANNER,
    )
    early_load = api.create_shipment_load(
        create_shipment_load_payload(
            sealed["id"], sealed["version"],
            component_marks=["C-1"], erection_stage="PRIMARY_FRAME",
        ),
        LOGISTICS,
    )

    validate_error(early_lot, "ERR_ORDER_NOT_RELEASED", expected_status=409)
    validate_error(early_load, "ERR_ORDER_NOT_RELEASED", expected_status=409)
    # The pin supplied was the order's current version, so this is not a stale pin.
    assert early_load.json()["data"]["error_id"] != "ERR_STALE_ORDER_VERSION"
    order = get_order(sealed["id"])
    assert_order_dimensions(order, "ENG_SEALED", "PROD_NOT_RELEASED")
    assert order["released_at"] is None
    assert_weight(order["total_shippable_weight_lbs"], 0)
    _, lot_meta = validate_paginated(
        api.list_production_lots(PLANNER, params={"order_id": sealed["id"]})
    )
    assert lot_meta["total_count"] == 0
    _, load_meta = validate_paginated(
        api.list_shipment_loads(LOGISTICS, params={"order_id": sealed["id"]})
    )
    assert load_meta["total_count"] == 0


def test_06_a_lot_type_must_map_to_the_line_it_is_booked_on(api):
    """The map is checked in both directions and reserves nothing when it fails.

    PRD §3.8: "The ``lot_type`` must map to the line's ``line_type``:
    ``PRIMARY_FRAME_FAB`` requires a ``PLATE_CUT_WELD`` line,
    ``SECONDARY_ROLL_FORM`` requires a ``ROLL_FORM`` line, and ``PANEL_RUN``
    requires a ``PANEL_ROLL`` line; any other pairing is refused with
    ``ERR_LOT_TYPE_LINE_MISMATCH``."

    PRD §2.5: "Checks are evaluated in a fixed global precedence, and the first
    failure short-circuits the request: no later check runs and no state
    changes."

    Design: Corner/errors/lot_type_must_map_to_the_chosen_line_type
    """
    chain = chain_released_order(components=minimal_bom())
    order_id = chain["order"]["id"]
    plate = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )
    panel = create_production_line(
        code="PL-3", name="Panel Line 1", line_type="PANEL_ROLL"
    )

    panel_run_on_plate = api.create_production_lot(
        create_production_lot_payload(
            order_id, plate["id"],
            lot_type="PANEL_RUN", paint_color="POLAR_WHITE", **PANEL_LOT_WINDOW,
        ),
        PLANNER,
    )
    panel_run_on_panel = schedule_lot(
        order_id, panel["id"],
        lot_type="PANEL_RUN", paint_color="POLAR_WHITE", **PANEL_LOT_WINDOW,
    )
    frame_fab_on_panel = api.create_production_lot(
        create_production_lot_payload(
            order_id, panel["id"],
            lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
            window_start="2026-08-13T08:00:00Z", window_end="2026-08-13T12:00:00Z",
        ),
        PLANNER,
    )

    validate_error(panel_run_on_plate, "ERR_LOT_TYPE_LINE_MISMATCH", expected_status=422)
    # The refused booking reserved nothing, so the same window is free on PL-3.
    assert panel_run_on_panel["status"] == "SCHEDULED"
    validate_error(frame_fab_on_panel, "ERR_LOT_TYPE_LINE_MISMATCH", expected_status=422)
    _, meta = validate_paginated(
        api.list_production_lots(PLANNER, params={"order_id": order_id})
    )
    assert meta["total_count"] == 1


def test_07_a_mark_rides_one_live_truck_and_appears_once_per_manifest(api):
    """Repetition inside a manifest and reuse across live trucks are separate codes.

    PRD §3.9: "Only after resolution does the system check the array for internal
    repetition: a ``component_marks`` array containing the same mark twice is
    refused with ``ERR_DUPLICATE_MARK``."

    PRD §3.9: "It then checks cross-load exclusivity: no mark may already sit on
    another shipment load of the same order whose ``status`` is ``PLANNED`` or
    ``DISPATCHED``, and a collision is refused with
    ``ERR_MARK_ALREADY_ASSIGNED``."

    PRD §3.9: "Marks released by a cancelled load are available again."

    PRD §3.9: "The load's ``status`` becomes ``CANCELLED``, its marks are released
    so they may be assigned to another load, and the order's pounds ledger is
    recomputed — ``assigned_weight_lbs`` decreases by the cancelled load's
    ``gross_weight_lbs`` and ``unassigned_weight_lbs`` increases by the same
    amount, so a plan-then-cancel round trip shows zero drift."

    Design: Corner/errors/a_mark_may_be_repeated_neither_inside_a_manifest_nor_across_live_loads
    """
    chain = _released_order_with_two_frame_marks()
    released = chain["order"]

    repeated = api.create_shipment_load(
        create_shipment_load_payload(
            released["id"], released["version"],
            component_marks=["C-1", "C-1"], erection_stage="PRIMARY_FRAME",
            unload_window_start="2026-09-18T08:00:00Z",
            unload_window_end="2026-09-18T12:00:00Z",
        ),
        LOGISTICS,
    )

    validate_error(repeated, "ERR_DUPLICATE_MARK", expected_status=400)

    # Nothing was created, which is why the same version pin is still current.
    first_truck = validate_success(
        api.create_shipment_load(
            create_shipment_load_payload(
                released["id"], released["version"],
                component_marks=["C-1", "C-2"], erection_stage="PRIMARY_FRAME",
                unload_window_start="2026-09-18T08:00:00Z",
                unload_window_end="2026-09-18T12:00:00Z",
            ),
            LOGISTICS,
        ),
        expected_status=201,
    )
    assert_weight(first_truck["gross_weight_lbs"], 17475.80)
    assert first_truck["stage_sequence"] == 2
    loaded = get_order(released["id"])
    assert_weight(loaded["total_shippable_weight_lbs"], 17508.80)
    assert_weight(loaded["assigned_weight_lbs"], 17475.80)
    assert_weight(loaded["unassigned_weight_lbs"], 33.00)
    assert_pounds_ledger_conserved(loaded)

    second_truck = api.create_shipment_load(
        create_shipment_load_payload(
            released["id"], loaded["version"],
            component_marks=["C-2"], erection_stage="PRIMARY_FRAME",
            carrier_name="Second Carrier",
            unload_window_start="2026-09-20T08:00:00Z",
            unload_window_end="2026-09-20T12:00:00Z",
        ),
        LOGISTICS,
    )

    validate_error(second_truck, "ERR_MARK_ALREADY_ASSIGNED", expected_status=409)
    # The two windows do not even meet, so this is not a site capacity refusal.
    assert second_truck.json()["data"]["error_id"] != "ERR_DUPLICATE_MARK"

    cancel_load(first_truck["id"])
    freed = get_order(released["id"])
    assert_weight(freed["assigned_weight_lbs"], 0.00)
    assert_weight(freed["unassigned_weight_lbs"], 17508.80)

    retry = plan_load(
        released["id"],
        expected_order_version=freed["version"],
        component_marks=["C-2"], erection_stage="PRIMARY_FRAME",
        carrier_name="Second Carrier",
        unload_window_start="2026-09-20T08:00:00Z",
        unload_window_end="2026-09-20T12:00:00Z",
    )

    assert_weight(retry["gross_weight_lbs"], 2200.00)


def test_08_an_earlier_stage_truck_still_planned_blocks_a_dispatch(api):
    """The anchors must leave before the frame, even with the frame lot complete.

    PRD §3.9: "Second, the erection order must be respected: no shipment load of
    the same order with a strictly smaller ``stage_sequence`` may still be
    ``PLANNED``."

    PRD §3.9: "A cancelled or already-dispatched earlier-stage load does not
    block."

    PRD §3.9: "First, the steel must actually be made: each erection stage maps to
    the fabrication step that produces it — ``PRIMARY_FRAME`` maps to
    ``PRIMARY_FRAME_FAB``, ``SECONDARY_FRAME`` maps to ``SECONDARY_ROLL_FORM``, and
    both ``ROOF_PANEL`` and ``WALL_PANEL`` map to ``PANEL_RUN`` — and where a
    mapping exists, the order must have a lot of that ``lot_type`` whose ``status``
    is ``COMPLETE``."

    PRD §3.9: "A ``blocked_load_count`` above zero is precisely the population that
    would fail the erection-sequence check if dispatch were attempted on them
    now."

    Design: Corner/errors/an_earlier_stage_load_still_planned_blocks_the_dispatch
    """
    chain = _released_order_with_two_frame_marks()
    order_id = chain["order"]["id"]
    plate = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )
    frame_lot = schedule_lot(
        order_id, plate["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="GALVALUME", **FRAME_LOT_WINDOW,
    )
    complete_lot(frame_lot["id"])
    anchors = plan_load(
        order_id,
        component_marks=["AB-1"], erection_stage="ANCHORAGE",
        unload_window_start="2026-09-16T08:00:00Z",
        unload_window_end="2026-09-16T12:00:00Z",
    )
    frame = plan_load(
        order_id,
        component_marks=["C-1", "C-2"], erection_stage="PRIMARY_FRAME",
        unload_window_start="2026-09-18T08:00:00Z",
        unload_window_end="2026-09-18T12:00:00Z",
    )

    out_of_order = api.dispatch_shipment_load(frame["id"], LOGISTICS)

    validate_error(out_of_order, "ERR_ERECTION_SEQUENCE_VIOLATION", expected_status=409)
    # The fabrication lot for the frame is COMPLETE, so this is not a lot refusal.
    assert out_of_order.json()["data"]["error_id"] != "ERR_LOT_NOT_COMPLETE"
    blocked = get_shipment_load(frame["id"])
    assert blocked["status"] == "PLANNED"
    assert blocked["dispatched_at"] is None
    assert_erection_sequence(
        get_erection_sequence(order_id),
        order_id=order_id,
        sequence="ANCHORAGE>PRIMARY_FRAME",
        next_dispatchable_stage="ANCHORAGE",
        planned_load_count=2,
        dispatched_load_count=0,
        blocked_load_count=1,
    )

    assert dispatch_load(anchors["id"])["status"] == "DISPATCHED"
    retried = validate_success(api.dispatch_shipment_load(frame["id"], LOGISTICS))

    assert retried["status"] == "DISPATCHED"
    assert_erection_sequence(
        get_erection_sequence(order_id),
        order_id=order_id,
        sequence="ANCHORAGE>PRIMARY_FRAME",
        next_dispatchable_stage="NONE",
        planned_load_count=0,
        dispatched_load_count=2,
        blocked_load_count=0,
    )


def test_09_an_acceptance_past_the_credit_ceiling_is_refused(api):
    """The same price passes one builder's ceiling exactly and breaks the other's.

    PRD §3.5: "And the quote's ``quoted_price_cents`` must be at most the builder's
    ``credit_available_cents``, or the request fails with
    ``ERR_BUILDER_CREDIT_EXCEEDED``."

    PRD §3.5: "In the same request the builder's ``credit_used_cents`` increases by
    the quote's ``quoted_price_cents`` and ``credit_available_cents`` is
    recomputed, the quote's ``status`` becomes ``ACCEPTED``, and both the quote's
    ``version`` and the builder's ``version`` increment."

    PRD §3.4: "``tier_discount_rate`` comes from the builder's ``tier``: zero for
    ``BRONZE``, 0.03 for ``SILVER``, 0.08 for ``GOLD``."

    PRD §3.4: "``total_discount_rate`` is the sum of the tier rate and the volume
    rate, capped at 0.12 — that is, the smaller of 0.12 and the sum — so a ``GOLD``
    builder on a million-dollar base is capped at twelve percent rather than the
    fourteen percent the two components would otherwise give."

    Design: Corner/errors/quote_acceptance_past_the_builders_credit_ceiling_is_refused_with_402
    """
    chain = chain_authorized_builder(
        builder_overrides={
            "name": "Thin Margin Builders", "tier": "BRONZE",
            "credit_limit_cents": 5000000,
        }
    )
    jurisdiction_id = chain["jurisdiction"]["id"]
    poor_id = chain["builder"]["id"]
    rich_id = authorize_builder(
        create_builder(
            jurisdiction_id, name="Exact Ceiling Builders", tier="BRONZE",
            credit_limit_cents=8854873,
        )["id"]
    )["id"]
    poor_quote = create_quote(
        poor_id, create_locked_configuration(poor_id, jurisdiction_id)["id"]
    )
    rich_quote = create_quote(
        rich_id, create_locked_configuration(rich_id, jurisdiction_id)["id"]
    )
    issue_quote(poor_quote["id"])
    issue_quote(rich_quote["id"])

    for quote in (poor_quote, rich_quote):
        assert quote["quoted_price_cents"] == 8854873
        assert quote["subtotal_cents"] == 8693910
        assert quote["freight_cost_cents"] == 160963
        assert_rate(quote["total_discount_rate"], 0.00)

    over_ceiling = api.accept_quote(
        poor_quote["id"],
        accept_quote_payload(job_site_code="SITE-P", site_delivery_capacity=None),
        make_builder_headers(poor_id),
    )

    validate_error(over_ceiling, "ERR_BUILDER_CREDIT_EXCEEDED", expected_status=402)
    refused_builder = get_builder(poor_id)
    assert refused_builder["credit_used_cents"] == 0
    assert refused_builder["credit_available_cents"] == 5000000
    assert get_quote(poor_quote["id"])["status"] == "ISSUED"
    _, meta = validate_paginated(
        api.list_orders(SALES, params={"quote_id": poor_quote["id"]})
    )
    assert meta["total_count"] == 0

    at_ceiling = validate_success(
        api.accept_quote(
            rich_quote["id"],
            accept_quote_payload(job_site_code="SITE-R", site_delivery_capacity=None),
            make_builder_headers(rich_id),
        ),
        expected_status=201,
    )

    # 8854873 cents against a ceiling of exactly 8854873 satisfies the gate.
    assert at_ceiling["builder_id"] == rich_id
    accepted_builder = get_builder(rich_id)
    assert accepted_builder["credit_used_cents"] == 8854873
    assert accepted_builder["credit_available_cents"] == 0
    assert_credit_ledger_conserved(accepted_builder)
