"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- districts ---
    def create_district(self, payload, headers):
        return self._request("POST", "/districts", payload, headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/districts", headers=headers, params=params)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}", headers=headers)

    def abandon_district(self, district_id, headers):
        return self._request("POST", f"/districts/{district_id}/abandon", {}, headers)

    def close_objection_window(self, district_id, headers):
        return self._request("POST", f"/districts/{district_id}/close-objection-window", {}, headers)

    def complete_construction(self, district_id, headers):
        return self._request("POST", f"/districts/{district_id}/complete-construction", {}, headers)

    def finalize_true_up(self, district_id, headers):
        return self._request("POST", f"/districts/{district_id}/finalize-true-up", {}, headers)

    def billing_run(self, district_id, headers):
        return self._request("POST", f"/districts/{district_id}/billing-run", {}, headers)

    def accept_district(self, district_id, headers):
        return self._request("POST", f"/districts/{district_id}/accept", {}, headers)

    def list_district_parcels(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/parcels", headers=headers, params=params)

    def list_district_petitions(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}/petitions", headers=headers)

    def list_district_cost_estimates(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}/cost-estimates", headers=headers)

    def list_district_assessments(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/parcel-assessments", headers=headers, params=params)

    def list_district_hearings(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}/hearings", headers=headers)

    def list_district_objections(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}/objections", headers=headers)

    def list_district_resolutions(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}/resolutions", headers=headers)

    def list_district_phases(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}/construction-phases", headers=headers)

    def list_district_change_orders(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}/change-orders", headers=headers)

    def list_district_invoices(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/invoices", headers=headers, params=params)

    # --- property owners ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def list_owner_parcels(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}/parcels", headers=headers)

    def list_owner_signatures(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}/signatures", headers=headers)

    def list_owner_objections(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}/objections", headers=headers)

    # --- parcels ---
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcel_signatures(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}/signatures", headers=headers)

    def list_parcel_assessments(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}/assessments", headers=headers)

    def list_parcel_objections(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}/objections", headers=headers)

    # --- petitions / signatures ---
    def create_petition(self, payload, headers):
        return self._request("POST", "/petitions", payload, headers)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/petitions/{petition_id}", headers=headers)

    def close_petition(self, petition_id, headers):
        return self._request("POST", f"/petitions/{petition_id}/close", {}, headers)

    def list_petition_signatures(self, petition_id, headers):
        return self._request("GET", f"/petitions/{petition_id}/signatures", headers=headers)

    def create_signature(self, payload, headers):
        return self._request("POST", "/signatures", payload, headers)

    def get_signature(self, signature_id, headers):
        return self._request("GET", f"/signatures/{signature_id}", headers=headers)

    def verify_signature(self, signature_id, headers):
        return self._request("POST", f"/signatures/{signature_id}/verify", {}, headers)

    def reject_signature(self, signature_id, payload, headers):
        return self._request("POST", f"/signatures/{signature_id}/reject", payload, headers)

    def withdraw_signature(self, signature_id, headers):
        return self._request("POST", f"/signatures/{signature_id}/withdraw", {}, headers)

    # --- cost estimates ---
    def create_cost_estimate(self, payload, headers):
        return self._request("POST", "/cost-estimates", payload, headers)

    def get_cost_estimate(self, estimate_id, headers):
        return self._request("GET", f"/cost-estimates/{estimate_id}", headers=headers)

    def approve_cost_estimate(self, estimate_id, headers):
        return self._request("POST", f"/cost-estimates/{estimate_id}/approve", {}, headers)

    # --- hearings ---
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def record_hearing_held(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/record-held", {}, headers)

    def list_hearing_objections(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}/objections", headers=headers)

    # --- objections ---
    def create_objection(self, payload, headers):
        return self._request("POST", "/objections", payload, headers)

    def get_objection(self, objection_id, headers):
        return self._request("GET", f"/objections/{objection_id}", headers=headers)

    def start_objection_review(self, objection_id, headers):
        return self._request("POST", f"/objections/{objection_id}/start-review", {}, headers)

    def sustain_objection(self, objection_id, headers):
        return self._request("POST", f"/objections/{objection_id}/sustain", {}, headers)

    def overrule_objection(self, objection_id, headers):
        return self._request("POST", f"/objections/{objection_id}/overrule", {}, headers)

    def withdraw_objection(self, objection_id, headers):
        return self._request("POST", f"/objections/{objection_id}/withdraw", {}, headers)

    # --- council resolutions ---
    def create_resolution(self, payload, headers):
        return self._request("POST", "/resolutions", payload, headers)

    def get_resolution(self, resolution_id, headers):
        return self._request("GET", f"/resolutions/{resolution_id}", headers=headers)

    # --- parcel assessments ---
    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/parcel-assessments/{assessment_id}", headers=headers)

    def select_payment_option(self, assessment_id, payload, headers):
        return self._request("POST", f"/parcel-assessments/{assessment_id}/select-payment-option", payload, headers)

    def payoff_quote(self, assessment_id, headers):
        return self._request("POST", f"/parcel-assessments/{assessment_id}/payoff-quote", {}, headers)

    def refund_credit(self, assessment_id, payload, headers):
        return self._request("POST", f"/parcel-assessments/{assessment_id}/refund-credit", payload, headers)

    def list_assessment_invoices(self, assessment_id, headers):
        return self._request("GET", f"/parcel-assessments/{assessment_id}/invoices", headers=headers)

    def list_assessment_payments(self, assessment_id, headers):
        return self._request("GET", f"/parcel-assessments/{assessment_id}/payments", headers=headers)

    # --- construction phases ---
    def create_construction_phase(self, payload, headers):
        return self._request("POST", "/construction-phases", payload, headers)

    def get_construction_phase(self, phase_id, headers):
        return self._request("GET", f"/construction-phases/{phase_id}", headers=headers)

    def start_phase(self, phase_id, headers):
        return self._request("POST", f"/construction-phases/{phase_id}/start", {}, headers)

    def complete_phase(self, phase_id, headers):
        return self._request("POST", f"/construction-phases/{phase_id}/complete", {}, headers)

    def cancel_phase(self, phase_id, headers):
        return self._request("POST", f"/construction-phases/{phase_id}/cancel", {}, headers)

    def list_phase_change_orders(self, phase_id, headers):
        return self._request("GET", f"/construction-phases/{phase_id}/change-orders", headers=headers)

    # --- change orders ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def approve_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/approve", {}, headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/reject", {}, headers)

    # --- invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    # --- payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)


api_client = ApiClient()
