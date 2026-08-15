"""Request-shape validation, caller-context validation, typed 404s, and the
role-before-existence ordering rule."""
from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_participant_payload,
    create_program,
    create_registration_payload,
    create_trip_payload,
    make_director_headers,
    make_guardian_headers,
    make_leader_headers,
    make_treasurer_headers,
    setup_program_with_open_trip,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()
MISSING = "11111111-1111-4111-8111-111111111111"


class TestUserContextHeaders:
    def test_missing_or_invalid_user_context_headers(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, naming their capacity.
        If either header is missing, or the role value is not one of the declared
        role names, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.8: the caller-context check is step "1. **Presence and shape of the
        caller context**: the two headers and a declared role name", ahead of
        "4. **Existence**".

        Design: Corner/validations/missing_or_invalid_user_context_headers
        """
        # No auth headers at all — fails even though the id does not exist.
        resp = api._request("GET", f"/youth-ministry/programs/{MISSING}",
                            None, None)
        validate_error(resp,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       400)

        # Undeclared role name — still the context error, not the 404.
        resp2 = api.get_program(MISSING,
                                build_user_headers("someone-1", "SuperAdmin"))
        validate_error(resp2,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       400)


class TestBodyShapeValidation:
    def test_invalid_enum_date_range_and_missing_required_field(self, api):
        """PRD §2.8: "**Body well-formedness**: required fields present, enum
        values within their declared sets (including `decision`, `to_status`, and
        `sanction` values — otherwise `ERR_INVALID_ENUM`), integer ranges
        respected ... and every start-before-end pair ordered (`check_out_date`
        strictly after `check_in_date`, `end_date` strictly after `start_date`,
        `end_at` strictly after `start_at` — otherwise `ERR_INVALID_DATE_RANGE`)."

        Design: Corner/validations/invalid_enum_and_date_range_and_unknown_field
        """
        program, trip = setup_program_with_open_trip()
        participant_resp = api.create_participant(
            create_participant_payload(program["id"]),
            make_guardian_headers("guardian-1"))
        participant = participant_resp.json()["data"]

        # Enum outside its declared set.
        bad_enum = api.create_registration(
            create_registration_payload(trip["id"], participant["id"],
                                        insurance_tier="GLOBAL"),
            make_guardian_headers("guardian-1"))
        validate_error(bad_enum, ApiErrorId.ERR_INVALID_ENUM, 400)

        # Inverted date pair.
        bad_dates = api.create_trip(
            create_trip_payload(program["id"], name="Bad",
                                start_date="2027-06-25", end_date="2027-06-15"),
            DIRECTOR)
        validate_error(bad_dates, ApiErrorId.ERR_INVALID_DATE_RANGE, 400)

        # Required field omitted (fundraising_goal_cents).
        missing_field = api.create_registration(
            {"trip_id": trip["id"], "participant_id": participant["id"],
             "insurance_tier": "INTERNATIONAL"},
            make_guardian_headers("guardian-1"))
        validate_error(missing_field, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestTypedNotFound:
    def test_not_found_for_every_resource_kind(self, api):
        """PRD §2.8: "path identifiers are resolved left to right, and
        body-referenced identifiers (`trip_id`, `participant_id`, `chaperone_id`,
        `registration_id`) must also exist; the first missing resource produces
        its specific 404 (`ERR_PROGRAM_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`,
        `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
        `ERR_CONSENT_FORM_NOT_FOUND`, `ERR_FUNDRAISING_ACCOUNT_NOT_FOUND`,
        `ERR_DONATION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
        `ERR_SCHOLARSHIP_APPLICATION_NOT_FOUND`, `ERR_CHAPERONE_NOT_FOUND`,
        `ERR_BACKGROUND_CHECK_NOT_FOUND`, `ERR_CHAPERONE_ASSIGNMENT_NOT_FOUND`,
        or `ERR_LODGING_RESERVATION_NOT_FOUND`)."

        Design: Corner/entities/not_found_for_every_resource_kind
        """
        probes = [
            ("program", api.get_program(MISSING, DIRECTOR),
             ApiErrorId.ERR_PROGRAM_NOT_FOUND),
            ("trip", api.get_trip(MISSING, DIRECTOR),
             ApiErrorId.ERR_TRIP_NOT_FOUND),
            ("participant", api.get_participant(MISSING, DIRECTOR),
             ApiErrorId.ERR_PARTICIPANT_NOT_FOUND),
            ("registration", api.get_registration(MISSING, DIRECTOR),
             ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
            ("consent form",
             api.review_consent_form(MISSING, {"decision": "VERIFY"}, DIRECTOR),
             ApiErrorId.ERR_CONSENT_FORM_NOT_FOUND),
            ("payment",
             api.refund_payment(MISSING, make_treasurer_headers()),
             ApiErrorId.ERR_PAYMENT_NOT_FOUND),
            ("donation",
             api.refund_donation(MISSING, make_treasurer_headers()),
             ApiErrorId.ERR_DONATION_NOT_FOUND),
            ("chaperone", api.get_chaperone(MISSING, DIRECTOR),
             ApiErrorId.ERR_CHAPERONE_NOT_FOUND),
            ("background check",
             api.advance_background_check(MISSING, {"to_status": "SCREENING"},
                                          DIRECTOR),
             ApiErrorId.ERR_BACKGROUND_CHECK_NOT_FOUND),
            ("scholarship application",
             api.get_scholarship_application(MISSING, DIRECTOR),
             ApiErrorId.ERR_SCHOLARSHIP_APPLICATION_NOT_FOUND),
            ("chaperone assignment",
             api.get_chaperone_assignment(MISSING, DIRECTOR),
             ApiErrorId.ERR_CHAPERONE_ASSIGNMENT_NOT_FOUND),
            ("lodging reservation",
             api.cancel_lodging_reservation(MISSING, make_leader_headers()),
             ApiErrorId.ERR_LODGING_RESERVATION_NOT_FOUND),
            ("fundraising account",
             api.get_fundraising_account(MISSING, make_treasurer_headers()),
             ApiErrorId.ERR_FUNDRAISING_ACCOUNT_NOT_FOUND),
        ]
        for label, resp, error_id in probes:
            validate_error(resp, error_id, 404), label


class TestRoleBeforeExistence:
    def test_role_forbidden_precedes_existence(self, api):
        """PRD §2.8: "the error reported is the one from the earliest applicable
        check in this sequence" — "3. **Role authorization**: the presented role
        must appear in the endpoint's authorized list (`ERR_ROLE_FORBIDDEN`)"
        runs before "4. **Existence**".

        Design: Corner/validations/role_forbidden_precedes_existence
        """
        # Trip cancel is ProgramDirector-only; a Treasurer hits the role check
        # before the (missing) trip id is ever resolved.
        resp = api.cancel_trip(MISSING, make_treasurer_headers())
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN, 403)


class TestParticipantGradeBounds:
    def test_participant_grade_and_bounds_enforced(self, api):
        """PRD §3.3: "`grade` (an integer from 6 to 12)".
        PRD §2.8: "integer ranges respected (an `amount_cents` of zero or below,
        a `grade` outside 6 through 12, a `capacity_youth` below 1, and similar
        violations raise `ERR_INVALID_REQUEST`)".

        Design: Corner/entities/participant_grade_and_bounds_enforced
        """
        program = create_program()
        for bad_grade in (5, 13):
            resp = api.create_participant(
                create_participant_payload(program["id"], grade=bad_grade),
                make_guardian_headers("guardian-1"))
            validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

        for good_grade in (6, 12):
            resp = api.create_participant(
                create_participant_payload(program["id"], grade=good_grade,
                                           last_name=f"G{good_grade}"),
                make_guardian_headers("guardian-1"))
            data = validate_success(resp, 201)
            assert data["grade"] == good_grade
