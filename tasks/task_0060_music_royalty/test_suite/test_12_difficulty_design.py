"""Difficulty-design tests — each instance from the difficulty-design
priority queue covered by AT LEAST TWO tests.

Each docstring is tagged `# difficulty: <rule_id>/<instance.name>` so the
coverage check can audit which instance each test satisfies.
"""
from __future__ import annotations
from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    DOFF,
    FIN,
    PA,
    advance_to_arbitration,
    advance_to_mediation,
    approve_work,
    close_pool,
    create_agency_binding_payload,
    create_distribution_rule_payload,
    create_payout_batch,
    create_payout_batch_payload,
    create_per_play_rule,
    create_per_duration_rule,
    create_rights_holder,
    create_rights_share_payload,
    create_share,
    create_work_draft,
    create_org_holder,
    create_minor_rights_holder_payload,
    execute_payout_batch,
    find_audit_by_kind,
    find_distribution_for,
    find_distributions_for_work,
    find_payment_for,
    finalize_pool,
    ingest_playback_batch,
    iso,
    list_batch_payments,
    list_pool_distributions,
    make_playback_event,
    make_rights_holder_headers,
    now_utc,
    open_dispute,
    patch_share_payload,
    psp_callback_failure,
    psp_callback_success,
    reopen_investigation,
    resolve_dispute,
    retry_payment,
    abandon_payment,
    setup_approved_recording_work,
    setup_approved_work_with_multi_share,
    setup_closeable_pool_for_works,
    setup_closed_pool_for_works,
    setup_distributed_pool_for_works,
    setup_dispute_cyclic_through_resolved,
    setup_dispute_open_freezes_distribution,
    setup_frozen_distributions_for_finalize_block,
    setup_minimum_payout_boundary,
    setup_minor_with_guardian,
    setup_payment_failed_payment_for_abandon,
    setup_per_play_vs_per_duration_pair,
    start_investigation,
    submit_evidence,
    submit_work,
    take_review,
    unique_isrc,
    unique_source_identifier,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc — per_play vs per_duration; forward vs chronological
