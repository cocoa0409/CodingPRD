"""API client: one method per endpoint the PRD defines under /host-agency."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/host-agency"


class ApiClient(GenericApiClient):
    """Typed wrapper over the Host Travel Agency Advisor Commissions API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def advance_clock_to(self, to_iso8601, headers):
        return self.set_clock({"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Reference data: split schedules, consortiums, suppliers
    # ------------------------------------------------------------------

    def create_split_schedule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/split-schedules", payload, headers)

    def create_consortium(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consortiums", payload, headers)

    def create_supplier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{PREFIX}/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/suppliers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Advisors
    # ------------------------------------------------------------------

    def create_advisor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/advisors", payload, headers)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"{PREFIX}/advisors/{advisor_id}", headers=headers)

    def list_advisors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/advisors", headers=headers, params=params)

    def activate_advisor(self, advisor_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/advisors/{advisor_id}/activate", payload or {}, headers
        )

    def suspend_advisor(self, advisor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/advisors/{advisor_id}/suspend", payload, headers
        )

    def reinstate_advisor(self, advisor_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/advisors/{advisor_id}/reinstate", payload or {}, headers
        )

    def declare_departure(self, advisor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/advisors/{advisor_id}/departure", payload, headers
        )

    def finalize_departure(self, advisor_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/advisors/{advisor_id}/departure/finalize",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Advisor agreements
    # ------------------------------------------------------------------

    def create_advisor_agreement(self, advisor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/advisors/{advisor_id}/agreements", payload, headers
        )

    def get_advisor_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/advisor-agreements/{agreement_id}", headers=headers
        )

    def list_advisor_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/advisor-agreements", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Compliance credentials
    # ------------------------------------------------------------------

    def create_compliance_credential(self, advisor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/advisors/{advisor_id}/credentials", payload, headers
        )

    def get_compliance_credential(self, credential_id, headers):
        return self._request(
            "GET", f"{PREFIX}/compliance-credentials/{credential_id}", headers=headers
        )

    def list_compliance_credentials(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/compliance-credentials", headers=headers, params=params
        )

    def decide_compliance_credential(self, credential_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/compliance-credentials/{credential_id}/decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Clients and the trust ledger
    # ------------------------------------------------------------------

    def create_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients", headers=headers, params=params)

    def create_trust_ledger_entry(self, client_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/clients/{client_id}/trust-ledger-entries", payload, headers
        )

    def list_client_trust_ledger_entries(self, client_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/clients/{client_id}/trust-ledger-entries",
            headers=headers,
            params=params,
        )

    def list_booking_trust_ledger_entries(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/bookings/{booking_id}/trust-ledger-entries",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Bookings
    # ------------------------------------------------------------------

    def create_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/confirm", payload or {}, headers
        )

    def mark_booking_traveled(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/traveled", payload or {}, headers
        )

    def cancel_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/cancel", payload, headers
        )

    def record_commission_receipt(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/commission-receipt", payload, headers
        )

    # ------------------------------------------------------------------
    # Commission claims
    # ------------------------------------------------------------------

    def create_commission_claim(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/commission-claims", payload, headers
        )

    def get_commission_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/commission-claims/{claim_id}", headers=headers
        )

    def list_commission_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/commission-claims", headers=headers, params=params
        )

    def deny_commission_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/commission-claims/{claim_id}/deny", payload, headers
        )

    def resubmit_commission_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/commission-claims/{claim_id}/resubmit",
            payload or {},
            headers,
        )

    def resolve_commission_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/commission-claims/{claim_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Settlement runs and advisor statements
    # ------------------------------------------------------------------

    def create_settlement_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-runs", payload, headers)

    def get_settlement_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/settlement-runs/{run_id}", headers=headers)

    def calculate_settlement_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/settlement-runs/{run_id}/calculate", payload or {}, headers
        )

    def post_settlement_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/settlement-runs/{run_id}/post", payload or {}, headers
        )

    def get_advisor_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/advisor-statements/{statement_id}", headers=headers
        )

    def list_advisor_statements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/advisor-statements", headers=headers, params=params
        )

    def pay_advisor_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/advisor-statements/{statement_id}/pay", payload, headers
        )


api_client = ApiClient()
