"""Allocating a revenue pool: the two run variants, the remainder pass, the basis."""

from test_helpers import (
    ApiErrorId,
    RunVariant,
    assert_cents_conserved,
    assert_fields_equal,
    assert_line,
    assert_reconciliation,
    close_pool_books,
    compute_run,
    lines_by_member,
    make_distribution_run_payload,
    make_finance_officer_headers,
    read_revenue_pool,
    read_run_lines,
    setup_approved_bowl_appearance,
    setup_books_closed_media_fixture,
    setup_full_media_fixture,
    setup_operating_conference_with_reserve,
    setup_unit_based_pool,
    validate_error,
    validate_success,
    void_bowl_appearance,
)

FY2027_AUDITED_EXPENSE_CENTS = 26_500_000


def test_provisional_run_counts_scheduled_games_and_submitted_berths(api):
    """PRD §3.7: "A media appearance is a schedule game in the pool's `fiscal_year` with
    `media_designated` true in which the member appears as either `home_member_id` or
    `away_member_id`; for a `PROVISIONAL` run such a game counts while its status is
    `SCHEDULED` or `PLAYED`, while for a `FINAL_AUDITED` run only `PLAYED` games count."
    PRD §3.7: "A postseason berth is a bowl appearance of that member in the pool's
    `fiscal_year`; for a `PROVISIONAL` run it counts while its status is `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED` or `APPROVED`, while for a `FINAL_AUDITED` run
    only `APPROVED` appearances count."
    PRD §3.7: "Under `APPEARANCE_PERFORMANCE_WEIGHTED` it is 10000, plus 1500 for each
    media appearance, plus 2500 for each postseason berth."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_audited_media_distribution
    """
    ctx = setup_full_media_fixture(api)
    ids = ctx["member_ids"]

    run = compute_run(api, ctx["pool_id"], RunVariant.PROVISIONAL.value)

    assert_fields_equal(
        run,
        variant="PROVISIONAL",
        status="COMPUTED",
        net_pool_cents=480_000_000,
        reserve_draw_cents=6_000_000,
        distributable_cents=474_000_000,
        total_weight_bps=57000,
    )
    lines = lines_by_member(read_run_lines(api, run["id"]))
    assert set(lines) == set(ids.values())
    # North: three media-designated games and one berth; West: one scheduled game and
    # the berth its still-SUBMITTED appearance carries.
    assert_line(lines[ids["north"]], weight_bps=17000, gross_share_cents=141_368_422)
    assert_line(lines[ids["south"]], weight_bps=13000, gross_share_cents=108_105_263)
    assert_line(lines[ids["east"]], weight_bps=13000, gross_share_cents=108_105_263)
    assert_line(lines[ids["west"]], weight_bps=14000, gross_share_cents=116_421_052)


def test_final_audited_run_counts_only_played_games_and_approved_berths(api):
    """PRD §3.7: "The expense basis depends on the variant: a `PROVISIONAL` run uses
    `estimated_expense_cents` and a `FINAL_AUDITED` run uses `audited_expense_cents`."
    PRD §3.7: "A media appearance is a schedule game in the pool's `fiscal_year` with
    `media_designated` true in which the member appears as either `home_member_id` or
    `away_member_id`; for a `PROVISIONAL` run such a game counts while its status is
    `SCHEDULED` or `PLAYED`, while for a `FINAL_AUDITED` run only `PLAYED` games count."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_audited_media_distribution
    """
    ctx = setup_books_closed_media_fixture(api)
    ids = ctx["member_ids"]

    run = compute_run(api, ctx["pool_id"], RunVariant.FINAL_AUDITED.value)

    assert_fields_equal(
        run,
        variant="FINAL_AUDITED",
        status="COMPUTED",
        net_pool_cents=473_500_000,
        reserve_draw_cents=6_000_000,
        distributable_cents=467_500_000,
        total_weight_bps=51500,
    )
    lines = lines_by_member(read_run_lines(api, run["id"]))
    # North keeps two played games and its approved berth; West's scheduled game and
    # voided appearance both drop out, leaving it on the bare base weight.
    assert_line(lines[ids["north"]], weight_bps=15500, gross_share_cents=140_703_884)
    assert_line(lines[ids["south"]], weight_bps=13000, gross_share_cents=118_009_709)
    assert_line(lines[ids["east"]], weight_bps=13000, gross_share_cents=118_009_708)
    assert_line(lines[ids["west"]], weight_bps=10000, gross_share_cents=90_776_699)


