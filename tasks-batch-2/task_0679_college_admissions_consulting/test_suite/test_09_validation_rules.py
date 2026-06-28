"""Corner queue — validations section: word-limit, single-binding-ED, task-due,
RD-defer, billing-model coherence, outstanding-balance close gate, and open-tasks
mark-ready gate.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_counselor_headers,
    make_student_headers,
    ApiErrorId,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


def test_word_limit_exceeded_on_submit_version(api):
    """PRD §3.5: "The submitted `word_count` must not exceed the essay's
    `word_limit`, or the submission is rejected with `ERR_WORD_LIMIT_EXCEEDED`."

    Design: Corner/validations/word_limit_exceeded_on_submit_version
    """
    counselor, student, essay = fx.setup_essay_drafting(
        student_overrides={"gpa": 3.5, "sat_total": 1300},
        essay_overrides={"prompt": "P", "word_limit": 650},
    )
    sh = make_student_headers(student["id"])
    resp = api.submit_essay_version(essay["id"], f.submit_essay_version_payload(700, "too long"), sh)
    validate_error(resp, ApiErrorId.ERR_WORD_LIMIT_EXCEEDED.value)


def test_second_binding_ed_application_conflict(api):
    """PRD §3.4: "An `ED` application may be created only if the student has no
    other `Application` with `round` of `ED` whose `prep_status` is `NOT_STARTED`,
    `IN_PROGRESS`, `READY`, or `SUBMITTED`; a second such binding ED application is
    rejected with `ERR_ED_CONFLICT`."

    Design: Corner/validations/ed_conflict_second_binding_ed
    """
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    version = student["version"]
    # Two ED schools selected.
    item_a = get_success_data(
        api_client.create_school_list_item(
            f.create_school_list_item_payload(student["id"], school_name="ED A",
                                              admit_rate=0.30, median_sat=1400, round="ED"),
            ch,
        )
    )
    get_success_data(api_client.select_school_list_item(item_a["id"], {"expected_student_version": version}, ch))
    version += 1
    item_b = get_success_data(
        api_client.create_school_list_item(
            f.create_school_list_item_payload(student["id"], school_name="ED B",
                                              admit_rate=0.25, median_sat=1450, round="ED"),
            ch,
        )
    )
    get_success_data(api_client.select_school_list_item(item_b["id"], {"expected_student_version": version}, ch))
    # First ED application.
    get_success_data(
        api_client.create_application(
            f.create_application_payload(student["id"], item_a["id"], "ED",
                                         deadline_utc="2026-11-01T00:00:00Z"),
            ch,
        )
    )
    # Second binding ED application rejected.
    resp = api.create_application(
        f.create_application_payload(student["id"], item_b["id"], "ED",
                                     deadline_utc="2026-11-01T00:00:00Z"),
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_ED_CONFLICT.value)


def test_task_due_after_deadline_rejected(api):
    """PRD §3.4: "A task's `due_utc` must be on or before the parent application's
    `deadline_utc` (equal is allowed); a later due date is rejected with
    `ERR_TASK_DUE_AFTER_DEADLINE`."

    Design: Corner/validations/task_due_after_deadline_rejected
    """
    counselor, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.5, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    resp = api.create_application_task(
        f.create_application_task_payload(app["id"], task_type="FORM", title="Late",
                                          due_utc="2027-02-01T00:00:00Z", blocks_submission=True),
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_TASK_DUE_AFTER_DEADLINE.value)


def test_defer_not_allowed_on_rd_round(api):
    """PRD §3.9: "Recording a `DEFERRED` outcome is additionally restricted to
    applications whose `round` is `ED` or `EA` — a regular-decision round cannot
    be deferred — otherwise it is rejected with `ERR_DEFER_NOT_ALLOWED`."

    Design: Corner/validations/defer_not_allowed_on_rd_round
    """
    counselor, student, app = fx.setup_application_submitted(
        round="RD", deadline_utc="2027-01-01T00:00:00Z", submit_clock="2026-12-01T00:00:00Z",
        student_overrides={"gpa": 3.5, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    resp = api.record_decision(app["id"], {"decision": "DEFERRED"}, ch)
    validate_error(resp, ApiErrorId.ERR_DEFER_NOT_ALLOWED.value)


def test_contract_billing_model_incoherent(api):
    """PRD §3.3: "A `PACKAGE` contract requires `package_fee_cents` greater than 0
    and `package_milestones` greater than 0 (the milestone count over which the
    flat fee amortizes) and requires `hourly_rate_cents` to be 0."
    PRD §3.3: "A body that violates the coherence rule for its declared model is
    rejected with `ERR_BILLING_MODEL_INCOHERENT`."

    Design: Corner/validations/contract_billing_model_incoherent
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    # PACKAGE with package_milestones=0 is incoherent.
    resp = api.create_contract(
        {"student_id": student["id"], "billing_model": "PACKAGE", "package_fee_cents": 600000,
         "package_milestones": 0, "coverage_start_utc": "2026-04-01T00:00:00Z",
         "coverage_end_utc": "2027-06-01T00:00:00Z"},
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_BILLING_MODEL_INCOHERENT.value)


def test_close_contract_with_outstanding_balance(api):
    """PRD §3.3: "it requires that `retainer_balance_cents` is at least 0, so that
    no money is owed, failing which it is rejected with `ERR_OUTSTANDING_BALANCE`"

    Design: Corner/validations/close_contract_outstanding_balance
    """
    # Active HOURLY contract, no deposit, then a 50000 manual CHARGE => balance -50000.
    counselor, student, contract = fx.setup_active_contract(
        billing_model="HOURLY",
        contract_overrides={"hourly_rate_cents": 20000},
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_billing_entry(
            f.create_billing_entry_payload(contract["id"], "CHARGE", "MANUAL", 50000, memo="work"),
            ch,
        )
    )
    resp = api.close_contract(contract["id"], ch)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE.value)


def test_mark_ready_with_open_tasks_remain(api):
    """PRD §3.4: "Marking ready moves `prep_status` from `IN_PROGRESS` to `READY`,
    permitted only when `open_task_count` is 0 — every blocking task `DONE` or
    `WAIVED` — otherwise rejected with `ERR_OPEN_TASKS_REMAIN`"

    Design: Corner/validations/mark_ready_with_open_tasks_remain
    """
    counselor, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.5, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_application_task(
            f.create_application_task_payload(app["id"], task_type="FORM", title="Form",
                                              due_utc="2026-12-01T00:00:00Z", blocks_submission=True),
            ch,
        )
    )
    resp = api.mark_ready_application(app["id"], ch)
    validate_error(resp, ApiErrorId.ERR_OPEN_TASKS_REMAIN.value)
