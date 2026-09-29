"""Deep write cascades fired by a single POST.

Two chains are exercised: withdrawal completion, which mints a retention
schedule and mirrors its governing date onto the student, and waived-branch
legal-demand production, which mutates an already-minted schedule instead.
"""
from test_helpers import (
    CLERK,
    COMPLIANCE,
    LEGAL,
    api_client,
    assert_cumulative_file,
    assert_disclosure_log_entry,
    assert_legal_demand,
    assert_millisecond_timestamp,
    assert_retention_schedule,
    assert_student,
    assert_withdrawal,
    complete_withdrawal,
    create_district,
    create_legal_demand,
    create_state_rule,
    create_student,
    create_withdrawal,
    get_cumulative_file_id,
    get_disclosure_log,
    get_file,
    get_retention_schedules,
    place_hold,
    produce_demand,
    release_hold,
    set_clock,
    validate_success,
)

CA_RULE = dict(
    transfer_response_days=10,
    discipline_inclusion_mode="SUSPENSIONS_AND_EXPULSIONS",
    discipline_min_days_removed=10,
    include_pending_investigations=False,
    sped_requires_consent=True,
    amendment_hearing_days=30,
    destruction_min_age_years=5,
    directory_optout_grace_days=14,
    notification_wait_days=7,
)


def _cleared_withdrawal_with_no_holds():
    """One student whose withdrawal is CLEARED with both holds released, the
    cumulative file never touched, and the clock parked at the completion
    instant."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    student = create_student(
        district["id"],
        first_name="Hana",
        last_name="Sorensen",
        dob="2012-12-01",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-hana",
    )
    file_id = get_cumulative_file_id(student["id"])
    withdrawal = create_withdrawal(
        student["id"],
        effective_date="2026-08-14",
        destination_district_code="RECV01",
        withdrawal_reason="TRANSFER_OUT",
    )
    place_hold(withdrawal["id"], "LIBRARY_FINE")
    place_hold(withdrawal["id"], "MEAL_ACCOUNT")
    release_hold(withdrawal["id"], "MEAL_ACCOUNT")
    cleared = release_hold(withdrawal["id"], "LIBRARY_FINE")
    assert cleared["status"] == "CLEARED"
    assert cleared["hold_count"] == 0
    set_clock("2026-08-15T12:00:00Z")
    return student, file_id, withdrawal


def _get_student(student_id):
    return validate_success(api_client.get_student(student_id, CLERK))


class TestWithdrawalCompletionCascade:
    def test_one_completion_call_fires_all_five_links(self):
        """Completing a cleared withdrawal must, in one request, close the
        withdrawal, exit the student, start the file, mint the retention
        schedule with its computed anchors, and mirror the governing
        destruction date onto the student.

        PRD: "On success, five effects fire in order and all of them are visible to the very next read."

        Design: Difficulty/transitive_cascade/withdrawal_completion_five_link_cascade
        """
        student, file_id, withdrawal = _cleared_withdrawal_with_no_holds()

        completed = complete_withdrawal(withdrawal["id"])

        assert_withdrawal(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["hold_count"] == 0
        assert completed["active_hold_types"] == []
        assert completed["completed_at"] == "2026-08-15T12:00:00.000Z"

        exited = _get_student(student["id"])
        assert_student(exited)
        assert exited["enrollment_status"] == "WITHDRAWN"
        assert exited["exit_effective_date"] == "2026-08-14"

        started = get_file(file_id)
        assert_cumulative_file(started)
        assert started["assembly_status"] == "IN_ASSEMBLY"
        assert started["completeness_pct"] == 0.0

        schedules = get_retention_schedules(file_id, headers=COMPLIANCE)
        assert len(schedules) == 1, (
            f"exactly one retention schedule must be minted, got {len(schedules)}"
        )
        schedule = schedules[0]
        assert_retention_schedule(schedule)
        assert schedule["status"] == "ACTIVE"
        assert schedule["exit_anchor_at"] == "2026-08-14T00:00:00.000Z"
        assert schedule["last_activity_at"] == "2026-08-14T00:00:00.000Z"
        assert schedule["destruction_min_age_years"] == 5
        assert schedule["destruction_eligible_at"] == "2031-08-14T00:00:00.000Z"
        assert schedule["exit_anchored_eligible_at"] == "2031-08-14T00:00:00.000Z"

        assert exited["records_disposition_date"] == "2031-08-14T00:00:00.000Z"

    def test_the_schedule_and_the_disposition_date_arrive_only_on_completion(self):
        """Before the completion call the file has no retention schedule and
        the student has no records disposition date at all, so the fourth and
        fifth links are attributable to that single POST and not to enrolment
        or to opening the withdrawal.

        PRD: "No retention schedule exists yet; that arrives only when a withdrawal completes."

        Design: Difficulty/transitive_cascade/withdrawal_completion_five_link_cascade
        """
        student, file_id, withdrawal = _cleared_withdrawal_with_no_holds()

        assert get_retention_schedules(file_id, headers=COMPLIANCE) == []
        before = _get_student(student["id"])
        assert before["records_disposition_date"] is None
        assert before["exit_effective_date"] is None
        assert before["enrollment_status"] == "WITHDRAWAL_PENDING"
        assert get_file(file_id)["assembly_status"] == "NOT_STARTED"

        complete_withdrawal(withdrawal["id"])

        after_schedules = get_retention_schedules(file_id, headers=COMPLIANCE)
        assert len(after_schedules) == 1
        after = _get_student(student["id"])
        assert after["records_disposition_date"] == (
            after_schedules[0]["destruction_eligible_at"]
        )
        assert after["records_disposition_date"] == "2031-08-14T00:00:00.000Z"


def _withdrawn_student_with_a_waived_demand():
    """A student already exited on 2026-08-14, so a retention schedule exists,
    then an ex parte demand docketed at 2026-10-02T08:30:00Z whose notification
    duty is waived."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    student = create_student(
        district["id"],
        first_name="Ivo",
        last_name="Marchetti",
        dob="2011-07-07",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-ivo",
    )
    file_id = get_cumulative_file_id(student["id"])
    withdrawal = create_withdrawal(
        student["id"],
        effective_date="2026-08-14",
        destination_district_code="RECV01",
        withdrawal_reason="MOVED",
    )
    complete_withdrawal(withdrawal["id"])
    schedules = get_retention_schedules(file_id, headers=COMPLIANCE)
    assert len(schedules) == 1
    schedule = schedules[0]
    assert schedule["destruction_eligible_at"] == "2031-08-14T00:00:00.000Z"

    set_clock("2026-10-02T08:30:00Z")
    demand = create_legal_demand(
        student["id"],
        demand_type="EX_PARTE_ORDER",
        issuing_authority="Superior Court of CA, County of Alta",
        case_reference="EX-2026-4417",
        production_scope=["ACADEMIC", "DISCIPLINE"],
        notification_waived=True,
        waiver_basis="EX_PARTE_COURT_ORDER",
    )
    return student, file_id, schedule, demand


