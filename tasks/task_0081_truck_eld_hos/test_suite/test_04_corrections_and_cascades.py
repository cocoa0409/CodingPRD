"""Corrections, erroneous-record marking, and recompute cascades (PRD §2.5, §3.3, §3.4, §3.6).

Covers difficulty rules non_linear_state_machine (parallel dimensions),
transitive_cascade, compensating_invariant, plus corner cascading_side_effects.
"""
from test_helpers import fixtures, constants


# =====================================================================
# Difficulty / non_linear_state_machine — parallel record + compliance dimensions
# =====================================================================
def test_correction_supersedes_target_and_flips_compliance_independently(api):
    """PRD §3.6: "On success the superseded event's record_status transitions
    ACTIVE → INACTIVE_CHANGED, its version increments, and the clocks and violations are
    recomputed over the corrected stream."
    PRD §3.6: "Because the surviving set has changed, a neighbouring event's
    compliance_disposition may flip in either direction between COMPLIANT and VIOLATING."

    Design: Difficulty/non_linear_state_machine/dutystatusevent_parallel_record_and_compliance_dimensions
    """
    setup = fixtures.setup_bound_driver()
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    drive_evt = stream.append("DRIVING", "2026-06-01T06:30:00Z")
    close_evt = stream.append("OFF_DUTY", "2026-06-01T17:25:00Z")  # 655 < 660, drive COMPLIANT

    # Correction: supersede the closing event, pushing the engine-off later to 17:32.
    # The correcting event_time must itself be strictly greater than the latest
    # surviving event (PRD §3.6 -> §3.3); 17:32 > 17:25 satisfies that precondition.
    # The surviving DRIVING interval now spans 06:30 -> 17:32 = 662 (> 660), so the
    # neighbouring event's compliance_disposition flips COMPLIANT -> VIOLATING.
    stream.append("OFF_DUTY", "2026-06-01T17:32:00Z",
                  edited_from_event_id=close_evt["id"], annotation="Corrected end time; engine off later.")

    superseded = fixtures.get_event(close_evt["id"])
    surviving = fixtures.get_event(drive_evt["id"])
    assert superseded["record_status"] == "INACTIVE_CHANGED", "record dimension advanced on target"
    assert surviving["record_status"] == "ACTIVE", "surviving event's record dimension unchanged"
    assert surviving["compliance_disposition"] == "VIOLATING", (
        "compliance dimension flipped: new surviving DRIVING interval 662 > 660"
    )


def test_correction_auto_dismisses_violation_made_compliant(api):
    """PRD §3.6: "If a previously OPEN violation's trigger interval no longer crosses its
    limit after the correction, that violation is auto-transitioned OPEN → DISMISSED with its
    resolution_note set to the system note "auto-dismissed: corrected"."

    Design: Difficulty/non_linear_state_machine/dutystatusevent_parallel_record_and_compliance_dimensions
    """
    setup = fixtures.setup_driving_11h_violation()
    d_id = setup["driver_id"]
    drive_evt = setup["drive_event"]
    violation = setup["violation"]
    stream = setup["stream"]

    # Supersede the DRIVING event that triggered the DRIVING_11H violation. The
    # correcting event_time (17:32) is strictly greater than the latest surviving
    # event (the 17:31 close), satisfying the §3.6 -> §3.3 ordering precondition.
    # With the trigger event now INACTIVE_CHANGED there is no surviving DRIVING
    # interval, so the trigger interval no longer crosses 660 and the OPEN
    # violation auto-transitions to DISMISSED (PRD §3.6).
    stream.append("OFF_DUTY", "2026-06-01T17:32:00Z",
                  edited_from_event_id=drive_evt["id"], annotation="Corrected: drive segment removed.")

    after = fixtures.get_violation(violation["id"])
    assert after["status"] == "DISMISSED"
    assert after["resolution_note"] == constants.NOTE_AUTO_DISMISSED_CORRECTED