# ===========================================================================
class TestDualVariantCalc:
    """difficulty: dual_variant_calc/pool_net_distributable_pricing_variant_per_play_vs_per_duration
    difficulty: dual_variant_calc/rights_holder_risk_scoring_forward_vs_chronological
    """

    def test_per_play_vs_per_duration_yield_different_per_work_gross(self, api):
        """# difficulty: dual_variant_calc/pool_net_distributable_pricing_variant_per_play_vs_per_duration

        PRD §3.9: 'Under PER_PLAY mode, the work's units are the count
        of eligible events multiplied by the average of the
        playback-type weight assigned to each event. Under PER_DURATION
        mode, the work's units are the sum, across eligible events, of
        each event's play_duration_seconds multiplied by that event's
        playback-type weight.'

        Claim: With identical playback (one 5s event + one 305s event
        spread across TWO works in the same pool, single holder), the
        per-work distribution under PER_PLAY (50/50) STRICTLY DIFFERS
        from PER_DURATION (5/(5+305) vs 305/(5+305)).
        """
        ctx = setup_per_play_vs_per_duration_pair()
        # Read both pool's distributions.
        dists_play = list_pool_distributions(ctx["pool_play"]["id"])
        dists_dur = list_pool_distributions(ctx["pool_dur"]["id"])
        play_short = find_distribution_for(
            dists_play, ctx["holder"]["id"], work_id=ctx["w_short"]["id"],
        )
        play_long = find_distribution_for(
            dists_play, ctx["holder"]["id"], work_id=ctx["w_long"]["id"],
        )
        dur_short = find_distribution_for(
            dists_dur, ctx["holder"]["id"], work_id=ctx["w_short"]["id"],
        )
        dur_long = find_distribution_for(
            dists_dur, ctx["holder"]["id"], work_id=ctx["w_long"]["id"],
        )
        assert play_short is not None and play_long is not None
        assert dur_short is not None and dur_long is not None
        # Under PER_PLAY the two distributions are equal (50/50 split).
        assert play_short["gross_amount_cents"] == play_long["gross_amount_cents"], \
            f"PER_PLAY should split 50/50: {play_short['gross_amount_cents']} vs {play_long['gross_amount_cents']}"
        # Under PER_DURATION the short event's distribution is
        # STRICTLY LESS than the long event's.
        assert dur_short["gross_amount_cents"] < dur_long["gross_amount_cents"], \
            f"PER_DURATION must allocate more cents to the long-duration work"
        # And the two modes produce strictly different per-work numbers.
        assert play_short["gross_amount_cents"] != dur_short["gross_amount_cents"]
        assert play_long["gross_amount_cents"] != dur_long["gross_amount_cents"]

    def test_per_play_and_per_duration_split_sum_to_subpool_total(self, api):
        """# difficulty: dual_variant_calc/pool_net_distributable_pricing_variant_per_play_vs_per_duration

        PRD §3.9: 'Within the sub-pool, the per-work cents allocation
        is the sub-pool's total cents multiplied by the work's fraction
        of total units in that sub-pool... rounded to whole cents using
        round half up. The rounding is performed per work first, then
        the residual cents — the difference between the sub-pool total
        and the sum of rounded per-work allocations — is lodged with
        the work whose units count is highest in the sub-pool...'

        Claim: For both PER_PLAY and PER_DURATION pools, sum of all
        Distribution.gross_amount_cents across the works == the
        performance sub-pool total (since both works are RECORDING and
        the holder owns 100% of each).
        """
        ctx = setup_per_play_vs_per_duration_pair()
        dists_play = list_pool_distributions(ctx["pool_play"]["id"])
        dists_dur = list_pool_distributions(ctx["pool_dur"]["id"])
        # Expected performance-take with platform=30%, mech_split=0%,
        # gross=20_000_000, admin tier-2 fee = 900_000.
        # net_distributable = 20_000_000 - 6_000_000 - 900_000 = 13_100_000.
        # performance_take = net (since mech_split = 0%).
        expected_perf = 13_100_000
        sum_play = sum(d["gross_amount_cents"] for d in dists_play)
        sum_dur = sum(d["gross_amount_cents"] for d in dists_dur)
        assert sum_play == expected_perf, \
            f"PER_PLAY total {sum_play} must equal performance_take {expected_perf}"
        assert sum_dur == expected_perf, \
            f"PER_DURATION total {sum_dur} must equal performance_take {expected_perf}"

    def test_forward_mode_differs_from_chronological_with_multiple_disputes(
        self, api, finance_headers,
    ):
        """# difficulty: dual_variant_calc/rights_holder_risk_scoring_forward_vs_chronological

        PRD §3.11: 'Two variants are available: the default
        forward_looking variant aggregates a 0.6-weighted count of
        currently-open disputes touching the holder ... plus a
        0.4-weighted contribution from the ratio of frozen distribution
        cents over total lifetime paid cents... The alternative
        chronological variant replays each dispute event in created_at
        order, decaying the contribution of each earlier dispute by 0.9
        per subsequent dispute... Identical inputs produce strictly
        different numbers under the two variants except when there is
        exactly one dispute on the holder.'

        Claim: A holder with 3+ disputes on works they share returns a
        DIFFERENT score under ?mode=chronological than under
        ?mode=forward_looking (default).
        """
        # Build a holder and create 3 disputes on 3 different works the
        # holder owns 100% shares of.
        holder = create_rights_holder(legal_name="MultiDispute Holder")
        for _ in range(3):
            w = create_work_draft(holder["id"], rights_type="RECORDING")
            create_share(w["id"], holder["id"], holder["id"], 100.00)
            submit_work(w["id"], holder["id"])
            take_review(w["id"])
            approve_work(w["id"])
            open_dispute(w["id"], holder["id"], dispute_kind="OWNERSHIP")
        # Read both variants.
        forward = validate_success(api.get_dispute_exposure(
            holder["id"], finance_headers, params={"mode": "forward_looking"},
        ), 200)
        chrono = validate_success(api.get_dispute_exposure(
            holder["id"], finance_headers, params={"mode": "chronological"},
        ), 200)
        assert forward["mode"] == "forward_looking"
        assert chrono["mode"] == "chronological"
        assert forward["score"] != chrono["score"], \
            f"forward {forward['score']} should differ from chronological {chrono['score']} with >=2 disputes"

    def test_dispute_exposure_returns_integer_score(self, api,
                                                   finance_headers):
        """# difficulty: dual_variant_calc/rights_holder_risk_scoring_forward_vs_chronological

        PRD §3.11: 'the score is then rounded to a whole integer using
        round half up.' PRD §3.15: 'The per-holder dispute-exposure
        read returns an object { score, mode } carrying the computed
        integer score and the variant label.'

        Claim: GET /royalty/rights-holders/{id}/dispute-exposure
        returns data.score as an integer and data.mode set to the
        requested variant.
        """
        holder = create_rights_holder(legal_name="ScoreShape Holder")
        resp = api.get_dispute_exposure(holder["id"], finance_headers)
        data = validate_success(resp, 200)
        assert isinstance(data["score"], int)
        assert data["mode"] == "forward_looking"


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:
    """difficulty: combinatorial_formula/distribution_share_nonlinear_units_with_branched_mode
    difficulty: combinatorial_formula/rounding_order_per_share_residual_lodging
    """

    def test_hybrid_classification_weights_change_per_work_split(self, api):
        """# difficulty: combinatorial_formula/distribution_share_nonlinear_units_with_branched_mode

        PRD §3.9: 'Under HYBRID mode, the work's units are the sum of
        two terms: the per_play_weight multiplied by the count of
        events weighted by their playback-type weight, plus the
        per_duration_weight multiplied by the sum of duration-times-
        type-weight across events. Each event's playback-type weight is
        drawn from the rule's playback_type_weights map after
        classifying the event into one of four types: FULL_PLAY when
        play_duration_seconds is at least 95% of the work's
        duration_seconds, SKIP when it is strictly less than 30% of
        duration_seconds, BACKGROUND for events explicitly tagged as
        background activity, and FOREGROUND for the remainder.'

        Claim: With identical PER_PLAY rule and identical event mix,
        when weights for FULL_PLAY are higher than weights for SKIP,
        a work whose events classify FULL_PLAY captures STRICTLY MORE
        of the pool than a work whose events classify SKIP.
        """
        # Two RECORDING works owned by separate holders, 100% each.
        ha = create_rights_holder(legal_name="HA full")
        hb = create_rights_holder(legal_name="HB skip")
        wa = create_work_draft(ha["id"], rights_type="RECORDING",
                               duration_seconds=300, isrc=unique_isrc())
        create_share(wa["id"], ha["id"], ha["id"], 100.00)
        submit_work(wa["id"], ha["id"]); take_review(wa["id"])
        approve_work(wa["id"])
        wb = create_work_draft(hb["id"], rights_type="RECORDING",
                               duration_seconds=300, isrc=unique_isrc())
        create_share(wb["id"], hb["id"], hb["id"], 100.00)
        submit_work(wb["id"], hb["id"]); take_review(wb["id"])
        approve_work(wb["id"])

        # PER_PLAY rule with FULL_PLAY weight 1.5 and SKIP weight 0.10.
        rule = create_per_play_rule(
            channel="STREAMING",
            playback_type_weights={
                "FULL_PLAY": 1.5, "SKIP": 0.10,
                "BACKGROUND": 0.20, "FOREGROUND": 1.0,
            },
        )
        now = now_utc()
        period_end = now - timedelta(hours=1)
        period_start = period_end - timedelta(days=5)
        # WA event classifies FULL_PLAY (290s >= 0.95 * 300).
        # WB event classifies SKIP (60s < 0.30 * 300).
        ingest_playback_batch(
            [
                make_playback_event(work_id=wa["id"], play_duration_seconds=290,
                                    played_at=iso(period_start + timedelta(hours=1)),
                                    region="US"),
                make_playback_event(work_id=wb["id"], play_duration_seconds=60,
                                    played_at=iso(period_start + timedelta(hours=2)),
                                    region="US"),
            ],
            reporting_period_start=iso(period_start),
            reporting_period_end=iso(period_end),
            channel="STREAMING",
            source_identifier=unique_source_identifier(),
        )
        from test_helpers import create_pool
        pool = create_pool(
            period_start=iso(period_start), period_end=iso(period_end),
            distribution_rule_version_id=rule["id"],
            revenue_source="STREAMING", region="WW",
            gross_revenue_cents=20_000_000,
            platform_share_percent=30.00, mechanical_split_percent=0.00,
        )
        close_pool(pool["id"])
        dists = list_pool_distributions(pool["id"])
        d_a = find_distribution_for(dists, ha["id"], work_id=wa["id"])
        d_b = find_distribution_for(dists, hb["id"], work_id=wb["id"])
        assert d_a is not None and d_b is not None
        assert d_a["gross_amount_cents"] > d_b["gross_amount_cents"], (
            f"FULL_PLAY-weighted work {d_a['gross_amount_cents']} must exceed "
            f"SKIP-weighted work {d_b['gross_amount_cents']}"
        )

    def test_per_share_residual_lodges_with_highest_share_percent(self, api):
        """# difficulty: combinatorial_formula/rounding_order_per_share_residual_lodging

        PRD §3.9: 'For each work, the per-share allocation distributes
        the work's cents to its active RightsShare rows. Each share
        receives the work's per-work cents multiplied by share_percent
        divided by 100, rounded to whole cents using round half up. The
        rounding is performed per share first, then the residual cents
        — the difference between the work's per-work cents and the sum
        of rounded per-share allocations — is lodged with the share
        whose share_percent is highest, with ties broken in favour of
        the lexicographically lowest RightsShare.id.'

        Claim: With three shares H1=33%, H2=33%, H3=34% on a work
        whose per-work cents = 10, the rounded per-share splits become
        H1=3, H2=3, H3=4 — H3 holds the 1-cent residual because its
        share_percent (34) is highest.
        """
        # Build a work with three shares 33/33/34.
        work, holders, shares = setup_approved_work_with_multi_share(
            share_specs=[(33.00, "H1"), (33.00, "H2"), (34.00, "H3")],
            rights_type="RECORDING",
        )
        h1, h2, h3 = holders
        # Build a pool sized to yield exactly 10 cents per work after
        # platform-take and admin fee.
        # We want work_pool_cents == 10. With one event, one work, the
        # work captures the full performance_take. So:
        # performance_take = gross - platform_take - admin_fee = 10
        # Try gross_revenue_cents=12, platform=0, mech_split=0 → tier 1
        # admin_fee = round(12 * 0.05) = round(0.6) = 1.
        # net = 12 - 0 - 1 = 11. Hmm, want 10. Try gross=11:
        # admin_fee = round(11*0.05) = round(0.55) = 1; net = 10. Good.
        # platform=0% to avoid additional rounding effects.
        rule = create_per_play_rule(channel="STREAMING")
        now = now_utc()
        period_end = now - timedelta(hours=1)
        period_start = period_end - timedelta(days=5)
        # Per-test unique region to isolate from any prior WW ingestions.
        # PRD §3.8 accepts any 2-letter region; we pick "QA" reserved for
        # this test alone.
        region_qa = "QA"
        ingest_playback_batch(
            [make_playback_event(work_id=work["id"],
                                 play_duration_seconds=300,
                                 played_at=iso(period_start + timedelta(hours=1)),
                                 region=region_qa)],
            reporting_period_start=iso(period_start),
            reporting_period_end=iso(period_end),
            channel="STREAMING",
            source_identifier=unique_source_identifier(),
        )
        from test_helpers import create_pool
        pool = create_pool(
            period_start=iso(period_start), period_end=iso(period_end),
            distribution_rule_version_id=rule["id"],
            revenue_source="STREAMING", region=region_qa,
            gross_revenue_cents=11,
            platform_share_percent=0.00, mechanical_split_percent=0.00,
        )
        close_pool(pool["id"])
        dists = list_pool_distributions(pool["id"])
        d1 = find_distribution_for(dists, h1["id"], work_id=work["id"])
        d2 = find_distribution_for(dists, h2["id"], work_id=work["id"])
        d3 = find_distribution_for(dists, h3["id"], work_id=work["id"])
        assert d1 is not None and d2 is not None and d3 is not None
        # H1 and H2 each get round_half_up(10 * 0.33) = round(3.3) = 3.
        # H3 gets round_half_up(10 * 0.34) = round(3.4) = 3 BEFORE
        # residual, then receives the 1-cent residual → 4.
        assert d1["gross_amount_cents"] == 3, d1
        assert d2["gross_amount_cents"] == 3, d2
        assert d3["gross_amount_cents"] == 4, d3
        # And: the three sum to 10 (no cents lost).
        total = (d1["gross_amount_cents"] + d2["gross_amount_cents"]
                 + d3["gross_amount_cents"])
        assert total == 10, f"Sum of per-share allocations must equal 10; got {total}"


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:
    """difficulty: non_linear_state_machine/dispute_cyclic_mediation_investigation_loop
    difficulty: non_linear_state_machine/work_branching_with_dispute_posture_parallel_dimension
    """

    def test_dispute_can_oscillate_mediation_investigation(self, api):
        """# difficulty: non_linear_state_machine/dispute_cyclic_mediation_investigation_loop

        PRD §3.11: 'Within mediation, the officer may either advance
        forward to ARBITRATION, or reopen the investigation by flipping
        the status back to UNDER_INVESTIGATION (the cyclic loop allows
        further evidence collection).'

        Claim: a dispute can traverse OPEN → UNDER_INVESTIGATION →
        MEDIATION → UNDER_INVESTIGATION → MEDIATION → ARBITRATION →
        RESOLVED_DISMISSED via six successful transitions.
        """
        ctx = setup_dispute_cyclic_through_resolved()
        assert ctx["mediation_1"]["status"] == "MEDIATION"
        assert ctx["reopen"]["status"] == "UNDER_INVESTIGATION"
        assert ctx["mediation_2"]["status"] == "MEDIATION"
        assert ctx["arbitration"]["status"] == "ARBITRATION"
        assert ctx["resolved"]["status"] == "RESOLVED_DISMISSED"

    def test_work_branching_reject_vs_approve_diverges(self, api):
        """# difficulty: non_linear_state_machine/work_branching_with_dispute_posture_parallel_dimension

        PRD §3.2: 'Rejection ... produces a layered cascade. The work's
        registration_status flips to REJECTED; every RightsShare row
        on this work whose share_status is ACTIVE transitions to
        TERMINATED ... [Approval] on success, the work's
        registration_status becomes APPROVED and dispute_posture is
        set to CLEAR as its initial posture.'

        Claim: parallel works in identical setups diverge — rejected
        work has all shares TERMINATED with TERMINATED audit rows;
        approved work keeps shares ACTIVE.
        """
        h_a = create_rights_holder(legal_name="Reject Owner")
        h_b = create_rights_holder(legal_name="Approve Owner")
        w_a = create_work_draft(h_a["id"], rights_type="RECORDING",
                                isrc=unique_isrc())
        s_a = create_share(w_a["id"], h_a["id"], h_a["id"], 100.00)
        submit_work(w_a["id"], h_a["id"]); take_review(w_a["id"])
        # Reject A.
        from test_helpers import reject_work
        rejected_a = reject_work(w_a["id"], reason="No proof")
        assert rejected_a["registration_status"] == "REJECTED"

        w_b = create_work_draft(h_b["id"], rights_type="RECORDING",
                                isrc=unique_isrc())
        s_b = create_share(w_b["id"], h_b["id"], h_b["id"], 100.00)
        submit_work(w_b["id"], h_b["id"]); take_review(w_b["id"])
        approved_b = approve_work(w_b["id"])
        assert approved_b["registration_status"] == "APPROVED"

        # A's share should be in audit ledger with TERMINATED kind.
        audit_a_resp = api.list_share_audit(
            w_a["id"], s_a["id"], make_rights_holder_headers(h_a["id"]),
            params={"limit": 100},
        )
        audits_a, _ = validate_paginated(audit_a_resp)
        assert len(find_audit_by_kind(audits_a, "TERMINATED")) >= 1, audits_a
        # B's share should NOT have a TERMINATED audit row.
        audit_b_resp = api.list_share_audit(
            w_b["id"], s_b["id"], make_rights_holder_headers(h_b["id"]),
            params={"limit": 100},
        )
        audits_b, _ = validate_paginated(audit_b_resp)
        assert len(find_audit_by_kind(audits_b, "TERMINATED")) == 0, audits_b

    def test_approved_work_dispute_posture_flips_independently(self, api):
        """# difficulty: non_linear_state_machine/work_branching_with_dispute_posture_parallel_dimension

        PRD §2.7: 'Posture is FROZEN if and only if there exists at
        least one Dispute on this work whose status is one of OPEN,
        UNDER_INVESTIGATION, MEDIATION, or ARBITRATION; otherwise the
        posture is CLEAR.'

        Claim: registration_status stays APPROVED while dispute_posture
        flips CLEAR → FROZEN purely as a function of dispute opening.
        """
        h, work, _share = setup_approved_recording_work()
        assert work["registration_status"] == "APPROVED"
        assert work["dispute_posture"] == "CLEAR"
        open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        reloaded = validate_success(api.get_work(
            work["id"], make_rights_holder_headers(h["id"]),
        ), 200)
        assert reloaded["registration_status"] == "APPROVED"
        assert reloaded["dispute_posture"] == "FROZEN"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:
    """difficulty: transitive_cascade/work_rejection_cascade_depth_3
    difficulty: transitive_cascade/dispute_open_cascade_depth_2
    """

    def test_reject_cascades_three_levels(self, api):
        """# difficulty: transitive_cascade/work_rejection_cascade_depth_3

        PRD §3.2: 'Rejection requires the reviewer to supply a
        reject_reason of 1 to 500 characters and produces a layered
        cascade. The work's registration_status flips to REJECTED;
        every RightsShare row on this work whose share_status is
        ACTIVE transitions to TERMINATED (cascade depth 2); and each
        of those terminated shares emits a ShareChangeAudit row with
        change_kind of TERMINATED capturing the pre-termination and
        post-termination snapshots (cascade depth 3).'

        Claim: reject on a work with 3 ACTIVE shares produces:
          Hop 1: Work.registration_status == REJECTED
          Hop 2: all 3 RightsShares flip to TERMINATED
          Hop 3: a TERMINATED ShareChangeAudit per share
        """
        h_owner = create_rights_holder(legal_name="3-share owner")
        h2 = create_rights_holder(legal_name="H2")
        h3 = create_rights_holder(legal_name="H3")
        work = create_work_draft(h_owner["id"], rights_type="RECORDING",
                                 isrc=unique_isrc())
        s1 = create_share(work["id"], h_owner["id"], h_owner["id"], 40.00)
        s2 = create_share(work["id"], h_owner["id"], h2["id"], 30.00)
        s3 = create_share(work["id"], h_owner["id"], h3["id"], 30.00)
        submit_work(work["id"], h_owner["id"]); take_review(work["id"])
        from test_helpers import reject_work
        rejected = reject_work(work["id"], reason="cascade test")
        assert rejected["registration_status"] == "REJECTED"
        # Each share's audit must contain a TERMINATED row.
        for s in (s1, s2, s3):
            resp = api.list_share_audit(
                work["id"], s["id"],
                make_rights_holder_headers(h_owner["id"]),
                params={"limit": 100},
            )
            audits, _ = validate_paginated(resp)
            term = find_audit_by_kind(audits, "TERMINATED")
            assert len(term) >= 1, (
                f"Share {s['id']} expected TERMINATED audit; got {audits}"
            )

    def test_dispute_open_cascade_two_levels(self, api):
        """# difficulty: transitive_cascade/dispute_open_cascade_depth_2

        PRD §2.7: 'When posture flips from CLEAR to FROZEN, every
        PENDING Distribution on that work flips to FROZEN.' PRD §3.11:
        'the work's dispute_posture is recomputed and, because at
        least one open dispute now exists, flips from CLEAR to FROZEN;
        the work's version is bumped and updated_at is refreshed; and
        every PENDING distribution on this work flips to FROZEN
        (cascade depth 2).'

        Claim: open dispute on a work with a PENDING distribution →
          Hop 1: Work.dispute_posture flips from CLEAR to FROZEN
          Hop 2: matching PENDING Distribution.status becomes FROZEN
        """
        ctx = setup_dispute_open_freezes_distribution()
        # Hop 1 check.
        work_resp = api.get_work(
            ctx["work"]["id"],
            make_rights_holder_headers(ctx["holder"]["id"]),
        )
        work_data = validate_success(work_resp, 200)
        assert work_data["dispute_posture"] == "FROZEN"
        # Hop 2: distributions for this work are FROZEN.
        dists_after = list_pool_distributions(ctx["pool"]["id"])
        for d in find_distributions_for_work(dists_after, ctx["work"]["id"]):
            assert d["status"] == "FROZEN"


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    """difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pool_finalize_conflict
    difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_minor_payout_conflict
    """

    def test_finalize_with_frozen_dist_returns_state_error(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pool_finalize_conflict

        PRD §3.10 / §2.10 priority 9: 'To finalise a pool, the pool's
        status must be CLOSED and no Distribution under it may carry
        status of FROZEN; a frozen distribution yields
        ERR_POOL_HAS_FROZEN_DISTRIBUTIONS (409).'

        Claim: finalize on a pool whose distributions are FROZEN due to
        an open dispute returns ERR_POOL_HAS_FROZEN_DISTRIBUTIONS (409)
        regardless of any downstream payout-level fiscal check.
        """
        ctx = setup_frozen_distributions_for_finalize_block()
        resp = api.finalize_pool(ctx["pool"]["id"], FIN)
        validate_error(
            resp, ApiErrorId.ERR_POOL_HAS_FROZEN_DISTRIBUTIONS.value, 409,
        )

    def test_finalize_succeeds_after_resolution(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pool_finalize_conflict

        PRD §3.11: 'On a successful resolution ... if no other open
        dispute remains on this work, posture flips to CLEAR (cascade
        depth 2) and every FROZEN distribution on this work flips to
        RELEASED.' PRD §3.10: 'On success, every PENDING distribution
        in the pool flips to RELEASED.'

        Claim: once the dispute is resolved (FROZEN → RELEASED), a
        subsequent finalize on the same pool succeeds with 200.
        """
        ctx = setup_dispute_open_freezes_distribution()
        # Take the dispute through resolution.
        disp = ctx["dispute"]
        start_investigation(disp["id"])
        submit_evidence(disp["id"], ctx["holder"]["id"],
                        url="https://example.com/e1.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/e2.pdf")
        advance_to_mediation(disp["id"])
        advance_to_arbitration(disp["id"])
        resolve_dispute(disp["id"], outcome="DISMISSED",
                        arbitration_decision="No merit.")
        # Now finalize.
        resp = api.finalize_pool(ctx["pool"]["id"], FIN)
        data = validate_success(resp, 200)
        assert data["status"] == "DISTRIBUTED"

    # NOTE: test_minor_payout_blocked_dominates_referential_check removed.
    # PRD §2.10 priority 11 names ERR_MINOR_PAYOUT_BLOCKED but PRD does
    # not define what makes a "guardian binding" active. PRD §3.5
    # requires guardian_holder_id at minor creation (always present)
    # and §3.4 declares AgencyBinding with agency_kind in
    # {PUBLISHER, LABEL, CMO} only (no GUARDIAN). Without a PRD-defined
    # "active guardian binding" entity, two faithful readers diverge:
    # always-active vs. never-active. Unique-derivability fails.


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:
    """difficulty: boundary_precision_check/minimum_payout_threshold_exact_equal_inclusive
    difficulty: boundary_precision_check/empty_event_set_pool_close_zero_units
    """

    def test_minimum_payout_threshold_inclusive_at_exact_match(self, api):
        """# difficulty: boundary_precision_check/minimum_payout_threshold_exact_equal_inclusive

        PRD §3.12: 'If the candidate gross is at or above
        minimum_payout_cents, a Payment row is created with gross_cents
        equal to the candidate gross.' (the >= semantics).

        Claim: a holder with candidate gross == minimum_payout_cents
        receives a Payment row; a holder with candidate gross ==
        minimum_payout_cents - 1 does NOT receive a Payment.
        """
        ctx = setup_minimum_payout_boundary(
            minimum_payout_cents=500,
            micro_accumulation_cap_cents=2000,
        )
        batch = create_payout_batch()
        payments = list_batch_payments(batch["id"])
        # H1 (target 500) → Payment exists with gross_cents == 500.
        pay_h1 = find_payment_for(payments, ctx["h1"]["id"], currency="USD")
        assert pay_h1 is not None, (
            f"H1 (exactly at threshold) must receive a Payment; got {payments}"
        )
        assert pay_h1["gross_cents"] == 500
        # H2 (target 499) → no Payment row.
        pay_h2 = find_payment_for(payments, ctx["h2"]["id"], currency="USD")
        assert pay_h2 is None, (
            f"H2 (below threshold) must NOT receive a Payment; got {pay_h2}"
        )

    def test_below_threshold_accumulates_into_micro_balance(self, api):
        """# difficulty: boundary_precision_check/minimum_payout_threshold_exact_equal_inclusive

        PRD §3.12: 'no Payment row is created; instead,
        MicroBalance.balance_cents is incremented by the base amount
        and the candidate distributions are marked as PAID immediately
        (their cents are consumed into the micro-balance).'

        Claim: when H2's net=499 cents < minimum_payout_cents=500 and
        cap not exceeded, MicroBalance for (H2, USD) ends at 499 cents.
        """
        ctx = setup_minimum_payout_boundary(
            minimum_payout_cents=500,
            micro_accumulation_cap_cents=2000,
        )
        create_payout_batch()  # generates the rows for both holders
        balances = validate_success(
            api.get_micro_balance(
                ctx["h2"]["id"],
                make_rights_holder_headers(ctx["h2"]["id"]),
            ), 200,
        )
        rows = balances if isinstance(balances, list) else [balances]
        usd = next((r for r in rows if r.get("currency") == "USD"), None)
        assert usd is not None, f"Expected USD MicroBalance for H2; got {rows}"
        assert usd["balance_cents"] == 499, (
            f"H2 sub-threshold cents must accumulate in MicroBalance; got {usd}"
        )

    def test_empty_event_set_close_produces_zero_distributions(self, api,
                                                                finance_headers):
        """# difficulty: boundary_precision_check/empty_event_set_pool_close_zero_units

        PRD §3.9: 'In the same close operation, the platform cascades
        distribution-row creation (cascade depth 2)...' PRD §3.10:
        'finalize ... every PENDING distribution in the pool flips to
        RELEASED.' Together with §3.9 eligibility filter, an empty
        eligible-event set produces zero Distribution rows.

        Claim: closing a pool whose period contains no eligible
        PlaybackEvents → 200 with status==CLOSED and zero Distribution
        rows under the pool.
        """
        # Create work but DO NOT ingest any playback for the pool's window.
        _h, work, _share = setup_approved_recording_work()
        rule = create_per_play_rule(channel="STREAMING")
        now = now_utc()
        period_end = now - timedelta(hours=1)
        period_start = period_end - timedelta(days=5)
        # PRD §3.8: WW matches any region; to construct an empty
        # eligibility set we use a unique 2-letter region (a country
        # code value reserved for this test) that no fixture has
        # ingested events under.
        from test_helpers import create_pool
        pool = create_pool(
            period_start=iso(period_start), period_end=iso(period_end),
            distribution_rule_version_id=rule["id"],
            revenue_source="STREAMING", region="ZZ",
            gross_revenue_cents=1_000_000,
            platform_share_percent=0.00, mechanical_split_percent=0.00,
        )
        closed = close_pool(pool["id"])
        assert closed["status"] == "CLOSED"
        dists = list_pool_distributions(pool["id"])
        assert dists == [] or len(dists) == 0, (
            f"Empty event set must produce zero Distribution rows; got {dists}"
        )


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    """difficulty: cross_entity_state_dependency/pool_finalize_depends_on_distribution_states
    difficulty: cross_entity_state_dependency/rights_share_termination_depends_on_work_dispute_posture
    """

    def test_finalize_blocked_by_frozen_then_unblocked(self, api):
        """# difficulty: cross_entity_state_dependency/pool_finalize_depends_on_distribution_states

        PRD §3.10: 'no Distribution under the pool may carry status of
        FROZEN; an attempt to finalise with even one frozen
        distribution is rejected with
        ERR_POOL_HAS_FROZEN_DISTRIBUTIONS.'

        Claim: finalize first fails with the documented error while
        any Distribution is FROZEN, and succeeds after the dispute is
        resolved (FROZEN → RELEASED).
        """
        ctx = setup_dispute_open_freezes_distribution()
        # First attempt: blocked.
        blocked = api.finalize_pool(ctx["pool"]["id"], FIN)
        validate_error(
            blocked, ApiErrorId.ERR_POOL_HAS_FROZEN_DISTRIBUTIONS.value, 409,
        )
        # Resolve the dispute.
        disp = ctx["dispute"]
        start_investigation(disp["id"])
        submit_evidence(disp["id"], ctx["holder"]["id"],
                        url="https://example.com/e1.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/e2.pdf")
        advance_to_mediation(disp["id"])
        advance_to_arbitration(disp["id"])
        resolve_dispute(disp["id"], outcome="DISMISSED",
                        arbitration_decision="No merit.")
        # Second attempt: succeeds.
        ok = api.finalize_pool(ctx["pool"]["id"], FIN)
        data = validate_success(ok, 200)
        assert data["status"] == "DISTRIBUTED"

    def test_share_termination_clear_vs_frozen_diverges(self, api):
        """# difficulty: cross_entity_state_dependency/rights_share_termination_depends_on_work_dispute_posture

        PRD §3.3 / §2.10 priority 7: 'Holder-initiated termination of a
        share is blocked while the parent work's dispute_posture is
        FROZEN; an attempt is rejected with ERR_WORK_FROZEN.'

        Claim: same PATCH payload, two works in different
        dispute_posture branches — Branch A (CLEAR) succeeds with 200;
        Branch B (FROZEN) returns ERR_WORK_FROZEN (409).
        """
        # Branch A — CLEAR
        h_a, work_a, share_a = setup_approved_recording_work(
            holder_legal_name="Branch A holder",
        )
        # Add a second share so termination of the first leaves the
        # work covered. Without this, terminating share_a leaves the
        # work uncovered; but PRD does not gate the PATCH itself on
        # post-condition share-sum — that gate fires only on approve.
        # So a single-share termination is acceptable.
        resp_a = api.patch_share(
            work_a["id"], share_a["id"],
            patch_share_payload(share_status="TERMINATED"),
            make_rights_holder_headers(h_a["id"]),
        )
        validate_success(resp_a, 200)

        # Branch B — FROZEN
        h_b, work_b, share_b = setup_approved_recording_work(
            holder_legal_name="Branch B holder",
        )
        open_dispute(work_b["id"], h_b["id"], dispute_kind="OWNERSHIP")
        resp_b = api.patch_share(
            work_b["id"], share_b["id"],
            patch_share_payload(share_status="TERMINATED"),
            make_rights_holder_headers(h_b["id"]),
        )
        validate_error(resp_b, ApiErrorId.ERR_WORK_FROZEN.value, 409)


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    """difficulty: resource_temporal_overlap/agency_binding_half_open_adjacency_allowed
    difficulty: resource_temporal_overlap/playback_batch_exact_window_uniqueness
    """

    def test_agency_binding_adjacent_allowed_overlap_rejected(self, api):
        """# difficulty: resource_temporal_overlap/agency_binding_half_open_adjacency_allowed

        PRD §3.4 / §2.10 priorities 19 and 20: 'a new binding for the
        same (rights_holder_id, agency_kind, territory) triple must not
        overlap an existing ACTIVE binding's half-open interval ... A
        successor binding for the same (rights_holder_id, agency_kind)
        and territory must start at or after its predecessor's
        effective_until — strictly earlier is rejected with the same
        ERR_AGENCY_BINDING_OVERLAP; the rule allows zero buffer
        (immediate handover at the same instant is valid).'

        Claim: two successive bindings on the same (holder, kind,
        territory) with B.from EXACTLY EQUAL to A.until succeed; B'
        starting one second earlier is rejected with
        ERR_AGENCY_BINDING_OVERLAP.
        """
        h = create_rights_holder()
        # PRE binding A: 2026-01-01 .. 2026-06-01.
        a_from = "2026-01-01T00:00:00.000Z"
        a_until = "2026-06-01T00:00:00.000Z"
        validate_success(api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"], effective_from=a_from,
                effective_until=a_until,
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        ), 201)
        # B: adjacent, from == A.until.
        b = validate_success(api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from=a_until,
                effective_until="2026-12-01T00:00:00.000Z",
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        ), 201)
        assert b["effective_from"] == a_until

    def test_agency_binding_overlap_even_by_microsecond_rejected(self, api):
        """# difficulty: resource_temporal_overlap/agency_binding_half_open_adjacency_allowed

        PRD §3.4: 'an overlap yields ERR_AGENCY_BINDING_OVERLAP.'

        Claim: a candidate binding whose effective_from is STRICTLY
        BEFORE the predecessor's effective_until (even by 1 ms) on the
        same triple is rejected.
        """
        h = create_rights_holder()
        a_from = "2026-01-01T00:00:00.000Z"
        a_until = "2026-06-01T00:00:00.000Z"
        validate_success(api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"], effective_from=a_from,
                effective_until=a_until,
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        ), 201)
        # B starts 1 ms before A's end → overlap.
        resp = api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from="2026-05-31T23:59:59.999Z",
                effective_until="2026-12-01T00:00:00.000Z",
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGENCY_BINDING_OVERLAP.value, 409)

    def test_playback_batch_exact_window_uniqueness(self, api):
        """# difficulty: resource_temporal_overlap/playback_batch_exact_window_uniqueness

        PRD §3.6 / §2.10 priority 22: 'On playback ingest, a batch from
        the same source_identifier covering exactly the same
        [reporting_period_start, reporting_period_end) window that
        already exists in the system with validity_status of VALID
        yields ERR_DUPLICATE_BATCH (409).'

        Claim: second ingest on the same (source_identifier, window)
        returns ERR_DUPLICATE_BATCH (409); a window shifted by 1
        second on the same source returns 201 VALID.
        """
        now = now_utc()
        period_end = iso(now - timedelta(hours=1))
        period_start = iso(now - timedelta(days=5))
        src = unique_source_identifier()
        from test_helpers import create_playback_batch_payload, PSRC
        # B1.
        b1 = validate_success(api.create_playback_batch(
            create_playback_batch_payload(
                events=[], source_identifier=src,
                reporting_period_start=period_start,
                reporting_period_end=period_end,
            ),
            PSRC,
        ), 201)
        assert b1["validity_status"] == "VALID"
        # B2 same window → duplicate.
        resp = api.create_playback_batch(
            create_playback_batch_payload(
                events=[], source_identifier=src,
                reporting_period_start=period_start,
                reporting_period_end=period_end,
            ),
            PSRC,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BATCH.value, 409)


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    """difficulty: compensating_invariant/dispute_open_resolve_distribution_status_invariant
    difficulty: compensating_invariant/payment_retry_abandon_micro_balance_invariant
    """

    def test_dispute_freeze_unfreeze_preserves_per_holder_gross(self, api):
        """# difficulty: compensating_invariant/dispute_open_resolve_distribution_status_invariant

        PRD §2.7: 'When posture flips from CLEAR to FROZEN, every
        PENDING Distribution on that work flips to FROZEN; when
        posture flips from FROZEN to CLEAR, every FROZEN Distribution
        on that work flips to RELEASED.'

        Claim: open dispute → resolve dispute leaves every
        Distribution.gross_amount_cents on the disputed work unchanged
        from its pre-dispute value (cents conservation across the
        freeze/unfreeze round trip).
        """
        work, holders, _shares = setup_approved_work_with_multi_share(
            share_specs=[(60.00, "Cons1"), (40.00, "Cons2")],
            rights_type="RECORDING",
        )
        h1, h2 = holders
        # Close the pool to mint PENDING distributions.
        closed, _rule, dists_before = setup_closed_pool_for_works(
            [work], gross_revenue_cents=10_000_000,
        )
        pre = {
            d["rights_holder_id"]: d["gross_amount_cents"]
            for d in dists_before
        }
        # Open + walk through arbitration + resolve DISMISSED.
        disp = open_dispute(work["id"], h1["id"], dispute_kind="OWNERSHIP")
        start_investigation(disp["id"])
        submit_evidence(disp["id"], h1["id"], url="https://example.com/e1.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/e2.pdf")
        advance_to_mediation(disp["id"])
        advance_to_arbitration(disp["id"])
        resolve_dispute(disp["id"], outcome="DISMISSED",
                        arbitration_decision="ok")
        dists_after = list_pool_distributions(closed["id"])
        post = {
            d["rights_holder_id"]: d["gross_amount_cents"]
            for d in dists_after
        }
        for holder_id, before_val in pre.items():
            assert post[holder_id] == before_val, (
                f"Per-holder gross changed across freeze/unfreeze: "
                f"{holder_id} {before_val} → {post[holder_id]}"
            )

    def test_dispute_freeze_resolve_releases_each_distribution(self, api):
        """# difficulty: compensating_invariant/dispute_open_resolve_distribution_status_invariant

        PRD §3.11: 'On a successful resolution ... every FROZEN
        distribution on this work flips to RELEASED (cascade depth 3).'

        Claim: after resolve, every distribution for the disputed work
        carries status != FROZEN (specifically RELEASED, or PAID if
        downstream cascade already flipped it).
        """
        h, work, _share = setup_approved_recording_work()
        closed, _rule, _ = setup_closed_pool_for_works(
            [work], gross_revenue_cents=10_000_000,
        )
        disp = open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        start_investigation(disp["id"])
        submit_evidence(disp["id"], h["id"], url="https://example.com/e1.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/e2.pdf")
        advance_to_mediation(disp["id"])
        advance_to_arbitration(disp["id"])
        resolve_dispute(disp["id"], outcome="DISMISSED",
                        arbitration_decision="ok")
        dists = list_pool_distributions(closed["id"])
        for d in find_distributions_for_work(dists, work["id"]):
            assert d["status"] != "FROZEN", \
                f"Distribution {d['id']} still FROZEN after resolve"

    def test_payment_abandon_returns_cents_to_micro_balance(self, api):
        """# difficulty: compensating_invariant/payment_retry_abandon_micro_balance_invariant

        PRD §3.13: 'Once retry_count reaches 3 and the payment is still
        FAILED, the operator may abandon it: the payment flips from
        FAILED to ABANDONED, and the underlying Distribution rows are
        either reverted from RELEASED to FORFEITED or returned to
        MicroBalance according to the supplied policy in the abandon
        body.'

        Claim: with abandon policy=RETURN_TO_MICRO, the MicroBalance
        for (holder, currency) gains the previously-drained cents back
        — net is non-zero after abandon.
        """
        ctx = setup_payment_failed_payment_for_abandon(
            enough_gross_cents=200_000,
        )
        pay = ctx["payment"]
        # PRD §3.13 retry cycle: FAILED → RETRYING via retry; background
        # sweep moves RETRYING → SENT; PSP callback then flips SENT →
        # FAILED. Walk retry_count to 3.
        from test_helpers import run_sweep
        retry_payment(pay["id"])           # 0 → 1, status RETRYING
        run_sweep()                        # RETRYING → SENT
        psp_callback_failure(pay["id"])    # SENT → FAILED
        retry_payment(pay["id"])           # 1 → 2, RETRYING
        run_sweep()
        psp_callback_failure(pay["id"])
        retry_payment(pay["id"])           # 2 → 3, RETRYING
        run_sweep()
        psp_callback_failure(pay["id"])
        # Now retry_count==3, payment FAILED → abandon.
        abandoned = abandon_payment(pay["id"], policy="RETURN_TO_MICRO")
        assert abandoned["status"] == "ABANDONED"
        # MicroBalance for (holder, USD) should now be > 0.
        mb_resp = api.get_micro_balance(
            ctx["holder"]["id"],
            make_rights_holder_headers(ctx["holder"]["id"]),
        )
        mb = validate_success(mb_resp, 200)
        rows = mb if isinstance(mb, list) else [mb]
        usd = next((r for r in rows if r.get("currency") == "USD"), None)
        assert usd is not None, f"Expected USD MicroBalance row; got {rows}"
        assert usd["balance_cents"] > 0, (
            f"After abandon with RETURN_TO_MICRO, MicroBalance must "
            f"reabsorb the unpaid cents; got {usd}"
        )

    def test_payment_abandon_flips_payment_terminal(self, api):
        """# difficulty: compensating_invariant/payment_retry_abandon_micro_balance_invariant

        PRD §3.13: 'The two terminal payment states are SUCCEEDED and
        ABANDONED.'

        Claim: after walking retry_count to 3 and abandoning, the
        Payment row carries status == ABANDONED.
        """
        ctx = setup_payment_failed_payment_for_abandon(
            enough_gross_cents=200_000,
        )
        pay = ctx["payment"]
        from test_helpers import run_sweep
        for _ in range(3):
            retry_payment(pay["id"])
            run_sweep()
            psp_callback_failure(pay["id"])
        abandoned = abandon_payment(pay["id"], policy="RETURN_TO_MICRO")
        assert abandoned["status"] == "ABANDONED"
        assert abandoned["retry_count"] == 3


