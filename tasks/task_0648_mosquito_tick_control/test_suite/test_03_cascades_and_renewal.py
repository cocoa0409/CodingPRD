"""Cascade and season-rollover tests.

Covers Difficulty rule transitive_cascade and the subscription<->visit half of
cross_entity_state_dependency, plus cross-cutting corner instances.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_account_holder_headers,
    create_active_subscription, list_recurring_visits, create_crew,
    create_route, dispatch_visit, log_application, complete_visit, set_clock,
    create_service_plan, create_account_holder, create_property, add_zone, create_subscription,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def _complete_n_recurring(ctx, crew, dates):
    visits = list_recurring_visits(ctx["sub"]["id"])
    for i, d in enumerate(dates):
        set_clock(f"{d}T08:00:00Z")
        v = visits[i]
        route = create_route(crew["id"], region="NE01", route_date=d)
        dispatch_visit(route["id"], v["id"], route["version"])
        log_application(v["id"], ctx["zones"][0]["id"], crew["id"])
        complete_visit(v["id"], crew["id"])


class TestCancelCascadeDepth3:
    """Cancelling an ACTIVE SEASONAL sub voids its invoice and credits a wallet refund."""

    def _setup(self):
        ctx = create_active_subscription(
            billing_mode="SEASONAL", region="NE01",
            zones=[{"label": "Yard", "zone_type": "TURF", "area_sqft": 4000}],
            season_start="2026-05-01", season_end="2026-08-14",
            plan_overrides={"tier": "PLUS", "includes_tick_barrier": False, "seasonal_price_cents": 30000})
        crew = create_crew(home_region_code="NE01")
        _complete_n_recurring(ctx, crew, ["2026-05-01", "2026-05-22"])
        set_clock("2026-06-15T08:00:00Z")
        return ctx

    def test_cancel_transitions_to_cancelled_and_voids_invoice(self, api):
        """
    PRD 3.7: "When the `billing_mode` is `SEASONAL` and a seasonal invoice exists in `ISSUED` status, that invoice is voided and a prorated refund is credited to the account holder's `wallet_credit_cents`."

        Design: Difficulty/transitive_cascade/cancel_cascade_subscription_to_visit_to_invoice_depth3
        """
        ctx = self._setup()
        ah = make_account_holder_headers(ctx["holder"]["id"])
        cancelled = validate_success(api.cancel_subscription(ctx["sub"]["id"], ah))
        assert cancelled["status"] == "CANCELLED"
        invs = get_success_data(api.list_subscription_invoices(ctx["sub"]["id"], BILLING))
        if isinstance(invs, dict) and "data" in invs:
            invs = invs["data"]
        seasonal = [i for i in invs if i["invoice_type"] == "SEASONAL"]
        assert len(seasonal) == 1
        assert seasonal[0]["status"] == "VOID", "the seasonal invoice must be voided"

    def test_cancel_credits_prorated_refund_to_wallet(self, api):
        """
    PRD 3.7: "The refund in cents is the seasonal invoice's `amount_cents` multiplied by the unserved count divided by the total, with the result floored toward zero to a whole cent."

        Design: Difficulty/transitive_cascade/cancel_cascade_subscription_to_visit_to_invoice_depth3
        """
        ctx = self._setup()
        ah = make_account_holder_headers(ctx["holder"]["id"])
        validate_success(api.cancel_subscription(ctx["sub"]["id"], ah))
        holder = get_success_data(api.get_account_holder(ctx["holder"]["id"], BILLING))
        assert holder["wallet_credit_cents"] == 18600, f"27900*4/6 floored == 18600, got {holder['wallet_credit_cents']}"


class TestOffSeasonCascadeDepth2:
    """Clock past season_end moves sub ACTIVE->OFF_SEASON, skips visits, mints successor."""

    def _setup(self):
        return create_active_subscription(
            billing_mode="PER_VISIT", region="NE01",
            season_start="2026-05-01", season_end="2026-05-22", auto_renew=True)

    def test_clock_advance_moves_subscription_off_season_and_skips_visits(self, api):
        """
    PRD 3.9: "As the subscription leaves its active season, every visit still in `SCHEDULED` or `WEATHER_HOLD` status is moved to `SKIPPED` in the off-season cascade."

        Design: Difficulty/transitive_cascade/offseason_cascade_subscription_to_visits_skip_depth2
        """
        ctx = self._setup()
        ah = make_account_holder_headers(ctx["holder"]["id"])
        set_clock("2026-05-23T00:00:00Z")
        sub = get_success_data(api.get_subscription(ctx["sub"]["id"], ah))
        assert sub["status"] == "OFF_SEASON"
        visits, _ = validate_paginated(api.list_subscription_visits(ctx["sub"]["id"], DISPATCHER))
        recurring = [v for v in visits if v["visit_kind"] == "RECURRING"]
        assert all(v["status"] == "SKIPPED" for v in recurring), f"got {[v['status'] for v in recurring]}"

    def test_offseason_mints_draft_successor_next_season(self, api):
        """
    PRD 3.9: "When the subscription's `auto_renew` is true, the system mints a successor subscription for the next season in `DRAFT` status: it carries the same plan and the same `billing_mode`, with both the `season_start_date` and `season_end_date` shifted forward by 365 days. The prior subscription's `renewed_into_subscription_id` is set to the successor's id."

        Design: Difficulty/transitive_cascade/offseason_cascade_subscription_to_visits_skip_depth2
        """
        ctx = self._setup()
        ah = make_account_holder_headers(ctx["holder"]["id"])
        set_clock("2026-05-23T00:00:00Z")
        sub = get_success_data(api.get_subscription(ctx["sub"]["id"], ah))
        successor_id = sub["renewed_into_subscription_id"]
        assert successor_id is not None, "a DRAFT successor must be minted"
        successor = get_success_data(api.get_subscription(successor_id, ah))
        assert successor["status"] == "DRAFT"
        assert successor["season_start_date"] == "2027-05-01", f"got {successor['season_start_date']}"


class TestOffSeasonBlockedByDispatchedVisit:
    """ACTIVE->OFF_SEASON blocked while any visit is DISPATCHED."""

    def _setup(self):
        ctx = create_active_subscription(billing_mode="PER_VISIT", region="NE01",
            season_start="2026-05-01", season_end="2026-05-22")
        crew = create_crew(home_region_code="NE01")
        set_clock("2026-05-01T08:00:00Z")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
        dispatch_visit(route["id"], rec["id"], route["version"])
        return ctx

    def test_close_season_blocked_while_visit_dispatched(self, api):
        """
    PRD 3.9: "The off-season transition is permitted only when the subscription is `ACTIVE`, the logical current date is strictly greater than the `season_end_date`, and no visit of the subscription is currently `DISPATCHED`."

        Design: Difficulty/cross_entity_state_dependency/offseason_blocked_by_dispatched_visit_subscription_visit_pair
        """
        ctx = self._setup()
        validate_error(api.close_season(ctx["sub"]["id"], PLATFORM), ApiErrorId.ERR_INVALID_STATE.value)

    def test_subscription_unchanged_after_blocked_close(self, api):
        """
    PRD 3.9: "When a platform operator advances the logical clock past an `ACTIVE` subscription's `season_end_date`, the system automatically transitions that subscription `ACTIVE → OFF_SEASON`; a platform operator may also force this transition directly on a single subscription."

        Design: Difficulty/cross_entity_state_dependency/offseason_blocked_by_dispatched_visit_subscription_visit_pair
        """
        ctx = self._setup()
        validate_error(api.close_season(ctx["sub"]["id"], PLATFORM), ApiErrorId.ERR_INVALID_STATE.value)
        ah = make_account_holder_headers(ctx["holder"]["id"])
        assert get_success_data(api.get_subscription(ctx["sub"]["id"], ah))["status"] == "ACTIVE"


def test_default_clock_is_april_first_2026(api):
    """
    PRD 2.4: "At server startup the logical current instant is exactly `2026-04-01T00:00:00Z`; before any clock is explicitly set, reads return precisely this default and the server never falls back to the real wall-clock."

    Design: Corner/cross_cutting_complexity_layers/default_clock_is_april_first_2026
    """
    plan = create_service_plan()
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code="NE01")
    add_zone(prop, holder["id"], zone_type="TURF", area_sqft=4000)
    sub = create_subscription(prop["id"], plan["id"], holder["id"], billing_mode="PER_VISIT")
    ah = make_account_holder_headers(holder["id"])
    activated = validate_success(api.activate_subscription(sub["id"], ah))
    assert activated["status"] == "ACTIVE", "default clock 2026-04-01 is before season_end"
    _, meta = validate_paginated(api.list_subscription_visits(sub["id"], ah))
    assert meta["total_count"] == 6


def test_offseason_cascade_skips_only_nonterminal_visits(api):
    """
    PRD 3.9: "As the subscription leaves its active season, every visit still in `SCHEDULED` or `WEATHER_HOLD` status is moved to `SKIPPED` in the off-season cascade."

    Design: Corner/cross_cutting_complexity_layers/cascade_offseason_skips_only_nonterminal_visits
    """
    ctx = create_active_subscription(billing_mode="PER_VISIT", region="NE01",
        season_start="2026-05-01", season_end="2026-05-22", auto_renew=False)
    crew = create_crew(home_region_code="NE01")
    set_clock("2026-05-01T08:00:00Z")
    visits = list_recurring_visits(ctx["sub"]["id"])
    v1, v2 = visits[0], visits[1]
    route = create_route(crew["id"], region="NE01", route_date="2026-05-01")
    dispatch_visit(route["id"], v1["id"], route["version"])
    log_application(v1["id"], ctx["zones"][0]["id"], crew["id"])
    complete_visit(v1["id"], crew["id"])
    set_clock("2026-05-23T00:00:00Z")
    assert get_success_data(api.get_visit(v1["id"], DISPATCHER))["status"] == "COMPLETED"
    assert get_success_data(api.get_visit(v2["id"], DISPATCHER))["status"] == "SKIPPED"
    ah = make_account_holder_headers(ctx["holder"]["id"])
    assert get_success_data(api.get_subscription(ctx["sub"]["id"], ah))["status"] == "OFF_SEASON"
