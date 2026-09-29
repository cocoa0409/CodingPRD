"""Report triage and the threat-case machine: initial states, single-shot transitions and the bounded cycle."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_case_state,
    assert_plan_state,
    assert_protection,
    assert_report_dimensions,
    assert_risk_scores,
    assert_seat_ballot,
    assert_severity,
    assert_total_count,
    build_ballot,
    build_closure,
    build_convene,
    build_decision,
    build_incident_report,
    build_reassess,
    build_triage,
    cast_standard_ballots,
    read_case,
    read_plan,
    read_report,
    read_worksite,
    setup_case_with_core_seats,
    setup_convened_case,
    setup_escalated_report,
    setup_filed_report,
    setup_open_case,
)

#: A hotline call about a shouting customer: unweaponed, uninjured and client typology.
MINOR_REPORT = {
    "channel": "HOTLINE",
    "occurred_at": "2026-07-31T09:00:00Z",
    "narrative": "A customer raised their voice at the counter and left without further contact.",
    "incident_type": "TYPE_2_CLIENT",
    "weapon_involved": False,
    "injury_level": "NONE",
}

#: The three core seats vote alike on the minor incident.
NO_CONCERN_BALLOTS = (
    ("threat_team_lead", "Single verbal episode with no follow-on contact."),
    ("member_sec", "No trespass history and no weapon indicators."),
    ("member_ops", "Counter staffing already meets the pair minimum."),
)


def _minor_case_in_deliberation(api: ApiClient):
    """A MINOR client incident whose three-discipline team has finished round 1."""
    ctx = setup_filed_report(api, None, **MINOR_REPORT)
    ctx = setup_escalated_report(api, ctx)
    ctx = setup_open_case(api, ctx)
    ctx = setup_case_with_core_seats(api, ctx)
    ctx["case"] = get_success_data(
        api.convene_threat_case(
            ctx["case"]["id"], build_convene(), ctx["headers"]["threat_team_lead"]
        )
    )
    for header_key, rationale in NO_CONCERN_BALLOTS:
        get_success_data(
            api.cast_ballot(
                ctx["case"]["id"],
                build_ballot("NO_CONCERN", rationale),
                ctx["headers"][header_key],
            )
        )
    ctx["case"] = read_case(api, ctx)
    return ctx


class TestTriageDimension:
    """Triage is single-shot, guarded by severity, and independent of the retaliation track."""

    def test_a_new_report_starts_at_both_initial_values(self, api: ApiClient) -> None:
        """Filing writes NEW and NOT_ALLEGED together with the severity classification, and appends nothing.

        PRD: "Every new report starts with both status dimensions at their initial values — `triage_status` `NEW` and `retaliation_status` `NOT_ALLEGED` — and with `triaged_by_employee_id` and `retaliation_claimant_employee_id` null."
        Design: Corner/state_machines/newly_created_report_starts_in_new_and_not_alleged
        """
        ctx = setup_filed_report(api)

        report = ctx["report"]
        assert_report_dimensions(report, triage_status="NEW", retaliation_status="NOT_ALLEGED")
        assert_severity(report, 50, "CRITICAL", log_required=True)
        assert report["triaged_by_employee_id"] is None
        assert report["retaliation_claimant_employee_id"] is None
        assert_total_count(
            api.list_log_entries(
                ctx["headers"]["safety_officer"], {"worksite_id": ctx["worksite"]["id"]}
            ),
            0,
        )

    def test_a_replayed_triage_is_refused_and_the_first_stamp_survives(
        self, api: ApiClient
    ) -> None:
        """Escalating an already-escalated report is an invalid state, not a silently absorbed replay.

        PRD: "Requesting `NO_ACTION` on a `SERIOUS` or `CRITICAL` report is refused with `ERR_REPORT_INVALID_STATE`, as is any triage of a report whose `triage_status` is not `NEW`."
        Design: Corner/state_machines/triage_second_call_on_escalated_report_returns_report_invalid_state
        """
        ctx = setup_escalated_report(api)

        response = api.triage_incident_report(
            ctx["report"]["id"],
            build_triage("ESCALATE", triage_note="Replaying the same triage decision."),
            ctx["headers"]["safety_officer"],
        )

        validate_error(response, ApiErrorId.REPORT_INVALID_STATE, 409)
        report = read_report(api, ctx)
        assert_report_dimensions(
            report, triage_status="ESCALATED", retaliation_status="NOT_ALLEGED"
        )
        assert report["triaged_by_employee_id"] == ctx["so"]["id"]

    def test_no_action_is_refused_on_the_critical_report_and_accepted_on_the_minor_one(
        self, api: ApiClient
    ) -> None:
        """The same call fails at 50 points and succeeds at 6, because only MINOR may be closed outright.

        PRD: "`NO_ACTION` moves it from `NEW` to `CLOSED_NO_ACTION` and forecloses the case entirely — no threat case may be opened afterwards — and it is permitted **only** when `severity_class` is `MINOR`."
        Design: Corner/state_machines/no_action_triage_on_critical_report_rejected
        """
        ctx = setup_filed_report(api)
        minor = get_success_data(
            api.create_incident_report(
                build_incident_report(
                    ctx["worksite"]["id"],
                    ctx["work_area"]["id"],
                    ctx["rep"]["id"],
                    channel="SUPERVISOR",
                    occurred_at="2026-07-29T08:00:00Z",
                    narrative="Client refused to leave the lobby and shouted at the receptionist.",
                    incident_type="TYPE_2_CLIENT",
                    weapon_involved=False,
                    injury_level="NONE",
                ),
                ctx["headers"]["employee"],
            )
        )

        validate_error(
            api.triage_incident_report(
                ctx["report"]["id"],
                build_triage(
                    "NO_ACTION",
                    triage_note="Attempting to close a critical report with no action.",
                ),
                ctx["headers"]["safety_officer"],
            ),
            ApiErrorId.REPORT_INVALID_STATE,
            409,
        )
        closed = get_success_data(
            api.triage_incident_report(
                minor["id"],
                build_triage(
                    "NO_ACTION", triage_note="Single verbal episode; no further action needed."
                ),
                ctx["headers"]["safety_officer"],
            )
        )

        critical = read_report(api, ctx)
        assert_report_dimensions(critical, triage_status="NEW")
        assert critical["triaged_by_employee_id"] is None
        assert_report_dimensions(closed, triage_status="CLOSED_NO_ACTION")
        assert_severity(closed, 6, "MINOR", log_required=False)
        assert closed["triaged_by_employee_id"] == ctx["so"]["id"]


class TestQuorumGuardOnConvene:
    """Convening is guarded by a computed roster condition, not by the source state alone."""

    def test_convene_is_refused_while_the_clinical_and_legal_seats_are_empty(
        self, api: ApiClient
    ) -> None:
        """A first-aid weaponed incident needs five disciplines, so the three-seat roster cannot open round 1.

        PRD: "It requires that `quorum_met` be true — otherwise `ERR_QUORUM_NOT_MET` — and that the governing plan not be frozen, so a case whose plan is `DRAFT`, `IN_REVIEW` or `SUPERSEDED` is refused with `ERR_PLAN_POSTURE_FROZEN`."
        Design: Corner/state_machines/convene_without_clinical_seat_returns_quorum_not_met
        """
        ctx = setup_case_with_core_seats(api)
        assert_case_state(read_case(api, ctx), status="OPEN", quorum_met=False)

        response = api.convene_threat_case(
            ctx["case"]["id"],
            build_convene(convene_note="Three disciplines seated; attempting to open round 1."),
            ctx["headers"]["threat_team_lead"],
        )

        validate_error(response, ApiErrorId.QUORUM_NOT_MET, 409)
        case = read_case(api, ctx)
        assert_case_state(case, status="OPEN")
        assert case["interim_risk_score"] is None
        assert case["risk_band"] is None
        assert_total_count(
            api.list_team_assignments(
                ctx["headers"]["threat_team_lead"],
                {"case_id": ctx["case"]["id"], "status": "ASSIGNED"},
            ),
            3,
        )


class TestBallotAdvanceAndRoundCeiling:
    """The case's state is a function of its seats, and the reassessment cycle is bounded."""

    def test_the_last_ballot_of_the_round_advances_the_case_on_its_own_call(
        self, api: ApiClient
    ) -> None:
        """Four ballots leave the case ASSESSING; the fifth bubbles it to DELIBERATION with no separate request.

        PRD: "The moment `ballot_count_current_round` equals the number of `ASSIGNED` seats whose `role_on_team` is `LEAD` or `VOTING_MEMBER` — that is, the moment every voting seat has balloted in the current round — the case advances `ASSESSING` → `DELIBERATION` automatically on that same ballot call, with no separate request."
        Design: Corner/state_machines/fifth_round_one_ballot_auto_advances_the_case_to_deliberation
        """
        ctx = setup_convened_case(api)
        ctx = cast_standard_ballots(api, ctx, 4)
        assert_case_state(
            read_case(api, ctx), status="ASSESSING", ballot_count_current_round=4
        )

        get_success_data(
            api.cast_ballot(
                ctx["case"]["id"],
                build_ballot(
                    "IMMINENT", "Conduct is chargeable; restraining order is viable."
                ),
                ctx["headers"]["member_legal"],
            )
        )

        case = read_case(api, ctx)
        assert_case_state(
            case, status="DELIBERATION", assessment_round=1, ballot_count_current_round=5
        )
        assert_risk_scores(case, interim=42.00)
        assert case["consensus_risk_score"] is None
        assert case["disposition"] is None
        seat = get_success_data(
            api.get_team_assignment(
                ctx["seats"]["legal"]["id"], ctx["headers"]["threat_team_lead"]
            )
        )
        assert_seat_ballot(seat, ballot_value="IMMINENT", ballot_round=1)
        assert seat["ballot_share"] is None

    def test_a_fourth_round_is_refused_once_the_third_has_balloted(
        self, api: ApiClient
    ) -> None:
        """Two reassessments are allowed; the third is refused by the counter rather than by the state.

        PRD: "The cycle may repeat, but `assessment_round` must be below 3 to reassess; a third-round case asking for a fourth is refused with `ERR_MAX_ASSESSMENT_ROUNDS`, which is what stops the loop running forever."
        Design: Corner/state_machines/reassess_at_round_three_returns_max_assessment_rounds
        """
        ctx = setup_convened_case(api)
        ctx = cast_standard_ballots(api, ctx, 5)
        for _ in range(2):
            ctx["case"] = get_success_data(
                api.reassess_threat_case(
                    ctx["case"]["id"], build_reassess(), ctx["headers"]["threat_team_lead"]
                )
            )
            ctx = cast_standard_ballots(api, ctx, 5)
        assert_case_state(
            read_case(api, ctx),
            status="DELIBERATION",
            assessment_round=3,
            ballot_count_current_round=5,
        )

        response = api.reassess_threat_case(
            ctx["case"]["id"],
            build_reassess(
                reassess_reason="The team wants one more round before recording a disposition."
            ),
            ctx["headers"]["threat_team_lead"],
        )

        validate_error(response, ApiErrorId.MAX_ASSESSMENT_ROUNDS, 409)
        assert_case_state(
            read_case(api, ctx),
            status="DELIBERATION",
            assessment_round=3,
            ballot_count_current_round=5,
        )
        assert_total_count(
            api.list_team_assignments(
                ctx["headers"]["threat_team_lead"],
                {"case_id": ctx["case"]["id"], "ballot_round": 3},
            ),
            5,
        )


