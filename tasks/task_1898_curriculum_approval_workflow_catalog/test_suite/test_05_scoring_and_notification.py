"""Substantive-change scoring (provisional vs final variants, multi-factor
branching, the threshold boundary) and the accreditor notification workflow,
including registrar-approval priority between the safety and referential
business rules.
"""
from test_helpers import (
    ApiErrorId,
    advance_through_committee,
    create_course_change_proposal,
    create_deactivation_proposal,
    create_department,
    create_pending_cross_listing,
    create_submitted_new_course_proposal,
    create_term,
    get_proposal,
    import_course,
    make_chair_headers,
    make_committee_headers,
    make_registrar_headers,
    make_senate_headers,
    post_decision,
    set_clock,
    setup_cross_listing_pair,
    submit_proposal,
    validate_error,
    validate_success,
)


# -------------------------------------------------------------------------
# Dual variant: provisional vs final score on a cross-listed deactivation
# -------------------------------------------------------------------------

def _setup_crosslisted_deactivation_in_committee(api):
    """CS 301 (dept CS) cross-listed PENDING with MATH 210 (dept MATH);
    DEACTIVATION proposal on CS 301 with 3 declared cohorts, submitted and
    sitting in DEPT_REVIEW."""
    ctx = setup_cross_listing_pair()
    dept_cs = ctx["dept_home"]
    course_c = ctx["home_course"]
    create_pending_cross_listing(course_c["id"], ctx["partner_course"]["id"],
                                 dept_cs["id"])
    proposal = create_deactivation_proposal(
        dept_cs["id"], ctx["term"]["id"], course_c["id"], 3,
        justification="obsolete content")
    submitted = submit_proposal(proposal["id"])
    ctx["proposal"] = proposal
    ctx["submitted"] = submitted
    return ctx


def test_provisional_score_excludes_post_submission_factors(api):
    """PRD §3.6: "Both variants begin from a base determined by
    `proposal_type`: 20 for `NEW_COURSE`, 10 for `COURSE_CHANGE`, and 30 for
    `DEACTIVATION`."
    PRD §3.6: "The provisional variant — computed at submission — stops there."
    PRD §3.6: "Whenever the stored score reaches at least the notification
    threshold of 50, `accreditor_notification_required` is set to true; below
    50 it is false."

    Design: Difficulty/dual_variant_calc/score_provisional_vs_final_crosslisted_deactivation
    """
    ctx = _setup_crosslisted_deactivation_in_committee(api)
    submitted = ctx["submitted"]
    assert submitted["substantive_change_score"] == 30, (
        "PROVISIONAL carries the DEACTIVATION base only: cross-listing and "
        "teach-out factors are post-submission state")
    assert submitted["accreditor_notification_required"] is False


def test_final_score_adds_cross_listing_and_teach_out_factors(api):
    """PRD §3.6: "The final variant, recomputed as the proposal moves
    `SENATE_REVIEW → REGISTRAR_REVIEW` and overwriting both stored fields, adds
    two more factors that only post-submission state can determine: 15 points
    when any cross-listing in `PENDING`, `HOME_APPROVED`, `PARTNER_APPROVED`,
    or `ACTIVE` status touches the target course on either side, and 20 points
    when the proposal is a `DEACTIVATION` whose `declared_remaining_cohorts`
    exceeds zero."

    Design: Difficulty/dual_variant_calc/score_provisional_vs_final_crosslisted_deactivation
    """
    ctx = _setup_crosslisted_deactivation_in_committee(api)
    proposal = ctx["proposal"]
    dept_cs = ctx["dept_home"]
    post_decision(proposal["id"], "APPROVE", make_chair_headers(dept_cs["id"]))
    post_decision(proposal["id"], "APPROVE", make_committee_headers())
    final = post_decision(proposal["id"], "APPROVE", make_senate_headers())

    assert final["status"] == "REGISTRAR_REVIEW"
    assert final["substantive_change_score"] == 65, (
        "FINAL = 30 base + 15 cross-listed target + 20 remaining cohorts")
    assert final["accreditor_notification_required"] is True, (
        "65 reaches the notification threshold of 50")


# -------------------------------------------------------------------------
# Multi-factor branching on a course change
# -------------------------------------------------------------------------

