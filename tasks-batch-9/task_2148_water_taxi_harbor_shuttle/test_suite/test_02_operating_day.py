"""The operating day: derived posture, event surge and the capacity it sizes."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_service_day,
    create_service_day_payload,
    create_trip,
    patch_service_day,
    setup_harbor_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["harbor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


@pytest.mark.parametrize(
    "service_date,wind_knots,wave_height_m,expected_posture",
    [
        ("2026-09-01", 21.9, 0.30, "NORMAL"),
        ("2026-09-02", 22.0, 0.30, "RESTRICTED"),
        ("2026-09-03", 34.9, 0.30, "RESTRICTED"),
        ("2026-09-04", 35.0, 0.30, "SUSPENDED"),
        ("2026-09-05", 10.0, 1.20, "RESTRICTED"),
        ("2026-09-06", 10.0, 2.50, "SUSPENDED"),
    ],
)
def test_posture_thresholds_are_exact_on_wind_and_wave(
    api, service_date, wind_knots, wave_height_m, expected_posture
):
    """PRD §3.2: "The boundaries are exact: a wind of exactly 22.0 knots restricts, a
    wind of exactly 35.0 knots suspends, a wave of exactly 1.20 metres restricts, a
    wave of exactly 2.50 metres suspends, and a predicted low water of exactly 1.80
    metres does not restrict at all, because that comparison alone is strict."
    PRD §3.2: "The derivation is a ladder, and the first matching rung wins."

    Design: Corner/calculations/posture_thresholds_fire_at_exactly_22_and_35_knots_and_at_wave_120_and_250
    """
    day = validate_success(
        api.create_service_day(
            create_service_day_payload(service_date=service_date, wind_knots=wind_knots,
                                       wave_height_m=wave_height_m, low_water_m=2.10),
            ADMIN,
        ),
        201,
    )

    assert_service_day(day)
    assert day["posture"] == expected_posture, (
        f"wind {wind_knots} kn / wave {wave_height_m} m must read {expected_posture}, "
        f"got {day['posture']}"
    )


def test_low_water_of_exactly_180_does_not_restrict_while_179_does(api):
    """PRD §3.2: "Otherwise, if `low_water_m` is strictly below 1.80 metres, the day
    is `RESTRICTED`."
    PRD §3.2: "The boundaries are exact: a wind of exactly 22.0 knots restricts, a
    wind of exactly 35.0 knots suspends, a wave of exactly 1.20 metres restricts, a
    wave of exactly 2.50 metres suspends, and a predicted low water of exactly 1.80
    metres does not restrict at all, because that comparison alone is strict."

    Design: Corner/calculations/low_water_of_exactly_180_does_not_restrict_while_179_does
    """
    at_threshold = validate_success(
        api.create_service_day(
            create_service_day_payload(service_date="2026-09-01", low_water_m=1.80), ADMIN
        ),
        201,
    )
    below_threshold = validate_success(
        api.create_service_day(
            create_service_day_payload(service_date="2026-09-02", low_water_m=1.79), ADMIN
        ),
        201,
    )

    assert at_threshold["posture"] == "NORMAL", (
        f"low_water_m 1.80 must not restrict, got {at_threshold['posture']}"
    )
    assert below_threshold["posture"] == "RESTRICTED", (
        f"low_water_m 1.79 must restrict, got {below_threshold['posture']}"
    )
    assert at_threshold["surge_tier"] == "NONE"


def test_surge_tier_selects_on_attendance_and_never_without_an_event(api):
    """PRD §3.2: "When `event_name` is present, an `expected_attendance` of at least
    30000 makes the tier `PEAK`, an attendance of at least 15000 but below 30000
    makes it `ELEVATED`, and anything below 15000 leaves it at `NONE`; exactly 15000
    is `ELEVATED` and exactly 30000 is `PEAK`."
    PRD §3.2: "When `event_name` is null the day's `surge_tier` is `NONE`, however
    large `expected_attendance` may be."
    PRD §3.2: "The tier then fixes two derived fields outright: `surge_multiplier_bp`
    is 10000 basis points at `NONE`, 12500 at `ELEVATED`, and 15000 at `PEAK`; and
    `planned_extra_vessels` — the operator's capacity plan for the event — is 0 at
    `NONE`, 1 at `ELEVATED`, and 2 at `PEAK`."

    Design: Corner/calculations/surge_tier_selects_at_attendance_15000_and_30000_and_never_without_an_event
    """
    below = validate_success(api.create_service_day(create_service_day_payload(
        service_date="2026-09-01", event_name="Cup Heat", expected_attendance=14999), ADMIN), 201)
    elevated = validate_success(api.create_service_day(create_service_day_payload(
        service_date="2026-09-02", event_name="Cup Semi", expected_attendance=15000), ADMIN), 201)
    peak = validate_success(api.create_service_day(create_service_day_payload(
        service_date="2026-09-03", event_name="Cup Final", expected_attendance=30000), ADMIN), 201)
    no_event = validate_success(api.create_service_day(create_service_day_payload(
        service_date="2026-09-04", expected_attendance=50000), ADMIN), 201)

    assert below["surge_tier"] == "NONE"
    assert below["surge_multiplier_bp"] == 10000
    assert elevated["surge_tier"] == "ELEVATED"
    assert elevated["surge_multiplier_bp"] == 12500
    assert elevated["planned_extra_vessels"] == 1
    assert peak["surge_tier"] == "PEAK"
    assert peak["surge_multiplier_bp"] == 15000
    assert peak["planned_extra_vessels"] == 2
    assert no_event["surge_tier"] == "NONE", (
        f"A null event_name forces NONE, got {no_event['surge_tier']}"
    )
    assert no_event["planned_extra_vessels"] == 0


def test_second_operating_day_on_the_same_date_is_rejected(api):
    """PRD §3.2: "A `HarborAdmin` opens one for a given `service_date` — a calendar
    date that must be unique across all operating days, a second attempt on the same
    date being rejected with `ERR_SERVICE_DAY_DUPLICATE` — and files the day's
    observations: `wind_knots`, the observed sustained wind in knots to one decimal
    and at least 0.0; `wave_height_m`, the observed significant wave height in metres
    to two decimals and at least 0.00; and `low_water_m`, the predicted lowest water
    level of the day in metres above chart datum, to two decimals and at least 0.00."

    Design: Corner/validations/second_service_day_for_the_same_calendar_date_is_rejected
    """
    first = validate_success(
        api.create_service_day(create_service_day_payload(service_date="2026-09-12"), ADMIN),
        201,
    )

    response = api.create_service_day(
        create_service_day_payload(service_date="2026-09-12", wind_knots=30.0,
                                   wave_height_m=1.90, low_water_m=1.10),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_DAY_DUPLICATE.value, 409)

    unchanged = validate_success(api.get_service_day(first["id"], ADMIN))
    assert unchanged["posture"] == "NORMAL", (
        f"The rejected duplicate must not overwrite the first day, got "
        f"{unchanged['posture']}"
    )
    assert float(unchanged["wind_knots"]) == pytest.approx(10.0)


def _capacity_world():
    """40-seat OFFSHORE hull mastered by a MASTER_25T holder, on a NORMAL event day."""
    return setup_harbor_world(
        vessel={"name": "Kestrel", "seat_capacity": 40, "draft_m": 1.20,
                "hull_class": "OFFSHORE", "required_endorsement": "MASTER_25T"},
        crew={"name": "J. Poole", "endorsement_class": "MASTER_25T"},
        annual_inspection=False,
        service_day={"service_date": "2026-09-12", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10,
                     "event_name": "Harbor Bowl", "expected_attendance": 18000},
        clock="2026-09-12T13:00:00Z",
    )


def test_effective_capacity_binds_on_the_crew_ceiling_plus_the_surge_bonus(api):
    """PRD §3.3: "The **crew ceiling** is the full `seat_capacity` when the master's
    `endorsement_class` is `MASTER_100T`, and a flat 24 seats when it is
    `MASTER_25T`."
    PRD §3.3: "On top of the core comes a standing-room bonus of 12 seats, awarded
    only when all three of the following hold at once: the day's posture is `NORMAL`,
    the day's `event_name` is not null, and the day's `expected_attendance` is at
    least 15000."
    PRD §3.3: "Finally, the sum of the core capacity and the bonus is capped at the
    vessel's `seat_capacity` plus 12, and `effective_capacity` is the smaller of the
    two."

    Design: Difficulty/combinatorial_formula/effective_capacity_min_of_posture_tide_and_crew_ceilings_with_gated_surge_bonus
    """
    world = _capacity_world()
    trip = create_trip(world)

    assert world["day"]["posture"] == "NORMAL"
    assert world["day"]["surge_tier"] == "ELEVATED"
    assert trip["effective_capacity"] == 36, (
        f"min(40 posture, 40 tide, 24 crew) + 12 bonus must be 36, got "
        f"{trip['effective_capacity']}"
    )


def test_restricting_the_day_makes_the_tide_ceiling_bind_and_kills_the_bonus(api):
    """PRD §3.3: "The **tide ceiling** depends on the under-keel clearance, which is
    the day's `low_water_m` minus the vessel's `draft_m`, rounded half up to two
    decimals; when that clearance is strictly below 0.60 metres the ceiling is
    `seat_capacity` divided by two and rounded down to a whole seat, and otherwise it
    is the full `seat_capacity`."
    PRD §3.3: "If any of the three fails, the bonus is 0 — which means the bonus is
    suppressed entirely once the posture leaves `NORMAL`, even on a `PEAK` event day
    with a sell-out crowd."
    PRD §3.2: "Moving `NORMAL → RESTRICTED` or `RESTRICTED → NORMAL` recomputes the
    `effective_capacity` of every trip on that day, since the posture factor is one
    of the inputs to it."

    Design: Difficulty/combinatorial_formula/effective_capacity_min_of_posture_tide_and_crew_ceilings_with_gated_surge_bonus
    """
    world = _capacity_world()
    trip = create_trip(world)

    patched_day = patch_service_day(world["day_id"], wind_knots=24.0, low_water_m=1.55)
    assert patched_day["posture"] == "RESTRICTED"
    assert patched_day["surge_tier"] == "ELEVATED"

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["effective_capacity"] == 20, (
        f"floor(40/2) tide ceiling must bind with no bonus, got "
        f"{refreshed['effective_capacity']}"
    )
    assert refreshed["operational_status"] == "SCHEDULED"
    assert refreshed["settlement_status"] == "UNSETTLED"
