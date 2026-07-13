"""Registration, pro verification lifecycle, and catalog/config validation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId, TEST_USERS, make_pro_headers,
    assert_customer, assert_pro,
    create_customer_payload, create_pro_payload,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["admin_headers"]


def test_register_customer_returns_201_with_server_minted_fields(api):
    """PRD 3.1: "Customers are registered the same way by an admin, each with an
    email, a full_name, and an optional phone; the email on both customers and
    pros must be unique and non-empty."
    PRD 4: "Operations that create a new, standalone resource return 201 Created."

    Design: Corner/entities/create_customer_success_returns_201_and_fields
    """
    payload = create_customer_payload(email="new@x.com", full_name="New Cust", phone="555-1000")
    resp = api.create_customer(payload, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_customer(data)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert data["email"] == "new@x.com", "email must echo the input"
    assert data["full_name"] == "New Cust"


def test_register_customer_without_email_rejected(api):
    """PRD 3.1: "the email on both customers and pros must be unique and non-empty."
    PRD 2.9: "Field validity — enums, ranges, and interval fields are within
    their declared bounds, else ERR_INVALID_REQUEST (422)."

    Design: Corner/entities/create_customer_missing_required_email_returns_invalid_request
    """
    resp = api.create_customer({"full_name": "No Email"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_unknown_pro_returns_not_found(api):
    """PRD 2.9: "Existence — every resource named in the path or body exists,
    validated left-to-right so the first missing reference determines the error,
    else ERR_NOT_FOUND (404)."

    Design: Corner/entities/get_pro_not_found_returns_404
    """
    resp = api.get_pro(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_new_pro_reputation_and_wallet_fields_default_zero(api):
    """PRD 3.1: "A newly registered pro starts with `verification_status` of
    `UNVERIFIED` and `billing_mode` of `PAY_PER_LEAD`; its `subscription_plan_id`
    is null, its wallet `credit_balance_cents` and `remaining_lead_credits` are
    zero, and its reputation fields `rating_avg`, `rating_count`,
    `provisional_rating`, and `dispute_count` all begin at zero."

    Design: Corner/entities/new_pro_rating_fields_default_zero
    """
    resp = api.create_pro(create_pro_payload(email="fresh@x.com", business_name="Fresh"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_pro(data)
    assert data["rating_avg"] == 0.0
    assert data["rating_count"] == 0
    assert data["provisional_rating"] == 0.0
    assert data["credit_balance_cents"] == 0
    assert data["verification_status"] == "UNVERIFIED"


def test_create_request_with_unknown_category_returns_not_found(api):
    """PRD 2.9: "Existence — every resource named in the path or body exists,
    validated left-to-right so the first missing reference determines the error,
    else ERR_NOT_FOUND (404)."

    Design: Corner/entities/create_request_unknown_category_returns_not_found
    """
    from test_helpers import make_customer_headers, create_service_request_payload
    cust = get_success_data(api.create_customer(create_customer_payload(), ADMIN))
    payload = create_service_request_payload(cust["id"], NON_EXISTENT_UUID)
    resp = api.create_service_request(payload, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_approve_already_verified_pro_returns_invalid_state(api):
    """PRD 3.1: "A decision of APPROVE moves a PENDING pro to VERIFIED; a decision
    of SUSPEND moves either a PENDING or an already-VERIFIED pro to SUSPENDED."
    PRD 3.1: "Attempting to verify a pro that is not in a state permitting the
    decision is an ERR_INVALID_STATE;"

    Design: Corner/state_machines/verify_approve_from_verified_returns_invalid_state
    """
    pro = get_success_data(api.create_pro(create_pro_payload(), ADMIN))
    pid = pro["id"]
    get_success_data(api.submit_verification(pid, make_pro_headers(pid)))
    get_success_data(api.verify_pro(pid, {"decision": "APPROVE"}, ADMIN))
    resp = api.verify_pro(pid, {"decision": "APPROVE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_verify_with_unknown_decision_returns_validation_decision(api):
    """PRD 3.1: "supplying a `decision` outside the allowed set is rejected with
    `ERR_VALIDATION_DECISION`."

    Design: Corner/validations/verify_bad_decision_returns_validation_decision
    """
    pro = get_success_data(api.create_pro(create_pro_payload(), ADMIN))
    pid = pro["id"]
    get_success_data(api.submit_verification(pid, make_pro_headers(pid)))
    resp = api.verify_pro(pid, {"decision": "MAYBE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_DECISION)


def test_subscribe_to_nonexistent_plan_returns_subscription_required(api):
    """PRD 3.1: "If the supplied plan does not exist, or the pro is already on
    that plan, the request is rejected with ERR_SUBSCRIPTION_REQUIRED."

    Design: Corner/validations/subscribe_unknown_plan_returns_subscription_required
    """
    pro = get_success_data(api.create_pro(create_pro_payload(), ADMIN))
    pid = pro["id"]
    resp = api.subscribe_pro(pid, {"subscription_plan_id": NON_EXISTENT_UUID}, make_pro_headers(pid))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED)


def test_credit_topup_bumps_pro_version_and_wallet(api):
    """PRD 3.1: "An operator funds a pro's wallet with a top-up, supplying
    amount_cents, which is added to credit_balance_cents and bumps the pro's
    version."
    PRD 2.4: "version — an integer that starts at its initial value and
    increments by one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/credit_topup_increments_pro_version
    """
    pro = get_success_data(api.create_pro(create_pro_payload(), ADMIN))
    pid = pro["id"]
    version_before = pro["version"]
    updated = validate_success(api.credit_topup(pid, {"amount_cents": 1000}, ADMIN))
    assert updated["version"] == version_before + 1, "top-up must bump version by exactly one"
    assert updated["credit_balance_cents"] == 1000
