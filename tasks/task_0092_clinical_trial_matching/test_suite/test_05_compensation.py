"""Visit compensation and the compensation sweep: per-visit tiered amounts,
the gross -> tier -> withholding -> net waterfall, and the withdrawn-enrollment
divergence (PRD §3.6, §3.7)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    complete_visit_payload,
    assert_visit, assert_compensation_payment,
    set_clock,
    setup_active_enrollment, setup_active_enrollment_with_completed_visits,
    schedule_visit, withdraw_enrollment, sweep_payment, pay_payment,
    TEST_USERS,
)

# Three on-time visits (seq 1,2,3): payable 10000 / 11200 / 12400 = gross 33600.
THREE_ON_TIME_VISITS = [
    {"sequence_index": 1, "scheduled_at": "2026-06-02T10:00:00Z", "draw_window_minutes": 30, "drawn_at": "2026-06-02T10:00:00Z"},
    {"sequence_index": 2, "scheduled_at": "2026-06-03T10:00:00Z", "draw_window_minutes": 30, "drawn_at": "2026-06-03T10:00:00Z"},
    {"sequence_index": 3, "scheduled_at": "2026-06-04T10:00:00Z", "draw_window_minutes": 30, "drawn_at": "2026-06-04T10:00:00Z"},
]


# ─── Difficulty: dual_variant_calc / standard vs early-termination ──


def test_standard_sweep_withholds_high_rate_above_threshold(api):
    """PRD §3.7: "when `gross_cents` is at least the threshold of 30000 cents,
    the withholding is the gross multiplied by the high rate of 0.10"
    PRD §3.7: "The payment's `amount_cents` is then `gross_cents` minus the
    withholding."

    Design: Difficulty/dual_variant_calc/dvc_compensation_standard_vs_early_termination
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment_with_completed_visits(THREE_ON_TIME_VISITS)

    res = api.create_payment(ctx["enrollment_id"], TEST_USERS["sponsor_headers"])
    data = validate_success(res, 201)
    assert_compensation_payment(data)
    assert data["gross_cents"] == 33600, f"gross is 33600, got {data['gross_cents']}"
    # withholding = round_half_up(33600 * 0.10) = 3360 ; net = 33600 - 3360 = 30240
    assert data["amount_cents"] == 30240, f"high-rate net is 30240, got {data['amount_cents']}"


def test_early_termination_sweep_withholds_nothing_for_withdrawn(api):
    """PRD §3.7: "When the enrollment being swept is `WITHDRAWN`, the same
    visit set and the same gross apply, but the withholding rate is forced to
    the low rate of 0.0 regardless of the gross — diverging from the standard
    sweep precisely at a gross that would otherwise meet or exceed the
    threshold."

    Design: Difficulty/dual_variant_calc/dvc_compensation_standard_vs_early_termination
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment_with_completed_visits(THREE_ON_TIME_VISITS)
    withdraw_enrollment(ctx["enrollment_id"])  # completed visits remain; only SCHEDULED ones cancel

    res = api.create_payment(ctx["enrollment_id"], TEST_USERS["sponsor_headers"])
    data = validate_success(res, 201)
    assert data["gross_cents"] == 33600, f"same gross 33600, got {data['gross_cents']}"
    assert data["amount_cents"] == 33600, \
        f"a withdrawn participant's residual is never withheld; net 33600, got {data['amount_cents']}"


# ─── Difficulty: combinatorial_formula / sweep circular mode (c) ────


def test_sweep_gross_keys_high_withholding_tier(api):
    """PRD §3.7: "The payment's `gross_cents` is the sum of the
    `payable_amount_cents` of the swept visits — summed first, because each
    per-visit value is already exact."
    PRD §3.7: "The evaluation order is fixed: compute the gross, then select
    the tier from the gross, then compute the net."

    Design: Difficulty/combinatorial_formula/cf_compensation_sweep_circular_mode_c
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment_with_completed_visits(THREE_ON_TIME_VISITS)

    res = api.create_payment(ctx["enrollment_id"], TEST_USERS["sponsor_headers"])
    data = validate_success(res, 201)
    assert data["gross_cents"] == 33600, "gross summed first"
    assert data["amount_cents"] == 30240, \
        "tier keyed on gross 33600 >= 30000 -> high rate -> withholding 3360 -> net 30240"


