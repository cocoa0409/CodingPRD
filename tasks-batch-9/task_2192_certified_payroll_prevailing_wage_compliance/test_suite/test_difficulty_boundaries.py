"""Exact boundaries on monetary, temporal and interval thresholds."""
from test_helpers import (
    ApiErrorId,
    build_active_determination,
    build_determination,
    build_finding,
    build_interview,
    build_rate,
    get_success_data,
    setup_deficient_submission_under_review,
    setup_env_with_worker,
    validate_error,
    validate_success,
)


def test_outstanding_restitution_of_exactly_500000_does_not_freeze(api, cruz_headers):
    """A demand of exactly 500000 cents leaves the posture OPEN.

    PRD 2.9: "Step two: otherwise, if the project's outstanding restitution is strictly
    greater than five thousand dollars — that is, more than 500,000 cents — the posture is
    `FROZEN`; an outstanding balance of exactly 500,000 cents does not freeze the project."

    Design: Difficulty/boundary_precision_check/posture_freeze_restitution_threshold_is_strictly_above_500000
    """
    env, submission, _rows = setup_deficient_submission_under_review(api)
    before = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert before["posture"] == "OPEN"

    resp = api.create_finding(
        {
            "project_id": env["project"]["id"],
            "payroll_submission_id": submission["id"],
            "finding_type": "UNDERPAYMENT",
            "severity": "MAJOR",
            "restitution_required_cents": 500000,
        },
        cruz_headers,
    )
    finding = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert finding["restitution_outstanding_cents"] == 500000

    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["outstanding_restitution_cents"] == 500000
    assert project["open_finding_count"] == 1
    assert project["open_critical_finding_count"] == 0
    assert project["posture"] == "OPEN"
    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], cruz_headers)
    )
    assert assignment["status"] == "ACTIVE"


def test_posture_open_at_the_threshold_still_permits_the_frozen_gated_advance(
    api, portal_admin_headers
):
    """With exactly 500000 outstanding the project may still advance to SUBSTANTIALLY_COMPLETE.

    PRD 3.4: "the same operator advances the project `ACTIVE → SUBSTANTIALLY_COMPLETE` with a
    `to_status` of `SUBSTANTIALLY_COMPLETE`; this requires the project to be `ACTIVE` and its
    `posture` not to be `FROZEN`, and a frozen project is held back with
    `ERR_PROJECT_FROZEN`."

    Design: Difficulty/boundary_precision_check/posture_freeze_restitution_threshold_is_strictly_above_500000
    """
    env, submission, _rows = setup_deficient_submission_under_review(api)
    build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="UNDERPAYMENT", severity="MAJOR", restitution_required_cents=500000,
    )
    advanced = get_success_data(
        api.set_project_status(
            env["project"]["id"], {"to_status": "SUBSTANTIALLY_COMPLETE"}, portal_admin_headers
        )
    )
    assert advanced["status"] == "SUBSTANTIALLY_COMPLETE"
    assert advanced["outstanding_restitution_cents"] == 500000


def test_an_interview_starting_exactly_sixty_minutes_later_is_permitted(api, cruz_headers):
    """The buffered span [10:00, 14:00) merely touches the existing half-open [08:00, 10:00).

    PRD 3.9: "The requested window is expanded by a full hour — sixty minutes — on each side,
    and the expanded span must not intersect the *unexpanded* window of any other interview on
    the same `worker_id` whose `status` is `SCHEDULED`, `CONDUCTED_MATCHED` or
    `CONDUCTED_DISCREPANT`." PRD 2.11: "An **interview window** is half-open: it runs from
    `window_start` inclusive up to `window_end` exclusive."

    Design: Difficulty/boundary_precision_check/interview_buffer_exact_sixty_minute_gap_is_permitted
    """
    env = setup_env_with_worker(api)
    first = build_interview(
        api, env, env["worker"]["id"],
        "2026-08-03T08:00:00.000Z", "2026-08-03T10:00:00.000Z",
    )
    resp = api.create_interview(
        {
            "project_id": env["project"]["id"],
            "contract_assignment_id": env["assignment"]["id"],
            "worker_id": env["worker"]["id"],
            "window_start": "2026-08-03T11:00:00.000Z",
            "window_end": "2026-08-03T13:00:00.000Z",
        },
        cruz_headers,
    )
    second = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert second["status"] == "SCHEDULED"
    assert second["window_start"] == "2026-08-03T11:00:00.000Z"
    still_there = get_success_data(api.get_interview(first["id"], cruz_headers))
    assert still_there["status"] == "SCHEDULED"


