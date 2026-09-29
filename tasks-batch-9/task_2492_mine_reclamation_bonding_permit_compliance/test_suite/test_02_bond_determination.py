"""The five-step bond determination and its two acreage bases."""
from test_helpers import (
    BOND_SPECIALIST_ACCEPTER,
    BOND_SPECIALIST_DECIDER,
    PERMIT_REVIEWER,
    ApiErrorId,
    api_client as api,
    assert_estimate,
    assert_money,
    assert_permit_ledger_invariants,
    chain_applied,
    chain_issued,
    create_estimate_payload,
    file_estimate,
    refresh_permit,
    validate_error,
    validate_success,
)

RIDGEBACK = {
    "legal_name": "Ridgeback Aggregates LLC",
    "tangible_net_worth": 40000000.00,
    "fixed_assets_in_state": 25000000.00,
    "total_liabilities": 8000000.00,
    "net_income_prior_year": 5000000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
ELK_HOLLOW = {"name": "Elk Hollow Pit", "county": "Carbon", "total_acres": 400.00}


def _ridgeback_permit():
    """An ISSUED 120-acre permit priced at 6000.00 per acre, 120 disturbed, 75 reclaimed."""
    return chain_issued(
        operator_overrides=RIDGEBACK,
        site_overrides=ELK_HOLLOW,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
        reclaimed_acres_credited=75.00,
    )


def test_full_plan_basis_prices_the_whole_mining_plan():
    """Third, the acreage basis, which depends on the permit's `bond_basis`:
    under `FULL_PLAN` the basis is the permit's `mining_plan_acres`; under
    `INCREMENTAL` the basis is `disturbed_acres` minus
    `reclaimed_acres_credited`, rounded half up to two decimals and floored at
    zero.

    Design: Difficulty/dual_variant_calc/bond_required_full_plan_vs_incremental_variant_divergence
    """
    ctx = _ridgeback_permit()
    permit = ctx["permit"]

    assert permit["bond_basis"] == "FULL_PLAN", "the permit is still on its default basis"
    # loaded per acre 7110.00 (6000.00 x 1.185, zero escalation years)
    # x 120.00 plan acres = 853200.00 subtotal, + 12798.00 fee
    assert_money(permit["bond_required_amount"], 865998.00, "bond_required_amount")
    assert_money(permit["disturbed_acres"], 120.00, "disturbed_acres")
    assert_money(permit["reclaimed_acres_credited"], 75.00, "reclaimed_acres_credited")
    assert permit["bond_required_amount"] != 324749.25, (
        "the FULL_PLAN basis must not price only the unreclaimed remainder"
    )


def test_incremental_basis_prices_only_the_unreclaimed_remainder():
    """Switching to `INCREMENTAL` is how a permit that has reclaimed most of its
    footprint stops paying for acreage it has already put back: the basis becomes
    the unreclaimed remainder, `disturbed_acres` minus
    `reclaimed_acres_credited`, rounded half up to two decimals and floored at
    zero.

    Design: Difficulty/dual_variant_calc/bond_required_full_plan_vs_incremental_variant_divergence
    """
    ctx = _ridgeback_permit()
    permit_id = ctx["permit"]["id"]
    full_plan_required = ctx["permit"]["bond_required_amount"]
    assert_money(full_plan_required, 865998.00, "FULL_PLAN bond_required_amount")

    guard = validate_success(api.get_permit(permit_id, BOND_SPECIALIST_DECIDER))["version"]
    recalculated = validate_success(
        api.recalculate_bond(
            permit_id,
            {"basis": "INCREMENTAL", "expected_permit_version": guard},
            BOND_SPECIALIST_ACCEPTER,
        )
    )

    assert recalculated["bond_basis"] == "INCREMENTAL", "the supplied basis is written"
    # 7110.00 x (120.00 - 75.00) = 319950.00 subtotal, + 4799.25 fee
    assert_money(recalculated["bond_required_amount"], 324749.25, "bond_required_amount")
    assert_money(
        full_plan_required - recalculated["bond_required_amount"],
        541248.75,
        "divergence between the two bases",
    )
    assert_money(recalculated["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(recalculated["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")
    assert recalculated["compliance_posture"] == "COMPLIANT", (
        "the held bond still covers the lowered requirement"
    )
    assert recalculated["version"] == guard + 1, "a recalculation is one mutation"


def _cedar_gap_permit():
    """An APPLICATION_SUBMITTED permit whose estimate prices acreage at 6133.33."""
    ctx = chain_applied(
        operator_overrides={
            "legal_name": "Cedar Gap Coal Inc",
            "tangible_net_worth": 15000000.00,
            "fixed_assets_in_state": 9000000.00,
            "total_liabilities": 5000000.00,
            "net_income_prior_year": 1200000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Cedar Gap No. 4", "county": "Fayette", "total_acres": 320.00},
        mining_plan_acres=120.00,
        permit_overrides={
            "post_mining_land_use": "FORESTLAND",
            "proposed_start_date": "2026-09-15",
        },
    )
    ctx["filed_estimate"] = file_estimate(
        ctx["permit"]["id"], ctx["operator_headers"],
        estimator_firm="Bluestone Estimating Group",
        estimator_license_no="RE-5502",
        estimate_effective_date="2026-07-01",
        direct_cost_per_acre=6133.33,
    )
    return ctx


def test_loaded_per_acre_cost_is_rounded_before_it_meets_the_acreage_basis():
    """Because the loaded per-acre cost is rounded before it is multiplied by the
    acreage basis, a determination that defers that rounding to the subtotal will
    disagree with this specification on many inputs; the rounding sequence above
    is the specification.

    Design: Difficulty/combinatorial_formula/bond_required_rounding_order_pinned_per_acre_before_multiply
    """
    ctx = _cedar_gap_permit()
    permit_id = ctx["permit"]["id"]

    guard = validate_success(api.get_permit(permit_id, PERMIT_REVIEWER))["version"]
    validate_success(
        api.accept_estimate(
            ctx["filed_estimate"]["id"],
            {"expected_permit_version": guard},
            PERMIT_REVIEWER,
        )
    )
    permit = refresh_permit(permit_id)

    # 6133.33 x 1.185 = 7267.99605, rounded to 7268.00 before the multiply;
    # 7268.00 x 120.00 = 872160.00 subtotal, + 1.5 percent fee of 13082.40.
    assert_money(permit["bond_required_amount"], 885242.40, "bond_required_amount")
    assert permit["bond_required_amount"] != 885241.92, (
        "deferring the per-acre rounding to the subtotal yields 885241.92, "
        "which this specification rejects"
    )


def test_estimate_acceptance_reprices_the_permit_and_recomputes_its_posture():
    """Acceptance of an estimate is a `PermitReviewer` act and moves the estimate
    `SUBMITTED → ACCEPTED`, stamping `accepted_at` with the logical clock's
    current value. The permit's `bond_required_amount` is then recomputed under
    its current `bond_basis`, `bond_deficiency_amount` is recomputed from it,
    `compliance_posture` is recomputed, and the permit's `version` increments by
    1.

    Design: Difficulty/combinatorial_formula/bond_required_rounding_order_pinned_per_acre_before_multiply
    """
    ctx = _cedar_gap_permit()
    permit_id = ctx["permit"]["id"]

    guard = validate_success(api.get_permit(permit_id, PERMIT_REVIEWER))["version"]
    accepted = validate_success(
        api.accept_estimate(
            ctx["filed_estimate"]["id"],
            {"expected_permit_version": guard},
            PERMIT_REVIEWER,
        )
    )
    assert_estimate(accepted)
    assert accepted["status"] == "ACCEPTED", "the estimate moves SUBMITTED to ACCEPTED"
    assert accepted["accepted_at"] is not None, "acceptance stamps accepted_at"

    permit = refresh_permit(permit_id)
    assert_permit_ledger_invariants(permit)
    assert_money(permit["bond_required_amount"], 885242.40, "bond_required_amount")
    assert_money(permit["bond_held_amount"], 0.00, "bond_held_amount")
    assert_money(permit["bond_deficiency_amount"], 885242.40, "bond_deficiency_amount")
    assert permit["compliance_posture"] == "BOND_DEFICIENT", (
        "nothing secures the permit yet, so the whole requirement is deficient"
    )
    assert permit["version"] == guard + 1, "acceptance is one mutation of the permit"
    assert permit["status"] == "APPLICATION_SUBMITTED", "pricing does not issue a permit"


def _fully_reclaimed_permit():
    """An ISSUED permit whose disturbed acreage has been wholly credited back."""
    return chain_issued(
        operator_overrides={
            "legal_name": "Fully Reclaimed Sand Co",
            "tangible_net_worth": 13000000.00,
            "fixed_assets_in_state": 6500000.00,
            "total_liabilities": 4500000.00,
            "net_income_prior_year": 500000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Sandhill Borrow Area", "county": "Cherry", "total_acres": 200.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
        disturbed_acres=75.00,
        reclaimed_acres_credited=75.00,
    )


def test_zero_acre_incremental_basis_floors_at_the_statutory_minimum():
    """Note that when that remainder is zero, the subtotal is 0.00, the
    administrative fee is nonetheless floored at 2500.00, and
    `bond_required_amount` is then floored at the statutory minimum of 10000.00.

    Design: Difficulty/boundary_precision_check/incremental_bond_zero_acre_basis_floors_to_statutory_minimum
    """
    ctx = _fully_reclaimed_permit()
    permit_id = ctx["permit"]["id"]
    assert_money(ctx["permit"]["disturbed_acres"], 75.00, "disturbed_acres")
    assert_money(ctx["permit"]["reclaimed_acres_credited"], 75.00, "reclaimed_acres_credited")

    guard = validate_success(api.get_permit(permit_id, BOND_SPECIALIST_DECIDER))["version"]
    recalculated = validate_success(
        api.recalculate_bond(
            permit_id,
            {"basis": "INCREMENTAL", "expected_permit_version": guard},
            BOND_SPECIALIST_ACCEPTER,
        )
    )

    assert_money(recalculated["bond_required_amount"], 10000.00, "bond_required_amount")
    assert recalculated["bond_required_amount"] != 0.00, (
        "an empty acreage basis does not zero the requirement"
    )
    assert recalculated["bond_required_amount"] != 2500.00, (
        "the administrative fee floor is not itself the answer; the statutory "
        "minimum bond of 10000.00 is applied after it"
    )


def test_zero_acre_incremental_recalculation_leaves_the_permit_compliant():
    """The supplied `basis` is written to the permit's `bond_basis`, and
    `bond_required_amount` is then re-derived by the five-step determination of
    §3.2 under that basis, followed by `bond_deficiency_amount` and
    `compliance_posture`.

    Design: Difficulty/boundary_precision_check/incremental_bond_zero_acre_basis_floors_to_statutory_minimum
    """
    ctx = _fully_reclaimed_permit()
    permit_id = ctx["permit"]["id"]

    guard = validate_success(api.get_permit(permit_id, BOND_SPECIALIST_DECIDER))["version"]
    recalculated = validate_success(
        api.recalculate_bond(
            permit_id,
            {"basis": "INCREMENTAL", "expected_permit_version": guard},
            BOND_SPECIALIST_ACCEPTER,
        )
    )

    assert recalculated["bond_basis"] == "INCREMENTAL", "the supplied basis is stored"
    assert_permit_ledger_invariants(recalculated)
    assert_money(recalculated["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(recalculated["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")
    assert recalculated["compliance_posture"] == "COMPLIANT", (
        "a permit holding more than it needs shows no deficiency"
    )
    assert recalculated["version"] == guard + 1, "the recalculation bumps the version once"
    assert recalculated["status"] == "ISSUED", "re-pricing does not move the status"


def test_estimate_older_than_three_years_cannot_be_accepted():
    """The `estimate_effective_date` must be no more than three years — 1095
    days — before the logical clock's current instant, else
    `ERR_ESTIMATE_EXPIRED`.

    Design: Corner/errors/expired_estimate_acceptance_rejected
    """
    ctx = chain_applied(
        operator_overrides={
            "legal_name": "Stale Estimate Mining",
            "tangible_net_worth": 12200000.00,
            "fixed_assets_in_state": 6080000.00,
            "total_liabilities": 4340000.00,
            "net_income_prior_year": 352000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Stale Estimate Pit", "county": "Lander", "total_acres": 242.00},
        mining_plan_acres=120.00,
    )
    permit_id = ctx["permit"]["id"]

    # 2023-01-01 sits 1308 days behind the 2026-08-01 clock, so filing is legal
    # but the estimate is no longer current.
    stale = validate_success(
        api.create_estimate(
            create_estimate_payload(permit_id, estimate_effective_date="2023-01-01"),
            ctx["operator_headers"],
        ),
        201,
    )
    guard = validate_success(api.get_permit(permit_id, PERMIT_REVIEWER))["version"]

    response = api.accept_estimate(
        stale["id"], {"expected_permit_version": guard}, PERMIT_REVIEWER
    )
    validate_error(response, ApiErrorId.ERR_ESTIMATE_EXPIRED, 422)

    unchanged = validate_success(api.get_estimate(stale["id"], PERMIT_REVIEWER))
    assert unchanged["status"] == "SUBMITTED", "the refused acceptance left the estimate alone"
    permit = refresh_permit(permit_id)
    assert_money(permit["bond_required_amount"], 0.00, "bond_required_amount")
    assert permit["version"] == guard, "no mutation, so no version bump"


def test_bond_summary_recomputes_the_phase_retention_floor_on_read():
    """For day-to-day supervision, a permit exposes a computed bond summary read
    that returns six figures: `bond_required_amount`, `bond_held_amount`,
    `bond_released_to_date`, `bond_deficiency_amount`, and — evaluated for a
    `phase` supplied as a query parameter, defaulting to `PHASE_I` when omitted —
    the `retention_floor` and the `releasable_amount` that the release arithmetic
    in §3.5 would produce for that phase right now.

    Design: Corner/endpoints/permit_bond_summary_computed_read_matches_phase_retention_floor
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Summary Read Mining",
            "tangible_net_worth": 15100000.00,
            "fixed_assets_in_state": 7500000.00,
            "total_liabilities": 5000000.00,
            "net_income_prior_year": 560000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Summary Read Pit", "county": "Carbon", "total_acres": 310.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )

    summary = validate_success(
        api.get_bond_summary(
            ctx["permit"]["id"], BOND_SPECIALIST_DECIDER, params={"phase": "PHASE_I"}
        )
    )

    assert_money(summary["bond_required_amount"], 865998.00, "bond_required_amount")
    assert_money(summary["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(summary["bond_released_to_date"], 0.00, "bond_released_to_date")
    assert_money(summary["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")
    # 865998.00 x 40 percent = 346399.20, well above the 10000.00 statutory floor.
    assert_money(summary["retention_floor"], 346399.20, "retention_floor")
    # available headroom = 900000.00 - 346399.20
    assert_money(summary["releasable_amount"], 553600.80, "releasable_amount")
