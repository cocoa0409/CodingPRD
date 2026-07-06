"""Intake, configuration, and CRUD/validation surface.

Translates corner-design instances from the entities, state_machines (intake),
validations (config), endpoints, and rbac sections.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    create_skill_tag_payload, create_sla_policy_payload,
    create_virtual_assistant_payload, create_client_payload, scope_client_payload,
    create_engagement_payload, create_task_payload, unique_email,
    assert_skill_tag, assert_client, assert_task,
    TEST_USERS, make_client_headers,
)

SM = TEST_USERS["staffing_manager_headers"]
NEVER_CREATED_UUID = "00000000-0000-4000-8000-000000000000"


# ─── entities section ───────────────────────────────────────────────────────
def test_create_skill_tag_returns_201_with_fields(api):
    """PRD §3.1: "A **skill tag** records a stable `code` (uppercase snake form, unique across all skill tags, e.g. `BOOKKEEPING` or `CRM_ADMIN`), a human-readable `name`, and a flag `is_specialized` that defaults to false"
    PRD §4: "Creating a new resource returns HTTP 201 with the created resource in `data".

    Design: Corner/entities/create_skill_tag_returns_201_with_fields
    """
    res = api.create_skill_tag(
        create_skill_tag_payload(code="TAX_PREP", name="Tax Prep", is_specialized=True), SM)
    data = validate_success(res, 201)
    assert_skill_tag(data)
    assert data["code"] == "TAX_PREP"
    assert data["is_specialized"] is True


def test_skill_tag_is_specialized_default_false_when_omitted(api):
    """PRD §3.1: "A **skill tag** records a stable `code` (uppercase snake form, unique across all skill tags, e.g. `BOOKKEEPING` or `CRM_ADMIN`), a human-readable `name`, and a flag `is_specialized` that defaults to false"

    Design: Corner/entities/skill_tag_is_specialized_default_false_when_omitted
    """
    res = api.create_skill_tag({"code": "INVOICING", "name": "Invoicing"}, SM)
    data = validate_success(res, 201)
    assert data["is_specialized"] is False


def test_get_client_not_found_returns_404(api):
    """PRD §2.6: "an unresolved path id (a `client_id`, `va_id`, `engagement_id`, `cycle_id`, `task_id`, `entry_id`, `escalation_id`, `addon_id`, `invoice_id`, `skill_tag_id`, or `sla_policy_id` that names no existing record) yields `ERR_NOT_FOUND` (HTTP 404"

    Design: Corner/entities/get_client_not_found_returns_404
    """
    res = api.get_client(NEVER_CREATED_UUID, SM)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_client_missing_required_company_name_returns_invalid_request(api):
    """PRD §2.7: "well-formedness of the body, meaning required fields are present and numeric fields lie within their declared ranges (`raw_minutes` at least 1, hours at least 0, rates at least 0) — `ERR_INVALID_REQUEST".
    PRD §3.2: "A client enters the platform through intake, supplying a `company_name` and a `contact_email` (unique across all clients; a collision is `ERR_DUPLICATE"

    Design: Corner/entities/client_missing_required_company_name_returns_invalid_request
    """
    res = api.create_client({"contact_email": unique_email("noname")}, SM)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_client_open_task_count_computed_reflects_open_tasks(api):
    """PRD §3.4: "A new task is `QUEUED`, and creating it recomputes the client's `open_task_count` — the number of that client's tasks not in a terminal state"

    Design: Corner/entities/client_open_task_count_computed_reflects_open_tasks
    """
    from test_helpers import setup_active_client_engagement, create_task
    ctx = setup_active_client_engagement(skill_code="TYPING")
    create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="A",
                as_headers=ctx["client_headers"])
    create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="B",
                as_headers=ctx["client_headers"])
    client = validate_success(api.get_client(ctx["client"]["id"], SM), 200)
    assert client["open_task_count"] == 2


def test_client_status_initialized_pending_system_field(api):
    """PRD §3.2: "At intake the client is born `PENDING`, with `open_task_count` initialized to 0, and no commercial terms yet"

    Design: Corner/entities/client_status_initialized_pending_system_field
    """
    res = api.create_client(create_client_payload(company_name="Init"), SM)
    data = validate_success(res, 201)
    assert data["status"] == "PENDING"


def test_sla_policy_invalid_tier_enum_rejected(api):
    """PRD §3.1: "An **SLA policy** binds a priority `tier` — one of `STANDARD`, `PRIORITY`, or `URGENT`, unique across all policies — to two deadlines and a penalty"
    PRD §2.7: "well-formedness of the body, meaning required fields are present and numeric fields lie within their declared ranges (`raw_minutes` at least 1, hours at least 0, rates at least 0) — `ERR_INVALID_REQUEST".

    Design: Corner/entities/sla_policy_invalid_tier_enum_rejected
    """
    res = api.create_sla_policy(
        {"tier": "CRITICAL", "response_minutes": 60, "resolution_hours": 24,
         "breach_penalty_pct": 0.0}, SM)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_va_rating_out_of_range_returns_validation_range(api):
    """PRD §3.3: "A `rating` outside the 0-to-5 band or a `weekly_capacity_hours` below 1.0 is rejected with `ERR_VALIDATION_RANGE"

    Design: Corner/entities/va_rating_out_of_range_returns_validation_range
    """
    res = api.create_virtual_assistant(
        create_virtual_assistant_payload(full_name="Bad Rating",
                                         email=unique_email("badr"),
                                         weekly_capacity_hours=40, rating=6.0), SM)
    validate_error(res, "ERR_VALIDATION_RANGE", expected_status=422)


def test_skill_tag_immutable_no_version_field(api):
    """PRD §2.4: "Three entities are immutable reference records and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version`: `SkillTag`, `SlaPolicy`, and the singleton `Clock`. Implementers must not emit `updated_at` or `version` for those three"

    Design: Corner/entities/skill_tag_immutable_no_version_field
    """
    created = validate_success(api.create_skill_tag(
        create_skill_tag_payload(code="PROOFREADING", name="Proofreading"), SM), 201)
    res = api.get_skill_tag(created["id"], SM)
    data = validate_success(res, 200)
    assert data["code"] == "PROOFREADING"
    assert "version" not in data, "SkillTag must not carry a version field"
    assert "updated_at" not in data, "SkillTag must not carry an updated_at field"


def test_engagement_create_unknown_va_id_fk_rejected(api):
    """PRD §2.6: "foreign keys supplied in a request body — `client_id`, `va_id`, `required_skill_tag_id`, `skill_tag_id`, `cycle_id`, `task_id`, and each element of `required_skill_tag_ids` — are validated against existing records and, if any references a non-existent entity, the request is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 422"

    Design: Corner/entities/engagement_create_unknown_va_id_fk_rejected
    """
    client = validate_success(api.create_client(create_client_payload(company_name="Fkc"), SM), 201)
    res = api.create_engagement(
        {"client_id": client["id"], "va_id": "00000000-0000-4000-8000-000000000001"}, SM)
    validate_error(res, "ERR_REFERENCED_ENTITY_NOT_FOUND", expected_status=422)


# ─── state_machines section (intake / config transitions) ───────────────────
def test_scope_pending_client_persists_retainer_fields(api):
    """PRD §3.2: "Scoping requires `monthly_retainer_hours`, `base_rate_cents`, and `overage_rate_cents` to be present, and persists all of these fields onto the client"
    PRD §3.2: "The client itself then **scopes** the contract, moving from `PENDING` to `SCOPED"

    Design: Corner/state_machines/scope_pending_client_persists_retainer_fields
    """
    skill = validate_success(api.create_skill_tag(
        create_skill_tag_payload(code="SCOPE_SK", name="Scope Skill"), SM), 201)
    client = validate_success(api.create_client(create_client_payload(company_name="Scp"), SM), 201)
    res = api.scope_client(
        client["id"],
        scope_client_payload(required_skill_tag_ids=[skill["id"]],
                             monthly_retainer_hours=12, base_rate_cents=4500,
                             overage_rate_cents=7000, rollover_cap_hours=3,
                             scope_summary="books"),
        make_client_headers(client["id"]))
    data = validate_success(res, 200)
    assert data["status"] == "SCOPED"
    assert data["monthly_retainer_hours"] == 12
    assert data["base_rate_cents"] == 4500


# ─── endpoints section ──────────────────────────────────────────────────────
def test_list_clients_pagination_invalid_limit_rejected(api):
    """PRD §2.3: "A request whose `limit` falls outside the range 1 through 100 inclusive, or whose `offset` is negative, is rejected with `ERR_PAGINATION_INVALID` (HTTP 422"

    Design: Corner/endpoints/list_clients_pagination_invalid_limit_rejected
    """
    res = api.list_clients(SM, params={"limit": 0})
    validate_error(res, "ERR_PAGINATION_INVALID", expected_status=422)


def test_list_tasks_filtered_by_client_id_reverse_reachability(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the count of all matching records before the page window is applied), and `has_more` (true when records remain beyond the current window) in the `meta` block"

    Design: Corner/endpoints/list_tasks_filtered_by_client_id_reverse_reachability
    """
    skill = validate_success(api.create_skill_tag(
        create_skill_tag_payload(code="LRR_SK", name="Lrr Skill"), SM), 201)
    client = validate_success(api.create_client(create_client_payload(company_name="Lrr"), SM), 201)
    task = validate_success(api.create_task(
        create_task_payload(client["id"], title="Lrr task",
                           required_skill_tag_id=skill["id"]),
        make_client_headers(client["id"])), 201)
    data, meta = validate_paginated(api.list_tasks(SM, params={"client_id": client["id"]}))
    assert any(t["id"] == task["id"] for t in data), "created task must appear in filtered list"
    assert "total_count" in meta and "has_more" in meta


