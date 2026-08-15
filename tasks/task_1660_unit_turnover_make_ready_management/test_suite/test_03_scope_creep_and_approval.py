"""Scope-creep tiering at both thresholds, the approval authority chain,
OCC on approval, validation precedence, and budget reconciliation."""
from test_helpers import (
    PM,
    RM,
    TC,
    ApiErrorId,
    add_scope_item,
    get_item,
    get_turn,
    setup_scoped_turn,
    validate_error,
    validate_success,
)


def _scoped_turn_with_budget(budget=100000, **property_overrides):
    """Turn SCOPED with a single base REPAIR item; approved budget locked."""
    return setup_scoped_turn("REPAIR", budget, **property_overrides)


# --- pm-threshold boundary (Difficulty: scope_creep_variance_exact_threshold_boundary)

def test_variance_exactly_at_pm_threshold_auto_approves(api):
    """PRD §3.5: "A variance at or below the property's `pm_threshold_bp` earns
    `approval_tier` `NONE` and the item is created directly in `PLANNED` —
    auto-approved, with equality at the threshold still approving."

    Design: Difficulty/boundary_precision_check/scope_creep_variance_exact_threshold_boundary
    """
    ctx = _scoped_turn_with_budget(100000)  # pm_threshold_bp 1000
    # 10000 over 100000 == exactly 1000bp variance: <=, so auto-approved.
    item = add_scope_item(ctx["turn"]["id"], "CLEAN", 10000, "at threshold")
    assert item["status"] == "PLANNED"
    assert item["approval_tier"] == "NONE"


def test_variance_one_tick_over_pm_threshold_requires_pm(api):
    """PRD §3.5: "A variance above `pm_threshold_bp` but at or below
    `rm_threshold_bp` earns tier `PM`; anything above `rm_threshold_bp` earns
    tier `RM` — and note that equality at the regional threshold stays in the
    `PM` tier. Items in either escalated tier are created in `PENDING_APPROVAL`
    and are invisible to the turn's estimate and projection until approved."

    Design: Difficulty/boundary_precision_check/scope_creep_variance_exact_threshold_boundary
    """
    ctx = _scoped_turn_with_budget(100000)
    # 10010 over 100000 == 1001bp variance: above the 1000bp PM threshold.
    item = add_scope_item(ctx["turn"]["id"], "CLEAN", 10010, "one tick over")
    assert item["status"] == "PENDING_APPROVAL"
    assert item["approval_tier"] == "PM"
    turn = get_turn(ctx["turn"]["id"])
    assert turn["estimated_cost_cents"] == 100000, (
        "pending items are invisible to the estimate until approved"
    )


# --- rm-threshold boundary + authority (Corner: rm_tier_boundary_and_authority_enforcement)

def test_rm_tier_boundary_and_authority_enforcement(api):
    """PRD §3.5: "A variance above `pm_threshold_bp` but at or below
    `rm_threshold_bp` earns tier `PM`; anything above `rm_threshold_bp` earns
    tier `RM` — and note that equality at the regional threshold stays in the
    `PM` tier."
    PRD §3.5: "a `PM`-tier item may be approved or rejected by either a
    `PropertyManager` or a `RegionalManager`, but an `RM`-tier item admits only
    a `RegionalManager`, and a `PropertyManager` attempting one is rejected
    with `ERR_APPROVAL_AUTHORITY_EXCEEDED`."
    PRD §3.5: "Approval moves the item `PENDING_APPROVAL` → `PLANNED`, adds
    the item's `estimated_cost_cents` to the turn's `approved_budget_cents` —
    the budget legitimately grows to absorb sanctioned creep — increments the
    turn's `version` by one, and recomputes the estimate and projection with
    commitment risk re-evaluated."

    Design: Corner/calculations/rm_tier_boundary_and_authority_enforcement
    """
    ctx = _scoped_turn_with_budget(100000)
    turn_id = ctx["turn"]["id"]
    at_boundary = add_scope_item(turn_id, "PAINT", 30000, "at rm boundary")
    over_boundary = add_scope_item(turn_id, "OTHER", 30010, "over rm boundary")
    assert at_boundary["approval_tier"] == "PM", (
        "variance exactly 3000bp satisfies <= rm and stays PM"
    )
    assert at_boundary["status"] == "PENDING_APPROVAL"
    assert over_boundary["approval_tier"] == "RM", "variance 3001bp exceeds rm"
    assert over_boundary["status"] == "PENDING_APPROVAL"

    version = get_turn(turn_id)["version"]
    denied = api.approve_scope_item(
        over_boundary["id"], {"expected_turn_version": version}, PM)
    validate_error(denied, ApiErrorId.ERR_APPROVAL_AUTHORITY_EXCEEDED, 403)
    assert get_turn(turn_id)["version"] == version, (
        "a rejected approval must not advance the turn version"
    )

    approved = validate_success(api.approve_scope_item(
        over_boundary["id"], {"expected_turn_version": version}, RM))
    assert approved["status"] == "PLANNED"
    assert get_turn(turn_id)["approved_budget_cents"] == 130010


# --- budget reconciliation (Corner: approved_budget_reconciles_on_approval)

