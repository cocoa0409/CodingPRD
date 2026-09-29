"""Weight-out settlement pricing: gain, base charge and the money waterfall."""

import pytest

from test_helpers import (
    BIG_COULEE,
    BIG_COULEE_HEAD_DAY_TERMS,
    DM_1300_AT_20,
    DM_1700_AT_25,
    DM_2000_AT_30,
    RIMROCK,
    RIMROCK_GAIN_TERMS,
    SAGE_FLAT,
    SAGE_FLAT_GAIN_TERMS,
    ApiErrorId,
    assert_settlement,
    assert_settlement_waterfall,
    draft_settlement,
    file_drought_reading,
    make_cattle_owner_headers,
    make_grazier_headers,
    make_range_consultant_headers,
    read_contract,
    read_lot,
    record_treatment,
    review_treatment_as_owner,
    set_logical_clock,
    settlement_payload,
    setup_full_north_bench_settlement,
    setup_gain_billed_lot,
    setup_north_bench_lot_on_feed,
    setup_school_section_lot_on_feed,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_out_lot,
)

TREATMENT_A = {
    "protocol_code": "BRD-A", "classification": "ROUTINE_PROTOCOL",
    "treatment_date": "2026-08-20", "withdrawal_days": 21, "head_treated": 12,
    "drug_cost_cents": 1250, "labor_cost_cents": 375,
}


# ===========================================================================
# The two gain books
# ===========================================================================

def test_the_provisional_method_values_missing_head_at_the_average_in_weight(api):
    """PRD 3.9: "Under `PROVISIONAL_PRORATED` — the method every draft starts with — the
    grazier's view prevails: the lot's shrunk in-weight is divided by the head received
    to get an average in-weight per head, that unrounded average is multiplied by the
    head that actually walked off, and the product is rounded half up to a whole pound
    and stored as `adjusted_in_weight_lbs`. `shrunk_gain_lbs` is then the lot's shrunk
    out-weight less that adjusted in-weight."
    PRD 3.9: "The methods disagree materially on identical scale tickets: 61514 pounds
    shrunk in on 150 head received with 146 head out at 74970 pounds shrunk out gives an
    adjusted in-weight of 59874 and a gain of 15096 pounds under the provisional method,
    but 59460 and 15510 pounds under the adjudicated one — 414 pounds of gain hanging on
    nothing but which book you keep."

    Design: Difficulty/dual_variant_calc/settlement_gain_provisional_prorated_vs_final_adjudicated
    """
    world = setup_full_north_bench_settlement()
    settlement = world.settlement
    assert_settlement(settlement)

    assert settlement["gain_method"] == "PROVISIONAL_PRORATED"
    assert settlement["adjusted_in_weight_lbs"] == 59874
    assert settlement["shrunk_gain_lbs"] == 15096
    assert settlement["base_charge_cents"] == 1283160
    assert settlement["treatment_charge_cents"] == 7627
    assert settlement["infrastructure_charge_cents"] == 90000
    assert settlement["death_loss_credit_cents"] == 84000
    assert settlement["subtotal_cents"] == 1296787
    assert settlement["volume_rebate_cents"] == 12968
    assert settlement["total_due_cents"] == 1283819


def test_an_upheld_owner_ruling_reprices_the_gain_at_the_average_out_weight(api):
    """PRD 3.9: "Under `FINAL_ADJUDICATED` the owner's view prevails: the missing head
    are deducted at the lot's *average out-weight* instead, so `adjusted_in_weight_lbs`
    is the shrunk in-weight less the product of the average out-weight per head and the
    number of head that went missing (head received less head out), rounded half up to a
    whole pound, and `shrunk_gain_lbs` is again the shrunk out-weight less that figure."
    PRD 3.9: "The resolution maps directly onto the gain method: `UPHELD_GRAZIER` sets
    `gain_method` to `PROVISIONAL_PRORATED`, `UPHELD_OWNER` sets it to
    `FINAL_ADJUDICATED`, and `SPLIT_MIDPOINT` sets it to `SPLIT_MIDPOINT`."

    Design: Difficulty/dual_variant_calc/settlement_gain_provisional_prorated_vs_final_adjudicated
    """
    world = setup_full_north_bench_settlement(dispute=True, claimed_shrunk_gain_lbs=15400)

    resp = api.adjudicate_settlement(
        world.settlement_id,
        {"resolution": "UPHELD_OWNER",
         "note": "Owner's out-weight proration is the correct read of the contract"},
        make_range_consultant_headers(world.consultant2_id),
    )
    ruled = validate_success(resp, 200)

    assert ruled["gain_method"] == "FINAL_ADJUDICATED"
    assert ruled["adjusted_in_weight_lbs"] == 59460
    assert ruled["shrunk_gain_lbs"] == 15510
    assert ruled["average_daily_gain"] == pytest.approx(1.1547, abs=0.00005)
    assert ruled["base_charge_cents"] == 1318350
    assert ruled["treatment_charge_cents"] == 7627
    assert ruled["infrastructure_charge_cents"] == 90000
    assert ruled["death_loss_credit_cents"] == 84000
    assert ruled["subtotal_cents"] == 1331977
    assert ruled["volume_rebate_cents"] == 13320
    assert ruled["total_due_cents"] == 1318657
    assert ruled["adjudicator_id"] == world.consultant2_id
    assert ruled["status"] == "ADJUDICATED"


