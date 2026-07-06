"""Per-call charging, per-call ceil-then-sum rounding, tiered marginal overage,
provisional-vs-final overage divergence, and the overage-summary read.

Each test builds its own empty-DB state via test_helpers fixtures.
"""
from test_helpers import (
    validate_success, get_success_data,
    fixtures as fx, factories as f,
    make_platform_admin_headers,
)

ADMIN = make_platform_admin_headers()


# =============================================================================
# Difficulty / combinatorial_formula / per_minute_round_per_call_then_sum
# =============================================================================
def test_per_minute_rounds_each_call_up_before_summing(api):
    """PRD §2.9: "This per-call rounding happens first, on each call in
    isolation; the system never sums raw seconds across multiple calls and rounds
    the total once."
    PRD §3.7: "Under PER_MINUTE, billed_units is this call's duration_seconds
    divided by sixty and rounded up to the next whole minute; a zero-second call
    yields zero units and bills nothing."

    Two 90-second calls each bill ceil(90/60)=2, so consumed_units == 4, not the
    3 that summing raw seconds (180s) and rounding once would give.

    Design: Difficulty/combinatorial_formula/per_minute_round_per_call_then_sum
    """
    env = fx.setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={"included_minutes": 100, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 300, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100},
        clock="2026-03-01T09:00:00Z")
    account = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    period_id = account["current_period_id"]

    c1 = fx.create_completed_call(env, "2026-03-01T09:05:00Z", "2026-03-01T09:06:30Z")
    c2 = fx.create_completed_call(env, "2026-03-01T09:10:00Z", "2026-03-01T09:11:30Z")

    assert c1["billed_units"] == 2, f"call 1 billed_units {c1['billed_units']} != 2"
    assert c2["billed_units"] == 2, f"call 2 billed_units {c2['billed_units']} != 2"

    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["consumed_units"] == 4, (
        f"consumed_units {period['consumed_units']} != 4 (per-call ceil then sum, not 3)")


def test_per_minute_two_short_calls_consumed_units_not_summed_seconds(api):
    """PRD §2.9: "a call's billable minutes are its duration in seconds divided by
    sixty and rounded up to the next whole number, where sixty seconds make one
    minute."

    A 61-second call bills ceil(61/60)=2 units; paired with a 90s call (2 units),
    consumed_units is 4 — confirming the per-call ceil is applied to each call
    independently.

    Design: Difficulty/combinatorial_formula/per_minute_round_per_call_then_sum
    """
    env = fx.setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={"included_minutes": 100, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 300, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100},
        clock="2026-03-01T08:00:00Z")
    account = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    period_id = account["current_period_id"]

    c1 = fx.create_completed_call(env, "2026-03-01T08:05:00Z", "2026-03-01T08:06:30Z")  # 90s
    c2 = fx.create_completed_call(env, "2026-03-01T08:10:00Z", "2026-03-01T08:11:01Z")  # 61s

    assert c1["billed_units"] == 2
    assert c2["billed_units"] == 2, f"61s call billed_units {c2['billed_units']} != 2"
    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["consumed_units"] == 4


