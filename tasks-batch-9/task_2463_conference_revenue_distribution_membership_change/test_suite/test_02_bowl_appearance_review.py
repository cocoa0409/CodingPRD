"""Postseason appearances: the reimbursement interlock, the revision loop and the unit counters."""

from test_helpers import (
    approve_bowl_appearance,
    assert_fields_equal,
    assert_light_resource,
    assert_reimbursement,
    assert_valuation,
    begin_bowl_review,
    make_compliance_officer_headers,
    make_finance_officer_headers,
    read_conference,
    request_bowl_revision,
    resubmit_bowl_appearance,
    setup_charter_roster,
    submit_bowl_appearance,
    validate_success,
    void_bowl_appearance,
)


def _units_of(api, appearance_id):
    return validate_success(
        api.list_appearance_postseason_units(
            appearance_id, headers=make_compliance_officer_headers()
        )
    )


def test_high_payout_appearance_is_capped_by_the_band_not_by_the_claim(api):
    """PRD §3.6: "First, `allowable_expense_cents` is the smaller of the claimed
    `submitted_expense_cents` and the allowable-expense cap of 8,000,000 cents (80,000
    dollars)."
    PRD §3.6: "Second, `travel_allowance_cents` is the smaller of `travel_miles` multiplied
    by the travel rate of 95 cents per mile and the travel-allowance cap of 2,500,000 cents
    (25,000 dollars)."
    PRD §3.6: "Third, the reimbursement band is selected by the payout alone — `event_tier`
    is descriptive and plays no part in the arithmetic: a `payout_cents` of at least
    10,000,000 cents (100,000 dollars) selects the high-payout band of 6000 basis points,
    and anything below that selects the low-payout band of 8500 basis points."
    PRD §3.6: "Then `reimbursed_cents` is the smaller of the sum of
    `allowable_expense_cents` and `travel_allowance_cents` and that ceiling, and
    `residual_to_pool_cents` is `payout_cents` minus `reimbursed_cents`."

    Design: Difficulty/combinatorial_formula/bowl_reimbursement_nested_caps_and_payout_band
    """
    ctx = setup_charter_roster(api)
    appearance = submit_bowl_appearance(
        api,
        ctx["member_ids"]["north"],
        event_name="Prairie Bowl",
        event_tier="TOURNAMENT",
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=2,
    )
    begin_bowl_review(api, appearance["id"])

    approved = approve_bowl_appearance(api, appearance["id"])

    assert_fields_equal(approved, status="APPROVED", payout_cents=12_000_000)
    assert_reimbursement(
        approved,
        allowable_expense_cents=8_000_000,
        travel_allowance_cents=133_000,
        reimbursement_ceiling_cents=7_200_000,
        reimbursed_cents=7_200_000,
        residual_to_pool_cents=4_800_000,
    )


def test_low_payout_appearance_selects_the_wider_band_on_the_same_claim(api):
    """PRD §3.6: "Third, the reimbursement band is selected by the payout alone — `event_tier`
    is descriptive and plays no part in the arithmetic: a `payout_cents` of at least
    10,000,000 cents (100,000 dollars) selects the high-payout band of 6000 basis points,
    and anything below that selects the low-payout band of 8500 basis points."
    PRD §3.6: "The `reimbursement_ceiling_cents` is `payout_cents` multiplied by the selected
    band and divided by 10000, rounded up to the next whole cent."
    PRD §3.6: "Because the band steps down as the payout rises past the threshold, a larger
    payout can actually lower the reimbursement — a deliberate property of the policy, not
    an artefact."

    Design: Difficulty/combinatorial_formula/bowl_reimbursement_nested_caps_and_payout_band
    """
    ctx = setup_charter_roster(api)
    appearance = submit_bowl_appearance(
        api,
        ctx["member_ids"]["west"],
        event_name="Harvest Bowl",
        event_tier="BOWL",
        payout_cents=6_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=1,
    )
    begin_bowl_review(api, appearance["id"])

    approved = approve_bowl_appearance(api, appearance["id"])

    # Identical claim and mileage as the high-payout case, yet the wider 8500 band applied
    # to the smaller payout yields the lower ceiling that now binds the reimbursement.
    assert_reimbursement(
        approved,
        allowable_expense_cents=8_000_000,
        travel_allowance_cents=133_000,
        reimbursement_ceiling_cents=5_100_000,
        reimbursed_cents=5_100_000,
        residual_to_pool_cents=900_000,
    )


