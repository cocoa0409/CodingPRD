"""Domain client for the residential PACE financing API.

One method per endpoint, named after the program action it performs.  Every
method returns the raw HTTP response so the caller decides whether to validate
it as a success or as an error.  Headers are always passed in explicitly: the
program has seven roles and several of them are identity-bearing, so there is
no sensible default caller.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload, ResourceId


class PaceApiClient(GenericApiClient):
    """HTTP surface of the PACE program, expressed in program vocabulary."""

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Headers):
        return self.post("/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    # ------------------------------------------------------------------
    # properties
    # ------------------------------------------------------------------

    def register_property(self, payload: Payload, headers: Headers):
        return self.post("/pace/properties", payload, headers)

    def get_property(self, property_id: ResourceId, headers: Headers):
        return self.get("/pace/properties/{0}".format(property_id), headers)

    def patch_valuation(self, property_id: ResourceId, payload: Payload, headers: Headers):
        return self._request(
            "PATCH",
            "/pace/properties/{0}/valuation".format(property_id),
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # mortgage liens
    # ------------------------------------------------------------------

    def record_mortgage_lien(self, payload: Payload, headers: Headers):
        return self.post("/pace/mortgage-liens", payload, headers)

    def get_mortgage_lien(self, lien_id: ResourceId, headers: Headers):
        return self.get("/pace/mortgage-liens/{0}".format(lien_id), headers)

    def list_mortgage_liens(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self.get("/pace/mortgage-liens", headers, params)

    def record_consent_response(
        self, lien_id: ResourceId, payload: Payload, headers: Headers
    ):
        return self.post(
            "/pace/mortgage-liens/{0}/consent-response".format(lien_id), payload, headers
        )

    # ------------------------------------------------------------------
    # eligible products
    # ------------------------------------------------------------------

    def create_product(self, payload: Payload, headers: Headers):
        return self.post("/pace/products", payload, headers)

    def get_product(self, product_id: ResourceId, headers: Headers):
        return self.get("/pace/products/{0}".format(product_id), headers)

    def list_products(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self.get("/pace/products", headers, params)

    def patch_product(self, product_id: ResourceId, payload: Payload, headers: Headers):
        return self._request(
            "PATCH", "/pace/products/{0}".format(product_id), payload, headers
        )

    # ------------------------------------------------------------------
    # contractors
    # ------------------------------------------------------------------

    def create_contractor(self, payload: Payload, headers: Headers):
        return self.post("/pace/contractors", payload, headers)

    def get_contractor(self, contractor_id: ResourceId, headers: Headers):
        return self.get("/pace/contractors/{0}".format(contractor_id), headers)

    def list_contractors(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self.get("/pace/contractors", headers, params)

    def enroll_contractor(self, contractor_id: ResourceId, headers: Headers, payload: Optional[Payload] = None):
        return self.post(
            "/pace/contractors/{0}/enroll".format(contractor_id), payload or {}, headers
        )

    def reinstate_contractor(
        self, contractor_id: ResourceId, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            "/pace/contractors/{0}/reinstate".format(contractor_id), payload or {}, headers
        )

    # ------------------------------------------------------------------
    # applications
    # ------------------------------------------------------------------

    def open_application(self, payload: Payload, headers: Headers):
        return self.post("/pace/applications", payload, headers)

    def get_application(self, application_id: ResourceId, headers: Headers):
        return self.get("/pace/applications/{0}".format(application_id), headers)

    def list_applications(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self.get("/pace/applications", headers, params)

    def add_measure(self, application_id: ResourceId, payload: Payload, headers: Headers):
        return self.post(
            "/pace/applications/{0}/measures".format(application_id), payload, headers
        )

    def submit_application(
        self, application_id: ResourceId, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            "/pace/applications/{0}/submit".format(application_id), payload or {}, headers
        )

    def underwrite_application(
        self, application_id: ResourceId, payload: Payload, headers: Headers
    ):
        return self.post(
            "/pace/applications/{0}/underwrite".format(application_id), payload, headers
        )

    def cure_application(
        self, application_id: ResourceId, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            "/pace/applications/{0}/cure".format(application_id), payload or {}, headers
        )

    def approve_application(
        self, application_id: ResourceId, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            "/pace/applications/{0}/approve".format(application_id), payload or {}, headers
        )

    def get_eligibility_report(self, application_id: ResourceId, headers: Headers):
        return self.get(
            "/pace/applications/{0}/eligibility-report".format(application_id), headers
        )

    def list_application_agreements(
        self,
        application_id: ResourceId,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            "/pace/applications/{0}/financing-agreements".format(application_id),
            headers,
            params,
        )

    def list_application_certificates(
        self,
        application_id: ResourceId,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            "/pace/applications/{0}/completion-certificates".format(application_id),
            headers,
            params,
        )

    # ------------------------------------------------------------------
    # project measures
    # ------------------------------------------------------------------

    def get_measure(self, measure_id: ResourceId, headers: Headers):
        return self.get("/pace/measures/{0}".format(measure_id), headers)

    def list_measures(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self.get("/pace/measures", headers, params)

    # ------------------------------------------------------------------
    # financing agreements
    # ------------------------------------------------------------------

    def issue_agreement(self, payload: Payload, headers: Headers):
        return self.post("/pace/financing-agreements", payload, headers)

    def get_agreement(self, agreement_id: ResourceId, headers: Headers):
        return self.get("/pace/financing-agreements/{0}".format(agreement_id), headers)

    def sign_agreement(self, agreement_id: ResourceId, payload: Payload, headers: Headers):
        return self.post(
            "/pace/financing-agreements/{0}/sign".format(agreement_id), payload, headers
        )

    def record_oral_confirmation(
        self, agreement_id: ResourceId, payload: Optional[Payload], headers: Headers
    ):
        return self.post(
            "/pace/financing-agreements/{0}/oral-confirmation".format(agreement_id),
            payload or {},
            headers,
        )

    def rescind_agreement(
        self, agreement_id: ResourceId, payload: Payload, headers: Headers
    ):
        return self.post(
            "/pace/financing-agreements/{0}/rescind".format(agreement_id), payload, headers
        )

    # ------------------------------------------------------------------
    # completion certificates
    # ------------------------------------------------------------------

    def file_certificate(self, payload: Payload, headers: Headers):
        return self.post("/pace/completion-certificates", payload, headers)

    def get_certificate(self, certificate_id: ResourceId, headers: Headers):
        return self.get("/pace/completion-certificates/{0}".format(certificate_id), headers)

    def sign_certificate(
        self, certificate_id: ResourceId, payload: Payload, headers: Headers
    ):
        return self.post(
            "/pace/completion-certificates/{0}/sign".format(certificate_id), payload, headers
        )

    def verify_certificate(
        self, certificate_id: ResourceId, payload: Payload, headers: Headers
    ):
        return self.post(
            "/pace/completion-certificates/{0}/verify".format(certificate_id),
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # disbursements
    # ------------------------------------------------------------------

    def request_disbursement(self, payload: Payload, headers: Headers):
        return self.post("/pace/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id: ResourceId, headers: Headers):
        return self.get("/pace/disbursements/{0}".format(disbursement_id), headers)

    def list_disbursements(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self.get("/pace/disbursements", headers, params)

    def release_disbursement(
        self, disbursement_id: ResourceId, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            "/pace/disbursements/{0}/release".format(disbursement_id), payload or {}, headers
        )

    def reverse_disbursement(
        self, disbursement_id: ResourceId, payload: Payload, headers: Headers
    ):
        return self.post(
            "/pace/disbursements/{0}/reverse".format(disbursement_id), payload, headers
        )

    # ------------------------------------------------------------------
    # workmanship complaints
    # ------------------------------------------------------------------

    def file_complaint(self, payload: Payload, headers: Headers):
        return self.post("/pace/complaints", payload, headers)

    def get_complaint(self, complaint_id: ResourceId, headers: Headers):
        return self.get("/pace/complaints/{0}".format(complaint_id), headers)

    def list_complaints(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self.get("/pace/complaints", headers, params)

    def adjudicate_complaint(
        self, complaint_id: ResourceId, payload: Payload, headers: Headers
    ):
        return self.post(
            "/pace/complaints/{0}/adjudicate".format(complaint_id), payload, headers
        )

    # ------------------------------------------------------------------
    # assessments and the tax roll
    # ------------------------------------------------------------------

    def record_assessment(self, payload: Payload, headers: Headers):
        return self.post("/pace/assessments", payload, headers)

    def get_assessment(self, assessment_id: ResourceId, headers: Headers):
        return self.get("/pace/assessments/{0}".format(assessment_id), headers)

    def list_assessments(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self.get("/pace/assessments", headers, params)

    def list_installments(
        self,
        assessment_id: ResourceId,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            "/pace/assessments/{0}/installments".format(assessment_id), headers, params
        )

    def get_installment(
        self, assessment_id: ResourceId, installment_id: ResourceId, headers: Headers
    ):
        return self.get(
            "/pace/assessments/{0}/installments/{1}".format(assessment_id, installment_id),
            headers,
        )

    def pay_installment(
        self,
        assessment_id: ResourceId,
        installment_id: ResourceId,
        payload: Payload,
        headers: Headers,
    ):
        return self.post(
            "/pace/assessments/{0}/installments/{1}/payments".format(
                assessment_id, installment_id
            ),
            payload,
            headers,
        )

    def prepay_assessment(
        self, assessment_id: ResourceId, payload: Payload, headers: Headers
    ):
        return self.post(
            "/pace/assessments/{0}/prepayments".format(assessment_id), payload, headers
        )

    def list_assessment_transfers(
        self,
        assessment_id: ResourceId,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            "/pace/assessments/{0}/transfers".format(assessment_id), headers, params
        )

    # ------------------------------------------------------------------
    # payoff quotes and transfers
    # ------------------------------------------------------------------

    def quote_transfer(self, payload: Payload, headers: Headers):
        return self.post("/pace/assessment-transfers", payload, headers)

    def get_transfer(self, transfer_id: ResourceId, headers: Headers):
        return self.get("/pace/assessment-transfers/{0}".format(transfer_id), headers)

    def record_transfer(
        self, transfer_id: ResourceId, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            "/pace/assessment-transfers/{0}/record".format(transfer_id), payload or {}, headers
        )

    # ------------------------------------------------------------------
    # county roll runs
    # ------------------------------------------------------------------

    def run_county_roll(self, county_code: str, payload: Payload, headers: Headers):
        return self.post(
            "/pace/counties/{0}/roll-runs".format(county_code), payload, headers
        )
