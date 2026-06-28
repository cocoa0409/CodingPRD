"""API client: one method per endpoint defined in the Greenhouse Nursery Grower PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Crop varieties --------------------------------------------------
    def create_variety(self, payload, headers):
        return self._request("POST", "/nursery/varieties", payload, headers)

    def get_variety(self, variety_id, headers):
        return self._request("GET", f"/nursery/varieties/{variety_id}", headers=headers)

    def list_varieties(self, headers, params=None):
        return self._request("GET", "/nursery/varieties", headers=headers, params=params)

    def activate_variety(self, variety_id, headers):
        return self._request("POST", f"/nursery/varieties/{variety_id}/activate", {}, headers)

    def suspend_variety(self, variety_id, headers):
        return self._request("POST", f"/nursery/varieties/{variety_id}/suspend", {}, headers)

    def retire_variety(self, variety_id, headers):
        return self._request("POST", f"/nursery/varieties/{variety_id}/retire", {}, headers)

    # ----- Zones -----------------------------------------------------------
    def create_zone(self, payload, headers):
        return self._request("POST", "/nursery/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/nursery/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/nursery/zones", headers=headers, params=params)

    def list_zone_batches(self, zone_id, headers, params=None):
        return self._request("GET", f"/nursery/zones/{zone_id}/batches", headers=headers, params=params)

    def quarantine_zone(self, zone_id, headers):
        return self._request("POST", f"/nursery/zones/{zone_id}/quarantine", {}, headers)

    def release_quarantine_zone(self, zone_id, headers):
        return self._request("POST", f"/nursery/zones/{zone_id}/release-quarantine", {}, headers)

    def decommission_zone(self, zone_id, headers):
        return self._request("POST", f"/nursery/zones/{zone_id}/decommission", {}, headers)

    # ----- Propagation batches ---------------------------------------------
    def create_batch(self, payload, headers):
        return self._request("POST", "/nursery/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/nursery/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/nursery/batches", headers=headers, params=params)

    def transplant_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/nursery/batches/{batch_id}/transplant", payload, headers)

    def start_grading(self, batch_id, headers):
        return self._request("POST", f"/nursery/batches/{batch_id}/start-grading", {}, headers)

    def finalize_grade(self, batch_id, headers):
        return self._request("POST", f"/nursery/batches/{batch_id}/finalize-grade", {}, headers)

    def cull_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/nursery/batches/{batch_id}/cull-batch", payload, headers)

    def void_batch(self, batch_id, headers):
        return self._request("POST", f"/nursery/batches/{batch_id}/void", {}, headers)

    def list_input_logs(self, batch_id, headers, params=None):
        return self._request("GET", f"/nursery/batches/{batch_id}/input-logs", headers=headers, params=params)

    def create_input_log(self, batch_id, payload, headers):
        return self._request("POST", f"/nursery/batches/{batch_id}/input-logs", payload, headers)

    # ----- Brokers ---------------------------------------------------------
    def create_broker(self, payload, headers):
        return self._request("POST", "/nursery/brokers", payload, headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/nursery/brokers/{broker_id}", headers=headers)

    def list_brokers(self, headers, params=None):
        return self._request("GET", "/nursery/brokers", headers=headers, params=params)

    def hold_broker(self, broker_id, headers):
        return self._request("POST", f"/nursery/brokers/{broker_id}/hold", {}, headers)

    def reinstate_broker(self, broker_id, headers):
        return self._request("POST", f"/nursery/brokers/{broker_id}/reinstate", {}, headers)

    # ----- Availability entries --------------------------------------------
    def create_availability(self, payload, headers):
        return self._request("POST", "/nursery/availability", payload, headers)

    def get_availability(self, entry_id, headers):
        return self._request("GET", f"/nursery/availability/{entry_id}", headers=headers)

    def list_availability(self, headers, params=None):
        return self._request("GET", "/nursery/availability", headers=headers, params=params)

    def close_availability(self, entry_id, headers):
        return self._request("POST", f"/nursery/availability/{entry_id}/close", {}, headers)

    # ----- Broker orders + lines -------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/nursery/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/nursery/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/nursery/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/nursery/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/nursery/orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/nursery/order-lines/{line_id}", headers=headers)

    def list_all_order_lines(self, headers, params=None):
        return self._request("GET", "/nursery/order-lines", headers=headers, params=params)

    def delete_order_line(self, line_id, headers):
        return self._request("DELETE", f"/nursery/order-lines/{line_id}", headers=headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/nursery/orders/{order_id}/confirm", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/nursery/orders/{order_id}/cancel", {}, headers)

    # ----- Phytosanitary certificates --------------------------------------
    def create_phyto_certificate(self, payload, headers):
        return self._request("POST", "/nursery/phyto-certificates", payload, headers)

    def get_phyto_certificate(self, cert_id, headers):
        return self._request("GET", f"/nursery/phyto-certificates/{cert_id}", headers=headers)

    def list_phyto_certificates(self, headers, params=None):
        return self._request("GET", "/nursery/phyto-certificates", headers=headers, params=params)

    # ----- Shipments -------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/nursery/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/nursery/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/nursery/shipments", headers=headers, params=params)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/nursery/shipments/{shipment_id}/dispatch", {}, headers)

    def void_shipment(self, shipment_id, headers):
        return self._request("POST", f"/nursery/shipments/{shipment_id}/void", {}, headers)

    # ----- Ops checkpoint + logical clock ----------------------------------
    def run_ops(self, headers):
        return self._request("POST", "/nursery/run-ops", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
