"""Death claims: the benefit split, the pinned residual rule and the two independent dimensions."""
import pytest
from test_helpers import validate_error, validate_success
from test_helpers.assertions import assert_death_benefit_conservation
from test_helpers.fixtures import (
    CLAIMS,
    RISK,
    add_allocation,
    approved_claim,
    claim_allocations,
    in_force_policy,
    move_clock,
    seal_allocations,
)


IRONBRIDGE = {"legal_name": "Ironbridge Life", "naic_code": "62111", "domicile_state": "MA"}
MERIDIAN = {"legal_name": "Meridian Life", "naic_code": "62121", "domicile_state": "CT"}
YARROW = {"legal_name": "Yarrow Life", "naic_code": "62131", "domicile_state": "DE"}

OKAFOR = {
    "full_name": "Chidi Okafor",
    "employee_number": "E-6901",
    "annual_salary_usd": 2_000_000.00,
    "officer_flag": True,
}
BHATT = {
    "full_name": "Anil Bhatt",
    "employee_number": "E-7001",
    "annual_salary_usd": 2_000_000.00,
    "officer_flag": True,
}
FERRARO = {
    "full_name": "Lucia Ferraro",
    "employee_number": "E-7101",
    "annual_salary_usd": 2_000_000.00,
    "officer_flag": True,
}

THIRDS = [
    ("Rowan Heir", "SPOUSE", 3333),
    ("Sasha Heir", "CHILD", 3333),
    ("Tamsin Heir", "CHILD", 3334),
]


def _placed_policy(api, carrier_overrides, employee_overrides, policy_number, product_name):
    """A 1,200,000.00 premium policy carrying 5,000,000.00 of death benefit."""
    return in_force_policy(
        api,
        carrier_overrides=carrier_overrides,
        product_overrides={"product_name": product_name},
        employee_overrides=employee_overrides,
        request_overrides={
            "single_premium_usd": 1_200_000.00,
            "face_amount_usd": 5_000_000.00,
        },
        policy_overrides={"policy_number": policy_number},
    )


def _claim_with_thirds(
    api,
    carrier_overrides,
    employee_overrides,
    policy_number,
    product_name,
    clock=None,
    **claim_overrides,
):
    """An approved claim on a 5,000,000.00 policy split into 3333/3333/3334 shares."""
    context = _placed_policy(
        api, carrier_overrides, employee_overrides, policy_number, product_name
    )
    if clock is not None:
        move_clock(api, clock)
    claim = approved_claim(api, context["policy_id"], **claim_overrides)
    for name, relationship, bps in THIRDS:
        add_allocation(
            api,
            claim["id"],
            beneficiary_name=name,
            relationship=relationship,
            allocation_pct_bps=bps,
        )
    context["claim"] = claim
    context["claim_id"] = claim["id"]
    return context


