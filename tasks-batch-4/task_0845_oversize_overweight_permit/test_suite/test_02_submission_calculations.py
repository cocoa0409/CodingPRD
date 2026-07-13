"""Submission-time calculations: classification, escort requirement, permit fee
(dual variant + per-segment rounding), superload boundary, bond amount, and the
repeat-multiplier violation penalty.

Difficulty instances get >=2 tests each; corner instances get >=1.
"""
from test_helpers import (
    TEST_USERS, make_carrier_headers,
    validate_success, validate_paginated,
    new_carrier, new_permit, add_segment, submit,
    create_violation_payload,
)

ENFORCER = TEST_USERS["enforcement_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / fee_single_vs_annual_variant
# ---------------------------------------------------------------------------
def _build_single_and_annual(api):
    carrier = new_carrier(api)
    single = new_permit(api, carrier["id"], length_in=900, width_in=100, height_in=100,
                        front_overhang_in=80, rear_overhang_in=0, gross_weight_lbs=120000, num_axles=9)
    add_segment(api, single["id"], carrier["id"], sequence_index=1, from_milepost=0, to_milepost=10.1)
    add_segment(api, single["id"], carrier["id"], sequence_index=2, from_milepost=10.1, to_milepost=20.2)
    annual = new_permit(api, carrier["id"], permit_type="ANNUAL", length_in=900, width_in=100, height_in=100,
                        front_overhang_in=80, rear_overhang_in=0, gross_weight_lbs=120000, num_axles=9,
                        valid_from="2026-06-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
    add_segment(api, annual["id"], carrier["id"], sequence_index=1, from_milepost=0, to_milepost=10.1)
    single_after = submit(api, single["id"], carrier["id"])
    annual_after = submit(api, annual["id"], carrier["id"])
    return single_after, annual_after


def test_single_trip_fee_and_classification(api):
    """PRD §3.3: "For a `SINGLE_TRIP` permit, the fee is a base of 1500 cents,
    plus a mileage total, plus all three surcharges; the mileage total is computed
    by taking each route segment's `miles` multiplied by 25 cents per mile,
    rounding that per-segment product half up to whole cents first, and then
    summing the rounded per-segment amounts (segments taken in ascending
    `sequence_index` order) — the per-segment rounding happens before summation,
    never after."

    Design: Difficulty/dual_variant_calc/fee_single_vs_annual_variant
    """
    single, _annual = _build_single_and_annual(api)
    assert single["classification"] == "OVERSIZE_OVERWEIGHT"
    assert single["fee_cents"] == 45006


def test_annual_fee_differs_from_single(api):
    """PRD §3.3: "For an `ANNUAL` permit, the fee is a flat base of 40000 cents
    plus the oversize and overweight surcharges only, with no mileage term and no
    superload surcharge (an annual superload is disallowed at submission)."

    Design: Difficulty/dual_variant_calc/fee_single_vs_annual_variant
    """
    single, annual = _build_single_and_annual(api)
    assert annual["fee_cents"] == 83000
    assert single["fee_cents"] != annual["fee_cents"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / fee_per_segment_round_then_sum
# ---------------------------------------------------------------------------
def _build_round_then_sum(api):
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], length_in=900, width_in=100, height_in=100,
                        front_overhang_in=80, rear_overhang_in=0, gross_weight_lbs=120000, num_axles=9)
    add_segment(api, permit["id"], carrier["id"], sequence_index=1, from_milepost=0, to_milepost=10.1)
    add_segment(api, permit["id"], carrier["id"], sequence_index=2, from_milepost=10.1, to_milepost=20.2)
    return submit(api, permit["id"], carrier["id"])


def test_fee_per_segment_rounding_total(api):
    """PRD §3.3: "the mileage total is computed by taking each route segment's
    `miles` multiplied by 25 cents per mile, rounding that per-segment product
    half up to whole cents first, and then summing the rounded per-segment amounts
    (segments taken in ascending `sequence_index` order) — the per-segment
    rounding happens before summation, never after."

    Design: Difficulty/combinatorial_formula/fee_per_segment_round_then_sum
    """
    permit = _build_round_then_sum(api)
    assert permit["fee_cents"] == 45006


def test_fee_rejects_sum_then_round_order(api):
    """PRD §3.3: "the per-segment rounding happens before summation, never after."

    Two 10.1-mile segments round to 253 + 253 = 506 cents; the forbidden
    sum-then-round (20.2 * 25 = 505) would make the total 45005, so the correct
    result is 45006 and must not equal 45005.

    Design: Difficulty/combinatorial_formula/fee_per_segment_round_then_sum
    """
    permit = _build_round_then_sum(api)
    assert permit["fee_cents"] == 45006
    assert permit["fee_cents"] != 45005


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / escort_nested_max_tiered
# ---------------------------------------------------------------------------
def _build_escort_nested(api):
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], length_in=1000, width_in=180, height_in=170,
                        front_overhang_in=0, rear_overhang_in=0, gross_weight_lbs=210000, num_axles=13)
    add_segment(api, permit["id"], carrier["id"], sequence_index=1, from_milepost=0, to_milepost=15)
    return submit(api, permit["id"], carrier["id"])


