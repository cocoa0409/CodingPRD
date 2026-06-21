"""Purchase create-time gates, settle-time card-active gate, and the
velocity-score trigger-row-inclusion and count-boundary tests.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_eligible_category,
    setup_household_with_active_card,
    create_purchase, settle_purchase, create_and_settle_purchase,
)

CW = TEST_USERS["caseworker_headers"]
INV = TEST_USERS["fraud_investigator_headers"]
MER = TEST_USERS["merchant_headers"]


# ─── Difficulty / combinatorial_formula / fraud_velocity_trigger_row_inclusion_order_pinned ──

def test_velocity_flag_raised_on_fourth_settle_proving_trigger_row_inclusion(api):
    """After three settled transactions of 15000 each within a 24-hour
    window, no VELOCITY_SPIKE flag exists (count=3 < MIN_TX_FOR_FLAG=4).
    The fourth settle must include the just-settled row in the window
    query (PRD §3.9's mandatory order) so the count reaches 4 AND the
    score 60000 + 4*5000 = 80000 satisfies "at least 80,000 cents". A flag
    is therefore created.

    PRD §3.9: "The velocity score is recomputed every time a
    `PurchaseTransaction` for the household transitions from `AUTHORIZED`
    to `SETTLED`. The order of operations is mandatory: first, the
    just-settled row's `status` is written to `SETTLED` and its
    `settled_at` is stamped to `SystemClock.current_utc`; second, the
    system re-queries the set of `SETTLED` transactions for the household
    whose `settled_at` falls in the 24-hour window ending at
    `SystemClock.current_utc` inclusive, so that the trigger row is
    included in that set; third, that set is sorted by `settled_at`
    ascending with `created_at` ascending as the tie-break (never by
    `id`); fourth, the total in cents of `total_cents` across that set
    is computed and the count of rows in that set is computed; fifth,
    the velocity score is the total plus the count multiplied by a
    per-transaction count penalty of 5,000 cents ($50). A flag is raised
    when the velocity score is at least 80,000 cents ($800) AND the count
    is at least 4. When both conditions hold, a `FraudFlag` with
    `trigger_rule` of `VELOCITY_SPIKE` and `status` of `OPEN` is created
    (cascade link 2 of the velocity cascade)."

    Design: Difficulty/combinatorial_formula/fraud_velocity_trigger_row_inclusion_order_pinned
    """
    set_clock("2026-07-15T12:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    hh, _app, card = setup_household_with_active_card(
        case_number="TX-400001", state_code="TX",
        clock_iso="2026-07-15T12:00:00Z",
    )
    for _ in range(3):
        create_and_settle_purchase(card["id"], 15000)
    # After 3 settles, no flag yet.
    pre = validate_success(api.list_fraud_flags(
        INV, params={"household_id": hh["id"],
                     "trigger_rule": "VELOCITY_SPIKE"}), 200)
    assert len(pre) == 0, \
        f"after 3 settles, no VELOCITY_SPIKE flag must exist, got {len(pre)}"

    # 4th tx → settle must include itself in the window and raise the flag.
    create_and_settle_purchase(card["id"], 15000)
    post = validate_success(api.list_fraud_flags(
        INV, params={"household_id": hh["id"],
                     "trigger_rule": "VELOCITY_SPIKE"}), 200)
    assert len(post) == 1, (
        f"4th settle must include itself in the 24h window (PRD §3.9 "
        f"mandatory order) and raise exactly one VELOCITY_SPIKE flag, "
        f"got {len(post)}"
    )
    assert post[0]["status"] == "OPEN"


def test_only_three_settles_does_not_raise_velocity_flag(api):
    """Complementary: with three settles only, no flag is raised, proving
    the cutoff is strictly at count >= 4. This shows the per-instance
    threshold is honored and the previous test's flag really did come
    from the fourth row's inclusion.

    PRD §3.9: "A flag is raised when the velocity score is at least
    80,000 cents ($800) AND the count is at least 4."

    Design: Difficulty/combinatorial_formula/fraud_velocity_trigger_row_inclusion_order_pinned
    """
    set_clock("2026-07-16T12:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    hh, _app, card = setup_household_with_active_card(
        case_number="TX-400002", state_code="TX",
        clock_iso="2026-07-16T12:00:00Z",
    )
    for _ in range(3):
        create_and_settle_purchase(card["id"], 15000)
    flags = validate_success(api.list_fraud_flags(
        INV, params={"household_id": hh["id"],
                     "trigger_rule": "VELOCITY_SPIKE"}), 200)
    assert len(flags) == 0, (
        f"3 settles must not raise a VELOCITY_SPIKE flag (count<4 fails the "
        f"AND-condition), got {len(flags)}"
    )


# ─── Difficulty / boundary_precision_check / fraud_velocity_min_transaction_count_at_four_exactly ──

def test_count_boundary_at_exactly_four_raises_flag(api):
    """The integer count boundary at 4 fires the flag on the 4th SETTLED
    transaction. Before the 4th settle: count=3 < 4, no flag. After: count=4,
    one flag.

    PRD §3.9: "A flag is raised when the velocity score is at least
    80,000 cents ($800) AND the count is at least 4. When both conditions
    hold, a `FraudFlag` with `trigger_rule` of `VELOCITY_SPIKE` and `status`
    of `OPEN` is created (cascade link 2 of the velocity cascade)."

    Design: Difficulty/boundary_precision_check/fraud_velocity_min_transaction_count_at_four_exactly
    """
    set_clock("2026-09-15T12:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    hh, _app, card = setup_household_with_active_card(
        case_number="IL-130001", state_code="IL",
        clock_iso="2026-09-15T12:00:00Z",
    )
    for _ in range(3):
        create_and_settle_purchase(card["id"], 15000)
    pre = validate_success(api.list_fraud_flags(
        INV, params={"household_id": hh["id"],
                     "trigger_rule": "VELOCITY_SPIKE"}), 200)
    assert len(pre) == 0
    # 4th settle → exactly satisfies count >= 4 AND score >= 80000.
    create_and_settle_purchase(card["id"], 15000)
    post = validate_success(api.list_fraud_flags(
        INV, params={"household_id": hh["id"],
                     "trigger_rule": "VELOCITY_SPIKE"}), 200)
    assert len(post) == 1, (
        f"count==4 boundary must raise exactly one VELOCITY_SPIKE flag, "
        f"got {len(post)}"
    )


def test_velocity_score_threshold_alone_does_not_raise_flag(api):
    """The AND-condition means that score >= 80000 with count < 4 does NOT
    raise a flag. Two settles of 50000 each: score = 100000 + 2*5000 =
    110000 >= 80000, but count=2 < 4 → no flag.

    PRD §3.9: "A flag is raised when the velocity score is at least
    80,000 cents ($800) AND the count is at least 4."

    Design: Difficulty/boundary_precision_check/fraud_velocity_min_transaction_count_at_four_exactly
    """
    set_clock("2026-09-16T12:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    hh, _app, card = setup_household_with_active_card(
        case_number="IL-130002", state_code="IL",
        clock_iso="2026-09-16T12:00:00Z",
    )
    for _ in range(2):
        create_and_settle_purchase(card["id"], 50000)
    flags = validate_success(api.list_fraud_flags(
        INV, params={"household_id": hh["id"],
                     "trigger_rule": "VELOCITY_SPIKE"}), 200)
    assert len(flags) == 0, (
        f"score >= 80000 alone must not raise a flag when count < 4; "
        f"got {len(flags)} flags"
    )


# ─── Difficulty / cross_entity_state_dependency / txn_settle_requires_card_active ──

def test_settle_rejected_when_card_is_suspended(api):
    """The settle endpoint must reject when the underlying EBTCard is not
    ACTIVE. Setup: suspend the card BEFORE creating the AUTHORIZED
    transaction, so the txn stays AUTHORIZED and the card is SUSPENDED at
    settle time.

    PRD §3.8: "Settlement, performed by a `Merchant`, transitions the
    transaction from `AUTHORIZED` to `SETTLED`. It requires that the
    transaction is in `AUTHORIZED` and that the underlying EBT card is in
    `ACTIVE` (otherwise `ERR_CARD_NOT_ACTIVE`). On success, `settled_at`
    is stamped to `SystemClock.current_utc`, and the velocity calculation
    in §3.9 is triggered."

    Design: Difficulty/cross_entity_state_dependency/txn_settle_requires_card_active
    """
    set_clock("2026-09-15T12:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    _hh, _app, card = setup_household_with_active_card(
        case_number="OH-150001", state_code="OH",
        clock_iso="2026-09-15T12:00:00Z",
    )
    validate_success(api.suspend_ebt_card(card["id"], CW), 200)
    tx = create_purchase(
        card["id"],
        line_items=[{"category_code": "FRESH_PRODUCE",
                     "amount_cents": 5000, "quantity": 1}],
    )
    resp = api.settle_purchase_transaction(tx["id"], MER)
    validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)


def test_settle_succeeds_when_card_is_active(api):
    """Complementary positive case: with card in ACTIVE, settle succeeds
    and stamps settled_at. Confirms the gate is specifically on card status.

    PRD §3.8: "Settlement, performed by a `Merchant`, transitions the
    transaction from `AUTHORIZED` to `SETTLED`. It requires that the
    transaction is in `AUTHORIZED` and that the underlying EBT card is in
    `ACTIVE` (otherwise `ERR_CARD_NOT_ACTIVE`). On success, `settled_at`
    is stamped to `SystemClock.current_utc`, and the velocity calculation
    in §3.9 is triggered."

    Design: Difficulty/cross_entity_state_dependency/txn_settle_requires_card_active
    """
    set_clock("2026-09-15T12:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    _hh, _app, card = setup_household_with_active_card(
        case_number="OH-150002", state_code="OH",
        clock_iso="2026-09-15T12:00:00Z",
    )
    tx = create_purchase(
        card["id"],
        line_items=[{"category_code": "FRESH_PRODUCE",
                     "amount_cents": 5000, "quantity": 1}],
    )
    settled = validate_success(api.settle_purchase_transaction(tx["id"], MER), 200)
    assert settled["status"] == "SETTLED"
    assert settled.get("settled_at"), \
        f"settled_at must be stamped on settle, got {settled.get('settled_at')!r}"


# ─── Corner / validations / all_items_ineligible_purchase_rejected ──

def test_purchase_with_all_ineligible_lines_rejected(api):
    """A PurchaseTransaction whose every line resolves to an ineligible
    category — and therefore would compute total_cents == 0 — is rejected
    with ERR_ALL_ITEMS_INELIGIBLE per PRD §3.8.

    PRD §3.8: "Three create-time rejections apply, evaluated after the
    standard parent and existence checks (see §2.8). If `line_items` is
    empty, or if any line's `category_code` does not name an existing
    category, the request fails with `ERR_INVALID_LINE_ITEMS`. If every
    line resolves to an ineligible category — so the computed `total_cents`
    would be 0 — the request fails with `ERR_ALL_ITEMS_INELIGIBLE`."

    Design: Corner/validations/all_items_ineligible_purchase_rejected
    """
    set_clock("2026-09-15T00:00:00Z")
    create_eligible_category("TOBACCO", "Tobacco", False)
    _hh, _app, card = setup_household_with_active_card(
        case_number="CA-800001", state_code="CA",
        clock_iso="2026-09-15T00:00:00Z",
    )
    resp = api.create_purchase_transaction(
        {"ebt_card_id": card["id"], "merchant_id": "M1",
         "line_items": [{"category_code": "TOBACCO",
                         "amount_cents": 5000, "quantity": 1}]},
        MER,
    )
    validate_error(resp, ApiErrorId.ERR_ALL_ITEMS_INELIGIBLE.value)


# ─── Corner / validations / mixed_eligible_ineligible_purchase_excludes_ineligible_from_total ──

def test_mixed_lines_exclude_ineligible_from_total_and_list_them(api):
    """For a purchase with FRESH_PRODUCE 7000 + TOBACCO 3000, total_cents
    is 7000 (TOBACCO excluded) and ineligible_line_codes contains 'TOBACCO'.

    PRD §3.8: "The `total_cents` field of the transaction is the sum of
    `amount_cents` over those `line_items` whose `category_code` resolves
    to an `EligibleItemCategory` with `eligible` of true; the
    `category_code` values of `line_items` whose category resolves to
    `eligible` of false are collected into the transaction's
    `ineligible_line_codes` array. Ineligible lines never contribute to
    `total_cents` and are recorded informationally only."

    Design: Corner/validations/mixed_eligible_ineligible_purchase_excludes_ineligible_from_total
    """
    set_clock("2026-09-15T00:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    create_eligible_category("TOBACCO", "Tobacco", False)
    _hh, _app, card = setup_household_with_active_card(
        case_number="CA-800002", state_code="CA",
        clock_iso="2026-09-15T00:00:00Z",
    )
    resp = api.create_purchase_transaction(
        {"ebt_card_id": card["id"], "merchant_id": "M1",
         "line_items": [
             {"category_code": "FRESH_PRODUCE",
              "amount_cents": 7000, "quantity": 1},
             {"category_code": "TOBACCO",
              "amount_cents": 3000, "quantity": 1},
         ]},
        MER,
    )
    tx = validate_success(resp, 201)
    assert tx["total_cents"] == 7000, (
        f"only eligible lines contribute to total_cents; "
        f"expected 7000, got {tx['total_cents']}"
    )
    assert "TOBACCO" in tx["ineligible_line_codes"], (
        f"ineligible_line_codes must list TOBACCO, got {tx['ineligible_line_codes']!r}"
    )


# ─── Corner / validations / invalid_line_items_empty_array_rejected ──

def test_purchase_with_empty_line_items_rejected(api):
    """An empty line_items array is rejected with ERR_INVALID_LINE_ITEMS
    per PRD §3.8.

    PRD §3.8: "Three create-time rejections apply, evaluated after the
    standard parent and existence checks (see §2.8). If `line_items` is
    empty, or if any line's `category_code` does not name an existing
    category, the request fails with `ERR_INVALID_LINE_ITEMS`. If every
    line resolves to an ineligible category — so the computed `total_cents`
    would be 0 — the request fails with `ERR_ALL_ITEMS_INELIGIBLE`."

    Design: Corner/validations/invalid_line_items_empty_array_rejected
    """
    set_clock("2026-09-15T00:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    _hh, _app, card = setup_household_with_active_card(
        case_number="CA-800003", state_code="CA",
        clock_iso="2026-09-15T00:00:00Z",
    )
    resp = api.create_purchase_transaction(
        {"ebt_card_id": card["id"], "merchant_id": "M1",
         "line_items": []},
        MER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_LINE_ITEMS.value)
