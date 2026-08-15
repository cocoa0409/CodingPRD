"""API client: one method per endpoint defined in the PRD (§4 endpoint index).

All resources are peers addressed at the top level under /nuclear-medicine;
resources reference one another through foreign keys in request bodies.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/nuclear-medicine"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- Isotope catalog ---
    def create_isotope_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/isotope-products", payload, headers)

    def list_isotope_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/isotope-products", headers=headers, params=params)

    def get_isotope_product(self, isotope_id, headers):
        return self._request("GET", f"{PREFIX}/isotope-products/{isotope_id}", headers=headers)

    # --- Licenses ---
    def create_license(self, payload, headers):
        return self._request("POST", f"{PREFIX}/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"{PREFIX}/licenses/{license_id}", headers=headers)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"{PREFIX}/licenses/{license_id}/suspend", {}, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"{PREFIX}/licenses/{license_id}/reinstate", {}, headers)

    # --- Authorized users ---
    def create_authorized_user(self, payload, headers):
        return self._request("POST", f"{PREFIX}/authorized-users", payload, headers)

    def list_authorized_users(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/authorized-users", headers=headers, params=params)

    def get_authorized_user(self, user_id, headers):
        return self._request("GET", f"{PREFIX}/authorized-users/{user_id}", headers=headers)

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/patients", headers=headers, params=params)

    # --- Imaging rooms ---
    def create_imaging_room(self, payload, headers):
        return self._request("POST", f"{PREFIX}/imaging-rooms", payload, headers)

    def get_imaging_room(self, room_id, headers):
        return self._request("GET", f"{PREFIX}/imaging-rooms/{room_id}", headers=headers)

    # --- Isotope deliveries ---
    def create_isotope_delivery(self, payload, headers):
        return self._request("POST", f"{PREFIX}/isotope-deliveries", payload, headers)

    def list_isotope_deliveries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/isotope-deliveries", headers=headers, params=params)

    def get_isotope_delivery(self, delivery_id, headers):
        return self._request("GET", f"{PREFIX}/isotope-deliveries/{delivery_id}", headers=headers)

    def receive_isotope_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"{PREFIX}/isotope-deliveries/{delivery_id}/receive", payload, headers)

    def mark_isotope_delivery_failed(self, delivery_id, payload, headers):
        return self._request("POST", f"{PREFIX}/isotope-deliveries/{delivery_id}/mark-failed", payload, headers)

    # --- Dose orders ---
    def create_dose_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dose-orders", payload, headers)

    def list_dose_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dose-orders", headers=headers, params=params)

    def get_dose_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/dose-orders/{order_id}", headers=headers)

    def cancel_dose_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dose-orders/{order_id}/cancel", payload, headers)

    def substitute_dose_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dose-orders/{order_id}/substitute", payload, headers)

    # --- Dose vials ---
    def create_dose_vial(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dose-vials", payload, headers)

    def list_dose_vials(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dose-vials", headers=headers, params=params)

    def get_dose_vial(self, vial_id, headers):
        return self._request("GET", f"{PREFIX}/dose-vials/{vial_id}", headers=headers)

    def calibrate_dose_vial(self, vial_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dose-vials/{vial_id}/calibrate", payload, headers)

    def administer_dose_vial(self, vial_id, headers):
        return self._request("POST", f"{PREFIX}/dose-vials/{vial_id}/administer", {}, headers)

    def dispose_dose_vial(self, vial_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dose-vials/{vial_id}/dispose", payload, headers)

    # --- Administration records (append-only read surface) ---
    def list_dose_administrations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dose-administrations", headers=headers, params=params)

    def get_dose_administration(self, administration_id, headers):
        return self._request("GET", f"{PREFIX}/dose-administrations/{administration_id}", headers=headers)

    # --- Procedure appointments ---
    def create_procedure_appointment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/procedure-appointments", payload, headers)

    def list_procedure_appointments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/procedure-appointments", headers=headers, params=params)

    def get_procedure_appointment(self, appointment_id, headers):
        return self._request("GET", f"{PREFIX}/procedure-appointments/{appointment_id}", headers=headers)

    def cancel_procedure_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/procedure-appointments/{appointment_id}/cancel", payload, headers)

    # --- Waste containers ---
    def create_waste_container(self, payload, headers):
        return self._request("POST", f"{PREFIX}/waste-containers", payload, headers)

    def list_waste_containers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/waste-containers", headers=headers, params=params)

    def get_waste_container(self, container_id, headers):
        return self._request("GET", f"{PREFIX}/waste-containers/{container_id}", headers=headers)

    def seal_waste_container(self, container_id, payload, headers):
        return self._request("POST", f"{PREFIX}/waste-containers/{container_id}/seal", payload, headers)

    def certify_waste_container_clearance(self, container_id, headers):
        return self._request("POST", f"{PREFIX}/waste-containers/{container_id}/certify-clearance", {}, headers)

    # --- Radiation surveys ---
    def create_radiation_survey(self, payload, headers):
        return self._request("POST", f"{PREFIX}/radiation-surveys", payload, headers)

    def list_radiation_surveys(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/radiation-surveys", headers=headers, params=params)

    def get_radiation_survey(self, survey_id, headers):
        return self._request("GET", f"{PREFIX}/radiation-surveys/{survey_id}", headers=headers)

    # --- Spill incidents ---
    def create_spill_incident(self, payload, headers):
        return self._request("POST", f"{PREFIX}/spill-incidents", payload, headers)

    def list_spill_incidents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/spill-incidents", headers=headers, params=params)

    def get_spill_incident(self, spill_id, headers):
        return self._request("GET", f"{PREFIX}/spill-incidents/{spill_id}", headers=headers)

    def advance_spill_incident(self, spill_id, payload, headers):
        return self._request("POST", f"{PREFIX}/spill-incidents/{spill_id}/advance", payload, headers)

    # --- Patient release instructions ---
    def create_patient_release_instruction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patient-release-instructions", payload, headers)

    def list_patient_release_instructions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/patient-release-instructions", headers=headers, params=params
        )

    def get_patient_release_instruction(self, instruction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/patient-release-instructions/{instruction_id}", headers=headers
        )


api_client = ApiClient()
