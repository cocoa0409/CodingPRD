"""State-machine corners: invalid transitions, guarded transitions, preconditions,
initial state, and valid cycles.

Queue B — corner section: state_machines.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    setup_workers, open_case_with_child, set_clock,
    create_investigation_in_progress, create_screened_in_referral,
    make_judge_headers,
)


def test_rescreen_screened_out_referral_rejected(api):
    """PRD §3.1: "the screen of a referral not in `RECEIVED` status is an invalid transition (`ERR_INVALID_STATE`)."
    A SCREENED_OUT referral (low score) cannot be re-screened.

    Design: Corner/state_machines/screen_already_screened_out_referral_returns_invalid_state
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    ref = get_success_data(api.create_referral(
        {"reporter_type": "ANONYMOUS", "child_name": "Child B",
         "alleged_maltreatment": "EMOTIONAL_ABUSE", "priority_factors": []}, w.screener))
    out = get_success_data(api.screen_referral(ref["id"], w.screener))
    assert out["status"] == "SCREENED_OUT"

    resp = api.screen_referral(ref["id"], w.screener)
    validate_error(resp, "ERR_INVALID_STATE")


def test_open_case_from_safe_investigation_rejected(api):
    """PRD §3.3: "A dependency `Case` may be opened only from an investigation that recommended state intervention — that is, an investigation whose status is `UNSAFE` or `CONDITIONALLY_SAFE`."
    PRD §3.3: "opening against an investigation in any other status (including `SAFE`) is rejected with `ERR_INVESTIGATION_NOT_REMOVAL`."

    Design: Corner/state_machines/open_case_from_safe_investigation_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    inv = create_investigation_in_progress(w)
    decided = get_success_data(api.decide_investigation(
        inv["id"], {"safety_factors": ["NO_FOOD"], "protective_capacity": 5}, w.investigator))
    assert decided["status"] == "SAFE"

    resp = api.create_case({"investigation_id": inv["id"]}, w.caseworker)
    validate_error(resp, "ERR_INVESTIGATION_NOT_REMOVAL")


def test_open_investigation_on_not_screened_in_referral_rejected(api):
    """PRD §3.2: "The referral must actually be screened in: opening an investigation against a referral whose `status` is anything other than `SCREENED_IN` is rejected with `ERR_REFERRAL_NOT_SCREENED_IN`."

    Design: Corner/state_machines/investigation_on_not_screened_in_referral_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    ref = get_success_data(api.create_referral(
        {"reporter_type": "MANDATED", "child_name": "Child U",
         "alleged_maltreatment": "PHYSICAL_ABUSE",
         "priority_factors": ["INJURY_VISIBLE", "PRIOR_REPORT"]}, w.screener))
    # Not screened.
    resp = api.create_investigation(
        {"referral_id": ref["id"], "investigator_id": w.investigator_id}, w.caseworker)
    validate_error(resp, "ERR_REFERRAL_NOT_SCREENED_IN")


def test_hold_hearing_before_scheduled_time_rejected(api):
    """PRD §3.9: "Holding a scheduled hearing requires that the current clock has reached or passed its `scheduled_at` and that a `ruling` is provided in the request".

    Design: Corner/state_machines/hold_hearing_before_scheduled_time_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    hearing = get_success_data(api.create_hearing(
        {"case_id": case["id"], "hearing_type": "SHELTER",
         "scheduled_at": "2026-02-10T10:00:00Z"}, w.caseworker))
    resp = api.hold_hearing(hearing["id"], {"ruling": "CONTINUE_PLACEMENT"}, make_judge_headers())
    validate_error(resp, "ERR_INVALID_STATE")


def test_investigation_initial_state_is_assigned(api):
    """PRD §3.2: "A new investigation is born in status `ASSIGNED`."

    Design: Corner/state_machines/investigation_initial_state_is_assigned
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    ref = create_screened_in_referral(w)
    inv = validate_success(api.create_investigation(
        {"referral_id": ref["id"], "investigator_id": w.investigator_id}, w.caseworker),
        expected_status=201)
    assert inv["status"] == "ASSIGNED"


def test_cancel_visit_after_window_open_rejected(api):
    """PRD §3.8: "it is **cancelled** only while the current clock is still strictly before its `window_start` (moving `SCHEDULED` to `CANCELLED`)."
    PRD §3.8: "an attempt that violates the timing precondition or operates on a non-scheduled visit fails the state guard."

    Design: Corner/state_machines/cancel_visit_after_window_open_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-02-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = get_success_data(api.create_case_plan(
        {"case_id": case["id"], "required_visits_per_month": 4, "objectives_total": 5}, w.caseworker))
    vis = get_success_data(api.create_visitation(
        {"case_plan_id": plan["id"], "child_id": child["id"], "supervision": "SUPERVISED",
         "window_start": "2026-02-05T10:00:00Z", "window_end": "2026-02-05T11:00:00Z"}, w.caseworker))
    set_clock("2026-02-05T10:30:00Z")  # window already open
    resp = api.cancel_visitation(vis["id"], w.caseworker)
    validate_error(resp, "ERR_INVALID_STATE")


def test_hearing_continue_then_reschedule_cycle(api):
    """PRD §3.9: "A judge may also **continue** a scheduled hearing (moving `SCHEDULED` to `CONTINUED`), later **reschedule** a continued hearing back to `SCHEDULED` at a newly supplied `scheduled_at".

    Design: Corner/state_machines/hearing_continue_reschedule_cycle_succeeds
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    judge = make_judge_headers()
    hearing = get_success_data(api.create_hearing(
        {"case_id": case["id"], "hearing_type": "REVIEW",
         "scheduled_at": "2026-01-20T10:00:00Z"}, w.caseworker))
    get_success_data(api.continue_hearing(hearing["id"], judge))
    rescheduled = validate_success(api.reschedule_hearing(
        hearing["id"], {"scheduled_at": "2026-02-15T10:00:00Z"}, judge))
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["scheduled_at"] == "2026-02-15T10:00:00.000Z"
