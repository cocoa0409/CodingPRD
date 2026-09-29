"""Chains where the last record moved never appears in the request.

One failing factory visit walks four entities deep — the agency file, the SKU,
the order and finally a lot that has not even been drawn yet — and every hop is
conditional on the state of the record it lands on. One scrapped lot walks three
hops the other way, through the metal ledger of the heat it was drawn from and
out to a sibling lot that shares that heat.
"""

from test_helpers import (
    advance_lot_to_extruded,
    assert_lot_dimensions,
    assert_money,
    assert_order_dimensions,
    assert_rod_mass_conserved,
    create_lot,
    read_certification,
    read_lot,
    read_order,
    read_product,
    read_rod_lot,
    scrap_lot,
    setup_baseline,
    setup_suspended_certification,
)

CASCADE_ORDER = {"order_number": "SO-CAS", "ordered_kft": 5.000}
TWO_LOT_ORDER = {"order_number": "SO-CAS", "ordered_kft": 10.000}
SECOND_LINE_WINDOW = {
    "line_code": "EXT-2",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T12:00:00Z",
}
OFF_CENTRE_EXTRUSION = {"measured_min_wall_mils": 23.0}
# A 500.00 lb heat is small enough that one scrapped 5000 ft lot writes off
# 19.80 percent of it, which is past the ten percent alarm.
SMALL_HEAT = {"order_overrides": {"order_number": "SO-SCR", "ordered_kft": 7.000},
              "rod_overrides": {"purchase_weight_lbs": 500.00}}


def _scrap_world(api, lot_a_length_ft):
    """A small heat carrying one nonconforming lot and one untouched sibling.

    Returns ``(world, lot_a, lot_b)`` with ``lot_a`` at `EXTRUDED` /
    `NONCONFORMING` and ``lot_b`` still at `QUEUED` / `PENDING`.
    """
    world = setup_baseline(api, **SMALL_HEAT)
    lot_a = create_lot(
        api, world, lot_code="LOT-SCR-A", planned_length_ft=lot_a_length_ft
    )
    lot_b = create_lot(
        api, world, lot_code="LOT-SCR-B", planned_length_ft=2000, **SECOND_LINE_WINDOW
    )
    advance_lot_to_extruded(api, lot_a["id"], extrusion_overrides=OFF_CENTRE_EXTRUSION)
    assert_lot_dimensions(read_lot(api, lot_a["id"]), "EXTRUDED", "NONCONFORMING")
    assert_lot_dimensions(lot_b, "QUEUED", "PENDING")
    return world, read_lot(api, lot_a["id"]), lot_b


