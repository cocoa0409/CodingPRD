"""HTTP client exposing one method per endpoint of the lead service line API."""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _query(**kwargs: Any) -> Dict[str, Any]:
    """Drop unset query parameters so defaults stay server side."""
    return {key: value for key, value in kwargs.items() if value is not None}


class ApiClient(GenericApiClient):
    """One method per endpoint; every method returns the raw response."""

    # ------------------------------------------------------------------
    # low level helpers
    # ------------------------------------------------------------------

    def patch(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("PATCH", path, payload=json, headers=headers)

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        """POST /lsl/_clock/set_current_utc"""
        return self.post(
            f"{API_PREFIX}/_clock/set_current_utc",
            json={"to_iso8601": to_iso8601},
            headers=headers,
        )

    def set_clock_raw(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/_clock/set_current_utc with a caller supplied body."""
        return self.post(
            f"{API_PREFIX}/_clock/set_current_utc", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # water systems
    # ------------------------------------------------------------------

    def create_water_system(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/water-systems"""
        return self.post(f"{API_PREFIX}/water-systems", json=payload, headers=headers)

    def list_water_systems(
        self,
        headers: Dict[str, str],
        inventory_status: Optional[str] = None,
        program_posture: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/water-systems"""
        return self.get(
            f"{API_PREFIX}/water-systems",
            headers=headers,
            params=params
            if params is not None
            else _query(
                inventory_status=inventory_status,
                program_posture=program_posture,
                limit=limit,
                offset=offset,
            ),
        )

    def get_water_system(
        self, water_system_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/water-systems/{id}"""
        return self.get(
            f"{API_PREFIX}/water-systems/{water_system_id}", headers=headers
        )

    def advance_inventory_status(
        self, water_system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/water-systems/{id}/advance-inventory-status"""
        return self.post(
            f"{API_PREFIX}/water-systems/{water_system_id}/advance-inventory-status",
            json=payload,
            headers=headers,
        )

    def patch_funding_policy(
        self, water_system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /lsl/water-systems/{id}/funding-policy"""
        return self.patch(
            f"{API_PREFIX}/water-systems/{water_system_id}/funding-policy",
            json=payload,
            headers=headers,
        )

    def patch_corrosion_control(
        self, water_system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /lsl/water-systems/{id}/corrosion-control"""
        return self.patch(
            f"{API_PREFIX}/water-systems/{water_system_id}/corrosion-control",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # service lines
    # ------------------------------------------------------------------

    def create_service_line(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/service-lines"""
        return self.post(f"{API_PREFIX}/service-lines", json=payload, headers=headers)

    def list_service_lines(
        self,
        headers: Dict[str, str],
        water_system_id: Optional[str] = None,
        street_project_id: Optional[str] = None,
        classification: Optional[str] = None,
        inventory_state: Optional[str] = None,
        replacement_state: Optional[str] = None,
        disadvantaged_status: Optional[Any] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/service-lines"""
        return self.get(
            f"{API_PREFIX}/service-lines",
            headers=headers,
            params=params
            if params is not None
            else _query(
                water_system_id=water_system_id,
                street_project_id=street_project_id,
                classification=classification,
                inventory_state=inventory_state,
                replacement_state=replacement_state,
                disadvantaged_status=disadvantaged_status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_service_line(
        self, service_line_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/service-lines/{id}"""
        return self.get(f"{API_PREFIX}/service-lines/{service_line_id}", headers=headers)

    def create_classification_override(
        self, service_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/service-lines/{id}/classification-overrides"""
        return self.post(
            f"{API_PREFIX}/service-lines/{service_line_id}/classification-overrides",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # evidence items
    # ------------------------------------------------------------------

    def create_evidence_item(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/evidence-items"""
        return self.post(f"{API_PREFIX}/evidence-items", json=payload, headers=headers)

    def list_evidence_items(
        self,
        headers: Dict[str, str],
        service_line_id: Optional[str] = None,
        source_type: Optional[str] = None,
        side: Optional[str] = None,
        retracted: Optional[Any] = None,
        origin: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/evidence-items"""
        return self.get(
            f"{API_PREFIX}/evidence-items",
            headers=headers,
            params=params
            if params is not None
            else _query(
                service_line_id=service_line_id,
                source_type=source_type,
                side=side,
                retracted=retracted,
                origin=origin,
                limit=limit,
                offset=offset,
            ),
        )

    def get_evidence_item(
        self, evidence_item_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/evidence-items/{id}"""
        return self.get(
            f"{API_PREFIX}/evidence-items/{evidence_item_id}", headers=headers
        )

    def retract_evidence_item(
        self, evidence_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/evidence-items/{id}/retract"""
        return self.post(
            f"{API_PREFIX}/evidence-items/{evidence_item_id}/retract",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # verification crews
    # ------------------------------------------------------------------

    def create_verification_crew(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/verification-crews"""
        return self.post(
            f"{API_PREFIX}/verification-crews", json=payload, headers=headers
        )

    def list_verification_crews(
        self,
        headers: Dict[str, str],
        water_system_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/verification-crews"""
        return self.get(
            f"{API_PREFIX}/verification-crews",
            headers=headers,
            params=params
            if params is not None
            else _query(
                water_system_id=water_system_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_verification_crew(
        self, crew_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/verification-crews/{id}"""
        return self.get(f"{API_PREFIX}/verification-crews/{crew_id}", headers=headers)

    def set_crew_status(
        self, crew_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/verification-crews/{id}/status"""
        return self.post(
            f"{API_PREFIX}/verification-crews/{crew_id}/status",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # verification appointments
    # ------------------------------------------------------------------

    def create_verification_appointment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/verification-appointments"""
        return self.post(
            f"{API_PREFIX}/verification-appointments", json=payload, headers=headers
        )

    def list_verification_appointments(
        self,
        headers: Dict[str, str],
        crew_id: Optional[str] = None,
        service_line_id: Optional[str] = None,
        state: Optional[str] = None,
        method: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/verification-appointments"""
        return self.get(
            f"{API_PREFIX}/verification-appointments",
            headers=headers,
            params=params
            if params is not None
            else _query(
                crew_id=crew_id,
                service_line_id=service_line_id,
                state=state,
                method=method,
                limit=limit,
                offset=offset,
            ),
        )

    def get_verification_appointment(
        self, appointment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/verification-appointments/{id}"""
        return self.get(
            f"{API_PREFIX}/verification-appointments/{appointment_id}", headers=headers
        )

    def arrive_appointment(
        self, appointment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/verification-appointments/{id}/arrive"""
        return self.post(
            f"{API_PREFIX}/verification-appointments/{appointment_id}/arrive",
            json={},
            headers=headers,
        )

    def complete_appointment(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/verification-appointments/{id}/complete"""
        return self.post(
            f"{API_PREFIX}/verification-appointments/{appointment_id}/complete",
            json=payload,
            headers=headers,
        )

    def no_access_appointment(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/verification-appointments/{id}/no-access"""
        return self.post(
            f"{API_PREFIX}/verification-appointments/{appointment_id}/no-access",
            json=payload,
            headers=headers,
        )

    def reschedule_appointment(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/verification-appointments/{id}/reschedule"""
        return self.post(
            f"{API_PREFIX}/verification-appointments/{appointment_id}/reschedule",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # sampling batches
    # ------------------------------------------------------------------

    def create_sampling_batch(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/sampling-batches"""
        return self.post(f"{API_PREFIX}/sampling-batches", json=payload, headers=headers)

    def list_sampling_batches(
        self,
        headers: Dict[str, str],
        water_system_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/sampling-batches"""
        return self.get(
            f"{API_PREFIX}/sampling-batches",
            headers=headers,
            params=params
            if params is not None
            else _query(
                water_system_id=water_system_id,
                state=state,
                limit=limit,
                offset=offset,
            ),
        )

    def get_sampling_batch(
        self, batch_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/sampling-batches/{id}"""
        return self.get(f"{API_PREFIX}/sampling-batches/{batch_id}", headers=headers)

    def append_sample(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/sampling-batches/{id}/samples"""
        return self.post(
            f"{API_PREFIX}/sampling-batches/{batch_id}/samples",
            json=payload,
            headers=headers,
        )

    def invalidate_sample(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/sampling-batches/{id}/invalidate-sample"""
        return self.post(
            f"{API_PREFIX}/sampling-batches/{batch_id}/invalidate-sample",
            json=payload,
            headers=headers,
        )

    def validate_sampling_batch(
        self, batch_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/sampling-batches/{id}/validate"""
        return self.post(
            f"{API_PREFIX}/sampling-batches/{batch_id}/validate",
            json={},
            headers=headers,
        )

    def reopen_sampling_batch(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/sampling-batches/{id}/reopen"""
        return self.post(
            f"{API_PREFIX}/sampling-batches/{batch_id}/reopen",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # inventory publications
    # ------------------------------------------------------------------

    def create_inventory_publication(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/inventory-publications"""
        return self.post(
            f"{API_PREFIX}/inventory-publications", json=payload, headers=headers
        )

    def list_inventory_publications(
        self,
        headers: Dict[str, str],
        water_system_id: Optional[str] = None,
        state: Optional[str] = None,
        basis: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/inventory-publications"""
        return self.get(
            f"{API_PREFIX}/inventory-publications",
            headers=headers,
            params=params
            if params is not None
            else _query(
                water_system_id=water_system_id,
                state=state,
                basis=basis,
                limit=limit,
                offset=offset,
            ),
        )

    def get_inventory_publication(
        self, publication_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/inventory-publications/{id}"""
        return self.get(
            f"{API_PREFIX}/inventory-publications/{publication_id}", headers=headers
        )

    def certify_publication(
        self, publication_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/inventory-publications/{id}/certify"""
        return self.post(
            f"{API_PREFIX}/inventory-publications/{publication_id}/certify",
            json={},
            headers=headers,
        )

    def publish_publication(
        self, publication_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/inventory-publications/{id}/publish"""
        return self.post(
            f"{API_PREFIX}/inventory-publications/{publication_id}/publish",
            json={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # customer notifications
    # ------------------------------------------------------------------

    def list_customer_notifications(
        self,
        headers: Dict[str, str],
        service_line_id: Optional[str] = None,
        inventory_publication_id: Optional[str] = None,
        state: Optional[str] = None,
        overdue: Optional[Any] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/customer-notifications"""
        return self.get(
            f"{API_PREFIX}/customer-notifications",
            headers=headers,
            params=params
            if params is not None
            else _query(
                service_line_id=service_line_id,
                inventory_publication_id=inventory_publication_id,
                state=state,
                overdue=overdue,
                limit=limit,
                offset=offset,
            ),
        )

    def get_customer_notification(
        self, notification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/customer-notifications/{id}"""
        return self.get(
            f"{API_PREFIX}/customer-notifications/{notification_id}", headers=headers
        )

    def deliver_notification(
        self, notification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/customer-notifications/{id}/deliver"""
        return self.post(
            f"{API_PREFIX}/customer-notifications/{notification_id}/deliver",
            json=payload,
            headers=headers,
        )

    def acknowledge_notification(
        self, notification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/customer-notifications/{id}/acknowledge"""
        return self.post(
            f"{API_PREFIX}/customer-notifications/{notification_id}/acknowledge",
            json=payload,
            headers=headers,
        )

    def return_notification(
        self, notification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/customer-notifications/{id}/return"""
        return self.post(
            f"{API_PREFIX}/customer-notifications/{notification_id}/return",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # replacement orders
    # ------------------------------------------------------------------

    def create_replacement_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/replacement-orders"""
        return self.post(
            f"{API_PREFIX}/replacement-orders", json=payload, headers=headers
        )

    def list_replacement_orders(
        self,
        headers: Dict[str, str],
        service_line_id: Optional[str] = None,
        street_project_id: Optional[str] = None,
        fulfillment_state: Optional[str] = None,
        consent_state: Optional[str] = None,
        scope: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/replacement-orders"""
        return self.get(
            f"{API_PREFIX}/replacement-orders",
            headers=headers,
            params=params
            if params is not None
            else _query(
                service_line_id=service_line_id,
                street_project_id=street_project_id,
                fulfillment_state=fulfillment_state,
                consent_state=consent_state,
                scope=scope,
                limit=limit,
                offset=offset,
            ),
        )

    def get_replacement_order(
        self, order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/replacement-orders/{id}"""
        return self.get(f"{API_PREFIX}/replacement-orders/{order_id}", headers=headers)

    def request_consent(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        """POST /lsl/replacement-orders/{id}/consent-request"""
        return self.post(
            f"{API_PREFIX}/replacement-orders/{order_id}/consent-request",
            json={},
            headers=headers,
        )

    def respond_consent(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/replacement-orders/{id}/consent-response"""
        return self.post(
            f"{API_PREFIX}/replacement-orders/{order_id}/consent-response",
            json=payload,
            headers=headers,
        )

    def plan_funding(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        """POST /lsl/replacement-orders/{id}/funding-plan"""
        return self.post(
            f"{API_PREFIX}/replacement-orders/{order_id}/funding-plan",
            json={},
            headers=headers,
        )

    def schedule_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/replacement-orders/{id}/schedule"""
        return self.post(
            f"{API_PREFIX}/replacement-orders/{order_id}/schedule",
            json=payload,
            headers=headers,
        )

    def start_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        """POST /lsl/replacement-orders/{id}/start"""
        return self.post(
            f"{API_PREFIX}/replacement-orders/{order_id}/start",
            json={},
            headers=headers,
        )

    def complete_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/replacement-orders/{id}/complete"""
        return self.post(
            f"{API_PREFIX}/replacement-orders/{order_id}/complete",
            json=payload,
            headers=headers,
        )

    def cancel_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/replacement-orders/{id}/cancel"""
        return self.post(
            f"{API_PREFIX}/replacement-orders/{order_id}/cancel",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # street projects
    # ------------------------------------------------------------------

    def create_street_project(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/street-projects"""
        return self.post(f"{API_PREFIX}/street-projects", json=payload, headers=headers)

    def list_street_projects(
        self,
        headers: Dict[str, str],
        water_system_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/street-projects"""
        return self.get(
            f"{API_PREFIX}/street-projects",
            headers=headers,
            params=params
            if params is not None
            else _query(water_system_id=water_system_id, limit=limit, offset=offset),
        )

    def get_street_project(
        self, street_project_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/street-projects/{id}"""
        return self.get(
            f"{API_PREFIX}/street-projects/{street_project_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # funding sources
    # ------------------------------------------------------------------

    def create_funding_source(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/funding-sources"""
        return self.post(f"{API_PREFIX}/funding-sources", json=payload, headers=headers)

    def list_funding_sources(
        self,
        headers: Dict[str, str],
        water_system_id: Optional[str] = None,
        source_kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/funding-sources"""
        return self.get(
            f"{API_PREFIX}/funding-sources",
            headers=headers,
            params=params
            if params is not None
            else _query(
                water_system_id=water_system_id,
                source_kind=source_kind,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_funding_source(
        self, funding_source_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/funding-sources/{id}"""
        return self.get(
            f"{API_PREFIX}/funding-sources/{funding_source_id}", headers=headers
        )

    def set_funding_source_status(
        self, funding_source_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/funding-sources/{id}/status"""
        return self.post(
            f"{API_PREFIX}/funding-sources/{funding_source_id}/status",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # progress reports
    # ------------------------------------------------------------------

    def create_progress_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /lsl/progress-reports"""
        return self.post(f"{API_PREFIX}/progress-reports", json=payload, headers=headers)

    def list_progress_reports(
        self,
        headers: Dict[str, str],
        water_system_id: Optional[str] = None,
        compliance_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /lsl/progress-reports"""
        return self.get(
            f"{API_PREFIX}/progress-reports",
            headers=headers,
            params=params
            if params is not None
            else _query(
                water_system_id=water_system_id,
                compliance_status=compliance_status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_progress_report(
        self, progress_report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /lsl/progress-reports/{id}"""
        return self.get(
            f"{API_PREFIX}/progress-reports/{progress_report_id}", headers=headers
        )
