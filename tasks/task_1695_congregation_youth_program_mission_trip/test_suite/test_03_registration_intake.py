"""Registration intake: account auto-creation, duplicate and window gates,
conditional consent-form rules, and parent-state gating of child creation."""
from test_helpers import (
    ApiErrorId,
    add_consent_form,
    advance_check,
    assert_registration,
    create_chaperone,
    create_participant,
    create_program,
    create_registration,
    create_registration_payload,
    create_trip,
    get_account_for_registration,
    initiate_background_check,
    make_director_headers,
    make_guardian_headers,
    set_clock,
    setup_program_with_open_trip,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = make_director_headers()


class TestFundraisingAccountAutoCreate:
    def test_fundraising_account_auto_created_one_to_one(self, api):
        """PRD §3.3: "A successful create produces a registration in `DRAFT` on
        the status track and `PENDING_DEPOSIT` on the payment track, copies
        `guardian_user_id` from the participant as the ownership anchor, computes
        the first `provisional_cost_share_cents`, and auto-opens the
        registration's one-to-one **FundraisingAccount** with `goal_cents` set
        from `fundraising_goal_cents`."
        PRD §3.4: "`goal_met` is a gross-basis comparison — true when `goal_cents`
        is positive and `raised_gross_cents` is at least `goal_cents`".

        Design: Corner/entities/fundraising_account_auto_created_one_to_one
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        registration = create_registration(
            trip["id"], participant["id"], "guardian-1",
            insurance_tier="DOMESTIC", fundraising_goal_cents=7500)
        assert_registration(registration)
        assert registration["registration_status"] == "DRAFT"
        assert registration["payment_status"] == "PENDING_DEPOSIT"
        assert registration["guardian_user_id"] == "guardian-1"

        account = get_account_for_registration(registration["id"])
        assert account["registration_id"] == registration["id"]
        assert account["status"] == "OPEN"
        assert account["goal_cents"] == 7500
        assert account["raised_gross_cents"] == 0
        assert account["fee_total_cents"] == 0
        assert account["raised_net_cents"] == 0
        assert account["available_credit_cents"] == 0
        assert account["goal_met"] is False


class TestDuplicateRegistration:
    def test_duplicate_registration_blocked_until_terminal_then_allowed(self, api):
        """PRD §3.3: "there must be no other non-terminal registration for the
        same (trip, participant) pair (`ERR_DUPLICATE_REGISTRATION`, HTTP 409)".
        PRD §3.7: "A guardian or director may withdraw a registration from any
        non-terminal status" — `WITHDRAWN` is terminal, so the pair frees up.

        Design: Corner/entities/duplicate_registration_blocked_until_terminal_then_allowed
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        first = create_registration(trip["id"], participant["id"], "guardian-1")

        dup = api.create_registration(
            create_registration_payload(trip["id"], participant["id"],
                                        insurance_tier="DOMESTIC"),
            make_guardian_headers("guardian-1"))
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_REGISTRATION, 409)

        wd = api.withdraw_registration(first["id"],
                                       make_guardian_headers("guardian-1"))
        validate_success(wd, 200)
        assert wd.json()["data"]["registration_status"] == "WITHDRAWN"

        second = api.create_registration(
            create_registration_payload(trip["id"], participant["id"],
                                        insurance_tier="DOMESTIC"),
            make_guardian_headers("guardian-1"))
        data = validate_success(second, 201)
        assert data["id"] != first["id"]


class TestDoubleSubmit:
    def test_registration_double_submit_rejected(self, api):
        """PRD §3.3: "Submission of the registration itself — `DRAFT` to
        `SUBMITTED`, by the guardian or a director — requires the trip to be
        `REGISTRATION_OPEN` and all three required form types to exist with
        status `SUBMITTED` or `VERIFIED`". Repeating the transition on a
        `SUBMITTED` registration violates its state precondition:
        "`ERR_REGISTRATION_STATE_FORBIDS_ACTION`" (§5).

        Design: Corner/state_machines/registration_double_submit_rejected
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        registration = create_registration(trip["id"], participant["id"],
                                           "guardian-1")
        for form_type in ("PARENTAL_CONSENT", "MEDICAL_RELEASE",
                          "CONDUCT_AGREEMENT"):
            add_consent_form(registration["id"], form_type, "guardian-1")

        first = api.submit_registration(registration["id"],
                                        make_guardian_headers("guardian-1"))
        data = validate_success(first, 200)
        assert data["registration_status"] == "SUBMITTED"

        second = api.submit_registration(registration["id"],
                                         make_guardian_headers("guardian-1"))
        validate_error(second, ApiErrorId.ERR_REGISTRATION_STATE_FORBIDS_ACTION,
                       409)


class TestRegistrationWindow:
    def test_registration_window_closed_temporal_gate(self, api):
        """PRD §3.3: "the trip must be `REGISTRATION_OPEN` and the clock must not
        be strictly past `registration_close_at` (`ERR_REGISTRATION_WINDOW_CLOSED`)".

        Design: Corner/validations/registration_window_closed_temporal_gate
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        set_clock("2026-12-02T00:00:00Z")  # strictly past the 2026-12-01 close

        resp = api.create_registration(
            create_registration_payload(trip["id"], participant["id"]),
            make_guardian_headers("guardian-1"))
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED, 422)

        _, meta = validate_paginated(
            api.list_registrations(DIRECTOR, params={"trip_id": trip["id"]}))
        assert meta["total_count"] == 0, "no registration row may be created"


