"""Term creation, policy defaults, envelope shape, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    assert_workload_term,
    create_course_payload,
    create_term_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]


def test_term_create_missing_required_field(api):
    """PRD §2.8: "Missing required fields, type mismatches, invalid enum members,
    out-of-range scalars (for example `credits_released` exceeding the faculty
    member's contractual load, or `credits_released` not greater than zero), a
    section `end_minute` that is not strictly greater than its `start_minute`,
    minutes outside the range 0 through 1439, a negative `enrolled_count`, a grant
    `end_date` earlier than its `start_date`, or a term whose `census_date` precedes
    its `start_date` — these surface as `ERR_VALIDATION` or, for the section
    time-window failures specifically, `ERR_INVALID_TIME_RANGE`."

    Design: Corner/entities/c_term_create_missing_required_field
    """
    payload = {
        "term_code": "2026-FA",
        "title": "Fall 2026",
        "census_date": "2026-09-07",
        "comp_budget_cents": 2_000_000,
    }
    resp = api.create_term(payload, CHAIR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    rows, _meta = validate_paginated(api.list_terms(CHAIR))
    assert all(r.get("term_code") != "2026-FA" for r in rows), (
        "rejected create must not persist a WorkloadTerm"
    )


def test_term_defaults_applied(api):
    """PRD §3.1: "The term record also carries the department's workload policy as
    inline fields, all of which have defaults when omitted at creation:
    `base_teaching_credits` (default 12) names the department-standard full-time
    teaching load per term; the credit-equivalency multipliers `lecture_multiplier`
    (default 1.0), `lab_multiplier` (default 0.75), and `seminar_multiplier`
    (default 1.25) convert catalog credits into workload credits by course type;
    `online_premium_credits` (default 0.5) is a flat credit premium added for online
    sections; `large_class_threshold` (default 40) and `large_class_bonus_credits`
    (default 1.0) together grant a flat bonus when a section's enrollment reaches
    the threshold; `overload_comp_rate_cents` (default 150000, i.e., $1,500.00 per
    overload credit) prices extra compensation; `union_max_overload_credits`
    (default 6) caps overload for union-covered faculty; `reassignment_notice_days`
    (default 14) defines the late window for rescinds and cancellations;
    `late_cancel_stipend_cents` (default 100000, i.e., $1,000.00) is the
    per-assignment stipend for late cancellations; and `flat_release_rate_cents`
    (default 80000, i.e., $800.00 per released credit) prices administrative and
    sabbatical buyouts."
    PRD §3.1: "A term is always born in `DRAFT` status with `comp_budget_spent_cents`
    at 0."

    Design: Corner/entities/c_term_defaults_applied
    """
    resp = api.create_term(create_term_payload(), CHAIR)
    data = validate_success(resp, 201)
    assert_workload_term(data)
    assert data["lecture_multiplier"] == pytest.approx(1.0)
    assert data["lab_multiplier"] == pytest.approx(0.75)
    assert data["seminar_multiplier"] == pytest.approx(1.25)
    assert data["online_premium_credits"] == pytest.approx(0.5)
    assert data["large_class_threshold"] == 40
    assert data["large_class_bonus_credits"] == pytest.approx(1.0)
    assert data["overload_comp_rate_cents"] == 150_000
    assert data["union_max_overload_credits"] == pytest.approx(6)
    assert data["reassignment_notice_days"] == 14
    assert data["late_cancel_stipend_cents"] == 100_000
    assert data["flat_release_rate_cents"] == 80_000
    assert data["base_teaching_credits"] == pytest.approx(12)
    assert data["status"] == "DRAFT"
    assert data["comp_budget_spent_cents"] == 0


def test_term_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_term_not_found_returns_404
    """
    resp = api.get_term(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_FOUND, 404)


def test_term_initial_state_draft(api):
    """PRD §3.1: "A term is always born in `DRAFT` status with
    `comp_budget_spent_cents` at 0."
    PRD §2.4: "`version` (integer): a system-managed integer that increments by
    exactly 1 on every mutation of the resource."

    Design: Corner/state_machines/c_term_initial_state_draft
    """
    resp = api.create_term(create_term_payload(), CHAIR)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["comp_budget_spent_cents"] == 0


def test_term_invalid_transition_draft_to_published(api):
    """PRD §3.1: "From `LOCKED` — and only from `LOCKED` — the chair may publish the
    term, moving it to the terminal `PUBLISHED` state, at which point the schedule
    becomes read-only."
    PRD §3.1: "Any other term transition request — for example opening a term that
    is already `OPEN`, or publishing from `OPEN` — is rejected with
    `ERR_INVALID_TERM_STATE`."

    Design: Corner/state_machines/c_term_invalid_transition_draft_to_published
    """
    resp = api.create_term(create_term_payload(), CHAIR)
    term = validate_success(resp, 201)

    resp = api.transition_term(term["id"], {"to_state": "PUBLISHED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_TERM_STATE, 409)

    after = validate_success(api.get_term(term["id"], CHAIR))
    assert after["status"] == "DRAFT", "term must remain DRAFT after the rejected publish"


def test_term_publish_lockdown_terminal(api):
    """PRD §3.1: "From `LOCKED` — and only from `LOCKED` — the chair may publish the
    term, moving it to the terminal `PUBLISHED` state, at which point the schedule
    becomes read-only."
    PRD §3.1: "While the term remains in `DRAFT`, the chair may revise the policy —
    `title`, `census_date`, `base_teaching_credits`, `comp_budget_cents`, any of the
    equivalency multipliers and premiums, the overload rate and union cap, the
    notice window, the stipend, and the flat release rate — through a policy edit
    that must carry `expected_term_version` per §2.5."

    Design: Corner/state_machines/c_term_publish_lockdown_terminal
    """
    resp = api.create_term(create_term_payload(), CHAIR)
    term = validate_success(resp, 201)
    term = validate_success(api.transition_term(term["id"], {"to_state": "OPEN"}, CHAIR))
    term = validate_success(api.transition_term(term["id"], {"to_state": "LOCKED"}, CHAIR))
    published = validate_success(api.transition_term(term["id"], {"to_state": "PUBLISHED"}, CHAIR))
    assert published["status"] == "PUBLISHED"

    resp = api.transition_term(term["id"], {"to_state": "LOCKED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_TERM_STATE, 409)

    resp = api.patch_term(
        term["id"],
        {"expected_term_version": published["version"], "lab_multiplier": 0.5},
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TERM_STATE, 409)


def test_term_patch_stale_version_412(api):
    """PRD §2.5: "A policy edit on a workload term must carry `expected_term_version`,
    a non-optional field whose value must equal the term's current `version`. If
    another writer has advanced the term's version since the client last read it —
    for example, a fellow chair just committed a policy edit — the edit is rejected
    with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the term is
    stale."

    Design: Corner/cross_cutting_layers/c_term_patch_stale_version_412
    """
    resp = api.create_term(create_term_payload(), CHAIR)
    term = validate_success(resp, 201)
    assert term["version"] == 1

    resp = api.patch_term(
        term["id"], {"expected_term_version": 1, "lecture_multiplier": 1.1}, CHAIR
    )
    updated = validate_success(resp)
    assert updated["version"] == 2
    assert updated["lecture_multiplier"] == pytest.approx(1.1)

    resp = api.patch_term(
        term["id"], {"expected_term_version": 1, "lab_multiplier": 0.5}, CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    after = validate_success(api.get_term(term["id"], CHAIR))
    assert after["lab_multiplier"] == pytest.approx(0.75), (
        "rejected stale write must not apply"
    )
    assert after["lecture_multiplier"] == pytest.approx(1.1)


def test_response_envelope_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
    this standard envelope format in their JSON body" with `meta`, `response_type`,
    and `data`.
    PRD §2.3: "The `meta` object of any list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items to skip and defaults to 0."

    Design: Corner/endpoints/c_response_envelope_shape
    """
    resp = api.create_term(create_term_payload(), CHAIR)
    term = validate_success(resp, 201)

    body = api.get_term(term["id"], CHAIR).json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["data"]["id"] == term["id"]

    rows, meta = validate_paginated(api.list_terms(CHAIR))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1


def test_immediate_read_after_write(api):
    """PRD §2.4: "Any mutation of a resource — including automatic cascades that touch
    a resource without an explicit client call on it, such as a section demoting from
    `STAFFED` to `SCHEDULED`, an assignment being withdrawn by a faculty-leave
    cascade, or a term's `comp_budget_spent_cents` increasing when a stipend posts —
    updates that resource's `updated_at` and increments its `version`."

    Design: Corner/consistency_model/c_immediate_read_after_write
    """
    resp = api.create_course(
        create_course_payload(course_code="CS-301", base_credits=3), CHAIR
    )
    course = validate_success(resp, 201)

    got = validate_success(api.get_course(course["id"], CHAIR))
    assert got["course_code"] == "CS-301"
    assert got["base_credits"] == pytest.approx(3)
