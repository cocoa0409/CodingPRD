"""Twin-ledger variants and the pinned arithmetic of the money formulas.

Every test in this file drives one of the two-variant or multi-tier calculations
through the public endpoints and checks the exact cents the contract works
through, including the wrong answer each pinned evaluation order rules out.
"""

from test_helpers import (
    BASIS_PROVISIONAL,
    BOOKING_HELD,
    BUDGET_LINE_PLANNED,
    CATEGORY_CREW,
    CATEGORY_POST,
    CHANGE_ORDER_PENDING_APPROVAL,
    DECISION_REQUEST_CHANGES,
    ENGAGEMENT_DRAFT,
    NON_UNION,
    TRIGGER_REVISION_ROUND_EXCEEDED,
    UNION,
    UNION_SESSION_REUSE,
    USAGE_BUYOUT,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    assert_booking_components,
    assert_booking_sum,
    assert_budget_line,
    assert_change_order,
    assert_ledgers,
    assert_talent_comp,
    assert_variance_is_zero_while_unapproved,
    book_crew,
    cast_talent,
    expected_booking_components,
    expected_buyout_comp,
    expected_change_order,
    expected_extended_cents,
    expected_union_comp,
    latest_change_order,
    lock_scope,
    open_project,
    read_project,
    register_location,
    schedule_shoot_day,
    submitted_cut,
    review_cut,
)


def _two_channel_project(api):
    """A DRAFT project licensed for two channels over a 24-month term."""
    return open_project(
        api,
        client_name="Northwind Bank",
        campaign_title="Trust Anthem 2027",
        creative_brief_summary="Sixty-second brand film with OLV and social cutdowns.",
        channel_scope=["OLV", "SOCIAL"],
        usage_term_months=24,
        budget_ceiling_cents=50000000,
        contracted_revision_rounds=2,
    )


def test_provisional_counts_the_planned_line_and_draft_memo_the_committed_ignores_both(api):
    """One unchanged set of rows read by the two ledger filters differs by 3,381,125 cents.

    PRD §2.7: "`provisional_cost_cents` is the forward-looking estimate. It is the
    sum of five contributions: every budget line of the project whose `status` is
    `PLANNED` or `COMMITTED`, contributing its `extended_cents`; every talent
    engagement of the project whose `status` is `DRAFT`, `CONFIRMED` or
    `COMPLETED`, contributing its `total_comp_cents`; every crew booking on any
    shoot day of the project whose `status` is `HELD`, `CONFIRMED` or `COMPLETED`,
    contributing its `cost_cents`; every equipment reservation on any shoot day of
    the project whose `status` is `RESERVED` or `RETURNED`, contributing its
    `total_cost_cents`; and every change order on any deliverable of the project
    whose `status` is `PENDING_APPROVAL` or `APPROVED`, contributing its
    `amount_cents`."

    PRD §2.7: "Because those four families exclude the not-yet-committed statuses —
    `PLANNED` lines, `DRAFT` engagements, `HELD` bookings and `PENDING_APPROVAL`
    change orders — the committed figure is strictly smaller than the provisional
    figure whenever any such row exists, and equal to it when none does."

    Design: Difficulty/dual_variant_calc/project_ledger_provisional_versus_committed_on_same_rows
    """
    project = _two_channel_project(api)
    line = add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Offline and online edit",
        quantity=2,
        unit_rate_cents=1000000,
        markup_pct=0.1,
    )
    engagement = cast_talent(
        api,
        project["id"],
        talent_name="Dana Reyes",
        union_affiliation=NON_UNION,
        compensation_model=USAGE_BUYOUT,
        session_fee_cents=250000,
        session_days=2,
    )

    assert_budget_line(line, extended_cents=2200000, status=BUDGET_LINE_PLANNED)
    assert_talent_comp(
        engagement,
        total_comp_cents=1181125,
        status=ENGAGEMENT_DRAFT,
        comp_basis=BASIS_PROVISIONAL,
    )

    read = read_project(api, project["id"])
    assert_ledgers(read, provisional_cents=3381125, committed_cents=0)
    assert read["provisional_cost_cents"] - read["committed_cost_cents"] == 3381125
    assert read["committed_cost_cents"] < read["provisional_cost_cents"]


