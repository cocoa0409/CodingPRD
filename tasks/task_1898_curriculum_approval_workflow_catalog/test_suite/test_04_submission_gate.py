"""The submission gate into DEPT_REVIEW: idempotency via state, the credit
workload check, requisite screening, learning outcomes, the proposal window,
and validation priority between state and temporal failures.
"""
from test_helpers import (
    ApiErrorId,
    advance_through_committee,
    create_course_change_proposal,
    create_deactivation_proposal,
    create_department,
    create_new_course_proposal,
    create_submitted_new_course_proposal,
    create_term,
    create_term_2027sp,
    freeze_term_proposals,
    get_proposal,
    import_course,
    list_decision_records,
    make_proposer_headers,
    make_registrar_headers,
    registrar_approve,
    submit_proposal,
    validate_error,
    validate_success,
)


def test_double_submit_rejected(api):
    """PRD §3.4: "Submission moves a proposal from `DRAFT` — or, on
    resubmission, from `RETURNED` — into `DEPT_REVIEW`, and every check below
    re-runs on every resubmission."
    PRD §2.8: "sixth, whether the requested transition exists from the
    resource's current state (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/double_submit_rejected
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")

    resp = api.submit_proposal(proposal["id"], make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    records = list_decision_records(proposal["id"])
    actions = [r["action"] for r in records]
    assert actions == ["SUBMIT"], (
        "a rejected second submit appends no further SUBMIT record")


def test_credit_workload_rounding_and_tolerance(api):
    """PRD §3.4: "And the **credit-hour workload check** verifies that the
    proposed credits are consistent with the stated workload: the weekly
    contact hours plus the weekly out-of-class hours are multiplied by the 15
    weeks of a term and divided by the 45 Carnegie hours per credit, the result
    rounded half-up to one decimal place, and the submission passes only if the
    absolute difference between `proposed_credit_hours` and that computed
    figure is no more than 0.5 — a tolerance that includes the boundary. A
    shortfall beyond tolerance is rejected with `ERR_CREDIT_HOUR_MISMATCH`."

    Design: Corner/calculations/credit_workload_rounding_and_tolerance
    """
    dept = create_department()
    term = create_term()
    # contact 2 + out-of-class 5 -> round_half_up(7*15/45, 1) == 2.3 credits.
    p_ok = create_new_course_proposal(
        dept["id"], term["id"], "480", proposed_title="Seminar",
        proposed_credit_hours=2.3, contact_hours_per_week=2,
        out_of_class_hours_per_week=5, learning_outcomes=["discuss"])
    p_bad = create_new_course_proposal(
        dept["id"], term["id"], "481", proposed_title="Seminar II",
        proposed_credit_hours=4.0, contact_hours_per_week=2,
        out_of_class_hours_per_week=5, learning_outcomes=["discuss more"])

    ok = api.submit_proposal(p_ok["id"], make_proposer_headers("fac-001"))
    assert validate_success(ok)["status"] == "DEPT_REVIEW", (
        "2.3 is within the inclusive 0.5 tolerance of computed 2.3")

    bad = api.submit_proposal(p_bad["id"], make_proposer_headers("fac-001"))
    validate_error(bad, ApiErrorId.ERR_CREDIT_HOUR_MISMATCH)
    assert get_proposal(p_bad["id"])["status"] == "DRAFT", (
        "4.0 deviates 1.7 from the computed 2.3 credits")


def test_self_requisite_rejected(api):
    """PRD §3.4: "Each entry in `proposed_requisites` is screened: the named
    requisite course must exist and be `ACTIVE` (a reference to a non-active
    course is rejected with `ERR_REQUISITE_TARGET_INACTIVE`), and no entry may
    name the proposal's own target course as its requisite (rejected with
    `ERR_SELF_REQUISITE`)."

    Design: Corner/validations/self_requisite_rejected
    """
    dept = create_department()
    term = create_term()
    course = import_course(dept["id"], term["id"])
    proposal = create_course_change_proposal(
        dept["id"], term["id"], course["id"],
        proposed_requisites=[{"requisite_course_id": course["id"],
                              "requisite_type": "PREREQUISITE"}])

    resp = api.submit_proposal(proposal["id"], make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_SELF_REQUISITE)
    assert get_proposal(proposal["id"])["status"] == "DRAFT"


def test_requisite_target_inactive_rejected(api):
    """PRD §3.4: "Each entry in `proposed_requisites` is screened: the named
    requisite course must exist and be `ACTIVE` (a reference to a non-active
    course is rejected with `ERR_REQUISITE_TARGET_INACTIVE`), and no entry may
    name the proposal's own target course as its requisite (rejected with
    `ERR_SELF_REQUISITE`)."

    Design: Corner/validations/requisite_target_inactive_rejected
    """
    dept = create_department()
    t1 = create_term()
    course_t = import_course(dept["id"], t1["id"], title="Target")

    # Deactivate T with zero remaining cohorts: fully approved, fall term
    # frozen, activated -> course leaves ACTIVE for DEACTIVATING.
    proposal_d = create_deactivation_proposal(
        dept["id"], t1["id"], course_t["id"], 0, justification="retire")
    submit_proposal(proposal_d["id"])
    advance_through_committee(proposal_d["id"], dept["id"])
    registrar_approve(proposal_d["id"], t1["id"])
    freeze_term_proposals(t1["id"])
    reg = make_registrar_headers()
    validate_success(api.activate_proposal(proposal_d["id"], reg))

    t2 = create_term_2027sp()
    proposal = create_new_course_proposal(
        dept["id"], t2["id"], "499", proposed_title="Advanced",
        proposed_requisites=[{"requisite_course_id": course_t["id"],
                              "requisite_type": "PREREQUISITE"}])
    resp = api.submit_proposal(proposal["id"], make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_REQUISITE_TARGET_INACTIVE)
    assert get_proposal(proposal["id"])["status"] == "DRAFT"


def test_learning_outcomes_empty_rejected(api):
    """PRD §3.4: "When `learning_outcomes` is present but an empty array on a
    new-course or change submission, the rejection is
    `ERR_LEARNING_OUTCOMES_REQUIRED` (an absent field is caught earlier as
    `ERR_VALIDATION`)."

    Design: Corner/validations/learning_outcomes_empty_rejected
    """
    dept = create_department()
    term = create_term()
    proposal = create_new_course_proposal(dept["id"], term["id"], "450",
                                          learning_outcomes=[])

    resp = api.submit_proposal(proposal["id"], make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_LEARNING_OUTCOMES_REQUIRED)


def test_submit_rejected_when_requested_term_frozen(api):
    """PRD §3.4: "The window check comes first among the business rules: the
    term named by `requested_effective_term_id` must be in `OPEN_FOR_PROPOSALS`
    and the logical clock must be strictly before that term's
    `proposal_freeze_at`, otherwise the submission is rejected with
    `ERR_PROPOSAL_WINDOW_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/proposal_submit_gated_by_term_state
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    pa = create_new_course_proposal(dept["id"], t1["id"], "460",
                                    proposed_title="A",
                                    learning_outcomes=["a"])
    create_new_course_proposal(dept["id"], t2["id"], "461",
                               proposed_title="B", learning_outcomes=["b"])
    freeze_term_proposals(t1["id"])  # clock -> 2026-10-02, T1 PROPOSAL_FROZEN

    resp = api.submit_proposal(pa["id"], make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_PROPOSAL_WINDOW_CLOSED)
    assert get_proposal(pa["id"])["status"] == "DRAFT"


def test_submit_succeeds_against_open_sibling_term(api):
    """PRD §3.4: "The window check comes first among the business rules: the
    term named by `requested_effective_term_id` must be in `OPEN_FOR_PROPOSALS`
    and the logical clock must be strictly before that term's
    `proposal_freeze_at`, otherwise the submission is rejected with
    `ERR_PROPOSAL_WINDOW_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/proposal_submit_gated_by_term_state
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    create_new_course_proposal(dept["id"], t1["id"], "460",
                               proposed_title="A", learning_outcomes=["a"])
    pb = create_new_course_proposal(dept["id"], t2["id"], "461",
                                    proposed_title="B",
                                    learning_outcomes=["b"])
    freeze_term_proposals(t1["id"])  # freezes T1 only; T2 stays OPEN

    resp = api.submit_proposal(pb["id"], make_proposer_headers("fac-001"))
    assert validate_success(resp)["status"] == "DEPT_REVIEW", (
        "the identical payload succeeds against the still-OPEN sibling term")


