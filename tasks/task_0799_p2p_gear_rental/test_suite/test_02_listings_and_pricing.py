"""Listing creation/validation, activation, editing, and the dynamic pricing engine."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_listing_payload, ApiErrorId,
    make_owner_headers,
    create_owner, create_active_listing, create_draft_listing,
    create_verified_renter, create_requested_booking,
)


# --- Listing field validation (Corner/entities) ------------------------------

def test_listing_missing_required_base_rate_rejected(api):
    """PRD §3.2: "An Owner creates a gear Listing by supplying the owner_id, a title,
    a free-text category, a declared_value_cents ..., a base_daily_rate_cents (greater
    than zero), and a deposit_cents ..."
    PRD §2.7: "Request well-formedness — body field types, enums, and ranges are valid,
    else ERR_INVALID_REQUEST (400)."

    Design: Corner/entities/listing_missing_required_base_rate_rejected
    """
    owner = create_owner(api, email="owner_req_rate@x.com")
    payload = create_listing_payload(owner["id"])
    del payload["base_daily_rate_cents"]
    resp = api.create_listing(payload, make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_listing_quantity_defaults_to_one(api):
    """PRD §3.2: "Two further fields are optional: quantity, the number of identical
    units available, which defaults to 1 and must be at least 1 ..."

    Design: Corner/entities/listing_quantity_defaults_to_one
    """
    owner = create_owner(api, email="owner_qty_default@x.com")
    payload = create_listing_payload(owner["id"])
    resp = api.create_listing(payload, make_owner_headers(owner["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["quantity"] == 1, f"quantity default must be 1, got {data['quantity']}"


def test_listing_demand_multiplier_out_of_range_rejected(api):
    """PRD §3.2: "demand_multiplier_bps, the dynamic demand multiplier in basis points,
    which defaults to 10000 (a factor of 1.0) and must be at least 5000 and at most 30000."

    Design: Corner/entities/listing_demand_multiplier_out_of_range_rejected
    """
    owner = create_owner(api, email="owner_demand_range@x.com")
    payload = create_listing_payload(owner["id"], demand_multiplier_bps=40000)
    resp = api.create_listing(payload, make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# --- Listing lifecycle (Corner/state_machines, cross_cutting) ----------------

def test_activate_already_active_listing_invalid(api):
    """PRD §3.2: "A listing becomes rentable when its owner activates it, moving DRAFT
    to ACTIVE ..."
    PRD §2.7: "State legality — the target resource is in a state from which the
    requested transition is defined, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/activate_already_active_listing_invalid
    """
    owner = create_owner(api, email="owner_double_activate@x.com")
    listing = create_active_listing(api, owner["id"])
    resp = api.activate_listing(listing["id"], make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_listing_patch_increments_version(api):
    """PRD §2.6: "an owner updating a listing's mutable fields must submit
    expected_listing_version, and a mismatch with the listing's current version is
    likewise rejected with ERR_STALE_LISTING_VERSION."
    PRD §3.2: "Such an edit is OCC-guarded on expected_listing_version as described in
    Section 2.6 and increments the listing's version ..."

    Design: Corner/cross_cutting_complexity_layers/listing_version_increments_on_patch
    """
    owner = create_owner(api, email="owner_patch_ver@x.com")
    listing = create_draft_listing(api, owner["id"])
    assert listing["version"] == 1
    resp = api.update_listing(
        listing["id"],
        {"expected_listing_version": listing["version"], "base_daily_rate_cents": 12000},
        make_owner_headers(owner["id"]),
    )
    data = validate_success(resp, expected_status=200)
    assert data["version"] == 2, f"version must advance 1->2, got {data['version']}"
    assert data["base_daily_rate_cents"] == 12000


# --- Dynamic pricing engine (Difficulty/combinatorial_formula) ---------------

def test_dynamic_pricing_subtotal_weekend_and_weekly_discount(api):
    """PRD §3.2: "if billable_days is at least 28, the discount is 2500 basis points;
    otherwise if billable_days is at least 7, the discount is 1000 basis points;
    otherwise there is no duration discount."
    PRD §3.2: "Round that day's figure to whole cents using round half up, and add the
    rounded day charge to rental_subtotal_cents. Rounding happens per day before summing;
    the accumulated rental_subtotal_cents is the sum of the individually rounded day
    charges, never a single rounding of a raw total."

    Design: Difficulty/combinatorial_formula/dynamic_daily_pricing_tier_weekend_demand_mode_a
    """
    owner = create_owner(api, email="owner_dp_a1@x.com")
    renter = create_verified_renter(api, email="renter_dp_a1@x.com")
    listing = create_active_listing(api, owner["id"], base_daily_rate_cents=10000,
                                    demand_multiplier_bps=10000, deposit_cents=50000,
                                    declared_value_cents=90000, quantity=1)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    assert booking["billable_days"] == 7
    assert booking["rental_subtotal_cents"] == 66600, booking["rental_subtotal_cents"]


def test_dynamic_pricing_service_fee_and_provisional_total(api):
    """PRD §3.3: "renter_service_fee_cents is the rental_subtotal_cents multiplied by
    1200 basis points divided by 10000 (twelve percent), rounded to whole cents using
    round half up on the summed subtotal, and provisional_total_cents is
    rental_subtotal_cents plus renter_service_fee_cents."

    Design: Difficulty/combinatorial_formula/dynamic_daily_pricing_tier_weekend_demand_mode_a
    """
    owner = create_owner(api, email="owner_dp_a2@x.com")
    renter = create_verified_renter(api, email="renter_dp_a2@x.com")
    listing = create_active_listing(api, owner["id"], base_daily_rate_cents=10000,
                                    demand_multiplier_bps=10000, deposit_cents=50000,
                                    declared_value_cents=90000, quantity=1)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    assert booking["rental_subtotal_cents"] == 66600
    assert booking["renter_service_fee_cents"] == 7992, booking["renter_service_fee_cents"]
    assert booking["provisional_total_cents"] == 74592, booking["provisional_total_cents"]


# --- Duration-discount boundary (Difficulty/boundary_precision_check) ---------

def test_no_weekly_discount_below_seven_nights(api):
    """PRD §3.2: "otherwise if billable_days is at least 7, the discount is 1000 basis
    points; otherwise there is no duration discount."

    Design: Difficulty/boundary_precision_check/weekly_discount_tier_at_7_day_boundary
    """
    owner = create_owner(api, email="owner_wd_lo@x.com")
    renter = create_verified_renter(api, email="renter_wd_lo@x.com")
    listing = create_active_listing(api, owner["id"], base_daily_rate_cents=10000, quantity=2)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-01T00:00:00Z", "2026-06-07T00:00:00Z")
    assert booking["billable_days"] == 6
    assert booking["rental_subtotal_cents"] == 62000, booking["rental_subtotal_cents"]


def test_weekly_discount_engages_at_seven_nights(api):
    """PRD §3.2: "otherwise if billable_days is at least 7, the discount is 1000 basis
    points; otherwise there is no duration discount."

    Design: Difficulty/boundary_precision_check/weekly_discount_tier_at_7_day_boundary
    """
    owner = create_owner(api, email="owner_wd_hi@x.com")
    renter = create_verified_renter(api, email="renter_wd_hi@x.com")
    listing = create_active_listing(api, owner["id"], base_daily_rate_cents=10000, quantity=2)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z")
    assert booking["billable_days"] == 7
    assert booking["rental_subtotal_cents"] == 66600, booking["rental_subtotal_cents"]


# --- Monthly-discount tier & quote (Corner) ----------------------------------

def test_monthly_discount_tier_at_28_plus_days(api):
    """PRD §3.2: "if billable_days is at least 28, the discount is 2500 basis points;
    otherwise if billable_days is at least 7, the discount is 1000 basis points;
    otherwise there is no duration discount."

    Design: Corner/calculations/monthly_discount_tier_at_28_plus_days
    """
    owner = create_owner(api, email="owner_mo@x.com")
    renter = create_verified_renter(api, email="renter_mo@x.com")
    listing = create_active_listing(api, owner["id"], base_daily_rate_cents=10000, quantity=1)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z")
    assert booking["billable_days"] == 30
    assert booking["rental_subtotal_cents"] == 237000, booking["rental_subtotal_cents"]


def test_quote_computed_read_matches_provisional(api):
    """PRD §3.2: "A renter (or owner) may fetch a live quote for a booking's window,
    which returns billable_days, rental_subtotal_cents, renter_service_fee_cents,
    provisional_total_cents, and the listing's deposit_cents without mutating anything."

    Design: Corner/endpoints/quote_computed_read_matches_provisional
    """
    owner = create_owner(api, email="owner_quote@x.com")
    renter = create_verified_renter(api, email="renter_quote@x.com")
    listing = create_active_listing(api, owner["id"], base_daily_rate_cents=10000,
                                    deposit_cents=50000, quantity=1)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    from test_helpers import make_renter_headers
    resp = api.get_quote(booking["id"], make_renter_headers(renter["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["provisional_total_cents"] == 74592, data["provisional_total_cents"]
    assert data["deposit_cents"] == 50000, data["deposit_cents"]