# ===========================================================================
# Base charge: the ADG tier boundary and the gain cap
# ===========================================================================

def test_an_average_daily_gain_of_exactly_one_and_a_half_selects_the_middle_tier(api):
    """PRD 3.9: "Performance earns a premium: an `average_daily_gain` below 1.50 pounds
    carries a multiplier of 1.00, a gain of at least 1.50 but below 2.25 carries 1.10,
    and a gain of 2.25 or more carries 1.20, with the tier selected from the
    four-decimal figure."
    PRD 3.9: "`average_daily_gain` follows from whichever gain figure is in force: the
    gain divided by the product of the head out and the lot's `days_on_feed`, rounded
    half up to four decimal places."

    Design: Difficulty/combinatorial_formula/base_charge_adg_tier_selection_and_gain_cap_mode_a
    """
    world = setup_gain_billed_lot(
        SAGE_FLAT, DM_1700_AT_25, SAGE_FLAT_GAIN_TERMS,
        lot_head=100, gross_in_lbs=50000, gross_out_lbs=65000,
        out_weighed_at="2026-11-18T09:00:00Z", clock="2026-11-20T00:00:00Z",
    )
    assert read_lot(world.lot_id, world.grazier_id)["days_on_feed"] == 100

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["adjusted_in_weight_lbs"] == 50000
    assert settlement["shrunk_gain_lbs"] == 15000
    assert settlement["average_daily_gain"] == pytest.approx(1.5000, abs=0.00005)
    assert settlement["billable_head_days"] == 0, (
        "Head-days are not billed under PER_POUND_OF_GAIN"
    )
    assert settlement["base_charge_cents"] == 1485000, (
        "15000 lb at 90 cents times the 1.10 multiplier"
    )


def test_the_gain_billed_settlement_carries_its_rebate_through_to_the_total(api):
    """PRD 3.9: "The gain that may be billed is capped at 250 pounds per contracted head
    — the smaller of `shrunk_gain_lbs` and the committed head multiplied by 250 — and
    `base_charge_cents` is that capped gain multiplied by the `rate_cents` and by the
    tier multiplier, rounded half up to a whole cent."
    PRD 3.9: "A base below 500000 cents earns no rebate; a base from 500000 up to but
    not including 1500000 earns 1.0 percent; a base of 1500000 or more earns 2.0
    percent."

    Design: Difficulty/combinatorial_formula/base_charge_adg_tier_selection_and_gain_cap_mode_a
    """
    world = setup_gain_billed_lot(
        SAGE_FLAT, DM_1700_AT_25, SAGE_FLAT_GAIN_TERMS,
        lot_head=100, gross_in_lbs=50000, gross_out_lbs=65000,
        out_weighed_at="2026-11-18T09:00:00Z", clock="2026-11-20T00:00:00Z",
    )

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["shrunk_gain_lbs"] == 15000, (
        "15000 lb is under the 25000 lb cap for 100 contracted head"
    )
    assert settlement["subtotal_cents"] == 1485000
    assert settlement["volume_rebate_cents"] == 14850
    assert settlement["total_due_cents"] == 1470150
    assert_settlement_waterfall(settlement)


