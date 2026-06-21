"""Cascade chains and compensating-action invariants: reconcile depth-3, cancel→
waitlist auto-promotion, transfer share conservation, reopen→reconcile REC conservation,
and committed_kw reconciliation.

Translates queue A (Difficulty) rules `transitive_cascade` and `compensating_invariant`,
plus queue B (Corner) `cross_cutting_complexity_layers` derived-field instances.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_subscriber_headers,
    factories as f,
    fixtures as fx,
)

GO = TEST_USERS["grid_operator_headers"]
PA = TEST_USERS["program_admin_headers"]


# ─── Queue A: transitive_cascade ──────────────────────────────────────

def test_reconcile_cascade_allocation_final_credit(api):
    """PRD §3.10: "First, every allocation of the period moves `PROVISIONAL → FINAL`
    and its `final_credit_cents` is computed on the metered basis."

    Design: Difficulty/transitive_cascade/reconcile_period_to_allocation_to_reconciliation_to_rec_depth3
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-05", forecast_production_kwh=10000, metered_production_kwh=10000,
        project_overrides={"name": "Garden G", "credit_rate_cents_per_kwh": 1,
                           "program_fee_rate": 0.10},
    )
    alloc = fx.first_allocation(reconciled["id"])
    assert alloc["status"] == "FINAL"
    assert alloc["final_credit_cents"] == 10000  # metered 10000 * 1


