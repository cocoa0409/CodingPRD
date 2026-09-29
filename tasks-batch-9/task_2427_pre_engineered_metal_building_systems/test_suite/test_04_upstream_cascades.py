"""Invalidation that propagates to its full depth inside one request.

Two upstream facts have downstream consequences: republishing a jurisdiction's
loading criteria and suspending a builder.  Neither queues work for later — the
response that caused the change already shows every hop.
"""

from test_helpers import (
    STANDARD_KITS,
    assert_credit_ledger_conserved,
    assert_order_dimensions,
    assert_pounds_ledger_conserved,
    assert_weight,
    chain_sealed_order,
    create_production_line,
    full_bom,
    get_builder,
    get_configuration,
    get_design,
    get_drawing_package,
    get_jurisdiction,
    get_order,
    get_production_lot,
    get_shipment_load,
    minimal_bom,
    plan_load,
    publish_loading_criteria,
    release_order,
    schedule_lot,
    suspend_builder,
)


def _released_order_with_one_scheduled_lot():
    """A sealed, released order carrying a single scheduled frame-fabrication lot."""
    chain = chain_sealed_order(kits=STANDARD_KITS[:1], components=minimal_bom())
    chain["order"] = release_order(chain["order"]["id"], chain["order"]["version"])
    line = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )
    chain["line"] = line
    chain["lot"] = schedule_lot(
        chain["order"]["id"], line["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T12:00:00Z",
    )
    return chain


def _released_order_with_two_planned_loads():
    """A released order with one scheduled lot and two planned truckloads."""
    chain = chain_sealed_order(kits=STANDARD_KITS, components=full_bom())
    order_id = chain["order"]["id"]
    chain["order"] = release_order(order_id, chain["order"]["version"])
    line = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )
    chain["lot"] = schedule_lot(
        order_id, line["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T12:00:00Z",
    )
    chain["load_a"] = plan_load(
        order_id,
        component_marks=["C-1", "R-1"],
        erection_stage="PRIMARY_FRAME",
        unload_window_start="2026-09-15T08:00:00Z",
        unload_window_end="2026-09-15T12:00:00Z",
    )
    chain["load_b"] = plan_load(
        order_id,
        component_marks=["P-1"],
        erection_stage="SECONDARY_FRAME",
        unload_window_start="2026-09-16T08:00:00Z",
        unload_window_end="2026-09-16T12:00:00Z",
    )
    return chain


def test_01_publishing_criteria_raises_the_revision_and_stales_the_locked_configuration():
    """Hop one: the configuration pinned to the old revision goes CRITERIA_STALE.

    PRD §3.1: "The four values replace the stored ones, ``criteria_revision``
    increases by exactly 1, and the jurisdiction's ``version`` increments."

    PRD §2.10: "Every locked configuration of that jurisdiction whose
    ``criteria_revision_at_lock`` now sits below the new ``criteria_revision``
    becomes ``CRITERIA_STALE``."

    PRD §2.10: "Re-locking a ``CRITERIA_STALE`` configuration returns it to
    ``LOCKED`` against the jurisdiction's current criteria, but the engineering
    designs that were voided are **not** revived — a new design must be opened."

    Design: Difficulty/transitive_cascade/jurisdiction_criteria_revision_cascade_depth_five
    """
    chain = _released_order_with_one_scheduled_lot()

    jurisdiction = publish_loading_criteria(
        chain["jurisdiction"]["id"],
        exposure_category="D",
        design_wind_speed_mph=160,
        ground_snow_load_psf=5,
        seismic_design_category="B",
    )
    assert jurisdiction["criteria_revision"] == 2

    configuration = get_configuration(chain["configuration"]["id"])
    assert configuration["status"] == "CRITERIA_STALE"
    assert configuration["criteria_revision_at_lock"] == 1
    # Going stale does not recompute anything: the loads remain the ones the
    # configuration was locked against.
    assert configuration["design_wind_pressure_psf"] == 48.79


def test_02_the_stale_configuration_voids_its_design_and_that_design_voids_its_package():
    """Hops two and three: design VOIDED, then drawing package VOIDED.

    PRD §2.10: "Because each of those configurations went stale, every
    engineering design of those configurations whose ``status`` is ``DRAFT``,
    ``SUBMITTED``, ``APPROVED`` or ``REVISION_REQUIRED`` becomes ``VOIDED``."

    PRD §2.10: "Because each of those designs was voided, every drawing package
    of those designs whose ``status`` is ``PENDING`` or ``SEALED`` becomes
    ``VOIDED``."

    PRD §3.7: "``VOIDED`` is terminal for a package: there is no un-void, and a
    new package must be opened against a newly approved design."

    Design: Difficulty/transitive_cascade/jurisdiction_criteria_revision_cascade_depth_five
    """
    chain = _released_order_with_one_scheduled_lot()
    assert get_design(chain["design"]["id"])["status"] == "APPROVED"
    assert get_drawing_package(chain["package"]["id"])["status"] == "SEALED"

    publish_loading_criteria(
        chain["jurisdiction"]["id"],
        exposure_category="D",
        design_wind_speed_mph=160,
        ground_snow_load_psf=5,
        seismic_design_category="B",
    )

    assert get_design(chain["design"]["id"])["status"] == "VOIDED"
    assert get_drawing_package(chain["package"]["id"])["status"] == "VOIDED"


def test_03_the_voided_package_puts_the_order_on_permit_hold_and_cancels_its_lot():
    """Hops four and five: ENG_REWORK with permit_hold, then a cancelled lot.

    PRD §2.10: "Because each of those packages was voided, every order pointing
    at one through its ``drawing_package_id`` gets ``permit_hold`` set to true
    and ``engineering_status`` moved to ``ENG_REWORK``."

    PRD §2.10: "And because each of those orders entered a permit hold, every one
    of its production lots with ``status`` ``SCHEDULED`` becomes ``CANCELLED``
    and its ``production_status`` is recomputed to ``PROD_HOLD``. Five hops, one
    request."

    PRD §3.8: "Otherwise, if either ``permit_hold`` or ``commercial_hold`` is
    true, the result is ``PROD_HOLD`` — a hold outranks any amount of finished
    fabrication."

    Design: Difficulty/transitive_cascade/jurisdiction_criteria_revision_cascade_depth_five
    """
    chain = _released_order_with_one_scheduled_lot()

    publish_loading_criteria(
        chain["jurisdiction"]["id"],
        exposure_category="D",
        design_wind_speed_mph=160,
        ground_snow_load_psf=5,
        seismic_design_category="B",
    )

    order = get_order(chain["order"]["id"])
    assert_order_dimensions(
        order, "ENG_REWORK", "PROD_HOLD", permit_hold=True, commercial_hold=False
    )
    assert get_production_lot(chain["lot"]["id"])["status"] == "CANCELLED"
    # The commercial chain is a different trigger entirely and did not run.
    assert get_builder(chain["builder"]["id"])["status"] == "AUTHORIZED"


def test_04_suspension_flips_the_builder_and_refreshes_the_territory_count():
    """The suspension itself is hop zero of the commercial chain.

    PRD §3.2: "Suspension is the transition out of ``AUTHORIZED`` into
    ``SUSPENDED``, and it is the most destructive operation a ``PlatformAdmin``
    can perform."

    PRD §3.2: "The builder's ``status`` becomes ``SUSPENDED``,
    ``authorized_builder_count`` is recomputed for every jurisdiction sharing
    the territory, and the three-hop commercial cascade of §2.10 runs: the
    builder's orders sitting in ``PROD_NOT_RELEASED``, ``PROD_RELEASED`` or
    ``PROD_IN_FABRICATION`` gain ``commercial_hold`` and are recomputed to
    ``PROD_HOLD``; each of those orders' ``PLANNED`` shipment loads becomes
    ``CANCELLED``; and each affected order's pounds ledger is recomputed."

    Design: Difficulty/transitive_cascade/builder_suspension_cascade_depth_three
    """
    chain = _released_order_with_two_planned_loads()
    assert get_configuration(chain["configuration"]["id"])["status"] == "LOCKED"

    suspended = suspend_builder(chain["builder"]["id"])

    assert suspended["status"] == "SUSPENDED"
    assert_credit_ledger_conserved(suspended)
    jurisdiction = get_jurisdiction(chain["jurisdiction"]["id"])
    assert jurisdiction["authorized_builder_count"] == 0


def test_05_the_commercial_hold_cancels_planned_loads_and_recomputes_the_pounds_ledger():
    """Hops one through three: hold, cancelled loads, ledger back to unassigned.

    PRD §2.10: "The second chain begins when a ``PlatformAdmin`` suspends a
    builder. Every order of that builder whose ``production_status`` is
    ``PROD_NOT_RELEASED``, ``PROD_RELEASED`` or ``PROD_IN_FABRICATION`` gets
    ``commercial_hold`` set to true and ``production_status`` recomputed to
    ``PROD_HOLD``. Because those orders entered a commercial hold, every shipment
    load of theirs with ``status`` ``PLANNED`` becomes ``CANCELLED``. Because
    those loads were cancelled, each affected order's ``assigned_weight_lbs`` and
    ``unassigned_weight_lbs`` are recomputed by the shippable-pounds ledger.
    Three hops, one request."

    PRD §2.9: "The invariant is that assigned plus unassigned equals the total at
    all times."

    Design: Difficulty/transitive_cascade/builder_suspension_cascade_depth_three
    """
    chain = _released_order_with_two_planned_loads()
    order_id = chain["order"]["id"]

    before = get_order(order_id)
    # 47323.92 of steel plus 1545.75 of kit weight.
    assert_weight(before["total_shippable_weight_lbs"], 48869.67)
    # 40234.60 on the frame truck plus 3386.40 on the secondary truck.
    assert_weight(before["assigned_weight_lbs"], 43621.00)
    assert_weight(before["unassigned_weight_lbs"], 5248.67)
    assert_pounds_ledger_conserved(before)

    suspend_builder(chain["builder"]["id"])

    after = get_order(order_id)
    assert_order_dimensions(
        after, "ENG_SEALED", "PROD_HOLD", permit_hold=False, commercial_hold=True
    )
    for load in (chain["load_a"], chain["load_b"]):
        assert get_shipment_load(load["id"])["status"] == "CANCELLED"
    assert_weight(after["assigned_weight_lbs"], 0)
    assert_weight(after["unassigned_weight_lbs"], 48869.67)
    assert_weight(after["total_shippable_weight_lbs"], 48869.67)
    assert_pounds_ledger_conserved(after)


def test_06_suspension_cancels_scheduled_lots_but_leaves_the_permit_chain_alone():
    """A commercial hold cancels shop work; the paperwork is untouched.

    PRD §3.8: "Separately, the system itself cancels a ``SCHEDULED`` lot when its
    order enters ``permit_hold`` or ``commercial_hold``, as the cascades of §2.10
    describe."

    PRD §2.11: "Two boolean flags feed it: ``permit_hold``, which becomes true
    when a jurisdiction criteria revision voided the order's sealed drawings, and
    ``commercial_hold``, which becomes true when the order's builder was
    suspended. Both default to false."

    Design: Difficulty/transitive_cascade/builder_suspension_cascade_depth_three
    """
    chain = _released_order_with_two_planned_loads()

    suspend_builder(chain["builder"]["id"])

    assert get_production_lot(chain["lot"]["id"])["status"] == "CANCELLED"
    assert get_order(chain["order"]["id"])["permit_hold"] is False
    assert get_configuration(chain["configuration"]["id"])["status"] == "LOCKED"
    assert get_design(chain["design"]["id"])["status"] == "APPROVED"
    assert get_drawing_package(chain["package"]["id"])["status"] == "SEALED"
