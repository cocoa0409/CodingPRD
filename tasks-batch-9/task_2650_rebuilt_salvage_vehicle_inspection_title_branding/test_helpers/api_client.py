"""API client: one method per endpoint the PRD declares."""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to the rebuilt-salvage program API."""

    # ------------------------------------------------------------------ reads
    def get_vehicle(self, vehicle_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}", headers=headers)

    def get_rebuilder(self, rebuilder_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/rebuilders/{rebuilder_id}", headers=headers)

    def get_inspector(self, inspector_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/inspectors/{inspector_id}", headers=headers)

    def get_inspection_station(self, station_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/inspection-stations/{station_id}", headers=headers
        )

    def get_damage_report(self, report_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/damage-reports/{report_id}", headers=headers)

    def list_damage_reports(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/damage-reports", headers=headers, params=params)

    def get_title_record(self, title_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/title-records/{title_id}", headers=headers)

    def list_title_records(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/title-records", headers=headers, params=params)

    def get_application(self, application_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/applications/{application_id}", headers=headers)

    def list_applications(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/applications", headers=headers, params=params)

    def get_fee_quote(self, application_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/applications/{application_id}/fee-quote", headers=headers
        )

    def get_parts_document(self, document_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/parts-documents/{document_id}", headers=headers)

    def list_parts_documents(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/parts-documents", headers=headers, params=params)

    def get_inspection(self, inspection_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/inspections", headers=headers, params=params)

    def get_finding(self, finding_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/findings/{finding_id}", headers=headers)

    def list_findings(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/findings", headers=headers, params=params)

    def get_appeal(self, appeal_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/appeals", headers=headers, params=params)

    def get_fraud_referral(self, referral_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/fraud-referrals/{referral_id}", headers=headers)

    def list_fraud_referrals(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/fraud-referrals", headers=headers, params=params)

    def get_recognition_request(self, request_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/recognition-requests/{request_id}", headers=headers
        )

    def list_recognition_requests(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/recognition-requests", headers=headers, params=params
        )

    def get_title_transfer(self, transfer_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/v1/title-transfers/{transfer_id}", headers=headers)

    def list_title_transfers(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/v1/title-transfers", headers=headers, params=params)

    # ----------------------------------------------------------------- writes
    def create_vehicle(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/vehicles", payload, headers)

    def create_rebuilder(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/rebuilders", payload, headers)

    def create_deposit(self, rebuilder_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/v1/rebuilders/{rebuilder_id}/deposits", payload, headers
        )

    def create_license_action(
        self, rebuilder_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/rebuilders/{rebuilder_id}/license-actions", payload, headers
        )

    def create_inspector(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/inspectors", payload, headers)

    def create_inspection_station(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/inspection-stations", payload, headers)

    def create_damage_report(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/damage-reports", payload, headers)

    def create_title_record(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/title-records", payload, headers)

    def surrender_title_record(
        self, title_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/title-records/{title_id}/surrender", payload, headers
        )

    def create_application(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/applications", payload, headers)

    def create_parts_document(
        self, application_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/applications/{application_id}/parts-documents", payload, headers
        )

    def verify_parts_document(
        self, document_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/parts-documents/{document_id}/verify", payload, headers
        )

    def reject_parts_document(
        self, document_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/parts-documents/{document_id}/reject", payload, headers
        )

    def submit_application(
        self, application_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/applications/{application_id}/submit", payload, headers
        )

    def review_application_docs(
        self, application_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/applications/{application_id}/docs-review", payload, headers
        )

    def schedule_inspection(
        self, application_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/applications/{application_id}/inspections", payload, headers
        )

    def start_inspection(
        self, inspection_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/inspections/{inspection_id}/start", payload, headers
        )

    def create_finding(
        self, inspection_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/inspections/{inspection_id}/findings", payload, headers
        )

    def complete_inspection(
        self, inspection_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/inspections/{inspection_id}/complete", payload, headers
        )

    def cancel_inspection(
        self, inspection_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/inspections/{inspection_id}/cancel", payload, headers
        )

    def withdraw_application(
        self, application_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/applications/{application_id}/withdraw", payload, headers
        )

    def issue_rebuilt_title(
        self, application_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/v1/applications/{application_id}/issue-rebuilt-title",
            payload,
            headers,
        )

    def create_appeal(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/appeals", payload, headers)

    def review_appeal(self, appeal_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/v1/appeals/{appeal_id}/review", payload, headers)

    def decide_appeal(self, appeal_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/v1/appeals/{appeal_id}/decide", payload, headers)

    def create_title_transfer(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/title-transfers", payload, headers)

    def create_fraud_referral(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/fraud-referrals", payload, headers)

    def investigate_fraud_referral(
        self, referral_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/fraud-referrals/{referral_id}/investigate", payload, headers
        )

    def resolve_fraud_referral(
        self, referral_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/fraud-referrals/{referral_id}/resolve", payload, headers
        )

    def create_recognition_request(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/recognition-requests", payload, headers)

    def decide_recognition_request(
        self, request_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/v1/recognition-requests/{request_id}/decide", payload, headers
        )

    def set_clock(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
