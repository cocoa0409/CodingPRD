"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; only PRD-specific endpoint methods
are declared here. The base _request() handles the HTTP envelope.
"""
import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # Per-test-server isolation restarts the server on the same port before
        # every test. A pooled keep-alive socket left over from a prior test now
        # points at a dead process, so its first reuse raises ConnectionError /
        # BadStatusLine. Send ``Connection: close`` so urllib3 never pools a
        # socket across a restart, and retry once to absorb a stale-socket hit
        # on the very first call after a reboot.
        merged = dict(headers or {})
        merged.setdefault("Connection", "close")
        try:
            return super()._request(method, path, payload, headers=merged, params=params)
        except requests.exceptions.ConnectionError:
            return super()._request(method, path, payload, headers=merged, params=params)

    # ---- Households ----
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    def patch_household(self, household_id, payload, headers):
        return self._request("PATCH", f"/households/{household_id}", payload, headers)

    def list_household_soft_credits(self, household_id, headers, params=None):
        return self._request(
            "GET", f"/households/{household_id}/soft-credits", headers=headers, params=params
        )

    # ---- Donors ----
    def create_donor(self, payload, headers):
        return self._request("POST", "/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/donors", headers=headers, params=params)

    def flag_lapsed_donor(self, donor_id, headers):
        return self._request("POST", f"/donors/{donor_id}/flag-lapsed", {}, headers)

    def reactivate_donor(self, donor_id, headers):
        return self._request("POST", f"/donors/{donor_id}/reactivate", {}, headers)

    def flag_active_donor(self, donor_id, headers):
        return self._request("POST", f"/donors/{donor_id}/flag-active", {}, headers)

    def archive_donor(self, donor_id, headers):
        return self._request("POST", f"/donors/{donor_id}/archive", {}, headers)

    # ---- Employers ----
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    # ---- Campaigns ----
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/open", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/close", {}, headers)

    # ---- Appeals ----
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    # ---- Pledges / Installments ----
    def create_pledge(self, payload, headers):
        return self._request("POST", "/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/pledges", headers=headers, params=params)

    def list_pledge_installments(self, pledge_id, headers, params=None):
        return self._request(
            "GET", f"/pledges/{pledge_id}/installments", headers=headers, params=params
        )

    def get_pledge_installment(self, installment_id, headers):
        return self._request("GET", f"/pledge-installments/{installment_id}", headers=headers)

    def list_all_pledge_installments(self, headers, params=None):
        return self._request("GET", "/pledge-installments", headers=headers, params=params)

    def evaluate_pledge_delinquency(self, pledge_id, headers):
        return self._request(
            "POST", f"/pledges/{pledge_id}/evaluate-delinquency", {}, headers
        )

    def cancel_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/pledges/{pledge_id}/cancel", payload, headers)

    # ---- Gifts ----
    def create_gift(self, payload, headers):
        return self._request("POST", "/gifts", payload, headers)

    def get_gift(self, gift_id, headers):
        return self._request("GET", f"/gifts/{gift_id}", headers=headers)

    def list_gifts(self, headers, params=None):
        return self._request("GET", "/gifts", headers=headers, params=params)

    def acknowledge_gift(self, gift_id, headers):
        return self._request("POST", f"/gifts/{gift_id}/acknowledge", {}, headers)

    def receipt_gift(self, gift_id, headers):
        return self._request("POST", f"/gifts/{gift_id}/receipt", {}, headers)

    def refund_gift(self, gift_id, payload, headers):
        return self._request("POST", f"/gifts/{gift_id}/refund", payload, headers)

    def list_gift_acknowledgements(self, gift_id, headers, params=None):
        return self._request(
            "GET", f"/gifts/{gift_id}/acknowledgements", headers=headers, params=params
        )

    def list_gift_soft_credits(self, gift_id, headers, params=None):
        return self._request(
            "GET", f"/gifts/{gift_id}/soft-credits", headers=headers, params=params
        )

    # ---- Soft credits ----
    def get_soft_credit(self, soft_credit_id, headers):
        return self._request("GET", f"/soft-credits/{soft_credit_id}", headers=headers)

    def list_soft_credits(self, headers, params=None):
        return self._request("GET", "/soft-credits", headers=headers, params=params)

    # ---- Match claims ----
    def create_match_claim(self, payload, headers):
        return self._request("POST", "/match-claims", payload, headers)

    def get_match_claim(self, claim_id, headers):
        return self._request("GET", f"/match-claims/{claim_id}", headers=headers)

    def list_match_claims(self, headers, params=None):
        return self._request("GET", "/match-claims", headers=headers, params=params)

    def approve_match_claim(self, claim_id, headers):
        return self._request("POST", f"/match-claims/{claim_id}/approve", {}, headers)

    def deny_match_claim(self, claim_id, headers):
        return self._request("POST", f"/match-claims/{claim_id}/deny", {}, headers)

    def pay_match_claim(self, claim_id, headers):
        return self._request("POST", f"/match-claims/{claim_id}/pay", {}, headers)

    # ---- Planned giving ----
    def create_planned_gift(self, payload, headers):
        return self._request("POST", "/planned-gifts", payload, headers)

    def get_planned_gift(self, planned_gift_id, headers):
        return self._request("GET", f"/planned-gifts/{planned_gift_id}", headers=headers)

    def list_planned_gifts(self, headers, params=None):
        return self._request("GET", "/planned-gifts", headers=headers, params=params)

    def confirm_planned_gift(self, planned_gift_id, headers):
        return self._request("POST", f"/planned-gifts/{planned_gift_id}/confirm", {}, headers)

    def realize_planned_gift(self, planned_gift_id, payload, headers):
        return self._request(
            "POST", f"/planned-gifts/{planned_gift_id}/realize", payload, headers
        )

    def lapse_planned_gift(self, planned_gift_id, headers):
        return self._request("POST", f"/planned-gifts/{planned_gift_id}/lapse", {}, headers)

    # ---- Acknowledgements (read) ----
    def get_acknowledgement(self, ack_id, headers):
        return self._request("GET", f"/acknowledgements/{ack_id}", headers=headers)

    def list_acknowledgements(self, headers, params=None):
        return self._request("GET", "/acknowledgements", headers=headers, params=params)

    # ---- Segments ----
    def create_segment(self, payload, headers):
        return self._request("POST", "/segments", payload, headers)

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"/segments/{segment_id}", headers=headers)

    def list_segment_members(self, segment_id, headers, params=None):
        return self._request(
            "GET", f"/segments/{segment_id}/members", headers=headers, params=params
        )

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
