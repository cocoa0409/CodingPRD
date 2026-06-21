"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Applicant ───────────────────────────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    # ─── ResidencyVerification ───────────────────────────────────────────
    def create_residency_verification(self, payload, headers):
        return self._request("POST", "/residency-verifications", payload, headers)

    def get_residency_verification(self, rv_id, headers):
        return self._request("GET", f"/residency-verifications/{rv_id}", headers=headers)

    def list_residency_verifications(self, headers, params=None):
        return self._request("GET", "/residency-verifications", headers=headers, params=params)

    def approve_residency_verification(self, rv_id, headers):
        return self._request("POST", f"/residency-verifications/{rv_id}/approve", {}, headers)

    def deny_residency_verification(self, rv_id, headers):
        return self._request("POST", f"/residency-verifications/{rv_id}/deny", {}, headers)

    # ─── EducationCertificate ────────────────────────────────────────────
    def create_education_certificate(self, payload, headers):
        return self._request("POST", "/education-certificates", payload, headers)

    def get_education_certificate(self, ec_id, headers):
        return self._request("GET", f"/education-certificates/{ec_id}", headers=headers)

    def list_education_certificates(self, headers, params=None):
        return self._request("GET", "/education-certificates", headers=headers, params=params)

    def verify_education_certificate(self, ec_id, headers):
        return self._request("POST", f"/education-certificates/{ec_id}/verify", {}, headers)

    def reject_education_certificate(self, ec_id, headers):
        return self._request("POST", f"/education-certificates/{ec_id}/reject", {}, headers)

    # ─── LicenseProduct ──────────────────────────────────────────────────
    def create_license_product(self, payload, headers):
        return self._request("POST", "/license-products", payload, headers)

    def get_license_product(self, product_id, headers):
        return self._request("GET", f"/license-products/{product_id}", headers=headers)

    def list_license_products(self, headers, params=None):
        return self._request("GET", "/license-products", headers=headers, params=params)

    def retire_license_product(self, product_id, headers):
        return self._request("POST", f"/license-products/{product_id}/retire", {}, headers)

    # ─── SpeciesSeason ───────────────────────────────────────────────────
    def create_species_season(self, payload, headers):
        return self._request("POST", "/species-seasons", payload, headers)

    def get_species_season(self, season_id, headers):
        return self._request("GET", f"/species-seasons/{season_id}", headers=headers)

    def list_species_seasons(self, headers, params=None):
        return self._request("GET", "/species-seasons", headers=headers, params=params)

    def open_species_season(self, season_id, headers):
        return self._request("POST", f"/species-seasons/{season_id}/open", {}, headers)

    def close_species_season(self, season_id, headers):
        return self._request("POST", f"/species-seasons/{season_id}/close", {}, headers)

    # ─── DrawPool ────────────────────────────────────────────────────────
    def create_draw_pool(self, payload, headers):
        return self._request("POST", "/draw-pools", payload, headers)

    def get_draw_pool(self, pool_id, headers):
        return self._request("GET", f"/draw-pools/{pool_id}", headers=headers)

    def list_draw_pools(self, headers, params=None):
        return self._request("GET", "/draw-pools", headers=headers, params=params)

    def close_entries_draw_pool(self, pool_id, headers):
        return self._request("POST", f"/draw-pools/{pool_id}/close-entries", {}, headers)

    def execute_draw(self, pool_id, payload, headers):
        return self._request("POST", f"/draw-pools/{pool_id}/execute-draw", payload, headers)

    # ─── DrawApplication ─────────────────────────────────────────────────
    def create_draw_application(self, payload, headers):
        return self._request("POST", "/draw-applications", payload, headers)

    def get_draw_application(self, app_id, headers):
        return self._request("GET", f"/draw-applications/{app_id}", headers=headers)

    def list_draw_applications(self, headers, params=None):
        return self._request("GET", "/draw-applications", headers=headers, params=params)

    def withdraw_draw_application(self, app_id, headers):
        return self._request("POST", f"/draw-applications/{app_id}/withdraw", {}, headers)

    # ─── License ─────────────────────────────────────────────────────────
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def get_bag_budget(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}/bag-budget", headers=headers)

    # ─── HarvestReport ───────────────────────────────────────────────────
    def create_harvest_report(self, payload, headers):
        return self._request("POST", "/harvest-reports", payload, headers)

    def get_harvest_report(self, report_id, headers):
        return self._request("GET", f"/harvest-reports/{report_id}", headers=headers)

    def list_harvest_reports(self, headers, params=None):
        return self._request("GET", "/harvest-reports", headers=headers, params=params)

    def accept_harvest_report(self, report_id, headers):
        return self._request("POST", f"/harvest-reports/{report_id}/accept", {}, headers)

    def reject_harvest_report(self, report_id, headers):
        return self._request("POST", f"/harvest-reports/{report_id}/reject", {}, headers)

    # ─── Replacement ─────────────────────────────────────────────────────
    def create_replacement(self, payload, headers):
        return self._request("POST", "/replacements", payload, headers)

    def get_replacement(self, replacement_id, headers):
        return self._request("GET", f"/replacements/{replacement_id}", headers=headers)

    def list_replacements(self, headers, params=None):
        return self._request("GET", "/replacements", headers=headers, params=params)

    # ─── Test-driving clock ──────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