def test_revision_loop_restates_the_figures_the_reimbursement_is_computed_from(api):
    """PRD §3.6: "From there the officer may send it back for correction with an explanatory
    `note`, moving it `UNDER_REVIEW` → `REVISION_REQUESTED` and incrementing its
    `revision_round` by 1."
    PRD §3.6: "The institution then resubmits with restated figures — a new
    `submitted_expense_cents`, new `travel_miles`, and optionally a new `units_claimed` —
    which returns the appearance `REVISION_REQUESTED` → `UNDER_REVIEW`, rewrites those three
    fields with the supplied values, and discards and re-mints the appearance's postseason
    units so that exactly `units_claimed` units exist again, all in `PROVISIONAL`."
    PRD §3.6: "Then `reimbursed_cents` is the smaller of the sum of
    `allowable_expense_cents` and `travel_allowance_cents` and that ceiling, and
    `residual_to_pool_cents` is `payout_cents` minus `reimbursed_cents`."

    Design: Difficulty/non_linear_state_machine/bowl_appearance_revision_loop_changes_reimbursement
    """
    ctx = setup_charter_roster(api)
    member_id = ctx["member_ids"]["west"]
    appearance = submit_bowl_appearance(
        api,
        member_id,
        event_name="Harvest Bowl",
        event_tier="BOWL",
        payout_cents=6_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=1,
    )
    begin_bowl_review(api, appearance["id"])
    request_bowl_revision(api, appearance["id"])

    resubmit_bowl_appearance(
        api,
        appearance["id"],
        member_id,
        submitted_expense_cents=4_200_000,
        travel_miles=900,
    )
    approved = approve_bowl_appearance(api, appearance["id"])

    # The restated claim now sits under the ceiling, so the sum of the two allowances
    # binds instead of the band, and the residual rises accordingly.
    assert_fields_equal(
        approved,
        status="APPROVED",
        revision_round=1,
        submitted_expense_cents=4_200_000,
        travel_miles=900,
    )
    assert_reimbursement(
        approved,
        allowable_expense_cents=4_200_000,
        travel_allowance_cents=85_500,
        reimbursement_ceiling_cents=5_100_000,
        reimbursed_cents=4_285_500,
        residual_to_pool_cents=1_714_500,
    )


def test_resubmission_re_mints_exactly_the_units_the_restated_claim_asks_for(api):
    """PRD §3.6: "The institution then resubmits with restated figures — a new
    `submitted_expense_cents`, new `travel_miles`, and optionally a new `units_claimed` —
    which returns the appearance `REVISION_REQUESTED` → `UNDER_REVIEW`, rewrites those three
    fields with the supplied values, and discards and re-mints the appearance's postseason
    units so that exactly `units_claimed` units exist again, all in `PROVISIONAL`."
    PRD §3.6: "The appearance is created in `SUBMITTED`, and submitting it mints
    `units_claimed` postseason units in status `PROVISIONAL`, each carrying its parent's
    identifier as `bowl_appearance_id`, the credited `member_id`, a `fiscal_year` copied
    from the parent appearance, and a 1-based `unit_index` giving its ordinal within the
    appearance."

    Design: Difficulty/non_linear_state_machine/bowl_appearance_revision_loop_changes_reimbursement
    """
    ctx = setup_charter_roster(api)
    member_id = ctx["member_ids"]["north"]
    appearance = submit_bowl_appearance(
        api,
        member_id,
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=2,
    )
    assert len(_units_of(api, appearance["id"])) == 2
    begin_bowl_review(api, appearance["id"])
    revision_requested = request_bowl_revision(api, appearance["id"])
    assert_fields_equal(
        revision_requested, status="REVISION_REQUESTED", revision_round=1
    )

    resubmitted = resubmit_bowl_appearance(
        api,
        appearance["id"],
        member_id,
        submitted_expense_cents=4_200_000,
        travel_miles=900,
        units_claimed=3,
    )

    assert_fields_equal(resubmitted, status="UNDER_REVIEW", units_claimed=3)
    units = _units_of(api, appearance["id"])
    assert len(units) == 3, "the re-mint leaves exactly units_claimed units"
    for unit in units:
        assert_light_resource(unit)
        assert_fields_equal(
            unit,
            status="PROVISIONAL",
            bowl_appearance_id=appearance["id"],
            member_id=member_id,
            fiscal_year=2027,
        )
    assert sorted(unit["unit_index"] for unit in units) == [1, 2, 3]


