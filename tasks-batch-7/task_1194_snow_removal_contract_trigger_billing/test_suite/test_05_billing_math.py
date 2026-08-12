"""Billing mathematics: dual-variant preview, hourly tiering, rounding, true-up."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_true_up_payload,
    setup_active_per_push, setup_active_seasonal, setup_active_hourly,
    setup_storm_event, schedule_visit, set_clock, post_observation, verify_event,
    setup_completed_visit, setup_billable_visit, log_material, expire_contract_at,
    create_material_payload,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CREW = TEST_USERS["crew_lead_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / provisional_preview_vs_final_invoice_push_billing
# ---------------------------------------------------------------------------

def _setup_dual_variant_scenario(api):
    """PER_PUSH contract (trigger 2.0, rate 45000); two REPORTED events each with
    one COMPLETED visit: e1 will verify at 2.6 (billable), e2 at 1.4 (below)."""
    ctx = setup_active_per_push(client_name="Acme Properties",
                                trigger_depth_inches=2.0, per_push_rate_cents=45_000,
                                require_photo_verification=False,
                                pavement_area_sqft=50_000)
    set_clock("2026-12-10T07:00:00Z")
    e1 = setup_storm_event(window_start="2026-12-10T00:00:00Z",
                           window_end="2026-12-10T08:00:00Z",
                           reported_accumulation_inches=2.6)
    e2 = setup_storm_event(window_start="2026-12-12T00:00:00Z",
                           window_end="2026-12-12T06:00:00Z",
                           reported_accumulation_inches=3.0)
    v1 = setup_completed_visit(ctx, e1)
    v2 = setup_completed_visit(
        ctx, e2, scheduled_start="2026-12-12T09:00:00Z",
        scheduled_end="2026-12-12T10:00:00Z",
        start_at="2026-12-12T09:05:00Z", complete_at="2026-12-12T10:00:00Z")
    return ctx, e1, e2, v1, v2


def _verify_dual_variant_events(e1, e2):
    post_observation(e1["id"], "NOAA", "2026-12-10T07:30:00Z", 2.5)
    post_observation(e1["id"], "DTN", "2026-12-10T08:00:00Z", 2.6)
    verify_event(e1["id"])
    post_observation(e2["id"], "NOAA", "2026-12-12T05:00:00Z", 1.5)
    post_observation(e2["id"], "DTN", "2026-12-12T05:30:00Z", 1.4)
    verify_event(e2["id"])


def test_provisional_counts_reported_events_while_final_excludes_them(api):
    """PRD §3.7: "the `provisional_billable_push_count` and `provisional_billable_cents` count `REPORTED` and `CHALLENGED` events at their `reported_accumulation_inches` and `VERIFIED` or `CLOSED` events at `verified_accumulation_inches`, while the `final_billable_push_count` and `final_billable_cents` count only `VERIFIED` and `CLOSED` events — mirroring exactly what invoicing may bill."

    Design: Difficulty/dual_variant_calc/provisional_preview_vs_final_invoice_push_billing
    """
    ctx, e1, e2, v1, v2 = _setup_dual_variant_scenario(api)
    preview = validate_success(
        api.get_billing_preview(ctx["contract"]["id"], DISPATCH), 200)
    assert preview["provisional_billable_push_count"] == 2
    assert preview["provisional_billable_cents"] == 90_000, (
        "both REPORTED events counted at their reported accumulation (2.6 and 3.0 "
        "both >= 2.0 trigger): 2 x 45000")
    assert preview["final_billable_push_count"] == 0
    assert preview["final_billable_cents"] == 0, (
        "no VERIFIED events yet -> the final variant counts nothing")


def test_preview_converges_after_verification(api):
    """PRD §3.7: "the `provisional_billable_push_count` and `provisional_billable_cents` count `REPORTED` and `CHALLENGED` events at their `reported_accumulation_inches` and `VERIFIED` or `CLOSED` events at `verified_accumulation_inches`, while the `final_billable_push_count` and `final_billable_cents` count only `VERIFIED` and `CLOSED` events"
    PRD §3.7: "with the comparison inclusive, so accumulation exactly equal to the trigger is billable" — and below the trigger the visit is NON_BILLABLE.

    Design: Difficulty/dual_variant_calc/provisional_preview_vs_final_invoice_push_billing
    """
    ctx, e1, e2, v1, v2 = _setup_dual_variant_scenario(api)
    _verify_dual_variant_events(e1, e2)

    v1_after = validate_success(api.get_visit(v1["id"], DISPATCH), 200)
    v2_after = validate_success(api.get_visit(v2["id"], DISPATCH), 200)
    assert v1_after["billing_status"] == "BILLABLE_CONFIRMED", "verified 2.6 >= 2.0"
    assert v2_after["billing_status"] == "NON_BILLABLE", "verified 1.4 < 2.0"

    preview = validate_success(
        api.get_billing_preview(ctx["contract"]["id"], DISPATCH), 200)
    assert preview["provisional_billable_cents"] == 45_000, (
        "post-verification the provisional variant uses verified readings: only e1 counts")
    assert preview["final_billable_cents"] == 45_000, "the two variants converge"


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / seasonal_material_actual_vs_normative_min_flip
# ---------------------------------------------------------------------------

def _setup_material_min_flip_scenario(api):
    """SEASONAL contract (salt 25c/blend 60c; site 40000 sqft; salt_included 100);
    one COMPLETED visit with salt 100 + salt 80 + blend 50 applications."""
    ctx = setup_active_seasonal(
        client_name="Harbor Mgmt", seasonal_fee_cents=2_000_000, seasonal_push_cap=5,
        seasonal_overage_rate_cents=40_000, trigger_depth_inches=1.0,
        pavement_area_sqft=40_000, completion_target_minutes=480,
        link_overrides={"salt_included_lbs": 100},
        salt_rate_per_lb_cents=25, blend_rate_per_lb_cents=60,
        brine_rate_per_lb_cents=35)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=3.0)
    visit = setup_completed_visit(ctx, event)
    log_material(visit["id"], "ROCK_SALT", 100.0)
    log_material(visit["id"], "ROCK_SALT", 80.0)
    log_material(visit["id"], "ICE_MELT_BLEND", 50.0)
    return ctx, event, visit


def test_material_settlement_actual_variant_binds(api):
    """PRD §3.9: "`material_actual_cents` is the sum of `line_cost_cents` over all `RECORDED` applications of the contract's season visits, while `material_normative_cents` is the area-normative cap — for each `RECORDED` application, the site's `pavement_area_sqft` times the normative rate for its material (0.0023 pounds per square foot for `ROCK_SALT`, 0.0015 for `ICE_MELT_BLEND`, 0.0040 for `LIQUID_BRINE`) times the application's frozen rate snapshot, rounded half-up per application."
    PRD §3.9: "The prepaid `material_allowance_cents` is the sum over the contract's sites of `salt_included_lbs` times the contract's `salt_rate_per_lb_cents`, rounded half-up per site. `material_settlement_cents` is then the smaller of actual and normative, reduced by the allowance, and never below zero"

    Design: Difficulty/dual_variant_calc/seasonal_material_actual_vs_normative_min_flip
    """
    ctx, event, visit = _setup_material_min_flip_scenario(api)
    preview = validate_success(
        api.get_true_up_preview(ctx["contract"]["id"], DISPATCH), 200)
    assert preview["projected_material_actual_cents"] == 7500, (
        "per-line rounded: 2500 + 2000 + 3000")
    assert preview["projected_material_normative_cents"] == 8200, (
        "round_half_up(40000*0.0023)*25 = 2300 per salt line (x2) "
        "+ round_half_up(40000*0.0015)*60 = 3600 for blend")
    assert preview["projected_material_allowance_cents"] == 2500
    assert preview["projected_material_settlement_cents"] == 5000, (
        "min(7500, 8200) - 2500: the ACTUAL variant binds")


def test_material_settlement_normative_variant_binds_after_large_application(api):
    """PRD §3.9: "`material_settlement_cents` is then the smaller of actual and normative, reduced by the allowance, and never below zero — over-application bills only up to the normative cap, and light application bills only what was logged."

    Design: Difficulty/dual_variant_calc/seasonal_material_actual_vs_normative_min_flip
    """
    ctx, event, visit = _setup_material_min_flip_scenario(api)
    log_material(visit["id"], "ROCK_SALT", 400.0)
    preview = validate_success(
        api.get_true_up_preview(ctx["contract"]["id"], DISPATCH), 200)
    assert preview["projected_material_actual_cents"] == 17_500
    assert preview["projected_material_normative_cents"] == 10_500, (
        "one more salt line adds another normative 2300")
    assert preview["projected_material_settlement_cents"] == 8_000, (
        "min(17500, 10500) - 2500: the min() selection flips to NORMATIVE")


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / hourly_tiered_charge_with_night_premium
# ---------------------------------------------------------------------------

def _setup_hourly_tier_scenario(api):
    """HOURLY contract (12000c/h tier1, 6000c/h tier2, threshold 120 min, premium
    0.25, trigger 1.0). vh2 (08:30-09:30) is created BEFORE vh1 (05:30-07:00);
    both completed; event verifies at 1.6."""
    ctx = setup_active_hourly(
        client_name="Nordic Retail Group", hourly_tier_threshold_minutes=120,
        trigger_depth_inches=1.0, completion_target_minutes=720,
        pavement_area_sqft=30_000)
    set_clock("2026-12-11T04:30:00Z")
    event = setup_storm_event(window_start="2026-12-11T04:00:00Z",
                              window_end="2026-12-11T06:00:00Z",
                              reported_accumulation_inches=1.5)
    vh2 = schedule_visit(event["id"], ctx["contract_site"]["id"],
                         scheduled_start="2026-12-11T08:30:00Z",
                         scheduled_end="2026-12-11T09:30:00Z")
    vh1 = schedule_visit(event["id"], ctx["contract_site"]["id"],
                         scheduled_start="2026-12-11T05:30:00Z",
                         scheduled_end="2026-12-11T07:00:00Z")
    set_clock("2026-12-11T05:30:00Z")
    get_success_data(api.start_visit(vh1["id"], CREW))
    set_clock("2026-12-11T07:00:00Z")
    get_success_data(api.complete_visit(vh1["id"], CREW))
    set_clock("2026-12-11T08:30:00Z")
    get_success_data(api.start_visit(vh2["id"], CREW))
    set_clock("2026-12-11T09:30:00Z")
    get_success_data(api.complete_visit(vh2["id"], CREW))
    post_observation(event["id"], "NOAA", "2026-12-11T05:00:00Z", 1.5)
    post_observation(event["id"], "DTN", "2026-12-11T05:30:00Z", 1.6)
    verify_event(event["id"])
    return ctx, event, vh1, vh2


def test_hourly_night_visit_tier1_with_premium(api):
    """PRD §3.7: "elapsed time from `actual_start_at` to `completed_at` is rounded up to whole six-minute increments to produce `billable_minutes`"
    PRD §3.7: "When the visit's `actual_start_at` hour in UTC is 22, 23, or 0 through 5, `night_premium_applied` is true and the summed base is multiplied by one plus `night_premium_pct`, with the final amount rounded half-up — the premium rounds last."
    PRD §3.7: "Each tier's amount — minutes times rate divided by sixty — is rounded half-up per tier before the two are summed into the base."

    Design: Difficulty/combinatorial_formula/hourly_tiered_charge_with_night_premium
    """
    ctx, event, vh1, _ = _setup_hourly_tier_scenario(api)
    visit = validate_success(api.get_visit(vh1["id"], DISPATCH), 200)
    assert visit["billing_status"] == "BILLABLE_CONFIRMED"
    assert visit["billable_minutes"] == 90
    assert visit["night_premium_applied"] is True, "05:30 UTC is in the night window"
    assert visit["billable_amount_cents"] == 22_500, (
        "90 min all tier-1: round_half_up(90*12000/60)=18000; "
        "premium last: round_half_up(18000*1.25)=22500")


def test_hourly_day_visit_bears_tier2_minutes_chronologically(api):
    """PRD §3.7: "tier allocation is chronological across the season, ordered by `actual_start_at` and then by `created_at` — never by completion order."
    PRD §3.7: "Of the visit's minutes, the portion billed at tier 1 is the headroom remaining under `hourly_tier_threshold_minutes` after accounting for all chronologically earlier billable visits of the contract, never less than zero and never more than the visit's own minutes; the remainder bills at tier 2."

    Design: Difficulty/combinatorial_formula/hourly_tiered_charge_with_night_premium
    """
    ctx, event, vh1, vh2 = _setup_hourly_tier_scenario(api)
    visit = validate_success(api.get_visit(vh2["id"], DISPATCH), 200)
    assert visit["billable_minutes"] == 60
    assert visit["night_premium_applied"] is False
    assert visit["billable_amount_cents"] == 9_000, (
        "vh1 (actual_start 05:30) is chronologically earlier even though vh2 was "
        "created first: prior 90 min -> tier1 min(120-90,60)=30 @200c/min=6000 "
        "+ tier2 30 @100c/min=3000")

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_minutes"] == 150


def test_hourly_contract_season_billable_minutes_sum(api):
    """PRD §3.7: "`season_billable_minutes` sums `billable_minutes` over that same set and feeds hourly tiering"

    Design: Difficulty/combinatorial_formula/hourly_tiered_charge_with_night_premium
    """
    ctx, event, vh1, vh2 = _setup_hourly_tier_scenario(api)
    v1 = validate_success(api.get_visit(vh1["id"], DISPATCH), 200)
    v2 = validate_success(api.get_visit(vh2["id"], DISPATCH), 200)
    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert v1["billable_minutes"] + v2["billable_minutes"] == 150
    assert contract["season_billable_minutes"] == 150


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / material_line_rounding_order_pinned
# ---------------------------------------------------------------------------

def _setup_brine_rounding_scenario(api):
    """PER_PUSH contract (brine rate 35c/lb, trigger 1.0); one COMPLETED visit."""
    ctx = setup_active_per_push(client_name="Summit Offices",
                                trigger_depth_inches=1.0, per_push_rate_cents=45_000,
                                require_photo_verification=False,
                                pavement_area_sqft=12_000,
                                brine_rate_per_lb_cents=35)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=1.5)
    visit = setup_completed_visit(ctx, event)
    return ctx, event, visit


def test_material_line_cost_rounded_half_up_per_line(api):
    """PRD §3.6: "Each application's `line_cost_cents` is its `quantity_lbs` multiplied by that frozen snapshot, rounded half-up to a whole cent per line before any summation"

    Design: Difficulty/combinatorial_formula/material_line_rounding_order_pinned
    """
    _, _, visit = _setup_brine_rounding_scenario(api)
    line = log_material(visit["id"], "LIQUID_BRINE", 1.05)
    assert line["line_cost_cents"] == 37, "round_half_up(1.05 * 35) = round_half_up(36.75) = 37"


def test_visit_material_cost_sums_per_line_rounded_values(api):
    """PRD §3.6: "the visit's `material_cost_cents` is then the sum of `line_cost_cents` over its `RECORDED` rows. The order is pinned — round per line, then sum — because summing first and rounding once yields a different, incorrect result."

    Design: Difficulty/combinatorial_formula/material_line_rounding_order_pinned
    """
    _, _, visit = _setup_brine_rounding_scenario(api)
    for _ in range(3):
        line = log_material(visit["id"], "LIQUID_BRINE", 1.05)
        assert line["line_cost_cents"] == 37
    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["material_cost_cents"] == 111, (
        "3 x round_half_up(36.75) = 111; the sum-then-round alternative (110) is incorrect")


# ---------------------------------------------------------------------------
# Corner/calculations: seasonal true-up literals, settle gate, cap boundary
# ---------------------------------------------------------------------------

def _setup_true_up_literals_scenario(api):
    """SEASONAL contract (fee 2000000, cap 1, overage 40000, penalty 15000);
    site 40000 sqft, salt_included 100 lbs; v1 on-time with salt 100,
    v2 LATE (deadline 16:00, completes 16:30) with salt 80 + blend 50;
    event verified at 2.9; contract expired 2027-01-05."""
    ctx = setup_active_seasonal(
        client_name="TrueUp Co", seasonal_fee_cents=2_000_000, seasonal_push_cap=1,
        seasonal_overage_rate_cents=40_000, trigger_depth_inches=1.0,
        pavement_area_sqft=40_000, completion_target_minutes=480,
        link_overrides={"salt_included_lbs": 100},
        sla_miss_penalty_cents=15_000,
        salt_rate_per_lb_cents=25, blend_rate_per_lb_cents=60,
        brine_rate_per_lb_cents=35)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=3.0)
    v1 = schedule_visit(event["id"], ctx["contract_site"]["id"],
                        scheduled_start="2026-12-10T09:00:00Z",
                        scheduled_end="2026-12-10T10:00:00Z")
    v2 = schedule_visit(event["id"], ctx["contract_site"]["id"],
                        scheduled_start="2026-12-10T11:30:00Z",
                        scheduled_end="2026-12-10T12:30:00Z")
    set_clock("2026-12-10T09:05:00Z")
    get_success_data(api.start_visit(v1["id"], CREW))
    set_clock("2026-12-10T10:00:00Z")
    v1_done = get_success_data(api.complete_visit(v1["id"], CREW))
    log_material(v1["id"], "ROCK_SALT", 100.0)
    set_clock("2026-12-10T11:30:00Z")
    get_success_data(api.start_visit(v2["id"], CREW))
    set_clock("2026-12-10T16:30:00Z")
    v2_done = get_success_data(api.complete_visit(v2["id"], CREW))
    log_material(v2["id"], "ROCK_SALT", 80.0)
    log_material(v2["id"], "ICE_MELT_BLEND", 50.0)
    post_observation(event["id"], "NOAA", "2026-12-10T07:00:00Z", 3.0)
    post_observation(event["id"], "DTN", "2026-12-10T07:30:00Z", 2.9)
    verify_event(event["id"])
    expired = expire_contract_at(ctx["contract"]["id"])
    return ctx, event, v1_done, v2_done, expired


def test_seasonal_true_up_full_settlement_literals(api):
    """PRD §3.5: "`sla_miss` is true when `completed_at` is strictly later than `sla_deadline_at`, and completing exactly at the deadline counts as on time"
    PRD §3.9: "First, the billable set is fixed as the season's visits with billing in `BILLABLE_CONFIRMED`, `INVOICED`, `DISPUTED`, or `SETTLED`, and `billable_push_count` is its size. Second, `overage_pushes` is the count minus `seasonal_push_cap`, floored at zero, and `overage_cents` is that many pushes times `seasonal_overage_rate_cents`."
    PRD §3.9: "Fourth, `performance_credit_cents` is the smaller of the miss count times `sla_miss_penalty_cents` and one fifth of `seasonal_fee_cents` rounded down to a whole cent"
    PRD §3.9: "Sixth and last, `balance_due_cents` is `overage_cents` plus `material_settlement_cents` minus `performance_credit_cents`."

    Design: Corner/calculations/seasonal_true_up_full_settlement_literals
    """
    ctx, event, v1, v2, expired = _setup_true_up_literals_scenario(api)
    assert v1["sla_miss"] is False, "10:00 <= deadline 16:00"
    assert v2["sla_miss"] is True, "16:30 > deadline 16:00"

    true_up = validate_success(api.create_true_up(
        create_true_up_payload(ctx["contract"]["id"], expired["version"]),
        DISPATCH), 201)
    assert true_up["billable_push_count"] == 2
    assert true_up["overage_pushes"] == 1
    assert true_up["overage_cents"] == 40_000
    assert true_up["material_actual_cents"] == 7_500
    assert true_up["material_normative_cents"] == 8_200
    assert true_up["material_allowance_cents"] == 2_500
    assert true_up["material_settlement_cents"] == 5_000
    assert true_up["sla_miss_count"] == 1
    assert true_up["performance_credit_cents"] == 15_000, (
        "min(1*15000, floor(2000000*0.20)=400000)")
    assert true_up["balance_due_cents"] == 30_000, "40000 + 5000 - 15000"


def test_trueup_settle_amount_mismatch_returns_error(api):
    """PRD §3.9: "Settlement moves `ISSUED` to `SETTLED` and is exact: the `settled_amount_cents` presented must equal `balance_due_cents` to the cent, failing as `ERR_SETTLEMENT_MISMATCH`; success stamps `settled_at`"

    Design: Corner/calculations/trueup_settle_amount_mismatch_returns_error
    """
    ctx = setup_active_seasonal(client_name="Settle Co", seasonal_push_cap=2)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit, _ = setup_billable_visit(ctx, event, [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])
    expired = expire_contract_at(ctx["contract"]["id"])
    true_up = validate_success(api.create_true_up(
        create_true_up_payload(ctx["contract"]["id"], expired["version"]),
        DISPATCH), 201)
    assert true_up["balance_due_cents"] == 0, (
        "1 push <= cap 2, no materials, no misses")
    get_success_data(api.issue_true_up(true_up["id"], DISPATCH))

    validate_error(api.settle_true_up(true_up["id"], {"settled_amount_cents": 1},
                                      DISPATCH),
                   ApiErrorId.ERR_SETTLEMENT_MISMATCH)

    settled = validate_success(api.settle_true_up(
        true_up["id"], {"settled_amount_cents": 0}, DISPATCH), 200)
    assert settled["status"] == "SETTLED"


def test_seasonal_cap_boundary_second_push_included_third_overage(api):
    """PRD §3.9: "Second, `overage_pushes` is the count minus `seasonal_push_cap`, floored at zero, and `overage_cents` is that many pushes times `seasonal_overage_rate_cents`."
    PRD §3.7: "`overage_active` — meaningful only for `SEASONAL` — flips true once `season_billable_push_count` exceeds `seasonal_push_cap`."

    Design: Corner/calculations/seasonal_cap_boundary_second_push_included_third_overage
    """
    ctx = setup_active_seasonal(client_name="Cap Co", seasonal_push_cap=2)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=3.0)
    slots = [("09:00", "09:30", "09:02", "09:30"),
             ("11:00", "11:30", "11:00", "11:30"),
             ("13:00", "13:30", "13:00", "13:30")]
    for sched_start, sched_end, start_at, complete_at in slots:
        visit = schedule_visit(event["id"], ctx["contract_site"]["id"],
                               scheduled_start=f"2026-12-10T{sched_start}:00Z",
                               scheduled_end=f"2026-12-10T{sched_end}:00Z")
        set_clock(f"2026-12-10T{start_at}:00Z")
        get_success_data(api.start_visit(visit["id"], CREW))
        set_clock(f"2026-12-10T{complete_at}:00Z")
        get_success_data(api.complete_visit(visit["id"], CREW))
    post_observation(event["id"], "NOAA", "2026-12-10T07:30:00Z", 3.0)
    post_observation(event["id"], "DTN", "2026-12-10T08:00:00Z", 3.1)
    verify_event(event["id"])

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 3
    assert contract["overage_active"] is True, (
        "overage is strict: only the 3rd push crosses cap 2")

    preview = validate_success(
        api.get_true_up_preview(ctx["contract"]["id"], DISPATCH), 200)
    assert preview["projected_overage_pushes"] == 1, (
        "the cap-th (2nd) push is included in the fee; only the 3rd bills")
    assert preview["projected_overage_cents"] == 40_000


def test_material_zero_quantity_rejected(api):
    """PRD §3.6: "Logging an application — by the `CrewLead` of an in-house visit or the assigned `Subcontractor` — names the `visit_id`, a `material_type` of `ROCK_SALT`, `ICE_MELT_BLEND`, or `LIQUID_BRINE`, and a `quantity_lbs` at two decimal places that must be strictly greater than zero, failing as `ERR_INVALID_QUANTITY`."
    PRD §2.6: "Wherever a multiplication produces a fractional cent, the result is rounded half-up to a whole cent"

    Design: Corner/validations/material_zero_quantity_rejected
    """
    ctx = setup_active_per_push(client_name="Quantity Co",
                                require_photo_verification=False)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"])
    set_clock("2026-12-10T09:05:00Z")
    get_success_data(api.start_visit(visit["id"], CREW))

    validate_error(api.create_material(
        create_material_payload(visit["id"], "ROCK_SALT", 0), CREW),
        ApiErrorId.ERR_INVALID_QUANTITY)

    line = validate_success(api.create_material(
        create_material_payload(visit["id"], "ROCK_SALT", 0.01), CREW), 201)
    assert line["line_cost_cents"] == 0, "round_half_up(0.01 * 25) = 0"