def test_final_audited_run_charges_no_withholding_and_supersedes_the_provisional(api):
    """PRD §3.7: "The `withheld_cents` is `gross_share_cents` multiplied by the provisional
    withholding of 1000 basis points and divided by 10000, rounded up, on a `PROVISIONAL`
    run, and exactly 0 on a `FINAL_AUDITED` run."
    PRD §3.7: "A successful computation creates the run in `COMPUTED` with one `ACTIVE`
    line per line member, records the acting user as `computed_by_user_id`, writes
    `net_pool_cents`, `reserve_draw_cents`, `distributable_cents` and `total_weight_bps`,
    sets any earlier run on the same pool that is still `COMPUTED` to `SUPERSEDED` with
    `superseded_by_run_id` pointing at the new run and every one of that older run's
    `ACTIVE` lines moved to `VOIDED`, and advances the pool's `version` by 1."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_audited_media_distribution
    """
    ctx = setup_full_media_fixture(api)
    ids = ctx["member_ids"]
    provisional = compute_run(api, ctx["pool_id"], RunVariant.PROVISIONAL.value)
    provisional_lines = lines_by_member(read_run_lines(api, provisional["id"]))
    assert_line(
        provisional_lines[ids["north"]],
        status="ACTIVE",
        withheld_cents=14_136_843,
        governance_fee_cents=1_250_000,
        net_payable_cents=125_981_579,
    )

    void_bowl_appearance(api, ctx["appearance_west"]["id"])
    close_pool_books(api, ctx["pool_id"], FY2027_AUDITED_EXPENSE_CENTS)
    final = compute_run(api, ctx["pool_id"], RunVariant.FINAL_AUDITED.value)

    final_lines = lines_by_member(read_run_lines(api, final["id"]))
    for line in final_lines.values():
        assert line["withheld_cents"] == 0, "a final audited line withholds nothing"
    assert_line(
        final_lines[ids["north"]],
        governance_fee_cents=1_250_000,
        net_payable_cents=139_453_884,
    )
    superseded = validate_success(
        api.get_distribution_run(
            provisional["id"], headers=make_finance_officer_headers()
        )
    )
    assert_fields_equal(
        superseded, status="SUPERSEDED", superseded_by_run_id=final["id"]
    )
    for line in read_run_lines(api, provisional["id"]):
        assert line["status"] == "VOIDED", "the superseded run's lines are voided"


def test_remainder_cents_break_an_equal_weight_tie_by_member_created_at(api):
    """PRD §3.7: "The receiving order is the line members sorted by `weight_bps` descending
    and, among equal weights, by the member's `created_at` ascending; the cents are dealt
    out along that order cyclically, so if there are more leftover cents than lines the
    order wraps around and a line may be topped up more than once."
    PRD §3.7: "Each time a line receives a cent its `gross_share_cents` rises by 1 and its
    `remainder_cent_awarded` rises by 1."

    Design: Difficulty/combinatorial_formula/remainder_cent_order_breaks_equal_weight_tie_by_created_at
    """
    ctx = setup_books_closed_media_fixture(api)
    ids = ctx["member_ids"]
    assert (
        ctx["members"]["south"]["created_at"] < ctx["members"]["east"]["created_at"]
    ), "South was seated before East, so it wins the tie-break"

    run = compute_run(api, ctx["pool_id"], RunVariant.FINAL_AUDITED.value)

    lines = lines_by_member(read_run_lines(api, run["id"]))
    # Two leftover cents: the first goes to the heaviest line, the second to the earlier
    # of the two lines that carry identical weight.
    assert_line(lines[ids["north"]], weight_bps=15500, remainder_cent_awarded=1)
    assert_line(lines[ids["south"]], weight_bps=13000, remainder_cent_awarded=1)
    assert_line(lines[ids["east"]], weight_bps=13000, remainder_cent_awarded=0)
    assert_line(lines[ids["west"]], weight_bps=10000, remainder_cent_awarded=0)
    assert (
        lines[ids["south"]]["gross_share_cents"]
        == lines[ids["east"]]["gross_share_cents"] + 1
    ), "the tied pair differ by exactly the one dealt cent"


