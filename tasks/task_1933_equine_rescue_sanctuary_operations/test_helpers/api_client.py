"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/rescue-ops/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- horses ----
    def create_horse(self, payload, headers):
        return self._request("POST", "/rescue-ops/horses", payload, headers)

    def list_horses(self, headers, params=None):
        return self._request("GET", "/rescue-ops/horses", headers=headers, params=params)

    def get_horse(self, horse_id, headers):
        return self._request("GET", f"/rescue-ops/horses/{horse_id}", headers=headers)

    def patch_horse(self, horse_id, payload, headers):
        return self._request("PATCH", f"/rescue-ops/horses/{horse_id}", payload, headers)

    def release_quarantine(self, horse_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/horses/{horse_id}/release-quarantine", payload, headers
        )

    def graduate_rehabilitation(self, horse_id, headers):
        return self._request(
            "POST", f"/rescue-ops/horses/{horse_id}/graduate-rehabilitation", {}, headers
        )

    def designate_sanctuary(self, horse_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/horses/{horse_id}/designate-sanctuary", payload, headers
        )

    def requarantine_horse(self, horse_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/horses/{horse_id}/quarantine", payload, headers
        )

    # ---- intake evaluations ----
    def create_intake_evaluation(self, payload, headers):
        return self._request("POST", "/rescue-ops/intake-evaluations", payload, headers)

    def list_intake_evaluations(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/intake-evaluations", headers=headers, params=params
        )

    def get_intake_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/rescue-ops/intake-evaluations/{evaluation_id}", headers=headers
        )

    def complete_intake_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/intake-evaluations/{evaluation_id}/complete",
            payload, headers,
        )

    # ---- quarantine protocols ----
    def list_quarantine_protocols(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/quarantine-protocols", headers=headers, params=params
        )

    def get_quarantine_protocol(self, protocol_id, headers):
        return self._request(
            "GET", f"/rescue-ops/quarantine-protocols/{protocol_id}", headers=headers
        )

    def extend_quarantine_protocol(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/quarantine-protocols/{protocol_id}/extend",
            payload, headers,
        )

    def clear_quarantine_protocol(self, protocol_id, headers):
        return self._request(
            "POST", f"/rescue-ops/quarantine-protocols/{protocol_id}/clear", {}, headers
        )

    # ---- daily health logs ----
    def create_daily_health_log(self, payload, headers):
        return self._request("POST", "/rescue-ops/daily-health-logs", payload, headers)

    def list_daily_health_logs(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/daily-health-logs", headers=headers, params=params
        )

    def get_daily_health_log(self, log_id, headers):
        return self._request(
            "GET", f"/rescue-ops/daily-health-logs/{log_id}", headers=headers
        )

    # ---- rehabilitation plans ----
    def create_rehabilitation_plan(self, payload, headers):
        return self._request("POST", "/rescue-ops/rehabilitation-plans", payload, headers)

    def list_rehabilitation_plans(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/rehabilitation-plans", headers=headers, params=params
        )

    def get_rehabilitation_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/rescue-ops/rehabilitation-plans/{plan_id}", headers=headers
        )

    def activate_rehabilitation_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/rescue-ops/rehabilitation-plans/{plan_id}/activate", {}, headers
        )

    def complete_rehabilitation_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/rescue-ops/rehabilitation-plans/{plan_id}/complete", {}, headers
        )

    # ---- practitioners ----
    def create_practitioner(self, payload, headers):
        return self._request("POST", "/rescue-ops/practitioners", payload, headers)

    def list_practitioners(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/practitioners", headers=headers, params=params
        )

    def get_practitioner(self, practitioner_id, headers):
        return self._request(
            "GET", f"/rescue-ops/practitioners/{practitioner_id}", headers=headers
        )

    def patch_practitioner(self, practitioner_id, payload, headers):
        return self._request(
            "PATCH", f"/rescue-ops/practitioners/{practitioner_id}", payload, headers
        )

    # ---- care service appointments ----
    def create_care_service_appointment(self, payload, headers):
        return self._request(
            "POST", "/rescue-ops/care-service-appointments", payload, headers
        )

    def list_care_service_appointments(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/care-service-appointments", headers=headers, params=params
        )

    def get_care_service_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/rescue-ops/care-service-appointments/{appointment_id}",
            headers=headers,
        )

    def confirm_care_service_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/rescue-ops/care-service-appointments/{appointment_id}/confirm",
            {}, headers,
        )

    def complete_care_service_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/care-service-appointments/{appointment_id}/complete",
            payload, headers,
        )

    def cancel_care_service_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/care-service-appointments/{appointment_id}/cancel",
            payload, headers,
        )

    # ---- stalls & assignments ----
    def create_stall(self, payload, headers):
        return self._request("POST", "/rescue-ops/stalls", payload, headers)

    def list_stalls(self, headers, params=None):
        return self._request("GET", "/rescue-ops/stalls", headers=headers, params=params)

    def get_stall(self, stall_id, headers):
        return self._request("GET", f"/rescue-ops/stalls/{stall_id}", headers=headers)

    def create_stall_assignment(self, payload, headers):
        return self._request("POST", "/rescue-ops/stall-assignments", payload, headers)

    def list_stall_assignments(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/stall-assignments", headers=headers, params=params
        )

    def get_stall_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/rescue-ops/stall-assignments/{assignment_id}", headers=headers
        )

    def end_stall_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/stall-assignments/{assignment_id}/end", payload, headers
        )

    # ---- adopters ----
    def create_adopter(self, payload, headers):
        return self._request("POST", "/rescue-ops/adopters", payload, headers)

    def list_adopters(self, headers, params=None):
        return self._request("GET", "/rescue-ops/adopters", headers=headers, params=params)

    def get_adopter(self, adopter_id, headers):
        return self._request("GET", f"/rescue-ops/adopters/{adopter_id}", headers=headers)

    def block_adopter(self, adopter_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/adopters/{adopter_id}/block", payload, headers
        )

    def unblock_adopter(self, adopter_id, headers):
        return self._request(
            "POST", f"/rescue-ops/adopters/{adopter_id}/unblock", {}, headers
        )

    # ---- adoption applications ----
    def create_adoption_application(self, payload, headers):
        return self._request("POST", "/rescue-ops/adoption-applications", payload, headers)

    def list_adoption_applications(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/adoption-applications", headers=headers, params=params
        )

    def get_adoption_application(self, application_id, headers):
        return self._request(
            "GET", f"/rescue-ops/adoption-applications/{application_id}", headers=headers
        )

    def start_application_review(self, application_id, headers):
        return self._request(
            "POST", f"/rescue-ops/adoption-applications/{application_id}/start-review",
            {}, headers,
        )

    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"/rescue-ops/adoption-applications/{application_id}/approve",
            {}, headers,
        )

    def reject_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/adoption-applications/{application_id}/reject",
            payload, headers,
        )

    def withdraw_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/adoption-applications/{application_id}/withdraw",
            payload, headers,
        )

    def pay_application_fee(self, application_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/adoption-applications/{application_id}/pay-fee",
            payload, headers,
        )

    def finalize_application(self, application_id, headers):
        return self._request(
            "POST", f"/rescue-ops/adoption-applications/{application_id}/finalize",
            {}, headers,
        )

    # ---- home checks ----
    def create_home_check(self, payload, headers):
        return self._request("POST", "/rescue-ops/home-checks", payload, headers)

    def list_home_checks(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/home-checks", headers=headers, params=params
        )

    def get_home_check(self, home_check_id, headers):
        return self._request(
            "GET", f"/rescue-ops/home-checks/{home_check_id}", headers=headers
        )

    def complete_home_check(self, home_check_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/home-checks/{home_check_id}/complete", payload, headers
        )

    # ---- follow-up visits ----
    def list_follow_up_visits(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/follow-up-visits", headers=headers, params=params
        )

    def get_follow_up_visit(self, visit_id, headers):
        return self._request(
            "GET", f"/rescue-ops/follow-up-visits/{visit_id}", headers=headers
        )

    def complete_follow_up_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/follow-up-visits/{visit_id}/complete", payload, headers
        )

    # ---- sponsors & sponsorships ----
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/rescue-ops/sponsors", payload, headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/rescue-ops/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/rescue-ops/sponsors/{sponsor_id}", headers=headers)

    def create_sponsorship(self, payload, headers):
        return self._request("POST", "/rescue-ops/sponsorships", payload, headers)

    def list_sponsorships(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/sponsorships", headers=headers, params=params
        )

    def get_sponsorship(self, sponsorship_id, headers):
        return self._request(
            "GET", f"/rescue-ops/sponsorships/{sponsorship_id}", headers=headers
        )

    def activate_sponsorship(self, sponsorship_id, headers):
        return self._request(
            "POST", f"/rescue-ops/sponsorships/{sponsorship_id}/activate", {}, headers
        )

    def lapse_sponsorship(self, sponsorship_id, headers):
        return self._request(
            "POST", f"/rescue-ops/sponsorships/{sponsorship_id}/lapse", {}, headers
        )

    def reinstate_sponsorship(self, sponsorship_id, headers):
        return self._request(
            "POST", f"/rescue-ops/sponsorships/{sponsorship_id}/reinstate", {}, headers
        )

    def cancel_sponsorship(self, sponsorship_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/sponsorships/{sponsorship_id}/cancel", payload, headers
        )

    # ---- sanctuary care plans ----
    def create_sanctuary_care_plan(self, payload, headers):
        return self._request("POST", "/rescue-ops/sanctuary-care-plans", payload, headers)

    def list_sanctuary_care_plans(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/sanctuary-care-plans", headers=headers, params=params
        )

    def get_sanctuary_care_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/rescue-ops/sanctuary-care-plans/{plan_id}", headers=headers
        )

    def approve_sanctuary_care_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/rescue-ops/sanctuary-care-plans/{plan_id}/approve", {}, headers
        )

    def close_sanctuary_care_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/sanctuary-care-plans/{plan_id}/close", payload, headers
        )

    # ---- feed: purchase orders, lots, summary, close-day ----
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/rescue-ops/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/purchase-orders", headers=headers, params=params
        )

    def get_purchase_order(self, order_id, headers):
        return self._request(
            "GET", f"/rescue-ops/purchase-orders/{order_id}", headers=headers
        )

    def mark_purchase_order_ordered(self, order_id, headers):
        return self._request(
            "POST", f"/rescue-ops/purchase-orders/{order_id}/mark-ordered", {}, headers
        )

    def receive_purchase_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/purchase-orders/{order_id}/receive", payload, headers
        )

    def list_feed_lots(self, headers, params=None):
        return self._request("GET", "/rescue-ops/feed-lots", headers=headers, params=params)

    def get_feed_lot(self, lot_id, headers):
        return self._request("GET", f"/rescue-ops/feed-lots/{lot_id}", headers=headers)

    def get_feed_inventory_summary(self, headers):
        return self._request("GET", "/rescue-ops/feed-inventory/summary", headers=headers)

    def close_feed_day(self, payload, headers):
        return self._request(
            "POST", "/rescue-ops/feed-inventory/close-day", payload, headers
        )

    def list_feed_day_closes(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/feed-day-closes", headers=headers, params=params
        )

    # ---- volunteers & shifts ----
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/rescue-ops/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/volunteers", headers=headers, params=params
        )

    def get_volunteer(self, volunteer_id, headers):
        return self._request(
            "GET", f"/rescue-ops/volunteers/{volunteer_id}", headers=headers
        )

    def create_barn_shift(self, payload, headers):
        return self._request("POST", "/rescue-ops/barn-shifts", payload, headers)

    def list_barn_shifts(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/barn-shifts", headers=headers, params=params
        )

    def get_barn_shift(self, shift_id, headers):
        return self._request("GET", f"/rescue-ops/barn-shifts/{shift_id}", headers=headers)

    def claim_barn_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/rescue-ops/barn-shifts/{shift_id}/claim", {}, headers
        )

    def release_barn_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/rescue-ops/barn-shifts/{shift_id}/release", {}, headers
        )

    def complete_barn_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/rescue-ops/barn-shifts/{shift_id}/complete", {}, headers
        )

    def mark_barn_shift_no_show(self, shift_id, headers):
        return self._request(
            "POST", f"/rescue-ops/barn-shifts/{shift_id}/mark-no-show", {}, headers
        )

    # ---- euthanasia cases ----
    def create_euthanasia_case(self, payload, headers):
        return self._request("POST", "/rescue-ops/euthanasia-cases", payload, headers)

    def list_euthanasia_cases(self, headers, params=None):
        return self._request(
            "GET", "/rescue-ops/euthanasia-cases", headers=headers, params=params
        )

    def get_euthanasia_case(self, case_id, headers):
        return self._request(
            "GET", f"/rescue-ops/euthanasia-cases/{case_id}", headers=headers
        )

    def certify_euthanasia_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/euthanasia-cases/{case_id}/certify", payload, headers
        )

    def authorize_euthanasia_case(self, case_id, headers):
        return self._request(
            "POST", f"/rescue-ops/euthanasia-cases/{case_id}/authorize", {}, headers
        )

    def execute_euthanasia_case(self, case_id, headers):
        return self._request(
            "POST", f"/rescue-ops/euthanasia-cases/{case_id}/execute", {}, headers
        )

    def overturn_euthanasia_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/euthanasia-cases/{case_id}/overturn", payload, headers
        )


api_client = ApiClient()
