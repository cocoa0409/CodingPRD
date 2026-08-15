"""Outage window lifecycle: temporal guards, half-open overlap, overrun charge
variants, approve/cancel reconciliation, and the closure cascade (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    assert_same_instant,
    create_circuit,
    create_window,
    approve_window,
    activate_window,
    close_window,
    set_clock,
    get_window,
    get_circuit,
    get_unit,
    get_assignment,
    setup_job_completed,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]


class TestWindowTemporalGuards:
    def test_window_starting_in_the_past_rejected(self, api):
        """PRD §3.2: "the window's start must not precede the logical clock —
        a past-start window is rejected with `ERR_WINDOW_IN_PAST`".

        Design: Corner/validations/window_in_past_rejected
        """
        circuit = create_circuit("CKT-V2")
        set_clock("2026-08-10T09:00:00Z")
        resp = api.create_outage_window(
            {
                "circuit_id": circuit["id"],
                "kind": "PLANNED_DIAGNOSTIC",
                "window_start": "2026-08-09T08:00:00Z",
                "window_end": "2026-08-09T12:00:00Z",
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)

    def test_window_before_default_clock_rejected(self, api):
        """PRD §2.4: "On server startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time at any
        point afterwards."
        PRD §3.2: "the window's start must not precede the logical clock —
        a past-start window is rejected with `ERR_WINDOW_IN_PAST`".

        Design: Corner/endpoints/window_before_default_clock_rejected
        """
        circuit = create_circuit("CKT-P6")
        # Clock is never set: startup default 2026-08-01T00:00:00Z applies.
        resp = api.create_outage_window(
            {
                "circuit_id": circuit["id"],
                "kind": "PLANNED_DIAGNOSTIC",
                "window_start": "2026-07-31T23:00:00Z",
                "window_end": "2026-08-01T02:00:00Z",
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)

    def test_close_twice_rejected(self, api):
        """PRD §3.2: "the window moves from `ACTIVE` to `CLOSED`."
        PRD §2.7: "6. **State legality** — the target entity must be in an
        allowed from-state for the requested transition, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/window_close_twice_rejected
        """
        circuit = create_circuit("CKT-S1")
        window = create_window(
            circuit["id"], window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
        )
        approve_window(window["id"])
        set_clock("2026-08-10T09:00:00Z")
        activate_window(window["id"])
        close_window(window["id"], "2026-08-10T10:15:00Z")

        resp = api.close_window(window["id"], {"restored_at": "2026-08-10T10:30:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_window(window["id"])
        assert after["status"] == "CLOSED"
        assert after["overrun_minutes"] == 15, "no overrun recomputation on the rejected close"


class TestWindowOverlap:
    def test_half_open_adjacency_allowed(self, api):
        """PRD §3.2: "the half-open interval must not overlap any existing
        window of the same circuit that is still in `REQUESTED`, `APPROVED`,
        or `ACTIVE` status, with pure adjacency (one window's start equal to
        another's end) explicitly permitted".

        Design: Difficulty/resource_temporal_overlap/outage_windows_half_open_adjacency_allowed
        """
        circuit = create_circuit("CKT-TO1")
        window_a = create_window(
            circuit["id"], window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T12:00:00Z",
        )
        resp = api.create_outage_window(
            {
                "circuit_id": circuit["id"],
                "kind": "REPAIR_RESTORE",
                "window_start": "2026-08-10T12:00:00Z",
                "window_end": "2026-08-10T14:00:00Z",
            },
            PLANNER,
        )
        window_b = validate_success(resp, 201)
        assert window_b["status"] == "REQUESTED", (
            "adjacency under half-open semantics is not overlap: the adjacent "
            "window is created and lands in REQUESTED (PRD §3.2)"
        )
        assert_same_instant(window_b["window_start"], "2026-08-10T12:00:00Z")
        assert window_a["id"] != window_b["id"]

    def test_one_minute_earlier_start_overlaps(self, api):
        """PRD §3.2: "an offending overlap is rejected with
        `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_windows_half_open_adjacency_allowed
        """
        circuit = create_circuit("CKT-TO1")
        create_window(
            circuit["id"], window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T12:00:00Z",
        )
        resp = api.create_outage_window(
            {
                "circuit_id": circuit["id"],
                "kind": "EMERGENCY_FAULT",
                "window_start": "2026-08-10T11:59:00Z",
                "window_end": "2026-08-10T13:00:00Z",
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


class TestOverrunCharge:
    def test_grace_boundary_fifteen_minutes_free(self, api):
        """PRD §3.2: "A grace period of fifteen minutes applies: only overrun
        minutes beyond the grace are chargeable, so an overrun of fifteen
        minutes or less costs nothing."

        Design: Difficulty/boundary_precision_check/overrun_grace_exactly_fifteen_minutes_free
        """
        circuit = create_circuit("CKT-BP3")
        window = create_window(
            circuit["id"], window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
        )
        approve_window(window["id"])
        set_clock("2026-08-10T09:00:00Z")
        activate_window(window["id"])
        closed = close_window(window["id"], "2026-08-10T10:15:00Z")
        assert closed["overrun_minutes"] == 15
        assert closed["overrun_charge_cents"] == 0, (
            "overrun == 15 is not > the 15-minute grace, so nothing is chargeable"
        )

    def test_sixteen_minutes_charges_one_tier1_minute(self, api):
        """PRD §3.2: "Chargeable minutes are then priced marginally across
        three tiers — the first sixty chargeable minutes at 400 cents per
        minute, the next one hundred twenty chargeable minutes at 650 cents
        per minute, and any chargeable minutes beyond one hundred eighty at
        900 cents per minute."

        Design: Difficulty/boundary_precision_check/overrun_grace_exactly_fifteen_minutes_free
        """
        circuit = create_circuit("CKT-BP3")
        window = create_window(
            circuit["id"], window_start="2026-08-10T13:00:00Z",
            window_end="2026-08-10T15:00:00Z",
        )
        approve_window(window["id"])
        set_clock("2026-08-10T14:00:00Z")
        activate_window(window["id"])
        closed = close_window(window["id"], "2026-08-10T15:16:00Z")
        assert closed["overrun_minutes"] == 16
        assert closed["overrun_charge_cents"] == 400, (
            "1 chargeable minute beyond grace at the 400-cent first tier"
        )

    def test_estimate_variant_stored_at_approve_actual_zero_at_close(self, api):
        """PRD §3.2: "A provisional exposure figure is stored in the window's
        `estimated_charge_cents`, computed with the estimate variant of the
        overrun charge: the estimated overrun is ten percent of
        `duration_minutes` rounded up to a whole minute, and that estimate is
        then priced with the tiered formula below."
        PRD §3.2: "computes `overrun_minutes` as zero when restoration
        happened at or before `window_end`".

        Design: Corner/calculations/overrun_estimate_variant_at_approve
        """
        circuit = create_circuit("CKT-C3")
        window = create_window(
            circuit["id"], window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T12:00:00Z",
        )
        approved = approve_window(window["id"])
        assert approved["duration_minutes"] == 240
        # estimate variant: ceil(240 * 0.10) = 24 overrun min -> 24 - 15 = 9
        # chargeable minutes at tier 1 (400 c/min) = 3600 cents.
        assert approved["estimated_charge_cents"] == 3600

        set_clock("2026-08-10T09:00:00Z")
        activate_window(window["id"])
        closed = close_window(window["id"], "2026-08-10T12:00:00Z")
        assert closed["overrun_minutes"] == 0
        assert closed["overrun_charge_cents"] == 0, (
            "restoration exactly at window_end is not an overrun (actual variant)"
        )


class TestApproveCancelReconciliation:
    def test_approve_adds_and_cancel_subtracts_minutes(self, api):
        """PRD §3.2: "Its `duration_minutes` is added to the circuit's
        `approved_outage_minutes_total`."
        PRD §3.2: "Cancelling an `APPROVED` window subtracts its
        `duration_minutes` from the circuit's `approved_outage_minutes_total`
        and, when no other window of the circuit remains in `APPROVED` or
        `ACTIVE`, returns the circuit `OUTAGE_PENDING` → `IN_SERVICE`."
        PRD §2.5: "`version`, an integer that increments by one on every
        mutation of the resource."

        Design: Corner/cross_cutting_layers/window_approve_cancel_conserves_minutes
        """
        circuit = create_circuit("CKT-X5")
        window = create_window(
            circuit["id"], window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T12:00:00Z",
        )
        created_version = window["version"]
        approved = approve_window(window["id"])
        assert approved["version"] == created_version + 1, (
            "approving mutates the window, so its version increments by one"
        )
        mid = get_circuit(circuit["id"])
        assert mid["approved_outage_minutes_total"] == 240
        assert mid["status"] == "OUTAGE_PENDING"

        validate_success(api.cancel_window(window["id"], PLANNER))
        end = get_circuit(circuit["id"])
        assert end["approved_outage_minutes_total"] == 0
        assert end["status"] == "IN_SERVICE"


class TestWindowCloseCascade:
    def test_close_restores_circuit_and_rolls_back_minutes(self, api):
        """PRD §3.2: "Hop one touches the circuit: if the circuit is
        `RESTORING` it returns `RESTORING` → `IN_SERVICE`" and "The window's
        `duration_minutes` is subtracted from the circuit's
        `approved_outage_minutes_total`". The 60-minute overshoot is priced
        after the 15-minute grace: 45 chargeable minutes at 400 cents.

        Design: Difficulty/transitive_cascade/window_close_cascade_restores_circuit_and_frees_fleet
        """
        ctx = setup_job_completed("CKT-TC2")
        circuit_id = ctx["circuit"]["id"]
        window_id = ctx["window"]["id"]
        set_clock("2026-08-12T13:00:00Z")
        closed = close_window(window_id, "2026-08-12T13:00:00Z")
        assert closed["status"] == "CLOSED"
        assert closed["overrun_minutes"] == 60
        assert closed["overrun_charge_cents"] == 18000, (
            "60 overrun minutes - 15 grace = 45 chargeable at 400 cents/min"
        )
        circuit = get_circuit(circuit_id)
        assert circuit["status"] == "IN_SERVICE", (
            "hop 1: circuit was RESTORING after permit release"
        )
        assert circuit["approved_outage_minutes_total"] == 0

    def test_close_releases_assignment_and_frees_unit(self, api):
        """PRD §3.2: "Hop two touches the fleet: every equipment assignment
        belonging to this circuit's jobs that is `CONFIRMED` or `ACTIVE` is
        moved to `RELEASED`. Hop three settles the hours: each released
        assignment subtracts its stored `duration_hours` from its unit's
        `committed_hours`, and a mobile unit left with no remaining assignment
        in `RESERVED`, `CONFIRMED`, or `ACTIVE` transitions `ASSIGNED` →
        `AVAILABLE`."

        Design: Difficulty/transitive_cascade/window_close_cascade_restores_circuit_and_frees_fleet
        """
        ctx = setup_job_completed("CKT-TC2")
        assignment_id = ctx["assignment"]["id"]
        unit_id = ctx["unit"]["id"]
        assert ctx["assignment"]["duration_hours"] == 53.0

        set_clock("2026-08-12T13:00:00Z")
        close_window(ctx["window"]["id"], "2026-08-12T13:00:00Z")

        assignment = get_assignment(assignment_id)
        assert assignment["status"] == "RELEASED", (
            "hop 2: CONFIRMED assignment cascade-released on window close"
        )
        unit = get_unit(unit_id)
        assert unit["committed_hours"] == 0.0, (
            "hop 3: the released 53.0 hours are subtracted from committed_hours"
        )
        assert unit["status"] == "AVAILABLE"
