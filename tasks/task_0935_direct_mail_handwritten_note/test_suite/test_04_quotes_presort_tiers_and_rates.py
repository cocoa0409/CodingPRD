"""The provisional quote: presort tier selection, the rate card and its rounding."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    FULLY_COVERED_TWELVE_PIECE_ROUTES,
    LIST_OPERATOR,
    SEVEN_RECORD_ROSTER,
    SIX_AUTOMATION_ROSTER,
    assert_eddm_route_selection,
    assert_mail_job,
    build_addressed_scenario,
    build_eddm_scenario,
    read_list_record,
    read_mail_job,
    validate_error,
    validate_success,
)

# One DPV "N" record produces no mailable pieces at all.
DEAD_ROSTER = [
    dict(first_name="Bob", last_name="Jones", address_line1="200 Oak Ave",
         city="Chicago", state_code="IL", zip5="60602", dpv_confirmation_code="N"),
    dict(first_name="Carl", last_name="Lee", address_line1="300 Pine Rd",
         city="Chicago", state_code="IL", zip5="60603", dpv_confirmation_code="N"),
]


def _seven_record_job(permit_number, mail_class):
    return build_addressed_scenario(
        permit_number=permit_number,
        roster=SEVEN_RECORD_ROSTER,
        dedupe_mode="EXACT",
        lock=True,
        mail_class=mail_class,
        stage="draft",
        topup_cents=None,
    )


def test_marketing_quote_rounds_each_tier_before_summing_them(api):
    """PRD §3.4: "First, the automation subtotal is A multiplied by the automation
    rate, rounded half up to a whole number of cents. Second, the retail subtotal
    is R multiplied by the retail rate, rounded half up to a whole number of
    cents. Third, the postage total is those two whole-cent subtotals added
    together."
    PRD §3.4: "Six automation pieces at 31.8 cents give 190.8, which rounds to
    191; one retail piece at 51.6 gives 51.6, which rounds to 52; the correct
    total is 243 cents, whereas rounding the combined 242.4 once yields 242."

    Design: Difficulty/combinatorial_formula/marketing_postage_round_per_tier_then_sum
    """
    world = _seven_record_job("PMT-103", "MARKETING_MAIL")

    quoted = validate_success(api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))
    assert_mail_job(quoted)

    # 6 automation pieces * 31.8 = 190.8 -> 191; 1 retail piece * 51.6 = 51.6 -> 52.
    assert quoted["provisional_postage_cents"] == 243
    assert quoted["provisional_postage_cents"] != 242, (
        "summing the unrounded products and rounding once would give 242"
    )


def test_marketing_quote_selects_the_mixed_aadc_tier_at_six_automation_pieces(api):
    """PRD §3.4: "A `MARKETING_MAIL` job is evaluated against three thresholds
    highest-first, the first satisfied threshold winning: `PRESORT_5D` at 12 or
    more automation pieces, `PRESORT_AADC` at 9 or more, `PRESORT_MIXED_AADC` at
    6 or more, and `NO_PRESORT` below that. Every threshold is inclusive — six
    automation pieces select `PRESORT_MIXED_AADC`, five select `NO_PRESORT`."
    PRD §3.4: "Call the count of surviving automation-tier records **A** and the
    count of surviving retail-tier records **R**; for an addressed job
    `billable_piece_count` is A plus R, `unmailable_piece_count` is the count of
    the list's records at `UNMAILABLE` tier, and `eddm_piece_count` is 0."

    Design: Difficulty/combinatorial_formula/marketing_postage_round_per_tier_then_sum
    """
    world = _seven_record_job("PMT-103", "MARKETING_MAIL")

    quoted = validate_success(api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))

    assert quoted["presort_tier"] == "PRESORT_MIXED_AADC"
    assert quoted["automation_piece_count"] == 6
    assert quoted["retail_piece_count"] == 1
    assert quoted["billable_piece_count"] == 7
    assert quoted["unmailable_piece_count"] == 0
    assert quoted["eddm_piece_count"] == 0


def test_first_class_quote_prices_automation_and_retail_from_two_different_rates(api):
    """PRD §3.4: "For `FIRST_CLASS`, automation-tier pieces price at 58.0 cents
    each when A is at least 6, and at the retail rate of 73.0 cents each when A
    falls below that minimum; retail-tier pieces on a first-class job always price
    at 73.0 cents each."
    PRD §3.4: "First, the automation subtotal is A multiplied by the automation
    rate, rounded half up to a whole number of cents. Second, the retail subtotal
    is R multiplied by the retail rate, rounded half up to a whole number of
    cents. Third, the postage total is those two whole-cent subtotals added
    together."

    Design: Difficulty/combinatorial_formula/first_class_automation_rate_fork_three_input_branch
    """
    world = _seven_record_job("PMT-105", "FIRST_CLASS")

    quoted = validate_success(api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))

    # 6 automation pieces * 58.0 = 348; 1 retail piece * 73.0 = 73; 348 + 73 = 421.
    assert quoted["provisional_postage_cents"] == 421


def test_first_class_quote_takes_presort_aadc_at_six_automation_pieces(api):
    """PRD §3.4: "A `FIRST_CLASS` job takes `PRESORT_AADC` when A is at least 6
    and `NO_PRESORT` otherwise."
    PRD §3.4: "Only A enters this decision; retail-tier and unmailable pieces
    never affect tier selection."

    Design: Difficulty/combinatorial_formula/first_class_automation_rate_fork_three_input_branch
    """
    world = _seven_record_job("PMT-105", "FIRST_CLASS")

    quoted = validate_success(api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))

    assert quoted["presort_tier"] == "PRESORT_AADC"
    assert quoted["automation_piece_count"] == 6
    assert quoted["retail_piece_count"] == 1
    assert quoted["mail_class"] == "FIRST_CLASS"


def test_six_automation_pieces_sit_on_the_inclusive_mixed_aadc_boundary(api):
    """PRD §3.4: "A `MARKETING_MAIL` job is evaluated against three thresholds
    highest-first, the first satisfied threshold winning: `PRESORT_5D` at 12 or
    more automation pieces, `PRESORT_AADC` at 9 or more, `PRESORT_MIXED_AADC` at
    6 or more, and `NO_PRESORT` below that. Every threshold is inclusive — six
    automation pieces select `PRESORT_MIXED_AADC`, five select `NO_PRESORT`."
    PRD §3.4: "For `MARKETING_MAIL`, the automation-tier rate follows the selected
    presort tier: 23.9 cents at `PRESORT_5D`, 28.1 cents at `PRESORT_AADC`, 31.8
    cents at `PRESORT_MIXED_AADC`, and 51.0 cents when the job misses every
    presort tier."

    Design: Difficulty/boundary_precision_check/presort_tier_boundary_six_versus_five_automation_pieces
    """
    world = build_addressed_scenario(
        permit_number="PMT-140", roster=SIX_AUTOMATION_ROSTER, list_name="Six List",
        dedupe_mode=None, lock=False, stage="draft", topup_cents=None,
    )

    quoted = validate_success(api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))

    assert quoted["automation_piece_count"] == 6
    assert quoted["presort_tier"] == "PRESORT_MIXED_AADC"
    # 6 * 31.8 = 190.8, which rounds half up to 191; there is no retail tier here.
    assert quoted["provisional_postage_cents"] == 191


def test_dropping_one_record_below_the_boundary_raises_the_quoted_price(api):
    """PRD §3.3: "A null forwarding address, by contrast, moves `move_status`
    `NONE → MOVE_NO_FORWARD`, forces `dpv_confirmation_code` to `N`, and drives
    `deliverability_tier` to `UNMAILABLE`."
    PRD §3.4: "Every threshold is inclusive — six automation pieces select
    `PRESORT_MIXED_AADC`, five select `NO_PRESORT`."
    PRD §3.4: "For `MARKETING_MAIL`, the automation-tier rate follows the selected
    presort tier: 23.9 cents at `PRESORT_5D`, 28.1 cents at `PRESORT_AADC`, 31.8
    cents at `PRESORT_MIXED_AADC`, and 51.0 cents when the job misses every
    presort tier."

    Design: Difficulty/boundary_precision_check/presort_tier_boundary_six_versus_five_automation_pieces
    """
    world = build_addressed_scenario(
        permit_number="PMT-140", roster=SIX_AUTOMATION_ROSTER, list_name="Six List",
        dedupe_mode=None, lock=False, stage="draft", topup_cents=None,
    )
    validate_success(api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))

    hal = world["records"][5]
    moved = validate_success(
        api.create_ncoa_move(hal["id"], {"new_address_line1": None}, LIST_OPERATOR)
    )
    assert moved["move_status"] == "MOVE_NO_FORWARD"
    assert moved["deliverability_tier"] == "UNMAILABLE"

    requoted = validate_success(api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))
    assert requoted["automation_piece_count"] == 5
    assert requoted["presort_tier"] == "NO_PRESORT"
    # 5 * 51.0 = 255 exactly; fewer pieces at a strictly higher total.
    assert requoted["provisional_postage_cents"] == 255
    assert requoted["unmailable_piece_count"] == 1
    assert read_list_record(hal["id"])["dpv_confirmation_code"] == "N"


def test_a_list_with_no_mailable_records_cannot_be_quoted(api):
    """PRD §3.4: "If a job's billable piece count comes out at zero — an addressed
    job whose survivors were all screened away or all found unmailable, or an EDDM
    job with no routes selected — the quote is refused with
    `ERR_NO_MAILABLE_PIECES` (HTTP 422)."
    PRD §3.3: "Otherwise — that is, for `N` (not confirmed) or `U` (unconfirmed or
    never run) — `cass_status` moves `PENDING → UNMAILABLE` and
    `deliverability_tier` becomes `UNMAILABLE`."

    Design: Corner/calculations/estimate_of_all_unmailable_list_returns_no_mailable_pieces
    """
    world = build_addressed_scenario(
        permit_number="PMT-233", roster=DEAD_ROSTER, list_name="Dead List",
        dedupe_mode=None, lock=False, stage="draft", topup_cents=None,
    )
    assert world["mailing_list"]["mailable_count"] == 0
    assert world["mailing_list"]["unmailable_count"] == 2

    response = api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_NO_MAILABLE_PIECES.value)

    assert read_mail_job(world["job"]["id"])["provisional_postage_cents"] is None


def test_the_two_eddm_rate_variants_diverge_on_identical_route_data(api):
    """PRD §3.4: "Otherwise the rate is 22.3 cents per piece under `SATURATION` and
    25.6 cents per piece under `HIGH_DENSITY_PLUS`, and the postage total is P
    multiplied by that rate, rounded half up to whole cents in a single step. The
    variant choice is consequential on identical data: two fully covered routes of
    six deliveries each yield twelve pieces, priced at 268 cents under
    `SATURATION` and 307 cents under `HIGH_DENSITY_PLUS`."
    PRD §2.9: "an EDDM job's `automation_piece_count`, `retail_piece_count` and
    `unmailable_piece_count` are all zero by construction, and its `presort_tier`
    is always `EDDM_ROUTE` rather than any of the addressed tiers."

    Design: Corner/calculations/eddm_saturation_versus_high_density_plus_rate_divergence
    """
    saturation = build_eddm_scenario(
        permit_number="PMT-230", stage="draft", topup_cents=None,
        routes=FULLY_COVERED_TWELVE_PIECE_ROUTES, eddm_rate_variant="SATURATION",
        target_in_home_date=None,
    )
    high_density = build_eddm_scenario(
        permit_number="PMT-230B", stage="draft", topup_cents=None,
        routes=FULLY_COVERED_TWELVE_PIECE_ROUTES,
        eddm_rate_variant="HIGH_DENSITY_PLUS", target_in_home_date=None,
    )

    sat = validate_success(api.estimate_mail_job(saturation["job"]["id"], CAMPAIGN_MANAGER))
    hdp = validate_success(
        api.estimate_mail_job(high_density["job"]["id"], CAMPAIGN_MANAGER)
    )

    assert sat["eddm_piece_count"] == 12
    assert hdp["eddm_piece_count"] == 12
    # 12 * 22.3 = 267.6 -> 268;  12 * 25.6 = 307.2 -> 307.
    assert sat["provisional_postage_cents"] == 268
    assert hdp["provisional_postage_cents"] == 307
    assert sat["presort_tier"] == "EDDM_ROUTE"
    assert sat["automation_piece_count"] == 0


def test_saturation_is_ineligible_when_a_route_is_only_partly_covered(api):
    """PRD §3.4: "The `SATURATION` variant demands complete coverage: each route's
    `selected_piece_count` must equal that route's `total_deliveries`."
    PRD §3.4: "If the declared variant is not eligible for every route, the
    request fails with `ERR_EDDM_VARIANT_INELIGIBLE` (HTTP 422)."
    PRD §3.4: "From those the server computes `selected_piece_count` as the sum of
    the residential and business counts, and `saturation_pct` as one hundred
    multiplied by `selected_piece_count`, divided by `total_deliveries`, rounded
    half up to two decimal places."

    Design: Corner/calculations/eddm_saturation_ineligible_on_partially_covered_route
    """
    world = build_eddm_scenario(
        permit_number="PMT-231", stage="draft", topup_cents=None,
        eddm_rate_variant="SATURATION", target_in_home_date=None,
        routes=[{"route_code": "C009", "total_deliveries": 8,
                 "residential_piece_count": 4, "business_piece_count": 2}],
    )
    route = world["routes"][0]
    assert_eddm_route_selection(route)
    assert route["selected_piece_count"] == 6
    # 100 * 6 / 8 = 75.00 percent.
    assert float(route["saturation_pct"]) == 75.00

    response = api.estimate_mail_job(world["job"]["id"], CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_EDDM_VARIANT_INELIGIBLE.value)

    assert read_mail_job(world["job"]["id"])["provisional_postage_cents"] is None


def test_attaching_a_carrier_route_to_an_addressed_job_is_a_kind_mismatch(api):
    """PRD §2.9: "Any disagreement among those fields at job creation is
    `ERR_JOB_KIND_MISMATCH` (HTTP 422) at rung 14, as is an attempt to attach a
    carrier route to a job whose `job_kind` is not `EDDM`."
    PRD §3.4: "An EDDM job's pieces come from carrier routes rather than from
    names, and a `CampaignManager` adds them one at a time while the job is still
    `DRAFT` — a later attempt is `ERR_MAIL_JOB_INVALID_STATE`, and an attempt
    against an `ADDRESSED` job is `ERR_JOB_KIND_MISMATCH` at the earlier rung 14."

    Design: Corner/validations/eddm_route_on_addressed_job_returns_job_kind_mismatch
    """
    world = build_addressed_scenario(
        permit_number="PMT-246", dedupe_mode=None, lock=False, stage="draft",
        target_in_home_date=None, topup_cents=None,
    )

    response = api.create_eddm_route(
        world["job"]["id"],
        {"route_code": "C001", "total_deliveries": 6,
         "residential_piece_count": 4, "business_piece_count": 2},
        CAMPAIGN_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_JOB_KIND_MISMATCH.value)

    job = read_mail_job(world["job"]["id"])
    assert job["eddm_piece_count"] == 0
    assert job["job_kind"] == "ADDRESSED"
