"""Registration holds, degree plans and registration clearance: release gates
and cascades, the plan revision cycle, pinned credit rounding, submit gates and
plan uniqueness."""
from test_helpers import (
    ApiErrorId,
    assert_degree_plan,
    assert_hold,
    assert_version_incremented,
    course,
    create_approved_plan,
    create_degree_plan_payload,
    create_draft_plan,
    create_student,
    create_submitted_plan,
    get_student,
    place_hold,
    term,
    validate_error,
    validate_success,
)


def _terms_half_credit_pair():
    """Two terms of three 3.5-credit courses each (per-term sum 10.5)."""
    return [
        term("FA26", course("BIO1", 3.5), course("CHM1", 3.5), course("MAT1", 3.5)),
        term("SP27", course("BIO2", 3.5), course("CHM2", 3.5), course("MAT2", 3.5)),
    ]


# ─── Difficulty: transitive_cascade / hold_release_cascades_to_clearance ──────

def test_hold_placement_blocks_clearance_and_release_moves_hold(api, director_headers):
    """PRD §3.8: "The new hold starts `ACTIVE`; the student's `registration_clearance` recomputes at once — any `ACTIVE` hold forces `BLOCKED` — and the `at_risk_score` gains 8 points per `ACTIVE` hold, with the usual tier consequences."
    PRD §3.8: "A successful release moves the hold `ACTIVE → RELEASED` and cascades: `registration_clearance` recomputes and becomes `CLEARED` exactly when no `ACTIVE` holds remain and the advising requirement is not `REQUIRED`, and the released hold's 8 points leave the `at_risk_score`."

    Design: Difficulty/transitive_cascade/hold_release_cascades_to_clearance
    """
    student = create_student(full_name="T2", email="t2@x.edu", gpa=3.0)
    hold = place_hold(student["id"], hold_type="FINANCIAL")
    assert_hold(hold)
    assert hold["status"] == "ACTIVE"
    assert get_student(student["id"])["registration_clearance"] == "BLOCKED"

    released = validate_success(
        api.release_hold(student["id"], hold["id"], director_headers), 200
    )
    assert released["status"] == "RELEASED"


def test_hold_release_clears_clearance_and_drops_score(api, director_headers):
    """PRD §3.8: "A successful release moves the hold `ACTIVE → RELEASED` and cascades: `registration_clearance` recomputes and becomes `CLEARED` exactly when no `ACTIVE` holds remain and the advising requirement is not `REQUIRED`, and the released hold's 8 points leave the `at_risk_score`."
    PRD §3.2: "Hold points add 8 per `ACTIVE` registration hold."

    Design: Difficulty/transitive_cascade/hold_release_cascades_to_clearance
    """
    student = create_student(full_name="T2", email="t2@x.edu", gpa=3.0)
    hold = place_hold(student["id"], hold_type="FINANCIAL")
    held = get_student(student["id"])
    assert held["at_risk_score"] == 18, "10 base (gpa 3.0) + 8 hold"

    validate_success(api.release_hold(student["id"], hold["id"], director_headers), 200)
    after = get_student(student["id"])
    assert after["registration_clearance"] == "CLEARED", (
        "no ACTIVE holds remain and the requirement is not REQUIRED"
    )
    assert after["at_risk_score"] == 10, "the released hold's 8 points leave the score"


# ─── Difficulty: cross_entity_state_dependency / hold_release_requires_plan_approved

def test_plan_gated_hold_release_rejected_while_plan_submitted(api, director_headers):
    """PRD §3.8: "When the hold's `requires_approved_plan` is true, the student must have a degree plan in `APPROVED`; without one the release is rejected with `ERR_PLAN_NOT_APPROVED` — a cross-entity check that §2.10 places after the state and ownership checks, so a release that fails both ownership and the plan gate reports `ERR_NOT_ASSIGNED_ADVISOR`."

    Design: Difficulty/cross_entity_state_dependency/hold_release_requires_plan_approved
    """
    student = create_student(full_name="X2", email="x2@x.edu")
    create_submitted_plan(student["id"], required_credits=10)
    hold = place_hold(student["id"], hold_type="ADVISING", requires_approved_plan=True)
    res = api.release_hold(student["id"], hold["id"], director_headers)
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED)


