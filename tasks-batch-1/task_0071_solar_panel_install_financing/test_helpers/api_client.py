"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Homeowner ---
    def create_homeowner(self, payload, headers=None):
        return self._request("POST", "/solar/homeowners", payload, headers=headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"/solar/homeowners/{homeowner_id}", headers=headers)

    # --- SolarInstaller ---
    def create_installer(self, payload, headers=None):
        return self._request("POST", "/solar/installers", payload, headers=headers)

    def get_installer(self, installer_id, headers):
        return self._request("GET", f"/solar/installers/{installer_id}", headers=headers)

    # --- Utility ---
    def create_utility(self, payload, headers):
        return self._request("POST", "/solar/utilities", payload, headers=headers)

    def get_utility(self, utility_id, headers):
        return self._request("GET", f"/solar/utilities/{utility_id}", headers=headers)

    # --- SrecBroker ---
    def create_broker(self, payload, headers=None):
        return self._request("POST", "/solar/brokers", payload, headers=headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/solar/brokers/{broker_id}", headers=headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/solar/projects", payload, headers=headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/solar/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/solar/projects", headers=headers, params=params)

    def assess_project(self, project_id, payload, headers):
        return self._request("POST", f"/solar/projects/{project_id}/assess", payload, headers=headers)

    def design_project(self, project_id, payload, headers):
        return self._request("POST", f"/solar/projects/{project_id}/design", payload, headers=headers)

    def submit_permit(self, project_id, headers, payload=None):
        return self._request("POST", f"/solar/projects/{project_id}/submit-permit", payload or {}, headers=headers)

    def approve_permit(self, project_id, headers, payload=None):
        return self._request("POST", f"/solar/projects/{project_id}/approve-permit", payload or {}, headers=headers)

    def complete_install(self, project_id, headers, payload=None):
        return self._request("POST", f"/solar/projects/{project_id}/complete-install", payload or {}, headers=headers)

    def inspect_project(self, project_id, payload, headers):
        return self._request("POST", f"/solar/projects/{project_id}/inspect", payload, headers=headers)

    def start_remediation(self, project_id, headers, payload=None):
        return self._request("POST", f"/solar/projects/{project_id}/start-remediation", payload or {}, headers=headers)

    def cancel_project(self, project_id, headers, payload=None):
        return self._request("POST", f"/solar/projects/{project_id}/cancel", payload or {}, headers=headers)

    # --- FinancingPlan ---
    def create_financing_plan(self, payload, headers):
        return self._request("POST", "/solar/financing-plans", payload, headers=headers)

    def get_financing_plan(self, plan_id, headers):
        return self._request("GET", f"/solar/financing-plans/{plan_id}", headers=headers)

    def list_financing_plans(self, headers, params=None):
        return self._request("GET", "/solar/financing-plans", headers=headers, params=params)

    def activate_financing_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/solar/financing-plans/{plan_id}/activate", payload, headers=headers)

    # --- InterconnectionApplication ---
    def create_interconnection_application(self, payload, headers):
        return self._request("POST", "/solar/interconnection-applications", payload, headers=headers)

    def get_interconnection_application(self, app_id, headers):
        return self._request("GET", f"/solar/interconnection-applications/{app_id}", headers=headers)

    def list_interconnection_applications(self, headers, params=None):
        return self._request("GET", "/solar/interconnection-applications", headers=headers, params=params)

    def begin_review(self, app_id, headers, payload=None):
        return self._request("POST", f"/solar/interconnection-applications/{app_id}/begin-review", payload or {}, headers=headers)

    def approve_interconnection(self, app_id, headers, payload=None):
        return self._request("POST", f"/solar/interconnection-applications/{app_id}/approve", payload or {}, headers=headers)

    def reject_interconnection(self, app_id, headers, payload=None):
        return self._request("POST", f"/solar/interconnection-applications/{app_id}/reject", payload or {}, headers=headers)

    def withdraw_interconnection(self, app_id, headers, payload=None):
        return self._request("POST", f"/solar/interconnection-applications/{app_id}/withdraw", payload or {}, headers=headers)

    def grant_pto(self, app_id, headers, payload=None):
        return self._request("POST", f"/solar/interconnection-applications/{app_id}/grant-pto", payload or {}, headers=headers)

    # --- SREC ---
    def mint_srec(self, payload, headers):
        return self._request("POST", "/solar/srecs", payload, headers=headers)

    def get_srec(self, srec_id, headers):
        return self._request("GET", f"/solar/srecs/{srec_id}", headers=headers)

    def list_srecs(self, headers, params=None):
        return self._request("GET", "/solar/srecs", headers=headers, params=params)

    def list_srec_for_sale(self, srec_id, headers, payload=None):
        return self._request("POST", f"/solar/srecs/{srec_id}/list", payload or {}, headers=headers)

    def retire_srec(self, srec_id, headers, payload=None):
        return self._request("POST", f"/solar/srecs/{srec_id}/retire", payload or {}, headers=headers)

    # --- SrecSale ---
    def create_srec_sale(self, payload, headers):
        return self._request("POST", "/solar/srec-sales", payload, headers=headers)

    def get_srec_sale(self, sale_id, headers):
        return self._request("GET", f"/solar/srec-sales/{sale_id}", headers=headers)

    def list_srec_sales(self, headers, params=None):
        return self._request("GET", "/solar/srec-sales", headers=headers, params=params)

    # --- NetMeterPeriod ---
    def create_net_meter_period(self, payload, headers):
        return self._request("POST", "/solar/net-meter-periods", payload, headers=headers)

    def get_net_meter_period(self, period_id, headers):
        return self._request("GET", f"/solar/net-meter-periods/{period_id}", headers=headers)

    def list_net_meter_periods(self, headers, params=None):
        return self._request("GET", "/solar/net-meter-periods", headers=headers, params=params)

    def settle_net_meter_period(self, period_id, headers, payload=None):
        return self._request("POST", f"/solar/net-meter-periods/{period_id}/settle", payload or {}, headers=headers)

    # --- WarrantyPolicy ---
    def get_warranty_policy(self, policy_id, headers):
        return self._request("GET", f"/solar/warranty-policies/{policy_id}", headers=headers)

    def list_warranty_policies(self, headers, params=None):
        return self._request("GET", "/solar/warranty-policies", headers=headers, params=params)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/solar/warranty-claims", payload, headers=headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/solar/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/solar/warranty-claims", headers=headers, params=params)

    def request_claim_info(self, claim_id, headers, payload=None):
        return self._request("POST", f"/solar/warranty-claims/{claim_id}/request-info", payload or {}, headers=headers)

    def resubmit_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/solar/warranty-claims/{claim_id}/resubmit", payload or {}, headers=headers)

    def approve_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/solar/warranty-claims/{claim_id}/approve", payload or {}, headers=headers)

    def deny_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/solar/warranty-claims/{claim_id}/deny", payload or {}, headers=headers)

    def remediate_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/solar/warranty-claims/{claim_id}/remediate", payload or {}, headers=headers)


api_client = ApiClient()
