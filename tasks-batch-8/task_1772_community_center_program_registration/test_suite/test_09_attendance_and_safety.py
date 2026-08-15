"""Attendance gating on verified safety forms, duplicate marks, form terminal
states, and the signature-before-duplicate precedence."""
from test_helpers import (
    FD,
    MINOR_BIRTH_DATE,
    ApiErrorId,
    add_participant,
    create_household,
    create_published_season,
    create_season,
    create_verified_safety_form,
    household_headers,
    mark_attendance,
    mark_present,
    register_and_pay,
    run_sweep,
    set_clock,
    setup_household_with_participants,
    setup_published_session,
    submit_safety_form,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api


def _active_session_with_enrolled() -> dict:
    """Published session (fees 2000, one meeting 2026-09-20 18:00-19:00)
    activated by the sweep; one adult participant registered and paid; clock
    at 2026-09-20T18:30:00Z (the meeting has started)."""
    ctx = setup_published_session(fee_resident_cents=2000, fee_nonresident_cents=2000)
    household, parts = setup_household_with_participants(count=1, account_name="HF",
                                                         name_prefix="Kata")
    registration = register_and_pay(ctx["session"]["id"], parts[0]["id"],
                                    household["id"])
    set_clock(ctx["session"]["enrollment_check_at"])
    run_sweep(ctx["season"]["id"])
    set_clock("2026-09-20T18:30:00Z")
    return {"ctx": ctx, "household": household, "participant": parts[0],
            "registration": registration}


def test_attendance_rejected_while_form_only_submitted(api):
    """PRD §3.9: "Four gates guard the mark, in pinned order: the registration
    must be `ENROLLED`, else `ERR_REGISTRATION_NOT_ENROLLED`; a `VERIFIED`
    safety form must exist for the participant in the session's season, else
    `ERR_SAFETY_FORM_REQUIRED`; the meeting must have started — now at or
    after its `starts_at` — else `ERR_ATTENDANCE_TOO_EARLY`; and at most one
    record may exist per meeting-and-registration, else
    `ERR_DUPLICATE_ATTENDANCE`."
    PRD §3.4: "Only a `VERIFIED` form clears the participant for attendance
    marking (§3.9)."

    Design: Difficulty/cross_entity_state_dependency/attendance_requires_verified_safety_form
    """
    scenario = _active_session_with_enrolled()
    ctx = scenario["ctx"]
    # Adult self-signed form, left merely SUBMITTED.
    submit_safety_form(scenario["participant"]["id"], ctx["season"]["id"],
                       scenario["household"]["id"],
                       signer_name=scenario["participant"]["full_name"])

    resp = mark_attendance(ctx["meetings"][0]["id"], scenario["registration"]["id"],
                           ctx["instructor"]["id"])
    validate_error(resp, ApiErrorId.ERR_SAFETY_FORM_REQUIRED, 422)


def test_attendance_succeeds_after_form_verified(api):
    """PRD §3.4: "A form is born `SUBMITTED`. `FrontDeskStaff` then verifies
    it, moving it to `VERIFIED`, or rejects it, moving it to `REJECTED`,
    optionally attaching a `reason`; both outcomes are terminal."
    PRD §3.4: "Only a `VERIFIED` form clears the participant for attendance
    marking (§3.9)."

    Design: Difficulty/cross_entity_state_dependency/attendance_requires_verified_safety_form
    """
    scenario = _active_session_with_enrolled()
    ctx = scenario["ctx"]
    create_verified_safety_form(scenario["participant"]["id"], ctx["season"]["id"],
                                scenario["household"]["id"],
                                signer_name=scenario["participant"]["full_name"])

    record = mark_present(ctx["meetings"][0]["id"], scenario["registration"]["id"],
                          ctx["instructor"]["id"])
    assert record["status"] == "PRESENT"


def test_duplicate_attendance_rejected(api):
    """PRD §3.9: "and at most one record may exist per
    meeting-and-registration, else `ERR_DUPLICATE_ATTENDANCE`."

    Design: Corner/validations/duplicate_attendance_rejected
    """
    scenario = _active_session_with_enrolled()
    ctx = scenario["ctx"]
    create_verified_safety_form(scenario["participant"]["id"], ctx["season"]["id"],
                                scenario["household"]["id"],
                                signer_name=scenario["participant"]["full_name"])
    mark_present(ctx["meetings"][0]["id"], scenario["registration"]["id"],
                 ctx["instructor"]["id"])

    resp = mark_attendance(ctx["meetings"][0]["id"], scenario["registration"]["id"],
                           ctx["instructor"]["id"], status="ABSENT")
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ATTENDANCE, 409)


