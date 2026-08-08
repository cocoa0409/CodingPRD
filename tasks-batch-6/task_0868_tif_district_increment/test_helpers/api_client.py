"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── TifDistrict ───────────────────────────────────────────────────────
    def create_district(self, payload, headers):
        return self._request("POST", "/tif-districts", payload, headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/tif-districts", headers=headers, params=params)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/tif-districts/{district_id}", headers=headers)

    def certify_district(self, district_id, headers, payload=None):
        return self._request("POST", f"/tif-districts/{district_id}/certify",
                             payload or {}, headers)

    def decertify_district(self, district_id, payload, headers):
        return self._request("POST", f"/tif-districts/{district_id}/decertify",
                             payload, headers)

    def get_project_fund(self, district_id, headers):
        return self._request("GET", f"/tif-districts/{district_id}/project-fund",
                             headers=headers)

    def get_district_taxing_bodies(self, district_id, headers, params=None):
        return self._request("GET", f"/tif-districts/{district_id}/taxing-bodies",
                             headers=headers, params=params)

    def get_district_obligations(self, district_id, headers, params=None):
        return self._request("GET", f"/tif-districts/{district_id}/obligations",
                             headers=headers, params=params)

    def get_district_increment_records(self, district_id, headers, params=None):
        return self._request("GET", f"/tif-districts/{district_id}/increment-records",
                             headers=headers, params=params)

    def get_district_annual_reports(self, district_id, headers, params=None):
        return self._request("GET", f"/tif-districts/{district_id}/annual-reports",
                             headers=headers, params=params)

    def get_district_surplus_agreements(self, district_id, headers, params=None):
        return self._request("GET", f"/tif-districts/{district_id}/surplus-agreements",
                             headers=headers, params=params)

    def get_district_surplus_distributions(self, district_id, headers, params=None):
        return self._request("GET", f"/tif-districts/{district_id}/surplus-distributions",
                             headers=headers, params=params)

    # ── TaxingBody ────────────────────────────────────────────────────────
    def create_taxing_body(self, district_id, payload, headers):
        return self._request("POST", f"/tif-districts/{district_id}/taxing-bodies",
                             payload, headers)

    def get_taxing_body(self, taxing_body_id, headers):
        return self._request("GET", f"/taxing-bodies/{taxing_body_id}", headers=headers)

    def get_taxing_body_surplus_distributions(self, taxing_body_id, headers, params=None):
        return self._request("GET",
                             f"/taxing-bodies/{taxing_body_id}/surplus-distributions",
                             headers=headers, params=params)

    def get_taxing_body_surplus_agreements(self, taxing_body_id, headers, params=None):
        return self._request("GET",
                             f"/taxing-bodies/{taxing_body_id}/surplus-agreements",
                             headers=headers, params=params)

    # ── Developer ─────────────────────────────────────────────────────────
    def create_developer(self, payload, headers):
        return self._request("POST", "/developers", payload, headers)

    def get_developer(self, developer_id, headers):
        return self._request("GET", f"/developers/{developer_id}", headers=headers)

    def get_developer_obligations(self, developer_id, headers, params=None):
        return self._request("GET", f"/developers/{developer_id}/obligations",
                             headers=headers, params=params)

    # ── Obligation ────────────────────────────────────────────────────────
    def create_obligation(self, payload, headers):
        return self._request("POST", "/obligations", payload, headers)

    def get_obligation(self, obligation_id, headers):
        return self._request("GET", f"/obligations/{obligation_id}", headers=headers)

    def submit_obligation(self, obligation_id, headers, payload=None):
        return self._request("POST", f"/obligations/{obligation_id}/submit",
                             payload or {}, headers)

    def register_obligation(self, obligation_id, payload, headers):
        return self._request("POST", f"/obligations/{obligation_id}/register",
                             payload, headers)

    def return_obligation(self, obligation_id, headers, payload=None):
        return self._request("POST", f"/obligations/{obligation_id}/return",
                             payload or {}, headers)

    def reject_obligation(self, obligation_id, headers, payload=None):
        return self._request("POST", f"/obligations/{obligation_id}/reject",
                             payload or {}, headers)

    def accrue_interest(self, obligation_id, payload, headers):
        return self._request("POST", f"/obligations/{obligation_id}/accrue-interest",
                             payload, headers)

    def create_disbursement(self, obligation_id, payload, headers):
        return self._request("POST", f"/obligations/{obligation_id}/disbursements",
                             payload, headers)

    def get_obligation_disbursements(self, obligation_id, headers, params=None):
        return self._request("GET", f"/obligations/{obligation_id}/disbursements",
                             headers=headers, params=params)

    # ── Disbursement ──────────────────────────────────────────────────────
    def void_disbursement(self, disbursement_id, headers, payload=None):
        return self._request("POST", f"/disbursements/{disbursement_id}/void",
                             payload or {}, headers)

    # ── IncrementRecord ───────────────────────────────────────────────────
    def create_increment_record(self, district_id, payload, headers):
        return self._request("POST", f"/tif-districts/{district_id}/increment-records",
                             payload, headers)

    def finalize_increment(self, increment_id, payload, headers):
        return self._request("POST", f"/increment-records/{increment_id}/finalize",
                             payload, headers)

    def reopen_increment(self, increment_id, headers, payload=None):
        return self._request("POST", f"/increment-records/{increment_id}/reopen",
                             payload or {}, headers)

    # ── AnnualReport ──────────────────────────────────────────────────────
    def create_annual_report(self, district_id, payload, headers):
        return self._request("POST", f"/tif-districts/{district_id}/annual-reports",
                             payload, headers)

    def file_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/annual-reports/{report_id}/file",
                             payload or {}, headers)

    def accept_report(self, report_id, payload, headers):
        return self._request("POST", f"/annual-reports/{report_id}/accept",
                             payload, headers)

    def return_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/annual-reports/{report_id}/return",
                             payload or {}, headers)

    # ── SurplusAgreement ──────────────────────────────────────────────────
    def create_surplus_agreement(self, district_id, payload, headers):
        return self._request("POST", f"/tif-districts/{district_id}/surplus-agreements",
                             payload, headers)


api_client = ApiClient()