def test_remainder_cent_goes_to_the_heaviest_line_before_any_tied_line(api):
    """PRD §3.7: "The receiving order is the line members sorted by `weight_bps` descending
    and, among equal weights, by the member's `created_at` ascending; the cents are dealt
    out along that order cyclically, so if there are more leftover cents than lines the
    order wraps around and a line may be topped up more than once."

    Design: Difficulty/combinatorial_formula/remainder_cent_order_breaks_equal_weight_tie_by_created_at
    """
    ctx = setup_full_media_fixture(api)
    ids = ctx["member_ids"]

    run = compute_run(api, ctx["pool_id"], RunVariant.PROVISIONAL.value)

    lines = lines_by_member(read_run_lines(api, run["id"]))
    # A single leftover cent, so only the heaviest line is topped up and neither member
    # of the tied pair receives anything.
    assert_line(lines[ids["north"]], weight_bps=17000, remainder_cent_awarded=1)
    assert_line(lines[ids["west"]], weight_bps=14000, remainder_cent_awarded=0)
    assert_line(lines[ids["south"]], weight_bps=13000, remainder_cent_awarded=0)
    assert_line(lines[ids["east"]], weight_bps=13000, remainder_cent_awarded=0)
    assert (
        lines[ids["south"]]["gross_share_cents"]
        == lines[ids["east"]]["gross_share_cents"]
    ), "equal weights that receive no cent land on the identical floored share"


def test_provisional_run_reconciliation_identity_is_exactly_zero(api):
    """PRD §3.9: "Summing those active lines gives `total_net_payable_cents`,
    `total_withheld_cents`, `total_governance_fee_cents` and `total_gor_offset_cents`, and
    the `reconciliation_delta_cents` is the run's `net_pool_cents` minus the sum of its
    `reserve_draw_cents` and those four totals."
    PRD §3.9: "For a run whose lines are all active the delta must be exactly 0 — that is
    the invariant the pinned remainder pass of §3.7 exists to guarantee, and it is the
    reason reversing a posted run must restore every conference counter it moved."

    Design: Difficulty/compensating_invariant/distribution_run_conserves_every_cent_of_the_net_pool
    """
    ctx = setup_full_media_fixture(api)
    run = compute_run(api, ctx["pool_id"], RunVariant.PROVISIONAL.value)

    reconciliation = validate_success(
        api.get_run_reconciliation(run["id"], headers=make_finance_officer_headers())
    )

    assert_reconciliation(
        reconciliation,
        net_pool_cents=480_000_000,
        reserve_draw_cents=6_000_000,
        total_net_payable_cents=421_599_997,
        total_withheld_cents=47_400_003,
        total_governance_fee_cents=5_000_000,
        total_gor_offset_cents=0,
        reconciliation_delta_cents=0,
    )
    assert reconciliation["distribution_run_id"] == run["id"]


