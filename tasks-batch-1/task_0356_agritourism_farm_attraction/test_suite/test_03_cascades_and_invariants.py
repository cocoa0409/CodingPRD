"""Transitive closure cascades, group-confirm seat commitment, and conservation
invariants.

Covers the depth-3 weather-closure cascade (farm -> window -> reservation ->
wallet/refund), the depth-2 group-confirm seat commit to SOLD_OUT, the
create-then-cancel seat conservation identity, and the refund-ledger mirror.
"""
from test_helpers import validate_success
from test_helpers import fixtures as fx
from test_helpers.test_users import make_visitor_headers


# ===========================================================================
# Queue A — transitive_cascade / depth-3 closure cascade
# ===========================================================================

def test_closure_cascade_cancels_window_and_reservation(api):
    """PRD §3.6: "every admission window on the farm whose `starts_at` falls
    inside the closure's affected span and whose `status` is not already
    `CANCELLED` is moved to `CANCELLED`."
    PRD §3.6: "every reservation on that window in `PENDING` or `CONFIRMED`
    status is moved to `CANCELLED` with closure as the cause".
    PRD §3.6: "The farm's `operational_status` moves to `CLOSED` and
    `active_weather_event_id` is set to the new event."

    Design: Difficulty/transitive_cascade/closure_cascade_depth3_farm_window_reservation_wallet
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Storm Farm", parking_fee_cents=1000)
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=10)
    visitor = fx.create_visitor(email="pass@x.com", full_name="Paula Pass")
    res = fx.create_confirmed_reservation(window["id"], visitor["id"], window["version"],
                                          adult_count=2, child_count=1)

    fx.declare_closure(farm["id"])

    farm_after = validate_success(api.get_farm(farm["id"], fx.MANAGER))
    assert farm_after["operational_status"] == "CLOSED"
    win_after = validate_success(api.get_admission_window(window["id"], fx.MANAGER))
    assert win_after["status"] == "CANCELLED"
    res_after = validate_success(api.get_reservation(res["id"], fx.MANAGER))
    assert res_after["status"] == "CANCELLED"


def test_closure_cascade_credits_wallet_and_refund_ledger(api):
    """PRD §3.6: "the visitor's `wallet_credit_cents` is increased by the
    reservation's `admission_charge_cents`; and the farm's `refunds_issued_cents`
    is increased by that same `admission_charge_cents`."

    Design: Difficulty/transitive_cascade/closure_cascade_depth3_farm_window_reservation_wallet
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Storm Farm", parking_fee_cents=1000)
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=10)
    visitor = fx.create_visitor(email="pass@x.com", full_name="Paula Pass")
    # 2 adults + 1 child, no pass -> admission 5200.
    fx.create_confirmed_reservation(window["id"], visitor["id"], window["version"],
                                    adult_count=2, child_count=1)

    fx.declare_closure(farm["id"])

    visitor_after = validate_success(api.get_visitor(visitor["id"], fx.MANAGER))
    assert visitor_after["wallet_credit_cents"] == 5200, (
        f"closure must credit wallet by admission 5200, got {visitor_after['wallet_credit_cents']}"
    )
    farm_after = validate_success(api.get_farm(farm["id"], fx.MANAGER))
    assert farm_after["refunds_issued_cents"] == 5200, (
        f"closure must bump refunds_issued_cents by 5200, got {farm_after['refunds_issued_cents']}"
    )


# ===========================================================================
# Queue A — transitive_cascade / depth-2 group confirm to SOLD_OUT
# ===========================================================================