def test_one_suspending_visit_freezes_the_chain_four_entities_deep(api):
    """The inspection row, the file, the SKU, the order and a lot that has had no
    process step run against it are all already moved by the time the visit's
    response is written.

    PRD 3.3: "A `SUSPEND` recorded on an `ACTIVE` file moves it directly `ACTIVE`
    → `SUSPENDED`."

    PRD 3.3: "Hop one takes every SKU whose `listing_certification_id` is this file
    and whose status is `RELEASED`, in ascending `created_at` order, and moves it
    `RELEASED` → `SUSPENDED`. Hop two, caused by each of those SKU suspensions,
    takes every order on that SKU whose fulfillment dimension is `OPEN` or
    `PARTIALLY_SHIPPED` and whose pricing dimension is `QUOTED` or `LOCKED`, in
    ascending `created_at` order, and sets its pricing dimension to `HELD` with
    `hold_reason` set to the exact string `CERTIFICATION_SUSPENDED`. Hop three,
    caused by each of those order holds, takes every production lot on that order
    whose quality dimension is `PENDING` and whose process dimension is neither
    `SHIPPED` nor `SCRAP_CLOSED`, in ascending `created_at` order, and sets its
    quality dimension to `QUARANTINED`."

    PRD 2.7: "The service therefore models these as **multi-hop cascades** executed
    inside the single request that triggered them, with immediate consistency: by
    the time the response is written, every affected record has already been moved
    and has already had its `version` incremented and its `updated_at` refreshed."

    Design: Difficulty/transitive_cascade/inspection_suspend_cascades_four_hops_to_queued_lot
    """
    world = setup_baseline(api, order_overrides=CASCADE_ORDER)
    lot = create_lot(api, world, lot_code="LOT-CAS", planned_length_ft=5000)
    assert_lot_dimensions(lot, "QUEUED", "PENDING")
    assert_order_dimensions(world["order"], "QUOTED", "OPEN")

    _, inspection = setup_suspended_certification(
        api, world=world, suspend_inspection_date="2026-08-10"
    )

    assert inspection["status"] == "OPEN", "a SUSPEND row is born open"
    assert inspection["corrective_action_due_date"] == "2026-09-09", (
        "2026-08-10 advanced by the 30 day corrective action window"
    )

    certification = read_certification(api, world["certification"]["id"])
    assert certification["status"] == "SUSPENDED"
    assert certification["open_variation_count"] == 1
    assert certification["last_inspection_date"] == "2026-08-10"
    assert certification["next_inspection_due_date"] == "2026-11-08"

    assert read_product(api, world["product"]["id"])["status"] == "SUSPENDED"

    order = read_order(api, world["order"]["id"])
    assert order["pricing_status"] == "HELD"
    assert order["hold_reason"] == "CERTIFICATION_SUSPENDED", (
        "the file's freeze records a different reason than a formulation's would"
    )

    frozen = read_lot(api, lot["id"])
    assert frozen["quality_state"] == "QUARANTINED", (
        "the fourth hop lands on a lot the visit never named, with no further "
        "request needed to make it visible"
    )
    assert frozen["version"] > lot["version"]


def test_the_cascade_moves_one_dimension_and_skips_a_lot_that_does_not_qualify(api):
    """Each hop touches exactly one dimension of its target and leaves the other
    where it was, and the sibling lot whose quality dimension is already
    `NONCONFORMING` fails the last hop's own precondition and is quietly skipped.

    PRD 2.7: "Cascades are deterministic. Wherever a cascade hop touches a set of
    sibling records, those records are processed in ascending `created_at` order,
    and each hop is evaluated only against records the previous hop actually moved.
    A hop never revisits a record it has already moved within the same request, and
    a record that fails a hop's own precondition is simply skipped rather than
    causing the request to fail."

    PRD 3.3: "Hop three, caused by each of those order holds, takes every
    production lot on that order whose quality dimension is `PENDING` and whose
    process dimension is neither `SHIPPED` nor `SCRAP_CLOSED`, in ascending
    `created_at` order, and sets its quality dimension to `QUARANTINED`."

    PRD 3.5: "The two dimensions are genuinely independent: `pricing_status` moves
    among `QUOTED`, `LOCKED`, `HELD` and `INVOICED`, while `fulfillment_status`
    moves among `OPEN`, `PARTIALLY_SHIPPED`, `FULFILLED` and the terminal
    `CANCELLED`, and neither dimension constrains the other except where a rule
    says so explicitly."

    Design: Difficulty/transitive_cascade/inspection_suspend_cascades_four_hops_to_queued_lot
    """
    world = setup_baseline(api, order_overrides=TWO_LOT_ORDER)
    queued = create_lot(api, world, lot_code="LOT-CAS-A", planned_length_ft=5000)
    condemned = create_lot(
        api, world, lot_code="LOT-CAS-B", planned_length_ft=5000, **SECOND_LINE_WINDOW
    )
    advance_lot_to_extruded(
        api, condemned["id"], extrusion_overrides=OFF_CENTRE_EXTRUSION
    )
    before_the_visit = read_lot(api, condemned["id"])
    assert_lot_dimensions(before_the_visit, "EXTRUDED", "NONCONFORMING")

    setup_suspended_certification(
        api, world=world, suspend_inspection_date="2026-08-10"
    )

    order = read_order(api, world["order"]["id"])
    assert_order_dimensions(order, "HELD", "OPEN")
    assert order["shipped_kft"] == 0.000, (
        "the freeze reached the pricing dimension and left fulfillment alone"
    )

    quarantined = read_lot(api, queued["id"])
    assert_lot_dimensions(quarantined, "QUEUED", "QUARANTINED")
    assert_money(
        quarantined["consumed_rod_lbs"], 99.00,
        "the quarantine froze the lot without touching the metal it committed",
    )

    skipped = read_lot(api, condemned["id"])
    assert_lot_dimensions(skipped, "EXTRUDED", "NONCONFORMING")
    assert skipped["version"] == before_the_visit["version"], (
        "the skipped lot failed the hop's precondition, so the visit left it "
        "exactly as it found it"
    )


