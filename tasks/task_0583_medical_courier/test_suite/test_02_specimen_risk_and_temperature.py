"""Specimen risk scoring and the temperature-excursion band."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_driver_headers,
    scan_payload,
    fixtures,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _picked_up_then_delivered(api, pickup_temp, dropoff_temp):
    """Dispatched route scanned at 09:15 (pickup) and 09:55 (dropoff): a planned
    window of 120 minutes against a realized transit of 40 minutes."""
    ctx = fixtures.setup_dispatched_route(clock="2026-05-05T08:00:00Z")
    spec = ctx["specimens"][0]
    fixtures.set_clock("2026-05-05T09:15:00Z")
    fixtures.scan(ctx["stops"][0]["id"], spec["id"], "PICKUP", pickup_temp, 2.5, ctx["driver"]["id"])
    fixtures.set_clock("2026-05-05T09:55:00Z")
    fixtures.scan(ctx["stops"][1]["id"], spec["id"], "DROPOFF", dropoff_temp, 3.5, ctx["driver"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Estimated risk (at pickup) vs final risk (at delivery)
# ---------------------------------------------------------------------------
def test_estimated_risk_score_uses_the_planned_route_window(api):
    """PRD §3.5: "That estimate begins from a base determined by `specimen_type` — 10
    for `BLOOD`, 20 for `TISSUE`, 5 for `URINE`, 5 for `SWAB`, and 15 for `CULTURE` — to
    which is added the planned transit duration in minutes (the route's `scheduled_end`
    minus its `scheduled_start`) divided by ten and rounded half-up."

    A BLOOD specimen (base 10) on a 09:00-11:00 route (120 planned minutes, 120/10 = 12)
    is estimated at 22, regardless of when the scan actually happened.

    Design: Difficulty/dual_variant_calc/specimen_risk_estimated_vs_final
    """
    ctx = _picked_up_then_delivered(api, pickup_temp=9.0, dropoff_temp=5.0)
    specimen = validate_success(api.get_specimen(ctx["specimens"][0]["id"], DISPATCHER))
    assert specimen["estimated_risk_score"] == 22, (
        f"Expected BLOOD base 10 + 120 planned minutes / 10 = 22, "
        f"got {specimen['estimated_risk_score']}"
    )


def test_final_risk_score_uses_realized_transit_plus_excursion_penalty(api):
    """PRD §3.5: "The dropoff stamps `delivered_at` and computes the `final_risk_score`
    from the same `specimen_type` base plus the realized transit duration in minutes
    (`delivered_at` minus `picked_up_at`) divided by ten and rounded half-up, plus a
    penalty of 25 points for each temperature excursion the specimen has accumulated in
    `excursion_count`."

    BLOOD base 10, a realized transit of 40 minutes (40/10 = 4) and one excursion
    (9.0 against a [2, 8] band) give 10 + 4 + 25 = 39.

    Design: Difficulty/dual_variant_calc/specimen_risk_estimated_vs_final
    """
    ctx = _picked_up_then_delivered(api, pickup_temp=9.0, dropoff_temp=5.0)
    specimen = validate_success(api.get_specimen(ctx["specimens"][0]["id"], DISPATCHER))
    assert specimen["final_risk_score"] == 39, (
        f"Expected BLOOD base 10 + 40 actual minutes / 10 + 25 excursion penalty = 39, "
        f"got {specimen['final_risk_score']}"
    )


def test_estimated_and_final_risk_scores_diverge_on_the_same_specimen(api):
    """PRD §3.5: "That estimate begins from a base determined by `specimen_type` — 10
    for `BLOOD`, 20 for `TISSUE`, 5 for `URINE`, 5 for `SWAB`, and 15 for `CULTURE` — to
    which is added the planned transit duration in minutes (the route's `scheduled_end`
    minus its `scheduled_start`) divided by ten and rounded half-up."
    PRD §3.5: "The dropoff stamps `delivered_at` and computes the `final_risk_score`
    from the same `specimen_type` base plus the realized transit duration in minutes
    (`delivered_at` minus `picked_up_at`) divided by ten and rounded half-up, plus a
    penalty of 25 points for each temperature excursion the specimen has accumulated in
    `excursion_count`."

    Design: Difficulty/dual_variant_calc/specimen_risk_estimated_vs_final
    """
    ctx = _picked_up_then_delivered(api, pickup_temp=9.0, dropoff_temp=5.0)
    specimen = validate_success(api.get_specimen(ctx["specimens"][0]["id"], DISPATCHER))
    assert specimen["estimated_risk_score"] == 22
    assert specimen["final_risk_score"] == 39
    assert specimen["estimated_risk_score"] != specimen["final_risk_score"], (
        "The planned-window estimate and the realized-transit final score must differ"
    )


# ---------------------------------------------------------------------------
# Temperature band boundary — the bounds are inclusive
# ---------------------------------------------------------------------------
def test_reading_exactly_at_the_upper_bound_is_in_band(api):
    """PRD §3.5: "The reading is an excursion when `temp_reading_c` is strictly below the
    specimen's `required_temp_min_c` or strictly above its `required_temp_max_c`,
    compared to two decimal places; a reading exactly equal to either bound is in band
    and is not an excursion."
    PRD §3.5: "The scan event records this outcome in its `is_excursion` flag."

    Design: Difficulty/boundary_precision_check/temp_reading_equals_max_is_inclusive
    """
    ctx = fixtures.setup_dispatched_route()
    spec = ctx["specimens"][0]
    event = validate_success(
        api.scan_stop(
            ctx["stops"][0]["id"],
            scan_payload(spec["id"], "PICKUP", 8.0, 2.5),
            make_driver_headers(ctx["driver"]["id"]),
        ),
        expected_status=201,
    )
    assert event["is_excursion"] is False, "8.0 sits exactly on the [2, 8] upper bound"

    specimen = validate_success(api.get_specimen(spec["id"], DISPATCHER))
    assert specimen["integrity_status"] == "INTACT"
    assert specimen["excursion_count"] == 0


def test_reading_exactly_at_the_lower_bound_is_in_band(api):
    """PRD §3.5: "The reading is an excursion when `temp_reading_c` is strictly below the
    specimen's `required_temp_min_c` or strictly above its `required_temp_max_c`,
    compared to two decimal places; a reading exactly equal to either bound is in band
    and is not an excursion."

    Design: Difficulty/boundary_precision_check/temp_reading_equals_max_is_inclusive
    """
    ctx = fixtures.setup_dispatched_route()
    spec = ctx["specimens"][0]
    event = validate_success(
        api.scan_stop(
            ctx["stops"][0]["id"],
            scan_payload(spec["id"], "PICKUP", 2.0, 2.5),
            make_driver_headers(ctx["driver"]["id"]),
        ),
        expected_status=201,
    )
    assert event["is_excursion"] is False, "2.0 sits exactly on the [2, 8] lower bound"

    specimen = validate_success(api.get_specimen(spec["id"], DISPATCHER))
    assert specimen["integrity_status"] == "INTACT"
    assert specimen["excursion_count"] == 0


def test_reading_just_above_the_upper_bound_is_an_excursion(api):
    """PRD §3.5: "The reading is an excursion when `temp_reading_c` is strictly below the
    specimen's `required_temp_min_c` or strictly above its `required_temp_max_c`,
    compared to two decimal places; a reading exactly equal to either bound is in band
    and is not an excursion."
    PRD §3.5: "When an excursion occurs, the specimen's integrity dimension moves
    `INTACT → COMPROMISED`, its `excursion_count` is incremented by one, and a route
    exception of type `TEMP_EXCURSION` is opened."

    Design: Difficulty/boundary_precision_check/temp_reading_equals_max_is_inclusive
    """
    ctx = fixtures.setup_dispatched_route()
    spec = ctx["specimens"][0]
    event = validate_success(
        api.scan_stop(
            ctx["stops"][0]["id"],
            scan_payload(spec["id"], "PICKUP", 8.01, 2.5),
            make_driver_headers(ctx["driver"]["id"]),
        ),
        expected_status=201,
    )
    assert event["is_excursion"] is True, "8.01 is strictly above the [2, 8] upper bound"

    specimen = validate_success(api.get_specimen(spec["id"], DISPATCHER))
    assert specimen["integrity_status"] == "COMPROMISED"
    assert specimen["excursion_count"] == 1


# ---------------------------------------------------------------------------
# Custody and integrity are parallel, independent dimensions
# ---------------------------------------------------------------------------
def test_pickup_scan_advances_custody_and_integrity_independently(api):
    """PRD §3.5: "A pickup scan advances the specimen's custody dimension
    `AWAITING_PICKUP → IN_TRANSIT`."
    PRD §3.5: "When an excursion occurs, the specimen's integrity dimension moves
    `INTACT → COMPROMISED`, its `excursion_count` is incremented by one, and a route
    exception of type `TEMP_EXCURSION` is opened."

    One scan reading 9.0 against a [2, 8] band moves both dimensions of the same
    specimen at once.

    Design: Difficulty/non_linear_state_machine/specimen_parallel_custody_and_integrity
    """
    ctx = fixtures.setup_dispatched_route()
    spec = ctx["specimens"][0]
    fixtures.scan(ctx["stops"][0]["id"], spec["id"], "PICKUP", 9.0, 2.5, ctx["driver"]["id"])

    specimen = validate_success(api.get_specimen(spec["id"], DISPATCHER))
    assert specimen["custody_status"] == "IN_TRANSIT"
    assert specimen["integrity_status"] == "COMPROMISED"
    assert specimen["excursion_count"] == 1


def test_specimen_can_be_delivered_and_compromised_at_once(api):
    """PRD §3.5: "Because custody and integrity are independent, a specimen can reach
    `DELIVERED` while `COMPROMISED`; the delivery is recorded but the integrity breach
    travels with it."

    Design: Difficulty/non_linear_state_machine/specimen_parallel_custody_and_integrity
    """
    ctx = fixtures.setup_served_route(pickup_temp=9.0, dropoff_temp=5.0)
    specimen = validate_success(api.get_specimen(ctx["specimens"][0]["id"], DISPATCHER))
    assert specimen["custody_status"] == "DELIVERED", "The delivery is still recorded"
    assert specimen["integrity_status"] == "COMPROMISED", "The integrity breach travels with it"
    assert specimen["excursion_count"] == 1
