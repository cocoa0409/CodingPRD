"""Composite setup helpers.

Every test runs against a fresh, empty database (the harness restarts the server
before each test). These helpers build the multi-step preconditions each test
needs, using only PRD-declared endpoints. They use the lenient get_success_data()
validator internally so setup failures surface as clear "Setup step failed" errors.

Identity threading: the Driver role is entity-backed, so every ownership-gated
call uses make_driver_headers(driver["id"]) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_driver_headers
from . import factories


ADMIN = TEST_USERS["carrier_admin_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]


# --------------------------------------------------------------------------
# Low-level building blocks
# --------------------------------------------------------------------------
def pin_clock(to_iso8601: str):
    """Pin the server's current UTC clock (PRD §3.11)."""
    return get_success_data(api_client.set_current_utc(to_iso8601, ADMIN))


def create_vehicle(**overrides) -> dict:
    return get_success_data(api_client.create_vehicle(factories.create_vehicle_payload(**overrides), ADMIN))


def create_device(vehicle_id, **overrides) -> dict:
    return get_success_data(api_client.create_device(factories.create_device_payload(vehicle_id, **overrides), ADMIN))


def create_driver(**overrides) -> dict:
    return get_success_data(api_client.create_driver(factories.create_driver_payload(**overrides), ADMIN))


def get_driver(driver_id) -> dict:
    return get_success_data(api_client.get_driver(driver_id, ADMIN))


def driver_version(driver_id) -> int:
    return get_driver(driver_id)["version"]


def login(device_id, driver_id) -> dict:
    return get_success_data(api_client.login_device(device_id, make_driver_headers(driver_id)))


# --------------------------------------------------------------------------
# Tier 1: a logged-in driver on an in-service vehicle/device, clock pinned.
# --------------------------------------------------------------------------
def setup_bound_driver(clock="2026-06-01T20:00:00Z", driver_overrides=None,
                       vehicle_status=None):
    """Create vehicle + device + driver, pin clock, log the driver in.

    Returns dict: {driver, device, vehicle, driver_id, device_id, vehicle_id}.
    If vehicle_status is given, the vehicle is patched to that status BEFORE login
    (used by the OUT_OF_SERVICE-blocks-login scenario, which then does not log in).
    """
    driver_overrides = driver_overrides or {}
    vehicle = create_vehicle()
    device = create_device(vehicle["id"])
    driver = create_driver(**driver_overrides)
    if clock is not None:
        pin_clock(clock)
    logged_in_device = login(device["id"], driver["id"])
    return {
        "driver": driver, "device": logged_in_device, "vehicle": vehicle,
        "driver_id": driver["id"], "device_id": device["id"], "vehicle_id": vehicle["id"],
    }


# --------------------------------------------------------------------------
# Tier 2 / Tier 4: append events while auto-threading the driver OCC version.
# --------------------------------------------------------------------------
class EventStream:
    """Appends duty events for one bound driver, re-reading Driver.version before
    each append so the OCC token (expected_driver_version) is always fresh.

    This mirrors the design-index pattern of GET /eld/drivers/{id} between appends.
    """

    def __init__(self, driver_id, device_id):
        self.driver_id = driver_id
        self.device_id = device_id
        self.headers = make_driver_headers(driver_id)
        self.events = []  # appended event dicts in order

    def append(self, duty_status, event_time, **overrides):
        """Append one event, capturing the fresh driver version first. Returns the
        created DutyStatusEvent dict."""
        v = driver_version(self.driver_id)
        payload = factories.create_duty_event_payload(
            self.driver_id, self.device_id, duty_status, event_time, v, **overrides
        )
        evt = get_success_data(api_client.create_duty_event(payload, self.headers))
        self.events.append(evt)
        return evt


def make_stream(setup: dict) -> EventStream:
    return EventStream(setup["driver_id"], setup["device_id"])


