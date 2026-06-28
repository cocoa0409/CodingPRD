"""Dual-variant and combinatorial calculations: session-pack settle vs
provisional, macro plan provisional-vs-locked, the non-linear macro formula,
the round-per-line invoice, the weighted adherence score, and the subscription
proration.

Depth (queue A): dual_variant_calc, combinatorial_formula.
Breadth (queue B): calculations section.
"""
from test_helpers import (
    validate_success, validate_paginated,
    api_client,
    set_clock, create_trainer, create_assessed_client, create_engagement,
    create_pack, get_pack, book_pack_session,
    setup_pack_engagement, setup_subscription_engagement, setup_session_pack_engagement,
    setup_client_with_assessed_weight, setup_provisional_macro_plan,
    create_macro_plan, create_published_program, log_habit,
    submit_check_in, assess_check_in,
    create_check_in_payload, invoice_payload,
    make_trainer_headers, make_client_headers,
)


# ─── dual_variant_calc / session_pack_settle_vs_provisional_balance ──────────

def test_engagement_end_refunds_unused_seats_not_naive_remaining(api):
    """PRD §3.3: "At settlement only seats that were truly consumed — those in
    `COMPLETED`, `NO_SHOW`, or `LATE_CANCELLED` — count against the pack; any seat
    still merely `BOOKED` is treated as unused and refunded."
    PRD §3.3: "The refund added to `wallet_credit_cents` is the number of unused
    seats (the pack's `total_sessions` minus the count of truly consumed seats)
    multiplied by `per_session_value_cents`."

    Pack of 5 @ 10000/seat with one COMPLETED + one still-BOOKED booking settles
    as 4 unused seats * 10000 = 40000, not the naive provisional 3-remaining
    (30000); the BOOKED seat is refunded.

    Design: Difficulty/dual_variant_calc/session_pack_settle_vs_provisional_balance
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    b1 = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                           "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    p_after = get_pack(t_id, pack["id"])
    b2 = book_pack_session(t_id, e_id, pack["id"], p_after["version"],
                           "2026-06-03T10:00:00Z", "2026-06-03T11:00:00Z")
    set_clock("2026-06-02T11:30:00Z")
    validate_success(api.complete_booking(b1["id"], make_trainer_headers(t_id)))

    eng = validate_success(api.end_engagement(e_id, make_trainer_headers(t_id)))
    assert eng["wallet_credit_cents"] == 40000, (
        f"expected 40000 refund, got {eng['wallet_credit_cents']}")
    assert eng["status"] == "ENDED"
    refreshed_pack = get_pack(t_id, pack["id"])
    assert refreshed_pack["status"] == "REFUNDED"
    b2_final = validate_success(api.get_booking(b2["id"], make_trainer_headers(t_id)))
    assert b2_final["status"] == "CANCELLED"


def test_engagement_end_settles_session_pack_to_refunded(api):
    """PRD §3.3: "Because outstanding `BOOKED` seats are refunded rather than
    counted as committed, this settled refund deliberately diverges from the live
    `sessions_remaining` figure whenever such seats exist, and the pack then moves
    to `REFUNDED`."

    The settled view diverges from live sessions_remaining (which would have been
    3 with one COMPLETED + one BOOKED seat against 5); settlement refunds 4 seats.

    Design: Difficulty/dual_variant_calc/session_pack_settle_vs_provisional_balance
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    b1 = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                           "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    p_after = get_pack(t_id, pack["id"])
    book_pack_session(t_id, e_id, pack["id"], p_after["version"],
                      "2026-06-03T10:00:00Z", "2026-06-03T11:00:00Z")
    # live sessions_remaining is 3 (two seats committed) before end.
    live = get_pack(t_id, pack["id"])
    assert live["sessions_remaining"] == 3
    set_clock("2026-06-02T11:30:00Z")
    validate_success(api.complete_booking(b1["id"], make_trainer_headers(t_id)))

    eng = validate_success(api.end_engagement(e_id, make_trainer_headers(t_id)))
    # divergence: settled refund (40000 = 4 seats) != live-remaining naive (30000).
    assert eng["wallet_credit_cents"] == 40000
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["status"] == "REFUNDED"