def test_the_gain_cap_and_the_top_tier_apply_together(api):
    """PRD 3.9: "The gain that may be billed is capped at 250 pounds per contracted head
    — the smaller of `shrunk_gain_lbs` and the committed head multiplied by 250 — and
    `base_charge_cents` is that capped gain multiplied by the `rate_cents` and by the
    tier multiplier, rounded half up to a whole cent."
    PRD 3.9: "Performance earns a premium: an `average_daily_gain` below 1.50 pounds
    carries a multiplier of 1.00, a gain of at least 1.50 but below 2.25 carries 1.10,
    and a gain of 2.25 or more carries 1.20, with the tier selected from the
    four-decimal figure."

    Design: Corner/calculations/gain_cap_and_top_adg_tier_apply_together
    """
    world = setup_gain_billed_lot(
        RIMROCK, DM_1300_AT_20, RIMROCK_GAIN_TERMS,
        lot_head=10, gross_in_lbs=5000, gross_out_lbs=8000,
        out_weighed_at="2026-11-10T09:00:00Z", clock="2026-11-12T00:00:00Z",
    )

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["shrunk_gain_lbs"] == 3000
    assert settlement["average_daily_gain"] == pytest.approx(3.2609, abs=0.00005)
    assert settlement["base_charge_cents"] == 270000, (
        "The 2500 lb cap clips the 3000 lb of gain before the 1.20 multiplier"
    )
    assert settlement["subtotal_cents"] == 270000
    assert settlement["volume_rebate_cents"] == 0
    assert settlement["total_due_cents"] == 270000


# ===========================================================================
# Head-day billing: the minimum-days floor and the death deduction
# ===========================================================================

def test_the_minimum_days_floor_binds_when_actual_head_days_fall_short(api):
    """PRD 3.9: "Against that raw figure stands the floor the owner guaranteed: the
    contract's `head_count_committed` multiplied by its `min_days`, computed from the
    *contracted* head and never from the head actually received. `billable_head_days` is
    whichever of the two is larger, and `base_charge_cents` is that figure multiplied by
    the contract's `rate_cents`, rounded half up to a whole cent."

    Design: Corner/calculations/min_days_floor_binds_when_actual_head_days_fall_short
    """
    world = setup_school_section_lot_on_feed(death_loss=True)
    weigh_out_lot(
        world.lot_id, world.grazier_id,
        gross_weight_lbs=20000, head_count=38,
        scale_ticket_ref="T4-OUT", weighed_at="2026-09-19T09:00:00Z",
    )
    set_logical_clock("2026-09-21T00:00:00Z")

    lot = read_lot(world.lot_id, world.grazier_id)
    assert lot["shrunk_weight_in_lbs"] == 21340
    assert lot["days_on_feed"] == 40

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["billable_head_days"] == 2400, "40 contracted head times 60 min days"
    assert settlement["base_charge_cents"] == 228000
    assert settlement["death_loss_credit_cents"] == 0
    assert settlement["subtotal_cents"] == 228000
    assert settlement["volume_rebate_cents"] == 0
    assert settlement["total_due_cents"] == 228000


def test_confirmed_deaths_stop_accruing_head_days_on_their_death_date(api):
    """PRD 3.9: "Under `PER_HEAD_PER_DAY`, the raw head-days are the head received
    multiplied by the days on feed, less a deduction for cattle that died partway
    through: for each `CONFIRMED` death-loss report on the lot, the head lost multiplied
    by the whole days from that report's `death_date` to the lot's `out_date` — dead head
    stop accruing on the day they died."
    PRD 3.9: "Reports that are `REPORTED`, `REJECTED` or `VOIDED` never reduce
    head-days."

    Design: Corner/calculations/head_days_stop_accruing_on_each_confirmed_death_date
    """
    world = setup_school_section_lot_on_feed(death_loss=True)
    weigh_out_lot(
        world.lot_id, world.grazier_id,
        gross_weight_lbs=26600, head_count=38,
        scale_ticket_ref="T4-OUT", weighed_at="2026-10-19T09:00:00Z",
    )
    set_logical_clock("2026-10-21T00:00:00Z")
    assert read_lot(world.lot_id, world.grazier_id)["days_on_feed"] == 70

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["billable_head_days"] == 2720, (
        "40 head over 70 days less 2 head over the 40 days after they died"
    )
    assert settlement["base_charge_cents"] == 258400
    assert settlement["total_due_cents"] == 258400


# ===========================================================================
# The volume rebate is keyed on the pre-rebate base
# ===========================================================================

