"""Transitive cascades (veto->denied->released->venue freed; debrief->closed->
reconciled), dual-variant calculations (cost-recovery estimate/actual; deposit
forfeit/refund), conservation invariants, cancel-refund, and finalize lockdown.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, assert_deposit_conserved,
    ApiErrorId,
    make_applicant_headers, make_reviewer_headers, officer_headers,
    get_venue_version,
    setup_under_review, setup_issued, setup_debrief_open, setup_conditionally_approved,
    log_all_actuals, pay_deposit, STAFFING,
)
import test_helpers.factories as F


# ==========================================================================
# Transitive cascade: veto -> denied -> released -> venue freed (queue A)
# ==========================================================================
def test_veto_denies_releases_frees_venue_depth3(api):
    """PRD §3.7: "When any department vetoes, the application moves UNDER_REVIEW →
    DENIED: every PLANNED route segment is moved to RELEASED and its corridor closure
    reservation is freed, the reserved venue occupancy is released (which increments
    the venue's version by 1), and every non-terminal PermitCondition is moved to
    WAIVED."

    Design: Difficulty/transitive_cascade/veto_denies_releases_frees_venue_depth3
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="RALLY",
                             occupy_start="2026-06-07T10:00:00Z",
                             occupy_end="2026-06-07T14:00:00Z")
    app_id = ctx["application"]["id"]
    segs = validate_success(api.list_route_segments(app_id, officer_headers()))
    seg_id = segs[0]["id"]
    venue_v_after_submit = get_venue_version(ctx["venue"]["id"])
    api.veto_review(app_id, ctx["reviews"]["EMS"], {"note": "No EMS staging space"},
                    make_reviewer_headers("EMS"))
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "DENIED"  # link2
    seg = validate_success(api.get_route_segment(app_id, seg_id, officer_headers()))
    assert seg["status"] == "RELEASED"  # link3
    venue_v_after_veto = get_venue_version(ctx["venue"]["id"])
    assert venue_v_after_veto == venue_v_after_submit + 1  # link3 frees reservation


