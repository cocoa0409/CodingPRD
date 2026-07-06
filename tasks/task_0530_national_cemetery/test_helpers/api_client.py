"""API client: one method per endpoint defined in the PRD.

All resource paths are nested under /cemeteries/{cemeteryId}/... per the
endpoint table; the logical clock endpoint sits at /_clock/set_current_utc.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Cemetery ----
    def create_cemetery(self, payload, headers):
        return self._request("POST", "/cemeteries", payload, headers)

    def get_cemetery(self, cemetery_id, headers):
        return self._request(
            "GET", f"/cemeteries/{cemetery_id}", headers=headers
        )

    def list_cemeteries(self, headers, params=None):
        return self._request(
            "GET", "/cemeteries", headers=headers, params=params
        )

    # ---- Section ----
    def create_section(self, cemetery_id, payload, headers):
        return self._request(
            "POST", f"/cemeteries/{cemetery_id}/sections", payload, headers
        )

    def list_sections(self, cemetery_id, headers, params=None):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/sections",
            headers=headers,
            params=params,
        )

    def get_section(self, cemetery_id, section_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/sections/{section_id}",
            headers=headers,
        )

    # ---- Gravesite ----
    def create_gravesite(self, cemetery_id, section_id, payload, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/sections/{section_id}/gravesites",
            payload,
            headers,
        )

    def list_gravesites(self, cemetery_id, section_id, headers, params=None):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/sections/{section_id}/gravesites",
            headers=headers,
            params=params,
        )

    def get_gravesite(self, cemetery_id, section_id, gravesite_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/sections/{section_id}/gravesites/{gravesite_id}",
            headers=headers,
        )

    def decommission_gravesite(self, cemetery_id, section_id, gravesite_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/sections/{section_id}/gravesites/{gravesite_id}/decommission",
            headers=headers,
        )

    # ---- Niche ----
    def create_niche(self, cemetery_id, section_id, payload, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/sections/{section_id}/niches",
            payload,
            headers,
        )

    def list_niches(self, cemetery_id, section_id, headers, params=None):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/sections/{section_id}/niches",
            headers=headers,
            params=params,
        )

    def get_niche(self, cemetery_id, section_id, niche_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/sections/{section_id}/niches/{niche_id}",
            headers=headers,
        )

    # ---- BurialCase ----
    def create_burial_case(self, cemetery_id, payload, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/burial-cases",
            payload,
            headers,
        )

    def list_burial_cases(self, cemetery_id, headers, params=None):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/burial-cases",
            headers=headers,
            params=params,
        )

    def get_burial_case(self, cemetery_id, case_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/burial-cases/{case_id}",
            headers=headers,
        )

    def run_eligibility(self, cemetery_id, case_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/burial-cases/{case_id}/eligibility",
            {},
            headers,
        )

    def get_eligibility(self, cemetery_id, case_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/burial-cases/{case_id}/eligibility",
            headers=headers,
        )

    def assign_plot(self, cemetery_id, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/burial-cases/{case_id}/assign-plot",
            payload if payload is not None else {},
            headers,
        )

    def release_plot(self, cemetery_id, case_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/burial-cases/{case_id}/release-plot",
            {},
            headers,
        )

    def cancel_case(self, cemetery_id, case_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/burial-cases/{case_id}/cancel",
            {},
            headers,
        )

    # ---- PreNeedDetermination (PMC) ----
    def create_pmc(self, cemetery_id, payload, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/pre-need-determinations",
            payload,
            headers,
        )

    def list_pmcs(self, cemetery_id, headers, params=None):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/pre-need-determinations",
            headers=headers,
            params=params,
        )

    def get_pmc(self, cemetery_id, pmc_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/pre-need-determinations/{pmc_id}",
            headers=headers,
        )

    def approve_pmc(self, cemetery_id, pmc_id, expected_pmc_version, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/pre-need-determinations/{pmc_id}/approve",
            {"expected_pmc_version": expected_pmc_version},
            headers,
        )

    def deny_pmc(self, cemetery_id, pmc_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/pre-need-determinations/{pmc_id}/deny",
            {},
            headers,
        )

    def expire_sweep_pmc(self, cemetery_id, pmc_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/pre-need-determinations/{pmc_id}/expire-sweep",
            {},
            headers,
        )

    # ---- IntermentSchedule ----
    def create_interment_schedule(self, cemetery_id, payload, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/interment-schedules",
            payload,
            headers,
        )

    def list_interment_schedules(self, cemetery_id, headers, params=None):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/interment-schedules",
            headers=headers,
            params=params,
        )

    def get_interment_schedule(self, cemetery_id, schedule_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/interment-schedules/{schedule_id}",
            headers=headers,
        )

    def complete_interment_schedule(self, cemetery_id, schedule_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/interment-schedules/{schedule_id}/complete",
            {},
            headers,
        )

    def cancel_interment_schedule(self, cemetery_id, schedule_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/interment-schedules/{schedule_id}/cancel",
            {},
            headers,
        )

    # ---- MarkerOrder ----
    def create_marker_order(self, cemetery_id, payload, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/marker-orders",
            payload,
            headers,
        )

    def list_marker_orders(self, cemetery_id, headers, params=None):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/marker-orders",
            headers=headers,
            params=params,
        )

    def get_marker_order(self, cemetery_id, marker_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/marker-orders/{marker_id}",
            headers=headers,
        )

    def submit_marker_order(self, cemetery_id, marker_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/marker-orders/{marker_id}/submit",
            {},
            headers,
        )

    def engrave_marker_order(self, cemetery_id, marker_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/marker-orders/{marker_id}/engrave",
            {},
            headers,
        )

    def cancel_marker_order(self, cemetery_id, marker_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/marker-orders/{marker_id}/cancel",
            {},
            headers,
        )

    # ---- MilitaryHonors ----
    def create_military_honors(self, cemetery_id, payload, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/military-honors",
            payload,
            headers,
        )

    def list_military_honors(self, cemetery_id, headers, params=None):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/military-honors",
            headers=headers,
            params=params,
        )

    def get_military_honors(self, cemetery_id, honors_id, headers):
        return self._request(
            "GET",
            f"/cemeteries/{cemetery_id}/military-honors/{honors_id}",
            headers=headers,
        )

    def confirm_military_honors(self, cemetery_id, honors_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/military-honors/{honors_id}/confirm",
            {},
            headers,
        )

    def cancel_military_honors(self, cemetery_id, honors_id, headers):
        return self._request(
            "POST",
            f"/cemeteries/{cemetery_id}/military-honors/{honors_id}/cancel",
            {},
            headers,
        )


api_client = ApiClient()
