"""License-fee pricing: residency multiplier and multiply-then-add rounding order.

PRD §3.5 governs all license pricing. These tests pin the divergence between resident
and non-resident pricing and the fixed two-step evaluation order (multiply-then-round
before the additive agent surcharge).
"""
from test_helpers import (
    validate_success, assert_license,
    create_resident_applicant, create_nonresident_applicant,
    create_product, issue_otc_license, set_clock,
    create_license_payload, TEST_USERS,
)

AGENT = TEST_USERS["license_agent_headers"]


def test_resident_otc_fee_is_base_plus_surcharge(api):
    """PRD §3.5: "For a resident applicant the base is taken as-is."
    PRD §3.5: "Then, and only when the license is being issued over the counter, a flat
    agent surcharge of 300 cents is added to the priced amount."

    Design: Difficulty/dual_variant_calc/license_fee_resident_vs_nonresident_diverge
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-DUCK", product_kind="STAMP",
                             base_fee_cents=4500, residency_restriction="ANY")
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")

    res = api.create_license(
        create_license_payload(applicant["id"], product["id"]), AGENT)
    license_ = validate_success(res, 201)
    assert_license(license_)
    assert license_["fee_charged_cents"] == 4800, (
        f"resident OTC fee should be 4500 base + 300 surcharge, got "
        f"{license_['fee_charged_cents']}")


def test_nonresident_otc_fee_diverges_from_resident(api):
    """PRD §3.5: "For a non-resident applicant the base is multiplied by the non-resident
    multiplier of 2.5 and that product is rounded half up to whole cents — this rounding
    happens here, before any surcharge."
    PRD §3.5: "Because the multiply-then-round happens strictly before the additive surcharge, a resident and a non-resident buying the same product over the counter diverge in price by more than a flat offset."

    Design: Difficulty/dual_variant_calc/license_fee_resident_vs_nonresident_diverge
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-DUCK", product_kind="STAMP",
                             base_fee_cents=4500, residency_restriction="ANY")
    res_applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    nr_applicant = create_nonresident_applicant(full_name="A NR", declared_state_code="CA")

    res_lic = validate_success(api.create_license(
        create_license_payload(res_applicant["id"], product["id"]), AGENT), 201)
    nr_lic = validate_success(api.create_license(
        create_license_payload(nr_applicant["id"], product["id"]), AGENT), 201)

    assert res_lic["fee_charged_cents"] == 4800
    assert nr_lic["fee_charged_cents"] == 11550, (
        f"non-resident OTC fee should be round(4500*2.5)=11250 + 300 = 11550, got "
        f"{nr_lic['fee_charged_cents']}")
    assert nr_lic["fee_charged_cents"] - res_lic["fee_charged_cents"] != 300, (
        "resident and non-resident must diverge by more than a flat 300-cent offset")


def test_nonresident_multiply_then_add_rounding_order_pinned(api):
    """PRD §3.5: "For a non-resident applicant the base is multiplied by the non-resident
    multiplier of 2.5 and that product is rounded half up to whole cents — this rounding
    happens here, before any surcharge."
    PRD §2.8: "the rounding method is round half up, applied exactly once and at the point
    the specification names, never re-rounded downstream."

    Design: Difficulty/combinatorial_formula/license_fee_multiply_then_add_rounding_order_pinned
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-TROUT", product_kind="STAMP",
                             base_fee_cents=4500, residency_restriction="ANY")
    nr_applicant = create_nonresident_applicant(full_name="A NR", declared_state_code="CA")

    license_ = validate_success(api.create_license(
        create_license_payload(nr_applicant["id"], product["id"]), AGENT), 201)
    # Pinned order: round(4500 * 2.5) = 11250, then + 300 = 11550.
    # Reversed order round((4500+300)*2.5) = 12000 would diverge.
    assert license_["fee_charged_cents"] == 11550, (
        f"expected multiply-then-add order to yield 11550, got "
        f"{license_['fee_charged_cents']} (12000 would indicate the surcharge was added "
        f"before the multiplier)")


def test_nonresident_otc_fee_value_exact(api):
    """PRD §3.5: "Then, and only when the license is being issued over the counter, a flat
    agent surcharge of 300 cents is added to the priced amount. The resulting amount is the
    `fee_charged_cents`."

    Design: Difficulty/combinatorial_formula/license_fee_multiply_then_add_rounding_order_pinned
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-SALMON", product_kind="STAMP",
                             base_fee_cents=4500, residency_restriction="ANY")
    nr_applicant = create_nonresident_applicant(full_name="A NR2", declared_state_code="CA")

    license_ = issue_otc_license(nr_applicant["id"], product["id"])
    assert license_["fee_charged_cents"] == 11550
    assert license_["issued_via"] == "OVER_THE_COUNTER"
