"""Calculation breadth probes: remainders, boundaries, and variant divergence.

Every figure asserted here is pinned by the contract's own arithmetic, so a
single misplaced rounding, floor, or comparison operator shows up as a
one-cent or one-basis-point discrepancy rather than as a vague failure.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_instant_equals,
    allocation_row,
    assert_allocation_sums_to,
    read_by_id,
    read_contract,
    read_element,
    read_work_order,
)
from test_helpers.factories import (
    common_element_payload,
    owner_ballot_payload,
    vendor_contract_payload,
    violation_case_payload,
    work_order_payload,
)
from test_helpers.fixtures import (
    add_element,
    add_owner,
    add_unit,
    adjust_claim,
    adopt_budget,
    convene,
    create_association,
    issue_certificate,
    notice_meeting,
    open_special_assessment,
    patch_association,
    report_claim,
    request_certificate,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS

HARBOR_POINT = "Harbor Point Condominium Association"


def _one_owner_association(api):
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    return ctx


def _board_of_one(api):
    ctx = _one_owner_association(api)
    add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    return ctx


def _post_charge_as_manager(api, unit_id, **fields):
    payload = {
        "entry_type": "ASSESSMENT",
        "amount_cents": 20_000,
        "due_on": "2026-09-05T10:00:00Z",
        "effective_period": "2026-09",
        "memo": "September stub",
    }
    payload.update(fields)
    return get_success_data(api.create_charge(unit_id, payload, MANAGER_HEADERS))


# ======================================================================
# The assessment allocator
# ======================================================================
def test_a_negative_allocation_drift_takes_a_cent_off_the_first_participant(api):
    """Four equal shares overshoot the pool, so a cent must be removed.

    916667 cents split four ways rounds each line up to 229167, overshooting by
    one; the fifth step of the allocator therefore subtracts, and the first
    participant in the pinned order is the one that gives the cent back.

    PRD 3.2: "First, the pool is fixed in integer cents *before* any per-unit
    arithmetic: for a budget adoption the pool is `assessment_total_cents`
    divided by 12 and rounded half up."
    PRD 3.2: "Second, the participants are every unit of the association --
    with no delinquency filter, because every unit owes assessments -- ordered
    by `interest_bp` descending and then by `created_at` ascending."
    PRD 3.2: "Third, each participant's share is computed as the pool
    multiplied by that unit's `interest_bp`, divided by 10000, and rounded half
    up; this per-line rounding is mandatory and summing before rounding is
    wrong."
    PRD 3.2: "Fifth, the drift is distributed one cent at a time by cycling
    through the participants in the same pinned order, starting at the first
    participant and wrapping around as often as necessary: a positive drift
    adds one cent per step, a negative drift removes one cent per step, until
    the drift is exhausted."
    PRD 3.2: "Each unit's `monthly_assessment_cents` receives its final share,
    and the budget's `allocation_snapshot` freezes one object per participant
    carrying `unit_id`, `interest_bp`, `monthly_cents` holding the final share,
    and `remainder_cent_awarded`, a boolean that is true exactly when the final
    share differs from the per-line rounded value computed in the third step."

    Design: Corner/calculations/allocation_negative_remainder_removes_one_cent_from_the_first_participant
    """
    ctx = _board_of_one(api)
    for label in ("101", "102", "103", "104"):
        add_unit(ctx, label, "o1", 2500, heated_sqft=1000)

    data = adopt_budget(
        ctx,
        operating_total_cents=10_000_004,
        reserve_contribution_cents=1_000_000,
        meeting_label="mtg1",
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
    )
    assert data["status"] == "ADOPTED"
    assert data["no_weight_bp"] == 0
    assert data["assessment_total_cents"] == 11_000_004
    assert data["monthly_assessable_cents"] == 916_667
    assert len(data["allocation_snapshot"]) == 4

    assert ctx.unit("101")["monthly_assessment_cents"] == 229_166
    assert ctx.unit("102")["monthly_assessment_cents"] == 229_167
    assert ctx.unit("103")["monthly_assessment_cents"] == 229_167
    assert ctx.unit("104")["monthly_assessment_cents"] == 229_167

    assert_allocation_sums_to(data["allocation_snapshot"], "monthly_cents", 916_667)
    first = allocation_row(data["allocation_snapshot"], ctx.units["101"])
    assert first["monthly_cents"] == 229_166
    assert first["remainder_cent_awarded"] is True


# ======================================================================
# The late-fee limbs
# ======================================================================
def test_one_billing_run_produces_the_grace_boundary_the_floor_and_the_cap(api):
    """Three units, one rule, three different answers.

    Ten days of aging is not strictly greater than the grace period, so no fee
    at all; an eleven-day small debt is lifted to the floor; an eleven-day large
    debt is cut to the cap.

    PRD 3.5: "The boundary matters: a charge aged exactly `late_fee_grace_days`
    -- ten days by default -- contributes nothing, because the charge must be
    strictly older than the grace period."
    PRD 3.5: "Otherwise the percentage limb is the delinquent principal
    multiplied by `late_fee_percent_bp`, divided by 10000, and rounded half up
    -- one tenth of the delinquent principal at the default of 1000 basis
    points -- and the fee is then that percentage limb raised to at least
    `late_fee_min_cents` and afterwards lowered to at most `late_fee_cap_cents`,
    applying the floor before the cap in that order."
    PRD 3.5: "A positive fee is posted as a `LATE_FEE` row in bucket
    `LATE_FEE` with a positive `amount_cents`, the run's `due_on` as its
    `due_on`, and the run's `period` as its `effective_period`."
    PRD 3.5: "A run for a period this association has already billed is refused
    with `ERR_PERIOD_ALREADY_BILLED`, and a `source_budget_id` that is not
    `ADOPTED`, or whose `fiscal_year` does not cover the `period`, is refused
    with `ERR_BUDGET_NOT_ADOPTED`."
    PRD 3.1: "Rule 5: if `oldest_unpaid_age_days` is strictly greater than
    `late_fee_grace_days`, the posture is `REMINDER`."

    Design: Corner/calculations/late_fee_grace_boundary_and_floor_cap_limbs_in_one_run
    """
    ctx = _board_of_one(api)
    add_unit(ctx, "101", "o1", 3334, heated_sqft=1000)
    add_unit(ctx, "102", "o1", 3333, heated_sqft=1000)
    add_unit(ctx, "103", "o1", 3333, heated_sqft=1000)

    budget = adopt_budget(
        ctx,
        meeting_label="mtg1",
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
    )
    # Aging is measured from due_on, so these may be posted after the clock jump.
    _post_charge_as_manager(api, ctx.units["101"], due_on="2026-09-05T10:00:00Z")
    _post_charge_as_manager(api, ctx.units["102"], due_on="2026-09-04T10:00:00Z")
    _post_charge_as_manager(
        api, ctx.units["103"], amount_cents=300_000, due_on="2026-09-04T10:00:00Z"
    )

    run_payload = {
        "source_budget_id": budget["id"],
        "period": "2026-10",
        "due_on": "2026-10-01T00:00:00Z",
    }
    run = validate_success(
        api.create_billing_run(ctx.association_id, run_payload, MANAGER_HEADERS),
        expected_status=201,
    )

    _, meta_101 = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["101"], "entry_type": "LATE_FEE"},
        )
    )
    assert meta_101["total_count"] == 0

    rows_102, meta_102 = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["102"], "entry_type": "LATE_FEE"},
        )
    )
    assert meta_102["total_count"] == 1
    assert rows_102[0]["amount_cents"] == 2500
    assert_instant_equals(rows_102[0]["due_on"], "2026-10-01T00:00:00Z")

    rows_103, meta_103 = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["103"], "entry_type": "LATE_FEE"},
        )
    )
    assert meta_103["total_count"] == 1
    assert rows_103[0]["amount_cents"] == 10_000

    _, assessment_meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"billing_run_id": run["id"], "entry_type": "ASSESSMENT"},
        )
    )
    assert assessment_meta["total_count"] == 3

    unit_101 = ctx.unit("101")
    assert unit_101["balance_due_cents"] == 386_740
    assert unit_101["delinquency_stage"] == "CURRENT"
    unit_102 = ctx.unit("102")
    assert unit_102["balance_due_cents"] == 389_130
    assert unit_102["delinquency_stage"] == "REMINDER"
    unit_103 = ctx.unit("103")
    assert unit_103["balance_due_cents"] == 676_630
    assert unit_103["delinquency_stage"] == "REMINDER"

    validate_error(
        api.create_billing_run(ctx.association_id, run_payload, MANAGER_HEADERS),
        "ERR_PERIOD_ALREADY_BILLED",
        expected_status=409,
    )


# ======================================================================
# Reserve funding adequacy
# ======================================================================
def test_the_two_reserve_methods_disagree_on_one_component_roster(api):
    """A component 35 years out is worth 1500000 straight-line and 0 by horizon.

    The same cash reads DEFICIENT under one method and, at exactly the
    threshold, ADEQUATE under the other, and neither read persists anything.

    PRD 3.6: "Under the default **straight-line** method -- selected when
    `method` is omitted or is `STRAIGHT_LINE` -- each component's fully-funded
    basis is its `replacement_cost_cents` multiplied by the lesser of
    `effective_age_years` and `useful_life_years`, divided by
    `useful_life_years`, and rounded half up; the target accrues linearly with
    effective age over the whole useful life, so every non-decommissioned
    component contributes something."
    PRD 3.6: "Under the **component** method -- selected when `method` is
    `COMPONENT` -- the component's remaining life is `useful_life_years` minus
    `effective_age_years` but never less than 0, and the fully-funded basis is
    0 when that remaining life exceeds a thirty-year cash-flow horizon and is
    otherwise `replacement_cost_cents` multiplied by thirty minus the remaining
    life, divided by thirty, and rounded half up."
    PRD 3.6: "Spendable reserves, reported as `spendable_cents`, are the
    association's `reserve_balance_cents` minus its `reserve_designated_cents`,
    so litigation designations and approved special assessments depress the
    score."
    PRD 3.6: "The reported `posture` is `ADEQUATE` when `percent_funded_bp` is
    greater than or equal to `reserve_adequacy_threshold_bp` and `DEFICIENT`
    otherwise; a value exactly equal to the seventy-percent default threshold
    is `ADEQUATE`."
    PRD 3.6: "Nothing is persisted by this report."

    Design: Corner/calculations/reserve_adequacy_methods_disagree_at_the_exact_threshold
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_element(
        ctx,
        "el1",
        name="Passenger Elevator #1",
        element_class="ELEVATOR",
        replacement_cost_cents=30_000_000,
        useful_life_years=50,
        effective_age_years=25,
    )
    add_element(
        ctx,
        "el2",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=12_000_000,
        useful_life_years=40,
        effective_age_years=5,
    )
    patch_association(ctx, reserve_balance_cents=3_500_000)

    straight = validate_success(
        api.get_reserve_adequacy(
            ctx.association_id, MANAGER_HEADERS, params={"method": "STRAIGHT_LINE"}
        )
    )
    assert straight["fully_funded_cents"] == 16_500_000
    assert straight["spendable_cents"] == 3_500_000
    assert straight["percent_funded_bp"] == 2121
    assert straight["posture"] == "DEFICIENT"

    component = validate_success(
        api.get_reserve_adequacy(
            ctx.association_id, MANAGER_HEADERS, params={"method": "COMPONENT"}
        )
    )
    assert component["fully_funded_cents"] == 5_000_000
    assert component["percent_funded_bp"] == 7000
    assert component["posture"] == "ADEQUATE"

    association = ctx.association()
    assert association["reserve_balance_cents"] == 3_500_000
    assert association["reserve_designated_cents"] == 0


