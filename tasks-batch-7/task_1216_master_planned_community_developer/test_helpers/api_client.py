"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Communities ---
    def create_community(self, payload, headers):
        return self._request("POST", "/mpc/communities", payload, headers)

    def list_communities(self, headers, params=None):
        return self._request("GET", "/mpc/communities", headers=headers, params=params)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/mpc/communities/{community_id}", headers=headers)

    def activate_community(self, community_id, payload, headers):
        return self._request("POST", f"/mpc/communities/{community_id}/activate", payload, headers)

    def record_turnover(self, community_id, headers):
        return self._request("POST", f"/mpc/communities/{community_id}/record-turnover", headers=headers)

    def get_community_summary(self, community_id, headers):
        return self._request("GET", f"/mpc/communities/{community_id}/summary", headers=headers)

    # --- Phases ---
    def create_phase(self, payload, headers):
        return self._request("POST", "/mpc/phases", payload, headers)

    def list_phases(self, headers, params=None):
        return self._request("GET", "/mpc/phases", headers=headers, params=params)

    def get_phase(self, phase_id, headers):
        return self._request("GET", f"/mpc/phases/{phase_id}", headers=headers)

    def open_sales(self, phase_id, headers):
        return self._request("POST", f"/mpc/phases/{phase_id}/open-sales", headers=headers)

    def close_out_phase(self, phase_id, headers):
        return self._request("POST", f"/mpc/phases/{phase_id}/close-out", headers=headers)

    def cancel_phase(self, phase_id, headers):
        return self._request("POST", f"/mpc/phases/{phase_id}/cancel", headers=headers)

    # --- Amenities ---
    def create_amenity(self, payload, headers):
        return self._request("POST", "/mpc/amenities", payload, headers)

    def list_amenities(self, headers, params=None):
        return self._request("GET", "/mpc/amenities", headers=headers, params=params)

    def get_amenity(self, amenity_id, headers):
        return self._request("GET", f"/mpc/amenities/{amenity_id}", headers=headers)

    def start_design(self, amenity_id, headers):
        return self._request("POST", f"/mpc/amenities/{amenity_id}/start-design", headers=headers)

    def start_construction(self, amenity_id, headers):
        return self._request("POST", f"/mpc/amenities/{amenity_id}/start-construction", headers=headers)

    def open_amenity(self, amenity_id, headers):
        return self._request("POST", f"/mpc/amenities/{amenity_id}/open", headers=headers)

    # --- Builders ---
    def create_builder(self, payload, headers):
        return self._request("POST", "/mpc/builders", payload, headers)

    def list_builders(self, headers, params=None):
        return self._request("GET", "/mpc/builders", headers=headers, params=params)

    def get_builder(self, builder_id, headers):
        return self._request("GET", f"/mpc/builders/{builder_id}", headers=headers)

    def reinstate_builder(self, builder_id, headers):
        return self._request("POST", f"/mpc/builders/{builder_id}/reinstate", headers=headers)

    # --- Lot purchase agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/mpc/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/mpc/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/mpc/agreements/{agreement_id}", headers=headers)

    def execute_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mpc/agreements/{agreement_id}/execute", headers=headers)

    def commence_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mpc/agreements/{agreement_id}/commence", headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mpc/agreements/{agreement_id}/terminate", headers=headers)

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/mpc/agreements/{agreement_id}/amendments", payload, headers)

    # --- Takedown tranches ---
    def create_tranche(self, payload, headers):
        return self._request("POST", "/mpc/tranches", payload, headers)

    def list_tranches(self, headers, params=None):
        return self._request("GET", "/mpc/tranches", headers=headers, params=params)

    def get_tranche(self, tranche_id, headers):
        return self._request("GET", f"/mpc/tranches/{tranche_id}", headers=headers)

    def cure_tranche(self, tranche_id, payload, headers):
        return self._request("POST", f"/mpc/tranches/{tranche_id}/cure", payload, headers)

    def waive_tranche(self, tranche_id, payload, headers):
        return self._request("POST", f"/mpc/tranches/{tranche_id}/waive", payload, headers)

    def certify_default(self, tranche_id, headers):
        return self._request("POST", f"/mpc/tranches/{tranche_id}/certify-default", headers=headers)

    # --- Lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/mpc/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/mpc/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/mpc/lots/{lot_id}", headers=headers)

    def offer_lot(self, lot_id, headers):
        return self._request("POST", f"/mpc/lots/{lot_id}/offer", headers=headers)

    def withdraw_lot(self, lot_id, headers):
        return self._request("POST", f"/mpc/lots/{lot_id}/withdraw", headers=headers)

    # --- Closings ---
    def create_closing(self, payload, headers):
        return self._request("POST", "/mpc/closings", payload, headers)

    def list_closings(self, headers, params=None):
        return self._request("GET", "/mpc/closings", headers=headers, params=params)

    def get_closing(self, closing_id, headers):
        return self._request("GET", f"/mpc/closings/{closing_id}", headers=headers)

    def close_closing(self, closing_id, headers):
        return self._request("POST", f"/mpc/closings/{closing_id}/close", headers=headers)

    def cancel_closing(self, closing_id, headers):
        return self._request("POST", f"/mpc/closings/{closing_id}/cancel", headers=headers)

    def rescind_closing(self, closing_id, headers):
        return self._request("POST", f"/mpc/closings/{closing_id}/rescind", headers=headers)

    # --- Budgets / line items ---
    def create_budget(self, payload, headers):
        return self._request("POST", "/mpc/budgets", payload, headers)

    def list_budgets(self, headers, params=None):
        return self._request("GET", "/mpc/budgets", headers=headers, params=params)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/mpc/budgets/{budget_id}", headers=headers)

    def create_line_item(self, payload, headers):
        return self._request("POST", "/mpc/line-items", payload, headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/mpc/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/mpc/line-items/{line_item_id}", headers=headers)

    def propose_budget(self, budget_id, headers):
        return self._request("POST", f"/mpc/budgets/{budget_id}/propose", headers=headers)

    def adopt_budget(self, budget_id, headers):
        return self._request("POST", f"/mpc/budgets/{budget_id}/adopt", headers=headers)

    def ratify_budget(self, budget_id, headers):
        return self._request("POST", f"/mpc/budgets/{budget_id}/ratify", headers=headers)

    def reject_budget(self, budget_id, headers):
        return self._request("POST", f"/mpc/budgets/{budget_id}/reject", headers=headers)

    def revise_budget(self, budget_id, headers):
        return self._request("POST", f"/mpc/budgets/{budget_id}/revise", headers=headers)

    def amend_budget(self, budget_id, payload, headers):
        return self._request("POST", f"/mpc/budgets/{budget_id}/amendments", payload, headers)

    # --- Assessment rates ---
    def create_assessment_rate(self, payload, headers):
        return self._request("POST", "/mpc/assessment-rates", payload, headers)

    def list_assessment_rates(self, headers, params=None):
        return self._request("GET", "/mpc/assessment-rates", headers=headers, params=params)

    def get_assessment_rate(self, rate_id, headers):
        return self._request("GET", f"/mpc/assessment-rates/{rate_id}", headers=headers)

    def approve_cap_override(self, rate_id, headers):
        return self._request("POST", f"/mpc/assessment-rates/{rate_id}/approve-cap-override", headers=headers)

    def ratify_cap_override(self, rate_id, headers):
        return self._request("POST", f"/mpc/assessment-rates/{rate_id}/ratify-cap-override", headers=headers)

    def arm_rate(self, rate_id, headers):
        return self._request("POST", f"/mpc/assessment-rates/{rate_id}/arm", headers=headers)

    # --- Districts / advances / levies / payments ---
    def create_district(self, payload, headers):
        return self._request("POST", "/mpc/districts", payload, headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/mpc/districts", headers=headers, params=params)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/mpc/districts/{district_id}", headers=headers)

    def create_advance(self, payload, headers):
        return self._request("POST", "/mpc/advances", payload, headers)

    def list_advances(self, headers, params=None):
        return self._request("GET", "/mpc/advances", headers=headers, params=params)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/mpc/advances/{advance_id}", headers=headers)

    def create_levy(self, payload, headers):
        return self._request("POST", "/mpc/levies", payload, headers)

    def list_levies(self, headers, params=None):
        return self._request("GET", "/mpc/levies", headers=headers, params=params)

    def get_levy(self, levy_id, headers):
        return self._request("GET", f"/mpc/levies/{levy_id}", headers=headers)

    def collect_levy(self, levy_id, headers):
        return self._request("POST", f"/mpc/levies/{levy_id}/collect", headers=headers)

    def create_payment(self, payload, headers):
        return self._request("POST", "/mpc/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/mpc/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/mpc/payments/{payment_id}", headers=headers)

    def certify_payment(self, payment_id, headers):
        return self._request("POST", f"/mpc/payments/{payment_id}/certify", headers=headers)

    def pay_payment(self, payment_id, headers):
        return self._request("POST", f"/mpc/payments/{payment_id}/pay", headers=headers)

    def reject_payment(self, payment_id, headers):
        return self._request("POST", f"/mpc/payments/{payment_id}/reject", headers=headers)

    # --- Design review applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/mpc/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/mpc/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/mpc/applications/{application_id}", headers=headers)

    def begin_review(self, application_id, headers):
        return self._request("POST", f"/mpc/applications/{application_id}/begin-review", headers=headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/mpc/applications/{application_id}/approve", headers=headers)

    def approve_with_conditions(self, application_id, payload, headers):
        return self._request("POST", f"/mpc/applications/{application_id}/approve-with-conditions", payload, headers)

    def deny_application(self, application_id, payload, headers):
        return self._request("POST", f"/mpc/applications/{application_id}/deny", payload, headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST", f"/mpc/applications/{application_id}/resubmit", headers=headers)

    def verify_conditions(self, application_id, headers):
        return self._request("POST", f"/mpc/applications/{application_id}/verify-conditions", headers=headers)

    def record_construction_start(self, application_id, headers):
        return self._request("POST", f"/mpc/applications/{application_id}/record-construction-start", headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/mpc/applications/{application_id}/withdraw", headers=headers)

    # --- Design violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/mpc/violations", payload, headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/mpc/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/mpc/violations/{violation_id}", headers=headers)

    def send_violation_notice(self, violation_id, headers):
        return self._request("POST", f"/mpc/violations/{violation_id}/send-notice", headers=headers)

    def record_cure(self, violation_id, headers):
        return self._request("POST", f"/mpc/violations/{violation_id}/record-cure", headers=headers)

    def escalate_violation(self, violation_id, headers):
        return self._request("POST", f"/mpc/violations/{violation_id}/escalate", headers=headers)

    def schedule_hearing(self, violation_id, payload, headers):
        return self._request("POST", f"/mpc/violations/{violation_id}/schedule-hearing", payload, headers)

    def levy_fine(self, violation_id, headers):
        return self._request("POST", f"/mpc/violations/{violation_id}/levy-fine", headers=headers)

    def record_violation_payment(self, violation_id, payload, headers):
        return self._request("POST", f"/mpc/violations/{violation_id}/record-payment", payload, headers)

    def appeal_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/mpc/violations/{violation_id}/appeal", payload, headers)

    def resolve_appeal(self, violation_id, payload, headers):
        return self._request("POST", f"/mpc/violations/{violation_id}/resolve-appeal", payload, headers)

    # --- Events / RSVPs ---
    def create_event(self, payload, headers):
        return self._request("POST", "/mpc/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/mpc/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/mpc/events/{event_id}", headers=headers)

    def schedule_event(self, event_id, headers):
        return self._request("POST", f"/mpc/events/{event_id}/schedule", headers=headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/mpc/events/{event_id}/cancel", headers=headers)

    def create_rsvp(self, payload, headers):
        return self._request("POST", "/mpc/rsvps", payload, headers)

    def list_rsvps(self, headers, params=None):
        return self._request("GET", "/mpc/rsvps", headers=headers, params=params)

    def get_rsvp(self, rsvp_id, headers):
        return self._request("GET", f"/mpc/rsvps/{rsvp_id}", headers=headers)

    def cancel_rsvp(self, rsvp_id, headers):
        return self._request("POST", f"/mpc/rsvps/{rsvp_id}/cancel", headers=headers)

    # --- Sales center appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/mpc/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/mpc/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/mpc/appointments/{appointment_id}", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/mpc/appointments/{appointment_id}/cancel", headers=headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/mpc/appointments/{appointment_id}/complete", headers=headers)

    # --- Residents ---
    def create_resident(self, payload, headers):
        return self._request("POST", "/mpc/residents", payload, headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/mpc/residents", headers=headers, params=params)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/mpc/residents/{resident_id}", headers=headers)

    def record_purchase(self, resident_id, payload, headers):
        return self._request("POST", f"/mpc/residents/{resident_id}/record-purchase", payload, headers)

    def archive_resident(self, resident_id, headers):
        return self._request("POST", f"/mpc/residents/{resident_id}/archive", headers=headers)

    # --- Notices ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/mpc/notices", payload, headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/mpc/notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/mpc/notices/{notice_id}", headers=headers)

    def schedule_notice(self, notice_id, headers):
        return self._request("POST", f"/mpc/notices/{notice_id}/schedule", headers=headers)

    def cancel_notice(self, notice_id, headers):
        return self._request("POST", f"/mpc/notices/{notice_id}/cancel", headers=headers)

    def supersede_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/mpc/notices/{notice_id}/supersede", payload, headers)

    # --- Board seats ---
    def list_board_seats(self, headers, params=None):
        return self._request("GET", "/mpc/board-seats", headers=headers, params=params)

    def get_board_seat(self, seat_id, headers):
        return self._request("GET", f"/mpc/board-seats/{seat_id}", headers=headers)

    def call_election(self, seat_id, headers):
        return self._request("POST", f"/mpc/board-seats/{seat_id}/call-election", headers=headers)

    def certify_election(self, seat_id, payload, headers):
        return self._request("POST", f"/mpc/board-seats/{seat_id}/certify-election", payload, headers)


api_client = ApiClient()
