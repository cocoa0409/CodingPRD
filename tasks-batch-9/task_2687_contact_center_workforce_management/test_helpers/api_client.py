"""Typed HTTP client: one method per endpoint of the service.

Every method returns the raw ``requests.Response`` so that tests can assert
status codes as well as bodies.  Paths are absolute and unprefixed, matching the
service's own surface.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Json


class ApiClient(GenericApiClient):
    """One method per documented endpoint of the workforce-management API."""

    # ── Logical clock ─────────────────────────────────

    def set_clock(self, payload: Json, headers: Headers):
        """POST /_clock/set_current_utc"""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Planning cycles ───────────────────────────────

    def create_planning_cycle(self, payload: Json, headers: Headers):
        """POST /planning-cycles"""
        return self._request("POST", "/planning-cycles", payload, headers)

    def get_planning_cycle(self, planning_cycle_id, headers: Headers):
        """GET /planning-cycles/{planning_cycle_id}"""
        return self._request(
            "GET", f"/planning-cycles/{planning_cycle_id}", None, headers
        )

    def list_planning_cycles(self, headers: Headers, params=None):
        """GET /planning-cycles"""
        return self._request("GET", "/planning-cycles", params, headers)

    def set_cycle_posture(self, planning_cycle_id, payload: Json, headers: Headers):
        """POST /planning-cycles/{planning_cycle_id}/posture"""
        return self._request(
            "POST", f"/planning-cycles/{planning_cycle_id}/posture", payload, headers
        )

    def reforecast(self, planning_cycle_id, payload: Json, headers: Headers):
        """POST /planning-cycles/{planning_cycle_id}/reforecast"""
        return self._request(
            "POST", f"/planning-cycles/{planning_cycle_id}/reforecast", payload, headers
        )

    def get_coverage_summary(self, planning_cycle_id, headers: Headers, params=None):
        """GET /planning-cycles/{planning_cycle_id}/coverage-summary"""
        return self._request(
            "GET",
            f"/planning-cycles/{planning_cycle_id}/coverage-summary",
            params,
            headers,
        )

    # ── Labour agreements ─────────────────────────────

    def create_labor_agreement(self, payload: Json, headers: Headers):
        """POST /labor-agreements"""
        return self._request("POST", "/labor-agreements", payload, headers)

    def get_labor_agreement(self, labor_agreement_id, headers: Headers):
        """GET /labor-agreements/{labor_agreement_id}"""
        return self._request(
            "GET", f"/labor-agreements/{labor_agreement_id}", None, headers
        )

    def list_labor_agreements(self, headers: Headers, params=None):
        """GET /labor-agreements"""
        return self._request("GET", "/labor-agreements", params, headers)

    # ── Forecast groups ───────────────────────────────

    def create_forecast_group(self, payload: Json, headers: Headers):
        """POST /forecast-groups"""
        return self._request("POST", "/forecast-groups", payload, headers)

    def get_forecast_group(self, forecast_group_id, headers: Headers):
        """GET /forecast-groups/{forecast_group_id}"""
        return self._request(
            "GET", f"/forecast-groups/{forecast_group_id}", None, headers
        )

    def list_forecast_groups(self, headers: Headers, params=None):
        """GET /forecast-groups"""
        return self._request("GET", "/forecast-groups", params, headers)

    def generate_interval_plans(self, forecast_group_id, payload: Json, headers: Headers):
        """POST /forecast-groups/{forecast_group_id}/interval-plans"""
        return self._request(
            "POST",
            f"/forecast-groups/{forecast_group_id}/interval-plans",
            payload,
            headers,
        )

    # ── Marketing events ──────────────────────────────

    def create_marketing_event(self, payload: Json, headers: Headers):
        """POST /marketing-events"""
        return self._request("POST", "/marketing-events", payload, headers)

    def get_marketing_event(self, marketing_event_id, headers: Headers):
        """GET /marketing-events/{marketing_event_id}"""
        return self._request(
            "GET", f"/marketing-events/{marketing_event_id}", None, headers
        )

    def list_marketing_events(self, headers: Headers, params=None):
        """GET /marketing-events"""
        return self._request("GET", "/marketing-events", params, headers)

    def set_marketing_event_status(
        self, marketing_event_id, payload: Json, headers: Headers
    ):
        """POST /marketing-events/{marketing_event_id}/status"""
        return self._request(
            "POST", f"/marketing-events/{marketing_event_id}/status", payload, headers
        )

    # ── Interval plans ────────────────────────────────

    def get_interval_plan(self, interval_plan_id, headers: Headers):
        """GET /interval-plans/{interval_plan_id}"""
        return self._request("GET", f"/interval-plans/{interval_plan_id}", None, headers)

    def list_interval_plans(self, headers: Headers, params=None):
        """GET /interval-plans"""
        return self._request("GET", "/interval-plans", params, headers)

    def post_actuals(self, interval_plan_id, payload: Json, headers: Headers):
        """POST /interval-plans/{interval_plan_id}/actuals"""
        return self._request(
            "POST", f"/interval-plans/{interval_plan_id}/actuals", payload, headers
        )

    # ── Agents ────────────────────────────────────────

    def create_agent(self, payload: Json, headers: Headers):
        """POST /agents"""
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id, headers: Headers):
        """GET /agents/{agent_id}"""
        return self._request("GET", f"/agents/{agent_id}", None, headers)

    def list_agents(self, headers: Headers, params=None):
        """GET /agents"""
        return self._request("GET", "/agents", params, headers)

    def update_agent(self, agent_id, payload: Json, headers: Headers):
        """PATCH /agents/{agent_id}"""
        return self._request("PATCH", f"/agents/{agent_id}", payload, headers)

    # ── Shift templates ───────────────────────────────

    def create_shift_template(self, payload: Json, headers: Headers):
        """POST /shift-templates"""
        return self._request("POST", "/shift-templates", payload, headers)

    def get_shift_template(self, shift_template_id, headers: Headers):
        """GET /shift-templates/{shift_template_id}"""
        return self._request(
            "GET", f"/shift-templates/{shift_template_id}", None, headers
        )

    def list_shift_templates(self, headers: Headers, params=None):
        """GET /shift-templates"""
        return self._request("GET", "/shift-templates", params, headers)

    # ── Bid rounds ────────────────────────────────────

    def create_bid_round(self, payload: Json, headers: Headers):
        """POST /bid-rounds"""
        return self._request("POST", "/bid-rounds", payload, headers)

    def get_bid_round(self, bid_round_id, headers: Headers):
        """GET /bid-rounds/{bid_round_id}"""
        return self._request("GET", f"/bid-rounds/{bid_round_id}", None, headers)

    def list_bid_rounds(self, headers: Headers, params=None):
        """GET /bid-rounds"""
        return self._request("GET", "/bid-rounds", params, headers)

    def set_bid_round_status(self, bid_round_id, payload: Json, headers: Headers):
        """POST /bid-rounds/{bid_round_id}/status"""
        return self._request(
            "POST", f"/bid-rounds/{bid_round_id}/status", payload, headers
        )

    def award_bid_round(self, bid_round_id, headers: Headers, payload: Json = None):
        """POST /bid-rounds/{bid_round_id}/award"""
        return self._request(
            "POST", f"/bid-rounds/{bid_round_id}/award", payload, headers
        )

    # ── Shift bids ────────────────────────────────────

    def create_shift_bid(self, payload: Json, headers: Headers):
        """POST /shift-bids"""
        return self._request("POST", "/shift-bids", payload, headers)

    def get_shift_bid(self, shift_bid_id, headers: Headers):
        """GET /shift-bids/{shift_bid_id}"""
        return self._request("GET", f"/shift-bids/{shift_bid_id}", None, headers)

    def list_shift_bids(self, headers: Headers, params=None):
        """GET /shift-bids"""
        return self._request("GET", "/shift-bids", params, headers)

    def withdraw_shift_bid(self, shift_bid_id, headers: Headers, payload: Json = None):
        """POST /shift-bids/{shift_bid_id}/withdraw"""
        return self._request(
            "POST", f"/shift-bids/{shift_bid_id}/withdraw", payload, headers
        )

    # ── Schedule shifts ───────────────────────────────

    def create_schedule_shift(self, payload: Json, headers: Headers):
        """POST /schedule-shifts"""
        return self._request("POST", "/schedule-shifts", payload, headers)

    def get_schedule_shift(self, schedule_shift_id, headers: Headers):
        """GET /schedule-shifts/{schedule_shift_id}"""
        return self._request(
            "GET", f"/schedule-shifts/{schedule_shift_id}", None, headers
        )

    def list_schedule_shifts(self, headers: Headers, params=None):
        """GET /schedule-shifts"""
        return self._request("GET", "/schedule-shifts", params, headers)

    def set_shift_publication(self, schedule_shift_id, payload: Json, headers: Headers):
        """POST /schedule-shifts/{schedule_shift_id}/publication"""
        return self._request(
            "POST",
            f"/schedule-shifts/{schedule_shift_id}/publication",
            payload,
            headers,
        )

    def record_adherence_observation(
        self, schedule_shift_id, payload: Json, headers: Headers
    ):
        """POST /schedule-shifts/{schedule_shift_id}/adherence-observations"""
        return self._request(
            "POST",
            f"/schedule-shifts/{schedule_shift_id}/adherence-observations",
            payload,
            headers,
        )

    # ── Adherence exceptions ──────────────────────────

    def create_adherence_exception(self, payload: Json, headers: Headers):
        """POST /adherence-exceptions"""
        return self._request("POST", "/adherence-exceptions", payload, headers)

    def get_adherence_exception(self, adherence_exception_id, headers: Headers):
        """GET /adherence-exceptions/{adherence_exception_id}"""
        return self._request(
            "GET", f"/adherence-exceptions/{adherence_exception_id}", None, headers
        )

    def list_adherence_exceptions(self, headers: Headers, params=None):
        """GET /adherence-exceptions"""
        return self._request("GET", "/adherence-exceptions", params, headers)

    def decide_adherence_exception(
        self, adherence_exception_id, payload: Json, headers: Headers
    ):
        """POST /adherence-exceptions/{adherence_exception_id}/decision"""
        return self._request(
            "POST",
            f"/adherence-exceptions/{adherence_exception_id}/decision",
            payload,
            headers,
        )

    def resubmit_adherence_exception(
        self, adherence_exception_id, payload: Json, headers: Headers
    ):
        """POST /adherence-exceptions/{adherence_exception_id}/resubmit"""
        return self._request(
            "POST",
            f"/adherence-exceptions/{adherence_exception_id}/resubmit",
            payload,
            headers,
        )

    # ── Intraday actions ──────────────────────────────

    def create_intraday_action(self, payload: Json, headers: Headers):
        """POST /intraday-actions"""
        return self._request("POST", "/intraday-actions", payload, headers)

    def get_intraday_action(self, intraday_action_id, headers: Headers):
        """GET /intraday-actions/{intraday_action_id}"""
        return self._request(
            "GET", f"/intraday-actions/{intraday_action_id}", None, headers
        )

    def list_intraday_actions(self, headers: Headers, params=None):
        """GET /intraday-actions"""
        return self._request("GET", "/intraday-actions", params, headers)

    def respond_to_intraday_action(
        self, intraday_action_id, payload: Json, headers: Headers
    ):
        """POST /intraday-actions/{intraday_action_id}/response"""
        return self._request(
            "POST", f"/intraday-actions/{intraday_action_id}/response", payload, headers
        )

    def revoke_intraday_action(
        self, intraday_action_id, headers: Headers, payload: Json = None
    ):
        """POST /intraday-actions/{intraday_action_id}/revoke"""
        return self._request(
            "POST", f"/intraday-actions/{intraday_action_id}/revoke", payload, headers
        )

    # ── Outsourced partners ───────────────────────────

    def create_outsource_partner(self, payload: Json, headers: Headers):
        """POST /outsource-partners"""
        return self._request("POST", "/outsource-partners", payload, headers)

    def get_outsource_partner(self, outsource_partner_id, headers: Headers):
        """GET /outsource-partners/{outsource_partner_id}"""
        return self._request(
            "GET", f"/outsource-partners/{outsource_partner_id}", None, headers
        )

    def list_outsource_partners(self, headers: Headers, params=None):
        """GET /outsource-partners"""
        return self._request("GET", "/outsource-partners", params, headers)

    def create_performance_report(
        self, outsource_partner_id, payload: Json, headers: Headers
    ):
        """POST /outsource-partners/{outsource_partner_id}/performance-reports"""
        return self._request(
            "POST",
            f"/outsource-partners/{outsource_partner_id}/performance-reports",
            payload,
            headers,
        )

    # ── Partner allocations ───────────────────────────

    def create_partner_allocation(self, payload: Json, headers: Headers):
        """POST /partner-allocations"""
        return self._request("POST", "/partner-allocations", payload, headers)

    def generate_partner_allocations(self, payload: Json, headers: Headers):
        """POST /partner-allocations/generate"""
        return self._request("POST", "/partner-allocations/generate", payload, headers)

    def get_partner_allocation(self, partner_allocation_id, headers: Headers):
        """GET /partner-allocations/{partner_allocation_id}"""
        return self._request(
            "GET", f"/partner-allocations/{partner_allocation_id}", None, headers
        )

    def list_partner_allocations(self, headers: Headers, params=None):
        """GET /partner-allocations"""
        return self._request("GET", "/partner-allocations", params, headers)

    def commit_partner_allocation(
        self, partner_allocation_id, payload: Json, headers: Headers
    ):
        """POST /partner-allocations/{partner_allocation_id}/commit"""
        return self._request(
            "POST",
            f"/partner-allocations/{partner_allocation_id}/commit",
            payload,
            headers,
        )

    def revoke_partner_allocation(
        self, partner_allocation_id, headers: Headers, payload: Json = None
    ):
        """POST /partner-allocations/{partner_allocation_id}/revoke"""
        return self._request(
            "POST",
            f"/partner-allocations/{partner_allocation_id}/revoke",
            payload,
            headers,
        )

    def settle_partner_allocation(
        self, partner_allocation_id, payload: Json, headers: Headers
    ):
        """POST /partner-allocations/{partner_allocation_id}/settle"""
        return self._request(
            "POST",
            f"/partner-allocations/{partner_allocation_id}/settle",
            payload,
            headers,
        )

    # ── Hiring classes ────────────────────────────────

    def create_hiring_class(self, payload: Json, headers: Headers):
        """POST /hiring-classes"""
        return self._request("POST", "/hiring-classes", payload, headers)

    def get_hiring_class(self, hiring_class_id, headers: Headers):
        """GET /hiring-classes/{hiring_class_id}"""
        return self._request("GET", f"/hiring-classes/{hiring_class_id}", None, headers)

    def list_hiring_classes(self, headers: Headers, params=None):
        """GET /hiring-classes"""
        return self._request("GET", "/hiring-classes", params, headers)

    def set_hiring_class_status(self, hiring_class_id, payload: Json, headers: Headers):
        """POST /hiring-classes/{hiring_class_id}/status"""
        return self._request(
            "POST", f"/hiring-classes/{hiring_class_id}/status", payload, headers
        )

    def graduate_hiring_class(
        self, hiring_class_id, headers: Headers, payload: Json = None
    ):
        """POST /hiring-classes/{hiring_class_id}/graduate"""
        return self._request(
            "POST", f"/hiring-classes/{hiring_class_id}/graduate", payload, headers
        )


api_client = ApiClient()
