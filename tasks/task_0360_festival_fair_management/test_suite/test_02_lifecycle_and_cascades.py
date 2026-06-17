"""Non-linear state machines and transitive cascade chains.

Difficulty queue (A): non_linear_state_machine, transitive_cascade.
"""
import pytest
from test_helpers import (
    validate_success, assert_festival, assert_wristband, assert_zone,
    create_live_festival, setup_live_festival_with_active_wristband,
    create_festival_with_zone_and_stage, create_zone, open_sales, go_live,
    weather_hold, gate_enter, setup_approved_application, setup_application_under_review,
    TEST_USERS,
)

_DIRECTOR = TEST_USERS["director_headers"]
_BOXOFFICE = TEST_USERS["boxoffice_headers"]
_VENDOR_MANAGER = TEST_USERS["vendor_manager_headers"]
_GATE = TEST_USERS["gate_attendant_headers"]


# ─── non_linear_state_machine / festival_cycle_live_suspended_resume ───

def test_festival_resume_returns_to_live(api):
    """PRD §3.1: "From `SUSPENDED`, resuming returns the festival to `LIVE` and permits
    entries again. This `LIVE` and `SUSPENDED` cycle may repeat as the weather changes."

    LIVE -> weather-hold (SUSPENDED) -> resume cycles the operational_posture back to
    LIVE on a back-edge loop.

    Design: Difficulty/non_linear_state_machine/festival_cycle_live_suspended_resume
    """
    festival, zone, stage = create_live_festival(start_date="2026-08-01", end_date="2026-08-02",
                                                 name="Cycle F")
    weather_hold(festival["id"])
    res = api.resume_festival(festival["id"], _DIRECTOR)
    resumed = validate_success(res, 200)
    assert_festival(resumed)
    assert resumed["operational_posture"] == "LIVE"


def test_festival_weather_hold_then_resume_permits_entry_again(api):
    """PRD §3.1: "While suspended, new gate entries are rejected with
    `ERR_FESTIVAL_SUSPENDED` but exits remain permitted, and scheduled performances are
    not auto-cancelled. From `SUSPENDED`, resuming returns the festival to `LIVE` and
    permits entries again."

    After the SUSPENDED->LIVE back-edge a fresh ENTER scan is admitted again, confirming
    the cycle reopens entry rather than leaving the suspend guard active.

    Design: Difficulty/non_linear_state_machine/festival_cycle_live_suspended_resume
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="CycleEnter F",
        rfid_uid="RF-CYC-1", max_reentries=1)
    weather_hold(festival["id"])
    validate_success(api.resume_festival(festival["id"], _DIRECTOR), 200)
    res = gate_enter(festival["id"], wristband["id"])
    event = validate_success(res, 201)
    assert event["outcome"] == "ADMITTED"


# ─── non_linear_state_machine / wristband_parallel_lifecycle_x_presence ───

def test_freeze_inside_wristband_keeps_presence_inside(api):
    """PRD §3.6: "The wristband carries two independent state dimensions: a lifecycle
    dimension governing the wallet and issuance, and a presence dimension governing
    whether the holder is currently inside the gates; the two evolve separately."
    PRD §3.6: "Freezing moves an `ACTIVE` wristband to `FROZEN`, which blocks further
    spend and triggers a recompute of `total_wallet_liability` to exclude this
    wristband's balance from the active sum."

    A wristband entered through the gate (presence INSIDE) then frozen reads
    lifecycle_status FROZEN while presence_status stays INSIDE — the two axes move
    independently on the same row.

    Design: Difficulty/non_linear_state_machine/wristband_parallel_lifecycle_x_presence
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="Parallel F",
        rfid_uid="RF-PAR-1", max_reentries=1)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    res = api.freeze_wristband(wristband["id"], _DIRECTOR)
    frozen = validate_success(res, 200)
    assert_wristband(frozen)
    assert frozen["lifecycle_status"] == "FROZEN"
    assert frozen["presence_status"] == "INSIDE"