class TestConsentFormIntakeRules:
    def test_medical_release_requires_notes_and_form_type_uniqueness(self, api):
        """PRD §3.3: "`medical_notes` defaults to empty but a `MEDICAL_RELEASE`
        with empty notes is rejected with `ERR_REQUIRED_FORMS_INCOMPLETE`
        (HTTP 422)."
        PRD §3.3: "only one form per `form_type` may exist in `SUBMITTED` or
        `VERIFIED` (`ERR_DUPLICATE_CONSENT_FORM_TYPE`, HTTP 409)".
        PRD §3.3: "a resubmit of a form not `REJECTED` is an
        `ERR_CONSENT_FORM_STATE_FORBIDS_ACTION` (HTTP 409)".

        Design: Corner/validations/medical_release_requires_notes_and_form_type_uniqueness
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        registration = create_registration(trip["id"], participant["id"],
                                           "guardian-1")
        guardian = make_guardian_headers("guardian-1")

        # MEDICAL_RELEASE without notes: conditional requirement fires.
        no_notes = api.create_consent_form(
            registration["id"],
            {"form_type": "MEDICAL_RELEASE", "signed_by_name": "G",
             "signed_at": "2026-08-02T10:00:00Z"},
            guardian)
        validate_error(no_notes, ApiErrorId.ERR_REQUIRED_FORMS_INCOMPLETE, 422)

        # PARENTAL_CONSENT needs no notes.
        ok = api.create_consent_form(
            registration["id"],
            {"form_type": "PARENTAL_CONSENT", "signed_by_name": "G",
             "signed_at": "2026-08-02T10:00:00Z"},
            guardian)
        form = validate_success(ok, 201)
        assert form["status"] == "SUBMITTED"

        # Second live form of the same type.
        dup = api.create_consent_form(
            registration["id"],
            {"form_type": "PARENTAL_CONSENT", "signed_by_name": "G2",
             "signed_at": "2026-08-02T11:00:00Z"},
            guardian)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_CONSENT_FORM_TYPE, 409)

        # Resubmit requires REJECTED; this form is SUBMITTED.
        resub = api.resubmit_consent_form(
            form["id"],
            {"signed_by_name": "G3", "signed_at": "2026-08-03T09:00:00Z"},
            guardian)
        validate_error(resub, ApiErrorId.ERR_CONSENT_FORM_STATE_FORBIDS_ACTION,
                       409)


class TestChildCreationParentGates:
    def test_child_creation_gated_by_parent_states(self, api):
        """PRD §3.3: "The create is gated by state and safety: the trip must be
        `REGISTRATION_OPEN`".
        PRD §3.1: "closing requires the program to be `OPEN` and every one of its
        trips to have reached `DEBRIEFED` or `CANCELLED`; otherwise the close is
        rejected with `ERR_PROGRAM_HAS_OPEN_TRIPS` (HTTP 409)" and "Creating
        trips, participants, or chaperones under a program that is not `OPEN`
        fails with `ERR_PROGRAM_NOT_OPEN`."
        PRD §3.8: "the trip must be in `DRAFT`, `REGISTRATION_OPEN`,
        `REGISTRATION_CLOSED`, or `ROSTER_LOCKED` (`ERR_TRIP_STATE_FORBIDS_ACTION`)".

        Design: Corner/validations/child_creation_gated_by_parent_states
        """
        program = create_program()
        trip = create_trip(program["id"], destination_type="IN_STATE",
                           start_date="2027-06-15", end_date="2027-06-16",
                           emergency_protocol_text="")
        participant = create_participant(program["id"], "guardian-1")
        chaperone = create_chaperone(program["id"])
        check = initiate_background_check(chaperone["id"])
        advance_check(check["id"], "SCREENING")
        advance_check(check["id"], "CLEARED")

        # Registration create against a DRAFT trip.
        e_draft = api.create_registration(
            create_registration_payload(trip["id"], participant["id"],
                                        insurance_tier="NONE"),
            make_guardian_headers("guardian-1"))
        validate_error(e_draft, ApiErrorId.ERR_TRIP_STATE_FORBIDS_ACTION, 409)

        # Program close blocked while T1 is non-terminal (DRAFT).
        e_close = api.close_program(program["id"], DIRECTOR)
        validate_error(e_close, ApiErrorId.ERR_PROGRAM_HAS_OPEN_TRIPS, 409)

        # Cancel from DRAFT, then an assignment against the CANCELLED trip.
        cancel = api.cancel_trip(trip["id"], DIRECTOR)
        validate_success(cancel, 200)
        e_cancelled = api.create_chaperone_assignment(
            {"trip_id": trip["id"], "chaperone_id": chaperone["id"],
             "role": "LEAD"},
            DIRECTOR)
        validate_error(e_cancelled, ApiErrorId.ERR_TRIP_STATE_FORBIDS_ACTION,
                       409)

        # With T1 terminal, the close succeeds.
        closed = api.close_program(program["id"], DIRECTOR)
        closed_data = validate_success(closed, 200)
        assert closed_data["status"] == "CLOSED"

        # A CLOSED program rejects new trips.
        e_notopen = api.create_trip(
            {"program_id": program["id"], "name": "T2",
             "destination_name": "Local", "destination_type": "IN_STATE",
             "start_date": "2027-07-01", "end_date": "2027-07-02",
             "capacity_youth": 5, "base_cost_cents": 100, "deposit_cents": 50,
             "chaperone_ratio": 5,
             "registration_open_at": "2026-08-01T00:00:00Z",
             "registration_close_at": "2026-12-01T00:00:00Z",
             "deposit_due_at": "2027-01-15T00:00:00Z",
             "final_payment_due_at": "2027-05-01T00:00:00Z"},
            DIRECTOR)
        validate_error(e_notopen, ApiErrorId.ERR_PROGRAM_NOT_OPEN, 409)
