"""Composite setup helpers.

Multi-step preconditions (venue -> day -> block -> booking -> approval ->
payment, sessions, suspensions, stoppages) are built here so tests can focus
on assertions. All setup calls use the lenient get_success_data validator so
a broken precondition surfaces as a clear "Setup step failed" error.

Version-guarded writes (booking approve, day resume, garage assignment) always
re-read the parent's current version immediately before the guarded call, so
fixtures stay correct no matter how many prior mutations advanced it.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_track_payload, create_coach_payload, create_track_day_payload,
    create_rental_block_payload, create_booking_payload, create_driver_payload,
    create_waiver_payload, create_inspection_payload, create_session_payload,
    create_incident_payload, create_noise_reading_payload,
    create_garage_assignment_payload, create_paddock_assignment_payload,
)
from .test_users import TEST_USERS, make_organizer_headers

OPS = TEST_USERS["trackops_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


def _d(resp):
    return get_success_data(resp)


# --- Tier 1: base entities ---------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START_ISO):
    """Position the logical clock (TrackOps-only capability)."""
    return _d(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


def make_track(**overrides):
    return _d(api_client.create_track(create_track_payload(**overrides), OPS))


def make_coach(tid, cert_level="INTERMEDIATE", **overrides):
    return _d(api_client.create_coach(
        tid, create_coach_payload(cert_level=cert_level, **overrides), OPS))


def make_track_day(tid, date="2026-09-01"):
    return _d(api_client.create_track_day(tid, create_track_day_payload(date=date), OPS))


def open_day(tid, tdid):
    return _d(api_client.open_track_day(tid, tdid, OPS))


def make_open_track_day(tid, date="2026-09-01"):
    day = make_track_day(tid, date)
    return _d(api_client.open_track_day(tid, day["id"], OPS))


def make_block(tid, tdid, **overrides):
    return _d(api_client.create_rental_block(
        tid, tdid, create_rental_block_payload(**overrides), OPS))


def setup_open_day_with_block(date="2026-09-01", track_overrides=None,
                              block_overrides=None):
    """Track + opened TrackDay + one RentalBlock. Returns dict of all three."""
    track = make_track(**(track_overrides or {}))
    day = make_open_track_day(track["id"], date)
    block = make_block(track["id"], day["id"], **(block_overrides or {}))
    return {"track": track, "day": day, "block": block}


# --- Tier 2: bookings, approval, payment --------------------------------------

def make_booking(tid, tdid, rbid, organizer_user_id="org-1", **overrides):
    payload = create_booking_payload(organizer_user_id=organizer_user_id, **overrides)
    return _d(api_client.create_booking(
        tid, tdid, rbid, payload, make_organizer_headers(organizer_user_id)))


def block_version(tid, tdid, rbid):
    return _d(api_client.get_rental_block(tid, tdid, rbid, OPS))["version"]


def day_version(tid, tdid):
    return _d(api_client.get_track_day(tid, tdid, OPS))["version"]


def get_block(tid, tdid, rbid):
    return _d(api_client.get_rental_block(tid, tdid, rbid, OPS))


def get_day(tid, tdid):
    return _d(api_client.get_track_day(tid, tdid, OPS))


def get_booking(tid, tdid, rbid, bid):
    return _d(api_client.get_booking(tid, tdid, rbid, bid, OPS))


def approve_booking(tid, tdid, rbid, bid):
    """Approve with the block's current version (OCC field re-read fresh)."""
    version = block_version(tid, tdid, rbid)
    return _d(api_client.approve_booking(
        tid, tdid, rbid, bid, {"expected_rental_block_version": version}, OPS))


def pay_booking(bid, capture=True):
    """AUTHORIZE, then CAPTURE (default) via the payment simulation."""
    _d(api_client.simulate_payment({"booking_id": bid, "outcome": "AUTHORIZE"}, OPS))
    if capture:
        return _d(api_client.simulate_payment(
            {"booking_id": bid, "outcome": "CAPTURE"}, OPS))
    return _d(api_client.get_booking_flat(bid, OPS))