def test_approval_validates_the_units_and_advances_the_conference_counters(api):
    """PRD §3.6: "Approving therefore moves the appearance `UNDER_REVIEW` → `APPROVED`,
    writes `allowable_expense_cents`, `travel_allowance_cents`, `reimbursement_ceiling_cents`,
    `reimbursed_cents` and `residual_to_pool_cents`, adds `residual_to_pool_cents` to the
    conference's `escrow_balance_cents`, transitions every postseason unit of the appearance
    `PROVISIONAL` → `VALIDATED`, advances the conference's `validated_postseason_unit_count`
    by `units_claimed`, and increments the conference's `version` by 1."

    Design: Difficulty/transitive_cascade/bowl_approval_cascades_to_conference_unit_counter_depth_three
    """
    ctx = setup_charter_roster(api)
    before = read_conference(api)
    assert_fields_equal(
        before, escrow_balance_cents=0, validated_postseason_unit_count=0
    )
    appearance = submit_bowl_appearance(
        api,
        ctx["member_ids"]["north"],
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=3,
    )
    begin_bowl_review(api, appearance["id"])

    approve_bowl_appearance(api, appearance["id"])

    units = _units_of(api, appearance["id"])
    assert len(units) == 3
    for unit in units:
        assert unit["status"] == "VALIDATED"
    after = read_conference(api)
    assert_fields_equal(
        after,
        escrow_balance_cents=4_800_000,
        validated_postseason_unit_count=3,
        version=before["version"] + 1,
    )


def test_validated_units_flow_through_to_the_member_unit_valuation(api):
    """PRD §3.6: "A validated unit is the only kind that counts toward a unit-based
    allocation or a valuation."
    PRD §3.6: "For a member in `ADMITTED_PHASING`, `FULL_SHARE` or `DEPARTED` the
    `ROLLING_SIX_YEAR` variant applies: the window covers the six fiscal years ending at the
    conference's `current_fiscal_year`, so `window_start_fiscal_year` is
    `current_fiscal_year` minus 5 and `window_end_fiscal_year` is `current_fiscal_year`."
    PRD §3.6: "Within the window, `validated_unit_count` is the number of that member's
    postseason units in status `VALIDATED` whose `fiscal_year` falls inside the window —
    provisional and voided units never count — and `valuation_cents` is that count
    multiplied by the conference's `unit_value_cents`, an exact multiplication with no
    rounding."

    Design: Difficulty/transitive_cascade/bowl_approval_cascades_to_conference_unit_counter_depth_three
    """
    ctx = setup_charter_roster(api)
    member_id = ctx["member_ids"]["north"]
    appearance = submit_bowl_appearance(
        api,
        member_id,
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=3,
    )
    begin_bowl_review(api, appearance["id"])
    provisional_valuation = validate_success(
        api.get_postseason_unit_valuation(
            member_id, headers=make_finance_officer_headers()
        )
    )
    assert_valuation(
        provisional_valuation,
        variant="ROLLING_SIX_YEAR",
        window_start_fiscal_year=2022,
        window_end_fiscal_year=2027,
        validated_unit_count=0,
        valuation_cents=0,
    )

    approve_bowl_appearance(api, appearance["id"])

    valuation = validate_success(
        api.get_postseason_unit_valuation(
            member_id, headers=make_finance_officer_headers()
        )
    )
    assert_valuation(
        valuation,
        variant="ROLLING_SIX_YEAR",
        window_start_fiscal_year=2022,
        window_end_fiscal_year=2027,
        validated_unit_count=3,
        valuation_cents=102_000_000,
    )
    assert valuation["member_id"] == member_id


