"""Hazard rating and catastrophe settlement arithmetic.

The residual earthquake programme prices a dwelling twice over its life — once
when the participating insurer quotes the coverage and again every time the term
rolls over — and the two ratings read the same dwelling through different eyes,
because only an inspection-verified retrofit survives into a renewal. It then
settles a loss twice as well: a provisional adjustment that sees structural
damage only and charges the deductible against Coverage A alone, and a final
adjustment signed by a second adjuster that admits a slice of cosmetic damage and
charges the deductible against the combined dwelling-and-contents basis. This
module exercises those paired computations: the eight factors of the hazard rate
and the single clamp that bounds their product, the divergence between the two
rating variants on a self-declared retrofit, the divergence between the two
settlement passes on identical reported damage, and the pinned order in which the
final pass splits the surviving amount so that no cent is created or lost.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CLAIM_ADJUSTER_ALT_HEADERS,
    CLAIM_ADJUSTER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    assertions,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import (
    CLAIM_ADJUSTER_ALT_USER_ID,
    CLAIM_ADJUSTER_USER_ID,
    make_insurer_headers,
)

# A pre-code cripple-wall house on soft soil in a tier-two county, carrying a
# five-hundred-thousand-dollar Coverage A limit.
SOFT_SOIL_CRIPPLE_WALL_DWELLING = {
    "street_address": "12 Cripple Wall Way",
    "county_hazard_tier": "TIER_2",
    "soil_class": "SOFT",
    "structure_type": "WOOD_FRAME_CRIPPLE_WALL",
    "year_built": 1955,
    "dwelling_limit_cents": 50000000,
}
FIFTEEN_PCT_DEDUCTIBLE_POLICY = {
    "deductible_pct": 15,
    "contents_sublimit_cents": 2500000,
    "loss_of_use_sublimit_cents": 1500000,
}
RENEWAL_WINDOW_INSTANT = "2027-07-01T00:00:00Z"


def test_01_quote_time_rating_credits_a_self_declared_retrofit(api):
    """PRD §3.3: "The result is written to `base_premium_cents`, and `rating_variant` records which of the two variants produced it, taking the value `QUOTE_TIME` or `RENEWAL_TIME`."
    PRD §3.3: "The retrofit factor is where the two variants diverge."
    PRD §3.3: "Both variants begin from the dwelling's stored `retrofit_status`, but the renewal variant first downgrades a `SELF_DECLARED` posture to `NONE`, so that only an inspection-verified retrofit survives into a renewal rating; the quote variant takes `retrofit_status` exactly as stored."
    PRD §3.3: "From that effective posture, the factor is 0.75 when the posture is `VERIFIED` *and* the `structure_type` is `WOOD_FRAME_CRIPPLE_WALL` *and* the `verified_retrofit_scope` is `CRIPPLE_WALL_BRACING` — the deepest discount in the program, reserved for the one retrofit that addresses the one failure mode; 0.90 when the posture is `VERIFIED` for any other combination of structure and scope; 0.95 when the effective posture is `SELF_DECLARED`, which can only ever happen under the quote variant; and 1.00 when the effective posture is `NONE`."
    PRD §3.3: "First, the exposure is expressed in units of one thousand dollars of Coverage A limit: divide `dwelling_limit_cents` by one hundred thousand, which is the number of cents in one thousand dollars."
    PRD §3.3: "Second, take the county's base rate per thousand dollars of limit, which is 180 cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."
    PRD §3.3: "the **soil factor** — 0.85 for `ROCK`, 1.00 for `STIFF`, 1.25 for `SOFT` and 1.55 for `LIQUEFACTION`;"
    PRD §3.3: "the **structure factor** — 1.00 for `WOOD_FRAME_SLAB`, 1.30 for `WOOD_FRAME_CRIPPLE_WALL`, 1.85 for `MASONRY_URM` and 1.45 for `MOBILE_HOME`;"
    PRD §3.3: "the **age factor** — 1.20 when `year_built` is 1979 or earlier, and 1.00 for anything built in 1980 or later;"
    PRD §3.3: "the **deductible factor** — 1.35 at a 5 percent deductible, 1.00 at 10 percent, 0.86 at 15 percent, 0.75 at 20 percent and 0.66 at 25 percent;"
    PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."
    PRD §3.3: "Finally, `annual_premium_cents` — the amount actually billed — is `base_premium_cents` less whatever `mitigation_discount_cents` currently stands at, which at quote time is zero."

    Design: Difficulty/dual_variant_calc/premium_quote_time_vs_renewal_time_on_self_declared_retrofit
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_parties(
        api, dwelling_overrides=SOFT_SOIL_CRIPPLE_WALL_DWELLING
    )
    fixtures.declare_retrofit(api, ctx, "CRIPPLE_WALL_BRACING")
    assert ctx["dwelling"]["retrofit_status"] == "SELF_DECLARED"
    assert ctx["dwelling"]["verified_retrofit_scope"] == "CRIPPLE_WALL_BRACING"
    ctx = fixtures.setup_accepted_offer(api, parties=ctx)

    quote = validate_success(
        api.create_policy(
            factories.create_policy_payload(
                ctx["dwelling"]["id"],
                ctx["insurer"]["id"],
                ctx["offer"]["id"],
                **FIFTEEN_PCT_DEDUCTIBLE_POLICY,
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        ),
        201,
    )

    # 320 per thousand x 500 exposure units x 1.25 soil x 1.30 structure
    # x 1.20 vintage x 0.95 self-declared retrofit x 0.86 deductible x 1.00 load.
    assert quote["base_premium_cents"] == 254904
    assert quote["rating_variant"] == "QUOTE_TIME"
    assert quote["mitigation_discount_cents"] == 0
    assert quote["annual_premium_cents"] == 254904
    assert quote["lifecycle_status"] == "QUOTED"
    assert quote["rated_dwelling_limit_cents"] == 50000000
    assertions.assert_premium_ledger_consistent(quote)


def test_02_renewal_rating_drops_the_self_declared_credit(api):
    """PRD §3.3: "Both variants begin from the dwelling's stored `retrofit_status`, but the renewal variant first downgrades a `SELF_DECLARED` posture to `NONE`, so that only an inspection-verified retrofit survives into a renewal rating; the quote variant takes `retrofit_status` exactly as stored."
    PRD §3.3: "From that effective posture, the factor is 0.75 when the posture is `VERIFIED` *and* the `structure_type` is `WOOD_FRAME_CRIPPLE_WALL` *and* the `verified_retrofit_scope` is `CRIPPLE_WALL_BRACING` — the deepest discount in the program, reserved for the one retrofit that addresses the one failure mode; 0.90 when the posture is `VERIFIED` for any other combination of structure and scope; 0.95 when the effective posture is `SELF_DECLARED`, which can only ever happen under the quote variant; and 1.00 when the effective posture is `NONE`."
    PRD §3.3: "The practical consequence is that an unverified attestation which earned a five percent credit on the first term costs five percent more at renewal on byte-identical dwelling data."
    PRD §3.4: "A renewal does a great deal at once: `term_number` rises by one; the old `expires_at` becomes the new `effective_at` and the new `expires_at` is three hundred and sixty-five days after that, so terms abut without gap or overlap; `rated_dwelling_limit_cents` is re-snapshotted from the dwelling's current limit; `base_premium_cents` is recomputed under the `RENEWAL_TIME` variant and `rating_variant` is set to `RENEWAL_TIME`; both `mitigation_discount_cents` and `prorated_credit_cents` are reset to zero, and `annual_premium_cents` becomes equal to the freshly computed `base_premium_cents`."
    PRD §3.2: "The distinction between the two routes has a price attached, and it is the single most consequential asymmetry in the rating engine: an attestation earns a discount on the term you buy it in and loses that discount the moment the policy rolls over."

    Design: Difficulty/dual_variant_calc/premium_quote_time_vs_renewal_time_on_self_declared_retrofit
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_parties(
        api, dwelling_overrides=SOFT_SOIL_CRIPPLE_WALL_DWELLING
    )
    fixtures.declare_retrofit(api, ctx, "CRIPPLE_WALL_BRACING")
    ctx = fixtures.setup_bound_policy(
        api, parties=ctx, **FIFTEEN_PCT_DEDUCTIBLE_POLICY
    )
    quote_base = ctx["quote"]["base_premium_cents"]
    assert quote_base == 254904
    assert ctx["quote"]["rating_variant"] == "QUOTE_TIME"
    assert ctx["policy"]["lifecycle_status"] == "ACTIVE"
    assert ctx["policy"]["base_premium_cents"] == 254904
    assert ctx["policy"]["rating_variant"] == "QUOTE_TIME"
    bound_expires_at = ctx["policy"]["expires_at"]

    fixtures.set_clock(api, RENEWAL_WINDOW_INSTANT)
    renewed = validate_success(
        api.renew_policy(
            ctx["policy"]["id"], None, make_insurer_headers(ctx["insurer"]["id"])
        )
    )

    # The very same dwelling row, re-rated with the retrofit posture downgraded
    # to NONE: 312000 x 1.00 x 0.86 instead of 312000 x 0.95 x 0.86.
    assert renewed["base_premium_cents"] == 268320
    assert renewed["rating_variant"] == "RENEWAL_TIME"
    assert renewed["base_premium_cents"] - quote_base == 13416
    assert renewed["term_number"] == 2
    assert renewed["lifecycle_status"] == "ACTIVE"
    assert renewed["effective_at"] == bound_expires_at
    assert renewed["mitigation_discount_cents"] == 0
    assert renewed["prorated_credit_cents"] == 0
    assert renewed["annual_premium_cents"] == 268320
    assert renewed["rated_dwelling_limit_cents"] == 50000000
    assertions.assert_premium_ledger_consistent(renewed)

    dwelling = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert dwelling["retrofit_status"] == "SELF_DECLARED"
    assert dwelling["verified_retrofit_scope"] == "CRIPPLE_WALL_BRACING"


def test_03_renewal_rating_matches_the_quote_when_no_retrofit_is_claimed(api):
    """PRD §3.3: "Both variants begin from the dwelling's stored `retrofit_status`, but the renewal variant first downgrades a `SELF_DECLARED` posture to `NONE`, so that only an inspection-verified retrofit survives into a renewal rating; the quote variant takes `retrofit_status` exactly as stored."
    PRD §3.3: "From that effective posture, the factor is 0.75 when the posture is `VERIFIED` *and* the `structure_type` is `WOOD_FRAME_CRIPPLE_WALL` *and* the `verified_retrofit_scope` is `CRIPPLE_WALL_BRACING` — the deepest discount in the program, reserved for the one retrofit that addresses the one failure mode; 0.90 when the posture is `VERIFIED` for any other combination of structure and scope; 0.95 when the effective posture is `SELF_DECLARED`, which can only ever happen under the quote variant; and 1.00 when the effective posture is `NONE`."
    PRD §3.2: "A new dwelling opens with `retrofit_status` at `NONE`, `verified_retrofit_scope` at `NONE` and `grant_lifetime_count` at zero."
    PRD §3.4: "A renewal does a great deal at once: `term_number` rises by one; the old `expires_at` becomes the new `effective_at` and the new `expires_at` is three hundred and sixty-five days after that, so terms abut without gap or overlap; `rated_dwelling_limit_cents` is re-snapshotted from the dwelling's current limit; `base_premium_cents` is recomputed under the `RENEWAL_TIME` variant and `rating_variant` is set to `RENEWAL_TIME`; both `mitigation_discount_cents` and `prorated_credit_cents` are reset to zero, and `annual_premium_cents` becomes equal to the freshly computed `base_premium_cents`."

    Design: Difficulty/dual_variant_calc/premium_quote_time_vs_renewal_time_on_self_declared_retrofit
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(
        api,
        dwelling_overrides=SOFT_SOIL_CRIPPLE_WALL_DWELLING,
        **FIFTEEN_PCT_DEDUCTIBLE_POLICY,
    )
    assert ctx["dwelling"]["retrofit_status"] == "NONE"
    # An unmitigated posture is worth factor 1.00 under both variants.
    assert ctx["quote"]["base_premium_cents"] == 268320
    assert ctx["quote"]["rating_variant"] == "QUOTE_TIME"

    fixtures.set_clock(api, RENEWAL_WINDOW_INSTANT)
    renewed = validate_success(
        api.renew_policy(
            ctx["policy"]["id"], None, make_insurer_headers(ctx["insurer"]["id"])
        )
    )

    assert renewed["base_premium_cents"] == 268320
    assert renewed["rating_variant"] == "RENEWAL_TIME"
    assert renewed["base_premium_cents"] - ctx["quote"]["base_premium_cents"] == 0
    assert renewed["term_number"] == 2
    assert renewed["annual_premium_cents"] == 268320
    assertions.assert_premium_ledger_consistent(renewed)


def test_04_urm_on_liquefaction_soil_clamps_down_to_the_premium_ceiling(api):
    """PRD §3.3: "First, the exposure is expressed in units of one thousand dollars of Coverage A limit: divide `dwelling_limit_cents` by one hundred thousand, which is the number of cents in one thousand dollars."
    PRD §3.3: "Second, take the county's base rate per thousand dollars of limit, which is 180 cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."
    PRD §3.3: "the **soil factor** — 0.85 for `ROCK`, 1.00 for `STIFF`, 1.25 for `SOFT` and 1.55 for `LIQUEFACTION`;"
    PRD §3.3: "the **structure factor** — 1.00 for `WOOD_FRAME_SLAB`, 1.30 for `WOOD_FRAME_CRIPPLE_WALL`, 1.85 for `MASONRY_URM` and 1.45 for `MOBILE_HOME`;"
    PRD §3.3: "the **age factor** — 1.20 when `year_built` is 1979 or earlier, and 1.00 for anything built in 1980 or later;"
    PRD §3.3: "the **deductible factor** — 1.35 at a 5 percent deductible, 1.00 at 10 percent, 0.86 at 15 percent, 0.75 at 20 percent and 0.66 at 25 percent;"
    PRD §3.3: "the **high-limit load** — 1.15 when `dwelling_limit_cents` is at least 75,000,000 cents, which is a Coverage A limit of seven hundred and fifty thousand dollars or more, and 1.00 below that."
    PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."
    PRD §3.3: "Clamp the unrounded product upward to a floor of 18,000 cents and downward to a ceiling of 4,000,000 cents — that is, no annual base premium is ever less than one hundred and eighty dollars or more than forty thousand dollars."
    PRD §3.3: "Only after the clamp is the value rounded, half up, exactly once, to whole cents, and that integer becomes `base_premium_cents`."
    PRD §3.3: "The quote copies the dwelling's owner into the policy's own `policyholder_id` so that ownership checks on the policy need no join, and it pins `rated_dwelling_limit_cents` from the dwelling's live `dwelling_limit_cents`."

    Design: Difficulty/combinatorial_formula/premium_eight_factor_product_clamps_at_both_ends
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_accepted_offer(
        api,
        dwelling_overrides={
            "street_address": "1 Liquefaction Row",
            "county_hazard_tier": "TIER_3",
            "soil_class": "LIQUEFACTION",
            "structure_type": "MASONRY_URM",
            "year_built": 1930,
            "dwelling_limit_cents": 300000000,
        },
    )
    assert ctx["dwelling"]["retrofit_status"] == "NONE"

    quote = validate_success(
        api.create_policy(
            factories.create_policy_payload(
                ctx["dwelling"]["id"],
                ctx["insurer"]["id"],
                ctx["offer"]["id"],
                deductible_pct=5,
                contents_sublimit_cents=5000000,
                loss_of_use_sublimit_cents=2000000,
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        ),
        201,
    )

    # 520 x 3000 units x 1.55 x 1.85 x 1.20 x 1.00 x 1.35 x 1.15 = 8333757.9,
    # which the ceiling cuts back to the programme maximum.
    assert quote["base_premium_cents"] == 4000000
    assert quote["base_premium_cents"] == constants.MAX_PREMIUM_CENTS
    assert quote["rating_variant"] == "QUOTE_TIME"
    assert quote["annual_premium_cents"] == 4000000
    assert quote["mitigation_discount_cents"] == 0
    assert quote["rated_dwelling_limit_cents"] == 300000000
    assert quote["policyholder_id"] == ctx["policyholder"]["id"]
    assertions.assert_premium_ledger_consistent(quote)


def test_05_post_code_slab_on_rock_clamps_up_to_the_premium_floor(api):
    """PRD §3.3: "First, the exposure is expressed in units of one thousand dollars of Coverage A limit: divide `dwelling_limit_cents` by one hundred thousand, which is the number of cents in one thousand dollars."
    PRD §3.3: "Second, take the county's base rate per thousand dollars of limit, which is 180 cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."
    PRD §3.3: "the **soil factor** — 0.85 for `ROCK`, 1.00 for `STIFF`, 1.25 for `SOFT` and 1.55 for `LIQUEFACTION`;"
    PRD §3.3: "the **structure factor** — 1.00 for `WOOD_FRAME_SLAB`, 1.30 for `WOOD_FRAME_CRIPPLE_WALL`, 1.85 for `MASONRY_URM` and 1.45 for `MOBILE_HOME`;"
    PRD §3.3: "the **age factor** — 1.20 when `year_built` is 1979 or earlier, and 1.00 for anything built in 1980 or later;"
    PRD §3.3: "the **deductible factor** — 1.35 at a 5 percent deductible, 1.00 at 10 percent, 0.86 at 15 percent, 0.75 at 20 percent and 0.66 at 25 percent;"
    PRD §3.3: "the **high-limit load** — 1.15 when `dwelling_limit_cents` is at least 75,000,000 cents, which is a Coverage A limit of seven hundred and fifty thousand dollars or more, and 1.00 below that."
    PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."
    PRD §3.3: "Clamp the unrounded product upward to a floor of 18,000 cents and downward to a ceiling of 4,000,000 cents — that is, no annual base premium is ever less than one hundred and eighty dollars or more than forty thousand dollars."
    PRD §3.3: "Only after the clamp is the value rounded, half up, exactly once, to whole cents, and that integer becomes `base_premium_cents`."

    Design: Difficulty/combinatorial_formula/premium_eight_factor_product_clamps_at_both_ends
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_accepted_offer(
        api,
        dwelling_overrides={
            "street_address": "2 Bedrock Court",
            "county_hazard_tier": "TIER_1",
            "soil_class": "ROCK",
            "structure_type": "WOOD_FRAME_SLAB",
            "year_built": 2005,
            "dwelling_limit_cents": 5000000,
        },
    )

    quote = validate_success(
        api.create_policy(
            factories.create_policy_payload(
                ctx["dwelling"]["id"],
                ctx["insurer"]["id"],
                ctx["offer"]["id"],
                deductible_pct=25,
                contents_sublimit_cents=500000,
                loss_of_use_sublimit_cents=250000,
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        ),
        201,
    )

    # 180 x 50 units x 0.85 x 1.00 x 1.00 x 1.00 x 0.66 x 1.00 = 5049, which the
    # floor lifts to the programme minimum.
    assert quote["base_premium_cents"] == 18000
    assert quote["base_premium_cents"] == constants.MIN_PREMIUM_CENTS
    assert quote["rating_variant"] == "QUOTE_TIME"
    assert quote["annual_premium_cents"] == 18000
    assert quote["mitigation_discount_cents"] == 0
    assert quote["rated_dwelling_limit_cents"] == 5000000
    assertions.assert_premium_ledger_consistent(quote)


def test_06_mid_range_eight_factor_product_survives_both_clamps_untouched(api):
    """PRD §3.3: "Second, take the county's base rate per thousand dollars of limit, which is 180 cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."
    PRD §3.3: "the **soil factor** — 0.85 for `ROCK`, 1.00 for `STIFF`, 1.25 for `SOFT` and 1.55 for `LIQUEFACTION`;"
    PRD §3.3: "the **structure factor** — 1.00 for `WOOD_FRAME_SLAB`, 1.30 for `WOOD_FRAME_CRIPPLE_WALL`, 1.85 for `MASONRY_URM` and 1.45 for `MOBILE_HOME`;"
    PRD §3.3: "the **age factor** — 1.20 when `year_built` is 1979 or earlier, and 1.00 for anything built in 1980 or later;"
    PRD §3.3: "the **deductible factor** — 1.35 at a 5 percent deductible, 1.00 at 10 percent, 0.86 at 15 percent, 0.75 at 20 percent and 0.66 at 25 percent;"
    PRD §3.3: "the **high-limit load** — 1.15 when `dwelling_limit_cents` is at least 75,000,000 cents, which is a Coverage A limit of seven hundred and fifty thousand dollars or more, and 1.00 below that."
    PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."
    PRD §3.3: "Clamp the unrounded product upward to a floor of 18,000 cents and downward to a ceiling of 4,000,000 cents — that is, no annual base premium is ever less than one hundred and eighty dollars or more than forty thousand dollars."

    Design: Difficulty/combinatorial_formula/premium_eight_factor_product_clamps_at_both_ends
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_accepted_offer(
        api,
        dwelling_overrides={
            "street_address": "44 Coach Road",
            "county_hazard_tier": "TIER_2",
            "soil_class": "SOFT",
            "structure_type": "MOBILE_HOME",
            "year_built": 1970,
            "dwelling_limit_cents": 80000000,
        },
    )

    quote = validate_success(
        api.create_policy(
            factories.create_policy_payload(
                ctx["dwelling"]["id"],
                ctx["insurer"]["id"],
                ctx["offer"]["id"],
                deductible_pct=20,
                contents_sublimit_cents=3000000,
                loss_of_use_sublimit_cents=1500000,
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        ),
        201,
    )

    # 320 x 800 units x 1.25 x 1.45 x 1.20 x 1.00 x 0.75 x 1.15 = 480240, which
    # sits between the floor and the ceiling and is therefore carried through.
    assert quote["base_premium_cents"] == 480240
    assert constants.MIN_PREMIUM_CENTS < quote["base_premium_cents"]
    assert quote["base_premium_cents"] < constants.MAX_PREMIUM_CENTS
    assert quote["rating_variant"] == "QUOTE_TIME"
    assert quote["annual_premium_cents"] == 480240
    assert quote["rated_dwelling_limit_cents"] == 80000000
    assertions.assert_premium_ledger_consistent(quote)


def test_07_high_limit_load_attaches_at_the_threshold_and_rounds_half_up(api):
    """PRD §3.3: "the **high-limit load** — 1.15 when `dwelling_limit_cents` is at least 75,000,000 cents, which is a Coverage A limit of seven hundred and fifty thousand dollars or more, and 1.00 below that."
    PRD §3.3: "First, the exposure is expressed in units of one thousand dollars of Coverage A limit: divide `dwelling_limit_cents` by one hundred thousand, which is the number of cents in one thousand dollars."
    PRD §3.3: "Second, take the county's base rate per thousand dollars of limit, which is 180 cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."
    PRD §3.3: "the **soil factor** — 0.85 for `ROCK`, 1.00 for `STIFF`, 1.25 for `SOFT` and 1.55 for `LIQUEFACTION`;"
    PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."
    PRD §3.3: "Only after the clamp is the value rounded, half up, exactly once, to whole cents, and that integer becomes `base_premium_cents`."
    PRD §2.6: "Rounding half up means that a fractional remainder of exactly one half rounds away from zero, to the next whole cent."

    Design: Difficulty/combinatorial_formula/premium_eight_factor_product_clamps_at_both_ends
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    loaded_ctx = fixtures.setup_accepted_offer(
        api,
        dwelling_overrides={
            "street_address": "750 Ridge Crest",
            "county_hazard_tier": "TIER_1",
            "soil_class": "ROCK",
            "structure_type": "WOOD_FRAME_SLAB",
            "year_built": 2005,
            "dwelling_limit_cents": 75000000,
        },
    )
    unloaded_dwelling = fixtures.create_dwelling(
        api,
        loaded_ctx["policyholder"]["id"],
        street_address="749 Ridge Crest",
        county_hazard_tier="TIER_1",
        soil_class="ROCK",
        structure_type="WOOD_FRAME_SLAB",
        year_built=2005,
        dwelling_limit_cents=74900000,
    )
    unloaded_ctx = fixtures.setup_accepted_offer(
        api,
        parties={
            "insurer": loaded_ctx["insurer"],
            "policyholder": loaded_ctx["policyholder"],
            "dwelling": unloaded_dwelling,
        },
    )

    loaded_quote = validate_success(
        api.create_policy(
            factories.create_policy_payload(
                loaded_ctx["dwelling"]["id"],
                loaded_ctx["insurer"]["id"],
                loaded_ctx["offer"]["id"],
                deductible_pct=10,
                contents_sublimit_cents=3000000,
                loss_of_use_sublimit_cents=1500000,
            ),
            make_insurer_headers(loaded_ctx["insurer"]["id"]),
        ),
        201,
    )
    unloaded_quote = validate_success(
        api.create_policy(
            factories.create_policy_payload(
                unloaded_dwelling["id"],
                unloaded_ctx["insurer"]["id"],
                unloaded_ctx["offer"]["id"],
                deductible_pct=10,
                contents_sublimit_cents=3000000,
                loss_of_use_sublimit_cents=1500000,
            ),
            make_insurer_headers(unloaded_ctx["insurer"]["id"]),
        ),
        201,
    )

    # 180 x 750 units x 0.85 x 1.15 = 131962.5, whose one-half remainder rounds
    # away from zero; one hundred dollars of limit less and the load falls away.
    assert loaded_quote["base_premium_cents"] == 131963
    assert unloaded_quote["base_premium_cents"] == 114597
    assert loaded_quote["rated_dwelling_limit_cents"] == constants.HIGH_LIMIT_THRESHOLD_CENTS
    assert unloaded_quote["rated_dwelling_limit_cents"] == 74900000
    assert loaded_quote["annual_premium_cents"] == 131963
    assert unloaded_quote["annual_premium_cents"] == 114597
    assertions.assert_premium_ledger_consistent(loaded_quote)
    assertions.assert_premium_ledger_consistent(unloaded_quote)


# The four damage figures reported at first notice on the cripple-wall house:
# cosmetic damage runs well past the tenth of structural the final pass admits.
HAYWARD_DAMAGE_REPORT = {
    "structural_damage_cents": 20000000,
    "cosmetic_damage_cents": 3000000,
    "contents_damage_cents": 4000000,
    "loss_of_use_cents": 1200000,
}


def _cripple_wall_policy_under_a_declared_event(api):
    """An in-force fifteen-percent-deductible policy and a declared earthquake."""
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    return fixtures.setup_event_with_policy(
        api,
        dwelling_overrides=SOFT_SOIL_CRIPPLE_WALL_DWELLING,
        policy_overrides=FIFTEEN_PCT_DEDUCTIBLE_POLICY,
    )


def test_08_provisional_pass_pays_structural_only_with_the_deductible_on_coverage_a(api):
    """PRD §3.8: "Both adjustment passes begin from the same deductible, and it is computed from the term snapshot rather than the live dwelling: `deductible_applied_cents` is the policy's `rated_dwelling_limit_cents` multiplied by its `deductible_pct` and divided by one hundred, rounded half up to whole cents."
    PRD §3.8: "Cosmetic damage is excluded from the basis entirely at this stage."
    PRD §3.8: "The Coverage A basis is the smaller of `structural_damage_cents` and the snapshot limit; `dwelling_part_cents` is that basis less the deductible, floored at zero, because the deductible is charged against Coverage A alone in this pass."
    PRD §3.8: "`contents_part_cents` is the smaller of `contents_damage_cents` and `contents_sublimit_cents`, and `loss_of_use_part_cents` is the smaller of `loss_of_use_cents` and `loss_of_use_sublimit_cents` — both pay in full up to their sublimits, undiminished."
    PRD §3.8: "`provisional_payable_cents` is the sum of the three parts, and `payable_cents` — the figure payments are measured against — is set equal to it."
    PRD §3.8: "The acting `X-User-ID` is recorded as `provisional_adjuster_user_id`, and `payment_status` is not touched, remaining `UNPAID`."
    PRD §3.8: "First notice of loss names the coverage through `policy_id` and the earthquake through `event_id`, and reports four damage figures in cents that are fixed at notice and never rewritten by either adjustment: `structural_damage_cents`, the adjuster-verified structural damage to the dwelling; `cosmetic_damage_cents`, damage that is cosmetic only; `contents_damage_cents`, the Coverage C loss before its sublimit; and `loss_of_use_cents`, the Coverage D expense before its sublimit."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_settlement_divergence
    """
    ctx = _cripple_wall_policy_under_a_declared_event(api)
    ctx = fixtures.setup_filed_claim(api, ctx=ctx, **HAYWARD_DAMAGE_REPORT)
    assert ctx["claim"]["adjustment_status"] == "FNOL_RECEIVED"

    claim = validate_success(
        api.adjust_claim_provisional(ctx["claim"]["id"], None, CLAIM_ADJUSTER_HEADERS)
    )

    # 50,000,000 snapshot limit at 15 per cent is a 7,500,000 deductible; the
    # 20,000,000 structural basis survives it by 12,500,000, contents is cut to
    # its 2,500,000 sublimit and loss of use pays its reported 1,200,000.
    assert claim["deductible_applied_cents"] == 7500000
    assert claim["dwelling_part_cents"] == 12500000
    assert claim["contents_part_cents"] == 2500000
    assert claim["loss_of_use_part_cents"] == 1200000
    assert claim["provisional_payable_cents"] == 16200000
    assert claim["payable_cents"] == 16200000
    assert claim["final_payable_cents"] == 0
    assert claim["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert claim["payment_status"] == "UNPAID"
    assert claim["paid_cents"] == 0
    assert claim["provisional_adjuster_user_id"] == CLAIM_ADJUSTER_USER_ID
    assert claim["structural_damage_cents"] == 20000000
    assert claim["cosmetic_damage_cents"] == 3000000
    assert claim["contents_damage_cents"] == 4000000
    assert claim["loss_of_use_cents"] == 1200000
    assertions.assert_settlement_parts_sum(claim, 16200000)


def test_09_final_pass_admits_capped_cosmetic_damage_and_charges_the_combined_basis(api):
    """PRD §3.8: "Cosmetic damage is now admitted, but only up to a tenth of the structural figure: the allowed cosmetic amount is the smaller of `cosmetic_damage_cents` and ten percent of `structural_damage_cents` rounded half up to whole cents."
    PRD §3.8: "The Coverage A basis becomes the smaller of the snapshot limit and the sum of `structural_damage_cents` and that allowed cosmetic amount."
    PRD §3.8: "And the deductible is now charged against the **combined** Coverage A and Coverage C basis rather than against Coverage A alone: take the Coverage C basis as the smaller of `contents_damage_cents` and `contents_sublimit_cents`, add it to the Coverage A basis to form the combined basis, and subtract the deductible from that combined figure, flooring at zero."
    PRD §3.8: "`final_payable_cents` is the sum of the three parts, `payable_cents` is set equal to it — the final figure supersedes the provisional one — and the acting `X-User-ID` is recorded as `final_adjuster_user_id`."
    PRD §3.8: "On the same reported figures the final number can land above the provisional one, when the cosmetic allowance dominates, or below it, when the deductible now also eats into Coverage C; both outcomes are correct."
    PRD §3.8: "`payment_status` is not changed by finalization."
    PRD §3.8: "First notice of loss names the coverage through `policy_id` and the earthquake through `event_id`, and reports four damage figures in cents that are fixed at notice and never rewritten by either adjustment: `structural_damage_cents`, the adjuster-verified structural damage to the dwelling; `cosmetic_damage_cents`, damage that is cosmetic only; `contents_damage_cents`, the Coverage C loss before its sublimit; and `loss_of_use_cents`, the Coverage D expense before its sublimit."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_settlement_divergence
    """
    ctx = _cripple_wall_policy_under_a_declared_event(api)
    ctx = fixtures.setup_provisionally_adjusted_claim(
        api, ctx=ctx, **HAYWARD_DAMAGE_REPORT
    )
    assert ctx["claim"]["provisional_payable_cents"] == 16200000

    claim = validate_success(
        api.finalize_claim_adjustment(
            ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS
        )
    )

    # Cosmetic is admitted at 2,000,000 — a tenth of structural, not the reported
    # 3,000,000 — lifting Coverage A to 22,000,000; with the 2,500,000 Coverage C
    # basis the combined figure is 24,500,000 and 17,000,000 survives the
    # deductible, of which Coverage C takes 1,734,694.
    assert claim["deductible_applied_cents"] == 7500000
    assert claim["dwelling_part_cents"] == 15265306
    assert claim["contents_part_cents"] == 1734694
    assert claim["loss_of_use_part_cents"] == 1200000
    assert claim["final_payable_cents"] == 18200000
    assert claim["payable_cents"] == 18200000
    assert claim["provisional_payable_cents"] == 16200000
    assert claim["final_payable_cents"] - claim["provisional_payable_cents"] == 2000000
    assert claim["adjustment_status"] == "FINAL_ADJUSTED"
    assert claim["payment_status"] == "UNPAID"
    assert claim["provisional_adjuster_user_id"] == CLAIM_ADJUSTER_USER_ID
    assert claim["final_adjuster_user_id"] == CLAIM_ADJUSTER_ALT_USER_ID
    assert claim["structural_damage_cents"] == 20000000
    assert claim["cosmetic_damage_cents"] == 3000000
    assert claim["contents_damage_cents"] == 4000000
    assert claim["loss_of_use_cents"] == 1200000
    assertions.assert_settlement_parts_sum(claim, 18200000)


def test_10_final_pass_admits_cosmetic_damage_below_the_tenth_of_structural_in_full(api):
    """PRD §3.8: "Cosmetic damage is now admitted, but only up to a tenth of the structural figure: the allowed cosmetic amount is the smaller of `cosmetic_damage_cents` and ten percent of `structural_damage_cents` rounded half up to whole cents."
    PRD §3.8: "The Coverage A basis becomes the smaller of the snapshot limit and the sum of `structural_damage_cents` and that allowed cosmetic amount."
    PRD §3.8: "And the deductible is now charged against the **combined** Coverage A and Coverage C basis rather than against Coverage A alone: take the Coverage C basis as the smaller of `contents_damage_cents` and `contents_sublimit_cents`, add it to the Coverage A basis to form the combined basis, and subtract the deductible from that combined figure, flooring at zero."
    PRD §3.8: "Cosmetic damage is excluded from the basis entirely at this stage."
    PRD §3.8: "`final_payable_cents` is the sum of the three parts, `payable_cents` is set equal to it — the final figure supersedes the provisional one — and the acting `X-User-ID` is recorded as `final_adjuster_user_id`."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_settlement_divergence
    """
    ctx = _cripple_wall_policy_under_a_declared_event(api)
    damages = dict(HAYWARD_DAMAGE_REPORT)
    damages["cosmetic_damage_cents"] = 1000000
    ctx = fixtures.setup_provisionally_adjusted_claim(api, ctx=ctx, **damages)
    # The provisional pass ignores cosmetic damage altogether, so it lands on the
    # same 16,200,000 as it does on a far more cosmetically damaged house.
    assert ctx["claim"]["provisional_payable_cents"] == 16200000

    claim = validate_success(
        api.finalize_claim_adjustment(
            ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS
        )
    )

    # The reported 1,000,000 is below the 2,000,000 tenth of structural, so all of
    # it is admitted: Coverage A basis 21,000,000, combined basis 23,500,000, and
    # 16,000,000 survives the 7,500,000 deductible.
    assert claim["contents_part_cents"] == 1702128
    assert claim["dwelling_part_cents"] == 14297872
    assert claim["loss_of_use_part_cents"] == 1200000
    assert claim["final_payable_cents"] == 17200000
    assert claim["payable_cents"] == 17200000
    assert claim["final_payable_cents"] - claim["provisional_payable_cents"] == 1000000
    assert claim["adjustment_status"] == "FINAL_ADJUSTED"
    assertions.assert_settlement_parts_sum(claim, 17200000)


# A Coverage A limit whose quarter is an odd number of cents, so the deductible
# lands on 5,000,001 and the final split has a genuine half-cent to place.
SPLIT_CENT_DWELLING = {
    "street_address": "3 Split Cent Lane",
    "county_hazard_tier": "TIER_1",
    "soil_class": "ROCK",
    "structure_type": "WOOD_FRAME_SLAB",
    "year_built": 2005,
    "dwelling_limit_cents": 20000004,
}
SPLIT_CENT_POLICY = {
    "deductible_pct": 25,
    "contents_sublimit_cents": 3000001,
    "loss_of_use_sublimit_cents": 100000,
}
SPLIT_CENT_DAMAGE_REPORT = {
    "structural_damage_cents": 2727274,
    "cosmetic_damage_cents": 500000,
    "contents_damage_cents": 4000000,
    "loss_of_use_cents": 0,
}


def _split_cent_policy_under_a_declared_event(api):
    """An in-force twenty-five-percent-deductible policy and a declared earthquake."""
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    return fixtures.setup_event_with_policy(
        api,
        dwelling_overrides=SPLIT_CENT_DWELLING,
        policy_overrides=SPLIT_CENT_POLICY,
    )


def test_11_provisional_deductible_wipes_coverage_a_and_contents_pays_its_sublimit(api):
    """PRD §3.8: "Both adjustment passes begin from the same deductible, and it is computed from the term snapshot rather than the live dwelling: `deductible_applied_cents` is the policy's `rated_dwelling_limit_cents` multiplied by its `deductible_pct` and divided by one hundred, rounded half up to whole cents."
    PRD §3.8: "The Coverage A basis is the smaller of `structural_damage_cents` and the snapshot limit; `dwelling_part_cents` is that basis less the deductible, floored at zero, because the deductible is charged against Coverage A alone in this pass."
    PRD §3.8: "`contents_part_cents` is the smaller of `contents_damage_cents` and `contents_sublimit_cents`, and `loss_of_use_part_cents` is the smaller of `loss_of_use_cents` and `loss_of_use_sublimit_cents` — both pay in full up to their sublimits, undiminished."
    PRD §3.8: "`provisional_payable_cents` is the sum of the three parts, and `payable_cents` — the figure payments are measured against — is set equal to it."

    Design: Difficulty/combinatorial_formula/claim_final_contents_share_rounded_first_dwelling_absorbs_residual
    """
    ctx = _split_cent_policy_under_a_declared_event(api)
    ctx = fixtures.setup_filed_claim(api, ctx=ctx, **SPLIT_CENT_DAMAGE_REPORT)

    claim = validate_success(
        api.adjust_claim_provisional(ctx["claim"]["id"], None, CLAIM_ADJUSTER_HEADERS)
    )

    # A quarter of the 20,000,004 snapshot limit is an odd 5,000,001 cents, which
    # is more than the whole 2,727,274 structural basis, so Coverage A pays
    # nothing and only the Coverage C sublimit answers.
    assert claim["deductible_applied_cents"] == 5000001
    assert claim["dwelling_part_cents"] == 0
    assert claim["contents_part_cents"] == 3000001
    assert claim["loss_of_use_part_cents"] == 0
    assert claim["provisional_payable_cents"] == 3000001
    assert claim["payable_cents"] == 3000001
    assert claim["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assertions.assert_settlement_parts_sum(claim, 3000001)


def test_12_final_split_rounds_the_contents_share_first_and_dwelling_takes_the_residual(api):
    """PRD §3.8: "Splitting the surviving amount between the two coverages has a **pinned order** that must be followed exactly."
    PRD §3.8: "Compute `contents_part_cents` first, as the after-deductible amount multiplied by the Coverage C basis and divided by the combined basis, rounded half up to whole cents — and as zero when the combined basis is zero."
    PRD §3.8: "Then take `dwelling_part_cents` as the residual: the after-deductible amount less the already-rounded `contents_part_cents`."
    PRD §3.8: "Rounding both shares independently and adding them is wrong and can drift by a cent; Coverage A absorbs the residual by construction."
    PRD §3.8: "`loss_of_use_part_cents` is again the smaller of `loss_of_use_cents` and `loss_of_use_sublimit_cents`, and is never reduced by the deductible."
    PRD §3.8: "`final_payable_cents` is the sum of the three parts, `payable_cents` is set equal to it — the final figure supersedes the provisional one — and the acting `X-User-ID` is recorded as `final_adjuster_user_id`."
    PRD §3.8: "On the same reported figures the final number can land above the provisional one, when the cosmetic allowance dominates, or below it, when the deductible now also eats into Coverage C; both outcomes are correct."
    PRD §2.6: "Where a total must be split across several rows, one designated row absorbs the residual so that the parts sum exactly to the whole rather than each part being rounded independently."

    Design: Difficulty/combinatorial_formula/claim_final_contents_share_rounded_first_dwelling_absorbs_residual
    """
    ctx = _split_cent_policy_under_a_declared_event(api)
    ctx = fixtures.setup_provisionally_adjusted_claim(
        api, ctx=ctx, **SPLIT_CENT_DAMAGE_REPORT
    )
    assert ctx["claim"]["provisional_payable_cents"] == 3000001

    claim = validate_success(
        api.finalize_claim_adjustment(
            ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS
        )
    )

    # The 272,727 cosmetic allowance lifts Coverage A to exactly 3,000,001, the
    # same as the Coverage C basis, so the 1,000,001 surviving the deductible
    # splits at exactly one half: Coverage C rounds up to 500,001 first and
    # Coverage A keeps whatever is left rather than rounding up as well.
    assert claim["deductible_applied_cents"] == 5000001
    assert claim["contents_part_cents"] == 500001
    assert claim["dwelling_part_cents"] == 500000
    assert claim["dwelling_part_cents"] + claim["contents_part_cents"] == 1000001
    assert claim["loss_of_use_part_cents"] == 0
    assert claim["final_payable_cents"] == 1000001
    assert claim["payable_cents"] == 1000001
    assert claim["final_payable_cents"] < claim["provisional_payable_cents"]
    assert claim["provisional_payable_cents"] == 3000001
    assert claim["adjustment_status"] == "FINAL_ADJUSTED"
    assert claim["final_adjuster_user_id"] == CLAIM_ADJUSTER_ALT_USER_ID
    assertions.assert_settlement_parts_sum(claim, 1000001)


def test_13_final_split_pays_nothing_on_either_coverage_when_the_combined_basis_is_zero(api):
    """PRD §3.8: "Compute `contents_part_cents` first, as the after-deductible amount multiplied by the Coverage C basis and divided by the combined basis, rounded half up to whole cents — and as zero when the combined basis is zero."
    PRD §3.8: "Then take `dwelling_part_cents` as the residual: the after-deductible amount less the already-rounded `contents_part_cents`."
    PRD §3.8: "`loss_of_use_part_cents` is again the smaller of `loss_of_use_cents` and `loss_of_use_sublimit_cents`, and is never reduced by the deductible."
    PRD §3.8: "And the deductible is now charged against the **combined** Coverage A and Coverage C basis rather than against Coverage A alone: take the Coverage C basis as the smaller of `contents_damage_cents` and `contents_sublimit_cents`, add it to the Coverage A basis to form the combined basis, and subtract the deductible from that combined figure, flooring at zero."
    PRD §3.8: "`final_payable_cents` is the sum of the three parts, `payable_cents` is set equal to it — the final figure supersedes the provisional one — and the acting `X-User-ID` is recorded as `final_adjuster_user_id`."

    Design: Difficulty/combinatorial_formula/claim_final_contents_share_rounded_first_dwelling_absorbs_residual
    """
    ctx = _split_cent_policy_under_a_declared_event(api)
    ctx = fixtures.setup_provisionally_adjusted_claim(
        api,
        ctx=ctx,
        structural_damage_cents=0,
        cosmetic_damage_cents=0,
        contents_damage_cents=0,
        loss_of_use_cents=250000,
    )

    claim = validate_success(
        api.finalize_claim_adjustment(
            ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS
        )
    )

    # No structural and no contents damage leaves a combined basis of zero, so
    # neither share exists and only the loss-of-use sublimit is paid.
    assert claim["contents_part_cents"] == 0
    assert claim["dwelling_part_cents"] == 0
    assert claim["loss_of_use_part_cents"] == 100000
    assert claim["final_payable_cents"] == 100000
    assert claim["payable_cents"] == 100000
    assert claim["deductible_applied_cents"] == 5000001
    assert claim["adjustment_status"] == "FINAL_ADJUSTED"
    assertions.assert_settlement_parts_sum(claim, 100000)
