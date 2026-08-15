"""Program review and corrective action tests (PRD §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_program_review, create_review_in_findings_issued,
    create_review_in_corrective_action, create_closed_review,
    create_corrective_action_payload,
    ApiErrorId, assert_program_review, assert_corrective_action, TEST_USERS,
)

REVIEWER = TEST_USERS["reviewer_headers"]
COORD = TEST_USERS["coordinator_headers"]


def test_program_review_closed_interval_overlap(api):
    """PRD §3.9: "The interval must not overlap any other review whose status
    is not `CLOSED`, and a shared boundary year counts as overlap — a review
    covering 2023–2024 and another covering 2024–2025 cannot coexist while
    either is open; violations are rejected with `ERR_REVIEW_SCOPE_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/program_review_closed_interval_overlap
    """
    create_program_review(scope_year_start=2023, scope_year_end=2025)

    # Shared boundary year 2025 counts as overlap under closed-interval semantics.
    res = api.create_program_review(
        {"scope_year_start": 2025, "scope_year_end": 2026}, REVIEWER
    )
    validate_error(res, ApiErrorId.ERR_REVIEW_SCOPE_OVERLAP.value, expected_status=409)

    # Disjoint interval [2026, 2027] is accepted.
    review = validate_success(api.create_program_review(
        {"scope_year_start": 2026, "scope_year_end": 2027}, REVIEWER
    ), 201)
    assert_program_review(review)
    assert review["status"] == "OPENED"


def test_program_review_interior_overlap_rejected(api):
    """PRD §3.9: "The interval must not overlap any other review whose status
    is not `CLOSED`, and a shared boundary year counts as overlap — a review
    covering 2023–2024 and another covering 2024–2025 cannot coexist while
    either is open; violations are rejected with `ERR_REVIEW_SCOPE_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/program_review_closed_interval_overlap
    """
    create_program_review(scope_year_start=2023, scope_year_end=2025)

    # [2024, 2024] lies entirely inside [2023, 2025].
    res = api.create_program_review(
        {"scope_year_start": 2024, "scope_year_end": 2024}, REVIEWER
    )
    validate_error(res, ApiErrorId.ERR_REVIEW_SCOPE_OVERLAP.value, expected_status=409)


def test_corrective_action_reject_cycles_to_open(api):
    """PRD §3.9: "Rejection moves `SUBMITTED → OPEN`, increments the action's
    `rejection_count` by one, stores the reviewer's `verification_note`, and
    leaves `open_action_count` unchanged on net, since both `SUBMITTED` and
    `OPEN` count as open."

    Design: Corner/state_machines/corrective_action_reject_cycles_to_open
    """
    review, action = create_review_in_corrective_action(
        scope_year_start=2024, scope_year_end=2025,
        action_overrides={
            "finding_code": "ASR-100", "severity": "MEDIUM",
            "description": "Late ASR", "due_date": "2026-09-15",
        },
    )
    submitted = validate_success(api.submit_corrective_action(
        action["id"], {"resolution_summary": "Procedures updated"}, COORD
    ), 200)
    assert submitted["status"] == "SUBMITTED"

    rejected = validate_success(api.reject_corrective_action(
        action["id"], {"verification_note": "Insufficient evidence"}, REVIEWER
    ), 200)
    assert rejected["status"] == "OPEN", "Rejection cycles the action back to OPEN"
    assert rejected["rejection_count"] == 1
    assert rejected["verification_note"] == "Insufficient evidence"


def test_review_verification_loop_and_close(api):
    """PRD §3.9: "Verification moves `SUBMITTED → VERIFIED` — the action's
    terminal state — decrements the review's `open_action_count` by one, and
    when that count reaches zero while the review is `CORRECTIVE_ACTION`, the
    review auto-advances to `UNDER_VERIFICATION`, recomputing `penalty_score`
    and `escalated` at the transition."
    PRD §3.9: "From `UNDER_VERIFICATION` the reviewer may instead return the
    review to `CORRECTIVE_ACTION` via return-for-correction, optionally
    recording a `note`, forming a remediation loop."
    PRD §3.9: "advancing from `CORRECTIVE_ACTION` or from `UNDER_VERIFICATION`
    requires `open_action_count` to be zero."

    Design: Corner/state_machines/review_verification_loop_and_close
    """
    review, action = create_review_in_corrective_action(
        scope_year_start=2022, scope_year_end=2023,
        action_overrides={
            "finding_code": "LOG-200", "severity": "LOW",
            "description": "Log gap", "due_date": "2026-09-01",
        },
    )
    validate_success(api.submit_corrective_action(
        action["id"], {"resolution_summary": "Fixed"}, COORD
    ), 200)
    validate_success(api.verify_corrective_action(action["id"], REVIEWER), 200)

    review_after_verify = validate_success(
        api.get_program_review(review["id"], REVIEWER), 200
    )
    assert review_after_verify["status"] == "UNDER_VERIFICATION", (
        "Verifying the last open action auto-advances the review"
    )

    returned = validate_success(api.return_review_for_correction(
        review["id"], {"note": "Spot-check failed"}, REVIEWER
    ), 200)
    assert returned["status"] == "CORRECTIVE_ACTION"

    # With zero open actions the reviewer advances back to UNDER_VERIFICATION
    # and then to CLOSED.
    review = validate_success(api.advance_review(review["id"], REVIEWER), 200)
    assert review["status"] == "UNDER_VERIFICATION"
    review = validate_success(api.advance_review(review["id"], REVIEWER), 200)
    assert review["status"] == "CLOSED"


def test_penalty_score_repeat_finding_doubles_and_escalates(api):
    """PRD §3.9: "`is_repeat_finding` is true when any corrective action with
    the same `finding_code` exists on any `CLOSED` review. `weight` is a base
    of 10 for `LOW`, 25 for `MEDIUM`, or 50 for `HIGH`, doubled when
    `is_repeat_finding` is true. Creating an action increments the review's
    `open_action_count` by one and recomputes `penalty_score`, which is the sum
    of `weight` over all of the review's actions regardless of action status;
    `escalated` is true when `penalty_score` is at least 100 — exactly 100
    escalates."

    Design: Corner/calculations/penalty_score_repeat_finding_doubles_and_escalates
    """
    # R1 closes with a HIGH action carrying finding_code LOG-001.
    create_closed_review(
        scope_year_start=2022, scope_year_end=2023,
        action_overrides={
            "finding_code": "LOG-001", "severity": "HIGH",
            "description": "Log not maintained", "due_date": "2026-09-01",
        },
    )

    r2 = create_review_in_findings_issued(scope_year_start=2024, scope_year_end=2025)
    repeat_action = validate_success(api.create_corrective_action(
        r2["id"],
        {"finding_code": "LOG-001", "severity": "HIGH",
         "description": "Repeat log finding", "due_date": "2026-10-01"},
        REVIEWER,
    ), 201)
    assert repeat_action["is_repeat_finding"] is True
    assert repeat_action["weight"] == 100, "HIGH base 50 doubled on a repeat finding"

    validate_success(api.create_corrective_action(
        r2["id"],
        {"finding_code": "ASR-002", "severity": "LOW",
         "description": "Minor ASR gap", "due_date": "2026-10-01"},
        REVIEWER,
    ), 201)

    r2_after = validate_success(api.get_program_review(r2["id"], REVIEWER), 200)
    assert r2_after["penalty_score"] == 110, "100 (repeat HIGH) + 10 (LOW)"
    assert r2_after["escalated"] is True, "110 >= 100 escalation threshold (inclusive)"


def test_advance_review_without_actions_rejected(api):
    """PRD §3.9: "Advancing from `FINDINGS_ISSUED` requires at least one
    corrective action to exist; advancing from `CORRECTIVE_ACTION` or from
    `UNDER_VERIFICATION` requires `open_action_count` to be zero. A gated
    advance that fails is rejected with `ERR_UNRESOLVED_ACTIONS` (HTTP 422)."

    Design: Corner/validations/advance_review_without_actions_rejected
    """
    review = create_review_in_findings_issued(scope_year_start=2021, scope_year_end=2022)

    res = api.advance_review(review["id"], REVIEWER)
    validate_error(res, ApiErrorId.ERR_UNRESOLVED_ACTIONS.value, expected_status=422)

    after = validate_success(api.get_program_review(review["id"], REVIEWER), 200)
    assert after["status"] == "FINDINGS_ISSUED"


def test_coordinator_cannot_advance_review(api):
    """PRD §2.1: "A request whose role is not listed for the endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the program-review advance endpoint lists only `FederalReviewer`.

    Design: Corner/rbac/coordinator_cannot_advance_review
    """
    review = create_program_review(scope_year_start=2020, scope_year_end=2020)

    res = api.advance_review(review["id"], COORD)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
