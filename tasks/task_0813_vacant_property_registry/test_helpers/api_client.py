"""API client: one method per endpoint defined in the registry PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock administration ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/registry/_clock/set_current_utc", payload, headers)

    # --- Registrants ---
    def create_registrant(self, payload, headers):
        return self._request("POST", "/registry/registrants", payload, headers)

    # --- Properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/registry/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/registry/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/registry/properties", headers=headers, params=params)

    def renew_property(self, property_id, payload, headers):
        return self._request("POST", f"/registry/properties/{property_id}/renew", payload, headers)

    def foreclosure_property(self, property_id, payload, headers):
        return self._request("POST", f"/registry/properties/{property_id}/foreclosure", payload, headers)

    def demolish_property(self, property_id, headers, payload=None):
        return self._request("POST", f"/registry/properties/{property_id}/demolish", payload or {}, headers)

    def get_property_ledger(self, property_id, headers, params=None):
        return self._request("GET", f"/registry/properties/{property_id}/ledger", headers=headers, params=params)

    # --- Maintenance standards ---
    def create_maintenance_standard(self, payload, headers):
        return self._request("POST", "/registry/maintenance-standards", payload, headers)

    def list_maintenance_standards(self, headers, params=None):
        return self._request("GET", "/registry/maintenance-standards", headers=headers, params=params)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/registry/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/registry/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/registry/inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/registry/inspections/{inspection_id}/complete", payload, headers)

    # --- Violations ---
    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/registry/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/registry/violations", headers=headers, params=params)

    def transition_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/registry/violations/{violation_id}/transition", payload, headers)

    def assess_fine(self, violation_id, headers, payload=None):
        return self._request("POST", f"/registry/violations/{violation_id}/fines", payload or {}, headers)

    # --- Fines ---
    def get_fine(self, fine_id, headers):
        return self._request("GET", f"/registry/fines/{fine_id}", headers=headers)

    def list_fines(self, headers, params=None):
        return self._request("GET", "/registry/fines", headers=headers, params=params)

    def transition_fine(self, fine_id, payload, headers):
        return self._request("POST", f"/registry/fines/{fine_id}/transition", payload, headers)

    def resolve_dispute(self, fine_id, payload, headers):
        return self._request("POST", f"/registry/fines/{fine_id}/resolve-dispute", payload, headers)

    def record_lien(self, fine_id, headers, payload=None):
        return self._request("POST", f"/registry/fines/{fine_id}/record-lien", payload or {}, headers)

    # --- Liens ---
    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/registry/liens/{lien_id}", headers=headers)

    def list_liens(self, headers, params=None):
        return self._request("GET", "/registry/liens", headers=headers, params=params)

    def pay_lien(self, lien_id, headers, payload=None):
        return self._request("POST", f"/registry/liens/{lien_id}/pay", payload or {}, headers)

    def foreclose_lien(self, lien_id, headers, payload=None):
        return self._request("POST", f"/registry/liens/{lien_id}/foreclose", payload or {}, headers)

    # --- Abatement orders ---
    def create_abatement_order(self, property_id, payload, headers):
        return self._request("POST", f"/registry/properties/{property_id}/abatement-orders", payload, headers)

    def list_abatement_orders(self, property_id, headers, params=None):
        return self._request("GET", f"/registry/properties/{property_id}/abatement-orders", headers=headers, params=params)

    def complete_abatement_order(self, abatement_order_id, payload, headers):
        return self._request("POST", f"/registry/abatement-orders/{abatement_order_id}/complete", payload, headers)

    # --- Receivership referrals ---
    def create_receivership_referral(self, property_id, payload, headers):
        return self._request("POST", f"/registry/properties/{property_id}/receivership-referrals", payload, headers)

    def list_receivership_referrals(self, property_id, headers, params=None):
        return self._request("GET", f"/registry/properties/{property_id}/receivership-referrals", headers=headers, params=params)

    def decide_receivership_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/registry/receivership-referrals/{referral_id}/decide", payload, headers)

    # --- Demolition listings ---
    def create_demolition_listing(self, payload, headers):
        return self._request("POST", "/registry/demolition-listings", payload, headers)

    def list_demolition_listings(self, property_id, headers, params=None):
        return self._request("GET", f"/registry/properties/{property_id}/demolition-listings", headers=headers, params=params)

    def schedule_demolition_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/registry/demolition-listings/{listing_id}/schedule", payload, headers)

    # --- Reporting ---
    def get_registry_summary(self, headers, params=None):
        return self._request("GET", "/registry/reports/registry-summary", headers=headers, params=params)


api_client = ApiClient()