def _setup_multi_factor_change(api):
    """Target course CS 301 carries 4 credits; the change proposes 3 credits
    (delta ratio exactly 0.25) plus two new PREREQUISITE links."""
    dept = create_department()
    term = create_term()
    course_c = import_course(dept["id"], term["id"], credit_hours=4,
                             contact_hours_per_week=4,
                             out_of_class_hours_per_week=5)
    course_r1 = import_course(dept["id"], term["id"], course_number="101",
                              title="Intro I", learning_outcomes=["basics"])
    course_r2 = import_course(dept["id"], term["id"], course_number="102",
                              title="Intro II",
                              learning_outcomes=["more basics"])
    proposal = create_course_change_proposal(
        dept["id"], term["id"], course_c["id"],
        proposed_course_number="301",
        proposed_credit_hours=3, contact_hours_per_week=3,
        out_of_class_hours_per_week=6,
        learning_outcomes=["design modern systems"],
        proposed_requisites=[
            {"requisite_course_id": course_r1["id"],
             "requisite_type": "PREREQUISITE"},
            {"requisite_course_id": course_r2["id"],
             "requisite_type": "PREREQUISITE"},
        ])
    return dept, term, proposal


def test_substantive_score_combines_base_delta_and_prereq_factors(api):
    """PRD §3.6: "A change proposal then adds 25 points when its credit shift
    is large — that is, when the absolute difference between
    `proposed_credit_hours` and the target course's current `credit_hours`,
    divided by the target's current `credit_hours`, reaches at least a 0.25
    ratio."
    PRD §3.6: "Both variants then add the prerequisite factor: 10 points per
    `proposed_requisites` entry of type `PREREQUISITE` for which no
    already-`ACTIVE` requisite link connects the target course to that same
    requisite course, with the total contribution capped at 20 points."

    Design: Difficulty/combinatorial_formula/substantive_score_multi_factor_branching
    """
    _dept, _term, proposal = _setup_multi_factor_change(api)
    submitted = submit_proposal(proposal["id"])
    # 10 (COURSE_CHANGE base) + 25 (|3-4|/4 = 0.25 ratio branch fires)
    # + min(2 * 10, 20) = 20 (two new PREREQUISITE links) == 55.
    assert submitted["substantive_change_score"] == 55
    assert submitted["accreditor_notification_required"] is True, (
        "55 reaches the notification threshold of 50")


def test_scored_proposal_enters_dept_review_with_stored_score(api):
    """PRD §3.4: "The proposal's provisional substantive-change score is
    computed and stored along with the notification flag (§3.6)."
    PRD §3.4: "Submission moves a proposal from `DRAFT` — or, on resubmission,
    from `RETURNED` — into `DEPT_REVIEW`, and every check below re-runs on
    every resubmission."

    Design: Difficulty/combinatorial_formula/substantive_score_multi_factor_branching
    """
    _dept, _term, proposal = _setup_multi_factor_change(api)
    submitted = submit_proposal(proposal["id"])
    assert submitted["status"] == "DEPT_REVIEW"
    stored = get_proposal(proposal["id"])
    assert stored["substantive_change_score"] == 55
    assert stored["accreditor_notification_required"] is True


# -------------------------------------------------------------------------
# Threshold boundary: exactly 50 notifies
# -------------------------------------------------------------------------

