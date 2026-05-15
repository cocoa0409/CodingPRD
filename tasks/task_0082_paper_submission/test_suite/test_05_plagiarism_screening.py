"""Plagiarism screening boundary and pass/fail semantics (PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    PLAGIARISM_THRESHOLD,
    assert_plagiarism_check,
    plagiarism_result_event_payload,
    register_author,
    setup_submitted_manuscript,
    validate_success,
)


def test_plagiarism_below_threshold_passes(api, platform_admin_headers):
    """PRD §3.3: "when it is strictly less than 25.0, the result is PASS."
    """
    base = setup_submitted_manuscript()
    # Re-ingest a plagiarism event with a fresh value just below threshold.
    res = api.plagiarism_result_event(
        plagiarism_result_event_payload(
            manuscript_id=base["manuscript"]["id"],
            similarity_percent=24.9,
        ),
        platform_admin_headers,
    )
    check = validate_success(res, expected_status=200)
    assert_plagiarism_check(check)
    assert check["result"] == "PASS"


def test_plagiarism_exactly_at_threshold_fails(api, platform_admin_headers):
    """PRD §3.3: "when similarity_percent is at least 25.0, the result is
    FAIL ... The boundary is inclusive on the FAIL side, so a similarity
    of exactly 25.0 fails."
    """
    base = setup_submitted_manuscript()
    res = api.plagiarism_result_event(
        plagiarism_result_event_payload(
            manuscript_id=base["manuscript"]["id"],
            similarity_percent=25.0,
        ),
        platform_admin_headers,
    )
    check = validate_success(res, expected_status=200)
    assert check["result"] == "FAIL"
    assert check["similarity_percent"] == 25.0


def test_plagiarism_above_threshold_fails(api, platform_admin_headers):
    """PRD §3.3: "when similarity_percent is at least 25.0, the result is
    FAIL ..."
    """
    base = setup_submitted_manuscript()
    res = api.plagiarism_result_event(
        plagiarism_result_event_payload(
            manuscript_id=base["manuscript"]["id"],
            similarity_percent=99.9,
        ),
        platform_admin_headers,
    )
    check = validate_success(res, expected_status=200)
    assert check["result"] == "FAIL"


def test_plagiarism_records_revision_round(api, platform_admin_headers):
    """PRD §3.3: "The system creates a PlagiarismCheck row pinned to the
    manuscript's current revision_round ..."
    """
    base = setup_submitted_manuscript()
    res = api.plagiarism_result_event(
        plagiarism_result_event_payload(
            manuscript_id=base["manuscript"]["id"],
            similarity_percent=10.0,
        ),
        platform_admin_headers,
    )
    check = validate_success(res, expected_status=200)
    assert check["revision_round"] == base["manuscript"]["revision_round"]


def test_plagiarism_mirrors_similarity_to_manuscript(api, platform_admin_headers):
    """PRD §3.3: "The latest plagiarism_similarity is mirrored onto the
    parent Manuscript's plagiarism_similarity field as a convenience for
    editor dashboards."
    """
    base = setup_submitted_manuscript()
    res = api.plagiarism_result_event(
        plagiarism_result_event_payload(
            manuscript_id=base["manuscript"]["id"],
            similarity_percent=12.5,
        ),
        platform_admin_headers,
    )
    validate_success(res, expected_status=200)
    refetch = api.get_manuscript(
        base["manuscript"]["id"], platform_admin_headers,
    )
    manuscript = validate_success(refetch, expected_status=200)
    assert manuscript["plagiarism_similarity"] == 12.5
