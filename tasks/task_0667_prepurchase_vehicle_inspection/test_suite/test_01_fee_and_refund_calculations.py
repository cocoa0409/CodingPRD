"""Fee estimation, late-credit reconciliation, VIN risk scoring, condition
scoring, and dispute-refund waterfall calculations.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, boundary_precision_check.
Queue B (Corner): calculations section.
"""
from test_helpers import (
    api_client, validate_success,
    setup_delivered_order, setup_dispute, set_clock,
    create_fee_schedule, create_account, create_vehicle, create_inspector,
    create_draft_order, offer_assignment, create_reported_order,
    create_report_for, add_photo, compile_vin_report,
    add_history_record, create_recall, create_dispatched_order,
    make_inspector_headers,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]


# ===========================================================================
# dual_variant_calc — fee_estimated vs fee_final late credit (Queue A)
# ===========================================================================
def test_late_delivery_credits_entire_rush_surcharge(api):
    """PRD §3.7: "When the delivery is late, the entire rush surcharge is
    credited back because the customer paid for speed that was not delivered,
    so `fee_total_cents` equals the subtotal alone - strictly less than the
    estimate whenever the rush tier is not `NONE`."

    Design: Difficulty/dual_variant_calc/fee_estimated_vs_final_late_credit_on_order
    """
    ctx = setup_delivered_order(
        fee_overrides={"tier_code": "PREMIUM", "base_fee_cents": 25000,
                       "vin_history_fee_cents": 4000, "per_mile_dispatch_cents": 150},
        account_overrides={"account_type": "DEALER", "net_terms_days": 30, "rush_discount_pct": 0.10},
        inspector_overrides={"certified_tiers": ["PREMIUM"]},
        order_overrides={"include_vin_history": True, "rush_tier": "EXPRESS"},
        asg_overrides={"dispatch_miles": 40},
        ordered_at="2026-06-01T00:00:00Z",
        delivered_at="2026-06-05T00:00:00Z",  # past 48h EXPRESS deadline
        pay=True,
    )
    delivered = ctx["delivered_order"]
    assert delivered["estimated_fee_cents"] == 41300
    assert delivered["fee_total_cents"] == 35000
    assert delivered["late_delivery"] is True


def test_on_time_final_fee_equals_estimated(api):
    """PRD §3.7: "When the delivery is on time, `fee_total_cents` equals the
    subtotal plus the discounted rush surcharge, which matches
    `estimated_fee_cents`."

    Design: Difficulty/dual_variant_calc/fee_estimated_vs_final_late_credit_on_order
    """
    ctx = setup_delivered_order(
        fee_overrides={"tier_code": "PREMIUM", "base_fee_cents": 25000,
                       "vin_history_fee_cents": 4000, "per_mile_dispatch_cents": 150},
        account_overrides={"account_type": "DEALER", "net_terms_days": 30, "rush_discount_pct": 0.10},
        inspector_overrides={"certified_tiers": ["PREMIUM"]},
        order_overrides={"include_vin_history": True, "rush_tier": "EXPRESS"},
        asg_overrides={"dispatch_miles": 40},
        ordered_at="2026-06-01T00:00:00Z",
        delivered_at="2026-06-02T12:00:00Z",  # within 48h EXPRESS deadline
        pay=True,
    )
    delivered = ctx["delivered_order"]
    assert delivered["estimated_fee_cents"] == 41300
    assert delivered["fee_total_cents"] == 41300
    assert delivered["late_delivery"] is False


# ===========================================================================
# dual_variant_calc — vin_risk clean vs branded (Queue A)
# ===========================================================================
def _seed_branded_vehicle(veh_id):
    add_history_record(veh_id, "BRANDING", "2021-05-01T00:00:00Z", branding_code="SALVAGE")
    add_history_record(veh_id, "TITLE", "2019-01-01T00:00:00Z", title_state="CA")
    add_history_record(veh_id, "TITLE", "2020-01-01T00:00:00Z", title_state="NV")
    add_history_record(veh_id, "TITLE", "2021-06-01T00:00:00Z", title_state="TX")
    add_history_record(veh_id, "ODOMETER", "2020-02-01T00:00:00Z", odometer_value=50000)
    add_history_record(veh_id, "ODOMETER", "2021-02-01T00:00:00Z", odometer_value=49800)


