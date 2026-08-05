"""Recovery plans: recoupment formula, payoff projections, overlap, and lifecycle guards."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_overpayment_in_recovery,
    setup_demanded_overpayment,
    setup_established_overpayment,
    create_recovery_plan_payload,
    advance_clock,
    assert_recovery_plan,
)

RECOVERY = TEST_USERS["recovery_officer_headers"]


# --------------------------------------------------------------------------- #
# Dual-variant payoff projections
# --------------------------------------------------------------------------- #
def test_projections_ipv_plan(api):
    """PRD 3.6: "`projected_months_regulatory` is `outstanding_principal_cents` divided by
    `monthly_recoupment_cents`, rounded up to a whole number of months — the horizon at
    the regulatory-minimum pace."
    PRD 3.6: "`projected_months_scheduled` is `outstanding_principal_cents` divided by the
    agreed `scheduled_monthly_cents`, rounded up to a whole number of months — the horizon
    at the agreed-schedule pace, which is typically shorter because the scheduled amount is
    usually larger."

    Design: Difficulty/dual_variant_calc/recovery_projection_regulatory_vs_scheduled
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IPV")  # recoupment 3880
    plan = validate_success(api.get_recovery_plan(ctx["recovery_plan"]["id"], RECOVERY))
    assert_recovery_plan(plan)
    assert plan["monthly_recoupment_cents"] == 3880
    assert plan["projected_months_regulatory"] == 12, (
        f"expected 12 (ceil 45050/3880), got {plan['projected_months_regulatory']}"
    )
    assert plan["projected_months_scheduled"] == 5, (
        f"expected 5 (ceil 45050/9010), got {plan['projected_months_scheduled']}"
    )


def test_projections_ihe_plan(api):
    """PRD 3.6: "`projected_months_regulatory` is `outstanding_principal_cents` divided by
    `monthly_recoupment_cents`, rounded up to a whole number of months — the horizon at
    the regulatory-minimum pace."
    PRD 3.6: "`projected_months_scheduled` is `outstanding_principal_cents` divided by the
    agreed `scheduled_monthly_cents`, rounded up to a whole number of months — the horizon
    at the agreed-schedule pace, which is typically shorter because the scheduled amount is
    usually larger."

    Design: Difficulty/dual_variant_calc/recovery_projection_regulatory_vs_scheduled
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")  # recoupment 1940
    plan = validate_success(api.get_recovery_plan(ctx["recovery_plan"]["id"], RECOVERY))
    assert plan["monthly_recoupment_cents"] == 1940
    assert plan["projected_months_regulatory"] == 24, (
        f"expected 24 (ceil 45050/1940), got {plan['projected_months_regulatory']}"
    )
    assert plan["projected_months_scheduled"] == 5, (
        f"expected 5 (ceil 45050/9010), got {plan['projected_months_scheduled']}"
    )


# --------------------------------------------------------------------------- #
# Recoupment tiered formula
# --------------------------------------------------------------------------- #
def test_recoupment_ipv_rate_and_nested_min_max(api):
    """PRD 3.6: "The rate is 0.20 (twenty percent) when the `claim_type` is `IPV` and 0.10
    (ten percent) for both `IHE` and `AE`. The floor is 2,000 cents ($20.00) when the
    `claim_type` is `IPV` and 1,000 cents ($10.00) for `IHE` and `AE`. The percentage
    amount is `monthly_allotment_cents` multiplied by the applicable rate, rounded half up
    to whole cents. The monthly recoupment is then the smaller of the outstanding principal
    and the larger of the applicable floor and that percentage amount — in other words, the
    recoupment is at least the floor but never more than what is still owed."

    Design: Difficulty/combinatorial_formula/recoupment_tiered_rate_mode_a
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IPV")  # 0.20 * 19400 = 3880
    plan = ctx["recovery_plan"]
    assert plan["monthly_recoupment_cents"] == 3880, (
        f"expected 3880, got {plan['monthly_recoupment_cents']}"
    )


