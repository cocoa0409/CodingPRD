"""Recall compensation (value conservation), vault/directive state locks, clock-driven
sweeps, and plan life-status lifecycle cascades."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_owner_headers, ADMIN_HEADERS,
    setup_released_asset,
    set_clock, create_plan, create_vault_item, seal_vault_item, create_beneficiary,
    create_review_reminder, mark_life_status,
)


# --------------------------------------------------------------------------- #
# value_conservation_release_then_recall_asset  (Difficulty/compensating_invariant)
# --------------------------------------------------------------------------- #
def test_recall_reverts_item_to_sealed_preserving_net_value(api):
    """PRD 3.2: "An owner or administrator may recall a released item back to `SEALED`;
    recalling an asset compensates its distribution by reverting every linked `VESTED`
    beneficiary back to `NOMINATED` and resetting each one's `allocated_value_cents` to 0,
    which conserves the asset's distributable value."

    Design: Difficulty/compensating_invariant/value_conservation_release_then_recall_asset
    """
    ctx = setup_released_asset(api, gross_value_cents=10000, liability_cents=1,
                               distribution_basis="NET", allocations=(100,))
    resp = api.recall_vault_item(ctx["item_id"], ADMIN_HEADERS)
    data = validate_success(resp, 200)
    assert data["status"] == "SEALED", f"expected SEALED, got {data['status']}"
    assert data["net_value_cents"] == 9999, f"net value must be conserved at 9999, got {data['net_value_cents']}"


def test_recall_reverts_beneficiary_to_nominated_zeroing_allocation(api):
    """PRD 3.2: "recalling an asset compensates its distribution by reverting every linked
    `VESTED` beneficiary back to `NOMINATED` and resetting each one's `allocated_value_cents`
    to 0, which conserves the asset's distributable value."

    Design: Difficulty/compensating_invariant/value_conservation_release_then_recall_asset
    """
    ctx = setup_released_asset(api, gross_value_cents=10000, liability_cents=1,
                               distribution_basis="NET", allocations=(100,))
    api.recall_vault_item(ctx["item_id"], ADMIN_HEADERS)
    b1 = ctx["beneficiary_ids"][0]
    data = validate_success(api.get_beneficiary(b1, make_owner_headers(ctx["plan_id"])), 200)
    assert data["status"] == "NOMINATED", f"expected NOMINATED, got {data['status']}"
    assert data["allocated_value_cents"] == 0, f"expected 0, got {data['allocated_value_cents']}"


# --------------------------------------------------------------------------- #
# seal_already_sealed_item_returns_invalid_state  (Corner/state_machines)
# --------------------------------------------------------------------------- #
def test_seal_already_sealed_item_rejected(api):
    """PRD 3.2: "An item's `status` follows the lifecycle `DRAFT → SEALED → RELEASED`, with
    `ARCHIVED` as a terminal soft-delete reachable from either `DRAFT` or `SEALED`."
    PRD 2.8: "Sixth, for state-transition endpoints, the target must be in a state from
    which the requested transition is defined, otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/seal_already_sealed_item_returns_invalid_state
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    item = create_vault_item(api, plan_id, kind="DOCUMENT", category="will", title="Will",
                             secret_ref="vault://will")
    seal_vault_item(api, plan_id, item["id"])
    resp = api.seal_vault_item(item["id"], make_owner_headers(plan_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# --------------------------------------------------------------------------- #
# plan_deceased_dismisses_scheduled_reminders  (Corner/state_machines)
# --------------------------------------------------------------------------- #
def test_declaring_death_dismisses_scheduled_reminder(api):
    """PRD 3.1: "When a plan transitions to `DECEASED`, every review reminder on that plan
    whose status is `SCHEDULED`, `DUE`, or `OVERDUE` is cascaded to `DISMISSED` as part of
    the same operation."

    Design: Corner/state_machines/plan_deceased_dismisses_scheduled_reminders
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    reminder = create_review_reminder(api, plan_id, subject_kind="VAULT", interval_days=180,
                                      last_reviewed_at="2026-06-01T00:00:00Z")
    plan_after = mark_life_status(api, plan_id, "DECEASED")
    assert plan_after["life_status"] == "DECEASED", f"expected DECEASED, got {plan_after['life_status']}"
    got = validate_success(api.get_review_reminder(reminder["id"], make_owner_headers(plan_id)), 200)
    assert got["status"] == "DISMISSED", f"expected DISMISSED, got {got['status']}"


# --------------------------------------------------------------------------- #
# integration_sync_cycle_sets_last_synced  (Corner/state_machines)
# --------------------------------------------------------------------------- #
def test_integration_sync_returns_to_linked_and_stamps_last_synced(api):
    """PRD 3.8: "An owner or administrator may trigger a sync, which moves `sync_status`
    from `LINKED` to `SYNCING` and, as the sync completes within the same request, back to
    `LINKED`, setting `last_synced_at` to the current clock."

    Design: Corner/state_machines/integration_sync_cycle_sets_last_synced
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    integ = validate_success(api.create_integration(
        {"plan_id": plan_id, "provider_type": "WILL_REGISTRY", "provider_name": "StateReg",
         "external_ref": "WR-1"}, make_owner_headers(plan_id)), 201)
    data = validate_success(api.sync_integration(integ["id"], make_owner_headers(plan_id)), 200)
    assert data["sync_status"] == "LINKED", f"expected LINKED, got {data['sync_status']}"
    assert data["last_synced_at"] is not None, "last_synced_at must be stamped after sync"


# --------------------------------------------------------------------------- #
# review_reminder_sweep_marks_overdue  (Corner/calculations)
# --------------------------------------------------------------------------- #
def test_sweep_marks_reminder_overdue_past_grace(api):
    """PRD 3.8: "The reminder's `due_at` is computed as the anchor `last_reviewed_at` plus
    `interval_days` days, and it starts in `SCHEDULED` status."
    PRD 3.8: "and once the clock reaches `due_at` plus 30 days or later it becomes
    `OVERDUE`."

    Design: Corner/calculations/review_reminder_sweep_marks_overdue
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    reminder = create_review_reminder(api, plan_id, subject_kind="DIRECTIVE", interval_days=180,
                                      last_reviewed_at="2026-06-01T00:00:00Z")
    # due_at = 2026-11-28; due_at + 30d grace = 2026-12-28; clock beyond -> OVERDUE.
    set_clock(api, "2027-01-01T00:00:00Z")
    validate_success(api.run_review_sweep({"plan_id": plan_id}, ADMIN_HEADERS), 200)
    got = validate_success(api.get_review_reminder(reminder["id"], make_owner_headers(plan_id)), 200)
    assert got["status"] == "OVERDUE", f"expected OVERDUE, got {got['status']}"


# --------------------------------------------------------------------------- #
# life_status_backwards_returns_invalid_life_event  (Corner/errors)
# --------------------------------------------------------------------------- #
def test_life_status_moving_backward_rejected(api):
    """PRD 3.1: "Any other requested life-status change — for instance moving backward, or
    supplying a status outside the `ACTIVE`/`INCAPACITATED`/`DECEASED` set — is rejected with
    `ERR_INVALID_LIFE_EVENT`."

    Design: Corner/errors/life_status_backwards_returns_invalid_life_event
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    mark_life_status(api, plan_id, "DECEASED")
    resp = api.set_life_status(
        plan_id, {"new_status": "INCAPACITATED", "evidence_ref": "cert-002"}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_LIFE_EVENT)


# --------------------------------------------------------------------------- #
# seal_asset_over_allocated_returns_allocation_exceeds_100  (Corner/validations)
# --------------------------------------------------------------------------- #
def test_seal_asset_with_over_100_percent_allocation_rejected(api):
    """PRD 3.2: "Sealing an asset requires that its `gross_value_cents` be present, and if
    beneficiaries are already linked to that asset, the sum of `allocation_pct` across the
    item's `NOMINATED` beneficiaries must not exceed 100 at the moment of sealing — a
    violation is rejected with `ERR_ALLOCATION_EXCEEDS_100`."

    Design: Corner/validations/seal_asset_over_allocated_returns_allocation_exceeds_100
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    item = create_vault_item(api, plan_id, kind="ASSET", category="estate", title="House",
                             secret_ref="vault://house", gross_value_cents=10000,
                             liability_cents=0, distribution_basis="NET")
    create_beneficiary(api, plan_id, full_name="Ben One", relationship="child",
                       allocation_pct=60, asset_vault_item_id=item["id"])
    create_beneficiary(api, plan_id, full_name="Ben Two", relationship="child",
                       allocation_pct=50, asset_vault_item_id=item["id"])
    resp = api.seal_vault_item(item["id"], make_owner_headers(plan_id))
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_100)