def test_head_day_billing_builds_the_pre_rebate_base(api):
    """PRD 3.4: "The shrunk figure is computed once, at the lot level: the ticket's gross
    weight is multiplied by one minus the applicable shrink percentage divided by 100,
    and that single product is rounded half up to a whole pound and stored as
    `shrunk_weight_lbs`."
    PRD 3.9: "Against that raw figure stands the floor the owner guaranteed: the
    contract's `head_count_committed` multiplied by its `min_days`, computed from the
    *contracted* head and never from the head actually received. `billable_head_days` is
    whichever of the two is larger, and `base_charge_cents` is that figure multiplied by
    the contract's `rate_cents`, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/volume_rebate_keyed_on_pre_rebate_base_mode_c
    """
    world = setup_gain_billed_lot(
        BIG_COULEE, DM_2000_AT_30, BIG_COULEE_HEAD_DAY_TERMS,
        lot_head=200, gross_in_lbs=108000, gross_out_lbs=132500,
        out_weighed_at="2026-11-10T09:00:00Z", clock="2026-11-12T00:00:00Z",
    )

    lot = read_lot(world.lot_id, world.grazier_id)
    assert lot["shrunk_weight_in_lbs"] == 103680
    assert lot["days_on_feed"] == 92

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)
    assert settlement["billable_head_days"] == 18400
    assert settlement["base_charge_cents"] == 1508800
    assert settlement["subtotal_cents"] == 1508800
    assert settlement["early_removal_adjustment_cents"] == 0


def test_the_rebate_tier_is_chosen_from_the_pre_rebate_base_not_the_amount_due(api):
    """PRD 3.9: "The volume rebate is the step most easily got wrong. Its tier is chosen
    from the **pre-rebate** base — the subtotal plus the early-removal adjustment — and
    never from the final amount due."
    PRD 3.9: "A worked case makes the trap concrete: a pre-rebate base of 1508800 cents
    sits in the 2.0 percent tier, so the rebate is 30176 cents and the amount due is
    1478624 cents — even though 1478624 by itself would have fallen in the 1.0 percent
    tier. Keying the tier on the final amount, and paying 15088 cents, is wrong."

    Design: Difficulty/combinatorial_formula/volume_rebate_keyed_on_pre_rebate_base_mode_c
    """
    world = setup_gain_billed_lot(
        BIG_COULEE, DM_2000_AT_30, BIG_COULEE_HEAD_DAY_TERMS,
        lot_head=200, gross_in_lbs=108000, gross_out_lbs=132500,
        out_weighed_at="2026-11-10T09:00:00Z", clock="2026-11-12T00:00:00Z",
    )

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["volume_rebate_cents"] == 30176, (
        "Keying the tier on total_due_cents would have produced 15088"
    )
    assert settlement["total_due_cents"] == 1478624
    assert_settlement_waterfall(settlement)


# ===========================================================================
# The signed early-removal adjustment
# ===========================================================================

def test_a_drought_removal_waives_five_percent_of_the_subtotal(api):
    """PRD 3.9: "A `DROUGHT` removal waives 5 percent of the subtotal, entered as a
    negative adjustment; an `OWNER_ELECTED` removal adds an 8 percent penalty as a
    positive adjustment; a `GRAZIER_ELECTED` removal gives the owner a 10 percent credit
    as a negative adjustment; and when no early removal happened the adjustment is 0."
    PRD 3.9: "Each percentage is taken of the subtotal and rounded half up to a whole
    cent before its sign is applied."

    Design: Corner/calculations/drought_early_removal_credits_five_percent_of_the_subtotal
    """
    world = setup_north_bench_lot_on_feed()
    file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-01", drought_index=3, forage_remaining_pct=45,
    )
    file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-15", drought_index=3, forage_remaining_pct=38,
    )
    weigh_out_lot(
        world.lot_id, world.grazier_id,
        gross_weight_lbs=66000, head_count=150,
        scale_ticket_ref="T-DRY", weighed_at="2026-09-30T09:00:00Z",
    )
    set_logical_clock("2026-10-02T00:00:00Z")

    assert read_contract(world.contract_id, world.grazier_id)["early_removal_reason"] == "DROUGHT"
    assert read_lot(world.lot_id, world.grazier_id)["days_on_feed"] == 51

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["shrunk_gain_lbs"] == 4486
    assert settlement["base_charge_cents"] == 381310
    assert settlement["subtotal_cents"] == 381310
    assert settlement["early_removal_adjustment_cents"] == -19066
    assert settlement["volume_rebate_cents"] == 0
    assert settlement["total_due_cents"] == 362244


