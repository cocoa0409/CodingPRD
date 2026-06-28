"""Corner queue — state_machines section: invalid transitions, terminal-state
lockdown, precondition enforcement, and side-effect execution (appointment
billing, essay-revision cascade demoting a READY application).
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


def test_void_active_contract_invalid_state(api):
    """PRD §3.3: "if it has any billing entries the void is rejected with
    `ERR_CONTRACT_HAS_ENTRIES`."
    PRD §2.5: "A transition is permitted only when the target resource is in a
    state from which that transition is defined; an attempt to transition from any
    other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/contract_void_from_active_invalid_state
    """
    counselor, student, contract = fx.setup_active_contract(
        billing_model="HOURLY",
        contract_overrides={"hourly_rate_cents": 20000, "retainer_deposit_cents": 100000},
    )
    ch = make_counselor_headers(counselor["id"])
    resp = api.void_contract(contract["id"], ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_essay_approve_without_revision_round_revision_required(api):
    """PRD §3.5: "Both approval transitions carry the same two preconditions: the
    essay's `latest_version_no` must be at least 1 (otherwise
    `ERR_NO_VERSION_TO_REVIEW`), and the essay's `revision_round` must be at least
    1, meaning at least one review cycle has completed (otherwise
    `ERR_REVISION_REQUIRED`)."

    Design: Corner/state_machines/essay_approve_without_revision_round_returns_revision_required
    """
    # Essay IN_REVIEW after first submit: latest_version_no 1 but revision_round still 0.
    counselor, student, essay = fx.setup_essay_in_review(
        word_count=500, body="v1", essay_overrides={"prompt": "P", "word_limit": 650}
    )
    ch = make_counselor_headers(counselor["id"])
    assert essay["revision_round"] == 0
    resp = api.approve_essay(essay["id"], ch)
    validate_error(resp, ApiErrorId.ERR_REVISION_REQUIRED.value)


def test_recommendation_requested_to_submitted_invalid_state(api):
    """PRD §3.6: "The counselor drives its lifecycle: from `REQUESTED` it may move
    to `ACCEPTED`, and from `ACCEPTED` it may move to `SUBMITTED`; from either
    `REQUESTED` or `ACCEPTED` it may move to `DECLINED`."

    Design: Corner/state_machines/recommendation_invalid_transition_requested_to_submitted
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    rec = get_success_data(
        api_client.create_recommendation(
            f.create_recommendation_payload(student["id"], recommender_name="Mr T",
                                            recommender_email="t@x.com", rec_type="TEACHER"),
            make_student_headers(student["id"]),
        )
    )
    # REQUESTED cannot jump directly to SUBMITTED.
    resp = api.transition_recommendation(rec["id"], {"to_status": "SUBMITTED"}, ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_appointment_invalid_state(api):
    """PRD §3.8: "`COMPLETED` and `CANCELLED` are terminal."
    PRD §2.5: "A transition is permitted only when the target resource is in a
    state from which that transition is defined; an attempt to transition from any
    other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/appointment_terminal_lockdown_cancel_after_cancel
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    appt = get_success_data(
        api_client.create_appointment(
            f.create_appointment_payload(student["id"], "2026-05-02T09:00:00Z",
                                         "2026-05-02T10:00:00Z", "CHECK_IN"),
            ch,
        )
    )
    get_success_data(api_client.cancel_appointment(appt["id"], ch))
    resp = api.cancel_appointment(appt["id"], ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_appointment_complete_hourly_billing_ledger_sync(api):
    """PRD §3.8: "On completion the system sets `billed_minutes` to the whole
    number of minutes between `start_utc` and `end_utc`"
    PRD §3.8: "if the student has an `ACTIVE` `HOURLY` contract, the system
    appends a `CHARGE` `BillingEntry` with `source_kind` of `APPOINTMENT`,
    `source_id` set to the appointment, `minutes` equal to `billed_minutes`, and
    `amount_cents` equal to `billed_minutes` divided by 60 and multiplied by the
    contract's `hourly_rate_cents`, rounded half up to a whole number of cents in
    a single final rounding step (never per-minute)."

    Design: Corner/state_machines/appointment_complete_billing_hourly_ledger_sync
    """
    counselor, student, contract = fx.setup_active_contract(
        billing_model="HOURLY",
        contract_overrides={"hourly_rate_cents": 20000, "retainer_deposit_cents": 200000},
    )
    ch = make_counselor_headers(counselor["id"])
    appt = get_success_data(
        api_client.create_appointment(
            f.create_appointment_payload(student["id"], "2026-05-03T09:00:00Z",
                                         "2026-05-03T10:30:00Z", "STRATEGY"),
            ch,
        )
    )
    fx.set_clock("2026-05-03T11:00:00Z")
    completed = validate_success(api.complete_appointment(appt["id"], ch))
    assert completed["billed_minutes"] == 90, (
        f"90-minute appointment should bill 90 minutes; got {completed['billed_minutes']}"
    )
    contract_after = validate_success(api.get_contract(contract["id"], ch))
    # 90/60 * 20000 = 30000.
    assert contract_after["charged_cents"] == 30000
    assert contract_after["retainer_balance_cents"] == 170000


def test_appointment_complete_before_start_not_started(api):
    """PRD §3.8: "It may instead be completed to `COMPLETED`, but only when the
    logical clock now is at or after the appointment's `start_utc`, otherwise the
    completion is rejected with `ERR_APPOINTMENT_NOT_STARTED`."
    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-04-01T00:00:00Z`"

    Design: Corner/state_machines/appointment_complete_before_start_not_started
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    # Clock left at default 2026-04-01; appointment starts in the future.
    appt = get_success_data(
        api_client.create_appointment(
            f.create_appointment_payload(student["id"], "2026-06-01T09:00:00Z",
                                         "2026-06-01T10:00:00Z", "CHECK_IN"),
            ch,
        )
    )
    resp = api.complete_appointment(appt["id"], ch)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_STARTED.value)


def test_essay_revision_demotes_ready_application(api):
    """PRD §3.5: "It also cascades: if the essay has an `application_id` and that
    application's `prep_status` is `READY`, the application is demoted from
    `READY` to `IN_PROGRESS` and its `open_task_count` is recomputed."

    Design: Corner/state_machines/essay_revision_demotes_ready_application_cascade
    """
    counselor, student, app = fx.setup_application_ready(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.5, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    sh = make_student_headers(student["id"])
    assert app["prep_status"] == "READY"
    # New essay linked to the READY application, submitted (IN_REVIEW).
    essay = get_success_data(
        api_client.create_essay(
            f.create_essay_payload(student["id"], word_limit=650, application_id=app["id"], prompt="P"),
            sh,
        )
    )
    get_success_data(api_client.submit_essay_version(essay["id"], f.submit_essay_version_payload(500, "v1"), sh))
    revised = validate_success(api.request_revision_essay(essay["id"], ch))
    assert revised["status"] == "REVISION_REQUESTED"
    app_after = validate_success(api.get_application(app["id"], ch))
    assert app_after["prep_status"] == "IN_PROGRESS", (
        f"request-revision should demote the READY application to IN_PROGRESS; got {app_after['prep_status']}"
    )
