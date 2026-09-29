"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/relicensing"


class ApiClient(GenericApiClient):
    """Typed access to every documented Hydroelectric Project Relicensing route."""

    # ---- logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- relicensing projects --------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def patch_project(self, project_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/projects/{project_id}", payload, headers
        )

    def file_pre_application_document(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/projects/{project_id}/pre-application-document",
            payload,
            headers,
        )

    def run_compliance_sweep(self, project_id, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/run-compliance-sweep", {}, headers
        )

    # ---- dams -------------------------------------------------------------
    def create_dam(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dams", payload, headers)

    def list_dams(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dams", headers=headers, params=params)

    def get_dam(self, dam_id, headers):
        return self._request("GET", f"{PREFIX}/dams/{dam_id}", headers=headers)

    # ---- study sites ------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    # ---- study plans ------------------------------------------------------
    def create_study_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/study-plans", payload, headers)

    def list_study_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/study-plans", headers=headers, params=params
        )

    def get_study_plan(self, study_plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/study-plans/{study_plan_id}", headers=headers
        )

    def submit_study_plan(self, study_plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/study-plans/{study_plan_id}/submit", payload, headers
        )

    def decide_study_plan(self, study_plan_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/study-plans/{study_plan_id}/determination",
            payload,
            headers,
        )

    # ---- resource studies -------------------------------------------------
    def create_study(self, payload, headers):
        return self._request("POST", f"{PREFIX}/studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"{PREFIX}/studies/{study_id}", headers=headers)

    def study_fieldwork(self, study_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/fieldwork", payload, headers
        )

    def submit_study_report(self, study_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/report", payload, headers
        )

    def decide_study_review(self, study_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/review-decision", payload, headers
        )

    # ---- consultation comments -------------------------------------------
    def create_comment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/comments", payload, headers)

    def list_comments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/comments", headers=headers, params=params)

    def get_comment(self, comment_id, headers):
        return self._request("GET", f"{PREFIX}/comments/{comment_id}", headers=headers)

    def resolve_comment(self, comment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/comments/{comment_id}/resolve", payload, headers
        )

    # ---- settlement parties ----------------------------------------------
    def create_party(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parties", payload, headers)

    def list_parties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/parties", headers=headers, params=params)

    def get_party(self, party_id, headers):
        return self._request("GET", f"{PREFIX}/parties/{party_id}", headers=headers)

    # ---- settlements ------------------------------------------------------
    def create_settlement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/settlements", headers=headers, params=params
        )

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlements/{settlement_id}", headers=headers
        )

    def circulate_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/circulate", payload, headers
        )

    def tally_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/tally", payload, headers
        )

    def withdraw_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/withdraw", payload, headers
        )

    # ---- settlement signatures -------------------------------------------
    def create_signature(self, payload, headers):
        return self._request("POST", f"{PREFIX}/signatures", payload, headers)

    def list_signatures(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/signatures", headers=headers, params=params
        )

    def get_signature(self, signature_id, headers):
        return self._request(
            "GET", f"{PREFIX}/signatures/{signature_id}", headers=headers
        )

    # ---- water quality certifications ------------------------------------
    def create_water_quality_certification(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/water-quality-certifications", payload, headers
        )

    def list_water_quality_certifications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/water-quality-certifications", headers=headers, params=params
        )

    def get_water_quality_certification(self, wqc_id, headers):
        return self._request(
            "GET", f"{PREFIX}/water-quality-certifications/{wqc_id}", headers=headers
        )

    def decide_water_quality_certification(self, wqc_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/water-quality-certifications/{wqc_id}/decision",
            payload,
            headers,
        )

    # ---- PME measures -----------------------------------------------------
    def create_measure(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pme-measures", payload, headers)

    def list_measures(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pme-measures", headers=headers, params=params
        )

    def get_measure(self, measure_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pme-measures/{measure_id}", headers=headers
        )

    def patch_measure(self, measure_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/pme-measures/{measure_id}", payload, headers
        )

    def record_definitive_estimate(self, measure_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pme-measures/{measure_id}/cost-estimate", payload, headers
        )

    # ---- license applications --------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applications", headers=headers, params=params
        )

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/applications/{application_id}", headers=headers
        )

    def advance_environmental_review(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/environmental-review",
            payload,
            headers,
        )

    def raise_deficiency(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/deficiency", payload, headers
        )

    def cure_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/cure", payload, headers
        )

    def issue_order(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/order", payload, headers
        )

    # ---- license orders ---------------------------------------------------
    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def file_annual_report(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/annual-report", payload, headers
        )

    # ---- compliance obligations ------------------------------------------
    def list_obligations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/obligations", headers=headers, params=params
        )

    def get_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/obligations/{obligation_id}", headers=headers
        )

    def schedule_obligation(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/obligations/{obligation_id}/schedule", payload, headers
        )

    def certify_obligation(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/obligations/{obligation_id}/certify", payload, headers
        )


api_client = ApiClient()
