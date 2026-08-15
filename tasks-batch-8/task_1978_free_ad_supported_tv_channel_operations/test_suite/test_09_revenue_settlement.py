"""Distribution agreements, revenue reports, variant calculations, dispute
cycles, and rate pinning (PRD §3.8, §2.8)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    factories,
    create_channel,
    setup_platform,
    setup_active_agreement,
    setup_revenue_report_scenario,
    setup_elapsed_report,
    setup_provisional_report,
    setup_finalized_report,
    advance_clock,
    make_analyst_headers,
    make_controller_headers,
    make_distributor_partner_headers,
    get_report,
    get_decision,
    get_agreement,
    get_platform,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


# ---------------------------------------------------------------------------
# Dual-variant revenue statements (provisional vs final)
# ---------------------------------------------------------------------------

def _setup_unreconciled_divergence(api):
    """d1 reconciled (500 imps, cpm 500 -> 250) and d2 committed-only (200 imps,
    cpm 400 -> 80); agreement below 2000 / above 4000 / threshold 100000."""
    return setup_revenue_report_scenario(
        decision_specs=[
            {"cpm_cents": 500, "iab_category": "IAB-9", "impressions": 500,
             "reconcile": True},
            {"cpm_cents": 400, "iab_category": "IAB-7", "impressions": 200,
             "reconcile": False},
        ],
        agreement_below=2000, agreement_above=4000, agreement_threshold=100000,
    )


def test_provisional_variant_includes_committed_and_reconciled(api):
    """PRD §3.8: "the provisional variant includes decisions in `COMMITTED` or
    `RECONCILED` status, while the final variant includes `RECONCILED` only".
    Provisional gross is 330 (250 reconciled + 80 committed-but-observed).

    Design: Difficulty/dual_variant_calc/r1_provisional_vs_final_revenue_statement_diverge_on_unreconciled
    """
    ctx = _setup_unreconciled_divergence(api)
    report = ctx["report"]
    assert report["report_status"] == "PROVISIONAL"
    assert report["calculation_variant"] == "PROVISIONAL"
    assert report["gross_revenue_cents"] == 330
    assert report["platform_share_cents"] == 66, "round_half_up(330*2000/10000)"
    assert report["net_revenue_cents"] == 264


def test_final_variant_excludes_unreconciled_decisions(api):
    """PRD §3.8: "the provisional variant includes decisions in `COMMITTED` or
    `RECONCILED` status, while the final variant includes `RECONCILED` only — so the
    final gross is the smaller figure whenever unreconciled decisions carry
    impressions." Final gross drops to 250 over identical events.

    Design: Difficulty/dual_variant_calc/r1_provisional_vs_final_revenue_statement_diverge_on_unreconciled
    """
    ctx = _setup_unreconciled_divergence(api)
    finalized = get_success_data(api.report_finalize(ctx["report"]["id"], CONTROLLER))
    assert finalized["calculation_variant"] == "FINAL"
    assert finalized["gross_revenue_cents"] == 250
    assert finalized["platform_share_cents"] == 50, "round_half_up(250*2000/10000)"
    assert finalized["net_revenue_cents"] == 200
    assert finalized["gross_revenue_cents"] != ctx["report"]["gross_revenue_cents"]
    assert get_decision(ctx["decisions"][1]["id"])["decision_status"] == "COMMITTED"


# ---------------------------------------------------------------------------
# Per-pair rounding then sum (pinned rounding order)
# ---------------------------------------------------------------------------

def _setup_per_pair_rounding(api, finalize=False):
    return setup_revenue_report_scenario(
        decision_specs=[
            {"cpm_cents": 500, "iab_category": "IAB-9", "impressions": 3,
             "reconcile": True},
            {"cpm_cents": 500, "iab_category": "IAB-7", "impressions": 3,
             "reconcile": True},
        ],
        agreement_below=2000, agreement_above=4000, agreement_threshold=100000,
        finalize=finalize,
    )


def test_per_pair_rounding_applies_to_each_reconciled_decision(api):
    """PRD §3.8: "The rounding order is pinned: each per-pair amount is rounded
    first, and only then are the rounded integers summed into the platform's gross;
    summing first and rounding once is the rejected alternative and yields different
    cents." round_half_up(500*3/1000) == 2 per decision, so gross is 2+2 == 4, not
    the sum-then-round 3.

    Design: Difficulty/combinatorial_formula/r2_per_pair_rounding_then_sum_rejects_sum_then_round
    """
    ctx = _setup_per_pair_rounding(api)
    d1 = get_decision(ctx["decisions"][0]["id"])
    d2 = get_decision(ctx["decisions"][1]["id"])
    assert d1["reconciled_cost_cents"] == 2, "round_half_up(1.5) == 2"
    assert d2["reconciled_cost_cents"] == 2
    finalized = get_success_data(api.report_finalize(ctx["report"]["id"], CONTROLLER))
    assert finalized["gross_revenue_cents"] == 4, (
        "per-pair rounding (2+2), NOT sum-then-round (3)"
    )


def test_per_pair_rounding_flows_into_statement_share(api):
    """PRD §3.8: "`platform_share_cents` is the raw share divided by 10,000 and
    rounded half-up to whole cents". Gross 4 at 2000 bps below the tier gives
    share 1 (round_half_up(0.8)) and net 3.

    Design: Difficulty/combinatorial_formula/r2_per_pair_rounding_then_sum_rejects_sum_then_round
    """
    ctx = _setup_per_pair_rounding(api)
    finalized = get_success_data(api.report_finalize(ctx["report"]["id"], CONTROLLER))
    assert finalized["gross_revenue_cents"] == 4
    assert finalized["platform_share_cents"] == 1
    assert finalized["net_revenue_cents"] == 3


# ---------------------------------------------------------------------------
# Tiered share with pinned evaluation order (marginal split)
# ---------------------------------------------------------------------------

def _setup_marginal_split(api):
    return setup_revenue_report_scenario(
        decision_specs=[
            {"cpm_cents": 1000, "iab_category": "IAB-9", "impressions": 2000,
             "reconcile": True},
        ],
        agreement_below=3000, agreement_above=4000, agreement_threshold=1000,
    )


def test_tiered_share_applies_marginal_split(api):
    """PRD §3.8: "Second, tier selection reads gross alone: the below-tier portion
    is the smaller of gross and the locked threshold `locked_tier_threshold_cents`,
    and the above-tier portion is the excess of gross over that threshold — zero
    when gross does not exceed it. Third, the raw share is the below-tier portion
    multiplied by `locked_rev_share_bps_below` plus the above-tier portion
    multiplied by `locked_rev_share_bps_above`, in basis points." Gross 2000 with
    threshold 1000 yields share 700, not flat-below 600 nor flat-above 800.

    Design: Difficulty/combinatorial_formula/r2_tiered_share_pinned_evaluation_order_marginal_split
    """
    ctx = _setup_marginal_split(api)
    finalized = get_success_data(api.report_finalize(ctx["report"]["id"], CONTROLLER))
    assert finalized["gross_revenue_cents"] == 2000
    assert finalized["platform_share_cents"] == 700, (
        "round_half_up((1000*3000 + 1000*4000) / 10000)"
    )


def test_tiered_share_marginal_split_net_revenue(api):
    """PRD §3.8: "Fifth, `net_revenue_cents` is `gross_revenue_cents` minus
    `platform_share_cents`." Gross 2000 less the 700-cent share nets 1300.

    Design: Difficulty/combinatorial_formula/r2_tiered_share_pinned_evaluation_order_marginal_split
    """
    ctx = _setup_marginal_split(api)
    finalized = get_success_data(api.report_finalize(ctx["report"]["id"], CONTROLLER))
    assert finalized["calculation_variant"] == "FINAL"
    assert finalized["net_revenue_cents"] == 1300


# ---------------------------------------------------------------------------
# Dispute / refinalize cycle (bounded cyclic machine)
# ---------------------------------------------------------------------------

def _setup_finalized_money_report(api):
    """One reconciled decision: 1000 imps at cpm 500 -> gross 500; below-tier
    3000 bps -> share 150, net 350."""
    return setup_revenue_report_scenario(
        decision_specs=[
            {"cpm_cents": 500, "iab_category": "IAB-9", "impressions": 1000,
             "reconcile": True},
        ],
        agreement_below=3000, agreement_above=4000, agreement_threshold=100000,
        finalize=True,
    )


def test_dispute_then_refinalize_increments_round(api):
    """PRD §3.8: "Refinalizing (`DISPUTED` → `FINALIZED`) again requires a
    `FinanceController` other than the generator, recomputes the final variant, and
    increments `dispute_round`." The first completed cycle lands on dispute_round 1.

    Design: Difficulty/non_linear_state_machine/r3_report_dispute_refinalize_cycle_bounded
    """
    ctx = _setup_finalized_money_report(api)
    rid = ctx["report"]["id"]
    partner = make_distributor_partner_headers(ctx["platform"]["id"])
    disputed = get_success_data(
        api.report_dispute(rid, {"dispute_reason": "impression undercount"}, partner)
    )
    assert disputed["report_status"] == "DISPUTED"
    refinalized = get_success_data(api.report_refinalize(rid, CONTROLLER))
    assert refinalized["report_status"] == "FINALIZED"
    assert refinalized["dispute_round"] == 1
    assert refinalized["gross_revenue_cents"] == 500
    assert refinalized["net_revenue_cents"] == 350


def test_dispute_cycle_traversable_twice_with_monotonic_round(api):
    """PRD §3.8: "A `DistributorPartner` may then dispute a finalized report — only
    for their own platform, else `ERR_FORBIDDEN_OWNERSHIP` — carrying a
    `dispute_reason`, provided `dispute_round` is below the ceiling of 3". Two full
    cycles succeed with the counter monotonic (1, then 2) and figures stable.

    Design: Difficulty/non_linear_state_machine/r3_report_dispute_refinalize_cycle_bounded
    """
    ctx = _setup_finalized_money_report(api)
    rid = ctx["report"]["id"]
    partner = make_distributor_partner_headers(ctx["platform"]["id"])
    for reason in ("first", "second"):
        get_success_data(api.report_dispute(rid, {"dispute_reason": reason}, partner))
        report = get_success_data(api.report_refinalize(rid, CONTROLLER))
    assert report["report_status"] == "FINALIZED"
    assert report["dispute_round"] == 2
    assert report["gross_revenue_cents"] == 500
    assert report["net_revenue_cents"] == 350


def test_dispute_beyond_max_rounds_rejected(api):
    """PRD §3.8: "provided `dispute_round` is below the ceiling of 3; disputing at
    the ceiling is rejected with `ERR_DISPUTE_ROUND_LIMIT`."

    Design: Corner/validations/dispute_beyond_max_rounds_rejected
    """
    ctx = setup_finalized_report(channel_name="Ch MX")
    rid = ctx["report"]["id"]
    partner = make_distributor_partner_headers(ctx["platform"]["id"])
    for reason in ("r1", "r2", "r3"):
        get_success_data(api.report_dispute(rid, {"dispute_reason": reason}, partner))
        get_success_data(api.report_refinalize(rid, CONTROLLER))
    resp = api.report_dispute(rid, {"dispute_reason": "r4"}, partner)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ROUND_LIMIT)
    report = get_report(rid)
    assert report["report_status"] == "FINALIZED"
    assert report["dispute_round"] == 3


# ---------------------------------------------------------------------------
# Report creation guards and recompute OCC
# ---------------------------------------------------------------------------

def test_report_create_before_period_elapsed_rejected(api):
    """PRD §3.8: "The period must be fully elapsed, meaning the current logical date
    is strictly after the last day of `period_month`, else
    `ERR_REPORT_PERIOD_NOT_ELAPSED`". At logical 2026-09-15 September has not ended.

    Design: Corner/validations/report_create_before_period_elapsed_rejected
    """
    channel = create_channel(name="Ch RP")
    platform = setup_platform()
    setup_active_agreement(channel["id"], platform["id"])
    advance_clock("2026-09-15T00:00:00Z")
    resp = api.create_revenue_report(
        factories.create_revenue_report_payload(channel["id"], platform["id"]),
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_NOT_ELAPSED)


def test_report_create_without_covering_agreement_rejected(api):
    """PRD §3.8: "Creation resolves the covering agreement: an agreement in
    `ACTIVE`, `SUSPENDED`, or `TERMINATED` status whose terms cover that (channel,
    platform, period) and which carries a locked rate snapshot — when none exists
    the creation fails with `ERR_NO_COVERING_AGREEMENT`."

    Design: Corner/validations/report_create_without_covering_agreement_rejected
    """
    channel = create_channel(name="Ch NC")
    platform = setup_platform()
    advance_clock("2026-10-01T00:00:00Z")
    resp = api.create_revenue_report(
        factories.create_revenue_report_payload(channel["id"], platform["id"]),
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_NO_COVERING_AGREEMENT)


def test_duplicate_report_rejected(api):
    """PRD §3.8: "Only one report may exist per (channel, platform, period), else
    `ERR_DUPLICATE_REPORT`."

    Design: Corner/validations/duplicate_report_rejected
    """
    ctx = setup_elapsed_report(channel_name="Ch DR")
    resp = api.create_revenue_report(
        factories.create_revenue_report_payload(
            ctx["channel"]["id"], ctx["platform"]["id"]
        ),
        make_analyst_headers("fin-2"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)


def test_report_recompute_with_stale_version_rejected(api):
    """PRD §2.8: "Recomputing a revenue report requires `expected_report_version`
    matching the report's current `version`. A mismatch is rejected with
    `ERR_STALE_REPORT_VERSION` (HTTP 412), preventing a stale writer from discarding
    figures produced after its read."

    Design: Corner/validations/report_recompute_with_stale_version_rejected
    """
    ctx = setup_elapsed_report(channel_name="Ch OC2")
    rid = ctx["report"]["id"]
    stale_version = ctx["report"]["version"]
    first = api.report_recompute(rid, {"expected_report_version": stale_version}, ANALYST)
    assert first.status_code == 200, "Setup failed: fresh recompute must succeed"
    resp = api.report_recompute(rid, {"expected_report_version": stale_version}, ANALYST)
    validate_error(resp, ApiErrorId.ERR_STALE_REPORT_VERSION)
    assert resp.status_code == 412
    assert get_report(rid)["report_status"] == "PROVISIONAL"


def test_settle_from_provisional_rejected(api):
    """PRD §3.8: "Settling (`FINALIZED` → `SETTLED`, terminal) carries the same
    segregation requirement." A PROVISIONAL report is not FINALIZED; PRD §2.10:
    "State-transition legality: the trigger must be valid from the resource's
    current state, including terminal-state lockdown, else
    `ERR_INVALID_STATE_TRANSITION`".

    Design: Corner/validations/settle_from_provisional_rejected
    """
    ctx = setup_provisional_report(channel_name="Ch ST")
    resp = api.report_settle(ctx["report"]["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_report(ctx["report"]["id"])["report_status"] == "PROVISIONAL"


# ---------------------------------------------------------------------------
# Agreement windows, rate pinning, and platform offboarding
# ---------------------------------------------------------------------------

def test_agreement_rev_share_out_of_range_rejected(api):
    """PRD §3.8: "the tiered revenue-share rates `rev_share_bps_below` and
    `rev_share_bps_above` (each between 0 and 6000 basis points inclusive, else
    `ERR_REV_SHARE_OUT_OF_RANGE`)". 7000 bps exceeds the ceiling.

    Design: Corner/validations/agreement_rev_share_out_of_range_rejected
    """
    channel = create_channel(name="Ch RS")
    platform = setup_platform(active=False)
    resp = api.create_distribution_agreement(
        factories.create_distribution_agreement_payload(
            channel["id"], platform["id"], rev_share_bps_above=7000
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REV_SHARE_OUT_OF_RANGE)


def test_agreement_activation_pins_rate_snapshot(api):
    """PRD §3.8: "First activation (`NEGOTIATION` → `ACTIVE`) requires the platform
    to be `ACTIVE` and the channel not `ARCHIVED`, and it pins the economics:
    `locked_rev_share_bps_below`, `locked_rev_share_bps_above`,
    `locked_tier_threshold_cents`, and `locked_minimum_guarantee_cents` are copied
    from the agreement's current values" — with rate fields "editable only while it
    remains" in NEGOTIATION, the 3500 edit made before activation is what pins.

    Design: Corner/cross_cutting_layers/agreement_activation_pins_rate_snapshot
    """
    channel = create_channel(name="Ch VP")
    platform = setup_platform()
    agreement = get_success_data(
        api.create_distribution_agreement(
            factories.create_distribution_agreement_payload(
                channel["id"], platform["id"], rev_share_bps_below=3000
            ),
            ADMIN,
        )
    )
    get_success_data(
        api.agreement_patch(agreement["id"], {"rev_share_bps_below": 3500}, ADMIN)
    )
    activated = get_success_data(
        api.agreement_patch(agreement["id"], {"target_status": "ACTIVE"}, ADMIN)
    )
    assert activated["locked_rev_share_bps_below"] == 3500, (
        "pinned from the activation-time value, not the original 3000"
    )


def test_agreement_reactivation_does_not_refresh_pinned_rates(api):
    """PRD §3.8: "An agreement may move between `ACTIVE` and `SUSPENDED`;
    re-activation requires the platform to be `ACTIVE` and deliberately does not
    refresh the pinned snapshot, so the original locked rates persist."

    Design: Corner/cross_cutting_layers/agreement_activation_pins_rate_snapshot
    """
    channel = create_channel(name="Ch VP2")
    platform = setup_platform()
    agreement = get_success_data(
        api.create_distribution_agreement(
            factories.create_distribution_agreement_payload(
                channel["id"], platform["id"], rev_share_bps_below=3000
            ),
            ADMIN,
        )
    )
    get_success_data(
        api.agreement_patch(agreement["id"], {"rev_share_bps_below": 3500}, ADMIN)
    )
    get_success_data(api.agreement_patch(agreement["id"], {"target_status": "ACTIVE"}, ADMIN))
    get_success_data(api.agreement_patch(agreement["id"], {"target_status": "SUSPENDED"}, ADMIN))
    reactivated = get_success_data(
        api.agreement_patch(agreement["id"], {"target_status": "ACTIVE"}, ADMIN)
    )
    assert reactivated["agreement_status"] == "ACTIVE"
    assert reactivated["locked_rev_share_bps_below"] == 3500, (
        "no re-pin on reinstate"
    )


def test_platform_offboard_terminates_agreements(api):
    """PRD §3.8: "from any non-terminal state to terminal `OFFBOARDED` — which
    terminates every distribution agreement of that platform still in `NEGOTIATION`,
    `ACTIVE`, or `SUSPENDED`."

    Design: Corner/state_machines/platform_offboard_terminates_agreements
    """
    channel = create_channel(name="Ch OF")
    platform = setup_platform()
    agreement = setup_active_agreement(channel["id"], platform["id"])
    offboarded = get_success_data(
        api.platform_patch(platform["id"], {"target_status": "OFFBOARDED"}, ADMIN)
    )
    assert offboarded["platform_status"] == "OFFBOARDED"
    assert get_agreement(agreement["id"])["agreement_status"] == "TERMINATED"


def test_agreement_closed_window_adjacency_counts_as_overlap(api):
    """PRD §3.8: "For the same (channel, platform) pair, agreements in
    `NEGOTIATION`, `ACTIVE`, or `SUSPENDED` may not overlap under closed-interval
    semantics — and unlike rights grants, adjacency counts as overlap here — else
    `ERR_AGREEMENT_WINDOW_OVERLAP`." A new agreement starting on the exact day the
    existing one ends (2026-06-30) is rejected.

    Design: Difficulty/resource_temporal_overlap/r8_distribution_agreement_closed_windows_reject_adjacency
    """
    channel = create_channel(name="Ch O")
    platform = setup_platform(active=False)
    get_success_data(
        api.create_distribution_agreement(
            factories.create_distribution_agreement_payload(
                channel["id"], platform["id"],
                effective_start_date="2026-01-01", effective_end_date="2026-06-30",
            ),
            ADMIN,
        )
    )
    resp = api.create_distribution_agreement(
        factories.create_distribution_agreement_payload(
            channel["id"], platform["id"],
            effective_start_date="2026-06-30", effective_end_date="2026-12-31",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)


def test_agreement_one_day_gap_accepted(api):
    """PRD §3.8: "agreements in `NEGOTIATION`, `ACTIVE`, or `SUSPENDED` may not
    overlap under closed-interval semantics — and unlike rights grants, adjacency
    counts as overlap here". Starting one day after the existing agreement's end
    (2026-07-01 after 2026-06-30) shares no date and is accepted.

    Design: Difficulty/resource_temporal_overlap/r8_distribution_agreement_closed_windows_reject_adjacency
    """
    channel = create_channel(name="Ch O2")
    platform = setup_platform(active=False)
    get_success_data(
        api.create_distribution_agreement(
            factories.create_distribution_agreement_payload(
                channel["id"], platform["id"],
                effective_start_date="2026-01-01", effective_end_date="2026-06-30",
            ),
            ADMIN,
        )
    )
    created = get_success_data(
        api.create_distribution_agreement(
            factories.create_distribution_agreement_payload(
                channel["id"], platform["id"],
                effective_start_date="2026-07-01", effective_end_date="2026-12-31",
            ),
            ADMIN,
        )
    )
    assert created["agreement_status"] == "NEGOTIATION"
