"""Confirmation preconditions evaluated in fixed priority order, plus auth gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_draft_line, setup_quoted_order, setup_quoted_paid_unapproved_art,
    setup_catalog_customer_order,
)

AM = TEST_USERS["account_manager_headers"]


# ---- queue A: state check pre-empts referential --------------------------

def test_confirm_on_draft_with_unapproved_art_returns_not_quoted(api):
    """PRD 3.6: "The order must be in `QUOTED`, else `ERR_ORDER_NOT_QUOTED`."
    PRD 2.9: "The order is: ... (4) resource state ... (5) cross-entity referential
    rules; (6) temporal rules; (7) quantity, capacity, and value constraints; (8)
    fiscal (money) rules; and (9) low-cost field-format checks on time windows."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_art_referential
    """
    ctx = setup_draft_line()
    resp = api.confirm_order(ctx["order_id"], AM)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_QUOTED)


def test_confirm_on_draft_leaves_order_draft(api):
    """PRD 3.6: "Confirming an order is the gate between sales and the shop floor
    and is performed by an `AccountManager`, advancing `fulfillment_status` from
    `QUOTED` to `CONFIRMED`."
    PRD 3.6: "The order must be in `QUOTED`, else `ERR_ORDER_NOT_QUOTED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_art_referential
    """
    ctx = setup_draft_line()
    api.confirm_order(ctx["order_id"], AM)
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["fulfillment_status"] == "DRAFT"


# ---- queue A: temporal check pre-empts fiscal ----------------------------

def test_confirm_short_lead_no_deposit_returns_lead_time(api):
    """PRD 3.6: "Then, as a temporal check, the whole-day lead from the current
    logical-clock date to the `in_hands_date` must be at least 3 days, else
    `ERR_INSUFFICIENT_LEAD_TIME`. Finally, as a fiscal check, the order's
    `escrow_cents` must be at least `deposit_required_cents`, else `ERR_DEPOSIT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_beats_fiscal
    """
    ctx = setup_quoted_order(in_hands_date="2026-05-03T00:00:00Z")
    resp = api.confirm_order(ctx["order_id"], AM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LEAD_TIME)


def test_confirm_short_lead_leaves_order_quoted(api):
    """PRD 3.6: "Then, as a temporal check, the whole-day lead from the current
    logical-clock date to the `in_hands_date` must be at least 3 days, else
    `ERR_INSUFFICIENT_LEAD_TIME`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_beats_fiscal
    """
    ctx = setup_quoted_order(in_hands_date="2026-05-03T00:00:00Z")
    api.confirm_order(ctx["order_id"], AM)
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["fulfillment_status"] == "QUOTED"


# ---- queue A: cross-entity art requirement -------------------------------

def test_confirm_requires_all_lines_art_approved(api):
    """PRD 3.6: "Then, as a cross-entity referential check, every non-cancelled line
    must have an `APPROVED` art proof — that is, `art_complete` must be true — else
    `ERR_ART_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_all_lines_art_approved
    """
    ctx = setup_quoted_paid_unapproved_art()
    resp = api.confirm_order(ctx["order_id"], AM)
    validate_error(resp, ApiErrorId.ERR_ART_NOT_APPROVED)


def test_confirm_blocked_by_pending_art_leaves_order_quoted(api):
    """PRD 3.6: "Then, as a cross-entity referential check, every non-cancelled line
    must have an `APPROVED` art proof — that is, `art_complete` must be true — else
    `ERR_ART_NOT_APPROVED`."
    PRD 3.3: "The order's `art_complete` becomes true precisely when every
    non-cancelled line has an `APPROVED` proof."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_all_lines_art_approved
    """
    ctx = setup_quoted_paid_unapproved_art()
    api.confirm_order(ctx["order_id"], AM)
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["fulfillment_status"] == "QUOTED"
    assert order["art_complete"] is False


# ---- corner: RBAC role denial --------------------------------------------

def test_customer_cannot_quote_order(api):
    """PRD 2.1: "When the role is valid but not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_quote_returns_unauthorized
    """
    ctx = setup_draft_line()
    resp = api.quote_order(ctx["order_id"], ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["fulfillment_status"] == "DRAFT"


# ---- corner: missing auth headers ----------------------------------------

def test_missing_user_headers_returns_unauthenticated(api):
    """PRD 2.1: "A request missing either header, or presenting an X-User-Role that
    is not one of the four recognized roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_user_headers_returns_unauthenticated
    """
    ctx = setup_catalog_customer_order()
    resp = api.get_order(ctx["order_id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
