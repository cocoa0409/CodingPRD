"""API client: one method per endpoint defined in the PRD (all under /greenpower)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/greenpower/_clock/set_current_utc", payload, headers)

    # --- Generators ---
    def create_generator(self, payload, headers):
        return self._request("POST", "/greenpower/generators", payload, headers)

    def list_generators(self, headers, params=None):
        return self._request("GET", "/greenpower/generators", headers=headers, params=params)

    def get_generator(self, generator_id, headers):
        return self._request("GET", f"/greenpower/generators/{generator_id}", headers=headers)

    def patch_generator(self, generator_id, payload, headers):
        return self._request("PATCH", f"/greenpower/generators/{generator_id}", payload, headers)

    def submit_generator_verification(self, generator_id, headers):
        return self._request(
            "POST", f"/greenpower/generators/{generator_id}/submit-verification", {}, headers
        )

    def verify_generator(self, generator_id, headers):
        return self._request("POST", f"/greenpower/generators/{generator_id}/verify", {}, headers)

    def reject_generator_verification(self, generator_id, payload, headers):
        return self._request(
            "POST", f"/greenpower/generators/{generator_id}/reject-verification", payload, headers
        )

    def suspend_generator(self, generator_id, headers):
        return self._request("POST", f"/greenpower/generators/{generator_id}/suspend", {}, headers)

    def reinstate_generator(self, generator_id, headers):
        return self._request("POST", f"/greenpower/generators/{generator_id}/reinstate", {}, headers)

    def decommission_generator(self, generator_id, headers):
        return self._request(
            "POST", f"/greenpower/generators/{generator_id}/decommission", {}, headers
        )

    def mint_run(self, generator_id, headers):
        return self._request("POST", f"/greenpower/generators/{generator_id}/mint-run", {}, headers)

    # --- Meter readings ---
    def create_meter_reading(self, payload, headers):
        return self._request("POST", "/greenpower/meter-readings", payload, headers)

    def list_meter_readings(self, headers, params=None):
        return self._request("GET", "/greenpower/meter-readings", headers=headers, params=params)

    def get_meter_reading(self, reading_id, headers):
        return self._request("GET", f"/greenpower/meter-readings/{reading_id}", headers=headers)

    def attest_reading(self, reading_id, headers):
        return self._request("POST", f"/greenpower/meter-readings/{reading_id}/attest", {}, headers)

    def reject_reading(self, reading_id, payload, headers):
        return self._request("POST", f"/greenpower/meter-readings/{reading_id}/reject", payload, headers)

    def resubmit_reading(self, reading_id, headers):
        return self._request("POST", f"/greenpower/meter-readings/{reading_id}/resubmit", {}, headers)

    def accept_reading(self, reading_id, headers):
        return self._request("POST", f"/greenpower/meter-readings/{reading_id}/accept", {}, headers)

    def void_reading(self, reading_id, payload, headers):
        return self._request("POST", f"/greenpower/meter-readings/{reading_id}/void", payload, headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/greenpower/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/greenpower/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/greenpower/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/greenpower/accounts/{account_id}/suspend", {}, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/greenpower/accounts/{account_id}/reinstate", {}, headers)

    # --- Certificates ---
    def list_certificates(self, headers, params=None):
        return self._request("GET", "/greenpower/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/greenpower/certificates/{certificate_id}", headers=headers)

    def revoke_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/greenpower/certificates/{certificate_id}/revoke", payload, headers
        )

    def transfer_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/greenpower/certificates/{certificate_id}/transfer", payload, headers
        )

    # --- Trades ---
    def create_trade(self, payload, headers):
        return self._request("POST", "/greenpower/trades", payload, headers)

    def list_trades(self, headers, params=None):
        return self._request("GET", "/greenpower/trades", headers=headers, params=params)

    def get_trade(self, trade_id, headers):
        return self._request("GET", f"/greenpower/trades/{trade_id}", headers=headers)

    def accept_trade(self, trade_id, headers):
        return self._request("POST", f"/greenpower/trades/{trade_id}/accept", {}, headers)

    def settle_trade(self, trade_id, headers):
        return self._request("POST", f"/greenpower/trades/{trade_id}/settle", {}, headers)

    def cancel_trade(self, trade_id, headers):
        return self._request("POST", f"/greenpower/trades/{trade_id}/cancel", {}, headers)

    def expire_trade(self, trade_id, headers):
        return self._request("POST", f"/greenpower/trades/{trade_id}/expire", {}, headers)

    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/greenpower/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/greenpower/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/greenpower/programs/{program_id}", headers=headers)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/greenpower/programs/{program_id}", payload, headers)

    def open_program(self, program_id, headers):
        return self._request("POST", f"/greenpower/programs/{program_id}/open", {}, headers)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/greenpower/programs/{program_id}/archive", {}, headers)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/greenpower/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/greenpower/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/greenpower/subscriptions/{subscription_id}", headers=headers)

    def activate_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/greenpower/subscriptions/{subscription_id}/activate", {}, headers
        )

    def suspend_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/greenpower/subscriptions/{subscription_id}/suspend", {}, headers
        )

    def reinstate_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/greenpower/subscriptions/{subscription_id}/reinstate", {}, headers
        )

    def terminate_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/greenpower/subscriptions/{subscription_id}/terminate", {}, headers
        )

    # --- Bills ---
    def create_bill(self, payload, headers):
        return self._request("POST", "/greenpower/bills", payload, headers)

    def list_bills(self, headers, params=None):
        return self._request("GET", "/greenpower/bills", headers=headers, params=params)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/greenpower/bills/{bill_id}", headers=headers)

    def issue_bill(self, bill_id, headers):
        return self._request("POST", f"/greenpower/bills/{bill_id}/issue", {}, headers)

    def dispute_bill(self, bill_id, payload, headers):
        return self._request("POST", f"/greenpower/bills/{bill_id}/dispute", payload, headers)

    def reissue_bill(self, bill_id, payload, headers):
        return self._request("POST", f"/greenpower/bills/{bill_id}/reissue", payload, headers)

    def void_bill(self, bill_id, headers):
        return self._request("POST", f"/greenpower/bills/{bill_id}/void", {}, headers)

    # --- Retirements ---
    def create_retirement(self, payload, headers):
        return self._request("POST", "/greenpower/retirements", payload, headers)

    def list_retirements(self, headers, params=None):
        return self._request("GET", "/greenpower/retirements", headers=headers, params=params)

    def get_retirement(self, retirement_id, headers):
        return self._request("GET", f"/greenpower/retirements/{retirement_id}", headers=headers)

    # --- Compliance obligations ---
    def create_obligation(self, payload, headers):
        return self._request("POST", "/greenpower/compliance-obligations", payload, headers)

    def list_obligations(self, headers, params=None):
        return self._request(
            "GET", "/greenpower/compliance-obligations", headers=headers, params=params
        )

    def get_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"/greenpower/compliance-obligations/{obligation_id}", headers=headers
        )

    def patch_obligation(self, obligation_id, payload, headers):
        return self._request(
            "PATCH", f"/greenpower/compliance-obligations/{obligation_id}", payload, headers
        )

    def close_obligation(self, obligation_id, headers):
        return self._request(
            "POST", f"/greenpower/compliance-obligations/{obligation_id}/close", {}, headers
        )

    # --- Claim reports ---
    def create_claim_report(self, payload, headers):
        return self._request("POST", "/greenpower/claim-reports", payload, headers)

    def list_claim_reports(self, headers, params=None):
        return self._request("GET", "/greenpower/claim-reports", headers=headers, params=params)

    def get_claim_report(self, report_id, headers):
        return self._request("GET", f"/greenpower/claim-reports/{report_id}", headers=headers)

    def submit_claim_report(self, report_id, headers):
        return self._request("POST", f"/greenpower/claim-reports/{report_id}/submit", {}, headers)

    def accept_claim_report(self, report_id, headers):
        return self._request("POST", f"/greenpower/claim-reports/{report_id}/accept", {}, headers)

    def reject_claim_report(self, report_id, payload, headers):
        return self._request("POST", f"/greenpower/claim-reports/{report_id}/reject", payload, headers)

    def revise_claim_report(self, report_id, headers):
        return self._request("POST", f"/greenpower/claim-reports/{report_id}/revise", {}, headers)


api_client = ApiClient()
