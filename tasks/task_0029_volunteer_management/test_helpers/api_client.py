"""API client: one method per endpoint defined in the PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response. Tests pass headers in every call because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every request.

The PRD uses the syntax `/volunteers/{id}/identity:verify` (colon-suffixed
sub-actions). These are passed through verbatim — the colon is a literal
character in the URL, not a delimiter we strip.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Volunteers + identity + background-check
    # =====================================================================
    def create_volunteer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def verify_identity(self, volunteer_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/identity:verify", payload or {}, headers
        )

    def reject_identity(self, volunteer_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/identity:reject", payload or {}, headers
        )

    def request_background_check(self, volunteer_id: str, headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/background-check:request",
            payload or {}, headers,
        )

    def clear_background_check(self, volunteer_id: str, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/background-check:clear",
            payload or {}, headers,
        )

    def fail_background_check(self, volunteer_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/background-check:fail",
            payload or {}, headers,
        )

    def list_volunteer_hours(self, volunteer_id: str, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/hours", headers=headers, params=params
        )

    # =====================================================================
    # Skills + VolunteerSkills
    # =====================================================================
    def create_skill(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/skills", payload, headers)

    def list_skills(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/skills", headers=headers, params=params)

    def declare_skill(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/volunteer-skills", payload, headers)

    def submit_volunteer_skill(self, vskill_id: str, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/volunteer-skills/{vskill_id}/submit", payload or {}, headers
        )

    def approve_volunteer_skill(self, vskill_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/volunteer-skills/{vskill_id}/approve", payload or {}, headers
        )

    def reject_volunteer_skill(self, vskill_id: str, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/volunteer-skills/{vskill_id}/reject", payload or {}, headers
        )

    def resubmit_volunteer_skill(self, vskill_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/volunteer-skills/{vskill_id}/resubmit", payload, headers
        )

    # =====================================================================
    # Activities + ActivityRoles
    # =====================================================================
    def create_activity(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/activities", payload, headers)

    def submit_activity(self, activity_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/activities/{activity_id}/submit", payload or {}, headers
        )

    def approve_activity(self, activity_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/activities/{activity_id}/approve", payload or {}, headers
        )

    def reject_activity(self, activity_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/activities/{activity_id}/reject", payload or {}, headers
        )

    def revise_activity(self, activity_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/activities/{activity_id}/revise", payload or {}, headers
        )

    def shelve_activity(self, activity_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/activities/{activity_id}/shelve", payload or {}, headers
        )

    def get_activity(self, activity_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/activities/{activity_id}", headers=headers)

    def list_activities(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/activities", headers=headers, params=params)

    def define_activity_role(self, activity_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/activities/{activity_id}/roles", payload, headers
        )

    def get_recommended_volunteers(self, activity_id: str, headers: Dict[str, str],
                                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/activities/{activity_id}/recommended-volunteers",
            headers=headers, params=params,
        )

    # =====================================================================
    # Applications
    # =====================================================================
    def apply_to_activity(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/applications", payload, headers)

    def approve_application(self, application_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/approve", payload or {}, headers
        )

    def reject_application(self, application_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/reject", payload or {}, headers
        )

    def withdraw_application(self, application_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", payload or {}, headers
        )

    def check_in(self, application_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/check-in", payload, headers
        )

    def request_leave(self, application_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/leave", payload, headers
        )

    def check_out(self, application_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/check-out", payload or {}, headers
        )

    def manual_correction(self, application_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/manual-correction",
            payload, headers,
        )

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/applications/{application_id}", headers=headers
        )

    # =====================================================================
    # Hour adjustments
    # =====================================================================
    def file_hour_adjustment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hour-adjustments", payload, headers)

    def approve_hour_adjustment(self, adj_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/hour-adjustments/{adj_id}/approve", payload or {}, headers
        )

    def reject_hour_adjustment(self, adj_id: str, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/hour-adjustments/{adj_id}/reject", payload or {}, headers
        )

    # =====================================================================
    # Point mall + redemptions
    # =====================================================================
    def create_point_mall_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/point-mall-items", payload, headers)

    def restock_point_mall_item(self, item_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/point-mall-items/{item_id}/restock", payload, headers
        )

    def archive_point_mall_item(self, item_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/point-mall-items/{item_id}/archive", payload or {}, headers
        )

    def list_point_mall_items(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/point-mall-items", headers=headers, params=params
        )

    def create_redemption_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/redemption-orders", payload, headers)

    def fulfill_redemption_order(self, order_id: str, headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/redemption-orders/{order_id}/fulfill", payload or {}, headers
        )

    def cancel_redemption_order(self, order_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/redemption-orders/{order_id}/cancel", payload or {}, headers
        )

    # =====================================================================
    # Certificates
    # =====================================================================
    def create_certificate_template(self, payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request("POST", "/certificate-templates", payload, headers)

    def issue_certificate(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/certificates", payload, headers)

    def issue_certificates_batch(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", "/certificates/batch", payload, headers)

    def reissue_certificate(self, certificate_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/certificates/{certificate_id}/reissue", payload or {}, headers
        )

    def revoke_certificate(self, certificate_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/certificates/{certificate_id}/revoke", payload or {}, headers
        )

    def verify_certificate(self, serial_number: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/certificates/verify/{serial_number}", headers=headers
        )

    # =====================================================================
    # Audit + Sync
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    def list_partner_sync_events(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/partner-sync-events", headers=headers, params=params
        )

    # =====================================================================
    # Test-driving clock
    # =====================================================================
    def advance_clock(self, target_time: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"target_time": target_time}, headers
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
