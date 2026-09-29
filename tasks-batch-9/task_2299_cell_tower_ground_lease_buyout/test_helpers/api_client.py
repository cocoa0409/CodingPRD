"""Typed client exposing exactly one method per endpoint of the lease-buyout API.

Every path is rooted at the ``/lease-buyouts`` prefix the PRD declares. Methods return
the raw ``requests.Response`` so tests decide whether to validate success or error.
"""

import time
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/lease-buyouts"


class ApiClient(GenericApiClient):
    """One method per endpoint; no business logic lives here."""

    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url)
        # The harness reboots the server on the same port before every test, so a
        # pooled keep-alive socket left over from the previous test points at a dead
        # process and fails the next request with ConnectionReset / RemoteDisconnected.
        # Asking for connection close keeps no socket across requests at all.
        self.session.headers["Connection"] = "close"

    # Transport-level retry budget. Two distinct failures live under
    # requests.ConnectionError, and neither delivered the request to the WSGI app,
    # so re-sending cannot double-apply a side effect:
    #   * ConnectionResetError / RemoteDisconnected -- a pooled keep-alive socket
    #     pointing at the previous, already-rebooted server process.
    #   * ConnectionRefusedError -- nothing bound to the port yet, i.e. the request
    #     landed inside a server boot window.
    # The refused case needs a budget on the order of a boot, not milliseconds, so
    # back off up to ~8s in total while staying well inside the 30s test timeout.
    _RETRY_BACKOFFS = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0)

    def _request(self, method: str, path: str, payload: Any = None, headers=None, params=None):
        last_error = None
        for backoff in (*self._RETRY_BACKOFFS, None):
            try:
                return super()._request(method, path, payload=payload, headers=headers, params=params)
            except requests.exceptions.ConnectionError as exc:  # pragma: no cover - transport only
                last_error = exc
                if backoff is None:
                    break
                # Drop every pooled socket before retrying; the one we just used is
                # known bad and the pool may hold more of the same generation.
                self.session.close()
                time.sleep(backoff)
        raise last_error

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_current_utc(self, current_utc: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/_clock/set_current_utc", json={"current_utc": current_utc}, headers=headers)

    # ------------------------------------------------------------------
    # Portfolios
    # ------------------------------------------------------------------

    def create_portfolio(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/portfolios", json=payload, headers=headers)

    def list_portfolios(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/portfolios", headers=headers, params=params)

    def get_portfolio(self, portfolio_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/portfolios/{portfolio_id}", headers=headers)

    def adjust_portfolio_capital(
        self, portfolio_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/portfolios/{portfolio_id}/capital-adjustments", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Financing facilities, pledges and advances
    # ------------------------------------------------------------------

    def create_financing_facility(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/financing-facilities", json=payload, headers=headers)

    def get_financing_facility(self, facility_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/financing-facilities/{facility_id}", headers=headers)

    def list_portfolio_financing_facilities(
        self, portfolio_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/portfolios/{portfolio_id}/financing-facilities", headers=headers, params=params)

    def create_pledge(
        self, facility_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/financing-facilities/{facility_id}/pledges", json=payload, headers=headers)

    def create_advance(
        self, facility_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/financing-facilities/{facility_id}/advances", json=payload, headers=headers)

    def list_collateral_pledges(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/collateral-pledges", headers=headers, params=params)

    def get_collateral_pledge(self, pledge_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/collateral-pledges/{pledge_id}", headers=headers)

    def release_collateral_pledge(
        self, pledge_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/collateral-pledges/{pledge_id}/release", json={}, headers=headers)

    # ------------------------------------------------------------------
    # Tower companies and sites
    # ------------------------------------------------------------------

    def create_tower_company(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/tower-companies", json=payload, headers=headers)

    def create_tower_site(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/tower-sites", json=payload, headers=headers)

    def list_tower_sites(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/tower-sites", headers=headers, params=params)

    def get_tower_site(self, tower_site_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/tower-sites/{tower_site_id}", headers=headers)

    # ------------------------------------------------------------------
    # Landowners
    # ------------------------------------------------------------------

    def create_landowner(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/landowners", json=payload, headers=headers)

    def get_landowner(self, landowner_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/landowners/{landowner_id}", headers=headers)

    def update_landowner(
        self, landowner_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.put(f"{API_PREFIX}/landowners/{landowner_id}", json=payload, headers=headers, method="PATCH")

    # ------------------------------------------------------------------
    # Lease streams
    # ------------------------------------------------------------------

    def create_lease_stream(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/lease-streams", json=payload, headers=headers)

    def list_lease_streams(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/lease-streams", headers=headers, params=params)

    def get_lease_stream(self, lease_stream_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/lease-streams/{lease_stream_id}", headers=headers)

    # ------------------------------------------------------------------
    # Carrier tenancies
    # ------------------------------------------------------------------

    def create_tenancy(
        self, lease_stream_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/lease-streams/{lease_stream_id}/tenancies", json=payload, headers=headers)

    def list_tenancies(
        self, lease_stream_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/lease-streams/{lease_stream_id}/tenancies", headers=headers, params=params)

    def set_tenancy_status(
        self, tenancy_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/carrier-tenancies/{tenancy_id}/status", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Stream valuations
    # ------------------------------------------------------------------

    def create_valuation(
        self, lease_stream_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/lease-streams/{lease_stream_id}/valuations", json=payload, headers=headers)

    def list_valuations(
        self, lease_stream_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/lease-streams/{lease_stream_id}/valuations", headers=headers, params=params)

    def approve_valuation(self, valuation_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/stream-valuations/{valuation_id}/approve", json={}, headers=headers)

    # ------------------------------------------------------------------
    # Deals
    # ------------------------------------------------------------------

    def create_deal(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals", json=payload, headers=headers)

    def list_deals(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/deals", headers=headers, params=params)

    def get_deal(self, deal_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/deals/{deal_id}", headers=headers)

    def start_outreach(self, deal_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals/{deal_id}/outreach", json={}, headers=headers)

    def terminate_deal(
        self, deal_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals/{deal_id}/terminate", json=payload, headers=headers)

    def get_settlement(self, deal_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/deals/{deal_id}/settlement", headers=headers)

    def clear_to_close(self, deal_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals/{deal_id}/clear-to-close", json={}, headers=headers)

    def fund_escrow(self, deal_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals/{deal_id}/escrow-funding", json={}, headers=headers)

    def close_deal(
        self, deal_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals/{deal_id}/close", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Offers
    # ------------------------------------------------------------------

    def create_offer(
        self, deal_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals/{deal_id}/offers", json=payload, headers=headers)

    def list_offers(
        self, deal_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/deals/{deal_id}/offers", headers=headers, params=params)

    def transition_offer(
        self, offer_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/offers/{offer_id}/transitions", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Title reports and mortgagee consent
    # ------------------------------------------------------------------

    def create_title_report(
        self, deal_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals/{deal_id}/title-reports", json=payload, headers=headers)

    def list_title_reports(
        self, deal_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/deals/{deal_id}/title-reports", headers=headers, params=params)

    def get_title_report(self, title_report_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/title-reports/{title_report_id}", headers=headers)

    def transition_title_report(
        self, title_report_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/title-reports/{title_report_id}/transitions", json=payload, headers=headers)

    def decide_consent(
        self, title_report_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/title-reports/{title_report_id}/consent-decision", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Right of first refusal
    # ------------------------------------------------------------------

    def serve_rofr_notice(
        self, deal_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/deals/{deal_id}/rofr-notices", json=payload or {}, headers=headers)

    def list_rofr_notices(
        self, deal_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/deals/{deal_id}/rofr-notices", headers=headers, params=params)

    def respond_to_rofr_notice(
        self, notice_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/rofr-notices/{notice_id}/response", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------

    def open_dispute(
        self, lease_stream_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/lease-streams/{lease_stream_id}/disputes", json=payload, headers=headers)

    def list_disputes(
        self, lease_stream_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/lease-streams/{lease_stream_id}/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/disputes/{dispute_id}", headers=headers)

    def transition_dispute(
        self, dispute_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/disputes/{dispute_id}/transitions", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Amendment events
    # ------------------------------------------------------------------

    def create_amendment_event(
        self, lease_stream_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/lease-streams/{lease_stream_id}/amendment-events", json=payload, headers=headers
        )

    def list_amendment_events(
        self, lease_stream_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/lease-streams/{lease_stream_id}/amendment-events", headers=headers, params=params
        )

    def reverse_amendment_event(
        self, amendment_event_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(f"{API_PREFIX}/amendment-events/{amendment_event_id}/reverse", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Raw escape hatch for negative probes that need an arbitrary path
    # ------------------------------------------------------------------

    def raw_get(
        self, path: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(path, headers=headers, params=params)

    def put(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        method: str = "PUT",
    ) -> requests.Response:
        """PATCH/PUT share a body-carrying request shape; ``method`` selects the verb."""
        return self._request(method, path, payload=json, headers=headers)


api_client = ApiClient()

__all__ = ["ApiClient", "api_client", "API_PREFIX"]
