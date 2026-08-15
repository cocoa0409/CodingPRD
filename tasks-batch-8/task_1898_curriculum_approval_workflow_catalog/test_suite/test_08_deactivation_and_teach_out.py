"""Deactivation proposals and their teach-out plans: dual completion
variants, pinned rounding order, constants, cohort-count body validation, the
zero-cohort boundary, the plan-gated course retirement cascade, and the
depth-3 deactivation cascade into dependent courses.
"""
from test_helpers import (
    ApiErrorId,
    advance_through_committee,
    create_and_commit_teach_out_plan,
    create_deactivation_proposal,
    create_department,
    create_submitted_new_course_proposal,
    create_teach_out_plan,
    create_term,
    create_term_2027fa,
    create_term_2027sp,
    create_term_2027su,
    freeze_term_proposals,
    fully_approve_proposal,
    get_course,
    get_proposal,
    get_success_data,
    import_course,
    make_chair_headers,
    make_proposer_headers,
    make_registrar_headers,
    notify_accreditor,
    registrar_approve,
    setup_approved_deactivation_with_committed_plan,
    submit_proposal,
    validate_error,
    validate_paginated,
    validate_success,
)


# -------------------------------------------------------------------------
# Dual variant: enrollment-driven vs catalog-driven completion
# -------------------------------------------------------------------------

def _setup_deactivation_draft_with_plan(api):
    """Department CS; terms at sequence 1, 3, 4; ACTIVE CS 301; a DRAFT
    DEACTIVATION proposal (3 declared cohorts) requesting the sequence-4 term,
    with a DRAFT teach-out plan whose last enrollment is the sequence-3 term."""
    dept = create_department()
    t1 = create_term()
    t3 = create_term_2027su()
    t4 = create_term_2027fa()
    course = import_course(dept["id"], t1["id"], title="Legacy Systems",
                           learning_outcomes=["maintain legacy code"])
    proposal = create_deactivation_proposal(
        dept["id"], t4["id"], course["id"], 3, justification="obsolete")
    plan = create_teach_out_plan(proposal["id"], 3, [5, 5, 5], t3["id"])
    return dept, t1, t3, t4, course, proposal, plan


def test_provisional_completion_uses_enrollment_drain_rate(api):
    """PRD §3.8: "At creation the plan computes an **enrollment-driven**
    estimate of when teach-out finishes and stores it as
    `provisional_completion_sequence`: the `sequence_index` of the
    last-enrolled term plus the cohort count divided by the per-term drain rate
    of 2 cohorts, the division rounded up to a whole number. Three cohorts
    whose last enrollment sits at sequence index 3 therefore estimate
    completion at index 5."

    Design: Difficulty/dual_variant_calc/teach_out_completion_enrollment_vs_catalog_variants
    """
    _d, _t1, _t3, _t4, _c, _p, plan = _setup_deactivation_draft_with_plan(api)
    assert plan["provisional_completion_sequence"] == 5, (
        "ENROLLMENT_DRIVEN: 3 + ceil(3/2)")
    assert plan["status"] == "DRAFT"
    assert plan["committed_completion_sequence"] is None, (
        "both committed fields stay null until commit")


def test_commit_recomputes_completion_catalog_driven(api):
    """PRD §3.8: "Committing recomputes completion under the
    **catalog-driven** variant and stores it as
    `committed_completion_sequence`: the `sequence_index` of the proposal's
    requested effective term plus the catalog policy of 4 teach-out terms. For
    the same plan with a requested effective term at sequence index 4, the
    committed value is 8 — a deliberately different answer from the same
    inputs, because it reflects catalog policy rather than enrollment reality."

    Design: Difficulty/dual_variant_calc/teach_out_completion_enrollment_vs_catalog_variants
    """
    dept, _t1, _t3, _t4, _c, _p, plan = \
        _setup_deactivation_draft_with_plan(api)
    assert plan["provisional_completion_sequence"] == 5

    committed = validate_success(
        api.commit_teach_out_plan(plan["id"], make_chair_headers(dept["id"])))
    assert committed["status"] == "COMMITTED"
    assert committed["committed_completion_sequence"] == 8, (
        "CATALOG_DRIVEN: 4 + 4 teach-out terms")
    assert committed["committed_completion_sequence"] != \
        committed["provisional_completion_sequence"], (
            "the two variants diverge on identical plan inputs")