# ======================================================================
# The deductible waterfall
# ======================================================================
def test_the_tier_three_waterfall_floors_each_share_then_tops_up_one_cent(api):
    """The gross loss alone chooses the tier, and the residue floors down.

    Three identical units each floor to 583333, one cent short of the residue,
    and that cent goes to the first participant in the pinned order -- the
    opposite remainder rule from the assessment allocator.

    PRD 3.7: "The tier basis is the claim's `gross_damage_cents` and **only**
    that figure; the owner exposure the waterfall itself produces is a reported
    output and is never fed back into the tier decision."
    PRD 3.7: "The association's share in basis points is 10000 when the basis
    is strictly below 5000000 cents, 6000 when the basis is at or above 5000000
    but strictly below 25000000 cents, and 3000 when the basis is at or above
    25000000 cents; the ceilings are exclusive at the low end of each band, so a
    basis of exactly 5000000 lands in the sixty-percent band and exactly
    25000000 lands in the thirty-percent band."
    PRD 3.7: "Each unit's provisional allocation is the residue multiplied by
    that unit's `heated_sqft`, divided by the total square footage, and
    **floored** -- a floor here, not a rounding."
    PRD 3.7: "The drift is the residue minus the sum of the floored allocations
    and is at least 0 and strictly less than the number of participants; one
    additional cent is given to each of the first drift participants in that
    pinned order, at most one cent each."
    PRD 3.7: "`SPLIT` moves the claim to `ADJUSTED_SPLIT` and requires that
    `affected_unit_ids` be non-empty -- an empty array is a rejection with
    `ERR_NO_AFFECTED_UNITS`, never a silent no-op -- and that both
    `within_unit_boundary_cents` and `common_element_damage_cents` be strictly
    greater than 0."

    Design: Corner/calculations/deductible_waterfall_tier3_floor_split_distributes_the_single_drift_cent
    """
    ctx = _one_owner_association(api)
    add_unit(ctx, "101", "o1", 3334, heated_sqft=1000)
    add_unit(ctx, "102", "o1", 3333, heated_sqft=1000)
    add_unit(ctx, "103", "o1", 3333, heated_sqft=1000)
    add_element(
        ctx,
        "el1",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=12_000_000,
        useful_life_years=40,
        effective_age_years=5,
    )
    patch_association(ctx, operating_cash_cents=5_000_000)

    claim = report_claim(
        ctx,
        "101",
        "el1",
        loss_type="WIND",
        loss_at="2026-07-20T00:00:00Z",
        gross_damage_cents=30_000_000,
        within_unit_boundary_cents=6_000_000,
        affected_unit_ids=[ctx.units["101"], ctx.units["102"], ctx.units["103"]],
    )
    data = adjust_claim(ctx, claim["id"], "SPLIT")

    assert data["adjustment_status"] == "ADJUSTED_SPLIT"
    assert data["common_element_damage_cents"] == 24_000_000
    assert data["association_absorbed_cents"] == 750_000
    assert data["owner_chargeback_cents"] == 1_750_000

    allocation = data["deductible_allocation"]
    assert [row["allocated_cents"] for row in allocation] == [583_334, 583_333, 583_333]
    assert allocation[0]["unit_id"] == ctx.units["101"]
    assert (
        sum(row["allocated_cents"] for row in allocation)
        + data["association_absorbed_cents"]
        == 2_500_000
    )

    assert ctx.unit("101")["balance_due_cents"] == 583_334
    assert ctx.unit("102")["balance_due_cents"] == 583_333

    _, meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={
                "source_claim_id": claim["id"],
                "entry_type": "INSURANCE_DEDUCTIBLE_CHARGEBACK",
            },
        )
    )
    assert meta["total_count"] == 3
    assert ctx.association()["operating_cash_cents"] == 4_250_000


