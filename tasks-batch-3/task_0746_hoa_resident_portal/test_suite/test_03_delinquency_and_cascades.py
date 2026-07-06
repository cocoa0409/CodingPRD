"""Delinquency score, standing / booking_privilege cascade, and the payment
reversal 3-aggregate cascade."""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_homeowner_headers,
    create_assessment_payload,
    api_client,
    setup_homeowner_and_property,
    setup_homeowner_property_assessment,
    setup_paid_assessment,
    set_clock,
    set_grace_policy,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]


# ===========================================================================
# Queue A — dual_variant_calc / delinquency_score_strict_vs_lenient
# ===========================================================================
def test_delinquency_score_strict_vs_lenient(api):
    """PRD §3.2: "Under the **strict** variant (in effect whenever
    `grace_policy` is `STRICT`), the server considers every `Assessment` on
    every property owned by the homeowner whose `status` is `OPEN`,
    `PARTIALLY_PAID`, `OVERDUE`, or `DELINQUENT`."
    PRD §3.2: "Under the **lenient** variant (in effect whenever
    `grace_policy` is `LENIENT`), the calculation is identical except that
    any assessment whose age is strictly less than 30 days is excluded
    entirely from the summation — its contribution is zero rather than
    weight 1.0."
    PRD §3.2: "A weight is chosen as one plus the integer-division of
    age-days by 30, multiplied by 0.5 — that is, an assessment aged less
    than 30 days carries weight 1.0, an assessment aged at least 30 and
    strictly less than 60 days carries weight 1.5"
    PRD §2.6: "Homeowner `standing` is derived from `delinquency_score`
    (whose recipe is given in §3.2): a score below 500 places the homeowner
    in `GOOD_STANDING`; a score in the range 500 through 1499 inclusive
    places them in `MARGINAL`"

    Design: Difficulty/dual_variant_calc/delinquency_score_strict_vs_lenient
    """
    homeowner, prop = setup_homeowner_and_property(
        email="hscore@example.com",
        address="3 Score Ln",
        monthly_dues_cents=30000,
    )
    set_grace_policy("STRICT")
    api.create_assessment(
        create_assessment_payload(
            prop["id"],
            billing_period_start="2026-04-01T00:00:00Z",
            billing_period_end="2026-05-01T00:00:00Z",
            due_date="2026-04-15T00:00:00Z",
        ),
        _MANAGER,
    )
    api.create_assessment(
        create_assessment_payload(
            prop["id"],
            billing_period_start="2026-05-01T00:00:00Z",
            billing_period_end="2026-06-01T00:00:00Z",
            due_date="2026-05-25T00:00:00Z",
        ),
        _MANAGER,
    )
    set_clock("2026-06-01T00:00:00Z")

    resp = api.get_homeowner(homeowner["id"], _MANAGER)
    strict = validate_success(resp)
    set_grace_policy("LENIENT")
    resp = api.get_homeowner(homeowner["id"], _MANAGER)
    lenient = validate_success(resp)

    assert strict["delinquency_score"] == 805
    assert strict["standing"] == "MARGINAL"
    assert lenient["delinquency_score"] == 495
    assert lenient["standing"] == "GOOD_STANDING"
    assert strict["delinquency_score"] != lenient["delinquency_score"]


# ===========================================================================
# Queue A — transitive_cascade / payment_reversal_depth_3_cascade
# ===========================================================================
def test_payment_reversal_depth_3_cascade(api):
    """PRD §3.2: "Reversal flips the payment's `status` to `REVERSED`, stamps
    `reversal_reason`, and reduces the target assessment's `amount_paid_cents`
    by the payment's `amount_cents`."
    PRD §3.2: "If the assessment had been `PAID` and the reversal drops it
    below full, the assessment reverts: to `OVERDUE` when the logical clock
    has already reached or passed `due_date` (at which point `late_fee_cents`
    is re-stamped from the late-fee calculation above)"
    PRD §3.2: "When the reversal moves the assessment back to `OVERDUE`, the
    homeowner's `delinquency_score` is recomputed and their `standing` and
    `booking_privilege` are re-derived; a homeowner who was previously
    booking amenities may find their privilege downgraded to `FROZEN` as a
    direct consequence of a payment reversal on a single assessment."
    PRD §2.6: "The property's `total_outstanding_cents` is the sum of
    `amount_due_cents` minus `amount_paid_cents` across every `Assessment`
    on the property whose `status` is `OPEN`, `PARTIALLY_PAID`, `OVERDUE`,
    or `DELINQUENT`"

    Design: Difficulty/transitive_cascade/payment_reversal_depth_3_cascade
    """
    homeowner, prop, assessment, payment = setup_paid_assessment(
        email="hcasc@ex.com",
        address="7 Casc Ln",
        monthly_dues_cents=200000,
        due_date="2026-04-15T00:00:00Z",
    )
    set_clock("2026-07-01T00:00:00Z")  # 77 days past due at reversal
    resp = api.reverse_payment(
        payment["id"], {"reversal_reason": "Chargeback"}, _MANAGER
    )
    reversed_payment = validate_success(resp)
    assert reversed_payment["status"] == "REVERSED"

    resp = api.get_assessment(assessment["id"], _MANAGER)
    a_state = validate_success(resp)
    # 77 days ≥ 60 → tier 4: round(200000*0.15)=30000; mult 1.0 (GOOD_STANDING
    # when the reverse fires); scaled=30000; cap=25000 → 25000. After the
    # reversal the score/standing recompute and standing DELINQUENT is set —
    # but late_fee_cents was re-stamped BEFORE standing crossed to DELINQUENT
    # in the same request; standing multiplier evaluated at that instant is
    # 1.0. Result: 25000 cents.
    assert a_state["amount_paid_cents"] == 0
    assert a_state["status"] == "DELINQUENT"
    assert a_state["late_fee_cents"] == 25000

    resp = api.get_property(prop["id"], _MANAGER)
    p_state = validate_success(resp)
    # total_outstanding_cents = amount_due - amount_paid + late_fee
    #                         = 200000 - 0 + 25000 = 225000
    assert p_state["total_outstanding_cents"] == 225000

    resp = api.get_homeowner(homeowner["id"], _MANAGER)
    h_state = validate_success(resp)
    # STRICT (default): age=77 → weight=1.0+(77//30)*0.5=1.0+2*0.5=2.0
    # contribution = (200000 - 0 + 25000) * 2.0 = 450000 cents
    # score = round(450000/100) = 4500
    assert h_state["delinquency_score"] == 4500
    assert h_state["standing"] == "DELINQUENT"
    assert h_state["booking_privilege"] == "FROZEN"


