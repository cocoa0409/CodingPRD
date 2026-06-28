"""Composite setup helpers for multi-step test prerequisites.

The harness re-launches the server and clears the database before EVERY test, so
every fixture builds its preconditions from scratch using only PRD-declared
endpoints. Fixtures use get_success_data() (lenient validator) so setup failures
surface as clear "Setup failed" errors rather than confusing assertions.

Identity threading: after creating a Member, any ownership-gated call (request /
confirm / cancel booking, sign waiver, enroll, withdraw) uses
make_member_headers(member["id"]) — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_facility_payload,
    create_lane_payload,
    create_machine_payload,
    create_maintenance_payload,
    create_member_payload,
    create_waiver_payload,
    create_instructor_payload,
    create_booking_payload,
    create_program_payload,
    create_enrollment_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_manager_headers,
    make_front_desk_headers,
)

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"


# ─── Clock control ────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the server logical clock (FacilityManager only)."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


def reset_clock():
    """Restore the startup-default logical clock."""
    return set_clock(DEFAULT_CLOCK)


# ─── Tier 1 / 2: Base resource creation ───────────────────────────────────────

def create_facility(**overrides):
    """Create a facility. Defaults to hourly_rate_cents=4000, token_price_cents=500."""
    payload = create_facility_payload(
        hourly_rate_cents=overrides.pop("hourly_rate_cents", 4000),
        token_price_cents=overrides.pop("token_price_cents", 500),
        **overrides,
    )
    return get_success_data(api_client.create_facility(payload, MANAGER))


def create_lane(facility_id, **overrides):
    """Create a lane under a facility (CAGE, buffer 0 by default)."""
    payload = create_lane_payload(facility_id, **overrides)
    return get_success_data(api_client.create_lane(payload, MANAGER))


def create_machine(facility_id, lane_id, model="WHEEL"):
    """Install a pitching machine on a lane."""
    payload = create_machine_payload(facility_id, lane_id, model=model)
    return get_success_data(api_client.create_machine(payload, MANAGER))


def create_instructor(facility_id, **overrides):
    """Create an instructor under a facility."""
    payload = create_instructor_payload(facility_id, **overrides)
    return get_success_data(api_client.create_instructor(payload, MANAGER))


def create_member(facility_id, tier="NONE", **overrides):
    """Register a member under a facility."""
    payload = create_member_payload(facility_id, tier=tier, **overrides)
    return get_success_data(api_client.create_member(payload, MANAGER))


def sign_waiver(facility_id, member_id):
    """Sign a waiver for a member, acting as that member (X-User-ID == member_id)."""
    payload = create_waiver_payload(facility_id, member_id)
    return get_success_data(
        api_client.create_waiver(payload, make_member_headers(member_id))
    )


def top_up(member_id, tokens):
    """Top up a member's wallet (FrontDesk)."""
    return get_success_data(
        api_client.wallet_top_up(member_id, {"tokens": tokens}, FRONT_DESK)
    )


def lane_version(lane_id):
    """Read the current version of a lane (for OCC expected_lane_version)."""
    lane = get_success_data(api_client.get_lane(lane_id, MANAGER))
    return lane["version"]


def program_version(program_id):
    """Read the current version of a program (for OCC expected_program_version)."""
    prog = get_success_data(api_client.get_program(program_id, MANAGER))
    return prog["version"]


# ─── Composite scenarios ──────────────────────────────────────────────────────

def setup_member_ready(
    facility_overrides=None,
    lane_overrides=None,
    tier="NONE",
    waiver=True,
    tokens=0,
):
    """Facility + lane + member, optionally with a signed waiver and a wallet top-up.

    Returns (facility, lane, member). The member is the canonical booking subject;
    use make_member_headers(member["id"]) for ownership-gated calls.
    """
    facility = create_facility(**(facility_overrides or {}))
    lane = create_lane(facility["id"], **(lane_overrides or {}))
    member = create_member(facility["id"], tier=tier)
    if waiver:
        sign_waiver(facility["id"], member["id"])
    if tokens:
        top_up(member["id"], tokens)
    # Re-read member so token_balance / waiver_ok reflect the side effects.
    member = get_success_data(api_client.get_member(member["id"], MANAGER))
    return facility, lane, member


def request_booking(facility, lane_id, member, kind, pay_mode, start_utc, end_utc, **overrides):
    """Request a booking on behalf of the member. Returns the REQUESTED booking."""
    payload = create_booking_payload(
        facility["id"], lane_id, member["id"], kind, pay_mode, start_utc, end_utc, **overrides
    )
    return get_success_data(
        api_client.create_booking(payload, make_member_headers(member["id"]))
    )


def confirm_booking(booking_id, member_id, lane_id):
    """Confirm a booking with a fresh expected_lane_version. Returns the CONFIRMED booking."""
    ver = lane_version(lane_id)
    return get_success_data(
        api_client.confirm_booking(
            booking_id, {"expected_lane_version": ver}, make_member_headers(member_id)
        )
    )


