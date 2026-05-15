"""Section editor assignment and desk rejection (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    assign_section_editor_payload,
    desk_reject_payload,
    make_editor_in_chief_headers,
    make_section_editor_headers,
    plagiarism_result_event_payload,
    register_editor,
    setup_submitted_manuscript,
    validate_error,
    validate_success,
)


def test_assign_section_editor_writes_field(api):
    """PRD §3.4: "The editor-in-chief assigns a section editor to a
    submitted manuscript by supplying section_editor_id on the assignment
    request; the field is written to Manuscript.section_editor_id."
    """
    base = setup_submitted_manuscript()
    eic = register_editor("EDITOR_IN_CHIEF")
    section_editor = register_editor("SECTION_EDITOR")

    res = api.assign_section_editor(
        base["manuscript"]["id"],
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        make_editor_in_chief_headers(eic["id"]),
    )
    updated = validate_success(res, expected_status=200)
    assert updated["section_editor_id"] == section_editor["id"]


def test_desk_reject_with_plagiarism_fail_succeeds(api, platform_admin_headers):
    """PRD §3.4: "either the latest PlagiarismCheck.result must be FAIL
    or the request body must supply a non-empty reason string."
    Combined with §3.3: "when similarity_percent is at least 25.0, the
    result is FAIL".
    """
    base = setup_submitted_manuscript(plagiarism_similarity=5.0)
    eic = register_editor("EDITOR_IN_CHIEF")
    section_editor = register_editor("SECTION_EDITOR")
    res = api.assign_section_editor(
        base["manuscript"]["id"],
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        make_editor_in_chief_headers(eic["id"]),
    )
    validate_success(res, expected_status=200)
    # Inject a FAIL plagiarism event so desk-reject can proceed without
    # a reason string.
    res = api.plagiarism_result_event(
        plagiarism_result_event_payload(
            manuscript_id=base["manuscript"]["id"],
            similarity_percent=99.0,
        ),
        platform_admin_headers,
    )
    validate_success(res, expected_status=200)

    rej_res = api.desk_reject_manuscript(
        base["manuscript"]["id"],
        make_section_editor_headers(section_editor["id"]),
        desk_reject_payload(),  # no reason
    )
    rejected = validate_success(rej_res, expected_status=200)
    assert rejected["status"] == "DESK_REJECTED"


def test_desk_reject_with_reason_string_succeeds(api):
    """PRD §3.4: "or the request body must supply a non-empty reason string."
    """
    base = setup_submitted_manuscript(plagiarism_similarity=5.0)
    eic = register_editor("EDITOR_IN_CHIEF")
    section_editor = register_editor("SECTION_EDITOR")
    res = api.assign_section_editor(
        base["manuscript"]["id"],
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        make_editor_in_chief_headers(eic["id"]),
    )
    validate_success(res, expected_status=200)

    rej_res = api.desk_reject_manuscript(
        base["manuscript"]["id"],
        make_section_editor_headers(section_editor["id"]),
        desk_reject_payload(reason="scope mismatch"),
    )
    rejected = validate_success(rej_res, expected_status=200)
    assert rejected["status"] == "DESK_REJECTED"


def test_desk_reject_with_pass_and_no_reason_returns_error(api):
    """PRD §3.4: "A desk-reject call that meets neither condition is
    rejected with ERR_DESK_REJECT_REASON_REQUIRED."
    Combined with §3.3 PASS rule.
    """
    base = setup_submitted_manuscript(plagiarism_similarity=5.0)
    eic = register_editor("EDITOR_IN_CHIEF")
    section_editor = register_editor("SECTION_EDITOR")
    res = api.assign_section_editor(
        base["manuscript"]["id"],
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        make_editor_in_chief_headers(eic["id"]),
    )
    validate_success(res, expected_status=200)
    rej_res = api.desk_reject_manuscript(
        base["manuscript"]["id"],
        make_section_editor_headers(section_editor["id"]),
        desk_reject_payload(),  # no reason, plagiarism PASS
    )
    validate_error(rej_res, ApiErrorId.ERR_DESK_REJECT_REASON_REQUIRED.value)


def test_assign_section_editor_requires_editor_in_chief(api, section_editor_fallback_headers):
    """PRD §4: "POST /manuscripts/{id}/assign-section-editor ... Authorized
    Role(s): EditorInChief."
    PRD §2.1: "Requests whose role is not authorized for the requested
    endpoint are rejected with ERR_FORBIDDEN (HTTP 403)."
    """
    base = setup_submitted_manuscript()
    section_editor = register_editor("SECTION_EDITOR")
    res = api.assign_section_editor(
        base["manuscript"]["id"],
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        section_editor_fallback_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