def test_reconcile_cascade_reconciliation_and_rec_minting(api):
    """PRD §3.10: "Second, one reconciliation is created per `FINAL` allocation,
    starting with a credit dimension of `DRAFT` and a dispute dimension of `NONE`,
    recording its `subscription_id`, `period_id`, and `allocation_id`, and carrying its
    gross, fee, and net figures."
    PRD §3.10: "The project's `rec_minted_total` is recomputed as the sum of `rec_count`
    across REC batches whose period is in `RECONCILED`, `TRUED_UP`, or `CLOSED`."

    Design: Difficulty/transitive_cascade/reconcile_period_to_allocation_to_reconciliation_to_rec_depth3
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-05", forecast_production_kwh=10000, metered_production_kwh=10000,
        project_overrides={"name": "Garden G2", "credit_rate_cents_per_kwh": 1,
                           "program_fee_rate": 0.10},
    )
    recons = get_success_data(api.list_reconciliations(GO, params={"period_id": reconciled["id"]}))
    assert len(recons) == 1
    # gross 10000, non-CO: fee = round(10000*0.10*0.90) = 900; net = 9100.
    assert recons[0]["net_savings_cents"] == 9100
    proj = fx.get_project(project["id"])
    assert proj["rec_minted_total"] == 10  # floor(10000/1000)


def test_cancel_releases_capacity_flips_full_to_open(api):
    """PRD §3.5: "On cancellation the project ledger releases the share: `committed_kw`
    decreases by the subscription's `share_kw`, and `available_kw`,
    `carve_out_committed_kw`, and `carve_out_available_kw` are recomputed. If the
    project was `FULL` and now has room (its `available_kw` is greater than zero), its
    `status` returns to `OPEN`."

    Design: Difficulty/transitive_cascade/cancel_releases_capacity_then_autopromotes_waitlist_depth2
    """
    project, holder, holder_sub, waiter, waitlist_entry = fx.setup_full_project_with_waitlist(
        nameplate_capacity_kw=10, holder_share=10.0, waiter_share=5.0
    )
    get_success_data(
        api.cancel_subscription(holder_sub["id"], make_subscriber_headers(holder["id"]))
    )
    proj = fx.get_project(project["id"])
    assert proj["available_kw"] == 10
    assert proj["status"] == "OPEN"


def test_cancel_autopromotes_oldest_waitlist_entry(api):
    """PRD §3.6: "Among the project's `QUEUED` waitlist entries, the service picks the
    oldest by `queued_at` ascending, breaking ties by `created_at` ascending, whose
    `requested_share_kw` is no greater than the project's now-available `available_kw`.
    That entry is moved to `PROMOTED`, and the promotion mints a fresh enrollment for
    it; the entry's `promoted_enrollment_id` records that minted enrollment's id."

    Design: Difficulty/transitive_cascade/cancel_releases_capacity_then_autopromotes_waitlist_depth2
    """
    project, holder, holder_sub, waiter, waitlist_entry = fx.setup_full_project_with_waitlist(
        nameplate_capacity_kw=10, holder_share=10.0, waiter_share=5.0
    )
    get_success_data(
        api.cancel_subscription(holder_sub["id"], make_subscriber_headers(holder["id"]))
    )
    entry = get_success_data(api.get_waitlist_entry(waitlist_entry["id"], PA))
    assert entry["status"] == "PROMOTED"
    assert entry["promoted_enrollment_id"], "an Enrollment was minted on promotion"


# ─── Queue A: compensating_invariant ──────────────────────────────────

def test_transfer_conserves_project_committed_kw(api):
    """PRD §3.5: "Across the whole transfer the net change to `committed_kw` is zero,
    because the successor holds the same `share_kw`; when the original is cancelled by
    that system edge, its `cancellation_effective_period_id` is set to the project's
    current `OPEN` period if one exists."

    Design: Difficulty/compensating_invariant/transfer_conserves_project_committed_kw
    """
    project = fx.create_project(name="Garden P", nameplate_capacity_kw=100)
    owner = fx.create_subscriber(full_name="P Owner", utility_account_no="ACC-18", state_code="NY")
    target = fx.create_subscriber(full_name="P Target", utility_account_no="ACC-19", state_code="NY")
    subscription = fx.create_active_subscription(project["id"], owner["id"], 5.0)
    before = fx.get_project(project["id"])
    assert before["committed_kw"] == 5
    get_success_data(
        api.transfer_subscription(
            subscription["id"], f.transfer_payload(target["id"], before["version"]),
            make_subscriber_headers(owner["id"]),
        )
    )
    after = fx.get_project(project["id"])
    assert after["committed_kw"] == 5, "committed_kw unchanged across transfer"
    assert after["available_kw"] == 95


def test_transfer_creates_successor_with_back_reference(api):
    """PRD §3.5: "On success the service creates a successor subscription in status
    `ACTIVE` owned by the target, copying the same `share_kw`, setting
    `transferred_from_subscription_id` to the original subscription's id, and setting
    the successor's `is_carve_out` from the target subscriber's `is_low_income`."

    Design: Difficulty/compensating_invariant/transfer_conserves_project_committed_kw
    """
    project = fx.create_project(name="Garden P2", nameplate_capacity_kw=100)
    owner = fx.create_subscriber(full_name="P2 Owner", utility_account_no="ACC-18b", state_code="NY")
    target = fx.create_subscriber(full_name="P2 Target", utility_account_no="ACC-19b", state_code="NY")
    subscription = fx.create_active_subscription(project["id"], owner["id"], 5.0)
    before = fx.get_project(project["id"])
    successor = get_success_data(
        api.transfer_subscription(
            subscription["id"], f.transfer_payload(target["id"], before["version"]),
            make_subscriber_headers(owner["id"]),
        )
    )
    assert successor["status"] == "ACTIVE"
    assert successor["share_kw"] == 5
    assert successor["transferred_from_subscription_id"] == subscription["id"]


def test_reopen_then_reconcile_conserves_rec_minted_total(api):
    """PRD §3.12: "Reopening deletes all of the period's reconciliations, moves each
    allocation `FINAL → PROVISIONAL`, clears each `final_credit_cents`, and resets the
    minted REC batch so the period's `rec_minted_count` is recomputed at the next
    reconcile."
    PRD §3.10: "in status `MINTED`, whose `rec_count` is the floor of the period's
    `metered_production_kwh` divided by 1000 (one REC per 1000 metered kWh)."

    Design: Difficulty/compensating_invariant/reopen_then_reconcile_conserves_rec_minted_total
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-10", forecast_production_kwh=10000, metered_production_kwh=10000,
        project_overrides={"name": "Garden Q", "program_fee_rate": 0.10},
    )
    before = fx.get_project(project["id"])
    assert before["rec_minted_total"] == 10
    get_success_data(api.reopen_period(reconciled["id"], GO))
    reopened = fx.get_period(reconciled["id"])
    fx.reconcile_period(reconciled["id"], reopened["version"])
    after = fx.get_project(project["id"])
    assert after["rec_minted_total"] == 10, "no REC drift after reopen+reconcile"


