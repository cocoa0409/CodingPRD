"""State machines, cyclic workflows, cascading side effects, and compensating
invariants (PRD §3.1-§3.9).

Difficulty queue: non_linear_state_machine (IPS cycle, plan parallel axes),
transitive_cascade (freeze depth-3, IPS approve supersede depth-2),
compensating_invariant (freeze/unfreeze conserves AUM, supersede conserves count).
Corner queue: side-effect executions and the rebalance execute collapse.
"""
import pytest

from test_helpers import (
    validate_success, validate_paginated, get_success_data, api_client as api,
    TEST_USERS, make_advisor_headers, make_compliance_headers,
    fixtures as fx, factories as f, STANDARD_TIERS,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine / ips_draft_proposed_revision_cycle
# ===========================================================================
def test_ips_revision_round_increments_over_two_cycles(api):
    """PRD §3.2: "Requesting changes returns the statement from `PROPOSED` to
    `DRAFT` and, as its side effect, increments `revision_round` by one — this is
    the cycle counter that records how many times the statement has been bounced
    back."

    Two PROPOSE/REQUEST_CHANGES loops -> revision_round 2, status DRAFT.

    Design: Difficulty/non_linear_state_machine/ips_draft_proposed_revision_cycle
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips = fx.create_draft_ips(client["id"], pf["id"], max_equity_pct=80)
    adv = make_advisor_headers("adv-1")
    co = make_compliance_headers("co-1")
    get_success_data(api.ips_state(ips["id"], "PROPOSE", adv))
    get_success_data(api.ips_state(ips["id"], "REQUEST_CHANGES", co))
    get_success_data(api.ips_state(ips["id"], "PROPOSE", adv))
    data = validate_success(api.ips_state(ips["id"], "REQUEST_CHANGES", co))
    assert data["status"] == "DRAFT", f"after second REQUEST_CHANGES expect DRAFT, got {data['status']}"
    assert data["revision_round"] == 2, \
        f"two cycles -> revision_round 2, got {data['revision_round']}"


def test_ips_single_request_changes_round_one(api):
    """PRD §3.2: "Requesting changes returns the statement from `PROPOSED` to
    `DRAFT` and, as its side effect, increments `revision_round` by one"

    One cycle -> revision_round 1.

    Design: Difficulty/non_linear_state_machine/ips_draft_proposed_revision_cycle
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips = fx.create_draft_ips(client["id"], pf["id"], max_equity_pct=80)
    adv = make_advisor_headers("adv-1")
    co = make_compliance_headers("co-1")
    get_success_data(api.ips_state(ips["id"], "PROPOSE", adv))
    data = validate_success(api.ips_state(ips["id"], "REQUEST_CHANGES", co))
    assert data["status"] == "DRAFT"
    assert data["revision_round"] == 1, \
        f"one cycle -> revision_round 1, got {data['revision_round']}"


# ===========================================================================
# Difficulty: non_linear_state_machine / financial_plan_parallel_lifecycle_and_review_axes
# ===========================================================================
def test_mark_reviewed_leaves_lifecycle_draft(api):
    """PRD §3.6: "A plan tracks a `lifecycle_status` on one axis — `DRAFT`, then
    `ACTIVE`, then the terminal `ARCHIVED` — and a `review_status` on a fully
    independent axis — `NEEDS_REVIEW`, `REVIEWED`, and `STALE` — both evolving on
    the same plan without touching each other."
    PRD §3.6: "On the review axis, marking reviewed moves a plan from either
    `NEEDS_REVIEW` or `STALE` to `REVIEWED` and, as a side effect, recomputes
    `funded_ratio_bps` and `on_track` for every goal under the plan; marking stale
    moves a plan from `REVIEWED` to `STALE` with no field change beyond the review
    status."

    Design: Difficulty/non_linear_state_machine/financial_plan_parallel_lifecycle_and_review_axes
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    plan = fx.create_draft_plan(hh["id"], assumed_annual_return_bps=600,
                                monthly_contribution_cents=0)
    fx.create_goal(plan["id"], target_amount_cents=1000000, target_date="2030-01-01",
                   current_amount_cents=0)
    data = validate_success(api.financial_plan_state(plan["id"], "MARK_REVIEWED", ADVISOR))
    assert data["review_status"] == "REVIEWED", \
        f"review axis -> REVIEWED, got {data['review_status']}"
    assert data["lifecycle_status"] == "DRAFT", \
        f"lifecycle axis unchanged, got {data['lifecycle_status']}"


def test_activate_leaves_review_status_unchanged(api):
    """PRD §3.6: "On the lifecycle axis, activating moves a plan from `DRAFT` to
    `ACTIVE` and requires at least one goal to exist under the plan; as a side
    effect it recomputes `funded_ratio_bps` and `on_track` for every goal under the
    plan."
    PRD §3.6: "A plan tracks a `lifecycle_status` on one axis — `DRAFT`, then
    `ACTIVE`, then the terminal `ARCHIVED` — and a `review_status` on a fully
    independent axis — `NEEDS_REVIEW`, `REVIEWED`, and `STALE` — both evolving on
    the same plan without touching each other."

    After MARK_REVIEWED then ACTIVATE, lifecycle is ACTIVE and review stays REVIEWED.

    Design: Difficulty/non_linear_state_machine/financial_plan_parallel_lifecycle_and_review_axes
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    plan = fx.create_draft_plan(hh["id"], assumed_annual_return_bps=600,
                                monthly_contribution_cents=0)
    fx.create_goal(plan["id"], target_amount_cents=1000000, target_date="2030-01-01",
                   current_amount_cents=0)
    get_success_data(api.financial_plan_state(plan["id"], "MARK_REVIEWED", ADVISOR))
    data = validate_success(api.financial_plan_state(plan["id"], "ACTIVATE", ADVISOR))
    assert data["lifecycle_status"] == "ACTIVE", \
        f"lifecycle axis -> ACTIVE, got {data['lifecycle_status']}"
    assert data["review_status"] == "REVIEWED", \
        f"review axis unchanged by lifecycle transition, got {data['review_status']}"


# ===========================================================================
# Difficulty: transitive_cascade / account_freeze_rejects_rebalance_then_clears_flag_depth3
# ===========================================================================
def test_freeze_rejects_proposed_rebalance_and_keeps_aggregated(api):
    """PRD §3.3: "freezing additionally cancels any rebalance order for that
    account currently in `PROPOSED` status by transitioning it from `PROPOSED` to
    `REJECTED`."
    PRD §3.3: "a frozen account's value is still aggregated into
    `aggregated_aum_cents` but is no longer billable, so the two figures diverge"

    Design: Difficulty/transitive_cascade/account_freeze_rejects_rebalance_then_clears_flag_depth3
    """
    setup = fx.setup_account_with_approved_ips(
        market_value_cents=200000000, equity_value_cents=200000000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct = setup["account"]
    hh = setup["household"]
    ro = fx.create_proposed_rebalance(acct["id"])
    # Trigger: FREEZE the account.
    frozen = validate_success(api.account_state(acct["id"], "FREEZE", ADVISOR))
    assert frozen["status"] == "FROZEN"
    ro_after = validate_success(api.get_rebalance_order(ro["id"], ADVISOR))
    assert ro_after["status"] == "REJECTED", \
        f"freeze cascades PROPOSED order to REJECTED, got {ro_after['status']}"
    hh_after = validate_success(api.get_household(hh["id"], ADVISOR))
    assert hh_after["aggregated_aum_cents"] == 200000000, \
        f"frozen account still aggregated, got {hh_after['aggregated_aum_cents']}"


def test_freeze_diverges_billable_from_aggregated(api):
    """PRD §3.3: "Freezing recomputes `billable_aum_cents` and `aggregated_aum_cents`
    — a frozen account's value is still aggregated into `aggregated_aum_cents` but
    is no longer billable, so the two figures diverge"

    Design: Difficulty/transitive_cascade/account_freeze_rejects_rebalance_then_clears_flag_depth3
    """
    setup = fx.setup_account_with_approved_ips(
        market_value_cents=200000000, equity_value_cents=200000000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct = setup["account"]
    hh = setup["household"]
    get_success_data(api.account_state(acct["id"], "FREEZE", ADVISOR))
    hh_after = validate_success(api.get_household(hh["id"], ADVISOR))
    assert hh_after["billable_aum_cents"] == 0, \
        f"frozen account drops from billable, got {hh_after['billable_aum_cents']}"
    assert hh_after["aggregated_aum_cents"] == 200000000, \
        f"frozen account still aggregated, got {hh_after['aggregated_aum_cents']}"


# ===========================================================================
# Difficulty: transitive_cascade / ips_approve_supersede_and_compliance_item_depth2
# ===========================================================================
def test_approve_second_ips_supersedes_prior_approved(api):
    """PRD §3.2: "it supersedes any other statement for the same `client_id`
    currently in `APPROVED` status by transitioning that prior statement from
    `APPROVED` to `SUPERSEDED`"

    Design: Difficulty/transitive_cascade/ips_approve_supersede_and_compliance_item_depth2
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips1 = fx.create_approved_ips(client["id"], pf["id"], max_equity_pct=80)
    ips2 = fx.create_proposed_ips(client["id"], pf["id"], max_equity_pct=70)
    data = validate_success(api.ips_state(ips2["id"], "APPROVE",
                                          make_compliance_headers("co-1")))
    assert data["status"] == "APPROVED", f"second IPS -> APPROVED, got {data['status']}"
    ips1_after = validate_success(api.get_ips(ips1["id"], COMPLIANCE))
    assert ips1_after["status"] == "SUPERSEDED", \
        f"prior APPROVED IPS -> SUPERSEDED, got {ips1_after['status']}"


def test_approve_ips_opens_ips_archive_compliance_item(api):
    """PRD §3.2: "it opens a compliance obligation — a compliance item whose
    `subject_type` is `CLIENT`, whose `subject_id` is the client, whose
    `obligation_type` is `IPS_ARCHIVE`, and whose status is `OPEN`."

    Design: Difficulty/transitive_cascade/ips_approve_supersede_and_compliance_item_depth2
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips1 = fx.create_approved_ips(client["id"], pf["id"], max_equity_pct=80)
    ips2 = fx.create_proposed_ips(client["id"], pf["id"], max_equity_pct=70)
    get_success_data(api.ips_state(ips2["id"], "APPROVE", make_compliance_headers("co-1")))
    items, _meta = validate_paginated(
        api.list_compliance_items(COMPLIANCE, params={"subject_id": client["id"]}))
    archive_items = [it for it in items
                     if it["obligation_type"] == "IPS_ARCHIVE" and it["status"] == "OPEN"]
    assert len(archive_items) >= 1, \
        f"approve must open an OPEN IPS_ARCHIVE item for the client, got {items}"


# ===========================================================================
# Difficulty: compensating_invariant / freeze_unfreeze_conserves_household_billable_aum
# ===========================================================================
def test_freeze_then_unfreeze_restores_billable_aum(api):
    """PRD §3.3: "Freezing moves an account from `ACTIVE` to `FROZEN`; unfreezing
    moves it back from `FROZEN` to `ACTIVE` and requires the owning household to be
    `ACTIVE`."
    PRD §3.3: "Activation, unfreezing, and either closure path each recompute
    `billable_aum_cents` and `aggregated_aum_cents`; activation and the two closure
    paths additionally recompute `breakpoint_tier_index`."

    FREEZE drops billable to 0; UNFREEZE restores it to the exact pre-freeze value.

    Design: Difficulty/compensating_invariant/freeze_unfreeze_conserves_household_billable_aum
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    acct = fx.create_active_billable_account(hh["id"], client["id"],
                                             market_value_cents=200000000)
    before = validate_success(api.get_household(hh["id"], ADVISOR))
    assert before["billable_aum_cents"] == 200000000
    get_success_data(api.account_state(acct["id"], "FREEZE", ADVISOR))
    frozen = validate_success(api.get_household(hh["id"], ADVISOR))
    assert frozen["billable_aum_cents"] == 0, \
        f"frozen account excluded from billable, got {frozen['billable_aum_cents']}"
    get_success_data(api.account_state(acct["id"], "UNFREEZE", ADVISOR))
    after = validate_success(api.get_household(hh["id"], ADVISOR))
    assert after["billable_aum_cents"] == 200000000, \
        f"unfreeze restores billable to exact pre-freeze value, got {after['billable_aum_cents']}"


def test_freeze_unfreeze_conserves_aggregated_aum(api):
    """PRD §3.3: "Activation, unfreezing, and either closure path each recompute
    `billable_aum_cents` and `aggregated_aum_cents`; activation and the two closure
    paths additionally recompute `breakpoint_tier_index`."
    PRD §2.8: "The `aggregated_aum_cents` is the broader figure: the sum of
    `market_value_cents` over **all** the household's `ACTIVE` member accounts,
    including held-away and non-billable ones."

    aggregated_aum_cents holds 200,000,000 while ACTIVE and is restored to that exact
    value after the FREEZE/UNFREEZE round-trip (the account is ACTIVE again).

    Design: Difficulty/compensating_invariant/freeze_unfreeze_conserves_household_billable_aum
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    acct = fx.create_active_billable_account(hh["id"], client["id"],
                                             market_value_cents=200000000)
    before = validate_success(api.get_household(hh["id"], ADVISOR))
    assert before["aggregated_aum_cents"] == 200000000
    get_success_data(api.account_state(acct["id"], "FREEZE", ADVISOR))
    get_success_data(api.account_state(acct["id"], "UNFREEZE", ADVISOR))
    after = validate_success(api.get_household(hh["id"], ADVISOR))
    assert after["aggregated_aum_cents"] == 200000000, \
        f"aggregated AUM restored exactly after the round-trip, got {after['aggregated_aum_cents']}"


# ===========================================================================
# Difficulty: compensating_invariant / ips_approve_supersede_conserves_approved_ips_count
# ===========================================================================
def test_supersede_conserves_approved_ips_count_at_one(api):
    """PRD §3.2: "it supersedes any other statement for the same `client_id`
    currently in `APPROVED` status by transitioning that prior statement from
    `APPROVED` to `SUPERSEDED`"

    Before the second approve there is exactly one APPROVED IPS; after, still
    exactly one (the new one), the prior is SUPERSEDED.

    Design: Difficulty/compensating_invariant/ips_approve_supersede_conserves_approved_ips_count
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips1 = fx.create_approved_ips(client["id"], pf["id"], max_equity_pct=80)

    def count_approved():
        items, _ = validate_paginated(
            api.list_ips(COMPLIANCE, params={"client_id": client["id"]}))
        return sum(1 for it in items if it["status"] == "APPROVED")

    assert count_approved() == 1, "exactly one APPROVED before the second approve"
    ips2 = fx.create_proposed_ips(client["id"], pf["id"], max_equity_pct=70)
    get_success_data(api.ips_state(ips2["id"], "APPROVE", make_compliance_headers("co-1")))
    assert count_approved() == 1, "cardinality conserved: still exactly one APPROVED"
    ips1_after = validate_success(api.get_ips(ips1["id"], COMPLIANCE))
    assert ips1_after["status"] == "SUPERSEDED"
    ips2_after = validate_success(api.get_ips(ips2["id"], COMPLIANCE))
    assert ips2_after["status"] == "APPROVED"


def test_supersede_makes_prior_terminal_and_new_active(api):
    """PRD §3.2: "The `SUPERSEDED` state is terminal and is reached only through
    this system-driven supersession; it carries no further cascade."
    PRD §3.2: "it supersedes any other statement for the same `client_id` currently
    in `APPROVED` status by transitioning that prior statement from `APPROVED` to
    `SUPERSEDED`"

    The single-approved-IPS invariant viewed as a status pair: exactly one of the
    two client IPSs is APPROVED and the other is the terminal SUPERSEDED.

    Design: Difficulty/compensating_invariant/ips_approve_supersede_conserves_approved_ips_count
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips1 = fx.create_approved_ips(client["id"], pf["id"], max_equity_pct=80)
    ips2 = fx.create_proposed_ips(client["id"], pf["id"], max_equity_pct=70)
    get_success_data(api.ips_state(ips2["id"], "APPROVE", make_compliance_headers("co-1")))
    statuses = {
        validate_success(api.get_ips(ips1["id"], COMPLIANCE))["status"],
        validate_success(api.get_ips(ips2["id"], COMPLIANCE))["status"],
    }
    assert statuses == {"APPROVED", "SUPERSEDED"}, \
        f"exactly one APPROVED and one SUPERSEDED, got {statuses}"


# ===========================================================================
# Corner: state_machines / review_complete_computes_next_due_date
# ===========================================================================
def test_review_complete_stamps_next_due_date(api):
    """PRD §3.8: "Completing a review moves it from `SCHEDULED` to the terminal
    `COMPLETED` state; it requires the review be `SCHEDULED` and the owning household
    be `ACTIVE`, and as side effects it stamps `completed_at` with the current
    logical-clock datetime and computes `next_due_date` as the `completed_at` date
    plus `cadence_days`."

    Design: Corner/state_machines/review_complete_computes_next_due_date
    """
    fx.set_clock("2026-03-01T00:00:00Z", headers=ADVISOR)
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    rev = get_success_data(api.create_review(
        f.review_payload(hh["id"], scheduled_for="2026-03-01", cadence_days=365), ADVISOR))
    data = validate_success(api.complete_review(rev["id"], ADVISOR))
    assert data["status"] == "COMPLETED"
    assert data["next_due_date"] == "2027-03-01", \
        f"completed_at date + 365 days == 2027-03-01, got {data['next_due_date']}"


# ===========================================================================
# Corner: state_machines / later_review_supersedes_earlier_as_missed
# ===========================================================================
def test_later_review_supersedes_earlier_as_missed(api):
    """PRD §3.8: "When a new review is scheduled for a household and its
    `scheduled_for` falls after that of an existing `SCHEDULED` review for the same
    household, the earlier `SCHEDULED` review is superseded — it transitions from
    `SCHEDULED` to the terminal `MISSED` state with no further cascade."

    Design: Corner/state_machines/later_review_supersedes_earlier_as_missed
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    rev1 = get_success_data(api.create_review(
        f.review_payload(hh["id"], scheduled_for="2026-06-01", cadence_days=365), ADVISOR))
    rev2 = get_success_data(api.create_review(
        f.review_payload(hh["id"], scheduled_for="2026-12-01", cadence_days=365), ADVISOR))
    r1 = validate_success(api.get_review(rev1["id"], ADVISOR))
    r2 = validate_success(api.get_review(rev2["id"], ADVISOR))
    assert r1["status"] == "MISSED", f"earlier review superseded -> MISSED, got {r1['status']}"
    assert r2["status"] == "SCHEDULED", f"later review remains SCHEDULED, got {r2['status']}"


# ===========================================================================
# Corner: state_machines / fee_run_calculate_locks_fee_schedule
# ===========================================================================
def test_calculate_locks_schedule_and_blocks_edit(api):
    """PRD §2.9: "A schedule exposes `is_locked`, which starts false and becomes
    true the moment any fee run that references the schedule reaches `CALCULATED`
    or `FINALIZED`. A locked schedule rejects edits to its tiers or minimum; such
    an edit is treated as an illegal operation and rejected with
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/fee_run_calculate_locks_fee_schedule
    """
    from test_helpers import validate_error, ApiErrorId
    setup = fx.setup_household_with_active_account(
        market_value_cents=100000000, billing_method="ARREARS")
    hh = setup["household"]
    sched = setup["fee_schedule"]
    v = fx.household_version(hh["id"])
    fx.create_calculated_fee_run(hh["id"], v)
    locked = validate_success(api.get_fee_schedule(sched["id"], TEST_USERS["billing_headers"]))
    assert locked["is_locked"] is True, "schedule must be locked after CALCULATE"
    resp = api.patch_fee_schedule(sched["id"], {"minimum_annual_fee_cents": 500},
                                  TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / fee_run_initial_state_is_draft
# ===========================================================================
def test_fee_run_starts_draft_with_zero_fees(api):
    """PRD §3.4: "On a successful create the run begins in `DRAFT`, and the system
    snapshots two values that pin the run against later drift: `billing_method_snapshot`,
    a copy of the household's `billing_method` (`ARREARS` or `ADVANCE`), and
    `fee_schedule_snapshot_id`, the household's fee schedule pinned at creation."
    PRD §3.4: "The run's `basis_aum_cents`, `gross_fee_cents`, and
    `assessed_fee_cents` all begin at 0; they are filled in by calculation."

    Design: Corner/state_machines/fee_run_initial_state_is_draft
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    v = fx.household_version(hh["id"])
    data = validate_success(api.create_fee_run(
        f.fee_run_payload(hh["id"], v), TEST_USERS["billing_headers"]), expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["gross_fee_cents"] == 0
    assert data["assessed_fee_cents"] == 0


# ===========================================================================
# Corner: endpoints / rebalance_execute_collapses_drift_action_endpoint
# ===========================================================================
def test_rebalance_execute_collapses_drift_to_zero(api):
    """PRD §3.7: "execution requires the order be `APPROVED` and the linked account
    be `ACTIVE`. Executing has two side effects on the account: it sets the
    account's `equity_value_cents` so that the account's actual equity percentage
    equals the target portfolio's `model_equity_pct`, and it then recomputes the
    account's `drift_bps` and `rebalance_flagged`, which collapse the drift toward
    zero."

    Design: Corner/endpoints/rebalance_execute_collapses_drift_action_endpoint
    """
    setup = fx.setup_account_with_approved_ips(
        market_value_cents=1000000, equity_value_cents=800000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct = setup["account"]
    ro = fx.create_approved_rebalance(acct["id"])
    data = validate_success(api.rebalance_order_state(ro["id"], "EXECUTE", ADVISOR))
    assert data["status"] == "EXECUTED"
    acct_after = validate_success(api.get_account(acct["id"], ADVISOR))
    assert acct_after["drift_bps"] == 0, \
        f"execute collapses drift to 0, got {acct_after['drift_bps']}"
    assert acct_after["rebalance_flagged"] is False