def test_plan_gated_hold_release_succeeds_after_approval(api, director_headers):
    """PRD §3.8: "Approval — again the assigned advisor or the director — moves `SUBMITTED → APPROVED` and recomputes the student's `registration_clearance`, since the plan gate for `requires_approved_plan` holds is now satisfiable."
    PRD §3.8: "When the hold's `requires_approved_plan` is true, the student must have a degree plan in `APPROVED`; without one the release is rejected with `ERR_PLAN_NOT_APPROVED` — a cross-entity check that §2.10 places after the state and ownership checks, so a release that fails both ownership and the plan gate reports `ERR_NOT_ASSIGNED_ADVISOR`."

    Design: Difficulty/cross_entity_state_dependency/hold_release_requires_plan_approved
    """
    student = create_student(full_name="X2", email="x2@x.edu")
    plan = create_submitted_plan(student["id"], required_credits=10)
    hold = place_hold(student["id"], hold_type="ADVISING", requires_approved_plan=True)
    validate_error(
        api.release_hold(student["id"], hold["id"], director_headers),
        ApiErrorId.ERR_PLAN_NOT_APPROVED,
    )
    approved = validate_success(
        api.approve_degree_plan(student["id"], plan["id"], director_headers), 200
    )
    assert approved["status"] == "APPROVED"
    released = validate_success(
        api.release_hold(student["id"], hold["id"], director_headers), 200
    )
    assert released["status"] == "RELEASED", (
        "with the plan APPROVED the release gate passes"
    )


# ─── Difficulty: non_linear_state_machine / degree_plan_revision_cycle ────────

def test_degree_plan_revision_cycle_revisits_draft(api, director_headers):
    """PRD §3.8: "Submission moves the plan from `DRAFT` to `SUBMITTED` and is guarded by two gates beyond the state check: `mapped_credits_total` must be at least `required_credits`, else `ERR_PLAN_CREDITS_INSUFFICIENT`, and every term's rounded credit total must not exceed 18, else `ERR_PLAN_TERM_OVERLOAD`."
    PRD §3.8: "When the plan needs more work, returning it moves `SUBMITTED → DRAFT` and requires a `reason`. Any transition attempted from the wrong source state is rejected with `ERR_PLAN_INVALID_STATE`; `APPROVED` is terminal."

    Design: Difficulty/non_linear_state_machine/degree_plan_revision_cycle
    """
    student = create_student(full_name="N1", email="n1@x.edu")
    plan = create_draft_plan(student["id"], required_credits=10)
    sid, pid = student["id"], plan["id"]

    st1 = validate_success(api.submit_degree_plan(sid, pid, director_headers), 200)
    assert st1["status"] == "SUBMITTED"
    st2 = validate_success(
        api.return_degree_plan(sid, pid, {"reason": "add second term"}, director_headers),
        200,
    )
    assert st2["status"] == "DRAFT", "the cycle re-enters DRAFT for revision"
    st3 = validate_success(api.submit_degree_plan(sid, pid, director_headers), 200)
    assert st3["status"] == "SUBMITTED", "re-submission after revision"
    st4 = validate_success(api.approve_degree_plan(sid, pid, director_headers), 200)
    assert st4["status"] == "APPROVED"


def test_degree_plan_edit_in_returned_draft_recomputes(api, director_headers):
    """PRD §3.8: "While the plan remains in `DRAFT`, the advisor may revise `terms` or `required_credits`, and `mapped_credits_total` recomputes on each edit; editing a plan that is no longer `DRAFT` is rejected with `ERR_PLAN_INVALID_STATE`."
    PRD §3.8: "For each term in `terms`, the system sums the course credits and rounds that term's sum half-up to a whole number; `mapped_credits_total` is then the sum of those per-term integers."
    PRD §2.5: "`version` (integer): a system-managed integer that increments with every modification to the resource."

    Design: Difficulty/non_linear_state_machine/degree_plan_revision_cycle
    """
    student = create_student(full_name="N1", email="n1@x.edu")
    plan = create_draft_plan(student["id"], required_credits=10)
    sid, pid = student["id"], plan["id"]
    last_version = plan["version"]

    st1 = validate_success(api.submit_degree_plan(sid, pid, director_headers), 200)
    assert_version_incremented(st1["version"], last_version)
    st2 = validate_success(
        api.return_degree_plan(sid, pid, {"reason": "add second term"}, director_headers),
        200,
    )
    assert_version_incremented(st2["version"], st1["version"])

    edited = validate_success(
        api.update_degree_plan(
            sid, pid,
            {"terms": [
                term("FA26", course("BIO1", 3.5), course("CHM1", 3.5), course("MAT1", 3.5)),
                term("SP27", course("ENG1", 3.0)),
            ]},
            director_headers,
        ),
        200,
    )
    assert edited["mapped_credits_total"] == 14, (
        "ROUND_HALF_UP(10.5)=11 plus ROUND_HALF_UP(3.0)=3"
    )
    assert_version_incremented(edited["version"], st2["version"])

    st3 = validate_success(api.submit_degree_plan(sid, pid, director_headers), 200)
    assert st3["status"] == "SUBMITTED"
    st4 = validate_success(api.approve_degree_plan(sid, pid, director_headers), 200)
    assert st4["status"] == "APPROVED"
    assert_version_incremented(st4["version"], st3["version"])