def test_verify_rejected_form_rejected(api):
    """PRD §3.4: "A form is born `SUBMITTED`. `FrontDeskStaff` then verifies
    it, moving it to `VERIFIED`, or rejects it, moving it to `REJECTED`,
    optionally attaching a `reason`; both outcomes are terminal."
    PRD §2.8: "Generic state-machine legality — the attempted trigger must be
    defined for the entity's current state. Publishing an already-published
    session, dropping an already-dropped registration, verifying an
    already-verified form, withdrawing a denied application, closing a season
    before its registration deadline, or completing a session with unfinished
    meetings are all `ERR_INVALID_STATE`."

    Design: Corner/state_machines/verify_rejected_form_rejected
    """
    season = create_season()
    household = create_household("HF")
    participant = add_participant(household["id"], "Adult F")
    form = submit_safety_form(participant["id"], season["id"], household["id"],
                              signer_name="Adult F")
    validate_success(_api.reject_safety_form(form["id"], FD))

    resp = _api.verify_safety_form(form["id"], FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def _minor_with_guardian_signed_form() -> dict:
    """Season (DRAFT is fine for forms), household with a minor participant
    (age 11 at the season start), and one guardian-signed form already
    SUBMITTED."""
    season = create_published_season()
    household = create_household("HM")
    minor = add_participant(household["id"], "Mini Me", MINOR_BIRTH_DATE)
    form = submit_safety_form(minor["id"], season["id"], household["id"],
                              signer_name="Guardian One")
    return {"season": season, "household": household, "minor": minor, "form": form}


def test_guardian_signature_beats_duplicate(api):
    """PRD §3.4: "Signature rules depend on age measured at the season's
    `start_date`: a minor — under eighteen — must be signed by someone other
    than the participant, and a self-signed minor's form is rejected with
    `ERR_GUARDIAN_SIGNATURE_REQUIRED`; an adult — eighteen or older — must
    self-sign, and a form signed by anyone else is rejected with
    `ERR_SELF_SIGNATURE_REQUIRED`. At most one form per participant-and-season
    may be live in `SUBMITTED` or `VERIFIED`; a second submission while one is
    live is rejected with `ERR_DUPLICATE_SAFETY_FORM`. The signature rules are
    evaluated before the duplicate-form guard, and the household-membership
    check — the participant must belong to the caller's household, else
    `ERR_NOT_HOUSEHOLD_MEMBER` — comes after both."

    Design: Difficulty/priority_pair_validation_conflict/safety_over_constraint_on_form_submission
    """
    scenario = _minor_with_guardian_signed_form()
    # Second form is BOTH self-signed by the minor AND a duplicate: the
    # signature rule reports first.
    resp = _api.create_safety_form(
        {"participant_id": scenario["minor"]["id"],
         "season_id": scenario["season"]["id"],
         "emergency_contact_name": "Guardian One",
         "emergency_contact_phone": "555-1",
         "signer_name": "Mini Me"},
        household_headers(scenario["household"]),
    )
    validate_error(resp, ApiErrorId.ERR_GUARDIAN_SIGNATURE_REQUIRED, 422)


def test_duplicate_form_fires_after_signature_passes(api):
    """PRD §3.4: "At most one form per participant-and-season may be live in
    `SUBMITTED` or `VERIFIED`; a second submission while one is live is
    rejected with `ERR_DUPLICATE_SAFETY_FORM`. The signature rules are
    evaluated before the duplicate-form guard, and the household-membership
    check — the participant must belong to the caller's household, else
    `ERR_NOT_HOUSEHOLD_MEMBER` — comes after both."

    Design: Difficulty/priority_pair_validation_conflict/safety_over_constraint_on_form_submission
    """
    scenario = _minor_with_guardian_signed_form()
    # Second form is properly guardian-signed: only the duplicate guard fails.
    resp = _api.create_safety_form(
        {"participant_id": scenario["minor"]["id"],
         "season_id": scenario["season"]["id"],
         "emergency_contact_name": "Guardian Two",
         "emergency_contact_phone": "555-2",
         "signer_name": "Guardian Two"},
        household_headers(scenario["household"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SAFETY_FORM, 409)