def test_approved_budget_reconciles_immediately_on_approval(api):
    """PRD §3.5: "Approval moves the item `PENDING_APPROVAL` → `PLANNED`, adds
    the item's `estimated_cost_cents` to the turn's `approved_budget_cents` —
    the budget legitimately grows to absorb sanctioned creep — increments the
    turn's `version` by one, and recomputes the estimate and projection with
    commitment risk re-evaluated."
    PRD §2.11: "Computed fields are never accepted from clients; they are
    maintained by the server and reconciled immediately as events occur."

    Design: Corner/cross_cutting_layers/approved_budget_reconciles_on_approval
    """
    ctx = _scoped_turn_with_budget(100000)
    turn_id = ctx["turn"]["id"]
    item = add_scope_item(turn_id, "PAINT", 15000, "A")  # 1500bp -> PM tier
    assert item["status"] == "PENDING_APPROVAL"
    version = get_turn(turn_id)["version"]

    validate_success(api.approve_scope_item(
        item["id"], {"expected_turn_version": version}, PM))
    turn = get_turn(turn_id)
    assert turn["approved_budget_cents"] == 115000, "100000 + 15000"
    assert turn["estimated_cost_cents"] == 115000, "item now PLANNED, counted"
    assert turn["version"] == version + 1


# --- OCC stale version (Corner: occ_stale_version_rejected)

def test_stale_turn_version_rejected_on_second_approval(api):
    """PRD §2.9: "The request must carry `expected_turn_version`, holding the
    `version` of the owning turn as the client last observed it. If the value
    does not match the turn's current `version` — because another writer has
    advanced the turn since the client last read it, for instance by approving
    a different pending item and thereby raising `approved_budget_cents` and
    re-tiering future scope adds — the approval is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from amending a
    budget baseline it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_version_rejected
    """
    ctx = _scoped_turn_with_budget(100000)
    turn_id = ctx["turn"]["id"]
    item_a = add_scope_item(turn_id, "PAINT", 15000, "A")   # 1500bp -> PM
    item_b = add_scope_item(turn_id, "CLEAN", 12000, "B")   # 1200bp -> PM
    assert item_a["approval_tier"] == "PM"
    assert item_b["approval_tier"] == "PM"
    observed_version = get_turn(turn_id)["version"]

    approved = validate_success(api.approve_scope_item(
        item_a["id"], {"expected_turn_version": observed_version}, PM))
    assert approved["status"] == "PLANNED"
    assert get_turn(turn_id)["version"] == observed_version + 1

    stale = api.approve_scope_item(
        item_b["id"], {"expected_turn_version": observed_version}, PM)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_item(item_b["id"])["status"] == "PENDING_APPROVAL"
    assert get_turn(turn_id)["approved_budget_cents"] == 115000


# --- state beats fiscal (Difficulty: state_beats_fiscal_on_rejected_item_approval)

def _rejected_rm_tier_item(api):
    """Turn SCOPED (budget 100000) + an RM-tier item rejected by the RM."""
    ctx = _scoped_turn_with_budget(100000)
    turn_id = ctx["turn"]["id"]
    big = add_scope_item(turn_id, "OTHER", 40000, "deck rebuild")  # 4000bp -> RM
    assert big["approval_tier"] == "RM"
    validate_success(api.reject_scope_item(big["id"], RM))
    assert get_item(big["id"])["status"] == "REJECTED"
    return ctx, big


def test_approve_rejected_item_reports_invalid_state_not_authority(api):
    """PRD §2.8: "Every request is evaluated against a fixed, ordered
    validation chain, and the first failing check determines the error returned
    — later checks are never reached once an earlier one fails."
    PRD §2.8: "an approval attempt on an item that is not `PENDING_APPROVAL`
    reports `ERR_INVALID_STATE` rather than any staleness or authority
    problem."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_rejected_item_approval
    """
    ctx, big = _rejected_rm_tier_item(api)
    version = get_turn(ctx["turn"]["id"])["version"]
    # The caller is a PropertyManager and the item is RM-tier (authority
    # violation) — but the item is REJECTED, so the state check fires first.
    resp = api.approve_scope_item(
        big["id"], {"expected_turn_version": version}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_failed_approval_leaves_item_and_budget_untouched(api):
    """PRD §3.5: "Rejection moves the item `PENDING_APPROVAL` → `REJECTED`
    under the same state and authority checks; rejected items are excluded from
    the estimate and the projection, and both are re-derived accordingly."
    PRD §2.8: "an approval attempt on an item that is not `PENDING_APPROVAL`
    reports `ERR_INVALID_STATE` rather than any staleness or authority
    problem."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_rejected_item_approval
    """
    ctx, big = _rejected_rm_tier_item(api)
    turn_id = ctx["turn"]["id"]
    version = get_turn(turn_id)["version"]
    validate_error(
        api.approve_scope_item(big["id"], {"expected_turn_version": version},
                               PM),
        ApiErrorId.ERR_INVALID_STATE, 409,
    )
    assert get_item(big["id"])["status"] == "REJECTED"
    assert get_turn(turn_id)["approved_budget_cents"] == 100000
