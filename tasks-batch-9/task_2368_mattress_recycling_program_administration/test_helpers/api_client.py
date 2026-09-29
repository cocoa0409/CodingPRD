"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # State programs
    # ------------------------------------------------------------------
    def create_state_program(self, payload, headers):
        return self._request("POST", "/state-programs", payload, headers)

    def get_state_program(self, program_id, headers):
        return self._request("GET", f"/state-programs/{program_id}", headers=headers)

    def update_cost_forecast(self, program_id, payload, headers):
        return self._request(
            "PATCH", f"/state-programs/{program_id}/cost-forecast", payload, headers
        )

    def get_fee_adequacy(self, program_id, headers):
        return self._request(
            "GET", f"/state-programs/{program_id}/fee-adequacy", headers=headers
        )

    # ------------------------------------------------------------------
    # Fee rate schedules
    # ------------------------------------------------------------------
    def create_fee_rate_schedule(self, payload, headers):
        return self._request("POST", "/fee-rate-schedules", payload, headers)

    def get_fee_rate_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/fee-rate-schedules/{schedule_id}", headers=headers
        )

    def list_fee_rate_schedules(self, headers, params=None):
        return self._request(
            "GET", "/fee-rate-schedules", headers=headers, params=params
        )

    def approve_fee_rate_schedule(self, schedule_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fee-rate-schedules/{schedule_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def activate_fee_rate_schedule(self, schedule_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fee-rate-schedules/{schedule_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Registrants
    # ------------------------------------------------------------------
    def create_registrant(self, payload, headers):
        return self._request("POST", "/registrants", payload, headers)

    def get_registrant(self, registrant_id, headers):
        return self._request("GET", f"/registrants/{registrant_id}", headers=headers)

    # ------------------------------------------------------------------
    # Sales remittances
    # ------------------------------------------------------------------
    def create_sales_remittance(self, payload, headers):
        return self._request("POST", "/sales-remittances", payload, headers)

    def get_sales_remittance(self, remittance_id, headers):
        return self._request(
            "GET", f"/sales-remittances/{remittance_id}", headers=headers
        )

    def list_sales_remittances(self, headers, params=None):
        return self._request(
            "GET", "/sales-remittances", headers=headers, params=params
        )

    def create_exemption_claim(self, remittance_id, payload, headers):
        return self._request(
            "POST",
            f"/sales-remittances/{remittance_id}/exemption-claims",
            payload,
            headers,
        )

    def list_exemption_claims(self, remittance_id, headers, params=None):
        return self._request(
            "GET",
            f"/sales-remittances/{remittance_id}/exemption-claims",
            headers=headers,
            params=params,
        )

    def file_sales_remittance(self, remittance_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sales-remittances/{remittance_id}/file",
            payload if payload is not None else {},
            headers,
        )

    def pay_sales_remittance(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/sales-remittances/{remittance_id}/pay", payload, headers
        )

    def refund_sales_remittance(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/sales-remittances/{remittance_id}/refund", payload, headers
        )

    def open_remittance_audit(self, remittance_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sales-remittances/{remittance_id}/audit-open",
            payload if payload is not None else {},
            headers,
        )

    def adjudicate_exemption_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/exemption-claims/{claim_id}/adjudicate", payload, headers
        )

    def request_remittance_amendment(self, remittance_id, payload, headers):
        return self._request(
            "POST",
            f"/sales-remittances/{remittance_id}/request-amendment",
            payload,
            headers,
        )

    def create_remittance_amendment(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/sales-remittances/{remittance_id}/amendments", payload, headers
        )

    def close_remittance_audit(self, remittance_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sales-remittances/{remittance_id}/audit-close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Collection sites and volume reports
    # ------------------------------------------------------------------
    def create_collection_site(self, payload, headers):
        return self._request("POST", "/collection-sites", payload, headers)

    def get_collection_site(self, site_id, headers):
        return self._request("GET", f"/collection-sites/{site_id}", headers=headers)

    def list_collection_sites(self, headers, params=None):
        return self._request(
            "GET", "/collection-sites", headers=headers, params=params
        )

    def enroll_collection_site(self, site_id, headers, payload=None):
        return self._request(
            "POST",
            f"/collection-sites/{site_id}/enroll",
            payload if payload is not None else {},
            headers,
        )

    def suspend_collection_site(self, site_id, payload, headers):
        return self._request(
            "POST", f"/collection-sites/{site_id}/suspend", payload, headers
        )

    def reinstate_collection_site(self, site_id, headers, payload=None):
        return self._request(
            "POST",
            f"/collection-sites/{site_id}/reinstate",
            payload if payload is not None else {},
            headers,
        )

    def create_volume_report(self, site_id, payload, headers):
        return self._request(
            "POST", f"/collection-sites/{site_id}/volume-reports", payload, headers
        )

    def list_volume_reports(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/collection-sites/{site_id}/volume-reports",
            headers=headers,
            params=params,
        )

    def accept_volume_report(self, report_id, headers, payload=None):
        return self._request(
            "POST",
            f"/volume-reports/{report_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Haulers
    # ------------------------------------------------------------------
    def create_hauler(self, payload, headers):
        return self._request("POST", "/haulers", payload, headers)

    def get_hauler(self, hauler_id, headers):
        return self._request("GET", f"/haulers/{hauler_id}", headers=headers)

    def list_haulers(self, headers, params=None):
        return self._request("GET", "/haulers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Recyclers and commodity output
    # ------------------------------------------------------------------
    def create_recycler(self, payload, headers):
        return self._request("POST", "/recyclers", payload, headers)

    def get_recycler(self, recycler_id, headers):
        return self._request("GET", f"/recyclers/{recycler_id}", headers=headers)

    def list_recyclers(self, headers, params=None):
        return self._request("GET", "/recyclers", headers=headers, params=params)

    def certify_recycler(self, recycler_id, headers, payload=None):
        return self._request(
            "POST",
            f"/recyclers/{recycler_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    def suspend_recycler_certification(self, recycler_id, payload, headers):
        return self._request(
            "POST", f"/recyclers/{recycler_id}/suspend-certification", payload, headers
        )

    def recertify_recycler(self, recycler_id, headers, payload=None):
        return self._request(
            "POST",
            f"/recyclers/{recycler_id}/recertify",
            payload if payload is not None else {},
            headers,
        )

    def create_commodity_output_record(self, recycler_id, payload, headers):
        return self._request(
            "POST",
            f"/recyclers/{recycler_id}/commodity-output-records",
            payload,
            headers,
        )

    def list_commodity_output_records(self, recycler_id, headers, params=None):
        return self._request(
            "GET",
            f"/recyclers/{recycler_id}/commodity-output-records",
            headers=headers,
            params=params,
        )

    def verify_commodity_output_record(self, record_id, headers, payload=None):
        return self._request(
            "POST",
            f"/commodity-output-records/{record_id}/verify",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Pickup orders, inspections and settlement
    # ------------------------------------------------------------------
    def create_pickup_order(self, payload, headers):
        return self._request("POST", "/pickup-orders", payload, headers)

    def get_pickup_order(self, order_id, headers):
        return self._request("GET", f"/pickup-orders/{order_id}", headers=headers)

    def list_pickup_orders(self, headers, params=None):
        return self._request("GET", "/pickup-orders", headers=headers, params=params)

    def confirm_pickup(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pickup-orders/{order_id}/pickup-confirm",
            payload if payload is not None else {},
            headers,
        )

    def deliver_pickup_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pickup-orders/{order_id}/deliver", payload, headers
        )

    def create_load_inspection(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pickup-orders/{order_id}/inspections", payload, headers
        )

    def list_load_inspections(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"/pickup-orders/{order_id}/inspections",
            headers=headers,
            params=params,
        )

    def finalize_settlement(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pickup-orders/{order_id}/finalize-settlement",
            payload if payload is not None else {},
            headers,
        )

    def void_pickup_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pickup-orders/{order_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Take-back deliveries
    # ------------------------------------------------------------------
    def create_take_back_delivery(self, payload, headers):
        return self._request("POST", "/take-back-deliveries", payload, headers)

    def get_take_back_delivery(self, delivery_id, headers):
        return self._request(
            "GET", f"/take-back-deliveries/{delivery_id}", headers=headers
        )

    def list_take_back_deliveries(self, headers, params=None):
        return self._request(
            "GET", "/take-back-deliveries", headers=headers, params=params
        )

    def complete_takeback(self, delivery_id, payload, headers):
        return self._request(
            "POST",
            f"/take-back-deliveries/{delivery_id}/complete-takeback",
            payload,
            headers,
        )

    def waive_takeback(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/take-back-deliveries/{delivery_id}/waive", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
