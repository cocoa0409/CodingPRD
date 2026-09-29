"""API client: one method per operation in the PRD's endpoint inventory (PRD §4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the Archival Clearance API. All collections are mounted under `/`."""

    # ── Productions ─────────────────────────────────────────────────────────

    def create_production(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/productions", payload, headers)

    def get_production(self, production_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/productions/{production_id}", headers=headers)

    def set_production_state(self, production_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"/productions/{production_id}/state", payload, headers)

    def list_production_clearance_charts(self, production_id: str, headers: Dict[str, str],
                                         params: Optional[Dict] = None):
        return self._request("GET", f"/productions/{production_id}/clearance-charts",
                             headers=headers, params=params)

    # ── Archives ────────────────────────────────────────────────────────────

    def create_archive(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/archives", payload, headers)

    def get_archive(self, archive_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/archives/{archive_id}", headers=headers)

    def set_archive_state(self, archive_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/archives/{archive_id}/state", payload, headers)

    def create_rate_card(self, archive_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/archives/{archive_id}/rate-cards", payload, headers)

    def list_archive_rate_cards(self, archive_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"/archives/{archive_id}/rate-cards",
                             headers=headers, params=params)

    def list_archive_source_candidates(self, archive_id: str, headers: Dict[str, str],
                                       params: Optional[Dict] = None):
        return self._request("GET", f"/archives/{archive_id}/source-candidates",
                             headers=headers, params=params)

    # ── Assets ──────────────────────────────────────────────────────────────

    def create_asset(self, production_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", f"/productions/{production_id}/assets", payload, headers)

    def get_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/assets", headers=headers, params=params)

    # ── Source candidates ───────────────────────────────────────────────────

    def create_source_candidate(self, asset_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/assets/{asset_id}/source-candidates", payload, headers)

    def list_asset_source_candidates(self, asset_id: str, headers: Dict[str, str],
                                     params: Optional[Dict] = None):
        return self._request("GET", f"/assets/{asset_id}/source-candidates",
                             headers=headers, params=params)

    def select_source(self, asset_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/assets/{asset_id}/select-source", payload, headers)

    # ── Licences ────────────────────────────────────────────────────────────

    def create_license(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def create_negotiation_round(self, license_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/negotiation-rounds",
                             payload, headers)

    def list_negotiation_rounds(self, license_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"/licenses/{license_id}/negotiation-rounds",
                             headers=headers, params=params)

    def set_license_state(self, license_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/state", payload, headers)

    def renew_license(self, license_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/renew", payload, headers)

    # ── Fair use analyses and opinion letters ───────────────────────────────

    def create_fair_use_analysis(self, asset_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"/assets/{asset_id}/fair-use-analyses", payload, headers)

    def get_fair_use_analysis(self, analysis_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/fair-use-analyses/{analysis_id}", headers=headers)

    def list_asset_fair_use_analyses(self, asset_id: str, headers: Dict[str, str],
                                     params: Optional[Dict] = None):
        return self._request("GET", f"/assets/{asset_id}/fair-use-analyses",
                             headers=headers, params=params)

    def set_fair_use_analysis_state(self, analysis_id: str, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request("POST", f"/fair-use-analyses/{analysis_id}/state",
                             payload, headers)

    def create_opinion_letter(self, analysis_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/fair-use-analyses/{analysis_id}/opinion-letters",
                             payload, headers)

    def list_opinion_letters(self, analysis_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", f"/fair-use-analyses/{analysis_id}/opinion-letters",
                             headers=headers, params=params)

    def set_opinion_letter_state(self, letter_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"/opinion-letters/{letter_id}/state", payload, headers)

    # ── Subject releases ────────────────────────────────────────────────────

    def create_subject_release(self, production_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"/productions/{production_id}/subject-releases",
                             payload, headers)

    def get_subject_release(self, release_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/subject-releases/{release_id}", headers=headers)

    def list_subject_releases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/subject-releases", headers=headers, params=params)

    def set_subject_release_state(self, release_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", f"/subject-releases/{release_id}/state", payload, headers)

    # ── Clearance charts ────────────────────────────────────────────────────

    def pin_clearance_chart(self, production_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/productions/{production_id}/clearance-charts",
                             payload, headers)

    def get_clearance_chart(self, chart_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/clearance-charts/{chart_id}", headers=headers)

    # ── E&O applications ────────────────────────────────────────────────────

    def create_eo_application(self, production_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/productions/{production_id}/eo-applications",
                             payload, headers)

    def get_eo_application(self, eo_application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/eo-applications/{eo_application_id}", headers=headers)

    def list_eo_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/eo-applications", headers=headers, params=params)

    def create_eo_review(self, eo_application_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/eo-applications/{eo_application_id}/reviews",
                             payload, headers)

    def set_eo_application_state(self, eo_application_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"/eo-applications/{eo_application_id}/state",
                             payload, headers)

    # ── Delivery packages ───────────────────────────────────────────────────

    def create_delivery_package(self, production_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/productions/{production_id}/delivery-packages",
                             payload, headers)

    def get_delivery_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/delivery-packages/{package_id}", headers=headers)

    def list_delivery_packages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/delivery-packages", headers=headers, params=params)

    def set_delivery_package_state(self, package_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", f"/delivery-packages/{package_id}/state",
                             payload, headers)

    # ── Rights sweep and logical clock ──────────────────────────────────────

    def run_rights_sweep(self, production_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/productions/{production_id}/rights-sweep",
                             payload if payload is not None else {}, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
