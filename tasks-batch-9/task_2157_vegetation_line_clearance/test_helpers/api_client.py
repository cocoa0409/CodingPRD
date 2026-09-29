"""API client: one method per endpoint defined in the PRD.

Every resource is mounted under the /vm prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/vm"


class ApiClient(GenericApiClient):
    # ---- Prescriptions ---------------------------------------------------
    def create_prescription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prescriptions", payload, headers=headers)

    def activate_prescription(self, prescription_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/prescriptions/{prescription_id}/activate",
            payload if payload is not None else {}, headers=headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"{PREFIX}/prescriptions/{prescription_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prescriptions", headers=headers, params=params)

    # ---- Circuits --------------------------------------------------------
    def create_circuit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/circuits", payload, headers=headers)

    def resolve_circuit_prescription(self, circuit_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/circuits/{circuit_id}/resolve-prescription",
            payload if payload is not None else {}, headers=headers)

    def get_circuit(self, circuit_id, headers):
        return self._request("GET", f"{PREFIX}/circuits/{circuit_id}", headers=headers)

    def list_circuits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/circuits", headers=headers, params=params)

    def get_circuit_reliability(self, circuit_id, headers):
        return self._request("GET", f"{PREFIX}/circuits/{circuit_id}/reliability", headers=headers)

    # ---- Outage records --------------------------------------------------
    def create_outage_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/outage-records", payload, headers=headers)

    def get_outage_record(self, outage_id, headers):
        return self._request("GET", f"{PREFIX}/outage-records/{outage_id}", headers=headers)

    def list_outage_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/outage-records", headers=headers, params=params)

    # ---- Work plans ------------------------------------------------------
    def create_work_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-plans", payload, headers=headers)

    def release_work_plan(self, work_plan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-plans/{work_plan_id}/release",
            payload if payload is not None else {}, headers=headers)

    def cancel_work_plan(self, work_plan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-plans/{work_plan_id}/cancel",
            payload if payload is not None else {}, headers=headers)

    def get_work_plan(self, work_plan_id, headers):
        return self._request("GET", f"{PREFIX}/work-plans/{work_plan_id}", headers=headers)

    def list_work_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-plans", headers=headers, params=params)

    def get_production_summary(self, work_plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/work-plans/{work_plan_id}/production-summary", headers=headers)

    # ---- Work orders -----------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders", payload, headers=headers)

    def map_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/map", payload, headers=headers)

    def release_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/release",
            payload if payload is not None else {}, headers=headers)

    def start_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/start",
            payload if payload is not None else {}, headers=headers)

    def complete_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/complete",
            payload if payload is not None else {}, headers=headers)

    def cancel_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/cancel",
            payload if payload is not None else {}, headers=headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders", headers=headers, params=params)

    def create_billing_line(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/billing-lines", payload, headers=headers)

    # ---- Crews and assignments ------------------------------------------
    def create_crew(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crews", payload, headers=headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"{PREFIX}/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/crews", headers=headers, params=params)

    def create_crew_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crew-assignments", payload, headers=headers)

    def release_crew_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/crew-assignments/{assignment_id}/release",
            payload if payload is not None else {}, headers=headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/crew-assignments", headers=headers, params=params)

    # ---- Production ------------------------------------------------------
    def create_production_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/production-entries", payload, headers=headers)

    def get_production_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/production-entries/{entry_id}", headers=headers)

    def list_production_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/production-entries", headers=headers, params=params)

    # ---- Customer notifications -----------------------------------------
    def create_customer_notification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customer-notifications", payload, headers=headers)

    def notify_customer_notification(self, notification_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/customer-notifications/{notification_id}/notify",
            payload if payload is not None else {}, headers=headers)

    def respond_customer_notification(self, notification_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/customer-notifications/{notification_id}/respond", payload, headers=headers)

    def escalate_customer_notification(self, notification_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/customer-notifications/{notification_id}/escalate",
            payload if payload is not None else {}, headers=headers)

    def finalize_refusal(self, notification_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/customer-notifications/{notification_id}/finalize-refusal",
            payload if payload is not None else {}, headers=headers)

    def get_customer_notification(self, notification_id, headers):
        return self._request(
            "GET", f"{PREFIX}/customer-notifications/{notification_id}", headers=headers)

    def list_customer_notifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/customer-notifications", headers=headers, params=params)

    # ---- Hazard trees ----------------------------------------------------
    def create_hazard_tree(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hazard-trees", payload, headers=headers)

    def assess_hazard_tree(self, tree_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/hazard-trees/{tree_id}/assess",
            payload if payload is not None else {}, headers=headers)

    def decide_hazard_tree(self, tree_id, payload, headers):
        return self._request("POST", f"{PREFIX}/hazard-trees/{tree_id}/decision", payload, headers=headers)

    def remove_hazard_tree(self, tree_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/hazard-trees/{tree_id}/remove",
            payload if payload is not None else {}, headers=headers)

    def get_hazard_tree(self, tree_id, headers):
        return self._request("GET", f"{PREFIX}/hazard-trees/{tree_id}", headers=headers)

    def list_hazard_trees(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hazard-trees", headers=headers, params=params)

    # ---- Herbicide permits -----------------------------------------------
    def create_herbicide_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/herbicide-permits", payload, headers=headers)

    def decide_herbicide_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/herbicide-permits/{permit_id}/decision", payload, headers=headers)

    def activate_herbicide_permit(self, permit_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/herbicide-permits/{permit_id}/activate",
            payload if payload is not None else {}, headers=headers)

    def revoke_herbicide_permit(self, permit_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/herbicide-permits/{permit_id}/revoke",
            payload if payload is not None else {}, headers=headers)

    def get_herbicide_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/herbicide-permits/{permit_id}", headers=headers)

    def list_herbicide_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/herbicide-permits", headers=headers, params=params)

    # ---- Storm response --------------------------------------------------
    def create_storm_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/storm-events", payload, headers=headers)

    def activate_storm_event(self, storm_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/storm-events/{storm_id}/activate",
            payload if payload is not None else {}, headers=headers)

    def create_storm_reassignment(self, storm_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/storm-events/{storm_id}/reassignments", payload, headers=headers)

    def demobilize_storm_event(self, storm_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/storm-events/{storm_id}/demobilize",
            payload if payload is not None else {}, headers=headers)

    def close_storm_event(self, storm_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/storm-events/{storm_id}/close",
            payload if payload is not None else {}, headers=headers)

    def get_storm_event(self, storm_id, headers):
        return self._request("GET", f"{PREFIX}/storm-events/{storm_id}", headers=headers)

    def list_storm_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/storm-events", headers=headers, params=params)

    # ---- Billing ---------------------------------------------------------
    def submit_billing_line(self, line_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/billing-lines/{line_id}/submit",
            payload if payload is not None else {}, headers=headers)

    def review_billing_line(self, line_id, payload, headers):
        return self._request("POST", f"{PREFIX}/billing-lines/{line_id}/review", payload, headers=headers)

    def resubmit_billing_line(self, line_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/billing-lines/{line_id}/resubmit",
            payload if payload is not None else {}, headers=headers)

    def void_billing_line(self, line_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/billing-lines/{line_id}/void",
            payload if payload is not None else {}, headers=headers)

    def pay_billing_line(self, line_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/billing-lines/{line_id}/pay",
            payload if payload is not None else {}, headers=headers)

    def get_billing_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/billing-lines/{line_id}", headers=headers)

    def list_billing_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/billing-lines", headers=headers, params=params)

    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)

    # ---- Raw escape hatch (used by path-resolution tests) ----------------
    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
