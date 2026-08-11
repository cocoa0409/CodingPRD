"""Boundary precision: inclusive tier thresholds on year-to-date net volume
(PRD §3.1) and the inclusive VOC limit (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_order_payload,
    create_product,
    create_voc_rule,
    get_account_version,
    place_and_pay_order,
    place_order,
    setup_account_job_product,
    setup_account_with_job,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


def _drive_volume_and_evaluate(api, company_name, volume_cents,
                               jurisdiction_code, sku):
    """One paid order whose subtotal equals volume_cents, then evaluate-tier."""
    account, _, job, product = setup_account_job_product(
        company_name=company_name, credit_limit_cents=100_000_000,
        jurisdiction_code=jurisdiction_code, job_name="J",
        sku=sku, list_price_cents=volume_cents)
    place_and_pay_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}],
                        headers=ASSOCIATE)
    resp = api.evaluate_tier(account["id"], ADMIN)
    return validate_success(resp, expected_status=200)


def test_volume_exactly_at_gold_threshold_earns_gold(api):
    """PRD §3.1: "The evaluation recomputes `ytd_net_volume_cents` at that
    instant and assigns `tier` by inclusive thresholds: `PLATINUM` when the
    volume reaches 40,000,000 cents ($400,000), otherwise `GOLD` when it
    reaches 15,000,000 cents ($150,000), otherwise `SILVER` when it reaches
    5,000,000 cents ($50,000), otherwise `STANDARD`. A volume exactly equal to
    a threshold earns that tier."

    Design: Difficulty/boundary_precision_check/tier_gold_threshold_inclusive
    """
    account = _drive_volume_and_evaluate(api, "A Exact", 15_000_000,
                                         "TX-B", "P-EXACT")
    assert account["tier"] == "GOLD", (
        f"V == 15000000 meets >= GOLD_MIN_CENTS inclusively, "
        f"got {account['tier']}")


def test_volume_one_cent_below_gold_stays_silver(api):
    """PRD §3.1: "The evaluation recomputes `ytd_net_volume_cents` at that
    instant and assigns `tier` by inclusive thresholds: `PLATINUM` when the
    volume reaches 40,000,000 cents ($400,000), otherwise `GOLD` when it
    reaches 15,000,000 cents ($150,000), otherwise `SILVER` when it reaches
    5,000,000 cents ($50,000), otherwise `STANDARD`. A volume exactly equal to
    a threshold earns that tier."

    One cent below the boundary does not reach it: 14,999,999 is SILVER.

    Design: Difficulty/boundary_precision_check/tier_gold_threshold_inclusive
    """
    account = _drive_volume_and_evaluate(api, "B Below", 14_999_999,
                                         "TX-B2", "P-BELOW")
    assert account["tier"] == "SILVER", (
        f"V == 14999999 is one cent below the GOLD threshold, "
        f"got {account['tier']}")


def _setup_voc_boundary(api):
    """Jurisdiction with a FLAT 250 gpl open-ended rule; products at exactly
    250 and at 251."""
    account, _, job = setup_account_with_job(
        company_name="Eq Co", credit_limit_cents=100_000_000,
        jurisdiction_code="CA-BAAQMD", jurisdiction_name="BAAQMD",
        job_name="SF Site")
    create_voc_rule(job["jurisdiction_id"], category="FLAT", max_voc_gpl=250,
                    effective_from="2026-01-01T00:00:00Z")
    p_eq = create_product(sku="P-EQ", name="Boundary Flat", category="FLAT",
                          voc_gpl=250, list_price_cents=10_000)
    p_over = create_product(sku="P-OVER", name="Over Flat", category="FLAT",
                            voc_gpl=251, list_price_cents=10_000)
    return account, job, p_eq, p_over


def test_voc_exactly_at_limit_is_compliant(api):
    """PRD §3.3: "Against each jurisdiction, VOC rules cap the
    volatile-organic-compound content of coatings: a rule carries its
    `jurisdiction_id`, a `category` of `FLAT`, `NON_FLAT`, or
    `INDUSTRIAL_MAINTENANCE`, a `max_voc_gpl` limit in grams per liter
    (greater than zero, and an inclusive bound — a product at exactly the
    limit is compliant), an `effective_from` instant (inclusive), and an
    optional `effective_to` (exclusive; null means open-ended)."

    Design: Difficulty/boundary_precision_check/voc_limit_equality_compliant
    """
    account, job, p_eq, _ = _setup_voc_boundary(api)
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": p_eq["id"], "quantity": 1}]),
        ASSOCIATE)
    order = validate_success(resp, expected_status=201)
    assert order["id"], "equality with the limit is compliant (<=)"


def test_voc_one_over_limit_rejected(api):
    """PRD §3.8: "for every line of the order, the product's `voc_gpl` must
    not exceed the `max_voc_gpl` of the VOC rule effective at the logical
    clock now for the pair of the job's `jurisdiction_id` and the product's
    `category` (a jurisdiction-and-category pair with no effective rule is
    unrestricted)." PRD §3.3: "Against each jurisdiction, VOC rules cap the
    volatile-organic-compound content of coatings: a rule carries its
    `jurisdiction_id`, a `category` of `FLAT`, `NON_FLAT`, or
    `INDUSTRIAL_MAINTENANCE`, a `max_voc_gpl` limit in grams per liter
    (greater than zero, and an inclusive bound — a product at exactly the
    limit is compliant), an `effective_from` instant (inclusive), and an
    optional `effective_to` (exclusive; null means open-ended)."

    At 251 against a 250 limit the order is rejected.

    Design: Difficulty/boundary_precision_check/voc_limit_equality_compliant
    """
    account, job, _, p_over = _setup_voc_boundary(api)
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": p_over["id"], "quantity": 1}]),
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_VOC_LIMIT_EXCEEDED)
