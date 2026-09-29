"""Two readings of the same formula, taken at two different instants or under
two different attribution theories, must both be reported and must differ.
"""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import BCM_HEADERS, api_client
from test_helpers.assertions import (
    assert_same_instant,
    round_half_up,
    violation_points,
)
from test_helpers.fixtures import (
    approve_exception,
    bootstrap_authorized_channel,
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_serial_unit,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_distributor,
    read_exposure,
    read_product,
    read_reseller,
    read_serial_unit,
    read_violation,
    request_exception,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_10 = "2026-08-10T00:00:00Z"
OBSERVED_AUG_05 = "2026-08-05T00:00:00Z"


# --------------------------------------------------------------------------- #
# Instance 1 — provisional points at detection versus final points at notice
# --------------------------------------------------------------------------- #
def _setup_provisional_vs_final():
    """Detect a marketplace breach, then move the floor with a retroactive exception."""
    pin_clock(CLOCK_AUG_01)
    world = bootstrap_authorized_channel(
        product_overrides={"msrp_cents": 15000, "standard_map_floor_cents": 10000},
    )
    pin_clock(CLOCK_AUG_10)
    violation, observation, evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=8000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_05,
    )
    world.update(
        {"violation": violation, "observation": observation, "evaluation": evaluation}
    )
    return world


def test_provisional_points_are_measured_against_the_floor_at_observed_at():
    """The provisional figure uses the floor and repeat tally as of observed_at.

    PRD: "The **provisional** figure is computed during evaluation with the instant
    set to `observed_at`, so the floor is the one that was in force when the listing
    was seen, and the repeat tally is counted as of `observed_at`; it is stored as
    `provisional_points` alongside `provisional_floor_cents`."

    Design: Difficulty/dual_variant_calc/violation_points_provisional_at_detection_vs_final_at_notice
    """
    world = _setup_provisional_vs_final()
    evaluation = world["evaluation"]
    violation = world["violation"]

    assert evaluation["evaluation_status"] == "EVALUATED_BREACH"
    assert evaluation["effective_map_floor_cents"] == 10000
    assert evaluation["floor_source"] == "STANDARD"
    assert evaluation["effective_advertised_price_cents"] == 8000
    assert evaluation["deviation_cents"] == 2000
    assert evaluation["deviation_pct"] == 0.2
    assert evaluation["provisional_points"] == violation_points(10000, 8000, "MARKETPLACE", 0) == 6

    assert violation["status"] == "DETECTED"
    assert violation["provisional_floor_cents"] == 10000
    assert violation["provisional_points"] == 6
    assert violation["assessed_points"] is None
    assert violation["assessed_floor_cents"] is None


def test_a_retroactive_exception_that_still_leaves_a_breach_voids_nothing():
    """The void cascade only reaches listings lifted to or above the new floor.

    PRD: "A violation is covered when its status is `DETECTED`, `NOTICED` or
    `DISPUTED`, when its observation's `channel` falls inside the exception's scope,
    when the observation's `observed_at` lies inside the half-open window from
    `starts_at` up to but not including `ends_at`, and when the observation's
    `effective_advertised_price_cents` is greater than or equal to the exception's
    newly installed `override_floor_cents`."

    Design: Difficulty/dual_variant_calc/violation_points_provisional_at_detection_vs_final_at_notice
    """
    world = _setup_provisional_vs_final()

    requested = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        channel_scope="MARKETPLACE",
        starts_at="2026-08-04T00:00:00Z",
        ends_at="2026-08-20T00:00:00Z",
        requested_override_floor_cents=8500,
    )
    assert requested["retroactive"] is True
    approved = approve_exception(requested["id"])

    assert approved["status"] == "APPROVED"
    assert approved["override_floor_cents"] == 8500
    # The listing advertised 8000, still under the 8500 override floor.
    assert approved["voided_violation_count"] == 0

    still_detected = read_violation(world["violation"]["id"])
    assert still_detected["status"] == "DETECTED"
    assert still_detected["assessed_points"] is None

    product = read_product(world["product"]["id"])
    assert product["open_exception_count"] == 1


def test_final_points_are_recomputed_at_issuance_against_the_moved_floor():
    """Issuance re-runs the formula at the issuance clock and that figure governs.

    PRD: "The **final** figure is recomputed at notice issuance with the instant set
    to the logical clock at issuance, so a retroactive exception approved between
    detection and notice can move the floor, move the deviation tier and therefore
    move the points, and the repeat tally is recounted and may have grown; it is
    stored as `assessed_points` alongside `assessed_floor_cents`."

    Design: Difficulty/dual_variant_calc/violation_points_provisional_at_detection_vs_final_at_notice
    """
    world = _setup_provisional_vs_final()
    requested = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        channel_scope="MARKETPLACE",
        starts_at="2026-08-04T00:00:00Z",
        ends_at="2026-08-20T00:00:00Z",
        requested_override_floor_cents=8500,
    )
    approve_exception(requested["id"])

    notice = issue_notice(world["reseller"]["id"], world["violation"]["id"])
    expected_final = violation_points(8500, 8000, "MARKETPLACE", 0)
    assert expected_final == 3

    assert notice["status"] == "ISSUED"
    assert notice["rung"] == "WARNING"
    assert notice["assessed_points"] == expected_final
    assert notice["cumulative_points_at_issue"] == 3

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "NOTICED"
    assert violation["assessed_floor_cents"] == 8500
    assert violation["assessed_points"] == 3
    assert violation["provisional_points"] == 6
    assert_same_instant(violation["cure_deadline_at"], "2026-08-20T00:00:00Z", "cure_deadline_at")

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 3


