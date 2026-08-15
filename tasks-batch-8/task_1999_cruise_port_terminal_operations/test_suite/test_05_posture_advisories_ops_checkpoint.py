"""Terminal posture derivation, weather advisory lifecycle, the operations
checkpoint sweep, and posture gating of departures and dispatches."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_berth_assignment,
    create_berth,
    create_port_call,
    create_terminal,
    create_transport_slot,
    create_weather_advisory,
    get_berth_assignment,
    get_port_call,
    get_terminal,
    get_transport_slot,
    get_weather_advisory,
    set_clock,
    setup_arrived_call,
    setup_base,
    setup_turnaround_call,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HARBORMASTER = TEST_USERS["harbormaster_headers"]


class TestPostureDerivation:
    def test_posture_derived_from_occupancy_and_advisories(self, api):
        """PRD §2.5: "The posture is `EMERGENCY` whenever the terminal has an
        `ACTIVE` weather advisory of severity `EMERGENCY` whose window covers
        the logical now. Failing that, the posture is `CONSTRAINED` whenever the
        terminal has an `ACTIVE` advisory of severity `WARNING` whose window
        covers the logical now, or when `free_berth_count` is zero. Otherwise
        the posture is `OPERATIONAL`."
        PRD §2.5: "Advisories of severity `WATCH` never affect posture,
        regardless of their window."

        Design: Corner/calculations/posture_derived_from_occupancy_and_advisories
        """
        # Two berths; the call arrives onto B1, leaving one free berth.
        ctx = setup_arrived_call()
        b2 = create_berth(ctx["terminal"]["id"], berth_code="B2",
                          length_ft=1100, max_draft_ft=38.0)
        term_id = ctx["terminal"]["id"]

        create_weather_advisory(term_id, severity="WATCH")

        t1 = get_terminal(term_id)
        assert t1["posture"] == "OPERATIONAL"
        assert t1["free_berth_count"] == 1, "2 active berths, 1 occupied"

        # Removing the last free berth drives free_berth_count to zero.
        validate_success(api.out_of_service_berth(b2["id"], ADMIN))
        t2 = get_terminal(term_id)
        assert t2["posture"] == "CONSTRAINED"
        assert t2["free_berth_count"] == 0

        validate_success(api.return_to_service_berth(b2["id"], ADMIN))
        create_weather_advisory(term_id, severity="WARNING")
        t3 = get_terminal(term_id)
        assert t3["posture"] == "CONSTRAINED", "a live WARNING forces CONSTRAINED"

        emergency = create_weather_advisory(term_id, severity="EMERGENCY")
        t4 = get_terminal(term_id)
        assert t4["posture"] == "EMERGENCY", "EMERGENCY overrides WARNING"

        validate_success(api.cancel_weather_advisory(emergency["id"], ADMIN))
        t5 = get_terminal(term_id)
        assert t5["posture"] == "CONSTRAINED", (
            "the still-active WARNING keeps the terminal CONSTRAINED"
        )


class TestOpsRunCheckpoint:
    def test_run_ops_sweeps_expiries_and_advances_index(self, api):
        """PRD §3.4: "The **operations checkpoint** — an admin-only capability
        restricted to `PortAuthorityAdmin` — sweeps the terminal against the
        logical clock: every `ACTIVE` advisory whose `window_end` is at or
        before the logical now becomes `EXPIRED`; every `TENTATIVE` berth
        assignment whose `window_start` is at or before the logical now becomes
        `EXPIRED`, its hold on the berth lapsed; and every `QUEUED` transport
        slot whose port call has reached `DEPARTED`, `CLOSED`, or `CANCELLED`
        becomes `EXPIRED`."
        PRD §3.4: "The sweep then recomputes the terminal's posture, increments
        `ops_run_index` by 1 — a monotone counter of how many checkpoints the
        terminal has run — and increments the terminal's `version` by 1."

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_sweep
        """
        ctx = setup_base()
        pc = create_port_call(
            ctx["terminal"]["id"], ctx["vessel"]["id"], voyage_ref="V1",
            scheduled_eta="2026-08-01T06:30:00Z",
            scheduled_etd="2026-08-01T12:30:00Z")
        assignment = add_berth_assignment(
            pc["id"], ctx["berth"]["id"],
            window_start="2026-08-01T06:00:00Z",
            window_end="2026-08-01T18:00:00Z",
            expected_port_call_version=pc["version"])
        advisory = create_weather_advisory(
            ctx["terminal"]["id"], severity="WARNING",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-02T00:00:00Z")

        before = get_terminal(ctx["terminal"]["id"])
        assert before["posture"] == "CONSTRAINED", "WARNING covers the default now"
        assert before["ops_run_index"] == 0

        set_clock("2026-08-03T00:00:00Z")
        swept = validate_success(api.run_ops(ctx["terminal"]["id"], ADMIN))
        assert swept["ops_run_index"] == 1

        assert get_weather_advisory(advisory["id"])["status"] == "EXPIRED"
        assert get_berth_assignment(assignment["id"])["status"] == "EXPIRED"

        after = get_terminal(ctx["terminal"]["id"])
        assert after["posture"] == "OPERATIONAL"


class TestAdvisoryValidation:
    def test_advisory_window_end_not_after_start_rejected(self, api):
        """PRD §3.4: "The window must be sane — `window_end` strictly later
        than `window_start` — or the advisory is rejected with
        `ERR_ADVISORY_WINDOW_INVALID` (HTTP 422)."

        Design: Corner/validations/advisory_window_invalid_rejected
        """
        terminal = create_terminal()
        resp = api.create_weather_advisory(
            {"terminal_id": terminal["id"], "severity": "WARNING",
             "window_start": "2026-08-10T00:00:00Z",
             "window_end": "2026-08-10T00:00:00Z"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_ADVISORY_WINDOW_INVALID)


class TestPostureGates:
    def test_emergency_posture_blocks_depart(self, api):
        """PRD §2.5: "While the posture is `EMERGENCY`, five operations are
        refused with `ERR_POSTURE_EMERGENCY` (HTTP 409): creating a berth
        assignment, confirming a berth assignment, approving a service order,
        dispatching a ground-transport slot, and departing a port call."
        PRD §3.3: "From `TURNAROUND`, four conditions must hold, evaluated in
        pipeline order: the terminal's posture must not be `EMERGENCY`
        (`ERR_POSTURE_EMERGENCY`); ..."

        Design: Corner/validations/emergency_posture_blocks_depart
        """
        ctx = setup_turnaround_call(customs="cleared")
        # EMERGENCY advisory covering the default logical now (2026-08-01).
        create_weather_advisory(ctx["terminal"]["id"], severity="EMERGENCY")

        resp = api.depart_port_call(ctx["port_call"]["id"],
                                    {"actual_etd": "2026-08-10T20:00:00Z"},
                                    HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_POSTURE_EMERGENCY)
        assert get_port_call(ctx["port_call"]["id"])["status"] == "TURNAROUND"

    def test_dispatch_blocked_in_emergency(self, api):
        """PRD §2.5: "While the posture is `EMERGENCY`, five operations are
        refused with `ERR_POSTURE_EMERGENCY` (HTTP 409): creating a berth
        assignment, confirming a berth assignment, approving a service order,
        dispatching a ground-transport slot, and departing a port call."

        Design: Corner/validations/dispatch_blocked_in_emergency
        """
        ctx = setup_arrived_call()
        slot = create_transport_slot(ctx["terminal"]["id"],
                                     ctx["port_call"]["id"], vehicle_class="TAXI")
        create_weather_advisory(ctx["terminal"]["id"], severity="EMERGENCY")

        resp = api.dispatch_transport_slot(slot["id"], TEST_USERS["operator_headers"])
        validate_error(resp, ApiErrorId.ERR_POSTURE_EMERGENCY)
        assert get_transport_slot(slot["id"])["status"] == "QUEUED"
