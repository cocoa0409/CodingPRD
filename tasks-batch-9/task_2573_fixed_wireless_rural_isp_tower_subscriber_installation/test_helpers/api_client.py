"""API client: one method per endpoint defined in PRD 4."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- towers ----------------
    def create_tower(self, payload, headers):
        return self._request("POST", "/towers", payload, headers)

    def get_tower(self, tower_id, headers):
        return self._request("GET", f"/towers/{tower_id}", headers=headers)

    def change_tower_status(self, tower_id, payload, headers):
        return self._request(
            "POST", f"/towers/{tower_id}/status-changes", payload, headers
        )

    def get_lease_schedule(self, tower_id, headers):
        return self._request("GET", f"/towers/{tower_id}/lease-schedule", headers=headers)

    def list_tower_backhaul_circuits(self, tower_id, headers, params=None):
        return self._request(
            "GET", f"/towers/{tower_id}/backhaul-circuits", headers=headers, params=params
        )

    def list_tower_outage_events(self, tower_id, headers, params=None):
        return self._request(
            "GET", f"/towers/{tower_id}/outage-events", headers=headers, params=params
        )

    # ---------------- backhaul circuits ----------------
    def create_backhaul_circuit(self, payload, headers):
        return self._request("POST", "/backhaul-circuits", payload, headers)

    def get_backhaul_circuit(self, circuit_id, headers):
        return self._request("GET", f"/backhaul-circuits/{circuit_id}", headers=headers)

    def change_circuit_state(self, circuit_id, payload, headers):
        return self._request(
            "POST", f"/backhaul-circuits/{circuit_id}/state-changes", payload, headers
        )

    # ---------------- spectrum licences ----------------
    def create_spectrum_license(self, payload, headers):
        return self._request("POST", "/spectrum-licenses", payload, headers)

    def get_spectrum_license(self, license_id, headers):
        return self._request("GET", f"/spectrum-licenses/{license_id}", headers=headers)

    # ---------------- sectors ----------------
    def create_sector(self, payload, headers):
        return self._request("POST", "/sectors", payload, headers)

    def get_sector(self, sector_id, headers):
        return self._request("GET", f"/sectors/{sector_id}", headers=headers)

    def list_sectors(self, headers, params=None):
        return self._request("GET", "/sectors", headers=headers, params=params)

    def activate_sector(self, sector_id, headers, payload=None):
        return self._request(
            "POST", f"/sectors/{sector_id}/activation", payload or {}, headers
        )

    def change_capacity_policy(self, sector_id, payload, headers):
        return self._request(
            "POST", f"/sectors/{sector_id}/capacity-policy", payload, headers
        )

    def list_sector_coordinations(self, sector_id, headers, params=None):
        return self._request(
            "GET",
            f"/sectors/{sector_id}/interference-coordinations",
            headers=headers,
            params=params,
        )

    # ---------------- interference coordination ----------------
    def create_coordination(self, payload, headers):
        return self._request("POST", "/interference-coordinations", payload, headers)

    def get_coordination(self, coordination_id, headers):
        return self._request(
            "GET", f"/interference-coordinations/{coordination_id}", headers=headers
        )

    def list_coordinations(self, headers, params=None):
        return self._request(
            "GET", "/interference-coordinations", headers=headers, params=params
        )

    def respond_to_coordination(self, coordination_id, payload, headers):
        return self._request(
            "POST",
            f"/interference-coordinations/{coordination_id}/responses",
            payload,
            headers,
        )

    def revise_coordination(self, coordination_id, payload, headers):
        return self._request(
            "POST",
            f"/interference-coordinations/{coordination_id}/revisions",
            payload,
            headers,
        )

    # ---------------- service plans ----------------
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    # ---------------- serviceability requests ----------------
    def create_serviceability_request(self, payload, headers):
        return self._request("POST", "/serviceability-requests", payload, headers)

    def get_serviceability_request(self, request_id, headers):
        return self._request(
            "GET", f"/serviceability-requests/{request_id}", headers=headers
        )

    def list_serviceability_requests(self, headers, params=None):
        return self._request(
            "GET", "/serviceability-requests", headers=headers, params=params
        )

    # ---------------- capacity holds ----------------
    def create_capacity_hold(self, payload, headers):
        return self._request("POST", "/capacity-holds", payload, headers)

    def get_capacity_hold(self, hold_id, headers):
        return self._request("GET", f"/capacity-holds/{hold_id}", headers=headers)

    def list_capacity_holds(self, headers, params=None):
        return self._request("GET", "/capacity-holds", headers=headers, params=params)

    def release_capacity_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/capacity-holds/{hold_id}/release", payload or {}, headers
        )

    # ---------------- subscribers ----------------
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", "/subscribers", headers=headers, params=params)

    def change_subscriber_plan(self, subscriber_id, payload, headers):
        return self._request(
            "POST", f"/subscribers/{subscriber_id}/plan-changes", payload, headers
        )

    def change_subscriber_status(self, subscriber_id, payload, headers):
        return self._request(
            "POST", f"/subscribers/{subscriber_id}/status-changes", payload, headers
        )

    def create_usage_record(self, subscriber_id, payload, headers):
        return self._request(
            "POST", f"/subscribers/{subscriber_id}/usage-records", payload, headers
        )

    def list_usage_records(self, subscriber_id, headers, params=None):
        return self._request(
            "GET",
            f"/subscribers/{subscriber_id}/usage-records",
            headers=headers,
            params=params,
        )

    def close_cycle(self, subscriber_id, headers, payload=None):
        return self._request(
            "POST", f"/subscribers/{subscriber_id}/cycle-close", payload or {}, headers
        )

    def list_subscriber_work_orders(self, subscriber_id, headers, params=None):
        return self._request(
            "GET",
            f"/subscribers/{subscriber_id}/install-work-orders",
            headers=headers,
            params=params,
        )

    def list_subscriber_equipment(self, subscriber_id, headers, params=None):
        return self._request(
            "GET",
            f"/subscribers/{subscriber_id}/equipment-assignments",
            headers=headers,
            params=params,
        )

    # ---------------- install work orders ----------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/install-work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"/install-work-orders/{work_order_id}", headers=headers
        )

    def survey_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/install-work-orders/{work_order_id}/survey", payload, headers
        )

    def decide_exception(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"/install-work-orders/{work_order_id}/exception-decision",
            payload,
            headers,
        )

    def reschedule_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/install-work-orders/{work_order_id}/reschedule", payload, headers
        )

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/install-work-orders/{work_order_id}/completion", payload, headers
        )

    # ---------------- equipment assignments ----------------
    def get_equipment_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/equipment-assignments/{assignment_id}", headers=headers
        )

    def return_equipment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/equipment-assignments/{assignment_id}/return", payload, headers
        )

    def settle_unreturned_equipment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/equipment-assignments/{assignment_id}/unreturned-settlement",
            payload or {},
            headers,
        )

    # ---------------- outage events ----------------
    def create_outage_event(self, payload, headers):
        return self._request("POST", "/outage-events", payload, headers)

    def get_outage_event(self, outage_id, headers):
        return self._request("GET", f"/outage-events/{outage_id}", headers=headers)

    def close_outage_event(self, outage_id, payload, headers):
        return self._request(
            "POST", f"/outage-events/{outage_id}/closure", payload, headers
        )

    # ---------------- outage credits ----------------
    def create_outage_credit(self, payload, headers):
        return self._request("POST", "/outage-credits", payload, headers)

    def get_outage_credit(self, credit_id, headers):
        return self._request("GET", f"/outage-credits/{credit_id}", headers=headers)

    def list_outage_credits(self, headers, params=None):
        return self._request("GET", "/outage-credits", headers=headers, params=params)

    def apply_outage_credit(self, credit_id, payload, headers):
        return self._request(
            "POST", f"/outage-credits/{credit_id}/application", payload or {}, headers
        )

    def reverse_outage_credit(self, credit_id, payload, headers):
        return self._request(
            "POST", f"/outage-credits/{credit_id}/reversal", payload, headers
        )


api_client = ApiClient()
