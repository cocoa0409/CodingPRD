"""Validation outcomes and the fixed validation-priority ordering
(PRD §2.10, §3.9)."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_cardholder_headers,
    set_clock,
    create_product,
    create_quarterly_category,
    create_active_account,
    setup_account_with_balance,
    create_redemption,
    account_version,
    ApiErrorId,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OPS = TEST_USERS["rewards_ops_headers"]


def test_state_beats_insufficient_points_on_confirm(api):
    """PRD §2.10: "the checks are evaluated in a fixed priority order, and the
    first failure determines the error returned. The order is: ... (7) the target
    resource being in the correct state for the operation, yielding
    `ERR_INVALID_STATE`; ... and finally (13) sufficiency of redeemable points,
    yielding `ERR_INSUFFICIENT_POINTS`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_insufficient_points_on_confirm
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, txn = setup_account_with_balance(
        amount_cents=100000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )  # balance 1000
    # Create a redemption within balance (PRD §3.8 validates the balance at create
    # time), then take it out of PENDING by rejecting it.
    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 1000, account_version(acct["id"]))
    validate_success(api.reject_redemption(red["id"], _OPS))  # now REJECTED, not PENDING
    # Refund the minting transaction so the balance is clawed back to 0 — now the
    # redemption is BOTH non-PENDING (p7) AND over balance (p13) at confirm time.
    validate_success(api.refund_transaction(txn["id"], _ADMIN))
    # Confirm now fails: state (p7) outranks insufficient-points (p13).
    res = api.confirm_redemption(red["id"], _OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_cross_product_beats_duplicate_on_activation(api):
    """PRD §2.10: "(8) cross-product referential integrity, yielding
    `ERR_CROSS_PRODUCT_MISMATCH`; (9) uniqueness constraints, yielding
    `ERR_DUPLICATE_ACTIVATION`".
    PRD §3.9: "The referenced `QuarterlyCategory` must belong to the account's
    product — its `card_product_id` must equal the account's `card_product_id` —
    and a mismatch is rejected with `ERR_CROSS_PRODUCT_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/cross_product_beats_duplicate_on_activation
    """
    set_clock("2026-07-01T00:00:00Z")
    p1 = create_product(name="P1 Visa")
    p2 = create_product(name="P2 Visa")
    qcat_p2 = create_quarterly_category(
        p2["id"], code="GROCERY", quarter_label="2026-Q3",
        window_start="2026-07-01T00:00:00Z", window_end="2026-10-01T00:00:00Z",
        earn_multiplier_bps=500, bonus_cap_cents=50000,
    )
    acct = create_active_account(card_product_id=p1["id"])
    # The quarterly category belongs to P2, so the p8 cross-product check fires
    # before the p9 duplicate check (and no prior activation exists anyway).
    res = api.create_category_activation(
        {"card_account_id": acct["id"], "quarterly_category_id": qcat_p2["id"]},
        make_cardholder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CROSS_PRODUCT_MISMATCH.value)


def test_duplicate_active_activation_rejected(api):
    """PRD §3.9: "There may be at most one `ACTIVE` activation for a given pairing
    of `card_account_id` and `quarterly_category_id`; a second is rejected with
    `ERR_DUPLICATE_ACTIVATION` (HTTP 409)."

    Design: Corner/validations/duplicate_active_activation_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Q Visa", signup_bonus_spend_threshold_cents=999999, signup_bonus_window_days=365)
    qcat = create_quarterly_category(
        prod["id"], code="GROCERY", quarter_label="2026-Q3",
        window_start="2026-07-01T00:00:00Z", window_end="2026-10-01T00:00:00Z",
        earn_multiplier_bps=500, bonus_cap_cents=50000,
    )
    acct = create_active_account(card_product_id=prod["id"])
    chh = make_cardholder_headers(acct["id"])
    validate_success(
        api.create_category_activation(
            {"card_account_id": acct["id"], "quarterly_category_id": qcat["id"]}, chh
        ),
        expected_status=201,
    )
    res = api.create_category_activation(
        {"card_account_id": acct["id"], "quarterly_category_id": qcat["id"]}, chh
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVATION.value)