# --------------------------------------------------------------------------- #
# Instance 2 — trace-attributed versus lot-prorated diversion exposure
# --------------------------------------------------------------------------- #
def _setup_split_lot():
    """One lot of five units split three to the first distributor and two to the second."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"], serialization_enabled=True)
    first = create_distributor(legal_name="Northwind Split Lot One")
    second = create_distributor(legal_name="Northwind Split Lot Two")
    units = {}
    for serial in ("SN-1", "SN-2", "SN-3"):
        units[serial] = create_serial_unit(
            product["id"], first["id"], serial_number=serial, lot_code="LOT-A"
        )
    for serial in ("SN-4", "SN-5"):
        units[serial] = create_serial_unit(
            product["id"], second["id"], serial_number=serial, lot_code="LOT-A"
        )
    pin_clock(CLOCK_AUG_10)
    # Only SN-1 is bought back and traced, so exactly one unit of the lot is traced.
    observation = capture_observation(
        product["id"], listed_price_cents=8000, observed_at=OBSERVED_AUG_05
    )
    purchase = order_test_purchase(observation["id"], ordered_at="2026-08-08T00:00:00Z")
    capture_purchase_serial(purchase["id"], "SN-1")
    purchase = confirm_unauthorized(purchase["id"])
    return {
        "product": product,
        "first": first,
        "second": second,
        "purchase": purchase,
        "unit": units["SN-1"],
    }


def test_trace_attributed_exposure_charges_each_traced_unit_in_full():
    """Every traced unit is billed whole to the distributor on its shipping record.

    PRD: "Under the `TRACE_ATTRIBUTED` variant — the default theory the chargeback
    workflow bills from — every traced unit is charged in full to the distributor
    named on its shipping record, so the counted units are simply the number of
    serialized units whose `shipped_distributor_id` is this distributor and whose
    custody state is `TRACED_UNAUTHORIZED`, and the exposure is the per-unit rate
    multiplied by that count."

    Design: Difficulty/dual_variant_calc/distributor_exposure_trace_attributed_vs_lot_prorated
    """
    world = _setup_split_lot()

    first = read_exposure(world["first"]["id"], "TRACE_ATTRIBUTED")
    assert first["variant"] == "TRACE_ATTRIBUTED"
    assert first["diversion_score"] == 0
    assert first["tier_rate_cents_per_unit"] == 2500
    assert first["traced_unit_count"] == 1
    assert first["units_counted"] == 1
    assert first["exposure_cents"] == 2500

    second = read_exposure(world["second"]["id"], "TRACE_ATTRIBUTED")
    assert second["traced_unit_count"] == 0
    assert second["units_counted"] == 0
    assert second["exposure_cents"] == 0


def test_lot_prorated_exposure_shares_traced_units_by_shipped_proportion():
    """Each distributor carries its shipped fraction of the lot's traced units.

    PRD: "Otherwise count all units of that lot in any custody state, and count the
    units of that lot whose `shipped_distributor_id` is this distributor in any
    custody state, and add to the running tally the lot's traced count multiplied by
    this distributor's shipped count, divided by the lot's total shipped count,
    rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/distributor_exposure_trace_attributed_vs_lot_prorated
    """
    world = _setup_split_lot()

    # The lot holds five shipped units, three from the first distributor and two from
    # the second, and exactly one of them has been traced.
    first_share = round_half_up(1 * 3 / 5, 2)
    second_share = round_half_up(1 * 2 / 5, 2)
    assert (first_share, second_share) == (0.6, 0.4)

    first = read_exposure(world["first"]["id"], "LOT_PRORATED")
    assert first["variant"] == "LOT_PRORATED"
    assert first["traced_unit_count"] == 1
    assert first["tier_rate_cents_per_unit"] == 2500
    assert first["units_counted"] == first_share
    assert first["exposure_cents"] == round_half_up(2500 * first_share) == 1500

    second = read_exposure(world["second"]["id"], "LOT_PRORATED")
    assert second["traced_unit_count"] == 0
    assert second["units_counted"] == second_share
    assert second["exposure_cents"] == round_half_up(2500 * second_share) == 1000


def test_the_exposure_read_bills_nothing_and_moves_neither_ledger():
    """The exposure read is a projection; only an assessment moves the ledgers.

    PRD: "A **diversion exposure** computed read lets either side see what is at
    stake before anyone bills anything, under a required `variant` selecting one of
    two attribution theories."

    Design: Difficulty/dual_variant_calc/distributor_exposure_trace_attributed_vs_lot_prorated
    """
    world = _setup_split_lot()
    read_exposure(world["first"]["id"], "TRACE_ATTRIBUTED")
    read_exposure(world["first"]["id"], "LOT_PRORATED")

    distributor = read_distributor(world["first"]["id"])
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["diversion_score"] == 0
    assert distributor["standing"] == "GOOD"

    rows, meta = validate_paginated(
        api_client.list_chargebacks(BCM_HEADERS, params={"distributor_id": world["first"]["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    unit = read_serial_unit(world["unit"]["id"])
    assert unit["status"] == "TRACED_UNAUTHORIZED"
