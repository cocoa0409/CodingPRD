"""CRUD basics, defaults, uniqueness, computed volume rollup, survey lock,
list filtering, pagination bounds, and role/ownership access control.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    assert_move_job, NON_EXISTENT_UUID,
    register_customer, create_job, create_survey_with_items,
    setup_job_with_survey, setup_booked_job, schedule_dispatch,
    register_truck, register_crew, generate_estimate,
    create_customer_payload, create_move_job_payload, create_truck_payload,
    create_survey_item_payload, create_dispatch_payload, create_estimate_payload,
    make_customer_headers, TEST_USERS,
    ITEMS_120CF,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_create_move_job_returns_201_with_defaults(api):
    """PRD §3.2: "Once a customer exists, a job is created in the `QUOTING` and
    `UNPAID` state."
    PRD §3.2: "Two accessorial inputs are optional and each default to 0 when
    omitted: `stair_flights` ... and `long_carry_units`."
    PRD §2.4: "`version` (integer): a system-managed integer that starts at its
    initial value and increments by one on every mutation of the resource."

    A new move job defaults job_status QUOTING, payment_status UNPAID,
    stair_flights 0, version 1.

    Design: Corner/entities/create_move_job_returns_201_with_defaults
    """
    cust_id = register_customer()["id"]
    res = api.create_move_job(
        create_move_job_payload(cust_id, "LOCAL"), make_customer_headers(cust_id))
    job = validate_success(res, 201)
    assert_move_job(job)
    assert job["job_status"] == "QUOTING"
    assert job["payment_status"] == "UNPAID"
    assert job["stair_flights"] == 0
    assert job["version"] == 1


def test_get_move_job_not_found(api):
    """PRD §2.5: "referenced resources named in the body ... are checked for
    existence, and any miss yields `ERR_NOT_FOUND`."
    PRD §5: "`ERR_NOT_FOUND` | 404"

    A GET on a non-existent move-job UUID returns ERR_NOT_FOUND.

    Design: Corner/entities/get_move_job_not_found_returns_404
    """
    res = api.get_move_job(NON_EXISTENT_UUID, PLATFORM_ADMIN)
    validate_error(res, "ERR_NOT_FOUND", 404)


def test_create_move_job_missing_required_field(api):
    """PRD §3.12: "Malformed JSON or a missing required field surfaces as
    `ERR_VALIDATION`."

    A move job created without service_type returns ERR_VALIDATION.

    Design: Corner/entities/create_move_job_missing_required_field_returns_400
    """
    cust_id = register_customer()["id"]
    payload = create_move_job_payload(cust_id, "LOCAL")
    del payload["service_type"]
    res = api.create_move_job(payload, make_customer_headers(cust_id))
    validate_error(res, "ERR_VALIDATION", 400)


def test_create_move_job_invalid_enum(api):
    """PRD §3.12: "an enum value outside its allowed set or a numeric field outside
    its declared range surfaces as `ERR_INVALID_FIELD`."

    A move job with service_type 'AIR' (not LOCAL/LONG_HAUL) returns
    ERR_INVALID_FIELD.

    Design: Corner/entities/create_move_job_invalid_enum_returns_422
    """
    cust_id = register_customer()["id"]
    payload = create_move_job_payload(cust_id, "AIR")
    res = api.create_move_job(payload, make_customer_headers(cust_id))
    validate_error(res, "ERR_INVALID_FIELD", 422)


def test_duplicate_customer_email_rejected(api):
    """PRD §3.1: "The `email` must be unique across all customers and non-empty;
    registering a second customer with an `email` already on file is rejected with
    `ERR_DUPLICATE_EMAIL`."

    Re-using an existing email returns ERR_DUPLICATE_EMAIL.

    Design: Corner/entities/duplicate_customer_email_returns_409
    """
    first = validate_success(api.create_customer(
        create_customer_payload(email="dup-cust@example.com", full_name="First"),
        PLATFORM_ADMIN), 201)
    res = api.create_customer(
        create_customer_payload(email="dup-cust@example.com", full_name="Second",
                                origin_state_code="NY"),
        PLATFORM_ADMIN)
    validate_error(res, "ERR_DUPLICATE_EMAIL", 409)


def test_duplicate_truck_plate_rejected(api):
    """PRD §3.1: "A duplicate `plate` is rejected with `ERR_DUPLICATE_PLATE`."

    Registering a truck with an existing plate returns ERR_DUPLICATE_PLATE.

    Design: Corner/entities/duplicate_truck_plate_returns_409
    """
    validate_success(api.create_truck(
        create_truck_payload(plate="DUP-PLATE-1", capacity_cubic_feet=2000), DISPATCHER), 201)
    res = api.create_truck(
        create_truck_payload(plate="DUP-PLATE-1", capacity_cubic_feet=1000,
                             home_state_code="NY"), DISPATCHER)
    validate_error(res, "ERR_DUPLICATE_PLATE", 409)


def test_survey_volume_rolled_up_from_items(api):
    """PRD §3.2: "The `total_cubic_feet` is the sum, over every survey item
    belonging to the survey, of that item's `quantity` multiplied by its
    `cubic_feet_each`, and is kept exact. The `estimated_weight_lbs` is then derived
    by multiplying the exact `total_cubic_feet` by a household-goods density of seven
    pounds per cubic foot and rounding the result half up to a whole number of
    pounds."

    sofa 2@35 + box 40@3 = 190cf -> estimated_weight_lbs 1330 (190*7).

    Design: Corner/entities/computed_cubic_feet_rollup_input_ignored
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL")
    survey = create_survey_with_items(
        job["id"],
        [{"label": "sofa", "quantity": 2, "cubic_feet_each": 35},
         {"label": "box", "quantity": 40, "cubic_feet_each": 3}],
        survey_method="VIRTUAL")
    assert survey["total_cubic_feet"] == 190
    assert survey["estimated_weight_lbs"] == 1330