def test_branded_vehicle_risk_score_clamps_to_100(api):
    """PRD §3.6: "The `risk_score` is the sum of branding, owner-churn, rollback,
    and recall points, with the total capped at 100."

    Design: Difficulty/dual_variant_calc/vin_risk_clean_vs_branded_on_vehicle
    """
    fs = create_fee_schedule(tier_code="STANDARD", base_fee_cents=15000,
                             vin_history_fee_cents=3000, per_mile_dispatch_cents=100)
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2018, make="Toyota", model="Corolla")
    _seed_branded_vehicle(veh["id"])
    create_recall(2018, "Toyota", "Corolla", campaign_id="RC-1", severity="HIGH")
    create_recall(2018, "Toyota", "Corolla", campaign_id="RC-2", severity="MEDIUM")
    order = create_draft_order(acct, veh, fs, include_vin_history=True, rush_tier="NONE")

    vr = validate_success(api.create_vin_report({"order_id": order["id"]}, OPS), 201)
    assert vr["worst_branding"] == "SALVAGE"
    assert vr["title_count"] == 3
    assert vr["odometer_rollback"] is True
    assert vr["open_recall_count"] == 2
    assert vr["risk_score"] == 100


def test_branded_worst_branding_is_most_severe(api):
    """PRD §3.6: "`worst_branding` is the most severe `branding_code` across the
    vehicle's `BRANDING` records, taken by a severity rank where `NONE` ranks 0,
    `REBUILT` 1, `FLOOD` 2, `SALVAGE` 3, and `LEMON` 4."

    Design: Difficulty/dual_variant_calc/vin_risk_clean_vs_branded_on_vehicle
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2018, make="Toyota", model="Corolla")
    _seed_branded_vehicle(veh["id"])
    create_recall(2018, "Toyota", "Corolla", campaign_id="RC-1", severity="HIGH")
    create_recall(2018, "Toyota", "Corolla", campaign_id="RC-2", severity="MEDIUM")
    order = create_draft_order(acct, veh, fs, include_vin_history=True, rush_tier="NONE")

    vr = validate_success(api.create_vin_report({"order_id": order["id"]}, OPS), 201)
    assert vr["worst_branding"] == "SALVAGE"
    assert vr["open_recall_count"] == 2


# ===========================================================================
# combinatorial_formula — condition_score multi-input non-linear (Queue A)
# ===========================================================================
def test_condition_score_critical_photo_forces_fail(api):
    """PRD §3.5: "The `outcome` is then derived from the rounded score and the
    critical count: if there is at least one critical photo, or the score is
    below 50, the outcome is `FAIL`; otherwise, if the score is below 80, the
    outcome is `CONDITIONAL`; otherwise the outcome is `PASS`."

    Design: Difficulty/combinatorial_formula/condition_score_multi_input_nonlinear
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle()
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)
    report = create_report_for(order, asg, points_total=100, points_failed=5, road_test_done=True)
    add_photo(report, insp["id"], caption="cracked frame", is_critical=True, url="http://x/1.jpg")

    submitted = validate_success(api.submit_report(report["id"], make_inspector_headers(insp["id"])), 200)
    assert submitted["condition_score"] == 85.0
    assert submitted["outcome"] == "FAIL"