class TestBenefitSplitAndResidual:
    def test_approval_caps_the_survivor_share_at_sixty_percent_of_the_total(self, api):
        """The proportional ceiling wins over the salary multiple here.

        "The total benefit is the policy's `face_amount_usd` plus the claim's
        `terminal_dividend_usd`. Against that total two ceilings are computed and
        the lower one wins. The first is a proportional cap: sixty hundredths of
        the total death benefit, rounded half up to 2 decimal places. The second
        is a salary multiple: the insured employee's `annual_salary_usd`
        multiplied by two, rounded half up to 2 decimal places.
        `survivor_entitlement_usd` is the lesser of those two figures, and
        `bank_portion_usd` is the total death benefit minus the survivor
        entitlement".

        Design: Difficulty/combinatorial_formula/beneficiary_split_round_then_sum_signed_residual
        """
        context = _claim_with_thirds(
            api,
            IRONBRIDGE,
            OKAFOR,
            "IB-0001",
            "Ironbridge GA BOLI",
            clock="2026-11-15T00:00:00Z",
            terminal_dividend_usd=25_000.13,
            date_of_death="2026-11-10T00:00:00Z",
        )
        claim = validate_success(api.get_death_claim(context["claim_id"], CLAIMS))

        assert claim["total_death_benefit_usd"] == pytest.approx(5_025_000.13, abs=0.01)
        assert claim["survivor_entitlement_usd"] == pytest.approx(3_015_000.08, abs=0.01), (
            "sixty hundredths of 5,025,000.13 is below the 4,000,000.00 salary multiple"
        )
        assert claim["bank_portion_usd"] == pytest.approx(2_010_000.05, abs=0.01)
        assert claim["adjudication_status"] == "APPROVED"
        assert claim["distribution_status"] == "NOT_STARTED"
        assert claim["allocated_bps_total"] == 10000

    def test_sealing_rounds_each_share_then_moves_one_signed_cent(self, api):
        """The residual lands on the largest share, not on the last one.

        "each allocation's share is the `survivor_entitlement_usd` multiplied by
        that allocation's `allocation_pct_bps` divided by ten thousand, rounded
        half up to 2 decimal places. Then the residual is computed as
        `survivor_entitlement_usd` minus the sum of those rounded shares — a
        value that may be positive or negative. That single signed residual is
        added to exactly one allocation: the `ACTIVE` allocation carrying the
        greatest `allocation_pct_bps`, with ties broken by `created_at` ascending
        and never by `id`." The three rounded shares overshoot by one cent, so
        the 3334 share is reduced to 1,005,201.02 rather than 1,005,201.03.

        Design: Difficulty/combinatorial_formula/beneficiary_split_round_then_sum_signed_residual
        """
        context = _claim_with_thirds(
            api,
            IRONBRIDGE,
            OKAFOR,
            "IB-0001",
            "Ironbridge GA BOLI",
            clock="2026-11-15T00:00:00Z",
            terminal_dividend_usd=25_000.13,
            date_of_death="2026-11-10T00:00:00Z",
        )

        sealed = seal_allocations(api, context["claim_id"])
        assert sealed["distribution_status"] == "ALLOCATED"
        assert sealed["adjudication_status"] == "APPROVED"
        assert sealed["allocated_bps_total"] == 10000

        allocations = claim_allocations(api, context["claim_id"])
        by_name = {a["beneficiary_name"]: a for a in allocations}
        assert by_name["Rowan Heir"]["gross_amount_usd"] == pytest.approx(1_004_899.53, abs=0.01)
        assert by_name["Sasha Heir"]["gross_amount_usd"] == pytest.approx(1_004_899.53, abs=0.01)
        assert by_name["Tamsin Heir"]["gross_amount_usd"] == pytest.approx(
            1_005_201.02, abs=0.01
        ), "the single signed residual of one cent lands on the greatest share"

        assert_death_benefit_conservation(sealed, allocations)


