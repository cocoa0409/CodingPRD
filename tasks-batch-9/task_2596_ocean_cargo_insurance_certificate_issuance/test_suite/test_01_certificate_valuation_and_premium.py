"""
Certificate valuation and premium composition at issue.

Covers the two valuation bases a shipment may be declared on, the rounding
order that composes the effective marine rate, the per-component rounding that
builds the premium, and the policy ledgers both variants book onto.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    CERTIFICATE_CIF_SHIPMENT,
    EXPECTED_BASE_PREMIUM,
    EXPECTED_BASE_PREMIUM_DECLARED,
    EXPECTED_BASE_PREMIUM_OVERAGE,
    EXPECTED_EFFECTIVE_RATE,
    EXPECTED_EFFECTIVE_RATE_OVERAGE,
    EXPECTED_INSURED_VALUE_CIF,
    EXPECTED_INSURED_VALUE_DECLARED,
    EXPECTED_STRIKES_PREMIUM,
    EXPECTED_STRIKES_PREMIUM_DECLARED,
    EXPECTED_TOTAL_PREMIUM,
    EXPECTED_TOTAL_PREMIUM_DECLARED,
    EXPECTED_TOTAL_PREMIUM_OVERAGE,
    EXPECTED_WAR_PREMIUM,
    EXPECTED_WAR_PREMIUM_DECLARED,
    UNDERWRITER,
    VESSEL_OLD_SALT,
    ApiClient,
    assert_money,
    assert_rate,
    build_canonical_environment,
    build_draft_certificate,
    create_vessel,
    issue_certificate,
    read_certificate,
    read_policy,
    read_vessel,
)

# The declared-value twin of the canonical CIF shipment: byte-identical
# commercial facts, differing only in the valuation basis and in the agreed
# figure the assured states.
DECLARED_TWIN_VALUE = 1050000

# The overage hull's screened surcharge: a 1996 build is 30 years old against
# the default logical clock.
OVERAGE_SURCHARGE_PCT = 0.25


def _build_two_valuation_variants(api: ApiClient) -> dict:
    """
    One open cover, one approved hull, two green ports and two issued
    certificates that differ only in `valuation_basis`. The CIF twin carries
    invoice 1000000.00, freight 45000.00 and duty 5000.00; the declared twin
    carries the very same three figures plus a stated value of 1050000.00.
    """
    env = build_canonical_environment(api)
    cif_draft = build_draft_certificate(api, env)
    declared_draft = build_draft_certificate(
        api, env,
        base=CERTIFICATE_CIF_SHIPMENT,
        certificate_number="CERT-B",
        valuation_basis="DECLARED_VALUE",
        declared_value=DECLARED_TWIN_VALUE,
    )
    env["cif_certificate"] = issue_certificate(
        api, cif_draft["id"], env["policy_id"])
    env["declared_certificate"] = issue_certificate(
        api, declared_draft["id"], env["policy_id"])
    return env


def _build_two_hull_variants(api: ApiClient) -> dict:
    """
    Two certificates with identical CIF inputs on the same open cover, one on a
    2015-built hull that screens to `APPROVED` and one on a 1996-built hull that
    screens to `OVERAGE_SURCHARGED`.
    """
    env = build_canonical_environment(api)
    env["overage_vessel"] = create_vessel(api, VESSEL_OLD_SALT)
    approved_draft = build_draft_certificate(api, env)
    overage_draft = build_draft_certificate(
        api, env,
        certificate_number="CERT-C",
        vessel_id=env["overage_vessel"]["id"],
    )
    env["approved_certificate"] = issue_certificate(
        api, approved_draft["id"], env["policy_id"])
    env["overage_certificate"] = issue_certificate(
        api, overage_draft["id"], env["policy_id"])
    return env


def test_cif_plus_markup_insures_the_marked_up_cif_base(api: ApiClient) -> None:
    """
    A CIF shipment insures invoice plus duty plus prepaid freight, uplifted by
    the cover's markup and rounded once at the end.

    The insured value is then the CIF base multiplied by one plus the policy's `markup_pct`, and that product is rounded half up to 2 decimals — one rounding, at the very end, never a rounding of the base first.

    Design: Difficulty/dual_variant_calc/certificate_insured_value_cif_markup_vs_declared_value
    """
    env = _build_two_valuation_variants(api)

    issued = read_certificate(api, env["cif_certificate"]["id"])
    assert issued["valuation_basis"] == "CIF_PLUS_MARKUP"
    assert issued["status"] == "ISSUED"
    assert_money(issued["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "cif certificate insured_value")


def test_declared_value_ignores_invoice_freight_duty_and_markup(
        api: ApiClient) -> None:
    """
    A declared-value shipment insures the stated figure alone, diverging from the
    CIF-plus-markup answer by 105000.00 on identical commercial facts.

    Under `DECLARED_VALUE` the insured value is simply the declared figure rounded half up to 2 decimals, and neither invoice, freight, duty nor markup participates: the same shipment declared at 1050000.00 insures for 1050000.00, a divergence of 105000.00 from the CIF-plus-markup answer that then propagates into every premium component, into all three accumulation ledgers and into the general average contributory value.

    Design: Difficulty/dual_variant_calc/certificate_insured_value_cif_markup_vs_declared_value
    """
    env = _build_two_valuation_variants(api)

    declared = read_certificate(api, env["declared_certificate"]["id"])
    cif = read_certificate(api, env["cif_certificate"]["id"])

    assert declared["valuation_basis"] == "DECLARED_VALUE"
    assert declared["status"] == "ISSUED"
    assert_money(declared["insured_value"], EXPECTED_INSURED_VALUE_DECLARED,
                 "declared certificate insured_value")
    assert_money(
        float(cif["insured_value"]) - float(declared["insured_value"]),
        EXPECTED_INSURED_VALUE_CIF - EXPECTED_INSURED_VALUE_DECLARED,
        "valuation divergence")


def test_valuation_variant_propagates_into_every_premium_component(
        api: ApiClient) -> None:
    """
    The two variants share one effective marine rate yet price differently,
    because every component scales with the insured value the variant produced.

    `base_premium_amount` is the insured value divided by 1000 — premium rates in this market are quoted per mille, per thousand units of value — multiplied by the effective marine rate, rounded half up to 2 decimals.

    Design: Difficulty/dual_variant_calc/certificate_insured_value_cif_markup_vs_declared_value
    """
    env = _build_two_valuation_variants(api)

    cif = read_certificate(api, env["cif_certificate"]["id"])
    declared = read_certificate(api, env["declared_certificate"]["id"])

    assert_rate(cif["effective_rate_per_mille"], EXPECTED_EFFECTIVE_RATE,
                label="cif effective_rate_per_mille")
    assert_rate(declared["effective_rate_per_mille"], EXPECTED_EFFECTIVE_RATE,
                label="declared effective_rate_per_mille")

    assert_money(cif["base_premium_amount"], EXPECTED_BASE_PREMIUM,
                 "cif base_premium_amount")
    assert_money(cif["war_premium_amount"], EXPECTED_WAR_PREMIUM,
                 "cif war_premium_amount")
    assert_money(cif["strikes_premium_amount"], EXPECTED_STRIKES_PREMIUM,
                 "cif strikes_premium_amount")
    assert_money(cif["total_premium_amount"], EXPECTED_TOTAL_PREMIUM,
                 "cif total_premium_amount")

    assert_money(declared["base_premium_amount"], EXPECTED_BASE_PREMIUM_DECLARED,
                 "declared base_premium_amount")
    assert_money(declared["war_premium_amount"], EXPECTED_WAR_PREMIUM_DECLARED,
                 "declared war_premium_amount")
    assert_money(declared["strikes_premium_amount"],
                 EXPECTED_STRIKES_PREMIUM_DECLARED,
                 "declared strikes_premium_amount")
    assert_money(declared["total_premium_amount"], EXPECTED_TOTAL_PREMIUM_DECLARED,
                 "declared total_premium_amount")


def test_both_valuation_variants_book_onto_the_open_cover_ledgers(
        api: ApiClient) -> None:
    """
    Each issue adds its own insured value and its own total premium to the open
    cover's ledgers, whichever valuation basis produced them.

    On the policy, `aggregate_insured_value_booked` rises by the insured value, `aggregate_premium_booked` rises by the total premium, and `certificates_issued_count` increments by one — that counter records every certificate that has ever left `DRAFT`, so it never falls back when one is later cancelled.

    Design: Difficulty/dual_variant_calc/certificate_insured_value_cif_markup_vs_declared_value
    """
    env = _build_two_valuation_variants(api)

    policy = read_policy(api, env["policy_id"])
    assert_money(
        policy["aggregate_insured_value_booked"],
        EXPECTED_INSURED_VALUE_CIF + EXPECTED_INSURED_VALUE_DECLARED,
        "aggregate_insured_value_booked")
    assert_money(
        policy["aggregate_premium_booked"],
        EXPECTED_TOTAL_PREMIUM + EXPECTED_TOTAL_PREMIUM_DECLARED,
        "aggregate_premium_booked")
    assert policy["certificates_issued_count"] == 2


def test_overage_hull_screens_to_a_twenty_five_percent_surcharge(
        api: ApiClient) -> None:
    """
    A 1996-built classed hull is exactly 30 years old against the default clock,
    so it screens to the surcharged branch rather than the blocked one.

    Otherwise, if the age is greater than 25 years the vessel goes to `OVERAGE_SURCHARGED` and `overage_surcharge_pct` is set to 0.25, so every certificate subsequently issued on that hull carries a twenty-five percent loading on its effective marine rate.

    Design: Difficulty/combinatorial_formula/premium_component_rounding_order_and_rate_prerounding
    """
    env = _build_two_hull_variants(api)

    overage = validate_success(
        api.get_vessel(env["overage_vessel"]["id"], UNDERWRITER))
    assert overage["status"] == "OVERAGE_SURCHARGED"
    assert_rate(overage["overage_surcharge_pct"], OVERAGE_SURCHARGE_PCT,
                places=2, label="overage_surcharge_pct")

    approved = read_vessel(api, env["vessel_id"])
    assert approved["status"] == "APPROVED"
    assert_rate(approved["overage_surcharge_pct"], 0.00, places=2,
                label="approved overage_surcharge_pct")


def test_effective_marine_rate_is_rounded_before_it_touches_money(
        api: ApiClient) -> None:
    """
    The composed marine rate 3.500 x 1.35 x 1.25 = 5.90625 is stored as 5.9063
    and only then multiplies the insured value, giving 6821.78 rather than
    6821.72.

    That rounding happens *before* the rate touches any money and it is load-bearing: with a base rate of 3.500, a loading of 0.35 and a surcharge of 0.25 the unrounded product is 5.90625, the stored rate is 5.9063, and on an insured value of 1155000.00 the marine premium is 6821.78 — where multiplying by the unrounded 5.90625 would have produced 6821.72.

    Design: Difficulty/combinatorial_formula/premium_component_rounding_order_and_rate_prerounding
    """
    env = _build_two_hull_variants(api)

    overage_certificate = read_certificate(api, env["overage_certificate"]["id"])
    assert_money(overage_certificate["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "overage certificate insured_value")
    assert_rate(overage_certificate["effective_rate_per_mille"],
                EXPECTED_EFFECTIVE_RATE_OVERAGE,
                label="overage effective_rate_per_mille")
    assert_money(overage_certificate["base_premium_amount"],
                 EXPECTED_BASE_PREMIUM_OVERAGE,
                 "overage base_premium_amount")


def test_total_premium_sums_the_already_rounded_components(
        api: ApiClient) -> None:
    """
    On the approved hull the three components round to 5457.38, 693.00 and
    294.53 first, so the total is 6444.91 and not the 6444.90 a single final
    rounding would give.

    `total_premium_amount` is then the sum of those three already-rounded components — never a re-derivation from the unrounded figures, and never recomputed after issue.

    Design: Difficulty/combinatorial_formula/premium_component_rounding_order_and_rate_prerounding
    """
    env = _build_two_hull_variants(api)

    certificate = get_success_data(
        api.get_certificate(env["approved_certificate"]["id"], UNDERWRITER))

    assert_rate(certificate["effective_rate_per_mille"], EXPECTED_EFFECTIVE_RATE,
                label="approved effective_rate_per_mille")
    assert_money(certificate["base_premium_amount"], EXPECTED_BASE_PREMIUM,
                 "base_premium_amount")
    assert_money(certificate["war_premium_amount"], EXPECTED_WAR_PREMIUM,
                 "war_premium_amount")
    assert_money(certificate["strikes_premium_amount"], EXPECTED_STRIKES_PREMIUM,
                 "strikes_premium_amount")
    assert_money(certificate["total_premium_amount"], EXPECTED_TOTAL_PREMIUM,
                 "total_premium_amount")
    assert_money(
        float(certificate["base_premium_amount"])
        + float(certificate["war_premium_amount"])
        + float(certificate["strikes_premium_amount"]),
        EXPECTED_TOTAL_PREMIUM,
        "sum of the rounded components")


def test_hull_surcharge_moves_only_the_marine_component_of_the_total(
        api: ApiClient) -> None:
    """
    Two certificates of identical insured value price differently only through
    the marine rate: the war and strikes components are unchanged and the
    surcharged total is 7809.31.

    Step one builds the marine rate: the policy's `premium_rate_per_mille` is multiplied by one plus the commodity class's `rate_loading_pct`, then by one plus the vessel's `overage_surcharge_pct` (which is zero unless the hull came out of its screen as `OVERAGE_SURCHARGED`), and the result is rounded half up to 4 decimals and stored as `effective_rate_per_mille`.

    Design: Difficulty/combinatorial_formula/premium_component_rounding_order_and_rate_prerounding
    """
    env = _build_two_hull_variants(api)

    approved = read_certificate(api, env["approved_certificate"]["id"])
    overage = read_certificate(api, env["overage_certificate"]["id"])

    assert_money(approved["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "approved insured_value")
    assert_money(overage["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "overage insured_value")

    assert_rate(approved["effective_rate_per_mille"], EXPECTED_EFFECTIVE_RATE,
                label="approved effective_rate_per_mille")
    assert_rate(overage["effective_rate_per_mille"],
                EXPECTED_EFFECTIVE_RATE_OVERAGE,
                label="overage effective_rate_per_mille")

    assert_money(overage["war_premium_amount"], EXPECTED_WAR_PREMIUM,
                 "overage war_premium_amount")
    assert_money(overage["strikes_premium_amount"], EXPECTED_STRIKES_PREMIUM,
                 "overage strikes_premium_amount")
    assert_money(overage["total_premium_amount"], EXPECTED_TOTAL_PREMIUM_OVERAGE,
                 "overage total_premium_amount")
    assert_money(approved["total_premium_amount"], EXPECTED_TOTAL_PREMIUM,
                 "approved total_premium_amount")