# ======================================================================
# The payment waterfall variants
# ======================================================================
def test_owner_direction_is_silently_ignored_once_the_lien_is_filed(api):
    """The same directed payment lands differently on two identical ledgers.

    A LIEN_FILED unit is forced back onto the statutory order, so interest is
    cleared first; the LATE_NOTICE unit keeps its direction.

    PRD 3.1: "The **owner-directed** variant applies when `application_mode` is
    `OWNER_DIRECTED` and `directed_bucket` names a bucket; the effective order
    then places `directed_bucket` first and follows it with the statutory order
    minus that bucket."
    PRD 3.1: "There is one override: if the unit's `delinquency_stage` is
    `LIEN_FILED` or `FORECLOSURE_REFERRAL`, an owner-directed request is
    **silently forced onto the statutory variant** rather than rejected --
    collection is with counsel and the owner no longer chooses."
    PRD 3.1: "The statutory bucket order is `INTEREST` first, then `LATE_FEE`,
    then `COLLECTION_COST`, then `FINE`, then `ASSESSMENT`, then
    `SPECIAL_ASSESSMENT`."
    PRD 3.1: "Whatever is left over becomes the payment's `unapplied_cents`,
    which is held as unapplied credit and is never negative."

    Design: Corner/calculations/owner_directed_payment_is_forced_onto_statutory_order_for_a_lien_filed_unit
    """
    ctx = _one_owner_association(api)
    add_unit(ctx, "101", "o1", 5000, heated_sqft=1000)
    add_unit(ctx, "102", "o1", 5000, heated_sqft=1000)

    interest_1 = _post_charge_as_manager(
        api,
        ctx.units["101"],
        entry_type="INTEREST",
        amount_cents=50_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="statutory interest",
    )
    assessment_1 = _post_charge_as_manager(
        api,
        ctx.units["101"],
        amount_cents=200_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="April assessment",
    )
    _post_charge_as_manager(
        api,
        ctx.units["102"],
        entry_type="INTEREST",
        amount_cents=50_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="statutory interest",
    )
    assessment_2 = _post_charge_as_manager(
        api,
        ctx.units["102"],
        amount_cents=100_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="April assessment",
    )

    assert ctx.unit("101")["delinquency_stage"] == "LIEN_FILED"
    assert ctx.unit("102")["delinquency_stage"] == "LATE_NOTICE"

    directed = {
        "amount_cents": 60_000,
        "effective_period": "2026-08",
        "application_mode": "OWNER_DIRECTED",
        "directed_bucket": "ASSESSMENT",
        "memo": "owner asks for assessment first",
    }
    forced = validate_success(
        api.create_payment(ctx.units["101"], directed, MANAGER_HEADERS),
        expected_status=201,
    )
    allocations = forced["applied_allocations"]
    assert len(allocations) == 2
    assert allocations[0]["bucket"] == "INTEREST"
    assert allocations[0]["target_entry_id"] == interest_1["id"]
    assert allocations[0]["applied_cents"] == 50_000
    assert allocations[1]["bucket"] == "ASSESSMENT"
    assert allocations[1]["target_entry_id"] == assessment_1["id"]
    assert allocations[1]["applied_cents"] == 10_000
    assert forced["unapplied_cents"] == 0

    unit_101 = ctx.unit("101")
    assert unit_101["balance_due_cents"] == 190_000
    assert unit_101["delinquency_stage"] == "LIEN_FILED"

    honoured = validate_success(
        api.create_payment(ctx.units["102"], directed, MANAGER_HEADERS),
        expected_status=201,
    )
    kept = honoured["applied_allocations"]
    assert len(kept) == 1
    assert kept[0]["bucket"] == "ASSESSMENT"
    assert kept[0]["target_entry_id"] == assessment_2["id"]
    assert kept[0]["applied_cents"] == 60_000

    unit_102 = ctx.unit("102")
    assert unit_102["balance_due_cents"] == 90_000
    assert unit_102["delinquency_stage"] == "LATE_NOTICE"


