"""Transitive cascades and ledger invariants: the four-link model-lock
cascade, ratify-driven capex commitment, approve/withdraw compensation, and
clock/withdrawal cascades (PRD §3.3, §3.6, §2.9, §2.8, §3.2)."""
from test_helpers import (
    approve_and_ratify,
    create_approved_site,
    create_draft_model,
    create_in_committee_site,
    create_loi_active_site,
    get_success_data,
    lock_model,
    run_ballot_plan,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
MANAGER = TEST_USERS["manager_headers"]


class TestModelLockSupersessionCascade:
    """Locking a second model for an IN_COMMITTEE site: model -> forecast ->
    review -> site, each link caused by the previous one."""

    def _lock_second_model(self, api):
        ctx = create_in_committee_site(num_voters=0)
        assert ctx["site"]["site_status"] == "IN_COMMITTEE"
        m2 = create_draft_model(
            ctx["site"]["id"], drive_time_minutes=10,
            trade_area_population=40000, per_capita_spend_cents=280000,
            cannibalization_variant="DISTANCE_DECAY",
        )
        m2 = lock_model(m2["id"], ctx["site"]["id"])
        return ctx, m2

    def test_model_and_forecast_links_supersede(self, api):
        """PRD §3.3: "Any other `LOCKED` model of the same site becomes
        `SUPERSEDED` (first link)."
        PRD §3.3: "Every sales forecast whose pinned `trade_area_model_id` is a
        just-superseded model and whose status is `DRAFT` or
        `COMMITTEE_LOCKED` becomes `SUPERSEDED` (second link)."

        Design: Difficulty/transitive_cascade/model_lock_supersession_cascade
        """
        ctx, m2 = self._lock_second_model(api)
        assert m2["model_status"] == "LOCKED"
        m1 = validate_success(api.get_trade_area_model(ctx["model"]["id"], ANALYST))
        assert m1["model_status"] == "SUPERSEDED"
        forecast = validate_success(
            api.get_sales_forecast(ctx["forecast"]["id"], ANALYST)
        )
        assert forecast["forecast_status"] == "SUPERSEDED"

    def test_review_expires_and_site_regresses_to_modeled(self, api):
        """PRD §3.3: "Any committee review pinning a just-superseded forecast,
        in `OPEN` or `DECIDED`, becomes `EXPIRED` (third link) — a decided
        review expired this way never reaches ratification."
        PRD §3.3: "Finally (fourth link), a site in `IN_COMMITTEE` whose review
        just expired falls back to `MODELED`, voiding the committee work
        product, and a site in `FORECAST_LOCKED` whose locked forecast was just
        superseded likewise falls back to `MODELED`, requiring a fresh forecast
        lock before resubmission."

        Design: Difficulty/transitive_cascade/model_lock_supersession_cascade
        """
        ctx, _m2 = self._lock_second_model(api)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "EXPIRED"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "MODELED"


class TestRatifyApproveCapexCascade:
    """E=4 review approved A/A/R/Ab (200 > 60*3 and 3 >= quorum 3); ratify
    applies the outcome and posts capital."""

    def _decided_approve_ctx(self, api):
        ctx = create_in_committee_site(num_voters=3)
        roster = ctx["roster"]
        voters = [v["id"] for v in roster["voters"]]
        plan = [
            (voters[0], "APPROVE", False),
            (voters[1], "APPROVE", False),
            (voters[2], "REJECT", False),
            (roster["chair"]["id"], "ABSTAIN", True),
        ]
        for resp in run_ballot_plan(ctx["review"]["id"], plan):
            validate_success(resp, expected_status=201)
        return ctx

    def test_ratify_applies_approve_to_review_and_site(self, api):
        """PRD §3.6: "Ratifying a `DECIDED` review moves it to the terminal
        `RATIFIED` state and applies the outcome: an approval moves the site
        from `IN_COMMITTEE` to `APPROVED` and commits capital by adding the
        site's `build_cost_cents` to the market's `committed_capex_cents`
        (exactly once, per the ledger invariant of §2.9)"

        Design: Difficulty/transitive_cascade/ratify_approve_capex_cascade
        """
        ctx = self._decided_approve_ctx(api)
        ratified = approve_and_ratify(
            ctx["review"]["id"], ctx["roster"]["chair"]["id"],
        )
        assert ratified["review_status"] == "RATIFIED"
        assert ratified["decided_outcome"] == "APPROVE"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "APPROVED"

    def test_ratify_posts_build_cost_to_market_ledger(self, api):
        """PRD §2.9: "`committed_capex_cents` is the sum of `build_cost_cents`
        over the market's sites in `APPROVED`, `LOI_ACTIVE`, `LEASE_EXECUTED`,
        `BUILD_OUT`, `OPEN`, `MEASURING`, or `UNDERPERFORMING` status."

        Design: Difficulty/transitive_cascade/ratify_approve_capex_cascade
        """
        ctx = self._decided_approve_ctx(api)
        before = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        assert before["committed_capex_cents"] == 0
        approve_and_ratify(ctx["review"]["id"], ctx["roster"]["chair"]["id"])
        after = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        assert after["committed_capex_cents"] == 500000000


class TestApproveWithdrawCapexConservation:
    def test_approve_commits_exactly_build_cost(self, api):
        """PRD §2.9: "The capital ledger obeys a strict compensation invariant:
        ratifying an approval adds the site's `build_cost_cents` to
        `committed_capex_cents` exactly once, and withdrawing that same site
        releases exactly that same amount, so an approve-then-withdraw sequence
        leaves `committed_capex_cents` unchanged."

        Design: Difficulty/compensating_invariant/approve_withdraw_capex_conservation
        """
        ctx = create_approved_site()
        market = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        assert market["committed_capex_cents"] == 500000000
        assert ctx["site"]["site_status"] == "APPROVED"

    def test_withdraw_releases_exactly_the_commitment(self, api):
        """PRD §3.2: "Withdrawal is compensating: if the site's prior state was
        `APPROVED`, `LOI_ACTIVE`, `LEASE_EXECUTED`, or `BUILD_OUT`, the
        market's `committed_capex_cents` is reduced by exactly the site's
        `build_cost_cents`, releasing the approval-time commitment; withdrawal
        from an earlier stage releases nothing."
        PRD §3.2: "The same action cascades downward — every LOI of the site in
        `DRAFT`, `SENT`, or `COUNTERED` moves to `WITHDRAWN`, and every
        committee review of the site in `OPEN` or `DECIDED` moves to `VOID`."

        Design: Difficulty/compensating_invariant/approve_withdraw_capex_conservation
        """
        ctx = create_approved_site()
        withdrawn = validate_success(api.withdraw_site(ctx["site"]["id"], MANAGER))
        assert withdrawn["site_status"] == "WITHDRAWN"
        market = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        assert market["committed_capex_cents"] == 0, (
            "approve-then-withdraw leaves committed_capex_cents unchanged"
        )
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "RATIFIED", (
            "only OPEN/DECIDED reviews void on withdrawal; RATIFIED is terminal"
        )


class TestClockAndWithdrawCascades:
    def test_review_expiry_clock_sweep_rejects_site(self, api):
        """PRD §2.8: "Every committee review in `OPEN` whose `expires_at`
        deadline has been passed moves to `EXPIRED`, and the site under that
        review falls from `IN_COMMITTEE` to `REJECTED`."

        Design: Corner/state_machines/review_expiry_clock_sweep_rejects_site
        """
        ctx = create_in_committee_site(num_voters=1)
        get_success_data(api.set_current_utc("2026-08-16T00:00:00Z", ADMIN))
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "EXPIRED"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "REJECTED"

    def test_withdraw_in_committee_voids_review(self, api):
        """PRD §3.2: "The same action cascades downward — every LOI of the site
        in `DRAFT`, `SENT`, or `COUNTERED` moves to `WITHDRAWN`, and every
        committee review of the site in `OPEN` or `DECIDED` moves to `VOID`."

        Design: Corner/state_machines/withdraw_in_committee_voids_review
        """
        ctx = create_in_committee_site(num_voters=1)
        withdrawn = validate_success(api.withdraw_site(ctx["site"]["id"], MANAGER))
        assert withdrawn["site_status"] == "WITHDRAWN"
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "VOID"
        market = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        assert market["committed_capex_cents"] == 0, (
            "an IN_COMMITTEE site never committed capital"
        )

    def test_withdraw_loi_active_cascades_to_sent_loi(self, api):
        """PRD §3.2: "The same action cascades downward — every LOI of the site
        in `DRAFT`, `SENT`, or `COUNTERED` moves to `WITHDRAWN`, and every
        committee review of the site in `OPEN` or `DECIDED` moves to `VOID`."
        PRD §3.2: "Withdrawal is compensating: if the site's prior state was
        `APPROVED`, `LOI_ACTIVE`, `LEASE_EXECUTED`, or `BUILD_OUT`, the
        market's `committed_capex_cents` is reduced by exactly the site's
        `build_cost_cents`, releasing the approval-time commitment"

        Design: Corner/state_machines/withdraw_loi_active_cascades_to_sent_loi
        """
        ctx = create_loi_active_site()
        assert ctx["site"]["site_status"] == "LOI_ACTIVE"
        assert ctx["loi"]["loi_status"] == "SENT"
        committed = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        assert committed["committed_capex_cents"] == 500000000
        withdrawn = validate_success(api.withdraw_site(ctx["site"]["id"], MANAGER))
        assert withdrawn["site_status"] == "WITHDRAWN"
        loi = validate_success(api.get_loi(ctx["loi"]["id"], MANAGER))
        assert loi["loi_status"] == "WITHDRAWN"
        market = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        assert market["committed_capex_cents"] == 0
