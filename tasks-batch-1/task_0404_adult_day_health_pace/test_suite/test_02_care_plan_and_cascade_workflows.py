"""Care-plan review cycle, disenrollment fork, and multi-hop cascades.

Difficulty queue A: non_linear_state_machine, transitive_cascade.
"""
from test_helpers import (
    api_client, get_success_data,
    create_program, set_clock, create_participant, create_certified_loc,
    create_active_care_plan, create_in_review_care_plan, create_active_med_order,
    setup_enrolled_participant,
    submit_disenrollment, approve_disenrollment, finalize_disenrollment,
    get_participant_version,
    TEST_USERS,
)

IC = TEST_USERS["intake_coordinator_headers"]
MD = TEST_USERS["medical_director_headers"]
NS = TEST_USERS["nurse_staff_headers"]
BS = TEST_USERS["billing_specialist_headers"]


# ===========================================================================
# non_linear_state_machine / care_plan_review_revision_cycle
# ===========================================================================
def test_care_plan_resubmit_after_revision_returns_to_in_review():
    """PRD 3.3: "From REVISION the IntakeCoordinator resubmits, returning the plan to
    IN_REVIEW; this resubmission likewise requires goal_count of at least 1
    (ERR_CARE_PLAN_NO_GOALS) and that the plan be in REVISION (ERR_INVALID_STATE)."
    PRD 3.3: "This IN_REVIEW → REVISION → IN_REVIEW cycle may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/care_plan_review_revision_cycle
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = get_success_data(api_client.create_care_plan({"participant_id": participant["id"]}, IC))
    get_success_data(api_client.add_care_plan_goal(
        cp["id"], {"discipline": "RN", "description": "G1"}, IC))
    get_success_data(api_client.sign_care_plan(cp["id"], {"discipline": "RN"}, NS))
    get_success_data(api_client.submit_care_plan(cp["id"], IC))
    get_success_data(api_client.request_care_plan_revision(cp["id"], MD))

    resubmitted = get_success_data(api_client.submit_care_plan(cp["id"], IC))
    assert resubmitted["status"] == "IN_REVIEW"


def test_request_revision_clears_signatures():
    """PRD 3.3: "A MedicalDirector reviewing an IN_REVIEW plan may send it back by
    requesting a revision, which moves it to REVISION and clears idt_disciplines_signed
    to empty (a revision invalidates every prior signature)."

    After resubmission the signature set remains empty (the revision cleared it).

    Design: Difficulty/non_linear_state_machine/care_plan_review_revision_cycle
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = get_success_data(api_client.create_care_plan({"participant_id": participant["id"]}, IC))
    get_success_data(api_client.add_care_plan_goal(
        cp["id"], {"discipline": "RN", "description": "G1"}, IC))
    get_success_data(api_client.sign_care_plan(cp["id"], {"discipline": "RN"}, NS))
    get_success_data(api_client.submit_care_plan(cp["id"], IC))
    revised = get_success_data(api_client.request_care_plan_revision(cp["id"], MD))
    assert revised["idt_disciplines_signed"] == []

    resubmitted = get_success_data(api_client.submit_care_plan(cp["id"], IC))
    assert resubmitted["status"] == "IN_REVIEW"
    assert resubmitted["idt_disciplines_signed"] == []


def test_review_cycle_repeats_twice():
    """PRD 3.3: "This IN_REVIEW → REVISION → IN_REVIEW cycle may repeat any number
    of times."

    Two full IN_REVIEW → REVISION → IN_REVIEW loops both land in IN_REVIEW.

    Design: Difficulty/non_linear_state_machine/care_plan_review_revision_cycle
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = get_success_data(api_client.create_care_plan({"participant_id": participant["id"]}, IC))
    get_success_data(api_client.add_care_plan_goal(
        cp["id"], {"discipline": "RN", "description": "G1"}, IC))
    get_success_data(api_client.submit_care_plan(cp["id"], IC))
    for _ in range(2):
        get_success_data(api_client.request_care_plan_revision(cp["id"], MD))
        back = get_success_data(api_client.submit_care_plan(cp["id"], IC))
        assert back["status"] == "IN_REVIEW"


# ===========================================================================
# non_linear_state_machine / disenrollment_submitted_branches_approve_or_deny
# ===========================================================================
def test_submitted_request_deny_branch_leaves_participant_enrolled():
    """PRD 3.8: "Alternatively the MedicalDirector may deny it, but only a VOLUNTARY
    request may be denied ... a successful deny moves the request to DENIED with no
    participant change."

    Denying a SUBMITTED VOLUNTARY request moves it to DENIED while the participant stays
    ENROLLED (the deny branch has no participant side effects).

    Design: Difficulty/non_linear_state_machine/disenrollment_submitted_branches_approve_or_deny
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="DISSATISFIED",
                               requested_effective_date="2026-08-01")

    denied = get_success_data(api_client.deny_disenrollment_request(req["id"], MD))
    assert denied["status"] == "DENIED"

    refreshed = get_success_data(api_client.get_participant(participant["id"], BS))
    assert refreshed["status"] == "ENROLLED"


