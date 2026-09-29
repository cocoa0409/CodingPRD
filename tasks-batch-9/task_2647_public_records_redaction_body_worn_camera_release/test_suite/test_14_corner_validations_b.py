"""Corner-case validation instances: the rejection ladder's lower rungs.

Each scenario below drives one declared refusal to its exact `error_id` and HTTP
status, proves the refused call mutated nothing, and — where the design pins the
subsequent legal call — drives that call too.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_CLAIM_RECORD_MISMATCH,
    ERR_ENTRY_ALREADY_REVERSED,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_TIME_RANGE,
    ERR_OBJECTION_UNRESOLVED,
    ERR_PAYMENT_EXCEEDS_OUTSTANDING,
    ERR_QA_LOAD_EXCEEDED,
    ERR_RETENTION_HOLD_ACTIVE,
)
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_ids,
    assert_ledger_conservation,
    assert_modified,
    assert_money_is_integer_cents,
    assert_total_count,
)
from test_helpers.factories import (
    inclusion_payload,
    payment_payload,
    purge_payload,
    redaction_task_payload,
    release_package_payload,
    reversal_payload,
    submit_qa_payload,
)
from test_helpers.fixtures import (
    attach_record,
    assert_claim,
    clarify_scope,
    create_asset,
    create_depicted_individual,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_asset,
    get_individual,
    get_ledger_entry,
    get_record,
    get_request,
    get_requester,
    get_staff,
    get_task,
    issue_notice,
    open_task,
    post_payment,
    record_verdict,
    rule_inclusion,
    scoped_request_with_records,
    set_clock,
    submit_for_qa,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    make_requester_headers,
    make_technician_headers,
)


# ------------------------------------------------------------------ instance A
def _reviewer_at_capacity_with_a_fourth_draft(api):
    """Quinn holds the maximum three QA_PENDING bookings; a fourth FACE task waits.

    The three booked windows sit thirty-one minutes apart, so none of them
    collides under the buffered closed-interval rule and only the concurrency
    ceiling is live.
    """
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    reviewer = create_staff(api, "Quinn Reviewer", "REVIEWER", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0645",
        device_serial="AXON-0645",
        officer_badge="B-1139",
        recorded_start_at="2026-07-16T14:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-16T00:00:00Z",
    )
    scoped = scoped_request_with_records(
        api,
        requester["id"],
        [asset["id"]],
        incident_number="INC-2026-0645",
        requested_date_from="2026-07-16T00:00:00Z",
        requested_date_to="2026-07-17T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0645",
    )
    record_id = scoped["record_ids"][0]
    tasks = [
        open_task(api, record_id, tech["id"], "FACE", start, start + 60000)["id"]
        for start in (0, 60000, 120000, 180000)
    ]
    submit_for_qa(
        api, tasks[0], tech["id"], reviewer["id"], 10,
        "2026-08-06T09:00:00Z", "2026-08-06T09:30:00Z",
    )
    submit_for_qa(
        api, tasks[1], tech["id"], reviewer["id"], 11,
        "2026-08-06T10:01:00Z", "2026-08-06T10:31:00Z",
    )
    submit_for_qa(
        api, tasks[2], tech["id"], reviewer["id"], 12,
        "2026-08-06T11:02:00Z", "2026-08-06T11:32:00Z",
    )
    return {
        "tech_id": tech["id"],
        "reviewer_id": reviewer["id"],
        "task_ids": tasks,
    }


def _assert_fourth_task_untouched(api, scenario):
    """The refused fourth submission booked nobody and claimed no minutes."""
    assert_fields(
        get_task(api, scenario["task_ids"][3]),
        status="DRAFT",
        qa_reviewer_id=None,
        qa_window_start_at=None,
        qa_window_end_at=None,
        logged_labor_minutes=0,
        approved_labor_minutes=0,
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 3


def test_a_reversed_qa_window_is_reported_before_the_reviewer_load_limit(api):
    """A fourth booking whose window runs backwards reports the time range, not the load.

    PRD: "And `qa_window_start_at` must fall strictly before `qa_window_end_at`, or the call is refused with `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/reversed_qa_window_is_reported_before_the_reviewer_load_limit
    """
    scenario = _reviewer_at_capacity_with_a_fourth_draft(api)

    response = api.submit_qa(
        scenario["task_ids"][3],
        submit_qa_payload(
            scenario["reviewer_id"], 13, "2026-08-06T13:00:00Z", "2026-08-06T12:00:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_INVALID_TIME_RANGE, 422)
    _assert_fourth_task_untouched(api, scenario)
    for task_id, minutes in zip(scenario["task_ids"][:3], (10, 11, 12)):
        assert_fields(
            get_task(api, task_id), status="QA_PENDING", logged_labor_minutes=minutes
        )


def test_the_well_formed_fourth_booking_then_reports_the_reviewer_load_limit(api):
    """With the window thirty-one minutes clear, the concurrency ceiling refuses it.

    PRD: "Separately, and regardless of where the windows sit, a reviewer may hold at most three tasks at `QA_PENDING` at once; a fourth booking is refused with `ERR_QA_LOAD_EXCEEDED`."

    Design: Corner/validations/reversed_qa_window_is_reported_before_the_reviewer_load_limit
    """
    scenario = _reviewer_at_capacity_with_a_fourth_draft(api)

    response = api.submit_qa(
        scenario["task_ids"][3],
        submit_qa_payload(
            scenario["reviewer_id"], 13, "2026-08-06T12:03:00Z", "2026-08-06T12:33:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_QA_LOAD_EXCEEDED, 409)
    _assert_fourth_task_untouched(api, scenario)
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"qa_reviewer_id": scenario["reviewer_id"]}
        ),
        3,
    )


# ------------------------------------------------------------------ instance B
def _past_due_recording_held_by_an_open_request(api):
    """A recording whose purge date matured on 2026-07-01, attached as a CANDIDATE.

    No litigation hold exists anywhere, so the recording stays `SCHEDULED` and the
    only thing locking it is the open request.
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0646",
        device_serial="AXON-0646",
        officer_badge="B-1140",
        recorded_start_at="2026-01-15T14:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="NON_EVIDENTIARY_180D",
        scheduled_purge_at="2026-07-01T00:00:00Z",
    )
    scoped = scoped_request_with_records(
        api,
        requester["id"],
        [asset["id"]],
        incident_number="INC-2026-0646",
        inclusion_status=None,
        requested_date_from="2026-01-15T00:00:00Z",
        requested_date_to="2026-01-16T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0646",
    )
    return {
        "asset_id": asset["id"],
        "request_id": scoped["request_id"],
        "record_id": scoped["record_ids"][0],
    }


