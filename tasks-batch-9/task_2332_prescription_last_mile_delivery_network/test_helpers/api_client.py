"""One typed method per documented endpoint.

Every collection is mounted at the top level; the only nested paths are the
HIPAA projection and the two disclosure audit trails.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Payload = Dict[str, Any]


def _page(limit: Optional[int], offset: Optional[int], **filters: Any) -> Dict[str, Any]:
    """Assemble a query string, dropping every parameter the caller omitted."""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    for key, value in filters.items():
        if value is not None:
            params[key] = value
    return params


class ApiClient(GenericApiClient):
    """HTTP surface of the prescription last-mile delivery network."""

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, current_utc: str, headers: Headers):
        """Set the logical clock that every temporal rule reads."""
        return self.post("/_clock/set_current_utc", json={"current_utc": current_utc}, headers=headers)

    # ─── Reference data ───────────────────────────────

    def create_health_plan(self, payload: Payload, headers: Headers):
        return self.post("/health-plans", json=payload, headers=headers)

    def create_plan_grant(self, payload: Payload, headers: Headers):
        return self.post("/plan-grants", json=payload, headers=headers)

    def get_plan_grant(self, grant_id: str, headers: Headers):
        return self.get(f"/plan-grants/{grant_id}", headers=headers)

    def list_plan_grants(
        self,
        headers: Headers,
        health_plan_id: Optional[str] = None,
        benefit_year: Optional[int] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/plan-grants",
            headers=headers,
            params=_page(limit, offset, health_plan_id=health_plan_id, benefit_year=benefit_year, status=status),
        )

    def create_pharmacy(self, payload: Payload, headers: Headers):
        return self.post("/pharmacies", json=payload, headers=headers)

    def create_delivery_zone(self, payload: Payload, headers: Headers):
        return self.post("/delivery-zones", json=payload, headers=headers)

    def create_patient(self, payload: Payload, headers: Headers):
        return self.post("/patients", json=payload, headers=headers)

    def record_patient_consent(self, patient_id: str, payload: Payload, headers: Headers):
        """Record or revoke the patient's HIPAA delivery-disclosure consent."""
        return self.post(f"/patients/{patient_id}/consent", json=payload, headers=headers)

    def create_courier(self, payload: Payload, headers: Headers):
        return self.post("/couriers", json=payload, headers=headers)

    def set_courier_status(self, courier_id: str, payload: Payload, headers: Headers):
        """Move a courier between OFFLINE, AVAILABLE and SUSPENDED."""
        return self.post(f"/couriers/{courier_id}/status", json=payload, headers=headers)

    def get_courier(self, courier_id: str, headers: Headers):
        return self.get(f"/couriers/{courier_id}", headers=headers)

    def list_courier_disclosures(
        self,
        courier_id: str,
        headers: Headers,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        """Audit trail of every PHI projection this courier has been shown."""
        return self.get(f"/couriers/{courier_id}/disclosures", headers=headers, params=_page(limit, offset))

    def create_delivery_window(self, payload: Payload, headers: Headers):
        return self.post("/delivery-windows", json=payload, headers=headers)

    def get_delivery_window(self, window_id: str, headers: Headers):
        return self.get(f"/delivery-windows/{window_id}", headers=headers)

    def list_delivery_windows(
        self,
        headers: Headers,
        zone_id: Optional[str] = None,
        courier_mode: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/delivery-windows",
            headers=headers,
            params=_page(limit, offset, zone_id=zone_id, courier_mode=courier_mode, status=status),
        )

    # ─── Orders ───────────────────────────────────────

    def create_pharmacy_order(self, payload: Payload, headers: Headers):
        return self.post("/pharmacy-orders", json=payload, headers=headers)

    def mark_order_ready(self, order_id: str, headers: Headers):
        """Release the order for delivery scheduling."""
        return self.post(f"/pharmacy-orders/{order_id}/mark-ready", json={}, headers=headers)

    def hold_order(self, order_id: str, headers: Headers, payload: Optional[Payload] = None):
        """Pull a READY order back to INTAKE for re-verification."""
        return self.post(f"/pharmacy-orders/{order_id}/hold", json=payload or {}, headers=headers)

    def get_pharmacy_order(self, order_id: str, headers: Headers):
        return self.get(f"/pharmacy-orders/{order_id}", headers=headers)

    def list_pharmacy_orders(
        self,
        headers: Headers,
        pharmacy_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        health_plan_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/pharmacy-orders",
            headers=headers,
            params=_page(
                limit,
                offset,
                pharmacy_id=pharmacy_id,
                patient_id=patient_id,
                health_plan_id=health_plan_id,
                status=status,
            ),
        )

    # ─── Deliveries ───────────────────────────────────

    def create_delivery(self, payload: Payload, headers: Headers):
        """Reserve a window slot for a READY order and price it provisionally."""
        return self.post("/deliveries", json=payload, headers=headers)

    def reschedule_delivery(self, delivery_id: str, payload: Payload, headers: Headers):
        return self.post(f"/deliveries/{delivery_id}/reschedule", json=payload, headers=headers)

    def cancel_delivery(self, delivery_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self.post(f"/deliveries/{delivery_id}/cancel", json=payload or {}, headers=headers)

    def dispatch_delivery(self, delivery_id: str, headers: Headers, payload: Optional[Payload] = None):
        """Offer the delivery to a policy-selected courier, or to a named one."""
        return self.post(f"/deliveries/{delivery_id}/dispatch", json=payload or {}, headers=headers)

    def pickup_delivery(self, delivery_id: str, headers: Headers, payload: Optional[Payload] = None):
        """Courier takes custody at the pharmacy counter."""
        return self.post(f"/deliveries/{delivery_id}/pickup", json=payload or {}, headers=headers)

    def depart_delivery(self, delivery_id: str, headers: Headers, payload: Optional[Payload] = None):
        """Courier leaves for the patient's address, first run or ladder re-attempt."""
        return self.post(f"/deliveries/{delivery_id}/depart", json=payload or {}, headers=headers)

    def record_attempt(self, delivery_id: str, payload: Payload, headers: Headers):
        """Record the outcome of one door-step run."""
        return self.post(f"/deliveries/{delivery_id}/attempts", json=payload, headers=headers)

    def confirm_return(self, delivery_id: str, headers: Headers, payload: Optional[Payload] = None):
        """Pharmacy confirms physical receipt of an undelivered bag."""
        return self.post(f"/deliveries/{delivery_id}/confirm-return", json=payload or {}, headers=headers)

    def settle_delivery(self, delivery_id: str, headers: Headers, payload: Optional[Payload] = None):
        """Finalize the money dimension with the FINAL variant."""
        return self.post(f"/deliveries/{delivery_id}/settle", json=payload or {}, headers=headers)

    def get_delivery(self, delivery_id: str, headers: Headers):
        return self.get(f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(
        self,
        headers: Headers,
        order_id: Optional[str] = None,
        window_id: Optional[str] = None,
        courier_id: Optional[str] = None,
        reship_of_delivery_id: Optional[str] = None,
        custody_status: Optional[str] = None,
        settlement_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/deliveries",
            headers=headers,
            params=_page(
                limit,
                offset,
                order_id=order_id,
                window_id=window_id,
                courier_id=courier_id,
                reship_of_delivery_id=reship_of_delivery_id,
                custody_status=custody_status,
                settlement_status=settlement_status,
            ),
        )

    def get_courier_view(self, delivery_id: str, headers: Headers, purpose: Optional[str] = None):
        """HIPAA minimum-necessary projection of a delivery for its courier."""
        params = {} if purpose is None else {"purpose": purpose}
        return self.get(f"/deliveries/{delivery_id}/courier-view", headers=headers, params=params)

    def list_delivery_disclosures(
        self,
        delivery_id: str,
        headers: Headers,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        """Audit trail of every courier shown this delivery's PHI."""
        return self.get(f"/deliveries/{delivery_id}/disclosures", headers=headers, params=_page(limit, offset))

    # ─── Courier assignments ──────────────────────────

    def accept_assignment(self, assignment_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self.post(f"/courier-assignments/{assignment_id}/accept", json=payload or {}, headers=headers)

    def decline_assignment(self, assignment_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self.post(f"/courier-assignments/{assignment_id}/decline", json=payload or {}, headers=headers)

    def revoke_assignment(self, assignment_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self.post(f"/courier-assignments/{assignment_id}/revoke", json=payload or {}, headers=headers)

    def get_courier_assignment(self, assignment_id: str, headers: Headers):
        return self.get(f"/courier-assignments/{assignment_id}", headers=headers)

    def list_courier_assignments(
        self,
        headers: Headers,
        delivery_id: Optional[str] = None,
        courier_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/courier-assignments",
            headers=headers,
            params=_page(limit, offset, delivery_id=delivery_id, courier_id=courier_id, status=status),
        )

    # ─── Attempts ─────────────────────────────────────

    def get_delivery_attempt(self, attempt_id: str, headers: Headers):
        return self.get(f"/delivery-attempts/{attempt_id}", headers=headers)

    def list_delivery_attempts(
        self,
        headers: Headers,
        delivery_id: Optional[str] = None,
        courier_id: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/delivery-attempts",
            headers=headers,
            params=_page(limit, offset, delivery_id=delivery_id, courier_id=courier_id, outcome=outcome),
        )

    # ─── Fee allocations ──────────────────────────────

    def get_fee_allocation(self, allocation_id: str, headers: Headers):
        return self.get(f"/fee-allocations/{allocation_id}", headers=headers)

    def list_fee_allocations(
        self,
        headers: Headers,
        delivery_id: Optional[str] = None,
        plan_grant_id: Optional[str] = None,
        variant: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/fee-allocations",
            headers=headers,
            params=_page(
                limit,
                offset,
                delivery_id=delivery_id,
                plan_grant_id=plan_grant_id,
                variant=variant,
                status=status,
            ),
        )

    # ─── Exception cases ──────────────────────────────

    def open_exception_case(self, payload: Payload, headers: Headers):
        return self.post("/exception-cases", json=payload, headers=headers)

    def start_exception_review(self, case_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self.post(f"/exception-cases/{case_id}/start-review", json=payload or {}, headers=headers)

    def adjudicate_exception_case(self, case_id: str, payload: Payload, headers: Headers):
        """Fork the case into a reship, a fee credit, or a denial."""
        return self.post(f"/exception-cases/{case_id}/adjudicate", json=payload, headers=headers)

    def close_exception_case(self, case_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self.post(f"/exception-cases/{case_id}/close", json=payload or {}, headers=headers)

    def get_exception_case(self, case_id: str, headers: Headers):
        return self.get(f"/exception-cases/{case_id}", headers=headers)

    def list_exception_cases(
        self,
        headers: Headers,
        delivery_id: Optional[str] = None,
        reship_delivery_id: Optional[str] = None,
        exception_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/exception-cases",
            headers=headers,
            params=_page(
                limit,
                offset,
                delivery_id=delivery_id,
                reship_delivery_id=reship_delivery_id,
                exception_type=exception_type,
                status=status,
            ),
        )

    # ─── Routing sweep ────────────────────────────────

    def run_routing_sweep(self, headers: Headers, payload: Optional[Payload] = None):
        """Expire stale offers, close elapsed windows, then offer QUEUED deliveries."""
        return self.post("/routing-runs", json=payload or {}, headers=headers)


api_client = ApiClient()
