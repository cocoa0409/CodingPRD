"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Organizers ---
    def create_organizer(self, payload, headers):
        return self._request("POST", "/organizers", payload, headers)

    def get_organizer(self, organizer_id, headers):
        return self._request("GET", f"/organizers/{organizer_id}", headers=headers)

    def list_organizer_petitions(self, organizer_id, headers, params=None):
        return self._request("GET", f"/organizers/{organizer_id}/petitions", headers=headers, params=params)

    def list_organizer_applications(self, organizer_id, headers, params=None):
        return self._request("GET", f"/organizers/{organizer_id}/permit-applications", headers=headers, params=params)

    def inject_organizer_forfeiture(self, payload, headers):
        return self._request("POST", "/_inject/organizer_forfeiture", payload, headers)

    # --- Street segments ---
    def create_street_segment(self, payload, headers):
        return self._request("POST", "/street-segments", payload, headers)

    def get_street_segment(self, segment_id, headers):
        return self._request("GET", f"/street-segments/{segment_id}", headers=headers)

    def list_segment_petitions(self, segment_id, headers, params=None):
        return self._request("GET", f"/street-segments/{segment_id}/petitions", headers=headers, params=params)

    def list_segment_applications(self, segment_id, headers, params=None):
        return self._request("GET", f"/street-segments/{segment_id}/permit-applications", headers=headers, params=params)

    # --- Logical clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Petitions ---
    def create_petition(self, payload, headers):
        return self._request("POST", "/petitions", payload, headers)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/petitions/{petition_id}", headers=headers)

    def add_signature(self, petition_id, payload, headers):
        return self._request("POST", f"/petitions/{petition_id}/signatures", payload, headers)

    def list_signatures(self, petition_id, headers, params=None):
        return self._request("GET", f"/petitions/{petition_id}/signatures", headers=headers, params=params)

    def withdraw_signature(self, petition_id, signature_id, headers):
        return self._request("POST", f"/petitions/{petition_id}/signatures/{signature_id}/withdraw", {}, headers)

    def submit_petition(self, petition_id, headers):
        return self._request("POST", f"/petitions/{petition_id}/submit", {}, headers)

    def verify_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/petitions/{petition_id}/verify", payload, headers)

    def cure_petition(self, petition_id, headers):
        return self._request("POST", f"/petitions/{petition_id}/cure", {}, headers)

    def list_petition_applications(self, petition_id, headers, params=None):
        return self._request("GET", f"/petitions/{petition_id}/permit-applications", headers=headers, params=params)

    # --- Permit applications ---
    def create_permit_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers)

    def list_permit_applications(self, headers, params=None):
        return self._request("GET", "/permit-applications", headers=headers, params=params)

    def get_permit_application(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}", headers=headers)

    def patch_permit_application(self, application_id, payload, headers):
        return self._request("PATCH", f"/permit-applications/{application_id}", payload, headers)

    def submit_permit_application(self, application_id, headers):
        return self._request("POST", f"/permit-applications/{application_id}/submit", {}, headers)

    def approve_permit_application(self, application_id, headers):
        return self._request("POST", f"/permit-applications/{application_id}/approve", {}, headers)

    def deny_permit_application(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/deny", payload, headers)

    def issue_permit_application(self, application_id, headers):
        return self._request("POST", f"/permit-applications/{application_id}/issue", {}, headers)

    def cancel_permit_application(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/cancel", payload, headers)

    def revoke_permit_application(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/revoke", payload, headers)

    def complete_permit_application(self, application_id, headers):
        return self._request("POST", f"/permit-applications/{application_id}/complete", {}, headers)

    # --- Traffic control plans ---
    def create_traffic_control_plan(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/traffic-control-plans", payload, headers)

    def list_traffic_control_plans(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}/traffic-control-plans", headers=headers)

    def get_traffic_control_plan(self, plan_id, headers):
        return self._request("GET", f"/traffic-control-plans/{plan_id}", headers=headers)

    def patch_traffic_control_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/traffic-control-plans/{plan_id}", payload, headers)

    def submit_traffic_control_plan(self, plan_id, headers):
        return self._request("POST", f"/traffic-control-plans/{plan_id}/submit", {}, headers)

    def review_traffic_control_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/traffic-control-plans/{plan_id}/review", payload, headers)

    # --- Sound plans ---
    def create_sound_plan(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/sound-plans", payload, headers)

    def list_sound_plans(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}/sound-plans", headers=headers)

    def get_sound_plan(self, plan_id, headers):
        return self._request("GET", f"/sound-plans/{plan_id}", headers=headers)

    def submit_sound_plan(self, plan_id, headers):
        return self._request("POST", f"/sound-plans/{plan_id}/submit", {}, headers)

    def review_sound_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/sound-plans/{plan_id}/review", payload, headers)

    # --- Insurance certificates ---
    def create_insurance_certificate(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/insurance-certificates", payload, headers)

    def list_insurance_certificates(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}/insurance-certificates", headers=headers)

    def get_insurance_certificate(self, certificate_id, headers):
        return self._request("GET", f"/insurance-certificates/{certificate_id}", headers=headers)

    def review_insurance_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/insurance-certificates/{certificate_id}/review", payload, headers)

    # --- Equipment stocks ---
    def create_equipment_stock(self, payload, headers):
        return self._request("POST", "/equipment-stocks", payload, headers)

    def list_equipment_stocks(self, headers, params=None):
        return self._request("GET", "/equipment-stocks", headers=headers, params=params)

    def get_equipment_stock(self, stock_id, headers):
        return self._request("GET", f"/equipment-stocks/{stock_id}", headers=headers)

    def list_stock_reservations(self, stock_id, headers, params=None):
        return self._request("GET", f"/equipment-stocks/{stock_id}/equipment-reservations", headers=headers, params=params)

    # --- Equipment reservations ---
    def create_equipment_reservation(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/equipment-reservations", payload, headers)

    def list_equipment_reservations(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}/equipment-reservations", headers=headers)

    def get_equipment_reservation(self, reservation_id, headers):
        return self._request("GET", f"/equipment-reservations/{reservation_id}", headers=headers)

    def cancel_equipment_reservation(self, reservation_id, headers):
        return self._request("POST", f"/equipment-reservations/{reservation_id}/cancel", {}, headers)

    def pay_equipment_reservation(self, reservation_id, headers):
        return self._request("POST", f"/equipment-reservations/{reservation_id}/pay", {}, headers)

    def waive_equipment_reservation(self, reservation_id, headers):
        return self._request("POST", f"/equipment-reservations/{reservation_id}/waive", {}, headers)

    def dispatch_equipment_reservation(self, reservation_id, headers):
        return self._request("POST", f"/equipment-reservations/{reservation_id}/dispatch", {}, headers)

    def return_equipment_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/equipment-reservations/{reservation_id}/return", payload, headers)

    def verify_return_equipment_reservation(self, reservation_id, headers):
        return self._request("POST", f"/equipment-reservations/{reservation_id}/verify-return", {}, headers)

    # --- Cost-share pools / contributions ---
    def create_cost_share_pool(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/cost-share-pools", payload, headers)

    def list_cost_share_pools(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}/cost-share-pools", headers=headers)

    def get_cost_share_pool(self, pool_id, headers):
        return self._request("GET", f"/cost-share-pools/{pool_id}", headers=headers)

    def create_contribution(self, pool_id, payload, headers):
        return self._request("POST", f"/cost-share-pools/{pool_id}/contributions", payload, headers)

    def list_contributions(self, pool_id, headers, params=None):
        return self._request("GET", f"/cost-share-pools/{pool_id}/contributions", headers=headers, params=params)

    def close_cost_share_pool(self, pool_id, headers):
        return self._request("POST", f"/cost-share-pools/{pool_id}/close", {}, headers)

    # --- Deposits / charge entries ---
    def create_deposit(self, application_id, headers):
        return self._request("POST", f"/permit-applications/{application_id}/deposits", {}, headers)

    def list_deposits(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}/deposits", headers=headers)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def settle_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/settle", {}, headers)

    def list_deposit_charges(self, deposit_id, headers, params=None):
        return self._request("GET", f"/deposits/{deposit_id}/charges", headers=headers, params=params)

    # --- Post-event reports ---
    def create_post_event_report(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/post-event-reports", payload, headers)

    def list_post_event_reports(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}/post-event-reports", headers=headers)

    def get_post_event_report(self, report_id, headers):
        return self._request("GET", f"/post-event-reports/{report_id}", headers=headers)

    def inspect_post_event_report(self, report_id, payload, headers):
        return self._request("POST", f"/post-event-reports/{report_id}/inspect", payload, headers)


api_client = ApiClient()
