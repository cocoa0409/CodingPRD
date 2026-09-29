"""API client: one method per endpoint defined in the PRD.

Every collection is mounted at the root of the API's flat top-level URL space;
there is no shared prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and operations
    # ------------------------------------------------------------------

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_compliance_sweep(self, headers, payload=None):
        return self._request("POST", "/_ops/compliance-sweep", payload or {}, headers)

    # ------------------------------------------------------------------
    # HealthCenter
    # ------------------------------------------------------------------

    def create_health_center(self, payload, headers):
        return self._request("POST", "/health-centers", payload, headers)

    def get_health_center(self, health_center_id, headers):
        return self._request(
            "GET", f"/health-centers/{health_center_id}", headers=headers
        )

    def list_health_centers(self, headers, params=None):
        return self._request("GET", "/health-centers", headers=headers, params=params)

    def lock_scope_baseline(self, health_center_id, headers, payload=None):
        return self._request(
            "POST",
            f"/health-centers/{health_center_id}/lock-scope-baseline",
            payload or {},
            headers,
        )

    def get_governance_summary(self, health_center_id, headers):
        return self._request(
            "GET",
            f"/health-centers/{health_center_id}/governance-summary",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # PovertyGuideline
    # ------------------------------------------------------------------

    def create_poverty_guideline(self, payload, headers):
        return self._request("POST", "/poverty-guidelines", payload, headers)

    def get_poverty_guideline(self, poverty_guideline_id, headers):
        return self._request(
            "GET", f"/poverty-guidelines/{poverty_guideline_id}", headers=headers
        )

    def list_poverty_guidelines(self, headers, params=None):
        return self._request(
            "GET", "/poverty-guidelines", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # BoardMember
    # ------------------------------------------------------------------

    def create_board_member(self, health_center_id, payload, headers):
        return self._request(
            "POST", f"/health-centers/{health_center_id}/board-members", payload, headers
        )

    def get_board_member(self, board_member_id, headers):
        return self._request("GET", f"/board-members/{board_member_id}", headers=headers)

    def list_board_members(self, headers, params=None):
        return self._request("GET", "/board-members", headers=headers, params=params)

    def resign_board_member(self, board_member_id, payload, headers):
        return self._request(
            "POST", f"/board-members/{board_member_id}/resign", payload, headers
        )

    # ------------------------------------------------------------------
    # ServiceSite
    # ------------------------------------------------------------------

    def create_service_site(self, health_center_id, payload, headers):
        return self._request(
            "POST",
            f"/health-centers/{health_center_id}/service-sites",
            payload,
            headers,
        )

    def get_service_site(self, service_site_id, headers):
        return self._request("GET", f"/service-sites/{service_site_id}", headers=headers)

    def list_health_center_service_sites(self, health_center_id, headers, params=None):
        return self._request(
            "GET",
            f"/health-centers/{health_center_id}/service-sites",
            headers=headers,
            params=params,
        )

    def suspend_service_site(self, service_site_id, headers, payload=None):
        return self._request(
            "POST", f"/service-sites/{service_site_id}/suspend", payload or {}, headers
        )

    def reinstate_service_site(self, service_site_id, headers, payload=None):
        return self._request(
            "POST", f"/service-sites/{service_site_id}/reinstate", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # ServiceDefinition
    # ------------------------------------------------------------------

    def create_service_definition(self, health_center_id, payload, headers):
        return self._request(
            "POST",
            f"/health-centers/{health_center_id}/service-definitions",
            payload,
            headers,
        )

    def get_service_definition(self, service_definition_id, headers):
        return self._request(
            "GET", f"/service-definitions/{service_definition_id}", headers=headers
        )

    def list_health_center_service_definitions(
        self, health_center_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/health-centers/{health_center_id}/service-definitions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # ScopeChangeRequest
    # ------------------------------------------------------------------

    def create_scope_change_request(self, health_center_id, payload, headers):
        return self._request(
            "POST",
            f"/health-centers/{health_center_id}/scope-change-requests",
            payload,
            headers,
        )

    def get_scope_change_request(self, scope_change_request_id, headers):
        return self._request(
            "GET", f"/scope-change-requests/{scope_change_request_id}", headers=headers
        )

    def list_scope_change_requests(self, headers, params=None):
        return self._request(
            "GET", "/scope-change-requests", headers=headers, params=params
        )

    def submit_scope_change_request(
        self, scope_change_request_id, headers, payload=None
    ):
        return self._request(
            "POST",
            f"/scope-change-requests/{scope_change_request_id}/submit",
            payload or {},
            headers,
        )

    def begin_review_scope_change_request(
        self, scope_change_request_id, headers, payload=None
    ):
        return self._request(
            "POST",
            f"/scope-change-requests/{scope_change_request_id}/begin-review",
            payload or {},
            headers,
        )

    def decide_scope_change_request(self, scope_change_request_id, payload, headers):
        return self._request(
            "POST",
            f"/scope-change-requests/{scope_change_request_id}/decide",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # FeeSchedule
    # ------------------------------------------------------------------

    def create_fee_schedule(self, health_center_id, payload, headers):
        return self._request(
            "POST",
            f"/health-centers/{health_center_id}/fee-schedules",
            payload,
            headers,
        )

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    def adopt_fee_schedule(self, fee_schedule_id, payload, headers):
        return self._request(
            "POST", f"/fee-schedules/{fee_schedule_id}/adopt", payload, headers
        )

    def annual_review_fee_schedule(self, fee_schedule_id, payload, headers):
        return self._request(
            "POST", f"/fee-schedules/{fee_schedule_id}/annual-review", payload, headers
        )

    # ------------------------------------------------------------------
    # DiscountTier
    # ------------------------------------------------------------------

    def create_discount_tier(self, fee_schedule_id, payload, headers):
        return self._request(
            "POST", f"/fee-schedules/{fee_schedule_id}/discount-tiers", payload, headers
        )

    def get_discount_tier(self, discount_tier_id, headers):
        return self._request(
            "GET", f"/discount-tiers/{discount_tier_id}", headers=headers
        )

    def list_fee_schedule_discount_tiers(self, fee_schedule_id, headers, params=None):
        return self._request(
            "GET",
            f"/fee-schedules/{fee_schedule_id}/discount-tiers",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Patient
    # ------------------------------------------------------------------

    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ------------------------------------------------------------------
    # IncomeVerification
    # ------------------------------------------------------------------

    def create_income_verification(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/income-verifications", payload, headers
        )

    def get_income_verification(self, income_verification_id, headers):
        return self._request(
            "GET", f"/income-verifications/{income_verification_id}", headers=headers
        )

    def list_income_verifications(self, headers, params=None):
        return self._request(
            "GET", "/income-verifications", headers=headers, params=params
        )

    def verify_income_verification(self, income_verification_id, payload, headers):
        return self._request(
            "POST",
            f"/income-verifications/{income_verification_id}/verify",
            payload,
            headers,
        )

    def resubmit_income_verification(self, income_verification_id, payload, headers):
        return self._request(
            "POST",
            f"/income-verifications/{income_verification_id}/resubmit",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Encounter
    # ------------------------------------------------------------------

    def create_encounter(self, payload, headers):
        return self._request("POST", "/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def bill_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"/encounters/{encounter_id}/bill", payload, headers)

    def record_encounter_payment(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/record-payment", payload, headers
        )

    def claim_wraparound(self, encounter_id, headers, payload=None):
        return self._request(
            "POST", f"/encounters/{encounter_id}/claim-wraparound", payload or {}, headers
        )

    def void_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"/encounters/{encounter_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # InabilityToPayWaiver
    # ------------------------------------------------------------------

    def create_waiver(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/waivers", payload, headers
        )

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def list_encounter_waivers(self, encounter_id, headers, params=None):
        return self._request(
            "GET", f"/encounters/{encounter_id}/waivers", headers=headers, params=params
        )

    def decide_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/waivers/{waiver_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # UDSReport
    # ------------------------------------------------------------------

    def create_uds_report(self, health_center_id, payload, headers):
        return self._request(
            "POST", f"/health-centers/{health_center_id}/uds-reports", payload, headers
        )

    def get_uds_report(self, uds_report_id, headers):
        return self._request("GET", f"/uds-reports/{uds_report_id}", headers=headers)

    def list_health_center_uds_reports(self, health_center_id, headers, params=None):
        return self._request(
            "GET",
            f"/health-centers/{health_center_id}/uds-reports",
            headers=headers,
            params=params,
        )

    def compute_uds_report(self, uds_report_id, headers, payload=None):
        return self._request(
            "POST", f"/uds-reports/{uds_report_id}/compute", payload or {}, headers
        )

    def submit_uds_report(self, uds_report_id, headers, payload=None):
        return self._request(
            "POST", f"/uds-reports/{uds_report_id}/submit", payload or {}, headers
        )

    def adjudicate_uds_report(self, uds_report_id, payload, headers):
        return self._request(
            "POST", f"/uds-reports/{uds_report_id}/adjudicate", payload, headers
        )

    # ------------------------------------------------------------------
    # QualityMeasureResult
    # ------------------------------------------------------------------

    def create_quality_measure_result(self, uds_report_id, payload, headers):
        return self._request(
            "POST",
            f"/uds-reports/{uds_report_id}/quality-measure-results",
            payload,
            headers,
        )

    def get_quality_measure_result(self, quality_measure_result_id, headers):
        return self._request(
            "GET",
            f"/quality-measure-results/{quality_measure_result_id}",
            headers=headers,
        )

    def list_uds_report_quality_measure_results(
        self, uds_report_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/uds-reports/{uds_report_id}/quality-measure-results",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # SiteVisitFinding
    # ------------------------------------------------------------------

    def create_site_visit_finding(self, health_center_id, payload, headers):
        return self._request(
            "POST",
            f"/health-centers/{health_center_id}/site-visit-findings",
            payload,
            headers,
        )

    def get_site_visit_finding(self, site_visit_finding_id, headers):
        return self._request(
            "GET", f"/site-visit-findings/{site_visit_finding_id}", headers=headers
        )

    def list_site_visit_findings(self, headers, params=None):
        return self._request(
            "GET", "/site-visit-findings", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # CorrectiveActionPlan
    # ------------------------------------------------------------------

    def create_corrective_action_plan(self, site_visit_finding_id, payload, headers):
        return self._request(
            "POST",
            f"/site-visit-findings/{site_visit_finding_id}/corrective-action-plans",
            payload,
            headers,
        )

    def get_corrective_action_plan(self, corrective_action_plan_id, headers):
        return self._request(
            "GET",
            f"/corrective-action-plans/{corrective_action_plan_id}",
            headers=headers,
        )

    def list_finding_corrective_action_plans(
        self, site_visit_finding_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/site-visit-findings/{site_visit_finding_id}/corrective-action-plans",
            headers=headers,
            params=params,
        )

    def submit_corrective_action_plan(
        self, corrective_action_plan_id, headers, payload=None
    ):
        return self._request(
            "POST",
            f"/corrective-action-plans/{corrective_action_plan_id}/submit",
            payload or {},
            headers,
        )

    def adjudicate_corrective_action_plan(
        self, corrective_action_plan_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/corrective-action-plans/{corrective_action_plan_id}/adjudicate",
            payload,
            headers,
        )


api_client = ApiClient()
