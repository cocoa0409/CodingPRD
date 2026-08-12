"""Transitive cascades: no-access escalation chain and audit-fail suspension
(PRD 3.4, 3.7)."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, get_success_data, record_for_cause_fail,
    setup_no_access_case, setup_program_wave_contractor,
    setup_work_order_qa_review, submit_rework, validate_paginated,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


def test_third_strike_opens_case(api):
    """PRD §3.4: "The third strike is the escalation boundary: once
    `no_access_strikes` reaches at least three and no `OPEN` no-access case
    exists for the work order, the system opens a `NoAccessCase` in `OPEN`
    status at stage `STAGE_1_DOOR_HANGER`, recording `strikes_at_open` equal
    to the strike count"

    Design: Difficulty/transitive_cascade/no_access_strike_escalation_cascade
    """
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 3})
    ctx = setup_no_access_case(contr["id"])
    wo = ctx["work_order"]
    assert wo["lifecycle_status"] == "ACCESS_FAILED"
    assert wo["no_access_strikes"] == 3
    case = ctx["case"]
    assert case["status"] == "OPEN"
    assert case["stage"] == "STAGE_1_DOOR_HANGER"
    assert case["strikes_at_open"] == 3
    assert case["work_order_id"] == wo["id"]
    # Exactly one OPEN case per work order
    cases, meta = validate_paginated(api_client.list_no_access_cases(
        SCHED, params={"work_order_id": wo["id"], "status": "OPEN"}))
    assert meta["total_count"] == 1


def test_case_creation_auto_sends_door_hanger(api):
    """PRD §3.4: "once `no_access_strikes` reaches at least three and no
    `OPEN` no-access case exists for the work order, the system opens a
    `NoAccessCase` in `OPEN` status at stage `STAGE_1_DOOR_HANGER`, recording
    `strikes_at_open` equal to the strike count, and immediately auto-creates
    the stage-one customer notification — `channel` `DOOR_HANGER`, status
    `SENT`, linked back to the case through `no_access_case_id`."

    Design: Difficulty/transitive_cascade/no_access_strike_escalation_cascade
    """
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 3})
    ctx = setup_no_access_case(contr["id"])
    case = ctx["case"]
    notifs, meta = validate_paginated(api_client.list_notifications(
        SCHED, params={"no_access_case_id": case["id"]}))
    assert meta["total_count"] == 1
    assert notifs[0]["channel"] == "DOOR_HANGER"
    assert notifs[0]["status"] == "SENT"
    assert notifs[0]["work_order_id"] == ctx["work_order"]["id"]


def test_third_fail_auto_suspends_contractor(api):
    """PRD §3.7: "Either verdict stamps `recorded_at` from the logical clock
    and triggers a recomputation of the contractor's quality score: over the
    contractor's latest twenty recorded audits, ordered by `recorded_at`
    descending with ties broken by `created_at` ascending, the score
    `quality_score_bp` is 10,000 basis points minus 400 basis points for each
    `FAIL` in that window, floored at zero — so a passing record can raise the
    score by evicting an old failure from the window — while
    `audits_failed_count` counts every recorded `FAIL` audit of the contractor
    without any window. A recorded `FAIL` also cascades: the work order moves
    `QA_REVIEW` → `QA_FAILED`, and if the recomputed score has dropped below
    9,200 basis points while the contractor is `ACTIVE`, the contractor is
    auto-suspended to `SUSPENDED`"

    Design: Difficulty/transitive_cascade/audit_fail_suspension_cascade
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_qa_review(contr["id"])
    record_for_cause_fail(ctx["work_order"]["id"], contr["id"])  # 9600
    submit_rework(ctx["work_order"]["id"], contr["id"])
    record_for_cause_fail(ctx["work_order"]["id"], contr["id"])  # 9200, still ACTIVE
    c = get_success_data(api_client.get_contractor(contr["id"], PM))
    assert c["quality_score_bp"] == 9200
    assert c["status"] == "ACTIVE"
    submit_rework(ctx["work_order"]["id"], contr["id"])
    record_for_cause_fail(ctx["work_order"]["id"], contr["id"])  # 8800 < 9200
    c = get_success_data(api_client.get_contractor(contr["id"], PM))
    assert c["quality_score_bp"] == 8800
    assert c["status"] == "SUSPENDED"
    assert c["audits_failed_count"] == 3


def test_fail_cascade_flips_work_order_to_qa_failed(api):
    """PRD §3.7: "A recorded `FAIL` also cascades: the work order moves
    `QA_REVIEW` → `QA_FAILED`"

    Design: Difficulty/transitive_cascade/audit_fail_suspension_cascade
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_qa_review(contr["id"])
    record_for_cause_fail(ctx["work_order"]["id"], contr["id"],
                          checks_total=12, checks_passed=11, defects_found=1)
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["lifecycle_status"] == "QA_FAILED"
