"""Cross-cutting validation gates and role-based access control: existence,
well-formedness, uniqueness, active-rate-card presence, authentication, ownership.
"""
from test_helpers import (
    validate_success, validate_error,
    create_active_rate_card, create_customer, create_vehicle,
    create_loan_payload, create_rate_card_payload, record_payment_payload,
    setup_loan,
    TEST_USERS, make_borrower_headers, build_user_headers,
    NON_EXISTENT_UUID,
)

FM = TEST_USERS["finance_manager_headers"]


def test_get_customer_not_found_returns_404(api):
    """PRD §2.5: "referenced customers, vehicles, rate cards, loans, and leases are checked for
    existence (in that left-to-right order) before any business rule is evaluated, and a missing
    reference yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    res = api.get_customer(NON_EXISTENT_UUID, FM)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_customer_invalid_fico_returns_422(api):
    """PRD §3.1: "The `fico_score` is the borrower's raw credit score and must fall between 300
    and 850 inclusive."

    Design: Corner/entities/create_customer_invalid_fico_returns_422
    """
    create_active_rate_card()
    res = api.create_customer(
        {"full_name": "Bad Fico", "email": "bad@x.com", "fico_score": 900}, FM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_customer_missing_required_field_returns_422(api):
    """PRD §2.8: "Then request well-formedness is checked — required body fields present and
    correctly typed, enum members valid, `fico_score` within the range 300 to 850 inclusive, and
    integer-cent fields non-negative — yielding `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_customer_missing_required_field_returns_422
    """
    create_active_rate_card()
    res = api.create_customer({"email": "noname@x.com", "fico_score": 700}, FM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_email_returns_409(api):
    """PRD §3.1: "The email must be unique across all customers; a registration whose email is
    already in use is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/duplicate_email_returns_409
    """
    create_active_rate_card()
    validate_success(api.create_customer(
        {"full_name": "First", "email": "dup@x.com", "fico_score": 700}, FM), 201)
    res = api.create_customer({"full_name": "Second", "email": "dup@x.com", "fico_score": 720}, FM)
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


def test_vehicle_defaults_status_available(api):
    """PRD §3.1: "A vehicle's `status` is system-managed and begins at `AVAILABLE`; it moves to
    `FINANCED` once a loan or lease is originated against it."

    Design: Corner/entities/vehicle_defaults_status_available
    """
    vehicle = validate_success(api.create_vehicle(
        {"vin": "VIN-DEF", "make_model": "Acme", "msrp_cents": 3_000_000,
         "sale_price_cents": 2_900_000, "residual_value_cents": 1_700_000}, FM), 201)
    assert vehicle["status"] == "AVAILABLE"


def test_origination_without_active_rate_card_returns_409(api):
    """PRD §3.2: "Origination requires an active rate card to exist; if none is active the
    request is rejected with `ERR_NO_ACTIVE_RATE_CARD`."

    Design: Corner/validations/origination_without_active_rate_card_returns_409
    """
    # Create a card but do NOT activate it.
    validate_success(api.create_rate_card(create_rate_card_payload(name="2026-Q2"), FM), 201)
    customer = validate_success(api.create_customer(
        {"full_name": "No Card", "email": "nocard@x.com", "fico_score": 760}, FM), 201)
    vehicle = validate_success(api.create_vehicle(
        {"vin": "VIN-NC", "make_model": "Acme Sedan", "msrp_cents": 3_200_000,
         "sale_price_cents": 3_000_000, "residual_value_cents": 1_850_000}, FM), 201)
    res = api.create_loan(create_loan_payload(customer["id"], vehicle["id"]), FM)
    validate_error(res, "ERR_NO_ACTIVE_RATE_CARD")


def test_borrower_cannot_originate_loan(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to perform the
    requested operation is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/borrower_cannot_originate_loan
    """
    create_active_rate_card()
    customer = create_customer(fico_score=760)
    vehicle = create_vehicle()
    borrower = make_borrower_headers(customer["id"])
    res = api.create_loan(create_loan_payload(customer["id"], vehicle["id"]), borrower)
    validate_error(res, "ERR_FORBIDDEN")


def test_borrower_cannot_pay_other_borrowers_loan(api):
    """PRD §2.1: "A `Borrower` may only act on contracts they own, and an attempt to act on
    someone else's contract is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/borrower_cannot_pay_other_borrowers_loan
    """
    create_active_rate_card()
    customer_a = create_customer(fico_score=760, email="ownera@x.com")
    customer_b = create_customer(fico_score=760, email="otherb@x.com")
    vehicle = create_vehicle()
    loan = validate_success(api.create_loan(
        create_loan_payload(customer_a["id"], vehicle["id"]), FM), 201)
    # Customer B (not the owner) attempts to pay.
    res = api.record_payment(
        loan["id"], record_payment_payload(loan["monthly_payment_cents"], "SCHEDULED"),
        make_borrower_headers(customer_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_or_unknown_role_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that is not one
    of the three recognized roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_401
    """
    res = api.list_customers(build_user_headers("someone", "NoSuchRole"))
    validate_error(res, "ERR_UNAUTHENTICATED")
