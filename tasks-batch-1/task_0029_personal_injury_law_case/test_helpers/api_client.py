"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clients (PRD §3.1) ────────────────────────────────────────
    def register_client(self, payload, headers):
        return self._request("POST", "/clients/register", payload, headers)

    def sign_retainer(self, client_id, headers, payload=None):
        return self._request(
            "POST",
            f"/clients/{client_id}/sign-retainer",
            payload if payload is not None else {},
            headers,
        )

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    # ─── Cases (PRD §3.1, §3.3, §3.8, §3.9) ────────────────────────
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def activate_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/cases/{case_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def abandon_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/cases/{case_id}/abandon",
            payload if payload is not None else {},
            headers,
        )

    def file_suit(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/cases/{case_id}/file-suit",
            payload if payload is not None else {},
            headers,
        )

    def close_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/cases/{case_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def get_damages_summary(self, case_id, headers):
        return self._request(
            "GET", f"/cases/{case_id}/damages-summary", headers=headers
        )

    # ─── Medical providers (PRD §3.2) ──────────────────────────────
    def register_provider(self, payload, headers):
        return self._request("POST", "/medical-providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/medical-providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request(
            "GET", "/medical-providers", headers=headers, params=params
        )

    # ─── Medical records requests (PRD §3.2) ───────────────────────
    def create_records_request(self, payload, headers):
        return self._request("POST", "/medical-records-requests", payload, headers)

    def get_records_request(self, mrr_id, headers):
        return self._request(
            "GET", f"/medical-records-requests/{mrr_id}", headers=headers
        )

    def list_records_requests(self, headers, params=None):
        return self._request(
            "GET", "/medical-records-requests", headers=headers, params=params
        )

    def receive_records_request(self, mrr_id, headers, payload=None):
        return self._request(
            "POST",
            f"/medical-records-requests/{mrr_id}/receive",
            payload if payload is not None else {},
            headers,
        )

    def review_records_request(self, mrr_id, headers, payload=None):
        return self._request(
            "POST",
            f"/medical-records-requests/{mrr_id}/review",
            payload if payload is not None else {},
            headers,
        )

    def reject_records_request(self, mrr_id, headers, payload=None):
        return self._request(
            "POST",
            f"/medical-records-requests/{mrr_id}/reject",
            payload if payload is not None else {},
            headers,
        )

    # ─── Damages items (PRD §3.3) ──────────────────────────────────
    def create_damages_item(self, payload, headers):
        return self._request("POST", "/damages-items", payload, headers)

    def get_damages_item(self, item_id, headers):
        return self._request("GET", f"/damages-items/{item_id}", headers=headers)

    def list_damages_items(self, headers, params=None):
        return self._request("GET", "/damages-items", headers=headers, params=params)

    def include_damages_item(self, item_id, headers, payload=None):
        return self._request(
            "POST",
            f"/damages-items/{item_id}/include",
            payload if payload is not None else {},
            headers,
        )

    def exclude_damages_item(self, item_id, headers, payload=None):
        return self._request(
            "POST",
            f"/damages-items/{item_id}/exclude",
            payload if payload is not None else {},
            headers,
        )

    # ─── Medical liens (PRD §3.7) ──────────────────────────────────
    def create_lien(self, payload, headers):
        return self._request("POST", "/medical-liens", payload, headers)

    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/medical-liens/{lien_id}", headers=headers)

    def list_liens(self, headers, params=None):
        return self._request("GET", "/medical-liens", headers=headers, params=params)

    def negotiate_lien(self, lien_id, headers, payload=None):
        return self._request(
            "POST",
            f"/medical-liens/{lien_id}/negotiate",
            payload if payload is not None else {},
            headers,
        )

    def agree_lien(self, lien_id, payload, headers):
        return self._request(
            "POST", f"/medical-liens/{lien_id}/agree", payload, headers
        )

    def dispute_lien(self, lien_id, headers, payload=None):
        return self._request(
            "POST",
            f"/medical-liens/{lien_id}/dispute",
            payload if payload is not None else {},
            headers,
        )

    def resume_lien(self, lien_id, headers, payload=None):
        return self._request(
            "POST",
            f"/medical-liens/{lien_id}/resume-negotiation",
            payload if payload is not None else {},
            headers,
        )

    # ─── Demand letters (PRD §3.4) ─────────────────────────────────
    def create_demand_letter(self, payload, headers):
        return self._request("POST", "/demand-letters", payload, headers)

    def get_demand_letter(self, dl_id, headers):
        return self._request("GET", f"/demand-letters/{dl_id}", headers=headers)

    def list_demand_letters(self, headers, params=None):
        return self._request("GET", "/demand-letters", headers=headers, params=params)

    def send_demand_letter(self, dl_id, headers, payload=None):
        return self._request(
            "POST",
            f"/demand-letters/{dl_id}/send",
            payload if payload is not None else {},
            headers,
        )

    def acknowledge_demand_letter(self, dl_id, headers, payload=None):
        return self._request(
            "POST",
            f"/demand-letters/{dl_id}/acknowledge",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_demand_letter(self, dl_id, headers, payload=None):
        return self._request(
            "POST",
            f"/demand-letters/{dl_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ─── Settlement offers (PRD §3.5, §3.6) ────────────────────────
    def create_offer(self, payload, headers):
        return self._request("POST", "/settlement-offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/settlement-offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request(
            "GET", "/settlement-offers", headers=headers, params=params
        )

    def accept_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/settlement-offers/{offer_id}/accept", payload, headers
        )

    def reject_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST",
            f"/settlement-offers/{offer_id}/reject",
            payload if payload is not None else {},
            headers,
        )

    # ─── Court events (PRD §3.8) ───────────────────────────────────
    def create_court_event(self, payload, headers):
        return self._request("POST", "/court-events", payload, headers)

    def get_court_event(self, event_id, headers):
        return self._request("GET", f"/court-events/{event_id}", headers=headers)

    def list_court_events(self, headers, params=None):
        return self._request("GET", "/court-events", headers=headers, params=params)

    def mark_court_event_occurred(self, event_id, headers, payload=None):
        return self._request(
            "POST",
            f"/court-events/{event_id}/mark-occurred",
            payload if payload is not None else {},
            headers,
        )

    def cancel_court_event(self, event_id, headers, payload=None):
        return self._request(
            "POST",
            f"/court-events/{event_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Disbursements (PRD §3.7) ──────────────────────────────────
    def get_disbursement(self, disb_id, headers):
        return self._request("GET", f"/disbursements/{disb_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    def release_disbursement(self, disb_id, payload, headers):
        return self._request(
            "POST", f"/disbursements/{disb_id}/release", payload, headers
        )

    # ─── System clock (PRD §2.10) ──────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
