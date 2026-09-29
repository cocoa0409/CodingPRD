"""Premium rating, risk scoring, cancellation and allocation arithmetic.

Every test builds its own account from the published endpoints because the
database is empty at the start of each test and the logical clock reads
2026-08-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers import factories
from test_helpers import fixtures
from test_helpers.assertions import (
    allocation_line,
    assert_allocation_line_order,
    assert_claim_incurred_identity,
    assert_premium_transaction,
)


def _fire_resistive_inland_overrides(name, site_address, hard_cost_value_cents):
    """A FIRE_RESISTIVE / INLAND project screened grade A."""
    return {
        "engineering_grade": "A",
        "name": name,
        "site_address": site_address,
        "construction_type": "FIRE_RESISTIVE",
        "project_kind": "NEW_CONSTRUCTION",
        "hard_cost_value_cents": hard_cost_value_cents,
        "cat_zone": "INLAND",
        "planned_start_date": "2026-09-01T00:00:00Z",
        "projected_completion_date": "2027-03-01T00:00:00Z",
    }


def test_minimum_premium_floor_below_at_and_above_the_boundary():
    """The quoted premium is the greater of the computed figure and 250000 cents.

    Section 3.4 says the quoted premium is "the greater of that figure and the
    minimum premium of 250000 cents", and "where the pre-floor figure equals the
    minimum exactly, the pre-floor figure stands". Three FIRE_RESISTIVE / INLAND
    schedules over a 200-day term compute 249920, 250000 and 250080 cents.

    Design: Corner/calculations/corner_minimum_premium_floor_binds_below_at_and_above_the_boundary
    """
    accounts = []
    for name, address, hard_cost in (
        ("Floor Low", "1 Floor Rd", 312400000),
        ("Floor Exact", "2 Floor Rd", 312500000),
        ("Floor High", "3 Floor Rd", 312600000),
    ):
        accounts.append(fixtures.draft_account(
            parts=(("MATERIALS_ON_SITE", 300000000),),
            with_owner=False,
            project_overrides=_fire_resistive_inland_overrides(
                name, address, hard_cost),
            term_start_date="2026-09-01T00:00:00Z",
            term_end_date="2027-03-20T00:00:00Z",
            includes_existing_structure=False,
            deductible_tier="STANDARD_25K",
            limit_cents=400000000,
            daily_delay_rate_cents=0,
        ))
    low, exact, high = accounts

    # A FIRE_RESISTIVE / INLAND project of this size scores 6 points, far below
    # the 75-point referral threshold, so each rating lands on QUOTED.
    assert low.project["submission_risk_score"] == 6, low.project
    assert low.policy["original_term_days"] == 200, low.policy

    quoted = []
    for account in accounts:
        policy = validate_success(
            api_client.quote_policy(account.policy_id, fixtures.UW))
        assert policy["status"] == "QUOTED", policy
        quoted.append(policy["quoted_premium_cents"])
    q_low, q_exact, q_high = quoted

    assert q_low == 250000, q_low
    assert q_exact == 250000, q_exact
    assert q_high == 250080, q_high
    # 80 cents per 1000 rated units: the floor is a max(), not a clamp.
    assert q_high - q_exact == 80, (q_exact, q_high)
    assert low.policy["insured_tiv_cents"] == 312400000, low.policy
    assert exact.policy["insured_tiv_cents"] == 312500000, exact.policy
    assert high.policy["insured_tiv_cents"] == 312600000, high.policy


def _terminal_overrides(name, site_address, projected_completion_date):
    """A NON_COMBUSTIBLE / WIND_TIER_2 terminal with a $20,000,000 hard cost."""
    return {
        "engineering_grade": "B",
        "name": name,
        "site_address": site_address,
        "construction_type": "NON_COMBUSTIBLE",
        "project_kind": "NEW_CONSTRUCTION",
        "hard_cost_value_cents": 2000000000,
        "cat_zone": "WIND_TIER_2",
        "planned_start_date": "2026-09-01T00:00:00Z",
        "projected_completion_date": projected_completion_date,
    }


def test_duration_load_activates_only_above_twelve_whole_months():
    """The duration load charges 2 percent of base per whole month beyond twelve.

    Section 3.4: "the month count is original_term_days divided by 30 and rounded
    up to a whole number, the excess over twelve months is floored at zero". A
    360-day term is 12 months and takes nothing; a 390-day term is 13 months and
    takes exactly one month of load.

    Design: Corner/calculations/corner_duration_load_activates_only_above_twelve_whole_months
    """
    twelve = fixtures.draft_account(
        parts=(("MATERIALS_ON_SITE", 1000000000),),
        with_owner=False,
        project_overrides=_terminal_overrides(
            "Twelve Month Terminal", "10 Dock Rd", "2027-08-01T00:00:00Z"),
        term_start_date="2026-09-01T00:00:00Z",
        term_end_date="2027-08-27T00:00:00Z",
        includes_existing_structure=False,
        deductible_tier="STANDARD_25K",
        limit_cents=2500000000,
        daily_delay_rate_cents=0,
    )
    thirteen = fixtures.draft_account(
        parts=(("MATERIALS_ON_SITE", 1000000000),),
        with_owner=False,
        project_overrides=_terminal_overrides(
            "Thirteen Month Terminal", "11 Dock Rd", "2027-09-01T00:00:00Z"),
        term_start_date="2026-09-01T00:00:00Z",
        term_end_date="2027-09-26T00:00:00Z",
        includes_existing_structure=False,
        deductible_tier="STANDARD_25K",
        limit_cents=2500000000,
        daily_delay_rate_cents=0,
    )

    assert twelve.policy["original_term_days"] == 360, twelve.policy
    assert thirteen.policy["original_term_days"] == 390, thirteen.policy
    # The schedule points follow the project's own dates, not the policy term.
    assert twelve.project["submission_risk_score"] == 28, twelve.project
    assert thirteen.project["submission_risk_score"] == 30, thirteen.project

    q_twelve = validate_success(
        api_client.quote_policy(twelve.policy_id, fixtures.UW))
    q_thirteen = validate_success(
        api_client.quote_policy(thirteen.policy_id, fixtures.UW))

    assert q_twelve["status"] == "QUOTED", q_twelve
    assert q_thirteen["status"] == "QUOTED", q_thirteen
    # base 2200000 + cat 396000, with one 44000 month of load on the longer term.
    assert q_twelve["quoted_premium_cents"] == 2596000, q_twelve
    assert q_thirteen["quoted_premium_cents"] == 2640000, q_thirteen
    assert (q_thirteen["quoted_premium_cents"]
            - q_twelve["quoted_premium_cents"]) == 44000


RENOVATION_PROJECT = {
    "name": "Fifth Avenue Renovation",
    "site_address": "5 Fifth Ave, Rockvale",
    "construction_type": "JOISTED_MASONRY",
    "project_kind": "RENOVATION",
    "hard_cost_value_cents": 1500000000,
    "existing_structure_value_cents": 500000000,
    "cat_zone": "SEISMIC",
    "planned_start_date": "2026-10-01T00:00:00Z",
    "projected_completion_date": "2027-04-15T00:00:00Z",
}

RENOVATION_PARTS = (
    ("MATERIALS_ON_SITE", 1000000000),
    ("SOFT_COST", 200000000),
    ("DELAY_IN_COMPLETION", 150000000),
)


def _renovation_policy(project, includes_existing_structure):
    """Write one renovation policy and schedule its three coverage parts."""
    account = fixtures.Account(project=project)
    payload = factories.create_policy_payload(
        project["id"], project["version"],
        term_start_date="2026-10-01T00:00:00Z",
        term_end_date="2027-04-30T00:00:00Z",
        includes_existing_structure=includes_existing_structure,
        deductible_tier="STANDARD_25K",
        limit_cents=2000000000,
        daily_delay_rate_cents=900000)
    account.policy = validate_success(
        api_client.create_policy(payload, fixtures.UW), expected_status=201)
    for part_type, sublimit_cents in RENOVATION_PARTS:
        fixtures.schedule_part(account, part_type, sublimit_cents)
    return account


def test_renovation_pricing_diverges_on_the_existing_structure_election():
    """Electing the existing structure lifts base, catastrophe and renovation load.

    Section 3.4: on a RENOVATION project "when includes_existing_structure is true
    the pre-existing structure's value enters insured_tiv_cents, which lifts the
    base premium and therefore the catastrophe load, the duration load and the
    renovation load together". The same project prices at 4320000 with the
    structure included and 3292500 with it excluded.

    Design: Corner/calculations/corner_renovation_variant_diverges_on_the_existing_structure_election
    """
    project = fixtures.eligible_project(
        engineering_grade="B", **RENOVATION_PROJECT)
    # The screening score counts the existing structure whatever the policy elects.
    assert project["submission_risk_score"] == 52, project

    included = _renovation_policy(project, True)
    assert included.policy["insured_tiv_cents"] == 2000000000, included.policy

    q_included = validate_success(
        api_client.quote_policy(included.policy_id, fixtures.UW))
    assert q_included["quoted_premium_cents"] == 4320000, q_included

    # Pull the quote back so the same project can carry a second draft.
    reopened = validate_success(
        api_client.reopen_policy(included.policy_id, fixtures.UW))
    assert reopened["status"] == "DRAFT", reopened
    assert reopened["quoted_premium_cents"] is None, reopened

    excluded = _renovation_policy(
        validate_success(api_client.get_project(project["id"], fixtures.UW)),
        False)
    assert excluded.policy["insured_tiv_cents"] == 1500000000, excluded.policy

    q_excluded = validate_success(
        api_client.quote_policy(excluded.policy_id, fixtures.UW))
    assert q_excluded["quoted_premium_cents"] == 3292500, q_excluded

    # base 750000 + cat 187500 + renovation 90000 all move together.
    assert (q_included["quoted_premium_cents"]
            - q_excluded["quoted_premium_cents"]) == 1027500

    superseded = validate_success(
        api_client.get_policy(included.policy_id, fixtures.UW))
    assert superseded["status"] == "SUPERSEDED", superseded
    # Reopening had already cleared the price, and superseding clears nothing.
    assert superseded["quoted_premium_cents"] is None, superseded


def _longspan_project(name, site_address, projected_completion_date):
    """A FRAME / WIND_TIER_1 bridge deck worth $100,000,000."""
    return fixtures.submit_project(
        name=name,
        site_address=site_address,
        construction_type="FRAME",
        project_kind="NEW_CONSTRUCTION",
        hard_cost_value_cents=10000000000,
        cat_zone="WIND_TIER_1",
        planned_start_date="2026-01-01T00:00:00Z",
        projected_completion_date=projected_completion_date)


def test_ineligible_threshold_at_eighty_nine_and_ninety_with_the_schedule_cap():
    """A score of 90 or more declines the project; the schedule term caps at 15.

    Section 3.1 caps the schedule component at 15 points and declines a project
    whose score "is 90 or more". A 550-day programme takes 14 schedule points and
    scores 89; a 580-day programme would take 16 but is clipped to 15, so it
    scores exactly 90 and screens INELIGIBLE.

    Design: Corner/calculations/corner_ineligible_threshold_at_eighty_nine_and_ninety_with_the_duration_cap
    """
    below = _longspan_project(
        "Longspan Bridge Deck A", "1 Longspan Way", "2027-07-05T00:00:00Z")
    at = _longspan_project(
        "Longspan Bridge Deck B", "2 Longspan Way", "2027-08-04T00:00:00Z")

    screened_below = validate_success(api_client.screen_project(
        below["id"],
        {"engineering_grade": "B", "loss_control_report_ref": "LC-A"},
        fixtures.RE))
    screened_at = validate_success(api_client.screen_project(
        at["id"],
        {"engineering_grade": "B", "loss_control_report_ref": "LC-B"},
        fixtures.RE))

    assert screened_below["submission_risk_score"] == 89, screened_below
    assert screened_below["status"] == "ELIGIBLE", screened_below
    # The score is stored on the declined project along with the grade and report.
    assert screened_at["submission_risk_score"] == 90, screened_at
    assert screened_at["status"] == "INELIGIBLE", screened_at
    assert screened_at["engineering_grade"] == "B", screened_at
    assert screened_at["loss_control_report_ref"] == "LC-B", screened_at

    refused = api_client.create_policy(
        factories.create_policy_payload(
            at["id"], screened_at["version"],
            term_start_date="2026-01-01T00:00:00Z",
            term_end_date="2027-08-31T00:00:00Z",
            includes_existing_structure=False,
            deductible_tier="STANDARD_25K",
            limit_cents=10000000000,
            daily_delay_rate_cents=0),
        fixtures.UW)
    validate_error(refused, "ERR_INVALID_PROJECT_STATE", expected_status=409)

    policies, meta = validate_paginated(
        api_client.list_project_policies(at["id"], fixtures.UW))
    assert meta["total_count"] == 0, meta
    assert policies == [], policies


HARBORLINE_PARTS = (
    ("MATERIALS_ON_SITE", 1000000000),
    ("SOFT_COST", 300000000),
    ("DELAY_IN_COMPLETION", 250000000),
)


def test_audit_risk_score_counts_only_qualifying_claims():
    """The audit score counts adjusted claims and ignores denied ones.

    Section 3.1 recomputes the audit score on every claim adjustment, counting
    5 points per claim of the policy whose adjustment status is ADJUSTED, SETTLED
    or CLOSED. The first adjustment lifts 28 to 33; denying a second claim leaves
    it at 33.

    Design: Corner/calculations/corner_audit_basis_counts_only_qualifying_claims
    """
    account = fixtures.in_force_account(parts=HARBORLINE_PARTS)
    project = validate_success(
        api_client.get_project(account.project_id, fixtures.RE))
    assert project["submission_risk_score"] == 28, project
    # Screening never fills the audit variant.
    assert project["audit_risk_score"] is None, project

    first = fixtures.report_claim(
        account, peril="FIRE", loss_date="2026-11-15T00:00:00Z",
        description="Formwork fire on level 3")
    second = fixtures.report_claim(
        account, peril="THEFT", loss_date="2026-12-01T00:00:00Z",
        description="Alleged copper theft, later found on site")

    reported = validate_success(
        api_client.get_project(account.project_id, fixtures.RE))
    # Two claims still only REPORTED contribute nothing at all.
    assert reported["audit_risk_score"] is None, reported

    adjusted = fixtures.adjust_claim(
        account, first,
        loss_items=[factories.loss_item("MATERIALS_ON_SITE", 20000000)],
        adjustment_basis="RECONSTRUCTION_COST", continuing_pm_weeks=0)
    assert adjusted["adjustment_status"] == "ADJUSTED", adjusted
    # 20000000 uplifted by 1.08 is 21600000, less the 10000000 deductible.
    assert adjusted["indemnity_cents"] == 11600000, adjusted

    after_one = validate_success(
        api_client.get_project(account.project_id, fixtures.RE))
    assert after_one["audit_risk_score"] == 33, after_one

    denied = validate_success(api_client.adjust_claim(
        second["id"], factories.adjust_claim_payload(outcome="DENY"),
        fixtures.CA))
    assert denied["adjustment_status"] == "DENIED", denied
    assert denied["indemnity_cents"] == 0, denied

    after_two = validate_success(
        api_client.get_project(account.project_id, fixtures.RE))
    assert after_two["audit_risk_score"] == 33, after_two
    # The two bases are stored side by side and never overwrite each other.
    assert after_two["submission_risk_score"] == 28, after_two


def test_cancellation_return_premium_variant_is_selected_by_cancel_reason():
    """CARRIER_INITIATED returns the full pro-rata; INSURED_REQUEST short-rates it.

    Section 3.9 pins the order: "the pro-rata figure is rounded *first*, and any
    retention and fee then apply to the rounded figure". A carrier-initiated
    cancellation returns the whole 1639335; the same term at the insured's request
    returns ninety percent of that, itself rounded, less the 25000-cent fee.

    Design: Corner/calculations/corner_cancellation_variant_is_selected_by_cancel_reason
    """
    carrier = fixtures.in_force_account(
        parts=HARBORLINE_PARTS,
        project_overrides={
            "name": "Harborline Terminal Expansion",
            "site_address": "410 Dock Rd, Newport",
        })
    insured = fixtures.in_force_account(
        parts=HARBORLINE_PARTS,
        project_overrides={
            "name": "Harborline Terminal Expansion Phase Two",
            "site_address": "412 Dock Rd, Newport",
        })

    assert carrier.policy["original_term_days"] == 302, carrier.policy
    assert carrier.policy["written_premium_cents"] == 2750440, carrier.policy
    assert insured.policy["written_premium_cents"] == 2750440, insured.policy

    carrier_policy = fixtures.cancel_account(
        carrier, cancel_reason="CARRIER_INITIATED",
        cancel_effective_date="2027-01-01T00:00:00Z")
    insured_policy = fixtures.cancel_account(
        insured, cancel_reason="INSURED_REQUEST",
        cancel_effective_date="2027-01-01T00:00:00Z")

    assert carrier_policy["status"] == "CANCELLED", carrier_policy
    assert insured_policy["status"] == "CANCELLED", insured_policy
    assert carrier_policy["return_premium_cents"] == 1639335, carrier_policy
    assert insured_policy["return_premium_cents"] == 1450402, insured_policy
    # Retaining a tenth of an unrounded pro-rata, or netting the fee first,
    # would miss this difference.
    assert (carrier_policy["return_premium_cents"]
            - insured_policy["return_premium_cents"]) == 188933

    # The written premium falls by exactly what was returned.
    assert carrier_policy["written_premium_cents"] == 1111105, carrier_policy
    assert insured_policy["written_premium_cents"] == 1300038, insured_policy

    for account, returned in ((carrier, 1639335), (insured, 1450402)):
        ledger = fixtures.premium_ledger(account)
        assert len(ledger) == 2, ledger
        for txn in ledger:
            assert_premium_transaction(txn)
        assert ledger[0]["txn_type"] == "INITIAL", ledger
        assert ledger[0]["amount_cents"] == 2750440, ledger
        assert ledger[1]["txn_type"] == "RETURN_PREMIUM", ledger
        assert ledger[1]["amount_cents"] == -returned, ledger
        assert ledger[1]["effective_date"] is not None, ledger


def test_deductible_credit_tier_table_prices_one_schedule_three_ways():
    """The deductible tier sets both the credit factor and the occurrence retention.

    Section 3.4: the deductible credit is "the subtotal multiplied by the tier's
    credit factor and rounded: nothing for STANDARD_25K, six percent for
    ELEVATED_100K and eleven percent for HIGH_250K". One 2596000-cent subtotal
    therefore prices three ways.

    Design: Corner/calculations/corner_deductible_credit_tier_table_prices_one_schedule_three_ways
    """
    expected = {
        "STANDARD_25K": (2500000, 2596000),
        "ELEVATED_100K": (10000000, 2440240),
        "HIGH_250K": (25000000, 2310440),
    }
    priced = {}
    for index, tier in enumerate(("STANDARD_25K", "ELEVATED_100K", "HIGH_250K")):
        account = fixtures.draft_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),),
            with_owner=False,
            project_overrides=_terminal_overrides(
                f"Tier Terminal {tier}", f"{20 + index} Dock Rd",
                "2027-06-01T00:00:00Z"),
            term_start_date="2026-09-01T00:00:00Z",
            term_end_date="2027-06-30T00:00:00Z",
            includes_existing_structure=False,
            deductible_tier=tier,
            limit_cents=2500000000,
            daily_delay_rate_cents=0,
        )
        assert account.policy["occurrence_deductible_cents"] == expected[tier][0], (
            account.policy)
        quoted = validate_success(
            api_client.quote_policy(account.policy_id, fixtures.UW))
        assert quoted["status"] == "QUOTED", quoted
        priced[tier] = quoted["quoted_premium_cents"]

    for tier, (_deductible, premium) in expected.items():
        assert priced[tier] == premium, (tier, priced)
    # The credit is a percentage of the subtotal, not a flat amount per tier,
    # and none of the three is lifted by the minimum premium.
    assert priced["STANDARD_25K"] - priced["ELEVATED_100K"] == 155760, priced
    assert priced["STANDARD_25K"] - priced["HIGH_250K"] == 285560, priced


CEDAR_MILLS_PARTS = (
    ("MATERIALS_ON_SITE", 100000000),
    ("IN_TRANSIT", 20000000),
    ("WATER_DAMAGE", 30000000),
    ("SOFT_COST", 50000000),
)


def test_waterfall_caps_each_line_at_its_sublimit_and_takes_one_deductible():
    """The waterfall sorts, uplifts, retains once, then caps each bucket.

    Section 3.7 applies the occurrence deductible to "the one with the greatest
    covered_basis_cents" among the non-DELAY lines, caps each line at its own
    "sublimit_cents less that part's eroded_cents", and stores the lines "in the
    pinned sequence order" whatever order the request supplied.

    Design: Corner/calculations/corner_waterfall_caps_each_line_at_its_sublimit_and_takes_one_deductible
    """
    account = fixtures.in_force_account(
        parts=CEDAR_MILLS_PARTS,
        project_overrides=_fire_resistive_inland_overrides(
            "Cedar Mills Warehouse", "12 Mill Rd, Cedar", 400000000),
        term_start_date="2026-09-01T00:00:00Z",
        term_end_date="2027-03-20T00:00:00Z",
        includes_existing_structure=False,
        deductible_tier="ELEVATED_100K",
        limit_cents=200000000,
        daily_delay_rate_cents=0,
    )
    assert account.policy["occurrence_deductible_cents"] == 10000000, account.policy

    claim = fixtures.report_claim(
        account, peril="FIRE", loss_date="2026-11-15T00:00:00Z",
        description="Sprinkler head sheared during steel erection")
    adjusted = fixtures.adjust_claim(
        account, claim,
        loss_items=[
            factories.loss_item("SOFT_COST", 5000000),
            factories.loss_item("IN_TRANSIT", 25000000),
            factories.loss_item("MATERIALS_ON_SITE", 40000000),
            factories.loss_item("WATER_DAMAGE", 12000000),
        ],
        adjustment_basis="RECONSTRUCTION_COST", continuing_pm_weeks=4)

    assert adjusted["adjustment_status"] == "ADJUSTED", adjusted
    assert adjusted["indemnity_cents"] == 72091360, adjusted

    lines = adjusted["allocation_lines"]
    assert len(lines) == 4, lines
    assert [line["part_type"] for line in lines] == [
        "MATERIALS_ON_SITE", "IN_TRANSIT", "WATER_DAMAGE", "SOFT_COST"], lines
    assert_allocation_line_order(adjusted)

    materials = allocation_line(adjusted, "MATERIALS_ON_SITE")
    transit = allocation_line(adjusted, "IN_TRANSIT")
    water = allocation_line(adjusted, "WATER_DAMAGE")
    soft = allocation_line(adjusted, "SOFT_COST")

    assert materials["allocated_cents"] == 33200000, materials
    assert transit["allocated_cents"] == 20000000, transit
    assert water["allocated_cents"] == 12960000, water
    assert soft["allocated_cents"] == 5931360, soft

    # One deductible per adjustment, on the greatest non-DELAY line.
    assert materials["deductible_applied_cents"] == 10000000, materials
    for line in (transit, water, soft):
        assert line["deductible_applied_cents"] == 0, line

    # The continuing-PM amount lands on the existing SOFT_COST line.
    assert soft["covered_basis_cents"] == 5931360, soft
    assert soft["gross_loss_cents"] == 5000000, soft

    assert transit["uncovered_cents"] == 7000000, transit
    for line in (materials, water, soft):
        assert line["uncovered_cents"] == 0, line
    assert adjusted["uncovered_cents"] == 17000000, adjusted

    assert adjusted["outstanding_reserve_cents"] == 72091360, adjusted
    assert adjusted["paid_cents"] == 0, adjusted
    assert adjusted["total_incurred_cents"] == 72091360, adjusted
    assert_claim_incurred_identity(adjusted)

    # Allocation is not erosion: nothing has been paid out yet.
    policy = account.refresh_policy()
    assert policy["eroded_total_cents"] == 0, policy
    for part in account.refresh_parts().values():
        assert part["eroded_cents"] == 0, part
        assert part["available_cents"] == part["sublimit_cents"], part
