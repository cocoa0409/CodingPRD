"""Special-order quote revision cycle, the confirm precondition, and the
optimistic-concurrency guard on re-quotes."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_store, new_member, new_special_order, quote,
    setup_special_order_in_review, setup_special_order_quoted,
    api_client, TEST_USERS,
)

ASSOCIATE = TEST_USERS["associate_headers"]


# ─── special_order_requote_cycle_back_to_quoted (queue A) ───

def test_request_changes_loops_review_back_to_quoted():
    """PRD §3.9: "From `QUOTED`, the associate submits the quote for customer
    review, moving it to `CUSTOMER_REVIEW`. From `CUSTOMER_REVIEW`, the associate
    may loop the order back to `QUOTED` to request further changes, restarting the
    revision cycle."

    Design: Difficulty/non_linear_state_machine/special_order_requote_cycle_back_to_quoted
    """
    ctx = setup_special_order_in_review()
    looped = validate_success(api_client.request_special_order_changes(
        ctx["special_order"]["id"], ASSOCIATE))
    assert looped["status"] == "QUOTED", f"expected QUOTED, got {looped['status']}"


def test_quote_revision_unchanged_by_review_transitions():
    """PRD §3.9: "Each quote sets the `quoted_price_cents`, increments
    `quote_revision` by one, and increments the order's `version` by one; a stale
    `expected_special_order_version` is rejected with `ERR_STALE_VERSION`."

    Design: Difficulty/non_linear_state_machine/special_order_requote_cycle_back_to_quoted
    """
    ctx = setup_special_order_in_review()
    looped = validate_success(api_client.request_special_order_changes(
        ctx["special_order"]["id"], ASSOCIATE))
    # Only the single quote incremented quote_revision; submit/request-changes do not.
    assert looped["quote_revision"] == 1, f"expected quote_revision 1, got {looped['quote_revision']}"


# ─── confirm_special_order_from_quoted_not_reviewable (queue B) ───

def test_confirm_from_quoted_not_reviewable():
    """PRD §3.9: "From `CUSTOMER_REVIEW`, the associate confirms the special order,
    moving it to the terminal `CONFIRMED` state; confirmation is permitted only from
    `CUSTOMER_REVIEW` (otherwise `ERR_SPECIAL_ORDER_NOT_REVIEWABLE`) and requires the
    owning `LoyaltyMember` to be `ACTIVE`."

    Design: Corner/state_machines/confirm_special_order_from_quoted_not_reviewable
    """
    ctx = setup_special_order_quoted(quoted_price_cents=40000)
    resp = api_client.confirm_special_order(ctx["special_order"]["id"], ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_SPECIAL_ORDER_NOT_REVIEWABLE.value)


# ─── special_order_requote_stale_version_rejected (queue B) ───

def test_requote_with_stale_version_rejected():
    """PRD §2.10: "The quote action requires the caller to supply
    `expected_special_order_version`, carrying the `version` of the special order the
    client last observed. If that value does not equal the special order's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/special_order_requote_stale_version_rejected
    """
    store = new_store(name="Store OCC1")
    member = new_member(email="occ1@x.com", full_name="OCC One")
    so = new_special_order(store["id"], member["id"], "Custom hutch")
    quote(so["id"], 30000, so["version"])  # advances version to 2
    resp = api_client.quote_special_order(
        so["id"], {"quoted_price_cents": 31000, "expected_special_order_version": so["version"]},
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    read = validate_success(api_client.get_special_order(so["id"], ASSOCIATE))
    assert read["quoted_price_cents"] == 30000, (
        f"rejected re-quote must not overwrite the price, got {read['quoted_price_cents']}")


# ─── requote_with_current_version_succeeds (queue B) ───

def test_requote_with_current_version_supersedes():
    """PRD §3.9: "from `QUOTED`, quoting again re-quotes in place (a self-loop that
    stays `QUOTED`), superseding the prior quote. Each quote sets the
    `quoted_price_cents`, increments `quote_revision` by one, and increments the
    order's `version` by one".

    Design: Corner/cross_cutting_complexity_layers/requote_with_current_version_succeeds
    """
    store = new_store(name="Store OCC2")
    member = new_member(email="occ2@x.com", full_name="OCC Two")
    so = new_special_order(store["id"], member["id"], "Custom bench")
    quoted = quote(so["id"], 20000, so["version"])
    requoted = quote(so["id"], 22000, quoted["version"])
    assert requoted["quoted_price_cents"] == 22000, f"got {requoted['quoted_price_cents']}"
    assert requoted["quote_revision"] == 2, f"expected quote_revision 2, got {requoted['quote_revision']}"
