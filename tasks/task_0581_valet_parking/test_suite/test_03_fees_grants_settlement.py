"""Parking-fee variants, the daily cap, the grace boundary, validation grants and the net
charge, and checkout state/time gates."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_damage_claim_payload, create_validation_payload,
)
from test_helpers.fixtures import (
    setup_active_event_env, setup_checked_in_ticket, setup_settled_ticket,
    setup_overflow_scene, check_in, checkout, apply_grant,
)

SUP = TEST_USERS["supervisor_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def test_quoted_fee_computed_at_checkin(api):
    """PRD §3.5: "The quoted fee is computed from the estimated stay, that is, the duration in
    minutes from `checkin_at` to `estimated_departure_at`."
    PRD §3.5: "Otherwise the number of billable hours is the duration in minutes divided by 60
    and rounded up to the next whole hour; the metered component is the lesser of those hours
    multiplied by `hourly_rate_cents` and the event's `daily_max_cents` cap; the event's flat
    `event_surcharge_cents` is then added on top of the capped metered component".

    Design: Difficulty/dual_variant_calc/parking_fee_quoted_vs_final_on_ticket
    """
    # checkin 10:00 → est 12:00 = 120 min: ceil(120/60)=2h × 800 = 1600 (< 2500 cap) + 500 = 2100.
    env = setup_checked_in_ticket()
    assert env["ticket"]["quoted_fee_cents"] == 2100


def test_final_fee_diverges_from_quoted_at_checkout(api):
    """PRD §3.7: "The final fee uses exactly the same tiered formula as the quoted fee in §3.5
    ... but its duration is the chronological actual stay, the minutes from `checkin_at` to the
    supplied `checkout_at`, so it diverges from the quoted figure whenever the actual departure
    differs from the estimate."

    Design: Difficulty/dual_variant_calc/parking_fee_quoted_vs_final_on_ticket
    """
    # actual 10:00 → 12:30 = 150 min: ceil(150/60)=3h × 800 = 2400 (< 2500 cap) + 500 = 2900.
    env = setup_checked_in_ticket()
    ticket = checkout(env["ticket"]["id"], checkout_at="2026-06-01T12:30:00Z")
    assert ticket["final_fee_cents"] == 2900
    assert ticket["final_fee_cents"] != ticket["quoted_fee_cents"]


def test_daily_cap_applied_before_surcharge_on_final_fee(api):
    """PRD §3.7: "the metered hours (rounded up) times the hourly rate, capped by the daily
    maximum, plus the flat event surcharge, plus the overflow surcharge when the ticket is in
    overflow".
    PRD §3.5: "the metered component is the lesser of those hours multiplied by
    `hourly_rate_cents` and the event's `daily_max_cents` cap; the event's flat
    `event_surcharge_cents` is then added on top of the capped metered component".

    Design: Difficulty/combinatorial_formula/final_fee_daily_cap_then_surcharge_mode_a
    """
    # 10:00 → 13:30 = 210 min: ceil(210/60)=4h × 800 = 3200, capped to 2500, + 500 = 3000.
    env = setup_active_event_env()
    ticket = check_in(env["event"]["id"], env["lot"]["id"], env["attendant"]["id"],
                      expected_lot_version=env["lot"]["version"],
                      estimated_departure_at="2026-06-01T13:30:00Z", license_plate="CAP1")
    settled = checkout(ticket["id"], checkout_at="2026-06-01T13:30:00Z")
    assert settled["final_fee_cents"] == 3000


def test_daily_cap_applied_to_quoted_fee(api):
    """PRD §3.5: "the metered component is the lesser of those hours multiplied by
    `hourly_rate_cents` and the event's `daily_max_cents` cap; the event's flat
    `event_surcharge_cents` is then added on top of the capped metered component".

    Design: Difficulty/combinatorial_formula/final_fee_daily_cap_then_surcharge_mode_a
    """
    # quoted from est 10:00 → 13:30 = 210 min: 4h × 800 = 3200 capped to 2500 + 500 = 3000.
    env = setup_active_event_env()
    ticket = check_in(env["event"]["id"], env["lot"]["id"], env["attendant"]["id"],
                      expected_lot_version=env["lot"]["version"],
                      estimated_departure_at="2026-06-01T13:30:00Z", license_plate="CAP1")
    assert ticket["quoted_fee_cents"] == 3000


def test_grace_boundary_charges_zero(api):
    """PRD §3.5: "If that duration is at or below the event's `free_grace_minutes`, the fee
    is 0."

    Design: Difficulty/boundary_precision_check/grace_minute_boundary_on_checkout
    """
    # 10:00 → 10:15 = 15 min == free_grace_minutes (default 15) → fee 0.
    env = setup_active_event_env()
    ticket = check_in(env["event"]["id"], env["lot"]["id"], env["attendant"]["id"],
                      expected_lot_version=env["lot"]["version"], key_tag="K1", license_plate="G1")
    settled = checkout(ticket["id"], checkout_at="2026-06-01T10:15:00Z")
    assert settled["final_fee_cents"] == 0


def test_one_minute_over_grace_charged(api):
    """PRD §3.5: "Otherwise the number of billable hours is the duration in minutes divided by
    60 and rounded up to the next whole hour; the metered component is the lesser of those hours
    multiplied by `hourly_rate_cents` and the event's `daily_max_cents` cap; the event's flat
    `event_surcharge_cents` is then added on top of the capped metered component".

    Design: Difficulty/boundary_precision_check/grace_minute_boundary_on_checkout
    """
    # 10:00 → 10:16 = 16 min > 15 grace: ceil(16/60)=1h × 800 = 800 + 500 = 1300.
    env = setup_active_event_env()
    ticket = check_in(env["event"]["id"], env["lot"]["id"], env["attendant"]["id"],
                      expected_lot_version=env["lot"]["version"], key_tag="K2", license_plate="G2")
    settled = checkout(ticket["id"], checkout_at="2026-06-01T10:16:00Z")
    assert settled["final_fee_cents"] == 1300


def test_overflow_surcharge_added_to_final_fee(api):
    """PRD §3.7: "the metered hours (rounded up) times the hourly rate, capped by the daily
    maximum, plus the flat event surcharge, plus the overflow surcharge when the ticket is in
    overflow".
    PRD §3.2: "the ticket's `in_overflow` flag is set to true".

    Design: Corner/calculations/overflow_surcharge_added_to_final_fee
    """
    scene = setup_overflow_scene()
    assert scene["t2"]["in_overflow"] is True
    # t2: 10:05 → 11:05 = 60 min: 1h × 800 = 800 + 500 surcharge + 700 overflow = 2000.
    settled = checkout(scene["t2"]["id"], checkout_at="2026-06-01T11:05:00Z")
    assert settled["final_fee_cents"] == 2000


def test_percent_then_flat_net_charge_order_sensitive(api):
    """PRD §3.7: "A `FLAT` grant subtracts its `value` in cents from the running amount,
    flooring the result at 0 so it never goes negative. A `PERCENT` grant multiplies the
    running amount by one hundred minus its whole-percent `value`, divides by one hundred, and
    rounds the result half up to the nearest cent. The order of application matters, so grants
    are always evaluated oldest first."

    Design: Corner/calculations/validation_percent_then_flat_order_sensitive
    """
    env = setup_settled_ticket()  # final_fee 2900, net 2900
    apply_grant(env["ticket"]["id"], "PERCENT", value=25)   # round_half_up(2900*0.75)=2175
    apply_grant(env["ticket"]["id"], "FLAT", value=500)     # 2175 - 500 = 1675
    ticket = validate_success(api.get_ticket(env["ticket"]["id"], SUP), 200)
    assert ticket["net_charge_cents"] == 1675


def test_flat_grant_reverse_restores_net_charge(api):
    """PRD §3.7: "A `Cashier` may reverse a grant, which moves its `status` from `APPLIED` to
    `REVERSED` and again recomputes the ticket's `net_charge_cents` (now excluding the reversed
    grant)."

    Design: Difficulty/compensating_invariant/net_charge_conserved_grant_apply_reverse
    """
    env = setup_settled_ticket()  # final_fee 2900, net 2900
    grant = apply_grant(env["ticket"]["id"], "FLAT", value=500)  # net → 2400
    reversed_grant = validate_success(
        api.reverse_validation_grant(grant["id"], CASHIER), 200)
    assert reversed_grant["status"] == "REVERSED"
    ticket = validate_success(api.get_ticket(env["ticket"]["id"], SUP), 200)
    assert ticket["net_charge_cents"] == 2900


def test_flat_grant_apply_then_reverse_no_cent_drift(api):
    """PRD §3.7: "The grant's `status` starts `APPLIED`, and creating it immediately recomputes
    the ticket's `net_charge_cents` by the rule above."
    PRD §3.7: "A `FLAT` grant subtracts its `value` in cents from the running amount, flooring
    the result at 0 so it never goes negative."

    Design: Difficulty/compensating_invariant/net_charge_conserved_grant_apply_reverse
    """
    env = setup_settled_ticket()  # final_fee 2900, net 2900
    grant = apply_grant(env["ticket"]["id"], "FLAT", value=500)
    after_apply = validate_success(api.get_ticket(env["ticket"]["id"], SUP), 200)
    assert after_apply["net_charge_cents"] == 2400  # 2900 - 500
    validate_success(api.reverse_validation_grant(grant["id"], CASHIER), 200)
    after_reverse = validate_success(api.get_ticket(env["ticket"]["id"], SUP), 200)
    assert after_reverse["net_charge_cents"] == 2900
    assert after_reverse["net_charge_cents"] == after_reverse["final_fee_cents"]


def test_validation_on_disputed_ticket_rejected(api):
    """PRD §3.7: "Neither applying nor reversing a grant is allowed once the ticket's
    `settlement_status` is `DISPUTED`; such an attempt is rejected with
    `ERR_VALIDATION_NOT_APPLICABLE`."

    Design: Corner/validations/validation_on_disputed_ticket_not_applicable
    """
    env = setup_settled_ticket()
    claim = validate_success(api.create_damage_claim(
        create_damage_claim_payload(env["ticket"]["id"], description="post",
                                    claimed_amount_cents=500), CASHIER), 201)
    validate_success(api.approve_damage_claim(
        claim["id"], {"approved_liability_cents": 500}, SUP), 200)
    res = api.create_validation(
        env["ticket"]["id"], create_validation_payload("FLAT", value=100), CASHIER)
    validate_error(res, ApiErrorId.ERR_VALIDATION_NOT_APPLICABLE)


def test_reverse_already_reversed_grant_rejected(api):
    """PRD §3.7: "Reversing a grant already in `REVERSED` is rejected with
    `ERR_GRANT_ALREADY_REVERSED`."

    Design: Corner/validations/reverse_already_reversed_grant_returns_error
    """
    env = setup_settled_ticket()
    grant = apply_grant(env["ticket"]["id"], "FLAT", value=500)
    validate_success(api.reverse_validation_grant(grant["id"], CASHIER), 200)
    res = api.reverse_validation_grant(grant["id"], CASHIER)
    validate_error(res, ApiErrorId.ERR_GRANT_ALREADY_REVERSED)


def test_checkout_before_checkin_rejected(api):
    """PRD §3.7: "The `checkout_at` must be at or after the ticket's `checkin_at`, or the
    request is rejected with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/checkout_before_checkin_returns_invalid_time_window
    """
    env = setup_checked_in_ticket()  # checkin_at 10:00
    res = api.checkout_ticket(env["ticket"]["id"], {"checkout_at": "2026-06-01T09:00:00Z"}, CASHIER)
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW)


def test_recheckout_closed_ticket_with_open_claim_returns_invalid_state(api):
    """PRD §3.7: "Checkout is permitted from a `park_status` of either `PARKED` or `RETRIEVED`;
    from any other state it is rejected with `ERR_INVALID_STATE`."
    PRD §2.7: "(5) the target resource being in a state that permits the requested transition,
    failing with `ERR_INVALID_STATE` or one of its specialized forms; ... (8) the
    no-open-damage-claim safety gate at checkout, failing with `ERR_OPEN_DAMAGE_CLAIM`".

    Design: Difficulty/priority_pair_validation_conflict/closed_ticket_state_beats_open_claim_safety
    """
    env = setup_settled_ticket()  # ticket CLOSED
    validate_success(api.create_damage_claim(
        create_damage_claim_payload(env["ticket"]["id"], description="late-found dent",
                                    claimed_amount_cents=500), CASHIER), 201)
    res = api.checkout_ticket(env["ticket"]["id"], {"checkout_at": "2026-06-01T13:00:00Z"}, CASHIER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_checkout_parked_ticket_with_open_claim_returns_open_damage_claim(api):
    """PRD §3.7: "As a safety gate, a ticket that has any damage claim still in `OPEN` status
    cannot be checked out; the attempt is rejected with `ERR_OPEN_DAMAGE_CLAIM`."

    Design: Difficulty/priority_pair_validation_conflict/closed_ticket_state_beats_open_claim_safety
    """
    env = setup_checked_in_ticket()  # ticket PARKED (valid state for checkout)
    validate_success(api.create_damage_claim(
        create_damage_claim_payload(env["ticket"]["id"], description="dent",
                                    claimed_amount_cents=500), CASHIER), 201)
    res = api.checkout_ticket(env["ticket"]["id"], {"checkout_at": "2026-06-01T12:30:00Z"}, CASHIER)
    validate_error(res, ApiErrorId.ERR_OPEN_DAMAGE_CLAIM)
