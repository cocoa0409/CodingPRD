"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the `/ccs` prefix except the logical clock endpoint,
which the PRD mounts at `/_clock/set_current_utc`.
"""

from prd_bench_local_runner.testing import GenericApiClient

CCS = "/ccs"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Storage projects
    # ------------------------------------------------------------------

    def create_storage_project(self, payload, headers):
        return self._request("POST", f"{CCS}/storage-projects", payload, headers)

    def list_storage_projects(self, headers, params=None):
        return self._request(
            "GET", f"{CCS}/storage-projects", headers=headers, params=params
        )

    def get_storage_project(self, project_id, headers):
        return self._request(
            "GET", f"{CCS}/storage-projects/{project_id}", headers=headers
        )

    def file_unitization_petition(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/storage-projects/{project_id}/unitization-petition",
            payload,
            headers,
        )

    def rule_unitization_petition(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/storage-projects/{project_id}/unitization-ruling",
            payload,
            headers,
        )

    def authorize_injection(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/storage-projects/{project_id}/authorize-injection",
            payload,
            headers,
        )

    def begin_pisc(self, project_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/storage-projects/{project_id}/begin-pisc", payload, headers
        )

    def certify_closure(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/storage-projects/{project_id}/certify-closure",
            payload,
            headers,
        )

    def list_project_legacy_wellbores(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{CCS}/storage-projects/{project_id}/legacy-wellbores",
            headers=headers,
            params=params,
        )

    def list_project_pore_space_tracts(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{CCS}/storage-projects/{project_id}/pore-space-tracts",
            headers=headers,
            params=params,
        )

    def list_project_monitoring_plans(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{CCS}/storage-projects/{project_id}/monitoring-plans",
            headers=headers,
            params=params,
        )

    def list_project_financial_instruments(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{CCS}/storage-projects/{project_id}/financial-instruments",
            headers=headers,
            params=params,
        )

    def list_project_remediation_orders(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{CCS}/storage-projects/{project_id}/remediation-orders",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Geologic models
    # ------------------------------------------------------------------

    def create_geologic_model(self, payload, headers):
        return self._request("POST", f"{CCS}/geologic-models", payload, headers)

    def list_geologic_models(self, headers, params=None):
        return self._request(
            "GET", f"{CCS}/geologic-models", headers=headers, params=params
        )

    def get_geologic_model(self, model_id, headers):
        return self._request(
            "GET", f"{CCS}/geologic-models/{model_id}", headers=headers
        )

    def run_plume_simulation(self, model_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/geologic-models/{model_id}/run-plume-simulation",
            payload,
            headers,
        )

    def submit_geologic_model(self, model_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/geologic-models/{model_id}/submit", payload, headers
        )

    def review_geologic_model(self, model_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/geologic-models/{model_id}/review", payload, headers
        )

    def finalize_aor(self, model_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/geologic-models/{model_id}/finalize-aor", payload, headers
        )

    # ------------------------------------------------------------------
    # Legacy wellbores
    # ------------------------------------------------------------------

    def create_legacy_wellbore(self, payload, headers):
        return self._request("POST", f"{CCS}/legacy-wellbores", payload, headers)

    def get_legacy_wellbore(self, wellbore_id, headers):
        return self._request(
            "GET", f"{CCS}/legacy-wellbores/{wellbore_id}", headers=headers
        )

    def schedule_corrective_action(self, wellbore_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/legacy-wellbores/{wellbore_id}/schedule-corrective-action",
            payload,
            headers,
        )

    def complete_corrective_action(self, wellbore_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/legacy-wellbores/{wellbore_id}/complete-corrective-action",
            payload,
            headers,
        )

    def waive_corrective_action(self, wellbore_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/legacy-wellbores/{wellbore_id}/waive-corrective-action",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Pore space tracts
    # ------------------------------------------------------------------

    def create_pore_space_tract(self, payload, headers):
        return self._request("POST", f"{CCS}/pore-space-tracts", payload, headers)

    def get_pore_space_tract(self, tract_id, headers):
        return self._request(
            "GET", f"{CCS}/pore-space-tracts/{tract_id}", headers=headers
        )

    def send_lease_offer(self, tract_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/pore-space-tracts/{tract_id}/offers", payload, headers
        )

    def respond_to_lease_offer(self, tract_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/pore-space-tracts/{tract_id}/respond", payload, headers
        )

    def terminate_lease(self, tract_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/pore-space-tracts/{tract_id}/terminate-lease",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Injection well permits
    # ------------------------------------------------------------------

    def create_injection_well_permit(self, payload, headers):
        return self._request("POST", f"{CCS}/injection-well-permits", payload, headers)

    def list_injection_well_permits(self, headers, params=None):
        return self._request(
            "GET", f"{CCS}/injection-well-permits", headers=headers, params=params
        )

    def get_injection_well_permit(self, permit_id, headers):
        return self._request(
            "GET", f"{CCS}/injection-well-permits/{permit_id}", headers=headers
        )

    def submit_injection_well_permit(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/injection-well-permits/{permit_id}/submit",
            payload,
            headers,
        )

    def review_injection_well_permit(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/injection-well-permits/{permit_id}/review",
            payload,
            headers,
        )

    def advance_construction(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/injection-well-permits/{permit_id}/advance-construction",
            payload,
            headers,
        )

    def record_mit(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/injection-well-permits/{permit_id}/record-mit",
            payload,
            headers,
        )

    def activate_injection_well_permit(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/injection-well-permits/{permit_id}/activate",
            payload,
            headers,
        )

    def report_injection_period(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/injection-well-permits/{permit_id}/injection-periods",
            payload,
            headers,
        )

    def list_injection_periods(self, permit_id, headers, params=None):
        return self._request(
            "GET",
            f"{CCS}/injection-well-permits/{permit_id}/injection-periods",
            headers=headers,
            params=params,
        )

    def void_injection_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/injection-periods/{period_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Monitoring plans and methods
    # ------------------------------------------------------------------

    def create_monitoring_plan(self, payload, headers):
        return self._request("POST", f"{CCS}/monitoring-plans", payload, headers)

    def get_monitoring_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{CCS}/monitoring-plans/{plan_id}", headers=headers
        )

    def add_monitoring_method(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/monitoring-plans/{plan_id}/methods", payload, headers
        )

    def list_monitoring_methods(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{CCS}/monitoring-plans/{plan_id}/methods",
            headers=headers,
            params=params,
        )

    def retire_monitoring_method(self, method_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/monitoring-methods/{method_id}/retire", payload, headers
        )

    def submit_monitoring_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/monitoring-plans/{plan_id}/submit", payload, headers
        )

    def review_monitoring_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/monitoring-plans/{plan_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Financial instruments
    # ------------------------------------------------------------------

    def create_financial_instrument(self, payload, headers):
        return self._request("POST", f"{CCS}/financial-instruments", payload, headers)

    def get_financial_instrument(self, instrument_id, headers):
        return self._request(
            "GET", f"{CCS}/financial-instruments/{instrument_id}", headers=headers
        )

    def allocate_financial_instrument(self, instrument_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/financial-instruments/{instrument_id}/allocate",
            payload,
            headers,
        )

    def deallocate_financial_instrument(self, instrument_id, payload, headers):
        return self._request(
            "POST",
            f"{CCS}/financial-instruments/{instrument_id}/deallocate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Tax credit claims
    # ------------------------------------------------------------------

    def create_tax_credit_claim(self, payload, headers):
        return self._request("POST", f"{CCS}/tax-credit-claims", payload, headers)

    def list_tax_credit_claims(self, headers, params=None):
        return self._request(
            "GET", f"{CCS}/tax-credit-claims", headers=headers, params=params
        )

    def get_tax_credit_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{CCS}/tax-credit-claims/{claim_id}", headers=headers
        )

    def submit_tax_credit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/tax-credit-claims/{claim_id}/submit", payload, headers
        )

    def verify_tax_credit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/tax-credit-claims/{claim_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Remediation orders
    # ------------------------------------------------------------------

    def create_remediation_order(self, payload, headers):
        return self._request("POST", f"{CCS}/remediation-orders", payload, headers)

    def resolve_remediation_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{CCS}/remediation-orders/{order_id}/resolve", payload, headers
        )


api_client = ApiClient()