class TestClaimDimensionsAreIndependent:
    def test_voiding_one_share_reverts_only_the_distribution_dimension(self, api):
        """A distribution-dimension revert leaves the adjudication decision standing.

        "Voiding an allocation sets its `status` to `VOIDED` and its
        `gross_amount_usd` to 0.00, reduces the claim's `allocated_bps_total` by
        the voided `allocation_pct_bps`, reverts the claim's distribution
        dimension `ALLOCATED → NOT_STARTED`". "Note what the revert leaves alone:
        `adjudication_status` stays at `APPROVED`, so the administrator can
        correct a share and re-seal without re-adjudicating."

        Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_move_independently
        """
        context = _placed_policy(api, MERIDIAN, BHATT, "MD-0001", "Meridian GA BOLI")
        move_clock(api, "2026-11-15T00:00:00Z")
        claim = approved_claim(
            api,
            context["policy_id"],
            terminal_dividend_usd=0.00,
            date_of_death="2026-11-10T00:00:00Z",
        )
        spouse = add_allocation(
            api,
            claim["id"],
            beneficiary_name="Nita Bhatt",
            relationship="SPOUSE",
            allocation_pct_bps=6000,
        )
        child = add_allocation(
            api,
            claim["id"],
            beneficiary_name="Ravi Bhatt",
            relationship="CHILD",
            allocation_pct_bps=4000,
        )
        seal_allocations(api, claim["id"])

        voided = validate_success(api.void_beneficiary_allocation(child["id"], CLAIMS))
        assert voided["status"] == "VOIDED"
        assert voided["gross_amount_usd"] == pytest.approx(0.00, abs=0.01)

        after = validate_success(api.get_death_claim(claim["id"], CLAIMS))
        assert after["distribution_status"] == "NOT_STARTED"
        assert after["adjudication_status"] == "APPROVED", (
            "the adjudication dimension is untouched by the distribution revert"
        )
        assert after["allocated_bps_total"] == 6000
        assert after["survivor_entitlement_usd"] == pytest.approx(3_000_000.00, abs=0.01)
        assert after["bank_portion_usd"] == pytest.approx(2_000_000.00, abs=0.01)

        surviving = validate_success(api.get_beneficiary_allocation(spouse["id"], CLAIMS))
        assert surviving["status"] == "ACTIVE"
        assert surviving["gross_amount_usd"] == pytest.approx(1_800_000.00, abs=0.01)

    def test_the_filing_side_effects_survive_the_distribution_revert(self, api):
        """What filing did to the policy and the employee is unaffected.

        Filing set the policy and the employee, since "the policy advances
        `IN_FORCE → CLAIM_PENDING` with its `version` incremented by 1; and the
        insured employee's `employment_status` is set to `DECEASED`". Voiding a
        single allocation touches only the distribution dimension, so both stay
        where filing put them.

        Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_move_independently
        """
        context = _placed_policy(api, MERIDIAN, BHATT, "MD-0001", "Meridian GA BOLI")
        move_clock(api, "2026-11-15T00:00:00Z")
        claim = approved_claim(
            api,
            context["policy_id"],
            terminal_dividend_usd=0.00,
            date_of_death="2026-11-10T00:00:00Z",
        )
        add_allocation(
            api,
            claim["id"],
            beneficiary_name="Nita Bhatt",
            relationship="SPOUSE",
            allocation_pct_bps=6000,
        )
        child = add_allocation(
            api,
            claim["id"],
            beneficiary_name="Ravi Bhatt",
            relationship="CHILD",
            allocation_pct_bps=4000,
        )
        seal_allocations(api, claim["id"])
        validate_success(api.void_beneficiary_allocation(child["id"], CLAIMS))

        policy = validate_success(api.get_policy(context["policy_id"], RISK))
        assert policy["status"] == "CLAIM_PENDING"

        employee = validate_success(api.get_employee(context["employee_id"], CLAIMS))
        assert employee["employment_status"] == "DECEASED"


