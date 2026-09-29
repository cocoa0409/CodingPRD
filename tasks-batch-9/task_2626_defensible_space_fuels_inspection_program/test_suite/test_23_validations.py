"""Conditional and cross-entity validation: lead time, eligibility, half-open
windows, per-day capacity and the ladder inside inspection completion."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    EPOCH_CLOCK_UTC,
    ERR_CONTRACTOR_CAPACITY_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_MISSING_VENDOR_INVOICE,
    ERR_NOTICE_LEAD_TIME_VIOLATION,
    ERR_PARCEL_NOT_INSPECTED,
    ERR_PROGRAM_WINDOW_CLOSED,
    ERR_ZONE_COVERAGE_INCOMPLETE,
    PROGRAM_TYPE_CHIPPER,
    PROGRAM_TYPE_GRANT,
    add_zone,
    add_zones,
    advance_cycle,
    assert_2dp,
    assert_award,
    assert_hours,
    assert_instant,
    assert_posture,
    assert_program_capacity,
    assert_risk,
    assert_version,
    authorize_abatement,
    award_order,
    award_payload,
    complete_inspection,
    complete_inspection_payload,
    create_contractor,
    create_inspector,
    create_parcel,
    create_program,
    decision_payload,
    enroll,
    enrollment_payload,
    get_certificate,
    get_contractor,
    get_inspection,
    get_order,
    get_parcel,
    get_program,
    list_enrollments,
    list_notices,
    list_zone_evaluations,
    notice_for_parcel,
    notice_service_payload,
    open_certificate,
    open_cycle,
    schedule_inspection,
    serve_notice,
    set_clock,
)
from test_helpers.test_users import (
    FIRE_MARSHAL_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_inspector_headers,
)


class TestNoticeLeadTimeFloor:
    """The floor is measured in whole days from the logical clock to the visit."""

    def test_a_visit_seven_days_out_cannot_be_noticed(self, client):
        """Serving notice on an inspection only 7 days away is refused and the
        inspection stays un-noticed.

        PRD: "The service is refused unless the whole days remaining between the
        logical clock and scheduled_start_utc are at least the governing cycle's
        notice_lead_days; falling short answers ERR_NOTICE_LEAD_TIME_VIOLATION."

        PRD: "notice_lead_days is the minimum number of whole days that must separate
        an owner notice from the visit it announces, and it defaults to 10 when the
        request omits it."

        PRD: "A ProgramAdmin serves the owner notice by declaring the notice_method
        used - IN_PERSON, CERTIFIED_MAIL or EMAIL - which advances the inspection
        SCHEDULED -> NOTICED and stamps notice_sent_at_utc with the logical clock."

        Design: Corner/validations/notice_lead_time_violation_under_ten_days
        """
        cycle = open_cycle(client)
        assert cycle["notice_lead_days"] == 10, "the district default"
        inspector = create_inspector(client)
        parcel = create_parcel(client)

        # Booking the visit is legal; only the notice call is too late.
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-08T15:00:00Z",
            scheduled_end_utc="2026-08-08T17:00:00Z",
        )
        assert inspection["status"] == "SCHEDULED"

        validate_error(
            client.serve_notice(
                inspection["id"],
                notice_service_payload("CERTIFIED_MAIL"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_NOTICE_LEAD_TIME_VIOLATION,
            422,
        )

        reread = get_inspection(client, inspection["id"])
        assert reread["status"] == "SCHEDULED"
        assert reread["notice_method"] is None
        assert reread["notice_sent_at_utc"] is None
        _rows, meta = list_notices(client, parcel_id=parcel["id"])
        assert meta["total_count"] == 0

    def test_exactly_ten_whole_days_is_enough_and_one_second_less_is_not(
        self, client
    ):
        """A start exactly 10 days out is served; a start one second earlier leaves
        only 9 whole days and is refused.

        PRD: "The service is refused unless the whole days remaining between the
        logical clock and scheduled_start_utc are at least the governing cycle's
        notice_lead_days; falling short answers ERR_NOTICE_LEAD_TIME_VIOLATION."

        PRD: "With the district default of 10 days, an inspector cannot be sent to a
        gate nine days after the letter went out."

        PRD: "version, an integer that starts at 1 when the resource is created and
        increments by exactly 1 on every successful mutation of that resource."

        Design: Corner/validations/notice_lead_time_satisfied_at_exactly_ten_days
        """
        cycle = open_cycle(client)
        on_time_inspector = create_inspector(client)
        late_inspector = create_inspector(client)

        on_time = schedule_inspection(
            client,
            create_parcel(client)["id"],
            cycle["id"],
            on_time_inspector["id"],
            scheduled_start_utc="2026-08-11T00:00:00Z",
            scheduled_end_utc="2026-08-11T02:00:00Z",
        )
        noticed = serve_notice(client, on_time["id"], "IN_PERSON")
        assert noticed["status"] == "NOTICED"
        assert noticed["notice_method"] == "IN_PERSON"
        assert_instant(noticed["notice_sent_at_utc"], EPOCH_CLOCK_UTC)
        assert_version(noticed, 2)

        # One second earlier is nine whole days, not ten.
        one_second_short = schedule_inspection(
            client,
            create_parcel(client)["id"],
            cycle["id"],
            late_inspector["id"],
            scheduled_start_utc="2026-08-10T23:59:59Z",
            scheduled_end_utc="2026-08-11T01:59:59Z",
        )
        validate_error(
            client.serve_notice(
                one_second_short["id"],
                notice_service_payload("IN_PERSON"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_NOTICE_LEAD_TIME_VIOLATION,
            422,
        )
        assert get_inspection(client, one_second_short["id"])["status"] == "SCHEDULED"


class TestCertificateEligibilityIsCrossEntity:
    """The decision endpoint reads a field that lives on the parcel."""

    def test_issue_on_a_never_inspected_parcel_is_refused_but_deny_is_not(
        self, client
    ):
        """A PENDING_INSPECTION parcel answers ERR_PARCEL_NOT_INSPECTED on ISSUE,
        while DENY on the very same request succeeds.

        PRD: "Issuance is only available on a parcel with a clean posture: its
        compliance_status must be COMPLIANT or EXEMPT, and it must hold no violation
        notice standing in ISSUED, EXTENDED, OVERDUE or ABATEMENT_AUTHORIZED."

        PRD: "Error selection between the two failure modes is unambiguous - a parcel
        whose compliance_status is PENDING_INSPECTION answers ERR_PARCEL_NOT_INSPECTED,
        and every other failing case, including a NON_COMPLIANT or ABATEMENT_PENDING
        posture and the open-notice case, answers ERR_OPEN_VIOLATION_EXISTS."

        PRD: "A DENY decision moves the certificate REQUESTED -> DENIED, records the
        supplied text as decision_note, and leaves every snapshot field null."

        PRD: "Alongside it the parcel keeps open_violation_count, initialised to 0,
        and last_passed_inspection_at_utc, which holds the completion instant of the
        most recent passing inspection on the parcel and stays null until one exists."

        Design: Corner/validations/certificate_issue_on_never_inspected_parcel_rejected
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        parcel = create_parcel(client)
        assert_posture(parcel, "PENDING_INSPECTION", open_violation_count=0)
        assert parcel["last_passed_inspection_at_utc"] is None

        certificate = open_certificate(client, parcel["id"])
        assert certificate["status"] == "REQUESTED"

        validate_error(
            client.certificate_decision(
                certificate["id"],
                decision_payload("ISSUE"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_PARCEL_NOT_INSPECTED,
            409,
        )

        held = get_certificate(client, certificate["id"])
        assert held["status"] == "REQUESTED"
        for field in (
            "issued_at_utc",
            "expires_at_utc",
            "snapshot_risk_class",
            "snapshot_compliance_status",
        ):
            assert held[field] is None, "%s must still be null" % field

        # The cross-entity guard covers issuance only.
        denied = validate_success(
            client.certificate_decision(
                certificate["id"],
                decision_payload("DENY", "Parcel has never been inspected"),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )
        assert denied["status"] == "DENIED"
        assert denied["decision_note"] == "Parcel has never been inspected"


class TestHalfOpenServiceWindow:
    """The programme window admits its start instant and refuses its end instant."""

    def test_one_second_inside_the_window_enrolls_and_the_end_instant_does_not(
        self, client
    ):
        """An enrollment at 2026-09-29T23:59:59Z is admitted; the same call with the
        clock standing on service_window_end_utc is refused.

        PRD: "Enrollment is accepted only while the logical clock lies inside the
        program's half-open service window, at or after service_window_start_utc and
        strictly before service_window_end_utc; a clock before the start or at or
        after the end answers ERR_PROGRAM_WINDOW_CLOSED."

        PRD: "Approval sets reserved_amount_cents to award_cents for a grant, debits
        the program's budget_remaining_cents by that same amount, increments
        reserved_slots by 1, leaves waitlist_position null, and advances the program's
        version by 1."

        PRD: "Optimistic concurrency - expected_parcel_version matches the current
        Parcel.version on parcel update and on discretionary notice issuance;
        expected_program_version matches the current SupportProgram.version on
        enrollment creation."

        Design: Corner/validations/enrollment_at_exclusive_window_end_rejected
        """
        cycle = open_cycle(client)
        program = create_program(
            client,
            cycle["id"],
            PROGRAM_TYPE_CHIPPER,
            budget_total_cents=0,
            capacity_slots=3,
            service_window_start_utc="2026-08-01T00:00:00Z",
            service_window_end_utc="2026-09-30T00:00:00Z",
        )
        first_parcel = create_parcel(client)
        second_parcel = create_parcel(client)

        set_clock(client, "2026-09-29T23:59:59Z")
        admitted = enroll(
            client, program["id"], first_parcel["id"], program["version"]
        )
        assert admitted["status"] == "APPROVED"

        current = get_program(client, program["id"])
        assert_version(current, 2)
        assert_program_capacity(current, 0, reserved_slots=1)

        set_clock(client, "2026-09-30T00:00:00Z")
        validate_error(
            client.create_enrollment(
                enrollment_payload(
                    program["id"], second_parcel["id"], current["version"]
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_PROGRAM_WINDOW_CLOSED,
            409,
        )

        _rows, meta = list_enrollments(client, support_program_id=program["id"])
        assert meta["total_count"] == 1, "the refused enrollment was never created"
        after = get_program(client, program["id"])
        assert_program_capacity(after, 0, reserved_slots=1)
        assert_version(after, current["version"])


def _two_authorized_orders(client):
    """Two parcels in one cycle carried all the way to AUTHORIZED abatement orders.

    Both citations are issued at the epoch, fall due on 2026-09-05 and are swept to
    OVERDUE by a single advance at 2026-10-01.
    """
    cycle = open_cycle(client)
    inspector = create_inspector(client)
    notices = []
    for start, end in (
        ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"),
        ("2026-08-21T09:00:00Z", "2026-08-21T11:00:00Z"),
    ):
        parcel = create_parcel(client)
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc=start,
            scheduled_end_utc=end,
        )
        serve_notice(client, inspection["id"])
        add_zones(client, inspection["id"], inspector["id"])
        complete_inspection(client, inspection["id"], inspector["id"], result="FAIL")
        notices.append(notice_for_parcel(client, parcel["id"]))

    set_clock(client, "2026-10-01T00:00:00Z")
    advance_cycle(client, cycle["id"])
    return [authorize_abatement(client, notice["id"]) for notice in notices]


class TestContractorDailyCapacity:
    """The cap is an aggregate over calendar dates, not a pairwise overlap test."""

    def test_a_second_award_on_the_same_date_is_refused_and_the_next_date_is_not(
        self, client
    ):
        """With max_daily_orders 1 a non-overlapping second job on the same UTC date
        is refused, and the identical job one date later is accepted.

        PRD: "Finally, for every UTC calendar date the new closed window touches, the
        count of that contractor's AWARDED and WORK_COMPLETE orders whose closed
        windows cover that same date must remain at or below max_daily_orders;
        exceeding it on any single date answers ERR_CONTRACTOR_CAPACITY_EXCEEDED."

        PRD: "This is an aggregate-per-day test, not a pairwise one: with the default
        cap of 2, a third overlapping job on the same Tuesday is refused even though
        no two of the three windows are identical."

        PRD: "A contractor's committed_crew_hours must always equal the sum of
        crew_hours across that contractor's orders whose status is AWARDED or
        WORK_COMPLETE; its completed_crew_hours is a lifetime tally that only ever
        grows."

        PRD: "a max_daily_orders ceiling on how many jobs the crew can hold on any one
        calendar day, which must be at least 1 and defaults to 2."

        Design: Corner/validations/contractor_daily_order_capacity_counted_per_calendar_date
        """
        first_order, second_order = _two_authorized_orders(client)
        contractor = create_contractor(client, max_daily_orders=1)
        assert contractor["max_daily_orders"] == 1, "supplied, not the default 2"

        awarded = award_order(
            client,
            first_order["id"],
            contractor["id"],
            crew_hours=4.0,
            work_start_utc="2026-10-05T08:00:00Z",
            work_end_utc="2026-10-05T12:00:00Z",
        )
        assert awarded["status"] == "AWARDED"
        assert_hours(
            get_contractor(client, contractor["id"])["committed_crew_hours"], 4.0
        )

        # 14:00-18:00 shares no instant with 08:00-12:00, so the window test passes
        # and the per-date count is what refuses the award.
        validate_error(
            client.award_order(
                second_order["id"],
                award_payload(
                    contractor["id"],
                    4.0,
                    "2026-10-05T14:00:00Z",
                    "2026-10-05T18:00:00Z",
                ),
                headers=FIRE_MARSHAL_HEADERS,
            ),
            ERR_CONTRACTOR_CAPACITY_EXCEEDED,
            409,
        )

        refused = get_order(client, second_order["id"])
        assert refused["status"] == "AUTHORIZED"
        for field in (
            "contractor_id",
            "crew_hours",
            "work_start_utc",
            "work_end_utc",
        ):
            assert refused[field] is None, "%s must stay null" % field
        assert_hours(
            get_contractor(client, contractor["id"])["committed_crew_hours"], 4.0
        )

        moved = award_order(
            client,
            second_order["id"],
            contractor["id"],
            crew_hours=4.0,
            work_start_utc="2026-10-06T08:00:00Z",
            work_end_utc="2026-10-06T12:00:00Z",
        )
        assert moved["status"] == "AWARDED"
        assert_hours(
            get_contractor(client, contractor["id"])["committed_crew_hours"], 8.0
        )


class TestConditionalVendorInvoice:
    """An optional field becomes mandatory only for one programme type."""

    def test_the_invoice_is_required_for_a_grant_and_forbidden_talk_for_a_chipper_day(
        self, client
    ):
        """The identical invoice-less payload is admitted by a chipper day and
        refused by a cost-share grant with a 422, not a 400.

        PRD: "Presence of that invoice is strictly conditional: it must be supplied
        when the program's program_type is COST_SHARE_GRANT and must be omitted
        otherwise, with a violation either way answering ERR_MISSING_VENDOR_INVOICE."

        PRD: "For a program that is not a cost-share grant,
        award_before_bonus_cents, bonus_pct and award_cents are all null and no money
        is ever reserved."

        PRD: "The base match rate is read from the parcel's risk_class as it stands at
        decision time: an EXTREME parcel is matched at 0.75, a HIGH parcel at 0.60, a
        MODERATE parcel at 0.45 and a LOW parcel at 0.30."

        PRD: "Cost-share invoice presence - vendor_invoice_cents must be present when
        the target program's program_type is COST_SHARE_GRANT and must be absent
        otherwise. Applies to support-enrollment creation. Failure:
        ERR_MISSING_VENDOR_INVOICE (422)."

        Design: Corner/validations/cost_share_enrollment_requires_vendor_invoice_only_for_grants
        """
        cycle = open_cycle(client)
        grant = create_program(
            client,
            cycle["id"],
            PROGRAM_TYPE_GRANT,
            budget_total_cents=500000,
            capacity_slots=2,
        )
        chipper = create_program(
            client,
            cycle["id"],
            PROGRAM_TYPE_CHIPPER,
            budget_total_cents=0,
            capacity_slots=2,
        )
        parcel = create_parcel(client, owner_hardship_flag=False)
        assert parcel["owner_hardship_flag"] is False
        assert_risk(parcel, 63.83, "HIGH")

        # No invoice is exactly right for a chipper day.
        chipper_enrollment = enroll(
            client, chipper["id"], parcel["id"], chipper["version"]
        )
        assert chipper_enrollment["status"] == "APPROVED"
        assert chipper_enrollment["award_cents"] is None
        assert chipper_enrollment["award_before_bonus_cents"] is None
        assert chipper_enrollment["bonus_pct"] is None

        validate_error(
            client.create_enrollment(
                enrollment_payload(grant["id"], parcel["id"], grant["version"]),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_MISSING_VENDOR_INVOICE,
            422,
        )
        untouched = get_program(client, grant["id"])
        assert_program_capacity(untouched, 500000, reserved_slots=0)
        assert_version(untouched, grant["version"])

        funded = enroll(
            client,
            grant["id"],
            parcel["id"],
            untouched["version"],
            vendor_invoice_cents=200000,
        )
        assert funded["status"] == "APPROVED"
        assert_award(funded, 120000, 0.05, 0, 120000, reserved=120000)
        assert_program_capacity(
            get_program(client, grant["id"]), 380000, reserved_slots=1
        )


class TestCompletionValidationLadder:
    """Each rung of completion must be cleared before the next becomes visible."""

    def test_the_state_gate_answers_before_the_zone_coverage_gate(self, client):
        """A SCHEDULED inspection answers 409 whatever its coverage; once noticed with
        two zones it answers 422; the third zone lets the result through.

        PRD: "An inspection in any state other than NOTICED cannot be completed."

        PRD: "Completion refuses to run unless all three zones - ZONE_0_EMBER, ZONE_1
        and ZONE_2 - carry exactly one evaluation each on this inspection, and unless
        the submitted result agrees with those findings: a PASS requires every zone's
        deficiency_severity to be NONE, and a FAIL requires at least one zone whose
        severity is not NONE. Any of these failures answers
        ERR_ZONE_COVERAGE_INCOMPLETE."

        PRD: "Requests are screened by a fixed ladder of gates, and the ladder is
        strictly ordered: the first gate that fails determines the response, and no
        later gate is evaluated."

        PRD: "measured_veg_points is the sum of the three zones' points values, and
        the rounding discipline here is pinned: each zone's points is already rounded
        to two decimals, and it is those rounded values that are added; the sum is then
        rounded half up to two decimals and capped at 100.00."

        Design: Corner/validations/complete_state_gate_outranks_zone_coverage_gate
        """
        cycle = open_cycle(client)
        inspector = create_inspector(client)
        parcel = create_parcel(client)
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
        )
        inspector_headers = make_inspector_headers(inspector["id"])
        completion = complete_inspection_payload("FAIL", "CERTIFIED_MAIL")

        # Rung one: still SCHEDULED, and zero of three zones recorded.
        validate_error(
            client.complete_inspection(
                inspection["id"], headers=inspector_headers, payload=completion
            ),
            ERR_INVALID_STATE,
            409,
        )

        serve_notice(client, inspection["id"])
        add_zone(client, inspection["id"], inspector["id"], "ZONE_0_EMBER", 5.0)
        add_zone(client, inspection["id"], inspector["id"], "ZONE_1", 15.0)

        # Rung two: the state gate is satisfied, so coverage becomes reachable.
        validate_error(
            client.complete_inspection(
                inspection["id"], headers=inspector_headers, payload=completion
            ),
            ERR_ZONE_COVERAGE_INCOMPLETE,
            422,
        )

        _rows, meta = list_zone_evaluations(client, inspection_id=inspection["id"])
        assert meta["total_count"] == 2
        held = get_inspection(client, inspection["id"])
        assert held["status"] == "NOTICED"
        assert held["result"] is None
        assert held["completed_at_utc"] is None
        assert_posture(get_parcel(client, parcel["id"]), "PENDING_INSPECTION")
        assert (
            get_parcel(client, parcel["id"])["risk_score_basis"]
            == "INTAKE_PROVISIONAL"
        ), "no cascade may have run"

        add_zone(client, inspection["id"], inspector["id"], "ZONE_2", 118.0)
        completed = validate_success(
            client.complete_inspection(
                inspection["id"], headers=inspector_headers, payload=completion
            )
        )
        assert completed["result"] == "FAIL"
        assert_2dp(completed["measured_veg_points"], 94.31)
        assert completed["max_deficiency_severity"] == "MAJOR"
