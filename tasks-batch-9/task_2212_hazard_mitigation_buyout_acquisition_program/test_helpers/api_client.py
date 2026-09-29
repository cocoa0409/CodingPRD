"""API client: one method per endpoint defined in the PRD.

All collections are mounted at the service root -- there is no versioned or
domain prefix in front of them.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical program clock ────────────────────────────────────────────────

    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── Mitigation projects ──────────────────────────────────────────────────

    def create_mitigation_project(self, payload, headers):
        return self._request("POST", "/mitigation-projects", payload, headers)

    def list_mitigation_projects(self, headers, params=None):
        return self._request("GET", "/mitigation-projects", headers=headers, params=params)

    def get_mitigation_project(self, project_id, headers):
        return self._request("GET", f"/mitigation-projects/{project_id}", headers=headers)

    def submit_mitigation_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/submit", payload or {}, headers
        )

    def return_mitigation_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/return", payload, headers
        )

    def approve_mitigation_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/approve", payload, headers
        )

    def closeout_mitigation_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/closeout", payload, headers
        )

    # ─── Benefit-cost analyses ────────────────────────────────────────────────

    def create_benefit_cost_analysis(self, project_id, payload, headers):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/benefit-cost-analyses", payload, headers
        )

    def list_benefit_cost_analyses(self, headers, params=None):
        return self._request("GET", "/benefit-cost-analyses", headers=headers, params=params)

    def get_benefit_cost_analysis(self, bca_id, headers):
        return self._request("GET", f"/benefit-cost-analyses/{bca_id}", headers=headers)

    def validate_benefit_cost_analysis(self, bca_id, payload, headers):
        return self._request(
            "POST", f"/benefit-cost-analyses/{bca_id}/validate", payload, headers
        )

    # ─── Parcels ──────────────────────────────────────────────────────────────

    def create_parcel(self, project_id, payload, headers):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/parcels", payload, headers
        )

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def record_pre_event_value(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/pre-event-value", payload, headers)

    def record_participation(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/participation", payload, headers)

    # ─── Parcel adjacencies ───────────────────────────────────────────────────

    def create_parcel_adjacency(self, payload, headers):
        return self._request("POST", "/parcel-adjacencies", payload, headers)

    def list_parcel_adjacencies(self, headers, params=None):
        return self._request("GET", "/parcel-adjacencies", headers=headers, params=params)

    def get_parcel_adjacency(self, adjacency_id, headers):
        return self._request("GET", f"/parcel-adjacencies/{adjacency_id}", headers=headers)

    # ─── Appraisals ───────────────────────────────────────────────────────────

    def create_appraisal(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/appraisals", payload, headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/appraisals", headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def submit_appraisal(self, appraisal_id, headers, payload=None):
        return self._request(
            "POST", f"/appraisals/{appraisal_id}/submit", payload or {}, headers
        )

    def review_appraisal(self, appraisal_id, payload, headers):
        return self._request(
            "POST", f"/appraisals/{appraisal_id}/review-decision", payload, headers
        )

    # ─── Duplication-of-benefits records ──────────────────────────────────────

    def create_dob_record(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/dob-records", payload, headers)

    def list_dob_records(self, headers, params=None):
        return self._request("GET", "/dob-records", headers=headers, params=params)

    def get_dob_record(self, dob_record_id, headers):
        return self._request("GET", f"/dob-records/{dob_record_id}", headers=headers)

    def reverse_dob_record(self, dob_record_id, payload, headers):
        return self._request(
            "POST", f"/dob-records/{dob_record_id}/reverse", payload, headers
        )

    # ─── Purchase offers ──────────────────────────────────────────────────────

    def create_purchase_offer(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/purchase-offers", payload, headers)

    def list_purchase_offers(self, headers, params=None):
        return self._request("GET", "/purchase-offers", headers=headers, params=params)

    def get_purchase_offer(self, offer_id, headers):
        return self._request("GET", f"/purchase-offers/{offer_id}", headers=headers)

    def present_purchase_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/purchase-offers/{offer_id}/present", payload or {}, headers
        )

    def respond_to_purchase_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/purchase-offers/{offer_id}/owner-response", payload, headers
        )

    def expire_purchase_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/purchase-offers/{offer_id}/expire", payload or {}, headers
        )

    def withdraw_purchase_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/purchase-offers/{offer_id}/withdraw", payload, headers
        )

    # ─── Relocation cases ─────────────────────────────────────────────────────

    def create_relocation_case(self, parcel_id, payload, headers):
        return self._request(
            "POST", f"/parcels/{parcel_id}/relocation-cases", payload, headers
        )

    def list_relocation_cases(self, headers, params=None):
        return self._request("GET", "/relocation-cases", headers=headers, params=params)

    def get_relocation_case(self, case_id, headers):
        return self._request("GET", f"/relocation-cases/{case_id}", headers=headers)

    def determine_relocation_eligibility(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/relocation-cases/{case_id}/determine-eligibility", payload or {}, headers
        )

    def submit_relocation_claim(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/relocation-cases/{case_id}/submit-claim", payload or {}, headers
        )

    def resolve_relocation_claim(self, case_id, payload, headers):
        return self._request(
            "POST", f"/relocation-cases/{case_id}/resolve-claim", payload, headers
        )

    def appeal_relocation_claim(self, case_id, payload, headers):
        return self._request("POST", f"/relocation-cases/{case_id}/appeal", payload, headers)

    # ─── Closing records ──────────────────────────────────────────────────────

    def create_closing_record(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/closing-records", payload, headers)

    def list_closing_records(self, headers, params=None):
        return self._request("GET", "/closing-records", headers=headers, params=params)

    def get_closing_record(self, closing_id, headers):
        return self._request("GET", f"/closing-records/{closing_id}", headers=headers)

    def fund_closing_record(self, closing_id, headers, payload=None):
        return self._request(
            "POST", f"/closing-records/{closing_id}/fund", payload or {}, headers
        )

    def record_closing_deed(self, closing_id, payload, headers):
        return self._request(
            "POST", f"/closing-records/{closing_id}/record", payload, headers
        )

    # ─── Demolition contractors ───────────────────────────────────────────────

    def create_demolition_contractor(self, payload, headers):
        return self._request("POST", "/demolition-contractors", payload, headers)

    def list_demolition_contractors(self, headers, params=None):
        return self._request("GET", "/demolition-contractors", headers=headers, params=params)

    def get_demolition_contractor(self, contractor_id, headers):
        return self._request(
            "GET", f"/demolition-contractors/{contractor_id}", headers=headers
        )

    def set_contractor_status(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/demolition-contractors/{contractor_id}/status", payload, headers
        )

    # ─── Demolition work orders ───────────────────────────────────────────────

    def create_demolition_work_order(self, parcel_id, payload, headers):
        return self._request(
            "POST", f"/parcels/{parcel_id}/demolition-work-orders", payload, headers
        )

    def list_demolition_work_orders(self, headers, params=None):
        return self._request("GET", "/demolition-work-orders", headers=headers, params=params)

    def get_demolition_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"/demolition-work-orders/{work_order_id}", headers=headers
        )

    def start_demolition_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"/demolition-work-orders/{work_order_id}/start", payload or {}, headers
        )

    def complete_demolition_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/demolition-work-orders/{work_order_id}/complete", payload, headers
        )

    def fail_demolition_inspection(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/demolition-work-orders/{work_order_id}/fail-inspection", payload, headers
        )

    def create_utility_disconnection(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"/demolition-work-orders/{work_order_id}/utility-disconnections",
            payload,
            headers,
        )

    # ─── Utility disconnections ───────────────────────────────────────────────

    def list_utility_disconnections(self, headers, params=None):
        return self._request("GET", "/utility-disconnections", headers=headers, params=params)

    def get_utility_disconnection(self, disconnection_id, headers):
        return self._request(
            "GET", f"/utility-disconnections/{disconnection_id}", headers=headers
        )

    def resolve_utility_disconnection(self, disconnection_id, payload, headers):
        return self._request(
            "POST", f"/utility-disconnections/{disconnection_id}/resolve", payload, headers
        )

    # ─── Deed restrictions and monitoring ─────────────────────────────────────

    def list_deed_restrictions(self, headers, params=None):
        return self._request("GET", "/deed-restrictions", headers=headers, params=params)

    def get_deed_restriction(self, restriction_id, headers):
        return self._request("GET", f"/deed-restrictions/{restriction_id}", headers=headers)

    def create_monitoring_inspection(self, restriction_id, payload, headers):
        return self._request(
            "POST", f"/deed-restrictions/{restriction_id}/monitoring-inspections", payload, headers
        )

    def list_monitoring_inspections(self, headers, params=None):
        return self._request("GET", "/monitoring-inspections", headers=headers, params=params)

    def get_monitoring_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/monitoring-inspections/{inspection_id}", headers=headers
        )

    def cure_deed_restriction(self, restriction_id, payload, headers):
        return self._request(
            "POST", f"/deed-restrictions/{restriction_id}/cure", payload, headers
        )

    def terminate_deed_restriction(self, restriction_id, payload, headers):
        return self._request(
            "POST", f"/deed-restrictions/{restriction_id}/terminate", payload, headers
        )

    # ─── Program income ledger ────────────────────────────────────────────────

    def create_program_income_entry(self, project_id, payload, headers):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/program-income-entries", payload, headers
        )

    def list_program_income_entries(self, headers, params=None):
        return self._request("GET", "/program-income-entries", headers=headers, params=params)

    def get_program_income_entry(self, entry_id, headers):
        return self._request("GET", f"/program-income-entries/{entry_id}", headers=headers)

    def reverse_program_income_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/program-income-entries/{entry_id}/reverse", payload, headers
        )


api_client = ApiClient()
