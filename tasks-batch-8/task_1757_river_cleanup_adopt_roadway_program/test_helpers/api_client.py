"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Groups ---
    def create_group(self, payload, headers):
        return self._request("POST", "/program/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/program/groups/{group_id}", headers=headers)

    # --- Segments ---
    def create_segment(self, payload, headers):
        return self._request("POST", "/program/segments", payload, headers)

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"/program/segments/{segment_id}", headers=headers)

    def list_segments(self, headers, params=None):
        return self._request("GET", "/program/segments", headers=headers, params=params)

    # --- Agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/program/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/program/agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", "/program/agreements", headers=headers, params=params
        )

    def review_decision(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/program/agreements/{agreement_id}/review-decision",
            payload, headers,
        )

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request(
            "PATCH", f"/program/agreements/{agreement_id}", payload, headers
        )

    def suspend_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/program/agreements/{agreement_id}/suspend", payload, headers
        )

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/program/agreements/{agreement_id}/terminate", payload, headers
        )

    def renewal_request(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/program/agreements/{agreement_id}/renewal-request",
            payload or {}, headers,
        )

    def renewal_decision(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/program/agreements/{agreement_id}/renewal-decision",
            payload, headers,
        )

    # --- Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/program/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/program/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/program/events", headers=headers, params=params)

    def edit_event(self, event_id, payload, headers):
        return self._request("PATCH", f"/program/events/{event_id}", payload, headers)

    def record_briefing(self, event_id, payload, headers):
        return self._request(
            "POST", f"/program/events/{event_id}/briefing", payload, headers
        )

    def postpone_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/program/events/{event_id}/postpone", payload, headers
        )

    def cancel_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/program/events/{event_id}/cancel", payload, headers
        )

    def submit_debris_report(self, event_id, payload, headers):
        return self._request(
            "POST", f"/program/events/{event_id}/debris-report", payload, headers
        )

    def list_event_debris_reports(self, event_id, headers):
        return self._request(
            "GET", f"/program/events/{event_id}/debris-reports", headers=headers
        )

    # --- Supplies ---
    def issue_supplies(self, event_id, payload, headers):
        return self._request(
            "POST", f"/program/events/{event_id}/supplies", payload, headers
        )

    def list_supplies(self, headers, params=None):
        return self._request("GET", "/program/supplies", headers=headers, params=params)

    def get_supply(self, supply_id, headers):
        return self._request("GET", f"/program/supplies/{supply_id}", headers=headers)

    def return_supplies(self, supply_id, payload, headers):
        return self._request(
            "POST", f"/program/supplies/{supply_id}/return", payload, headers
        )

    # --- Depots ---
    def create_depot(self, payload, headers):
        return self._request("POST", "/program/depots", payload, headers)

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"/program/depots/{depot_id}", headers=headers)

    # --- Waivers ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/program/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/program/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/program/waivers", headers=headers, params=params)

    def revoke_waiver(self, waiver_id, headers):
        return self._request(
            "POST", f"/program/waivers/{waiver_id}/revoke", {}, headers
        )

    # --- Hazards ---
    def create_hazard(self, payload, headers):
        return self._request("POST", "/program/hazards", payload, headers)

    def get_hazard(self, hazard_id, headers):
        return self._request("GET", f"/program/hazards/{hazard_id}", headers=headers)

    def list_hazards(self, headers, params=None):
        return self._request("GET", "/program/hazards", headers=headers, params=params)

    def acknowledge_hazard(self, hazard_id, headers):
        return self._request(
            "POST", f"/program/hazards/{hazard_id}/acknowledge", {}, headers
        )

    def resolve_hazard(self, hazard_id, payload, headers):
        return self._request(
            "POST", f"/program/hazards/{hazard_id}/resolve", payload, headers
        )

    # --- Signs ---
    def request_sign(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/program/agreements/{agreement_id}/signs", payload, headers
        )

    def list_agreement_signs(self, agreement_id, headers):
        return self._request(
            "GET", f"/program/agreements/{agreement_id}/signs", headers=headers
        )

    def install_sign(self, sign_id, headers):
        return self._request("POST", f"/program/signs/{sign_id}/install", {}, headers)

    # --- Metrics ---
    def get_metrics(self, headers):
        return self._request("GET", "/program/metrics", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