def test_gate_entry_does_not_change_lifecycle_status(api):
    """PRD §3.6: "Activation ... moves the wristband's `lifecycle_status` from `ISSUED`
    to `ACTIVE`; the presence dimension is untouched and stays `OUTSIDE`."
    PRD §3.7: "An entry scan advances the presence dimension from `OUTSIDE` to `INSIDE`."

    Entering the gate moves presence_status to INSIDE while the lifecycle dimension
    remains ACTIVE — the presence transition leaves the lifecycle axis untouched.

    Design: Difficulty/non_linear_state_machine/wristband_parallel_lifecycle_x_presence
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="ParallelEnter F",
        rfid_uid="RF-PAR-2", max_reentries=1)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    after = validate_success(api.get_wristband(wristband["id"], _BOXOFFICE), 200)
    assert after["presence_status"] == "INSIDE"
    assert after["lifecycle_status"] == "ACTIVE"


# ─── transitive_cascade / cancel_cascade_ticket_to_wristband_to_liability_depth3 ───

def _setup_suspended_with_active_wristband(api, name, rfid_uid, balance,
                                           start_date="2026-08-01", end_date="2026-08-03",
                                           day_count=3):
    """Live festival -> ticket activated onto a topped-up wristband -> weather hold.
    Returns (festival, ticket, wristband) in SUSPENDED posture with balance in liability."""
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date=start_date, end_date=end_date, name=name, rfid_uid=rfid_uid,
        balance=balance, day_count=day_count, max_reentries=1)
    weather_hold(festival["id"])
    return festival, ticket, wristband


def test_cancel_cascade_freezes_linked_wristband_and_zeros_liability(api):
    """PRD §3.1: "The ticket refund chains further: if a refunded ticket is linked to a
    wristband whose `lifecycle_status` is `ACTIVE`, that wristband is automatically
    frozen to `FROZEN` so no further spend can occur, and freezing it in turn triggers
    a recompute of `total_wallet_liability` to drop the now-frozen balance out of the
    active sum — a three-step chain from ticket to wristband to festival liability."

    SUSPENDED->CANCELLED with one ACTIVATED ticket on a 50.00-balance ACTIVE wristband:
    the ticket is REFUNDED, its linked wristband is FROZEN, and total_wallet_liability
    drops to 0.00 as the frozen balance leaves the active sum.

    Design: Difficulty/transitive_cascade/cancel_cascade_ticket_to_wristband_to_liability_depth3
    """
    festival, ticket, wristband = _setup_suspended_with_active_wristband(
        api, "Cascade F", "RF-CAS-1", 50.00)
    res = api.cancel_festival(festival["id"], _DIRECTOR)
    cancelled = validate_success(res, 200)
    assert cancelled["operational_posture"] == "CANCELLED"
    assert cancelled["total_wallet_liability"] == 0.00, (
        f"expected total_wallet_liability 0.00, got {cancelled['total_wallet_liability']}")

    ticket_after = validate_success(api.get_ticket(ticket["id"], _BOXOFFICE), 200)
    assert ticket_after["status"] == "REFUNDED"
    wb_after = validate_success(api.get_wristband(wristband["id"], _BOXOFFICE), 200)
    assert wb_after["lifecycle_status"] == "FROZEN"


def test_cancel_cascade_refunds_ticket_before_freezing_wristband(api):
    """PRD §3.1: "In both cases, every ticket whose `status` is `SOLD` or `ACTIVATED`
    is refunded by the weather pro-rata refund algorithm using `current_festival_day`
    as the elapsed-days input, the ticket's `status` is set to `REFUNDED`, and each
    such refund increments the festival's `total_refund_liability`."

    The first hop of the depth-3 chain: cancelling from SUSPENDED sets the ACTIVATED
    ticket's status to REFUNDED, which is the cause of the subsequent wristband freeze.

    Design: Difficulty/transitive_cascade/cancel_cascade_ticket_to_wristband_to_liability_depth3
    """
    festival, ticket, wristband = _setup_suspended_with_active_wristband(
        api, "CascadeRefund F", "RF-CAS-2", 25.00)
    validate_success(api.cancel_festival(festival["id"], _DIRECTOR), 200)
    ticket_after = validate_success(api.get_ticket(ticket["id"], _BOXOFFICE), 200)
    assert ticket_after["status"] == "REFUNDED"
    wb_after = validate_success(api.get_wristband(wristband["id"], _BOXOFFICE), 200)
    assert wb_after["lifecycle_status"] == "FROZEN"


# ─── transitive_cascade / return_for_revision_releases_slot_depth2 ───

def test_return_for_revision_clears_fee_and_releases_slot(api):
    """PRD §3.8: "The manager may return the application for revision, reverting it to
    `UNDER_REVIEW`, but only if `fee_paid` is still 0; the revert is a compensation
    that decrements the zone's `allocated_count` by one, clears `booth_fee` back to
    null, and advances the zone's `version`, restoring the slot to the pool."

    Return-for-revision is a depth-2 compensation: the application returns to
    UNDER_REVIEW (A) which decrements the zone's allocated_count back to 0 and nulls
    the booth_fee (B).

    Design: Difficulty/transitive_cascade/return_for_revision_releases_slot_depth2
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_approved_application(festival["id"], zone, booth_tier="STANDARD",
                                             day_count=2, vendor_name="Art Co")
    res = api.return_for_revision(app["id"], _VENDOR_MANAGER)
    reverted = validate_success(res, 200)
    assert reverted["status"] == "UNDER_REVIEW"
    assert reverted["booth_fee"] is None, f"expected booth_fee null, got {reverted['booth_fee']}"

    zone_after = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    assert_zone(zone_after)
    assert zone_after["allocated_count"] == 0, (
        f"expected allocated_count 0, got {zone_after['allocated_count']}")


def test_approval_then_revision_zone_version_advances_twice(api):
    """PRD §3.8: "On a successful approval the server computes the booth fee, persists
    it on the application, increments the zone's `allocated_count` by one, and advances
    the zone's `version`."
    PRD §3.8: "the revert is a compensation that decrements the zone's `allocated_count`
    by one, clears `booth_fee` back to null, and advances the zone's `version`,
    restoring the slot to the pool."

    Approval advances the zone version once and the compensating revision advances it
    again, so after approve+return the zone version has moved past its creation value
    by two mutations while allocated_count nets back to 0.

    Design: Difficulty/transitive_cascade/return_for_revision_releases_slot_depth2
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    version_before_approve = zone["version"]
    vendor, app = setup_approved_application(festival["id"], zone, booth_tier="STANDARD",
                                             day_count=2, vendor_name="Art2 Co")
    zone_after_approve = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    assert zone_after_approve["version"] > version_before_approve
    validate_success(api.return_for_revision(app["id"], _VENDOR_MANAGER), 200)
    zone_after_revert = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    assert zone_after_revert["version"] > zone_after_approve["version"]
    assert zone_after_revert["allocated_count"] == 0
