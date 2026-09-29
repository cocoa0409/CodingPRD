"""HTTP client for every endpoint of the retail media network API.

One method per endpoint, named after what the endpoint does rather than after
its URL, so a test reads as a sequence of business steps.

Almost every path sits under the business prefix. The logical clock and the daily
checkpoint sweep are operational capabilities and are declared without it, so
`set_clock` and `run_daily_checkpoint` post to bare paths.

Collection reads take filter and pagination arguments as keyword parameters and
pass them through as query parameters untouched, which lets a test send a
deliberately invalid `limit` or `offset` and observe the refusal.
"""

from typing import Any, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH, DAILY_CHECKPOINT_PATH


class RmnApiClient(GenericApiClient):
    """Typed access to all 101 endpoints of the retail media network API."""

    prefix = API_PREFIX

    def _url(self, suffix: str) -> str:
        """Join the business prefix to a resource path."""
        return "%s%s" % (self.prefix, suffix)

    def set_clock(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Sets the logical clock used by every window, flight, pacing, SLA and net-terms
        rule.
        """
        return self._request(
            "POST",
            CLOCK_PATH,
            payload=payload or {},
            headers=headers,
        )

    def run_daily_checkpoint(
        self,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Deterministic daily sweep at the current logical clock: recomputes
        campaign_pacing_allowance, refreshes dispute_sla_clock breach flags, closes
        elapsed flights and exhausts drained budget plans.
        """
        return self._request(
            "POST",
            DAILY_CHECKPOINT_PATH,
            payload=payload or {},
            headers=headers,
        )

    def create_advertiser(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Registers an advertiser in DRAFT onboarding_status under either the SELF_SERVE
        or MANAGED service model.
        """
        return self._request(
            "POST",
            self._url("/advertisers"),
            payload=payload or {},
            headers=headers,
        )

    def list_advertisers(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists advertisers; filtering by parent_advertiser_id resolves an agency
        umbrella's child brands.
        """
        return self._request(
            "GET",
            self._url("/advertisers"),
            headers=headers,
            params=params or None,
        )

    def get_advertiser(self, advertiser_id: str, headers: Optional[dict] = None) -> Any:
        """Reads one advertiser including computed credit_exposure_cents and
        dispute_credit_balance_cents.
        """
        return self._request(
            "GET",
            self._url("/advertisers/%s" % advertiser_id),
            headers=headers,
        )

    def update_advertiser(
        self,
        advertiser_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Amends advertiser commercial terms while onboarding_status is DRAFT, KYC_REVIEW,
        CREDIT_HOLD or ACTIVE.
        """
        return self._request(
            "PATCH",
            self._url("/advertisers/%s" % advertiser_id),
            payload=payload or {},
            headers=headers,
        )

    def submit_advertiser_onboarding(
        self,
        advertiser_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Submits onboarding paperwork, moving DRAFT or CREDIT_HOLD through SUBMITTED into
        KYC_REVIEW.
        """
        return self._request(
            "POST",
            self._url("/advertisers/%s/submit-onboarding" % advertiser_id),
            payload=payload or {},
            headers=headers,
        )

    def decide_advertiser_kyc(
        self,
        advertiser_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Branching KYC fork from KYC_REVIEW: APPROVE -> ACTIVE, HOLD -> CREDIT_HOLD,
        REJECT -> REJECTED.
        """
        return self._request(
            "POST",
            self._url("/advertisers/%s/kyc-decision" % advertiser_id),
            payload=payload or {},
            headers=headers,
        )

    def suspend_advertiser(
        self,
        advertiser_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Suspends an ACTIVE advertiser and runs the depth-3 suspension cascade."""
        return self._request(
            "POST",
            self._url("/advertisers/%s/suspend" % advertiser_id),
            payload=payload or {},
            headers=headers,
        )

    def reinstate_advertiser(
        self,
        advertiser_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Returns a SUSPENDED advertiser to ACTIVE without automatically resuming any
        paused campaign.
        """
        return self._request(
            "POST",
            self._url("/advertisers/%s/reinstate" % advertiser_id),
            payload=payload or {},
            headers=headers,
        )

    def terminate_advertiser(
        self,
        advertiser_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Terminates an advertiser from SUSPENDED, closing every open financial container.
        """
        return self._request(
            "POST",
            self._url("/advertisers/%s/terminate" % advertiser_id),
            payload=payload or {},
            headers=headers,
        )

    def get_advertiser_credit_summary(
        self,
        advertiser_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Computed read returning the advertiser_credit_exposure inputs and headroom,
        including the parent umbrella limit when parent_advertiser_id is non-null.
        """
        return self._request(
            "GET",
            self._url("/advertisers/%s/credit-summary" % advertiser_id),
            headers=headers,
        )

    def create_budget_plan(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Opens a DRAFT budget plan for one advertiser and fiscal period, splitting the
        commitment between trade-fund share and cash share.
        """
        return self._request(
            "POST",
            self._url("/budget-plans"),
            payload=payload or {},
            headers=headers,
        )

    def list_budget_plans(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists budget plans, filterable by owning advertiser, fiscal period and status."""
        return self._request(
            "GET",
            self._url("/budget-plans"),
            headers=headers,
            params=params or None,
        )

    def get_budget_plan(self, budget_plan_id: str, headers: Optional[dict] = None) -> Any:
        """Reads one budget plan with the live committed / reserved / consumed / available
        decomposition.
        """
        return self._request(
            "GET",
            self._url("/budget-plans/%s" % budget_plan_id),
            headers=headers,
        )

    def submit_budget_plan(
        self,
        budget_plan_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Submits a DRAFT plan for approval, reserving the requested trade-fund share
        against the matching fiscal-period fund account.
        """
        return self._request(
            "POST",
            self._url("/budget-plans/%s/submit" % budget_plan_id),
            payload=payload or {},
            headers=headers,
        )

    def approve_budget_plan(
        self,
        budget_plan_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Approves a PENDING_APPROVAL plan into APPROVED and immediately into ACTIVE,
        checking advertiser credit headroom and plan-window exclusivity.
        """
        return self._request(
            "POST",
            self._url("/budget-plans/%s/approve" % budget_plan_id),
            payload=payload or {},
            headers=headers,
        )

    def return_budget_plan_for_revision(
        self,
        budget_plan_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Returns a PENDING_APPROVAL plan to DRAFT for rework, incrementing
        revision_round; the cycle is bounded by MAX_REVISION_ROUNDS.
        """
        return self._request(
            "POST",
            self._url("/budget-plans/%s/return-for-revision" % budget_plan_id),
            payload=payload or {},
            headers=headers,
        )

    def top_up_budget_plan(
        self,
        budget_plan_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Adds cash headroom to an ACTIVE or EXHAUSTED plan; an EXHAUSTED plan returns to
        ACTIVE and its paused campaigns become resumable.
        """
        return self._request(
            "POST",
            self._url("/budget-plans/%s/top-up" % budget_plan_id),
            payload=payload or {},
            headers=headers,
        )

    def close_budget_plan(
        self,
        budget_plan_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Closes an ACTIVE or EXHAUSTED plan once its window has elapsed, compensating
        every outstanding reservation.
        """
        return self._request(
            "POST",
            self._url("/budget-plans/%s/close" % budget_plan_id),
            payload=payload or {},
            headers=headers,
        )

    def create_trade_fund_account(
        self,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Opens the co-op / trade-fund pool an advertiser's media deductions draw from for
        one fiscal period.
        """
        return self._request(
            "POST",
            self._url("/trade-fund-accounts"),
            payload=payload or {},
            headers=headers,
        )

    def list_trade_fund_accounts(
        self,
        headers: Optional[dict] = None,
        **params: Any,
    ) -> Any:
        """Lists trade-fund accounts, filterable by owning advertiser, fiscal period and
        status.
        """
        return self._request(
            "GET",
            self._url("/trade-fund-accounts"),
            headers=headers,
            params=params or None,
        )

    def get_trade_fund_account(
        self,
        trade_fund_account_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one trade-fund account with its accrued / reserved / deducted / available
        decomposition.
        """
        return self._request(
            "GET",
            self._url("/trade-fund-accounts/%s" % trade_fund_account_id),
            headers=headers,
        )

    def post_trade_fund_accrual(
        self,
        trade_fund_account_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Books a supplier accrual into an OPEN fund account, raising the pool the media
        deduction waterfall can draw on.
        """
        return self._request(
            "POST",
            self._url("/trade-fund-accounts/%s/accruals" % trade_fund_account_id),
            payload=payload or {},
            headers=headers,
        )

    def post_trade_fund_deduction(
        self,
        trade_fund_account_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Applies a manual deduction against an OPEN fund account."""
        return self._request(
            "POST",
            self._url("/trade-fund-accounts/%s/deductions" % trade_fund_account_id),
            payload=payload or {},
            headers=headers,
        )

    def freeze_trade_fund_account(
        self,
        trade_fund_account_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Freezes an OPEN fund account so no accrual, deduction or invoice issuance may
        touch it.
        """
        return self._request(
            "POST",
            self._url("/trade-fund-accounts/%s/freeze" % trade_fund_account_id),
            payload=payload or {},
            headers=headers,
        )

    def unfreeze_trade_fund_account(
        self,
        trade_fund_account_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Returns a FROZEN fund account to OPEN, optionally passing through RECONCILING
        when a reconciliation pass is requested.
        """
        return self._request(
            "POST",
            self._url("/trade-fund-accounts/%s/unfreeze" % trade_fund_account_id),
            payload=payload or {},
            headers=headers,
        )

    def create_campaign(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Creates a DRAFT campaign bound to one funded budget plan, fixing its channel
        mix, pacing mode and attribution model.
        """
        return self._request(
            "POST",
            self._url("/campaigns"),
            payload=payload or {},
            headers=headers,
        )

    def list_campaigns(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists campaigns, filterable by advertiser, funding plan and either parallel
        status dimension.
        """
        return self._request(
            "GET",
            self._url("/campaigns"),
            headers=headers,
            params=params or None,
        )

    def get_campaign(self, campaign_id: str, headers: Optional[dict] = None) -> Any:
        """Reads one campaign including both parallel status dimensions and its closed-loop
        measurement fields.
        """
        return self._request(
            "GET",
            self._url("/campaigns/%s" % campaign_id),
            headers=headers,
        )

    def update_campaign(
        self,
        campaign_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Amends a DRAFT or PENDING_REVIEW campaign's flight, pacing, cap or attribution
        settings.
        """
        return self._request(
            "PATCH",
            self._url("/campaigns/%s" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def submit_campaign_for_review(
        self,
        campaign_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Submits a DRAFT campaign for network review, checking plan headroom, channel-mix
        completeness and window containment.
        """
        return self._request(
            "POST",
            self._url("/campaigns/%s/submit-for-review" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def decide_campaign_review(
        self,
        campaign_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Branching review fork from PENDING_REVIEW: APPROVE -> SCHEDULED with the budget
        reserved, REJECT -> REJECTED with nothing reserved.
        """
        return self._request(
            "POST",
            self._url("/campaigns/%s/review-decision" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def activate_campaign(
        self,
        campaign_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Starts delivery on a SCHEDULED campaign once the logical clock has reached
        flight_start_at.
        """
        return self._request(
            "POST",
            self._url("/campaigns/%s/activate" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def pause_campaign(
        self,
        campaign_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Pauses a DELIVERING campaign, cascading the pause to every serving line item."""
        return self._request(
            "POST",
            self._url("/campaigns/%s/pause" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def resume_campaign(
        self,
        campaign_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Returns a PAUSED campaign to DELIVERING when the plan is ACTIVE, the advertiser
        is ACTIVE and headroom remains.
        """
        return self._request(
            "POST",
            self._url("/campaigns/%s/resume" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def complete_campaign(
        self,
        campaign_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Completes a DELIVERING or PAUSED campaign whose flight has elapsed and hands it
        to billing.
        """
        return self._request(
            "POST",
            self._url("/campaigns/%s/complete" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def archive_campaign(
        self,
        campaign_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Archives a SCHEDULED, REJECTED or COMPLETED campaign; archiving a SCHEDULED
        campaign is the compensating release of its untouched reservation.
        """
        return self._request(
            "POST",
            self._url("/campaigns/%s/archive" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def post_campaign_offsite_reconciliation(
        self,
        campaign_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Loads the partner-reported off-site spend for the campaign and runs
        offsite_spend_reconciliation to pick the billable basis.
        """
        return self._request(
            "POST",
            self._url("/campaigns/%s/offsite-reconciliation" % campaign_id),
            payload=payload or {},
            headers=headers,
        )

    def get_campaign_performance_summary(
        self,
        campaign_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Computed read returning delivered spend, attributed revenue, incremental
        revenue, roas, iroas and pacing_index for the campaign.
        """
        return self._request(
            "GET",
            self._url("/campaigns/%s/performance-summary" % campaign_id),
            headers=headers,
        )

    def create_placement_slot(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Declares a sponsored inventory slot with its channel, capacity, floor price,
        relevance weight and exclusivity category.
        """
        return self._request(
            "POST",
            self._url("/placement-slots"),
            payload=payload or {},
            headers=headers,
        )

    def list_placement_slots(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists placement slots, filterable by channel, page type and status."""
        return self._request(
            "GET",
            self._url("/placement-slots"),
            headers=headers,
            params=params or None,
        )

    def get_placement_slot(
        self,
        placement_slot_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one placement slot with its live occupancy_count."""
        return self._request(
            "GET",
            self._url("/placement-slots/%s" % placement_slot_id),
            headers=headers,
        )

    def update_placement_slot(
        self,
        placement_slot_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Retunes a slot or moves it between OPEN, MAINTENANCE and RETIRED; RETIRED is
        terminal.
        """
        return self._request(
            "PATCH",
            self._url("/placement-slots/%s" % placement_slot_id),
            payload=payload or {},
            headers=headers,
        )

    def create_line_item(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Creates a DRAFT line item binding one campaign to one placement slot with a bid,
        flight and keyword set.
        """
        return self._request(
            "POST",
            self._url("/line-items"),
            payload=payload or {},
            headers=headers,
        )

    def list_line_items(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists line items, filterable by owning campaign, placement slot, status and
        priority tier.
        """
        return self._request(
            "GET",
            self._url("/line-items"),
            headers=headers,
            params=params or None,
        )

    def get_line_item(self, line_item_id: str, headers: Optional[dict] = None) -> Any:
        """Reads one line item with its relevance_score, quality_adjusted_score,
        priority_tier and reservation state.
        """
        return self._request(
            "GET",
            self._url("/line-items/%s" % line_item_id),
            headers=headers,
        )

    def submit_line_item_eligibility(
        self,
        line_item_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Submits a DRAFT line item for catalog and inventory eligibility review."""
        return self._request(
            "POST",
            self._url("/line-items/%s/submit-eligibility" % line_item_id),
            payload=payload or {},
            headers=headers,
        )

    def decide_line_item_eligibility(
        self,
        line_item_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Branching eligibility fork from PENDING_ELIGIBILITY: APPROVE -> ELIGIBLE and
        claims slot occupancy, REJECT -> REJECTED and claims nothing.
        """
        return self._request(
            "POST",
            self._url("/line-items/%s/eligibility-decision" % line_item_id),
            payload=payload or {},
            headers=headers,
        )

    def activate_line_item(
        self,
        line_item_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Moves an ELIGIBLE line item into SERVING so it can enter auctions, reserving its
        daily budget.
        """
        return self._request(
            "POST",
            self._url("/line-items/%s/activate" % line_item_id),
            payload=payload or {},
            headers=headers,
        )

    def pause_line_item(
        self,
        line_item_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Manually pauses a SERVING line item, releasing its reservation and slot
        occupancy.
        """
        return self._request(
            "POST",
            self._url("/line-items/%s/pause" % line_item_id),
            payload=payload or {},
            headers=headers,
        )

    def resume_line_item(
        self,
        line_item_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Returns an OOS_PAUSED or MANUAL_PAUSED line item to SERVING once its blocking
        condition has cleared.
        """
        return self._request(
            "POST",
            self._url("/line-items/%s/resume" % line_item_id),
            payload=payload or {},
            headers=headers,
        )

    def end_line_item(
        self,
        line_item_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Ends a line item from ELIGIBLE, SERVING, OOS_PAUSED or MANUAL_PAUSED; ENDED is
        the terminal compensator that guarantees no occupancy or reservation leaks.
        """
        return self._request(
            "POST",
            self._url("/line-items/%s/end" % line_item_id),
            payload=payload or {},
            headers=headers,
        )

    def create_catalog_product(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Registers a retail SKU that sponsored line items may promote."""
        return self._request(
            "POST",
            self._url("/catalog-products"),
            payload=payload or {},
            headers=headers,
        )

    def list_catalog_products(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists catalog products, filterable by category, eligibility status and SKU."""
        return self._request(
            "GET",
            self._url("/catalog-products"),
            headers=headers,
            params=params or None,
        )

    def get_catalog_product(
        self,
        catalog_product_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one catalog product with its live stock and eligibility state."""
        return self._request(
            "GET",
            self._url("/catalog-products/%s" % catalog_product_id),
            headers=headers,
        )

    def post_catalog_product_stock_adjustment(
        self,
        catalog_product_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Applies a signed stock movement; crossing below min_stock_units_for_serving
        fires the depth-3 out-of-stock pausing cascade and crossing back above it clears
        the cascade.
        """
        return self._request(
            "POST",
            self._url("/catalog-products/%s/stock-adjustments" % catalog_product_id),
            payload=payload or {},
            headers=headers,
        )

    def restrict_catalog_product(
        self,
        catalog_product_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Restricts an ELIGIBLE or OUT_OF_STOCK product for policy reasons, pausing every
        assignment that references it.
        """
        return self._request(
            "POST",
            self._url("/catalog-products/%s/restrict" % catalog_product_id),
            payload=payload or {},
            headers=headers,
        )

    def reinstate_catalog_product(
        self,
        catalog_product_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Clears a RESTRICTED product back to ELIGIBLE or OUT_OF_STOCK depending on its
        current stock level.
        """
        return self._request(
            "POST",
            self._url("/catalog-products/%s/reinstate" % catalog_product_id),
            payload=payload or {},
            headers=headers,
        )

    def delist_catalog_product(
        self,
        catalog_product_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Permanently delists a product; DELISTED is terminal and removes every
        assignment.
        """
        return self._request(
            "POST",
            self._url("/catalog-products/%s/delist" % catalog_product_id),
            payload=payload or {},
            headers=headers,
        )

    def create_product_assignment(
        self,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Attaches a catalog product to a line item, optionally as the hero SKU."""
        return self._request(
            "POST",
            self._url("/product-assignments"),
            payload=payload or {},
            headers=headers,
        )

    def list_product_assignments(
        self,
        headers: Optional[dict] = None,
        **params: Any,
    ) -> Any:
        """Lists product assignments, filterable by line item, catalog product and status.
        """
        return self._request(
            "GET",
            self._url("/product-assignments"),
            headers=headers,
            params=params or None,
        )

    def get_product_assignment(
        self,
        product_assignment_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one product assignment including its relevance_contribution."""
        return self._request(
            "GET",
            self._url("/product-assignments/%s" % product_assignment_id),
            headers=headers,
        )

    def delete_product_assignment(
        self,
        product_assignment_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Removes a product assignment; the last ACTIVE hero assignment of a non-DRAFT
        line item cannot be removed.
        """
        return self._request(
            "DELETE",
            self._url("/product-assignments/%s" % product_assignment_id),
            headers=headers,
        )

    def create_auction_event(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Opens a sponsored placement auction for one slot and shopper request context."""
        return self._request(
            "POST",
            self._url("/auction-events"),
            payload=payload or {},
            headers=headers,
        )

    def list_auction_events(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists auction events, filterable by slot, winning line item and status."""
        return self._request(
            "GET",
            self._url("/auction-events"),
            headers=headers,
            params=params or None,
        )

    def get_auction_event(
        self,
        auction_event_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one auction event with winner_score, second_best_score and
        clearing_price_cents.
        """
        return self._request(
            "GET",
            self._url("/auction-events/%s" % auction_event_id),
            headers=headers,
        )

    def rank_auction_event(
        self,
        auction_event_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Runs the ordered eligibility filter chain and relevance-adjusted ranking over
        every candidate line item on the slot, materialising one AuctionBid row per
        candidate.
        """
        return self._request(
            "POST",
            self._url("/auction-events/%s/rank" % auction_event_id),
            payload=payload or {},
            headers=headers,
        )

    def award_auction_event(
        self,
        auction_event_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Branching award fork from RANKED: a non-empty surviving pool awards the top-
        ranked bid at the second-price clearing price, an empty pool records NO_FILL.
        """
        return self._request(
            "POST",
            self._url("/auction-events/%s/award" % auction_event_id),
            payload=payload or {},
            headers=headers,
        )

    def settle_auction_event(
        self,
        auction_event_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Settles an AWARDED or NO_FILL auction, charging the winner and running the
        depth-3 budget-exhaustion cascade when the plan drains.
        """
        return self._request(
            "POST",
            self._url("/auction-events/%s/settle" % auction_event_id),
            payload=payload or {},
            headers=headers,
        )

    def list_auction_bids(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists the materialised bid ledger, filterable by auction event and line item,
        exposing rank, outcome and filter_reason.
        """
        return self._request(
            "GET",
            self._url("/auction-bids"),
            headers=headers,
            params=params or None,
        )

    def get_auction_bid(self, auction_bid_id: str, headers: Optional[dict] = None) -> Any:
        """Reads one auction bid row with its raw bid, relevance score, quality-adjusted
        score and rank.
        """
        return self._request(
            "GET",
            self._url("/auction-bids/%s" % auction_bid_id),
            headers=headers,
        )

    def create_engagement_event(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Records an on-site impression or click, or an off-site view, against the winning
        line item of a settled auction.
        """
        return self._request(
            "POST",
            self._url("/engagement-events"),
            payload=payload or {},
            headers=headers,
        )

    def list_engagement_events(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists engagement events, filterable by line item, auction event, catalog product
        and type.
        """
        return self._request(
            "GET",
            self._url("/engagement-events"),
            headers=headers,
            params=params or None,
        )

    def get_engagement_event(
        self,
        engagement_event_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one engagement event with its billable_cents and shopper_hash."""
        return self._request(
            "GET",
            self._url("/engagement-events/%s" % engagement_event_id),
            headers=headers,
        )

    def create_attributed_sale(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Closes the loop by matching a retail order line back to an engagement event and
        crediting it under the campaign's attribution model.
        """
        return self._request(
            "POST",
            self._url("/attributed-sales"),
            payload=payload or {},
            headers=headers,
        )

    def list_attributed_sales(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists attributed sales, filterable by engagement event, line item, catalog
        product and restatement flag.
        """
        return self._request(
            "GET",
            self._url("/attributed-sales"),
            headers=headers,
            params=params or None,
        )

    def get_attributed_sale(
        self,
        attributed_sale_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one attributed sale with its applied model, weight and credited amount."""
        return self._request(
            "GET",
            self._url("/attributed-sales/%s" % attributed_sale_id),
            headers=headers,
        )

    def create_incrementality_study(
        self,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Designs a holdout study for a campaign under either GEO_HOLDOUT or USER_HOLDOUT,
        subject to the washout gap against every other live or published study.
        """
        return self._request(
            "POST",
            self._url("/incrementality-studies"),
            payload=payload or {},
            headers=headers,
        )

    def list_incrementality_studies(
        self,
        headers: Optional[dict] = None,
        **params: Any,
    ) -> Any:
        """Lists incrementality studies, filterable by campaign, superseded study, design
        method and status.
        """
        return self._request(
            "GET",
            self._url("/incrementality-studies"),
            headers=headers,
            params=params or None,
        )

    def get_incrementality_study(
        self,
        study_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one study with lift_pct, incremental_sales_cents, significance_score and
        significance_flag.
        """
        return self._request(
            "GET",
            self._url("/incrementality-studies/%s" % study_id),
            headers=headers,
        )

    def start_incrementality_study(
        self,
        study_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Starts a DESIGNED study once the clock has reached window_start_at, splitting
        exposed and control groups.
        """
        return self._request(
            "POST",
            self._url("/incrementality-studies/%s/start" % study_id),
            payload=payload or {},
            headers=headers,
        )

    def measure_incrementality_study(
        self,
        study_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Loads exposed and control outcomes for a RUNNING study whose window has elapsed
        and computes lift under the study's design variant.
        """
        return self._request(
            "POST",
            self._url("/incrementality-studies/%s/measure" % study_id),
            payload=payload or {},
            headers=headers,
        )

    def publish_incrementality_study(
        self,
        study_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Publishes a MEASURING study that cleared the significance threshold, writing its
        incremental result onto the campaign.
        """
        return self._request(
            "POST",
            self._url("/incrementality-studies/%s/publish" % study_id),
            payload=payload or {},
            headers=headers,
        )

    def invalidate_incrementality_study(
        self,
        study_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Invalidates a RUNNING, MEASURING or PUBLISHED study; invalidating a PUBLISHED
        study runs the depth-3 restatement cascade and a DATA_DEFECT reason returns it
        to MEASURING for re-measurement.
        """
        return self._request(
            "POST",
            self._url("/incrementality-studies/%s/invalidate" % study_id),
            payload=payload or {},
            headers=headers,
        )

    def create_invoice(self, payload: dict, headers: Optional[dict] = None) -> Any:
        """Opens a DRAFT invoice for one advertiser billing period, bound to the funding
        plan and the fiscal-period-matched trade fund account.
        """
        return self._request(
            "POST",
            self._url("/invoices"),
            payload=payload or {},
            headers=headers,
        )

    def list_invoices(self, headers: Optional[dict] = None, **params: Any) -> Any:
        """Lists invoices, filterable by advertiser, funding plan, trade fund account,
        period and status.
        """
        return self._request(
            "GET",
            self._url("/invoices"),
            headers=headers,
            params=params or None,
        )

    def get_invoice(self, invoice_id: str, headers: Optional[dict] = None) -> Any:
        """Reads one invoice with the full settlement waterfall decomposition and
        net_cash_due_cents.
        """
        return self._request(
            "GET",
            self._url("/invoices/%s" % invoice_id),
            headers=headers,
        )

    def issue_invoice(
        self,
        invoice_id: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """Issues a DRAFT invoice, running the ten pinned steps of
        invoice_settlement_waterfall over every PENDING_INVOICE campaign in the period.
        """
        return self._request(
            "POST",
            self._url("/invoices/%s/issue" % invoice_id),
            payload=payload or {},
            headers=headers,
        )

    def adjust_invoice(
        self,
        invoice_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Applies a credit adjustment to a DISPUTED invoice, bounded by
        MAX_ADJUSTMENT_ROUNDS, and re-runs the waterfall.
        """
        return self._request(
            "POST",
            self._url("/invoices/%s/adjust" % invoice_id),
            payload=payload or {},
            headers=headers,
        )

    def settle_invoice(
        self,
        invoice_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Settles an ISSUED or ADJUSTED invoice against an exact-amount payment."""
        return self._request(
            "POST",
            self._url("/invoices/%s/settle" % invoice_id),
            payload=payload or {},
            headers=headers,
        )

    def write_off_invoice(
        self,
        invoice_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Writes off an ISSUED or ADJUSTED invoice once WRITE_OFF_DAYS have passed since
        due_at; the write-off is the compensating transaction that restores the trade-
        fund invariant.
        """
        return self._request(
            "POST",
            self._url("/invoices/%s/write-off" % invoice_id),
            payload=payload or {},
            headers=headers,
        )

    def create_measurement_dispute(
        self,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Files a measurement dispute against an ISSUED or ADJUSTED invoice inside the
        dispute grace window, starting the reporting SLA clock.
        """
        return self._request(
            "POST",
            self._url("/measurement-disputes"),
            payload=payload or {},
            headers=headers,
        )

    def list_measurement_disputes(
        self,
        headers: Optional[dict] = None,
        **params: Any,
    ) -> Any:
        """Lists measurement disputes, filterable by invoice, disputed line item, category,
        status and breach flag.
        """
        return self._request(
            "GET",
            self._url("/measurement-disputes"),
            headers=headers,
            params=params or None,
        )

    def get_measurement_dispute(
        self,
        dispute_id: str,
        headers: Optional[dict] = None,
    ) -> Any:
        """Reads one dispute with its SLA clock, review rounds and awarded credit."""
        return self._request(
            "GET",
            self._url("/measurement-disputes/%s" % dispute_id),
            headers=headers,
        )

    def start_measurement_dispute_review(
        self,
        dispute_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Assigns an analyst to a SUBMITTED dispute and stamps the first response,
        stopping the SLA clock.
        """
        return self._request(
            "POST",
            self._url("/measurement-disputes/%s/start-review" % dispute_id),
            payload=payload or {},
            headers=headers,
        )

    def request_measurement_dispute_info(
        self,
        dispute_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Requests further evidence from an UNDER_REVIEW dispute, extending the SLA; the
        request/response cycle is bounded by MAX_INFO_REQUESTS.
        """
        return self._request(
            "POST",
            self._url("/measurement-disputes/%s/request-info" % dispute_id),
            payload=payload or {},
            headers=headers,
        )

    def provide_measurement_dispute_info(
        self,
        dispute_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Supplies the requested evidence, returning an INFO_REQUESTED dispute to
        UNDER_REVIEW.
        """
        return self._request(
            "POST",
            self._url("/measurement-disputes/%s/provide-info" % dispute_id),
            payload=payload or {},
            headers=headers,
        )

    def resolve_measurement_dispute(
        self,
        dispute_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Branching resolution fork from UNDER_REVIEW: UPHOLD awards credit and runs the
        depth-3 unwind cascade, REJECT closes the dispute with no credit.
        """
        return self._request(
            "POST",
            self._url("/measurement-disputes/%s/resolve" % dispute_id),
            payload=payload or {},
            headers=headers,
        )

    def escalate_measurement_dispute(
        self,
        dispute_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Escalates an UNDER_REVIEW, INFO_REQUESTED or REJECTED dispute to the next
        escalation level, re-opening the SLA clock at the escalated base hours.
        """
        return self._request(
            "POST",
            self._url("/measurement-disputes/%s/escalate" % dispute_id),
            payload=payload or {},
            headers=headers,
        )

    def withdraw_measurement_dispute(
        self,
        dispute_id: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> Any:
        """Withdraws a SUBMITTED, UNDER_REVIEW or INFO_REQUESTED dispute at the
        advertiser's request, restoring the invoice.
        """
        return self._request(
            "POST",
            self._url("/measurement-disputes/%s/withdraw" % dispute_id),
            payload=payload or {},
            headers=headers,
        )



# Module-level singleton. The server's lifecycle belongs to the test runner, which
# restarts it before every individual test, so a single client instance is safe.
api_client = RmnApiClient()
