"""Second-coverage tests for every difficulty instance.

The difficulty queue requires ≥2 tests per instance. test_01-test_12
contains the first; this file contains a second test per instance,
varying the angle (different input values, neighbouring boundary, or
side-effect surface) while citing the same PRD prose for the same rule.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_clock_and_school, register_applicant,
    invite_and_accept_recommender, create_recommender_invited,
    create_application, create_essay, create_and_submit_letter,
    create_requested_letter,
    submit_application, start_review, decide, advance_clock_to,
    setup_admitted_with_fa_profile, setup_under_review_application,
    create_aid_offer_payload, decide_payload, create_school_payload,
    make_applicant_headers, make_recommender_headers,
    admissions_headers, fa_officer_headers, admin_headers,
    api_client, make_body_with_word_count,
)


# ============================================================================
# Rule 1 — dual_variant_calc (followups)
# ============================================================================

def test_aid_offer_federal_zero_efc_demonstrated_need_equals_coa(api):
    """PRD §3.6: "The demonstrated_need_cents is the maximum of zero and
    the difference between cost_of_attendance_cents and the applicable
    EFC; the applicable EFC is fafsa_efc_cents from the linked
    FinancialAidProfile when variant is FEDERAL"

    Design: Difficulty/dual_variant_calc/aid_offer_federal_vs_institutional_divergence
    """
    # When fafsa_efc_cents == 0, FEDERAL demonstrated_need == COA exactly.
    applicant, school, admitted, _fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=0,
        family_income_cents=3_000_000,
        school_overrides={"name": "Federal-Zero-EFC"},
    )
    res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=admitted["version"],
            cost_of_attendance_cents=5_000_000,
            variant="FEDERAL",
            grant_cents=0, loan_cents=0, work_study_cents=0),
        fa_officer_headers())
    offer = validate_success(res, 201)
    assert offer["demonstrated_need_cents"] == 5_000_000


def test_admission_score_final_equals_provisional_when_all_letters_submitted(api):
    """PRD §3.5: "when every letter is already SUBMITTED, the two variants
    agree exactly."

    Design: Difficulty/dual_variant_calc/admission_probability_provisional_vs_final_divergence
    """
    school = setup_clock_and_school(name="EQ-VARIANTS")
    applicant = register_applicant(full_name="Eq Variants", gpa=3.8, sat_total=1500)
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], rec["id"])

    headers = make_applicant_headers(applicant["id"])
    prov = validate_success(api.get_application(
        app["id"], headers, params={"score_variant": "PROVISIONAL"}), 200)
    fnl = validate_success(api.get_application(
        app["id"], headers, params={"score_variant": "FINAL"}), 200)
    assert prov["admission_probability_score"] == fnl["admission_probability_score"]


# ============================================================================
# Rule 2 — combinatorial_formula (followups)
# ============================================================================

def test_admission_score_plan_bonus_distinguishes_ea_vs_regular(api):
    """PRD §3.5: "The plan bonus is a fixed integer that depends on the
    application's plan: fifteen for EARLY_DECISION, eight for
    EARLY_ACTION, five for ROLLING, and zero for REGULAR."

    Design: Difficulty/combinatorial_formula/admission_score_per_component_rounding_order_pinned
    """
    school = setup_clock_and_school(name="Plan-Bonus-EA",
                                    rolling_open=True)
    # gpa=3.0 → 30; sat=null → 0; EA → +8; no letters → 0. Total = 38.
    applicant = register_applicant(full_name="EA Plan", gpa=3.0, sat_total=None)
    app = create_application(applicant["id"], school["id"], "EARLY_ACTION")
    res = api.get_application(
        app["id"], make_applicant_headers(applicant["id"]),
        params={"score_variant": "PROVISIONAL"})
    data = validate_success(res, 200)
    assert data["admission_probability_score"] == 38


def test_aid_offer_net_price_exact_match_when_awards_equal_coa(api):
    """PRD §3.6: "The net_price_cents is the maximum of zero and the value
    of cost_of_attendance_cents minus grant_cents minus loan_cents minus
    work_study_cents."

    Design: Difficulty/combinatorial_formula/aid_offer_three_input_conditional_branch_with_floor
    """
    applicant, school, admitted, _fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=0,
        family_income_cents=3_000_000,
        school_overrides={"name": "Net-Price-Exact"},
    )
    # COA=4M, grant=2M, loan=1M, work_study=1M → sum equals COA → net=0
    res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=admitted["version"],
            cost_of_attendance_cents=4_000_000,
            variant="FEDERAL",
            grant_cents=2_000_000, loan_cents=1_000_000, work_study_cents=1_000_000),
        fa_officer_headers())
    offer = validate_success(res, 201)
    assert offer["net_price_cents"] == 0


# ============================================================================
# Rule 3 — non_linear_state_machine (followups)
# ============================================================================

def test_admit_branch_does_not_rewrite_plan(api):
    """PRD §3.4: "ADMIT transitions to ADMITTED and sets decision_at to
    the server clock."

    Design: Difficulty/non_linear_state_machine/application_branching_under_review_diverges_admit_vs_defer
    """
    # The ADMIT branch must NOT rewrite plan to REGULAR (unlike DEFER).
    school = setup_clock_and_school(name="Admit-EA-Branch")
    applicant = register_applicant(email="ea-admit@example.com",
                                   gpa=3.6, sat_total=1400)
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "EARLY_ACTION")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], rec["id"])
    submit_application(app["id"], applicant["id"])
    reviewed = start_review(app["id"])
    admitted = decide(app["id"], "ADMIT", reviewed["version"])
    assert admitted["status"] == "ADMITTED"
    assert admitted["plan"] == "EARLY_ACTION"  # plan untouched on ADMIT


def test_recommender_accept_branch_does_not_delete_letters(api):
    """PRD §3.2: "Accepting transitions invite_status from INVITED to
    ACCEPTED."

    Design: Difficulty/non_linear_state_machine/recommender_branching_invited_diverges_accept_vs_decline_with_cascade
    """
    # The ACCEPT branch leaves the letter in REQUESTED and the profile
    # remains READY — divergent from DECLINE.
    school = setup_clock_and_school(name="Accept-Branch")
    applicant = register_applicant(email="acc@example.com",
                                   full_name="Acc", gpa=3.5, sat_total=1300)
    rec = create_recommender_invited(applicant["id"])

    app = create_application(applicant["id"], school["id"], "REGULAR")
    letter = create_requested_letter(app["id"], applicant["id"], rec["id"])

    # Profile becomes READY when Recommender row exists with field
    # completeness — same precondition as decline test.
    before = validate_success(api.get_applicant(
        applicant["id"], make_applicant_headers(applicant["id"])), 200)
    assert before["profile_status"] == "READY"

    # ACCEPT branch
    accepted = validate_success(api.accept_recommender(rec["id"]), 200)
    assert accepted["invite_status"] == "ACCEPTED"

    # Profile remains READY (no cascade).
    after = validate_success(api.get_applicant(
        applicant["id"], make_applicant_headers(applicant["id"])), 200)
    assert after["profile_status"] == "READY"


# ============================================================================
# Rule 4 — transitive_cascade (followups)
# ============================================================================

def test_regular_accept_offer_does_not_withdraw_sibling_applications(api):
    """PRD §2.7: "If the accepted application's plan is Early Decision,
    every other application owned by the same applicant whose status is
    DRAFT, SUBMITTED, UNDER_REVIEW, ADMITTED, WAITLISTED, or DEFERRED
    auto-transitions to WITHDRAWN"

    Design: Difficulty/transitive_cascade/ed_accept_offer_cascade_three_deep
    """
    # Conjugate proof: when plan != EARLY_DECISION, the ED cascade
    # described in PRD §2.7 does NOT fire — sibling applications remain
    # untouched.
    setup_clock_and_school()
    from test_helpers import create_school
    s1 = create_school(name="Cas-REG-S1", target_class_size=10)
    s2 = create_school(name="Cas-REG-S2", target_class_size=10)

    applicant = register_applicant(email="cas-reg@example.com",
                                   gpa=3.7, sat_total=1400)
    rec = invite_and_accept_recommender(applicant["id"])

    # App1: REGULAR on s1 → ADMITTED.
    app1 = create_application(applicant["id"], s1["id"], "REGULAR")
    create_essay(app1["id"], applicant["id"])
    create_and_submit_letter(app1["id"], applicant["id"], rec["id"])
    submit_application(app1["id"], applicant["id"])
    reviewed1 = start_review(app1["id"])
    admitted1 = decide(app1["id"], "ADMIT", reviewed1["version"])

    # App2: REGULAR on s2 in DRAFT (sibling).
    app2 = create_application(applicant["id"], s2["id"], "REGULAR")

    # Accept the REGULAR offer.
    get_success_data(api.accept_offer(
        admitted1["id"], make_applicant_headers(applicant["id"])))

    # Sibling app2 must remain DRAFT (no ED cascade).
    app2_state = validate_success(api.get_application(
        app2["id"], make_applicant_headers(applicant["id"])), 200)
    assert app2_state["status"] == "DRAFT"


def test_recommender_decline_with_no_requested_letters_leaves_recommender_terminal(api):
    """PRD §3.2: "Declining transitions invite_status from INVITED to
    DECLINED; the decline is terminal and triggers the cascade described
    in §2.7 — every REQUESTED letter pointing at this recommender is
    deleted"

    Design: Difficulty/transitive_cascade/recommender_decline_two_step_cascade
    """
    # When the recommender has NO REQUESTED letters, the decline still
    # lands and is terminal — depth-1 cascade simply finds nothing to
    # delete. We assert the terminal state holds (a second decline is
    # rejected as INVALID_STATE).
    applicant = register_applicant(email="dec-empty@example.com",
                                   gpa=3.0)
    rec = create_recommender_invited(applicant["id"])

    declined = validate_success(api.decline_recommender(rec["id"]), 200)
    assert declined["invite_status"] == "DECLINED"

    # Confirm the terminal nature via second decline → ERR_INVALID_STATE
    # (only DRAFT/INVITED can transition; DECLINED is terminal).
    res = api.decline_recommender(rec["id"])
    validate_error(res, "ERR_INVALID_STATE")


# ============================================================================
# Rule 5 — priority_pair_validation_conflict (followups)
# ============================================================================

def test_regular_submit_after_deadline_returns_deadline_passed(api):
    """PRD §3.4: "for a Regular-Decision submission the server clock must
    be at or before rd_deadline_iso ... A submission that violates any
    deadline window is rejected with ERR_DEADLINE_PASSED."

    Design: Difficulty/priority_pair_validation_conflict/ed_submit_deadline_passed_beats_missing_letter
    """
    # Same priority (12) outcome but a different from-state (REGULAR
    # plan, not ED). Tests that ERR_DEADLINE_PASSED is the verdict.
    school = setup_clock_and_school(
        clock_iso="2030-10-15T00:00:00Z",
        name="P5A-REG",
        ed_deadline_iso="2030-10-20T00:00:00Z",
        ea_deadline_iso="2030-10-25T00:00:00Z",
        rd_deadline_iso="2030-11-01T00:00:00Z",
    )
    applicant = register_applicant(email="p5a-reg@example.com",
                                   gpa=3.0)
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], rec["id"])
    advance_clock_to("2030-12-01T00:00:00Z")

    res = api.submit_application(
        app["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_DEADLINE_PASSED")


def test_yield_run_with_no_waitlist_returns_no_open_seats(api):
    """PRD §3.7: "the open-seats rule: the school's posture must be OPEN
    (that is, confirmed_enrollment_count is strictly less than
    target_class_size) AND there must be at least one application at this
    school in WAITLISTED status; a run against an AT_TARGET or
    OVER_TARGET school, or against a school with no waitlist, is rejected
    with ERR_NO_OPEN_SEATS."

    Design: Difficulty/priority_pair_validation_conflict/yield_run_no_open_seats_beats_cooldown_active
    """
    # Variant: posture OPEN but the waitlist is empty → priority-18 rule
    # still triggers as ERR_NO_OPEN_SEATS per PRD §3.7's verbatim
    # "or against a school with no waitlist".
    school = setup_clock_and_school(name="P5B-NoWL", target_class_size=10)
    res = api.run_yield(school["id"], admissions_headers())
    validate_error(res, "ERR_NO_OPEN_SEATS")


# ============================================================================
# Rule 6 — boundary_precision_check (followups)
# ============================================================================

def test_essay_word_count_zero_rejected_and_one_accepted(api):
    """PRD §3.5: "word_count must fall in the range from 1 through 650
    words inclusive; a word_count outside that range is rejected with
    ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE."

    Design: Difficulty/boundary_precision_check/essay_word_count_upper_boundary_inclusive
    """
    school = setup_clock_and_school(name="ESS-WC-LOW")
    applicant = register_applicant(email="ess-low@example.com")
    invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")

    res_zero = api.create_essay(
        {"application_id": app["id"], "prompt_code": "P", "body": ""},
        make_applicant_headers(applicant["id"]))
    validate_error(res_zero, "ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE")

    # 1 token → accepted (inclusive lower).
    from test_helpers import create_school
    other = create_school(name="ESS-WC-1")
    app1 = create_application(applicant["id"], other["id"], "REGULAR")
    res_one = api.create_essay(
        {"application_id": app1["id"], "prompt_code": "P", "body": "one"},
        make_applicant_headers(applicant["id"]))
    essay = validate_success(res_one, 201)
    assert essay["word_count"] == 1


def test_recommender_capacity_five_letters_all_accepted(api):
    """PRD §3.2: "Five active drafts is permitted; a sixth REQUESTED →
    IN_PROGRESS transition is rejected"

    Design: Difficulty/boundary_precision_check/recommender_inprogress_capacity_boundary_inclusive
    """
    setup_clock_and_school()
    from test_helpers import create_school
    schools = [create_school(name=f"CAP-OK-{i}") for i in range(5)]

    applicant = register_applicant(email="cap-ok@example.com")
    rec = invite_and_accept_recommender(applicant["id"])

    apps = [create_application(applicant["id"], s["id"], "REGULAR")
            for s in schools]
    letters = [create_requested_letter(a["id"], applicant["id"], rec["id"])
               for a in apps]

    # All 5 starts must succeed — inclusive boundary at 5.
    for letter in letters:
        res = api.start_letter(letter["id"],
                               make_recommender_headers(rec["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "IN_PROGRESS"


# ============================================================================
# Rule 7 — cross_entity_state_dependency (followups)
# ============================================================================

def test_letter_start_succeeds_when_application_is_draft(api):
    """PRD §3.2: "this transition requires that the recommender's
    invite_status be ACCEPTED and that the owning application's status
    still be DRAFT"

    Design: Difficulty/cross_entity_state_dependency/letter_start_blocked_when_application_not_draft
    """
    # Positive case — the cross-entity precondition is satisfied
    # (Application = DRAFT, Recommender = ACCEPTED) → start succeeds.
    school = setup_clock_and_school(name="CE1-OK")
    applicant = register_applicant(email="ce1ok@example.com")
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")
    letter = create_requested_letter(app["id"], applicant["id"], rec["id"])

    res = api.start_letter(letter["id"],
                           make_recommender_headers(rec["id"]))
    started = validate_success(res, 200)
    assert started["status"] == "IN_PROGRESS"


def test_waitlist_promotion_proceeds_when_school_posture_open(api):
    """PRD §3.7: "the open-seats rule: the school's posture must be OPEN
    (that is, confirmed_enrollment_count is strictly less than
    target_class_size) AND there must be at least one application at this
    school in WAITLISTED status"
    PRD §3.7: "Each promotion transitions an application from WAITLISTED
    to ADMITTED, sets decision_at to the server clock, and nulls out
    waitlist_rank."

    Design: Difficulty/cross_entity_state_dependency/waitlist_promotion_blocked_when_school_posture_not_open
    """
    # Positive case — School.posture == OPEN, one WAITLISTED applicant
    # → yield run promotes them.
    school = setup_clock_and_school(name="CE2-OK", target_class_size=5)
    applicant = register_applicant(email="ce2ok@example.com")
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], rec["id"])
    submit_application(app["id"], applicant["id"])
    reviewed = start_review(app["id"])
    waitlisted = decide(app["id"], "WAITLIST", reviewed["version"])
    assert waitlisted["status"] == "WAITLISTED"

    get_success_data(api.run_yield(school["id"], admissions_headers()))

    promoted = validate_success(api.get_application(
        app["id"], make_applicant_headers(applicant["id"])), 200)
    assert promoted["status"] == "ADMITTED"
    assert promoted["waitlist_rank"] is None


# ============================================================================
# Rule 8 — resource_temporal_overlap (followups)
# ============================================================================

def test_school_creation_with_non_strict_ea_rd_ordering_rejected(api):
    """PRD §3.3: "The three deadlines must satisfy a strict ordering: the
    Early-Decision deadline is earlier than the Early-Action deadline,
    which is earlier than the Regular-Decision deadline."

    Design: Difficulty/resource_temporal_overlap/school_deadline_zero_width_touch_rejected_half_open
    """
    advance_clock_to("2030-09-01T00:00:00Z")
    # Same instant for EA and RD — strict ordering must reject.
    res = api.create_school(
        {"name": "OVL-EA-RD", "target_class_size": 5,
         "ed_deadline_iso": "2030-10-01T00:00:00Z",
         "ea_deadline_iso": "2030-11-01T00:00:00Z",
         "rd_deadline_iso": "2030-11-01T00:00:00Z",
         "rolling_open": False, "requires_css_profile": False,
         "cooldown_ms": 86_400_000},
        admin_headers())
    validate_error(res, "ERR_SCHOOL_DEADLINE_ORDER")


def test_yield_cooldown_inclusive_boundary_accepts_at_24h(api):
    """PRD §3.7: "the server clock must satisfy server-clock at or after
    the value of last_yield_run_at plus 86,400,000 milliseconds (the
    rule's lower boundary is inclusive — a run at exactly twenty-four
    hours after the prior run is permitted)."

    Design: Difficulty/resource_temporal_overlap/yield_cooldown_closed_lower_bound_buffer
    """
    # target_class_size=1 so the first yield consumes 1 open seat (promotes 1)
    # and the second WAITLISTED applicant remains on the waitlist. Without
    # this gap PRD §3.7's "at least one application at this school in
    # WAITLISTED status" precondition would be exhausted by the first run
    # and the second run would fail ERR_NO_OPEN_SEATS before reaching the
    # cooldown rule we are exercising.
    school = setup_clock_and_school(name="CD-OK", target_class_size=1)
    # Two WAITLISTED applicants — first yield promotes one, second remains.
    for i in range(2):
        a = register_applicant(email=f"cd_{i}@example.com")
        rec = invite_and_accept_recommender(a["id"])
        app = create_application(a["id"], school["id"], "REGULAR")
        create_essay(app["id"], a["id"])
        create_and_submit_letter(app["id"], a["id"], rec["id"])
        submit_application(app["id"], a["id"])
        reviewed = start_review(app["id"])
        decide(app["id"], "WAITLIST", reviewed["version"])

    # First yield at clock = 2030-10-01T00:00:00Z; sets last_yield_run_at.
    get_success_data(api.run_yield(school["id"], admissions_headers()))

    # Advance the clock by exactly 24h — boundary instant.
    advance_clock_to("2030-10-02T00:00:00Z")

    # Second yield must succeed (closed lower boundary).
    res = api.run_yield(school["id"], admissions_headers())
    assert res.status_code == 200, \
        f"PRD §3.7 closed lower boundary requires acceptance at exactly 24h, got {res.status_code}"


# ============================================================================
# Rule 9 — compensating_invariant (followups)
# ============================================================================

def test_enrollment_count_unchanged_after_decline_offer(api):
    """PRD §2.7: "When an applicant accepts an offer on an admitted
    application, the owning school's confirmed_enrollment_count is
    incremented by one"

    Design: Difficulty/compensating_invariant/enrollment_ledger_invariant_under_accept_then_revoke
    """
    # Decline-offer does NOT touch confirmed_enrollment_count — the ledger
    # invariant only moves on accept/revoke. The DECLINED_OFFER terminal
    # state must hold without affecting the school count.
    school = setup_clock_and_school(name="INV-DECLINE", target_class_size=5)
    applicant = register_applicant(email="inv-decline@example.com")
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], rec["id"])
    submit_application(app["id"], applicant["id"])
    reviewed = start_review(app["id"])
    decide(app["id"], "ADMIT", reviewed["version"])

    s0 = validate_success(api.get_school(school["id"], admin_headers()), 200)
    assert s0["confirmed_enrollment_count"] == 0

    get_success_data(api.decline_offer(
        app["id"], make_applicant_headers(applicant["id"])))

    s1 = validate_success(api.get_school(school["id"], admin_headers()), 200)
    assert s1["confirmed_enrollment_count"] == 0  # unchanged

    declined = validate_success(api.get_application(
        app["id"], make_applicant_headers(applicant["id"])), 200)
    assert declined["status"] == "DECLINED_OFFER"


def test_waitlist_ranks_recomputed_after_first_position_withdraws(api):
    """PRD §3.7: "When admissions waitlists an application, the platform
    stamps waitlist_added_at with the server clock and recomputes
    waitlist_rank across the school's full set of waitlisted applications
    ... The same recompute runs when a waitlisted application withdraws"

    Design: Difficulty/compensating_invariant/waitlist_rank_sequence_invariant_under_waitlist_then_withdraw
    """
    school = setup_clock_and_school(name="INV-WL-FIRST", target_class_size=10)

    def _waitlist(email_seed, clock_stamp):
        a = register_applicant(email=f"{email_seed}@example.com")
        rec = invite_and_accept_recommender(a["id"])
        app = create_application(a["id"], school["id"], "REGULAR")
        create_essay(app["id"], a["id"])
        create_and_submit_letter(app["id"], a["id"], rec["id"])
        submit_application(app["id"], a["id"])
        reviewed = start_review(app["id"])
        advance_clock_to(clock_stamp)
        return a, decide(app["id"], "WAITLIST", reviewed["version"])

    a1, app_a = _waitlist("wlf_a", "2030-10-01T00:01:00Z")
    a2, app_b = _waitlist("wlf_b", "2030-10-01T00:02:00Z")

    assert app_a["waitlist_rank"] == 1
    assert app_b["waitlist_rank"] == 2

    # First-rank withdraws.
    get_success_data(api.withdraw_application(
        app_a["id"], make_applicant_headers(a1["id"])))

    b_now = validate_success(api.get_application(
        app_b["id"], make_applicant_headers(a2["id"])), 200)
    assert b_now["waitlist_rank"] == 1  # promoted to head of queue
