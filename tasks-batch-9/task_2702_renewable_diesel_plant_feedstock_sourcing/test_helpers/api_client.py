"""Typed client: one method per endpoint in the endpoint table.

Every method takes the request payload (where the endpoint has one) plus the
caller's auth headers and returns the raw `requests.Response` so tests can
assert on status codes as well as bodies.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -----------------------------------------------------------------
    # Suppliers
    # -----------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", None, headers)

    def create_traceability_document(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/traceability-documents", payload, headers
        )

    def list_traceability_documents(self, supplier_id, headers, params=None):
        return self._request(
            "GET",
            f"/suppliers/{supplier_id}/traceability-documents",
            params or {},
            headers,
        )

    def verify_due_diligence(self, supplier_id, payload, headers):
        return self._request(
            "POST",
            f"/suppliers/{supplier_id}/due-diligence-verifications",
            payload,
            headers,
        )

    def suspend_supplier(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/suspensions", payload, headers
        )

    # -----------------------------------------------------------------
    # Feedstock lots
    # -----------------------------------------------------------------
    def create_feedstock_lot(self, payload, headers):
        return self._request("POST", "/feedstock-lots", payload, headers)

    def get_feedstock_lot(self, lot_id, headers):
        return self._request("GET", f"/feedstock-lots/{lot_id}", None, headers)

    def list_feedstock_lots(self, headers, params=None):
        return self._request("GET", "/feedstock-lots", params or {}, headers)

    def create_quality_test(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/feedstock-lots/{lot_id}/quality-tests", payload, headers
        )

    def list_quality_tests(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/feedstock-lots/{lot_id}/quality-tests", params or {}, headers
        )

    def create_pretreatment(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/feedstock-lots/{lot_id}/pretreatments", payload, headers
        )

    def accept_lot(self, lot_id, headers, payload=None):
        return self._request(
            "POST", f"/feedstock-lots/{lot_id}/acceptances", payload or {}, headers
        )

    def list_lot_allocations(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/feedstock-lots/{lot_id}/allocations", params or {}, headers
        )

    # -----------------------------------------------------------------
    # Hydrotreating units
    # -----------------------------------------------------------------
    def create_unit(self, payload, headers):
        return self._request("POST", "/hydrotreating-units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/hydrotreating-units/{unit_id}", None, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/hydrotreating-units", params or {}, headers)

    def create_catalyst_charge(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/hydrotreating-units/{unit_id}/catalyst-charges", payload, headers
        )

    def list_catalyst_charges(self, unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/hydrotreating-units/{unit_id}/catalyst-charges",
            params or {},
            headers,
        )

    def create_turnaround_window(self, unit_id, payload, headers):
        return self._request(
            "POST",
            f"/hydrotreating-units/{unit_id}/turnaround-windows",
            payload,
            headers,
        )

    def list_turnaround_windows(self, unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/hydrotreating-units/{unit_id}/turnaround-windows",
            params or {},
            headers,
        )

    # -----------------------------------------------------------------
    # Turnaround window transitions
    # -----------------------------------------------------------------
    def approve_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/turnaround-windows/{window_id}/approvals", payload or {}, headers
        )

    def start_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/turnaround-windows/{window_id}/starts", payload or {}, headers
        )

    def complete_window(self, window_id, headers, payload=None):
        return self._request(
            "POST",
            f"/turnaround-windows/{window_id}/completions",
            payload or {},
            headers,
        )

    def cancel_window(self, window_id, headers, payload=None):
        return self._request(
            "POST",
            f"/turnaround-windows/{window_id}/cancellations",
            payload or {},
            headers,
        )

    # -----------------------------------------------------------------
    # Hydrogen contracts and nominations
    # -----------------------------------------------------------------
    def create_hydrogen_contract(self, payload, headers):
        return self._request("POST", "/hydrogen-contracts", payload, headers)

    def get_hydrogen_contract(self, contract_id, headers):
        return self._request("GET", f"/hydrogen-contracts/{contract_id}", None, headers)

    def create_nomination(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/hydrogen-contracts/{contract_id}/nominations", payload, headers
        )

    def list_contract_nominations(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/hydrogen-contracts/{contract_id}/nominations",
            params or {},
            headers,
        )

    def list_run_nominations(self, run_id, headers, params=None):
        return self._request(
            "GET",
            f"/processing-runs/{run_id}/hydrogen-nominations",
            params or {},
            headers,
        )

    def cancel_nomination(self, nomination_id, headers, payload=None):
        return self._request(
            "POST",
            f"/hydrogen-nominations/{nomination_id}/cancellations",
            payload or {},
            headers,
        )

    # -----------------------------------------------------------------
    # Processing runs (campaigns)
    # -----------------------------------------------------------------
    def create_processing_run(self, payload, headers):
        return self._request("POST", "/processing-runs", payload, headers)

    def get_processing_run(self, run_id, headers):
        return self._request("GET", f"/processing-runs/{run_id}", None, headers)

    def list_processing_runs(self, headers, params=None):
        return self._request("GET", "/processing-runs", params or {}, headers)

    def create_allocation(self, run_id, payload, headers):
        return self._request(
            "POST", f"/processing-runs/{run_id}/allocations", payload, headers
        )

    def list_run_allocations(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/processing-runs/{run_id}/allocations", params or {}, headers
        )

    def release_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/feedstock-allocations/{allocation_id}/releases",
            payload or {},
            headers,
        )

    def secure_hydrogen(self, run_id, headers, payload=None):
        return self._request(
            "POST",
            f"/processing-runs/{run_id}/hydrogen-securements",
            payload or {},
            headers,
        )

    def start_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/processing-runs/{run_id}/starts", payload or {}, headers
        )

    def complete_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/processing-runs/{run_id}/completions", payload, headers
        )

    def reconcile_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/processing-runs/{run_id}/reconciliations", payload or {}, headers
        )

    def abort_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/processing-runs/{run_id}/aborts", payload, headers
        )

    # -----------------------------------------------------------------
    # Product batches
    # -----------------------------------------------------------------
    def get_product_batch(self, batch_id, headers):
        return self._request("GET", f"/product-batches/{batch_id}", None, headers)

    def list_product_batches(self, headers, params=None):
        return self._request("GET", "/product-batches", params or {}, headers)

    def request_certification(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/product-batches/{batch_id}/certification-requests", payload, headers
        )

    def decide_certification(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/product-batches/{batch_id}/certification-decisions",
            payload,
            headers,
        )

    def reserve_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/product-batches/{batch_id}/reservations", payload, headers
        )

    def release_batch_reservation(self, batch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/product-batches/{batch_id}/reservation-releases",
            payload or {},
            headers,
        )

    def ship_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/product-batches/{batch_id}/shipments", payload or {}, headers
        )

    # -----------------------------------------------------------------
    # Pathway registrations
    # -----------------------------------------------------------------
    def create_pathway(self, payload, headers):
        return self._request("POST", "/pathway-registrations", payload, headers)

    def get_pathway(self, pathway_id, headers):
        return self._request(
            "GET", f"/pathway-registrations/{pathway_id}", None, headers
        )

    def list_pathways(self, headers, params=None):
        return self._request("GET", "/pathway-registrations", params or {}, headers)

    def submit_pathway(self, pathway_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pathway-registrations/{pathway_id}/submissions",
            payload or {},
            headers,
        )

    def start_pathway_review(self, pathway_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pathway-registrations/{pathway_id}/review-starts",
            payload or {},
            headers,
        )

    def decide_pathway_review(self, pathway_id, payload, headers):
        return self._request(
            "POST",
            f"/pathway-registrations/{pathway_id}/review-decisions",
            payload,
            headers,
        )

    # -----------------------------------------------------------------
    # Credit blocks
    # -----------------------------------------------------------------
    def create_credit_block(self, payload, headers):
        return self._request("POST", "/credit-blocks", payload, headers)

    def get_credit_block(self, block_id, headers):
        return self._request("GET", f"/credit-blocks/{block_id}", None, headers)

    def list_credit_blocks(self, headers, params=None):
        return self._request("GET", "/credit-blocks", params or {}, headers)

    def internal_signoff(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/credit-blocks/{block_id}/internal-signoffs", payload or {}, headers
        )

    def submit_for_verification(self, block_id, headers, payload=None):
        return self._request(
            "POST",
            f"/credit-blocks/{block_id}/verification-submissions",
            payload or {},
            headers,
        )

    def decide_verification(self, block_id, payload, headers):
        return self._request(
            "POST", f"/credit-blocks/{block_id}/verification-decisions", payload, headers
        )

    def retire_credits(self, block_id, payload, headers):
        return self._request(
            "POST", f"/credit-blocks/{block_id}/retirements", payload, headers
        )

    def reverse_retirement(self, block_id, payload, headers):
        return self._request(
            "POST", f"/credit-blocks/{block_id}/retirement-reversals", payload, headers
        )

    # -----------------------------------------------------------------
    # Hedge positions
    # -----------------------------------------------------------------
    def create_hedge_position(self, payload, headers):
        return self._request("POST", "/hedge-positions", payload, headers)

    def get_hedge_position(self, position_id, headers):
        return self._request("GET", f"/hedge-positions/{position_id}", None, headers)

    def list_hedge_positions(self, headers, params=None):
        return self._request("GET", "/hedge-positions", params or {}, headers)

    def unwind_hedge_position(self, position_id, payload, headers):
        return self._request(
            "POST", f"/hedge-positions/{position_id}/unwinds", payload, headers
        )
