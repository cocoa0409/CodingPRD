"""Finalize cascades: escrow credit -> FULL flip -> lease flag latch, escrow cap
truncation, escrow conservation through disbursement, default cascade stripping
the guarantee, and the default threshold / cure floor."""
from test_helpers import (
    validate_success, validate_error, api_client,
    ApiErrorId, TEST_USERS,
    create_active_lease, set_clock, create_and_issue_settlement,
    finalize_healthy_week, finalize_short_week,
    setup_lease_with_missed_payments, setup_defaulted_lease,
    offer_and_accept_lane,
    assert_escrow_conservation,
)

ADMIN = TEST_USERS["lease_admin_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


# ─── Queue A: difficulty/transitive_cascade (finalize chain) ──

def _scenario_two_weeks_finalized_cap_50000():
    """ACTIVE lease (escrow 20000/wk, cap 50000) with W1 and W2 finalized
    healthy: balance 40000, still ACCUMULATING. Clock left at W2 close."""
    scenario = create_active_lease(escrow_cap_cents=50000)
    lease_id = scenario["lease"]["id"]
    finalize_healthy_week(lease_id, "2026-08-03", "2026-08-12T00:00:00Z")
    finalize_healthy_week(lease_id, "2026-08-10", "2026-08-19T00:00:00Z")
    return scenario


def test_finalize_escrow_full_flip_and_balance(api):
    """PRD section 3.4: "Link one: the escrow account is credited by the
    settlement's `escrow_contribution_cents` — `balance_cents` and
    `total_credited_cents` each increase by that amount. Link two: if the credit
    brings `balance_cents` to or above the lease's `escrow_cap_cents` — equality
    counts — the escrow account flips `ACCUMULATING` → `FULL`."

    Design: Difficulty/transitive_cascade/finalize_escrow_full_cascade_sets_lease_flag
    """
    scenario = _scenario_two_weeks_finalized_cap_50000()
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-26T00:00:00Z")
    st3 = create_and_issue_settlement(lease_id, "2026-08-17")

    finalized = validate_success(api.finalize_settlement(st3["id"], CLERK), 200)
    assert finalized["escrow_contribution_cents"] == 10000, (
        "min(20000, cap room 10000, funds): truncated at the cap")

    escrow = validate_success(
        api.get_escrow_account(scenario["escrow"]["id"], ADMIN), 200)
    assert escrow["balance_cents"] == 50000
    assert escrow["total_credited_cents"] == 50000
    assert escrow["status"] == "FULL", "balance reached the cap: equality counts"


def test_finalize_escrow_full_sets_lease_escrow_satisfied(api):
    """PRD section 3.4: "Link three: that flip sets the lease's
    `escrow_satisfied` flag true, a latch that is never reset."

    Design: Difficulty/transitive_cascade/finalize_escrow_full_cascade_sets_lease_flag
    """
    scenario = _scenario_two_weeks_finalized_cap_50000()
    lease_id = scenario["lease"]["id"]
    assert scenario["lease"]["escrow_satisfied"] is False
    set_clock("2026-08-26T00:00:00Z")
    st3 = create_and_issue_settlement(lease_id, "2026-08-17")
    validate_success(api.finalize_settlement(st3["id"], CLERK), 200)

    lease = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert lease["escrow_satisfied"] is True, "cascade link 3 fired from the FULL flip"
    assert lease["missed_payment_count"] == 0, "healthy settlements never fall short"


# ─── Queue A: difficulty/boundary_precision_check (escrow cap) ──

def _scenario_cap_40001_through_w4_issued():
    """ACTIVE lease (escrow 20000/wk, cap 40001): W1..W3 finalized healthy
    (balance 40001 after W3's one-cent truncated credit), W4 issued."""
    scenario = create_active_lease(escrow_cap_cents=40001)
    lease_id = scenario["lease"]["id"]
    finalize_healthy_week(lease_id, "2026-08-03", "2026-08-12T00:00:00Z")
    finalize_healthy_week(lease_id, "2026-08-10", "2026-08-19T00:00:00Z")
    set_clock("2026-08-26T00:00:00Z")
    st3 = create_and_issue_settlement(lease_id, "2026-08-17")
    set_clock("2026-09-02T00:00:00Z")
    st4 = create_and_issue_settlement(lease_id, "2026-08-24")
    return scenario, st3, st4


def test_escrow_cap_exact_cent_reach(api):
    """PRD section 3.4: "step four takes the escrow contribution as the smallest
    of the scheduled `escrow_weekly_contribution_cents`, the remaining room under
    the lease's `escrow_cap_cents` (the cap minus the escrow account's current
    balance, floored at zero), and the funds remaining after step three". PRD
    section 3.4: "Link two: if the credit brings `balance_cents` to or above the
    lease's `escrow_cap_cents` — equality counts — the escrow account flips
    `ACCUMULATING` → `FULL`."

    Design: Difficulty/boundary_precision_check/escrow_cap_exact_cent_reach
    """
    scenario, st3, _ = _scenario_cap_40001_through_w4_issued()
    finalized3 = validate_success(api.finalize_settlement(st3["id"], CLERK), 200)
    assert finalized3["escrow_contribution_cents"] == 1, (
        "min(20000, cap room 1, funds): truncated to the exact remaining cent")

    escrow = validate_success(
        api.get_escrow_account(scenario["escrow"]["id"], ADMIN), 200)
    assert escrow["balance_cents"] == 40001, "balance lands exactly on the cap"
    assert escrow["status"] == "FULL", ">= semantics: equality triggers FULL"


def test_escrow_credit_zero_once_cap_reached(api):
    """PRD section 3.4: "step four takes the escrow contribution as the smallest
    of the scheduled `escrow_weekly_contribution_cents`, the remaining room under
    the lease's `escrow_cap_cents` (the cap minus the escrow account's current
    balance, floored at zero), and the funds remaining after step three — this
    becomes `escrow_contribution_cents`".

    Design: Difficulty/boundary_precision_check/escrow_cap_exact_cent_reach
    """
    scenario, st3, st4 = _scenario_cap_40001_through_w4_issued()
    validate_success(api.finalize_settlement(st3["id"], CLERK), 200)

    finalized4 = validate_success(api.finalize_settlement(st4["id"], CLERK), 200)
    assert finalized4["escrow_contribution_cents"] == 0, "cap room is 0 after FULL"

    escrow = validate_success(
        api.get_escrow_account(scenario["escrow"]["id"], ADMIN), 200)
    assert escrow["balance_cents"] == 40001
    assert escrow["total_credited_cents"] == 40001


# ─── Queue A: difficulty/compensating_invariant (escrow) ──

def _scenario_full_escrow_then_completed_lease():
    """ACTIVE lease (cap 50000) with W1..W3 finalized healthy (credits
    20000+20000+10000 = 50000, balance 50000, FULL); clock past term end and
    the lease completed (escrow -> REFUND_PENDING)."""
    scenario = _scenario_two_weeks_finalized_cap_50000()
    lease_id = scenario["lease"]["id"]
    finalize_healthy_week(lease_id, "2026-08-17", "2026-08-26T00:00:00Z")
    set_clock("2027-08-03T00:00:00Z")
    validate_success(api_client.complete_lease(lease_id, ADMIN), 200)
    return scenario


def test_escrow_disburse_refunds_full_balance(api):
    """PRD section 3.7: "A `SettlementClerk` then disburses a `REFUND_PENDING`
    escrow: the full `balance_cents` is added to `total_refunded_cents`, the
    balance zeroes, and the account moves to `REFUNDED`".

    Design: Difficulty/compensating_invariant/escrow_credit_refund_conservation
    """
    scenario = _scenario_full_escrow_then_completed_lease()
    escrow_id = scenario["escrow"]["id"]
    pre = validate_success(api.get_escrow_account(escrow_id, ADMIN), 200)
    assert pre["status"] == "REFUND_PENDING"
    assert pre["balance_cents"] == 50000

    disbursed = validate_success(api.disburse_escrow(escrow_id, CLERK), 200)
    assert disbursed["status"] == "REFUNDED"
    assert disbursed["balance_cents"] == 0
    assert disbursed["total_refunded_cents"] == 50000
    assert disbursed["total_applied_cents"] == 0


def test_escrow_credit_refund_conservation(api):
    """PRD section 3.7: "A `SettlementClerk` then disburses a `REFUND_PENDING`
    escrow: the full `balance_cents` is added to `total_refunded_cents`, the
    balance zeroes, and the account moves to `REFUNDED`". PRD section 3.4: "Link
    one: the escrow account is credited by the settlement's
    `escrow_contribution_cents` — `balance_cents` and `total_credited_cents` each
    increase by that amount."

    Design: Difficulty/compensating_invariant/escrow_credit_refund_conservation
    """
    scenario = _scenario_full_escrow_then_completed_lease()
    escrow_id = scenario["escrow"]["id"]
    validate_success(api.disburse_escrow(escrow_id, CLERK), 200)

    escrow = validate_success(api.get_escrow_account(escrow_id, ADMIN), 200)
    assert escrow["total_credited_cents"] == 50000, "20000 + 20000 + 10000 at the cap"
    # 50000 == 0 + 50000 + 0: credits conserved across credit + refund
    assert_escrow_conservation(escrow)


# ─── Queue A: difficulty/transitive_cascade (declare-default chain) ──

def _scenario_defaultable_with_issued_w4():
    """ACTIVE lease with lane ACCEPTED covering W1..W4, three all-zero short
    finalizations (missed_payment_count 3), and a W4 settlement ISSUED with
    gross 100000 (provisional top-up 50000, net 65000)."""
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    lane = offer_and_accept_lane(lease_id, scenario["operator"]["id"])
    finalize_short_week(lease_id, "2026-08-03", "2026-08-12T00:00:00Z")
    finalize_short_week(lease_id, "2026-08-10", "2026-08-19T00:00:00Z")
    finalize_short_week(lease_id, "2026-08-17", "2026-08-26T00:00:00Z")
    set_clock("2026-08-31T00:00:00Z")
    st4 = create_and_issue_settlement(
        lease_id, "2026-08-24",
        gross_revenue_cents=100000, fuel_gallons=0, insurance_weekly_cents=0,
        miles_driven=0, load_declined_flag=False)
    scenario["lane"] = lane
    scenario["st4"] = st4
    return scenario


def test_declare_default_revokes_accepted_lane(api):
    """PRD section 3.5: "because default strips guarantee eligibility, declaring
    default on a lease not only revokes its `ACCEPTED` lanes (link one of the
    default cascade) but also recomputes every non-final settlement of that lease
    (link two, caused by link one) with `guarantee_top_up_cents` forced to zero
    and the waterfall and `net_pay_cents` recomputed accordingly."

    Design: Difficulty/transitive_cascade/declare_default_revokes_lane_strips_guarantee
    """
    scenario = _scenario_defaultable_with_issued_w4()
    assert scenario["st4"]["guarantee_top_up_cents"] == 50000, "guarantee active pre-default"
    assert scenario["st4"]["net_pay_cents"] == 65000

    defaulted = validate_success(api.declare_default(scenario["lease"]["id"], ADMIN), 200)
    assert defaulted["status"] == "DEFAULTED"

    lane = validate_success(api.get_lane_assignment(scenario["lane"]["id"], ADMIN), 200)
    assert lane["status"] == "REVOKED", "cascade link 1: ACCEPTED lane revoked"


def test_declare_default_strips_guarantee_from_open_settlement(api):
    """PRD section 3.5: "declaring default on a lease not only revokes its
    `ACCEPTED` lanes (link one of the default cascade) but also recomputes every
    non-final settlement of that lease (link two, caused by link one) with
    `guarantee_top_up_cents` forced to zero and the waterfall and `net_pay_cents`
    recomputed accordingly."

    Design: Difficulty/transitive_cascade/declare_default_revokes_lane_strips_guarantee
    """
    scenario = _scenario_defaultable_with_issued_w4()
    validate_success(api.declare_default(scenario["lease"]["id"], ADMIN), 200)

    st4 = validate_success(api.get_settlement(scenario["st4"]["id"], CLERK), 200)
    assert st4["guarantee_top_up_cents"] == 0, "cascade link 2: guarantee stripped"
    # 100000 - 0 - 0 - 0 - 20000 escrow - 65000 lease
    assert st4["net_pay_cents"] == 15000
    assert st4["status"] == "ISSUED", "recompute does not change lifecycle state"


# ─── Queue B: corner/calculations + corner/validations ──

def test_default_threshold_two_vs_three(api):
    """PRD section 3.7: "a `LeaseAdmin` declares default on an `ACTIVE` lease
    (wrong state: `ERR_LEASE_NOT_ACTIVE`) whose `missed_payment_count` has
    reached at least three (otherwise `ERR_LEASE_NOT_DEFAULT_ELIGIBLE`), moving
    `ACTIVE` → `DEFAULTED`."

    Design: Corner/calculations/default_threshold_two_vs_three
    """
    scenario = setup_lease_with_missed_payments(2)
    lease_id = scenario["lease"]["id"]
    assert scenario["lease"]["missed_payment_count"] == 2

    res = api.declare_default(lease_id, ADMIN)
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_DEFAULT_ELIGIBLE.value)

    finalize_short_week(lease_id, "2026-08-17", "2026-08-26T00:00:00Z")
    lease = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert lease["missed_payment_count"] == 3
    assert lease["arrears_cents"] == 195000

    defaulted = validate_success(api.declare_default(lease_id, ADMIN), 200)
    assert defaulted["status"] == "DEFAULTED", ">= semantics: three missed payments suffice"


