"""State graphs that are not straight lines.

A budget re-enters a state it already occupied and adopts on the second pass; a
special assessment advances one of its two independent dimensions while the
other stays frozen.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant_equals,
    bucket_totals,
    read_budget,
    read_special_assessment,
)
from test_helpers.factories import (
    installment_payload,
    owner_ballot_payload,
    payment_payload,
    special_assessment_payload,
)
from test_helpers.fixtures import (
    add_owner,
    add_unit,
    convene,
    create_association,
    draft_budget,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS


# ======================================================================
# The budget revision cycle
# ======================================================================
def _two_unit_board(api: ApiClient):
    """Three seated directors plus two owners holding 6000 and 4000 bp."""
    ctx = create_association(api, legal_name="Ridgeline Condominium Association")
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "o1", full_name="Owner One")
    add_owner(ctx, "o2", full_name="Owner Two")
    add_unit(ctx, "601", "o1", 6000, 1400)
    add_unit(ctx, "602", "o2", 4000, 900)
    return ctx


def _budget_noticed_with_one_no_ballot(ctx):
    """Take a budget to NOTICED against mtg1 and let the 6000 bp owner vote NO."""
    mtg1 = schedule_meeting(
        ctx,
        "mtg1",
        ["BUDGET_RATIFICATION"],
        "2026-09-05T18:00:00Z",
        "2026-09-05T21:00:00Z",
    )
    schedule_meeting(
        ctx,
        "mtg2",
        ["BUDGET_RATIFICATION"],
        "2026-11-01T18:00:00Z",
        "2026-11-01T21:00:00Z",
    )
    budget = draft_budget(
        ctx,
        fiscal_year=2026,
        operating_total_cents=12_000_000,
        reserve_contribution_cents=1_200_000,
        ratification_meeting_id=mtg1,
    )
    get_success_data(
        ctx.api.propose_budget(
            budget["id"], MANAGER_HEADERS, payload={"ratification_meeting_id": mtg1}
        )
    )
    get_success_data(ctx.api.send_budget_notice(budget["id"], MANAGER_HEADERS))
    no_ballot = get_success_data(
        ctx.api.cast_vote(
            owner_ballot_payload(
                ctx.association_id,
                "BUDGET",
                budget["id"],
                ctx.owners["o1"],
                ctx.units["601"],
                choice="NO",
            ),
            ctx.owner("o1"),
        )
    )
    set_clock(ctx.api, "2026-09-05T18:00:00Z")
    convene(ctx, "mtg1", ("d1", "d2", "tr"))
    return budget, no_ballot


def test_budget_veto_weight_at_the_threshold_rejects_without_allocating(
    api: ApiClient,
) -> None:
    """A 6000 bp NO clears the 5000 bp veto bar, and the REJECTED branch is inert.

    PRD 3.2: "On `NOTICED → REJECTED`, the server writes `no_weight_bp` from the
    tally, does **not** touch any unit's `monthly_assessment_cents`, leaves
    `allocation_snapshot` empty, voids no certificate, and advances
    `Budget.version` by 1."

    Design: Difficulty/non_linear_state_machine/budget_revision_cycle_draft_proposed_noticed_rejected_draft_then_adopts
    """
    ctx = _two_unit_board(api)
    budget, _ = _budget_noticed_with_one_no_ballot(ctx)

    rejected = get_success_data(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))

    assert rejected["status"] == "REJECTED"
    assert rejected["no_weight_bp"] == 6000
    assert rejected["allocation_snapshot"] == []
    assert ctx.unit("601")["monthly_assessment_cents"] == 0
    assert ctx.unit("602")["monthly_assessment_cents"] == 0


def test_return_to_draft_from_rejected_rewinds_the_notice_and_the_tally(
    api: ApiClient,
) -> None:
    """The REJECTED leg clears the notice, zeroes the veto weight, uncounts ballots.

    PRD 3.2: "From `REJECTED → DRAFT` the budget must be `REJECTED`; the effects
    are that `revision_round` rises by 1, `notice_sent_at` is cleared to null,
    `no_weight_bp` is reset to 0, every `BUDGET` vote on this budget has
    `counted` set to false, and `Budget.version` rises by 1."

    Design: Difficulty/non_linear_state_machine/budget_revision_cycle_draft_proposed_noticed_rejected_draft_then_adopts
    """
    ctx = _two_unit_board(api)
    budget, no_ballot = _budget_noticed_with_one_no_ballot(ctx)
    get_success_data(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))

    redrafted = get_success_data(
        ctx.api.return_budget_to_draft(
            budget["id"],
            ctx.director("d2"),
            payload={"reason": "board reworks the reserve line"},
        )
    )

    assert redrafted["status"] == "DRAFT"
    assert redrafted["revision_round"] == 1
    assert redrafted["notice_sent_at"] is None
    assert redrafted["no_weight_bp"] == 0

    votes, _ = validate_paginated(
        api.list_votes(MANAGER_HEADERS, params={"subject_id": budget["id"], "limit": 50})
    )
    stored = next(vote for vote in votes if vote["id"] == no_ballot["id"])
    assert stored["counted"] is False
    assert stored["choice"] == "NO"


def test_budget_re_enters_noticed_against_a_second_ratification_meeting(
    api: ApiClient,
) -> None:
    """The same row walks back through PROPOSED into NOTICED, notice re-stamped.

    PRD 3.2: "The cycle is genuinely cyclic: a board may push a budget back to
    `DRAFT` from `PROPOSED`, from `NOTICED`, or from `REJECTED`, and each return
    increments `revision_round`, which starts at 0."

    Design: Difficulty/non_linear_state_machine/budget_revision_cycle_draft_proposed_noticed_rejected_draft_then_adopts
    """
    ctx = _two_unit_board(api)
    budget, _ = _budget_noticed_with_one_no_ballot(ctx)
    get_success_data(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))
    get_success_data(
        ctx.api.return_budget_to_draft(budget["id"], ctx.director("d2"), payload={})
    )

    get_success_data(
        ctx.api.propose_budget(
            budget["id"],
            MANAGER_HEADERS,
            payload={"ratification_meeting_id": ctx.meetings["mtg2"]},
        )
    )
    renoticed = get_success_data(ctx.api.send_budget_notice(budget["id"], MANAGER_HEADERS))

    assert renoticed["status"] == "NOTICED"
    assert renoticed["ratification_meeting_id"] == ctx.meetings["mtg2"]
    assert_instant_equals(renoticed["notice_sent_at"], "2026-09-05T18:00:00Z")
    assert renoticed["revision_round"] == 1


def test_ballots_cast_before_the_re_mailed_notice_cannot_veto_the_second_round(
    api: ApiClient,
) -> None:
    """The uncounted round-one NO leaves the second tally at zero, so it adopts.

    PRD 3.2: "Ballots cast before the notice, or before the notice was re-mailed
    after a return-to-draft, are excluded, because their `counted` flag was
    cleared."

    Design: Difficulty/non_linear_state_machine/budget_revision_cycle_draft_proposed_noticed_rejected_draft_then_adopts
    """
    ctx = _two_unit_board(api)
    budget, _ = _budget_noticed_with_one_no_ballot(ctx)
    get_success_data(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))
    get_success_data(
        ctx.api.return_budget_to_draft(budget["id"], ctx.director("d2"), payload={})
    )
    get_success_data(
        ctx.api.propose_budget(
            budget["id"],
            MANAGER_HEADERS,
            payload={"ratification_meeting_id": ctx.meetings["mtg2"]},
        )
    )
    get_success_data(ctx.api.send_budget_notice(budget["id"], MANAGER_HEADERS))
    set_clock(api, "2026-11-01T18:00:00Z")
    convene(ctx, "mtg2", ("d1", "d2", "tr"))

    adopted = get_success_data(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))

    assert adopted["status"] == "ADOPTED"
    assert adopted["no_weight_bp"] == 0
    assert adopted["revision_round"] == 1
    assert_instant_equals(adopted["adopted_at"], "2026-11-01T18:00:00Z")


def test_second_pass_adoption_allocates_the_pool_across_both_units(
    api: ApiClient,
) -> None:
    """Only the adopting pass mints per-unit assessments.

    PRD 3.2: "Hop one computes the allocation snapshot and writes every unit's
    `monthly_assessment_cents`, advancing each `Unit.version` by 1."

    The pool round_half_up(13200000 / 12) == 1100000 splits 6000/4000 with no
    drift, giving 660000 and 440000.

    Design: Difficulty/non_linear_state_machine/budget_revision_cycle_draft_proposed_noticed_rejected_draft_then_adopts
    """
    ctx = _two_unit_board(api)
    budget, _ = _budget_noticed_with_one_no_ballot(ctx)
    get_success_data(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))
    get_success_data(
        ctx.api.return_budget_to_draft(budget["id"], ctx.director("d2"), payload={})
    )
    get_success_data(
        ctx.api.propose_budget(
            budget["id"],
            MANAGER_HEADERS,
            payload={"ratification_meeting_id": ctx.meetings["mtg2"]},
        )
    )
    get_success_data(ctx.api.send_budget_notice(budget["id"], MANAGER_HEADERS))
    set_clock(api, "2026-11-01T18:00:00Z")
    convene(ctx, "mtg2", ("d1", "d2", "tr"))
    get_success_data(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))

    assert ctx.unit("601")["monthly_assessment_cents"] == 660_000
    assert ctx.unit("602")["monthly_assessment_cents"] == 440_000
    assert read_budget(api, budget["id"], MANAGER_HEADERS)["status"] == "ADOPTED"


# ======================================================================
# Special assessment: two dimensions on one row
# ======================================================================
def _approved_assessment(api: ApiClient):
    """A 1000000 assessment in two rounds, approved unanimously, nothing collected."""
    ctx = create_association(api, legal_name="Cedar Mill Condominium Association")
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "o1", full_name="Owner One")
    add_owner(ctx, "o2", full_name="Owner Two")
    add_unit(ctx, "701", "o1", 6000, 1400)
    add_unit(ctx, "702", "o2", 4000, 900)
    assessment = get_success_data(
        ctx.api.create_special_assessment(
            ctx.association_id,
            special_assessment_payload(
                ctx.association_version(),
                purpose="Elevator modernization",
                total_amount_cents=1_000_000,
                installment_count=2,
            ),
            ctx.treasurer(),
        )
    )
    get_success_data(ctx.api.open_ballot(assessment["id"], ctx.director("d1")))
    for owner_label, unit_label in (("o1", "701"), ("o2", "702")):
        get_success_data(
            ctx.api.cast_vote(
                owner_ballot_payload(
                    ctx.association_id,
                    "SPECIAL_ASSESSMENT",
                    assessment["id"],
                    ctx.owners[owner_label],
                    ctx.units[unit_label],
                    choice="YES",
                ),
                ctx.owner(owner_label),
            )
        )
    closed = get_success_data(ctx.api.close_ballot(assessment["id"], ctx.director("d1")))
    return ctx, closed


def test_approval_leaves_the_funding_dimension_untouched(api: ApiClient) -> None:
    """Approval designates reserve cents but collects nothing.

    PRD 3.4: "On `BALLOTING → APPROVED`, the server writes `eligible_weight_bp`,
    `yes_weight_bp`, and `ballot_closed_at` from the logical clock, increases the
    association's `reserve_designated_cents` by `total_amount_cents` and advances
    `Association.version` by 1, leaves `funding_status` untouched at `UNFUNDED`,
    and advances `SpecialAssessment.version` by 1."

    Design: Difficulty/non_linear_state_machine/special_assessment_parallel_dimensions_funding_advances_while_approval_frozen
    """
    ctx, assessment = _approved_assessment(api)

    assert assessment["approval_status"] == "APPROVED"
    assert assessment["yes_weight_bp"] == 10_000
    assert assessment["eligible_weight_bp"] == 10_000
    assert assessment["funding_status"] == "UNFUNDED"
    association = ctx.association()
    assert association["reserve_designated_cents"] == 1_000_000
    assert association["restricted_sa_cash_cents"] == 0


def test_installment_rounds_use_the_pool_then_the_exact_remainder(
    api: ApiClient,
) -> None:
    """Round one divides and rounds; the final round takes whatever is left.

    PRD 3.4: "Each round reuses the same allocator as budget adoption, with one
    difference: the pool for rounds one through `installment_count` minus one is
    `total_amount_cents` divided by `installment_count` and rounded half up,
    while the **final** round instead uses `total_amount_cents` minus the sum of
    the pools already posted, so that the posted installments sum to
    `total_amount_cents` exactly with no drift."

    Design: Difficulty/non_linear_state_machine/special_assessment_parallel_dimensions_funding_advances_while_approval_frozen
    """
    ctx, assessment = _approved_assessment(api)

    get_success_data(
        ctx.api.post_installment(
            assessment["id"],
            installment_payload(due_on="2026-09-10T00:00:00Z", effective_period="2026-09"),
            ctx.treasurer(),
        )
    )
    round_one = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert round_one["installments_posted"] == 1
    assert ctx.unit("701")["balance_due_cents"] == 300_000
    assert ctx.unit("702")["balance_due_cents"] == 200_000

    get_success_data(
        ctx.api.post_installment(
            assessment["id"],
            installment_payload(due_on="2026-10-10T00:00:00Z", effective_period="2026-10"),
            ctx.treasurer(),
        )
    )
    round_two = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert round_two["installments_posted"] == 2
    assert round_two["charged_cents"] == 1_000_000
    assert ctx.unit("701")["balance_due_cents"] == 600_000
    assert ctx.unit("702")["balance_due_cents"] == 400_000


def test_partial_collection_moves_only_the_funding_dimension(api: ApiClient) -> None:
    """Cash arriving advances funding_status and restricted cash, nothing else.

    PRD 3.4: "When a payment waterfall credits `SPECIAL_ASSESSMENT`-bucket rows
    of an approved assessment and the resulting `collected_cents` is greater than
    0 but strictly less than `total_amount_cents`, `funding_status` moves
    `UNFUNDED → PARTIALLY_COLLECTED`, the association's
    `restricted_sa_cash_cents` rises by the applied cents with
    `Association.version` advancing by 1, and `SpecialAssessment.version`
    advances by 1."

    Design: Difficulty/non_linear_state_machine/special_assessment_parallel_dimensions_funding_advances_while_approval_frozen
    """
    ctx, assessment = _approved_assessment(api)
    get_success_data(
        ctx.api.post_installment(
            assessment["id"],
            installment_payload(due_on="2026-09-10T00:00:00Z", effective_period="2026-09"),
            ctx.treasurer(),
        )
    )

    get_success_data(
        ctx.api.create_payment(
            ctx.units["701"],
            payment_payload(300_000, effective_period="2026-09", memo="SA round 1"),
            ctx.owner("o1"),
        )
    )

    partial = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert partial["funding_status"] == "PARTIALLY_COLLECTED"
    assert partial["collected_cents"] == 300_000
    assert partial["approval_status"] == "APPROVED"
    association = ctx.association()
    assert association["restricted_sa_cash_cents"] == 300_000
    assert association["reserve_designated_cents"] == 1_000_000


def test_full_collection_freezes_approval_while_funding_completes(
    api: ApiClient,
) -> None:
    """Four ledger-moving requests later, approval_status has never been rewritten.

    PRD 3.4: "Collection progresses without touching `approval_status`, and only
    rescission moves both."

    PRD 3.4: "When a later payment brings `collected_cents` to
    `total_amount_cents` or beyond, `funding_status` moves
    `PARTIALLY_COLLECTED → FULLY_COLLECTED` with the same cash and version
    effects."

    Design: Difficulty/non_linear_state_machine/special_assessment_parallel_dimensions_funding_advances_while_approval_frozen
    """
    ctx, assessment = _approved_assessment(api)
    approval_readings = [assessment["approval_status"]]

    def record() -> None:
        approval_readings.append(
            read_special_assessment(api, assessment["id"], MANAGER_HEADERS)[
                "approval_status"
            ]
        )

    get_success_data(
        ctx.api.post_installment(
            assessment["id"],
            installment_payload(due_on="2026-09-10T00:00:00Z", effective_period="2026-09"),
            ctx.treasurer(),
        )
    )
    record()
    get_success_data(
        ctx.api.create_payment(
            ctx.units["701"],
            payment_payload(300_000, effective_period="2026-09", memo="SA round 1"),
            ctx.owner("o1"),
        )
    )
    record()
    get_success_data(
        ctx.api.post_installment(
            assessment["id"],
            installment_payload(due_on="2026-10-10T00:00:00Z", effective_period="2026-10"),
            ctx.treasurer(),
        )
    )
    record()
    get_success_data(
        ctx.api.create_payment(
            ctx.units["701"],
            payment_payload(300_000, effective_period="2026-10", memo="SA round 2"),
            ctx.owner("o1"),
        )
    )
    record()
    get_success_data(
        ctx.api.create_payment(
            ctx.units["702"],
            payment_payload(400_000, effective_period="2026-10", memo="SA rounds 1 and 2"),
            ctx.owner("o2"),
        )
    )
    record()

    final = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert final["collected_cents"] == 1_000_000
    assert final["funding_status"] == "FULLY_COLLECTED"
    assert set(approval_readings) == {"APPROVED"}

    association = ctx.association()
    assert association["restricted_sa_cash_cents"] == 1_000_000
    assert association["reserve_designated_cents"] == 1_000_000

    for label in ("701", "702"):
        unit = ctx.unit(label)
        assert unit["balance_due_cents"] == 0
        assert unit["delinquency_stage"] == "CURRENT"


def test_special_assessment_payments_apply_entirely_to_the_assessment_bucket(
    api: ApiClient,
) -> None:
    """With no other open charges the whole payment lands on SPECIAL_ASSESSMENT.

    PRD 3.1: "For each charge visited, the amount taken is the lesser of the
    amount still remaining and that charge's remaining capacity; the charge's
    `applied_cents` grows by the amount taken, an entry recording the `bucket`,
    the `target_entry_id`, and the `applied_cents` taken is appended in visit
    order to the payment's `applied_allocations` array, and the remaining amount
    falls by the same figure."

    Design: Difficulty/non_linear_state_machine/special_assessment_parallel_dimensions_funding_advances_while_approval_frozen
    """
    ctx, assessment = _approved_assessment(api)
    get_success_data(
        ctx.api.post_installment(
            assessment["id"],
            installment_payload(due_on="2026-09-10T00:00:00Z", effective_period="2026-09"),
            ctx.treasurer(),
        )
    )

    payment = get_success_data(
        ctx.api.create_payment(
            ctx.units["701"],
            payment_payload(300_000, effective_period="2026-09", memo="SA round 1"),
            ctx.owner("o1"),
        )
    )

    assert payment["amount_cents"] == -300_000
    assert payment["unapplied_cents"] == 0
    assert payment["bucket"] == "NONE"
    assert [row["bucket"] for row in payment["applied_allocations"]] == [
        "SPECIAL_ASSESSMENT"
    ]
    assert bucket_totals(ctx.ledger("701"))["SPECIAL_ASSESSMENT"] == 300_000
