"""API client: one method per endpoint declared in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/property-care"


class ApiClient(GenericApiClient):
    """One method per PRD endpoint. All paths are mounted under /property-care."""

    def set_clock(self, payload=None, headers=None):
        return self._request("POST", "/property-care/_clock/set_current_utc", payload if payload is not None else {}, headers=headers)

    def get_clock(self, headers=None, params=None):
        return self._request("GET", "/property-care/_clock", headers=headers, params=params)

    def create_owner(self, payload=None, headers=None):
        return self._request("POST", "/property-care/owners", payload if payload is not None else {}, headers=headers)

    def list_owners(self, headers=None, params=None):
        return self._request("GET", "/property-care/owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers=None, params=None):
        return self._request("GET", f"/property-care/owners/{owner_id}", headers=headers, params=params)

    def update_owner(self, owner_id, payload=None, headers=None):
        return self._request("PATCH", f"/property-care/owners/{owner_id}", payload if payload is not None else {}, headers=headers)

    def create_property(self, payload=None, headers=None):
        return self._request("POST", "/property-care/properties", payload if payload is not None else {}, headers=headers)

    def list_properties(self, headers=None, params=None):
        return self._request("GET", "/property-care/properties", headers=headers, params=params)

    def get_property(self, property_id, headers=None, params=None):
        return self._request("GET", f"/property-care/properties/{property_id}", headers=headers, params=params)

    def update_property(self, property_id, payload=None, headers=None):
        return self._request("PATCH", f"/property-care/properties/{property_id}", payload if payload is not None else {}, headers=headers)

    def create_property_seasonal_transition(self, property_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/properties/{property_id}/seasonal-transitions", payload if payload is not None else {}, headers=headers)

    def create_property_occupancy_transition(self, property_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/properties/{property_id}/occupancy-transitions", payload if payload is not None else {}, headers=headers)

    def get_risk_posture(self, property_id, headers=None, params=None):
        return self._request("GET", f"/property-care/properties/{property_id}/risk-posture", headers=headers, params=params)

    def create_service_plan(self, payload=None, headers=None):
        return self._request("POST", "/property-care/service-plans", payload if payload is not None else {}, headers=headers)

    def list_service_plans(self, headers=None, params=None):
        return self._request("GET", "/property-care/service-plans", headers=headers, params=params)

    def get_service_plan(self, service_plan_id, headers=None, params=None):
        return self._request("GET", f"/property-care/service-plans/{service_plan_id}", headers=headers, params=params)

    def retire_service_plan(self, service_plan_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/service-plans/{service_plan_id}/retire", payload if payload is not None else {}, headers=headers)

    def create_subscription(self, payload=None, headers=None):
        return self._request("POST", "/property-care/subscriptions", payload if payload is not None else {}, headers=headers)

    def list_subscriptions(self, headers=None, params=None):
        return self._request("GET", "/property-care/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers=None, params=None):
        return self._request("GET", f"/property-care/subscriptions/{subscription_id}", headers=headers, params=params)

    def activate_subscription(self, subscription_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/subscriptions/{subscription_id}/activate", payload if payload is not None else {}, headers=headers)

    def pause_subscription(self, subscription_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/subscriptions/{subscription_id}/pause", payload if payload is not None else {}, headers=headers)

    def resume_subscription(self, subscription_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/subscriptions/{subscription_id}/resume", payload if payload is not None else {}, headers=headers)

    def tier_changes_subscription(self, subscription_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/subscriptions/{subscription_id}/tier-changes", payload if payload is not None else {}, headers=headers)

    def cancel_subscription(self, subscription_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/subscriptions/{subscription_id}/cancel", payload if payload is not None else {}, headers=headers)

    def mark_delinquent_subscription(self, subscription_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/subscriptions/{subscription_id}/mark-delinquent", payload if payload is not None else {}, headers=headers)

    def clear_delinquency_subscription(self, subscription_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/subscriptions/{subscription_id}/clear-delinquency", payload if payload is not None else {}, headers=headers)

    def create_subscription_billing_cycle(self, subscription_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/subscriptions/{subscription_id}/billing-cycles", payload if payload is not None else {}, headers=headers)

    def list_billing_cycles(self, headers=None, params=None):
        return self._request("GET", "/property-care/billing-cycles", headers=headers, params=params)

    def get_billing_cycle(self, billing_cycle_id, headers=None, params=None):
        return self._request("GET", f"/property-care/billing-cycles/{billing_cycle_id}", headers=headers, params=params)

    def close_billing_cycle(self, billing_cycle_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/billing-cycles/{billing_cycle_id}/close", payload if payload is not None else {}, headers=headers)

    def create_away_period(self, payload=None, headers=None):
        return self._request("POST", "/property-care/away-periods", payload if payload is not None else {}, headers=headers)

    def list_away_periods(self, headers=None, params=None):
        return self._request("GET", "/property-care/away-periods", headers=headers, params=params)

    def get_away_period(self, away_period_id, headers=None, params=None):
        return self._request("GET", f"/property-care/away-periods/{away_period_id}", headers=headers, params=params)

    def update_away_period_cadence(self, away_period_id, payload=None, headers=None):
        return self._request("PATCH", f"/property-care/away-periods/{away_period_id}/cadence", payload if payload is not None else {}, headers=headers)

    def create_checklist_template(self, payload=None, headers=None):
        return self._request("POST", "/property-care/checklist-templates", payload if payload is not None else {}, headers=headers)

    def list_checklist_templates(self, headers=None, params=None):
        return self._request("GET", "/property-care/checklist-templates", headers=headers, params=params)

    def get_checklist_template(self, checklist_template_id, headers=None, params=None):
        return self._request("GET", f"/property-care/checklist-templates/{checklist_template_id}", headers=headers, params=params)

    def create_visit(self, payload=None, headers=None):
        return self._request("POST", "/property-care/visits", payload if payload is not None else {}, headers=headers)

    def list_visits(self, headers=None, params=None):
        return self._request("GET", "/property-care/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers=None, params=None):
        return self._request("GET", f"/property-care/visits/{visit_id}", headers=headers, params=params)

    def depart_visit(self, visit_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/visits/{visit_id}/depart", payload if payload is not None else {}, headers=headers)

    def arrive_visit(self, visit_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/visits/{visit_id}/arrive", payload if payload is not None else {}, headers=headers)

    def complete_visit(self, visit_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/visits/{visit_id}/complete", payload if payload is not None else {}, headers=headers)

    def defer_visit(self, visit_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/visits/{visit_id}/defer", payload if payload is not None else {}, headers=headers)

    def reschedule_visit(self, visit_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/visits/{visit_id}/reschedule", payload if payload is not None else {}, headers=headers)

    def convert_to_turnover_visit(self, visit_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/visits/{visit_id}/convert-to-turnover", payload if payload is not None else {}, headers=headers)

    def abort_visit(self, visit_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/visits/{visit_id}/abort", payload if payload is not None else {}, headers=headers)

    def create_visit_finding(self, visit_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/visits/{visit_id}/findings", payload if payload is not None else {}, headers=headers)

    def list_findings(self, headers=None, params=None):
        return self._request("GET", "/property-care/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers=None, params=None):
        return self._request("GET", f"/property-care/findings/{finding_id}", headers=headers, params=params)

    def triage_finding(self, finding_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/findings/{finding_id}/triage", payload if payload is not None else {}, headers=headers)

    def monitor_finding(self, finding_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/findings/{finding_id}/monitor", payload if payload is not None else {}, headers=headers)

    def dismiss_finding(self, finding_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/findings/{finding_id}/dismiss", payload if payload is not None else {}, headers=headers)

    def create_vendor(self, payload=None, headers=None):
        return self._request("POST", "/property-care/vendors", payload if payload is not None else {}, headers=headers)

    def list_vendors(self, headers=None, params=None):
        return self._request("GET", "/property-care/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers=None, params=None):
        return self._request("GET", f"/property-care/vendors/{vendor_id}", headers=headers, params=params)

    def update_vendor_credentials(self, vendor_id, payload=None, headers=None):
        return self._request("PATCH", f"/property-care/vendors/{vendor_id}/credentials", payload if payload is not None else {}, headers=headers)

    def suspend_vendor(self, vendor_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/vendors/{vendor_id}/suspend", payload if payload is not None else {}, headers=headers)

    def reinstate_vendor(self, vendor_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/vendors/{vendor_id}/reinstate", payload if payload is not None else {}, headers=headers)

    def refresh_eligibility_vendor(self, vendor_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/vendors/{vendor_id}/refresh-eligibility", payload if payload is not None else {}, headers=headers)

    def create_finding_work_order(self, finding_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/findings/{finding_id}/work-orders", payload if payload is not None else {}, headers=headers)

    def list_work_orders(self, headers=None, params=None):
        return self._request("GET", "/property-care/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers=None, params=None):
        return self._request("GET", f"/property-care/work-orders/{work_order_id}", headers=headers, params=params)

    def submit_work_order(self, work_order_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/work-orders/{work_order_id}/submit", payload if payload is not None else {}, headers=headers)

    def approve_work_order(self, work_order_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/work-orders/{work_order_id}/approve", payload if payload is not None else {}, headers=headers)

    def reject_work_order(self, work_order_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/work-orders/{work_order_id}/reject", payload if payload is not None else {}, headers=headers)

    def dispatch_work_order(self, work_order_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/work-orders/{work_order_id}/dispatch", payload if payload is not None else {}, headers=headers)

    def complete_work_order(self, work_order_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/work-orders/{work_order_id}/complete", payload if payload is not None else {}, headers=headers)

    def invoice_work_order(self, work_order_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/work-orders/{work_order_id}/invoice", payload if payload is not None else {}, headers=headers)

    def list_vendor_assignments(self, headers=None, params=None):
        return self._request("GET", "/property-care/vendor-assignments", headers=headers, params=params)

    def get_vendor_assignment(self, vendor_assignment_id, headers=None, params=None):
        return self._request("GET", f"/property-care/vendor-assignments/{vendor_assignment_id}", headers=headers, params=params)

    def accept_vendor_assignment(self, vendor_assignment_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/vendor-assignments/{vendor_assignment_id}/accept", payload if payload is not None else {}, headers=headers)

    def decline_vendor_assignment(self, vendor_assignment_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/vendor-assignments/{vendor_assignment_id}/decline", payload if payload is not None else {}, headers=headers)

    def start_work_vendor_assignment(self, vendor_assignment_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/vendor-assignments/{vendor_assignment_id}/start-work", payload if payload is not None else {}, headers=headers)

    def finish_work_vendor_assignment(self, vendor_assignment_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/vendor-assignments/{vendor_assignment_id}/finish-work", payload if payload is not None else {}, headers=headers)

    def withdraw_vendor_assignment(self, vendor_assignment_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/vendor-assignments/{vendor_assignment_id}/withdraw", payload if payload is not None else {}, headers=headers)

    def create_property_key_asset(self, property_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/properties/{property_id}/key-assets", payload if payload is not None else {}, headers=headers)

    def list_key_assets(self, headers=None, params=None):
        return self._request("GET", "/property-care/key-assets", headers=headers, params=params)

    def get_key_asset(self, key_asset_id, headers=None, params=None):
        return self._request("GET", f"/property-care/key-assets/{key_asset_id}", headers=headers, params=params)

    def rotate_code_key_asset(self, key_asset_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/key-assets/{key_asset_id}/rotate-code", payload if payload is not None else {}, headers=headers)

    def create_key_asset_key_issuance(self, key_asset_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/key-assets/{key_asset_id}/issuances", payload if payload is not None else {}, headers=headers)

    def list_key_issuances(self, headers=None, params=None):
        return self._request("GET", "/property-care/key-issuances", headers=headers, params=params)

    def get_key_issuance(self, key_issuance_id, headers=None, params=None):
        return self._request("GET", f"/property-care/key-issuances/{key_issuance_id}", headers=headers, params=params)

    def return_key_issuance(self, key_issuance_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/key-issuances/{key_issuance_id}/return", payload if payload is not None else {}, headers=headers)

    def mark_overdue_key_issuance(self, key_issuance_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/key-issuances/{key_issuance_id}/mark-overdue", payload if payload is not None else {}, headers=headers)

    def declare_lost_key_issuance(self, key_issuance_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/key-issuances/{key_issuance_id}/declare-lost", payload if payload is not None else {}, headers=headers)

    def create_key_asset_access_grant(self, key_asset_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/key-assets/{key_asset_id}/access-grants", payload if payload is not None else {}, headers=headers)

    def list_access_grants(self, headers=None, params=None):
        return self._request("GET", "/property-care/access-grants", headers=headers, params=params)

    def get_access_grant(self, access_grant_id, headers=None, params=None):
        return self._request("GET", f"/property-care/access-grants/{access_grant_id}", headers=headers, params=params)

    def activate_access_grant(self, access_grant_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/access-grants/{access_grant_id}/activate", payload if payload is not None else {}, headers=headers)

    def revoke_access_grant(self, access_grant_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/access-grants/{access_grant_id}/revoke", payload if payload is not None else {}, headers=headers)

    def create_property_winterization_record(self, property_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/properties/{property_id}/winterization-records", payload if payload is not None else {}, headers=headers)

    def list_winterization_records(self, headers=None, params=None):
        return self._request("GET", "/property-care/winterization-records", headers=headers, params=params)

    def get_winterization_record(self, winterization_record_id, headers=None, params=None):
        return self._request("GET", f"/property-care/winterization-records/{winterization_record_id}", headers=headers, params=params)

    def steps_winterization_record(self, winterization_record_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/winterization-records/{winterization_record_id}/steps", payload if payload is not None else {}, headers=headers)

    def reopen_winterization_record(self, winterization_record_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/winterization-records/{winterization_record_id}/reopen", payload if payload is not None else {}, headers=headers)

    def create_property_rental_turnover(self, property_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/properties/{property_id}/rental-turnovers", payload if payload is not None else {}, headers=headers)

    def list_rental_turnovers(self, headers=None, params=None):
        return self._request("GET", "/property-care/rental-turnovers", headers=headers, params=params)

    def get_rental_turnover(self, rental_turnover_id, headers=None, params=None):
        return self._request("GET", f"/property-care/rental-turnovers/{rental_turnover_id}", headers=headers, params=params)

    def advance_rental_turnover(self, rental_turnover_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/rental-turnovers/{rental_turnover_id}/advance", payload if payload is not None else {}, headers=headers)

    def fail_inspection_rental_turnover(self, rental_turnover_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/rental-turnovers/{rental_turnover_id}/fail-inspection", payload if payload is not None else {}, headers=headers)

    def create_property_mail_hold(self, property_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/properties/{property_id}/mail-holds", payload if payload is not None else {}, headers=headers)

    def list_mail_holds(self, headers=None, params=None):
        return self._request("GET", "/property-care/mail-holds", headers=headers, params=params)

    def get_mail_hold(self, mail_hold_id, headers=None, params=None):
        return self._request("GET", f"/property-care/mail-holds/{mail_hold_id}", headers=headers, params=params)

    def log_packages_mail_hold(self, mail_hold_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/mail-holds/{mail_hold_id}/log-packages", payload if payload is not None else {}, headers=headers)

    def forward_mail_hold(self, mail_hold_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/mail-holds/{mail_hold_id}/forward", payload if payload is not None else {}, headers=headers)

    def extend_mail_hold(self, mail_hold_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/mail-holds/{mail_hold_id}/extend", payload if payload is not None else {}, headers=headers)

    def release_mail_hold(self, mail_hold_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/mail-holds/{mail_hold_id}/release", payload if payload is not None else {}, headers=headers)

    def create_property_security_incident(self, property_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/properties/{property_id}/security-incidents", payload if payload is not None else {}, headers=headers)

    def list_security_incidents(self, headers=None, params=None):
        return self._request("GET", "/property-care/security-incidents", headers=headers, params=params)

    def get_security_incident(self, security_incident_id, headers=None, params=None):
        return self._request("GET", f"/property-care/security-incidents/{security_incident_id}", headers=headers, params=params)

    def acknowledge_security_incident(self, security_incident_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/security-incidents/{security_incident_id}/acknowledge", payload if payload is not None else {}, headers=headers)

    def investigate_security_incident(self, security_incident_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/security-incidents/{security_incident_id}/investigate", payload if payload is not None else {}, headers=headers)

    def escalate_security_incident(self, security_incident_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/security-incidents/{security_incident_id}/escalate", payload if payload is not None else {}, headers=headers)

    def resolve_security_incident(self, security_incident_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/security-incidents/{security_incident_id}/resolve", payload if payload is not None else {}, headers=headers)

    def reclassify_false_alarm_security_incident(self, security_incident_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/security-incidents/{security_incident_id}/reclassify-false-alarm", payload if payload is not None else {}, headers=headers)

    def create_storm_event(self, payload=None, headers=None):
        return self._request("POST", "/property-care/storm-events", payload if payload is not None else {}, headers=headers)

    def list_storm_events(self, headers=None, params=None):
        return self._request("GET", "/property-care/storm-events", headers=headers, params=params)

    def get_storm_event(self, storm_event_id, headers=None, params=None):
        return self._request("GET", f"/property-care/storm-events/{storm_event_id}", headers=headers, params=params)

    def advisory_storm_event(self, storm_event_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/storm-events/{storm_event_id}/advisory", payload if payload is not None else {}, headers=headers)

    def landfall_storm_event(self, storm_event_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/storm-events/{storm_event_id}/landfall", payload if payload is not None else {}, headers=headers)

    def all_clear_storm_event(self, storm_event_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/storm-events/{storm_event_id}/all-clear", payload if payload is not None else {}, headers=headers)

    def close_storm_event(self, storm_event_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/storm-events/{storm_event_id}/close", payload if payload is not None else {}, headers=headers)

    def create_storm_event_storm_response(self, storm_event_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/storm-events/{storm_event_id}/responses", payload if payload is not None else {}, headers=headers)

    def list_storm_responses(self, headers=None, params=None):
        return self._request("GET", "/property-care/storm-responses", headers=headers, params=params)

    def get_storm_response(self, storm_response_id, headers=None, params=None):
        return self._request("GET", f"/property-care/storm-responses/{storm_response_id}", headers=headers, params=params)

    def schedule_sweep_storm_response(self, storm_response_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/storm-responses/{storm_response_id}/schedule-sweep", payload if payload is not None else {}, headers=headers)

    def create_storm_response_assessment(self, storm_response_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/storm-responses/{storm_response_id}/assessments", payload if payload is not None else {}, headers=headers)

    def close_storm_response(self, storm_response_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/storm-responses/{storm_response_id}/close", payload if payload is not None else {}, headers=headers)

    def create_billing_cycle_invoice(self, billing_cycle_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/billing-cycles/{billing_cycle_id}/invoices", payload if payload is not None else {}, headers=headers)

    def list_invoices(self, headers=None, params=None):
        return self._request("GET", "/property-care/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers=None, params=None):
        return self._request("GET", f"/property-care/invoices/{invoice_id}", headers=headers, params=params)

    def create_invoice_invoice_line(self, invoice_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/invoices/{invoice_id}/lines", payload if payload is not None else {}, headers=headers)

    def list_invoice_lines(self, headers=None, params=None):
        return self._request("GET", "/property-care/invoice-lines", headers=headers, params=params)

    def get_invoice_line(self, invoice_line_id, headers=None, params=None):
        return self._request("GET", f"/property-care/invoice-lines/{invoice_line_id}", headers=headers, params=params)

    def void_invoice_line(self, invoice_line_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/invoice-lines/{invoice_line_id}/void", payload if payload is not None else {}, headers=headers)

    def issue_invoice(self, invoice_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/invoices/{invoice_id}/issue", payload if payload is not None else {}, headers=headers)

    def pay_invoice(self, invoice_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/invoices/{invoice_id}/pay", payload if payload is not None else {}, headers=headers)

    def dispute_invoice(self, invoice_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/invoices/{invoice_id}/dispute", payload if payload is not None else {}, headers=headers)

    def resolve_dispute_invoice(self, invoice_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/invoices/{invoice_id}/resolve-dispute", payload if payload is not None else {}, headers=headers)

    def void_invoice(self, invoice_id, payload=None, headers=None):
        return self._request("POST", f"/property-care/invoices/{invoice_id}/void", payload if payload is not None else {}, headers=headers)


api_client = ApiClient()
