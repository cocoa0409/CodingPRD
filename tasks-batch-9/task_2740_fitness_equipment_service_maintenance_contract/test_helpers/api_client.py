"""
FleetCare API client: exactly one method per declared endpoint.

Every method returns the raw ``requests.Response`` so tests can assert both the
status code and the envelope. Paths are written once here so no test hard-codes a
URL, and query filters are passed through as ``params`` so pagination and domain
filters behave as described by the PRD.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import BUSINESS_PREFIX, CLOCK_PATH


def _params(**kwargs) -> Optional[Dict[str, Any]]:
    """Drop unset filters so a request only carries the parameters a test named."""
    cleaned = {k: v for k, v in kwargs.items() if v is not None}
    return cleaned or None


class FleetCareClient(GenericApiClient):
    """Typed access to every FleetCare endpoint."""

    # ─── The logical service clock (all six roles) ────────────────────────────

    def set_clock(self, to_iso8601: str, headers):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ─── Clubs ────────────────────────────────────────────────────────────────

    def create_club(self, payload, headers):
        return self._request("POST", f"{BUSINESS_PREFIX}/clubs", payload, headers)

    def list_clubs(self, headers, region_code=None, limit=None, offset=None):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/clubs",
            None,
            headers,
            params=_params(region_code=region_code, limit=limit, offset=offset),
        )

    def get_club(self, club_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/clubs/{club_id}", None, headers
        )

    # ─── Equipment models ─────────────────────────────────────────────────────

    def create_equipment_model(self, payload, headers):
        return self._request(
            "POST", f"{BUSINESS_PREFIX}/equipment-models", payload, headers
        )

    def list_equipment_models(
        self, headers, category=None, manufacturer=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/equipment-models",
            None,
            headers,
            params=_params(
                category=category,
                manufacturer=manufacturer,
                limit=limit,
                offset=offset,
            ),
        )

    def get_equipment_model(self, model_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/equipment-models/{model_id}", None, headers
        )

    # ─── Equipment ────────────────────────────────────────────────────────────

    def create_equipment(self, payload, headers):
        return self._request("POST", f"{BUSINESS_PREFIX}/equipment", payload, headers)

    def list_equipment(
        self,
        headers,
        club_id=None,
        model_id=None,
        lifecycle_status=None,
        pm_status=None,
        support_status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/equipment",
            None,
            headers,
            params=_params(
                club_id=club_id,
                model_id=model_id,
                lifecycle_status=lifecycle_status,
                pm_status=pm_status,
                support_status=support_status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_equipment(self, equipment_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/equipment/{equipment_id}", None, headers
        )

    def record_usage_reading(self, equipment_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/equipment/{equipment_id}/usage-readings",
            payload,
            headers,
        )

    def tag_out_equipment(self, equipment_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/equipment/{equipment_id}/tag-out",
            payload,
            headers,
        )

    # ─── Service contracts ────────────────────────────────────────────────────

    def create_contract(self, payload, headers):
        return self._request("POST", f"{BUSINESS_PREFIX}/contracts", payload, headers)

    def list_contracts(
        self,
        headers,
        club_id=None,
        status=None,
        coverage_tier=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/contracts",
            None,
            headers,
            params=_params(
                club_id=club_id,
                status=status,
                coverage_tier=coverage_tier,
                limit=limit,
                offset=offset,
            ),
        )

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/contracts/{contract_id}", None, headers
        )

    def activate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/contracts/{contract_id}/activate",
            payload,
            headers,
        )

    def suspend_contract(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/contracts/{contract_id}/suspend",
            payload,
            headers,
        )

    def reinstate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/contracts/{contract_id}/reinstate",
            payload,
            headers,
        )

    def adjust_parts_allowance(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/contracts/{contract_id}/parts-allowance-adjustments",
            payload,
            headers,
        )

    def reconcile_credits(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/contracts/{contract_id}/credit-reconciliations",
            payload,
            headers,
        )

    def get_credit_summary(self, contract_id, headers):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/contracts/{contract_id}/credit-summary",
            None,
            headers,
        )

    def create_renewal_quote(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/contracts/{contract_id}/renewal-quotes",
            payload,
            headers,
        )

    # ─── Renewal quotes ───────────────────────────────────────────────────────

    def list_renewal_quotes(
        self, headers, contract_id=None, status=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/renewal-quotes",
            None,
            headers,
            params=_params(
                contract_id=contract_id, status=status, limit=limit, offset=offset
            ),
        )

    def get_renewal_quote(self, quote_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/renewal-quotes/{quote_id}", None, headers
        )

    def accept_renewal_quote(self, quote_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/renewal-quotes/{quote_id}/accept",
            payload,
            headers,
        )

    def decline_renewal_quote(self, quote_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/renewal-quotes/{quote_id}/decline",
            payload,
            headers,
        )

    # ─── Technicians ──────────────────────────────────────────────────────────

    def create_technician(self, payload, headers):
        return self._request("POST", f"{BUSINESS_PREFIX}/technicians", payload, headers)

    def list_technicians(
        self,
        headers,
        region_code=None,
        duty_status=None,
        is_safety_inspector=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/technicians",
            None,
            headers,
            params=_params(
                region_code=region_code,
                duty_status=duty_status,
                is_safety_inspector=is_safety_inspector,
                limit=limit,
                offset=offset,
            ),
        )

    def get_technician(self, technician_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/technicians/{technician_id}", None, headers
        )

    def set_duty_status(self, technician_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/technicians/{technician_id}/duty-status",
            payload,
            headers,
        )

    # ─── Technician assignments ───────────────────────────────────────────────

    def list_technician_assignments(
        self,
        headers,
        technician_id=None,
        service_call_id=None,
        preventive_visit_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/technician-assignments",
            None,
            headers,
            params=_params(
                technician_id=technician_id,
                service_call_id=service_call_id,
                preventive_visit_id=preventive_visit_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_technician_assignment(self, assignment_id, headers):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/technician-assignments/{assignment_id}",
            None,
            headers,
        )

    def release_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/technician-assignments/{assignment_id}/release",
            payload,
            headers,
        )

    # ─── Preventive visits ────────────────────────────────────────────────────

    def create_preventive_visit(self, payload, headers):
        return self._request(
            "POST", f"{BUSINESS_PREFIX}/preventive-visits", payload, headers
        )

    def list_preventive_visits(
        self,
        headers,
        contract_id=None,
        equipment_id=None,
        assigned_technician_id=None,
        visit_status=None,
        safety_doc_status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/preventive-visits",
            None,
            headers,
            params=_params(
                contract_id=contract_id,
                equipment_id=equipment_id,
                assigned_technician_id=assigned_technician_id,
                visit_status=visit_status,
                safety_doc_status=safety_doc_status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_preventive_visit(self, visit_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}", None, headers
        )

    def start_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}/start",
            payload,
            headers,
        )

    def record_checklist_result(self, visit_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}/checklist-results",
            payload,
            headers,
        )

    def complete_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}/complete",
            payload,
            headers,
        )

    def cancel_visit(self, visit_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}/cancel",
            payload,
            headers,
        )

    def mark_visit_missed(self, visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}/mark-missed",
            payload,
            headers,
        )

    def submit_safety_doc(self, visit_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}/safety-doc/submit",
            payload,
            headers,
        )

    def certify_safety_doc(self, visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}/safety-doc/certify",
            payload,
            headers,
        )

    def reject_safety_doc(self, visit_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/preventive-visits/{visit_id}/safety-doc/reject",
            payload,
            headers,
        )

    # ─── Service calls ────────────────────────────────────────────────────────

    def create_service_call(self, payload, headers):
        return self._request(
            "POST", f"{BUSINESS_PREFIX}/service-calls", payload, headers
        )

    def list_service_calls(
        self,
        headers,
        contract_id=None,
        equipment_id=None,
        assigned_technician_id=None,
        status=None,
        severity=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/service-calls",
            None,
            headers,
            params=_params(
                contract_id=contract_id,
                equipment_id=equipment_id,
                assigned_technician_id=assigned_technician_id,
                status=status,
                severity=severity,
                limit=limit,
                offset=offset,
            ),
        )

    def get_service_call(self, call_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/service-calls/{call_id}", None, headers
        )

    def dispatch_service_call(self, call_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/service-calls/{call_id}/dispatch",
            payload,
            headers,
        )

    def arrive_service_call(self, call_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/service-calls/{call_id}/arrive",
            payload,
            headers,
        )

    def place_parts_hold(self, call_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/service-calls/{call_id}/parts-hold",
            payload,
            headers,
        )

    def resume_service_call(self, call_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/service-calls/{call_id}/resume",
            payload,
            headers,
        )

    def resolve_service_call(self, call_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/service-calls/{call_id}/resolve",
            payload,
            headers,
        )

    def cancel_service_call(self, call_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/service-calls/{call_id}/cancel",
            payload,
            headers,
        )

    # ─── Spare parts ──────────────────────────────────────────────────────────

    def create_part(self, payload, headers):
        return self._request("POST", f"{BUSINESS_PREFIX}/parts", payload, headers)

    def list_parts(
        self,
        headers,
        model_id=None,
        category=None,
        lifecycle_status=None,
        is_critical_spare=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/parts",
            None,
            headers,
            params=_params(
                model_id=model_id,
                category=category,
                lifecycle_status=lifecycle_status,
                is_critical_spare=is_critical_spare,
                limit=limit,
                offset=offset,
            ),
        )

    def get_part(self, part_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/parts/{part_id}", None, headers
        )

    def adjust_inventory(self, part_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/parts/{part_id}/inventory-adjustments",
            payload,
            headers,
        )

    def declare_end_of_support(self, part_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/parts/{part_id}/declare-end-of-support",
            payload,
            headers,
        )

    # ─── Part orders ──────────────────────────────────────────────────────────

    def list_part_orders(
        self,
        headers,
        service_call_id=None,
        part_id=None,
        status=None,
        source=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/part-orders",
            None,
            headers,
            params=_params(
                service_call_id=service_call_id,
                part_id=part_id,
                status=status,
                source=source,
                limit=limit,
                offset=offset,
            ),
        )

    def get_part_order(self, order_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/part-orders/{order_id}", None, headers
        )

    def install_part_order(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/part-orders/{order_id}/install",
            payload,
            headers,
        )

    def cancel_part_order(self, order_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/part-orders/{order_id}/cancel",
            payload,
            headers,
        )

    # ─── Downtime events ──────────────────────────────────────────────────────

    def list_downtime_events(
        self,
        headers,
        contract_id=None,
        equipment_id=None,
        service_call_id=None,
        status=None,
        period_key=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BUSINESS_PREFIX}/downtime-events",
            None,
            headers,
            params=_params(
                contract_id=contract_id,
                equipment_id=equipment_id,
                service_call_id=service_call_id,
                status=status,
                period_key=period_key,
                limit=limit,
                offset=offset,
            ),
        )

    def get_downtime_event(self, event_id, headers):
        return self._request(
            "GET", f"{BUSINESS_PREFIX}/downtime-events/{event_id}", None, headers
        )

    def waive_downtime_event(self, event_id, payload, headers):
        return self._request(
            "POST",
            f"{BUSINESS_PREFIX}/downtime-events/{event_id}/waive",
            payload,
            headers,
        )

    # ─── Raw escape hatches for shape and pagination probes ───────────────────

    def get_path(self, path, headers, params=None):
        """GET an arbitrary path (used for out-of-bounds pagination probes)."""
        return self._request("GET", path, None, headers, params=params)

    def post_path(self, path, payload, headers):
        """POST to an arbitrary path (used for malformed-shape probes)."""
        return self._request("POST", path, payload, headers)
