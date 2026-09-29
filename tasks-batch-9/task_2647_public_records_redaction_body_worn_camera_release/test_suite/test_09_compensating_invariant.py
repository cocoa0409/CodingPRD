"""Quantities that must return to their exact prior value when work is undone.

The ledger's conservation identity survives a reversal of a settled payment, and a
request's billable minutes survive a rejected quality review.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_ENTRY_ALREADY_REVERSED
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_ledger_conservation,
    assert_total_count,
)
from test_helpers.factories import reversal_payload
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
    issue_invoice,
    open_task,
    post_payment,
    produce_release,
    record_verdict,
    rule_inclusion,
    submit_for_qa,
)
from test_helpers.test_users import SUPERVISOR_HEADERS


def _invoiced_released_request(api):
    """A released request carrying a 596-cent invoice and nothing paid against it."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Ray Counsel", "COUNSEL", 3)
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0519",
        device_serial="AXON-0519",
        officer_badge="B-1111",
        recorded_start_at="2026-07-20T07:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-20T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0519",
        requested_date_from="2026-07-20T00:00:00Z",
        requested_date_to="2026-07-21T00:00:00Z",
        scope_narrative="BWC video for INC-2026-0519",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Plates only",
        requested_date_from="2026-07-20T00:00:00Z",
        requested_date_to="2026-07-20T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    create_estimate(api, request["id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")
    claim = assert_claim(
        api, record["id"], counsel_a["id"], "MEDICAL", "PARTIAL_REDACT",
        statutory_citation="456.057(7)",
    )
    adjudicate(api, claim["id"], counsel_b["id"], "SUSTAINED")

    task1 = open_task(api, record["id"], tech["id"], "LICENSE_PLATE", 0, 10000, claim["id"])
    submit_for_qa(
        api, task1["id"], tech["id"], reviewer["id"], 5,
        "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
    )
    record_verdict(api, task1["id"], reviewer["id"], "PASS")
    task2 = open_task(api, record["id"], tech["id"], "LICENSE_PLATE", 10000, 20000, claim["id"])
    submit_for_qa(
        api, task2["id"], tech["id"], reviewer["id"], 5,
        "2026-08-01T15:00:00Z", "2026-08-01T16:00:00Z",
    )
    record_verdict(api, task2["id"], reviewer["id"], "PASS")
    produce_release(api, request["id"], "DIGITAL_DOWNLOAD")
    issue_invoice(api, request["id"], memo="Final invoice for INC-2026-0519")
    return {"request_id": request["id"], "requester_id": requester["id"]}


def test_payment_in_full_settles_the_fee_and_closes_the_request(api):
    """The 596-cent payment posts one positive DEPOSIT_PAYMENT line and squares the account.

    PRD: "A successful payment appends a ledger line with `entry_type` `DEPOSIT_PAYMENT` and `source_kind` `DEPOSIT` carrying the positive amount, then re-derives `deposit_paid_cents` and `deposit_balance_cents`."

    Design: Difficulty/compensating_invariant/payment_reversal_conserves_ledger_balance_identity
    """
    scenario = _invoiced_released_request(api)

    entry = post_payment(api, scenario["request_id"], scenario["requester_id"], 596)

    assert_fields(
        entry, entry_type="DEPOSIT_PAYMENT", amount_cents=596, source_kind="DEPOSIT"
    )
    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        deposit_paid_cents=596,
        fee_recognized_cents=596,
        deposit_balance_cents=0,
        fee_status="SETTLED",
        processing_status="CLOSED",
    )
    assert_ledger_conservation(request)


