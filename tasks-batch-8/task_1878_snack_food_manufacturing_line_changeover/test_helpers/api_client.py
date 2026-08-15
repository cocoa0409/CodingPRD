"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock -------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/snack-mfg/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- products ------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/snack-mfg/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request(
            "GET", f"/snack-mfg/products/{product_id}", headers=headers,
        )

    # --- production lines ------------------------------------------------------
    def create_line(self, payload, headers):
        return self._request("POST", "/snack-mfg/lines", payload, headers)

    def get_line(self, line_id, headers):
        return self._request(
            "GET", f"/snack-mfg/lines/{line_id}", headers=headers,
        )

    # --- production runs -------------------------------------------------------
    def create_run(self, payload, headers):
        return self._request("POST", "/snack-mfg/production-runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request(
            "GET", f"/snack-mfg/production-runs/{run_id}", headers=headers,
        )

    def list_runs(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/production-runs", headers=headers, params=params,
        )

    def start_run(self, run_id, headers):
        return self._request(
            "POST", f"/snack-mfg/production-runs/{run_id}/start", headers=headers,
        )

    def place_hold(self, run_id, headers):
        return self._request(
            "POST", f"/snack-mfg/production-runs/{run_id}/place-hold",
            headers=headers,
        )

    def release_hold(self, run_id, headers):
        return self._request(
            "POST", f"/snack-mfg/production-runs/{run_id}/release-hold",
            headers=headers,
        )

    def complete_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/snack-mfg/production-runs/{run_id}/complete",
            payload, headers,
        )

    def cancel_run(self, run_id, headers):
        return self._request(
            "POST", f"/snack-mfg/production-runs/{run_id}/cancel", headers=headers,
        )

    def quality_disposition(self, run_id, disposition, headers):
        return self._request(
            "POST", f"/snack-mfg/production-runs/{run_id}/quality-disposition",
            {"disposition": disposition}, headers,
        )

    def get_cost_summary(self, run_id, headers):
        return self._request(
            "GET", f"/snack-mfg/production-runs/{run_id}/cost-summary",
            headers=headers,
        )

    # --- weight checks ---------------------------------------------------------
    def create_weight_check(self, payload, headers):
        return self._request("POST", "/snack-mfg/weight-checks", payload, headers)

    def get_weight_check(self, check_id, headers):
        return self._request(
            "GET", f"/snack-mfg/weight-checks/{check_id}", headers=headers,
        )

    def list_weight_checks(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/weight-checks", headers=headers, params=params,
        )

    # --- changeovers -----------------------------------------------------------
    def create_changeover(self, payload, headers):
        return self._request("POST", "/snack-mfg/changeovers", payload, headers)

    def get_changeover(self, changeover_id, headers):
        return self._request(
            "GET", f"/snack-mfg/changeovers/{changeover_id}", headers=headers,
        )

    def list_changeovers(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/changeovers", headers=headers, params=params,
        )

    def begin_cleaning(self, changeover_id, headers):
        return self._request(
            "POST", f"/snack-mfg/changeovers/{changeover_id}/begin-cleaning",
            headers=headers,
        )

    def record_swab(self, changeover_id, result, headers):
        return self._request(
            "POST", f"/snack-mfg/changeovers/{changeover_id}/record-swab",
            {"result": result}, headers,
        )

    def validate_changeover(self, changeover_id, headers):
        return self._request(
            "POST", f"/snack-mfg/changeovers/{changeover_id}/validate",
            headers=headers,
        )

    # --- fryer oil -------------------------------------------------------------
    def get_fryer_oil(self, oil_id, headers):
        return self._request(
            "GET", f"/snack-mfg/fryer-oils/{oil_id}", headers=headers,
        )

    def list_fryer_oils(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/fryer-oils", headers=headers, params=params,
        )

    def begin_oil_change(self, oil_id, headers):
        return self._request(
            "POST", f"/snack-mfg/fryer-oils/{oil_id}/begin-change",
            headers=headers,
        )

    # --- oil movements ---------------------------------------------------------
    def create_oil_movement(self, payload, headers):
        return self._request("POST", "/snack-mfg/oil-movements", payload, headers)

    def get_oil_movement(self, movement_id, headers):
        return self._request(
            "GET", f"/snack-mfg/oil-movements/{movement_id}", headers=headers,
        )

    def list_oil_movements(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/oil-movements", headers=headers, params=params,
        )

    # --- shipments -------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/snack-mfg/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request(
            "GET", f"/snack-mfg/shipments/{shipment_id}", headers=headers,
        )

    def list_shipments(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/shipments", headers=headers, params=params,
        )

    def plan_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/snack-mfg/shipments/{shipment_id}/plan", headers=headers,
        )

    def replan_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/snack-mfg/shipments/{shipment_id}/replan", headers=headers,
        )

    def dispatch_shipment(self, shipment_id, headers, payload=None):
        return self._request(
            "POST", f"/snack-mfg/shipments/{shipment_id}/dispatch",
            payload, headers,
        )

    def cancel_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/snack-mfg/shipments/{shipment_id}/cancel", headers=headers,
        )

    # --- promo windows ---------------------------------------------------------
    def create_promo_window(self, payload, headers):
        return self._request("POST", "/snack-mfg/promo-windows", payload, headers)

    def get_promo_window(self, window_id, headers):
        return self._request(
            "GET", f"/snack-mfg/promo-windows/{window_id}", headers=headers,
        )

    def list_promo_windows(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/promo-windows", headers=headers, params=params,
        )

    def activate_promo_window(self, window_id, headers):
        return self._request(
            "POST", f"/snack-mfg/promo-windows/{window_id}/activate",
            headers=headers,
        )

    def close_promo_window(self, window_id, headers):
        return self._request(
            "POST", f"/snack-mfg/promo-windows/{window_id}/close", headers=headers,
        )

    # --- display cases ---------------------------------------------------------
    def create_display_case(self, payload, headers):
        return self._request("POST", "/snack-mfg/display-cases", payload, headers)

    def get_display_case(self, case_id, headers):
        return self._request(
            "GET", f"/snack-mfg/display-cases/{case_id}", headers=headers,
        )

    def list_display_cases(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/display-cases", headers=headers, params=params,
        )

    def build_display_case(self, case_id, headers):
        return self._request(
            "POST", f"/snack-mfg/display-cases/{case_id}/build", headers=headers,
        )

    def cancel_display_case(self, case_id, headers):
        return self._request(
            "POST", f"/snack-mfg/display-cases/{case_id}/cancel", headers=headers,
        )

    # --- co-manufacturers --------------------------------------------------------
    def create_co_manufacturer(self, payload, headers):
        return self._request(
            "POST", "/snack-mfg/co-manufacturers", payload, headers,
        )

    def get_co_manufacturer(self, coman_id, headers):
        return self._request(
            "GET", f"/snack-mfg/co-manufacturers/{coman_id}", headers=headers,
        )

    # --- co-man agreements -------------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request(
            "POST", "/snack-mfg/co-man-agreements", payload, headers,
        )

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/snack-mfg/co-man-agreements/{agreement_id}", headers=headers,
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/co-man-agreements", headers=headers, params=params,
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/snack-mfg/co-man-agreements/{agreement_id}/activate",
            headers=headers,
        )

    def suspend_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/snack-mfg/co-man-agreements/{agreement_id}/suspend",
            headers=headers,
        )

    def resume_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/snack-mfg/co-man-agreements/{agreement_id}/resume",
            headers=headers,
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/snack-mfg/co-man-agreements/{agreement_id}/terminate",
            headers=headers,
        )

    # --- co-man slots ------------------------------------------------------------
    def create_slot(self, payload, headers):
        return self._request("POST", "/snack-mfg/co-man-slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request(
            "GET", f"/snack-mfg/co-man-slots/{slot_id}", headers=headers,
        )

    def list_slots(self, headers, params=None):
        return self._request(
            "GET", "/snack-mfg/co-man-slots", headers=headers, params=params,
        )

    def confirm_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/snack-mfg/co-man-slots/{slot_id}/confirm", headers=headers,
        )

    def release_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/snack-mfg/co-man-slots/{slot_id}/release", headers=headers,
        )

    def consume_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/snack-mfg/co-man-slots/{slot_id}/consume", headers=headers,
        )


api_client = ApiClient()
