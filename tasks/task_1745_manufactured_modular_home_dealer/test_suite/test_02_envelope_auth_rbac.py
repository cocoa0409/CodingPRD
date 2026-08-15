"""Response envelope, authentication, authorization, and ownership claims (PRD §2.1, §2.2, §2.8)."""
from test_helpers import (
    NON_EXISTENT_ID,
    TEST_USERS,
    ApiErrorId,
    create_customer,
    make_customer_headers,
    new_order_scenario,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]


def test_response_envelope_shape(api, admin_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/response_envelope_shape
    """
    resp = api.create_home_model(
        {
            "model_code": "M-ENV-1",
            "name": "Envelope One",
            "floor_plan_type": "SINGLE_WIDE",
            "section_count": 1,
            "width_ft": 13.9,
            "length_ft": 66,
            "base_price_cents": 4_200_000,
            "factory_lead_time_days": 14,
        },
        admin_headers,
    )
    body = resp.json()
    assert resp.status_code == 201
    assert body["response_type"] == "object", f"single-resource response_type must be 'object', got {body['response_type']}"
    assert isinstance(body["meta"].get("api_request_id"), str) and body["meta"]["api_request_id"].startswith("req_")
    assert body["data"]["model_code"] == "M-ENV-1"

    err_resp = api.get_home_model(NON_EXISTENT_ID, admin_headers)
    err_body = err_resp.json()
    assert err_resp.status_code == 404
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_HOME_MODEL_NOT_FOUND"
    assert isinstance(err_body["data"].get("message"), str) and err_body["data"]["message"]


def test_request_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every API request must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the acting role. If
    either header is missing, or the role value is not one of the declared role
    names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/request_missing_auth_headers_unauthenticated
    """
    resp = api.create_home_model(
        {
            "model_code": "M-1",
            "name": "One",
            "floor_plan_type": "SINGLE_WIDE",
            "section_count": 1,
            "width_ft": 13.9,
            "length_ft": 66,
            "base_price_cents": 4_200_000,
            "factory_lead_time_days": 14,
        },
        None,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unauthenticated_beats_not_found(api):
    """PRD §2.8: "Incoming requests are validated against the following checks in
    the stated order; the first failing check determines the response."
    PRD §2.8: "(all endpoints): `X-User-Role` and `X-User-ID` present and the
    role declared, else `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.8: "(all endpoints with path ids): path template ids resolve,
    validated left-to-right; the first missing resource yields that entity's
    not-found error (HTTP 404)".

    Design: Corner/validations/unauthenticated_beats_not_found
    """
    resp = api.get_sales_order(NON_EXISTENT_ID, None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_entity_not_found_matrix(api):
    """PRD §2.8: "(all endpoints with path ids): path template ids resolve,
    validated left-to-right; the first missing resource yields that entity's
    not-found error (HTTP 404) — `ERR_HOME_MODEL_NOT_FOUND`,
    `ERR_COMMUNITY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_HOME_UNIT_NOT_FOUND`, `ERR_SALES_ORDER_NOT_FOUND`,
    `ERR_ORDER_OPTION_NOT_FOUND`, `ERR_SITE_EVALUATION_NOT_FOUND`,
    `ERR_FINANCING_APPLICATION_NOT_FOUND`, `ERR_TRANSPORT_CREW_NOT_FOUND`,
    `ERR_TRANSPORT_JOB_NOT_FOUND`, `ERR_TITLE_RECORD_NOT_FOUND`,
    `ERR_WARRANTY_CLAIM_NOT_FOUND`, or `ERR_TRADE_IN_APPRAISAL_NOT_FOUND`."

    Design: Corner/errors/entity_not_found_matrix
    """
    cases = [
        (api.get_home_model, ApiErrorId.ERR_HOME_MODEL_NOT_FOUND, ADMIN),
        (api.get_community, ApiErrorId.ERR_COMMUNITY_NOT_FOUND, ADMIN),
        (api.get_lot, ApiErrorId.ERR_LOT_NOT_FOUND, CONSULTANT),
        (api.get_customer, ApiErrorId.ERR_CUSTOMER_NOT_FOUND, CONSULTANT),
        (api.get_home_unit, ApiErrorId.ERR_HOME_UNIT_NOT_FOUND, ADMIN),
        (api.get_site_evaluation, ApiErrorId.ERR_SITE_EVALUATION_NOT_FOUND, CONSULTANT),
        (api.get_financing_application, ApiErrorId.ERR_FINANCING_APPLICATION_NOT_FOUND, TEST_USERS["lender_headers"]),
        (api.get_transport_crew, ApiErrorId.ERR_TRANSPORT_CREW_NOT_FOUND, TEST_USERS["coordinator_headers"]),
        (api.get_transport_job, ApiErrorId.ERR_TRANSPORT_JOB_NOT_FOUND, TEST_USERS["coordinator_headers"]),
        (api.get_title_record, ApiErrorId.ERR_TITLE_RECORD_NOT_FOUND, ADMIN),
        (api.get_warranty_claim, ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND, TEST_USERS["service_headers"]),
        (api.get_trade_in_appraisal, ApiErrorId.ERR_TRADE_IN_APPRAISAL_NOT_FOUND, TEST_USERS["appraiser_headers"]),
    ]
    for call, error_id, headers in cases:
        resp = call(NON_EXISTENT_ID, headers)
        validate_error(resp, error_id)

    resp = api.void_order_option(NON_EXISTENT_ID, CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_ORDER_OPTION_NOT_FOUND)


def test_customer_cannot_create_home_model(api):
    """PRD §2.1: "If the role is declared but not authorized for the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /api/home-models — "Register a factory model in the catalog |
    DealershipAdmin".

    Design: Corner/rbac/customer_cannot_create_home_model
    """
    customer = create_customer()
    resp = api.create_home_model(
        {
            "model_code": "M-R1-1",
            "name": "One",
            "floor_plan_type": "SINGLE_WIDE",
            "section_count": 1,
            "width_ft": 13.9,
            "length_ft": 66,
            "base_price_cents": 4_200_000,
            "factory_lead_time_days": 14,
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_customer_cannot_claim_against_others_order(api):
    """PRD §3.8: "A warranty claim is filed against a `home_unit_id` and the
    `sales_order_id` that sold it — the order is the ownership anchor for
    `Customer` callers, whose `X-User-ID` must equal the order's `customer_id`,
    else `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_resubmit_others_claim
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND")
    other_customer = create_customer()
    resp = api.create_warranty_claim(
        {
            "home_unit_id": scn["unit"]["id"],
            "sales_order_id": scn["order"]["id"],
            "claim_type": "FACTORY_DEFECT",
            "description": "Not my order",
            "estimated_cost_cents": 10_000,
        },
        make_customer_headers(other_customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
