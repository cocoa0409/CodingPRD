"""Projects, areas, roster, language governance, RBAC, envelopes, pagination.

Translates queue-B instances from the entities, state_machines, endpoints, and
rbac sections of the corner-design index.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_project_payload,
    create_area_payload,
    assert_project,
    assert_case,
    create_project,
    create_open_project,
    create_draft_area,
    create_open_area,
    add_case,
)

ADMIN = TEST_USERS["survey_admin_headers"]
SUPERVISOR = TEST_USERS["field_supervisor_headers"]
ENUM = TEST_USERS["enumerator_headers"]


def test_create_project_missing_name_returns_validation(api):
    """PRD §2.11: "then structural input validation — required fields, correct
    types, valid enum membership, and the rule that an attempt's `window_end` is
    strictly after its `window_start` (`ERR_VALIDATION`)".

    Design: Corner/entities/create_project_missing_name_returns_validation
    """
    payload = create_project_payload()
    del payload["name"]
    res = api.create_project(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_create_project_defaults_applied(api):
    """PRD §3.1: "Three further settings are optional and fall back to defaults
    when omitted: `fraud_score_threshold`, the score at or above which a captured
    response is flagged for reinterview, defaults to 60 and must lie between 0 and
    100; `max_attempts`, the ceiling on contact attempts per case, defaults to 6
    and must be at least 1; and `mileage_rate_cents_per_mile`, the reimbursement
    rate applied to in-person attempt mileage, defaults to 67 cents and must be
    non-negative."
    PRD §3.1: "A newly created project begins in `PLANNING`."

    Design: Corner/entities/create_project_defaults_applied
    """
    res = api.create_project(create_project_payload(name="Wave S"), ADMIN)
    proj = validate_success(res, 201)
    assert proj["fraud_score_threshold"] == 60
    assert proj["max_attempts"] == 6
    assert proj["mileage_rate_cents_per_mile"] == 67
    assert proj["status"] == "PLANNING"
    assert_project(proj)


def test_create_project_success_envelope_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §3.1: "A newly created project begins in `PLANNING`."

    Design: Corner/endpoints/create_project_success_envelope_shape
    """
    res = api.create_project(create_project_payload(name="Wave AF"), ADMIN)
    body = res.json()
    assert body["response_type"] == "object"
    proj = validate_success(res, 201)
    assert proj["status"] == "PLANNING"


def test_create_project_default_language_unsupported(api):
    """PRD §2.10: "A project whose `default_language` is absent from
    `supported_languages` is rejected with `ERR_UNSUPPORTED_LANGUAGE`."

    Design: Corner/validations/create_project_default_language_unsupported_returns_error
    """
    res = api.create_project(
        create_project_payload(name="Wave AB", default_language="ZH",
                               supported_languages=["EN", "ES"]),
        ADMIN)
    validate_error(res, "ERR_UNSUPPORTED_LANGUAGE", expected_status=400)


def test_get_nonexistent_case_returns_not_found(api):
    """PRD §2.6: "The server validates the path identifiers strictly left to right
    and rejects the request at the first identifier that does not resolve to an
    existing resource, returning the not-found error for that resource type —
    `ERR_PROJECT_NOT_FOUND`, `ERR_AREA_NOT_FOUND`, `ERR_CASE_NOT_FOUND`".

    Design: Corner/entities/get_case_nonexistent_returns_not_found
    """
    res = api.get_case(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_CASE_NOT_FOUND", expected_status=404)


def test_reopen_project_open_twice_returns_invalid_state(api):
    """PRD §3.1: "A `SurveyAdmin` opens the project for field work, moving it from
    `PLANNING` to `IN_FIELD`; opening a project that is not in `PLANNING` fails
    with `ERR_PROJECT_INVALID_STATE`."

    Design: Corner/state_machines/reopen_project_open_twice_returns_invalid_state
    """
    proj = create_open_project()
    res = api.open_project(proj["id"], ADMIN)
    validate_error(res, "ERR_PROJECT_INVALID_STATE", expected_status=409)


def test_created_case_starts_unassigned(api):
    """PRD §3.2: "On creation the case starts in `UNASSIGNED`, the area's
    `total_case_count` increments by one, its `pending_case_count` increments by
    one, and the area's coverage rates are recomputed."
    PRD §3.2: "A case additionally carries `assigned_enumerator_id`, which holds
    the enumerator id of its current active assignment or null when none is active,
    and `attempt_count`, the number of its LOGGED (non-cancelled) attempts."

    Design: Corner/state_machines/created_case_starts_unassigned
    """
    proj = create_project()
    area = create_draft_area(proj["id"])
    res = api.create_case(area["id"], {"address": "A St", "respondent_language": "EN"}, ADMIN)
    case = validate_success(res, 201)
    assert case["status"] == "UNASSIGNED"
    assert case["attempt_count"] == 0
    assert case["assigned_enumerator_id"] is None
    assert_case(case)


def test_unfreeze_area_returns_to_in_field(api):
    """PRD §3.2: "An administrator may freeze an `IN_FIELD` area — optionally
    supplying a `reason` — moving it to `FROZEN`, and may later unfreeze it back
    to `IN_FIELD`; freezing a non-`IN_FIELD` area or unfreezing a non-`FROZEN`
    area fails with `ERR_AREA_INVALID_STATE`."

    Design: Corner/state_machines/unfreeze_area_returns_to_in_field
    """
    proj = create_open_project()
    area = create_open_area(proj["id"])
    get_success_data(api.freeze_area(area["id"], ADMIN))
    res = api.unfreeze_area(area["id"], ADMIN)
    updated = validate_success(res, 200)
    assert updated["status"] == "IN_FIELD"


def test_list_cases_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_cases_returns_paginated_envelope
    """
    proj = create_project()
    area = create_draft_area(proj["id"])
    add_case(area["id"], address="1 A St")
    add_case(area["id"], address="2 A St")
    data, meta = validate_paginated(api.list_cases(area["id"], ADMIN))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_enumerator_cannot_create_project(api):
    """PRD §2.1: "When the headers are valid but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/enumerator_cannot_create_project
    """
    res = api.create_project(create_project_payload(name="Wave AG"), ENUM)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_field_supervisor_cannot_create_area(api):
    """PRD §2.1: "When the headers are valid but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/field_supervisor_cannot_create_area
    """
    proj = create_project()
    res = api.create_area(proj["id"], create_area_payload(), SUPERVISOR)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
