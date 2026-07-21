"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup step failed" errors, not confusing assertion failures.

The book lifecycle is deep: intake -> grade -> appraise -> list -> shelf, plus
consignment (propose -> activate) and sale drafting. These helpers encapsulate
those chains so tests focus on assertions.

Role usage (PRD §2.1):
- StoreClerk: intake, book-item, listing create, catalog edit, sale draft, shipment
- Appraiser: grade, appraisal issue
- Manager: patron/lot/fair create, settle/reject, consignment lifecycle,
  buyback accept/void, sale confirm/refund
Both StoreClerk and Manager may create patrons, lots, buyback offers, booth slots,
and sale orders; the helpers below pick a permitted role for each call.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_patron_payload, create_intake_lot_payload, create_book_item_payload,
    create_appraisal_payload, create_listing_payload,
    create_consignment_agreement_payload, create_buyback_offer_payload,
    create_fair_event_payload, create_booth_slot_payload,
    create_sale_order_payload, line_item, unique_email,
)
from .test_users import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["storeclerk_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1: single-step primitives
# ─────────────────────────────────────────────────────────────────────────────

def new_patron(email=None, display_name="Test Patron", default_commission_pct=None,
               headers=MANAGER):
    payload = create_patron_payload(display_name=display_name,
                                    email=email or unique_email())
    if default_commission_pct is not None:
        payload["default_commission_pct"] = default_commission_pct
    return get_success_data(api_client.create_patron(payload, headers))


def new_intake_lot(acquisition_channel="PURCHASE", consignor_id=None, headers=CLERK):
    payload = create_intake_lot_payload(acquisition_channel=acquisition_channel)
    if consignor_id is not None:
        payload["consignor_id"] = consignor_id
    return get_success_data(api_client.create_intake_lot(payload, headers))


def new_book_item(lot_id, title="Test Book", author="Test Author",
                  comp_median_cents=10000, printing_number=None,
                  stated_first_edition=None, headers=CLERK):
    payload = create_book_item_payload(title=title, author=author,
                                       comp_median_cents=comp_median_cents)
    if printing_number is not None:
        payload["printing_number"] = printing_number
    if stated_first_edition is not None:
        payload["stated_first_edition"] = stated_first_edition
    return get_success_data(api_client.create_book_item(lot_id, payload, headers))


def grade_item(book_id, condition_grade="GOOD", headers=APPRAISER):
    return get_success_data(
        api_client.grade_book_item(book_id, {"condition_grade": condition_grade}, headers)
    )


def issue_appraisal(book_id, expected_book_item_version, basis="FAIR_MARKET",
                    headers=APPRAISER):
    return get_success_data(
        api_client.create_appraisal(
            book_id, create_appraisal_payload(expected_book_item_version, basis=basis),
            headers)
    )


def create_listing(book_id, list_price_cents=10000, headers=CLERK):
    return get_success_data(
        api_client.create_listing(book_id, create_listing_payload(list_price_cents=list_price_cents),
                                  headers)
    )


def patch_listing(listing_id, expected_catalog_listing_version, headers=CLERK, **changes):
    payload = dict(changes)
    payload["expected_catalog_listing_version"] = expected_catalog_listing_version
    return get_success_data(api_client.update_catalog_listing(listing_id, payload, headers))


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2: book-lifecycle progressions
# ─────────────────────────────────────────────────────────────────────────────

def make_graded_book(condition_grade="GOOD", comp_median_cents=10000,
                     printing_number=None, stated_first_edition=None,
                     acquisition_channel="PURCHASE", consignor_id=None, title="Test Book"):
    """Lot + book intaken + graded. Returns the graded BookItem (carries version)."""
    lot = new_intake_lot(acquisition_channel=acquisition_channel, consignor_id=consignor_id)
    book = new_book_item(lot["id"], title=title, comp_median_cents=comp_median_cents,
                         printing_number=printing_number,
                         stated_first_edition=stated_first_edition)
    graded = grade_item(book["id"], condition_grade=condition_grade)
    return {"lot": lot, "book": graded}


def make_appraised_book(condition_grade="GOOD", basis="FAIR_MARKET",
                        comp_median_cents=10000, printing_number=None,
                        stated_first_edition=None, acquisition_channel="PURCHASE",
                        consignor_id=None, title="Test Book"):
    """Lot + book graded + appraised. Returns {lot, book (APPRAISED), appraisal}."""
    ctx = make_graded_book(condition_grade=condition_grade,
                           comp_median_cents=comp_median_cents,
                           printing_number=printing_number,
                           stated_first_edition=stated_first_edition,
                           acquisition_channel=acquisition_channel,
                           consignor_id=consignor_id, title=title)
    appraisal = issue_appraisal(ctx["book"]["id"], ctx["book"]["version"], basis=basis)
    book = get_success_data(api_client.get_book_item(ctx["book"]["id"], MANAGER))
    ctx.update({"book": book, "appraisal": appraisal})
    return ctx


def make_listed_book(condition_grade="GOOD", list_price_cents=10000,
                     comp_median_cents=10000, on_shelf=False, online_live=False,
                     acquisition_channel="PURCHASE", consignor_id=None, title="Test Book"):
    """Lot + book through LISTED, with a CatalogListing. Optionally advance an axis.
    Returns {lot, book (LISTED), appraisal, listing}."""
    ctx = make_appraised_book(condition_grade=condition_grade,
                              comp_median_cents=comp_median_cents,
                              acquisition_channel=acquisition_channel,
                              consignor_id=consignor_id, title=title)
    listing = create_listing(ctx["book"]["id"], list_price_cents=list_price_cents)
    if on_shelf:
        listing = patch_listing(listing["id"], listing["version"], shop_status="ON_SHELF")
    if online_live:
        listing = patch_listing(listing["id"], listing["version"], online_status="LIVE")
    book = get_success_data(api_client.get_book_item(ctx["book"]["id"], MANAGER))
    ctx.update({"book": book, "listing": listing})
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3: consignment + sale scenarios
# ─────────────────────────────────────────────────────────────────────────────

def setup_consigned_shelved(commission_pct=0.30, fee_model="GROSS_COMMISSION",
                            flat_fee_cents=0, comp_median_cents=20000, grade="VERY_GOOD",
                            list_price_cents=30000, activate=True):
    """Patron + consigned book LISTED and shelved (shop_status ON_SHELF) with a
    consignment agreement (ACTIVE when activate=True, else PROPOSED).
    Returns {patron, lot, book, appraisal, listing, agreement}."""
    patron = new_patron()
    ctx = make_listed_book(condition_grade=grade, list_price_cents=list_price_cents,
                           comp_median_cents=comp_median_cents, on_shelf=True,
                           acquisition_channel="CONSIGNMENT", consignor_id=patron["id"])
    ag_payload = create_consignment_agreement_payload(
        patron["id"], ctx["book"]["id"], commission_pct=commission_pct,
        fee_model=fee_model, flat_fee_cents=flat_fee_cents)
    agreement = get_success_data(api_client.create_consignment_agreement(ag_payload, MANAGER))
    if activate:
        agreement = get_success_data(
            api_client.activate_consignment_agreement(agreement["id"], MANAGER))
    ctx.update({"patron": patron, "agreement": agreement})
    return ctx


def draft_shop_order(book_id, sale_price_cents, buyer_patron_id=None,
                     store_credit_applied_cents=0, discount_pct=0, tax_pct=None,
                     channel="SHOP"):
    """Draft a SaleOrder for a single line item. Returns the SaleOrder."""
    payload = create_sale_order_payload(
        channel, [line_item(book_id, sale_price_cents, discount_pct=discount_pct)])
    if buyer_patron_id is not None:
        payload["buyer_patron_id"] = buyer_patron_id
    if store_credit_applied_cents:
        payload["store_credit_applied_cents"] = store_credit_applied_cents
    if tax_pct is not None:
        payload["tax_pct"] = tax_pct
    return get_success_data(api_client.create_sale_order(payload, CLERK))


def setup_confirmed_consigned_sale(commission_pct=0.30, fee_model="GROSS_COMMISSION",
                                   flat_fee_cents=0, sale_price_cents=30000,
                                   comp_median_cents=20000):
    """Full path to a CONFIRMED sale of a consigned, shelved book.
    Returns {patron, book, listing, agreement, order}."""
    ctx = setup_consigned_shelved(commission_pct=commission_pct, fee_model=fee_model,
                                  flat_fee_cents=flat_fee_cents,
                                  comp_median_cents=comp_median_cents,
                                  list_price_cents=sale_price_cents, activate=True)
    order = draft_shop_order(ctx["book"]["id"], sale_price_cents,
                             buyer_patron_id=None, channel="SHOP")
    order = get_success_data(api_client.confirm_sale_order(order["id"], MANAGER))
    ctx["order"] = order
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Tier 4: buyback / store-credit scenarios
# ─────────────────────────────────────────────────────────────────────────────

def make_buyback_offer(offer_value_cents, patron_id=None, book_item_id=None, headers=CLERK):
    """Create a buyback offer. Returns {patron, offer}."""
    if patron_id is None:
        patron = new_patron()
        patron_id = patron["id"]
    else:
        patron = None
    payload = create_buyback_offer_payload(patron_id, offer_value_cents)
    if book_item_id is not None:
        payload["book_item_id"] = book_item_id
    offer = get_success_data(api_client.create_buyback_offer(payload, headers))
    return {"patron_id": patron_id, "patron": patron, "offer": offer}


def make_accepted_buyback(offer_value_cents, patron_id=None):
    """Patron + an ACCEPTED buyback offer (store credit issued). Returns {patron_id, offer}."""
    ctx = make_buyback_offer(offer_value_cents, patron_id=patron_id)
    offer = get_success_data(api_client.accept_buyback_offer(ctx["offer"]["id"], MANAGER))
    ctx["offer"] = offer
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Tier 5: fair / booth and shipment scenarios
# ─────────────────────────────────────────────────────────────────────────────

def make_fair_with_slot(table_capacity=10, booth_table="T1",
                        window_start="2026-07-10T10:00:00.000Z",
                        window_end="2026-07-10T12:00:00.000Z", display_item_count=1):
    """FairEvent + one RESERVED booth slot. Returns {fair, slot}."""
    fair = get_success_data(
        api_client.create_fair_event(create_fair_event_payload(table_capacity=table_capacity),
                                     MANAGER))
    slot_payload = create_booth_slot_payload(booth_table, window_start, window_end,
                                             display_item_count=display_item_count)
    slot = get_success_data(api_client.create_booth_slot(fair["id"], slot_payload, CLERK))
    return {"fair": fair, "slot": slot}


def make_order_with_shipment(packing_station_label, pack_start, pack_end,
                             weight_grams=400, zone=1, channel="ONLINE"):
    """A DRAFT sale order with one packed shipment. Returns {order, shipment}."""
    order = get_success_data(
        api_client.create_sale_order(create_sale_order_payload(channel, []), CLERK))
    from .factories import create_shipment_payload
    ship_payload = create_shipment_payload(packing_station_label, weight_grams, zone,
                                           pack_start, pack_end)
    shipment = get_success_data(api_client.create_shipment(order["id"], ship_payload, CLERK))
    return {"order": order, "shipment": shipment}


def make_empty_sale_order(channel="ONLINE"):
    """A DRAFT sale order with an empty line_items array. Returns the order."""
    return get_success_data(
        api_client.create_sale_order(create_sale_order_payload(channel, []), CLERK))