# ─── dual_variant_calc / macro_targets_provisional_vs_locked ────────────────

def test_provisional_macro_recomputes_on_new_assessed_checkin(api):
    """PRD §3.7: "While the plan is `PROVISIONAL`, these numbers are an estimate
    that is recomputed from the client's `latest_weight_kg` every time a check-in
    is assessed, so the same plan yields different targets as the client's weight
    changes."

    A PROVISIONAL FAT_LOSS/MODERATE plan (male, age 30, 180cm) computed at weight
    80 (2207) recomputes to 2182 after a later assessed check-in at weight 78.

    Design: Difficulty/dual_variant_calc/macro_targets_provisional_vs_locked
    """
    ctx = setup_provisional_macro_plan(clock_utc="2026-06-01T00:00:00Z",
                                       weight_kg=80, goal="FAT_LOSS",
                                       activity_level="MODERATE",
                                       client_overrides={"sex": "MALE",
                                                         "birth_year": 1996,
                                                         "height_cm": 180})
    t_id, c_id, e_id, mp = (ctx["trainer"]["id"], ctx["client"]["id"],
                            ctx["engagement"]["id"], ctx["macro_plan"])
    assert mp["target_calories"] == 2207

    ci2 = submit_check_in(c_id, e_id, "2026-06-08T08:00:00Z", 78,
                          "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    assess_check_in(t_id, ci2["id"])

    refreshed = validate_success(api.get_macro_plan(mp["id"], make_trainer_headers(t_id)))
    assert refreshed["target_calories"] == 2182, (
        f"expected recomputed 2182, got {refreshed['target_calories']}")
    assert refreshed["status"] == "PROVISIONAL"
    client = validate_success(api.get_client(c_id, make_trainer_headers(t_id)))
    assert client["latest_weight_kg"] == 78


def test_locked_macro_plan_does_not_recompute_on_later_checkin(api):
    """PRD §3.7: "Locking the plan moves `status` from `PROVISIONAL` to the
    terminal `LOCKED`, which requires the plan to be `PROVISIONAL` (otherwise
    `ERR_INVALID_STATE`) and freezes `target_calories`, `protein_g`, `carb_g`, and
    `fat_g` so that later check-ins no longer recompute them."

    A plan locked at 2207 stays 2207 after a later assessed check-in at weight 78,
    the locked counterpart to the provisional-recompute path.

    Design: Difficulty/dual_variant_calc/macro_targets_provisional_vs_locked
    """
    ctx = setup_provisional_macro_plan(clock_utc="2026-06-01T00:00:00Z",
                                       weight_kg=80, goal="FAT_LOSS",
                                       activity_level="MODERATE",
                                       client_overrides={"sex": "MALE",
                                                         "birth_year": 1996,
                                                         "height_cm": 180})
    t_id, c_id, e_id, mp = (ctx["trainer"]["id"], ctx["client"]["id"],
                            ctx["engagement"]["id"], ctx["macro_plan"])
    assert mp["target_calories"] == 2207
    validate_success(api.lock_macro_plan(mp["id"], make_trainer_headers(t_id)))

    ci2 = submit_check_in(c_id, e_id, "2026-06-08T08:00:00Z", 78,
                          "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    assess_check_in(t_id, ci2["id"])

    refreshed = validate_success(api.get_macro_plan(mp["id"], make_trainer_headers(t_id)))
    assert refreshed["target_calories"] == 2207, (
        f"locked plan must stay 2207, got {refreshed['target_calories']}")
    assert refreshed["status"] == "LOCKED"


# ─── combinatorial_formula / macro_plan_nonlinear_multiinput ────────────────

def test_macro_plan_male_fat_loss_full_split(api):
    """PRD §3.7: "for a `MALE` client it is ten times the weight in kilograms,
    plus 6.25 times the height in centimeters, minus five times the age, plus
    five"
    PRD §3.7: "for `FAT_LOSS` it is the expenditure reduced by 20 percent
    (multiplied by 0.80)"
    PRD §3.7: "Thus `protein_g` is the target calories times the protein fraction
    divided by four, `carb_g` is the target calories times the carbohydrate
    fraction divided by four, and `fat_g` is the target calories times the fat
    fraction divided by nine — each rounded half-up to a whole gram."

    Male/80kg/180cm/age30/MODERATE(1.55)/FAT_LOSS yields 2207 kcal and a
    221p/166c/74f split.

    Design: Difficulty/combinatorial_formula/macro_plan_nonlinear_multiinput
    """
    ctx = setup_client_with_assessed_weight(clock_utc="2026-06-01T00:00:00Z",
                                            billing_model="ONLINE_SUBSCRIPTION",
                                            weight_kg=80,
                                            client_overrides={"sex": "MALE",
                                                              "birth_year": 1996,
                                                              "height_cm": 180})
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    mp = create_macro_plan(t_id, e_id, goal="FAT_LOSS", activity_level="MODERATE")
    assert mp["target_calories"] == 2207, f"got {mp['target_calories']}"
    assert mp["protein_g"] == 221, f"got {mp['protein_g']}"
    assert mp["carb_g"] == 166, f"got {mp['carb_g']}"
    assert mp["fat_g"] == 74, f"got {mp['fat_g']}"


def test_macro_plan_female_muscle_gain_sedentary_variant(api):
    """PRD §3.7: "for a `FEMALE` client it is the same expression but minus 161 at
    the end instead of plus five."
    PRD §3.7: "total daily energy expenditure is the basal rate multiplied by the
    activity multiplier — 1.2 for `SEDENTARY`, 1.55 for `MODERATE`, or 1.725 for
    `ACTIVE`."
    PRD §3.7: "for `MUSCLE_GAIN` it is the expenditure increased by 10 percent
    (multiplied by 1.10), with the result rounded half-up to a whole calorie."

    Female/65kg/168cm/age28/SEDENTARY(1.2)/MUSCLE_GAIN(+10%) yields 1847 kcal,
    distinct from the male FAT_LOSS branch.

    Design: Difficulty/combinatorial_formula/macro_plan_nonlinear_multiinput
    """
    ctx = setup_client_with_assessed_weight(clock_utc="2026-06-01T00:00:00Z",
                                            billing_model="ONLINE_SUBSCRIPTION",
                                            weight_kg=65,
                                            client_overrides={"sex": "FEMALE",
                                                              "birth_year": 1998,
                                                              "height_cm": 168})
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    mp = create_macro_plan(t_id, e_id, goal="MUSCLE_GAIN", activity_level="SEDENTARY")
    assert mp["target_calories"] == 1847, f"got {mp['target_calories']}"


# ─── combinatorial_formula / invoice_round_per_line_then_sum ────────────────

def test_invoice_rounds_per_line_then_sums_then_taxes(api):
    """PRD §3.3: "first each line's net is computed as its list price multiplied by
    one minus that line's discount fraction, rounded half-up to a whole cent; then
    those rounded line nets are summed to produce `subtotal_cents`; then tax is
    computed as the subtotal multiplied by the tax rate of 8.75 percent (0.0875),
    again rounded half-up to a whole cent, yielding `tax_cents`; and finally
    `invoice_total_cents` is the subtotal plus the tax."
    PRD §3.3: "three lines each listing 201 cents at a 50 percent discount round to
    101 per line and sum to a subtotal of 303 (not 302), giving a total of 330
    (not 328)."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum
    """
    ctx = setup_session_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                        client_overrides={"sex": "FEMALE",
                                                          "birth_year": 1998,
                                                          "height_cm": 168})
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    lines = [{"list_price_cents": 201, "discount_pct": 0.50},
             {"list_price_cents": 201, "discount_pct": 0.50},
             {"list_price_cents": 201, "discount_pct": 0.50}]
    resp = api.session_pack_invoice(e_id, invoice_payload(lines), make_trainer_headers(t_id))
    data = validate_success(resp, 200)
    assert data["subtotal_cents"] == 303, f"got {data['subtotal_cents']}"
    assert data["tax_cents"] == 27, f"got {data['tax_cents']}"
    assert data["invoice_total_cents"] == 330, f"got {data['invoice_total_cents']}"


def test_invoice_total_diverges_from_sum_then_round(api):
    """PRD §3.3: "Rounding each line before summing — rather than summing raw
    amounts and rounding once at the end — is required, because the two orders
    genuinely diverge: three lines each listing 201 cents at a 50 percent discount
    round to 101 per line and sum to a subtotal of 303 (not 302), giving a total of
    330 (not 328)."

    The pinned order yields 330, never the sum-then-round 328.

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum
    """
    ctx = setup_session_pack_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    lines = [{"list_price_cents": 201, "discount_pct": 0.50},
             {"list_price_cents": 201, "discount_pct": 0.50},
             {"list_price_cents": 201, "discount_pct": 0.50}]
    data = validate_success(
        api.session_pack_invoice(e_id, invoice_payload(lines), make_trainer_headers(t_id)), 200)
    assert data["invoice_total_cents"] == 330
    assert data["invoice_total_cents"] != 328


# ─── Corner: calculations / subscription_midcycle_refund_correct ─────────────

def test_subscription_midcycle_end_prorates_refund(api):
    """PRD §3.7: "The refund in cents is `monthly_fee_cents` multiplied by the
    remaining days divided by the cycle length, rounded half-up to a whole cent,
    and that amount is added to the engagement's `wallet_credit_cents` as part of
    the end cascade."
    PRD §3.7: "The elapsed days are the time from the cycle start to the logical
    clock, divided by one day and rounded down to a whole day."

    Ending at day 10 of a 30-day cycle (fee 6000) refunds round_half_up(6000*20/30)
    = 4000.

    Design: Corner/calculations/subscription_midcycle_refund_correct
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z",
                                        monthly_fee_cents=6000,
                                        cycle_start_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    set_clock("2026-06-11T00:00:00Z")
    eng = validate_success(api.end_engagement(e_id, make_trainer_headers(t_id)))
    assert eng["wallet_credit_cents"] == 4000, f"got {eng['wallet_credit_cents']}"
    assert eng["status"] == "ENDED"


# ─── Corner: calculations / adherence_weighted_score_correct ─────────────────

def test_adherence_weighted_score_blends_three_ratios(api):
    """PRD §3.6: "These three ratios are kept at full precision and combined with
    weights of 0.50 for workouts, 0.30 for nutrition, and 0.20 for habits; the
    weighted blend is multiplied by 100 and rounded half-up to a single integer
    exactly once at the very end."
    PRD §3.6: "The workout ratio is the count of `WORKOUT_COMPLETED` logs in the
    window divided by that planned-workout figure, capped at 1."

    Window 7d, planned 4 workouts; 3 workouts, 5 distinct nutrition days, 6 habit
    checks (target 10) -> round_half_up(100*(0.5*0.75 + 0.3*(5/7) + 0.2*0.6)) = 71.

    Design: Corner/calculations/adherence_weighted_score_correct
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    prog = create_published_program(t_id, e_id, planned_workouts_per_week=4,
                                    habit_checks_target=10)
    p_id = prog["id"]
    for day in ("2026-06-01", "2026-06-02", "2026-06-03"):
        log_habit(c_id, e_id, p_id, "WORKOUT_COMPLETED", f"{day}T07:00:00Z")
    for day in ("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"):
        log_habit(c_id, e_id, p_id, "NUTRITION_LOGGED", f"{day}T12:00:00Z")
    for day in ("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-06"):
        log_habit(c_id, e_id, p_id, "HABIT_CHECK", f"{day}T20:00:00Z")

    ci = submit_check_in(c_id, e_id, "2026-06-08T08:00:00Z", 78,
                         "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    assert ci["adherence_score"] == 71, f"got {ci['adherence_score']}"


# ─── Corner: calculations / macro_female_muscle_gain_variant ─────────────────

def test_macro_female_muscle_gain_sedentary_constant_application(api):
    """PRD §3.7: "for a `FEMALE` client it is the same expression but minus 161 at
    the end instead of plus five."
    PRD §3.7: "total daily energy expenditure is the basal rate multiplied by the
    activity multiplier — 1.2 for `SEDENTARY`, 1.55 for `MODERATE`, or 1.725 for
    `ACTIVE`."

    Female/65kg/168cm/age28/SEDENTARY/MUSCLE_GAIN -> 1847 kcal.

    Design: Corner/calculations/macro_female_muscle_gain_variant
    """
    ctx = setup_client_with_assessed_weight(clock_utc="2026-06-01T00:00:00Z",
                                            billing_model="ONLINE_SUBSCRIPTION",
                                            weight_kg=65,
                                            client_overrides={"sex": "FEMALE",
                                                              "birth_year": 1998,
                                                              "height_cm": 168})
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    mp = create_macro_plan(t_id, e_id, goal="MUSCLE_GAIN", activity_level="SEDENTARY")
    assert mp["target_calories"] == 1847, f"got {mp['target_calories']}"


# ─── Corner: calculations / macro_locked_freezes_on_later_checkin ────────────

def test_macro_locked_freezes_value_after_later_checkin(api):
    """PRD §3.7: "freezes `target_calories`, `protein_g`, `carb_g`, and `fat_g` so
    that later check-ins no longer recompute them."
    PRD §3.7: "a locked plan and a provisional plan that started from identical
    inputs can diverge after a subsequent check-in."

    A plan locked at 2207 stays 2207 after a later assessed check-in at weight 78.

    Design: Corner/calculations/macro_locked_freezes_on_later_checkin
    """
    ctx = setup_provisional_macro_plan(clock_utc="2026-06-01T00:00:00Z",
                                       weight_kg=80, goal="FAT_LOSS",
                                       activity_level="MODERATE",
                                       client_overrides={"sex": "MALE",
                                                         "birth_year": 1996,
                                                         "height_cm": 180})
    t_id, c_id, e_id, mp = (ctx["trainer"]["id"], ctx["client"]["id"],
                            ctx["engagement"]["id"], ctx["macro_plan"])
    validate_success(api.lock_macro_plan(mp["id"], make_trainer_headers(t_id)))
    ci2 = submit_check_in(c_id, e_id, "2026-06-08T08:00:00Z", 78,
                          "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    assess_check_in(t_id, ci2["id"])
    refreshed = validate_success(api.get_macro_plan(mp["id"], make_trainer_headers(t_id)))
    assert refreshed["target_calories"] == 2207
    assert refreshed["status"] == "LOCKED"


# ─── Corner: entities / per_session_value_computed_on_pack_create ────────────

def test_per_session_value_computed_on_pack_create(api):
    """PRD §3.3: "At creation the system records the pack's `per_session_value_cents`
    as the price divided by the number of sessions, rounded half-up to a whole
    cent; this per-session value is what drives both no-show fees and
    end-of-engagement refunds."

    80000/10 -> 8000, sessions_remaining starts at total_sessions (10).

    Design: Corner/entities/per_session_value_computed_on_pack_create
    """
    ctx = setup_session_pack_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    pack = create_pack(t_id, e_id, total_sessions=10, price_cents=80000)
    assert pack["per_session_value_cents"] == 8000, f"got {pack['per_session_value_cents']}"
    assert pack["sessions_remaining"] == 10
