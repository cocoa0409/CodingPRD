"""Typed HTTP client — one method per endpoint of the PRD §4 endpoint table.

All paths are mounted under the PRD §1 service prefix `/gear-service`.
Every method returns the raw requests.Response so tests can assert on the
HTTP status as well as the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _drop_none(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not params:
        return {}
    return {key: value for key, value in params.items() if value is not None}


class GearServiceApiClient(GenericApiClient):
    """One method per PRD §4 endpoint."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers=None):
        """POST /gear-service/_clock/set_current_utc — PRD §2.4."""
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # ------------------------------------------------------- service centres
    def create_service_center(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/service-centers", payload, headers)

    def get_service_center(self, center_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/service-centers/{center_id}", None, headers
        )

    def create_surge_window(self, center_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/service-centers/{center_id}/surge-windows",
            payload,
            headers,
        )

    def list_surge_windows(self, center_id, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/service-centers/{center_id}/surge-windows",
            _drop_none(params),
            headers,
        )

    def queue_review(self, center_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/service-centers/{center_id}/queue-review",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------ gear models
    def create_gear_model(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/gear-models", payload, headers)

    def get_gear_model(self, model_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/gear-models/{model_id}", None, headers
        )

    def list_gear_models(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/gear-models", _drop_none(params), headers
        )

    def patch_gear_model(self, model_id, payload, headers=None):
        return self._request(
            "PATCH", f"{API_PREFIX}/gear-models/{model_id}", payload, headers
        )

    # -------------------------------------------------------------- customers
    def create_customer(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/customers/{customer_id}", None, headers
        )

    # ------------------------------------------------------------- gear items
    def create_gear_item(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/gear-items", payload, headers)

    def get_gear_item(self, item_id, headers=None):
        return self._request("GET", f"{API_PREFIX}/gear-items/{item_id}", None, headers)

    def list_gear_items(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/gear-items", _drop_none(params), headers
        )

    def trade_in_gear_item(self, item_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/gear-items/{item_id}/trade-in", payload, headers
        )

    def set_gear_item_disposition(self, item_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/gear-items/{item_id}/disposition", payload, headers
        )

    # ------------------------------------------------------------ technicians
    def create_technician(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/technicians", payload, headers)

    def get_technician(self, technician_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/technicians/{technician_id}", None, headers
        )

    def list_technicians(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/technicians", _drop_none(params), headers
        )

    def patch_technician(self, technician_id, payload, headers=None):
        return self._request(
            "PATCH", f"{API_PREFIX}/technicians/{technician_id}", payload, headers
        )

    # ------------------------------------------------------------ work blocks
    def create_work_block(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/work-blocks", payload, headers)

    def get_work_block(self, block_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/work-blocks/{block_id}", None, headers
        )

    def list_work_blocks(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/work-blocks", _drop_none(params), headers
        )

    def cancel_work_block(self, block_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/work-blocks/{block_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------------------- part lots
    def create_part_lot(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/part-lots", payload, headers)

    def get_part_lot(self, lot_id, headers=None):
        return self._request("GET", f"{API_PREFIX}/part-lots/{lot_id}", None, headers)

    def list_part_lots(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/part-lots", _drop_none(params), headers
        )

    def adjust_part_lot(self, lot_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/part-lots/{lot_id}/adjustments", payload, headers
        )

    # ------------------------------------------------------ parts reservations
    def create_parts_reservation(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/repair-orders/{order_id}/parts-reservations",
            payload,
            headers,
        )

    def get_parts_reservation(self, reservation_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/parts-reservations/{reservation_id}", None, headers
        )

    def list_parts_reservations(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/parts-reservations", _drop_none(params), headers
        )

    def release_parts_reservation(self, reservation_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/parts-reservations/{reservation_id}/release",
            payload if payload is not None else {},
            headers,
        )

    def consume_parts_reservation(self, reservation_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/parts-reservations/{reservation_id}/consume",
            payload if payload is not None else {},
            headers,
        )

    # --------------------------------------------------------- warranty claims
    def create_warranty_claim(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/warranty-claims/{claim_id}", None, headers
        )

    def list_warranty_claims(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/warranty-claims", _drop_none(params), headers
        )

    def submit_claim(self, claim_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{claim_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def create_info_request(self, claim_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{claim_id}/info-requests",
            payload,
            headers,
        )

    def resubmit_claim(self, claim_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/warranty-claims/{claim_id}/resubmit", payload, headers
        )

    def create_assessment(self, claim_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{claim_id}/assessments",
            payload,
            headers,
        )

    def get_claim_assessment(self, assessment_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/claim-assessments/{assessment_id}", None, headers
        )

    def list_claim_assessments(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/claim-assessments", _drop_none(params), headers
        )

    def decide_claim(self, claim_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{claim_id}/decision",
            payload if payload is not None else {},
            headers,
        )

    def list_claim_liability_entries(self, claim_id, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/warranty-claims/{claim_id}/liability-entries",
            _drop_none(params),
            headers,
        )

    # ----------------------------------------------------------- repair orders
    def create_repair_order(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/repair-orders", payload, headers)

    def get_repair_order(self, order_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/repair-orders/{order_id}", None, headers
        )

    def list_repair_orders(self, headers=None, **params):
        return self._request(
            "GET", f"{API_PREFIX}/repair-orders", _drop_none(params), headers
        )

    def create_estimate(self, order_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/repair-orders/{order_id}/estimates", payload, headers
        )

    def list_order_estimates(self, order_id, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/repair-orders/{order_id}/estimates",
            _drop_none(params),
            headers,
        )

    def get_estimate(self, estimate_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/repair-estimates/{estimate_id}", None, headers
        )

    def approve_estimate(self, estimate_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/repair-estimates/{estimate_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def decline_estimate(self, estimate_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/repair-estimates/{estimate_id}/decline",
            payload if payload is not None else {},
            headers,
        )

    def bench_complete(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/repair-orders/{order_id}/bench-complete",
            payload,
            headers,
        )

    def create_qc_inspection(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/repair-orders/{order_id}/qc-inspections",
            payload,
            headers,
        )

    def close_irreparable(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/repair-orders/{order_id}/close-irreparable",
            payload,
            headers,
        )

    def invoice_order(self, order_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/repair-orders/{order_id}/invoice",
            payload if payload is not None else {},
            headers,
        )

    def pay_order(self, order_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/repair-orders/{order_id}/payments", payload, headers
        )

    def release_to_customer(self, order_id, headers=None, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/repair-orders/{order_id}/release-to-customer",
            payload if payload is not None else {},
            headers,
        )
