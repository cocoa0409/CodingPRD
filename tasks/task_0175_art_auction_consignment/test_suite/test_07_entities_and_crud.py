"""Entity CRUD breadth: creation echoes, not-found, required fields, defaults,
type constraints, server-set system fields, the immutable PremiumSchedule, and
body-FK resolution.
"""
from test_helpers import validate_success, validate_error, get_success_data
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_seller, assert_bidder, assert_lot
from test_helpers.fixtures import (
    create_premium_schedule, create_seller, create_active_consignment,
    create_cataloging_sale, ADMIN,
)
from test_helpers.factories import (
    create_seller_payload, create_bidder_payload, create_lot_payload, FLAT_TIERS,
)


# ===========================================================================
# Queue B — entities section
# ===========================================================================
def test_create_seller_returns_201_with_fields(api):
    """PRD §3.1: "A `SaleAdministrator` registers a consignor as a `Seller`,
    supplying the `legal_name`, the contact `email`, the residence
    `country_code` ... and the disbursement account reference `payout_iban`."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created"

    Design: Corner/entities/create_seller_returns_201_with_fields
    """
    payload = create_seller_payload(legal_name="Solo Seller", country_code="US")
    data = validate_success(api.create_seller(payload, ADMIN), expected_status=201)
    assert data["legal_name"] == "Solo Seller"
    assert data["country_code"] == "US"
    assert data["version"] == 1
    assert_seller(data)


def test_get_seller_not_found_returns_404(api):
    """PRD §2.7: "When a path contains more than one resource identifier, the
    system validates them strictly left to right and rejects the request with
    `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing
    resource."

    Design: Corner/entities/get_seller_not_found_returns_404
    """
    resp = api.get_seller("00000000-0000-4000-8000-0000000000aa", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_bidder_missing_required_field_returns_400(api):
    """PRD §3.1: "The same administrator registers a `Bidder` with `legal_name`,
    `email` (unique among bidders), and `country_code`"
    PRD §2.9: "well-formedness of the request body (`ERR_INVALID_REQUEST`)"

    Omitting the required legal_name yields ERR_INVALID_REQUEST.

    Design: Corner/entities/create_bidder_missing_required_field_returns_400
    """
    resp = api.create_bidder({"email": "noname@example.com", "country_code": "US"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_bidder_default_credit_limit_zero(api):
    """PRD §3.1: "may optionally set the `credit_limit_cents`, which defaults to
    0."
    PRD §3.1: "Each new bidder begins with `status` of `ACTIVE` and an
    `outstanding_balance_cents` of 0"

    Design: Corner/entities/create_bidder_default_credit_limit_zero
    """
    payload = {"legal_name": "Default Bidder", "email": "def-bidder@example.com", "country_code": "US"}
    data = validate_success(api.create_bidder(payload, ADMIN), expected_status=201)
    assert data["credit_limit_cents"] == 0
    assert data["status"] == "ACTIVE"
    assert data["outstanding_balance_cents"] == 0


def test_create_bidder_negative_credit_limit_returns_400(api):
    """PRD §2.9: "well-formedness of the request body (`ERR_INVALID_REQUEST`)"
    PRD §3.1: "A bidder's `credit_limit_cents` is the maximum unsettled exposure
    permitted across all of that bidder's open invoices"

    A negative credit_limit_cents is malformed and rejected with
    ERR_INVALID_REQUEST (amounts are non-negative integer cents per §2.5).

    Design: Corner/entities/create_bidder_invalid_country_type_returns_400
    """
    payload = create_bidder_payload(legal_name="Neg Bidder", credit_limit_cents=-100)
    resp = api.create_bidder(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_lot_system_fields_server_set(api):
    """PRD §3.3: "A new lot is created with `sale_status` of `CATALOGED` and
    `settlement_status` of `NONE`, its `hammer_price_cents` 0, and its
    `winning_paddle_registration_id` null until it sells."

    Design: Corner/entities/system_fields_ignored_on_lot_create
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS)
    seller = create_seller()
    cons = create_active_consignment(seller["id"])
    sale = create_cataloging_sale(schedule["id"])
    data = validate_success(
        api.create_lot(sale["id"], create_lot_payload(cons["id"]), ADMIN), expected_status=201)
    assert data["sale_status"] == "CATALOGED"
    assert data["settlement_status"] == "NONE"
    assert data["hammer_price_cents"] == 0
    assert_lot(data)


def test_premium_schedule_immutable_no_version(api):
    """PRD §2.4: "A `PremiumSchedule` is immutable after creation and carries
    only `id` and `created_at`; it has neither `updated_at` nor `version`."

    Design: Corner/entities/premium_schedule_immutable_no_version_field
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS, name="Immutable")
    data = validate_success(api.get_premium_schedule(schedule["id"], ADMIN))
    assert data["name"] == "Immutable"
    assert "tiers" in data
    assert "version" not in data, "PremiumSchedule must not carry a version field"
    assert "updated_at" not in data, "PremiumSchedule must not carry an updated_at field"


def test_lot_create_unknown_consignment_fk_not_found(api):
    """PRD §3.3: "A lot may attach only under a consignment that permits it, and
    a referenced consignment that does not resolve yields `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/lot_parent_wrong_consignment_returns_fk_not_found
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS)
    sale = create_cataloging_sale(schedule["id"])
    payload = create_lot_payload("00000000-0000-4000-8000-0000000000bb")
    resp = api.create_lot(sale["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)
