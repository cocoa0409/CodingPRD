"""Session-charge calculation: forward estimate vs final actual, the combinatorial
min/prepaid/discount nesting, and the wallet/prepaid conservation invariants.

Every test reaches a confirmed/checked-out reservation through API calls only;
the server is restarted before each test, so all preconditions are built here.
"""
from test_helpers import (
    validate_success,
    setup_member_machine_cert,
    setup_confirmed_reservation,
    create_held_reservation,
    confirm_reservation,
    set_clock,
    make_member_headers,
)

# A MAKER monthly tier with a 10% machine-time discount and no prepaid minutes;
# a LASER charging 4800c/hr with a 500c setup fee, 30-min floor, 15-min cooldown.
MAKER_TIER = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 0, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}
LASER_MACHINE = {
    "machine_class": "LASER", "hourly_rate_cents": 4800, "setup_fee_cents": 500,
    "min_billing_minutes": 30, "cooldown_minutes": 15, "requires_certification": True,
}
PRO_TIER = {
    "code": "PRO", "name": "Pro", "billing_mode": "MONTHLY", "monthly_fee_cents": 0,
    "discount_bps": 2000, "prepaid_machine_minutes": 60, "locker_free_liters": 100,
    "unsupervised_allowed": True,
}
CNC_MACHINE = {
    "machine_class": "CNC", "hourly_rate_cents": 9000, "setup_fee_cents": 1500,
    "min_billing_minutes": 60, "cooldown_minutes": 30, "requires_certification": True,
}


# ===========================================================================
# dual_variant_calc / session_charge_estimate_vs_final_on_reservation
# ===========================================================================
def test_confirm_writes_forward_estimate_charge(api):
    """PRD §3.11: "The basis is the reserved-window length, `reserved_minutes`, in
    the forward estimate variant used at confirm, and the real occupancy length,
    `actual_minutes`, in the final variant used at check-out."
    PRD §3.6: "On a successful confirm the server computes `estimate_charge_cents`
    via the **forward** variant of the session-charge calculation in §3.10 on the
    reserved-window basis, records the `free_minutes_applied` it consumed, debits
    `wallet_credit_cents` by `estimate_charge_cents`, moves `billing_status` to
    `HOLD_PLACED`."

    A 90-min reserved LASER window at 4800c/hr with a 10% time discount and a 500c
    setup fee yields estimate_charge_cents == 6980 (90*4800/60=7200, *0.9=6480, +500).

    Design: Difficulty/dual_variant_calc/session_charge_estimate_vs_final_on_reservation
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-04-10T10:00:00Z", end_at="2026-04-10T11:30:00Z",
    )
    assert res["estimate_charge_cents"] == 6980, res["estimate_charge_cents"]
    assert res["billing_status"] == "HOLD_PLACED"


def test_checkout_writes_final_charge_distinct_from_estimate(api):
    """PRD §3.6: "Checking out moves the reservation from `CHECKED_IN` to
    `COMPLETED`. It stamps `check_out_at` with the clock now, computes
    `actual_minutes` as the whole minutes from `check_in_at` to `check_out_at`, and
    computes `final_charge_cents` via the **final** variant of the session-charge
    calculation on the actual-minutes basis."

    Same LASER: 90-min reserved (estimate 6980) but only 45 actual minutes used
    yields final_charge_cents == 3740 (45*4800/60=3600, *0.9=3240, +500), distinct
    from the estimate; billing settles.

    Design: Difficulty/dual_variant_calc/session_charge_estimate_vs_final_on_reservation
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-04-10T10:00:00Z", end_at="2026-04-10T11:30:00Z",
    )
    mh = make_member_headers(member["id"])
    set_clock("2026-04-10T10:05:00Z")
    validate_success(api.check_in(res["id"], mh))
    set_clock("2026-04-10T10:50:00Z")
    out = validate_success(api.check_out(res["id"], mh))
    assert out["estimate_charge_cents"] == 6980, out["estimate_charge_cents"]
    assert out["final_charge_cents"] == 3740, out["final_charge_cents"]
    assert out["estimate_charge_cents"] != out["final_charge_cents"]
    assert out["billing_status"] == "SETTLED"


