"""Membership lifecycle: activation grant, renewal rollover order, cancellation forfeit and
refund valuation, credit-ledger reconciliation, and OCC on renewal."""
from test_helpers import (
    validate_success, validate_error,
    setup_membership_for_refund, setup_active_membership_for_rollover,
    setup_active_membership_simple, setup_renewed_membership,
    create_plan, create_member, create_active_membership,
    get_ledger_for_membership, get_all_payments,
    set_clock, api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


# ─── Rollover order (comb_b) ──────────────────────────────────────────────
def test_renewal_rollover_expires_overflow_then_grants(api):
    """PRD §3.3: "If that overflow is positive, an `EXPIRE` ledger entry is appended first,
    with a `delta` equal to the negative of the overflow, so that the balance lands exactly
    on `rollover_cap`. Then a `GRANT` ledger entry is appended for the plan's
    `included_floats_per_cycle` floats."

    Design: Difficulty/combinatorial_formula/comb_b_rollover_order_pinned
    """
    # included 10, cap 6, pre_balance 10: overflow 4 -> EXPIRE -4 (balance 6) -> GRANT +10 (16).
    ctx = setup_active_membership_for_rollover(included=10, rollover_cap=6)
    ship = ctx["membership"]
    renewed = validate_success(
        api.renew_membership(ship["id"], {"expected_membership_version": ship["version"]},
                             FRONTDESK), 200)
    assert renewed["credit_balance"] == 16, (
        f"expected post-renewal balance 16, got {renewed['credit_balance']}"
    )


def test_renewal_writes_expire_and_grant_ledger_entries(api):
    """PRD §3.3: "First the platform measures the overflow above the cap: the overflow is the
    pre-renewal `credit_balance` minus the plan's `rollover_cap`, floored at zero. If that
    overflow is positive, an `EXPIRE` ledger entry is appended first, with a `delta` equal to
    the negative of the overflow, so that the balance lands exactly on `rollover_cap`. Then a
    `GRANT` ledger entry is appended for the plan's `included_floats_per_cycle` floats."

    Design: Difficulty/combinatorial_formula/comb_b_rollover_order_pinned
    """
    ctx = setup_active_membership_for_rollover(included=10, rollover_cap=6)
    ship = ctx["membership"]
    validate_success(
        api.renew_membership(ship["id"], {"expected_membership_version": ship["version"]},
                             FRONTDESK), 200)
    ledger = get_ledger_for_membership(ship["id"])
    expires = [e for e in ledger if e["reason"] == "EXPIRE" and e["delta"] == -4]
    # Both the first activation and this renewal append a GRANT of included_floats_per_cycle
    # (+10); only the renewal appends an EXPIRE. So post-renewal there are two GRANT +10 rows.
    grants = [e for e in ledger if e["reason"] == "GRANT" and e["delta"] == 10]
    assert len(expires) == 1, f"expected one EXPIRE -4 entry, got {expires}"
    assert len(grants) == 2, f"expected two GRANT +10 entries (activation + renewal), got {grants}"


# ─── Refund valuation dual variant (dvc_membership) ───────────────────────
def test_cancel_emits_prorated_refund_payment(api):
    """PRD §3.7: "The authoritative valuation is a forward-looking proration of the captured
    monthly fee: take `monthly_fee_cents_snapshot`, multiply by the number of whole days
    remaining in the cycle, divide by the total cycle length of thirty days, and round to the
    nearest cent."

    Design: Difficulty/dual_variant_calc/dvc_membership_refund_prorated_vs_consumed
    """
    # monthly_fee 9000, 15 days remaining, cycle 30 -> round(9000*15/30) = 4500; refund -4500.
    ctx = setup_membership_for_refund()
    ship = ctx["membership"]
    validate_success(api.cancel_membership(ship["id"], FRONTDESK), 200)
    payments = get_all_payments()
    refunds = [p for p in payments
               if p["kind"] == "SESSION_REFUND" and p.get("booking_id") is None
               and p["amount_cents"] == -4500]
    assert len(refunds) == 1, (
        f"expected one SESSION_REFUND of -4500 with booking_id null, got {refunds}"
    )


def test_cancel_membership_forfeits_then_sets_cancelled(api):
    """PRD §3.3: "Cancellation cascades in order: if the `credit_balance` is positive, a
    `FORFEIT` ledger entry is appended first with a `delta` equal to the negative of the whole
    balance, and that insert recomputes the balance to zero".

    Design: Difficulty/dual_variant_calc/dvc_membership_refund_prorated_vs_consumed
    """
    ctx = setup_membership_for_refund()
    ship = ctx["membership"]
    cancelled = validate_success(api.cancel_membership(ship["id"], FRONTDESK), 200)
    assert cancelled["credit_balance"] == 0
    assert cancelled["status"] == "CANCELLED"


# ─── Cancel forfeit cascade (cascade_membership_cancel) ───────────────────
def test_cancel_active_membership_appends_forfeit_for_full_balance(api):
    """PRD §3.3: "if the `credit_balance` is positive, a `FORFEIT` ledger entry is appended
    first with a `delta` equal to the negative of the whole balance, and that insert
    recomputes the balance to zero".

    Design: Difficulty/transitive_cascade/cascade_membership_cancel_forfeit_balance
    """
    # SOLO included 4 -> balance 4 at activation, none consumed.
    ctx = setup_active_membership_simple(included=4)
    ship = ctx["membership"]
    assert ship["credit_balance"] == 4, "precondition: balance is 4 before cancel"
    cancelled = validate_success(api.cancel_membership(ship["id"], FRONTDESK), 200)
    ledger = get_ledger_for_membership(ship["id"])
    forfeits = [e for e in ledger if e["reason"] == "FORFEIT" and e["delta"] == -4]
    assert len(forfeits) == 1, f"expected one FORFEIT -4 entry, got {forfeits}"
    assert cancelled["credit_balance"] == 0


def test_cancel_recomputes_balance_to_zero_via_ledger(api):
    """PRD §2.9: "A membership's `credit_balance` is, at every moment, the sum of the `delta`
    values across all `CreditLedgerEntry` rows for that membership; every time a ledger row is
    inserted, the membership's balance is recomputed from the full set of its entries."

    Design: Difficulty/transitive_cascade/cascade_membership_cancel_forfeit_balance
    """
    ctx = setup_active_membership_simple(included=4)
    ship = ctx["membership"]
    validate_success(api.cancel_membership(ship["id"], FRONTDESK), 200)
    ledger = get_ledger_for_membership(ship["id"])
    refreshed = validate_success(api.get_membership(ship["id"], FRONTDESK), 200)
    assert refreshed["credit_balance"] == sum(e["delta"] for e in ledger) == 0


# ─── Credit ledger conservation (ci_credit_ledger) ────────────────────────
def test_activation_grant_balance_equals_ledger_sum(api):
    """PRD §3.3: "appends a credit-ledger grant of the plan's `included_floats_per_cycle` (a
    `GRANT` entry with a positive `delta` equal to that count and no source booking), and
    recomputes the membership's `credit_balance` from its ledger."

    Design: Difficulty/compensating_invariant/ci_credit_ledger_conservation_consume
    """
    ctx = setup_active_membership_simple(included=4)
    ship = ctx["membership"]
    ledger = get_ledger_for_membership(ship["id"])
    grants = [e for e in ledger if e["reason"] == "GRANT" and e["delta"] == 4]
    assert len(grants) == 1, f"expected one GRANT +4 at activation, got {grants}"
    assert ship["credit_balance"] == sum(e["delta"] for e in ledger) == 4


# ─── OCC stale version on renew (error_stale_version) ─────────────────────
def test_renew_with_stale_version_rejected(api):
    """PRD §2.10: "If that value does not equal the membership's current `version`, the
    renewal is rejected as stale with `ERR_STALE_VERSION` (HTTP 412) rather than
    double-applying the cycle advance."

    Design: Corner/errors/error_stale_version_on_renew
    """
    ctx = setup_renewed_membership()
    ship = ctx["membership"]
    # v_act was observed at activation; a renew already advanced version past it.
    res = api.renew_membership(ship["id"], {"expected_membership_version": ctx["v_act"]},
                               FRONTDESK)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── Version increment on renew (version_increments) ──────────────────────
def test_renew_increments_version_and_cycle_index(api):
    """PRD §3.3: "After the ledger writes, the membership recomputes its `credit_balance`,
    advances `cycle_index` by one, slides `cycle_start_utc` to the old `cycle_end_utc`, pushes
    `cycle_end_utc` forward by another thirty days, and increments its `version` by one."

    Design: Corner/endpoints/version_increments_on_membership_renew
    """
    # Activation lands version at 2 (create=1, activate mutates to 2). Renew -> 3, cycle_index 1.
    set_clock("2026-01-05T00:00:00Z")
    plan = create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                       rollover_cap=4, retail_float_cents=5000)
    member = create_member()
    ship = create_active_membership(member["id"], plan["id"])
    assert ship["version"] == 2, f"precondition: activated version is 2, got {ship['version']}"
    renewed = validate_success(
        api.renew_membership(ship["id"], {"expected_membership_version": ship["version"]},
                             FRONTDESK), 200)
    assert renewed["version"] == 3, f"expected version 3, got {renewed['version']}"
    assert renewed["cycle_index"] == 1, f"expected cycle_index 1, got {renewed['cycle_index']}"
