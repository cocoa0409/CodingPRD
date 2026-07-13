"""Resource CRUD, defaults, required/typed fields, promo validation,
authentication/authorization/ownership, and read-after-write consistency."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, TEST_USERS, NON_EXISTENT_UUID,
    create_customer, create_order, make_customer_headers,
    setup_loaded_batch,
)


# ===========================================================================
# entities / create_customer_success (corner)
# ===========================================================================
def test_create_customer_starts_with_zero_counters(api):
    """PRD §3.7: "A customer's `risk_score` is an integer capped at 100, computed
    as 20 points for each of that customer's claims in `APPROVED` status plus 5
    points for each claim in `SUBMITTED` or `UNDER_REVIEW` status, with the sum
    capped at 100."
    PRD §3.7: "A customer also carries a `wallet_credit_cents` balance of
    refundable store credit."

    A newly registered customer has no claims and no payouts, so both risk_score
    and wallet_credit_cents are 0.

    Design: Corner/entities/create_customer_success
    """
    resp = api.create_customer(
        {"email": "c_new@x.com", "full_name": "New Cust", "state_code": "NY"},
        TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["wallet_credit_cents"] == 0, data
    assert data["risk_score"] == 0, data


# ===========================================================================
# entities / order_optional_defaults_applied (corner)
# ===========================================================================
def test_order_optional_flags_default_false(api):
    """PRD §3.1: "Two optional add-on flags are captured: `lost_damage_protection`,
    indicating whether the paid protection add-on was purchased (defaulting to
    not purchased), and `is_gift`, indicating whether the order is a gift
    (defaulting to not a gift)."

    Omitting both flags applies the defaults false/false.

    Design: Corner/entities/order_optional_defaults_applied
    """
    cust = create_customer(api, email="def@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    assert order["lost_damage_protection"] is False, order
    assert order["is_gift"] is False, order


# ===========================================================================
# entities / create_order_missing_required_field_returns_validation (corner)
# ===========================================================================
def test_create_order_missing_turnaround_rejected(api):
    """PRD §3.1: "Missing required fields, or an invalid enum or type on any
    field, are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_order_missing_required_field_returns_validation
    """
    cust = create_customer(api, email="mr@x.com")
    resp = api.create_order(
        {"customer_id": cust["id"], "plan_tier": "STANDARD_KIT", "output_option": "CLOUD"},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ===========================================================================
# entities / create_order_invalid_enum_turnaround_returns_validation (corner)
# ===========================================================================
def test_create_order_invalid_turnaround_enum_rejected(api):
    """PRD §3.1: "Missing required fields, or an invalid enum or type on any
    field, are rejected with `ERR_VALIDATION` (HTTP 400)."

    A turnaround outside {STANDARD, RUSH} is an invalid enum.

    Design: Corner/entities/create_order_invalid_enum_turnaround_returns_validation
    """
    cust = create_customer(api, email="ie@x.com")
    resp = api.create_order(
        {"customer_id": cust["id"], "plan_tier": "STANDARD_KIT",
         "turnaround": "OVERNIGHT", "output_option": "CLOUD"},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ===========================================================================
# entities / get_order_unknown_id_not_found (corner)
# ===========================================================================
def test_get_unknown_order_returns_not_found(api):
    """PRD §2.8: "the first identifier in the path that does not resolve to an
    existing resource causes the request to be rejected with `ERR_NOT_FOUND`
    (HTTP 404), before any deeper identifier or business rule is considered."

    Design: Corner/entities/get_order_unknown_id_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# entities / create_order_unknown_customer_not_found (corner)