def test_an_owner_elected_removal_adds_an_eight_percent_penalty(api):
    """PRD 3.9: "A `DROUGHT` removal waives 5 percent of the subtotal, entered as a
    negative adjustment; an `OWNER_ELECTED` removal adds an 8 percent penalty as a
    positive adjustment; a `GRAZIER_ELECTED` removal gives the owner a 10 percent credit
    as a negative adjustment; and when no early removal happened the adjustment is 0."
    PRD 3.8: "If any lot on the contract is in `ON_FEED` or `REMOVAL_SCHEDULED`, the
    contract moves `ACTIVE → EARLY_REMOVAL_PENDING`, stores `early_removal_reason` and
    `early_removal_effective_date`, and cascades to every `ON_FEED` lot, moving it to
    `REMOVAL_SCHEDULED` with `scheduled_removal_date` set to the effective date."

    Design: Corner/calculations/owner_elected_early_removal_adds_an_eight_percent_penalty
    """
    world = setup_north_bench_lot_on_feed()
    validate_success(
        api.early_removal(
            world.contract_id,
            {"reason": "OWNER_ELECTED", "effective_date": "2026-10-15"},
            make_cattle_owner_headers(world.owner_id),
        ),
        200,
    )
    weigh_out_lot(
        world.lot_id, world.grazier_id,
        gross_weight_lbs=66000, head_count=150,
        scale_ticket_ref="T-OE", weighed_at="2026-10-15T09:00:00Z",
    )
    set_logical_clock("2026-10-17T00:00:00Z")

    contract = read_contract(world.contract_id, world.grazier_id)
    assert contract["lifecycle_status"] == "EARLY_REMOVAL_PENDING"
    assert contract["early_removal_reason"] == "OWNER_ELECTED"
    assert read_lot(world.lot_id, world.grazier_id)["days_on_feed"] == 66

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["average_daily_gain"] == pytest.approx(0.4531, abs=0.00005)
    assert settlement["subtotal_cents"] == 381310
    assert settlement["early_removal_adjustment_cents"] == 30505
    assert settlement["total_due_cents"] == 411815


# ===========================================================================
# The two drafting preconditions and the stale-parent guard
# ===========================================================================

def test_drafting_is_refused_while_a_treatment_is_still_awaiting_review(api):
    """PRD 3.9: "Two preconditions guard the draft: the lot must have exactly one `OUT`
    scale ticket — no weigh-out means no gain to settle, and the empty case is rejected
    with `ERR_NO_OUT_WEIGHT` — and every health treatment on the lot must already be
    `APPROVED` or `VOIDED`, with any row still `RECORDED` or `DISPUTED` rejected as
    `ERR_OPEN_TREATMENT_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/settlement_draft_gated_by_open_health_treatment_review
    """
    world = setup_north_bench_lot_on_feed()
    record_treatment(world.lot_id, world.grazier_id, **TREATMENT_A)
    weigh_out_lot(world.lot_id, world.grazier_id)
    set_logical_clock("2026-11-12T00:00:00Z")

    contract_version = read_contract(world.contract_id, world.grazier_id)["version"]
    resp = api.create_settlement(
        settlement_payload(world.contract_id, world.lot_id, contract_version),
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_TREATMENT_REVIEW.value, 409)

    _, meta = validate_paginated(
        api.list_settlements(
            make_grazier_headers(world.grazier_id), params={"contract_id": world.contract_id}
        )
    )
    assert meta["total_count"] == 0, "The refused draft wrote no settlement"


def test_approving_the_open_treatment_lets_the_identical_draft_through(api):
    """PRD 3.9: "Two preconditions guard the draft: the lot must have exactly one `OUT`
    scale ticket — no weigh-out means no gain to settle, and the empty case is rejected
    with `ERR_NO_OUT_WEIGHT` — and every health treatment on the lot must already be
    `APPROVED` or `VOIDED`, with any row still `RECORDED` or `DISPUTED` rejected as
    `ERR_OPEN_TREATMENT_REVIEW`."
    PRD 3.9: "After the base charge, `treatment_charge_cents` is the sum of the owner
    shares of the lot's `APPROVED` treatments, each already rounded when it was
    recorded, as §3.5 requires."

    Design: Difficulty/cross_entity_state_dependency/settlement_draft_gated_by_open_health_treatment_review
    """
    world = setup_north_bench_lot_on_feed()
    treatment = record_treatment(world.lot_id, world.grazier_id, **TREATMENT_A)
    weigh_out_lot(world.lot_id, world.grazier_id)
    set_logical_clock("2026-11-12T00:00:00Z")

    approved = review_treatment_as_owner(treatment["id"], world.owner_id, "APPROVE")
    assert approved["status"] == "APPROVED"

    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["status"] == "DRAFT"
    assert settlement["treatment_charge_cents"] == 1089
    assert settlement["base_charge_cents"] == 1143760
    assert settlement["subtotal_cents"] == 1144849
    assert settlement["volume_rebate_cents"] == 11448
    assert settlement["total_due_cents"] == 1133401


