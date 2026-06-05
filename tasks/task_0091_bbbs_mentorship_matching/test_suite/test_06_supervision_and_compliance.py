"""Monthly supervision, activity aggregation, and the derived compliance posture.

Queue-A dual_variant_calc / combinatorial_formula / boundary_precision plus
queue-B aggregation and not-active corners.
"""
from test_helpers import (
    validate_success,
    fixtures as fx,
)

SUPERVISOR = fx.SUPERVISOR


def test_total_mentoring_minutes_aggregates_logged_activities(api):
    """PRD §3.6: "Appending an entry recomputes the match's
    `total_mentoring_minutes` as the sum of `duration_minutes` over the match's
    `LOGGED` activity entries".

    Design: Corner/calculations/total_mentoring_minutes_aggregation
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Tm"},
        guardian_overrides={"full_name": "G Tm"},
        child_overrides={"first_name": "Tm"},
    )
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    fx.log_activity(match_id, "2026-01-10T10:00:00Z", 60, "CALL", specialist_headers=spec)
    fx.log_activity(match_id, "2026-01-12T10:00:00Z", 90, "OUTING", specialist_headers=spec)
    match = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert match["total_mentoring_minutes"] == 150


def test_compliance_amber_contact_day_boundary_strict_gt(api):
    """PRD §3.6: "the posture is `AMBER` if the days since contact exceed 30 ...
    Each threshold comparison is strict — exactly 60 days since contact, for
    instance, is not yet `RED`."

    Design: Difficulty/boundary_precision_check/compliance_amber_contact_day_boundary_strict_gt
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Bd", "home_zip": "55401",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Bd"},
        child_overrides={"first_name": "Leo", "age": 11, "home_zip": "55401",
                         "interest_tags": ["STEM"]},
    )
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    # Anchor both activity and the completed contact at 2026-01-30.
    fx.log_activity(match_id, "2026-01-30T00:00:00Z", 60, "MEAL", specialist_headers=spec)
    sc_id = fx.first_open_contact_id(match_id)
    fx.complete_contact(sc_id, "2026-01-30T00:00:00Z", "BIG")
    # Exactly 30 days later → GREEN (strict >).
    fx.set_clock("2026-03-01T00:00:00Z")
    at30 = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert at30["compliance_status"] == "GREEN"
    # 31 days → AMBER.
    fx.set_clock("2026-03-02T00:00:00Z")
    at31 = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert at31["compliance_status"] == "AMBER"


def test_compliance_green_below_amber_contact_boundary(api):
    """PRD §3.6: "the posture is `AMBER` if the days since contact exceed 30 ...
    Otherwise the posture is `GREEN`. Each threshold comparison is strict".

    Design: Difficulty/boundary_precision_check/compliance_amber_contact_day_boundary_strict_gt
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Bd2", "home_zip": "55401",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Bd2"},
        child_overrides={"first_name": "Leo2", "age": 11, "home_zip": "55401",
                         "interest_tags": ["STEM"]},
    )
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    fx.log_activity(match_id, "2026-01-30T00:00:00Z", 60, "MEAL", specialist_headers=spec)
    sc_id = fx.first_open_contact_id(match_id)
    fx.complete_contact(sc_id, "2026-01-30T00:00:00Z", "BIG")
    # 29 days after the contact (below the 30-day threshold) → GREEN.
    fx.set_clock("2026-02-28T00:00:00Z")
    at29 = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert at29["compliance_status"] == "GREEN"


def test_compliance_amber_from_stale_activity_despite_fresh_contact(api):
    """PRD §3.6: "the posture is `AMBER` if the days since contact exceed 30, or
    the days since activity exceed 45."

    Design: Difficulty/dual_variant_calc/compliance_contact_driven_vs_activity_driven_on_match
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Act", "gender": "FEMALE",
                             "home_zip": "30303", "interest_tags": ["ARTS"]},
        guardian_overrides={"full_name": "G Act"},
        child_overrides={"first_name": "Mia", "age": 9, "gender": "FEMALE",
                         "home_zip": "30303", "interest_tags": ["ARTS"]},
    )
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    # Latest activity 50 days before the read; latest completed contact 15 days before.
    fx.log_activity(match_id, "2026-02-10T00:00:00Z", 90, "OUTING", specialist_headers=spec)
    sc_id = fx.first_open_contact_id(match_id)
    fx.complete_contact(sc_id, "2026-03-17T00:00:00Z", "BIG")
    fx.set_clock("2026-04-01T00:00:00Z")
    match = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert match["compliance_status"] == "AMBER"
    assert match["last_activity_at"] is not None
    assert match["last_contact_at"] is not None


