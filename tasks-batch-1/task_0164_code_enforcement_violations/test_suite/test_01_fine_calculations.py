"""Fine accrual: provisional vs settlement, cap-then-multiply-then-round ordering,
the max-total cap boundary, and base-only / small-accrual results.

PRD coverage: §2.6 (rounding once on the final product), §3.6 (the accrual formula,
the provisional/settlement split, and the cap).
"""
from test_helpers import validate_success
from test_helpers import fixtures as F
from test_helpers.api_client import api_client


OFFICER = F.OFFICER


# ==========================================================================
# Difficulty: dual_variant_calc / fine_accrual_provisional_vs_settlement_on_notice
# ==========================================================================
def test_overdue_notice_reports_provisional_fine_total(api):
    """PRD §3.6: "While a notice is `OVERDUE`, the figure is provisional: it is
    recomputed on every read against the current clock and grows as days pass."
    PRD §3.6: "The raw accrual is the schedule's `base_fine_cents` plus its
    `daily_accrual_cents` multiplied by `days_overdue`."

    Design: Difficulty/dual_variant_calc/fine_accrual_provisional_vs_settlement_on_notice
    """
    ctx = F.setup_overdue_notice(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    notice = validate_success(api.get_notice(ctx["notice"]["id"], OFFICER))
    assert notice["status"] == "OVERDUE", f"expected OVERDUE, got {notice['status']}"
    assert notice["days_overdue"] == 10, f"expected 10 overdue days, got {notice['days_overdue']}"
    # base 20000 + daily 500 * 10 = 25000, under cap, FIRST tier *1.0
    assert notice["fine_total_cents"] == 25000, (
        f"provisional total expected 25000, got {notice['fine_total_cents']}"
    )


def test_passed_reinspection_freezes_settlement_fine_total(api):
    """PRD §3.6: "Once a notice reaches `COMPLIED`, `UPHELD`, `DISMISSED`, or
    `SETTLED`, or once a contest pauses accrual, the figure is frozen at its
    settlement value as of the freezing instant and never changes again."
    PRD §3.7: "From `OVERDUE`, recording a passing re-inspection moves the notice
    to `COMPLIED` and freezes `fine_total_cents` at the settlement variant computed
    as of the re-inspection's `result_on` instant"

    Design: Difficulty/dual_variant_calc/fine_accrual_provisional_vs_settlement_on_notice
    """
    ctx = F.setup_overdue_notice(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    nid = ctx["notice"]["id"]
    # Observe the provisional figure while OVERDUE.
    provisional = validate_success(api.get_notice(nid, OFFICER))["fine_total_cents"]
    assert provisional == 25000

    reinsp = F.schedule_reinspection(nid)
    F.record_reinspection(reinsp["id"], "PASSED")

    settled = validate_success(api.get_notice(nid, OFFICER))
    assert settled["status"] == "COMPLIED", f"expected COMPLIED, got {settled['status']}"
    # Frozen at result_on = 2026-01-25 (10 days overdue) -> same 25000, fixed thereafter.
    assert settled["fine_total_cents"] == 25000, (
        f"settlement total expected 25000, got {settled['fine_total_cents']}"
    )


# ==========================================================================
# Difficulty: combinatorial_formula / fine_accrual_cap_then_multiply_then_round_order
# ==========================================================================
def test_repeat_tier_fine_applies_multiplier_after_cap_rounded_once(api):
    """PRD §3.6: "Only after the cap is applied does the escalation multiplier come
    in: the capped, pre-multiplier figure is multiplied by the notice's frozen
    `escalation_multiplier`, and that single product is rounded half-up to the
    nearest whole cent to yield `fine_total_cents`."
    PRD §2.6: "the product is rounded to the nearest whole cent using the
    round-half-up convention, and that rounding is applied exactly once to the final
    product — never per intermediate day and never to a running subtotal."

    Design: Difficulty/combinatorial_formula/fine_accrual_cap_then_multiply_then_round_order
    """
    # Drive the owner to REPEAT, then issue the test notice while REPEAT (1.5x).
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner = F.create_owner()
    F.raise_owner_to_repeat(owner["id"], "MAJOR")

    # Confirm the owner is now REPEAT before issuance.
    live = validate_success(api.get_owner(owner["id"], OFFICER))
    assert live["repeat_tier"] == "REPEAT", f"setup expected REPEAT, got {live['repeat_tier']}"

    F.set_clock("2026-03-01T00:00:00Z")
    prop = F.create_property(owner["id"])
    case = F.create_case(prop["id"])
    insp = F.add_violation_found_inspection(case["id"])
    notice = F.issue_notice(case["id"], insp["id"], "MAJOR")
    F.set_clock("2026-03-25T00:00:00Z")  # 10 whole days past 2026-03-15 deadline

    got = validate_success(api.get_notice(notice["id"], OFFICER))
    assert got["escalation_multiplier"] == 1.5, (
        f"expected frozen 1.5 multiplier, got {got['escalation_multiplier']}"
    )
    assert got["days_overdue"] == 10, f"expected 10 overdue days, got {got['days_overdue']}"
    # min(20000+500*10, 100000) = 25000; 25000 * 1.5 = 37500, rounded once.
    assert got["fine_total_cents"] == 37500, (
        f"expected 37500 (cap-then-multiply-then-round), got {got['fine_total_cents']}"
    )


def test_repeat_tier_fine_multiplies_uncapped_accrual_rounded_once(api):
    """PRD §3.6: "Only after the cap is applied does the escalation multiplier come
    in: the capped, pre-multiplier figure is multiplied by the notice's frozen
    `escalation_multiplier`, and that single product is rounded half-up to the
    nearest whole cent to yield `fine_total_cents`. The multiplier is applied after
    the cap, and the half-up rounding happens exactly once on the final product —
    the daily accrual is never rounded per-day."

    Design: Difficulty/combinatorial_formula/fine_accrual_cap_then_multiply_then_round_order
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner = F.create_owner()
    F.raise_owner_to_repeat(owner["id"], "MAJOR")

    F.set_clock("2026-03-01T00:00:00Z")
    prop = F.create_property(owner["id"])
    case = F.create_case(prop["id"])
    insp = F.add_violation_found_inspection(case["id"])
    notice = F.issue_notice(case["id"], insp["id"], "MAJOR")
    F.set_clock("2026-03-20T00:00:00Z")  # 5 whole days past the 2026-03-15 deadline

    got = validate_success(api.get_notice(notice["id"], OFFICER))
    assert got["days_overdue"] == 5, f"expected 5 overdue days, got {got['days_overdue']}"
    # (20000 + 500*5) = 22500 (well under cap); 22500 * 1.5 = 33750, rounded once.
    assert got["fine_total_cents"] == 33750, (
        f"expected 33750 (accrual then *1.5, rounded once), got {got['fine_total_cents']}"
    )


# ==========================================================================
# Difficulty: boundary_precision_check / fine_cap_boundary_at_max_total
# ==========================================================================
def test_fine_below_cap_one_day_before_boundary(api):
    """PRD §3.6: "The raw accrual is the schedule's `base_fine_cents` plus its
    `daily_accrual_cents` multiplied by `days_overdue`. That raw figure is then
    capped at the schedule's `max_total_cents` by taking the smaller of the two."

    Design: Difficulty/boundary_precision_check/fine_cap_boundary_at_max_total
    """
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    nid = ctx["notice"]["id"]
    F.set_clock("2026-06-23T00:00:00Z")  # 159 whole days past 2026-01-15 deadline
    got = validate_success(api.get_notice(nid, OFFICER))
    assert got["days_overdue"] == 159, f"expected 159 overdue days, got {got['days_overdue']}"
    # 20000 + 500*159 = 99500, still below the 100000 cap.
    assert got["fine_total_cents"] == 99500, (
        f"expected 99500 (uncapped), got {got['fine_total_cents']}"
    )


def test_fine_reaches_cap_exactly_at_boundary(api):
    """PRD §3.6: "That raw figure is then capped at the schedule's `max_total_cents`
    by taking the smaller of the two."

    Design: Difficulty/boundary_precision_check/fine_cap_boundary_at_max_total
    """
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    nid = ctx["notice"]["id"]
    F.set_clock("2026-06-24T00:00:00Z")  # 160 whole days past 2026-01-15 deadline
    got = validate_success(api.get_notice(nid, OFFICER))
    assert got["days_overdue"] == 160, f"expected 160 overdue days, got {got['days_overdue']}"
    # 20000 + 500*160 = 100000, exactly at the cap.
    assert got["fine_total_cents"] == 100000, (
        f"expected 100000 (at cap), got {got['fine_total_cents']}"
    )


# ==========================================================================
# Corner: calculations / minor_fine_accrual_correct_result
# ==========================================================================
def test_minor_notice_accrual_correct_result(api):
    """PRD §3.6: "The raw accrual is the schedule's `base_fine_cents` plus its
    `daily_accrual_cents` multiplied by `days_overdue`."

    Design: Corner/calculations/minor_fine_accrual_correct_result
    """
    ctx = F.setup_issued_notice("MINOR", clock="2026-01-01T00:00:00Z")
    nid = ctx["notice"]["id"]
    F.set_clock("2026-01-27T00:00:00Z")  # 5 whole days past 2026-01-22 deadline (cure 21)
    got = validate_success(api.get_notice(nid, OFFICER))
    assert got["days_overdue"] == 5, f"expected 5 overdue days, got {got['days_overdue']}"
    # 5000 + 200*5 = 6000, FIRST tier.
    assert got["fine_total_cents"] == 6000, (
        f"expected 6000 (5000 + 200*5), got {got['fine_total_cents']}"
    )


# ==========================================================================
# Corner: calculations / not_yet_overdue_notice_fine_is_base_only
# ==========================================================================
def test_notice_within_cure_window_is_base_only(api):
    """PRD §3.6: "the whole days elapsed between the `compliance_deadline` and the
    as-of instant ... if that result is negative it is treated as zero, so
    `days_overdue` never drops below zero. The raw accrual is the schedule's
    `base_fine_cents` plus its `daily_accrual_cents` multiplied by `days_overdue`."

    Design: Corner/calculations/not_yet_overdue_notice_fine_is_base_only
    """
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    nid = ctx["notice"]["id"]
    F.set_clock("2026-01-10T00:00:00Z")  # before the 2026-01-15 deadline
    got = validate_success(api.get_notice(nid, OFFICER))
    assert got["status"] == "ISSUED", f"expected still ISSUED, got {got['status']}"
    assert got["days_overdue"] == 0, f"expected 0 overdue days, got {got['days_overdue']}"
    # base 20000 + 200*0 -> 20000, FIRST tier.
    assert got["fine_total_cents"] == 20000, (
        f"expected 20000 (base only), got {got['fine_total_cents']}"
    )
