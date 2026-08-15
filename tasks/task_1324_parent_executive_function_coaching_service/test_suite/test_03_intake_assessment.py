"""Intake assessment workflow: the supervised revision cycle (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    add_client,
    create_coach,
    create_family,
    create_intake,
    get_success_data,
    make_coach_headers,
    make_family_headers,
    validate_error,
    validate_success,
)


def test_intake_revision_cycle_closes_loop(api):
    """PRD §3.2: "A family member moves the assessment from `DRAFT` to
    `SUBMITTED`, which requires `presenting_concerns` to be non-empty and
    `baseline_score` to be present, failing which the submission is rejected
    with `ERR_VALIDATION`. A coach then moves it from `SUBMITTED` to
    `UNDER_REVIEW`."
    PRD §3.2: "The family then moves a `NEEDS_REVISION` assessment back to
    `DRAFT` to edit and resubmit; the `review_notes` are retained for the
    family's reference, and the cycle may repeat without limit."

    Design: Difficulty/non_linear_state_machine/intake_revision_cycle
    """
    family = create_family("Fam IC", "ic@example.com")
    client = add_client(family["id"], full_name="Kid I", date_of_birth="2013-06-01")
    coach = create_coach("CERTIFIED", full_name="Coach I")
    intake = create_intake(client["id"], "v1", 40)
    fam_h = make_family_headers(family["id"])
    coach_h = make_coach_headers(coach["id"])

    st1 = validate_success(api.transition_intake(intake["id"], "SUBMITTED", fam_h))
    st2 = validate_success(api.transition_intake(intake["id"], "UNDER_REVIEW", coach_h))
    st3 = validate_success(
        api.transition_intake(intake["id"], "NEEDS_REVISION", coach_h,
                              review_notes="expand goals")
    )
    st4 = validate_success(api.transition_intake(intake["id"], "DRAFT", fam_h))
    st5 = validate_success(api.transition_intake(intake["id"], "SUBMITTED", fam_h))
    st6 = validate_success(api.transition_intake(intake["id"], "UNDER_REVIEW", coach_h))
    st7 = validate_success(api.transition_intake(intake["id"], "APPROVED", coach_h))

    assert st1["status"] == "SUBMITTED"
    assert st2["status"] == "UNDER_REVIEW"
    assert st3["status"] == "NEEDS_REVISION"
    assert st4["status"] == "DRAFT", "the cycle must revisit DRAFT after SUBMITTED"
    assert st5["status"] == "SUBMITTED"
    assert st6["status"] == "UNDER_REVIEW"
    assert st7["status"] == "APPROVED"


def test_intake_revision_cycle_retains_review_notes(api):
    """PRD §3.2: "Alternatively, the coach may send the assessment back by
    moving it to `NEEDS_REVISION`, a transition that requires the coach to
    supply `review_notes`; the notes are stored on the assessment. The family
    then moves a `NEEDS_REVISION` assessment back to `DRAFT` to edit and
    resubmit; the `review_notes` are retained for the family's reference, and
    the cycle may repeat without limit."

    Design: Difficulty/non_linear_state_machine/intake_revision_cycle
    """
    family = create_family("Fam IC2", "ic2@example.com")
    client = add_client(family["id"], full_name="Kid I2", date_of_birth="2013-06-01")
    coach = create_coach("CERTIFIED", full_name="Coach I2")
    intake = create_intake(client["id"], "v1", 40)
    fam_h = make_family_headers(family["id"])
    coach_h = make_coach_headers(coach["id"])

    api.transition_intake(intake["id"], "SUBMITTED", fam_h)
    api.transition_intake(intake["id"], "UNDER_REVIEW", coach_h)
    revision = validate_success(
        api.transition_intake(intake["id"], "NEEDS_REVISION", coach_h,
                              review_notes="expand goals")
    )
    assert revision["status"] == "NEEDS_REVISION"
    assert revision["review_notes"] == "expand goals", (
        "review_notes must be stored on the assessment"
    )

    back = validate_success(api.transition_intake(intake["id"], "DRAFT", fam_h))
    assert back["status"] == "DRAFT"
    retained = validate_success(api.get_intake(intake["id"], fam_h))
    assert retained["review_notes"] == "expand goals", (
        "review_notes must be retained after the return to DRAFT"
    )


def test_intake_approved_terminal_lockdown_rejected(api):
    """PRD §3.2: "Approval — the transition to the terminal `APPROVED` state —
    may only be performed by a coach holding `credential_level` `CERTIFIED` or
    `SUPERVISOR`"
    PRD §2.8: "a state transition requested for a from-state the machine does
    not permit — including any write against a terminal state — is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/intake_approved_terminal_lockdown_rejected
    """
    family = create_family("Fam IA", "ia@example.com")
    client = add_client(family["id"], full_name="Kid IA", date_of_birth="2014-11-01")
    coach = create_coach("CERTIFIED", full_name="Coach IA")
    intake = create_intake(client["id"], "ia", 50)
    fam_h = make_family_headers(family["id"])
    coach_h = make_coach_headers(coach["id"])
    get_success_data(api.transition_intake(intake["id"], "SUBMITTED", fam_h))
    get_success_data(api.transition_intake(intake["id"], "UNDER_REVIEW", coach_h))
    approved = get_success_data(api.transition_intake(intake["id"], "APPROVED", coach_h))
    assert approved["status"] == "APPROVED"

    resp = api.transition_intake(intake["id"], "DRAFT", fam_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_intake_approval_by_associate_forbidden(api):
    """PRD §3.2: "Approval — the transition to the terminal `APPROVED` state —
    may only be performed by a coach holding `credential_level` `CERTIFIED` or
    `SUPERVISOR`; an `ASSOCIATE` attempting approval is rejected with
    `ERR_CREDENTIAL_INSUFFICIENT`."

    Design: Corner/validations/intake_approval_by_associate_forbidden
    """
    family = create_family("Fam CR", "cr@example.com")
    client = add_client(family["id"], full_name="Kid CR", date_of_birth="2014-10-15")
    associate = create_coach("ASSOCIATE", full_name="Coach Assoc")
    intake = create_intake(client["id"], "cr", 50)
    fam_h = make_family_headers(family["id"])
    assoc_h = make_coach_headers(associate["id"])
    get_success_data(api.transition_intake(intake["id"], "SUBMITTED", fam_h))
    get_success_data(api.transition_intake(intake["id"], "UNDER_REVIEW", assoc_h))

    resp = api.transition_intake(intake["id"], "APPROVED", assoc_h)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_INSUFFICIENT)