def test_sweep_withholding_rounds_gross_product_once(api):
    """PRD §3.7: "Either way the withholding is the gross-times-rate product
    rounded to whole cents using round-half-up — the rounding is applied once
    to that product, never per visit."

    Design: Difficulty/combinatorial_formula/cf_compensation_sweep_circular_mode_c
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment_with_completed_visits(THREE_ON_TIME_VISITS)

    res = api.create_payment(ctx["enrollment_id"], TEST_USERS["sponsor_headers"])
    data = validate_success(res, 201)
    # round_half_up(33600 * 0.10) == 3360 exactly; net 33600 - 3360 = 30240.
    assert data["gross_cents"] - data["amount_cents"] == 3360, \
        f"withholding rounds the gross*rate product to 3360, got {data['gross_cents'] - data['amount_cents']}"


# ─── Corner: calculations ───────────────────────────────────────────


def test_visit_compensation_late_grace_tier(api):
    """PRD §3.6: "when the deviation is greater than 15 minutes but at most 60
    minutes the bonus is the reduced 1000 cents"
    PRD §3.6: "The stored `payable_amount_cents` is the sum of base, bonus, and
    mileage."

    Design: Corner/calculations/visit_compensation_late_grace_tier_value
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()
    visit = schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 45)

    # deviation 30 min => late-grace tier (15 < 30 <= 60); seq 1 => no mileage.
    res = api.complete_visit(
        visit["id"], complete_visit_payload("2026-06-02T10:30:00Z"),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 200)
    assert_visit(data)
    assert data["draw_deviation_minutes"] == 30
    # 7500 base + 1000 late bonus + 0 mileage = 8500
    assert data["payable_amount_cents"] == 8500, \
        f"late-grace seq-1 payable is 8500, got {data['payable_amount_cents']}"


def test_sweep_below_threshold_no_withholding(api):
    """PRD §3.7: "below the threshold the withholding is the gross multiplied
    by the low rate of 0.0."

    Design: Corner/calculations/compensation_sweep_below_threshold_no_withholding
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment_with_completed_visits([
        {"sequence_index": 1, "scheduled_at": "2026-06-02T10:00:00Z", "draw_window_minutes": 30, "drawn_at": "2026-06-02T10:00:00Z"},
        {"sequence_index": 2, "scheduled_at": "2026-06-03T10:00:00Z", "draw_window_minutes": 30, "drawn_at": "2026-06-03T10:00:00Z"},
    ])

    res = api.create_payment(ctx["enrollment_id"], TEST_USERS["sponsor_headers"])
    data = validate_success(res, 201)
    # 10000 + 11200 = 21200 < 30000 -> low rate 0.0 -> net == gross.
    assert data["gross_cents"] == 21200, f"gross is 21200, got {data['gross_cents']}"
    assert data["amount_cents"] == 21200, \
        f"below threshold there is no withholding, got {data['amount_cents']}"


def test_empty_sweep_rejected(api):
    """PRD §3.7: "If no such visit exists, the sweep is rejected with
    `ERR_NO_PAYABLE_VISITS` (HTTP 409)."

    Design: Corner/calculations/empty_sweep_no_payable_visits
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()  # ACTIVE, but no completed visits

    res = api.create_payment(ctx["enrollment_id"], TEST_USERS["sponsor_headers"])
    validate_error(res, ApiErrorId.ERR_NO_PAYABLE_VISITS.value, 409)


def test_pay_non_pending_payment_rejected(api):
    """PRD §3.7: "This applies only to a payment currently in `PENDING`; an
    attempt to pay a payment that is not pending is rejected with
    `ERR_PAYMENT_NOT_PENDING` (HTTP 409)."

    Design: Corner/validations/pay_non_pending_payment_rejected
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment_with_completed_visits([
        {"sequence_index": 1, "scheduled_at": "2026-06-02T10:00:00Z", "draw_window_minutes": 30, "drawn_at": "2026-06-02T10:00:00Z"},
    ])
    payment = sweep_payment(ctx["enrollment_id"])
    pay_payment(payment["id"])  # first pay -> PAID

    res = api.pay_payment(payment["id"], TEST_USERS["sponsor_headers"])
    validate_error(res, ApiErrorId.ERR_PAYMENT_NOT_PENDING.value, 409)

    payments = validate_success(api.list_payments(ctx["enrollment_id"], TEST_USERS["sponsor_headers"]), 200)
    target = next(p for p in payments if p["id"] == payment["id"])
    assert target["status"] == "PAID", "the payment stays PAID"
