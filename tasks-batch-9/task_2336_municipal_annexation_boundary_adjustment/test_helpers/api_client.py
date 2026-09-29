"""Typed wrapper over the framework HTTP client — one method per documented
endpoint of the Municipal Annexation And Boundary Adjustment API.

Every method returns the raw ``requests.Response`` so that tests may assert on
success envelopes or on error envelopes with equal ease.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class AnnexationApiClient:
    """Thin, explicit binding of the documented endpoint surface."""

    def __init__(self, client: Optional[GenericApiClient] = None):
        self.client = client or GenericApiClient()

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _body(**fields: Any) -> Dict[str, Any]:
        """Drop keys whose value is ``None`` so optional inputs are omitted
        rather than sent as explicit nulls."""
        return {k: v for k, v in fields.items() if v is not None}

    # ==================================================================
    # Logical clock
    # ==================================================================
    def set_clock(self, headers: Dict[str, str], to_iso8601: str):
        return self.client.post(
            "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # ==================================================================
    # StatuteProfile
    # ==================================================================
    def create_statute_profile(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/statute-profiles", payload, headers=headers)

    def get_statute_profile(self, headers: Dict[str, str], statute_profile_id: str):
        return self.client.get(f"/statute-profiles/{statute_profile_id}", headers=headers)

    # ==================================================================
    # Municipality
    # ==================================================================
    def create_municipality(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/municipalities", payload, headers=headers)

    def get_municipality(self, headers: Dict[str, str], municipality_id: str):
        return self.client.get(f"/municipalities/{municipality_id}", headers=headers)

    def list_municipalities(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/municipalities", params=params or None, headers=headers)

    # ==================================================================
    # ServiceProvider
    # ==================================================================
    def create_service_provider(
        self, headers: Dict[str, str], municipality_id: str, payload: Dict[str, Any]
    ):
        return self.client.post(
            f"/municipalities/{municipality_id}/service-providers", payload, headers=headers
        )

    def get_service_provider(self, headers: Dict[str, str], service_provider_id: str):
        return self.client.get(f"/service-providers/{service_provider_id}", headers=headers)

    def list_service_providers(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/service-providers", params=params or None, headers=headers)

    # ==================================================================
    # PropertyOwner
    # ==================================================================
    def create_property_owner(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/property-owners", payload, headers=headers)

    def get_property_owner(self, headers: Dict[str, str], property_owner_id: str):
        return self.client.get(f"/property-owners/{property_owner_id}", headers=headers)

    # ==================================================================
    # AnnexationCase
    # ==================================================================
    def create_annexation_case(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/annexation-cases", payload, headers=headers)

    def get_annexation_case(self, headers: Dict[str, str], case_id: str):
        return self.client.get(f"/annexation-cases/{case_id}", headers=headers)

    def list_annexation_cases(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/annexation-cases", params=params or None, headers=headers)

    def certify_territory(self, headers: Dict[str, str], case_id: str):
        return self.client.post(
            f"/annexation-cases/{case_id}/certify-territory", {}, headers=headers
        )

    def adopt_ordinance(self, headers: Dict[str, str], case_id: str):
        return self.client.post(
            f"/annexation-cases/{case_id}/adopt-ordinance", {}, headers=headers
        )

    def record_referendum(self, headers: Dict[str, str], case_id: str, result: str):
        return self.client.post(
            f"/annexation-cases/{case_id}/record-referendum",
            {"result": result},
            headers=headers,
        )

    def submit_to_commission(self, headers: Dict[str, str], case_id: str):
        return self.client.post(
            f"/annexation-cases/{case_id}/submit-to-commission", {}, headers=headers
        )

    def commission_decision(self, headers: Dict[str, str], case_id: str, decision: str):
        return self.client.post(
            f"/annexation-cases/{case_id}/commission-decision",
            {"decision": decision},
            headers=headers,
        )

    def effectuate(self, headers: Dict[str, str], case_id: str, effective_date: str):
        return self.client.post(
            f"/annexation-cases/{case_id}/effectuate",
            {"effective_date": effective_date},
            headers=headers,
        )

    def post_tax_roll(self, headers: Dict[str, str], case_id: str):
        return self.client.post(
            f"/annexation-cases/{case_id}/post-tax-roll", {}, headers=headers
        )

    def adopt_msd_alternative(self, headers: Dict[str, str], case_id: str):
        return self.client.post(
            f"/annexation-cases/{case_id}/adopt-msd-alternative", {}, headers=headers
        )

    # ==================================================================
    # Parcel
    # ==================================================================
    def create_parcel(self, headers: Dict[str, str], case_id: str, payload: Dict[str, Any]):
        return self.client.post(
            f"/annexation-cases/{case_id}/parcels", payload, headers=headers
        )

    def get_parcel(self, headers: Dict[str, str], parcel_id: str):
        return self.client.get(f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/parcels", params=params or None, headers=headers)

    def exclude_parcel(self, headers: Dict[str, str], parcel_id: str):
        return self.client.post(f"/parcels/{parcel_id}/exclude", {}, headers=headers)

    # ==================================================================
    # UtilityAccount
    # ==================================================================
    def create_utility_account(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/utility-accounts", payload, headers=headers)

    def get_utility_account(self, headers: Dict[str, str], utility_account_id: str):
        return self.client.get(f"/utility-accounts/{utility_account_id}", headers=headers)

    def list_utility_accounts(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/utility-accounts", params=params or None, headers=headers)

    # ==================================================================
    # Petition
    # ==================================================================
    def create_petition(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/petitions", payload, headers=headers)

    def get_petition(self, headers: Dict[str, str], petition_id: str):
        return self.client.get(f"/petitions/{petition_id}", headers=headers)

    def list_petitions(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/petitions", params=params or None, headers=headers)

    def certify_sufficiency(self, headers: Dict[str, str], petition_id: str):
        return self.client.post(
            f"/petitions/{petition_id}/certify-sufficiency", {}, headers=headers
        )

    # ==================================================================
    # ParcelOwnerConsent
    # ==================================================================
    def create_consent(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/parcel-owner-consents", payload, headers=headers)

    def get_consent(self, headers: Dict[str, str], consent_id: str):
        return self.client.get(f"/parcel-owner-consents/{consent_id}", headers=headers)

    def list_consents(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/parcel-owner-consents", params=params or None, headers=headers)

    def withdraw_consent(self, headers: Dict[str, str], consent_id: str):
        return self.client.post(
            f"/parcel-owner-consents/{consent_id}/withdraw", {}, headers=headers
        )

    # ==================================================================
    # FiscalImpactAnalysis
    # ==================================================================
    def create_fiscal_impact_analysis(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/fiscal-impact-analyses", payload, headers=headers)

    def get_fiscal_impact_analysis(self, headers: Dict[str, str], analysis_id: str):
        return self.client.get(f"/fiscal-impact-analyses/{analysis_id}", headers=headers)

    def list_fiscal_impact_analyses(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/fiscal-impact-analyses", params=params or None, headers=headers)

    def finalize_fiscal_impact_analysis(self, headers: Dict[str, str], analysis_id: str):
        return self.client.post(
            f"/fiscal-impact-analyses/{analysis_id}/finalize", {}, headers=headers
        )

    # ==================================================================
    # PlanOfServices
    # ==================================================================
    def create_plan_of_services(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/plans-of-services", payload, headers=headers)

    def get_plan_of_services(self, headers: Dict[str, str], plan_id: str):
        return self.client.get(f"/plans-of-services/{plan_id}", headers=headers)

    def list_plans_of_services(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/plans-of-services", params=params or None, headers=headers)

    def adopt_plan_of_services(self, headers: Dict[str, str], plan_id: str):
        return self.client.post(f"/plans-of-services/{plan_id}/adopt", {}, headers=headers)

    # ==================================================================
    # ServiceCommitment
    # ==================================================================
    def create_service_commitment(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/service-commitments", payload, headers=headers)

    def get_service_commitment(self, headers: Dict[str, str], commitment_id: str):
        return self.client.get(f"/service-commitments/{commitment_id}", headers=headers)

    def list_service_commitments(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/service-commitments", params=params or None, headers=headers)

    def activate_service_commitment(self, headers: Dict[str, str], commitment_id: str):
        return self.client.post(
            f"/service-commitments/{commitment_id}/activate", {}, headers=headers
        )

    def void_service_commitment(self, headers: Dict[str, str], commitment_id: str):
        return self.client.post(
            f"/service-commitments/{commitment_id}/void", {}, headers=headers
        )

    # ==================================================================
    # PublicHearing
    # ==================================================================
    def create_public_hearing(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/public-hearings", payload, headers=headers)

    def get_public_hearing(self, headers: Dict[str, str], hearing_id: str):
        return self.client.get(f"/public-hearings/{hearing_id}", headers=headers)

    def list_public_hearings(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/public-hearings", params=params or None, headers=headers)

    def hold_hearing(self, headers: Dict[str, str], hearing_id: str):
        return self.client.post(f"/public-hearings/{hearing_id}/hold", {}, headers=headers)

    def close_protest_period(self, headers: Dict[str, str], hearing_id: str):
        return self.client.post(
            f"/public-hearings/{hearing_id}/close-protest-period", {}, headers=headers
        )

    # ==================================================================
    # NoticePublication
    # ==================================================================
    def publish_notice(self, headers: Dict[str, str], hearing_id: str, publication_type: str):
        return self.client.post(
            f"/public-hearings/{hearing_id}/notice-publications",
            {"publication_type": publication_type},
            headers=headers,
        )

    def list_hearing_notices(self, headers: Dict[str, str], hearing_id: str, **params: Any):
        return self.client.get(
            f"/public-hearings/{hearing_id}/notice-publications",
            params=params or None,
            headers=headers,
        )

    def get_notice_publication(self, headers: Dict[str, str], notice_publication_id: str):
        return self.client.get(
            f"/notice-publications/{notice_publication_id}", headers=headers
        )

    def list_notice_publications(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/notice-publications", params=params or None, headers=headers)

    # ==================================================================
    # ProtestFiling
    # ==================================================================
    def create_protest_filing(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.client.post("/protest-filings", payload, headers=headers)

    def get_protest_filing(self, headers: Dict[str, str], filing_id: str):
        return self.client.get(f"/protest-filings/{filing_id}", headers=headers)

    def list_protest_filings(self, headers: Dict[str, str], **params: Any):
        return self.client.get("/protest-filings", params=params or None, headers=headers)

    def withdraw_protest_filing(self, headers: Dict[str, str], filing_id: str):
        return self.client.post(
            f"/protest-filings/{filing_id}/withdraw", {}, headers=headers
        )

    # ==================================================================
    # Raw escape hatches — for tests that must send malformed requests
    # ==================================================================
    def raw_post(self, path: str, payload: Any = None, headers: Optional[Dict[str, str]] = None):
        return self.client.post(path, payload, headers=headers)

    def raw_get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self.client.get(path, params=params, headers=headers)