def test_crosslisted_change_scores_exactly_50_at_final(api):
    """PRD §3.6: "Whenever the stored score reaches at least the notification
    threshold of 50, `accreditor_notification_required` is set to true; below
    50 it is false."
    PRD §3.6: "The final variant, recomputed as the proposal moves
    `SENATE_REVIEW → REGISTRAR_REVIEW` and overwriting both stored fields, adds
    two more factors that only post-submission state can determine: 15 points
    when any cross-listing in `PENDING`, `HOME_APPROVED`, `PARTNER_APPROVED`,
    or `ACTIVE` status touches the target course on either side, and 20 points
    when the proposal is a `DEACTIVATION` whose `declared_remaining_cohorts`
    exceeds zero."

    Design: Difficulty/boundary_precision_check/accreditor_threshold_exactly_50_triggers
    """
    dept_cs = create_department()
    dept_math = create_department(dept_name="Mathematics",
                                  subject_codes=["MATH"], college="Sciences")
    term = create_term()
    course_c = import_course(dept_cs["id"], term["id"], course_number="301",
                             credit_hours=4, contact_hours_per_week=4,
                             out_of_class_hours_per_week=5, title="C")
    course_m = import_course(dept_math["id"], term["id"], subject_code="MATH",
                             course_number="210", title="M")
    create_pending_cross_listing(course_c["id"], course_m["id"], dept_cs["id"])

    pa = create_course_change_proposal(
        dept_cs["id"], term["id"], course_c["id"],
        proposed_course_number="301", proposed_title="C v2",
        proposed_credit_hours=3, learning_outcomes=["x2"])
    submitted = submit_proposal(pa["id"])
    assert submitted["substantive_change_score"] == 35, (
        "PROVISIONAL = 10 base + 25 credit delta; the cross-listing factor is "
        "post-submission state")
    assert submitted["accreditor_notification_required"] is False

    final = advance_through_committee(pa["id"], dept_cs["id"])
    assert final["substantive_change_score"] == 50, (
        "FINAL adds 15 for the PENDING cross-listing touching the target")
    assert final["accreditor_notification_required"] is True, (
        "exactly 50 triggers because the rule is >= 50")


def test_non_crosslisted_change_stays_below_threshold(api):
    """PRD §3.6: "Whenever the stored score reaches at least the notification
    threshold of 50, `accreditor_notification_required` is set to true; below
    50 it is false."
    PRD §3.6: "A change proposal then adds 25 points when its credit shift is
    large — that is, when the absolute difference between
    `proposed_credit_hours` and the target course's current `credit_hours`,
    divided by the target's current `credit_hours`, reaches at least a 0.25
    ratio."

    Design: Difficulty/boundary_precision_check/accreditor_threshold_exactly_50_triggers
    """
    dept = create_department()
    term = create_term()
    course_d = import_course(dept["id"], term["id"], course_number="302",
                             credit_hours=4, contact_hours_per_week=4,
                             out_of_class_hours_per_week=5, title="D")
    pb = create_course_change_proposal(
        dept["id"], term["id"], course_d["id"],
        proposed_course_number="302", proposed_title="D v2",
        proposed_credit_hours=3, learning_outcomes=["x2"])
    submit_proposal(pb["id"])
    final = advance_through_committee(pb["id"], dept["id"])
    assert final["substantive_change_score"] == 35, (
        "no cross-listing touches the target, so the FINAL variant adds nothing")
    assert final["accreditor_notification_required"] is False


# -------------------------------------------------------------------------
# Registrar approval priority: notification pending beats teach-out missing
# -------------------------------------------------------------------------

def _setup_unnotified_deactivation_at_registrar(api, declared_cohorts=2):
    """DEACTIVATION proposal advanced to REGISTRAR_REVIEW with a FINAL score
    of 50 (notification required, never sent) and no teach-out plan."""
    dept = create_department()
    term = create_term()
    course = import_course(dept["id"], term["id"], title="Legacy",
                           learning_outcomes=["legacy"])
    proposal = create_deactivation_proposal(
        dept["id"], term["id"], course["id"], declared_cohorts,
        justification="obsolete")
    submit_proposal(proposal["id"])
    final = advance_through_committee(proposal["id"], dept["id"])
    return dept, term, proposal, final


def test_registrar_approve_blocked_by_pending_notification(api):
    """PRD §3.7: "Two business preconditions then apply, in order: the
    notification obligation of §3.6 must be satisfied, and for a `DEACTIVATION`
    proposal whose `declared_remaining_cohorts` exceeds zero, a teach-out plan
    serving this proposal must already exist in `COMMITTED`, `IN_PROGRESS`, or
    `COMPLETE` status — otherwise the approval is rejected with
    `ERR_TEACH_OUT_NOT_COMMITTED`."
    PRD §3.6: "A proposal flagged as requiring notification cannot complete
    registrar approval until the notification has actually been recorded: the
    registrar's approval is rejected with
    `ERR_ACCREDITOR_NOTIFICATION_PENDING` while `notification_sent_at` remains
    null."

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_vs_referential_registrar_approve
    """
    dept, term, proposal, final = \
        _setup_unnotified_deactivation_at_registrar(api)
    assert final["accreditor_notification_required"] is True, (
        "FINAL score 30 + 20 = 50 crosses the threshold")

    resp = api.post_decision(
        proposal["id"],
        {"action": "APPROVE", "effective_term_id": term["id"]},
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_ACCREDITOR_NOTIFICATION_PENDING)