# =====================================================================
# Difficulty / transitive_cascade — append cascades event -> violation -> certified log
# =====================================================================
def test_append_cascade_closes_interval_recertifies_log_and_opens_violation(api):
    """PRD §3.3: "A plain append that succeeds closes the previously open event by setting
    that prior event's duration_minutes to the whole-minute gap between the prior event's
    event_time and this new event's event_time."
    PRD §2.5: "When recomputation changes a day's totals after the driver had already
    certified that day's log, the log's certification_status is forced from CERTIFIED back to
    RECERTIFY_REQUIRED and its certified_at is cleared to null".
    PRD §3.5: "A DRIVING_11H violation arises when the driving clock exceeds 660 minutes
    (11 hours)."

    Design: Difficulty/transitive_cascade/append_cascades_event_to_violation_to_certified_log
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T07:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    drive_evt = stream.append("DRIVING", "2026-06-01T06:30:00Z")  # open event, compliant so far
    log = fixtures.open_daily_log(d_id, "2026-06-01")
    certified = fixtures.certify_daily_log(d_id, log["id"])
    assert certified["certification_status"] == "CERTIFIED"

    fixtures.pin_clock("2026-06-01T20:00:00Z")
    stream.append("OFF_DUTY", "2026-06-01T17:31:00Z")  # closes drive at 661 min

    # Link 1
    assert fixtures.get_event(drive_evt["id"])["duration_minutes"] == 661
    # Link 2
    after_log = fixtures.get_daily_log(log["id"])
    assert after_log["certification_status"] == "RECERTIFY_REQUIRED"
    assert after_log["certified_at"] is None
    # Link 3
    violation = fixtures.find_one_violation(d_id, violation_type="DRIVING_11H", status="OPEN")
    assert violation["overage_minutes"] == 1


def test_append_cascade_recertify_link_isolated(api):
    """PRD §2.5: "When recomputation changes a day's totals after the driver had already
    certified that day's log, the log's certification_status is forced from CERTIFIED back to
    RECERTIFY_REQUIRED and its certified_at is cleared to null".

    Design: Difficulty/transitive_cascade/append_cascades_event_to_violation_to_certified_log
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T07:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T06:30:00Z")
    log = fixtures.open_daily_log(d_id, "2026-06-01")
    fixtures.certify_daily_log(d_id, log["id"])

    fixtures.pin_clock("2026-06-01T20:00:00Z")
    stream.append("OFF_DUTY", "2026-06-01T17:31:00Z")

    after_log = fixtures.get_daily_log(log["id"])
    assert after_log["certification_status"] == "RECERTIFY_REQUIRED"
    assert after_log["certified_at"] is None


# =====================================================================
# Difficulty / transitive_cascade — mark-error cascades recompute -> violation dismiss
# =====================================================================
def test_markerror_removes_interval_and_auto_dismisses_violation(api):
    """PRD §3.6: "Marking transitions the event ACTIVE → INACTIVE_ERROR, which removes it
    from every clock and violation computation, increments its version, and triggers the same
    recomputation and reconciliation of downstream daily-log totals, driver clocks, and
    affected violations."
    PRD §3.10: "when a correction or an extended-limit recompute makes a trigger interval
    compliant, an OPEN or ACKNOWLEDGED violation auto-transitions to DISMISSED and records the
    corresponding system resolution_note".

    Design: Difficulty/transitive_cascade/markerror_cascades_clock_recompute_to_violation_dismiss
    """
    setup = fixtures.setup_driving_11h_violation()
    close_evt = setup["close_event"]
    violation = setup["violation"]

    fixtures.mark_error(close_evt["id"])

    after_evt = fixtures.get_event(close_evt["id"])
    assert after_evt["record_status"] == "INACTIVE_ERROR"
    after_v = fixtures.get_violation(violation["id"])
    assert after_v["status"] == "DISMISSED"
    assert after_v["resolution_note"] == constants.NOTE_AUTO_DISMISSED_CORRECTED


