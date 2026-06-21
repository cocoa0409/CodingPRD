"""CRUD, creation defaults, retrieval, listing, and input validation for the
core entities.

Covers the corner `entities` section instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_vendor_headers, NON_EXISTENT_UUID, TEST_USERS,
    create_market, create_vendor,
    create_market_payload, create_booth_payload, create_permit_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_market_returns_201_with_zeroed_ledgers(api):
    """PRD 3.1: "A freshly created market starts with booth_count at 0 and every
    ledger field (total_commission_accrued_cents, total_fees_collected_cents,
    voucher_liability_cents) at 0." PRD 2.4: version "begins at 1 on creation".

    Design: Corner/entities/create_market_returns_201_with_zeroed_ledgers
    """
    res = api.create_market(create_market_payload(), ADMIN)
    market = validate_success(res, 201)
    assert market["booth_count"] == 0
    assert market["total_fees_collected_cents"] == 0
    assert market["total_commission_accrued_cents"] == 0
    assert market["voucher_liability_cents"] == 0
    assert market["version"] == 1


def test_get_market_returns_stored_data(api):
    """PRD 3.1: "The creating payload supplies the market's name, its season window
    as a season_start_date and season_end_date pair ... and the market's fiscal
    policy: a season_fee_cents, a daily_fee_cents, a commission_bps commission rate,
    and a voucher_face_value_cents cash value for one redeemed token." PRD 2.2: "The
    data field contains the resource object or an array of resource objects." So the
    stored market echoes the created name and commission_bps.

    Design: Corner/entities/get_market_returns_stored_data
    """
    market = create_market(name="Green Sq", commission_bps=700)
    got = validate_success(api.get_market(market["id"], ADMIN), 200)
    assert got["name"] == "Green Sq"
    assert got["commission_bps"] == 700


def test_list_booths_paginated_with_total_count(api):
    """PRD 2.3: "Every list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope" and "when omitted it defaults
    to 10".

    Design: Corner/entities/list_booths_paginated_with_total_count
    """
    market = create_market()
    validate_success(api.create_booth(
        create_booth_payload(market["id"], label="A-1", grid_row=0, grid_col=1,
                            size_class="SINGLE", allowed_categories=[]), ADMIN), 201)
    validate_success(api.create_booth(
        create_booth_payload(market["id"], label="A-2", grid_row=0, grid_col=2,
                            size_class="DOUBLE", allowed_categories=[]), ADMIN), 201)

    data, meta = validate_paginated(api.list_booths(ADMIN, params={"market_id": market["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10


def test_get_market_not_found_returns_404(api):
    """PRD 2.6: "The server validates every path-referenced resource for existence
    within the market scope ... rejecting the first one that does not resolve with
    ERR_NOT_FOUND."

    Design: Corner/entities/get_market_not_found_returns_404
    """
    res = api.get_market(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_market_missing_required_field_returns_invalid_request(api):
    """PRD 2.11: "structural validation of the request body — required fields
    present and well-typed ... (ERR_INVALID_REQUEST)." Omitting commission_bps is
    a missing required field.

    Design: Corner/entities/create_market_missing_required_field_returns_invalid_request
    """
    payload = create_market_payload()
    del payload["commission_bps"]
    res = api.create_market(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_assignment_type_invalid_enum_returns_invalid_request(api):
    """PRD 2.11: "required fields present and well-typed, enum values legal ...
    (ERR_INVALID_REQUEST)." assignment_type='WEEKLY' is an illegal enum.

    Design: Corner/entities/assignment_type_invalid_enum_returns_invalid_request
    """
    market = create_market()
    booth = get_success_data(api.create_booth(
        create_booth_payload(market["id"], label="A-1", grid_row=0, grid_col=1,
                            size_class="SINGLE", allowed_categories=[]), ADMIN))
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    vh = make_vendor_headers(vendor["id"])
    res = api.create_booth_assignment(
        {"market_id": market["id"], "booth_id": booth["id"], "vendor_id": vendor["id"],
         "assignment_type": "WEEKLY", "expected_booth_version": booth["version"]}, vh)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_season_window_dates_reversed_returns_validation_bounds(api):
    """PRD 3.1: "The season end date may equal the start date but may not precede
    it ... A violation of any of these bounds — an end date earlier than the start
    ... — is rejected with ERR_VALIDATION_BOUNDS."

    Design: Corner/entities/season_window_dates_reversed_returns_validation_bounds
    """
    payload = create_market_payload(name="Bad", season_start_date="2026-09-30",
                                    season_end_date="2026-06-01")
    res = api.create_market(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION_BOUNDS")


def test_commission_bps_out_of_range_returns_validation_bounds(api):
    """PRD 3.1: "commission_bps must lie between 0 and 10000 inclusive. A violation
    of any of these bounds — ... or a basis-point rate outside the 0-to-10000 range
    — is rejected with ERR_VALIDATION_BOUNDS." 10001 > 10000.

    Design: Corner/entities/commission_bps_out_of_range_returns_validation_bounds
    """
    payload = create_market_payload(name="Bad", commission_bps=10001)
    res = api.create_market(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION_BOUNDS")


def test_permit_expiry_not_after_issue_returns_validation_bounds(api):
    """PRD 3.2: "the expiry must be strictly after the issue date — an expiry on or
    before the issue date is rejected with ERR_VALIDATION_BOUNDS."

    Design: Corner/entities/permit_expiry_not_after_issue_returns_validation_bounds
    """
    market = create_market()
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    vh = make_vendor_headers(vendor["id"])
    res = api.create_permit(
        create_permit_payload(vendor["id"], permit_type="HEALTH", permit_number="H-1",
                            issue_date="2026-05-10", expiry_date="2026-05-10"), vh)
    validate_error(res, "ERR_VALIDATION_BOUNDS")


def test_requires_health_permit_computed_from_category(api):
    """PRD 3.2: "On creation the system computes requires_health_permit, which is
    true exactly when the chosen category is one of DAIRY, MEAT, or PREPARED_FOOD".
    A DAIRY application yields true.

    Design: Corner/entities/requires_health_permit_computed_from_category
    """
    market = create_market()
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    vh = make_vendor_headers(vendor["id"])
    app = validate_success(api.create_application(
        {"vendor_id": vendor["id"], "product_category": "DAIRY"}, vh), 201)
    assert app["requires_health_permit"] is True


def test_vendor_starts_prospect_with_version_1(api):
    """PRD 3.2: "A new vendor starts in PROSPECT status, with no_show_strikes at 0
    and permit_ok false." PRD 2.4: version "begins at 1 on creation".

    Design: Corner/entities/vendor_id_and_status_system_assigned
    """
    market = create_market()
    vendor = validate_success(api.create_vendor(
        {"market_id": market["id"], "legal_name": "V1", "contact_email": "v1@x.com"}, ADMIN), 201)
    assert vendor["status"] == "PROSPECT"
    assert vendor["version"] == 1


def test_duplicate_booth_label_returns_duplicate(api):
    """PRD 3.1: "Attempting a duplicate label within the same market is rejected
    with ERR_DUPLICATE."

    Design: Corner/entities/duplicate_booth_label_returns_duplicate
    """
    market = create_market()
    validate_success(api.create_booth(
        create_booth_payload(market["id"], label="A-1", grid_row=0, grid_col=1,
                            size_class="SINGLE", allowed_categories=[]), ADMIN), 201)
    res = api.create_booth(
        create_booth_payload(market["id"], label="A-1", grid_row=0, grid_col=2,
                            size_class="DOUBLE", allowed_categories=[]), ADMIN)
    validate_error(res, "ERR_DUPLICATE")


def test_vendor_with_nonexistent_market_returns_not_found(api):
    """PRD 2.6: "Body foreign keys that point at non-existent rows are likewise
    treated as not-found." A vendor's market_id pointing nowhere yields ERR_NOT_FOUND.

    Design: Corner/entities/child_vendor_requires_existing_market_parent
    """
    res = api.create_vendor(
        {"market_id": NON_EXISTENT_UUID, "legal_name": "V1", "contact_email": "v1@x.com"}, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")
