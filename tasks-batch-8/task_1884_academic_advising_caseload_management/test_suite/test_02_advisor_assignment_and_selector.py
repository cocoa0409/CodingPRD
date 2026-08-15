"""Advisor assignment claims: manual create-with-supersede, OCC guard, the
auto-assign selector policy (ranking variants, eligibility, tie-breaks,
capacity boundary) and the load-measure invariants."""
from test_helpers import (
    ApiErrorId,
    assert_assignment,
    auto_assign_payload,
    auto_assign_student,
    create_advisor,
    create_assignment_payload,
    create_manual_assignment,
    create_referral,
    create_student,
    get_advisor,
    get_student,
    set_logical_clock,
    setup_divergent_caseload_pool,
    setup_student_with_two_advisors,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Difficulty: dual_variant_calc / caseload_headcount_vs_weighted_ranking ──

def test_auto_assign_headcount_picks_lowest_headcount(api, director_headers):
    """PRD §3.3: "Under `HEADCOUNT` mode, the primary ranking is the lowest `assigned_active_count`, with ties broken by lower `weighted_load` and then by earlier `created_at`."
    PRD §3.1: "`assigned_active_count` is the number of assignments naming this advisor whose status is `ACTIVE`."

    Design: Difficulty/dual_variant_calc/caseload_headcount_vs_weighted_ranking
    """
    ctx = setup_divergent_caseload_pool()
    # A: headcount 2, load 2. B: headcount 1, load 3 (HIGH-risk advisee).
    res = api.auto_assign(
        auto_assign_payload(ctx["s4"]["id"], ranking_mode="HEADCOUNT"),
        director_headers,
    )
    assignment = validate_success(res, 201)
    assert_assignment(assignment)
    assert assignment["advisor_id"] == ctx["advisor_b"]["id"], (
        "HEADCOUNT: B has headcount 1 < A's 2, so B must win"
    )
    assert assignment["assignment_mode"] == "AUTO"


def test_auto_assign_weighted_picks_lowest_weighted_load(api, director_headers):
    """PRD §3.3: "Under the default `WEIGHTED` mode, the winner is the candidate with the lowest `weighted_load`, with ties broken by lower `assigned_active_count` and then by earlier `created_at`."
    PRD §3.1: "`weighted_load` sums, over those same active assignments, a per-student risk weight: 1 for a `LOW`-tier student, 2 for `MEDIUM`, and 3 for `HIGH`."

    Design: Difficulty/dual_variant_calc/caseload_headcount_vs_weighted_ranking
    """
    ctx = setup_divergent_caseload_pool()
    headcount_res = api.auto_assign(
        auto_assign_payload(ctx["s4"]["id"], ranking_mode="HEADCOUNT"),
        director_headers,
    )
    headcount_assignment = validate_success(headcount_res, 201)
    # After s4 (LOW, weight 1) joins B: A load 2 < B load 3 + 1 = 4.
    weighted_res = api.auto_assign(
        auto_assign_payload(ctx["s5"]["id"], ranking_mode="WEIGHTED"),
        director_headers,
    )
    weighted_assignment = validate_success(weighted_res, 201)
    assert weighted_assignment["advisor_id"] == ctx["advisor_a"]["id"], (
        "WEIGHTED: A weighted_load 2 < B weighted_load 4 after s4 joins B"
    )
    assert weighted_assignment["advisor_id"] != headcount_assignment["advisor_id"], (
        "same pool, two ranking variants, different winners"
    )


# ─── Difficulty: boundary_precision_check / advisor_capacity_at_max_excluded ──

def test_auto_assign_admits_advisor_below_capacity(api, director_headers):
    """PRD §3.3: "The candidate pool contains exactly those advisors who are `ACTIVE`, serve the student's major, and have headroom; an empty pool is rejected with `ERR_NO_ELIGIBLE_ADVISOR` (HTTP 422, distinct from the 409s surrounding it)."
    PRD §3.3: "the advisor must have headroom, meaning `assigned_active_count` strictly below `max_caseload`."

    Design: Difficulty/boundary_precision_check/advisor_capacity_at_max_excluded
    """
    advisor = create_advisor(full_name="Advisor B1", email="b1@x.edu", max_caseload=1)
    s1 = create_student(full_name="BS1", email="bs1@x.edu")
    # count 0 < max 1 -> the advisor is eligible and must be selected.
    assignment = auto_assign_student(s1["id"])
    assert_assignment(assignment)
    assert assignment["advisor_id"] == advisor["id"]
    advisor_after = get_advisor(advisor["id"])
    assert advisor_after["assigned_active_count"] == 1


def test_auto_assign_empty_pool_when_advisor_at_capacity(api, director_headers):
    """PRD §3.3: "An advisor whose count already equals the cap is at capacity, and the creation is rejected with `ERR_ADVISOR_AT_CAPACITY`."
    PRD §3.3: "The candidate pool contains exactly those advisors who are `ACTIVE`, serve the student's major, and have headroom; an empty pool is rejected with `ERR_NO_ELIGIBLE_ADVISOR` (HTTP 422, distinct from the 409s surrounding it)."

    Design: Difficulty/boundary_precision_check/advisor_capacity_at_max_excluded
    """
    advisor = create_advisor(full_name="Advisor B1", email="b1@x.edu", max_caseload=1)
    s1 = create_student(full_name="BS1", email="bs1@x.edu")
    auto_assign_student(s1["id"])  # count 1 == max 1 -> at capacity
    s2 = create_student(full_name="BS2", email="bs2@x.edu")
    res = api.auto_assign(auto_assign_payload(s2["id"]), director_headers)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_ADVISOR)
    assert get_advisor(advisor["id"])["assigned_active_count"] == 1, (
        "a rejected auto-assign must not move the advisor's count"
    )


