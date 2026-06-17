"""Validation ordering, RBAC, list filtering, OCC, derived reconciliation, and
immediate consistency.

Header/auth/existence/referential/fiscal validation errors, role and ownership
denial, paginated list filtering, payout optimistic-concurrency, seat-pool count
reconciliation, and same-response charge consistency (PRD §2.1, §2.3, §2.7-§2.9,
§3.3, §3.4, §3.5, §3.7).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    TEST_USERS, make_seller_headers, make_buyer_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


# ==========================================================================
# validations section
# ==========================================================================
def test_missing_user_context_header_returns_401(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they act. If either header is missing or malformed, the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_user_context_header_returns_401
    """
    resp = api.create_venue(F.create_venue_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_existence_checked_before_state_listing_not_found(api):
    """PRD §2.8: "Third, all referenced foreign keys are resolved left to right,
    yielding the relevant not-found error."
    PRD §2.7: "The first identifier that fails to resolve produces that resource's
    specific not-found error — `ERR_EVENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_SECTION_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`,
    `ERR_BUYER_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_TRANSFER_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_CREDIT_NOT_FOUND`, or `ERR_FLAG_NOT_FOUND` — before any business rule is
    evaluated."

    Design: Corner/validations/existence_checked_before_state_listing_not_found
    """
    seller = fx.create_seller()
    resp = api.activate_listing(NON_EXISTENT_UUID, make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_FOUND.value)


def test_referential_mismatch_offer_replacement_wrong_event(api):
    """PRD §2.7: "a guarantee replacement listing must sit on the same event as the
    original order ... Any such inconsistency is rejected with
    `ERR_REFERENTIAL_MISMATCH`."

    Design: Corner/validations/referential_mismatch_offer_replacement_wrong_event
    """
    # Claim on an order of event1; offered listing lives on a DIFFERENT event2.
    ctx = fx.setup_delivery_failed_with_claim(quantity=1, reason="NOT_DELIVERED")
    other_event = fx.create_event(ctx["venue_id"], doors_open_at="2027-11-01T19:00:00.000Z",
                                  title="Other")
    other_event = fx.open_sales(other_event["id"])
    other_listing, _ = fx.create_active_listing(
        other_event["id"], ctx["seller_id"], ctx["section_id"],
        seat_count=1, barcode_prefix="RM",
    )
    resp = api.offer_replacement(
        ctx["claim"]["id"], {"offered_listing_id": other_listing["id"]}, TRUST)
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_MISMATCH.value)


def test_price_cap_exceeded_on_listing_create_returns_402(api):
    """PRD §3.3: "At creation the system validates the price against the cap:
    neither the `ask_price_cents` nor, for dynamic listings, the floor may exceed
    the section's `face_value_cents` multiplied by the event's
    `price_cap_multiplier`, and a violation is rejected with
    `ERR_PRICE_CAP_EXCEEDED`."

    Design: Corner/validations/price_cap_exceeded_on_listing_create_returns_402
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1, open_for_sale=False)
    seller_h = make_seller_headers(base["seller_id"])
    # cap = 10000*3 = 30000; ask 40000 > cap.
    payload = F.create_listing_payload(
        base["event_id"], base["seller_id"], base["section_id"], ask_price_cents=40000)
    resp = api.create_listing(payload, seller_h)
    validate_error(resp, ApiErrorId.ERR_PRICE_CAP_EXCEEDED.value)


def test_split_rule_pairs_rejects_odd_quantity(api):
    """PRD §3.4: "a `PAIRS` listing accepts only even quantities and a `WHOLE`
    listing accepts only a quantity equal to the listing's entire available pool,
    while an `ANY` listing accepts any quantity; a violation is rejected with
    `ERR_SPLIT_RULE_VIOLATION`."

    Design: Corner/validations/split_rule_pairs_rejects_odd_quantity
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=4)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=4, split_rule="PAIRS", barcode_prefix="SP",
    )
    payload = F.create_order_payload(listing["id"], base["buyer_id"], listing["version"], quantity=1)
    resp = api.create_order(payload, make_buyer_headers(base["buyer_id"]))
    validate_error(resp, ApiErrorId.ERR_SPLIT_RULE_VIOLATION.value)


