"""Charter / CrewAssignment / SlotReservation state machines: the weather-hold
reschedule cycle, crew lock/unlock cycle, schedule preconditions that depend on
sibling-entity state, invalid transitions, and terminal-state lockdown. Covers
difficulty-design non-linear-state-machine and cross-entity-state-dependency
instances and the corner state_machines instances rooted in §3.7–§3.8.
"""
from test_helpers import (
    validate_success,
    validate_error,
    make_captain_headers,
    pin_clock,
    create_marina,
    create_dock_slot,
    create_boat,
    create_captain,
    create_mate,
    create_permit,
    create_customer,
    create_charter,
    create_booking,
    pay_deposit,
    reserve_slot,
    assign_captain,
    assign_mate,
    get_charter,
    setup_scheduled_charter,
    setup_weather_hold_charter,
    setup_sailed_charter,
    setup_sailed_offshore_charter,
    api_client,
)
from test_helpers.fixtures import FLEET_MANAGER, DOCK_MASTER


# ===========================================================================
# Difficulty: non_linear_state_machine / charter_weather_hold_reschedule_cycle
# ===========================================================================

def test_charter_returns_to_scheduled_after_reschedule(api):
    """PRD §3.7: "To bring a held charter back, the `FleetManager` **reschedules**
    it to a new window, moving it `WEATHER_HOLD → SCHEDULED`."

    A SCHEDULED -> WEATHER_HOLD -> SCHEDULED loop returns the charter to SCHEDULED
    (a true cycle edge), and overwrites depart_at with the new window.

    Design: Difficulty/non_linear_state_machine/charter_weather_hold_reschedule_cycle
    """
    pin_clock("2026-09-01T00:00:00Z")
    ctx = setup_weather_hold_charter(
        charter_overrides={"depart_at": "2026-09-10T12:00:00Z",
                           "return_at": "2026-09-10T16:00:00Z"})
    res = api.reschedule_charter(
        ctx["charter"]["id"],
        {"depart_at": "2026-09-12T12:00:00Z", "return_at": "2026-09-12T16:00:00Z"},
        FLEET_MANAGER,
    )
    charter = validate_success(res, expected_status=200)
    assert charter["status"] == "SCHEDULED"
    assert charter["depart_at"][:19] == "2026-09-12T12:00:00", charter["depart_at"]


def test_reschedule_increments_weather_reschedule_count(api):
    """PRD §3.7: "On success the charter's `depart_at` and `return_at` are
    overwritten with the new window ... `weather_reschedule_count` increases by 1."

    weather_reschedule_count goes 0 -> 1 across the cycle, proving the loop edge.

    Design: Difficulty/non_linear_state_machine/charter_weather_hold_reschedule_cycle
    """
    pin_clock("2026-09-01T00:00:00Z")
    ctx = setup_weather_hold_charter(
        charter_overrides={"depart_at": "2026-09-10T12:00:00Z",
                           "return_at": "2026-09-10T16:00:00Z"})
    assert ctx["charter"]["weather_reschedule_count"] == 0
    api.reschedule_charter(
        ctx["charter"]["id"],
        {"depart_at": "2026-09-12T12:00:00Z", "return_at": "2026-09-12T16:00:00Z"},
        FLEET_MANAGER,
    )
    fresh = get_charter(ctx["charter"]["id"])
    assert fresh["weather_reschedule_count"] == 1, fresh["weather_reschedule_count"]


# ===========================================================================
# Difficulty: non_linear_state_machine / crew_assignment_lock_unlock_cycle
# ===========================================================================

def test_crew_assignment_relocks_to_tentative_on_weather_hold(api):
    """PRD §3.7: "it floats the crew back to the roster pool by moving every crew
    assignment from `LOCKED` back to `TENTATIVE`."

    Scheduling locks crew to LOCKED; a weather hold returns the assignment from
    LOCKED back to TENTATIVE — a cycle edge on the CrewAssignment entity.

    Design: Difficulty/non_linear_state_machine/crew_assignment_lock_unlock_cycle
    """
    pin_clock("2026-09-01T00:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2026-09-10T12:00:00Z",
                           "return_at": "2026-09-10T16:00:00Z"})
    crew_id = ctx["crew"]["id"]
    locked = validate_success(api.get_crew_assignment(crew_id, FLEET_MANAGER), 200)
    assert locked["status"] == "LOCKED"
    api.weather_hold_charter(ctx["charter"]["id"], make_captain_headers(ctx["captain"]["id"]))
    crew = validate_success(api.get_crew_assignment(crew_id, FLEET_MANAGER), 200)
    assert crew["status"] == "TENTATIVE", crew["status"]