def test_the_sixty_minute_gap_is_permitted_on_the_earlier_side_too(api):
    """A window ending exactly sixty minutes before the existing start is equally legal.

    PRD 3.9: "The requested window is expanded by a full hour — sixty minutes — on each side,
    and the expanded span must not intersect the *unexpanded* window of any other interview on
    the same `worker_id`". PRD 3.9: "Because the comparison is made against the expanded span,
    two windows that merely touch end-to-end still collide".

    Design: Difficulty/boundary_precision_check/interview_buffer_exact_sixty_minute_gap_is_permitted
    """
    env = setup_env_with_worker(api)
    build_interview(
        api, env, env["worker"]["id"],
        "2026-08-03T08:00:00.000Z", "2026-08-03T10:00:00.000Z",
    )
    # Expands to [04:00, 08:00), which touches 08:00 without containing it.
    earlier = build_interview(
        api, env, env["worker"]["id"],
        "2026-08-03T05:00:00.000Z", "2026-08-03T07:00:00.000Z",
    )
    assert earlier["status"] == "SCHEDULED"
    assert earlier["window_end"] == "2026-08-03T07:00:00.000Z"


def _locality_determinations(api):
    """A [01-01, 06-01) ACTIVE, B [06-01, +inf) ACTIVE, C [05-15, 05-20) still DRAFT."""
    wd_a, _rates_a = build_active_determination(
        api,
        effective_date="2026-01-01T00:00:00.000Z",
        expiry_date="2026-06-01T00:00:00.000Z",
    )
    wd_b, _rates_b = build_active_determination(api, effective_date="2026-06-01T00:00:00.000Z")
    wd_c = build_determination(
        api,
        effective_date="2026-05-15T00:00:00.000Z",
        expiry_date="2026-05-20T00:00:00.000Z",
    )
    build_rate(api, wd_c["id"])
    return wd_a, wd_b, wd_c


def test_a_determination_landing_inside_a_governing_period_cannot_activate(
    api, portal_admin_headers
):
    """C sits strictly inside A's half-open span, so its activation is refused.

    PRD 2.11: "A determination whose `effective_date` falls exactly on another
    determination's `expiry_date` does not collide with it, while one whose `effective_date`
    falls strictly inside another's span does." PRD 3.1: "If any of those periods intersects
    the activating one, the activation is refused with `ERR_DETERMINATION_PERIOD_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/determination_governing_period_half_open_on_a_locality
    """
    wd_a, wd_b, wd_c = _locality_determinations(api)
    resp = api.activate_wage_determination(wd_c["id"], portal_admin_headers, {})
    validate_error(
        resp, ApiErrorId.ERR_DETERMINATION_PERIOD_OVERLAP.value, expected_status=409
    )

    still_draft = get_success_data(api.get_wage_determination(wd_c["id"], portal_admin_headers))
    assert still_draft["status"] == "DRAFT"
    read_a = get_success_data(api.get_wage_determination(wd_a["id"], portal_admin_headers))
    assert read_a["status"] == "ACTIVE"
    assert read_a["expiry_date"] == "2026-06-01T00:00:00.000Z"
    read_b = get_success_data(api.get_wage_determination(wd_b["id"], portal_admin_headers))
    assert read_b["status"] == "ACTIVE"


