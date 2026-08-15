"""API client: one method per endpoint defined in PRD §4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            "/rights/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # --- RightsHolder ---
    def create_rights_holder(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/rights/rights-holders", payload, headers)

    def get_rights_holder(self, holder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rights/rights-holders/{holder_id}", headers=headers)

    def list_rights_holders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/rights/rights-holders", headers=headers, params=params)

    # --- Asset ---
    def create_asset(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/rights/assets", payload, headers)

    def get_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rights/assets/{asset_id}", headers=headers)

    def list_assets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/rights/assets", headers=headers, params=params)

    def retire_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/rights/assets/{asset_id}/retire", {}, headers)

    # --- RightsDiligenceLog ---
    def append_diligence_log(self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/rights/assets/{asset_id}/diligence-logs", payload, headers)

    def list_diligence_logs(self, asset_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/rights/assets/{asset_id}/diligence-logs", headers=headers, params=params
        )

    # --- ClearanceRequest ---
    def create_clearance_request(self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/assets/{asset_id}/clearance-requests", payload, headers
        )

    def get_clearance_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rights/clearance-requests/{request_id}", headers=headers)

    def list_clearance_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/rights/clearance-requests", headers=headers, params=params)

    def list_asset_clearance_requests(
        self, asset_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/rights/assets/{asset_id}/clearance-requests",
            headers=headers,
            params=params,
        )

    def advance_clearance_request(
        self, request_id: str, expected_clearance_version: int, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/rights/clearance-requests/{request_id}/advance",
            {"expected_clearance_version": expected_clearance_version},
            headers,
        )

    def deny_clearance_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/rights/clearance-requests/{request_id}/deny", {}, headers)

    def withdraw_clearance_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/clearance-requests/{request_id}/withdraw", {}, headers
        )

    def grant_license(self, request_id: str, grant_fee_cents: int, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/rights/clearance-requests/{request_id}/grant",
            {"grant_fee_cents": grant_fee_cents},
            headers,
        )

    # --- NegotiationRound ---
    def post_round(self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/clearance-requests/{request_id}/rounds", payload, headers
        )

    def list_rounds(self, request_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/rights/clearance-requests/{request_id}/rounds", headers=headers, params=params
        )

    # --- License ---
    def get_license(self, license_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rights/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/rights/licenses", headers=headers, params=params)

    def revoke_license(self, license_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/rights/licenses/{license_id}/revoke", {}, headers)

    # --- UsageReservation ---
    def create_reservation(self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/licenses/{license_id}/usage-reservations", payload, headers
        )

    def list_reservations(
        self, license_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/rights/licenses/{license_id}/usage-reservations",
            headers=headers,
            params=params,
        )

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rights/usage-reservations/{reservation_id}", headers=headers)

    def list_reservation_usage_events(
        self, reservation_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/rights/usage-reservations/{reservation_id}/usage-events",
            headers=headers,
            params=params,
        )

    def release_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/usage-reservations/{reservation_id}/release", {}, headers
        )

    # --- UsageEvent ---
    def post_usage_event(self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/licenses/{license_id}/usage-events", payload, headers
        )

    def list_usage_events(
        self, license_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/rights/licenses/{license_id}/usage-events", headers=headers, params=params
        )

    # --- LicensePayment ---
    def post_payment(self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/rights/licenses/{license_id}/payments", payload, headers)

    def list_payments(
        self, license_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/rights/licenses/{license_id}/payments", headers=headers, params=params
        )

    # --- FairUseAssessment ---
    def create_fair_use_assessment(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/rights/assets/{asset_id}/fair-use-assessments", payload, headers
        )

    def get_fair_use_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/rights/fair-use-assessments/{assessment_id}", headers=headers
        )

    def list_asset_fair_use_assessments(
        self, asset_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/rights/assets/{asset_id}/fair-use-assessments",
            headers=headers,
            params=params,
        )

    def list_fair_use_assessments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/rights/fair-use-assessments", headers=headers, params=params)

    def certify_fair_use_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/fair-use-assessments/{assessment_id}/certify", {}, headers
        )

    def reject_fair_use_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/fair-use-assessments/{assessment_id}/reject", {}, headers
        )

    # --- TakedownNotice ---
    def file_takedown_notice(self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/assets/{asset_id}/takedown-notices", payload, headers
        )

    def list_takedown_notices(
        self, asset_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/rights/assets/{asset_id}/takedown-notices", headers=headers, params=params
        )

    def get_takedown_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rights/takedown-notices/{notice_id}", headers=headers)

    def counter_takedown_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/takedown-notices/{notice_id}/counter", {}, headers
        )

    def retract_takedown_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rights/takedown-notices/{notice_id}/retract", {}, headers
        )

    # --- RenewalAlert ---
    def list_license_renewal_alerts(
        self, license_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/rights/licenses/{license_id}/renewal-alerts", headers=headers, params=params
        )

    def list_renewal_alerts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/rights/renewal-alerts", headers=headers, params=params)


api_client = ApiClient()