def test_list_addons_filtered_by_engagement_id_reverse_reachability(api):
    """PRD §3.6: "A client requests an **add-on** on a specific engagement by naming the `engagement_id`, the `skill_tag_id` of the specialized skill, and a `surcharge_rate_cents".
    PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the count of all matching records before the page window is applied), and `has_more` (true when records remain beyond the current window) in the `meta` block"

    Design: Corner/endpoints/list_addons_filtered_by_engagement_id_reverse_reachability
    """
    skill = validate_success(api.create_skill_tag(
        create_skill_tag_payload(code="ARR_SK", name="Arr Skill", is_specialized=True), SM), 201)
    va = validate_success(api.create_virtual_assistant(
        create_virtual_assistant_payload(full_name="Va Arr", email=unique_email("vaarr"),
                                         skill_tag_ids=[skill["id"]]), SM), 201)
    client = validate_success(api.create_client(create_client_payload(company_name="Arr"), SM), 201)
    ch = make_client_headers(client["id"])
    validate_success(api.scope_client(client["id"],
        scope_client_payload(required_skill_tag_ids=[skill["id"]]), ch), 200)
    eng = validate_success(api.create_engagement(
        create_engagement_payload(client["id"], va["id"]), SM), 201)
    addon = validate_success(api.create_addon(
        {"engagement_id": eng["id"], "skill_tag_id": skill["id"], "surcharge_rate_cents": 3000},
        ch), 201)
    data, _ = validate_paginated(api.list_addons(SM, params={"engagement_id": eng["id"]}))
    assert any(a["id"] == addon["id"] for a in data), "requested add-on must appear in filtered list"


# ─── rbac section ───────────────────────────────────────────────────────────
def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of these three recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401"

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    res = api.list_clients(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_va_cannot_assign_task_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested operation — or is an ownership-bound role acting on a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403"

    Design: Corner/rbac/va_cannot_assign_task_forbidden
    """
    from test_helpers import setup_active_client_engagement, create_task
    ctx = setup_active_client_engagement(skill_code="FBD_SK")
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="Fbd task",
                       as_headers=ctx["client_headers"])
    res = api.assign_task(task["id"], ctx["va_headers"])
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
