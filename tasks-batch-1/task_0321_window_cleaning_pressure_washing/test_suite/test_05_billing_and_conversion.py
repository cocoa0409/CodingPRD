"""Billing guards and quote-conversion validation errors: duplicate invoice,
recurring interval requirement, referential mismatch on quote creation, and
accepting an expired quote.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_account, create_property, create_sent_quote, create_accepted_quote,
    setup_completed_visit,
    set_clock_payload,
    TEST_USERS, make_customer_headers,
)

BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# Queue B — endpoints (duplicate invoice)
# ===========================================================================
def test_second_invoice_for_same_visit_rejected(api):
    """PRD §3.7: "There is at most one invoice per visit: an invoice request naming
    a `visit_id` that already has an invoice is rejected with
    `ERR_DUPLICATE_INVOICE`."

    Design: Corner/endpoints/duplicate_invoice_for_same_visit_returns_duplicate_invoice
    """
    account, prop, agreement, visit, crew, route = setup_completed_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        after_photo_count=1)
    validate_success(api.create_invoice({"visit_id": visit["id"]}, BILLING), 201)
    res = api.create_invoice({"visit_id": visit["id"]}, BILLING)
    validate_error(res, "ERR_DUPLICATE_INVOICE", expected_status=409)


# ===========================================================================
# Queue B — errors (conversion / quote)
# ===========================================================================
def test_recurring_conversion_without_interval_rejected(api):
    """PRD §3.2: "For a `RECURRING` agreement the interval is required and must be
    at least 7 days".

    Design: Corner/errors/recurring_agreement_missing_interval_returns_invalid_request
    """
    account = create_account(region_code="NORTH")
    prop = create_property(account["id"])
    quote = create_accepted_quote(account["id"], prop["id"],
                                  pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    res = api.create_service_agreement(
        {"quote_id": quote["id"], "schedule_kind": "RECURRING"}, BILLING)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_quote_property_account_mismatch_rejected(api):
    """PRD §2.5: "When referenced resources exist individually but are not
    consistent with one another — for instance, a quote whose `property_id` points
    at a property owned by a different account than the quote's `account_id` — the
    request is rejected with `ERR_REFERENTIAL_MISMATCH`."

    Design: Corner/errors/convert_referential_mismatch_property_account_returns_referential_mismatch
    """
    account_a = create_account(region_code="NORTH")
    account_b = create_account(region_code="NORTH")
    prop_b = create_property(account_b["id"])
    res = api.create_quote(
        {"account_id": account_a["id"], "property_id": prop_b["id"],
         "pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"],
         "valid_until": "2026-12-31T00:00:00Z"}, BILLING)
    validate_error(res, "ERR_REFERENTIAL_MISMATCH", expected_status=422)


def test_accept_expired_quote_rejected(api):
    """PRD §3.1: "an accept attempt past that instant is rejected as expired with
    `ERR_QUOTE_EXPIRED`, and the quote is treated as `EXPIRED`."

    Design: Corner/errors/accept_expired_quote_returns_quote_expired
    """
    account = create_account(region_code="NORTH")
    prop = create_property(account["id"])
    quote = create_sent_quote(account["id"], prop["id"],
                              pricing_basis="PANE_COUNT", addon_codes=["GUTTER"],
                              valid_until="2026-07-01T00:00:00Z")
    validate_success(api.set_clock(set_clock_payload("2026-07-02T00:00:00Z"), BILLING), 200)
    cust = make_customer_headers(account["id"])
    res = api.accept_quote(quote["id"], cust)
    validate_error(res, "ERR_QUOTE_EXPIRED", expected_status=409)
