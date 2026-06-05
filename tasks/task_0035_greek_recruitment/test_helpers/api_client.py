"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Chapters (PRD §3.1) -------------------------------------------------
    def create_chapter(self, payload, headers):
        return self._request("POST", "/rush/chapters", payload, headers)

    def get_chapter(self, chapter_id, headers):
        return self._request("GET", f"/rush/chapters/{chapter_id}", headers=headers)

    def list_chapters(self, headers, params=None):
        return self._request("GET", "/rush/chapters", headers=headers, params=params)

    def update_chapter(self, chapter_id, payload, headers):
        return self._request("PUT", f"/rush/chapters/{chapter_id}", payload, headers)

    def list_chapter_parties(self, chapter_id, headers, params=None):
        return self._request(
            "GET", f"/rush/chapters/{chapter_id}/parties", headers=headers, params=params
        )

    def list_chapter_risk_incidents(self, chapter_id, headers, params=None):
        return self._request(
            "GET",
            f"/rush/chapters/{chapter_id}/risk-incidents",
            headers=headers,
            params=params,
        )

    def list_chapter_dues_ledger(self, chapter_id, headers, params=None):
        return self._request(
            "GET",
            f"/rush/chapters/{chapter_id}/dues-ledger",
            headers=headers,
            params=params,
        )

    def list_chapter_preferences(self, chapter_id, headers, params=None):
        return self._request(
            "GET",
            f"/rush/chapters/{chapter_id}/preferences",
            headers=headers,
            params=params,
        )

    # --- PNMs (PRD §3.1) -----------------------------------------------------
    def register_pnm(self, payload, headers):
        return self._request("POST", "/rush/pnms/register", payload, headers)

    def get_pnm(self, pnm_id, headers):
        return self._request("GET", f"/rush/pnms/{pnm_id}", headers=headers)

    def list_pnms(self, headers, params=None):
        return self._request("GET", "/rush/pnms", headers=headers, params=params)

    def activate_pnm(self, pnm_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/pnms/{pnm_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_pnm(self, pnm_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/pnms/{pnm_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    def list_pnm_invitations(self, pnm_id, headers, params=None):
        return self._request(
            "GET", f"/rush/pnms/{pnm_id}/invitations", headers=headers, params=params
        )

    def list_pnm_preferences(self, pnm_id, headers, params=None):
        return self._request(
            "GET", f"/rush/pnms/{pnm_id}/preferences", headers=headers, params=params
        )

    def list_pnm_bid_matches(self, pnm_id, headers, params=None):
        return self._request(
            "GET", f"/rush/pnms/{pnm_id}/bid-matches", headers=headers, params=params
        )

    def list_pnms_legacy_of(self, chapter_id, headers, params=None):
        return self._request(
            "GET", f"/rush/pnms/legacy-of/{chapter_id}", headers=headers, params=params
        )

    # --- Rounds (PRD §3.1) ---------------------------------------------------
    def create_round(self, payload, headers):
        return self._request("POST", "/rush/rounds", payload, headers)

    def get_round(self, round_id, headers):
        return self._request("GET", f"/rush/rounds/{round_id}", headers=headers)

    def list_rounds(self, headers, params=None):
        return self._request("GET", "/rush/rounds", headers=headers, params=params)

    def advance_round(self, round_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/rounds/{round_id}/advance",
            payload if payload is not None else {},
            headers,
        )

    def list_round_parties(self, round_id, headers, params=None):
        return self._request(
            "GET", f"/rush/rounds/{round_id}/parties", headers=headers, params=params
        )

    def list_round_preferences(self, round_id, headers, params=None):
        return self._request(
            "GET", f"/rush/rounds/{round_id}/preferences", headers=headers, params=params
        )

    def list_round_bid_matches(self, round_id, headers, params=None):
        return self._request(
            "GET", f"/rush/rounds/{round_id}/bid-matches", headers=headers, params=params
        )

    # --- Parties (PRD §3.2) --------------------------------------------------
    def create_party(self, payload, headers):
        return self._request("POST", "/rush/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/rush/parties/{party_id}", headers=headers)

    def open_party(self, party_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/parties/{party_id}/open",
            payload if payload is not None else {},
            headers,
        )

    def complete_party(self, party_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/parties/{party_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_party(self, party_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/parties/{party_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    def list_party_invitations(self, party_id, headers, params=None):
        return self._request(
            "GET", f"/rush/parties/{party_id}/invitations", headers=headers, params=params
        )

    def list_party_risk_incidents(self, party_id, headers, params=None):
        return self._request(
            "GET",
            f"/rush/parties/{party_id}/risk-incidents",
            headers=headers,
            params=params,
        )

    # --- Invitations (PRD §3.3) ----------------------------------------------
    def create_invitation(self, payload, headers):
        return self._request("POST", "/rush/invitations", payload, headers)

    def get_invitation(self, invitation_id, headers):
        return self._request(
            "GET", f"/rush/invitations/{invitation_id}", headers=headers
        )

    def accept_invitation(self, invitation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/invitations/{invitation_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def decline_invitation(self, invitation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/invitations/{invitation_id}/decline",
            payload if payload is not None else {},
            headers,
        )

    # --- Preferences (PRD §3.4) ----------------------------------------------
    def create_preference(self, payload, headers):
        return self._request("POST", "/rush/preferences", payload, headers)

    def get_preference(self, preference_id, headers):
        return self._request(
            "GET", f"/rush/preferences/{preference_id}", headers=headers
        )

    # --- BidMatches (PRD §3.5, §3.6) -----------------------------------------
    def create_bid_match(self, payload, headers):
        return self._request("POST", "/rush/bid-matches", payload, headers)

    def get_bid_match(self, bid_match_id, headers):
        return self._request(
            "GET", f"/rush/bid-matches/{bid_match_id}", headers=headers
        )

    def list_bid_matches(self, headers, params=None):
        return self._request("GET", "/rush/bid-matches", headers=headers, params=params)

    def list_bid_match_dues_ledger_entries(self, bid_match_id, headers, params=None):
        return self._request(
            "GET",
            f"/rush/bid-matches/{bid_match_id}/dues-ledger-entries",
            headers=headers,
            params=params,
        )

    def accept_bid_match(self, bid_match_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/bid-matches/{bid_match_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def rescind_bid_match(self, bid_match_id, payload, headers):
        return self._request(
            "POST",
            f"/rush/bid-matches/{bid_match_id}/rescind",
            payload,
            headers,
        )

    def decline_bid_match(self, bid_match_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/bid-matches/{bid_match_id}/decline",
            payload if payload is not None else {},
            headers,
        )

    # --- RiskIncidents (PRD §3.8) --------------------------------------------
    def create_risk_incident(self, payload, headers):
        return self._request("POST", "/rush/risk-incidents", payload, headers)

    def get_risk_incident(self, risk_incident_id, headers):
        return self._request(
            "GET", f"/rush/risk-incidents/{risk_incident_id}", headers=headers
        )

    def dismiss_risk_incident(self, risk_incident_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rush/risk-incidents/{risk_incident_id}/dismiss",
            payload if payload is not None else {},
            headers,
        )

    # --- Test-driving clock (PRD §3.9) ---------------------------------------
    def set_clock(self, payload, headers):
        return self._request(
            "POST", "/rush/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
