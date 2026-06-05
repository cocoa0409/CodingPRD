"""Composite setup helpers.

Each interesting test claim requires the system to be in a specific state that
takes several API calls to reach (provision a berth + vessel, schedule and
berth a window, declare and ground a container, clear customs, book and check
in a gate appointment, ...). These helpers encapsulate those multi-step
preambles so test files focus on the trigger + assertion.

The harness restarts the server before every test, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. All setup calls
go through get_success_data() (lenient 2xx validator) so a broken precondition
surfaces as a clear "Setup step failed" error.

Per PRD §2.1 every role's X-User-ID is opaque; ownership is never checked, so
fixtures use the shared TEST_USERS header constants throughout.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F

ADMIN = TEST_USERS["terminal_admin_headers"]
BERTH = TEST_USERS["berth_planner_headers"]
YARD = TEST_USERS["yard_planner_headers"]
GATE = TEST_USERS["gate_operator_headers"]
CUSTOMS = TEST_USERS["customs_officer_headers"]
REEFER = TEST_USERS["reefer_technician_headers"]


# --------------------------------------------------------------------------- #
# Clock control
# --------------------------------------------------------------------------- #
def set_clock(iso: str):
    """Set the test-controllable logical clock to the given instant."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# --------------------------------------------------------------------------- #
# Tier 1 / 2: provisioning + window state progression
# --------------------------------------------------------------------------- #
def provision_berth(**overrides) -> dict:
    return get_success_data(api_client.create_berth(F.create_berth_payload(**overrides), ADMIN))


def provision_vessel(**overrides) -> dict:
    return get_success_data(api_client.create_vessel(F.create_vessel_payload(**overrides), ADMIN))


def create_scheduled_window(berth_id, vessel_id, **overrides) -> dict:
    """Schedule a berth window (SCHEDULED). Returns the window entity."""
    payload = F.create_berth_window_payload(berth_id, vessel_id, **overrides)
    return get_success_data(api_client.create_berth_window(payload, BERTH))


def berth_window(window) -> dict:
    """Berth a SCHEDULED window using its current version. Returns the berthed window."""
    return get_success_data(
        api_client.berth_window(
            window["id"], {"expected_berth_window_version": window["version"]}, BERTH
        )
    )


def provision_berthed_window(
    berth_overrides=None, vessel_overrides=None, window_overrides=None
):
    """Berth + vessel + a BERTHED window. Returns (berth, vessel, berthed_window)."""
    berth = provision_berth(**(berth_overrides or {}))
    vessel = provision_vessel(**(vessel_overrides or {}))
    window = create_scheduled_window(berth["id"], vessel["id"], **(window_overrides or {}))
    berthed = berth_window(window)
    return berth, vessel, berthed


# --------------------------------------------------------------------------- #
# Tier 2 / 3: containers, grounding, customs
# --------------------------------------------------------------------------- #
def declare_container(vessel_id, berth_window_id, **overrides) -> dict:
    payload = F.create_container_payload(vessel_id, berth_window_id, **overrides)
    return get_success_data(api_client.create_container(payload, YARD))


def create_yard_slot(**overrides) -> dict:
    return get_success_data(api_client.create_yard_slot(F.create_yard_slot_payload(**overrides), YARD))


def ground_container(container_id, yard_slot_id, condition="SOUND") -> dict:
    return get_success_data(
        api_client.ground_container(
            container_id, F.ground_payload(yard_slot_id, condition=condition), YARD
        )
    )


def customs_clear(container_id) -> dict:
    """Direct-clear a PENDING container, reading its current version first."""
    cont = get_success_data(api_client.get_container(container_id, YARD))
    return get_success_data(
        api_client.customs_clear_container(
            container_id, {"expected_container_version": cont["version"]}, CUSTOMS
        )
    )


def setup_grounded_container(
    free_time_days=60, container_overrides=None, slot_overrides=None
):
    """A berthed window with one container grounded into a ground-tier slot.

    free_time_days defaults high so demurrage stays 0 unless a test opts in.
    Returns (vessel, berthed_window, container, slot).
    """
    _, vessel, window = provision_berthed_window(
        vessel_overrides={"free_time_days": free_time_days}
    )
    container = declare_container(vessel["id"], window["id"], **(container_overrides or {}))
    slot = create_yard_slot(**(slot_overrides or {}))
    ground_container(container["id"], slot["id"])
    return vessel, window, container, slot


def setup_grounded_cleared_container(free_time_days=60, container_overrides=None):
    """A berthed window with one container grounded AND customs-cleared.

    handling_status == GROUNDED, customs_status == CLEARED. Returns
    (vessel, berthed_window, container, slot).
    """
    vessel, window, container, slot = setup_grounded_container(
        free_time_days=free_time_days, container_overrides=container_overrides
    )
    customs_clear(container["id"])
    return vessel, window, container, slot


