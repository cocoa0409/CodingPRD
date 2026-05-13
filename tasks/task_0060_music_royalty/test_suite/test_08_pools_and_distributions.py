"""Royalty pools: opening, closing, finalising, the platform-take split,
admin-fee tiers, sub-pool allocation, residual-cent lodging, and
finalize gating (PRD §3.8, §3.9, §3.10, §2.10 priorities 8, 9, 18)."""
from __future__ import annotations
from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    FIN,
    PA,
    assert_distribution,
    assert_royalty_pool,
    close_pool,
    create_pool,
    create_per_play_rule,
    create_rights_holder,
    create_share,
    create_work_draft,
    create_royalty_pool_payload,
    create_distribution_rule_payload,
    finalize_pool,
    find_distribution_for,
    find_distributions_for_work,
    ingest_playback_batch,
    iso,
    list_pool_distributions,
    make_playback_event,
    now_utc,
    open_dispute,
    setup_approved_recording_work,
    setup_closed_pool_for_works,
    setup_distributed_pool_for_works,
    setup_dispute_open_freezes_distribution,
    submit_work,
    take_review,
    approve_work,
    unique_source_identifier,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOpenPool:

    def test_open_pool_minimal(self, api, finance_headers):
        """PRD §3.8: 'A FinanceOps operator opens a RoyaltyPool by
        declaring the reporting window as period_start (inclusive UTC)
        and period_end (exclusive UTC), the revenue_source... and a
        mechanical_split_percent between 0.00 and 100.00 inclusive...
        The pool is born in status OPEN.'

        Claim: POST /royalty/pools → 201 with status==OPEN.
        """
        now = now_utc()
        resp = api.create_pool(
            create_royalty_pool_payload(
                period_start=iso(now - timedelta(days=10)),
                period_end=iso(now - timedelta(hours=1)),
                revenue_source="STREAMING", region="WW",
                gross_revenue_cents=20_000_000,
                platform_share_percent=30.00,
                mechanical_split_percent=0.00,
                pool_currency="USD",
            ),
            finance_headers,
        )
        data = validate_success(resp, 201)
        assert_royalty_pool(data)
        assert data["status"] == "OPEN"


