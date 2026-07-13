"""Deposits, settlement, gratuity distribution (provisional equal-split vs final
role-weighted), validation precedence on pay-deposit, and completion guards."""
from test_helpers import validate_success, validate_error
from test_helpers import TEST_USERS
from test_helpers.fixtures import (
    create_trip, setup_open_trip, create_reservation,
    setup_settled_trip_three_guides,
)

MGR = TEST_USERS["outfitter_manager_headers"]
RESV = TEST_USERS["reservationist_headers"]


# ── Gratuity: provisional equal split vs final role-weighted ──

def test_provisional_gratuity_equal_split_on_settlement(api):
    """PRD §3.6: "The provisional split divides this pool equally among the trip's
    `ASSIGNED` guide assignments, ordered by `created_at` ascending (ties broken by
    `created_at`, never by `id`). If there are no assigned guides, no distribution occurs.
    Otherwise each guide's base share is the pool divided by the number of guides, rounded
    down to whole cents; the leftover cents — the pool minus that base share times the
    number of guides — are handed out one cent each to the first several guides in
    `created_at` ascending order."

    Design: Difficulty/dual_variant_calc/gratuity_provisional_equal_vs_final_weighted
    """
    ctx = setup_settled_trip_three_guides(api, gratuity_cents=10000)
    ga_lead = validate_success(api.get_guide_assignment(ctx["ga_lead"]["id"], MGR), 200)
    # pool=10000 over 3 guides: base=3333, remainder=1 -> first (LEAD) gets 3334
    assert ga_lead["provisional_gratuity_share_cents"] == 3334


def test_final_gratuity_role_weighted_diverges_from_provisional(api):
    """PRD §3.9: "The final split takes the same pooled gratuity — the sum of
    `gratuity_cents` over the trip's `SETTLED` reservations — and weights it by role, with
    `LEAD` weighted 3, `SAFETY` weighted 2, and `SWEEP` weighted 1."
    PRD §3.9: "each guide's raw share is the pool multiplied by that guide's role weight,
    divided by the total weight, rounded down to whole cents. The leftover — the pool minus
    the sum of all raw shares — is distributed one cent at a time to the guides in
    `created_at` ascending order (never by `id`)."

    Design: Difficulty/dual_variant_calc/gratuity_provisional_equal_vs_final_weighted
    """
    ctx = setup_settled_trip_three_guides(api, gratuity_cents=10000)
    validate_success(api.complete_trip(ctx["trip"]["id"], MGR), 200)
    ga_lead = validate_success(api.get_guide_assignment(ctx["ga_lead"]["id"], MGR), 200)
    ga_safety = validate_success(api.get_guide_assignment(ctx["ga_safety"]["id"], MGR), 200)
    ga_sweep = validate_success(api.get_guide_assignment(ctx["ga_sweep"]["id"], MGR), 200)
    # W=6: raw LEAD=floor(10000*3/6)=5000, SAFETY=3333, SWEEP=1666; remainder 1 -> LEAD 5001
    assert ga_lead["final_gratuity_share_cents"] == 5001
    assert ga_safety["final_gratuity_share_cents"] == 3333
    assert ga_sweep["final_gratuity_share_cents"] == 1666
    assert ga_lead["final_gratuity_share_cents"] != ga_lead["provisional_gratuity_share_cents"]


# ── Final gratuity pinned rounding order ──

def test_final_gratuity_leftover_cent_goes_to_earliest_guide(api):
    """PRD §3.9: "The leftover — the pool minus the sum of all raw shares — is distributed
    one cent at a time to the guides in `created_at` ascending order (never by `id`)."

    Design: Difficulty/combinatorial_formula/final_gratuity_rounding_order_mode_b
    """
    ctx = setup_settled_trip_three_guides(api, gratuity_cents=10000)
    validate_success(api.complete_trip(ctx["trip"]["id"], MGR), 200)
    ga_lead = validate_success(api.get_guide_assignment(ctx["ga_lead"]["id"], MGR), 200)
    assert ga_lead["final_gratuity_share_cents"] == 5001


def test_final_gratuity_shares_sum_to_pool(api):
    """PRD §3.9: "each guide's raw share is the pool multiplied by that guide's role
    weight, divided by the total weight, rounded down to whole cents. The leftover — the
    pool minus the sum of all raw shares — is distributed one cent at a time to the guides
    in `created_at` ascending order (never by `id`)."

    Design: Difficulty/combinatorial_formula/final_gratuity_rounding_order_mode_b
    """
    ctx = setup_settled_trip_three_guides(api, gratuity_cents=10000)
    validate_success(api.complete_trip(ctx["trip"]["id"], MGR), 200)
    shares = [
        validate_success(api.get_guide_assignment(ctx[k]["id"], MGR), 200)["final_gratuity_share_cents"]
        for k in ("ga_lead", "ga_safety", "ga_sweep")
    ]
    assert shares == [5001, 3333, 1666]
    assert sum(shares) == 10000


# ── Validation precedence: cancelled state beats deposit fiscal ──

