"""Which rule answers first: a tranche's own state against the fiscal check, the plan's
amendment scope against its status, and a downgrade that empties the candidate pool.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors, factories, fiduciary_headers, sponsor_headers
from test_helpers.constants import (
    IN_KIND_HAIRCUT_BP,
    PER_LOT_CUSTODY_FEE_CENTS,
    RATING_POINTS,
    SAFEST_AVAILABLE_MIN_RATING_POINTS,
    accounting_liability,
    apply_bp,
    composite_score_bp,
    data_confidence_for,
    in_kind_credited_value,
    in_kind_transfer_expense,
    settlement_liability,
)
from test_helpers.fixtures import (
    InsurerSpec,
    ParticipantSpec,
    QuoteSpec,
    adopt_amendment,
    assign_participant,
    build_authorized_plan,
    build_locked_tranche,
    build_quoting_tranche,
    change_rating,
    collect_quotes,
    create_insurer_panel,
    create_tranche,
    initiate_in_kind_transfer,
    list_asset_transfers,
    read_insurer,
    read_participant,
    read_plan,
    read_quote,
    read_tranche,
    rescind_amendment,
    review_transfer,
    select_insurer,
    settle_tranche,
)

DEFERRED = "DEFERRED_VESTED"
RETIREE = "RETIREE_IN_PAY"


# ---------------------------------------------------------------------------
# Design: Difficulty/priority_pair_validation_conflict/settled_tranche_state_beats_transfer_shortfall_fiscal
# ---------------------------------------------------------------------------

TRANSFER_PREMIUM_CENTS = 11800000
TRANSFER_GROSS_CENTS = 12000000
SHORT_LOT_COUNT = 3
EXACT_LOT_COUNT = 2

BEACON = InsurerSpec("Beacon National Life", "AA_MINUS", 3800, 200000000)


def _locked_tranche_for_funding(api):
    authorized = build_authorized_plan(
        api,
        participants=[ParticipantSpec(100000, cohort=DEFERRED)],
        total_liability_cents=100000000,
        plan_assets_cents=92000000,
        service_cost_cents=3000000,
        interest_cost_cents=9000000,
        unrecognized_actuarial_loss_cents=4000000,
    )
    insurer = create_insurer_panel(api, (BEACON,))[0]
    tranche = build_locked_tranche(
        api,
        authorized.plan_id,
        authorized.participants,
        [QuoteSpec(insurer["id"], TRANSFER_PREMIUM_CENTS, 90, 60)],
        target_cohort=DEFERRED,
    )
    return authorized, insurer, tranche


def _short_transfer(api, tranche_id, expected_version):
    payload = factories.in_kind_transfer_payload(
        expected_version, TRANSFER_GROSS_CENTS, SHORT_LOT_COUNT
    )
    return api.create_asset_transfer(tranche_id, payload, sponsor_headers())


def test_a_locked_tranche_values_the_delivery_and_refuses_the_short_one(api):
    """While the tranche is locked the fiscal check is what the delivery meets.

    PRD: "An in-kind delivery suffers two frictions: a valuation haircut of 125 basis
    points applied to `gross_value_cents` and rounded half up over 10,000, plus a
    per-lot custody fee of 25,000 cents for each security lot delivered."

    PRD: "In both modes `credited_value_cents` is `gross_value_cents` minus
    `transfer_expense_cents`, and `shortfall_cents` is the amount by which the tranche's
    `locked_premium_cents` exceeds `credited_value_cents`, or 0 when the credited value
    reaches or passes the premium. A shortfall above 0 is fatal: the request is rejected
    with `ERR_TRANSFER_VALUE_SHORTFALL` and no delivery record is created at all."

    Design: Difficulty/priority_pair_validation_conflict/settled_tranche_state_beats_transfer_shortfall_fiscal
    """
    _authorized, insurer, tranche = _locked_tranche_for_funding(api)

    assert tranche["tranche_status"] == "PRICING_LOCKED"
    assert tranche["locked_premium_cents"] == TRANSFER_PREMIUM_CENTS

    short_expense = in_kind_transfer_expense(TRANSFER_GROSS_CENTS, SHORT_LOT_COUNT)
    assert short_expense == (
        apply_bp(TRANSFER_GROSS_CENTS, IN_KIND_HAIRCUT_BP)
        + SHORT_LOT_COUNT * PER_LOT_CUSTODY_FEE_CENTS
    )
    assert in_kind_credited_value(TRANSFER_GROSS_CENTS, SHORT_LOT_COUNT) < TRANSFER_PREMIUM_CENTS

    rejected = _short_transfer(api, tranche["id"], tranche["version"])
    validate_error(rejected, api_errors.ERR_TRANSFER_VALUE_SHORTFALL)

    # No row was written and the tranche was not even touched.
    assert list_asset_transfers(api, tranche["id"]) == []
    untouched = read_tranche(api, tranche["id"])
    assert untouched["version"] == tranche["version"]
    assert untouched["tranche_status"] == "PRICING_LOCKED"
    assert untouched["transfer_expense_cents"] == 0

    accepted = initiate_in_kind_transfer(
        api, tranche["id"], TRANSFER_GROSS_CENTS, EXACT_LOT_COUNT, tranche["version"]
    )
    exact_expense = in_kind_transfer_expense(TRANSFER_GROSS_CENTS, EXACT_LOT_COUNT)
    assert accepted["transfer_expense_cents"] == exact_expense
    assert accepted["credited_value_cents"] == TRANSFER_PREMIUM_CENTS
    assert accepted["shortfall_cents"] == 0
    assert accepted["transfer_status"] == "INITIATED"
    assert accepted["in_kind_market_value_cents"] == TRANSFER_GROSS_CENTS
    assert accepted["in_kind_lot_count"] == EXACT_LOT_COUNT

    review_transfer(api, accepted["id"], insurer["id"], "ACCEPT")
    transferred = read_tranche(api, tranche["id"])
    assert transferred["tranche_status"] == "ASSETS_TRANSFERRED"
    assert transferred["transfer_expense_cents"] == exact_expense


def test_a_settled_tranche_answers_from_its_own_state_before_the_money_is_valued(api):
    """The identical short delivery draws a different error once the tranche is settled.

    PRD: "The families below are evaluated in the order listed; the first family that
    finds a violation decides the response, and later families are not consulted."

    PRD: "**Own-state precondition** — the target resource's own status field permits
    the requested transition, else the entity-specific conflict error:
    `ERR_PLAN_STATE_INVALID`, `ERR_STRATEGY_STATE_INVALID`,
    `ERR_PARTICIPANT_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`,
    `ERR_WINDOW_STATE_INVALID`, `ERR_ELECTION_STATE_INVALID`,
    `ERR_TRANCHE_STATE_INVALID`, `ERR_QUOTE_STATE_INVALID`, `ERR_EXPERT_STATE_INVALID`,
    `ERR_TRANSFER_STATE_INVALID`, or `ERR_COMPLAINT_STATE_INVALID`, all HTTP 409.
    Applies to every state-transition endpoint."

    Design: Difficulty/priority_pair_validation_conflict/settled_tranche_state_beats_transfer_shortfall_fiscal
    """
    _authorized, insurer, tranche = _locked_tranche_for_funding(api)

    first = _short_transfer(api, tranche["id"], tranche["version"])
    validate_error(first, api_errors.ERR_TRANSFER_VALUE_SHORTFALL)

    accepted = initiate_in_kind_transfer(
        api, tranche["id"], TRANSFER_GROSS_CENTS, EXACT_LOT_COUNT, tranche["version"]
    )
    review_transfer(api, accepted["id"], insurer["id"], "ACCEPT")
    settled = settle_tranche(api, tranche["id"])
    assert settled["tranche_status"] == "SETTLED"

    # The correct version is supplied, so the stale-version family cannot answer either.
    second = _short_transfer(api, tranche["id"], settled["version"])
    validate_error(second, api_errors.ERR_TRANCHE_STATE_INVALID)

    rows = list_asset_transfers(api, tranche["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == accepted["id"]
    assert rows[0]["transfer_status"] == "SETTLED"
    assert read_tranche(api, tranche["id"])["version"] == settled["version"]


# ---------------------------------------------------------------------------
# Design: Difficulty/cross_entity_state_dependency/quoting_gated_on_plan_amendment_scope_not_plan_state
# ---------------------------------------------------------------------------

SCOPE_BENEFIT_CENTS = 250000
SCOPE_PLAN = {
    "total_liability_cents": 90000000,
    "plan_assets_cents": 84000000,
    "service_cost_cents": 2500000,
    "interest_cost_cents": 7500000,
    "unrecognized_actuarial_loss_cents": 3000000,
    "discount_rate_bps": 490,
}
AMENDMENT_EFFECTIVE_DATE = "2026-08-15T00:00:00Z"


def _lump_sum_scoped_plan_with_a_draft_tranche(api):
    authorized = build_authorized_plan(
        api,
        participants=[ParticipantSpec(SCOPE_BENEFIT_CENTS)],
        strategy_type="HYBRID_WINDOW_AND_BUYOUT",
        amendment_scope="LUMP_SUM_ONLY",
        amendment_effective_date=AMENDMENT_EFFECTIVE_DATE,
        **SCOPE_PLAN
    )
    tranche = create_tranche(api, authorized.plan_id, RETIREE, tranche_name="Cadence Tranche")
    assign_participant(api, tranche["id"], authorized.participants[0]["id"])
    return authorized, read_tranche(api, tranche["id"])


def test_an_authorized_plan_whose_scope_omits_the_buyout_still_refuses_quoting(api):
    """The gate reads the amendment scope, not the plan status.

    PRD: "The plan must be `SETTLEMENT_AUTHORIZED` with an `amendment_scope` of
    `BUYOUT_ONLY` or `BOTH`, else `ERR_PLAN_NOT_SETTLEMENT_AUTHORIZED`."

    Design: Difficulty/cross_entity_state_dependency/quoting_gated_on_plan_amendment_scope_not_plan_state
    """
    authorized, tranche = _lump_sum_scoped_plan_with_a_draft_tranche(api)

    plan = read_plan(api, authorized.plan_id)
    assert plan["plan_status"] == "SETTLEMENT_AUTHORIZED"
    assert plan["amendment_scope"] == "LUMP_SUM_ONLY"
    assert tranche["tranche_status"] == "DRAFT"
    assert tranche["assigned_participant_count"] == 1

    response = api.post_tranche_quoting(tranche["id"], {}, fiduciary_headers())
    validate_error(response, api_errors.ERR_PLAN_NOT_SETTLEMENT_AUTHORIZED)

    untouched = read_tranche(api, tranche["id"])
    assert untouched["tranche_status"] == "DRAFT"
    assert untouched["version"] == tranche["version"]
    assert untouched["data_readiness_flag"] == tranche["data_readiness_flag"]


def test_rescinding_the_amendment_abandons_the_draft_so_its_own_state_answers_first(api):
    """After the rescission cascade the target's own state pre-empts the peer check.

    PRD: "When it succeeds, `amendment_scope`, `amendment_adopted_at`, and
    `amendment_effective_date` are all cleared, and two cascades fire: every window of
    the plan still in `PLANNED` transitions to `VOIDED`, and every tranche of the plan
    still in `DRAFT` transitions to `ABANDONED` — which in turn returns each of that
    tranche's assigned participants from `ASSIGNED` to `IN_PLAN` with `tranche_id`
    cleared and each such participant's `data_confidence_score` recomputed."

    PRD: "The families below are evaluated in the order listed; the first family that
    finds a violation decides the response, and later families are not consulted."

    Design: Difficulty/cross_entity_state_dependency/quoting_gated_on_plan_amendment_scope_not_plan_state
    """
    authorized, tranche = _lump_sum_scoped_plan_with_a_draft_tranche(api)
    participant_id = authorized.participants[0]["id"]

    first = api.post_tranche_quoting(tranche["id"], {}, fiduciary_headers())
    validate_error(first, api_errors.ERR_PLAN_NOT_SETTLEMENT_AUTHORIZED)

    rescinded = rescind_amendment(api, authorized.plan_id)
    assert rescinded["plan_status"] == "ONGOING"
    assert rescinded["amendment_scope"] is None

    abandoned = read_tranche(api, tranche["id"])
    assert abandoned["tranche_status"] == "ABANDONED"

    released = read_participant(api, participant_id)
    assert released["participant_status"] == "IN_PLAN"
    assert released["tranche_id"] is None
    assert released["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "PASSED_CLOSED"
    )

    second = api.post_tranche_quoting(tranche["id"], {}, fiduciary_headers())
    validate_error(second, api_errors.ERR_TRANCHE_STATE_INVALID)

    assert read_tranche(api, tranche["id"])["tranche_status"] == "ABANDONED"


def test_re_adopting_with_both_lets_the_unchanged_quoting_call_succeed(api):
    """A scope of `BOTH` opens the buyout channel and the same request now passes.

    PRD: "A scope of `LUMP_SUM_ONLY` is backed by an approved `LUMP_SUM_WINDOW` or
    `HYBRID_WINDOW_AND_BUYOUT` strategy; a scope of `BUYOUT_ONLY` is backed by an
    approved `ANNUITY_BUYOUT` or `HYBRID_WINDOW_AND_BUYOUT` strategy; a scope of `BOTH`
    is backed only by an approved `HYBRID_WINDOW_AND_BUYOUT` strategy."

    PRD: "On success the tranche's `accounting_liability_cents` and
    `settlement_liability_cents` are recomputed over the assigned population, its
    `data_readiness_flag` is set to `READY`, and its `version` is bumped."

    Design: Difficulty/cross_entity_state_dependency/quoting_gated_on_plan_amendment_scope_not_plan_state
    """
    authorized, tranche = _lump_sum_scoped_plan_with_a_draft_tranche(api)
    participant_id = authorized.participants[0]["id"]

    validate_error(
        api.post_tranche_quoting(tranche["id"], {}, fiduciary_headers()),
        api_errors.ERR_PLAN_NOT_SETTLEMENT_AUTHORIZED,
    )
    rescind_amendment(api, authorized.plan_id)

    readopted = adopt_amendment(api, authorized.plan_id, "BOTH", AMENDMENT_EFFECTIVE_DATE)
    assert readopted["plan_status"] == "SETTLEMENT_AUTHORIZED"
    assert readopted["amendment_scope"] == "BOTH"

    rebuilt = create_tranche(api, authorized.plan_id, RETIREE, tranche_name="Cadence Tranche Two")
    assign_participant(api, rebuilt["id"], participant_id)

    quoting = api.post_tranche_quoting(rebuilt["id"], {}, fiduciary_headers())
    opened = read_tranche(api, rebuilt["id"])
    assert quoting.status_code == 200
    assert opened["tranche_status"] == "QUOTING"
    assert opened["data_readiness_flag"] == "READY"
    assert opened["accounting_liability_cents"] == accounting_liability(
        SCOPE_BENEFIT_CENTS, RETIREE
    )
    assert opened["settlement_liability_cents"] == settlement_liability(
        SCOPE_BENEFIT_CENTS, RETIREE
    )

    # None of these transitions settles anything, so the plan's liability is untouched.
    assert read_plan(api, authorized.plan_id)["total_liability_cents"] == (
        SCOPE_PLAN["total_liability_cents"]
    )


# ---------------------------------------------------------------------------
# Design: Difficulty/transitive_cascade/rating_downgrade_cascades_quote_tranche_and_empties_pool
# ---------------------------------------------------------------------------

CARDINAL_PREMIUM_CENTS = 13400000
AURORA_PREMIUM_CENTS = 12500000
DOWNGRADE_PANEL = (
    InsurerSpec("Cardinal Guaranty Life", "AAA", 5100, 200000000),
    InsurerSpec("Aurora Life Assurance", "AA_PLUS", 4200, 200000000),
)
DOWNGRADE_GRADE = "BBB"
DOWNGRADE_CAPITAL_BP = 2600


def _selected_tranche_before_a_downgrade(api):
    authorized = build_authorized_plan(api, participants=[ParticipantSpec(SCOPE_BENEFIT_CENTS)])
    cardinal, aurora = create_insurer_panel(api, DOWNGRADE_PANEL)
    quoting = build_quoting_tranche(api, authorized.plan_id, authorized.participants)
    cardinal_quote, aurora_quote = collect_quotes(
        api,
        quoting.tranche_id,
        [
            QuoteSpec(cardinal["id"], CARDINAL_PREMIUM_CENTS, 90, 60),
            QuoteSpec(aurora["id"], AURORA_PREMIUM_CENTS, 90, 60),
        ],
    )
    selected = select_insurer(api, quoting.tranche_id, "SAFETY_WEIGHTED")
    return authorized, cardinal, aurora, selected, cardinal_quote, aurora_quote


def test_a_downgrade_below_the_floor_drags_the_tranche_back_out_of_selection(api):
    """One regulator write unpicks the carrier three entities deep.

    PRD: "The action stamps `rating_changed_at`, bumps the carrier's `version`, and
    cascades when the new grade maps below 78 points. Every quote of that carrier whose
    `quote_status` is `SUBMITTED` or `SHORTLISTED` transitions to `INELIGIBLE`, bumping
    each quote's `version`."

    PRD: "Where the ineligible quote was `SHORTLISTED` — that is, where it was some
    tranche's selected quote — that tranche falls back `INSURER_SELECTED → QUOTING`: its
    `selected_quote_id`, `selected_insurer_id`, `selection_score_bp`, and
    `selection_basis` are all cleared, its assigned participants' readiness is
    re-evaluated, its `data_readiness_flag` is set to `BLOCKED`, and its `version` is
    bumped."

    Design: Difficulty/transitive_cascade/rating_downgrade_cascades_quote_tranche_and_empties_pool
    """
    _authorized, cardinal, _aurora, selected, cardinal_quote, _aurora_quote = (
        _selected_tranche_before_a_downgrade(api)
    )

    expected_winner_score = composite_score_bp(
        "SAFETY_WEIGHTED", "AAA", 5100, AURORA_PREMIUM_CENTS, CARDINAL_PREMIUM_CENTS
    )
    assert selected["tranche_status"] == "INSURER_SELECTED"
    assert selected["selected_insurer_id"] == cardinal["id"]
    assert selected["selected_quote_id"] == cardinal_quote["id"]
    assert selected["selection_score_bp"] == expected_winner_score
    assert selected["data_readiness_flag"] == "READY"

    assert RATING_POINTS[DOWNGRADE_GRADE] < SAFEST_AVAILABLE_MIN_RATING_POINTS
    downgraded = change_rating(
        api, cardinal["id"], DOWNGRADE_GRADE, capital_ratio_bp=DOWNGRADE_CAPITAL_BP
    )
    assert downgraded["rating_grade"] == DOWNGRADE_GRADE
    assert downgraded["capital_ratio_bp"] == DOWNGRADE_CAPITAL_BP
    assert downgraded["rating_changed_at"] is not None

    assert read_quote(api, cardinal_quote["id"])["quote_status"] == "INELIGIBLE"

    fallen_back = read_tranche(api, selected["id"])
    assert fallen_back["tranche_status"] == "QUOTING"
    assert fallen_back["selected_quote_id"] is None
    assert fallen_back["selected_insurer_id"] is None
    assert fallen_back["selection_score_bp"] is None
    assert fallen_back["selection_basis"] is None
    assert fallen_back["data_readiness_flag"] == "BLOCKED"


def test_the_declined_rival_stays_terminal_so_re_selection_finds_no_candidates(api):
    """The cascade is lossy: the losing quote is not resurrected to fill the pool.

    PRD: "And the candidate pool must be non-empty, else `ERR_NO_ELIGIBLE_QUOTE` and no
    state changes at all — an empty pool is a rejection, not a zero score."

    PRD: "The candidate pool consists of every quote of this tranche whose
    `quote_status` is `SUBMITTED`, whose `expires_at` is strictly after the logical
    clock, whose `rating_at_submission` maps to at least 78 points, and whose carrier's
    `insurer_status` is `ACTIVE`."

    Design: Difficulty/transitive_cascade/rating_downgrade_cascades_quote_tranche_and_empties_pool
    """
    _authorized, cardinal, aurora, selected, cardinal_quote, aurora_quote = (
        _selected_tranche_before_a_downgrade(api)
    )

    loser_score = composite_score_bp(
        "SAFETY_WEIGHTED", "AA_PLUS", 4200, AURORA_PREMIUM_CENTS, AURORA_PREMIUM_CENTS
    )
    declined = read_quote(api, aurora_quote["id"])
    assert declined["quote_status"] == "DECLINED"
    assert declined["composite_score_bp"] == loser_score

    change_rating(api, cardinal["id"], DOWNGRADE_GRADE, capital_ratio_bp=DOWNGRADE_CAPITAL_BP)

    still_declined = read_quote(api, aurora_quote["id"])
    assert still_declined["quote_status"] == "DECLINED"
    assert still_declined["insurer_id"] == aurora["id"]
    assert read_quote(api, cardinal_quote["id"])["quote_status"] == "INELIGIBLE"

    response = api.post_insurer_selection(
        selected["id"],
        factories.insurer_selection_payload("SAFETY_WEIGHTED"),
        fiduciary_headers(),
    )
    validate_error(response, api_errors.ERR_NO_ELIGIBLE_QUOTE)

    unchanged = read_tranche(api, selected["id"])
    assert unchanged["tranche_status"] == "QUOTING"
    assert unchanged["selected_quote_id"] is None
    assert unchanged["selected_insurer_id"] is None


def test_the_downgrade_cascade_stops_at_the_tranche_and_leaves_participant_data_intact(api):
    """Readiness is blocked by the selection loss, not by any participant defect.

    PRD: "The `data_readiness_flag` is `BLOCKED` if the population is empty, `BLOCKED`
    if any assigned participant's `data_status` is anything other than `CLEAN`,
    `BLOCKED` if any assigned participant's `mortality_status` is anything other than
    `ALIVE_CONFIRMED`, `BLOCKED` if any assigned participant's `benefit_audit_status` is
    outside `PASSED_CLOSED` and `CORRECTED`, and `READY` only when none of those
    conditions holds."

    Design: Difficulty/transitive_cascade/rating_downgrade_cascades_quote_tranche_and_empties_pool
    """
    authorized, cardinal, _aurora, selected, _cq, _aq = _selected_tranche_before_a_downgrade(api)
    participant_id = authorized.participants[0]["id"]

    change_rating(api, cardinal["id"], DOWNGRADE_GRADE, capital_ratio_bp=DOWNGRADE_CAPITAL_BP)

    participant = read_participant(api, participant_id)
    assert participant["participant_status"] == "ASSIGNED"
    assert participant["data_status"] == "CLEAN"
    assert participant["mortality_status"] == "ALIVE_CONFIRMED"
    assert participant["benefit_audit_status"] == "PASSED_CLOSED"
    assert participant["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "PASSED_CLOSED"
    )

    tranche = read_tranche(api, selected["id"])
    assert tranche["data_readiness_flag"] == "BLOCKED"
    assert tranche["assigned_participant_count"] == 1
    assert tranche["accounting_liability_cents"] == accounting_liability(
        SCOPE_BENEFIT_CENTS, RETIREE
    )
    assert read_insurer(api, cardinal["id"])["rating_grade"] == DOWNGRADE_GRADE