# ===========================================================================
# combinatorial_formula / session_charge_nonlinear_min_prepaid_discount
# ===========================================================================
def test_session_charge_nests_min_then_prepaid_then_discount(api):
    """PRD §3.11: "The billable minutes are the greater of the basis minutes and
    the machine's `min_billing_minutes`. The free minutes are the lesser of the
    billable minutes and the member's `prepaid_minutes_remaining`, and the charged
    minutes are the billable minutes less the free minutes."

    PRO tier (60 prepaid, 20% discount) on a CNC (9000c/hr, 1500 setup, 60-min
    floor) for a 120-min reserve: billable 120, free 60, charged 60 ->
    60*9000/60=9000, *0.8=7200, +1500 setup = 8700c.

    Design: Difficulty/combinatorial_formula/session_charge_nonlinear_min_prepaid_discount
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="CNC", tier_overrides=PRO_TIER, machine_overrides=CNC_MACHINE,
        topup_cents=20000,
    )
    res = create_held_reservation(
        member, machine, cert, "2026-04-10T09:00:00Z", "2026-04-10T11:00:00Z"
    )
    confirmed = confirm_reservation(res["id"], member["id"])
    assert confirmed["estimate_charge_cents"] == 8700, confirmed["estimate_charge_cents"]
    assert confirmed["free_minutes_applied"] == 60, confirmed["free_minutes_applied"]


def test_session_charge_consumes_prepaid_minutes(api):
    """PRD §3.6: "On a successful confirm the server computes `estimate_charge_cents`
    via the **forward** variant ... records the `free_minutes_applied` it consumed,
    debits `wallet_credit_cents` by `estimate_charge_cents`, moves `billing_status`
    to `HOLD_PLACED`, decrements `prepaid_minutes_remaining` by `free_minutes_applied`."

    The PRO member's 60 prepaid minutes are entirely consumed by the 120-min CNC
    reservation, leaving prepaid_minutes_remaining == 0 after confirm.

    Design: Difficulty/combinatorial_formula/session_charge_nonlinear_min_prepaid_discount
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="CNC", tier_overrides=PRO_TIER, machine_overrides=CNC_MACHINE,
        topup_cents=20000,
    )
    res = create_held_reservation(
        member, machine, cert, "2026-04-10T09:00:00Z", "2026-04-10T11:00:00Z"
    )
    confirm_reservation(res["id"], member["id"])
    mh = make_member_headers(member["id"])
    refreshed = validate_success(api.get_member(member["id"], mh))
    assert refreshed["prepaid_minutes_remaining"] == 0, refreshed["prepaid_minutes_remaining"]


