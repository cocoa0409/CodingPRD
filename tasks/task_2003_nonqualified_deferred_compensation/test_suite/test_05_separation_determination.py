"""Separation-from-service determination: presumption variants, evidence tiling,
reopen cycle, and the cascades into participants, elections, and distributions.

PRD §3.4 (Separation-from-Service Determination), §2.10 (service-record tiling).
"""
from test_helpers import (
    TEST_USERS,
    add_fund,
    add_window,
    advance_clock,
    append_record,
    append_records,
    create_active_plan,
    create_distribution,
    create_election,
    determine_case,
    enroll_participant,
    get_case,
    get_distribution,
    get_election,
    get_participant,
    make_participant_headers,
    open_account,
    open_separation_case,
    post_deferral,
    schedule_distribution,
    setup_funded_account,
    setup_plan_fund_window,
    setup_separation_distribution,
    settle_account,
    standard_evidence,
    submit_election,
    validate_error,
    validate_success,
    verify_distribution,
)

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _variant_case(api, plan_name, fraction_test):
    """ACTIVE plan with the given presumption test + a participant with an
    EVIDENCE_SUBMITTED case averaging 4001 bp over 1096 contiguous days."""
    plan = create_active_plan(name=plan_name, distribution_events_allowed=["SEPARATION"],
                              separation_fraction_test=fraction_test)
    participant = enroll_participant(plan["id"], employee_ref=f"EMP-{fraction_test}",
                                     hire_date="2020-01-06")
    case = open_separation_case(participant["id"], "2026-06-30", "SERVICE_REDUCTION")
    append_records(case["id"], [
        ("2023-06-30", "2024-06-30", 6000),
        ("2024-06-30", "2025-06-30", 4000),
        ("2025-06-30", "2026-06-30", 2000),
    ])
    return plan, participant, case


class TestPresumptionVariantFlip:
    def test_separation_fraction_plan_variant_determination_flip(self, api):
        """PRD §3.4: "Under the `DEFAULT_50` test the threshold is 5000 basis
        points; under `LIBERAL_20` it is 2000. An outcome of
        `CONFIRMED_SEPARATION` is valid only when the computed average fraction
        is strictly below the threshold, while `REBUTTED_CONTINUED_SERVICE` is
        valid only when the average is at or above it — an average of exactly
        the threshold therefore means the participant is *not* separated, and
        identical evidence can flip the correct determination between the two
        plan configurations. An outcome contradicting the presumption is
        rejected with `ERR_SERVICE_FRACTION_CONTRADICTS_OUTCOME`."
        PRD §3.4: "Every append recomputes `computed_avg_fraction_bp` — null
        until the first record arrives — as the coverage-weighted average
        service fraction: multiply each record's `service_fraction_bp` by its
        length in days, sum those products, divide by the total number of days
        covered, and round down to whole basis points."

        Identical records average floor(4386000/1096) = 4001 bp: CONFIRMED is
        valid under DEFAULT_50 (4001 < 5000) and contradicts the presumption
        under LIBERAL_20 (4001 >= 2000).

        Design: Difficulty/dual_variant_calc/separation_fraction_plan_variant_determination_flip
        """
        _, _, case50 = _variant_case(api, "Plan P50", "DEFAULT_50")
        _, _, case20 = _variant_case(api, "Plan P20", "LIBERAL_20")

        determined50 = determine_case(case50["id"], "CONFIRMED_SEPARATION")
        assert determined50["computed_avg_fraction_bp"] == 4001
        assert determined50["status"] == "DETERMINED_SEPARATED", (
            "4001 < 5000 presumption met under DEFAULT_50"
        )
        assert determined50["determination_threshold_bp"] == 5000

        blocked = api.determine_case(case20["id"], {"outcome": "CONFIRMED_SEPARATION"}, CO)
        validate_error(blocked, "ERR_SERVICE_FRACTION_CONTRADICTS_OUTCOME", expected_status=409)
        assert get_case(case20["id"])["status"] == "EVIDENCE_SUBMITTED"

    def test_rebutted_branch_flips_with_plan_variant(self, api):
        """PRD §3.4: "An outcome of `CONFIRMED_SEPARATION` is valid only when the
        computed average fraction is strictly below the threshold, while
        `REBUTTED_CONTINUED_SERVICE` is valid only when the average is at or
        above it".
        PRD §3.4: "A rebutted determination instead returns the participant from
        `SEPARATION_REVIEW` to `ACTIVE`, moves the case to
        `DETERMINED_NOT_SEPARATED`".

        On the same 4001 bp evidence: REBUTTED contradicts the presumption
        under DEFAULT_50 and is the valid outcome under LIBERAL_20.

        Design: Difficulty/dual_variant_calc/separation_fraction_plan_variant_determination_flip
        """
        _, p50, case50 = _variant_case(api, "Plan P50B", "DEFAULT_50")
        _, p20, case20 = _variant_case(api, "Plan P20B", "LIBERAL_20")

        blocked = api.determine_case(case50["id"], {"outcome": "REBUTTED_CONTINUED_SERVICE"}, CO)
        validate_error(blocked, "ERR_SERVICE_FRACTION_CONTRADICTS_OUTCOME", expected_status=409)
        assert get_participant(p50["id"])["status"] == "SEPARATION_REVIEW"

        determined20 = determine_case(case20["id"], "REBUTTED_CONTINUED_SERVICE")
        assert determined20["status"] == "DETERMINED_NOT_SEPARATED", (
            "4001 >= 2000 under LIBERAL_20"
        )
        assert determined20["determination_threshold_bp"] == 2000
        assert get_participant(p20["id"])["status"] == "ACTIVE", (
            "rebutted returns the participant to ACTIVE"
        )