def test_markerror_sets_record_status_inactive_error(api):
    """PRD §3.6: "Marking transitions the event ACTIVE → INACTIVE_ERROR, which removes it
    from every clock and violation computation".

    Design: Difficulty/transitive_cascade/markerror_cascades_clock_recompute_to_violation_dismiss
    """
    setup = fixtures.setup_driving_11h_violation()
    close_evt = setup["close_event"]
    fixtures.mark_error(close_evt["id"])
    assert fixtures.get_event(close_evt["id"])["record_status"] == "INACTIVE_ERROR"


# =====================================================================
# Difficulty / compensating_invariant
# =====================================================================
def test_markerror_restores_cycle_on_duty_minutes(api):
    """PRD §3.6: "Marking transitions the event ACTIVE → INACTIVE_ERROR, which removes it
    from every clock and violation computation".
    PRD §3.4: "A driver's cycle_on_duty_minutes is the sum of DRIVING-with-NONE, YARD_MOVE,
    and ON_DUTY_NOT_DRIVING minutes over the rolling cycle window".

    Design: Difficulty/compensating_invariant/markerror_restores_cycle_on_duty_minutes_invariant
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    onduty_evt = stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")
    stream.append("DRIVING", "2026-06-01T06:30:00Z")  # closes ON_DUTY at 30 min

    mid = fixtures.get_driver(d_id)
    assert mid["cycle_on_duty_minutes"] == 30

    fixtures.mark_error(onduty_evt["id"])
    after = fixtures.get_driver(d_id)
    assert after["cycle_on_duty_minutes"] == 0, (
        f"removing the ON_DUTY interval restores cycle to pre-append 0, got {after['cycle_on_duty_minutes']}"
    )


def test_markerror_excludes_event_record_from_record_status(api):
    """PRD §3.6: "Marking transitions the event ACTIVE → INACTIVE_ERROR, which removes it from
    every clock and violation computation".
    PRD §3.4: "The recomputation considers only ACTIVE events for that driver; events in
    INACTIVE_CHANGED or INACTIVE_ERROR are excluded from every clock and every violation
    calculation entirely."

    Design: Difficulty/compensating_invariant/markerror_restores_cycle_on_duty_minutes_invariant
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    onduty_evt = stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")
    stream.append("DRIVING", "2026-06-01T06:30:00Z")  # 30 on-duty minutes counted
    assert fixtures.get_driver(d_id)["cycle_on_duty_minutes"] == 30

    fixtures.mark_error(onduty_evt["id"])
    assert fixtures.get_event(onduty_evt["id"])["record_status"] == "INACTIVE_ERROR"
    assert fixtures.get_driver(d_id)["cycle_on_duty_minutes"] == 0


# =====================================================================
# Corner / cross_cutting_complexity_layers — cascade reconciles daily totals
# =====================================================================
def test_markerror_reconciles_daily_total_driving_minutes_downward(api):
    """PRD §3.6: "Marking transitions the event ACTIVE → INACTIVE_ERROR, which removes it
    from every clock and violation computation, increments its version, and triggers the same
    recomputation and reconciliation of downstream daily-log totals".
    PRD §3.8: "total_driving_minutes, the sum of duration_minutes over ACTIVE DRIVING events
    with category NONE whose event_time falls in the day".

    Design: Corner/cross_cutting_complexity_layers/cascade_recompute_reconciles_daily_totals_after_markerror
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T06:30:00Z")
    close_evt = stream.append("OFF_DUTY", "2026-06-01T08:30:00Z")  # 120 driving min closed
    log = fixtures.open_daily_log(d_id, "2026-06-01")
    assert log["total_driving_minutes"] == 120

    fixtures.mark_error(close_evt["id"])  # DRIVING event becomes open again
    after = fixtures.get_daily_log(log["id"])
    assert after["total_driving_minutes"] == 0, (
        f"DRIVING event now open, no closed interval -> 0, got {after['total_driving_minutes']}"
    )
