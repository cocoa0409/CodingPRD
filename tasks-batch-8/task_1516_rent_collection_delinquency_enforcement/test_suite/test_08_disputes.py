"""Disputes: filing ownership, resolution gates, the reopen loop cap, the
upheld -> reopened -> adjusted cycle, and the Cascade C auto-recall."""
from test_helpers import (
    ApiErrorId,
    add_charge,
    create_lease,
    file_dispute,
    get_ledger,
    list_charges,
    list_referrals,
    move_out_lease,
    reopen_dispute,
    resolve_dispute,
    set_clock,
    setup_ended_lease_with_referral,
    setup_property_tenant_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_tenant_headers

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def test_dispute_charge_on_wrong_lease_rejected(api):
    """PRD 3.9: "The payload names the `lease_id`, the disputed `charge_id` — which
    must belong to that lease, else `ERR_CHARGE_NOT_ON_LEASE` — and a free-text
    `reason`."

    Design: Corner/validations/dispute_charge_on_wrong_lease_rejected
    """
    ctx = setup_property_tenant_lease()
    lease1 = ctx["lease"]
    lease2 = create_lease(ctx["property"]["id"], ctx["tenant"]["id"], unit_label="102", activate=True)
    foreign = add_charge(lease2["id"], kind="DAMAGE_FEE", amount_cents=30000)

    from test_helpers import create_dispute_payload
    response = api.create_dispute(
        create_dispute_payload(lease1["id"], foreign["id"], ctx["tenant"]["id"], reason="wrong lease reference"),
        make_tenant_headers(ctx["tenant"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_ON_LEASE)


def test_dispute_resolve_twice_rejected(api):
    """PRD 3.9: "Resolving is permitted only from `OPEN` or `REOPENED`; any other
    status is rejected with `ERR_DISPUTE_INVALID_TRANSITION`."

    Design: Corner/validations/dispute_resolve_twice_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=50000)
    dispute = file_dispute(lease_id, charge["id"], ctx["tenant"]["id"])

    resolved = resolve_dispute(dispute["id"], outcome="UPHELD")
    assert resolved["status"] == "RESOLVED_UPHELD"

    response = api.transition_dispute(dispute["id"], {"action": "RESOLVE", "outcome": "UPHELD"}, PM)
    validate_error(response, ApiErrorId.ERR_DISPUTE_INVALID_TRANSITION)


def test_dispute_second_reopen_rejected(api):
    """PRD 3.9: "Reopening from any other status is rejected with
    `ERR_DISPUTE_INVALID_TRANSITION`, and the reopen may be spent only once: a second
    attempt is rejected with `ERR_DISPUTE_REOPEN_EXHAUSTED`."

    Design: Corner/state_machines/dispute_second_reopen_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=50000)
    tenant_id = ctx["tenant"]["id"]
    dispute = file_dispute(lease_id, charge["id"], tenant_id)

    resolve_dispute(dispute["id"], outcome="UPHELD")
    reopen_dispute(dispute["id"], tenant_id)
    resolved_again = resolve_dispute(dispute["id"], outcome="UPHELD")
    assert resolved_again["status"] == "RESOLVED_UPHELD"

    response = api.transition_dispute(dispute["id"], {"action": "REOPEN"}, make_tenant_headers(tenant_id))
    validate_error(response, ApiErrorId.ERR_DISPUTE_REOPEN_EXHAUSTED)


def test_dispute_upheld_reopened_adjusted_cycle(api):
    """PRD 3.9: "A reopened dispute resolves again exactly as an open one — `UPHELD`
    returning it to `RESOLVED_UPHELD`, `ADJUSTED` firing the same cascade — and with
    the reopen exhausted, the cycle `OPEN` → `RESOLVED_UPHELD` → `REOPENED` →
    `RESOLVED_*` terminates; `RESOLVED_UPHELD` is then effectively final, and
    `RESOLVED_ADJUSTED` is always terminal."
    PRD 3.9: "An adjustment fires Cascade C: the charge's `amount_cents` is replaced
    by the adjusted figure — an adjustment to zero sends the charge to `VOID`, whether
    it stood at `OPEN` or `PARTIALLY_PAID`, and in the latter case the existing
    applications remain on the books as historical record — its `outstanding_cents` is
    recomputed, ..."

    Design: Difficulty/non_linear_state_machine/dispute_upheld_reopened_adjusted_cycle
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=50000)
    tenant_id = ctx["tenant"]["id"]
    dispute = file_dispute(lease_id, charge["id"], tenant_id, reason="not my damage")

    s1 = resolve_dispute(dispute["id"], outcome="UPHELD")
    assert s1["status"] == "RESOLVED_UPHELD"

    s2 = reopen_dispute(dispute["id"], tenant_id)
    assert s2["status"] == "REOPENED"
    assert s2["reopen_count"] == 1

    s3 = resolve_dispute(dispute["id"], outcome="ADJUSTED", adjusted_amount_cents=30000, resolution_notes="split the difference")
    assert s3["status"] == "RESOLVED_ADJUSTED"

    reread = [c for c in list_charges(lease_id) if c["id"] == charge["id"]][0]
    assert reread["amount_cents"] == 30000
    assert reread["outstanding_cents"] == 30000

    # The loop cap terminates the cycle: a further REOPEN is rejected.
    response = api.transition_dispute(dispute["id"], {"action": "REOPEN"}, make_tenant_headers(tenant_id))
    validate_error(response, ApiErrorId.ERR_DISPUTE_INVALID_TRANSITION)


def test_dispute_adjust_cascade_depth3(api):
    """PRD 3.9: "An adjustment fires Cascade C: the charge's `amount_cents` is
    replaced by the adjusted figure — an adjustment to zero sends the charge to `VOID`,
    whether it stood at `OPEN` or `PARTIALLY_PAID`, and in the latter case the existing
    applications remain on the books as historical record — its `outstanding_cents` is
    recomputed, every `DRAFT` notice covering the charge recomputes its demanded
    amount, and any `PENDING` collections referral on the lease recomputes its referred
    balance, automatically recalling itself to `RECALLED` with the system-set
    `recall_reason` `BALANCE_RESOLVED` when that balance has fallen below the
    property's `collections_threshold_cents`."

    Design: Difficulty/transitive_cascade/dispute_adjust_cascade_depth3
    """
    ctx = setup_ended_lease_with_referral(charge_amount_cents=15000)
    lease_id = ctx["lease"]["id"]
    referral = ctx["referrals"][0]
    assert referral["referred_balance_cents"] == 15000

    dispute = file_dispute(lease_id, ctx["charge"]["id"], ctx["tenant"]["id"], reason="pre-existing damage")
    resolve_dispute(dispute["id"], outcome="ADJUSTED", adjusted_amount_cents=5000)

    reread = [c for c in list_charges(lease_id) if c["id"] == ctx["charge"]["id"]][0]
    assert reread["amount_cents"] == 5000
    assert reread["outstanding_cents"] == 5000

    referrals = list_referrals(lease_id)
    assert referrals[0]["referred_balance_cents"] == 5000
    assert referrals[0]["status"] == "RECALLED"
    assert referrals[0]["recall_reason"] == "BALANCE_RESOLVED"


def test_dispute_cycle_reopen_count_caps_loop(api):
    """PRD 3.9: "The filing `Tenant` — and only that tenant, by ownership — may reopen
    a `RESOLVED_UPHELD` dispute, moving it to `REOPENED` with its `reopen_count`
    incremented by one. Reopening from any other status is rejected with
    `ERR_DISPUTE_INVALID_TRANSITION`, and the reopen may be spent only once: a second
    attempt is rejected with `ERR_DISPUTE_REOPEN_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/dispute_upheld_reopened_adjusted_cycle
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=50000)
    tenant_id = ctx["tenant"]["id"]
    dispute = file_dispute(lease_id, charge["id"], tenant_id)
    assert dispute["status"] == "OPEN"
    assert dispute["reopen_count"] == 0

    resolve_dispute(dispute["id"], outcome="UPHELD")
    reopened = reopen_dispute(dispute["id"], tenant_id)
    assert reopened["reopen_count"] == 1

    # RESOLVED_ADJUSTED is terminal: REOPEN from it is an invalid transition, not
    # merely an exhausted reopen.
    resolve_dispute(dispute["id"], outcome="ADJUSTED", adjusted_amount_cents=30000)
    response = api.transition_dispute(dispute["id"], {"action": "REOPEN"}, make_tenant_headers(tenant_id))
    validate_error(response, ApiErrorId.ERR_DISPUTE_INVALID_TRANSITION)


def test_dispute_adjust_cascade_recomputes_referral_balance(api):
    """PRD 3.9: "An adjustment fires Cascade C: the charge's `amount_cents` is
    replaced by the adjusted figure — an adjustment to zero sends the charge to `VOID`,
    whether it stood at `OPEN` or `PARTIALLY_PAID`, and in the latter case the existing
    applications remain on the books as historical record — its `outstanding_cents` is
    recomputed, every `DRAFT` notice covering the charge recomputes its demanded
    amount, and any `PENDING` collections referral on the lease recomputes its referred
    balance, automatically recalling itself to `RECALLED` with the system-set
    `recall_reason` `BALANCE_RESOLVED` when that balance has fallen below the
    property's `collections_threshold_cents`."

    Design: Difficulty/transitive_cascade/dispute_adjust_cascade_depth3
    """
    ctx = setup_ended_lease_with_referral(charge_amount_cents=15000)
    lease_id = ctx["lease"]["id"]

    # A partial adjustment that keeps the balance at the threshold does NOT recall.
    dispute = file_dispute(lease_id, ctx["charge"]["id"], ctx["tenant"]["id"], reason="partial correction")
    resolve_dispute(dispute["id"], outcome="ADJUSTED", adjusted_amount_cents=10000)

    referrals = list_referrals(lease_id)
    assert referrals[0]["referred_balance_cents"] == 10000, (
        "The PENDING referral's balance recomputes to the adjusted outstanding"
    )
    assert referrals[0]["status"] == "PENDING", (
        "At exactly the 10000 threshold the referral is not auto-recalled (the recall fires only below the threshold)"
    )