# ======================================================================
# The two owner tallies
# ======================================================================
def test_a_yes_share_of_exactly_the_threshold_approves_over_an_abstain(api):
    """The abstaining unit stays in the denominator and does not inflate the share.

    PRD 3.4: "`eligible_weight_bp` is the sum of `interest_bp` over every unit
    of the association whose `voting_eligible` is true, so a unit that never
    cast a ballot still sits in the denominator."
    PRD 3.4: "`yes_weight_bp` is the sum of `weight_bp` over the counted
    ballots whose `choice` is `YES`; `ABSTAIN` ballots add nothing to the
    numerator and do not leave the denominator."
    PRD 3.4: "Otherwise the yes share in basis points is `yes_weight_bp`
    multiplied by 10000, divided by `eligible_weight_bp`, and floored; the
    assessment is approved when that share is greater than or equal to
    `special_assessment_approval_bp`."
    PRD 3.4: "With the default two-thirds-plus threshold of 6667 basis points,
    a yes share of exactly 6667 approves and 6666 fails."
    PRD 3.4: "On `BALLOTING → APPROVED`, the server writes `eligible_weight_bp`,
    `yes_weight_bp`, and `ballot_closed_at` from the logical clock, increases
    the association's `reserve_designated_cents` by `total_amount_cents` and
    advances `Association.version` by 1, leaves `funding_status` untouched at
    `UNFUNDED`, and advances `SpecialAssessment.version` by 1."
    PRD 3.3: "Note that `counted` is recomputed at tally time as true for every
    board vote and, for owner ballots, as the unit's `voting_eligible` at that
    moment."

    Design: Corner/calculations/special_assessment_approves_at_exactly_6667_with_an_abstain_in_the_denominator
    """
    ctx = _board_of_one(api)
    add_owner(ctx, "o2", full_name="Nina Boyd", email="nina@example.test")
    add_owner(
        ctx,
        "tr",
        full_name="Tina Cole",
        email="tina@example.test",
        board_role="TREASURER",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 6667, heated_sqft=1400)
    add_unit(ctx, "102", "o2", 3333, heated_sqft=900)

    assessment = open_special_assessment(
        ctx,
        total_amount_cents=4_000_000,
        installment_count=4,
        purpose="Facade repair",
    )
    for owner_label, unit_label, choice in (
        ("o1", "101", "YES"),
        ("o2", "102", "ABSTAIN"),
    ):
        get_success_data(
            api.cast_vote(
                owner_ballot_payload(
                    ctx.association_id,
                    "SPECIAL_ASSESSMENT",
                    assessment["id"],
                    ctx.owners[owner_label],
                    ctx.units[unit_label],
                    choice=choice,
                ),
                ctx.owner(owner_label),
            )
        )

    data = validate_success(api.close_ballot(assessment["id"], ctx.director("d1")))
    assert data["approval_status"] == "APPROVED"
    assert data["eligible_weight_bp"] == 10000
    assert data["yes_weight_bp"] == 6667
    assert_instant_equals(data["ballot_closed_at"], "2026-08-01T00:00:00Z")
    assert data["funding_status"] == "UNFUNDED"
    assert data["collected_cents"] == 0

    association = ctx.association()
    assert association["reserve_designated_cents"] == 4_000_000
    assert association["restricted_sa_cash_cents"] == 0

    rows, meta = validate_paginated(
        api.list_votes(MANAGER_HEADERS, params={"subject_id": assessment["id"]})
    )
    assert meta["total_count"] == 2
    assert all(row["counted"] is True for row in rows)


