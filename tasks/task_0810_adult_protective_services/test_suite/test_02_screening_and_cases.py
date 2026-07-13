"""Report screening: the RECEIVED -> {SCREENED_IN, SCREENED_OUT} fork, the
divergent side effects, and immediate case visibility."""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx

SUPERVISOR = TEST_USERS["supervisor_headers"]


def test_screen_out_sets_terminal_status_and_reason(api):
    """PRD §3.2: "On the **screen-out** branch, the report moves from `RECEIVED`
    to `SCREENED_OUT`. Here the system records the supplied `screen_out_reason`
    on the report and stamps `screening_overdue` as just described, but no case
    is created and the subject client is left entirely untouched".

    Design: Difficulty/non_linear_state_machine/report_screen_out_branch_no_case
    """
    client = fx.new_client()
    report = fx.new_report(client["id"], reporter_type="ANONYMOUS",
                           allegation_types=["SELF_NEGLECT"], priority="ROUTINE", narrative="welfare check")
    resp = api.screen_report(report["id"],
                             {"decision": "SCREEN_OUT", "screen_out_reason": "does not meet APS criteria"},
                             SUPERVISOR)
    data = validate_success(resp)
    assert data["status"] == "SCREENED_OUT"
    assert data["screen_out_reason"] == "does not meet APS criteria"


def test_screen_out_creates_no_case(api):
    """PRD §3.2: "no case is created and the subject client is left entirely
    untouched — its status, counts, and every other attribute are unchanged."
    PRD §3.1: "a freshly filed report has ... its `case_id` null".

    Design: Difficulty/non_linear_state_machine/report_screen_out_branch_no_case
    """
    client = fx.new_client()
    report = fx.new_report(client["id"], reporter_type="ANONYMOUS",
                           allegation_types=["SELF_NEGLECT"], priority="ROUTINE", narrative="welfare check")
    resp = api.screen_report(report["id"],
                             {"decision": "SCREEN_OUT", "screen_out_reason": "does not meet APS criteria"},
                             SUPERVISOR)
    data = validate_success(resp)
    assert data["case_id"] is None, f"screen-out must not create a case; case_id={data['case_id']}"
    # No case exists for this report.
    _, meta = validate_paginated(api.list_cases(SUPERVISOR, params={"report_id": report["id"]}))
    assert meta["total_count"] == 0, "screen-out must open no case"
    # Client left untouched: still INTAKE, no case counted.
    client_after = fx.get_client(client["id"])
    assert client_after["status"] == "INTAKE"
    assert client_after["open_case_count"] == 0


def test_screen_already_screened_returns_invalid_state(api):
    """PRD §3.2: "Either path requires the report to be in `RECEIVED` status;
    screening a report in any other status is rejected with
    `ERR_REPORT_INVALID_STATE` (409)."

    Design: Corner/state_machines/screen_already_screened_returns_invalid_state
    """
    client = fx.new_client()
    report = fx.new_report(client["id"], reporter_type="ANONYMOUS",
                           allegation_types=["SELF_NEGLECT"], priority="ROUTINE", narrative="x")
    fx.screen_out(report["id"], "no jurisdiction")
    resp = api.screen_report(report["id"], {"decision": "SCREEN_IN"}, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE.value)


def test_immediate_case_visible_after_screen_in(api):
    """PRD §3.2: "The system opens a new **Case** in `OPEN` status, recording
    the originating report as the case's `report_id` ... The report's `case_id`
    is set to the new case's id."
    PRD §3.1: "the resulting case can be located by filtering cases on their
    originating report."

    Design: Corner/consistency_model/immediate_case_visible_after_screen_in
    """
    client = fx.new_client()
    report = fx.new_report(client["id"], allegation_types=["NEGLECT"], priority="PRIORITY", narrative="n")
    screened = fx.screen_in(report["id"])
    case_id = screened["case_id"]
    data, meta = validate_paginated(api.list_cases(SUPERVISOR, params={"report_id": report["id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == case_id
    assert data[0]["report_id"] == report["id"]