# ─── Difficulty: combinatorial_formula / term_credit_per_term_rounding_order ──

def test_term_credit_rounding_per_term_then_sum(api, director_headers):
    """PRD §3.8: "Rounding each term first and then summing is mandatory — the sum-then-round alternative is rejected: two terms of 10.5 credits each map to 11 plus 11, a total of 22, under the pinned order, whereas summing first would round 21.0 to 21."

    Design: Difficulty/combinatorial_formula/term_credit_per_term_rounding_order
    """
    student = create_student(full_name="C2", email="c2@x.edu")
    plan = create_draft_plan(
        student["id"], required_credits=21, terms=_terms_half_credit_pair()
    )
    assert_degree_plan(plan)
    assert plan["mapped_credits_total"] == 22, (
        "per-term ROUND_HALF_UP(10.5)=11 twice, then summed; sum-then-round (21) rejected"
    )


def test_plan_submit_succeeds_when_gates_pass(api, director_headers):
    """PRD §3.8: "Submission moves the plan from `DRAFT` to `SUBMITTED` and is guarded by two gates beyond the state check: `mapped_credits_total` must be at least `required_credits`, else `ERR_PLAN_CREDITS_INSUFFICIENT`, and every term's rounded credit total must not exceed 18, else `ERR_PLAN_TERM_OVERLOAD`."

    Design: Difficulty/combinatorial_formula/term_credit_per_term_rounding_order
    """
    student = create_student(full_name="C2", email="c2@x.edu")
    plan = create_draft_plan(
        student["id"], required_credits=21, terms=_terms_half_credit_pair()
    )
    assert plan["mapped_credits_total"] == 22
    submitted = validate_success(
        api.submit_degree_plan(student["id"], plan["id"], director_headers), 200
    )
    assert submitted["status"] == "SUBMITTED", "22 >= 21 and each term 11 <= 18"


# ─── Corner: state_machines / hold_release_from_released_rejected ────────────

def test_hold_release_from_released_rejected(api, director_headers):
    """PRD §3.8: "The hold must exist under the path student (`ERR_HOLD_NOT_FOUND`) and must be `ACTIVE` (`ERR_HOLD_NOT_ACTIVE`)."

    Design: Corner/state_machines/hold_release_from_released_rejected
    """
    student = create_student(full_name="S9", email="s9c@x.edu")
    hold = place_hold(student["id"], hold_type="ADMINISTRATIVE")
    validate_success(api.release_hold(student["id"], hold["id"], director_headers), 200)
    res = api.release_hold(student["id"], hold["id"], director_headers)
    validate_error(res, ApiErrorId.ERR_HOLD_NOT_ACTIVE)


# ─── Corner: state_machines / degree_plan_return_from_approved_rejected ───────

def test_degree_plan_return_from_approved_rejected(api, director_headers):
    """PRD §3.8: "When the plan needs more work, returning it moves `SUBMITTED → DRAFT` and requires a `reason`. Any transition attempted from the wrong source state is rejected with `ERR_PLAN_INVALID_STATE`; `APPROVED` is terminal."

    Design: Corner/state_machines/degree_plan_return_from_approved_rejected
    """
    student = create_student(full_name="S3", email="s3c@x.edu")
    plan = create_approved_plan(student["id"], required_credits=10)
    res = api.return_degree_plan(
        student["id"], plan["id"], {"reason": "too late"}, director_headers
    )
    validate_error(res, ApiErrorId.ERR_PLAN_INVALID_STATE)