def test_variance_reads_zero_while_the_provisional_figure_stands_at_3381125(api):
    """The same two rows leave variance at 0 because no budget has been approved.

    PRD §2.7: "`budget_variance_cents` is `provisional_cost_cents` minus
    `approved_budget_cents`, and is reported as 0 for as long as
    `approved_budget_cents` is null."

    PRD §2.7: "Three exclusions are absolute and prevent double counting. A shoot
    day's `day_cost_cents` never enters either figure: it is a display-only day
    total, and a location's daily fee reaches the project ledger only through a
    budget line of category `LOCATION`."

    Design: Difficulty/dual_variant_calc/project_ledger_provisional_versus_committed_on_same_rows
    """
    project = _two_channel_project(api)
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Offline and online edit",
        quantity=2,
        unit_rate_cents=1000000,
        markup_pct=0.1,
    )
    cast_talent(
        api,
        project["id"],
        talent_name="Dana Reyes",
        union_affiliation=NON_UNION,
        compensation_model=USAGE_BUYOUT,
        session_fee_cents=250000,
        session_days=2,
    )

    read = read_project(api, project["id"])
    assert read["provisional_cost_cents"] == 3381125
    assert_variance_is_zero_while_unapproved(read)


def test_identical_session_inputs_price_1181125_on_buyout_and_2238188_on_union(api):
    """The same 250,000-cent day rate over two days diverges by 1,057,063 cents.

    PRD §3.3: "`usage_load_cents` is then the base fee multiplied by the channel
    multiplier and by the term multiplier, rounded half up to whole cents.
    `reuse_cycles`, `reuse_fee_cents` and `pension_health_cents` are all 0 for a
    buyout. The agent's commission, `agent_fee_cents`, is ten percent of the sum of
    the base fee and the rounded usage load, itself rounded half up.
    `total_comp_cents` is the base fee plus the rounded usage load plus the rounded
    agent fee."

    PRD §3.3: "The first cycle is covered by the session fee itself, so
    `reuse_fee_cents` is thirty-five percent of the base fee multiplied by the
    number of cycles beyond the first — using zero whenever the cycle count is one
    or fewer — rounded half up. `pension_health_cents`, the union pension and health
    contribution, is 19.75 percent of the sum of the base fee and the rounded reuse
    fee, rounded half up."

    Design: Difficulty/dual_variant_calc/talent_comp_buyout_versus_union_on_identical_session_inputs
    """
    project = _two_channel_project(api)
    buyout = cast_talent(
        api,
        project["id"],
        talent_name="Dana Reyes",
        union_affiliation=NON_UNION,
        compensation_model=USAGE_BUYOUT,
        session_fee_cents=250000,
        session_days=2,
    )
    union = cast_talent(
        api,
        project["id"],
        talent_name="Marc Ilesanmi",
        union_affiliation=UNION,
        compensation_model=UNION_SESSION_REUSE,
        session_fee_cents=250000,
        session_days=2,
    )

    assert_talent_comp(
        buyout,
        base_fee_cents=500000,
        usage_load_cents=573750,
        agent_fee_cents=107375,
        total_comp_cents=1181125,
    )
    assert buyout["reuse_cycles"] == 0
    assert buyout["reuse_fee_cents"] == 0
    assert buyout["pension_health_cents"] == 0

    assert_talent_comp(
        union,
        base_fee_cents=500000,
        usage_load_cents=0,
        reuse_fee_cents=1225000,
        pension_health_cents=340688,
        agent_fee_cents=172500,
        total_comp_cents=2238188,
    )
    assert union["reuse_cycles"] == 8
    assert union["total_comp_cents"] - buyout["total_comp_cents"] == 1057063


