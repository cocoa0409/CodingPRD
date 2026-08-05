"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # ---- NoiseLimitPolicy ----
    def create_noise_policy(self, payload, headers):
        return self._request("POST", "/noise-policies", payload, headers=headers)

    def list_noise_policies(self, headers, params=None):
        return self._request("GET", "/noise-policies", headers=headers, params=params)

    # ---- VariancePermit ----
    def create_variance_permit(self, payload, headers):
        return self._request("POST", "/variance-permits", payload, headers=headers)

    def list_variance_permits(self, headers, params=None):
        return self._request("GET", "/variance-permits", headers=headers, params=params)

    def get_variance_permit(self, variance_id, headers):
        return self._request("GET", f"/variance-permits/{variance_id}", headers=headers)

    def issue_variance_permit(self, variance_id, payload, headers):
        return self._request("POST", f"/variance-permits/{variance_id}/issue", payload, headers=headers)

    def deny_variance_permit(self, variance_id, payload, headers):
        return self._request("POST", f"/variance-permits/{variance_id}/deny", payload, headers=headers)

    def revoke_variance_permit(self, variance_id, payload, headers):
        return self._request("POST", f"/variance-permits/{variance_id}/revoke", payload, headers=headers)

    # ---- Complaint ----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def review_complaint(self, complaint_id, headers, payload=None):
        return self._request("POST", f"/complaints/{complaint_id}/review", payload or {}, headers=headers)

    def create_inspection(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/inspections", payload, headers=headers)

    def list_inspections(self, complaint_id, headers, params=None):
        return self._request("GET", f"/complaints/{complaint_id}/inspections", headers=headers, params=params)

    def substantiate_complaint(self, complaint_id, headers, payload=None):
        return self._request("POST", f"/complaints/{complaint_id}/substantiate", payload or {}, headers=headers)

    def dismiss_complaint(self, complaint_id, headers, payload=None):
        return self._request("POST", f"/complaints/{complaint_id}/dismiss", payload or {}, headers=headers)

    # ---- CrossAgencyReferral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def acknowledge_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/referrals/{referral_id}/acknowledge", payload or {}, headers=headers)

    def close_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/referrals/{referral_id}/close", payload or {}, headers=headers)

    # ---- Enforcement ----
    def list_enforcements(self, headers, params=None):
        return self._request("GET", "/enforcements", headers=headers, params=params)

    def get_enforcement(self, enforcement_id, headers):
        return self._request("GET", f"/enforcements/{enforcement_id}", headers=headers)

    def contest_enforcement(self, enforcement_id, headers, payload=None):
        return self._request("POST", f"/enforcements/{enforcement_id}/contest", payload or {}, headers=headers)

    def create_hearing(self, enforcement_id, payload, headers):
        return self._request("POST", f"/enforcements/{enforcement_id}/hearings", payload, headers=headers)

    def list_hearings(self, enforcement_id, headers, params=None):
        return self._request("GET", f"/enforcements/{enforcement_id}/hearings", headers=headers, params=params)

    def create_payment(self, enforcement_id, payload, headers):
        return self._request("POST", f"/enforcements/{enforcement_id}/payments", payload, headers=headers)

    def list_payments(self, enforcement_id, headers, params=None):
        return self._request("GET", f"/enforcements/{enforcement_id}/payments", headers=headers, params=params)

    # ---- Hearing ----
    def decide_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/decide", payload, headers=headers)

    # ---- AbatementOrder ----
    def create_abatement_order(self, payload, headers):
        return self._request("POST", "/abatement-orders", payload, headers=headers)

    def list_abatement_orders(self, headers, params=None):
        return self._request("GET", "/abatement-orders", headers=headers, params=params)

    def get_abatement_order(self, abatement_id, headers):
        return self._request("GET", f"/abatement-orders/{abatement_id}", headers=headers)

    def comply_abatement_order(self, abatement_id, headers, payload=None):
        return self._request("POST", f"/abatement-orders/{abatement_id}/comply", payload or {}, headers=headers)

    def escalate_abatement_order(self, abatement_id, headers, payload=None):
        return self._request("POST", f"/abatement-orders/{abatement_id}/escalate", payload or {}, headers=headers)


api_client = ApiClient()
