"""API client: one method per endpoint in the PRD's endpoint table (§4).

Every method returns the raw ``requests.Response`` so tests can assert status
codes and envelope contents through the framework validators. The topology is
flat (§2): every collection is mounted as a top-level path segment, and the
nested paths — a program's agreements, a site's negotiations and zoning dockets,
an application's load studies — are reverse-reachability reads only.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------- siting programs --
    def create_siting_program(self, payload: dict, headers: dict):
        return self._request("POST", "/siting-programs", payload, headers)

    def get_siting_program(self, program_id: str, headers: dict):
        return self._request("GET", f"/siting-programs/{program_id}", headers=headers)

    def list_program_power_purchase_agreements(
        self, program_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/siting-programs/{program_id}/power-purchase-agreements",
            headers=headers,
            params=params,
        )

    def run_option_expiry_sweep(
        self, program_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/siting-programs/{program_id}/option-expiry-sweep",
            payload if payload is not None else {},
            headers,
        )

    # ---------------------------------------------------------------- utilities --
    def create_utility(self, payload: dict, headers: dict):
        return self._request("POST", "/utilities", payload, headers)

    def get_utility(self, utility_id: str, headers: dict):
        return self._request("GET", f"/utilities/{utility_id}", headers=headers)

    def create_capacity_revision(self, utility_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/utilities/{utility_id}/capacity-revisions", payload, headers
        )

    # ------------------------------------------------------------ water sources --
    def create_water_source(self, payload: dict, headers: dict):
        return self._request("POST", "/water-sources", payload, headers)

    def get_water_source(self, water_source_id: str, headers: dict):
        return self._request(
            "GET", f"/water-sources/{water_source_id}", headers=headers
        )

    def create_drought_declaration(
        self, water_source_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/water-sources/{water_source_id}/drought-declarations",
            payload,
            headers,
        )

    # ---------------------------------------------------------- candidate sites --
    def create_candidate_site(self, payload: dict, headers: dict):
        return self._request("POST", "/candidate-sites", payload, headers)

    def list_candidate_sites(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/candidate-sites", headers=headers, params=params)

    def get_candidate_site(self, site_id: str, headers: dict):
        return self._request("GET", f"/candidate-sites/{site_id}", headers=headers)

    def screen_candidate_site(self, site_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/candidate-sites/{site_id}/screen", payload, headers
        )

    def commit_candidate_site(
        self, site_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/candidate-sites/{site_id}/commit",
            payload if payload is not None else {},
            headers,
        )

    def disqualify_candidate_site(self, site_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/candidate-sites/{site_id}/disqualify", payload, headers
        )

    def list_site_incentive_negotiations(
        self, site_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/candidate-sites/{site_id}/incentive-negotiations",
            headers=headers,
            params=params,
        )

    def list_site_zoning_applications(
        self, site_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/candidate-sites/{site_id}/zoning-applications",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------- interconnection applications --
    def create_interconnection_application(self, payload: dict, headers: dict):
        return self._request(
            "POST", "/interconnection-applications", payload, headers
        )

    def list_interconnection_applications(
        self, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/interconnection-applications", headers=headers, params=params
        )

    def get_interconnection_application(self, application_id: str, headers: dict):
        return self._request(
            "GET", f"/interconnection-applications/{application_id}", headers=headers
        )

    def submit_interconnection_application(
        self, application_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/interconnection-applications/{application_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def create_load_study(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/interconnection-applications/{application_id}/load-studies",
            payload,
            headers,
        )

    def list_load_studies(
        self, application_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/interconnection-applications/{application_id}/load-studies",
            headers=headers,
            params=params,
        )

    def reserve_capacity(
        self, application_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/interconnection-applications/{application_id}/reserve-capacity",
            payload if payload is not None else {},
            headers,
        )

    def commit_energization(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/interconnection-applications/{application_id}/commit-energization",
            payload,
            headers,
        )

    def withdraw_interconnection_application(
        self, application_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/interconnection-applications/{application_id}/withdraw",
            payload,
            headers,
        )

    # ---------------------------------------------------- incentive negotiations --
    def create_incentive_negotiation(self, payload: dict, headers: dict):
        return self._request("POST", "/incentive-negotiations", payload, headers)

    def create_negotiation_round(
        self, negotiation_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST", f"/incentive-negotiations/{negotiation_id}/rounds", payload, headers
        )

    def sign_incentive_negotiation(
        self, negotiation_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/incentive-negotiations/{negotiation_id}/sign",
            payload if payload is not None else {},
            headers,
        )

    def ratify_incentive_negotiation(
        self, negotiation_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/incentive-negotiations/{negotiation_id}/ratify",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------------- zoning applications --
    def create_zoning_application(self, payload: dict, headers: dict):
        return self._request("POST", "/zoning-applications", payload, headers)

    def create_community_objection(
        self, zoning_application_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/zoning-applications/{zoning_application_id}/community-objections",
            payload,
            headers,
        )

    def decide_zoning_application(
        self, zoning_application_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/zoning-applications/{zoning_application_id}/decide",
            payload,
            headers,
        )

    # ------------------------------------------------ power purchase agreements --
    def create_power_purchase_agreement(self, payload: dict, headers: dict):
        return self._request("POST", "/power-purchase-agreements", payload, headers)

    def execute_power_purchase_agreement(
        self, agreement_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/power-purchase-agreements/{agreement_id}/execute",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------ parcel options --
    def create_parcel_option(self, payload: dict, headers: dict):
        return self._request("POST", "/parcel-options", payload, headers)

    def list_parcel_options(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/parcel-options", headers=headers, params=params)

    def get_parcel_option(self, option_id: str, headers: dict):
        return self._request("GET", f"/parcel-options/{option_id}", headers=headers)

    def exercise_parcel_option(
        self, option_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/parcel-options/{option_id}/exercise",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------------------- logical clock --
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
