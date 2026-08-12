"""Used-club showcase: reservation expiry sweep, reserved-listing purchase
gating, and segregation of duties on price adjustment."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client,
    set_clock, create_customer, create_specialist, create_manager,
    submit_appraisal, issue_offer, accept_appraisal,
    get_listing_for_appraisal, customer_headers, staff_headers,
)


def _setup_listed(clubs=None, offer_staff=None):
    """Accepted appraisal -> LISTED listing. Returns ctx with listing."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer()
    specialist = offer_staff or create_specialist()
    appraisal = submit_appraisal(
        customer, clubs or [{"club_type": "WEDGE", "condition_grade": "A"}])
    appraisal = issue_offer(appraisal, specialist, "GRADE_MATRIX")
    appraisal = accept_appraisal(appraisal, customer)
    listing = get_listing_for_appraisal(appraisal["id"])
    return {"customer": customer, "specialist": specialist,
            "appraisal": appraisal, "listing": listing}


def test_listing_reservation_expiry_sweep(api):
    """PRD §3.6: "If the clock sweeps past `reserved_until` with no purchase,
    the listing falls back to `LISTED` and both reservation fields are
    cleared." and "`reserved_until` to the reserve instant plus 24 hours."

    Design: Corner/state_machines/listing_reservation_expiry_sweep
    """
    ctx = _setup_listed()
    reserver = create_customer("Gail Gale")
    reserved = get_success_data(
        api_client.reserve_listing(ctx["listing"]["id"], customer_headers(reserver))
    )
    assert reserved["status"] == "RESERVED"
    assert reserved["reserved_by_customer_id"] == reserver["id"]

    # Reserved at 2026-05-10T09:00:00Z; reserved_until is +24h.
    set_clock("2026-05-11T10:00:00Z")
    manager = create_manager()
    listing = get_success_data(
        api_client.get_listing(ctx["listing"]["id"], staff_headers(manager))
    )
    assert listing["status"] == "LISTED", (
        f"listing past reserved_until must fall back to LISTED, got {listing['status']}"
    )
    assert listing["reserved_by_customer_id"] is None
    assert listing["reserved_until"] is None


def test_listing_reserve_blocks_other_buyer(api):
    """PRD §3.6: "A `RESERVED` listing can be bought only by the customer
    holding the reservation; anyone else's purchase attempt is rejected with
    `ERR_LISTING_RESERVED_BY_OTHER` (HTTP 409), while the reserving customer's
    purchase completes the same `SOLD` transition."

    Design: Corner/endpoints/listing_reserve_blocks_other_buyer
    """
    ctx = _setup_listed()
    reserver = create_customer("Hank Hale")
    other = create_customer("Ina Inns")
    get_success_data(
        api_client.reserve_listing(ctx["listing"]["id"], customer_headers(reserver))
    )

    resp = api_client.purchase_listing(ctx["listing"]["id"], customer_headers(other))
    validate_error(resp, ApiErrorId.ERR_LISTING_RESERVED_BY_OTHER)

    sold = get_success_data(
        api_client.purchase_listing(ctx["listing"]["id"], customer_headers(reserver))
    )
    assert sold["status"] == "SOLD", (
        f"the reserving customer's purchase must complete SOLD, got {sold['status']}"
    )


def test_appraiser_cannot_adjust_own_listing_price(api):
    """PRD §3.6: "Price management belongs to a `ShopManager`, who may set a
    `LISTED` listing's `list_price_cents` to a supplied `new_price_cents` —
    but never the manager who appraised it: if the acting staff member's id
    equals the listing's `appraised_by_staff_id`, the adjustment is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." and "its `list_price_cents`
    initialized to the offered value multiplied by 1.4, rounded half-up."

    Design: Corner/rbac/appraiser_cannot_adjust_own_listing_price
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Moe Mere")
    m1 = create_manager("Mary One")
    m2 = create_manager("Mark Two")
    appraisal = submit_appraisal(customer, [{"club_type": "WEDGE", "condition_grade": "A"}])
    appraisal = issue_offer(appraisal, m1, "GRADE_MATRIX")
    # round(8999*0.60) = 5399.
    assert appraisal["offered_value_cents"] == 5_399
    accept_appraisal(appraisal, customer)
    listing = get_listing_for_appraisal(appraisal["id"], staff_headers(m2))
    # round_half_up(5399 * 1.4) = 7559.
    assert listing["list_price_cents"] == 7_559, (
        f"initial list price must be round(5399*1.4)=7559, got {listing['list_price_cents']}"
    )
    assert listing["appraised_by_staff_id"] == m1["id"]

    resp = api_client.adjust_listing_price(
        listing["id"], {"new_price_cents": 6_000}, staff_headers(m1)
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    adjusted = get_success_data(
        api_client.adjust_listing_price(
            listing["id"], {"new_price_cents": 6_000}, staff_headers(m2)
        )
    )
    assert adjusted["list_price_cents"] == 6_000, (
        f"a different manager may adjust the price, got {adjusted['list_price_cents']}"
    )