# ─── Difficulty: compensating_invariant / assign_end_conserve_advisor_count ──

def test_assign_then_end_conserves_load_measures(api, director_headers):
    """PRD §3.3: "A successful ending sets the status to `ENDED` with `ended_reason` set to `MANUAL_END`, recomputes the advisor's two load measures, and increments the student's `version` by 1."
    PRD §3.1: "A freshly created advisor starts with `status` set to `ACTIVE` and all three load measures at zero."

    Design: Difficulty/compensating_invariant/assign_end_conserve_advisor_count
    """
    advisor = create_advisor(full_name="Advisor I1", email="i1@x.edu")
    student = create_student(full_name="I1", email="i1s@x.edu")
    pre = get_advisor(advisor["id"])
    assert pre["assigned_active_count"] == 0
    assert pre["weighted_load"] == 0

    assignment = create_manual_assignment(student["id"], advisor["id"])
    validate_success(api.end_assignment(assignment["id"], director_headers), 200)

    post = get_advisor(advisor["id"])
    assert post["assigned_active_count"] == 0, (
        "forward + compensating action must conserve the count at zero drift"
    )
    assert post["weighted_load"] == 0


def test_ended_assignment_leaves_no_active_rows(api, director_headers):
    """PRD §3.3: "Assignment history — active and ended alike — can be browsed with `student_id`, `advisor_id`, and `status` filters."
    PRD §3.3: "A successful ending sets the status to `ENDED` with `ended_reason` set to `MANUAL_END`, recomputes the advisor's two load measures, and increments the student's `version` by 1."

    Design: Difficulty/compensating_invariant/assign_end_conserve_advisor_count
    """
    advisor = create_advisor(full_name="Advisor I1", email="i1@x.edu")
    student = create_student(full_name="I1", email="i1s@x.edu")
    assignment = create_manual_assignment(student["id"], advisor["id"])
    validate_success(api.end_assignment(assignment["id"], director_headers), 200)

    active, active_meta = validate_paginated(
        api.list_assignments(
            director_headers,
            params={"advisor_id": advisor["id"], "status": "ACTIVE"},
        )
    )
    assert active_meta["total_count"] == 0, (
        "after the end, no ACTIVE assignment may remain for the advisor"
    )
    ended, ended_meta = validate_paginated(
        api.list_assignments(
            director_headers,
            params={"advisor_id": advisor["id"], "status": "ENDED"},
        )
    )
    assert ended_meta["total_count"] == 1
    assert ended[0]["ended_reason"] == "MANUAL_END"


# ─── Corner: state_machines / assignment_supersede_ends_prior ────────────────

def test_assignment_supersede_ends_prior(api, director_headers):
    """PRD §3.3: "If the student already has an `ACTIVE` assignment, that incumbent is ended as part of the same operation — its status becomes `ENDED` with `ended_reason` set to `SUPERSEDED` — and the new assignment begins `ACTIVE` with `assignment_mode` recording `MANUAL`."
    PRD §3.3: "Both affected advisors have `assigned_active_count` and `weighted_load` recomputed, and the student's `version` increments by 1: the superseding creation is precisely the event the optimistic-concurrency guard protects later writers against."

    Design: Corner/state_machines/assignment_supersede_ends_prior
    """
    advisor_a = create_advisor(full_name="Advisor SA", email="sa@x.edu")
    advisor_b = create_advisor(full_name="Advisor SB", email="sb@x.edu")
    student = create_student(full_name="S7", email="s7c@x.edu")
    create_manual_assignment(student["id"], advisor_a["id"])
    create_manual_assignment(student["id"], advisor_b["id"])

    ended, ended_meta = validate_paginated(
        api.list_assignments(
            director_headers,
            params={"student_id": student["id"], "status": "ENDED"},
        )
    )
    assert ended_meta["total_count"] == 1
    assert ended[0]["ended_reason"] == "SUPERSEDED"
    assert ended[0]["advisor_id"] == advisor_a["id"]
    assert get_advisor(advisor_b["id"])["assigned_active_count"] == 1


# ─── Corner: cross_cutting_layers / occ_stale_version_on_assignment_create_rejected

