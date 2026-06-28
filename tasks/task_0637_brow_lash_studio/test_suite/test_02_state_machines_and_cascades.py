"""Non-linear state machine and transitive cascade tests.

Design queue A (Difficulty): non_linear_state_machine, transitive_cascade.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_lash_tech_headers,
    create_appointment_payload, create_recurring_schedule_payload,
)
from test_helpers.fixtures import (
    SM, FD, set_clock, create_studio, create_service_type, create_plan, create_tech,
    create_member, create_membership, sanitize_tech, credit_ledger, get_membership,
    get_appointment, get_member,
)


# ──────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / membership_cyclic_suspend_reactivate
# ──────────────────────────────────────────────────────────────────────────
def _drive_to_suspended():
    """Threshold=3, window=90. Two in-window no-shows (May 1), then a third (June 1)."""
    studio = create_studio(name="Glow", noshow_strike_window_days=90, noshow_strike_threshold=3,
                          late_cancel_cutoff_hours=24)
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-05-01T00:00:00Z")
    sanitize_tech(tech["id"], "2026-06-01T00:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"])
    set_clock("2026-05-01T09:00:00Z")
    a1 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-05-01T08:00:00Z"), FD))
    get_success_data(api_client.mark_no_show(a1["id"], FD))
    a2 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-05-01T08:30:00Z"), FD))
    get_success_data(api_client.mark_no_show(a2["id"], FD))
    set_clock("2026-06-01T09:00:00Z")
    a3 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-01T08:00:00Z"), FD))
    return studio, member, ms, a3


def test_third_noshow_auto_suspends_membership():
    """PRD §3.8: "The member's `noshow_strike_count` is then recomputed against the rolling
    window, and if it reaches the studio's `noshow_strike_threshold` the member's membership
    cascades from `ACTIVE` or `PAST_DUE` to `SUSPENDED`".

    Design: Difficulty/non_linear_state_machine/membership_cyclic_suspend_reactivate
    """
    studio, member, ms, a3 = _drive_to_suspended()
    get_success_data(api_client.mark_no_show(a3["id"], FD))
    after = get_membership(ms["id"])
    assert after["status"] == "SUSPENDED", \
        f"3rd in-window strike suspends membership, got {after['status']}"


def test_suspended_membership_reactivates_after_strikes_age_out():
    """PRD §3.4: "A `SUSPENDED` membership may be reactivated to `ACTIVE`, but only when the
    member's `noshow_strike_count` has fallen below the studio's threshold because the
    offending strikes have aged out of the rolling window".

    Design: Difficulty/non_linear_state_machine/membership_cyclic_suspend_reactivate
    """
    studio, member, ms, a3 = _drive_to_suspended()
    get_success_data(api_client.mark_no_show(a3["id"], FD))
    # Advance clock so all three strikes (May 1, May 1, June 1) age past the 90-day window.
    set_clock("2026-09-15T00:00:00Z")
    reactivated = validate_success(api_client.reactivate_membership(ms["id"], SM))
    assert reactivated["status"] == "ACTIVE", \
        f"after strikes age out, reactivate -> ACTIVE, got {reactivated['status']}"
    refreshed_member = get_member(member["id"])
    assert refreshed_member["noshow_strike_count"] == 0, \
        f"all strikes aged out -> count 0, got {refreshed_member['noshow_strike_count']}"


# ──────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / appointment_fork_join_completed_vs_noshow
# ──────────────────────────────────────────────────────────────────────────
def _setup_two_premium_appts_past_start():
    """Two cash FULL_SET (PREMIUM) BOOKED appointments for one member on two techs; clock 12:30."""
    studio = create_studio(name="Glow", noshow_strike_threshold=3)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech1 = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    tech2 = create_tech(studio["id"], full_name="Nia", skill_level=3, station_number=2)
    sanitize_tech(tech1["id"], "2026-06-10T09:00:00Z")
    sanitize_tech(tech2["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    appt_done = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T12:00:00Z"), FD))
    appt_ns = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T12:00:00Z"), FD))
    set_clock("2026-06-10T12:30:00Z")
    return member, appt_done, appt_ns


def test_complete_branch_anchors_premium_and_forfeits_nothing():
    """PRD §3.8: "Completion is performed by the assigned `LashTech` (or a `StudioManager`)
    and moves the appointment to `COMPLETED` ... On completion, if the service `category` is
    `PREMIUM`, the member's `last_premium_completed_utc` is recomputed to reflect this newly
    completed premium visit".

    Design: Difficulty/non_linear_state_machine/appointment_fork_join_completed_vs_noshow
    """
    member, appt_done, _ = _setup_two_premium_appts_past_start()
    tech_id = appt_done["lash_tech_id"]
    completed = validate_success(api_client.complete_appointment(appt_done["id"],
                                                                 make_lash_tech_headers(tech_id)))
    assert completed["status"] == "COMPLETED"
    assert completed["deposit_forfeited_cents"] == 0, \
        f"COMPLETED forfeits nothing, got {completed['deposit_forfeited_cents']}"
    refreshed = get_member(member["id"])
    assert refreshed["last_premium_completed_utc"] is not None
    assert refreshed["last_premium_completed_utc"][:19] == "2026-06-10T12:00:00", \
        f"anchor = completed PREMIUM start, got {refreshed['last_premium_completed_utc']}"


def test_noshow_branch_forfeits_full_deposit_and_adds_strike():
    """PRD §3.8: "The full deposit is kept: `deposit_forfeited_cents` is set equal to
    `deposit_cents`, and the cash deposit is retained by the studio."
    PRD §3.8: "The member's `noshow_strike_count` is then recomputed against the rolling
    window, and if it reaches the studio's `noshow_strike_threshold` the member's membership
    cascades from `ACTIVE` or `PAST_DUE` to `SUSPENDED`".

    Design: Difficulty/non_linear_state_machine/appointment_fork_join_completed_vs_noshow
    """
    member, _, appt_ns = _setup_two_premium_appts_past_start()
    no_show = validate_success(api_client.mark_no_show(appt_ns["id"], FD))
    assert no_show["status"] == "NO_SHOW"
    assert no_show["deposit_forfeited_cents"] == 2400, \
        f"NO_SHOW forfeits full 2400, got {no_show['deposit_forfeited_cents']}"
    refreshed = get_member(member["id"])
    assert refreshed["noshow_strike_count"] == 1, \
        f"one strike after one no-show, got {refreshed['noshow_strike_count']}"


# ──────────────────────────────────────────────────────────────────────────
# transitive_cascade / noshow_suspends_membership_cancels_future_appts_ends_schedule
# ──────────────────────────────────────────────────────────────────────────
def test_noshow_cascade_suspends_and_cancels_future_credit_appt_with_refund():
    """PRD §2.7: "every one of that member's appointments that is still `BOOKED` with a start
    instant in the future is auto-cancelled to `CANCELLED`, and for each such appointment that
    was credit-paid the credits are returned while each cash-deposit appointment forfeits
    nothing, because it is the suspension and not the member that cancels them."

    Design: Difficulty/transitive_cascade/noshow_suspends_membership_cancels_future_appts_ends_schedule
    """
    studio = create_studio(name="Glow", noshow_strike_threshold=3, noshow_strike_window_days=90)
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=2, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T00:00:00Z")
    sanitize_tech(tech["id"], "2026-06-20T06:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    set_clock("2026-06-10T09:00:00Z")
    a1 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-10T08:00:00Z"), FD))
    get_success_data(api_client.mark_no_show(a1["id"], FD))
    a2 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-10T08:30:00Z"), FD))
    get_success_data(api_client.mark_no_show(a2["id"], FD))
    ms_v_now = get_membership(ms["id"])["version"]
    future_appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-20T10:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms_v_now), FD))
    a3 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-12T10:00:00Z"), FD))
    set_clock("2026-06-12T10:30:00Z")
    # Trigger: third no-show
    resolved = validate_success(api_client.mark_no_show(a3["id"], FD))
    assert resolved["status"] == "NO_SHOW"
    assert get_membership(ms["id"])["status"] == "SUSPENDED"
    assert get_appointment(future_appt["id"])["status"] == "CANCELLED", \
        "future BOOKED credit appt auto-cancelled by suspension"
    ledger = credit_ledger(ms["id"])
    refunds = [e for e in ledger if e["reason"] == "REFUND" and e["source_ref_id"] == future_appt["id"]]
    assert len(refunds) == 1 and refunds[0]["delta"] == 2, \
        f"credit-paid auto-cancel refunds +2 referencing the future appt, got {refunds}"


def test_noshow_cascade_auto_cancels_future_cash_appt_without_forfeiture():
    """PRD §2.7: "every one of that member's appointments that is still `BOOKED` with a start
    instant in the future is auto-cancelled to `CANCELLED`, and for each such appointment that
    was credit-paid the credits are returned while each cash-deposit appointment forfeits
    nothing, because it is the suspension and not the member that cancels them."

    Design: Difficulty/transitive_cascade/noshow_suspends_membership_cancels_future_appts_ends_schedule
    """
    studio = create_studio(name="Glow", noshow_strike_threshold=3, noshow_strike_window_days=90)
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=2, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T00:00:00Z")
    sanitize_tech(tech["id"], "2026-06-20T06:00:00Z")
    member = create_member(studio["id"])
    create_membership(member["id"], plan["id"], initial_credits=8)
    set_clock("2026-06-10T09:00:00Z")
    a1 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-10T08:00:00Z"), FD))
    get_success_data(api_client.mark_no_show(a1["id"], FD))
    a2 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-10T08:30:00Z"), FD))
    get_success_data(api_client.mark_no_show(a2["id"], FD))
    # A future CASH appointment that the suspension should auto-cancel with no forfeiture.
    future_cash = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-20T10:00:00Z"), FD))
    a3 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-12T10:00:00Z"), FD))
    set_clock("2026-06-12T10:30:00Z")
    get_success_data(api_client.mark_no_show(a3["id"], FD))  # third strike -> suspension cascade
    resolved_future = get_appointment(future_cash["id"])
    assert resolved_future["status"] == "CANCELLED", \
        f"future cash appt auto-cancelled by suspension, got {resolved_future['status']}"
    assert resolved_future["deposit_forfeited_cents"] == 0, \
        f"suspension-driven cancel forfeits nothing, got {resolved_future['deposit_forfeited_cents']}"


# ──────────────────────────────────────────────────────────────────────────
# transitive_cascade / cancel_membership_ends_recurring_schedule
# ──────────────────────────────────────────────────────────────────────────
def test_cancel_membership_ends_active_recurring_schedule():
    """PRD §2.7: "When a membership is cancelled, any recurring fill schedule belonging to
    that member that is currently `ACTIVE` is automatically transitioned to `ENDED` as a
    cascade."

    Design: Difficulty/transitive_cascade/cancel_membership_ends_recurring_schedule
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=False)
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    sched = get_success_data(api_client.create_recurring_schedule(
        create_recurring_schedule_payload(member["id"], fill["id"], cadence_days=14,
                                           first_start_utc="2026-06-15T10:00:00Z"), FD))
    cancelled = validate_success(api_client.cancel_membership(ms["id"], SM))
    assert cancelled["status"] == "CANCELLED"
    refreshed_sched = get_success_data(api_client.get_recurring_schedule(sched["id"], FD))
    assert refreshed_sched["status"] == "ENDED", \
        f"cancel-membership cascades ACTIVE schedule -> ENDED, got {refreshed_sched['status']}"


def test_cancel_membership_does_not_end_paused_schedule():
    """PRD §2.7: "When a membership is cancelled, any recurring fill schedule belonging to
    that member that is currently `ACTIVE` is automatically transitioned to `ENDED` as a
    cascade."

    Design: Difficulty/transitive_cascade/cancel_membership_ends_recurring_schedule
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=False)
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    sched = get_success_data(api_client.create_recurring_schedule(
        create_recurring_schedule_payload(member["id"], fill["id"], cadence_days=14,
                                           first_start_utc="2026-06-15T10:00:00Z"), FD))
    # Move the schedule to PAUSED — the cascade only ends schedules that are currently ACTIVE.
    get_success_data(api_client.pause_schedule(sched["id"], FD))
    cancelled = validate_success(api_client.cancel_membership(ms["id"], SM))
    assert cancelled["status"] == "CANCELLED"
    refreshed_sched = get_success_data(api_client.get_recurring_schedule(sched["id"], FD))
    assert refreshed_sched["status"] == "PAUSED", \
        f"only ACTIVE schedules cascade to ENDED; PAUSED is untouched, got {refreshed_sched['status']}"
