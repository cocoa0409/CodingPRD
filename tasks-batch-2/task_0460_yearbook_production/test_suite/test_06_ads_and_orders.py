"""Commercial pipeline: ad-contract sign/place/void compensation, pre-sale pay/cancel
compensation, the delivery cascade to fulfillment + distribution, and the guards that
gate placing and cancelling.

Difficulty (queue A) and corner (queue B) instances appear here.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_ad_contract_payload,
    create_presale_order_payload,
    create_print_run_payload,
    create_yearbook,
    create_yearbook_early_window,
    create_page,
    create_active_staff_assignment,
    create_approved_page,
    create_ads_page_with_ad,
    create_signed_ad,
    create_paid_order,
    create_shipped_print_run,
    current_yearbook_version,
    TEST_USERS,
)

ADVISER = TEST_USERS["adviser_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


# ─── Compensating invariant: ad revenue sign then void ───────────────────────

def test_ad_revenue_compensated_to_zero_after_sign_then_void(api):
    """PRD §3.5: "voiding a `SIGNED` contract is a compensating action that subtracts
    its `net_price_cents` back out of the yearbook's `ad_revenue_cents`, restoring the
    figure to its pre-sign value."

    Design: Difficulty/compensating_invariant/compensating_ad_revenue_sign_then_void
    """
    yb = create_yearbook()
    page, ad = create_signed_ad(yb["id"], page_number=2, size="HALF", discount_pct=0.10)
    yb_before = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_before["ad_revenue_cents"] == 21600

    voided = validate_success(api.void_ad_contract(ad["id"], SALESREP), 200)
    assert voided["status"] == "VOIDED"
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["ad_revenue_cents"] == 0


def test_void_draft_ad_has_no_revenue_effect(api):
    """PRD §3.5: "voiding a `DRAFT` contract has no revenue effect, but voiding a
    `SIGNED` contract is a compensating action that subtracts its `net_price_cents`
    back out of the yearbook's `ad_revenue_cents`, restoring the figure to its pre-sign
    value."

    Design: Difficulty/compensating_invariant/compensating_ad_revenue_sign_then_void
    """
    # A DRAFT (never-signed) contract was never added to ad_revenue, so voiding it
    # leaves ad_revenue_cents at 0 — the conserved quantity is untouched.
    yb = create_yearbook()
    page, ad = create_ads_page_with_ad(yb["id"], page_number=2, size="HALF", discount_pct=0.10)
    validate_success(api.void_ad_contract(ad["id"], SALESREP), 200)  # DRAFT -> VOIDED
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["ad_revenue_cents"] == 0


# ─── Compensating invariant: presale revenue pay then cancel ─────────────────

def test_presale_revenue_compensated_to_zero_after_pay_then_cancel(api):
    """PRD §3.5: "or from `PAID` (moving to `CANCELLED` and compensating by subtracting
    its `total_price_cents` back out of `presale_revenue_cents`, restoring the pre-pay
    figure)."

    Design: Difficulty/compensating_invariant/compensating_presale_revenue_pay_then_cancel
    """
    yb = create_yearbook_early_window()
    order = create_paid_order(yb["id"], buyer_name="Pat", quantity=1)
    yb_before = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_before["presale_revenue_cents"] == 6500  # EARLY base, qty 1

    cancelled = validate_success(api.cancel_presale_order(order["id"], SALESREP), 200)
    assert cancelled["status"] == "CANCELLED"
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["presale_revenue_cents"] == 0


def test_cancel_placed_unpaid_order_has_no_revenue_effect(api):
    """PRD §3.5: "An order may be cancelled from `PLACED` (moving straight to
    `CANCELLED` with no revenue effect, since it was never paid) or from `PAID`
    (moving to `CANCELLED` and compensating by subtracting its `total_price_cents`
    back out of `presale_revenue_cents`, restoring the pre-pay figure)."

    Design: Difficulty/compensating_invariant/compensating_presale_revenue_pay_then_cancel
    """
    # A PLACED (unpaid) order was never added to presale_revenue, so cancelling it
    # leaves the conserved quantity at 0 — the compensation path only fires for PAID.
    yb = create_yearbook_early_window()
    order = validate_success(
        api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="Pat", quantity=1), SALESREP
        ), 201,
    )
    validate_success(api.cancel_presale_order(order["id"], SALESREP), 200)
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["presale_revenue_cents"] == 0


# ─── Cross-entity: placing an ad requires its page approved ──────────────────

def test_place_signed_ad_requires_page_approved(api):
    """PRD §3.5: "A signed contract can be placed, advancing from `SIGNED` to `PLACED`,
    but only once its referenced page has reached `APPROVED`; placing against a page
    that is not `APPROVED` is rejected with `ERR_AD_PAGE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/cross_ad_place_requires_page_approved
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 6, "ADS", template_code="T-AD")  # stays DRAFT
    ad = validate_success(
        api.create_ad_contract(
            create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Acme", size="FULL"),
            SALESREP,
        ), 201,
    )
    validate_success(api.sign_ad_contract(ad["id"], SALESREP), 200)
    res = api.place_ad_contract(ad["id"], SALESREP)
    validate_error(res, "ERR_AD_PAGE_NOT_APPROVED")


def test_place_signed_ad_succeeds_once_page_approved(api):
    """PRD §3.5: "A signed contract can be placed, advancing from `SIGNED` to `PLACED`,
    but only once its referenced page has reached `APPROVED`".

    Design: Difficulty/cross_entity_state_dependency/cross_ad_place_requires_page_approved
    """
    # Contrast with the rejection case: drive the ADS page to APPROVED, then place succeeds.
    yb = create_yearbook()
    sa = create_active_staff_assignment(yb["id"])
    page = create_approved_page(yb["id"], sa["id"], 6, "ADS", template_code="T-AD")
    ad = validate_success(
        api.create_ad_contract(
            create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Acme", size="FULL"),
            SALESREP,
        ), 201,
    )
    validate_success(api.sign_ad_contract(ad["id"], SALESREP), 200)
    placed = validate_success(api.place_ad_contract(ad["id"], SALESREP), 200)
    assert placed["status"] == "PLACED"


# ─── Terminal-state lockdown: signing a VOIDED ad ────────────────────────────

def test_sign_voided_ad_contract_returns_invalid_state(api):
    """PRD §3.5: "A contract may be voided from either `DRAFT` or `SIGNED`, moving it
    to `VOIDED`". PRD §2.6: "that the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/terminal_voided_ad_contract_cannot_sign
    """
    yb = create_yearbook()
    page, ad = create_ads_page_with_ad(yb["id"], page_number=2, size="QUARTER")
    validate_success(api.void_ad_contract(ad["id"], SALESREP), 200)  # DRAFT -> VOIDED
    res = api.sign_ad_contract(ad["id"], SALESREP)
    validate_error(res, "ERR_INVALID_STATE")


# ─── FK existence: ad contract body references missing page ──────────────────

def test_ad_contract_missing_ladder_page_returns_reference_not_found(api):
    """PRD §2.5: "Foreign-key targets named in the request body — for example the
    `ladder_page_id` a sponsor contract points at ... a missing body-referenced target
    yields `ERR_REFERENCE_NOT_FOUND` (also a 404)."

    Design: Corner/endpoints/ad_contract_body_fk_not_found_returns_reference_not_found
    """
    yb = create_yearbook()
    res = api.create_ad_contract(
        create_ad_contract_payload(yb["id"], "00000000-0000-4000-8000-000000000abc",
                                   sponsor_name="Ghost", size="HALF"),
        SALESREP,
    )
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ─── Delivery cascade: deliver -> fulfill -> distribution (depth-3) ──────────

def test_deliver_cascades_fulfill_and_distribution_record(api):
    """PRD §3.7: "every pre-sale order on the yearbook currently in `PAID` transitions
    `PAID → FULFILLED`, and each newly fulfilled order spawns a **DistributionRecord**."
    PRD §3.7: "the server copies the order's buyer name into `recipient_name` and the
    order's quantity into `copies_handed`".

    Design: Difficulty/transitive_cascade/cascade_deliver_to_fulfill_to_distribution_depth3
    """
    yb = create_yearbook_early_window()
    order = create_paid_order(yb["id"], buyer_name="Dana", quantity=3)
    run = create_shipped_print_run(yb["id"], quantity=50)
    validate_success(api.deliver_print_run(run["id"], ADVISER), 200)

    order_after = validate_success(api.get_presale_order(order["id"], SALESREP), 200)
    assert order_after["status"] == "FULFILLED"

    data, meta = _list_distribution(api, order["id"])
    matching = [r for r in data if r["presale_order_id"] == order["id"]]
    assert len(matching) == 1
    rec = matching[0]
    assert rec["copies_handed"] == 3
    assert rec["recipient_name"] == "Dana"


def test_deliver_transitions_paid_order_to_fulfilled_and_phase_delivered(api):
    """PRD §3.7: "When the run reaches `DELIVERED`, the system cascades: every pre-sale
    order on the yearbook currently in `PAID` transitions `PAID → FULFILLED`, and each
    newly fulfilled order spawns a **DistributionRecord**. The yearbook's
    `production_phase` is then recomputed to `DELIVERED`."

    Design: Difficulty/transitive_cascade/cascade_deliver_to_fulfill_to_distribution_depth3
    """
    yb = create_yearbook_early_window()
    order = create_paid_order(yb["id"], buyer_name="Dana", quantity=3)
    run = create_shipped_print_run(yb["id"], quantity=50)
    validate_success(api.deliver_print_run(run["id"], ADVISER), 200)

    order_after = validate_success(api.get_presale_order(order["id"], SALESREP), 200)
    assert order_after["status"] == "FULFILLED"
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["production_phase"] == "DELIVERED"


def _list_distribution(api, presale_order_id):
    from test_helpers import validate_paginated
    res = api.list_distribution_records(
        ADVISER, params={"presale_order_id": presale_order_id}
    )
    return validate_paginated(res)


# ─── Guard: cancelling PAID order after distribution started ─────────────────

def test_cancel_paid_order_after_shipped_returns_already_distributed(api):
    """PRD §3.5: "Cancelling a `PAID` order is blocked once the book has gone out the
    door: if any print run on the yearbook has reached `SHIPPED` or `DELIVERED`, the
    cancel is rejected with `ERR_ALREADY_DISTRIBUTED`."

    Design: Corner/state_machines/cancel_paid_order_after_shipped_returns_already_distributed
    """
    yb = create_yearbook_early_window()
    order = create_paid_order(yb["id"], buyer_name="Late", quantity=1)
    create_shipped_print_run(yb["id"], quantity=100)
    res = api.cancel_presale_order(order["id"], SALESREP)
    validate_error(res, "ERR_ALREADY_DISTRIBUTED")
