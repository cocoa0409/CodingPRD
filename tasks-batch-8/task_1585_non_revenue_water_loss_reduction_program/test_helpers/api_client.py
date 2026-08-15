"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (PRD §2.5) ─────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/nrw/_clock/set_current_utc", payload, headers)

    # ─── District Metered Areas (PRD §3.1) ────────────
    def create_dma(self, payload, headers):
        return self._request("POST", "/nrw/dmas", payload, headers)

    def list_dmas(self, headers, params=None):
        return self._request("GET", "/nrw/dmas", headers=headers, params=params)

    def get_dma(self, dma_id, headers):
        return self._request("GET", f"/nrw/dmas/{dma_id}", headers=headers)

    def list_dma_water_balance_periods(self, dma_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/dmas/{dma_id}/water-balance-periods",
            headers=headers, params=params,
        )

    def list_dma_night_flow_assessments(self, dma_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/dmas/{dma_id}/night-flow-assessments",
            headers=headers, params=params,
        )

    def list_dma_leak_surveys(self, dma_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/dmas/{dma_id}/leak-surveys",
            headers=headers, params=params,
        )

    def list_dma_customer_meters(self, dma_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/dmas/{dma_id}/customer-meters",
            headers=headers, params=params,
        )

    def list_dma_unauthorized_consumption_cases(self, dma_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/dmas/{dma_id}/unauthorized-consumption-cases",
            headers=headers, params=params,
        )

    def list_dma_pressure_projects(self, dma_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/dmas/{dma_id}/pressure-projects",
            headers=headers, params=params,
        )

    def list_dma_intervention_proposals(self, dma_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/dmas/{dma_id}/intervention-proposals",
            headers=headers, params=params,
        )

    # ─── Water balance periods (PRD §3.2) ─────────────
    def create_water_balance_period(self, payload, headers):
        return self._request("POST", "/nrw/water-balance-periods", payload, headers)

    def list_water_balance_periods(self, headers, params=None):
        return self._request(
            "GET", "/nrw/water-balance-periods", headers=headers, params=params
        )

    def get_water_balance_period(self, period_id, headers):
        return self._request(
            "GET", f"/nrw/water-balance-periods/{period_id}", headers=headers
        )

    def submit_water_balance_period(self, period_id, headers):
        return self._request(
            "POST", f"/nrw/water-balance-periods/{period_id}/submit", {}, headers
        )

    def finalize_water_balance_period(self, period_id, headers):
        return self._request(
            "POST", f"/nrw/water-balance-periods/{period_id}/finalize", {}, headers
        )

    # ─── Night-flow assessments (PRD §3.3) ────────────
    def create_night_flow_assessment(self, payload, headers):
        return self._request("POST", "/nrw/night-flow-assessments", payload, headers)

    def get_night_flow_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/nrw/night-flow-assessments/{assessment_id}", headers=headers
        )

    def analyze_night_flow_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/nrw/night-flow-assessments/{assessment_id}/analyze",
            {}, headers,
        )

    def void_night_flow_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/nrw/night-flow-assessments/{assessment_id}/void", {}, headers
        )

    # ─── Leak surveys (PRD §3.3) ──────────────────────
    def create_leak_survey(self, payload, headers):
        return self._request("POST", "/nrw/leak-surveys", payload, headers)

    def get_leak_survey(self, survey_id, headers):
        return self._request("GET", f"/nrw/leak-surveys/{survey_id}", headers=headers)

    def list_survey_leaks(self, survey_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/leak-surveys/{survey_id}/leaks",
            headers=headers, params=params,
        )

    def start_leak_survey(self, survey_id, headers):
        return self._request(
            "POST", f"/nrw/leak-surveys/{survey_id}/start", {}, headers
        )

    def complete_leak_survey(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/nrw/leak-surveys/{survey_id}/complete", payload, headers
        )

    def cancel_leak_survey(self, survey_id, headers):
        return self._request(
            "POST", f"/nrw/leak-surveys/{survey_id}/cancel", {}, headers
        )

    # ─── Leaks (PRD §3.4) ─────────────────────────────
    def create_leak(self, payload, headers):
        return self._request("POST", "/nrw/leaks", payload, headers)

    def list_leaks(self, headers, params=None):
        return self._request("GET", "/nrw/leaks", headers=headers, params=params)

    def get_leak(self, leak_id, headers):
        return self._request("GET", f"/nrw/leaks/{leak_id}", headers=headers)

    def verify_leak(self, leak_id, headers):
        return self._request("POST", f"/nrw/leaks/{leak_id}/verify", {}, headers)

    def schedule_leak_repair(self, leak_id, headers):
        return self._request(
            "POST", f"/nrw/leaks/{leak_id}/schedule-repair", {}, headers
        )

    def complete_leak_repair(self, leak_id, payload, headers):
        return self._request(
            "POST", f"/nrw/leaks/{leak_id}/complete-repair", payload, headers
        )

    def verify_leak_repair(self, leak_id, headers):
        return self._request(
            "POST", f"/nrw/leaks/{leak_id}/verify-repair", {}, headers
        )

    def reopen_leak(self, leak_id, headers):
        return self._request("POST", f"/nrw/leaks/{leak_id}/reopen", {}, headers)

    def withdraw_leak(self, leak_id, headers):
        return self._request("POST", f"/nrw/leaks/{leak_id}/withdraw", {}, headers)

    # ─── Customer meters (PRD §3.5) ───────────────────
    def create_customer_meter(self, payload, headers):
        return self._request("POST", "/nrw/customer-meters", payload, headers)

    def get_customer_meter(self, meter_id, headers):
        return self._request(
            "GET", f"/nrw/customer-meters/{meter_id}", headers=headers
        )

    def list_meter_accuracy_tests(self, meter_id, headers, params=None):
        return self._request(
            "GET", f"/nrw/customer-meters/{meter_id}/accuracy-tests",
            headers=headers, params=params,
        )

    def flag_meter_replacement(self, meter_id, headers):
        return self._request(
            "POST", f"/nrw/customer-meters/{meter_id}/flag-replacement", {}, headers
        )

    def replace_customer_meter(self, meter_id, payload, headers):
        return self._request(
            "POST", f"/nrw/customer-meters/{meter_id}/replace", payload, headers
        )

    def retire_customer_meter(self, meter_id, headers):
        return self._request(
            "POST", f"/nrw/customer-meters/{meter_id}/retire", {}, headers
        )

    # ─── Meter accuracy tests (PRD §3.5) ──────────────
    def create_meter_accuracy_test(self, payload, headers):
        return self._request("POST", "/nrw/meter-accuracy-tests", payload, headers)

    def get_meter_accuracy_test(self, test_id, headers):
        return self._request(
            "GET", f"/nrw/meter-accuracy-tests/{test_id}", headers=headers
        )

    def complete_meter_accuracy_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/nrw/meter-accuracy-tests/{test_id}/complete", payload, headers
        )

    def cancel_meter_accuracy_test(self, test_id, headers):
        return self._request(
            "POST", f"/nrw/meter-accuracy-tests/{test_id}/cancel", {}, headers
        )

    # ─── Unauthorized-consumption cases (PRD §3.6) ────
    def create_unauthorized_consumption_case(self, payload, headers):
        return self._request(
            "POST", "/nrw/unauthorized-consumption-cases", payload, headers
        )

    def get_unauthorized_consumption_case(self, case_id, headers):
        return self._request(
            "GET", f"/nrw/unauthorized-consumption-cases/{case_id}", headers=headers
        )

    def begin_evidence(self, case_id, headers):
        return self._request(
            "POST",
            f"/nrw/unauthorized-consumption-cases/{case_id}/begin-evidence",
            {}, headers,
        )

    def substantiate_case(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/nrw/unauthorized-consumption-cases/{case_id}/substantiate",
            payload, headers,
        )

    def close_case_unfounded(self, case_id, headers):
        return self._request(
            "POST",
            f"/nrw/unauthorized-consumption-cases/{case_id}/close-unfounded",
            {}, headers,
        )

    def close_case(self, case_id, headers):
        return self._request(
            "POST", f"/nrw/unauthorized-consumption-cases/{case_id}/close",
            {}, headers,
        )

    def propose_adjustment(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/nrw/unauthorized-consumption-cases/{case_id}/propose-adjustment",
            payload, headers,
        )

    def approve_adjustment(self, case_id, headers):
        return self._request(
            "POST",
            f"/nrw/unauthorized-consumption-cases/{case_id}/approve-adjustment",
            {}, headers,
        )

    def reject_adjustment(self, case_id, headers):
        return self._request(
            "POST",
            f"/nrw/unauthorized-consumption-cases/{case_id}/reject-adjustment",
            {}, headers,
        )

    def post_adjustment(self, case_id, headers):
        return self._request(
            "POST",
            f"/nrw/unauthorized-consumption-cases/{case_id}/post-adjustment",
            {}, headers,
        )

    # ─── Pressure projects (PRD §3.7) ─────────────────
    def create_pressure_project(self, payload, headers):
        return self._request("POST", "/nrw/pressure-projects", payload, headers)

    def get_pressure_project(self, project_id, headers):
        return self._request(
            "GET", f"/nrw/pressure-projects/{project_id}", headers=headers
        )

    def approve_pressure_project(self, project_id, headers):
        return self._request(
            "POST", f"/nrw/pressure-projects/{project_id}/approve", {}, headers
        )

    def reject_pressure_project(self, project_id, headers):
        return self._request(
            "POST", f"/nrw/pressure-projects/{project_id}/reject", {}, headers
        )

    def activate_pressure_project(self, project_id, headers):
        return self._request(
            "POST", f"/nrw/pressure-projects/{project_id}/activate", {}, headers
        )

    def commission_pressure_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/nrw/pressure-projects/{project_id}/commission",
            payload, headers,
        )

    # ─── Intervention proposals (PRD §3.8) ────────────
    def create_intervention_proposal(self, payload, headers):
        return self._request("POST", "/nrw/intervention-proposals", payload, headers)

    def get_intervention_proposal(self, proposal_id, headers):
        return self._request(
            "GET", f"/nrw/intervention-proposals/{proposal_id}", headers=headers
        )

    def submit_intervention_proposal(self, proposal_id, headers):
        return self._request(
            "POST", f"/nrw/intervention-proposals/{proposal_id}/submit", {}, headers
        )

    def approve_intervention_proposal(self, proposal_id, headers):
        return self._request(
            "POST", f"/nrw/intervention-proposals/{proposal_id}/approve", {}, headers
        )

    def reject_intervention_proposal(self, proposal_id, headers):
        return self._request(
            "POST", f"/nrw/intervention-proposals/{proposal_id}/reject", {}, headers
        )

    # ─── Benchmark reports (PRD §3.9) ─────────────────
    def create_benchmark_report(self, payload, headers):
        return self._request("POST", "/nrw/benchmark-reports", payload, headers)

    def list_benchmark_reports(self, headers, params=None):
        return self._request(
            "GET", "/nrw/benchmark-reports", headers=headers, params=params
        )

    def get_benchmark_report(self, report_id, headers):
        return self._request(
            "GET", f"/nrw/benchmark-reports/{report_id}", headers=headers
        )

    def submit_benchmark_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/nrw/benchmark-reports/{report_id}/submit", payload, headers
        )

    def accept_benchmark_report(self, report_id, headers):
        return self._request(
            "POST", f"/nrw/benchmark-reports/{report_id}/accept", {}, headers
        )

    def return_benchmark_report(self, report_id, headers):
        return self._request(
            "POST", f"/nrw/benchmark-reports/{report_id}/return", {}, headers
        )

    # ─── Audit events (PRD §2.12) ─────────────────────
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/nrw/audit-events", headers=headers, params=params)


api_client = ApiClient()
