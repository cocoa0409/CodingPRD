"""Complaint screening, investigation open/adjudicate/reopen, segregation of duties, and the
sanction cap.

Queue A: non_linear_state_machine (investigation reopen cycle), cross_entity_state_dependency
(open requires screened complaint). Queue B: screen-dismiss branch, final_sanction cap, SoD.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_investigator_headers, make_adjudicator_headers, TEST_USERS,
    register_jurisdiction, register_filer,
    setup_filed_complaint, setup_screened_complaint, setup_open_investigation,
    api_client, create_complaint_payload,
)


def _adjudicate_not_sustained(api, ctx):
    return get_success_data(api.adjudicate_investigation(
        ctx["investigation"]["id"], {"decision": "NOT_SUSTAINED", "findings": "no violation"},
        make_adjudicator_headers("adj-1")))


def test_reopen_not_sustained_investigation_back_to_open(api):
    """PRD 3.8: "Reopening requires the investigation to be `NOT_SUSTAINED`, moves it
    `NOT_SUSTAINED → OPEN`".

    Design: Difficulty/non_linear_state_machine/investigation_reopen_cycle
    """
    ctx = setup_open_investigation(investigator_id="inv-1")
    _adjudicate_not_sustained(api, ctx)
    res = api.reopen_investigation(
        ctx["investigation"]["id"], {"reopen_reason": "new evidence"},
        TEST_USERS["ethics_officer_headers"])
    inv = validate_success(res, 200)
    assert inv["status"] == "OPEN"


def test_reopen_restores_complaint_to_screened(api, ethics_officer_headers, registrar_headers):
    """PRD 3.8: "and transitions the parent complaint `DISMISSED → SCREENED` to re-open the
    matter — the cyclic shape `OPEN → NOT_SUSTAINED → OPEN`."

    Design: Difficulty/non_linear_state_machine/investigation_reopen_cycle
    """
    ctx = setup_open_investigation(investigator_id="inv-1")
    _adjudicate_not_sustained(api, ctx)
    api.reopen_investigation(ctx["investigation"]["id"], {"reopen_reason": "new evidence"},
                             ethics_officer_headers)
    complaint = validate_success(api.get_complaint(ctx["complaint"]["id"], registrar_headers), 200)
    assert complaint["status"] == "SCREENED"


def test_open_investigation_on_filed_complaint_rejected(api):
    """PRD 3.8: "An `Investigator` opens an **investigation** on a screened complaint".
    PRD 2.11: "that the target is in a state from which the requested transition is defined,
    yielding `ERR_INVALID_STATE`".

    Design: Difficulty/cross_entity_state_dependency/investigation_open_requires_complaint_screened
    """
    ctx = setup_filed_complaint()
    res = api.open_investigation(
        ctx["complaint"]["id"], {"scope_note": "premature"}, make_investigator_headers("inv-1"))
    validate_error(res, "ERR_INVALID_STATE")


def test_open_investigation_on_filed_complaint_creates_nothing(api, investigator_headers, registrar_headers):
    """PRD 3.8: "An `Investigator` opens an **investigation** on a screened complaint".
    PRD 3.8: "a `decision` directing screening moves the complaint `FILED → SCREENED` and makes
    it eligible for investigation".

    Design: Difficulty/cross_entity_state_dependency/investigation_open_requires_complaint_screened
    """
    ctx = setup_filed_complaint()
    api.open_investigation(ctx["complaint"]["id"], {}, investigator_headers)
    data, meta = validate_paginated(
        api.list_investigations(registrar_headers, params={"complaint_id": ctx["complaint"]["id"]}))
    assert meta["total_count"] == 0


def test_screen_dismiss_moves_to_dismissed(api, ethics_officer_headers):
    """PRD 3.8: "while a `decision` directing dismissal moves it `FILED → DISMISSED`."

    Design: Corner/state_machines/screen_dismiss_branch_terminal
    """
    ctx = setup_filed_complaint()
    res = api.screen_complaint(
        ctx["complaint"]["id"], {"decision": "DISMISSED", "screen_note": "no merit"},
        ethics_officer_headers)
    complaint = validate_success(res, 200)
    assert complaint["status"] == "DISMISSED"


def test_final_sanction_capped(api, registrar_headers):
    """PRD 3.8: "On sustaining, the system sets `final_sanction_cents` to the lesser of the
    jurisdiction's `penalty_cap_cents` and the `recommended_sanction_cents`".

    Design: Corner/calculations/final_sanction_capped_at_penalty_cap
    """
    ctx = setup_open_investigation(investigator_id="inv-1", jur_overrides={"penalty_cap_cents": 50000})
    res = api.adjudicate_investigation(
        ctx["investigation"]["id"], {"decision": "SUSTAINED", "recommended_sanction_cents": 999999},
        make_adjudicator_headers("adj-1"))
    inv = validate_success(res, 200)
    assert inv["final_sanction_cents"] == 50000
    filer = validate_success(api.get_filer(ctx["filer"]["id"], registrar_headers), 200)
    assert filer["outstanding_penalty_cents"] == 50000


def test_sod_adjudicator_equals_investigator(api):
    """PRD 3.8: "the acting `X-User-ID` to differ from the investigation's
    `assigned_investigator_id`; an adjudicator who is also the assigned investigator is rejected
    with `ERR_SOD_CONFLICT` (HTTP 409)."

    Design: Corner/rbac/sod_adjudicator_equals_investigator_rejected
    """
    ctx = setup_open_investigation(investigator_id="inv-1", jur_overrides={"penalty_cap_cents": 50000})
    assigned = ctx["investigation"]["assigned_investigator_id"]
    res = api.adjudicate_investigation(
        ctx["investigation"]["id"], {"decision": "SUSTAINED", "recommended_sanction_cents": 10000},
        make_adjudicator_headers(assigned))
    validate_error(res, "ERR_SOD_CONFLICT")
