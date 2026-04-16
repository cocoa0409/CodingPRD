"""API client: one method per endpoint from scaffold Table 5."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Pet Adoption and Boarding Platform API client with one method per endpoint."""

    # ── Shelters ───────────────────────────────────────────────────────
    def create_shelter(self, payload, headers):
        return self._request("POST", "/petcare/shelters", payload, headers)

    def list_shelters(self, headers, params=None):
        return self._request("GET", "/petcare/shelters", headers=headers, params=params)

    def get_shelter(self, shelter_id, headers):
        return self._request("GET", f"/petcare/shelters/{shelter_id}", headers=headers)

    def suspend_shelter(self, shelter_id, headers):
        return self._request("POST", f"/petcare/shelters/{shelter_id}/suspend", headers=headers)

    def reopen_shelter(self, shelter_id, headers):
        return self._request("POST", f"/petcare/shelters/{shelter_id}/reopen", headers=headers)

    # ── Animals ────────────────────────────────────────────────────────
    def create_animal(self, payload, headers):
        return self._request("POST", "/petcare/animals", payload, headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/petcare/animals", headers=headers, params=params)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/petcare/animals/{animal_id}", headers=headers)

    def update_animal(self, animal_id, payload, headers):
        return self._request("PATCH", f"/petcare/animals/{animal_id}", payload, headers)

    def make_animal_available(self, animal_id, headers):
        return self._request("POST", f"/petcare/animals/{animal_id}/make-available", headers=headers)

    # ── VaccinationRecords ─────────────────────────────────────────────
    def create_vaccination_record(self, payload, headers):
        return self._request("POST", "/petcare/vaccination-records", payload, headers)

    def list_vaccination_records(self, headers, params=None):
        return self._request("GET", "/petcare/vaccination-records", headers=headers, params=params)

    def get_vaccination_record(self, vaccination_record_id, headers):
        return self._request("GET", f"/petcare/vaccination-records/{vaccination_record_id}", headers=headers)

    # ── Adopters ───────────────────────────────────────────────────────
    def create_adopter(self, payload, headers):
        return self._request("POST", "/petcare/adopters", payload, headers)

    def list_adopters(self, headers, params=None):
        return self._request("GET", "/petcare/adopters", headers=headers, params=params)

    def get_adopter(self, adopter_id, headers):
        return self._request("GET", f"/petcare/adopters/{adopter_id}", headers=headers)

    def update_adopter(self, adopter_id, payload, headers):
        return self._request("PATCH", f"/petcare/adopters/{adopter_id}", payload, headers)

    def blacklist_adopter(self, adopter_id, payload, headers):
        return self._request("POST", f"/petcare/adopters/{adopter_id}/blacklist", payload, headers)

    # ── AdoptionApplications ───────────────────────────────────────────
    def create_adoption_application(self, payload, headers):
        return self._request("POST", "/petcare/adoption-applications", payload, headers)

    def list_adoption_applications(self, headers, params=None):
        return self._request("GET", "/petcare/adoption-applications", headers=headers, params=params)

    def get_adoption_application(self, application_id, headers):
        return self._request("GET", f"/petcare/adoption-applications/{application_id}", headers=headers)

    def start_review_application(self, application_id, headers):
        return self._request("POST", f"/petcare/adoption-applications/{application_id}/start-review", headers=headers)

    def require_home_visit(self, application_id, headers):
        return self._request("POST", f"/petcare/adoption-applications/{application_id}/require-home-visit", headers=headers)

    def complete_review(self, application_id, headers):
        return self._request("POST", f"/petcare/adoption-applications/{application_id}/complete-review", headers=headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/petcare/adoption-applications/{application_id}/approve", headers=headers)

    def reject_application(self, application_id, payload, headers):
        return self._request("POST", f"/petcare/adoption-applications/{application_id}/reject", payload, headers)

    def complete_application(self, application_id, headers):
        return self._request("POST", f"/petcare/adoption-applications/{application_id}/complete", headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/petcare/adoption-applications/{application_id}/withdraw", headers=headers)

    # ── HomeVisits ─────────────────────────────────────────────────────
    def create_home_visit(self, payload, headers):
        return self._request("POST", "/petcare/home-visits", payload, headers)

    def list_home_visits(self, headers, params=None):
        return self._request("GET", "/petcare/home-visits", headers=headers, params=params)

    def get_home_visit(self, home_visit_id, headers):
        return self._request("GET", f"/petcare/home-visits/{home_visit_id}", headers=headers)

    def complete_home_visit(self, home_visit_id, payload, headers):
        return self._request("POST", f"/petcare/home-visits/{home_visit_id}/complete", payload, headers)

    def cancel_home_visit(self, home_visit_id, headers):
        return self._request("POST", f"/petcare/home-visits/{home_visit_id}/cancel", headers=headers)

    def expire_due_home_visits(self, headers):
        return self._request("POST", "/petcare/home-visits/expire-due", headers=headers)

    # ── BoardingReservations ───────────────────────────────────────────
    def create_boarding_reservation(self, payload, headers):
        return self._request("POST", "/petcare/boarding-reservations", payload, headers)

    def list_boarding_reservations(self, headers, params=None):
        return self._request("GET", "/petcare/boarding-reservations", headers=headers, params=params)

    def get_boarding_reservation(self, reservation_id, headers):
        return self._request("GET", f"/petcare/boarding-reservations/{reservation_id}", headers=headers)

    def confirm_boarding_reservation(self, reservation_id, headers):
        return self._request("POST", f"/petcare/boarding-reservations/{reservation_id}/confirm", headers=headers)

    def check_in_boarding_reservation(self, reservation_id, headers):
        return self._request("POST", f"/petcare/boarding-reservations/{reservation_id}/check-in", headers=headers)

    def check_out_boarding_reservation(self, reservation_id, headers):
        return self._request("POST", f"/petcare/boarding-reservations/{reservation_id}/check-out", headers=headers)

    def cancel_boarding_reservation(self, reservation_id, headers):
        return self._request("POST", f"/petcare/boarding-reservations/{reservation_id}/cancel", headers=headers)

    # ── BoardingMatches ────────────────────────────────────────────────
    def get_boarding_match(self, boarding_match_id, headers):
        return self._request("GET", f"/petcare/boarding-matches/{boarding_match_id}", headers=headers)

    # ── FeeInvoices ────────────────────────────────────────────────────
    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/petcare/fee-invoices", headers=headers, params=params)

    def get_fee_invoice(self, invoice_id, headers):
        return self._request("GET", f"/petcare/fee-invoices/{invoice_id}", headers=headers)

    def pay_fee_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/petcare/fee-invoices/{invoice_id}/pay", payload, headers)

    def refund_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/petcare/fee-invoices/{invoice_id}/refund", headers=headers)

    def void_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/petcare/fee-invoices/{invoice_id}/void", headers=headers)

    # ── ComplianceHolds ────────────────────────────────────────────────
    def create_compliance_hold(self, payload, headers):
        return self._request("POST", "/petcare/compliance-holds", payload, headers)

    def list_compliance_holds(self, headers, params=None):
        return self._request("GET", "/petcare/compliance-holds", headers=headers, params=params)

    def get_compliance_hold(self, hold_id, headers):
        return self._request("GET", f"/petcare/compliance-holds/{hold_id}", headers=headers)

    def resolve_compliance_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/petcare/compliance-holds/{hold_id}/resolve", payload, headers)

    # ── FeeSchedules ───────────────────────────────────────────────────
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/petcare/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/petcare/fee-schedules", headers=headers, params=params)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/petcare/fee-schedules/{fee_schedule_id}", headers=headers)

    # ── SettlementBatches ──────────────────────────────────────────────
    def create_settlement_batch(self, payload, headers):
        return self._request("POST", "/petcare/settlement-batches", payload, headers)

    def list_settlement_batches(self, headers, params=None):
        return self._request("GET", "/petcare/settlement-batches", headers=headers, params=params)

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"/petcare/settlement-batches/{batch_id}", headers=headers)

    def approve_settlement_batch(self, batch_id, headers):
        return self._request("POST", f"/petcare/settlement-batches/{batch_id}/approve", headers=headers)

    def mark_paid_settlement_batch(self, batch_id, headers):
        return self._request("POST", f"/petcare/settlement-batches/{batch_id}/mark-paid", headers=headers)


api_client = ApiClient()