def test_recoupment_floor_dominates_low_percentage(api):
    """PRD 3.6: "The rate is 0.20 (twenty percent) when the `claim_type` is `IPV` and 0.10
    (ten percent) for both `IHE` and `AE`. The floor is 2,000 cents ($20.00) when the
    `claim_type` is `IPV` and 1,000 cents ($10.00) for `IHE` and `AE`. The percentage
    amount is `monthly_allotment_cents` multiplied by the applicable rate, rounded half up
    to whole cents. The monthly recoupment is then the smaller of the outstanding principal
    and the larger of the applicable floor and that percentage amount — in other words, the
    recoupment is at least the floor but never more than what is still owed."

    Design: Difficulty/combinatorial_formula/recoupment_tiered_rate_mode_a
    """
    # IHE rate 0.10 * 5000 = 500, below the 1000 floor -> floor dominates.
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE",
                                        plan_overrides={"monthly_allotment_cents": 5000})
    plan = ctx["recovery_plan"]
    assert plan["monthly_recoupment_cents"] == 1000, (
        f"expected 1000 (floor), got {plan['monthly_recoupment_cents']}"
    )


# --------------------------------------------------------------------------- #
# Overlapping half-open recoupment ranges on the same subject
# --------------------------------------------------------------------------- #
def test_overlapping_recoupment_plan_rejected(api):
    """PRD 3.6: "A `RECOUPMENT` plan may not be created for a subject who already has an
    overlapping active recoupment plan whose `[start_date, end_date)` range intersects this
    one; such an overlap is rejected with `ERR_OVERLAPPING_RECOVERY_PLAN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/overlapping_recoupment_plan_halfopen_range
    """
    ctx1 = setup_overpayment_in_recovery(
        api, claim_type="IHE",
        plan_overrides={"start_date": "2026-05-01", "end_date": "2026-08-01"},
    )
    subject = ctx1["subject"]
    ctx2 = setup_demanded_overpayment(api, claim_type="IHE", subject=subject)
    resp = api.create_recovery_plan(
        create_recovery_plan_payload(ctx2["overpayment"]["id"],
                                     start_date="2026-07-01", end_date="2026-10-01"),
        RECOVERY,
    )
    validate_error(resp, ApiErrorId.ERR_OVERLAPPING_RECOVERY_PLAN.value)


def test_adjacent_recoupment_plan_allowed(api):
    """PRD 3.6: "A `RECOUPMENT` plan may not be created for a subject who already has an
    overlapping active recoupment plan whose `[start_date, end_date)` range intersects this
    one; such an overlap is rejected with `ERR_OVERLAPPING_RECOVERY_PLAN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/overlapping_recoupment_plan_halfopen_range
    """
    ctx1 = setup_overpayment_in_recovery(
        api, claim_type="IHE",
        plan_overrides={"start_date": "2026-05-01", "end_date": "2026-08-01"},
    )
    subject = ctx1["subject"]
    ctx2 = setup_demanded_overpayment(api, claim_type="IHE", subject=subject)
    # New range starts exactly where the prior half-open range ends -> no intersection.
    resp = api.create_recovery_plan(
        create_recovery_plan_payload(ctx2["overpayment"]["id"],
                                     start_date="2026-08-01", end_date="2026-11-01"),
        RECOVERY,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"


# --------------------------------------------------------------------------- #
# Plan lifecycle guards
# --------------------------------------------------------------------------- #
def test_create_plan_requires_demanded_overpayment(api):
    """PRD 3.6: "Creating the plan advances the overpayment from `DEMANDED` to
    `IN_RECOVERY`; a plan against an overpayment that is not `DEMANDED` is rejected with
    `ERR_OVERPAYMENT_NOT_DEMANDED` (HTTP 409)."

    Design: Corner/validations/create_plan_requires_demanded
    """
    ctx = setup_established_overpayment(api, claim_type="IHE")  # ESTABLISHED, not DEMANDED
    resp = api.create_recovery_plan(
        create_recovery_plan_payload(ctx["overpayment"]["id"]), RECOVERY
    )
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT_NOT_DEMANDED.value)


def test_default_plan_after_due_date(api):
    """PRD 3.6: "A `RecoveryOfficer` may mark an `ACTIVE` plan `DEFAULTED`, advancing it
    from `ACTIVE` to `DEFAULTED`, but only when the logical clock is strictly past the
    overpayment's `due_date` and `outstanding_principal_cents` is still greater than zero."

    Design: Corner/state_machines/default_plan_after_due_date
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")  # demanded 2026-05-01, due 2026-05-31
    advance_clock(api, "2026-07-01T00:00:00Z")
    data = validate_success(api.default_plan(ctx["recovery_plan"]["id"], RECOVERY))
    assert data["status"] == "DEFAULTED", f"expected DEFAULTED, got {data['status']}"
