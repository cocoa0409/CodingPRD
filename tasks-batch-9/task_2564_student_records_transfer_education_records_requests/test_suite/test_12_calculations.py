"""Derived quantities read back at the values the arithmetic demands.

Packet page counts against the summary-substitution threshold, business-day
windows that skip weekends, age arithmetic on the birthday itself, and retention
dates projected in whole years from the anchors the contract names.
"""
from test_helpers import (
    CLERK,
    COMPLIANCE,
    api_client,
    assert_cumulative_file,
    assert_file_component,
    assert_page_custody_identity,
    assert_records_request,
    assert_retention_schedule,
    assert_student,
    certify_component,
    collect_component,
    complete_withdrawal,
    create_district,
    create_records_request,
    create_state_rule,
    create_student,
    create_withdrawal,
    get_components,
    get_cumulative_file_id,
    get_file,
    get_retention_schedules,
    mark_ready_request,
    set_clock,
    validate_request,
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
TX_RULE = dict(
    transfer_response_days=30,
    discipline_inclusion_mode="ALL_INCIDENTS",
    discipline_min_days_removed=10,
    include_pending_investigations=True,
    sped_requires_consent=False,
    amendment_hearing_days=45,
    destruction_min_age_years=7,
    directory_optout_grace_days=10,
    notification_wait_days=3,
)


def _both_rules():
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)


def _get_student(student_id):
    return validate_success(api_client.get_student(student_id, CLERK))


def _certify_pages(file_id, pages):
    """Collect and certify each named component at the given page and redaction
    counts, returning the component rows by type."""
    components = get_components(file_id)
    for component_type, page_count, redactions in pages:
        component_id = components[component_type]["id"]
        collect_component(file_id, component_id, page_count, redactions)
        certify_component(file_id, component_id)
    return components


def _snapshot_for(student_id, requesting_district_id, responding_district_id, reference):
    """File, validate and snapshot one request over the student's current file."""
    file_id = get_cumulative_file_id(student_id)
    request = create_records_request(
        student_id,
        requesting_district_id,
        responding_district_id,
        authorization_reference=reference,
    )
    validate_request(request["id"])
    return mark_ready_request(request["id"], file_id)


def _two_siblings_at_five_hundred_and_five_hundred_and_one():
    """Yara's three certified components total exactly 500 raw pages; Zeke's
    total 501, differing only in the discipline component's page count."""
    _both_rules()
    sending = create_district("SEND01", state_code="CA", name="Sending Unified")
    receiving = create_district("RECV01", state_code="TX", name="Receiving Unified")
    yara = create_student(
        sending["id"],
        first_name="Yara",
        last_name="Kovac",
        dob="2011-02-02",
        grade_level=10,
        has_iep=False,
        guardian_user_id="guardian-yara",
    )
    zeke = create_student(
        sending["id"],
        first_name="Zeke",
        last_name="Kovac",
        dob="2011-03-03",
        grade_level=10,
        has_iep=False,
        guardian_user_id="guardian-zeke",
    )
    _certify_pages(
        get_cumulative_file_id(yara["id"]),
        (("ACADEMIC", 300, 0), ("HEALTH", 150, 0), ("DISCIPLINE", 50, 0)),
    )
    _certify_pages(
        get_cumulative_file_id(zeke["id"]),
        (("ACADEMIC", 300, 0), ("HEALTH", 150, 0), ("DISCIPLINE", 51, 0)),
    )
    return sending, receiving, yara, zeke