def _get_schedule(schedule_id):
    return validate_success(api_client.get_retention_schedule(schedule_id, COMPLIANCE))


class TestWaivedLegalDemandProductionCascade:
    def test_waived_production_logs_the_disclosure_and_moves_the_governing_date(self):
        """Production on the waived fork must skip NOTIFIED entirely, append
        exactly one LEGAL_DEMAND log row at the production instant, drag the
        schedule's activity and governing eligibility instants onto it, and
        re-mirror the student's disposition date.

        PRD: "And because a new disclosure entry exists, the student's retention schedule has its `last_activity_at` set to that entry's `disclosed_at` and its `destruction_eligible_at` recomputed, and because that date changed, the student's `records_disposition_date` is re-mirrored from it."

        Design: Difficulty/transitive_cascade/legal_demand_production_four_link_cascade
        """
        student, file_id, schedule, demand = _withdrawn_student_with_a_waived_demand()

        produced = produce_demand(demand["id"], 40)

        assert_legal_demand(produced)
        assert produced["status"] == "PRODUCED"
        assert produced["produced_at"] == "2026-10-02T08:30:00.000Z"
        assert produced["produced_page_count"] == 40
        assert produced["notification_sent_at"] is None
        assert produced["notified_party"] is None

        log = get_disclosure_log(student["id"], headers=LEGAL)
        assert len(log) == 1, f"exactly one disclosure entry expected, got {len(log)}"
        entry = log[0]
        assert_disclosure_log_entry(entry)
        assert entry["disclosure_type"] == "LEGAL_DEMAND"
        assert entry["source_type"] == "LEGAL_DEMAND"
        assert entry["source_id"] == demand["id"]
        assert entry["page_count"] == 40
        assert entry["disclosed_at"] == "2026-10-02T08:30:00.000Z"
        assert entry["logged_by_user_id"] == "legal-1"

        moved = _get_schedule(schedule["id"])
        assert_retention_schedule(moved)
        assert moved["last_activity_at"] == "2026-10-02T08:30:00.000Z"
        assert moved["destruction_eligible_at"] == "2031-10-02T08:30:00.000Z"

        assert _get_student(student["id"])["records_disposition_date"] == (
            "2031-10-02T08:30:00.000Z"
        )

    def test_production_mutates_the_existing_schedule_and_leaves_the_advisory_date_frozen(self):
        """The chain must move the single pre-existing schedule rather than mint
        a second one, and the advisory date stays pinned to the exit anchor
        while the governing date runs five years past the production instant.

        PRD: "The advisory date, `exit_anchored_eligible_at`, is `exit_anchor_at` advanced by the same number of whole years."

        Design: Difficulty/transitive_cascade/legal_demand_production_four_link_cascade
        """
        student, file_id, schedule, demand = _withdrawn_student_with_a_waived_demand()
        assert schedule["last_activity_at"] == "2026-08-14T00:00:00.000Z"

        produce_demand(demand["id"], 40)

        schedules = get_retention_schedules(file_id, headers=COMPLIANCE)
        assert len(schedules) == 1, (
            "production must mutate the existing retention schedule, not mint another"
        )
        assert schedules[0]["id"] == schedule["id"]
        assert schedules[0]["status"] == "ACTIVE"
        assert schedules[0]["exit_anchor_at"] == "2026-08-14T00:00:00.000Z"
        assert schedules[0]["exit_anchored_eligible_at"] == "2031-08-14T00:00:00.000Z"
        assert schedules[0]["destruction_eligible_at"] == "2031-10-02T08:30:00.000Z"
        assert_millisecond_timestamp(schedules[0]["last_activity_at"], "last_activity_at")
        assert schedules[0]["last_activity_at"] == "2026-10-02T08:30:00.000Z"