def test_submitted_request_approve_branch_drives_participant_pending():
    """PRD 3.8: "approval moves the request to APPROVED, drives the participant from
    ENROLLED to DISENROLLMENT_PENDING, and increments the participant's version."

    The approve branch diverges from the deny branch: it moves the participant to
    DISENROLLMENT_PENDING.

    Design: Difficulty/non_linear_state_machine/disenrollment_submitted_branches_approve_or_deny
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="DISSATISFIED",
                               requested_effective_date="2026-08-01")

    approved = get_success_data(api_client.approve_disenrollment_request(req["id"], MD))
    assert approved["status"] == "APPROVED"

    refreshed = get_success_data(api_client.get_participant(participant["id"], BS))
    assert refreshed["status"] == "DISENROLLMENT_PENDING"


# ===========================================================================
# transitive_cascade / disenroll_finalize_cascade_depth3
# ===========================================================================
def test_disenroll_finalize_cascades_careplan_and_med_order():
    """PRD 3.8: "On finalize the participant moves from DISENROLLMENT_PENDING to
    DISENROLLED and the following cascade runs atomically".
    PRD 3.8: "for any non-death reason the plan moves to SUPERSEDED ... In either case
    that plan's medication orders in ORDERED, ACTIVE, or HELD status are all cascaded
    to DISCONTINUED."

    Depth-3 cascade: finalize -> participant DISENROLLED -> ACTIVE care plan SUPERSEDED
    -> that plan's ACTIVE med order DISCONTINUED.

    Design: Difficulty/transitive_cascade/disenroll_finalize_cascade_depth3
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    participant = create_participant(program["id"])
    create_certified_loc(participant["id"])
    care_plan = create_active_care_plan(participant["id"])
    med_order = create_active_med_order(participant["id"], care_plan["id"])
    get_success_data(api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-06-01"}, IC))

    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-08-01")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    assert get_success_data(api_client.get_participant(participant["id"], BS))["status"] == "DISENROLLED"
    assert get_success_data(api_client.get_care_plan(care_plan["id"], MD))["status"] == "SUPERSEDED"
    assert get_success_data(api_client.get_medication_order(med_order["id"], NS))["status"] == "DISCONTINUED"


def test_disenroll_finalize_deceased_voids_care_plan():
    """PRD 3.8: "for any non-death reason the plan moves to SUPERSEDED, but when the
    reason_code is DECEASED it moves to VOID instead. In either case that plan's
    medication orders in ORDERED, ACTIVE, or HELD status are all cascaded to DISCONTINUED."

    The DECEASED branch diverges: the ACTIVE care plan moves to VOID (not SUPERSEDED),
    and its ACTIVE med order is still DISCONTINUED.

    Design: Difficulty/transitive_cascade/disenroll_finalize_cascade_depth3
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    participant = create_participant(program["id"])
    create_certified_loc(participant["id"])
    care_plan = create_active_care_plan(participant["id"])
    med_order = create_active_med_order(participant["id"], care_plan["id"])
    get_success_data(api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-06-01"}, IC))

    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="DECEASED",
                               requested_effective_date="2026-08-01")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    assert get_success_data(api_client.get_care_plan(care_plan["id"], MD))["status"] == "VOID"
    assert get_success_data(api_client.get_medication_order(med_order["id"], NS))["status"] == "DISCONTINUED"


# ===========================================================================
# transitive_cascade / care_plan_activate_supersede_cascade_depth2
# ===========================================================================
def test_activate_successor_supersedes_prior_and_discontinues_its_meds():
    """PRD 3.3: "Activation supersedes the predecessor in one step: if the participant
    already had a different active plan, that prior plan transitions to SUPERSEDED, and
    that prior plan's medication orders in ORDERED, ACTIVE, or HELD status are all
    cascaded to DISCONTINUED."

    Depth-2 cascade from care-plan activate: activating plan B supersedes plan A, which
    discontinues plan A's ACTIVE med order.

    Design: Difficulty/transitive_cascade/care_plan_activate_supersede_cascade_depth2
    """
    program = create_program()
    participant = create_participant(program["id"])
    plan_a = create_active_care_plan(participant["id"])
    med_order = create_active_med_order(participant["id"], plan_a["id"])

    # Plan B supersedes A
    cpb = get_success_data(api_client.create_care_plan(
        {"participant_id": participant["id"], "supersedes_care_plan_id": plan_a["id"]}, IC))
    get_success_data(api_client.add_care_plan_goal(
        cpb["id"], {"discipline": "RN", "description": "B"}, IC))
    for disc, signer in (("RN", NS), ("SW", IC), ("MEDICAL_DIRECTOR", MD)):
        get_success_data(api_client.sign_care_plan(cpb["id"], {"discipline": disc}, signer))
    get_success_data(api_client.submit_care_plan(cpb["id"], IC))
    activated_b = get_success_data(api_client.activate_care_plan(cpb["id"], MD))

    assert activated_b["status"] == "ACTIVE"
    assert get_success_data(api_client.get_care_plan(plan_a["id"], MD))["status"] == "SUPERSEDED"
    assert get_success_data(api_client.get_medication_order(med_order["id"], NS))["status"] == "DISCONTINUED"


def test_activate_successor_points_participant_active_care_plan():
    """PRD 3.3: "The participant's active_care_plan_id is then pointed at the newly
    activated plan and the participant's version increments."

    After activating plan B, the participant's active_care_plan_id is plan B.

    Design: Difficulty/transitive_cascade/care_plan_activate_supersede_cascade_depth2
    """
    program = create_program()
    participant = create_participant(program["id"])
    plan_a = create_active_care_plan(participant["id"])

    cpb = get_success_data(api_client.create_care_plan(
        {"participant_id": participant["id"], "supersedes_care_plan_id": plan_a["id"]}, IC))
    get_success_data(api_client.add_care_plan_goal(
        cpb["id"], {"discipline": "RN", "description": "B"}, IC))
    for disc, signer in (("RN", NS), ("SW", IC), ("MEDICAL_DIRECTOR", MD)):
        get_success_data(api_client.sign_care_plan(cpb["id"], {"discipline": disc}, signer))
    get_success_data(api_client.submit_care_plan(cpb["id"], IC))
    get_success_data(api_client.activate_care_plan(cpb["id"], MD))

    refreshed = get_success_data(api_client.get_participant(participant["id"], MD))
    assert refreshed["active_care_plan_id"] == cpb["id"]
