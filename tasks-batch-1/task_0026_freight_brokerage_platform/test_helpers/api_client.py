"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Shippers (PRD §3.1) ───────────────────────────────────────
    def create_shipper(self, payload, headers):
        return self._request("POST", "/freight/shippers", payload, headers)

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"/freight/shippers/{shipper_id}", headers=headers)

    def list_shippers(self, headers, params=None):
        return self._request("GET", "/freight/shippers", headers=headers, params=params)

    def get_credit_risk(self, shipper_id, headers):
        return self._request(
            "GET",
            f"/freight/shippers/{shipper_id}/credit-risk",
            headers=headers,
        )

    def list_shipper_smartway_audits(self, shipper_id, headers, params=None):
        return self._request(
            "GET",
            f"/freight/shippers/{shipper_id}/smartway-audits",
            headers=headers,
            params=params,
        )

    # ─── Carriers (PRD §3.1) ───────────────────────────────────────
    def create_carrier(self, payload, headers):
        return self._request("POST", "/freight/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/freight/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/freight/carriers", headers=headers, params=params)

    def qualify_carrier(self, carrier_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/carriers/{carrier_id}/qualify",
            payload if payload is not None else {},
            headers,
        )

    def reject_carrier(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"/freight/carriers/{carrier_id}/reject", payload, headers
        )

    def suspend_carrier(self, carrier_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/carriers/{carrier_id}/suspend",
            payload if payload is not None else {},
            headers,
        )

    def reinstate_carrier(self, carrier_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/carriers/{carrier_id}/reinstate",
            payload if payload is not None else {},
            headers,
        )

    # ─── Contract rates (PRD §3.2) ─────────────────────────────────
    def create_contract_rate(self, payload, headers):
        return self._request("POST", "/freight/contract-rates", payload, headers)

    def get_contract_rate(self, contract_rate_id, headers):
        return self._request(
            "GET", f"/freight/contract-rates/{contract_rate_id}", headers=headers
        )

    def list_contract_rates(self, headers, params=None):
        return self._request(
            "GET", "/freight/contract-rates", headers=headers, params=params
        )

    def activate_contract_rate(self, contract_rate_id, payload, headers):
        return self._request(
            "POST",
            f"/freight/contract-rates/{contract_rate_id}/activate",
            payload,
            headers,
        )

    def terminate_contract_rate(self, contract_rate_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/contract-rates/{contract_rate_id}/terminate",
            payload if payload is not None else {},
            headers,
        )

    # ─── Quote requests (PRD §3.3, §3.4) ───────────────────────────
    def create_quote_request(self, payload, headers):
        return self._request("POST", "/freight/quote-requests", payload, headers)

    def get_quote_request(self, quote_id, headers):
        return self._request(
            "GET", f"/freight/quote-requests/{quote_id}", headers=headers
        )

    def list_quote_requests(self, headers, params=None):
        return self._request(
            "GET", "/freight/quote-requests", headers=headers, params=params
        )

    def award_quote(self, quote_id, payload, headers):
        return self._request(
            "POST", f"/freight/quote-requests/{quote_id}/award", payload, headers
        )

    def withdraw_quote(self, quote_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/quote-requests/{quote_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ─── Loads (PRD §3.5, §3.6) ────────────────────────────────────
    def get_load(self, load_id, headers):
        return self._request("GET", f"/freight/loads/{load_id}", headers=headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/freight/loads", headers=headers, params=params)

    def pickup_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/freight/loads/{load_id}/pickup", payload, headers
        )

    def deliver_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/freight/loads/{load_id}/deliver", payload, headers
        )

    def cancel_load(self, load_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/loads/{load_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    def invoice_load(self, load_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/loads/{load_id}/invoice",
            payload if payload is not None else {},
            headers,
        )

    def add_accessorial(self, load_id, payload, headers):
        return self._request(
            "POST", f"/freight/loads/{load_id}/accessorials", payload, headers
        )

    def list_accessorials(self, load_id, headers, params=None):
        return self._request(
            "GET",
            f"/freight/loads/{load_id}/accessorials",
            headers=headers,
            params=params,
        )

    # ─── Invoices (PRD §3.6) ───────────────────────────────────────
    def get_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/freight/invoices/{invoice_id}", headers=headers
        )

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/freight/invoices", headers=headers, params=params)

    def record_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/freight/invoices/{invoice_id}/payments", payload, headers
        )

    # ─── Factoring (PRD §3.8) ──────────────────────────────────────
    def create_factoring_request(self, payload, headers):
        return self._request("POST", "/freight/factoring-requests", payload, headers)

    def get_factoring_request(self, fr_id, headers):
        return self._request(
            "GET", f"/freight/factoring-requests/{fr_id}", headers=headers
        )

    def list_factoring_requests(self, headers, params=None):
        return self._request(
            "GET", "/freight/factoring-requests", headers=headers, params=params
        )

    def approve_factoring(self, fr_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/factoring-requests/{fr_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def advance_factoring(self, fr_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/factoring-requests/{fr_id}/advance",
            payload if payload is not None else {},
            headers,
        )

    def reject_factoring(self, fr_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/factoring-requests/{fr_id}/reject",
            payload if payload is not None else {},
            headers,
        )

    # ─── Dispute claims (PRD §3.7) ─────────────────────────────────
    def create_dispute_claim(self, payload, headers):
        return self._request("POST", "/freight/dispute-claims", payload, headers)

    def get_dispute_claim(self, dc_id, headers):
        return self._request(
            "GET", f"/freight/dispute-claims/{dc_id}", headers=headers
        )

    def list_dispute_claims(self, headers, params=None):
        return self._request(
            "GET", "/freight/dispute-claims", headers=headers, params=params
        )

    def resolve_dispute(self, dc_id, payload, headers):
        return self._request(
            "POST", f"/freight/dispute-claims/{dc_id}/resolve", payload, headers
        )

    def withdraw_dispute(self, dc_id, headers, payload=None):
        return self._request(
            "POST",
            f"/freight/dispute-claims/{dc_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ─── SmartWay audits (PRD §3.8) ────────────────────────────────
    def create_smartway_audit(self, payload, headers):
        return self._request("POST", "/freight/smartway-audits", payload, headers)

    def list_smartway_audits(self, headers, params=None):
        return self._request(
            "GET", "/freight/smartway-audits", headers=headers, params=params
        )

    # ─── Test-driving clock (PRD §3.9) ─────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request(
            "POST", "/freight/_clock/set_current_utc", payload, headers
        )

    def clock_advance(self, headers, payload=None):
        return self._request(
            "POST",
            "/freight/_clock/advance",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
