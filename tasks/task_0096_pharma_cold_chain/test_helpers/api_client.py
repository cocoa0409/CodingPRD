"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient. Tests pass headers explicitly because PRD
§2.1 requires X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Warehouses (PRD §3.1)
    # =======================================================================
    def create_warehouse(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/warehouses", payload, headers)

    def list_warehouses(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/warehouses", headers=headers, params=params,
        )

    def get_warehouse(self, warehouse_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}", headers=headers,
        )

    # =======================================================================
    # Zones (PRD §3.1)
    # =======================================================================
    def create_zone(self, warehouse_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/zones", payload, headers,
        )

    def list_zones(self, warehouse_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/zones",
            headers=headers, params=params,
        )

    def get_zone(self, zone_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    # =======================================================================
    # Bins (PRD §3.1)
    # =======================================================================
    def create_bin(self, zone_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/zones/{zone_id}/bins", payload, headers,
        )

    def list_bins(self, zone_id: str, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/zones/{zone_id}/bins",
            headers=headers, params=params,
        )

    # =======================================================================
    # Suppliers (PRD §3.1)
    # =======================================================================
    def create_supplier(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/suppliers/{supplier_id}", headers=headers,
        )

    # =======================================================================
    # Products (PRD §3.1)
    # =======================================================================
    def create_product(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/products/{product_id}", headers=headers,
        )

    # =======================================================================
    # Inbound receipts (PRD §3.2)
    # =======================================================================
    def create_receipt(self, warehouse_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/receipts", payload, headers,
        )

    def list_receipts(self, warehouse_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/receipts",
            headers=headers, params=params,
        )

    def get_receipt(self, receipt_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/receipts/{receipt_id}", headers=headers,
        )

    def inspect_receipt(self, receipt_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/receipts/{receipt_id}/inspect",
            payload if payload is not None else {}, headers,
        )

    def accept_receipt(self, receipt_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/receipts/{receipt_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def quarantine_receipt(self, receipt_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/receipts/{receipt_id}/quarantine",
            payload if payload is not None else {}, headers,
        )

    def release_receipt_from_quarantine(self, receipt_id: str,
                                        headers: Dict[str, str],
                                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/receipts/{receipt_id}/release-from-quarantine",
            payload if payload is not None else {}, headers,
        )

    def reject_receipt(self, receipt_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/receipts/{receipt_id}/reject",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Lots (PRD §3.2)
    # =======================================================================
    def list_lots(self, warehouse_id: str, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/lots",
            headers=headers, params=params,
        )

    def get_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    # =======================================================================
    # Outbound shipments (PRD §3.5)
    # =======================================================================
    def create_shipment(self, warehouse_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/shipments", payload, headers,
        )

    def list_shipments(self, warehouse_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/shipments",
            headers=headers, params=params,
        )

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/shipments/{shipment_id}", headers=headers,
        )

    def get_shipment_summary(self, shipment_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/shipments/{shipment_id}/summary", headers=headers,
        )

    def pick_shipment(self, shipment_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/pick",
            payload if payload is not None else {}, headers,
        )

    def pack_shipment(self, shipment_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/pack",
            payload if payload is not None else {}, headers,
        )

    def dispatch_shipment(self, shipment_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/dispatch",
            payload if payload is not None else {}, headers,
        )

    def qa_release_shipment(self, shipment_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/qa-release",
            payload if payload is not None else {}, headers,
        )

    def cancel_shipment(self, shipment_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Temperature monitoring (PRD §3.3)
    # =======================================================================
    def record_temperature_event(self, zone_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/zones/{zone_id}/temperature-events", payload, headers,
        )

    def list_temperature_events(self, zone_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/zones/{zone_id}/temperature-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Deviations (PRD §3.3)
    # =======================================================================
    def list_deviations(self, warehouse_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/deviations",
            headers=headers, params=params,
        )

    def get_deviation(self, deviation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/deviations/{deviation_id}", headers=headers,
        )

    def assess_deviation(self, deviation_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/deviations/{deviation_id}/assess", payload, headers,
        )

    # =======================================================================
    # CAPAs (PRD §3.3)
    # =======================================================================
    def list_capas(self, warehouse_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/capas",
            headers=headers, params=params,
        )

    def get_capa(self, capa_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/capas/{capa_id}", headers=headers)

    def complete_capa(self, capa_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/capas/{capa_id}/complete",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Recalls (PRD §3.7)
    # =======================================================================
    def create_recall(self, warehouse_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/recalls", payload, headers,
        )

    def add_recall_scope(self, recall_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/recalls/{recall_id}/scope", payload, headers,
        )

    def announce_recall(self, recall_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/recalls/{recall_id}/announce",
            payload if payload is not None else {}, headers,
        )

    def notify_next_customer(self, recall_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/recalls/{recall_id}/notify-next-customer",
            payload if payload is not None else {}, headers,
        )

    def record_recall_return(self, recall_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/recalls/{recall_id}/record-return", payload, headers,
        )

    def close_recall(self, recall_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/recalls/{recall_id}/close",
            payload if payload is not None else {}, headers,
        )

    def get_recall(self, recall_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/recalls/{recall_id}", headers=headers,
        )

    def get_recall_preview(self, recall_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/recalls/{recall_id}/preview", headers=headers,
        )

    def list_recalls(self, warehouse_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/recalls",
            headers=headers, params=params,
        )

    # =======================================================================
    # External sync events (PRD §3.8)
    # =======================================================================
    def list_external_events(self, warehouse_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/external-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit log (PRD §3.8)
    # =======================================================================
    def list_audit_log(self, warehouse_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/audit-log",
            headers=headers, params=params,
        )

    # =======================================================================
    # Deterministic clock + sweep (PRD §2.7)
    # =======================================================================
    def clock_advance(self, warehouse_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/_clock/advance",
            payload, headers,
        )

    def sweep_run(self, warehouse_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/_sweep/run",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
