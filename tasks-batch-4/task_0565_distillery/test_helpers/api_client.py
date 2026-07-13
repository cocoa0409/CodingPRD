"""API client: one method per endpoint defined in the PRD (mounted under /dsp)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/dsp/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def set_cbma_ytd(self, distillery_id, cbma_pg_removed_ytd, headers):
        return self._request(
            "POST", "/dsp/_ledger/set_cbma_ytd",
            {"distillery_id": distillery_id, "cbma_pg_removed_ytd": cbma_pg_removed_ytd},
            headers,
        )

    # ---- Distillery ----
    def create_distillery(self, payload, headers):
        return self._request("POST", "/dsp/distilleries", payload, headers)

    def get_distillery(self, distillery_id, headers):
        return self._request("GET", f"/dsp/distilleries/{distillery_id}", headers=headers)

    def list_distilleries(self, headers, params=None):
        return self._request("GET", "/dsp/distilleries", headers=headers, params=params)

    def set_club_release(self, distillery_id, active, headers):
        return self._request("POST", f"/dsp/distilleries/{distillery_id}/club-release", {"active": active}, headers)

    # ---- MashBatch ----
    def create_mash_batch(self, payload, headers):
        return self._request("POST", "/dsp/mash-batches", payload, headers)

    def get_mash_batch(self, mash_batch_id, headers):
        return self._request("GET", f"/dsp/mash-batches/{mash_batch_id}", headers=headers)

    def list_mash_batches(self, headers, params=None):
        return self._request("GET", "/dsp/mash-batches", headers=headers, params=params)

    def dump_mash_batch(self, mash_batch_id, headers):
        return self._request("POST", f"/dsp/mash-batches/{mash_batch_id}/dump", {}, headers)

    # ---- DistillationRun ----
    def create_distillation_run(self, payload, headers):
        return self._request("POST", "/dsp/distillation-runs", payload, headers)

    def get_distillation_run(self, run_id, headers):
        return self._request("GET", f"/dsp/distillation-runs/{run_id}", headers=headers)

    def list_distillation_runs(self, headers, params=None):
        return self._request("GET", "/dsp/distillation-runs", headers=headers, params=params)

    def gauge_run(self, run_id, headers):
        return self._request("POST", f"/dsp/distillation-runs/{run_id}/gauge", {}, headers)

    # ---- Barrel ----
    def create_barrel(self, payload, headers):
        return self._request("POST", "/dsp/barrels", payload, headers)

    def get_barrel(self, barrel_id, headers):
        return self._request("GET", f"/dsp/barrels/{barrel_id}", headers=headers)

    def list_barrels(self, headers, params=None):
        return self._request("GET", "/dsp/barrels", headers=headers, params=params)

    def dump_barrel(self, barrel_id, headers):
        return self._request("POST", f"/dsp/barrels/{barrel_id}/dump", {}, headers)

    # ---- LabelApplication ----
    def create_label_application(self, payload, headers):
        return self._request("POST", "/dsp/label-applications", payload, headers)

    def get_label_application(self, label_id, headers):
        return self._request("GET", f"/dsp/label-applications/{label_id}", headers=headers)

    def list_label_applications(self, headers, params=None):
        return self._request("GET", "/dsp/label-applications", headers=headers, params=params)

    def submit_label(self, label_id, headers):
        return self._request("POST", f"/dsp/label-applications/{label_id}/submit", {}, headers)

    def decide_label(self, label_id, payload, headers):
        return self._request("POST", f"/dsp/label-applications/{label_id}/decide", payload, headers)

    def resubmit_label(self, label_id, headers):
        return self._request("POST", f"/dsp/label-applications/{label_id}/resubmit", {}, headers)

    # ---- BottlingRun ----
    def create_bottling_run(self, payload, headers):
        return self._request("POST", "/dsp/bottling-runs", payload, headers)

    def get_bottling_run(self, run_id, headers):
        return self._request("GET", f"/dsp/bottling-runs/{run_id}", headers=headers)

    def list_bottling_runs(self, headers, params=None):
        return self._request("GET", "/dsp/bottling-runs", headers=headers, params=params)

    def start_bottling_run(self, run_id, headers):
        return self._request("POST", f"/dsp/bottling-runs/{run_id}/start", {}, headers)

    def complete_bottling_run(self, run_id, headers):
        return self._request("POST", f"/dsp/bottling-runs/{run_id}/complete", {}, headers)

    def cancel_bottling_run(self, run_id, headers):
        return self._request("POST", f"/dsp/bottling-runs/{run_id}/cancel", {}, headers)

    # ---- TaxRemoval ----
    def create_tax_removal(self, payload, headers):
        return self._request("POST", "/dsp/tax-removals", payload, headers)

    def get_tax_removal(self, removal_id, headers):
        return self._request("GET", f"/dsp/tax-removals/{removal_id}", headers=headers)

    def list_tax_removals(self, headers, params=None):
        return self._request("GET", "/dsp/tax-removals", headers=headers, params=params)

    # ---- ExciseReport ----
    def create_excise_report(self, payload, headers):
        return self._request("POST", "/dsp/excise-reports", payload, headers)

    def get_excise_report(self, report_id, headers):
        return self._request("GET", f"/dsp/excise-reports/{report_id}", headers=headers)

    def list_excise_reports(self, headers, params=None):
        return self._request("GET", "/dsp/excise-reports", headers=headers, params=params)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/dsp/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/dsp/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/dsp/customers", headers=headers, params=params)

    # ---- SalesOrder ----
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/dsp/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/dsp/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/dsp/sales-orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/dsp/sales-orders/{order_id}/pay", {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/dsp/sales-orders/{order_id}/ship", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/dsp/sales-orders/{order_id}/cancel", {}, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/dsp/sales-orders/{order_id}/refund", {}, headers)

    # ---- TourBooking ----
    def create_tour_booking(self, payload, headers):
        return self._request("POST", "/dsp/tour-bookings", payload, headers)

    def get_tour_booking(self, booking_id, headers):
        return self._request("GET", f"/dsp/tour-bookings/{booking_id}", headers=headers)

    def list_tour_bookings(self, headers, params=None):
        return self._request("GET", "/dsp/tour-bookings", headers=headers, params=params)

    def confirm_tour(self, booking_id, headers):
        return self._request("POST", f"/dsp/tour-bookings/{booking_id}/confirm", {}, headers)

    def cancel_tour(self, booking_id, headers):
        return self._request("POST", f"/dsp/tour-bookings/{booking_id}/cancel", {}, headers)


api_client = ApiClient()