# --------------------------------------------------------------------------- #
# Tier 3: gate appointments
# --------------------------------------------------------------------------- #
def book_appointment(container_id, **overrides) -> dict:
    payload = F.create_gate_appointment_payload(container_id, **overrides)
    return get_success_data(api_client.create_gate_appointment(payload, GATE))


def setup_arrived_appointment(
    free_time_days=60,
    clock_at_booking="2026-02-02T10:30:00.000Z",
    window_start="2026-02-02T10:00:00.000Z",
    window_end="2026-02-02T11:00:00.000Z",
):
    """A grounded, cleared container with an ARRIVED appointment (checked in).

    The clock is positioned inside the appointment slot before check-in.
    Returns (container, slot, appointment).
    """
    _, _, container, slot = setup_grounded_cleared_container(free_time_days=free_time_days)
    appt = book_appointment(
        container["id"], window_start=window_start, window_end=window_end
    )
    set_clock(clock_at_booking)
    get_success_data(api_client.check_in_gate_appointment(appt["id"], GATE))
    appt = get_success_data(api_client.get_gate_appointment(appt["id"], GATE))
    return container, slot, appt


# --------------------------------------------------------------------------- #
# Tier 4: threshold targeting for demurrage
# --------------------------------------------------------------------------- #
def setup_container_for_demurrage(
    berth_at="2026-02-01T00:00:00.000Z",
    free_time_days=5,
    as_of_clock=None,
    cleared=True,
):
    """Provision a container under a window berthed at `berth_at`, optionally
    cleared, then advance the clock to `as_of_clock`. Used for boundary and
    tiered demurrage tests.

    The window's actual_berth_at is `berth_at`, so
    free_time_expires_at == berth_at + free_time_days days.
    Returns (vessel, berthed_window, container, slot).
    """
    set_clock(berth_at)
    _, vessel, window = provision_berthed_window(
        vessel_overrides={"free_time_days": free_time_days},
        window_overrides={"etd": "2026-03-25T00:00:00.000Z"},
    )
    container = declare_container(vessel["id"], window["id"])
    slot = create_yard_slot()
    ground_container(container["id"], slot["id"])
    if cleared:
        customs_clear(container["id"])
    if as_of_clock is not None:
        set_clock(as_of_clock)
    return vessel, window, container, slot


def gate_out_container(
    container_id, window_start, window_end, check_in_clock, condition="SOUND"
):
    """Book -> check-in -> fulfill a cleared, grounded container. Drives it to
    GATED_OUT and mints a DemurrageInvoice. Returns the fulfilled appointment.

    The caller is responsible for having set the clock so that the demurrage
    computation lands as desired; check_in_clock must be inside the slot.
    """
    appt = book_appointment(container_id, window_start=window_start, window_end=window_end)
    set_clock(check_in_clock)
    get_success_data(api_client.check_in_gate_appointment(appt["id"], GATE))
    return get_success_data(
        api_client.fulfill_gate_appointment(appt["id"], {"condition": condition}, GATE)
    )


def get_only_invoice(container_id) -> dict:
    """Return the single DemurrageInvoice for a gated-out container."""
    data, _meta = _list(api_client.list_container_demurrage_invoices(container_id, ADMIN))
    assert len(data) >= 1, f"expected a demurrage invoice for container {container_id}"
    return data[0]


# --------------------------------------------------------------------------- #
# Tier 4: reefer containers + readings
# --------------------------------------------------------------------------- #
def setup_reefer_container(setpoint_c=-18.0):
    """A reefer container declared under a berthed window. Returns (container)."""
    _, vessel, window = provision_berthed_window()
    container = declare_container(
        vessel["id"], window["id"], is_reefer=True, setpoint_c=setpoint_c
    )
    return container


def record_reading(container_id, recorded_at, temperature_c) -> dict:
    return get_success_data(
        api_client.record_reefer_reading(
            container_id, F.reefer_reading_payload(recorded_at, temperature_c), REEFER
        )
    )


# --------------------------------------------------------------------------- #
# Tier 5: customs holds
# --------------------------------------------------------------------------- #
def place_hold(container_id, reason="INSPECTION") -> dict:
    return get_success_data(
        api_client.create_customs_hold(
            F.create_customs_hold_payload(container_id, reason=reason), CUSTOMS
        )
    )


def setup_held_container(free_time_days=60):
    """A grounded container with an ACTIVE customs hold (customs_status=HELD).
    Returns (container, slot, hold)."""
    _, _, container, slot = setup_grounded_container(free_time_days=free_time_days)
    hold = place_hold(container["id"])
    return container, slot, hold


# --------------------------------------------------------------------------- #
# Internal
# --------------------------------------------------------------------------- #
def _list(response):
    """Return (data, meta) from a list response without strict envelope checks."""
    body = response.json()
    if not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup list step failed with HTTP {response.status_code}: {response.text}"
        )
    return body.get("data", []), body.get("meta", {})
