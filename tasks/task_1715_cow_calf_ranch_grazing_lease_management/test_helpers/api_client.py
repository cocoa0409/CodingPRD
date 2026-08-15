"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Ranches
    # ------------------------------------------------------------------
    def create_ranch(self, payload, headers):
        return self._request("POST", "/api/ranches", payload, headers)

    def get_ranch(self, ranch_id, headers):
        return self._request("GET", f"/api/ranches/{ranch_id}", headers=headers)

    def patch_ranch(self, ranch_id, payload, headers):
        return self._request("PATCH", f"/api/ranches/{ranch_id}", payload, headers)

    # ------------------------------------------------------------------
    # Pastures
    # ------------------------------------------------------------------
    def create_pasture(self, payload, headers):
        return self._request("POST", "/api/pastures", payload, headers)

    def get_pasture(self, pasture_id, headers):
        return self._request("GET", f"/api/pastures/{pasture_id}", headers=headers)

    def list_pastures(self, headers, params=None):
        return self._request("GET", "/api/pastures", headers=headers, params=params)

    def close_pasture(self, pasture_id, headers):
        return self._request("POST", f"/api/pastures/{pasture_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Grazing leases
    # ------------------------------------------------------------------
    def create_lease(self, payload, headers):
        return self._request("POST", "/api/grazing-leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/api/grazing-leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/api/grazing-leases", headers=headers, params=params)

    def patch_lease(self, lease_id, payload, headers):
        return self._request("PATCH", f"/api/grazing-leases/{lease_id}", payload, headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/api/grazing-leases/{lease_id}/activate", {}, headers)

    def suspend_lease(self, lease_id, headers):
        return self._request("POST", f"/api/grazing-leases/{lease_id}/suspend", {}, headers)

    def reinstate_lease(self, lease_id, headers):
        return self._request("POST", f"/api/grazing-leases/{lease_id}/reinstate", {}, headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"/api/grazing-leases/{lease_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Lease statements
    # ------------------------------------------------------------------
    def create_lease_statement(self, payload, headers):
        return self._request("POST", "/api/lease-statements", payload, headers)

    def get_lease_statement(self, statement_id, headers):
        return self._request("GET", f"/api/lease-statements/{statement_id}", headers=headers)

    def list_lease_statements(self, headers, params=None):
        return self._request("GET", "/api/lease-statements", headers=headers, params=params)

    def issue_statement(self, statement_id, headers):
        return self._request("POST", f"/api/lease-statements/{statement_id}/issue", {}, headers)

    def approve_statement(self, statement_id, headers):
        return self._request("POST", f"/api/lease-statements/{statement_id}/approve", {}, headers)

    def mark_statement_paid(self, statement_id, headers):
        return self._request("POST", f"/api/lease-statements/{statement_id}/mark-paid", {}, headers)

    # ------------------------------------------------------------------
    # Herd groups
    # ------------------------------------------------------------------
    def create_herd_group(self, payload, headers):
        return self._request("POST", "/api/herd-groups", payload, headers)

    def get_herd_group(self, group_id, headers):
        return self._request("GET", f"/api/herd-groups/{group_id}", headers=headers)

    def list_herd_groups(self, headers, params=None):
        return self._request("GET", "/api/herd-groups", headers=headers, params=params)

    def record_reduction(self, group_id, payload, headers):
        return self._request("POST", f"/api/herd-groups/{group_id}/reductions", payload, headers)

    # ------------------------------------------------------------------
    # Breeding seasons
    # ------------------------------------------------------------------
    def create_breeding_season(self, payload, headers):
        return self._request("POST", "/api/breeding-seasons", payload, headers)

    def get_breeding_season(self, season_id, headers):
        return self._request("GET", f"/api/breeding-seasons/{season_id}", headers=headers)

    def list_breeding_seasons(self, headers, params=None):
        return self._request("GET", "/api/breeding-seasons", headers=headers, params=params)

    def begin_breeding(self, season_id, headers):
        return self._request("POST", f"/api/breeding-seasons/{season_id}/begin-breeding", {}, headers)

    def end_breeding(self, season_id, headers):
        return self._request("POST", f"/api/breeding-seasons/{season_id}/end-breeding", {}, headers)

    # ------------------------------------------------------------------
    # Bulls
    # ------------------------------------------------------------------
    def create_bull(self, payload, headers):
        return self._request("POST", "/api/bulls", payload, headers)

    def get_bull(self, bull_id, headers):
        return self._request("GET", f"/api/bulls/{bull_id}", headers=headers)

    def list_bulls(self, headers, params=None):
        return self._request("GET", "/api/bulls", headers=headers, params=params)

    def record_bse(self, bull_id, payload, headers):
        return self._request("POST", f"/api/bulls/{bull_id}/record-bse", payload, headers)

    def retire_bull(self, bull_id, payload, headers):
        return self._request("POST", f"/api/bulls/{bull_id}/retire", payload, headers)

    # ------------------------------------------------------------------
    # Bull turnouts
    # ------------------------------------------------------------------
    def create_bull_turnout(self, payload, headers):
        return self._request("POST", "/api/bull-turnouts", payload, headers)

    def get_bull_turnout(self, turnout_id, headers):
        return self._request("GET", f"/api/bull-turnouts/{turnout_id}", headers=headers)

    def list_bull_turnouts(self, headers, params=None):
        return self._request("GET", "/api/bull-turnouts", headers=headers, params=params)

    def turn_in_turnout(self, turnout_id, headers):
        return self._request("POST", f"/api/bull-turnouts/{turnout_id}/turn-in", {}, headers)

    def remove_turnout(self, turnout_id, payload, headers):
        return self._request("POST", f"/api/bull-turnouts/{turnout_id}/remove", payload, headers)

    def cancel_turnout(self, turnout_id, headers):
        return self._request("POST", f"/api/bull-turnouts/{turnout_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Preg checks
    # ------------------------------------------------------------------
    def create_preg_check(self, payload, headers):
        return self._request("POST", "/api/preg-checks", payload, headers)

    def get_preg_check(self, check_id, headers):
        return self._request("GET", f"/api/preg-checks/{check_id}", headers=headers)

    def list_preg_checks(self, headers, params=None):
        return self._request("GET", "/api/preg-checks", headers=headers, params=params)

    def finalize_preg_check(self, check_id, payload, headers):
        return self._request("POST", f"/api/preg-checks/{check_id}/finalize", payload, headers)

    # ------------------------------------------------------------------
    # Calf crops
    # ------------------------------------------------------------------
    def create_calf_crop(self, payload, headers):
        return self._request("POST", "/api/calf-crops", payload, headers)

    def get_calf_crop(self, crop_id, headers):
        return self._request("GET", f"/api/calf-crops/{crop_id}", headers=headers)

    def list_calf_crops(self, headers, params=None):
        return self._request("GET", "/api/calf-crops", headers=headers, params=params)

    def record_weaning(self, crop_id, payload, headers):
        return self._request("POST", f"/api/calf-crops/{crop_id}/record-weaning", payload, headers)

    def enroll_preconditioning(self, crop_id, headers):
        return self._request("POST", f"/api/calf-crops/{crop_id}/enroll-preconditioning", {}, headers)

    def record_vaccine(self, crop_id, payload, headers):
        return self._request("POST", f"/api/calf-crops/{crop_id}/record-vaccine", payload, headers)

    def certify_preconditioning(self, crop_id, headers):
        return self._request("POST", f"/api/calf-crops/{crop_id}/certify-preconditioning", {}, headers)

    def retain_heifers(self, crop_id, payload, headers):
        return self._request("POST", f"/api/calf-crops/{crop_id}/retain-heifers", payload, headers)

    def unretain_heifers(self, crop_id, payload, headers):
        return self._request("POST", f"/api/calf-crops/{crop_id}/unretain-heifers", payload, headers)

    def record_death_loss(self, crop_id, payload, headers):
        return self._request("POST", f"/api/calf-crops/{crop_id}/record-death-loss", payload, headers)

    # ------------------------------------------------------------------
    # Sale lots
    # ------------------------------------------------------------------
    def create_sale_lot(self, payload, headers):
        return self._request("POST", "/api/sale-lots", payload, headers)

    def get_sale_lot(self, lot_id, headers):
        return self._request("GET", f"/api/sale-lots/{lot_id}", headers=headers)

    def list_sale_lots(self, headers, params=None):
        return self._request("GET", "/api/sale-lots", headers=headers, params=params)

    def offer_lot(self, lot_id, headers):
        return self._request("POST", f"/api/sale-lots/{lot_id}/offer", {}, headers)

    def contract_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/sale-lots/{lot_id}/contract", payload, headers)

    def relist_lot(self, lot_id, headers):
        return self._request("POST", f"/api/sale-lots/{lot_id}/relist", {}, headers)

    def deliver_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/sale-lots/{lot_id}/deliver", payload, headers)

    def dispute_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/sale-lots/{lot_id}/dispute", payload, headers)

    def resolve_dispute(self, lot_id, payload, headers):
        return self._request("POST", f"/api/sale-lots/{lot_id}/resolve-dispute", payload, headers)

    def settle_lot(self, lot_id, headers):
        return self._request("POST", f"/api/sale-lots/{lot_id}/settle", {}, headers)

    def cancel_lot(self, lot_id, headers):
        return self._request("POST", f"/api/sale-lots/{lot_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Grazing assignments
    # ------------------------------------------------------------------
    def create_grazing_assignment(self, payload, headers):
        return self._request("POST", "/api/grazing-assignments", payload, headers)

    def get_grazing_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/grazing-assignments/{assignment_id}", headers=headers)

    def list_grazing_assignments(self, headers, params=None):
        return self._request("GET", "/api/grazing-assignments", headers=headers, params=params)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/grazing-assignments/{assignment_id}/complete", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/grazing-assignments/{assignment_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Supplement programs
    # ------------------------------------------------------------------
    def create_supplement_program(self, payload, headers):
        return self._request("POST", "/api/supplement-programs", payload, headers)

    def get_supplement_program(self, program_id, headers):
        return self._request("GET", f"/api/supplement-programs/{program_id}", headers=headers)

    def list_supplement_programs(self, headers, params=None):
        return self._request("GET", "/api/supplement-programs", headers=headers, params=params)

    def record_delivery(self, program_id, payload, headers):
        return self._request("POST", f"/api/supplement-programs/{program_id}/deliveries", payload, headers)

    def complete_program(self, program_id, headers):
        return self._request("POST", f"/api/supplement-programs/{program_id}/complete", {}, headers)

    def cancel_program(self, program_id, headers):
        return self._request("POST", f"/api/supplement-programs/{program_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Drought assessments
    # ------------------------------------------------------------------
    def create_drought_assessment(self, payload, headers):
        return self._request("POST", "/api/drought-assessments", payload, headers)

    def get_drought_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/drought-assessments/{assessment_id}", headers=headers)

    def list_drought_assessments(self, headers, params=None):
        return self._request("GET", "/api/drought-assessments", headers=headers, params=params)

    def finalize_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/api/drought-assessments/{assessment_id}/finalize", payload, headers)

    # ------------------------------------------------------------------
    # Destock orders
    # ------------------------------------------------------------------
    def get_destock_order(self, order_id, headers):
        return self._request("GET", f"/api/destock-orders/{order_id}", headers=headers)

    def list_destock_orders(self, headers, params=None):
        return self._request("GET", "/api/destock-orders", headers=headers, params=params)

    def verify_compliance(self, order_id, headers):
        return self._request("POST", f"/api/destock-orders/{order_id}/verify-compliance", {}, headers)

    def waive_destock_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/destock-orders/{order_id}/waive", payload, headers)


api_client = ApiClient()