# =============================================================================
# Difficulty / combinatorial_formula / tiered_overage_marginal_crosstier_charge
# =============================================================================
def test_marginal_charge_crosses_tier_boundary(api):
    """PRD §3.7: "The system evaluates the period's tiered overage charge twice:
    once on the period's consumed_units as they stand immediately before this call
    is billed, and once on consumed_units plus this call's billed_units. The
    call's charge_cents is the larger of zero and the second figure minus the
    first."
    PRD §3.8: "The overage_charge_cents is then the first-tier units multiplied by
    the plan's overage_rate_cents plus the second-tier units multiplied by the
    plan's overage_tier2_rate_cents."

    included=2, tier2_threshold=3, R1=100, R2=300. After two calls consumed=4
    (overage 2 -> 1 tier-1 unit at threshold-1=2... overage of 4=2 tiers). A third
    121s call (3 units) takes consumed 4->7. Charge at 7 minus charge at 4 = 900.

    Design: Difficulty/combinatorial_formula/tiered_overage_marginal_crosstier_charge
    """
    env = fx.setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={"included_minutes": 2, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 300, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 3},
        clock="2026-03-01T08:00:00Z")
    account = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    period_id = account["current_period_id"]

    fx.create_completed_call(env, "2026-03-01T08:01:00Z", "2026-03-01T08:02:30Z")  # 90s -> 2u
    fx.create_completed_call(env, "2026-03-01T08:05:00Z", "2026-03-01T08:06:01Z")  # 61s -> 2u
    c3 = fx.create_completed_call(env, "2026-03-01T08:10:00Z", "2026-03-01T08:12:01Z")  # 121s -> 3u

    assert c3["billed_units"] == 3, f"call 3 billed_units {c3['billed_units']} != 3"
    assert c3["charge_cents"] == 900, (
        f"call 3 charge_cents {c3['charge_cents']} != 900 (marginal cross-tier 1100-200)")
    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["consumed_units"] == 7
    assert period["overage_charge_cents"] == 1100, (
        f"period overage_charge_cents {period['overage_charge_cents']} != 1100")


def test_call_within_allowance_contributes_zero_charge(api):
    """PRD §3.7: "a call whose units fall entirely within the included allowance
    contributes nothing, while a call whose units push the period into (or further
    into) overage contributes exactly the overage cents that its units add."

    With included_minutes=100, a single 121s (3 unit) call stays within allowance,
    so its charge_cents is 0 even though it bills 3 units.

    Design: Difficulty/combinatorial_formula/tiered_overage_marginal_crosstier_charge
    """
    env = fx.setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={"included_minutes": 100, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 300, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100},
        clock="2026-03-01T08:00:00Z")
    call = fx.create_completed_call(env, "2026-03-01T08:01:00Z", "2026-03-01T08:03:01Z")  # 121s
    assert call["billed_units"] == 3
    assert call["charge_cents"] == 0, (
        f"in-allowance call charge_cents {call['charge_cents']} != 0")


# =============================================================================
# Difficulty / dual_variant_calc / billing_overage_provisional_exceeds_final
# =============================================================================
def test_provisional_overage_includes_in_flight_estimate_final_excludes_it(api):
    """PRD §3.8: "It counts the billed_units of all BILLED and ADJUSTED calls and
    additionally adds a forward-looking estimate for every one of the account's
    calls currently IN_PROGRESS or WRAP_UP."
    PRD §3.8: "The final variant is the authoritative figure persisted on the
    period. It counts billed_units only from calls whose billing_status is BILLED
    or ADJUSTED, excluding all in-flight calls."

    included=2, R1=100, R2=300, tier2_threshold=100. Call A completes 2 units
    (consumed 2, no overage, persisted charge 0). Call B is left IN_PROGRESS at
    121s elapsed -> estimate 3 units -> provisional consumed 5, overage 3, charge
    300. The persisted final period charge stays 0.

    Design: Difficulty/dual_variant_calc/billing_overage_provisional_exceeds_final
    """
    env = fx.setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={"included_minutes": 2, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 300, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100},
        clock="2026-03-01T10:00:00Z")
    account = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    period_id = account["current_period_id"]
    acct_id = env["account"]["id"]
    rec_id = env["receptionist"]["id"]

    # Call A: 90s -> 2 billed minutes, COMPLETED.
    fx.create_completed_call(env, "2026-03-01T10:05:00Z", "2026-03-01T10:06:30Z")

    # Call B: answer + start, leave IN_PROGRESS for 121s elapsed.
    call_b = fx.intake_call(acct_id, rec_id, caller_id="5552222", requested_language="EN")
    fx.answer_call(call_b["id"], rec_id)
    fx.set_clock("2026-03-01T10:10:00Z")
    rec_headers = env["rec_headers"]
    get_success_data(api.start_call(call_b["id"], rec_headers))
    fx.set_clock("2026-03-01T10:12:01Z")  # 121s elapsed

    summary = validate_success(api.get_overage_summary(period_id, ADMIN))
    assert summary["consumed_units"] == 5, (
        f"provisional consumed_units {summary['consumed_units']} != 5")
    assert summary["overage_units"] == 3
    assert summary["overage_charge_cents"] == 300, (
        f"provisional overage_charge_cents {summary['overage_charge_cents']} != 300")
    assert summary["variant"] == "provisional"

    # PRD §3.8: while the period is OPEN, fetching it directly reports the
    # provisional variant (the same figure as the summary), so GET-period cannot
    # observe the persisted final figure. The final variant is "computed ... when
    # a billing period is closed" (PRD §3.8) and surfaced once the period is no
    # longer OPEN (PRD §3.11: beginning the close "finalizes overage_charge_cents
    # under the final variant"). Close the period to read the persisted final
    # figure, which excludes the in-flight Call B entirely.
    open_period = validate_success(api.get_billing_period(period_id, ADMIN))
    closed = validate_success(api.close_billing_period(
        period_id, {"expected_period_version": open_period["version"]}, ADMIN))
    assert closed["overage_charge_cents"] == 0, (
        f"final persisted overage_charge_cents {closed['overage_charge_cents']} != 0")