def create_confirmed_booking(
    facility, lane, member, kind="OPEN_SLOT", pay_mode="TOKEN",
    start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z", **overrides
):
    """Request + confirm a booking on the given lane. Returns the CONFIRMED booking."""
    booking = request_booking(
        facility, lane["id"], member, kind, pay_mode, start_utc, end_utc, **overrides
    )
    return confirm_booking(booking["id"], member["id"], lane["id"])


def run_completed_session(
    facility, lane, member, start_utc, end_utc, machine_id=None, pay_mode="TOKEN"
):
    """Drive one booking REQUESTED -> CONFIRMED -> CHECKED_IN -> COMPLETED.

    Returns the COMPLETED booking. Used to accumulate machine pitch_count.
    """
    overrides = {}
    if machine_id is not None:
        overrides["machine_id"] = machine_id
    booking = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", pay_mode, start_utc, end_utc, **overrides
    )
    confirm_booking(booking["id"], member["id"], lane["id"])
    # PRD 3.6: check-in is permitted only while the clock is within
    # [start_utc - 30min, end_utc), and completion only when the clock is at or
    # after start_utc. Advance the logical clock to the booking's start_utc so both
    # the check-in window and the completion guard are satisfied.
    set_clock(start_utc)
    get_success_data(api_client.check_in_booking(booking["id"], FRONT_DESK))
    return get_success_data(api_client.complete_booking(booking["id"], FRONT_DESK))


def run_n_completed_sessions(facility, lane, member, machine_id, n, base_hour=9):
    """Run n back-to-back 10-minute COMPLETED sessions on the lane using the machine.

    Sessions are non-overlapping, starting at base_hour:00 on 2026-04-01.
    Each COMPLETED session adds PITCHES_PER_SESSION (1000) to the machine's pitch_count.
    Returns the last COMPLETED booking.
    """
    last = None
    minute = base_hour * 60
    for _ in range(n):
        sh, sm = divmod(minute, 60)
        eh, em = divmod(minute + 10, 60)
        start_utc = f"2026-04-01T{sh:02d}:{sm:02d}:00Z"
        end_utc = f"2026-04-01T{eh:02d}:{em:02d}:00Z"
        last = run_completed_session(
            facility, lane, member, start_utc, end_utc, machine_id=machine_id
        )
        minute += 10
    return last


def drive_machine_to_degraded(facility, lane, member, machine_id):
    """Run exactly 5 COMPLETED 10-min sessions so machine pitch_count reaches 5000
    (DEGRADED). Member must already have a signed waiver and >= ~5 tokens of wallet.
    Returns the machine after the fifth completion."""
    run_n_completed_sessions(facility, lane, member, machine_id, 5)
    return get_success_data(api_client.get_machine(machine_id, MANAGER))


# ─── Program / enrollment scenarios ────────────────────────────────────────────

def create_program(facility, lane_id, kind="LEAGUE", capacity=1, price_cents=5000,
                   session_start_utc="2026-04-10T18:00:00Z",
                   session_end_utc="2026-04-10T20:00:00Z"):
    """Create a program under a facility. Returns the OPEN program."""
    payload = create_program_payload(
        facility["id"], lane_id, kind, capacity, price_cents,
        session_start_utc, session_end_utc,
    )
    return get_success_data(api_client.create_program(payload, MANAGER))


def enroll_member(program_id, member_id, expected_program_version):
    """Enroll a member into a program (as that member). Returns the ENROLLED enrollment."""
    payload = create_enrollment_payload(member_id, expected_program_version)
    return get_success_data(
        api_client.create_enrollment(program_id, payload, make_member_headers(member_id))
    )


def setup_full_single_seat_program(kind="LEAGUE", price_cents=5000):
    """Facility + lane + member + single-seat program with that member enrolled (FULL).

    Returns (facility, lane, member, program, enrollment). The program is FULL because
    its only seat is taken.
    """
    facility = create_facility()
    lane = create_lane(facility["id"], kind="LANE", label="Lane A")
    member = create_member(facility["id"], tier="NONE")
    program = create_program(
        facility, lane["id"], kind=kind, capacity=1, price_cents=price_cents
    )
    enrollment = enroll_member(program["id"], member["id"], program["version"])
    program = get_success_data(api_client.get_program(program["id"], MANAGER))
    return facility, lane, member, program, enrollment


# ─── Maintenance scenarios ─────────────────────────────────────────────────────

def open_maintenance(facility, lane_id, start_utc, end_utc, severity):
    """Open a maintenance window on a lane. Returns the OPEN window."""
    payload = create_maintenance_payload(
        facility["id"], lane_id, start_utc, end_utc, severity
    )
    return get_success_data(api_client.create_maintenance(payload, MANAGER))
