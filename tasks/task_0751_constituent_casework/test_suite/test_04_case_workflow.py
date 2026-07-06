"""Case lifecycle: the AWAITING_CONSTITUENT cycle, invalid transitions, terminal-state
lockdown, template mismatch at triage, and purged-constituent intake refusal."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_representative, new_constituent, new_template, new_case, triage,
    triaged_case,
    TEST_USERS,
)

ADMIN = TEST_USERS["office_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# --- Difficulty: non_linear_state_machine / case_await_constituent_cycle ---

def test_case_returns_to_in_progress_after_reply(api):
    """PRD §3.4: "The constituent supplies the requested information with their own
    optional `message`, which moves the case from `AWAITING_CONSTITUENT` back to
    `IN_PROGRESS`".

    Design: Difficulty/non_linear_state_machine/case_await_constituent_cycle
    """
    s = triaged_case(api, category="HEALTHCARE", priority="NORMAL", window=100)
    validate_success(api.request_info(s["case_id"], {"message": "please send docs"}, CASEWORKER))
    data = validate_success(api.constituent_reply(s["case_id"], {"message": "here they are"}, s["con_headers"]))
    assert data["status"] == "IN_PROGRESS", f"expected IN_PROGRESS, got {data['status']}"


def test_case_reenters_awaiting_constituent_loop(api):
    """PRD §3.4: "This `IN_PROGRESS ↔ AWAITING_CONSTITUENT` loop may repeat any number
    of times, each hop adding to the accumulated pause total."

    Design: Difficulty/non_linear_state_machine/case_await_constituent_cycle
    """
    s = triaged_case(api, category="HEALTHCARE", priority="NORMAL", window=100)
    validate_success(api.request_info(s["case_id"], {"message": "first"}, CASEWORKER))
    validate_success(api.constituent_reply(s["case_id"], {"message": "reply"}, s["con_headers"]))
    data = validate_success(api.request_info(s["case_id"], {"message": "one more thing"}, CASEWORKER))
    assert data["status"] == "AWAITING_CONSTITUENT", \
        f"re-entry into AWAITING_CONSTITUENT expected, got {data['status']}"


# --- Corner: state_machines / close_case_from_new_rejected ---

def test_close_case_from_new_rejected(api):
    """PRD §3.6: "Closing is an `OfficeAdmin`-only finalization, valid only from
    `RESOLVED`, that moves the case to `CLOSED` and stamps `closed_at`."

    Design: Corner/state_machines/close_case_from_new_rejected
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    case = new_case(api, con["id"], category="OTHER")
    resp = api.close_case(case["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


# --- Corner: state_machines / withdraw_closed_case_rejected ---

def test_withdraw_closed_case_rejected(api):
    """PRD §3.6: "`RESOLVED` and `CLOSED` are terminal outcomes that cannot be
    withdrawn; `WITHDRAWN` and `CLOSED` are the two terminal states of a case."

    Design: Corner/state_machines/withdraw_closed_case_rejected
    """
    s = triaged_case(api, category="OTHER", priority="NORMAL", window=100)
    validate_success(api.respond_case(s["case_id"], {}, CASEWORKER))
    validate_success(api.close_case(s["case_id"], ADMIN))
    resp = api.withdraw_case(s["case_id"], {}, s["con_headers"])
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


# --- Corner: validations / template_mismatch_on_triage_rejected ---

def test_template_mismatch_on_triage_rejected(api):
    """PRD §3.3: "The referenced template must exist, be active, and have a `category`
    equal to the case's own category; if the template is inactive or its category
    does not match, the request is rejected with `ERR_TEMPLATE_MISMATCH`."

    Design: Corner/validations/template_mismatch_on_triage_rejected
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "HEALTHCARE", response_window_hours=100)
    case = new_case(api, con["id"], category="HOUSING")
    resp = api.triage_case(
        case["id"], {"template_id": tmpl["id"], "priority": "NORMAL", "assignee_staff_id": "s1"}, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_MISMATCH)
    still = validate_success(api.get_case(case["id"], CASEWORKER))
    assert still["status"] == "NEW", "case must remain NEW after a rejected triage"


# --- Corner: validations / purged_constituent_new_case_rejected ---

def test_purged_constituent_new_case_rejected(api):
    """PRD §3.3: "Intake refuses a `PURGED` constituent with `ERR_CONSTITUENT_PURGED`."

    Design: Corner/validations/purged_constituent_new_case_rejected
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    validate_success(api.purge_constituent(con["id"], ADMIN))
    resp = api.create_case(
        {"constituent_id": con["id"], "subject": "S", "description": "d", "category": "OTHER"}, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_CONSTITUENT_PURGED)
