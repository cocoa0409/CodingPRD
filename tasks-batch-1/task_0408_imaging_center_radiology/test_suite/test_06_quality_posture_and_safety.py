"""Center posture / quality governance: cross-entity state dependencies, the
repeat/reject-rate cascade into QUALITY_HOLD that freezes acquisition, rate and
SLA boundary precision, validation-priority conflicts, and the unacknowledged
SLA breach on clock advance.

Translates Difficulty/cross_entity_state_dependency, Difficulty/transitive_cascade
(reject), Difficulty/boundary_precision_check, Difficulty/priority_pair_validation_conflict,
and Corner/calculations (rate-below-threshold, unacked-breach).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_screening_payload, finalize_series_payload, create_series_payload,
    create_exam_payload,
    TEST_USERS, make_nurse_headers, make_technologist_headers, make_radiologist_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["center_admin_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


# ─── Difficulty: cross-entity state dependency ────────────────────────

def test_clear_screening_blocked_when_screening_blocked(api):
    """PRD §3.3: "When the order's modality requires contrast screening, the
    order must have a `ContrastScreening` child whose `outcome` is `CLEARED`, or
    the clearance is rejected with `ERR_SCREENING_NOT_CLEARED`".
    PRD §3.3: "If the modality is `MRI` and the patient has an unsafe metal
    implant, the screening is `BLOCKED` with reason `METAL_IMPLANT`."

    Design: Difficulty/cross_entity_state_dependency/clear_screening_requires_screening_cleared
    """
    center = fx.create_center(name="C")
    mri = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                             base_rvu=2.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["MRI"])
    nh = make_nurse_headers(nurse["id"])
    order = fx.create_order(center["id"], mri["id"], requires_contrast=False)
    fx.advance_order_to_benefit_checked(order["id"])
    scr = validate_success(api.create_screening(order["id"],
            create_screening_payload(egfr_value=90, has_contrast_allergy=False,
                                     is_pregnant=False, metal_implant_unsafe=True), nh), 201)
    evaluated = validate_success(api.evaluate_screening(scr["id"], nh), 200)
    assert evaluated["outcome"] == "BLOCKED"
    assert evaluated["blocking_reason"] == "METAL_IMPLANT"
    res = api.clear_screening(order["id"], nh)
    validate_error(res, "ERR_SCREENING_NOT_CLEARED", 409)


def test_clear_screening_succeeds_once_screening_cleared(api):
    """Second translation of the order->screening cross-entity dependency,
    exercising the complementary (dependency-satisfied) side: once the child
    screening is CLEARED, the order's BENEFIT_CHECKED -> SCREEN_CLEARED advance
    succeeds.

    PRD §3.3: "When the order's modality requires contrast screening, the order
    must have a `ContrastScreening` child whose `outcome` is `CLEARED`, or the
    clearance is rejected with `ERR_SCREENING_NOT_CLEARED`".
    PRD §3.3: "With benefit checked, a `Nurse` clears the order for scheduling,
    advancing it from `BENEFIT_CHECKED` to `SCREEN_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/clear_screening_requires_screening_cleared
    """
    center = fx.create_center(name="C")
    mri = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                             base_rvu=2.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["MRI"])
    nh = make_nurse_headers(nurse["id"])
    order = fx.create_order(center["id"], mri["id"], requires_contrast=False)
    fx.advance_order_to_benefit_checked(order["id"])
    scr = validate_success(api.create_screening(order["id"],
            create_screening_payload(egfr_value=90, has_contrast_allergy=False,
                                     is_pregnant=False, metal_implant_unsafe=False), nh), 201)
    cleared_scr = validate_success(api.evaluate_screening(scr["id"], nh), 200)
    assert cleared_scr["outcome"] == "CLEARED"
    advanced = validate_success(api.clear_screening(order["id"], nh), 200)
    assert advanced["status"] == "SCREEN_CLEARED"


def test_start_acquisition_blocked_when_center_quality_hold(api):
    """Second translation of the exam->center posture dependency, using a
    metric-driven QUALITY_HOLD rather than an admin lock.

    PRD §3.5: "the center's `posture` must not be `QUALITY_HOLD`, or the start
    is rejected with `ERR_CENTER_QUALITY_HOLD`."
    PRD §2.8: "Otherwise: if the center's `repeat_reject_rate_pct` is at or
    above its `repeat_rate_threshold_pct`, or if any `CriticalResult` belonging
    to the center currently has `sla_breached` equal to true, the posture is
    `QUALITY_HOLD`."

    Exam1 is driven to a finalized REPEATED series (rate 100.0 >= threshold 8.0),
    flipping posture to QUALITY_HOLD; a second checked-in exam's start is blocked.

    Design: Difficulty/cross_entity_state_dependency/start_acquisition_depends_on_center_posture
    """
    center = fx.create_center(name="C", repeat_rate_threshold_pct=8.0)
    fx.set_clock(center["id"], "2026-06-01T09:00:00Z")
    xr = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                            base_rvu=1.0, requires_prior_auth=False)
    room1 = fx.create_room(center["id"], xr["id"], name="XR-1")
    room2 = fx.create_room(center["id"], xr["id"], name="XR-2")
    tech = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": xr["id"], "modality": xr,
            "room_id": room1["id"], "tech_id": tech["id"], "nurse_id": nurse["id"], "rad_id": None}
    th = make_technologist_headers(tech["id"])

    o1, o1v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam1 = fx.schedule_exam(topo, o1, o1v, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z",
                             room_id=room1["id"], technologist_id=tech["id"])
    validate_success(api.check_in(exam1["id"], th), 200)
    validate_success(api.start_acquisition(exam1["id"], th), 200)
    fx.finalize_n_series(exam1["id"], tech["id"], n_accepted=0, n_repeated=1)

    # tech already holds exam1 at 09:00-09:30, so the second exam to block must
    # use a distinct technologist (no tech double-booking) on a non-overlapping
    # window; the QUALITY_HOLD gate on start-acquisition is what we exercise.
    tech2 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T2", credentialed_modalities=["XRAY"])
    o3, o3v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam3 = fx.schedule_exam(topo, o3, o3v, "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z",
                             room_id=room2["id"], technologist_id=tech2["id"])
    fx.set_clock(center["id"], "2026-06-01T10:00:00Z")
    th2 = make_technologist_headers(tech2["id"])
    validate_success(api.check_in(exam3["id"], th2), 200)
    center_after = validate_success(api.get_center(center["id"], ADMIN), 200)
    assert center_after["posture"] == "QUALITY_HOLD"
    res = api.start_acquisition(exam3["id"], th2)
    validate_error(res, "ERR_CENTER_QUALITY_HOLD", 409)


# ─── Difficulty: depth-3 cascade reject -> rate -> posture -> freeze ──

def test_reject_series_rate_posture_blocks_acquisition(api):
    """PRD §3.5: "when the outcome is `REPEATED` or `REJECTED`, the center's
    `total_repeat_reject_series` also increases by one. The
    `repeat_reject_rate_pct` is then recomputed as 100 multiplied by
    `total_repeat_reject_series` divided by `total_acquired_series`, rounded
    half-up to 2 decimal places".
    PRD §2.8: "Otherwise: if the center's `repeat_reject_rate_pct` is at or
    above its `repeat_rate_threshold_pct`, or if any `CriticalResult` belonging
    to the center currently has `sla_breached` equal to true, the posture is
    `QUALITY_HOLD`."
    PRD §3.5: "the center's `posture` must not be `QUALITY_HOLD`, or the start
    is rejected with `ERR_CENTER_QUALITY_HOLD`."

    11 ACCEPTED + 1 REPEATED on exam1 => 12 finalized, 1 rr => 8.33% >= 8.0;
    a second checked-in exam's start-acquisition is then blocked center-wide.

    Design: Difficulty/transitive_cascade/reject_series_rate_posture_blocks_acquisition_depth3
    """
    center = fx.create_center(name="C", repeat_rate_threshold_pct=8.0)
    fx.set_clock(center["id"], "2026-06-01T09:00:00Z")
    xr = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                            base_rvu=1.0, requires_prior_auth=False)
    room1 = fx.create_room(center["id"], xr["id"], name="XR-1")
    room2 = fx.create_room(center["id"], xr["id"], name="XR-2")
    tech = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": xr["id"], "modality": xr,
            "room_id": room1["id"], "tech_id": tech["id"], "nurse_id": nurse["id"], "rad_id": None}
    th = make_technologist_headers(tech["id"])

    # Exam 1: bring to ACQUIRING, finalize 11 ACCEPTED, hold 1 CAPTURING for trigger.
    o1, o1v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam1 = fx.schedule_exam(topo, o1, o1v, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z",
                             room_id=room1["id"], technologist_id=tech["id"])
    validate_success(api.check_in(exam1["id"], th), 200)
    validate_success(api.start_acquisition(exam1["id"], th), 200)
    fx.finalize_n_series(exam1["id"], tech["id"], n_accepted=11)
    rr_series = validate_success(api.create_series(exam1["id"], create_series_payload("RR"), th), 201)

    # Exam 2: a second order booked + checked-in in room2 (after 10:00), ready to start.
    o2, o2v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam2 = fx.schedule_exam(topo, o2, o2v, "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z",
                             room_id=room2["id"], technologist_id=tech["id"])
    fx.set_clock(center["id"], "2026-06-01T10:00:00Z")
    validate_success(api.check_in(exam2["id"], th), 200)

    # Trigger: finalize the 12th series REPEATED -> rate 8.33 -> QUALITY_HOLD.
    validate_success(api.finalize_series(rr_series["id"],
                     finalize_series_payload("REPEATED", reject_reason="MOTION"), th), 200)
    center_after = validate_success(api.get_center(center["id"], ADMIN), 200)
    assert center_after["repeat_reject_rate_pct"] == 8.33
    assert center_after["posture"] == "QUALITY_HOLD"

    res = api.start_acquisition(exam2["id"], th)
    validate_error(res, "ERR_CENTER_QUALITY_HOLD", 409)


def test_reject_series_drives_posture_quality_hold(api):
    """Second translation isolating the rate->posture hop of the cascade.

    PRD §3.5: "Immediately after the counters and rate update, the center's
    `posture` is re-derived per §2.8; if the recomputed rate has reached the
    threshold, the resulting `QUALITY_HOLD` is what blocks subsequent
    start-acquisition attempts across the center."

    Design: Difficulty/transitive_cascade/reject_series_rate_posture_blocks_acquisition_depth3
    """
    acq = fx.setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=8.0)
    # 11 ACCEPTED then 1 REPEATED -> 12 finalized, 1 rr -> 8.33% >= 8.0.
    fx.finalize_n_series(acq["exam_id"], acq["topo"]["tech_id"], n_accepted=11, n_repeated=1)
    center = validate_success(api.get_center(acq["topo"]["center_id"], ADMIN), 200)
    assert center["repeat_reject_rate_pct"] == 8.33
    assert center["posture"] == "QUALITY_HOLD"


# ─── Difficulty: boundary precision (rate exactly at threshold) ───────

def test_repeat_rate_exactly_at_threshold_triggers_hold(api):
    """PRD §2.8: "Otherwise: if the center's `repeat_reject_rate_pct` is at or
    above its `repeat_rate_threshold_pct`, or if any `CriticalResult` belonging
    to the center currently has `sla_breached` equal to true, the posture is
    `QUALITY_HOLD`."

    2 of 25 finalized = exactly 8.0% == threshold => QUALITY_HOLD (at-or-above).

    Design: Difficulty/boundary_precision_check/repeat_rate_exactly_at_threshold_triggers_hold
    """
    acq = fx.setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=8.0)
    # 23 ACCEPTED + 2 REJECTED => 25 finalized, 2 rr => 8.0%.
    fx.finalize_n_series(acq["exam_id"], acq["topo"]["tech_id"],
                         n_accepted=23, n_rejected=2, reject_reason="EXPOSURE")
    center = validate_success(api.get_center(acq["topo"]["center_id"], ADMIN), 200)
    assert center["repeat_reject_rate_pct"] == 8.0
    assert center["posture"] == "QUALITY_HOLD"


def test_repeat_rate_at_threshold_alternate_counts_triggers_hold(api):
    """Second translation of the at-threshold boundary using a different count
    tuple (4 of 50 = exactly 8.0%), confirming the at-or-above rule is on the
    rate value, not a specific count.

    PRD §2.8: "Otherwise: if the center's `repeat_reject_rate_pct` is at or
    above its `repeat_rate_threshold_pct`, or if any `CriticalResult` belonging
    to the center currently has `sla_breached` equal to true, the posture is
    `QUALITY_HOLD`."

    Design: Difficulty/boundary_precision_check/repeat_rate_exactly_at_threshold_triggers_hold
    """
    acq = fx.setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=8.0)
    # 46 ACCEPTED + 4 REPEATED => 50 finalized, 4 rr => 8.0%.
    fx.finalize_n_series(acq["exam_id"], acq["topo"]["tech_id"],
                         n_accepted=46, n_repeated=4, reject_reason="ARTIFACT")
    center = validate_success(api.get_center(acq["topo"]["center_id"], ADMIN), 200)
    assert center["repeat_reject_rate_pct"] == 8.0
    assert center["posture"] == "QUALITY_HOLD"


def test_repeat_rate_below_threshold_stays_open(api):
    """PRD §2.8: "Otherwise: if the center's `repeat_reject_rate_pct` is at or
    above its `repeat_rate_threshold_pct`, or if any `CriticalResult` belonging
    to the center currently has `sla_breached` equal to true, the posture is
    `QUALITY_HOLD`. If neither of those holds, the posture is `OPEN`."

    1 of 13 finalized = 7.69% < 8.0 => posture stays OPEN.

    Design: Corner/calculations/repeat_reject_rate_below_threshold_stays_open
    """
    acq = fx.setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=8.0)
    fx.finalize_n_series(acq["exam_id"], acq["topo"]["tech_id"],
                         n_accepted=12, n_repeated=1, reject_reason="POSITIONING")
    center = validate_success(api.get_center(acq["topo"]["center_id"], ADMIN), 200)
    assert center["repeat_reject_rate_pct"] == 7.69
    assert center["posture"] == "OPEN"


# ─── Difficulty: boundary precision (critical ack exactly at SLA) ─────

def test_critical_ack_exactly_at_sla_not_breached(api):
    """PRD §3.7: "`sla_breached` is set true when `minutes_to_ack` is strictly
    greater than the center's `critical_ack_sla_minutes`."
    PRD §3.7: "the boundary is exclusive — elapsed time exactly equal to the SLA
    window is not a breach."

    Raised 09:00, acked 10:00 => minutes_to_ack 60.0 == sla 60 => not breached.

    Design: Difficulty/boundary_precision_check/critical_ack_exactly_at_sla_not_breached
    """
    setup = fx.setup_critical_result(modality_type="XRAY", critical_ack_sla_minutes=60,
                                     start="2026-06-01T08:30:00Z", end="2026-06-01T09:00:00Z",
                                     checkin_clock="2026-06-01T08:30:00Z",
                                     raised_clock="2026-06-01T09:00:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    fx.set_clock(setup["topo"]["center_id"], "2026-06-01T10:00:00Z")
    acked = validate_success(api.acknowledge_critical_result(setup["cr_id"], rh), 200)
    assert acked["minutes_to_ack"] == 60.0
    assert acked["sla_breached"] is False


def test_critical_ack_one_minute_over_sla_breached(api):
    """Second translation of the ack-time SLA boundary, exercising the X+1 side
    of the strict-`>` comparison.

    PRD §3.7: "`sla_breached` is set true when `minutes_to_ack` is strictly
    greater than the center's `critical_ack_sla_minutes`."

    Raised 09:00, acked 10:01 => minutes_to_ack 61.0 > sla 60 => breached.

    Design: Difficulty/boundary_precision_check/critical_ack_exactly_at_sla_not_breached
    """
    setup = fx.setup_critical_result(modality_type="XRAY", critical_ack_sla_minutes=60,
                                     start="2026-06-01T08:30:00Z", end="2026-06-01T09:00:00Z",
                                     checkin_clock="2026-06-01T08:30:00Z",
                                     raised_clock="2026-06-01T09:00:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    fx.set_clock(setup["topo"]["center_id"], "2026-06-01T10:01:00Z")
    acked = validate_success(api.acknowledge_critical_result(setup["cr_id"], rh), 200)
    assert acked["minutes_to_ack"] == 61.0
    assert acked["sla_breached"] is True


def test_critical_unacked_breach_on_clock_advance(api):
    """PRD §3.7: "While a result is still unacknowledged, its breach status is
    re-evaluated whenever the center clock advances: the elapsed minutes from
    `raised_at_utc` to the center's current `now_utc` are compared against
    `critical_ack_sla_minutes`, and `sla_breached` becomes true when that
    elapsed time is strictly greater than the SLA window."
    PRD §2.8: "if any `CriticalResult` belonging to the center currently has
    `sla_breached` equal to true, the posture is `QUALITY_HOLD`."

    Raised 09:00, sla 60; clock to 10:01 (61 min > 60) => breached, QUALITY_HOLD.

    Design: Corner/calculations/critical_unacked_breach_on_clock_advance
    """
    setup = fx.setup_critical_result(modality_type="XRAY", critical_ack_sla_minutes=60,
                                     start="2026-06-01T08:30:00Z", end="2026-06-01T09:00:00Z",
                                     checkin_clock="2026-06-01T08:30:00Z",
                                     raised_clock="2026-06-01T09:00:00Z",
                                     notified_party_role="RAPID_RESPONSE")
    fx.set_clock(setup["topo"]["center_id"], "2026-06-01T10:01:00Z")
    cr = validate_success(api.get_critical_result(setup["cr_id"],
                          make_radiologist_headers(setup["topo"]["rad_id"])), 200)
    assert cr["sla_breached"] is True
    center = validate_success(api.get_center(setup["topo"]["center_id"], ADMIN), 200)
    assert center["posture"] == "QUALITY_HOLD"


# ─── Difficulty: validation-priority conflicts ────────────────────────

def test_state_beats_fiscal_on_benefit_check(api):
    """PRD §3.9: "then the target resource being in the correct state for the
    requested transition (`ERR_INVALID_STATE`)".
    PRD §3.2: "It may only run while the order is `REQUESTED` (otherwise
    `ERR_INVALID_STATE`)."

    A CANCELLED prior-auth-required order with no AUTHORIZED auth: the state
    check (ERR_INVALID_STATE) is reached before the fiscal gate.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_benefit_check
    """
    center = fx.create_center(name="C")
    mri = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                             base_rvu=2.0, requires_prior_auth=True)
    order = fx.create_order(center["id"], mri["id"], requires_contrast=False)
    validate_success(api.cancel_order(order["id"], CLERK), 200)
    res = api.benefit_check(order["id"], {}, CLERK)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_fiscal_gate_fires_in_isolation_when_state_valid(api):
    """Second translation of the state-vs-fiscal pair, isolating the fiscal gate:
    on a correctly-stated (REQUESTED) prior-auth-required order with no
    AUTHORIZED authorization, the fiscal check is reached and fires.

    PRD §3.2: "When the order's modality has `requires_prior_auth` true, the
    order must have a `PriorAuthorization` child in `AUTHORIZED` status, or the
    benefit check is rejected with `ERR_PRIOR_AUTH_REQUIRED`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_benefit_check
    """
    center = fx.create_center(name="C")
    mri = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                             base_rvu=2.0, requires_prior_auth=True)
    order = fx.create_order(center["id"], mri["id"], requires_contrast=False)
    # Order is still REQUESTED (state precondition satisfied); only the fiscal
    # gate can fail here.
    res = api.benefit_check(order["id"], {}, CLERK)
    validate_error(res, "ERR_PRIOR_AUTH_REQUIRED", 402)


def test_safety_screening_beats_temporal_interval(api):
    """PRD §3.9: "then the target resource being in the correct state for the
    requested transition (`ERR_INVALID_STATE`)".
    PRD §3.3: "When the order's modality requires contrast screening, the order
    must have a `ContrastScreening` child whose `outcome` is `CLEARED`, or the
    clearance is rejected with `ERR_SCREENING_NOT_CLEARED`".

    clear-screening on a BENEFIT_CHECKED MRI order with a still-PENDING screening
    is rejected at the screening gate before any later scheduling/interval check.

    Design: Difficulty/priority_pair_validation_conflict/safety_screening_beats_temporal_interval
    """
    center = fx.create_center(name="C")
    mri = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                             base_rvu=2.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["MRI"])
    nh = make_nurse_headers(nurse["id"])
    order = fx.create_order(center["id"], mri["id"], requires_contrast=True)
    fx.advance_order_to_benefit_checked(order["id"])
    # Screening created but NOT evaluated (still PENDING).
    validate_success(api.create_screening(order["id"],
            create_screening_payload(egfr_value=90), nh), 201)
    res = api.clear_screening(order["id"], nh)
    validate_error(res, "ERR_SCREENING_NOT_CLEARED", 409)


def test_temporal_interval_check_reachable_once_screening_satisfied(api):
    """Second translation of the safety-vs-temporal pair, isolating the temporal
    check: once screening is satisfied (XRAY needs none, so the order reaches
    SCREEN_CLEARED), the interval-validity check is reachable and fires on a bad
    interval.

    PRD §3.4: "The interval itself must be valid — `scheduled_end_utc` strictly
    after `scheduled_start_utc`, otherwise `ERR_INVALID_INTERVAL`."

    Design: Difficulty/priority_pair_validation_conflict/safety_screening_beats_temporal_interval
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T08:00:00Z")
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    res = api.create_exam(order_id,
            create_exam_payload(room_id=topo["room_id"], technologist_id=topo["tech_id"],
                                scheduled_start_utc="2026-06-01T09:30:00Z",
                                scheduled_end_utc="2026-06-01T09:00:00Z",
                                expected_imaging_order_version=ov), CLERK)
    validate_error(res, "ERR_INVALID_INTERVAL", 422)
