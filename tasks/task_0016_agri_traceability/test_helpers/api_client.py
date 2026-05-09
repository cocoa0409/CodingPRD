"""API client for the Agri-Traceability API: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------- PesticideRegistry ----------------------
    def create_registry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/pesticide-registry", payload, headers)

    def list_registry(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/pesticide-registry", headers=headers, params=params)

    def prohibit_registry(self, registration_no: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/pesticide-registry/{registration_no}/prohibit",
            payload,
            headers,
        )

    # ---------------------- PlantingBatch ----------------------
    def create_planting_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/planting-batches", payload, headers)

    def list_planting_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/planting-batches", headers=headers, params=params)

    def get_planting_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/planting-batches/{batch_id}", headers=headers)

    def declare_growing(self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/planting-batches/{batch_id}/declare-growing", payload or {}, headers)

    # ---------------------- AgrochemicalApplication ----------------------
    def create_agrochemical_application(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/planting-batches/{batch_id}/agrochemical-applications", payload, headers
        )

    def list_agrochemical_applications(self, batch_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/planting-batches/{batch_id}/agrochemical-applications", headers=headers, params=params
        )

    # ---------------------- HarvestRecord ----------------------
    def create_harvest_record(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/planting-batches/{batch_id}/harvest-records", payload, headers)

    def list_harvest_records(self, batch_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/planting-batches/{batch_id}/harvest-records", headers=headers, params=params
        )

    # ---------------------- StorageBin ----------------------
    def create_storage_bin(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/storage-bins", payload, headers)

    def get_storage_bin(self, bin_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/storage-bins/{bin_id}", headers=headers)

    # ---------------------- LogisticsLeg ----------------------
    def create_logistics_leg(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/planting-batches/{batch_id}/logistics-legs", payload, headers)

    def list_logistics_legs(self, batch_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/planting-batches/{batch_id}/logistics-legs", headers=headers, params=params
        )

    def depart_leg(self, leg_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/logistics-legs/{leg_id}/depart", payload or {}, headers)

    def acknowledge_leg(self, leg_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/logistics-legs/{leg_id}/acknowledge", payload or {}, headers)

    # ---------------------- SensorReading ----------------------
    def create_sensor_reading(self, leg_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/logistics-legs/{leg_id}/sensor-readings", payload, headers)

    def list_sensor_readings(self, leg_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/logistics-legs/{leg_id}/sensor-readings", headers=headers, params=params)

    # ---------------------- InspectionReport ----------------------
    def create_inspection_report(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/planting-batches/{batch_id}/inspection-reports", payload, headers
        )

    def issue_inspection(self, report_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/inspection-reports/{report_id}/issue", payload or {}, headers)

    def revoke_inspection(self, report_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/inspection-reports/{report_id}/revoke", payload or {}, headers)

    # ---------------------- QRCode ----------------------
    def mint_qr_code(self, harvest_record_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/harvest-records/{harvest_record_id}/qr-code", payload or {}, headers)

    def trace_qr(self, qr_code_value: str, payload: Dict[str, Any], headers: Dict[str, str]):
        # PRD §3.7: trace endpoint takes anti_counterfeit_token in the request body.
        return self._request("GET", f"/qr-codes/{qr_code_value}/trace", payload, headers)

    # ---------------------- Distributor ----------------------
    def create_distributor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/distributors", payload, headers)

    def list_distributors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/distributors", headers=headers, params=params)

    # ---------------------- RecallOrder ----------------------
    def create_recall(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/recall-orders", payload, headers)

    def get_recall(self, recall_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/recall-orders/{recall_id}", headers=headers)

    def notify_recall(self, recall_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/recall-orders/{recall_id}/notify", payload or {}, headers)

    def create_disposal(self, recall_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/recall-orders/{recall_id}/disposals", payload, headers)

    def complete_recall(self, recall_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/recall-orders/{recall_id}/complete", payload or {}, headers)

    def cancel_recall(self, recall_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/recall-orders/{recall_id}/cancel", payload or {}, headers)

    # ---------------------- AuditLog ----------------------
    def list_audit_logs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    # ---------------------- Test-only utilities ----------------------
    def advance_clock(self, to: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"to": to}, headers)

    def emit_event(self, event_type: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", {"event_type": event_type, "payload": payload}, headers)


api_client = ApiClient()
