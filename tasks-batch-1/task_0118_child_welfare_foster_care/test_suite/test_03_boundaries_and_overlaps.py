"""Boundary precision, temporal-overlap geometry, and validation-priority conflicts.

Queue A — difficulty rules: boundary_precision_check, resource_temporal_overlap,
priority_pair_validation_conflict.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    setup_workers, open_case_with_child, create_licensed_home, place_child,
    setup_placed_child, set_clock,
)


# =========================================================================
# Rule 6 — boundary_precision_check / tpr_clock_exact_15_month_boundary
# =========================================================================
def test_tpr_clock_breached_true_at_exactly_15_months(api):
    """PRD §3.6: "The case's `months_in_care` is the number of **completed whole months** that have elapsed from `removal_date` to the current clock — counted by month anniversaries, not by dividing days. A removal on the third of a month counts a given month only once the third of the following month is reached".
    PRD §3.6: "tpr_clock_breached` is true once `months_in_care` is at least 15, and false otherwise."
    Removed 2024-01-03, clock 2025-04-03 -> exactly 15 completed months.

    Design: Difficulty/boundary_precision_check/tpr_clock_exact_15_month_boundary
    """
    w = setup_workers()
    set_clock("2024-01-03T00:00:00Z")
    case, child = open_case_with_child(w)
    home = create_licensed_home(w, bed_capacity=1, max_age_years=18)
    place_child(w, child["id"], home["id"], home["version"])

    set_clock("2025-04-03T00:00:00Z")
    recomputed = validate_success(api.recompute_clock(case["id"], w.caseworker))
    assert recomputed["months_in_care"] == 15, f"got {recomputed['months_in_care']}"
    assert recomputed["tpr_clock_breached"] is True


def test_tpr_clock_not_breached_one_day_before_15_months(api):
    """PRD §3.6: "partial months do not count."
    PRD §3.6: "Below 15 months there is no filing pressure".
    Removed 2024-01-03, clock 2025-04-02 (14 months + 30 days, the 15th anniversary
    not yet reached) -> months_in_care 14, breach false.

    Design: Difficulty/boundary_precision_check/tpr_clock_exact_15_month_boundary
    """
    w = setup_workers()
    set_clock("2024-01-03T00:00:00Z")
    case, child = open_case_with_child(w)
    home = create_licensed_home(w, bed_capacity=1, max_age_years=18)
    place_child(w, child["id"], home["id"], home["version"])

    set_clock("2025-04-02T00:00:00Z")
    recomputed = validate_success(api.recompute_clock(case["id"], w.caseworker))
    assert recomputed["months_in_care"] == 14, f"got {recomputed['months_in_care']}"
    assert recomputed["tpr_clock_breached"] is False


# =========================================================================
# Rule 6 — boundary_precision_check / visitation_touching_intervals_do_not_overlap
# =========================================================================
def test_touching_visit_windows_do_not_overlap(api):
    """PRD §3.8: "Because the interval is half-open, two visits that merely touch — one ending exactly when the next begins — do not overlap and are both allowed."

    Design: Difficulty/boundary_precision_check/visitation_touching_intervals_do_not_overlap
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-02-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = get_success_data(api.create_case_plan({"case_id": case["id"],
            "required_visits_per_month": 4, "objectives_total": 5}, w.caseworker))
    get_success_data(api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T10:00:00Z", "window_end": "2026-02-05T11:00:00Z"}, w.caseworker))

    vis2 = validate_success(api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T11:00:00Z", "window_end": "2026-02-05T12:00:00Z"}, w.caseworker),
        expected_status=201)
    assert vis2["status"] == "SCHEDULED"
    assert vis2["window_start"] == "2026-02-05T11:00:00.000Z"


def test_overlapping_visit_window_rejected_after_touching_allowed(api):
    """PRD §3.8: "a new `SCHEDULED` visit for the same child whose window, treated as a half-open interval from `window_start` up to but not including `window_end`, overlaps an existing `SCHEDULED` visit for that same child is rejected with `ERR_VISIT_OVERLAP`."
    A window starting at 10:30 (strictly inside [10:00,11:00)) overlaps and is rejected.

    Design: Difficulty/boundary_precision_check/visitation_touching_intervals_do_not_overlap
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-02-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = get_success_data(api.create_case_plan({"case_id": case["id"],
            "required_visits_per_month": 4, "objectives_total": 5}, w.caseworker))
    get_success_data(api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T10:00:00Z", "window_end": "2026-02-05T11:00:00Z"}, w.caseworker))

    resp = api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T10:30:00Z", "window_end": "2026-02-05T11:30:00Z"}, w.caseworker)
    validate_error(resp, "ERR_VISIT_OVERLAP")


# =========================================================================
# Rule 8 — resource_temporal_overlap / visitation_half_open_interval_overlap_rejected
# =========================================================================
def test_interior_visit_overlap_rejected(api):
    """PRD §3.8: "a new `SCHEDULED` visit for the same child whose window, treated as a half-open interval from `window_start` up to but not including `window_end`, overlaps an existing `SCHEDULED` visit for that same child is rejected with `ERR_VISIT_OVERLAP`."
    Existing [10:00,11:00); new [10:30,11:30) genuinely intersects.

    Design: Difficulty/resource_temporal_overlap/visitation_half_open_interval_overlap_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-02-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = get_success_data(api.create_case_plan({"case_id": case["id"],
            "required_visits_per_month": 4, "objectives_total": 5}, w.caseworker))
    get_success_data(api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T10:00:00Z", "window_end": "2026-02-05T11:00:00Z"}, w.caseworker))

    resp = api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T10:30:00Z", "window_end": "2026-02-05T11:30:00Z"}, w.caseworker)
    validate_error(resp, "ERR_VISIT_OVERLAP")


def test_non_overlapping_later_visit_accepted(api):
    """PRD §3.8: "Visits also may not collide: a new `SCHEDULED` visit for the same child whose window, treated as a half-open interval from `window_start` up to but not including `window_end`, overlaps an existing `SCHEDULED` visit for that same child is rejected with `ERR_VISIT_OVERLAP`."
    A clearly disjoint later window ([12:00,13:00) after [10:00,11:00)) does not
    collide and is accepted.

    Design: Difficulty/resource_temporal_overlap/visitation_half_open_interval_overlap_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-02-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = get_success_data(api.create_case_plan({"case_id": case["id"],
            "required_visits_per_month": 4, "objectives_total": 5}, w.caseworker))
    get_success_data(api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T10:00:00Z", "window_end": "2026-02-05T11:00:00Z"}, w.caseworker))

    vis2 = validate_success(api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T12:00:00Z", "window_end": "2026-02-05T13:00:00Z"}, w.caseworker),
        expected_status=201)
    assert vis2["status"] == "SCHEDULED"


# =========================================================================
# Rule 8 — resource_temporal_overlap / hearing_docket_buffer_overlap_rejected
# =========================================================================
def test_hearing_within_30min_buffer_rejected(api):
    """PRD §3.9: "a new `SCHEDULED` hearing whose `scheduled_at` falls within 30 minutes — inclusive on both sides — of an existing `SCHEDULED` hearing on the same case is rejected with `ERR_HEARING_OVERLAP`."
    Existing 10:00; new 10:20 falls inside the +/-30-minute band.

    Design: Difficulty/resource_temporal_overlap/hearing_docket_buffer_overlap_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    get_success_data(api.create_hearing(
        {"case_id": case["id"], "hearing_type": "REVIEW",
         "scheduled_at": "2026-01-10T10:00:00Z"}, w.caseworker))

    resp = api.create_hearing(
        {"case_id": case["id"], "hearing_type": "REVIEW",
         "scheduled_at": "2026-01-10T10:20:00Z"}, w.caseworker)
    validate_error(resp, "ERR_HEARING_OVERLAP")


def test_hearing_exactly_31min_away_accepted(api):
    """PRD §3.9: "A new hearing exactly 30 minutes from an existing one collides; one strictly more than 30 minutes away does not."
    Existing 10:00; new 10:31 is strictly beyond the buffer -> accepted.

    Design: Difficulty/resource_temporal_overlap/hearing_docket_buffer_overlap_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    get_success_data(api.create_hearing(
        {"case_id": case["id"], "hearing_type": "REVIEW",
         "scheduled_at": "2026-01-10T10:00:00Z"}, w.caseworker))

    second = validate_success(api.create_hearing(
        {"case_id": case["id"], "hearing_type": "REVIEW",
         "scheduled_at": "2026-01-10T10:31:00Z"}, w.caseworker), expected_status=201)
    assert second["status"] == "SCHEDULED"


# =========================================================================
# Rule 5 — priority_pair_validation_conflict / state_beats_fiscal_no_beds_on_terminal_home
# =========================================================================
def test_suspended_full_home_surfaces_home_not_licensed_over_no_beds(api):
    """PRD §3.5: "the home must be in a state that accepts children — its `license_status` must be `LICENSED` or `PROVISIONAL`, never `PENDING`, `SUSPENDED`, or `EXPIRED`, else `ERR_HOME_NOT_LICENSED`".
    PRD §3.5: "A request that violates several of these surfaces the earliest in this ordering."
    A SUSPENDED, full (cap 1) home violates both; the licensing check wins.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_no_beds_on_terminal_home
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    # First child placed into a cap-1 home, then home suspended (cascade removes child1).
    case, child1, home, placement = setup_placed_child(w, bed_capacity=1)
    child2 = get_success_data(api.create_child(
        {"case_id": case["id"], "full_name": "Child Z2",
         "date_of_birth": "2016-01-01T00:00:00Z"}, w.caseworker))
    suspended = get_success_data(api.suspend_home(home["id"], w.licensing))

    resp = api.create_placement(
        {"child_id": child2["id"], "foster_home_id": home["id"],
         "expected_foster_home_version": suspended["version"]}, w.caseworker)
    validate_error(resp, "ERR_HOME_NOT_LICENSED")


def test_licensed_full_home_surfaces_no_beds_when_licensing_passes(api):
    """PRD §3.5: "the home must have an open bed — its `active_placement_count` must be strictly less than its `bed_capacity`, else `ERR_NO_BEDS`".
    PRD §3.5: "A request that violates several of these surfaces the earliest in this ordering."
    When the higher-priority licensing/state check passes (home stays LICENSED), the
    capacity branch is the one that fires: a cap-1 home holding one ACTIVE placement
    rejects a second placement with ERR_NO_BEDS.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_no_beds_on_terminal_home
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child1, home, placement = setup_placed_child(w, bed_capacity=1)
    child2 = get_success_data(api.create_child(
        {"case_id": case["id"], "full_name": "Child Z3",
         "date_of_birth": "2016-01-01T00:00:00Z"}, w.caseworker))
    home_now = get_success_data(api.get_foster_home(home["id"], w.caseworker))
    assert home_now["license_status"] == "LICENSED"
    resp = api.create_placement(
        {"child_id": child2["id"], "foster_home_id": home["id"],
         "expected_foster_home_version": home_now["version"]}, w.caseworker)
    validate_error(resp, "ERR_NO_BEDS")


# =========================================================================
# Rule 5 — priority_pair_validation_conflict / existence_beats_state_unknown_referral_screen
# =========================================================================
def test_screen_unknown_referral_surfaces_not_found_over_invalid_state(api):
    """PRD §2.6: "The first reference that resolves to nothing yields `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.3: "This basic shape validation is the lowest-priority of the constraint checks, applied only after the authentication, authorization, existence, and state guards above have passed".
    Screening a non-existent referral id resolves to nothing first -> 404, never 409.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_unknown_referral_screen
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    resp = api.screen_referral("00000000-0000-4000-8000-000000000000", w.screener)
    validate_error(resp, "ERR_NOT_FOUND")


def test_existing_referral_wrong_state_surfaces_invalid_state_not_not_found(api):
    """PRD §3.1: "the screen of a referral not in `RECEIVED` status is an invalid transition (`ERR_INVALID_STATE`)."
    PRD §2.6: "any resource named in the URL path is resolved first, and only then are body-referenced resources resolved."
    A referral that EXISTS but is SCREENED_OUT passes the existence guard and fails the
    state guard with 409 - the complementary side of existence(P3)-before-state(P4):
    the state check is only reached once existence holds.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_unknown_referral_screen
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    ref = get_success_data(api.create_referral(
        {"reporter_type": "ANONYMOUS", "child_name": "Child B2",
         "alleged_maltreatment": "EMOTIONAL_ABUSE", "priority_factors": []}, w.screener))
    out = get_success_data(api.screen_referral(ref["id"], w.screener))
    assert out["status"] == "SCREENED_OUT"
    resp = api.screen_referral(ref["id"], w.screener)
    validate_error(resp, "ERR_INVALID_STATE")
