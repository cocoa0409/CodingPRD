"""API client: one method per endpoint defined in the PRD.

Collections are mounted at the root of the service; there is no shared
resource prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # The logical project clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Facade packages
    # ------------------------------------------------------------------
    def create_facade_package(self, payload, headers):
        return self._request("POST", "/facade-packages", payload, headers)

    def list_facade_packages(self, headers, params=None):
        return self._request("GET", "/facade-packages", headers=headers, params=params)

    def get_facade_package(self, package_id, headers):
        return self._request("GET", f"/facade-packages/{package_id}", headers=headers)

    def decide_system(self, package_id, payload, headers):
        return self._request(
            "POST", f"/facade-packages/{package_id}/system-decision", payload, headers
        )

    def close_out_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/facade-packages/{package_id}/close-out", payload, headers
        )

    def get_earned_value(self, package_id, headers):
        return self._request(
            "GET", f"/facade-packages/{package_id}/earned-value", headers=headers
        )

    def list_package_submittals(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/facade-packages/{package_id}/submittals", headers=headers, params=params
        )

    def list_package_zones(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/facade-packages/{package_id}/zones", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Shop drawing submittals
    # ------------------------------------------------------------------
    def create_submittal(self, payload, headers):
        return self._request("POST", "/shop-drawing-submittals", payload, headers)

    def list_submittals(self, headers, params=None):
        return self._request("GET", "/shop-drawing-submittals", headers=headers, params=params)

    def get_submittal(self, submittal_id, headers):
        return self._request(
            "GET", f"/shop-drawing-submittals/{submittal_id}", headers=headers
        )

    def seal_submittal(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/shop-drawing-submittals/{submittal_id}/seal", payload, headers
        )

    def start_submittal_review(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/shop-drawing-submittals/{submittal_id}/start-review", payload, headers
        )

    def review_submittal(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/shop-drawing-submittals/{submittal_id}/review", payload, headers
        )

    def resubmit_submittal(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/shop-drawing-submittals/{submittal_id}/resubmit", payload, headers
        )

    def reopen_submittal_review(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/shop-drawing-submittals/{submittal_id}/reopen-review", payload, headers
        )

    def close_submittal_notes(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/shop-drawing-submittals/{submittal_id}/close-notes", payload, headers
        )

    # ------------------------------------------------------------------
    # Glass orders
    # ------------------------------------------------------------------
    def create_glass_order(self, payload, headers):
        return self._request("POST", "/glass-orders", payload, headers)

    def list_glass_orders(self, headers, params=None):
        return self._request("GET", "/glass-orders", headers=headers, params=params)

    def get_glass_order(self, order_id, headers):
        return self._request("GET", f"/glass-orders/{order_id}", headers=headers)

    def start_glass_production(self, order_id, payload, headers):
        return self._request(
            "POST", f"/glass-orders/{order_id}/start-production", payload, headers
        )

    def revise_coating(self, order_id, payload, headers):
        return self._request(
            "POST", f"/glass-orders/{order_id}/coating-revision", payload, headers
        )

    def request_expedite(self, order_id, payload, headers):
        return self._request(
            "POST", f"/glass-orders/{order_id}/request-expedite", payload, headers
        )

    def receive_glass_order(self, order_id, payload, headers):
        return self._request("POST", f"/glass-orders/{order_id}/receive", payload, headers)

    def recompute_glass_risk(self, order_id, payload, headers):
        return self._request(
            "POST", f"/glass-orders/{order_id}/recompute-risk", payload, headers
        )

    def list_glass_order_panel_lots(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/glass-orders/{order_id}/panel-lots", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Fabrication releases
    # ------------------------------------------------------------------
    def create_fabrication_release(self, payload, headers):
        return self._request("POST", "/fabrication-releases", payload, headers)

    def list_fabrication_releases(self, headers, params=None):
        return self._request("GET", "/fabrication-releases", headers=headers, params=params)

    def get_fabrication_release(self, release_id, headers):
        return self._request("GET", f"/fabrication-releases/{release_id}", headers=headers)

    def list_release_panel_lots(self, release_id, headers, params=None):
        return self._request(
            "GET", f"/fabrication-releases/{release_id}/panel-lots",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Panel lots
    # ------------------------------------------------------------------
    def list_panel_lots(self, headers, params=None):
        return self._request("GET", "/panel-lots", headers=headers, params=params)

    def get_panel_lot(self, lot_id, headers):
        return self._request("GET", f"/panel-lots/{lot_id}", headers=headers)

    def advance_fabrication(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/panel-lots/{lot_id}/advance-fabrication", payload, headers
        )

    # ------------------------------------------------------------------
    # Breakage draws
    # ------------------------------------------------------------------
    def create_breakage_draw(self, payload, headers):
        return self._request("POST", "/breakage-draws", payload, headers)

    def list_breakage_draws(self, headers, params=None):
        return self._request("GET", "/breakage-draws", headers=headers, params=params)

    def get_breakage_draw(self, draw_id, headers):
        return self._request("GET", f"/breakage-draws/{draw_id}", headers=headers)

    def cancel_breakage_draw(self, draw_id, payload, headers):
        return self._request("POST", f"/breakage-draws/{draw_id}/cancel", payload, headers)

    # ------------------------------------------------------------------
    # Test laboratories
    # ------------------------------------------------------------------
    def create_test_lab(self, payload, headers):
        return self._request("POST", "/test-labs", payload, headers)

    def list_test_labs(self, headers, params=None):
        return self._request("GET", "/test-labs", headers=headers, params=params)

    def get_test_lab(self, lab_id, headers):
        return self._request("GET", f"/test-labs/{lab_id}", headers=headers)

    def update_test_lab(self, lab_id, payload, headers, method="PUT"):
        """Laboratories have no update capability of any kind; used to prove that."""
        return self._request(method, f"/test-labs/{lab_id}", payload, headers)

    def delete_test_lab(self, lab_id, headers):
        return self._request("DELETE", f"/test-labs/{lab_id}", headers=headers)

    # ------------------------------------------------------------------
    # Mockup tests
    # ------------------------------------------------------------------
    def create_mockup_test(self, payload, headers):
        return self._request("POST", "/mockup-tests", payload, headers)

    def list_mockup_tests(self, headers, params=None):
        return self._request("GET", "/mockup-tests", headers=headers, params=params)

    def get_mockup_test(self, test_id, headers):
        return self._request("GET", f"/mockup-tests/{test_id}", headers=headers)

    def record_mockup_result(self, test_id, payload, headers):
        return self._request(
            "POST", f"/mockup-tests/{test_id}/record-result", payload, headers
        )

    # ------------------------------------------------------------------
    # Anchor embed surveys
    # ------------------------------------------------------------------
    def create_embed_survey(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/installation-zones/{zone_id}/embed-surveys", payload, headers
        )

    def list_embed_surveys(self, headers, params=None):
        return self._request("GET", "/embed-surveys", headers=headers, params=params)

    def get_embed_survey(self, survey_id, headers):
        return self._request("GET", f"/embed-surveys/{survey_id}", headers=headers)

    def record_embed_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/embed-surveys/{survey_id}/survey", payload, headers)

    def confirm_pour(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/embed-surveys/{survey_id}/confirm-pour", payload, headers
        )

    # ------------------------------------------------------------------
    # Installation zones
    # ------------------------------------------------------------------
    def create_installation_zone(self, payload, headers):
        return self._request("POST", "/installation-zones", payload, headers)

    def list_installation_zones(self, headers, params=None):
        return self._request("GET", "/installation-zones", headers=headers, params=params)

    def get_installation_zone(self, zone_id, headers):
        return self._request("GET", f"/installation-zones/{zone_id}", headers=headers)

    def set_anchors(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/installation-zones/{zone_id}/set-anchors", payload, headers
        )

    def hang_panels(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/installation-zones/{zone_id}/hang-panels", payload, headers
        )

    def certify_weather_tight(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/installation-zones/{zone_id}/certify-weather-tight", payload, headers
        )

    def retune_joint(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/installation-zones/{zone_id}/retune-joint", payload, headers
        )

    def list_zone_crew_day_logs(self, zone_id, headers, params=None):
        return self._request(
            "GET", f"/installation-zones/{zone_id}/crew-day-logs",
            headers=headers, params=params,
        )

    def list_zone_field_tests(self, zone_id, headers, params=None):
        return self._request(
            "GET", f"/installation-zones/{zone_id}/field-tests",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Crew days
    # ------------------------------------------------------------------
    def post_crew_day(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/installation-zones/{zone_id}/crew-days", payload, headers
        )

    def list_crew_day_logs(self, headers, params=None):
        return self._request("GET", "/crew-day-logs", headers=headers, params=params)

    def get_crew_day_log(self, crew_day_id, headers):
        return self._request("GET", f"/crew-day-logs/{crew_day_id}", headers=headers)

    def void_crew_day(self, zone_id, crew_day_id, payload, headers):
        return self._request(
            "POST",
            f"/installation-zones/{zone_id}/crew-days/{crew_day_id}/void",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Hoist rigs and reservations
    # ------------------------------------------------------------------
    def create_hoist_rig(self, payload, headers):
        return self._request("POST", "/hoist-rigs", payload, headers)

    def list_hoist_rigs(self, headers, params=None):
        return self._request("GET", "/hoist-rigs", headers=headers, params=params)

    def get_hoist_rig(self, rig_id, headers):
        return self._request("GET", f"/hoist-rigs/{rig_id}", headers=headers)

    def list_rig_reservations(self, rig_id, headers, params=None):
        return self._request(
            "GET", f"/hoist-rigs/{rig_id}/reservations", headers=headers, params=params
        )

    def create_hoist_reservation(self, payload, headers):
        return self._request("POST", "/hoist-reservations", payload, headers)

    def list_hoist_reservations(self, headers, params=None):
        return self._request("GET", "/hoist-reservations", headers=headers, params=params)

    def get_hoist_reservation(self, reservation_id, headers):
        return self._request("GET", f"/hoist-reservations/{reservation_id}", headers=headers)

    def cancel_hoist_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/hoist-reservations/{reservation_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Field tests
    # ------------------------------------------------------------------
    def schedule_field_test(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/installation-zones/{zone_id}/field-tests", payload, headers
        )

    def list_field_tests(self, headers, params=None):
        return self._request("GET", "/field-tests", headers=headers, params=params)

    def get_field_test(self, test_id, headers):
        return self._request("GET", f"/field-tests/{test_id}", headers=headers)

    def record_field_test_result(self, test_id, payload, headers):
        return self._request(
            "POST", f"/field-tests/{test_id}/record-result", payload, headers
        )

    # ------------------------------------------------------------------
    # Defect items
    # ------------------------------------------------------------------
    def create_defect_item(self, payload, headers):
        return self._request("POST", "/defect-items", payload, headers)

    def list_defect_items(self, headers, params=None):
        return self._request("GET", "/defect-items", headers=headers, params=params)

    def get_defect_item(self, defect_id, headers):
        return self._request("GET", f"/defect-items/{defect_id}", headers=headers)

    def submit_defect_remediation(self, defect_id, payload, headers):
        return self._request(
            "POST", f"/defect-items/{defect_id}/submit-remediation", payload, headers
        )

    def reinspect_defect(self, defect_id, payload, headers):
        return self._request(
            "POST", f"/defect-items/{defect_id}/reinspect", payload, headers
        )

    def waive_defect(self, defect_id, payload, headers):
        return self._request("POST", f"/defect-items/{defect_id}/waive", payload, headers)


api_client = ApiClient()
