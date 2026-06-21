"""Lot-term and paddle validations, list-endpoint pagination/filtering, body-FK
errors, and role-based access control.
"""
from test_helpers import validate_success, validate_error, validate_paginated, get_success_data
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    setup_base_scene, setup_sold_lot, create_premium_schedule, create_seller,
    create_active_consignment, create_cataloging_sale, create_bidder,
    ADMIN, AUCTIONEER, FINANCE,
)
from test_helpers.test_users import TEST_USERS, make_role_headers
from test_helpers.factories import create_lot_payload, FLAT_TIERS, STANDARD_TIERS


# ===========================================================================
# Queue B — validations section (lot terms / paddles)
# ===========================================================================
def test_reserve_above_low_estimate_rejected(api):
    """PRD §3.3: "The estimates must be ordered so that the low estimate is
    greater than 0 and no greater than the high estimate ...; the reserve must
    not exceed the low estimate. Any of these orderings being violated yields
    `ERR_INVALID_LOT_TERMS`."

    Design: Corner/validations/reserve_above_low_estimate_rejected
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS)
    seller = create_seller()
    cons = create_active_consignment(seller["id"])
    sale = create_cataloging_sale(schedule["id"])
    payload = create_lot_payload(cons["id"], low_estimate_cents=1300000,
                                 high_estimate_cents=1800000, reserve_cents=1500000)
    resp = api.create_lot(sale["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_TERMS.value)


def test_low_estimate_above_high_rejected(api):
    """PRD §3.3: "The estimates must be ordered so that the low estimate is
    greater than 0 and no greater than the high estimate, and the high estimate
    is at least the low estimate ... Any of these orderings being violated
    yields `ERR_INVALID_LOT_TERMS`."

    Design: Corner/validations/low_estimate_above_high_rejected
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS)
    seller = create_seller()
    cons = create_active_consignment(seller["id"])
    sale = create_cataloging_sale(schedule["id"])
    payload = create_lot_payload(cons["id"], low_estimate_cents=2000000,
                                 high_estimate_cents=1800000, reserve_cents=1000000)
    resp = api.create_lot(sale["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_TERMS.value)


def test_absentee_registration_missing_max_rejected(api):
    """PRD §3.4: "The `max_absentee_bid_cents` ... is required and must be
    greater than 0 when the `registration_type` is `ABSENTEE`, and it must be 0
    for `FLOOR` and `PHONE` registrations; the default value is 0. A
    registration that violates this absentee rule is rejected with
    `ERR_INVALID_LOT_TERMS`."

    Design: Corner/validations/absentee_registration_missing_max_rejected
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS)
    bidder = create_bidder()
    sale = create_cataloging_sale(schedule["id"])
    resp = api.create_paddle_registration(
        {"auction_sale_id": sale["id"], "bidder_id": bidder["id"],
         "registration_type": "ABSENTEE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_TERMS.value)


def test_suspended_bidder_paddle_rejected(api):
    """PRD §3.4: "Registration is blocked entirely for a `SUSPENDED` bidder,
    which is rejected with `ERR_PADDLE_INELIGIBLE`."
    PRD §3.1: "A `SaleAdministrator` may adjust a bidder after the fact ...
    flipping the `status` between `ACTIVE` and `SUSPENDED`"

    Design: Corner/validations/suspended_bidder_paddle_rejected
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS)
    bidder = create_bidder()
    get_success_data(api.patch_bidder(
        bidder["id"], {"status": "SUSPENDED", "expected_bidder_version": bidder["version"]}, ADMIN))
    sale = create_cataloging_sale(schedule["id"])
    resp = api.create_paddle_registration(
        {"auction_sale_id": sale["id"], "bidder_id": bidder["id"],
         "registration_type": "FLOOR"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PADDLE_INELIGIBLE.value)


# ===========================================================================
# Queue B — endpoints section
# ===========================================================================
def test_list_lots_in_sale_paginated(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned ... The
    `meta` object on list responses carries `limit`, `offset`, `total_count`,
    and `has_more`."

    Two cataloged lots, limit=1 -> total_count 2, has_more true, one item.

    Design: Corner/endpoints/list_lots_in_sale_paginated
    """
    scene = setup_base_scene(lot_number=1)
    sale_id = scene["sale"]["id"]
    cons_id = scene["consignment"]["id"]
    get_success_data(api.create_lot(sale_id, create_lot_payload(cons_id, lot_number=2), ADMIN))
    data, meta = validate_paginated(api.list_sale_lots(sale_id, ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_lots_pagination_out_of_range(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative
    `offset`, is rejected with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/endpoints/list_lots_pagination_out_of_range
    """
    resp = api.list_lots(ADMIN, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)


def test_filter_lots_by_consignment(api):
    """PRD §2.7: "Several relationships are denormalized rather than path-nested
    and are discovered through filtered lists."
    PRD §4 (endpoint table): "GET `/lots` | List lots, filterable by
    consignment"

    Design: Corner/endpoints/filter_consignment_lots
    """
    scene = setup_base_scene(lot_number=1)
    cons_id = scene["consignment"]["id"]
    lot_id = scene["lot"]["id"]
    data, meta = validate_paginated(api.list_lots(ADMIN, params={"consignment_id": cons_id}))
    assert len(data) == 1
    assert data[0]["id"] == lot_id


# ===========================================================================
# Queue B — errors section
# ===========================================================================
def test_payment_exceeds_remaining_due_rejected(api):
    """PRD §3.6: "A payment's `amount_cents` must be greater than 0 and must not
    exceed the invoice's remaining due (its `total_due_cents` less its current
    `amount_paid_cents`); a payment of zero or less, or one that overshoots the
    remaining due, is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Invoice total_due 1,575,000; a 2,000,000 payment overshoots.

    Design: Corner/errors/payment_exceeds_remaining_due_rejected
    """
    scene = setup_sold_lot(hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    invoice = get_success_data(api.invoice_lot(lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    assert invoice["total_due_cents"] == 1575000
    resp = api.create_payment(
        invoice["id"], {"amount_cents": 2000000, "expected_invoice_version": invoice["version"]},
        FINANCE)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


def test_consignment_unknown_seller_fk_not_found(api):
    """PRD §2.9: "then body foreign-key references (`ERR_FK_NOT_FOUND`)."
    PRD §3.2: "A `SaleAdministrator` creates one in `DRAFT` status, naming the
    consignor through `seller_id`"

    Design: Corner/errors/fk_not_found_on_consignment_create
    """
    resp = api.create_consignment(
        {"seller_id": "00000000-0000-4000-8000-0000000000cc", "seller_commission_bps": 1000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


# ===========================================================================
# Queue B — rbac section
# ===========================================================================
def test_bidder_cannot_create_sale(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4 (endpoint table): "POST `/auction-sales` | Create an auction sale
    (CATALOGING) | SaleAdministrator"

    Design: Corner/rbac/bidder_cannot_create_sale
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS)
    resp = api.create_auction_sale(
        {"title": "Illicit Sale", "sale_date_utc": "2026-08-02T15:00:00Z",
         "currency": "USD", "buyers_premium_schedule_id": schedule["id"]},
        TEST_USERS["bidder_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognized
    role names, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api.get_seller("00000000-0000-4000-8000-0000000000dd", make_role_headers("u1", "NotARole"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_auctioneer_cannot_invoice(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4 (endpoint table): "POST `/lots/{id}/invoice` | Issue the buyer
    invoice for a SOLD lot (OCC-guarded) | FinanceOfficer"

    Design: Corner/rbac/auctioneer_cannot_invoice
    """
    scene = setup_sold_lot(hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, AUCTIONEER))
    resp = api.invoice_lot(lot_id, {"expected_lot_version": lot["version"]}, AUCTIONEER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
