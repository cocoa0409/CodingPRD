"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/comics"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Comics Direct Market Publishing API."""

    # ─── Logical clock ────────────────────────────────

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Creators ─────────────────────────────────────

    def create_creator(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/creators", payload, headers)

    def list_creators(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/creators", headers=headers, params=params)

    def get_creator(self, creator_id, headers):
        return self._request("GET", f"{API_PREFIX}/creators/{creator_id}", headers=headers)

    def list_creator_assignments(self, creator_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/creators/{creator_id}/creative-assignments",
            headers=headers,
            params=params,
        )

    # ─── Titles ───────────────────────────────────────

    def create_title(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/titles", payload, headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/titles", headers=headers, params=params)

    def get_title(self, title_id, headers):
        return self._request("GET", f"{API_PREFIX}/titles/{title_id}", headers=headers)

    def greenlight_title(self, title_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/titles/{title_id}/greenlight", headers=headers
        )

    def cancel_title(self, title_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/titles/{title_id}/cancel", payload, headers
        )

    def create_creative_assignment(self, title_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/titles/{title_id}/creative-assignments", payload, headers
        )

    def list_title_assignments(self, title_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/titles/{title_id}/creative-assignments",
            headers=headers,
            params=params,
        )

    def create_issue(self, title_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/titles/{title_id}/issues", payload, headers
        )

    def list_title_issues(self, title_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/titles/{title_id}/issues", headers=headers, params=params
        )

    # ─── Creative assignments ─────────────────────────

    def get_creative_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/creative-assignments/{assignment_id}", headers=headers
        )

    def counter_creative_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/creative-assignments/{assignment_id}/counter",
            payload,
            headers,
        )

    def repropose_creative_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/creative-assignments/{assignment_id}/repropose",
            payload,
            headers,
        )

    def accept_creative_assignment(self, assignment_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/creative-assignments/{assignment_id}/accept",
            headers=headers,
        )

    def terminate_creative_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/creative-assignments/{assignment_id}/terminate",
            payload,
            headers,
        )

    def list_assignment_stages(self, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/creative-assignments/{assignment_id}/production-stages",
            headers=headers,
            params=params,
        )

    # ─── Issues ───────────────────────────────────────

    def get_issue(self, issue_id, headers):
        return self._request("GET", f"{API_PREFIX}/issues/{issue_id}", headers=headers)

    def create_production_stage(self, issue_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/issues/{issue_id}/production-stages", payload, headers
        )

    def list_issue_stages(self, issue_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/issues/{issue_id}/production-stages",
            headers=headers,
            params=params,
        )

    def create_variant_cover(self, issue_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/issues/{issue_id}/variant-covers", payload, headers
        )

    def list_variant_covers(self, issue_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/issues/{issue_id}/variant-covers",
            headers=headers,
            params=params,
        )

    def foc_lock_issue(self, issue_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/issues/{issue_id}/foc-lock", headers=headers
        )

    def release_issue(self, issue_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/issues/{issue_id}/release", headers=headers
        )

    def create_print_run(self, issue_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/issues/{issue_id}/print-runs", payload, headers
        )

    def list_print_runs(self, issue_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/issues/{issue_id}/print-runs", headers=headers, params=params
        )

    def create_release_window(self, issue_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/issues/{issue_id}/release-windows", payload, headers
        )

    def list_release_windows(self, issue_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/issues/{issue_id}/release-windows",
            headers=headers,
            params=params,
        )

    def list_issue_revenue_events(self, issue_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/issues/{issue_id}/revenue-events",
            headers=headers,
            params=params,
        )

    def list_issue_solicitations(self, issue_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/issues/{issue_id}/solicitations",
            headers=headers,
            params=params,
        )

    # ─── Production stages ────────────────────────────

    def get_production_stage(self, stage_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/production-stages/{stage_id}", headers=headers
        )

    def start_production_stage(self, stage_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/production-stages/{stage_id}/start", headers=headers
        )

    def deliver_production_stage(self, stage_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/production-stages/{stage_id}/deliver", payload, headers
        )

    def kick_back_production_stage(self, stage_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/production-stages/{stage_id}/kick-back", payload, headers
        )

    def approve_production_stage(self, stage_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/production-stages/{stage_id}/approve", headers=headers
        )

    # ─── Catalogs ─────────────────────────────────────

    def create_catalog(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/catalogs", payload, headers)

    def list_catalogs(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/catalogs", headers=headers, params=params)

    def get_catalog(self, catalog_id, headers):
        return self._request("GET", f"{API_PREFIX}/catalogs/{catalog_id}", headers=headers)

    def lock_catalog(self, catalog_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/catalogs/{catalog_id}/lock", headers=headers
        )

    def publish_catalog(self, catalog_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/catalogs/{catalog_id}/publish", headers=headers
        )

    def create_solicitation(self, catalog_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/catalogs/{catalog_id}/solicitations", payload, headers
        )

    def list_catalog_solicitations(self, catalog_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/catalogs/{catalog_id}/solicitations",
            headers=headers,
            params=params,
        )

    # ─── Solicitations ────────────────────────────────

    def get_solicitation(self, solicitation_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/solicitations/{solicitation_id}", headers=headers
        )

    def submit_solicitation(self, solicitation_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/solicitations/{solicitation_id}/submit", headers=headers
        )

    def accept_solicitation(self, solicitation_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/solicitations/{solicitation_id}/accept", headers=headers
        )

    def withdraw_solicitation(self, solicitation_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/solicitations/{solicitation_id}/withdraw",
            payload,
            headers,
        )

    # ─── Retailers ────────────────────────────────────

    def create_retailer(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/retailers", payload, headers)

    def list_retailers(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/retailers", headers=headers, params=params)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"{API_PREFIX}/retailers/{retailer_id}", headers=headers)

    def suspend_retailer(self, retailer_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retailers/{retailer_id}/suspend", payload, headers
        )

    def reinstate_retailer(self, retailer_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retailers/{retailer_id}/reinstate", headers=headers
        )

    # ─── Retailer orders ──────────────────────────────

    def create_retailer_order(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/retailer-orders", payload, headers)

    def list_retailer_orders(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/retailer-orders", headers=headers, params=params
        )

    def get_retailer_order(self, order_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/retailer-orders/{order_id}", headers=headers
        )

    def submit_retailer_order(self, order_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retailer-orders/{order_id}/submit", headers=headers
        )

    def adjust_retailer_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retailer-orders/{order_id}/adjust", payload, headers
        )

    def invoice_retailer_order(self, order_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retailer-orders/{order_id}/invoice", headers=headers
        )

    def ship_retailer_order(self, order_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retailer-orders/{order_id}/ship", headers=headers
        )

    def cancel_retailer_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retailer-orders/{order_id}/cancel", payload, headers
        )

    # ─── Print runs ───────────────────────────────────

    def get_print_run(self, print_run_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/print-runs/{print_run_id}", headers=headers
        )

    def complete_print_run(self, print_run_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/print-runs/{print_run_id}/complete", headers=headers
        )

    def cancel_print_run(self, print_run_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/print-runs/{print_run_id}/cancel", payload, headers
        )

    # ─── Revenue events ───────────────────────────────

    def create_revenue_event(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/revenue-events", payload, headers)

    # ─── Royalty statements ───────────────────────────

    def create_royalty_statement(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/royalty-statements", payload, headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/royalty-statements", headers=headers, params=params
        )

    def get_royalty_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/royalty-statements/{statement_id}", headers=headers
        )

    def issue_royalty_statement(self, statement_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/royalty-statements/{statement_id}/issue", headers=headers
        )

    def pay_royalty_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/royalty-statements/{statement_id}/pay", payload, headers
        )

    def reverse_royalty_statement(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/royalty-statements/{statement_id}/reverse",
            payload,
            headers,
        )


api_client = ApiClient()
