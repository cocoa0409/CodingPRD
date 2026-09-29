"""API client: one method per endpoint the PRD declares. All collections are
mounted beneath /otb."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/otb"


class ApiClient(GenericApiClient):
    # ─── Departments ──────────────────────────────────
    def create_department(self, payload, headers):
        return self._request("POST", f"{PREFIX}/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"{PREFIX}/departments/{department_id}", headers=headers)

    # ─── Categories ───────────────────────────────────
    def create_category(self, payload, headers):
        return self._request("POST", f"{PREFIX}/categories", payload, headers)

    def get_category(self, category_id, headers):
        return self._request("GET", f"{PREFIX}/categories/{category_id}", headers=headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/categories", headers=headers, params=params)

    # ─── Store clusters ───────────────────────────────
    def create_store_cluster(self, payload, headers):
        return self._request("POST", f"{PREFIX}/store-clusters", payload, headers)

    def get_store_cluster(self, cluster_id, headers):
        return self._request("GET", f"{PREFIX}/store-clusters/{cluster_id}", headers=headers)

    def list_store_clusters(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/store-clusters", headers=headers, params=params)

    # ─── Vendors ──────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", headers=headers)

    def set_vendor_status(self, vendor_id, payload, headers):
        return self._request("POST", f"{PREFIX}/vendors/{vendor_id}/status", payload, headers)

    # ─── Vendor authorizations ────────────────────────
    def create_vendor_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vendor-authorizations", payload, headers)

    def get_vendor_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"{PREFIX}/vendor-authorizations/{authorization_id}", headers=headers
        )

    def list_vendor_authorizations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/vendor-authorizations", headers=headers, params=params
        )

    # ─── Category plans ───────────────────────────────
    def create_category_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/category-plans", payload, headers)

    def get_category_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/category-plans/{plan_id}", headers=headers)

    def list_category_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/category-plans", headers=headers, params=params)

    def submit_category_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/category-plans/{plan_id}/submit", payload, headers
        )

    def approve_category_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/category-plans/{plan_id}/approve", payload, headers
        )

    def reject_category_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/category-plans/{plan_id}/reject", payload, headers
        )

    def close_category_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/category-plans/{plan_id}/close", payload, headers
        )

    def get_otb_summary(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/category-plans/{plan_id}/otb-summary",
            headers=headers, params=params,
        )

    def open_reforecast_cycle(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/category-plans/{plan_id}/reforecasts", payload, headers
        )

    # ─── Plan months ──────────────────────────────────
    def create_plan_month(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plan-months", payload, headers)

    def get_plan_month(self, month_id, headers):
        return self._request("GET", f"{PREFIX}/plan-months/{month_id}", headers=headers)

    def list_plan_months(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/plan-months", headers=headers, params=params)

    def open_season(self, month_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-months/{month_id}/open-season", payload, headers
        )

    def get_otb_ledger(self, month_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/plan-months/{month_id}/otb-ledger",
            headers=headers, params=params,
        )

    def list_month_actuals_posts(self, month_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/plan-months/{month_id}/actuals-posts",
            headers=headers, params=params,
        )

    # ─── Option plans and size curves ─────────────────
    def create_option_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/option-plans", payload, headers)

    def get_option_plan(self, option_plan_id, headers):
        return self._request("GET", f"{PREFIX}/option-plans/{option_plan_id}", headers=headers)

    def list_option_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/option-plans", headers=headers, params=params)

    def replace_size_curve(self, option_plan_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/option-plans/{option_plan_id}/size-curve", payload, headers
        )

    def list_size_curve_cells(self, option_plan_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/option-plans/{option_plan_id}/size-curve-cells",
            headers=headers, params=params,
        )

    # ─── Assortment items ─────────────────────────────
    def create_assortment_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/assortment-items", payload, headers)

    def get_assortment_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/assortment-items/{item_id}", headers=headers)

    def list_assortment_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/assortment-items", headers=headers, params=params)

    def adopt_assortment_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assortment-items/{item_id}/adopt", payload, headers
        )

    def activate_assortment_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assortment-items/{item_id}/activate", payload, headers
        )

    def close_assortment_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assortment-items/{item_id}/close", payload, headers
        )

    # ─── Receipt commitments ──────────────────────────
    def create_receipt_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/receipt-commitments", payload, headers)

    def get_receipt_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/receipt-commitments/{commitment_id}", headers=headers
        )

    def list_receipt_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/receipt-commitments", headers=headers, params=params
        )

    def commit_receipt_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/receipt-commitments/{commitment_id}/commit", payload, headers
        )

    def cancel_receipt_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/receipt-commitments/{commitment_id}/cancel", payload, headers
        )

    def ship_receipt_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/receipt-commitments/{commitment_id}/ship", payload, headers
        )

    def post_receipt(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/receipt-commitments/{commitment_id}/receipts", payload, headers
        )

    # ─── Weekly actuals ───────────────────────────────
    def create_actuals_post(self, payload, headers):
        return self._request("POST", f"{PREFIX}/actuals-posts", payload, headers)

    # ─── Reforecast cycles ────────────────────────────
    def get_reforecast_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/reforecast-cycles/{cycle_id}", headers=headers)

    def list_reforecast_cycles(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reforecast-cycles", headers=headers, params=params
        )

    def close_reforecast_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reforecast-cycles/{cycle_id}/close", payload, headers
        )

    # ─── Chase / cancel decisions ─────────────────────
    def create_chase_cancel_decision(self, payload, headers):
        return self._request("POST", f"{PREFIX}/chase-cancel-decisions", payload, headers)

    def get_chase_cancel_decision(self, decision_id, headers):
        return self._request(
            "GET", f"{PREFIX}/chase-cancel-decisions/{decision_id}", headers=headers
        )

    def list_chase_cancel_decisions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/chase-cancel-decisions", headers=headers, params=params
        )

    def approve_chase_cancel_decision(self, decision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chase-cancel-decisions/{decision_id}/approve", payload, headers
        )

    def reject_chase_cancel_decision(self, decision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chase-cancel-decisions/{decision_id}/reject", payload, headers
        )

    # ─── Localization overlays ────────────────────────
    def create_localization_overlay(self, payload, headers):
        return self._request("POST", f"{PREFIX}/localization-overlays", payload, headers)

    def get_localization_overlay(self, overlay_id, headers):
        return self._request(
            "GET", f"{PREFIX}/localization-overlays/{overlay_id}", headers=headers
        )

    def list_localization_overlays(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/localization-overlays", headers=headers, params=params
        )

    def activate_localization_overlay(self, overlay_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/localization-overlays/{overlay_id}/activate", payload, headers
        )

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