def test_group_confirm_commits_seats(api):
    """PRD §3.7: "A successful confirm moves the booking `QUOTED → CONFIRMED`,
    locks the `deposit_cents` at the ceiling of `quoted_total_cents` multiplied
    by one quarter (the non-refundable deposit is rounded up so it is never under
    a quarter of the quote), adds `headcount` to the window's `seats_committed`,
    recomputes `seats_available`, flips the window to `SOLD_OUT` if availability
    reaches 0, and increments the window's `version` by one."

    Design: Difficulty/transitive_cascade/group_confirm_cascade_depth2_seats_then_soldout
    """
    farm = fx.create_farm(name="Block Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=10)
    leader = fx.create_visitor(email="blk@x.com", full_name="Bea Block")
    group = fx.create_group(farm["id"], window["id"], leader["id"], "FIELD_TRIP",
                            adult_count=4, child_count=6)

    confirmed = fx.confirm_group(group["id"], leader["id"], window["version"])
    assert confirmed["status"] == "CONFIRMED"

    win_after = validate_success(api.get_admission_window(window["id"], fx.MANAGER))
    assert win_after["seats_committed"] == 10, (
        f"group of 10 must commit 10 seats, got {win_after['seats_committed']}"
    )


def test_group_confirm_drives_window_sold_out(api):
    """PRD §3.7: "flips the window to `SOLD_OUT` if availability reaches 0".
    PRD §3.1: "It flips to `SOLD_OUT` the moment a reservation create or confirm
    drives its `seats_available` to exactly 0".

    Design: Difficulty/transitive_cascade/group_confirm_cascade_depth2_seats_then_soldout
    """
    farm = fx.create_farm(name="SoldOut Block Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=10)
    leader = fx.create_visitor(email="blk2@x.com", full_name="Ben Block")
    group = fx.create_group(farm["id"], window["id"], leader["id"], "FIELD_TRIP",
                            adult_count=4, child_count=6)

    fx.confirm_group(group["id"], leader["id"], window["version"])

    win_after = validate_success(api.get_admission_window(window["id"], fx.MANAGER))
    assert win_after["seats_available"] == 0
    assert win_after["status"] == "SOLD_OUT", "window must flip SOLD_OUT when availability hits 0"


# ===========================================================================
# Queue A — compensating_invariant / seat conservation
# ===========================================================================

def test_seat_conservation_create_then_cancel(api):
    """PRD §3.3: "Cancellation releases the inventory the reservation was
    holding: if the reservation was `PENDING`, `participant_count` is subtracted
    from `seats_held`".
    PRD §3.3: "Available seats are the window's `capacity` less held less
    committed, floored at 0 so the figure is never negative."

    Design: Difficulty/compensating_invariant/seat_conservation_create_then_cancel
    """
    s = fx.setup_farm_with_visitor(capacity=10)
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=2, child_count=1)

    cancelled = fx.cancel_reservation(res["id"], s["visitor"]["id"])
    assert cancelled["status"] == "CANCELLED"

    win_after = validate_success(api.get_admission_window(s["window"]["id"], fx.MANAGER))
    assert win_after["seats_held"] == 0
    assert win_after["seats_committed"] == 0
    assert win_after["seats_available"] == 10, (
        f"create+cancel must restore seats_available to 10, got {win_after['seats_available']}"
    )


def test_seat_conservation_no_drift_over_repeated_cycles(api):
    """PRD §3.3: "in either case `seats_available` is recomputed and a `SOLD_OUT`
    window flips back to `SCHEDULED` once availability exceeds 0."
    PRD §3.3: "Available seats are the window's `capacity` less held less
    committed, floored at 0 so the figure is never negative."

    Design: Difficulty/compensating_invariant/seat_conservation_create_then_cancel
    """
    s = fx.setup_farm_with_visitor(capacity=10)
    headers = make_visitor_headers(s["visitor"]["id"])
    for _ in range(4):
        v = fx.window_version(s["window"]["id"])
        res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"], v,
                                            adult_count=2, child_count=1)
        fx.cancel_reservation(res["id"], s["visitor"]["id"])

    win_after = validate_success(api.get_admission_window(s["window"]["id"], headers))
    assert win_after["seats_held"] == 0
    assert win_after["seats_available"] == 10, (
        f"repeated create+cancel must not drift the seat ledger, got {win_after['seats_available']}"
    )


# ===========================================================================
# Queue A — compensating_invariant / refund-ledger mirror
# ===========================================================================

def test_refund_ledger_mirrors_summed_wallet_credits(api):
    """PRD §3.6: "the visitor's `wallet_credit_cents` is increased by the
    reservation's `admission_charge_cents`; and the farm's `refunds_issued_cents`
    is increased by that same `admission_charge_cents`."

    Design: Difficulty/compensating_invariant/refund_ledger_mirror_wallet_equals_farm_refunds
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Ledger Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=10)
    va = fx.create_visitor(email="la@x.com", full_name="Lena A")
    vb = fx.create_visitor(email="lb@x.com", full_name="Leo B")

    # Reservation A: 2 adult 1 child -> admission 5200.
    fx.create_confirmed_reservation(window["id"], va["id"], window["version"],
                                    adult_count=2, child_count=1)
    # Reservation B: 1 adult -> admission 2000 (fresh version after A's commit).
    v_after_a = fx.window_version(window["id"])
    fx.create_confirmed_reservation(window["id"], vb["id"], v_after_a,
                                    adult_count=1, child_count=0)

    fx.declare_closure(farm["id"])

    va_after = validate_success(api.get_visitor(va["id"], fx.MANAGER))
    vb_after = validate_success(api.get_visitor(vb["id"], fx.MANAGER))
    farm_after = validate_success(api.get_farm(farm["id"], fx.MANAGER))

    assert va_after["wallet_credit_cents"] == 5200
    assert vb_after["wallet_credit_cents"] == 2000
    # Farm ledger mirrors the sum of all closure-credited wallets with no drift.
    assert farm_after["refunds_issued_cents"] == 7200, (
        f"farm refund ledger must equal summed wallet credits (7200), got {farm_after['refunds_issued_cents']}"
    )
    assert farm_after["refunds_issued_cents"] == (
        va_after["wallet_credit_cents"] + vb_after["wallet_credit_cents"]
    )


def test_self_cancel_does_not_credit_wallet(api):
    """PRD §3.3: "A self-initiated cancellation does not credit the visitor's
    wallet — only a weather closure credits, per §3.6."

    Design: Difficulty/compensating_invariant/refund_ledger_mirror_wallet_equals_farm_refunds
    """
    s = fx.setup_farm_with_visitor(capacity=10)
    res = fx.create_confirmed_reservation(s["window"]["id"], s["visitor"]["id"],
                                          s["window"]["version"], adult_count=2, child_count=1)
    fx.cancel_reservation(res["id"], s["visitor"]["id"])

    visitor_after = validate_success(api.get_visitor(s["visitor"]["id"], fx.MANAGER))
    assert visitor_after["wallet_credit_cents"] == 0, (
        "self-cancel must not credit the wallet (only weather closures credit)"
    )
    farm_after = validate_success(api.get_farm(s["farm"]["id"], fx.MANAGER))
    assert farm_after["refunds_issued_cents"] == 0