def test_insufficient_wallet_credit_returns_402(api):
    """PRD §3.4: "If the buyer elects more credit than their wallet holds, the
    reservation is rejected with `ERR_INSUFFICIENT_WALLET_CREDIT`."

    Design: Corner/validations/insufficient_wallet_credit_returns_402
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="IW",
    )
    payload = F.create_order_payload(listing["id"], base["buyer_id"], listing["version"],
                                     quantity=1, applied_credit_cents=5000)
    resp = api.create_order(payload, make_buyer_headers(base["buyer_id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET_CREDIT.value)


# ==========================================================================
# rbac section
# ==========================================================================
def test_buyer_cannot_create_listing_returns_forbidden(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to
    perform the requested operation — or an ownership-scoped role is acting on a
    resource it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/buyer_cannot_create_listing_returns_forbidden
    """
    base = fx.setup_catalog(open_for_sale=False)
    payload = F.create_listing_payload(base["event_id"], base["seller_id"], base["section_id"])
    resp = api.create_listing(payload, make_buyer_headers(base["buyer_id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_buyer_cannot_charge_another_buyers_order_ownership_scope(api):
    """PRD §2.1: "A `Buyer` is likewise entity-backed ... Ownership checks on a
    buyer's orders, guarantee claims, and event credits compare the resource's
    `buyer_id` to `X-User-ID`."

    Design: Corner/rbac/buyer_cannot_charge_another_buyers_order_ownership_scope
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1)
    b2 = fx.create_buyer("B2")
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="OW",
    )
    order = fx.reserve_order(listing["id"], base["buyer_id"], 1, listing["version"])
    # B2 attempts to charge B1's order.
    resp = api.charge_order(order["id"], make_buyer_headers(b2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_seller_cannot_adjudicate_guarantee_claim_peer_isolation(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to
    perform the requested operation ... the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.7: "A `TrustSafety` operator drives adjudication. Investigation moves a
    `FILED` claim to `INVESTIGATING`."

    Design: Corner/rbac/seller_cannot_adjudicate_guarantee_claim_peer_isolation
    """
    ctx = fx.setup_charged_order(quantity=1, seat_count=1)
    seller_h = make_seller_headers(ctx["seller_id"])
    buyer_h = make_buyer_headers(ctx["buyer_id"])
    transfer = get_success_data(api.initiate_transfer(ctx["order"]["id"], seller_h))
    get_success_data(api.fail_transfer(transfer["id"], seller_h))
    claim = get_success_data(api.create_guarantee_claim(
        F.create_guarantee_claim_payload(ctx["order"]["id"], reason="NOT_DELIVERED"), buyer_h))
    # Seller (not TrustSafety) attempts to investigate.
    resp = api.investigate_claim(claim["id"], seller_h)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ==========================================================================
# endpoints section
# ==========================================================================
def test_list_listings_filter_by_event_id_returns_array(api):
    """PRD §2.3: "Every list response carries these fields in the `meta` object:
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_listings_filter_by_event_id_returns_array
    """
    base = fx.setup_catalog(open_for_sale=False)
    other = fx.create_event(base["venue_id"], doors_open_at="2026-10-01T19:00:00.000Z", title="Y")
    # Two listings on the base event, one on the other event.
    fx.create_draft_listing(base["event_id"], base["seller_id"], base["section_id"])
    fx.create_draft_listing(base["event_id"], base["seller_id"], base["section_id"],
                            ask_price_cents=21000)
    fx.create_draft_listing(other["id"], base["seller_id"], base["section_id"])

    resp = api.list_listings(make_buyer_headers(base["buyer_id"]),
                             params={"event_id": base["event_id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"exactly 2 listings on the filtered event, got {len(data)}"
    assert all(item["event_id"] == base["event_id"] for item in data)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ==========================================================================
# cross_cutting_complexity_layers section (non-stub)
# ==========================================================================
def test_occ_payout_pay_stale_version_returns_412(api):
    """PRD §2.9: "Paying a payout is anchored to the `Payout`. The pay request must
    carry `expected_payout_version`, the client's last observed `version` of that
    payout. ... if the payout's current `version` no longer matches the supplied
    `expected_payout_version`, the pay request is rejected with
    `ERR_STALE_PAYOUT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_payout_pay_stale_version_returns_412
    """
    fx.set_clock("2027-01-01T10:00:00.000Z")
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1,
                            doors_open_at="2027-01-02T19:00:00.000Z")
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="OCP",
    )
    order = fx.reserve_and_charge(listing["id"], base["buyer_id"], 1, listing["version"])
    seller_h = make_seller_headers(base["seller_id"])
    buyer_h = make_buyer_headers(base["buyer_id"])

    transfer = get_success_data(api.initiate_transfer(order["id"], seller_h))
    get_success_data(api.send_transfer(transfer["id"], seller_h))
    get_success_data(api.accept_transfer(transfer["id"], buyer_h))  # delivered

    payout = fx.get_payout_for_order(order["id"])
    stale_version = payout["version"]
    # confirm-delivery-window advances payout.version (ESCROWED → RELEASABLE).
    get_success_data(api.confirm_delivery_window(order["id"], ADMIN))

    resp = api.pay_payout(payout["id"], {"expected_payout_version": stale_version}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_PAYOUT_VERSION.value)


def test_derived_field_available_seat_count_reconciles_after_release(api):
    """PRD §3.4: "Either way the order's `HELD` seats return to `AVAILABLE`,
    `available_seat_count` is restored."
    PRD §2.5: "`held_seat_count` is the number whose `status` is `HELD`. These are
    recomputed on every seat status change and on every reservation, charge, or
    release."

    Design: Corner/cross_cutting_complexity_layers/derived_field_available_seat_count_reconciles_after_release
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=2, barcode_prefix="DF",
    )
    buyer_h = make_buyer_headers(base["buyer_id"])
    order = fx.reserve_order(listing["id"], base["buyer_id"], 1, listing["version"])

    get_success_data(api.cancel_reservation(order["id"], buyer_h))
    after = validate_success(api.get_listing(listing["id"], buyer_h))
    assert after["available_seat_count"] == 2, \
        f"available restored to 2 after release, got {after['available_seat_count']}"
    assert after["held_seat_count"] == 0, \
        f"held back to 0 after release, got {after['held_seat_count']}"


# ==========================================================================
# consistency_model section
# ==========================================================================
def test_immediate_consistency_charge_reflects_in_same_response(api):
    """PRD §3.4: "Charging commits the purchase, moving `payment_status` from
    `PENDING` to `CHARGED`. ... On charge, the final variant of the buyer-charge
    calculation runs: the `final_total_cents` and the actual `buyer_fee_cents` are
    recomputed."

    Design: Corner/consistency_model/immediate_consistency_charge_reflects_in_same_response
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="IM",
    )
    order = fx.reserve_order(listing["id"], base["buyer_id"], 1, listing["version"])
    charged = validate_success(api.charge_order(order["id"], make_buyer_headers(base["buyer_id"])))
    # qty1: base 20000, fee 2400, final 22400 — present in the charge response itself.
    assert charged["payment_status"] == "CHARGED"
    assert charged["final_total_cents"] == 22400