def test_a_scrap_walks_the_metal_ledger_into_a_quarantine_and_freezes_a_sibling(api):
    """Ninety-nine pounds of a five hundred pound heat is written off, which is
    19.80 percent — past the alarm — so the heat is quarantined and a sibling lot
    that shares nothing with the scrapped one but the heat is frozen.

    PRD 3.7: "First, the lot's `consumed_rod_lbs` moves out of the rod lot's
    `committed_lbs` and into that rod lot's `scrapped_lbs`, with the rod lot's
    `version` incremented by one."

    PRD 3.1: "After scrap has been posted, the lot's scrap percentage is computed
    as one hundred multiplied by `scrapped_lbs`, divided by `purchase_weight_lbs`,
    rounded half up to two decimals."

    PRD 3.1: "That transition then triggers a further hop: every *other* production
    lot drawn from the same rod lot whose quality dimension currently reads
    `PENDING`, processed in ascending `created_at` order, has its quality dimension
    set to `QUARANTINED` while its process dimension is left exactly as it was,
    each such lot's `version` incremented by one."

    Design: Difficulty/transitive_cascade/lot_scrap_cascades_three_hops_through_metal_ledger_to_sibling_lot
    """
    world, lot_a, lot_b = _scrap_world(api, 5000)
    before = read_rod_lot(api, world["rod_lot"]["id"])
    assert_money(before["committed_lbs"], 138.60, "99.00 plus 39.60")
    assert_money(before["remaining_lbs"], 361.40, "what is left uncommitted")
    assert before["status"] == "RECEIVED"

    scrap_lot(api, lot_a["id"], reason="off centre beyond recovery")

    closed = read_lot(api, lot_a["id"])
    assert_lot_dimensions(closed, "SCRAP_CLOSED", "SCRAPPED")
    assert_money(closed["consumed_rod_lbs"], 99.00, "5.0 kft at 19.8 lbs per kft")

    heat = read_rod_lot(api, world["rod_lot"]["id"])
    assert_money(heat["committed_lbs"], 39.60, "only the sibling is still committed")
    assert_money(heat["scrapped_lbs"], 99.00, "the scrapped lot's mass, written off")
    assert_money(heat["remaining_lbs"], 361.40, "the uncommitted bucket did not move")
    assert heat["status"] == "QUARANTINED", (
        "one hundred times 99.00 divided by 500.00 is 19.80, strictly more than "
        "the ten percent alarm"
    )
    assert heat["version"] > before["version"]

    frozen = read_lot(api, lot_b["id"])
    assert frozen["quality_state"] == "QUARANTINED", (
        "the third hop reaches a lot that shares only the heat with the scrapped one"
    )
    assert frozen["version"] > lot_b["version"]


