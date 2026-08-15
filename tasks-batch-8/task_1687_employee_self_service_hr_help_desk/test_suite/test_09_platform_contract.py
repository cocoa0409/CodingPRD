"""Platform contract: response envelope, pagination, authentication, domain
404s, and cross-domain role boundaries (PRD §2.1, §2.2, §2.3, §2.10)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_error,
    validate_paginated,
    make_team,
    make_category,
    make_sla_policy,
    make_employee,
    create_ticket_for,
    create_dcr,
    get_dcr,
)

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]
PLANNER = TEST_USERS["planner_headers"]


def test_pagination_defaults_and_bounds(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` caps the
    number of items returned: it defaults to 10, with a minimum of 1 and a maximum of
    100. `offset` says how many items to skip and defaults to 0."
    PRD §2.3: "The `meta` object of every list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/pagination_defaults_and_bounds
    """
    team = make_team("Pg Team")
    for i in range(1, 12):
        make_category(team["id"], code=f"C{i:02d}", name=f"c{i:02d}")

    data, meta = validate_paginated(api.list_categories(ADMIN))
    assert len(data) == 10, f"default limit is 10, got {len(data)} rows"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 11
    assert meta["has_more"] is True

    body = api.list_categories(ADMIN).json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "array"

    tail, tail_meta = validate_paginated(
        api.list_categories(ADMIN, params={"limit": 5, "offset": 10})
    )
    assert len(tail) == 1, "the tail page holds the single remaining row"
    assert tail_meta["total_count"] == 11
    assert tail_meta["has_more"] is False


def test_not_found_sweep_returns_domain_404(api):
    """PRD §2.10: "4. **Existence.** Path identifiers resolve left to right, then
    body foreign keys resolve — `employee_id`, `category_id`, `agent_id`,
    `article_id`, `team_id`, `staffing_window_id`, `ticket_id` as applicable.
    Failures: `ERR_EMPLOYEE_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`,
    `ERR_CATEGORY_NOT_FOUND`, `ERR_ARTICLE_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_DCR_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, or
    `ERR_SHIFT_NOT_FOUND` (all 404)."

    Design: Corner/errors/not_found_sweep_returns_404
    """
    cases = [
        (api.get_ticket(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_TICKET_NOT_FOUND.value),
        (api.get_data_change_request(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_DCR_NOT_FOUND.value),
        (api.get_survey(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_SURVEY_NOT_FOUND.value),
        (api.get_staffing_window(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_WINDOW_NOT_FOUND.value),
        (api.get_kb_article(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_ARTICLE_NOT_FOUND.value),
        (api.get_employee(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value),
        (api.get_agent(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_AGENT_NOT_FOUND.value),
        (api.get_team(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_TEAM_NOT_FOUND.value),
        (api.get_category(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_CATEGORY_NOT_FOUND.value),
    ]
    for resp, error_id in cases:
        validate_error(resp, error_id)
        assert resp.status_code == 404, f"{error_id} must be HTTP 404, got {resp.status_code}"


def test_list_tickets_unauthenticated(api):
    """PRD §2.1: "Every request carries two mandatory HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming their operational
    capacity."
    PRD §2.1: "A request with missing or malformed headers, a role value outside this
    set, or — for the entity-backed roles below — an identifier that references no
    persisted row is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/list_tickets_unauthenticated
    """
    resp = api.list_tickets(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.status_code == 401


def test_steward_cannot_triage(api):
    """PRD §2.1: "A caller whose role is not listed for the endpoint, or who
    violates a record-level ownership scope, is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §3.5: "A new ticket first meets a human at triage, which moves `NEW` to
    `TRIAGED` and is performed by a `HelpDeskAgent` or a `SensitiveCaseManager`; for
    a sensitive ticket the caller must hold `SENSITIVE` clearance, otherwise the call
    fails with `ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`."

    Design: Corner/rbac/steward_cannot_triage
    """
    team = make_team("ST Team")
    category = make_category(team["id"], code="ST", name="ST")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E502", full_name="Ste Ward", email="ste@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="s")

    resp = api.triage_ticket(ticket["id"], {}, STEWARD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_planner_cannot_approve(api):
    """PRD §2.1: "A caller whose role is not listed for the endpoint, or who
    violates a record-level ownership scope, is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §3.7: "Approval is the compliance moment: it moves a request from
    `PENDING_VERIFICATION` or `PENDING_APPROVAL` to `APPLIED`, it is performed by an
    `HRDataSteward`, and it is gated by four checks."

    Design: Corner/rbac/planner_cannot_approve
    """
    employee = make_employee(employee_number="E503", full_name="Plan Ner", email="plan@x.com")
    dcr = create_dcr(employee["id"], "ADDRESS",
                     new_values={"address_line1": "4 D St", "city": "Tulsa",
                                 "region": "OK", "postal_code": "74101"})
    assert dcr["approval_status"] == "PENDING_APPROVAL"

    resp = api.approve_data_change_request(dcr["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    after = get_dcr(dcr["id"])
    assert after["approval_status"] == "PENDING_APPROVAL"
