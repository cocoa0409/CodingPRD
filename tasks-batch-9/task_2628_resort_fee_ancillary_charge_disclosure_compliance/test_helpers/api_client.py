"""API client: one method per endpoint declared by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def get_clock(self, headers=None):
        return self._request("GET", "/_clock", headers=headers)

    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- jurisdictions ----------------
    def create_jurisdiction(self, payload, headers=None):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers=None):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdictions(self, headers=None, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    # ---------------- taxability rules ----------------
    def create_taxability_rule(self, payload, headers=None):
        return self._request("POST", "/taxability-rules", payload, headers)

    def get_taxability_rule(self, rule_id, headers=None):
        return self._request("GET", f"/taxability-rules/{rule_id}", headers=headers)

    def list_taxability_rules(self, headers=None, params=None):
        return self._request("GET", "/taxability-rules", headers=headers, params=params)

    # ---------------- properties ----------------
    def create_property(self, payload, headers=None):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers=None):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers=None, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_disclosure_summary(self, property_id, headers=None):
        return self._request(
            "GET", f"/properties/{property_id}/disclosure-summary", headers=headers
        )

    # ---------------- channels ----------------
    def create_channel(self, payload, headers=None):
        return self._request("POST", "/channels", payload, headers)

    def get_channel(self, channel_id, headers=None):
        return self._request("GET", f"/channels/{channel_id}", headers=headers)

    def list_channels(self, headers=None, params=None):
        return self._request("GET", "/channels", headers=headers, params=params)

    # ---------------- fee programs ----------------
    def create_fee_program(self, payload, headers=None):
        return self._request("POST", "/fee-programs", payload, headers)

    def get_fee_program(self, program_id, headers=None):
        return self._request("GET", f"/fee-programs/{program_id}", headers=headers)

    def list_fee_programs(self, headers=None, params=None):
        return self._request("GET", "/fee-programs", headers=headers, params=params)

    def submit_fee_program_for_review(self, program_id, headers=None):
        return self._request(
            "POST", f"/fee-programs/{program_id}/submit-review", {}, headers
        )

    def publish_fee_program(self, program_id, attestation_note, headers=None):
        return self._request(
            "POST",
            f"/fee-programs/{program_id}/publish",
            {"attestation_note": attestation_note},
            headers,
        )

    # ---------------- fees and inclusions ----------------
    def create_fee(self, program_id, payload, headers=None):
        return self._request("POST", f"/fee-programs/{program_id}/fees", payload, headers)

    def get_fee(self, fee_id, headers=None):
        return self._request("GET", f"/fees/{fee_id}", headers=headers)

    def list_fees(self, headers=None, params=None):
        return self._request("GET", "/fees", headers=headers, params=params)

    def create_fee_inclusion(self, fee_id, payload, headers=None):
        return self._request("POST", f"/fees/{fee_id}/inclusions", payload, headers)

    def list_fee_inclusions(self, fee_id, headers=None, params=None):
        return self._request(
            "GET", f"/fees/{fee_id}/inclusions", headers=headers, params=params
        )

    # ---------------- channel disclosure profiles ----------------
    def create_channel_disclosure_profile(self, payload, headers=None):
        return self._request("POST", "/channel-disclosure-profiles", payload, headers)

    def get_channel_disclosure_profile(self, profile_id, headers=None):
        return self._request(
            "GET", f"/channel-disclosure-profiles/{profile_id}", headers=headers
        )

    def list_channel_disclosure_profiles(self, headers=None, params=None):
        return self._request(
            "GET", "/channel-disclosure-profiles", headers=headers, params=params
        )

    def deploy_profile(self, profile_id, headers=None):
        return self._request(
            "POST", f"/channel-disclosure-profiles/{profile_id}/deploy", {}, headers
        )

    def audit_profile(self, profile_id, headers=None):
        return self._request(
            "POST", f"/channel-disclosure-profiles/{profile_id}/audit", {}, headers
        )

    def remediate_profile(self, profile_id, payload, headers=None):
        return self._request(
            "POST",
            f"/channel-disclosure-profiles/{profile_id}/remediate",
            payload,
            headers,
        )

    def confirm_remediation(self, profile_id, headers=None):
        return self._request(
            "POST",
            f"/channel-disclosure-profiles/{profile_id}/confirm-remediation",
            {},
            headers,
        )

    # ---------------- bookings ----------------
    def create_booking(self, payload, headers=None):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers=None):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers=None, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers=None):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def check_in_booking(self, booking_id, headers=None):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def check_out_booking(self, booking_id, headers=None):
        return self._request("POST", f"/bookings/{booking_id}/check-out", {}, headers)

    def list_booking_folios(self, booking_id, headers=None, params=None):
        return self._request(
            "GET", f"/bookings/{booking_id}/folios", headers=headers, params=params
        )

    # ---------------- folios ----------------
    def get_folio(self, folio_id, headers=None):
        return self._request("GET", f"/folios/{folio_id}", headers=headers)

    def list_folios(self, headers=None, params=None):
        return self._request("GET", "/folios", headers=headers, params=params)

    def itemize_folio(self, folio_id, headers=None):
        return self._request("POST", f"/folios/{folio_id}/itemize", {}, headers)

    def post_folio(self, folio_id, headers=None):
        return self._request("POST", f"/folios/{folio_id}/post", {}, headers)

    def close_folio(self, folio_id, headers=None):
        return self._request("POST", f"/folios/{folio_id}/close", {}, headers)

    # ---------------- folio lines ----------------
    def get_folio_line(self, folio_line_id, headers=None):
        return self._request("GET", f"/folio-lines/{folio_line_id}", headers=headers)

    def list_folio_lines(self, headers=None, params=None):
        return self._request("GET", "/folio-lines", headers=headers, params=params)

    # ---------------- opt-out requests ----------------
    def create_opt_out_request(self, booking_id, fee_id, headers=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/opt-out-requests", {"fee_id": fee_id}, headers
        )

    def get_opt_out_request(self, opt_out_id, headers=None):
        return self._request("GET", f"/opt-out-requests/{opt_out_id}", headers=headers)

    def list_opt_out_requests(self, headers=None, params=None):
        return self._request("GET", "/opt-out-requests", headers=headers, params=params)

    def grant_opt_out_request(self, opt_out_id, headers=None):
        return self._request("POST", f"/opt-out-requests/{opt_out_id}/grant", {}, headers)

    def deny_opt_out_request(self, opt_out_id, denial_reason_code, headers=None):
        return self._request(
            "POST",
            f"/opt-out-requests/{opt_out_id}/deny",
            {"denial_reason_code": denial_reason_code},
            headers,
        )

    def revoke_opt_out_request(self, opt_out_id, headers=None):
        return self._request("POST", f"/opt-out-requests/{opt_out_id}/revoke", {}, headers)

    # ---------------- guest complaints ----------------
    def create_guest_complaint(self, booking_id, payload, headers=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/guest-complaints", payload, headers
        )

    def get_guest_complaint(self, complaint_id, headers=None):
        return self._request("GET", f"/guest-complaints/{complaint_id}", headers=headers)

    def list_guest_complaints(self, headers=None, params=None):
        return self._request("GET", "/guest-complaints", headers=headers, params=params)

    def investigate_complaint(self, complaint_id, headers=None):
        return self._request(
            "POST", f"/guest-complaints/{complaint_id}/investigate", {}, headers
        )

    def substantiate_complaint(self, complaint_id, headers=None):
        return self._request(
            "POST", f"/guest-complaints/{complaint_id}/substantiate", {}, headers
        )

    def dismiss_complaint(self, complaint_id, dismissal_reason_code, headers=None):
        return self._request(
            "POST",
            f"/guest-complaints/{complaint_id}/dismiss",
            {"dismissal_reason_code": dismissal_reason_code},
            headers,
        )

    def refund_complaint(self, complaint_id, refund_amount_cents, headers=None):
        return self._request(
            "POST",
            f"/guest-complaints/{complaint_id}/refund",
            {"refund_amount_cents": refund_amount_cents},
            headers,
        )

    # ---------------- regulator inquiries ----------------
    def create_regulator_inquiry(self, payload, headers=None):
        return self._request("POST", "/regulator-inquiries", payload, headers)

    def get_regulator_inquiry(self, inquiry_id, headers=None):
        return self._request("GET", f"/regulator-inquiries/{inquiry_id}", headers=headers)

    def list_regulator_inquiries(self, headers=None, params=None):
        return self._request("GET", "/regulator-inquiries", headers=headers, params=params)

    def draft_inquiry_response(self, inquiry_id, response_summary, headers=None):
        return self._request(
            "POST",
            f"/regulator-inquiries/{inquiry_id}/draft-response",
            {"response_summary": response_summary},
            headers,
        )

    def submit_inquiry_response(self, inquiry_id, headers=None):
        return self._request(
            "POST", f"/regulator-inquiries/{inquiry_id}/submit-response", {}, headers
        )

    def require_inquiry_remediation(self, inquiry_id, remediation_directive, headers=None):
        return self._request(
            "POST",
            f"/regulator-inquiries/{inquiry_id}/require-remediation",
            {"remediation_directive": remediation_directive},
            headers,
        )

    def submit_inquiry_remediation(self, inquiry_id, remediation_summary, headers=None):
        return self._request(
            "POST",
            f"/regulator-inquiries/{inquiry_id}/submit-remediation",
            {"remediation_summary": remediation_summary},
            headers,
        )

    def reject_inquiry_remediation(self, inquiry_id, rejection_reason, headers=None):
        return self._request(
            "POST",
            f"/regulator-inquiries/{inquiry_id}/reject-remediation",
            {"rejection_reason": rejection_reason},
            headers,
        )

    def accept_inquiry(self, inquiry_id, headers=None):
        return self._request(
            "POST", f"/regulator-inquiries/{inquiry_id}/accept", {}, headers
        )

    def withdraw_inquiry(self, inquiry_id, withdrawal_reason, headers=None):
        return self._request(
            "POST",
            f"/regulator-inquiries/{inquiry_id}/withdraw",
            {"withdrawal_reason": withdrawal_reason},
            headers,
        )

    # ---------------- revenue impact models ----------------
    def create_revenue_impact_model(self, payload, headers=None):
        return self._request("POST", "/revenue-impact-models", payload, headers)

    def get_revenue_impact_model(self, model_id, headers=None):
        return self._request("GET", f"/revenue-impact-models/{model_id}", headers=headers)

    def list_revenue_impact_models(self, headers=None, params=None):
        return self._request(
            "GET", "/revenue-impact-models", headers=headers, params=params
        )


api_client = ApiClient()
