"""API client: one method per endpoint the PRD defines.

Conventions:
  * every method takes the caller's ``headers`` dict last (see ``test_users``);
  * action endpoints that take no request body are called without a payload;
  * list endpoints take ``params`` for the documented query filters plus
    ``limit`` / ``offset``.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # ModelSpec
    # ------------------------------------------------------------------
    def create_model_spec(self, payload, headers):
        return self._request("POST", "/model-specs", payload, headers)

    def get_model_spec(self, model_spec_id, headers):
        return self._request("GET", f"/model-specs/{model_spec_id}", headers=headers)

    # ------------------------------------------------------------------
    # ApprovedPart
    # ------------------------------------------------------------------
    def create_approved_part(self, payload, headers):
        return self._request("POST", "/approved-parts", payload, headers)

    def get_approved_part(self, approved_part_id, headers):
        return self._request("GET", f"/approved-parts/{approved_part_id}", headers=headers)

    def list_approved_parts(self, headers, params=None):
        return self._request("GET", "/approved-parts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # TestBench
    # ------------------------------------------------------------------
    def create_test_bench(self, payload, headers):
        return self._request("POST", "/test-benches", payload, headers)

    def get_test_bench(self, test_bench_id, headers):
        return self._request("GET", f"/test-benches/{test_bench_id}", headers=headers)

    def calibrate_test_bench(self, test_bench_id, payload, headers):
        return self._request(
            "POST", f"/test-benches/{test_bench_id}/calibrate", payload, headers
        )

    # ------------------------------------------------------------------
    # LoanerUnit
    # ------------------------------------------------------------------
    def create_loaner_unit(self, payload, headers):
        return self._request("POST", "/loaner-units", payload, headers)

    def get_loaner_unit(self, loaner_unit_id, headers):
        return self._request("GET", f"/loaner-units/{loaner_unit_id}", headers=headers)

    def list_loaner_units(self, headers, params=None):
        return self._request("GET", "/loaner-units", headers=headers, params=params)

    # ------------------------------------------------------------------
    # CustomerAccount
    # ------------------------------------------------------------------
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/customer-accounts", payload, headers)

    def get_customer_account(self, customer_account_id, headers):
        return self._request(
            "GET", f"/customer-accounts/{customer_account_id}", headers=headers
        )

    def acknowledge_liability(self, customer_account_id, payload, headers):
        return self._request(
            "POST",
            f"/customer-accounts/{customer_account_id}/liability-acknowledgment",
            payload,
            headers,
        )

    def set_billing_hold(self, customer_account_id, payload, headers):
        return self._request(
            "POST", f"/customer-accounts/{customer_account_id}/billing-hold", payload, headers
        )

    # ------------------------------------------------------------------
    # IntakeShipment
    # ------------------------------------------------------------------
    def create_intake_shipment(self, payload, headers):
        return self._request("POST", "/intake-shipments", payload, headers)

    def get_intake_shipment(self, intake_shipment_id, headers):
        return self._request(
            "GET", f"/intake-shipments/{intake_shipment_id}", headers=headers
        )

    def list_intake_shipments(self, headers, params=None):
        return self._request("GET", "/intake-shipments", headers=headers, params=params)

    def count_intake_shipment(self, intake_shipment_id, payload, headers):
        return self._request(
            "POST", f"/intake-shipments/{intake_shipment_id}/count", payload, headers
        )

    def accept_intake_shipment(self, intake_shipment_id, payload, headers):
        return self._request(
            "POST", f"/intake-shipments/{intake_shipment_id}/accept", payload, headers
        )

    def settle_intake_shipment(self, intake_shipment_id, headers):
        return self._request(
            "POST", f"/intake-shipments/{intake_shipment_id}/settle", {}, headers
        )

    # ------------------------------------------------------------------
    # EquipmentUnit
    # ------------------------------------------------------------------
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/equipment-units", payload, headers)

    def get_equipment_unit(self, equipment_unit_id, headers):
        return self._request(
            "GET", f"/equipment-units/{equipment_unit_id}", headers=headers
        )

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/equipment-units", headers=headers, params=params)

    def identify_equipment_unit(self, equipment_unit_id, payload, headers):
        return self._request(
            "POST", f"/equipment-units/{equipment_unit_id}/identify", payload, headers
        )

    def disassemble_equipment_unit(self, equipment_unit_id, headers):
        return self._request(
            "POST", f"/equipment-units/{equipment_unit_id}/disassemble", {}, headers
        )

    def create_component_inspection(self, equipment_unit_id, payload, headers):
        return self._request(
            "POST", f"/equipment-units/{equipment_unit_id}/inspections", payload, headers
        )

    def list_component_inspections(self, equipment_unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/equipment-units/{equipment_unit_id}/inspections",
            headers=headers,
            params=params,
        )

    def condemn_equipment_unit(self, equipment_unit_id, payload, headers):
        return self._request(
            "POST", f"/equipment-units/{equipment_unit_id}/condemn", payload, headers
        )

    def stage_return_equipment_unit(self, equipment_unit_id, headers):
        return self._request(
            "POST", f"/equipment-units/{equipment_unit_id}/stage-return", {}, headers
        )

    def release_equipment_unit(self, equipment_unit_id, payload, headers):
        return self._request(
            "POST", f"/equipment-units/{equipment_unit_id}/release", payload, headers
        )

    def purge_equipment_unit_records(self, equipment_unit_id, headers):
        return self._request(
            "POST", f"/equipment-units/{equipment_unit_id}/purge-records", {}, headers
        )

    def list_unit_certification_labels(self, equipment_unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/equipment-units/{equipment_unit_id}/certification-labels",
            headers=headers,
            params=params,
        )

    def list_unit_destruction_records(self, equipment_unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/equipment-units/{equipment_unit_id}/destruction-records",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # ShellTest
    # ------------------------------------------------------------------
    def create_shell_test(self, payload, headers):
        return self._request("POST", "/shell-tests", payload, headers)

    def get_shell_test(self, shell_test_id, headers):
        return self._request("GET", f"/shell-tests/{shell_test_id}", headers=headers)

    def list_shell_tests(self, headers, params=None):
        return self._request("GET", "/shell-tests", headers=headers, params=params)

    def record_impacts(self, shell_test_id, payload, headers):
        return self._request(
            "POST", f"/shell-tests/{shell_test_id}/record-impacts", payload, headers
        )

    def determine_shell_test(self, shell_test_id, payload, headers):
        return self._request(
            "POST", f"/shell-tests/{shell_test_id}/determine", payload, headers
        )

    # ------------------------------------------------------------------
    # RepairOrder
    # ------------------------------------------------------------------
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/repair-orders/{repair_order_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def add_repair_order_part_line(self, repair_order_id, payload, headers):
        return self._request(
            "POST", f"/repair-orders/{repair_order_id}/part-lines", payload, headers
        )

    def submit_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/submit", {}, headers)

    def install_repair_order(self, repair_order_id, payload, headers):
        """``payload`` may be ``{}``; ``warranty_claim_ref`` is optional."""
        return self._request(
            "POST", f"/repair-orders/{repair_order_id}/install", payload, headers
        )

    def verify_repair_order(self, repair_order_id, payload, headers):
        return self._request(
            "POST", f"/repair-orders/{repair_order_id}/verify", payload, headers
        )

    def cancel_repair_order(self, repair_order_id, payload, headers):
        return self._request(
            "POST", f"/repair-orders/{repair_order_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # CertificationLabel
    # ------------------------------------------------------------------
    def create_certification_label(self, payload, headers):
        return self._request("POST", "/certification-labels", payload, headers)

    def get_certification_label(self, certification_label_id, headers):
        return self._request(
            "GET", f"/certification-labels/{certification_label_id}", headers=headers
        )

    def void_certification_label(self, certification_label_id, payload, headers):
        return self._request(
            "POST",
            f"/certification-labels/{certification_label_id}/void",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # DestructionRecord
    # ------------------------------------------------------------------
    def get_destruction_record(self, destruction_record_id, headers):
        return self._request(
            "GET", f"/destruction-records/{destruction_record_id}", headers=headers
        )

    def witness_destruction_record(self, destruction_record_id, payload, headers):
        return self._request(
            "POST",
            f"/destruction-records/{destruction_record_id}/witness",
            payload,
            headers,
        )

    def verify_destruction_record(self, destruction_record_id, payload, headers):
        return self._request(
            "POST",
            f"/destruction-records/{destruction_record_id}/verify",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # LoanerAssignment
    # ------------------------------------------------------------------
    def create_loaner_assignment(self, payload, headers):
        return self._request("POST", "/loaner-assignments", payload, headers)

    def get_loaner_assignment(self, loaner_assignment_id, headers):
        return self._request(
            "GET", f"/loaner-assignments/{loaner_assignment_id}", headers=headers
        )

    def list_loaner_assignments(self, headers, params=None):
        return self._request("GET", "/loaner-assignments", headers=headers, params=params)

    def return_loaner_assignment(self, loaner_assignment_id, payload, headers):
        """``payload`` may be ``{}``; ``return_condition_note`` is optional."""
        return self._request(
            "POST",
            f"/loaner-assignments/{loaner_assignment_id}/return",
            payload,
            headers,
        )


api_client = ApiClient()
