"""API client: one method per endpoint defined in the PRD.

The system is mounted under the ``/dno`` path prefix; the logical-clock endpoint
``POST /_clock/set_current_utc`` sits outside that prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/dno"


class ApiClient(GenericApiClient):
    # ─── Insureds ────────────────────────────────────────────────────────────

    def create_insured(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insureds", payload, headers)

    def update_insured(self, insured_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/insureds/{insured_id}", payload, headers)

    def get_insured(self, insured_id, headers):
        return self._request("GET", f"{PREFIX}/insureds/{insured_id}", headers=headers)

    # ─── Disclosure packages and litigation events ───────────────────────────

    def create_disclosure_package(self, insured_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/insureds/{insured_id}/disclosure-packages", payload, headers
        )

    def list_disclosure_packages(self, insured_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/insureds/{insured_id}/disclosure-packages",
            headers=headers, params=params,
        )

    def create_litigation_event(self, insured_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/insureds/{insured_id}/litigation-events", payload, headers
        )

    def list_litigation_events(self, insured_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/insureds/{insured_id}/litigation-events",
            headers=headers, params=params,
        )

    # ─── Submissions ─────────────────────────────────────────────────────────

    def create_submission(self, payload, headers):
        return self._request("POST", f"{PREFIX}/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"{PREFIX}/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/submissions", headers=headers, params=params)

    def score_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/submissions/{submission_id}/score", payload, headers
        )

    # ─── Quotes ──────────────────────────────────────────────────────────────

    def create_quote(self, submission_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/submissions/{submission_id}/quotes", payload, headers
        )

    def list_quotes(self, submission_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/submissions/{submission_id}/quotes",
            headers=headers, params=params,
        )

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"{PREFIX}/quotes/{quote_id}", headers=headers)

    def accept_quote(self, quote_id, headers):
        """Bind the quote and issue the policy. The request carries no body."""
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/accept", None, headers)

    # ─── Exclusion terms ─────────────────────────────────────────────────────

    def create_exclusion_term(self, quote_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/quotes/{quote_id}/exclusion-terms", payload, headers
        )

    def list_exclusion_terms(self, quote_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/quotes/{quote_id}/exclusion-terms",
            headers=headers, params=params,
        )

    def counter_exclusion_term(self, term_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exclusion-terms/{term_id}/counter", payload, headers
        )

    def resolve_exclusion_term(self, term_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exclusion-terms/{term_id}/resolve", payload, headers
        )

    # ─── Policies ────────────────────────────────────────────────────────────

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/policies", headers=headers, params=params)

    def list_coverage_parts(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/coverage-parts",
            headers=headers, params=params,
        )

    def create_premium_payment(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/premium-payments", payload, headers
        )

    def cancel_policy(self, policy_id, payload, headers):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/cancel", payload, headers)

    # ─── Tower layers ────────────────────────────────────────────────────────

    def create_layer(self, policy_id, payload, headers):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/layers", payload, headers)

    def get_layer(self, layer_id, headers):
        return self._request("GET", f"{PREFIX}/layers/{layer_id}", headers=headers)

    def list_layers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/layers", headers=headers, params=params)

    def seal_tower(self, policy_id, headers):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/seal-tower", None, headers)

    # ─── Run-off endorsements ────────────────────────────────────────────────

    def create_runoff_endorsement(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/runoff-endorsements", payload, headers
        )

    def list_runoff_endorsements(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/runoff-endorsements",
            headers=headers, params=params,
        )

    # ─── Circumstance reports ────────────────────────────────────────────────

    def create_circumstance_report(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/circumstance-reports", payload, headers
        )

    def list_circumstance_reports(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/circumstance-reports",
            headers=headers, params=params,
        )

    def mature_circumstance_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/circumstance-reports/{report_id}/mature", payload, headers
        )

    # ─── Claims ──────────────────────────────────────────────────────────────

    def create_claim(self, policy_id, payload, headers):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def create_coverage_decision(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/coverage-decision", payload, headers
        )

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/resolve", payload, headers)

    # ─── Defense invoices ────────────────────────────────────────────────────

    def create_defense_invoice(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/defense-invoices", payload, headers
        )

    def list_defense_invoices(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/defense-invoices",
            headers=headers, params=params,
        )

    def allocate_defense_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/defense-invoices/{invoice_id}/allocate", payload, headers
        )

    # ─── Settlement proposals ────────────────────────────────────────────────

    def create_settlement_proposal(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/settlement-proposals", payload, headers
        )

    def list_settlement_proposals(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/settlement-proposals",
            headers=headers, params=params,
        )

    def respond_settlement_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-proposals/{proposal_id}/respond", payload, headers
        )

    # ─── Administrative sweeps ───────────────────────────────────────────────

    def advance_epoch(self, headers):
        """Advance the system epoch. The sweep takes no request body."""
        return self._request("POST", f"{PREFIX}/ops-runs", None, headers)

    def set_clock(self, to_iso8601, headers):
        """Set the logical clock used by every deadline, window and recency rule."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
