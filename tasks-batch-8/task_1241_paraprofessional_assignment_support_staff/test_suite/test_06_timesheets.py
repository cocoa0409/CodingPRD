"""Timesheets: logging, computed minutes, closed-interval double-log protection,
and the submit/reject/approve cycle (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_timesheet,
    create_active_assignment,
    create_active_plan,
    create_active_student,
    create_para,
    create_timesheet_payload,
    log_timesheet,
    make_para_headers,
    setup_plan_with_active_assignment,
    submit_timesheet,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANY = TEST_USERS["any_headers"]
BLDG_ADMIN = TEST_USERS["building_admin_headers"]


def test_timesheet_minutes_worked_computed(api):
    """PRD §3.7: "The entry’s `minutes_worked` is the window length in minutes, and its `plan_id` derives from the assignment."

    Design: Corner/entities/timesheet_minutes_worked_computed
    """
    scenario = setup_plan_with_active_assignment()
    a1, p1 = scenario["a1"], scenario["p1"]

    resp = api.create_timesheet(
        create_timesheet_payload(a1["id"], "2026-05-04", 480, 700),
        make_para_headers(p1["id"]),
    )
    entry = validate_success(resp, 201)
    assert entry["minutes_worked"] == 220  # 700 - 480
    assert entry["status"] == "DRAFT"
    assert entry["plan_id"] == scenario["plan"]["id"]
    assert entry["para_id"] == p1["id"]


def test_timesheet_closed_interval_touch_is_conflict(api):
    """PRD §3.7: "Double-logging is policed with closed-interval semantics, a deliberate contrast to the half-open assignment rule: for the same para and `work_date`, a new entry conflicts with any existing entry in `SUBMITTED` or `APPROVED` when the intervals touch or overlap at all — the new start on or before the other’s end, and the other’s start on or before the new end — and touching endpoints count as conflict. Entries still in `DRAFT` do not participate."

    Design: Difficulty/resource_temporal_overlap/timesheet_closed_interval_touch_conflict
    """
    scenario = setup_plan_with_active_assignment()
    a1, p1 = scenario["a1"], scenario["p1"]
    t1 = log_timesheet(a1["id"], p1["id"], "2026-05-04", 480, 660)
    submit_timesheet(t1["id"], p1["id"])

    # New entry start touches the SUBMITTED entry's end (660 == 660) -> conflict
    resp = api.create_timesheet(
        create_timesheet_payload(a1["id"], "2026-05-04", 660, 780),
        make_para_headers(p1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_OVERLAP)
    entries = validate_success(
        api.list_timesheets(ANY, params={"plan_id": scenario["plan"]["id"]})
    )
    assert len(entries) == 1  # no second entry persisted


def test_timesheet_reject_resubmit_cycle_ends_approved(api):
    """PRD §3.7: "New entries sit in `DRAFT`. Submission moves an entry from `DRAFT` to `SUBMITTED`, requires the caller to be the entry’s para (else `ERR_TIMESHEET_NOT_OWN`), and re-runs the closed-interval overlap check. A `BuildingAdministrator` then approves — `SUBMITTED` to `APPROVED`, terminal — or rejects, which bounces the entry from `SUBMITTED` back to `DRAFT` for correction and resubmission; both decisions are accepted while the plan is `ACTIVE` or `RECONCILING`, and any other transition attempt is `ERR_TIMESHEET_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/timesheet_reject_resubmit_cycle
    """
    scenario = setup_plan_with_active_assignment()
    a1, p1 = scenario["a1"], scenario["p1"]
    t1 = log_timesheet(a1["id"], p1["id"], "2026-05-04", 480, 780)

    submitted = submit_timesheet(t1["id"], p1["id"])
    assert submitted["status"] == "SUBMITTED"
    rejected = validate_success(api.reject_timesheet(t1["id"], BLDG_ADMIN))
    assert rejected["status"] == "DRAFT"  # bounce-back revision loop
    resubmitted = submit_timesheet(t1["id"], p1["id"])
    assert resubmitted["status"] == "SUBMITTED"
    approved = approve_timesheet(t1["id"])
    assert approved["status"] == "APPROVED"
    final = validate_success(api.get_timesheet(t1["id"], ANY))
    assert final["version"] == 5  # create + submit + reject + submit + approve


def test_approve_draft_timesheet_returns_invalid_state(api):
    """PRD §3.7: "A `BuildingAdministrator` then approves — `SUBMITTED` to `APPROVED`, terminal — or rejects, which bounces the entry from `SUBMITTED` back to `DRAFT` for correction and resubmission; both decisions are accepted while the plan is `ACTIVE` or `RECONCILING`, and any other transition attempt is `ERR_TIMESHEET_INVALID_STATE`."

    Design: Corner/errors/approve_draft_timesheet_returns_invalid_state
    """
    scenario = setup_plan_with_active_assignment()
    a1, p1 = scenario["a1"], scenario["p1"]
    t1 = log_timesheet(a1["id"], p1["id"], "2026-05-04", 480, 780)
    assert t1["status"] == "DRAFT"
    resp = api.approve_timesheet(t1["id"], BLDG_ADMIN)
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_INVALID_STATE)


def test_timesheet_create_for_other_para_returns_not_own(api):
    """PRD §3.7: "The entry’s `para_id` is always fixed to the caller’s `X-User-ID`, and attempting to log against an assignment owned by a different para is rejected with `ERR_TIMESHEET_NOT_OWN`."

    Design: Corner/errors/timesheet_create_for_other_para_returns_not_own
    """
    scenario = setup_plan_with_active_assignment()
    plan_id, b1 = scenario["plan"]["id"], scenario["building"]["id"]
    a1 = scenario["a1"]
    p2 = create_para(plan_id, b1, full_name="Sam Sub", hire_date="2025-09-01")

    resp = api.create_timesheet(
        create_timesheet_payload(a1["id"], "2026-05-04", 480, 540),
        make_para_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_NOT_OWN)


def test_approved_timesheet_is_terminal(api):
    """PRD §3.7: "A `BuildingAdministrator` then approves — `SUBMITTED` to `APPROVED`, terminal — or rejects, which bounces the entry from `SUBMITTED` back to `DRAFT` for correction and resubmission; both decisions are accepted while the plan is `ACTIVE` or `RECONCILING`, and any other transition attempt is `ERR_TIMESHEET_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/timesheet_reject_resubmit_cycle
    """
    scenario = setup_plan_with_active_assignment()
    a1, p1 = scenario["a1"], scenario["p1"]
    t1 = log_timesheet(a1["id"], p1["id"], "2026-05-04", 480, 780)
    submit_timesheet(t1["id"], p1["id"])
    approved = approve_timesheet(t1["id"])
    assert approved["status"] == "APPROVED"

    # APPROVED is terminal: neither resubmission nor reject is declared from it
    resp_submit = api.submit_timesheet(t1["id"], make_para_headers(p1["id"]))
    validate_error(resp_submit, ApiErrorId.ERR_TIMESHEET_INVALID_STATE)
    resp_reject = api.reject_timesheet(t1["id"], BLDG_ADMIN)
    validate_error(resp_reject, ApiErrorId.ERR_TIMESHEET_INVALID_STATE)
    after = validate_success(api.get_timesheet(t1["id"], ANY))
    assert after["status"] == "APPROVED"


def test_draft_timesheets_excluded_from_overlap_but_submit_rechecks(api):
    """PRD §3.7: "Entries still in `DRAFT` do not participate."
    PRD §3.7: "The check runs at creation and again at submission, and a conflict rejects with `ERR_TIMESHEET_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/timesheet_closed_interval_touch_conflict
    """
    scenario = setup_plan_with_active_assignment()
    a1, p1 = scenario["a1"], scenario["p1"]
    t1 = log_timesheet(a1["id"], p1["id"], "2026-05-04", 480, 660)  # stays DRAFT

    # T2 touches T1's endpoint, but T1 is DRAFT and does not participate at create
    t2 = log_timesheet(a1["id"], p1["id"], "2026-05-04", 660, 780)
    assert t2["status"] == "DRAFT"

    # Once T1 is SUBMITTED, the closed-interval re-check at T2's submission fires
    submit_timesheet(t1["id"], p1["id"])
    resp = api.submit_timesheet(t2["id"], make_para_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_OVERLAP)
    after = validate_success(api.get_timesheet(t2["id"], ANY))
    assert after["status"] == "DRAFT"
