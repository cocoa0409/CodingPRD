"""Project creation defaults, not-found behavior, response envelope, and
list pagination."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_project,
    create_project_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_project_created_with_defaults(api, pm_headers):
    """PRD section 3.1: "The project also records the
    `equipment_hourly_rate_cents` at which crane time is billed under
    time-and-materials work, a `retainage_pct` specifying the fraction withheld
    from each non-final invoice (defaulting to 0.10 when omitted, and always
    within zero to 0.20 inclusive), and an `ot_basis` of `DAILY_OT` or
    `WEEKLY_OT` selecting the prevailing-wage overtime regime for the project's
    labor — `DAILY_OT` applies when the field is omitted."
    PRD section 3.1: "A new project starts with `work_status` of `AWARDED`,
    `hold_status` of `CLEAR`, no approved rigging plan
    (`approved_rigging_plan_id` and `approved_rigging_plan_revision` are null),
    all three rollup figures (`approved_labor_cents`,
    `approved_equipment_cents`, `invoiced_cents`) at zero, and `version` 1."

    Design: Corner/entities/project_created_with_defaults
    """
    payload = create_project_payload(
        name="Defaults Job",
        customer_name="Acme",
        site_address="20 Plant Rd",
        retainage_pct=None,  # omitted -> default applies
        ot_basis=None,  # omitted -> default applies
    )
    assert "retainage_pct" not in payload and "ot_basis" not in payload

    resp = api.create_project(payload, pm_headers)
    data = validate_success(resp, 201)

    assert_project(data)
    assert data["retainage_pct"] == 0.10, (
        f"retainage_pct default should be 0.10, got {data['retainage_pct']}"
    )
    assert data["ot_basis"] == "DAILY_OT", (
        f"ot_basis default should be DAILY_OT, got {data['ot_basis']}"
    )
    assert data["work_status"] == "AWARDED"
    assert data["hold_status"] == "CLEAR"
    assert data["version"] == 1
    assert data["approved_rigging_plan_id"] is None
    assert data["approved_rigging_plan_revision"] is None
    assert data["approved_labor_cents"] == 0
    assert data["approved_equipment_cents"] == 0
    assert data["invoiced_cents"] == 0


def test_project_get_not_found_returns_404(api, pm_headers):
    """PRD section 2.6: "Existence checking follows: every resource identifier
    appearing in the path or the request body must resolve to an existing
    resource, or the request fails with `ERR_NOT_FOUND`."

    Design: Corner/entities/project_get_not_found_returns_404
    """
    resp = api.get_project(NON_EXISTENT_UUID, pm_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_response_envelope_shape(api, pm_headers, pay_headers):
    """PRD section 2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."
    PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."
    PRD section 2.2: "The `api_request_timestamp` is a server-generated ISO
    8601 UTC timestamp with three fractional digits."

    Design: Corner/endpoints/response_envelope_shape
    """
    create_resp = api.create_project(
        create_project_payload(name="Envelope Job", site_address="58 Plant Rd"),
        pm_headers,
    )
    body = create_resp.json()
    assert "meta" in body and "response_type" in body and "data" in body
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"

    created = validate_success(create_resp, 201)
    get_resp = api.get_project(created["id"], pay_headers)
    get_body = get_resp.json()
    assert get_body["response_type"] == "object"
    assert isinstance(get_body["meta"]["api_request_id"], str)
    assert is_iso8601_timestamp(get_body["meta"]["api_request_timestamp"])
    fetched = validate_success(get_resp)
    assert fetched["id"] == created["id"]


def test_projects_list_pagination(api, pm_headers):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned; when omitted it defaults to 10, and it may not be less than 1 or
    more than 100."
    PRD section 2.3: "List responses carry the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope."

    Design: Corner/endpoints/projects_list_pagination
    """
    for i in range(1, 4):
        api.create_project(
            create_project_payload(
                name=f"Page Job {i}",
                site_address=f"{54 + i} Plant Rd",
                billing_mode="LUMP_SUM" if i == 3 else "TM",
            ),
            pm_headers,
        )

    page1, meta1 = validate_paginated(
        api.list_projects(pm_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2, f"page 1 should hold 2 items, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_projects(pm_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1, f"page 2 should hold 1 item, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