# ===========================================================================
def test_create_order_unknown_customer_returns_not_found(api):
    """PRD §2.8: "when a request body names a foreign key — a `customer_id`,
    `machine_id`, `bin_id`, `media_item_id`, or `order_id` — that reference must
    resolve to an existing row. An unresolved body reference is rejected with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_order_unknown_customer_not_found
    """
    resp = api.create_order(
        {"customer_id": NON_EXISTENT_UUID, "plan_tier": "STANDARD_KIT",
         "turnaround": "STANDARD", "output_option": "CLOUD"},
        TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# validations / invalid_promo_code_returns_invalid_promo (corner)
# ===========================================================================
def test_invalid_promo_code_rejected(api):
    """PRD §3.1: "A `promo_code` that is present but is anything other than
    `SAVE5` causes the order creation to be rejected with `ERR_INVALID_PROMO`
    (HTTP 422)."

    Design: Corner/validations/invalid_promo_code_returns_invalid_promo
    """
    cust = create_customer(api, email="ip@x.com")
    resp = api.create_order(
        {"customer_id": cust["id"], "plan_tier": "STANDARD_KIT", "turnaround": "STANDARD",
         "output_option": "CLOUD", "promo_code": "BOGUS", "declared_tape_count": 1},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PROMO)


# ===========================================================================
# validations / access_missing_auth_returns_unauthenticated (corner)
# ===========================================================================
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    A request carrying no auth headers is rejected before path resolution.

    Design: Corner/validations/access_missing_auth_returns_unauthenticated
    """
    resp = api.get_order(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ===========================================================================
# rbac / intake_cannot_run_batch (corner)
# ===========================================================================
def test_intake_tech_cannot_run_batch(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Running a batch is a LabTech/Admin operation; an IntakeTech is refused.

    Design: Corner/rbac/intake_cannot_run_batch
    """
    base = setup_loaded_batch(api, customer_email="ic@x.com")
    resp = api.run_batch(base["batch"]["id"], TEST_USERS["intake_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ===========================================================================
# rbac / customer_cannot_review_claim (corner)
# ===========================================================================
def test_customer_cannot_review_claim(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Adjudicating a claim is a ClaimsAdjuster/Admin operation; a Customer is
    refused.

    Design: Corner/rbac/customer_cannot_review_claim
    """
    from test_helpers import (
        authorize_payment, receive_order, create_bin, log_media_item, file_claim,
    )
    cust = create_customer(api, email="cc@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    authorize_payment(api, order["id"], cust["id"])
    receive_order(api, order["id"])
    bin_ = create_bin(api, capacity=10)
    mi = log_media_item(api, order["id"], bin_["id"], "TAPE")
    claim = file_claim(api, order["id"], cust["id"], mi["id"], claim_type="LOST")
    resp = api.review_claim(claim["id"], {"decision": "APPROVE"},
                            make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ===========================================================================
# rbac / customer_not_owner_reading_others_order (corner)
# ===========================================================================
def test_customer_cannot_read_other_customers_order(api):
    """PRD §2.1: "a `Customer` may act on an `Order` (or an `OutputArtifact`
    belonging to that order) only when the order's `customer_id` equals
    `X-User-ID`. A violation is rejected with `ERR_NOT_OWNER` (HTTP 403)."

    Customer B reading Customer A's order is refused.

    Design: Corner/rbac/customer_not_owner_reading_others_order
    """
    cust_a = create_customer(api, email="owA@x.com")
    cust_b = create_customer(api, email="owB@x.com")
    order_a = create_order(api, cust_a["id"], declared={"declared_tape_count": 1})
    resp = api.get_order(order_a["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)


# ===========================================================================
# consistency_model / immediate_read_after_create (corner)
# ===========================================================================
def test_customer_immediately_readable_after_create(api):
    """PRD §3.7: "and is registered with an `email` (unique and non-empty), a
    `full_name`, and a two-letter `state_code`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    A customer created in one request is immediately readable with the same
    state_code in the following GET.

    Design: Corner/consistency_model/immediate_read_after_create
    """
    cust = create_customer(api, email="im@x.com", full_name="Imm", state_code="TX")
    got = validate_success(api.get_customer(cust["id"], TEST_USERS["admin_headers"]))
    assert got["id"] == cust["id"], got
    assert got["state_code"] == "TX", got
