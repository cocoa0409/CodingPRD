"""
One method per endpoint declared by the PRD.

Every method returns the raw `requests.Response` so tests can assert on the
HTTP status as well as the body.  All paths are rooted at the declared API
prefix; the logical-clock endpoint is the single exception and lives outside it.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


def _wire_query(params):
    """
    Render query values the way HTTP carries them.

    A Python bool stringifies to ``True``/``False``, which is not the spelling a
    boolean filter is enumerated with on the wire; send ``true``/``false``.
    """
    if not isinstance(params, dict):
        return params
    rendered = {}
    for key, value in params.items():
        if isinstance(value, bool):
            rendered[key] = "true" if value else "false"
        else:
            rendered[key] = value
    return rendered


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        if method.upper() in ("GET", "DELETE"):
            payload = _wire_query(payload)
        return super()._request(
            method, path, payload, headers, _wire_query(params)
        )

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------
    def create_category(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/categories", payload, headers)

    def get_category(self, category_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/categories/{category_id}", None, headers
        )

    def list_categories(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/categories", params, headers)

    # ------------------------------------------------------------------
    # Stores
    # ------------------------------------------------------------------
    def create_store(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/stores", payload, headers)

    def get_store(self, store_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/stores/{store_id}", None, headers)

    def list_stores(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/stores", params, headers)

    def get_store_fulfillment_eligibility(self, store_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/stores/{store_id}/fulfillment-eligibility", None, headers
        )

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------
    def create_vendor(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/vendors/{vendor_id}", None, headers)

    def list_vendors(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/vendors", params, headers)

    def create_chargeback(self, vendor_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/vendors/{vendor_id}/chargebacks", payload, headers
        )

    def create_chargeback_credit(self, vendor_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/vendors/{vendor_id}/chargeback-credits",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Counter firms
    # ------------------------------------------------------------------
    def create_counter_firm(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/counter-firms", payload, headers)

    def get_counter_firm(self, counter_firm_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/counter-firms/{counter_firm_id}", None, headers
        )

    def list_counter_firms(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/counter-firms", params, headers)

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------
    def create_item(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/items", payload, headers)

    def get_item(self, item_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/items/{item_id}", None, headers)

    def list_items(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/items", params, headers)

    # ------------------------------------------------------------------
    # Stock positions
    # ------------------------------------------------------------------
    def create_stock_position(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/stock-positions", payload, headers)

    def get_stock_position(self, stock_position_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/stock-positions/{stock_position_id}", None, headers
        )

    def list_stock_positions(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/stock-positions", params, headers)

    def get_stock_position_accuracy(self, stock_position_id: str, headers: dict):
        return self._request(
            "GET",
            f"{API_PREFIX}/stock-positions/{stock_position_id}/accuracy",
            None,
            headers,
        )

    def run_integrity_scan(self, stock_position_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/stock-positions/{stock_position_id}/integrity-scan",
            payload if payload is not None else {},
            headers,
        )

    def create_adjustment(self, stock_position_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/stock-positions/{stock_position_id}/adjustments",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Adjustments
    # ------------------------------------------------------------------
    def get_adjustment(self, adjustment_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/adjustments/{adjustment_id}", None, headers
        )

    def list_adjustments(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/adjustments", params, headers)

    def approve_adjustment(self, adjustment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/adjustments/{adjustment_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def reject_adjustment(self, adjustment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/adjustments/{adjustment_id}/reject",
            payload if payload is not None else {},
            headers,
        )

    def post_adjustment(self, adjustment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/adjustments/{adjustment_id}/post",
            payload if payload is not None else {},
            headers,
        )

    def reverse_adjustment(self, adjustment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/adjustments/{adjustment_id}/reverse",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Tag batches
    # ------------------------------------------------------------------
    def create_tag_batch(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/tag-batches", payload, headers)

    def get_tag_batch(self, tag_batch_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/tag-batches/{tag_batch_id}", None, headers
        )

    def list_tag_batches(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/tag-batches", params, headers)

    def encode_tag_batch(self, tag_batch_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/tag-batches/{tag_batch_id}/encode", payload, headers
        )

    def receive_tag_batch(self, tag_batch_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/tag-batches/{tag_batch_id}/receive",
            payload if payload is not None else {},
            headers,
        )

    def verify_tag_batch(self, tag_batch_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/tag-batches/{tag_batch_id}/verify", payload, headers
        )

    def rework_tag_batch(self, tag_batch_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/tag-batches/{tag_batch_id}/rework",
            payload if payload is not None else {},
            headers,
        )

    def scrap_tag_batch(self, tag_batch_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/tag-batches/{tag_batch_id}/scrap",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Count schedules
    # ------------------------------------------------------------------
    def create_count_schedule(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/count-schedules", payload, headers)

    def get_count_schedule(self, count_schedule_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/count-schedules/{count_schedule_id}", None, headers
        )

    def list_count_schedules(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/count-schedules", params, headers)

    def pause_count_schedule(self, count_schedule_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/count-schedules/{count_schedule_id}/pause",
            payload if payload is not None else {},
            headers,
        )

    def resume_count_schedule(self, count_schedule_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/count-schedules/{count_schedule_id}/resume",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Count tasks and count lines
    # ------------------------------------------------------------------
    def create_count_task(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/count-tasks", payload, headers)

    def get_count_task(self, count_task_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/count-tasks/{count_task_id}", None, headers
        )

    def list_count_tasks(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/count-tasks", params, headers)

    def start_count_task(self, count_task_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/count-tasks/{count_task_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def create_count_line(self, count_task_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/count-tasks/{count_task_id}/lines", payload, headers
        )

    def get_count_line(self, count_line_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/count-lines/{count_line_id}", None, headers
        )

    def list_count_lines(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/count-lines", params, headers)

    def submit_count_task(self, count_task_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/count-tasks/{count_task_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def return_count_task_to_count(self, count_task_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/count-tasks/{count_task_id}/return-to-count",
            payload if payload is not None else {},
            headers,
        )

    def reconcile_count_task(self, count_task_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/count-tasks/{count_task_id}/reconcile",
            payload if payload is not None else {},
            headers,
        )

    def void_count_task(self, count_task_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/count-tasks/{count_task_id}/void",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Variance investigations
    # ------------------------------------------------------------------
    def get_investigation(self, investigation_id: str, headers: dict):
        return self._request(
            "GET",
            f"{API_PREFIX}/variance-investigations/{investigation_id}",
            None,
            headers,
        )

    def list_investigations(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/variance-investigations", params, headers
        )

    def assign_investigation(self, investigation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/variance-investigations/{investigation_id}/assign",
            payload,
            headers,
        )

    def propose_cause(self, investigation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/variance-investigations/{investigation_id}/propose-cause",
            payload,
            headers,
        )

    def return_investigation(self, investigation_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/variance-investigations/{investigation_id}/return",
            payload if payload is not None else {},
            headers,
        )

    def approve_cause(self, investigation_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/variance-investigations/{investigation_id}/approve-cause",
            payload if payload is not None else {},
            headers,
        )

    def close_investigation(self, investigation_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/variance-investigations/{investigation_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Shrink periods
    # ------------------------------------------------------------------
    def create_shrink_period(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/shrink-periods", payload, headers)

    def get_shrink_period(self, shrink_period_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/shrink-periods/{shrink_period_id}", None, headers
        )

    def list_shrink_periods(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/shrink-periods", params, headers)

    def get_shrink_period_attribution(self, shrink_period_id: str, headers: dict):
        return self._request(
            "GET",
            f"{API_PREFIX}/shrink-periods/{shrink_period_id}/attribution",
            None,
            headers,
        )

    def provisional_close_shrink_period(self, shrink_period_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/shrink-periods/{shrink_period_id}/provisional-close",
            payload if payload is not None else {},
            headers,
        )

    def reopen_shrink_period(self, shrink_period_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/shrink-periods/{shrink_period_id}/reopen",
            payload if payload is not None else {},
            headers,
        )

    def final_close_shrink_period(self, shrink_period_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/shrink-periods/{shrink_period_id}/final-close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Physical inventories
    # ------------------------------------------------------------------
    def create_physical_inventory(self, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/physical-inventories", payload, headers
        )

    def get_physical_inventory(self, physical_inventory_id: str, headers: dict):
        return self._request(
            "GET",
            f"{API_PREFIX}/physical-inventories/{physical_inventory_id}",
            None,
            headers,
        )

    def list_physical_inventories(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/physical-inventories", params, headers
        )

    def start_physical_inventory(self, physical_inventory_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/physical-inventories/{physical_inventory_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def create_physical_inventory_line(self, physical_inventory_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/physical-inventories/{physical_inventory_id}/lines",
            payload,
            headers,
        )

    def get_physical_inventory_line(self, physical_inventory_line_id: str, headers: dict):
        return self._request(
            "GET",
            f"{API_PREFIX}/physical-inventory-lines/{physical_inventory_line_id}",
            None,
            headers,
        )

    def list_physical_inventory_lines(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/physical-inventory-lines", params, headers
        )

    def complete_pass(self, physical_inventory_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/physical-inventories/{physical_inventory_id}/complete-pass",
            payload if payload is not None else {},
            headers,
        )

    def order_recount(self, physical_inventory_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/physical-inventories/{physical_inventory_id}/order-recount",
            payload if payload is not None else {},
            headers,
        )

    def reconcile_physical_inventory(self, physical_inventory_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/physical-inventories/{physical_inventory_id}/reconcile",
            payload if payload is not None else {},
            headers,
        )

    def certify_physical_inventory(self, physical_inventory_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/physical-inventories/{physical_inventory_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    def abandon_physical_inventory(self, physical_inventory_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/physical-inventories/{physical_inventory_id}/abandon",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers
        )
