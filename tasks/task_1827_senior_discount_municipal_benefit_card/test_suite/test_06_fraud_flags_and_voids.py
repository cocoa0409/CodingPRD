"""Fraud review: manual flagging, the threshold suspension cascade, flag
clearing with segregation of duties, the restoration cascade, and merchant
voids with year-to-date reversal (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_usage_transaction_payload,
    flag_transactions,
    make_fraud_analyst_headers,
    make_merchant_operator_headers,
    onboard_cardholder,
    post_transactions,
    read_cards,
    read_cardholder,
    set_clock,
    setup_merchant_with_offer,
    setup_posted_transactions,
    setup_suspended_cardholder,
    validate_error,
    validate_success,
)

FRAUD1_HEADERS = TEST_USERS["fraud_analyst_headers"]  # X-User-ID: fraud-1


def _setup_three_posted_transactions():
    """Cardholder with an ACTIVE card, a merchant with a GROCERY offer, and
    three POSTED transactions of purchase 100 at clock 2026-08-10T10:00:00Z."""
    return setup_posted_transactions(
        3, 100, clock="2026-08-10T10:00:00Z",
        merchant_overrides={"reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})


def test_third_flag_suspends_via_threshold_cascade(api):
    """PRD §3.7: "Every flag transition — manual or automatic — increments the
    cardholder's `fraud_flag_count` by one, and when that count reaches three
    while the member stands in `ACTIVE` or `RECERTIFICATION_DUE`, the system
    suspends the member: the member's pre-suspension standing is preserved in
    `pre_suspension_status`, the status becomes `SUSPENDED`, and the
    suspension cascades the member's `ACTIVE` cards to `SUSPENDED`."
    PRD §3.7: "The flag stamps `flagged_by_user_id` with the analyst's
    `X-User-ID` and `flag_reason` with the supplied reason."
    The third manual flag is the threshold crossing: link 1 is the flag
    transition, link 2 the counter increment it causes.

    Design: Difficulty/transitive_cascade/manual_flag_cascade_suspends_cardholder_and_cards
    """
    scenario = _setup_three_posted_transactions()
    t1, t2, t3 = [t["id"] for t in scenario["transactions"]]
    flag_transactions([t1, t2], reason="duplicate pattern")
    assert read_cardholder(scenario["cardholder"]["id"])["fraud_flag_count"] == 2

    flagged = validate_success(
        api.flag_transaction(t3, "third strike", FRAUD1_HEADERS), 200)
    assert flagged["status"] == "FLAGGED"
    assert flagged["flagged_by_user_id"] == "fraud-1"
    assert flagged["flag_reason"] == "third strike"

    cardholder = read_cardholder(scenario["cardholder"]["id"])
    assert cardholder["fraud_flag_count"] == 3, (
        "the flag transition — not the flag call itself — incremented the counter")


def test_third_flag_cascade_reaches_cardholder_and_cards(api):
    """PRD §3.7: "Every flag transition — manual or automatic — increments the
    cardholder's `fraud_flag_count` by one, and when that count reaches three
    while the member stands in `ACTIVE` or `RECERTIFICATION_DUE`, the system
    suspends the member: the member's pre-suspension standing is preserved in
    `pre_suspension_status`, the status becomes `SUSPENDED`, and the
    suspension cascades the member's `ACTIVE` cards to `SUSPENDED`."
    Links 3 and 4: the threshold crossing suspends the member (preserving the
    pre-suspension standing), and the suspension cascades to the cards.

    Design: Difficulty/transitive_cascade/manual_flag_cascade_suspends_cardholder_and_cards
    """
    scenario = _setup_three_posted_transactions()
    t1, t2, t3 = [t["id"] for t in scenario["transactions"]]
    flag_transactions([t1, t2], reason="duplicate pattern")
    validate_success(api.flag_transaction(t3, "third strike", FRAUD1_HEADERS), 200)

    cardholder = read_cardholder(scenario["cardholder"]["id"])
    assert cardholder["status"] == "SUSPENDED"
    assert cardholder["pre_suspension_status"] == "ACTIVE", (
        "the pre-suspension standing is preserved")

    cards = read_cards(scenario["cardholder"]["id"])
    card = [c for c in cards if c["id"] == scenario["card"]["id"]][0]
    assert card["status"] == "SUSPENDED", (
        "the cardholder suspension cascades their ACTIVE cards to SUSPENDED")


def test_clear_flag_decrements_counter(api):
    """PRD §3.7: "Clearing decrements the member's `fraud_flag_count` by one
    and empties `flagged_by_user_id` and `flag_reason`, returning the
    transaction to `POSTED`."
    The clearer (fraud-2) differs from the flagger (fraud-1), satisfying
    segregation of duties.

    Design: Difficulty/transitive_cascade/clear_flag_cascade_restores_cardholder_and_cards
    """
    scenario = setup_suspended_cardholder()
    t1 = scenario["transactions"][0]["id"]

    cleared = validate_success(
        api.clear_flag(t1, make_fraud_analyst_headers("fraud-2")), 200)
    assert cleared["status"] == "POSTED"
    assert cleared["flagged_by_user_id"] is None
    assert cleared["flag_reason"] is None

    cardholder = read_cardholder(scenario["cardholder"]["id"])
    assert cardholder["fraud_flag_count"] == 2, (
        "the clear transition decremented the counter from 3 to 2")


def test_clear_flag_restores_cardholder_and_cards(api):
    """PRD §3.7: "When the count thereby drops below three and the member
    stands `SUSPENDED`, the member is restored to the standing captured in
    `pre_suspension_status` — `ACTIVE` or `RECERTIFICATION_DUE` —
    `pre_suspension_status` is emptied, and the restoration cascades the
    member's `SUSPENDED` cards back to `ACTIVE`."

    Design: Difficulty/transitive_cascade/clear_flag_cascade_restores_cardholder_and_cards
    """
    scenario = setup_suspended_cardholder()
    t1 = scenario["transactions"][0]["id"]
    validate_success(api.clear_flag(t1, make_fraud_analyst_headers("fraud-2")), 200)

    cardholder = read_cardholder(scenario["cardholder"]["id"])
    assert cardholder["status"] == "ACTIVE", (
        "dropping below the threshold restores the preserved standing")
    assert cardholder["pre_suspension_status"] is None

    cards = read_cards(scenario["cardholder"]["id"])
    card = [c for c in cards if c["id"] == scenario["card"]["id"]][0]
    assert card["status"] == "ACTIVE", (
        "the restoration cascades their SUSPENDED cards back to ACTIVE")


def test_analyst_cannot_clear_own_flag(api):
    """PRD §3.7: "A `FraudAnalyst` may clear a transaction standing in
    `FLAGGED` — any other status is rejected with
    `ERR_TRANSACTION_NOT_FLAGGABLE` — but segregation of duties forbids an
    analyst from clearing a flag they personally raised: when
    `flagged_by_user_id` names an analyst rather than `SYSTEM`, a clearer
    whose `X-User-ID` equals it is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    Design: Corner/validations/analyst_cannot_clear_own_flag_rejected
    """
    scenario = setup_posted_transactions(
        1, 100, clock=None,
        merchant_overrides={"name": "Flag Store", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    t1 = scenario["transactions"][0]["id"]
    flag_transactions([t1], reason="suspicious")

    res = api.clear_flag(t1, FRAUD1_HEADERS)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    after = validate_success(
        api.get_usage_transaction(t1, make_fraud_analyst_headers("fraud-2")), 200)
    assert after["status"] == "FLAGGED", "the rejected clear changes nothing"
    assert after["flagged_by_user_id"] == "fraud-1"


def test_void_flagged_transaction_rejected(api):
    """PRD §3.7: "The `MerchantOperator` of the merchant where the sale
    occurred — the caller's `X-User-ID` must equal the transaction's
    `merchant_id`, else `ERR_MERCHANT_OWNERSHIP_MISMATCH` — may void a
    transaction standing in `POSTED`; voiding is rejected with
    `ERR_TRANSACTION_NOT_VOIDABLE` (HTTP 409) in any other status, so a
    `FLAGGED` transaction must first be cleared by a fraud analyst, and
    `VOIDED` is terminal."

    Design: Corner/state_machines/void_flagged_transaction_rejected
    """
    scenario = setup_posted_transactions(
        1, 100, clock=None,
        merchant_overrides={"name": "Void Foods", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    t1 = scenario["transactions"][0]["id"]
    flag_transactions([t1], reason="review hold")

    res = api.void_transaction(
        t1, make_merchant_operator_headers(scenario["merchant"]["id"]))
    validate_error(res, ApiErrorId.ERR_TRANSACTION_NOT_VOIDABLE)

    after = validate_success(
        api.get_usage_transaction(t1, FRAUD1_HEADERS), 200)
    assert after["status"] == "FLAGGED"
    cardholder = read_cardholder(scenario["cardholder"]["id"])
    assert cardholder["ytd_discount_cents"] == 10, (
        "the rejected void leaves the year-to-date totals unchanged")
    assert cardholder["ytd_transaction_count"] == 1


def test_clear_flag_on_posted_transaction_rejected(api):
    """PRD §3.7: "A `FraudAnalyst` may clear a transaction standing in
    `FLAGGED` — any other status is rejected with
    `ERR_TRANSACTION_NOT_FLAGGABLE` — but segregation of duties forbids an
    analyst from clearing a flag they personally raised: when
    `flagged_by_user_id` names an analyst rather than `SYSTEM`, a clearer
    whose `X-User-ID` equals it is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    Design: Corner/state_machines/clear_flag_on_posted_transaction_rejected
    """
    scenario = setup_posted_transactions(
        1, 100, clock=None,
        merchant_overrides={"name": "Clear Corner", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    t1 = scenario["transactions"][0]["id"]
    res = api.clear_flag(t1, FRAUD1_HEADERS)
    validate_error(res, ApiErrorId.ERR_TRANSACTION_NOT_FLAGGABLE)


def test_post_then_void_accumulates_ytd(api, program_administrator_headers):
    """PRD §3.3: "The cardholder record also surfaces derived figures on every
    read: `age_years`, the whole-year age against the current clock date;
    `fraud_flag_count`, the number of the member's transactions currently in
    `FLAGGED` status; `ytd_discount_cents`, the sum of `discount_cents` over
    the member's transactions in `POSTED` or `FLAGGED` status whose
    `created_at` falls inside the clock's current calendar year; and
    `ytd_transaction_count`, the count of that same inclusion set."
    Two posted purchases of 5000 at 10% (discount 500 each) give the 1000/2
    baseline; a third posting raises the totals to 1500/3.

    Design: Difficulty/compensating_invariant/void_conserves_cardholder_ytd_totals
    """
    onboard = onboard_cardholder(full_name="Vera Void", residency_address="18 Refund Rd")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Void Variety", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    set_clock("2026-08-05T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 2, 5000)
    baseline = read_cardholder(onboard["cardholder"]["id"])
    assert baseline["ytd_discount_cents"] == 1000
    assert baseline["ytd_transaction_count"] == 2

    t3 = validate_success(api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant["id"],
                                         "GROCERY", 5000),
        make_merchant_operator_headers(merchant["id"])), 201)
    assert t3["discount_cents"] == 500

    after_post = read_cardholder(onboard["cardholder"]["id"])
    assert after_post["ytd_discount_cents"] == 1500
    assert after_post["ytd_transaction_count"] == 3


def test_void_restores_ytd_baseline(api):
    """PRD §3.7: "The void records `voided_by_user_id` and reverses the
    member's year-to-date figures, subtracting the transaction's
    `discount_cents` from `ytd_discount_cents` and decrementing
    `ytd_transaction_count` by one — equivalently, both figures are recomputed
    over the member's transactions in `POSTED` or `FLAGGED` status within the
    clock's current calendar year, from which the voided transaction is now
    excluded."
    The post/void pair conserves the year-to-date totals exactly:
    1000/2 -> 1500/3 -> 1000/2.

    Design: Difficulty/compensating_invariant/void_conserves_cardholder_ytd_totals
    """
    onboard = onboard_cardholder(full_name="Vera Void", residency_address="18 Refund Rd")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Void Variety", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    set_clock("2026-08-05T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 2, 5000)

    t3 = validate_success(api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant["id"],
                                         "GROCERY", 5000),
        make_merchant_operator_headers(merchant["id"])), 201)
    assert read_cardholder(onboard["cardholder"]["id"])["ytd_discount_cents"] == 1500

    voided = validate_success(
        api.void_transaction(t3["id"], make_merchant_operator_headers(merchant["id"])),
        200)
    assert voided["status"] == "VOIDED"
    assert voided["voided_by_user_id"] == merchant["id"]

    after_void = read_cardholder(onboard["cardholder"]["id"])
    assert after_void["ytd_discount_cents"] == 1000, (
        "the void subtracts the transaction's discount from the year-to-date figure")
    assert after_void["ytd_transaction_count"] == 2
