"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (admin) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # ---- Property owners ----
    def create_property_owner(self, payload, headers):
        return self._request("POST", "/abatement/property-owners", payload, headers=headers)

    def get_property_owner(self, owner_id, headers):
        return self._request(
            "GET", f"/abatement/property-owners/{owner_id}", headers=headers
        )

    # ---- Sites ----
    def create_site(self, payload, headers):
        return self._request("POST", "/abatement/sites", payload, headers=headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/abatement/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/abatement/sites", headers=headers, params=params)

    # ---- Reports ----
    def create_report(self, payload, headers):
        return self._request("POST", "/abatement/reports", payload, headers=headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/abatement/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/abatement/reports", headers=headers, params=params)

    def triage_report(self, report_id, headers):
        return self._request(
            "POST", f"/abatement/reports/{report_id}/triage", {}, headers=headers
        )

    # ---- Crews ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/abatement/crews", payload, headers=headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/abatement/crews/{crew_id}", headers=headers)

    # ---- Work orders ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/abatement/work-orders", payload, headers=headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/abatement/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/abatement/work-orders", headers=headers, params=params)

    def start_work_order(self, wo_id, headers):
        return self._request(
            "POST", f"/abatement/work-orders/{wo_id}/start", {}, headers=headers
        )

    def complete_work_order(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/abatement/work-orders/{wo_id}/complete", payload, headers=headers
        )

    def cancel_work_order(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/abatement/work-orders/{wo_id}/cancel", payload, headers=headers
        )

    def recall_work_order(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/abatement/work-orders/{wo_id}/recall", payload, headers=headers
        )

    def upload_photo(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/abatement/work-orders/{wo_id}/photos", payload, headers=headers
        )

    def list_photos(self, wo_id, headers):
        return self._request(
            "GET", f"/abatement/work-orders/{wo_id}/photos", headers=headers
        )

    def list_removal_logs(self, wo_id, headers):
        return self._request(
            "GET", f"/abatement/work-orders/{wo_id}/removal-logs", headers=headers
        )

    def list_work_order_reservations(self, wo_id, headers):
        return self._request(
            "GET", f"/abatement/work-orders/{wo_id}/material-reservations", headers=headers
        )

    # ---- Materials ----
    def create_material(self, payload, headers):
        return self._request("POST", "/abatement/materials", payload, headers=headers)

    def get_material(self, material_id, headers):
        return self._request("GET", f"/abatement/materials/{material_id}", headers=headers)

    def list_material_reservations(self, material_id, headers):
        return self._request(
            "GET", f"/abatement/materials/{material_id}/material-reservations", headers=headers
        )

    # ---- Notices ----
    def issue_notice(self, site_id, payload, headers):
        return self._request(
            "POST", f"/abatement/sites/{site_id}/notices", payload, headers=headers
        )

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/abatement/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/abatement/notices", headers=headers, params=params)

    def consent_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/abatement/notices/{notice_id}/consent", {}, headers=headers
        )

    def dispute_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/abatement/notices/{notice_id}/dispute", payload, headers=headers
        )

    def expire_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/abatement/notices/{notice_id}/expire", {}, headers=headers
        )

    # ---- Cost recoveries ----
    def get_cost_recovery(self, cr_id, headers):
        return self._request("GET", f"/abatement/cost-recoveries/{cr_id}", headers=headers)

    def list_cost_recoveries(self, headers, params=None):
        return self._request(
            "GET", "/abatement/cost-recoveries", headers=headers, params=params
        )

    def pay_cost_recovery(self, cr_id, headers):
        return self._request(
            "POST", f"/abatement/cost-recoveries/{cr_id}/pay", {}, headers=headers
        )

    def waive_cost_recovery(self, cr_id, payload, headers):
        return self._request(
            "POST", f"/abatement/cost-recoveries/{cr_id}/waive", payload, headers=headers
        )


api_client = ApiClient()
