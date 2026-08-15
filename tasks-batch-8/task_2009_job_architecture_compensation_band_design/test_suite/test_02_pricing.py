"""Market pricing: dual variants, rounding discipline, aging, posture and OCC
gates (PRD §2.4, §2.7, §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    api_client,
    create_accepted_survey_with_cut,
    create_child_zone,
    create_market_cut_payload,
    create_market_survey_payload,
    create_pay_band_payload,
    create_program,
    get_success_data,
    setup_framework,
    setup_pricing_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]


def _dual_variant_setup():
    """ENG/P2 band with three cuts: S1+S2 ACCEPTED, S3 left SUBMITTED."""
    ctx = setup_pricing_program(approve_profiles=(1,))
    fam, lvls, zone, prog = ctx["family"], ctx["levels"], ctx["zone"], ctx["program"]
    prof2 = ctx["profiles"][2]
    s1 = get_success_data(api_client.create_market_survey(
        create_market_survey_payload(name="S1", survey_year=2026,
                                     effective_date="2026-01-01"), ANALYST))
    s2 = get_success_data(api_client.create_market_survey(
        create_market_survey_payload(name="S2", survey_year=2025,
                                     effective_date="2025-07-01"), ANALYST))
    s3 = get_success_data(api_client.create_market_survey(
        create_market_survey_payload(name="S3", survey_year=2026,
                                     effective_date="2026-06-01"), ANALYST))
    api_client.create_market_cut(
        create_market_cut_payload(s1["id"], prof2["id"], zone["id"],
                                  p50_cents=12_000_000, sample_size=40,
                                  effective_date="2026-01-01"), ANALYST)
    api_client.create_market_cut(
        create_market_cut_payload(s2["id"], prof2["id"], zone["id"],
                                  p50_cents=11_500_000, sample_size=10,
                                  effective_date="2025-07-01"), ANALYST)
    api_client.create_market_cut(
        create_market_cut_payload(s3["id"], prof2["id"], zone["id"],
                                  p50_cents=13_000_000, sample_size=99,
                                  effective_date="2026-06-01"), ANALYST)
    get_success_data(api_client.accept_market_survey(s1["id"], MANAGER))
    get_success_data(api_client.accept_market_survey(s2["id"], MANAGER))
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fam["id"], lvls[1]["id"], zone["id"],
                                target_percentile="P50", spread_pct=0.5000),
        ANALYST))
    return ctx, band


def test_market_composite_provisional_variant(api):
    """PRD §3.4: "The PROVISIONAL variant — permitted only while the band is in
    `DRAFT` or `PRICED`, which are the only states pricing is legal in anyway —
    admits cuts whose surveys sit in `SUBMITTED` or `ACCEPTED`, applies no
    aging, and computes the composite as the unweighted mean of the raw
    `p50_cents` values: the sum of the medians divided by the number of
    candidate cuts, rounded half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/market_composite_provisional_vs_official
    """
    _ctx, band = _dual_variant_setup()
    priced = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "PROVISIONAL", "expected_pay_band_version": band["version"]},
        ANALYST), 200)
    # Unweighted mean of the three raw medians: (12000000+11500000+13000000)/3.
    assert priced["market_composite_cents"] == 12_166_667
    assert priced["composite_cut_count"] == 3
    assert priced["pricing_variant"] == "PROVISIONAL"


def test_market_composite_official_variant_differs(api):
    """PRD §3.4: "The OFFICIAL variant — mandatory before a band can be
    approved — admits only cuts that satisfy every one of the following: the
    cut's job profile shares the band's family and level, that profile is
    `APPROVED`, the cut's `geo_zone_id` matches the band's, the cut is not
    flagged `excluded_from_composite`, and its survey is `ACCEPTED`. Each
    admitted cut is aged per §3.3, and the composite is the sample-size-weighted
    mean of the aged medians: the sum over candidates of each aged median
    multiplied by its `sample_size`, divided by the sum of the sample sizes,
    rounded half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/market_composite_provisional_vs_official
    """
    _ctx, band = _dual_variant_setup()
    v1 = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "PROVISIONAL", "expected_pay_band_version": band["version"]},
        ANALYST), 200)
    priced = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": v1["version"]},
        ANALYST), 200)
    # Aged A (7 months): 12000000*1.0175 = 12210000 (x40); aged B (13 months):
    # 11500000*1.0325 = 11873750 (x10); weighted mean over 50 samples.
    assert priced["market_composite_cents"] == 12_142_750
    assert priced["composite_cut_count"] == 2
    assert priced["midpoint_cents"] == 12_142_750
    assert priced["min_cents"] == 9_107_063
    assert priced["max_cents"] == 15_178_438
    assert priced["pricing_variant"] == "OFFICIAL"


def _nested_rounding_setup():
    ctx = setup_pricing_program(approve_profiles=(1,))
    bay = create_child_zone("US-BAY", "SF Bay", 1.180000, ctx["zone"]["id"])
    ctx["bay"] = bay
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], bay["id"],
                                    10_000_025, sample_size=30,
                                    effective_date="2026-08-01")
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(ctx["program"]["id"], ctx["family"]["id"],
                                ctx["levels"][1]["id"], bay["id"],
                                target_percentile="P62_5", spread_pct=0.4000),
        ANALYST))
    return ctx, band


def test_midpoint_nested_rounding_per_step(api):
    """PRD §3.4: "Midpoint construction runs immediately after the composite,
    in three steps with rounding after every step."
    PRD §3.4: "The rounding-after-every-step discipline is mandatory:
    collapsing the three steps into a single unrounded product produces a
    different midpoint and is non-conformant."

    Design: Difficulty/combinatorial_formula/midpoint_nested_rounding_order
    """
    _ctx, band = _nested_rounding_setup()
    priced = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": band["version"]},
        ANALYST), 200)
    assert priced["market_composite_cents"] == 10_000_025
    # step1 round(10000025 * 1.06) = 10600027; step2 round(10600027 * 1.18) = 12508032.
    assert priced["midpoint_cents"] == 12_508_032


def test_midpoint_nested_rounding_edges_and_snapshot(api):
    """PRD §3.4: "Second, that result is multiplied by the band's
    `geo_ratio_snapshot` and again rounded half-up to whole cents."
    PRD §3.4: "The `geo_ratio_snapshot` itself is the zone's `effective_ratio`
    captured at pricing time, insulating the priced band from any later
    re-parenting of the zone tree, and `priced_at` is stamped from the logical
    clock as the band's `version` increments and its status moves from `DRAFT`
    to `PRICED`."
    PRD §3.4: "`min_cents` is the midpoint reduced by half the `spread_pct` —
    the midpoint multiplied by one minus half the spread, rounded half-up to
    whole cents — and `max_cents` is the midpoint increased by half the
    spread, computed the same way in the upward direction."

    Design: Difficulty/combinatorial_formula/midpoint_nested_rounding_order
    """
    _ctx, band = _nested_rounding_setup()
    priced = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": band["version"]},
        ANALYST), 200)
    assert priced["min_cents"] == 10_006_426
    assert priced["max_cents"] == 15_009_638
    assert priced["geo_ratio_snapshot"] == pytest.approx(1.180000, abs=1e-9)


def test_price_provisional_empty_candidate_set(api):
    """PRD §3.4: "For either variant, an empty candidate set rejects the price
    call with `ERR_NO_MARKET_DATA` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/price_with_empty_candidate_set
    """
    ctx = setup_pricing_program(approve_profiles=(1,))
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(ctx["program"]["id"], ctx["family"]["id"],
                                ctx["levels"][1]["id"], ctx["zone"]["id"]),
        ANALYST))
    res = api.price_pay_band(
        band["id"],
        {"pricing_variant": "PROVISIONAL", "expected_pay_band_version": band["version"]},
        ANALYST)
    validate_error(res, ApiErrorId.ERR_NO_MARKET_DATA, expected_status=422)


def test_price_official_empty_candidate_set_leaves_band_untouched(api):
    """PRD §3.4: "For either variant, an empty candidate set rejects the price
    call with `ERR_NO_MARKET_DATA` (HTTP 422)."
    PRD §3.4: "A new band opens in `DRAFT` with `pricing_variant` null and with
    `market_composite_cents`, `composite_cut_count`, `midpoint_cents`,
    `min_cents`, `max_cents`, `geo_ratio_snapshot`, and `priced_at` all unset
    until the first pricing."

    Design: Difficulty/boundary_precision_check/price_with_empty_candidate_set
    """
    ctx = setup_pricing_program(approve_profiles=(1,))
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(ctx["program"]["id"], ctx["family"]["id"],
                                ctx["levels"][1]["id"], ctx["zone"]["id"]),
        ANALYST))
    res = api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": band["version"]},
        ANALYST)
    validate_error(res, ApiErrorId.ERR_NO_MARKET_DATA, expected_status=422)
    after = validate_success(api.get_pay_band(band["id"], ANALYST), 200)
    assert after["status"] == "DRAFT"
    assert after["midpoint_cents"] is None
    assert after["version"] == band["version"]


def test_price_rejected_while_program_draft(api):
    """PRD §2.4: "The posture gate rejects with `ERR_PROGRAM_STATE_FORBIDS`
    (HTTP 409) any of the following attempted against a program in the wrong
    status: pricing a band (requires `PRICING` or `MAPPING_OPEN`), publishing
    a band (requires `PRICING` or `MAPPING_OPEN`), submitting a mapping
    decision (requires `MAPPING_OPEN`), creating an exception request
    (requires `PUBLISHED`), scheduling a refresh cycle (requires `PUBLISHED`),
    and applying a refresh cycle (requires `PUBLISHED`)."

    Design: Difficulty/cross_entity_state_dependency/band_price_gated_by_program_posture
    """
    ctx = setup_pricing_program(approve_profiles=(1,))
    prog = ctx["program"]
    # Roll a second program that stays in DRAFT but shares the framework.
    draft_prog = create_program()
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], ctx["zone"]["id"],
                                    13_000_000, sample_size=20)
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(draft_prog["id"], ctx["family"]["id"],
                                ctx["levels"][1]["id"], ctx["zone"]["id"]),
        ANALYST))
    res = api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": band["version"]},
        ANALYST)
    validate_error(res, ApiErrorId.ERR_PROGRAM_STATE_FORBIDS, expected_status=409)


def test_price_succeeds_after_program_reaches_pricing(api):
    """PRD §2.4: "Moving from `FRAMEWORK_LOCKED` to `PRICING` requires that at
    least one job profile in `APPROVED` status exists, and entering `PRICING`
    makes band pricing calls legal for the program."

    Design: Difficulty/cross_entity_state_dependency/band_price_gated_by_program_posture
    """
    ctx = setup_pricing_program(approve_profiles=(1,))
    prog = ctx["program"]
    # Fresh program advanced to PRICING.
    prog2 = create_program()
    advance_program(prog2["id"], "FRAMEWORK_LOCKED")
    advance_program(prog2["id"], "PRICING")
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], ctx["zone"]["id"],
                                    13_000_000, sample_size=20)
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(prog2["id"], ctx["family"]["id"],
                                ctx["levels"][1]["id"], ctx["zone"]["id"]),
        ANALYST))
    priced = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": band["version"]},
        ANALYST), 200)
    assert priced["midpoint_cents"] == 13_000_000
    assert priced["status"] == "PRICED"


def test_occ_band_price_stale_version_rejected(api):
    """PRD §2.7: "Pricing a pay band requires the client to send
    `expected_pay_band_version` carrying the band's `version` as the client
    last observed it; if the band's current `version` has advanced beyond that
    — for example because a prior accepted price call already moved it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), since the client
    priced against market and composite inputs read at an older band version."

    Design: Corner/cross_cutting_layers/occ_band_price_stale_version
    """
    ctx = setup_pricing_program(approve_profiles=(0,))
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], ctx["zone"]["id"],
                                    10_000_000, sample_size=20)
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(ctx["program"]["id"], ctx["family"]["id"],
                                ctx["levels"][0]["id"], ctx["zone"]["id"]),
        ANALYST))
    stale_v = band["version"]
    priced = validate_success(api.price_pay_band(
        band["id"], {"pricing_variant": "OFFICIAL", "expected_pay_band_version": stale_v},
        ANALYST), 200)
    assert priced["version"] == stale_v + 1
    assert priced["midpoint_cents"] == 10_000_000
    res = api.price_pay_band(
        band["id"], {"pricing_variant": "OFFICIAL", "expected_pay_band_version": stale_v},
        ANALYST)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_band_reprice_with_current_version_succeeds(api):
    """PRD §3.4: "Three gates precede the computation, in the precedence order
    of §2.8: the stale-version guard first, then the posture gate requiring
    the band's program to be in `PRICING` or `MAPPING_OPEN` (mid-exercise
    repricing is legitimate, so an open mapping posture does not block a price
    call), then transition legality — pricing is declared only from `DRAFT` or
    `PRICED`, and a re-price from `PRICED` overwrites the previously recorded
    `pricing_variant`."

    Design: Corner/cross_cutting_layers/occ_band_price_stale_version
    """
    ctx = setup_pricing_program(approve_profiles=(0,))
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], ctx["zone"]["id"],
                                    10_000_000, sample_size=20)
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(ctx["program"]["id"], ctx["family"]["id"],
                                ctx["levels"][0]["id"], ctx["zone"]["id"]),
        ANALYST))
    priced = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": band["version"]},
        ANALYST), 200)
    repriced = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": priced["version"]},
        ANALYST), 200)
    assert repriced["version"] == priced["version"] + 1
    assert repriced["midpoint_cents"] == 10_000_000


def test_aging_partial_month_floor(api):
    """PRD §3.3: "The age in months is the number of whole calendar months
    between the cut's `effective_date` and the pricing date — the program's
    `pricing_as_of_date` for manual pricing, or the refresh cycle's
    `effective_date` for refresh pricing — and a partial month never counts."
    PRD §3.3: "The aged median is then the original `p50_cents` grown at the
    escalation rate of three percent per year, prorated by those whole months:
    precisely, the original median multiplied by one plus three-hundredths
    times the month count divided by twelve, with the result rounded half-up
    to a whole cent."

    Design: Corner/calculations/aging_partial_month_floor
    """
    ctx = setup_pricing_program(approve_profiles=(1,))
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], ctx["zone"]["id"],
                                    10_000_000, sample_size=20,
                                    effective_date="2026-01-15")
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(ctx["program"]["id"], ctx["family"]["id"],
                                ctx["levels"][1]["id"], ctx["zone"]["id"]),
        ANALYST))
    priced = validate_success(api.price_pay_band(
        band["id"],
        {"pricing_variant": "OFFICIAL", "expected_pay_band_version": band["version"]},
        ANALYST), 200)
    # 2026-01-15 -> 2026-08-01 is six whole months: 10000000 * 1.015.
    assert priced["market_composite_cents"] == 10_150_000
