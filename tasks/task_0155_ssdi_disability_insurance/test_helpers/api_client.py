"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.

Paths are verbatim from PRD §4 endpoint table.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clock — PRD §2.10, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    # =======================================================================
    # Claimants — PRD §3.1, §4
    # =======================================================================
    def create_claimant(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/claimants", payload, headers)

    def get_claimant(self, claimant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/claimants/{claimant_id}", headers=headers,
        )

    def patch_claimant(self, claimant_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/claimants/{claimant_id}", payload, headers,
        )

    # =======================================================================
    # Quarter credits — PRD §3.1, §4
    # =======================================================================
    def create_quarter_credit(self, claimant_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/claimants/{claimant_id}/quarter-credits",
            payload, headers,
        )

    def list_quarter_credits(self, claimant_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/claimants/{claimant_id}/quarter-credits",
            headers=headers, params=params,
        )

    # =======================================================================
    # Medical evidence — PRD §3.3, §4
    # =======================================================================
    def create_medical_evidence(self, claimant_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/claimants/{claimant_id}/medical-evidence",
            payload, headers,
        )

    def accept_medical_evidence(self, claimant_id: str, evidence_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/claimants/{claimant_id}/medical-evidence/{evidence_id}/accept",
            None, headers,
        )

    def reject_medical_evidence(self, claimant_id: str, evidence_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/claimants/{claimant_id}/medical-evidence/{evidence_id}/reject",
            None, headers,
        )

    # =======================================================================
    # Application — PRD §3.3, §3.4, §3.6, §4
    # =======================================================================
    def create_application(self, claimant_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claimants/{claimant_id}/applications",
            payload or {}, headers,
        )

    def submit_application(self, claimant_id: str, app_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/claimants/{claimant_id}/applications/{app_id}/submit",
            None, headers,
        )

    def get_application(self, claimant_id: str, app_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/claimants/{claimant_id}/applications/{app_id}",
            headers=headers,
        )

    def create_determination(self, claimant_id: str, app_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/claimants/{claimant_id}/applications/{app_id}/determinations",
            payload, headers,
        )

    def list_determinations(self, claimant_id: str, app_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/claimants/{claimant_id}/applications/{app_id}/determinations",
            headers=headers, params=params,
        )

    def appeal_application(self, claimant_id: str, app_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/claimants/{claimant_id}/applications/{app_id}/appeal",
            payload, headers,
        )

    # =======================================================================
    # Hearing slots — PRD §3.7, §4
    # =======================================================================
    def create_hearing_slot(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/hearing-slots", payload, headers)

    def list_hearing_slots(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/hearing-slots", headers=headers, params=params,
        )

    def book_hearing_slot(self, slot_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/hearing-slots/{slot_id}/book", payload, headers,
        )

    def hold_hearing_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/hearing-slots/{slot_id}/hold", None, headers,
        )

    def no_show_hearing_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/hearing-slots/{slot_id}/no-show", None, headers,
        )

    def reschedule_hearing_slot(self, slot_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/hearing-slots/{slot_id}/reschedule", payload, headers,
        )

    # =======================================================================
    # Child auxiliaries — PRD §3.5, §4
    # =======================================================================
    def create_child_auxiliary(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/child-auxiliaries", payload, headers,
        )

    def entitle_child_auxiliary(self, child_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/child-auxiliaries/{child_id}/entitle",
            None, headers,
        )

    def terminate_child_auxiliary(self, child_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/child-auxiliaries/{child_id}/terminate",
            payload, headers,
        )

    def list_child_auxiliaries(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/child-auxiliaries", headers=headers, params=params,
        )

    # =======================================================================
    # SSI supplements — PRD §3.5, §4
    # =======================================================================
    def create_ssi_supplement(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/ssi-supplements", payload, headers,
        )

    def activate_ssi_supplement(self, supplement_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/ssi-supplements/{supplement_id}/activate",
            None, headers,
        )

    def patch_ssi_supplement(self, supplement_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/ssi-supplements/{supplement_id}", payload, headers,
        )

    # =======================================================================
    # CDR reviews — PRD §3.8, §4
    # =======================================================================
    def list_cdr_reviews(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/cdr-reviews", headers=headers, params=params,
        )

    def schedule_cdr_review(self, cdr_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cdr-reviews/{cdr_id}/schedule", None, headers,
        )

    def complete_cdr_review(self, cdr_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/cdr-reviews/{cdr_id}/complete", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
