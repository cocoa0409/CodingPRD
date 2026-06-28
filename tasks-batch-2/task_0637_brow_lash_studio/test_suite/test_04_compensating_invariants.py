"""Compensating-invariant tests: credit conservation across consume/refund, and recurring
schedule slot conservation across spawn/cancel.

Design queue A (Difficulty): compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, ApiErrorId,
    make_lash_tech_headers,
    create_appointment_payload, create_recurring_schedule_payload,
)
from test_helpers.fixtures import (
    SM, FD, set_clock, create_studio, create_service_type, create_plan, create_tech,
    create_member, create_membership, sanitize_tech, credit_ledger, get_membership,
)


def _setup_anchored_credit_member():
    """Studio cutoff 24h; PREMIER plan allotment 8; FULL_SET + FILL; one tech sanitized for
    both anchor and the fill date; member with ACTIVE membership balance 8 and a COMPLETED
    FULL_SET anchor at 2026-06-01T10:00:00Z. Returns (member, fill_id, ms, ms_version_now)."""
    studio = create_studio(name="Glow", late_cancel_cutoff_hours=24)
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-01T09:00:00Z")
    sanitize_tech(tech["id"], "2026-06-09T08:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    set_clock("2026-06-01T09:00:00Z")
    full_appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-01T10:00:00Z"), FD))
    set_clock("2026-06-01T12:30:00Z")
    get_success_data(api_client.complete_appointment(full_appt["id"],
                                                     make_lash_tech_headers(full_appt["lash_tech_id"])))
    ms_v = get_membership(ms["id"])["version"]
    return member, fill["id"], full_st["id"], ms, ms_v


def test_credit_consume_then_timely_cancel_conserves_balance():
    """PRD §3.8: "the appointment moves to `CANCELLED`, `deposit_forfeited_cents` is set to
    zero so the cash deposit is fully refundable, and if it was credit-paid a `REFUND` ledger
    entry with a `delta` of the positive of `credits_charged` is appended, returning the
    credits."

    Design: Difficulty/compensating_invariant/credit_consume_then_refund_conserves_balance
    """
    member, fill_id, _full_id, ms, ms_v = _setup_anchored_credit_member()
    set_clock("2026-06-05T09:00:00Z")
    # FILL credit booking (cost 1); start 2026-06-09 is >24h ahead so cancel is timely.
    fill_appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], fill_id, "2026-06-09T10:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms_v), FD))
    cancelled = validate_success(api_client.cancel_appointment(fill_appt["id"], FD))
    assert cancelled["status"] == "CANCELLED"
    assert get_membership(ms["id"])["credit_balance"] == 8, \
        "consume -1 then refund +1 restores balance to 8"
    ledger = credit_ledger(ms["id"])
    consumes = [e for e in ledger if e["reason"] == "CONSUME" and e["source_ref_id"] == fill_appt["id"]]
    refunds = [e for e in ledger if e["reason"] == "REFUND" and e["source_ref_id"] == fill_appt["id"]]
    assert len(consumes) == 1 and consumes[0]["delta"] == -1, f"one CONSUME -1, got {consumes}"
    assert len(refunds) == 1 and refunds[0]["delta"] == 1, f"one REFUND +1, got {refunds}"
    assert consumes[0]["delta"] + refunds[0]["delta"] == 0, "consume + refund deltas sum to 0"


def test_credit_consume_then_late_cancel_conserves_balance():
    """PRD §3.8: "A late cancellation of a credit-paid appointment likewise appends a `REFUND`
    ledger entry of the positive of `credits_charged`."

    Design: Difficulty/compensating_invariant/credit_consume_then_refund_conserves_balance
    """
    member, fill_id, _full_id, ms, ms_v = _setup_anchored_credit_member()
    set_clock("2026-06-05T09:00:00Z")
    # FILL credit booking (cost 1); start 2026-06-09 then cancel within the 24h cutoff (late).
    fill_appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], fill_id, "2026-06-09T10:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms_v), FD))
    set_clock("2026-06-08T20:00:00Z")  # 14h before start -> within 24h cutoff -> late cancel
    cancelled = validate_success(api_client.cancel_appointment(fill_appt["id"], FD))
    assert cancelled["status"] == "LATE_CANCELLED"
    assert get_membership(ms["id"])["credit_balance"] == 8, \
        "consume -1 then late-cancel refund +1 restores balance to 8"
    ledger = credit_ledger(ms["id"])
    consumes = [e for e in ledger if e["reason"] == "CONSUME" and e["source_ref_id"] == fill_appt["id"]]
    refunds = [e for e in ledger if e["reason"] == "REFUND" and e["source_ref_id"] == fill_appt["id"]]
    assert len(consumes) == 1 and consumes[0]["delta"] == -1, f"one CONSUME -1, got {consumes}"
    assert len(refunds) == 1 and refunds[0]["delta"] == 1, f"one REFUND +1, got {refunds}"


def test_recurring_spawn_advances_slot_pointer():
    """PRD §3.7: "After a successful spawn, the schedule's `next_due_utc` advances by
    `cadence_days` and its `spawned_count` increases by one."

    Design: Difficulty/compensating_invariant/recurring_spawn_then_cancel_conserves_schedule_slot
    """
    member, fill_id, _full_id, ms, ms_v = _setup_anchored_credit_member()
    sched = get_success_data(api_client.create_recurring_schedule(
        create_recurring_schedule_payload(member["id"], fill_id, cadence_days=14,
                                           first_start_utc="2026-06-09T10:00:00Z"), FD))
    assert sched["spawned_count"] == 0
    assert sched["next_due_utc"][:19] == "2026-06-09T10:00:00"
    ms_v = get_membership(ms["id"])["version"]
    set_clock("2026-06-05T09:00:00Z")
    get_success_data(api_client.spawn_next(sched["id"], ms_v, FD))
    after = get_success_data(api_client.get_recurring_schedule(sched["id"], FD))
    assert after["spawned_count"] == 1, f"spawn increments spawned_count to 1, got {after['spawned_count']}"
    # next_due advances by cadence_days (14): 2026-06-09 -> 2026-06-23
    assert after["next_due_utc"][:19] == "2026-06-23T10:00:00", \
        f"next_due advances by 14d to 2026-06-23, got {after['next_due_utc']}"


def test_recurring_spawn_then_timely_cancel_conserves_schedule_slot():
    """PRD §3.8: "When a timely cancellation resolves an appointment that was spawned by a
    recurring schedule, the slot is reclaimed: the schedule's `next_due_utc` is rewound by
    `cadence_days` and its `spawned_count` is decreased by one."

    Design: Difficulty/compensating_invariant/recurring_spawn_then_cancel_conserves_schedule_slot
    """
    member, fill_id, _full_id, ms, ms_v = _setup_anchored_credit_member()
    sched = get_success_data(api_client.create_recurring_schedule(
        create_recurring_schedule_payload(member["id"], fill_id, cadence_days=14,
                                           first_start_utc="2026-06-09T10:00:00Z"), FD))
    ms_v = get_membership(ms["id"])["version"]
    set_clock("2026-06-05T09:00:00Z")
    spawned = get_success_data(api_client.spawn_next(sched["id"], ms_v, FD))
    # After spawn: spawned_count==1, next_due advanced by 14d. Timely-cancel the spawned fill.
    cancelled = validate_success(api_client.cancel_appointment(spawned["id"], FD))
    assert cancelled["status"] == "CANCELLED"
    refreshed = get_success_data(api_client.get_recurring_schedule(sched["id"], FD))
    assert refreshed["spawned_count"] == 0, \
        f"spawn(+1) then timely-cancel(-1) restores spawned_count 0, got {refreshed['spawned_count']}"
    assert refreshed["next_due_utc"][:19] == "2026-06-09T10:00:00", \
        f"next_due rewound to first_start, got {refreshed['next_due_utc']}"
    assert get_membership(ms["id"])["credit_balance"] == 8, \
        "FILL credit consume then refund leaves balance at 8"
