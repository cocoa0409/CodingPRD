"""API client: one method per endpoint defined in the PRD.

Collections are mounted flat at the root of the service; there is no nesting in
URL paths and no API prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- creditors ----------------
    def create_creditor(self, payload, headers):
        return self._request("POST", "/creditors", payload, headers)

    # ---------------- debtors ----------------
    def create_debtor(self, payload, headers):
        return self._request("POST", "/debtors", payload, headers)

    def get_debtor(self, debtor_id, headers):
        return self._request("GET", f"/debtors/{debtor_id}", headers=headers)

    def skip_trace(self, debtor_id, payload, headers):
        return self._request(
            "POST", f"/debtors/{debtor_id}/skip-trace", payload, headers
        )

    # ---------------- judgments ----------------
    def create_judgment(self, payload, headers):
        return self._request("POST", "/judgments", payload, headers)

    def list_judgments(self, headers, params=None):
        return self._request("GET", "/judgments", params or {}, headers)

    def get_judgment(self, judgment_id, headers):
        return self._request("GET", f"/judgments/{judgment_id}", headers=headers)

    def get_payoff(self, judgment_id, headers, params=None):
        return self._request(
            "GET", f"/judgments/{judgment_id}/payoff", params or {}, headers
        )

    def renew_judgment(self, judgment_id, headers):
        return self._request("POST", f"/judgments/{judgment_id}/renew", {}, headers)

    # ---------------- county filings ----------------
    def create_county_filing(self, payload, headers):
        return self._request("POST", "/county-filings", payload, headers)

    def list_county_filings(self, headers, params=None):
        return self._request("GET", "/county-filings", params or {}, headers)

    def get_county_filing(self, county_filing_id, headers):
        return self._request(
            "GET", f"/county-filings/{county_filing_id}", headers=headers
        )

    def submit_county_filing(self, county_filing_id, headers):
        return self._request(
            "POST", f"/county-filings/{county_filing_id}/submit", {}, headers
        )

    def adjudicate_county_filing(self, county_filing_id, payload, headers):
        return self._request(
            "POST", f"/county-filings/{county_filing_id}/adjudicate", payload, headers
        )

    # ---------------- asset findings ----------------
    def create_asset_finding(self, payload, headers):
        return self._request("POST", "/asset-findings", payload, headers)

    def list_asset_findings(self, headers, params=None):
        return self._request("GET", "/asset-findings", params or {}, headers)

    def get_asset_finding(self, asset_finding_id, headers):
        return self._request(
            "GET", f"/asset-findings/{asset_finding_id}", headers=headers
        )

    def verify_asset_finding(self, asset_finding_id, headers):
        return self._request(
            "POST", f"/asset-findings/{asset_finding_id}/verify", {}, headers
        )

    # ---------------- enforcement actions ----------------
    def create_enforcement_action(self, payload, headers):
        return self._request("POST", "/enforcement-actions", payload, headers)

    def list_enforcement_actions(self, headers, params=None):
        return self._request("GET", "/enforcement-actions", params or {}, headers)

    def get_enforcement_action(self, enforcement_action_id, headers):
        return self._request(
            "GET", f"/enforcement-actions/{enforcement_action_id}", headers=headers
        )

    def request_writ(self, enforcement_action_id, headers):
        return self._request(
            "POST",
            f"/enforcement-actions/{enforcement_action_id}/request-writ",
            {},
            headers,
        )

    def serve_writ(self, enforcement_action_id, served_on, headers):
        return self._request(
            "POST",
            f"/enforcement-actions/{enforcement_action_id}/serve",
            {"served_on": served_on},
            headers,
        )

    def release_writ(self, enforcement_action_id, headers):
        return self._request(
            "POST",
            f"/enforcement-actions/{enforcement_action_id}/release",
            {},
            headers,
        )

    # ---------------- exemption claims ----------------
    def create_exemption_claim(self, payload, headers):
        return self._request("POST", "/exemption-claims", payload, headers)

    def list_exemption_claims(self, headers, params=None):
        return self._request("GET", "/exemption-claims", params or {}, headers)

    def get_exemption_claim(self, exemption_claim_id, headers):
        return self._request(
            "GET", f"/exemption-claims/{exemption_claim_id}", headers=headers
        )

    def oppose_exemption_claim(self, exemption_claim_id, headers):
        return self._request(
            "POST", f"/exemption-claims/{exemption_claim_id}/oppose", {}, headers
        )

    def rule_exemption_claim(self, exemption_claim_id, outcome, headers):
        return self._request(
            "POST",
            f"/exemption-claims/{exemption_claim_id}/rule",
            {"outcome": outcome},
            headers,
        )

    # ---------------- debtor examinations ----------------
    def create_examination(self, payload, headers):
        return self._request("POST", "/debtor-examinations", payload, headers)

    def list_examinations(self, headers, params=None):
        return self._request("GET", "/debtor-examinations", params or {}, headers)

    def get_examination(self, examination_id, headers):
        return self._request(
            "GET", f"/debtor-examinations/{examination_id}", headers=headers
        )

    def issue_subpoena(self, examination_id, payload, headers):
        return self._request(
            "POST", f"/debtor-examinations/{examination_id}/subpoena", payload, headers
        )

    def serve_examination(self, examination_id, served_on, headers):
        return self._request(
            "POST",
            f"/debtor-examinations/{examination_id}/serve",
            {"served_on": served_on},
            headers,
        )

    def record_examination_outcome(self, examination_id, payload, headers):
        return self._request(
            "POST",
            f"/debtor-examinations/{examination_id}/record-outcome",
            payload,
            headers,
        )

    # ---------------- settlement offers ----------------
    def create_settlement_offer(self, payload, headers):
        return self._request("POST", "/settlement-offers", payload, headers)

    def list_settlement_offers(self, headers, params=None):
        return self._request("GET", "/settlement-offers", params or {}, headers)

    def get_settlement_offer(self, settlement_offer_id, headers):
        return self._request(
            "GET", f"/settlement-offers/{settlement_offer_id}", headers=headers
        )

    def accept_settlement_offer(self, settlement_offer_id, headers):
        return self._request(
            "POST", f"/settlement-offers/{settlement_offer_id}/accept", {}, headers
        )

    def reject_settlement_offer(self, settlement_offer_id, headers):
        return self._request(
            "POST", f"/settlement-offers/{settlement_offer_id}/reject", {}, headers
        )

    # ---------------- installment agreements ----------------
    def list_installment_agreements(self, headers, params=None):
        return self._request("GET", "/installment-agreements", params or {}, headers)

    def get_installment_agreement(self, installment_agreement_id, headers):
        return self._request(
            "GET",
            f"/installment-agreements/{installment_agreement_id}",
            headers=headers,
        )

    def record_installment_miss(self, installment_agreement_id, headers):
        return self._request(
            "POST",
            f"/installment-agreements/{installment_agreement_id}/record-miss",
            {},
            headers,
        )

    def reinstate_installment_agreement(self, installment_agreement_id, headers):
        return self._request(
            "POST",
            f"/installment-agreements/{installment_agreement_id}/reinstate",
            {},
            headers,
        )

    # ---------------- payments ----------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", params or {}, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def reverse_payment(self, payment_id, reason, headers):
        return self._request(
            "POST", f"/payments/{payment_id}/reverse", {"reason": reason}, headers
        )


api_client = ApiClient()