def test_provisional_overage_is_upper_bound_above_final(api):
    """PRD §3.8: "Because it anticipates in-flight calls, the provisional figure is
    an upper-bound preview that may exceed the eventual final charge."

    With one COMPLETED call (final charge persisted) and one in-flight WRAP_UP
    call adding an estimate, the provisional summary overage_charge_cents is
    strictly greater than the period's persisted (final) overage_charge_cents.

    Design: Difficulty/dual_variant_calc/billing_overage_provisional_exceeds_final
    """
    env = fx.setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={"included_minutes": 2, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 300, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100},
        clock="2026-03-01T10:00:00Z")
    account = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    period_id = account["current_period_id"]
    acct_id = env["account"]["id"]
    rec_id = env["receptionist"]["id"]
    rec_headers = env["rec_headers"]

    fx.create_completed_call(env, "2026-03-01T10:05:00Z", "2026-03-01T10:06:30Z")  # 2u
    call_b = fx.intake_call(acct_id, rec_id, caller_id="5552222")
    fx.answer_call(call_b["id"], rec_id)
    fx.set_clock("2026-03-01T10:10:00Z")
    get_success_data(api.start_call(call_b["id"], rec_headers))
    fx.set_clock("2026-03-01T10:12:01Z")  # 121s in-flight

    summary = validate_success(api.get_overage_summary(period_id, ADMIN))
    # PRD §3.8: an OPEN period reports the provisional variant on direct fetch, so
    # the persisted final figure is only observable once the period is no longer
    # OPEN. Close the period (PRD §3.11 finalizes overage under the final variant)
    # to read the authoritative final charge, then assert provisional > final.
    open_period = validate_success(api.get_billing_period(period_id, ADMIN))
    final_period = validate_success(api.close_billing_period(
        period_id, {"expected_period_version": open_period["version"]}, ADMIN))
    assert summary["overage_charge_cents"] > final_period["overage_charge_cents"], (
        f"provisional {summary['overage_charge_cents']} must exceed final "
        f"{final_period['overage_charge_cents']}")


# =============================================================================
# Corner / calculations / per_call_charge_is_one_unit_regardless_of_duration
# =============================================================================
def test_per_call_plan_bills_one_unit_regardless_of_duration(api):
    """PRD §3.7: "Under PER_CALL, billed_units is exactly 1 regardless of
    duration, and the plan's included_calls allowance applies."

    A 121-second call on a PER_CALL plan bills exactly 1 unit.

    Design: Corner/calculations/per_call_charge_is_one_unit_regardless_of_duration
    """
    env = fx.setup_answer_environment(plan_kind="PER_CALL", clock="2026-03-01T09:00:00Z")
    call = fx.create_completed_call(env, "2026-03-01T09:00:00Z", "2026-03-01T09:02:01Z")  # 121s
    assert call["duration_seconds"] == 121, (
        f"duration_seconds {call['duration_seconds']} != 121")
    assert call["billed_units"] == 1, (
        f"PER_CALL billed_units {call['billed_units']} != 1")