def test_veto_denial_waives_proposed_conditions_depth3(api):
    """PRD §3.7: "When any department vetoes, the application moves UNDER_REVIEW →
    DENIED: every PLANNED route segment is moved to RELEASED ..., and every
    non-terminal PermitCondition is moved to WAIVED." PRD §3.5: "A condition that is
    still PROPOSED when the application is denied or cancelled is moved to WAIVED."
    (Second link-3 effect of the same veto->DENIED cascade: PROPOSED conditions.)

    Design: Difficulty/transitive_cascade/veto_denies_releases_frees_venue_depth3
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="RALLY",
                             occupy_start="2026-08-07T10:00:00Z",
                             occupy_end="2026-08-07T14:00:00Z")
    app_id = ctx["application"]["id"]
    reviews = ctx["reviews"]
    cond = validate_success(api.add_condition(app_id, reviews["POLICE"],
                                              {"text": "barricades", "mandatory": True},
                                              make_reviewer_headers("POLICE")),
                            expected_status=201)
    api.veto_review(app_id, reviews["EMS"], {"note": "No EMS staging"},
                    make_reviewer_headers("EMS"))
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "DENIED"
    cond_now = validate_success(api.get_condition_global(cond["id"], officer_headers()))
    assert cond_now["status"] == "WAIVED"


# ==========================================================================
# Transitive cascade: debrief finalize -> closed + reconciled (queue A)
# ==========================================================================
def test_debrief_finalize_closes_reconciles_depth2(api):
    """PRD §3.8: "the forfeited_amount is the lesser of the deposit's amount and the
    debrief's cleanup_charges, rounded to two decimals, and the refunded_amount is
    the deposit's amount minus the forfeited_amount ... cleanup charges beyond the
    deposit are never clawed back from the applicant. If cleanup_charges exceed 0 the
    deposit moves to FORFEITED_PARTIAL". PRD §3.8: "the application transitions ISSUED
    → CLOSED, a terminal state."

    Design: Difficulty/transitive_cascade/debrief_finalize_closes_reconciles_depth2
    """
    ctx = setup_debrief_open(cleanup_charges=700, actual_attendance=3000,
                             incident_count=2, deposit_amount=500,
                             attendance=3000, max_capacity=5000, buffer=60,
                             venue_type="PLAZA", event_kind="FESTIVAL",
                             occupy_start="2026-06-08T10:00:00Z",
                             occupy_end="2026-06-08T14:00:00Z")
    app_id = ctx["application"]["id"]
    debrief_id = ctx["debrief"]["id"]
    deposit_id = ctx["deposit"]["id"]
    api.finalize_debrief(app_id, debrief_id, officer_headers())
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "CLOSED"  # link2
    deposit = validate_success(api.get_deposit_global(deposit_id, officer_headers()))
    assert deposit["status"] == "FORFEITED_PARTIAL"
    assert deposit["forfeited_amount"] == 500.00  # capped at deposit amount
    assert deposit["refunded_amount"] == 0.00


def test_debrief_finalize_releases_active_segments_and_settles_invoice_depth2(api):
    """PRD §3.8: "every ACTIVE route segment is moved to RELEASED, freeing its corridor
    reservation and incrementing the venue's version by 1. Finally, the debrief moves
    OPEN → FINALIZED and the application transitions ISSUED → CLOSED". PRD §3.8: "the
    invoice moves to SETTLED." (Second angle on the debrief-finalize link-2 cascade:
    segment release + invoice settlement rather than the deposit branch.)

    Design: Difficulty/transitive_cascade/debrief_finalize_closes_reconciles_depth2
    """
    ctx = setup_debrief_open(cleanup_charges=0, actual_attendance=3000,
                             deposit_amount=500,
                             attendance=3000, max_capacity=5000, buffer=60,
                             venue_type="PLAZA", event_kind="FESTIVAL",
                             occupy_start="2026-08-08T10:00:00Z",
                             occupy_end="2026-08-08T14:00:00Z")
    app_id = ctx["application"]["id"]
    segs = validate_success(api.list_route_segments(app_id, officer_headers()))
    seg_id = segs[0]["id"]
    api.finalize_debrief(app_id, ctx["debrief"]["id"], officer_headers())
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "CLOSED"
    seg = validate_success(api.get_route_segment(app_id, seg_id, officer_headers()))
    assert seg["status"] == "RELEASED"
    inv = validate_success(api.list_invoices(app_id, officer_headers()))[0]
    assert inv["status"] == "SETTLED"


# ==========================================================================
# Dual-variant calc: cost-recovery estimate vs actual (queue A)
# ==========================================================================
def test_cost_recovery_estimate_vs_actual_diverge(api):
    """PRD §3.8: "it computes the staffing cost-recovery actual using the same method
    as the estimate but drawing each department's hours from actual_hours rather than
    planned_hours ... The invoice's cost_recovery_actual is set to this figure, its
    balance_due is trued up to the sum of fee_component and cost_recovery_actual".
    PRD §3.6: the estimate uses planned_hours ("planned_personnel multiplied by
    planned_hours multiplied by hourly_rate, rounded to cents").

    Design: Difficulty/dual_variant_calc/cost_recovery_estimate_vs_actual_diverge
    """
    ctx = setup_issued(attendance=3000, max_capacity=5000, buffer=60,
                       venue_type="PARK", event_kind="FESTIVAL",
                       occupy_start="2026-06-01T10:00:00Z",
                       occupy_end="2026-06-01T14:00:00Z",
                       set_clock_first=True)
    app_id = ctx["application"]["id"]
    reviews = ctx["reviews"]
    # Log actuals: POLICE 10 (was planned 8), others unchanged from planned
    log_all_actuals(app_id, reviews,
                    {"POLICE": 10, "FIRE": 6, "EMS": 8, "PUBLIC_WORKS": 4})
    debrief = validate_success(api.open_debrief(app_id,
                                                F.open_debrief_payload(3100, cleanup_charges=0,
                                                                       incident_count=0),
                                                officer_headers()), expected_status=201)
    api.finalize_debrief(app_id, debrief["id"], officer_headers())
    invoices = validate_success(api.list_invoices(app_id, officer_headers()))
    inv = invoices[0]
    # estimate: 1600+720+360+480=3160 *1.15 = 3634.00
    assert inv["cost_recovery_estimate"] == 3634.00
    # actual: POLICE 4*10*50=2000 => 2000+720+360+480=3560 *1.15 = 4094.00
    assert inv["cost_recovery_actual"] == 4094.00
    assert inv["cost_recovery_actual"] != inv["cost_recovery_estimate"]


def test_cost_recovery_actual_default_zero_hours_when_not_logged(api):
    """PRD §3.8: "A department that never logs actuals keeps its actual_hours at the
    default of 0." PRD §3.8: the actual "drawing each department's hours from
    actual_hours rather than planned_hours".

    Design: Difficulty/dual_variant_calc/cost_recovery_estimate_vs_actual_diverge
    """
    ctx = setup_issued(attendance=3000, max_capacity=5000, buffer=60,
                       venue_type="PARK", event_kind="FESTIVAL",
                       occupy_start="2026-06-01T10:00:00Z",
                       occupy_end="2026-06-01T14:00:00Z",
                       set_clock_first=True)
    app_id = ctx["application"]["id"]
    # Log actuals only for POLICE (4*10*50=2000); others stay at actual_hours 0
    log_all_actuals(app_id, ctx["reviews"], {"POLICE": 10})
    debrief = validate_success(api.open_debrief(app_id,
                                                F.open_debrief_payload(3000, cleanup_charges=0),
                                                officer_headers()), expected_status=201)
    api.finalize_debrief(app_id, debrief["id"], officer_headers())
    invoices = validate_success(api.list_invoices(app_id, officer_headers()))
    inv = invoices[0]
    # only POLICE contributes: 4*10*50=2000, others 0 -> 2000 *1.15 = 2300.00
    assert inv["cost_recovery_actual"] == 2300.00


# ==========================================================================
# Dual-variant calc: deposit partial forfeit vs full refund (queue A)
# ==========================================================================
def test_deposit_partial_forfeit_on_finalize(api):
    """PRD §3.8: "the forfeited_amount is the lesser of the deposit's amount and the
    debrief's cleanup_charges, rounded to two decimals, and the refunded_amount is
    the deposit's amount minus the forfeited_amount, rounded to two decimals ... If
    cleanup_charges exceed 0 the deposit moves to FORFEITED_PARTIAL".

    Design: Difficulty/dual_variant_calc/deposit_partial_forfeit_vs_full_refund
    """
    ctx = setup_debrief_open(cleanup_charges=120, actual_attendance=2900,
                             incident_count=1, deposit_amount=500,
                             attendance=3000, max_capacity=5000, buffer=60,
                             venue_type="PLAZA", event_kind="PARADE",
                             occupy_start="2026-06-02T10:00:00Z",
                             occupy_end="2026-06-02T14:00:00Z")
    app_id = ctx["application"]["id"]
    deposit_id = ctx["deposit"]["id"]
    api.finalize_debrief(app_id, ctx["debrief"]["id"], officer_headers())
    deposit = validate_success(api.get_deposit_global(deposit_id, officer_headers()))
    assert deposit["status"] == "FORFEITED_PARTIAL"
    assert deposit["forfeited_amount"] == 120.00
    assert deposit["refunded_amount"] == 380.00


def test_deposit_full_refund_on_cancel_from_conditionally_approved(api):
    """PRD §3.7: "Cancelling from CONDITIONALLY_APPROVED likewise releases all PLANNED
    segments and increments the venue's version by 1, and additionally refunds any
    HELD deposit in full — the deposit moves to REFUNDED with refunded_amount set to
    its amount and forfeited_amount set to 0."

    Design: Difficulty/dual_variant_calc/deposit_partial_forfeit_vs_full_refund
    """
    ctx = setup_conditionally_approved(attendance=3000, max_capacity=6000, buffer=60,
                                       event_kind="FESTIVAL",
                                       occupy_start="2026-07-19T10:00:00Z",
                                       occupy_end="2026-07-19T14:00:00Z",
                                       set_clock_first=True)
    app_id = ctx["application"]["id"]
    applicant_id = ctx["applicant"]["id"]
    deposit = pay_deposit(app_id, applicant_id, 500)
    api.cancel_application(app_id, make_applicant_headers(applicant_id))
    dep = validate_success(api.get_deposit_global(deposit["id"], officer_headers()))
    assert dep["status"] == "REFUNDED"
    assert dep["refunded_amount"] == 500.00
    assert dep["forfeited_amount"] == 0.00


# ==========================================================================
# Cancel from conditionally-approved full cascade (queue B)
# ==========================================================================
def test_cancel_from_conditionally_approved_refunds_deposit_full(api):
    """PRD §3.7: "Cancelling from CONDITIONALLY_APPROVED likewise releases all PLANNED
    segments and increments the venue's version by 1, and additionally refunds any
    HELD deposit in full — the deposit moves to REFUNDED with refunded_amount set to
    its amount and forfeited_amount set to 0."

    Design: Corner/cross_cutting_complexity_layers/cancel_from_conditionally_approved_refunds_deposit_full
    """
    ctx = setup_conditionally_approved(attendance=3000, max_capacity=6000, buffer=60,
                                       event_kind="FESTIVAL",
                                       occupy_start="2026-07-19T10:00:00Z",
                                       occupy_end="2026-07-19T14:00:00Z",
                                       set_clock_first=True)
    app_id = ctx["application"]["id"]
    applicant_id = ctx["applicant"]["id"]
    deposit = pay_deposit(app_id, applicant_id, 500)
    segs = validate_success(api.list_route_segments(app_id, officer_headers()))
    seg_id = segs[0]["id"]
    api.cancel_application(app_id, make_applicant_headers(applicant_id))
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "CANCELLED"
    dep = validate_success(api.get_deposit_global(deposit["id"], officer_headers()))
    assert dep["status"] == "REFUNDED"
    assert dep["refunded_amount"] == 500.00
    assert dep["forfeited_amount"] == 0.00
    seg = validate_success(api.get_route_segment(app_id, seg_id, officer_headers()))
    assert seg["status"] == "RELEASED"


# ==========================================================================
# Conservation invariants (queue A)
# ==========================================================================
def test_deposit_conservation_forfeit_plus_refund(api):
    """PRD §3.8: "so the two always sum back to the deposit amount, and cleanup charges
    beyond the deposit are never clawed back from the applicant." PRD §3.8: "the
    forfeited_amount is the lesser of the deposit's amount and the debrief's
    cleanup_charges ... the refunded_amount is the deposit's amount minus the
    forfeited_amount".

    Design: Difficulty/compensating_invariant/deposit_conservation_forfeit_plus_refund
    """
    ctx = setup_debrief_open(cleanup_charges=120, actual_attendance=3000,
                             incident_count=0, deposit_amount=500,
                             attendance=3000, max_capacity=5000, buffer=60,
                             venue_type="PLAZA", event_kind="FESTIVAL",
                             occupy_start="2026-06-18T10:00:00Z",
                             occupy_end="2026-06-18T14:00:00Z")
    app_id = ctx["application"]["id"]
    deposit_id = ctx["deposit"]["id"]
    api.finalize_debrief(app_id, ctx["debrief"]["id"], officer_headers())
    deposit = validate_success(api.get_deposit_global(deposit_id, officer_headers()))
    assert deposit["forfeited_amount"] == 120.00
    assert deposit["refunded_amount"] == 380.00
    assert_deposit_conserved(deposit)  # 120 + 380 == 500 == amount


def test_deposit_conservation_holds_when_charges_exceed_deposit(api):
    """PRD §3.8: "so the two always sum back to the deposit amount, and cleanup charges
    beyond the deposit are never clawed back from the applicant." PRD §3.8: "the
    forfeited_amount is the lesser of the deposit's amount and the debrief's
    cleanup_charges". (Second angle: even when cleanup_charges (700) exceed the
    deposit (500), forfeited+refunded still conserves exactly the deposit amount.)

    Design: Difficulty/compensating_invariant/deposit_conservation_forfeit_plus_refund
    """
    ctx = setup_debrief_open(cleanup_charges=700, actual_attendance=3000,
                             deposit_amount=500,
                             attendance=3000, max_capacity=5000, buffer=60,
                             venue_type="PLAZA", event_kind="FESTIVAL",
                             occupy_start="2026-08-18T10:00:00Z",
                             occupy_end="2026-08-18T14:00:00Z")
    app_id = ctx["application"]["id"]
    deposit_id = ctx["deposit"]["id"]
    api.finalize_debrief(app_id, ctx["debrief"]["id"], officer_headers())
    deposit = validate_success(api.get_deposit_global(deposit_id, officer_headers()))
    assert deposit["forfeited_amount"] == 500.00  # capped at amount
    assert deposit["refunded_amount"] == 0.00
    assert_deposit_conserved(deposit)  # 500 + 0 == 500 == amount


def test_venue_version_reserve_release_balance(api):
    """PRD §3.4: "The submit also increments the venue's version by 1, provisionally
    reserving the occupancy window for the application's window". PRD §3.7:
    "Cancelling from UNDER_REVIEW or REVISION_REQUESTED moves all PLANNED route
    segments to RELEASED, increments the venue's version by 1 to free the
    reservation". PRD §2.7: on resubmit the buffered window "must not overlap the ...
    booked window of any other non-terminal application on the same venue" — a
    cancelled application is terminal, so the same window becomes bookable again.

    Design: Difficulty/compensating_invariant/venue_version_reserve_release_balance
    """
    from test_helpers import (create_venue, create_closure_schedule, create_applicant,
                              create_application, add_segment)
    venue = create_venue(venue_type="PARK", max_capacity=5000, setup_buffer_minutes=60)
    sched1 = create_closure_schedule(corridor_name="P1 St", min_gap_minutes=30)
    sched2 = create_closure_schedule(corridor_name="P2 St", min_gap_minutes=30)
    u1 = create_applicant(org_name="Org P1", contact_email="p1@x.com")
    u2 = create_applicant(org_name="Org P2", contact_email="p2@x.com")
    app1 = create_application(venue["id"], u1["id"], event_kind="PARADE",
                              expected_attendance=2000,
                              occupy_start="2026-06-19T10:00:00Z",
                              occupy_end="2026-06-19T14:00:00Z")
    add_segment(app1["id"], u1["id"], sched1["id"], segment_label="P1 1-3",
                closure_start="2026-06-19T09:00:00Z", closure_end="2026-06-19T15:00:00Z")
    api.submit_for_review(app1["id"], {"expected_venue_version": venue["version"]},
                          make_applicant_headers(u1["id"]))
    api.cancel_application(app1["id"], make_applicant_headers(u1["id"]))
    venue_v_after_cancel = get_venue_version(venue["id"])
    # App2 wants the SAME window; App1's release should make it bookable again
    app2 = create_application(venue["id"], u2["id"], event_kind="FESTIVAL",
                              expected_attendance=2000,
                              occupy_start="2026-06-19T10:00:00Z",
                              occupy_end="2026-06-19T14:00:00Z")
    add_segment(app2["id"], u2["id"], sched2["id"], segment_label="P2 1-3",
                closure_start="2026-06-19T09:00:00Z", closure_end="2026-06-19T15:00:00Z")
    resp = api.submit_for_review(app2["id"], {"expected_venue_version": venue_v_after_cancel},
                                 make_applicant_headers(u2["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "UNDER_REVIEW"
    app1_now = validate_success(api.get_application(app1["id"], officer_headers()))
    assert app1_now["status"] == "CANCELLED"


def test_venue_version_increments_on_both_submit_and_cancel(api):
    """PRD §3.4: "The submit also increments the venue's version by 1, provisionally
    reserving the occupancy window". PRD §3.7: "Cancelling from UNDER_REVIEW or
    REVISION_REQUESTED moves all PLANNED route segments to RELEASED, increments the
    venue's version by 1 to free the reservation". (Second angle: the reserve/release
    pair each advance Venue.version by exactly 1, the conserved reservation ledger.)

    Design: Difficulty/compensating_invariant/venue_version_reserve_release_balance
    """
    from test_helpers import (create_venue, create_closure_schedule, create_applicant,
                              create_application, add_segment)
    venue = create_venue(venue_type="PARK", max_capacity=5000, setup_buffer_minutes=60)
    sched = create_closure_schedule(corridor_name="R1 St", min_gap_minutes=30)
    u1 = create_applicant(org_name="Org R1", contact_email="r1@x.com")
    v0 = venue["version"]
    app1 = create_application(venue["id"], u1["id"], event_kind="PARADE",
                              expected_attendance=2000,
                              occupy_start="2026-08-19T10:00:00Z",
                              occupy_end="2026-08-19T14:00:00Z")
    add_segment(app1["id"], u1["id"], sched["id"], segment_label="R1 1-3",
                closure_start="2026-08-19T09:00:00Z", closure_end="2026-08-19T15:00:00Z")
    api.submit_for_review(app1["id"], {"expected_venue_version": v0},
                          make_applicant_headers(u1["id"]))
    v_after_submit = get_venue_version(venue["id"])
    assert v_after_submit == v0 + 1  # reserve
    api.cancel_application(app1["id"], make_applicant_headers(u1["id"]))
    v_after_cancel = get_venue_version(venue["id"])
    assert v_after_cancel == v_after_submit + 1  # release


# ==========================================================================
# Finalize lockdown (queue B)
# ==========================================================================
# DELETED: test_finalize_debrief_from_closed_returns_not_open.
# ERROR PRECEDENCE SILENCE / unreachable-outcome. The test finalized a debrief
# twice; after the first finalize the application is CLOSED *and* the debrief is
# FINALIZED, so on the second call both the ISSUED guard and the OPEN guard fail.
# PRD §3.8 orders the checks "requires the application to be ISSUED (else
# ERR_APPLICATION_NOT_ISSUED) *and* a debrief in OPEN (else ERR_DEBRIEF_NOT_OPEN)"
# and PRD §2.7's tier-5 precedence list places ERR_APPLICATION_NOT_ISSUED before
# ERR_DEBRIEF_NOT_OPEN, so a PRD-faithful implementation returns
# ERR_APPLICATION_NOT_ISSUED, masking ERR_DEBRIEF_NOT_OPEN. Because finalizing
# always moves ISSUED->CLOSED in lockstep with OPEN->FINALIZED, the state
# "app ISSUED but debrief not OPEN" is unreachable, making ERR_DEBRIEF_NOT_OPEN on
# this endpoint permanently masked. The test asserted the masked error, which
# contradicts PRD-derivable precedence.
