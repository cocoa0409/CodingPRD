"""Appointment and membership lifecycles: confirm / cancel / no-show / checkout
state machines, terminal-state lockdown, divergent branch side effects, the
no-show -> strike -> auto-suspend cascade, the void -> no-show reclassification
cascade, and deposit forfeit/refund reconciliation.

Queue A (Difficulty) — rules: non_linear_state_machine, transitive_cascade,
boundary_precision_check (third strike at threshold).
Queue B (Corner) — sections: state_machines, cross_cutting_complexity_layers
(wallet reconciliation).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_appointment_payload,
    create_checkout_payload,
    create_salon,
    create_stylist,
    create_resource,
    create_service,
    create_client,
    create_product_sku,
    advance_clock,
    book_appointment,
    checkout_appointment,
    setup_bookable_salon,
    setup_membership,
)

OWNER = TEST_USERS["salon_owner_headers"]
FRONT = TEST_USERS["front_desk_headers"]


# =========================================================================== #
# Rule 3 — non_linear_state_machine
# =========================================================================== #
def test_appointment_branches_cancel_vs_noshow_divergent_effects(api):
    """PRD §3.4: "Cancellation sets the appointment to CANCELLED and reverses the
    booking's holds: the full deposit_held_cents is refunded into the client's
    wallet_credit_cents."
    PRD §3.4: "The forfeit is computed as the quoted price multiplied by the
    salon's no_show_fee_pct, rounded half up to whole cents; the salon actually
    forfeits the smaller of that fee and the held deposit, and the remainder of
    the deposit ... is refunded into the client's wallet_credit_cents. The
    client's no_show_strikes is then incremented by one."

    Design: Difficulty/non_linear_state_machine/appointment_branch_divergent_side_effects
    """
    salon = create_salon(name="Branch Salon", no_show_fee_pct=0.50,
                         no_show_suspend_threshold=3, tip_split_policy="DIRECT")
    # Two stylists so the two concurrent 13:00 appointments do not collide on a
    # single stylist's schedule (one stylist cannot serve two clients at once).
    stylist_c = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                               commission_pct=0.40, buffer_minutes=0)
    stylist_n = create_stylist(salon["id"], full_name="S2", compensation_model="COMMISSION",
                               commission_pct=0.40, buffer_minutes=0)
    chA = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    chB = create_resource(salon["id"], label="Chair B", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=8000, deposit_pct=0.50, requires_room=False)
    cli_c = create_client(salon["id"], full_name="Cancel Client", email="cc@x.com")
    cli_n = create_client(salon["id"], full_name="Noshow Client", email="nc@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt_c = get_success_data(api.create_appointment(
        create_appointment_payload(salon["id"], cli_c["id"], stylist_c["id"], chA["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist_c["version"]),
        FRONT,
    ))
    appt_n = get_success_data(api.create_appointment(
        create_appointment_payload(salon["id"], cli_n["id"], stylist_n["id"], chB["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist_n["version"]),
        FRONT,
    ))
    # Cancel branch (clock still before start).
    get_success_data(api.cancel_appointment(appt_c["id"], FRONT))
    # No-show branch (advance past start first).
    advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appt_n["id"], FRONT))

    appt_c_data = get_success_data(api.get_appointment(appt_c["id"], FRONT))
    appt_n_data = get_success_data(api.get_appointment(appt_n["id"], FRONT))
    cli_c_data = get_success_data(api.get_client(cli_c["id"], OWNER))
    cli_n_data = get_success_data(api.get_client(cli_n["id"], OWNER))
    assert appt_c_data["status"] == "CANCELLED"
    assert cli_c_data["wallet_credit_cents"] == 4000  # full deposit refunded
    assert cli_c_data["no_show_strikes"] == 0
    assert appt_n_data["status"] == "NO_SHOW"
    assert cli_n_data["wallet_credit_cents"] == 0  # fee 4000 == deposit 4000, nothing refunded
    assert cli_n_data["no_show_strikes"] == 1


def test_appointment_completed_branch_creates_checkout(api):
    """PRD §3.5: "Creating the checkout is what completes the appointment ... On
    success the appointment moves to COMPLETED, a checkout is created in the
    SETTLED state, and the appointment's version advances."

    Design: Difficulty/non_linear_state_machine/appointment_branch_divergent_side_effects
    """
    salon = create_salon(name="Complete Branch", no_show_fee_pct=0.50,
                         no_show_suspend_threshold=3, tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=8000, deposit_pct=0.50)
    client = create_client(salon["id"], full_name="Complete Client", email="comp@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    co = checkout_appointment(appt["id"], tip_cents=0)
    assert co["status"] == "SETTLED"
    appt_after = get_success_data(api.get_appointment(appt["id"], FRONT))
    assert appt_after["status"] == "COMPLETED"
    # The COMPLETED branch adds zero strikes (distinct from the NO_SHOW branch).
    client_after = get_success_data(api.get_client(client["id"], OWNER))
    assert client_after["no_show_strikes"] == 0


def test_membership_active_pastdue_cycle(api):
    """PRD §3.2: "A SalonOwner may mark an ACTIVE membership PAST_DUE — a lapse
    that suspends its discounts so that future appointment quotes price as
    non-member — and may later reinstate a PAST_DUE membership back to ACTIVE,
    restoring its discounts; the ACTIVE and PAST_DUE states therefore form a
    reversible cycle. ... Each of these three transitions advances the
    membership's version."

    Design: Difficulty/non_linear_state_machine/membership_active_pastdue_cycle
    """
    salon = create_salon(name="Cycle Salon")
    setup = setup_membership(salon["id"], plan_overrides={"name": "Gold", "service_discount_pct": 0.20})
    mem = setup["membership"]
    lapsed = get_success_data(api.lapse_membership(mem["id"], OWNER))
    assert lapsed["status"] == "PAST_DUE"
    reinstated = get_success_data(api.reinstate_membership(mem["id"], OWNER))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] > lapsed["version"]


def test_membership_lapse_then_reinstate_each_bumps_version(api):
    """PRD §3.2: "Each of these three transitions advances the membership's
    version."

    Design: Difficulty/non_linear_state_machine/membership_active_pastdue_cycle
    """
    salon = create_salon(name="Cycle Salon 2")
    setup = setup_membership(salon["id"])
    mem = setup["membership"]
    v0 = mem["version"]
    lapsed = get_success_data(api.lapse_membership(mem["id"], OWNER))
    reinstated = get_success_data(api.reinstate_membership(mem["id"], OWNER))
    assert lapsed["version"] > v0
    assert reinstated["version"] > lapsed["version"]
    assert reinstated["status"] == "ACTIVE"


# =========================================================================== #
# Rule 4 — transitive_cascade
# =========================================================================== #
def test_noshow_strike_triggers_auto_suspend_depth3(api):
    """PRD §3.4: "The client's no_show_strikes is then incremented by one. That
    strike increment is itself the trigger for a second-order effect: if the
    client's resulting no_show_strikes is at or above the salon's
    no_show_suspend_threshold and the client is currently ACTIVE, the client is
    auto-suspended to SUSPENDED within the same request."

    Design: Difficulty/transitive_cascade/noshow_strike_triggers_auto_suspend_depth3
    """
    salon = create_salon(name="Strike Salon", no_show_suspend_threshold=3,
                         no_show_fee_pct=0.0, tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Quick", duration_minutes=15,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="Repeat", email="rep@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    sv = stylist["version"]
    appts = []
    for hour in (13, 14, 15):
        appt = get_success_data(api.create_appointment(
            create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                       service["id"], f"2026-07-01T{hour}:00:00Z", sv),
            FRONT,
        ))
        sv += 1
        appts.append(appt)
    advance_clock(salon["id"], "2026-07-01T16:00:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appts[0]["id"], FRONT))
    get_success_data(api.no_show_appointment(appts[1]["id"], FRONT))
    # Third no-show drives strikes 2 -> 3 == threshold, flipping ACTIVE -> SUSPENDED.
    get_success_data(api.no_show_appointment(appts[2]["id"], FRONT))
    client_data = get_success_data(api.get_client(client["id"], OWNER))
    assert client_data["no_show_strikes"] == 3
    assert client_data["status"] == "SUSPENDED"
    appt3 = get_success_data(api.get_appointment(appts[2]["id"], FRONT))
    assert appt3["status"] == "NO_SHOW"


def test_void_reclassifies_appointment_to_noshow_depth2(api):
    """PRD §3.6: "Finally, the void reclassifies the visit as a missed one: the
    appointment is set to NO_SHOW and the full no-show cascade of §3.4 is applied
    — the client's no_show_strikes is incremented, the conditional auto-suspension
    is evaluated, and the deposit forfeit-and-refund against the client's
    wallet_credit_cents is performed exactly as a direct no-show would do."

    Design: Difficulty/transitive_cascade/void_reclassifies_appointment_to_noshow_depth2
    """
    salon = create_salon(name="Void Salon", no_show_fee_pct=0.0,
                         no_show_suspend_threshold=3, tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Wash", duration_minutes=30,
                             base_price_cents=6000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="Voidee", email="void@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt = get_success_data(api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    ))
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    co = get_success_data(api.create_checkout(create_checkout_payload(appt["id"], tip_cents=0), FRONT))
    # Void: checkout VOIDED -> appointment NO_SHOW -> strike 0 -> 1.
    voided = get_success_data(api.void_checkout(co["id"], OWNER))
    assert voided["status"] == "VOIDED"
    appt_after = get_success_data(api.get_appointment(appt["id"], FRONT))
    assert appt_after["status"] == "NO_SHOW"
    client_after = get_success_data(api.get_client(client["id"], OWNER))
    assert client_after["no_show_strikes"] == 1


def test_noshow_strike_increments_without_suspend_below_threshold(api):
    """PRD §3.4: "The client's no_show_strikes is then incremented by one. That
    strike increment is itself the trigger for a second-order effect: if the
    client's resulting no_show_strikes is at or above the salon's
    no_show_suspend_threshold and the client is currently ACTIVE, the client is
    auto-suspended to SUSPENDED within the same request."

    Design: Difficulty/transitive_cascade/noshow_strike_triggers_auto_suspend_depth3
    """
    # Threshold 5 so a single no-show increments the strike (depth-1 link) but
    # does NOT cross the suspend threshold (the second-order link stays inert).
    salon = create_salon(name="No Suspend Salon", no_show_suspend_threshold=5,
                         no_show_fee_pct=0.0, tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Quick", duration_minutes=15,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="One", email="one@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appt["id"], FRONT))
    client_data = get_success_data(api.get_client(client["id"], OWNER))
    assert client_data["no_show_strikes"] == 1
    assert client_data["status"] == "ACTIVE"


def test_void_reclassification_applies_deposit_forfeit_cascade(api):
    """PRD §3.6: "Finally, the void reclassifies the visit as a missed one: the
    appointment is set to NO_SHOW and the full no-show cascade of §3.4 is applied
    — the client's no_show_strikes is incremented, the conditional auto-suspension
    is evaluated, and the deposit forfeit-and-refund against the client's
    wallet_credit_cents is performed exactly as a direct no-show would do."

    Design: Difficulty/transitive_cascade/void_reclassifies_appointment_to_noshow_depth2
    """
    # deposit 4000 (base 8000 @ 0.5); no_show_fee_pct 0.25 -> forfeit 2000,
    # refund 2000. The deposit was applied at checkout, but on void the missed-
    # visit cascade runs the forfeit-and-refund just like a direct no-show.
    salon = create_salon(name="Void Forfeit Salon", no_show_fee_pct=0.25,
                         no_show_suspend_threshold=3, tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=8000, deposit_pct=0.5)
    client = create_client(salon["id"], full_name="VF", email="vf@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    co = checkout_appointment(appt["id"], tip_cents=0)
    get_success_data(api.void_checkout(co["id"], OWNER))
    appt_after = get_success_data(api.get_appointment(appt["id"], FRONT))
    assert appt_after["status"] == "NO_SHOW"
    client_after = get_success_data(api.get_client(client["id"], OWNER))
    assert client_after["no_show_strikes"] == 1
    # forfeit round_half_up(8000 * 0.25) = 2000; refund 4000 - 2000 = 2000.
    assert client_after["wallet_credit_cents"] == 2000


# =========================================================================== #
# Rule 6 — boundary_precision_check: third strike at threshold suspends
# =========================================================================== #
def test_strikes_below_threshold_stay_active(api):
    """PRD §3.4: "if the client's resulting no_show_strikes is at or above the
    salon's no_show_suspend_threshold and the client is currently ACTIVE, the
    client is auto-suspended to SUSPENDED within the same request."

    Design: Difficulty/boundary_precision_check/third_strike_at_threshold_suspends
    """
    salon = create_salon(name="Threshold Salon", no_show_suspend_threshold=3,
                         no_show_fee_pct=0.0, tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Quick", duration_minutes=15,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="Rep", email="rep2@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    sv = stylist["version"]
    appts = []
    for hour in (13, 14):
        appt = get_success_data(api.create_appointment(
            create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                       service["id"], f"2026-07-01T{hour}:00:00Z", sv),
            FRONT,
        ))
        sv += 1
        appts.append(appt)
    advance_clock(salon["id"], "2026-07-01T16:00:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appts[0]["id"], FRONT))
    get_success_data(api.no_show_appointment(appts[1]["id"], FRONT))
    # At 2 strikes (< threshold 3): still ACTIVE.
    at_two = get_success_data(api.get_client(client["id"], OWNER))
    assert at_two["no_show_strikes"] == 2
    assert at_two["status"] == "ACTIVE"


def test_third_strike_at_threshold_suspends(api):
    """PRD §3.4: "if the client's resulting no_show_strikes is at or above the
    salon's no_show_suspend_threshold and the client is currently ACTIVE, the
    client is auto-suspended to SUSPENDED within the same request."

    Design: Difficulty/boundary_precision_check/third_strike_at_threshold_suspends
    """
    salon = create_salon(name="Threshold Salon 2", no_show_suspend_threshold=3,
                         no_show_fee_pct=0.0, tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Quick", duration_minutes=15,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="Rep", email="rep3@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    sv = stylist["version"]
    appts = []
    for hour in (13, 14, 15):
        appt = get_success_data(api.create_appointment(
            create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                       service["id"], f"2026-07-01T{hour}:00:00Z", sv),
            FRONT,
        ))
        sv += 1
        appts.append(appt)
    advance_clock(salon["id"], "2026-07-01T16:00:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appts[0]["id"], FRONT))
    get_success_data(api.no_show_appointment(appts[1]["id"], FRONT))
    get_success_data(api.no_show_appointment(appts[2]["id"], FRONT))
    # The instant strikes reaches 3 (== threshold): SUSPENDED.
    at_three = get_success_data(api.get_client(client["id"], OWNER))
    assert at_three["no_show_strikes"] == 3
    assert at_three["status"] == "SUSPENDED"


# =========================================================================== #
# Corner — state_machines section
# =========================================================================== #
def test_cancel_already_cancelled_appointment_returns_invalid_state(api):
    """PRD §3.4: "Cancellation is available ... and is permitted only while the
    appointment is BOOKED or CONFIRMED and only while the salon's current_utc is
    still strictly before the appointment's start_utc ...; attempting it on an
    ineligible state or after start yields ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/cancel_already_cancelled_appointment_returns_invalid_state
    """
    base = setup_bookable_salon(
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 4000, "deposit_pct": 0.5},
    )
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    appt, _ = book_appointment(sid, base["client"]["id"], stylist,
                               base["resources"][0]["id"], base["service"]["id"],
                               "2026-07-01T13:00:00Z")
    get_success_data(api.cancel_appointment(appt["id"], FRONT))
    resp = api.cancel_appointment(appt["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    # No second refund: wallet holds exactly one deposit (2000).
    client_data = get_success_data(api.get_client(base["client"]["id"], OWNER))
    assert client_data["wallet_credit_cents"] == 2000


def test_no_show_before_start_returns_invalid_state(api):
    """PRD §3.4: "No-show ... is permitted only while the appointment is BOOKED
    or CONFIRMED and only once the slot has begun — the salon's current_utc is at
    or after the appointment's start_utc; an out-of-state or too-early attempt
    yields ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/no_show_before_start_returns_invalid_state
    """
    base = setup_bookable_salon(
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.0},
    )
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    appt, _ = book_appointment(sid, base["client"]["id"], stylist,
                               base["resources"][0]["id"], base["service"]["id"],
                               "2026-07-01T13:00:00Z")
    # Clock still at 12:00 (before the 13:00 start).
    resp = api.no_show_appointment(appt["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_void_already_voided_checkout_returns_invalid_state(api):
    """PRD §3.6: "It is permitted only while the checkout is SETTLED; voiding an
    already-voided checkout is rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/void_already_voided_checkout_returns_invalid_state
    """
    base = setup_bookable_salon(
        salon_overrides={"no_show_fee_pct": 0.0},
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 6000, "deposit_pct": 0.0},
    )
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    sku = create_product_sku(sid, sku="SK-1", name="P", unit_price_cents=1000, qty_on_hand=10)
    appt, _ = book_appointment(sid, base["client"]["id"], stylist,
                               base["resources"][0]["id"], base["service"]["id"],
                               "2026-07-01T13:00:00Z")
    advance_clock(sid, "2026-07-01T14:00:00Z", base["salon_version"])
    co = checkout_appointment(appt["id"], retail_lines=[{"product_sku_id": sku["id"], "quantity": 2}])
    get_success_data(api.void_checkout(co["id"], OWNER))
    resp = api.void_checkout(co["id"], OWNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    # Inventory not restored a second time (back to 10 once, stays 10).
    sku_after = get_success_data(api.get_product_sku(sku["id"], FRONT))
    assert sku_after["qty_on_hand"] == 10


def test_reinstate_active_membership_returns_invalid_state(api):
    """PRD §3.2: "Reinstating a membership that is not currently PAST_DUE is a
    state error."

    Design: Corner/state_machines/reinstate_active_membership_returns_invalid_state
    """
    salon = create_salon(name="S")
    setup = setup_membership(salon["id"], plan_overrides={"service_discount_pct": 0.2})
    resp = api.reinstate_membership(setup["membership"]["id"], OWNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_lapse_cancelled_membership_returns_invalid_state(api):
    """PRD §3.2: "From either the ACTIVE or the PAST_DUE state a SalonOwner may
    cancel the membership, moving it to the terminal CANCELLED state, which
    grants no discounts and cannot be revived."

    Design: Corner/state_machines/lapse_cancelled_membership_returns_invalid_state
    """
    salon = create_salon(name="S")
    setup = setup_membership(salon["id"], plan_overrides={"service_discount_pct": 0.2})
    mem = setup["membership"]
    get_success_data(api.cancel_membership(mem["id"], OWNER))
    resp = api.lapse_membership(mem["id"], OWNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_second_checkout_already_checked_out(api):
    """PRD §3.5: "a second checkout for an appointment that already has a settled
    one is rejected with ERR_ALREADY_CHECKED_OUT (HTTP 409)."

    Design: Corner/state_machines/checkout_completed_appointment_returns_invalid_state
    """
    base = setup_bookable_salon(
        salon_overrides={"no_show_fee_pct": 0.0},
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 6000, "deposit_pct": 0.0},
    )
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    appt, _ = book_appointment(sid, base["client"]["id"], stylist,
                               base["resources"][0]["id"], base["service"]["id"],
                               "2026-07-01T13:00:00Z")
    advance_clock(sid, "2026-07-01T14:00:00Z", base["salon_version"])
    checkout_appointment(appt["id"])
    resp = api.create_checkout(create_checkout_payload(appt["id"], tip_cents=0), FRONT)
    validate_error(resp, ApiErrorId.ERR_ALREADY_CHECKED_OUT.value, 409)


def test_freshly_booked_appointment_is_booked_version_one(api):
    """PRD §3.3: "On a successful booking the appointment's status is set to
    BOOKED."
    PRD §2.4: "The version field is an integer that starts at its initial value
    on creation and increments by one on every mutation."

    Design: Corner/state_machines/appointment_initial_state_is_booked
    """
    base = setup_bookable_salon(
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.0},
    )
    stylist = base["stylists"][0]
    appt = get_success_data(api.create_appointment(
        create_appointment_payload(base["salon"]["id"], base["client"]["id"], stylist["id"],
                                   base["resources"][0]["id"], base["service"]["id"],
                                   "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    ))
    assert appt["status"] == "BOOKED"
    assert appt["version"] == 1


def test_confirm_then_cancel_refunds_full_deposit(api):
    """PRD §3.4: "a SalonOwner or FrontDesk operator advances an appointment from
    BOOKED to CONFIRMED, permitted only while the appointment is in BOOKED and
    its client is not ARCHIVED."
    PRD §3.4: "Cancellation sets the appointment to CANCELLED and reverses the
    booking's holds: the full deposit_held_cents is refunded into the client's
    wallet_credit_cents."

    Design: Corner/state_machines/confirm_then_cancel_confirmed_appointment_refunds_deposit
    """
    base = setup_bookable_salon(
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.5},
    )
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    appt, _ = book_appointment(sid, base["client"]["id"], stylist,
                               base["resources"][0]["id"], base["service"]["id"],
                               "2026-07-01T13:00:00Z")
    get_success_data(api.confirm_appointment(appt["id"], FRONT))
    cancelled = get_success_data(api.cancel_appointment(appt["id"], FRONT))
    assert cancelled["status"] == "CANCELLED"
    client_data = get_success_data(api.get_client(base["client"]["id"], OWNER))
    assert client_data["wallet_credit_cents"] == 2500


# =========================================================================== #
# Corner — cross_cutting_complexity_layers: wallet reconciliation
# =========================================================================== #
def test_wallet_credit_reconciles_after_noshow_partial_forfeit(api):
    """PRD §3.4: "The forfeit is computed as the quoted price multiplied by the
    salon's no_show_fee_pct, rounded half up to whole cents; the salon actually
    forfeits the smaller of that fee and the held deposit, and the remainder of
    the deposit (the held deposit minus the amount forfeited) is refunded into
    the client's wallet_credit_cents."

    Design: Corner/cross_cutting_complexity_layers/wallet_credit_reconciles_after_noshow_partial_forfeit
    """
    salon = create_salon(name="S", no_show_fee_pct=0.30, no_show_suspend_threshold=3)
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Color", duration_minutes=60,
                             base_price_cents=10000, deposit_pct=0.5)
    client = create_client(salon["id"], full_name="C1", email="wc@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt = get_success_data(api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    ))
    # deposit_held = round_half_up(10000 * 0.5) = 5000.
    assert appt["deposit_held_cents"] == 5000
    advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appt["id"], FRONT))
    client_data = get_success_data(api.get_client(client["id"], OWNER))
    # forfeit = round_half_up(10000 * 0.30) = 3000; refund = 5000 - 3000 = 2000.
    assert client_data["wallet_credit_cents"] == 2000
    assert client_data["no_show_strikes"] == 1
