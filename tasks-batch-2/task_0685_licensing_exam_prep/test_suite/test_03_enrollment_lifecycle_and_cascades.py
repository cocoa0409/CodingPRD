"""Enrollment certification branching, claim decisions, and terminal cascades.

Covers difficulty queue (A): non_linear_state_machine (certify PASS/FAIL, claim
APPROVE/DENY), transitive_cascade (money-back depth-3, pass depth-2),
cross_entity_state_dependency (program-published, balance gate),
priority_pair_validation_conflict (claim state vs eligibility),
and corner queue (B) state-machine / error instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment, setup_financed_active_enrollment,
    setup_eligible_failed_enrollment, setup_ineligible_failed_enrollment,
    create_published_program, create_program, create_plan, create_learner,
    create_enrollment, create_cohort, activate, get_enrollment, list_installments,
    pay_installment, certify, file_claim, decide_claim, join_cohort,
    make_learner_headers,
)

PROCTOR = TEST_USERS["exam_proctor_headers"]
ADMIN = TEST_USERS["content_admin_headers"]


# ==========================================================================
# non_linear_state_machine / enrollment_branches_active_to_pass_vs_fail_divergent_side_effects
# ==========================================================================
def test_certify_pass_moves_to_passed(api):
    """Certifying PASS moves the enrollment to the terminal PASSED status.

    PRD §3.5: "When PASS succeeds, `exam_outcome` becomes `PASS`, the enrollment moves from
    `ACTIVE` to `PASSED` (a terminal status), and as a cascade every `JOINED` cohort
    membership of this enrollment is dropped to `DROPPED` — each affected cohort decrements
    its `seats_taken`, recomputes its derived status, and is re-versioned, and each
    membership is itself re-versioned."

    Design: Difficulty/non_linear_state_machine/enrollment_branches_active_to_pass_vs_fail_divergent_side_effects
    """
    ctx = setup_active_enrollment(
        license_code="RE-BROK",
        plan_overrides={"tier": "BASIC", "total_price_cents": 30000, "included_mock_credits": 3},
        learner_email="pa@x.com",
        pay_in_full=True,
    )
    enr = ctx["enrollment"]
    result = validate_success(api.certify_exam(enr["id"], {"outcome": "PASS"}, PROCTOR))
    assert result["status"] == "PASSED"
    assert result["exam_outcome"] == "PASS"


def test_certify_fail_moves_to_failed_with_eligibility_snapshot(api):
    """Certifying FAIL moves to FAILED and snapshots guarantee_eligible (false on a non-guarantee plan).

    PRD §3.5: "A FAIL certification has no balance precondition. On FAIL the system snapshots
    `guarantee_eligible` — recording, at that instant, whether the activity-and-readiness
    thresholds described below were met — then sets `exam_outcome` to `FAIL`, moves the
    enrollment from `ACTIVE` to `FAILED`, and increments the enrollment's `version`."

    Design: Difficulty/non_linear_state_machine/enrollment_branches_active_to_pass_vs_fail_divergent_side_effects
    """
    ctx = setup_active_enrollment(
        license_code="RE-BROK2",
        plan_overrides={"tier": "BASIC", "total_price_cents": 30000, "included_mock_credits": 3},
        learner_email="fa@x.com",
    )
    enr = ctx["enrollment"]
    result = validate_success(api.certify_exam(enr["id"], {"outcome": "FAIL"}, PROCTOR))
    assert result["status"] == "FAILED"
    assert result["exam_outcome"] == "FAIL"
    # plan.pass_guarantee is false -> guarantee_eligible snapshot must be false
    assert result["guarantee_eligible"] is False


# ==========================================================================
# non_linear_state_machine / claim_branches_submitted_to_approve_vs_deny_divergent_side_effects
# ==========================================================================
def test_claim_approve_retake_extension_keeps_enrollment_failed(api):
    """Approving a RETAKE_EXTENSION claim sets refund 0 and leaves the enrollment FAILED.

    PRD §3.5: "An approval sets the claim to `APPROVED`, re-versions it, and then branches on
    the remedy."
    PRD §3.5: "When the approved remedy is `RETAKE_EXTENSION`, the claim's
    `refund_amount_cents` is zero and the enrollment stays in `FAILED` (its retake window is
    extended)."

    Design: Difficulty/non_linear_state_machine/claim_branches_submitted_to_approve_vs_deny_divergent_side_effects
    """
    ctx = setup_eligible_failed_enrollment(
        license_code="CPA-REG",
        plan_overrides={"tier": "PRO", "total_price_cents": 50000, "down_payment_pct": 0.00,
                        "financing_months": 1, "included_mock_credits": 5,
                        "pass_guarantee": True, "guarantee_refund_pct": 0.50},
        learner_email="rx@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    claim = file_claim(enr["id"], learner["id"], "RETAKE_EXTENSION")
    decided = validate_success(api.decide_pass_guarantee_claim(claim["id"], {"decision": "APPROVE"}, PROCTOR))
    assert decided["status"] == "APPROVED"
    assert decided["refund_amount_cents"] == 0
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "FAILED", "RETAKE_EXTENSION must not refund or terminate the enrollment"


def test_claim_deny_terminates_claim_only(api):
    """Denying a claim sets it to DENIED without touching the enrollment status.

    PRD §3.5: "A denial requires only the `FAILED`-state check and then sets the claim to
    `DENIED`, re-versioning the claim."

    Design: Difficulty/non_linear_state_machine/claim_branches_submitted_to_approve_vs_deny_divergent_side_effects
    """
    ctx = setup_eligible_failed_enrollment(
        license_code="CPA-REG2",
        plan_overrides={"tier": "PRO", "total_price_cents": 50000, "down_payment_pct": 0.00,
                        "financing_months": 1, "included_mock_credits": 5,
                        "pass_guarantee": True, "guarantee_refund_pct": 0.50},
        learner_email="rx2@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    claim = file_claim(enr["id"], learner["id"], "MONEY_BACK")
    decided = validate_success(api.decide_pass_guarantee_claim(claim["id"], {"decision": "DENY"}, PROCTOR))
    assert decided["status"] == "DENIED"
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "FAILED", "DENY leaves the enrollment FAILED"


# ==========================================================================
# transitive_cascade / moneyback_approval_cascades_enrollment_installments_and_cohort_depth3
# ==========================================================================
def test_money_back_approval_cascades_to_refunded_void_and_cohort_reopen(api):
    """Approving a MONEY_BACK claim refunds, voids DUE installments, drops membership, reopens cohort.

    PRD §3.5: "When the approved remedy is `MONEY_BACK`, the system computes the refund and
    then drives the enrollment from `FAILED` to `REFUNDED` as a cascade."
    PRD §3.5: "Driving the enrollment to `REFUNDED` voids every remaining `DUE` installment
    (each moves to `VOID`, bringing `financing_balance_cents` to zero), drops every `JOINED`
    cohort membership of the enrollment to `DROPPED` with the same cohort seat-recompute and
    re-versioning cascade described above, sets the enrollment `status` to `REFUNDED` (a
    terminal status), and increments the enrollment's `version`."
    PRD §3.8: "when a drop later brings `seats_taken` back below `capacity`, it flips from
    `FULL` back to `OPEN`."

    Design: Difficulty/transitive_cascade/moneyback_approval_cascades_enrollment_installments_and_cohort_depth3
    """
    # PRO money-back financed plan; down paid + activated + eligible + FAILED, with a capacity-1 cohort joined.
    prog = create_published_program("NCLEX-PN", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=75)
    plan = create_plan(tier="PRO", total_price_cents=100000, down_payment_pct=0.30,
                       financing_months=6, included_mock_credits=5,
                       pass_guarantee=True, guarantee_refund_pct=0.50)
    cohort = create_cohort(prog["id"], title="Live Review", capacity=1)
    learner = create_learner(email="csc@x.com", full_name="Cascade")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    insts = list_installments(enr["id"], learner["id"])
    pay_installment(enr["id"], insts[0]["id"], learner["id"])
    activate(enr["id"], learner["id"])
    from test_helpers import accumulate_eligibility
    accumulate_eligibility(enr["id"], learner["id"], clock_1="2026-05-09T09:00:00Z", clock_2="2026-05-10T09:00:00Z")
    membership = join_cohort(cohort["id"], enr["id"], learner["id"],
                             session_start_utc="2026-06-01T10:00:00Z", session_end_utc="2026-06-01T12:00:00Z")
    certify(enr["id"], "FAIL")
    claim = file_claim(enr["id"], learner["id"], "MONEY_BACK")

    validate_success(api.decide_pass_guarantee_claim(claim["id"], {"decision": "APPROVE"}, PROCTOR))

    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "REFUNDED"
    assert enr["financing_balance_cents"] == 0
    # all prior DUE installments are now VOID
    void_insts, void_meta = validate_paginated(api.list_installments(enr["id"], make_learner_headers(learner["id"]), params={"status": "VOID"}))
    assert void_meta["total_count"] >= 1, "remaining DUE installments must be voided"
    mem = validate_success(api.get_cohort_membership(membership["id"], make_learner_headers(learner["id"])))
    assert mem["status"] == "DROPPED"
    refreshed_cohort = validate_success(api.get_cohort(cohort["id"], ADMIN))
    assert refreshed_cohort["seats_taken"] == 0
    assert refreshed_cohort["status"] == "OPEN"


def test_money_back_approval_voids_due_installments_and_zeros_balance(api):
    """The REFUNDED cascade voids remaining DUE installments and brings the balance to zero.

    PRD §3.5: "Driving the enrollment to `REFUNDED` voids every remaining `DUE` installment
    (each moves to `VOID`, bringing `financing_balance_cents` to zero), drops every `JOINED`
    cohort membership of the enrollment to `DROPPED` with the same cohort seat-recompute and
    re-versioning cascade described above, sets the enrollment `status` to `REFUNDED` (a
    terminal status), and increments the enrollment's `version`."

    Design: Difficulty/transitive_cascade/moneyback_approval_cascades_enrollment_installments_and_cohort_depth3
    """
    # financed PRO money-back plan; down paid + activated + eligible + FAILED, no cohort joined.
    prog = create_published_program("NCLEX-PN2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=75)
    plan = create_plan(tier="PRO", total_price_cents=100000, down_payment_pct=0.30,
                       financing_months=6, included_mock_credits=5,
                       pass_guarantee=True, guarantee_refund_pct=0.50)
    learner = create_learner(email="csc2@x.com", full_name="Cascade2")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    insts = list_installments(enr["id"], learner["id"])
    pay_installment(enr["id"], insts[0]["id"], learner["id"])
    activate(enr["id"], learner["id"])
    from test_helpers import accumulate_eligibility
    accumulate_eligibility(enr["id"], learner["id"], clock_1="2026-05-11T09:00:00Z", clock_2="2026-05-12T09:00:00Z")
    # confirm there is still an outstanding balance before refund
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["financing_balance_cents"] > 0
    certify(enr["id"], "FAIL")
    claim = file_claim(enr["id"], learner["id"], "MONEY_BACK")

    validate_success(api.decide_pass_guarantee_claim(claim["id"], {"decision": "APPROVE"}, PROCTOR))

    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "REFUNDED"
    assert enr["financing_balance_cents"] == 0
    remaining_due, due_meta = validate_paginated(
        api.list_installments(enr["id"], make_learner_headers(learner["id"]), params={"status": "DUE"}))
    assert due_meta["total_count"] == 0, "no installment may remain DUE after the REFUNDED cascade"


# ==========================================================================
# transitive_cascade / pass_certification_cascades_membership_drop_and_cohort_reopen_depth2
# ==========================================================================
def test_pass_certification_cascades_membership_drop_and_cohort_reopen(api):
    """PASS certification drops the JOINED membership and reopens a capacity-1 cohort.

    PRD §3.5: "When PASS succeeds, `exam_outcome` becomes `PASS`, the enrollment moves from
    `ACTIVE` to `PASSED` (a terminal status), and as a cascade every `JOINED` cohort
    membership of this enrollment is dropped to `DROPPED` — each affected cohort decrements
    its `seats_taken`, recomputes its derived status, and is re-versioned, and each
    membership is itself re-versioned."
    PRD §3.8: "when a drop later brings `seats_taken` back below `capacity`, it flips from
    `FULL` back to `OPEN`."

    Design: Difficulty/transitive_cascade/pass_certification_cascades_membership_drop_and_cohort_reopen_depth2
    """
    ctx = setup_active_enrollment(
        license_code="RE-APPR",
        plan_overrides={"tier": "BASIC", "total_price_cents": 30000, "included_mock_credits": 3},
        learner_email="p2@x.com",
        pay_in_full=True,
    )
    enr, learner, prog = ctx["enrollment"], ctx["learner"], ctx["program"]
    cohort = create_cohort(prog["id"], title="Cap1", capacity=1)
    membership = join_cohort(cohort["id"], enr["id"], learner["id"],
                             session_start_utc="2026-06-02T10:00:00Z", session_end_utc="2026-06-02T12:00:00Z")
    full_cohort = validate_success(api.get_cohort(cohort["id"], ADMIN))
    assert full_cohort["status"] == "FULL" and full_cohort["seats_taken"] == 1

    validate_success(api.certify_exam(enr["id"], {"outcome": "PASS"}, PROCTOR))

    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "PASSED"
    mem = validate_success(api.get_cohort_membership(membership["id"], make_learner_headers(learner["id"])))
    assert mem["status"] == "DROPPED"
    reopened = validate_success(api.get_cohort(cohort["id"], ADMIN))
    assert reopened["seats_taken"] == 0 and reopened["status"] == "OPEN"


def test_pass_certification_drops_all_joined_memberships(api):
    """PASS certification drops every JOINED membership of the enrollment across cohorts.

    PRD §3.5: "When PASS succeeds, `exam_outcome` becomes `PASS`, the enrollment moves from
    `ACTIVE` to `PASSED` (a terminal status), and as a cascade every `JOINED` cohort
    membership of this enrollment is dropped to `DROPPED` — each affected cohort decrements
    its `seats_taken`, recomputes its derived status, and is re-versioned, and each
    membership is itself re-versioned."

    Design: Difficulty/transitive_cascade/pass_certification_cascades_membership_drop_and_cohort_reopen_depth2
    """
    ctx = setup_active_enrollment(
        license_code="RE-APPR2",
        plan_overrides={"tier": "BASIC", "total_price_cents": 30000, "included_mock_credits": 3},
        learner_email="p2b@x.com",
        pay_in_full=True,
    )
    enr, learner, prog = ctx["enrollment"], ctx["learner"], ctx["program"]
    # join two distinct cohorts with non-overlapping windows
    c1 = create_cohort(prog["id"], title="C1", capacity=5)
    c2 = create_cohort(prog["id"], title="C2", capacity=5)
    join_cohort(c1["id"], enr["id"], learner["id"],
                session_start_utc="2026-06-02T08:00:00Z", session_end_utc="2026-06-02T09:00:00Z")
    join_cohort(c2["id"], enr["id"], learner["id"],
                session_start_utc="2026-06-02T10:00:00Z", session_end_utc="2026-06-02T11:00:00Z")

    validate_success(api.certify_exam(enr["id"], {"outcome": "PASS"}, PROCTOR))

    memberships, _ = validate_paginated(
        api.list_memberships_by_enrollment(make_learner_headers(learner["id"]), params={"enrollment_id": enr["id"]}))
    assert len(memberships) == 2
    assert all(m["status"] == "DROPPED" for m in memberships), "all JOINED memberships must drop on PASS"
    for c in (c1, c2):
        refreshed = validate_success(api.get_cohort(c["id"], ADMIN))
        assert refreshed["seats_taken"] == 0


# ==========================================================================
# cross_entity_state_dependency / enrollment_activation_requires_program_published
# ==========================================================================
def test_activate_against_draft_program_rejected(api):
    """Activating an enrollment whose program is still DRAFT returns ERR_PROGRAM_NOT_PUBLISHED.

    PRD §3.3: "The referenced license program must be `PUBLISHED`, or the activation is
    rejected with `ERR_PROGRAM_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_requires_program_published
    """
    prog = create_program("DRAFTP", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)  # not published
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    learner = create_learner(email="np@x.com", full_name="NoPub")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False)
    resp = api.activate_enrollment(enr["id"], make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_PUBLISHED.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "DRAFT"


def test_activate_against_draft_program_blocked_even_with_down_payment_paid(api):
    """Activation is blocked by the unpublished program even when the down payment is paid.

    PRD §3.3: "The referenced license program must be `PUBLISHED`, or the activation is
    rejected with `ERR_PROGRAM_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_requires_program_published
    """
    prog = create_program("DRAFTP2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)  # DRAFT
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="np2@x.com", full_name="NoPub2")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    insts = list_installments(enr["id"], learner["id"])
    pay_installment(enr["id"], insts[0]["id"], learner["id"])  # down payment paid
    resp = api.activate_enrollment(enr["id"], make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_PUBLISHED.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "DRAFT"


# ==========================================================================
# cross_entity_state_dependency / pass_certification_requires_zero_installment_balance
# ==========================================================================
def test_certify_pass_with_outstanding_balance_rejected(api):
    """Certifying PASS while a financing balance remains returns ERR_BALANCE_OUTSTANDING.

    PRD §3.5: "A PASS certification additionally requires that the enrollment owe nothing:
    if `financing_balance_cents` is greater than zero, the PASS is rejected with
    `ERR_BALANCE_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/pass_certification_requires_zero_installment_balance
    """
    ctx = setup_financed_active_enrollment(
        license_code="BAL-P",
        plan_overrides={"tier": "PLUS", "total_price_cents": 120000, "down_payment_pct": 0.20,
                        "financing_months": 6, "included_mock_credits": 8},
        learner_email="bal@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    # only the down payment (24000) is paid -> balance 96000
    resp = api.certify_exam(enr["id"], {"outcome": "PASS"}, PROCTOR)
    validate_error(resp, ApiErrorId.ERR_BALANCE_OUTSTANDING.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "ACTIVE"
    assert enr["financing_balance_cents"] == 96000


def test_certify_pass_succeeds_once_balance_paid_to_zero(api):
    """Once every installment is PAID (balance 0), PASS certification succeeds.

    PRD §3.5: "A PASS certification additionally requires that the enrollment owe nothing:
    if `financing_balance_cents` is greater than zero, the PASS is rejected with
    `ERR_BALANCE_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/pass_certification_requires_zero_installment_balance
    """
    ctx = setup_financed_active_enrollment(
        license_code="BAL-P2",
        plan_overrides={"tier": "PLUS", "total_price_cents": 120000, "down_payment_pct": 0.20,
                        "financing_months": 6, "included_mock_credits": 8},
        learner_email="bal2@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    # pay every remaining DUE installment -> balance 0
    due, _ = validate_paginated(api.list_installments(enr["id"], make_learner_headers(learner["id"]), params={"status": "DUE"}))
    for inst in due:
        pay_installment(enr["id"], inst["id"], learner["id"])
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["financing_balance_cents"] == 0
    result = validate_success(api.certify_exam(enr["id"], {"outcome": "PASS"}, PROCTOR))
    assert result["status"] == "PASSED"


# ==========================================================================
# priority_pair_validation_conflict / claim_decide_state_beats_guarantee_eligibility
# ==========================================================================
def test_decide_terminal_claim_returns_invalid_state_over_eligibility(api):
    """Deciding an already-DENIED claim returns ERR_INVALID_STATE, not ERR_GUARANTEE_NOT_ELIGIBLE.

    PRD §3.5: "Either decision first requires the owning enrollment to be in `FAILED` status,
    or the decision is rejected with `ERR_INVALID_STATE`."
    PRD §2.5: "the system evaluates them in a fixed priority order and returns the first
    failure encountered."

    Design: Difficulty/priority_pair_validation_conflict/claim_decide_state_beats_guarantee_eligibility
    """
    # ineligible FAILED enrollment (guarantee plan, no activity), claim filed and DENIED;
    # re-deciding the terminal claim: state check (FAILED-state of claim's lifecycle) fires first.
    ctx = setup_ineligible_failed_enrollment(license_code="CPA-BEC", learner_email="ineli@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    claim = file_claim(enr["id"], learner["id"], "MONEY_BACK")
    decide_claim(claim["id"], "DENY")  # claim now DENIED (terminal)
    resp = api.decide_pass_guarantee_claim(claim["id"], {"decision": "APPROVE"}, PROCTOR)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_GUARANTEE_NOT_ELIGIBLE.value


def test_redeny_terminal_claim_returns_invalid_state_over_eligibility(api):
    """Re-denying an already-DENIED claim on an ineligible enrollment also returns ERR_INVALID_STATE.

    PRD §3.5: "An `ExamProctor` then **decides** a `SUBMITTED` claim, supplying a `decision`
    of APPROVE or DENY."
    PRD §2.5: "seventh, that the target resource is in a legal state for the requested
    transition (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/claim_decide_state_beats_guarantee_eligibility
    """
    ctx = setup_ineligible_failed_enrollment(license_code="CPA-BEC2", learner_email="ineli2@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    claim = file_claim(enr["id"], learner["id"], "MONEY_BACK")
    decide_claim(claim["id"], "DENY")  # terminal DENIED
    resp = api.decide_pass_guarantee_claim(claim["id"], {"decision": "DENY"}, PROCTOR)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_GUARANTEE_NOT_ELIGIBLE.value


# ==========================================================================
# Corner / state_machines / certify_exam_twice_already_certified
# ==========================================================================
def test_certify_exam_twice_already_certified(api):
    """Certifying a second outcome after exam_outcome != PENDING returns ERR_EXAM_ALREADY_CERTIFIED.

    PRD §3.5: "Certification is permitted only while `exam_outcome` is still `PENDING`; a
    second certification attempt is rejected with `ERR_EXAM_ALREADY_CERTIFIED`."

    Design: Corner/state_machines/certify_exam_twice_already_certified
    """
    ctx = setup_active_enrollment(license_code="CT2", learner_email="ct2@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    validate_success(api.certify_exam(enr["id"], {"outcome": "FAIL"}, PROCTOR))
    resp = api.certify_exam(enr["id"], {"outcome": "PASS"}, PROCTOR)
    validate_error(resp, ApiErrorId.ERR_EXAM_ALREADY_CERTIFIED.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "FAILED"


# ==========================================================================
# Corner / state_machines / activate_already_active_enrollment_invalid_state
# ==========================================================================
def test_activate_already_active_enrollment_invalid_state(api):
    """Activating an already-ACTIVE enrollment returns ERR_INVALID_STATE.

    PRD §2.5: "seventh, that the target resource is in a legal state for the requested
    transition (`ERR_INVALID_STATE`)."
    PRD §3.3: "A learner **activates** a `DRAFT` enrollment to begin studying, transitioning
    it to `ACTIVE`."

    Design: Corner/state_machines/activate_already_active_enrollment_invalid_state
    """
    ctx = setup_active_enrollment(license_code="AA", learner_email="aa@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    resp = api.activate_enrollment(enr["id"], make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Corner / state_machines / pay_installment_on_terminal_enrollment_invalid_state
# ==========================================================================
def test_pay_installment_on_withdrawn_enrollment_invalid_state(api):
    """Paying an installment whose enrollment is WITHDRAWN returns ERR_INVALID_STATE.

    PRD §3.2: "Paying is permitted only while the owning enrollment is in `DRAFT` or
    `ACTIVE`; in any other enrollment state the payment is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pay_installment_on_terminal_enrollment_invalid_state
    """
    prog = create_program("PIT", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="pit@x.com", full_name="PIT")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    insts = list_installments(enr["id"], learner["id"])
    inst2 = insts[1]
    validate_success(api.withdraw_enrollment(enr["id"], make_learner_headers(learner["id"])))
    resp = api.pay_installment(enr["id"], inst2["id"], make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "WITHDRAWN"


# ==========================================================================
# Corner / errors / error_plan_archived_on_activation
# ==========================================================================
def test_activate_with_archived_plan_rejected(api):
    """Activating an enrollment whose plan was archived returns ERR_PLAN_ARCHIVED.

    PRD §3.3: "The referenced subscription plan must be `ACTIVE`, or it is rejected with
    `ERR_PLAN_ARCHIVED`."

    Design: Corner/errors/error_plan_archived_on_activation
    """
    prog = create_published_program("ARC", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    learner = create_learner(email="arc@x.com", full_name="Arc")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False)
    validate_success(api.archive_subscription_plan(plan["id"], ADMIN))
    resp = api.activate_enrollment(enr["id"], make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_ARCHIVED.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "DRAFT"


# ==========================================================================
# Corner / errors / error_down_payment_unpaid_on_financed_activation
# ==========================================================================
def test_activate_financed_without_down_payment_rejected(api):
    """Activating a financed enrollment before paying installment 1 returns ERR_DOWN_PAYMENT_UNPAID.

    PRD §3.3: "if the enrollment is financed, the down-payment installment — the one at
    `sequence_no` 1 — must already be `PAID`, or the activation is rejected with
    `ERR_DOWN_PAYMENT_UNPAID`."

    Design: Corner/errors/error_down_payment_unpaid_on_financed_activation
    """
    prog = create_published_program("DPU", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="dpu@x.com", full_name="Dpu")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    resp = api.activate_enrollment(enr["id"], make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_DOWN_PAYMENT_UNPAID.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "DRAFT"


# ==========================================================================
# Corner / errors / error_guarantee_not_eligible_positive_path
# ==========================================================================
def test_approve_claim_on_ineligible_enrollment_rejected(api):
    """Approving a claim on an ineligible FAILED enrollment returns ERR_GUARANTEE_NOT_ELIGIBLE.

    PRD §3.5: "Approval additionally requires that the owning enrollment's
    `guarantee_eligible` be true; an attempt to approve an ineligible claim is rejected with
    `ERR_GUARANTEE_NOT_ELIGIBLE`."

    Design: Corner/errors/error_guarantee_not_eligible_positive_path
    """
    ctx = setup_ineligible_failed_enrollment(license_code="GNE", learner_email="gne@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    claim = file_claim(enr["id"], learner["id"], "MONEY_BACK")
    resp = api.decide_pass_guarantee_claim(claim["id"], {"decision": "APPROVE"}, PROCTOR)
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_ELIGIBLE.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "FAILED"
