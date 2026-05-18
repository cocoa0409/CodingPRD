"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Consumer — PRD §3.1, §4
    # =======================================================================
    def create_consumer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/consumers", payload, headers)

    def get_consumer(self, consumer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/consumers/{consumer_id}", headers=headers,
        )

    def get_consumer_risk(self, consumer_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/consumers/{consumer_id}/risk", headers=headers,
        )

    # =======================================================================
    # Furnisher — PRD §3.1, §4
    # =======================================================================
    def create_furnisher(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/furnishers", payload, headers)

    def get_furnisher(self, furnisher_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/furnishers/{furnisher_id}", headers=headers,
        )

    # =======================================================================
    # CreditReport — PRD §3.1, §3.5, §3.9, §3.14, §4
    # =======================================================================
    def create_credit_report(self, consumer_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/consumers/{consumer_id}/credit_reports",
            payload, headers,
        )

    def get_credit_report(self, consumer_id: str,
                          credit_report_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/consumers/{consumer_id}/credit_reports/{credit_report_id}",
            headers=headers,
        )

    def get_projected_fico(self, consumer_id: str,
                           credit_report_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/consumers/{consumer_id}/credit_reports/"
            f"{credit_report_id}/projected_fico",
            headers=headers,
        )

    def pull_free_credit_report(self, consumer_id: str,
                                credit_report_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/credit_reports/"
            f"{credit_report_id}/pull_free",
            payload if payload is not None else {}, headers,
        )

    def archive_credit_report(self, consumer_id: str,
                              credit_report_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/credit_reports/"
            f"{credit_report_id}/archive",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # TradelineItem — PRD §3.1, §4
    # =======================================================================
    def create_tradeline_item(self, credit_report_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/credit_reports/{credit_report_id}/tradeline_items",
            payload, headers,
        )

    def get_tradeline_item(self, credit_report_id: str,
                           tradeline_item_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/credit_reports/{credit_report_id}/tradeline_items/"
            f"{tradeline_item_id}",
            headers=headers,
        )

    # =======================================================================
    # Dispute — PRD §3.2 – §3.4, §4
    # =======================================================================
    def create_dispute(self, consumer_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/consumers/{consumer_id}/disputes",
            payload, headers,
        )

    def get_dispute(self, consumer_id: str, dispute_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/consumers/{consumer_id}/disputes/{dispute_id}",
            headers=headers,
        )

    def start_investigation(self, consumer_id: str, dispute_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/disputes/{dispute_id}/"
            f"start_investigation",
            payload if payload is not None else {}, headers,
        )

    def submit_additional_info(self, consumer_id: str, dispute_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/disputes/{dispute_id}/"
            f"additional_info",
            payload, headers,
        )

    def record_furnisher_response(self, consumer_id: str,
                                  dispute_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/disputes/{dispute_id}/"
            f"furnisher_response",
            payload, headers,
        )

    def issue_result_notice(self, consumer_id: str, dispute_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/disputes/{dispute_id}/"
            f"issue_result_notice",
            payload if payload is not None else {}, headers,
        )

    def dismiss_frivolous(self, consumer_id: str, dispute_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/disputes/{dispute_id}/"
            f"dismiss_frivolous",
            payload if payload is not None else {}, headers,
        )

    def get_result_notice(self, consumer_id: str, dispute_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/consumers/{consumer_id}/disputes/{dispute_id}/"
            f"result_notice",
            headers=headers,
        )

    # =======================================================================
    # RegulatoryComplaint — PRD §3.10, §4
    # =======================================================================
    def create_regulatory_complaint(self, consumer_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/regulatory_complaints",
            payload, headers,
        )

    def get_regulatory_complaint(self, complaint_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/regulatory_complaints/{complaint_id}",
            headers=headers,
        )

    def accept_complaint(self, complaint_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/regulatory_complaints/{complaint_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def reject_complaint(self, complaint_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/regulatory_complaints/{complaint_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def resolve_complaint(self, complaint_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/regulatory_complaints/{complaint_id}/resolve",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # CreditFreeze — PRD §3.11, §4
    # =======================================================================
    def create_credit_freeze(self, consumer_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/consumers/{consumer_id}/credit_freezes",
            payload, headers,
        )

    def get_credit_freeze(self, consumer_id: str, freeze_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/consumers/{consumer_id}/credit_freezes/{freeze_id}",
            headers=headers,
        )

    def lift_credit_freeze(self, consumer_id: str, freeze_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/credit_freezes/{freeze_id}/lift",
            payload, headers,
        )

    # =======================================================================
    # CreditLock — PRD §3.11, §4
    # =======================================================================
    def create_credit_lock(self, consumer_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/consumers/{consumer_id}/credit_locks",
            payload, headers,
        )

    def unlock_credit_lock(self, consumer_id: str, lock_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/credit_locks/{lock_id}/unlock",
            payload if payload is not None else {}, headers,
        )

    def relock_credit_lock(self, consumer_id: str, lock_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/consumers/{consumer_id}/credit_locks/{lock_id}/relock",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # HardInquiry — PRD §3.12, §4
    # =======================================================================
    def create_hard_inquiry(self, credit_report_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/credit_reports/{credit_report_id}/hard_inquiries",
            payload, headers,
        )

    # =======================================================================
    # Test-driving system endpoints — PRD §2.4, §2.11, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    def sweep_run(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