def test_survey_locked_after_estimate_rejects_new_item(api):
    """PRD §3.2: "A line item may only be appended while the survey is unlocked;
    once an estimate has been generated from a survey the survey's `locked` flag
    flips to true, and any further attempt to append an item is rejected with
    `ERR_SURVEY_LOCKED`."

    Adding an item to a survey locked by a generated estimate returns
    ERR_SURVEY_LOCKED.

    Design: Corner/state_machines/survey_locked_after_estimate_rejects_new_item
    """
    cust_id, job, survey = setup_job_with_survey(service_type="LOCAL", items=ITEMS_120CF)
    generate_estimate(job["id"], survey["id"], job["version"],
                      binding_type="BINDING", valuation_coverage="RELEASED")
    res = api.add_survey_item(
        survey["id"], create_survey_item_payload(label="lamp", quantity=1, cubic_feet_each=5),
        ESTIMATOR)
    validate_error(res, "ERR_SURVEY_LOCKED", 409)


def test_list_estimates_filtered_by_move_job_id(api):
    """PRD §3.5: "the accepted one is discoverable by listing the job's estimates
    filtered to the accepted status."
    PRD §4: "GET | `/estimates` | List estimates (filter by move_job_id, survey_id,
    status) | Estimator, PlatformAdmin, Customer"

    Filtering estimates by move_job_id returns that job's single estimate; meta
    total_count is 1.

    Design: Corner/endpoints/list_estimates_filtered_by_move_job_id
    """
    cust_id, job, survey = setup_job_with_survey(service_type="LOCAL", items=ITEMS_120CF)
    est = generate_estimate(job["id"], survey["id"], job["version"],
                            binding_type="BINDING", valuation_coverage="RELEASED")
    data, meta = validate_paginated(api.list_estimates(ESTIMATOR, params={"move_job_id": job["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == est["id"]


def test_list_survey_items_subresource(api):
    """PRD §4: "GET | `/surveys/{id}/items` | List items of a survey | Estimator,
    PlatformAdmin, Customer, Dispatcher"
    PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    A survey with two items lists them; meta total_count is 2.

    Design: Corner/endpoints/list_survey_items_subresource
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL")
    survey = create_survey_with_items(
        job["id"],
        [{"label": "sofa", "quantity": 2, "cubic_feet_each": 35},
         {"label": "box", "quantity": 40, "cubic_feet_each": 3}])
    data, meta = validate_paginated(api.list_survey_items(survey["id"], ESTIMATOR))
    assert meta["total_count"] == 2


def test_pagination_limit_out_of_bounds_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`,
    is rejected with `ERR_PAGINATION_INVALID`."

    GET /move-jobs with limit=500 (> max 100) returns ERR_PAGINATION_INVALID.

    Design: Corner/validations/pagination_limit_out_of_bounds_returns_422
    """
    res = api.list_move_jobs(PLATFORM_ADMIN, params={"limit": 500})
    validate_error(res, "ERR_PAGINATION_INVALID", 422)


def test_estimator_cannot_create_dispatch(api):
    """PRD §2.1: "When the headers are present and valid but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4: "POST | `/dispatches` | Schedule a truck+crew within a window |
    Dispatcher"

    An Estimator calling POST /dispatches (Dispatcher-only) returns
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/estimator_cannot_create_dispatch
    """
    truck = register_truck(capacity_cubic_feet=2000)
    crew = register_crew(head_count=3)
    cust_id, job, survey, estimate = setup_booked_job(service_type="LOCAL", items=ITEMS_120CF)
    res = api.create_dispatch(
        create_dispatch_payload(job["id"], truck["id"], crew["id"],
                                window_start="2026-07-01T09:00:00Z",
                                window_end="2026-07-01T12:00:00Z", required_crew_size=3),
        ESTIMATOR)
    validate_error(res, "ERR_FORBIDDEN_ROLE", 403)


def test_non_owner_customer_cannot_cancel_others_job(api):
    """PRD §2.1: "for customer-owned operations — accepting an estimate, cancelling
    a job, and applying a payment — the acting `Customer`'s `X-User-ID` must equal
    the targeted `MoveJob`'s `customer_id`, or the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Customer B cancelling Customer A's job returns ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/non_owner_customer_cannot_cancel_others_job
    """
    cust_a = register_customer(email="owner-a@example.com")["id"]
    cust_b = register_customer(email="owner-b@example.com")["id"]
    job = create_job(cust_a, "LOCAL")
    res = api.cancel_move_job(job["id"], make_customer_headers(cust_b))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", 403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    A POST /move-jobs with an unknown role header returns ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    cust_id = register_customer()["id"]
    bad_headers = {"X-User-ID": cust_id, "X-User-Role": "Anonymous",
                   "Content-Type": "application/json"}
    res = api.create_move_job(create_move_job_payload(cust_id, "LOCAL"), bad_headers)
    validate_error(res, "ERR_UNAUTHENTICATED", 401)
