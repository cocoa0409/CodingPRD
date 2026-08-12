"""Weather closures, rain-check issuance tiers, and closure cascades
(PRD §3.4)."""
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    TEST_USERS,
    assert_closure_event,
    create_lane_allocation_payload, create_rental_payload,
    make_facility, make_season, make_pass_holder, make_admission,
    make_lifeguard, make_chemistry_log, make_weather_closure, set_clock,
    get_facility, make_rental, approve_rental, facility_version,
    make_passholder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]

SEASON_PRICES = dict(
    resident_pass_price_cents=10000,
    non_resident_pass_price_cents=15000,
    resident_daily_price_cents=1000,
    non_resident_daily_price_cents=1500,
)


def _setup_entered_admission(clock_date="2026-07-20", enter_time="10:00:00",
                             season_overrides=None):
    facility = make_facility(max_bather_capacity=200, lap_lane_count=4)
    season = make_season(facility["id"], **(season_overrides or SEASON_PRICES))
    holder = make_pass_holder(
        full_name="WxPat", date_of_birth="1990-01-01T00:00:00Z",
        residency_status="RESIDENT",
    )
    set_clock(f"{clock_date}T09:55:00Z")
    admission = make_admission(
        facility["id"], holder["id"], f"{clock_date}T00:00:00Z"
    )
    set_clock(f"{clock_date}T{enter_time}Z")
    admission = get_success_data(api_client.enter_admission(admission["id"], GATE))
    return facility, season, holder, admission


def test_weather_closure_depth3_cascade(api):
    """PRD §3.4: "The transition moves the facility to `CLOSED_WEATHER`,
    creates a `PoolClosureEvent` with `closure_reason` of `WEATHER`, cancels
    every `RESERVED` `LaneAllocation` overlapping the window, force-completes
    every `CHECKED_IN` rental with overtime waived, cancels every `APPROVED`
    rental whose `start_datetime` falls inside the closure window with a full
    refund, transitions every `ENTERED` admission to `RAIN_CHECKED`, and
    resets `current_bather_count` to 0."

    Design: Difficulty/transitive_cascade/weather_closure_depth3_cascade
    """
    facility, season, holder, admission = _setup_entered_admission()
    allocation = get_success_data(
        api.create_lane_allocation(
            create_lane_allocation_payload(
                facility["id"],
                purpose="SWIM_TEAM",
                start_datetime="2026-07-20T11:00:00Z",
                end_datetime="2026-07-20T12:00:00Z",
                lane_count=2,
            ),
            MANAGER,
        )
    )
    set_clock("2026-07-20T10:30:00Z")
    closure = validate_success(
        api.create_closure(
            facility["id"],
            {"closure_reason": "WEATHER", "started_at": "2026-07-20T10:30:00Z"},
            MANAGER,
        ),
        expected_status=201,
    )
    assert_closure_event(closure)
    assert closure["closure_reason"] == "WEATHER"
    assert closure["rain_check_issuance"] == "FULL_REFUND"
    admission_after = validate_success(api.get_admission(admission["id"], GATE))
    assert admission_after["status"] == "RAIN_CHECKED"
    allocation_after = validate_success(
        api.get_lane_allocation(allocation["id"], MANAGER)
    )
    assert allocation_after["status"] == "CANCELLED"
    facility_after = get_facility(facility["id"])
    assert facility_after["operational_status"] == "CLOSED_WEATHER"
    assert facility_after["current_bather_count"] == 0


def test_weather_closure_cancels_approved_rental_inside_window(api):
    """PRD §3.4: "The transition moves the facility to `CLOSED_WEATHER`,
    creates a `PoolClosureEvent` with `closure_reason` of `WEATHER`, cancels
    every `RESERVED` `LaneAllocation` overlapping the window, force-completes
    every `CHECKED_IN` rental with overtime waived, cancels every `APPROVED`
    rental whose `start_datetime` falls inside the closure window with a full
    refund, transitions every `ENTERED` admission to `RAIN_CHECKED`, and
    resets `current_bather_count` to 0."

    Design: Difficulty/transitive_cascade/weather_closure_depth3_cascade
    """
    facility, season, holder, admission = _setup_entered_admission()
    renter = make_pass_holder(
        full_name="Renter", date_of_birth="1985-01-01T00:00:00Z",
        residency_status="RESIDENT",
    )
    rental = get_success_data(
        api.create_rental(
            create_rental_payload(
                facility["id"], renter["id"],
                party_size=10,
                start_datetime="2026-07-20T11:00:00Z",
                end_datetime="2026-07-20T13:00:00Z",
            ),
            make_passholder_headers(renter["id"]),
        )
    )
    approve_rental(rental["id"], facility["id"])
    set_clock("2026-07-20T10:30:00Z")
    closure = make_weather_closure(facility["id"], "2026-07-20T10:30:00Z")
    assert closure["closure_reason"] == "WEATHER"
    rental_after = validate_success(api.get_rental(rental["id"], MANAGER))
    assert rental_after["status"] == "CANCELLED", (
        f"APPROVED rental starting inside the closure window must be "
        f"CANCELLED, got {rental_after['status']}"
    )
    admission_after = validate_success(api.get_admission(admission["id"], GATE))
    assert admission_after["status"] == "RAIN_CHECKED"


