"""Shoppable-service comparison: median/min negotiated allowed and self-pay price."""
from test_helpers import validate_success, fixtures, TEST_USERS

PATIENT_PLACEHOLDER = TEST_USERS["patient_headers"]


# --------------------------------------------------------------------------
# Difficulty — MEDIAN vs MIN variants (odd count of three)
# --------------------------------------------------------------------------
def test_comparison_median_of_three(api):
    """PRD §3.1: "median_allowed_cents is the middle value when the count is odd,
    or the mean of the two middle values rounded half up to whole cents when the
    count is even." PRD §3.1: "The count of qualifying rates is returned as
    sample_count."

    Design: Difficulty/dual_variant_calc/dv_shoppable_median_vs_min
    """
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    fixtures.three_active_flat_rates(api, procedure["id"], [100000, 150000, 250000])
    data = validate_success(api.get_comparison(procedure["id"], PATIENT_PLACEHOLDER), 200)
    assert data["sample_count"] == 3
    assert data["median_allowed_cents"] == 150000


def test_comparison_min_and_self_pay(api):
    """PRD §3.1: "min_allowed_cents is the smallest ... a self_pay_price_cents
    equal to the gross charge multiplied by 0.65 — that is, the gross charge less
    a 35% self-pay discount — rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/dv_shoppable_median_vs_min
    """
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    fixtures.three_active_flat_rates(api, procedure["id"], [100000, 150000, 250000])
    data = validate_success(api.get_comparison(procedure["id"], PATIENT_PLACEHOLDER), 200)
    assert data["min_allowed_cents"] == 100000
    assert data["self_pay_price_cents"] == 195000


# --------------------------------------------------------------------------
# Corner — even count median averages the two middle values
# --------------------------------------------------------------------------
def test_comparison_even_count_median_averages_middle_two(api):
    """PRD §3.1: "median_allowed_cents is the middle value when the count is odd,
    or the mean of the two middle values rounded half up to whole cents when the
    count is even."

    Design: Corner/calculations/comparison_even_count_median_averages_middle_two
    """
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    fixtures.three_active_flat_rates(
        api, procedure["id"], [100000, 150000, 200000, 300000])
    data = validate_success(api.get_comparison(procedure["id"], PATIENT_PLACEHOLDER), 200)
    assert data["sample_count"] == 4
    assert data["median_allowed_cents"] == 175000  # (150000 + 200000) / 2
    assert data["min_allowed_cents"] == 100000


# --------------------------------------------------------------------------
# Difficulty — empty rate set boundary
# --------------------------------------------------------------------------
def test_comparison_empty_rate_set_nulls(api):
    """PRD §3.1: "When `sample_count` is zero, both `median_allowed_cents` and
    `min_allowed_cents` are null."

    Design: Difficulty/boundary_precision_check/bpc_comparison_empty_rate_set
    """
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    data = validate_success(api.get_comparison(procedure["id"], PATIENT_PLACEHOLDER), 200)
    assert data["sample_count"] == 0
    assert data["median_allowed_cents"] is None
    assert data["min_allowed_cents"] is None


def test_comparison_empty_rate_set_self_pay_still_computed(api):
    """PRD §3.1: "Alongside these, the response reports the procedure's own
    gross_charge_cents and a self_pay_price_cents equal to the gross charge
    multiplied by 0.65 ... rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/bpc_comparison_empty_rate_set
    """
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    data = validate_success(api.get_comparison(procedure["id"], PATIENT_PLACEHOLDER), 200)
    assert data["self_pay_price_cents"] == 195000
    assert data["gross_charge_cents"] == 300000