class TestServiceRecordTiling:
    def test_service_record_gap_and_overlap_rejected(self, api):
        """PRD §2.10: "Service records within a separation case must **tile
        contiguously** as half-open intervals: each appended record's start must
        equal the previous record's end. A break in the chain is rejected with
        `ERR_SERVICE_RECORD_GAP`; a record that starts before the previous
        record's end is rejected with `ERR_SERVICE_RECORD_OVERLAP`."

        Design: Corner/validations/service_record_gap_and_overlap_rejected
        """
        plan = create_active_plan(name="Plan SG", distribution_events_allowed=["SEPARATION"])
        pa = enroll_participant(plan["id"], employee_ref="EMP-SGA")
        pb = enroll_participant(plan["id"], employee_ref="EMP-SGB")
        case_a = open_separation_case(pa["id"], "2027-03-15", "TERMINATION")
        case_b = open_separation_case(pb["id"], "2027-03-15", "TERMINATION")
        append_record(case_a["id"], "2024-03-15", "2025-03-15", 6000)
        append_record(case_b["id"], "2024-03-15", "2025-04-15", 6000)

        gap = api.append_service_record(case_a["id"], {
            "period_start": "2025-03-16", "period_end": "2026-03-15",
            "service_fraction_bp": 2000}, BA)
        validate_error(gap, "ERR_SERVICE_RECORD_GAP", expected_status=409)

        overlap = api.append_service_record(case_b["id"], {
            "period_start": "2025-03-15", "period_end": "2026-03-15",
            "service_fraction_bp": 2000}, BA)
        validate_error(overlap, "ERR_SERVICE_RECORD_OVERLAP", expected_status=409)

        case_a_after = get_case(case_a["id"])
        case_b_after = get_case(case_b["id"])
        assert case_a_after["status"] == "EVIDENCE_SUBMITTED"
        assert case_b_after["status"] == "EVIDENCE_SUBMITTED"
        assert len(case_a_after["service_records"]) == 1
        assert len(case_b_after["service_records"]) == 1