# ─── Corner: errors / plan_already_active_trigger ─────────────────────────────

def test_plan_already_active_trigger(api, director_headers):
    """PRD §3.8: "A student who already has a plan in `DRAFT` or `SUBMITTED` may not open another — the attempt is rejected with `ERR_PLAN_ALREADY_ACTIVE`."

    Design: Corner/errors/plan_already_active_trigger
    """
    student = create_student(full_name="R2", email="r2e@x.edu")
    create_draft_plan(
        student["id"],
        required_credits=10,
        terms=[term("FA26", course("BIO1", 4.0))],
        catalog_year=2024,
    )
    res = api.create_degree_plan(
        student["id"],
        create_degree_plan_payload(
            catalog_year=2025,
            required_credits=12,
            terms=[term("SP27", course("ENG1", 4.0))],
        ),
        director_headers,
    )
    validate_error(res, ApiErrorId.ERR_PLAN_ALREADY_ACTIVE)


# ─── Corner: errors / plan_submit_insufficient_credits_rejected ───────────────

def test_plan_submit_insufficient_credits_rejected(api, director_headers):
    """PRD §3.8: "Submission moves the plan from `DRAFT` to `SUBMITTED` and is guarded by two gates beyond the state check: `mapped_credits_total` must be at least `required_credits`, else `ERR_PLAN_CREDITS_INSUFFICIENT`, and every term's rounded credit total must not exceed 18, else `ERR_PLAN_TERM_OVERLOAD`."

    Design: Corner/errors/plan_submit_insufficient_credits_rejected
    """
    student = create_student(full_name="R4", email="r4e@x.edu")
    plan = create_draft_plan(
        student["id"],
        required_credits=12,
        terms=[term("FA26", course("BIO1", 3.5), course("CHM1", 3.5), course("MAT1", 3.5))],
    )
    assert plan["mapped_credits_total"] == 11
    res = api.submit_degree_plan(student["id"], plan["id"], director_headers)
    validate_error(res, ApiErrorId.ERR_PLAN_CREDITS_INSUFFICIENT)


# ─── Corner: errors / plan_submit_term_overload_rejected ──────────────────────

def test_plan_submit_term_overload_rejected(api, director_headers):
    """PRD §3.8: "Submission moves the plan from `DRAFT` to `SUBMITTED` and is guarded by two gates beyond the state check: `mapped_credits_total` must be at least `required_credits`, else `ERR_PLAN_CREDITS_INSUFFICIENT`, and every term's rounded credit total must not exceed 18, else `ERR_PLAN_TERM_OVERLOAD`."

    Design: Corner/errors/plan_submit_term_overload_rejected
    """
    student = create_student(full_name="R5", email="r5e@x.edu")
    plan = create_draft_plan(
        student["id"],
        required_credits=10,
        terms=[term("FA26", course("A", 4.0), course("B", 4.0), course("C", 4.0),
                    course("D", 4.0), course("E", 4.0))],
    )
    assert plan["mapped_credits_total"] == 20, "credit gate passes (20 >= 10)"
    res = api.submit_degree_plan(student["id"], plan["id"], director_headers)
    validate_error(res, ApiErrorId.ERR_PLAN_TERM_OVERLOAD)


# ─── Corner: calculations / clearance_blocked_by_unsatisfied_requirement ──────

def test_clearance_blocked_by_unsatisfied_requirement(api, director_headers):
    """PRD §3.8: "`advising_requirement_status` is `NOT_REQUIRED` when `advising_required_flag` is false; otherwise it is `SATISFIED` when a `COMPLETED` appointment exists for the student in the student's `current_term_code`, and `REQUIRED` when none does."
    PRD §3.8: "`registration_clearance` is `BLOCKED` whenever any of the student's holds is `ACTIVE`; failing that, it is `BLOCKED` when the advising requirement is `REQUIRED`; otherwise it is `CLEARED`."

    Design: Corner/calculations/clearance_blocked_by_unsatisfied_requirement
    """
    student = create_student(
        full_name="QC4", email="qc4@x.edu", advising_required_flag=True
    )
    assert student["advising_requirement_status"] == "REQUIRED"
    assert student["registration_clearance"] == "BLOCKED", (
        "BLOCKED with zero holds because the advising requirement is REQUIRED"
    )