def test_reopen_moves_allocations_back_to_provisional(api):
    """PRD §3.12: "Reopening deletes all of the period's reconciliations, moves each
    allocation `FINAL → PROVISIONAL`, clears each `final_credit_cents`, and resets the
    minted REC batch so the period's `rec_minted_count` is recomputed at the next
    reconcile."
    PRD §3.12: "A `RECONCILED` period that should not have been finalized can be
    reopened by a `GridOperator`, moving it `RECONCILED → METERED`, provided no
    reconciliation of that period has yet reached credit `APPLIED`; a reopen attempted
    after any reconciliation was applied is rejected with `ERR_RECON_ALREADY_APPLIED`
    (HTTP 409)."

    Design: Difficulty/compensating_invariant/reopen_then_reconcile_conserves_rec_minted_total
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-10", forecast_production_kwh=10000, metered_production_kwh=10000,
        project_overrides={"name": "Garden Q2", "program_fee_rate": 0.10},
    )
    reopened = get_success_data(api.reopen_period(reconciled["id"], GO))
    assert reopened["status"] == "METERED", "reopen returns RECONCILED → METERED"
    alloc = fx.first_allocation(reconciled["id"])
    assert alloc["status"] == "PROVISIONAL", "allocation moved FINAL → PROVISIONAL"


# ─── Queue B: derived-field reconciliation ────────────────────────────

def test_derived_field_committed_kw_reconciles_after_activate_and_cancel(api):
    """PRD §2.5: "`committed_kw` is the sum of `share_kw` across all subscriptions of
    the project whose status is `ACTIVE`, `SUSPENDED`, or `TRANSFERRING`."
    PRD §3.5: "On cancellation the project ledger releases the share: `committed_kw`
    decreases by the subscription's `share_kw`, and `available_kw`,
    `carve_out_committed_kw`, and `carve_out_available_kw` are recomputed."

    Design: Corner/cross_cutting_complexity_layers/derived_field_committed_kw_reconciles_after_activate_and_cancel
    """
    project, subscriber, subscription = fx.setup_project_with_active_subscription(
        project_overrides={"name": "P34"}, requested_share_kw=5.0
    )
    after_activate = fx.get_project(project["id"])
    assert after_activate["committed_kw"] == 5
    get_success_data(
        api.cancel_subscription(subscription["id"], make_subscriber_headers(subscriber["id"]))
    )
    after_cancel = fx.get_project(project["id"])
    assert after_cancel["committed_kw"] == 0
    assert after_cancel["available_kw"] == 100


def test_occ_version_increments_on_each_write(api):
    """PRD §2.4: "Most entities also carry a `version`, an integer that begins at its
    initial value when the resource is created and increments by one each time the
    resource is mutated, alongside a refresh of `updated_at`."
    PRD §3.1: "recomputes `carve_out_available_kw` from the new fraction, and increments
    the project's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_write
    """
    project = fx.create_project(name="P33", carve_out_pct=0.40)
    assert project["version"] == 1
    fx.create_carve_out_adjustment(project["id"], 0.50, "expand")
    after = fx.get_project(project["id"])
    assert after["version"] == 2
