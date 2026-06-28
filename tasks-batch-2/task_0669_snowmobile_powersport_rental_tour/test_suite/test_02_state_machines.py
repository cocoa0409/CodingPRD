"""State-machine corner claims: invalid transitions, terminal lockdown, waiver
preconditions/expiry, maintenance blocking, guide release, and the zero-count
closure. Corner section: state_machines."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, TEST_USERS,
    create_trail, create_unit, create_guide, create_departure,
    register_member, register_signed_member,
    create_reservation, create_and_confirm_reservation,
    assign_guide, set_clock,
    setup_checked_out_reservation,
    read_member, read_reservation, read_departure, read_unit, read_guide,
    make_member_headers, make_guide_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_cancel_already_cancelled_reservation_returns_invalid_state(api):
    """PRD §3.9: "Attempting any of these transitions from a state in which it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_already_cancelled_reservation_returns_invalid_state
    """
    trail = create_trail(name="TermT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-02-05T09:00:00Z",
                           ends_at="2027-02-05T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_member()
    res = create_reservation(member, dep["id"], unit["id"])
    validate_success(api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    resp = api.cancel_reservation(res["id"], make_member_headers(member["id"]))
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
    assert read_reservation(res["id"])["reservation_status"] == "CANCELLED"


def test_depart_from_scheduled_returns_invalid_state(api):
    """PRD §3.6: "Once a departure is locked, the tour itself proceeds. A `Guide` assigned
    to the departure departs it, moving it from `LOCKED` to `DEPARTED`."
    PRD §3.9: "Attempting any of these transitions from a state in which it is not defined
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/depart_from_scheduled_returns_invalid_state
    """
    trail = create_trail(name="SchT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    guide = create_guide(max_class="TRAIL")
    dep = create_departure(trail["id"], starts_at="2027-02-07T09:00:00Z",
                           ends_at="2027-02-07T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_signed_member()
    create_and_confirm_reservation(member, dep["id"], unit["id"], expected_version=dep["version"])
    assign_guide(dep["id"], guide["id"])  # assigned but never LOCKED
    set_clock("2027-02-07T09:30:00Z")
    resp = api.depart_departure(dep["id"], make_guide_headers(guide["id"]))
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
    assert read_departure(dep["id"])["status"] == "SCHEDULED"


def test_complete_cancelled_departure_returns_invalid_state(api):
    """PRD §3.3: "that `status` progresses through `LOCKED`, `DEPARTED`, and `COMPLETED`,
    or off to the terminal `CANCELLED`."
    PRD §3.9: "Attempting any of these transitions from a state in which it is not
    defined is rejected with `ERR_INVALID_STATE`."
    PRD §2.1/§3.9: "a guide may only depart or complete a departure they are assigned
    to lead, on pain of `ERR_OWNERSHIP_REQUIRED`" — and that ownership gate applies
    before the business/state gates.

    The guide here is genuinely assigned to the departure before it is cancelled, so
    the request comes from a principal who led the departure. PRD §3.6 says cancellation
    "deactivates its guide assignments," so a faithful reader may treat the (now-inactive)
    assignment either as still satisfying the ownership gate — reaching the terminal-state
    gate and `ERR_INVALID_STATE` — or as no longer owning the departure, yielding
    `ERR_OWNERSHIP_REQUIRED`. PRD does not uniquely determine which precedence outcome
    fires, so either PRD-named rejection is accepted.

    Design: Corner/state_machines/complete_terminal_departure_returns_invalid_state
    """
    trail = create_trail(name="CanT", required_class="TRAIL", max_riders=10)
    dep = create_departure(trail["id"], starts_at="2027-02-09T09:00:00Z",
                           ends_at="2027-02-09T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    guide = create_guide(max_class="TRAIL")
    assign_guide(dep["id"], guide["id"])  # guide genuinely leads this departure
    validate_success(api.cancel_departure(dep["id"], DISPATCH), 200)  # now terminal CANCELLED
    resp = api.complete_departure(dep["id"], make_guide_headers(guide["id"]))
    validate_error_is_one_of(resp, ["ERR_INVALID_STATE", "ERR_OWNERSHIP_REQUIRED"])
    assert read_departure(dep["id"])["status"] == "CANCELLED"


def test_waiver_expires_after_validity_window_on_expire_call(api):
    """PRD §3.1: "A waiver does not stay valid forever: when the clock now is later than
    `waiver_signed_at` plus the waiver validity window of 365 days, the waiver lapses from
    `SIGNED` to `EXPIRED` and its `waiver_signed_at` stamp is cleared. This lapse is
    re-evaluated whenever the logical clock is set, and may also be forced on demand
    through a dispatcher-or-admin re-evaluation capability that moves a stale `SIGNED`
    waiver to `EXPIRED` and clears the stamp".

    Design: Corner/state_machines/waiver_expires_after_validity_window_on_clock_set
    """
    member = register_signed_member(date_of_birth="1980-01-01")  # signed at default clock 2026-04-01
    set_clock("2027-05-01T00:00:00Z")  # > 365 days later
    updated = validate_success(api.expire_waiver(member["id"], DISPATCH), 200)
    assert updated["waiver_status"] == "EXPIRED"
    assert updated["waiver_signed_at"] is None


def test_complete_departure_releases_guide_back_to_available(api):
    """PRD §3.6: "Completion releases the departure's staffing: every active
    `GuideAssignment` has its `active` flag set to false, the departure's `guide_count` is
    reset to zero, and each affected guide returns from `OFF_DUTY` to `AVAILABLE` if they
    hold no other active assignment."

    Design: Corner/state_machines/complete_departure_releases_guide_back_to_available
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "CmpT", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2027-02-13T09:00:00Z", "ends_at": "2027-02-13T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        depart_clock="2027-02-13T09:30:00Z")
    guide = bundle["guide"]
    set_clock("2027-02-13T11:30:00Z")
    validate_success(api.return_reservation(bundle["reservation"]["id"], {"fuel_return_fraction": 1.0}, DISPATCH), 200)
    completed = validate_success(api.complete_departure(bundle["departure"]["id"], make_guide_headers(guide["id"])), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["guide_count"] == 0
    assert read_guide(guide["id"])["status"] == "AVAILABLE"


def test_trail_close_with_no_departures_count_zero(api):
    """PRD §3.7: "The number of departures cancelled this way is counted into the
    `ClosureEvent`'s `cancelled_departure_count`."
    PRD §4: "post[ing] a closure event" returns `201 Created`.

    Design: Corner/state_machines/trail_close_with_no_departures_count_zero
    """
    trail = create_trail(name="EmptyT", required_class="TRAIL", max_riders=10)
    event = validate_success(
        api.post_closure(trail["id"], {"new_condition": "CLOSED", "reason": "preemptive"}, DISPATCH), 201)
    assert event["cancelled_departure_count"] == 0
    assert validate_success(api.get_trail(trail["id"], DISPATCH), 200)["condition"] == "CLOSED"
