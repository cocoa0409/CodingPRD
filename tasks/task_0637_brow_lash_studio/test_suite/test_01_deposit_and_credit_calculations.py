"""Dual-variant and combinatorial calculation tests (deposit forfeiture, cycle rollover,
retail rounding order, credit gate evaluation order).

Design queue A (Difficulty): dual_variant_calc, combinatorial_formula.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_lash_tech_headers,
    create_appointment_payload, create_retail_order_payload,
)
from test_helpers.fixtures import (
    SM, FD, set_clock, create_studio, create_service_type, create_plan, create_tech,
    create_member, create_membership, sanitize_tech, credit_ledger, get_membership,
)


# ──────────────────────────────────────────────────────────────────────────
# dual_variant_calc / deposit_forfeiture_noshow_vs_late_cancel
# ──────────────────────────────────────────────────────────────────────────
def _setup_two_cash_full_set_appts():
    """Studio deposit 0.20, cutoff 24h; FULL_SET base 12000; two sanitized techs; member.
    Books a no-show appt (start 09:30) and a late-cancel appt (start 20:00) at clock 10:00."""
    studio = create_studio(name="Glow", deposit_rate_pct=0.20, late_cancel_cutoff_hours=24)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech1 = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    tech2 = create_tech(studio["id"], full_name="Nia", skill_level=3, station_number=2)
    sanitize_tech(tech1["id"], "2026-06-10T09:00:00Z")
    sanitize_tech(tech2["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    appt_ns = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T09:30:00Z",
                                   pay_with_credits=False), FD))
    appt_late = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z",
                                   pay_with_credits=False), FD))
    return member, appt_ns, appt_late


def test_noshow_forfeits_full_deposit():
    """PRD §3.8: "The full deposit is kept: `deposit_forfeited_cents` is set equal to
    `deposit_cents`, and the cash deposit is retained by the studio."

    Design: Difficulty/dual_variant_calc/deposit_forfeiture_noshow_vs_late_cancel
    """
    member, appt_ns, _ = _setup_two_cash_full_set_appts()
    assert appt_ns["deposit_cents"] == 2400, f"deposit should be 12000*0.20=2400, got {appt_ns['deposit_cents']}"
    resolved = validate_success(api_client.mark_no_show(appt_ns["id"], FD))
    assert resolved["status"] == "NO_SHOW"
    assert resolved["deposit_forfeited_cents"] == 2400, \
        f"NO_SHOW forfeits full deposit 2400, got {resolved['deposit_forfeited_cents']}"


def test_late_cancel_forfeits_half_deposit():
    """PRD §3.8: "the appointment moves to `LATE_CANCELLED`, and `deposit_forfeited_cents`
    is set to the deposit multiplied by one half, rounded half up to the nearest cent, so
    the studio keeps half the deposit."

    Design: Difficulty/dual_variant_calc/deposit_forfeiture_noshow_vs_late_cancel
    """
    member, _, appt_late = _setup_two_cash_full_set_appts()
    resolved = validate_success(api_client.cancel_appointment(appt_late["id"], FD))
    assert resolved["status"] == "LATE_CANCELLED", \
        f"clock 10:00 vs start 20:00 (10h < 24h cutoff) is late, got {resolved['status']}"
    assert resolved["deposit_forfeited_cents"] == 1200, \
        f"LATE_CANCELLED forfeits half of 2400 = 1200, got {resolved['deposit_forfeited_cents']}"


# ──────────────────────────────────────────────────────────────────────────
# dual_variant_calc / cycle_rollover_within_cap_vs_over_cap
# ──────────────────────────────────────────────────────────────────────────
def _setup_two_memberships_for_rollover():
    """PREMIER plan allotment=4 cap multiplier 1.0 (cap 4); membership A initial 3, B initial 6."""
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=4,
                       monthly_fee_cents=9900, rollover_cap_multiplier=1.0)
    member_a = create_member(studio["id"], full_name="A", email="a@x.com")
    member_b = create_member(studio["id"], full_name="B", email="b@x.com")
    ms_a = create_membership(member_a["id"], plan["id"], initial_credits=3)
    ms_b = create_membership(member_b["id"], plan["id"], initial_credits=6)
    return ms_a, ms_b


def test_cycle_close_within_cap_carries_all_credits():
    """PRD §3.4: "When the pre-close balance is at or below the ceiling, nothing is
    forfeited and the carried amount equals the pre-close balance. After any forfeiture, a
    `GRANT` ledger entry with a `delta` of the plan's `monthly_credit_allotment` is appended,
    so the resulting `credit_balance` equals the carried amount plus the monthly allotment."

    Design: Difficulty/dual_variant_calc/cycle_rollover_within_cap_vs_over_cap
    """
    ms_a, _ = _setup_two_memberships_for_rollover()
    closed = validate_success(api_client.close_cycle(ms_a["id"], ms_a["version"], SM))
    assert closed["credit_balance"] == 7, f"3 carried + 4 grant = 7, got {closed['credit_balance']}"
    ledger = credit_ledger(ms_a["id"])
    forfeits = [e for e in ledger if e["reason"] == "ROLLOVER_FORFEIT"]
    assert forfeits == [], f"no forfeit when within cap, got {forfeits}"


def test_cycle_close_over_cap_forfeits_overage():
    """PRD §3.4: "When the pre-close balance exceeds the ceiling, the overage is given up: a
    `ROLLOVER_FORFEIT` ledger entry with a `delta` equal to the negative of the forfeited
    amount is appended; the alternative reading in which all credits are carried regardless
    of the cap is incorrect and must not be implemented."

    Design: Difficulty/dual_variant_calc/cycle_rollover_within_cap_vs_over_cap
    """
    _, ms_b = _setup_two_memberships_for_rollover()
    closed = validate_success(api_client.close_cycle(ms_b["id"], ms_b["version"], SM))
    assert closed["credit_balance"] == 8, f"min(6,4)=4 carried + 4 grant = 8, got {closed['credit_balance']}"
    ledger = credit_ledger(ms_b["id"])
    forfeits = [e for e in ledger if e["reason"] == "ROLLOVER_FORFEIT"]
    assert len(forfeits) == 1, f"exactly one ROLLOVER_FORFEIT expected, got {forfeits}"
    assert forfeits[0]["delta"] == -2, f"forfeit delta should be -(6-4)=-2, got {forfeits[0]['delta']}"


# ──────────────────────────────────────────────────────────────────────────
# combinatorial_formula / retail_total_per_line_round_then_sum
# ──────────────────────────────────────────────────────────────────────────
def test_retail_subtotal_rounds_per_line_then_sums():
    """PRD §3.9: "For each line, the line amount is `unit_price_cents` multiplied by
    `quantity` multiplied by one minus the loyalty fraction, rounded half up to the nearest
    cent — the discount and rounding are applied **per line first**, and only then are the
    line amounts summed into `subtotal_cents`. Summing the raw amounts and rounding once at
    the end is the wrong reading and must not be used."

    Design: Difficulty/combinatorial_formula/retail_total_per_line_round_then_sum
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=4,
                       monthly_fee_cents=9900, loyalty_discount_pct=0.10)
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    create_membership(member["id"], plan["id"])
    set_clock("2026-06-10T10:00:00Z")
    appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-10T13:00:00Z",
                                   pay_with_credits=False), FD))
    order = validate_success(api_client.create_retail_order(
        create_retail_order_payload(member["id"], appt["id"],
            [{"sku": "SERUM", "unit_price_cents": 125, "quantity": 1},
             {"sku": "GEL", "unit_price_cents": 125, "quantity": 1}]), FD), expected_status=201)
    # per line: round(125*1*0.9)=round(112.5)=113; 113+113=226 (sum-then-round would give 225)
    assert order["subtotal_cents"] == 226, f"per-line round-then-sum = 226, got {order['subtotal_cents']}"
    assert order["peak_surcharge_cents"] == 0
    assert order["total_cents"] == 226