def test_pay_deposit_on_cancelled_reservation_returns_cancelled_over_deposit(api):
    """PRD §2.6: "When more than one rule could reject a request, the checks are applied in
    a fixed order of precedence, and the first failing check determines the returned error."
    PRD §3.6: "The reservation must not have been cancelled, otherwise
    `ERR_RESERVATION_CANCELLED`."
    PRD §3.6: "only a strict shortfall is rejected with `ERR_DEPOSIT_TOO_LOW`."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_state_beats_deposit_fiscal_on_pay_deposit
    """
    trip = create_trip(api, difficulty_class="CLASS_III")
    res = create_reservation(api, trip["id"], party_size=5, deposit_cents=1)  # underfunded deposit
    validate_success(api.cancel_reservation(res["id"], RESV), 200)
    validate_error(api.pay_deposit(res["id"], RESV), "ERR_RESERVATION_CANCELLED")


def test_pay_deposit_on_cancelled_reservation_with_sufficient_deposit_still_cancelled(api):
    """PRD §3.6: "The reservation must not have been cancelled, otherwise
    `ERR_RESERVATION_CANCELLED`."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_state_beats_deposit_fiscal_on_pay_deposit
    """
    trip = create_trip(api, difficulty_class="CLASS_III")
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)  # sufficient (est 12000)
    validate_success(api.cancel_reservation(res["id"], RESV), 200)
    validate_error(api.pay_deposit(res["id"], RESV), "ERR_RESERVATION_CANCELLED")


# ── Deposits-held conservation across pay + refund ──

def test_deposits_held_accumulates_on_pay(api):
    """PRD §3.6: "On success the trip's `deposits_held_cents` is recomputed. That aggregate
    is the sum of `deposit_cents` over the trip's reservations whose `payment_status` is
    `DEPOSIT_PAID` or `SETTLED`."

    Design: Difficulty/compensating_invariant/deposits_held_conserved_across_pay_and_refund
    """
    trip, _, _ = setup_open_trip(api)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    validate_success(api.confirm_reservation(res["id"], RESV), 200)
    validate_success(api.pay_deposit(res["id"], RESV), 200)
    trip_after = validate_success(api.get_trip(trip["id"], MGR), 200)
    assert trip_after["deposits_held_cents"] == 3000


def test_deposits_held_returns_to_zero_on_cancel_refund(api):
    """PRD §3.9: "If the reservation's `payment_status` was `DEPOSIT_PAID` or `SETTLED`, it
    moves to `REFUNDED` and the trip's `deposits_held_cents` is recomputed downward by the
    `deposit_cents`."

    Design: Difficulty/compensating_invariant/deposits_held_conserved_across_pay_and_refund
    """
    trip, _, _ = setup_open_trip(api)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    validate_success(api.confirm_reservation(res["id"], RESV), 200)
    validate_success(api.pay_deposit(res["id"], RESV), 200)
    assert validate_success(api.get_trip(trip["id"], MGR), 200)["deposits_held_cents"] == 3000
    validate_success(api.cancel_reservation(res["id"], RESV), 200)
    trip_after = validate_success(api.get_trip(trip["id"], MGR), 200)
    assert trip_after["deposits_held_cents"] == 0
    res_after = validate_success(api.get_reservation(res["id"], RESV), 200)
    assert res_after["payment_status"] == "REFUNDED"


# ── Corner: deposit sufficiency at boundary + shortfall ──

def test_deposit_at_exact_required_threshold_accepted(api):
    """PRD §3.6: "it must be at least the required deposit, which is the reservation's
    `estimated_total_cents` multiplied by the deposit percentage of 25 percent (0.25),
    rounded half-up to the nearest whole cent; a deposit exactly equal to the required
    amount is accepted, and only a strict shortfall is rejected with `ERR_DEPOSIT_TOO_LOW`."

    Design: Corner/calculations/deposit_at_exact_required_threshold_accepted
    """
    trip = create_trip(api, base_rate_cents=12000, difficulty_class="CLASS_II")
    # est=12000 -> required deposit = round(12000*0.25)=3000
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    paid = validate_success(api.pay_deposit(res["id"], RESV), 200)
    assert paid["payment_status"] == "DEPOSIT_PAID"


def test_pay_deposit_below_required_returns_deposit_too_low(api):
    """PRD §3.6: "only a strict shortfall is rejected with `ERR_DEPOSIT_TOO_LOW`."

    Design: Corner/validations/pay_deposit_below_required_returns_deposit_too_low
    """
    trip = create_trip(api, base_rate_cents=12000, difficulty_class="CLASS_II")
    # est=12000 -> required 3000; 2999 is a strict shortfall
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=2999)
    validate_error(api.pay_deposit(res["id"], RESV), "ERR_DEPOSIT_TOO_LOW")


# ── Corner: completion guard ──

def test_complete_trip_with_pending_reservation_returns_unresolved(api):
    """PRD §3.9: "Completion has two guards: no reservation on the trip may still be
    `PENDING`, otherwise `ERR_UNRESOLVED_RESERVATIONS`; and every `CHECKED_IN` reservation
    must have `payment_status` `SETTLED`, otherwise `ERR_UNSETTLED_RESERVATION`."

    Design: Corner/state_machines/complete_trip_with_pending_reservation_returns_unresolved
    """
    trip, _, _ = setup_open_trip(api)
    create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)  # left PENDING
    validate_error(api.complete_trip(trip["id"], MGR), "ERR_UNRESOLVED_RESERVATIONS")
