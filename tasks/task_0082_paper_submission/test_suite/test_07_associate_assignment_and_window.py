"""Associate-editor assignment and the 5-day non-overlap window (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    assign_associate_payload,
    assign_section_editor_payload,
    make_editor_in_chief_headers,
    make_section_editor_headers,
    register_editor,
    setup_associate_editor_with_open_window,
    setup_submitted_manuscript,
    validate_error,
    validate_success,
)


def test_assign_associate_topic_mismatch_rejected(api):
    """PRD §3.4: "The candidate must be an Editor row whose role is
    ASSOCIATE_EDITOR and whose topic_tags array contains the manuscript's
    topic_tag; a mismatch returns ERR_EDITOR_TOPIC_MISMATCH."
    """
    base = setup_submitted_manuscript(topic_tag="ml")
    eic = register_editor("EDITOR_IN_CHIEF")
    section_editor = register_editor("SECTION_EDITOR", topic_tags=["ml"])
    # Associate editor's topic_tags do NOT include "ml".
    bad_associate = register_editor("ASSOCIATE_EDITOR", topic_tags=["robotics"])

    res = api.assign_section_editor(
        base["manuscript"]["id"],
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        make_editor_in_chief_headers(eic["id"]),
    )
    validate_success(res, expected_status=200)

    res = api.assign_associate(
        base["manuscript"]["id"],
        assign_associate_payload(associate_editor_id=bad_associate["id"]),
        make_section_editor_headers(section_editor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_EDITOR_TOPIC_MISMATCH.value)


def test_assign_associate_success_writes_window(api):
    """PRD §3.4: "A successful assignment writes associate_editor_id,
    stamps associate_assigned_at to the server clock, sets
    associate_window_end_at to five days after associate_assigned_at,
    and advances the manuscript from SUBMITTED to UNDER_REVIEW."
    """
    base = setup_submitted_manuscript(topic_tag="ml")
    eic = register_editor("EDITOR_IN_CHIEF")
    section_editor = register_editor("SECTION_EDITOR", topic_tags=["ml"])
    associate = register_editor("ASSOCIATE_EDITOR", topic_tags=["ml"])

    res = api.assign_section_editor(
        base["manuscript"]["id"],
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        make_editor_in_chief_headers(eic["id"]),
    )
    validate_success(res, expected_status=200)

    res = api.assign_associate(
        base["manuscript"]["id"],
        assign_associate_payload(associate_editor_id=associate["id"]),
        make_section_editor_headers(section_editor["id"]),
    )
    manuscript = validate_success(res, expected_status=200)
    assert manuscript["status"] == "UNDER_REVIEW"
    assert manuscript["associate_editor_id"] == associate["id"]
    assert manuscript["associate_assigned_at"] is not None
    assert manuscript["associate_window_end_at"] is not None


def test_assign_associate_to_overlapping_window_rejected(api):
    """PRD §3.4: "the candidate associate editor must not already have an
    open assignment-acceptance window on a different manuscript. That
    window is defined as the five-day interval starting at
    associate_assigned_at and ending at associate_window_end_at; two
    manuscripts whose windows overlap on the same associate editor are
    rejected with ERR_EDITOR_WINDOW_OVERLAP."
    """
    state = setup_associate_editor_with_open_window(topic_tag="ml")
    res = api.assign_associate(
        state["manuscript_m2"]["id"],
        assign_associate_payload(
            associate_editor_id=state["associate_editor"]["id"]),
        make_section_editor_headers(state["section_editor_m2"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_EDITOR_WINDOW_OVERLAP.value)


def test_assign_associate_requires_section_editor_role(api, associate_editor_fallback_headers):
    """PRD §4: "POST /manuscripts/{id}/assign-associate ... Authorized
    Role(s): SectionEditor."
    PRD §2.1: "Requests whose role is not authorized for the requested
    endpoint are rejected with ERR_FORBIDDEN (HTTP 403)."
    """
    base = setup_submitted_manuscript()
    associate = register_editor("ASSOCIATE_EDITOR",
                                topic_tags=[base["manuscript"]["topic_tag"]])
    res = api.assign_associate(
        base["manuscript"]["id"],
        assign_associate_payload(associate_editor_id=associate["id"]),
        associate_editor_fallback_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
