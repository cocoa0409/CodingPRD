"""Permit lifecycle, public notices, and the issuance gates.

Covers the permit revision cycle, the notice-closed / invalid-state precedence
pair, and the public-notice validation corners.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    register_facility, setup_facility_with_source, create_permit,
    setup_permit_in_public_notice, setup_issued_permit,
    make_facility_operator_headers, TEST_USERS, api_client,
    create_public_notice_payload,
)

REVIEWER = TEST_USERS["permit_reviewer_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _permit_by_rule_facility(name):
    facility, source = setup_facility_with_source(
        name, max_hourly_rate_lbs=10, operating_hours_per_year=8760, permit_limit_ppm=50)
    return facility


# ─── non_linear_state_machine / permit_revision_cycle_returns_to_draft ───

def test_permit_returns_to_draft_on_revision(api):
    """PRD §3.3: "From UNDER_REVIEW the reviewer may return the application for
    revision, moving it back UNDER_REVIEW → DRAFT (the revision loop)".

    Design: Difficulty/non_linear_state_machine/permit_revision_cycle_returns_to_draft
    """
    facility = _permit_by_rule_facility("Delta Rev Co")
    op = make_facility_operator_headers(facility["id"])
    permit = create_permit(facility["id"], "PERMIT_BY_RULE")
    validate_success(api.submit_permit(permit["id"], op), 200)
    validate_success(api.begin_review_permit(permit["id"], REVIEWER), 200)
    p = validate_success(api.return_permit_for_revision(permit["id"], REVIEWER), 200)
    assert p["status"] == "DRAFT"


def test_permit_resubmits_after_revision_cycle(api):
    """PRD §3.3: "The operator submits the draft ... Submission moves the permit
    DRAFT → SUBMITTED."

    Design: Difficulty/non_linear_state_machine/permit_revision_cycle_returns_to_draft
    """
    facility = _permit_by_rule_facility("Delta Cycle Co")
    op = make_facility_operator_headers(facility["id"])
    permit = create_permit(facility["id"], "PERMIT_BY_RULE")
    validate_success(api.submit_permit(permit["id"], op), 200)
    validate_success(api.begin_review_permit(permit["id"], REVIEWER), 200)
    validate_success(api.return_permit_for_revision(permit["id"], REVIEWER), 200)
    p = validate_success(api.submit_permit(permit["id"], op), 200)
    assert p["status"] == "SUBMITTED"


# ─── priority_pair_validation_conflict / permit_issue_invalid_state_beats_notice_not_closed ───

def test_issue_under_review_with_open_notice_reports_invalid_state(api):
    """PRD §2.10: "(5) the target resource is in a state that permits the requested
    transition, else ERR_INVALID_STATE (409); ... (7) the notice-closed
    precondition for permit issuance, else ERR_NOTICE_NOT_CLOSED (409)".
    PRD §3.3: "Issuing the permit moves it PUBLIC_NOTICE → ISSUED and is allowed
    only while the permit is PUBLIC_NOTICE".

    Design: Difficulty/priority_pair_validation_conflict/permit_issue_invalid_state_beats_notice_not_closed
    """
    facility = _permit_by_rule_facility("India Co")
    op = make_facility_operator_headers(facility["id"])
    permit = create_permit(facility["id"], "PERMIT_BY_RULE")
    validate_success(api.submit_permit(permit["id"], op), 200)
    validate_success(api.begin_review_permit(permit["id"], REVIEWER), 200)
    validate_success(api.create_public_notice(create_public_notice_payload(
        permit["id"], "2026-03-01T00:00:00Z", "2026-03-15T00:00:00Z"), REVIEWER), 201)
    res = api.issue_permit(permit["id"], REVIEWER)
    validate_error(res, "ERR_INVALID_STATE")


def test_issue_from_submitted_reports_invalid_state(api):
    """PRD §3.3: "Issuing the permit moves it PUBLIC_NOTICE → ISSUED and is allowed
    only while the permit is PUBLIC_NOTICE".

    Design: Difficulty/priority_pair_validation_conflict/permit_issue_invalid_state_beats_notice_not_closed
    """
    facility = _permit_by_rule_facility("India Sub Co")
    op = make_facility_operator_headers(facility["id"])
    permit = create_permit(facility["id"], "PERMIT_BY_RULE")
    validate_success(api.submit_permit(permit["id"], op), 200)
    res = api.issue_permit(permit["id"], REVIEWER)
    validate_error(res, "ERR_INVALID_STATE")


# ─── cross_entity_state_dependency / permit_issue_requires_public_notice_closed ───

def test_issue_blocked_while_notice_open(api):
    """PRD §3.3: "Issuing the permit moves it PUBLIC_NOTICE → ISSUED and is allowed
    only while the permit is PUBLIC_NOTICE and only when the linked public notice's
    status is CLOSED; issuing against a notice that is not yet closed is rejected
    with ERR_NOTICE_NOT_CLOSED."

    Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_public_notice_closed
    """
    facility = _permit_by_rule_facility("Lima Co")
    permit, notice = setup_permit_in_public_notice(facility["id"], "PERMIT_BY_RULE")
    res = api.issue_permit(permit["id"], REVIEWER)
    validate_error(res, "ERR_NOTICE_NOT_CLOSED")


def test_issue_succeeds_once_notice_closed(api):
    """PRD §3.3: "After the window has elapsed, the PermitReviewer closes the
    notice, moving its status from OPEN to CLOSED, which is the precondition that
    unlocks issuance." PRD §3.3: "Issuance sets issued_at to the current logical
    clock".

    Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_public_notice_closed
    """
    facility = _permit_by_rule_facility("Lima Closed Co")
    permit, notice = setup_issued_permit(facility["id"], "PERMIT_BY_RULE")
    assert permit["status"] == "ISSUED"
    assert permit["issued_at"] is not None


# ─── state_machines corner ───

def test_permit_full_issue_happy_path(api):
    """PRD §3.3: "Issuing the permit moves it PUBLIC_NOTICE → ISSUED ... Issuance
    sets issued_at to the current logical clock".

    Design: Corner/state_machines/permit_full_issue_happy_path
    """
    facility = _permit_by_rule_facility("Zulu Co")
    permit, notice = setup_issued_permit(facility["id"], "PERMIT_BY_RULE")
    assert permit["status"] == "ISSUED"
    assert permit["issued_at"] is not None


def test_permit_renewal_cycle_increments_count(api):
    """PRD §3.3: "the FacilityOperator starts a renewal, moving it ISSUED →
    RENEWAL_PENDING, and a PermitReviewer completes it, moving it RENEWAL_PENDING →
    ISSUED, incrementing renewal_count by one and refreshing issued_at."

    Design: Corner/state_machines/permit_renewal_cycle_increments_count
    """
    facility = _permit_by_rule_facility("Charlie2 Co")
    op = make_facility_operator_headers(facility["id"])
    permit, notice = setup_issued_permit(facility["id"], "PERMIT_BY_RULE")
    validate_success(api.start_renewal_permit(permit["id"], op), 200)
    p = validate_success(api.complete_renewal_permit(permit["id"], REVIEWER), 200)
    assert p["status"] == "ISSUED"
    assert p["renewal_count"] == 1


# ─── validations corner (permits & public notices) ───

def test_permit_track_mismatch_on_submit(api):
    """PRD §3.3: "submitting a TITLE_V permit is permitted only when the facility's
    track is TITLE_V; a mismatch is rejected with ERR_PERMIT_TRACK_MISMATCH."

    Design: Corner/validations/permit_track_mismatch_returns_error
    """
    facility = _permit_by_rule_facility("India2 Co")
    op = make_facility_operator_headers(facility["id"])
    permit = create_permit(facility["id"], "TITLE_V")
    res = api.submit_permit(permit["id"], op)
    validate_error(res, "ERR_PERMIT_TRACK_MISMATCH")


def test_notice_window_overlap_rejected(api):
    """PRD §3.3: "The proposed comment window must not overlap any other notice on
    permits of the same facility, treating the windows as closed intervals; an
    overlap is rejected with ERR_NOTICE_WINDOW_OVERLAP".

    Design: Corner/validations/notice_window_overlap_returns_error
    """
    facility = register_facility(name="Hotel2 Co")
    permit = create_permit(facility["id"], "PERMIT_BY_RULE")
    validate_success(api.create_public_notice(create_public_notice_payload(
        permit["id"], "2026-03-01T00:00:00Z", "2026-03-15T00:00:00Z"), REVIEWER), 201)
    res = api.create_public_notice(create_public_notice_payload(
        permit["id"], "2026-03-10T00:00:00Z", "2026-03-20T00:00:00Z"), REVIEWER)
    validate_error(res, "ERR_NOTICE_WINDOW_OVERLAP")


def test_notice_invalid_interval_rejected(api):
    """PRD §3.3: "a window whose comment_close_at is not strictly after its
    comment_open_at is rejected with ERR_INVALID_INTERVAL."

    Design: Corner/validations/notice_invalid_interval_returns_error
    """
    facility = register_facility(name="Juliet2 Co")
    permit = create_permit(facility["id"], "PERMIT_BY_RULE")
    res = api.create_public_notice(create_public_notice_payload(
        permit["id"], "2026-03-15T00:00:00Z", "2026-03-01T00:00:00Z"), REVIEWER)
    validate_error(res, "ERR_INVALID_INTERVAL")


def test_comment_after_window_close_rejected(api):
    """PRD §3.3: "a public comment supplies its comment_text and increments the
    notice's comment_count by one, but is accepted only while the notice's status
    is OPEN and the logical clock is strictly before comment_close_at; otherwise it
    is rejected with ERR_COMMENT_WINDOW_CLOSED."

    Design: Corner/validations/comment_after_window_close_returns_error
    """
    facility = register_facility(name="Mike2 Co")
    permit = create_permit(facility["id"], "PERMIT_BY_RULE")
    notice = validate_success(api.create_public_notice(create_public_notice_payload(
        permit["id"], "2026-03-01T00:00:00Z", "2026-03-05T00:00:00Z"), REVIEWER), 201)
    validate_success(api.set_clock("2026-03-10T00:00:00Z", REVIEWER), 200)
    res = api.comment_public_notice(notice["id"], {"comment_text": "too late"}, ANON)
    validate_error(res, "ERR_COMMENT_WINDOW_CLOSED")
