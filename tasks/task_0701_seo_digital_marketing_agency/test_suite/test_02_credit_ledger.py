"""Retainer credit pool: conservation invariant, cycle rollover, and OCC.

Covers queue A compensating_invariant (credit pool) instances and the queue B
calculations / cross_cutting / consistency corner instances on the credit pool.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
    assert_credit_ledger_reconciles,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_credit_pool_conserved_across_assign_then_reject(api):
    """PRD §2.9: "`credits_available` is exactly `credits_granted` minus
    `credits_committed` minus `credits_consumed`."
    PRD §3.6: "On success, assignment moves the deliverable to `ASSIGNED`, adds the
    `credit_cost` to the retainer's `credits_committed` and recomputes
    `credits_available`".
    PRD §3.6: "An account manager may reject a deliverable from `ASSIGNED`,
    `IN_PROGRESS`, or `IN_REVIEW`, moving it to the terminal `REJECTED`: this
    subtracts the `credit_cost` from the retainer's `credits_committed` and recomputes
    `credits_available`".

    Granted 20, assign a CONTENT/STANDARD deliverable (cost 3) -> committed 3,
    available 17; reject -> available restored to 20 (no drift).

    Design: Difficulty/compensating_invariant/credit_pool_conserved_across_assign_then_reject
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable, retainer_after_assign = fixtures.create_assigned_deliverable(
        client["id"], retainer["id"], sprint["id"],
        deliverable_overrides={"kind": "CONTENT", "complexity": "STANDARD"},
    )
    assert retainer_after_assign["credits_committed"] == 3
    assert retainer_after_assign["credits_available"] == 17
    assert_credit_ledger_reconciles(retainer_after_assign)

    validate_success(api.reject_deliverable(deliverable["id"], AM))
    retainer_after_reject = validate_success(api.get_retainer(retainer["id"], ADMIN))
    assert retainer_after_reject["credits_available"] == 20, (
        f"reject must restore credits_available to 20, "
        f"got {retainer_after_reject['credits_available']}"
    )
    assert retainer_after_reject["credits_committed"] == 0
    assert_credit_ledger_reconciles(retainer_after_reject)


def test_sprint_committed_credits_conserved_across_assign_then_reject(api):
    """PRD §3.6: "On success, assignment moves the deliverable to `ASSIGNED`, adds the
    `credit_cost` to the retainer's `credits_committed` and recomputes
    `credits_available`, adds the same amount to the sprint's `committed_credits`, and
    increments the deliverable's `version` (and the retainer's `version`, per the
    reservation against it)."
    PRD §3.6: "An account manager may reject a deliverable from `ASSIGNED`,
    `IN_PROGRESS`, or `IN_REVIEW`, moving it to the terminal `REJECTED`: this subtracts
    the `credit_cost` from the retainer's `credits_committed` and recomputes
    `credits_available`, subtracts it from the sprint's `committed_credits`, and
    increments the deliverable's `version`."

    The sprint's committed_credits rises by credit_cost on assign and falls back to 0
    on reject, mirroring the retainer ledger compensation.

    Design: Difficulty/compensating_invariant/credit_pool_conserved_across_assign_then_reject
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
        sprint_overrides={"capacity_credits": 20},
    )
    deliverable, _ = fixtures.create_assigned_deliverable(
        client["id"], retainer["id"], sprint["id"],
        deliverable_overrides={"kind": "CONTENT", "complexity": "STANDARD"},
    )
    sprint_after_assign = validate_success(api.get_sprint(sprint["id"], ADMIN))
    assert sprint_after_assign["committed_credits"] == 3

    validate_success(api.reject_deliverable(deliverable["id"], AM))
    sprint_after_reject = validate_success(api.get_sprint(sprint["id"], ADMIN))
    assert sprint_after_reject["committed_credits"] == 0, (
        f"reject must release sprint committed_credits back to 0, "
        f"got {sprint_after_reject['committed_credits']}"
    )


def test_credit_pool_reconciles_on_immediate_get_after_assign(api):
    """PRD §2.9: "`credits_available` is exactly `credits_granted` minus
    `credits_committed` minus `credits_consumed`."
    PRD §3.4: "Reading a single retainer recomputes and returns its `credits_available`
    from the live ledger."
    PRD §3.6: "On success, assignment moves the deliverable to `ASSIGNED`, adds the
    `credit_cost` to the retainer's `credits_committed` and recomputes
    `credits_available`".

    Assign response shows ASSIGNED, and an immediate GET on the retainer shows
    credits_committed 3 / credits_available 17 with no lag.

    Design: Corner/consistency_model/assign_visible_in_same_response_immediate
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable = fixtures.create_draft_deliverable(
        client["id"], retainer["id"], sprint["id"],
        kind="CONTENT", complexity="STANDARD",
    )
    fresh_retainer = validate_success(api.get_retainer(retainer["id"], ADMIN))
    assign_resp = validate_success(
        api.assign_deliverable(
            deliverable["id"],
            {"expected_retainer_version": fresh_retainer["version"]},
            AM,
        )
    )
    assert assign_resp["status"] == "ASSIGNED"

    retainer_now = validate_success(api.get_retainer(retainer["id"], ADMIN))
    assert retainer_now["credits_committed"] == 3
    assert retainer_now["credits_available"] == 17


