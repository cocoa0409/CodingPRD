"""Inspection scheduling rules and completion scoring (weighted vs flat variants)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_inspection,
    create_inspection_payload,
    create_lab,
    setup_lab_with_completed_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_weighted_score_is_authoritative_for_outcome(api):
    """PRD §3.5: "`score_weighted` starts from 100 and deducts 20 per `MAJOR` finding
    and 5 per `MINOR` finding, while `score_flat` starts from 100 and deducts a flat
    10 per finding regardless of severity, so identical findings can yield a
    different flat score than weighted score (two `MAJOR` findings and one `MINOR`
    finding give a weighted 55 against a flat 70)."
    PRD §3.5: "The `outcome` is `PASS` when `score_weighted` is at least 70 — the
    boundary is inclusive, so a weighted score of exactly 70 passes — and `FAIL`
    otherwise"

    Design: Difficulty/dual_variant_calc/inspection_scoring_weighted_vs_flat
    """
    ctx = setup_lab_with_completed_inspection(
        [
            {"severity": "MAJOR", "description": "unlabeled waste"},
            {"severity": "MAJOR", "description": "blocked shower"},
            {"severity": "MINOR", "description": "missing signage"},
        ],
        name="Bio B",
        room="202",
        with_pi=False,
    )
    inspection = ctx["inspection"]
    assert inspection["status"] == "COMPLETED"
    assert inspection["score_weighted"] == 55, (
        f"weighted 100 - 40 - 5 = 55, got {inspection['score_weighted']}"
    )
    assert inspection["score_flat"] == 70, (
        f"flat 100 - 3*10 = 70, got {inspection['score_flat']}"
    )
    assert inspection["outcome"] == "FAIL", (
        "the weighted variant is authoritative: 55 < 70 -> FAIL despite flat 70"
    )


def test_completion_fields_null_until_completed(api):
    """PRD §3.5: "Until completion, `score_weighted`, `score_flat`, `outcome`,
    `completed_by_inspector_id`, and `completed_at` are all null."
    PRD §3.5: "Completion also stamps `completed_by_inspector_id` with the acting
    `X-User-ID`, records `completed_at` at the logical now"

    Design: Difficulty/dual_variant_calc/inspection_scoring_weighted_vs_flat
    """
    lab = create_lab(name="Bio B2", department="Biology", building="Hall B", room="202")
    inspection = create_inspection(lab["id"], inspector_id="insp-1")
    for field in ("score_weighted", "score_flat", "outcome",
                  "completed_by_inspector_id", "completed_at"):
        assert inspection[field] is None, f"{field} must be null before completion"

    completed = validate_success(
        api.complete_inspection(
            inspection["id"],
            {"findings": [
                {"severity": "MAJOR", "description": "unlabeled waste"},
                {"severity": "MAJOR", "description": "blocked shower"},
                {"severity": "MINOR", "description": "missing signage"},
            ]},
            TEST_USERS["inspector_headers"],
        ),
        200,
    )
    assert completed["score_weighted"] == 55
    assert completed["score_flat"] == 70
    assert completed["outcome"] == "FAIL"
    assert completed["completed_by_inspector_id"] == "insp-1"
    assert completed["completed_at"] is not None
    assert completed["completed_at"].startswith("2026-08-01T00:00:00"), (
        "completed_at records the logical now (startup default clock)"
    )


def test_pass_threshold_inclusive_at_seventy(api):
    """PRD §3.5: "The `outcome` is `PASS` when `score_weighted` is at least 70 — the
    boundary is inclusive, so a weighted score of exactly 70 passes — and `FAIL`
    otherwise"
    (1 MAJOR + 2 MINOR findings: weighted 100 - 20 - 10 = 70 -> PASS; flat 100 - 30 = 70.)

    Design: Corner/calculations/inspection_pass_threshold_inclusive
    """
    ctx = setup_lab_with_completed_inspection(
        [
            {"severity": "MAJOR", "description": "f1"},
            {"severity": "MINOR", "description": "f2"},
            {"severity": "MINOR", "description": "f3"},
        ],
        name="Lab O2",
        room="207",
        with_pi=False,
    )
    inspection = ctx["inspection"]
    assert inspection["score_weighted"] == 70
    assert inspection["outcome"] == "PASS", "score_weighted exactly 70 passes (inclusive)"
    assert inspection["score_flat"] == 70


def test_corrective_action_due_date_by_severity(api):
    """PRD §3.5: "Every finding spawns exactly one corrective action in `OPEN` status,
    carrying the parent `inspection_id`, the `lab_id` copied from the inspection, and
    the `description` and `severity` copied from the triggering finding. The action's
    `due_date` is `completed_at` plus 14 days for a `MAJOR` finding or plus 30 days
    for a `MINOR` finding."
    (Completion happens at the 2026-08-01T00:00:00Z startup clock: MAJOR -> due
    2026-08-15T00:00:00Z; MINOR -> due 2026-08-31T00:00:00Z.)

    Design: Corner/calculations/corrective_action_due_date_by_severity
    """
    ctx = setup_lab_with_completed_inspection(
        [
            {"severity": "MAJOR", "description": "open container"},
            {"severity": "MINOR", "description": "label faded"},
        ],
        name="Lab M2",
        room="205",
        with_pi=False,
    )
    cas = ctx["corrective_actions"]
    assert len(cas) == 2, "exactly one corrective action per finding"
    by_severity = {ca["severity"]: ca for ca in cas}
    major, minor = by_severity["MAJOR"], by_severity["MINOR"]

    assert major["due_date"].startswith("2026-08-15T00:00:00"), (
        f"MAJOR due completed_at + 14d, got {major['due_date']}"
    )
    assert minor["due_date"].startswith("2026-08-31T00:00:00"), (
        f"MINOR due completed_at + 30d, got {minor['due_date']}"
    )
    for ca in cas:
        assert ca["status"] == "OPEN"
        assert ca["lab_id"] == ctx["lab"]["id"]
        assert ca["inspection_id"] == ctx["inspection"]["id"]


def test_inspector_adjacent_windows_allowed(api):
    """PRD §3.5: "An inspector's calendar is protected by a half-open overlap rule:
    no other `SCHEDULED` inspection for the same `inspector_id` may overlap the new
    window, where two windows overlap exactly when the new start is before the
    existing end and the existing start is before the new end — windows that merely
    touch at an endpoint are allowed."

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_overlap
    """
    lab = create_lab(name="Lab O", department="Biology", building="Hall B", room="210")
    first = create_inspection(
        lab["id"], inspector_id="insp-1",
        scheduled_start="2026-08-10T09:00:00Z", scheduled_end="2026-08-10T10:00:00Z",
    )
    assert first["status"] == "SCHEDULED"

    # touching endpoint: 10:00 == existing end 10:00 -> allowed (half-open)
    adjacent = validate_success(
        api.create_inspection(
            create_inspection_payload(
                lab["id"], inspector_id="insp-1",
                scheduled_start="2026-08-10T10:00:00Z",
                scheduled_end="2026-08-10T11:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert adjacent["status"] == "SCHEDULED"


def test_inspector_overlapping_window_rejected(api):
    """PRD §3.5: "no other `SCHEDULED` inspection for the same `inspector_id` may
    overlap the new window, where two windows overlap exactly when the new start is
    before the existing end and the existing start is before the new end — windows
    that merely touch at an endpoint are allowed. A conflict is rejected with
    `ERR_INSPECTOR_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_overlap
    """
    lab = create_lab(name="Lab O2b", department="Biology", building="Hall B", room="210")
    create_inspection(
        lab["id"], inspector_id="insp-1",
        scheduled_start="2026-08-10T09:00:00Z", scheduled_end="2026-08-10T10:00:00Z",
    )

    # 09:30 < 10:00 and 09:00 < 10:30 -> true overlap
    res = api.create_inspection(
        create_inspection_payload(
            lab["id"], inspector_id="insp-1",
            scheduled_start="2026-08-10T09:30:00Z",
            scheduled_end="2026-08-10T10:30:00Z",
        ),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT)

    _, meta = validate_paginated(api.list_inspections(ADMIN, params={"inspector_id": "insp-1"}))
    assert meta["total_count"] == 1, "the conflicting inspection must not be created"


def test_inspection_window_end_must_be_strictly_after_start(api):
    """PRD §3.5: "The end must be strictly after the start, otherwise
    `ERR_INVALID_WINDOW`."

    Design: Corner/validations/inspection_window_end_before_start_rejected
    """
    lab = create_lab(name="Lab S2", department="Biology", building="Hall B", room="208")
    res = api.create_inspection(
        create_inspection_payload(
            lab["id"], inspector_id="insp-1",
            scheduled_start="2026-08-10T10:00:00Z",
            scheduled_end="2026-08-10T10:00:00Z",
        ),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW)