def test_rain_check_full_refund_under_60min(api):
    """PRD §3.4: "If elapsed time is at most 60 minutes, the issuance is
    `FULL_REFUND` and the patron is refunded their full `charge_cents`."
    PRD §3.4: "Elapsed minutes are computed from `entered_at` to the closure's
    `started_at`, floored to a whole minute."

    Design: Corner/calculations/rain_check_full_refund_under_60min
    """
    facility, season, holder, admission = _setup_entered_admission(
        clock_date="2026-07-15", enter_time="10:00:00",
        season_overrides=dict(
            resident_daily_price_cents=800, non_resident_daily_price_cents=1200,
        ),
    )
    set_clock("2026-07-15T10:30:00Z")
    closure = validate_success(
        api.create_closure(
            facility["id"],
            {"closure_reason": "WEATHER", "started_at": "2026-07-15T10:30:00Z"},
            MANAGER,
        ),
        expected_status=201,
    )
    assert_closure_event(closure)
    assert closure["rain_check_issuance"] == "FULL_REFUND"
    admission_after = validate_success(api.get_admission(admission["id"], GATE))
    assert admission_after["status"] == "RAIN_CHECKED"


def test_rain_check_pro_rata_over_60min(api):
    """PRD §3.4: "If elapsed time is greater than 60 minutes, the issuance is
    `PRO_RATA_CREDIT` and the patron is refunded 50 percent of `charge_cents`,
    rounded half-up to the nearest cent."

    Design: Corner/calculations/rain_check_pro_rata_over_60min
    """
    facility, season, holder, admission = _setup_entered_admission(
        clock_date="2026-07-15", enter_time="10:00:00",
        season_overrides=dict(
            resident_daily_price_cents=801, non_resident_daily_price_cents=1200,
        ),
    )
    set_clock("2026-07-15T11:30:00Z")
    closure = validate_success(
        api.create_closure(
            facility["id"],
            {"closure_reason": "WEATHER", "started_at": "2026-07-15T11:30:00Z"},
            MANAGER,
        ),
        expected_status=201,
    )
    assert_closure_event(closure)
    assert closure["rain_check_issuance"] == "PRO_RATA_CREDIT"
    admission_after = validate_success(api.get_admission(admission["id"], GATE))
    assert admission_after["status"] == "RAIN_CHECKED"


def test_rain_check_none_for_chemistry(api):
    """PRD §3.4: "For closures not caused by weather — chemistry or
    staffing — the issuance is `NONE` and no refund is owed."
    PRD §3.3: "The cascade that follows cancels every `RESERVED`
    `LaneAllocation` overlapping the closure window, force-completes every
    `CHECKED_IN` `FacilityRental` with `final_price_cents` set to the locked
    `quoted_price_cents` (overtime is waived for a chemistry-forced exit),
    transitions every `ENTERED` `DailyAdmission` to `EXITED` with `exited_at`
    stamped now and no refund, and resets `current_bather_count` to 0."

    Design: Corner/calculations/rain_check_none_for_chemistry
    """
    facility, season, holder, admission = _setup_entered_admission(
        clock_date="2026-07-15", enter_time="10:00:00",
        season_overrides=dict(
            resident_daily_price_cents=800, non_resident_daily_price_cents=1200,
        ),
    )
    lifeguard = make_lifeguard()
    make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at="2026-07-15T10:15:00Z",
        free_chlorine_ppm=0.5, ph=7.5, combined_chlorine_ppm=0.2,
    )
    admission_after = validate_success(api.get_admission(admission["id"], GATE))
    assert admission_after["status"] == "EXITED"
    facility_after = get_facility(facility["id"])
    assert facility_after["operational_status"] == "CLOSED_CHEMISTRY"
    assert facility_after["current_bather_count"] == 0
    closures, meta = validate_paginated(
        api.list_facility_closures(facility["id"], MANAGER)
    )
    chem_closures = [c for c in closures if c["closure_reason"] == "CHEMISTRY"]
    assert len(chem_closures) == 1
    assert chem_closures[0]["rain_check_issuance"] == "NONE"