def test_escort_requirement_nested_max(api):
    """PRD §3.3: "The required escort count is the greater of the width and length
    components, plus the height component, plus the police component."

    Design: Difficulty/combinatorial_formula/escort_nested_max_tiered
    """
    permit = _build_escort_nested(api)
    assert permit["required_escort_count"] == 4


def test_escort_load_classifies_superload(api):
    """PRD §3.3: "It is a *superload* if its `width_in` is at least 192 inches, or
    its `height_in` is at least 204 inches, or its `length_in` is at least 1560
    inches, or its `gross_weight_lbs` is at least 200000 pounds — so a load of
    exactly 200000 pounds is a superload while 199999 pounds is not."

    Design: Difficulty/combinatorial_formula/escort_nested_max_tiered
    """
    permit = _build_escort_nested(api)
    assert permit["classification"] == "SUPERLOAD"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / superload_weight_ge_200000_boundary
# ---------------------------------------------------------------------------
def _submit_gross(api, gross):
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], length_in=900, width_in=100, height_in=100,
                        gross_weight_lbs=gross, num_axles=13)
    add_segment(api, permit["id"], carrier["id"])
    return submit(api, permit["id"], carrier["id"])


def test_superload_boundary_at_threshold(api):
    """PRD §3.3: "It is a *superload* if ... its `gross_weight_lbs` is at least
    200000 pounds — so a load of exactly 200000 pounds is a superload while 199999
    pounds is not."

    Design: Difficulty/boundary_precision_check/superload_weight_ge_200000_boundary
    """
    permit = _submit_gross(api, 200000)
    assert permit["classification"] == "SUPERLOAD"


def test_superload_boundary_just_below(api):
    """PRD §3.3: "It is a *superload* if ... its `gross_weight_lbs` is at least
    200000 pounds — so a load of exactly 200000 pounds is a superload while 199999
    pounds is not."

    Design: Difficulty/boundary_precision_check/superload_weight_ge_200000_boundary
    """
    permit = _submit_gross(api, 199999)
    assert permit["classification"] == "OVERWEIGHT"


# ---------------------------------------------------------------------------
# Corner: calculations
# ---------------------------------------------------------------------------
def test_superload_bond_amount(api):
    """PRD §3.3: "For a superload, the `Bond` created at submission has its
    `amount_cents` computed as a base of 5000000 cents plus, for the amount by
    which `gross_weight_lbs` exceeds 200000 pounds divided by 1000 and rounded up
    to the next whole number, 100000 cents per each such thousand pounds."

    Design: Corner/calculations/superload_bond_amount_and_reverse_lookup
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=210000, num_axles=13)
    add_segment(api, permit["id"], carrier["id"])
    submit(api, permit["id"], carrier["id"])
    resp = api.list_bonds(make_carrier_headers(carrier["id"]), params={"permit_id": permit["id"]})
    bonds, _meta = validate_paginated(resp)
    assert len(bonds) == 1
    assert bonds[0]["amount_cents"] == 6000000
    assert bonds[0]["status"] == "DRAFT"


def test_violation_penalty_repeat_multiplier(api):
    """PRD §3.8: "multiplied by a severity multiplier of 1 for `MINOR`, 2 for
    `MAJOR`, or 3 for `CRITICAL`, and then by a repeat multiplier. The repeat
    multiplier is 1 plus 0.5 times the number of the carrier's violations already
    in `UPHELD` status, counted in ascending `created_at` order as of the instant
    of creation; the final product is rounded half up to whole cents."

    Design: Corner/calculations/violation_penalty_repeat_multiplier
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"])
    v1 = validate_success(
        api.create_violation(create_violation_payload(permit["id"], violation_type="OVER_DIMENSION", severity="MAJOR"), ENFORCER), 201)
    assert v1["penalty_cents"] == 200000
    validate_success(api.uphold_violation(v1["id"], ENFORCER), 200)
    v2 = validate_success(
        api.create_violation(create_violation_payload(permit["id"], violation_type="OVER_DIMENSION", severity="MAJOR"), ENFORCER), 201)
    assert v2["penalty_cents"] == 300000
