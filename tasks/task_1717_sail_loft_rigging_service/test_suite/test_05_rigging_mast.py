"""Rigging inspections (replacement clocks, FAIL cascades) and mast services
(half-open slots, safety gates, hold release)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    assert_rigging_inspection,
    create_boat,
    create_customer,
    create_mast_service_event,
    create_rigging_inspection,
    get_boat,
    get_mast_service_event,
    get_rigging_inspection,
    report_inspection,
    setup_boat_with_reported_fail,
    setup_customer_with_boat,
    setup_fail_closed_by_replacement,
    validate_error,
    validate_success,
    TEST_USERS,
)

MGR = TEST_USERS["loft_manager_headers"]
RIG = TEST_USERS["rigger_headers"]


# ---------------------------------------------------------------------------
# Dual replacement clocks: calendar months vs sail-hours — PRD §2.11/§3.6
# ---------------------------------------------------------------------------

def _report_full_pass(hours, install_date):
    ctx = setup_customer_with_boat(
        hull_length_m=10.0, racing_class="J70",
        standing_rigging_install_date=install_date,
        running_rigging_hours_accumulated=hours,
    )
    inspection = create_rigging_inspection(ctx["boat"]["id"], rigging_scope="FULL")
    reported = report_inspection(ctx["boat"]["id"], inspection["id"], "PASS")
    return ctx, reported


def test_hours_clock_overrides_pass_to_advisory(api):
    """PRD §3.6: "`standing_replacement_due_date` is the calendar date exactly 120
    months after the installation date; and `running_replacement_due_hours` is the
    hours-variant threshold of 2,000 sail-hours. The verdict floor of §2.11 then
    applies on both clocks: if `standing_months_at_inspection` is at least 120, or
    if the boat's `running_rigging_hours_accumulated` is at least 2,000, a filed
    `PASS` is recorded as `ADVISORY`."

    Design: Difficulty/dual_variant_calc/rigging_calendar_vs_hours_variants_diverge
    """
    _, reported = _report_full_pass(hours=2100, install_date="2025-08-01T00:00:00Z")
    assert_rigging_inspection(reported)
    # Hours clock trips (2100 >= 2000); calendar clock does not (~12 < 120 months).
    assert reported["verdict"] == "ADVISORY", (
        f"hours at/above 2000 must floor a filed PASS to ADVISORY, got {reported['verdict']}"
    )
    # PRD pins the VALUE ("the calendar date exactly 120 months after the
    # installation date") but not its serialization format; compare instants.
    due = datetime.fromisoformat(
        reported["standing_replacement_due_date"].replace("Z", "+00:00")
    )
    assert due == datetime(2035, 8, 1, tzinfo=timezone.utc), (
        f"calendar due date must be install + 120 months: {reported['standing_replacement_due_date']}"
    )
    assert reported["running_replacement_due_hours"] == 2000


def test_calendar_clock_passes_while_hours_floor_trips(api):
    """PRD §2.11: "Because the clocks measure different things, they can disagree
    for the same boat at the same moment: a two-year-old boat with 2,100
    sail-hours passes the calendar test but trips the hours floor."

    Design: Difficulty/dual_variant_calc/rigging_calendar_vs_hours_variants_diverge
    """
    _, reported = _report_full_pass(hours=2100, install_date="2025-08-01T00:00:00Z")
    # Calendar variant: the boat is ~1 year old, far under the 120-month floor...
    assert reported["standing_months_at_inspection"] < 120, (
        f"calendar clock must not trip for a young boat: {reported['standing_months_at_inspection']}"
    )
    # ...yet the recorded verdict is ADVISORY — only the hours clock can explain it.
    assert reported["verdict"] == "ADVISORY"


# ---------------------------------------------------------------------------
# Boundary: standing rigging at 119 vs 120 months (inclusive >=) — PRD §3.6
# ---------------------------------------------------------------------------

def test_standing_at_119_months_keeps_pass_verdict(api):
    """PRD §3.6: "if `standing_months_at_inspection` is at least 120, or if the
    boat's `running_rigging_hours_accumulated` is at least 2,000, a filed `PASS`
    is recorded as `ADVISORY`."

    Design: Difficulty/boundary_precision_check/standing_rigging_at_119_vs_120_months_advisory_boundary
    """
    ctx = setup_customer_with_boat(
        hull_length_m=10.0, boat_name="B12a",
        standing_rigging_install_date="2016-09-01T00:00:00Z",
        running_rigging_hours_accumulated=0,
    )
    inspection = create_rigging_inspection(ctx["boat"]["id"], rigging_scope="STANDING")
    reported = report_inspection(ctx["boat"]["id"], inspection["id"], "PASS")
    assert reported["standing_months_at_inspection"] == 119, (
        f"install 2016-09-01 must read 119 whole months, got {reported['standing_months_at_inspection']}"
    )
    assert reported["verdict"] == "PASS", (
        f"119 < 120 leaves the filed PASS intact, got {reported['verdict']}"
    )


def test_standing_at_120_months_forces_advisory(api):
    """PRD §3.6: "if `standing_months_at_inspection` is at least 120, or if the
    boat's `running_rigging_hours_accumulated` is at least 2,000, a filed `PASS`
    is recorded as `ADVISORY`."

    Design: Difficulty/boundary_precision_check/standing_rigging_at_119_vs_120_months_advisory_boundary
    """
    ctx = setup_customer_with_boat(
        hull_length_m=10.0, boat_name="B12b",
        standing_rigging_install_date="2016-08-01T00:00:00Z",
        running_rigging_hours_accumulated=0,
    )
    inspection = create_rigging_inspection(ctx["boat"]["id"], rigging_scope="STANDING")
    reported = report_inspection(ctx["boat"]["id"], inspection["id"], "PASS")
    assert reported["standing_months_at_inspection"] == 120, (
        f"install 2016-08-01 must read 120 whole months, got {reported['standing_months_at_inspection']}"
    )
    assert reported["verdict"] == "ADVISORY", (
        f"120 >= 120 must override PASS to ADVISORY, got {reported['verdict']}"
    )


# ---------------------------------------------------------------------------
# FAIL cascade: boat grounded, BOOKED events held — PRD §3.6
# ---------------------------------------------------------------------------

def test_fail_report_grounds_boat_and_holds_bookings(api):
    """PRD §3.6: "Filing a `FAIL` report transitions the boat's `status` from
    `ACTIVE` to `OUT_OF_SERVICE`, and — caused by that status change together with
    the open failed inspection — every mast service event for the boat sitting in
    `BOOKED` status transitions to `RIGGING_HOLD`."

    Design: Difficulty/transitive_cascade/rigging_fail_cascades_two_hops_to_mast_events
    """
    ctx = setup_boat_with_reported_fail(
        boat_kw={"hull_length_m": 10.5, "racing_class": "J105", "running_rigging_hours_accumulated": 100},
        scope="STANDING",
    )
    assert ctx["inspection"]["inspection_status"] == "REPORTED"
    assert ctx["inspection"]["verdict"] == "FAIL"
    boat = get_boat(ctx["boat"]["id"])
    assert boat["status"] == "OUT_OF_SERVICE", f"hop 1: boat must ground, got {boat['status']}"
    event = get_mast_service_event(ctx["mast_event"]["id"])
    assert event["event_status"] == "RIGGING_HOLD", (
        f"hop 2: BOOKED event must be held, got {event['event_status']}"
    )


def test_fail_report_holds_only_booked_events(api):
    """PRD §3.6: "every mast service event for the boat sitting in `BOOKED` status
    transitions to `RIGGING_HOLD`" — events already COMPLETED are outside the
    cascade's remit.

    Design: Difficulty/transitive_cascade/rigging_fail_cascades_two_hops_to_mast_events
    """
    ctx = setup_customer_with_boat(hull_length_m=10.5, racing_class="J105",
                                   running_rigging_hours_accumulated=100)
    boat_id = ctx["boat"]["id"]
    done = create_mast_service_event(boat_id, service_kind="UNSTEP",
                                     slot_start_utc="2026-09-01T08:00:00Z",
                                     slot_end_utc="2026-09-01T12:00:00Z")
    validate_success(api.start_mast_event(boat_id, done["id"], RIG))
    completed = validate_success(api.complete_mast_event(boat_id, done["id"], RIG))
    assert completed["event_status"] == "COMPLETED"
    pending = create_mast_service_event(boat_id, service_kind="TUNE",
                                        slot_start_utc="2026-09-02T08:00:00Z",
                                        slot_end_utc="2026-09-02T12:00:00Z")

    inspection = create_rigging_inspection(boat_id, rigging_scope="STANDING")
    reported = report_inspection(boat_id, inspection["id"], "FAIL")
    assert reported["verdict"] == "FAIL"

    assert get_mast_service_event(done["id"])["event_status"] == "COMPLETED", (
        "COMPLETED events must not be dragged into RIGGING_HOLD"
    )
    assert get_mast_service_event(pending["id"])["event_status"] == "RIGGING_HOLD"
    assert get_boat(boat_id)["status"] == "OUT_OF_SERVICE"


# ---------------------------------------------------------------------------
# Cross-entity gate: mast start blocked by an unresolved FAIL — PRD §3.6
# ---------------------------------------------------------------------------

def test_mast_start_blocked_while_fail_unresolved(api):
    """PRD §3.6: "Starting moves a `BOOKED` event to `IN_PROGRESS`, but only while
    no rigging inspection for the boat sits in `REPORTED` with a `FAIL` verdict
    and the boat's `status` is not `OUT_OF_SERVICE` — a violation is rejected with
    `ERR_UNRESOLVED_RIGGING_FAIL` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/mast_service_start_blocked_by_open_fail_inspection
    """
    ctx = setup_boat_with_reported_fail(scope="FULL")
    boat_id = ctx["boat"]["id"]
    # Booked after the FAIL, on a different day than the held event; booking runs
    # only the overlap rule (PRD §3.6), so the event lands in BOOKED.
    fresh = create_mast_service_event(boat_id, service_kind="TUNE",
                                      slot_start_utc="2026-09-06T08:00:00Z",
                                      slot_end_utc="2026-09-06T12:00:00Z")
    assert fresh["event_status"] == "BOOKED"

    resp = api.start_mast_event(boat_id, fresh["id"], RIG)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_RIGGING_FAIL)
    assert get_mast_service_event(fresh["id"])["event_status"] == "BOOKED", (
        "rejected start must leave the event BOOKED"
    )


def test_mast_start_allowed_after_fail_closed(api):
    """PRD §3.6: "When the failed inspection is closed on the strength of that
    passing replacement, the hold releases: the boat's `status` may return to
    `ACTIVE`, and the boat's held mast service events return from `RIGGING_HOLD`
    to `BOOKED` automatically."
    PRD §3.6: "At start, the boat's `mast_status` moves per the `service_kind`:
    `UNSTEPPED` for an unstep, `STEPPED` for a step, and `TUNING_IN_PROGRESS` for
    a tune."

    Design: Difficulty/cross_entity_state_dependency/mast_service_start_blocked_by_open_fail_inspection
    """
    ctx = setup_fail_closed_by_replacement(scope="STANDING")
    boat_id = ctx["boat"]["id"]
    event = get_mast_service_event(ctx["mast_event"]["id"])
    assert event["event_status"] == "BOOKED", "hold must release the event to BOOKED"

    started = validate_success(api.start_mast_event(boat_id, event["id"], RIG))
    assert started["event_status"] == "IN_PROGRESS"
    boat = get_boat(boat_id)
    assert boat["mast_status"] == "UNSTEPPED", (
        f"starting an UNSTEP must move mast_status to UNSTEPPED, got {boat['mast_status']}"
    )


# ---------------------------------------------------------------------------
# Mast slots: half-open intervals, adjacency allowed — PRD §2.10
# ---------------------------------------------------------------------------

def test_mast_slot_adjacent_booking_allowed(api):
    """PRD §2.10: "Mast work books the crane and rig dock in half-open intervals:
    a mast service event occupies its slot from `slot_start_utc` up to but not
    including `slot_end_utc`. Two events on the same boat conflict when the first
    event's slot start is earlier than the second event's slot end and the second
    event's slot start is earlier than the first event's slot end; because the
    interval is half-open, one event ending at exactly the instant another begins
    is permitted."

    Design: Difficulty/resource_temporal_overlap/mast_slot_half_open_adjacency_allowed
    """
    ctx = setup_customer_with_boat(hull_length_m=10.0)
    boat_id = ctx["boat"]["id"]
    first = create_mast_service_event(boat_id, service_kind="UNSTEP",
                                      slot_start_utc="2026-09-10T08:00:00Z",
                                      slot_end_utc="2026-09-10T12:00:00Z")
    second = create_mast_service_event(boat_id, service_kind="STEP",
                                       slot_start_utc="2026-09-10T12:00:00Z",
                                       slot_end_utc="2026-09-10T16:00:00Z")
    assert first["event_status"] == "BOOKED"
    assert second["event_status"] == "BOOKED", (
        "adjacency (start == prior end) must be permitted under half-open semantics"
    )
    assert second["slot_start_utc"] == first["slot_end_utc"]


def test_mast_slot_partial_overlap_rejected(api):
    """PRD §2.10: "An overlapping booking is rejected with `ERR_MAST_SLOT_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/mast_slot_half_open_adjacency_allowed
    """
    ctx = setup_customer_with_boat(hull_length_m=10.0)
    boat_id = ctx["boat"]["id"]
    create_mast_service_event(boat_id, service_kind="UNSTEP",
                              slot_start_utc="2026-09-10T08:00:00Z",
                              slot_end_utc="2026-09-10T12:00:00Z")
    # 11:00 < existing 12:00 end: a genuine overlap, not adjacency.
    resp = api.create_mast_service_event(
        boat_id,
        {"service_kind": "STEP", "slot_start_utc": "2026-09-10T11:00:00Z",
         "slot_end_utc": "2026-09-10T16:00:00Z"},
        RIG,
    )
    validate_error(resp, ApiErrorId.ERR_MAST_SLOT_OVERLAP)


# ---------------------------------------------------------------------------
# Corner: true overlap, FAIL-close gating, hold release
# ---------------------------------------------------------------------------

def test_mast_slot_true_overlap_rejected(api):
    """PRD §2.10: "Two events on the same boat conflict when the first event's
    slot start is earlier than the second event's slot end and the second event's
    slot start is earlier than the first event's slot end" and "An overlapping
    booking is rejected with `ERR_MAST_SLOT_OVERLAP` (HTTP 409)."

    Design: Corner/validations/mast_slot_true_overlap_rejected
    """
    customer = create_customer(full_name="C35")
    boat = create_boat(customer["id"], boat_name="B35", hull_length_m=10.0)
    create_mast_service_event(boat["id"], service_kind="UNSTEP",
                              slot_start_utc="2026-09-15T08:00:00Z",
                              slot_end_utc="2026-09-15T12:00:00Z")
    resp = api.create_mast_service_event(
        boat["id"],
        {"service_kind": "TUNE", "slot_start_utc": "2026-09-15T10:00:00Z",
         "slot_end_utc": "2026-09-15T14:00:00Z"},
        RIG,
    )
    validate_error(resp, ApiErrorId.ERR_MAST_SLOT_OVERLAP)


def test_close_fail_inspection_without_replacement_rejected(api):
    """PRD §3.6: "closing a `REPORTED` inspection whose verdict is `FAIL` is
    refused with `ERR_FAIL_NOT_SUPERSEDED` (HTTP 409) unless a replacement
    inspection with a non-`FAIL` verdict already exists in `REPORTED` status for
    the same boat and the same scope."

    Design: Corner/validations/close_fail_inspection_without_passing_replacement_rejected
    """
    ctx = setup_boat_with_reported_fail(mast_event=False, scope="STANDING")
    resp = api.close_inspection(ctx["boat"]["id"], ctx["inspection"]["id"], RIG)
    validate_error(resp, ApiErrorId.ERR_FAIL_NOT_SUPERSEDED)

    after = get_rigging_inspection(ctx["inspection"]["id"])
    assert after["inspection_status"] == "REPORTED", (
        f"refused close must leave the inspection REPORTED, got {after['inspection_status']}"
    )


def test_hold_releases_when_fail_closed_by_pass(api):
    """PRD §3.6: "closing a `REPORTED` inspection whose verdict is `FAIL` is
    refused with `ERR_FAIL_NOT_SUPERSEDED` (HTTP 409) unless a replacement
    inspection with a non-`FAIL` verdict already exists in `REPORTED` status for
    the same boat and the same scope. When the failed inspection is closed on the
    strength of that passing replacement, the hold releases: the boat's `status`
    may return to `ACTIVE`, and the boat's held mast service events return from
    `RIGGING_HOLD` to `BOOKED` automatically."

    Design: Corner/cross_cutting_layers/mast_event_hold_releases_to_booked_when_fail_closed_by_pass
    """
    ctx = setup_fail_closed_by_replacement(scope="STANDING")
    assert ctx["inspection"]["inspection_status"] == "CLOSED", (
        f"passing replacement must allow the close, got {ctx['inspection']['inspection_status']}"
    )
    event = get_mast_service_event(ctx["mast_event"]["id"])
    assert event["event_status"] == "BOOKED", (
        f"held event must return to BOOKED automatically, got {event['event_status']}"
    )