class TestReopenCycle:
    def test_separation_case_reopen_once_then_limit(self, api):
        """PRD §3.4: "A `BenefitsAdministrator` may reopen a case that is
        `DETERMINED_SEPARATED` or `DETERMINED_NOT_SEPARATED` (from any other
        state, `ERR_CASE_STATE_INVALID`), but only once — the `reopen_count`,
        which starts at zero, is hard-capped at one, and a second reopen is
        rejected with `ERR_CASE_REOPEN_LIMIT`".
        PRD §3.4: "After a reopen and a fresh determination under the same
        rules, `reopen_count` has reached one and the determination is final."

        Design: Corner/state_machines/separation_case_reopen_once_then_limit
        """
        plan = create_active_plan(name="Plan RO", distribution_events_allowed=["SEPARATION"])
        participant = enroll_participant(plan["id"], employee_ref="EMP-RO")
        case = open_separation_case(participant["id"], "2027-03-15", "TERMINATION")
        standard_evidence(case["id"])
        determine_case(case["id"], "CONFIRMED_SEPARATION")

        reopened = validate_success(api.reopen_case(case["id"], BA), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1

        redetermined = determine_case(case["id"], "CONFIRMED_SEPARATION")
        assert redetermined["status"] == "DETERMINED_SEPARATED", (
            "evidence persists across reopen; the cycle completes once"
        )

        second = api.reopen_case(case["id"], BA)
        validate_error(second, "ERR_CASE_REOPEN_LIMIT", expected_status=409)

    def test_reopen_after_window_expired(self, api):
        """PRD §3.4: "only within thirty days after the determination date,
        inclusive of the thirtieth day (`ERR_REOPEN_WINDOW_EXPIRED`)".

        Determined at the startup clock 2026-08-01, the reopen window runs
        through 2026-08-31; at clock 2026-09-01 the reopen is rejected.

        Design: Corner/validations/reopen_after_window_expired
        """
        plan = create_active_plan(name="Plan RW", distribution_events_allowed=["SEPARATION"])
        participant = enroll_participant(plan["id"], employee_ref="EMP-RW",
                                         hire_date="2020-01-06")
        case = open_separation_case(participant["id"], "2026-06-30", "SERVICE_REDUCTION")
        append_records(case["id"], [
            ("2023-06-30", "2024-06-30", 6000),
            ("2024-06-30", "2025-06-30", 4000),
            ("2025-06-30", "2026-06-30", 2000),
        ])
        determined = determine_case(case["id"], "CONFIRMED_SEPARATION")
        assert determined["status"] == "DETERMINED_SEPARATED"

        advance_clock("2026-09-01T00:00:00Z")  # past determined_at + 30 days (2026-08-31)
        expired = api.reopen_case(case["id"], BA)
        validate_error(expired, "ERR_REOPEN_WINDOW_EXPIRED", expected_status=422)
        assert get_case(case["id"])["status"] == "DETERMINED_SEPARATED"

    def test_reopen_with_paid_distribution_blocked(self, api):
        """PRD §3.4: "only while no linked distribution request has reached
        `PAID` (`ERR_CASE_HAS_PAID_DISTRIBUTIONS`), since reopening would
        otherwise invalidate a completed payment."

        The linked SEPARATION request is paid on its scheduled date; the case
        can never be reopened afterward even though the 30-day window is open
        (determined 2027-03-20, reopen attempted 2027-04-14 <= 2027-04-19).

        Design: Corner/errors/reopen_with_paid_distribution_blocked
        """
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan RP", "distribution_events_allowed": ["SEPARATION"],
                            "processing_lag_days": 30, "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-RP"})
        advance_clock("2027-03-20T00:00:00Z")
        case = open_separation_case(ctx["participant"]["id"], "2027-03-15", "TERMINATION")
        standard_evidence(case["id"])
        determine_case(case["id"], "CONFIRMED_SEPARATION")

        request = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                      "SEPARATION", separation_case_id=case["id"])
        verify_distribution(request["id"])
        scheduled = schedule_distribution(request["id"])
        assert scheduled["scheduled_payment_date"] == "2027-04-14"

        advance_clock("2027-04-14T00:00:00Z")  # PAYABLE
        paid = validate_success(api.pay_distribution(request["id"], BA), 200)
        assert paid["status"] == "PAID"

        blocked = api.reopen_case(case["id"], BA)
        validate_error(blocked, "ERR_CASE_HAS_PAID_DISTRIBUTIONS", expected_status=409)
        assert get_case(case["id"])["status"] == "DETERMINED_SEPARATED"