# --------------------------------------------------------------------------
# Composite: a driver who has driven a 661-minute DRIVING interval, yielding one
# OPEN DRIVING_11H violation (overage 1). Reused by many depth + corner instances.
# --------------------------------------------------------------------------
def setup_driving_11h_violation(clock="2026-06-01T20:00:00Z", driver_overrides=None):
    """DRIVING 06:30 -> OFF_DUTY 17:31 = 661 driving minutes -> one OPEN DRIVING_11H.

    Returns dict with: setup keys, drive_event, close_event, violation (the OPEN
    DRIVING_11H row), driver_id.
    """
    setup = setup_bound_driver(clock=clock, driver_overrides=driver_overrides)
    stream = make_stream(setup)
    drive_evt = stream.append("DRIVING", "2026-06-01T06:30:00Z")
    close_evt = stream.append("OFF_DUTY", "2026-06-01T17:31:00Z")
    violation = find_one_violation(setup["driver_id"], violation_type="DRIVING_11H", status="OPEN")
    setup.update({
        "stream": stream, "drive_event": drive_evt, "close_event": close_evt,
        "violation": violation,
    })
    return setup


# --------------------------------------------------------------------------
# Read helpers for violations / segments.
# --------------------------------------------------------------------------
def list_violations(driver_id=None, violation_type=None, status=None):
    params = {}
    if driver_id:
        params["driver_id"] = driver_id
    if violation_type:
        params["violation_type"] = violation_type
    if status:
        params["status"] = status
    return get_success_data(api_client.list_violations(OFFICER, params=params))


def find_one_violation(driver_id, violation_type=None, status=None) -> dict:
    rows = list_violations(driver_id=driver_id, violation_type=violation_type, status=status)
    assert len(rows) == 1, (
        f"Setup expected exactly 1 violation (type={violation_type}, status={status}), got {len(rows)}"
    )
    return rows[0]


def get_violation(violation_id) -> dict:
    return get_success_data(api_client.get_violation(violation_id, OFFICER))


def get_event(event_id) -> dict:
    return get_success_data(api_client.get_duty_event(event_id, ADMIN))


def get_daily_log(log_id) -> dict:
    return get_success_data(api_client.get_daily_log(log_id, ADMIN))


# --------------------------------------------------------------------------
# Daily-log helpers.
# --------------------------------------------------------------------------
def open_daily_log(driver_id, log_date) -> dict:
    payload = factories.create_daily_log_payload(driver_id, log_date)
    return get_success_data(api_client.create_daily_log(payload, make_driver_headers(driver_id)))


def certify_daily_log(driver_id, log_id) -> dict:
    return get_success_data(api_client.certify_daily_log(log_id, make_driver_headers(driver_id)))


# --------------------------------------------------------------------------
# Adverse-claim helpers.
# --------------------------------------------------------------------------
def file_adverse_claim(driver_id, log_date, reason="WEATHER", narrative="Adverse conditions.") -> dict:
    payload = factories.create_adverse_claim_payload(driver_id, log_date, reason=reason, narrative=narrative)
    return get_success_data(api_client.create_adverse_claim(payload, make_driver_headers(driver_id)))


def approve_adverse_claim(claim_id, expected_version) -> dict:
    payload = factories.approve_claim_payload(expected_version)
    return get_success_data(api_client.approve_adverse_claim(claim_id, payload, OFFICER))


def reject_adverse_claim(claim_id) -> dict:
    return get_success_data(api_client.reject_adverse_claim(claim_id, OFFICER))


# --------------------------------------------------------------------------
# Violation lifecycle helpers.
# --------------------------------------------------------------------------
def acknowledge_violation(violation_id) -> dict:
    return get_success_data(api_client.acknowledge_violation(violation_id, OFFICER))


def reopen_violation(violation_id) -> dict:
    return get_success_data(api_client.reopen_violation(violation_id, OFFICER))


# --------------------------------------------------------------------------
# Mark-error helper (CarrierAdmin), auto-reading the event's current version.
# --------------------------------------------------------------------------
def mark_error(event_id) -> dict:
    v = get_event(event_id)["version"]
    payload = factories.mark_error_payload(v)
    return get_success_data(api_client.mark_error_duty_event(event_id, payload, ADMIN))
