"""The two cascade chains, the readiness variants and immediate consistency."""

from test_helpers import (
    TEST_USERS,
    assert_hours,
    assert_score,
    create_exercise,
    read_activation,
    read_assignment,
    read_cohort,
    read_completion,
    read_credential,
    read_program,
    read_session,
    read_trainee,
    record_completion,
    register_participation,
    run_exercise_to_credit,
    set_clock,
    setup_credentialed_trainees,
    setup_passed_core_trainees,
    setup_rostered_activation,
    setup_session_a_delivered,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Chain A: voiding a passed core completion
# ---------------------------------------------------------------------------

def test_voiding_a_passed_core_completion_demotes_the_graduate_and_suspends_the_card(api):
    """PRD §3.4: "Voiding from `PASSED` fires cascade chain A, six links deep. The
    completion's `credited_contact_hours` drops to 0. Because of that, the trainee's
    `earned_contact_hours` falls by the hours just withdrawn, their `passed_core_count` falls
    by 1 when the module is core, their `readiness_score` is recomputed, and — when that
    leaves `passed_core_count` below the count of curriculum modules that are both core and
    active while the trainee stands at `GRADUATED` — the trainee is demoted `GRADUATED →
    ENROLLED`. Because of that demotion, the trainee's credential, if it stands at `ACTIVE`,
    moves `ACTIVE → SUSPENDED` and their `currency_status` moves `CURRENT → LAPSED`."

    Design: Difficulty/transitive_cascade/void_passed_core_completion_cascades_through_credential_to_activation_fill
    """
    ctx = setup_rostered_activation(severity="ROUTINE", requested_responders=1)
    completion = ctx["completions"]["tara_a"]

    voided = validate_success(
        api.void_module_completion(
            completion["id"], {"reason": "Attendance sheet was mis-keyed"}, COORD
        )
    )
    assert voided["status"] == "VOIDED"
    assert_hours(voided["credited_contact_hours"], 0.0, "credited_contact_hours")

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 7.5, "earned_contact_hours")
    assert trainee["passed_core_count"] == 2
    assert trainee["enrollment_status"] == "ENROLLED", "the graduate is demoted"
    assert trainee["currency_status"] == "LAPSED"

    assert read_credential(ctx, "tara")["status"] == "SUSPENDED"


def test_the_same_void_pulls_the_volunteer_off_the_roster_and_reopens_review(api):
    """PRD §3.4: "Because of that suspension, every roster assignment of that trainee
    standing at `NOTIFIED` or `ACCEPTED` whose activation stands at `REQUESTED`, `ROSTERED`,
    or `ACTIVATED` moves to `WITHDRAWN`. Because of those withdrawals, each affected
    activation recomputes `rostered_count`, `accepted_count`, `deployed_count`, and
    `fill_status`, so an activation that had been `FILLED` may fall back to `PARTIAL` or even
    `UNFILLED`. And separately caused by the same demotion, a cohort sitting in
    `GRADUATION_REVIEW` reverts to `IN_SESSION` and the program's `pending_graduation_count`
    falls by 1."
    PRD §3.2: "On that revert, `graduation_reviewer_user_id` is cleared to null and the
    program's `pending_graduation_count` is decreased by 1."

    Design: Difficulty/transitive_cascade/void_passed_core_completion_cascades_through_credential_to_activation_fill
    """
    ctx = setup_rostered_activation(severity="ROUTINE", requested_responders=1)
    assignment = ctx["assignments"]["tara"]
    assert read_activation(ctx)["fill_status"] == "FILLED"
    assert read_program(ctx)["pending_graduation_count"] == 1

    validate_success(
        api.void_module_completion(
            ctx["completions"]["tara_a"]["id"],
            {"reason": "Attendance sheet was mis-keyed"}, COORD,
        )
    )

    assert read_assignment(ctx, assignment)["status"] == "WITHDRAWN"
    activation = read_activation(ctx)
    assert activation["rostered_count"] == 0
    assert activation["accepted_count"] == 0
    assert activation["fill_status"] == "UNFILLED"
    assert activation["status"] == "ROSTERED"

    cohort = read_cohort(ctx)
    assert cohort["status"] == "IN_SESSION"
    assert cohort["graduation_reviewer_user_id"] is None
    assert read_program(ctx)["pending_graduation_count"] == 0


# ---------------------------------------------------------------------------
# Chain B: cancelling a delivered class session
# ---------------------------------------------------------------------------

