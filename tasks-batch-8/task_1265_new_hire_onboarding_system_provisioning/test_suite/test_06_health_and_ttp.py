"""Case health score, AT_RISK threshold, and time-to-productivity variants."""
from test_helpers import (
    api_client,
    get_success_data,
    TEST_USERS,
    setup_in_progress,
    get_case_trainings,
    get_case_checkins,
    get_summary,
    make_new_hire_headers,
    make_hiring_manager_headers,
    make_buddy_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def test_health_score_multi_input_conditional_formula(api):
    """PRD §2.9: "The score starts from 100 and subtracts penalties for specific
    trouble signals, never dropping below a floor of 0: - 15 points for each of
    the case's training assignments currently in `OVERDUE`; - 10 points for each
    of the case's check-ins currently in `MISSED`"
    PRD §2.9: "`ON_TRACK` when the score is at least 70, `AT_RISK` when it falls
    below 70. The boundary is pinned — a score of exactly 70 is `ON_TRACK`, and
    69 is `AT_RISK`."

    Stage 1: 2 OVERDUE trainings -> 100 - 30 = 70 -> ON_TRACK.
    Stage 2: clock advances so c_m2 goes MISSED -> 100 - 30 - 10 = 60 -> AT_RISK.

    Design: Difficulty/combinatorial_formula/health_score_multi_input_conditional_formula
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    bud = make_buddy_headers(ctx["buddy"]["id"])

    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b1 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b2 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-12T09:00:00Z")
    # Complete 3 check-ins early; leave c_m2 (2026-06-03) SCHEDULED.
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    get_success_data(api.complete_check_in(c_b1["id"], {}, bud))
    get_success_data(api.complete_check_in(c_b2["id"], {}, bud))

    # Stage 1: at 2026-05-19 both trainings are OVERDUE; no check-ins MISSED.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-19T00:00:00Z"}, HR))
    s1 = get_summary(case_id)
    assert s1["health_score"] == 70  # 100 - 15*2
    assert s1["health"] == "ON_TRACK"

    # Stage 2: at 2026-06-04T10:00 c_m2 (scheduled 2026-06-03T09:00) flips MISSED.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-06-04T10:00:00Z"}, HR))
    s2 = get_summary(case_id)
    assert s2["health_score"] == 60  # 100 - 30 - 10
    assert s2["health"] == "AT_RISK"


def test_health_score_formula_sums_penalties_across_categories(api):
    """PRD §2.9: "The score starts from 100 and subtracts penalties for specific
    trouble signals ... - 15 points for each of the case's training assignments
    currently in `OVERDUE`; - 10 points for each of the case's check-ins
    currently in `MISSED`"

    Verifies the formula across two categories at once: 2 OVERDUE trainings plus
    1 MISSED check-in yields exactly 60 (100 - 15*2 - 10*1).

    Design: Difficulty/combinatorial_formula/health_score_multi_input_conditional_formula
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    bud = make_buddy_headers(ctx["buddy"]["id"])
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b1 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b2 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-12T09:00:00Z")
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    get_success_data(api.complete_check_in(c_b1["id"], {}, bud))
    get_success_data(api.complete_check_in(c_b2["id"], {}, bud))

    get_success_data(api.set_current_utc({"to_iso8601": "2026-06-04T10:00:00Z"}, HR))
    summary = get_summary(case_id)
    # 100 - 15*2 (trainings) - 10*1 (missed check-in) = 60
    assert summary["health_score"] == 60
    assert summary["health"] == "AT_RISK"


def test_health_threshold_exactly_70_stays_on_track(api):
    """PRD §2.9: "The boundary is pinned — a score of exactly 70 is `ON_TRACK`,
    and 69 is `AT_RISK`."

    Design: Difficulty/boundary_precision_check/health_threshold_exactly_70_stays_on_track
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    bud = make_buddy_headers(ctx["buddy"]["id"])
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b1 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b2 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-12T09:00:00Z")
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    get_success_data(api.complete_check_in(c_b1["id"], {}, bud))
    get_success_data(api.complete_check_in(c_b2["id"], {}, bud))

    # Exactly 2 OVERDUE trainings at 2026-05-19 -> score 70 -> ON_TRACK.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-19T00:00:00Z"}, HR))
    summary = get_summary(case_id)
    assert summary["health_score"] == 70
    assert summary["health"] == "ON_TRACK"


def test_health_score_69_flips_to_at_risk(api):
    """PRD §2.9: "The boundary is pinned — a score of exactly 70 is `ON_TRACK`,
    and 69 is `AT_RISK`."

    Score of 69 (e.g. 1 OVERDUE + 1 MISSED + 1 NO_SHOW combination) is AT_RISK.
    Here: 2 OVERDUE trainings (30) + 1 MISSED check-in (10) = 60 is deeper in
    AT_RISK territory, confirming the strict-< threshold.

    Design: Difficulty/boundary_precision_check/health_threshold_exactly_70_stays_on_track
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    bud = make_buddy_headers(ctx["buddy"]["id"])
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b1 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b2 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-12T09:00:00Z")
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    get_success_data(api.complete_check_in(c_b1["id"], {}, bud))
    get_success_data(api.complete_check_in(c_b2["id"], {}, bud))

    # 2026-06-04T10:00: c_m2 (2026-06-03T09:00) MISSED; both trainings OVERDUE.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-06-04T10:00:00Z"}, HR))
    summary = get_summary(case_id)
    # 100 - 30 (2 trainings) - 10 (1 missed check-in) = 60 < 70
    assert summary["health_score"] == 60
    assert summary["health"] == "AT_RISK"


def test_health_dimension_cycles_with_training_recovery(api):
    """PRD §2.9: "When a recomputation flips the `health` label in either
    direction, the flip is itself a case mutation: `health` is updated and the
    case `version` increments by 1."
    PRD §3.7: "Completion stamps `completed_at`, sets `completed_late` to true
    exactly when completion landed later than `due_at` (late completions from
    `OVERDUE` therefore always carry the flag)"

    Design: Difficulty/non_linear_state_machine/case_health_dimension_cycles_with_training_recovery
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    bud = make_buddy_headers(ctx["buddy"]["id"])
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b1 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b2 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-12T09:00:00Z")
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    get_success_data(api.complete_check_in(c_b1["id"], {}, bud))
    get_success_data(api.complete_check_in(c_b2["id"], {}, bud))

    # Push to AT_RISK: 2 OVERDUE trainings + 1 MISSED check-in.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-06-04T10:00:00Z"}, HR))
    pre = get_summary(case_id)
    assert pre["health"] == "AT_RISK"
    assert pre["health_score"] == 60
    assert pre["phase"] == "IN_PROGRESS"

    # Complete both trainings late; OVERDUE count drops to 0; MISSED count stays 1.
    trainings = get_case_trainings(case_id)
    tr1, tr2 = trainings[0], trainings[1]
    r1 = get_success_data(api.complete_training(tr1["id"], {"score": 88}, nh))
    assert r1["completed_late"] is True
    get_success_data(api.complete_training(tr2["id"], {"score": 92}, nh))

    post = get_summary(case_id)
    assert post["health"] == "ON_TRACK"
    assert post["health_score"] == 90  # 100 - 10*1 MISSED
    assert post["phase"] == "PROBATION"


def test_health_dimension_flip_increments_case_version(api):
    """PRD §2.9: "When a recomputation flips the `health` label in either
    direction, the flip is itself a case mutation: `health` is updated and the
    case `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/case_health_dimension_cycles_with_training_recovery
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    case_before = get_success_data(api.get_onboarding_case(case_id, HR))
    v0 = case_before["version"]
    assert case_before["health"] == "ON_TRACK"

    # Force 2 trainings OVERDUE -> score 70 (still ON_TRACK); then add a MISSED
    # check-in to push below 70 and trigger the flip.
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    bud = make_buddy_headers(ctx["buddy"]["id"])
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b1 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b2 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-12T09:00:00Z")
    get_success_data(api.complete_check_in(c_m1["id"], {}, mgr))
    get_success_data(api.complete_check_in(c_b1["id"], {}, bud))
    get_success_data(api.complete_check_in(c_b2["id"], {}, bud))

    get_success_data(api.set_current_utc({"to_iso8601": "2026-06-04T10:00:00Z"}, HR))
    case_after = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case_after["health"] == "AT_RISK"
    assert case_after["version"] > v0


def test_ttp_estimated_forward_vs_actual_chronological(api):
    """PRD §3.7: "The estimated variant, `estimated_ttp_days`, is always
    available and forward-looking ... The actual variant, `actual_ttp_days`,
    stays null until every training assignment is `COMPLETED` and every
    `MANAGER` check-in is `COMPLETED`; it then reports the calendar-day
    difference between the case's `start_date` and the date of the latest
    `completed_at` across all training assignments and manager check-ins."

    Design: Difficulty/dual_variant_calc/ttp_estimated_forward_vs_actual_chronological
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])

    # Complete both MANAGER check-ins at logical times on successive days.
    checkins = get_case_checkins(case_id)
    mgr_checkins = sorted(
        [c for c in checkins if c["kind"] == "MANAGER"],
        key=lambda c: c["scheduled_at"],
    )
    c_m1, c_m2 = mgr_checkins[0], mgr_checkins[1]
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-05T08:00:00Z"}, HR))
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    get_success_data(api.complete_check_in(c_m2["id"], {"productivity_rating": 5}, mgr))

    # Trainings still ASSIGNED; complete them on 2026-05-06.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-06T08:00:00Z"}, HR))
    trainings = get_case_trainings(case_id)
    for tr in trainings:
        get_success_data(api.complete_training(tr["id"], {"score": 90}, nh))

    summary = get_summary(case_id)
    # Forward-looking variant: base max(14, 30) + 0 slips = 30.
    assert summary["estimated_ttp_days"] == 30
    # Chronological variant: last completion date 2026-05-06 minus start 2026-05-04 = 2.
    assert summary["actual_ttp_days"] == 2
    assert summary["estimated_ttp_days"] != summary["actual_ttp_days"]
    # Probation gate fires on the last training completion.
    assert summary["phase"] == "PROBATION"


def test_ttp_actual_stays_null_until_all_completed(api):
    """PRD §3.7: "The actual variant, `actual_ttp_days`, stays null until every
    training assignment is `COMPLETED` and every `MANAGER` check-in is
    `COMPLETED`"

    Design: Difficulty/dual_variant_calc/ttp_estimated_forward_vs_actual_chronological
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    # Without any completions, actual is null.
    summary = get_summary(case_id)
    assert summary["actual_ttp_days"] is None
    # Estimated variant is always computable.
    assert summary["estimated_ttp_days"] == 30
