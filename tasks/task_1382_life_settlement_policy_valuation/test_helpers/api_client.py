"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # per-test-server isolation SIGKILLs and respawns the server before
        # every test; a keep-alive pool can then hand a stale connection to
        # the next request (RemoteDisconnected / ConnectionResetError on
        # non-idempotent POSTs). Connection: close forces a fresh TCP
        # connection per request, eliminating the race.
        self.session.headers["Connection"] = "close"

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Brokers / investors / insureds / policies / licenses ---
    def create_broker(self, payload, headers):
        return self._request("POST", "/api/brokers", payload, headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/api/brokers/{broker_id}", headers=headers)

    def list_broker_cases(self, broker_id, headers, params=None):
        return self._request("GET", f"/api/brokers/{broker_id}/cases", headers=headers, params=params)

    def list_broker_insureds(self, broker_id, headers, params=None):
        return self._request("GET", f"/api/brokers/{broker_id}/insureds", headers=headers, params=params)

    def list_broker_disbursements(self, broker_id, headers, params=None):
        return self._request("GET", f"/api/brokers/{broker_id}/disbursements", headers=headers, params=params)

    def create_investor(self, payload, headers):
        return self._request("POST", "/api/investors", payload, headers)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/api/investors/{investor_id}", headers=headers)

    def create_insured(self, payload, headers):
        return self._request("POST", "/api/insureds", payload, headers)

    def get_insured(self, insured_id, headers):
        return self._request("GET", f"/api/insureds/{insured_id}", headers=headers)

    def list_insured_policies(self, insured_id, headers, params=None):
        return self._request("GET", f"/api/insureds/{insured_id}/policies", headers=headers, params=params)

    def create_policy(self, payload, headers):
        return self._request("POST", "/api/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/api/policies/{policy_id}", headers=headers)

    def patch_policy(self, policy_id, payload, headers):
        return self._request("PATCH", f"/api/policies/{policy_id}", payload, headers)

    def list_policy_cases(self, policy_id, headers, params=None):
        return self._request("GET", f"/api/policies/{policy_id}/cases", headers=headers, params=params)

    def create_license(self, payload, headers):
        return self._request("POST", "/api/licenses", payload, headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/api/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/api/licenses/{license_id}", headers=headers)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/api/licenses/{license_id}/suspend", {}, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/api/licenses/{license_id}/reinstate", {}, headers)

    # --- Cases / screening / underwriting ---
    def create_case(self, payload, headers):
        return self._request("POST", "/api/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}", headers=headers)

    def submit_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/submit", {}, headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/withdraw", {}, headers)

    def create_screening(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/screenings", {}, headers)

    def list_screenings(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/screenings", headers=headers, params=params)

    def order_le_report(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/le-reports", payload, headers)

    def list_le_reports(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/le-reports", headers=headers, params=params)

    def deliver_le_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/le-reports/{report_id}/deliver", payload, headers)

    def get_le_report(self, report_id, headers):
        return self._request("GET", f"/api/le-reports/{report_id}", headers=headers)

    def uw_decision(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/uw-decision", payload, headers)

    def reunderwrite_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/reunderwrite", {}, headers)

    def deliver_disclosures(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/deliver-disclosures", payload, headers)

    # --- Offers / negotiation ---
    def create_offer(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/offers", payload, headers)

    def list_offers(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}", headers=headers)

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/counter", payload, headers)

    def respond_to_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/respond", payload, headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/accept", payload, headers)

    def reject_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/reject", {}, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/withdraw", {}, headers)

    # --- Closing packages / escrow / disbursements ---
    def get_case_closing_package(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}/closing-package", headers=headers)

    def list_closing_packages(self, headers, params=None):
        return self._request("GET", "/api/closing-packages", headers=headers, params=params)

    def get_closing_package(self, package_id, headers):
        return self._request("GET", f"/api/closing-packages/{package_id}", headers=headers)

    def send_for_signature(self, package_id, headers):
        return self._request("POST", f"/api/closing-packages/{package_id}/send-for-signature", {}, headers)

    def record_signature(self, package_id, payload, headers):
        return self._request("POST", f"/api/closing-packages/{package_id}/record-signature", payload, headers)

    def submit_review(self, package_id, headers):
        return self._request("POST", f"/api/closing-packages/{package_id}/submit-review", {}, headers)

    def return_deficiency(self, package_id, payload, headers):
        return self._request("POST", f"/api/closing-packages/{package_id}/return-deficiency", payload, headers)

    def approve_package(self, package_id, headers):
        return self._request("POST", f"/api/closing-packages/{package_id}/approve", {}, headers)

    def submit_carrier(self, package_id, headers):
        return self._request("POST", f"/api/closing-packages/{package_id}/submit-carrier", {}, headers)

    def confirm_ownership(self, package_id, headers):
        return self._request("POST", f"/api/closing-packages/{package_id}/confirm-ownership", {}, headers)

    def cancel_package(self, package_id, headers):
        return self._request("POST", f"/api/closing-packages/{package_id}/cancel", {}, headers)

    def get_case_escrow_account(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}/escrow-account", headers=headers)

    def get_escrow_account(self, escrow_id, headers):
        return self._request("GET", f"/api/escrow-accounts/{escrow_id}", headers=headers)

    def fund_escrow(self, escrow_id, payload, headers):
        return self._request("POST", f"/api/escrow-accounts/{escrow_id}/fund", payload, headers)

    def release_escrow(self, escrow_id, headers):
        return self._request("POST", f"/api/escrow-accounts/{escrow_id}/release", {}, headers)

    def rescind_escrow(self, escrow_id, headers):
        return self._request("POST", f"/api/escrow-accounts/{escrow_id}/rescind", {}, headers)

    def list_escrow_disbursements(self, escrow_id, headers, params=None):
        return self._request("GET", f"/api/escrow-accounts/{escrow_id}/disbursements", headers=headers, params=params)

    def mark_disbursement_paid(self, disbursement_id, headers):
        return self._request("POST", f"/api/disbursements/{disbursement_id}/mark-paid", {}, headers)

    # --- Portfolios / premium schedules / payments ---
    def create_portfolio(self, payload, headers):
        return self._request("POST", "/api/portfolios", payload, headers)

    def list_portfolios(self, headers, params=None):
        return self._request("GET", "/api/portfolios", headers=headers, params=params)

    def get_portfolio(self, portfolio_id, headers):
        return self._request("GET", f"/api/portfolios/{portfolio_id}", headers=headers)

    def list_portfolio_cases(self, portfolio_id, headers, params=None):
        return self._request("GET", f"/api/portfolios/{portfolio_id}/cases", headers=headers, params=params)

    def assign_portfolio(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/assign-portfolio", payload, headers)

    def create_premium_schedule(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/premium-schedules", payload, headers)

    def list_premium_schedules(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/premium-schedules", headers=headers, params=params)

    def get_premium_schedule(self, schedule_id, headers):
        return self._request("GET", f"/api/premium-schedules/{schedule_id}", headers=headers)

    def list_schedule_payments(self, schedule_id, headers, params=None):
        return self._request("GET", f"/api/premium-schedules/{schedule_id}/payments", headers=headers, params=params)

    def get_premium_payment(self, payment_id, headers):
        return self._request("GET", f"/api/premium-payments/{payment_id}", headers=headers)

    def pay_premium(self, payment_id, payload, headers):
        return self._request("POST", f"/api/premium-payments/{payment_id}/pay", payload, headers)

    # --- Tracking / death claims ---
    def create_tracking_event(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/tracking-events", payload, headers)

    def list_tracking_events(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/tracking-events", headers=headers, params=params)

    def verify_tracking_event(self, event_id, headers):
        return self._request("POST", f"/api/tracking-events/{event_id}/verify", {}, headers)

    def reject_tracking_event(self, event_id, headers):
        return self._request("POST", f"/api/tracking-events/{event_id}/reject", {}, headers)

    def create_death_claim(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/death-claims", payload, headers)

    def get_death_claim(self, claim_id, headers):
        return self._request("GET", f"/api/death-claims/{claim_id}", headers=headers)

    def list_case_death_claims(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/death-claims", headers=headers, params=params)

    def verify_death_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/death-claims/{claim_id}/verify", payload, headers)

    def file_death_claim(self, claim_id, headers):
        return self._request("POST", f"/api/death-claims/{claim_id}/file", {}, headers)

    def settle_death_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/death-claims/{claim_id}/settle", payload, headers)

    # --- Valuation snapshots ---
    def create_valuation_snapshot(self, portfolio_id, payload, headers):
        return self._request("POST", f"/api/portfolios/{portfolio_id}/valuation-snapshots", payload, headers)

    def list_valuation_snapshots(self, portfolio_id, headers, params=None):
        return self._request("GET", f"/api/portfolios/{portfolio_id}/valuation-snapshots", headers=headers, params=params)

    def get_valuation_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/api/valuation-snapshots/{snapshot_id}", headers=headers)

    def finalize_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/api/valuation-snapshots/{snapshot_id}/finalize", {}, headers)


api_client = ApiClient()
