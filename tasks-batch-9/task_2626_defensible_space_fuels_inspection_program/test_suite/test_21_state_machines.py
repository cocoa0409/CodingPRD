"""Declared transitions, their stamps, their refusals and the aggregates they
carry with them."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_CYCLE_ALREADY_ACTIVE,
    ERR_INVALID_STATE,
    EPOCH_CLOCK_UTC,
    PASS_CLEARANCES,
    PROGRAM_TYPE_GRANT,
    access_denial_payload,
    activate_cycle,
    add_zones,
    assert_award,
    assert_cents,
    assert_end_of_day,
    assert_instant,
    assert_metrics,
    assert_notice_schedule,
    assert_posture,
    assert_program_capacity,
    assert_risk,
    assert_version,
    close_cycle,
    complete_inspection,
    complete_inspection_payload,
    create_cycle,
    create_inspector,
    create_parcel,
    create_program,
    cycle_metrics,
    decide_certificate,
    enroll,
    failed_world,
    get_certificate,
    get_cycle,
    get_inspection,
    get_inspector,
    get_parcel,
    get_program,
    list_notices,
    noticed_world,
    notice_service_payload,
    open_certificate,
    reason_payload,
    reschedule_payload,
    schedule_inspection,
    serve_notice,
    set_clock,
)
from test_helpers.test_users import (
    FIRE_MARSHAL_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_inspector_headers,
)


class TestCycleActivation:
    """PLANNING -> ACTIVE stamps the clock and is not an advance."""

    def test_cycle_activate_moves_planning_to_active_with_a_stamp(self, client):
        """Activation reports ACTIVE with activated_at_utc at the logical clock,
        version 2 and the epoch counter still at 0.

        PRD: "A cycle becomes operational when a ProgramAdmin moves it PLANNING ->
        ACTIVE, which stamps activated_at_utc with the logical clock."

        PRD: "A newly created cycle opens in PLANNING with its epoch counter at 0
        and its activated_at_utc and closed_at_utc both null."

        PRD: "Finally the cycle's epoch is incremented by exactly 1 and its
        version is incremented by 1."

        PRD: "version, an integer that starts at 1 when the resource is created
        and increments by exactly 1 on every successful mutation of that resource."

        Design: Corner/state_machines/cycle_activate_moves_planning_to_active_with_stamp
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        cycle = create_cycle(client, season_year=2026)
        assert cycle["status"] == "PLANNING"
        assert_version(cycle, 1)

        activated = activate_cycle(client, cycle["id"])
        assert activated["status"] == "ACTIVE"
        assert_instant(activated["activated_at_utc"], EPOCH_CLOCK_UTC)
        assert activated["closed_at_utc"] is None
        assert_version(activated, 2)
        assert activated["epoch"] == 0, "activation runs none of the eight steps"

    def test_cycle_activate_is_refused_while_another_cycle_is_active(self, client):
        """A second season cannot be activated over a live one, and the refusal
        leaves the candidate exactly as it was.

        PRD: "The district runs exactly one season at a time: if any other cycle is
        already ACTIVE, the activation is refused with ERR_CYCLE_ALREADY_ACTIVE, and
        a cycle that is not sitting in PLANNING cannot be activated at all."

        PRD: "Closing a season moves the cycle ACTIVE -> CLOSED and stamps
        closed_at_utc."

        PRD: "ERR_CYCLE_ALREADY_ACTIVE when a second cycle activation is attempted"

        Design: Corner/state_machines/cycle_activate_rejected_while_another_cycle_active
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        first = activate_cycle(client, create_cycle(client, season_year=2026)["id"])
        second = create_cycle(client, season_year=2027)
        assert_version(second, 1)

        validate_error(
            client.activate_cycle(second["id"], headers=PROGRAM_ADMIN_HEADERS),
            ERR_CYCLE_ALREADY_ACTIVE,
            409,
        )

        refused = get_cycle(client, second["id"])
        assert refused["status"] == "PLANNING"
        assert refused["activated_at_utc"] is None
        assert_version(refused, 1)

        live = get_cycle(client, first["id"])
        assert live["status"] == "ACTIVE"
        assert_version(live, first["version"])

        close_cycle(client, first["id"])
        promoted = activate_cycle(client, second["id"])
        assert promoted["status"] == "ACTIVE"


class TestNoticeService:
    """Serving the entry notice performs exactly two writes."""

    def test_notice_service_stamps_the_method_and_the_send_instant(self, client):
        """SCHEDULED -> NOTICED records the method and the clock, leaves the window
        alone, keeps the assignment live and raises no citation.

        PRD: "A ProgramAdmin serves the owner notice by declaring the
        notice_method used - IN_PERSON, CERTIFIED_MAIL or EMAIL - which advances the
        inspection SCHEDULED -> NOTICED and stamps notice_sent_at_utc with the
        logical clock."

        PRD: "An inspector's assigned_open_count must always equal the number of
        inspections carrying that inspector_id whose status is SCHEDULED, NOTICED or
        ACCESS_DENIED."

        PRD: "compliance_status is the parcel's derived defensible-space posture,
        initialised at intake to PENDING_INSPECTION and thereafter moving among
        COMPLIANT, NON_COMPLIANT, ABATEMENT_PENDING and EXEMPT as inspections, notices
        and abatement orders move."

        Design: Corner/state_machines/notice_service_stamps_method_and_sent_at
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        cycle = activate_cycle(client, create_cycle(client)["id"])
        inspector = create_inspector(client)
        parcel = create_parcel(client)
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
            access_arrangement="GATE_CODE",
        )
        assert_version(inspection, 1)

        noticed = serve_notice(client, inspection["id"], "CERTIFIED_MAIL")
        assert noticed["status"] == "NOTICED"
        assert noticed["notice_method"] == "CERTIFIED_MAIL"
        assert_instant(noticed["notice_sent_at_utc"], EPOCH_CLOCK_UTC)
        assert_version(noticed, 2)
        assert_instant(noticed["scheduled_start_utc"], "2026-08-20T15:00:00Z")
        assert_instant(noticed["scheduled_end_utc"], "2026-08-20T17:00:00Z")

        assert get_inspector(client, inspector["id"])["assigned_open_count"] == 1

        _rows, meta = list_notices(client, parcel_id=parcel["id"])
        assert meta["total_count"] == 0, "an entry notice is not a citation"
        assert_posture(
            get_parcel(client, parcel["id"]), "PENDING_INSPECTION", open_violation_count=0
        )

    def test_a_second_notice_service_is_refused_and_not_reapplied(self, client):
        """The repeat call is a 409 and neither the method nor the send instant nor
        the version moves.

        PRD: "A ProgramAdmin serves the owner notice by declaring the notice_method
        used - IN_PERSON, CERTIFIED_MAIL or EMAIL - which advances the inspection
        SCHEDULED -> NOTICED and stamps notice_sent_at_utc with the logical clock."

        PRD: "State gate - the target resource is in a state from which the
        requested transition is declared, including any attempt to leave a terminal
        state. Applies to every state-changing endpoint. The general failure is
        ERR_INVALID_STATE (409), with five specialised identifiers at the same rung:
        ERR_NOTICE_NOT_OVERDUE when abatement authority is exercised on a notice that
        has not lapsed, ERR_CYCLE_ALREADY_ACTIVE when a second cycle activation is
        attempted, ERR_ZONE_ALREADY_EVALUATED when a zone already carries an evaluation
        on the same inspection, ERR_ACCESS_DENIAL_LIMIT_REACHED on a third denial
        attempt, and ERR_DUPLICATE_ENROLLMENT for a repeat non-cancelled enrollment of
        the same parcel in the same program."

        PRD: "Setting the clock may move it forward or backward and performs no
        state transitions of its own - no notice becomes overdue and no certificate
        expires merely because the clock moved."

        Design: Corner/state_machines/second_notice_service_rejected_not_reapplied
        """
        world = noticed_world(
            client,
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
        )
        first = world["inspection"]
        assert_version(first, 2)

        set_clock(client, "2026-08-05T00:00:00Z")
        validate_error(
            client.serve_notice(
                first["id"],
                notice_service_payload("IN_PERSON"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INVALID_STATE,
            409,
        )

        reread = get_inspection(client, first["id"])
        assert reread["notice_method"] == "CERTIFIED_MAIL"
        assert_instant(reread["notice_sent_at_utc"], EPOCH_CLOCK_UTC)
        assert_version(reread, first["version"])


class TestUndeclaredTransition:
    """The state gate answers before any later gate is evaluated."""

    def test_inspection_complete_from_scheduled_is_a_state_error(self, client):
        """Completing a never-noticed inspection reports ERR_INVALID_STATE rather
        than the zone-coverage error that also applies.

        PRD: "The assigned inspector closes an inspection standing in NOTICED by
        submitting a result of PASS or FAIL, optionally accompanied by a
        violation_notice_method that names how any resulting citation should be
        served."

        PRD: "An inspection in any state other than NOTICED cannot be completed."

        PRD: "Requests are screened by a fixed ladder of gates, and the ladder is
        strictly ordered: the first gate that fails determines the response, and no
        later gate is evaluated."

        PRD: "With access_denial_count standing at 0, the count is incremented to 1
        and the inspection moves NOTICED -> ACCESS_DENIED."

        Design: Corner/state_machines/inspection_complete_from_scheduled_returns_409
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        cycle = activate_cycle(client, create_cycle(client)["id"])
        inspector = create_inspector(client)
        parcel = create_parcel(client)
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
            access_arrangement="OWNER_PRESENT",
        )
        inspector_headers = make_inspector_headers(inspector["id"])

        validate_error(
            client.complete_inspection(
                inspection["id"],
                headers=inspector_headers,
                payload=complete_inspection_payload("PASS"),
            ),
            ERR_INVALID_STATE,
            409,
        )

        reread = get_inspection(client, inspection["id"])
        assert reread["status"] == "SCHEDULED"
        assert reread["result"] is None
        assert reread["completed_at_utc"] is None
        assert_risk(
            get_parcel(client, parcel["id"]),
            63.83,
            "HIGH",
            basis="INTAKE_PROVISIONAL",
        )

        # ACCESS_DENIED is likewise reachable only from NOTICED.
        validate_error(
            client.record_access_denial(
                inspection["id"],
                headers=inspector_headers,
                payload=access_denial_payload(),
            ),
            ERR_INVALID_STATE,
            409,
        )
        assert get_inspection(client, inspection["id"])["access_denial_count"] == 0


class TestDeclaredInitialStates:
    """No creation endpoint accepts a status; each row lands on its opening state."""

    def test_created_rows_start_in_their_declared_initial_states(self, client):
        """A cycle opens in PLANNING, a certificate request in REQUESTED with every
        snapshot null, and an inspection in SCHEDULED with nothing measured yet.

        PRD: "A newly created cycle opens in PLANNING with its epoch counter at 0
        and its activated_at_utc and closed_at_utc both null."

        PRD: "A newly opened request stands in REQUESTED with decision_note,
        issued_at_utc, expires_at_utc, snapshot_risk_class,
        snapshot_compliance_status and revoked_at_utc all null."

        PRD: "A newly booked inspection opens in SCHEDULED with
        access_denial_count at 0, result, notice_method and notice_sent_at_utc all
        null, and the assigned inspector's assigned_open_count incremented by 1."

        Design: Corner/state_machines/created_rows_start_in_declared_initial_states
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        cycle = create_cycle(client)
        assert cycle["status"] == "PLANNING"
        activate_cycle(client, cycle["id"])

        inspector = create_inspector(client)
        parcel = create_parcel(client)

        certificate = open_certificate(
            client,
            parcel["id"],
            requester_kind="REAL_ESTATE",
            transaction_reference="ESC-4410",
        )
        assert certificate["status"] == "REQUESTED"
        for field in (
            "decision_note",
            "issued_at_utc",
            "expires_at_utc",
            "snapshot_risk_class",
            "snapshot_compliance_status",
            "revoked_at_utc",
        ):
            assert certificate[field] is None, "%s must open null" % field

        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
            access_arrangement="OWNER_PRESENT",
        )
        assert inspection["status"] == "SCHEDULED"
        assert inspection["access_denial_count"] == 0
        for field in (
            "result",
            "notice_method",
            "notice_sent_at_utc",
            "measured_veg_points",
            "hardening_credit_points",
            "max_deficiency_severity",
        ):
            assert inspection[field] is None, "%s must open null" % field
        assert get_inspector(client, inspector["id"])["assigned_open_count"] == 1


class TestTerminalInspectionStates:
    """CANCELLED is terminal and its window is already released."""

    def test_a_cancelled_inspection_cannot_be_rescheduled_or_reused(self, client):
        """Reschedule, notice and complete are each refused after a cancel, and the
        released assignment is not re-taken.

        PRD: "A ProgramAdmin may cancel an inspection standing in either SCHEDULED
        or NOTICED by recording a reason, moving it SCHEDULED -> CANCELLED or
        NOTICED -> CANCELLED. Cancellation releases the inspector's half-open window
        so that a later inspection may occupy it and decrements that inspector's
        assigned_open_count by 1."

        PRD: "Rebooking anything that is not in ACCESS_DENIED is refused with
        ERR_INVALID_STATE."

        PRD: "A COMPLETED, CANCELLED or ABANDONED inspection cannot be cancelled -
        all three are terminal - and the attempt answers ERR_INVALID_STATE."

        Design: Corner/state_machines/cancelled_inspection_cannot_be_rescheduled
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        cycle = activate_cycle(client, create_cycle(client)["id"])
        inspector = create_inspector(client)
        parcel = create_parcel(client)
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
            access_arrangement="OWNER_PRESENT",
        )

        cancelled = validate_success(
            client.cancel_inspection(
                inspection["id"],
                headers=PROGRAM_ADMIN_HEADERS,
                payload=reason_payload("Owner sold the parcel"),
            )
        )
        assert cancelled["status"] == "CANCELLED"

        validate_error(
            client.reschedule_inspection(
                inspection["id"],
                reschedule_payload("2026-08-25T15:00:00Z", "2026-08-25T17:00:00Z"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INVALID_STATE,
            409,
        )
        reread = get_inspection(client, inspection["id"])
        assert reread["status"] == "CANCELLED"
        assert_instant(reread["scheduled_start_utc"], "2026-08-20T15:00:00Z")
        assert get_inspector(client, inspector["id"])["assigned_open_count"] == 0

        validate_error(
            client.serve_notice(
                inspection["id"],
                notice_service_payload("EMAIL"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INVALID_STATE,
            409,
        )
        validate_error(
            client.complete_inspection(
                inspection["id"],
                headers=make_inspector_headers(inspector["id"]),
                payload=complete_inspection_payload("PASS"),
            ),
            ERR_INVALID_STATE,
            409,
        )
        validate_error(
            client.cancel_inspection(
                inspection["id"],
                headers=PROGRAM_ADMIN_HEADERS,
                payload=reason_payload("Second thoughts"),
            ),
            ERR_INVALID_STATE,
            409,
        )


class TestAdmissionAggregates:
    """An admission decided inside the enrollment request moves the programme row."""

    def test_enrollment_admission_bubbles_the_slot_and_the_budget_to_the_program(
        self, client
    ):
        """An approved grant enrollment debits budget_remaining_cents, takes a slot
        and advances only the programme's version.

        PRD: "The enrollment is approved when the program still has an unused slot -
        reserved_slots strictly below capacity_slots - and, for a cost-share grant,
        when budget_remaining_cents is at least the computed award_cents. Approval
        sets reserved_amount_cents to award_cents for a grant, debits the program's
        budget_remaining_cents by that same amount, increments reserved_slots by 1,
        leaves waitlist_position null, and advances the program's version by 1."

        PRD: "The eligible cost is the lesser of the submitted vendor_invoice_cents
        and the per-parcel award cap of 250,000 cents, that is 2,500 dollars."

        PRD: "a pre-bonus award of 120,000 cents or more draws 0.05 - a pre-bonus
        award of exactly 120,000 cents therefore draws 0.05, not 0.10.
        hardship_bonus_cents is award_before_bonus_cents multiplied by bonus_pct,
        rounded half up to a whole cent, but only when the parcel's
        owner_hardship_flag is true; where the flag is false the bonus is exactly 0."

        PRD: "REQUESTED is the enrollment's declared initial state and the admission
        decision resolves it to APPROVED or WAITLISTED before the response is
        returned."

        Design: Corner/state_machines/enrollment_admission_bubbles_slot_and_budget_to_program
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        cycle = activate_cycle(client, create_cycle(client)["id"])
        program = create_program(
            client,
            cycle["id"],
            PROGRAM_TYPE_GRANT,
            budget_total_cents=500000,
            capacity_slots=2,
        )
        assert_program_capacity(program, 500000, reserved_slots=0)
        parcel = create_parcel(client, owner_hardship_flag=False)

        enrollment = enroll(
            client,
            program["id"],
            parcel["id"],
            program["version"],
            vendor_invoice_cents=200000,
        )

        assert enrollment["status"] == "APPROVED"
        assert enrollment["waitlist_position"] is None
        # 200000 is under the 250000 cap, matched at the HIGH rate of 0.60.
        assert_award(enrollment, 120000, 0.05, 0, 120000, reserved=120000)

        after = get_program(client, program["id"])
        assert_program_capacity(after, 380000, reserved_slots=1)
        assert_cents(
            after["budget_remaining_cents"],
            program["budget_remaining_cents"] - enrollment["reserved_amount_cents"],
        )
        assert_version(after, program["version"] + 1)
        assert after["capacity_slots"] == 2
        assert_version(get_parcel(client, parcel["id"]), parcel["version"])


class TestVoidCompensatesPostureOnly:
    """Voiding walks back the citation without walking back the measurements."""

    def test_void_restores_the_parcel_posture_without_undoing_the_rescore(
        self, client
    ):
        """A voided notice returns the parcel to PENDING_INSPECTION and leaves the
        verified risk score exactly where the failing inspection left it.

        PRD: "A FireMarshal who concludes a notice was issued in error voids it with
        a reason, which is recorded as void_reason."

        PRD: "the parcel's open_violation_count drops by 1 and its
        compliance_status is recomputed - restored to COMPLIANT when the count has
        reached 0 and the parcel has a passing inspection on record, and set back to
        PENDING_INSPECTION when the count has reached 0 but no passing inspection
        exists - with both the notice's and the parcel's version advancing by 1."

        PRD: "Parcels sitting in PENDING_INSPECTION or EXEMPT are excluded from both
        the numerator and the denominator - they are not counted as failures, they
        are simply not counted."

        PRD: "Where the eligible set is empty the rate is null, which is a distinct
        value from 0.00 and must be reported as null rather than as a zero."

        Design: Corner/state_machines/void_notice_restores_parcel_posture_without_rescoring
        """
        world = failed_world(client, fail_at="2026-08-22T00:00:00Z")
        notice = world["notice"]
        assert_notice_schedule(
            notice,
            "MAJOR",
            "2026-08-27T00:00:00Z",
            30,
            "2026-09-26",
            status="ISSUED",
        )
        assert_posture(world["parcel"], "NON_COMPLIANT", open_violation_count=1)
        assert_risk(world["parcel"], 70.49, "HIGH", basis="POST_INSPECTION_VERIFIED")

        voided = validate_success(
            client.void_notice(
                notice["id"],
                reason_payload("Wrong parcel cited: the deficiency is next door"),
                headers=FIRE_MARSHAL_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == (
            "Wrong parcel cited: the deficiency is next door"
        )
        assert_version(voided, notice["version"] + 1)

        parcel = get_parcel(client, world["parcel"]["id"])
        assert_posture(parcel, "PENDING_INSPECTION", open_violation_count=0)
        # The measurements stand: only the citation was withdrawn.
        assert_risk(parcel, 70.49, "HIGH", basis="POST_INSPECTION_VERIFIED")
        assert_version(parcel, world["parcel"]["version"] + 1)

        # A PENDING_INSPECTION parcel leaves the eligible denominator empty.
        assert_metrics(cycle_metrics(client, world["cycle"]["id"]), 0, 0, None)

        inspection = get_inspection(client, world["inspection"]["id"])
        assert inspection["status"] == "COMPLETED"
        assert inspection["result"] == "FAIL"


class TestInspectorLoadInvariant:
    """assigned_open_count is a derived count, not a hand-maintained tally."""

    def test_assigned_open_count_tracks_live_inspections_up_and_down(self, client):
        """Three bookings raise the count to 3 and three cancellations walk it back
        to 0, with a noticed visit still counting as live.

        PRD: "An inspector's assigned_open_count must always equal the number of
        inspections carrying that inspector_id whose status is SCHEDULED, NOTICED or
        ACCESS_DENIED."

        PRD: "Cancellation releases the inspector's half-open window so that a later
        inspection may occupy it and decrements that inspector's
        assigned_open_count by 1."

        Design: Corner/state_machines/inspector_assigned_open_count_tracks_live_inspections
        """
        set_clock(client, EPOCH_CLOCK_UTC)
        cycle = activate_cycle(client, create_cycle(client)["id"])
        inspector = create_inspector(client)
        assert inspector["assigned_open_count"] == 0

        windows = (
            ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"),
            ("2026-08-21T09:00:00Z", "2026-08-21T11:00:00Z"),
            ("2026-08-22T09:00:00Z", "2026-08-22T11:00:00Z"),
        )
        booked = []
        for index, (start, end) in enumerate(windows):
            parcel = create_parcel(client)
            inspection = schedule_inspection(
                client,
                parcel["id"],
                cycle["id"],
                inspector["id"],
                scheduled_start_utc=start,
                scheduled_end_utc=end,
            )
            booked.append(inspection)
            assert (
                get_inspector(client, inspector["id"])["assigned_open_count"]
                == index + 1
            )

        # A NOTICED inspection is still live, so the count does not move.
        serve_notice(client, booked[0]["id"])
        assert get_inspector(client, inspector["id"])["assigned_open_count"] == 3

        for expected_remaining, inspection in (
            (2, booked[1]),
            (1, booked[2]),
            (0, booked[0]),
        ):
            cancelled = validate_success(
                client.cancel_inspection(
                    inspection["id"],
                    headers=PROGRAM_ADMIN_HEADERS,
                    payload=reason_payload("Season rebalanced"),
                )
            )
            assert cancelled["status"] == "CANCELLED"
            assert (
                get_inspector(client, inspector["id"])["assigned_open_count"]
                == expected_remaining
            )


class TestCertificateRevocationCascade:
    """A failing inspection reaches sideways into the paperwork an escrow holds."""

    def test_a_failing_inspection_revokes_only_the_issued_certificate(self, client):
        """The ISSUED certificate is driven to REVOKED with its snapshots intact
        while the DENIED one is left exactly as it was decided.

        PRD: "Because a violation notice now exists on the parcel, every compliance
        certificate on that parcel standing in ISSUED whose expires_at_utc is at or
        after the logical clock transitions ISSUED -> REVOKED with revoked_at_utc
        stamped at the logical clock."

        PRD: "An ISSUE decision moves the certificate REQUESTED -> ISSUED and stamps
        four fields: issued_at_utc at the logical clock; expires_at_utc at the
        calendar date 90 days after issuance, expressed at 23:59:59 UTC on that
        date; snapshot_risk_class pinned to the parcel's risk_class at that moment;
        and snapshot_compliance_status pinned to the parcel's posture, which will
        therefore be either COMPLIANT or EXEMPT."

        PRD: "A DENY decision moves the certificate REQUESTED -> DENIED, records the
        supplied text as decision_note, and leaves every snapshot field null."

        PRD: "DENIED and REVOKED are terminal; the revocation path is the one
        described in section 3.5, where a failing inspection on the parcel drives an
        unexpired issued certificate ISSUED -> REVOKED with revoked_at_utc stamped
        and the original snapshots preserved exactly as issued."

        Design: Corner/state_machines/fail_inspection_revokes_only_the_issued_certificate
        """
        world = noticed_world(client)
        parcel_id = world["parcel"]["id"]
        inspector_id = world["inspector"]["id"]

        add_zones(client, world["inspection"]["id"], inspector_id, PASS_CLEARANCES)
        set_clock(client, "2026-08-22T00:00:00Z")
        complete_inspection(
            client, world["inspection"]["id"], inspector_id, result="PASS"
        )
        passed = get_parcel(client, parcel_id)
        assert_risk(passed, 37.95, "MODERATE", basis="POST_INSPECTION_VERIFIED")
        assert_posture(passed, "COMPLIANT", open_violation_count=0)

        insurance = decide_certificate(
            client,
            open_certificate(client, parcel_id, requester_kind="INSURANCE")["id"],
            "ISSUE",
            "Clean defensible space record",
        )
        assert insurance["status"] == "ISSUED"
        assert_instant(insurance["issued_at_utc"], "2026-08-22T00:00:00Z")
        assert_end_of_day(insurance["expires_at_utc"], "2026-11-20")
        assert insurance["snapshot_risk_class"] == "MODERATE"
        assert insurance["snapshot_compliance_status"] == "COMPLIANT"
        assert insurance["revoked_at_utc"] is None

        lender = decide_certificate(
            client,
            open_certificate(client, parcel_id, requester_kind="LENDER")["id"],
            "DENY",
            "Loan file incomplete",
        )
        assert lender["status"] == "DENIED"
        assert lender["decision_note"] == "Loan file incomplete"
        assert lender["snapshot_risk_class"] is None
        assert lender["snapshot_compliance_status"] is None
        assert lender["revoked_at_utc"] is None

        reinspection = schedule_inspection(
            client,
            parcel_id,
            world["cycle"]["id"],
            inspector_id,
            scheduled_start_utc="2026-09-10T15:00:00Z",
            scheduled_end_utc="2026-09-10T17:00:00Z",
            inspection_type="REINSPECTION",
        )
        reinspection = serve_notice(client, reinspection["id"])
        add_zones(client, reinspection["id"], inspector_id)
        set_clock(client, "2026-09-10T00:00:00Z")
        complete_inspection(
            client,
            reinspection["id"],
            inspector_id,
            result="FAIL",
            violation_notice_method="CERTIFIED_MAIL",
        )

        revoked = get_certificate(client, insurance["id"])
        assert revoked["status"] == "REVOKED"
        assert_instant(revoked["revoked_at_utc"], "2026-09-10T00:00:00Z")
        # Frozen evidence: the snapshots are the ones taken at issuance.
        assert revoked["snapshot_risk_class"] == "MODERATE"
        assert revoked["snapshot_compliance_status"] == "COMPLIANT"
        assert_end_of_day(revoked["expires_at_utc"], "2026-11-20")
        assert_version(revoked, insurance["version"] + 1)

        untouched = get_certificate(client, lender["id"])
        assert untouched["status"] == "DENIED"
        assert untouched["revoked_at_utc"] is None
        assert_version(untouched, lender["version"])

        failed = get_parcel(client, parcel_id)
        assert_risk(failed, 70.49, "HIGH", basis="POST_INSPECTION_VERIFIED")
        assert_posture(failed, "NON_COMPLIANT", open_violation_count=1)

        rows, _meta = list_notices(client, parcel_id=parcel_id)
        assert len(rows) == 1
        assert_notice_schedule(
            rows[0],
            "MAJOR",
            "2026-09-15T00:00:00Z",
            30,
            "2026-10-15",
            status="ISSUED",
        )
