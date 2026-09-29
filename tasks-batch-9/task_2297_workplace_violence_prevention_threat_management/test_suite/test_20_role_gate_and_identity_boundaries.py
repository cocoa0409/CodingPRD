"""The role gate on each exclusive operation, the two opaque extremes and the identity check behind them."""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
)

from test_helpers import (
    ANONYMOUS_HEADERS,
    COMPLIANCE_AUDITOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_case_state,
    assert_plan_state,
    assert_readiness,
    assert_report_dimensions,
    assert_risk_scores,
    assert_severity,
    assert_total_count,
    assign_training,
    build_convene,
    build_hazard_validation,
    build_incident_report,
    build_plan_activation,
    build_plan_revision_return,
    build_prevention_plan,
    build_protective_action,
    build_separation,
    build_training_completion,
    build_triage,
    build_work_area,
    build_worksite,
    make_employee_headers,
    read_case,
    read_employee,
    read_plan,
    setup_active_plan,
    setup_employee,
    setup_filed_report,
    setup_fully_seated_case,
    setup_programme,
    setup_submitted_plan,
    setup_training_cohort,
)

#: A second, benign area a ProgramAdmin adds after the safety officer has been separated.
BREAK_ROOM = {
    "name": "Break Room",
    "job_function": "ADMIN",
    "public_access_flag": False,
    "lone_worker_flag": False,
    "night_shift_flag": False,
    "occupancy_cap": 6,
}


def _dropbox_filing(worksite_id: str, work_area_id: str, **overrides: Any) -> Dict[str, Any]:
    """An anonymous filing whose payload leaves the reporter field out altogether."""
    payload = build_incident_report(worksite_id, work_area_id, **overrides)
    del payload["reporter_employee_id"]
    return payload


