"""Enrollment, dispute, and plan-lifecycle state machines
(corner: state_machines; difficulty: non_linear_state_machine)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    make_registrar_headers,
    create_district, create_student, create_dispute, setup_active_plan,
    setup_eligible_student,
)
from test_helpers.api_client import api_client

SC = TEST_USERS["state_coordinator_headers"]


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_immediate_enroll_without_records(api):
    """PRD §3.2: "This succeeds regardless of whether `records_received` is true — arrival of prior-school records is deliberately **not** a precondition, so a homeless child is never blocked from enrolling for want of paperwork."

    Design: Corner/state_machines/student_immediate_enroll_without_records
    """
    d = create_district()
    reg = make_registrar_headers(d["id"])
    s = get_success_data(api.create_student(
        {"first_name": "Imm", "last_name": "Ediate", "birthdate": "2012-01-01",
         "enrolled_district_id": d["id"], "origin_district_id": d["id"],
         "living_situation": "UNSHELTERED", "records_received": False}, reg))
    data = validate_success(api.enroll_student(s["id"], reg))
    assert data["status"] == "ENROLLED"


def test_approve_plan_from_draft_is_invalid_state(api):
    """PRD §3.5: "Submitting advances `DRAFT` to `PROPOSED`. From `PROPOSED`, the plan either advances to `APPROVED` or is denied to the terminal `DENIED`."
    PRD §3.5: "Every transition is valid only from its named source state, raising `ERR_INVALID_STATE` otherwise."

    Design: Corner/state_machines/plan_approve_from_draft_invalid_state
    """
    ctx = setup_eligible_student()
    plan = get_success_data(api.create_plan(
        {"student_id": ctx["student"]["id"], "origin_district_id": ctx["district"]["id"],
         "serving_district_id": ctx["district"]["id"], "route_miles": 20}, SC))
    validate_error(api.approve_plan(plan["id"], SC), ApiErrorId.ERR_INVALID_STATE.value, 409)
    still = validate_success(api.get_plan(plan["id"], SC))
    assert still["status"] == "DRAFT", "a rejected transition fires no side effects"


def test_enroll_twice_rejected(api):
    """PRD §3.2: "Enrollment is only valid from `INTAKE`; attempting it from any
    other state raises `ERR_INVALID_STATE`."

    Design: Corner/state_machines/student_enroll_twice_idempotency_rejected
    """
    d = create_district()
    reg = make_registrar_headers(d["id"])
    s = create_student(d["id"], headers=reg)
    validate_success(api.enroll_student(s["id"], reg))
    validate_error(api.enroll_student(s["id"], reg), ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_resolve_after_terminal_rejected(api):
    """PRD §3.4: "Each of these transitions is valid only from its named source
    state; an out-of-state attempt raises `ERR_INVALID_STATE`."
    PRD §3.4: "Both terminal resolutions are reachable only from `UNDER_REVIEW`."

    Design: Corner/state_machines/dispute_resolve_after_terminal_invalid_state
    """
    d = create_district()
    s = create_student(d["id"])
    dsp = create_dispute(s["id"], dispute_type="TRANSPORT", description="Route too far")
    api.begin_review(dsp["id"], SC)
    validate_success(api.resolve_dispute(dsp["id"], {"outcome": "DENIED"}, SC))
    validate_error(api.resolve_dispute(dsp["id"], {"outcome": "UPHELD"}, SC),
                   ApiErrorId.ERR_INVALID_STATE.value, 409)
    still = validate_success(api.get_dispute(dsp["id"], SC))
    assert still["status"] == "RESOLVED_DENIED"


def test_resolve_upheld_restores_eligibility(api):
    """PRD §3.4: "When the `outcome` is `UPHELD`, the dispute moves to
    `RESOLVED_UPHELD`, records `outcome` `UPHELD`, and — if the student is not
    already `ELIGIBLE` — restores eligibility exactly as a favorable determination
    would: the student's `eligibility_status` is set to `ELIGIBLE`, and if the
    student has no `ACTIVE` benefit link, a new `BenefitLink` (`AUTO_ELIGIBILITY`,
    `ACTIVE`) is created and the district's `categorical_eligible_count` is incremented."

    Design: Corner/state_machines/dispute_resolve_upheld_restores_eligibility
    """
    d = create_district()
    s = create_student(d["id"], living_situation="DOUBLED_UP")
    det = get_success_data(api.create_determination(
        s["id"], {"category": "HOMELESS", "basis": "DOUBLED_UP", "decision": "INELIGIBLE",
                  "effective_date": "2026-05-01", "expected_student_version": s["version"]}, SC))
    api.finalize_determination(det["id"], SC)
    dsp = create_dispute(s["id"], dispute_type="ELIGIBILITY", description="Should be eligible")
    api.begin_review(dsp["id"], SC)
    resolved = validate_success(api.resolve_dispute(dsp["id"], {"outcome": "UPHELD"}, SC))
    assert resolved["status"] == "RESOLVED_UPHELD"
    student = validate_success(api.get_student(s["id"], SC))
    assert student["eligibility_status"] == "ELIGIBLE"
    district = validate_success(api.get_district(d["id"], SC))
    assert district["categorical_eligible_count"] == 1


def test_finalize_on_withdrawn_student_rejected(api):
    """PRD §3.3: "Finalization is permitted only from `DRAFT`; it additionally
    requires that the subject student not be `WITHDRAWN`, raising
    `ERR_STUDENT_WITHDRAWN` otherwise."

    Design: Corner/state_machines/student_withdrawn_blocks_operations
    """
    d = create_district()
    reg = make_registrar_headers(d["id"])
    s = create_student(d["id"], headers=reg)
    enrolled = validate_success(api.enroll_student(s["id"], reg))
    # DRAFT determination created while the student is still enrolled.
    det = get_success_data(api.create_determination(
        s["id"], {"category": "HOMELESS", "basis": "SHELTER", "decision": "ELIGIBLE",
                  "effective_date": "2026-05-01", "expected_student_version": enrolled["version"]}, SC))
    validate_success(api.withdraw_student(s["id"], reg))
    validate_error(api.finalize_determination(det["id"], SC),
                   ApiErrorId.ERR_STUDENT_WITHDRAWN.value, 409)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine — dispute cyclic loop
# ---------------------------------------------------------------------------
def _dispute_to_info_requested():
    d = create_district()
    s = create_student(d["id"])
    dsp = create_dispute(s["id"], dispute_type="ELIGIBILITY", description="Contest determination")
    api_client.begin_review(dsp["id"], SC)
    api_client.request_info(dsp["id"], SC)
    return dsp


def test_dispute_resubmit_returns_to_filed(api):
    """PRD §3.4: "From `INFO_REQUESTED`, a `Liaison` or `StateCoordinator`
    resubmits, returning the dispute to `FILED` so a fresh review round can start —
    this back-edge is what makes the machine cyclic."

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_info_request_loop
    """
    dsp = _dispute_to_info_requested()
    data = validate_success(api.resubmit_dispute(dsp["id"], TEST_USERS["liaison_headers"]))
    assert data["status"] == "FILED", "resubmit returns INFO_REQUESTED -> FILED"


def test_dispute_review_round_restarts_after_resubmit(api):
    """PRD §3.4: "A `StateCoordinator` begins review, moving the dispute from
    `FILED` to `UNDER_REVIEW`."
    PRD §3.4: "From `INFO_REQUESTED`, a `Liaison` or `StateCoordinator` resubmits,
    returning the dispute to `FILED` so a fresh review round can start — this
    back-edge is what makes the machine cyclic."

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_info_request_loop
    """
    dsp = _dispute_to_info_requested()
    api.resubmit_dispute(dsp["id"], TEST_USERS["liaison_headers"])
    data = validate_success(api.begin_review(dsp["id"], SC))
    assert data["status"] == "UNDER_REVIEW", "begin-review is valid again after the cycle"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine — plan branch + active/suspend revert
# ---------------------------------------------------------------------------
def test_plan_suspend_from_active(api):
    """PRD §3.5: "from `ACTIVE`, suspension moves it to `SUSPENDED` and resumption moves it back to `ACTIVE`"

    Design: Difficulty/non_linear_state_machine/plan_branch_approve_and_active_suspend_revert
    """
    ctx = setup_active_plan(route_miles=20)
    data = validate_success(api.suspend_plan(ctx["plan"]["id"], SC))
    assert data["status"] == "SUSPENDED"


def test_plan_resume_reverts_to_active(api):
    """PRD §3.5: "from `ACTIVE`, suspension moves it to `SUSPENDED` and resumption moves it back to `ACTIVE`"

    Design: Difficulty/non_linear_state_machine/plan_branch_approve_and_active_suspend_revert
    """
    ctx = setup_active_plan(route_miles=20)
    api.suspend_plan(ctx["plan"]["id"], SC)
    data = validate_success(api.resume_plan(ctx["plan"]["id"], SC))
    assert data["status"] == "ACTIVE", "SUSPENDED -> ACTIVE revert loop"
