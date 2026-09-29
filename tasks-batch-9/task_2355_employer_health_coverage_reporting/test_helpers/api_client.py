"""API client: one method per endpoint defined in the PRD (§4).

Every path is absolute and mounted under the ``/ale-reporting`` namespace, which
is a namespace rather than a collection: every entity owns a flat top-level
collection beneath it.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/ale-reporting"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Filing seasons
    # ------------------------------------------------------------------
    def create_filing_season(self, payload, headers):
        return self._request("POST", f"{BASE}/filing-seasons", payload, headers)

    def list_filing_seasons(self, headers, params=None):
        return self._request("GET", f"{BASE}/filing-seasons", headers=headers, params=params)

    def get_filing_season(self, season_id, headers):
        return self._request("GET", f"{BASE}/filing-seasons/{season_id}", headers=headers)

    def lock_filing_season(self, season_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/filing-seasons/{season_id}/lock", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Controlled groups
    # ------------------------------------------------------------------
    def create_controlled_group(self, payload, headers):
        return self._request("POST", f"{BASE}/controlled-groups", payload, headers)

    def list_controlled_groups(self, headers, params=None):
        return self._request("GET", f"{BASE}/controlled-groups", headers=headers, params=params)

    def get_controlled_group(self, group_id, headers):
        return self._request("GET", f"{BASE}/controlled-groups/{group_id}", headers=headers)

    def run_ale_determination(self, group_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/controlled-groups/{group_id}/ale-determination", payload, headers
        )

    def reopen_controlled_group(self, group_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/controlled-groups/{group_id}/reopen", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Group members
    # ------------------------------------------------------------------
    def create_group_member(self, payload, headers):
        return self._request("POST", f"{BASE}/group-members", payload, headers)

    def list_group_members(self, headers, params=None):
        return self._request("GET", f"{BASE}/group-members", headers=headers, params=params)

    def get_group_member(self, member_id, headers):
        return self._request("GET", f"{BASE}/group-members/{member_id}", headers=headers)

    def update_group_member(self, member_id, payload, headers):
        return self._request("PATCH", f"{BASE}/group-members/{member_id}", payload, headers)

    # ------------------------------------------------------------------
    # Monthly headcounts
    # ------------------------------------------------------------------
    def create_monthly_headcounts(self, payload, headers):
        return self._request("POST", f"{BASE}/monthly-headcounts", payload, headers)

    def list_monthly_headcounts(self, headers, params=None):
        return self._request("GET", f"{BASE}/monthly-headcounts", headers=headers, params=params)

    def get_monthly_headcount(self, headcount_id, headers):
        return self._request("GET", f"{BASE}/monthly-headcounts/{headcount_id}", headers=headers)

    # ------------------------------------------------------------------
    # Measurement cycles
    # ------------------------------------------------------------------
    def create_measurement_cycle(self, payload, headers):
        return self._request("POST", f"{BASE}/measurement-cycles", payload, headers)

    def list_measurement_cycles(self, headers, params=None):
        return self._request("GET", f"{BASE}/measurement-cycles", headers=headers, params=params)

    def get_measurement_cycle(self, cycle_id, headers):
        return self._request("GET", f"{BASE}/measurement-cycles/{cycle_id}", headers=headers)

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", f"{BASE}/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", f"{BASE}/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"{BASE}/employees/{employee_id}", headers=headers)

    def update_employee(self, employee_id, payload, headers):
        return self._request("PATCH", f"{BASE}/employees/{employee_id}", payload, headers)

    def recompute_employee_full_time(self, employee_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/employees/{employee_id}/full-time-recompute", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Hours records
    # ------------------------------------------------------------------
    def create_hours_records(self, payload, headers):
        return self._request("POST", f"{BASE}/hours-records", payload, headers)

    def list_hours_records(self, headers, params=None):
        return self._request("GET", f"{BASE}/hours-records", headers=headers, params=params)

    def get_hours_record(self, record_id, headers):
        return self._request("GET", f"{BASE}/hours-records/{record_id}", headers=headers)

    # ------------------------------------------------------------------
    # Employment events
    # ------------------------------------------------------------------
    def create_employment_event(self, payload, headers):
        return self._request("POST", f"{BASE}/employment-events", payload, headers)

    def list_employment_events(self, headers, params=None):
        return self._request("GET", f"{BASE}/employment-events", headers=headers, params=params)

    def get_employment_event(self, event_id, headers):
        return self._request("GET", f"{BASE}/employment-events/{event_id}", headers=headers)

    # ------------------------------------------------------------------
    # Coverage offers
    # ------------------------------------------------------------------
    def create_coverage_offer(self, payload, headers):
        return self._request("POST", f"{BASE}/coverage-offers", payload, headers)

    def list_coverage_offers(self, headers, params=None):
        return self._request("GET", f"{BASE}/coverage-offers", headers=headers, params=params)

    def get_coverage_offer(self, offer_id, headers):
        return self._request("GET", f"{BASE}/coverage-offers/{offer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Furnishing consents
    # ------------------------------------------------------------------
    def create_furnishing_consent(self, payload, headers):
        return self._request("POST", f"{BASE}/furnishing-consents", payload, headers)

    def list_furnishing_consents(self, headers, params=None):
        return self._request("GET", f"{BASE}/furnishing-consents", headers=headers, params=params)

    def get_furnishing_consent(self, consent_id, headers):
        return self._request("GET", f"{BASE}/furnishing-consents/{consent_id}", headers=headers)

    def grant_furnishing_consent(self, consent_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/furnishing-consents/{consent_id}/grant", payload or {}, headers
        )

    def withdraw_furnishing_consent(self, consent_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/furnishing-consents/{consent_id}/withdraw", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Forms 1095-C
    # ------------------------------------------------------------------
    def create_form_1095c(self, payload, headers):
        return self._request("POST", f"{BASE}/forms-1095c", payload, headers)

    def list_forms_1095c(self, headers, params=None):
        return self._request("GET", f"{BASE}/forms-1095c", headers=headers, params=params)

    def get_form_1095c(self, form_id, headers):
        return self._request("GET", f"{BASE}/forms-1095c/{form_id}", headers=headers)

    def regenerate_form_1095c(self, form_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/forms-1095c/{form_id}/regenerate", payload or {}, headers
        )

    def furnish_form_1095c(self, form_id, payload, headers):
        return self._request("POST", f"{BASE}/forms-1095c/{form_id}/furnish", payload, headers)

    # ------------------------------------------------------------------
    # Monthly coverage lines
    # ------------------------------------------------------------------
    def list_monthly_coverage_lines(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/monthly-coverage-lines", headers=headers, params=params
        )

    def get_monthly_coverage_line(self, line_id, headers):
        return self._request("GET", f"{BASE}/monthly-coverage-lines/{line_id}", headers=headers)

    # ------------------------------------------------------------------
    # Transmittals
    # ------------------------------------------------------------------
    def create_transmittal(self, payload, headers):
        return self._request("POST", f"{BASE}/transmittals", payload, headers)

    def list_transmittals(self, headers, params=None):
        return self._request("GET", f"{BASE}/transmittals", headers=headers, params=params)

    def get_transmittal(self, transmittal_id, headers):
        return self._request("GET", f"{BASE}/transmittals/{transmittal_id}", headers=headers)

    def attach_forms(self, transmittal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/transmittals/{transmittal_id}/attach-forms", payload, headers
        )

    def detach_form(self, transmittal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/transmittals/{transmittal_id}/detach-form", payload, headers
        )

    def build_transmittal(self, transmittal_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/transmittals/{transmittal_id}/build", payload or {}, headers
        )

    def transmit_transmittal(self, transmittal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/transmittals/{transmittal_id}/transmit", payload, headers
        )

    def record_agency_response(self, transmittal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/transmittals/{transmittal_id}/agency-response", payload, headers
        )

    def start_correction_cycle(self, transmittal_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/transmittals/{transmittal_id}/start-correction-cycle",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Transmittal errors
    # ------------------------------------------------------------------
    def create_transmittal_error(self, payload, headers):
        return self._request("POST", f"{BASE}/transmittal-errors", payload, headers)

    def list_transmittal_errors(self, headers, params=None):
        return self._request("GET", f"{BASE}/transmittal-errors", headers=headers, params=params)

    def get_transmittal_error(self, error_id, headers):
        return self._request("GET", f"{BASE}/transmittal-errors/{error_id}", headers=headers)

    def resolve_transmittal_error(self, error_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/transmittal-errors/{error_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Penalty notices
    # ------------------------------------------------------------------
    def create_penalty_notice(self, payload, headers):
        return self._request("POST", f"{BASE}/penalty-notices", payload, headers)

    def list_penalty_notices(self, headers, params=None):
        return self._request("GET", f"{BASE}/penalty-notices", headers=headers, params=params)

    def get_penalty_notice(self, notice_id, headers):
        return self._request("GET", f"{BASE}/penalty-notices/{notice_id}", headers=headers)

    def create_penalty_evidence(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/penalty-notices/{notice_id}/evidence", payload, headers
        )

    def recompute_penalty_notice(self, notice_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/penalty-notices/{notice_id}/recompute", payload or {}, headers
        )

    def reset_penalty_allocation(self, notice_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/penalty-notices/{notice_id}/allocation/reset", payload or {}, headers
        )

    def submit_penalty_response(self, notice_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/penalty-notices/{notice_id}/submit-response", payload or {}, headers
        )

    def record_agency_determination(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/penalty-notices/{notice_id}/agency-determination", payload, headers
        )

    # ------------------------------------------------------------------
    # Penalty evidence reads
    # ------------------------------------------------------------------
    def list_penalty_evidence(self, headers, params=None):
        return self._request("GET", f"{BASE}/penalty-evidence", headers=headers, params=params)

    def get_penalty_evidence(self, evidence_id, headers):
        return self._request("GET", f"{BASE}/penalty-evidence/{evidence_id}", headers=headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
