"""API client: one method per endpoint defined in the PRD (mounted at /vmi)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock / system sweep (PRD §2.4, §3.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/vmi/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def sweep_cert_expiry(self, headers):
        return self._request("POST", "/vmi/_sweep/cert-expiry", {}, headers)

    # ------------------------------------------------------------------
    # Customer sites (PRD §3.1)
    # ------------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/vmi/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/vmi/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/vmi/sites", headers=headers, params=params)

    def retire_site(self, site_id, headers):
        return self._request("POST", f"/vmi/sites/{site_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Parts (PRD §3.1)
    # ------------------------------------------------------------------
    def create_part(self, payload, headers):
        return self._request("POST", "/vmi/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/vmi/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/vmi/parts", headers=headers, params=params)

    def obsolete_part(self, part_id, headers):
        return self._request("POST", f"/vmi/parts/{part_id}/obsolete", {}, headers)

    # ------------------------------------------------------------------
    # Part cross-references (PRD §3.1)
    # ------------------------------------------------------------------
    def create_part_cross_reference(self, payload, headers):
        return self._request("POST", "/vmi/part-cross-references", payload, headers)

    def get_part_cross_reference(self, xref_id, headers):
        return self._request("GET", f"/vmi/part-cross-references/{xref_id}",
                             headers=headers)

    def list_part_cross_references(self, headers, params=None):
        return self._request("GET", "/vmi/part-cross-references",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Bin agreements (PRD §3.2)
    # ------------------------------------------------------------------
    def create_bin_agreement(self, payload, headers):
        return self._request("POST", "/vmi/bin-agreements", payload, headers)

    def get_bin_agreement(self, agreement_id, headers):
        return self._request("GET", f"/vmi/bin-agreements/{agreement_id}",
                             headers=headers)

    def list_bin_agreements(self, headers, params=None):
        return self._request("GET", "/vmi/bin-agreements", headers=headers,
                             params=params)

    def update_bin_agreement(self, agreement_id, payload, headers):
        return self._request("PUT", f"/vmi/bin-agreements/{agreement_id}",
                             payload, headers)

    def retire_bin_agreement(self, agreement_id, headers):
        return self._request("POST", f"/vmi/bin-agreements/{agreement_id}/retire",
                             {}, headers)

    def substitute_bin_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/vmi/bin-agreements/{agreement_id}/substitute",
                             {}, headers)

    def get_sizing_recommendation(self, agreement_id, headers, params=None):
        return self._request("GET",
                             f"/vmi/bin-agreements/{agreement_id}/sizing-recommendation",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Replenishment routes (PRD §3.3)
    # ------------------------------------------------------------------
    def create_route(self, payload, headers):
        return self._request("POST", "/vmi/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/vmi/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/vmi/routes", headers=headers, params=params)

    def start_route(self, route_id, headers):
        return self._request("POST", f"/vmi/routes/{route_id}/start", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/vmi/routes/{route_id}/cancel", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/vmi/routes/{route_id}/close", {}, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/vmi/routes/{route_id}/stops",
                             headers=headers, params=params)

    def create_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/vmi/routes/{route_id}/stops",
                             payload, headers)

    # ------------------------------------------------------------------
    # Route stops (PRD §3.3)
    # ------------------------------------------------------------------
    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/vmi/route-stops/{stop_id}", headers=headers)

    def list_route_stops_global(self, headers, params=None):
        return self._request("GET", "/vmi/route-stops", headers=headers,
                             params=params)

    def submit_route_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/vmi/route-stops/{stop_id}/submit",
                             payload, headers)

    # ------------------------------------------------------------------
    # Replenishment orders (PRD §3.4)
    # ------------------------------------------------------------------
    def get_replenishment_order(self, order_id, headers):
        return self._request("GET", f"/vmi/replenishment-orders/{order_id}",
                             headers=headers)

    def list_replenishment_orders(self, headers, params=None):
        return self._request("GET", "/vmi/replenishment-orders", headers=headers,
                             params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST",
                             f"/vmi/replenishment-orders/{order_id}/confirm",
                             {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST",
                             f"/vmi/replenishment-orders/{order_id}/ship",
                             {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST",
                             f"/vmi/replenishment-orders/{order_id}/deliver",
                             {}, headers)

    def dispute_order(self, order_id, headers):
        return self._request("POST",
                             f"/vmi/replenishment-orders/{order_id}/dispute",
                             {}, headers)

    def resolve_dispute(self, order_id, headers):
        return self._request("POST",
                             f"/vmi/replenishment-orders/{order_id}/resolve-dispute",
                             {}, headers)

    def release_hold_order(self, order_id, headers):
        return self._request("POST",
                             f"/vmi/replenishment-orders/{order_id}/release-hold",
                             {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST",
                             f"/vmi/replenishment-orders/{order_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Lot certificates (PRD §3.5)
    # ------------------------------------------------------------------
    def create_lot_certificate(self, payload, headers):
        return self._request("POST", "/vmi/lot-certificates", payload, headers)

    def get_lot_certificate(self, cert_id, headers):
        return self._request("GET", f"/vmi/lot-certificates/{cert_id}",
                             headers=headers)

    def list_lot_certificates(self, headers, params=None):
        return self._request("GET", "/vmi/lot-certificates", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Kit jobs (PRD §3.6)
    # ------------------------------------------------------------------
    def create_kit_job(self, payload, headers):
        return self._request("POST", "/vmi/kit-jobs", payload, headers)

    def get_kit_job(self, kit_id, headers):
        return self._request("GET", f"/vmi/kit-jobs/{kit_id}", headers=headers)

    def list_kit_jobs(self, headers, params=None):
        return self._request("GET", "/vmi/kit-jobs", headers=headers, params=params)

    def start_picking(self, kit_id, headers):
        return self._request("POST", f"/vmi/kit-jobs/{kit_id}/start-picking",
                             {}, headers)

    def hold_kit_job(self, kit_id, headers):
        return self._request("POST", f"/vmi/kit-jobs/{kit_id}/hold", {}, headers)

    def resume_kit_job(self, kit_id, headers):
        return self._request("POST", f"/vmi/kit-jobs/{kit_id}/resume", {}, headers)

    def pack_kit_job(self, kit_id, headers):
        return self._request("POST", f"/vmi/kit-jobs/{kit_id}/pack", {}, headers)

    def complete_kit_job(self, kit_id, headers):
        return self._request("POST", f"/vmi/kit-jobs/{kit_id}/complete", {}, headers)

    def scrap_kit_job(self, kit_id, headers):
        return self._request("POST", f"/vmi/kit-jobs/{kit_id}/scrap", {}, headers)


api_client = ApiClient()