def test_condition_score_critical_penalty_applied(api):
    """PRD §3.5: "the critical penalty is 15 points per critical photo, capped at
    40 points. The `condition_score` is the raw score plus the road-test bonus
    minus the critical penalty, then clamped to lie between 0 and 100, and
    rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/condition_score_multi_input_nonlinear
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle()
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)
    report = create_report_for(order, asg, points_total=100, points_failed=5, road_test_done=True)
    add_photo(report, insp["id"], caption="cracked frame", is_critical=True, url="http://x/1.jpg")

    submitted = validate_success(api.submit_report(report["id"], make_inspector_headers(insp["id"])), 200)
    # raw 95 + road-test 5 - critical 15 = 85.0
    assert submitted["condition_score"] == 85.0


# ===========================================================================
# combinatorial_formula — dispute_refund pinned eval order (Queue A)
# ===========================================================================
def test_missed_defect_refund_caps_at_half_fee(api):
    """PRD §3.8: "The reason cap depends on the dispute reason: for
    `MISSED_DEFECT` it is the floor of half the `fee_total_cents`; for
    `LATE_DELIVERY` it is the rush surcharge that was actually billed (which is
    0 when the order was already late-credited, since no surcharge was charged);
    and for `WRONG_VEHICLE` it is the full `fee_total_cents`."

    Design: Difficulty/combinatorial_formula/dispute_refund_pinned_eval_order
    """
    ctx = setup_delivered_order(
        fee_overrides={"tier_code": "PREMIUM", "base_fee_cents": 25000,
                       "vin_history_fee_cents": 4000, "per_mile_dispatch_cents": 150},
        account_overrides={"account_type": "DEALER", "net_terms_days": 30, "rush_discount_pct": 0.10},
        inspector_overrides={"certified_tiers": ["PREMIUM"]},
        order_overrides={"include_vin_history": True, "rush_tier": "EXPRESS"},
        asg_overrides={"dispatch_miles": 40},
        ordered_at="2026-06-01T00:00:00Z",
        delivered_at="2026-06-02T12:00:00Z",  # on time -> fee_total 41300
        pay=True,
    )
    order = ctx["delivered_order"]
    assert order["fee_total_cents"] == 41300
    dispute = setup_dispute("MISSED_DEFECT", 30000, ctx["account"]["id"], order, ctx["report"])

    resolved = validate_success(api.resolve_dispute(dispute["id"], OPS), 200)
    assert resolved["approved_cents"] == 20650  # floor(41300 * 0.50)
    refreshed = validate_success(api.get_order(order["id"], OPS), 200)
    assert refreshed["refunded_cents"] == 20650
    assert refreshed["payment_status"] == "REFUNDED"


def test_missed_defect_refund_smaller_claim_wins(api):
    """PRD §3.8: "The `approved_cents` is the smallest of the `claimed_cents`,
    the reason cap, and the refundable ceiling, and is never negative."

    Design: Difficulty/combinatorial_formula/dispute_refund_pinned_eval_order
    """
    ctx = setup_delivered_order(
        fee_overrides={"tier_code": "PREMIUM", "base_fee_cents": 25000,
                       "vin_history_fee_cents": 4000, "per_mile_dispatch_cents": 150},
        account_overrides={"account_type": "DEALER", "net_terms_days": 30, "rush_discount_pct": 0.10},
        inspector_overrides={"certified_tiers": ["PREMIUM"]},
        order_overrides={"include_vin_history": True, "rush_tier": "EXPRESS"},
        asg_overrides={"dispatch_miles": 40},
        ordered_at="2026-06-01T00:00:00Z",
        delivered_at="2026-06-02T12:00:00Z",
        pay=True,
    )
    order = ctx["delivered_order"]
    assert order["fee_total_cents"] == 41300
    # claimed 5000 < cap 20650 < ceiling 41300 -> claimed wins
    dispute = setup_dispute("MISSED_DEFECT", 5000, ctx["account"]["id"], order, ctx["report"])

    resolved = validate_success(api.resolve_dispute(dispute["id"], OPS), 200)
    assert resolved["approved_cents"] == 5000


# ===========================================================================
# boundary_precision_check — condition_score exactly 50 (Queue A)
# ===========================================================================
def test_condition_score_exactly_50_is_conditional(api):
    """PRD §3.5: "A score of exactly 50 is not a fail, and a score of exactly 80
    is a pass."

    Design: Difficulty/boundary_precision_check/condition_score_exact_50_is_conditional_not_fail
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle()
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)
    report = create_report_for(order, asg, points_total=100, points_failed=50, road_test_done=False)

    submitted = validate_success(api.submit_report(report["id"], make_inspector_headers(insp["id"])), 200)
    assert submitted["condition_score"] == 50.0
    assert submitted["outcome"] == "CONDITIONAL"


