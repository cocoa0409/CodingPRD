"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
``X-User-Role`` and ``X-User-ID`` on every call.

All endpoint paths share the ``/scf`` prefix as declared in PRD §4.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # CoreEnterprise (PRD §3.1, §4)
    # =======================================================================
    def create_core_enterprise(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", "/scf/core-enterprises",
                             payload, headers)

    def get_core_enterprise(self, ce_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/scf/core-enterprises/{ce_id}",
                             headers=headers)

    def approve_core_enterprise(self, ce_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST",
                             f"/scf/core-enterprises/{ce_id}/approve",
                             payload, headers)

    def reject_core_enterprise(self, ce_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/scf/core-enterprises/{ce_id}/reject",
                             payload or {}, headers)

    def suspend_core_enterprise(self, ce_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST",
                             f"/scf/core-enterprises/{ce_id}/suspend",
                             payload, headers)

    def reinstate_core_enterprise(self, ce_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/scf/core-enterprises/{ce_id}/reinstate",
                             payload or {}, headers)

    # =======================================================================
    # Supplier (PRD §3.2, §4)
    # =======================================================================
    def create_supplier(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/scf/suppliers", payload, headers)

    def kyc_supplier(self, supplier_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST",
                             f"/scf/suppliers/{supplier_id}/kyc",
                             payload, headers)

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/scf/suppliers/{supplier_id}",
                             headers=headers)

    # =======================================================================
    # PayableConfirmation (PRD §3.3, §4)
    # =======================================================================
    def create_payable_confirmation(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request("POST", "/scf/payable-confirmations",
                             payload, headers)

    def confirm_payable_confirmation(self, conf_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/scf/payable-confirmations/{conf_id}/confirm",
                             payload or {}, headers)

    def revoke_payable_confirmation(self, conf_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request("POST",
                             f"/scf/payable-confirmations/{conf_id}/revoke",
                             payload, headers)

    def list_payable_confirmations(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/scf/payable-confirmations",
                             headers=headers, params=params)

    def get_payable_confirmation(self, conf_id: str,
                                 headers: Dict[str, str]):
        return self._request("GET",
                             f"/scf/payable-confirmations/{conf_id}",
                             headers=headers)

    # =======================================================================
    # Receivable (PRD §3.4, §4)
    # =======================================================================
    def create_receivable(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/scf/receivables", payload, headers)

    def central_registry_file(self, receivable_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scf/receivables/{receivable_id}/central-registry-file",
            payload, headers,
        )

    def pledge_receivable(self, receivable_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/scf/receivables/{receivable_id}/pledge",
                             payload or {}, headers)

    def transfer_receivable(self, receivable_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST",
                             f"/scf/receivables/{receivable_id}/transfer",
                             payload, headers)

    def get_receivable(self, receivable_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/scf/receivables/{receivable_id}",
                             headers=headers)

    def list_receivables(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/scf/receivables",
                             headers=headers, params=params)

    # =======================================================================
    # TradeBackgroundVerification (PRD §3.9, §4)
    # =======================================================================
    def create_verification(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/scf/verifications", payload, headers)

    def verification_on_site(self, verification_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/scf/verifications/{verification_id}/on-site",
                             payload or {}, headers)

    def finalize_verification(self, verification_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scf/verifications/{verification_id}/finalize",
            payload or {}, headers,
        )

    # =======================================================================
    # FinancingApplication (PRD §3.5, §4)
    # =======================================================================
    def create_financing_application(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request("POST", "/scf/financing-applications",
                             payload, headers)

    def submit_financing_application(self, app_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scf/financing-applications/{app_id}/submit",
            payload or {}, headers,
        )

    def start_review_financing_application(self, app_id: str,
                                           headers: Dict[str, str],
                                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scf/financing-applications/{app_id}/start-review",
            payload or {}, headers,
        )

    def return_financing_application(self, app_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scf/financing-applications/{app_id}/return",
            payload, headers,
        )

    def approve_financing_application(self, app_id: str,
                                      payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scf/financing-applications/{app_id}/approve",
            payload, headers,
        )

    def reject_financing_application(self, app_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scf/financing-applications/{app_id}/reject",
            payload, headers,
        )

    def get_financing_application(self, app_id: str,
                                  headers: Dict[str, str]):
        return self._request("GET",
                             f"/scf/financing-applications/{app_id}",
                             headers=headers)

    def list_financing_applications(self, headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/scf/financing-applications",
                             headers=headers, params=params)

    # =======================================================================
    # Disbursement (PRD §3.6, §4)
    # =======================================================================
    def create_disbursement(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/scf/disbursements", payload, headers)

    def reconcile_disbursement(self, disbursement_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scf/disbursements/{disbursement_id}/reconcile",
            payload or {}, headers,
        )

    def get_disbursement(self, disbursement_id: str,
                         headers: Dict[str, str]):
        return self._request("GET",
                             f"/scf/disbursements/{disbursement_id}",
                             headers=headers)

    # =======================================================================
    # RepaymentSchedule (PRD §3.7, §4)
    # =======================================================================
    def get_repayment_schedule(self, schedule_id: str,
                               headers: Dict[str, str]):
        return self._request("GET",
                             f"/scf/repayment-schedules/{schedule_id}",
                             headers=headers)

    def repay_repayment_schedule(self, schedule_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scf/repayment-schedules/{schedule_id}/repay",
            payload, headers,
        )

    # =======================================================================
    # CollectionCase (PRD §3.8, §4)
    # =======================================================================
    def remind_collection_case(self, case_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scf/collection-cases/{case_id}/remind",
            payload or {}, headers,
        )

    def escalate_collection_case(self, case_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scf/collection-cases/{case_id}/escalate",
            payload or {}, headers,
        )

    def invoke_joint_liability(self, case_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scf/collection-cases/{case_id}/invoke-joint-liability",
            payload or {}, headers,
        )

    def legal_collection_case(self, case_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scf/collection-cases/{case_id}/legal",
            payload or {}, headers,
        )

    def write_off_collection_case(self, case_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scf/collection-cases/{case_id}/write-off",
            payload, headers,
        )

    def get_collection_case(self, case_id: str,
                            headers: Dict[str, str]):
        return self._request("GET",
                             f"/scf/collection-cases/{case_id}",
                             headers=headers)

    # =======================================================================
    # Audit logs (PRD §3.10, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/scf/audit-logs",
                             headers=headers, params=params)

    # =======================================================================
    # Test-driving capabilities (PRD §3.10, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/scf/_clock/advance",
                             payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", "/scf/_sweep/run",
                             payload or {}, headers)

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/scf/_events/emit",
                             payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
