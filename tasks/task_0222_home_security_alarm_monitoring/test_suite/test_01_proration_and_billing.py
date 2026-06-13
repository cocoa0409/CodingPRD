"""Proration, plan-change billing, permit fees, and early-termination fees.

Covers the dual-variant proration calculation (day-by-day round-then-sum
authoritative value vs the per-segment forward quote), the combinatorial
permit-fee formula, and the early-termination boundary.
"""
import pytest

from test_helpers import (
    validate_success,
    make_admin_headers,
    set_clock,
    create_plan,
    create_account,
    create_system,
    create_sensor,
    setup_two_plans_activated_account,
    change_plan_payload,
    create_permit_payload,
    BASE_PERMIT_FEE_CENTS,
    COMMERCIAL_UPLIFT_CENTS,
    LATE_CAP_CENTS,
)

ADMIN = make_admin_headers()


# ─── dual_variant_calc / combinatorial_formula: proration day-7 BASIC->PLUS ──

def _activate_basic_change_plus_read(api):
    """Helper: BASIC account activated at day0, changed to PLUS at day7, read
    at day30. Returns the day-30 account read.

    Mirrors the day-by-day proration scenario: fees 1500 (BASIC) / 3100 (PLUS).
    """
    set_clock("2026-06-01T00:00:00Z")
    bp = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                     max_sensors=8, cellular_backup_included=False)
    pp = create_plan(tier="PLUS", monthly_fee_cents=3100, police_dispatch_included=True,
                     max_sensors=16, cellular_backup_included=True)
    acct = create_account(bp["id"])
    system = create_system(acct["id"], primary_path="BROADBAND")
    create_sensor(system["id"], zone_number=1, sensor_type="DOOR")
    activated = validate_success(api.activate_account(acct["id"], ADMIN), 200)
    version = activated["version"]

    set_clock("2026-06-08T00:00:00Z")  # day 7
    validate_success(
        api.change_plan(acct["id"], change_plan_payload(pp["id"], version), ADMIN), 200)

    set_clock("2026-07-01T00:00:00Z")  # day 30
    return validate_success(api.get_account(acct["id"], ADMIN), 200)


def test_proration_day7_change_uses_day_by_day_value_2719(api):
    """PRD §3.2: "For reference, a `BASIC`-to-`PLUS` change at day seven, with
    monthly fees of 1500 and 3100 cents, yields 2719 cents under this
    authoritative day-by-day method (a per-segment projection that rounds once
    per segment would instead yield 2727, but that projection is only a forward
    quote, never the stored value)."

    Design: Difficulty/dual_variant_calc/proration_forward_quote_vs_final_chronological
    """
    acct = _activate_basic_change_plus_read(api)
    assert acct["monitoring_balance_cents"] == 2719, (
        f"authoritative day-by-day proration must be 2719, "
        f"got {acct['monitoring_balance_cents']}"
    )


def test_proration_day7_change_is_not_per_segment_quote_2727(api):
    """PRD §3.2: "a per-segment projection that rounds once per segment would
    instead yield 2727, but that projection is only a forward quote, never the
    stored value."

    Design: Difficulty/dual_variant_calc/proration_forward_quote_vs_final_chronological
    """
    acct = _activate_basic_change_plus_read(api)
    assert acct["monitoring_balance_cents"] != 2727, (
        "stored monitoring_balance must never be the 2727 per-segment forward quote"
    )
    assert acct["current_tier"] == "PLUS", "current_tier reflects the changed-to plan"


def test_proration_rounding_order_per_day_yields_2719(api):
    """PRD §3.2: "The rounding order is fixed: each day is rounded to whole cents
    first, and only then are the rounded daily charges summed. The system must
    not sum unrounded daily fractions and round once at the end."

    Design: Difficulty/combinatorial_formula/proration_rounding_order_per_day_vs_per_segment
    """
    acct = _activate_basic_change_plus_read(api)
    assert acct["monitoring_balance_cents"] == 2719, (
        "per-day round-then-sum order is pinned; balance must be 2719"
    )


def test_proration_rounding_order_not_sum_then_round(api):
    """PRD §3.2: "That day's charge is the monthly fee of the in-effect tier's
    plan divided by 30, rounded half up to a whole cent. The proration amount is
    the sum of those per-day charges across all elapsed days."

    Design: Difficulty/combinatorial_formula/proration_rounding_order_per_day_vs_per_segment
    """
    acct = _activate_basic_change_plus_read(api)
    # A sum-then-round / per-segment order would surface 2727; the pinned order
    # must not produce that.
    assert acct["monitoring_balance_cents"] != 2727


# ─── combinatorial_formula: permit fee (commercial uplift + capped late) ─────

def test_permit_fee_commercial_200_days_late_hits_cap_12000(api):
    """PRD §3.8: "The base is 5000 cents, plus a commercial uplift of 3000 cents
    when the account's `premises_type` is `COMMERCIAL`... the penalty is the base
    permit fee of 5000 cents multiplied by 20 percent per late period, where the
    number of late periods is `filed_days_late` divided by 30 and rounded up to
    the next whole period; that product is rounded half up to whole cents and
    then capped at 4000 cents. The `fee_total_cents` is the base plus this late
    penalty."

    Design: Difficulty/combinatorial_formula/permit_fee_commercial_uplift_plus_capped_late_penalty
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    acct = create_account(plan["id"], premises_type="COMMERCIAL")
    res = api.create_permit(
        create_permit_payload(acct["id"], "P-COMM-200", filed_days_late=200), ADMIN)
    permit = validate_success(res, 201)
    # base = 5000 + 3000 = 8000; penalty = min(round(5000*0.2*ceil(200/30)), 4000)
    #      = min(round(5000*0.2*7), 4000) = min(7000, 4000) = 4000; total = 12000
    assert permit["fee_total_cents"] == 12000, (
        f"expected 12000 (8000 base + 4000 capped penalty), got {permit['fee_total_cents']}"
    )


def test_permit_fee_commercial_capped_penalty_not_uncapped_15000(api):
    """PRD §3.8: "that product is rounded half up to whole cents and then capped
    at 4000 cents."

    Design: Difficulty/combinatorial_formula/permit_fee_commercial_uplift_plus_capped_late_penalty
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    acct = create_account(plan["id"], premises_type="COMMERCIAL")
    permit = validate_success(
        api.create_permit(create_permit_payload(acct["id"], "P-COMM-200B", filed_days_late=200), ADMIN),
        201)
    # 8000 + 7000 (uncapped) = 15000 must NOT occur — the cap applies.
    assert permit["fee_total_cents"] != 15000, "late penalty must be capped at 4000"
    assert permit["fee_total_cents"] == BASE_PERMIT_FEE_CENTS + COMMERCIAL_UPLIFT_CENTS + LATE_CAP_CENTS
