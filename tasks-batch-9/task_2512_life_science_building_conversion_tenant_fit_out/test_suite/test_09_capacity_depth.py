"""A shutdown gated by somebody's meeting, and a reservation returned without drift."""

from test_helpers import (
    LANDLORD_HEADERS,
    ApiErrorId,
    assert_capacity_pool_identity,
    assert_money,
    assert_pools_restored,
    book_and_confirm_allocation,
    create_amenity,
    create_phase,
    get_allocation,
    get_building,
    get_phase,
    get_reservation,
    get_success_data,
    reserve_capacity,
    same_instant,
    schedule_phase,
    setup_permitted_project,
    utc,
    validate_error,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
DEMAND = {
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}
LEASE = {"base_rent_psf": 105.00, "delivery_deadline": "2026-12-31T00:00:00Z"}

BOOKING_WINDOW = (utc(2026, 9, 10, 8), utc(2026, 9, 10, 12))
SHUTDOWN_WINDOW = (utc(2026, 9, 10), utc(2026, 9, 11))

RESERVED_EXHAUST_CFM = 18000.00
RESERVED_POWER_KW = 250.00


def _project_with_a_shutdown_package(api):
    """A permitted project, a glasswash serving its plate, a confirmed booking on
    that glasswash and a shutdown package naming it."""
    bundle = setup_permitted_project(
        api,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides=dict(LEASE),
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={
            "design_exhaust_cfm": 15000,
            "design_power_kw": 220,
            "scope_summary": "BSL2 biology fit-out, floor 2",
        },
    )
    bundle["amenity"] = create_amenity(
        api,
        bundle["building"]["id"],
        2,
        name="Level 2 Glasswash",
        amenity_type="GLASSWASH",
        concurrent_capacity=2,
        vibration_sensitive=False,
    )
    bundle["allocation"] = book_and_confirm_allocation(
        api,
        bundle["amenity"]["id"],
        bundle["project"]["id"],
        *BOOKING_WINDOW,
        headcount=10,
    )
    bundle["phase"] = create_phase(
        api,
        bundle["project"]["id"],
        premium_class="LAB_MEP",
        work_class="SHUTDOWN_REQUIRED",
        hard_cost_usd=50000.00,
        restoration_cost_usd=30000.00,
        affected_amenity_id=bundle["amenity"]["id"],
    )
    return bundle


def _project_on_a_fully_built_out_base_building(api):
    """A permitted project on a building whose riser and generator work are both
    closed out, with capacity reserved against the enlarged pools."""
    bundle = setup_permitted_project(
        api,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides=dict(LEASE),
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        declare_disciplines=("LAB_EXHAUST", "EMERGENCY_POWER"),
        complete_disciplines=("LAB_EXHAUST", "EMERGENCY_POWER"),
        exhaust_delta_cfm=20000,
        power_delta_kw=400,
        project_overrides={
            "design_exhaust_cfm": 18000,
            "design_power_kw": 250,
            "scope_summary": "BSL2 biology fit-out, floor 2",
        },
    )
    return bundle


def test_the_shutdown_cannot_be_scheduled_over_a_confirmed_booking(api):
    """The window is judged against the state of a booking on another entity.

    The package's own window is legal in every respect the package controls, and
    it is refused solely because the amenity it takes out of service is booked by
    a confirmed allocation that the window overlaps.

    Design: Difficulty/cross_entity_state_dependency/shutdown_phase_gated_on_confirmed_amenity_allocation_state
    """
    bundle = _project_with_a_shutdown_package(api)
    phase = bundle["phase"]
    assert phase["work_class"] == "SHUTDOWN_REQUIRED"
    assert phase["affected_amenity_id"] == bundle["amenity"]["id"]
    assert phase["status"] == "DRAFT"
    assert bundle["allocation"]["status"] == "CONFIRMED"

    response = api.schedule_phase(
        phase["id"],
        {"window_start": SHUTDOWN_WINDOW[0], "window_end": SHUTDOWN_WINDOW[1]},
        LANDLORD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SHUTDOWN_CONFLICTS_AMENITY.value, 409)

    unchanged = get_phase(api, phase["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["window_start"] is None
    assert get_allocation(api, bundle["allocation"]["id"])["status"] == "CONFIRMED"


def test_cancelling_the_booking_admits_the_identical_shutdown_window(api):
    """Only a confirmed booking stands in the way.

    The tenant cancels its own booking, which is the only thing that changes, and
    the identical window is then accepted -- so the objection was the state of
    the allocation rather than anything about the window itself.

    Design: Difficulty/cross_entity_state_dependency/shutdown_phase_gated_on_confirmed_amenity_allocation_state
    """
    bundle = _project_with_a_shutdown_package(api)
    phase = bundle["phase"]
    validate_error(
        api.schedule_phase(
            phase["id"],
            {"window_start": SHUTDOWN_WINDOW[0], "window_end": SHUTDOWN_WINDOW[1]},
            LANDLORD_HEADERS,
        ),
        ApiErrorId.ERR_SHUTDOWN_CONFLICTS_AMENITY.value,
        409,
    )

    cancelled = get_success_data(
        api.cancel_allocation(bundle["allocation"]["id"], bundle["tenant_headers"])
    )
    assert cancelled["status"] == "CANCELLED"

    scheduled = schedule_phase(api, phase["id"], *SHUTDOWN_WINDOW)

    assert scheduled["status"] == "SCHEDULED"
    assert same_instant(scheduled["window_start"], SHUTDOWN_WINDOW[0])
    assert same_instant(scheduled["window_end"], SHUTDOWN_WINDOW[1])


def test_cancelling_a_reservation_returns_the_pools_to_the_cent(api):
    """The reversal is by the reservation's own amounts, not a recomputation.

    Reserving moves capacity out of both availability figures and cancelling
    moves exactly the same figures back, so the pools finish at precisely the
    values they held before the reservation existed and the pool identity holds
    at every stage.

    Design: Difficulty/compensating_invariant/reservation_cancel_restores_building_pools_without_drift
    """
    bundle = _project_on_a_fully_built_out_base_building(api)
    building_id = bundle["building"]["id"]
    before = get_building(api, building_id)
    assert_money(before["exhaust_capacity_total_cfm"], 80000.00, "exhaust total")
    assert_money(before["power_capacity_total_kw"], 1200.00, "power total")
    assert_money(before["exhaust_available_cfm"], 80000.00, "exhaust_available_cfm")
    assert_money(before["power_available_kw"], 1200.00, "power_available_kw")
    assert_capacity_pool_identity(before)

    reservation = reserve_capacity(
        api,
        bundle["project"]["id"],
        building_id,
        RESERVED_EXHAUST_CFM,
        RESERVED_POWER_KW,
    )
    during = get_building(api, building_id)
    assert reservation["status"] == "RESERVED"
    assert_money(during["exhaust_reserved_cfm"], 18000.00, "exhaust_reserved_cfm")
    assert_money(during["exhaust_available_cfm"], 62000.00, "exhaust_available_cfm")
    assert_money(during["power_reserved_kw"], 250.00, "power_reserved_kw")
    assert_money(during["power_available_kw"], 950.00, "power_available_kw")
    assert_capacity_pool_identity(during)

    cancelled = get_success_data(
        api.cancel_reservation(reservation["id"], LANDLORD_HEADERS)
    )

    assert cancelled["status"] == "CANCELLED"
    after = get_building(api, building_id)
    assert_pools_restored(before, after)
    assert_money(after["exhaust_reserved_cfm"], 0.00, "exhaust_reserved_cfm")
    assert_money(after["exhaust_committed_cfm"], 0.00, "exhaust_committed_cfm")
    assert_money(after["power_reserved_kw"], 0.00, "power_reserved_kw")
    assert_money(after["power_committed_kw"], 0.00, "power_committed_kw")
    assert after["suitability_state"] == "CONVERSION_APPROVED"


def test_the_same_reservation_cannot_be_returned_twice(api):
    """A cancelled reservation has nothing left to give back.

    The second cancellation is refused rather than absorbed, which is what keeps
    the pools from drifting below the value they started at, and the reservation
    is left in the terminal state the first cancellation gave it.

    Design: Difficulty/compensating_invariant/reservation_cancel_restores_building_pools_without_drift
    """
    bundle = _project_on_a_fully_built_out_base_building(api)
    building_id = bundle["building"]["id"]
    reservation = reserve_capacity(
        api,
        bundle["project"]["id"],
        building_id,
        RESERVED_EXHAUST_CFM,
        RESERVED_POWER_KW,
    )
    get_success_data(api.cancel_reservation(reservation["id"], LANDLORD_HEADERS))
    restored = get_building(api, building_id)

    response = api.cancel_reservation(reservation["id"], LANDLORD_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_RESERVATION_STATE.value, 409)

    assert get_reservation(api, reservation["id"])["status"] == "CANCELLED"
    assert_pools_restored(restored, get_building(api, building_id))
    assert_money(
        get_building(api, building_id)["exhaust_available_cfm"],
        80000.00,
        "exhaust_available_cfm",
    )
