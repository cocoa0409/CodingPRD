"""API client: one method per endpoint defined in the Federal Acquisition PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock (test-driving) ───────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── VendorRegistration ─────────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def activate_vendor(self, vendor_id, headers, payload=None):
        return self._request(
            "POST", f"/vendors/{vendor_id}/activate", payload or {}, headers
        )

    def expire_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/expire", {}, headers)

    def exclude_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/exclude", {}, headers)

    # ── Solicitation ───────────────────────────────────────────────
    def create_solicitation(self, payload, headers):
        return self._request("POST", "/solicitations", payload, headers)

    def get_solicitation(self, sol_id, headers):
        return self._request("GET", f"/solicitations/{sol_id}", headers=headers)

    def list_solicitations(self, headers, params=None):
        return self._request("GET", "/solicitations", headers=headers, params=params)

    def add_factor(self, sol_id, payload, headers):
        return self._request("POST", f"/solicitations/{sol_id}/factors", payload, headers)

    def list_factors(self, sol_id, headers):
        return self._request("GET", f"/solicitations/{sol_id}/factors", headers=headers)

    def open_solicitation(self, sol_id, headers):
        return self._request("POST", f"/solicitations/{sol_id}/open", {}, headers)

    def amend_solicitation(self, sol_id, headers):
        return self._request("POST", f"/solicitations/{sol_id}/amend", {}, headers)

    def close_solicitation(self, sol_id, headers):
        return self._request("POST", f"/solicitations/{sol_id}/close", {}, headers)

    def finalize_evaluation(self, sol_id, headers):
        return self._request(
            "POST", f"/solicitations/{sol_id}/finalize-evaluation", {}, headers
        )

    def cancel_solicitation(self, sol_id, headers):
        return self._request("POST", f"/solicitations/{sol_id}/cancel", {}, headers)

    # ── Proposal ───────────────────────────────────────────────────
    def create_proposal(self, payload, headers):
        return self._request("POST", "/proposals", payload, headers)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/proposals", headers=headers, params=params)

    def add_score(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/proposals/{proposal_id}/scores", payload, headers
        )

    def list_scores(self, proposal_id, headers):
        return self._request(
            "GET", f"/proposals/{proposal_id}/scores", headers=headers
        )

    def get_factor_score(self, fs_id, headers):
        return self._request("GET", f"/factor-scores/{fs_id}", headers=headers)

    def list_factor_scores(self, headers, params=None):
        return self._request("GET", "/factor-scores", headers=headers, params=params)

    def submit_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/submit", {}, headers)

    def begin_evaluation(self, proposal_id, headers):
        return self._request(
            "POST", f"/proposals/{proposal_id}/begin-evaluation", {}, headers
        )

    def score_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/score", {}, headers)

    # ── Award ──────────────────────────────────────────────────────
    def create_award(self, payload, headers):
        return self._request("POST", "/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    # ── Contract ───────────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def add_clin(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/clins", payload, headers
        )

    def list_clins(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/clins", headers=headers)

    def complete_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/complete", {}, headers
        )

    def closeout_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/closeout", {}, headers
        )

    # ── Invoice ────────────────────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/approve", {}, headers)

    def reject_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/reject", {}, headers)

    # ── Modification ───────────────────────────────────────────────
    def create_modification(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/modifications", payload, headers
        )

    def list_modifications(self, contract_id, headers):
        return self._request(
            "GET", f"/contracts/{contract_id}/modifications", headers=headers
        )

    def get_modification(self, mod_id, headers):
        return self._request("GET", f"/modifications/{mod_id}", headers=headers)

    def approve_modification(self, mod_id, headers):
        return self._request("POST", f"/modifications/{mod_id}/approve", {}, headers)

    def reject_modification(self, mod_id, headers):
        return self._request("POST", f"/modifications/{mod_id}/reject", {}, headers)

    # ── Protest ────────────────────────────────────────────────────
    def create_protest(self, payload, headers):
        return self._request("POST", "/protests", payload, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"/protests/{protest_id}", headers=headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", "/protests", headers=headers, params=params)

    def begin_review(self, protest_id, headers):
        return self._request(
            "POST", f"/protests/{protest_id}/begin-review", {}, headers
        )

    def resolve_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"/protests/{protest_id}/resolve", payload, headers
        )

    def withdraw_protest(self, protest_id, headers):
        return self._request("POST", f"/protests/{protest_id}/withdraw", {}, headers)

    # ── CPARS ──────────────────────────────────────────────────────
    def create_cpars(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/cpars", payload, headers
        )

    def list_cpars(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/cpars", headers=headers)


api_client = ApiClient()