def test_the_quarantine_hop_is_conditional_on_the_scrap_percentage(api):
    """A four hundred foot lot writes off 7.92 pounds, which is 1.58 percent, so the
    heat stays `RECEIVED` and the sibling stays `PENDING` — the second and third
    hops simply do not fire.

    PRD 3.1: "If that percentage is strictly greater than 10.00 — that is, once more
    than a tenth of the heat has been written off — `status` becomes `QUARANTINED`
    and `version` is incremented by one."

    PRD 2.8: "Mass on a lot that was actually drawn and then scrapped is written
    off to the scrap bucket and counts against the rod lot's scrap percentage."

    PRD 2.7: "Cascades are deterministic. Wherever a cascade hop touches a set of
    sibling records, those records are processed in ascending `created_at` order,
    and each hop is evaluated only against records the previous hop actually moved."

    Design: Difficulty/transitive_cascade/lot_scrap_cascades_three_hops_through_metal_ledger_to_sibling_lot
    """
    world, lot_a, lot_b = _scrap_world(api, 400)
    assert_money(lot_a["consumed_rod_lbs"], 7.92, "0.4 kft at 19.8 lbs per kft")

    scrap_lot(api, lot_a["id"], reason="short run, off centre")

    heat = read_rod_lot(api, world["rod_lot"]["id"])
    assert_money(heat["scrapped_lbs"], 7.92, "the small write-off")
    assert heat["status"] == "RECEIVED", (
        "one hundred times 7.92 divided by 500.00 is 1.58, which is not past the "
        "ten percent alarm"
    )
    assert_money(heat["committed_lbs"], 39.60, "the sibling's mass is untouched")
    assert_money(heat["remaining_lbs"], 452.48, "500.00 less 7.92 less 39.60")
    assert_rod_mass_conserved(heat)

    untouched = read_lot(api, lot_b["id"])
    assert_lot_dimensions(untouched, "QUEUED", "PENDING")
    assert untouched["version"] == lot_b["version"], (
        "with no quarantine there is no third hop, so the sibling was never written"
    )


def test_the_sibling_freeze_touches_only_the_quality_dimension(api):
    """The frozen sibling keeps its process state, its committed mass and its
    schedule; only its quality dimension moved, and the heat's three buckets still
    sum to the mass it arrived with.

    PRD 3.1: "That transition then triggers a further hop: every *other* production
    lot drawn from the same rod lot whose quality dimension currently reads
    `PENDING`, processed in ascending `created_at` order, has its quality dimension
    set to `QUARANTINED` while its process dimension is left exactly as it was,
    each such lot's `version` incremented by one."

    PRD 2.8: "Every received rod lot records the mass it arrived with, and that
    arrival mass is thereafter split across exactly three buckets: mass still
    uncommitted, mass committed to production lots that have neither been scrapped
    nor cancelled, and mass written off as scrap."

    PRD 2.8: "After every one of the three mutations that touch these buckets —
    scheduling a lot, scrapping a lot, and cancelling an order that had queued lots
    — the three buckets must still sum exactly to the arrival mass."

    Design: Difficulty/transitive_cascade/lot_scrap_cascades_three_hops_through_metal_ledger_to_sibling_lot
    """
    world, lot_a, lot_b = _scrap_world(api, 5000)
    scrap_lot(api, lot_a["id"])

    frozen = read_lot(api, lot_b["id"])
    assert_lot_dimensions(frozen, "QUEUED", "QUARANTINED")
    assert_money(frozen["consumed_rod_lbs"], 39.60, "2.0 kft at 19.8 lbs per kft")
    assert frozen["line_code"] == "EXT-2", "the freeze does not release the line"
    assert frozen["scheduled_start_at"] == "2026-08-02T08:00:00Z"
    assert frozen["rework_count"] == 0
    assert frozen["packaged_length_ft"] == 0

    heat = read_rod_lot(api, world["rod_lot"]["id"])
    assert_rod_mass_conserved(heat)
    assert_money(
        heat["remaining_lbs"] + heat["committed_lbs"] + heat["scrapped_lbs"], 500.00,
        "361.40 uncommitted plus 39.60 committed plus 99.00 scrapped",
    )