def test_cancelling_a_delivered_session_voids_its_completions_and_rewrites_the_ledger(api):
    """PRD §3.3: "Cancelling a session that has already been `DELIVERED` fires cascade chain
    B in full: first the cohort's `delivered_contact_hours` is reduced by that module's
    `contact_hours`; because the session's delivery is thereby invalidated, every completion
    recorded against it standing at `RECORDED`, `SKILLS_PENDING`, `PASSED`, or `FAILED` is
    moved to `VOIDED`; because those completions are gone, each affected trainee's
    `earned_contact_hours`, `passed_core_count`, `last_qualifying_activity_at`, and
    `readiness_score` are recomputed; because those recomputations may leave a core active
    module with no delivered session on a cohort sitting in graduation review, that cohort
    reverts to `IN_SESSION` with `graduation_reviewer_user_id` cleared to null; and because
    the cohort left review, the program's `pending_graduation_count` is reduced by 1."

    Design: Difficulty/transitive_cascade/cancel_delivered_session_cascades_to_cohort_review_revert
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    assert read_cohort(ctx)["delivered_contact_hours"] == 10.0

    cancelled = validate_success(
        api.cancel_class_session(
            ctx["session_a"]["id"],
            {"reason": "Instructor no-show discovered in audit"}, COORD,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert read_cohort(ctx)["delivered_contact_hours"] == 7.5

    completion = read_completion(ctx, "tara_a")
    assert completion["status"] == "VOIDED"
    assert_hours(completion["credited_contact_hours"], 0.0, "credited_contact_hours")

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 7.5, "earned_contact_hours")
    assert trainee["passed_core_count"] == 2
    assert trainee["enrollment_status"] == "ENROLLED"


def test_the_cancellation_reverts_the_cohort_and_leaves_untouched_sessions_alone(api):
    """PRD §3.2: "The system takes it automatically whenever a voided completion or a
    cancelled session leaves a core active module without a delivered session on the cohort,
    or drops any graduated trainee of that cohort back to enrolled. On that revert,
    `graduation_reviewer_user_id` is cleared to null and the program's
    `pending_graduation_count` is decreased by 1."
    PRD §3.4: "Because of that demotion, the trainee's credential, if it stands at `ACTIVE`,
    moves `ACTIVE → SUSPENDED` and their `currency_status` moves `CURRENT → LAPSED`."

    Design: Difficulty/transitive_cascade/cancel_delivered_session_cascades_to_cohort_review_revert
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    assert read_program(ctx)["pending_graduation_count"] == 1

    validate_success(
        api.cancel_class_session(
            ctx["session_a"]["id"],
            {"reason": "Instructor no-show discovered in audit"}, COORD,
        )
    )

    cohort = read_cohort(ctx)
    assert cohort["status"] == "IN_SESSION"
    assert cohort["graduation_reviewer_user_id"] is None
    assert read_program(ctx)["pending_graduation_count"] == 0

    assert read_credential(ctx, "tara")["status"] == "SUSPENDED"
    assert read_trainee(ctx, "tara")["currency_status"] == "LAPSED"

    assert read_completion(ctx, "tara_b")["status"] == "PASSED", (
        "only completions of the cancelled session are voided"
    )
    assert read_completion(ctx, "tara_c")["status"] == "PASSED"
    assert read_session(ctx, "session_b")["status"] == "DELIVERED"


# ---------------------------------------------------------------------------
# The two readiness variants
# ---------------------------------------------------------------------------

def test_the_readiness_read_exposes_both_variants_component_by_component(api):
    """PRD §3.9: "The **certified** variant counts, as earned core hours, only completions
    standing at `PASSED` on core modules, and its demonstration set is the `demo_score` of
    completions standing at `PASSED` whose module has `requires_skills_demo` true."
    PRD §3.9: "The **provisional** variant is never persisted: on top of everything the
    certified variant counts, it also credits completions standing at `SKILLS_PENDING` on core
    modules with **half** of their module's `contact_hours` toward earned core hours, and
    enters each of them into the demonstration set with an imputed score of 70."
    PRD §3.9: "A dedicated computed read exposes the two side by side, returning
    `certified_readiness_score`, `provisional_readiness_score`, `core_hours_total`,
    `core_hours_earned_certified`, `core_hours_earned_provisional`, `core_ratio_certified`,
    `core_ratio_provisional`, `demo_avg_certified`, `demo_avg_provisional`, `recency_factor`,
    and `exercise_bonus`."

    Design: Difficulty/dual_variant_calc/readiness_certified_vs_provisional_diverge_on_pending_demo
    """
    ctx = setup_passed_core_trainees(sign_c=False)
    readiness = validate_success(
        api.get_trainee_readiness(ctx["trainees"]["tara"]["id"], COORD)
    )

    assert_hours(readiness["core_hours_total"], 10.0, "core_hours_total")
    assert_hours(readiness["core_hours_earned_certified"], 5.0,
                 "core_hours_earned_certified")
    assert_hours(readiness["core_hours_earned_provisional"], 7.5,
                 "core_hours_earned_provisional")
    assert_score(readiness["core_ratio_certified"], 0.5, "core_ratio_certified")
    assert_score(readiness["core_ratio_provisional"], 0.75, "core_ratio_provisional")
    assert_score(readiness["demo_avg_certified"], 88.0, "demo_avg_certified")
    assert_score(readiness["demo_avg_provisional"], 79.0, "demo_avg_provisional")
    assert_score(readiness["recency_factor"], 1.0, "recency_factor")
    assert_score(readiness["exercise_bonus"], 0.0, "exercise_bonus")


