"""API client: one method per endpoint the PRD defines."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Charitable Solicitation Registration API."""

    # ---------------------------------------------------------------- config

    def create_state_profile(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/state-profiles", payload, headers)

    def get_state_profile(self, state_code: str, headers=None):
        return self._request(
            "GET", f"/state-profiles/{state_code}", headers=headers
        )

    def set_clock(self, to_iso8601: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --------------------------------------------------------- organizations

    def create_organization(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/organizations", payload, headers)

    def list_organizations(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/organizations", headers=headers, params=params)

    def get_organization(self, organization_id: str, headers=None):
        return self._request(
            "GET", f"/organizations/{organization_id}", headers=headers
        )

    def update_organization(
        self, organization_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "PATCH", f"/organizations/{organization_id}", payload, headers
        )

    def get_compliance_calendar(
        self, organization_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/compliance-calendar",
            headers=headers,
            params=params,
        )

    def list_organization_solicitation_activities(
        self, organization_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/solicitation-activities",
            headers=headers,
            params=params,
        )

    def list_organization_financial_statements(
        self, organization_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/financial-statements",
            headers=headers,
            params=params,
        )

    def list_organization_officer_disclosures(
        self, organization_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/officer-disclosures",
            headers=headers,
            params=params,
        )

    def list_organization_disclosure_statements(
        self, organization_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/disclosure-statements",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------- onboarding child rows

    def create_solicitation_activity(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/solicitation-activities", payload, headers)

    def create_financial_statement(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/financial-statements", payload, headers)

    def create_officer_disclosure(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/officer-disclosures", payload, headers)

    def create_disclosure_statement(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/disclosure-statements", payload, headers)

    # ----------------------------------------------------- state filings

    def create_state_registration(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/state-registrations", payload, headers)

    def list_state_registrations(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/state-registrations", headers=headers, params=params
        )

    def get_state_registration(self, registration_id: str, headers=None):
        return self._request(
            "GET", f"/state-registrations/{registration_id}", headers=headers
        )

    def submit_state_registration(
        self, registration_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        return self._request(
            "POST",
            f"/state-registrations/{registration_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_state_registration(
        self, registration_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/state-registrations/{registration_id}/review", payload, headers
        )

    def withdraw_state_registration(
        self, registration_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/state-registrations/{registration_id}/withdraw", payload, headers
        )

    def list_registration_extension_requests(
        self, registration_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/state-registrations/{registration_id}/extension-requests",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------------- documents

    def create_registration_document(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/registration-documents", payload, headers)

    def list_registration_documents(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/registration-documents", headers=headers, params=params
        )

    def get_registration_document(self, document_id: str, headers=None):
        return self._request(
            "GET", f"/registration-documents/{document_id}", headers=headers
        )

    # ------------------------------------------------- extension requests

    def create_extension_request(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/extension-requests", payload, headers)

    def decide_extension_request(
        self, extension_request_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/extension-requests/{extension_request_id}/decide", payload, headers
        )

    # ------------------------------------------------- fundraiser registry

    def create_professional_fundraiser(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/professional-fundraisers", payload, headers)

    def get_professional_fundraiser(self, fundraiser_id: str, headers=None):
        return self._request(
            "GET", f"/professional-fundraisers/{fundraiser_id}", headers=headers
        )

    def list_fundraiser_registrations(
        self, fundraiser_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/professional-fundraisers/{fundraiser_id}/registrations",
            headers=headers,
            params=params,
        )

    def create_fundraiser_registration(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/fundraiser-registrations", payload, headers)

    # ---------------------------------------------------------- contracts

    def create_fundraising_contract(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/fundraising-contracts", payload, headers)

    def file_fundraising_contract(
        self, contract_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        return self._request(
            "POST",
            f"/fundraising-contracts/{contract_id}/file",
            payload if payload is not None else {},
            headers,
        )

    def list_fundraising_contracts(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/fundraising-contracts", headers=headers, params=params
        )

    def get_fundraising_contract(self, contract_id: str, headers=None):
        return self._request(
            "GET", f"/fundraising-contracts/{contract_id}", headers=headers
        )

    # --------------------------------------------------------- promotions

    def create_coventure_promotion(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/coventure-promotions", payload, headers)

    def file_coventure_promotion(
        self, promotion_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        return self._request(
            "POST",
            f"/coventure-promotions/{promotion_id}/file",
            payload if payload is not None else {},
            headers,
        )

    def activate_coventure_promotion(
        self, promotion_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        return self._request(
            "POST",
            f"/coventure-promotions/{promotion_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def settle_coventure_promotion(
        self, promotion_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/coventure-promotions/{promotion_id}/settle", payload, headers
        )

    def list_coventure_promotions(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/coventure-promotions", headers=headers, params=params
        )

    def get_coventure_promotion(self, promotion_id: str, headers=None):
        return self._request(
            "GET", f"/coventure-promotions/{promotion_id}", headers=headers
        )

    # ------------------------------------------------------- enforcement

    def create_enforcement_action(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/enforcement-actions", payload, headers)

    def remediate_enforcement_action(
        self, action_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/enforcement-actions/{action_id}/remediate", payload, headers
        )

    def decide_enforcement_action(
        self, action_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/enforcement-actions/{action_id}/decide", payload, headers
        )

    def vacate_enforcement_action(
        self, action_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/enforcement-actions/{action_id}/vacate", payload, headers
        )

    def list_enforcement_actions(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/enforcement-actions", headers=headers, params=params
        )

    def get_enforcement_action(self, action_id: str, headers=None):
        return self._request(
            "GET", f"/enforcement-actions/{action_id}", headers=headers
        )

    # ------------------------------------------------------------ sweeps

    def run_compliance_sweep(
        self, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        return self._request(
            "POST",
            "/compliance-sweeps",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
