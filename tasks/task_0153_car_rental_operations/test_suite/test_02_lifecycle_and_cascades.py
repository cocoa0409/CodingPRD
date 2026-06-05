"""Reservation / vehicle / agreement lifecycles and multi-hop cascades.

Covers the branching reservation fork, the cyclic vehicle state machine, the
depth-3 write-off cascade, the depth-2 incident-void reversal cascade, and the
two compensating-invariant conservation checks (ledger cash and availability count).
"""
from test_helpers import (
    validate_success, validate_error,
    make_fleet_manager_headers, make_rental_agent_headers,
    create_location, create_econ_class, create_vehicle, create_member,
    create_reservation, confirm_reservation, hold_vehicle, set_clock,
    setup_fleet, setup_confirmed_reservation, setup_open_agreement,
    get_vehicle, get_vehicle_class, get_agreement, get_member,
    get_reservation, get_ledger_entries,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import find_ledger_entries, ledger_sum

FM = make_fleet_manager_headers()
RA = make_rental_agent_headers()


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================
def test_confirmed_reservation_no_show_branch_releases_vehicle_and_strikes(api):
    """PRD §3.6: "Declaring the no-show releases any vehicle that was `RESERVED`
    for the reservation back to `AVAILABLE`, clearing its `held_by_reservation_id`
    and reconciling the class `available_count` upward, and recomputes the
    member's `no_show_strikes` so that this reservation now counts toward the
    strike total."

    Design: Difficulty/non_linear_state_machine/reservation_branches_confirmed_then_noshow_vs_pickup
    """
    set_clock("2026-07-01T09:00:00Z", api=api)
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res, veh, member = ctx["reservation"], ctx["vehicles"][0], ctx["member"]
    hold_vehicle(veh["id"], res["id"], veh["version"], api=api)
    # Advance past the 120-min grace window (pickup 10:00 + 120m = 12:00).
    set_clock("2026-07-01T12:30:00Z", api=api)

    no_show = validate_success(api.no_show_reservation(res["id"], RA))
    assert no_show["status"] == "NO_SHOW"

    veh_after = get_vehicle(veh["id"], api=api)
    assert veh_after["status"] == "AVAILABLE"
    assert veh_after["held_by_reservation_id"] is None

    member_after = get_member(member["id"], api=api)
    assert member_after["no_show_strikes"] == 1


def test_vehicle_reserved_back_to_available_on_release_restores_count(api):
    """PRD §3.4: "A held vehicle can be **released** without a pickup, a
    `RentalAgent` action that returns it `RESERVED → AVAILABLE`, clears
    `held_by_reservation_id`, and reconciles `available_count` upward."

    Design: Difficulty/non_linear_state_machine/vehicle_cycle_reserved_back_to_available_on_release
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res, veh, cls = ctx["reservation"], ctx["vehicles"][0], ctx["vehicle_class"]
    hold_vehicle(veh["id"], res["id"], veh["version"], api=api)

    released = validate_success(api.release_vehicle(veh["id"], RA))
    assert released["status"] == "AVAILABLE"
    assert released["held_by_reservation_id"] is None

    cls_after = get_vehicle_class(cls["id"], api=api)
    assert cls_after["available_count"] == 1, "release restores availability to its pre-hold value"


# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================
def test_writeoff_cascade_retires_vehicle_and_decrements_class_total(api):
    """PRD §3.8: "The write-off moves the agreement `OPEN → WRITE_OFF`, runs the
    final settlement including the full damage charge, and triggers a total-loss
    cascade on the vehicle: the on-rent vehicle is retired, moving
    `ON_RENT → RETIRED`, and the class accounting is reconciled so that both
    `total_count` and `available_count` drop to reflect the retired car."

    Design: Difficulty/transitive_cascade/writeoff_cascade_agreement_to_vehicle_to_class_depth3
    """
    ctx = setup_open_agreement(api=api, reservation_overrides={"ldw_selected": True},
                               odometer_out=1000, fuel_out_eighths=8)
    agr, veh, cls = ctx["agreement"], ctx["vehicle"], ctx["vehicle_class"]
    validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "TOTAL", 400000), RA,
    ), 201)

    wo = validate_success(api.write_off_rental_agreement(
        agr["id"], {"odometer_in": 1500, "fuel_in_eighths": 4}, FM,
    ))
    assert wo["status"] == "WRITE_OFF"

    veh_after = get_vehicle(veh["id"], api=api)
    assert veh_after["status"] == "RETIRED"

    cls_after = get_vehicle_class(cls["id"], api=api)
    assert cls_after["total_count"] == 0, "retired car drops total_count"
    assert cls_after["available_count"] == 0


def test_void_incident_reversal_drops_final_total(api):
    """PRD §3.8: "If a `DAMAGE` ledger line had already been emitted for that
    incident on a closed agreement, voiding emits a compensating
    `INCIDENT_REVERSAL` ledger line of an equal negative amount so the
    agreement's ledger sum drops by exactly the prior damage charge, and the
    agreement's `final_total_cents` is recomputed."

    Design: Difficulty/transitive_cascade/void_incident_cascade_reversal_to_final_total_depth2
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    inc = validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "MINOR", 25000), RA,
    ), 201)
    # Close at exactly 100 miles (no overage), full fuel -> base 15000 + DAMAGE 25000.
    closed = validate_success(api.close_rental_agreement(
        agr["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, RA,
    ))
    assert closed["final_total_cents"] == 40000

    validate_success(api.void_incident_report(inc["id"], FM))
    after = get_agreement(agr["id"], api=api)
    assert after["final_total_cents"] == 15000, "reversal of -25000 drops final by the DAMAGE charge"

    entries = get_ledger_entries(agr["id"], api=api)
    reversals = find_ledger_entries(entries, "INCIDENT_REVERSAL")
    assert len(reversals) == 1
    assert reversals[0]["amount_cents"] == -25000


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
def test_ledger_sum_conserved_across_damage_then_void(api):
    """PRD §3.8: "voiding emits a compensating `INCIDENT_REVERSAL` ledger line of
    an equal negative amount so the agreement's ledger sum drops by exactly the
    prior damage charge, and the agreement's `final_total_cents` is recomputed."

    Design: Difficulty/compensating_invariant/ledger_total_conserved_across_damage_then_void
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    inc = validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "MINOR", 25000), RA,
    ), 201)
    closed = validate_success(api.close_rental_agreement(
        agr["id"], {"odometer_in": 1600, "fuel_in_eighths": 8}, RA,
    ))
    assert closed["final_total_cents"] == 40000, "15000 base + 25000 DAMAGE"

    validate_success(api.void_incident_report(inc["id"], FM))
    after = get_agreement(agr["id"], api=api)
    assert after["final_total_cents"] == 15000

    entries = get_ledger_entries(agr["id"], api=api)
    assert ledger_sum(entries) == 15000, "ledger sum returns to the pre-incident base"


def test_available_count_conserved_across_hold_then_release(api):
    """PRD §3.4: "A successful hold sets `held_by_reservation_id` to the
    reservation, decrements the class `available_count` through reconciliation"
    PRD §3.4: "a `RentalAgent` action that returns it `RESERVED → AVAILABLE`,
    clears `held_by_reservation_id`, and reconciles `available_count` upward."

    Design: Difficulty/compensating_invariant/availability_count_conserved_across_hold_then_release
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res, veh, cls = ctx["reservation"], ctx["vehicles"][0], ctx["vehicle_class"]
    hold_vehicle(veh["id"], res["id"], veh["version"], api=api)

    mid = get_vehicle_class(cls["id"], api=api)
    assert mid["available_count"] == 0, "hold decrements available_count to 0"

    validate_success(api.release_vehicle(veh["id"], RA))
    after = get_vehicle_class(cls["id"], api=api)
    assert after["available_count"] == 1, "release restores available_count to 1"


# ===========================================================================
# Queue B — state_machines section
# ===========================================================================
def test_confirm_already_confirmed_reservation_invalid_state(api):
    """PRD §2.7: "(5) the state precondition that the target resource is in a
    state from which the requested transition is defined, rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_already_confirmed_reservation_returns_invalid_state
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res = ctx["reservation"]
    resp = api.confirm_reservation(res["id"], RA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_after_grace_window_rejected(api):
    """PRD §3.3: "Cancelling a `CONFIRMED` reservation is permitted only within
    the grace window — that is, only while the current server time is at or
    before `hold_expires_at`; an attempt after the window is rejected with
    `ERR_GRACE_WINDOW_EXPIRED`."

    Design: Corner/state_machines/cancel_after_grace_window_returns_grace_expired
    """
    set_clock("2026-07-01T09:00:00Z", api=api)
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res = ctx["reservation"]
    set_clock("2026-07-01T13:00:00Z", api=api)  # pickup 10:00 + 120m grace = 12:00; now past it.
    resp = api.cancel_reservation(res["id"], RA)
    validate_error(resp, ApiErrorId.ERR_GRACE_WINDOW_EXPIRED.value)


def test_no_show_within_grace_window_rejected(api):
    """PRD §3.6: "A no-show may be declared only strictly after the grace window
    has elapsed — the current server time must be strictly greater than
    `hold_expires_at`; an attempt while still within the window (current time at
    or before the deadline) is rejected with `ERR_WITHIN_GRACE`."

    Design: Corner/state_machines/no_show_within_grace_returns_within_grace
    """
    set_clock("2026-07-01T09:00:00Z", api=api)
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res = ctx["reservation"]
    set_clock("2026-07-01T10:30:00Z", api=api)  # inside 120-min grace.
    resp = api.no_show_reservation(res["id"], RA)
    validate_error(resp, ApiErrorId.ERR_WITHIN_GRACE.value)


def test_close_with_odometer_rollback_rejected(api):
    """PRD §3.7: "The return odometer must not roll backward: `odometer_in` must
    be at least `odometer_out`, else the close is rejected with
    `ERR_ODOMETER_ROLLBACK`."

    Design: Corner/state_machines/close_with_odometer_rollback_returns_rollback
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    resp = api.close_rental_agreement(ctx["agreement"]["id"], {"odometer_in": 900, "fuel_in_eighths": 8}, RA)
    validate_error(resp, ApiErrorId.ERR_ODOMETER_ROLLBACK.value)


def test_close_with_filed_total_incident_requires_writeoff(api):
    """PRD §3.7: "An agreement that still carries a `FILED` incident of `TOTAL`
    severity cannot be closed at all — a total loss must instead be written off
    — and such a close is rejected with `ERR_TOTAL_LOSS_REQUIRES_WRITEOFF`."

    Design: Corner/state_machines/close_with_filed_total_incident_requires_writeoff
    """
    ctx = setup_open_agreement(api=api, reservation_overrides={"ldw_selected": True},
                               odometer_out=1000, fuel_out_eighths=8)
    validate_success(api.create_incident_report(
        f.create_incident_report_payload(ctx["agreement"]["id"], "TOTAL", 500000), RA,
    ), 201)
    resp = api.close_rental_agreement(ctx["agreement"]["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, RA)
    validate_error(resp, ApiErrorId.ERR_TOTAL_LOSS_REQUIRES_WRITEOFF.value)


def test_writeoff_without_total_incident_rejected(api):
    """PRD §3.8: "the write-off requires at least one `TOTAL`-severity incident
    on the agreement, otherwise it is rejected with `ERR_NO_TOTAL_INCIDENT`."

    Design: Corner/state_machines/writeoff_without_total_incident_returns_no_total
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    resp = api.write_off_rental_agreement(ctx["agreement"]["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, FM)
    validate_error(resp, ApiErrorId.ERR_NO_TOTAL_INCIDENT.value)


def test_hold_busy_vehicle_nonoverlap_window_not_available(api):
    """PRD §3.4: "Finally, the vehicle must itself be `AVAILABLE`; a vehicle that
    is busy in some other status (even with no overlapping window) fails here
    with `ERR_VEHICLE_NOT_AVAILABLE`."

    Design: Corner/state_machines/hold_busy_vehicle_nonoverlap_returns_not_available
    """
    set_clock("2026-07-01T09:00:00Z", api=api)
    fleet = setup_fleet(api=api, num_vehicles=2)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    veh1, veh2 = fleet["vehicles"]
    member = create_member(api=api)

    # veh1 -> ON_RENT for R1 [Jul1, Jul5).
    res1 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-05T10:00:00Z", api=api)
    confirm_reservation(res1["id"], api=api)
    hold_vehicle(veh1["id"], res1["id"], veh1["version"], api=api)
    validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(res1["id"], veh1["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)

    # R2 [Jul10, Jul12) does not overlap; confirmed via veh2 capacity.
    res2 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-10T10:00:00Z", "2026-07-12T10:00:00Z", api=api)
    confirm_reservation(res2["id"], api=api)
    veh1_now = get_vehicle(veh1["id"], api=api)
    resp = api.hold_vehicle(veh1["id"], {"reservation_id": res2["id"],
                                         "expected_vehicle_version": veh1_now["version"]}, RA)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_AVAILABLE.value)


def test_terminal_cancelled_reservation_cannot_confirm(api):
    """PRD §2.7: "(5) the state precondition that the target resource is in a
    state from which the requested transition is defined, rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_cancelled_reservation_cannot_confirm
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)
    member = create_member(api=api)
    res = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    validate_success(api.cancel_reservation(res["id"], RA))
    resp = api.confirm_reservation(res["id"], RA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue A — second variants (each difficulty instance carries >=2 tests)
# ===========================================================================
def test_confirmed_reservation_pickup_branch_drives_on_rent(api):
    """PRD §3.5: "On success, the reservation advances `CONFIRMED → PICKED_UP`, a
    new `RentalAgreement` is created in `OPEN` status referencing the reservation
    and the assigned vehicle, and the vehicle moves to `ON_RENT`"

    Design: Difficulty/non_linear_state_machine/reservation_branches_confirmed_then_noshow_vs_pickup
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res, veh = ctx["reservation"], ctx["vehicles"][0]
    hold_vehicle(veh["id"], res["id"], veh["version"], api=api)
    agr = validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(res["id"], veh["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)
    assert agr["status"] == "OPEN"
    res_after = get_reservation(res["id"], api=api)
    assert res_after["status"] == "PICKED_UP"
    assert get_vehicle(veh["id"], api=api)["status"] == "ON_RENT"


def test_vehicle_hold_decrements_available_count(api):
    """PRD §3.4: "A successful hold sets `held_by_reservation_id` to the
    reservation, decrements the class `available_count` through reconciliation,
    and increments the vehicle's `version` by one"

    Design: Difficulty/non_linear_state_machine/vehicle_cycle_reserved_back_to_available_on_release
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res, veh, cls = ctx["reservation"], ctx["vehicles"][0], ctx["vehicle_class"]
    held = validate_success(api.hold_vehicle(veh["id"], {
        "reservation_id": res["id"], "expected_vehicle_version": veh["version"],
    }, RA))
    assert held["status"] == "RESERVED"
    assert held["held_by_reservation_id"] == res["id"]
    cls_mid = get_vehicle_class(cls["id"], api=api)
    assert cls_mid["available_count"] == 0


def test_writeoff_runs_full_damage_settlement(api):
    """PRD §3.8: "The write-off moves the agreement `OPEN → WRITE_OFF`, runs the
    final settlement including the full damage charge"

    Design: Difficulty/transitive_cascade/writeoff_cascade_agreement_to_vehicle_to_class_depth3
    """
    ctx = setup_open_agreement(api=api, reservation_overrides={"ldw_selected": True},
                               odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    # TOTAL with LDW: liability capped at the TOTAL deductible 250000.
    validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "TOTAL", 400000), RA,
    ), 201)
    wo = validate_success(api.write_off_rental_agreement(
        agr["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, FM,
    ))
    entries = get_ledger_entries(agr["id"], api=api)
    damage = find_ledger_entries(entries, "DAMAGE")
    assert len(damage) == 1
    assert damage[0]["amount_cents"] == 250000
    # base 3*5000=15000; ldw_selected -> ADDONS = 3*ldw_per_day(1500)=4500;
    # 100 miles (no overage), full fuel (no fuel charge); damage 250000.
    # final = 15000 + 4500 + 250000 = 269500 (PRD §3.7 sum-of-ledger-lines).
    assert wo["final_total_cents"] == 269500


def test_void_incident_emits_reversal_ledger_entry(api):
    """PRD §3.8: "voiding emits a compensating `INCIDENT_REVERSAL` ledger line of
    an equal negative amount so the agreement's ledger sum drops by exactly the
    prior damage charge"

    Design: Difficulty/transitive_cascade/void_incident_cascade_reversal_to_final_total_depth2
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    inc = validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "MINOR", 25000), RA,
    ), 201)
    validate_success(api.close_rental_agreement(agr["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, RA))
    void = validate_success(api.void_incident_report(inc["id"], FM))
    assert void["status"] == "VOID"
    entries = get_ledger_entries(agr["id"], api=api)
    reversal = find_ledger_entries(entries, "INCIDENT_REVERSAL")
    assert len(reversal) == 1
    assert reversal[0]["amount_cents"] == -25000


def test_ledger_sum_equals_final_total_before_void(api):
    """PRD §3.7: "The agreement's `final_total_cents` is the sum of `amount_cents`
    across all of that agreement's ledger entries, where charges are positive
    and credits or reversals are negative."

    Design: Difficulty/compensating_invariant/ledger_total_conserved_across_damage_then_void
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "MINOR", 25000), RA,
    ), 201)
    closed = validate_success(api.close_rental_agreement(agr["id"], {"odometer_in": 1600, "fuel_in_eighths": 8}, RA))
    entries = get_ledger_entries(agr["id"], api=api)
    assert ledger_sum(entries) == closed["final_total_cents"] == 40000


def test_pickup_does_not_change_available_count_for_reserved_vehicle(api):
    """PRD §3.5: "if it was `RESERVED` its `held_by_reservation_id` is cleared and
    the class `available_count` is unchanged (the car was already excluded from
    availability while reserved)"

    Design: Difficulty/compensating_invariant/availability_count_conserved_across_hold_then_release
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res, veh, cls = ctx["reservation"], ctx["vehicles"][0], ctx["vehicle_class"]
    hold_vehicle(veh["id"], res["id"], veh["version"], api=api)
    assert get_vehicle_class(cls["id"], api=api)["available_count"] == 0
    validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(res["id"], veh["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)
    # Pickup from RESERVED leaves available_count unchanged at 0.
    assert get_vehicle_class(cls["id"], api=api)["available_count"] == 0
