"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Every resource is mounted under the ``/mill`` prefix, with the sole
    exception of the logical-clock capability."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Species profiles
    # ------------------------------------------------------------------
    def create_species_profile(self, payload, headers):
        return self._request("POST", "/mill/species-profiles", payload, headers)

    def get_species_profile(self, species_profile_id, headers):
        return self._request(
            "GET", f"/mill/species-profiles/{species_profile_id}", headers=headers
        )

    def list_species_profiles(self, headers, params=None):
        return self._request(
            "GET", "/mill/species-profiles", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Drying schedules
    # ------------------------------------------------------------------
    def create_drying_schedule(self, payload, headers):
        return self._request("POST", "/mill/drying-schedules", payload, headers)

    def get_drying_schedule(self, drying_schedule_id, headers):
        return self._request(
            "GET", f"/mill/drying-schedules/{drying_schedule_id}", headers=headers
        )

    def list_drying_schedules(self, headers, params=None):
        return self._request(
            "GET", "/mill/drying-schedules", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Green receipts
    # ------------------------------------------------------------------
    def create_green_receipt(self, payload, headers):
        return self._request("POST", "/mill/green-receipts", payload, headers)

    def get_green_receipt(self, green_receipt_id, headers):
        return self._request(
            "GET", f"/mill/green-receipts/{green_receipt_id}", headers=headers
        )

    def list_green_receipts(self, headers, params=None):
        return self._request(
            "GET", "/mill/green-receipts", headers=headers, params=params
        )

    def accept_green_receipt(self, green_receipt_id, payload, headers):
        return self._request(
            "POST", f"/mill/green-receipts/{green_receipt_id}/accept", payload, headers
        )

    def reject_green_receipt(self, green_receipt_id, payload, headers):
        return self._request(
            "POST", f"/mill/green-receipts/{green_receipt_id}/reject", payload, headers
        )

    # ------------------------------------------------------------------
    # Kiln chambers
    # ------------------------------------------------------------------
    def create_kiln_chamber(self, payload, headers):
        return self._request("POST", "/mill/kiln-chambers", payload, headers)

    def get_kiln_chamber(self, kiln_chamber_id, headers):
        return self._request(
            "GET", f"/mill/kiln-chambers/{kiln_chamber_id}", headers=headers
        )

    def list_kiln_chambers(self, headers, params=None):
        return self._request(
            "GET", "/mill/kiln-chambers", headers=headers, params=params
        )

    def start_chamber_maintenance(self, kiln_chamber_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/kiln-chambers/{kiln_chamber_id}/start_maintenance",
            payload,
            headers,
        )

    def complete_chamber_maintenance(self, kiln_chamber_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mill/kiln-chambers/{kiln_chamber_id}/complete_maintenance",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Kiln charges
    # ------------------------------------------------------------------
    def create_kiln_charge(self, payload, headers):
        return self._request("POST", "/mill/kiln-charges", payload, headers)

    def get_kiln_charge(self, kiln_charge_id, headers):
        return self._request(
            "GET", f"/mill/kiln-charges/{kiln_charge_id}", headers=headers
        )

    def list_kiln_charges(self, headers, params=None):
        return self._request("GET", "/mill/kiln-charges", headers=headers, params=params)

    def allocate_receipt(self, kiln_charge_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/kiln-charges/{kiln_charge_id}/allocate_receipt",
            payload,
            headers,
        )

    def deallocate_receipt(self, kiln_charge_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/kiln-charges/{kiln_charge_id}/deallocate_receipt",
            payload,
            headers,
        )

    def load_charge(self, kiln_charge_id, headers, payload=None):
        return self._request(
            "POST", f"/mill/kiln-charges/{kiln_charge_id}/load", payload, headers
        )

    def start_drying(self, kiln_charge_id, headers, payload=None):
        return self._request(
            "POST", f"/mill/kiln-charges/{kiln_charge_id}/start_drying", payload, headers
        )

    def begin_conditioning(self, kiln_charge_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mill/kiln-charges/{kiln_charge_id}/begin_conditioning",
            payload,
            headers,
        )

    def record_stress_test(self, kiln_charge_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/kiln-charges/{kiln_charge_id}/record_stress_test",
            payload,
            headers,
        )

    def resume_conditioning(self, kiln_charge_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mill/kiln-charges/{kiln_charge_id}/resume_conditioning",
            payload,
            headers,
        )

    def reschedule_charge(self, kiln_charge_id, payload, headers):
        return self._request(
            "POST", f"/mill/kiln-charges/{kiln_charge_id}/reschedule", payload, headers
        )

    # ------------------------------------------------------------------
    # Product lines
    # ------------------------------------------------------------------
    def create_product_line(self, payload, headers):
        return self._request("POST", "/mill/product-lines", payload, headers)

    def get_product_line(self, product_line_id, headers):
        return self._request(
            "GET", f"/mill/product-lines/{product_line_id}", headers=headers
        )

    def list_product_lines(self, headers, params=None):
        return self._request(
            "GET", "/mill/product-lines", headers=headers, params=params
        )

    def fund_warranty(self, product_line_id, payload, headers):
        return self._request(
            "POST", f"/mill/product-lines/{product_line_id}/fund_warranty", payload, headers
        )

    def freeze_product_line(self, product_line_id, payload, headers):
        return self._request(
            "POST", f"/mill/product-lines/{product_line_id}/freeze", payload, headers
        )

    def unfreeze_product_line(self, product_line_id, headers, payload=None):
        return self._request(
            "POST", f"/mill/product-lines/{product_line_id}/unfreeze", payload, headers
        )

    # ------------------------------------------------------------------
    # Core stock
    # ------------------------------------------------------------------
    def create_core_stock(self, payload, headers):
        return self._request("POST", "/mill/core-stocks", payload, headers)

    def get_core_stock(self, core_stock_id, headers):
        return self._request(
            "GET", f"/mill/core-stocks/{core_stock_id}", headers=headers
        )

    def list_core_stocks(self, headers, params=None):
        return self._request("GET", "/mill/core-stocks", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Flooring lots
    # ------------------------------------------------------------------
    def create_flooring_lot(self, payload, headers):
        return self._request("POST", "/mill/flooring-lots", payload, headers)

    def get_flooring_lot(self, flooring_lot_id, headers):
        return self._request(
            "GET", f"/mill/flooring-lots/{flooring_lot_id}", headers=headers
        )

    def list_flooring_lots(self, headers, params=None):
        return self._request(
            "GET", "/mill/flooring-lots", headers=headers, params=params
        )

    def complete_milling(self, flooring_lot_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/flooring-lots/{flooring_lot_id}/complete_milling",
            payload,
            headers,
        )

    def finalize_flooring_lot(self, flooring_lot_id, payload, headers):
        return self._request(
            "POST", f"/mill/flooring-lots/{flooring_lot_id}/finalize", payload, headers
        )

    def void_flooring_lot(self, flooring_lot_id, payload, headers):
        return self._request(
            "POST", f"/mill/flooring-lots/{flooring_lot_id}/void", payload, headers
        )

    def get_yield_summary(self, flooring_lot_id, headers):
        return self._request(
            "GET", f"/mill/flooring-lots/{flooring_lot_id}/yield-summary", headers=headers
        )

    # ------------------------------------------------------------------
    # Grade runs and bundles
    # ------------------------------------------------------------------
    def create_grade_run(self, payload, headers):
        return self._request("POST", "/mill/grade-runs", payload, headers)

    def get_grade_run(self, grade_run_id, headers):
        return self._request("GET", f"/mill/grade-runs/{grade_run_id}", headers=headers)

    def list_grade_runs(self, headers, params=None):
        return self._request("GET", "/mill/grade-runs", headers=headers, params=params)

    def create_grade_bundle(self, grade_run_id, payload, headers):
        return self._request(
            "POST", f"/mill/grade-runs/{grade_run_id}/bundles", payload, headers
        )

    def list_grade_run_bundles(self, grade_run_id, headers, params=None):
        return self._request(
            "GET", f"/mill/grade-runs/{grade_run_id}/bundles", headers=headers, params=params
        )

    def get_grade_bundle(self, grade_bundle_id, headers):
        return self._request(
            "GET", f"/mill/grade-bundles/{grade_bundle_id}", headers=headers
        )

    def list_grade_bundles(self, headers, params=None):
        return self._request(
            "GET", "/mill/grade-bundles", headers=headers, params=params
        )

    def finalize_grade_run(self, grade_run_id, headers, payload=None):
        return self._request(
            "POST", f"/mill/grade-runs/{grade_run_id}/finalize", payload, headers
        )

    def supersede_grade_run(self, grade_run_id, payload, headers):
        return self._request(
            "POST", f"/mill/grade-runs/{grade_run_id}/supersede", payload, headers
        )

    # ------------------------------------------------------------------
    # Prefinish lines and runs
    # ------------------------------------------------------------------
    def create_prefinish_line(self, payload, headers):
        return self._request("POST", "/mill/prefinish-lines", payload, headers)

    def get_prefinish_line(self, prefinish_line_id, headers):
        return self._request(
            "GET", f"/mill/prefinish-lines/{prefinish_line_id}", headers=headers
        )

    def list_prefinish_lines(self, headers, params=None):
        return self._request(
            "GET", "/mill/prefinish-lines", headers=headers, params=params
        )

    def create_prefinish_run(self, payload, headers):
        return self._request("POST", "/mill/prefinish-runs", payload, headers)

    def get_prefinish_run(self, prefinish_run_id, headers):
        return self._request(
            "GET", f"/mill/prefinish-runs/{prefinish_run_id}", headers=headers
        )

    def list_prefinish_runs(self, headers, params=None):
        return self._request(
            "GET", "/mill/prefinish-runs", headers=headers, params=params
        )

    def release_prefinish_hold(self, prefinish_run_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mill/prefinish-runs/{prefinish_run_id}/release_hold",
            payload,
            headers,
        )

    def start_prefinish_run(self, prefinish_run_id, headers, payload=None):
        return self._request(
            "POST", f"/mill/prefinish-runs/{prefinish_run_id}/start", payload, headers
        )

    def complete_prefinish_run(self, prefinish_run_id, headers, payload=None):
        return self._request(
            "POST", f"/mill/prefinish-runs/{prefinish_run_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Byproduct batches and sales
    # ------------------------------------------------------------------
    def get_byproduct_batch(self, byproduct_batch_id, headers):
        return self._request(
            "GET", f"/mill/byproduct-batches/{byproduct_batch_id}", headers=headers
        )

    def list_byproduct_batches(self, headers, params=None):
        return self._request(
            "GET", "/mill/byproduct-batches", headers=headers, params=params
        )

    def create_byproduct_sale(self, payload, headers):
        return self._request("POST", "/mill/byproduct-sales", payload, headers)

    def get_byproduct_sale(self, byproduct_sale_id, headers):
        return self._request(
            "GET", f"/mill/byproduct-sales/{byproduct_sale_id}", headers=headers
        )

    def list_byproduct_sales(self, headers, params=None):
        return self._request(
            "GET", "/mill/byproduct-sales", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/mill/warranty-claims", payload, headers)

    def get_warranty_claim(self, warranty_claim_id, headers):
        return self._request(
            "GET", f"/mill/warranty-claims/{warranty_claim_id}", headers=headers
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", "/mill/warranty-claims", headers=headers, params=params
        )

    def request_claim_info(self, warranty_claim_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/warranty-claims/{warranty_claim_id}/request_info",
            payload,
            headers,
        )

    def resubmit_claim(self, warranty_claim_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/warranty-claims/{warranty_claim_id}/resubmit",
            payload,
            headers,
        )

    def adjudicate_claim(self, warranty_claim_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/warranty-claims/{warranty_claim_id}/adjudicate",
            payload,
            headers,
        )

    def reverse_claim(self, warranty_claim_id, payload, headers):
        return self._request(
            "POST",
            f"/mill/warranty-claims/{warranty_claim_id}/reverse",
            payload,
            headers,
        )

    def start_remediation(self, warranty_claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mill/warranty-claims/{warranty_claim_id}/start_remediation",
            payload,
            headers,
        )

    def complete_remediation(self, warranty_claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mill/warranty-claims/{warranty_claim_id}/complete_remediation",
            payload,
            headers,
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
