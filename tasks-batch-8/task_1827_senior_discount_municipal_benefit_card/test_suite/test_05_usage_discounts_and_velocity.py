"""Recording purchases: the discount min-chain, rounding, the monthly
discount ceiling, offer resolution, standing checks, and the two velocity
windows (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_usage_transaction,
    create_usage_transaction_payload,
    flag_transactions,
    make_merchant_operator_headers,
    onboard_cardholder,
    post_transactions,
    read_cardholder,
    set_clock,
    setup_merchant_with_offer,
    setup_posted_transactions,
    setup_suspended_cardholder,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_min_chain_scenario():
    """Cardholder + merchant (GROCERY 25% off, per-transaction cap 700) with
    4900 cents of same-month discounts already posted: four purchases of 2800
    on 2026-08-03 and three on 2026-08-04, each discounting 700."""
    onboard = onboard_cardholder(full_name="Minnie Chain",
                                 date_of_birth="1959-03-03",
                                 annual_income_cents=800000,
                                 residency_address="4 Pine St")
    merchant, offer = setup_merchant_with_offer(
        merchant_overrides={"name": "Min Mart", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 25,
                         "max_discount_cents": 700})
    set_clock("2026-08-03T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 4, 2800)
    set_clock("2026-08-04T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 3, 2800)
    return onboard, merchant, offer


def test_min_chain_selects_monthly_remaining(api):
    """PRD §3.6: "First, the raw discount is the purchase amount multiplied by
    the resolved offer's `discount_pct` and divided by one hundred, carried as
    an exact rational figure with no rounding. Second, the raw figure is
    capped at the offer's `max_discount_cents`. Third, the member's
    month-to-date usage is the sum of `discount_cents` across that
    cardholder's transactions in `POSTED` or `FLAGGED` status whose
    `created_at` falls inside the clock's current calendar month, and the
    remaining headroom is the program's monthly discount ceiling of $50 per
    cardholder minus that usage, floored at zero. Fourth, the granted figure
    is the lesser of the capped figure and the remaining headroom. Only now is
    rounding applied: the granted figure is rounded half-up once, to a whole
    cent, and stored."
    Purchase 2000 at 25% gives raw 500; the per-transaction cap is 700; the
    monthly remaining after 4900 of prior discounts is 100 — the min chain
    selects the state-dependent remaining.

    Design: Difficulty/combinatorial_formula/discount_min_chain_selects_monthly_remaining
    """
    onboard, merchant, _ = _setup_min_chain_scenario()
    probe = validate_success(api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant["id"],
                                         "GROCERY", 2000),
        make_merchant_operator_headers(merchant["id"])), 201)
    assert_usage_transaction(probe)
    assert probe["discount_cents"] == 100, (
        "min(raw 500, cap 700, remaining 5000-4900 = 100) selects the remaining; "
        "100 differs from both raw (500) and cap (700), so all three terms are "
        "distinguishable")
    assert probe["status"] == "POSTED", (
        "the probe is the fourth transaction of its calendar day, below the "
        "flag threshold")


def test_min_chain_result_accumulates_ytd(api, program_administrator_headers):
    """PRD §3.3: "The cardholder record also surfaces derived figures on every
    read: `age_years`, the whole-year age against the current clock date;
    `fraud_flag_count`, the number of the member's transactions currently in
    `FLAGGED` status; `ytd_discount_cents`, the sum of `discount_cents` over
    the member's transactions in `POSTED` or `FLAGGED` status whose
    `created_at` falls inside the clock's current calendar year; and
    `ytd_transaction_count`, the count of that same inclusion set."
    After the 100-cent probe, the year-to-date totals reconcile to the full
    5000-cent monthly ceiling across eight transactions.

    Design: Difficulty/combinatorial_formula/discount_min_chain_selects_monthly_remaining
    """
    onboard, merchant, _ = _setup_min_chain_scenario()
    validate_success(api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant["id"],
                                         "GROCERY", 2000),
        make_merchant_operator_headers(merchant["id"])), 201)
    cardholder = read_cardholder(onboard["cardholder"]["id"])
    assert cardholder["ytd_discount_cents"] == 5000, "4900 + 100"
    assert cardholder["ytd_transaction_count"] == 8


def test_discount_rounds_half_up_at_half_cent(api):
    """PRD §3.6: "First, the raw discount is the purchase amount multiplied by
    the resolved offer's `discount_pct` and divided by one hundred, carried as
    an exact rational figure with no rounding. Second, the raw figure is
    capped at the offer's `max_discount_cents`. Third, the member's
    month-to-date usage is the sum of `discount_cents` across that
    cardholder's transactions in `POSTED` or `FLAGGED` status whose
    `created_at` falls inside the clock's current calendar month, and the
    remaining headroom is the program's monthly discount ceiling of $50 per
    cardholder minus that usage, floored at zero. Fourth, the granted figure
    is the lesser of the capped figure and the remaining headroom. Only now is
    rounding applied: the granted figure is rounded half-up once, to a whole
    cent, and stored."
    Purchase 1005 at 10% gives raw 100.5; round-half-up yields 101 (a
    truncating implementation would give 100).

    Design: Corner/calculations/discount_rounds_half_up_at_half_cent
    """
    scenario = setup_posted_transactions(
        0, clock="2026-08-10T10:00:00Z",
        merchant_overrides={"name": "Half Mart", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    txn = validate_success(api.create_usage_transaction(
        create_usage_transaction_payload(scenario["card"]["id"],
                                         scenario["merchant"]["id"],
                                         "GROCERY", 1005),
        make_merchant_operator_headers(scenario["merchant"]["id"])), 201)
    assert txn["discount_cents"] == 101, "round_half_up(100.5) is 101"


def test_discount_zero_when_monthly_cap_exhausted(api):
    """PRD §3.6: "A cardholder whose month is already exhausted therefore
    receives a zero-cent discount on further purchases rather than a
    rejection."
    Five purchases of 10000 at 10% (max 1000) exhaust the 5000-cent monthly
    ceiling — the fifth also trips the calendar-day flag — and the sixth is
    still persisted, with discount_cents 0.

    Design: Corner/calculations/discount_zero_when_monthly_cap_exhausted
    """
    scenario = setup_posted_transactions(
        5, 10000, clock="2026-08-10T10:00:00Z",
        merchant_overrides={"name": "Zero Mart", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    sixth = validate_success(api.create_usage_transaction(
        create_usage_transaction_payload(scenario["card"]["id"],
                                         scenario["merchant"]["id"],
                                         "GROCERY", 10000),
        make_merchant_operator_headers(scenario["merchant"]["id"])), 201)
    assert sixth["discount_cents"] == 0, (
        "remaining = max(5000 - 5000, 0) = 0 floors the min chain")
    assert sixth["status"] == "FLAGGED", (
        "calendar-day count 6 >= 5: a zero-discount transaction is still "
        "persisted and auto-flagged")


def test_fifth_same_day_transaction_auto_flagged(api, program_administrator_headers):
    """PRD §3.6: "The trailing-window count tallies transactions whose
    `created_at` falls later than twenty-four hours before the current clock
    instant and at or before it, and adds one for the candidate; if that total
    reaches ten, creation is refused outright with `ERR_VELOCITY_HARD_LIMIT`
    (HTTP 422). Otherwise the calendar-day count tallies transactions whose
    `created_at` calendar date equals the clock's calendar date and adds one
    for the candidate; if that total reaches five, the transaction is
    persisted as `POSTED` and then immediately auto-transitioned to `FLAGGED`,
    with `flagged_by_user_id` recorded as the literal `SYSTEM` and
    `flag_reason` recorded as `VELOCITY_AUTO`, and the same fraud cascade
    described in §3.7 fires from that flag."
    The threshold is inclusive: transactions 1-4 stay POSTED, the fifth is
    auto-flagged.

    Design: Corner/calculations/velocity_flag_threshold_at_exactly_five
    """
    onboard = onboard_cardholder(full_name="Vel Five", residency_address="41 Fifth St")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Vel Mart", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    set_clock("2026-08-10T10:00:00Z")
    m_h = make_merchant_operator_headers(merchant["id"])
    txns = []
    for _ in range(5):
        txns.append(validate_success(api.create_usage_transaction(
            create_usage_transaction_payload(onboard["card"]["id"], merchant["id"],
                                             "GROCERY", 100),
            m_h), 201))

    assert txns[0]["status"] == "POSTED", "calendar-day count 1 < 5"
    assert txns[3]["status"] == "POSTED", "calendar-day count 4 < 5"
    assert txns[4]["status"] == "FLAGGED", "calendar-day count 5 >= 5"
    assert txns[4]["flagged_by_user_id"] == "SYSTEM"
    assert txns[4]["flag_reason"] == "VELOCITY_AUTO"

    cardholder = read_cardholder(onboard["cardholder"]["id"])
    assert cardholder["fraud_flag_count"] == 1, (
        "below the suspension threshold of three")
    assert cardholder["status"] == "ACTIVE"


def _setup_velocity_divergence():
    """Two cardholders with identical evening batches; Y additionally has a
    five-transaction morning batch (fifth auto-flagged). Returns the ids."""
    x = onboard_cardholder(full_name="Xavier Senior", date_of_birth="1960-01-01",
                           annual_income_cents=900000, residency_address="2 Oak St")
    y = onboard_cardholder(full_name="Yara Senior", date_of_birth="1960-01-01",
                           annual_income_cents=900000, residency_address="3 Elm St")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Velocity Mart", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    set_clock("2026-08-10T20:00:00Z")
    post_transactions(x["card"]["id"], merchant["id"], 4, 100)
    post_transactions(y["card"]["id"], merchant["id"], 4, 100)
    set_clock("2026-08-11T08:00:00Z")
    y_morning = post_transactions(y["card"]["id"], merchant["id"], 5, 100)
    return x, y, merchant, y_morning


def test_calendar_day_window_governs_flagging(api):
    """PRD §3.6: "The trailing-window count tallies transactions whose
    `created_at` falls later than twenty-four hours before the current clock
    instant and at or before it, and adds one for the candidate; if that total
    reaches ten, creation is refused outright with `ERR_VELOCITY_HARD_LIMIT`
    (HTTP 422). Otherwise the calendar-day count tallies transactions whose
    `created_at` calendar date equals the clock's calendar date and adds one
    for the candidate; if that total reaches five, the transaction is
    persisted as `POSTED` and then immediately auto-transitioned to `FLAGGED`,
    with `flagged_by_user_id` recorded as the literal `SYSTEM` and
    `flag_reason` recorded as `VELOCITY_AUTO`, and the same fraud cascade
    described in §3.7 fires from that flag."
    PRD §3.6: "Because the two windows differ — a burst late yesterday evening
    counts toward this morning's trailing-window total but not toward today's
    calendar-day total — the hard limit can refuse a sale even on a quiet
    calendar day."
    X's probe has trailing-24h count 5 but calendar-day count 1: it stays
    POSTED, proving the calendar-day window (not the trailing window) governs
    flagging.

    Design: Difficulty/dual_variant_calc/velocity_calendar_day_vs_trailing_24h_divergence
    """
    x, y, merchant, y_morning = _setup_velocity_divergence()
    assert y_morning[4]["status"] == "FLAGGED", (
        "Y's fifth transaction of 2026-08-11 trips the calendar-day threshold")
    y_cardholder = read_cardholder(y["cardholder"]["id"])
    assert y_cardholder["fraud_flag_count"] == 1
    assert y_cardholder["status"] == "ACTIVE", "one flag is below the suspension threshold"

    set_clock("2026-08-11T10:00:00Z")
    probe = validate_success(api.create_usage_transaction(
        create_usage_transaction_payload(x["card"]["id"], merchant["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(merchant["id"])), 201)
    assert probe["status"] == "POSTED", (
        "calendar-day count 1 (< 5): no auto-flag even though the trailing-24h "
        "count is 5 — had the trailing window governed flagging this would be "
        "FLAGGED")


def test_trailing_24h_window_governs_hard_reject(api):
    """PRD §3.6: "The trailing-window count tallies transactions whose
    `created_at` falls later than twenty-four hours before the current clock
    instant and at or before it, and adds one for the candidate; if that total
    reaches ten, creation is refused outright with `ERR_VELOCITY_HARD_LIMIT`
    (HTTP 422). Otherwise the calendar-day count tallies transactions whose
    `created_at` calendar date equals the clock's calendar date and adds one
    for the candidate; if that total reaches five, the transaction is
    persisted as `POSTED` and then immediately auto-transitioned to `FLAGGED`,
    with `flagged_by_user_id` recorded as the literal `SYSTEM` and
    `flag_reason` recorded as `VELOCITY_AUTO`, and the same fraud cascade
    described in §3.7 fires from that flag."
    PRD §3.6: "Because the two windows differ — a burst late yesterday evening
    counts toward this morning's trailing-window total but not toward today's
    calendar-day total — the hard limit can refuse a sale even on a quiet
    calendar day."
    Y's probe has trailing-24h count 10 (4 last evening + 5 this morning +
    candidate) but calendar-day count 6: it is rejected outright, proving the
    trailing-24h window (not the calendar-day window) governs rejection.

    Design: Difficulty/dual_variant_calc/velocity_calendar_day_vs_trailing_24h_divergence
    """
    _, y, merchant, _ = _setup_velocity_divergence()
    set_clock("2026-08-11T10:00:00Z")
    res = api.create_usage_transaction(
        create_usage_transaction_payload(y["card"]["id"], merchant["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_VELOCITY_HARD_LIMIT)


def test_usage_without_matching_offer_rejected(api):
    """PRD §3.6: "If no offer covers the sale, the transaction is rejected
    with `ERR_NO_ACTIVE_OFFER` (HTTP 422)."
    The merchant publishes GROCERY only; the purchase is DINING, so the
    candidate set is empty.

    Design: Corner/validations/usage_without_matching_offer_rejected
    """
    onboard = onboard_cardholder(full_name="No Offer", residency_address="48 Empty Ct")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Select Shops", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    res = api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant["id"],
                                         "DINING", 100),
        make_merchant_operator_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_OFFER)


def test_usage_rejected_when_card_suspended(api):
    """PRD §3.6: "Before any business rule runs, three standing checks fire in
    a pinned order: the presented card must be `ACTIVE` (a `SUSPENDED`,
    `REPLACED`, `EXPIRED`, or `REVOKED` card is rejected with
    `ERR_CARD_NOT_ACTIVE`, HTTP 409); then the cardholder resolved from that
    card must stand in `ACTIVE` or `RECERTIFICATION_DUE` (otherwise
    `ERR_CARDHOLDER_NOT_ACTIVE`); then the merchant must be `ACTIVE`
    (otherwise `ERR_MERCHANT_NOT_ACTIVE`)."
    The fraud cascade has suspended the card; the merchant, offer, and window
    are all valid.

    Design: Difficulty/cross_entity_state_dependency/usage_rejected_when_card_not_active
    """
    scenario = setup_suspended_cardholder()
    res = api.create_usage_transaction(
        create_usage_transaction_payload(scenario["card"]["id"],
                                         scenario["merchant"]["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(scenario["merchant"]["id"]))
    validate_error(res, ApiErrorId.ERR_CARD_NOT_ACTIVE)


def test_card_gate_precedes_cardholder_gate(api):
    """PRD §3.6: "Before any business rule runs, three standing checks fire in
    a pinned order: the presented card must be `ACTIVE` (a `SUSPENDED`,
    `REPLACED`, `EXPIRED`, or `REVOKED` card is rejected with
    `ERR_CARD_NOT_ACTIVE`, HTTP 409); then the cardholder resolved from that
    card must stand in `ACTIVE` or `RECERTIFICATION_DUE` (otherwise
    `ERR_CARDHOLDER_NOT_ACTIVE`); then the merchant must be `ACTIVE`
    (otherwise `ERR_MERCHANT_NOT_ACTIVE`)."
    The pinned order is observable: the cardholder is ALSO SUSPENDED here, yet
    the card error — not `ERR_CARDHOLDER_NOT_ACTIVE` — is returned.

    Design: Difficulty/cross_entity_state_dependency/usage_rejected_when_card_not_active
    """
    scenario = setup_suspended_cardholder()
    cardholder = read_cardholder(scenario["cardholder"]["id"])
    assert cardholder["status"] == "SUSPENDED", (
        "the cardholder is suspended too — the returned error must still be "
        "the card's")

    res = api.create_usage_transaction(
        create_usage_transaction_payload(scenario["card"]["id"],
                                         scenario["merchant"]["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(scenario["merchant"]["id"]))
    validate_error(res, ApiErrorId.ERR_CARD_NOT_ACTIVE)


def test_read_after_write_consistent(api):
    """PRD §3.6: "The granted discount is computed once at creation and frozen
    on the transaction as `discount_cents`, immutable thereafter."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    The transaction returned by the create call and the one returned by an
    immediate read expose identical discount_cents and status.

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    scenario = setup_posted_transactions(
        0, clock=None,
        merchant_overrides={"name": "Sync Shops", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    m_h = make_merchant_operator_headers(scenario["merchant"]["id"])
    created = validate_success(api.create_usage_transaction(
        create_usage_transaction_payload(scenario["card"]["id"],
                                         scenario["merchant"]["id"],
                                         "GROCERY", 5000),
        m_h), 201)
    assert created["discount_cents"] == 500
    assert created["status"] == "POSTED"

    fetched = validate_success(
        api.get_usage_transaction(created["id"], m_h), 200)
    assert fetched["id"] == created["id"]
    assert fetched["discount_cents"] == 500, "frozen at creation"
    assert fetched["status"] == "POSTED"


def test_usage_list_pagination_and_status_filter(api):
    """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."
    PRD §3.6: "The transaction list endpoint accepts optional `card_id`,
    `cardholder_id`, `merchant_id`, `offer_id`, and `status` filters alongside
    `limit` and `offset`."

    Design: Corner/endpoints/usage_list_pagination_and_status_filter
    """
    scenario = setup_posted_transactions(
        3, 100, clock=None,
        merchant_overrides={"name": "Page Plaza", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    merchant_id = scenario["merchant"]["id"]
    t1_id = scenario["transactions"][0]["id"]
    flag_transactions([t1_id], reason="audit")
    m_h = make_merchant_operator_headers(merchant_id)

    page1, meta1 = validate_paginated(api.list_usage_transactions(
        m_h, params={"merchant_id": merchant_id, "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_usage_transactions(
        m_h, params={"merchant_id": merchant_id, "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    flagged, meta3 = validate_paginated(api.list_usage_transactions(
        m_h, params={"merchant_id": merchant_id, "status": "FLAGGED"}))
    assert len(flagged) == 1, "the status filter narrows the set"
    assert flagged[0]["id"] == t1_id
