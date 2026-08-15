"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/pest/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/pest/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/pest/properties/{property_id}", headers=headers)

    def get_property_summary(self, property_id, headers):
        return self._request("GET", f"/pest/properties/{property_id}/summary", headers=headers)

    # --- contracts ---
    def create_contract(self, property_id, payload, headers):
        return self._request("POST", f"/pest/properties/{property_id}/contracts", payload, headers)

    def list_contracts(self, property_id, headers, params=None):
        return self._request("GET", f"/pest/properties/{property_id}/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/pest/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/pest/contracts/{contract_id}/activate", {}, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/pest/contracts/{contract_id}/suspend", {}, headers)

    def reactivate_contract(self, contract_id, headers):
        return self._request("POST", f"/pest/contracts/{contract_id}/reactivate", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/pest/contracts/{contract_id}/terminate", {}, headers)

    # --- units ---
    def create_unit(self, property_id, payload, headers):
        return self._request("POST", f"/pest/properties/{property_id}/units", payload, headers)

    def list_units(self, property_id, headers, params=None):
        return self._request("GET", f"/pest/properties/{property_id}/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/pest/units/{unit_id}", headers=headers)

    def get_unit_risk_score(self, unit_id, headers, params=None):
        return self._request("GET", f"/pest/units/{unit_id}/risk-score", headers=headers, params=params)

    def get_adjacent_exposure(self, unit_id, headers):
        return self._request("GET", f"/pest/units/{unit_id}/adjacent-exposure", headers=headers)

    # --- leases & residents ---
    def create_lease(self, unit_id, payload, headers):
        return self._request("POST", f"/pest/units/{unit_id}/leases", payload, headers)

    def list_leases(self, unit_id, headers, params=None):
        return self._request("GET", f"/pest/units/{unit_id}/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/pest/leases/{lease_id}", headers=headers)

    def list_lease_chargebacks(self, lease_id, headers, params=None):
        return self._request("GET", f"/pest/leases/{lease_id}/chargebacks", headers=headers, params=params)

    def create_resident(self, unit_id, payload, headers):
        return self._request("POST", f"/pest/units/{unit_id}/residents", payload, headers)

    def list_residents(self, unit_id, headers, params=None):
        return self._request("GET", f"/pest/units/{unit_id}/residents", headers=headers, params=params)

    def list_lease_residents(self, lease_id, headers, params=None):
        return self._request("GET", f"/pest/leases/{lease_id}/residents", headers=headers, params=params)

    # --- technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/pest/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/pest/technicians/{technician_id}", headers=headers)

    def list_technician_treatments(self, technician_id, headers, params=None):
        return self._request("GET", f"/pest/technicians/{technician_id}/treatments", headers=headers, params=params)

    def list_technician_inspections(self, technician_id, headers, params=None):
        return self._request("GET", f"/pest/technicians/{technician_id}/inspections", headers=headers, params=params)

    # --- inspections ---
    def create_inspection(self, unit_id, payload, headers):
        return self._request("POST", f"/pest/units/{unit_id}/inspections", payload, headers)

    def list_unit_inspections(self, unit_id, headers, params=None):
        return self._request("GET", f"/pest/units/{unit_id}/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/pest/inspections/{inspection_id}", headers=headers)

    def list_case_inspections(self, case_id, headers, params=None):
        return self._request("GET", f"/pest/bed-bug-cases/{case_id}/inspections", headers=headers, params=params)

    def list_inspection_treatments(self, inspection_id, headers, params=None):
        return self._request("GET", f"/pest/inspections/{inspection_id}/treatments", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/pest/inspections/{inspection_id}/complete", payload, headers)

    def no_access_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/pest/inspections/{inspection_id}/no-access", payload or {}, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/pest/inspections/{inspection_id}/cancel", {}, headers)

    # --- treatments ---
    def create_treatment(self, unit_id, payload, headers):
        return self._request("POST", f"/pest/units/{unit_id}/treatments", payload, headers)

    def list_unit_treatments(self, unit_id, headers, params=None):
        return self._request("GET", f"/pest/units/{unit_id}/treatments", headers=headers, params=params)

    def get_treatment(self, treatment_id, headers):
        return self._request("GET", f"/pest/treatments/{treatment_id}", headers=headers)

    def list_case_treatments(self, case_id, headers, params=None):
        return self._request("GET", f"/pest/bed-bug-cases/{case_id}/treatments", headers=headers, params=params)

    def list_treatment_chargebacks(self, treatment_id, headers, params=None):
        return self._request("GET", f"/pest/treatments/{treatment_id}/chargebacks", headers=headers, params=params)

    def notify_prep(self, treatment_id, headers):
        return self._request("POST", f"/pest/treatments/{treatment_id}/notify-prep", {}, headers)

    def acknowledge_prep(self, treatment_id, headers):
        return self._request("POST", f"/pest/treatments/{treatment_id}/acknowledge-prep", {}, headers)

    def verify_prep(self, treatment_id, payload, headers):
        return self._request("POST", f"/pest/treatments/{treatment_id}/verify-prep", payload, headers)

    def reschedule_treatment(self, treatment_id, payload, headers):
        return self._request("POST", f"/pest/treatments/{treatment_id}/reschedule", payload, headers)

    def complete_treatment(self, treatment_id, payload, headers):
        return self._request("POST", f"/pest/treatments/{treatment_id}/complete", payload, headers)

    def cancel_treatment(self, treatment_id, headers, payload=None):
        return self._request("POST", f"/pest/treatments/{treatment_id}/cancel", payload or {}, headers)

    # --- bed bug cases & furniture disposals ---
    def list_unit_bed_bug_cases(self, unit_id, headers, params=None):
        return self._request("GET", f"/pest/units/{unit_id}/bed-bug-cases", headers=headers, params=params)

    def get_bed_bug_case(self, case_id, headers):
        return self._request("GET", f"/pest/bed-bug-cases/{case_id}", headers=headers)

    def list_case_chargebacks(self, case_id, headers, params=None):
        return self._request("GET", f"/pest/bed-bug-cases/{case_id}/chargebacks", headers=headers, params=params)

    def create_furniture_disposal(self, case_id, payload, headers):
        return self._request("POST", f"/pest/bed-bug-cases/{case_id}/furniture-disposals", payload, headers)

    def list_furniture_disposals(self, case_id, headers, params=None):
        return self._request("GET", f"/pest/bed-bug-cases/{case_id}/furniture-disposals", headers=headers, params=params)

    def verify_furniture_disposal(self, disposal_id, payload, headers):
        return self._request("POST", f"/pest/furniture-disposals/{disposal_id}/verify", payload, headers)

    def evaluate_clearance(self, case_id, headers):
        return self._request("POST", f"/pest/bed-bug-cases/{case_id}/evaluate-clearance", {}, headers)

    # --- chargebacks ---
    def create_chargeback(self, lease_id, payload, headers):
        return self._request("POST", f"/pest/leases/{lease_id}/chargebacks", payload, headers)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/pest/chargebacks/{chargeback_id}", headers=headers)

    def dispute_chargeback(self, chargeback_id, payload, headers):
        return self._request("POST", f"/pest/chargebacks/{chargeback_id}/dispute", payload, headers)

    def resolve_dispute(self, chargeback_id, payload, headers):
        return self._request("POST", f"/pest/chargebacks/{chargeback_id}/resolve-dispute", payload, headers)

    def bill_chargeback(self, chargeback_id, headers):
        return self._request("POST", f"/pest/chargebacks/{chargeback_id}/bill", {}, headers)

    def record_payment(self, chargeback_id, payload, headers):
        return self._request("POST", f"/pest/chargebacks/{chargeback_id}/record-payment", payload, headers)

    # --- claim packets ---
    def create_claim_packet(self, property_id, payload, headers):
        return self._request("POST", f"/pest/properties/{property_id}/claim-packets", payload, headers)

    def list_claim_packets(self, property_id, headers, params=None):
        return self._request("GET", f"/pest/properties/{property_id}/claim-packets", headers=headers, params=params)

    def get_claim_packet(self, packet_id, headers):
        return self._request("GET", f"/pest/claim-packets/{packet_id}", headers=headers)

    def finalize_claim_packet(self, packet_id, headers):
        return self._request("POST", f"/pest/claim-packets/{packet_id}/finalize", {}, headers)

    def discard_claim_packet(self, packet_id, headers):
        return self._request("POST", f"/pest/claim-packets/{packet_id}/discard", {}, headers)


api_client = ApiClient()