# -------------------------------------------------------------------------
# Pinned rounding order in the sectioning cost
# -------------------------------------------------------------------------

def test_teach_out_cost_rounds_per_cohort_before_summing(api):
    """PRD §3.8: "The rounding order is pinned and non-interchangeable:
    rounding per cohort before summing is the specified behavior, so cohorts of
    16 and 9 students require 2 plus 1, that is 3 sections, costing 1200000
    cents — whereas summing first would wrongly yield 2 sections."

    Design: Difficulty/combinatorial_formula/teach_out_cost_per_cohort_rounding
    """
    dept = create_department()
    t1 = create_term()
    t3 = create_term_2027su()
    t4 = create_term_2027fa()
    course = import_course(dept["id"], t1["id"], title="Legacy Systems",
                           learning_outcomes=["maintain legacy code"])
    proposal = create_deactivation_proposal(
        dept["id"], t4["id"], course["id"], 2, justification="obsolete")
    plan = create_teach_out_plan(proposal["id"], 2, [16, 9], t3["id"])

    committed = validate_success(
        api.commit_teach_out_plan(plan["id"], make_chair_headers(dept["id"])))
    assert committed["resource_cost_cents"] == 1200000, (
        "ceil(16/15)=2 plus ceil(9/15)=1 gives 3 sections x 400000 cents; the "
        "sum-first order would wrongly give 800000")


def test_committed_plan_records_catalog_driven_completion(api):
    """PRD §3.8: "Committing recomputes completion under the
    **catalog-driven** variant and stores it as
    `committed_completion_sequence`: the `sequence_index` of the proposal's
    requested effective term plus the catalog policy of 4 teach-out terms."
    PRD §3.8: "Both computed fields are null until commit; the commit
    increments the plan's `version`."

    Design: Difficulty/combinatorial_formula/teach_out_cost_per_cohort_rounding
    """
    dept = create_department()
    t1 = create_term()
    t3 = create_term_2027su()
    t4 = create_term_2027fa()
    course = import_course(dept["id"], t1["id"], title="Legacy Systems",
                           learning_outcomes=["maintain legacy code"])
    proposal = create_deactivation_proposal(
        dept["id"], t4["id"], course["id"], 2, justification="obsolete")
    plan = create_teach_out_plan(proposal["id"], 2, [16, 9], t3["id"])
    assert plan["resource_cost_cents"] is None
    assert plan["committed_completion_sequence"] is None

    committed = validate_success(
        api.commit_teach_out_plan(plan["id"], make_chair_headers(dept["id"])))
    assert committed["status"] == "COMMITTED"
    assert committed["committed_completion_sequence"] == 8, (
        "requested effective term sits at sequence 4; 4 + 4 = 8")
    assert committed["version"] == plan["version"] + 1


# -------------------------------------------------------------------------
# Constants and cohort-count body validation
# -------------------------------------------------------------------------

