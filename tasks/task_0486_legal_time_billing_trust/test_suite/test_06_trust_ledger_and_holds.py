"""Trust deposits/disbursements/confirm/reverse, three-way reconciliation, the
no-overdraw rule, retainer-hold closed-interval overlap, and hold release.

Queue A: compensating_invariant (trust reverse three-way),
resource_temporal_overlap (retainer holds). Queue B: state_machines (tx + hold),
calculations (three-way pending lag), validations (overdraw), endpoints (FK
transactions), cross_cutting (ledger aggregation).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    make_attorney_headers,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_trust_transaction_payload, create_retainer_hold_payload,
    setup_trust_account_and_ledger, setup_funded_ledger, post_deposit,
    setup_ledger_with_active_hold, create_client,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
ATT = TEST_USERS["attorney_headers"]
ATT9 = make_attorney_headers("att-9")


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / trust_reverse_preserves_three_way
# ---------------------------------------------------------------------------
def test_reverse_confirmed_deposit_zeroes_all_three_legs(api):
    """PRD §3.8: "Reversing a `CONFIRMED` transaction also sets `status` to
    `VOIDED` and reverses the sub-ledger and book legs, and additionally subtracts
    the signed amount from `bank_balance_cents` because that transaction had
    already cleared; both versions increment." PRD §3.8: "a `reconciled` boolean
    that is true only when all three legs are equal".

    Design: Difficulty/compensating_invariant/trust_reverse_preserves_three_way
    """
    base = setup_funded_ledger(deposit_cents=100000, confirm=True)
    dep_id = base["deposit_tx"]["id"]
    ta_id = base["trust_account"]["id"]
    validate_success(api.reverse_trust_transaction(dep_id, ATT9))
    recon = validate_success(api.get_reconciliation(ta_id, CLERK))
    assert recon["leg_book_cents"] == 0
    assert recon["leg_client_cents"] == 0
    assert recon["leg_bank_cents"] == 0


def test_reverse_confirmed_deposit_reports_reconciled(api):
    """PRD §3.8: "The three-way reconciliation report for an account returns the
    book leg as `leg_book_cents`, the summed client sub-ledgers as
    `leg_client_cents`, the bank leg as `leg_bank_cents`, a `reconciled` boolean
    that is true only when all three legs are equal".

    Design: Difficulty/compensating_invariant/trust_reverse_preserves_three_way
    """
    base = setup_funded_ledger(deposit_cents=100000, confirm=True)
    dep_id = base["deposit_tx"]["id"]
    ta_id = base["trust_account"]["id"]
    validate_success(api.reverse_trust_transaction(dep_id, ATT9))
    recon = validate_success(api.get_reconciliation(ta_id, CLERK))
    assert recon["reconciled"] is True


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / retainer_hold_closed_interval_touching_collides
# ---------------------------------------------------------------------------
def test_touching_retainer_hold_collides(api):
    """PRD §3.9: "Two holds on the same sub-ledger may not overlap, and because
    the interval is closed the endpoints collide: a new hold whose start equals an
    existing active hold's end (or vice versa) does overlap and is rejected".
    PRD §3.9: "Any overlap with an `ACTIVE` hold on the same sub-ledger is rejected
    with `ERR_HOLD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/retainer_hold_closed_interval_touching_collides
    """
    base = setup_ledger_with_active_hold(amount_cents=20000,
                                         hold_start_at="2026-06-01T00:00:00Z",
                                         hold_end_at="2026-06-10T00:00:00Z")
    led_id = base["ledger"]["id"]
    # New hold starts exactly at the existing hold's end -> closed-interval collision.
    payload = create_retainer_hold_payload(led_id, 15000,
                                           "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z")
    validate_error(api.create_retainer_hold(payload, CLERK), ApiErrorId.ERR_HOLD_OVERLAP)


def test_non_touching_retainer_hold_after_gap_allowed(api):
    """PRD §3.9: "Two holds on the same sub-ledger may not overlap, and because
    the interval is closed the endpoints collide: a new hold whose start equals an
    existing active hold's end (or vice versa) does overlap and is rejected — this
    is stricter than the half-open time-entry interval, where touching endpoints
    are allowed."

    Design: Difficulty/resource_temporal_overlap/retainer_hold_closed_interval_touching_collides
    """
    base = setup_ledger_with_active_hold(amount_cents=20000,
                                         hold_start_at="2026-06-01T00:00:00Z",
                                         hold_end_at="2026-06-10T00:00:00Z")
    led_id = base["ledger"]["id"]
    # A strictly-later, non-overlapping window is accepted.
    payload = create_retainer_hold_payload(led_id, 15000,
                                           "2026-06-11T00:00:00Z", "2026-06-20T00:00:00Z")
    validate_success(api.create_retainer_hold(payload, CLERK), expected_status=201)


# ---------------------------------------------------------------------------
# Section 2 — State Machines (trust tx + hold) (queue B)
# ---------------------------------------------------------------------------
def test_confirm_already_confirmed_tx_invalid_state(api):
    """PRD §3.8: "Confirming a `PENDING` transaction — a `BillingClerk` action —
    records that it cleared at the bank: it sets `status` to `CONFIRMED`".

    Design: Corner/state_machines/confirm_already_confirmed_tx_invalid_state
    """
    base = setup_funded_ledger(deposit_cents=100000, confirm=True)
    dep_id = base["deposit_tx"]["id"]
    validate_error(api.confirm_trust_transaction(dep_id, CLERK), ApiErrorId.ERR_INVALID_STATE)


def test_reverse_already_voided_tx_invalid_state(api):
    """PRD §3.8: "Reversing a still-`PENDING` transaction sets its `status` to
    `VOIDED`". PRD §2.10: "Only after those gates does the system evaluate whether
    the target resource is in a legal state for the requested transition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/reverse_already_voided_tx_invalid_state
    """
    base = setup_funded_ledger(deposit_cents=100000, confirm=False)
    dep_id = base["deposit_tx"]["id"]
    validate_success(api.reverse_trust_transaction(dep_id, ATT9))
    # VOIDED is terminal -> a second reverse is invalid.
    validate_error(api.reverse_trust_transaction(dep_id, ATT9), ApiErrorId.ERR_INVALID_STATE)


def test_retainer_hold_release_then_overlap_now_allowed(api):
    """PRD §3.9: "releasing sets its `status` to `RELEASED`, frees the window so a
    later active hold may occupy it, and increments the hold's `version`."

    Design: Corner/state_machines/retainer_hold_release_then_overlap_now_allowed
    """
    base = setup_ledger_with_active_hold(amount_cents=20000,
                                         hold_start_at="2026-06-01T00:00:00Z",
                                         hold_end_at="2026-06-10T00:00:00Z")
    led_id = base["ledger"]["id"]
    h1_id = base["hold"]["id"]
    released = validate_success(api.release_retainer_hold(h1_id, CLERK))
    assert released["status"] == "RELEASED"
    # An overlapping window now succeeds because the released hold no longer occupies it.
    payload = create_retainer_hold_payload(led_id, 25000,
                                           "2026-06-05T00:00:00Z", "2026-06-15T00:00:00Z")
    validate_success(api.create_retainer_hold(payload, CLERK), expected_status=201)


# ---------------------------------------------------------------------------
# Section 3 — Calculations (three-way pending lag) (queue B)
# ---------------------------------------------------------------------------
def test_three_way_book_vs_bank_pending_lag(api):
    """PRD §2.8: "The bank leg is allowed to lag: `bank_balance_cents` moves only
    when a transaction clears at the bank, so while any transaction is still
    pending the bank leg trails the book leg by the signed total of those pending
    transactions." PRD §3.8: "an `unconfirmed_cents` figure equal to the book leg
    minus the bank leg — the magnitude still pending at the bank."

    Design: Corner/calculations/three_way_book_vs_bank_pending_lag
    """
    base = setup_funded_ledger(deposit_cents=100000, confirm=False)  # PENDING deposit
    ta_id = base["trust_account"]["id"]
    recon = validate_success(api.get_reconciliation(ta_id, CLERK))
    assert recon["leg_book_cents"] == 100000
    assert recon["leg_client_cents"] == 100000
    assert recon["leg_bank_cents"] == 0
    assert recon["reconciled"] is False
    assert recon["unconfirmed_cents"] == 100000


# ---------------------------------------------------------------------------
# Section 4 — Validations (overdraw) (queue B)
# ---------------------------------------------------------------------------
def test_trust_overdraw_rejected(api):
    """PRD §3.8: "A `DISBURSEMENT` or `SWEEP_TO_OPERATING` may never drive the
    sub-ledger's `balance_cents` below zero — a client's trust funds may never
    cover another client's obligation — and any such overdraw is rejected with
    `ERR_TRUST_OVERDRAW` (HTTP 422)."

    Design: Corner/validations/trust_overdraw_rejected
    """
    base = setup_funded_ledger(deposit_cents=10000, confirm=True)
    led_id = base["ledger"]["id"]
    # initiated_by must differ from the approving attorney's X-User-ID (att-9) so the
    # segregation-of-duties gate (PRD §2.10 precedence) passes and the no-overdraw rule
    # is the one exercised. PRD §3.8: "the approving attorney's `X-User-ID` must differ
    # from the transaction's `initiated_by_user_id`."
    payload = create_trust_transaction_payload(led_id, "DISBURSEMENT", 30000, "clerk-1")
    validate_error(api.create_trust_transaction(payload, ATT9), ApiErrorId.ERR_TRUST_OVERDRAW)


# ---------------------------------------------------------------------------
# Section 5 — Endpoints (FK transactions) (queue B)
# ---------------------------------------------------------------------------
def test_fk_reverse_trust_transactions_by_ledger(api):
    """PRD §4 endpoint table: "GET `/firm/trust-ledgers/{id}/transactions` | List
    a sub-ledger's transactions".

    Design: Corner/endpoints/fk_reverse_trust_transactions_by_ledger
    """
    base = setup_trust_account_and_ledger()
    led_id = base["ledger"]["id"]
    tx = post_deposit(led_id, 100000)
    data, _ = validate_paginated(api.list_ledger_transactions(led_id, CLERK))
    assert any(t["id"] == tx["id"] for t in data)


# ---------------------------------------------------------------------------
# Section 8 — Cross-cutting (ledger aggregation) (queue B)
# ---------------------------------------------------------------------------
def test_trust_ledger_idempotent_per_account_client(api):
    """PRD §3.8: "Posting a transaction is immediate on the book side: it adjusts
    the sub-ledger's `balance_cents` and the account's `book_balance_cents` by the
    signed amount".

    Design: Corner/cross_cutting_complexity_layers/trust_ledger_idempotent_per_account_client
    """
    base = setup_trust_account_and_ledger()
    led_id = base["ledger"]["id"]
    post_deposit(led_id, 40000, confirm=True)
    post_deposit(led_id, 60000, confirm=True)
    led = validate_success(api.get_trust_ledger(led_id, CLERK))
    assert led["balance_cents"] == 100000
