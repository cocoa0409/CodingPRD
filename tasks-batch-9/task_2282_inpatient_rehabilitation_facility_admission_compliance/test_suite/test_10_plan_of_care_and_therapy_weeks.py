"""Signing plans of care, superseding them, and opening therapy weeks."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_plan_of_care,
    assert_therapy_week,
    create_plan_of_care_payload,
    create_therapy_week_payload,
    evaluate_week,
    grant_week_exception_payload,
    open_therapy_week,
    read_admission,
    read_therapy_week,
    setup_facility_with_staff,
    setup_stay,
    setup_stay_with_week,
    sign_plan_of_care,
    validate_error,
    validate_success,
)


def test_plan_of_care_signed_without_a_mode_is_judged_daily():
    """The optional mode is omitted, so the daily three-hour variant is pinned.

    PRD §3.5: "One optional field, `three_hour_rule_mode`, selects how therapy
    weeks opened while this plan is active will be judged; it is either
    `DAILY_3HR` or `WEEKLY_15HR` and defaults to `DAILY_3HR`."

    Design: Corner/entities/plan_of_care_three_hour_rule_mode_defaults_to_daily
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stay = setup_stay(env, with_plan=False)
    admission = read_admission(stay["admission"]["id"])

    response = api_client.create_plan_of_care(
        create_plan_of_care_payload(admission["id"], admission["version"]),
        env["physician_headers"],
    )

    plan = validate_success(response, expected_status=201)
    assert_plan_of_care(plan)
    assert plan["three_hour_rule_mode"] == "DAILY_3HR"
    assert plan["status"] == "ACTIVE"
    assert plan["authored_by_clinician_id"] == env["physician"]["id"]
    assert plan["signed_at"].startswith("2026-08-04T12:00:00")
    assert read_admission(admission["id"])["documentation_status"] == "POC_SIGNED"


def test_second_plan_supersedes_the_first_without_repinning_the_open_week():
    """The new weekly mode reaches the next week only; week one keeps its own.

    PRD §3.5: "A second plan for the same admission is legitimate and does not
    replace history: the prior `ACTIVE` plan moves to `SUPERSEDED` and the new one
    becomes `ACTIVE`."

    PRD §3.5: "Therapy weeks that already exist keep the `evaluation_mode` they
    pinned at their own creation; only weeks opened after the new plan takes
    effect pin the new plan's `three_hour_rule_mode`."

    Design: Corner/state_machines/new_plan_supersedes_prior_plan_but_week_keeps_pinned_mode
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env)
    assert stay["week"]["evaluation_mode"] == "DAILY_3HR"

    second_plan = sign_plan_of_care(env, stay["admission"]["id"],
                                    three_hour_rule_mode="WEEKLY_15HR")

    assert second_plan["status"] == "ACTIVE"
    assert second_plan["three_hour_rule_mode"] == "WEEKLY_15HR"
    first_plan = validate_success(
        api_client.get_plan_of_care(stay["plan"]["id"], env["physician_headers"])
    )
    assert first_plan["status"] == "SUPERSEDED"
    assert read_therapy_week(stay["week"]["id"])["evaluation_mode"] == "DAILY_3HR"
    later_week = open_therapy_week(env, stay["admission"]["id"], week_index=2,
                                   week_start_date="2026-08-11")
    assert later_week["evaluation_mode"] == "WEEKLY_15HR"


def test_plan_of_care_pinning_a_superseded_admission_version_is_rejected():
    """Signing a plan advanced the admission, so the version once held is stale.

    PRD §2.7: "If that value differs from the admission's current `version`, the
    request is rejected with `ERR_STALE_ADMISSION_VERSION` and HTTP 412."

    Design: Corner/cross-cutting complexity layers/plan_of_care_create_with_stale_admission_version_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stay = setup_stay(env)
    version_before_signing = stay["admission"]["version"]

    response = api_client.create_plan_of_care(
        create_plan_of_care_payload(stay["admission"]["id"],
                                    version_before_signing),
        env["physician_headers"],
    )

    validate_error(response, ApiErrorId.ERR_STALE_ADMISSION_VERSION)
    still_active = validate_success(
        api_client.get_plan_of_care(stay["plan"]["id"], env["physician_headers"])
    )
    assert still_active["status"] == "ACTIVE"


