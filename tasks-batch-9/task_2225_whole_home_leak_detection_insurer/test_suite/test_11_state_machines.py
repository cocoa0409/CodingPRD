"""Lifecycle edges: the states a device and its satellites may legally reach.

A device is born on three independent dimensions with no baseline row behind it;
the hold test is the once-only gate that mints one; telemetry, valve commands,
resolution and feedback each name the exact set of states they are legal from; and
the operational sweep is the only actor that turns clock time into a ladder hop.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_baseline_profile,
    assert_device,
    assert_escalation_ticket,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.factories import (
    feedback_payload,
    resolve_payload,
    telemetry_payload,
    valve_command_payload,
    verify_install_payload,
)
from test_helpers.fixtures import (
    acknowledge_ticket,
    create_emergency_contact,
    deactivate_homeowner,
    read_baseline_profiles,
    read_device,
    read_device_version,
    read_events,
    read_homeowner,
    read_live_baseline,
    read_property,
    read_telemetry,
    read_tickets,
    resolve_event,
    run_ops_sweep,
    set_clock,
    setup_armed_device,
    setup_burst_event,
    setup_registered_device,
    setup_second_registered_device,
    verify_install,
)
from test_helpers.test_users import (
    SECOND_INSTALLER_TECH_USER_ID,
    make_gateway_headers,
    make_homeowner_headers,
    make_installer_tech_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()
GATEWAY = make_gateway_headers()
TECH = make_installer_tech_headers()

QUIET_SAMPLE = {
    "static_pressure_psi": 60.0,
    "flow_gpm": 0.0,
    "duration_minutes": 0,
    "total_gallons": 0.0,
}


class TestDeviceInitialState:
    def test_registration_lands_on_three_dimensions_with_no_baseline_row(
        self, api: ApiClient
    ):
        """The profile is minted by the hold test, not by registration.

        "Because a device carries three independent posture dimensions rather than one
        status, a newly registered row lands in `lifecycle_state` `REGISTERED`,
        `valve_state` `OPEN`, and `monitor_mode` `NORMAL` simultaneously, with
        `close_count` and `reopen_count` both at 0 and `monitor_mode_updated_at` equal
        to `created_at`."
        "In the same step exactly one baseline profile row is created for the device,
        with `device_id` pointing back at it, `learning_state` `COLLECTING`,
        `learning_cycle_no` at 1, `learning_started_at` set to the clock, `sample_count`
        at 0, and `baseline_version` at 0."

        Design: Corner/state_machines/device_lifecycle_starts_in_registered_and_baseline_row_absent
        """
        state = setup_registered_device(api)

        device = read_device(api, state["device_id"])
        assert_device(device)
        assert device["lifecycle_state"] == "REGISTERED"
        assert device["valve_state"] == "OPEN"
        assert device["monitor_mode"] == "NORMAL"
        assert device["install_verified_by_user_id"] is None
        assert device["monitor_mode_updated_at"] == device["created_at"]
        assert device["created_at"].startswith("2026-08-01T06:05:00")

        rows, meta = validate_paginated(
            api.list_baseline_profiles(state["device_id"], TECH)
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestInstallVerification:
    def test_a_passing_hold_test_walks_the_device_through_to_learning(
        self, api: ApiClient
    ):
        """Two lifecycle hops happen inside the one request the technician makes.

        "A passing test does several things at once. It records
        `install_verified_by_user_id` as the acting technician's `X-User-ID` and
        `install_verified_at` as the current logical clock, persists the submitted
        `installed_static_pressure_psi` onto the device, and advances `lifecycle_state`
        through `REGISTERED → INSTALL_VERIFIED → LEARNING` inside the single request —
        the intermediate state is real and enumerable, but no client action sits between
        the two hops."

        Design: Corner/state_machines/verify_install_publishes_collecting_baseline_profile
        """
        state = setup_registered_device(api)
        verified = verify_install(api, state["device_id"])

        assert verified["lifecycle_state"] == "LEARNING"
        assert verified["installed_static_pressure_psi"] == TEST_DEFAULTS["INSTALL_PSI"]
        assert verified["install_verified_by_user_id"] == state["installer_user_id"]
        assert verified["install_verified_at"].startswith("2026-08-01T06:05:00")
        assert verified["baseline_ready"] is False
        # Registration then verification: one accepted write since creation.
        assert verified["version"] == 2

    def test_the_hold_test_mints_exactly_one_collecting_profile(self, api: ApiClient):
        """The learned values stay null until three eligible samples land.

        "In the same step exactly one baseline profile row is created for the device,
        with `device_id` pointing back at it, `learning_state` `COLLECTING`,
        `learning_cycle_no` at 1, `learning_started_at` set to the clock, `sample_count`
        at 0, and `baseline_version` at 0."
        "The three learned values — `baseline_static_pressure_psi`,
        `baseline_peak_flow_gpm`, and `drip_threshold_gpm` — are all null at this point,
        as are `completed_at`, `last_false_positive_at`, and `invalidated_reason`, and
        `false_positive_count` starts at 0."

        Design: Corner/state_machines/verify_install_publishes_collecting_baseline_profile
        """
        state = setup_registered_device(api)
        verify_install(api, state["device_id"])

        rows, meta = validate_paginated(
            api.list_baseline_profiles(state["device_id"], TECH)
        )
        assert meta["total_count"] == 1
        profile = rows[0]
        assert_baseline_profile(profile)
        assert profile["device_id"] == state["device_id"]
        assert profile["learning_state"] == "COLLECTING"
        assert profile["learning_cycle_no"] == 1
        assert profile["sample_count"] == 0
        assert profile["baseline_version"] == 0
        assert profile["learning_started_at"].startswith("2026-08-01T06:05:00")

        assert profile["baseline_static_pressure_psi"] is None
        assert profile["baseline_peak_flow_gpm"] is None
        assert profile["drip_threshold_gpm"] is None
        assert profile["completed_at"] is None
        assert profile["last_false_positive_at"] is None
        assert profile["invalidated_reason"] is None
        assert profile["false_positive_count"] == 0

    def test_a_second_hold_test_is_refused_and_overwrites_nothing(
        self, api: ApiClient
    ):
        """Once verified, a device has left the only state the operation accepts.

        "Verification is once only: a device whose `lifecycle_state` is anything other
        than `REGISTERED` refuses the operation with `ERR_INSTALL_ALREADY_VERIFIED`, and
        the device's property must be in `ACTIVE` state."
        "In the same step exactly one baseline profile row is created for the
        device, with `device_id` pointing back at it, `learning_state` `COLLECTING`,
        `learning_cycle_no` at 1, `learning_started_at` set to the clock,
        `sample_count` at 0, and `baseline_version` at 0."

        Design: Corner/state_machines/verify_install_twice_returns_install_already_verified
        """
        state = setup_registered_device(api)
        verify_install(api, state["device_id"])

        response = api.verify_install(
            state["device_id"],
            verify_install_payload(
                installed_static_pressure_psi=71.0, pressure_drop_psi=0.2
            ),
            make_installer_tech_headers(SECOND_INSTALLER_TECH_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_INSTALL_ALREADY_VERIFIED, 409)

        device = read_device(api, state["device_id"])
        assert device["installed_static_pressure_psi"] == TEST_DEFAULTS["INSTALL_PSI"]
        assert device["install_verified_by_user_id"] == state["installer_user_id"]

        rows, meta = validate_paginated(
            api.list_baseline_profiles(state["device_id"], TECH)
        )
        assert meta["total_count"] == 1
        assert rows[0]["learning_cycle_no"] == 1

    def test_one_tenth_of_a_psi_above_the_ceiling_fails_the_hold_test(
        self, api: ApiClient
    ):
        """A failed test mints no profile and leaves the device REGISTERED.

        "The test passes only when the static pressure is at least 40.0 and at most 80.0
        pounds per square inch **and** the pressure drop is at most 2.0 pounds per square
        inch; all three bounds are inclusive, so exactly 40.0, exactly 80.0, and a drop
        of exactly 2.0 all pass, while 39.9, 80.1, and a drop of 2.1 all fail with
        `ERR_INSTALL_PRESSURE_TEST_FAILED`."

        Design: Corner/state_machines/verify_install_above_max_static_pressure_returns_pressure_test_failed
        """
        state = setup_registered_device(api)

        response = api.verify_install(
            state["device_id"],
            verify_install_payload(
                installed_static_pressure_psi=80.1, pressure_drop_psi=0.5
            ),
            TECH,
        )
        validate_error(response, ApiErrorId.ERR_INSTALL_PRESSURE_TEST_FAILED, 422)

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "REGISTERED"
        assert device["installed_static_pressure_psi"] is None
        assert read_baseline_profiles(api, state["device_id"], TECH) == []

    def test_exactly_at_both_inclusive_ceilings_the_hold_test_passes(
        self, api: ApiClient
    ):
        """80.0 psi with a 2.0 psi drop is admitted, not refused.

        "The test passes only when the static pressure is at least 40.0 and at most 80.0
        pounds per square inch **and** the pressure drop is at most 2.0 pounds per square
        inch; all three bounds are inclusive, so exactly 40.0, exactly 80.0, and a drop
        of exactly 2.0 all pass, while 39.9, 80.1, and a drop of 2.1 all fail with
        `ERR_INSTALL_PRESSURE_TEST_FAILED`."

        Design: Corner/state_machines/verify_install_above_max_static_pressure_returns_pressure_test_failed
        """
        state = setup_registered_device(api)
        second = setup_second_registered_device(api, state)

        verified = verify_install(
            api,
            second["id"],
            installed_static_pressure_psi=80.0,
            pressure_drop_psi=2.0,
        )
        assert verified["lifecycle_state"] == "LEARNING"
        assert verified["installed_static_pressure_psi"] == 80.0
        assert read_live_baseline(api, second["id"])["learning_state"] == "COLLECTING"


class TestTelemetryAcceptingPosture:
    def test_a_registered_device_refuses_the_sample_and_stores_nothing(
        self, api: ApiClient
    ):
        """No hold test means no ingest, and no coverage minutes either.

        "A device accepts telemetry only while its `lifecycle_state` is `LEARNING`,
        `ARMED`, or `TRANSFER_PENDING`."
        "A `REGISTERED` device that has not yet passed its pressure test, and a
        `DECOMMISSIONED` device, both refuse the sample with
        `ERR_DEVICE_NOT_ACCEPTING_TELEMETRY`."
        "A refused sample is never persisted at all — it leaves no trace, contributes
        nothing to learning, and, importantly, contributes nothing to the uptime
        coverage the insurer scores."

        Design: Corner/state_machines/telemetry_to_registered_device_returns_not_accepting_telemetry
        """
        state = setup_registered_device(api)

        response = api.create_telemetry_reading(
            state["device_id"],
            telemetry_payload("2026-08-01T06:00:00Z", **QUIET_SAMPLE),
            GATEWAY,
        )
        validate_error(
            response, ApiErrorId.ERR_DEVICE_NOT_ACCEPTING_TELEMETRY, 409
        )

        assert read_telemetry(api, state["device_id"]) == []
        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "REGISTERED"
        assert device["last_reading_at"] is None


DEACTIVATED_AT = "2026-08-01T08:00:00Z"


def _decommissioned_by_account_closure(api: ApiClient) -> dict:
    """The widest cascade in the platform, run over one armed device."""
    state = setup_armed_device(api)
    set_clock(api, DEACTIVATED_AT)
    deactivate_homeowner(api, state["homeowner_id"])
    return state


class TestDecommissionedTerminalState:
    def test_the_closure_cascade_parks_the_device_in_its_terminal_state(
        self, api: ApiClient
    ):
        """Lifecycle, valve and mode are all forced, and the profile invalidated.

        "On success the homeowner moves `ACTIVE → DEACTIVATED` with `deactivated_at`
        stamped at the clock and `version` incremented, and the following cascade runs
        in full:"
        "Because a device carries three independent posture dimensions rather than one
        status, a newly registered row lands in `lifecycle_state` `REGISTERED`,
        `valve_state` `OPEN`, and `monitor_mode` `NORMAL` simultaneously, with
        `close_count` and `reopen_count` both at 0 and `monitor_mode_updated_at` equal
        to `created_at`."

        Design: Corner/state_machines/decommissioned_device_rejects_every_further_write
        """
        state = _decommissioned_by_account_closure(api)

        device = read_device(api, state["device_id"])
        assert_device(device)
        assert device["lifecycle_state"] == "DECOMMISSIONED"
        assert device["decommissioned_at"].startswith("2026-08-01T08:00:00")
        assert device["valve_state"] == "CLOSED"
        assert device["monitor_mode"] == "NORMAL"
        assert device["baseline_ready"] is False

        assert read_live_baseline(api, state["device_id"])["learning_state"] == (
            "INVALIDATED"
        )
        assert read_property(api, state["property_id"])["property_state"] == "ARCHIVED"
        assert read_homeowner(api, state["homeowner_id"])["account_state"] == (
            "DEACTIVATED"
        )

    def test_a_decommissioned_device_refuses_telemetry_and_valve_commands_alike(
        self, api: ApiClient
    ):
        """Nothing outgoing: the sample is rejected and the account gate answers first.

        "A `REGISTERED` device that has not yet passed its pressure test, and a
        `DECOMMISSIONED` device, both refuse the sample with
        `ERR_DEVICE_NOT_ACCEPTING_TELEMETRY`."
        "After closure the account can neither act nor be the target of a write: any
        attempt resolves to `ERR_HOMEOWNER_DEACTIVATED`."

        Design: Corner/state_machines/decommissioned_device_rejects_every_further_write
        """
        state = _decommissioned_by_account_closure(api)
        current_version = read_device_version(api, state["device_id"])

        validate_error(
            api.create_telemetry_reading(
                state["device_id"],
                telemetry_payload(DEACTIVATED_AT, **QUIET_SAMPLE),
                GATEWAY,
            ),
            ApiErrorId.ERR_DEVICE_NOT_ACCEPTING_TELEMETRY,
            409,
        )
        validate_error(
            api.send_valve_command(
                state["device_id"],
                valve_command_payload(
                    "OPEN",
                    current_version,
                    override_reason="Trying to reopen a dead device",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_HOMEOWNER_DEACTIVATED,
            409,
        )

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "DECOMMISSIONED"
        assert device["valve_state"] == "CLOSED"
        assert device["version"] == current_version
        # Only the three learning samples remain; the refused one left no trace.
        assert len(read_telemetry(api, state["device_id"])) == 3


BURST_AT = "2026-08-01T07:00:00Z"


def _resolved_burst_event(api: ApiClient) -> dict:
    """One catastrophic burst, acknowledged and then closed out by the homeowner."""
    state = setup_burst_event(api, BURST_AT)
    acknowledge_ticket(
        api, state["ticket_id"], make_homeowner_headers(state["homeowner_id"])
    )
    state["resolved"] = resolve_event(api, state["event_id"], state["homeowner_id"])
    return state


class TestEventClosureIsTerminal:
    def test_a_second_resolve_is_refused_and_overwrites_nothing(self, api: ApiClient):
        """RESOLVED has no outgoing edge, so the stored note survives untouched.

        "An anomaly event accepts a closing action only while its `event_state` is
        `DETECTED`, `ALERTED`, `ESCALATED`, or `SUPPRESSED`; an event already `RESOLVED`
        or `FALSE_POSITIVE` is terminal and refuses further feedback or resolution with
        `ERR_EVENT_NOT_ACTIONABLE`."
        "It carries `resolution_note`, a free-text closure note of 1 to 280 characters,
        and moves the event to `RESOLVED` with `resolved_at` stamped at the clock and the
        event's `version` incremented by 1."

        Design: Corner/state_machines/resolve_already_resolved_event_returns_event_not_actionable
        """
        state = _resolved_burst_event(api)
        assert state["resolved"]["event_state"] == "RESOLVED"

        validate_error(
            api.resolve_anomaly_event(
                state["event_id"],
                resolve_payload("Resolving again"),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            ApiErrorId.ERR_EVENT_NOT_ACTIONABLE,
            409,
        )

        event = read_events(api, state["device_id"])[0]
        assert event["event_state"] == "RESOLVED"
        assert event["resolution_note"] == "Burst hose bib replaced"
        assert event["resolved_at"].startswith("2026-08-01T07:00:00")
        assert event["feedback_label"] is None

    def test_a_resolved_event_refuses_feedback_and_tunes_nothing(
        self, api: ApiClient
    ):
        """The same terminal check gates the other closing verb.

        "An anomaly event accepts a closing action only while its `event_state` is
        `DETECTED`, `ALERTED`, `ESCALATED`, or `SUPPRESSED`; an event already `RESOLVED`
        or `FALSE_POSITIVE` is terminal and refuses further feedback or resolution with
        `ERR_EVENT_NOT_ACTIONABLE`."
        "Third, the live baseline is widened: `drip_threshold_gpm` becomes the smaller of
        an absolute ceiling of 0.50 gallons per minute and the current threshold
        increased by twenty percent, rounded half up to two decimal places;
        `last_false_positive_at` is stamped at the clock; and `baseline_version`
        increments by 1."

        Design: Corner/state_machines/resolve_already_resolved_event_returns_event_not_actionable
        """
        state = _resolved_burst_event(api)
        before = read_live_baseline(api, state["device_id"])

        validate_error(
            api.submit_event_feedback(
                state["event_id"],
                feedback_payload("FALSE_POSITIVE"),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            ApiErrorId.ERR_EVENT_NOT_ACTIONABLE,
            409,
        )

        profile = read_live_baseline(api, state["device_id"])
        assert_baseline_profile(profile)
        assert profile["false_positive_count"] == 0
        assert profile["drip_threshold_gpm"] == before["drip_threshold_gpm"]
        assert profile["baseline_version"] == before["baseline_version"]
        assert profile["last_false_positive_at"] is None
        assert read_events(api, state["device_id"])[0]["feedback_label"] is None


class TestValveCommandMustChangeSomething:
    def test_closing_an_already_closed_valve_does_not_double_count(
        self, api: ApiClient
    ):
        """The refusal lands ahead of the burst gate and consumes no version.

        "A command that would not change anything is refused: `CLOSE` on an
        already-closed valve, or `OPEN` on an already-open valve, yields
        `ERR_VALVE_ALREADY_IN_STATE`."
        "When no gate applies, the closure executes as a single atomic cascade: the
        device's `valve_state` moves `OPEN → CLOSED`, `close_count` increases by 1,
        `last_shutoff_at` is stamped with the clock, and the device's `version`
        increases by 1."

        Design: Corner/state_machines/valve_close_on_already_closed_valve_returns_valve_already_in_state
        """
        state = setup_burst_event(api, BURST_AT)
        closed = read_device(api, state["device_id"])
        assert closed["valve_state"] == "CLOSED"
        assert closed["close_count"] == 1

        validate_error(
            api.send_valve_command(
                state["device_id"],
                valve_command_payload(
                    "CLOSE", closed["version"], override_reason="Belt and braces"
                ),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            ApiErrorId.ERR_VALVE_ALREADY_IN_STATE,
            409,
        )

        after = read_device(api, state["device_id"])
        assert after["valve_state"] == "CLOSED"
        assert after["close_count"] == 1
        assert after["reopen_count"] == 0
        # The stale-version gate never fired, so the same version is still current.
        assert after["version"] == closed["version"]
        assert read_events(api, state["device_id"])[0]["event_state"] == "ALERTED"


SLA_BOUNDARY = "2026-08-01T07:15:00Z"
SECOND_CONTACT_PHONE = "+14155550404"


def _burst_with_a_verified_and_an_unverified_contact(api: ApiClient) -> dict:
    """Rank 1 is VERIFIED, rank 2 is left PENDING, and the SLA has just landed."""
    state = setup_burst_event(api, BURST_AT)
    state["verified_contact"] = create_emergency_contact(
        api, state["homeowner_id"], 1, verify_immediately=True
    )
    state["pending_contact"] = create_emergency_contact(
        api,
        state["homeowner_id"],
        2,
        full_name="Dee Nunez",
        phone_e164=SECOND_CONTACT_PHONE,
    )
    assert state["verified_contact"]["verification_state"] == "VERIFIED"
    assert state["pending_contact"]["verification_state"] == "PENDING"
    assert state["ticket"]["homeowner_deadline_at"].startswith("2026-08-01T07:15:00")
    set_clock(api, SLA_BOUNDARY)
    return state


def _contacts(api: ApiClient, state: dict) -> dict:
    rows = get_success_data(
        api.list_emergency_contacts(
            state["homeowner_id"], make_homeowner_headers(state["homeowner_id"])
        )
    )
    return {row["priority_rank"]: row for row in rows}


class TestEscalationLadderHop:
    def test_the_sweep_hops_the_ticket_to_the_verified_rank_one_contact(
        self, api: ApiClient
    ):
        """Exactly at the deadline the ladder climbs its second rung.

        "A ticket in `PENDING_HOMEOWNER` whose `homeowner_deadline_at` the clock has
        reached — inclusively, so exactly fifteen minutes after creation escalates and
        one minute earlier does nothing — attempts to escalate to the emergency roster."
        "If a contact is selected, the ticket moves
        `PENDING_HOMEOWNER → PENDING_EMERGENCY_CONTACT`: `notified_contact_id` records
        the chosen contact, `escalated_at` is stamped at the clock, `contact_deadline_at`
        is set to the clock plus 30 minutes, `notification_attempt_count` becomes 2, and
        the chosen contact's own `last_notified_at` is stamped at the clock."
        "The same hop mirrors onto the anomaly event, moving it `ALERTED → ESCALATED` and
        incrementing the event's `version` by 1."

        Design: Corner/state_machines/ops_sweep_hops_ticket_to_verified_emergency_contact
        """
        state = _burst_with_a_verified_and_an_unverified_contact(api)

        report = run_ops_sweep(api)
        assert report["tickets_escalated"] == 1
        assert report["tickets_expired"] == 0
        assert report["modes_reverted"] == 0
        assert report["transfers_expired"] == 0
        assert report["swept_at"].startswith("2026-08-01T07:15:00")

        ticket = read_tickets(api, anomaly_event_id=state["event_id"])[0]
        assert_escalation_ticket(ticket)
        assert ticket["id"] == state["ticket_id"]
        assert ticket["stage"] == "PENDING_EMERGENCY_CONTACT"
        assert ticket["notified_contact_id"] == state["verified_contact"]["id"]
        assert ticket["escalated_at"].startswith("2026-08-01T07:15:00")
        assert ticket["contact_deadline_at"].startswith("2026-08-01T07:45:00")
        assert ticket["notification_attempt_count"] == 2
        assert ticket["expiry_reason"] is None

        event = read_events(api, state["device_id"])[0]
        assert event["event_state"] == "ESCALATED"

    def test_the_pending_rank_two_contact_is_skipped_and_the_hop_is_not_repeated(
        self, api: ApiClient
    ):
        """Verification, not rank, decides; and a second sweep finds nothing to do.

        "The eligible pool is the owning homeowner's emergency contacts whose `status` is
        `ACTIVE` **and** whose `verification_state` is `VERIFIED`; contacts still
        `PENDING` verification are ineligible, and this is a real failure mode rather
        than a theoretical one."
        "The sweep walks tickets whose `stage` is `PENDING_HOMEOWNER` or
        `PENDING_EMERGENCY_CONTACT` and whose underlying anomaly event is still `ALERTED`
        or `ESCALATED`, in chronological order by ticket `created_at` ascending, and
        applies the following to each."

        Design: Corner/state_machines/ops_sweep_hops_ticket_to_verified_emergency_contact
        """
        state = _burst_with_a_verified_and_an_unverified_contact(api)
        run_ops_sweep(api)

        contacts = _contacts(api, state)
        assert contacts[1]["last_notified_at"].startswith("2026-08-01T07:15:00")
        assert contacts[2]["verification_state"] == "PENDING"
        assert contacts[2]["last_notified_at"] is None

        again = run_ops_sweep(api)
        assert again["tickets_escalated"] == 0
        assert again["tickets_expired"] == 0

        ticket = read_tickets(api, anomaly_event_id=state["event_id"])[0]
        assert ticket["stage"] == "PENDING_EMERGENCY_CONTACT"
        assert ticket["notification_attempt_count"] == 2
        assert ticket["notified_contact_id"] == contacts[1]["id"]
        assert _contacts(api, state)[2]["last_notified_at"] is None