def test_the_two_component_sets_are_what_the_declared_formulas_produce(api):
    """Both engagements match the formulas component by component, and roll up to 3,419,313.

    PRD §2.6: "**Talent compensation rounds per component, then sums.** Each money
    component of an engagement is rounded to whole cents on its own, and the
    components are then added; the resulting total is never re-rounded."

    PRD §3.3: "Reuse is metered in thirteen-week cycles: `reuse_cycles` is the term
    in months multiplied by 30 days per month, divided by 91 days per cycle, rounded
    up to a whole cycle."

    Design: Difficulty/dual_variant_calc/talent_comp_buyout_versus_union_on_identical_session_inputs
    """
    project = _two_channel_project(api)
    buyout = cast_talent(
        api,
        project["id"],
        talent_name="Dana Reyes",
        union_affiliation=NON_UNION,
        compensation_model=USAGE_BUYOUT,
        session_fee_cents=250000,
        session_days=2,
    )
    union = cast_talent(
        api,
        project["id"],
        talent_name="Marc Ilesanmi",
        union_affiliation=UNION,
        compensation_model=UNION_SESSION_REUSE,
        session_fee_cents=250000,
        session_days=2,
    )

    expected_buyout = expected_buyout_comp(
        session_fee_cents=250000, session_days=2, channel_count=2, term_months=24
    )
    for field, value in expected_buyout.items():
        assert buyout[field] == value, f"{field}: {buyout[field]} != {value}"

    expected_union = expected_union_comp(session_fee_cents=250000, session_days=2, term_months=24)
    for field, value in expected_union.items():
        assert union[field] == value, f"{field}: {union[field]} != {value}"

    read = read_project(api, project["id"])
    assert_ledgers(read, provisional_cents=3419313, committed_cents=0)


