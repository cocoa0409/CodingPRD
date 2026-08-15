"""Calculation tests: aging variants, restitution rounding, timeliness score,
early-warning evaluation order, and posture thresholds (PRD §3.5, §3.6, §3.8, §3.10)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, headers_for,
    assert_instant_equals, assert_trend_snapshot,
    setup_reference_data, setup_complaint, intake_complaint,
    intake_portal_complaint, setup_resolved_complaint,
    setup_complaint_in_response_qa, setup_product_with_substantiated,
    create_and_complete_rca, create_decision, create_rca, complete_rca,
    drive_to_investigating, claim_review, complete_review,
    draft_response, submit_for_qa, set_clock,
    get_complaint, get_product, get_referral, get_decision, get_review,
    list_complaint_referrals,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]


def test_complaint_age_terminal_frozen_against_clock_movement(api):
    """PRD §3.5: "`days_open_calendar` counts whole days from `received_at` to an
    end instant — `resolved_at` when the complaint is `RESOLVED` or `WITHDRAWN`,
    the current logical clock otherwise — discarding fractional days; for
    terminal complaints the value is frozen at resolution and immune to later
    clock movement, while for open complaints it grows as the clock advances."
    PRD §3.5: "On resolution, `resolved_at` is stamped from the logical clock,
    `retention_purge_at` is fixed at the same calendar date five years after
    `resolved_at` (with February 29 mapping to February 28 in non-leap years),
    the product's `open_complaint_count` decrements by 1, the product's `posture`
    recomputes, a `STATUS_CHANGED` event is appended, and the complaint's
    `version` bumps."

    Design: Corner/calculations/complaint_age_terminal_frozen_against_clock_movement
    """
    ctx = setup_resolved_complaint(
        "P-CALC1", "WEB", "C.CALC1", verdict="NOT_SUBSTANTIATED",
        owner_id="user_intake_c1", reviewer_id="user_qa_c1",
        window_end_at="2026-08-04T00:00:00Z", resolve_clock="2026-08-05T00:00:00Z",
    )
    cid = ctx["complaint"]["id"]
    set_clock("2026-08-25T00:00:00Z")
    complaint = get_complaint(cid)
    assert complaint["days_open_calendar"] == 4, (
        f"terminal age is frozen at resolution: received 2026-08-01, resolved "
        f"2026-08-05 -> 4 days, got {complaint['days_open_calendar']}"
    )
    assert_instant_equals(complaint["resolved_at"], "2026-08-05T00:00:00Z", "resolved_at")
    assert_instant_equals(
        complaint["retention_purge_at"], "2031-08-05T00:00:00Z", "retention_purge_at",
    )


def test_timeliness_score_late_path_floor_before_bonus(api):
    """PRD §3.8: "First, whole days to respond are counted from the complaint's
    `received_at` to the referral's `submitted_at`, discarding fractional days. A
    base score starts at 100 and loses 5 points per day to respond, floored at 0.
    The base is then halved when the referral's `timeliness` is `LATE` (multiplier
    one-half) and left whole when `ON_TIME` (multiplier one), and this product is
    floored to an integer **before** any bonuses apply. A quality bonus then adds
    10 when the latest `COMPLETED` quality review passed, subtracts 15 when it
    failed, and adds 0 when no completed review exists. A high-value bonus adds 5
    when the complaint's `claimed_loss_cents` is at least 1000000 cents. Finally
    the total is capped at 100 and floored at 0."

    Design: Corner/calculations/timeliness_score_late_path_floor_before_bonus
    """
    complaint, referral = intake_portal_complaint(
        "P-CALC2", "CFPB_PORTAL", "C.CALC2", narrative="late score",
        claimed_loss_cents=5000, portal_ref="R-CALC2",
    )
    set_clock("2026-08-20T00:00:00Z")
    submitted = validate_success(api.submit_referral_response(
        referral["id"], {"response_text": "late response"}, HANDLER,
    ))
    assert submitted["timeliness"] == "LATE"
    # 19 days to respond: base = max(0, 100 - 95) = 5; floor(5 * 0.5) = 2;
    # no completed review (+0), claim below the high-value threshold (+0).
    score = get_complaint(complaint["id"])["timeliness_score"]
    assert score == 2, f"expected timeliness_score 2, got {score}"


def test_restitution_no_bps_rate_is_identity(api):
    """PRD §3.6: "The decision's `restitution_amount_cents` is computed under a
    pinned rounding order: for each line item, multiply its `amount_cents` by its
    `rounding_rate_bps` (defaulting to 10000, the full amount, when omitted),
    divide by 10000, and floor to a whole cent — then sum the per-line results."

    Design: Corner/calculations/restitution_no_bps_rate_is_identity
    """
    ctx = setup_complaint("P-CALC3", "WEB", "C.CALC3", narrative="identity bps")
    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid)
    decision = create_decision(
        cid, "RESTITUTION", [{"label": "full", "amount_cents": 15000}],
    )
    assert decision["restitution_amount_cents"] == 15000, (
        "a line without rounding_rate_bps uses the full-amount default: "
        f"expected 15000, got {decision['restitution_amount_cents']}"
    )


def test_product_posture_watch_boundary_at_exactly_three_substantiated(api):
    """PRD §3.10: "the posture then derives by threshold: `FROZEN` when
    `substantiated_count_90d` reaches at least 5; otherwise `WATCH` when
    `early_warning_active` is true or `substantiated_count_90d` is at least 3;
    otherwise `OPEN`."

    Design: Corner/calculations/product_posture_watch_boundary_at_exactly_three_substantiated
    """
    ctx = setup_product_with_substantiated("P-CALC4", 2, "WEB", "C.CALC4")
    pid = ctx["product"]["id"]
    mid = get_product(pid)
    assert mid["substantiated_count_90d"] == 2
    assert mid["posture"] == "OPEN", f"2 substantiated is below the WATCH boundary: {mid['posture']}"

    third = intake_complaint("P-CALC4", "WEB", "C.CALC4", narrative="w3")
    create_and_complete_rca(third["id"], "SUBSTANTIATED", "P-CALC4")
    product = get_product(pid)
    assert product["substantiated_count_90d"] == 3
    assert product["posture"] == "WATCH", (
        f"exactly 3 substantiated is the inclusive WATCH boundary: {product['posture']}"
    )
    assert product["posture"] != "FROZEN"


def test_snapshot_rate_floor_precision_one_third(api):
    """PRD §3.10: "Then `substantiation_rate_bps` is derived in basis points: 0
    when `complaint_count` is 0, otherwise the substantiated count times 10000
    divided by the complaint count, floored to an integer."
    PRD §3.10: "Finally `early_warning` is true when `complaint_count` is at
    least 3 **and** at least one of two conditions holds —
    `substantiation_rate_bps` is at least 5000, or the live open count is at
    least 10."

    Design: Corner/calculations/snapshot_rate_floor_precision_one_third
    """
    refs = setup_reference_data("P-CALC5", "WEB", "C.CALC5")
    pid = refs["product"]["id"]
    verdicts = ["SUBSTANTIATED", "NOT_SUBSTANTIATED", "INCONCLUSIVE"]
    for i, verdict in enumerate(verdicts):
        complaint = intake_complaint("P-CALC5", "WEB", "C.CALC5", narrative=f"t{i + 1}")
        create_and_complete_rca(complaint["id"], verdict, "P-CALC5")

    snapshot = validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-08-01T00:00:00Z",
                  "period_end_at": "2026-08-31T23:59:59Z"}, MANAGER,
        ),
        expected_status=201,
    )
    assert_trend_snapshot(snapshot)
    assert snapshot["complaint_count"] == 3
    assert snapshot["substantiated_count"] == 1
    assert snapshot["substantiation_rate_bps"] == 3333, (
        "floor(1 * 10000 / 3) must be 3333, got "
        f"{snapshot['substantiation_rate_bps']}"
    )
    assert snapshot["early_warning"] is False


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc
# ---------------------------------------------------------------------------

def test_complaint_age_calendar_vs_business_divergence_over_weekend(api):
    """PRD §3.5: "`days_open_calendar` counts whole days from `received_at` to an
    end instant — `resolved_at` when the complaint is `RESOLVED` or `WITHDRAWN`,
    the current logical clock otherwise — discarding fractional days; for
    terminal complaints the value is frozen at resolution and immune to later
    clock movement, while for open complaints it grows as the clock advances."
    PRD §3.5: "`days_open_business` counts, over the same window, only calendar
    dates strictly after the intake date and on or before the end date that fall
    Monday through Friday and are not in the fixed holiday set (2026-01-01,
    2026-07-04, 2026-12-25); the intake date itself is never counted."

    Design: Difficulty/dual_variant_calc/complaint_age_calendar_vs_business_divergence
    """
    ctx = setup_complaint("CKNG-STD", "WEB", "FEES.OVERDRAFT",
                          narrative="Overdraft fee dispute")
    cid = ctx["complaint"]["id"]
    # Received 2026-08-01 (Saturday) at the startup default clock.
    assert_instant_equals(ctx["complaint"]["received_at"], "2026-08-01T00:00:00Z",
                          "received_at")
    set_clock("2026-08-10T00:00:00Z")  # Monday
    complaint = get_complaint(cid)
    assert complaint["days_open_calendar"] == 9, (
        f"calendar age: 2026-08-01 -> 2026-08-10 is 9 days, got "
        f"{complaint['days_open_calendar']}"
    )
    assert complaint["days_open_business"] == 6, (
        f"business age: 08-03..08-07 plus 08-10 are the countable weekdays, got "
        f"{complaint['days_open_business']}"
    )
    assert complaint["days_open_calendar"] != complaint["days_open_business"]


def test_complaint_age_calendar_vs_business_divergence_friday_to_monday(api):
    """PRD §3.5: "`days_open_calendar` counts whole days from `received_at` to an
    end instant — `resolved_at` when the complaint is `RESOLVED` or `WITHDRAWN`,
    the current logical clock otherwise — discarding fractional days; for
    terminal complaints the value is frozen at resolution and immune to later
    clock movement, while for open complaints it grows as the clock advances."
    PRD §3.5: "`days_open_business` counts, over the same window, only calendar
    dates strictly after the intake date and on or before the end date that fall
    Monday through Friday and are not in the fixed holiday set (2026-01-01,
    2026-07-04, 2026-12-25); the intake date itself is never counted."
    PRD §3.5: "Whenever a weekend or holiday falls inside the window, the
    business count is strictly smaller than the calendar count."

    Design: Difficulty/dual_variant_calc/complaint_age_calendar_vs_business_divergence
    """
    setup_reference_data("SAVE-DV", "WEB", "SVC.DV")
    set_clock("2026-08-07T00:00:00Z")  # Friday intake
    complaint = intake_complaint("SAVE-DV", "WEB", "SVC.DV", narrative="Fri intake")
    set_clock("2026-08-10T00:00:00Z")  # Monday read
    fetched = get_complaint(complaint["id"])
    assert fetched["days_open_calendar"] == 3, (
        f"Friday -> Monday spans 3 calendar days, got {fetched['days_open_calendar']}"
    )
    assert fetched["days_open_business"] == 1, (
        f"only Monday 08-10 is countable (08-08/08-09 are weekend days), got "
        f"{fetched['days_open_business']}"
    )
    assert fetched["days_open_business"] < fetched["days_open_calendar"]


def test_restitution_per_line_floor_then_sum_two_half_rate_lines(api):
    """PRD §3.6: "The decision's `restitution_amount_cents` is computed under a
    pinned rounding order: for each line item, multiply its `amount_cents` by its
    `rounding_rate_bps` (defaulting to 10000, the full amount, when omitted),
    divide by 10000, and floor to a whole cent — then sum the per-line results."
    PRD §3.6: "Flooring per line before summation is the specification; summing
    raw amounts first and flooring once at the end yields a different total
    whenever two or more lines carry a rate below the full amount and is a
    violation."

    Design: Difficulty/dual_variant_calc/restitution_per_line_floor_vs_sum_first_divergence
    """
    ctx = setup_complaint("CARD-GLD", "PHONE", "FEES.LATE", narrative="Late fee dispute")
    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid)
    decision = create_decision(cid, "RESTITUTION", [
        {"label": "fee1", "amount_cents": 101, "rounding_rate_bps": 5000},
        {"label": "fee2", "amount_cents": 103, "rounding_rate_bps": 5000},
    ])
    # Per-line floor: floor(50.5) + floor(51.5) = 50 + 51 = 101.
    # Sum-first would yield floor(204 * 0.5) = 102 — a spec violation.
    assert decision["restitution_amount_cents"] == 101, (
        f"expected per-line floor then sum == 101, got "
        f"{decision['restitution_amount_cents']}"
    )
    assert decision["restitution_amount_cents"] != 102


def test_restitution_per_line_floor_then_sum_repeated_identical_lines(api):
    """PRD §3.6: "The decision's `restitution_amount_cents` is computed under a
    pinned rounding order: for each line item, multiply its `amount_cents` by its
    `rounding_rate_bps` (defaulting to 10000, the full amount, when omitted),
    divide by 10000, and floor to a whole cent — then sum the per-line results."
    PRD §3.6: "Flooring per line before summation is the specification; summing
    raw amounts first and flooring once at the end yields a different total
    whenever two or more lines carry a rate below the full amount and is a
    violation."

    Design: Difficulty/dual_variant_calc/restitution_per_line_floor_vs_sum_first_divergence
    """
    ctx = setup_complaint("CARD-SLV", "PHONE", "FEES.ATM", narrative="ATM fee dispute")
    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid)
    decision = create_decision(cid, "RESTITUTION", [
        {"label": "fee-a", "amount_cents": 199, "rounding_rate_bps": 5000},
        {"label": "fee-b", "amount_cents": 199, "rounding_rate_bps": 5000},
    ])
    # Per-line floor: floor(99.5) + floor(99.5) = 99 + 99 = 198.
    # Sum-first would yield floor(398 * 0.5) = 199 — a spec violation.
    assert decision["restitution_amount_cents"] == 198, (
        f"expected per-line floor then sum == 198, got "
        f"{decision['restitution_amount_cents']}"
    )
    assert decision["restitution_amount_cents"] != 199


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula
# ---------------------------------------------------------------------------

def test_timeliness_score_on_time_qa_pass_high_value(api):
    """PRD §3.8: "First, whole days to respond are counted from the complaint's
    `received_at` to the referral's `submitted_at`, discarding fractional days. A
    base score starts at 100 and loses 5 points per day to respond, floored at 0.
    The base is then halved when the referral's `timeliness` is `LATE` (multiplier
    one-half) and left whole when `ON_TIME` (multiplier one), and this product is
    floored to an integer **before** any bonuses apply. A quality bonus then adds
    10 when the latest `COMPLETED` quality review passed, subtracts 15 when it
    failed, and adds 0 when no completed review exists. A high-value bonus adds 5
    when the complaint's `claimed_loss_cents` is at least 1000000 cents. Finally
    the total is capped at 100 and floored at 0."
    PRD §3.2: "The referral's `received_via_portal_at` equals the complaint's
    `received_at`; its `portal_ref` is the supplied value, defaulting to `AUTO-`
    followed by the complaint's `id` when omitted; and its `response_due_at` is
    exactly fifteen calendar days after `received_via_portal_at`, computed with
    calendar-day arithmetic that preserves the time of day and applies no
    business-day adjustment."

    Design: Difficulty/combinatorial_formula/timeliness_score_multi_input_nonlinear
    """
    ctx = setup_complaint_in_response_qa(
        "MORT-CONF", "CFPB_PORTAL", "LOAN.SERVICING", portal=True,
        owner_id="user_intake_1", narrative="Escrow mishandling",
        claimed_loss_cents=2000000, portal_ref="CFPB-2026-001",
    )
    cid = ctx["complaint"]["id"]
    referral = list_complaint_referrals(cid)[0]
    review = claim_review(cid, "user_qa_1", "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z")
    complete_review(review["id"], "PASS", "user_qa_1")
    set_clock("2026-08-05T00:00:00Z")
    submitted = validate_success(api.submit_referral_response(
        referral["id"],
        {"response_text": "Response to regulator with remediation summary."},
        HANDLER,
    ))
    assert submitted["timeliness"] == "ON_TIME"
    assert_instant_equals(submitted["response_due_at"], "2026-08-16T00:00:00Z",
                          "response_due_at")
    # 4 days: base = 100 - 20 = 80; ON_TIME -> floor(80 * 1.0) = 80;
    # QA PASS (+10); claimed_loss 2000000 >= 1000000 (+5); min(100, 95) = 95.
    score = get_complaint(cid)["timeliness_score"]
    assert score == 95, f"expected timeliness_score 95, got {score}"


def test_timeliness_score_on_time_qa_fail_high_value(api):
    """PRD §3.8: "First, whole days to respond are counted from the complaint's
    `received_at` to the referral's `submitted_at`, discarding fractional days. A
    base score starts at 100 and loses 5 points per day to respond, floored at 0.
    The base is then halved when the referral's `timeliness` is `LATE` (multiplier
    one-half) and left whole when `ON_TIME` (multiplier one), and this product is
    floored to an integer **before** any bonuses apply. A quality bonus then adds
    10 when the latest `COMPLETED` quality review passed, subtracts 15 when it
    failed, and adds 0 when no completed review exists. A high-value bonus adds 5
    when the complaint's `claimed_loss_cents` is at least 1000000 cents. Finally
    the total is capped at 100 and floored at 0."
    PRD §3.5: "Completing a review with `PASS` leaves the complaint in
    `RESPONSE_QA` — a pass alone never resolves anything — while the dedicated
    qa-fail action moves the complaint `RESPONSE_QA → INVESTIGATING`, completes
    the acting reviewer's `OPEN` review with outcome `FAIL` in the same call,
    appends `QA_FAILED`, and bumps the complaint's `version`."

    Design: Difficulty/combinatorial_formula/timeliness_score_multi_input_nonlinear
    """
    ctx = setup_complaint_in_response_qa(
        "MORT-JMB", "CFPB_PORTAL", "LOAN.ESCROW", portal=True,
        owner_id="user_intake_hv", narrative="Escrow shortage",
        claimed_loss_cents=1500000, portal_ref="CFPB-2026-002",
    )
    cid = ctx["complaint"]["id"]
    referral = list_complaint_referrals(cid)[0]
    review = claim_review(cid, "user_qa_hv", "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z")
    # qa_fail completes the acting reviewer's OPEN review with FAIL.
    validate_success(api.qa_fail(cid, headers_for("QAReviewer", "user_qa_hv")))
    assert get_review(review["id"])["outcome"] == "FAIL"
    set_clock("2026-08-03T00:00:00Z")
    submitted = validate_success(api.submit_referral_response(
        referral["id"], {"response_text": "Initial regulator response."}, HANDLER,
    ))
    assert submitted["timeliness"] == "ON_TIME"
    # 2 days: base = 100 - 10 = 90; ON_TIME -> floor(90 * 1.0) = 90;
    # latest COMPLETED review FAIL (-15); high-value claim (+5); total 80.
    score = get_complaint(cid)["timeliness_score"]
    assert score == 80, f"expected timeliness_score 80, got {score}"


def test_early_warning_rate_boundary_exactly_5000_bps(api):
    """PRD §3.10: "First `complaint_count` counts the product's complaints whose
    `received_at` falls inside the closed window on both ends. Then
    `substantiated_count` counts, among those, complaints whose latest RCA verdict
    is `SUBSTANTIATED`. Then `substantiation_rate_bps` is derived in basis points:
    0 when `complaint_count` is 0, otherwise the substantiated count times 10000
    divided by the complaint count, floored to an integer. The live
    `open_complaint_count` of the product is read next. Finally `early_warning` is
    true when `complaint_count` is at least 3 **and** at least one of two
    conditions holds — `substantiation_rate_bps` is at least 5000, or the live
    open count is at least 10."
    PRD §3.10: "Persisting a snapshot updates the product's `early_warning_active`
    to the snapshot's `early_warning` value and recomputes the product's
    `posture`."

    Design: Difficulty/combinatorial_formula/early_warning_pinned_evaluation_order
    """
    refs = setup_reference_data("AUTO-IND", "BRANCH", "LOAN.PAYOFF")
    pid = refs["product"]["id"]
    verdicts = ["SUBSTANTIATED", "SUBSTANTIATED", "NOT_SUBSTANTIATED", "INCONCLUSIVE"]
    for i, verdict in enumerate(verdicts):
        complaint = intake_complaint("AUTO-IND", "BRANCH", "LOAN.PAYOFF",
                                     complainant_ref=f"CUST-10{i + 1}",
                                     narrative=f"n{i + 1}")
        create_and_complete_rca(complaint["id"], verdict, "AUTO-IND",
                                process_step="PAYOFF_QUOTE")

    snapshot = validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-08-01T00:00:00Z",
                  "period_end_at": "2026-08-31T23:59:59Z"}, MANAGER,
        ),
        expected_status=201,
    )
    assert_trend_snapshot(snapshot)
    assert snapshot["complaint_count"] == 4
    assert snapshot["substantiated_count"] == 2
    assert snapshot["substantiation_rate_bps"] == 5000, (
        "floor(2 * 10000 / 4) == 5000 exactly — the inclusive rate boundary"
    )
    assert snapshot["early_warning"] is True

    product = get_product(pid)
    assert product["early_warning_active"] is True
    # substantiated_count_90d == 2 (< 3), so WATCH is driven by early_warning alone.
    assert product["posture"] == "WATCH"


def test_early_warning_open_count_branch_with_low_rate(api):
    """PRD §3.10: "Finally `early_warning` is true when `complaint_count` is at
    least 3 **and** at least one of two conditions holds —
    `substantiation_rate_bps` is at least 5000, or the live open count is at
    least 10."
    PRD §3.10: "Persisting a snapshot updates the product's `early_warning_active`
    to the snapshot's `early_warning` value and recomputes the product's
    `posture`."

    Design: Difficulty/combinatorial_formula/early_warning_pinned_evaluation_order
    """
    refs = setup_reference_data("RV-OPEN", "BRANCH", "LOAN.ORIG")
    pid = refs["product"]["id"]
    # Three complaints received inside the snapshot window (clock at 2026-08-01).
    for i in range(3):
        intake_complaint("RV-OPEN", "BRANCH", "LOAN.ORIG",
                         complainant_ref=f"CUST-EW-A{i}", narrative=f"early {i}")
    # Seven more received after the window closes (clock at 2026-08-20).
    set_clock("2026-08-20T00:00:00Z")
    for i in range(7):
        intake_complaint("RV-OPEN", "BRANCH", "LOAN.ORIG",
                         complainant_ref=f"CUST-EW-B{i}", narrative=f"late {i}")

    snapshot = validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-08-01T00:00:00Z",
                  "period_end_at": "2026-08-10T00:00:00Z"}, MANAGER,
        ),
        expected_status=201,
    )
    assert_trend_snapshot(snapshot)
    assert snapshot["complaint_count"] == 3
    assert snapshot["substantiated_count"] == 0
    assert snapshot["substantiation_rate_bps"] == 0
    # Rate branch fails (0 < 5000) but the live open count is 10 (>= 10),
    # and complaint_count 3 meets the minimum: early warning fires.
    assert snapshot["early_warning"] is True

    product = get_product(pid)
    assert product["early_warning_active"] is True
    assert product["open_complaint_count"] == 10
    assert product["posture"] == "WATCH"
