"""Lump-sum pricing: the fee tier is keyed on the pre-fee amount, both tier ceilings
are inclusive, and data cleanliness outranks the eligibility ceiling.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors, make_participant_headers
from test_helpers.constants import (
    ADMIN_FEE_CAP_CENTS,
    ADMIN_FEE_TIER_1_MAX_CENTS,
    ADMIN_FEE_TIER_2_MAX_CENTS,
    LS_FACTOR_BP,
    admin_fee_bp_for,
    admin_fee_cents_for,
    annualise,
    apply_bp,
    net_lump_sum_cents_for,
    raw_lump_sum_pv,
    recomputed_monthly_benefit,
)
from test_helpers.fixtures import (
    ParticipantSpec,
    build_authorized_plan,
    build_open_window,
    confirm_address,
    confirm_alive,
    create_clean_participants,
    create_participant,
    elect,
    latest_audit,
    open_benefit_audit,
    read_election,
    read_participant,
    resolve_audit,
)

DEFERRED = "DEFERRED_VESTED"

#: A deferred-vested participant's raw present value is exactly 120x the monthly benefit.
PV_MULTIPLE = 120


def _lump_sum_plan(api, **plan_overrides):
    return build_authorized_plan(
        api,
        participants=[],
        strategy_type="LUMP_SUM_WINDOW",
        amendment_scope="LUMP_SUM_ONLY",
        **plan_overrides
    )


# ---------------------------------------------------------------------------
# Design: Difficulty/combinatorial_formula/lump_sum_fee_tier_keyed_on_pre_fee_amount
# ---------------------------------------------------------------------------


def test_fee_tier_reads_the_pre_fee_present_value_not_the_net_amount(api):
    """A 12,006,000-cent offer pays 40 bp even though its net falls back in the 75 bp band.

    PRD: "Second, the administrative fee tier, keyed strictly on that **pre-fee**
    `raw_pv_cents` and never on the net amount."

    PRD: "This ladder is deliberately non-monotonic — the largest offers are charged
    the *lower* rate of 40 basis points, because the administrative work does not
    scale with the size of the cheque — so keying the tier off a post-fee amount would
    push a large offer down into the 75-basis-point band and overcharge it."

    Design: Difficulty/combinatorial_formula/lump_sum_fee_tier_keyed_on_pre_fee_amount
    """
    authorized = _lump_sum_plan(api)
    participants = create_clean_participants(
        api,
        authorized.plan_id,
        [ParticipantSpec(100000, cohort=DEFERRED), ParticipantSpec(100050, cohort=DEFERRED)],
    )
    opened = build_open_window(api, authorized.plan_id, participants)

    assert opened.window["notice_count"] == 2

    priced = [
        elect(api, opened.election_for(participant["id"])["id"], participant["id"], "LUMP_SUM")
        for participant in participants
    ]
    at_ceiling, above_ceiling = priced

    assert at_ceiling["raw_pv_cents"] == raw_lump_sum_pv(100000, DEFERRED)
    assert at_ceiling["admin_fee_bp"] == 75
    assert at_ceiling["admin_fee_cents"] == admin_fee_cents_for(at_ceiling["raw_pv_cents"])
    assert at_ceiling["net_lump_sum_cents"] == net_lump_sum_cents_for(at_ceiling["raw_pv_cents"])

    assert above_ceiling["raw_pv_cents"] == raw_lump_sum_pv(100050, DEFERRED)
    assert above_ceiling["admin_fee_bp"] == 40
    assert above_ceiling["admin_fee_cents"] == admin_fee_cents_for(above_ceiling["raw_pv_cents"])
    assert above_ceiling["net_lump_sum_cents"] == net_lump_sum_cents_for(
        above_ceiling["raw_pv_cents"]
    )

    # Keying the tier off the net figure would put it back in the 75 bp band.
    net_keyed_fee = apply_bp(above_ceiling["raw_pv_cents"], 75)
    assert admin_fee_bp_for(above_ceiling["net_lump_sum_cents"]) == 75
    assert above_ceiling["admin_fee_cents"] != net_keyed_fee
    assert above_ceiling["net_lump_sum_cents"] > at_ceiling["net_lump_sum_cents"]


def test_the_deferred_vested_raw_present_value_is_the_annual_benefit_times_its_factor(api):
    """The priced offer is the annualised benefit scaled by the cohort's lump-sum factor.

    PRD: "It is multiplied by twelve to give an annual amount, that annual amount is
    multiplied by the lump-sum factor for the participant's `cohort` — 121,000 basis
    points for `RETIREE_IN_PAY` and 100,000 basis points for `DEFERRED_VESTED`,
    meaning a deferred-vested participant's raw present value is exactly 120 times the
    monthly benefit — and the product is rounded half up over 10,000 to give
    `raw_pv_cents`."

    PRD: "Fourth, `net_lump_sum_cents` is `raw_pv_cents` minus `admin_fee_cents`. That
    net figure is what the cap waterfall allocates and what the participant is actually
    paid."

    Design: Difficulty/combinatorial_formula/lump_sum_fee_tier_keyed_on_pre_fee_amount
    """
    authorized = _lump_sum_plan(api)
    participants = create_clean_participants(
        api, authorized.plan_id, [ParticipantSpec(100050, cohort=DEFERRED)]
    )
    opened = build_open_window(api, authorized.plan_id, participants)

    election = elect(
        api,
        opened.election_for(participants[0]["id"])["id"],
        participants[0]["id"],
        "LUMP_SUM",
    )

    assert election["election_status"] == "ELECTED_LUMP_SUM"
    assert election["raw_pv_cents"] == apply_bp(annualise(100050), LS_FACTOR_BP[DEFERRED])
    assert election["raw_pv_cents"] == 100050 * PV_MULTIPLE
    assert election["net_lump_sum_cents"] == (
        election["raw_pv_cents"] - election["admin_fee_cents"]
    )


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/admin_fee_tier_ceilings_are_inclusive_and_net_is_non_monotonic
# ---------------------------------------------------------------------------

#: Monthly benefits chosen so the raw present values sit exactly on, and one
#: representable step above, each of the two tier ceilings.
CEILING_PROBE_BENEFITS = (20000, 20001, 100000, 100001)


def test_both_admin_fee_tier_ceilings_are_inclusive(api):
    """An amount sitting exactly on a ceiling stays in the lower-numbered tier.

    PRD: "A `raw_pv_cents` of at most 2,400,000 (twenty-four thousand dollars) sets
    `admin_fee_bp` to 0. A `raw_pv_cents` above 2,400,000 and at most 12,000,000 sets
    `admin_fee_bp` to 75. A `raw_pv_cents` above 12,000,000 sets `admin_fee_bp` to 40.
    Both tier ceilings are inclusive."

    Design: Difficulty/boundary_precision_check/admin_fee_tier_ceilings_are_inclusive_and_net_is_non_monotonic
    """
    authorized = _lump_sum_plan(api)
    participants = create_clean_participants(
        api,
        authorized.plan_id,
        [ParticipantSpec(benefit, cohort=DEFERRED) for benefit in CEILING_PROBE_BENEFITS],
    )
    opened = build_open_window(api, authorized.plan_id, participants)

    assert opened.window["notice_count"] == 4

    priced = [
        elect(api, opened.election_for(participant["id"])["id"], participant["id"], "LUMP_SUM")
        for participant in participants
    ]
    on_tier_1, above_tier_1, on_tier_2, above_tier_2 = priced

    assert on_tier_1["raw_pv_cents"] == ADMIN_FEE_TIER_1_MAX_CENTS
    assert on_tier_1["admin_fee_bp"] == 0
    assert on_tier_1["admin_fee_cents"] == 0
    assert on_tier_1["net_lump_sum_cents"] == ADMIN_FEE_TIER_1_MAX_CENTS

    assert above_tier_1["raw_pv_cents"] == ADMIN_FEE_TIER_1_MAX_CENTS + PV_MULTIPLE
    assert above_tier_1["admin_fee_bp"] == 75

    assert on_tier_2["raw_pv_cents"] == ADMIN_FEE_TIER_2_MAX_CENTS
    assert on_tier_2["admin_fee_bp"] == 75
    assert on_tier_2["admin_fee_cents"] == apply_bp(ADMIN_FEE_TIER_2_MAX_CENTS, 75)

    assert above_tier_2["raw_pv_cents"] == ADMIN_FEE_TIER_2_MAX_CENTS + PV_MULTIPLE
    assert above_tier_2["admin_fee_bp"] == 40

    for election in priced:
        assert election["admin_fee_cents"] < ADMIN_FEE_CAP_CENTS


def test_crossing_a_tier_ceiling_makes_the_net_payment_move_the_wrong_way(api):
    """A 120-cent larger entitlement can pay less, and the uncapped fee rounds half up.

    PRD: "Third, the fee itself. The uncapped fee is `raw_pv_cents` multiplied by
    `admin_fee_bp` and rounded half up over 10,000, and `admin_fee_cents` is that
    uncapped fee or 500,000 cents — a five-thousand-dollar ceiling — whichever is
    smaller."

    PRD: "This ladder is deliberately non-monotonic — the largest offers are charged
    the *lower* rate of 40 basis points, because the administrative work does not
    scale with the size of the cheque — so keying the tier off a post-fee amount would
    push a large offer down into the 75-basis-point band and overcharge it."

    Design: Difficulty/boundary_precision_check/admin_fee_tier_ceilings_are_inclusive_and_net_is_non_monotonic
    """
    authorized = _lump_sum_plan(api)
    participants = create_clean_participants(
        api,
        authorized.plan_id,
        [ParticipantSpec(benefit, cohort=DEFERRED) for benefit in CEILING_PROBE_BENEFITS],
    )
    opened = build_open_window(api, authorized.plan_id, participants)

    priced = [
        elect(api, opened.election_for(participant["id"])["id"], participant["id"], "LUMP_SUM")
        for participant in participants
    ]
    on_tier_1, above_tier_1, on_tier_2, above_tier_2 = priced

    # The fee on the first crossing is a true fraction of a cent above 18000.
    raw_above_tier_1 = ADMIN_FEE_TIER_1_MAX_CENTS + PV_MULTIPLE
    assert raw_above_tier_1 * 75 % 10000 != 0
    assert above_tier_1["admin_fee_cents"] == apply_bp(raw_above_tier_1, 75)
    assert above_tier_1["admin_fee_cents"] == raw_above_tier_1 * 75 // 10000 + 1

    # A larger entitlement nets strictly less across the first ceiling.
    assert above_tier_1["raw_pv_cents"] > on_tier_1["raw_pv_cents"]
    assert above_tier_1["net_lump_sum_cents"] < on_tier_1["net_lump_sum_cents"]
    assert on_tier_1["net_lump_sum_cents"] - above_tier_1["net_lump_sum_cents"] == (
        above_tier_1["admin_fee_cents"] - PV_MULTIPLE
    )

    # Across the second ceiling the net payment jumps by the whole fee saving.
    raw_above_tier_2 = ADMIN_FEE_TIER_2_MAX_CENTS + PV_MULTIPLE
    assert above_tier_2["admin_fee_cents"] == apply_bp(raw_above_tier_2, 40)
    assert above_tier_2["net_lump_sum_cents"] - on_tier_2["net_lump_sum_cents"] == (
        on_tier_2["admin_fee_cents"] - above_tier_2["admin_fee_cents"] + PV_MULTIPLE
    )
    assert above_tier_2["net_lump_sum_cents"] > on_tier_2["net_lump_sum_cents"]


# ---------------------------------------------------------------------------
# Design: Difficulty/priority_pair_validation_conflict/election_data_cleanliness_safety_beats_eligibility_constraint
# ---------------------------------------------------------------------------

#: Stated benefit and earnings chosen so the recomputation exceeds the stated figure
#: by 600 cents, past the 500-cent audit tolerance.
STATED_BENEFIT_CENTS = 100000
UNDERSTATED_EARNINGS_CENTS = 201200
ELIGIBILITY_CEILING_CENTS = 12000000


def _window_with_a_participant_pushed_over_the_ceiling(api):
    authorized = _lump_sum_plan(api)
    participant = create_participant(
        api,
        authorized.plan_id,
        cohort=DEFERRED,
        stated_monthly_benefit_cents=STATED_BENEFIT_CENTS,
        final_average_monthly_earnings_cents=UNDERSTATED_EARNINGS_CENTS,
        credited_service_months=400,
    )
    confirm_address(api, participant["id"])
    confirm_alive(api, participant["id"])

    opened = build_open_window(
        api,
        authorized.plan_id,
        [participant],
        eligibility_max_lump_sum_cents=ELIGIBILITY_CEILING_CENTS,
    )

    first_audit = open_benefit_audit(api, participant["id"])
    resolve_audit(api, first_audit["id"], "APPLY_CORRECTION")
    second_audit = open_benefit_audit(api, participant["id"])
    return authorized, participant, opened, first_audit, second_audit


def test_data_cleanliness_is_reported_while_the_eligibility_breach_is_masked(api):
    """Both rules are broken; the higher-ranked cleanliness rule is the one reported.

    PRD: "The election must currently be in `NOTICE_SENT`; the window must be `OPEN`
    and the logical clock strictly before the window's `closes_at`, with either
    failure rejected as `ERR_WINDOW_NOT_OPEN`; the participant's `mortality_status`
    must be `ALIVE_CONFIRMED`, otherwise `ERR_MORTALITY_NOT_CONFIRMED`; and the
    participant's `benefit_audit_status` must be `PASSED_CLOSED` or `CORRECTED`,
    otherwise `ERR_PARTICIPANT_DATA_NOT_CLEAN` — nobody elects against an unaudited
    benefit figure. The participant's raw present value must also remain at or below
    the window's `eligibility_max_lump_sum_cents`, and an offer that has grown past
    the ceiling since the notice went out is rejected with
    `ERR_LUMP_SUM_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/election_data_cleanliness_safety_beats_eligibility_constraint
    """
    _authorized, participant, opened, first_audit, second_audit = (
        _window_with_a_participant_pushed_over_the_ceiling(api)
    )
    election_id = opened.election_for(participant["id"])["id"]

    assert opened.window["notice_count"] == 1
    assert opened.election_for(participant["id"])["notice_estimated_lump_sum_cents"] == (
        ELIGIBILITY_CEILING_CENTS
    )

    recomputed = recomputed_monthly_benefit(UNDERSTATED_EARNINGS_CENTS, 400)
    assert recomputed == STATED_BENEFIT_CENTS + 600

    corrected = read_participant(api, participant["id"])
    assert corrected["audited_monthly_benefit_cents"] == recomputed
    assert corrected["benefit_audit_status"] == "CORRECTION_REQUIRED"

    # Both rules are genuinely violated at this instant.
    breaching_pv = raw_lump_sum_pv(recomputed, DEFERRED)
    assert breaching_pv > ELIGIBILITY_CEILING_CENTS

    response = api.post_election(
        election_id, {"election_choice": "LUMP_SUM"}, make_participant_headers(participant["id"])
    )
    validate_error(response, api_errors.ERR_PARTICIPANT_DATA_NOT_CLEAN)

    untouched = read_election(api, election_id)
    assert untouched["election_status"] == "NOTICE_SENT"
    assert untouched["raw_pv_cents"] is None
    assert second_audit["audit_sequence"] == first_audit["audit_sequence"] + 1


def test_clearing_the_audit_uncovers_the_eligibility_rejection_underneath(api):
    """Once the audit is closed, the same request fails on the ceiling it always breached.

    PRD: "The participant's raw present value must also remain at or below the
    window's `eligibility_max_lump_sum_cents`, and an offer that has grown past the
    ceiling since the notice went out is rejected with `ERR_LUMP_SUM_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/election_data_cleanliness_safety_beats_eligibility_constraint
    """
    _authorized, participant, opened, _first_audit, second_audit = (
        _window_with_a_participant_pushed_over_the_ceiling(api)
    )
    election_id = opened.election_for(participant["id"])["id"]

    first_attempt = api.post_election(
        election_id, {"election_choice": "LUMP_SUM"}, make_participant_headers(participant["id"])
    )
    validate_error(first_attempt, api_errors.ERR_PARTICIPANT_DATA_NOT_CLEAN)

    resolve_audit(api, second_audit["id"], "APPLY_CORRECTION")
    cleared = read_participant(api, participant["id"])
    assert cleared["benefit_audit_status"] == "CORRECTED"
    assert latest_audit(api, participant["id"])["audit_status"] == "CORRECTED"

    second_attempt = api.post_election(
        election_id, {"election_choice": "LUMP_SUM"}, make_participant_headers(participant["id"])
    )
    validate_error(second_attempt, api_errors.ERR_LUMP_SUM_NOT_ELIGIBLE)

    untouched = read_election(api, election_id)
    assert untouched["election_status"] == "NOTICE_SENT"
    assert untouched["raw_pv_cents"] is None
