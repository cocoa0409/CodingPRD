"""Error breadth probes: one identifier per rung, and nothing written on refusal.

Each test drives a single documented refusal and then re-reads the touched rows,
because an error is only correct if the transaction it interrupted left no trace:
no extra ledger row, no half-promoted meeting, no silently altered posture.
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
    fetch_ledger_entries,
    find_entry,
    read_budget,
    read_case,
    read_claim,
    read_contract,
    read_element,
    read_meeting,
    read_special_assessment,
    read_unit,
)
from test_helpers.factories import (
    charge_payload,
    installment_payload,
    resale_certificate_payload,
    special_assessment_payload,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    adopt_budget,
    approve_special_assessment,
    convene,
    create_association,
    docket_hearing,
    draft_budget,
    notice_meeting,
    notice_violation_case,
    open_special_assessment,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import (
    ADJUSTER_HEADERS,
    MANAGER_HEADERS,
    TITLE_AGENT_HEADERS,
)

HARBOR_POINT = "Harbor Point Condominium Association"


def _owner_and_unit(api, **overrides):
    """One association, one owner of record, one unit holding the whole interest."""
    ctx = create_association(api, legal_name=HARBOR_POINT, **overrides)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_unit(ctx, "101", "o1", 10_000, heated_sqft=1_000)
    return ctx


def _seat_director(ctx, label="d1", full_name="Dana Reed", email="dana@example.test"):
    add_owner(
        ctx,
        label,
        full_name=full_name,
        email=email,
        board_role="DIRECTOR",
        is_seated=True,
    )


def _seat_treasurer(ctx):
    add_owner(
        ctx,
        "tr",
        full_name="Tina Cole",
        email="tina@example.test",
        board_role="TREASURER",
        is_seated=True,
    )


# ======================================================================
# Ledger corrections
# ======================================================================
def test_reversing_an_already_reversed_row_refuses_and_posts_no_third_row(api):
    """The compensating row exists exactly once, and the ledger proves it.

    A `REVERSED` charge no longer has a positive `amount_cents`, so the second
    reversal is refused; the unit is left with exactly two rows -- the reversed
    original and one compensating `REVERSAL` -- which net to a zero balance and
    put the unit on the first rung of the ladder.

    PRD 3.1: "A `BoardTreasurer` may reverse a ledger row, optionally supplying a
    `memo`; the target must have `status` `POSTED` and an `amount_cents` greater
    than zero, so reversing an already-`REVERSED` row or reversing a payment or
    credit row is refused with `ERR_ENTRY_ALREADY_REVERSED`."
    PRD 3.1: "A successful reversal creates a `REVERSAL` row whose
    `reverses_entry_id` names the original and whose `amount_cents` is the exact
    negation of the original's, flips the original's `status` to `REVERSED`,
    recomputes the unit's `balance_due_cents`, re-derives its
    `delinquency_stage`, and advances `Unit.version` by 1."
    PRD 3.1: "`balance_due_cents` is the signed sum of `amount_cents` over
    *every* ledger row of the unit, regardless of `status` -- a reversed pair nets
    to zero, so nothing is double counted."
    PRD 3.1: "Rule 1: if `balance_due_cents` is less than or equal to 0, the
    posture is `CURRENT`."

    Design: Corner/errors/reversing_an_already_reversed_entry_returns_entry_already_reversed
    """
    ctx = _owner_and_unit(api)
    _seat_treasurer(ctx)

    charge = get_success_data(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="ASSESSMENT",
                amount_cents=20_000,
                due_on="2026-08-15T00:00:00Z",
                effective_period="2026-08",
                memo="August assessment",
            ),
            MANAGER_HEADERS,
        )
    )
    get_success_data(
        api.reverse_ledger_entry(
            charge["id"], ctx.treasurer(), payload={"memo": "billed in error"}
        )
    )

    validate_error(
        api.reverse_ledger_entry(
            charge["id"], ctx.treasurer(), payload={"memo": "double reversal attempt"}
        ),
        "ERR_ENTRY_ALREADY_REVERSED",
        409,
    )

    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": ctx.units["101"]})
    )
    assert meta["total_count"] == 2
    rows = fetch_ledger_entries(api, MANAGER_HEADERS, unit_id=ctx.units["101"])
    original = find_entry(rows, id=charge["id"])
    assert original["status"] == "REVERSED"
    assert original["amount_cents"] == 20_000
    reversal = find_entry(rows, entry_type="REVERSAL")
    assert reversal["status"] == "POSTED"
    assert reversal["amount_cents"] == -20_000
    assert reversal["reverses_entry_id"] == charge["id"]

    unit = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert unit["balance_due_cents"] == 0
    assert unit["delinquency_stage"] == "CURRENT"


# ======================================================================
# Budget cycle refusals
# ======================================================================
def test_noticing_a_budget_bound_to_a_regular_only_meeting_is_refused(api):
    """The notice period is satisfied; the agenda is not.

    The bound meeting sits forty-five days out, so the notice-period rung passes
    and the only remaining defect is the agenda: a `REGULAR`-only meeting cannot
    host `BUDGET_RATIFICATION`. The failed notice must leave both rows alone --
    the budget still `PROPOSED` with a null `notice_sent_at`, and the meeting
    never promoted out of `SCHEDULED`.

    PRD 3.2: "Mailing the statutory notice moves the budget `PROPOSED →
    NOTICED`."
    PRD 3.2: "The budget must be `PROPOSED`; its `ratification_meeting_id` must
    be set; the referenced meeting's `status` must be `SCHEDULED` or `NOTICED`;
    that meeting's `agenda_kinds` must contain `BUDGET_RATIFICATION`, failing
    which the response is `ERR_AGENDA_KIND_MISSING`; and the meeting's
    `scheduled_start` must be at least `budget_notice_days` days after the
    logical clock, failing which the response is
    `ERR_NOTICE_PERIOD_NOT_SATISFIED`."
    PRD 3.2: "On success `notice_sent_at` is stamped with the logical clock; if
    the referenced meeting was `SCHEDULED` it is promoted to `NOTICED` with its
    own `notice_sent_at` stamped and `BoardMeeting.version` advanced by 1; and
    `Budget.version` advances by 1."

    Design: Corner/errors/budget_notice_to_a_regular_only_meeting_returns_agenda_kind_missing
    """
    ctx = _owner_and_unit(api)
    meeting_id = schedule_meeting(
        ctx, "mtg1", ["REGULAR"], "2026-09-15T10:00:00Z", "2026-09-15T12:00:00Z"
    )
    budget = draft_budget(ctx, ratification_meeting_id=meeting_id)
    get_success_data(api.propose_budget(budget["id"], MANAGER_HEADERS))

    validate_error(
        api.send_budget_notice(budget["id"], MANAGER_HEADERS),
        "ERR_AGENDA_KIND_MISSING",
        409,
    )

    stalled = read_budget(api, budget["id"], MANAGER_HEADERS)
    assert stalled["status"] == "PROPOSED"
    assert stalled["notice_sent_at"] is None
    meeting = read_meeting(api, meeting_id, MANAGER_HEADERS)
    assert meeting["status"] == "SCHEDULED"
    assert meeting["notice_sent_at"] is None


def test_proposing_a_second_budget_for_an_already_adopted_year_is_refused(api):
    """Drafting a rival for an adopted year is legal; proposing it is not.

    Creation only supersedes `DRAFT` or `PROPOSED` predecessors, so the second
    fiscal-2026 draft is accepted; the refusal lands on `propose`, and the
    adopted budget's arithmetic and the unit's monthly assessment must survive
    the attempt untouched.

    PRD 3.2: "And no other budget of the association for the same `fiscal_year`
    may already be `ADOPTED`, or the request fails with
    `ERR_DUPLICATE_ADOPTED_BUDGET`."
    PRD 3.2: "On success the server computes `assessment_total_cents` as
    `operating_total_cents` plus `reserve_contribution_cents`, computes
    `monthly_assessable_cents` as `assessment_total_cents` divided by 12 and
    rounded half up, and advances `Budget.version` by 1."
    PRD 3.2: "Creation is deliberately destructive of stale work: any other
    budget of the same association and the same `fiscal_year` whose `status` is
    `DRAFT` or `PROPOSED` moves to `SUPERSEDED`, the new budget records that
    predecessor in its own `supersedes_budget_id`, and every vote whose
    `subject_type` is `BUDGET` and whose `subject_id` is the superseded budget
    has its `counted` flag set to false."

    Design: Corner/errors/proposing_a_second_budget_for_an_adopted_year_returns_duplicate_adopted_budget
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx)

    adopted = adopt_budget(
        ctx,
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
    )
    assert adopted["status"] == "ADOPTED"
    assert adopted["monthly_assessable_cents"] == 1_100_000

    rival = draft_budget(
        ctx, operating_total_cents=13_000_000, reserve_contribution_cents=1_300_000
    )
    assert rival["status"] == "DRAFT"

    validate_error(
        api.propose_budget(rival["id"], MANAGER_HEADERS),
        "ERR_DUPLICATE_ADOPTED_BUDGET",
        409,
    )

    assert read_budget(api, rival["id"], MANAGER_HEADERS)["status"] == "DRAFT"
    survivor = read_budget(api, adopted["id"], MANAGER_HEADERS)
    assert survivor["status"] == "ADOPTED"
    assert survivor["monthly_assessable_cents"] == 1_100_000
    assert (
        read_unit(api, ctx.units["101"], MANAGER_HEADERS)["monthly_assessment_cents"]
        == 1_100_000
    )


# ======================================================================
# Special-assessment balloting refusals
# ======================================================================
def test_a_second_open_ballot_is_refused_while_a_sibling_is_balloting(api):
    """The blocking condition lives on a sibling row, not on the target.

    The second assessment is a flawless `DRAFT` and the association's interest
    still sums to 10000; the only obstacle is that the association already holds
    one `BALLOTING` assessment, so the open is refused and the target stays in
    `DRAFT`.

    PRD 3.4: "Four conditions apply: the assessment must be in `DRAFT`; the
    association's `total_interest_bp` must equal exactly 10000, or
    `ERR_INTEREST_SUM_INVALID` is returned; no other special assessment of the
    association may already be `BALLOTING`, or `ERR_BALLOT_ALREADY_OPEN` is
    returned; and when `funding_claim_id` is set, the referenced claim's
    `litigation_status` must be `TENDERED` or `IN_LITIGATION`."
    PRD 3.4: "The owner-approval dimension `approval_status` runs through
    `DRAFT`, `BALLOTING`, `APPROVED`, `FAILED`, and `RESCINDED`, starting at
    `DRAFT`."

    Design: Corner/errors/opening_a_second_ballot_returns_ballot_already_open
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx)
    _seat_treasurer(ctx)

    first = open_special_assessment(
        ctx,
        total_amount_cents=4_000_000,
        installment_count=4,
        purpose="Roof replacement",
    )
    second = get_success_data(
        api.create_special_assessment(
            ctx.association_id,
            special_assessment_payload(
                ctx.association_version(),
                purpose="Garage waterproofing",
                total_amount_cents=2_000_000,
                installment_count=2,
            ),
            ctx.treasurer(),
        )
    )
    assert second["approval_status"] == "DRAFT"

    validate_error(
        api.open_ballot(second["id"], ctx.director("d1")),
        "ERR_BALLOT_ALREADY_OPEN",
        409,
    )

    assert (
        read_special_assessment(api, first["id"], MANAGER_HEADERS)["approval_status"]
        == "BALLOTING"
    )
    assert (
        read_special_assessment(api, second["id"], MANAGER_HEADERS)["approval_status"]
        == "DRAFT"
    )


def test_closing_a_ballot_whose_only_unit_lost_eligibility_is_refused(api):
    """An empty denominator is an error, not a failed vote.

    The single unit escalates `LATE_NOTICE → LIEN_FILED` while the ballot is
    open, which flips `voting_eligible` to false and forces the open assessment
    to recompute `eligible_weight_bp` down to 0. Closing then has nothing to
    divide by, so the answer is a refusal rather than a `FAILED` tally, and no
    reserve designation may be booked.

    PRD 3.1: "Reaching `LATE_NOTICE → LIEN_FILED` additionally stamps
    `lien_recorded_at` with the logical clock and flips `voting_eligible` to
    false; because eligibility changed, every special assessment of the
    association whose `approval_status` is `BALLOTING` recomputes its
    `eligible_weight_bp` and re-derives the `counted` flag on its votes, each
    such assessment advancing its own `version` by 1; and when the re-derivation
    happened inside a billing run, that run's `escalated_unit_count` rises by 1."
    PRD 3.4: "`eligible_weight_bp` is the sum of `interest_bp` over every unit of
    the association whose `voting_eligible` is true, so a unit that never cast a
    ballot still sits in the denominator."
    PRD 3.4: "If `eligible_weight_bp` is 0 -- every unit having escalated to
    `LIEN_FILED` or `FORECLOSURE_REFERRAL` -- the close is rejected with
    `ERR_NO_ELIGIBLE_VOTERS` rather than being treated as a failure."
    PRD 3.1: "Rule 3: if `oldest_unpaid_age_days` is at least 90 and
    `balance_due_cents` is at least `lien_threshold_cents`, the posture is
    `LIEN_FILED`."

    Design: Corner/errors/closing_a_ballot_with_every_unit_ineligible_returns_no_eligible_voters
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx)
    _seat_treasurer(ctx)

    assessment = open_special_assessment(
        ctx,
        total_amount_cents=4_000_000,
        installment_count=4,
        purpose="Roof replacement",
    )

    for amount in (50_000, 150_000):
        get_success_data(
            api.create_charge(
                ctx.units["101"],
                charge_payload(
                    entry_type="COLLECTION_COST",
                    amount_cents=amount,
                    due_on="2026-05-01T00:00:00Z",
                    effective_period="2026-05",
                    memo="collection counsel",
                ),
                MANAGER_HEADERS,
            )
        )
    lienned = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert lienned["balance_due_cents"] == 200_000
    assert lienned["oldest_unpaid_age_days"] == 92
    assert lienned["delinquency_stage"] == "LIEN_FILED"
    assert lienned["voting_eligible"] is False
    assert_instant_equals(lienned["lien_recorded_at"], "2026-08-01T00:00:00Z")

    validate_error(
        api.close_ballot(assessment["id"], ctx.director("d1")),
        "ERR_NO_ELIGIBLE_VOTERS",
        409,
    )

    open_still = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert open_still["approval_status"] == "BALLOTING"
    assert open_still["eligible_weight_bp"] == 0
    assert ctx.association()["reserve_designated_cents"] == 0


def test_a_second_installment_round_on_a_single_round_assessment_is_refused(api):
    """One round was the whole assessment, so there is no second round to post.

    With `installment_count` 1 the first round is also the final round and takes
    the entire 4000000 cents, driving `installments_posted` to its ceiling; the
    second call is refused and the unit's ledger keeps exactly one
    special-assessment row.

    PRD 3.4: "The assessment's `approval_status` must be `APPROVED`, and
    `installments_posted` must be strictly below `installment_count`, or the
    request is refused with `ERR_INSTALLMENTS_EXHAUSTED`."
    PRD 3.4: "Each round reuses the same allocator as budget adoption, with one
    difference: the pool for rounds one through `installment_count` minus one is
    `total_amount_cents` divided by `installment_count` and rounded half up,
    while the **final** round instead uses `total_amount_cents` minus the sum of
    the pools already posted, so that the posted installments sum to
    `total_amount_cents` exactly with no drift."
    PRD 3.4: "One `SPECIAL_ASSESSMENT_INSTALLMENT` row per unit is posted with
    that unit's share, `installments_posted` rises by 1, `charged_cents` is
    recomputed, every affected unit's `balance_due_cents` is recomputed and its
    `delinquency_stage` re-derived with `Unit.version` advancing by 1, and
    `SpecialAssessment.version` advances by 1."

    Design: Corner/errors/posting_a_second_installment_on_a_single_round_assessment_is_exhausted
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx)
    _seat_treasurer(ctx)

    assessment = approve_special_assessment(
        ctx,
        total_amount_cents=4_000_000,
        installment_count=1,
        purpose="Roof replacement",
        ballots=(("o1", "101", "YES"),),
    )
    assert assessment["approval_status"] == "APPROVED"
    get_success_data(
        api.post_installment(
            assessment["id"],
            installment_payload(
                due_on="2026-09-01T00:00:00Z", effective_period="2026-09"
            ),
            ctx.treasurer(),
        )
    )

    validate_error(
        api.post_installment(
            assessment["id"],
            installment_payload(
                due_on="2026-10-01T00:00:00Z", effective_period="2026-10"
            ),
            ctx.treasurer(),
        ),
        "ERR_INSTALLMENTS_EXHAUSTED",
        409,
    )

    exhausted = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert exhausted["installments_posted"] == 1
    assert exhausted["charged_cents"] == 4_000_000

    _rows, meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS, params={"special_assessment_id": assessment["id"]}
        )
    )
    assert meta["total_count"] == 1
    rows = fetch_ledger_entries(
        api, MANAGER_HEADERS, special_assessment_id=assessment["id"]
    )
    assert rows[0]["amount_cents"] == 4_000_000
    assert rows[0]["bucket"] == "SPECIAL_ASSESSMENT"
    assert (
        read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"]
        == 4_000_000
    )


# ======================================================================
# Insurance claim refusals
# ======================================================================
def test_a_split_adjustment_with_no_affected_units_is_refused(api):
    """A split needs somebody to charge, and an empty array is not a no-op.

    Both sides of the damage split are strictly positive, so the arithmetic
    preconditions hold; what is missing is participants for the waterfall, and
    the answer is an explicit refusal that writes no chargeback row and leaves
    the element serviceable.

    PRD 3.7: "`SPLIT` moves the claim to `ADJUSTED_SPLIT` and requires that
    `affected_unit_ids` be non-empty -- an empty array is a rejection with
    `ERR_NO_AFFECTED_UNITS`, never a silent no-op -- and that both
    `within_unit_boundary_cents` and `common_element_damage_cents` be strictly
    greater than 0."
    PRD 3.7: "From `REPORTED → UNDER_REVIEW` the requirements are that
    `adjustment_status` be `REPORTED` or `APPEALED` and that at least one of
    `unit_id` or `element_id` be set; the side effects are that
    `common_element_damage_cents` is computed as `gross_damage_cents` minus
    `within_unit_boundary_cents` and `InsuranceClaim.version` advances by 1."
    PRD 3.7: "The claim also carries `common_element_damage_cents`,
    `deductible_allocation`, `association_absorbed_cents`,
    `owner_chargeback_cents`, `appeal_round`, and `disclosure_required`, all
    starting at 0, the empty array, or false as appropriate."
    PRD 3.6: "Serviceability is tracked in `status`, which runs through
    `SERVICEABLE`, `IMPAIRED`, `OUT_OF_SERVICE`, and `DECOMMISSIONED` and starts
    at `SERVICEABLE`."

    Design: Corner/errors/split_adjustment_with_no_affected_units_returns_no_affected_units
    """
    ctx = _owner_and_unit(api)
    element_id = add_element(
        ctx,
        "el1",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=12_000_000,
        useful_life_years=40,
        effective_age_years=5,
    )
    claim = get_success_data(
        api.create_insurance_claim(
            {
                "association_id": ctx.association_id,
                "loss_type": "WIND",
                "loss_at": "2026-07-20T00:00:00Z",
                "gross_damage_cents": 30_000_000,
                "within_unit_boundary_cents": 6_000_000,
                "element_id": element_id,
            },
            MANAGER_HEADERS,
        )
    )
    reviewed = get_success_data(api.assign_adjuster(claim["id"], ADJUSTER_HEADERS))
    assert reviewed["adjustment_status"] == "UNDER_REVIEW"
    assert reviewed["common_element_damage_cents"] == 24_000_000

    validate_error(
        api.adjust_claim(claim["id"], {"responsibility": "SPLIT"}, ADJUSTER_HEADERS),
        "ERR_NO_AFFECTED_UNITS",
        422,
    )

    stalled = read_claim(api, claim["id"], MANAGER_HEADERS)
    assert stalled["adjustment_status"] == "UNDER_REVIEW"
    assert stalled["association_absorbed_cents"] == 0
    assert stalled["owner_chargeback_cents"] == 0
    assert stalled["deductible_allocation"] == []

    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"source_claim_id": claim["id"]})
    )
    assert meta["total_count"] == 0
    assert read_element(api, element_id, MANAGER_HEADERS)["status"] == "SERVICEABLE"


def test_owner_responsibility_on_a_partly_common_loss_is_refused(api):
    """`OWNER` means the whole loss sat inside the unit, and 5000000 is not 8000000.

    Because 3000000 cents of common element damage exists, the owner branch
    contradicts the damage figures and is refused outright -- the server may not
    quietly fall back to a split allocation, so no chargeback row appears on the
    unit.

    PRD 3.7: "`OWNER` moves the claim to `ADJUSTED_OWNER` and requires `unit_id`
    to be set and `within_unit_boundary_cents` to equal `gross_damage_cents`
    exactly, meaning no common element was damaged."
    PRD 3.7: "In every case `adjustment_status` must be `UNDER_REVIEW` first, and
    a `responsibility` that contradicts the claim's damage figures is refused
    with `ERR_RESPONSIBILITY_MISMATCH`."
    PRD 3.7: "From `REPORTED → UNDER_REVIEW` the requirements are that
    `adjustment_status` be `REPORTED` or `APPEALED` and that at least one of
    `unit_id` or `element_id` be set; the side effects are that
    `common_element_damage_cents` is computed as `gross_damage_cents` minus
    `within_unit_boundary_cents` and `InsuranceClaim.version` advances by 1."

    Design: Corner/errors/owner_responsibility_on_a_common_element_loss_returns_responsibility_mismatch
    """
    ctx = _owner_and_unit(api)
    claim = get_success_data(
        api.create_insurance_claim(
            {
                "association_id": ctx.association_id,
                "loss_type": "WATER",
                "loss_at": "2026-07-20T00:00:00Z",
                "gross_damage_cents": 8_000_000,
                "within_unit_boundary_cents": 5_000_000,
                "unit_id": ctx.units["101"],
            },
            MANAGER_HEADERS,
        )
    )
    reviewed = get_success_data(api.assign_adjuster(claim["id"], ADJUSTER_HEADERS))
    assert reviewed["common_element_damage_cents"] == 3_000_000

    validate_error(
        api.adjust_claim(claim["id"], {"responsibility": "OWNER"}, ADJUSTER_HEADERS),
        "ERR_RESPONSIBILITY_MISMATCH",
        409,
    )

    stalled = read_claim(api, claim["id"], MANAGER_HEADERS)
    assert stalled["adjustment_status"] == "UNDER_REVIEW"
    assert stalled["common_element_damage_cents"] == 3_000_000
    assert stalled["owner_chargeback_cents"] == 0
    assert stalled["deductible_allocation"] == []

    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": ctx.units["101"]})
    )
    assert meta["total_count"] == 0


def test_reporting_a_claim_with_within_unit_damage_over_gross_is_refused(api):
    """The scope check bites at creation, before a negative figure can exist.

    A within-boundary portion larger than the gross loss would make
    `common_element_damage_cents` negative the moment the adjuster took the claim
    under review, so the row is never created at all.

    PRD 3.7: "A claim naming neither `unit_id` nor `element_id`, or whose
    `within_unit_boundary_cents` exceeds its `gross_damage_cents`, is rejected
    with `ERR_CLAIM_SCOPE_INVALID`."
    PRD 2.9: "A claim names at least one of `unit_id` or `element_id` and
    `within_unit_boundary_cents` does not exceed `gross_damage_cents` --
    otherwise `ERR_CLAIM_SCOPE_INVALID`, on claim reporting and on adjuster
    assignment."

    Design: Corner/errors/claim_with_within_unit_damage_over_gross_returns_claim_scope_invalid
    """
    ctx = _owner_and_unit(api)

    validate_error(
        api.create_insurance_claim(
            {
                "association_id": ctx.association_id,
                "loss_type": "WATER",
                "loss_at": "2026-07-20T00:00:00Z",
                "gross_damage_cents": 8_000_000,
                "within_unit_boundary_cents": 9_000_000,
                "unit_id": ctx.units["101"],
            },
            MANAGER_HEADERS,
        ),
        "ERR_CLAIM_SCOPE_INVALID",
        422,
    )

    _claims, meta = validate_paginated(
        api.list_insurance_claims(
            MANAGER_HEADERS, params={"association_id": ctx.association_id}
        )
    )
    assert meta["total_count"] == 0


# ======================================================================
# Enforcement docket and hearing refusals
# ======================================================================
def test_a_third_case_for_one_unit_on_one_docket_is_refused(api):
    """Capacity is free, the slot is free, and the per-unit cap still bites.

    The docket holds two of its six slots and 11:00 is unclaimed, so neither the
    capacity rung nor the slot-collision rung can answer; the refusal is the
    per-unit limit alone, and the meeting's slot count must stay at two.

    PRD 3.8: "From `NOTICE_SENT` the requirements are: the case is
    `NOTICE_SENT`; the logical clock is **strictly after** `cure_deadline_at`,
    since the deadline instant itself still belongs to the owner and a hearing
    docketed at or before it is refused with `ERR_CURE_PERIOD_ACTIVE`; the target
    meeting's `status` is `SCHEDULED` or `NOTICED` and its `agenda_kinds`
    contains `HEARING`, failing which the response is `ERR_AGENDA_KIND_MISSING`;
    the meeting's `hearing_slot_count` is strictly below
    `hearing_docket_capacity`, failing which the response is
    `ERR_HEARING_DOCKET_FULL`; `hearing_slot_start` sits on a thirty-minute
    boundary and the whole thirty-minute slot lies inside the meeting's window,
    which is inclusive of `scheduled_start` and exclusive of `scheduled_end`,
    failing which the response is `ERR_SLOT_OUTSIDE_MEETING`; no other case
    docketed to that meeting occupies the half-open thirty-minute slot beginning
    at `hearing_slot_start`, failing which the response is
    `ERR_HEARING_SLOT_TAKEN`; and at most one other case for the same `unit_id`
    is already docketed to that meeting, so a third case for one unit on one
    docket is refused with `ERR_UNIT_DOCKET_LIMIT`."
    PRD 3.8: "The side effects are that `hearing_meeting_id` and
    `hearing_slot_start` are written, `hearing_round` is set to 1, the meeting's
    `hearing_slot_count` rises by 1 with `BoardMeeting.version` advancing by 1,
    and `ViolationCase.version` advances by 1."

    Design: Corner/errors/third_case_for_one_unit_at_one_meeting_returns_unit_docket_limit
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx)
    _seat_director(ctx, "d2", full_name="Rita Vance", email="rita@example.test")
    meeting_id = schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-08-20T10:00:00Z", "2026-08-20T12:00:00Z"
    )
    cases = [
        notice_violation_case(ctx, "101", rule_code=rule_code, reporter_label="d2")
        for rule_code in ("R-14-PETS", "R-22-NOISE", "R-31-PARKING")
    ]

    set_clock(api, "2026-08-16T00:00:00Z")
    docket_hearing(ctx, cases[0]["id"], "mtg1", "2026-08-20T10:00:00Z")
    docket_hearing(ctx, cases[1]["id"], "mtg1", "2026-08-20T10:30:00Z")

    validate_error(
        api.schedule_hearing(
            cases[2]["id"],
            {
                "hearing_meeting_id": meeting_id,
                "hearing_slot_start": "2026-08-20T11:00:00Z",
            },
            ctx.director("d1"),
        ),
        "ERR_UNIT_DOCKET_LIMIT",
        409,
    )

    assert read_meeting(api, meeting_id, MANAGER_HEADERS)["hearing_slot_count"] == 2
    turned_away = read_case(api, cases[2]["id"], MANAGER_HEADERS)
    assert turned_away["status"] == "NOTICE_SENT"
    assert turned_away["hearing_meeting_id"] is None
    assert turned_away["hearing_round"] == 0


def test_deciding_a_hearing_before_the_meeting_convenes_is_refused(api):
    """Docketing onto a `SCHEDULED` meeting is legal; deciding at one is not.

    The case is properly docketed while the meeting is still `SCHEDULED`, so the
    only defect at decision time is the session state -- and because the session
    rung sits above the quorum rung, that is the identifier returned even though
    quorum is equally absent. No fine may be posted and no appeal clock started.

    PRD 3.8: "Every decision requires that the case be `HEARING_SCHEDULED`, that
    the hearing meeting's `status` be `IN_SESSION` with its `quorum_met` true --
    otherwise `ERR_MEETING_NOT_IN_SESSION` or `ERR_BOARD_QUORUM_NOT_MET` -- and
    that the acting director not be the reporter: the `X-User-ID` must differ
    from `reported_by_owner_id`, or the response is
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 2.9: "And because meeting session (rank 13) precedes quorum (rank 14), a
    decision recorded at a meeting that was never convened reports
    `ERR_MEETING_NOT_IN_SESSION` even though quorum is also absent."
    PRD 3.8: "The case is born with `status` `OPEN`, `hearing_round` 0,
    `fine_tier` 0, and `fine_amount_cents` 0; `prior_case_id`,
    `decision_owner_id`, `hearing_meeting_id`, `notice_sent_at`,
    `cure_deadline_at`, `hearing_slot_start`, `fine_entry_id`, and
    `appeal_deadline_at` are all null."

    Design: Corner/errors/hearing_decision_before_the_meeting_convenes_returns_meeting_not_in_session
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx)
    _seat_director(ctx, "d2", full_name="Rita Vance", email="rita@example.test")
    meeting_id = schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-08-20T10:00:00Z", "2026-08-20T12:00:00Z"
    )
    case = notice_violation_case(
        ctx, "101", rule_code="R-14-PETS", reporter_label="d2"
    )

    set_clock(api, "2026-08-16T00:00:00Z")
    docketed = docket_hearing(ctx, case["id"], "mtg1", "2026-08-20T10:00:00Z")
    assert docketed["status"] == "HEARING_SCHEDULED"
    assert read_meeting(api, meeting_id, MANAGER_HEADERS)["status"] == "SCHEDULED"

    validate_error(
        api.hearing_decision(case["id"], {"outcome": "FINE"}, ctx.director("d1")),
        "ERR_MEETING_NOT_IN_SESSION",
        409,
    )

    undecided = read_case(api, case["id"], MANAGER_HEADERS)
    assert undecided["status"] == "HEARING_SCHEDULED"
    assert undecided["fine_amount_cents"] == 0
    assert undecided["fine_tier"] == 0
    assert undecided["appeal_deadline_at"] is None
    assert undecided["fine_entry_id"] is None

    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"source_case_id": case["id"]})
    )
    assert meta["total_count"] == 0
    assert read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"] == 0


def test_appealing_one_second_past_the_deadline_is_refused(api):
    """The appeal gate is inclusive, so one second past it is one second too late.

    A fine assessed at 2026-09-01T10:00:00Z is appealable through exactly
    2026-10-01T10:00:00Z; at 2026-10-01T10:00:01Z the window is shut, the docket
    slot is *not* released, and the fine row stays owed.

    PRD 3.8: "The requirements are that the case be `FINE_ASSESSED`, that the
    logical clock be at or before `appeal_deadline_at` -- an appeal filed after
    the deadline instant is refused with `ERR_APPEAL_WINDOW_CLOSED` -- and that
    the acting `X-User-ID` be the `current_owner_id` of the cited unit, or
    `ERR_NOT_UNIT_OWNER` is returned."
    PRD 3.8: "The side effects release the docket slot: the former hearing
    meeting's `hearing_slot_count` falls by 1 with that `BoardMeeting.version`
    advancing by 1, `hearing_meeting_id` and `hearing_slot_start` are cleared to
    null, the `FINE` row stays `POSTED` so the fine remains owed throughout the
    appeal, and `ViolationCase.version` advances by 1."
    PRD 3.8: "It writes `fine_tier` and `fine_amount_cents` from the tier
    selection below, posts a `FINE` row in bucket `FINE` on the cited unit with a
    positive `amount_cents` equal to `fine_amount_cents` and `due_on` thirty days
    after the logical clock, stores that row's identifier in `fine_entry_id`,
    recomputes the unit's `balance_due_cents` and re-derives its
    `delinquency_stage` with `Unit.version` advancing by 1, sets
    `decision_owner_id` to the acting `X-User-ID`, sets `appeal_deadline_at` to
    the logical clock advanced by `appeal_window_days`, and advances
    `ViolationCase.version` by 1."

    Design: Corner/errors/appealing_one_second_after_the_deadline_returns_appeal_window_closed
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx)
    _seat_director(ctx, "d2", full_name="Rita Vance", email="rita@example.test")
    meeting_id = schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"
    )
    case = notice_violation_case(
        ctx, "101", rule_code="R-14-PETS", reporter_label="d2"
    )

    set_clock(api, "2026-08-16T00:00:00Z")
    docket_hearing(ctx, case["id"], "mtg1", "2026-09-01T10:00:00Z")
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-09-01T10:00:00Z")
    convene(ctx, "mtg1", attending=("d1",))
    fined = get_success_data(
        api.hearing_decision(case["id"], {"outcome": "FINE"}, ctx.director("d1"))
    )
    assert fined["fine_amount_cents"] == 5_000
    assert_instant_equals(fined["appeal_deadline_at"], "2026-10-01T10:00:00Z")

    set_clock(api, "2026-10-01T10:00:01Z")
    validate_error(
        api.appeal_case(
            case["id"],
            ctx.owner("o1"),
            payload={"grounds": "the dog is a service animal"},
        ),
        "ERR_APPEAL_WINDOW_CLOSED",
        409,
    )

    unappealed = read_case(api, case["id"], MANAGER_HEADERS)
    assert unappealed["status"] == "FINE_ASSESSED"
    assert_instant_equals(unappealed["appeal_deadline_at"], "2026-10-01T10:00:00Z")
    assert unappealed["hearing_round"] == 1
    assert unappealed["hearing_meeting_id"] == meeting_id
    assert read_meeting(api, meeting_id, MANAGER_HEADERS)["hearing_slot_count"] == 1

    fine_row = find_entry(
        fetch_ledger_entries(api, MANAGER_HEADERS, source_case_id=case["id"]),
        entry_type="FINE",
    )
    assert fine_row["status"] == "POSTED"
    assert fine_row["amount_cents"] == 5_000
    assert fine_row["bucket"] == "FINE"


# ======================================================================
# Optimistic concurrency and term validity
# ======================================================================
def test_a_certificate_request_on_a_stale_unit_version_is_refused_then_retried(api):
    """The guard is version-based, so the refreshed token succeeds unchanged.

    A charge posted between reading the unit and requesting the certificate bumps
    `Unit.version`, so the request carrying the old token is refused with a 412
    and no certificate row appears; resending the identical payload with the
    refreshed version is accepted.

    PRD 2.6: "Creating a resale-certificate request requires
    `expected_unit_version` in the request body, carrying the client's last
    observed `version` of the target `Unit`."
    PRD 2.6: "A mismatch against the unit's current `version` is rejected with
    `ERR_STALE_UNIT_VERSION` (HTTP 412)."
    PRD 3.1: "Posting a charge recomputes the unit's `balance_due_cents`,
    re-derives its `delinquency_stage`, and advances `Unit.version` by 1."
    PRD 3.9: "The certificate is born with `status` `REQUESTED` and with
    `ledger_balance_cents`, `projected_payoff_cents`, `proration_credit_cents`,
    `open_violation_count`, and `special_assessment_disclosure_cents` at 0,
    `disclosed_claim_ids` empty, `requires_reissue` false, and
    `pinned_budget_id`, `pinned_unit_version`, `pinned_budget_version`,
    `cert_fee_entry_id`, `issued_at`, and `expires_at` all null."

    Design: Corner/errors/certificate_request_with_a_stale_unit_version_returns_stale_unit_version
    """
    ctx = _owner_and_unit(api)
    stale_version = ctx.unit_version("101")
    get_success_data(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="ASSESSMENT",
                amount_cents=20_000,
                due_on="2026-08-15T00:00:00Z",
                effective_period="2026-08",
                memo="August assessment",
            ),
            MANAGER_HEADERS,
        )
    )
    assert ctx.unit_version("101") == stale_version + 1

    stale_payload = resale_certificate_payload(
        "TA-0001", stale_version, closing_date="2026-11-16T00:00:00Z"
    )
    validate_error(
        api.request_resale_certificate(
            ctx.units["101"], stale_payload, TITLE_AGENT_HEADERS
        ),
        "ERR_STALE_UNIT_VERSION",
        412,
    )
    _certs, meta = validate_paginated(
        api.list_resale_certificates(
            MANAGER_HEADERS, params={"unit_id": ctx.units["101"]}
        )
    )
    assert meta["total_count"] == 0

    fresh_payload = resale_certificate_payload(
        "TA-0001", ctx.unit_version("101"), closing_date="2026-11-16T00:00:00Z"
    )
    accepted = validate_success(
        api.request_resale_certificate(
            ctx.units["101"], fresh_payload, TITLE_AGENT_HEADERS
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED"
    assert accepted["issued_at"] is None


def test_submitting_a_zero_length_contract_term_is_refused(api):
    """A draft may hold a degenerate term; submission is where the term is tested.

    Identical `effective_from` and `effective_to` survive creation and fail the
    strictly-before test at submit time, leaving the row in `DRAFT` with nothing
    encumbered and nothing pinned.

    PRD 3.6: "Three term conditions apply: `effective_from` must be strictly
    before `effective_to`, and `insurance_cert_expires_at` must be at or after
    `effective_to` so that the certificate covers the whole term -- either
    failure yields `ERR_CONTRACT_TERM_INVALID` -- and the covered element's
    `status` must not be `DECOMMISSIONED`, failing which the response is
    `ERR_ELEMENT_NOT_SERVICEABLE`."
    PRD 3.6: "`approval_yes_count` starts at 0, `pinned_element_version` is null
    until the board awards, and `suspension_reason` is an enum over `NONE`,
    `INSURANCE_LAPSED`, `PERFORMANCE`, and `ELEMENT_SPEC_CHANGED` defaulting to
    `NONE`."
    PRD 3.6: "Contract `status` runs through `DRAFT`, `PENDING_APPROVAL`,
    `APPROVED`, `ACTIVE`, `SUSPENDED`, `TERMINATED`, and `EXPIRED`, starting at
    `DRAFT`, with `TERMINATED` and `EXPIRED` terminal."

    Design: Corner/errors/submitting_a_zero_length_contract_term_returns_contract_term_invalid
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_element(
        ctx,
        "el1",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=12_000_000,
        useful_life_years=40,
        effective_age_years=5,
    )
    contract_id = add_contract(
        ctx,
        "ct1",
        "el1",
        vendor_name="Ridgeline Roofing",
        contract_cap_cents=1_000_000,
        insurance_cert_expires_at="2027-06-30T00:00:00Z",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )

    validate_error(
        api.submit_contract(contract_id, MANAGER_HEADERS),
        "ERR_CONTRACT_TERM_INVALID",
        422,
    )

    unsubmitted = read_contract(api, contract_id, MANAGER_HEADERS)
    assert unsubmitted["status"] == "DRAFT"
    assert unsubmitted["committed_cents"] == 0
    assert unsubmitted["invoiced_cents"] == 0
    assert unsubmitted["pinned_element_version"] is None
    assert unsubmitted["approval_yes_count"] == 0
    assert unsubmitted["suspension_reason"] == "NONE"
