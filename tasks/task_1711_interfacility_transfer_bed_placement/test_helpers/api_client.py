"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Facilities, beds, physicians, diversion events
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facility_beds(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/beds",
                             headers=headers, params=params)

    def list_facility_physicians(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/physicians",
                             headers=headers, params=params)

    def list_facility_diversion_events(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/diversion-events",
                             headers=headers, params=params)

    def create_bed(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/beds",
                             payload, headers)

    def update_bed(self, bed_id, payload, headers):
        return self._request("PUT", f"/beds/{bed_id}", payload, headers)

    def create_physician(self, payload, headers):
        return self._request("POST", "/physicians", payload, headers)

    def create_diversion_event(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/diversion-events",
                             payload, headers)

    def lift_diversion_event(self, event_id, headers):
        return self._request("POST", f"/diversion-events/{event_id}/lift",
                             {}, headers)

    # ------------------------------------------------------------------
    # Transfer cases and EMTALA screening
    # ------------------------------------------------------------------
    def create_transfer_case(self, payload, headers):
        return self._request("POST", "/transfer-cases", payload, headers)

    def list_transfer_cases(self, headers, params=None):
        return self._request("GET", "/transfer-cases", headers=headers, params=params)

    def get_transfer_case(self, case_id, headers):
        return self._request("GET", f"/transfer-cases/{case_id}", headers=headers)

    def create_emtala_screening(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/emtala-screening",
                             payload, headers)

    def get_emtala_screening(self, case_id, headers):
        return self._request("GET", f"/transfer-cases/{case_id}/emtala-screening",
                             headers=headers)

    def certify_emtala_screening(self, case_id, headers):
        return self._request("POST",
                             f"/transfer-cases/{case_id}/emtala-screening/certify",
                             {}, headers)

    def amend_emtala_screening(self, case_id, payload, headers):
        return self._request("POST",
                             f"/transfer-cases/{case_id}/emtala-screening/amend",
                             payload, headers)

    # ------------------------------------------------------------------
    # Negotiation
    # ------------------------------------------------------------------
    def request_acceptance(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/request-acceptance",
                             payload, headers)

    def re_request(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/re-request",
                             payload, headers)

    def accept_case(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/accept",
                             payload, headers)

    def refuse_case(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/refuse",
                             payload, headers)

    def list_communications(self, headers, params=None):
        return self._request("GET", "/communications", headers=headers, params=params)

    def get_communication(self, communication_id, headers):
        return self._request("GET", f"/communications/{communication_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Bed holds
    # ------------------------------------------------------------------
    def create_bed_hold(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/bed-holds",
                             payload, headers)

    def list_bed_holds(self, headers, params=None):
        return self._request("GET", "/bed-holds", headers=headers, params=params)

    def get_bed_hold(self, hold_id, headers):
        return self._request("GET", f"/bed-holds/{hold_id}", headers=headers)

    def release_bed_hold(self, hold_id, headers):
        return self._request("POST", f"/bed-holds/{hold_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def create_dispatch(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/dispatch",
                             payload, headers)

    def list_transport_dispatches(self, headers, params=None):
        return self._request("GET", "/transport-dispatches",
                             headers=headers, params=params)

    def get_transport_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/transport-dispatches/{dispatch_id}",
                             headers=headers)

    def cancel_transport_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/transport-dispatches/{dispatch_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Case lifecycle
    # ------------------------------------------------------------------
    def depart_case(self, case_id, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/depart", {}, headers)

    def arrive_case(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/arrive",
                             payload, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/complete",
                             {}, headers)

    def cancel_case(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/cancel",
                             payload, headers)

    def get_case_outcome(self, case_id, headers):
        return self._request("GET", f"/transfer-cases/{case_id}/outcome",
                             headers=headers)

    # ------------------------------------------------------------------
    # Insurance notifications
    # ------------------------------------------------------------------
    def create_insurance_notification(self, case_id, payload, headers):
        return self._request("POST",
                             f"/transfer-cases/{case_id}/insurance-notifications",
                             payload, headers)

    def list_insurance_notifications(self, headers, params=None):
        return self._request("GET", "/insurance-notifications",
                             headers=headers, params=params)

    def get_insurance_notification(self, notification_id, headers):
        return self._request("GET", f"/insurance-notifications/{notification_id}",
                             headers=headers)

    def notify_insurance(self, notification_id, headers):
        return self._request("POST",
                             f"/insurance-notifications/{notification_id}/notify",
                             {}, headers)

    def claim_exception(self, notification_id, payload, headers):
        return self._request(
            "POST", f"/insurance-notifications/{notification_id}/claim-exception",
            payload, headers)

    # ------------------------------------------------------------------
    # Clinical packets
    # ------------------------------------------------------------------
    def create_clinical_packet(self, case_id, payload, headers):
        return self._request("POST", f"/transfer-cases/{case_id}/clinical-packet",
                             payload, headers)

    def list_clinical_packets(self, headers, params=None):
        return self._request("GET", "/clinical-packets", headers=headers, params=params)

    def get_clinical_packet(self, packet_id, headers):
        return self._request("GET", f"/clinical-packets/{packet_id}", headers=headers)

    def upload_packet_documents(self, packet_id, payload, headers):
        return self._request("POST", f"/clinical-packets/{packet_id}/documents",
                             payload, headers)

    def imaging_exchange(self, packet_id, payload, headers):
        return self._request("POST",
                             f"/clinical-packets/{packet_id}/imaging-exchange",
                             payload, headers)

    # ------------------------------------------------------------------
    # Refusal records
    # ------------------------------------------------------------------
    def list_refusal_records(self, headers, params=None):
        return self._request("GET", "/refusal-records", headers=headers, params=params)

    def get_refusal_record(self, record_id, headers):
        return self._request("GET", f"/refusal-records/{record_id}", headers=headers)

    # ------------------------------------------------------------------
    # Quality reviews
    # ------------------------------------------------------------------
    def list_quality_reviews(self, headers, params=None):
        return self._request("GET", "/quality-reviews", headers=headers, params=params)

    def get_quality_review(self, review_id, headers):
        return self._request("GET", f"/quality-reviews/{review_id}", headers=headers)

    def begin_quality_review(self, review_id, headers):
        return self._request("POST", f"/quality-reviews/{review_id}/begin",
                             {}, headers)

    def close_quality_review(self, review_id, payload, headers):
        return self._request("POST", f"/quality-reviews/{review_id}/close",
                             payload, headers)


api_client = ApiClient()