class TestVoidAndReplaceRestoresConservation:
    def test_voiding_a_share_frees_its_basis_points_for_a_replacement(self, api):
        """The freed basis points are exactly what the replacement needs.

        Because "Allocations in `VOIDED` contribute neither basis points nor
        amounts", the running total drops to 6666 and a replacement share of
        3334 basis points is accepted, since "The running total of `ACTIVE`
        allocations may never exceed 10000 basis points on a create".

        Design: Difficulty/compensating_invariant/void_and_replace_allocation_restores_death_benefit_conservation
        """
        context = _claim_with_thirds(
            api,
            YARROW,
            FERRARO,
            "YR-0001",
            "Yarrow GA BOLI",
            terminal_dividend_usd=25_000.13,
            date_of_death="2026-08-20T00:00:00Z",
        )
        seal_allocations(api, context["claim_id"])
        allocations = claim_allocations(api, context["claim_id"])
        largest = next(a for a in allocations if a["allocation_pct_bps"] == 3334)

        voided = validate_success(api.void_beneficiary_allocation(largest["id"], CLAIMS))
        assert voided["status"] == "VOIDED"
        assert voided["gross_amount_usd"] == pytest.approx(0.00, abs=0.01)

        after_void = validate_success(api.get_death_claim(context["claim_id"], CLAIMS))
        assert after_void["allocated_bps_total"] == 6666
        assert after_void["distribution_status"] == "NOT_STARTED"
        assert after_void["adjudication_status"] == "APPROVED"

        replacement = add_allocation(
            api,
            context["claim_id"],
            beneficiary_name="Ugo Heir",
            relationship="TRUST",
            allocation_pct_bps=3334,
        )
        assert replacement["status"] == "ACTIVE"
        assert replacement["gross_amount_usd"] == pytest.approx(0.00, abs=0.01)

        restored = validate_success(api.get_death_claim(context["claim_id"], CLAIMS))
        assert restored["allocated_bps_total"] == 10000

    def test_resealing_the_replaced_split_reproduces_exact_conservation(self, api):
        """Re-sealing recomputes every share and the identity holds to the cent.

        Sealing again requires the same exact total, since the "`ACTIVE`
        allocations must sum to" exactly "10000 basis points, with any other
        total refused as `ERR_BENEFICIARY_TOTAL_INVALID`", and afterwards "the
        conservation identity must hold exactly: the `total_death_benefit_usd`
        equals `bank_portion_usd` plus the sum of `gross_amount_usd` over the
        claim's `ACTIVE` allocations." The voided share stays at 0.00 and
        contributes nothing.

        Design: Difficulty/compensating_invariant/void_and_replace_allocation_restores_death_benefit_conservation
        """
        context = _claim_with_thirds(
            api,
            YARROW,
            FERRARO,
            "YR-0001",
            "Yarrow GA BOLI",
            terminal_dividend_usd=25_000.13,
            date_of_death="2026-08-20T00:00:00Z",
        )
        seal_allocations(api, context["claim_id"])
        allocations = claim_allocations(api, context["claim_id"])
        largest = next(a for a in allocations if a["allocation_pct_bps"] == 3334)
        validate_success(api.void_beneficiary_allocation(largest["id"], CLAIMS))
        replacement = add_allocation(
            api,
            context["claim_id"],
            beneficiary_name="Ugo Heir",
            relationship="TRUST",
            allocation_pct_bps=3334,
        )

        resealed = seal_allocations(api, context["claim_id"])
        assert resealed["distribution_status"] == "ALLOCATED"
        assert resealed["survivor_entitlement_usd"] == pytest.approx(3_015_000.08, abs=0.01)
        assert resealed["bank_portion_usd"] == pytest.approx(2_010_000.05, abs=0.01)

        new_share = validate_success(api.get_beneficiary_allocation(replacement["id"], CLAIMS))
        assert new_share["gross_amount_usd"] == pytest.approx(1_005_201.02, abs=0.01), (
            "the replacement carries the greatest share and so absorbs the residual"
        )

        stale = validate_success(api.get_beneficiary_allocation(largest["id"], CLAIMS))
        assert stale["status"] == "VOIDED"
        assert stale["gross_amount_usd"] == pytest.approx(0.00, abs=0.01)

        final_allocations = claim_allocations(api, context["claim_id"])
        assert_death_benefit_conservation(resealed, final_allocations)

    def test_sealing_below_ten_thousand_basis_points_is_refused(self, api):
        """A split that no longer totals the full share cannot be sealed.

        The guard is exact: the "`ACTIVE` allocations must sum to" exactly
        "10000 basis points, with any other total refused as
        `ERR_BENEFICIARY_TOTAL_INVALID`". With one share voided the total stands
        at 6666, so the claim cannot be re-sealed until it is replaced.

        Design: Difficulty/compensating_invariant/void_and_replace_allocation_restores_death_benefit_conservation
        """
        context = _claim_with_thirds(
            api,
            YARROW,
            FERRARO,
            "YR-0001",
            "Yarrow GA BOLI",
            terminal_dividend_usd=25_000.13,
            date_of_death="2026-08-20T00:00:00Z",
        )
        seal_allocations(api, context["claim_id"])
        allocations = claim_allocations(api, context["claim_id"])
        largest = next(a for a in allocations if a["allocation_pct_bps"] == 3334)
        validate_success(api.void_beneficiary_allocation(largest["id"], CLAIMS))

        validate_error(
            api.seal_claim_allocations(context["claim_id"], CLAIMS),
            "ERR_BENEFICIARY_TOTAL_INVALID",
            422,
        )

        after = validate_success(api.get_death_claim(context["claim_id"], CLAIMS))
        assert after["distribution_status"] == "NOT_STARTED"
        assert after["allocated_bps_total"] == 6666
