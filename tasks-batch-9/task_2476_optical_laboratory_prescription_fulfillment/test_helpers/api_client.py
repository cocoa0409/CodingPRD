"""Typed client covering every endpoint the PRD declares.

Every endpoint is rooted at the server origin with no version or product
prefix, so each path below is written exactly as the PRD spells it.
"""

from typing import Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per declared endpoint."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Prescribers
    # ------------------------------------------------------------------

    def create_prescriber(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/prescribers", payload, headers)

    def get_prescriber(self, prescriber_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/prescribers/{prescriber_id}", None, headers)

    def list_prescribers(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/prescribers", params, headers)

    def patch_prescriber_status(
        self, prescriber_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/prescribers/{prescriber_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Insurance plans
    # ------------------------------------------------------------------

    def create_insurance_plan(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/insurance-plans", payload, headers)

    def get_insurance_plan(self, plan_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/insurance-plans/{plan_id}", None, headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------

    def create_patient(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/patients/{patient_id}", None, headers)

    def list_patients(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/patients", params, headers)

    # ------------------------------------------------------------------
    # Lens designs
    # ------------------------------------------------------------------

    def create_lens_design(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/lens-designs", payload, headers)

    def get_lens_design(self, design_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/lens-designs/{design_id}", None, headers)

    # ------------------------------------------------------------------
    # Tolerance standards
    # ------------------------------------------------------------------

    def create_tolerance_standard(
        self, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request("POST", "/tolerance-standards", payload, headers)

    def get_tolerance_standard(
        self, standard_id: str, headers: dict
    ) -> requests.Response:
        return self._request(
            "GET", f"/tolerance-standards/{standard_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Lens blank lots
    # ------------------------------------------------------------------

    def create_lens_blank_lot(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/lens-blank-lots", payload, headers)

    def get_lens_blank_lot(self, lot_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/lens-blank-lots/{lot_id}", None, headers)

    def list_lens_blank_lots(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/lens-blank-lots", params, headers)

    def replenish_lens_blank_lot(
        self, lot_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/lens-blank-lots/{lot_id}/replenish", payload, headers
        )

    # ------------------------------------------------------------------
    # Lab machines
    # ------------------------------------------------------------------

    def create_lab_machine(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/lab-machines", payload, headers)

    def get_lab_machine(self, machine_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/lab-machines/{machine_id}", None, headers)

    def patch_lab_machine_status(
        self, machine_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/lab-machines/{machine_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Finishing bays
    # ------------------------------------------------------------------

    def create_finishing_bay(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/finishing-bays", payload, headers)

    def get_finishing_bay(self, bay_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/finishing-bays/{bay_id}", None, headers)

    def patch_finishing_bay_status(
        self, bay_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/finishing-bays/{bay_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Prescriptions
    # ------------------------------------------------------------------

    def create_prescription(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/prescriptions", payload, headers)

    def get_prescription(self, rx_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/prescriptions/{rx_id}", None, headers)

    def list_prescriptions(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/prescriptions", params, headers)

    def verify_prescription(
        self, rx_id: str, payload: Optional[dict], headers: dict
    ) -> requests.Response:
        return self._request("POST", f"/prescriptions/{rx_id}/verify", payload, headers)

    def attest_prescription(
        self, rx_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/prescriptions/{rx_id}/prescriber-attest", payload, headers
        )

    def reject_prescription(
        self, rx_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request("POST", f"/prescriptions/{rx_id}/reject", payload, headers)

    def resubmit_prescription(
        self, rx_id: str, payload: Optional[dict], headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/prescriptions/{rx_id}/resubmit", payload, headers
        )

    # ------------------------------------------------------------------
    # Rx orders
    # ------------------------------------------------------------------

    def create_rx_order(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/rx-orders", payload, headers)

    def get_rx_order(self, order_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/rx-orders/{order_id}", None, headers)

    def list_rx_orders(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/rx-orders", params, headers)

    def get_charge_summary(self, order_id: str, headers: dict) -> requests.Response:
        return self._request(
            "GET", f"/rx-orders/{order_id}/charge-summary", None, headers
        )

    def apply_benefit(
        self, order_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/rx-orders/{order_id}/benefit-application", payload, headers
        )

    def void_benefit(
        self, order_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/rx-orders/{order_id}/benefit-void", payload, headers
        )

    def settle_patient_portion(
        self, order_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/rx-orders/{order_id}/settle-patient-portion", payload, headers
        )

    def dispense_rx_order(
        self, order_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/rx-orders/{order_id}/dispense", payload, headers
        )

    def cancel_rx_order(
        self, order_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/rx-orders/{order_id}/cancel", payload, headers)

    def list_order_frame_layouts(
        self, order_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/rx-orders/{order_id}/frame-layouts", params, headers
        )

    def list_order_settlement_entries(
        self, order_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/rx-orders/{order_id}/settlement-entries", params, headers
        )

    # ------------------------------------------------------------------
    # Frame layouts
    # ------------------------------------------------------------------

    def create_frame_layout(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/frame-layouts", payload, headers)

    def get_frame_layout(self, layout_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/frame-layouts/{layout_id}", None, headers)

    # ------------------------------------------------------------------
    # Lab jobs
    # ------------------------------------------------------------------

    def create_lab_job(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/lab-jobs", payload, headers)

    def get_lab_job(self, job_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/lab-jobs/{job_id}", None, headers)

    def list_lab_jobs(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/lab-jobs", params, headers)

    def release_lab_job(
        self, job_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/lab-jobs/{job_id}/release", payload, headers)

    # ------------------------------------------------------------------
    # Lab operations
    # ------------------------------------------------------------------

    def create_lab_operation(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/lab-operations", payload, headers)

    def get_lab_operation(self, operation_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/lab-operations/{operation_id}", None, headers)

    def list_lab_operations(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/lab-operations", params, headers)

    def start_lab_operation(
        self, operation_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/lab-operations/{operation_id}/start", payload, headers
        )

    def complete_lab_operation(
        self, operation_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/lab-operations/{operation_id}/complete", payload, headers
        )

    def report_breakage(
        self, operation_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/lab-operations/{operation_id}/report-breakage", payload, headers
        )

    def cancel_lab_operation(
        self, operation_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/lab-operations/{operation_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Quality inspections
    # ------------------------------------------------------------------

    def create_quality_inspection(
        self, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request("POST", "/quality-inspections", payload, headers)

    def get_quality_inspection(
        self, inspection_id: str, headers: dict
    ) -> requests.Response:
        return self._request(
            "GET", f"/quality-inspections/{inspection_id}", None, headers
        )

    def list_quality_inspections(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/quality-inspections", params, headers)

    # ------------------------------------------------------------------
    # Remake cases
    # ------------------------------------------------------------------

    def create_remake_case(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/remake-cases", payload, headers)

    def get_remake_case(self, case_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/remake-cases/{case_id}", None, headers)

    def list_remake_cases(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/remake-cases", params, headers)

    def adjudicate_remake_case(
        self, case_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/remake-cases/{case_id}/adjudicate", payload, headers
        )

    def close_remake_case(
        self, case_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/remake-cases/{case_id}/close", payload, headers
        )


api_client = ApiClient()
