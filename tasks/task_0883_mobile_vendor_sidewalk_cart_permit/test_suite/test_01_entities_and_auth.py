"""Entity creation defaults, input validation, and authentication/ownership
corner cases (Corner queue: entities, validations)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_vendor, create_vendor_payload, create_cart_payload, insurance_payload,
    payment_payload, TEST_USERS, make_vendor_headers, NON_EXISTENT_UUID,
    FEE_NEW_STANDARD_MEDIUM,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]
HI = TEST_USERS["health_inspector_headers"]


def test_create_vendor_returns_defaults(api):
    """PRD §3.1: "A new vendor starts with status of ACTIVE (the vendor-level
    standing enum ranges over ACTIVE, SUSPENDED, and REVOKED), an insurance_status
    of NONE, and both ledger accumulators at 0."
    PRD §2.4: "The version begins at 1 when the resource is created and increments
    by 1 on every mutation of that resource."

    Design: Corner/entities/create_vendor_returns_defaults
    """
    fx.set_clock()
    res = api.create_vendor(create_vendor_payload(legal_name="Acme", seniority_years=3), PO)
    vendor = validate_success(res, 201)
    assert_vendor(vendor)
    assert vendor["status"] == "ACTIVE"
    assert vendor["insurance_status"] == "NONE"
    assert vendor["balance_owed_cents"] == 0
    assert vendor["total_charged_cents"] == 0
    assert vendor["total_credited_cents"] == 0
    assert vendor["version"] == 1


def test_get_unknown_vendor_returns_not_found(api):
    """PRD §2.9: "every referenced resource in the path and body must exist; the
    first missing reference yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/vendor_not_found_returns_404
    """
    fx.set_clock()
    res = api.get_vendor(NON_EXISTENT_UUID, PO)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_cart_missing_size_returns_validation(api):
    """PRD §3.2: "A Vendor registers a cart by supplying vendor_id, commissary_id,
    a cart_type of FOOD, PRODUCE, or MERCHANDISE, and its footprint size_sqft."
    PRD §2.1: "then existence of every referenced resource, then body
    well-formedness, then enum membership, then state legality"

    Design: Corner/entities/create_cart_missing_required_field_returns_validation
    """
    fx.set_clock()
    vendor = fx.create_vendor()
    commissary = fx.create_commissary()
    payload = create_cart_payload(vendor["id"], commissary["id"])
    del payload["size_sqft"]
    res = api.create_cart(payload, make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_create_cart_invalid_enum_returns_invalid_enum(api):
    """PRD §4: "an enum field carrying a non-member value returns ERR_INVALID_ENUM."

    Design: Corner/entities/create_cart_invalid_enum_returns_invalid_enum
    """
    fx.set_clock()
    vendor = fx.create_vendor()
    commissary = fx.create_commissary()
    payload = create_cart_payload(vendor["id"], commissary["id"], cart_type="HOTDOG")
    res = api.create_cart(payload, make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_INVALID_ENUM", expected_status=422)


def test_permit_fee_and_points_are_server_computed(api):
    """PRD §3.3: "On issuance the fee variant is set to NEW and the permit fee is
    assessed as described in Section 3.4"
    PRD §3.7: "A permit's violation_points is the sum of the point values of that
    permit's UPHELD violations whose updated_at falls within the trailing 365-day
    window ending at the clock; violations that are ISSUED, CONTESTED, or DISMISSED
    contribute nothing."

    Design: Corner/entities/permit_computed_fee_and_points_ignore_client_input
    """
    fx.set_clock()
    vendor = fx.create_insured_vendor()
    commissary = fx.create_commissary()
    cart = fx.create_cart(vendor["id"], commissary["id"], size_sqft=30)
    zone = fx.create_zone(zone_type="STANDARD")
    draft = fx.create_draft_permit(vendor["id"], cart["id"], zone["id"])
    assert draft["violation_points"] == 0
    get_success_data(api.submit_permit(draft["id"], make_vendor_headers(vendor["id"])))
    issued = validate_success(api.issue_permit(draft["id"], PO), 200)
    assert issued["fee_amount_cents"] == FEE_NEW_STANDARD_MEDIUM
    assert issued["fee_variant"] == "NEW"


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected
    with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    fx.set_clock()
    res = api.create_vendor(create_vendor_payload(), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_vendor_creates_cart_for_other_vendor_ownership(api):
    """PRD §2.1: "Ownership checks on any resource that references a vendor compare
    the resource's owning vendor_id to X-User-ID: for a Cart or Permit, the
    resource's own vendor_id ... A Vendor acting on a resource it does not own is
    rejected with ERR_OWNERSHIP (HTTP 403)."

    Design: Corner/validations/vendor_creates_cart_for_other_vendor_ownership
    """
    fx.set_clock()
    va = fx.create_vendor(legal_name="A", contact_email="a@x.com")
    vb = fx.create_vendor(legal_name="B", contact_email="b@x.com")
    commissary = fx.create_commissary()
    # Vendor A (X-User-ID=va) posting a cart owned by vb.
    res = api.create_cart(create_cart_payload(vb["id"], commissary["id"]),
                          make_vendor_headers(va["id"]))
    validate_error(res, "ERR_OWNERSHIP", expected_status=403)


def test_insurance_below_minimum_coverage_rejected(api):
    """PRD §3.1: "If the submitted insurance_coverage_cents is below the minimum
    liability requirement of $1,000,000 — that is, below 100,000,000 cents — the
    submission is rejected with ERR_INSUFFICIENT_COVERAGE."

    Design: Corner/validations/insurance_insufficient_coverage_rejected
    """
    fx.set_clock()
    vendor = fx.create_vendor()
    res = api.submit_insurance(
        vendor["id"], insurance_payload(insurance_coverage_cents=50_000_000),
        make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_INSUFFICIENT_COVERAGE", expected_status=422)


def test_payment_exceeding_balance_rejected(api):
    """PRD §3.1: "The payment must be strictly greater than zero and must not exceed
    the current balance_owed_cents; a non-positive amount or an amount above the
    outstanding balance is rejected with ERR_PAYMENT_INVALID."

    Design: Corner/validations/payment_exceeds_balance_rejected
    """
    ctx = fx.setup_issued_permit()  # balance_owed_cents == 34257 after issue
    vendor = ctx["vendor"]
    res = api.create_payment(vendor["id"], payment_payload(999_999_999),
                             make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_PAYMENT_INVALID", expected_status=422)
