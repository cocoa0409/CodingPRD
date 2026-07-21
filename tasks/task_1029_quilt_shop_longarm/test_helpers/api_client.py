"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers=headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def list_member_loyalty_transactions(self, member_id, headers, params=None):
        return self._request("GET", f"/api/members/{member_id}/loyalty-transactions",
                             headers=headers, params=params)

    # --- FabricBolt ---
    def create_fabric_bolt(self, payload, headers):
        return self._request("POST", "/api/fabric-bolts", payload, headers=headers)

    def get_fabric_bolt(self, bolt_id, headers):
        return self._request("GET", f"/api/fabric-bolts/{bolt_id}", headers=headers)

    def restock_fabric_bolt(self, bolt_id, payload, headers):
        return self._request("POST", f"/api/fabric-bolts/{bolt_id}/restock", payload, headers=headers)

    def discontinue_fabric_bolt(self, bolt_id, headers):
        return self._request("POST", f"/api/fabric-bolts/{bolt_id}/discontinue", {}, headers=headers)

    # --- FabricCut ---
    def create_fabric_cut(self, payload, headers):
        return self._request("POST", "/api/fabric-cuts", payload, headers=headers)

    def list_fabric_cuts(self, headers, params=None):
        return self._request("GET", "/api/fabric-cuts", headers=headers, params=params)

    def get_fabric_cut(self, cut_id, headers):
        return self._request("GET", f"/api/fabric-cuts/{cut_id}", headers=headers)

    def void_fabric_cut(self, cut_id, headers):
        return self._request("POST", f"/api/fabric-cuts/{cut_id}/void", {}, headers=headers)

    # --- Kit ---
    def create_kit(self, payload, headers):
        return self._request("POST", "/api/kits", payload, headers=headers)

    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/api/kits/{kit_id}", headers=headers)

    # --- LongarmMachine ---
    def create_longarm_machine(self, payload, headers):
        return self._request("POST", "/api/longarm-machines", payload, headers=headers)

    def get_longarm_machine(self, machine_id, headers):
        return self._request("GET", f"/api/longarm-machines/{machine_id}", headers=headers)

    # --- LongarmJob ---
    def create_longarm_job(self, payload, headers):
        return self._request("POST", "/api/longarm-jobs", payload, headers=headers)

    def list_longarm_jobs(self, headers, params=None):
        return self._request("GET", "/api/longarm-jobs", headers=headers, params=params)

    def get_longarm_job(self, job_id, headers):
        return self._request("GET", f"/api/longarm-jobs/{job_id}", headers=headers)

    def start_longarm_job(self, job_id, payload, headers):
        return self._request("POST", f"/api/longarm-jobs/{job_id}/start", payload, headers=headers)

    def complete_longarm_job(self, job_id, payload, headers):
        return self._request("POST", f"/api/longarm-jobs/{job_id}/complete", payload, headers=headers)

    # --- ClassEvent ---
    def create_class(self, payload, headers):
        return self._request("POST", "/api/classes", payload, headers=headers)

    def get_class(self, class_id, headers):
        return self._request("GET", f"/api/classes/{class_id}", headers=headers)

    def cancel_class(self, class_id, headers):
        return self._request("POST", f"/api/classes/{class_id}/cancel", {}, headers=headers)

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/api/enrollments", payload, headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/api/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/api/enrollments/{enrollment_id}", headers=headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/cancel", {}, headers=headers)

    # --- SpecialOrder ---
    def create_special_order(self, payload, headers):
        return self._request("POST", "/api/special-orders", payload, headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/api/special-orders", headers=headers, params=params)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/api/special-orders/{order_id}", headers=headers)

    def revise_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/special-orders/{order_id}/revise-quote", payload, headers=headers)

    def fulfill_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/special-orders/{order_id}/fulfill", payload, headers=headers)


api_client = ApiClient()