def test_condition_score_exactly_50_not_fail_outcome(api):
    """PRD §3.5: "if there is at least one critical photo, or the score is below
    50, the outcome is `FAIL`."

    Design: Difficulty/boundary_precision_check/condition_score_exact_50_is_conditional_not_fail
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle()
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)
    report = create_report_for(order, asg, points_total=100, points_failed=50, road_test_done=False)

    submitted = validate_success(api.submit_report(report["id"], make_inspector_headers(insp["id"])), 200)
    assert submitted["outcome"] != "FAIL"


# ===========================================================================
# boundary_precision_check — odometer rollback exactly 100 gap (Queue A)
# ===========================================================================
def test_odometer_gap_exactly_100_does_not_flag_rollback(api):
    """PRD §3.6: "The comparison is strict: a reading must be more than 100 miles
    below the running maximum to flag a rollback, so a reading exactly 100 miles
    below does not flag."

    Design: Difficulty/boundary_precision_check/odometer_rollback_exact_100_gap_does_not_flag
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2014, make="Hyundai", model="Elantra")
    add_history_record(veh["id"], "ODOMETER", "2020-01-01T00:00:00Z", odometer_value=50000)
    add_history_record(veh["id"], "ODOMETER", "2021-01-01T00:00:00Z", odometer_value=49900)
    order = create_draft_order(acct, veh, fs, include_vin_history=True, rush_tier="NONE")

    vr = validate_success(api.create_vin_report({"order_id": order["id"]}, OPS), 201)
    assert vr["odometer_rollback"] is False


def test_odometer_gap_above_100_flags_rollback(api):
    """PRD §3.6: "the flag is set to true if any later reading is lower than the
    running maximum by more than a tolerance of 100 miles."

    Design: Difficulty/boundary_precision_check/odometer_rollback_exact_100_gap_does_not_flag
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2014, make="Hyundai", model="Elantra")
    add_history_record(veh["id"], "ODOMETER", "2020-01-01T00:00:00Z", odometer_value=50000)
    add_history_record(veh["id"], "ODOMETER", "2021-01-01T00:00:00Z", odometer_value=49899)  # gap 101
    order = create_draft_order(acct, veh, fs, include_vin_history=True, rush_tier="NONE")

    vr = validate_success(api.create_vin_report({"order_id": order["id"]}, OPS), 201)
    assert vr["odometer_rollback"] is True


# ===========================================================================
# Queue B — calculations corner instances
# ===========================================================================
def test_estimated_fee_requoted_on_dispatch_with_miles(api):
    """PRD §3.4: "creating it records the order's `dispatch_miles`, re-quotes
    `estimated_fee_cents`, and increments the order's `version`."

    Design: Corner/calculations/fee_estimated_requote_on_dispatch_with_miles
    """
    set_clock("2026-06-01T00:00:00Z")
    fs = create_fee_schedule(tier_code="PREMIUM", base_fee_cents=25000,
                             vin_history_fee_cents=4000, per_mile_dispatch_cents=150)
    acct = create_account(account_type="DEALER", net_terms_days=30, rush_discount_pct=0.10)
    veh = create_vehicle()
    insp = create_inspector(certified_tiers=["PREMIUM"])
    order = create_draft_order(acct, veh, fs, include_vin_history=True, rush_tier="EXPRESS")

    offer_assignment(order, insp, dispatch_miles=40)
    refreshed = validate_success(api.get_order(order["id"], OPS), 200)
    assert refreshed["estimated_fee_cents"] == 41300


def test_vin_clean_title_risk_score_17(api):
    """PRD §3.6: "The owner-churn points are the `title_count` capped at 5,
    multiplied by 6." "The recall points are the `open_recall_count` capped at 3,
    multiplied by 5."

    Design: Corner/calculations/vin_risk_clean_title_score_17
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2018, make="Toyota", model="Prius")
    add_history_record(veh["id"], "TITLE", "2018-01-01T00:00:00Z", title_state="CA")
    add_history_record(veh["id"], "TITLE", "2020-01-01T00:00:00Z", title_state="OR")
    add_history_record(veh["id"], "ODOMETER", "2020-06-01T00:00:00Z", odometer_value=40000)
    create_recall(2018, "Toyota", "Prius", campaign_id="RC-9", severity="LOW")
    order = create_draft_order(acct, veh, fs, include_vin_history=True, rush_tier="NONE")

    vr = validate_success(api.create_vin_report({"order_id": order["id"]}, OPS), 201)
    assert vr["worst_branding"] == "NONE"
    assert vr["title_count"] == 2
    assert vr["open_recall_count"] == 1
    assert vr["risk_score"] == 17


