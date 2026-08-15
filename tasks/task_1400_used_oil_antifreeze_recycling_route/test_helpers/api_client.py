"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Customer ----------
    def create_customer(self, payload, headers):
        return self._request("POST", "/recycle-routes/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/recycle-routes/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/recycle-routes/customers/{customer_id}", headers=headers)

    def activate_customer(self, customer_id, headers):
        return self._request("POST", f"/recycle-routes/customers/{customer_id}/activate", {}, headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/recycle-routes/customers/{customer_id}/suspend", {}, headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/recycle-routes/customers/{customer_id}/reinstate", {}, headers)

    def terminate_customer(self, customer_id, headers):
        return self._request("POST", f"/recycle-routes/customers/{customer_id}/terminate", {}, headers)

    def top_up_customer(self, customer_id, payload, headers):
        return self._request("POST", f"/recycle-routes/customers/{customer_id}/top-up", payload, headers)

    def list_customer_tank_sites(self, customer_id, headers, params=None):
        return self._request("GET", f"/recycle-routes/customers/{customer_id}/tank-sites", headers=headers, params=params)

    # ---------- TankSite ----------
    def create_tank_site(self, payload, headers):
        return self._request("POST", "/recycle-routes/tank-sites", payload, headers)

    def list_tank_sites(self, headers, params=None):
        return self._request("GET", "/recycle-routes/tank-sites", headers=headers, params=params)

    def get_tank_site(self, tank_site_id, headers):
        return self._request("GET", f"/recycle-routes/tank-sites/{tank_site_id}", headers=headers)

    def activate_tank_site(self, tank_site_id, headers):
        return self._request("POST", f"/recycle-routes/tank-sites/{tank_site_id}/activate", {}, headers)

    def deactivate_tank_site(self, tank_site_id, headers):
        return self._request("POST", f"/recycle-routes/tank-sites/{tank_site_id}/deactivate", {}, headers)

    def certify_clean_tank_site(self, tank_site_id, headers):
        return self._request("POST", f"/recycle-routes/tank-sites/{tank_site_id}/certify-clean", {}, headers)

    def list_tank_site_tanks(self, tank_site_id, headers, params=None):
        return self._request("GET", f"/recycle-routes/tank-sites/{tank_site_id}/tanks", headers=headers, params=params)

    # ---------- Tank ----------
    def create_tank(self, payload, headers):
        return self._request("POST", "/recycle-routes/tanks", payload, headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/recycle-routes/tanks", headers=headers, params=params)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/recycle-routes/tanks/{tank_id}", headers=headers)

    def install_tank(self, tank_id, headers):
        return self._request("POST", f"/recycle-routes/tanks/{tank_id}/install", {}, headers)

    def register_existing_tank(self, tank_id, headers):
        return self._request("POST", f"/recycle-routes/tanks/{tank_id}/register-existing", {}, headers)

    def decommission_tank(self, tank_id, headers):
        return self._request("POST", f"/recycle-routes/tanks/{tank_id}/decommission", {}, headers)

    def decommission_confirm_tank(self, tank_id, headers):
        return self._request("POST", f"/recycle-routes/tanks/{tank_id}/decommission-confirm", {}, headers)

    def clear_quarantine_tank(self, tank_id, headers):
        return self._request("POST", f"/recycle-routes/tanks/{tank_id}/clear-quarantine", {}, headers)

    def record_intake(self, tank_id, payload, headers):
        return self._request("POST", f"/recycle-routes/tanks/{tank_id}/record-intake", payload, headers)

    # ---------- Driver ----------
    def create_driver(self, payload, headers):
        return self._request("POST", "/recycle-routes/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/recycle-routes/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/recycle-routes/drivers/{driver_id}", headers=headers)

    def suspend_driver(self, driver_id, headers):
        return self._request("POST", f"/recycle-routes/drivers/{driver_id}/suspend", {}, headers)

    # ---------- Route ----------
    def create_route(self, payload, headers):
        return self._request("POST", "/recycle-routes/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/recycle-routes/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/recycle-routes/routes/{route_id}", headers=headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/recycle-routes/routes/{route_id}/dispatch", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/recycle-routes/routes/{route_id}/complete", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/recycle-routes/routes/{route_id}/cancel", {}, headers)

    def list_route_stops_for_route(self, route_id, headers, params=None):
        return self._request("GET", f"/recycle-routes/routes/{route_id}/route-stops", headers=headers, params=params)

    def get_route_manifest(self, route_id, headers):
        return self._request("GET", f"/recycle-routes/routes/{route_id}/manifest", headers=headers)

    # ---------- RouteStop ----------
    def create_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/recycle-routes/routes/{route_id}/route-stops", payload, headers)

    def get_route_stop(self, route_stop_id, headers):
        return self._request("GET", f"/recycle-routes/route-stops/{route_stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/recycle-routes/route-stops", headers=headers, params=params)

    def arrive_route_stop(self, route_stop_id, headers):
        return self._request("POST", f"/recycle-routes/route-stops/{route_stop_id}/arrive", {}, headers)

    def begin_screening_route_stop(self, route_stop_id, headers):
        return self._request("POST", f"/recycle-routes/route-stops/{route_stop_id}/begin-screening", {}, headers)

    def cancel_by_customer_route_stop(self, route_stop_id, headers):
        return self._request("POST", f"/recycle-routes/route-stops/{route_stop_id}/cancel-by-customer", {}, headers)

    def skip_below_minimum_route_stop(self, route_stop_id, payload, headers):
        return self._request("POST", f"/recycle-routes/route-stops/{route_stop_id}/skip-below-minimum", payload, headers)

    def list_sample_screenings_for_stop(self, route_stop_id, headers, params=None):
        return self._request("GET", f"/recycle-routes/route-stops/{route_stop_id}/sample-screenings", headers=headers, params=params)

    def list_pickup_tickets_for_stop(self, route_stop_id, headers, params=None):
        return self._request("GET", f"/recycle-routes/route-stops/{route_stop_id}/pickup-tickets", headers=headers, params=params)

    # ---------- SampleScreening ----------
    def create_sample_screening(self, route_stop_id, payload, headers):
        return self._request("POST", f"/recycle-routes/route-stops/{route_stop_id}/sample-screenings", payload, headers)

    def get_sample_screening(self, screening_id, headers):
        return self._request("GET", f"/recycle-routes/sample-screenings/{screening_id}", headers=headers)

    def list_sample_screenings(self, headers, params=None):
        return self._request("GET", "/recycle-routes/sample-screenings", headers=headers, params=params)

    # ---------- PickupTicket ----------
    def create_pickup_ticket(self, route_stop_id, payload, headers):
        return self._request("POST", f"/recycle-routes/route-stops/{route_stop_id}/pickup-tickets", payload, headers)

    def get_pickup_ticket(self, ticket_id, headers):
        return self._request("GET", f"/recycle-routes/pickup-tickets/{ticket_id}", headers=headers)

    def list_pickup_tickets(self, headers, params=None):
        return self._request("GET", "/recycle-routes/pickup-tickets", headers=headers, params=params)

    def settle_pickup_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/recycle-routes/pickup-tickets/{ticket_id}/settle", payload, headers)

    def dispute_pickup_ticket(self, ticket_id, headers):
        return self._request("POST", f"/recycle-routes/pickup-tickets/{ticket_id}/dispute", {}, headers)

    def adjust_pickup_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/recycle-routes/pickup-tickets/{ticket_id}/adjust", payload, headers)

    # ---------- DisposalFacility ----------
    def create_disposal_facility(self, payload, headers):
        return self._request("POST", "/recycle-routes/disposal-facilities", payload, headers)

    def list_disposal_facilities(self, headers, params=None):
        return self._request("GET", "/recycle-routes/disposal-facilities", headers=headers, params=params)

    def get_disposal_facility(self, facility_id, headers):
        return self._request("GET", f"/recycle-routes/disposal-facilities/{facility_id}", headers=headers)

    # ---------- Manifest ----------
    def create_manifest(self, route_id, payload, headers):
        return self._request("POST", f"/recycle-routes/routes/{route_id}/manifest", payload, headers)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/recycle-routes/manifests/{manifest_id}", headers=headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/recycle-routes/manifests", headers=headers, params=params)

    def submit_manifest(self, manifest_id, headers):
        return self._request("POST", f"/recycle-routes/manifests/{manifest_id}/submit", {}, headers)

    def depart_manifest(self, manifest_id, headers):
        return self._request("POST", f"/recycle-routes/manifests/{manifest_id}/depart", {}, headers)

    def deliver_manifest(self, manifest_id, headers):
        return self._request("POST", f"/recycle-routes/manifests/{manifest_id}/deliver", {}, headers)

    def close_manifest(self, manifest_id, headers):
        return self._request("POST", f"/recycle-routes/manifests/{manifest_id}/close", {}, headers)

    def request_amendment_manifest(self, manifest_id, headers):
        return self._request("POST", f"/recycle-routes/manifests/{manifest_id}/request-amendment", {}, headers)

    def approve_amendment_manifest(self, manifest_id, headers):
        return self._request("POST", f"/recycle-routes/manifests/{manifest_id}/approve-amendment", {}, headers)

    def facility_reject_manifest(self, manifest_id, headers):
        return self._request("POST", f"/recycle-routes/manifests/{manifest_id}/facility-reject", {}, headers)

    # ---------- BlendBatch ----------
    def create_blend_batch(self, payload, headers):
        return self._request("POST", "/recycle-routes/blend-batches", payload, headers)

    def list_blend_batches(self, headers, params=None):
        return self._request("GET", "/recycle-routes/blend-batches", headers=headers, params=params)

    def get_blend_batch(self, batch_id, headers):
        return self._request("GET", f"/recycle-routes/blend-batches/{batch_id}", headers=headers)

    def start_blending_batch(self, batch_id, headers):
        return self._request("POST", f"/recycle-routes/blend-batches/{batch_id}/start-blending", {}, headers)

    def hold_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/recycle-routes/blend-batches/{batch_id}/hold", {}, headers)

    def resume_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/recycle-routes/blend-batches/{batch_id}/resume", {}, headers)

    def release_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/recycle-routes/blend-batches/{batch_id}/release", {}, headers)

    def mark_sold_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/recycle-routes/blend-batches/{batch_id}/mark-sold", {}, headers)

    def cancel_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/recycle-routes/blend-batches/{batch_id}/cancel", {}, headers)

    # ---------- SpillIncident ----------
    def create_spill_incident(self, payload, headers):
        return self._request("POST", "/recycle-routes/spill-incidents", payload, headers)

    def list_spill_incidents(self, headers, params=None):
        return self._request("GET", "/recycle-routes/spill-incidents", headers=headers, params=params)

    def get_spill_incident(self, spill_id, headers):
        return self._request("GET", f"/recycle-routes/spill-incidents/{spill_id}", headers=headers)

    def begin_investigation_spill(self, spill_id, headers):
        return self._request("POST", f"/recycle-routes/spill-incidents/{spill_id}/begin-investigation", {}, headers)

    def remediate_spill(self, spill_id, headers):
        return self._request("POST", f"/recycle-routes/spill-incidents/{spill_id}/remediate", {}, headers)

    def close_spill(self, spill_id, headers):
        return self._request("POST", f"/recycle-routes/spill-incidents/{spill_id}/close", {}, headers)

    # ---------- MarketPrice ----------
    def create_market_price(self, payload, headers):
        return self._request("POST", "/recycle-routes/market-prices", payload, headers)

    def list_market_prices(self, headers, params=None):
        return self._request("GET", "/recycle-routes/market-prices", headers=headers, params=params)

    def get_market_price(self, market_price_id, headers):
        return self._request("GET", f"/recycle-routes/market-prices/{market_price_id}", headers=headers)

    # ---------- Clock (test-driving) ----------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/recycle-routes/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
