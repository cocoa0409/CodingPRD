"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under /api (PRD section 4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD section 2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Rating cycles
    # ------------------------------------------------------------------
    def create_rating_cycle(self, payload, headers):
        return self._request("POST", "/api/rating-cycles", payload, headers)

    def list_rating_cycles(self, headers, params=None):
        return self._request("GET", "/api/rating-cycles", headers=headers, params=params)

    def get_rating_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/rating-cycles/{cycle_id}", headers=headers)

    def transition_rating_cycle(self, cycle_id, to_state, headers):
        return self._request("POST", f"/api/rating-cycles/{cycle_id}/transition",
                             {"to_state": to_state}, headers)

    # ------------------------------------------------------------------
    # Measures
    # ------------------------------------------------------------------
    def create_measure(self, payload, headers):
        return self._request("POST", "/api/measures", payload, headers)

    def list_measures(self, headers, params=None):
        return self._request("GET", "/api/measures", headers=headers, params=params)

    def get_measure(self, measure_id, headers):
        return self._request("GET", f"/api/measures/{measure_id}", headers=headers)

    def transition_measure(self, measure_id, to_state, headers):
        return self._request("POST", f"/api/measures/{measure_id}/transition",
                             {"to_state": to_state}, headers)

    # ------------------------------------------------------------------
    # Cut point sets
    # ------------------------------------------------------------------
    def create_cutpoint_set(self, payload, headers):
        return self._request("POST", "/api/cutpoint-sets", payload, headers)

    def list_cutpoint_sets(self, headers, params=None):
        return self._request("GET", "/api/cutpoint-sets", headers=headers, params=params)

    def get_cutpoint_set(self, set_id, headers):
        return self._request("GET", f"/api/cutpoint-sets/{set_id}", headers=headers)

    def replace_cutpoint_rows(self, set_id, payload, headers):
        return self._request("PUT", f"/api/cutpoint-sets/{set_id}", payload, headers)

    def publish_cutpoint_set(self, set_id, expected_rating_cycle_version, headers):
        return self._request("POST", f"/api/cutpoint-sets/{set_id}/publish",
                             {"expected_rating_cycle_version": expected_rating_cycle_version},
                             headers)

    # ------------------------------------------------------------------
    # Measure performances
    # ------------------------------------------------------------------
    def create_measure_performance(self, payload, headers):
        return self._request("POST", "/api/measure-performances", payload, headers)

    def list_measure_performances(self, headers, params=None):
        return self._request("GET", "/api/measure-performances", headers=headers, params=params)

    def get_measure_performance(self, perf_id, headers):
        return self._request("GET", f"/api/measure-performances/{perf_id}", headers=headers)

    def correct_measure_performance(self, perf_id, payload, headers):
        return self._request("PUT", f"/api/measure-performances/{perf_id}", payload, headers)

    def transition_measure_performance(self, perf_id, to_state, headers):
        return self._request("POST", f"/api/measure-performances/{perf_id}/transition",
                             {"to_state": to_state}, headers)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def transition_member(self, member_id, to_state, headers):
        return self._request("POST", f"/api/members/{member_id}/transition",
                             {"to_state": to_state}, headers)

    # ------------------------------------------------------------------
    # Care gaps
    # ------------------------------------------------------------------
    def create_care_gap(self, payload, headers):
        return self._request("POST", "/api/care-gaps", payload, headers)

    def list_care_gaps(self, headers, params=None):
        return self._request("GET", "/api/care-gaps", headers=headers, params=params)

    def get_care_gap(self, gap_id, headers):
        return self._request("GET", f"/api/care-gaps/{gap_id}", headers=headers)

    def transition_care_gap(self, gap_id, to_state, headers):
        return self._request("POST", f"/api/care-gaps/{gap_id}/transition",
                             {"to_state": to_state}, headers)

    def intervene_care_gap(self, gap_id, channel, headers):
        return self._request("POST", f"/api/care-gaps/{gap_id}/intervene",
                             {"channel": channel}, headers)

    # ------------------------------------------------------------------
    # Provider groups
    # ------------------------------------------------------------------
    def create_provider_group(self, payload, headers):
        return self._request("POST", "/api/provider-groups", payload, headers)

    def list_provider_groups(self, headers, params=None):
        return self._request("GET", "/api/provider-groups", headers=headers, params=params)

    def get_provider_group(self, group_id, headers):
        return self._request("GET", f"/api/provider-groups/{group_id}", headers=headers)

    def transition_provider_group(self, group_id, to_state, headers):
        return self._request("POST", f"/api/provider-groups/{group_id}/transition",
                             {"to_state": to_state}, headers)

    # ------------------------------------------------------------------
    # Incentive payouts
    # ------------------------------------------------------------------
    def create_incentive_payout(self, payload, headers):
        return self._request("POST", "/api/incentive-payouts", payload, headers)

    def list_incentive_payouts(self, headers, params=None):
        return self._request("GET", "/api/incentive-payouts", headers=headers, params=params)

    def get_incentive_payout(self, payout_id, headers):
        return self._request("GET", f"/api/incentive-payouts/{payout_id}", headers=headers)

    def transition_incentive_payout(self, payout_id, to_state, headers):
        return self._request("POST", f"/api/incentive-payouts/{payout_id}/transition",
                             {"to_state": to_state}, headers)

    # ------------------------------------------------------------------
    # Survey vendors
    # ------------------------------------------------------------------
    def create_survey_vendor(self, payload, headers):
        return self._request("POST", "/api/survey-vendors", payload, headers)

    def list_survey_vendors(self, headers, params=None):
        return self._request("GET", "/api/survey-vendors", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Survey waves
    # ------------------------------------------------------------------
    def create_survey_wave(self, payload, headers):
        return self._request("POST", "/api/survey-waves", payload, headers)

    def list_survey_waves(self, headers, params=None):
        return self._request("GET", "/api/survey-waves", headers=headers, params=params)

    def get_survey_wave(self, wave_id, headers):
        return self._request("GET", f"/api/survey-waves/{wave_id}", headers=headers)

    def transition_survey_wave(self, wave_id, to_state, headers, response_count=None):
        payload = {"to_state": to_state}
        if response_count is not None:
            payload["response_count"] = response_count
        return self._request("POST", f"/api/survey-waves/{wave_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Complaint cases
    # ------------------------------------------------------------------
    def create_complaint_case(self, payload, headers):
        return self._request("POST", "/api/complaint-cases", payload, headers)

    def list_complaint_cases(self, headers, params=None):
        return self._request("GET", "/api/complaint-cases", headers=headers, params=params)

    def get_complaint_case(self, case_id, headers):
        return self._request("GET", f"/api/complaint-cases/{case_id}", headers=headers)

    def transition_complaint_case(self, case_id, to_state, headers):
        return self._request("POST", f"/api/complaint-cases/{case_id}/transition",
                             {"to_state": to_state}, headers)

    # ------------------------------------------------------------------
    # Rating forecasts
    # ------------------------------------------------------------------
    def create_rating_forecast(self, payload, headers):
        return self._request("POST", "/api/rating-forecasts", payload, headers)

    def list_rating_forecasts(self, headers, params=None):
        return self._request("GET", "/api/rating-forecasts", headers=headers, params=params)

    def get_rating_forecast(self, forecast_id, headers):
        return self._request("GET", f"/api/rating-forecasts/{forecast_id}", headers=headers)


api_client = ApiClient()