# ===========================================================================
# compensating_invariant / wallet_credit_conserved_on_confirm_then_cancel
# ===========================================================================
def test_wallet_restored_to_preconfirm_balance_after_cancel(api):
    """PRD §3.6: "if a hold was in place — that is, if `billing_status` is
    `HOLD_PLACED` — the cancellation refunds `wallet_credit_cents` by
    `estimate_charge_cents`, restores `prepaid_minutes_remaining` by
    `free_minutes_applied`, moves `billing_status` to `REFUNDED`, and appends a
    `WalletEntry` of kind `REFUND` carrying the estimate and the `reservation_id`."

    A 60-min LASER reserve estimates 4820 (60*4800/60=4800, *0.9=4320, +500);
    confirm debits it from a 10000 wallet, cancel refunds the identical amount,
    returning the wallet to exactly 10000.

    Design: Difficulty/compensating_invariant/wallet_credit_conserved_on_confirm_then_cancel
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-05-02T10:00:00Z", end_at="2026-05-02T11:00:00Z",
    )
    assert res["estimate_charge_cents"] == 4820, res["estimate_charge_cents"]
    mh = make_member_headers(member["id"])
    cancelled = validate_success(api.cancel_reservation(res["id"], mh))
    assert cancelled["billing_status"] == "REFUNDED"
    after = validate_success(api.get_member(member["id"], mh))
    assert after["wallet_credit_cents"] == 10000, after["wallet_credit_cents"]


def test_cancel_sets_billing_status_refunded(api):
    """PRD §3.6: "A member may **cancel** a reservation that is `HELD` or
    `CONFIRMED`. Cancellation moves `occupancy_status` to `CANCELLED`; if a hold
    was in place — that is, if `billing_status` is `HOLD_PLACED` — the cancellation
    refunds `wallet_credit_cents` by `estimate_charge_cents` ... moves
    `billing_status` to `REFUNDED`."

    Design: Difficulty/compensating_invariant/wallet_credit_conserved_on_confirm_then_cancel
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-05-02T10:00:00Z", end_at="2026-05-02T11:00:00Z",
    )
    mh = make_member_headers(member["id"])
    cancelled = validate_success(api.cancel_reservation(res["id"], mh))
    assert cancelled["occupancy_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "REFUNDED"


# ===========================================================================
# compensating_invariant / prepaid_minutes_conserved_on_confirm_then_release
# ===========================================================================
def test_prepaid_minutes_restored_after_release_hold(api):
    """PRD §3.6: "Releasing refunds `wallet_credit_cents` by `estimate_charge_cents`,
    sets `billing_status` back to `UNBILLED`, restores `prepaid_minutes_remaining` by
    `free_minutes_applied`, resets `free_minutes_applied` to 0, and appends a
    `WalletEntry` of kind `REFUND` with a positive `amount_cents` equal to the
    estimate and the reservation's `reservation_id`."

    PRO member (60 prepaid) confirms a 120-min CNC reserve consuming 60 free
    minutes (prepaid -> 0), then release-hold restores prepaid_minutes_remaining
    back to exactly 60.

    Design: Difficulty/compensating_invariant/prepaid_minutes_conserved_on_confirm_then_release
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="CNC", tier_overrides=PRO_TIER, machine_overrides=CNC_MACHINE,
        topup_cents=20000,
    )
    res = create_held_reservation(
        member, machine, cert, "2026-05-03T09:00:00Z", "2026-05-03T11:00:00Z"
    )
    confirmed = confirm_reservation(res["id"], member["id"])
    assert confirmed["free_minutes_applied"] == 60, confirmed["free_minutes_applied"]
    mh = make_member_headers(member["id"])
    after_confirm = validate_success(api.get_member(member["id"], mh))
    assert after_confirm["prepaid_minutes_remaining"] == 0, after_confirm["prepaid_minutes_remaining"]
    validate_success(api.release_hold(res["id"], mh))
    after_release = validate_success(api.get_member(member["id"], mh))
    assert after_release["prepaid_minutes_remaining"] == 60, after_release["prepaid_minutes_remaining"]


def test_release_hold_resets_billing_to_unbilled(api):
    """PRD §3.6: "Before the window opens, a member may **release the hold**, moving
    the reservation from `CONFIRMED` back to `HELD`. ... Releasing refunds
    `wallet_credit_cents` by `estimate_charge_cents`, sets `billing_status` back to
    `UNBILLED`, restores `prepaid_minutes_remaining` by `free_minutes_applied`,
    resets `free_minutes_applied` to 0."

    After release-hold the reservation is HELD again with billing_status UNBILLED.

    Design: Difficulty/compensating_invariant/prepaid_minutes_conserved_on_confirm_then_release
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="CNC", tier_overrides=PRO_TIER, machine_overrides=CNC_MACHINE,
        topup_cents=20000,
    )
    res = create_held_reservation(
        member, machine, cert, "2026-05-03T09:00:00Z", "2026-05-03T11:00:00Z"
    )
    confirm_reservation(res["id"], member["id"])
    mh = make_member_headers(member["id"])
    released = validate_success(api.release_hold(res["id"], mh))
    assert released["occupancy_status"] == "HELD"
    assert released["billing_status"] == "UNBILLED"