def test_closed_recall_excluded_from_open_count(api):
    """PRD §3.6: "A new recall begins with `status` of `OPEN`; closing it moves
    the `status` to `CLOSED`, which excludes it from future open-recall counts."

    Design: Corner/calculations/closed_recall_excluded_from_open_count
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2016, make="Mazda", model="3")
    create_recall(2016, "Mazda", "3", campaign_id="RC-OPEN", severity="HIGH")
    rc_closed = create_recall(2016, "Mazda", "3", campaign_id="RC-CLOSED", severity="LOW")
    api.close_recall(rc_closed["id"], OPS)
    order = create_draft_order(acct, veh, fs, include_vin_history=True, rush_tier="NONE")

    vr = validate_success(api.create_vin_report({"order_id": order["id"]}, OPS), 201)
    assert vr["open_recall_count"] == 1


def test_odometer_rollback_sorts_by_event_date_not_insert_order(api):
    """PRD §3.6: "`odometer_rollback` is determined by replaying the vehicle's
    `ODOMETER` records in ascending `event_date` order, breaking ties by
    ascending `created_at`."

    Design: Corner/calculations/odometer_rollback_chronological_out_of_order_insert
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2013, make="Ford", model="Escape")
    # later event_date (2022) inserted FIRST, earlier event_date (2021) SECOND
    add_history_record(veh["id"], "ODOMETER", "2022-01-01T00:00:00Z", odometer_value=49000)
    add_history_record(veh["id"], "ODOMETER", "2021-01-01T00:00:00Z", odometer_value=50000)
    order = create_draft_order(acct, veh, fs, include_vin_history=True, rush_tier="NONE")

    vr = validate_success(api.create_vin_report({"order_id": order["id"]}, OPS), 201)
    assert vr["odometer_rollback"] is True


def test_same_day_sla_deadline_is_8_hours(api):
    """PRD §3.2: "The deadline horizon depends on the rush tier: a `NONE` order
    allows 120 hours, an `EXPRESS` order allows 48 hours, and a `SAME_DAY` order
    allows 8 hours. The `sla_deadline` is the `ordered_at` instant plus that many
    hours."

    Design: Corner/calculations/turnaround_sla_same_day_deadline
    """
    set_clock("2026-06-01T00:00:00Z")
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2015, make="Kia", model="Soul")
    order = create_draft_order(acct, veh, fs, rush_tier="SAME_DAY")

    deadline = order["sla_deadline"]
    assert deadline.startswith("2026-06-01T08:00:00"), f"expected 8h SLA deadline, got {deadline}"
