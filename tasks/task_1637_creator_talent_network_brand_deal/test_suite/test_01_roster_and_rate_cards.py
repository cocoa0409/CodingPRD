"""Roster intake, rate-card computation, creator standing (PRD §3.1, §2.3)."""
import pytest

from test_helpers import (
    DEFAULT_CLOCK_ISO,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_creator,
    create_creator_payload,
    make_active_creator,
    make_active_deal,
    make_creator,
    parse_instant,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["talent_manager_headers"]


class TestCreatorOnboarding:
    def test_creator_create_initial_state_defaults(self, api):
        """PRD §3.1: "A newly onboarded creator lands in `APPLIED`, the first
        state of a lifecycle that runs `APPLIED` → `SCREENING` → `ACTIVE`, with
        `SUSPENDED` as a standing penalty and `EXITED` as the only terminal
        state."
        PRD §3.1: "`compliance_strikes`, initially zero, counts `ESCALATED`
        disclosure checks on the creator's deliverables"
        PRD §3.1: "The `lifetime_billed_cents` counter, also initially zero,
        accumulates the `fee_line_cents` of every invoice on the creator's
        deals that reaches `PAID`"
        PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and until the clock is first set it continues to
        read that default — there is no silent fallback to real time."

        Design: Corner/entities/creator_create_initial_state_defaults
        """
        res = api.create_creator(
            create_creator_payload(
                handle="ce1", email="ce1@x.com", niche="BEAUTY",
                primary_platform="INSTAGRAM", followers=5000,
                avg_views_30d=2000, engagement_rate_bps=300,
            ),
            TM,
        )
        creator = validate_success(res, 201)
        assert_creator(creator)
        assert creator["status"] == "APPLIED", "new creator opens in APPLIED"
        assert creator["compliance_strikes"] == 0
        assert creator["lifetime_billed_cents"] == 0
        assert creator["pending_disclosure_count"] == 0
        created = parse_instant(creator["created_at"])
        assert created == parse_instant(DEFAULT_CLOCK_ISO), (
            "created_at is stamped from the logical clock at its startup "
            f"default {DEFAULT_CLOCK_ISO}, got {creator['created_at']}"
        )

    def test_creator_create_missing_required_email_returns_validation(self, api):
        """PRD §3.1: "A `TalentManager` onboards each creator with a unique
        `handle`, a contact `email`, a content `niche` (one of `BEAUTY`,
        `FASHION`, `TECH`, `FINANCE`, `GAMING`, `FITNESS`, `FOOD`, `TRAVEL`,
        or `OTHER`), a `primary_platform` ... and three audience metrics"
        PRD §2.8: "Payload well-formedness: required fields present, enums
        valid, ranges valid — `period_end` later than `period_start`,
        `audited_views` not exceeding `views`, `reduction_pct` strictly
        between zero and one (else `ERR_VALIDATION`)."

        Design: Corner/entities/creator_create_missing_required_email_returns_validation
        """
        payload = create_creator_payload(handle="ce2")
        payload.pop("email")
        res = api.create_creator(payload, TM)
        validate_error(res, ApiErrorId.ERR_VALIDATION, 400)
        # Nothing persisted: the roster listing stays empty of that handle.
        data, meta = validate_paginated(api.list_creators(TM))
        assert all(c["handle"] != "ce2" for c in data)


class TestRateCardComputation:
    def test_rate_card_tier_multiplier_floor_on_activation(self, api):
        """PRD §3.1: "at least 100,000 but fewer than 1,000,000 prices at
        3,000 cents"
        PRD §3.1: "below 600 it is 1.15"
        PRD §3.1: "A niche multiplier applies next: 1.20 for `FINANCE` or
        `TECH`, 1.10 for `BEAUTY` or `FASHION`, and 1.00 for every other
        niche."
        PRD §3.1: "The `rate_card_cpm_cents` is the base CPM multiplied by
        the engagement multiplier and then by the niche multiplier, rounded
        half up to whole cents."
        PRD §3.1: "The `rate_card_flat_cents` — the per-deliverable flat fee —
        is `rate_card_cpm_cents` multiplied by `avg_views_30d` and divided by
        one thousand, rounded half up to whole cents"

        MID base 3000 x 1.15 (450bps) x 1.20 (TECH) = 4140; flat =
        4140 x 80000 / 1000 = 331200.

        Design: Difficulty/combinatorial_formula/rate_card_tier_multiplier_floor
        """
        creator = make_active_creator(
            handle="crc1", niche="TECH", primary_platform="TIKTOK",
            followers=250000, avg_views_30d=80000, engagement_rate_bps=450,
        )
        assert creator["status"] == "ACTIVE"
        assert creator["rate_card_cpm_cents"] == 4140, (
            f"expected cpm 3000*1.15*1.20 = 4140, got "
            f"{creator['rate_card_cpm_cents']}"
        )
        assert creator["rate_card_flat_cents"] == 331200, (
            f"expected flat 4140*80000/1000 = 331200, got "
            f"{creator['rate_card_flat_cents']}"
        )

    def test_rate_card_flat_floor_on_metrics_update(self, api):
        """PRD §3.1: "The same computation re-runs on every audience-metrics
        update, which carries `followers`, `avg_views_30d`, and
        `engagement_rate_bps` and bumps the creator's `version`."
        PRD §3.1: "and then raised to a floor of 50,000 cents whenever the
        computed value falls below that floor."

        Same cpm (4140) but avg_views_30d = 0 -> raw flat 0 -> clamped to the
        50,000-cent floor.

        Design: Difficulty/combinatorial_formula/rate_card_tier_multiplier_floor
        """
        creator = make_active_creator(
            handle="crc1b", niche="TECH", primary_platform="TIKTOK",
            followers=250000, avg_views_30d=80000, engagement_rate_bps=450,
        )
        version_before = creator["version"]
        res = api.patch_creator_metrics(
            creator["id"],
            {"followers": 250000, "avg_views_30d": 0,
             "engagement_rate_bps": 450},
            TM,
        )
        updated = validate_success(res, 200)
        assert updated["rate_card_cpm_cents"] == 4140, "cpm inputs unchanged"
        assert updated["rate_card_flat_cents"] == 50000, (
            f"floor clamps 0 to 50000, got {updated['rate_card_flat_cents']}"
        )
        assert updated["version"] == version_before + 1, (
            "metrics update bumps the creator's version"
        )


class TestRateCardFollowersBoundary:
    def test_followers_99999_stays_micro(self, api):
        """PRD §3.1: "at least 10,000 but fewer than 100,000 prices at 2,200
        cents"
        PRD §3.1: "below 300 it is 1.00"

        99,999 followers (< 100,000) with 100bps engagement and OTHER niche:
        2200 x 1.00 x 1.00 = 2200.

        Design: Difficulty/boundary_precision_check/rate_card_followers_boundary_100k
        """
        creator = make_active_creator(
            handle="crb5a", followers=99999, avg_views_30d=0,
            engagement_rate_bps=100, niche="OTHER",
        )
        assert creator["rate_card_cpm_cents"] == 2200, (
            f"99,999 followers is MICRO (2200), got "
            f"{creator['rate_card_cpm_cents']}"
        )

    def test_followers_exactly_100000_crosses_to_mid(self, api):
        """PRD §3.1: "at least 100,000 but fewer than 1,000,000 prices at
        3,000 cents"
        PRD §3.1: "The same computation re-runs on every audience-metrics
        update, which carries `followers`, `avg_views_30d`, and
        `engagement_rate_bps` and bumps the creator's `version`."

        The tier minimum is inclusive: exactly 100,000 followers prices MID.

        Design: Difficulty/boundary_precision_check/rate_card_followers_boundary_100k
        """
        creator = make_active_creator(
            handle="crb5b", followers=99999, avg_views_30d=0,
            engagement_rate_bps=100, niche="OTHER",
        )
        res = api.patch_creator_metrics(
            creator["id"],
            {"followers": 100000, "avg_views_30d": 0,
             "engagement_rate_bps": 100},
            TM,
        )
        updated = validate_success(res, 200)
        assert updated["rate_card_cpm_cents"] == 3000, (
            f"exactly 100,000 followers crosses into MID (3000), got "
            f"{updated['rate_card_cpm_cents']}"
        )


class TestCreatorListing:
    def test_creator_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; when omitted it defaults to 10, and it may not be lower
        than 1 or higher than 100. The `offset` parameter sets the number of
        items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/creator_list_pagination_envelope
        """
        for handle in ("cp1", "cp2", "cp3"):
            make_creator(handle=handle)

        res1 = api.list_creators(TM, params={"limit": 2, "offset": 0})
        body1 = res1.json()
        page1, meta1 = validate_paginated(res1)
        assert body1["response_type"] == "array"
        assert isinstance(body1["meta"]["api_request_id"], str)
        assert body1["meta"]["api_request_id"].startswith("req_")
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_creators(TM, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestCreatorExit:
    def test_creator_exit_with_active_deals_rejected(self, api):
        """PRD §3.1: "A creator leaves the roster by moving from `ACTIVE` or
        `SUSPENDED` to `EXITED` — but only while no deal naming that creator
        sits outside `COMPLETED` or `TERMINATED`; an exit attempted over live
        deals is rejected with `ERR_ACTIVE_DEALS_EXIST`."

        Design: Corner/validations/creator_exit_with_active_deals_rejected
        """
        ns = make_active_deal()
        res = api.transition_creator(ns.creator["id"], {"to_state": "EXITED"}, TM)
        validate_error(res, ApiErrorId.ERR_ACTIVE_DEALS_EXIST, 422)
        creator = validate_success(api.get_creator(ns.creator["id"], TM))
        assert creator["status"] == "ACTIVE", "rejected exit leaves creator ACTIVE"
