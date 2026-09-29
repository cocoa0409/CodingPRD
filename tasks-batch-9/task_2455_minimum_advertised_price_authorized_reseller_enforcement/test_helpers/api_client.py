"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock --
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # ----------------------------------------------------- pricing policies --
    def create_pricing_policy(self, payload, headers):
        return self._request("POST", "/pricing-policies", payload, headers=headers)

    def submit_policy_review(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/pricing-policies/{policy_id}/submit-review", payload or {}, headers=headers
        )

    def decide_policy_review(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/pricing-policies/{policy_id}/review-decision", payload, headers=headers
        )

    def publish_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/pricing-policies/{policy_id}/publish", payload, headers=headers
        )

    def withdraw_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/pricing-policies/{policy_id}/withdraw", payload, headers=headers
        )

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/pricing-policies/{policy_id}", headers=headers)

    def list_pricing_policies(self, headers, params=None):
        return self._request("GET", "/pricing-policies", headers=headers, params=params)

    # -------------------------------------------------------------- products --
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers=headers)

    def adjust_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers=headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_effective_floor(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/products/{product_id}/effective-floor", headers=headers, params=params
        )

    # ---------------------------------------------------------- distributors --
    def create_distributor(self, payload, headers):
        return self._request("POST", "/distributors", payload, headers=headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/distributors/{distributor_id}", headers=headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", "/distributors", headers=headers, params=params)

    def get_diversion_exposure(self, distributor_id, headers, params=None):
        return self._request(
            "GET",
            f"/distributors/{distributor_id}/diversion-exposure",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------- resellers --
    def create_reseller(self, payload, headers):
        return self._request("POST", "/resellers", payload, headers=headers)

    def set_supply_status(self, reseller_id, payload, headers):
        return self._request(
            "POST", f"/resellers/{reseller_id}/supply-status", payload, headers=headers
        )

    def get_reseller(self, reseller_id, headers):
        return self._request("GET", f"/resellers/{reseller_id}", headers=headers)

    def list_resellers(self, headers, params=None):
        return self._request("GET", "/resellers", headers=headers, params=params)

    def get_compliance_summary(self, reseller_id, headers, params=None):
        return self._request(
            "GET", f"/resellers/{reseller_id}/compliance-summary", headers=headers, params=params
        )

    # --------------------------------------------------- reseller agreements --
    def create_agreement(self, payload, headers):
        return self._request("POST", "/reseller-agreements", payload, headers=headers)

    def send_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/reseller-agreements/{agreement_id}/send", payload or {}, headers=headers
        )

    def respond_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/reseller-agreements/{agreement_id}/respond", payload, headers=headers
        )

    def activate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/reseller-agreements/{agreement_id}/activate", payload or {}, headers=headers
        )

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/reseller-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/reseller-agreements", headers=headers, params=params)

    # ------------------------------------------------------ price observations --
    def create_observation(self, payload, headers):
        return self._request("POST", "/price-observations", payload, headers=headers)

    def evaluate_observation(self, observation_id, headers, payload=None):
        return self._request(
            "POST", f"/price-observations/{observation_id}/evaluate", payload or {}, headers=headers
        )

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"/price-observations/{observation_id}", headers=headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", "/price-observations", headers=headers, params=params)

    # ------------------------------------------------------------ violations --
    def submit_cure(self, violation_id, payload, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/cure-submission", payload, headers=headers
        )

    def dispute_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/dispute", payload, headers=headers
        )

    def decide_violation_dispute(self, violation_id, payload, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/dispute-decision", payload, headers=headers
        )

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    # --------------------------------------------------- enforcement notices --
    def issue_notice(self, payload, headers):
        return self._request("POST", "/enforcement-notices", payload, headers=headers)

    def acknowledge_notice(self, notice_id, headers, payload=None):
        return self._request(
            "POST", f"/enforcement-notices/{notice_id}/acknowledge", payload or {}, headers=headers
        )

    def rescind_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/enforcement-notices/{notice_id}/rescind", payload, headers=headers
        )

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/enforcement-notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/enforcement-notices", headers=headers, params=params)

    # ---------------------------------------------------- pricing exceptions --
    def create_exception(self, payload, headers):
        return self._request("POST", "/pricing-exceptions", payload, headers=headers)

    def decide_exception(self, exception_id, payload, headers):
        return self._request(
            "POST", f"/pricing-exceptions/{exception_id}/decision", payload, headers=headers
        )

    def get_exception(self, exception_id, headers):
        return self._request("GET", f"/pricing-exceptions/{exception_id}", headers=headers)

    def list_exceptions(self, headers, params=None):
        return self._request("GET", "/pricing-exceptions", headers=headers, params=params)

    # ----------------------------------------------------------- serial units --
    def create_serial_unit(self, payload, headers):
        return self._request("POST", "/serial-units", payload, headers=headers)

    def ship_downstream(self, serial_unit_id, payload, headers):
        return self._request(
            "POST", f"/serial-units/{serial_unit_id}/ship-downstream", payload, headers=headers
        )

    def get_serial_unit(self, serial_unit_id, headers):
        return self._request("GET", f"/serial-units/{serial_unit_id}", headers=headers)

    def list_serial_units(self, headers, params=None):
        return self._request("GET", "/serial-units", headers=headers, params=params)

    # -------------------------------------------------------- test purchases --
    def create_test_purchase(self, payload, headers):
        return self._request("POST", "/test-purchases", payload, headers=headers)

    def capture_serial(self, test_purchase_id, payload, headers):
        return self._request(
            "POST", f"/test-purchases/{test_purchase_id}/serial-capture", payload, headers=headers
        )

    def confirm_outcome(self, test_purchase_id, payload, headers):
        return self._request(
            "POST", f"/test-purchases/{test_purchase_id}/confirm-outcome", payload, headers=headers
        )

    def get_test_purchase(self, test_purchase_id, headers):
        return self._request("GET", f"/test-purchases/{test_purchase_id}", headers=headers)

    def list_test_purchases(self, headers, params=None):
        return self._request("GET", "/test-purchases", headers=headers, params=params)

    # ------------------------------------------------ distributor chargebacks --
    def assess_chargeback(self, payload, headers):
        return self._request("POST", "/distributor-chargebacks", payload, headers=headers)

    def dispute_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/distributor-chargebacks/{chargeback_id}/dispute", payload, headers=headers
        )

    def decide_chargeback_dispute(self, chargeback_id, payload, headers):
        return self._request(
            "POST",
            f"/distributor-chargebacks/{chargeback_id}/dispute-decision",
            payload,
            headers=headers,
        )

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/distributor-chargebacks/{chargeback_id}", headers=headers)

    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/distributor-chargebacks", headers=headers, params=params)

    # ------------------------------------------------------------- sweep ------
    def run_sweep(self, headers, payload=None):
        return self._request("POST", "/enforcement-sweeps", payload or {}, headers=headers)


api_client = ApiClient()
