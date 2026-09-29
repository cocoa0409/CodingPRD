"""One client method per endpoint in the PRD's endpoint table.

Every method returns the raw HTTP response so a test can assert on the status
code as well as on the envelope. Paths are mounted at the root of the service.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import (
    AdoptionCyclePayload,
    AncillaryBundlePayload,
    ClockPayload,
    CommitteePanelPayload,
    CommitteeVotePayload,
    ContentEditPayload,
    ContentEditResubmitPayload,
    ContentEditReviewPayload,
    ContentEditRevertPayload,
    CorrelationEntryPayload,
    CorrelationVerdictPayload,
    DistrictOrderPayload,
    InventoryAdjustmentPayload,
    JsonDict,
    OrderCancelPayload,
    PresentationSlotPayload,
    PricingDecisionPayload,
    PricingProposalPayload,
    PublicCommentPayload,
    PublicCommentResponsePayload,
    RevisionPlanPayload,
    SamplingShipmentPayload,
    StateProfilePayload,
    StateStandardPayload,
    SubmissionPayload,
    TitlePayload,
    WithdrawPayload,
)

Headers = Optional[Dict[str, str]]


class ApiClient(GenericApiClient):
    """Endpoint surface of the state adoption review service."""

    # ------------------------------------------------------------------
    # The logical adoption clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: ClockPayload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_clock_to(self, instant: str, headers: Headers = None) -> requests.Response:
        return self.set_clock({"to_iso8601": instant}, headers)

    # ------------------------------------------------------------------
    # State profiles and academic frameworks
    # ------------------------------------------------------------------

    def create_state_profile(
        self, payload: StateProfilePayload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/state-profiles", payload, headers)

    def get_state_profile(self, state_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/state-profiles/{state_id}", None, headers)

    def add_state_standard(
        self, state_id: str, payload: StateStandardPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/state-profiles/{state_id}/standards", payload, headers
        )

    def list_state_standards(
        self, state_id: str, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/state-profiles/{state_id}/standards", params, headers
        )

    # ------------------------------------------------------------------
    # Adoption cycles
    # ------------------------------------------------------------------

    def create_adoption_cycle(
        self, payload: AdoptionCyclePayload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/adoption-cycles", payload, headers)

    def list_adoption_cycles(
        self, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/adoption-cycles", params, headers)

    def get_adoption_cycle(self, cycle_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/adoption-cycles/{cycle_id}", None, headers)

    def advance_cycle_phase(
        self, cycle_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/adoption-cycles/{cycle_id}/phase-advance", payload or {}, headers
        )

    def list_cycle_panels(
        self, cycle_id: str, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/adoption-cycles/{cycle_id}/panels", params, headers
        )

    # ------------------------------------------------------------------
    # Titles, inventory, revision plans and bundles
    # ------------------------------------------------------------------

    def create_title(
        self, payload: TitlePayload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/titles/{title_id}", None, headers)

    def release_title(
        self, title_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/titles/{title_id}/release", payload or {}, headers
        )

    def adjust_inventory(
        self,
        title_id: str,
        payload: InventoryAdjustmentPayload,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/titles/{title_id}/inventory-adjustments", payload, headers
        )

    def revision_plan(
        self, title_id: str, payload: RevisionPlanPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/titles/{title_id}/revision-plan", payload, headers
        )

    def create_ancillary_bundle(
        self, title_id: str, payload: AncillaryBundlePayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/titles/{title_id}/ancillary-bundles", payload, headers
        )

    def list_ancillary_bundles(
        self, title_id: str, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/titles/{title_id}/ancillary-bundles", params, headers
        )

    # ------------------------------------------------------------------
    # Content edits
    # ------------------------------------------------------------------

    def create_content_edit(
        self, payload: ContentEditPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/content-edits", payload, headers)

    def list_content_edits(
        self, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/content-edits", params, headers)

    def get_content_edit(self, edit_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/content-edits/{edit_id}", None, headers)

    def review_content_edit(
        self, edit_id: str, payload: ContentEditReviewPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/content-edits/{edit_id}/review", payload, headers
        )

    def resubmit_content_edit(
        self,
        edit_id: str,
        payload: ContentEditResubmitPayload,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/content-edits/{edit_id}/resubmit", payload, headers
        )

    def apply_content_edit(
        self, edit_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/content-edits/{edit_id}/apply", payload or {}, headers
        )

    def revert_content_edit(
        self, edit_id: str, payload: ContentEditRevertPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/content-edits/{edit_id}/revert", payload, headers
        )

    # ------------------------------------------------------------------
    # Submissions, correlations and sampling
    # ------------------------------------------------------------------

    def create_submission(
        self, payload: SubmissionPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/submissions", payload, headers)

    def list_submissions(
        self, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/submissions", params, headers)

    def get_submission(
        self, submission_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/submissions/{submission_id}", None, headers)

    def create_correlation(
        self,
        submission_id: str,
        payload: CorrelationEntryPayload,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/submissions/{submission_id}/correlations", payload, headers
        )

    def list_correlations(
        self,
        submission_id: str,
        headers: Headers = None,
        params: Optional[JsonDict] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/submissions/{submission_id}/correlations", params, headers
        )

    def record_correlation_verdict(
        self,
        submission_id: str,
        entry_id: str,
        payload: CorrelationVerdictPayload,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/submissions/{submission_id}/correlations/{entry_id}/verdict",
            payload,
            headers,
        )

    def file_submission(
        self,
        submission_id: str,
        headers: Headers = None,
        payload: Optional[JsonDict] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/submissions/{submission_id}/file", payload or {}, headers
        )

    def withdraw_submission(
        self, submission_id: str, payload: WithdrawPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/submissions/{submission_id}/withdraw", payload, headers
        )

    def ship_sampling_copies(
        self,
        submission_id: str,
        payload: SamplingShipmentPayload,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/submissions/{submission_id}/sampling-shipments", payload, headers
        )

    # ------------------------------------------------------------------
    # Public comments
    # ------------------------------------------------------------------

    def create_public_comment(
        self, submission_id: str, payload: PublicCommentPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/submissions/{submission_id}/public-comments", payload, headers
        )

    def list_public_comments(
        self,
        submission_id: str,
        headers: Headers = None,
        params: Optional[JsonDict] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/submissions/{submission_id}/public-comments", params, headers
        )

    def respond_to_public_comment(
        self,
        comment_id: str,
        payload: PublicCommentResponsePayload,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/public-comments/{comment_id}/response", payload, headers
        )

    # ------------------------------------------------------------------
    # Committee panels, slots, ballots and tallies
    # ------------------------------------------------------------------

    def create_committee_panel(
        self, payload: CommitteePanelPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/committee-panels", payload, headers)

    def get_committee_panel(
        self, panel_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/committee-panels/{panel_id}", None, headers)

    def reserve_slot(
        self, panel_id: str, payload: PresentationSlotPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/committee-panels/{panel_id}/slots", payload, headers
        )

    def open_panel_session(
        self, panel_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/committee-panels/{panel_id}/open-session", payload or {}, headers
        )

    def close_panel_session(
        self, panel_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/committee-panels/{panel_id}/close-session",
            payload or {},
            headers,
        )

    def list_presentation_slots(
        self, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/presentation-slots", params, headers)

    def get_presentation_slot(
        self, slot_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/presentation-slots/{slot_id}", None, headers)

    def present_slot(
        self, slot_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/presentation-slots/{slot_id}/present", payload or {}, headers
        )

    def cast_vote(
        self, slot_id: str, payload: CommitteeVotePayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/presentation-slots/{slot_id}/votes", payload, headers
        )

    def list_votes(
        self, slot_id: str, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/presentation-slots/{slot_id}/votes", params, headers
        )

    def tally_slot(
        self, slot_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/presentation-slots/{slot_id}/tally", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Pricing proposals
    # ------------------------------------------------------------------

    def create_pricing_proposal(
        self, payload: PricingProposalPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/pricing-proposals", payload, headers)

    def list_pricing_proposals(
        self, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pricing-proposals", params, headers)

    def get_pricing_proposal(
        self, proposal_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/pricing-proposals/{proposal_id}", None, headers)

    def decide_pricing_proposal(
        self, proposal_id: str, payload: PricingDecisionPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pricing-proposals/{proposal_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # District orders
    # ------------------------------------------------------------------

    def create_district_order(
        self, payload: DistrictOrderPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/district-orders", payload, headers)

    def list_district_orders(
        self, headers: Headers = None, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/district-orders", params, headers)

    def get_district_order(
        self, order_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/district-orders/{order_id}", None, headers)

    def confirm_district_order(
        self, order_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/district-orders/{order_id}/confirm", payload or {}, headers
        )

    def fulfill_district_order(
        self, order_id: str, headers: Headers = None, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/district-orders/{order_id}/fulfill", payload or {}, headers
        )

    def cancel_district_order(
        self, order_id: str, payload: OrderCancelPayload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/district-orders/{order_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Convenience readers
    # ------------------------------------------------------------------

    def read_submission_version(self, submission_id: str, headers: Headers = None) -> Any:
        """Return the submission's current record version."""
        body = self.get_submission(submission_id, headers).json()
        return body["data"]["version"]

    def read_panel_version(self, panel_id: str, headers: Headers = None) -> Any:
        """Return the panel's current record version."""
        body = self.get_committee_panel(panel_id, headers).json()
        return body["data"]["version"]


#: Session-wide client instance shared by every test.
api_client = ApiClient()
