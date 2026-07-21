"""Special orders: quote OCC, deposit gating, state preconditions, quantity validation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures, factories,
)

STAFF = fixtures.STAFF


# ---------------------------------------------------------------------------
# Queue B — state_machines / special_order_confirm_from_requested_returns_invalid_state
# ---------------------------------------------------------------------------

def test_confirm_unquoted_special_order_rejected(api):
    """PRD §3.8: "On success the deposit is debited from `wallet_credit_cents` and
    the order moves to `CONFIRMED`; confirming anything not `QUOTED` yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/special_order_confirm_from_requested_returns_invalid_state
    """
    member, member_headers, product, so = fixtures.setup_requested_special_order(api)
    validate_error(api.confirm_special_order(so["id"], member_headers),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue B — validations / special_order_invalid_quantity_returns_422
# ---------------------------------------------------------------------------

def test_special_order_zero_quantity_rejected(api):
    """PRD §3.8: "It is opened with a `member_id`, a `product_id`, and a
    `quantity` greater than 0 (otherwise `ERR_INVALID_QUANTITY`), and starts
    `REQUESTED`".

    Design: Corner/validations/special_order_invalid_quantity_returns_422
    """
    member, member_headers = fixtures.create_active_member(api)
    product = fixtures.create_product(api, retail_price_cents=50000)
    validate_error(api.create_special_order(
        factories.special_order_payload(member["id"], product["id"], quantity=0), member_headers),
        ApiErrorId.ERR_INVALID_QUANTITY.value)


# ---------------------------------------------------------------------------
# Queue B — errors / special_order_confirm_insufficient_wallet_returns_402
# ---------------------------------------------------------------------------

def test_confirm_with_insufficient_wallet_rejected(api):
    """PRD §3.8: "The member confirms a `QUOTED` order, which computes the required
    `deposit_cents` as the floor of the `quoted_price_cents` multiplied by the
    deposit rate of 0.20. Confirmation requires the member's `wallet_credit_cents`
    to be at least that deposit; if the wallet cannot cover it the confirm is
    rejected with `ERR_INSUFFICIENT_WALLET`."

    Design: Corner/errors/special_order_confirm_insufficient_wallet_returns_402
    """
    member, member_headers, product, so_q, v0 = fixtures.setup_quoted_special_order(
        api, quoted_price_cents=50000)
    validate_error(api.confirm_special_order(so_q["id"], member_headers),
                   ApiErrorId.ERR_INSUFFICIENT_WALLET.value)


# ---------------------------------------------------------------------------
# Queue B — cross_cutting / special_order_requote_stale_version_returns_412
# ---------------------------------------------------------------------------

def test_requote_with_stale_version_rejected(api):
    """PRD §2.7: "The server compares it to the order's current `version`: if
    another writer has advanced the order's version since the client last read it,
    the re-quote is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a
    staffer working from a stale view from silently overwriting a newer quote."

    Design: Corner/cross_cutting/special_order_requote_stale_version_returns_412
    """
    member, member_headers, product, so_q, v0 = fixtures.setup_quoted_special_order(
        api, quoted_price_cents=50000)
    validate_error(api.quote_special_order(
        so_q["id"], {"quoted_price_cents": 52000, "expected_special_order_version": v0}, STAFF),
        ApiErrorId.ERR_STALE_VERSION.value)
