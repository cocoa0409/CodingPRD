"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Employer ----
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def list_employer_policies(self, employer_id, headers, params=None):
        return self._request("GET", f"/employers/{employer_id}/policies", headers=headers, params=params)

    def list_employer_workers(self, employer_id, headers, params=None):
        return self._request("GET", f"/employers/{employer_id}/workers", headers=headers, params=params)

    def list_employer_experience_mods(self, employer_id, headers, params=None):
        return self._request("GET", f"/employers/{employer_id}/experience-mods", headers=headers, params=params)

    # ---- Policy ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    # ---- Worker ----
    def create_worker(self, payload, headers):
        return self._request("POST", "/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/workers/{worker_id}", headers=headers)

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def accept_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/accept", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reopen", {}, headers)

    def reserve_adjustment(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reserve-adjustments", payload, headers)

    # ---- InjuryReport (FROI/SROI EDI) ----
    def create_injury_report(self, payload, headers):
        return self._request("POST", "/injury-reports", payload, headers)

    def get_injury_report(self, report_id, headers):
        return self._request("GET", f"/injury-reports/{report_id}", headers=headers)

    def list_claim_injury_reports(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/injury-reports", headers=headers, params=params)

    def transmit_injury_report(self, report_id, headers):
        return self._request("POST", f"/injury-reports/{report_id}/transmit", {}, headers)

    def ack_injury_report(self, report_id, headers):
        return self._request("POST", f"/injury-reports/{report_id}/ack", {}, headers)

    def reject_injury_report(self, report_id, payload, headers):
        return self._request("POST", f"/injury-reports/{report_id}/reject", payload, headers)

    # ---- WageStatement ----
    def create_wage_statement(self, payload, headers):
        return self._request("POST", "/wage-statements", payload, headers)

    def list_claim_wage_statements(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/wage-statements", headers=headers, params=params)

    # ---- Reserve ----
    def create_reserve(self, payload, headers):
        return self._request("POST", "/reserves", payload, headers)

    def get_reserve(self, reserve_id, headers):
        return self._request("GET", f"/reserves/{reserve_id}", headers=headers)

    def list_claim_reserves(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/reserves", headers=headers, params=params)

    def create_medical_payment(self, reserve_id, payload, headers):
        return self._request("POST", f"/reserves/{reserve_id}/medical-payments", payload, headers)

    # ---- BenefitPayment ----
    def create_benefit_payment(self, payload, headers):
        return self._request("POST", "/benefit-payments", payload, headers)

    def get_benefit_payment(self, payment_id, headers):
        return self._request("GET", f"/benefit-payments/{payment_id}", headers=headers)

    def list_claim_benefit_payments(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/benefit-payments", headers=headers, params=params)

    def list_benefit_payments(self, headers, params=None):
        return self._request("GET", "/benefit-payments", headers=headers, params=params)

    def void_benefit_payment(self, payment_id, headers):
        return self._request("POST", f"/benefit-payments/{payment_id}/void", {}, headers)

    # ---- ImpairmentRating (MMI) ----
    def create_impairment_rating(self, payload, headers):
        return self._request("POST", "/impairment-ratings", payload, headers)

    def get_impairment_rating(self, rating_id, headers):
        return self._request("GET", f"/impairment-ratings/{rating_id}", headers=headers)

    def list_claim_impairment_ratings(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/impairment-ratings", headers=headers, params=params)

    def dispute_impairment_rating(self, rating_id, headers):
        return self._request("POST", f"/impairment-ratings/{rating_id}/dispute", {}, headers)

    def finalize_impairment_rating(self, rating_id, headers):
        return self._request("POST", f"/impairment-ratings/{rating_id}/finalize", {}, headers)

    # ---- ReturnToWorkOffer ----
    def create_rtw_offer(self, payload, headers):
        return self._request("POST", "/rtw-offers", payload, headers)

    def get_rtw_offer(self, offer_id, headers):
        return self._request("GET", f"/rtw-offers/{offer_id}", headers=headers)

    def list_claim_rtw_offers(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/rtw-offers", headers=headers, params=params)

    def accept_rtw_offer(self, offer_id, headers):
        return self._request("POST", f"/rtw-offers/{offer_id}/accept", {}, headers)

    def decline_rtw_offer(self, offer_id, headers):
        return self._request("POST", f"/rtw-offers/{offer_id}/decline", {}, headers)

    # ---- IMEOrder ----
    def create_ime_order(self, payload, headers):
        return self._request("POST", "/ime-orders", payload, headers)

    def get_ime_order(self, ime_id, headers):
        return self._request("GET", f"/ime-orders/{ime_id}", headers=headers)

    def list_claim_ime_orders(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/ime-orders", headers=headers, params=params)

    def complete_ime_order(self, ime_id, headers):
        return self._request("POST", f"/ime-orders/{ime_id}/complete", {}, headers)

    def no_show_ime_order(self, ime_id, headers):
        return self._request("POST", f"/ime-orders/{ime_id}/no-show", {}, headers)

    def cancel_ime_order(self, ime_id, headers):
        return self._request("POST", f"/ime-orders/{ime_id}/cancel", {}, headers)

    # ---- ExperienceModEntry (EMR) ----
    def create_experience_mod(self, payload, headers):
        return self._request("POST", "/experience-mods", payload, headers)

    def get_experience_mod(self, mod_id, headers):
        return self._request("GET", f"/experience-mods/{mod_id}", headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
