"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- TreatmentPlant ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/treatment-plants", payload, headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/treatment-plants", headers=headers, params=params)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}", headers=headers)

    def suspend_plant(self, plant_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/suspend", headers=headers)

    def reinstate_plant(self, plant_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/reinstate", headers=headers)

    def revoke_plant(self, plant_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/revoke", headers=headers)

    def settle_liability(self, plant_id, headers):
        return self._request("POST", f"/treatment-plants/{plantId}/settle-liability".format(plantId=plant_id), headers=headers)

    # --- TreatmentCylinder ---
    def create_cylinder(self, plant_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders", payload, headers)

    def get_cylinder(self, plant_id, cylinder_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}", headers=headers)

    def list_cylinders(self, plant_id, headers, params=None):
        return self._request("GET", f"/treatment-plants/{plant_id}/cylinders", headers=headers, params=params)

    def mark_cleaned(self, plant_id, cylinder_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/mark-cleaned", headers=headers)

    def decommission_cylinder(self, plant_id, cylinder_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/decommission", headers=headers)

    # --- PreservativeConcentrate ---
    def create_preservative(self, plant_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/preservatives", payload, headers)

    def get_preservative(self, plant_id, preservative_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/preservatives/{preservative_id}", headers=headers)

    def assay_preservative(self, plant_id, preservative_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/preservatives/{preservative_id}/assay", payload, headers)

    def replenish_preservative(self, plant_id, preservative_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/preservatives/{preservative_id}/replenish", payload, headers)

    def quarantine_preservative(self, plant_id, preservative_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/preservatives/{preservative_id}/quarantine", payload, headers)

    def release_quarantine(self, plant_id, preservative_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/preservatives/{preservative_id}/release-quarantine", headers=headers)

    # --- CustomerAccount ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def record_payment(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/record-payment", payload, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/close", headers=headers)

    # --- Charge ---
    def load_charge(self, plant_id, cylinder_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/charges", payload, headers)

    def list_charges(self, plant_id, headers, params=None):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges", headers=headers, params=params)

    def get_charge(self, plant_id, charge_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}", headers=headers)

    def order_retreat(self, plant_id, charge_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/charges/{charge_id}/order-retreat", payload, headers)

    def reject_charge(self, plant_id, charge_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/charges/{charge_id}/reject", headers=headers)

    def scrap_charge(self, plant_id, charge_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/charges/{charge_id}/scrap", headers=headers)

    def tag_charge(self, plant_id, charge_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/charges/{charge_id}/tag", headers=headers)

    # --- ChargePiece ---
    def list_pieces(self, plant_id, charge_id, headers, params=None):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}/pieces", headers=headers, params=params)

    def get_piece(self, plant_id, charge_id, piece_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}/pieces/{piece_id}", headers=headers)

    def incise_piece(self, plant_id, charge_id, piece_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/charges/{charge_id}/pieces/{piece_id}/incise", headers=headers)

    # --- TreatmentCycle ---
    def create_cycle(self, plant_id, cylinder_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/cycles", payload, headers)

    def get_cycle(self, plant_id, cylinder_id, cycle_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, plant_id, cylinder_id, headers, params=None):
        return self._request("GET", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/cycles", headers=headers, params=params)

    def start_cycle(self, plant_id, cylinder_id, cycle_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/cycles/{cycle_id}/start", headers=headers)

    def begin_drain(self, plant_id, cylinder_id, cycle_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/cycles/{cycle_id}/begin-drain", headers=headers)

    def complete_cycle(self, plant_id, cylinder_id, cycle_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/cycles/{cycle_id}/complete", payload, headers)

    def abort_cycle(self, plant_id, cylinder_id, cycle_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/cycles/{cycle_id}/abort", payload, headers)

    # --- RetentionAssay ---
    def record_assay(self, plant_id, charge_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/charges/{charge_id}/retention-assays", payload, headers)

    def list_assays(self, plant_id, charge_id, headers, params=None):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}/retention-assays", headers=headers, params=params)

    def get_assay(self, plant_id, charge_id, assay_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}/retention-assays/{assay_id}", headers=headers)

    # --- QualityInspection ---
    def create_inspection(self, plant_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/inspections", payload, headers)

    def get_inspection(self, plant_id, inspection_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/inspections/{inspection_id}", headers=headers)

    def begin_inspection(self, plant_id, inspection_id, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/inspections/{inspection_id}/begin", headers=headers)

    def issue_findings(self, plant_id, inspection_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/inspections/{inspection_id}/issue-findings", payload, headers)

    def close_inspection(self, plant_id, inspection_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/inspections/{inspection_id}/close", payload, headers)

    # --- DripPadLog ---
    def create_drip_log(self, plant_id, charge_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/charges/{charge_id}/drip-pad-logs", payload, headers)

    def list_drip_logs(self, plant_id, charge_id, headers, params=None):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}/drip-pad-logs", headers=headers, params=params)

    def get_drip_log(self, plant_id, charge_id, log_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}/drip-pad-logs/{log_id}", headers=headers)

    # --- WarrantyRegistration ---
    def register_warranty(self, plant_id, charge_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/charges/{charge_id}/warranty-registrations", payload, headers)

    def list_warranties(self, plant_id, charge_id, headers, params=None):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}/warranty-registrations", headers=headers, params=params)

    def get_warranty(self, plant_id, charge_id, warranty_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/charges/{charge_id}/warranty-registrations/{warranty_id}", headers=headers)

    # --- CylinderScheduleSlot ---
    def create_slot(self, plant_id, cylinder_id, payload, headers):
        return self._request("POST", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/slots", payload, headers)

    def list_slots(self, plant_id, cylinder_id, headers, params=None):
        return self._request("GET", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/slots", headers=headers, params=params)

    def get_slot(self, plant_id, cylinder_id, slot_id, headers):
        return self._request("GET", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/slots/{slot_id}", headers=headers)

    def delete_slot(self, plant_id, cylinder_id, slot_id, headers):
        return self._request("DELETE", f"/treatment-plants/{plant_id}/cylinders/{cylinder_id}/slots/{slot_id}", headers=headers)

    # --- Test-driving hooks (PRD §2.10) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def force_charge_state(self, charge_id, payload, headers):
        return self._request("POST", f"/_charges/{charge_id}/force-state", payload, headers)


api_client = ApiClient()
