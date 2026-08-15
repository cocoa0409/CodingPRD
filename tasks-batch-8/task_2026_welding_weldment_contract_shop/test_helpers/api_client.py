"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/weld-shop/_clock/set_current_utc",
                             payload, headers)

    # ------------------------------------------------------------------
    # Shops
    # ------------------------------------------------------------------
    def create_shop(self, payload, headers):
        return self._request("POST", "/weld-shop/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/weld-shop/shops/{shop_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Welders
    # ------------------------------------------------------------------
    def create_welder(self, shop_id, payload, headers):
        return self._request("POST", f"/weld-shop/shops/{shop_id}/welders",
                             payload, headers)

    def list_welders(self, shop_id, headers, params=None):
        return self._request("GET", f"/weld-shop/shops/{shop_id}/welders",
                             headers=headers, params=params)

    def get_welder(self, shop_id, welder_id, headers):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/welders/{welder_id}",
            headers=headers)

    def get_welder_flat(self, welder_id, headers):
        return self._request("GET", f"/weld-shop/welders/{welder_id}",
                             headers=headers)

    def list_welders_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/welders", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # NDT vendors
    # ------------------------------------------------------------------
    def create_ndt_vendor(self, shop_id, payload, headers):
        return self._request("POST", f"/weld-shop/shops/{shop_id}/ndt-vendors",
                             payload, headers)

    def list_ndt_vendors(self, shop_id, headers, params=None):
        return self._request("GET", f"/weld-shop/shops/{shop_id}/ndt-vendors",
                             headers=headers, params=params)

    def get_ndt_vendor_flat(self, vendor_id, headers):
        return self._request("GET", f"/weld-shop/ndt-vendors/{vendor_id}",
                             headers=headers)

    def list_ndt_vendors_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/ndt-vendors", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Ovens
    # ------------------------------------------------------------------
    def create_oven(self, shop_id, payload, headers):
        return self._request("POST", f"/weld-shop/shops/{shop_id}/ovens",
                             payload, headers)

    def list_ovens(self, shop_id, headers, params=None):
        return self._request("GET", f"/weld-shop/shops/{shop_id}/ovens",
                             headers=headers, params=params)

    def take_oven_offline(self, shop_id, oven_id, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/ovens/{oven_id}/take-offline",
            {}, headers)

    def bring_oven_online(self, shop_id, oven_id, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/ovens/{oven_id}/bring-online",
            {}, headers)

    def get_oven_flat(self, oven_id, headers):
        return self._request("GET", f"/weld-shop/ovens/{oven_id}",
                             headers=headers)

    def list_ovens_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/ovens", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # PQRs
    # ------------------------------------------------------------------
    def create_pqr(self, shop_id, payload, headers):
        return self._request("POST", f"/weld-shop/shops/{shop_id}/pqrs",
                             payload, headers)

    def list_pqrs(self, shop_id, headers, params=None):
        return self._request("GET", f"/weld-shop/shops/{shop_id}/pqrs",
                             headers=headers, params=params)

    def get_pqr(self, shop_id, pqr_id, headers):
        return self._request("GET",
                             f"/weld-shop/shops/{shop_id}/pqrs/{pqr_id}",
                             headers=headers)

    def approve_pqr(self, shop_id, pqr_id, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/pqrs/{pqr_id}/approve",
            {}, headers)

    def reject_pqr(self, shop_id, pqr_id, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/pqrs/{pqr_id}/reject",
            {}, headers)

    def get_pqr_flat(self, pqr_id, headers):
        return self._request("GET", f"/weld-shop/pqrs/{pqr_id}",
                             headers=headers)

    def list_pqrs_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/pqrs", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # WPS revisions
    # ------------------------------------------------------------------
    def create_wps(self, shop_id, payload, headers):
        return self._request("POST", f"/weld-shop/shops/{shop_id}/wps",
                             payload, headers)

    def list_wps(self, shop_id, headers, params=None):
        return self._request("GET", f"/weld-shop/shops/{shop_id}/wps",
                             headers=headers, params=params)

    def get_wps(self, shop_id, wps_id, headers):
        return self._request("GET",
                             f"/weld-shop/shops/{shop_id}/wps/{wps_id}",
                             headers=headers)

    def approve_wps(self, shop_id, wps_id, payload, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/wps/{wps_id}/approve",
            payload, headers)

    def reject_wps(self, shop_id, wps_id, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/wps/{wps_id}/reject",
            {}, headers)

    def get_wps_flat(self, wps_id, headers):
        return self._request("GET", f"/weld-shop/wps/{wps_id}",
                             headers=headers)

    def list_wps_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/wps", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Welder qualifications
    # ------------------------------------------------------------------
    def create_qualification(self, shop_id, payload, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/welder-qualifications",
            payload, headers)

    def list_qualifications(self, shop_id, headers, params=None):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/welder-qualifications",
            headers=headers, params=params)

    def get_qualification(self, shop_id, qual_id, headers):
        return self._request(
            "GET",
            f"/weld-shop/shops/{shop_id}/welder-qualifications/{qual_id}",
            headers=headers)

    def requalify_qualification(self, shop_id, qual_id, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/welder-qualifications/{qual_id}/requalify",
            {}, headers)

    def revoke_qualification(self, shop_id, qual_id, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/welder-qualifications/{qual_id}/revoke",
            {}, headers)

    def get_qualification_flat(self, qual_id, headers):
        return self._request(
            "GET", f"/weld-shop/welder-qualifications/{qual_id}",
            headers=headers)

    def list_qualifications_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/welder-qualifications",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Consumable lots
    # ------------------------------------------------------------------
    def create_consumable_lot(self, shop_id, payload, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/consumable-lots",
            payload, headers)

    def list_consumable_lots(self, shop_id, headers, params=None):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/consumable-lots",
            headers=headers, params=params)

    def get_consumable_lot(self, shop_id, lot_id, headers):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/consumable-lots/{lot_id}",
            headers=headers)

    def rebake_lot(self, shop_id, lot_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/consumable-lots/{lot_id}/rebake",
            payload, headers)

    def get_consumable_lot_flat(self, lot_id, headers):
        return self._request("GET", f"/weld-shop/consumable-lots/{lot_id}",
                             headers=headers)

    def list_consumable_lots_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/consumable-lots",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Consumable issues
    # ------------------------------------------------------------------
    def create_consumable_issue(self, shop_id, payload, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/consumable-issues",
            payload, headers)

    def list_consumable_issues(self, shop_id, headers, params=None):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/consumable-issues",
            headers=headers, params=params)

    def return_consumable_issue(self, shop_id, issue_id, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/consumable-issues/{issue_id}/return",
            {}, headers)

    def get_consumable_issue_flat(self, issue_id, headers):
        return self._request("GET", f"/weld-shop/consumable-issues/{issue_id}",
                             headers=headers)

    def list_consumable_issues_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/consumable-issues",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------
    def create_fixture(self, shop_id, payload, headers):
        return self._request("POST", f"/weld-shop/shops/{shop_id}/fixtures",
                             payload, headers)

    def list_fixtures(self, shop_id, headers, params=None):
        return self._request("GET", f"/weld-shop/shops/{shop_id}/fixtures",
                             headers=headers, params=params)

    def reserve_fixture(self, shop_id, fixture_id, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/fixtures/{fixture_id}/reserve",
            {}, headers)

    def release_fixture(self, shop_id, fixture_id, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/fixtures/{fixture_id}/release",
            {}, headers)

    def send_fixture_for_repair(self, shop_id, fixture_id, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/fixtures/{fixture_id}/send-for-repair",
            {}, headers)

    def get_fixture_flat(self, fixture_id, headers):
        return self._request("GET", f"/weld-shop/fixtures/{fixture_id}",
                             headers=headers)

    def list_fixtures_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/fixtures", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Shop orders
    # ------------------------------------------------------------------
    def create_shop_order(self, shop_id, payload, headers):
        return self._request("POST", f"/weld-shop/shops/{shop_id}/shop-orders",
                             payload, headers)

    def list_shop_orders(self, shop_id, headers, params=None):
        return self._request("GET", f"/weld-shop/shops/{shop_id}/shop-orders",
                             headers=headers, params=params)

    def get_shop_order(self, shop_id, order_id, headers):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/shop-orders/{order_id}",
            headers=headers)

    def get_shop_order_flat(self, order_id, headers):
        return self._request("GET", f"/weld-shop/shop-orders/{order_id}",
                             headers=headers)

    def list_shop_orders_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/shop-orders", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Weldments
    # ------------------------------------------------------------------
    def create_weldment(self, shop_id, order_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/shop-orders/{order_id}/weldments",
            payload, headers)

    def list_weldments_under_order(self, shop_id, order_id, headers,
                                   params=None):
        return self._request(
            "GET",
            f"/weld-shop/shops/{shop_id}/shop-orders/{order_id}/weldments",
            headers=headers, params=params)

    def get_weldment(self, shop_id, weldment_id, headers):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}",
            headers=headers)

    def ship_weldment(self, shop_id, weldment_id, payload, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/ship",
            payload, headers)

    def cancel_weldment(self, shop_id, weldment_id, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/cancel",
            {}, headers)

    def clear_repair_review(self, shop_id, weldment_id, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/clear-repair-review",
            {}, headers)

    def unfreeze_weldment(self, shop_id, weldment_id, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/unfreeze",
            {}, headers)

    def get_weldment_flat(self, weldment_id, headers):
        return self._request("GET", f"/weld-shop/weldments/{weldment_id}",
                             headers=headers)

    def list_weldments_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/weldments", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Joints
    # ------------------------------------------------------------------
    def create_joint(self, shop_id, weldment_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/joints",
            payload, headers)

    def list_joints(self, shop_id, weldment_id, headers, params=None):
        return self._request(
            "GET",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/joints",
            headers=headers, params=params)

    def get_joint(self, shop_id, joint_id, headers):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/joints/{joint_id}",
            headers=headers)

    def start_fabrication(self, shop_id, joint_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/joints/{joint_id}/start-fabrication",
            payload, headers)

    def weld_out(self, shop_id, joint_id, headers):
        return self._request(
            "POST", f"/weld-shop/shops/{shop_id}/joints/{joint_id}/weld-out",
            {}, headers)

    def declare_repair(self, shop_id, joint_id, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/joints/{joint_id}/declare-repair",
            {}, headers)

    def rebind_wps(self, shop_id, joint_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/joints/{joint_id}/rebind-wps",
            payload, headers)

    def get_joint_flat(self, joint_id, headers):
        return self._request("GET", f"/weld-shop/joints/{joint_id}",
                             headers=headers)

    def list_joints_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/joints", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Weld passes
    # ------------------------------------------------------------------
    def record_weld_pass(self, shop_id, joint_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/joints/{joint_id}/weld-passes",
            payload, headers)

    def list_weld_passes(self, shop_id, joint_id, headers, params=None):
        return self._request(
            "GET",
            f"/weld-shop/shops/{shop_id}/joints/{joint_id}/weld-passes",
            headers=headers, params=params)

    def get_weld_pass_flat(self, pass_id, headers):
        return self._request("GET", f"/weld-shop/weld-passes/{pass_id}",
                             headers=headers)

    def list_weld_passes_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/weld-passes", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Distortion reports
    # ------------------------------------------------------------------
    def create_distortion_report(self, shop_id, weldment_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/distortion-reports",
            payload, headers)

    def list_distortion_reports(self, shop_id, weldment_id, headers,
                                params=None):
        return self._request(
            "GET",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/distortion-reports",
            headers=headers, params=params)

    def disposition_distortion_report(self, shop_id, report_id, payload,
                                      headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/distortion-reports/{report_id}/disposition",
            payload, headers)

    def get_distortion_report_flat(self, report_id, headers):
        return self._request(
            "GET", f"/weld-shop/distortion-reports/{report_id}",
            headers=headers)

    def list_distortion_reports_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/distortion-reports",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def create_inspection(self, shop_id, joint_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/joints/{joint_id}/inspections",
            payload, headers)

    def list_inspections(self, shop_id, joint_id, headers, params=None):
        return self._request(
            "GET",
            f"/weld-shop/shops/{shop_id}/joints/{joint_id}/inspections",
            headers=headers, params=params)

    def get_inspection(self, shop_id, inspection_id, headers):
        return self._request(
            "GET", f"/weld-shop/shops/{shop_id}/inspections/{inspection_id}",
            headers=headers)

    def record_inspection_result(self, shop_id, inspection_id, payload,
                                 headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/inspections/{inspection_id}/record-result",
            payload, headers)

    def get_inspection_flat(self, inspection_id, headers):
        return self._request("GET", f"/weld-shop/inspections/{inspection_id}",
                             headers=headers)

    def list_inspections_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/inspections", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Traveler sign-offs
    # ------------------------------------------------------------------
    def create_traveler_sign_off(self, shop_id, weldment_id, payload, headers):
        return self._request(
            "POST",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/traveler-sign-offs",
            payload, headers)

    def list_traveler_sign_offs(self, shop_id, weldment_id, headers,
                                params=None):
        return self._request(
            "GET",
            f"/weld-shop/shops/{shop_id}/weldments/{weldment_id}/traveler-sign-offs",
            headers=headers, params=params)

    def get_traveler_sign_off_flat(self, signoff_id, headers):
        return self._request(
            "GET", f"/weld-shop/traveler-sign-offs/{signoff_id}",
            headers=headers)

    def list_traveler_sign_offs_flat(self, headers, params=None):
        return self._request("GET", "/weld-shop/traveler-sign-offs",
                             headers=headers, params=params)


api_client = ApiClient()
