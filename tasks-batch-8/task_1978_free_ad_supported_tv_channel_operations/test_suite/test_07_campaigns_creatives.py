"""Campaign and creative lifecycles: activation gates, review quality gates,
pause/void/retire cascades, and budget integrity (PRD §3.4, §3.5)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    factories,
    create_loop,
    tile_loop,
    setup_validated_loop,
    setup_exhausted_campaign_loop,
    create_active_campaign,
    run_decision_run,
    make_adops_headers,
    make_reviewer_headers,
    get_campaign,
    get_creative,
    get_decision,
    get_break,
    get_loop,
)

ADOPS = TEST_USERS["adops_headers"]
PROGRAMMER = TEST_USERS["programmer_headers"]


def test_campaign_invalid_flight_rejected(api):
    """PRD §3.5: "the flight window `flight_start_date` through `flight_end_date` —
    the end may not precede the start, else `ERR_INVALID_FLIGHT`."

    Design: Corner/validations/campaign_invalid_flight_rejected
    """
    resp = api.create_ad_campaign(
        factories.create_ad_campaign_payload(
            flight_start_date="2026-09-01", flight_end_date="2026-08-01"
        ),
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_FLIGHT)


def test_campaign_activate_without_approved_creative_rejected(api):
    """PRD §3.5: "Activating a campaign (`DRAFT` → `ACTIVE`) requires at least one
    creative of the campaign in `APPROVED` status and a `flight_end_date` on or
    after the current logical date." With the creative still PENDING_REVIEW the
    transition is rejected.

    Design: Difficulty/cross_entity_state_dependency/r7_campaign_activate_requires_approved_creative
    """
    campaign = get_success_data(
        api.create_ad_campaign(factories.create_ad_campaign_payload(), ADOPS)
    )
    creative = get_success_data(
        api.create_ad_creative(
            factories.create_ad_creative_payload(campaign["id"]), ADOPS
        )
    )
    assert creative["creative_status"] == "PENDING_REVIEW", "Setup failed"
    resp = api.campaign_activate(campaign["id"], ADOPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_campaign(campaign["id"])["campaign_status"] == "DRAFT"


def test_campaign_activate_succeeds_once_creative_approved(api):
    """PRD §3.5: "Activating a campaign (`DRAFT` → `ACTIVE`) requires at least one
    creative of the campaign in `APPROVED` status and a `flight_end_date` on or
    after the current logical date." After the creative crosses PENDING_REVIEW ->
    APPROVED the same activation succeeds.

    Design: Difficulty/cross_entity_state_dependency/r7_campaign_activate_requires_approved_creative
    """
    campaign = get_success_data(
        api.create_ad_campaign(factories.create_ad_campaign_payload(), ADOPS)
    )
    creative = get_success_data(
        api.create_ad_creative(
            factories.create_ad_creative_payload(campaign["id"]), ADOPS
        )
    )
    resp = api.campaign_activate(campaign["id"], ADOPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    get_success_data(
        api.creative_approve(creative["id"], make_reviewer_headers("rev-1"))
    )
    activated = get_success_data(api.campaign_activate(campaign["id"], ADOPS))
    assert activated["campaign_status"] == "ACTIVE"


def test_creative_approve_with_bad_duration_rejected(api):
    """PRD §3.5: "And the ad-quality rule requires `duration_seconds` to be exactly
    30 or exactly 60, else `ERR_AD_QUALITY_RULE` — this check deliberately runs at
    approve time, not at trafficking time, so a non-conforming duration can be
    ingested but never approved."

    Design: Corner/validations/creative_approve_with_bad_duration_rejected
    """
    campaign = get_success_data(
        api.create_ad_campaign(factories.create_ad_campaign_payload(), ADOPS)
    )
    creative = get_success_data(
        api.create_ad_creative(
            factories.create_ad_creative_payload(campaign["id"], duration_seconds=90),
            ADOPS,
        )
    )
    resp = api.creative_approve(creative["id"], make_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_AD_QUALITY_RULE)
    assert get_creative(creative["id"])["creative_status"] == "PENDING_REVIEW"


def test_category_mismatch_trumps_duration_quality_error(api):
    """PRD §3.5: "Review belongs to `AdQualityReviewer`, and three approve-time
    checks hold, evaluated in the priority order of §2.10 — segregation first (tier
    6), then category match (tier 9), then ad quality (tier 10)." A creative failing
    both category match (IAB-8 vs campaign IAB-9) and ad quality (90s) reports
    `ERR_CATEGORY_MISMATCH`, never `ERR_AD_QUALITY_RULE`.

    Design: Difficulty/priority_pair_validation_conflict/r5_creative_category_mismatch_trumps_duration_quality
    """
    campaign = get_success_data(
        api.create_ad_campaign(
            factories.create_ad_campaign_payload(iab_category="IAB-9"), ADOPS
        )
    )
    creative = get_success_data(
        api.create_ad_creative(
            factories.create_ad_creative_payload(
                campaign["id"], iab_category="IAB-8", duration_seconds=90
            ),
            ADOPS,
        )
    )
    resp = api.creative_approve(creative["id"], make_reviewer_headers("rev-1"))
    err = validate_error(resp, ApiErrorId.ERR_CATEGORY_MISMATCH)
    assert err["error_id"] == "ERR_CATEGORY_MISMATCH"


def test_category_mismatch_leaves_creative_pending_review(api):
    """PRD §3.5: "The creative's `iab_category` must equal its campaign's
    `iab_category`, else `ERR_CATEGORY_MISMATCH`." The rejected approval leaves the
    creative PENDING_REVIEW and unreviewed.

    Design: Difficulty/priority_pair_validation_conflict/r5_creative_category_mismatch_trumps_duration_quality
    """
    campaign = get_success_data(
        api.create_ad_campaign(
            factories.create_ad_campaign_payload(iab_category="IAB-9"), ADOPS
        )
    )
    creative = get_success_data(
        api.create_ad_creative(
            factories.create_ad_creative_payload(
                campaign["id"], iab_category="IAB-8", duration_seconds=90
            ),
            ADOPS,
        )
    )
    resp = api.creative_approve(creative["id"], make_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_CATEGORY_MISMATCH)
    after = get_creative(creative["id"])
    assert after["creative_status"] == "PENDING_REVIEW"
    assert after.get("reviewed_by_user_id") is None


def test_creative_reject_resubmit_cycle_clears_reason(api):
    """PRD §3.5: "rejection records the request's `reason` into `rejection_reason`
    and likewise stamps `reviewed_by_user_id`. A rejected creative may be
    resubmitted, returning to `PENDING_REVIEW` with `rejection_reason` cleared."

    Design: Corner/state_machines/creative_reject_resubmit_cycle_clears_reason
    """
    campaign = get_success_data(
        api.create_ad_campaign(factories.create_ad_campaign_payload(), ADOPS)
    )
    creative = get_success_data(
        api.create_ad_creative(
            factories.create_ad_creative_payload(campaign["id"]), ADOPS
        )
    )
    rejected = get_success_data(
        api.creative_reject(creative["id"], {"reason": "loud audio"},
                            make_reviewer_headers("rev-1"))
    )
    assert rejected["creative_status"] == "REJECTED"
    assert rejected["rejection_reason"] == "loud audio"

    resubmitted = get_success_data(api.creative_resubmit(creative["id"], ADOPS))
    assert resubmitted["creative_status"] == "PENDING_REVIEW"
    assert resubmitted.get("rejection_reason") is None

    approved = get_success_data(
        api.creative_approve(creative["id"], make_reviewer_headers("rev-1"))
    )
    assert approved["creative_status"] == "APPROVED"


def test_retired_creative_terminal_lockdown(api):
    """PRD §3.5: "Retiring an `APPROVED` creative (terminal `RETIRED`)"; PRD §2.10:
    "State-transition legality: the trigger must be valid from the resource's
    current state, including terminal-state lockdown, else
    `ERR_INVALID_STATE_TRANSITION`".

    Design: Corner/state_machines/retired_creative_terminal_lockdown
    """
    campaign, creative = create_active_campaign()
    get_success_data(api.creative_retire(creative["id"], ADOPS))
    resp = api.creative_approve(creative["id"], make_reviewer_headers("rev-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_creative(creative["id"])["creative_status"] == "RETIRED"


def test_unlock_compensates_committed_decisions(api):
    """PRD §3.4: "Unlocking (`LOCKED` → `VALIDATED`) runs the compensation: every
    committed decision returns to `PROVISIONAL` and each campaign's `spent_cents` is
    reduced by the corresponding `committed_cost_cents`".

    Design: Corner/state_machines/unlock_compensates_committed_decisions
    """
    ctx = setup_validated_loop(
        channel_name="Ch UN", break_durations=(30,), content_runtime=570
    )
    campaign, _ = create_active_campaign(
        total_budget_cents=5000, daily_budget_cents=5000
    )
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert decisions, "Setup failed: expected a DIRECT decision"
    get_success_data(api.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    assert get_campaign(campaign["id"])["spent_cents"] == 500, "Setup failed: lock commits 500"

    unlocked = get_success_data(api.loop_unlock(ctx["loop"]["id"], PROGRAMMER))
    assert unlocked["loop_status"] == "VALIDATED"
    assert get_decision(decisions[0]["id"])["decision_status"] == "PROVISIONAL"
    assert get_campaign(campaign["id"])["spent_cents"] == 0, (
        "pre-lock baseline restored"
    )


def test_creative_retire_voids_provisional_but_keeps_committed(api):
    """PRD §3.5: "Retiring an `APPROVED` creative (terminal `RETIRED`) voids every
    provisional decision using it and recomputes the affected breaks — `COMMITTED`
    and `RECONCILED` decisions are untouched, since that inventory is already
    bought."

    Design: Corner/cross_cutting_layers/creative_retire_voids_provisional_but_keeps_committed
    """
    ctx = setup_validated_loop(
        channel_name="Ch CC", break_durations=(30,), content_runtime=570
    )
    campaign, creative = create_active_campaign(cpm_cents=500)
    committed_run = run_decision_run(ctx["breaks"][0]["id"])
    d_committed = committed_run[0]
    get_success_data(api.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    assert get_decision(d_committed["id"])["decision_status"] == "COMMITTED", "Setup failed"

    lb = create_loop(ctx["channel"]["id"], "2026-09-02")
    _, bb = tile_loop(lb["id"], ctx["content"]["id"], (30,))
    get_success_data(api.loop_validate(lb["id"], PROGRAMMER))
    provisional_run = run_decision_run(bb[0]["id"])
    d_prov = provisional_run[0]
    assert get_decision(d_prov["id"])["decision_status"] == "PROVISIONAL", "Setup failed"

    retired = get_success_data(api.creative_retire(creative["id"], ADOPS))
    assert retired["creative_status"] == "RETIRED"
    assert get_decision(d_prov["id"])["decision_status"] == "VOIDED"
    assert get_decision(d_committed["id"])["decision_status"] == "COMMITTED"
    assert get_break(bb[0]["id"])["break_status"] == "MARKED"
    assert get_break(ctx["breaks"][0]["id"])["break_status"] == "DECIDED"


def test_adjust_budget_below_spent_rejected(api):
    """PRD §3.5: "A budget adjustment carrying `new_total_budget_cents` is rejected
    when the new total would fall below `spent_cents` (`ERR_BUDGET_BELOW_SPENT`)".
    With 500 cents committed, lowering the total to 400 is rejected.

    Design: Corner/validations/adjust_budget_below_spent_rejected
    """
    ctx = setup_exhausted_campaign_loop()
    get_success_data(api.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["spent_cents"] == 500, "Setup failed: lock commits 500"

    resp = api.campaign_adjust_budget(
        campaign["id"], {"new_total_budget_cents": 400}, ADOPS
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_BELOW_SPENT)
    assert get_campaign(campaign["id"])["total_budget_cents"] == 500


def test_resume_with_spent_equal_budget_rejected(api):
    """PRD §3.5: "Resuming (`PAUSED` → `ACTIVE`) requires `spent_cents` strictly
    below `total_budget_cents` — otherwise `ERR_BUDGET_EXHAUSTED`". Spent equals the
    total (500 == 500), so the paused campaign cannot resume.

    Design: Corner/validations/resume_with_spent_equal_budget_rejected
    """
    ctx = setup_exhausted_campaign_loop()
    get_success_data(api.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    cid = ctx["campaign"]["id"]
    assert get_campaign(cid)["campaign_status"] == "EXHAUSTED", "Setup failed"
    get_success_data(api.campaign_adjust_budget(cid, {"new_total_budget_cents": 1000}, ADOPS))
    get_success_data(api.campaign_adjust_budget(cid, {"new_total_budget_cents": 500}, ADOPS))
    get_success_data(api.campaign_pause(cid, ADOPS))
    assert get_campaign(cid)["campaign_status"] == "PAUSED", "Setup failed"

    resp = api.campaign_resume(cid, ADOPS)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXHAUSTED)
    assert get_campaign(cid)["campaign_status"] == "PAUSED"


def test_pause_cascade_voids_provisional_decisions(api):
    """PRD §3.5: "Pausing (`ACTIVE` → `PAUSED`) voids all of the campaign's
    provisional decisions, and every affected break recomputes — a `DECIDED` break
    left with no provisional or committed decisions falls back to `MARKED`."

    Design: Difficulty/transitive_cascade/r4_campaign_pause_cascade_voids_provisionals_and_unmarks_break
    """
    ctx = setup_validated_loop(channel_name="Ch I", break_durations=(60,))
    campaign, _ = create_active_campaign(
        total_budget_cents=5000, daily_budget_cents=5000
    )
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert decisions and decisions[0]["fill_type"] == "DIRECT", "Setup failed"

    paused = get_success_data(api.campaign_pause(campaign["id"], ADOPS))
    assert paused["campaign_status"] == "PAUSED"
    assert get_decision(decisions[0]["id"])["decision_status"] == "VOIDED"


def test_pause_cascade_unmarks_break_and_preserves_zero_spend(api):
    """PRD §3.5: "Pausing (`ACTIVE` → `PAUSED`) voids all of the campaign's
    provisional decisions" — provisional voiding has no spend impact: PRD §3.4
    "Reverting a validated loop (`VALIDATED` → `DRAFT`) voids every provisional fill
    decision on the loop's breaks — with no spend impact, since provisional
    decisions were never charged — and flips each break in `DECIDED` status that has
    no remaining provisional or committed decisions back to `MARKED`."

    Design: Difficulty/transitive_cascade/r4_campaign_pause_cascade_voids_provisionals_and_unmarks_break
    """
    ctx = setup_validated_loop(channel_name="Ch I2", break_durations=(60,))
    campaign, _ = create_active_campaign(
        total_budget_cents=5000, daily_budget_cents=5000
    )
    run_decision_run(ctx["breaks"][0]["id"])
    get_success_data(api.campaign_pause(campaign["id"], ADOPS))
    assert get_break(ctx["breaks"][0]["id"])["break_status"] == "MARKED"
    assert get_campaign(campaign["id"])["spent_cents"] == 0


def test_lock_commit_flips_campaign_exhausted_at_equality(api):
    """PRD §3.5: "The system itself moves a campaign to `EXHAUSTED` the moment
    `spent_cents` reaches or exceeds `total_budget_cents` after a commit or a
    reconcile adjustment". The 500-cent commit lands exactly on the 500-cent budget.

    Design: Difficulty/compensating_invariant/r9_commit_then_void_conserves_campaign_spent
    """
    ctx = setup_exhausted_campaign_loop()
    get_success_data(api.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["spent_cents"] == 500
    assert campaign["campaign_status"] == "EXHAUSTED", (
        "spent >= budget at exact equality"
    )


def test_void_committed_decision_refunds_and_revives_campaign(api):
    """PRD §3.6: "Voiding a committed decision refunds its `committed_cost_cents`
    from the campaign's `spent_cents`, which may return an `EXHAUSTED` campaign to
    `ACTIVE` when its flight remains valid". Commit (0 -> 500, EXHAUSTED) then void
    (500 -> 0, ACTIVE): the conserved spend returns to its pre-lock baseline.

    Design: Difficulty/compensating_invariant/r9_commit_then_void_conserves_campaign_spent
    """
    ctx = setup_exhausted_campaign_loop()
    get_success_data(api.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    assert get_campaign(ctx["campaign"]["id"])["campaign_status"] == "EXHAUSTED", "Setup failed"

    voided = get_success_data(api.fill_decision_void(ctx["decisions"][0]["id"], ADOPS))
    assert voided["decision_status"] == "VOIDED"
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["spent_cents"] == 0, "identical to the pre-lock baseline"
    assert campaign["campaign_status"] == "ACTIVE", (
        "EXHAUSTED revives when spend drops below budget and flight is valid"
    )
