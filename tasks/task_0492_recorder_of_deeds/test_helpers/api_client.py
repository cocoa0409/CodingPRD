"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- RecordingOffice ---
    def create_office(self, payload, headers):
        return self._request("POST", "/offices", payload, headers)

    def get_office(self, office_id, headers):
        return self._request("GET", f"/offices/{office_id}", headers=headers)

    def deposit_escrow(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/deposit-escrow", payload, headers)

    # --- Submitter ---
    def create_submitter(self, payload, headers):
        return self._request("POST", "/submitters", payload, headers)

    def get_submitter(self, submitter_id, headers):
        return self._request("GET", f"/submitters/{submitter_id}", headers=headers)

    def suspend_submitter(self, submitter_id, headers):
        return self._request("POST", f"/submitters/{submitter_id}/suspend", {}, headers)

    def list_submitters(self, headers, params=None):
        return self._request("GET", "/submitters", headers=headers, params=params)

    # --- DocumentPackage ---
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    def add_party_entry(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/party-entries", payload, headers)

    def list_party_entries(self, package_id, headers, params=None):
        return self._request("GET", f"/packages/{package_id}/party-entries", headers=headers, params=params)

    def begin_examination(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/begin-examination", {}, headers)

    def create_assessment(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/assessments", payload, headers)

    def list_assessments(self, package_id, headers, params=None):
        return self._request("GET", f"/packages/{package_id}/assessments", headers=headers, params=params)

    def reject_package(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/reject", payload, headers)

    def list_rejections(self, package_id, headers, params=None):
        return self._request("GET", f"/packages/{package_id}/rejections", headers=headers, params=params)

    def re_record(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/re-record", payload, headers)

    def create_payment(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/payments", payload, headers)

    def list_payments(self, package_id, headers, params=None):
        return self._request("GET", f"/packages/{package_id}/payments", headers=headers, params=params)

    def record_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/record", {}, headers)

    def get_package_recorded_document(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}/recorded-document", headers=headers)

    def withdraw_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/withdraw", {}, headers)

    # --- RecordedDocument ---
    def get_recorded_document(self, recorded_document_id, headers):
        return self._request("GET", f"/recorded-documents/{recorded_document_id}", headers=headers)

    def void_correction(self, recorded_document_id, headers):
        return self._request("POST", f"/recorded-documents/{recorded_document_id}/void-correction", {}, headers)

    # --- PlatSurvey ---
    def create_plat(self, payload, headers):
        return self._request("POST", "/plats", payload, headers)

    def get_plat(self, plat_id, headers):
        return self._request("GET", f"/plats/{plat_id}", headers=headers)

    def list_plats(self, headers, params=None):
        return self._request("GET", "/plats", headers=headers, params=params)

    def approve_plat(self, plat_id, headers):
        return self._request("POST", f"/plats/{plat_id}/approve", {}, headers)

    def reject_plat(self, plat_id, headers):
        return self._request("POST", f"/plats/{plat_id}/reject", {}, headers)

    def record_plat(self, plat_id, headers):
        return self._request("POST", f"/plats/{plat_id}/record", {}, headers)

    # --- LienUccFiling ---
    def create_ucc_filing(self, payload, headers):
        return self._request("POST", "/ucc-filings", payload, headers)

    def get_ucc_filing(self, filing_id, headers):
        return self._request("GET", f"/ucc-filings/{filing_id}", headers=headers)

    def list_ucc_filings(self, headers, params=None):
        return self._request("GET", "/ucc-filings", headers=headers, params=params)

    def continue_ucc_filing(self, filing_id, headers):
        return self._request("POST", f"/ucc-filings/{filing_id}/continue", {}, headers)

    def terminate_ucc_filing(self, filing_id, headers):
        return self._request("POST", f"/ucc-filings/{filing_id}/terminate", {}, headers)

    # --- CopySearchRequest ---
    def create_copy_search_request(self, payload, headers):
        return self._request("POST", "/copy-search-requests", payload, headers)

    def get_copy_search_request(self, request_id, headers):
        return self._request("GET", f"/copy-search-requests/{request_id}", headers=headers)

    def list_copy_search_requests(self, headers, params=None):
        return self._request("GET", "/copy-search-requests", headers=headers, params=params)

    def fulfill_copy_search_request(self, request_id, headers):
        return self._request("POST", f"/copy-search-requests/{request_id}/fulfill", {}, headers)

    def deny_copy_search_request(self, request_id, headers):
        return self._request("POST", f"/copy-search-requests/{request_id}/deny", {}, headers)

    # --- Test-driving: logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
