"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Creator ---
    def create_creator(self, payload, headers):
        return self._request("POST", "/creators", payload, headers)

    def list_creators(self, headers, params=None):
        return self._request("GET", "/creators", headers=headers, params=params)

    def get_creator(self, creator_id, headers):
        return self._request("GET", f"/creators/{creator_id}", headers=headers)

    def patch_creator_metrics(self, creator_id, payload, headers):
        return self._request(
            "PATCH", f"/creators/{creator_id}/metrics", payload, headers
        )

    def transition_creator(self, creator_id, payload, headers):
        return self._request(
            "POST", f"/creators/{creator_id}/transition", payload, headers
        )

    # --- Brand ---
    def create_brand(self, payload, headers):
        return self._request("POST", "/brands", payload, headers)

    def list_brands(self, headers, params=None):
        return self._request("GET", "/brands", headers=headers, params=params)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def patch_brand(self, brand_id, payload, headers):
        return self._request("PATCH", f"/brands/{brand_id}", payload, headers)

    # --- Brief ---
    def create_brief(self, payload, headers):
        return self._request("POST", "/briefs", payload, headers)

    def list_briefs(self, headers, params=None):
        return self._request("GET", "/briefs", headers=headers, params=params)

    def get_brief(self, brief_id, headers):
        return self._request("GET", f"/briefs/{brief_id}", headers=headers)

    def publish_brief(self, brief_id, headers):
        return self._request("POST", f"/briefs/{brief_id}/publish", {}, headers)

    def close_brief(self, brief_id, headers):
        return self._request("POST", f"/briefs/{brief_id}/close", {}, headers)

    def list_brief_pitches(self, brief_id, headers, params=None):
        return self._request(
            "GET", f"/briefs/{brief_id}/pitches", headers=headers, params=params
        )

    def create_pitch(self, brief_id, payload, headers):
        return self._request("POST", f"/briefs/{brief_id}/pitches", payload, headers)

    # --- Pitch ---
    def list_pitches(self, headers, params=None):
        return self._request("GET", "/pitches", headers=headers, params=params)

    def get_pitch(self, pitch_id, headers):
        return self._request("GET", f"/pitches/{pitch_id}", headers=headers)

    def pitch_brand_action(self, pitch_id, payload, headers):
        return self._request(
            "POST", f"/pitches/{pitch_id}/brand-action", payload, headers
        )

    def pitch_talent_action(self, pitch_id, payload, headers):
        return self._request(
            "POST", f"/pitches/{pitch_id}/talent-action", payload, headers
        )

    # --- Deal ---
    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def propose_terms(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/propose-terms", payload, headers
        )

    def creator_respond(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/creator-respond", payload, headers
        )

    def brand_respond(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/brand-respond", payload, headers
        )

    def terminate_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/terminate", payload, headers)

    def create_dispute(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/disputes", payload, headers)

    # --- Deliverable ---
    def create_deliverable(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/deliverables", payload, headers)

    def list_deal_deliverables(self, deal_id, headers, params=None):
        return self._request(
            "GET", f"/deals/{deal_id}/deliverables", headers=headers, params=params
        )

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    def submit_deliverable(self, deliverable_id, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/submit", {}, headers
        )

    def review_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/review", payload, headers
        )

    def publish_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/publish", payload, headers
        )

    def list_deliverable_disclosure_checks(self, deliverable_id, headers, params=None):
        return self._request(
            "GET",
            f"/deliverables/{deliverable_id}/disclosure-checks",
            headers=headers,
            params=params,
        )

    def list_deliverable_reshoots(self, deliverable_id, headers, params=None):
        return self._request(
            "GET", f"/deliverables/{deliverable_id}/reshoots",
            headers=headers, params=params,
        )

    def create_reshoot(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/reshoots", payload, headers
        )

    # --- DisclosureCheck ---
    def review_disclosure_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/disclosure-checks/{check_id}/review", payload, headers
        )

    def requeue_disclosure_check(self, check_id, headers):
        return self._request(
            "POST", f"/disclosure-checks/{check_id}/requeue", {}, headers
        )

    # --- PerformanceReport ---
    def create_performance_report(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/performance-reports", payload, headers
        )

    def list_deal_performance_reports(self, deal_id, headers, params=None):
        return self._request(
            "GET", f"/deals/{deal_id}/performance-reports",
            headers=headers, params=params,
        )

    def finalize_performance_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/performance-reports/{report_id}/finalize", payload, headers
        )

    # --- Invoice ---
    def create_invoice(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/invoices", {}, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/record-payment", payload, headers
        )

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)

    # --- Payout ---
    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/release", {}, headers)

    def hold_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/hold", {}, headers)

    def unhold_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/unhold", {}, headers)

    # --- Dispute ---
    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/review", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", payload, headers
        )

    # --- Reshoot ---
    def list_reshoots(self, headers, params=None):
        return self._request("GET", "/reshoots", headers=headers, params=params)

    def get_reshoot(self, reshoot_id, headers):
        return self._request("GET", f"/reshoots/{reshoot_id}", headers=headers)

    def respond_reshoot(self, reshoot_id, payload, headers):
        return self._request("POST", f"/reshoots/{reshoot_id}/respond", payload, headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
