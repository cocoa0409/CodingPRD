"""API client: one method per endpoint declared in PRD section 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Electric Outage Management & Storm Restoration API.

    Every endpoint mounts under the `/om` prefix.
    """

    # --- Logical clock (test-driving, PRD 2.4) ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/_clock/set_current_utc", payload, headers)

    # --- Storm events ---
    def create_storm_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/storm-events", payload, headers)

    def list_storm_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/om/storm-events", headers=headers, params=params)

    def get_storm_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/storm-events/{event_id}", headers=headers
        )

    def activate_storm_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/storm-events/{event_id}/activate", {}, headers
        )

    def begin_demobilization(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/storm-events/{event_id}/begin_demobilization", {}, headers
        )

    def close_storm_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/storm-events/{event_id}/close", {}, headers
        )

    def run_clustering(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/storm-events/{event_id}/run_clustering", payload, headers
        )

    def dispatch_next(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/storm-events/{event_id}/dispatch_next", payload, headers
        )

    def get_cost_summary(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/storm-events/{event_id}/cost-summary", headers=headers
        )

    # --- Feeders ---
    def create_feeder(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/feeders", payload, headers)

    def get_feeder(self, feeder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/om/feeders/{feeder_id}", headers=headers)

    # --- Priority customers ---
    def create_priority_customer(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/om/priority-customers", payload, headers)

    def get_priority_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/priority-customers/{customer_id}", headers=headers
        )

    def list_priority_customers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/priority-customers", headers=headers, params=params
        )

    def certify_priority_customer(
        self, customer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/om/priority-customers/{customer_id}/certify",
            payload,
            headers,
        )

    def decertify_priority_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/priority-customers/{customer_id}/decertify", {}, headers
        )

    # --- Trouble signals ---
    def create_trouble_signal(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/om/trouble-signals", payload, headers)

    def get_trouble_signal(self, signal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/trouble-signals/{signal_id}", headers=headers
        )

    def list_trouble_signals(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/trouble-signals", headers=headers, params=params
        )

    # --- Outages ---
    def create_outage(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/outages", payload, headers)

    def get_outage(self, outage_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/om/outages/{outage_id}", headers=headers)

    def list_outages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/om/outages", headers=headers, params=params)

    def confirm_outage(
        self, outage_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/outages/{outage_id}/confirm", payload, headers
        )

    def cancel_outage(self, outage_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/om/outages/{outage_id}/cancel", {}, headers)

    def merge_outage(
        self, outage_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/outages/{outage_id}/merge", payload, headers
        )

    def report_restored(self, outage_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/outages/{outage_id}/report_restored", {}, headers
        )

    def verify_outage(self, outage_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/om/outages/{outage_id}/verify", {}, headers)

    # --- ETR revisions ---
    def list_etr_revisions(
        self, outage_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/om/outages/{outage_id}/etr-revisions",
            headers=headers,
            params=params,
        )

    def publish_etr_revision(
        self, outage_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/outages/{outage_id}/etr-revisions", payload, headers
        )

    # --- Damage assessments ---
    def list_outage_damage_assessments(
        self, outage_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/om/outages/{outage_id}/damage-assessments",
            headers=headers,
            params=params,
        )

    def create_damage_assessment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/om/damage-assessments", payload, headers)

    def get_damage_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/damage-assessments/{assessment_id}", headers=headers
        )

    def list_damage_assessments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/damage-assessments", headers=headers, params=params
        )

    def submit_damage_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/damage-assessments/{assessment_id}/submit", {}, headers
        )

    def return_damage_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/damage-assessments/{assessment_id}/return", {}, headers
        )

    def accept_damage_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/damage-assessments/{assessment_id}/accept", payload, headers
        )

    # --- Internal crews ---
    def create_crew(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/crews", payload, headers)

    def get_crew(self, crew_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/om/crews/{crew_id}", headers=headers)

    def start_shift(self, crew_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/om/crews/{crew_id}/start_shift", {}, headers)

    def end_shift(self, crew_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/om/crews/{crew_id}/end_shift", {}, headers)

    # --- Mutual-aid crews ---
    def create_mutual_aid_crew(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/om/mutual-aid-crews", payload, headers)

    def get_mutual_aid_crew(self, crew_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/mutual-aid-crews/{crew_id}", headers=headers
        )

    def list_mutual_aid_crews(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/mutual-aid-crews", headers=headers, params=params
        )

    def mark_arrived(self, crew_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/mutual-aid-crews/{crew_id}/mark_arrived", {}, headers
        )

    def assign_lodging(
        self, crew_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/mutual-aid-crews/{crew_id}/assign_lodging", payload, headers
        )

    def demobilize_mutual_aid_crew(self, crew_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/mutual-aid-crews/{crew_id}/demobilize", {}, headers
        )

    def depart_mutual_aid_crew(
        self, crew_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/mutual-aid-crews/{crew_id}/depart", payload, headers
        )

    def cancel_mutual_aid_crew(self, crew_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/mutual-aid-crews/{crew_id}/cancel", {}, headers
        )

    # --- Lodging blocks ---
    def create_lodging_block(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/lodging-blocks", payload, headers)

    def get_lodging_block(self, block_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/om/lodging-blocks/{block_id}", headers=headers)

    def list_lodging_blocks(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/lodging-blocks", headers=headers, params=params
        )

    def commit_lodging_block(self, block_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/lodging-blocks/{block_id}/commit", {}, headers
        )

    def release_lodging_block(self, block_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/lodging-blocks/{block_id}/release", {}, headers
        )

    # --- Work orders ---
    def create_work_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/work-orders", payload, headers)

    def get_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/work-orders/{work_order_id}", headers=headers
        )

    def list_work_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/work-orders", headers=headers, params=params
        )

    def ready_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/work-orders/{work_order_id}/ready", {}, headers
        )

    def assign_work_order(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/work-orders/{work_order_id}/assign", payload, headers
        )

    def arrive_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/work-orders/{work_order_id}/arrive", {}, headers
        )

    def start_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/work-orders/{work_order_id}/start", {}, headers
        )

    def complete_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/work-orders/{work_order_id}/complete", {}, headers
        )

    def verify_work_order(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/work-orders/{work_order_id}/verify", payload, headers
        )

    def cancel_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/work-orders/{work_order_id}/cancel", {}, headers
        )

    # --- Switching orders ---
    def create_switching_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/om/switching-orders", payload, headers)

    def get_switching_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/switching-orders/{order_id}", headers=headers
        )

    def list_switching_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/switching-orders", headers=headers, params=params
        )

    def issue_switching_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/switching-orders/{order_id}/issue", {}, headers
        )

    def approve_switching_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/switching-orders/{order_id}/approve", {}, headers
        )

    def execute_switching_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/switching-orders/{order_id}/execute", {}, headers
        )

    def abort_switching_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/switching-orders/{order_id}/abort", {}, headers
        )

    # --- Material stock pools ---
    def create_material_stock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/material-stocks", payload, headers)

    def get_material_stock(self, stock_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/material-stocks/{stock_id}", headers=headers
        )

    # --- Material requisitions ---
    def create_material_requisition(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/om/material-requisitions", payload, headers)

    def get_material_requisition(self, requisition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/material-requisitions/{requisition_id}", headers=headers
        )

    def list_material_requisitions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/material-requisitions", headers=headers, params=params
        )

    def stage_material_requisition(self, requisition_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/material-requisitions/{requisition_id}/stage", {}, headers
        )

    def issue_material_requisition(self, requisition_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/material-requisitions/{requisition_id}/issue", {}, headers
        )

    def return_material_requisition(self, requisition_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/material-requisitions/{requisition_id}/return", {}, headers
        )

    def consume_material_requisition(self, requisition_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/material-requisitions/{requisition_id}/consume", {}, headers
        )

    def cancel_material_requisition(self, requisition_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/material-requisitions/{requisition_id}/cancel", {}, headers
        )

    # --- Cost ledger (read-only) ---
    def get_cost_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/om/cost-ledger-entries/{entry_id}", headers=headers
        )

    def list_cost_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/om/cost-ledger-entries", headers=headers, params=params
        )

    # --- FEMA claims ---
    def create_fema_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/om/fema-claims", payload, headers)

    def get_fema_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/om/fema-claims/{claim_id}", headers=headers)

    def list_fema_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/om/fema-claims", headers=headers, params=params)

    def submit_fema_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/fema-claims/{claim_id}/submit", {}, headers
        )

    def certify_fema_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/fema-claims/{claim_id}/certify", {}, headers
        )

    def withdraw_fema_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/om/fema-claims/{claim_id}/withdraw", payload, headers
        )

    def obligate_fema_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/fema-claims/{claim_id}/obligate", {}, headers
        )

    def mark_paid_fema_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/om/fema-claims/{claim_id}/mark_paid", {}, headers
        )


api_client = ApiClient()
