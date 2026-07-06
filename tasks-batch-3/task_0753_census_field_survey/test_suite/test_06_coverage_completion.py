"""Area coverage rates (projected vs final), the completion bubble-up cascade,
and case-count conservation across the reopen cycle.

Translates queue-A dual_variant_calc (coverage leg), transitive_cascade
(completion leg), and compensating_invariant (case-count leg).
"""
import pytest

from test_helpers import (
    validate_success,
    make_enumerator_headers,
    TEST_USERS,
    create_response_payload,
    assert_area_count_partition,
    create_open_project,
    create_open_area,
    create_active_enumerator,
    add_case,
    assign_case,
    log_attempt,
    capture_response,
    setup_case_with_contact_made,
    setup_reinterview_in_review,
    finalize_reinterview,
)

ADMIN = TEST_USERS["survey_admin_headers"]


# ── dual_variant_calc: coverage_projected_vs_final_area ───────────────────────

def test_coverage_projected_counts_in_progress_final_does_not(api):
    """PRD §3.2: "Otherwise the projected rate is the sum of the complete and
    in-progress case counts divided by the total case count, and the final rate is
    the complete case count alone divided by the total case count; each is rounded
    half up to four decimal places."

    Area of 4 cases: 1 COMPLETE + 1 IN_PROGRESS + 2 UNASSIGNED ->
    projected = (1+1)/4 = 0.5, final = 1/4 = 0.25.

    Design: Difficulty/dual_variant_calc/coverage_projected_vs_final_area
    """
    proj = create_open_project()
    area = create_open_area(proj["id"], budget_cents=1_000_000)
    en1 = create_active_enumerator(proj["id"])
    case1 = add_case(area["id"], address="1 A St")
    case2 = add_case(area["id"], address="2 A St")
    add_case(area["id"], address="3 A St")
    add_case(area["id"], address="4 A St")

    assign_case(case1["id"], en1["id"], case1["version"])
    log_attempt(case1["id"], en1["id"], mode="IN_PERSON",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T10:30:00Z",
                disposition="CONTACT_MADE", mileage_miles=0)
    capture_response(case1["id"], en1["id"], mode="IN_PERSON", language_used="EN",
                     duration_minutes=20, flagged_answer_count=0, gps_variance_meters=0)

    assign_case(case2["id"], en1["id"], case2["version"])
    log_attempt(case2["id"], en1["id"], mode="PHONE",
                window_start="2026-03-01T13:00:00Z", window_end="2026-03-01T13:30:00Z",
                disposition="NO_ONE_HOME")

    report = validate_success(api.coverage_report(area["id"], ADMIN), 200)
    assert report["total_case_count"] == 4
    assert report["projected_coverage_rate"] == pytest.approx(0.5, abs=1e-6)
    assert report["final_coverage_rate"] == pytest.approx(0.25, abs=1e-6)


def test_coverage_projected_above_final_with_only_in_progress(api):
    """PRD §3.2: "Otherwise the projected rate is the sum of the complete and
    in-progress case counts divided by the total case count, and the final rate is
    the complete case count alone divided by the total case count; each is rounded
    half up to four decimal places."

    Area of 2 cases: 1 IN_PROGRESS + 1 UNASSIGNED, none COMPLETE ->
    projected = (0+1)/2 = 0.5, final = 0/2 = 0.0.

    Design: Difficulty/dual_variant_calc/coverage_projected_vs_final_area
    """
    proj = create_open_project()
    area = create_open_area(proj["id"], budget_cents=1_000_000)
    en1 = create_active_enumerator(proj["id"])
    case1 = add_case(area["id"], address="1 A St")
    add_case(area["id"], address="2 A St")

    assign_case(case1["id"], en1["id"], case1["version"])
    log_attempt(case1["id"], en1["id"], mode="PHONE",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T10:30:00Z",
                disposition="NO_ONE_HOME")

    report = validate_success(api.coverage_report(area["id"], ADMIN), 200)
    assert report["total_case_count"] == 2
    assert report["projected_coverage_rate"] == pytest.approx(0.5, abs=1e-6)
    assert report["final_coverage_rate"] == pytest.approx(0.0, abs=1e-6)


# ── transitive_cascade: completion_cascade_depth3 ─────────────────────────────