def test_only_the_certified_variant_is_ever_written_to_the_trainee(api):
    """PRD §3.9: "Identical stored data therefore yields a strictly higher provisional figure
    than certified figure whenever any pending completion exists, which is exactly what a
    coordinator wants to see on a graduation-review dashboard."
    PRD §3.9: "This is the only variant ever written to the trainee's stored
    `readiness_score`, and it is the variant the roster selector ranks on."
    PRD §3.4: "The evaluator fields `evaluator_id` and `demo_score` start null,
    `attempt_number` starts at 1, and `credited_contact_hours` starts at 0."

    Design: Difficulty/dual_variant_calc/readiness_certified_vs_provisional_diverge_on_pending_demo
    """
    ctx = setup_passed_core_trainees(sign_c=False)
    readiness = validate_success(
        api.get_trainee_readiness(ctx["trainees"]["tara"]["id"], COORD)
    )

    assert_score(readiness["certified_readiness_score"], 65.20,
                 "certified_readiness_score")
    assert_score(readiness["provisional_readiness_score"], 76.60,
                 "provisional_readiness_score")
    assert readiness["provisional_readiness_score"] > readiness["certified_readiness_score"]

    assert_score(read_trainee(ctx, "tara")["readiness_score"], 65.20,
                 "stored readiness_score")

    pending = read_completion(ctx, "tara_c")
    assert pending["status"] == "SKILLS_PENDING"
    assert_hours(pending["credited_contact_hours"], 0.0, "credited_contact_hours")


def test_the_readiness_clamp_binds_at_a_hundred_points(api):
    """PRD §3.9: "Sixth, the exercise bonus is 2.5 points for each of that volunteer's
    exercise participations standing at `CREDITED`, capped at 10.0 points — four credited
    exercises reach the cap and a fifth adds nothing."
    PRD §3.9: "Ninth and last, the score is that raw figure clamped to no less than 0.00 and
    no more than 100.00, and rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/readiness_min_max_caps_interact_with_recency_tier
    """
    ctx = setup_passed_core_trainees(demo_scores={"tara": (100, 100)})
    create_exercise(ctx, "drill1", title="Drill 1", base_credit_hours=2.0,
                    starts_at="2026-08-06T08:00:00Z", ends_at="2026-08-06T09:00:00Z")
    register_participation(ctx, "drill1", "tara", role_played="LOGISTICS",
                           store_as="p1")
    run_exercise_to_credit(ctx, "drill1", accept_at="2026-08-06T10:00:00Z")

    readiness = validate_success(
        api.get_trainee_readiness(ctx["trainees"]["tara"]["id"], COORD)
    )
    assert_score(readiness["core_ratio_certified"], 1.0, "core_ratio_certified")
    assert_score(readiness["demo_avg_certified"], 100.0, "demo_avg_certified")
    assert_score(readiness["recency_factor"], 1.0, "recency_factor")
    assert_score(readiness["exercise_bonus"], 2.5, "exercise_bonus")
    assert_score(readiness["certified_readiness_score"], 100.00,
                 "certified_readiness_score")


