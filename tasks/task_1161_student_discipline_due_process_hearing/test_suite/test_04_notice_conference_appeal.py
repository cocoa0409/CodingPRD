"""Due-process window: notice, conference, appeal gates and deadlines."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_suspension_notice, assert_conference, assert_appeal,
    create_conference_payload, create_conference_outcome_payload,
    create_appeal_payload, create_sanction_payload, create_classify_payload,
    set_clock, create_offense_code_with_bands, create_student,
    create_case, create_classified_case, create_sanctioned_case,
    propose_sanction, issue_notice,
    setup_notice_issued_case, setup_appeal_filed_case, get_case,
    make_school_admin_headers, make_parent_guardian_headers,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["district_admin_headers"]
REF = TEST_USERS["school_referrer_headers"]
CLS = TEST_USERS["school_classifier_headers"]


def test_notice_after_one_day_window_returns_409(api):
    """PRD §3.4: "Two gates guard issuance, IDEA safety before the clock per
    the ladder in §2.9: no manifestation determination for the case may stand
    `PENDING` or `SCHEDULED` (`ERR_MDR_INCOMPLETE`), and the clock must sit no
    later than one day after `proposed_at`, a late attempt drawing
    `ERR_NOTICE_WINDOW_PASSED`."

    Design: Corner/validations/notice_after_one_day_window_returns_409
    """
    set_clock("2026-05-04T09:00:00Z")
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    student = create_student(full_name="Stu NotW", guardian_id="gnw")
    case = create_sanctioned_case(student["id"], oc["id"],
                                  "2026-05-04T08:00:00Z", sanction_days=2)
    # 1 day + 1 second past the proposal instant.
    set_clock("2026-05-05T09:00:01Z")
    res = api.issue_notice(case["id"], {"delivery_method": "EMAIL"}, CLS)
    validate_error(res, ApiErrorId.ERR_NOTICE_WINDOW_PASSED, expected_status=409)

    settled = get_case(case["id"])
    assert settled["status"] == "SANCTION_PROPOSED"
    notices = validate_success(api.list_notices(case["id"], CLS), 200)
    assert notices == [], "no SuspensionNotice row may be created"


def test_conference_beyond_deadline_returns_409(api):
    """PRD §3.4: "Scheduling is possible only while the case is
    `NOTICE_ISSUED`, and the chosen `scheduled_at` must fall on or before the
    notice's `conference_deadline`, otherwise `ERR_CONFERENCE_DEADLINE_PASSED`."

    Design: Corner/validations/conference_beyond_deadline_returns_409
    """
    bundle = setup_notice_issued_case(
        guardian_id="gcd", full_name="Stu ConfD", clock="2026-05-04T09:00:00Z")
    # conference_deadline = issued_at (2026-05-04T09:00) + 3 days.
    res = api.create_conference(
        bundle["case"]["id"],
        create_conference_payload("2026-05-08T10:00:00Z"), CLS)
    validate_error(res, ApiErrorId.ERR_CONFERENCE_DEADLINE_PASSED,
                   expected_status=409)


def test_conference_attempt_limit_returns_409(api):
    """PRD §3.4: "rescheduling a no-show returns it to `SCHEDULED`, replaces
    `scheduled_at`, and increments `attempt_number`, but only while
    `attempt_number` is still below the hard cap of 2 — a second reschedule is
    rejected with `ERR_CONFERENCE_ATTEMPT_LIMIT`".

    Design: Corner/state_machines/conference_attempt_limit_returns_409
    """
    bundle = setup_notice_issued_case(
        guardian_id="ga1", full_name="Stu Att", clock="2026-05-04T09:00:00Z")
    conf = validate_success(api.create_conference(
        bundle["case"]["id"], create_conference_payload("2026-05-05T10:00:00Z"),
        CLS), 201)
    assert_conference(conf)
    assert conf["attempt_number"] == 1

    validate_success(api.record_conference_outcome(
        conf["id"], create_conference_outcome_payload("NO_SHOW"), CLS), 200)
    rescheduled = validate_success(api.reschedule_conference(
        conf["id"], create_conference_payload("2026-05-06T10:00:00Z"), CLS), 200)
    assert rescheduled["attempt_number"] == 2
    validate_success(api.record_conference_outcome(
        conf["id"], create_conference_outcome_payload("NO_SHOW"), CLS), 200)

    # attempt_number == 2 reaches the cap; a further reschedule is rejected.
    res = api.reschedule_conference(
        conf["id"], create_conference_payload("2026-05-07T08:00:00Z"), CLS)
    validate_error(res, ApiErrorId.ERR_CONFERENCE_ATTEMPT_LIMIT,
                   expected_status=409)

    confs = validate_success(api.list_conferences(bundle["case"]["id"], CLS), 200)
    assert confs[0]["status"] == "NO_SHOW", (
        f"conference must remain NO_SHOW, got {confs[0]['status']!r}")
    assert confs[0]["attempt_number"] == 2


def test_appeal_one_second_past_deadline_returns_409(api):
    """PRD §3.4: "The filing window closes at the inclusive `appeal_deadline`
    — filing after it draws `ERR_APPEAL_WINDOW_CLOSED`".

    Design: Corner/validations/appeal_one_second_past_deadline_returns_409
    """
    bundle = setup_notice_issued_case(
        guardian_id="glate", full_name="Stu Late", clock="2026-05-04T09:00:00Z")
    # appeal_deadline = 2026-05-04T09:00 + 5 days = 2026-05-09T09:00; +1s.
    set_clock("2026-05-09T09:00:01Z")
    res = api.file_appeal(
        bundle["case"]["id"], create_appeal_payload("one second late"),
        make_parent_guardian_headers("glate"))
    validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED, expected_status=409)


def test_second_open_appeal_returns_409(api):
    """PRD §3.4: "only one appeal may stand `FILED` per case at a time, a
    second drawing `ERR_APPEAL_ALREADY_OPEN`."

    Design: Corner/validations/second_open_appeal_returns_409
    """
    bundle = setup_appeal_filed_case(
        guardian_id="gt2", full_name="Stu Two", clock="2026-05-04T09:00:00Z",
        appeal_clock="2026-05-05T09:00:00Z", grounds="first")
    assert bundle["appeal"]["status"] == "FILED"

    set_clock("2026-05-06T09:00:00Z")  # still inside the filing window
    res = api.file_appeal(
        bundle["case"]["id"], create_appeal_payload("second while first open"),
        make_parent_guardian_headers("gt2"))
    validate_error(res, ApiErrorId.ERR_APPEAL_ALREADY_OPEN, expected_status=409)


def test_confirm_from_classified_returns_409(api):
    """PRD §3.4: "Confirmation is the last step of the ordinary track, moving
    the case `NOTICE_ISSUED` → `CONFIRMED` behind two due-process gates".
    PRD §2.9: "The entity stands in a valid from-state for the requested
    transition ... Violations are rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_from_classified_returns_409
    """
    set_clock("2026-05-04T09:00:00Z")
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    student = create_student(full_name="Stu Inv", guardian_id="gi2")
    case = create_classified_case(student["id"], oc["id"],
                                  "2026-05-04T08:00:00Z")
    res = api.confirm_case(case["id"], {}, CLS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_close_from_notice_issued_returns_409(api):
    """PRD §3.8: "An ordinary confirmed case closes once its days are served:
    the clock must have reached the day falling `sanction_days_final` days
    after `confirmed_at`, and an earlier close is rejected with
    `ERR_INVALID_STATE`."
    PRD §2.9: "The entity stands in a valid from-state for the requested
    transition ... Violations are rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_from_notice_issued_returns_409
    """
    bundle = setup_notice_issued_case(
        guardian_id="gi3", full_name="Stu Inv2", clock="2026-05-04T09:00:00Z")
    res = api.close_case(bundle["case"]["id"], {}, CLS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_confirm_while_appeal_filed_returns_409(api):
    """PRD §3.4: "The appeal gate then requires that no appeal of the case
    stands `FILED` and that either the `appeal_deadline` has passed or at least
    one appeal has reached a terminal decision; otherwise the confirm is
    rejected with `ERR_APPEAL_WINDOW_OPEN`."

    Design: Corner/validations/confirm_while_appeal_filed_returns_409
    """
    bundle = setup_appeal_filed_case(
        guardian_id="gcaw", full_name="Stu CAW", clock="2026-05-04T09:00:00Z",
        appeal_clock="2026-05-05T09:00:00Z", grounds="pending appeal")
    # Past the conference deadline (issued + 3 days) but inside the appeal
    # window, with the appeal still FILED.
    set_clock("2026-05-08T09:00:00Z")
    res = api.confirm_case(bundle["case"]["id"], {}, CLS)
    validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_OPEN, expected_status=409)


def test_confirm_before_conference_gate_returns_409(api):
    """PRD §3.4: "Confirmation is the last step of the ordinary track, moving
    the case `NOTICE_ISSUED` → `CONFIRMED` behind two due-process gates
    evaluated in a pinned order, conference first and appeal second. The
    conference gate requires that at least one conference of the case stands
    `HELD` or `WAIVED`, or that the clock has passed the notice's
    `conference_deadline`; otherwise the confirm is rejected with
    `ERR_CONFERENCE_WINDOW_OPEN`."

    Design: Corner/validations/confirm_before_conference_gate_returns_409
    """
    bundle = setup_notice_issued_case(
        guardian_id="gccw", full_name="Stu CCW", clock="2026-05-04T09:00:00Z")
    # No conference, no appeal; both windows still open. The pinned order
    # surfaces the conference gate first.
    set_clock("2026-05-05T09:00:00Z")
    res = api.confirm_case(bundle["case"]["id"], {}, CLS)
    validate_error(res, ApiErrorId.ERR_CONFERENCE_WINDOW_OPEN, expected_status=409)


# ─── Difficulty: conference reschedule cycle ──────────

def _setup_conference_no_show(api):
    """Notice issued at 2026-05-04T09:00 (conference_deadline
    2026-05-07T09:00); conference attempt 1 scheduled 2026-05-05T10:00 and
    recorded NO_SHOW."""
    bundle = setup_notice_issued_case(
        guardian_id="g2", full_name="Stu Conf", date_of_birth="2009-06-01T00:00:00Z",
        clock="2026-05-04T09:00:00Z")
    conf = validate_success(api.create_conference(
        bundle["case"]["id"], create_conference_payload("2026-05-05T10:00:00Z"),
        CLS), 201)
    no_show = validate_success(api.record_conference_outcome(
        conf["id"], create_conference_outcome_payload("NO_SHOW"), CLS), 200)
    return bundle, no_show


def test_conference_no_show_reschedule_returns_to_scheduled(api):
    """PRD §3.4: "an outcome of `NO_SHOW` leaves it eligible for exactly one
    retry: rescheduling a no-show returns it to `SCHEDULED`, replaces
    `scheduled_at`, and increments `attempt_number`".

    Design: Difficulty/non_linear_state_machine/conference_cycle_reschedule_after_no_show
    """
    bundle, no_show = _setup_conference_no_show(api)
    assert no_show["status"] == "NO_SHOW"

    rescheduled = validate_success(api.reschedule_conference(
        no_show["id"], create_conference_payload("2026-05-06T10:00:00Z"),
        CLS), 200)
    assert rescheduled["status"] == "SCHEDULED", (
        "the NO_SHOW -> SCHEDULED loop edge must be taken")
    assert rescheduled["attempt_number"] == 2, (
        f"reschedule increments attempt_number 1 -> 2, got "
        f"{rescheduled['attempt_number']}")
    assert rescheduled["scheduled_at"] == "2026-05-06T10:00:00Z"


def test_conference_cycle_completes_held_after_reschedule(api):
    """PRD §3.4: "Recording an `outcome` of `HELD` or `WAIVED` closes the
    conference successfully from `SCHEDULED`".
    PRD §3.4: "The conference begins `SCHEDULED` with `attempt_number` 1."

    Design: Difficulty/non_linear_state_machine/conference_cycle_reschedule_after_no_show
    """
    bundle, no_show = _setup_conference_no_show(api)
    rescheduled = validate_success(api.reschedule_conference(
        no_show["id"], create_conference_payload("2026-05-06T10:00:00Z"),
        CLS), 200)
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["attempt_number"] == 2

    held = validate_success(api.record_conference_outcome(
        rescheduled["id"], create_conference_outcome_payload("HELD"), CLS), 200)
    assert held["status"] == "HELD"
    assert held["attempt_number"] == 2, (
        "the attempt counter persists through the terminal outcome")


# ─── Difficulty: inclusive appeal deadline ────────────

def _setup_notice_for_appeal_deadline(api):
    """Case NOTICE_ISSUED at 2026-05-04T09:00 via IN_PORTAL; appeal_deadline
    2026-05-09T09:00:00Z."""
    return setup_notice_issued_case(
        guardian_id="g7", full_name="Stu Appeal",
        date_of_birth="2009-11-01T00:00:00Z", demographic_group="ASIAN",
        clock="2026-05-04T09:00:00Z", delivery_method="IN_PORTAL")


def test_appeal_filed_exactly_at_deadline_accepted(api):
    """PRD §3.4: "The filing window closes at the inclusive `appeal_deadline`
    — filing after it draws `ERR_APPEAL_WINDOW_CLOSED`".
    PRD §3.4: "A lawful issuance creates the notice in `ISSUED` status with
    `issued_at` stamped at the clock, an `appeal_deadline` five days after
    issuance inclusive".

    Design: Difficulty/boundary_precision_check/appeal_deadline_day_five_inclusive
    """
    bundle = _setup_notice_for_appeal_deadline(api)
    assert bundle["notice"]["appeal_deadline"] == "2026-05-09T09:00:00Z"

    # Filing at exactly issued_at + 5 days.
    set_clock("2026-05-09T09:00:00Z")
    res = api.file_appeal(
        bundle["case"]["id"],
        create_appeal_payload("filed at the deadline instant"),
        make_parent_guardian_headers("g7"))
    appeal = validate_success(res, 201)
    assert_appeal(appeal)
    assert appeal["status"] == "FILED"


def test_appeal_at_deadline_records_filed_at_equal_to_deadline(api):
    """PRD §3.4: "A `ParentGuardian` files an appeal with `grounds` while the
    case is `NOTICE_ISSUED`; the filing is stamped `filed_at` at the clock and
    `filed_by` with the guardian's `X-User-ID`".
    PRD §3.4: "an `appeal_deadline` five days after issuance inclusive".

    Design: Difficulty/boundary_precision_check/appeal_deadline_day_five_inclusive
    """
    bundle = _setup_notice_for_appeal_deadline(api)
    set_clock("2026-05-09T09:00:00Z")
    appeal = validate_success(api.file_appeal(
        bundle["case"]["id"],
        create_appeal_payload("filed at the deadline instant"),
        make_parent_guardian_headers("g7")), 201)
    assert appeal["filed_at"] == "2026-05-09T09:00:00Z", (
        f"filed_at must equal the clock instant, got {appeal['filed_at']!r}")
    assert appeal["filed_at"] == bundle["notice"]["appeal_deadline"], (
        "the inclusive deadline instant is exactly the notice appeal_deadline")
    assert appeal["filed_by"] == "g7"