def test_an_open_request_locks_a_past_due_recording_against_destruction(api):
    """The lock comes from the live request alone, and it beats the matured purge date.

    PRD: "A recording that is `SUSPENDED` or already `PURGED` is refused with `ERR_ASSET_STATE_INVALID`; one that is still locked — whether by an `ACTIVE` matching hold or by an open request — is refused with `ERR_RETENTION_HOLD_ACTIVE`; and one whose purge date has not yet arrived is refused with `ERR_PURGE_NOT_DUE`."

    Design: Corner/validations/open_request_locks_the_recording_against_destruction
    """
    scenario = _past_due_recording_held_by_an_open_request(api)

    response = api.purge_video_asset(
        scenario["asset_id"], purge_payload("Retention schedule sweep"), SUPERVISOR_HEADERS
    )

    validate_error(response, ERR_RETENTION_HOLD_ACTIVE, 409)
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        disposition_state="SCHEDULED",
        retention_locked=True,
        suspended_by_hold_id=None,
    )
    assert_fields(get_record(api, scenario["record_id"]), inclusion_status="CANDIDATE")


def test_excluding_the_record_releases_the_lock_and_the_purge_lands(api):
    """Ruling the record EXCLUDED unlocks the recording in the same flow.

    PRD: "A ruling of `EXCLUDED` moves the record `CANDIDATE → EXCLUDED`, which is terminal, recomputes the request's `responsive_record_count`, and recomputes the recording's `retention_locked`, since the excluded record no longer justifies locking it."

    Design: Corner/validations/open_request_locks_the_recording_against_destruction
    """
    scenario = _past_due_recording_held_by_an_open_request(api)
    api.purge_video_asset(
        scenario["asset_id"], purge_payload("Retention schedule sweep"), SUPERVISOR_HEADERS
    )

    ruled = assert_modified(
        api.rule_inclusion(scenario["record_id"], inclusion_payload("EXCLUDED"), CLERK_HEADERS)
    )

    assert_fields(ruled, inclusion_status="EXCLUDED")
    purged = assert_modified(
        api.purge_video_asset(
            scenario["asset_id"],
            purge_payload("Retention schedule sweep, second pass"),
            SUPERVISOR_HEADERS,
        )
    )
    assert_fields(purged, disposition_state="PURGED", retention_locked=False)
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="SCOPING",
        responsive_record_count=0,
    )


