"""API client: one method per endpoint defined in the PRD §4.

All endpoints are mounted under /pet-hospital per PRD §1. Headers are
mandatory on every request because PRD §2.1 requires X-User-ID and
X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


_PFX = "/pet-hospital"


class ApiClient(GenericApiClient):
    # =====================================================================
    # Owners
    # =====================================================================
    def create_owner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/owners", payload, headers)

    def get_owner(self, owner_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PFX}/owners/{owner_id}", headers=headers)

    def issue_verification(self, owner_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/owners/{owner_id}/issue-verification",
            payload or {}, headers,
        )

    def verify_contact(self, owner_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/owners/{owner_id}/verify-contact", payload, headers,
        )

    def deposit(self, owner_id: str, payload: Dict[str, Any],
                headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/owners/{owner_id}/deposits", payload, headers,
        )

    # =====================================================================
    # Pets
    # =====================================================================
    def create_pet(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/pets", payload, headers)

    def get_pet(self, pet_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PFX}/pets/{pet_id}", headers=headers)

    def update_pet(self, pet_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"{_PFX}/pets/{pet_id}", payload, headers,
        )

    def archive_pet(self, pet_id: str, headers: Dict[str, str]):
        return self._request("DELETE", f"{_PFX}/pets/{pet_id}", headers=headers)

    def list_pet_visits(self, pet_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PFX}/pets/{pet_id}/visits", headers=headers, params=params,
        )

    def get_due_list(self, pet_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PFX}/pets/{pet_id}/vaccines/due-list", headers=headers,
        )

    def record_vaccination(self, pet_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/pets/{pet_id}/vaccinations", payload, headers,
        )

    # =====================================================================
    # Vaccine schedules + recalls
    # =====================================================================
    def create_vaccine_schedule(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/vaccine-schedules", payload, headers)

    def vaccine_batch_recall(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/_events/vaccine-batch-recall", payload, headers,
        )

    # =====================================================================
    # Visits
    # =====================================================================
    def create_visit(self, pet_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/pets/{pet_id}/visits", payload, headers,
        )

    def get_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PFX}/visits/{visit_id}", headers=headers)

    def triage_visit(self, visit_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/visits/{visit_id}/triage", payload or {}, headers,
        )

    def start_consult(self, visit_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/visits/{visit_id}/start-consult",
            payload or {}, headers,
        )

    def re_triage(self, visit_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/visits/{visit_id}/re-triage",
            payload or {}, headers,
        )

    def end_consult(self, visit_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/visits/{visit_id}/end-consult",
            payload or {}, headers,
        )

    def close_visit(self, visit_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/visits/{visit_id}/close",
            payload or {}, headers,
        )

    def cancel_visit(self, visit_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/visits/{visit_id}/cancel",
            payload or {}, headers,
        )

    # =====================================================================
    # Treatment Records
    # =====================================================================
    def create_treatment_record(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/treatment-records", payload, headers)

    def amend_treatment_record(self, tr_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH", f"{_PFX}/treatment-records/{tr_id}", payload, headers,
        )

    def finalize_treatment_record(self, tr_id: str, headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/treatment-records/{tr_id}/finalize",
            payload or {}, headers,
        )

    # =====================================================================
    # Lab Reports
    # =====================================================================
    def create_lab_report(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/lab-reports", payload, headers)

    def collect_sample(self, lr_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/lab-reports/{lr_id}/collect-sample", payload, headers,
        )

    def send_to_lab(self, lr_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/lab-reports/{lr_id}/send-to-lab", payload, headers,
        )

    def external_lab_result(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/_events/external-lab-result", payload, headers,
        )

    def finalize_lab_report(self, lr_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/lab-reports/{lr_id}/finalize",
            payload or {}, headers,
        )

    def lab_report_history(self, lr_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PFX}/lab-reports/{lr_id}/history", headers=headers,
        )

    def cancel_lab_report(self, lr_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/lab-reports/{lr_id}/cancel",
            payload or {}, headers,
        )

    # =====================================================================
    # Drugs
    # =====================================================================
    def create_drug(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/drugs", payload, headers)

    def update_drug(self, drug_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"{_PFX}/drugs/{drug_id}", payload, headers,
        )

    # =====================================================================
    # Prescriptions
    # =====================================================================
    def create_prescription(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/prescriptions", payload, headers)

    def submit_prescription(self, rx_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/prescriptions/{rx_id}/submit",
            payload or {}, headers,
        )

    def approve_prescription(self, rx_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/prescriptions/{rx_id}/approve",
            payload or {}, headers,
        )

    def reject_prescription(self, rx_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/prescriptions/{rx_id}/reject", payload, headers,
        )

    def redraft_prescription(self, rx_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/prescriptions/{rx_id}/redraft",
            payload or {}, headers,
        )

    def dispense_prescription(self, rx_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/prescriptions/{rx_id}/dispense",
            payload or {}, headers,
        )

    def cancel_prescription(self, rx_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/prescriptions/{rx_id}/cancel",
            payload or {}, headers,
        )

    # =====================================================================
    # Cages and Hospitalizations
    # =====================================================================
    def create_cage(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/cages", payload, headers)

    def create_hospitalization(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/hospitalizations", payload, headers)

    def begin_care(self, h_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/hospitalizations/{h_id}/begin-care",
            payload or {}, headers,
        )

    def append_care_log(self, h_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/hospitalizations/{h_id}/care-log", payload, headers,
        )

    def request_discharge(self, h_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/hospitalizations/{h_id}/request-discharge",
            payload or {}, headers,
        )

    def discharge_hospitalization(self, h_id: str, headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/hospitalizations/{h_id}/discharge",
            payload or {}, headers,
        )

    def cancel_hospitalization(self, h_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/hospitalizations/{h_id}/cancel",
            payload or {}, headers,
        )

    # =====================================================================
    # Bills
    # =====================================================================
    def create_bill(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PFX}/bills", payload, headers)

    def recompute_bill(self, bill_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/bills/{bill_id}/recompute",
            payload or {}, headers,
        )

    def issue_bill(self, bill_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/bills/{bill_id}/issue",
            payload or {}, headers,
        )

    def post_payment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/_events/payment", payload, headers,
        )

    def issue_invoice(self, bill_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/bills/{bill_id}/issue-invoice",
            payload or {}, headers,
        )

    def refund_bill(self, bill_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/bills/{bill_id}/refund", payload, headers,
        )

    def confirm_refund(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/_events/refund-confirm", payload, headers,
        )

    def cancel_bill(self, bill_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PFX}/bills/{bill_id}/cancel",
            payload or {}, headers,
        )

    # =====================================================================
    # Audit / IM bridge / clock
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PFX}/audit-logs", headers=headers, params=params,
        )

    def im_emit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/_events/im-emit", payload, headers,
        )

    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PFX}/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
