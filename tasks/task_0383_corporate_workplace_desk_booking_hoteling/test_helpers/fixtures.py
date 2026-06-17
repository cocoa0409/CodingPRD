"""Composite setup helpers for the Workplace Desk Booking & Hoteling API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of every test.

Fixtures use get_success_data() (lenient 2xx validator) internally so that a
setup failure surfaces as a clear "Setup failed" error rather than a confusing
downstream assertion error.

Identity threading: the Employee role is entity_backed. After creating an
Employee, any ownership-gated call (create reservation, check-in, complete,
cancel, amenity add/cancel, visitor-pass request-changes/approve) MUST use
make_employee_headers(employee_id) so X-User-ID equals the owning entity's id.
FacilityManager / Receptionist / Analyst are opaque and use the shared headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_employee_headers
from .factories import (
    create_site_payload, create_floor_payload, create_capacity_policy_payload,
    create_neighborhood_payload, create_seat_payload, create_room_payload,
    create_employee_payload, create_reservation_payload, create_amenity_payload,
    create_visitor_pass_payload,
)

FM = TEST_USERS["facility_manager_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]
ANALYST = TEST_USERS["analyst_headers"]

_email_counter = [0]


def _unique_email(prefix="emp"):
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@x.com"


# ---------------------------------------------------------------------------
# Primitive creators (each returns the created resource's data dict)
# ---------------------------------------------------------------------------
def create_site(name="Test HQ", **overrides):
    resp = api_client.create_site(create_site_payload(name=name, **overrides), FM)
    return get_success_data(resp)


def create_floor(site_id, level=1, workday_start_minute=540, workday_end_minute=1080, **overrides):
    resp = api_client.create_floor(
        site_id,
        create_floor_payload(level=level, workday_start_minute=workday_start_minute,
                             workday_end_minute=workday_end_minute, **overrides),
        FM,
    )
    return get_success_data(resp)


def create_capacity_policy(floor_id, **overrides):
    resp = api_client.create_capacity_policy(floor_id, create_capacity_policy_payload(**overrides), FM)
    return get_success_data(resp)


def create_neighborhood(floor_id, name="Zone", **overrides):
    resp = api_client.create_neighborhood(floor_id, create_neighborhood_payload(name=name, **overrides), FM)
    return get_success_data(resp)


def create_seat(neighborhood_id, label="S1", **overrides):
    resp = api_client.create_seat(neighborhood_id, create_seat_payload(label=label, **overrides), FM)
    return get_success_data(resp)


def create_room(floor_id, label="R1", seats_capacity=6, **overrides):
    resp = api_client.create_room(floor_id, create_room_payload(label=label, seats_capacity=seats_capacity, **overrides), FM)
    return get_success_data(resp)


def create_employee(email=None, full_name="Test Emp", team_code="ENG", **overrides):
    if email is None:
        email = _unique_email()
    resp = api_client.create_employee(
        create_employee_payload(email=email, full_name=full_name, team_code=team_code, **overrides), FM)
    return get_success_data(resp)


def set_clock(current_date, current_minute):
    resp = api_client.set_clock(current_date, current_minute, FM)
    return get_success_data(resp)


def seat_version(seat_id):
    return get_success_data(api_client.get_seat(seat_id, FM))["version"]


def room_version(room_id):
    return get_success_data(api_client.get_room(room_id, FM))["version"]


def create_seat_reservation(employee_id, seat_id, booking_date, start_minute, end_minute,
                            expected_seat_version=None):
    """Create a SEAT reservation owned by employee_id. Looks up the live seat
    version if not supplied so the OCC guard passes."""
    if expected_seat_version is None:
        expected_seat_version = seat_version(seat_id)
    payload = create_reservation_payload(
        employee_id=employee_id, resource_type="SEAT", seat_id=seat_id,
        booking_date=booking_date, start_minute=start_minute, end_minute=end_minute,
        expected_seat_version=expected_seat_version,
    )
    resp = api_client.create_reservation(payload, make_employee_headers(employee_id))
    return get_success_data(resp)


def create_room_reservation(employee_id, room_id, booking_date, start_minute, end_minute,
                            expected_room_version=None):
    if expected_room_version is None:
        expected_room_version = room_version(room_id)
    payload = create_reservation_payload(
        employee_id=employee_id, resource_type="ROOM", room_id=room_id, seat_id=None,
        booking_date=booking_date, start_minute=start_minute, end_minute=end_minute,
        expected_room_version=expected_room_version,
    )
    resp = api_client.create_reservation(payload, make_employee_headers(employee_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: base floor-plan scaffolding
# ---------------------------------------------------------------------------
def setup_floor_plan(level=1, cap_pct=100, team_code=None, enforce_team_zoning=False,
                     grace_minutes=30, max_active=5, seat_label="S1",
                     workday_start_minute=540, workday_end_minute=1080,
                     clock_date=None, clock_minute=500):
    """Active site + floor + capacity policy + one neighborhood + one seat +
    one employee, with the logical clock set. Returns a dict of the created
    resources. The default policy disables team zoning and uses a generous
    reservation limit so unrelated gates do not interfere.
    """
    site = create_site(name=f"HQ-{level}-{_email_counter[0]}")
    floor = create_floor(site["id"], level=level,
                         workday_start_minute=workday_start_minute,
                         workday_end_minute=workday_end_minute)
    policy = create_capacity_policy(
        floor["id"], max_active_reservations_per_employee=max_active,
        grace_minutes=grace_minutes, enforce_team_zoning=enforce_team_zoning)
    nb_kwargs = {"capacity_cap_pct": cap_pct}
    if team_code is not None:
        nb_kwargs["team_code"] = team_code
    neighborhood = create_neighborhood(floor["id"], name=f"Zone-{level}", **nb_kwargs)
    seat = create_seat(neighborhood["id"], label=seat_label)
    employee = create_employee(team_code=(team_code or "ENG"))
    if clock_date is not None:
        set_clock(clock_date, clock_minute)
    return {
        "site": site, "floor": floor, "policy": policy,
        "neighborhood": neighborhood, "seat": seat, "employee": employee,
    }


def setup_neighborhood_with_seats(num_seats, cap_pct=100, enforce_team_zoning=False,
                                  team_code=None, level=1, max_active=5, grace_minutes=30,
                                  clock_date=None, clock_minute=500):
    """Floor + neighborhood with `num_seats` seats. Returns
    (floor, neighborhood, [seats]). Useful for capacity-cap boundary tests."""
    site = create_site(name=f"HQ-NS-{level}-{_email_counter[0]}")
    floor = create_floor(site["id"], level=level)
    policy = create_capacity_policy(
        floor["id"], max_active_reservations_per_employee=max_active,
        grace_minutes=grace_minutes, enforce_team_zoning=enforce_team_zoning)
    nb_kwargs = {"capacity_cap_pct": cap_pct}
    if team_code is not None:
        nb_kwargs["team_code"] = team_code
    neighborhood = create_neighborhood(floor["id"], name=f"Zone-NS-{level}", **nb_kwargs)
    seats = [create_seat(neighborhood["id"], label=f"S{i}") for i in range(1, num_seats + 1)]
    if clock_date is not None:
        set_clock(clock_date, clock_minute)
    return floor, neighborhood, seats


# ---------------------------------------------------------------------------
# Tier 1 / 3: reservation lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_booked_reservation(booking_date="2026-06-20", start_minute=540, end_minute=600,
                             grace_minutes=30, clock_minute=500, **floor_kwargs):
    """Floor plan + one BOOKED reservation. Returns (env, reservation)."""
    env = setup_floor_plan(grace_minutes=grace_minutes, clock_date=booking_date,
                           clock_minute=clock_minute, **floor_kwargs)
    resv = create_seat_reservation(
        env["employee"]["id"], env["seat"]["id"], booking_date, start_minute, end_minute)
    return env, resv


def setup_checked_in_reservation(booking_date="2026-06-20", start_minute=540, end_minute=1080,
                                 grace_minutes=30, checkin_minute=545, **floor_kwargs):
    """Floor plan + one reservation walked to CHECKED_IN. Returns (env, reservation).
    The clock is left at checkin_minute (within grace)."""
    env = setup_floor_plan(grace_minutes=grace_minutes, clock_date=booking_date,
                           clock_minute=checkin_minute, **floor_kwargs)
    resv = create_seat_reservation(
        env["employee"]["id"], env["seat"]["id"], booking_date, start_minute, end_minute)
    resp = api_client.checkin_reservation(resv["id"], make_employee_headers(env["employee"]["id"]))
    resv = get_success_data(resp)
    return env, resv


# ---------------------------------------------------------------------------
# Tier 4: amenity chargeback setups
# ---------------------------------------------------------------------------
def add_amenity_line(reservation_id, employee_id, amenity_code, unit_price_cents, quantity):
    resp = api_client.create_amenity(
        reservation_id,
        create_amenity_payload(amenity_code=amenity_code, unit_price_cents=unit_price_cents, quantity=quantity),
        make_employee_headers(employee_id),
    )
    return get_success_data(resp)


def approve_amenity_line(amenity_id):
    return get_success_data(api_client.approve_amenity(amenity_id, FM))


def setup_reservation_with_amenity_lines(lines, booking_date="2026-06-20",
                                         start_minute=540, end_minute=1080,
                                         checkin_minute=545, level=1):
    """CHECKED_IN reservation carrying the given amenity lines.

    `lines` is a list of dicts: {code, unit_price_cents, quantity, approve: bool}.
    Returns (env, reservation, [amenity_line_data]). Each amenity_line_data is
    the post-approval (or post-create) line.
    """
    env, resv = setup_checked_in_reservation(
        booking_date=booking_date, start_minute=start_minute, end_minute=end_minute,
        checkin_minute=checkin_minute, level=level)
    emp_id = env["employee"]["id"]
    created = []
    for spec in lines:
        line = add_amenity_line(resv["id"], emp_id, spec["code"],
                                spec["unit_price_cents"], spec["quantity"])
        if spec.get("approve"):
            line = approve_amenity_line(line["id"])
        created.append(line)
    return env, resv, created


def complete_reservation(reservation_id, employee_id):
    return get_success_data(
        api_client.complete_reservation(reservation_id, make_employee_headers(employee_id)))


# ---------------------------------------------------------------------------
# Strike accrual / suspension setups
# ---------------------------------------------------------------------------
def release_reservation_as_no_show(reservation_id):
    """FacilityManager force-releases a grace-expired reservation."""
    return get_success_data(api_client.release_reservation(reservation_id, FM))


def accrue_strikes(env, num_strikes, booking_date="2026-07-04", base_start=540,
                   window=60, gap=160):
    """Drive the env's single employee through `num_strikes` NO_SHOW releases on
    the env's single seat, returning the list of released reservation ids.

    Each strike: set clock before start -> create reservation -> set clock past
    deadline -> release. STRIKE_WEIGHT=10, so num_strikes*10 is the resulting
    strike_score (assuming no prior good check-ins). Reuses the same seat across
    distinct, non-overlapping windows; the seat version is re-read each time.
    """
    emp_id = env["employee"]["id"]
    seat_id = env["seat"]["id"]
    released = []
    start = base_start
    for i in range(num_strikes):
        end = start + window
        set_clock(booking_date, start - 40 if start - 40 >= 0 else 0)
        resv = create_seat_reservation(emp_id, seat_id, booking_date, start, end)
        # advance past the deadline (start + grace) and release
        set_clock(booking_date, end + 100)
        release_reservation_as_no_show(resv["id"])
        released.append(resv["id"])
        start = end + gap
    return released


def setup_suspended_employee(booking_date="2026-07-04", level=14):
    """Floor plan whose employee has accrued 3 NO_SHOW strikes (score 30) and is
    therefore SUSPENDED. Returns the env. A spare seat 'S2' is also created so a
    fresh booking attempt has an unbooked target."""
    env = setup_floor_plan(level=level, grace_minutes=30, clock_date=booking_date,
                           clock_minute=500)
    # second seat in the same neighborhood for the eventual fresh-booking attempt
    env["seat2"] = create_seat(env["neighborhood"]["id"], label="S2")
    accrue_strikes(env, 3, booking_date=booking_date)
    return env


# ---------------------------------------------------------------------------
# Visitor pass setups
# ---------------------------------------------------------------------------
def setup_visitor_pass(booking_date="2026-06-24", start_minute=600, end_minute=720,
                       level=5, clock_minute=500):
    """Floor + neighborhood + visitor seat + host employee + one REQUESTED
    visitor pass. Returns (env, visitor_pass)."""
    site = create_site(name=f"HQ-VP-{level}-{_email_counter[0]}")
    floor = create_floor(site["id"], level=level)
    create_capacity_policy(floor["id"], enforce_team_zoning=False, grace_minutes=30,
                          max_active_reservations_per_employee=5)
    neighborhood = create_neighborhood(floor["id"], name=f"VPZone-{level}")
    seat = create_seat(neighborhood["id"], label="V1")
    host = create_employee(team_code="ENG")
    set_clock(booking_date, clock_minute)
    resp = api_client.create_visitor_pass(
        create_visitor_pass_payload(
            host_employee_id=host["id"], seat_id=seat["id"], visitor_name="Guest",
            booking_date=booking_date, start_minute=start_minute, end_minute=end_minute),
        RECEPTION,
    )
    vp = get_success_data(resp)
    env = {"site": site, "floor": floor, "neighborhood": neighborhood,
           "seat": seat, "host": host}
    return env, vp


def setup_room_floor(level=16, turnover_buffer_minute=15, clock_date="2026-07-07",
                     clock_minute=500):
    """Floor + one room + two employees + clock. Returns
    (floor, room, employee_a, employee_b)."""
    site = create_site(name=f"HQ-RM-{level}-{_email_counter[0]}")
    floor = create_floor(site["id"], level=level)
    create_capacity_policy(floor["id"], enforce_team_zoning=False, grace_minutes=30,
                          max_active_reservations_per_employee=5)
    room = create_room(floor["id"], label="R1", seats_capacity=8,
                       turnover_buffer_minute=turnover_buffer_minute)
    emp_a = create_employee(team_code="ENG")
    emp_b = create_employee(team_code="ENG")
    set_clock(clock_date, clock_minute)
    return floor, room, emp_a, emp_b
