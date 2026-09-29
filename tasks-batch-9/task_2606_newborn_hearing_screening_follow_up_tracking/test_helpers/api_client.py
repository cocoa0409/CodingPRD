"""HTTP client with one method per documented endpoint.

Every path below is exactly as published by the contract: a flat, top-level
collection namespace with sub-resource actions expressed as suffixes.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, JsonDict


class EhdiApiClient(GenericApiClient):
    """Thin, explicit wrapper around the newborn-hearing-screening API."""

    # ------------------------------------------------------------------
    # low-level helpers
    # ------------------------------------------------------------------

    def patch(
        self,
        path: str,
        json: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        """PATCH helper; the base client exposes only GET/POST/PUT/DELETE."""
        return self._request("PATCH", path, payload=json, headers=headers)

    @staticmethod
    def _page_params(
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if extra:
            for key, value in extra.items():
                if value is not None:
                    params[key] = value
        return params

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Optional[Headers] = None):
        return self.post(
            "/_clock/set_current_utc", json={"to_iso8601": to_iso8601}, headers=headers
        )

    # ------------------------------------------------------------------
    # facilities
    # ------------------------------------------------------------------

    def create_facility(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/facilities", json=payload, headers=headers)

    def get_facility(self, facility_id: str, headers: Optional[Headers] = None):
        return self.get("/facilities/{0}".format(facility_id), headers=headers)

    def list_facilities(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/facilities",
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )

    def create_penalty_adjustment(
        self, facility_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/facilities/{0}/penalty-adjustments".format(facility_id),
            json=payload,
            headers=headers,
        )

    def list_facility_providers(
        self,
        facility_id: str,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/facilities/{0}/providers".format(facility_id),
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )

    def get_facility_performance(self, facility_id: str, headers: Optional[Headers] = None):
        return self.get("/facilities/{0}/performance".format(facility_id), headers=headers)

    # ------------------------------------------------------------------
    # providers
    # ------------------------------------------------------------------

    def create_provider(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/providers", json=payload, headers=headers)

    def get_provider(self, provider_id: str, headers: Optional[Headers] = None):
        return self.get("/providers/{0}".format(provider_id), headers=headers)

    # ------------------------------------------------------------------
    # infants
    # ------------------------------------------------------------------

    def create_infant(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/infants", json=payload, headers=headers)

    def get_infant(self, infant_id: str, headers: Optional[Headers] = None):
        return self.get("/infants/{0}".format(infant_id), headers=headers)

    def list_infants(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/infants", headers=headers, params=self._page_params(limit, offset, filters)
        )

    def discharge_infant(
        self, infant_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/infants/{0}/discharge".format(infant_id), json=payload, headers=headers
        )

    def patch_contact_preferences(
        self, infant_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.patch(
            "/infants/{0}/contact-preferences".format(infant_id),
            json=payload,
            headers=headers,
        )

    def get_timeliness(self, infant_id: str, headers: Optional[Headers] = None):
        return self.get("/infants/{0}/timeliness".format(infant_id), headers=headers)

    def list_risk_factor_entries(
        self,
        infant_id: str,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/infants/{0}/risk-factor-entries".format(infant_id),
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )

    # ------------------------------------------------------------------
    # screening encounters
    # ------------------------------------------------------------------

    def create_encounter(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/screening-encounters", json=payload, headers=headers)

    def get_encounter(self, encounter_id: str, headers: Optional[Headers] = None):
        return self.get("/screening-encounters/{0}".format(encounter_id), headers=headers)

    def list_encounters(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/screening-encounters",
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )

    # ------------------------------------------------------------------
    # follow-up episodes
    # ------------------------------------------------------------------

    def create_episode(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/follow-up-episodes", json=payload, headers=headers)

    def close_episode(
        self, episode_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/follow-up-episodes/{0}/close".format(episode_id), json=payload, headers=headers
        )

    def get_episode(self, episode_id: str, headers: Optional[Headers] = None):
        return self.get("/follow-up-episodes/{0}".format(episode_id), headers=headers)

    def list_episodes(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/follow-up-episodes",
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )

    # ------------------------------------------------------------------
    # clinic slots
    # ------------------------------------------------------------------

    def create_slot(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/clinic-slots", json=payload, headers=headers)

    def get_slot(self, slot_id: str, headers: Optional[Headers] = None):
        return self.get("/clinic-slots/{0}".format(slot_id), headers=headers)

    def list_slots(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/clinic-slots", headers=headers, params=self._page_params(limit, offset, filters)
        )

    # ------------------------------------------------------------------
    # rescreen appointments
    # ------------------------------------------------------------------

    def create_appointment(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/rescreen-appointments", json=payload, headers=headers)

    def close_appointment(
        self, appointment_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/rescreen-appointments/{0}/close".format(appointment_id),
            json=payload,
            headers=headers,
        )

    def get_appointment(self, appointment_id: str, headers: Optional[Headers] = None):
        return self.get("/rescreen-appointments/{0}".format(appointment_id), headers=headers)

    def list_appointments(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/rescreen-appointments",
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )

    # ------------------------------------------------------------------
    # diagnostic evaluations
    # ------------------------------------------------------------------

    def create_evaluation(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/diagnostic-evaluations", json=payload, headers=headers)

    def submit_evaluation(
        self, evaluation_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/diagnostic-evaluations/{0}/submit".format(evaluation_id),
            json=payload,
            headers=headers,
        )

    def attest_evaluation(
        self, evaluation_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/diagnostic-evaluations/{0}/attest".format(evaluation_id),
            json=payload,
            headers=headers,
        )

    def finalize_evaluation(
        self, evaluation_id: str, payload: Optional[JsonDict] = None, headers: Optional[Headers] = None
    ):
        return self.post(
            "/diagnostic-evaluations/{0}/finalize".format(evaluation_id),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_evaluation(self, evaluation_id: str, headers: Optional[Headers] = None):
        return self.get("/diagnostic-evaluations/{0}".format(evaluation_id), headers=headers)

    def list_evaluations(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/diagnostic-evaluations",
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )

    # ------------------------------------------------------------------
    # early intervention referrals
    # ------------------------------------------------------------------

    def assign_referral_program(
        self, referral_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/ei-referrals/{0}/assign-program".format(referral_id),
            json=payload,
            headers=headers,
        )

    def decide_referral(
        self, referral_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/ei-referrals/{0}/decision".format(referral_id), json=payload, headers=headers
        )

    def enroll_referral(
        self, referral_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/ei-referrals/{0}/enroll".format(referral_id), json=payload, headers=headers
        )

    def get_referral(self, referral_id: str, headers: Optional[Headers] = None):
        return self.get("/ei-referrals/{0}".format(referral_id), headers=headers)

    def list_referrals(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/ei-referrals", headers=headers, params=self._page_params(limit, offset, filters)
        )

    # ------------------------------------------------------------------
    # risk factor registry
    # ------------------------------------------------------------------

    def create_risk_factor_entry(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/risk-factor-entries", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # navigation tasks
    # ------------------------------------------------------------------

    def create_task(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/navigation-tasks", json=payload, headers=headers)

    def assign_task(self, task_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post(
            "/navigation-tasks/{0}/assign".format(task_id), json=payload, headers=headers
        )

    def close_task(self, task_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post(
            "/navigation-tasks/{0}/close".format(task_id), json=payload, headers=headers
        )

    def get_task(self, task_id: str, headers: Optional[Headers] = None):
        return self.get("/navigation-tasks/{0}".format(task_id), headers=headers)

    def list_tasks(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/navigation-tasks",
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )

    # ------------------------------------------------------------------
    # reporting periods
    # ------------------------------------------------------------------

    def create_period(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/reporting-periods", json=payload, headers=headers)

    def close_period(
        self, period_id: str, payload: Optional[JsonDict] = None, headers: Optional[Headers] = None
    ):
        return self.post(
            "/reporting-periods/{0}/close".format(period_id),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_period(self, period_id: str, headers: Optional[Headers] = None):
        return self.get("/reporting-periods/{0}".format(period_id), headers=headers)

    # ------------------------------------------------------------------
    # facility reports
    # ------------------------------------------------------------------

    def create_report(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.post("/facility-reports", json=payload, headers=headers)

    def review_report(
        self, report_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/facility-reports/{0}/review".format(report_id), json=payload, headers=headers
        )

    def waive_report_penalty(
        self, report_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.post(
            "/facility-reports/{0}/waive-penalty".format(report_id),
            json=payload,
            headers=headers,
        )

    def get_report(self, report_id: str, headers: Optional[Headers] = None):
        return self.get("/facility-reports/{0}".format(report_id), headers=headers)

    def list_reports(
        self,
        headers: Optional[Headers] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        **filters: Any
    ):
        return self.get(
            "/facility-reports",
            headers=headers,
            params=self._page_params(limit, offset, filters),
        )
