"""API client: one method per endpoint defined in the PRD (section 4).

All resources are addressed flat under the /bulk-liquid prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/bulk-liquid/_clock/set_current_utc", payload, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/bulk-liquid/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/bulk-liquid/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/bulk-liquid/customers/{customer_id}/suspend", headers=headers)

    def reactivate_customer(self, customer_id, headers):
        return self._request("POST", f"/bulk-liquid/customers/{customer_id}/reactivate", headers=headers)

    # --- products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/bulk-liquid/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/bulk-liquid/products/{product_id}", headers=headers)

    # --- compatibility rules ---
    def create_compatibility_rule(self, payload, headers):
        return self._request("POST", "/bulk-liquid/compatibility-rules", payload, headers)

    def list_compatibility_rules(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/compatibility-rules", headers=headers, params=params)

    def get_compatibility_rule(self, rule_id, headers):
        return self._request("GET", f"/bulk-liquid/compatibility-rules/{rule_id}", headers=headers)

    # --- trailers ---
    def create_trailer(self, payload, headers):
        return self._request("POST", "/bulk-liquid/trailers", payload, headers)

    def list_trailers(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/trailers", headers=headers, params=params)

    def get_trailer(self, trailer_id, headers):
        return self._request("GET", f"/bulk-liquid/trailers/{trailer_id}", headers=headers)

    # --- drivers ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/bulk-liquid/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/bulk-liquid/drivers/{driver_id}", headers=headers)

    def deactivate_driver(self, driver_id, headers):
        return self._request("POST", f"/bulk-liquid/drivers/{driver_id}/deactivate", headers=headers)

    # --- wash bays ---
    def create_wash_bay(self, payload, headers):
        return self._request("POST", "/bulk-liquid/wash-bays", payload, headers)

    def list_wash_bays(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/wash-bays", headers=headers, params=params)

    def get_wash_bay(self, wash_bay_id, headers):
        return self._request("GET", f"/bulk-liquid/wash-bays/{wash_bay_id}", headers=headers)

    # --- tank wash certificates ---
    def create_wash_certificate(self, payload, headers):
        return self._request("POST", "/bulk-liquid/tank-wash-certificates", payload, headers)

    def list_wash_certificates(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/tank-wash-certificates", headers=headers, params=params)

    def get_wash_certificate(self, cert_id, headers):
        return self._request("GET", f"/bulk-liquid/tank-wash-certificates/{cert_id}", headers=headers)

    def certify_wash_certificate(self, cert_id, headers):
        return self._request("POST", f"/bulk-liquid/tank-wash-certificates/{cert_id}/certify", headers=headers)

    def revoke_wash_certificate(self, cert_id, headers):
        return self._request("POST", f"/bulk-liquid/tank-wash-certificates/{cert_id}/revoke", headers=headers)

    def cancel_wash_booking(self, cert_id, headers):
        return self._request("POST", f"/bulk-liquid/tank-wash-certificates/{cert_id}/cancel-booking", headers=headers)

    # --- loading racks ---
    def create_loading_rack(self, payload, headers):
        return self._request("POST", "/bulk-liquid/loading-racks", payload, headers)

    def list_loading_racks(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/loading-racks", headers=headers, params=params)

    def get_loading_rack(self, rack_id, headers):
        return self._request("GET", f"/bulk-liquid/loading-racks/{rack_id}", headers=headers)

    # --- shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/bulk-liquid/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/bulk-liquid/shipments/{shipment_id}", headers=headers)

    def patch_shipment(self, shipment_id, payload, headers):
        return self._request("PATCH", f"/bulk-liquid/shipments/{shipment_id}", payload, headers)

    def plan_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/plan", payload, headers)

    def unplan_shipment(self, shipment_id, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/unplan", headers=headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/cancel", headers=headers)

    def check_in_shipment(self, shipment_id, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/check-in", headers=headers)

    def abort_loading(self, shipment_id, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/abort-loading", headers=headers)

    def close_meter(self, shipment_id, payload, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/close-meter", payload, headers)

    def record_weights(self, shipment_id, payload, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/record-weights", payload, headers)

    def confirm_placards(self, shipment_id, payload, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/confirm-placards", payload, headers)

    def depart_shipment(self, shipment_id, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/depart", headers=headers)

    def start_delivery(self, shipment_id, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/start-delivery", headers=headers)

    def resolve_variance(self, shipment_id, payload, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/resolve-variance", payload, headers)

    def reconcile_shipment(self, shipment_id, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/reconcile", headers=headers)

    # --- meter tickets ---
    def list_meter_tickets(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/meter-tickets", headers=headers, params=params)

    def get_meter_ticket(self, ticket_id, headers):
        return self._request("GET", f"/bulk-liquid/meter-tickets/{ticket_id}", headers=headers)

    # --- delivery tickets ---
    def list_delivery_tickets(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/delivery-tickets", headers=headers, params=params)

    def get_delivery_ticket(self, ticket_id, headers):
        return self._request("GET", f"/bulk-liquid/delivery-tickets/{ticket_id}", headers=headers)

    def close_delivery_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/bulk-liquid/delivery-tickets/{ticket_id}/close", payload, headers)

    # --- retain samples ---
    def list_retain_samples(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/retain-samples", headers=headers, params=params)

    def get_retain_sample(self, sample_id, headers):
        return self._request("GET", f"/bulk-liquid/retain-samples/{sample_id}", headers=headers)

    def dispose_retain_sample(self, sample_id, headers):
        return self._request("POST", f"/bulk-liquid/retain-samples/{sample_id}/dispose", headers=headers)

    # --- spill response plans ---
    def create_spill_plan(self, payload, headers):
        return self._request("POST", "/bulk-liquid/spill-response-plans", payload, headers)

    def list_spill_plans(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/spill-response-plans", headers=headers, params=params)

    def get_spill_plan(self, plan_id, headers):
        return self._request("GET", f"/bulk-liquid/spill-response-plans/{plan_id}", headers=headers)

    def submit_spill_plan(self, plan_id, headers):
        return self._request("POST", f"/bulk-liquid/spill-response-plans/{plan_id}/submit", headers=headers)

    def approve_spill_plan(self, plan_id, headers):
        return self._request("POST", f"/bulk-liquid/spill-response-plans/{plan_id}/approve", headers=headers)

    def reject_spill_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/bulk-liquid/spill-response-plans/{plan_id}/reject", payload, headers)

    def suspend_spill_plan(self, plan_id, headers):
        return self._request("POST", f"/bulk-liquid/spill-response-plans/{plan_id}/suspend", headers=headers)

    def reinstate_spill_plan(self, plan_id, headers):
        return self._request("POST", f"/bulk-liquid/spill-response-plans/{plan_id}/reinstate", headers=headers)

    # --- spill incidents ---
    def create_spill_incident(self, shipment_id, payload, headers):
        return self._request("POST", f"/bulk-liquid/shipments/{shipment_id}/spill-incidents", payload, headers)

    def list_spill_incidents(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/spill-incidents", headers=headers, params=params)

    def get_spill_incident(self, incident_id, headers):
        return self._request("GET", f"/bulk-liquid/spill-incidents/{incident_id}", headers=headers)

    def start_incident_review(self, incident_id, headers):
        return self._request("POST", f"/bulk-liquid/spill-incidents/{incident_id}/start-review", headers=headers)

    def request_incident_info(self, incident_id, headers):
        return self._request("POST", f"/bulk-liquid/spill-incidents/{incident_id}/request-info", headers=headers)

    def close_spill_incident(self, incident_id, headers):
        return self._request("POST", f"/bulk-liquid/spill-incidents/{incident_id}/close", headers=headers)

    def reopen_spill_incident(self, incident_id, headers):
        return self._request("POST", f"/bulk-liquid/spill-incidents/{incident_id}/reopen", headers=headers)

    # --- dedicated trailer agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/bulk-liquid/dedicated-trailer-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/bulk-liquid/dedicated-trailer-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/bulk-liquid/dedicated-trailer-agreements/{agreement_id}", headers=headers)

    def patch_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/bulk-liquid/dedicated-trailer-agreements/{agreement_id}", payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/bulk-liquid/dedicated-trailer-agreements/{agreement_id}/activate", headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/bulk-liquid/dedicated-trailer-agreements/{agreement_id}/terminate", headers=headers)

    def close_agreement_month(self, agreement_id, payload, headers):
        return self._request("POST", f"/bulk-liquid/dedicated-trailer-agreements/{agreement_id}/close-month", payload, headers)


api_client = ApiClient()