def test_reversal_returns_the_balance_to_its_exact_pre_payment_value(api):
    """Undoing the payment restores -596 with zero drift and adds a third ledger row.

    PRD: "A successful reversal appends a line with `entry_type` `REVERSAL`, `source_kind` `ADJUSTMENT`, `reverses_entry_id` set to the targeted line, and `amount_cents` set to exactly the negation of the target's `amount_cents`."

    Design: Difficulty/compensating_invariant/payment_reversal_conserves_ledger_balance_identity
    """
    scenario = _invoiced_released_request(api)
    payment = post_payment(api, scenario["request_id"], scenario["requester_id"], 596)

    response = api.reverse_ledger_entry(
        payment["id"],
        reversal_payload(memo="Card chargeback; payment withdrawn"),
        SUPERVISOR_HEADERS,
    )

    reversal = assert_created(response)
    assert_fields(
        reversal,
        entry_type="REVERSAL",
        amount_cents=-596,
        reverses_entry_id=payment["id"],
        source_kind="ADJUSTMENT",
    )
    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        deposit_balance_cents=-596,
        deposit_paid_cents=0,
        fee_recognized_cents=596,
        waiver_credit_total_cents=0,
        invoiced_total_cents=596,
        fee_status="INVOICED",
        processing_status="CLOSED",
    )
    assert_ledger_conservation(request)
    assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        3,
    )


def test_reversing_the_same_entry_twice_is_refused(api):
    """A line already named by a reversal cannot be reversed again.

    PRD: "The targeted ledger line must not itself be a `REVERSAL` and must not already be named by an existing reversal's `reverses_entry_id`; either condition is refused with `ERR_ENTRY_ALREADY_REVERSED`."

    Design: Difficulty/compensating_invariant/payment_reversal_conserves_ledger_balance_identity
    """
    scenario = _invoiced_released_request(api)
    payment = post_payment(api, scenario["request_id"], scenario["requester_id"], 596)
    api.reverse_ledger_entry(
        payment["id"],
        reversal_payload(memo="Card chargeback; payment withdrawn"),
        SUPERVISOR_HEADERS,
    )

    response = api.reverse_ledger_entry(
        payment["id"],
        reversal_payload(memo="Duplicate chargeback attempt"),
        SUPERVISOR_HEADERS,
    )

    validate_error(response, ERR_ENTRY_ALREADY_REVERSED, 409)
    assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        3,
    )
    assert get_request(api, scenario["request_id"])["deposit_balance_cents"] == -596


def _one_approved_task_and_one_draft(api):
    """Two tasks over the same seconds; the FACE one is approved at seven minutes."""
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0520",
        device_serial="AXON-0520",
        officer_badge="B-1112",
        recorded_start_at="2026-07-19T19:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-19T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0520",
        requested_date_from="2026-07-19T00:00:00Z",
        requested_date_to="2026-07-20T00:00:00Z",
        scope_narrative="BWC video for INC-2026-0520",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="First 20 seconds",
        requested_date_from="2026-07-19T00:00:00Z",
        requested_date_to="2026-07-19T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task1 = open_task(api, record["id"], tech["id"], "FACE", 0, 20000)
    task2 = open_task(api, record["id"], tech["id"], "LICENSE_PLATE", 0, 20000)
    submit_for_qa(
        api, task1["id"], tech["id"], reviewer["id"], 7,
        "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z",
    )
    record_verdict(api, task1["id"], reviewer["id"], "PASS")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "tech_id": tech["id"],
        "reviewer_id": reviewer["id"],
        "task1_id": task1["id"],
        "task2_id": task2["id"],
    }


def test_a_pending_submission_adds_nothing_to_billable_minutes(api):
    """Five claimed minutes sitting at QA_PENDING leave the request's total at seven.

    PRD: "Nothing fiscal moves: the request's `billable_labor_minutes` is untouched, because the task has not been approved."

    Design: Difficulty/compensating_invariant/qa_rejection_conserves_request_billable_minutes
    """
    scenario = _one_approved_task_and_one_draft(api)
    assert_fields(get_task(api, scenario["task1_id"]), status="APPROVED", approved_labor_minutes=7)
    assert_fields(
        get_request(api, scenario["request_id"]),
        billable_labor_minutes=7,
        processing_status="REDACTION",
    )

    submit_for_qa(
        api, scenario["task2_id"], scenario["tech_id"], scenario["reviewer_id"], 5,
        "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z",
    )

    assert_fields(
        get_task(api, scenario["task2_id"]),
        status="QA_PENDING",
        logged_labor_minutes=5,
        approved_labor_minutes=0,
    )
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 7