def test_the_clamp_stops_binding_once_the_recency_tier_drops(api):
    """PRD §3.9: "Fifth, the recency factor is derived from the whole number of days between
    the volunteer's `last_qualifying_activity_at` and the logical clock: 1.00 when that gap is
    90 days or fewer, 0.90 when it is more than 90 but no more than 180, 0.75 when it is more
    than 180 but no more than 365, 0.50 when it exceeds 365, and 0.50 when
    `last_qualifying_activity_at` is null because the volunteer has never had a qualifying
    activity at all."
    PRD §3.9: "Eighth, the raw figure is the base multiplied by the recency factor, with the
    exercise bonus then added."

    Design: Difficulty/combinatorial_formula/readiness_min_max_caps_interact_with_recency_tier
    """
    ctx = setup_passed_core_trainees(demo_scores={"tara": (100, 100)})
    create_exercise(ctx, "drill1", title="Drill 1", base_credit_hours=2.0,
                    starts_at="2026-08-06T08:00:00Z", ends_at="2026-08-06T09:00:00Z")
    register_participation(ctx, "drill1", "tara", role_played="LOGISTICS",
                           store_as="p1")
    run_exercise_to_credit(ctx, "drill1", accept_at="2026-08-06T10:00:00Z")

    participation = validate_success(
        api.get_exercise_participation(ctx["participations"]["p1"]["id"], AUDITOR)
    )
    assert participation["status"] == "CREDITED"
    assert_hours(participation["hours_credited"], 2.0, "hours_credited")

    set_clock("2026-11-05T10:00:00Z")
    readiness = validate_success(
        api.get_trainee_readiness(ctx["trainees"]["tara"]["id"], COORD)
    )
    assert_score(readiness["recency_factor"], 0.90, "recency_factor")
    assert_score(readiness["certified_readiness_score"], 92.50,
                 "certified_readiness_score")


def test_the_recency_factor_steps_at_each_declared_tier_boundary(api):
    """PRD §3.9: "Fifth, the recency factor is derived from the whole number of days between
    the volunteer's `last_qualifying_activity_at` and the logical clock: 1.00 when that gap is
    90 days or fewer, 0.90 when it is more than 90 but no more than 180, 0.75 when it is more
    than 180 but no more than 365, 0.50 when it exceeds 365, and 0.50 when
    `last_qualifying_activity_at` is null because the volunteer has never had a qualifying
    activity at all."
    PRD §3.9: "Seventh, the base is 60.0 multiplied by the core ratio plus 40.0 multiplied by
    the demonstration average divided by 100.0."

    Design: Corner/calculations/readiness_recency_factor_steps_at_each_declared_tier_boundary
    """
    ctx = setup_passed_core_trainees()
    trainee_id = ctx["trainees"]["tara"]["id"]

    expectations = [
        ("2026-11-03T15:00:00Z", 1.00, 96.00),
        ("2026-11-04T15:00:00Z", 0.90, 86.40),
        ("2027-02-01T15:00:00Z", 0.90, 86.40),
        ("2027-02-02T15:00:00Z", 0.75, 72.00),
        ("2027-08-05T15:00:00Z", 0.75, 72.00),
        ("2027-08-06T15:00:00Z", 0.50, 48.00),
    ]
    for instant, factor, score in expectations:
        set_clock(instant)
        readiness = validate_success(api.get_trainee_readiness(trainee_id, AUDITOR))
        assert_score(readiness["recency_factor"], factor, f"recency_factor at {instant}")
        assert_score(readiness["certified_readiness_score"], score,
                     f"certified_readiness_score at {instant}")


# ---------------------------------------------------------------------------
# Immediate consistency
# ---------------------------------------------------------------------------

def test_a_cascade_is_fully_settled_in_the_very_next_read(api):
    """PRD §2.10: "Every row touched anywhere in such a chain has its `updated_at` refreshed
    and its `version` incremented, exactly as if it had been modified directly. A cascade is
    not a silent write."
    PRD §3.3: "Cancelling a session that has already been `DELIVERED` fires cascade chain B
    in full: first the cohort's `delivered_contact_hours` is reduced by that module's
    `contact_hours`; because the session's delivery is thereby invalidated, every completion
    recorded against it standing at `RECORDED`, `SKILLS_PENDING`, `PASSED`, or `FAILED` is
    moved to `VOIDED`; because those completions are gone, each affected trainee's
    `earned_contact_hours`, `passed_core_count`, `last_qualifying_activity_at`, and
    `readiness_score` are recomputed; because those recomputations may leave a core active
    module with no delivered session on a cohort sitting in graduation review, that cohort
    reverts to `IN_SESSION` with `graduation_reviewer_user_id` cleared to null; and because
    the cohort left review, the program's `pending_graduation_count` is reduced by 1."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response
    """
    ctx = setup_session_a_delivered()
    record_completion(ctx, "tara", "session_a", 150, store_as="tara_a")

    cancelled = validate_success(
        api.cancel_class_session(ctx["session_a"]["id"], {"reason": "Audit finding"}, COORD)
    )
    assert cancelled["status"] == "CANCELLED", (
        "the cancel response body itself already reports the new status"
    )

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 0.0, "earned_contact_hours")
    assert trainee["passed_core_count"] == 0

    assert read_cohort(ctx)["delivered_contact_hours"] == 0

    rows, meta = validate_paginated(
        api.list_module_completions(
            AUDITOR, {"class_session_id": ctx["session_a"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "VOIDED"
