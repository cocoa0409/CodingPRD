"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- briefs
    def create_brief(self, payload, headers):
        return self._request("POST", "/briefs", payload, headers)

    def get_brief(self, brief_id, headers):
        return self._request("GET", f"/briefs/{brief_id}", headers=headers)

    def list_briefs(self, headers, params=None):
        return self._request("GET", "/briefs", headers=headers, params=params)

    def patch_brief(self, brief_id, payload, headers):
        return self._request("PATCH", f"/briefs/{brief_id}", payload, headers)

    def decide_brief(self, brief_id, payload, headers):
        return self._request("POST", f"/briefs/{brief_id}/decision", payload, headers)

    # ----------------------------------------------------- marketing claims
    def create_marketing_claim(self, payload, headers):
        return self._request("POST", "/marketing-claims", payload, headers)

    def get_marketing_claim(self, claim_id, headers):
        return self._request("GET", f"/marketing-claims/{claim_id}", headers=headers)

    def list_marketing_claims(self, headers, params=None):
        return self._request("GET", "/marketing-claims", headers=headers, params=params)

    def decide_claim_clearance(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/marketing-claims/{claim_id}/clearance", payload, headers
        )

    # -------------------------------------------------------- artwork assets
    def create_artwork_asset(self, payload, headers):
        return self._request("POST", "/artwork-assets", payload, headers)

    def get_artwork_asset(self, asset_id, headers):
        return self._request("GET", f"/artwork-assets/{asset_id}", headers=headers)

    def list_artwork_assets(self, headers, params=None):
        return self._request("GET", "/artwork-assets", headers=headers, params=params)

    def create_artwork_version(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/artwork-assets/{asset_id}/versions", payload, headers
        )

    # ------------------------------------------------------ artwork versions
    def get_artwork_version(self, version_id, headers):
        return self._request("GET", f"/artwork-versions/{version_id}", headers=headers)

    def list_artwork_versions(self, headers, params=None):
        return self._request("GET", "/artwork-versions", headers=headers, params=params)

    def patch_artwork_version(self, version_id, payload, headers):
        return self._request(
            "PATCH", f"/artwork-versions/{version_id}", payload, headers
        )

    def verify_elements(self, version_id, payload, headers):
        return self._request(
            "POST", f"/artwork-versions/{version_id}/verify-elements", payload, headers
        )

    def revise_artwork_version(self, version_id, payload, headers):
        return self._request(
            "POST", f"/artwork-versions/{version_id}/revise", payload, headers
        )

    def submit_artwork_version(self, version_id, payload, headers):
        return self._request(
            "POST", f"/artwork-versions/{version_id}/submit", payload, headers
        )

    def release_to_print(self, version_id, payload, headers):
        return self._request(
            "POST", f"/artwork-versions/{version_id}/release-to-print", payload, headers
        )

    # -------------------------------------------------------- element checks
    def get_element_check(self, check_id, headers):
        return self._request("GET", f"/element-checks/{check_id}", headers=headers)

    def list_element_checks(self, headers, params=None):
        return self._request("GET", "/element-checks", headers=headers, params=params)

    def waive_element_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/element-checks/{check_id}/waiver", payload, headers
        )

    # --------------------------------------------------------- review routes
    def get_review_route(self, route_id, headers):
        return self._request("GET", f"/review-routes/{route_id}", headers=headers)

    def list_review_routes(self, headers, params=None):
        return self._request("GET", "/review-routes", headers=headers, params=params)

    # ---------------------------------------------------------- review tasks
    def get_review_task(self, task_id, headers):
        return self._request("GET", f"/review-tasks/{task_id}", headers=headers)

    def list_review_tasks(self, headers, params=None):
        return self._request("GET", "/review-tasks", headers=headers, params=params)

    def decide_review_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/review-tasks/{task_id}/decision", payload, headers
        )

    # -------------------------------------------------------------- printers
    def create_printer(self, payload, headers):
        return self._request("POST", "/printers", payload, headers)

    def get_printer(self, printer_id, headers):
        return self._request("GET", f"/printers/{printer_id}", headers=headers)

    def list_printers(self, headers, params=None):
        return self._request("GET", "/printers", headers=headers, params=params)

    # -------------------------------------------------------- printer proofs
    def create_printer_proof(self, payload, headers):
        return self._request("POST", "/printer-proofs", payload, headers)

    def get_printer_proof(self, proof_id, headers):
        return self._request("GET", f"/printer-proofs/{proof_id}", headers=headers)

    def list_printer_proofs(self, headers, params=None):
        return self._request("GET", "/printer-proofs", headers=headers, params=params)

    def decide_proof_color(self, proof_id, payload, headers):
        return self._request(
            "POST", f"/printer-proofs/{proof_id}/color-decision", payload, headers
        )

    def decide_proof_substrate(self, proof_id, payload, headers):
        return self._request(
            "POST", f"/printer-proofs/{proof_id}/substrate-decision", payload, headers
        )

    def book_press_check(self, proof_id, payload, headers):
        return self._request(
            "POST", f"/printer-proofs/{proof_id}/press-check", payload, headers
        )

    # ---------------------------------------------------------- plate orders
    def create_plate_order(self, payload, headers):
        return self._request("POST", "/plate-orders", payload, headers)

    def get_plate_order(self, order_id, headers):
        return self._request("GET", f"/plate-orders/{order_id}", headers=headers)

    def list_plate_orders(self, headers, params=None):
        return self._request("GET", "/plate-orders", headers=headers, params=params)

    def cancel_plate_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/plate-orders/{order_id}/cancel", payload, headers
        )

    # ------------------------------------------------------ inventory runouts
    def create_inventory_runout(self, payload, headers):
        return self._request("POST", "/inventory-runouts", payload, headers)

    def get_inventory_runout(self, runout_id, headers):
        return self._request("GET", f"/inventory-runouts/{runout_id}", headers=headers)

    def list_inventory_runouts(self, headers, params=None):
        return self._request(
            "GET", "/inventory-runouts", headers=headers, params=params
        )

    def append_depletion_records(self, runout_id, payload, headers):
        return self._request(
            "POST", f"/inventory-runouts/{runout_id}/depletion-records", payload, headers
        )

    def disposition_runout(self, runout_id, payload, headers):
        return self._request(
            "POST", f"/inventory-runouts/{runout_id}/disposition", payload, headers
        )

    def reverse_runout_disposition(self, runout_id, payload, headers):
        return self._request(
            "POST",
            f"/inventory-runouts/{runout_id}/disposition-reversal",
            payload,
            headers,
        )

    # --------------------------------------------------------- error escapes
    def create_error_escape(self, payload, headers):
        return self._request("POST", "/error-escapes", payload, headers)

    def get_error_escape(self, escape_id, headers):
        return self._request("GET", f"/error-escapes/{escape_id}", headers=headers)

    def list_error_escapes(self, headers, params=None):
        return self._request("GET", "/error-escapes", headers=headers, params=params)

    def assign_root_cause(self, escape_id, payload, headers):
        return self._request(
            "POST", f"/error-escapes/{escape_id}/root-cause", payload, headers
        )

    def raise_recovery_claim(self, escape_id, payload, headers):
        return self._request(
            "POST", f"/error-escapes/{escape_id}/recovery-claim", payload, headers
        )

    def dispute_escape(self, escape_id, payload, headers):
        return self._request(
            "POST", f"/error-escapes/{escape_id}/dispute", payload, headers
        )

    def settle_escape(self, escape_id, payload, headers):
        return self._request(
            "POST", f"/error-escapes/{escape_id}/settle", payload, headers
        )


api_client = ApiClient()
