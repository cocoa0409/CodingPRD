"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock + seed fast-forwards ──────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def seed_scheduled_job(self, homeowner_id, headers):
        return self._request("POST", "/_seed/scheduled-job",
                             {"homeowner_id": homeowner_id}, headers)

    def seed_warranted_job(self, homeowner_id, headers):
        return self._request("POST", "/_seed/warranted-job",
                             {"homeowner_id": homeowner_id}, headers)

    # ─── Homeowner ────────────────────────────────────────────────────────
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"/homeowners/{homeowner_id}", headers=headers)

    # ─── Crew ─────────────────────────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # ─── Job ──────────────────────────────────────────────────────────────
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def mark_lost(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/mark-lost", headers=headers)

    def pay_cash(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/pay-cash", headers=headers)

    def create_install_order(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/install-orders", payload, headers)

    def issue_warranty(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/warranty", payload, headers)

    def close_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/close", headers=headers)

    # ─── Inspection ───────────────────────────────────────────────────────
    def create_inspection(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def finalize_inspection(self, job_id, inspection_id, headers):
        return self._request(
            "POST", f"/jobs/{job_id}/inspections/{inspection_id}/finalize", headers=headers)

    # ─── Quote ────────────────────────────────────────────────────────────
    def create_quote(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", headers=headers)

    def revise_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/revise", payload, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", payload, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/decline", headers=headers)

    def expire_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/expire", headers=headers)

    # ─── FinancingApplication ─────────────────────────────────────────────
    def create_financing_application(self, payload, headers):
        return self._request("POST", "/financing-applications", payload, headers)

    def get_financing_application(self, app_id, headers):
        return self._request("GET", f"/financing-applications/{app_id}", headers=headers)

    def list_financing_applications(self, headers, params=None):
        return self._request("GET", "/financing-applications", headers=headers, params=params)

    def decide_financing(self, app_id, payload, headers):
        return self._request("POST", f"/financing-applications/{app_id}/decide", payload, headers)

    def withdraw_financing(self, app_id, headers):
        return self._request("POST", f"/financing-applications/{app_id}/withdraw", headers=headers)

    # ─── InstallOrder ─────────────────────────────────────────────────────
    def get_install_order(self, install_order_id, headers):
        return self._request("GET", f"/install-orders/{install_order_id}", headers=headers)

    def list_install_orders(self, headers, params=None):
        return self._request("GET", "/install-orders", headers=headers, params=params)

    def dispatch_install_order(self, install_order_id, headers):
        return self._request("POST", f"/install-orders/{install_order_id}/dispatch", headers=headers)

    def start_install_order(self, install_order_id, headers):
        return self._request("POST", f"/install-orders/{install_order_id}/start", headers=headers)

    def inspect_pass_install_order(self, install_order_id, headers):
        return self._request(
            "POST", f"/install-orders/{install_order_id}/inspect-pass", headers=headers)

    def inspect_fail_install_order(self, install_order_id, headers):
        return self._request(
            "POST", f"/install-orders/{install_order_id}/inspect-fail", headers=headers)

    def complete_install_order(self, install_order_id, payload, headers):
        return self._request(
            "POST", f"/install-orders/{install_order_id}/complete", payload, headers)

    def cancel_install_order(self, install_order_id, headers):
        return self._request("POST", f"/install-orders/{install_order_id}/cancel", headers=headers)

    # ─── CrewBooking ──────────────────────────────────────────────────────
    def create_crew_booking(self, payload, headers):
        return self._request("POST", "/crew-bookings", payload, headers)

    def get_crew_booking(self, booking_id, headers):
        return self._request("GET", f"/crew-bookings/{booking_id}", headers=headers)

    def list_crew_bookings(self, headers, params=None):
        return self._request("GET", "/crew-bookings", headers=headers, params=params)

    def confirm_crew_booking(self, booking_id, headers):
        return self._request("POST", f"/crew-bookings/{booking_id}/confirm", headers=headers)

    def release_crew_booking(self, booking_id, headers):
        return self._request("POST", f"/crew-bookings/{booking_id}/release", headers=headers)

    # ─── Warranty ─────────────────────────────────────────────────────────
    def get_warranty(self, warranty_id, headers):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def list_warranties(self, headers, params=None):
        return self._request("GET", "/warranties", headers=headers, params=params)

    def transfer_warranty(self, warranty_id, payload, headers):
        return self._request("POST", f"/warranties/{warranty_id}/transfer", payload, headers)

    def void_warranty(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/void", headers=headers)

    def lapse_warranty(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/lapse", headers=headers)

    # ─── ServiceVisit ─────────────────────────────────────────────────────
    def create_service_visit(self, warranty_id, payload, headers):
        return self._request(
            "POST", f"/warranties/{warranty_id}/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/service-visits/{visit_id}", headers=headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/service-visits", headers=headers, params=params)

    def complete_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/complete", headers=headers)

    def cancel_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/cancel", headers=headers)

    # ─── Claim ────────────────────────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def triage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/triage", payload, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reopen", headers=headers)

    # ─── FoundationReferral ───────────────────────────────────────────────
    def create_foundation_referral(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/foundation-referrals", payload, headers)

    def get_foundation_referral(self, referral_id, headers):
        return self._request("GET", f"/foundation-referrals/{referral_id}", headers=headers)

    def list_foundation_referrals(self, headers, params=None):
        return self._request("GET", "/foundation-referrals", headers=headers, params=params)

    def send_foundation_referral(self, referral_id, headers):
        return self._request("POST", f"/foundation-referrals/{referral_id}/send", headers=headers)

    def resolve_foundation_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/foundation-referrals/{referral_id}/resolve", payload, headers)


api_client = ApiClient()
