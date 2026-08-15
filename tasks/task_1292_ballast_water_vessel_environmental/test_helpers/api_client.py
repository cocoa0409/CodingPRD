"""API client: one method per endpoint defined in the PRD endpoint table."""
import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The per-test-server isolation kills and reboots the server before
        # every test. Disable HTTP keep-alive so this session-scoped client
        # can never reuse a pooled connection whose server end was just
        # SIGKILLed (the stale-socket RemoteDisconnected race).
        self.session.headers["Connection"] = "close"

    def _request(self, method, path, payload=None, headers=None, params=None):
        try:
            return super()._request(method, path, payload=payload,
                                    headers=headers, params=params)
        except requests.exceptions.ConnectionError:
            # The server is only ever killed between tests, never mid-test,
            # so a connection error means the request never reached a live
            # handler; one retry on a fresh connection is transparent for
            # idempotent and mutating requests alike.
            return super()._request(method, path, payload=payload,
                                    headers=headers, params=params)


    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Vessels ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/vessels", headers=headers, params=params)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    # --- Plans ---
    def create_plan(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/plans", payload, headers)

    def list_plans(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/plans", headers=headers, params=params)

    def get_plan(self, vessel_id, plan_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}/plans/{plan_id}", headers=headers)

    def submit_plan(self, vessel_id, plan_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/plans/{plan_id}/submit", headers=headers)

    def approve_plan(self, vessel_id, plan_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/plans/{plan_id}/approve", headers=headers)

    def withdraw_plan(self, vessel_id, plan_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/plans/{plan_id}/withdraw", headers=headers)

    # --- Voyages ---
    def create_voyage(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/voyages", payload, headers)

    def list_voyages(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/voyages", headers=headers, params=params)

    def get_voyage(self, vessel_id, voyage_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}/voyages/{voyage_id}", headers=headers)

    def depart_voyage(self, vessel_id, voyage_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/voyages/{voyage_id}/depart", headers=headers)

    def arrive_voyage(self, vessel_id, voyage_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/voyages/{voyage_id}/arrive", payload, headers)

    # --- Ballast Water Events ---
    def create_ballast_event(self, vessel_id, voyage_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/voyages/{voyage_id}/ballast-events", payload, headers
        )

    def list_ballast_events(self, vessel_id, voyage_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/voyages/{voyage_id}/ballast-events",
            headers=headers, params=params,
        )

    # --- Determinations ---
    def list_determinations(self, vessel_id, voyage_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/voyages/{voyage_id}/determinations",
            headers=headers, params=params,
        )

    def recompute_determination(self, vessel_id, voyage_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/voyages/{voyage_id}/determinations/recompute",
            headers=headers,
        )

    # --- Reports ---
    def list_reports(self, vessel_id, voyage_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/voyages/{voyage_id}/reports",
            headers=headers, params=params,
        )

    def submit_report(self, vessel_id, voyage_id, report_id, payload, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/reports/{report_id}/submit",
            payload, headers,
        )

    def acknowledge_report(self, vessel_id, voyage_id, report_id, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/reports/{report_id}/acknowledge",
            headers=headers,
        )

    def reject_report(self, vessel_id, voyage_id, report_id, payload, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/reports/{report_id}/reject",
            payload, headers,
        )

    # --- Sampling / Inspections ---
    def create_inspection(self, vessel_id, voyage_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/voyages/{voyage_id}/inspections", payload, headers
        )

    def list_inspections(self, vessel_id, voyage_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/voyages/{voyage_id}/inspections",
            headers=headers, params=params,
        )

    def evaluate_inspection(self, vessel_id, voyage_id, inspection_id, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/inspections/{inspection_id}/evaluate",
            headers=headers,
        )

    def close_inspection(self, vessel_id, voyage_id, inspection_id, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/inspections/{inspection_id}/close",
            headers=headers,
        )

    def reopen_inspection(self, vessel_id, voyage_id, inspection_id, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/inspections/{inspection_id}/reopen",
            headers=headers,
        )

    # --- Noncompliance ---
    def list_noncompliance(self, vessel_id, voyage_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/voyages/{voyage_id}/noncompliance",
            headers=headers, params=params,
        )

    def respond_noncompliance(self, vessel_id, voyage_id, record_id, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/noncompliance/{record_id}/respond",
            headers=headers,
        )

    def close_noncompliance(self, vessel_id, voyage_id, record_id, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/noncompliance/{record_id}/close",
            headers=headers,
        )

    # --- Deficiencies ---
    def list_deficiencies(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/deficiencies", headers=headers, params=params)

    def begin_rectification(self, vessel_id, deficiency_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/deficiencies/{deficiency_id}/begin-rectification",
            headers=headers,
        )

    def claim_rectified(self, vessel_id, deficiency_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/deficiencies/{deficiency_id}/claim-rectified",
            payload, headers,
        )

    def verify_deficiency(self, vessel_id, deficiency_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/deficiencies/{deficiency_id}/verify", headers=headers
        )

    def reject_verification(self, vessel_id, deficiency_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/deficiencies/{deficiency_id}/reject-verification",
            headers=headers,
        )

    # --- Record Books ---
    def create_record_book(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/record-books", payload, headers)

    def list_record_books(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/record-books", headers=headers, params=params)

    def create_record_book_entry(self, vessel_id, book_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/record-books/{book_id}/entries", payload, headers
        )

    def list_record_book_entries(self, vessel_id, book_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/record-books/{book_id}/entries",
            headers=headers, params=params,
        )

    def seal_record_book(self, vessel_id, book_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/record-books/{book_id}/seal", headers=headers
        )

    # --- Emissions ---
    def create_emissions_record(self, vessel_id, voyage_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/voyages/{voyage_id}/emissions", payload, headers
        )

    def list_emissions_records(self, vessel_id, voyage_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/voyages/{voyage_id}/emissions",
            headers=headers, params=params,
        )

    def evaluate_emissions(self, vessel_id, voyage_id, record_id, headers):
        return self._request(
            "POST",
            f"/vessels/{vessel_id}/voyages/{voyage_id}/emissions/{record_id}/evaluate",
            headers=headers,
        )

    # --- Drills ---
    def create_drill(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/drills", payload, headers)

    def list_drills(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/drills", headers=headers, params=params)

    def complete_drill(self, vessel_id, drill_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/drills/{drill_id}/complete", payload, headers
        )

    def cancel_drill(self, vessel_id, drill_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/drills/{drill_id}/cancel", headers=headers
        )

    # --- Enforcement ---
    def list_enforcement_cases(self, vessel_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/enforcement-cases", headers=headers, params=params
        )

    def submit_case_response(self, vessel_id, case_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/enforcement-cases/{case_id}/submit-response",
            headers=headers,
        )

    def close_case(self, vessel_id, case_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/enforcement-cases/{case_id}/close", payload, headers
        )

    def withdraw_case(self, vessel_id, case_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/enforcement-cases/{case_id}/withdraw", headers=headers
        )


api_client = ApiClient()
