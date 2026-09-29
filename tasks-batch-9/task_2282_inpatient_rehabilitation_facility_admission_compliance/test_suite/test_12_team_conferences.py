"""The weekly interdisciplinary team conference: chair, attendance and timing."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_team_conference,
    create_team_conference_payload,
    read_admission,
    record_conference,
    set_clock,
    setup_facility_with_staff,
    setup_stay_with_week,
    validate_error,
    validate_success,
)

PLAN_PT = {"three_hour_rule_mode": "DAILY_3HR", "disciplines": ["PT"]}


def test_conference_chaired_by_the_nurse_is_rejected():
    """The nurse records the conference but may not be the one who chairs it.

    PRD §3.7: "The chair must hold credential `REHAB_PHYSICIAN` and be `ACTIVE`;
    any other credential is `ERR_CONFERENCE_LEAD_NOT_PHYSICIAN`."

    Design: Corner/validations/conference_led_by_nurse_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    set_clock("2026-08-05T18:00:00Z")

    response = api_client.create_team_conference(
        create_team_conference_payload(
            stay["admission"]["id"], stay["week"]["id"], env["nurse"]["id"],
            [env["nurse"]["id"], env["pt"]["id"]], "2026-08-05T14:00:00Z",
        ),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CONFERENCE_LEAD_NOT_PHYSICIAN)
    assert read_admission(stay["admission"]["id"])["conference_compliant"] is False


def test_conference_without_a_therapist_of_the_planned_discipline_is_rejected():
    """The plan names physical therapy, so a PT must sit at the table.

    PRD §3.7: "the participants must include at least one clinician with the
    `NURSE` credential and, for every discipline named in the admission's
    `ACTIVE` plan of care, at least one therapist holding the matching credential
    — a gap on either count is `ERR_CONFERENCE_PARTICIPANTS_INCOMPLETE`."

    Design: Corner/validations/conference_without_therapist_participant_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    set_clock("2026-08-05T18:00:00Z")

    response = api_client.create_team_conference(
        create_team_conference_payload(
            stay["admission"]["id"], stay["week"]["id"], env["physician"]["id"],
            [env["nurse"]["id"]], "2026-08-05T14:00:00Z",
        ),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CONFERENCE_PARTICIPANTS_INCOMPLETE)


def test_conference_held_the_day_after_the_window_closes_is_rejected():
    """The window ends 08-10, so a meeting held on 08-11 documents nothing.

    PRD §3.7: "The UTC calendar date of `held_at` must fall inside the week's
    window, from `week_start_date` through `week_end_date` inclusive; a conference
    held outside its own week is `ERR_CONFERENCE_OUTSIDE_WEEK`."

    Design: Corner/validations/conference_held_outside_week_window_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    assert stay["week"]["week_end_date"] == "2026-08-10"
    set_clock("2026-08-11T18:00:00Z")

    response = api_client.create_team_conference(
        create_team_conference_payload(
            stay["admission"]["id"], stay["week"]["id"], env["physician"]["id"],
            [env["nurse"]["id"], env["pt"]["id"]], "2026-08-11T14:00:00Z",
        ),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CONFERENCE_OUTSIDE_WEEK)


def test_second_recorded_conference_for_the_same_week_is_rejected():
    """One recorded discussion per week is the whole of the entitlement.

    PRD §3.7: "Only a `RECORDED` conference counts toward compliance, and at most
    one `RECORDED` conference may exist per therapy week — a second attempt where
    one already exists is `ERR_CONFERENCE_ALREADY_RECORDED`."

    Design: Corner/validations/second_conference_for_same_week_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    set_clock("2026-08-05T18:00:00Z")
    first = record_conference(env, stay["admission"]["id"], stay["week"]["id"],
                              "2026-08-05T14:00:00Z")
    assert first["status"] == "RECORDED"

    response = api_client.create_team_conference(
        create_team_conference_payload(
            stay["admission"]["id"], stay["week"]["id"], env["physician"]["id"],
            [env["nurse"]["id"], env["pt"]["id"]], "2026-08-06T14:00:00Z",
        ),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CONFERENCE_ALREADY_RECORDED)


def test_conference_held_and_recorded_on_the_closing_day_counts_as_recorded():
    """Recording on 08-10 itself is still timely, so the admission is compliant.

    PRD §3.7: "the conference's `status` is `RECORDED` when the logical clock's
    calendar date at the moment of recording is at or before the week's
    `week_end_date`, and `LATE_RECORDED` when it is after."

    Design: Corner/validations/conference_on_final_day_of_week_window_accepted
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    set_clock("2026-08-10T18:00:00Z")

    response = api_client.create_team_conference(
        create_team_conference_payload(
            stay["admission"]["id"], stay["week"]["id"], env["physician"]["id"],
            [env["nurse"]["id"], env["pt"]["id"]], "2026-08-10T14:00:00Z",
        ),
        env["nurse_headers"],
    )

    conference = validate_success(response, expected_status=201)
    assert_team_conference(conference)
    assert conference["status"] == "RECORDED"
    assert conference["held_at"].startswith("2026-08-10T14:00:00")
    assert read_admission(stay["admission"]["id"])["conference_compliant"] is True


def test_conference_naming_another_stays_therapy_week_is_rejected():
    """Two stays run side by side and their weeks may not be crossed over.

    PRD §2.10: "a therapy week named on a team conference must belong to the same
    admission as the conference, reported as `ERR_WEEK_ADMISSION_MISMATCH`"

    Design: Corner/validations/conference_referencing_another_admissions_week_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay_a = setup_stay_with_week(env, mrn="MRN-A", plan_overrides=PLAN_PT)
    stay_b = setup_stay_with_week(
        env, mrn="MRN-B", patient_overrides={"full_name": "Bo Whitaker"},
        plan_overrides=PLAN_PT,
    )
    set_clock("2026-08-05T18:00:00Z")

    response = api_client.create_team_conference(
        create_team_conference_payload(
            stay_a["admission"]["id"], stay_b["week"]["id"],
            env["physician"]["id"],
            [env["nurse"]["id"], env["pt"]["id"]], "2026-08-05T14:00:00Z",
        ),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_WEEK_ADMISSION_MISMATCH)
    assert read_admission(stay_a["admission"]["id"])["conference_compliant"] is False