class TestNoThreatBranchAndTerminalState:
    """The NO_THREAT decision skips the cascade entirely and lands on a terminal state."""

    def test_no_threat_closes_the_report_and_appends_nothing(self, api: ApiClient) -> None:
        """Three NO_CONCERN ballots blend to 4.51, and closing the case leaves worksite, log and plan untouched.

        PRD: "A `disposition` of `NO_THREAT` moves the case `DELIBERATION` → `CLOSED` and **skips that entire cascade**. The linked report moves `ESCALATED` → `CLOSED_NO_ACTION`, no log entry is appended, the worksite's `violent_incident_count_12mo` is unchanged, no protection window is opened, `protection_status` stays `NOT_APPLICABLE` and `coverage_gap_hours` stays 0.00."
        Design: Corner/state_machines/decide_no_threat_closes_report_and_appends_no_log_entry
        """
        ctx = _minor_case_in_deliberation(api)
        assert_risk_scores(read_case(api, ctx), interim=3.60)

        decided = get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("NO_THREAT"),
                ctx["headers"]["threat_team_lead"],
            )
        )

        assert_case_state(decided, status="CLOSED")
        assert_risk_scores(
            decided, consensus=4.51, risk_band="LOW", disposition="NO_THREAT"
        )
        assert decided["protection_window_start"] is None
        assert_protection(
            decided, coverage_gap_hours=0.00, protection_status="NOT_APPLICABLE"
        )
        assert_report_dimensions(
            read_report(api, ctx),
            triage_status="CLOSED_NO_ACTION",
            retaliation_status="NOT_ALLEGED",
        )
        assert_total_count(
            api.list_log_entries(
                ctx["headers"]["safety_officer"], {"worksite_id": ctx["worksite"]["id"]}
            ),
            0,
        )
        worksite = read_worksite(api, ctx["worksite"]["id"])
        assert worksite["violent_incident_count_12mo"] == 0
        assert worksite["high_risk_flag"] is False
        assert_plan_state(read_plan(api, ctx), status="ACTIVE", compliance_posture="OPEN")

    def test_a_closed_case_refuses_both_close_and_reassess(self, api: ApiClient) -> None:
        """CLOSED is terminal in both directions, so neither declared transition can leave it.

        PRD: "This also covers idempotent replays: submitting an already `IN_REVIEW` plan, closing an already `CLOSED` case, completing an already `COMPLETED` assignment."
        Design: Corner/state_machines/close_on_already_closed_case_rejected_from_terminal_state
        """
        ctx = _minor_case_in_deliberation(api)
        ctx["case"] = get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("NO_THREAT"),
                ctx["headers"]["threat_team_lead"],
            )
        )
        assert_case_state(ctx["case"], status="CLOSED")
        assert_risk_scores(ctx["case"], consensus=4.51, disposition="NO_THREAT")

        validate_error(
            api.close_threat_case(
                ctx["case"]["id"],
                build_closure(
                    closure_summary="Attempting to close a case that is already closed."
                ),
                ctx["headers"]["threat_team_lead"],
            ),
            ApiErrorId.CASE_INVALID_STATE,
            409,
        )
        validate_error(
            api.reassess_threat_case(
                ctx["case"]["id"],
                build_reassess(
                    reassess_reason="Attempting to reopen assessment on a closed case."
                ),
                ctx["headers"]["threat_team_lead"],
            ),
            ApiErrorId.CASE_INVALID_STATE,
            409,
        )

        assert_case_state(read_case(api, ctx), status="CLOSED", assessment_round=1)
