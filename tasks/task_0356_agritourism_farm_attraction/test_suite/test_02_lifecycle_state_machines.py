"""Non-linear state machines and cross-entity state dependencies.

Covers the reservation fork-join settle gate, the group revise/requote cycle,
and the two cross-entity gates (reservation confirm depends on farm posture;
check-in depends on the window not being closure-cancelled).
"""
from test_helpers import validate_success, validate_error, validate_error_is_one_of, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.test_users import make_visitor_headers, make_group_leader_headers
from test_helpers.api_client import api_client

GATE = fx.GATE


# ===========================================================================
# Queue A — non_linear_state_machine / reservation fork-join
# ===========================================================================

def test_settle_rejected_while_pumpkin_still_estimated(api):
    """PRD §3.4: "A settle attempted while a pumpkin is still `ESTIMATED` or
    while the waiver is not satisfied — that is, before the join condition is met
    — is rejected with `ERR_CHECKOUT_NOT_FINALIZED`."

    Design: Difficulty/non_linear_state_machine/reservation_forkjoin_settle_requires_both_legs
    """
    s = fx.setup_checked_in(capacity=10, adult_count=1, child_count=0)
    res = s["reservation"]
    # Add a pumpkin and leave it ESTIMATED (weigh-out leg open).
    fx.add_pumpkin(res["id"], s["visitor"]["id"], estimated_weight_lb=12)

    resp = api.settle_reservation(res["id"], GATE)
    validate_error(resp, ApiErrorId.ERR_CHECKOUT_NOT_FINALIZED.value)

    after = validate_success(api.get_reservation(res["id"], GATE))
    assert after["status"] == "CHECKED_IN", "reservation must stay CHECKED_IN after the rejected settle"


def test_settle_succeeds_once_both_legs_complete(api):
    """PRD §3.4: "A `GateAgent` settles a `CHECKED_IN` reservation, which is
    permitted only when both legs are complete: `checkout_finalized` is true
    (every pumpkin is `WEIGHED`, or there are none) and `waiver_satisfied` is
    true."

    Design: Difficulty/non_linear_state_machine/reservation_forkjoin_settle_requires_both_legs
    """
    s = fx.setup_checked_in(capacity=10, adult_count=1, child_count=0)
    res = s["reservation"]
    pk = fx.add_pumpkin(res["id"], s["visitor"]["id"], estimated_weight_lb=12)
    # Finalize the weigh-out leg; the waiver leg was already satisfied at check-in.
    fx.weigh_out(pk["id"], scale_weight_lb=12)

    settled = validate_success(api.settle_reservation(res["id"], GATE))
    assert settled["status"] == "SETTLED", "settle must succeed once both legs join"


# ===========================================================================
# Queue A — non_linear_state_machine / group cyclic revise loop
# ===========================================================================

