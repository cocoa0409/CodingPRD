"""API client: one method per endpoint published by the PRD.

Every path is mounted under the `/battery-warranty` service root. Methods return
the raw `requests.Response` so tests can assert status codes themselves.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/battery-warranty"


class ApiClient(GenericApiClient):
    """Thin wrapper exposing one named method per PRD endpoint."""

    # ───────────────────────── logical clock ─────────────────────────

    def set_clock(self, current_utc: str, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # ─────────────────────── warranty programs ───────────────────────

    def create_warranty_program(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/warranty-programs", payload, headers)

    def get_warranty_program(self, program_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/warranty-programs/{program_id}", headers=headers
        )

    # ───────────────────────────── vehicles ─────────────────────────────

    def create_vehicle(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/vehicles", headers=headers, params=params)

    # ──────────────────────── service centers ────────────────────────

    def create_service_center(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/service-centers", payload, headers)

    def get_service_center(self, center_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/service-centers/{center_id}", headers=headers
        )

    def list_service_centers(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/service-centers", headers=headers, params=params
        )

    # ──────────────────────────── technicians ────────────────────────────

    def create_technician(self, center_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/service-centers/{center_id}/technicians", payload, headers
        )

    def list_technicians(
        self, center_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/service-centers/{center_id}/technicians",
            headers=headers,
            params=params,
        )

    # ─────────────────────────── battery packs ───────────────────────────

    def create_battery_pack(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/battery-packs", payload, headers)

    def get_battery_pack(self, pack_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/battery-packs/{pack_id}", headers=headers
        )

    def list_battery_packs(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/battery-packs", headers=headers, params=params
        )

    def list_battery_modules(
        self, pack_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/battery-packs/{pack_id}/modules",
            headers=headers,
            params=params,
        )

    # ─────────────────────── telematics snapshots ───────────────────────

    def ingest_snapshot(self, vehicle_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/vehicles/{vehicle_id}/telematics-snapshots",
            payload,
            headers,
        )

    def list_snapshots(
        self, vehicle_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/vehicles/{vehicle_id}/telematics-snapshots",
            headers=headers,
            params=params,
        )

    # ───────────────────────── SoH assessments ─────────────────────────

    def create_assessment(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/soh-assessments", payload, headers)

    def get_assessment(self, assessment_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/soh-assessments/{assessment_id}", headers=headers
        )

    def list_assessments(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/soh-assessments", headers=headers, params=params
        )

    # ───────────────────────── warranty claims ─────────────────────────

    def create_claim(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def get_claim(self, claim_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims/{claim_id}", headers=headers
        )

    def list_claims(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims", headers=headers, params=params
        )

    def request_info(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/request-info", payload, headers
        )

    def resubmit_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/resubmit", payload, headers
        )

    def adjudicate_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/adjudicate", payload, headers
        )

    def fulfil_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/fulfil", payload, headers
        )

    def close_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/close", payload, headers
        )

    def list_claim_disputes(
        self, claim_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/warranty-claims/{claim_id}/capacity-disputes",
            headers=headers,
            params=params,
        )

    # ────────────────────────── thermal events ──────────────────────────

    def create_thermal_event(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/thermal-events", payload, headers)

    def get_thermal_event(self, event_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/thermal-events/{event_id}", headers=headers
        )

    def list_thermal_events(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/thermal-events", headers=headers, params=params
        )

    def containment_step(self, event_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/thermal-events/{event_id}/containment-step",
            payload,
            headers,
        )

    def file_regulatory_notification(self, event_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/thermal-events/{event_id}/regulatory-notification",
            payload,
            headers,
        )

    # ──────────────────────── remediation campaigns ────────────────────────

    def create_campaign(self, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/remediation-campaigns", payload, headers
        )

    def get_campaign(self, campaign_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/remediation-campaigns/{campaign_id}", headers=headers
        )

    def list_campaigns(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/remediation-campaigns", headers=headers, params=params
        )

    def release_campaign(self, campaign_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/remediation-campaigns/{campaign_id}/release",
            payload,
            headers,
        )

    # ───────────────────────── remediation consents ─────────────────────────

    def create_consent(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/remediation-consents", payload, headers)

    def get_consent(self, consent_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/remediation-consents/{consent_id}", headers=headers
        )

    def list_consents(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/remediation-consents", headers=headers, params=params
        )

    def decide_consent(self, consent_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/remediation-consents/{consent_id}/decision",
            payload,
            headers,
        )

    def apply_update(self, consent_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/remediation-consents/{consent_id}/apply-update",
            payload,
            headers,
        )

    # ────────────────────────── capacity disputes ──────────────────────────

    def create_dispute(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/capacity-disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/capacity-disputes/{dispute_id}", headers=headers
        )

    def record_lab_result(self, dispute_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/capacity-disputes/{dispute_id}/lab-result",
            payload,
            headers,
        )

    def resolve_dispute(self, dispute_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/capacity-disputes/{dispute_id}/resolve", payload, headers
        )

    # ─────────────────────────── pack shipments ───────────────────────────

    def create_shipment(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/pack-shipments", payload, headers)

    def get_shipment(self, shipment_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/pack-shipments/{shipment_id}", headers=headers
        )

    def list_shipments(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/pack-shipments", headers=headers, params=params
        )

    def tender_shipment(self, shipment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/pack-shipments/{shipment_id}/tender", payload, headers
        )

    def receive_shipment(self, shipment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/pack-shipments/{shipment_id}/receive", payload, headers
        )


# Module-level singleton, exported through the barrel.
api_client = ApiClient()
