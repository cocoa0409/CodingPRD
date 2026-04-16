"""API client: one method per endpoint from scaffold Table 5."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ── Shelter ──────────────────────────────────────────────
    def create_shelter(self, payload, headers):
        return self._request("POST", "/shelters", payload, headers)

    def list_shelters(self, headers, params=None):
        return self._request("GET", "/shelters", headers=headers, params=params)

    def get_shelter(self, shelter_id, headers):
        return self._request("GET", f"/shelters/{shelter_id}", headers=headers)

    def suspend_shelter(self, shelter_id, headers):
        return self._request("POST", f"/shelters/{shelter_id}/suspend", headers=headers)

    def reopen_shelter(self, shelter_id, headers):
        return self._request("POST", f"/shelters/{shelter_id}/reopen", headers=headers)

    # ── Animal ───────────────────────────────────────────────
    def create_animal(self, payload, headers):
        return self._request("POST", "/animals", payload, headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/animals", headers=headers, params=params)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/animals/{animal_id}", headers=headers)

    def update_animal(self, animal_id, payload, headers):
        return self._request("PATCH", f"/animals/{animal_id}", payload, headers)

    def make_animal_available(self, animal_id, headers):
        return self._request("POST", f"/animals/{animal_id}/make-available", headers=headers)

    # ── VaccinationRecord ────────────────────────────────────
    def create_vaccination_record(self, payload, headers):
        return self._request("POST", "/vaccination-records", payload, headers)

    def list_vaccination_records(self, headers, params=None):
        return self._request("GET", "/vaccination-records", headers=headers, params=params)

    def get_vaccination_record(self, record_id, headers):
        return self._request("GET", f"/vaccination-records/{record_id}", headers=headers)

    # ── Adopter ──────────────────────────────────────────────
    def create_adopter(self, payload, headers):
        return self._request("POST", "/adopters", payload, headers)

    def list_adopters(self, headers, params=None):
        return self._request("GET", "/adopters", headers=headers, params=params)

    def get_adopter(self, adopter_id, headers):
        return self._request("GET", f"/adopters/{adopter_id}", headers=headers)

    def update_adopter(self, adopter_id, payload, headers):
        return self._request("PATCH", f"/adopters/{adopter_id}", payload, headers)

    def blacklist_adopter(self, adopter_id, headers):
        return self._request("POST", f"/adopters/{adopter_id}/blacklist", headers=headers)

    # ── AdoptionApplication ──────────────────────────────────
    def create_adoption_application(self, payload, headers):
        return self._request("POST", "/adoption-applications", payload, headers)

    def list_adoption_applications(self, headers, params=None):
        return self._request("GET", "/adoption-applications", headers=headers, params=params)

    def get_adoption_application(self, application_id, headers):
        return self._request("GET", f"/adoption-applications/{application_id}", headers=headers)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/adoption-applications/{application_id}/start-review", headers=headers)

    def require_home_visit(self, application_id, headers):
        return self._request("POST", f"/adoption-applications/{application_id}/require-home-visit", headers=headers)

    def complete_review(self, application_id, headers):
        return self._request("POST", f"/adoption-applications/{application_id}/complete-review", headers=headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/adoption-applications/{application_id}/approve", headers=headers)

    def reject_application(self, application_id, payload, headers):
        return self._request("POST", f"/adoption-applications/{application_id}/reject", payload, headers)

    def complete_application(self, application_id, headers):
        return self._request("POST", f"/adoption-applications/{application_id}/complete", headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/adoption-applications/{application_id}/withdraw", headers=headers)

    # ── HomeVisit ────────────────────────────────────────────
    def create_home_visit(self, payload, headers):
        return self._request("POST", "/home-visits", payload, headers)

    def list_home_visits(self, headers, params=None):
        return self._request("GET", "/home-visits", headers=headers, params=params)

    def get_home_visit(self, home_visit_id, headers):
        return self._request("GET", f"/home-visits/{home_visit_id}", headers=headers)

    def complete_home_visit(self, home_visit_id, payload, headers):
        return self._request("POST", f"/home-visits/{home_visit_id}/complete", payload, headers)

    def cancel_home_visit(self, home_visit_id, headers):
        return self._request("POST", f"/home-visits/{home_visit_id}/cancel", headers=headers)

    # ── BoardingReservation ──────────────────────────────────
    def create_boarding_reservation(self, payload, headers):
        return self._request("POST", "/boarding-reservations", payload, headers)

    def list_boarding_reservations(self, headers, params=None):
        return self._request("GET", "/boarding-reservations", headers=headers, params=params)

    def get_boarding_reservation(self, reservation_id, headers):
        return self._request("GET", f"/boarding-reservations/{reservation_id}", headers=headers)

    def confirm_boarding_reservation(self, reservation_id, headers):
        return self._request("POST", f"/boarding-reservations/{reservation_id}/confirm", headers=headers)

    def check_in_boarding(self, reservation_id, headers):
        return self._request("POST", f"/boarding-reservations/{reservation_id}/check-in", headers=headers)

    def check_out_boarding(self, reservation_id, headers):
        return self._request("POST", f"/boarding-reservations/{reservation_id}/check-out", headers=headers)

    def cancel_boarding_reservation(self, reservation_id, headers):
        return self._request("POST", f"/boarding-reservations/{reservation_id}/cancel", headers=headers)

    # ── FeeInvoice ───────────────────────────────────────────
    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/fee-invoices", headers=headers, params=params)

    def get_fee_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fee-invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/pay", payload, headers)

    def refund_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/refund", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/void", headers=headers)

    # ── ComplianceHold ───────────────────────────────────────
    def create_compliance_hold(self, payload, headers):
        return self._request("POST", "/compliance-holds", payload, headers)

    def list_compliance_holds(self, headers, params=None):
        return self._request("GET", "/compliance-holds", headers=headers, params=params)

    def get_compliance_hold(self, hold_id, headers):
        return self._request("GET", f"/compliance-holds/{hold_id}", headers=headers)

    def resolve_compliance_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/compliance-holds/{hold_id}/resolve", payload, headers)

    # ── FeeSchedule ──────────────────────────────────────────
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)


api_client = ApiClient()
