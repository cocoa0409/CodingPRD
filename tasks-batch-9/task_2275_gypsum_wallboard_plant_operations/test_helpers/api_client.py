"""One method per endpoint listed in PRD section 4.

Every path is written out literally so a typo in a route shows up as a 404 from
the server rather than as a silently different call.
"""

from __future__ import annotations

from typing import Any, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[dict[str, str]]
Payload = Optional[dict[str, Any]]
Params = Optional[dict[str, Any]]

BASE = "/plant-ops"


class ApiClient(GenericApiClient):
    """Typed surface for the gypsum wallboard plant operations API."""

    # ------------------------------------------------------------------ #
    # Logical clock
    # ------------------------------------------------------------------ #

    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Plants
    # ------------------------------------------------------------------ #

    def create_plant(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/plants", payload, headers)

    def list_plants(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{BASE}/plants", params, headers)

    def get_plant(self, plant_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/plants/{plant_id}", None, headers)

    # ------------------------------------------------------------------ #
    # Board lines
    # ------------------------------------------------------------------ #

    def create_board_line(
        self, plant_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/plants/{plant_id}/board-lines", payload, headers)

    def list_plant_board_lines(
        self, plant_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/plants/{plant_id}/board-lines", params, headers)

    def list_board_lines(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{BASE}/board-lines", params, headers)

    def get_board_line(self, line_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/board-lines/{line_id}", None, headers)

    # ------------------------------------------------------------------ #
    # Product specs
    # ------------------------------------------------------------------ #

    def create_product_spec(
        self, plant_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/plants/{plant_id}/product-specs", payload, headers)

    def list_plant_product_specs(
        self, plant_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/plants/{plant_id}/product-specs", params, headers)

    def list_product_specs(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/product-specs", params, headers)

    def get_product_spec(self, spec_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/product-specs/{spec_id}", None, headers)

    # ------------------------------------------------------------------ #
    # Markets
    # ------------------------------------------------------------------ #

    def create_market(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/markets", payload, headers)

    def list_markets(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{BASE}/markets", params, headers)

    def get_market(self, market_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/markets/{market_id}", None, headers)

    # ------------------------------------------------------------------ #
    # Gypsum lots
    # ------------------------------------------------------------------ #

    def create_gypsum_lot(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/gypsum-lots", payload, headers)

    def list_gypsum_lots(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{BASE}/gypsum-lots", params, headers)

    def get_gypsum_lot(self, lot_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/gypsum-lots/{lot_id}", None, headers)

    def assay_gypsum_lot(
        self, lot_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/gypsum-lots/{lot_id}/assay", payload, headers)

    def reject_gypsum_lot(
        self, lot_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/gypsum-lots/{lot_id}/reject", payload, headers)

    def list_lot_feeds(
        self, lot_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/gypsum-lots/{lot_id}/feeds", params, headers)

    # ------------------------------------------------------------------ #
    # Calciner batches
    # ------------------------------------------------------------------ #

    def create_calciner_batch(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/calciner-batches", payload, headers)

    def list_calciner_batches(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/calciner-batches", params, headers)

    def get_calciner_batch(self, batch_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/calciner-batches/{batch_id}", None, headers)

    def create_batch_feed(
        self, batch_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/calciner-batches/{batch_id}/feeds", payload, headers)

    def list_batch_feeds_of_batch(
        self, batch_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/calciner-batches/{batch_id}/feeds", params, headers)

    def close_feed(
        self, batch_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/calciner-batches/{batch_id}/close-feed", payload or {}, headers
        )

    def create_stucco_test(
        self, batch_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/calciner-batches/{batch_id}/stucco-tests", payload, headers
        )

    def list_stucco_tests_of_batch(
        self, batch_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/calciner-batches/{batch_id}/stucco-tests", params, headers
        )

    def abort_calciner_batch(
        self, batch_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/calciner-batches/{batch_id}/abort", payload, headers)

    def list_batch_feeds(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{BASE}/batch-feeds", params, headers)

    def get_batch_feed(self, feed_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/batch-feeds/{feed_id}", None, headers)

    def list_stucco_tests(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/stucco-tests", params, headers)

    def get_stucco_test(self, stucco_test_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/stucco-tests/{stucco_test_id}", None, headers)

    # ------------------------------------------------------------------ #
    # Production runs
    # ------------------------------------------------------------------ #

    def create_production_run(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/production-runs", payload, headers)

    def list_production_runs(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/production-runs", params, headers)

    def get_production_run(self, run_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/production-runs/{run_id}", None, headers)

    def schedule_run(
        self, run_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/production-runs/{run_id}/schedule", payload, headers)

    def start_run(
        self, run_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/production-runs/{run_id}/start", payload or {}, headers
        )

    def complete_run(
        self, run_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/production-runs/{run_id}/complete", payload, headers)

    def cancel_run(
        self, run_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/production-runs/{run_id}/cancel", payload, headers)

    def create_board_test(
        self, run_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/production-runs/{run_id}/board-tests", payload, headers
        )

    def list_board_tests_of_run(
        self, run_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/production-runs/{run_id}/board-tests", params, headers)

    def evaluate_quality(
        self, run_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/production-runs/{run_id}/quality-evaluation", payload or {}, headers
        )

    def disposition_quality(
        self, run_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/production-runs/{run_id}/quality-disposition", payload, headers
        )

    def list_board_tests(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{BASE}/board-tests", params, headers)

    def get_board_test(self, board_test_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/board-tests/{board_test_id}", None, headers)

    # ------------------------------------------------------------------ #
    # Maintenance outages
    # ------------------------------------------------------------------ #

    def create_outage(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/maintenance-outages", payload, headers)

    def list_outages(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{BASE}/maintenance-outages", params, headers)

    def get_outage(self, outage_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/maintenance-outages/{outage_id}", None, headers)

    def approve_outage(
        self, outage_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/maintenance-outages/{outage_id}/approve", payload or {}, headers
        )

    def defer_outage(
        self, outage_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/maintenance-outages/{outage_id}/defer", payload, headers
        )

    def repropose_outage(
        self, outage_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/maintenance-outages/{outage_id}/repropose", payload, headers
        )

    def start_outage(
        self, outage_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/maintenance-outages/{outage_id}/start", payload or {}, headers
        )

    def close_outage(
        self, outage_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/maintenance-outages/{outage_id}/close", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Load orders
    # ------------------------------------------------------------------ #

    def create_load_order(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/load-orders", payload, headers)

    def list_load_orders(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{BASE}/load-orders", params, headers)

    def get_load_order(self, load_order_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/load-orders/{load_order_id}", None, headers)

    def load_load_order(
        self, load_order_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/load-orders/{load_order_id}/load", payload, headers)

    def ship_load_order(
        self, load_order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/load-orders/{load_order_id}/ship", payload or {}, headers
        )

    def cancel_load_order(
        self, load_order_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/load-orders/{load_order_id}/cancel", payload, headers)
