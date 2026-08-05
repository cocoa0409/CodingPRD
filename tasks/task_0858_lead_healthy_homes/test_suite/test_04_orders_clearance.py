"""Hazard-control orders: clearance cycle, clearance cascade, dust-wipe limits, four-eyes.

Queue A: non_linear_state_machine, transitive_cascade.
Queue B: calculations, validations, rbac.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    build_remediation_scenario, make_contractor_headers, make_inspector_headers,
    create_clearance_test_payload, TEST_USERS,
)

CM = TEST_USERS["case_manager_headers"]
IC = TEST_USERS["intake_headers"]


# ─── non_linear_state_machine / order_clearance_pending_remediation_cycle ─
def test_clearance_fail_regresses_order_to_in_remediation(api):
    """PRD §3.5: "A `FAIL` sends the order back from `CLEARANCE_PENDING` to
    `IN_REMEDIATION` — the cyclic back edge — so that the contractor can re-work and
    request clearance again."
    PRD §3.5: "the result is `PASS` only when all three measurements are within their
    federal limits — the floor result at most 10, the sill result at most 100, and the
    trough result at most 400 micrograms per square foot — where a result exactly at a
    limit passes; otherwise the result is `FAIL`."

    Design: Difficulty/non_linear_state_machine/order_clearance_pending_remediation_cycle
    """
    ctx = build_remediation_scenario(stage="clearance_pending", num_hazards=1,
                                     second_inspector=True)
    ct = validate_success(api_client.create_clearance_test(
        create_clearance_test_payload(ctx["order_id"], floor_result_ug_ft2=50.0,
                                       sill_result_ug_ft2=40.0, trough_result_ug_ft2=100.0),
        make_inspector_headers(ctx["insp2_id"])), 201)
    assert ct["evaluated_result"] == "FAIL"
    order = validate_success(api_client.get_order(ctx["order_id"], CM), 200)
    assert order["status"] == "IN_REMEDIATION"


def test_rerequest_then_pass_completes_cycle_to_cleared(api):
    """PRD §3.5: "the assigned `Contractor` declares the order ready for clearance,
    moving it from `IN_REMEDIATION` to `CLEARANCE_PENDING`".
    PRD §3.5: "A `PASS` moves the order from `CLEARANCE_PENDING` to `CLEARED`".

    Design: Difficulty/non_linear_state_machine/order_clearance_pending_remediation_cycle
    """
    ctx = build_remediation_scenario(stage="clearance_pending", num_hazards=1,
                                     second_inspector=True)
    # FAIL back edge
    validate_success(api_client.create_clearance_test(
        create_clearance_test_payload(ctx["order_id"], floor_result_ug_ft2=50.0,
                                       sill_result_ug_ft2=40.0, trough_result_ug_ft2=100.0),
        make_inspector_headers(ctx["insp2_id"])), 201)
    # re-request returns to CLEARANCE_PENDING
    reordered = validate_success(
        api_client.request_clearance(ctx["order_id"], make_contractor_headers(ctx["con_id"])), 200)
    assert reordered["status"] == "CLEARANCE_PENDING"
    # PASS reaches CLEARED
    ct2 = validate_success(api_client.create_clearance_test(
        create_clearance_test_payload(ctx["order_id"], floor_result_ug_ft2=5.0,
                                       sill_result_ug_ft2=40.0, trough_result_ug_ft2=100.0),
        make_inspector_headers(ctx["insp2_id"])), 201)
    assert ct2["evaluated_result"] == "PASS"
    order = validate_success(api_client.get_order(ctx["order_id"], CM), 200)
    assert order["status"] == "CLEARED"


# ─── transitive_cascade / clearance_pass_depth2_order_hazards ──────────
def test_clearance_pass_clears_order_and_controls_hazards(api):
    """PRD §3.5: "A `PASS` moves the order from `CLEARANCE_PENDING` to `CLEARED` and
    triggers the clearance cascade: every `OPEN` hazard finding of the source
    investigation transitions to `CONTROLLED`, the case's `open_hazard_count` is
    decremented and its `controlled_hazard_count` incremented by the number
    reclassified, and its `total_hazard_count` is unchanged."

    Design: Difficulty/transitive_cascade/clearance_pass_depth2_order_hazards
    """
    ctx = build_remediation_scenario(stage="clearance_pending", num_hazards=2,
                                     second_inspector=True)
    ct = validate_success(api_client.create_clearance_test(
        create_clearance_test_payload(ctx["order_id"]),
        make_inspector_headers(ctx["insp2_id"])), 201)
    assert ct["evaluated_result"] == "PASS"
    order = validate_success(api_client.get_order(ctx["order_id"], CM), 200)
    assert order["status"] == "CLEARED"
    findings, _ = validate_paginated(
        api_client.list_investigation_hazard_findings(ctx["inv_id"], CM))
    assert findings and all(f["control_status"] == "CONTROLLED" for f in findings)


def test_clearance_pass_adjusts_case_counts_conserving_total(api):
    """PRD §3.5: "the case's `open_hazard_count` is decremented and its
    `controlled_hazard_count` incremented by the number reclassified, and its
    `total_hazard_count` is unchanged."

    Design: Difficulty/transitive_cascade/clearance_pass_depth2_order_hazards
    """
    ctx = build_remediation_scenario(stage="clearance_pending", num_hazards=2,
                                     second_inspector=True)
    validate_success(api_client.create_clearance_test(
        create_clearance_test_payload(ctx["order_id"]),
        make_inspector_headers(ctx["insp2_id"])), 201)
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["open_hazard_count"] == 0
    assert case["controlled_hazard_count"] == 2
    assert case["total_hazard_count"] == 2


# ─── Corner: calculations / clearance_boundary_floor_exactly_at_limit_passes ─
def test_clearance_all_measurements_exactly_at_limits_passes(api):
    """PRD §3.5: "the floor result at most 10, the sill result at most 100, and the
    trough result at most 400 micrograms per square foot — where a result exactly at a
    limit passes; otherwise the result is `FAIL`."

    Design: Corner/calculations/clearance_boundary_floor_exactly_at_limit_passes
    """
    ctx = build_remediation_scenario(stage="clearance_pending", num_hazards=1,
                                     second_inspector=True)
    ct = validate_success(api_client.create_clearance_test(
        create_clearance_test_payload(ctx["order_id"], floor_result_ug_ft2=10.0,
                                       sill_result_ug_ft2=100.0, trough_result_ug_ft2=400.0),
        make_inspector_headers(ctx["insp2_id"])), 201)
    assert ct["evaluated_result"] == "PASS"
    order = validate_success(api_client.get_order(ctx["order_id"], CM), 200)
    assert order["status"] == "CLEARED"


# ─── Corner: validations / clearance_by_same_investigation_inspector_rejected ─
def test_clearance_by_source_investigation_inspector_rejected(api):
    """PRD §3.5: "The signing inspector's `X-User-ID` is captured as
    `cleared_by_inspector_id`, and the four-eyes rule applies: if it equals the source
    investigation's `inspector_id`, the test is rejected with `ERR_SOD_CONFLICT`
    (HTTP 409)."

    Design: Corner/validations/clearance_by_same_investigation_inspector_rejected
    """
    ctx = build_remediation_scenario(stage="clearance_pending", num_hazards=1)
    res = api_client.create_clearance_test(
        create_clearance_test_payload(ctx["order_id"]),
        make_inspector_headers(ctx["insp_id"]))  # same inspector who investigated
    validate_error(res, "ERR_SOD_CONFLICT")


# ─── Corner: rbac / contractor_cannot_record_clearance_test ────────────
def test_contractor_cannot_record_clearance_test(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/contractor_cannot_record_clearance_test
    """
    res = api_client.create_clearance_test(
        create_clearance_test_payload("00000000-0000-4000-8000-000000000009"),
        TEST_USERS["contractor_headers"])
    validate_error(res, "ERR_UNAUTHORIZED")
