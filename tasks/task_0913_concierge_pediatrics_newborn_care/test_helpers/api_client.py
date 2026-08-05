"""API client: one method per endpoint defined in the PRD (§4).

Everything is mounted under the `/peds` prefix and every collection is a flat
peer — nothing is nested in the URL space.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/peds"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------------------------------
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ---------------- membership plans -------------------------------------
    def create_membership_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/membership-plans", payload, headers)

    def get_membership_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/membership-plans/{plan_id}", headers=headers
        )

    # ---------------- physicians -------------------------------------------
    def create_physician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/physicians", payload, headers)

    def get_physician(self, physician_id, headers):
        return self._request(
            "GET", f"{PREFIX}/physicians/{physician_id}", headers=headers
        )

    def get_physician_panel(self, physician_id, headers):
        return self._request(
            "GET", f"{PREFIX}/physicians/{physician_id}/panel", headers=headers
        )

    # ---------------- families ---------------------------------------------
    def create_family(self, payload, headers):
        return self._request("POST", f"{PREFIX}/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"{PREFIX}/families/{family_id}", headers=headers)

    # ---------------- insurance policies -----------------------------------
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-policies", payload, headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/insurance-policies", headers=headers, params=params
        )

    def get_insurance_policy(self, policy_id, headers):
        return self._request(
            "GET", f"{PREFIX}/insurance-policies/{policy_id}", headers=headers
        )

    def terminate_insurance_policy(self, policy_id, headers):
        return self._request(
            "POST", f"{PREFIX}/insurance-policies/{policy_id}/terminate", {}, headers
        )

    # ---------------- children ---------------------------------------------
    def create_child(self, payload, headers):
        return self._request("POST", f"{PREFIX}/children", payload, headers)

    def list_children(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/children", headers=headers, params=params)

    def get_child(self, child_id, headers):
        return self._request("GET", f"{PREFIX}/children/{child_id}", headers=headers)

    # ---------------- memberships ------------------------------------------
    def create_membership(self, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/memberships", headers=headers, params=params
        )

    def get_membership(self, membership_id, headers):
        return self._request(
            "GET", f"{PREFIX}/memberships/{membership_id}", headers=headers
        )

    def cancel_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/cancel", payload, headers
        )

    def suspend_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/suspend", payload, headers
        )

    def reinstate_membership(self, membership_id, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/reinstate", {}, headers
        )

    # ---------------- panel waitlist entries -------------------------------
    def create_waitlist_entry(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/panel-waitlist-entries", payload, headers
        )

    def list_waitlist_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/panel-waitlist-entries", headers=headers, params=params
        )

    def get_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/panel-waitlist-entries/{waitlist_entry_id}",
            headers=headers,
        )

    def withdraw_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/panel-waitlist-entries/{waitlist_entry_id}/withdraw",
            {},
            headers,
        )

    # ---------------- entitlement grants -----------------------------------
    def list_entitlement_grants(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/entitlement-grants", headers=headers, params=params
        )

    def get_entitlement_grant(self, grant_id, headers):
        return self._request(
            "GET", f"{PREFIX}/entitlement-grants/{grant_id}", headers=headers
        )

    # ---------------- consult bookings -------------------------------------
    def create_consult_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consult-bookings", payload, headers)

    def list_consult_bookings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/consult-bookings", headers=headers, params=params
        )

    def get_consult_booking(self, booking_id, headers):
        return self._request(
            "GET", f"{PREFIX}/consult-bookings/{booking_id}", headers=headers
        )

    def reschedule_consult_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-bookings/{booking_id}/reschedule", payload, headers
        )

    def complete_consult_booking(self, booking_id, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-bookings/{booking_id}/complete", {}, headers
        )

    def cancel_consult_booking(self, booking_id, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-bookings/{booking_id}/cancel", {}, headers
        )

    # ---------------- well visits ------------------------------------------
    def list_well_visits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/well-visits", headers=headers, params=params
        )

    def get_well_visit(self, well_visit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/well-visits/{well_visit_id}", headers=headers
        )

    def schedule_well_visit(self, well_visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/well-visits/{well_visit_id}/schedule", payload, headers
        )

    def complete_well_visit(self, well_visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/well-visits/{well_visit_id}/complete", payload, headers
        )

    # ---------------- immunization doses -----------------------------------
    def create_immunization_dose(self, payload, headers):
        return self._request("POST", f"{PREFIX}/immunization-doses", payload, headers)

    def list_immunization_doses(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/immunization-doses", headers=headers, params=params
        )

    def get_immunization_dose(self, dose_id, headers):
        return self._request(
            "GET", f"{PREFIX}/immunization-doses/{dose_id}", headers=headers
        )

    def invalidate_immunization_dose(self, dose_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/immunization-doses/{dose_id}/invalidate", payload, headers
        )

    # ---------------- encounters -------------------------------------------
    def create_encounter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/encounters", payload, headers)

    def list_encounters(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/encounters", headers=headers, params=params
        )

    def get_encounter(self, encounter_id, headers):
        return self._request(
            "GET", f"{PREFIX}/encounters/{encounter_id}", headers=headers
        )

    def complete_clinical_encounter(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/encounters/{encounter_id}/complete-clinical", payload, headers
        )

    def submit_encounter_billing(self, encounter_id, headers):
        return self._request(
            "POST", f"{PREFIX}/encounters/{encounter_id}/submit-billing", {}, headers
        )

    def cancel_encounter(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/encounters/{encounter_id}/cancel", payload, headers
        )

    # ---------------- service lines ----------------------------------------
    def list_service_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-lines", headers=headers, params=params
        )

    def get_service_line(self, service_line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/service-lines/{service_line_id}", headers=headers
        )

    def adjudicate_service_line(self, service_line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-lines/{service_line_id}/adjudicate", payload, headers
        )

    def settle_service_line(self, service_line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-lines/{service_line_id}/settle", payload, headers
        )

    # ---------------- invoices ---------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/issue", {}, headers
        )

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/pay", payload, headers
        )

    # ---------------- form requests ----------------------------------------
    def create_form_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/form-requests", payload, headers)

    def list_form_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/form-requests", headers=headers, params=params
        )

    def get_form_request(self, form_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/form-requests/{form_request_id}", headers=headers
        )

    def issue_form_request(self, form_request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/form-requests/{form_request_id}/issue", {}, headers
        )

    def recheck_form_request(self, form_request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/form-requests/{form_request_id}/recheck", {}, headers
        )


api_client = ApiClient()
