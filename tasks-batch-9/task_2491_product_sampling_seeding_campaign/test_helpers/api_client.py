"""Typed HTTP client covering every endpoint in the PRD.

One method per endpoint, named after the operation.  Every method takes an
explicit ``headers`` mapping so a test always states which identity is acting.
Optional inputs are omitted from the request body unless supplied, which lets
tests exercise the server-side defaults.
"""

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``None`` (i.e. not supplied).

    Tests that need to send a literal ``null`` should build the payload dict
    themselves and use the raw ``post``/``get`` helpers.
    """
    return {key: value for key, value in payload.items() if value is not None}


class SamplingApiClient(GenericApiClient):
    """Endpoint-per-method client for the sampling and seeding API."""

    # ------------------------------------------------------------------
    # Raw escape hatches — for payloads that must contain nulls, unknown
    # fields, or deliberately malformed values.
    # ------------------------------------------------------------------
    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", path, payload=payload, headers=headers)

    # ==================================================================
    # Campaign
    # ==================================================================
    def create_campaign(
        self,
        headers: Dict[str, str],
        name: str,
        objective_type: str,
        target_segment_codes: List[str],
        sampling_window_start: str,
        sampling_window_end: str,
        budget_total_cents: int,
        syndication_retailer_ids: Optional[List[str]] = None,
        review_due_days: Optional[int] = None,
        min_review_word_count: Optional[int] = None,
        holdout_pct: Optional[float] = None,
    ) -> requests.Response:
        payload = _compact(
            {
                "name": name,
                "objective_type": objective_type,
                "target_segment_codes": target_segment_codes,
                "sampling_window_start": sampling_window_start,
                "sampling_window_end": sampling_window_end,
                "budget_total_cents": budget_total_cents,
                "syndication_retailer_ids": syndication_retailer_ids,
                "review_due_days": review_due_days,
                "min_review_word_count": min_review_word_count,
                "holdout_pct": holdout_pct,
            }
        )
        return self._request("POST", "/campaigns", payload=payload, headers=headers)

    def get_campaign(self, headers: Dict[str, str], campaign_id: str) -> requests.Response:
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(
        self,
        headers: Dict[str, str],
        status: Optional[str] = None,
        objective_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "status": status,
                "objective_type": objective_type,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def get_campaign_cost_summary(
        self, headers: Dict[str, str], campaign_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"/campaigns/{campaign_id}/cost-summary", headers=headers
        )

    def open_screening(self, headers: Dict[str, str], campaign_id: str) -> requests.Response:
        return self._request(
            "POST", f"/campaigns/{campaign_id}/open-screening", headers=headers
        )

    def activate_sampling(
        self, headers: Dict[str, str], campaign_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/campaigns/{campaign_id}/activate-sampling", headers=headers
        )

    def suspend_campaign(self, headers: Dict[str, str], campaign_id: str) -> requests.Response:
        return self._request("POST", f"/campaigns/{campaign_id}/suspend", headers=headers)

    def resume_campaign(self, headers: Dict[str, str], campaign_id: str) -> requests.Response:
        return self._request("POST", f"/campaigns/{campaign_id}/resume", headers=headers)

    def open_review_window(
        self, headers: Dict[str, str], campaign_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/campaigns/{campaign_id}/open-review-window", headers=headers
        )

    def close_campaign(self, headers: Dict[str, str], campaign_id: str) -> requests.Response:
        return self._request("POST", f"/campaigns/{campaign_id}/close", headers=headers)

    # ==================================================================
    # KitLine
    # ==================================================================
    def create_kit_line(
        self,
        headers: Dict[str, str],
        campaign_id: str,
        component_sku: str,
        component_role: str,
        unit_cost_cents: int,
        quantity_per_kit: int,
        component_discount_pct: Optional[float] = None,
    ) -> requests.Response:
        payload = _compact(
            {
                "campaign_id": campaign_id,
                "component_sku": component_sku,
                "component_role": component_role,
                "unit_cost_cents": unit_cost_cents,
                "quantity_per_kit": quantity_per_kit,
                "component_discount_pct": component_discount_pct,
            }
        )
        return self._request("POST", "/kit-lines", payload=payload, headers=headers)

    def get_kit_line(self, headers: Dict[str, str], kit_line_id: str) -> requests.Response:
        return self._request("GET", f"/kit-lines/{kit_line_id}", headers=headers)

    def list_kit_lines(
        self,
        headers: Dict[str, str],
        campaign_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "campaign_id": campaign_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/kit-lines", headers=headers, params=params)

    def record_kit_line_receipt(
        self, headers: Dict[str, str], kit_line_id: str, units: int
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/kit-lines/{kit_line_id}/receipts",
            payload={"units": units},
            headers=headers,
        )

    def record_kit_line_write_off(
        self, headers: Dict[str, str], kit_line_id: str, units: int, reason: str
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/kit-lines/{kit_line_id}/write-offs",
            payload={"units": units, "reason": reason},
            headers=headers,
        )

    def retire_kit_line(self, headers: Dict[str, str], kit_line_id: str) -> requests.Response:
        return self._request("POST", f"/kit-lines/{kit_line_id}/retire", headers=headers)

    # ==================================================================
    # FulfillmentCenter
    # ==================================================================
    def create_fulfillment_center(
        self,
        headers: Dict[str, str],
        name: str,
        zone_code: str,
        daily_pick_capacity_units: int,
        freight_cents_per_kit: int,
    ) -> requests.Response:
        payload = {
            "name": name,
            "zone_code": zone_code,
            "daily_pick_capacity_units": daily_pick_capacity_units,
            "freight_cents_per_kit": freight_cents_per_kit,
        }
        return self._request(
            "POST", "/fulfillment-centers", payload=payload, headers=headers
        )

    def get_fulfillment_center(
        self, headers: Dict[str, str], fulfillment_center_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"/fulfillment-centers/{fulfillment_center_id}", headers=headers
        )

    # ==================================================================
    # FulfillmentWave
    # ==================================================================
    def create_fulfillment_wave(
        self,
        headers: Dict[str, str],
        fulfillment_center_id: str,
        window_start: str,
        window_end: str,
        planned_capacity_units: int,
    ) -> requests.Response:
        payload = {
            "fulfillment_center_id": fulfillment_center_id,
            "window_start": window_start,
            "window_end": window_end,
            "planned_capacity_units": planned_capacity_units,
        }
        return self._request("POST", "/fulfillment-waves", payload=payload, headers=headers)

    def get_fulfillment_wave(
        self, headers: Dict[str, str], fulfillment_wave_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"/fulfillment-waves/{fulfillment_wave_id}", headers=headers
        )

    def list_fulfillment_waves(
        self,
        headers: Dict[str, str],
        fulfillment_center_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "fulfillment_center_id": fulfillment_center_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/fulfillment-waves", headers=headers, params=params)

    def lock_fulfillment_wave(
        self, headers: Dict[str, str], fulfillment_wave_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/fulfillment-waves/{fulfillment_wave_id}/lock", headers=headers
        )

    def release_fulfillment_wave(
        self, headers: Dict[str, str], fulfillment_wave_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/fulfillment-waves/{fulfillment_wave_id}/release", headers=headers
        )

    # ==================================================================
    # Panelist
    # ==================================================================
    def create_panelist(
        self,
        headers: Optional[Dict[str, str]],
        email: str,
        display_name: str,
        address_hash: str,
        account_opened_at: str,
        segment_code: str,
        referred_by_panelist_id: Optional[str] = None,
    ) -> requests.Response:
        payload = _compact(
            {
                "email": email,
                "display_name": display_name,
                "address_hash": address_hash,
                "account_opened_at": account_opened_at,
                "segment_code": segment_code,
                "referred_by_panelist_id": referred_by_panelist_id,
            }
        )
        return self._request("POST", "/panelists", payload=payload, headers=headers)

    def get_panelist(self, headers: Dict[str, str], panelist_id: str) -> requests.Response:
        return self._request("GET", f"/panelists/{panelist_id}", headers=headers)

    def list_panelists(
        self,
        headers: Dict[str, str],
        referred_by_panelist_id: Optional[str] = None,
        integrity_status: Optional[str] = None,
        segment_code: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "referred_by_panelist_id": referred_by_panelist_id,
                "integrity_status": integrity_status,
                "segment_code": segment_code,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/panelists", headers=headers, params=params)

    def rescore_panelist_risk(
        self, headers: Dict[str, str], panelist_id: str, variant: str
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/panelists/{panelist_id}/risk-rescore",
            payload={"variant": variant},
            headers=headers,
        )

    # ==================================================================
    # Enrollment
    # ==================================================================
    def create_enrollment(
        self,
        headers: Dict[str, str],
        campaign_id: str,
        panelist_id: str,
        screening_answers: Dict[str, Any],
    ) -> requests.Response:
        payload = {
            "campaign_id": campaign_id,
            "panelist_id": panelist_id,
            "screening_answers": screening_answers,
        }
        return self._request("POST", "/enrollments", payload=payload, headers=headers)

    def get_enrollment(self, headers: Dict[str, str], enrollment_id: str) -> requests.Response:
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(
        self,
        headers: Dict[str, str],
        campaign_id: Optional[str] = None,
        panelist_id: Optional[str] = None,
        screening_status: Optional[str] = None,
        obligation_status: Optional[str] = None,
        holdout_flag: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "campaign_id": campaign_id,
                "panelist_id": panelist_id,
                "screening_status": screening_status,
                "obligation_status": obligation_status,
                "holdout_flag": holdout_flag,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def screen_enrollment(
        self, headers: Dict[str, str], enrollment_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/screen", headers=headers
        )

    def resubmit_screening(
        self,
        headers: Dict[str, str],
        enrollment_id: str,
        screening_answers: Dict[str, Any],
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/resubmit-screening",
            payload={"screening_answers": screening_answers},
            headers=headers,
        )

    def list_enrollment_purchase_matches(
        self,
        headers: Dict[str, str],
        enrollment_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact({"limit": limit, "offset": offset})
        return self._request(
            "GET",
            f"/enrollments/{enrollment_id}/purchase-matches",
            headers=headers,
            params=params,
        )

    # ==================================================================
    # SampleShipment
    # ==================================================================
    def create_sample_shipment(
        self,
        headers: Dict[str, str],
        enrollment_id: str,
        fulfillment_wave_id: str,
        expected_enrollment_version: int,
        surcharge_cents: Optional[int] = None,
        supersedes_shipment_id: Optional[str] = None,
    ) -> requests.Response:
        payload = _compact(
            {
                "enrollment_id": enrollment_id,
                "fulfillment_wave_id": fulfillment_wave_id,
                "expected_enrollment_version": expected_enrollment_version,
                "surcharge_cents": surcharge_cents,
                "supersedes_shipment_id": supersedes_shipment_id,
            }
        )
        return self._request("POST", "/sample-shipments", payload=payload, headers=headers)

    def get_sample_shipment(
        self, headers: Dict[str, str], sample_shipment_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"/sample-shipments/{sample_shipment_id}", headers=headers
        )

    def list_sample_shipments(
        self,
        headers: Dict[str, str],
        enrollment_id: Optional[str] = None,
        fulfillment_wave_id: Optional[str] = None,
        supersedes_shipment_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "enrollment_id": enrollment_id,
                "fulfillment_wave_id": fulfillment_wave_id,
                "supersedes_shipment_id": supersedes_shipment_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/sample-shipments", headers=headers, params=params)

    def cancel_sample_shipment(
        self, headers: Dict[str, str], sample_shipment_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/sample-shipments/{sample_shipment_id}/cancel", headers=headers
        )

    def deliver_sample_shipment(
        self, headers: Dict[str, str], sample_shipment_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/sample-shipments/{sample_shipment_id}/deliver", headers=headers
        )

    def report_sample_shipment_lost(
        self, headers: Dict[str, str], sample_shipment_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/sample-shipments/{sample_shipment_id}/report-lost", headers=headers
        )

    # ==================================================================
    # ReviewSubmission
    # ==================================================================
    def create_review_submission(
        self,
        headers: Dict[str, str],
        enrollment_id: str,
        headline: str,
        body_text: str,
        star_rating: int,
        disclosure_statement: Optional[str] = None,
        honest_opinion_attested: Optional[bool] = None,
    ) -> requests.Response:
        payload = _compact(
            {
                "enrollment_id": enrollment_id,
                "headline": headline,
                "body_text": body_text,
                "star_rating": star_rating,
                "disclosure_statement": disclosure_statement,
                "honest_opinion_attested": honest_opinion_attested,
            }
        )
        return self._request("POST", "/review-submissions", payload=payload, headers=headers)

    def get_review_submission(
        self, headers: Dict[str, str], review_submission_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"/review-submissions/{review_submission_id}", headers=headers
        )

    def list_review_submissions(
        self,
        headers: Dict[str, str],
        enrollment_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "enrollment_id": enrollment_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/review-submissions", headers=headers, params=params)

    def submit_review(
        self, headers: Dict[str, str], review_submission_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/review-submissions/{review_submission_id}/submit", headers=headers
        )

    def moderate_review(
        self,
        headers: Dict[str, str],
        review_submission_id: str,
        decision: str,
        moderator_note: Optional[str] = None,
    ) -> requests.Response:
        payload = _compact({"decision": decision, "moderator_note": moderator_note})
        return self._request(
            "POST",
            f"/review-submissions/{review_submission_id}/moderate",
            payload=payload,
            headers=headers,
        )

    def revise_review(
        self,
        headers: Dict[str, str],
        review_submission_id: str,
        headline: str,
        body_text: str,
        star_rating: int,
        disclosure_statement: Optional[str] = None,
        honest_opinion_attested: Optional[bool] = None,
    ) -> requests.Response:
        payload = _compact(
            {
                "headline": headline,
                "body_text": body_text,
                "star_rating": star_rating,
                "disclosure_statement": disclosure_statement,
                "honest_opinion_attested": honest_opinion_attested,
            }
        )
        return self._request(
            "POST",
            f"/review-submissions/{review_submission_id}/revise",
            payload=payload,
            headers=headers,
        )

    # ==================================================================
    # Retailer
    # ==================================================================
    def create_retailer(
        self,
        headers: Dict[str, str],
        name: str,
        feed_status: Optional[str] = None,
        requires_disclosure_badge: Optional[bool] = None,
        min_star_rating_accepted: Optional[int] = None,
        max_reviews_per_panelist_per_month: Optional[int] = None,
    ) -> requests.Response:
        payload = _compact(
            {
                "name": name,
                "feed_status": feed_status,
                "requires_disclosure_badge": requires_disclosure_badge,
                "min_star_rating_accepted": min_star_rating_accepted,
                "max_reviews_per_panelist_per_month": max_reviews_per_panelist_per_month,
            }
        )
        return self._request("POST", "/retailers", payload=payload, headers=headers)

    def get_retailer(self, headers: Dict[str, str], retailer_id: str) -> requests.Response:
        return self._request("GET", f"/retailers/{retailer_id}", headers=headers)

    # ==================================================================
    # SyndicationRecord
    # ==================================================================
    def create_syndication_record(
        self, headers: Dict[str, str], review_submission_id: str, retailer_id: str
    ) -> requests.Response:
        payload = {
            "review_submission_id": review_submission_id,
            "retailer_id": retailer_id,
        }
        return self._request(
            "POST", "/syndication-records", payload=payload, headers=headers
        )

    def get_syndication_record(
        self, headers: Dict[str, str], syndication_record_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"/syndication-records/{syndication_record_id}", headers=headers
        )

    def list_syndication_records(
        self,
        headers: Dict[str, str],
        review_submission_id: Optional[str] = None,
        retailer_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "review_submission_id": review_submission_id,
                "retailer_id": retailer_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/syndication-records", headers=headers, params=params)

    def dispatch_syndication_record(
        self, headers: Dict[str, str], syndication_record_id: str
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/syndication-records/{syndication_record_id}/dispatch",
            headers=headers,
        )

    # ==================================================================
    # DiversionCase
    # ==================================================================
    def create_diversion_case(
        self,
        headers: Dict[str, str],
        panelist_id: str,
        sample_shipment_id: str,
        signal_type: str,
        evidence_note: str,
    ) -> requests.Response:
        payload = {
            "panelist_id": panelist_id,
            "sample_shipment_id": sample_shipment_id,
            "signal_type": signal_type,
            "evidence_note": evidence_note,
        }
        return self._request("POST", "/diversion-cases", payload=payload, headers=headers)

    def get_diversion_case(
        self, headers: Dict[str, str], diversion_case_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"/diversion-cases/{diversion_case_id}", headers=headers
        )

    def list_diversion_cases(
        self,
        headers: Dict[str, str],
        panelist_id: Optional[str] = None,
        sample_shipment_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "panelist_id": panelist_id,
                "sample_shipment_id": sample_shipment_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/diversion-cases", headers=headers, params=params)

    def investigate_diversion_case(
        self, headers: Dict[str, str], diversion_case_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/diversion-cases/{diversion_case_id}/investigate", headers=headers
        )

    def reopen_diversion_case(
        self, headers: Dict[str, str], diversion_case_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/diversion-cases/{diversion_case_id}/reopen", headers=headers
        )

    def dismiss_diversion_case(
        self, headers: Dict[str, str], diversion_case_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/diversion-cases/{diversion_case_id}/dismiss", headers=headers
        )

    def substantiate_diversion_case(
        self, headers: Dict[str, str], diversion_case_id: str
    ) -> requests.Response:
        return self._request(
            "POST", f"/diversion-cases/{diversion_case_id}/substantiate", headers=headers
        )

    # ==================================================================
    # PurchaseMatch
    # ==================================================================
    def create_purchase_match(
        self,
        headers: Dict[str, str],
        enrollment_id: str,
        retailer_channel_code: str,
        purchase_amount_cents: int,
        purchased_at: str,
        match_confidence: float,
    ) -> requests.Response:
        payload = {
            "enrollment_id": enrollment_id,
            "retailer_channel_code": retailer_channel_code,
            "purchase_amount_cents": purchase_amount_cents,
            "purchased_at": purchased_at,
            "match_confidence": match_confidence,
        }
        return self._request("POST", "/purchase-matches", payload=payload, headers=headers)

    def get_purchase_match(
        self, headers: Dict[str, str], purchase_match_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"/purchase-matches/{purchase_match_id}", headers=headers
        )

    def list_purchase_matches(
        self,
        headers: Dict[str, str],
        enrollment_id: Optional[str] = None,
        qualified: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "enrollment_id": enrollment_id,
                "qualified": qualified,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/purchase-matches", headers=headers, params=params)

    # ==================================================================
    # LiftAnalysis
    # ==================================================================
    def create_lift_analysis(
        self,
        headers: Dict[str, str],
        campaign_id: str,
        variant: str,
        expected_campaign_version: int,
    ) -> requests.Response:
        payload = {
            "campaign_id": campaign_id,
            "variant": variant,
            "expected_campaign_version": expected_campaign_version,
        }
        return self._request("POST", "/lift-analyses", payload=payload, headers=headers)

    def get_lift_analysis(
        self, headers: Dict[str, str], lift_analysis_id: str
    ) -> requests.Response:
        return self._request("GET", f"/lift-analyses/{lift_analysis_id}", headers=headers)

    def list_lift_analyses(
        self,
        headers: Dict[str, str],
        campaign_id: Optional[str] = None,
        variant: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "campaign_id": campaign_id,
                "variant": variant,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/lift-analyses", headers=headers, params=params)

    # ==================================================================
    # Logical clock
    # ==================================================================
    def set_clock(self, headers: Dict[str, str], to_iso8601: str) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601},
            headers=headers,
        )
