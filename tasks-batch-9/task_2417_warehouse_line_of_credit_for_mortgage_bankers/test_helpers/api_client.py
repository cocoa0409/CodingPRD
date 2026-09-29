"""API client: one method per endpoint the PRD declares.

Every collection is addressed absolutely from the API root `/`; there is no
shared resource prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Facilities ───────────────────────────────────────────────────────────

    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def approve_facility(self, facility_id, headers, payload=None):
        return self._request(
            "POST", f"/facilities/{facility_id}/approve", payload or {}, headers
        )

    def suspend_facility(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/suspend", payload, headers
        )

    def reinstate_facility(self, facility_id, headers, payload=None):
        return self._request(
            "POST", f"/facilities/{facility_id}/reinstate", payload or {}, headers
        )

    # ─── Product advance rates ────────────────────────────────────────────────

    def create_product_advance_rate(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/product-advance-rates", payload, headers
        )

    def list_product_advance_rates(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/product-advance-rates",
            headers=headers,
            params=params,
        )

    # ─── Custodians ───────────────────────────────────────────────────────────

    def create_custodian(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/custodians", payload, headers
        )

    def list_facility_custodians(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/custodians", headers=headers, params=params
        )

    def get_custodian(self, custodian_id, headers):
        return self._request("GET", f"/custodians/{custodian_id}", headers=headers)

    def suspend_custodian(self, custodian_id, payload, headers):
        return self._request(
            "POST", f"/custodians/{custodian_id}/suspend", payload, headers
        )

    def list_custodian_receipts(self, custodian_id, headers, params=None):
        return self._request(
            "GET", f"/custodians/{custodian_id}/receipts", headers=headers, params=params
        )

    # ─── Take-out investors ───────────────────────────────────────────────────

    def create_investor(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/investors", payload, headers
        )

    def list_facility_investors(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/investors", headers=headers, params=params
        )

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    def approve_investor(self, investor_id, headers, payload=None):
        return self._request(
            "POST", f"/investors/{investor_id}/approve", payload or {}, headers
        )

    def suspend_investor(self, investor_id, payload, headers):
        return self._request(
            "POST", f"/investors/{investor_id}/suspend", payload, headers
        )

    def list_investor_commitments(self, investor_id, headers, params=None):
        return self._request(
            "GET", f"/investors/{investor_id}/commitments", headers=headers, params=params
        )

    def list_investor_bailee_letters(self, investor_id, headers, params=None):
        return self._request(
            "GET",
            f"/investors/{investor_id}/bailee-letters",
            headers=headers,
            params=params,
        )

    # ─── Take-out commitments ─────────────────────────────────────────────────

    def create_commitment(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/commitments", payload, headers
        )

    def list_facility_commitments(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/commitments",
            headers=headers,
            params=params,
        )

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/commitments/{commitment_id}", headers=headers)

    def withdraw_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"/commitments/{commitment_id}/withdraw", payload, headers
        )

    # ─── Advances ─────────────────────────────────────────────────────────────

    def create_advance(self, payload, headers):
        return self._request("POST", "/advances", payload, headers)

    def list_advances(self, headers, params=None):
        return self._request("GET", "/advances", headers=headers, params=params)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/advances/{advance_id}", headers=headers)

    def list_advance_wire_instructions(self, advance_id, headers, params=None):
        return self._request(
            "GET",
            f"/advances/{advance_id}/wire-instructions",
            headers=headers,
            params=params,
        )

    def decide_wire_instruction(self, wire_instruction_id, payload, headers):
        return self._request(
            "POST", f"/wire-instructions/{wire_instruction_id}/decision", payload, headers
        )

    def fund_advance(self, advance_id, headers, payload=None):
        return self._request(
            "POST", f"/advances/{advance_id}/fund", payload or {}, headers
        )

    # ─── Custodian receipts ───────────────────────────────────────────────────

    def create_receipt(self, advance_id, payload, headers):
        return self._request(
            "POST", f"/advances/{advance_id}/receipts", payload, headers
        )

    def list_advance_receipts(self, advance_id, headers, params=None):
        return self._request(
            "GET", f"/advances/{advance_id}/receipts", headers=headers, params=params
        )

    def cure_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/receipts/{receipt_id}/cure", payload, headers)

    # ─── Valuation, shipment, settlement ──────────────────────────────────────

    def value_advance(self, advance_id, payload, headers):
        return self._request(
            "POST", f"/advances/{advance_id}/valuation", payload, headers
        )

    def ship_advance(self, advance_id, payload, headers):
        return self._request("POST", f"/advances/{advance_id}/ship", payload, headers)

    def list_advance_bailee_letters(self, advance_id, headers, params=None):
        return self._request(
            "GET",
            f"/advances/{advance_id}/bailee-letters",
            headers=headers,
            params=params,
        )

    def purchase_advance(self, advance_id, headers, payload=None):
        return self._request(
            "POST", f"/advances/{advance_id}/purchase", payload or {}, headers
        )

    def repurchase_advance(self, advance_id, payload, headers):
        return self._request(
            "POST", f"/advances/{advance_id}/repurchase", payload, headers
        )

    # ─── Repurchase demands ───────────────────────────────────────────────────

    def create_repurchase_demand(self, advance_id, payload, headers):
        return self._request(
            "POST", f"/advances/{advance_id}/repurchase-demands", payload, headers
        )

    def list_advance_repurchase_demands(self, advance_id, headers, params=None):
        return self._request(
            "GET",
            f"/advances/{advance_id}/repurchase-demands",
            headers=headers,
            params=params,
        )

    def escalate_repurchase_demand(self, demand_id, headers, payload=None):
        return self._request(
            "POST", f"/repurchase-demands/{demand_id}/escalate", payload or {}, headers
        )

    # ─── Margin calls ─────────────────────────────────────────────────────────

    def create_margin_call(self, payload, headers):
        return self._request("POST", "/margin-calls", payload, headers)

    def list_facility_margin_calls(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/margin-calls",
            headers=headers,
            params=params,
        )

    def list_advance_margin_calls(self, advance_id, headers, params=None):
        return self._request(
            "GET", f"/advances/{advance_id}/margin-calls", headers=headers, params=params
        )

    def get_margin_call(self, margin_call_id, headers):
        return self._request("GET", f"/margin-calls/{margin_call_id}", headers=headers)

    def create_cure_payment(self, margin_call_id, payload, headers):
        return self._request(
            "POST", f"/margin-calls/{margin_call_id}/cure-payments", payload, headers
        )

    def list_cure_payments(self, margin_call_id, headers, params=None):
        return self._request(
            "GET",
            f"/margin-calls/{margin_call_id}/cure-payments",
            headers=headers,
            params=params,
        )

    def waive_margin_call(self, margin_call_id, payload, headers):
        return self._request(
            "POST", f"/margin-calls/{margin_call_id}/waive", payload, headers
        )

    # ─── Covenant tests ───────────────────────────────────────────────────────

    def create_covenant_test(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/covenant-tests", payload, headers
        )

    def list_covenant_tests(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/covenant-tests",
            headers=headers,
            params=params,
        )

    def waive_covenant_test(self, covenant_test_id, payload, headers):
        return self._request(
            "POST", f"/covenant-tests/{covenant_test_id}/waive", payload, headers
        )

    # ─── Aging run, ledger and reconciliation ─────────────────────────────────

    def run_aging(self, facility_id, headers, payload=None):
        return self._request(
            "POST", f"/facilities/{facility_id}/aging-run", payload or {}, headers
        )

    def list_facility_ledger_entries(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    def list_advance_ledger_entries(self, advance_id, headers, params=None):
        return self._request(
            "GET",
            f"/advances/{advance_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    def get_exposure_summary(self, facility_id, headers):
        return self._request(
            "GET", f"/facilities/{facility_id}/exposure-summary", headers=headers
        )

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, current_utc, headers=None):
        """Set the logical clock. Auth headers are not required here."""
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload, headers=None):
        """Set the logical clock with a caller-supplied body."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
