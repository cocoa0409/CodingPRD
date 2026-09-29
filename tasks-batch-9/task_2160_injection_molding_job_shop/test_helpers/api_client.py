"""API client: one method per endpoint defined in the PRD.

Every endpoint is mounted at the root of the service; no resource is nested
inside another, so parent references travel in the request body or as a list
filter.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ----------------------------------------------------- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------------------------------------------------- customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ------------------------------------------------------------- press ----
    def create_press(self, payload, headers):
        return self._request("POST", "/presses", payload, headers)

    def get_press(self, press_id, headers):
        return self._request("GET", f"/presses/{press_id}", headers=headers)

    def list_presses(self, headers, params=None):
        return self._request("GET", "/presses", headers=headers, params=params)

    def set_press_status(self, press_id, payload, headers):
        return self._request("POST", f"/presses/{press_id}/status", payload, headers)

    # -------------------------------------------------------------- mold ----
    def create_mold(self, payload, headers):
        return self._request("POST", "/molds", payload, headers)

    def get_mold(self, mold_id, headers):
        return self._request("GET", f"/molds/{mold_id}", headers=headers)

    def list_molds(self, headers, params=None):
        return self._request("GET", "/molds", headers=headers, params=params)

    def mold_quality_hold(self, mold_id, payload, headers):
        return self._request("POST", f"/molds/{mold_id}/quality-hold", payload, headers)

    def retire_mold(self, mold_id, payload, headers):
        return self._request("POST", f"/molds/{mold_id}/retire", payload, headers)

    # ------------------------------------------------- press qualification --
    def create_press_qualification(self, payload, headers):
        return self._request("POST", "/press-qualifications", payload, headers)

    def get_press_qualification(self, qualification_id, headers):
        return self._request(
            "GET", f"/press-qualifications/{qualification_id}", headers=headers
        )

    def list_press_qualifications(self, headers, params=None):
        return self._request(
            "GET", "/press-qualifications", headers=headers, params=params
        )

    def schedule_run_at_rate(self, qualification_id, payload, headers):
        return self._request(
            "POST",
            f"/press-qualifications/{qualification_id}/schedule-run-at-rate",
            payload,
            headers,
        )

    def record_run_at_rate(self, qualification_id, payload, headers):
        return self._request(
            "POST",
            f"/press-qualifications/{qualification_id}/record-run-at-rate",
            payload,
            headers,
        )

    # ------------------------------------------------------------- quote ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def price_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/price", payload, headers)

    def submit_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/submit", {}, headers)

    def quote_customer_decision(self, quote_id, payload, headers):
        return self._request(
            "POST", f"/quotes/{quote_id}/customer-decision", payload, headers
        )

    # --------------------------------------------------- PPAP submission ----
    def create_ppap_submission(self, payload, headers):
        return self._request("POST", "/ppap-submissions", payload, headers)

    def get_ppap_submission(self, submission_id, headers):
        return self._request(
            "GET", f"/ppap-submissions/{submission_id}", headers=headers
        )

    def list_ppap_submissions(self, headers, params=None):
        return self._request(
            "GET", "/ppap-submissions", headers=headers, params=params
        )

    def submit_ppap(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/ppap-submissions/{submission_id}/submit", payload, headers
        )

    def ppap_internal_review(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/ppap-submissions/{submission_id}/internal-review",
            payload,
            headers,
        )

    def ppap_customer_decision(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/ppap-submissions/{submission_id}/customer-decision",
            payload,
            headers,
        )

    def revise_ppap(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/ppap-submissions/{submission_id}/revise", payload, headers
        )

    # ---------------------------------------------------------- resin lot ----
    def create_resin_lot(self, payload, headers):
        return self._request("POST", "/resin-lots", payload, headers)

    def get_resin_lot(self, lot_id, headers):
        return self._request("GET", f"/resin-lots/{lot_id}", headers=headers)

    def resin_lot_disposition(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/resin-lots/{lot_id}/disposition", payload, headers
        )

    # ----------------------------------------------------- production job ----
    def create_production_job(self, payload, headers):
        return self._request("POST", "/production-jobs", payload, headers)

    def get_production_job(self, job_id, headers):
        return self._request("GET", f"/production-jobs/{job_id}", headers=headers)

    def list_production_jobs(self, headers, params=None):
        return self._request("GET", "/production-jobs", headers=headers, params=params)

    def schedule_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/schedule", payload, headers
        )

    def stage_material(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/stage-material", payload, headers
        )

    def start_job(self, job_id, headers):
        return self._request("POST", f"/production-jobs/{job_id}/start", {}, headers)

    def complete_job(self, job_id, headers):
        return self._request("POST", f"/production-jobs/{job_id}/complete", {}, headers)

    def cancel_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/cancel", payload, headers
        )

    def unblock_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/unblock", payload, headers
        )

    # -------------------------------------------------- production report ----
    def create_production_report(self, payload, headers):
        return self._request("POST", "/production-reports", payload, headers)

    def get_production_report(self, report_id, headers):
        return self._request("GET", f"/production-reports/{report_id}", headers=headers)

    def list_production_reports(self, headers, params=None):
        return self._request(
            "GET", "/production-reports", headers=headers, params=params
        )

    def reverse_production_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/production-reports/{report_id}/reverse", payload, headers
        )

    # -------------------------------------------------- maintenance order ----
    def create_maintenance_order(self, payload, headers):
        return self._request("POST", "/maintenance-orders", payload, headers)

    def get_maintenance_order(self, order_id, headers):
        return self._request("GET", f"/maintenance-orders/{order_id}", headers=headers)

    def list_maintenance_orders(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-orders", headers=headers, params=params
        )

    def close_maintenance_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-orders/{order_id}/close", payload, headers
        )

    # ------------------------------------------------------- tool transfer ---
    def create_tool_transfer(self, payload, headers):
        return self._request("POST", "/tool-transfers", payload, headers)

    def get_tool_transfer(self, transfer_id, headers):
        return self._request("GET", f"/tool-transfers/{transfer_id}", headers=headers)

    def list_tool_transfers(self, headers, params=None):
        return self._request("GET", "/tool-transfers", headers=headers, params=params)

    def tool_transfer_decision(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/tool-transfers/{transfer_id}/decision", payload, headers
        )

    def complete_tool_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/tool-transfers/{transfer_id}/complete", payload, headers
        )

    # ----------------------------------------------------- capacity commit ---
    def create_capacity_commit(self, payload, headers):
        return self._request("POST", "/capacity-commits", payload, headers)

    def get_capacity_commit(self, commit_id, headers):
        return self._request("GET", f"/capacity-commits/{commit_id}", headers=headers)

    def list_capacity_commits(self, headers, params=None):
        return self._request("GET", "/capacity-commits", headers=headers, params=params)

    def settle_capacity_commit(self, commit_id, headers):
        return self._request("POST", f"/capacity-commits/{commit_id}/settle", {}, headers)

    def cancel_capacity_commit(self, commit_id, payload, headers):
        return self._request(
            "POST", f"/capacity-commits/{commit_id}/cancel", payload, headers
        )


api_client = ApiClient()
