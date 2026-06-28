"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base `_request()` is inherited.
GET requests pass filters/pagination via `params`; POST requests pass `payload`
as a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Practice & clock ────────────────────────────────────────────────────
    def create_practice(self, payload, headers):
        return self._request("POST", "/practices", payload, headers)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/practices/{practice_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Sliding-scale tiers ─────────────────────────────────────────────────
    def create_sliding_scale_tier(self, payload, headers):
        return self._request("POST", "/sliding-scale-tiers", payload, headers)

    def get_sliding_scale_tier(self, tier_id, headers):
        return self._request("GET", f"/sliding-scale-tiers/{tier_id}", headers=headers)

    def list_sliding_scale_tiers(self, headers, params=None):
        return self._request("GET", "/sliding-scale-tiers", headers=headers, params=params)

    # ─── Service packages ────────────────────────────────────────────────────
    def create_service_package(self, payload, headers):
        return self._request("POST", "/service-packages", payload, headers)

    def get_service_package(self, package_id, headers):
        return self._request("GET", f"/service-packages/{package_id}", headers=headers)

    def list_service_packages(self, headers, params=None):
        return self._request("GET", "/service-packages", headers=headers, params=params)

    # ─── Consultants ─────────────────────────────────────────────────────────
    def create_consultant(self, payload, headers):
        return self._request("POST", "/consultants", payload, headers)

    def get_consultant(self, consultant_id, headers):
        return self._request("GET", f"/consultants/{consultant_id}", headers=headers)

    def list_consultants(self, headers, params=None):
        return self._request("GET", "/consultants", headers=headers, params=params)

    # ─── Clients ─────────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    # ─── Consults ────────────────────────────────────────────────────────────
    def create_consult(self, payload, headers):
        return self._request("POST", "/consults", payload, headers)

    def get_consult(self, consult_id, headers):
        return self._request("GET", f"/consults/{consult_id}", headers=headers)

    def list_consults(self, headers, params=None):
        return self._request("GET", "/consults", headers=headers, params=params)

    def reschedule_consult(self, consult_id, payload, headers):
        return self._request("POST", f"/consults/{consult_id}/reschedule", payload, headers)

    def start_consult(self, consult_id, headers):
        return self._request("POST", f"/consults/{consult_id}/start", {}, headers)

    def complete_consult(self, consult_id, headers):
        return self._request("POST", f"/consults/{consult_id}/complete", {}, headers)

    def no_show_consult(self, consult_id, headers):
        return self._request("POST", f"/consults/{consult_id}/no-show", {}, headers)

    def cancel_consult(self, consult_id, headers):
        return self._request("POST", f"/consults/{consult_id}/cancel", {}, headers)

    # ─── Feeding assessments ─────────────────────────────────────────────────
    def create_feeding_assessment(self, payload, headers):
        return self._request("POST", "/feeding-assessments", payload, headers)

    def get_feeding_assessment(self, assessment_id, headers):
        return self._request("GET", f"/feeding-assessments/{assessment_id}", headers=headers)

    def list_feeding_assessments(self, headers, params=None):
        return self._request("GET", "/feeding-assessments", headers=headers, params=params)

    # ─── Follow-up plans & weighted feeds ────────────────────────────────────
    def create_follow_up_plan(self, payload, headers):
        return self._request("POST", "/follow-up-plans", payload, headers)

    def get_follow_up_plan(self, plan_id, headers):
        return self._request("GET", f"/follow-up-plans/{plan_id}", headers=headers)

    def list_follow_up_plans(self, headers, params=None):
        return self._request("GET", "/follow-up-plans", headers=headers, params=params)

    def close_follow_up_plan(self, plan_id, headers):
        return self._request("POST", f"/follow-up-plans/{plan_id}/close", {}, headers)

    def create_weighted_feed(self, payload, headers):
        return self._request("POST", "/weighted-feeds", payload, headers)

    def get_weighted_feed(self, feed_id, headers):
        return self._request("GET", f"/weighted-feeds/{feed_id}", headers=headers)

    def list_weighted_feeds(self, headers, params=None):
        return self._request("GET", "/weighted-feeds", headers=headers, params=params)

    # ─── Superbills ──────────────────────────────────────────────────────────
    def create_superbill(self, payload, headers):
        return self._request("POST", "/superbills", payload, headers)

    def get_superbill(self, superbill_id, headers):
        return self._request("GET", f"/superbills/{superbill_id}", headers=headers)

    def list_superbills(self, headers, params=None):
        return self._request("GET", "/superbills", headers=headers, params=params)

    def submit_superbill(self, superbill_id, headers):
        return self._request("POST", f"/superbills/{superbill_id}/submit", {}, headers)

    def adjudicate_superbill(self, superbill_id, payload, headers):
        return self._request("POST", f"/superbills/{superbill_id}/adjudicate", payload, headers)

    def void_superbill(self, superbill_id, payload, headers):
        return self._request("POST", f"/superbills/{superbill_id}/void", payload, headers)

    # ─── DME qualifications ──────────────────────────────────────────────────
    def create_dme_qualification(self, payload, headers):
        return self._request("POST", "/dme-qualifications", payload, headers)

    def get_dme_qualification(self, dme_id, headers):
        return self._request("GET", f"/dme-qualifications/{dme_id}", headers=headers)

    def list_dme_qualifications(self, headers, params=None):
        return self._request("GET", "/dme-qualifications", headers=headers, params=params)

    def adjudicate_dme_qualification(self, dme_id, headers):
        return self._request("POST", f"/dme-qualifications/{dme_id}/adjudicate", {}, headers)

    # ─── Pediatrician referrals ──────────────────────────────────────────────
    def create_pediatrician_referral(self, payload, headers):
        return self._request("POST", "/pediatrician-referrals", payload, headers)

    def get_pediatrician_referral(self, referral_id, headers):
        return self._request("GET", f"/pediatrician-referrals/{referral_id}", headers=headers)

    def list_pediatrician_referrals(self, headers, params=None):
        return self._request("GET", "/pediatrician-referrals", headers=headers, params=params)

    def acknowledge_pediatrician_referral(self, referral_id, headers):
        return self._request("POST", f"/pediatrician-referrals/{referral_id}/acknowledge", {}, headers)

    def cancel_pediatrician_referral(self, referral_id, headers):
        return self._request("POST", f"/pediatrician-referrals/{referral_id}/cancel", {}, headers)


api_client = ApiClient()
