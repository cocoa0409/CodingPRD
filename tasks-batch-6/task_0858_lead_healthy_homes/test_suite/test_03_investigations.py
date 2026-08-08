"""Environmental investigations: scheduling gates, inspector calendar, completion boundary.

Queue A: resource_temporal_overlap, boundary_precision_check, cross_entity_state_dependency.
Queue B: state_machines, validations.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    build_remediation_scenario, setup_case, create_inspector, schedule_investigation,
    make_inspector_headers, create_finding_payload, create_investigation_payload, TEST_USERS,
)

CM = TEST_USERS["case_manager_headers"]
IC = TEST_USERS["intake_headers"]


# ─── resource_temporal_overlap / inspector_halfopen_window_overlap ─────
def test_overlapping_inspector_window_rejected(api):
    """PRD §3.4: "the request is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED` (HTTP 409)
    if the assigned inspector already has another investigation in `SCHEDULED` or
    `IN_PROGRESS` whose window overlaps this one."

    Design: Difficulty/resource_temporal_overlap/inspector_halfopen_window_overlap
    """
    ctx = build_remediation_scenario(stage="investigation", income_tier="LOW")
    res = api_client.create_investigation(
        create_investigation_payload(ctx["case_id"], ctx["d_id"], ctx["insp_id"],
                                      scheduled_start="2026-05-05T11:00:00Z",
                                      scheduled_end="2026-05-05T13:00:00Z"), CM)
    validate_error(res, "ERR_INSPECTOR_DOUBLE_BOOKED")


def test_adjacent_inspector_window_accepted(api):
    """PRD §3.4: "The windows are treated as half-open intervals from `scheduled_start`
    up to but not including `scheduled_end`, so two windows that merely touch at an
    endpoint do not overlap."

    Design: Difficulty/resource_temporal_overlap/inspector_halfopen_window_overlap
    """
    ctx = build_remediation_scenario(stage="investigation", income_tier="LOW")
    inv = validate_success(api_client.create_investigation(
        create_investigation_payload(ctx["case_id"], ctx["d_id"], ctx["insp_id"],
                                      scheduled_start="2026-05-05T12:00:00Z",
                                      scheduled_end="2026-05-05T14:00:00Z"), CM), 201)
    assert inv["status"] == "SCHEDULED"


# ─── boundary_precision_check / empty_hazard_set_completes_without_order ─
def test_empty_completion_issues_no_order_case_stays_investigation(api):
    """PRD §3.4: "If instead the investigation recorded zero findings, no order is
    issued; the case advances from `INVESTIGATION` to `CLOSED` only if its
    `medical_status` is already `RESOLVED`, and otherwise it remains `INVESTIGATION`
    with no order."

    Design: Difficulty/boundary_precision_check/empty_hazard_set_completes_without_order
    """
    ctx = build_remediation_scenario(stage="investigation", income_tier="LOW")
    inv = validate_success(
        api_client.complete_investigation(ctx["inv_id"], make_inspector_headers(ctx["insp_id"])), 200)
    assert inv["status"] == "COMPLETED"
    assert inv["hazard_finding_count"] == 0
    data, meta = validate_paginated(api_client.list_orders(CM, params={"case_id": ctx["case_id"]}))
    assert meta["total_count"] == 0 and len(data) == 0
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["case_status"] == "INVESTIGATION"


def test_nonempty_completion_issues_order_and_enforcement(api):
    """PRD §3.4: "If the completed investigation recorded at least one hazard —
    `hazard_finding_count` of one or more — the system issues a `HazardControlOrder`
    in `ISSUED`, snapshots its `hazard_count` from the investigation's finding count,
    and advances the case's `case_status` from `INVESTIGATION` to `ENFORCEMENT`."

    Design: Difficulty/boundary_precision_check/empty_hazard_set_completes_without_order
    """
    ctx = build_remediation_scenario(stage="order", income_tier="LOW", num_hazards=2)
    data, meta = validate_paginated(api_client.list_orders(CM, params={"case_id": ctx["case_id"]}))
    assert meta["total_count"] == 1
    assert data[0]["status"] == "ISSUED"
    assert data[0]["hazard_count"] == 2
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["case_status"] == "ENFORCEMENT"


# ─── cross_entity_state_dependency / investigation_create_requires_case_open_or_investigation ─
def test_investigation_rejected_when_case_in_enforcement(api):
    """PRD §3.4: "Scheduling is permitted only when the case's `case_status` is `OPEN`
    or `INVESTIGATION`; the first investigation scheduled for an `OPEN` case advances
    its `case_status` to `INVESTIGATION`."
    PRD §2.8: "the target is in a state from which the requested transition is defined,
    else `ERR_INVALID_STATE` (409)."

    Design: Difficulty/cross_entity_state_dependency/investigation_create_requires_case_open_or_investigation
    """
    ctx = build_remediation_scenario(stage="order", income_tier="LOW", num_hazards=1)
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["case_status"] == "ENFORCEMENT"
    res = api_client.create_investigation(
        create_investigation_payload(ctx["case_id"], ctx["d_id"], ctx["insp_id"],
                                      scheduled_start="2026-05-20T09:00:00Z",
                                      scheduled_end="2026-05-20T12:00:00Z"), CM)
    validate_error(res, "ERR_INVALID_STATE")


def test_first_investigation_on_open_case_advances_to_investigation(api):
    """PRD §3.4: "Scheduling is permitted only when the case's `case_status` is `OPEN`
    or `INVESTIGATION`; the first investigation scheduled for an `OPEN` case advances
    its `case_status` to `INVESTIGATION`."

    Design: Difficulty/cross_entity_state_dependency/investigation_create_requires_case_open_or_investigation
    """
    ctx = setup_case(income_tier="LOW", bll=22.0)
    insp = create_inspector()
    inv = validate_success(api_client.create_investigation(
        create_investigation_payload(ctx["case_id"], ctx["d_id"], insp["id"]), CM), 201)
    assert inv["status"] == "SCHEDULED"
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["case_status"] == "INVESTIGATION"


# ─── Corner: state_machines / complete_already_completed_investigation_rejected ─
def test_complete_already_completed_investigation_rejected(api):
    """PRD §2.8: "the target is in a state from which the requested transition is
    defined, else `ERR_INVALID_STATE` (409)."
    PRD §3.4: "Completion is allowed from either `SCHEDULED` or `IN_PROGRESS`".

    Design: Corner/state_machines/complete_already_completed_investigation_rejected
    """
    ctx = build_remediation_scenario(stage="order", income_tier="LOW", num_hazards=1)
    res = api_client.complete_investigation(ctx["inv_id"], make_inspector_headers(ctx["insp_id"]))
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: validations / inspector_cannot_add_findings_to_others_investigation ─
def test_inspector_cannot_add_findings_to_others_investigation(api):
    """PRD §2.1: "recording findings on and completing an investigation both require
    the acting inspector's `X-User-ID` to equal the investigation's `inspector_id`".
    PRD §2.1: "In both cases an ownership mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/inspector_cannot_add_findings_to_others_investigation
    """
    ctx = setup_case(income_tier="LOW", bll=22.0)
    insp_a = create_inspector(full_name="Insp A", certification_id_number="RA-001")
    insp_b = create_inspector(full_name="Insp B", certification_id_number="RA-002")
    inv = schedule_investigation(ctx["case_id"], ctx["d_id"], insp_a["id"])
    res = api_client.create_finding(inv["id"], create_finding_payload(),
                                    make_inspector_headers(insp_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