class TestSummarySubstitutionThreshold:
    def test_exactly_five_hundred_raw_pages_travel_whole(self):
        """The test is strictly greater-than, so a packet sitting exactly on the
        threshold keeps all fifty of its discipline pages and reports the raw
        figure unchanged.

        PRD: "Otherwise the packet page count is the raw figure unchanged."

        Design: Corner/calculations/packet_page_count_threshold_at_500_and_501
        """
        sending, receiving, yara, _zeke = (
            _two_siblings_at_five_hundred_and_five_hundred_and_one()
        )

        ready = _snapshot_for(
            yara["id"], receiving["id"], sending["id"], "ENR-2026-9020"
        )

        assert_records_request(ready)
        assert ready["status"] == "READY_FOR_RELEASE"
        assert ready["packet_status"] == "SNAPSHOT"
        assert ready["packet_page_count"] == 500

        file_read = get_file(get_cumulative_file_id(yara["id"]))
        assert_cumulative_file(file_read)
        assert file_read["total_page_count"] == 500
        assert file_read["disclosable_page_count"] == 500

    def test_one_page_over_swaps_the_discipline_pages_for_three_summary_pages(self):
        """501 raw pages trip the substitution: the 51 discipline pages come out
        and three summary pages go in, giving 453 — a figure below the threshold
        that is never re-tested.

        PRD: "When the raw figure is strictly greater than 500 pages, the packet substitutes a summary for the disciplinary material: the packet page count becomes the raw figure minus the discipline pages, plus three pages of summary."

        Design: Corner/calculations/packet_page_count_threshold_at_500_and_501
        """
        sending, receiving, _yara, zeke = (
            _two_siblings_at_five_hundred_and_five_hundred_and_one()
        )

        ready = _snapshot_for(
            zeke["id"], receiving["id"], sending["id"], "ENR-2026-9021"
        )

        assert_records_request(ready)
        assert ready["status"] == "READY_FOR_RELEASE"
        assert ready["packet_page_count"] == 453, (
            "501 raw pages less 51 discipline pages plus 3 summary pages"
        )

        file_read = get_file(get_cumulative_file_id(zeke["id"]))
        assert file_read["total_page_count"] == 501
        assert file_read["disclosable_page_count"] == 501
        assert_page_custody_identity(file_read)


class TestPacketCountsOnlyCertifiedNetOfRedactions:
    def test_an_uncertified_two_hundred_page_component_contributes_nothing(self):
        """The file's own disclosable total is 360, but the packet counts only the
        three certified components net of their redactions and lands on 160 with
        the collected special-education pages left out entirely.

        PRD: "Only `CERTIFIED` components contribute; `PENDING`, `COLLECTED`, and `EXCLUDED` components contribute nothing, which is precisely why excluding a certified component both reopens the request and changes the page count of the next snapshot."

        Design: Corner/calculations/packet_page_count_counts_only_certified_net_of_redactions
        """
        _both_rules()
        sending = create_district("SEND01", state_code="CA", name="Sending Unified")
        receiving = create_district("RECV01", state_code="TX", name="Receiving Unified")
        student = create_student(
            sending["id"],
            first_name="Anya",
            last_name="Sokolov",
            dob="2011-04-14",
            grade_level=10,
            has_iep=False,
            guardian_user_id="guardian-anya",
        )
        file_id = get_cumulative_file_id(student["id"])
        components = get_components(file_id)
        collect_component(file_id, components["SPECIAL_EDUCATION"]["id"], 200, 0)
        _certify_pages(
            file_id, (("ACADEMIC", 100, 10), ("HEALTH", 50, 0), ("DISCIPLINE", 20, 0))
        )

        ready = _snapshot_for(
            student["id"], receiving["id"], sending["id"], "ENR-2026-9022"
        )

        assert_records_request(ready)
        assert ready["status"] == "READY_FOR_RELEASE"
        assert ready["packet_page_count"] == 160, (
            "100 + 50 + 20 certified pages less the 10 redacted ones"
        )

        file_read = get_file(file_id)
        assert_cumulative_file(file_read)
        assert file_read["assembly_status"] == "COMPLETE"
        assert file_read["completeness_pct"] == 100.0
        assert file_read["total_page_count"] == 370
        assert file_read["included_page_count"] == 370
        assert file_read["excluded_page_count"] == 0
        assert file_read["disclosable_page_count"] == 360
        assert_page_custody_identity(file_read)

        left_out = get_components(file_id)["SPECIAL_EDUCATION"]
        assert_file_component(left_out)
        assert left_out["status"] == "COLLECTED"
        assert left_out["is_required"] is False


