"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Applicant ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ---- Officiant ----
    def create_officiant(self, payload, headers):
        return self._request("POST", "/officiants", payload, headers)

    def get_officiant(self, officiant_id, headers):
        return self._request("GET", f"/officiants/{officiant_id}", headers=headers)

    def suspend_officiant(self, officiant_id, headers):
        return self._request("POST", f"/officiants/{officiant_id}/suspend", headers=headers)

    def list_officiant_returns(self, officiant_id, headers, params=None):
        return self._request("GET", f"/officiants/{officiant_id}/returns", headers=headers, params=params)

    # ---- MarriageApplication ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/decide", payload, headers)

    def list_application_licenses(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/licenses", headers=headers, params=params)

    def list_application_ledger(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/ledger", headers=headers, params=params)

    # ---- MarriageLicense ----
    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def expire_check_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/expire-check", {}, headers)

    def void_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/void", {}, headers)

    # ---- OfficiantReturn ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def accept_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/accept", {}, headers)

    def reject_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/reject", payload, headers)

    # ---- MarriageRecord ----
    def get_record(self, record_id, headers):
        return self._request("GET", f"/records/{record_id}", headers=headers)

    def list_records(self, headers, params=None):
        return self._request("GET", "/records", headers=headers, params=params)

    def seal_record(self, record_id, headers):
        return self._request("POST", f"/records/{record_id}/seal", {}, headers)

    def list_record_certified_copies(self, record_id, headers, params=None):
        return self._request("GET", f"/records/{record_id}/certified-copies", headers=headers, params=params)

    def list_record_amendments(self, record_id, headers, params=None):
        return self._request("GET", f"/records/{record_id}/amendments", headers=headers, params=params)

    # ---- CertifiedCopyRequest ----
    def create_certified_copy(self, payload, headers):
        return self._request("POST", "/certified-copies", payload, headers)

    def list_certified_copies(self, headers, params=None):
        return self._request("GET", "/certified-copies", headers=headers, params=params)

    def get_certified_copy(self, copy_id, headers):
        return self._request("GET", f"/certified-copies/{copy_id}", headers=headers)

    def decide_certified_copy(self, copy_id, payload, headers):
        return self._request("POST", f"/certified-copies/{copy_id}/decide", payload, headers)

    def refund_certified_copy(self, copy_id, headers):
        return self._request("POST", f"/certified-copies/{copy_id}/refund", {}, headers)

    def list_certified_copy_apostilles(self, copy_id, headers, params=None):
        return self._request("GET", f"/certified-copies/{copy_id}/apostilles", headers=headers, params=params)

    # ---- AmendmentRequest ----
    def create_amendment(self, payload, headers):
        return self._request("POST", "/amendments", payload, headers)

    def get_amendment(self, amendment_id, headers):
        return self._request("GET", f"/amendments/{amendment_id}", headers=headers)

    def decide_amendment(self, amendment_id, payload, headers):
        return self._request("POST", f"/amendments/{amendment_id}/decide", payload, headers)

    def resubmit_amendment(self, amendment_id, headers):
        return self._request("POST", f"/amendments/{amendment_id}/resubmit", {}, headers)

    # ---- ApostilleRequest ----
    def create_apostille(self, payload, headers):
        return self._request("POST", "/apostilles", payload, headers)

    def get_apostille(self, apostille_id, headers):
        return self._request("GET", f"/apostilles/{apostille_id}", headers=headers)

    def decide_apostille(self, apostille_id, payload, headers):
        return self._request("POST", f"/apostilles/{apostille_id}/decide", payload, headers)

    # ---- FeeWaiver ----
    def create_fee_waiver(self, payload, headers):
        return self._request("POST", "/fee-waivers", payload, headers)

    def get_fee_waiver(self, waiver_id, headers):
        return self._request("GET", f"/fee-waivers/{waiver_id}", headers=headers)

    def list_fee_waivers(self, headers, params=None):
        return self._request("GET", "/fee-waivers", headers=headers, params=params)

    def decide_fee_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/fee-waivers/{waiver_id}/decide", payload, headers)

    # ---- Clock / system ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