def test_occ_stale_version_on_assignment_create_rejected(api, director_headers):
    """PRD §2.9: "If the value does not match the student's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a view of the student that another writer has already advanced."
    PRD §2.9: "A student's `version` advances on every student update and on every assignment creation, auto-assignment, or assignment ending for that student, so a client that read the student before such an event holds a stale version and will be stopped."
    PRD §3.3: "the student's `version` increments by 1: the superseding creation is precisely the event the optimistic-concurrency guard protects later writers against."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_assignment_create_rejected
    """
    advisor_a = create_advisor(full_name="Advisor OA", email="oa@x.edu")
    advisor_b = create_advisor(full_name="Advisor OB", email="ob@x.edu")
    student = create_student(full_name="OC1", email="oc1@x.edu")
    observed_version = student["version"]

    first = api.create_assignment(
        create_assignment_payload(student["id"], advisor_a["id"], observed_version),
        director_headers,
    )
    validate_success(first, 201)

    stale = api.create_assignment(
        create_assignment_payload(student["id"], advisor_b["id"], observed_version),
        director_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert get_student(student["id"])["version"] == observed_version + 1, (
        "exactly one version bump from the single successful assignment creation"
    )


# ─── Corner: cross_cutting_layers / auto_assign_tie_break_uses_created_at ────

def test_auto_assign_tie_break_uses_created_at(api, director_headers):
    """PRD §3.3: "Under the default `WEIGHTED` mode, the winner is the candidate with the lowest `weighted_load`, with ties broken by lower `assigned_active_count` and then by earlier `created_at`."
    PRD §3.3: "The chosen advisor receives a new `ACTIVE` assignment with `assignment_mode` set to `AUTO`; the same supersede discipline applies to any incumbent, the same load recomputations fire, and the student's `version` increments by 1."

    Design: Corner/cross_cutting_layers/auto_assign_tie_break_uses_created_at
    """
    advisor_a = create_advisor(full_name="Advisor TA", email="ta@x.edu")
    # Advance the logical clock (PRD §2.4) between creations so the two
    # advisors carry strictly ordered created_at stamps; otherwise both share
    # the frozen default instant and the PRD tie-break cannot rank them.
    set_logical_clock("2026-08-01T00:00:01Z")
    create_advisor(full_name="Advisor TB", email="tb@x.edu")
    student = create_student(full_name="TB1", email="tb1@x.edu")
    # Both advisors: load 0, count 0 -> tie broken by earlier created_at.
    assignment = auto_assign_student(student["id"])
    assert assignment["advisor_id"] == advisor_a["id"], (
        "identical load and headcount -> the earlier-created advisor must win"
    )
    assert assignment["assignment_mode"] == "AUTO"


# ─── Corner: cross_cutting_layers / auto_assign_eligibility_excludes_mismatch ──

def test_auto_assign_eligibility_excludes_mismatch(api, director_headers):
    """PRD §3.3: "The candidate pool contains exactly those advisors who are `ACTIVE`, serve the student's major, and have headroom; an empty pool is rejected with `ERR_NO_ELIGIBLE_ADVISOR` (HTTP 422, distinct from the 409s surrounding it)."

    Design: Corner/cross_cutting_layers/auto_assign_eligibility_excludes_mismatch
    """
    create_advisor(full_name="Advisor TE", email="te@x.edu", major_codes=("BIO",))
    student = create_student(full_name="TE1", email="te1@x.edu", major_code="CS")
    res = api.auto_assign(auto_assign_payload(student["id"]), director_headers)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_ADVISOR)


# ─── Corner: calculations / weighted_load_recomputes_on_tier_flip ────────────

def test_weighted_load_recomputes_on_tier_flip(api, director_headers):
    """PRD §3.1: "`weighted_load` sums, over those same active assignments, a per-student risk weight: 1 for a `LOW`-tier student, 2 for `MEDIUM`, and 3 for `HIGH`."
    PRD §2.7: "No read ever returns a stale derived value, and no client ever needs to poll for a cascade to settle."
    PRD §3.6: "Intake immediately recomputes the student's `at_risk_score` and `risk_tier`, because the new referral's severity boost joins the pool described in §3.2."

    Design: Corner/calculations/weighted_load_recomputes_on_tier_flip
    """
    student, advisor_a, _advisor_b = setup_student_with_two_advisors(gpa=2.4)
    assert get_advisor(advisor_a["id"])["weighted_load"] == 1, (
        "gpa 2.4 -> base 25 -> LOW tier -> weight 1"
    )
    create_referral(student["id"], severity="HIGH", reason="failing")
    after = get_advisor(advisor_a["id"])
    assert after["weighted_load"] == 2, (
        "25 + 20 HIGH referral = 45 -> MEDIUM tier -> weight 2, no assignment change"
    )
    student_after = get_student(student["id"])
    assert student_after["at_risk_score"] == 45
    assert student_after["risk_tier"] == "MEDIUM"
