"""Optimistic concurrency control on plan-scoped writes, the response envelope,
and the validation pipeline's state/uniqueness/date-shape guards.

PRD §2.7 (OCC), §2.2/§2.3 (envelope), §2.8 (pipeline).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_fund,
    add_member,
    add_window,
    advance_clock,
    create_active_plan,
    create_crediting_run_payload,
    create_document_finding_payload,
    create_election,
    create_election_window_payload,
    create_plan,
    create_rabbi_trust_payload,
    create_specified_list_payload,
    enroll_participant,
    get_case,
    get_plan,
    is_iso8601_timestamp,
    make_participant_headers,
    open_account,
    open_separation_case,
    plan_version,
    setup_operational_failure,
    submit_election,
    validate_error,
    validate_paginated,
    validate_success,
)

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestOptimisticConcurrency:
    """PRD §2.7: "Four writes are guarded by optimistic concurrency control
    against the sponsoring plan's version: amending a plan's configuration,
    creating an election window, posting a crediting run, and creating a
    specified-employee list."
    """

    def test_occ_plan_amend_stale_version(self, api):
        """PRD §2.7: "If the plan's current `version` has advanced beyond that
        value — because another writer amended the plan, created a window,
        posted a run, or created a list in the interim — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building
        on a configuration baseline it has not observed."
        PRD §3.1: "through the concurrency-guarded write described in §2.7,
        which requires `expected_plan_version` and bumps the plan's `version`
        on success."

        After activation advances the version, a PATCH carrying the
        pre-activation version is rejected; one carrying the current version
        succeeds and advances the version by exactly one.

        Design: Corner/cross_cutting_layers/occ_plan_amend_stale_version
        """
        plan = create_plan(name="Plan OC", distribution_events_allowed=["SEPARATION"])
        observed_v0 = plan["version"]
        activated = validate_success(api.activate_plan(plan["id"], PS), 200)
        observed_v1 = activated["version"]
        assert observed_v1 == observed_v0 + 1

        stale = api.amend_plan(plan["id"], {
            "processing_lag_days": 45, "expected_plan_version": observed_v0}, PS)
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

        amended = validate_success(api.amend_plan(plan["id"], {
            "processing_lag_days": 45, "expected_plan_version": observed_v1}, PS), 200)
        assert amended["processing_lag_days"] == 45
        assert amended["version"] == observed_v1 + 1, "successful amend increments version by 1"

    def test_occ_window_create_stale_plan(self, api):
        """PRD §2.7: "If the plan's current `version` has advanced beyond that
        value — because another writer amended the plan, created a window,
        posted a run, or created a list in the interim — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.2: "Window creation is one of the four concurrency-guarded writes
        of §2.7 — the request must carry `expected_plan_version`".

        A window create carrying the version observed before the first window
        was created is stale; refetching and retrying succeeds.

        Design: Corner/cross_cutting_layers/occ_window_create_stale_plan
        """
        plan = create_active_plan(name="Plan OW", distribution_events_allowed=["SEPARATION"])
        observed = plan_version(plan["id"])
        window1 = add_window(plan["id"], plan_year=2027,
                             general_open_date="2026-10-01", general_close_date="2026-12-31")
        assert window1["status"] == "SCHEDULED"

        stale = api.create_election_window(create_election_window_payload(
            plan["id"], observed, plan_year=2028,
            general_open_date="2027-10-01", general_close_date="2027-12-31"), PS)
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

        fresh = plan_version(plan["id"])
        assert fresh == observed + 1, "the first window create advanced Plan.version"
        window2 = validate_success(api.create_election_window(create_election_window_payload(
            plan["id"], fresh, plan_year=2028,
            general_open_date="2027-10-01", general_close_date="2027-12-31"), PS), 201)
        assert window2["id"], "retry with the fresh version succeeds"

    def test_occ_crediting_run_stale_plan(self, api):
        """PRD §2.7: "If the plan's current `version` has advanced beyond that
        value — because another writer amended the plan, created a window,
        posted a run, or created a list in the interim — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.3: "Creation is concurrency-guarded by `expected_plan_version`
        per §2.7".

        After run R1 advances the plan version, a second run carrying the
        pre-R1 version is rejected; refetching and retrying succeeds.

        Design: Corner/cross_cutting_layers/occ_crediting_run_stale_plan
        """
        plan = create_active_plan(name="Plan OR", distribution_events_allowed=["SEPARATION"])
        observed = plan_version(plan["id"])
        run1 = validate_success(api.create_crediting_run(create_crediting_run_payload(
            plan["id"], observed, period_start="2027-01-01", period_end="2027-02-01"), BA), 201)
        assert run1["status"] == "POSTED"

        stale = api.create_crediting_run(create_crediting_run_payload(
            plan["id"], observed, period_start="2027-02-01", period_end="2027-03-01"), BA)
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

        fresh = plan_version(plan["id"])
        assert fresh == observed + 1, "the first run advanced Plan.version"
        run2 = validate_success(api.create_crediting_run(create_crediting_run_payload(
            plan["id"], fresh, period_start="2027-02-01", period_end="2027-03-01"), BA), 201)
        assert run2["status"] == "POSTED"

    def test_occ_specified_list_create_stale_plan(self, api):
        """PRD §2.7: "The check is evaluated before all business logic on those
        endpoints."
        PRD §3.5: "Creation is concurrency-guarded by `expected_plan_version`
        per §2.7, only one `DRAFT` list may exist per plan at a time
        (`ERR_DRAFT_LIST_EXISTS`)".

        A second list create carrying the version observed before the first
        list was created reports ERR_STALE_VERSION — the OCC check pre-empts
        the DRAFT-list uniqueness check that would also fail.

        Design: Corner/cross_cutting_layers/occ_specified_list_create_stale_plan
        """
        plan = create_active_plan(name="Plan OL", distribution_events_allowed=["SEPARATION"])
        observed = plan_version(plan["id"])
        list1 = validate_success(api.create_specified_employee_list(
            create_specified_list_payload(plan["id"], observed), CO), 201)
        assert list1["status"] == "DRAFT"

        stale = api.create_specified_employee_list(create_specified_list_payload(
            plan["id"], observed, identification_date="2027-12-31",
            effective_date="2028-04-01"), CO)
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)


class TestResponseEnvelope:
    def test_response_envelope_success_and_error_shape(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "data" carrying "error_id" and
        "message".

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        plan = create_plan(name="Plan ENV", distribution_events_allowed=["SEPARATION"])

        single = api.get_plan(plan["id"], PS)
        body = single.json()
        assert single.status_code == 200
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"], "non-empty request id"
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == plan["id"]

        data, meta = validate_paginated(api.list_plans(PS))
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"list meta carries {field}"
        assert isinstance(data, list)

        missing = api.get_plan(NON_EXISTENT_UUID, PS)
        err_body = missing.json()
        assert err_body["response_type"] == "error"
        assert isinstance(err_body["data"].get("error_id"), str)
        assert isinstance(err_body["data"].get("message"), str) and err_body["data"]["message"]
        validate_error(missing, "ERR_NOT_FOUND", expected_status=404)


class TestWorkflowStateGuards:
    def test_workflow_state_guard_error_sweep(self, api):
        """PRD §3.6: "Scheduling belongs to the `BenefitsAdministrator` and is
        permitted only from `EVENT_VERIFIED` (`ERR_DISTRIBUTION_STATE_INVALID`)".
        PRD §3.4: "requires the case to hold at least one service record in
        `EVIDENCE_SUBMITTED` or `REOPENED` status, else `ERR_CASE_STATE_INVALID`".
        PRD §3.8: "Quantification is the first compliance step, performed by a
        `ComplianceOfficer` on an `IDENTIFIED` case (`ERR_FAILURE_STATE_INVALID`)"
        and assessment "may assess a `QUANTIFIED` case
        (`ERR_FAILURE_STATE_INVALID`)".
        PRD §3.9: "adjudication from any state other than `CORRECTION_FILED` is
        rejected with `ERR_FINDING_STATE_INVALID`".
        PRD §3.1: "each of these transitions requires the matching source state
        and is otherwise rejected with `ERR_PLAN_STATE_INVALID`".
        PRD §3.3: "a participant who is `SEPARATED` — and only one who is
        `SEPARATED`, else `ERR_PARTICIPANT_STATE_INVALID` — may be returned to
        `ACTIVE`".

        Six distinct workflow state guards each reject from the wrong state.

        Design: Corner/errors/workflow_state_guard_error_sweep
        """
        plan = create_active_plan(name="Plan WG",
                                  distribution_events_allowed=["FIXED_TIME", "SEPARATION"])
        participant = enroll_participant(plan["id"], employee_ref="EMP-WG")
        account = open_account(participant["id"], plan["id"])

        request = validate_success(api.create_distribution_request(
            {"account_id": account["id"], "event_type": "FIXED_TIME",
             "fixed_date": "2027-06-01"},
            make_participant_headers(participant["id"])), 201)

        case = open_separation_case(participant["id"], "2027-03-15", "RESIGNATION")
        assert case["status"] == "OPEN"

        failure = setup_operational_failure(account["id"], failure_type="EXCESS_DEFERRAL",
                                            failure_date="2026-06-01", amount_cents=5000)
        finding = validate_success(api.create_document_finding(
            create_document_finding_payload(plan["id"], description="Missing delay language",
                                            failure_year=2026), CO), 201)

        e_sched = api.schedule_distribution(request["id"], BA)
        validate_error(e_sched, "ERR_DISTRIBUTION_STATE_INVALID", expected_status=409)

        e_det = api.determine_case(case["id"], {"outcome": "CONFIRMED_SEPARATION"}, CO)
        validate_error(e_det, "ERR_CASE_STATE_INVALID", expected_status=409)

        e_assess = api.assess_inclusion(failure["id"], CO2)
        validate_error(e_assess, "ERR_FAILURE_STATE_INVALID", expected_status=409)

        e_adj = api.adjudicate_finding(finding["id"], {"outcome": "CORRECTED"}, PS)
        validate_error(e_adj, "ERR_FINDING_STATE_INVALID", expected_status=409)

        e_resume = api.resume_plan(plan["id"], PS)
        validate_error(e_resume, "ERR_PLAN_STATE_INVALID", expected_status=409)

        # The participant is SEPARATION_REVIEW while the case is open.
        assert get_case(case["id"])["status"] == "OPEN"
        e_rehire = api.rehire_participant(participant["id"], BA)
        validate_error(e_rehire, "ERR_PARTICIPANT_STATE_INVALID", expected_status=409)


class TestUniquenessConstraints:
    def test_uniqueness_constraint_error_sweep(self, api):
        """PRD §3.2: "one election per participant per window, with a repeat
        attempt rejected as `ERR_DUPLICATE_ELECTION`".
        PRD §3.4: "A participant may carry at most one open case at a time —
        open meaning `OPEN`, `EVIDENCE_SUBMITTED`, or `REOPENED` — and a second
        attempt is rejected with `ERR_OPEN_CASE_EXISTS`."
        PRD §3.7: "established once per plan by a `PlanSponsor` — a second trust
        for the same plan is rejected with `ERR_TRUST_EXISTS`".
        PRD §3.5: "only one `DRAFT` list may exist per plan at a time
        (`ERR_DRAFT_LIST_EXISTS`)".
        PRD §3.5: "one row per participant per list (`ERR_DUPLICATE_MEMBER`)".

        Five uniqueness constraints fire independently.

        Design: Corner/errors/uniqueness_constraint_error_sweep
        """
        plan = create_active_plan(name="Plan UQ", distribution_events_allowed=["SEPARATION"])
        fund = add_fund(plan["id"])
        window = add_window(plan["id"])
        p1 = enroll_participant(plan["id"], employee_ref="EMP-UQ1")
        p2 = enroll_participant(plan["id"], employee_ref="EMP-UQ2")

        advance_clock("2026-10-15T00:00:00Z")  # window OPEN
        election = create_election(p1["id"], window["id"], fund["id"])
        case = open_separation_case(p2["id"], "2027-03-15", "RESIGNATION")
        trust = validate_success(api.create_rabbi_trust(
            create_rabbi_trust_payload(plan["id"], funding_target_bp=10000), PS), 201)
        lst = validate_success(api.create_specified_employee_list(
            create_specified_list_payload(plan["id"], plan_version(plan["id"])), CO), 201)
        add_member(lst["id"], p1["id"], "FIVE_PERCENT_OWNER", 30000000)

        e_dup_el = api.create_deferral_election({
            "participant_id": p1["id"], "election_window_id": window["id"],
            "election_type": "GENERAL", "deferral_percent_bp": 2500,
            "notional_fund_id": fund["id"],
        }, make_participant_headers(p1["id"]))
        validate_error(e_dup_el, "ERR_DUPLICATE_ELECTION", expected_status=409)

        e_case = api.create_separation_case({
            "participant_id": p2["id"], "alleged_separation_date": "2027-04-01",
            "trigger_reason": "TERMINATION"}, BA)
        validate_error(e_case, "ERR_OPEN_CASE_EXISTS", expected_status=409)

        e_trust = api.create_rabbi_trust(
            create_rabbi_trust_payload(plan["id"], funding_target_bp=5000), PS)
        validate_error(e_trust, "ERR_TRUST_EXISTS", expected_status=409)

        e_list = api.create_specified_employee_list(create_specified_list_payload(
            plan["id"], plan_version(plan["id"]), identification_date="2027-12-31",
            effective_date="2028-04-01"), CO)
        validate_error(e_list, "ERR_DRAFT_LIST_EXISTS", expected_status=409)

        e_member = api.add_list_member(lst["id"], {
            "participant_id": p1["id"], "basis": "OFFICER",
            "annual_compensation_cents": 30000000}, CO)
        validate_error(e_member, "ERR_DUPLICATE_MEMBER", expected_status=409)


class TestDateShapeRules:
    def test_date_shape_validation_sweep(self, api):
        """PRD §3.2: "the general close date must fall inside the calendar year
        immediately preceding `plan_year`, and the open date must not fall after
        the close date; either defect is rejected with
        `ERR_INVALID_WINDOW_DATES`."
        PRD §3.2: "the two are supplied together or not at all, and when present
        the performance period must span at least 365 days, again on pain of
        `ERR_INVALID_WINDOW_DATES`."
        PRD §3.5: "the latter must fall strictly after the identification date
        and no later than 120 days after it, inclusive of that 120th day, else
        `ERR_INVALID_EFFECTIVE_DATE`."
        PRD §2.6: "The target instant must not be earlier than the current
        logical clock — time never runs backward — and a regressive request is
        rejected with `ERR_CLOCK_REGRESSION`."

        Design: Corner/validations/date_shape_validation_sweep
        """
        plan = create_active_plan(name="Plan DS", distribution_events_allowed=["SEPARATION"])

        wrong_year = api.create_election_window(create_election_window_payload(
            plan["id"], plan_version(plan["id"]), plan_year=2027,
            general_open_date="2026-10-01", general_close_date="2027-01-15"), PS)
        validate_error(wrong_year, "ERR_INVALID_WINDOW_DATES", expected_status=422)

        short_perf = api.create_election_window(create_election_window_payload(
            plan["id"], plan_version(plan["id"]), plan_year=2027,
            general_open_date="2026-10-01", general_close_date="2026-12-31",
            performance_period_start="2027-01-01", performance_period_end="2027-06-30"), PS)
        validate_error(short_perf, "ERR_INVALID_WINDOW_DATES", expected_status=422)

        not_strictly_after = api.create_specified_employee_list(
            create_specified_list_payload(plan["id"], plan_version(plan["id"]),
                                          identification_date="2026-12-31",
                                          effective_date="2026-12-31"), CO)
        validate_error(not_strictly_after, "ERR_INVALID_EFFECTIVE_DATE", expected_status=422)

        regression = api.set_clock("2026-07-01T00:00:00Z", ADMIN)
        validate_error(regression, "ERR_CLOCK_REGRESSION", expected_status=422)