class TestApprovalOperationsBelongToTheSiteManager:
    """The author of the paperwork cannot approve it, and the role gate says so first."""

    def test_the_safety_officer_is_turned_away_from_all_three_approvals(
        self, api: ApiClient
    ) -> None:
        """Activate, return and validate all answer on authority, never on the actor comparison behind them.

        PRD: "Once the headers are accepted, the role is matched against the endpoint's authorised role list from §4; a role that is not listed is rejected with `ERR_UNAUTHORIZED` (403)."
        Design: Corner/rbac/safety_officer_cannot_activate_or_validate_their_own_work
        """
        ctx = setup_submitted_plan(api)
        officer = ctx["headers"]["safety_officer"]
        plan_id = ctx["plan"]["id"]
        assessment_id = ctx["hazard_assessment"]["id"]
        assert ctx["plan"]["submitted_by_employee_id"] == ctx["so"]["id"]

        self_approval = api.activate_prevention_plan(
            plan_id, build_plan_activation(activation_note="Approving my own plan."), officer
        )

        validate_error(self_approval, ApiErrorId.UNAUTHORIZED, 403)
        assert (
            self_approval.json()["data"]["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES
        )
        validate_error(
            api.return_prevention_plan_for_revision(
                plan_id,
                build_plan_revision_return(revision_reason="Sending my own plan back."),
                officer,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.validate_hazard_assessment(
                assessment_id,
                build_hazard_validation(walkthrough_note="Validating my own screening."),
                officer,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        assert_plan_state(read_plan(api, ctx), status="IN_REVIEW")
        assert (
            get_success_data(
                api.get_hazard_assessment(assessment_id, ctx["headers"]["site_manager"])
            )["status"]
            == "SCREENING"
        )

        activated = get_success_data(
            api.activate_prevention_plan(
                plan_id, build_plan_activation(), ctx["headers"]["site_manager"]
            )
        )

        assert_plan_state(activated, status="ACTIVE", compliance_posture="OPEN")
        assert activated["activated_by_employee_id"] == ctx["sm"]["id"]


class TestAnonymousMayOnlyWrite:
    """The reporting channel is a one-way door: the filing succeeds, every read is refused."""

    def test_the_dropbox_caller_cannot_read_back_the_report_it_is_allowed_to_file(
        self, api: ApiClient
    ) -> None:
        """List, single read and triage all answer 403, while the untraceable filing is classified normally.

        PRD: "`Anonymous` may file an incident report and do nothing else."
        Design: Corner/rbac/anonymous_cannot_read_any_incident_report_it_filed
        """
        ctx = setup_filed_report(api)
        worksite_id = ctx["worksite"]["id"]

        validate_error(
            api.list_incident_reports(ANONYMOUS_HEADERS, {"worksite_id": worksite_id}),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.get_incident_report(ctx["report"]["id"], ANONYMOUS_HEADERS),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.triage_incident_report(
                ctx["report"]["id"],
                build_triage("ESCALATE", triage_note="Anonymous caller trying to triage."),
                ANONYMOUS_HEADERS,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        filed = get_success_data(
            api.create_incident_report(
                _dropbox_filing(
                    worksite_id,
                    ctx["work_area"]["id"],
                    channel="ANONYMOUS_DROPBOX",
                    occurred_at="2026-07-31T22:00:00Z",
                    narrative="A supervisor threatened a colleague in the loading corridor.",
                    incident_type="TYPE_3_COWORKER",
                    weapon_involved=False,
                    injury_level="NONE",
                ),
                ANONYMOUS_HEADERS,
            ),
            201,
        )

        assert_severity(filed, 12, "MINOR", log_required=False)
        assert filed["reporter_employee_id"] is None
        assert_report_dimensions(
            filed, triage_status="NEW", retaliation_status="NOT_ALLEGED"
        )


class TestComplianceAuditorReadsEverythingAndWritesNothing:
    """The inspector's opaque identity buys breadth of sight and no authority at all."""

    def test_three_writes_across_three_domains_are_all_refused_on_authority(
        self, api: ApiClient
    ) -> None:
        """A plan, a worksite and the nightly sweep are refused as 403 rather than 401, and nothing moves.

        PRD: "`ComplianceAuditor` is a read-only regulatory inspector with visibility into every collection and no write capability at all."
        Design: Corner/rbac/compliance_auditor_cannot_write_any_row
        """
        ctx = setup_active_plan(api)
        worksite_id = ctx["worksite"]["id"]

        drafting = api.create_prevention_plan(
            build_prevention_plan(worksite_id, effective_date="2026-09-01T00:00:00Z"),
            COMPLIANCE_AUDITOR_HEADERS,
        )

        validate_error(drafting, ApiErrorId.UNAUTHORIZED, 403)
        assert drafting.json()["data"]["error_id"] != ApiErrorId.UNAUTHENTICATED
        validate_error(
            api.create_worksite(
                build_worksite(name="Inspector Depot", employee_count=5),
                COMPLIANCE_AUDITOR_HEADERS,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.daily_run(COMPLIANCE_AUDITOR_HEADERS), ApiErrorId.UNAUTHORIZED, 403
        )

        plans = assert_total_count(
            api.list_prevention_plans(
                COMPLIANCE_AUDITOR_HEADERS, {"worksite_id": worksite_id}
            ),
            1,
        )
        assert_total_count(api.list_worksites(COMPLIANCE_AUDITOR_HEADERS), 1)
        assert plans[0]["id"] == ctx["plan"]["id"]
        assert_readiness(read_plan(api, ctx), score=79.90, inspection_ready=True)


class TestProgramAdminHoldsNoCaseAuthority:
    """Bootstrapping reference data and driving the clock is the whole of the mandate."""

    def test_convene_triage_and_measure_are_all_refused_for_the_operator_role(
        self, api: ApiClient
    ) -> None:
        """The triage attempt proves the point: the report is already ESCALATED yet answers on authority.

        PRD: "`ProgramAdmin` bootstraps organisational reference data — worksites, work areas, employees, training modules — and drives the logical clock and the nightly sweep, but holds no clinical, HR or threat-assessment authority."
        Design: Corner/rbac/program_admin_cannot_exercise_threat_team_authority
        """
        ctx = setup_fully_seated_case(api)
        case_id = ctx["case"]["id"]
        assert_report_dimensions(ctx["report"], triage_status="ESCALATED")

        validate_error(
            api.convene_threat_case(
                case_id,
                build_convene(convene_note="Program admin opening the meeting."),
                PROGRAM_ADMIN_HEADERS,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        retriage = api.triage_incident_report(
            ctx["report"]["id"],
            build_triage("ESCALATE", triage_note="Program admin re-triaging."),
            PROGRAM_ADMIN_HEADERS,
        )

        validate_error(retriage, ApiErrorId.UNAUTHORIZED, 403)
        assert retriage.json()["data"]["error_id"] != ApiErrorId.REPORT_INVALID_STATE
        validate_error(
            api.create_case_action(
                build_protective_action(
                    case_id,
                    "SCHEDULE_CHANGE",
                    ctx["subj"]["id"],
                    "2026-08-02T00:00:00Z",
                    "2026-08-03T00:00:00Z",
                    note="Program admin scheduling a change.",
                ),
                PROGRAM_ADMIN_HEADERS,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        untouched = read_case(api, ctx)
        assert_case_state(untouched, status="OPEN", quorum_met=True)
        assert untouched["interim_risk_score"] is None

        convened = get_success_data(
            api.convene_threat_case(
                case_id, build_convene(), ctx["headers"]["threat_team_lead"]
            )
        )

        assert_case_state(convened, status="ASSESSING", assessment_round=1)
        assert_risk_scores(convened, interim=42.00, risk_band="MODERATE")


class TestSeparationRevokesAuthority:
    """The identity check reads the backing row, so offboarding is also a permissions event."""

    def test_the_separated_officers_id_fails_even_a_read_while_the_operator_role_carries_on(
        self, api: ApiClient
    ) -> None:
        """Write, read and filing all answer 403 on the stale identity; the opaque role skips the check.

        PRD: "For all seven, the identifier must resolve to an existing `Employee` whose `employment_status` is `ACTIVE`; a separated worker's identifier can no longer act, and such a request is rejected with `ERR_UNAUTHORIZED` (403)."
        Design: Corner/rbac/separated_employee_id_cannot_act_while_opaque_roles_still_can
        """
        ctx = setup_programme(api)
        worksite_id = ctx["worksite"]["id"]
        officer_id = ctx["so"]["id"]
        separated = get_success_data(
            api.separate_employee(
                officer_id,
                build_separation(separation_reason="Left the safety team last month."),
                ctx["headers"]["hr_partner"],
            )
        )
        assert separated["employment_status"] == "SEPARATED"

        validate_error(
            api.create_prevention_plan(
                build_prevention_plan(worksite_id), ctx["headers"]["safety_officer"]
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.list_prevention_plans(
                ctx["headers"]["safety_officer"], {"worksite_id": worksite_id}
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        filing = api.create_incident_report(
            build_incident_report(
                worksite_id,
                ctx["work_area"]["id"],
                officer_id,
                weapon_involved=False,
                injury_level="NONE",
                narrative="Filed after separation, which the identity gate refuses.",
            ),
            make_employee_headers(officer_id),
        )

        validate_error(filing, ApiErrorId.UNAUTHORIZED, 403)
        assert filing.json()["data"]["error_id"] != ApiErrorId.EMPLOYEE_NOT_FOUND

        late_area = get_success_data(
            api.create_work_area(
                build_work_area(worksite_id, **BREAK_ROOM), PROGRAM_ADMIN_HEADERS
            ),
            201,
        )

        assert late_area["name"] == "Break Room"
        assert_total_count(
            api.list_prevention_plans(
                COMPLIANCE_AUDITOR_HEADERS, {"worksite_id": worksite_id}
            ),
            0,
        )


class TestRoleGateLeaksNoExistence:
    """One identifier, two roles, two status codes, and the difference is authority alone."""

    def test_the_unauthorised_caller_learns_nothing_about_the_identifier_it_probed(
        self, api: ApiClient
    ) -> None:
        """The safety officer gets 403 on an identifier that does not exist; the site manager gets the 404.

        PRD: "This outranks every existence, state and business rule, so a wrong-role call against a non-existent identifier returns 403 and not 404."
        Design: Corner/rbac/wrong_role_on_a_nonexistent_id_returns_unauthorized_before_not_found
        """
        ctx = setup_programme(api)

        probe = api.activate_prevention_plan(
            NON_EXISTENT_UUID,
            build_plan_activation(activation_note="Probing an id I am not allowed to touch."),
            ctx["headers"]["safety_officer"],
        )

        validate_error(probe, ApiErrorId.UNAUTHORIZED, 403)
        assert probe.json()["data"]["error_id"] != ApiErrorId.PREVENTION_PLAN_NOT_FOUND

        permitted = api.activate_prevention_plan(
            NON_EXISTENT_UUID,
            build_plan_activation(
                activation_note="Same id, from the role that owns the operation."
            ),
            ctx["headers"]["site_manager"],
        )

        validate_error(permitted, ApiErrorId.PREVENTION_PLAN_NOT_FOUND, 404)
        assert_total_count(api.list_prevention_plans(COMPLIANCE_AUDITOR_HEADERS), 0)


class TestHRPartnerDrivesTheTrainingAndOffboardingChain:
    """Two exclusive operations and one shared one where HR acts for the worker."""

    def test_hr_assigns_completes_and_then_separates_the_same_worker(
        self, api: ApiClient
    ) -> None:
        """The completion recorded by HR is never an ownership failure, and the offboarding unwinds nothing.

        PRD: "Completing an assignment is done by the learner themselves or on their behalf by an `HRPartner`, and carries a single input: `score`."
        Design: Corner/rbac/hr_partner_owns_training_assignment_and_separation_end_to_end
        """
        ctx = setup_training_cohort(api)
        hr_headers = ctx["headers"]["hr_partner"]
        learner = setup_employee(
            api,
            ctx["worksite"]["id"],
            ctx["work_area"]["id"],
            full_name="Wendy Cole",
            job_function="ADMIN",
        )
        assert learner["training_current"] is False

        assignment = assign_training(
            api, ctx, learner["id"], due_at="2026-08-20T00:00:00Z"
        )

        assert assignment["status"] == "ASSIGNED"
        assert assignment["assigned_at"] == "2026-08-01T00:00:00Z"
        assert assignment["attempt_count"] == 0
        assert read_employee(api, learner["id"])["version"] == learner["version"] + 1

        completion = api.complete_training_assignment(
            assignment["id"], build_training_completion(84), hr_headers
        )
        completed = get_success_data(completion)

        assert completed["status"] == "COMPLETED"
        assert completed["expires_at"] == "2027-08-01T00:00:00Z"
        assert completed["scenario_set_version"] == "2026.1"
        assert completed["attempt_count"] == 1
        assert read_employee(api, learner["id"])["training_current"] is True

        offboarded = get_success_data(
            api.separate_employee(
                learner["id"],
                build_separation(separation_reason="Transferred to another employer."),
                hr_headers,
            )
        )

        assert offboarded["employment_status"] == "SEPARATED"
        assert offboarded["escort_committed_minutes"] == 0
        assert offboarded["active_restriction_count"] == 0