def test_retail_subtotal_per_line_rounding_distinct_from_sum_then_round():
    """PRD §3.9: "the discount and rounding are applied **per line first**, and only then are
    the line amounts summed into `subtotal_cents`. Summing the raw amounts and rounding once
    at the end is the wrong reading and must not be used."

    Design: Difficulty/combinatorial_formula/retail_total_per_line_round_then_sum
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=4,
                       monthly_fee_cents=9900, loyalty_discount_pct=0.10)
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    create_membership(member["id"], plan["id"])
    set_clock("2026-06-10T10:00:00Z")
    appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-10T13:00:00Z",
                                   pay_with_credits=False), FD))
    order = validate_success(api_client.create_retail_order(
        create_retail_order_payload(member["id"], appt["id"],
            [{"sku": "SERUM", "unit_price_cents": 75, "quantity": 1},
             {"sku": "GEL", "unit_price_cents": 75, "quantity": 1}]), FD), expected_status=201)
    # per line: round(75*0.9)=round(67.5)=68; 68+68=136 (sum-then-round would give round(135)=135)
    assert order["subtotal_cents"] == 136, f"per-line round-then-sum = 136, got {order['subtotal_cents']}"
    assert order["peak_surcharge_cents"] == 0
    assert order["total_cents"] == 136


# ──────────────────────────────────────────────────────────────────────────
# combinatorial_formula / credit_gate_evaluation_order_before_consume
# ──────────────────────────────────────────────────────────────────────────
def test_credit_gate_passes_at_exact_balance_then_consumes():
    """PRD §3.5: "the available balance is read as the sum of the membership's existing
    ledger deltas before this booking; the required amount is the service's `credit_cost`;
    if the available balance is less than the required amount the booking is rejected with
    `ERR_INSUFFICIENT_CREDITS` (HTTP 402) and nothing is appended; only when the gate passes
    does the system append a `CONSUME` ledger entry with a `delta` of the negative of the
    required amount, set `credits_charged` to the required amount, and increment the
    membership's `version` by one."

    Design: Difficulty/combinatorial_formula/credit_gate_evaluation_order_before_consume
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=4)
    set_clock("2026-06-10T10:00:00Z")
    appt = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms["version"]), FD), expected_status=201)
    assert appt["status"] == "BOOKED"
    assert appt["credits_charged"] == 4, f"credits_charged should equal cost 4, got {appt['credits_charged']}"
    after = get_membership(ms["id"])
    assert after["credit_balance"] == 0, f"4-4=0, got {after['credit_balance']}"
    ledger = credit_ledger(ms["id"])
    consumes = [e for e in ledger if e["reason"] == "CONSUME"]
    assert len(consumes) == 1 and consumes[0]["delta"] == -4, \
        f"one CONSUME delta -4 expected, got {consumes}"


def test_credit_gate_rejects_below_required_no_consume_appended():
    """PRD §3.5: "if the available balance is less than the required amount the booking is
    rejected with `ERR_INSUFFICIENT_CREDITS` (HTTP 402) and nothing is appended".

    Design: Difficulty/combinatorial_formula/credit_gate_evaluation_order_before_consume
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=3)
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms["version"]), FD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS)
    after = get_membership(ms["id"])
    assert after["credit_balance"] == 3, f"balance unchanged (no append) = 3, got {after['credit_balance']}"
    ledger = credit_ledger(ms["id"])
    assert [e for e in ledger if e["reason"] == "CONSUME"] == [], "no CONSUME appended on rejection"
