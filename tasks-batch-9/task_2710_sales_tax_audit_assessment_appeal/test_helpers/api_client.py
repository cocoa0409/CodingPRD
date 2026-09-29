"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Permit holders ---------------------------------------------------
    def create_taxpayer(self, payload, headers):
        return self._request("POST", "/taxpayers", payload, headers)

    def list_taxpayers(self, headers, params=None):
        return self._request("GET", "/taxpayers", headers=headers, params=params)

    def get_taxpayer(self, taxpayer_id, headers):
        return self._request("GET", f"/taxpayers/{taxpayer_id}", headers=headers)

    def rescore_screening(self, taxpayer_id, headers, payload=None):
        return self._request(
            "POST", f"/taxpayers/{taxpayer_id}/rescore-screening", payload, headers
        )

    def list_taxpayer_information_returns(self, taxpayer_id, headers, params=None):
        return self._request(
            "GET",
            f"/taxpayers/{taxpayer_id}/information-returns",
            headers=headers,
            params=params,
        )

    # --- Information returns ---------------------------------------------
    def create_information_return(self, payload, headers):
        return self._request("POST", "/information-returns", payload, headers)

    def get_information_return(self, information_return_id, headers):
        return self._request(
            "GET", f"/information-returns/{information_return_id}", headers=headers
        )

    # --- Industry projects ------------------------------------------------
    def create_industry_project(self, payload, headers):
        return self._request("POST", "/industry-projects", payload, headers)

    def list_industry_projects(self, headers, params=None):
        return self._request("GET", "/industry-projects", headers=headers, params=params)

    def get_industry_project(self, project_id, headers):
        return self._request("GET", f"/industry-projects/{project_id}", headers=headers)

    def create_selection_run(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/industry-projects/{project_id}/selection-runs", payload, headers
        )

    # --- Audit leads ------------------------------------------------------
    def list_audit_leads(self, headers, params=None):
        return self._request("GET", "/audit-leads", headers=headers, params=params)

    def get_audit_lead(self, lead_id, headers):
        return self._request("GET", f"/audit-leads/{lead_id}", headers=headers)

    def decline_audit_lead(self, lead_id, payload, headers):
        return self._request(
            "POST", f"/audit-leads/{lead_id}/decline", payload, headers
        )

    def convert_audit_lead(self, lead_id, payload, headers):
        return self._request(
            "POST", f"/audit-leads/{lead_id}/convert", payload, headers
        )

    # --- Audits -----------------------------------------------------------
    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def scope_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/scope", payload, headers)

    def project_sample(self, audit_id, headers, payload=None):
        return self._request(
            "POST", f"/audits/{audit_id}/project-sample", payload, headers
        )

    def close_fieldwork(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/audits/{audit_id}/close-fieldwork", payload, headers
        )

    def reopen_fieldwork(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/audits/{audit_id}/reopen-fieldwork", payload, headers
        )

    def abandon_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/abandon", payload, headers)

    def get_liability_preview(self, audit_id, headers):
        return self._request(
            "GET", f"/audits/{audit_id}/liability-preview", headers=headers
        )

    def list_audit_statute_waivers(self, audit_id, headers, params=None):
        return self._request(
            "GET", f"/audits/{audit_id}/statute-waivers", headers=headers, params=params
        )

    def list_audit_use_tax_purchases(self, audit_id, headers, params=None):
        return self._request(
            "GET",
            f"/audits/{audit_id}/use-tax-purchases",
            headers=headers,
            params=params,
        )

    # --- Statute waivers --------------------------------------------------
    def create_statute_waiver(self, payload, headers):
        return self._request("POST", "/statute-waivers", payload, headers)

    def get_statute_waiver(self, waiver_id, headers):
        return self._request("GET", f"/statute-waivers/{waiver_id}", headers=headers)

    def execute_statute_waiver(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"/statute-waivers/{waiver_id}/execute", payload, headers
        )

    def void_statute_waiver(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"/statute-waivers/{waiver_id}/void", payload, headers
        )

    # --- Sampling agreements ----------------------------------------------
    def create_sampling_agreement(self, payload, headers):
        return self._request("POST", "/sampling-agreements", payload, headers)

    def list_sampling_agreements(self, headers, params=None):
        return self._request(
            "GET", "/sampling-agreements", headers=headers, params=params
        )

    def get_sampling_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/sampling-agreements/{agreement_id}", headers=headers
        )

    def counter_sampling_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/sampling-agreements/{agreement_id}/counter", payload, headers
        )

    def revise_sampling_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/sampling-agreements/{agreement_id}/revise", payload, headers
        )

    def agree_sampling_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/sampling-agreements/{agreement_id}/agree", payload, headers
        )

    def list_agreement_sample_units(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/sampling-agreements/{agreement_id}/sample-units",
            headers=headers,
            params=params,
        )

    # --- Sample units -----------------------------------------------------
    def create_sample_unit(self, payload, headers):
        return self._request("POST", "/sample-units", payload, headers)

    def get_sample_unit(self, sample_unit_id, headers):
        return self._request("GET", f"/sample-units/{sample_unit_id}", headers=headers)

    def redetermine_sample_unit(self, sample_unit_id, payload, headers):
        return self._request(
            "POST", f"/sample-units/{sample_unit_id}/redetermine", payload, headers
        )

    # --- Exemption certificates -------------------------------------------
    def create_exemption_certificate(self, payload, headers):
        return self._request("POST", "/exemption-certificates", payload, headers)

    def list_exemption_certificates(self, headers, params=None):
        return self._request(
            "GET", "/exemption-certificates", headers=headers, params=params
        )

    def get_exemption_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/exemption-certificates/{certificate_id}", headers=headers
        )

    def review_exemption_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/exemption-certificates/{certificate_id}/review", payload, headers
        )

    def cure_exemption_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/exemption-certificates/{certificate_id}/cure", payload, headers
        )

    # --- Use-tax purchases ------------------------------------------------
    def create_use_tax_purchase(self, payload, headers):
        return self._request("POST", "/use-tax-purchases", payload, headers)

    def get_use_tax_purchase(self, purchase_id, headers):
        return self._request("GET", f"/use-tax-purchases/{purchase_id}", headers=headers)

    def reclassify_use_tax_purchase(self, purchase_id, payload, headers):
        return self._request(
            "POST", f"/use-tax-purchases/{purchase_id}/reclassify", payload, headers
        )

    # --- Assessments ------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def recompute_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"/assessments/{assessment_id}/recompute", payload, headers
        )

    def issue_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/issue", payload, headers
        )

    def abate_penalty(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/abate-penalty", payload, headers
        )

    def finalize_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"/assessments/{assessment_id}/finalize", payload, headers
        )

    def refer_to_collections(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/collection-referral", payload, headers
        )

    def list_assessment_payment_arrangements(self, assessment_id, headers, params=None):
        return self._request(
            "GET",
            f"/assessments/{assessment_id}/payment-arrangements",
            headers=headers,
            params=params,
        )

    # --- Assessment adjustments (the ledger) ------------------------------
    def create_assessment_adjustment(self, payload, headers):
        return self._request("POST", "/assessment-adjustments", payload, headers)

    def list_assessment_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/assessment-adjustments", headers=headers, params=params
        )

    def get_assessment_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/assessment-adjustments/{adjustment_id}", headers=headers
        )

    def reverse_assessment_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST", f"/assessment-adjustments/{adjustment_id}/reverse", payload, headers
        )

    # --- Appeal proceedings -----------------------------------------------
    def create_appeal_proceeding(self, payload, headers):
        return self._request("POST", "/appeal-proceedings", payload, headers)

    def list_appeal_proceedings(self, headers, params=None):
        return self._request(
            "GET", "/appeal-proceedings", headers=headers, params=params
        )

    def get_appeal_proceeding(self, proceeding_id, headers):
        return self._request(
            "GET", f"/appeal-proceedings/{proceeding_id}", headers=headers
        )

    def decide_appeal_proceeding(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"/appeal-proceedings/{proceeding_id}/decision", payload, headers
        )

    # --- Payment arrangements ---------------------------------------------
    def create_payment_arrangement(self, payload, headers):
        return self._request("POST", "/payment-arrangements", payload, headers)

    def get_payment_arrangement(self, arrangement_id, headers):
        return self._request(
            "GET", f"/payment-arrangements/{arrangement_id}", headers=headers
        )

    def approve_payment_arrangement(self, arrangement_id, headers, payload=None):
        return self._request(
            "POST", f"/payment-arrangements/{arrangement_id}/approve", payload, headers
        )

    def create_arrangement_payment(self, arrangement_id, payload, headers):
        return self._request(
            "POST", f"/payment-arrangements/{arrangement_id}/payments", payload, headers
        )

    def default_payment_arrangement(self, arrangement_id, payload, headers):
        return self._request(
            "POST", f"/payment-arrangements/{arrangement_id}/default", payload, headers
        )

    # --- Logical clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
