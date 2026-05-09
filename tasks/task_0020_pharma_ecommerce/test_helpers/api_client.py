"""API client: one method per endpoint defined in the PRD.

The API is mounted under `/pharma-platforms` per PRD §2 and §4.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- PharmaPlatform ---
    def create_platform(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/pharma-platforms", payload, headers)

    def get_platform(self, pid: str, headers: Dict[str, str]):
        return self._request("GET", f"/pharma-platforms/{pid}", headers=headers)

    def advance_clock(self, pid: str, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/_clock/advance",
            {"to_iso": to_iso},
            headers,
        )

    # --- Drug ---
    def create_drug(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pharma-platforms/{pid}/drugs", payload, headers)

    def list_drugs(self, pid: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/pharma-platforms/{pid}/drugs", headers=headers, params=params)

    def get_drug(self, pid: str, drug_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pharma-platforms/{pid}/drugs/{drug_id}", headers=headers)

    def shelve_drug(self, pid: str, drug_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/pharma-platforms/{pid}/drugs/{drug_id}/shelve", payload or {}, headers)

    def off_shelve_drug(self, pid: str, drug_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/pharma-platforms/{pid}/drugs/{drug_id}/off-shelve", payload or {}, headers)

    # --- Vendor ---
    def create_vendor(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pharma-platforms/{pid}/vendors", payload, headers)

    def list_vendors(self, pid: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/pharma-platforms/{pid}/vendors", headers=headers, params=params)

    def get_vendor(self, pid: str, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pharma-platforms/{pid}/vendors/{vendor_id}", headers=headers)

    def resubmit_vendor_qualification(self, pid: str, vendor_id: str,
                                       payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/vendors/{vendor_id}/resubmit-qualification",
            payload,
            headers,
        )

    # --- Pharmacist ---
    def create_pharmacist(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pharma-platforms/{pid}/pharmacists", payload, headers)

    def list_pharmacists(self, pid: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/pharma-platforms/{pid}/pharmacists", headers=headers, params=params)

    def get_pharmacist(self, pid: str, pharmacist_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pharma-platforms/{pid}/pharmacists/{pharmacist_id}", headers=headers)

    def renew_certificate(self, pid: str, pharmacist_id: str,
                           payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/pharmacists/{pharmacist_id}/renew-certificate",
            payload,
            headers,
        )

    def suspend_pharmacist(self, pid: str, pharmacist_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/pharmacists/{pharmacist_id}/suspend",
            payload or {},
            headers,
        )

    # --- Customer ---
    def create_customer(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pharma-platforms/{pid}/customers", payload, headers)

    def get_customer(self, pid: str, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pharma-platforms/{pid}/customers/{customer_id}", headers=headers)

    def patch_customer(self, pid: str, customer_id: str,
                        payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/pharma-platforms/{pid}/customers/{customer_id}",
            payload,
            headers,
        )

    # --- Prescriber denylist ---
    def add_prescriber_to_denylist(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/prescriber-denylist",
            payload,
            headers,
        )

    def list_prescriber_denylist(self, pid: str, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/pharma-platforms/{pid}/prescriber-denylist",
            headers=headers,
            params=params,
        )

    # --- Purchase limit rules ---
    def create_purchase_limit_rule(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/purchase-limit-rules",
            payload,
            headers,
        )

    def list_purchase_limit_rules(self, pid: str, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/pharma-platforms/{pid}/purchase-limit-rules",
            headers=headers,
            params=params,
        )

    def delete_purchase_limit_rule(self, pid: str, rule_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/pharma-platforms/{pid}/purchase-limit-rules/{rule_id}",
            headers=headers,
        )

    # --- Prescription ---
    def create_prescription(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pharma-platforms/{pid}/prescriptions", payload, headers)

    def get_prescription(self, pid: str, rx_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pharma-platforms/{pid}/prescriptions/{rx_id}", headers=headers)

    def approve_prescription(self, pid: str, rx_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/prescriptions/{rx_id}/approve",
            payload or {},
            headers,
        )

    def reject_prescription(self, pid: str, rx_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/prescriptions/{rx_id}/reject",
            payload or {},
            headers,
        )

    def revoke_prescription(self, pid: str, rx_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/prescriptions/{rx_id}/revoke",
            payload or {},
            headers,
        )

    # --- Order ---
    def create_order(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pharma-platforms/{pid}/orders", payload, headers)

    def get_order(self, pid: str, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pharma-platforms/{pid}/orders/{order_id}", headers=headers)

    def list_orders(self, pid: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/pharma-platforms/{pid}/orders", headers=headers, params=params)

    def pay_order(self, pid: str, order_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/pay",
            payload or {},
            headers,
        )

    def cancel_order(self, pid: str, order_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/cancel",
            payload or {},
            headers,
        )

    def open_pharmacist_review(self, pid: str, order_id: str,
                                 payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/open-pharmacist-review",
            payload,
            headers,
        )

    def dispense_order(self, pid: str, order_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/dispense",
            payload or {},
            headers,
        )

    def ship_order(self, pid: str, order_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/ship",
            payload or {},
            headers,
        )

    def deliver_order(self, pid: str, order_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/deliver",
            payload or {},
            headers,
        )

    # --- Pharmacist Reviews ---
    def get_pharmacist_review(self, pid: str, order_id: str, review_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/pharma-platforms/{pid}/orders/{order_id}/pharmacist-reviews/{review_id}",
            headers=headers,
        )

    def approve_pharmacist_review(self, pid: str, order_id: str, review_id: str,
                                    payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/pharmacist-reviews/{review_id}/approve",
            payload,
            headers,
        )

    def reject_pharmacist_review(self, pid: str, order_id: str, review_id: str,
                                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/pharmacist-reviews/{review_id}/reject",
            payload,
            headers,
        )

    def request_change_pharmacist_review(self, pid: str, order_id: str, review_id: str,
                                           payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/pharmacist-reviews/{review_id}/request-change",
            payload,
            headers,
        )

    def resume_pharmacist_review(self, pid: str, order_id: str, review_id: str,
                                   headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/orders/{order_id}/pharmacist-reviews/{review_id}/resume",
            payload or {},
            headers,
        )

    # --- Cold Chain Shipments ---
    def create_cold_chain_shipment(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/cold-chain-shipments",
            payload,
            headers,
        )

    def get_cold_chain_shipment(self, pid: str, shipment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/pharma-platforms/{pid}/cold-chain-shipments/{shipment_id}",
            headers=headers,
        )

    def append_cold_chain_reading(self, pid: str, shipment_id: str,
                                    payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/cold-chain-shipments/{shipment_id}/readings",
            payload,
            headers,
        )

    def mark_cold_chain_in_transit(self, pid: str, shipment_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/cold-chain-shipments/{shipment_id}/mark-in-transit",
            payload or {},
            headers,
        )

    def dispose_cold_chain_shipment(self, pid: str, shipment_id: str,
                                      headers: Dict[str, str],
                                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/cold-chain-shipments/{shipment_id}/dispose",
            payload or {},
            headers,
        )

    # --- Adverse Reaction Reports ---
    def create_adr(self, pid: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/adverse-reactions",
            payload,
            headers,
        )

    def escalate_adr(self, pid: str, report_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/adverse-reactions/{report_id}/escalate",
            payload or {},
            headers,
        )

    def submit_adr(self, pid: str, report_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/adverse-reactions/{report_id}/submit",
            payload or {},
            headers,
        )

    def acknowledge_adr(self, pid: str, report_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/adverse-reactions/{report_id}/acknowledge",
            payload or {},
            headers,
        )

    def archive_adr(self, pid: str, report_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/pharma-platforms/{pid}/adverse-reactions/{report_id}/archive",
            payload or {},
            headers,
        )

    def get_adr(self, pid: str, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/pharma-platforms/{pid}/adverse-reactions/{report_id}",
            headers=headers,
        )

    def list_adrs(self, pid: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/pharma-platforms/{pid}/adverse-reactions",
            headers=headers,
            params=params,
        )

    # --- Audit logs / external events ---
    def list_audit_logs(self, pid: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/pharma-platforms/{pid}/audit-logs",
            headers=headers,
            params=params,
        )

    def list_external_events(self, pid: str, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/pharma-platforms/{pid}/external-events",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
