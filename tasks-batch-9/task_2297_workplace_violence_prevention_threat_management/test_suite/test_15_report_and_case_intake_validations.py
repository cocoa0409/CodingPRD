"""Channel-conditional reporting, case uniqueness, seat integrity and the band mapping on decide."""

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ANONYMOUS_HEADERS,
    ANONYMOUS_HEADERS_WITHOUT_USER_ID,
    ApiClient,
    ApiErrorId,
    assert_case_state,
    assert_report_dimensions,
    assert_risk_scores,
    assert_seat_ballot,
    assert_severity,
    assert_total_count,
    build_decision,
    build_incident_report,
    build_team_assignment,
    build_threat_case,
    read_case,
    setup_deliberating_case,
    setup_employee,
    setup_fully_seated_case,
    setup_open_case,
    setup_programme,
)

#: A quiet lobby episode: unweaponed, uninjured and client typology, so six points and MINOR.
LOBBY_REPORT = {
    "channel": "SUPERVISOR",
    "occurred_at": "2026-07-29T08:00:00Z",
    "narrative": "Client refused to leave the lobby and shouted at the receptionist.",
    "incident_type": "TYPE_2_CLIENT",
    "weapon_involved": False,
    "injury_level": "NONE",
}


def _report_naming_nobody(ctx: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """A filing payload that leaves the reporter field out of the body altogether."""
    payload = build_incident_report(
        ctx["worksite"]["id"], ctx["work_area"]["id"], **overrides
    )
    del payload["reporter_employee_id"]
    return payload


class TestReportingChannelConditional:
    """Whether a reporter is required is decided by the channel, so both arms can be broken."""

    def test_naming_a_reporter_on_the_dropbox_and_omitting_one_on_the_web_form_both_fail(
        self, api: ApiClient
    ) -> None:
        """The same code answers opposite mistakes, and neither is a static request-shape failure.

        PRD: "For every channel other than `ANONYMOUS_DROPBOX` a reporter must be named, and for `ANONYMOUS_DROPBOX` it must be absent; either mistake is refused with `ERR_REPORTER_REQUIRED`."
        Design: Corner/validations/anonymous_dropbox_report_with_a_reporter_rejected
        """
        ctx = setup_programme(api)

        named = api.create_incident_report(
            build_incident_report(
                ctx["worksite"]["id"],
                ctx["work_area"]["id"],
                ctx["rep"]["id"],
                channel="ANONYMOUS_DROPBOX",
                occurred_at="2026-07-30T14:00:00Z",
                narrative="Anonymous note naming the reporter, which defeats the point of the dropbox.",
                incident_type="TYPE_3_COWORKER",
                weapon_involved=False,
                injury_level="NONE",
            ),
            ANONYMOUS_HEADERS,
        )

        validate_error(named, ApiErrorId.REPORTER_REQUIRED, 422)
        assert named.json()["data"]["error_id"] != ApiErrorId.INVALID_REQUEST

        unnamed = api.create_incident_report(
            _report_naming_nobody(
                ctx,
                channel="WEB_FORM",
                occurred_at="2026-07-30T14:00:00Z",
                narrative="Web form submission with no reporter identified.",
                incident_type="TYPE_3_COWORKER",
                weapon_involved=False,
                injury_level="NONE",
            ),
            ctx["headers"]["employee"],
        )

        validate_error(unnamed, ApiErrorId.REPORTER_REQUIRED, 422)
        assert unnamed.json()["data"]["error_id"] != ApiErrorId.INVALID_REQUEST
        assert_total_count(
            api.list_incident_reports(
                ctx["headers"]["safety_officer"], {"worksite_id": ctx["worksite"]["id"]}
            ),
            0,
        )

    def test_the_dropbox_accepts_an_unidentified_filing_and_still_classifies_it(
        self, api: ApiClient
    ) -> None:
        """No X-User-ID at all is accepted on the one opaque role, and the stored claimant stays null.

        PRD: "The consequence is worth stating plainly, because it constrains a later workflow: an anonymous report can never support a retaliation claim, because there is no claimant to protect."
        Design: Corner/validations/anonymous_dropbox_report_without_a_reporter_is_accepted
        """
        ctx = setup_programme(api)

        report = get_success_data(
            api.create_incident_report(
                _report_naming_nobody(
                    ctx,
                    channel="ANONYMOUS_DROPBOX",
                    occurred_at="2026-07-30T14:00:00Z",
                    narrative="Someone on the night shift has been showing a knife to colleagues.",
                    incident_type="TYPE_3_COWORKER",
                    weapon_involved=True,
                    injury_level="MEDICAL_TREATMENT",
                ),
                ANONYMOUS_HEADERS_WITHOUT_USER_ID,
            ),
            201,
        )

        assert report["reporter_employee_id"] is None
        assert report["channel"] == "ANONYMOUS_DROPBOX"
        assert_severity(report, 60, "CRITICAL", log_required=True)
        assert_report_dimensions(
            report, triage_status="NEW", retaliation_status="NOT_ALLEGED"
        )
        assert report["retaliation_claimant_employee_id"] is None


class TestCaseUniquenessOnTheReport:
    """One code covers both a second case on one report and a first case on an untriaged one."""

    def test_a_second_case_and_a_case_on_a_new_report_are_both_refused(
        self, api: ApiClient
    ) -> None:
        """The open case blocks its own report and the untriaged report blocks itself.

        PRD: "The report's `triage_status` must be `ESCALATED` and no non-`CLOSED` case may already exist for that report; either violation is refused with `ERR_CASE_ALREADY_OPEN_FOR_REPORT`."
        Design: Corner/validations/second_case_for_the_same_report_returns_case_already_open
        """
        ctx = setup_open_case(api)
        lead_headers = ctx["headers"]["threat_team_lead"]

        validate_error(
            api.create_threat_case(
                build_threat_case(ctx["report"]["id"], ctx["lead"]["id"]), lead_headers
            ),
            ApiErrorId.CASE_ALREADY_OPEN_FOR_REPORT,
            409,
        )

        untriaged = get_success_data(
            api.create_incident_report(
                build_incident_report(
                    ctx["worksite"]["id"],
                    ctx["work_area"]["id"],
                    ctx["rep"]["id"],
                    **LOBBY_REPORT,
                ),
                ctx["headers"]["employee"],
            )
        )
        assert_severity(untriaged, 6, "MINOR", log_required=False)
        assert_report_dimensions(untriaged, triage_status="NEW")

        validate_error(
            api.create_threat_case(
                build_threat_case(untriaged["id"], ctx["lead"]["id"]), lead_headers
            ),
            ApiErrorId.CASE_ALREADY_OPEN_FOR_REPORT,
            409,
        )

        assert_total_count(
            api.list_threat_cases(
                lead_headers, {"incident_report_id": ctx["report"]["id"]}
            ),
            1,
        )
        assert_total_count(
            api.list_threat_cases(lead_headers, {"incident_report_id": untriaged["id"]}), 0
        )


class TestSeatUniqueness:
    """Two uniqueness rules on one roster, separated by which one the request breaks."""

    def test_re_seating_a_member_and_seating_a_second_lead_fail_differently(
        self, api: ApiClient
    ) -> None:
        """A held seat answers duplicate-assignment; an unseated worker asking for LEAD answers duplicate-lead.

        PRD: "An employee may hold at most one `ASSIGNED` seat per case, or the request is refused with `ERR_DUPLICATE_TEAM_ASSIGNMENT`."
        Design: Corner/validations/duplicate_team_seat_and_second_lead_rejected
        """
        ctx = setup_fully_seated_case(api)
        lead_headers = ctx["headers"]["threat_team_lead"]
        seated = {"case_id": ctx["case"]["id"], "status": "ASSIGNED"}
        assert_total_count(api.list_team_assignments(lead_headers, seated), 5)
        assert_case_state(read_case(api, ctx), status="OPEN", quorum_met=True)

        validate_error(
            api.create_team_assignment(
                ctx["case"]["id"],
                build_team_assignment(ctx["sec"]["id"], "SECURITY", "ADVISOR"),
                lead_headers,
            ),
            ApiErrorId.DUPLICATE_TEAM_ASSIGNMENT,
            409,
        )
        newcomer = setup_employee(
            api,
            ctx["worksite"]["id"],
            ctx["work_area"]["id"],
            full_name="Tara Hall",
            job_function="ADMIN",
        )

        second_lead = api.create_team_assignment(
            ctx["case"]["id"],
            build_team_assignment(newcomer["id"], "HR", "LEAD"),
            lead_headers,
        )

        validate_error(second_lead, ApiErrorId.DUPLICATE_TEAM_LEAD, 409)
        assert (
            second_lead.json()["data"]["error_id"]
            != ApiErrorId.DUPLICATE_TEAM_ASSIGNMENT
        )
        assert_total_count(api.list_team_assignments(lead_headers, seated), 5)
        assert_case_state(read_case(api, ctx), quorum_met=True)

    def test_neither_the_reporter_nor_the_subject_may_take_a_seat(
        self, api: ApiClient
    ) -> None:
        """The subject sits on the case and the reporter one hop further out, and both are barred.

        PRD: "Nobody evaluates their own case: a seat naming the case's `subject_employee_id`, its `protected_employee_id`, or the `reporter_employee_id` of the underlying report is refused with `ERR_SUBJECT_CONFLICT_OF_INTEREST`."
        Design: Corner/validations/team_seat_naming_the_reporter_returns_conflict_of_interest
        """
        ctx = setup_open_case(api)
        lead_headers = ctx["headers"]["threat_team_lead"]
        assert ctx["case"]["subject_employee_id"] == ctx["subj"]["id"]
        assert ctx["case"]["protected_employee_id"] == ctx["rep"]["id"]

        reporter_seat = api.create_team_assignment(
            ctx["case"]["id"],
            build_team_assignment(ctx["rep"]["id"], "OPERATIONS", "VOTING_MEMBER"),
            lead_headers,
        )

        validate_error(reporter_seat, ApiErrorId.SUBJECT_CONFLICT_OF_INTEREST, 409)
        assert reporter_seat.json()["data"]["error_id"] != ApiErrorId.EMPLOYEE_NOT_FOUND

        subject_seat = api.create_team_assignment(
            ctx["case"]["id"],
            build_team_assignment(ctx["subj"]["id"], "OPERATIONS", "ADVISOR"),
            lead_headers,
        )

        validate_error(subject_seat, ApiErrorId.SUBJECT_CONFLICT_OF_INTEREST, 409)
        assert subject_seat.json()["data"]["error_id"] != ApiErrorId.EMPLOYEE_NOT_FOUND
        assert_total_count(
            api.list_team_assignments(lead_headers, {"case_id": ctx["case"]["id"]}), 0
        )
        assert_case_state(read_case(api, ctx), status="OPEN", quorum_met=False)


class TestDispositionBandMapping:
    """The mapping is enforced against the consensus score the decide call has just computed."""

    def test_a_monitor_disposition_on_a_high_consensus_is_refused_and_writes_nothing(
        self, api: ApiClient
    ) -> None:
        """The refused decide leaves the case in DELIBERATION with no consensus and no ballot shares.

        PRD: "A requested `disposition` that does not match the mapping and arrives without an `override_justification` is refused with `ERR_DISPOSITION_BAND_MISMATCH`."
        Design: Corner/validations/disposition_not_matching_the_band_returns_band_mismatch
        """
        ctx = setup_deliberating_case(api)
        lead_headers = ctx["headers"]["threat_team_lead"]
        security_seat_id = ctx["seats"]["sec"]["id"]
        operations_seat_id = ctx["seats"]["ops"]["id"]
        assert_risk_scores(read_case(api, ctx), interim=42.00, risk_band="MODERATE")

        validate_error(
            api.decide_threat_case(
                ctx["case"]["id"], build_decision("MONITOR"), lead_headers
            ),
            ApiErrorId.DISPOSITION_BAND_MISMATCH,
            409,
        )

        refused = read_case(api, ctx)
        assert_case_state(refused, status="DELIBERATION", ballot_count_current_round=5)
        assert refused["consensus_risk_score"] is None
        assert refused["disposition"] is None
        untouched_seat = get_success_data(
            api.get_team_assignment(security_seat_id, lead_headers)
        )
        assert untouched_seat["ballot_share"] is None

        decided = get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"], build_decision("ELEVATED_RISK"), lead_headers
            )
        )

        assert_case_state(decided, status="MONITORING")
        assert_risk_scores(
            decided, consensus=60.94, risk_band="HIGH", disposition="ELEVATED_RISK"
        )
        assert_seat_ballot(
            get_success_data(api.get_team_assignment(security_seat_id, lead_headers)),
            ballot_value="IMMINENT",
            ballot_round=1,
            ballot_weight=1.325,
            ballot_share=24.56,
        )
        assert_seat_ballot(
            get_success_data(api.get_team_assignment(operations_seat_id, lead_headers)),
            ballot_value="ELEVATED",
            ballot_weight=0.775,
            ballot_share=9.83,
        )