class TestStandardWindowCountsBusinessDaysOnly:
    def test_thirty_business_days_from_a_monday_land_on_the_fourteenth_of_september(self):
        """The receipt day itself is never counted and only Saturdays and Sundays
        are skipped, so a Monday 3 August receipt with a thirty-day budget resolves
        to 14 September rather than the naive 2 September.

        PRD: "**Business-day offsets** advance a cursor one calendar day at a time from an anchor instant, counting only days that fall on Monday, Tuesday, Wednesday, Thursday, or Friday, until the required number of business days has been counted; the anchor's own calendar day is never counted even when it is itself a business day, and no holiday calendar exists, so Saturday and Sunday are the only skipped weekdays."

        Design: Corner/calculations/standard_window_skips_weekends_and_never_counts_anchor_day
        """
        _both_rules()
        responding = create_district(
            "TXD01", state_code="TX", name="Texas Holding District"
        )
        requesting = create_district(
            "CAD01", state_code="CA", name="California Receiving District"
        )
        student = create_student(
            responding["id"],
            first_name="Bram",
            last_name="Delacroix",
            dob="2011-05-15",
            grade_level=10,
            has_iep=False,
            guardian_user_id="guardian-bram",
        )
        set_clock("2026-08-03T00:00:00Z")

        request = create_records_request(
            student["id"],
            requesting["id"],
            responding["id"],
            request_priority="STANDARD",
            includes_special_education=False,
            authorization_reference="ENR-2026-9023",
        )

        assert_records_request(request)
        assert request["received_at"] == "2026-08-03T00:00:00.000Z"
        assert request["statutory_days_allowed"] == 30, (
            "the responding TX rule supplies the budget"
        )
        assert request["statutory_due_at"] == "2026-09-14T23:59:59.999Z"
        assert request["is_overdue"] is False