def test_floor_then_deal_pass_leaves_no_cent_of_the_distributable_unallocated(api):
    """PRD §3.7: "Rounding each line half-up and summing is explicitly **not** the rule and
    produces a different, non-conserving answer; the floor-then-deal pass exists so that
    not one cent of `distributable_cents` disappears."
    PRD §3.9: "For a run whose lines are all active the delta must be exactly 0 — that is
    the invariant the pinned remainder pass of §3.7 exists to guarantee, and it is the
    reason reversing a posted run must restore every conference counter it moved."

    Design: Difficulty/compensating_invariant/distribution_run_conserves_every_cent_of_the_net_pool
    """
    ctx = setup_books_closed_media_fixture(api)
    run = compute_run(api, ctx["pool_id"], RunVariant.FINAL_AUDITED.value)
    lines = read_run_lines(api, run["id"])

    assert_cents_conserved(467_500_000, lines)

    reconciliation = validate_success(
        api.get_run_reconciliation(run["id"], headers=make_finance_officer_headers())
    )
    assert_reconciliation(
        reconciliation,
        net_pool_cents=473_500_000,
        reserve_draw_cents=6_000_000,
        total_net_payable_cents=462_500_000,
        total_withheld_cents=0,
        total_governance_fee_cents=5_000_000,
        total_gor_offset_cents=0,
        reconciliation_delta_cents=0,
    )


def test_unit_based_pool_with_zero_validated_units_has_an_empty_basis(api):
    """PRD §3.7: "Under `UNIT_BASED` it is 10000 multiplied by the member's count of
    postseason units in status `VALIDATED` whose `fiscal_year` equals the pool's
    `fiscal_year` — so a member with no validated units for that year has a raw weight of
    exactly 0."
    PRD §3.7: "The `total_weight_bps` recorded on the run is the sum of `weight_bps` over
    the members that do receive a line, and if that total is 0 the whole request is refused
    with `ERR_EMPTY_ALLOCATION_BASIS`."

    Design: Difficulty/boundary_precision_check/unit_based_pool_with_zero_validated_units_is_empty_basis
    """
    ctx = setup_operating_conference_with_reserve(api)
    pool = setup_unit_based_pool(api, ctx)

    response = api.create_distribution_run(
        pool["id"],
        make_distribution_run_payload(pool["version"], RunVariant.PROVISIONAL.value),
        headers=make_finance_officer_headers(),
    )

    validate_error(response, ApiErrorId.ERR_EMPTY_ALLOCATION_BASIS.value, 422)
    runs = validate_success(
        api.list_pool_distribution_runs(
            pool["id"], headers=make_finance_officer_headers()
        )
    )
    assert runs == [], "a refused computation leaves no run behind"
    assert read_revenue_pool(api, pool["id"])["version"] == pool["version"]


def test_unit_based_pool_allocates_only_to_members_holding_validated_units(api):
    """PRD §3.7: "Under `UNIT_BASED` it is 10000 multiplied by the member's count of
    postseason units in status `VALIDATED` whose `fiscal_year` equals the pool's
    `fiscal_year` — so a member with no validated units for that year has a raw weight of
    exactly 0."
    PRD §3.7: "A member whose `weight_bps` lands on exactly 0 — a fully phased-in school in
    a unit-based pool with no validated units, or a first-year school whose raw weight is
    small enough that the phase fraction floors it away — receives no distribution line at
    all, and therefore is never charged the governance service fee either."

    Design: Difficulty/boundary_precision_check/unit_based_pool_with_zero_validated_units_is_empty_basis
    """
    ctx = setup_operating_conference_with_reserve(api)
    setup_approved_bowl_appearance(
        api,
        ctx["member_ids"]["north"],
        event_name="Prairie Bowl",
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=2,
    )
    pool = setup_unit_based_pool(api, ctx)

    run = compute_run(api, pool["id"], RunVariant.PROVISIONAL.value)

    assert_fields_equal(
        run,
        status="COMPUTED",
        net_pool_cents=100_000_000,
        reserve_draw_cents=5_000_000,
        distributable_cents=95_000_000,
        total_weight_bps=20000,
    )
    lines = read_run_lines(api, run["id"])
    assert len(lines) == 1, "only the member holding validated units receives a line"
    assert_line(
        lines[0],
        member_id=ctx["member_ids"]["north"],
        weight_bps=20000,
        gross_share_cents=95_000_000,
        remainder_cent_awarded=0,
        withheld_cents=9_500_000,
        governance_fee_cents=1_250_000,
        net_payable_cents=84_250_000,
    )