def setup_approved_booking(date="2026-09-01", organizer_user_id="org-1",
                           track_overrides=None, block_overrides=None,
                           booking_overrides=None):
    """Open day + block + one APPROVED booking. Returns dict."""
    env = setup_open_day_with_block(date, track_overrides, block_overrides)
    booking = make_booking(env["track"]["id"], env["day"]["id"], env["block"]["id"],
                           organizer_user_id, **(booking_overrides or {}))
    booking = approve_booking(env["track"]["id"], env["day"]["id"],
                              env["block"]["id"], booking["id"])
    env["booking"] = booking
    return env


def setup_approved_paid_booking(date="2026-09-01", organizer_user_id="org-1",
                                track_overrides=None, block_overrides=None,
                                booking_overrides=None):
    """APPROVED booking with payment CAPTURED. Returns dict."""
    env = setup_approved_booking(date, organizer_user_id, track_overrides,
                                 block_overrides, booking_overrides)
    pay_booking(env["booking"]["id"], capture=True)
    env["booking"] = get_booking(env["track"]["id"], env["day"]["id"],
                                 env["block"]["id"], env["booking"]["id"])
    return env


# --- Tier 3: sessions, incidents, posture -------------------------------------

def make_session(tid, tdid, rbid, run_group_class="ADVANCED"):
    return _d(api_client.create_session(
        tid, tdid, create_session_payload(rental_block_id=rbid,
                                          run_group_class=run_group_class), OPS))


def setup_running_day_with_session(date="2026-09-01", run_group_class="ADVANCED",
                                   track_overrides=None, block_overrides=None):
    """Open day + block + one GREEN session (day flips to RUNNING)."""
    env = setup_open_day_with_block(date, track_overrides, block_overrides)
    env["session"] = make_session(env["track"]["id"], env["day"]["id"],
                                  env["block"]["id"], run_group_class)
    env["day"] = get_day(env["track"]["id"], env["day"]["id"])
    return env


def report_incident(tid, tdid, sid, severity="LOW", reported_by="ops-1",
                    headers=None):
    return _d(api_client.report_incident(
        tid, tdid, create_incident_payload(session_id=sid, severity=severity,
                                           reported_by_user_id=reported_by),
        headers or OPS))


def post_noise_reading(tid, tdid, sid, db_level, recorded_at_utc):
    return _d(api_client.create_noise_reading(
        tid, tdid, create_noise_reading_payload(
            session_id=sid, db_level=db_level, recorded_at_utc=recorded_at_utc),
        OPS))


def setup_suspended_day_via_noise(date="2026-09-04", noise_limit_db=90,
                                  breach_dbs=(95, 96, 97),
                                  run_group_class="ADVANCED"):
    """RUNNING day pushed to posture SUSPENDED by three breaching readings
    recorded inside the trailing sixty-minute window."""
    env = setup_running_day_with_session(
        date, run_group_class,
        track_overrides={"noise_limit_db": noise_limit_db})
    set_clock(f"{date}T09:25:00Z")
    tid, tdid, sid = env["track"]["id"], env["day"]["id"], env["session"]["id"]
    for i, db in enumerate(breach_dbs):
        post_noise_reading(tid, tdid, sid, db, f"{date}T09:{i * 5:02d}:00Z")
    env["day"] = get_day(tid, tdid)
    return env


def setup_stopped_day_via_incident(date="2026-09-05", severity="HIGH",
                                   reporter="ops-1"):
    """RUNNING day + GREEN session, then one HIGH/CRITICAL incident stops the
    day and reddens the session. Returns dict including the incident."""
    env = setup_running_day_with_session(date)
    env["incident"] = report_incident(env["track"]["id"], env["day"]["id"],
                                      env["session"]["id"], severity, reporter)
    env["day"] = get_day(env["track"]["id"], env["day"]["id"])
    return env


def investigate_and_clear(tid, tdid, iid, cleared_by="safety-1",
                          investigate=True):
    if investigate:
        _d(api_client.investigate_incident(tid, tdid, iid, SAFETY))
    return _d(api_client.clear_incident(
        tid, tdid, iid, {"cleared_by_user_id": cleared_by}, SAFETY))