def test_fresh_contact_and_activity_keep_compliance_green(api):
    """PRD §3.6: "Failing that, the posture is `AMBER` if the days since contact
    exceed 30, or the days since activity exceed 45. Otherwise the posture is
    `GREEN`."

    Design: Difficulty/dual_variant_calc/compliance_contact_driven_vs_activity_driven_on_match
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Act2", "gender": "FEMALE",
                             "home_zip": "30303", "interest_tags": ["ARTS"]},
        guardian_overrides={"full_name": "G Act2"},
        child_overrides={"first_name": "Mia2", "age": 9, "gender": "FEMALE",
                         "home_zip": "30303", "interest_tags": ["ARTS"]},
    )
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    # Both activity and contact recent (within both thresholds) → GREEN.
    fx.log_activity(match_id, "2026-03-20T00:00:00Z", 90, "OUTING", specialist_headers=spec)
    sc_id = fx.first_open_contact_id(match_id)
    fx.complete_contact(sc_id, "2026-03-25T00:00:00Z", "BIG")
    fx.set_clock("2026-04-01T00:00:00Z")
    match = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    # days_since_contact 7 <= 30, days_since_activity 12 <= 45 → GREEN.
    assert match["compliance_status"] == "GREEN"


def test_compliance_recompute_then_evaluate_on_completion(api):
    """PRD §3.6: "Completion moves the follow-up `OPEN → COMPLETED`, sets its
    `contacted_at` ... it then recomputes the match's `compliance_status` and
    refreshes the match's `last_contact_at` to that `contacted_at`."
    PRD §3.6: "The posture is `RED` if the days since contact exceed 60".

    Design: Difficulty/combinatorial_formula/compliance_eval_order_pinned_mode_c
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Eval", "gender": "FEMALE",
                             "home_zip": "44114", "interest_tags": ["MUSIC"],
                             "max_weekly_hours": 6},
        guardian_overrides={"full_name": "G Eval"},
        child_overrides={"first_name": "Ava", "age": 8, "gender": "FEMALE",
                         "home_zip": "44114", "interest_tags": ["MUSIC"]},
    )
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    fx.log_activity(match_id, "2026-01-25T10:00:00Z", 60, "CALL", specialist_headers=spec)
    sc_id = fx.first_open_contact_id(match_id)
    # Day ~63 since activation (2026-01-02) with the first contact still OPEN → RED.
    fx.set_clock("2026-03-05T00:00:00Z")
    pre = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert pre["compliance_status"] == "RED"
    # Completing the contact recomputes last_contact_at, then evaluates → GREEN.
    fx.complete_contact(sc_id, "2026-03-05T00:00:00Z", "BIG")
    post = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert post["compliance_status"] == "GREEN"
    assert post["last_contact_at"] is not None


def test_completion_recomputes_last_contact_at_to_recorded_instant(api):
    """PRD §3.6: "it then recomputes the match's `compliance_status` and refreshes
    the match's `last_contact_at` to that `contacted_at`."

    Design: Difficulty/combinatorial_formula/compliance_eval_order_pinned_mode_c
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Eval2", "gender": "FEMALE",
                             "home_zip": "44114", "interest_tags": ["MUSIC"],
                             "max_weekly_hours": 6},
        guardian_overrides={"full_name": "G Eval2"},
        child_overrides={"first_name": "Ava2", "age": 8, "gender": "FEMALE",
                         "home_zip": "44114", "interest_tags": ["MUSIC"]},
    )
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    fx.log_activity(match_id, "2026-01-25T10:00:00Z", 60, "CALL", specialist_headers=spec)
    sc_id = fx.first_open_contact_id(match_id)
    fx.set_clock("2026-03-05T00:00:00Z")
    completed = fx.complete_contact(sc_id, "2026-03-05T00:00:00Z", "BIG")
    assert completed["status"] == "COMPLETED"
    match = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert match["last_contact_at"] == "2026-03-05T00:00:00Z" or \
        match["last_contact_at"].startswith("2026-03-05T00:00:00")