def test_teach_out_constants_applied(api):
    """PRD §3.8: "At creation the plan computes an **enrollment-driven**
    estimate of when teach-out finishes and stores it as
    `provisional_completion_sequence`: the `sequence_index` of the
    last-enrolled term plus the cohort count divided by the per-term drain rate
    of 2 cohorts, the division rounded up to a whole number."
    PRD §3.8: "for each cohort in `cohort_sizes` — all of them, with no status
    filtering, since every cohort runs to completion — the cohort size is
    divided by the section capacity of 15 students and rounded up to a whole
    section count; the sections are then summed across cohorts and multiplied
    by the per-section cost of 400000 cents."

    Design: Corner/calculations/teach_out_constants_applied
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    t4 = create_term_2027fa()
    course = import_course(dept["id"], t1["id"], title="Legacy")
    proposal = create_deactivation_proposal(
        dept["id"], t4["id"], course["id"], 4, justification="retire")
    plan = create_teach_out_plan(proposal["id"], 4, [4, 4, 4, 4], t2["id"])
    assert plan["provisional_completion_sequence"] == 4, (
        "2 + ceil(4/2)")

    committed = validate_success(
        api.commit_teach_out_plan(plan["id"], make_chair_headers(dept["id"])))
    assert committed["committed_completion_sequence"] == 8, "4 + 4"
    assert committed["resource_cost_cents"] == 1600000, (
        "4 cohorts x ceil(4/15)=1 section each -> 4 sections x 400000")


def test_teach_out_cohort_mismatch_rejected(api):
    """PRD §3.8: "Body validation requires the cohort-count arithmetic to agree
    with the proposal: `enrolled_cohort_count` must equal the proposal's
    `declared_remaining_cohorts`, the length of `cohort_sizes` must equal
    `enrolled_cohort_count`, and every size must be at least one."
    PRD §2.8: "fourth, request-body shape and completeness, including
    type-specific submit completeness, date ordering, array length, and
    foreign-key existence (`ERR_VALIDATION`)".

    Design: Corner/validations/teach_out_cohort_mismatch_rejected
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    course = import_course(dept["id"], t1["id"], title="C")
    proposal = create_deactivation_proposal(
        dept["id"], t2["id"], course["id"], 3, justification="retire")

    wrong_count = api.create_teach_out_plan(
        proposal["id"],
        {"enrolled_cohort_count": 2, "cohort_sizes": [5, 5],
         "last_enrolled_term_id": t1["id"]},
        make_proposer_headers("fac-001"))
    validate_error(wrong_count, ApiErrorId.ERR_VALIDATION)

    wrong_length = api.create_teach_out_plan(
        proposal["id"],
        {"enrolled_cohort_count": 3, "cohort_sizes": [5, 5],
         "last_enrolled_term_id": t1["id"]},
        make_proposer_headers("fac-001"))
    validate_error(wrong_length, ApiErrorId.ERR_VALIDATION)


# -------------------------------------------------------------------------
# Zero-cohort boundary on the registrar's teach-out precondition
# -------------------------------------------------------------------------

def _advance_deactivation_to_registrar(api, course_number, declared_cohorts):
    """DRAFT -> REGISTRAR_REVIEW for a DEACTIVATION proposal. Returns
    (dept, term, proposal, senate_response)."""
    dept = create_department()
    term = create_term()
    course = import_course(dept["id"], term["id"], course_number=course_number,
                           title=course_number, learning_outcomes=["x"])
    proposal = create_deactivation_proposal(
        dept["id"], term["id"], course["id"], declared_cohorts,
        justification="phasing out")
    submit_proposal(proposal["id"])
    final = advance_through_committee(proposal["id"], dept["id"])
    return dept, term, proposal, final


def test_zero_cohort_deactivation_approves_without_teach_out(api):
    """PRD §3.7: "Two business preconditions then apply, in order: the
    notification obligation of §3.6 must be satisfied, and for a `DEACTIVATION`
    proposal whose `declared_remaining_cohorts` exceeds zero, a teach-out plan
    serving this proposal must already exist in `COMMITTED`, `IN_PROGRESS`, or
    `COMPLETE` status — otherwise the approval is rejected with
    `ERR_TEACH_OUT_NOT_COMMITTED`."

    Design: Difficulty/boundary_precision_check/zero_cohort_deactivation_exempts_teach_out
    """
    dept, term, proposal, final = \
        _advance_deactivation_to_registrar(api, "401", 0)
    assert final["accreditor_notification_required"] is False, (
        "FINAL score 30 with no teach-out factor stays below 50")

    approved = registrar_approve(proposal["id"], term["id"])
    assert approved["status"] == "APPROVED", (
        "zero declared cohorts: the teach-out requirement does not engage")
    assert approved["effective_term_id"] == term["id"]


