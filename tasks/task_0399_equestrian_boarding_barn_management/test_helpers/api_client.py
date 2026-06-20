"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Owner & deposit ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def adjust_deposit(self, owner_id, payload, headers):
        return self._request(
            "POST", f"/owners/{owner_id}/deposit", payload, headers
        )

    # ---- LiabilityWaiver (sub-resource of Owner) ----
    def create_waiver(self, owner_id, headers, payload=None):
        return self._request(
            "POST", f"/owners/{owner_id}/waivers", payload if payload is not None else {}, headers
        )

    def list_waivers(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/owners/{owner_id}/waivers", headers=headers, params=params
        )

    def sign_waiver(self, owner_id, waiver_id, headers, payload=None):
        return self._request(
            "POST",
            f"/owners/{owner_id}/waivers/{waiver_id}/sign",
            payload if payload is not None else {},
            headers,
        )

    # ---- Stall ----
    def create_stall(self, payload, headers):
        return self._request("POST", "/stalls", payload, headers)

    def get_stall(self, stall_id, headers):
        return self._request("GET", f"/stalls/{stall_id}", headers=headers)

    def list_stall_boarding_agreements(self, stall_id, headers, params=None):
        return self._request(
            "GET", f"/stalls/{stall_id}/boarding-agreements", headers=headers, params=params
        )

    def list_stall_turnouts(self, stall_id, headers, params=None):
        return self._request(
            "GET", f"/stalls/{stall_id}/turnouts", headers=headers, params=params
        )

    # ---- Horse ----
    def create_horse(self, payload, headers):
        return self._request("POST", "/horses", payload, headers)

    def get_horse(self, horse_id, headers):
        return self._request("GET", f"/horses/{horse_id}", headers=headers)

    def list_owner_horses(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/owners/{owner_id}/horses", headers=headers, params=params
        )

    def list_horse_boarding_agreements(self, horse_id, headers, params=None):
        return self._request(
            "GET", f"/horses/{horse_id}/boarding-agreements", headers=headers, params=params
        )

    def list_horse_lessons(self, horse_id, headers, params=None):
        return self._request(
            "GET", f"/horses/{horse_id}/lessons", headers=headers, params=params
        )

    def list_horse_service_visits(self, horse_id, headers, params=None):
        return self._request(
            "GET", f"/horses/{horse_id}/service-visits", headers=headers, params=params
        )

    def list_horse_show_entries(self, horse_id, headers, params=None):
        return self._request(
            "GET", f"/horses/{horse_id}/show-entries", headers=headers, params=params
        )

    def list_horse_turnouts(self, horse_id, headers, params=None):
        return self._request(
            "GET", f"/horses/{horse_id}/turnouts", headers=headers, params=params
        )

    # ---- BoardingAgreement ----
    def create_boarding_agreement(self, payload, headers):
        return self._request("POST", "/boarding-agreements", payload, headers)

    def transition_boarding_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/boarding-agreements/{agreement_id}/transition", payload, headers
        )

    # ---- Lesson ----
    def create_lesson(self, payload, headers):
        return self._request("POST", "/lessons", payload, headers)

    def transition_lesson(self, lesson_id, payload, headers):
        return self._request(
            "POST", f"/lessons/{lesson_id}/transition", payload, headers
        )

    # ---- ServiceVisit ----
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/service-visits", payload, headers)

    def transition_service_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/service-visits/{visit_id}/transition", payload, headers
        )

    # ---- ShowEntry ----
    def create_show_entry(self, payload, headers):
        return self._request("POST", "/show-entries", payload, headers)

    def transition_show_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/show-entries/{entry_id}/transition", payload, headers
        )

    # ---- TurnoutAssignment ----
    def create_turnout(self, payload, headers):
        return self._request("POST", "/turnout-assignments", payload, headers)

    def transition_turnout(self, turnout_id, payload, headers):
        return self._request(
            "POST", f"/turnout-assignments/{turnout_id}/transition", payload, headers
        )

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_owner_invoices(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/owners/{owner_id}/invoices", headers=headers, params=params
        )

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/transition", payload, headers
        )


api_client = ApiClient()