def test_charter_enters_weather_hold_on_hold_call(api):
    """PRD §3.7: "A `Captain` may put a `SCHEDULED` charter on a weather hold,
    moving it `SCHEDULED → WEATHER_HOLD`."

    The hold transition (which drives the crew LOCKED->TENTATIVE cycle edge) moves
    the charter itself into WEATHER_HOLD.

    Design: Difficulty/non_linear_state_machine/crew_assignment_lock_unlock_cycle
    """
    pin_clock("2026-09-01T00:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2026-09-10T12:00:00Z",
                           "return_at": "2026-09-10T16:00:00Z"})
    res = api.weather_hold_charter(ctx["charter"]["id"],
                                   make_captain_headers(ctx["captain"]["id"]))
    charter = validate_success(res, expected_status=200)
    assert charter["status"] == "WEATHER_HOLD", charter["status"]


# ===========================================================================
# Difficulty: cross_entity_state_dependency / charter_schedule_requires_boat_in_service
# ===========================================================================

def test_schedule_rejected_when_boat_in_drydock(api):
    """PRD §3.7: "Scheduling demands that the boat be `IN_SERVICE` (else
    `ERR_BOAT_NOT_IN_SERVICE`)."

    A fully-crewed, fully-slotted DRAFT charter whose boat is set to DRYDOCK is
    rejected at schedule with ERR_BOAT_NOT_IN_SERVICE.

    Design: Difficulty/cross_entity_state_dependency/charter_schedule_requires_boat_in_service
    """
    marina = create_marina(name="Boat Marina")
    slot = create_dock_slot(marina["id"], slot_label="I1")
    boat = create_boat(marina["id"], name="Dryboat")
    captain = create_captain(marina["id"])
    charter = create_charter(marina["id"], boat["id"],
                             depart_at="2027-01-10T12:00:00Z",
                             return_at="2027-01-10T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    api.set_boat_status(boat["id"], {"status": "DRYDOCK"}, FLEET_MANAGER)
    res = api.schedule_charter(charter["id"], FLEET_MANAGER)
    validate_error(res, "ERR_BOAT_NOT_IN_SERVICE")


def test_schedule_succeeds_when_boat_in_service(api):
    """PRD §3.7: "Scheduling demands that the boat be `IN_SERVICE` (else
    `ERR_BOAT_NOT_IN_SERVICE`) ... When these hold, scheduling ... increments the
    charter's `version`."

    The same charter with the boat left IN_SERVICE schedules to SCHEDULED — the
    boat-state gate is the only difference from the DRYDOCK rejection.

    Design: Difficulty/cross_entity_state_dependency/charter_schedule_requires_boat_in_service
    """
    pin_clock("2027-01-01T00:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2027-01-10T12:00:00Z",
                           "return_at": "2027-01-10T16:00:00Z"})
    assert ctx["charter"]["status"] == "SCHEDULED"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / charter_schedule_requires_marina_open
# ===========================================================================

