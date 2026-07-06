"""Assessment creation, proration, late-fee tier arithmetic, and status
transitions driven by the logical clock."""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_homeowner_headers,
    create_assessment_payload,
    setup_homeowner_and_property,
    setup_homeowner_property_assessment,
    set_clock,
    api_client,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]


# ===========================================================================
# Queue A — dual_variant_calc / assessment_prorate_full_vs_daily
# ===========================================================================
def test_assessment_prorate_full_month_vs_daily_variants(api):
    """PRD §3.2: "When `prorate_from` is absent or is less than or equal to
    `billing_period_start`, the full-month variant applies and
    `amount_due_cents` equals the property's `monthly_dues_cents`."
    PRD §3.2: "When `prorate_from` is strictly after `billing_period_start`
    and strictly before `billing_period_end`, the daily-prorate variant
    applies: the number of included days is the whole-day count from
    `prorate_from` (inclusive) to `billing_period_end` (exclusive), and the
    number of days in the period is the whole-day count from
    `billing_period_start` to `billing_period_end`. The raw prorated amount
    is `monthly_dues_cents` multiplied by included days, then divided by
    days in period; the value written to `amount_due_cents` is that raw
    amount rounded half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/assessment_prorate_full_vs_daily
    """
    _, prop_full = setup_homeowner_and_property(
        email="hfull@example.com", address="1 Full Ln", monthly_dues_cents=30000
    )
    _, prop_daily = setup_homeowner_and_property(
        email="hdaily@example.com", address="2 Daily Ln", monthly_dues_cents=30000
    )
    resp = api.create_assessment(
        create_assessment_payload(
            prop_full["id"],
            billing_period_start="2026-03-01T00:00:00Z",
            billing_period_end="2026-04-01T00:00:00Z",
            due_date="2026-04-15T00:00:00Z",
        ),
        _MANAGER,
    )
    a_full = validate_success(resp, expected_status=201)
    resp = api.create_assessment(
        create_assessment_payload(
            prop_daily["id"],
            billing_period_start="2026-03-01T00:00:00Z",
            billing_period_end="2026-04-01T00:00:00Z",
            due_date="2026-04-15T00:00:00Z",
            prorate_from="2026-03-15T00:00:00Z",
        ),
        _MANAGER,
    )
    a_daily = validate_success(resp, expected_status=201)
    # 31-day March; included = 17 days; 30000 * 17 / 31 = 16451.6129... → 16452
    assert a_full["amount_due_cents"] == 30000
    assert a_daily["amount_due_cents"] == 16452
    assert a_full["amount_due_cents"] != a_daily["amount_due_cents"]


