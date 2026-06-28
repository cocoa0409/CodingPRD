"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() handles the
envelope, base URL, and header plumbing.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Species ----
    def create_species(self, payload, headers):
        return self._request("POST", "/species", payload, headers)

    def list_species(self, headers, params=None):
        return self._request("GET", "/species", headers=headers, params=params)

    def get_species(self, species_id, headers):
        return self._request("GET", f"/species/{species_id}", headers=headers)

    # ---- Tank ----
    def create_tank(self, payload, headers):
        return self._request("POST", "/tanks", payload, headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/tanks", headers=headers, params=params)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/tanks/{tank_id}", headers=headers)

    def set_posture_override(self, tank_id, payload, headers):
        return self._request(
            "POST", f"/tanks/{tank_id}/posture-override", payload, headers
        )

    def create_water_quality_reading(self, tank_id, payload, headers):
        return self._request(
            "POST", f"/tanks/{tank_id}/water-quality-readings", payload, headers
        )

    def list_water_quality_readings(self, tank_id, headers, params=None):
        return self._request(
            "GET", f"/tanks/{tank_id}/water-quality-readings",
            headers=headers, params=params,
        )

    # ---- BroodstockBatch ----
    def create_broodstock_batch(self, payload, headers):
        return self._request("POST", "/broodstock-batches", payload, headers)

    def list_broodstock_batches(self, headers, params=None):
        return self._request(
            "GET", "/broodstock-batches", headers=headers, params=params
        )

    def get_broodstock_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/broodstock-batches/{batch_id}", headers=headers
        )

    # ---- Cohort ----
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/cohorts", headers=headers, params=params)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def get_cohort_summary(self, cohort_id, headers):
        return self._request(
            "GET", f"/cohorts/{cohort_id}/summary", headers=headers
        )

    def create_feed_log(self, cohort_id, payload, headers):
        return self._request(
            "POST", f"/cohorts/{cohort_id}/feed-logs", payload, headers
        )

    def list_feed_logs(self, cohort_id, headers, params=None):
        return self._request(
            "GET", f"/cohorts/{cohort_id}/feed-logs", headers=headers, params=params
        )

    # ---- StockingEvent ----
    def create_stocking_event(self, payload, headers):
        return self._request("POST", "/stocking-events", payload, headers)

    def list_stocking_events(self, headers, params=None):
        return self._request(
            "GET", "/stocking-events", headers=headers, params=params
        )

    def get_stocking_event(self, event_id, headers):
        return self._request(
            "GET", f"/stocking-events/{event_id}", headers=headers
        )

    # ---- GradingEvent ----
    def create_grading_event(self, payload, headers):
        return self._request("POST", "/grading-events", payload, headers)

    def list_grading_events(self, headers, params=None):
        return self._request(
            "GET", "/grading-events", headers=headers, params=params
        )

    def get_grading_event(self, event_id, headers):
        return self._request(
            "GET", f"/grading-events/{event_id}", headers=headers
        )

    def plan_grading_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/grading-events/{event_id}/plan", payload or {}, headers
        )

    def revise_grading_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/grading-events/{event_id}/revise", payload or {}, headers
        )

    def commit_grading_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/grading-events/{event_id}/commit", payload, headers
        )

    def cancel_grading_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/grading-events/{event_id}/cancel", payload or {}, headers
        )

    # ---- HealthTreatment ----
    def create_health_treatment(self, payload, headers):
        return self._request("POST", "/health-treatments", payload, headers)

    def list_health_treatments(self, headers, params=None):
        return self._request(
            "GET", "/health-treatments", headers=headers, params=params
        )

    def get_health_treatment(self, treatment_id, headers):
        return self._request(
            "GET", f"/health-treatments/{treatment_id}", headers=headers
        )

    def complete_health_treatment(self, treatment_id, headers, payload=None):
        return self._request(
            "POST", f"/health-treatments/{treatment_id}/complete",
            payload or {}, headers,
        )

    def clear_health_treatment(self, treatment_id, headers, payload=None):
        return self._request(
            "POST", f"/health-treatments/{treatment_id}/clear",
            payload or {}, headers,
        )

    # ---- HarvestOrder ----
    def create_harvest_order(self, payload, headers):
        return self._request("POST", "/harvest-orders", payload, headers)

    def list_harvest_orders(self, headers, params=None):
        return self._request(
            "GET", "/harvest-orders", headers=headers, params=params
        )

    def get_harvest_order(self, order_id, headers):
        return self._request(
            "GET", f"/harvest-orders/{order_id}", headers=headers
        )

    def schedule_harvest_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/harvest-orders/{order_id}/schedule", payload or {}, headers
        )

    def start_harvest_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/harvest-orders/{order_id}/start", payload or {}, headers
        )

    def complete_harvest_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/harvest-orders/{order_id}/complete", payload, headers
        )

    def cancel_harvest_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/harvest-orders/{order_id}/cancel", payload or {}, headers
        )

    # ---- ProcessingBatch ----
    def create_processing_batch(self, payload, headers):
        return self._request("POST", "/processing-batches", payload, headers)

    def list_processing_batches(self, headers, params=None):
        return self._request(
            "GET", "/processing-batches", headers=headers, params=params
        )

    def get_processing_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/processing-batches/{batch_id}", headers=headers
        )

    def start_processing_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/processing-batches/{batch_id}/start", payload or {}, headers
        )

    def complete_processing_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/processing-batches/{batch_id}/complete", payload, headers
        )

    def reject_processing_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/processing-batches/{batch_id}/reject", payload or {}, headers
        )

    # ---- ProductLot ----
    def list_product_lots(self, headers, params=None):
        return self._request(
            "GET", "/product-lots", headers=headers, params=params
        )

    def get_product_lot(self, lot_id, headers):
        return self._request("GET", f"/product-lots/{lot_id}", headers=headers)

    # ---- SalesOrder & lines ----
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request(
            "GET", "/sales-orders", headers=headers, params=params
        )

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def add_sales_order_line(self, order_id, payload, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/lines", payload, headers
        )

    def list_sales_order_lines(self, headers, params=None):
        return self._request(
            "GET", "/sales-order-lines", headers=headers, params=params
        )

    def get_sales_order_line(self, line_id, headers):
        return self._request(
            "GET", f"/sales-order-lines/{line_id}", headers=headers
        )

    def confirm_sales_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/confirm", payload, headers
        )

    def fulfill_sales_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/sales-orders/{order_id}/fulfill", payload or {}, headers
        )

    def cancel_sales_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/sales-orders/{order_id}/cancel", payload or {}, headers
        )


api_client = ApiClient()