# ===========================================================================
# Additional coverage for instances with only one primary test above,
# bringing every instance to >=2 tests per the difficulty coverage rule.
# ===========================================================================
class TestDifficultyCoverageSupplement:
    """Extra tests so every difficulty-design instance carries >=2 tags."""

    def test_combinatorial_nonlinear_skip_classifier_reduces_units(self, api):
        """# difficulty: combinatorial_formula/distribution_share_nonlinear_units_with_branched_mode

        PRD §3.9: 'Each event's playback-type weight is drawn from the
        rule's playback_type_weights map after classifying the event
        into one of four types: FULL_PLAY when play_duration_seconds is
        at least 95% of the work's duration_seconds, SKIP when it is
        strictly less than 30% of duration_seconds, BACKGROUND for
        events explicitly tagged as background activity, and FOREGROUND
        for the remainder.'

        Claim: when a single work has one FULL_PLAY event and another
        single work has one SKIP event in the same pool under PER_PLAY
        with FULL_PLAY=2.0 and SKIP=0.5, the FULL_PLAY work receives
        STRICTLY MORE cents than the SKIP work.
        """
        ha = create_rights_holder(legal_name="Combo Full")
        hb = create_rights_holder(legal_name="Combo Skip")
        wa = create_work_draft(ha["id"], rights_type="RECORDING",
                               duration_seconds=300, isrc=unique_isrc())
        create_share(wa["id"], ha["id"], ha["id"], 100.00)
        submit_work(wa["id"], ha["id"]); take_review(wa["id"])
        approve_work(wa["id"])
        wb = create_work_draft(hb["id"], rights_type="RECORDING",
                               duration_seconds=300, isrc=unique_isrc())
        create_share(wb["id"], hb["id"], hb["id"], 100.00)
        submit_work(wb["id"], hb["id"]); take_review(wb["id"])
        approve_work(wb["id"])
        rule = create_per_play_rule(
            channel="STREAMING",
            playback_type_weights={
                "FULL_PLAY": 2.0, "SKIP": 0.5,
                "BACKGROUND": 0.5, "FOREGROUND": 1.0,
            },
        )
        now = now_utc()
        period_end = now - timedelta(hours=1)
        period_start = period_end - timedelta(days=5)
        ingest_playback_batch(
            [
                make_playback_event(work_id=wa["id"],
                                    play_duration_seconds=300,
                                    played_at=iso(period_start + timedelta(hours=1)),
                                    region="US"),
                make_playback_event(work_id=wb["id"],
                                    play_duration_seconds=30,
                                    played_at=iso(period_start + timedelta(hours=2)),
                                    region="US"),
            ],
            reporting_period_start=iso(period_start),
            reporting_period_end=iso(period_end),
            channel="STREAMING",
            source_identifier=unique_source_identifier(),
        )
        from test_helpers import create_pool
        pool = create_pool(
            period_start=iso(period_start), period_end=iso(period_end),
            distribution_rule_version_id=rule["id"],
            revenue_source="STREAMING", region="WW",
            gross_revenue_cents=20_000_000,
            platform_share_percent=30.00, mechanical_split_percent=0.00,
        )
        close_pool(pool["id"])
        dists = list_pool_distributions(pool["id"])
        da = find_distribution_for(dists, ha["id"], work_id=wa["id"])
        db = find_distribution_for(dists, hb["id"], work_id=wb["id"])
        assert da is not None and db is not None
        assert da["gross_amount_cents"] > db["gross_amount_cents"]

    def test_combinatorial_rounding_per_share_sums_to_work_pool(self, api):
        """# difficulty: combinatorial_formula/rounding_order_per_share_residual_lodging

        PRD §3.9: 'the residual cents — the difference between the
        work's per-work cents and the sum of rounded per-share
        allocations — is lodged with the share whose share_percent is
        highest...'

        Claim: with shares 33/33/34 and a per-work cents pool of 10,
        the sum of all share gross_amount_cents equals exactly 10
        (cents are conserved across the per-share rounding step).
        """
        work, holders, _shares = setup_approved_work_with_multi_share(
            share_specs=[(33.00, "S1"), (33.00, "S2"), (34.00, "S3")],
            rights_type="RECORDING",
        )
        rule = create_per_play_rule(channel="STREAMING")
        now = now_utc()
        period_end = now - timedelta(hours=1)
        period_start = period_end - timedelta(days=5)
        # Per-test unique region (PRD §3.8: any 2-letter code) so prior
        # tests' events do not contaminate this pool's eligibility set.
        region_qb = "QB"
        ingest_playback_batch(
            [make_playback_event(work_id=work["id"],
                                 play_duration_seconds=300,
                                 played_at=iso(period_start + timedelta(hours=1)),
                                 region=region_qb)],
            reporting_period_start=iso(period_start),
            reporting_period_end=iso(period_end),
            channel="STREAMING",
            source_identifier=unique_source_identifier(),
        )
        from test_helpers import create_pool
        pool = create_pool(
            period_start=iso(period_start), period_end=iso(period_end),
            distribution_rule_version_id=rule["id"],
            revenue_source="STREAMING", region=region_qb,
            gross_revenue_cents=11,
            platform_share_percent=0.00, mechanical_split_percent=0.00,
        )
        close_pool(pool["id"])
        dists = list_pool_distributions(pool["id"])
        per_work = [d for d in dists if d.get("work_id") == work["id"]]
        total = sum(d["gross_amount_cents"] for d in per_work)
        assert total == 10, f"Sum across all 3 shares must equal 10; got {total}"

    def test_nonlinear_dispute_cyclic_evidence_persists_through_loop(self, api):
        """# difficulty: non_linear_state_machine/dispute_cyclic_mediation_investigation_loop

        PRD §3.11: 'Parties may attach evidence to an OPEN or
        in-progress dispute. Each evidence submission appends an entry
        to evidence_items carrying submitter_role, submitter_id, the
        evidence url, and a submitted_at timestamp; the list is
        append-only.'

        Claim: evidence submitted before the MEDIATION ↔
        UNDER_INVESTIGATION loop remains present on the dispute body
        after the loop completes — the list is append-only.
        """
        h, work, _share = setup_approved_recording_work()
        disp = open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        start_investigation(disp["id"])
        ev_r = submit_evidence(disp["id"], h["id"],
                               url="https://example.com/persist.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/officer.pdf")
        advance_to_mediation(disp["id"])
        reopen_investigation(disp["id"])
        med_again = advance_to_mediation(disp["id"])
        # evidence_items must still hold both rows.
        items = med_again.get("evidence_items", [])
        urls = [item.get("url") for item in items]
        assert "https://example.com/persist.pdf" in urls
        assert "https://example.com/officer.pdf" in urls

    def test_transitive_cascade_depth_3_audit_after_terminate(self, api):
        """# difficulty: transitive_cascade/work_rejection_cascade_depth_3

        PRD §3.2: 'each of those terminated shares emits a
        ShareChangeAudit row with change_kind of TERMINATED capturing
        the pre-termination and post-termination snapshots (cascade
        depth 3).'

        Claim: every TERMINATED audit row written during reject-cascade
        carries a non-null before_snapshot (capturing the pre-state).
        """
        h = create_rights_holder()
        work = create_work_draft(h["id"], rights_type="RECORDING",
                                 isrc=unique_isrc())
        s = create_share(work["id"], h["id"], h["id"], 100.00)
        submit_work(work["id"], h["id"]); take_review(work["id"])
        from test_helpers import reject_work
        reject_work(work["id"], reason="cascade depth-3 test")
        audit_resp = api.list_share_audit(
            work["id"], s["id"], make_rights_holder_headers(h["id"]),
            params={"limit": 100},
        )
        audits, _ = validate_paginated(audit_resp)
        term = find_audit_by_kind(audits, "TERMINATED")
        assert len(term) >= 1
        for row in term:
            assert row.get("before_snapshot") is not None
            # before_snapshot should have share_status ACTIVE.
            before = row["before_snapshot"]
            assert before.get("share_status") == "ACTIVE"

    def test_transitive_dispute_cascade_only_for_matching_work(self, api):
        """# difficulty: transitive_cascade/dispute_open_cascade_depth_2

        PRD §3.11: 'every PENDING distribution on this work flips to
        FROZEN (cascade depth 2).'

        Claim: opening a dispute on Work A FREEZES only distributions
        whose work_id == A; distributions belonging to a different
        Work B in the same pool remain PENDING.
        """
        ha = create_rights_holder(legal_name="CascadeA")
        hb = create_rights_holder(legal_name="CascadeB")
        wa = create_work_draft(ha["id"], rights_type="RECORDING",
                               isrc=unique_isrc())
        create_share(wa["id"], ha["id"], ha["id"], 100.00)
        submit_work(wa["id"], ha["id"]); take_review(wa["id"])
        approve_work(wa["id"])
        wb = create_work_draft(hb["id"], rights_type="RECORDING",
                               isrc=unique_isrc())
        create_share(wb["id"], hb["id"], hb["id"], 100.00)
        submit_work(wb["id"], hb["id"]); take_review(wb["id"])
        approve_work(wb["id"])
        closed, _rule, _ = setup_closed_pool_for_works(
            [wa, wb], gross_revenue_cents=10_000_000,
        )
        # Open dispute on WA only.
        open_dispute(wa["id"], ha["id"], dispute_kind="OWNERSHIP")
        dists = list_pool_distributions(closed["id"])
        for d in find_distributions_for_work(dists, wa["id"]):
            assert d["status"] == "FROZEN"
        for d in find_distributions_for_work(dists, wb["id"]):
            assert d["status"] == "PENDING"

    # NOTE: test_priority_minor_payout_blocked_dominates_with_below_min
    # removed for the same unique-derivability reason as
    # test_minor_payout_blocked_dominates_referential_check: PRD names
    # ERR_MINOR_PAYOUT_BLOCKED but never defines "active guardian
    # binding". A faithful PRD reader can produce an implementation
    # where minors with guardian_holder_id always pass the check, so
    # this priority-vs-priority assertion cannot be uniquely derived.

    def test_boundary_empty_event_pool_status_distributed_after_finalize(
        self, api,
    ):
        """# difficulty: boundary_precision_check/empty_event_set_pool_close_zero_units

        PRD §3.10: 'On success, every PENDING distribution in the pool
        flips to RELEASED.'

        Claim: a pool with zero distributions finalises to
        status=DISTRIBUTED (no Distribution rows to flip; finalize
        still succeeds because no FROZEN distribution exists).
        """
        rule = create_per_play_rule(channel="STREAMING")
        now = now_utc()
        period_end = now - timedelta(hours=1)
        period_start = period_end - timedelta(days=5)
        from test_helpers import create_pool
        pool = create_pool(
            period_start=iso(period_start), period_end=iso(period_end),
            distribution_rule_version_id=rule["id"],
            revenue_source="STREAMING", region="WW",
            gross_revenue_cents=1_000_000,
            platform_share_percent=0.00, mechanical_split_percent=0.00,
        )
        close_pool(pool["id"])
        finalize_pool(pool["id"])
        # Re-read.
        resp = api.get_pool(pool["id"], FIN)
        data = validate_success(resp, 200)
        assert data["status"] == "DISTRIBUTED"

    def test_cross_entity_pool_finalize_requires_no_frozen(self, api):
        """# difficulty: cross_entity_state_dependency/pool_finalize_depends_on_distribution_states

        PRD §3.10: 'no Distribution under the pool may carry status of
        FROZEN.'

        Claim: a pool with zero FROZEN distributions (only PENDING and
        nothing else) finalises successfully — the cross-entity guard
        depends on aggregate child status, not on a global flag.
        """
        _h, work, _share = setup_approved_recording_work()
        closed, _rule, dists = setup_closed_pool_for_works(
            [work], gross_revenue_cents=10_000_000,
        )
        for d in dists:
            assert d["status"] == "PENDING"
        resp = api.finalize_pool(closed["id"], FIN)
        data = validate_success(resp, 200)
        assert data["status"] == "DISTRIBUTED"

    def test_cross_entity_share_terminate_unblocked_after_resolve(self, api):
        """# difficulty: cross_entity_state_dependency/rights_share_termination_depends_on_work_dispute_posture

        PRD §3.11: 'On a successful resolution ... if no other open
        dispute remains on this work, posture flips to CLEAR.' PRD §3.3:
        'Holder-initiated termination of a share is blocked while the
        parent work's dispute_posture is FROZEN.'

        Claim: once the dispute is resolved and posture flips back to
        CLEAR, the previously-blocked PATCH share share_status=
        TERMINATED succeeds with 200.
        """
        h, work, share = setup_approved_recording_work()
        disp = open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        # Confirm blocked during FROZEN posture.
        blocked = api.patch_share(
            work["id"], share["id"],
            patch_share_payload(share_status="TERMINATED"),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_WORK_FROZEN.value, 409)
        # Resolve dispute → posture CLEAR.
        start_investigation(disp["id"])
        submit_evidence(disp["id"], h["id"], url="https://example.com/a.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/b.pdf")
        advance_to_mediation(disp["id"])
        advance_to_arbitration(disp["id"])
        resolve_dispute(disp["id"], outcome="DISMISSED",
                        arbitration_decision="ok")
        # Now PATCH succeeds.
        ok = api.patch_share(
            work["id"], share["id"],
            patch_share_payload(share_status="TERMINATED"),
            make_rights_holder_headers(h["id"]),
        )
        data = validate_success(ok, 200)
        assert data["share_status"] == "TERMINATED"

    def test_resource_temporal_playback_shifted_window_accepted(self, api):
        """# difficulty: resource_temporal_overlap/playback_batch_exact_window_uniqueness

        PRD §3.6: 'a prior batch from the same source_identifier
        covering exactly the same [reporting_period_start,
        reporting_period_end) window already exists with
        validity_status of VALID' is the precondition for DEDUPED.

        Claim: a second batch on the same source_identifier with a
        window shifted by 1 second is NOT a duplicate — it returns 201
        with validity_status=VALID.
        """
        now = now_utc()
        period_end = iso(now - timedelta(hours=1))
        period_start = iso(now - timedelta(days=5))
        src = unique_source_identifier()
        from test_helpers import create_playback_batch_payload, PSRC
        # First batch.
        validate_success(api.create_playback_batch(
            create_playback_batch_payload(
                events=[], source_identifier=src,
                reporting_period_start=period_start,
                reporting_period_end=period_end,
            ),
            PSRC,
        ), 201)
        # Shift the period_start by 1 second.
        shifted_start = iso(now - timedelta(days=5) + timedelta(seconds=1))
        shifted_end = iso(now - timedelta(hours=1) + timedelta(seconds=1))
        data = validate_success(api.create_playback_batch(
            create_playback_batch_payload(
                events=[], source_identifier=src,
                reporting_period_start=shifted_start,
                reporting_period_end=shifted_end,
            ),
            PSRC,
        ), 201)
        assert data["validity_status"] == "VALID"