def test_one_cohort_deactivation_without_plan_rejected(api):
    """PRD §3.7: "Two business preconditions then apply, in order: the
    notification obligation of §3.6 must be satisfied, and for a `DEACTIVATION`
    proposal whose `declared_remaining_cohorts` exceeds zero, a teach-out plan
    serving this proposal must already exist in `COMMITTED`, `IN_PROGRESS`, or
    `COMPLETE` status — otherwise the approval is rejected with
    `ERR_TEACH_OUT_NOT_COMMITTED`."

    Design: Difficulty/boundary_precision_check/zero_cohort_deactivation_exempts_teach_out
    """
    dept, term, proposal, final = \
        _advance_deactivation_to_registrar(api, "402", 1)
    assert final["accreditor_notification_required"] is True, (
        "FINAL score 30 + 20 = 50")
    notify_accreditor(proposal["id"])

    resp = api.post_decision(
        proposal["id"],
        {"action": "APPROVE", "effective_term_id": term["id"]},
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_TEACH_OUT_NOT_COMMITTED)
    assert get_proposal(proposal["id"])["status"] == "REGISTRAR_REVIEW"


# -------------------------------------------------------------------------
# Course retirement gated on plan completion
# -------------------------------------------------------------------------

def test_teach_out_complete_before_activation_rejected(api):
    """PRD §3.8: "When the owning deactivation proposal activates, the
    committed plan moves `COMMITTED → IN_PROGRESS` automatically. Finally, the
    registrar completes an in-progress plan; completion from any other state is
    rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/course_retirement_gated_by_teach_out
    """
    ctx = setup_approved_deactivation_with_committed_plan(
        declared_remaining_cohorts=1, cohort_sizes=[7])

    resp = api.complete_teach_out_plan(ctx["plan"]["id"],
                                       make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_course_retires_only_when_plan_completes(api):
    """PRD §3.8: "When the owning deactivation proposal activates, the
    committed plan moves `COMMITTED → IN_PROGRESS` automatically. Finally, the
    registrar completes an in-progress plan; completion from any other state is
    rejected with `ERR_INVALID_STATE`. Completing the plan cascades the linked
    course from `DEACTIVATING` to `INACTIVE`, which in turn excludes the
    course's `INCLUDED` catalog entries in editions still in `DRAFT` or
    `FROZEN` status, recomputing `included_entry_count` on each affected
    edition."

    Design: Difficulty/cross_entity_state_dependency/course_retirement_gated_by_teach_out
    """
    ctx = setup_approved_deactivation_with_committed_plan(
        declared_remaining_cohorts=1, cohort_sizes=[7])
    reg = make_registrar_headers()

    # The plan is COMMITTED, not IN_PROGRESS: completion is gated behind the
    # proposal's activation.
    validate_error(api.complete_teach_out_plan(ctx["plan"]["id"], reg),
                   ApiErrorId.ERR_INVALID_STATE)

    freeze_term_proposals(ctx["t1"]["id"])
    activated = validate_success(api.activate_proposal(ctx["proposal"]["id"],
                                                       reg))
    assert activated["status"] == "EFFECTIVE"
    assert get_course(ctx["course"]["id"])["status"] == "DEACTIVATING", (
        "activation alone never retires the course")

    completed = validate_success(
        api.complete_teach_out_plan(ctx["plan"]["id"], reg))
    assert completed["status"] == "COMPLETE"
    assert get_course(ctx["course"]["id"])["status"] == "INACTIVE", (
        "the cross-entity cascade fires only from the plan's COMPLETE "
        "transition")


# -------------------------------------------------------------------------
# Depth-3 deactivation cascade into dependent courses
# -------------------------------------------------------------------------

def _setup_deactivation_cascade(api):
    """Course C (CS 101) imported ACTIVE; course D (CS 201) activated via a
    NEW_COURSE proposal carrying a PREREQUISITE link D -> C; a DEACTIVATION
    proposal on C (1 cohort) with a COMMITTED plan is fully approved with the
    frozen fall term as its effective term."""
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    course_c = import_course(dept["id"], t1["id"], course_number="101",
                             title="Intro I", learning_outcomes=["basics"])

    proposal_d = create_submitted_new_course_proposal(
        dept["id"], t1["id"], "201", proposed_title="Intro II",
        learning_outcomes=["more basics"], justification="sequence",
        proposed_requisites=[{"requisite_course_id": course_c["id"],
                              "requisite_type": "PREREQUISITE"}])
    fully_approve_proposal(proposal_d["id"], dept["id"], t1["id"])
    freeze_term_proposals(t1["id"])
    reg = make_registrar_headers()
    get_success_data(api.activate_proposal(proposal_d["id"], reg))
    courses, _ = validate_paginated(
        api.list_courses(reg, params={"subject_code": "CS",
                                      "course_number": "201"}))
    course_d = courses[0]
    d_summary_pre = course_d["prerequisite_summary"]

    proposal_x = create_deactivation_proposal(
        dept["id"], t2["id"], course_c["id"], 1,
        justification="merged into 201")
    create_and_commit_teach_out_plan(proposal_x["id"], dept["id"], 1, [3],
                                     t1["id"])
    submit_proposal(proposal_x["id"])
    advance_through_committee(proposal_x["id"], dept["id"])
    score_final = get_proposal(proposal_x["id"])["substantive_change_score"]
    notify_accreditor(proposal_x["id"])
    registrar_approve(proposal_x["id"], t1["id"])

    return {"dept": dept, "t1": t1, "t2": t2, "course_c": course_c,
            "course_d": course_d, "d_summary_pre": d_summary_pre,
            "proposal_x": proposal_x, "score_final": score_final}


def test_deactivation_activation_cascades_to_dependent_course_links(api):
    """PRD §3.7: "A `DEACTIVATION` activation instead moves the target course
    `ACTIVE → DEACTIVATING` and fires the widest cascade in the system. The
    course's committed teach-out plan moves `COMMITTED → IN_PROGRESS`.
    Every active requisite link that names the deactivated course as its
    requisite becomes `REMOVED`, and each such removal recomputes
    `prerequisite_summary` and increments `version` on the dependent course at
    the link's other end."

    Design: Difficulty/transitive_cascade/deactivation_activation_cascade_depth3
    """
    ctx = _setup_deactivation_cascade(api)
    reg = make_registrar_headers()
    assert ctx["d_summary_pre"] == "CS 101", (
        "the dependent course's summary reflects its active link before the "
        "cascade")
    assert ctx["score_final"] == 50, (
        "30 base + 20 teach-out factor, which forced the NOTIFY step")

    activated = validate_success(
        api.activate_proposal(ctx["proposal_x"]["id"], reg))
    assert activated["status"] == "EFFECTIVE"
    assert get_course(ctx["course_c"]["id"])["status"] == "DEACTIVATING", (
        "hop 1: the activate transition deactivates the target course")

    links, _ = validate_paginated(
        api.list_course_requisites(ctx["course_c"]["id"], reg))
    assert len(links) == 1
    assert links[0]["status"] == "REMOVED", (
        "hop 2: the D -> C link died from C's deactivation, not from the "
        "activate call directly")


def test_deactivation_cascade_recomputes_dependent_summary_and_version(api):
    """PRD §3.7: "Every active requisite link that names the deactivated
    course as its requisite becomes `REMOVED`, and each such removal recomputes
    `prerequisite_summary` and increments `version` on the dependent course at
    the link's other end."
    PRD §2.4: "`version` (integer): a system-managed integer that increments by
    one with every mutation of the resource, including mutations caused by
    cascade side effects originating on a different resource."

    Design: Difficulty/transitive_cascade/deactivation_activation_cascade_depth3
    """
    ctx = _setup_deactivation_cascade(api)
    reg = make_registrar_headers()
    assert ctx["d_summary_pre"] == "CS 101"

    validate_success(api.activate_proposal(ctx["proposal_x"]["id"], reg))

    course_d = get_course(ctx["course_d"]["id"])
    assert course_d["prerequisite_summary"] == "", (
        "hop 3: the link removal recomputed the dependent course's summary to "
        "the empty string")
    assert course_d["version"] == 3, (
        "1 at course creation + 1 at link activation + 1 at cascade removal")
