"""Endpoint client for the Club Demo Sampling API — one method per PRD section 4 row."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, typed wrapper over the 55 declared endpoints."""

    # ------------------------------------------------------------------
    # Manufacturer
    # ------------------------------------------------------------------
    def create_manufacturer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/manufacturers/{manufacturer_id}", None, headers)

    def update_manufacturer(
        self, manufacturer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/manufacturers/{manufacturer_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Club
    # ------------------------------------------------------------------
    def create_club(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/clubs", payload, headers)

    def get_club(self, club_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/clubs/{club_id}", None, headers)

    def update_club(self, club_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/clubs/{club_id}", payload, headers)

    def get_club_capacity(
        self,
        club_id: str,
        headers: Dict[str, str],
        event_date: str,
        product_id: Optional[str] = None,
    ):
        params: Dict[str, Any] = {"event_date": event_date}
        if product_id is not None:
            params["product_id"] = product_id
        return self._request("GET", f"/clubs/{club_id}/capacity", params, headers)

    # ------------------------------------------------------------------
    # Product
    # ------------------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/products/{product_id}", None, headers)

    def list_products(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/products", params or {}, headers)

    # ------------------------------------------------------------------
    # ClubProductBaseline
    # ------------------------------------------------------------------
    def create_baseline(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/club-product-baselines", payload, headers)

    def get_baseline(self, baseline_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/club-product-baselines/{baseline_id}", None, headers
        )

    def list_baselines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/club-product-baselines", params or {}, headers)

    def update_baseline(
        self, baseline_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/club-product-baselines/{baseline_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Demonstrator + certifications
    # ------------------------------------------------------------------
    def create_demonstrator(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/demonstrators", payload, headers)

    def get_demonstrator(self, demonstrator_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/demonstrators/{demonstrator_id}", None, headers)

    def list_demonstrators(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/demonstrators", params or {}, headers)

    def update_demonstrator(
        self, demonstrator_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/demonstrators/{demonstrator_id}", payload, headers
        )

    def create_certification(
        self, demonstrator_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/demonstrators/{demonstrator_id}/certifications", payload, headers
        )

    def list_certifications(
        self,
        demonstrator_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/demonstrators/{demonstrator_id}/certifications",
            params or {},
            headers,
        )

    def revoke_certification(
        self,
        demonstrator_id: str,
        certification_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/demonstrators/{demonstrator_id}/certifications/{certification_id}/revoke",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # EquipmentUnit
    # ------------------------------------------------------------------
    def create_equipment_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/equipment-units", payload, headers)

    def get_equipment_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/equipment-units/{unit_id}", None, headers)

    def list_equipment_units(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/equipment-units", params or {}, headers)

    def update_equipment_unit(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/equipment-units/{unit_id}", payload, headers)

    # ------------------------------------------------------------------
    # DemoEvent
    # ------------------------------------------------------------------
    def create_demo_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/demo-events", payload, headers)

    def get_demo_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/demo-events/{event_id}", None, headers)

    def list_demo_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/demo-events", params or {}, headers)

    def update_demo_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/demo-events/{event_id}", payload, headers)

    def demo_event_transition(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/demo-events/{event_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # EventAssignment
    # ------------------------------------------------------------------
    def create_assignment(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/demo-events/{event_id}/assignments", payload, headers
        )

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/event-assignments/{assignment_id}", None, headers
        )

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/event-assignments", params or {}, headers)

    def assignment_transition(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/event-assignments/{assignment_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # EquipmentReservation
    # ------------------------------------------------------------------
    def create_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/equipment-reservations", payload, headers)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/equipment-reservations/{reservation_id}", None, headers
        )

    def list_reservations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/equipment-reservations", params or {}, headers)

    def reservation_transition(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/equipment-reservations/{reservation_id}/transitions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # SampleShipment
    # ------------------------------------------------------------------
    def create_shipment(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/demo-events/{event_id}/sample-shipments", payload, headers
        )

    def list_shipments(
        self, event_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/demo-events/{event_id}/sample-shipments", params or {}, headers
        )

    def receive_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sample-shipments/{shipment_id}/receive", payload, headers
        )

    # ------------------------------------------------------------------
    # SampleReconciliation
    # ------------------------------------------------------------------
    def create_reconciliation(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/demo-events/{event_id}/sample-reconciliation", payload, headers
        )

    def get_reconciliation(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/demo-events/{event_id}/sample-reconciliation", None, headers
        )

    def write_off_reconciliation(
        self, reconciliation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sample-reconciliations/{reconciliation_id}/write-off",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # SalesLiftMeasurement
    # ------------------------------------------------------------------
    def create_lift_measurement(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/demo-events/{event_id}/lift-measurements", payload, headers
        )

    def list_lift_measurements(
        self, event_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/demo-events/{event_id}/lift-measurements", params or {}, headers
        )

    # ------------------------------------------------------------------
    # EventInvoice
    # ------------------------------------------------------------------
    def create_invoice(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/demo-events/{event_id}/invoice", payload, headers
        )

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/event-invoices/{invoice_id}", None, headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/event-invoices", params or {}, headers)

    def invoice_transition(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/event-invoices/{invoice_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # CancellationCredit
    # ------------------------------------------------------------------
    def get_credit(self, credit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cancellation-credits/{credit_id}", None, headers
        )

    def list_credits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cancellation-credits", params or {}, headers)

    def decide_credit(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cancellation-credits/{credit_id}/decisions", payload, headers
        )

    # ------------------------------------------------------------------
    # Test-driving endpoints
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def inject_assignment_history(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/_inject/assignment-history", payload, headers)
