"""Domain client for the trailer plant API.

One method per endpoint of PRD section 4. Every method returns the raw
response object so that tests can assert on the status code as well as the
body; no method raises on a 4xx.
"""

from prd_bench_local_runner.testing import GenericApiClient


class TrailerPlantClient(GenericApiClient):
    # --- Logical clock (PRD 2.4) -----------------------------------------
    def set_clock(self, to_iso8601, headers=None):
        return self.post("/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)

    # --- Trailer models (PRD 3.1) ---------------------------------------
    def create_model(self, payload, headers=None):
        return self.post("/trailer-models", payload, headers=headers)

    def submit_model(self, model_id, payload, headers=None):
        return self.post(
            "/trailer-models/%s/certification-submission" % model_id, payload, headers=headers
        )

    def decide_model(self, model_id, payload, headers=None):
        return self.post(
            "/trailer-models/%s/certification-decision" % model_id, payload, headers=headers
        )

    def get_model(self, model_id, headers=None):
        return self.get("/trailer-models/%s" % model_id, headers=headers)

    # --- Dealers and floor plan (PRD 3.8) -------------------------------
    def create_dealer(self, payload, headers=None):
        return self.post("/dealers", payload, headers=headers)

    def adjust_floor_plan(self, dealer_id, payload, headers=None):
        return self.post("/dealers/%s/floor-plan-adjustments" % dealer_id, payload, headers=headers)

    def get_dealer(self, dealer_id, headers=None):
        return self.get("/dealers/%s" % dealer_id, headers=headers)

    # --- Plant assets (PRD 3.2, 3.6) ------------------------------------
    def create_jig(self, payload, headers=None):
        return self.post("/weld-jigs", payload, headers=headers)

    def get_jig(self, jig_id, headers=None):
        return self.get("/weld-jigs/%s" % jig_id, headers=headers)

    def create_lane(self, payload, headers=None):
        return self.post("/test-lanes", payload, headers=headers)

    def get_lane(self, lane_id, headers=None):
        return self.get("/test-lanes/%s" % lane_id, headers=headers)

    # --- Build records (PRD 3.2) ----------------------------------------
    def create_unit(self, payload, headers=None):
        return self.post("/trailer-units", payload, headers=headers)

    def get_unit(self, unit_id, headers=None):
        return self.get("/trailer-units/%s" % unit_id, headers=headers)

    def list_units(self, params=None, headers=None):
        return self.get("/trailer-units", headers=headers, params=params)

    # --- Jig reservations (PRD 3.2) -------------------------------------
    def reserve_jig(self, jig_id, payload, headers=None):
        return self.post("/weld-jigs/%s/jig-reservations" % jig_id, payload, headers=headers)

    def list_jig_reservations(self, jig_id, params=None, headers=None):
        return self.get("/weld-jigs/%s/jig-reservations" % jig_id, headers=headers, params=params)

    def list_unit_jig_reservations(self, unit_id, params=None, headers=None):
        return self.get("/trailer-units/%s/jig-reservations" % unit_id, headers=headers, params=params)

    # --- Frame inspections (PRD 3.3) ------------------------------------
    def create_frame_inspection(self, unit_id, payload, headers=None):
        return self.post("/trailer-units/%s/frame-inspections" % unit_id, payload, headers=headers)

    def list_frame_inspections(self, unit_id, params=None, headers=None):
        return self.get("/trailer-units/%s/frame-inspections" % unit_id, headers=headers, params=params)

    # --- Systems installation (PRD 3.4) ---------------------------------
    def install_systems(self, unit_id, payload, headers=None):
        return self.post("/trailer-units/%s/systems-install" % unit_id, payload, headers=headers)

    # --- Option installs (PRD 3.5) --------------------------------------
    def create_option_install(self, unit_id, payload, headers=None):
        return self.post("/trailer-units/%s/option-installs" % unit_id, payload, headers=headers)

    def complete_option_install(self, option_install_id, payload, headers=None):
        return self.post("/option-installs/%s/completion" % option_install_id, payload, headers=headers)

    def delete_option_install(self, option_install_id, payload=None, headers=None):
        return self.delete("/option-installs/%s" % option_install_id, headers=headers, params=payload)

    def get_option_install(self, option_install_id, headers=None):
        return self.get("/option-installs/%s" % option_install_id, headers=headers)

    def list_option_installs(self, unit_id, params=None, headers=None):
        return self.get("/trailer-units/%s/option-installs" % unit_id, headers=headers, params=params)

    # --- Road tests (PRD 3.6) -------------------------------------------
    def book_road_test(self, unit_id, payload, headers=None):
        return self.post("/trailer-units/%s/road-tests" % unit_id, payload, headers=headers)

    def record_road_test_result(self, road_test_id, payload, headers=None):
        return self.post("/road-tests/%s/result" % road_test_id, payload, headers=headers)

    def get_road_test(self, road_test_id, headers=None):
        return self.get("/road-tests/%s" % road_test_id, headers=headers)

    def list_unit_road_tests(self, unit_id, params=None, headers=None):
        return self.get("/trailer-units/%s/road-tests" % unit_id, headers=headers, params=params)

    def list_lane_road_tests(self, lane_id, params=None, headers=None):
        return self.get("/test-lanes/%s/road-tests" % lane_id, headers=headers, params=params)

    # --- Certification labels (PRD 3.7) ---------------------------------
    def issue_label(self, unit_id, payload, headers=None):
        return self.post("/trailer-units/%s/certification-label" % unit_id, payload, headers=headers)

    def list_labels(self, unit_id, params=None, headers=None):
        return self.get("/trailer-units/%s/certification-label" % unit_id, headers=headers, params=params)

    # --- Dealer orders (PRD 3.8) ----------------------------------------
    def create_order(self, payload, headers=None):
        return self.post("/dealer-orders", payload, headers=headers)

    def allocate_order(self, order_id, payload, headers=None):
        return self.post("/dealer-orders/%s/allocation" % order_id, payload, headers=headers)

    def cancel_order(self, order_id, payload, headers=None):
        return self.post("/dealer-orders/%s/cancellation" % order_id, payload, headers=headers)

    def deliver_order(self, order_id, payload, headers=None):
        return self.post("/dealer-orders/%s/delivery" % order_id, payload, headers=headers)

    def get_order(self, order_id, headers=None):
        return self.get("/dealer-orders/%s" % order_id, headers=headers)

    def list_orders(self, params=None, headers=None):
        return self.get("/dealer-orders", headers=headers, params=params)

    # --- Warranty claims (PRD 3.9) --------------------------------------
    def create_claim(self, payload, headers=None):
        return self.post("/warranty-claims", payload, headers=headers)

    def review_claim(self, claim_id, payload, headers=None):
        return self.post("/warranty-claims/%s/review" % claim_id, payload, headers=headers)

    def resubmit_claim(self, claim_id, payload, headers=None):
        return self.post("/warranty-claims/%s/resubmission" % claim_id, payload, headers=headers)

    def ship_claim_parts(self, claim_id, payload, headers=None):
        return self.post("/warranty-claims/%s/part-shipment" % claim_id, payload, headers=headers)

    def get_claim(self, claim_id, headers=None):
        return self.get("/warranty-claims/%s" % claim_id, headers=headers)

    def list_claims(self, params=None, headers=None):
        return self.get("/warranty-claims", headers=headers, params=params)

    # --- Raw escape hatch for header-omission tests (PRD 2.1) -----------
    def raw_post(self, path, payload=None, headers=None):
        return self.post(path, payload, headers=headers)

    def raw_get(self, path, params=None, headers=None):
        return self.get(path, headers=headers, params=params)


api_client = TrailerPlantClient()
ApiClient = TrailerPlantClient