def test_group_revise_requote_recomputes_quote(api):
    """PRD §3.7: "The leader may open a `QUOTED` booking for editing, moving it
    `QUOTED → REVISING`; from `REVISING` the leader may edit the headcount and
    kind, then requote to move it `REVISING → QUOTED`, which recomputes
    `quoted_total_cents` from the updated figures."

    Design: Difficulty/non_linear_state_machine/group_booking_cyclic_revise_requote_loop
    """
    farm = fx.create_farm(name="Cycle Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=50)
    leader = fx.create_visitor(email="cyc@x.com", full_name="Cy Cycle")

    group = fx.create_group(farm["id"], window["id"], leader["id"], "FIELD_TRIP",
                            adult_count=4, child_count=8)
    # 4*2000 + 8*1200 = 17600; headcount 12 < 15 -> no discount.
    assert group["quoted_total_cents"] == 17600

    fx.revise_group(group["id"], leader["id"])
    fx.edit_group(group["id"], leader["id"], adult_count=5, child_count=25)
    requoted = fx.requote_group(group["id"], leader["id"])

    # 5*2000 + 25*1200 = 40000; headcount 30 >= 15, FIELD_TRIP -> 0.20.
    # round_half_up(40000 * 0.80) = 32000.
    assert requoted["quoted_total_cents"] == 32000, (
        f"requote should recompute to 32000, got {requoted['quoted_total_cents']}"
    )
    assert requoted["status"] == "QUOTED"


def test_group_revise_returns_to_revising_status(api):
    """PRD §3.7: "The leader may open a `QUOTED` booking for editing, moving it
    `QUOTED → REVISING`".

    Design: Difficulty/non_linear_state_machine/group_booking_cyclic_revise_requote_loop
    """
    farm = fx.create_farm(name="Revise Status Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=50)
    leader = fx.create_visitor(email="rev@x.com", full_name="Rae Revise")

    group = fx.create_group(farm["id"], window["id"], leader["id"], "FIELD_TRIP",
                            adult_count=4, child_count=8)
    assert group["status"] == "QUOTED"

    revising = fx.revise_group(group["id"], leader["id"])
    assert revising["status"] == "REVISING", "revise must move QUOTED -> REVISING"


# ===========================================================================
# Queue A — cross_entity_state_dependency / confirm depends on farm posture
# ===========================================================================

def test_reservation_confirm_blocked_during_weather_hold(api):
    """PRD §3.3: "Confirmation is permitted only on a `PENDING` reservation whose
    owning farm is `OPEN` and whose window is not `CANCELLED`".
    PRD §3.3: "A confirm against a farm that is not `OPEN` is rejected with
    `ERR_FARM_NOT_OPEN`".

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_blocked_when_farm_weather_hold
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=1, child_count=0)
    fx.declare_hold(s["farm"]["id"], note="Lightning in area")

    resp = api.confirm_reservation(res["id"], make_visitor_headers(s["visitor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FARM_NOT_OPEN.value)

    after = validate_success(api.get_reservation(res["id"], make_visitor_headers(s["visitor"]["id"])))
    assert after["status"] == "PENDING", "reservation must stay PENDING when confirm is blocked"
    farm = validate_success(api.get_farm(s["farm"]["id"], fx.MANAGER))
    assert farm["operational_status"] == "WEATHER_HOLD"


def test_reservation_confirm_succeeds_when_farm_open(api):
    """PRD §3.3: "Confirmation moves the reservation `PENDING → CONFIRMED`".
    PRD §3.3: "Confirmation is permitted only on a `PENDING` reservation whose
    owning farm is `OPEN` and whose window is not `CANCELLED`".

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_blocked_when_farm_weather_hold
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=1, child_count=0)

    confirmed = validate_success(
        api.confirm_reservation(res["id"], make_visitor_headers(s["visitor"]["id"])))
    assert confirmed["status"] == "CONFIRMED", "confirm must succeed while the farm is OPEN"


# ===========================================================================
# Queue A — cross_entity_state_dependency / check-in depends on window status
# ===========================================================================

def test_checkin_blocked_after_closure_cancelled_window(api):
    """PRD §3.6: "every reservation on that window in `PENDING` or `CONFIRMED`
    status is moved to `CANCELLED` with closure as the cause".
    PRD §3.4: "Checking a reservation in is permitted only on a `CONFIRMED`
    reservation, only while the owning farm is `OPEN` or under a `WEATHER_HOLD`
    (a hold does not block check-in, but a `CLOSED` farm does), only when the
    window is not `CANCELLED`...". "A transition attempted from a status other
    than `CONFIRMED` is rejected with `ERR_INVALID_STATE`."

    A closure cascade simultaneously sets the farm `CLOSED`, the window
    `CANCELLED`, and the reservation `CANCELLED`. The check-in prose lists these
    three eligibility conditions without pinning a precedence among them, so a
    PRD-faithful implementer may report whichever guard it evaluates first:
    `ERR_FARM_NOT_OPEN` (farm CLOSED), `ERR_INVALID_STATE` (reservation not
    CONFIRMED), or `ERR_WINDOW_CANCELLED` (window CANCELLED) are all admissible.

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_window_cancelled
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Cancel Window Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=5)
    visitor = fx.create_visitor(email="cw@x.com", full_name="Cleo Window")
    res = fx.create_confirmed_reservation(window["id"], visitor["id"], window["version"],
                                          adult_count=1, child_count=0)

    fx.declare_closure(farm["id"])

    resp = api.check_in_reservation(res["id"], GATE)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_INVALID_STATE.value,
        ApiErrorId.ERR_FARM_NOT_OPEN.value,
        ApiErrorId.ERR_WINDOW_CANCELLED.value,
    ])

    win_after = validate_success(api.get_admission_window(window["id"], fx.MANAGER))
    assert win_after["status"] == "CANCELLED"
    res_after = validate_success(api.get_reservation(res["id"], GATE))
    assert res_after["status"] == "CANCELLED", "closure cascade must cancel the confirmed reservation"


def test_checkin_succeeds_on_active_window(api):
    """PRD §3.4: "Check-in moves the reservation `CONFIRMED → CHECKED_IN`,
    recomputes and locks the `settled_charge_cents` (the settled pricing variant
    of §3.5), recomputes `waiver_satisfied`, and opens the fork".

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_window_cancelled
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    res = fx.create_confirmed_reservation(s["window"]["id"], s["visitor"]["id"],
                                          s["window"]["version"], adult_count=1, child_count=0)
    fx.sign_waiver(res["id"], s["visitor"]["id"], "Solo Guest")

    checked_in = validate_success(api.check_in_reservation(res["id"], GATE))
    assert checked_in["status"] == "CHECKED_IN", "check-in must succeed on a non-cancelled window"