def _thirteen_and_a_half_hour_booking(api):
    """A scope-locked project, a two-stage venue, a long day and one 5,000-cent grip."""
    project = open_project(
        api,
        client_name="Meridian Foods",
        campaign_title="Harvest Table",
        creative_brief_summary="Broadcast brand film shot over one stage day.",
        channel_scope=["BROADCAST"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Hero 60",
        channel="BROADCAST",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="CLOSED_SRT",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_CREW,
        description="Camera department day rate pool",
        quantity=1,
        unit_rate_cents=100000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    location = register_location(
        api,
        name="Pier 9 Stage",
        address="9 Harbor Way, Oakland",
        stage_count=2,
        daily_fee_cents=400000,
        insurance_minimum_cents=100000000,
        permit_authority="City Film Office",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T19:30:00Z",
    )
    member = add_crew_member(
        api, full_name="Ivo Marek", department="CAMERA", hourly_rate_cents=5000, min_turnaround_hours=10
    )
    booking = book_crew(
        api,
        day["id"],
        member["id"],
        department_role="1st AC",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T19:30:00Z",
    )
    return project, booking


def test_a_thirteen_and_a_half_hour_booking_splits_across_all_three_rate_tiers(api):
    """13.5 hours at 5,000 cents an hour is 50,000 plus 15,000 plus 15,000.

    PRD §3.6: "Three components are then formed against the roster entry's
    `hourly_rate_cents`: `straight_time_cents` is the lesser of the scheduled hours
    and 10 hours, multiplied by the rate; `overtime_tier1_cents` covers the hours
    from the tenth to the twelfth — the lesser of two hours and however much of the
    span exceeds 10 hours, never below zero — multiplied by the rate and by 1.5; and
    `overtime_tier2_cents` covers everything beyond the twelfth hour — the span minus
    12 hours, never below zero — multiplied by the rate and by 2.0."

    Design: Difficulty/combinatorial_formula/crew_overtime_nested_min_max_across_three_tiers
    """
    _project, booking = _thirteen_and_a_half_hour_booking(api)

    assert_booking_components(
        booking,
        scheduled_hours=13.5,
        straight_time_cents=50000,
        overtime_tier1_cents=15000,
        overtime_tier2_cents=15000,
        cost_cents=80000,
        status=BOOKING_HELD,
    )
    # Dropping the inner min on the first tier would bill 3.5 hours at 1.5 and land
    # on 26,250 cents for that tier instead of 15,000.
    assert booking["overtime_tier1_cents"] != 26250


def test_the_booking_total_is_summed_before_it_is_rounded_and_lands_only_on_provisional(api):
    """The three components are added first, and a HELD booking commits nothing.

    PRD §2.6: "**Crew bookings sum first, then round once.** Deliberately the
    opposite order: a booking's straight-time, first-tier overtime and second-tier
    overtime components are computed as exact values, added together, and the single
    total is rounded half up exactly once."

    PRD §3.6: "A new booking is written at `status` `HELD`, which puts its cost
    inside the provisional figure but not the committed one, and refreshes the day's
    `day_cost_cents`."

    Design: Difficulty/combinatorial_formula/crew_overtime_nested_min_max_across_three_tiers
    """
    project, booking = _thirteen_and_a_half_hour_booking(api)

    expected = expected_booking_components(scheduled_hours=13.5, hourly_rate_cents=5000)
    assert_booking_components(
        booking,
        straight_time_cents=expected["straight_time_cents"],
        overtime_tier1_cents=expected["overtime_tier1_cents"],
        overtime_tier2_cents=expected["overtime_tier2_cents"],
        cost_cents=expected["cost_cents"],
    )
    assert_booking_sum(booking)

    read = read_project(api, project["id"])
    assert_ledgers(read, provisional_cents=180000, committed_cents=0)


def _three_marked_up_post_lines(api):
    """Three identical post lines of raw 22,220 cents at a markup of 0.075."""
    project = open_project(
        api,
        client_name="Halden Pharma",
        campaign_title="Clinic Voices",
        creative_brief_summary="Internal brand film series with matching social cutdowns.",
        channel_scope=["INTERNAL"],
        usage_term_months=12,
        budget_ceiling_cents=10000000,
    )
    lines = [
        add_budget_line(
            api,
            project["id"],
            category=CATEGORY_POST,
            description=description,
            quantity=2,
            unit_rate_cents=11110,
            markup_pct=0.075,
        )
        for description in (
            "Colour grade suite hours",
            "Sound mix suite hours",
            "Conform and deliverables hours",
        )
    ]
    return project, lines


def test_each_line_rounds_its_own_markup_and_the_roll_up_reaches_71661(api):
    """Three lines of 23,887 cents roll up to 71,661, not to 71,660.

    PRD §2.6: "**Budget lines round per line, then sum.** A line's markup is rounded
    to whole cents on that line, the rounded markup is added to that line's exact raw
    amount, and only then are the line totals added together for a project roll-up.
    Summing raw amounts across lines and applying the markup percentage to the sum is
    forbidden: three lines whose raw amounts are each 22,220 cents at a markup of
    0.075 produce 1,667 cents of markup each and therefore 23,887 cents per line and
    71,661 cents for the roll-up, whereas summing raw first (66,660 cents) and
    rounding a single markup of 4,999.5 cents to 5,000 would produce 71,660 cents —
    one cent short of the sanctioned answer."

    Design: Difficulty/combinatorial_formula/budget_markup_rounds_per_line_before_summing
    """
    project, lines = _three_marked_up_post_lines(api)

    for line in lines:
        assert_budget_line(line, extended_cents=23887)

    read = read_project(api, project["id"])
    assert read["provisional_cost_cents"] == 71661
    assert read["provisional_cost_cents"] != 71660


def test_the_line_total_is_the_exact_raw_amount_plus_the_rounded_markup(api):
    """23,887 is 22,220 exact plus 1,667 rounded, per line.

    PRD §3.2: "The line's total, `extended_cents`, is derived in a fixed order. First
    the raw amount is the `quantity` multiplied by the `unit_rate_cents`, kept exact
    with no rounding. Then the markup amount is that raw amount multiplied by
    `markup_pct` and rounded half up to whole cents. Finally `extended_cents` is the
    exact raw amount plus the rounded markup amount."

    PRD §2.6: "Because every addend of a project-level roll-up is already a
    whole-cent integer, no rounding occurs at roll-up time, and both roll-ups are
    order-independent — no tie-break rule is needed."

    Design: Difficulty/combinatorial_formula/budget_markup_rounds_per_line_before_summing
    """
    project, lines = _three_marked_up_post_lines(api)

    for line in lines:
        assert line["extended_cents"] == expected_extended_cents(2, 11110, 0.075)
        assert line["extended_cents"] == 22220 + 1667

    read = read_project(api, project["id"])
    assert read["provisional_cost_cents"] == sum(line["extended_cents"] for line in lines)


def _extra_round_change_order(api):
    """One contracted round, spent by a request for changes, priced with no rush."""
    project = open_project(
        api,
        client_name="Aster Mobility",
        campaign_title="City Loop",
        creative_brief_summary="Single OLV brand film with one contracted revision round.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
        contracted_revision_rounds=1,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title="City Loop 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Post production package",
        quantity=2,
        unit_rate_cents=1000000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    cut = submitted_cut(api, deliverable["id"], cut_label="v1 rough", file_size_gb=12.5)
    review_cut(
        api,
        cut["id"],
        DECISION_REQUEST_CHANGES,
        review_note="Tighten the open and lose the third beat.",
    )
    return project, deliverable


def test_the_producer_fee_tier_is_chosen_by_the_480000_subtotal_and_bills_566400(api):
    """A 480,000-cent subtotal sits below 500,000, so the fee is 18 percent.

    PRD §3.9: "The producer's fee tier is keyed on `subtotal_cents` — the pre-fee
    figure — and never on the invoiced total, even though the invoiced total is what
    the client pays. `producer_fee_pct` is 0.12 when `subtotal_cents` is at least
    1,000,000 cents, 0.15 when it is at least 500,000 but below 1,000,000, and 0.18
    below 500,000."

    PRD §3.9: "`labor_cents`, the post-production labour component, is 480,000 cents
    (4,800.00 in currency units) for every round granted when the trigger is
    `REVISION_ROUND_EXCEEDED` — so 480,000 cents for the single round such an order
    grants — and a flat 620,000 cents when the trigger is
    `DELIVERABLE_ADDED_AFTER_SCOPE_LOCK`, where no rounds are granted at all."

    Design: Difficulty/combinatorial_formula/change_order_producer_fee_tier_keyed_on_subtotal_not_amount
    """
    _project, deliverable = _extra_round_change_order(api)

    change_order = latest_change_order(api, deliverable["id"])
    assert_change_order(
        change_order,
        trigger_reason=TRIGGER_REVISION_ROUND_EXCEEDED,
        labor_cents=480000,
        rush_pct=0.00,
        rush_cents=0,
        subtotal_cents=480000,
        producer_fee_pct=0.18,
        producer_fee_cents=86400,
        amount_cents=566400,
        status=CHANGE_ORDER_PENDING_APPROVAL,
    )
    assert change_order["additional_rounds_granted"] == 1


def test_keying_the_tier_on_the_invoiced_total_would_have_billed_552000_instead(api):
    """The 566,400-cent total would have selected 15 percent, and does not.

    PRD §3.9: "Consider an extra-round order with no rush: labour of 480,000 cents
    and a rush percentage of 0.00 give a subtotal of 480,000 cents, which sits in the
    below-500,000 band and therefore attracts 18 percent, a producer fee of 86,400
    cents and an amount of 566,400 cents. Keying the tier on the 566,400-cent total
    instead would have selected the at-least-500,000 band, produced a fee of 72,000
    cents and an amount of 552,000 cents — a 14,400-cent divergence on identical
    inputs, which is exactly why the order of evaluation is fixed."

    Design: Difficulty/combinatorial_formula/change_order_producer_fee_tier_keyed_on_subtotal_not_amount
    """
    _project, deliverable = _extra_round_change_order(api)

    change_order = latest_change_order(api, deliverable["id"])
    expected = expected_change_order(TRIGGER_REVISION_ROUND_EXCEEDED, days_to_air=122)
    assert change_order["amount_cents"] == expected["amount_cents"] == 566400
    assert change_order["amount_cents"] != 552000
    assert change_order["producer_fee_cents"] != 72000
    # The invoiced total is above the 500,000 threshold and the chosen tier is still
    # the below-500,000 one, which is only possible if the subtotal keyed it.
    assert change_order["amount_cents"] > 500000
    assert change_order["producer_fee_pct"] == 0.18
