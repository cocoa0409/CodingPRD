"""Committee submission gates (PRD §3.6): occupancy bands, forecast pinning,
deadline, eligible pool, and the capital budget cap."""
from test_helpers import (
    ApiErrorId,
    approve_and_ratify,
    assert_committee_review,
    assert_sales_forecast,
    create_committee_roster,
    create_draft_forecast,
    create_forecast_locked_site,
    create_in_committee_site,
    create_modeled_site,
    create_qualified_market,
    create_scored_site,
    create_stores,
    create_submit_committee_payload,
    get_success_data,
    lock_forecast,
    submit_to_committee,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
MANAGER = TEST_USERS["manager_headers"]

# ANALOG roster netting 1,000,000,000 cents for a STANDARD site.
NET_1B_STORES = (("B1", "STANDARD", 900000000), ("B2", "STANDARD", 1100000000))


def _net_1b_market(api, name):
    market = create_qualified_market(name=name)
    create_stores(market["id"], NET_1B_STORES)
    return market


class TestOccupancyRatioTieredBranching:
    """YELLOW band: ratio 1800 bp; the submission branch depends on
    chair_override."""

    def _yellow_forecast(self, api):
        market = _net_1b_market(api, "Metro Y")
        ctx = create_forecast_locked_site(
            market["id"],
            site_overrides={"address": "7 Pine Rd",
                            "asking_rent_psf_cents": 18000,
                            "cam_psf_cents": 0, "tax_psf_cents": 0},
        )
        return ctx

    def test_lock_computes_yellow_band_at_1800bp(self, api):
        """PRD §3.5: "`occupancy_ratio_bp` is the sum of the site's
        `asking_rent_psf_cents`, `cam_psf_cents`, and `tax_psf_cents`,
        multiplied by the `square_footage`, multiplied by 10,000, divided by
        the forecast's own `net_annual_sales_cents`, rounded half-up to an
        integer basis-point figure; the `occupancy_band` is `GREEN` at 1,500
        basis points or fewer, `YELLOW` from 1,501 through 2,200, and `RED` at
        2,201 or more."

        Design: Difficulty/combinatorial_formula/occupancy_ratio_tiered_branching
        """
        ctx = self._yellow_forecast(api)
        forecast = ctx["forecast"]
        assert_sales_forecast(forecast)
        assert forecast["net_annual_sales_cents"] == 1000000000
        # 18000 * 10000 sqft = 180000000; * 10000 / 1000000000 = 1800 bp.
        assert forecast["occupancy_ratio_bp"] == 1800
        assert forecast["occupancy_band"] == "YELLOW"

    def test_yellow_band_requires_chair_override(self, api):
        """PRD §3.6: "The occupancy gates then apply to the pinned forecast's
        band: a `RED` band blocks submission outright with
        `ERR_OCCUPANCY_RATIO_RED`, and a `YELLOW` band is admitted only when
        `chair_override` is true, else `ERR_CHAIR_OVERRIDE_REQUIRED`."

        Design: Difficulty/combinatorial_formula/occupancy_ratio_tiered_branching
        """
        ctx = self._yellow_forecast(api)
        roster = create_committee_roster(num_voters=0)
        denied = api.submit_site_to_committee(
            ctx["site"]["id"],
            create_submit_committee_payload(
                sales_forecast_id=ctx["forecast"]["id"],
                sponsor_member_id=roster["sponsor"]["id"],
            ),
            MANAGER,
        )
        validate_error(denied, ApiErrorId.ERR_CHAIR_OVERRIDE_REQUIRED)
        review = submit_to_committee(
            ctx["site"]["id"], ctx["forecast"]["id"], roster["sponsor"]["id"],
            chair_override=True,
        )
        assert_committee_review(review)
        assert review["review_status"] == "OPEN"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "IN_COMMITTEE"


class TestOccupancyRatioGreenBoundary:
    """Exactly 1500 bp is GREEN (inclusive) and submits with no override."""

    def _green_boundary_fixture(self, api):
        market = _net_1b_market(api, "Metro B1500")
        ctx = create_forecast_locked_site(
            market["id"],
            site_overrides={"address": "1500 Boundary Ln",
                            "asking_rent_psf_cents": 15000,
                            "cam_psf_cents": 0, "tax_psf_cents": 0},
        )
        roster = create_committee_roster(num_voters=0)
        return ctx, roster

    def test_ratio_exactly_1500_is_green(self, api):
        """PRD §3.5: "the `occupancy_band` is `GREEN` at 1,500 basis points or
        fewer, `YELLOW` from 1,501 through 2,200, and `RED` at 2,201 or more."

        Design: Difficulty/boundary_precision_check/occupancy_ratio_exactly_1500_is_green
        """
        ctx, _roster = self._green_boundary_fixture(api)
        forecast = ctx["forecast"]
        assert forecast["net_annual_sales_cents"] == 1000000000
        # 15000 * 10000 = 150000000; * 10000 / 1000000000 = exactly 1500 bp.
        assert forecast["occupancy_ratio_bp"] == 1500
        assert forecast["occupancy_band"] == "GREEN"

    def test_green_boundary_submits_without_override(self, api):
        """PRD §3.6: "The eligible voter pool — the count of `ACTIVE` members
        other than the sponsor — must contain at least one member, else
        `ERR_NO_ELIGIBLE_VOTERS`; this count is pinned on the review as
        `eligible_member_count` at creation, along with `quorum_count`, the
        smallest integer greater than or equal to two-thirds of the eligible
        count."
        PRD §3.6: "A passing submission creates the review in `OPEN` with its
        tallies (`approve_votes`, `reject_votes`, `abstain_votes`) at zero and
        `decided_outcome` unset, and moves the site from `FORECAST_LOCKED` to
        `IN_COMMITTEE`, advancing the site's `version`."

        Design: Difficulty/boundary_precision_check/occupancy_ratio_exactly_1500_is_green
        """
        ctx, roster = self._green_boundary_fixture(api)
        review = submit_to_committee(
            ctx["site"]["id"], ctx["forecast"]["id"], roster["sponsor"]["id"],
        )
        assert_committee_review(review)
        assert review["review_status"] == "OPEN"
        assert review["eligible_member_count"] == 1
        assert review["quorum_count"] == 1
        assert review["approve_votes"] == 0
        assert review["decided_outcome"] is None
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "IN_COMMITTEE"


class TestSubmitForecastGate:
    def _site_with_superseded_second_forecast(self, api):
        market = _net_1b_market(api, "Metro FK")
        ctx = create_scored_site(market["id"])
        f1 = create_draft_forecast(ctx["site"]["id"], ctx["model"]["id"],
                                   model_variant="ANALOG")
        f2 = create_draft_forecast(ctx["site"]["id"], ctx["model"]["id"],
                                   model_variant="GRAVITY")
        f1 = lock_forecast(f1["id"])
        roster = create_committee_roster(num_voters=0)
        site = validate_success(api.get_site(ctx["site"]["id"], ANALYST))
        return ctx, f1, f2, roster, site

    def test_lock_supersedes_sibling_draft(self, api):
        """PRD §3.5: "Locking supersedes every sibling forecast of the same
        site in `DRAFT` or `COMMITTEE_LOCKED`, and the site bubbles up from
        `SCORED` to `FORECAST_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/submit_requires_committee_locked_forecast_of_same_site
        """
        _ctx, f1, f2, _roster, site = (
            self._site_with_superseded_second_forecast(api)
        )
        assert f1["forecast_status"] == "COMMITTEE_LOCKED"
        reloaded_f2 = validate_success(api.get_sales_forecast(f2["id"], ANALYST))
        assert reloaded_f2["forecast_status"] == "SUPERSEDED"
        assert site["site_status"] == "FORECAST_LOCKED"

    def test_submit_referencing_superseded_forecast_rejected(self, api):
        """PRD §3.6: "The pinned forecast must be `COMMITTEE_LOCKED` and belong
        to the site, else `ERR_FORECAST_NOT_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/submit_requires_committee_locked_forecast_of_same_site
        """
        ctx, _f1, f2, roster, _site = (
            self._site_with_superseded_second_forecast(api)
        )
        resp = api.submit_site_to_committee(
            ctx["site"]["id"],
            create_submit_committee_payload(
                sales_forecast_id=f2["id"],
                sponsor_member_id=roster["sponsor"]["id"],
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_FORECAST_NOT_LOCKED)
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "FORECAST_LOCKED"
        reviews, meta = validate_paginated(api.list_committee_reviews(
            MANAGER, params={"site_id": ctx["site"]["id"]},
        ))
        assert meta["total_count"] == 0


class TestStateBeatsFiscalOnSubmit:
    """Site A is MODELED (state failure); the referenced forecast of site B is
    RED (fiscal failure) and belongs to another site (referential failure).
    The state layer is checked first."""

    def _setup(self, api):
        market = _net_1b_market(api, "Metro PC")
        site_a_ctx = create_modeled_site(market["id"], site_overrides={
            "address": "11 Alpha Way",
        })
        site_b_ctx = create_forecast_locked_site(
            market["id"],
            site_overrides={"address": "22 Beta Rd",
                            "asking_rent_psf_cents": 25000,
                            "cam_psf_cents": 0, "tax_psf_cents": 0},
        )
        roster = create_committee_roster(num_voters=0)
        return site_a_ctx, site_b_ctx, roster

    def test_submit_modeled_site_with_red_forecast_fails_state(self, api):
        """PRD §2.7: "Every request is validated against the following layers
        in the order listed; a failure at an earlier layer is reported and
        masks any failure a later layer would have produced."
        PRD §2.7: "a live resource in the wrong state yields
        `ERR_INVALID_STATE` (409)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_submit
        """
        site_a_ctx, site_b_ctx, roster = self._setup(api)
        assert site_a_ctx["site"]["site_status"] == "MODELED"
        assert site_b_ctx["forecast"]["occupancy_band"] == "RED"
        resp = api.submit_site_to_committee(
            site_a_ctx["site"]["id"],
            create_submit_committee_payload(
                sales_forecast_id=site_b_ctx["forecast"]["id"],
                sponsor_member_id=roster["sponsor"]["id"],
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_submit_leaves_no_review_for_site(self, api):
        """PRD §2.7: "Every request is validated against the following layers
        in the order listed; a failure at an earlier layer is reported and
        masks any failure a later layer would have produced."
        PRD §3.6: "A passing submission creates the review in `OPEN` with its
        tallies (`approve_votes`, `reject_votes`, `abstain_votes`) at zero and
        `decided_outcome` unset, and moves the site from `FORECAST_LOCKED` to
        `IN_COMMITTEE`, advancing the site's `version`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_submit
        """
        site_a_ctx, site_b_ctx, roster = self._setup(api)
        resp = api.submit_site_to_committee(
            site_a_ctx["site"]["id"],
            create_submit_committee_payload(
                sales_forecast_id=site_b_ctx["forecast"]["id"],
                sponsor_member_id=roster["sponsor"]["id"],
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        site = validate_success(api.get_site(site_a_ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "MODELED"
        _reviews, meta = validate_paginated(api.list_committee_reviews(
            MANAGER, params={"site_id": site_a_ctx["site"]["id"]},
        ))
        assert meta["total_count"] == 0


class TestRemainingSubmissionGates:
    def test_error_no_eligible_voters(self, api):
        """PRD §3.6: "The eligible voter pool — the count of `ACTIVE` members
        other than the sponsor — must contain at least one member, else
        `ERR_NO_ELIGIBLE_VOTERS`"

        Design: Corner/errors/error_no_eligible_voters
        """
        market = _net_1b_market(api, "Metro E6")
        ctx = create_forecast_locked_site(market["id"])
        sponsor = get_success_data(api.create_committee_member(
            {"display_name": "Sponsor Only"}, ADMIN,
        ))
        resp = api.submit_site_to_committee(
            ctx["site"]["id"],
            create_submit_committee_payload(
                sales_forecast_id=ctx["forecast"]["id"],
                sponsor_member_id=sponsor["id"],
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_VOTERS)
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "FORECAST_LOCKED"

    def test_error_deadline_in_past(self, api):
        """PRD §3.6: "The deadline must be strictly after the logical clock at
        submission, else `ERR_DEADLINE_IN_PAST`."
        PRD §2.8: "At server startup, before any clock operation, the logical
        clock reads exactly 2026-08-01T00:00:00Z, and it must not fall back to
        wall-clock time under any circumstance."

        Design: Corner/errors/error_deadline_in_past
        """
        market = _net_1b_market(api, "Metro E7")
        ctx = create_forecast_locked_site(market["id"])
        roster = create_committee_roster(num_voters=0)
        resp = api.submit_site_to_committee(
            ctx["site"]["id"],
            create_submit_committee_payload(
                sales_forecast_id=ctx["forecast"]["id"],
                sponsor_member_id=roster["sponsor"]["id"],
                expires_at="2026-07-01T00:00:00Z",
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_DEADLINE_IN_PAST)

    def test_error_occupancy_ratio_red_blocks_submit(self, api):
        """PRD §3.6: "The occupancy gates then apply to the pinned forecast's
        band: a `RED` band blocks submission outright with
        `ERR_OCCUPANCY_RATIO_RED`, and a `YELLOW` band is admitted only when
        `chair_override` is true, else `ERR_CHAIR_OVERRIDE_REQUIRED`."

        Design: Corner/errors/error_occupancy_ratio_red_blocks_submit
        """
        market = _net_1b_market(api, "Metro E15")
        ctx = create_forecast_locked_site(
            market["id"],
            site_overrides={"address": "8 Red Blvd",
                            "asking_rent_psf_cents": 25000,
                            "cam_psf_cents": 0, "tax_psf_cents": 0},
        )
        # 25000 * 10000 = 250000000; * 10000 / 1000000000 = 2500 bp -> RED.
        assert ctx["forecast"]["occupancy_ratio_bp"] == 2500
        assert ctx["forecast"]["occupancy_band"] == "RED"
        roster = create_committee_roster(num_voters=0)
        resp = api.submit_site_to_committee(
            ctx["site"]["id"],
            create_submit_committee_payload(
                sales_forecast_id=ctx["forecast"]["id"],
                sponsor_member_id=roster["sponsor"]["id"],
                chair_override=True,
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_OCCUPANCY_RATIO_RED)

    def test_budget_cap_inclusive_then_exceeded(self, api):
        """PRD §3.6: "Finally the capital gate: the market's
        `committed_capex_cents` plus the site's `build_cost_cents` must not
        exceed ninety percent of the market's `annual_capex_budget_cents` — the
        cap computed by multiplying the budget by 9,000 and dividing by 10,000,
        rounded half-up to whole cents — with the boundary inclusive; a deal
        that would breach the cap is rejected with `ERR_BUDGET_CAP_EXCEEDED`."

        Design: Corner/calculations/budget_cap_inclusive_then_exceeded
        """
        market = _net_1b_market(api, "Metro BC")
        # Site1 commits 1300000000 at ratify (cap is 2000000000 * 90%).
        ctx1 = create_in_committee_site(
            market_id=market["id"], stores=None, num_voters=0,
            site_overrides={"address": "1 First Ave",
                            "build_cost_cents": 1300000000},
        )
        roster = ctx1["roster"]
        approve_and_ratify(ctx1["review"]["id"], roster["chair"]["id"])
        market_after = get_success_data(api.get_market(market["id"], ADMIN))
        assert market_after["committed_capex_cents"] == 1300000000

        ctx2 = create_forecast_locked_site(
            market["id"], site_overrides={"address": "2 Second Ave"},
        )
        ctx3 = create_forecast_locked_site(
            market["id"], site_overrides={"address": "3 Third Ave",
                                          "build_cost_cents": 500000001},
        )
        # 1300000000 + 500000000 == 1800000000 == cap (inclusive) -> admitted.
        review2 = submit_to_committee(
            ctx2["site"]["id"], ctx2["forecast"]["id"], roster["sponsor"]["id"],
        )
        assert review2["review_status"] == "OPEN"
        # 1300000000 + 500000001 > 1800000000 by one cent -> rejected.
        resp = api.submit_site_to_committee(
            ctx3["site"]["id"],
            create_submit_committee_payload(
                sales_forecast_id=ctx3["forecast"]["id"],
                sponsor_member_id=roster["sponsor"]["id"],
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_CAP_EXCEEDED)
        market_final = get_success_data(api.get_market(market["id"], ADMIN))
        assert market_final["committed_capex_cents"] == 1300000000, (
            "submission alone commits nothing; only ratification posts capital"
        )
