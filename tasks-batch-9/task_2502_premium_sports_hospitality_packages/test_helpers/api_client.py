"""Typed HTTP client with one method per endpoint of PRD §4.

Every collection sits at the root of the URL space (PRD §2.8), so no method
nests one resource inside another's path; relationships travel in request
bodies as explicit identifiers.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per row of the PRD §4 endpoint table."""

    # ---------------------------------------------------------------- admin
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def daily_run(self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", "/operations/daily-run", payload or {}, headers)

    # --------------------------------------------------------------- events
    def create_event(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/events/{event_id}", None, headers)

    def postpone_event(self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/postpone", payload, headers)

    def cancel_event(self, event_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/cancel", payload or {}, headers)

    def complete_event(self, event_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/complete", payload or {}, headers)

    def get_margin_report(self, event_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/events/{event_id}/margin-report", params, headers)

    # ---------------------------------------------------------- rights deals
    def create_rights_deal(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rights-deals", payload, headers)

    def get_rights_deal(self, deal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rights-deals/{deal_id}", None, headers)

    def list_rights_deals(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/rights-deals", params, headers)

    def commit_rights_deal(self, deal_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/rights-deals/{deal_id}/commit", payload or {}, headers)

    def settle_rights_deal(self, deal_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/rights-deals/{deal_id}/settle", payload or {}, headers)

    # ------------------------------------------------------ release tranches
    def create_release_tranche(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/release-tranches", payload, headers)

    def get_release_tranche(self, tranche_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/release-tranches/{tranche_id}", None, headers)

    def list_release_tranches(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/release-tranches", params, headers)

    def confirm_release_tranche(self, tranche_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/release-tranches/{tranche_id}/confirm", payload, headers)

    # ------------------------------------------------------ allocation blocks
    def create_allocation_block(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/allocation-blocks", payload, headers)

    def get_allocation_block(self, block_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/allocation-blocks/{block_id}", None, headers)

    def list_allocation_blocks(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/allocation-blocks", params, headers)

    def recall_allocation_block(self, block_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/allocation-blocks/{block_id}/recall", payload or {}, headers)

    # ------------------------------------------------------ package products
    def create_package_product(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/package-products", payload, headers)

    def get_package_product(self, package_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/package-products/{package_id}", None, headers)

    def list_package_products(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/package-products", params, headers)

    def price_package_product(self, package_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/package-products/{package_id}/price", payload or {}, headers)

    def publish_package_product(self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/package-products/{package_id}/publish", payload, headers)

    # ---------------------------------------------------- package components
    def create_package_component(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/package-components", payload, headers)

    def get_package_component(self, component_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/package-components/{component_id}", None, headers)

    def list_package_components(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/package-components", params, headers)

    # -------------------------------------------------------------- clients
    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clients/{client_id}", None, headers)

    # ------------------------------------------------------------- bookings
    def create_booking(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/bookings/{booking_id}", None, headers)

    def list_bookings(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/bookings", params, headers)

    def allocate_booking(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/bookings/{booking_id}/allocate", payload, headers)

    def issue_credentials(self, booking_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/bookings/{booking_id}/issue-credentials", payload or {}, headers)

    def cancel_booking(self, booking_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload or {}, headers)

    def rebook_booking(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/bookings/{booking_id}/rebook", payload, headers)

    # -------------------------------------------------- payment installments
    def get_payment_installment(self, installment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/payment-installments/{installment_id}", None, headers)

    def list_payment_installments(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/payment-installments", params, headers)

    def pay_installment(self, installment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/payment-installments/{installment_id}/pay", payload, headers)

    # --------------------------------------------------- hospitality builds
    def create_hospitality_build(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/hospitality-builds", payload, headers)

    def get_hospitality_build(self, build_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/hospitality-builds/{build_id}", None, headers)

    def list_hospitality_builds(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/hospitality-builds", params, headers)

    def approve_hospitality_build(self, build_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/hospitality-builds/{build_id}/approve", payload or {}, headers)

    def ready_hospitality_build(self, build_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/hospitality-builds/{build_id}/ready", payload or {}, headers)

    # -------------------------------------------------------- on-site hosts
    def create_on_site_host(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/on-site-hosts", payload, headers)

    def get_on_site_host(self, host_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/on-site-hosts/{host_id}", None, headers)

    # ------------------------------------------------------ host assignments
    def create_host_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/host-assignments", payload, headers)

    def get_host_assignment(self, assignment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/host-assignments/{assignment_id}", None, headers)

    def list_host_assignments(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/host-assignments", params, headers)

    def release_host_assignment(self, assignment_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/host-assignments/{assignment_id}/release", payload or {}, headers)

    # ------------------------------------------------------- raw escape hatch
    def raw_post(self, path: str, payload: Any, headers: Optional[Dict[str, str]]) -> requests.Response:
        """POST with no payload normalisation, for header and shape probes."""
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, params: Any, headers: Optional[Dict[str, str]]) -> requests.Response:
        """GET with no payload normalisation, for header and shape probes."""
        return self._request("GET", path, params, headers)