def test_a_successor_effective_exactly_on_the_expiry_date_activates_cleanly(
    api, portal_admin_headers
):
    """B's effective_date equals A's expiry_date, so the two half-open periods only touch.

    PRD 2.11: "A determination's **governing period** is half-open: it runs from
    `effective_date` inclusive up to `expiry_date` exclusive". PRD 3.1: "Because both periods
    are half-open, a determination whose `effective_date` sits exactly on another's
    `expiry_date` — whether that expiry was declared at creation or written into the row by an
    earlier supersede — passes cleanly".

    Design: Difficulty/resource_temporal_overlap/determination_governing_period_half_open_on_a_locality
    """
    wd_a, _rates_a = build_active_determination(
        api,
        effective_date="2026-01-01T00:00:00.000Z",
        expiry_date="2026-06-01T00:00:00.000Z",
    )
    wd_b = build_determination(api, effective_date="2026-06-01T00:00:00.000Z")
    build_rate(api, wd_b["id"])

    resp = api.activate_wage_determination(wd_b["id"], portal_admin_headers, {})
    activated = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert activated["status"] == "ACTIVE"
    # The predecessor was not superseded, so it keeps its own declared expiry.
    read_a = get_success_data(api.get_wage_determination(wd_a["id"], portal_admin_headers))
    assert read_a["status"] == "ACTIVE"
    assert read_a["expiry_date"] == "2026-06-01T00:00:00.000Z"


def test_the_sixty_minute_buffer_creates_a_conflict_raw_windows_do_not_have(api, cruz_headers):
    """Raw [08:00, 10:00) and [10:30, 12:30) do not overlap, but the buffer makes them collide.

    PRD 3.9: "That buffer is what keeps auditors from double-booking a worker. The requested
    window is expanded by a full hour — sixty minutes — on each side, and the expanded span
    must not intersect the *unexpanded* window of any other interview on the same `worker_id`
    whose `status` is `SCHEDULED`, `CONDUCTED_MATCHED` or `CONDUCTED_DISCREPANT`. ... the
    request is refused with `ERR_INTERVIEW_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/interview_window_buffered_overlap_on_a_worker
    """
    env = setup_env_with_worker(api)
    first = build_interview(
        api, env, env["worker"]["id"],
        "2026-08-03T08:00:00.000Z", "2026-08-03T10:00:00.000Z",
    )
    resp = api.create_interview(
        {
            "project_id": env["project"]["id"],
            "contract_assignment_id": env["assignment"]["id"],
            "worker_id": env["worker"]["id"],
            "window_start": "2026-08-03T10:30:00.000Z",
            "window_end": "2026-08-03T12:30:00.000Z",
        },
        cruz_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEW_BUFFER_CONFLICT.value, expected_status=409)

    unchanged = get_success_data(api.get_interview(first["id"], cruz_headers))
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["window_end"] == "2026-08-03T10:00:00.000Z"


def test_cancelling_frees_the_buffered_window_on_the_worker(api, cruz_headers):
    """The rejected booking succeeds once the occupying interview is CANCELLED.

    PRD 3.9: "Interviews in `CANCELLED` do not occupy anything: cancelling frees the window,
    and a new interview on the same worker may then take an overlapping or buffer-adjacent
    slot."

    Design: Difficulty/resource_temporal_overlap/interview_window_buffered_overlap_on_a_worker
    """
    env = setup_env_with_worker(api)
    first = build_interview(
        api, env, env["worker"]["id"],
        "2026-08-03T08:00:00.000Z", "2026-08-03T10:00:00.000Z",
    )
    cancelled = get_success_data(
        api.cancel_interview(
            first["id"], {"cancellation_reason": "Crew demobilised from the site."}, cruz_headers
        )
    )
    assert cancelled["status"] == "CANCELLED"

    second = build_interview(
        api, env, env["worker"]["id"],
        "2026-08-03T10:30:00.000Z", "2026-08-03T12:30:00.000Z",
    )
    assert second["status"] == "SCHEDULED"
    assert second["window_start"] == "2026-08-03T10:30:00.000Z"
