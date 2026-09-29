"""
One method per endpoint of the Win-Loss Intelligence API.

All resources are flat, root-level collections mounted directly at the API root
and joined by foreign keys; the Program record is the scoping root of the domain
but is not a URL prefix, so a sampling frame, an interview or a battlecard is
addressed by its own identifier.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class WinLossApiClient(GenericApiClient):
    """Endpoint-per-method client for the Win-Loss Intelligence API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------

    def create_program(self, payload, headers) -> requests.Response:
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}", None, headers)

    def activate_program(self, program_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/programs/{program_id}/activate", payload or {}, headers
        )

    def begin_closing_program(self, program_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/programs/{program_id}/begin-closing", payload or {}, headers
        )

    def close_program(self, program_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/programs/{program_id}/close", payload or {}, headers
        )

    def replace_incentive_budget(self, program_id, payload, headers) -> requests.Response:
        return self._request(
            "PUT", f"/programs/{program_id}/incentive-budget", payload, headers
        )

    def replace_interview_guide(self, program_id, payload, headers) -> requests.Response:
        return self._request(
            "PUT", f"/programs/{program_id}/interview-guide", payload, headers
        )

    def list_program_competitors(self, program_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/programs/{program_id}/competitors", params, headers
        )

    def list_program_analysts(self, program_id, headers, params=None) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}/analysts", params, headers)

    def list_program_sampling_frames(
        self, program_id, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"/programs/{program_id}/sampling-frames", params, headers
        )

    def get_loss_trends(self, program_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/programs/{program_id}/loss-trends", params, headers
        )

    def run_enablement_sweep(self, program_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/programs/{program_id}/enablement-sweep", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Competitors
    # ------------------------------------------------------------------

    def create_competitor(self, payload, headers) -> requests.Response:
        return self._request("POST", "/competitors", payload, headers)

    def get_competitor(self, competitor_id, headers) -> requests.Response:
        return self._request("GET", f"/competitors/{competitor_id}", None, headers)

    def archive_competitor(self, competitor_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/competitors/{competitor_id}/archive", payload or {}, headers
        )

    def list_competitors(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/competitors", params, headers)

    # ------------------------------------------------------------------
    # Deals
    # ------------------------------------------------------------------

    def create_deal(self, payload, headers) -> requests.Response:
        return self._request("POST", "/deals", payload, headers)

    def get_deal(self, deal_id, headers) -> requests.Response:
        return self._request("GET", f"/deals/{deal_id}", None, headers)

    def list_deals(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/deals", params, headers)

    def patch_deal(self, deal_id, payload, headers) -> requests.Response:
        return self._request("PATCH", f"/deals/{deal_id}", payload, headers)

    def decline_selection(self, deal_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/deals/{deal_id}/decline-selection", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Analysts
    # ------------------------------------------------------------------

    def create_analyst(self, payload, headers) -> requests.Response:
        return self._request("POST", "/analysts", payload, headers)

    def get_analyst(self, analyst_id, headers) -> requests.Response:
        return self._request("GET", f"/analysts/{analyst_id}", None, headers)

    def deactivate_analyst(self, analyst_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/analysts/{analyst_id}/deactivate", payload or {}, headers
        )

    def list_analysts(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/analysts", params, headers)

    # ------------------------------------------------------------------
    # Buyer contacts
    # ------------------------------------------------------------------

    def create_buyer_contact(self, deal_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/deals/{deal_id}/buyer-contacts", payload, headers)

    def list_deal_buyer_contacts(self, deal_id, headers, params=None) -> requests.Response:
        return self._request("GET", f"/deals/{deal_id}/buyer-contacts", params, headers)

    def get_buyer_contact(self, contact_id, headers) -> requests.Response:
        return self._request("GET", f"/buyer-contacts/{contact_id}", None, headers)

    def record_consent(self, deal_id, contact_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"/deals/{deal_id}/buyer-contacts/{contact_id}/consent",
            payload,
            headers,
        )

    def list_buyer_contacts(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/buyer-contacts", params, headers)

    # ------------------------------------------------------------------
    # Sampling frames
    # ------------------------------------------------------------------

    def create_sampling_frame(self, payload, headers) -> requests.Response:
        return self._request("POST", "/sampling-frames", payload, headers)

    def get_sampling_frame(self, frame_id, headers) -> requests.Response:
        return self._request("GET", f"/sampling-frames/{frame_id}", None, headers)

    def seal_frame(self, frame_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/sampling-frames/{frame_id}/seal", payload or {}, headers
        )

    def draw_frame(self, frame_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/sampling-frames/{frame_id}/draw", payload, headers)

    def close_frame(self, frame_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/sampling-frames/{frame_id}/close", payload or {}, headers
        )

    def list_sampling_frames(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/sampling-frames", params, headers)

    # ------------------------------------------------------------------
    # Interviews
    # ------------------------------------------------------------------

    def create_interview(self, payload, headers) -> requests.Response:
        return self._request("POST", "/interviews", payload, headers)

    def get_interview(self, interview_id, headers) -> requests.Response:
        return self._request("GET", f"/interviews/{interview_id}", None, headers)

    def list_interviews(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/interviews", params, headers)

    def complete_interview(self, interview_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/interviews/{interview_id}/complete", payload, headers
        )

    def no_show_interview(self, interview_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/interviews/{interview_id}/no-show", payload or {}, headers
        )

    def reschedule_interview(self, interview_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/interviews/{interview_id}/reschedule", payload, headers
        )

    def cancel_interview(self, interview_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/interviews/{interview_id}/cancel", payload or {}, headers
        )

    def create_interview_response(self, interview_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/interviews/{interview_id}/responses", payload, headers
        )

    def list_interview_responses(self, interview_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/interviews/{interview_id}/responses", params, headers
        )

    def get_interview_response(self, response_id, headers) -> requests.Response:
        return self._request("GET", f"/interview-responses/{response_id}", None, headers)

    def list_interview_responses_flat(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/interview-responses", params, headers)

    # ------------------------------------------------------------------
    # Loss reasons
    # ------------------------------------------------------------------

    def create_loss_reason(self, payload, headers) -> requests.Response:
        return self._request("POST", "/loss-reasons", payload, headers)

    def get_loss_reason(self, reason_id, headers) -> requests.Response:
        return self._request("GET", f"/loss-reasons/{reason_id}", None, headers)

    def list_loss_reasons(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/loss-reasons", params, headers)

    def patch_loss_reason(self, reason_id, payload, headers) -> requests.Response:
        return self._request("PATCH", f"/loss-reasons/{reason_id}", payload, headers)

    def deprecate_loss_reason(self, reason_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/loss-reasons/{reason_id}/deprecate", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Loss attributions
    # ------------------------------------------------------------------

    def create_loss_attribution(self, payload, headers) -> requests.Response:
        return self._request("POST", "/loss-attributions", payload, headers)

    def get_loss_attribution(self, attribution_id, headers) -> requests.Response:
        return self._request("GET", f"/loss-attributions/{attribution_id}", None, headers)

    def list_loss_attributions(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/loss-attributions", params, headers)

    def ratify_loss_attribution(
        self, attribution_id, headers, payload=None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loss-attributions/{attribution_id}/ratify", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Battlecards
    # ------------------------------------------------------------------

    def create_battlecard(self, payload, headers) -> requests.Response:
        return self._request("POST", "/battlecards", payload, headers)

    def get_battlecard(self, battlecard_id, headers) -> requests.Response:
        return self._request("GET", f"/battlecards/{battlecard_id}", None, headers)

    def list_battlecards(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/battlecards", params, headers)

    def create_claim(self, battlecard_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/battlecards/{battlecard_id}/claims", payload, headers
        )

    def list_claims(self, battlecard_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/battlecards/{battlecard_id}/claims", params, headers
        )

    def legal_decision(self, battlecard_id, claim_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"/battlecards/{battlecard_id}/claims/{claim_id}/legal-decision",
            payload,
            headers,
        )

    def submit_legal(self, battlecard_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/battlecards/{battlecard_id}/submit-legal", payload or {}, headers
        )

    def publish_battlecard(self, battlecard_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/battlecards/{battlecard_id}/publish", payload or {}, headers
        )

    def reopen_battlecard(self, battlecard_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/battlecards/{battlecard_id}/reopen", payload or {}, headers
        )

    def list_battlecard_assignments(
        self, battlecard_id, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"/battlecards/{battlecard_id}/enablement-assignments", params, headers
        )

    def get_battlecard_claim(self, claim_id, headers) -> requests.Response:
        return self._request("GET", f"/battlecard-claims/{claim_id}", None, headers)

    def list_battlecard_claims(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/battlecard-claims", params, headers)

    # ------------------------------------------------------------------
    # Enablement assignments
    # ------------------------------------------------------------------

    def create_enablement_assignment(self, payload, headers) -> requests.Response:
        return self._request("POST", "/enablement-assignments", payload, headers)

    def get_enablement_assignment(self, assignment_id, headers) -> requests.Response:
        return self._request(
            "GET", f"/enablement-assignments/{assignment_id}", None, headers
        )

    def complete_assignment(self, assignment_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/enablement-assignments/{assignment_id}/complete", payload, headers
        )

    def list_enablement_assignments(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/enablement-assignments", params, headers)

    # ------------------------------------------------------------------
    # Product gaps
    # ------------------------------------------------------------------

    def create_product_gap(self, payload, headers) -> requests.Response:
        return self._request("POST", "/product-gaps", payload, headers)

    def get_product_gap(self, gap_id, headers) -> requests.Response:
        return self._request("GET", f"/product-gaps/{gap_id}", None, headers)

    def list_product_gaps(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/product-gaps", params, headers)

    def triage_product_gap(self, gap_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/product-gaps/{gap_id}/triage", payload, headers)

    def promote_product_gap(self, gap_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/product-gaps/{gap_id}/promote", payload, headers)

    # ------------------------------------------------------------------
    # Raw escape hatch for header-level and structural probes
    # ------------------------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers, params)