# ===========================================================================
# Queue B — calculations / assessment_prorate_boundary_prorate_from_equal_start
# ===========================================================================
def test_prorate_from_equal_billing_start_uses_full_month(api):
    """PRD §3.2: "When `prorate_from` is absent or is less than or equal to
    `billing_period_start`, the full-month variant applies and
    `amount_due_cents` equals the property's `monthly_dues_cents`."

    Design: Corner/calculations/assessment_prorate_boundary_prorate_from_equal_start
    """
    _, prop = setup_homeowner_and_property(
        email="hpr@ex.com", address="26 Pr Ln", monthly_dues_cents=30000
    )
    resp = api.create_assessment(
        create_assessment_payload(
            prop["id"],
            billing_period_start="2026-03-01T00:00:00Z",
            billing_period_end="2026-04-01T00:00:00Z",
            due_date="2026-04-15T00:00:00Z",
            prorate_from="2026-03-01T00:00:00Z",
        ),
        _MANAGER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["amount_due_cents"] == 30000


# ===========================================================================
# Queue A — combinatorial_formula / late_fee_tiered_nonlinear_mode_a
# ===========================================================================
def test_late_fee_tier3_at_30_days_good_standing(api):
    """PRD §3.2: "The tier's base fee is computed by multiplying the
    outstanding amount by that tier's rate (0.02 for tier 1, 0.05 for tier 2,
    0.10 for tier 3, 0.15 for tier 4) and rounding half-up to a whole cent."
    PRD §3.2: "A standing multiplier is chosen from the owning homeowner's
    current `standing`: 1.0 when `standing` is `GOOD_STANDING`, 1.5 when
    `standing` is `MARGINAL`, and 2.0 when `standing` is `DELINQUENT`."
    PRD §3.2: "The tier floors are 1000, 1000, 2500, and 5000 cents for tiers
    1 through 4 respectively; the tier caps are 2500, 5000, 10000, and 25000
    cents."

    Design: Difficulty/combinatorial_formula/late_fee_tiered_nonlinear_mode_a
    """
    _, _, assessment = setup_homeowner_property_assessment(
        email="hlate@example.com",
        address="4 Late Ln",
        monthly_dues_cents=30000,
        due_date="2026-04-15T00:00:00Z",
    )
    set_clock("2026-05-15T00:00:00Z")  # 30 days past due
    resp = api.get_assessment(assessment["id"], _MANAGER)
    data = validate_success(resp)
    assert data["late_fee_cents"] == 3000  # tier 3: round(30000*0.10)=3000, mult 1.0, in [2500,10000]
    assert data["status"] == "OVERDUE"


# ===========================================================================
# Queue A — boundary_precision_check / late_fee_tier_boundary_days_30_vs_29
# ===========================================================================
def test_late_fee_tier_boundary_at_days_29_vs_30(api):
    """PRD §3.2: "A tier is chosen from days overdue against the boundaries
    14, 30, and 60 days: days overdue at least 1 and strictly less than 14
    selects tier 1, at least 14 and strictly less than 30 selects tier 2,
    at least 30 and strictly less than 60 selects tier 3, and 60 or greater
    selects tier 4."
    PRD §3.2: "The tier's base fee is computed by multiplying the outstanding
    amount by that tier's rate (0.02 for tier 1, 0.05 for tier 2, 0.10 for
    tier 3, 0.15 for tier 4) and rounding half-up to a whole cent."
    PRD §3.2: "The tier floors are 1000, 1000, 2500, and 5000 cents for tiers
    1 through 4 respectively; the tier caps are 2500, 5000, 10000, and 25000
    cents."

    Design: Difficulty/boundary_precision_check/late_fee_tier_boundary_days_30_vs_29
    """
    _, _, a29 = setup_homeowner_property_assessment(
        email="h29@ex.com",
        address="29 Boundary Ln",
        monthly_dues_cents=30000,
        due_date="2026-04-15T00:00:00Z",
    )
    _, prop30 = setup_homeowner_and_property(
        email="h30@ex.com",
        address="30 Boundary Ln",
        monthly_dues_cents=30000,
    )
    set_clock("2026-05-14T00:00:00Z")  # 29 days past due
    resp = api.get_assessment(a29["id"], _MANAGER)
    data_29 = validate_success(resp)
    # Now create the 30-day assessment (fresh property so its transition
    # fires on the next clock advance).
    resp = api.create_assessment(
        create_assessment_payload(
            prop30["id"],
            billing_period_start="2026-03-01T00:00:00Z",
            billing_period_end="2026-04-01T00:00:00Z",
            due_date="2026-04-15T00:00:00Z",
        ),
        _MANAGER,
    )
    a30 = validate_success(resp, expected_status=201)
    set_clock("2026-05-15T00:00:00Z")  # 30 days past due
    resp = api.get_assessment(a30["id"], _MANAGER)
    data_30 = validate_success(resp)
    # 29 days = tier 2 (14<=29<30): round(30000*0.05)=1500; floor=1000, cap=5000 → 1500
    # 30 days = tier 3 (30<=30<60): round(30000*0.10)=3000; floor=2500, cap=10000 → 3000
    assert data_29["late_fee_cents"] == 1500
    assert data_30["late_fee_cents"] == 3000
    assert data_30["late_fee_cents"] != data_29["late_fee_cents"]


# ===========================================================================
# Queue B — calculations / late_fee_tier1_floor_applied
# ===========================================================================
def test_late_fee_tier1_below_floor_clamped_up(api):
    """PRD §3.2: "The scaled fee is finally clamped: it is raised, if
    necessary, to the tier's floor and reduced, if necessary, to the tier's
    cap. The tier floors are 1000, 1000, 2500, and 5000 cents for tiers 1
    through 4 respectively"
    PRD §3.2: "days overdue at least 1 and strictly less than 14 selects
    tier 1"

    Design: Corner/calculations/late_fee_tier1_floor_applied
    """
    _, _, assessment = setup_homeowner_property_assessment(
        email="hfl@ex.com",
        address="27 FL Ln",
        monthly_dues_cents=30000,
        due_date="2026-04-15T00:00:00Z",
    )
    set_clock("2026-04-20T00:00:00Z")  # 5 days past due — tier 1
    resp = api.get_assessment(assessment["id"], _MANAGER)
    data = validate_success(resp)
    # base = round(30000 * 0.02) = 600 → clamped up to floor 1000
    assert data["late_fee_cents"] == 1000
    assert data["status"] == "OVERDUE"


# ===========================================================================
# Queue B — state_machines / assessment_initial_state_open
# ===========================================================================
def test_assessment_initial_status_is_open(api):
    """PRD §3.2: "`amount_paid_cents` and `late_fee_cents` start at `0`; the
    assessment's initial `status` is `OPEN`."

    Design: Corner/state_machines/assessment_initial_state_open
    """
    _, prop = setup_homeowner_and_property(email="hist@ex.com", address="23 Ist Ln")
    resp = api.create_assessment(create_assessment_payload(prop["id"]), _MANAGER)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "OPEN"


# ===========================================================================
# Queue B — consistency_model / derived_field_immediate_visibility
# ===========================================================================
def test_derived_field_immediate_visibility_after_partial_pay(api):
    """PRD §2.6: "Whenever a state transition, payment post, payment reversal,
    fine, adjudication, or ARC approval alters the inputs to a derived field,
    the server recomputes that field within the same request, mutates the
    affected resource's `updated_at`, and increments its `version`."

    Design: Corner/consistency_model/derived_field_immediate_visibility
    """
    homeowner, prop, assessment = setup_homeowner_property_assessment(
        email="him@ex.com",
        address="37 Im Ln",
        monthly_dues_cents=30000,
        due_date="2026-05-15T00:00:00Z",
    )
    resp = api.pay_assessment(
        assessment["id"],
        {"amount_cents": 15000, "method": "MANUAL"},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_success(resp, expected_status=201)
    resp = api.get_property(prop["id"], _MANAGER)
    data = validate_success(resp)
    assert data["total_outstanding_cents"] == 15000