def test_cycle_rollover_capped_carry_forward(api):
    """PRD §3.4: "then compute the cap as `monthly_credits` multiplied by
    `rollover_cap_pct`, taking the floor to whole credits; then the rolled amount is
    the smaller of the leftover and that cap, which guarantees no cycle ever carries
    more than was actually unused. With the rolled amount in hand, set
    `credits_granted` to `monthly_credits` plus the rolled amount, reset both
    `credits_committed` and `credits_consumed` to 0 for the new cycle, recompute
    `credits_available`, advance `cycle_index` by one".

    monthly_credits 20, rollover_cap_pct 0.25 -> cap floor(5)=5, leftover 20 ->
    rolled min(20,5)=5; credits_granted 25, available 25, cycle_index 1.

    Design: Corner/calculations/retainer_cycle_rollover_capped
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    rolled = validate_success(
        api.rollover_retainer(
            retainer["id"], {"expected_retainer_version": retainer["version"]}, AM
        )
    )
    assert rolled["credits_granted"] == 25, (
        f"granted should be 20 + capped rollover 5 = 25, got {rolled['credits_granted']}"
    )
    assert rolled["credits_available"] == 25
    assert rolled["cycle_index"] == 1
    assert_credit_ledger_reconciles(rolled)


def test_retainer_version_increments_on_each_mutation(api):
    """PRD §2.4: "an integer `version` that begins at its creation value and
    increments by one on every mutation — including mutations to computed and derived
    fields."
    PRD §3.4: "Activation grants the cycle-zero allotment — `credits_granted` is set
    to `monthly_credits`, since cycle zero has no rollover — recomputes
    `credits_available`, computes `billing_price_cents`, promotes the client from
    `AUDITED` to `ACTIVE` if it was `AUDITED`, and increments the retainer's `version`."
    PRD §3.4: "Suspending an `ACTIVE` retainer moves it to `SUSPENDED` (by
    account-manager action or as the client-pause cascade) and increments its
    `version`".

    create -> version 1, activate -> 2, suspend -> 3.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_retainer_mutation
    """
    client, retainer = fixtures.create_audited_client_with_draft_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    assert retainer["version"] == 1, f"create version should be 1, got {retainer['version']}"
    activated = validate_success(api.activate_retainer(retainer["id"], ADMIN))
    assert activated["version"] == 2, f"activate version should be 2, got {activated['version']}"
    suspended = validate_success(api.suspend_retainer(retainer["id"], AM))
    assert suspended["version"] == 3, f"suspend version should be 3, got {suspended['version']}"


def test_second_rollover_with_stale_version_rejected(api):
    """PRD §2.8: "Advancing a retainer's billing cycle requires the request to carry
    `expected_retainer_version` equal to the retainer's current `version`; if another
    writer has advanced that version since the client last read the retainer, the
    rollover is rejected with `ERR_STALE_RETAINER_VERSION` at HTTP 412, which prevents
    a second rollover from doubling a carry-forward against a cycle that no longer
    exists."

    First rollover succeeds and bumps the version; a second rollover replaying the
    pre-first-rollover version is stale -> ERR_STALE_RETAINER_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/rollover_stale_version_rejected
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    v_after_activate = retainer["version"]
    validate_success(
        api.rollover_retainer(
            retainer["id"], {"expected_retainer_version": v_after_activate}, AM
        )
    )
    resp = api.rollover_retainer(
        retainer["id"], {"expected_retainer_version": v_after_activate}, AM
    )
    validate_error(resp, ApiErrorId.ERR_STALE_RETAINER_VERSION.value)
