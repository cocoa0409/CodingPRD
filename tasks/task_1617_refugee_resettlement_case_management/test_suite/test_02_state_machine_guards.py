"""State-machine guards (PRD §2.5, §3.2–§3.7): invalid transitions, terminal
lockdown, and repeat triggers across cases, applications, transfers,
sessions, reports, benchmarks, and housing setups.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    date_part,
    make_case,
    setup_arrived_case,
    get_case, list_case_benchmarks, get_benchmark_by_type, make_benefit_application,
    transition_application, make_orientation_session,
    complete_orientation_session, list_orientation_sessions, make_case_transfer,
    respond_case_transfer, make_federal_report,
    set_clock, make_housing_setup,
    make_housing_unit, vacate_setup, waive_benchmark,
)
from test_helpers.fixtures import CM, HC, AD, FO


class TestCaseArriveTwice:
    def test_second_arrive_rejected(self, api):
        """PRD §3.3: "The case must be `PRE_ARRIVAL` — recording arrival a
        second time is rejected with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/case_arrive_twice_returns_invalid_state
        """
        ctx = setup_arrived_case(case_number="CASE-SM1", household_size=1)
        case_id = ctx["case"]["id"]
        resp = api.arrive_case(case_id, {"actual_arrival_date": "2026-08-11"}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_second_arrive_preserves_first_arrival_and_benchmarks(self, api):
        """PRD §3.3: "The case must be `PRE_ARRIVAL` — recording arrival a
        second time is rejected with `ERR_INVALID_STATE`" and "Every benchmark
        is stored with two due dates computed at seeding time from its
        `due_rule`".

        Design: Corner/state_machines/case_arrive_twice_returns_invalid_state
        """
        ctx = setup_arrived_case(case_number="CASE-SM1B", household_size=1)
        case_id = ctx["case"]["id"]
        api.arrive_case(case_id, {"actual_arrival_date": "2026-08-11"}, CM)
        case = get_case(case_id, headers=CM)
        assert date_part(case["actual_arrival_date"]) == "2026-08-10"
        assert case["status"] == "ARRIVED"
        benchmarks = list_case_benchmarks(case_id, headers=CM)
        assert len(benchmarks) == 5


class TestBenefitApplicationTerminalLockdown:
    def _approved_application(self):
        ctx = setup_arrived_case(
            case_number="CASE-SM2", household_size=1,
            members=[{"full_name": "Adult S", "date_of_birth": "1990-01-01",
                      "relationship": "PRINCIPAL", "work_eligible": True}])
        app = make_benefit_application(ctx["case"]["id"], ctx["members"][0]["id"])
        transition_application(app["id"], "FILED")
        return transition_application(app["id"], "APPROVED")

    def test_approved_application_rejects_decide(self, api):
        """PRD §3.5: "`APPROVED` and `WITHDRAWN` are terminal, and any
        transition that does not match one of these pairs — including deciding
        an `APPROVED` application or appealing a `FILED` one — is rejected
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/application_terminal_lockdown
        """
        app = self._approved_application()
        assert app["status"] == "APPROVED"
        resp = api.transition_benefit_application(app["id"], {"to_status": "DENIED"}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approved_application_rejects_appeal(self, api):
        """PRD §3.5: "`APPROVED` and `WITHDRAWN` are terminal, and any
        transition that does not match one of these pairs — including deciding
        an `APPROVED` application or appealing a `FILED` one — is rejected
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/application_terminal_lockdown
        """
        app = self._approved_application()
        resp = api.transition_benefit_application(app["id"], {"to_status": "APPEALED"}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBenefitApplicationSkipState:
    def test_draft_to_approved_rejected(self, api):
        """PRD §3.5: "From `DRAFT` an application is filed, moving to `FILED`
        with `filed_on` stamped from the logical clock." and "any transition
        that does not match one of these pairs — including deciding an
        `APPROVED` application or appealing a `FILED` one — is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/application_invalid_skip_draft_to_approved
        """
        ctx = setup_arrived_case(
            case_number="CASE-SM3", household_size=1,
            members=[{"full_name": "Adult K", "date_of_birth": "1990-01-01",
                      "relationship": "PRINCIPAL", "work_eligible": True}])
        app = make_benefit_application(ctx["case"]["id"], ctx["members"][0]["id"])
        assert app["status"] == "DRAFT"
        resp = api.transition_benefit_application(app["id"], {"to_status": "APPROVED"}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTransferRespondTwice:
    def test_respond_after_rejected_rejected(self, api):
        """PRD §3.6: "On `REJECTED`, the transfer moves `INITIATED →
        REJECTED`, the case's `open_transfer_id` clears to null, the case's
        `version` increments by 1, and nothing else happens". PRD §2.5:
        "Sixth, state-machine legality — wrong from-state, terminal lockdown,
        state-gated creates — else `ERR_INVALID_STATE` or
        `ERR_BENCHMARK_NOT_PENDING`."

        Design: Corner/state_machines/transfer_respond_twice_returns_invalid_state
        """
        ctx = setup_arrived_case(case_number="CASE-SM4", household_size=1)
        transfer = make_case_transfer(ctx["case"]["id"])
        responded = respond_case_transfer(transfer["id"], "REJECTED")
        assert responded["status"] == "REJECTED"
        resp = api.respond_case_transfer(transfer["id"], {"decision": "ACCEPTED"}, AD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSessionCompleteTwice:
    def _completed_session(self):
        ctx = setup_arrived_case(case_number="CASE-SM5", household_size=1)
        session = make_orientation_session(
            ctx["case"]["id"], topic="US_LAWS",
            start_at="2026-08-12T09:00:00Z", end_at="2026-08-12T10:00:00Z")
        set_clock("2026-08-13T10:00:00Z")
        completed = complete_orientation_session(session["id"])
        return ctx, completed

    def test_complete_completed_session_rejected(self, api):
        """PRD §3.5: "Completing a session — again a `CaseManager` action,
        requiring no open transfer — moves it `SCHEDULED → COMPLETED` and
        stamps `completed_on` from the logical clock." PRD §2.5: "Sixth,
        state-machine legality — wrong from-state, terminal lockdown,
        state-gated creates — else `ERR_INVALID_STATE` or
        `ERR_BENCHMARK_NOT_PENDING`."

        Design: Corner/state_machines/session_complete_twice_returns_invalid_state
        """
        _, completed = self._completed_session()
        resp = api.complete_orientation_session(completed["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_double_complete_preserves_completed_on(self, api):
        """PRD §3.5: "Completing a session — again a `CaseManager` action,
        requiring no open transfer — moves it `SCHEDULED → COMPLETED` and
        stamps `completed_on` from the logical clock."

        Design: Corner/state_machines/session_complete_twice_returns_invalid_state
        """
        ctx, completed = self._completed_session()
        api.complete_orientation_session(completed["id"], CM)
        sessions = list_orientation_sessions(ctx["case"]["id"], headers=CM)
        target = [s for s in sessions if s["id"] == completed["id"]][0]
        assert target["status"] == "COMPLETED"
        assert date_part(target["completed_on"]) == "2026-08-13"


class TestReportReviewDraft:
    def test_review_draft_report_rejected(self, api):
        """PRD §3.7: "On `ACCEPTED` the report moves `SUBMITTED` → `ACCEPTED`
        — its terminal state — with `reviewed_by_user_id` stamped. On
        `REJECTED` the report returns `SUBMITTED` → `DRAFT`". PRD §2.5:
        "Sixth, state-machine legality — wrong from-state, terminal lockdown,
        state-gated creates — else `ERR_INVALID_STATE` or
        `ERR_BENCHMARK_NOT_PENDING`."

        Design: Corner/state_machines/report_review_draft_returns_invalid_state
        """
        report = make_federal_report("2026-10-01", "2027-01-01")
        assert report["status"] == "DRAFT"
        resp = api.review_federal_report(report["id"], {"decision": "ACCEPTED"}, FO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBenchmarkRescindPending:
    def test_rescind_pending_benchmark_rejected(self, api):
        """PRD §3.4: "And a `MET` benchmark may be rescinded back to
        `PENDING` by a `CaseManager` when the documentation was wrong".
        PRD §2.5: "Sixth, state-machine legality — wrong from-state, terminal
        lockdown, state-gated creates — else `ERR_INVALID_STATE` or
        `ERR_BENCHMARK_NOT_PENDING`."

        Design: Corner/state_machines/benchmark_rescind_pending_returns_invalid_state
        """
        ctx = setup_arrived_case(case_number="CASE-SM7", household_size=1)
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        assert bm["status"] == "PENDING"
        resp = api.rescind_benchmark(bm["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBenchmarkWaiveWaived:
    def test_waive_already_waived_rejected(self, api):
        """PRD §3.4: "The benchmark must be `PENDING` — fulfilling or waiving
        a benchmark in any other state is rejected with
        `ERR_BENCHMARK_NOT_PENDING` (HTTP 409)".

        Design: Corner/state_machines/benchmark_waive_waived_returns_not_pending
        """
        ctx = setup_arrived_case(case_number="CASE-SM8", household_size=1)
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT", headers=AD)
        waived = waive_benchmark(bm["id"], reason="Not applicable to this case")
        assert waived["status"] == "WAIVED"
        resp = api.waive_benchmark(bm["id"], {"reason": "Waive again"}, AD)
        validate_error(resp, ApiErrorId.ERR_BENCHMARK_NOT_PENDING)


class TestHousingFurnishVacated:
    def test_furnish_vacated_setup_rejected(self, api):
        """PRD §4: "Mark one required-furnishings `item` complete on a
        `PREPARING` setup". PRD §3.2: "A setup in any of `PREPARING`, `READY`,
        or `OCCUPIED` may also be vacated by the coordinator, moving it to the
        terminal `VACATED` state and recomputing its unit's derived status."
        PRD §2.5: "Sixth, state-machine legality — wrong from-state, terminal
        lockdown, state-gated creates — else `ERR_INVALID_STATE` or
        `ERR_BENCHMARK_NOT_PENDING`."

        Design: Corner/state_machines/housing_furnish_vacated_returns_invalid_state
        """
        case = make_case(case_number="CASE-SM9", household_size=1)
        unit = make_housing_unit(address="400 Larch St", bedrooms=1)
        setup = make_housing_setup(case["id"], unit["id"])
        vacated = vacate_setup(setup["id"])
        assert vacated["status"] == "VACATED"
        resp = api.furnish_setup(setup["id"], {"item": "BED"}, HC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