def _twins_born_a_day_apart():
    """Two twelfth-graders, one born 2008-08-01 and one 2008-08-02, read at the
    default clock 2026-08-01T00:00:00Z."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    on_birthday = create_student(
        district["id"],
        first_name="Cato",
        last_name="Bianchi",
        dob="2008-08-01",
        grade_level=12,
        has_iep=False,
        guardian_user_id="guardian-cato",
        student_user_id="student-cato",
    )
    day_short = create_student(
        district["id"],
        first_name="Dov",
        last_name="Bianchi",
        dob="2008-08-02",
        grade_level=12,
        has_iep=False,
        guardian_user_id="guardian-dov",
        student_user_id="student-dov",
    )
    return on_birthday, day_short


class TestEligibleStudentStatusOnTheBirthday:
    def test_the_birthday_itself_already_counts_and_a_day_short_does_not(self):
        """Eighteen whole years are complete on the birthday instant, so the
        student born on 2008-08-01 is eligible at 2026-08-01T00:00:00Z while the
        twin born a day later is not.

        PRD: "`is_eligible_student` is true when that whole-year count is at least 18, so eligibility begins on the birthday itself: a student born on 2008-08-01 is eligible from the instant `2026-08-01T00:00:00.000Z` and is not eligible at `2026-07-31T23:59:59.999Z`."

        Design: Corner/calculations/eligible_student_status_inclusive_on_eighteenth_birthday
        """
        on_birthday, day_short = _twins_born_a_day_apart()

        eligible = _get_student(on_birthday["id"])
        assert_student(eligible)
        assert eligible["is_eligible_student"] is True
        assert eligible["student_user_id"] == "student-cato"

        not_yet = _get_student(day_short["id"])
        assert_student(not_yet)
        assert not_yet["is_eligible_student"] is False
        assert not_yet["student_user_id"] == "student-dov"

    def test_moving_the_clock_one_day_flips_only_the_younger_twin(self):
        """The flag is recomputed on every read rather than frozen at enrolment, so
        the same stored row reads false on the first and true on the second.

        PRD: "Whether a student or their parent holds the family's rights is a pure function of age and the clock, recomputed on every read of the student and on every mutation, and again on every authorization check for an endpoint that admits the `Parent` or `EligibleStudent` role."

        Design: Corner/calculations/eligible_student_status_inclusive_on_eighteenth_birthday
        """
        on_birthday, day_short = _twins_born_a_day_apart()
        assert _get_student(day_short["id"])["is_eligible_student"] is False

        set_clock("2026-08-02T00:00:00Z")

        assert _get_student(day_short["id"])["is_eligible_student"] is True
        assert _get_student(on_birthday["id"])["is_eligible_student"] is True


def _texas_student_exited_on_the_fourteenth():
    """A TX student whose withdrawal is completed on 2026-08-16 at 09:00 with no
    disclosures and no certifications anywhere on the file."""
    _both_rules()
    district = create_district("TXD01", state_code="TX", name="Texas Holding District")
    student = create_student(
        district["id"],
        first_name="Esti",
        last_name="Marchetti",
        dob="2011-06-16",
        grade_level=10,
        has_iep=False,
        guardian_user_id="guardian-esti",
    )
    file_id = get_cumulative_file_id(student["id"])
    withdrawal = create_withdrawal(
        student["id"],
        effective_date="2026-08-14",
        destination_district_code="TXD01",
        withdrawal_reason="MOVED",
    )
    set_clock("2026-08-16T09:00:00Z")
    completed = complete_withdrawal(withdrawal["id"])
    assert completed["status"] == "COMPLETED"
    schedules = get_retention_schedules(file_id, headers=COMPLIANCE)
    assert len(schedules) == 1, f"exactly one schedule is minted, got {len(schedules)}"
    return student, file_id, schedules[0]


class TestRetentionScheduleCopiesTheGoverningStateRule:
    def test_the_schedule_takes_the_seven_year_texas_rule_not_a_default(self):
        """The minted schedule copies destruction_min_age_years from the state rule
        governing the student's own district at that moment, so a TX file carries
        seven years and opens in ACTIVE with nothing destroyed.

        PRD: "Fourth, because the file entered `IN_ASSEMBLY` by that route, a **retention schedule** is minted for it with `cumulative_file_id` naming the file, `status` `ACTIVE`, `exit_anchor_at` set to the student's `exit_effective_date` at `00:00:00.000Z`, `destruction_min_age_years` copied from the governing state rule at that moment, and `last_activity_at`, `destruction_eligible_at`, and `exit_anchored_eligible_at` computed as described in the retention narrative below; `destruction_method`, `certification_note`, and `destroyed_at` all begin null."

        Design: Corner/calculations/retention_schedule_copies_state_destruction_min_age_years
        """
        _student, _file_id, schedule = _texas_student_exited_on_the_fourteenth()

        assert_retention_schedule(schedule)
        assert schedule["destruction_min_age_years"] == 7
        assert schedule["status"] == "ACTIVE"
        assert schedule["exit_anchor_at"] == "2026-08-14T00:00:00.000Z"
        assert schedule["last_activity_at"] == "2026-08-14T00:00:00.000Z"
        assert schedule["destruction_method"] is None
        assert schedule["certification_note"] is None
        assert schedule["destroyed_at"] is None

    def test_both_anchors_project_seven_whole_years_onto_the_same_instant(self):
        """With no disclosure and no certification the latest-activity anchor is
        the exit anchor itself, so the governing and advisory dates coincide at
        2033-08-14T00:00:00.000Z and the student's disposition date mirrors it.

        PRD: "The governing eligibility date, `destruction_eligible_at`, is `last_activity_at` advanced by `destruction_min_age_years` whole years, using the year arithmetic of §2.5 with its February 29 fallback to the 28th and its exact preservation of the anchor's time of day."

        Design: Corner/calculations/retention_schedule_copies_state_destruction_min_age_years
        """
        student, _file_id, schedule = _texas_student_exited_on_the_fourteenth()

        assert schedule["destruction_eligible_at"] == "2033-08-14T00:00:00.000Z"
        assert schedule["exit_anchored_eligible_at"] == "2033-08-14T00:00:00.000Z"

        mirrored = _get_student(student["id"])
        assert mirrored["records_disposition_date"] == "2033-08-14T00:00:00.000Z"
        assert mirrored["exit_effective_date"] == "2026-08-14"