# =============================================================================
# Corner / calculations / per_minute_zero_duration_bills_zero_units
# =============================================================================
def test_per_minute_zero_duration_bills_zero_units(api):
    """PRD §2.9: "A call with zero duration rounds up to zero minutes and therefore
    bills nothing."

    A PER_MINUTE call wrapped at the same logical second it started has
    duration_seconds 0 -> ceil(0/60)=0 billed units and 0 charge.

    Design: Corner/calculations/per_minute_zero_duration_bills_zero_units
    """
    env = fx.setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={"included_minutes": 0, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 300, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100},
        clock="2026-03-01T09:00:00Z")
    account = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    period_id = account["current_period_id"]
    acct_id = env["account"]["id"]
    rec_id = env["receptionist"]["id"]
    rec_headers = env["rec_headers"]

    call = fx.intake_call(acct_id, rec_id, caller_id="5550001")
    fx.answer_call(call["id"], rec_id)
    # start and wrap at the same clock instant -> duration 0.
    get_success_data(api.start_call(call["id"], rec_headers))
    wrapped = get_success_data(api.wrap_call(call["id"], rec_headers))
    assert wrapped["duration_seconds"] == 0, (
        f"duration_seconds {wrapped['duration_seconds']} != 0")
    completed = get_success_data(api.complete_call(call["id"], rec_headers))

    assert completed["billed_units"] == 0, f"billed_units {completed['billed_units']} != 0"
    assert completed["charge_cents"] == 0, f"charge_cents {completed['charge_cents']} != 0"
    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["consumed_units"] == 0


# =============================================================================
# Corner / endpoints / overage_summary_reports_provisional_variant
# =============================================================================
def test_overage_summary_reports_provisional_variant_on_open_period(api):
    """PRD §3.8: "The overage summary read returns, for an OPEN period, the
    provisional breakdown: consumed_units, overage_units, the first-tier unit
    count as tier1_units, the second-tier unit count as tier2_units, the
    overage_charge_cents, and a variant label identifying which variant produced
    the figures."

    A fresh account with no usage reports variant "provisional" and all-zero
    breakdown.

    Design: Corner/endpoints/overage_summary_reports_provisional_variant
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_minute_plan(
        plan_overrides={"included_minutes": 2, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 300, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100})
    period_id = account["current_period_id"]
    summary = validate_success(api.get_overage_summary(period_id, ADMIN))
    assert summary["variant"] == "provisional"
    assert summary["consumed_units"] == 0
    assert summary["overage_units"] == 0
    assert summary["overage_charge_cents"] == 0


# =============================================================================
# Corner / cross_cutting_complexity_layers / first_overage_unit_marks_delinquent
# =============================================================================
def test_overage_below_hard_cap_marks_account_delinquent(api):
    """PRD §3.9: "From ACTIVE, the account moves to DELINQUENT when the open
    period's overage_units is greater than zero while its overage_charge_cents is
    still below the hard cap."

    included=0, R1=100, hard_cap=100000 (high). A 61s call bills 2 units ->
    overage 2 -> charge 200 < cap -> account becomes DELINQUENT, not SUSPENDED.

    Design: Corner/cross_cutting_complexity_layers/first_overage_unit_marks_delinquent
    """
    env = fx.setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={"included_minutes": 0, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 100, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100},
        clock="2026-03-01T09:00:00Z")
    account = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    period_id = account["current_period_id"]

    call = fx.create_completed_call(env, "2026-03-01T09:00:00Z", "2026-03-01T09:01:01Z")  # 61s
    assert call["billed_units"] == 2

    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["overage_units"] == 2
    assert period["overage_charge_cents"] == 200

    acct = validate_success(api.get_account(env["account"]["id"], ADMIN))
    assert acct["status"] == "DELINQUENT", (
        f"account status {acct['status']} != DELINQUENT (overage>0, below cap)")
