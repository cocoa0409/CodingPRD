"""Used-gear trade-in negotiation: dual payout variants, the offer/counter loop,
round cap, invalid accept, and credit-accept wallet reconciliation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures,
)

STAFF = fixtures.STAFF


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / tradein_cash_vs_credit_on_tradein
# ---------------------------------------------------------------------------

def test_offer_computes_cash_variant(api):
    """PRD §3.5: "The `offered_cash_cents` is the floor of the retail price times
    the grade factor times the cash factor of 0.80, and the `offered_credit_cents`
    is the floor of the retail price times the grade factor times the credit
    factor of 1.00 — cash pays less than store credit for the same item."

    Design: Difficulty/dual_variant_calc/tradein_cash_vs_credit_on_tradein
    """
    member, member_headers, product, ti = fixtures.setup_offered_trade_in(
        api, retail_price_cents=100000, condition_grade="B")
    assert ti["offered_cash_cents"] == 28000


def test_offer_computes_credit_variant_higher_than_cash(api):
    """PRD §3.5: "The grade factor is 0.50 for grade `A`, 0.35 for grade `B`, and
    0.20 for grade `C`."
    PRD §3.5: "the `offered_credit_cents` is the floor of the retail price times
    the grade factor times the credit factor of 1.00 — cash pays less than store
    credit for the same item."

    Design: Difficulty/dual_variant_calc/tradein_cash_vs_credit_on_tradein
    """
    member, member_headers, product, ti = fixtures.setup_offered_trade_in(
        api, retail_price_cents=100000, condition_grade="B")
    assert ti["offered_credit_cents"] == 35000
    assert ti["offered_credit_cents"] != ti["offered_cash_cents"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / tradein_offer_counter_cycle
# ---------------------------------------------------------------------------

def test_counter_then_reoffer_returns_to_offered(api):
    """PRD §3.5: "this forms the `OFFERED`↔`COUNTERED` negotiation loop, since
    staff may re-offer from `COUNTERED` and recompute the two payout figures."

    Design: Difficulty/non_linear_state_machine/tradein_offer_counter_cycle
    """
    member, member_headers, product, ti = fixtures.setup_offered_trade_in(
        api, retail_price_cents=100000, condition_grade="A")
    validate_success(api.counter_trade_in(ti["id"], {"counter_ask_cents": 45000}, member_headers))
    reoffered = validate_success(api.offer_trade_in(ti["id"], STAFF))
    assert reoffered["status"] == "OFFERED"


def test_counter_increments_rounds(api):
    """PRD §3.5: "From an `OFFERED` state the member may counter, recording a
    non-binding `counter_ask_cents`, incrementing the completed-loop counter
    `rounds` by 1, and moving the trade-in to `COUNTERED`".

    Design: Difficulty/non_linear_state_machine/tradein_offer_counter_cycle
    """
    member, member_headers, product, ti = fixtures.setup_offered_trade_in(
        api, retail_price_cents=100000, condition_grade="A")
    validate_success(api.counter_trade_in(ti["id"], {"counter_ask_cents": 45000}, member_headers))
    reoffered = validate_success(api.offer_trade_in(ti["id"], STAFF))
    assert reoffered["rounds"] == 1


# ---------------------------------------------------------------------------
# Queue B — state_machines / tradein_accept_from_submitted_returns_invalid_state
# ---------------------------------------------------------------------------

def test_accept_submitted_trade_in_rejected(api):
    """PRD §3.5: "Accepting from a non-`OFFERED` state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/tradein_accept_from_submitted_returns_invalid_state
    """
    member, member_headers, product, ti = fixtures.setup_submitted_trade_in(
        api, retail_price_cents=80000, condition_grade="A")
    validate_error(api.accept_trade_in(ti["id"], {"accepted_payout_type": "CASH"}, member_headers),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue B — state_machines / tradein_counter_exceeds_max_rounds_rejected
# ---------------------------------------------------------------------------

def test_counter_after_round_cap_rejected(api):
    """PRD §3.5: "A counter is allowed only while the trade-in is `OFFERED` and
    only while `rounds` is still below the cap of 3 completed loops; a counter
    attempted once `rounds` has reached 3 is rejected with
    `ERR_TRADE_IN_ROUNDS_EXCEEDED`".

    Design: Corner/state_machines/tradein_counter_exceeds_max_rounds_rejected
    """
    member, member_headers, product, ti = fixtures.setup_trade_in_at_round_cap(
        api, retail_price_cents=60000, condition_grade="B")
    assert ti["rounds"] == 3
    validate_error(api.counter_trade_in(ti["id"], {"counter_ask_cents": 33000}, member_headers),
                   ApiErrorId.ERR_TRADE_IN_ROUNDS_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Queue B — cross_cutting / wallet_credited_on_tradein_credit_accept
# ---------------------------------------------------------------------------

def test_credit_accept_credits_member_wallet(api):
    """PRD §3.5: "acceptance pins `accepted_payout_cents` to the
    `offered_cash_cents` when `CASH` was chosen or the `offered_credit_cents` when
    `CREDIT` was chosen ... When the accepted channel is `CREDIT`, the accepted
    amount is added to the member's `wallet_credit_cents`".

    Design: Corner/cross_cutting/wallet_credited_on_tradein_credit_accept
    """
    member, member_headers, product, ti = fixtures.setup_offered_trade_in(
        api, retail_price_cents=100000, condition_grade="A")
    accepted = validate_success(api.accept_trade_in(
        ti["id"], {"accepted_payout_type": "CREDIT"}, member_headers))
    assert accepted["accepted_payout_cents"] == 50000
    member = validate_success(api.get_member(member["id"], member_headers))
    assert member["wallet_credit_cents"] == 50000
