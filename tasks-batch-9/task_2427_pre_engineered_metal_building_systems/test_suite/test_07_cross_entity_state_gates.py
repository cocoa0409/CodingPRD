"""Writes that are gated on the state of a different entity.

Each of these operations is legal in itself and legal on its own row's state; it
is a neighbouring row — a configuration, a drawing package, a fabrication lot —
that decides whether it may proceed.
"""

from test_helpers import (
    CLOCK_WORKING_DAY,
    ENGINEER,
    LOGISTICS,
    PLANNER,
    STANDARD_KITS,
    SEALING_ENGINEER_USER_ID,
    assert_order_dimensions,
    assert_pounds_ledger_conserved,
    assert_weight,
    chain_accepted_order,
    chain_approved_design,
    chain_authorized_builder,
    complete_lot,
    connection_component_payload,
    create_configuration,
    create_design,
    create_design_payload,
    create_drawing_package,
    create_production_line,
    get_drawing_package,
    get_order,
    get_production_lot,
    get_shipment_load,
    lock_configuration,
    member_component_payload,
    minimal_bom,
    plan_load,
    release_order,
    release_payload,
    schedule_lot,
    seal_drawing_package,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A bill spanning the primary frame, the secondary frame and the anchorage, so
#: several erection stages can be loaded onto separate trucks.
MULTI_STAGE_BILL = [
    member_component_payload(
        mark="C-1", member_type="COLUMN", quantity=10, length_ft=24.5, weight_per_ft=62.35
    ),
    member_component_payload(
        mark="P-1",
        component_class="SECONDARY_MEMBER",
        member_type="PURLIN",
        erection_stage="SECONDARY_FRAME",
        quantity=40,
        length_ft=25.083,
        weight_per_ft=3.375,
    ),
    member_component_payload(
        mark="AB-1",
        component_class="ANCHOR_PACKAGE",
        member_type="ANCHOR_BOLT",
        erection_stage="ANCHORAGE",
        quantity=10,
        length_ft=1.5,
        weight_per_ft=2.2,
    ),
    connection_component_payload(
        mark="K-1", connection_type="KNEE", capacity_moment_kip_ft=1100
    ),
    connection_component_payload(
        mark="B-1", connection_type="BASE", capacity_moment_kip_ft=900,
        erection_stage="ANCHORAGE",
    ),
]


def _draft_configuration():
    """An authorized builder and a configuration still in DRAFT."""
    chain = chain_authorized_builder()
    chain["configuration"] = create_configuration(
        chain["builder"]["id"], chain["jurisdiction"]["id"]
    )
    return chain


def _order_with_an_unsealed_package():
    """An approved design packaged for a Texas permit, but not yet sealed."""
    chain = chain_accepted_order(kits=STANDARD_KITS[:1])
    chain_approved_design(chain, components=minimal_bom())
    chain["package"] = create_drawing_package(
        chain["design"]["id"], chain["jurisdiction"]["id"],
        sealing_license_state="TX", sheet_count=12,
    )
    chain["order"] = get_order(chain["order"]["id"])
    return chain


def _planned_load_over_a_scheduled_lot():
    """A released order with a scheduled frame lot and one planned frame truck."""
    chain = chain_accepted_order()
    chain_approved_design(chain, components=MULTI_STAGE_BILL)
    package = create_drawing_package(
        chain["design"]["id"], chain["jurisdiction"]["id"],
        sealing_license_state="TX", sheet_count=14,
    )
    seal_drawing_package(package["id"])
    order = get_order(chain["order"]["id"])
    chain["order"] = release_order(order["id"], order["version"])
    line = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD",
        changeover_buffer_minutes=120,
    )
    chain["lot"] = schedule_lot(
        order["id"], line["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T12:00:00Z",
    )
    chain["load"] = plan_load(
        order["id"],
        component_marks=["C-1"],
        erection_stage="PRIMARY_FRAME",
        unload_window_start="2026-09-15T08:00:00Z",
        unload_window_end="2026-09-15T12:00:00Z",
    )
    return chain


def test_01_a_design_cannot_be_opened_against_a_draft_configuration(api):
    """The configuration's own state gates the design create, version pin aside.

    PRD §3.6: "The configuration must be ``LOCKED``, or the request is refused
    with ``ERR_CONFIGURATION_NOT_LOCKED``."

    PRD §3.3: "A fresh configuration is ``DRAFT``, and every geometry, load and
    weight field on it stays null until it is locked; ``locked_at`` and
    ``criteria_revision_at_lock`` are likewise null while ``DRAFT``."

    Design: Difficulty/cross_entity_state_dependency/design_create_requires_configuration_locked
    """
    chain = _draft_configuration()
    configuration = chain["configuration"]
    assert configuration["status"] == "DRAFT"

    response = api.create_design(
        create_design_payload(configuration["id"], configuration["version"]), ENGINEER
    )

    validate_error(response, "ERR_CONFIGURATION_NOT_LOCKED", expected_status=409)
    _, meta = validate_paginated(api.list_designs(ENGINEER))
    assert meta["total_count"] == 0


def test_02_locking_the_configuration_opens_the_gate_and_the_design_computes():
    """Once LOCKED the very same create succeeds and runs the combinations.

    PRD §3.3: "Locking also pins provenance and stamps time:
    ``criteria_revision_at_lock`` is set to the jurisdiction's current
    ``criteria_revision``, ``locked_at`` is set to the current logical clock,
    ``status`` becomes ``LOCKED``, and the configuration's ``version``
    increments."

    PRD §3.6: "A freshly opened design is ``DRAFT`` with ``frame_weight_lbs``,
    ``shippable_weight_lbs``, ``component_count`` and ``revision_count`` all at 0,
    and ``submitted_by_user_id`` and ``reviewed_by_user_id`` both null."

    Design: Difficulty/cross_entity_state_dependency/design_create_requires_configuration_locked
    """
    chain = _draft_configuration()

    locked = lock_configuration(chain["configuration"]["id"])
    assert locked["status"] == "LOCKED"
    assert locked["criteria_revision_at_lock"] == 1

    design = create_design(locked["id"], locked["version"])
    assert design["status"] == "DRAFT"
    assert design["component_count"] == 0
    assert design["revision_count"] == 0
    assert design["required_moment_kip_ft"] == 1010.94


def test_03_release_is_refused_while_the_drawing_package_is_only_pending(api):
    """A PENDING package leaves the order unlinked, so the plant may not start.

    PRD §3.8: "The order's paperwork must be complete and unencumbered:
    ``engineering_status`` must be ``ENG_SEALED``, ``drawing_package_id`` must not
    be null, the package at that id must itself be ``SEALED``, and neither
    ``permit_hold`` nor ``commercial_hold`` may be raised — any of those four
    failing produces ``ERR_DRAWINGS_NOT_SEALED``."

    PRD §3.7: "``ENG_SEALED`` is the gate the plant waits on."

    Design: Difficulty/cross_entity_state_dependency/release_requires_drawing_package_sealed
    """
    chain = _order_with_an_unsealed_package()
    assert get_drawing_package(chain["package"]["id"])["status"] == "PENDING"

    response = api.release_order_to_fabrication(
        chain["order"]["id"], release_payload(chain["order"]["version"]), PLANNER
    )

    validate_error(response, "ERR_DRAWINGS_NOT_SEALED", expected_status=409)
    order = get_order(chain["order"]["id"])
    assert_order_dimensions(order, "ENG_APPROVED", "PROD_NOT_RELEASED")
    assert order["drawing_package_id"] is None


def test_04_sealing_links_the_package_and_the_release_then_succeeds():
    """The seal is what supplies the link and the state the release demands.

    PRD §3.7: "A successful seal stamps ``sealed_at`` with the current logical
    clock, records the acting ``X-User-ID`` as ``sealed_by_user_id``, captures the
    jurisdiction's current ``criteria_revision`` as ``criteria_revision_at_seal``,
    and sets ``status`` to ``SEALED``."

    PRD §3.8: "And it stamps ``released_at`` with the current logical clock and
    sets ``production_status`` to ``PROD_RELEASED``, leaving
    ``engineering_status`` at ``ENG_SEALED``."

    Design: Difficulty/cross_entity_state_dependency/release_requires_drawing_package_sealed
    """
    chain = _order_with_an_unsealed_package()

    sealed = seal_drawing_package(chain["package"]["id"])
    assert sealed["status"] == "SEALED"
    assert sealed["criteria_revision_at_seal"] == 1
    assert sealed["sealed_by_user_id"] == SEALING_ENGINEER_USER_ID

    after_seal = get_order(chain["order"]["id"])
    assert_order_dimensions(after_seal, "ENG_SEALED", "PROD_NOT_RELEASED")
    assert after_seal["drawing_package_id"] == chain["package"]["id"]

    released = release_order(after_seal["id"], after_seal["version"])
    assert_order_dimensions(released, "ENG_SEALED", "PROD_RELEASED")
    assert released["released_at"].startswith(CLOCK_WORKING_DAY[:-1])


def test_05_a_load_cannot_be_dispatched_while_its_fabrication_lot_is_scheduled(api):
    """The steel has to be made before the truck may leave.

    PRD §3.9: "First, the steel must actually be made: each erection stage maps to
    the fabrication step that produces it — ``PRIMARY_FRAME`` maps to
    ``PRIMARY_FRAME_FAB``, ``SECONDARY_FRAME`` maps to ``SECONDARY_ROLL_FORM``,
    and both ``ROOF_PANEL`` and ``WALL_PANEL`` map to ``PANEL_RUN`` — and where a
    mapping exists, the order must have a lot of that ``lot_type`` whose
    ``status`` is ``COMPLETE``."

    PRD §3.9: "A missing or unfinished lot is refused with
    ``ERR_LOT_NOT_COMPLETE``."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_matching_production_lot_complete
    """
    chain = _planned_load_over_a_scheduled_lot()
    assert get_production_lot(chain["lot"]["id"])["status"] == "SCHEDULED"

    response = api.dispatch_shipment_load(chain["load"]["id"], LOGISTICS)

    validate_error(response, "ERR_LOT_NOT_COMPLETE", expected_status=409)
    load = get_shipment_load(chain["load"]["id"])
    assert load["status"] == "PLANNED"
    assert load["dispatched_at"] is None


def test_06_completing_the_lot_lets_the_dispatch_through_without_moving_weight(api):
    """A dispatched load stays assigned, so the pounds ledger is unchanged.

    PRD §3.8: "A ``ProductionPlanner`` completes a ``SCHEDULED`` lot, which
    requires the owning order's ``production_status`` to be ``PROD_RELEASED`` or
    ``PROD_IN_FABRICATION``; the lot's ``status`` becomes ``COMPLETE``,
    ``completed_at`` is stamped with the current logical clock, the production
    rollup re-runs on the order, and both the lot's and the order's ``version``
    increment."

    PRD §3.9: "On success ``status`` becomes ``DISPATCHED``, ``dispatched_at`` is
    stamped with the current logical clock, the order's weight ledger is
    deliberately left unchanged because a dispatched load remains assigned, and
    the load's ``version`` increments."

    PRD §2.9: "Dispatching a load moves nothing, because a dispatched load is
    still assigned."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_matching_production_lot_complete
    """
    chain = _planned_load_over_a_scheduled_lot()
    before = get_order(chain["order"]["id"])
    assert_weight(before["assigned_weight_lbs"], 15275.80)

    completed = complete_lot(chain["lot"]["id"])
    assert completed["status"] == "COMPLETE"
    assert completed["completed_at"].startswith(CLOCK_WORKING_DAY[:-1])

    dispatched = validate_success(
        api.dispatch_shipment_load(chain["load"]["id"], LOGISTICS)
    )
    assert dispatched["status"] == "DISPATCHED"
    assert_weight(dispatched["gross_weight_lbs"], 15275.80)
    assert dispatched["stage_sequence"] == 2

    after = get_order(chain["order"]["id"])
    assert_weight(after["assigned_weight_lbs"], 15275.80)
    assert_pounds_ledger_conserved(after)
