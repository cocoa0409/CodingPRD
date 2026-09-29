"""
Endpoint contracts observed from the outside.

The scenarios here read what an endpoint actually promises to return: the
startup instant every date-derived field resolves against when nobody has moved
the clock, the counts and side effects of the activation batch, the deduction
history a saver can reach from their own enrolment, the narrow contact-update
surface of a participant record, and the registration action a headcount below
the mandate floor makes unavailable.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    CLOCK_2026_01_01,
    CLOCK_EPOCH,
    ERR_REGISTRATION_STATE_INVALID,
    PARTICIPANT_ANA,
    PARTICIPANT_ROSA,
    PARTICIPANT_TOMAS,
    REGISTRATION_DELTA,
    WAVE_3_DEADLINE,
    add_remittance_line,
    assert_amounts,
    assert_envelope_meta,
    assert_fields,
    assert_nulls,
    assert_total_count,
    build_active_saver_environment,
    create_employer,
    create_enrollment,
    create_fund_menu,
    create_investment_option,
    create_participant,
    create_program_year,
    create_remittance,
    make_employer_headers,
    make_participant_headers,
    opt_out,
    parse_instant,
    post_full_remittance,
    read_account,
    read_employer,
    read_enrollment,
    read_participant,
    read_remittance_line,
    register_employer,
    set_clock,
)

TINY_BAKERY = {
    "ein": "44-1112223",
    "legal_name": "Tiny Batch Bakery LLC",
    "employee_count": 3,
}

FIVE_PERSON_STUDIO = {
    "ein": "44-1112224",
    "legal_name": "Five Person Studio LLC",
    "employee_count": 5,
}


def test_dates_derive_from_the_startup_instant_when_the_clock_is_untouched(api):
    """
    Nothing in this scenario moves the clock, so the programme must still be
    sitting on the first of August 2026: a saver born in May 1980 is 46 at year
    end and an enrolment opened now gets a thirty-day notice deadline of the
    thirty-first of August, neither of which a host-clock fallback would produce.

    "The service maintains a **logical clock** whose value at start-up is exactly
    `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time —
    before any clock call is made, the clock reads that instant."

    Design: Corner/endpoints/logical_clock_starts_at_the_declared_epoch_before_any_set_call
    """
    create_program_year(api)
    create_investment_option(api)
    employer = create_employer(api)
    register_employer(api, employer["id"], REGISTRATION_DELTA)
    saver = create_participant(api, PARTICIPANT_ROSA)

    enrollment = validate_success(api.create_enrollment(
        employer["id"],
        {"participant_id": saver["id"], "hire_date": "2026-07-20",
         "annual_compensation_cents": 9600000},
        make_employer_headers(employer["id"])), expected_status=201)

    assert_fields(enrollment, {
        "enrollment_status": "NOTIFIED",
        "opt_out_deadline": "2026-08-31",
    }, label="enrolment opened at the startup instant")
    assert_fields(read_participant(api, saver["id"]), {
        "age_at_year_end": 46,
        "catch_up_eligible": False,
    }, label="saver aged against the startup instant")
    assert_fields(read_employer(api, employer["id"]), {
        "registration_status": "REGISTERED",
        "compliance_status": "COMPLIANT",
    }, label="employer at the startup instant")
    echoed = validate_success(
        api.set_current_utc({"current_utc": CLOCK_EPOCH}, ADMIN))
    # The PRD promises the response "echoes back the instant now in effect"; it
    # fixes the instant, not its rendering, so compare the instant itself. The
    # house ISO form declared in 2.2 and 2.4 carries three fractional digits,
    # which a faithful reader may equally apply to this echo.
    assert parse_instant(echoed["current_utc"]) == parse_instant(CLOCK_EPOCH), (
        f"clock echo {echoed['current_utc']!r} is not the instant {CLOCK_EPOCH!r}"
    )


def test_the_activation_batch_moves_only_the_enrolments_whose_notice_has_run(api):
    """
    Three enrolments meet the batch: one whose thirty-day notice has just run
    out, one the saver already refused, and one opened today whose deadline is
    still five weeks away. Exactly one is activated and exactly one account is
    opened, and the two the batch passed over are left as they were rather than
    aborting the run.

    "For each enrolment in `NOTIFIED` whose `opt_out_deadline` has arrived — the
    batch's evaluation date is on or after that deadline — and whose employer is
    still `REGISTERED`, the enrolment moves `NOTIFIED → ACTIVE`."

    Design: Corner/endpoints/auto_enrollment_run_activates_only_the_ripe_notified_enrollments
    """
    set_clock(api, CLOCK_2026_01_01)
    create_program_year(api)
    create_fund_menu(api)
    employer = create_employer(api)
    register_employer(api, employer["id"], REGISTRATION_DELTA)
    ripe_saver = create_participant(api, PARTICIPANT_ROSA)
    refusing_saver = create_participant(api, PARTICIPANT_ANA)
    late_hire = create_participant(api, PARTICIPANT_TOMAS)
    ripe = create_enrollment(api, employer["id"], ripe_saver["id"])
    refused = create_enrollment(api, employer["id"], refusing_saver["id"])
    opt_out(api, refused["id"], refusing_saver["id"], "AFFORDABILITY")
    set_clock(api, "2026-01-31T00:00:00Z")
    not_yet = create_enrollment(api, employer["id"], late_hire["id"],
                                hire_date="2026-01-28",
                                annual_compensation_cents=7200000)
    assert read_enrollment(api, not_yet["id"])["opt_out_deadline"] == "2026-03-02"

    run = validate_success(api.run_auto_enrollment(ADMIN, {}))

    assert_fields(run, {
        "activated_count": 1,
        "accounts_opened_count": 1,
    }, label="activation batch")
    assert "skipped_count" in run, "the batch must report skipped_count"
    assert read_enrollment(api, ripe["id"])["enrollment_status"] == "ACTIVE"
    assert read_enrollment(api, refused["id"])["enrollment_status"] == "OPTED_OUT"
    assert read_enrollment(api, not_yet["id"])["enrollment_status"] == "NOTIFIED"
    assert_total_count(api.list_participant_accounts(ADMIN), 1,
                       label="accounts after the run")
    opened = assert_total_count(
        api.list_participant_accounts(
            ADMIN, {"participant_id": ripe_saver["id"]}), 1,
        label="accounts of the activated saver")
    assert opened[0]["account_type"] == "ROTH_IRA"
    assert_total_count(
        api.list_participant_accounts(
            ADMIN, {"participant_id": refusing_saver["id"]}), 0,
        label="accounts of the saver who refused")
    assert_total_count(
        api.list_participant_accounts(
            ADMIN, {"participant_id": late_hire["id"]}), 0,
        label="accounts of the saver still inside her notice period")


def test_a_saver_reads_every_deduction_line_of_their_own_enrolment(api):
    """
    Three payroll lines for one saver are created under three different batches,
    two of them posted and one still sitting in an unsubmitted draft. The
    enrolment-scoped history gathers all three, and asking for the posted ones
    narrows the same collection to two rows without disturbing the envelope.

    "Remittance listings accept `employer_id` and `status`; remittance-line
    listings accept `status`."

    Design: Corner/endpoints/enrollment_remittance_line_history_is_reachable_from_the_enrollment
    """
    env = build_active_saver_environment(api)
    saver_headers = make_participant_headers(env["participant_id"])
    set_clock(api, "2026-03-06T00:00:00Z")
    post_full_remittance(api, env["employer_id"], env["enrollment_id"],
                         "2026-02-01", "2026-02-28", "2026-03-05",
                         4000000, 200000, "PR-2026-0001")
    set_clock(api, "2026-04-06T00:00:00Z")
    post_full_remittance(api, env["employer_id"], env["enrollment_id"],
                         "2026-03-01", "2026-03-31", "2026-04-03",
                         4000000, 200000, "PR-2026-0002")
    set_clock(api, "2026-05-06T00:00:00Z")
    draft = create_remittance(api, env["employer_id"], "2026-04-01",
                              "2026-04-30", "2026-05-05", 200000)
    pending_line = add_remittance_line(api, draft["id"], env["employer_id"],
                                       env["enrollment_id"], 4000000, 200000)

    whole_history = api.list_enrollment_remittance_lines(
        env["enrollment_id"], saver_headers)

    assert_envelope_meta(whole_history)
    assert_total_count(whole_history, 3, label="deduction history of the saver")
    posted_only = assert_total_count(
        api.list_enrollment_remittance_lines(
            env["enrollment_id"], saver_headers, {"status": "POSTED"}), 2,
        label="posted deduction history of the saver")
    for row in posted_only:
        assert_fields(row, {
            "status": "POSTED",
            "enrollment_id": env["enrollment_id"],
        }, label="posted line")
    still_pending = read_remittance_line(api, draft["id"], pending_line["id"])
    assert still_pending["status"] == "PENDING"
    assert_amounts(still_pending, {"allocated_cents": 0},
                   label="line of the unsubmitted batch")
    assert_amounts(read_enrollment(api, env["enrollment_id"]),
                   {"lifetime_deducted_cents": 400000}, label="enrolment")
    assert_amounts(read_account(api, env["account_id"]), {
        "ytd_contribution_cents": 400000,
        "remaining_headroom_cents": 300000,
    }, label="account after two postings")


def test_the_service_centre_update_touches_only_the_contact_fields(api):
    """
    A saver changes their own e-mail and address and then, in a second call,
    their telephone number alone. Every identity field and both derived age
    figures survive untouched, the e-mail set by the first call is not nulled by
    the second, and each accepted update moves the record's version by one.

    "Later, either the saver or a `ProgramAdministrator` may run a service-centre
    contact update supplying any of `email`, `mailing_address` and `phone`;
    identity and birth date are immutable, and the update increments the
    participant's `version`."

    Design: Corner/endpoints/participant_self_service_patch_updates_contact_fields_and_nothing_else
    """
    set_clock(api, CLOCK_2026_01_01)
    create_program_year(api)
    saver = create_participant(api, PARTICIPANT_ROSA)
    saver_headers = make_participant_headers(saver["id"])
    assert saver["version"] == 1

    validate_success(api.update_participant(
        saver["id"],
        {"email": "rosa.lim@new.example",
         "mailing_address": "88 Alder Way, Fresno CA 93701"},
        saver_headers))
    validate_success(api.update_participant(
        saver["id"], {"phone": "+1-559-555-0142"}, saver_headers))

    assert_fields(read_participant(api, saver["id"]), {
        "email": "rosa.lim@new.example",
        "mailing_address": "88 Alder Way, Fresno CA 93701",
        "phone": "+1-559-555-0142",
        "full_name": "Rosa Lim",
        "date_of_birth": "1980-05-10",
        "ssn_last4": "1234",
        "state_resident": True,
        "age_at_year_end": 46,
        "catch_up_eligible": False,
        "version": 3,
    }, label="saver after two contact updates")


def test_an_employer_below_the_mandate_floor_has_nothing_to_register_for(api):
    """
    A three-employee bakery is placed outside the mandate at creation, so its
    perfectly formed registration is unavailable to it and leaves the record
    exactly where it was; the five-employee studio beside it, one head above the
    floor, registers with the same payload shape.

    "Completing registration is the employer's own act and no one else's: only the
    `Employer` principal that owns the record may do it, the record must still be
    in `PENDING_REGISTRATION`, and its `wave_tier` must be something other than
    `NOT_COVERED` — otherwise the request is refused with
    `ERR_REGISTRATION_STATE_INVALID`."

    Design: Corner/endpoints/not_covered_employer_registration_is_rejected_as_state_invalid
    """
    set_clock(api, CLOCK_2026_01_01)
    create_program_year(api)
    tiny = create_employer(api, **TINY_BAKERY)
    covered = create_employer(api, **FIVE_PERSON_STUDIO)
    assert_fields(tiny, {
        "wave_tier": "NOT_COVERED",
        "registration_status": "EXEMPT_SMALL",
    }, label="employer below the mandate floor")
    assert_nulls(tiny, ["registration_deadline"], label="uncovered employer")

    validate_error(
        api.register_employer(
            tiny["id"],
            {"non_fiduciary_acknowledged": True,
             "payroll_contact_email": "owner@tinybatch.example"},
            make_employer_headers(tiny["id"])),
        ERR_REGISTRATION_STATE_INVALID)

    unchanged = read_employer(api, tiny["id"])
    assert unchanged["registration_status"] == "EXEMPT_SMALL"
    assert_nulls(unchanged, ["registered_at"], label="uncovered employer")
    assert_fields(covered, {
        "wave_tier": "WAVE_3",
        "registration_deadline": WAVE_3_DEADLINE,
    }, label="employer one head above the floor")
    registered = validate_success(api.register_employer(
        covered["id"],
        {"non_fiduciary_acknowledged": True,
         "payroll_contact_email": "owner@fiveperson.example"},
        make_employer_headers(covered["id"])))
    assert_fields(registered, {
        "registration_status": "REGISTERED",
        "non_fiduciary_acknowledged": True,
    }, label="employer that completed its registration")