def test_a_veto_of_exactly_the_threshold_rejects_from_an_uncounted_ballot(api):
    """Veto rights survive delinquency: the denominator is the whole association.

    The LIEN_FILED unit's ballot is uncounted -- that flag belongs to the
    special-assessment tally -- yet its 5000 basis points of NO weight still
    reach the veto threshold exactly, and rejection leaves the allocation unwritten.

    PRD 3.2: "In deliberate contrast with the special-assessment tally,
    **veto rights survive delinquency** -- `voting_eligible` is *not* applied
    here, and the denominator is the whole association."
    PRD 3.2: "`no_weight_bp` is the sum of `weight_bp` over the surviving
    ballots whose `choice` is `NO`, the denominator is the association's
    `total_interest_bp` (always 10000, never the eligible weight), and the
    budget is rejected when `no_weight_bp` is greater than or equal to
    `budget_veto_bp`."
    PRD 3.2: "On `NOTICED → REJECTED`, the server writes `no_weight_bp` from
    the tally, does **not** touch any unit's `monthly_assessment_cents`, leaves
    `allocation_snapshot` empty, voids no certificate, and advances
    `Budget.version` by 1."
    PRD 3.1: "Rule 3: if `oldest_unpaid_age_days` is at least 90 and
    `balance_due_cents` is at least `lien_threshold_cents`, the posture is
    `LIEN_FILED`."
    PRD 3.3: "Note that `counted` is recomputed at tally time as true for every
    board vote and, for owner ballots, as the unit's `voting_eligible` at that
    moment."

    Design: Corner/calculations/budget_veto_at_exactly_5000_rejects_even_though_the_ballot_is_uncounted
    """
    ctx = _board_of_one(api)
    add_unit(ctx, "101", "o1", 5000, heated_sqft=1000)
    add_unit(ctx, "102", "o1", 5000, heated_sqft=1000)
    _post_charge_as_manager(
        api,
        ctx.units["101"],
        entry_type="COLLECTION_COST",
        amount_cents=200_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="collection counsel",
    )
    assert ctx.unit("101")["delinquency_stage"] == "LIEN_FILED"

    data = adopt_budget(
        ctx,
        meeting_label="mtg1",
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
        veto_ballots=[("o1", "101", "NO")],
    )
    assert data["status"] == "REJECTED"
    assert data["no_weight_bp"] == 5000
    assert data["adopted_at"] is None
    assert data["allocation_snapshot"] == []

    rows, meta = validate_paginated(
        api.list_votes(MANAGER_HEADERS, params={"subject_id": data["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["weight_bp"] == 5000
    assert rows[0]["counted"] is False

    unit_101 = ctx.unit("101")
    assert unit_101["monthly_assessment_cents"] == 0
    assert unit_101["voting_eligible"] is False
    assert ctx.unit("102")["monthly_assessment_cents"] == 0


# ======================================================================
# Fine tier selection
# ======================================================================
def test_a_cured_predecessor_still_lifts_the_next_fine_to_tier_two(api):
    """Curing settles the case but keeps it in the repeat chain.

    PRD 3.8: "The predecessor is resolved as the first row among this
    association's cases for the same `unit_id` and the same `rule_code` whose
    `notice_sent_at` falls within `repeat_lookback_days` before this case's
    `notice_sent_at` and whose `status` is `FINE_ASSESSED`, `FINE_UPHELD`, or
    `CURED`, ordered by `notice_sent_at` descending and then by `created_at`
    descending; when no such row exists, `prior_case_id` stays null."
    PRD 3.8: "There is no ledger effect, the case stays in the repeat chain for
    future tier counting, and `ViolationCase.version` advances by 1."
    PRD 3.8: "`fine_tier` is 1 when the qualifying chain is empty, 2 when it
    holds exactly one link, and 3 when it holds two or more."
    PRD 3.8: "It writes `fine_tier` and `fine_amount_cents` from the tier
    selection below, posts a `FINE` row in bucket `FINE` on the cited unit with
    a positive `amount_cents` equal to `fine_amount_cents` and `due_on` thirty
    days after the logical clock, stores that row's identifier in
    `fine_entry_id`, recomputes the unit's `balance_due_cents` and re-derives
    its `delinquency_stage` with `Unit.version` advancing by 1, sets
    `decision_owner_id` to the acting `X-User-ID`, sets `appeal_deadline_at` to
    the logical clock advanced by `appeal_window_days`, and advances
    `ViolationCase.version` by 1."

    Design: Corner/calculations/repeat_chain_through_a_cured_case_charges_tier_two
    """
    ctx = _board_of_one(api)
    add_owner(
        ctx,
        "d2",
        full_name="Rita Vance",
        email="rita@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)
    schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"
    )

    payload = violation_case_payload(
        ctx.association_id, ctx.units["101"], ctx.owners["d2"], rule_code="R-14-PETS"
    )
    case_a = get_success_data(api.create_violation_case(payload, MANAGER_HEADERS))
    get_success_data(api.send_case_notice(case_a["id"], MANAGER_HEADERS))
    set_clock(api, "2026-08-10T00:00:00Z")
    get_success_data(api.mark_case_cured(case_a["id"], MANAGER_HEADERS))

    set_clock(api, "2026-08-16T00:00:00Z")
    case_b = get_success_data(api.create_violation_case(payload, MANAGER_HEADERS))
    get_success_data(api.send_case_notice(case_b["id"], MANAGER_HEADERS))

    set_clock(api, "2026-08-31T00:00:00Z")
    get_success_data(
        api.schedule_hearing(
            case_b["id"],
            {
                "hearing_meeting_id": ctx.meetings["mtg1"],
                "hearing_slot_start": "2026-09-01T10:00:00Z",
            },
            ctx.director("d1"),
        )
    )
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-09-01T10:00:00Z")
    convene(ctx, "mtg1", attending=("d1",))

    data = validate_success(
        api.hearing_decision(case_b["id"], {"outcome": "FINE"}, ctx.director("d1"))
    )
    assert data["status"] == "FINE_ASSESSED"
    assert data["prior_case_id"] == case_a["id"]
    assert data["fine_tier"] == 2
    assert data["fine_amount_cents"] == 10_000
    assert_instant_equals(data["appeal_deadline_at"], "2026-10-01T10:00:00Z")

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["101"], "entry_type": "FINE"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == 10_000
    assert_instant_equals(rows[0]["due_on"], "2026-10-01T10:00:00Z")

    unit = ctx.unit("101")
    assert unit["balance_due_cents"] == 10_000
    assert unit["delinquency_stage"] == "CURRENT"


# ======================================================================
# The resale payoff bases
# ======================================================================
def test_estimated_payoff_projects_two_periods_and_credits_the_buyer_half_a_month(api):
    """The two payoff bases diverge by the projection plus the seller credit.

    Only the periods whose first day falls strictly inside the open interval
    between the clock and the closing date are projected, and the single
    proration rounding happens once at the very end.

    PRD 3.9: "Under `LEDGER_BALANCE`, `ledger_balance_cents` and
    `projected_payoff_cents` are both the unit's `balance_due_cents` and
    `proration_credit_cents` is 0: today's ledger only, with no forward
    projection and no seller credit."
    PRD 3.9: "Under `ESTIMATED_PAYOFF`, `ledger_balance_cents` is still the
    unit's `balance_due_cents`, the count of future periods is the number of
    whole billing periods whose first day falls strictly after the logical clock
    and strictly before `closing_date` and for which the unit has no `POSTED`
    `ASSESSMENT` row yet, the gross figure is the unit's `balance_due_cents`
    plus that count multiplied by the unit's `monthly_assessment_cents` plus the
    unbilled special-assessment disclosure, `proration_credit_cents` is the
    unit's `monthly_assessment_cents` multiplied by the buyer's days, divided by
    the month length, and rounded half up **once at the end** -- prorating each
    future period separately and summing is explicitly not the pinned order --
    and `projected_payoff_cents` is the gross figure minus
    `proration_credit_cents`."
    PRD 3.9: "The seller's interval is half-open over the closing month: it
    begins at midnight UTC on the first day of the calendar month containing
    `closing_date` and ends strictly before `closing_date`, so the closing day
    itself belongs to the buyer."
    PRD 3.9: "First the `RESALE_FEE` row is posted on the unit for
    `resale_cert_fee_cents`, with its identifier stored in `cert_fee_entry_id`,
    and the unit's `balance_due_cents` and `delinquency_stage` are recomputed
    with `Unit.version` advancing by 1."
    PRD 3.9: "Finally `issued_at` is stamped from the logical clock,
    `expires_at` is set to `issued_at` advanced by `certificate_validity_days`,
    the unit's `transfer_blocked` is set to false, and
    `ResaleCertificate.version` advances by 1."

    Design: Corner/calculations/estimated_payoff_projects_two_unbilled_periods_and_credits_the_buyer_half_month
    """
    ctx = _board_of_one(api)
    add_unit(ctx, "101", "o1", 5000, heated_sqft=1000)
    add_unit(ctx, "102", "o1", 5000, heated_sqft=1000)
    adopt_budget(
        ctx,
        meeting_label="mtg1",
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
    )

    ledger_cert = issue_certificate(
        ctx, "102", closing_date="2026-11-16T00:00:00Z", payoff_basis="LEDGER_BALANCE"
    )
    estimated = request_certificate(
        ctx, "101", closing_date="2026-11-16T00:00:00Z", payoff_basis="ESTIMATED_PAYOFF"
    )

    data = validate_success(
        api.issue_resale_certificate(estimated["id"], MANAGER_HEADERS)
    )
    assert data["status"] == "ISSUED"
    assert data["payoff_basis"] == "ESTIMATED_PAYOFF"
    assert data["ledger_balance_cents"] == 35_000
    assert data["proration_credit_cents"] == 275_000
    assert data["projected_payoff_cents"] == 860_000
    assert data["special_assessment_disclosure_cents"] == 0
    assert data["open_violation_count"] == 0
    assert data["disclosed_claim_ids"] == []
    assert_instant_equals(data["issued_at"], "2026-09-15T10:00:00Z")
    assert_instant_equals(data["expires_at"], "2026-10-15T10:00:00Z")

    stored = read_by_id(
        api.list_resale_certificates(
            MANAGER_HEADERS, params={"unit_id": ctx.units["102"]}
        ),
        ledger_cert["id"],
    )
    assert stored["ledger_balance_cents"] == 35_000
    assert stored["proration_credit_cents"] == 0
    assert stored["projected_payoff_cents"] == 35_000


# ======================================================================
# Encumbrance conservation
# ======================================================================
def test_invoicing_at_the_exact_tolerance_swaps_committed_into_invoiced(api):
    """A cancel round trip returns committed to 0, and the tolerance is inclusive.

    One cent above the floored ten-percent overrun is refused; the boundary
    itself is admitted and moves the estimate out of committed_cents.

    PRD 3.6: "The overrun tolerance admits a `final_cost_cents` no greater than
    `estimated_cost_cents` multiplied by 11 and divided by 10 with the result
    floored -- a ten percent overrun, inclusive of the boundary -- and the sum
    of the contract's `invoiced_cents` and `final_cost_cents` must not exceed
    `contract_cap_cents`; either failure yields
    `ERR_INVOICE_EXCEEDS_TOLERANCE`."
    PRD 3.6: "On success `encumbered_cents` becomes 0, the contract's
    `committed_cents` falls by `estimated_cost_cents` while its `invoiced_cents`
    rises by `final_cost_cents` with `VendorContract.version` advancing by 1,
    the association's `operating_cash_cents` falls by `final_cost_cents` with
    `Association.version` advancing by 1, and `MaintenanceWorkOrder.version`
    advances by 1."
    PRD 3.6: "Both legs set `encumbered_cents` to 0 and reduce the contract's
    `committed_cents` by exactly the released encumbrance, advancing
    `VendorContract.version` by 1, and both advance the order's own `version`
    by 1."
    PRD 3.6: "Completing work moves it `IN_PROGRESS → COMPLETED`, requires that
    the logical clock have reached `window_start`, drives the element's `status`
    to `SERVICEABLE`, stamps the element's `last_serviced_at` with the logical
    clock, and -- when the payload sets the optional `resets_component` flag to
    true -- resets the element's `effective_age_years` to 0, which changes the
    fully-funded basis used by the reserve computation below; both
    `CommonElement.version` and `MaintenanceWorkOrder.version` advance by 1."
    PRD 3.6: "The `percent_funded_bp` figure is 10000 when `fully_funded_cents`
    is 0 -- an association with no components reports full funding rather than
    dividing by zero -- and is otherwise `spendable_cents` multiplied by 10000,
    divided by `fully_funded_cents`, and floored."

    Design: Corner/calculations/encumbrance_round_trip_and_invoice_at_the_exact_overrun_tolerance
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    patch_association(ctx, operating_cash_cents=5_000_000)

    element = get_success_data(
        api.create_common_element(
            ctx.association_id,
            common_element_payload(
                name="Passenger Elevator #1",
                element_class="ELEVATOR",
                replacement_cost_cents=30_000_000,
                useful_life_years=50,
                effective_age_years=25,
            ),
            MANAGER_HEADERS,
        )
    )
    contract = get_success_data(
        api.create_vendor_contract(
            ctx.association_id,
            vendor_contract_payload(
                element["id"],
                vendor_name="Summit Elevator Co",
                contract_cap_cents=5_000_000,
                insurance_cert_expires_at="2027-06-30T00:00:00Z",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2027-06-30T00:00:00Z",
            ),
            MANAGER_HEADERS,
        )
    )
    get_success_data(api.submit_contract(contract["id"], MANAGER_HEADERS))
    meeting_id = schedule_meeting(
        ctx, "mtg1", ["CONTRACT_AWARD"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z"
    )
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-08-05T10:00:00Z")
    convene(ctx, "mtg1", attending=("d1",))
    get_success_data(
        api.cast_vote(
            {
                "association_id": ctx.association_id,
                "subject_type": "VENDOR_CONTRACT",
                "subject_id": contract["id"],
                "choice": "YES",
                "voter_owner_id": ctx.owners["d1"],
                "meeting_id": meeting_id,
            },
            ctx.director("d1"),
        )
    )
    get_success_data(api.approve_contract(contract["id"], ctx.director("d1")))
    get_success_data(api.activate_contract(contract["id"], MANAGER_HEADERS))

    deferred = get_success_data(
        api.create_work_order(
            work_order_payload(
                contract["id"],
                element["id"],
                read_contract(api, contract["id"], MANAGER_HEADERS)["version"],
                scope="Cab interior refresh",
                window_start="2026-09-10T08:00:00Z",
                window_end="2026-09-10T16:00:00Z",
                estimated_cost_cents=400_000,
            ),
            MANAGER_HEADERS,
        )
    )
    get_success_data(
        api.cancel_work_order(
            deferred["id"],
            MANAGER_HEADERS,
            payload={"reason": "deferred to next fiscal year"},
        )
    )
    assert read_contract(api, contract["id"], MANAGER_HEADERS)["committed_cents"] == 0

    order = get_success_data(
        api.create_work_order(
            work_order_payload(
                contract["id"],
                element["id"],
                read_contract(api, contract["id"], MANAGER_HEADERS)["version"],
                scope="Annual traction inspection",
                window_start="2026-08-06T08:00:00Z",
                window_end="2026-08-06T16:00:00Z",
                estimated_cost_cents=1_000_000,
            ),
            MANAGER_HEADERS,
        )
    )
    set_clock(api, "2026-08-06T08:00:00Z")
    get_success_data(api.start_work_order(order["id"], MANAGER_HEADERS))
    get_success_data(
        api.complete_work_order(
            order["id"], MANAGER_HEADERS, payload={"resets_component": True}
        )
    )

    validate_error(
        api.invoice_work_order(
            order["id"], {"final_cost_cents": 1_100_001}, MANAGER_HEADERS
        ),
        "ERR_INVOICE_EXCEEDS_TOLERANCE",
        expected_status=409,
    )
    data = validate_success(
        api.invoice_work_order(
            order["id"], {"final_cost_cents": 1_100_000}, MANAGER_HEADERS
        )
    )
    assert data["status"] == "INVOICED"
    assert data["encumbered_cents"] == 0

    stored_contract = read_contract(api, contract["id"], MANAGER_HEADERS)
    assert stored_contract["committed_cents"] == 0
    assert stored_contract["invoiced_cents"] == 1_100_000

    cancelled = read_work_order(api, deferred["id"], MANAGER_HEADERS)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["encumbered_cents"] == 0

    assert ctx.association()["operating_cash_cents"] == 3_900_000

    stored_element = read_element(api, element["id"], MANAGER_HEADERS)
    assert stored_element["status"] == "SERVICEABLE"
    assert stored_element["effective_age_years"] == 0
    assert_instant_equals(stored_element["last_serviced_at"], "2026-08-06T08:00:00Z")

    report = validate_success(
        api.get_reserve_adequacy(
            ctx.association_id, MANAGER_HEADERS, params={"method": "STRAIGHT_LINE"}
        )
    )
    assert report["fully_funded_cents"] == 0
    assert report["posture"] == "ADEQUATE"
