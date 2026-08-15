"""Inquiry intake rules, application filing guards, and funnel counters."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_applicant,
    create_applicant,
    create_applicant_payload,
    create_application_for_new_applicant,
    create_cycle,
    create_program,
    is_valid_uuid,
    setup_open_cycle_with_program,
    submit_application,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]


class TestApplicantTypeData:
    def test_readmit_dismissed_rejected(self, api):
        """PRD 3.3: "a `READMIT` applicant must supply `prior_standing`, one
        of `GOOD_STANDING`, `ACADEMIC_PROBATION`, or `DISMISSED`; missing
        type-required data is rejected with `ERR_APPLICANT_TYPE_DATA_MISSING`,
        and a readmit applicant whose `prior_standing` is `DISMISSED` is
        rejected outright with `ERR_READMIT_NOT_ELIGIBLE`."

        Design: Corner/validations/readmit_dismissed_rejected
        """
        cycle = create_cycle()
        bad = api.create_applicant(
            create_applicant_payload(cycle["id"], applicant_type="READMIT",
                                     prior_standing="DISMISSED"),
            OFFICER)
        validate_error(bad, ApiErrorId.ERR_READMIT_NOT_ELIGIBLE)

        good = api.create_applicant(
            create_applicant_payload(cycle["id"], applicant_type="READMIT",
                                     prior_standing="GOOD_STANDING"),
            OFFICER)
        applicant = validate_success(good, 201)
        assert_applicant(applicant)
        assert applicant["applicant_type"] == "READMIT"

    def test_transfer_missing_credits_rejected(self, api):
        """PRD 3.3: "a `TRANSFER` applicant must supply
        `transfer_credit_hours` (a non-negative integer), and a `READMIT`
        applicant must supply `prior_standing`, one of `GOOD_STANDING`,
        `ACADEMIC_PROBATION`, or `DISMISSED`; missing type-required data is
        rejected with `ERR_APPLICANT_TYPE_DATA_MISSING`"

        Design: Corner/validations/transfer_missing_credits_rejected
        """
        cycle = create_cycle()
        missing = api.create_applicant(
            create_applicant_payload(cycle["id"], applicant_type="TRANSFER"),
            OFFICER)
        validate_error(missing, ApiErrorId.ERR_APPLICANT_TYPE_DATA_MISSING)

        supplied = api.create_applicant(
            create_applicant_payload(cycle["id"], applicant_type="TRANSFER",
                                     transfer_credit_hours=30),
            OFFICER)
        applicant = validate_success(supplied, 201)
        assert applicant["transfer_credit_hours"] == 30


class TestApplicantEmailUniqueness:
    def test_duplicate_email_same_cycle_rejected(self, api):
        """PRD 3.3: "Email addresses are unique within a cycle: a second
        inquiry in the same cycle carrying an `email` already present on
        another applicant of that cycle is rejected with
        `ERR_DUPLICATE_APPLICANT_EMAIL`."

        Design: Corner/validations/duplicate_email_same_cycle_rejected
        """
        cycle_one = create_cycle()
        cycle_two = create_cycle(name="Spring 2028")
        first = api.create_applicant(
            create_applicant_payload(cycle_one["id"], email="dup@x.com"),
            OFFICER)
        validate_success(first, 201)

        same_cycle = api.create_applicant(
            create_applicant_payload(cycle_one["id"], email="dup@x.com",
                                     inquiry_source="REFERRAL"),
            OFFICER)
        validate_error(same_cycle, ApiErrorId.ERR_DUPLICATE_APPLICANT_EMAIL)

        other_cycle = api.create_applicant(
            create_applicant_payload(cycle_two["id"], email="dup@x.com"),
            OFFICER)
        validate_success(other_cycle, 201)


class TestApplicantSystemFields:
    def test_applicant_system_fields_input_ignored(self, api):
        """PRD 2.5: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD 2.5: "`version` (integer): a system-managed integer that
        increments with every modification to the resource."

        Design: Corner/entities/applicant_system_fields_input_ignored
        """
        cycle = create_cycle()
        payload = create_applicant_payload(cycle["id"])
        payload["id"] = "11111111-1111-4111-8111-111111111111"
        payload["version"] = 42
        applicant = validate_success(api.create_applicant(payload, OFFICER),
                                     201)
        assert applicant["id"] != "11111111-1111-4111-8111-111111111111", \
            "The server mints its own id, ignoring the client-supplied one"
        assert is_valid_uuid(applicant["id"])
        assert isinstance(applicant["version"], int), \
            "version is system-managed; the client-supplied 42 is ignored"
        assert applicant["version"] != 42


class TestApplicationFiling:
    def test_application_bad_program_fk_not_found(self, api):
        """PRD 2.9: "Third, existence — any path identifier or body foreign
        key (`applicant_id`, `program_id`, `cycle_id`, `application_id`) that
        does not resolve yields `ERR_NOT_FOUND`."

        Design: Corner/entities/application_bad_program_fk_not_found
        """
        setup = setup_open_cycle_with_program(name="FKP")
        applicant = create_applicant(setup["cycle"]["id"])
        resp = api.create_application(
            {"applicant_id": applicant["id"], "program_id": NON_EXISTENT_UUID,
             "cycle_id": setup["cycle"]["id"], "academic_score": 80,
             "efc_cents": 5_000_000},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_program_cycle_mismatch_rejected(self, api):
        """PRD 3.3: "the declared `cycle_id` must equal both the referenced
        applicant's cycle and the referenced program's cycle, with any
        divergence rejected as `ERR_PROGRAM_CYCLE_MISMATCH`"

        Design: Corner/validations/program_cycle_mismatch_rejected
        """
        set_up = setup_open_cycle_with_program(name="P1")
        cycle_one = set_up["cycle"]
        cycle_two = create_cycle(name="Spring 2028")
        program_two = create_program(cycle_two["id"], name="P2")
        applicant = create_applicant(cycle_one["id"])

        resp = api.create_application(
            {"applicant_id": applicant["id"], "program_id": program_two["id"],
             "cycle_id": cycle_one["id"], "academic_score": 80,
             "efc_cents": 5_000_000},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CYCLE_MISMATCH)

    def test_application_score_out_of_range_rejected(self, api):
        """PRD 3.3: "an `academic_score` outside the 0-to-100 range is
        rejected with `ERR_SCORE_OUT_OF_RANGE`"

        Design: Corner/entities/application_score_out_of_range_rejected
        """
        setup = setup_open_cycle_with_program(name="RNG")
        applicant = create_applicant(setup["cycle"]["id"])
        resp = api.create_application(
            {"applicant_id": applicant["id"],
             "program_id": setup["program"]["id"],
             "cycle_id": setup["cycle"]["id"], "academic_score": 120,
             "efc_cents": 5_000_000},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE)

    def test_application_create_cycle_not_open_rejected(self, api):
        """PRD 3.3: "and the cycle must currently be in `OPEN`, with filings
        at any other phase rejected with `ERR_CYCLE_PHASE_MISMATCH`."

        Design: Corner/validations/application_create_cycle_not_open_rejected
        """
        cycle = create_cycle()
        program = create_program(cycle["id"], name="NOP")
        applicant = create_applicant(cycle["id"])
        resp = api.create_application(
            {"applicant_id": applicant["id"], "program_id": program["id"],
             "cycle_id": cycle["id"], "academic_score": 80,
             "efc_cents": 5_000_000},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_PHASE_MISMATCH)


class TestFunnelCounters:
    def test_cycle_funnel_counters_reconciled(self, api):
        """PRD 3.3: "A successful filing lands in `SUBMITTED`, stamps
        `submitted_at` from the logical clock, initializes `review_round` to
        1, flips the applicant from `INQUIRY` to `APPLIED` — an automatic,
        absorbing transition that never reverses — and recomputes the cycle's
        `application_count`."
        PRD 3.1: "`inquiry_count` tracks how many applicants are attributed
        to the cycle, `application_count` tracks applications filed in it"

        Design: Corner/cross_cutting_layers/cycle_funnel_counters_reconciled
        """
        setup = setup_open_cycle_with_program(name="DFR")
        cycle_id = setup["cycle"]["id"]
        first = create_applicant(cycle_id, full_name="Df 1")
        second = create_applicant(cycle_id, full_name="Df 2")

        submit_application(cycle_id, setup["program"]["id"], first["id"],
                           academic_score=80)

        cycle = validate_success(api.get_cycle(cycle_id, OFFICER))
        assert cycle["inquiry_count"] == 2
        assert cycle["application_count"] == 1

        first_after = validate_success(api.get_applicant(first["id"], OFFICER))
        assert first_after["funnel_stage"] == "APPLIED", \
            "The first filing flips the applicant INQUIRY -> APPLIED"
        second_after = validate_success(
            api.get_applicant(second["id"], OFFICER))
        assert second_after["funnel_stage"] == "INQUIRY", \
            "An applicant without a filing remains INQUIRY"