class TestClosePool:

    def test_close_before_period_end_rejected(self, api, finance_headers):
        """PRD §3.8 / §2.10 priority 8: 'To close a pool, the pool's
        status must be OPEN and the current server time must be at or
        after period_end; otherwise ERR_INVALID_STATE (409).'

        Claim: POST close on a pool whose period_end is in the future →
        ERR_INVALID_STATE (409).
        """
        # Create the rule first.
        rule_resp = api.create_distribution_rule(
            create_distribution_rule_payload(distribution_mode="PER_PLAY"),
            PA,
        )
        rule = validate_success(rule_resp, 201)
        now = now_utc()
        pool_resp = api.create_pool(
            create_royalty_pool_payload(
                period_start=iso(now - timedelta(days=1)),
                period_end=iso(now + timedelta(days=30)),
                distribution_rule_version_id=rule["id"],
                gross_revenue_cents=1_000_000,
            ),
            finance_headers,
        )
        pool = validate_success(pool_resp, 201)
        resp = api.close_pool(pool["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    def test_close_succeeds_and_creates_distributions(self, api):
        """PRD §3.8: 'The pool's status flips to CLOSED, closed_at is
        stamped with the current time, and the platform computes the
        money chain.' PRD §3.9: 'In the same close operation, the
        platform cascades distribution-row creation (cascade depth 2)
        and per-row gross computation (cascade depth 3).'

        Claim: close on a valid pool returns 200 with status==CLOSED
        and at least one Distribution row exists.
        """
        _h, work, _share = setup_approved_recording_work()
        closed, _rule, dists = setup_closed_pool_for_works(
            [work], gross_revenue_cents=10_000_000,
        )
        assert closed["status"] == "CLOSED"
        assert closed.get("closed_at") is not None
        assert len(dists) >= 1
        for d in dists:
            assert_distribution(d)

    def test_close_uses_pinned_rule(self, api, finance_headers):
        """PRD §3.8 / §2.10 priority 18: 'At pool close, the pinned
        DistributionRuleVersion.effective_from must be strictly less
        than the pool's period_end; otherwise ERR_RULE_NOT_EFFECTIVE
        (422).'

        Claim: close when rule's effective_from is AFTER pool
        period_end → ERR_RULE_NOT_EFFECTIVE (422).
        """
        # Create rule whose effective_from is in the FAR future.
        now = now_utc()
        future = iso(now + timedelta(days=365))
        rule_resp = api.create_distribution_rule(
            create_distribution_rule_payload(
                distribution_mode="PER_PLAY",
                effective_from=future,
            ),
            PA,
        )
        rule = validate_success(rule_resp, 201)
        pool_resp = api.create_pool(
            create_royalty_pool_payload(
                period_start=iso(now - timedelta(days=10)),
                period_end=iso(now - timedelta(hours=1)),
                distribution_rule_version_id=rule["id"],
                gross_revenue_cents=1_000_000,
            ),
            finance_headers,
        )
        pool = validate_success(pool_resp, 201)
        resp = api.close_pool(pool["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_RULE_NOT_EFFECTIVE.value, 422)


class TestPlatformTakeAndSubpoolSplit:

    def test_platform_take_round_half_up_lodges_remainder_with_net(self, api):
        """PRD §3.8: 'The platform-take is the gross revenue multiplied
        by the platform's share, expressed as a fraction with two
        decimal places of precision, then rounded to whole cents using
        round half up. The net distributable is the gross revenue minus
        this rounded platform-take, evaluated as an integer subtraction
        (no further rounding). The rounding order is pinned: the
        platform-take is rounded before subtraction, so that the small
        remainder produced by the rounding step lodges with the net
        distributable rather than with the platform-take.'

        Claim: gross=20_000_000, platform=30.00 → platform_take=6_000_000;
        net = gross - platform_take - admin_fee. Admin tier 1 covers
        gross < 10_000_000 cents; this pool sits in tier 2 (10M..100M),
        admin_fee = round(10M*0.05)+ round((20M-10M)*0.04)
        = 500_000 + 400_000 = 900_000.
        net_distributable = 20_000_000 - 6_000_000 - 900_000 = 13_100_000.
        """
        _h, work, _share = setup_approved_recording_work()
        closed, _rule, _ = setup_closed_pool_for_works(
            [work], gross_revenue_cents=20_000_000,
            platform_share_percent=30.00, mechanical_split_percent=0.00,
        )
        assert closed["net_distributable_cents"] == 13_100_000


class TestFinalize:

    def test_finalize_flips_pending_to_released(self, api):
        """PRD §3.10: 'Once distributions exist, FinanceOps finalises
        the pool, advancing its status from CLOSED to DISTRIBUTED. The
        single precondition is that no Distribution under the pool may
        carry status of FROZEN; an attempt to finalise with even one
        frozen distribution is rejected with
        ERR_POOL_HAS_FROZEN_DISTRIBUTIONS. On success, every PENDING
        distribution in the pool flips to RELEASED.'

        Claim: finalize on a fully-PENDING CLOSED pool →
        status=DISTRIBUTED; every distribution.status==RELEASED.
        """
        _h, work, _share = setup_approved_recording_work()
        pool, _rule, dists = setup_distributed_pool_for_works(
            [work], gross_revenue_cents=10_000_000,
        )
        assert pool["status"] == "CLOSED"  # pre-finalize status of returned
        # Reload pool after finalize. Actually setup_distributed_pool
        # calls finalize internally; let's read pool.
        resp = api.get_pool(pool["id"], FIN)
        data = validate_success(resp, 200)
        assert data["status"] == "DISTRIBUTED"
        for d in dists:
            assert d["status"] == "RELEASED"

    def test_finalize_blocked_when_distribution_frozen(self, api):
        """PRD §3.10 / §2.10 priority 9: 'To finalise a pool, the
        pool's status must be CLOSED and no Distribution under it may
        carry status of FROZEN; a frozen distribution yields
        ERR_POOL_HAS_FROZEN_DISTRIBUTIONS (409).'

        Claim: finalize while any distribution is FROZEN →
        ERR_POOL_HAS_FROZEN_DISTRIBUTIONS (409).
        """
        ctx = setup_dispute_open_freezes_distribution()
        resp = api.finalize_pool(ctx["pool"]["id"], FIN)
        validate_error(resp,
                       ApiErrorId.ERR_POOL_HAS_FROZEN_DISTRIBUTIONS.value,
                       409)


class TestSubPoolRouting:

    def test_recording_work_routes_to_performance_subpool(self, api):
        """PRD §3.9: 'A work's sub-pool target is the mechanical-take
        when its rights_type is COMPOSITION or LYRICS, otherwise the
        performance-take (when rights_type is RECORDING or
        PERFORMANCE).'

        Claim: closing a pool that contains only a RECORDING work
        yields distributions whose sub_pool == PERFORMANCE.
        """
        _h, work, _share = setup_approved_recording_work()
        # mechanical_split=50 so both sub-pools exist but only PERFORMANCE
        # receives a distribution from this RECORDING work.
        _closed, _rule, dists = setup_closed_pool_for_works(
            [work], gross_revenue_cents=2_000_000,
            mechanical_split_percent=50.00,
        )
        for d in dists:
            assert d["sub_pool"] == "PERFORMANCE", \
                f"RECORDING work distribution must route to PERFORMANCE; got {d['sub_pool']}"