def test_therapy_lead_may_not_sign_the_plan_of_care():
    """Signing the overall plan of care is a rehabilitation physician act.

    PRD §2.1: "If the headers are well formed but the declared role is not
    authorised for the endpoint being called, the rejection is
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/therapy_lead_cannot_create_plan_of_care
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay(env, with_plan=False)
    admission = read_admission(stay["admission"]["id"])

    response = api_client.create_plan_of_care(
        create_plan_of_care_payload(admission["id"], admission["version"]),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert read_admission(admission["id"])["documentation_status"] == "INCOMPLETE"


def test_therapy_week_opened_before_any_plan_is_signed_is_rejected():
    """Therapy cannot be measured against a plan that does not yet exist.

    PRD §3.6: "Opening a week requires an `ACTIVE` plan of care to exist for the
    admission (`ERR_PLAN_OF_CARE_MISSING`) and requires the admission to be
    `ADMITTED`."

    Design: Corner/validations/therapy_week_without_active_plan_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay(env, with_plan=False)

    response = api_client.create_therapy_week(
        create_therapy_week_payload(stay["admission"]["id"], 1, "2026-08-04"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PLAN_OF_CARE_MISSING)


def test_therapy_week_starting_the_day_before_admission_is_rejected():
    """The patient was admitted on 08-04, so a window opening 08-03 is too early.

    PRD §3.6: "The window may not start before the day the patient was admitted
    (`ERR_WEEK_BEFORE_ADMISSION`) and may not overlap any existing window of the
    same admission"

    Design: Corner/validations/week_starting_before_admission_date_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay(env)

    response = api_client.create_therapy_week(
        create_therapy_week_payload(stay["admission"]["id"], 1, "2026-08-03"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_WEEK_BEFORE_ADMISSION)


def test_second_window_reusing_week_index_one_is_rejected():
    """The adjacent window is legal in time but its ordinal is already taken.

    PRD §3.6: "The index is a 1-based ordinal of the window within the stay, from
    1 through 26, unique per admission — a repeat is `ERR_WEEK_INDEX_DUPLICATE`."

    Design: Corner/validations/duplicate_week_index_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env)

    response = api_client.create_therapy_week(
        create_therapy_week_payload(stay["admission"]["id"], 1, "2026-08-11"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_WEEK_INDEX_DUPLICATE)
    first = read_therapy_week(stay["week"]["id"])
    assert first["week_index"] == 1
    assert first["week_start_date"] == "2026-08-04"


def test_exception_granted_on_a_week_still_open_is_rejected():
    """The week has not yet been judged, so there is no failure to excuse.

    PRD §3.6: "The week must be in `NOT_MET` — an exception requested for a week
    in any other status is `ERR_EXCEPTION_NOT_ALLOWED` — and the granting
    physician must hold credential `REHAB_PHYSICIAN` with status `ACTIVE`."

    Design: Corner/state_machines/therapy_week_exception_from_open_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env)
    assert stay["week"]["status"] == "OPEN"

    response = api_client.grant_therapy_week_exception(
        stay["week"]["id"], grant_week_exception_payload(),
        env["physician_headers"],
    )

    validate_error(response, ApiErrorId.ERR_EXCEPTION_NOT_ALLOWED)
    untouched = read_therapy_week(stay["week"]["id"])
    assert_therapy_week(untouched)
    assert untouched["status"] == "OPEN"
    assert untouched["exception_reason"] is None


def test_therapy_lead_may_not_grant_the_week_exception():
    """The therapist who runs the week cannot excuse its own failure.

    PRD §3.6: "A `RehabPhysician` may grant a documented exception, supplying an
    `exception_reason`."

    PRD §2.1: "If the headers are well formed but the declared role is not
    authorised for the endpoint being called, the rejection is
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/therapy_lead_cannot_grant_week_exception
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env)
    evaluated = evaluate_week(env, stay["week"]["id"])
    assert evaluated["status"] == "NOT_MET"

    response = api_client.grant_therapy_week_exception(
        stay["week"]["id"], grant_week_exception_payload(), env["pt_headers"]
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    untouched = read_therapy_week(stay["week"]["id"])
    assert untouched["status"] == "NOT_MET"
    assert untouched["exception_granted_by_clinician_id"] is None
