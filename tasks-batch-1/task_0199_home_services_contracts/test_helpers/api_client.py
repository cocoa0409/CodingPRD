"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the /home-services prefix (PRD §1).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/home-services"


class ApiClient(GenericApiClient):
    # ---- ServicePlan ----
    def create_service_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/service-plans/{plan_id}", headers=headers)

    def list_service_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-plans", headers=headers, params=params)

    def retire_service_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/service-plans/{plan_id}/retire", {}, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    # ---- Site ----
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def list_site_equipment(self, site_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites/{site_id}/equipment", headers=headers, params=params)

    # ---- Equipment ----
    def create_equipment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"{PREFIX}/equipment/{equipment_id}", headers=headers)

    def flag_service_equipment(self, equipment_id, headers):
        return self._request("POST", f"{PREFIX}/equipment/{equipment_id}/flag-service", {}, headers)

    def clear_service_equipment(self, equipment_id, headers):
        return self._request("POST", f"{PREFIX}/equipment/{equipment_id}/clear-service", {}, headers)

    def decommission_equipment(self, equipment_id, headers):
        return self._request("POST", f"{PREFIX}/equipment/{equipment_id}/decommission", {}, headers)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"{PREFIX}/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/technicians", headers=headers, params=params)

    # ---- Membership ----
    def create_membership(self, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships", headers=headers, params=params)

    def activate_membership(self, membership_id, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/activate", {}, headers)

    def suspend_membership(self, membership_id, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/suspend", {}, headers)

    def reinstate_membership(self, membership_id, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/reinstate", {}, headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/cancel", {}, headers)

    def create_renewal_offer(self, membership_id, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/renewal-offers", payload, headers)

    def list_membership_renewal_offers(self, membership_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}/renewal-offers", headers=headers, params=params)

    def list_membership_service_visits(self, membership_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}/service-visits", headers=headers, params=params)

    # ---- RenewalOffer ----
    def get_renewal_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/renewal-offers/{offer_id}", headers=headers)

    def list_renewal_offers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/renewal-offers", headers=headers, params=params)

    def accept_renewal_offer(self, offer_id, headers):
        return self._request("POST", f"{PREFIX}/renewal-offers/{offer_id}/accept", {}, headers)

    def decline_renewal_offer(self, offer_id, headers):
        return self._request("POST", f"{PREFIX}/renewal-offers/{offer_id}/decline", {}, headers)

    # ---- ServiceVisit ----
    def create_service_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"{PREFIX}/service-visits/{visit_id}", headers=headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-visits", headers=headers, params=params)

    def reschedule_service_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/reschedule", payload, headers)

    def dispatch_service_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/dispatch", payload, headers)

    def recall_service_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/recall", {}, headers)

    def depart_service_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/depart", {}, headers)

    def arrive_service_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/arrive", {}, headers)

    def complete_service_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/complete", {}, headers)

    def cancel_service_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/cancel", {}, headers)

    def mark_no_show_service_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/mark-no-show", {}, headers)

    # ---- RefrigerantLog ----
    def post_refrigerant_log(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/refrigerant-logs", payload, headers)

    def list_visit_refrigerant_logs(self, visit_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-visits/{visit_id}/refrigerant-logs", headers=headers, params=params)

    def get_refrigerant_log(self, log_id, headers):
        return self._request("GET", f"{PREFIX}/refrigerant-logs/{log_id}", headers=headers)

    def list_refrigerant_logs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/refrigerant-logs", headers=headers, params=params)

    # ---- PartUsage ----
    def post_part_usage(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-visits/{visit_id}/part-usages", payload, headers)

    def list_visit_part_usages(self, visit_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-visits/{visit_id}/part-usages", headers=headers, params=params)

    # ---- WarrantyClaim ----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warranty-claims", headers=headers, params=params)

    def start_review_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/start-review", {}, headers)

    def approve_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/approve", payload, headers)

    def deny_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/deny", payload, headers)

    def settle_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/settle", {}, headers)

    # ---- Administrative test clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def advance_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/advance", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
