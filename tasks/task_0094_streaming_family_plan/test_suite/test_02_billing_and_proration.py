"""Billing, the cycle-charge proration arithmetic, and Account optimistic
concurrency (plan-change / invoice).

Translates Difficulty/dual_variant_calc + Difficulty/combinatorial_formula
(cycle-charge), and Corner/calculations + Corner/cross_cutting_complexity_layers
(OCC) instances.
"""
from test_helpers import (
    make_owner_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)
import test_helpers as h


# ---------------------------------------------------------------------------
# Cycle-charge proration: prorated-vs-flat and sum-then-round
# ---------------------------------------------------------------------------

def test_midperiod_upgrade_prorates_period_charge(api):
    """PRD §2.6: "For any plan, the exact daily rate is its monthly_fee_cents
    divided by 30, kept as an exact real number and never rounded per day. Each
    segment contributes its daily rate multiplied by the number of days in that
    segment. The period_charge_cents is the sum of all segment contributions,
    rounded once at the very end using round-half-up to whole integer cents".
    PRD §2.6: "The proration_adjustment_cents is then that rounded
    period_charge_cents minus the current plan's monthly_fee_cents".
    PRD §3.3: the plan change "re-runs the cycle-charge computation so that
    period_charge_cents and proration_adjustment_cents reflect the new
    segmentation".

    1 day @500 + 29 days @1000 = 500/30 + 29*1000/30 = 983 (round-half-up);
    adjustment = 983 - 1000 = -17.

    Design: Difficulty/dual_variant_calc/cycle_charge_prorated_vs_flat_on_account
    """
    s = h.setup_two_plans_with_midperiod_upgrade(
        period_open_iso="2026-06-01T00:00:00Z", day1_iso="2026-06-02T00:00:00Z",
        ad_fee=500, prem_fee=1000, initial_credit_cents=100000, billing_anchor_day=1,
    )
    acct = h.fetch_account(s["account"]["id"])
    assert acct["period_charge_cents"] == 983
    assert acct["proration_adjustment_cents"] == -17
    assert acct["period_charge_cents"] != 1000


def test_cycle_charge_sum_then_round_not_round_per_segment(api):
    """PRD §2.6: "The period_charge_cents is the sum of all segment contributions,
    rounded once at the very end using round-half-up to whole integer cents — the
    daily contributions are summed exactly first and rounded only at the end,
    never per day and never per segment."

    1 day @500 + 29 days @1000: sum-then-round of (16.6667 + 966.6667) = 983;
    round-per-segment-then-sum would give 17 + 967 = 984.

    Design: Difficulty/combinatorial_formula/cycle_charge_sum_then_round_mode_b
    """
    s = h.setup_two_plans_with_midperiod_upgrade(
        period_open_iso="2026-07-01T00:00:00Z", day1_iso="2026-07-02T00:00:00Z",
        ad_fee=500, prem_fee=1000, initial_credit_cents=50000, billing_anchor_day=1,
    )
    acct = h.fetch_account(s["account"]["id"])
    assert acct["period_charge_cents"] == 983


def test_single_plan_period_charge_equals_flat_fee(api):
    """PRD §2.6: "When no plan change landed in the period, there is exactly one
    segment spanning all 30 days, period_charge_cents equals the plan's
    monthly_fee_cents, and proration_adjustment_cents is 0."
    PRD §3.2 / §2.6: invoicing "debits wallet_credit_cents by the resulting net
    charge" and "The net charge actually settled at invoice equals
    period_charge_cents".

    Design: Corner/calculations/single_plan_period_charge_equals_flat_fee
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="flat@x.com", initial_credit_cents=5000)
    resp = api.invoice_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"]),
    )
    data = validate_success(resp, 200)
    assert data["period_charge_cents"] == 1000
    assert data["proration_adjustment_cents"] == 0
    assert data["wallet_credit_cents"] == 4000
    assert data["billing_status"] == "INVOICED"


# ---------------------------------------------------------------------------
# Optimistic concurrency on the Account
# ---------------------------------------------------------------------------

def test_stale_account_version_on_plan_change_rejected(api):
    """PRD §3.3: "if expected_account_version does not equal the account's current
    version, the change is rejected with ERR_STALE_ACCOUNT_VERSION and the client
    must re-read before retrying."
    PRD §2.7: "if another writer has advanced the Account's version since the
    client last read it — for instance by having already applied a plan change
    that rewrote period_charge_cents — the request is rejected with
    ERR_STALE_ACCOUNT_VERSION at HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_plan_change
    """
    plan_ad, plan_prem, account = h.setup_account_for_plan_change(initial_credit_cents=50000)
    v0 = account["version"]
    # First change advances the version.
    first = api.create_plan_change(
        account["id"], {"to_plan_id": plan_prem["id"], "expected_account_version": v0},
        make_owner_headers(account["id"]),
    )
    validate_success(first, 201)
    # Second change reuses the now-stale v0.
    resp = api.create_plan_change(
        account["id"], {"to_plan_id": plan_ad["id"], "expected_account_version": v0},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value, 412)


def test_fresh_version_on_invoice_succeeds_and_bumps_version(api):
    """PRD §3.2: invoicing "runs the cycle-charge computation to finalize
    period_charge_cents and the signed proration_adjustment_cents, debits
    wallet_credit_cents by the resulting net charge, flips billing_status from
    OPEN to INVOICED, and increments version by one."
    PRD §2.4: an integer "version that begins at its initial value and increments
    by one on each modification."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_version_on_invoice_succeeds
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="occ2@x.com", initial_credit_cents=5000)
    resp = api.invoice_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"]),
    )
    data = validate_success(resp, 200)
    assert data["billing_status"] == "INVOICED"
    assert data["version"] == 2