def test_resubmit_on_frozen_term_surfaces_state_error(api):
    """PRD §2.8: "The order is: first, authentication of the headers
    (`ERR_UNAUTHENTICATED`); second, role authorization for the endpoint
    (`ERR_FORBIDDEN`); third, left-to-right path resolution (`ERR_NOT_FOUND`);
    fourth, request-body shape and completeness, including type-specific submit
    completeness, date ordering, array length, and foreign-key existence
    (`ERR_VALIDATION`); fifth, resource-level ownership
    (`ERR_NOT_RESOURCE_OWNER`); sixth, whether the requested transition exists
    from the resource's current state (`ERR_INVALID_STATE`); seventh,
    stage-role matching on committee decisions (`ERR_FORBIDDEN`); eighth,
    segregation of duties (`ERR_SELF_APPROVAL_FORBIDDEN`); and only then the
    business rules in their own order — accreditor notification pending
    (`ERR_ACCREDITOR_NOTIFICATION_PENDING`), the proposal submission window
    (`ERR_PROPOSAL_WINDOW_CLOSED`), freeze dates not yet reached
    (`ERR_FREEZE_DATE_NOT_REACHED`), terms not locked (`ERR_TERM_NOT_LOCKED`),
    teach-out commitment (`ERR_TEACH_OUT_NOT_COMMITTED`), requisite target
    activity (`ERR_REQUISITE_TARGET_INACTIVE`), prerequisite cycles
    (`ERR_REQUISITE_CYCLE`), self-requisites (`ERR_SELF_REQUISITE`),
    course-number holds (`ERR_COURSE_NUMBER_HELD`), term date overlap
    (`ERR_TERM_DATE_OVERLAP`), term sequence conflicts
    (`ERR_TERM_SEQUENCE_CONFLICT`), edition window conflicts
    (`ERR_EDITION_WINDOW_CONFLICT`), duplicate cross-listings
    (`ERR_CROSS_LISTING_EXISTS`), empty learning outcomes
    (`ERR_LEARNING_OUTCOMES_REQUIRED`), and finally the credit-hour workload
    check (`ERR_CREDIT_HOUR_MISMATCH`)."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_temporal_submit_frozen_term
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")
    freeze_term_proposals(term["id"])  # window now closed for T1

    # The resubmission is BOTH out-of-state (already DEPT_REVIEW) and past the
    # term's proposal freeze; the state failure outranks the temporal one.
    resp = api.submit_proposal(proposal["id"], make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_failed_dual_failure_resubmit_leaves_proposal_unchanged(api):
    """PRD §2.8: "sixth, whether the requested transition exists from the
    resource's current state (`ERR_INVALID_STATE`)".
    PRD §3.4: "A `DecisionRecord` with action `SUBMIT` is appended, capturing
    `from_status` `DRAFT` (or `RETURNED`) and `to_status` `DEPT_REVIEW`, and
    the proposal's `version` increments."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_temporal_submit_frozen_term
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")
    freeze_term_proposals(term["id"])

    resp = api.submit_proposal(proposal["id"], make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_proposal(proposal["id"])
    assert after["status"] == "DEPT_REVIEW"
    records = list_decision_records(proposal["id"])
    assert [r["action"] for r in records] == ["SUBMIT"], (
        "the rejected resubmission appends no record and changes no state")
