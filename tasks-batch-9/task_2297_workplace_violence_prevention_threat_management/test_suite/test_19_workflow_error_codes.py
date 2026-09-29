"""Immutability of the register, per-row ownership, the override direction and the closed ballot round."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    OMIT,
    ApiClient,
    ApiErrorId,
    add_team_seat,
    assert_case_state,
    assert_log_elements_present,
    assert_plan_metrics,
    assert_risk_scores,
    assert_seat_ballot,
    assert_total_count,
    assign_training,
    build_ballot,
    build_decision,
    build_log_amendment,
    build_training_completion,
    cast_standard_ballots,
    complete_training,
    make_employee_headers,
    make_threat_team_member_headers,
    read_case,
    read_employee,
    read_plan,
    setup_amended_log_case,
    setup_convened_case,
    setup_deliberating_case,
    setup_fully_seated_case,
    setup_training_cohort,
)

#: One character short of the forty-character floor an override justification must clear.
SHORT_JUSTIFICATION = "Weapon on site and no badge control now"

#: A de-escalating justification, long enough to pass the length rule and still refused.
DE_ESCALATING_JUSTIFICATION = "Team prefers a lighter touch than the band requires."

#: A justification that skips two bands downward rather than one step upward.
TWO_BAND_DROP_JUSTIFICATION = "Team believes the whole matter was a misunderstanding."

#: The escalation the band permits: one step above HIGH, with a written rationale.
ESCALATING_JUSTIFICATION = (
    "Weapon on site, no badge control at the front desk and the subject "
    "still works the same shift."
)


class TestLogEntryImmutability:
    """The correction chain may only be extended from its newest live link."""

    def test_a_second_amendment_of_the_original_is_refused_but_the_successor_accepts_one(
        self, api: ApiClient
    ) -> None:
        """Aiming at the superseded original returns the immutability code; aiming at its successor appends.

        PRD: "Amendment is only permitted against an entry whose `superseded_flag` is false and whose `retention_status` is `ACTIVE`; amending an already-superseded entry, or one past retention, is refused with `ERR_LOG_ENTRY_IMMUTABLE`, so corrections always chain from the newest live entry."
        Design: Corner/errors/amendment_on_a_superseded_entry_returns_log_entry_immutable
        """
        ctx = setup_amended_log_case(api)
        officer = ctx["headers"]["safety_officer"]
        original = ctx["log_entry"]
        successor = ctx["log_amendment"]
        assert successor["supersedes_entry_id"] == original["id"]
        assert_log_elements_present(successor, 8)

        branch = api.amend_log_entry(
            original["id"],
            build_log_amendment(
                amendment_reason="Second correction aimed at the original entry rather than its successor.",
                controls_summary="Also added a duress button at the counter.",
                consequence_narrative=OMIT,
            ),
            officer,
        )

        validate_error(branch, ApiErrorId.LOG_ENTRY_IMMUTABLE, 409)
        assert branch.json()["data"]["error_id"] != ApiErrorId.LOG_ENTRY_NOT_FOUND

        chained = get_success_data(
            api.amend_log_entry(
                successor["id"],
                build_log_amendment(
                    amendment_reason="Correction chained from the newest live entry.",
                    controls_summary="Badge control plus a duress button at the counter.",
                    consequence_narrative=OMIT,
                ),
                officer,
            ),
            201,
        )

        assert chained["supersedes_entry_id"] == successor["id"]
        assert_log_elements_present(chained, 8)
        assert get_success_data(api.get_log_entry(successor["id"], officer))[
            "superseded_flag"
        ] is True
        assert chained["superseded_flag"] is False
        live = assert_total_count(
            api.list_log_entries(
                officer, {"case_id": ctx["case"]["id"], "superseded_flag": "false"}
            ),
            1,
        )
        assert live[0]["id"] == chained["id"]
        assert_plan_metrics(read_plan(api, ctx), log_completeness_pct=100.00)


class TestTrainingCompletionOwnership:
    """Ownership is a per-row check that runs before the score is even read."""

    def test_a_colleague_cannot_finish_someone_elses_module_but_the_owner_can(
        self, api: ApiClient
    ) -> None:
        """The intruder is a valid ACTIVE employee on a listed role, so the refusal is ownership, not authority.

        PRD: "An actor whose role is `Employee` may complete only a training assignment whose `employee_id` equals their `X-User-ID`, and may allege retaliation only on a report whose `reporter_employee_id` equals their `X-User-ID`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (403)."
        Design: Corner/errors/employee_completing_another_workers_training_returns_not_resource_owner
        """
        ctx = setup_training_cohort(api)
        learner = ctx["rep"]
        assignment = assign_training(api, ctx, learner["id"])

        intruder = api.complete_training_assignment(
            assignment["id"],
            build_training_completion(95),
            make_employee_headers(ctx["hr"]["id"]),
        )

        validate_error(intruder, ApiErrorId.NOT_RESOURCE_OWNER, 403)
        assert intruder.json()["data"]["error_id"] != ApiErrorId.UNAUTHORIZED
        untouched = get_success_data(
            api.get_training_assignment(assignment["id"], ctx["headers"]["hr_partner"])
        )
        assert untouched["status"] == "ASSIGNED"
        assert untouched["attempt_count"] == 0

        completed = complete_training(api, ctx, assignment["id"], learner["id"], score=95)

        assert completed["status"] == "COMPLETED"
        assert completed["attempt_count"] == 1
        assert completed["expires_at"] == "2027-08-01T00:00:00Z"
        assert read_employee(api, learner["id"])["training_current"] is True


class TestOverrideDirectionAndLength:
    """An override may only escalate, by one step, and only with forty characters behind it."""

    def test_two_de_escalations_and_a_thirty_nine_character_rationale_are_all_refused(
        self, api: ApiClient
    ) -> None:
        """Only the one-step escalation is admitted, and it lands on IMMINENT_RISK above the HIGH mapping.

        PRD: "An `override_justification` must be at least 40 characters long, and may raise the disposition by **at most one step** above the band mapping; it may never lower a disposition below the mapping, and it may never skip more than one band."
        Design: Corner/errors/de_escalating_override_returns_override_not_permitted
        """
        ctx = setup_deliberating_case(api)
        lead_headers = ctx["headers"]["threat_team_lead"]
        assert len(SHORT_JUSTIFICATION) == 39
        assert len(DE_ESCALATING_JUSTIFICATION) >= 40

        lighter = api.decide_threat_case(
            ctx["case"]["id"],
            build_decision("MONITOR", override_justification=DE_ESCALATING_JUSTIFICATION),
            lead_headers,
        )

        validate_error(lighter, ApiErrorId.OVERRIDE_NOT_PERMITTED, 409)
        assert (
            lighter.json()["data"]["error_id"] != ApiErrorId.DISPOSITION_BAND_MISMATCH
        )
        validate_error(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("NO_THREAT", override_justification=TWO_BAND_DROP_JUSTIFICATION),
                lead_headers,
            ),
            ApiErrorId.OVERRIDE_NOT_PERMITTED,
            409,
        )
        validate_error(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("IMMINENT_RISK", override_justification=SHORT_JUSTIFICATION),
                lead_headers,
            ),
            ApiErrorId.OVERRIDE_NOT_PERMITTED,
            409,
        )

        refused = read_case(api, ctx)
        assert_case_state(refused, status="DELIBERATION")
        assert refused["consensus_risk_score"] is None
        assert refused["disposition"] is None

        escalated = get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("IMMINENT_RISK", override_justification=ESCALATING_JUSTIFICATION),
                lead_headers,
            )
        )

        assert_case_state(escalated, status="MONITORING")
        assert_risk_scores(
            escalated, consensus=60.94, risk_band="HIGH", disposition="IMMINENT_RISK"
        )
        assert escalated["protection_window_start"] == "2026-08-01T00:00:00Z"
        assert escalated["protection_window_end"] == "2026-08-15T00:00:00Z"


class TestBallotRoundIsClosedPerSeat:
    """Three ballot faults, two codes, and a counter that refuses to move for any of them."""

    def test_a_repeat_ballot_an_advisor_ballot_and_a_seatless_caller_all_fail(
        self, api: ApiClient
    ) -> None:
        """The repeat and the advisor share the round-closed code while the seatless caller gets a 404.

        PRD: "The caller must hold an `ASSIGNED` seat on the case whose `role_on_team` is `LEAD` or `VOTING_MEMBER`, must not already have balloted in the case's current `assessment_round`, and the case must still be `ASSESSING`; a second ballot in the same round, a ballot from an `ADVISOR` seat, a ballot from a `RECUSED` seat, and a ballot arriving after the case has already advanced are all refused with `ERR_BALLOT_ROUND_CLOSED`."
        Design: Corner/errors/second_ballot_in_the_same_round_returns_ballot_round_closed
        """
        ctx = setup_fully_seated_case(api)
        advisor_seat = add_team_seat(api, ctx, "hr", "OPERATIONS", "ADVISOR")
        ctx = setup_convened_case(api, ctx)
        ctx = cast_standard_ballots(api, ctx, 1)
        case_id = ctx["case"]["id"]
        assert_case_state(
            read_case(api, ctx),
            status="ASSESSING",
            assessment_round=1,
            quorum_met=True,
            ballot_count_current_round=1,
        )

        repeat = api.cast_ballot(
            case_id,
            build_ballot("IMMINENT", "Changing my vote after hearing the security briefing."),
            ctx["headers"]["member_ops"],
        )
        advisory = api.cast_ballot(
            case_id,
            build_ballot("MONITOR", "Advisory view from the HR seat."),
            make_threat_team_member_headers(ctx["hr"]["id"]),
        )
        seatless = api.cast_ballot(
            case_id,
            build_ballot("MONITOR", "Security coordinator opinion, offered unsolicited."),
            make_threat_team_member_headers(ctx["coord"]["id"]),
        )

        validate_error(repeat, ApiErrorId.BALLOT_ROUND_CLOSED, 409)
        validate_error(advisory, ApiErrorId.BALLOT_ROUND_CLOSED, 409)
        validate_error(seatless, ApiErrorId.TEAM_ASSIGNMENT_NOT_FOUND, 404)
        assert_seat_ballot(
            get_success_data(
                api.get_team_assignment(
                    ctx["seats"]["ops"]["id"], ctx["headers"]["threat_team_lead"]
                )
            ),
            ballot_value="ELEVATED",
            ballot_round=1,
        )
        held_advisor = get_success_data(
            api.get_team_assignment(advisor_seat["id"], ctx["headers"]["threat_team_lead"])
        )
        assert held_advisor["role_on_team"] == "ADVISOR"
        assert held_advisor["ballot_value"] is None
        assert_case_state(
            read_case(api, ctx), status="ASSESSING", ballot_count_current_round=1
        )
