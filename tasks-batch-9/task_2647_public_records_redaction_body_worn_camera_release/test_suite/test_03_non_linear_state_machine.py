"""Lifecycles that are not a single line: two independent request dimensions, and a
redaction task that revisits QA_PENDING as often as the reviewer sends it back."""

from test_helpers.assertions import assert_fields, assert_list_response
from test_helpers.fixtures import (
    adjudicate,
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_record,
    get_request,
    get_staff,
    get_task,
    open_task,
    post_payment,
    record_verdict,
    rule_inclusion,
    set_clock,
    submit_for_qa,
)
from test_helpers.test_users import SUPERVISOR_HEADERS


def _two_dimension_scenario(api):
    """A fresh INTAKE request over a 40-minute USE_OF_FORCE recording, plus two attorneys."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Ray Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0305",
        device_serial="AXON-0305",
        officer_badge="B-7713",
        recorded_start_at="2026-07-28T22:00:00Z",
        duration_ms=2400000,
        classification="USE_OF_FORCE",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-28T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0305",
        requested_date_from="2026-07-28T00:00:00Z",
        requested_date_to="2026-07-29T00:00:00Z",
        scope_narrative="All BWC video for incident INC-2026-0305",
    )
    return {
        "request_id": request["id"],
        "request": request,
        "asset_id": asset["id"],
        "requester_id": requester["id"],
        "counsel_a_id": counsel_a["id"],
        "counsel_b_id": counsel_b["id"],
    }


def _advance_processing_to_exemption_review(api, scenario):
    """Clarify scope and rule the single recording responsive."""
    clarify_scope(
        api,
        scenario["request_id"],
        scope_narrative="Use-of-force segment only",
        requested_date_from="2026-07-28T00:00:00Z",
        requested_date_to="2026-07-28T23:59:59Z",
    )
    record = attach_record(api, scenario["request_id"], scenario["asset_id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return record["id"]


def test_processing_dimension_advances_while_the_fee_dimension_stands_still(api):
    """Scoping and inclusion move processing_status only; fee_status stays NOT_ASSESSED.

    PRD: "Neither dimension constrains the other except at two pinned junctions, both described in §3.8: a request that has reached `RELEASED` advances to `CLOSED` once its fee dimension reaches `SETTLED` or `WAIVED`, and a reversal that undoes a settled charge drops the fee dimension from `SETTLED` back to `INVOICED` without touching `processing_status` at all."

    Design: Difficulty/non_linear_state_machine/request_parallel_dimensions_evolve_independently
    """
    scenario = _two_dimension_scenario(api)
    assert_fields(
        scenario["request"],
        processing_status="INTAKE",
        fee_status="NOT_ASSESSED",
        statutory_deadline_at="2026-08-21T00:00:00Z",
        tolled_days=0,
    )

    clarify_scope(
        api,
        scenario["request_id"],
        scope_narrative="Use-of-force segment only",
        requested_date_from="2026-07-28T00:00:00Z",
        requested_date_to="2026-07-28T23:59:59Z",
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="SCOPING",
        fee_status="NOT_ASSESSED",
        scope_clarification_count=1,
    )

    record = attach_record(api, scenario["request_id"], scenario["asset_id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")

    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="EXEMPTION_REVIEW",
        fee_status="NOT_ASSESSED",
    )


def test_fee_dimension_advances_while_processing_status_stands_still(api):
    """Estimating and then paying the deposit never touches processing_status.

    PRD: "When `fee_status` is `DEPOSIT_DUE` and `deposit_balance_cents` after the payment has reached `deposit_required_cents`, the request moves `DEPOSIT_DUE → DEPOSIT_PAID`; on that specific edge, and only on it, `tolled_days` is frozen and `statutory_deadline_at` is re-struck as described in §3.3."

    Design: Difficulty/non_linear_state_machine/request_parallel_dimensions_evolve_independently
    """
    scenario = _two_dimension_scenario(api)
    record_id = _advance_processing_to_exemption_review(api, scenario)
    assert_claim(api, record_id, scenario["counsel_a_id"], "MEDICAL", "PARTIAL_REDACT")

    create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "USB")
    after_estimate = get_request(api, scenario["request_id"])
    assert_fields(
        after_estimate,
        fee_status="DEPOSIT_DUE",
        estimated_total_cents=5000,
        deposit_required_cents=2500,
        deposit_due_at="2026-08-31T00:00:00Z",
        processing_status="EXEMPTION_REVIEW",
    )

    set_clock(api, "2026-09-05T00:00:00Z")
    post_payment(api, scenario["request_id"], scenario["requester_id"], 2500)

    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="DEPOSIT_PAID",
        deposit_paid_cents=2500,
        deposit_balance_cents=2500,
        tolled_days=5,
        statutory_deadline_at="2026-08-26T00:00:00Z",
        processing_status="EXEMPTION_REVIEW",
    )


def test_adjudication_moves_processing_only_and_leaves_the_paid_deposit_alone(api):
    """The sustain cascade advances processing to REDACTION with fee_status still DEPOSIT_PAID.

    PRD: "If no claim on the request remains `ASSERTED` and at least one `RESPONSIVE` record still has `release_posture` `RESTRICTED`, the request advances `EXEMPTION_REVIEW → REDACTION`, because targeted obscuration is now owed."

    Design: Difficulty/non_linear_state_machine/request_parallel_dimensions_evolve_independently
    """
    scenario = _two_dimension_scenario(api)
    record_id = _advance_processing_to_exemption_review(api, scenario)
    claim = assert_claim(api, record_id, scenario["counsel_a_id"], "MEDICAL", "PARTIAL_REDACT")
    create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "USB")
    set_clock(api, "2026-09-05T00:00:00Z")
    deposit_entry = post_payment(
        api, scenario["request_id"], scenario["requester_id"], 2500
    )
    assert_fields(
        deposit_entry, entry_type="DEPOSIT_PAYMENT", amount_cents=2500, source_kind="DEPOSIT"
    )

    adjudicate(api, claim["id"], scenario["counsel_b_id"], "SUSTAINED")

    # The request's estimated_total_cents mirror is not asserted here: PRD 3.8
    # says the mirror is "0 whenever no `ACTIVE` estimate exists", and the sustain
    # has just driven this request's only estimate to STALE.
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="REDACTION",
        fee_status="DEPOSIT_PAID",
    )
    assert get_record(api, record_id)["release_posture"] == "RESTRICTED"
    rows, _meta = assert_list_response(
        api.list_fee_estimates(scenario["request_id"], SUPERVISOR_HEADERS)
    )
    assert [row["status"] for row in rows] == ["STALE"]


def _draft_face_task(api):
    """A DRAFT face task over the first minute of a ten-minute unclaimed recording."""
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0306",
        device_serial="AXON-0306",
        officer_badge="B-7714",
        recorded_start_at="2026-07-29T10:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-29T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0306",
        requested_date_from="2026-07-29T00:00:00Z",
        requested_date_to="2026-07-30T00:00:00Z",
        scope_narrative="Lobby camera BWC video",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Lobby camera, first ten minutes",
        requested_date_from="2026-07-29T00:00:00Z",
        requested_date_to="2026-07-29T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 60000)
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "task_id": task["id"],
        "tech_id": tech["id"],
        "reviewer_id": reviewer["id"],
    }


def test_rejected_task_returns_to_qa_pending_with_the_rework_counter_raised(api):
    """The task revisits QA_PENDING on resubmission and rework_count becomes 1.

    PRD: "A successful submission moves the task `DRAFT → QA_PENDING`, or `QA_REJECTED → QA_PENDING` when the work is being resubmitted after a failure, in which case `rework_count` also increases by 1."

    Design: Difficulty/non_linear_state_machine/redaction_task_qa_rework_cycle_repeats_qa_pending
    """
    scenario = _draft_face_task(api)

    first = submit_for_qa(
        api,
        scenario["task_id"],
        scenario["tech_id"],
        scenario["reviewer_id"],
        9,
        "2026-08-01T09:00:00Z",
        "2026-08-01T10:00:00Z",
    )
    assert_fields(first, status="QA_PENDING", rework_count=0, logged_labor_minutes=9)
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1

    rejected = record_verdict(
        api,
        scenario["task_id"],
        scenario["reviewer_id"],
        "FAIL",
        ["FACE_MISSED", "EDGE_BLEED"],
    )
    assert_fields(rejected, status="QA_REJECTED", approved_labor_minutes=0)
    assert rejected["defect_codes"] == ["FACE_MISSED", "EDGE_BLEED"]
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0

    resubmitted = submit_for_qa(
        api,
        scenario["task_id"],
        scenario["tech_id"],
        scenario["reviewer_id"],
        4,
        "2026-08-01T11:00:00Z",
        "2026-08-01T12:00:00Z",
    )
    assert_fields(resubmitted, status="QA_PENDING", rework_count=1, logged_labor_minutes=4)
    assert resubmitted["logged_labor_minutes"] != 13


def test_rework_cycle_leaves_billable_minutes_at_the_final_approved_figure(api):
    """A failure banks nothing and the eventual pass banks only the resubmitted minutes.

    PRD: "A failure moves the task `QA_PENDING → QA_REJECTED`, stores the supplied `defect_codes`, and leaves `approved_labor_minutes` at 0 — which is why a submission followed by a failure leaves the request's `billable_labor_minutes` exactly where it started."

    Design: Difficulty/non_linear_state_machine/redaction_task_qa_rework_cycle_repeats_qa_pending
    """
    scenario = _draft_face_task(api)
    submit_for_qa(
        api,
        scenario["task_id"],
        scenario["tech_id"],
        scenario["reviewer_id"],
        9,
        "2026-08-01T09:00:00Z",
        "2026-08-01T10:00:00Z",
    )
    record_verdict(
        api,
        scenario["task_id"],
        scenario["reviewer_id"],
        "FAIL",
        ["FACE_MISSED", "EDGE_BLEED"],
    )
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 0

    submit_for_qa(
        api,
        scenario["task_id"],
        scenario["tech_id"],
        scenario["reviewer_id"],
        4,
        "2026-08-01T11:00:00Z",
        "2026-08-01T12:00:00Z",
    )
    approved = record_verdict(api, scenario["task_id"], scenario["reviewer_id"], "PASS")

    assert_fields(approved, status="APPROVED", approved_labor_minutes=4)
    assert approved["defect_codes"] == []
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0
    assert get_task(api, scenario["task_id"])["approved_labor_minutes"] == 4
    assert get_record(api, scenario["record_id"])["approved_labor_minutes"] == 4
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 4