# ===========================================================================
# Queue A — compensating_invariant / payment_reverse_restores_outstanding
# ===========================================================================
def test_payment_reverse_before_due_date_restores_outstanding(api):
    """PRD §3.2: "If the assessment had been `PAID` and the reversal drops it
    below full, the assessment reverts: to `OVERDUE` when the logical clock
    has already reached or passed `due_date` (at which point `late_fee_cents`
    is re-stamped from the late-fee calculation above), or to
    `PARTIALLY_PAID` when the logical clock is still strictly before
    `due_date`."
    PRD §3.2: "The property's `total_outstanding_cents` is recomputed."

    Design: Difficulty/compensating_invariant/payment_reverse_restores_outstanding_money_conservation
    """
    homeowner, prop = setup_homeowner_and_property(
        email="hinv1@ex.com", address="13 Inv Ln", monthly_dues_cents=30000
    )
    resp = api.create_assessment(
        create_assessment_payload(
            prop["id"],
            billing_period_start="2026-03-01T00:00:00Z",
            billing_period_end="2026-04-01T00:00:00Z",
            due_date="2026-05-15T00:00:00Z",
        ),
        _MANAGER,
    )
    assessment = validate_success(resp, expected_status=201)

    resp = api.get_property(prop["id"], _MANAGER)
    pre = validate_success(resp)
    assert pre["total_outstanding_cents"] == 30000

    resp = api.pay_assessment(
        assessment["id"],
        {"amount_cents": 30000, "method": "MANUAL"},
        make_homeowner_headers(homeowner["id"]),
    )
    payment = validate_success(resp, expected_status=201)

    resp = api.get_property(prop["id"], _MANAGER)
    mid = validate_success(resp)
    assert mid["total_outstanding_cents"] == 0

    resp = api.reverse_payment(
        payment["id"], {"reversal_reason": "Compensating test"}, _MANAGER
    )
    validate_success(resp)

    resp = api.get_property(prop["id"], _MANAGER)
    post = validate_success(resp)
    assert post["total_outstanding_cents"] == 30000
    assert post["total_outstanding_cents"] == pre["total_outstanding_cents"]


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / threshold_delinquent_boundary_1500
# ===========================================================================
def test_standing_flips_to_delinquent_at_1500(api):
    """PRD §2.6: "a score of 1500 or greater places them in `DELINQUENT`."
    PRD §2.6: "The homeowner's `booking_privilege` is derived from `standing`
    in turn: it is `ALLOWED` while `standing` is `GOOD_STANDING` or
    `MARGINAL`, and `FROZEN` while `standing` is `DELINQUENT`."
    PRD §3.2: "A weight is chosen as one plus the integer-division of
    age-days by 30, multiplied by 0.5"
    PRD §3.2: "and 60 or greater selects tier 4."
    PRD §3.2: "the tier caps are 2500, 5000, 10000, and 25000 cents."

    Design: Corner/cross_cutting_complexity_layers/threshold_delinquent_boundary_1500
    """
    set_grace_policy("STRICT")
    homeowner, prop = setup_homeowner_and_property(
        email="hth@ex.com", address="36 Th Ln", monthly_dues_cents=100000
    )
    resp = api.create_assessment(
        create_assessment_payload(
            prop["id"],
            billing_period_start="2026-03-01T00:00:00Z",
            billing_period_end="2026-04-01T00:00:00Z",
            due_date="2026-04-15T00:00:00Z",
        ),
        _MANAGER,
    )
    validate_success(resp, expected_status=201)
    set_clock("2026-06-15T00:00:00Z")  # 61 days past due; tier 4; weight 2.0
    resp = api.get_homeowner(homeowner["id"], _MANAGER)
    data = validate_success(resp)
    # base = round(100000 * 0.15) = 15000, mult 1.0 → 15000, clamped in [5000,25000]
    # contribution = (100000-0+15000) * 2.0 = 230000 cents → 2300 dollars
    assert data["delinquency_score"] == 2300
    assert data["standing"] == "DELINQUENT"
    assert data["booking_privilege"] == "FROZEN"
