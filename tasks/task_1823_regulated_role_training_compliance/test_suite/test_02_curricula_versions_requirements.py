"""Curriculum lifecycle, content versions, retention precedence, requirements."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_curriculum_version,
    add_requirement,
    create_active_curriculum,
    create_curriculum,
    create_regulator,
    create_role,
    get_success_data,
    list_completions,
    make_employee_headers,
    reject_completion,
    set_clock,
    setup_employee_with_assignment,
    submit_completion,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories

ADMIN = TEST_USERS["compliance_admin_headers"]


class TestVersionWindows:
    def test_adjacent_version_window_accepted(self, api):
        """PRD §3.1: "These are half-open windows: one version's `effective_from`
        may coincide with another's `effective_to`, but any true overlap between
        windows of the same curriculum is rejected with
        `ERR_VERSION_WINDOW_OVERLAP`."
        PRD §3.1: "a `null` `effective_to` means the version is open-ended"

        Design: Difficulty/resource_temporal_overlap/curriculum_version_half_open_adjacency
        """
        reg = create_regulator(code="REG-V8A", name="V8A Regulator")
        cur = create_curriculum(reg["id"], code="CUR-V8A", title="V8A Course")
        add_curriculum_version(
            cur["id"], version_no=1,
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
            content_uri="uri://v8a-1",
        )
        resp = api.create_curriculum_version(
            cur["id"],
            factories.create_version_payload(
                version_no=2, effective_from="2026-06-01T00:00:00Z",
                content_uri="uri://v8a-2",
            ),
            ADMIN,
        )
        v2 = validate_success(resp, 201)
        assert v2["version_no"] == 2
        assert v2.get("effective_to") is None, "omitted effective_to is open-ended (null)"

    def test_overlapping_version_window_rejected(self, api):
        """PRD §3.1: "These are half-open windows: one version's `effective_from`
        may coincide with another's `effective_to`, but any true overlap between
        windows of the same curriculum is rejected with
        `ERR_VERSION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/curriculum_version_half_open_adjacency
        """
        reg = create_regulator(code="REG-V8A", name="V8A Regulator")
        cur = create_curriculum(reg["id"], code="CUR-V8A", title="V8A Course")
        add_curriculum_version(
            cur["id"], version_no=1,
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
            content_uri="uri://v8a-1",
        )
        add_curriculum_version(
            cur["id"], version_no=2, effective_from="2026-06-01T00:00:00Z",
            content_uri="uri://v8a-2",
        )
        resp = api.create_curriculum_version(
            cur["id"],
            factories.create_version_payload(
                version_no=3, effective_from="2026-05-15T00:00:00Z",
                content_uri="uri://v8a-3",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_WINDOW_OVERLAP.value)

        lst = api.list_curriculum_versions(cur["id"], ADMIN)
        _, meta = validate_paginated(lst)
        assert meta["total_count"] == 2, "rejected version must not persist"


def test_duplicate_version_number_rejected_despite_disjoint_window(api):
    """PRD §3.1: "Each version carries a `version_no` — a positive integer
    unique per curriculum, with a reused number rejected as
    `ERR_VERSION_NUMBER_CONFLICT`"

    Design: Corner/validations/duplicate_version_number_rejected
    """
    reg = create_regulator(code="REG-VNC", name="VNC Regulator")
    cur = create_curriculum(reg["id"], code="CUR-VNC", title="VNC Course")
    add_curriculum_version(
        cur["id"], version_no=1,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
        content_uri="uri://vnc-1",
    )
    resp = api.create_curriculum_version(
        cur["id"],
        factories.create_version_payload(
            version_no=1, effective_from="2026-07-01T00:00:00Z",
            content_uri="uri://vnc-1b",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VERSION_NUMBER_CONFLICT.value)


def test_activation_without_effective_version_rejected(api):
    """PRD §3.1: "Moving a curriculum from `DRAFT` to `ACTIVE` requires, first,
    that at least one of its versions is currently effective — `effective_from`
    at or before the present instant, with `effective_to` either absent or
    strictly after it — or the transition fails with `ERR_NO_EFFECTIVE_VERSION`;
    and, second, that the owning regulator is `ACTIVE`, or the transition fails
    with `ERR_REGULATOR_RETIRED`."

    Design: Corner/errors/curriculum_activate_without_effective_version_rejected
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-NEV", name="NEV Regulator")
    cur = create_curriculum(reg["id"], code="CUR-NEV", title="NEV Course")
    add_curriculum_version(
        cur["id"], version_no=1, effective_from="2027-01-01T00:00:00Z",
        content_uri="uri://nev-future",
    )
    resp = api.update_curriculum(
        cur["id"],
        {"status": "ACTIVE", "expected_curriculum_version": cur["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_VERSION.value)

    current = get_success_data(api.get_curriculum(cur["id"], ADMIN), 200)
    assert current["status"] == "DRAFT", "failed activation must leave status unchanged"


def test_retired_regulator_rejects_new_curriculum(api):
    """PRD §3.1: "Retiring a regulator moves `status` from `ACTIVE` to `RETIRED`;
    existing curricula and assignments are entirely unaffected, but creating a
    new curriculum under a retired regulator is rejected with
    `ERR_REGULATOR_RETIRED`, and activating a curriculum under one meets the
    same refusal."

    Design: Corner/errors/retired_regulator_rejects_new_curriculum
    """
    reg = create_regulator(code="REG-RET2", name="RET2 Regulator")
    resp = api.update_regulator(
        reg["id"], {"status": "RETIRED", "expected_regulator_version": reg["version"]},
        ADMIN,
    )
    retired = validate_success(resp, 200)
    assert retired["status"] == "RETIRED"

    resp = api.create_curriculum(
        factories.create_curriculum_payload(reg["id"], code="CUR-RET2", title="RET2 Course"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REGULATOR_RETIRED.value)


def test_retention_precedence_override_then_regulator_fallback(api):
    """PRD §3.1: "A curriculum may carry a `recordkeeping_years_override` between
    1 and 25; the field is nullable, and writing JSON `null` to it clears the
    override. The curriculum's computed `effective_recordkeeping_years` is the
    override when one is set and the owning regulator's `recordkeeping_years`
    otherwise — the curriculum override beats the regulator default, and the
    regulator default applies whenever the override is absent."

    Design: Corner/calculations/retention_precedence_override_then_regulator_fallback
    """
    reg = create_regulator(code="REG-RET", name="RET Regulator", recordkeeping_years=7)
    cur = create_curriculum(
        reg["id"], code="CUR-RET", title="RET Course", recordkeeping_years_override=3,
    )
    fetched = get_success_data(api.get_curriculum(cur["id"], ADMIN), 200)
    assert fetched["effective_recordkeeping_years"] == 3, "override beats regulator default"

    cleared = api.update_curriculum(
        cur["id"],
        {"recordkeeping_years_override": None,
         "expected_curriculum_version": fetched["version"]},
        ADMIN,
    )
    updated = validate_success(cleared, 200)
    assert updated["recordkeeping_years_override"] is None
    assert updated["effective_recordkeeping_years"] == 7, "cleared override falls back to regulator"


def test_passing_score_change_applies_only_to_future_submissions(api):
    """PRD §3.1: "The passing threshold is evaluated at submission time using
    the curriculum's *current* `passing_score_pct`, and `validity_months` is
    read at accept time; updates to a curriculum's `passing_score_pct` therefore
    apply to future submissions only, never to records already submitted."
    PRD §3.4: "`passed`, true exactly when `score_pct` is at least the
    curriculum's passing threshold at that moment."

    Design: Corner/calculations/passing_score_change_applies_only_to_future_submissions
    """
    ctx = setup_employee_with_assignment("PSC", max_attempts=3)
    asg = ctx["assignment"]
    emp = ctx["employee"]

    c1 = submit_completion(asg["id"], emp["id"], score_pct=80)
    assert c1["passed"] is True, "80 >= 80 at submission time"
    reject_completion(c1["id"], review_note="please redo")

    current = get_success_data(api.get_curriculum(ctx["curriculum"]["id"], ADMIN), 200)
    resp = api.update_curriculum(
        ctx["curriculum"]["id"],
        {"passing_score_pct": 90, "expected_curriculum_version": current["version"]},
        ADMIN,
    )
    validate_success(resp, 200)

    resp = api.submit_completion(
        asg["id"], factories.submit_completion_payload(score_pct=85),
        make_employee_headers(emp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_PASSING.value)

    records, meta = list_completions(asg["id"])
    assert meta["total_count"] == 1, "rejected submission must not persist a record"
    assert records[0]["passed"] is True, "historical record's passed flag is immutable"


class TestRequirementCurriculumGate:
    def test_requirement_referencing_draft_curriculum_rejected(self, api):
        """PRD §3.2: "The referenced curriculum must be `ACTIVE`, or creation
        fails with `ERR_CURRICULUM_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/requirement_create_gated_by_curriculum_status
        """
        set_clock("2026-08-03T09:00:00Z")
        reg = create_regulator(code="REG-X7B", name="X7B Regulator")
        cur = create_curriculum(reg["id"], code="CUR-X7B", title="X7B Course")
        add_curriculum_version(cur["id"], version_no=1)
        role = create_role(code="R-X7B", name="X7B Role")

        resp = api.create_requirement(
            role["id"], factories.create_requirement_payload(cur["id"]), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CURRICULUM_NOT_ACTIVE.value)

    def test_rejected_requirement_is_not_persisted(self, api):
        """PRD §3.2: "The referenced curriculum must be `ACTIVE`, or creation
        fails with `ERR_CURRICULUM_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/requirement_create_gated_by_curriculum_status
        """
        set_clock("2026-08-03T09:00:00Z")
        reg = create_regulator(code="REG-X7B", name="X7B Regulator")
        cur = create_curriculum(reg["id"], code="CUR-X7B", title="X7B Course")
        add_curriculum_version(cur["id"], version_no=1)
        role = create_role(code="R-X7B", name="X7B Role")

        api.create_requirement(role["id"], factories.create_requirement_payload(cur["id"]), ADMIN)
        lst = api.list_role_requirements(role["id"], ADMIN)
        _, meta = validate_paginated(lst)
        assert meta["total_count"] == 0, "rejected requirement must not persist"


def test_duplicate_active_requirement_rejected_then_allowed_after_retire(api):
    """PRD §3.2: "At most one `ACTIVE` requirement may exist for a given
    role-and-curriculum pair; a second is rejected with
    `ERR_DUPLICATE_ACTIVE_REQUIREMENT`. A requirement is born `ACTIVE`."
    PRD §3.2: "Retiring a requirement — again only while `ACTIVE`, else
    `ERR_INVALID_STATE` — leaves existing assignments running untouched but
    excludes the requirement from all future sweeps, recurrence creations, and
    role-change assignment."

    Design: Corner/validations/duplicate_active_requirement_rejected_then_allowed_after_retire
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-DUP", name="DUP Regulator")
    cur = create_active_curriculum(reg["id"], code="CUR-DUP", title="DUP Course")
    role = create_role(code="R-DUP", name="DUP Role")

    rq1 = add_requirement(role["id"], cur["id"])
    resp = api.create_requirement(
        role["id"],
        factories.create_requirement_payload(
            cur["id"], recurrence="VALIDITY_CYCLE", due_in_days=60, criticality="HARD",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_REQUIREMENT.value)

    retired = get_success_data(api.retire_requirement(rq1["id"], ADMIN), 200)
    assert retired["status"] == "RETIRED"

    resp = api.create_requirement(
        role["id"],
        factories.create_requirement_payload(
            cur["id"], recurrence="VALIDITY_CYCLE", due_in_days=60, criticality="HARD",
        ),
        ADMIN,
    )
    rq2 = validate_success(resp, 201)
    assert rq2["status"] == "ACTIVE", "re-creation allowed once the prior is retired"