class TestVerifyEventGating:
    def test_distribution_verify_gated_by_case_determination(self, api):
        """PRD §3.6: "A `SEPARATION` request verifies only when its linked case
        stands `DETERMINED_SEPARATED` and the case's participant matches the
        account's participant."
        PRD §3.6: "Each of these failures is rejected with
        `ERR_EVENT_NOT_CONFIRMED`."

        Verify fails while the case is merely EVIDENCE_SUBMITTED and succeeds
        after determination.

        Design: Difficulty/cross_entity_state_dependency/distribution_verify_gated_by_case_determination
        """
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan GV", "distribution_events_allowed": ["SEPARATION"],
                            "processing_lag_days": 30, "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-GV"})
        case = open_separation_case(ctx["participant"]["id"], "2027-03-15", "TERMINATION")
        standard_evidence(case["id"])

        request = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                      "SEPARATION", separation_case_id=case["id"])
        blocked = api.verify_distribution_event(request["id"], CO)
        validate_error(blocked, "ERR_EVENT_NOT_CONFIRMED", expected_status=409)
        assert get_distribution(request["id"])["status"] == "REQUESTED"

        determine_case(case["id"], "CONFIRMED_SEPARATION")
        verified = verify_distribution(request["id"])
        assert verified["status"] == "EVENT_VERIFIED"
        assert verified["verified_at"] is not None

    def test_death_request_verify_gated_by_participant_status(self, api):
        """PRD §3.6: "A `DEATH` request verifies only when the participant is
        `DECEASED`, and a `DISABILITY` request only when the participant is
        `DISABLED`."
        PRD §3.3: "marking a participant `DECEASED` is permitted from any state
        other than `DECEASED` itself".

        The same cross-entity gate on a different event type: DEATH verification
        flips from ERR_EVENT_NOT_CONFIRMED to EVENT_VERIFIED when the
        participant is marked DECEASED.

        Design: Difficulty/cross_entity_state_dependency/distribution_verify_gated_by_case_determination
        """
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan GD", "distribution_events_allowed": ["DEATH"]},
            participant_overrides={"employee_ref": "EMP-GD"})
        request = create_distribution(ctx["account"]["id"], ctx["participant"]["id"], "DEATH")

        blocked = api.verify_distribution_event(request["id"], CO)
        validate_error(blocked, "ERR_EVENT_NOT_CONFIRMED", expected_status=409)
        assert get_distribution(request["id"])["status"] == "REQUESTED"

        deceased = validate_success(api.update_participant(
            ctx["participant"]["id"], {"status": "DECEASED"}, BA), 200)
        assert deceased["status"] == "DECEASED"

        verified = verify_distribution(request["id"])
        assert verified["status"] == "EVENT_VERIFIED"