# ------------------------------------------------------------------ instance C
def _two_records_with_a_claim_on_the_first(api):
    """Sibling records A and B on one request; only A carries an ASSERTED claim."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset_a = create_asset(
        api,
        incident_number="INC-2026-0647",
        device_serial="AXON-0647A",
        officer_badge="B-1141",
        recorded_start_at="2026-07-15T14:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-15T00:00:00Z",
    )
    asset_b = create_asset(
        api,
        incident_number="INC-2026-0647",
        device_serial="AXON-0647B",
        officer_badge="B-1142",
        recorded_start_at="2026-07-15T14:30:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-15T00:00:00Z",
    )
    scoped = scoped_request_with_records(
        api,
        requester["id"],
        [asset_a["id"], asset_b["id"]],
        incident_number="INC-2026-0647",
        requested_date_from="2026-07-15T00:00:00Z",
        requested_date_to="2026-07-16T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0647",
    )
    record_a, record_b = scoped["record_ids"]
    claim = assert_claim(api, record_a, counsel["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT")
    return {
        "tech_id": tech["id"],
        "record_a": record_a,
        "record_b": record_b,
        "claim_a": claim["id"],
    }


def test_a_task_cannot_cite_a_claim_hanging_off_the_sibling_record(api):
    """The claim exists, so the coherence failure is reported instead of a 404.

    PRD: "A supplied `exemption_claim_id` must name a claim whose `responsive_record_id` is the record in the path, or the call is refused with `ERR_CLAIM_RECORD_MISMATCH`."

    Design: Corner/validations/task_cannot_cite_a_claim_from_a_different_record
    """
    scenario = _two_records_with_a_claim_on_the_first(api)

    response = api.create_redaction_task(
        scenario["record_b"],
        redaction_task_payload(
            scenario["tech_id"], "FACE", 0, 60000, scenario["claim_a"]
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_CLAIM_RECORD_MISMATCH, 422)
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_b"]}
        ),
        0,
    )
    assert_fields(
        get_record(api, scenario["record_b"]),
        release_posture="OPEN",
        unadjudicated_claim_count=0,
    )


def test_the_same_claim_is_accepted_on_its_own_record(api):
    """Cited from record A, the identical payload opens a DRAFT task.

    PRD: "The task is created at `status` `DRAFT` with `rework_count` 0, `logged_labor_minutes` 0, `approved_labor_minutes` 0 and `defect_codes` as an empty array, and with `qa_reviewer_id`, `qa_window_start_at` and `qa_window_end_at` all null until the first submission books a reviewer."

    Design: Corner/validations/task_cannot_cite_a_claim_from_a_different_record
    """
    scenario = _two_records_with_a_claim_on_the_first(api)
    api.create_redaction_task(
        scenario["record_b"],
        redaction_task_payload(scenario["tech_id"], "FACE", 0, 60000, scenario["claim_a"]),
        make_technician_headers(scenario["tech_id"]),
    )

    response = api.create_redaction_task(
        scenario["record_a"],
        redaction_task_payload(
            scenario["tech_id"], "FACE", 0, 60000, scenario["claim_a"]
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    task = assert_created(response)
    assert_fields(
        task,
        status="DRAFT",
        exemption_claim_id=scenario["claim_a"],
        rework_count=0,
        logged_labor_minutes=0,
        approved_labor_minutes=0,
        qa_reviewer_id=None,
    )
    assert task["defect_codes"] == []
    data, _ = assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"exemption_claim_id": scenario["claim_a"]}
        ),
        1,
    )
    assert_ids(data, [task["id"]])
    assert_fields(get_record(api, scenario["record_a"]), release_posture="RESTRICTED")


# ------------------------------------------------------------ instances D and E
def _request_owing_a_3060_cent_deposit(api):
    """One 120-minute ROUTINE recording priced on DVD: subtotal 6800, deposit 3060.

    Labour is 120 review minutes plus a 30-minute baseline obscuration less the
    sixty-minute free allowance, so the estimate lands at 6120 cents and the
    deposit at half of it. The clock never leaves 2026-08-01T00:00:00Z, so the
    payment arrives long before `deposit_due_at`.
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0648",
        device_serial="AXON-0648",
        officer_badge="B-1143",
        recorded_start_at="2026-07-14T09:00:00Z",
        duration_ms=7200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-14T00:00:00Z",
    )
    scoped = scoped_request_with_records(
        api,
        requester["id"],
        [asset["id"]],
        incident_number="INC-2026-0648",
        requested_date_from="2026-07-14T00:00:00Z",
        requested_date_to="2026-07-15T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0648",
    )
    estimate = create_estimate(api, scoped["request_id"], "PRESUMPTIVE", "DVD")
    assert_fields(
        estimate, subtotal_cents=6800, estimated_total_cents=6120, deposit_required_cents=3060
    )
    return {
        "requester_id": requester["id"],
        "request_id": scoped["request_id"],
        "estimate_id": estimate["id"],
    }


