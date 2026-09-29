"""API client: one method per endpoint defined in the PRD.

Every method returns the raw ``requests.Response`` so tests can assert both the
HTTP status code and the response envelope.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/salt"


class ApiClient(GenericApiClient):
    # ── logical compliance clock ──────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── taxpayer groups ───────────────────────────────────────────────────
    def create_group(self, payload, headers):
        return self._request("POST", f"{PREFIX}/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"{PREFIX}/groups/{group_id}", headers=headers)

    def list_groups(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/groups", headers=headers, params=params)

    # ── member entities ───────────────────────────────────────────────────
    def create_legal_entity(self, group_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/groups/{group_id}/legal-entities", payload, headers
        )

    def get_legal_entity(self, legal_entity_id, headers):
        return self._request(
            "GET", f"{PREFIX}/legal-entities/{legal_entity_id}", headers=headers
        )

    def list_group_legal_entities(self, group_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/groups/{group_id}/legal-entities",
            headers=headers, params=params,
        )

    # ── state registrations ───────────────────────────────────────────────
    def create_registration(self, group_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/groups/{group_id}/registrations", payload, headers
        )

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/registrations/{registration_id}", headers=headers
        )

    def list_group_registrations(self, group_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/groups/{group_id}/registrations",
            headers=headers, params=params,
        )

    def update_registration(self, registration_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/registrations/{registration_id}", payload, headers
        )

    def evaluate_nexus(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/evaluate-nexus",
            payload, headers,
        )

    def complete_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/complete-registration",
            payload, headers,
        )

    def withdraw_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/withdraw", payload, headers
        )

    def roll_filing_calendar(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/roll-filing-calendar",
            payload, headers,
        )

    # ── activity records ──────────────────────────────────────────────────
    def create_activity_record(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/activity-records",
            payload, headers,
        )

    def get_activity_record(self, activity_record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/activity-records/{activity_record_id}", headers=headers
        )

    def list_activity_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/activity-records", headers=headers, params=params
        )

    # ── filing elections ──────────────────────────────────────────────────
    def create_election(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/elections", payload, headers
        )

    def get_election(self, election_id, headers):
        return self._request("GET", f"{PREFIX}/elections/{election_id}", headers=headers)

    def list_registration_elections(self, registration_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/registrations/{registration_id}/elections",
            headers=headers, params=params,
        )

    def revoke_election(self, election_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/elections/{election_id}/revoke", payload, headers
        )

    def reinstate_election(self, election_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/elections/{election_id}/reinstate", payload, headers
        )

    # ── state returns ─────────────────────────────────────────────────────
    def create_filing(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/filings", payload, headers
        )

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"{PREFIX}/filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/filings", headers=headers, params=params)

    def compute_factors(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/compute-factors", payload, headers
        )

    def lock_factors(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/lock-factors", payload, headers
        )

    def submit_review(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/submit-review", payload, headers
        )

    def approve_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/approve", payload, headers
        )

    def reject_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/reject", payload, headers
        )

    def file_filing(self, filing_id, payload, headers):
        return self._request("POST", f"{PREFIX}/filings/{filing_id}/file", payload, headers)

    def amend_filing(self, filing_id, payload, headers):
        return self._request("POST", f"{PREFIX}/filings/{filing_id}/amend", payload, headers)

    def claim_refund(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/claim-refund", payload, headers
        )

    def list_filing_factors(self, filing_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/filings/{filing_id}/factors", headers=headers, params=params
        )

    # ── modifications ─────────────────────────────────────────────────────
    def create_modification(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/modifications", payload, headers
        )

    def list_filing_modifications(self, filing_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/filings/{filing_id}/modifications",
            headers=headers, params=params,
        )

    # ── credit claims ─────────────────────────────────────────────────────
    def create_credit_claim(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/credit-claims", payload, headers
        )

    def get_credit_claim(self, credit_claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/credit-claims/{credit_claim_id}", headers=headers
        )

    def list_filing_credit_claims(self, filing_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/filings/{filing_id}/credit-claims",
            headers=headers, params=params,
        )

    # ── estimated payments ────────────────────────────────────────────────
    def create_payment(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/payments", payload, headers
        )

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{PREFIX}/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payments", headers=headers, params=params)

    def apply_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/payments/{payment_id}/apply", payload, headers
        )

    def unapply_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/payments/{payment_id}/unapply", payload, headers
        )

    # ── extension requests ────────────────────────────────────────────────
    def create_extension(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/extensions", payload, headers
        )

    def list_filing_extensions(self, filing_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/filings/{filing_id}/extensions",
            headers=headers, params=params,
        )

    def acknowledge_extension(self, extension_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/extensions/{extension_id}/acknowledge", payload, headers
        )

    # ── notices ───────────────────────────────────────────────────────────
    def create_notice(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/filings/{filing_id}/notices", payload, headers
        )

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"{PREFIX}/notices/{notice_id}", headers=headers)

    def list_filing_notices(self, filing_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/filings/{filing_id}/notices", headers=headers, params=params
        )

    def respond_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/notices/{notice_id}/respond", payload, headers
        )

    def request_notice_info(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/notices/{notice_id}/request-info", payload, headers
        )

    def appeal_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/notices/{notice_id}/appeal", payload, headers
        )

    def decide_notice_appeal(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/notices/{notice_id}/appeal-decision", payload, headers
        )

    def close_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/notices/{notice_id}/close", payload, headers
        )

    # ── voluntary disclosure agreements ───────────────────────────────────
    def create_vda_agreement(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/vda-agreements",
            payload, headers,
        )

    def get_vda_agreement(self, vda_id, headers):
        return self._request("GET", f"{PREFIX}/vda-agreements/{vda_id}", headers=headers)

    def list_vda_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/vda-agreements", headers=headers, params=params
        )

    def submit_vda_agreement(self, vda_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vda-agreements/{vda_id}/submit", payload, headers
        )

    def execute_vda_agreement(self, vda_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vda-agreements/{vda_id}/execute", payload, headers
        )

    def withdraw_vda_agreement(self, vda_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vda-agreements/{vda_id}/withdraw", payload, headers
        )


api_client = ApiClient()
