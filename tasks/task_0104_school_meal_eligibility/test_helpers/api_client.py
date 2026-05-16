"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # District — PRD §3.1
    # =======================================================================
    def create_district(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/districts", payload, headers)

    def get_district(self, district_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/districts/{district_id}", headers=headers,
        )

    # =======================================================================
    # ParentAccount — PRD §3.1, §3.6
    # =======================================================================
    def create_parent_account(self, district_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/districts/{district_id}/parent-accounts",
            payload, headers,
        )

    def get_parent_account(self, district_id: str, account_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/districts/{district_id}/parent-accounts/{account_id}",
            headers=headers,
        )

    def top_up_parent_account(self, district_id: str, account_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/parent-accounts/{account_id}/top-up",
            payload, headers,
        )

    def refund_parent_account(self, district_id: str, account_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/parent-accounts/{account_id}/refund",
            payload, headers,
        )

    # =======================================================================
    # Student — PRD §3.1
    # =======================================================================
    def create_student(self, district_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/districts/{district_id}/students", payload, headers,
        )

    def get_student(self, district_id: str, student_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/districts/{district_id}/students/{student_id}",
            headers=headers,
        )

    # =======================================================================
    # AllergyProfileEntry — PRD §3.2
    # =======================================================================
    def create_allergy_entry(self, district_id: str, student_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/allergy-entries",
            payload, headers,
        )

    def delete_allergy_entry(self, district_id: str, student_id: str,
                             entry_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/districts/{district_id}/students/{student_id}"
            f"/allergy-entries/{entry_id}",
            headers=headers,
        )

    # =======================================================================
    # FrlApplication — PRD §3.4, §3.5
    # =======================================================================
    def create_frl_application(self, district_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/districts/{district_id}/frl-applications",
            payload, headers,
        )

    def get_frl_application(self, district_id: str, app_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/districts/{district_id}/frl-applications/{app_id}",
            headers=headers,
        )

    def submit_frl_application(self, district_id: str, app_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/frl-applications/{app_id}/submit",
            {}, headers,
        )

    def request_info_frl_application(self, district_id: str, app_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/frl-applications/{app_id}/request-info",
            payload, headers,
        )

    def resubmit_frl_application(self, district_id: str, app_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/frl-applications/{app_id}/resubmit",
            payload, headers,
        )

    def approve_frl_application(self, district_id: str, app_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/frl-applications/{app_id}/approve",
            {}, headers,
        )

    def deny_frl_application(self, district_id: str, app_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/frl-applications/{app_id}/deny",
            payload, headers,
        )

    def auto_renew_frl_application(self, district_id: str, app_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/frl-applications/{app_id}/auto-renew",
            {}, headers,
        )

    # =======================================================================
    # MenuItem — PRD §3.3
    # =======================================================================
    def create_menu_item(self, district_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/districts/{district_id}/menu-items",
            payload, headers,
        )

    def get_nutrition_label(self, district_id: str, menu_item_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/districts/{district_id}/menu-items/{menu_item_id}"
            f"/nutrition-label",
            headers=headers,
        )

    def retire_menu_item(self, district_id: str, menu_item_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/menu-items/{menu_item_id}/retire",
            {}, headers,
        )

    # =======================================================================
    # MealServingRecord — PRD §3.6
    # =======================================================================
    def create_meal_serving(self, district_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/districts/{district_id}/meal-servings",
            payload, headers,
        )

    def void_meal_serving(self, district_id: str, serving_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/meal-servings/{serving_id}/void",
            {}, headers,
        )

    # =======================================================================
    # UsdaReimbursementClaim — PRD §3.7
    # =======================================================================
    def create_usda_claim(self, district_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/districts/{district_id}/usda-claims",
            payload, headers,
        )

    def get_usda_claim(self, district_id: str, claim_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/districts/{district_id}/usda-claims/{claim_id}",
            headers=headers,
        )

    def submit_usda_claim(self, district_id: str, claim_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/usda-claims/{claim_id}/submit",
            {}, headers,
        )

    def finalize_usda_claim(self, district_id: str, claim_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/usda-claims/{claim_id}/finalize",
            {}, headers,
        )

    def reject_usda_claim(self, district_id: str, claim_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/usda-claims/{claim_id}/reject",
            {}, headers,
        )

    # =======================================================================
    # Test-driving clock — PRD §2.8 (AuditOfficer only)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