def test_rejected_dual_failure_approve_leaves_proposal_in_registrar_review(api):
    """PRD §2.8: "and only then the business rules in their own order —
    accreditor notification pending
    (`ERR_ACCREDITOR_NOTIFICATION_PENDING`), the proposal submission window
    (`ERR_PROPOSAL_WINDOW_CLOSED`), freeze dates not yet reached
    (`ERR_FREEZE_DATE_NOT_REACHED`), terms not locked (`ERR_TERM_NOT_LOCKED`),
    teach-out commitment (`ERR_TEACH_OUT_NOT_COMMITTED`)".

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_vs_referential_registrar_approve
    """
    dept, term, proposal, final = \
        _setup_unnotified_deactivation_at_registrar(api)
    assert final["accreditor_notification_required"] is True

    resp = api.post_decision(
        proposal["id"],
        {"action": "APPROVE", "effective_term_id": term["id"]},
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_ACCREDITOR_NOTIFICATION_PENDING)
    assert get_proposal(proposal["id"])["status"] == "REGISTRAR_REVIEW", (
        "the notification-pending failure outranks the missing teach-out plan "
        "and the proposal does not advance")


# -------------------------------------------------------------------------
# NOTIFY self-loop gating and stamping
# -------------------------------------------------------------------------

def test_notify_when_not_required_rejected(api):
    """PRD §3.6: "Recording the notification is a registrar self-loop on
    `REGISTRAR_REVIEW` — a decision with action `NOTIFY` — valid only while the
    flag is true and no notification has yet been sent; a repeated notification
    after one has been sent is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/notify_when_not_required_rejected
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")
    final = advance_through_committee(proposal["id"], dept["id"])
    assert final["accreditor_notification_required"] is False, (
        "a NEW_COURSE base score of 20 stays below the threshold")

    resp = api.post_decision(proposal["id"], {"action": "NOTIFY"},
                             make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_proposal(proposal["id"])["notification_sent_at"] is None


def test_notify_stamps_logical_clock(api):
    """PRD §3.6: "A successful notification stamps `notification_sent_at` with
    the current logical time, appends a `DecisionRecord` whose `from_status`
    and `to_status` are both `REGISTRAR_REVIEW`, and increments `version`."
    PRD §2.5: "A registrar-only test-driving capability advances the clock to a
    supplied `to_iso8601` instant and returns the resulting `current_utc`; from
    that point on, every subsequent time-gated validation evaluates against the
    new logical now."

    Design: Corner/state_machines/notify_stamps_logical_clock
    """
    from datetime import datetime, timezone

    dept = create_department()
    term = create_term()
    course = import_course(dept["id"], term["id"], title="Legacy")
    proposal = create_deactivation_proposal(
        dept["id"], term["id"], course["id"], 1, justification="retire")
    submit_proposal(proposal["id"])
    final = advance_through_committee(proposal["id"], dept["id"])
    assert final["accreditor_notification_required"] is True

    set_clock("2026-09-01T12:00:00Z")
    resp = api.post_decision(proposal["id"], {"action": "NOTIFY"},
                             make_registrar_headers())
    data = validate_success(resp)
    assert data["status"] == "REGISTRAR_REVIEW", "NOTIFY is a self-loop"
    stamped = datetime.fromisoformat(
        data["notification_sent_at"].replace("Z", "+00:00"))
    assert stamped == datetime(2026, 9, 1, 12, 0, 0,
                               tzinfo=timezone.utc), (
        "the stamp carries the logical clock value, not wall-clock time")

    records = list(api.list_decisions(proposal["id"],
                                      make_registrar_headers()).json()["data"])
    last = records[-1]
    assert last["action"] == "NOTIFY"
    assert last["from_status"] == "REGISTRAR_REVIEW"
    assert last["to_status"] == "REGISTRAR_REVIEW"
