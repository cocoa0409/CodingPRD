"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/prosthetics"


class ApiClient(GenericApiClient):
    # ---- logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Patient ---------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/patients", headers=headers, params=params)

    # ---- Coverage --------------------------------------------------------
    def create_coverage(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverages", payload, headers)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"{PREFIX}/coverages/{coverage_id}", headers=headers)

    def list_coverages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coverages", headers=headers, params=params)

    # ---- DentalLab -------------------------------------------------------
    def create_lab(self, payload, headers):
        return self._request("POST", f"{PREFIX}/labs", payload, headers)

    def get_lab(self, lab_id, headers):
        return self._request("GET", f"{PREFIX}/labs/{lab_id}", headers=headers)

    def list_labs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/labs", headers=headers, params=params)

    # ---- ProsthesisCase --------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases", headers=headers, params=params)

    def complete_exam(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/complete-exam", {}, headers)

    def cancel_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/cancel", payload if payload is not None else {}, headers
        )

    # ---- CaseArch --------------------------------------------------------
    def create_case_arch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/case-arches", payload, headers)

    def get_case_arch(self, case_arch_id, headers):
        return self._request("GET", f"{PREFIX}/case-arches/{case_arch_id}", headers=headers)

    def list_case_arches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/case-arches", headers=headers, params=params)

    def start_fabrication(self, case_arch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/case-arches/{case_arch_id}/start-fabrication", {}, headers
        )

    # ---- ImpressionRecord ------------------------------------------------
    def create_impression(self, payload, headers):
        return self._request("POST", f"{PREFIX}/impressions", payload, headers)

    def get_impression(self, impression_id, headers):
        return self._request("GET", f"{PREFIX}/impressions/{impression_id}", headers=headers)

    def list_impressions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/impressions", headers=headers, params=params)

    def review_impression(self, impression_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/impressions/{impression_id}/review", payload, headers
        )

    def request_retake(self, impression_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/impressions/{impression_id}/request-retake", payload, headers
        )

    # ---- TryInMilestone --------------------------------------------------
    def create_try_in(self, payload, headers):
        return self._request("POST", f"{PREFIX}/try-ins", payload, headers)

    def get_try_in(self, try_in_id, headers):
        return self._request("GET", f"{PREFIX}/try-ins/{try_in_id}", headers=headers)

    def list_try_ins(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/try-ins", headers=headers, params=params)

    def decide_try_in(self, try_in_id, payload, headers):
        return self._request("POST", f"{PREFIX}/try-ins/{try_in_id}/decide", payload, headers)

    # ---- LabCase ---------------------------------------------------------
    def create_lab_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lab-cases", payload, headers)

    def get_lab_case(self, lab_case_id, headers):
        return self._request("GET", f"{PREFIX}/lab-cases/{lab_case_id}", headers=headers)

    def list_lab_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lab-cases", headers=headers, params=params)

    def dispatch_lab_case(self, lab_case_id, headers):
        return self._request("POST", f"{PREFIX}/lab-cases/{lab_case_id}/dispatch", {}, headers)

    def receive_lab_case(self, lab_case_id, headers):
        return self._request("POST", f"{PREFIX}/lab-cases/{lab_case_id}/receive", {}, headers)

    def qc_lab_case(self, lab_case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lab-cases/{lab_case_id}/qc", payload, headers)

    def resend_lab_case(self, lab_case_id, headers):
        return self._request("POST", f"{PREFIX}/lab-cases/{lab_case_id}/resend", {}, headers)

    # ---- Prosthesis ------------------------------------------------------
    def create_prosthesis(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prostheses", payload, headers)

    def get_prosthesis(self, prosthesis_id, headers):
        return self._request("GET", f"{PREFIX}/prostheses/{prosthesis_id}", headers=headers)

    def list_prostheses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prostheses", headers=headers, params=params)

    def recall_complete(self, prosthesis_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/prostheses/{prosthesis_id}/recall-complete", payload, headers
        )

    # ---- PostDeliveryService ---------------------------------------------
    def create_service(self, payload, headers):
        return self._request("POST", f"{PREFIX}/services", payload, headers)

    def get_service(self, service_id, headers):
        return self._request("GET", f"{PREFIX}/services/{service_id}", headers=headers)

    def list_services(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/services", headers=headers, params=params)

    def complete_service(self, service_id, headers):
        return self._request("POST", f"{PREFIX}/services/{service_id}/complete", {}, headers)

    def void_service(self, service_id, headers):
        return self._request("POST", f"{PREFIX}/services/{service_id}/void", {}, headers)

    # ---- WarrantyClaim ---------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, warranty_claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims/{warranty_claim_id}", headers=headers
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warranty-claims", headers=headers, params=params)

    def adjudicate_warranty_claim(self, warranty_claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{warranty_claim_id}/adjudicate", payload, headers
        )

    def clinical_review_warranty_claim(self, warranty_claim_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/warranty-claims/{warranty_claim_id}/clinical-review",
            payload,
            headers,
        )

    # ---- RemakeRequest ---------------------------------------------------
    def create_remake_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/remake-requests", payload, headers)

    def get_remake_request(self, remake_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/remake-requests/{remake_request_id}", headers=headers
        )

    def list_remake_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/remake-requests", headers=headers, params=params)

    def approve_remake_request(self, remake_request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/remake-requests/{remake_request_id}/approve", {}, headers
        )

    def deny_remake_request(self, remake_request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/remake-requests/{remake_request_id}/deny",
            payload if payload is not None else {},
            headers,
        )

    # ---- Predetermination ------------------------------------------------
    def create_predetermination(self, payload, headers):
        return self._request("POST", f"{PREFIX}/predeterminations", payload, headers)

    def get_predetermination(self, predetermination_id, headers):
        return self._request(
            "GET", f"{PREFIX}/predeterminations/{predetermination_id}", headers=headers
        )

    def list_predeterminations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/predeterminations", headers=headers, params=params
        )

    def determine_predetermination(self, predetermination_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/predeterminations/{predetermination_id}/determine", payload, headers
        )

    # ---- Claim -----------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/submit", {}, headers)

    def post_claim_payment(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/post-payment", payload, headers)

    def reverse_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/claims/{claim_id}/reverse",
            payload if payload is not None else {},
            headers,
        )

    # ---- PaymentPlan -----------------------------------------------------
    def create_payment_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payment-plans", payload, headers)

    def get_payment_plan(self, payment_plan_id, headers):
        return self._request("GET", f"{PREFIX}/payment-plans/{payment_plan_id}", headers=headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payment-plans", headers=headers, params=params)

    def assess_delinquency(self, payment_plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/payment-plans/{payment_plan_id}/assess-delinquency", {}, headers
        )

    # ---- Installment -----------------------------------------------------
    def get_installment(self, installment_id, headers):
        return self._request("GET", f"{PREFIX}/installments/{installment_id}", headers=headers)

    def list_installments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/installments", headers=headers, params=params)

    def pay_installment(self, installment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/installments/{installment_id}/pay", payload, headers
        )

    def reverse_installment_payment(self, installment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/installments/{installment_id}/reverse-payment", {}, headers
        )


api_client = ApiClient()