def _assert_no_payment_landed(api, scenario):
    """A refused payment writes no ledger row and moves no fiscal figure."""
    assert_total_count(
        api.list_ledger_entries(SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}),
        0,
    )
    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        fee_status="DEPOSIT_DUE",
        deposit_required_cents=3060,
        deposit_paid_cents=0,
        deposit_balance_cents=0,
    )
    assert_ledger_conservation(request)


def test_a_zero_payment_is_refused_as_an_invalid_amount(api):
    """Zero is not strictly greater than zero, so nothing is posted.

    PRD: "The amount must be strictly greater than zero, or the call is refused with `ERR_INVALID_AMOUNT`."

    Design: Corner/validations/payment_must_be_positive_and_within_the_outstanding_deposit
    """
    scenario = _request_owing_a_3060_cent_deposit(api)

    response = api.post_payment(
        scenario["request_id"],
        payment_payload(0, "Zero payment"),
        make_requester_headers(scenario["requester_id"]),
    )

    validate_error(response, ERR_INVALID_AMOUNT, 422)
    _assert_no_payment_landed(api, scenario)


def test_one_cent_over_the_outstanding_deposit_is_refused(api):
    """3061 cents exceeds the 3060 still owed, so the overpayment is rejected.

    PRD: "It must also not exceed what is currently owed: the ceiling is the greater of `deposit_required_cents` less `deposit_paid_cents` and `invoiced_total_cents` less `deposit_paid_cents`, evaluated against the request's current `fee_status`, and an overpayment is refused with `ERR_PAYMENT_EXCEEDS_OUTSTANDING`."

    Design: Corner/validations/payment_must_be_positive_and_within_the_outstanding_deposit
    """
    scenario = _request_owing_a_3060_cent_deposit(api)

    response = api.post_payment(
        scenario["request_id"],
        payment_payload(3061, "One cent over"),
        make_requester_headers(scenario["requester_id"]),
    )

    validate_error(response, ERR_PAYMENT_EXCEEDS_OUTSTANDING, 422)
    _assert_no_payment_landed(api, scenario)


def test_the_exact_outstanding_deposit_settles_it_and_tolls_nothing(api):
    """Exactly 3060 cents posts one DEPOSIT_PAYMENT line and freezes tolled_days at 0.

    PRD: "When `fee_status` is `DEPOSIT_DUE` and `deposit_balance_cents` after the payment has reached `deposit_required_cents`, the request moves `DEPOSIT_DUE → DEPOSIT_PAID`; on that specific edge, and only on it, `tolled_days` is frozen and `statutory_deadline_at` is re-struck as described in §3.3."

    Design: Corner/validations/payment_must_be_positive_and_within_the_outstanding_deposit
    """
    scenario = _request_owing_a_3060_cent_deposit(api)
    api.post_payment(
        scenario["request_id"],
        payment_payload(0, "Zero payment"),
        make_requester_headers(scenario["requester_id"]),
    )

    response = api.post_payment(
        scenario["request_id"],
        payment_payload(3060, "Deposit in full"),
        make_requester_headers(scenario["requester_id"]),
    )

    entry = assert_created(response)
    assert_fields(
        entry,
        entry_type="DEPOSIT_PAYMENT",
        source_kind="DEPOSIT",
        amount_cents=3060,
        reverses_entry_id=None,
    )
    assert_money_is_integer_cents(entry, "amount_cents")
    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        fee_status="DEPOSIT_PAID",
        deposit_paid_cents=3060,
        deposit_balance_cents=3060,
        deposit_required_cents=3060,
        tolled_days=0,
        statutory_deadline_at="2026-08-21T00:00:00Z",
    )
    assert_ledger_conservation(request)
    assert_total_count(
        api.list_ledger_entries(SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}),
        1,
    )
    estimates, _ = assert_total_count(
        api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS), 1
    )
    assert_fields(estimates[0], status="ACTIVE", deposit_required_cents=3060)


