"""Rate indication calculation variants and the credibility blend (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_indication,
    assert_pct,
    create_indication,
    create_indication_payload,
    create_product,
    validate_error,
)
from test_helpers import fixtures as fx


def test_incurred_credibility_variant_literal(api):
    """PRD §3.2: "Under the `INCURRED_CREDIBILITY` variant, the incurred losses
    are developed to ultimate by multiplying `incurred_loss_cents` by the loss
    development factor 1.12; those ultimate losses are divided by the product
    of `earned_premium_cents` and the target loss ratio 0.68, and one is
    subtracted from that quotient to yield the experience indication. The
    countrywide complement is then projected forward by one year of trend,
    multiplying `countrywide_change_pct` by one plus `trend_factor`. The
    variant's result is the credibility-weighted blend: `credibility_z` times
    the experience indication, plus the complement of credibility (one minus
    `credibility_z`) times the trended countrywide change."

    Design: Difficulty/dual_variant_calc/indication_incurred_credibility_vs_paid_pure
    """
    product = create_product()
    indication = create_indication(product["id"], product["version"])

    assert_indication(indication)
    # 0.6797847 * 0.1529412 + 0.3202153 * 0.0624 = 0.1239485 -> 0.1239 (4dp)
    assert_pct(indication["indicated_change_pct"], 0.1239)
    # The preserved other variant: (0.65 / 0.68) - 1 = -0.0441176 -> -0.0441
    assert_pct(indication["alternate_change_pct"], -0.0441)


def test_paid_pure_variant_literal(api):
    """PRD §3.2: "Under the `PAID_PURE` variant the result is deliberately
    simpler: `paid_loss_cents` divided by `earned_premium_cents`, that ratio
    divided by the target loss ratio 0.68, minus one — no credibility blend,
    no trend, and no loss development apply. Whichever variant the request
    names is stored as `indicated_change_pct`, and the other variant's result
    is preserved alongside it as `alternate_change_pct`".

    Design: Difficulty/dual_variant_calc/indication_incurred_credibility_vs_paid_pure
    """
    product = create_product()
    indication = create_indication(
        product["id"], product["version"], variant="PAID_PURE"
    )

    assert_indication(indication)
    assert_pct(indication["indicated_change_pct"], -0.0441)
    assert_pct(indication["alternate_change_pct"], 0.1239)
    # Identical inputs diverge in sign between the two variants.
    assert indication["indicated_change_pct"] < 0 < indication["alternate_change_pct"]


def test_partial_credibility_blend_below_full_standard(api):
    """PRD §3.2: "`credibility_z` is the lesser of one and the square root of
    the ratio of `exposure_units` to the full-credibility standard of 1,082
    earned exposures".

    Design: Difficulty/combinatorial_formula/indication_credibility_blend_min_sqrt_branch
    """
    product = create_product()
    indication = create_indication(
        product["id"], product["version"], exposure_units=500
    )

    # Z = sqrt(500/1082) ~= 0.6798: partial blend, countrywide complement active.
    assert indication["credibility_z"] == pytest.approx(0.6798, abs=1e-4)
    assert indication["credibility_z"] < 1
    assert_pct(indication["indicated_change_pct"], 0.1239)


def test_full_credibility_clamps_at_standard(api):
    """PRD §3.2: "`credibility_z` is the lesser of one and the square root of
    the ratio of `exposure_units` to the full-credibility standard of 1,082
    earned exposures — a book with 1,082 or more exposure units is fully
    credible."

    Design: Difficulty/combinatorial_formula/indication_credibility_blend_min_sqrt_branch
    """
    product = create_product()
    indication = create_indication(
        product["id"], product["version"], exposure_units=2000
    )

    # Z clamps at 1: pure experience indication 7840000/6800000 - 1 = 0.15294...
    assert indication["credibility_z"] == 1
    assert_pct(indication["indicated_change_pct"], 0.1529)


def test_indication_create_rejects_computed_field_input(api):
    """PRD §2.5: "Derived and computed fields are maintained by the server and
    are never accepted as client input."
    PRD §2.8: "third, request-body well-formedness — required fields present,
    no unknown fields, types correct, enum members valid, amounts positive,
    dates in ISO format — with violations rejected as `ERR_INVALID_REQUEST`
    (HTTP 400)".

    Design: Corner/entities/create_indication_unknown_field_rejected
    """
    product = create_product()
    payload = create_indication_payload(
        product["id"], product["version"], variant="PAID_PURE"
    )
    payload["indicated_change_pct"] = 0.99  # computed field offered as input
    res = api.create_indication(payload, fx.ACT1)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