def test_cure_underpayment_returns_422(api):
    """PRD section 3.7: "A `LeaseAdmin` cures a `DEFAULTED` lease (wrong state:
    `ERR_LEASE_NOT_DEFAULTED`) by submitting an `arrears_payment_cents` amount; a
    payment smaller than the current `arrears_cents` is rejected with
    `ERR_ARREARS_NOT_CLEARED` (HTTP 422). On success the lease returns
    `DEFAULTED` → `ACTIVE`, `arrears_cents` and `missed_payment_count` reset to
    zero".

    Design: Corner/validations/cure_underpayment_returns_422
    """
    scenario = setup_defaulted_lease()
    lease_id = scenario["lease"]["id"]
    assert scenario["lease"]["arrears_cents"] == 195000

    res = api.cure_default(lease_id, {"arrears_payment_cents": 100000}, ADMIN)
    validate_error(res, ApiErrorId.ERR_ARREARS_NOT_CLEARED.value)

    after_fail = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert after_fail["status"] == "DEFAULTED"
    assert after_fail["arrears_cents"] == 195000, "rejected cure changes nothing"

    cured = validate_success(
        api.cure_default(lease_id, {"arrears_payment_cents": 195000}, ADMIN), 200)
    assert cured["status"] == "ACTIVE"
    assert cured["arrears_cents"] == 0