def test_a_rejected_submission_leaves_billable_minutes_exactly_where_it_started(api):
    """The submit-and-reject pair is fully compensating: still exactly seven minutes.

    PRD: "A failure moves the task `QA_PENDING → QA_REJECTED`, stores the supplied `defect_codes`, and leaves `approved_labor_minutes` at 0 — which is why a submission followed by a failure leaves the request's `billable_labor_minutes` exactly where it started."

    Design: Difficulty/compensating_invariant/qa_rejection_conserves_request_billable_minutes
    """
    scenario = _one_approved_task_and_one_draft(api)
    submit_for_qa(
        api, scenario["task2_id"], scenario["tech_id"], scenario["reviewer_id"], 5,
        "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z",
    )

    record_verdict(
        api, scenario["task2_id"], scenario["reviewer_id"], "FAIL", ["EDGE_BLEED"]
    )

    rejected = get_task(api, scenario["task2_id"])
    assert_fields(rejected, status="QA_REJECTED", approved_labor_minutes=0)
    assert rejected["defect_codes"] == ["EDGE_BLEED"]
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 7
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0


def test_resubmission_overwrites_the_claimed_minutes_rather_than_accumulating_them(api):
    """The rework carries six minutes, not the discarded five and not eleven.

    PRD: "Whichever edge is taken, `qa_reviewer_id`, `qa_window_start_at`, `qa_window_end_at` and `logged_labor_minutes` are all overwritten by this call — the claimed minutes are replaced, never accumulated across attempts — and the nominated reviewer's `open_qa_assignment_count` increases by 1."

    Design: Difficulty/compensating_invariant/qa_rejection_conserves_request_billable_minutes
    """
    scenario = _one_approved_task_and_one_draft(api)
    submit_for_qa(
        api, scenario["task2_id"], scenario["tech_id"], scenario["reviewer_id"], 5,
        "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z",
    )
    record_verdict(api, scenario["task2_id"], scenario["reviewer_id"], "FAIL", ["EDGE_BLEED"])

    submit_for_qa(
        api, scenario["task2_id"], scenario["tech_id"], scenario["reviewer_id"], 6,
        "2026-08-01T14:00:00Z", "2026-08-01T15:00:00Z",
    )

    resubmitted = get_task(api, scenario["task2_id"])
    assert_fields(
        resubmitted, status="QA_PENDING", rework_count=1, logged_labor_minutes=6
    )
    assert resubmitted["logged_labor_minutes"] != 11
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1


def test_the_eventual_pass_bills_the_relogged_minutes_only(api):
    """Thirteen minutes: seven plus the re-logged six, never twelve and never eighteen.

    PRD: "Both then reconcile the labour rollup: a record's `approved_labor_minutes` is the total `approved_labor_minutes` of the tasks on it whose `status` is `APPROVED`, its `redacted_segment_ms` is the total of `clip_end_ms` minus `clip_start_ms` over those same approved tasks, and the request's `billable_labor_minutes` is the total of `approved_labor_minutes` across every one of its records — including `EXCLUDED` ones, whose tasks are cancelled and therefore contribute nothing anyway."

    Design: Difficulty/compensating_invariant/qa_rejection_conserves_request_billable_minutes
    """
    scenario = _one_approved_task_and_one_draft(api)
    submit_for_qa(
        api, scenario["task2_id"], scenario["tech_id"], scenario["reviewer_id"], 5,
        "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z",
    )
    record_verdict(api, scenario["task2_id"], scenario["reviewer_id"], "FAIL", ["EDGE_BLEED"])
    submit_for_qa(
        api, scenario["task2_id"], scenario["tech_id"], scenario["reviewer_id"], 6,
        "2026-08-01T14:00:00Z", "2026-08-01T15:00:00Z",
    )

    record_verdict(api, scenario["task2_id"], scenario["reviewer_id"], "PASS")

    assert_fields(
        get_task(api, scenario["task2_id"]), status="APPROVED", approved_labor_minutes=6
    )
    request = get_request(api, scenario["request_id"])
    assert request["billable_labor_minutes"] == 13
    assert request["billable_labor_minutes"] not in (12, 18)
    assert request["processing_status"] == "RELEASE_READY"
    assert_fields(
        get_record(api, scenario["record_id"]),
        approved_labor_minutes=13,
        redacted_segment_ms=40000,
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0