def test_drafting_against_a_lot_that_never_weighed_out_is_refused(api):
    """PRD 3.9: "Two preconditions guard the draft: the lot must have exactly one `OUT`
    scale ticket — no weigh-out means no gain to settle, and the empty case is rejected
    with `ERR_NO_OUT_WEIGHT` — and every health treatment on the lot must already be
    `APPROVED` or `VOIDED`, with any row still `RECORDED` or `DISPUTED` rejected as
    `ERR_OPEN_TREATMENT_REVIEW`."

    Design: Corner/validations/settlement_on_a_lot_still_on_feed_returns_no_out_weight
    """
    world = setup_north_bench_lot_on_feed()

    contract_version = read_contract(world.contract_id, world.grazier_id)["version"]
    resp = api.create_settlement(
        settlement_payload(world.contract_id, world.lot_id, contract_version),
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_NO_OUT_WEIGHT.value, 409)

    assert read_lot(world.lot_id, world.grazier_id)["status"] == "ON_FEED"
    assert read_contract(world.contract_id, world.grazier_id)["billing_status"] == "UNBILLED"


def test_a_stale_expected_contract_version_is_rejected_before_any_business_check(api):
    """PRD 2.6: "A mismatch against the contract's current `version` is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."
    PRD 2.8: "And because state (rule 10) sits below the stale-parent check (rule 9), a
    settlement draft carrying a stale `expected_contract_version` reports the
    stale-version code even when the lot would also have failed a later business check."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_contract_version_on_a_settlement_draft_returns_412
    """
    world = setup_north_bench_lot_on_feed()
    stale_version = 1

    resp = api.create_settlement(
        settlement_payload(world.contract_id, world.lot_id, stale_version),
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value, 412)

    _, meta = validate_paginated(
        api.list_settlements(
            make_grazier_headers(world.grazier_id), params={"contract_id": world.contract_id}
        )
    )
    assert meta["total_count"] == 0, "No settlement row was written"
    assert read_contract(world.contract_id, world.grazier_id)["version"] == 3


def test_the_draft_response_already_carries_every_derived_total(api):
    """PRD 1: "Every derived aggregate — a pasture's booked head-days, an owner's open
    settlement balance, a lot's confirmed death count — is recomputed inside the request
    that invalidated it, and every cascade a mutation implies is applied before the
    response is written."
    PRD 3.9: "The draft lands in `status` `DRAFT` with `dispute_round` at 0,
    `gain_method` at `PROVISIONAL_PRORATED`, and a snapshot of the lot's `days_on_feed`
    copied onto it."

    Design: Corner/consistency_model/settlement_draft_response_carries_every_derived_total_immediately
    """
    world = setup_north_bench_lot_on_feed()
    weigh_out_lot(world.lot_id, world.grazier_id)
    set_logical_clock("2026-11-12T00:00:00Z")

    contract_version = read_contract(world.contract_id, world.grazier_id)["version"]
    resp = api.create_settlement(
        settlement_payload(world.contract_id, world.lot_id, contract_version),
        make_grazier_headers(world.grazier_id),
    )
    created = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"

    for field in (
        "base_charge_cents", "treatment_charge_cents", "infrastructure_charge_cents",
        "death_loss_credit_cents", "subtotal_cents", "volume_rebate_cents",
        "total_due_cents",
    ):
        assert field in created, f"The create response must already carry {field}"

    assert created["subtotal_cents"] == 1143760
    assert created["total_due_cents"] == 1132322
    assert created["gain_method"] == "PROVISIONAL_PRORATED"
    assert created["days_on_feed"] == 92
    assert created["dispute_round"] == 0
    assert created["status"] == "DRAFT"

    reread = validate_success(
        api.get_settlement(created["id"], make_cattle_owner_headers(world.owner_id))
    )
    assert reread["total_due_cents"] == created["total_due_cents"], (
        "A follow-up read must return the same figure with no reconciliation lag"
    )
