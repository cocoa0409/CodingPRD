"""API client: one method per endpoint defined in the PRD routing table."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/licensing"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Product categories
    # ------------------------------------------------------------------

    def create_product_category(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/product-categories", payload, headers)

    def list_product_categories(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/product-categories", headers=headers, params=params)

    def get_product_category(self, category_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/product-categories/{category_id}", headers=headers)

    def patch_product_category(self, category_id: str, payload: dict, headers: dict):
        return self._request(
            "PATCH", f"{PREFIX}/product-categories/{category_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Clubs and players
    # ------------------------------------------------------------------

    def create_club(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/clubs", payload, headers)

    def list_clubs(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/clubs", headers=headers, params=params)

    def get_club(self, club_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/clubs/{club_id}", headers=headers)

    def patch_club(self, club_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"{PREFIX}/clubs/{club_id}", payload, headers)

    def create_player(self, club_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/clubs/{club_id}/players", payload, headers)

    def list_players(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/players", headers=headers, params=params)

    def get_player(self, player_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/players/{player_id}", headers=headers)

    def set_group_licensing(self, player_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/players/{player_id}/group-licensing", payload, headers
        )

    def set_individual_grant(self, player_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/players/{player_id}/individual-grants", payload, headers
        )

    # ------------------------------------------------------------------
    # Mark rights
    # ------------------------------------------------------------------

    def create_mark_right(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/mark-rights", payload, headers)

    def list_mark_rights(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/mark-rights", headers=headers, params=params)

    def get_mark_right(self, mark_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/mark-rights/{mark_id}", headers=headers)

    def set_mark_right_status(self, mark_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/mark-rights/{mark_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Licensees
    # ------------------------------------------------------------------

    def create_licensee(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/licensees", payload, headers)

    def list_licensees(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/licensees", headers=headers, params=params)

    def get_licensee(self, licensee_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/licensees/{licensee_id}", headers=headers)

    def set_licensee_status(self, licensee_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/licensees/{licensee_id}/status", payload, headers)

    def get_licensee_risk_index(
        self, licensee_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/licensees/{licensee_id}/risk-index", headers=headers, params=params
        )

    def create_retailer_authorization(self, licensee_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/licensees/{licensee_id}/retailer-authorizations", payload, headers
        )

    # ------------------------------------------------------------------
    # License agreements
    # ------------------------------------------------------------------

    def create_agreement(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def list_agreements(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def patch_agreement(self, agreement_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"{PREFIX}/agreements/{agreement_id}", payload, headers)

    def set_contract_status(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/contract-status", payload, headers
        )

    def create_advance_payment(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/advance-payments", payload, headers
        )

    def annual_true_up(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/annual-true-up", payload, headers
        )

    def create_territory_grant(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/territory-grants", payload, headers
        )

    def list_territory_grants(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/territory-grants", headers=headers, params=params)

    def get_territory_grant(self, grant_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/territory-grants/{grant_id}", headers=headers)

    def set_territory_grant_status(self, grant_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/territory-grants/{grant_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Product submissions and sample reviews
    # ------------------------------------------------------------------

    def create_product_submission(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/product-submissions", payload, headers
        )

    def list_product_submissions(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/product-submissions", headers=headers, params=params)

    def get_product_submission(self, submission_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/product-submissions/{submission_id}", headers=headers
        )

    def patch_product_submission(self, submission_id: str, payload: dict, headers: dict):
        return self._request(
            "PATCH", f"{PREFIX}/product-submissions/{submission_id}", payload, headers
        )

    def submit_product_submission(self, submission_id: str, payload: Optional[dict], headers: dict):
        return self._request(
            "POST", f"{PREFIX}/product-submissions/{submission_id}/submit", payload, headers
        )

    def create_submission_review_decision(self, submission_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/product-submissions/{submission_id}/review-decisions",
            payload,
            headers,
        )

    def create_sample_review(self, submission_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/product-submissions/{submission_id}/sample-reviews", payload, headers
        )

    def list_sample_reviews(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/sample-reviews", headers=headers, params=params)

    def get_sample_review(self, sample_review_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/sample-reviews/{sample_review_id}", headers=headers)

    # ------------------------------------------------------------------
    # Retailer authorizations
    # ------------------------------------------------------------------

    def list_retailer_authorizations(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/retailer-authorizations", headers=headers, params=params
        )

    def get_retailer_authorization(self, authorization_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/retailer-authorizations/{authorization_id}", headers=headers
        )

    def set_retailer_authorization_status(self, authorization_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/retailer-authorizations/{authorization_id}/status",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Royalty reports
    # ------------------------------------------------------------------

    def create_royalty_report(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/royalty-reports", payload, headers)

    def list_royalty_reports(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/royalty-reports", headers=headers, params=params)

    def get_royalty_report(self, report_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/royalty-reports/{report_id}", headers=headers)

    def patch_royalty_report(self, report_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"{PREFIX}/royalty-reports/{report_id}", payload, headers)

    def file_royalty_report(self, report_id: str, payload: Optional[dict], headers: dict):
        return self._request("POST", f"{PREFIX}/royalty-reports/{report_id}/file", payload, headers)

    def create_report_review_decision(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/royalty-reports/{report_id}/review-decisions", payload, headers
        )

    # ------------------------------------------------------------------
    # Audit engagements
    # ------------------------------------------------------------------

    def create_audit_engagement(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/audit-engagements", payload, headers)

    def list_audit_engagements(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/audit-engagements", headers=headers, params=params)

    def get_audit_engagement(self, engagement_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/audit-engagements/{engagement_id}", headers=headers)

    def begin_fieldwork(self, engagement_id: str, payload: Optional[dict], headers: dict):
        return self._request(
            "POST", f"{PREFIX}/audit-engagements/{engagement_id}/begin-fieldwork", payload, headers
        )

    def issue_findings(self, engagement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/audit-engagements/{engagement_id}/issue-findings", payload, headers
        )

    def dispute_engagement(self, engagement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/audit-engagements/{engagement_id}/dispute", payload, headers
        )

    def settle_engagement(self, engagement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/audit-engagements/{engagement_id}/settle", payload, headers
        )

    def close_engagement(self, engagement_id: str, payload: Optional[dict], headers: dict):
        return self._request(
            "POST", f"{PREFIX}/audit-engagements/{engagement_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Enforcement actions
    # ------------------------------------------------------------------

    def create_enforcement_action(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/enforcement-actions", payload, headers)

    def list_enforcement_actions(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/enforcement-actions", headers=headers, params=params)

    def get_enforcement_action(self, action_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/enforcement-actions/{action_id}", headers=headers)

    def set_enforcement_action_status(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/enforcement-actions/{action_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Distribution runs and club distributions
    # ------------------------------------------------------------------

    def create_distribution_run(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/distribution-runs", payload, headers)

    def list_distribution_runs(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/distribution-runs", headers=headers, params=params)

    def get_distribution_run(self, run_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/distribution-runs/{run_id}", headers=headers)

    def lock_distribution_run(self, run_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/distribution-runs/{run_id}/lock", payload, headers
        )

    def unlock_distribution_run(self, run_id: str, payload: Optional[dict], headers: dict):
        return self._request(
            "POST", f"{PREFIX}/distribution-runs/{run_id}/unlock", payload, headers
        )

    def distribute_run(self, run_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/distribution-runs/{run_id}/distribute", payload, headers
        )

    def list_club_distributions(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/club-distributions", headers=headers, params=params)

    def get_club_distribution(self, distribution_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/club-distributions/{distribution_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def quarter_close(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/ops/quarter-close", payload, headers)


api_client = ApiClient()
