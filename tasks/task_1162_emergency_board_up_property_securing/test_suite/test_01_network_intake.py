"""Network configuration, job intake, listing and envelope basics."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_job,
    assert_market,
    assert_property,
    assert_same_instant,
    assert_subcontractor,
    create_customer_payload,
    create_job_payload,
    create_market_payload,
    create_property_payload,
    get_success_data,
    is_valid_uuid,
    make_subcontractor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_market_creation_echo_and_system_fields(api, admin_headers, dispatcher_headers):
    """PRD §2.4: "`version` — an integer that starts at 1 and increments by
    exactly one on every mutation, whether the mutation was client-requested or
    the by-product of an automatic cascade."
    PRD §2.5: "Before any administrative intervention, the clock starts at
    exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock time
    under any circumstance."

    Design: Corner/entities/market_creation_echo_and_system_fields
    """
    payload = create_market_payload()
    res = api.create_market(payload, admin_headers)
    market = validate_success(res, 201)
    assert_market(market)
    assert market["version"] == 1
    # PRD §2.4 pins created_at to three fractional digits; §2.5 pins the clock
    # start to 2026-05-01T00:00:00Z — together: "2026-05-01T00:00:00.000Z".
    assert market["created_at"] == "2026-05-01T00:00:00.000Z"

    fetched = validate_success(api.get_market(market["id"], dispatcher_headers), 200)
    assert fetched["code"] == "SEA"
    assert fetched["generator_pool_units"] == 2
    assert fetched["removal_flat_fee_cents"] == 25000
    for field, value in payload.items():
        assert fetched[field] == value, f"echo mismatch on {field}"


def test_subcontractor_computed_fields_input_ignored(api, admin_headers):
    """PRD §3.1: "A new subcontractor starts with `status` set to `ACTIVE`, all
    three operational counters — `completed_job_count`, `breached_job_count`,
    `expired_offer_count` — at zero, and both reliability scores at 1.0000."

    Design: Corner/entities/subcontractor_computed_fields_input_ignored
    """
    payload = {
        "legal_name": "Gamed Crew",
        "status": "SUSPENDED",
        "completed_job_count": 99,
        "reliability_score_lenient": 0.1,
    }
    res = api.create_subcontractor(payload, admin_headers)
    sub = validate_success(res, 201)
    assert_subcontractor(sub)
    assert sub["status"] == "ACTIVE", "injected SUSPENDED must be ignored"
    assert sub["completed_job_count"] == 0
    assert sub["breached_job_count"] == 0
    assert sub["expired_offer_count"] == 0
    assert sub["reliability_score_lenient"] == pytest.approx(1.0)
    assert sub["reliability_score_strict"] == pytest.approx(1.0)


def test_job_customer_id_computed_input_ignored(api, admin_headers, dispatcher_headers):
    """PRD §3.2: "The job's `customer_id` is always derived from the property's
    owning customer — any client-supplied value is ignored."
    PRD §3.2: "it selects which of the market's SLA minute fields is snapshotted
    into the job's `sla_minutes` at creation"

    Design: Corner/entities/job_customer_id_computed_input_ignored
    """
    from test_helpers import create_market, register_customer, register_property

    market = create_market()
    customer = register_customer()
    prop = register_property(customer["id"], market["id"])
    payload = create_job_payload(
        prop["id"], incident_type="FIRE", priority="P2",
        customer_id="00000000-0000-0000-0000-000000000000",
    )
    job = validate_success(api.create_job(payload, dispatcher_headers), 201)
    assert_job(job)
    assert job["customer_id"] == customer["id"], "customer_id must derive from the property"
    assert job["sla_minutes"] == 480, "P2 job must snapshot sla_minutes_p2"


def test_job_initial_state_intake(api, admin_headers, dispatcher_headers):
    """PRD §3.2: "A new job enters `INTAKE` with `reported_at` stamped from the
    logical clock, `safety_cleared` and `compliance_breach` both false, and
    `total_planned_sheets` at zero."
    PRD §2.5: "Before any administrative intervention, the clock starts at
    exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock time
    under any circumstance."

    Design: Corner/state_machines/job_initial_state_intake
    """
    from test_helpers import create_market, register_customer, register_property

    market = create_market()
    customer = register_customer()
    prop = register_property(customer["id"], market["id"])
    job = validate_success(
        api.create_job(create_job_payload(prop["id"], incident_type="STORM", priority="P3"),
                       dispatcher_headers),
        201,
    )
    assert_job(job)
    assert job["work_status"] == "INTAKE"
    assert job["safety_cleared"] is False
    assert job["compliance_breach"] is False
    assert job["total_planned_sheets"] == 0
    assert job["version"] == 1
    assert job["sla_minutes"] == 1440, "P3 job must snapshot sla_minutes_p3"
    assert_same_instant(job["reported_at"], "2026-05-01T00:00:00Z")


def test_create_job_missing_required_property_id(api, dispatcher_headers):
    """PRD §2.7: "required body fields are present and values are well-formed
    (`ERR_INVALID_REQUEST`, HTTP 400)"

    Design: Corner/entities/create_job_missing_required_property_id
    """
    res = api.create_job({"incident_type": "FIRE", "priority": "P2"}, dispatcher_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_job_invalid_enum_rejected(api, admin_headers, dispatcher_headers):
    """PRD §2.7: "every enum field carries a member of its declared set
    (`ERR_INVALID_ENUM`, HTTP 400)."
    PRD §3.2: "the `incident_type` (`FIRE`, `STORM`, or `VANDALISM`)"

    Design: Corner/entities/create_job_invalid_enum_rejected
    """
    from test_helpers import create_market, register_customer, register_property

    market = create_market()
    customer = register_customer()
    prop = register_property(customer["id"], market["id"])
    payload = create_job_payload(prop["id"], incident_type="HAIL", priority="P2")
    res = api.create_job(payload, dispatcher_headers)
    validate_error(res, "ERR_INVALID_ENUM")


def test_get_job_not_found_returns_404(api, dispatcher_headers):
    """PRD §2.6: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first path identifier that does not correspond to an existing resource"

    Design: Corner/entities/get_job_not_found_returns_404
    """
    res = api.get_job(NON_EXISTENT_UUID, dispatcher_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_error_envelope_shape_on_not_found(api, dispatcher_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format" with "`response_type`: "error"" and a data object carrying
    "`error_id`" and "`message`", and "The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    res = api.get_job(NON_EXISTENT_UUID, dispatcher_headers)
    assert res.status_code == 404
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str) and body["meta"]["api_request_id"]
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_create_job_unauthenticated_missing_headers(api, admin_headers):
    """PRD §2.1: "A request missing either header, or bearing a role value outside
    the four recognized operational roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.1: "A fifth value, `Anonymous`, is recognized nowhere: it exists only
    as a marker for unauthenticated callers, and any request bearing it is rejected."

    Design: Corner/validations/create_job_unauthenticated_missing_headers
    """
    from test_helpers import create_market, register_customer, register_property

    market = create_market()
    customer = register_customer()
    prop = register_property(customer["id"], market["id"])
    payload = create_job_payload(prop["id"], incident_type="FIRE", priority="P2")

    # Anonymous role marker is rejected even with an otherwise valid body.
    res = api.create_job(payload, TEST_USERS["anonymous_headers"])
    validate_error(res, "ERR_UNAUTHENTICATED")

    # Missing auth headers entirely is likewise rejected.
    res = api.create_job(payload, {"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_list_pagination_envelope(api, admin_headers, dispatcher_headers):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "every list endpoint returns its resources sorted by creation
    timestamp (`created_at`) in ascending order — oldest first."

    Design: Corner/entities/list_pagination_envelope
    """
    from test_helpers import create_market, intake_job, register_customer, register_property

    market = create_market()
    customer = register_customer()
    prop = register_property(customer["id"], market["id"])
    job1 = intake_job(prop["id"], incident_type="FIRE", priority="P3")
    job2 = intake_job(prop["id"], incident_type="STORM", priority="P3")

    page1, meta = validate_paginated(api.list_jobs(dispatcher_headers, params={"limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    page2, meta = validate_paginated(api.list_jobs(dispatcher_headers, params={"limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False

    # Both jobs share the default-clock created_at; the two pages partition them.
    assert {page1[0]["id"], page2[0]["id"]} == {job1["id"], job2["id"]}
    assert page1[0]["created_at"] <= page2[0]["created_at"], "created_at ascending"


def test_filtered_list_isolation(api, admin_headers, dispatcher_headers):
    """PRD §3.2: "The job register can be listed filtered by `property_id`,
    `customer_id`, or `work_status`."
    PRD §3.1: "Properties can be listed filtered by `customer_id` or `market_id`."

    Design: Corner/endpoints/filtered_list_isolation
    """
    from test_helpers import create_market, intake_job, register_customer, register_property

    market = create_market()
    c1 = register_customer(full_name="Ann A", email="ann@x.com")
    c2 = register_customer(full_name="Bob B", email="bob@x.com")
    p1 = register_property(c1["id"], market["id"], address_line="1 Pine St", wind_zone="LOW")
    p2 = register_property(c2["id"], market["id"], address_line="2 Oak St", wind_zone="HIGH")
    j1 = intake_job(p1["id"], incident_type="FIRE", priority="P3")
    j2 = intake_job(p2["id"], incident_type="STORM", priority="P1")

    data, meta = validate_paginated(
        api.list_jobs(dispatcher_headers, params={"customer_id": c1["id"]}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [j1["id"]], "foreign customer's job must be excluded"

    data, meta = validate_paginated(
        api.list_properties(dispatcher_headers,
                            params={"market_id": market["id"], "customer_id": c2["id"]}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [p2["id"]]
    assert_property(data[0])


def test_reverse_list_empty(api, admin_headers, dispatcher_headers):
    """PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."
    PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/reverse_list_empty
    """
    from test_helpers import create_market, intake_job, register_customer, register_property

    market = create_market()
    customer = register_customer()
    prop = register_property(customer["id"], market["id"])
    job = intake_job(prop["id"], incident_type="FIRE", priority="P3")

    data, meta = validate_paginated(api.list_scope_items(job["id"], dispatcher_headers))
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