def _deposit_paid_request(api):
    """The same request with its 3060-cent deposit posted in full, one ledger row."""
    scenario = _request_owing_a_3060_cent_deposit(api)
    payment = post_payment(
        api, scenario["request_id"], scenario["requester_id"], 3060
    )
    return {**scenario, "payment_id": payment["id"]}


def test_reversing_the_deposit_payment_restores_the_pre_payment_figures(api):
    """The compensating line carries -3060 and returns both figures to zero.

    PRD: "A successful reversal appends a line with `entry_type` `REVERSAL`, `source_kind` `ADJUSTMENT`, `reverses_entry_id` set to the targeted line, and `amount_cents` set to exactly the negation of the target's `amount_cents`."

    Design: Corner/validations/a_ledger_entry_can_only_be_reversed_once
    """
    scenario = _deposit_paid_request(api)

    response = api.reverse_ledger_entry(
        scenario["payment_id"], reversal_payload("Card chargeback"), SUPERVISOR_HEADERS
    )

    reversal = assert_created(response)
    assert_fields(
        reversal,
        entry_type="REVERSAL",
        source_kind="ADJUSTMENT",
        amount_cents=-3060,
        reverses_entry_id=scenario["payment_id"],
    )
    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        deposit_paid_cents=0,
        deposit_balance_cents=0,
        fee_status="DEPOSIT_PAID",
    )
    assert_ledger_conservation(request)
    assert_total_count(
        api.list_ledger_entries(SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}),
        2,
    )
    assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"reverses_entry_id": scenario["payment_id"]}
        ),
        1,
    )


def test_a_second_reversal_of_the_same_ledger_entry_is_refused(api):
    """A line already named by a reversal cannot be reversed twice.

    PRD: "The targeted ledger line must not itself be a `REVERSAL` and must not already be named by an existing reversal's `reverses_entry_id`; either condition is refused with `ERR_ENTRY_ALREADY_REVERSED`."

    Design: Corner/validations/a_ledger_entry_can_only_be_reversed_once
    """
    scenario = _deposit_paid_request(api)
    api.reverse_ledger_entry(
        scenario["payment_id"], reversal_payload("Card chargeback"), SUPERVISOR_HEADERS
    )

    response = api.reverse_ledger_entry(
        scenario["payment_id"],
        reversal_payload("Second chargeback attempt"),
        SUPERVISOR_HEADERS,
    )

    validate_error(response, ERR_ENTRY_ALREADY_REVERSED, 409)
    assert_fields(
        get_ledger_entry(api, scenario["payment_id"]),
        entry_type="DEPOSIT_PAYMENT",
        amount_cents=3060,
    )
    assert_total_count(
        api.list_ledger_entries(SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}),
        2,
    )
    request = get_request(api, scenario["request_id"])
    assert_fields(request, deposit_paid_cents=0, deposit_balance_cents=0)
    assert_ledger_conservation(request)


def test_a_reversal_entry_is_not_itself_reversible(api):
    """Reversing the reversal is refused, so the ledger settles at exactly two rows.

    PRD: "The targeted ledger line must not itself be a `REVERSAL` and must not already be named by an existing reversal's `reverses_entry_id`; either condition is refused with `ERR_ENTRY_ALREADY_REVERSED`."

    Design: Corner/validations/a_ledger_entry_can_only_be_reversed_once
    """
    scenario = _deposit_paid_request(api)
    reversal = assert_created(
        api.reverse_ledger_entry(
            scenario["payment_id"], reversal_payload("Card chargeback"), SUPERVISOR_HEADERS
        )
    )

    response = api.reverse_ledger_entry(
        reversal["id"], reversal_payload("Un-reverse the reversal"), SUPERVISOR_HEADERS
    )

    validate_error(response, ERR_ENTRY_ALREADY_REVERSED, 409)
    assert_total_count(
        api.list_ledger_entries(SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}),
        2,
    )
    request = get_request(api, scenario["request_id"])
    assert_fields(request, deposit_paid_cents=0, deposit_balance_cents=0, fee_status="DEPOSIT_PAID")
    assert_ledger_conservation(request)


