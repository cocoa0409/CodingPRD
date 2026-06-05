"""Direct validation-violation corners (single-failure scenarios).

Queue B — corner section: validations.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    setup_workers, open_case_with_child, create_licensed_home, create_pending_home,
    place_child, setup_placed_child, set_clock, create_screened_in_referral,
)


def test_sod_conflict_screener_cannot_investigate_own_referral(api):
    """PRD §3.2: "the supplied `investigator_id` must not equal the originating referral's `screened_in_by`. A worker may not investigate a referral they themselves screened in; that conflict is rejected with `ERR_SOD_CONFLICT`."

    Design: Corner/validations/sod_conflict_screener_cannot_investigate_own_referral
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    # The screener screens the referral in; then is offered as investigator.
    ref = create_screened_in_referral(w)
    resp = api.create_investigation(
        {"referral_id": ref["id"], "investigator_id": w.screener_id}, w.caseworker)
    validate_error(resp, "ERR_SOD_CONFLICT")


def test_visitation_window_end_not_after_start_rejected(api):
    """PRD §3.8: "The window must be well-formed: `window_end` must be strictly after `window_start`, else the schedule is rejected with `ERR_INVALID_WINDOW`."
    window_end == window_start is not strictly after -> rejected.

    Design: Corner/validations/visitation_window_end_not_after_start_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-02-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = get_success_data(api.create_case_plan(
        {"case_id": case["id"], "required_visits_per_month": 4, "objectives_total": 5}, w.caseworker))
    resp = api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T11:00:00Z", "window_end": "2026-02-05T11:00:00Z"}, w.caseworker)
    validate_error(resp, "ERR_INVALID_WINDOW")


def test_placement_child_age_exceeds_home_max_age_rejected(api):
    """PRD §3.5: "the child's `age_years` must be no greater than the home's `max_age_years`, else `ERR_AGE_NOT_LICENSED".
    Child age 10 (born 2016, clock 2026-06) into a home with max_age_years 5.

    Design: Corner/validations/placement_age_exceeds_home_max_age_rejected
    """
    w = setup_workers()
    set_clock("2026-06-01T00:00:00Z")
    case, child = open_case_with_child(w, dob="2016-01-01T00:00:00Z")
    home = create_licensed_home(w, bed_capacity=1, max_age_years=5)
    resp = api.create_placement(
        {"child_id": child["id"], "foster_home_id": home["id"],
         "expected_foster_home_version": home["version"]}, w.caseworker)
    validate_error(resp, "ERR_AGE_NOT_LICENSED")


def test_place_into_pending_home_rejected(api):
    """PRD §3.5: "its `license_status` must be `LICENSED` or `PROVISIONAL`, never `PENDING`, `SUSPENDED`, or `EXPIRED`, else `ERR_HOME_NOT_LICENSED".

    Design: Corner/validations/place_into_pending_unlicensed_home_rejected
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    home = create_pending_home(w, bed_capacity=1, max_age_years=18)
    resp = api.create_placement(
        {"child_id": child["id"], "foster_home_id": home["id"],
         "expected_foster_home_version": home["version"]}, w.caseworker)
    validate_error(resp, "ERR_HOME_NOT_LICENSED")


def test_license_with_flagged_clearance_rejected(api):
    """PRD §3.4: "if any screening is `FLAGGED`, the request is rejected with `ERR_CLEARANCE_FLAGGED".

    Design: Corner/validations/license_with_flagged_clearance_rejected
    """
    w = setup_workers()
    home = get_success_data(api.create_foster_home(
        {"licensing_worker_id": w.licensing_id, "home_name": "Home FL",
         "bed_capacity": 1, "max_age_years": 18, "accepts_maltreatment": ["NEGLECT"]}, w.licensing))
    scr = get_success_data(api.create_screening(
        {"foster_home_id": home["id"], "member_name": "Risky Member", "disqualifying": True}, w.licensing))
    get_success_data(api.resolve_screening(scr["id"], w.licensing))
    resp = api.license_home(home["id"], {"expected_foster_home_version": home["version"]}, w.licensing)
    validate_error(resp, "ERR_CLEARANCE_FLAGGED")


def test_license_with_pending_clearance_incomplete_rejected(api):
    """PRD §3.4: "if no screening is flagged but at least one is still `PENDING`, it is rejected with `ERR_CLEARANCES_INCOMPLETE`."

    Design: Corner/validations/license_with_pending_clearance_incomplete_rejected
    """
    w = setup_workers()
    home = get_success_data(api.create_foster_home(
        {"licensing_worker_id": w.licensing_id, "home_name": "Home PC",
         "bed_capacity": 1, "max_age_years": 18, "accepts_maltreatment": ["NEGLECT"]}, w.licensing))
    get_success_data(api.create_screening(
        {"foster_home_id": home["id"], "member_name": "Unresolved Member"}, w.licensing))
    # Screening left PENDING (unresolved).
    resp = api.license_home(home["id"], {"expected_foster_home_version": home["version"]}, w.licensing)
    validate_error(resp, "ERR_CLEARANCES_INCOMPLETE")


def test_no_beds_when_home_at_capacity_rejected(api):
    """PRD §3.5: "the home must have an open bed — its `active_placement_count` must be strictly less than its `bed_capacity`, else `ERR_NO_BEDS".
    A cap-1 home already holding one ACTIVE placement rejects a second child.

    Design: Corner/validations/no_beds_when_home_at_capacity_rejected
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child1, home, placement = setup_placed_child(w, bed_capacity=1)
    child2 = get_success_data(api.create_child(
        {"case_id": case["id"], "full_name": "Child NB2",
         "date_of_birth": "2016-01-01T00:00:00Z"}, w.caseworker))
    home_now = get_success_data(api.get_foster_home(home["id"], w.caseworker))
    resp = api.create_placement(
        {"child_id": child2["id"], "foster_home_id": home["id"],
         "expected_foster_home_version": home_now["version"]}, w.caseworker)
    validate_error(resp, "ERR_NO_BEDS")


def test_age_out_under_age_rejected(api):
    """PRD §3.10: "The caseworker ages out a child who is `PLACED` or in `TRIAL_HOME_VISIT` and whose `age_years` is at least 18; an attempt on a younger child is rejected with `ERR_AGE_NOT_ELIGIBLE`."
    A PLACED child age 10 cannot age out.

    Design: Corner/validations/age_out_under_age_rejected
    """
    w = setup_workers()
    set_clock("2026-06-01T00:00:00Z")
    case, child, home, placement = setup_placed_child(w, dob="2016-01-01T00:00:00Z")
    resp = api.age_out(child["id"], w.caseworker)
    validate_error(resp, "ERR_AGE_NOT_ELIGIBLE")
