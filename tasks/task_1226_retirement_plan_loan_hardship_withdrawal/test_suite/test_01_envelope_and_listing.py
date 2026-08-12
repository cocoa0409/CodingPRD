"""Envelope shape, pagination, and plan-scoped listing coverage (PRD §2.2, §2.3)."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_hardship_request_payload,
    create_loan_payload,
    create_participant_payload,
    create_plan_payload,
    enroll_participant,
    make_participant_headers,
    request_loan,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_response_envelope_shape_on_success_and_error_success_leg(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
    this standard envelope format in their JSON body" with meta.api_request_id,
    meta.api_request_timestamp, response_type, and data.

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(name="Plan Env"), ADMIN), 201
    )
    res = api.get_plan(plan["id"], ADMIN)
    body = res.json()
    assert "meta" in body and "response_type" in body and "data" in body
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    assert body["data"]["id"] == plan["id"]


def test_response_envelope_shape_on_success_and_error_error_leg(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format" with data.error_id and data.message and response_type error.

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    res = api.get_plan(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN
    )
    err = validate_error(res, ApiErrorId.ERR_PLAN_NOT_FOUND, expected_status=404)
    assert isinstance(err.get("message"), str) and len(err["message"]) > 0
    body = res.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]


def test_list_loans_pagination_defaults_and_fields(api):
    """PRD §2.3: "The `limit` parameter ... If not provided, it defaults to 10 ...
    The `offset` parameter ... defaults to 0." and "Paginated and non-paginated
    list-based responses include the following fields in the `meta` object of the
    response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_loans_pagination_defaults_and_fields
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    participant = enroll_participant(plan["id"], vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)

    res = api.list_participant_loans(participant["id"], ADMIN)
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert data[0]["id"] == loan["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_plan_scoped_list_endpoints_return_children(api):
    """PRD §3.1: "`loan_approval_chain` and `hardship_approval_chain` are ordered
    lists of approver roles, each defaulting to `PLAN_SPONSOR` followed by
    `RECORDKEEPER_ADMIN`, and each entry spawns one approval task per
    originating request." The plan's scoped listing endpoints surface the loans,
    hardship requests, and approval tasks booked under it (PRD §4).

    Design: Corner/endpoints/plan_scoped_list_endpoints_return_children
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    participant = enroll_participant(plan["id"], vested_balance_cents=20_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    hardship = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL",
                amount_cents=200_000,
                amount_semantics="GROSS",
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )

    loans, loans_meta = validate_paginated(api.list_plan_loans(plan["id"], ADMIN))
    hardships, hardships_meta = validate_paginated(
        api.list_plan_hardship_requests(plan["id"], ADMIN)
    )
    tasks, tasks_meta = validate_paginated(
        api.list_plan_approval_tasks(plan["id"], ADMIN, params={"limit": 100})
    )
    assert loans[0]["id"] == loan["id"]
    assert hardships[0]["id"] == hardship["id"]
    assert tasks_meta["total_count"] == 4  # 2 loan-chain + 2 hardship-chain tasks


def test_clock_default_is_fixed_startup_constant_disburse_leg(api):
    """PRD §2.6: "At startup the logical clock reads exactly
    `2026-05-01T00:00:00Z`; before any client sets it, every clock-dependent
    evaluation uses that default, and the server never falls back to wall-clock
    time."

    Design: Corner/endpoints/clock_default_is_fixed_startup_constant
    """
    from test_helpers import (
        approve_loan_fully,
        setup_plan_and_participant,
        request_loan,
    )

    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    approve_loan_fully(loan["id"])
    disbursed = validate_success(api.disburse_loan(loan["id"], ADMIN), 200)
    assert disbursed["disbursed_on"] == "2026-05-01T00:00:00Z"


def test_clock_default_is_fixed_startup_constant_set_leg(api):
    """PRD §2.6: "An admin-only test-driving capability advances the logical clock
    to a supplied `to_iso8601` instant and returns the resulting `current_utc`."

    Design: Corner/endpoints/clock_default_is_fixed_startup_constant
    """
    res = api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN)
    body = validate_success(res, 200)
    assert body["current_utc"] == "2026-08-01T00:00:00Z"