def test_schedule_rejected_when_marina_closed(api):
    """PRD §3.7: "the marina be `OPEN` (else `ERR_MARINA_NOT_OPEN`)."

    A fully-crewed, fully-slotted DRAFT charter whose marina is CLOSED is rejected
    at schedule with ERR_MARINA_NOT_OPEN.

    Design: Difficulty/cross_entity_state_dependency/charter_schedule_requires_marina_open
    """
    marina = create_marina(name="Closed Marina")
    slot = create_dock_slot(marina["id"], slot_label="J1")
    boat = create_boat(marina["id"], name="Openboat")
    captain = create_captain(marina["id"])
    charter = create_charter(marina["id"], boat["id"],
                             depart_at="2027-01-10T12:00:00Z",
                             return_at="2027-01-10T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    api.set_marina_status(marina["id"], {"status": "CLOSED"}, DOCK_MASTER)
    res = api.schedule_charter(charter["id"], FLEET_MANAGER)
    validate_error(res, "ERR_MARINA_NOT_OPEN")


def test_schedule_rejected_when_marina_restricted(api):
    """PRD §3.1: "The `DockMaster` may later move a marina between `OPEN`,
    `RESTRICTED`, and `CLOSED`; both `RESTRICTED` and `CLOSED` gate new slot
    occupations."
    PRD §3.7: "the marina be `OPEN` (else `ERR_MARINA_NOT_OPEN`)."

    A RESTRICTED marina (which is not OPEN) also fails the schedule gate with
    ERR_MARINA_NOT_OPEN — the Charter->Marina state pair.

    Design: Difficulty/cross_entity_state_dependency/charter_schedule_requires_marina_open
    """
    marina = create_marina(name="Restricted Marina")
    slot = create_dock_slot(marina["id"], slot_label="J2")
    boat = create_boat(marina["id"], name="Resboat")
    captain = create_captain(marina["id"])
    charter = create_charter(marina["id"], boat["id"],
                             depart_at="2027-01-10T12:00:00Z",
                             return_at="2027-01-10T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    api.set_marina_status(marina["id"], {"status": "RESTRICTED"}, DOCK_MASTER)
    res = api.schedule_charter(charter["id"], FLEET_MANAGER)
    validate_error(res, "ERR_MARINA_NOT_OPEN")


# ===========================================================================
# Corner: state_machines / charter_initial_state_is_draft
# ===========================================================================

def test_charter_created_in_draft_with_zero_aggregates(api):
    """PRD §3.2: "A `FleetManager` opens a trip by creating a **Charter**, which
    begins life in `DRAFT` ... A fresh charter records `seats_booked` at 0,
    `catch_total` at 0, and `weather_reschedule_count` at 0."

    Design: Corner/state_machines/charter_initial_state_is_draft
    """
    marina = create_marina(name="Init Marina")
    boat = create_boat(marina["id"], name="Initboat")
    res = api.create_charter(
        {"marina_id": marina["id"], "boat_id": boat["id"], "trip_type": "INSHORE",
         "depart_at": "2027-10-10T12:00:00Z", "return_at": "2027-10-10T16:00:00Z",
         "base_seat_price_cents": 10000, "seats_total": 6},
        FLEET_MANAGER,
    )
    charter = validate_success(res, expected_status=201)
    assert charter["status"] == "DRAFT"
    assert charter["seats_booked"] == 0
    assert charter["weather_reschedule_count"] == 0


# ===========================================================================
# Corner: state_machines / reschedule_from_scheduled_not_on_hold_rejected
# ===========================================================================

def test_reschedule_on_scheduled_charter_rejected(api):
    """PRD §3.7: "if the charter is not on hold the request is rejected with
    `ERR_CHARTER_NOT_ON_HOLD`."

    Design: Corner/state_machines/reschedule_from_scheduled_not_on_hold_rejected
    """
    pin_clock("2027-08-01T00:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2027-08-10T12:00:00Z",
                           "return_at": "2027-08-10T16:00:00Z"})
    res = api.reschedule_charter(
        ctx["charter"]["id"],
        {"depart_at": "2027-08-12T12:00:00Z", "return_at": "2027-08-12T16:00:00Z"},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_CHARTER_NOT_ON_HOLD")


# ===========================================================================
# Corner: state_machines / cancel_from_settled_terminal_rejected
# ===========================================================================

def test_cancel_on_settled_charter_rejected(api):
    """PRD §3.8: "A charter may be **cancelled** by the `FleetManager` from
    `DRAFT`, `SCHEDULED`, or `WEATHER_HOLD`, moving it to `CANCELLED`; from any
    other state the request is rejected with `ERR_CHARTER_NOT_CANCELLABLE`."

    A SETTLED charter is terminal; cancel returns ERR_CHARTER_NOT_CANCELLABLE.

    Design: Corner/state_machines/cancel_from_settled_terminal_rejected
    """
    pin_clock("2027-08-10T12:00:00Z")
    ctx = setup_sailed_charter(
        charter_overrides={"depart_at": "2027-08-10T12:00:00Z",
                           "return_at": "2027-08-10T16:00:00Z"})
    api.settle_charter(ctx["charter"]["id"], FLEET_MANAGER)
    res = api.cancel_charter(ctx["charter"]["id"], FLEET_MANAGER)
    validate_error(res, "ERR_CHARTER_NOT_CANCELLABLE")


# ===========================================================================
# Corner: state_machines / sail_before_depart_time_rejected
# ===========================================================================

def test_sail_before_depart_time_rejected(api):
    """PRD §3.8: "Sailing requires the charter to be `SCHEDULED` ... the current
    clock to have reached or passed `depart_at` (else `ERR_DEPART_TIME_NOT_REACHED`)."

    Design: Corner/state_machines/sail_before_depart_time_rejected
    """
    pin_clock("2027-08-09T00:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2027-08-10T12:00:00Z",
                           "return_at": "2027-08-10T16:00:00Z"})
    res = api.sail_charter(ctx["charter"]["id"], make_captain_headers(ctx["captain"]["id"]))
    validate_error(res, "ERR_DEPART_TIME_NOT_REACHED")


# ===========================================================================
# Corner: state_machines / settle_bag_limit_exceeded_rejected
# ===========================================================================

def test_settle_rejected_when_catch_exceeds_bag_limit(api):
    """PRD §3.8: "Settlement requires the charter to be `SAILED` ... and, when a
    permit is attached, the kept-fish `catch_total` to be within the permit's
    `daily_bag_limit` (else `ERR_BAG_LIMIT_EXCEEDED`)."

    permit daily_bag_limit 10; a report keeping 11 fish -> catch_total 11 > 10 ->
    ERR_BAG_LIMIT_EXCEEDED.

    Design: Corner/state_machines/settle_bag_limit_exceeded_rejected
    """
    pin_clock("2027-09-10T06:00:00Z")
    ctx = setup_sailed_offshore_charter(
        daily_bag_limit=10,
        charter_overrides={"depart_at": "2027-09-10T06:00:00Z",
                           "return_at": "2027-09-10T18:00:00Z"})
    from test_helpers import file_catch_report
    file_catch_report(ctx["charter"]["id"], ctx["captain"]["id"], "Snapper", 11, released_count=0)
    res = api.settle_charter(ctx["charter"]["id"], FLEET_MANAGER)
    validate_error(res, "ERR_BAG_LIMIT_EXCEEDED")


# ===========================================================================
# Corner: state_machines / schedule_offshore_without_mate_rejected
# ===========================================================================

def test_schedule_offshore_without_mate_rejected(api):
    """PRD §3.7: "For an offshore trip, scheduling additionally requires a `MATE`
    crew assignment with a non-null `mate_id` (else `ERR_NO_MATE_ASSIGNED`)."

    Design: Corner/state_machines/schedule_offshore_without_mate_rejected
    """
    marina = create_marina(name="NoMate Marina")
    slot = create_dock_slot(marina["id"], slot_label="R1", max_boat_length_ft=50)
    boat = create_boat(marina["id"], name="NoMateboat", length_ft=42,
                       passenger_capacity=8, offshore_rated=True)
    permit = create_permit(daily_bag_limit=20)
    captain = create_captain(marina["id"], uscg_license_grade="MASTER_100")
    charter = create_charter(marina["id"], boat["id"], trip_type="OFFSHORE",
                             permit_id=permit["id"], base_seat_price_cents=30000,
                             seats_total=8, depart_at="2027-10-10T06:00:00Z",
                             return_at="2027-10-10T18:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    res = api.schedule_charter(charter["id"], FLEET_MANAGER)
    validate_error(res, "ERR_NO_MATE_ASSIGNED")


# ===========================================================================
# Corner: state_machines / charter_cancel_cascade_releases_crew_and_slot
# ===========================================================================

def test_charter_cancel_releases_crew_and_slot(api):
    """PRD §3.8: "Cancelling cascades: every non-terminal booking is cancelled ...
    every crew assignment is `RELEASED`, the slot reservation is `RELEASED`, and
    the charter's `version` increments."

    Cancelling a SCHEDULED charter sets its crew assignment and its slot
    reservation to RELEASED.

    Design: Corner/state_machines/charter_cancel_cascade_releases_crew_and_slot
    """
    pin_clock("2027-11-01T00:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2027-11-10T12:00:00Z",
                           "return_at": "2027-11-10T16:00:00Z"})
    api.cancel_charter(ctx["charter"]["id"], FLEET_MANAGER)
    crew = validate_success(api.get_crew_assignment(ctx["crew"]["id"], FLEET_MANAGER), 200)
    res = validate_success(api.get_slot_reservation(ctx["reservation"]["id"], FLEET_MANAGER), 200)
    assert crew["status"] == "RELEASED", crew["status"]
    assert res["status"] == "RELEASED", res["status"]


# ===========================================================================
# Corner: calculations / reschedule_fee_first_tier_accrued
# ===========================================================================

def test_first_reschedule_fee_flat_1000_for_standard_customer(api):
    """PRD §3.7: "The fee tier keys on `weather_reschedule_count` **as it stands
    before this reschedule increments it**: a count of 0 means the first
    reschedule and a flat 1000 cents ... Whatever fee results is added to that
    booking's running `reschedule_fee_total_cents`."

    First reschedule (count 0) on a STANDARD customer's booking -> 1000 accrued.

    Design: Corner/calculations/reschedule_fee_first_tier_accrued
    """
    pin_clock("2028-01-01T00:00:00Z")
    ctx = setup_weather_hold_charter(
        charter_overrides={"depart_at": "2028-01-10T12:00:00Z",
                           "return_at": "2028-01-10T16:00:00Z"},
        customer_loyalty="STANDARD")
    api.reschedule_charter(
        ctx["charter"]["id"],
        {"depart_at": "2028-01-12T12:00:00Z", "return_at": "2028-01-12T16:00:00Z"},
        FLEET_MANAGER,
    )
    booking = validate_success(api.get_booking(ctx["booking"]["id"], FLEET_MANAGER), 200)
    assert booking["reschedule_fee_total_cents"] == 1000, booking["reschedule_fee_total_cents"]