def resume_day(tid, tdid):
    """Resume with the day's current version (OCC field re-read fresh)."""
    version = day_version(tid, tdid)
    return _d(api_client.resume_track_day(
        tid, tdid, {"expected_track_day_version": version}, SAFETY))


# --- Tier 4: drivers, waivers, inspections ------------------------------------

def make_driver(tid, tdid, rbid, bid, organizer_user_id="org-1", **overrides):
    return _d(api_client.create_driver(
        tid, tdid, rbid, bid, create_driver_payload(**overrides),
        make_organizer_headers(organizer_user_id)))


def get_driver(tid, tdid, rbid, bid, did):
    return _d(api_client.get_driver(tid, tdid, rbid, bid, did, OPS))


def sign_waiver(tid, tdid, rbid, bid, did, signed_at_utc="2026-08-01T08:00:00Z",
                organizer_user_id="org-1", signature_payload_hash="sig-hash"):
    return _d(api_client.submit_waiver(
        tid, tdid, rbid, bid, did,
        create_waiver_payload(signed_at_utc=signed_at_utc,
                              signature_payload_hash=signature_payload_hash),
        make_organizer_headers(organizer_user_id)))


def inspect_driver(tid, tdid, rbid, bid, did, inspector_user_id="safety-1",
                   helmet_ok=True, harness_ok=True):
    return _d(api_client.inspect_driver(
        tid, tdid, rbid, bid, did,
        create_inspection_payload(inspector_user_id=inspector_user_id,
                                  helmet_ok=helmet_ok, harness_ok=harness_ok),
        SAFETY))


def setup_booking_with_driver(date="2026-09-01", organizer_user_id="org-1",
                              approve=False, pay=False, sign=False,
                              inspect=False):
    """Booking (+optional approval/payment) with one registered driver, with
    optional signed waiver and passed inspection. Returns dict."""
    if approve or pay:
        env = setup_approved_booking(date, organizer_user_id)
    else:
        env = setup_open_day_with_block(date)
        env["booking"] = make_booking(env["track"]["id"], env["day"]["id"],
                                      env["block"]["id"], organizer_user_id)
    tid, tdid, rbid, bid = (env["track"]["id"], env["day"]["id"],
                            env["block"]["id"], env["booking"]["id"])
    env["driver"] = make_driver(tid, tdid, rbid, bid, organizer_user_id)
    if sign:
        env["waiver"] = sign_waiver(tid, tdid, rbid, bid, env["driver"]["id"],
                                    organizer_user_id=organizer_user_id)
    if inspect:
        env["inspection"] = inspect_driver(tid, tdid, rbid, bid,
                                           env["driver"]["id"])
    if pay:
        pay_booking(bid, capture=True)
    env["booking"] = get_booking(tid, tdid, rbid, bid)
    env["driver"] = get_driver(tid, tdid, rbid, bid, env["driver"]["id"])
    return env


# --- Tier 5: facilities --------------------------------------------------------

def make_garage_assignment(tid, tdid, bid, bay_number=1, power_hookups=1,
                           water_hookup=False):
    """Create a garage assignment with the day's current version (OCC)."""
    version = day_version(tid, tdid)
    payload = create_garage_assignment_payload(
        booking_id=bid, bay_number=bay_number, power_hookups=power_hookups,
        water_hookup=water_hookup, expected_track_day_version=version)
    return _d(api_client.create_garage_assignment(tid, tdid, payload, OPS))


def make_paddock_assignment(tid, tdid, bid, stall_number=1):
    payload = create_paddock_assignment_payload(booking_id=bid,
                                                stall_number=stall_number)
    return _d(api_client.create_paddock_assignment(tid, tdid, payload, OPS))


def assign_coach(tid, tdid, rbid, bid, cid):
    return _d(api_client.assign_coach(tid, tdid, rbid, bid, {"coach_id": cid}, OPS))
