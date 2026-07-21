"""Layaway financing: installment split, deposit floor, cancellation refund,
overpayment, store-credit funding, payoff, and the state-vs-fiscal precedence."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    authenticated_watch_and_customer, active_layaway, defaulted_layaway,
    new_customer, new_model, new_authenticated_watch, get_customer, get_watch, TEST_USERS,
)
from test_helpers.factories import create_layaway_plan_payload

ASSOC = TEST_USERS["associate_headers"]


def test_installment_split_floors_per_and_final_absorbs_remainder(api):
    """PRD §3.4: "The per_installment_cents is the financed amount divided by
    term_months, taking the floor (the largest whole cent not exceeding the
    quotient). The final_installment_cents is the financed amount minus
    per_installment_cents multiplied by term_months minus one — that is, the final
    installment absorbs the rounding remainder so that the first term_months minus
    one installments each equal per_installment_cents and the whole schedule
    reconciles exactly to the financed amount."

    Design: Difficulty/combinatorial_formula/layaway_installment_rounding_order
    """
    ctx = active_layaway(250000, 7, "2026-08-01T00:00:00Z", list_price_cents=1000000)
    plan = ctx["plan"]
    assert plan["total_price_cents"] == 1000000
    assert plan["per_installment_cents"] == 107142, plan["per_installment_cents"]
    assert plan["final_installment_cents"] == 107148, plan["final_installment_cents"]


def test_installment_schedule_reconciles_to_financed_amount(api):
    """PRD §3.4: "the final installment absorbs the rounding remainder so that the
    first term_months minus one installments each equal per_installment_cents and
    the whole schedule reconciles exactly to the financed amount."

    Design: Difficulty/combinatorial_formula/layaway_installment_rounding_order
    """
    ctx = active_layaway(250000, 7, "2026-08-01T00:00:00Z", list_price_cents=1000000)
    plan = ctx["plan"]
    # financed = 1000000 - 250000 = 750000
    assert plan["per_installment_cents"] * 6 + plan["final_installment_cents"] == 750000


def test_deposit_exactly_min_ratio_accepted(api):
    """PRD §3.4: "The deposit must be at least twenty percent of the price —
    specifically, at least the price multiplied by 0.20 and rounded half-up to
    whole cents; a deposit below that floor is rejected with ERR_DEPOSIT_TOO_LOW
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/layaway_deposit_exactly_min_ratio
    """
    ctx = authenticated_watch_and_customer(list_price_cents=1000000)
    plan = validate_success(
        api.create_layaway_plan(
            create_layaway_plan_payload(ctx["customer"]["id"], ctx["watch"]["id"],
                                        200000, 8, "2026-09-01T00:00:00Z"),
            ASSOC),
        expected_status=201,
    )
    assert plan["status"] == "ACTIVE"


def test_deposit_one_cent_below_floor_rejected(api):
    """PRD §3.4: "The deposit must be at least twenty percent of the price —
    specifically, at least the price multiplied by 0.20 and rounded half-up to
    whole cents; a deposit below that floor is rejected with ERR_DEPOSIT_TOO_LOW
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/layaway_deposit_exactly_min_ratio
    """
    ctx = authenticated_watch_and_customer(list_price_cents=1000000)
    validate_error(
        api.create_layaway_plan(
            create_layaway_plan_payload(ctx["customer"]["id"], ctx["watch"]["id"],
                                        199999, 8, "2026-09-01T00:00:00Z"),
            ASSOC),
        ApiErrorId.ERR_DEPOSIT_TOO_LOW,
    )


def test_cancellation_refunds_paid_minus_restock_fee(api):
    """PRD §3.4: "a restocking fee equal to total_price_cents multiplied by 0.05
    and rounded half-up is computed, and the refund is paid_cents minus that fee
    but never below zero, credited to the customer's store_credit_cents."

    Design: Corner/calculations/layaway_cancellation_refund_minus_restock
    """
    ctx = active_layaway(80000, 4, "2026-09-01T00:00:00Z", list_price_cents=400000)
    cancelled = validate_success(api.cancel_layaway(ctx["plan"]["id"], ASSOC))
    assert cancelled["status"] == "CANCELLED"
    # refund = 80000 paid - round_half_up(0.05 * 400000)=20000 -> 60000
    assert get_customer(ctx["customer"]["id"])["store_credit_cents"] == 60000
    assert get_watch(ctx["watch"]["id"])["status"] == "IN_STOCK"


def test_overpayment_on_active_plan_rejected(api):
    """PRD §3.4: "A payment may never push paid_cents above total_price_cents; an
    overpayment is rejected with ERR_OVERPAYMENT (422)."

    Design: Corner/validations/overpayment_on_active_plan_rejected
    """
    ctx = active_layaway(80000, 4, "2026-09-01T00:00:00Z", list_price_cents=400000)
    validate_error(
        api.pay_layaway(ctx["plan"]["id"], {"amount_cents": 999999}, ASSOC),
        ApiErrorId.ERR_OVERPAYMENT,
    )


def test_store_credit_deposit_insufficient_balance_rejected(api):
    """PRD §3.4: "And when use_store_credit is set, the customer's
    store_credit_cents must be at least the deposit_cents; if it is short, the
    request is rejected with ERR_INSUFFICIENT_STORE_CREDIT (422)."

    Design: Corner/validations/insufficient_store_credit_for_deposit
    """
    customer = new_customer()  # store_credit_cents starts at 0
    watch = new_authenticated_watch(new_model()["id"], list_price_cents=1000000)
    validate_error(
        api.create_layaway_plan(
            create_layaway_plan_payload(customer["id"], watch["id"], 200000, 8,
                                        "2026-09-01T00:00:00Z", use_store_credit=True),
            ASSOC),
        ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT,
    )


def test_payment_on_defaulted_plan_returns_invalid_state(api):
    """PRD §2.10: "Among the business rules, state-validity checks
    (ERR_INVALID_STATE, 409) and the specific business constraints described
    throughout Section 3 apply".
    PRD §3.4: "Defaulting a plan (by an Associate only) moves it ACTIVE →
    DEFAULTED, but only once the current clock is at or after first_due_at plus ten
    days of grace; an attempt before that instant is rejected with ERR_INVALID_STATE
    (409)."

    Design: Difficulty/priority_pair_validation_conflict/defaulted_plan_overpayment_state_beats_fiscal
    """
    ctx = defaulted_layaway(60000, 3, "2026-07-05T00:00:00Z", 300000, "2026-07-16T00:00:00Z")
    assert ctx["plan"]["status"] == "DEFAULTED"
    validate_error(
        api.pay_layaway(ctx["plan"]["id"], {"amount_cents": 999999}, ASSOC),
        ApiErrorId.ERR_INVALID_STATE,
    )


def test_defaulted_overpayment_prefers_state_check_over_fiscal(api):
    """PRD §2.10: "Only after these four universal gates pass are the domain-specific
    business rules evaluated. Among the business rules, state-validity checks
    (ERR_INVALID_STATE, 409) and the specific business constraints described
    throughout Section 3 apply".

    Design: Difficulty/priority_pair_validation_conflict/defaulted_plan_overpayment_state_beats_fiscal
    """
    ctx = defaulted_layaway(60000, 3, "2026-07-05T00:00:00Z", 300000, "2026-07-16T00:00:00Z")
    err = api.pay_layaway(ctx["plan"]["id"], {"amount_cents": 999999}, ASSOC)
    body = err.json()["data"]
    assert body["error_id"] == "ERR_INVALID_STATE", body["error_id"]
    assert body["error_id"] != "ERR_OVERPAYMENT"


def test_full_payoff_fulfills_plan_and_sells_watch(api):
    """PRD §3.4: "When a payment brings paid_cents to exactly total_price_cents, the
    plan advances ACTIVE → PAID_OFF, sets remaining_cents to 0, and is then
    automatically fulfilled PAID_OFF → FULFILLED, which sells the watch by moving it
    RESERVED → SOLD."

    Design: Corner/consistency_model/layaway_payoff_immediate_fulfillment
    """
    ctx = active_layaway(40000, 4, "2026-09-01T00:00:00Z", list_price_cents=200000)
    plan = validate_success(api.pay_layaway(ctx["plan"]["id"], {"amount_cents": 160000}, ASSOC))
    assert plan["paid_cents"] == 200000
    assert plan["status"] == "FULFILLED", plan["status"]
    assert get_watch(ctx["watch"]["id"])["status"] == "SOLD"


def test_layaway_on_reserved_watch_unavailable(api):
    """PRD §3.4: "The target watch must be IN_STOCK (else ERR_WATCH_UNAVAILABLE,
    409) and AUTHENTICATED (else ERR_WATCH_NOT_AUTHENTICATED, 409)."

    Design: Corner/state_machines/layaway_on_reserved_watch_unavailable
    """
    ctx = active_layaway(100000, 5, "2026-09-01T00:00:00Z", list_price_cents=500000)
    # Watch is now RESERVED by the first plan; a second reserve must be refused.
    validate_error(
        api.create_layaway_plan(
            create_layaway_plan_payload(ctx["customer"]["id"], ctx["watch"]["id"],
                                        100000, 5, "2026-09-01T00:00:00Z"),
            ASSOC),
        ApiErrorId.ERR_WATCH_UNAVAILABLE,
    )
