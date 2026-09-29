"""Composite setup helpers.

The database starts empty for every single test, so each helper below builds the
state it names from scratch through the documented endpoints.  Every helper
unwraps its responses with `get_success_data()` so a broken setup fails at the
line that broke rather than deep inside an assertion, and every helper takes
`**overrides` so a caller can vary one field of an otherwise canonical scenario.

Identity is threaded, never assumed: a homeowner's `X-User-ID` is the acting
`Homeowner.id`, so every helper that acts as a homeowner builds its headers from
the account row it just created.

The canonical household — one homeowner, one irrigation-capable property, one
install-verified device and the three learning samples that arm it — recurs
throughout the suite, so `setup_armed_device()` builds it once and the richer
helpers layer on top of it.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    CANONICAL_BURST_READING,
    CANONICAL_DRIP_READING,
    CANONICAL_LEARNING_READINGS,
    DEFAULT_CLOCK_UTC,
    FIXTURE_CLOCK_UTC,
    TEST_DEFAULTS,
)
from .factories import (
    attestation_payload,
    buyer_payload,
    claim_decision_payload,
    claim_payload,
    clock_payload,
    device_payload,
    device_transfer_payload,
    emergency_contact_payload,
    feedback_payload,
    firmware_update_payload,
    homeowner_payload,
    irrigation_window_payload,
    monitor_mode_payload,
    policy_payload,
    property_payload,
    resolve_payload,
    second_property_payload,
    telemetry_payload,
    valve_command_payload,
    verify_install_payload,
)
from .test_users import (
    ADJUSTER_USER_ID,
    INSTALLER_TECH_USER_ID,
    INSURER_ANALYST_USER_ID,
    TEST_USERS,
    make_claims_adjuster_headers,
    make_homeowner_headers,
    make_installer_tech_headers,
    make_insurer_analyst_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
GATEWAY = TEST_USERS["gateway_headers"]
ANALYST = TEST_USERS["insurer_analyst_headers"]


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601: str) -> dict:
    """Move the logical clock; the program administrator holds this capability."""
    return get_success_data(api.set_current_utc(clock_payload(to_iso8601), ADMIN))


def read_clock_after(api, to_iso8601: str) -> str:
    """Move the clock and hand back the instant the server now reports."""
    return set_clock(api, to_iso8601)["current_utc"]


# --------------------------------------------------------------------------
# Tier 1 — single rows
# --------------------------------------------------------------------------
def create_homeowner(api, **overrides) -> dict:
    """Register an account; only the program administrator may do so."""
    return get_success_data(
        api.create_homeowner(homeowner_payload(**overrides), ADMIN), 201
    )


def create_buyer(api, **overrides) -> dict:
    """A second account, used as the buyer at closing."""
    return get_success_data(api.create_homeowner(buyer_payload(**overrides), ADMIN), 201)


def create_emergency_contact(api, homeowner_id: str, priority_rank: int = 1, **overrides):
    return get_success_data(
        api.create_emergency_contact(
            homeowner_id,
            emergency_contact_payload(priority_rank, **overrides),
            make_homeowner_headers(homeowner_id),
        ),
        201,
    )


def create_property(api, homeowner_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_property(
            property_payload(homeowner_id, **overrides),
            make_homeowner_headers(homeowner_id),
        ),
        201,
    )


def create_second_property(api, homeowner_id: str, **overrides) -> dict:
    """A property without irrigation, at a second address."""
    return get_success_data(
        api.create_property(
            second_property_payload(homeowner_id, **overrides),
            make_homeowner_headers(homeowner_id),
        ),
        201,
    )


def create_irrigation_window(
    api,
    property_id: str,
    homeowner_id: str,
    start_at: str,
    end_at: str,
    expected_max_flow_gpm: float = 4.0,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_irrigation_window(
            property_id,
            irrigation_window_payload(
                start_at, end_at, expected_max_flow_gpm, **overrides
            ),
            make_homeowner_headers(homeowner_id),
        ),
        201,
    )


def create_device(api, property_id: str, user_id: str = INSTALLER_TECH_USER_ID, **overrides):
    return get_success_data(
        api.create_device(
            device_payload(property_id, **overrides),
            make_installer_tech_headers(user_id),
        ),
        201,
    )


def verify_install(api, device_id: str, user_id: str = INSTALLER_TECH_USER_ID, **overrides):
    """Record the static-pressure hold test; only the installer may."""
    return get_success_data(
        api.verify_install(
            device_id,
            verify_install_payload(**overrides),
            make_installer_tech_headers(user_id),
        )
    )


def ingest_reading(
    api,
    device_id: str,
    reading_at: str,
    static_pressure_psi: float,
    flow_gpm: float,
    duration_minutes: float,
    total_gallons: float,
    **overrides,
) -> dict:
    """Ingest one sample; only the gateway may write telemetry."""
    return get_success_data(
        api.create_telemetry_reading(
            device_id,
            telemetry_payload(
                reading_at,
                static_pressure_psi,
                flow_gpm,
                duration_minutes,
                total_gallons,
                **overrides,
            ),
            GATEWAY,
        ),
        201,
    )


def ingest_quiet_reading(api, device_id: str, reading_at: str, **overrides) -> dict:
    """A sample with no flow at all, used to accrue uptime coverage."""
    return ingest_reading(api, device_id, reading_at, 60.0, 0.0, 0, 0.0, **overrides)


def ingest_burst_reading(api, device_id: str, reading_at: str, **overrides) -> dict:
    """The canonical burst: 12.0 gpm for 6 minutes moving 72 gallons."""
    reading = dict(CANONICAL_BURST_READING)
    reading.update(overrides)
    return ingest_reading(api, device_id, reading_at, **reading)


def ingest_drip_reading(api, device_id: str, reading_at: str, **overrides) -> dict:
    """A drip: 0.20 gpm held for a full hour, above the 0.12 gpm threshold."""
    reading = dict(CANONICAL_DRIP_READING)
    reading.update(overrides)
    return ingest_reading(api, device_id, reading_at, **reading)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------
def read_device(api, device_id: str, headers=None) -> dict:
    return get_success_data(api.get_device(device_id, headers or ADMIN))


def read_property(api, property_id: str, headers=None) -> dict:
    return get_success_data(api.get_property(property_id, headers or ADMIN))


def read_homeowner(api, homeowner_id: str, headers=None) -> dict:
    return get_success_data(api.get_homeowner(homeowner_id, headers or ADMIN))


def read_policy(api, policy_id: str, headers=None) -> dict:
    return get_success_data(api.get_policy(policy_id, headers or ANALYST))


def read_attestation_list(api, policy_id: str, headers=None, params=None) -> list:
    return get_success_data(
        api.list_credit_attestations(policy_id, headers or ANALYST, params)
    )


def read_claim(api, claim_id: str, headers=None) -> dict:
    return get_success_data(api.get_claim(claim_id, headers or ADMIN))


def read_transfer(api, transfer_id: str, headers=None) -> dict:
    return get_success_data(api.get_device_transfer(transfer_id, headers or ADMIN))


def read_live_baseline(api, device_id: str, headers=None) -> dict:
    """The live profile is the last row of the cycle-ordered list."""
    rows = get_success_data(api.list_baseline_profiles(device_id, headers or ADMIN))
    assert rows, "the device has no baseline profile row yet"
    return rows[-1]


def read_baseline_profiles(api, device_id: str, headers=None, params=None) -> list:
    return get_success_data(api.list_baseline_profiles(device_id, headers or ADMIN, params))


def read_telemetry(api, device_id: str, headers=None, params=None) -> list:
    return get_success_data(api.list_telemetry_readings(device_id, headers or ADMIN, params))


def read_device_version(api, device_id: str, headers=None) -> int:
    """The version an optimistic-concurrency command must carry."""
    return read_device(api, device_id, headers)["version"]


def read_property_version(api, property_id: str, headers=None) -> int:
    return read_property(api, property_id, headers or ANALYST)["version"]


def read_events(api, device_id: str = None, headers=None, **params) -> list:
    query = dict(params)
    if device_id is not None:
        query["device_id"] = device_id
    return get_success_data(api.list_anomaly_events(headers or ADMIN, query or None))


def read_tickets(api, headers=None, **params) -> list:
    return get_success_data(
        api.list_escalation_tickets(headers or ADMIN, dict(params) or None)
    )


def read_irrigation_windows(api, property_id: str, headers=None, params=None) -> list:
    return get_success_data(
        api.list_irrigation_windows(property_id, headers or ADMIN, params)
    )


def read_health_summary(api, device_id: str, headers=None, params=None) -> dict:
    return get_success_data(api.get_health_summary(device_id, headers or ADMIN, params))


# --------------------------------------------------------------------------
# Tier 2 — the canonical household
# --------------------------------------------------------------------------
def setup_household(api, clock: str = FIXTURE_CLOCK_UTC, homeowner=None, property=None) -> dict:
    """One account and one irrigation-capable property, clock pinned."""
    set_clock(api, clock)
    owner = create_homeowner(api, **(homeowner or {}))
    home = create_property(api, owner["id"], **(property or {}))
    return {
        "homeowner": owner,
        "homeowner_id": owner["id"],
        "homeowner_headers": make_homeowner_headers(owner["id"]),
        "property": home,
        "property_id": home["id"],
    }


def setup_learning_device(
    api,
    clock: str = FIXTURE_CLOCK_UTC,
    homeowner=None,
    property=None,
    device=None,
    install=None,
    installer_user_id: str = INSTALLER_TECH_USER_ID,
    install_clock: str = DEFAULT_CLOCK_UTC,
) -> dict:
    """The household plus one install-verified device.

    A passing hold test moves the device straight to LEARNING and opens learning
    cycle 1, so the device is watching but not yet armed.

    The hold test is signed off at `install_clock`, which pins the profile's
    `learning_started_at` — `sample_count` only counts readings stamped at or
    after that instant, and the canonical learning samples are stamped from
    `2026-08-01T00:00:00Z` onwards.  The clock is returned to `clock` before the
    helper hands back, so every later step still runs at the fixture instant.
    """
    state = setup_household(api, clock, homeowner, property)
    dev = create_device(api, state["property_id"], installer_user_id, **(device or {}))
    set_clock(api, install_clock)
    dev = verify_install(api, dev["id"], installer_user_id, **(install or {}))
    set_clock(api, clock)
    state["device"] = dev
    state["device_id"] = dev["id"]
    state["installer_user_id"] = installer_user_id
    return state


def setup_registered_device(
    api,
    clock: str = FIXTURE_CLOCK_UTC,
    homeowner=None,
    property=None,
    device=None,
    installer_user_id: str = INSTALLER_TECH_USER_ID,
) -> dict:
    """The household plus one device that has not had its hold test yet."""
    state = setup_household(api, clock, homeowner, property)
    dev = create_device(api, state["property_id"], installer_user_id, **(device or {}))
    state["device"] = dev
    state["device_id"] = dev["id"]
    state["installer_user_id"] = installer_user_id
    return state


def ingest_learning_samples(api, device_id: str, readings=None) -> list:
    """Feed the samples that a learning cycle needs.

    The canonical three are a quiet sample, a 6.00 gpm peak and another quiet
    sample, which settle the baseline at 60.0 psi static / 6.00 gpm peak and put
    the drip threshold at 0.12 gpm.
    """
    samples = readings if readings is not None else CANONICAL_LEARNING_READINGS
    return [ingest_reading(api, device_id, **sample) for sample in samples]


def setup_armed_device(
    api,
    clock: str = FIXTURE_CLOCK_UTC,
    homeowner=None,
    property=None,
    device=None,
    install=None,
    readings=None,
    installer_user_id: str = INSTALLER_TECH_USER_ID,
) -> dict:
    """The canonical armed device.

    Three baseline-eligible samples close learning cycle 1, which completes the
    profile and promotes the device from LEARNING to ARMED with the valve OPEN
    and monitor mode NORMAL.
    """
    state = setup_learning_device(
        api, clock, homeowner, property, device, install, installer_user_id
    )
    state["learning_readings"] = ingest_learning_samples(api, state["device_id"], readings)
    state["baseline"] = read_live_baseline(api, state["device_id"])
    state["device"] = read_device(api, state["device_id"])
    return state


def setup_armed_device_with_contact(
    api, clock: str = FIXTURE_CLOCK_UTC, verify_immediately: bool = True, **kwargs
) -> dict:
    """The canonical armed device plus one rank-1 emergency contact.

    Only a VERIFIED contact is selectable when the ladder hops, so the default
    here creates the contact already verified.
    """
    state = setup_armed_device(api, clock, **kwargs)
    state["contact"] = create_emergency_contact(
        api,
        state["homeowner_id"],
        1,
        verify_immediately=verify_immediately,
    )
    return state


def setup_armed_device_with_buyer(api, clock: str = FIXTURE_CLOCK_UTC, **kwargs) -> dict:
    """The canonical armed device plus a second account to sell it to."""
    state = setup_armed_device(api, clock, **kwargs)
    buyer = create_buyer(api)
    state["buyer"] = buyer
    state["buyer_id"] = buyer["id"]
    state["buyer_headers"] = make_homeowner_headers(buyer["id"])
    return state


# --------------------------------------------------------------------------
# Tier 3 — the insurer policy
# --------------------------------------------------------------------------
def create_policy(
    api,
    property_id: str,
    policy_year_start_at: str,
    expected_property_version: int = None,
    user_id: str = INSURER_ANALYST_USER_ID,
    **overrides,
) -> dict:
    """Write a policy against a property; only an insurer analyst may.

    The create carries the property version the analyst read, so the helper reads
    it first unless the caller pins a version deliberately.
    """
    headers = make_insurer_analyst_headers(user_id)
    version = (
        expected_property_version
        if expected_property_version is not None
        else read_property_version(api, property_id, headers)
    )
    return get_success_data(
        api.create_policy(
            policy_payload(property_id, version, policy_year_start_at, **overrides),
            headers,
        ),
        201,
    )


def setup_armed_device_with_policy(
    api,
    policy_year_start_at: str,
    clock: str = FIXTURE_CLOCK_UTC,
    policy=None,
    **kwargs,
) -> dict:
    """The canonical armed device with a policy covering its property."""
    state = setup_armed_device(api, clock, **kwargs)
    pol = create_policy(
        api, state["property_id"], policy_year_start_at, **(policy or {})
    )
    state["policy"] = pol
    state["policy_id"] = pol["id"]
    return state


def open_attestation(
    api,
    policy_id: str,
    period_start_at: str,
    period_end_at: str,
    user_id: str = INSURER_ANALYST_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_credit_attestation(
            policy_id,
            attestation_payload(period_start_at, period_end_at, **overrides),
            make_insurer_analyst_headers(user_id),
        ),
        201,
    )


def finalize_attestation(
    api, attestation_id: str, user_id: str = INSURER_ANALYST_USER_ID
) -> dict:
    return get_success_data(
        api.finalize_credit_attestation(
            attestation_id, {}, make_insurer_analyst_headers(user_id)
        )
    )


# --------------------------------------------------------------------------
# Device operations
# --------------------------------------------------------------------------
def set_monitor_mode(api, device_id: str, homeowner_id: str, mode: str, **overrides) -> dict:
    return get_success_data(
        api.set_monitor_mode(
            device_id,
            monitor_mode_payload(mode, **overrides),
            make_homeowner_headers(homeowner_id),
        )
    )


def snooze_device(api, device_id: str, homeowner_id: str, snooze_minutes: int = 60) -> dict:
    """Suppress alerting for a bounded stretch, after which a cooldown runs."""
    return set_monitor_mode(
        api, device_id, homeowner_id, "SNOOZE", snooze_minutes=snooze_minutes
    )


def send_valve_command(
    api,
    device_id: str,
    homeowner_id: str,
    command: str,
    expected_device_version: int = None,
    **overrides,
) -> dict:
    """Override the valve, reading the current version unless one is pinned."""
    headers = make_homeowner_headers(homeowner_id)
    version = (
        expected_device_version
        if expected_device_version is not None
        else read_device_version(api, device_id, headers)
    )
    return get_success_data(
        api.send_valve_command(
            device_id, valve_command_payload(command, version, **overrides), headers
        )
    )


def close_valve(
    api,
    device_id: str,
    homeowner_id: str,
    expected_device_version: int = None,
    override_reason: str = "leaving for the weekend",
) -> dict:
    return send_valve_command(
        api,
        device_id,
        homeowner_id,
        "CLOSE",
        expected_device_version,
        override_reason=override_reason,
    )


def reopen_valve(
    api,
    device_id: str,
    homeowner_id: str,
    expected_device_version: int = None,
    override_reason: str = "Repair complete, restoring water",
) -> dict:
    """Reopen after a shutoff, which the PRD requires be acknowledged in writing."""
    return send_valve_command(
        api,
        device_id,
        homeowner_id,
        "OPEN",
        expected_device_version,
        override_reason=override_reason,
        acknowledge_water_damage_risk=True,
    )


def push_firmware(
    api, device_id: str, target_firmware_version: str = "3.2.1", user_id: str = None
) -> dict:
    return get_success_data(
        api.push_firmware_update(
            device_id,
            firmware_update_payload(target_firmware_version),
            make_installer_tech_headers(user_id or INSTALLER_TECH_USER_ID),
        )
    )


def run_ops_sweep(api) -> dict:
    """One operator sweep: mode reverts, then SLA hops, then transfer expiries."""
    return get_success_data(api.run_ops_sweep({}, ADMIN))


def deactivate_homeowner(api, homeowner_id: str) -> dict:
    return get_success_data(api.deactivate_homeowner(homeowner_id, {}, ADMIN))


# --------------------------------------------------------------------------
# Alert handling
# --------------------------------------------------------------------------
def resolve_event(
    api, event_id: str, homeowner_id: str, resolution_note: str = "Burst hose bib replaced"
) -> dict:
    return get_success_data(
        api.resolve_anomaly_event(
            event_id,
            resolve_payload(resolution_note),
            make_homeowner_headers(homeowner_id),
        )
    )


def submit_feedback(api, event_id: str, homeowner_id: str, label: str) -> dict:
    return get_success_data(
        api.submit_event_feedback(
            event_id, feedback_payload(label), make_homeowner_headers(homeowner_id)
        )
    )


def acknowledge_ticket(api, ticket_id: str, headers=None) -> dict:
    return get_success_data(
        api.acknowledge_escalation_ticket(ticket_id, {}, headers or ADMIN)
    )


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def file_claim(
    api,
    policy_id: str,
    device_id: str,
    claim_type: str,
    documented_loss_cents: int,
    homeowner_id: str,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_claim(
            claim_payload(
                policy_id, device_id, claim_type, documented_loss_cents, **overrides
            ),
            make_homeowner_headers(homeowner_id),
        ),
        201,
    )


def decide_claim(api, claim_id: str, decision: str, headers) -> dict:
    return get_success_data(
        api.decide_claim(claim_id, claim_decision_payload(decision), headers)
    )


def begin_claim_review(api, claim_id: str, user_id: str = ADJUSTER_USER_ID) -> dict:
    return decide_claim(api, claim_id, "BEGIN_REVIEW", make_claims_adjuster_headers(user_id))


def approve_claim(api, claim_id: str, user_id: str = ADJUSTER_USER_ID) -> dict:
    """Approve, which selects the payout algebra and records the deciding operator."""
    return decide_claim(api, claim_id, "APPROVE", make_claims_adjuster_headers(user_id))


def pay_claim(api, claim_id: str, user_id: str = INSURER_ANALYST_USER_ID) -> dict:
    """Disburse, which must be a different operator from the one who approved."""
    return decide_claim(api, claim_id, "PAY", make_insurer_analyst_headers(user_id))


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
def initiate_transfer(
    api,
    device_id: str,
    to_homeowner_id: str,
    seller_id: str,
    expected_device_version: int = None,
    **overrides,
) -> dict:
    headers = make_homeowner_headers(seller_id)
    version = (
        expected_device_version
        if expected_device_version is not None
        else read_device_version(api, device_id, headers)
    )
    return get_success_data(
        api.create_device_transfer(
            device_transfer_payload(device_id, to_homeowner_id, version, **overrides),
            headers,
        ),
        201,
    )


def accept_transfer(api, transfer_id: str, buyer_id: str) -> dict:
    """Only the buyer may accept, and acceptance rewrites ownership."""
    return get_success_data(
        api.accept_device_transfer(transfer_id, {}, make_homeowner_headers(buyer_id))
    )


# --------------------------------------------------------------------------
# Tier 4 — scenarios that a whole family of tests starts from
# --------------------------------------------------------------------------
def setup_burst_event(
    api,
    burst_at: str = "2026-08-01T07:00:00Z",
    clock: str = FIXTURE_CLOCK_UTC,
    **kwargs,
) -> dict:
    """The canonical armed device with one unresolved catastrophic burst.

    The ingest fans out in a single request: the reading freezes its verdict, an
    anomaly event is minted in ALERTED, the ladder opens a ticket pending the
    homeowner, and the auto-shutoff closes the valve.
    """
    state = setup_armed_device(api, clock, **kwargs)
    set_clock(api, burst_at)
    state["burst_reading"] = ingest_burst_reading(api, state["device_id"], burst_at)
    events = read_events(api, state["device_id"])
    assert len(events) == 1, f"expected exactly one anomaly event, got {len(events)}"
    state["event"] = events[0]
    state["event_id"] = events[0]["id"]
    tickets = read_tickets(api, anomaly_event_id=events[0]["id"])
    state["ticket"] = tickets[0] if tickets else None
    state["ticket_id"] = tickets[0]["id"] if tickets else None
    state["device"] = read_device(api, state["device_id"])
    return state


def setup_burst_event_with_policy(
    api,
    policy_year_start_at: str = "2026-08-01T00:00:00Z",
    burst_at: str = "2026-08-01T07:00:00Z",
    clock: str = FIXTURE_CLOCK_UTC,
    policy=None,
    **kwargs,
) -> dict:
    """An unresolved burst on a device whose property carries a policy."""
    state = setup_armed_device_with_policy(
        api, policy_year_start_at, clock, policy, **kwargs
    )
    set_clock(api, burst_at)
    state["burst_reading"] = ingest_burst_reading(api, state["device_id"], burst_at)
    events = read_events(api, state["device_id"])
    assert len(events) == 1, f"expected exactly one anomaly event, got {len(events)}"
    state["event"] = events[0]
    state["event_id"] = events[0]["id"]
    state["device"] = read_device(api, state["device_id"])
    state["policy"] = read_policy(api, state["policy_id"])
    return state


def setup_irrigation_window(
    api,
    start_at: str,
    end_at: str,
    expected_max_flow_gpm: float = 4.0,
    clock: str = FIXTURE_CLOCK_UTC,
    label: str = "front lawn",
    **kwargs,
) -> dict:
    """The canonical armed device with one declared irrigation exclusion window."""
    state = setup_armed_device(api, clock, **kwargs)
    state["irrigation_window"] = create_irrigation_window(
        api,
        state["property_id"],
        state["homeowner_id"],
        start_at,
        end_at,
        expected_max_flow_gpm,
        label=label,
    )
    state["irrigation_window_id"] = state["irrigation_window"]["id"]
    return state


def setup_pending_transfer(
    api, clock: str = FIXTURE_CLOCK_UTC, transfer=None, **kwargs
) -> dict:
    """An armed device frozen behind a transfer the buyer has not accepted."""
    state = setup_armed_device_with_buyer(api, clock, **kwargs)
    state["device_version_before_transfer"] = read_device_version(
        api, state["device_id"], state["homeowner_headers"]
    )
    state["transfer"] = initiate_transfer(
        api,
        state["device_id"],
        state["buyer_id"],
        state["homeowner_id"],
        state["device_version_before_transfer"],
        **(transfer or {}),
    )
    state["transfer_id"] = state["transfer"]["id"]
    return state


def ingest_quiet_readings(api, device_id: str, timestamps) -> list:
    """Accrue uptime coverage with quiet samples at the instants named."""
    return [ingest_quiet_reading(api, device_id, stamp) for stamp in timestamps]


def setup_finalized_credit_period(
    api,
    policy_year_start_at: str = "2026-08-02T00:00:00Z",
    reading_times=(
        "2026-08-02T00:00:00Z",
        "2026-08-02T02:00:00Z",
        "2026-08-02T04:00:00Z",
        "2026-08-02T06:20:00Z",
    ),
    period_start_at: str = "2026-08-02T00:00:00Z",
    period_end_at: str = "2026-08-02T06:40:00Z",
    clock_before_readings: str = "2026-08-02T06:20:00Z",
    clock_before_finalize: str = "2026-08-02T06:40:00Z",
    clock: str = FIXTURE_CLOCK_UTC,
    **kwargs,
) -> dict:
    """One awarded attestation period on the canonical armed device.

    The four samples cover 380 of the period's 400 minutes because the last one
    is clamped at the period end, which puts uptime at exactly the floor.
    """
    state = setup_armed_device_with_policy(api, policy_year_start_at, clock, **kwargs)
    set_clock(api, clock_before_readings)
    state["period_readings"] = ingest_quiet_readings(
        api, state["device_id"], reading_times
    )
    set_clock(api, clock_before_finalize)
    attestation = open_attestation(
        api, state["policy_id"], period_start_at, period_end_at
    )
    state["attestation"] = finalize_attestation(api, attestation["id"])
    state["attestation_id"] = attestation["id"]
    state["policy"] = read_policy(api, state["policy_id"])
    return state


def setup_two_households(api, clock: str = FIXTURE_CLOCK_UTC, **kwargs) -> dict:
    """Two accounts, each with its own property and its own armed device.

    Used wherever a refusal has to follow the resource rather than the endpoint
    shape, and wherever an event on one property must not qualify a claim on the
    other.
    """
    first = setup_armed_device(api, clock, **kwargs)
    second_owner = create_buyer(api)
    second_property = create_second_property(api, second_owner["id"])
    second_device = create_device(
        api,
        second_property["id"],
        serial_number=TEST_DEFAULTS["SECOND_SERIAL_NUMBER"],
        model_code=TEST_DEFAULTS["SECOND_MODEL_CODE"],
    )
    verify_install(
        api,
        second_device["id"],
        installed_static_pressure_psi=61.0,
        pressure_drop_psi=0.5,
    )
    ingest_learning_samples(
        api,
        second_device["id"],
        [
            {
                "reading_at": "2026-08-01T01:00:00Z",
                "static_pressure_psi": 60.0,
                "flow_gpm": 0.0,
                "duration_minutes": 0,
                "total_gallons": 0.0,
            },
            {
                "reading_at": "2026-08-01T01:20:00Z",
                "static_pressure_psi": 62.0,
                "flow_gpm": 6.0,
                "duration_minutes": 4,
                "total_gallons": 24.0,
            },
            {
                "reading_at": "2026-08-01T01:40:00Z",
                "static_pressure_psi": 58.0,
                "flow_gpm": 0.0,
                "duration_minutes": 0,
                "total_gallons": 0.0,
            },
        ],
    )
    first["second_homeowner"] = second_owner
    first["second_homeowner_id"] = second_owner["id"]
    first["second_homeowner_headers"] = make_homeowner_headers(second_owner["id"])
    first["second_property"] = second_property
    first["second_property_id"] = second_property["id"]
    first["second_device"] = read_device(api, second_device["id"])
    first["second_device_id"] = second_device["id"]
    return first


def setup_second_registered_device(api, state: dict, **overrides) -> dict:
    """A second device on the same property that has not had its hold test."""
    payload = {
        "serial_number": TEST_DEFAULTS["SECOND_SERIAL_NUMBER"],
        "model_code": TEST_DEFAULTS["SECOND_MODEL_CODE"],
    }
    payload.update(overrides)
    return create_device(api, state["property_id"], **payload)


def ingest_drip_and_read_event(api, device_id: str, reading_at: str, **overrides) -> dict:
    """Ingest one drip sample and hand back the event it minted."""
    set_clock(api, reading_at)
    ingest_drip_reading(api, device_id, reading_at, **overrides)
    events = read_events(api, device_id)
    assert events, "the drip sample minted no anomaly event"
    return events[-1]


def label_drip_false_positive(
    api, device_id: str, homeowner_id: str, reading_at: str, **overrides
) -> dict:
    """Ingest a drip and label it a false positive, which raises the threshold."""
    event = ingest_drip_and_read_event(api, device_id, reading_at, **overrides)
    return submit_feedback(api, event["id"], homeowner_id, "FALSE_POSITIVE")