def test_voiding_an_approved_appearance_restores_both_conference_counters(api):
    """PRD §3.6: "From `APPROVED` it is a true compensation and reverses the approval exactly:
    `residual_to_pool_cents` is subtracted from the conference's `escrow_balance_cents`,
    every unit moves `VALIDATED` → `VOIDED`, `validated_postseason_unit_count` is reduced by
    `units_claimed`, and the conference's `version` advances — leaving both conference
    counters back at their pre-approval values."
    PRD §2.9: "Where a compensation exists, the specification's intent is that the conserved
    quantity is exactly conserved; an implementation that reverses only some of the counters
    is wrong even if no error is raised."

    Design: Difficulty/compensating_invariant/bowl_void_restores_conference_unit_and_escrow_counters
    """
    ctx = setup_charter_roster(api)
    appearance = submit_bowl_appearance(
        api,
        ctx["member_ids"]["north"],
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=2,
    )
    begin_bowl_review(api, appearance["id"])
    approve_bowl_appearance(api, appearance["id"])
    approved_conference = read_conference(api)
    assert_fields_equal(
        approved_conference,
        escrow_balance_cents=4_800_000,
        validated_postseason_unit_count=2,
    )

    voided = void_bowl_appearance(api, appearance["id"])

    assert_fields_equal(
        voided, status="VOIDED", residual_to_pool_cents=4_800_000
    )
    after = read_conference(api)
    assert_fields_equal(
        after,
        escrow_balance_cents=0,
        validated_postseason_unit_count=0,
        version=approved_conference["version"] + 1,
    )


def test_voiding_an_approved_appearance_zeroes_the_member_unit_valuation(api):
    """PRD §3.6: "From `APPROVED` it is a true compensation and reverses the approval exactly:
    `residual_to_pool_cents` is subtracted from the conference's `escrow_balance_cents`,
    every unit moves `VALIDATED` → `VOIDED`, `validated_postseason_unit_count` is reduced by
    `units_claimed`, and the conference's `version` advances — leaving both conference
    counters back at their pre-approval values."
    PRD §3.6: "Within the window, `validated_unit_count` is the number of that member's
    postseason units in status `VALIDATED` whose `fiscal_year` falls inside the window —
    provisional and voided units never count — and `valuation_cents` is that count
    multiplied by the conference's `unit_value_cents`, an exact multiplication with no
    rounding."

    Design: Difficulty/compensating_invariant/bowl_void_restores_conference_unit_and_escrow_counters
    """
    ctx = setup_charter_roster(api)
    member_id = ctx["member_ids"]["north"]
    appearance = submit_bowl_appearance(
        api,
        member_id,
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=2,
    )
    begin_bowl_review(api, appearance["id"])
    approve_bowl_appearance(api, appearance["id"])

    void_bowl_appearance(api, appearance["id"])

    units = _units_of(api, appearance["id"])
    assert len(units) == 2, "voiding does not delete the units it invalidates"
    for unit in units:
        assert unit["status"] == "VOIDED"
    valuation = validate_success(
        api.get_postseason_unit_valuation(
            member_id, headers=make_finance_officer_headers()
        )
    )
    assert_valuation(
        valuation,
        variant="ROLLING_SIX_YEAR",
        window_start_fiscal_year=2022,
        window_end_fiscal_year=2027,
        validated_unit_count=0,
        valuation_cents=0,
    )
