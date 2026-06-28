"""Claim adjudication (labor cap, rounding, coverage filtering) and payout (deductible).

Translates corner-design calculations + endpoints/consistency instances and the
difficulty-design combinatorial_formula labor-rounding instance.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
)
from test_helpers.fixtures import setup_under_review_claim, setup_submitted_claim

ADJUSTER = TEST_USERS["claims_adjuster_headers"]


def test_uncovered_line_contributes_zero(api):
    """PRD §3.4: "For any line whose `covered` flag is false, the line's
    `allowed_amount_cents` is 0."

    Design: Corner/calculations/uncovered_line_contributes_zero
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "mixed"},
        claim_lines=[
            {"line_type": "PART", "part_number": "C-1", "requested_amount_cents": 10000, "covered": True},
            {"line_type": "PART", "part_number": "U-1", "requested_amount_cents": 50000, "covered": False},
        ],
        pool_name="Pool UNC",
        contract_overrides={"vin": "VINUNC0001"},
    )
    assert base["claim"]["adjudicated_amount_cents"] == 10000, \
        f"expected 10000 (uncovered excluded), got {base['claim']['adjudicated_amount_cents']}"


def test_labor_rate_capped_at_plan_cap(api):
    """PRD §3.4: "the effective labor rate is the lesser of the facility's
    `posted_labor_rate_cents_per_hour` and the plan's `labor_rate_cap_cents_per_hour`;
    that effective rate is multiplied by the line's `labor_hours`".

    Design: Corner/calculations/labor_rate_capped_at_plan_cap
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "labor"},
        claim_lines=[{"line_type": "LABOR", "labor_hours": 2.0, "covered": True}],
        facility_overrides={"name": "Pricey Shop", "posted_labor_rate_cents_per_hour": 15000, "direct_pay_enrolled": True},
        pool_name="Pool CAP",
        contract_overrides={"vin": "VINCAP0001"},
    )
    assert base["claim"]["adjudicated_amount_cents"] == 24000, \
        f"expected 24000 (capped at 12000/hr), got {base['claim']['adjudicated_amount_cents']}"


def test_deductible_floored_when_covered_below_deductible(api):
    """PRD §3.5: "The deductible applied is the lesser of that covered repair amount
    and the plan's `deductible_cents`, so it never exceeds the covered repair and
    never drives the net below zero (the deductible floor is zero)."

    Design: Corner/calculations/deductible_floored_when_covered_below_deductible
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "sensor"},
        claim_lines=[{"line_type": "PART", "part_number": "SN-1", "requested_amount_cents": 3000, "covered": True}],
        facility_overrides={"name": "Shop", "posted_labor_rate_cents_per_hour": 9500,
                            "network_status": "IN_NETWORK", "direct_pay_enrolled": True},
        pool_name="Pool DED",
        contract_overrides={"vin": "VINDED0001"},
    )
    from test_helpers.fixtures import api_client
    api_client.approve_claim(base["claim"]["id"], ADJUSTER)
    auth = validate_success(api.authorize_claim(base["claim"]["id"], ADJUSTER), expected_status=201)
    assert auth["deductible_applied_cents"] == 3000, \
        f"expected deductible 3000 (min of covered, deductible), got {auth['deductible_applied_cents']}"
    assert auth["total_payout_cents"] == 0, \
        f"expected total payout floored at 0, got {auth['total_payout_cents']}"


def test_labor_round_per_line_then_sum(api):
    """PRD §3.4: "each line is computed and rounded to whole cents, and only then are
    the rounded lines summed — summing raw amounts and rounding once at the end is
    explicitly not used."
    PRD §3.4: "that effective rate is multiplied by the line's `labor_hours`, and the
    product is rounded half up to whole cents to give the line's allowed amount."

    Design: Difficulty/combinatorial_formula/labor_round_per_line_then_sum
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "noise"},
        claim_lines=[
            {"line_type": "LABOR", "labor_hours": 1.15, "covered": True},
            {"line_type": "LABOR", "labor_hours": 0.05, "covered": True},
        ],
        facility_overrides={"name": "Shop", "posted_labor_rate_cents_per_hour": 9500, "direct_pay_enrolled": True},
        pool_name="Pool R",
        contract_overrides={"vin": "VINROUND001"},
    )
    # 1.15*9500 = 10925.0 -> 10925 ; 0.05*9500 = 475.0 -> 475 ; sum = 11400
    assert base["claim"]["adjudicated_amount_cents"] == 11400, \
        f"expected 11400 (10925 + 475, rounded per line then summed), got {base['claim']['adjudicated_amount_cents']}"


def test_immediate_visibility_of_adjudicated_amount(api):
    """PRD §3.4: "When review starts, the system runs the adjudication computation to
    set each line's `allowed_amount_cents` and the claim's `adjudicated_amount_cents`".

    Design: Corner/consistency_model/immediate_visibility_of_adjudicated_amount
    """
    base = setup_submitted_claim(
        claim_overrides={"complaint": "x"},
        claim_lines=[{"line_type": "PART", "part_number": "IM-1", "requested_amount_cents": 10000, "covered": True}],
        facility_overrides={"name": "Shop", "posted_labor_rate_cents_per_hour": 9500, "direct_pay_enrolled": True},
        pool_name="Pool IM",
        contract_overrides={"vin": "VINIM00001"},
    )
    resp = validate_success(api.start_review_claim(base["claim"]["id"], ADJUSTER))
    assert resp["adjudicated_amount_cents"] == 10000, \
        f"start-review response must immediately reflect adjudicated 10000, got {resp['adjudicated_amount_cents']}"