class TestDeterminationElectionCascade:
    def test_separation_confirmation_election_void_cascade(self, api):
        """PRD §3.4: "the participant moves from `SEPARATION_REVIEW` to
        `SEPARATED` with `separation_date` set to the case's
        `alleged_separation_date`, and that participant mutation in turn voids
        every `DRAFT` or `SUBMITTED` deferral election of the participant while
        `LOCKED` elections persist untouched."

        The participant holds a LOCKED election (2027 window, closed) and a
        SUBMITTED election (2028 window, open); determination voids the latter
        and leaves the former.

        Design: Difficulty/transitive_cascade/separation_confirmation_election_void_cascade
        """
        plan = create_active_plan(name="Plan VC", distribution_events_allowed=["SEPARATION"])
        fund = add_fund(plan["id"])
        window1 = add_window(plan["id"], plan_year=2027,
                             general_open_date="2026-10-01", general_close_date="2026-12-31")
        window2 = add_window(plan["id"], plan_year=2028,
                             general_open_date="2027-10-01", general_close_date="2027-12-31")
        participant = enroll_participant(plan["id"], employee_ref="EMP-VC")

        advance_clock("2026-10-15T00:00:00Z")
        e1 = create_election(participant["id"], window1["id"], fund["id"],
                             deferral_percent_bp=5000)
        submit_election(e1["id"], participant["id"])
        advance_clock("2027-01-01T00:00:00Z")  # e1 LOCKED
        assert get_election(e1["id"])["status"] == "LOCKED"

        advance_clock("2027-10-15T00:00:00Z")  # window2 OPEN
        e2 = create_election(participant["id"], window2["id"], fund["id"],
                             deferral_percent_bp=2500)
        submit_election(e2["id"], participant["id"])
        assert get_election(e2["id"])["status"] == "SUBMITTED"

        case = open_separation_case(participant["id"], "2027-11-15", "TERMINATION")
        append_records(case["id"], [
            ("2024-11-15", "2025-11-15", 0),
            ("2025-11-15", "2026-11-15", 0),
            ("2026-11-15", "2027-11-15", 0),
        ])
        determined = determine_case(case["id"], "CONFIRMED_SEPARATION")
        assert determined["status"] == "DETERMINED_SEPARATED"

        assert get_participant(participant["id"])["status"] == "SEPARATED"
        assert get_election(e2["id"])["status"] == "VOIDED", (
            "SUBMITTED election voided by the participant mutation"
        )
        assert get_election(e1["id"])["status"] == "LOCKED", (
            "irrevocable elections are not voided"
        )

    def test_rebutted_determination_leaves_elections_untouched(self, api):
        """PRD §3.4: "A rebutted determination instead returns the participant
        from `SEPARATION_REVIEW` to `ACTIVE`, moves the case to
        `DETERMINED_NOT_SEPARATED`".
        PRD §3.4 scopes the election voiding to the confirmed path: "that
        participant mutation in turn voids every `DRAFT` or `SUBMITTED` deferral
        election of the participant while `LOCKED` elections persist untouched."

        With evidence averaging 6000 bp (>= 5000), REBUTTED is the valid
        outcome; the participant returns to ACTIVE and the still-SUBMITTED
        election is untouched.

        Design: Difficulty/transitive_cascade/separation_confirmation_election_void_cascade
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan VC2", "distribution_events_allowed": ["SEPARATION"]})
        participant = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-VC2")
        advance_clock("2026-10-15T00:00:00Z")
        election = create_election(participant["id"], ctx["window"]["id"], ctx["fund"]["id"],
                                   deferral_percent_bp=2500)
        submit_election(election["id"], participant["id"])

        case = open_separation_case(participant["id"], "2027-03-15", "SERVICE_REDUCTION")
        standard_evidence(case["id"], fractions=(6000, 6000, 6000))  # avg 6000 >= 5000
        determined = determine_case(case["id"], "REBUTTED_CONTINUED_SERVICE")
        assert determined["status"] == "DETERMINED_NOT_SEPARATED"

        assert get_participant(participant["id"])["status"] == "ACTIVE"
        assert get_election(election["id"])["status"] == "SUBMITTED", (
            "no voiding on the rebutted path"
        )


class TestReopenHoldsDistribution:
    def test_separation_reopen_holds_scheduled_distribution(self, api):
        """PRD §3.6: "When a linked separation case reopens, a `SCHEDULED`
        request slides to `ON_HOLD`; when the reopened case is re-determined as
        a confirmed separation, the request returns from `ON_HOLD` to `SCHEDULED`
        with its payment date recomputed against the new separation date; and
        when the case is instead rebutted, the `ON_HOLD` request is denied
        outright."
        PRD §3.4: "Reopening increments `reopen_count`, moves the case to
        `REOPENED`, and — when the case had been determined separated — pulls
        the participant back from `SEPARATED` to `SEPARATION_REVIEW`, nulls the
        `separation_date`, and places any linked `SCHEDULED` distribution
        request `ON_HOLD`."

        Design: Corner/state_machines/separation_reopen_holds_scheduled_distribution
        """
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan HD", "distribution_events_allowed": ["SEPARATION"],
                            "processing_lag_days": 30, "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-HD"})
        case = open_separation_case(ctx["participant"]["id"], "2027-03-15", "TERMINATION")
        standard_evidence(case["id"])
        determine_case(case["id"], "CONFIRMED_SEPARATION")

        request = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                      "SEPARATION", separation_case_id=case["id"])
        verify_distribution(request["id"])
        scheduled = schedule_distribution(request["id"])
        assert scheduled["scheduled_payment_date"] == "2027-04-14"

        reopened = validate_success(api.reopen_case(case["id"], BA), 200)
        assert reopened["status"] == "REOPENED"
        assert get_distribution(request["id"])["status"] == "ON_HOLD", "reopen cascade"
        assert get_participant(ctx["participant"]["id"])["status"] == "SEPARATION_REVIEW"

        determine_case(case["id"], "CONFIRMED_SEPARATION")
        back = get_distribution(request["id"])
        assert back["status"] == "SCHEDULED"
        assert back["scheduled_payment_date"] == "2027-04-14", (
            "separation date unchanged, so the recomputed date is the same"
        )
