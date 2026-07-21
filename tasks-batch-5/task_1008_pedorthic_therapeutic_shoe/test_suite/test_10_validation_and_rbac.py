"""Body validation, cross-entity referential guards, and role-based access control."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

SM = TEST_USERS["store_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]
FITTER = TEST_USERS["fitter_headers"]
GHOST = TEST_USERS["ghost_headers"]


def test_create_product_missing_required_field_returns_422(api):
    """PRD §2.9: "(3) request-body well-formedness (`ERR_VALIDATION`) — required fields
    present, enums in range, integers non-negative where constrained."
    PRD §3.1: "A product carries a `base_price_cents` (the retail unit price copied onto
    each sale line at add time)."

    Design: Corner/entities/create_product_missing_required_field_returns_422
    """
    resp = api.create_product({"name": "No Price", "brand": "X", "category": "REGULAR"}, SM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_product_invalid_category_enum_returns_422(api):
    """PRD §3.1: "a `category` — one of `THERAPEUTIC`, `DIABETIC`, `ORTHOTIC`, `REGULAR`,
    or `INSERT`."
    PRD §2.9: "(3) request-body well-formedness (`ERR_VALIDATION`) — required fields
    present, enums in range."

    Design: Corner/entities/create_product_invalid_category_enum_returns_422
    """
    resp = api.create_product(
        {"name": "Bad Cat", "brand": "X", "category": "SANDAL", "base_price_cents": 5000}, SM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_medicare_line_without_diabetic_fitting_returns_missing_measurement(api):
    """PRD §3.4: "a `requires_medicare` line requires the sale to reference — for the same
    customer — an appointment of type `DIABETIC_FITTING` in status `COMPLETED`; absent
    that, the add is rejected with `ERR_MISSING_MEASUREMENT`."

    Design: Corner/validations/medicare_line_missing_diabetic_fitting_returns_referential
    """
    fx.set_clock()
    prod = fx.create_product(name="Dia Line", brand="Apex", category="DIABETIC",
                             base_price_cents=30000, medicare_allowable_cents=30000, hcpcs_code="A5500")
    inv = fx.create_inventory(prod["id"], lot_number="D1", quantity_on_hand=3)
    cust = fx.create_customer(full_name="Ref Cust", date_of_birth="1950-06-06",
                              medicare_beneficiary_id="1AB2CD3EF44")  # adult -> pediatric check skipped
    fitter = fx.create_fitter(full_name="Ref Fit")
    fh = fx.make_fitter_headers(fitter["id"])
    sale = fx.open_sale(cust["id"], fitter["id"], fh)
    resp = api.add_sale_line(
        sale["id"], {"inventory_item_id": inv["id"], "quantity": 1, "requires_medicare": True}, fh)
    validate_error(resp, ApiErrorId.ERR_MISSING_MEASUREMENT.value)


def test_fitter_cannot_create_product_returns_unauthorized(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `StoreManager` is the operational administrator: catalog and inventory
    creation, fitter and gait-lab setup, return adjudication, special-order placement and
    receipt, recall management, and manual loyalty adjustments are theirs."

    Design: Corner/rbac/fitter_cannot_create_product_returns_unauthorized
    """
    resp = api.create_product(
        {"name": "Nope", "brand": "X", "category": "REGULAR", "base_price_cents": 1000}, FITTER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_fitter_cannot_submit_claim_returns_unauthorized(api):
    """PRD §2.1: "A `BillingSpecialist` owns Medicare certifications and the entire claim
    lifecycle."
    PRD §2.9: "they are evaluated in a fixed global order... (2) authorization
    (`ERR_UNAUTHORIZED`); ... (5) existence of all path and body foreign keys."

    Design: Corner/rbac/fitter_cannot_submit_claim_returns_unauthorized
    """
    resp = api.submit_claim("00000000-0000-4000-8000-0000000000bb", FITTER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.get_customer("00000000-0000-4000-8000-0000000000cc", GHOST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
