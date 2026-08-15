"""Endpoint-surface and immediate-consistency tests: pagination envelope,
reverse reachability, and the logical clock (PRD §2.2, §2.3, §2.5, §3.2, §4)."""
from test_helpers import (
    validate_success, validate_paginated,
    ApiErrorId, TEST_USERS, headers_for,
    assert_instant_equals, assert_complaint,
    setup_reference_data, setup_complaint, intake_complaint, set_clock,
    get_complaint,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]


def test_complaints_list_pagination_envelope(api):
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. Results are sorted by `created_at` ascending.
    The `meta` block of every list response carries `limit`, `offset`,
    `total_count`, and `has_more` so callers can page deterministically to the
    end of any collection."

    Design: Corner/endpoints/complaints_list_pagination_envelope
    """
    setup_reference_data("P-E1", "WEB", "C.E1")
    for i in range(12):
        intake_complaint("P-E1", "WEB", "C.E1",
                         complainant_ref=f"CU-E1-{i + 1:02d}", narrative=f"n{i + 1:02d}")

    page, meta = validate_paginated(
        api.list_complaints(AUDITOR, params={"product_code": "P-E1",
                                             "limit": 10, "offset": 10})
    )
    assert meta["total_count"] == 12, f"expected total_count 12, got {meta['total_count']}"
    assert len(page) == 2, f"page 2 of 12 at limit 10 must hold 2 items, got {len(page)}"
    assert meta["has_more"] is False, "the final page must report has_more false"
    assert meta["limit"] == 10
    assert meta["offset"] == 10


def test_product_complaints_subresource_reverse_reachability(api):
    """PRD §4: "| GET | /complaint-office/products/{id}/complaints | List
    complaints of a product (optional `status` filter) | ComplaintManager,
    CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover,
    ExecutiveReviewer, Auditor |"
    PRD §2.3: "Results are sorted by `created_at` ascending."

    Design: Corner/endpoints/product_complaints_subresource_reverse_reachability
    """
    refs_a = setup_reference_data("P-E2A", "WEB", "C.E2")
    pa = refs_a["product"]["id"]
    pb = api.create_product({"product_code": "P-E2B", "display_name": "E2B"}, MANAGER)
    pb_id = validate_success(pb, expected_status=201)["id"]

    ca = intake_complaint("P-E2A", "WEB", "C.E2", complainant_ref="CU-E2A", narrative="a")
    cb = intake_complaint("P-E2B", "WEB", "C.E2", complainant_ref="CU-E2B", narrative="b")

    listed, meta = validate_paginated(api.list_product_complaints(pa, AUDITOR))
    ids = [c["id"] for c in listed]
    assert ids == [ca["id"]], (
        f"product A's complaints must be exactly its own complaint, got {ids}"
    )
    assert cb["id"] not in ids

    listed_b, _ = validate_paginated(api.list_product_complaints(pb_id, AUDITOR))
    assert [c["id"] for c in listed_b] == [cb["id"]]


def test_clock_set_endpoint_updates_logical_time(api):
    """PRD §2.5: "A `ComplaintManager` may advance it through an admin-only
    test-driving capability that accepts a `to_iso8601` instant and sets the
    clock to that value; the endpoint returns the current logical time as
    `current_utc`."
    PRD §3.2: "A successful intake stamps `received_at` from the logical clock,
    sets `status` to `INTAKE`, records the acting `X-User-ID` as `owner_user_id`
    (the anchor for later segregation-of-duties checks), initializes `version` at
    1, appends a `CREATED` audit event, increments the product's
    `open_complaint_count` by 1, and recomputes the product's `posture`."

    Design: Corner/endpoints/clock_set_endpoint_updates_logical_time
    """
    clock = validate_success(api.set_clock("2026-08-03T04:05:06Z", MANAGER))
    assert_instant_equals(clock["current_utc"], "2026-08-03T04:05:06Z", "current_utc")

    setup_reference_data("P-E3", "WEB", "C.E3")
    complaint = intake_complaint("P-E3", "WEB", "C.E3", narrative="clock check")
    assert_instant_equals(complaint["received_at"], "2026-08-03T04:05:06Z",
                          "received_at")


def test_complaint_default_clock_startup_value(api):
    """PRD §2.5: "At server startup the logical clock reads exactly
    2026-08-01T00:00:00Z."
    PRD §2.5: "Before any such call the default value stands, and the clock never
    falls back to wall-clock time under any circumstance."

    Design: Corner/endpoints/complaint_default_clock_startup_value
    """
    setup_reference_data("P-E4", "WEB", "C.E4")
    complaint = intake_complaint("P-E4", "WEB", "C.E4", narrative="default clock")
    assert_instant_equals(complaint["received_at"], "2026-08-01T00:00:00Z",
                          "received_at")


def test_immediate_consistency_intake_response_contains_final_fields(api):
    """PRD §3.2: "A successful intake stamps `received_at` from the logical
    clock, sets `status` to `INTAKE`, records the acting `X-User-ID` as
    `owner_user_id` (the anchor for later segregation-of-duties checks),
    initializes `version` at 1, appends a `CREATED` audit event, increments the
    product's `open_complaint_count` by 1, and recomputes the product's
    `posture`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/consistency_model/immediate_consistency_intake_response_contains_final_fields
    """
    setup_reference_data("P-CM1", "WEB", "C.CM1")
    response = api.create_complaint(
        {"complainant_ref": "CU-CM1", "channel_code": "WEB",
         "product_code": "P-CM1", "category_code": "C.CM1", "narrative": "immediate"},
        headers_for("IntakeSpecialist", "user_cm1"),
    )
    data = validate_success(response, expected_status=201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']}"
    )
    assert data["status"] == "INTAKE"
    assert data["owner_user_id"] == "user_cm1"
    assert data["version"] == 1
    assert_instant_equals(data["received_at"], "2026-08-01T00:00:00Z", "received_at")
