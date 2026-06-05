"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── BusinessEntity (PRD §3.1, §3.2, §3.12) ────────────────────
    def create_business_entity(self, payload, headers):
        return self._request("POST", "/business-entities", payload, headers)

    def get_business_entity(self, be_id, headers):
        return self._request("GET", f"/business-entities/{be_id}", headers=headers)

    def list_business_entities(self, headers, params=None):
        return self._request("GET", "/business-entities", headers=headers, params=params)

    def dissolve_business_entity(self, be_id, headers, payload=None):
        return self._request(
            "PATCH",
            f"/business-entities/{be_id}/dissolve",
            payload if payload is not None else {},
            headers,
        )

    def reinstate_business_entity(self, be_id, headers, payload=None):
        return self._request(
            "POST",
            f"/business-entities/{be_id}/reinstate",
            payload if payload is not None else {},
            headers,
        )

    # ─── RegisteredAgent (PRD §3.3) ────────────────────────────────
    def create_registered_agent(self, be_id, payload, headers):
        return self._request(
            "POST", f"/business-entities/{be_id}/registered-agents", payload, headers
        )

    def list_registered_agents(self, be_id, headers, params=None):
        return self._request(
            "GET",
            f"/business-entities/{be_id}/registered-agents",
            headers=headers,
            params=params,
        )

    def get_registered_agent(self, ra_id, headers):
        return self._request("GET", f"/registered-agents/{ra_id}", headers=headers)

    def list_foreign_qualifications_for_agent(self, ra_id, headers, params=None):
        return self._request(
            "GET",
            f"/registered-agents/{ra_id}/foreign-qualifications",
            headers=headers,
            params=params,
        )

    def resign_registered_agent(self, ra_id, headers, payload=None):
        return self._request(
            "POST",
            f"/registered-agents/{ra_id}/resign",
            payload if payload is not None else {},
            headers,
        )

    # ─── OperatingAgreement (PRD §3.4) ─────────────────────────────
    def create_operating_agreement(self, be_id, payload, headers):
        return self._request(
            "POST",
            f"/business-entities/{be_id}/operating-agreements",
            payload,
            headers,
        )

    def list_operating_agreements(self, be_id, headers, params=None):
        return self._request(
            "GET",
            f"/business-entities/{be_id}/operating-agreements",
            headers=headers,
            params=params,
        )

    def execute_operating_agreement(self, oa_id, headers, payload=None):
        return self._request(
            "POST",
            f"/operating-agreements/{oa_id}/execute",
            payload if payload is not None else {},
            headers,
        )

    # ─── EINApplication (PRD §3.5) ─────────────────────────────────
    def create_ein_application(self, be_id, payload, headers):
        return self._request(
            "POST", f"/business-entities/{be_id}/ein-applications", payload, headers
        )

    def list_ein_applications(self, be_id, headers, params=None):
        return self._request(
            "GET",
            f"/business-entities/{be_id}/ein-applications",
            headers=headers,
            params=params,
        )

    def issue_ein_application(self, ein_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ein-applications/{ein_id}/issue",
            payload if payload is not None else {},
            headers,
        )

    # ─── AnnualReport (PRD §3.7) ───────────────────────────────────
    def create_annual_report(self, be_id, payload, headers):
        return self._request(
            "POST", f"/business-entities/{be_id}/annual-reports", payload, headers
        )

    def list_annual_reports(self, be_id, headers, params=None):
        return self._request(
            "GET",
            f"/business-entities/{be_id}/annual-reports",
            headers=headers,
            params=params,
        )

    def file_annual_report(self, ar_id, headers, payload=None):
        return self._request(
            "POST",
            f"/annual-reports/{ar_id}/file",
            payload if payload is not None else {},
            headers,
        )

    def void_annual_report(self, ar_id, headers, payload=None):
        return self._request(
            "POST",
            f"/annual-reports/{ar_id}/void",
            payload if payload is not None else {},
            headers,
        )

    # ─── ForeignQualification (PRD §3.10) ──────────────────────────
    def create_foreign_qualification(self, be_id, payload, headers):
        return self._request(
            "POST",
            f"/business-entities/{be_id}/foreign-qualifications",
            payload,
            headers,
        )

    def list_foreign_qualifications(self, be_id, headers, params=None):
        return self._request(
            "GET",
            f"/business-entities/{be_id}/foreign-qualifications",
            headers=headers,
            params=params,
        )

    def approve_foreign_qualification(self, fq_id, headers, payload=None):
        return self._request(
            "POST",
            f"/foreign-qualifications/{fq_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_foreign_qualification(self, fq_id, headers, payload=None):
        return self._request(
            "POST",
            f"/foreign-qualifications/{fq_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ─── BOIDisclosure (PRD §3.11) ─────────────────────────────────
    def create_boi_disclosure(self, be_id, payload, headers):
        return self._request(
            "POST", f"/business-entities/{be_id}/boi-disclosures", payload, headers
        )

    def list_boi_disclosures(self, be_id, headers, params=None):
        return self._request(
            "GET",
            f"/business-entities/{be_id}/boi-disclosures",
            headers=headers,
            params=params,
        )

    def submit_boi_disclosure(self, boi_id, headers, payload=None):
        return self._request(
            "POST",
            f"/boi-disclosures/{boi_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def amend_boi_disclosure(self, boi_id, payload, headers):
        return self._request(
            "POST", f"/boi-disclosures/{boi_id}/amend", payload, headers
        )

    # ─── ComplianceEvent (PRD §3.12) ───────────────────────────────
    def list_compliance_events(self, be_id, headers, params=None):
        return self._request(
            "GET",
            f"/business-entities/{be_id}/compliance-events",
            headers=headers,
            params=params,
        )

    # ─── Test-driving clock (PRD §2.9, §3.7) ───────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