# ------------------------------------------------------------------ instance F
def _release_ready_request_with_a_notified_victim(api):
    """A RELEASE_READY request over one hour of footage depicting a notified victim.

    No exemption claim is ever asserted, so the single FACE task carried the
    request through REDACTION to RELEASE_READY on its PASS verdict, and no fee
    estimate is issued, so the fiscal gate is already satisfied. The notice goes
    out at 2026-08-05T14:30:00Z, closing the victim's ten-day window at
    2026-08-15T14:30:00Z.
    """
    tech = create_staff(api, "Tech One", "TECHNICIAN", 1)
    reviewer = create_staff(api, "Reviewer One", "REVIEWER", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0650",
        device_serial="AXON-0650",
        officer_badge="B-1145",
        recorded_start_at="2026-07-12T09:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-12T00:00:00Z",
    )
    individual = create_depicted_individual(api, asset["id"], "Victim A", "VICTIM")
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0650",
        requested_date_from="2026-07-12T00:00:00Z",
        requested_date_to="2026-07-13T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0650",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The single one-hour recording",
        requested_date_from="2026-07-12T00:00:00Z",
        requested_date_to="2026-07-12T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 3600000)
    submit_for_qa(
        api, task["id"], tech["id"], reviewer["id"], 20,
        "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z",
    )
    record_verdict(api, task["id"], reviewer["id"], "PASS")
    set_clock(api, "2026-08-05T14:30:00Z")
    issue_notice(api, individual["id"], "FIRST_CLASS_MAIL")
    return {
        "requester_id": requester["id"],
        "request_id": request["id"],
        "record_id": record["id"],
        "individual_id": individual["id"],
        "task_id": task["id"],
    }


def test_an_open_victim_objection_window_blocks_the_release(api):
    """Five days into a ten-day window the release is refused and nothing is swept.

    PRD: "A notification-required individual sitting at `OBJECTED`, or at `NOTIFIED` with a window that has not yet run, yields `ERR_OBJECTION_UNRESOLVED`."

    Design: Corner/validations/unexpired_victim_notice_blocks_release_then_the_sweep_waives_it
    """
    scenario = _release_ready_request_with_a_notified_victim(api)
    assert_fields(get_task(api, scenario["task_id"]), status="APPROVED", approved_labor_minutes=20)
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASE_READY",
        billable_labor_minutes=20,
    )
    assert_fields(
        get_individual(api, scenario["individual_id"]),
        notification_status="NOTIFIED",
        objection_deadline_at="2026-08-15T14:30:00Z",
    )
    set_clock(api, "2026-08-10T09:00:00Z")

    response = api.create_release_package(
        scenario["request_id"], release_package_payload("DIGITAL_DOWNLOAD"), CLERK_HEADERS
    )

    validate_error(response, ERR_OBJECTION_UNRESOLVED, 409)
    assert_fields(
        get_individual(api, scenario["individual_id"]), notification_status="NOTIFIED"
    )
    assert_fields(
        get_record(api, scenario["record_id"]), inclusion_status="RESPONSIVE", released_at=None
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASE_READY",
        open_notification_count=1,
    )
    assert_total_count(api.list_release_packages(scenario["request_id"], CLERK_HEADERS), 0)


def test_the_sweep_waives_the_notice_at_the_deadline_instant_and_the_release_lands(api):
    """At exactly 2026-08-15T14:30:00Z the same call sweeps the victim and releases.

    PRD: "This ordering is load-bearing: an individual swept in this call counts as satisfied within the same call, so a release attempted at exactly the deadline instant succeeds."

    Design: Corner/validations/unexpired_victim_notice_blocks_release_then_the_sweep_waives_it
    """
    scenario = _release_ready_request_with_a_notified_victim(api)
    set_clock(api, "2026-08-10T09:00:00Z")
    api.create_release_package(
        scenario["request_id"], release_package_payload("DIGITAL_DOWNLOAD"), CLERK_HEADERS
    )
    set_clock(api, "2026-08-15T14:30:00Z")

    response = api.create_release_package(
        scenario["request_id"], release_package_payload("DIGITAL_DOWNLOAD"), CLERK_HEADERS
    )

    package = assert_created(response)
    assert_fields(
        package,
        waived_notification_count=1,
        package_kind="FINAL",
        included_record_count=1,
        produced_minutes=60,
        disc_count=0,
        production_cost_cents=0,
        released_at="2026-08-15T14:30:00Z",
    )
    assert_fields(
        get_individual(api, scenario["individual_id"]), notification_status="WAIVED"
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASED",
        open_notification_count=0,
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RELEASED",
        released_at="2026-08-15T14:30:00Z",
    )
    assert get_requester(api, scenario["requester_id"])["open_request_count"] == 0
