"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/api/v1"


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- contractors ---
    def create_contractor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"{PREFIX}/contractors/{contractor_id}", headers=headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contractors", headers=headers, params=params)

    def patch_contractor(self, contractor_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/contractors/{contractor_id}", payload, headers)

    # --- equipment catalog ---
    def create_equipment_model(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-models", payload, headers)

    def get_equipment_model(self, model_id, headers):
        return self._request("GET", f"{PREFIX}/equipment-models/{model_id}", headers=headers)

    def list_equipment_models(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/equipment-models", headers=headers, params=params)

    # --- AHRI ratings ---
    def create_ahri_rating(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ahri-ratings", payload, headers)

    def get_ahri_rating(self, rating_id, headers):
        return self._request("GET", f"{PREFIX}/ahri-ratings/{rating_id}", headers=headers)

    def list_ahri_ratings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ahri-ratings", headers=headers, params=params)

    # --- pre-buy programs ---
    def create_prebuy_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prebuy-programs", payload, headers)

    def get_prebuy_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/prebuy-programs/{program_id}", headers=headers)

    def list_prebuy_programs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prebuy-programs", headers=headers, params=params)

    def close_prebuy_program(self, program_id, headers):
        return self._request("POST", f"{PREFIX}/prebuy-programs/{program_id}/close", {}, headers)

    # --- allocation pools ---
    def create_allocation_pool(self, payload, headers):
        return self._request("POST", f"{PREFIX}/allocation-pools", payload, headers)

    def get_allocation_pool(self, pool_id, headers):
        return self._request("GET", f"{PREFIX}/allocation-pools/{pool_id}", headers=headers)

    def list_allocation_pools(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/allocation-pools", headers=headers, params=params)

    def close_allocation_pool(self, pool_id, headers):
        return self._request("POST", f"{PREFIX}/allocation-pools/{pool_id}/close", {}, headers)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def patch_order(self, order_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/orders/{order_id}", payload, headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/order-lines/{line_id}", headers=headers)

    def list_all_order_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/order-lines", headers=headers, params=params)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/submit", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/cancel", {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/ship", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/deliver", {}, headers)

    def post_billing_event(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/billing-events", payload, headers)

    # --- warranty registrations ---
    def create_warranty_registration(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-registrations", payload, headers)

    def get_warranty_registration(self, registration_id, headers):
        return self._request("GET", f"{PREFIX}/warranty-registrations/{registration_id}", headers=headers)

    def list_warranty_registrations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warranty-registrations", headers=headers, params=params)

    def register_warranty(self, registration_id, headers):
        return self._request("POST", f"{PREFIX}/warranty-registrations/{registration_id}/register", {}, headers)

    def void_warranty(self, registration_id, headers):
        return self._request("POST", f"{PREFIX}/warranty-registrations/{registration_id}/void", {}, headers)

    # --- parts claims ---
    def create_parts_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-claims", payload, headers)

    def get_parts_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/parts-claims/{claim_id}", headers=headers)

    def list_parts_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/parts-claims", headers=headers, params=params)

    def parts_claim_decision(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-claims/{claim_id}/decision", payload, headers)

    def resubmit_parts_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-claims/{claim_id}/resubmit", payload, headers)

    # --- refrigerant cylinders ---
    def create_cylinder(self, payload, headers):
        return self._request("POST", f"{PREFIX}/refrigerant-cylinders", payload, headers)

    def get_cylinder(self, cylinder_id, headers):
        return self._request("GET", f"{PREFIX}/refrigerant-cylinders/{cylinder_id}", headers=headers)

    def list_cylinders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/refrigerant-cylinders", headers=headers, params=params)

    def issue_cylinder(self, cylinder_id, payload, headers):
        return self._request("POST", f"{PREFIX}/refrigerant-cylinders/{cylinder_id}/issue", payload, headers)

    def return_cylinder(self, cylinder_id, payload, headers):
        return self._request("POST", f"{PREFIX}/refrigerant-cylinders/{cylinder_id}/return", payload, headers)

    def reclaim_cylinder(self, cylinder_id, headers):
        return self._request("POST", f"{PREFIX}/refrigerant-cylinders/{cylinder_id}/reclaim", {}, headers)

    def refill_cylinder(self, cylinder_id, headers):
        return self._request("POST", f"{PREFIX}/refrigerant-cylinders/{cylinder_id}/refill", {}, headers)

    def list_cylinder_events(self, cylinder_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/refrigerant-cylinders/{cylinder_id}/events", headers=headers, params=params)

    # --- rebate submissions ---
    def create_rebate_submission(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rebate-submissions", payload, headers)

    def get_rebate_submission(self, submission_id, headers):
        return self._request("GET", f"{PREFIX}/rebate-submissions/{submission_id}", headers=headers)

    def list_rebate_submissions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rebate-submissions", headers=headers, params=params)

    def patch_rebate_submission(self, submission_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/rebate-submissions/{submission_id}", payload, headers)

    def submit_rebate(self, submission_id, headers):
        return self._request("POST", f"{PREFIX}/rebate-submissions/{submission_id}/submit", {}, headers)

    def rebate_decision(self, submission_id, payload, headers):
        return self._request("POST", f"{PREFIX}/rebate-submissions/{submission_id}/decision", payload, headers)

    # --- training ---
    def create_training_course(self, payload, headers):
        return self._request("POST", f"{PREFIX}/training-courses", payload, headers)

    def get_training_course(self, course_id, headers):
        return self._request("GET", f"{PREFIX}/training-courses/{course_id}", headers=headers)

    def list_training_courses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/training-courses", headers=headers, params=params)

    def patch_training_course(self, course_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/training-courses/{course_id}", payload, headers)

    def complete_training_course(self, course_id, payload, headers):
        return self._request("POST", f"{PREFIX}/training-courses/{course_id}/complete", payload, headers)

    def get_training_credit(self, credit_id, headers):
        return self._request("GET", f"{PREFIX}/training-credits/{credit_id}", headers=headers)

    def list_training_credits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/training-credits", headers=headers, params=params)

    # --- co-op claims ---
    def create_coop_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coop-claims", payload, headers)

    def get_coop_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/coop-claims/{claim_id}", headers=headers)

    def list_coop_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coop-claims", headers=headers, params=params)

    def coop_claim_decision(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coop-claims/{claim_id}/decision", payload, headers)


api_client = ApiClient()