def test_response_capture_bubbles_area_to_complete(api):
    """PRD §3.7: "If after this the area has no case left pending or in progress —
    that is, its pending and in-progress counts together reach zero — the area
    bubbles up automatically from `IN_FIELD` to `COMPLETE`."
    PRD §3.7: "Capturing a response advances the area's tallies: the area's
    `in_progress_case_count` decrements by one, its `complete_case_count`
    increments by one, and coverage is recomputed."

    A single-case area: capturing the response drives Case -> COMPLETE, then area
    complete_case_count -> 1 / final coverage 1.0, then area bubble-up -> COMPLETE.

    Design: Difficulty/transitive_cascade/completion_cascade_depth3
    """
    ctx = setup_case_with_contact_made()
    capture_response(ctx["case"]["id"], ctx["enumerator"]["id"], mode="IN_PERSON",
                     language_used="EN", duration_minutes=20, flagged_answer_count=0,
                     gps_variance_meters=0)
    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "COMPLETE"
    area = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert area["complete_case_count"] == 1
    assert area["final_coverage_rate"] == pytest.approx(1.0, abs=1e-6)
    assert area["status"] == "COMPLETE"


def test_response_capture_no_bubble_when_pending_case_remains(api):
    """PRD §3.7: "If after this the area has no case left pending or in progress —
    that is, its pending and in-progress counts together reach zero — the area
    bubbles up automatically from `IN_FIELD` to `COMPLETE`."

    With a second still-UNASSIGNED (pending) case in the area, capturing the
    response on the first case does NOT satisfy the bubble-up precondition, so the
    area stays IN_FIELD even though one case is COMPLETE.

    Design: Difficulty/transitive_cascade/completion_cascade_depth3
    """
    proj = create_open_project()
    area = create_open_area(proj["id"], budget_cents=1_000_000)
    en1 = create_active_enumerator(proj["id"])
    case1 = add_case(area["id"], address="1 A St")
    add_case(area["id"], address="2 A St")  # remains pending (UNASSIGNED)

    assign_case(case1["id"], en1["id"], case1["version"])
    log_attempt(case1["id"], en1["id"], mode="IN_PERSON",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T10:30:00Z",
                disposition="CONTACT_MADE", mileage_miles=0)
    capture_response(case1["id"], en1["id"], mode="IN_PERSON", language_used="EN",
                     duration_minutes=20, flagged_answer_count=0, gps_variance_meters=0)

    case = validate_success(api.get_case(case1["id"], ADMIN), 200)
    assert case["status"] == "COMPLETE"
    area_after = validate_success(api.get_area(area["id"], ADMIN), 200)
    assert area_after["complete_case_count"] == 1
    assert area_after["status"] == "IN_FIELD"


# ── compensating_invariant: case_count_conservation_on_reopen ─────────────────

def test_total_case_count_conserved_through_fraud_reopen(api):
    """PRD §3.8: "Second, invalidating the response reopens its parent case from
    `COMPLETE` back to `IN_PROGRESS`: the area's `complete_case_count` decrements
    by one, its `in_progress_case_count` increments by one, and coverage is
    recomputed."

    After response capture (COMPLETE) and its compensating fraud-reopen
    (IN_PROGRESS), the area's per-status counts still sum to total_case_count == 1.

    Design: Difficulty/compensating_invariant/case_count_conservation_on_reopen
    """
    ctx = setup_reinterview_in_review()
    finalize_reinterview(ctx["reinterview"]["id"], "FRAUD")

    area = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert area["total_case_count"] == 1
    assert area["complete_case_count"] == 0
    assert area["in_progress_case_count"] == 1
    assert_area_count_partition(area)


def test_case_count_partition_holds_before_and_after_reopen(api):
    """PRD §3.2: "The area maintains a full partition of its cases by status:
    `total_case_count` over all cases, and one running count each for cases in
    `UNASSIGNED` or `ASSIGNED` combined (`pending_case_count`), `IN_PROGRESS`
    (`in_progress_case_count`), `COMPLETE` (`complete_case_count`), `REFUSED`
    (`refused_case_count`), `VACANT` (`vacant_case_count`), and `MAX_ATTEMPTS`
    (`max_attempts_case_count`)."

    The partition sums to the (unchanged) total_case_count == 1 both while the sole
    case is COMPLETE and after the fraud reopen moves it to IN_PROGRESS.

    Design: Difficulty/compensating_invariant/case_count_conservation_on_reopen
    """
    ctx = setup_reinterview_in_review()
    before = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert before["total_case_count"] == 1
    assert before["complete_case_count"] == 1
    assert_area_count_partition(before)

    finalize_reinterview(ctx["reinterview"]["id"], "FRAUD")
    after = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert after["total_case_count"] == 1
    assert_area_count_partition(after)
