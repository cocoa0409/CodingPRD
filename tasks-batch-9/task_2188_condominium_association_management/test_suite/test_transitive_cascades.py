"""Cascades whose later hops are caused by earlier hops, not by the request.

Budget adoption reaches five hops deep, from unit allocations all the way to a
balloting assessment's eligible weight; a litigation tender reaches two, and the
second hop is attributable to the first because an operator void does not fire
it.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant_equals,
    assert_unit_ledger_conserved,
    find_entry,
    read_certificate,
    read_claim,
    read_special_assessment,
)
from test_helpers.factories import special_assessment_payload
from test_helpers.fixtures import (
    add_element,
    add_owner,
    add_unit,
    adjust_claim,
    convene,
    create_association,
    draft_budget,
    issue_certificate,
    patch_association,
    post_charge,
    report_claim,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import ADJUSTER_HEADERS, ATTORNEY_HEADERS, MANAGER_HEADERS


# ======================================================================
# Five hops from a budget ratification
# ======================================================================
def _five_hop_world(api: ApiClient):
    """A lien-filed unit with an issued certificate and a live ballot open.

    Returns the context, the FY2027 budget awaiting ratification, the collection
    cost entry and the issued certificate.
    """
    ctx = create_association(api, legal_name="Stonegate Condominium Association")
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "o1", full_name="Owner One")
    add_owner(ctx, "o2", full_name="Owner Two")
    add_unit(ctx, "801", "o1", 6000, 1500)
    add_unit(ctx, "802", "o2", 4000, 1000)
    mtg1 = schedule_meeting(
        ctx, "mtg1", ["BUDGET_RATIFICATION"], "2026-09-05T18:00:00Z", "2026-09-05T21:00:00Z"
    )
    mtg2 = schedule_meeting(
        ctx, "mtg2", ["BUDGET_RATIFICATION"], "2026-10-20T18:00:00Z", "2026-10-20T21:00:00Z"
    )

    budget_2026 = draft_budget(
        ctx,
        fiscal_year=2026,
        operating_total_cents=12_000_000,
        reserve_contribution_cents=1_200_000,
        ratification_meeting_id=mtg1,
    )
    get_success_data(
        ctx.api.propose_budget(
            budget_2026["id"], MANAGER_HEADERS, payload={"ratification_meeting_id": mtg1}
        )
    )
    get_success_data(ctx.api.send_budget_notice(budget_2026["id"], MANAGER_HEADERS))
    set_clock(api, "2026-09-05T18:00:00Z")
    convene(ctx, "mtg1", ("d1", "d2", "tr"))
    get_success_data(ctx.api.ratify_budget(budget_2026["id"], ctx.director("d1")))

    assessment = get_success_data(
        ctx.api.create_special_assessment(
            ctx.association_id,
            special_assessment_payload(
                ctx.association_version(),
                purpose="Garage deck waterproofing",
                total_amount_cents=800_000,
                installment_count=4,
            ),
            ctx.treasurer(),
        )
    )
    get_success_data(ctx.api.open_ballot(assessment["id"], ctx.director("d1")))

    budget_2027 = draft_budget(
        ctx,
        fiscal_year=2027,
        operating_total_cents=13_000_000,
        reserve_contribution_cents=1_300_000,
        ratification_meeting_id=mtg2,
    )
    get_success_data(
        ctx.api.propose_budget(
            budget_2027["id"], MANAGER_HEADERS, payload={"ratification_meeting_id": mtg2}
        )
    )
    get_success_data(ctx.api.send_budget_notice(budget_2027["id"], MANAGER_HEADERS))

    set_clock(api, "2026-10-18T00:00:00Z")
    collection_cost = post_charge(
        ctx,
        "801",
        entry_type="COLLECTION_COST",
        amount_cents=165_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="collection costs advanced",
    )
    certificate = issue_certificate(
        ctx,
        "801",
        closing_date="2026-11-08T00:00:00Z",
        payoff_basis="LEDGER_BALANCE",
        requesting_agent_id="TA-CASCADE",
    )

    set_clock(api, "2026-10-20T18:00:00Z")
    convene(ctx, "mtg2", ("d1", "d2", "tr"))
    return ctx, budget_2027, collection_cost, certificate, assessment


def test_lien_filed_unit_pre_trigger_baseline_holds_before_the_cascade(
    api: ApiClient,
) -> None:
    """The 200-day-old 200000 balance is on the lien rung with eligibility lost.

    PRD 3.1: "Rule 3: if `oldest_unpaid_age_days` is at least 90 and
    `balance_due_cents` is at least `lien_threshold_cents`, the posture is
    `LIEN_FILED`."

    Design: Difficulty/transitive_cascade/budget_adoption_five_hop_cascade_reaches_balloting_eligible_weight
    """
    ctx, _, _, _, assessment = _five_hop_world(api)

    unit = ctx.unit("801")
    assert unit["balance_due_cents"] == 200_000
    assert unit["delinquency_stage"] == "LIEN_FILED"
    assert unit["voting_eligible"] is False
    assert_instant_equals(unit["lien_recorded_at"], "2026-10-18T00:00:00Z")
    assert (
        read_special_assessment(api, assessment["id"], MANAGER_HEADERS)[
            "eligible_weight_bp"
        ]
        == 4000
    )


def test_hop_one_adoption_rewrites_every_units_monthly_assessment(
    api: ApiClient,
) -> None:
    """The FY2027 pool replaces the FY2026 per-unit figures.

    PRD 3.2: "Hop one computes the allocation snapshot and writes every unit's
    `monthly_assessment_cents`, advancing each `Unit.version` by 1."

    round_half_up(14300000 / 12) == 1191667 splits into 715000 and 476667, up
    from the FY2026 figures of 660000 and 440000.

    Design: Difficulty/transitive_cascade/budget_adoption_five_hop_cascade_reaches_balloting_eligible_weight
    """
    ctx, budget_2027, _, _, _ = _five_hop_world(api)
    assert ctx.unit("801")["monthly_assessment_cents"] == 660_000

    adopted = get_success_data(
        ctx.api.ratify_budget(budget_2027["id"], ctx.director("d1"))
    )

    assert adopted["status"] == "ADOPTED"
    assert adopted["no_weight_bp"] == 0
    assert adopted["monthly_assessable_cents"] == 1_191_667
    assert ctx.unit("801")["monthly_assessment_cents"] == 715_000
    assert ctx.unit("802")["monthly_assessment_cents"] == 476_667


def test_hop_two_voids_the_certificate_pinned_to_the_older_budget(
    api: ApiClient,
) -> None:
    """The certificate is voided because the figures it printed moved.

    PRD 3.2: "Hop two: because those figures changed, every resale certificate
    of those units whose `status` is `ISSUED` and whose `pinned_budget_id` is not
    this budget becomes `VOIDED` with `requires_reissue` set to true."

    Design: Difficulty/transitive_cascade/budget_adoption_five_hop_cascade_reaches_balloting_eligible_weight
    """
    ctx, budget_2027, _, certificate, _ = _five_hop_world(api)
    assert certificate["status"] == "ISSUED"
    assert certificate["pinned_budget_id"] != budget_2027["id"]

    get_success_data(ctx.api.ratify_budget(budget_2027["id"], ctx.director("d1")))

    voided = read_certificate(api, certificate["id"], MANAGER_HEADERS)
    assert voided["status"] == "VOIDED"
    assert voided["requires_reissue"] is True


def test_hop_three_reverses_the_fee_of_the_cascade_voided_certificate(
    api: ApiClient,
) -> None:
    """A cascade void refunds the fee with a REVERSAL, unlike an operator void.

    PRD 3.2: "Hop three: because those certificates were voided by cascade rather
    than by an operator, a `REVERSAL` row of the negated certificate fee is
    posted against each certificate's `cert_fee_entry_id`, that row's `status`
    becomes `REVERSED`, and each affected unit's `balance_due_cents` is
    recomputed."

    Design: Difficulty/transitive_cascade/budget_adoption_five_hop_cascade_reaches_balloting_eligible_weight
    """
    ctx, budget_2027, _, certificate, _ = _five_hop_world(api)
    fee_entry_id = certificate["cert_fee_entry_id"]

    get_success_data(ctx.api.ratify_budget(budget_2027["id"], ctx.director("d1")))

    rows = ctx.ledger("801")
    fee = find_entry(rows, id=fee_entry_id)
    reversal = find_entry(rows, entry_type="REVERSAL")
    assert fee["status"] == "REVERSED"
    assert reversal["reverses_entry_id"] == fee_entry_id
    assert reversal["amount_cents"] == -35_000
    assert reversal["status"] == "POSTED"


def test_hop_four_de_escalates_the_ladder_and_restores_eligibility(
    api: ApiClient,
) -> None:
    """The refunded fee drops the balance below the lien threshold.

    PRD 3.2: "Hop four: because balances fell, each affected unit's
    `delinquency_stage` is re-derived through the ladder, and a unit leaving
    `LIEN_FILED` clears `lien_recorded_at` and flips `voting_eligible` to true."

    Design: Difficulty/transitive_cascade/budget_adoption_five_hop_cascade_reaches_balloting_eligible_weight
    """
    ctx, budget_2027, _, _, _ = _five_hop_world(api)

    get_success_data(ctx.api.ratify_budget(budget_2027["id"], ctx.director("d1")))

    unit = ctx.unit("801")
    assert unit["balance_due_cents"] == 165_000
    assert unit["delinquency_stage"] == "LATE_NOTICE"
    assert unit["lien_recorded_at"] is None
    assert unit["voting_eligible"] is True
    assert unit["transfer_blocked"] is True


def test_hop_five_recomputes_the_balloting_assessments_eligible_weight(
    api: ApiClient,
) -> None:
    """The restored eligibility reaches all the way into the open ballot.

    PRD 3.2: "Hop five: because a unit's `voting_eligible` flipped, every special
    assessment of the association whose `approval_status` is `BALLOTING`
    recomputes `eligible_weight_bp` and re-derives `counted` on its votes."

    Design: Difficulty/transitive_cascade/budget_adoption_five_hop_cascade_reaches_balloting_eligible_weight
    """
    ctx, budget_2027, _, _, assessment = _five_hop_world(api)

    get_success_data(ctx.api.ratify_budget(budget_2027["id"], ctx.director("d1")))

    reread = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert reread["approval_status"] == "BALLOTING"
    assert reread["eligible_weight_bp"] == 10_000


def test_five_hop_cascade_touches_only_the_certificate_fee_pair(
    api: ApiClient,
) -> None:
    """The unrelated collection cost survives, and the ledger still balances.

    PRD 3.1: "`balance_due_cents` is the signed sum of `amount_cents` over
    *every* ledger row of the unit, regardless of `status` -- a reversed pair
    nets to zero, so nothing is double counted."

    Design: Difficulty/transitive_cascade/budget_adoption_five_hop_cascade_reaches_balloting_eligible_weight
    """
    ctx, budget_2027, collection_cost, _, _ = _five_hop_world(api)

    get_success_data(ctx.api.ratify_budget(budget_2027["id"], ctx.director("d1")))

    rows = ctx.ledger("801")
    surviving = find_entry(rows, id=collection_cost["id"])
    assert surviving["status"] == "POSTED"
    assert surviving["amount_cents"] == 165_000
    assert len(rows) == 3
    signed_sum = assert_unit_ledger_conserved(api, ctx.units["801"], MANAGER_HEADERS)
    assert signed_sum == 165_000


# ======================================================================
# Two hops from a litigation tender
# ======================================================================
def _tender_world(api: ApiClient):
    """A defect claim adjusted to the association, and one issued certificate."""
    ctx = create_association(api, legal_name="Wexford Court Condominium Association")
    patch_association(ctx, operating_cash_cents=5_000_000)
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "o1", full_name="Owner One")
    add_owner(ctx, "o2", full_name="Owner Two")
    add_unit(ctx, "901", "o1", 6000, 1500)
    add_unit(ctx, "902", "o2", 4000, 1000)
    add_element(
        ctx,
        "garage",
        name="Parking Garage Deck",
        element_class="GARAGE",
        replacement_cost_cents=9_000_000,
        useful_life_years=30,
        effective_age_years=10,
    )
    mtg1 = schedule_meeting(
        ctx, "mtg1", ["BUDGET_RATIFICATION"], "2026-09-05T18:00:00Z", "2026-09-05T21:00:00Z"
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
    set_clock(api, "2026-09-05T18:00:00Z")
    convene(ctx, "mtg1", ("d1", "d2", "tr"))
    get_success_data(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))

    claim = report_claim(
        ctx,
        "901",
        "garage",
        loss_type="CONSTRUCTION_DEFECT",
        loss_at="2026-06-15T00:00:00Z",
        gross_damage_cents=4_800_000,
        within_unit_boundary_cents=400_000,
        affected_unit_ids=[ctx.units["901"]],
    )
    adjust_claim(ctx, claim["id"], "ASSOCIATION")

    set_clock(api, "2026-09-15T00:00:00Z")
    certificate = issue_certificate(
        ctx,
        "901",
        closing_date="2026-11-08T00:00:00Z",
        payoff_basis="LEDGER_BALANCE",
        requesting_agent_id="TA-TENDER",
    )
    return ctx, claim, certificate


def test_pre_tender_baseline_has_a_clean_certificate_and_no_disclosure(
    api: ApiClient,
) -> None:
    """Before the tender there is nothing to disclose and the fee is the only row.

    PRD 3.7: "`disclosure_required` is true exactly when `litigation_status` is
    `TENDERED` or `IN_LITIGATION`."

    Design: Difficulty/transitive_cascade/litigation_tender_two_hop_cascade_voids_certificate_and_reverses_fee
    """
    ctx, claim, certificate = _tender_world(api)

    assert certificate["status"] == "ISSUED"
    assert certificate["disclosed_claim_ids"] == []
    assert certificate["ledger_balance_cents"] == 35_000
    unit = ctx.unit("901")
    assert unit["balance_due_cents"] == 35_000
    assert unit["delinquency_stage"] == "CURRENT"
    assert unit["transfer_blocked"] is False
    assert read_claim(api, claim["id"], ADJUSTER_HEADERS)["disclosure_required"] is False


def test_tender_moves_the_litigation_dimension_alone(api: ApiClient) -> None:
    """The adjustment dimension and the absorbed cents are left exactly as they were.

    PRD 3.7: "The `litigation_status` dimension runs over `NONE`, `TENDERED`,
    `IN_LITIGATION`, and `RESOLVED`, starting at `NONE`, and evolves entirely
    independently -- a claim can be settled for adjustment purposes while its
    suit is still tendered, and a claim can be in litigation while its adjustment
    is denied."

    Design: Difficulty/transitive_cascade/litigation_tender_two_hop_cascade_voids_certificate_and_reverses_fee
    """
    ctx, claim, _ = _tender_world(api)

    tendered = validate_success(
        api.set_litigation_stage(claim["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS)
    )

    assert tendered["litigation_status"] == "TENDERED"
    assert tendered["disclosure_required"] is True
    assert tendered["adjustment_status"] == "ADJUSTED_ASSOCIATION"
    assert tendered["association_absorbed_cents"] == 1_000_000
    assert ctx.association()["operating_cash_cents"] == 4_000_000


def test_tender_hop_one_voids_the_already_printed_certificate(
    api: ApiClient,
) -> None:
    """A printed certificate cannot disclose a matter tendered afterwards.

    PRD 3.7: "It sets `disclosure_required` to true and then cascades: every
    resale certificate whose `status` is `ISSUED` and whose `unit_id` appears in
    `affected_unit_ids` becomes `VOIDED` with `requires_reissue` set to true,
    because an already-issued certificate cannot disclose a matter tendered after
    it was printed; each such certificate's `cert_fee_entry_id` is answered with a
    `REVERSAL` row, and the affected unit's `balance_due_cents` and
    `delinquency_stage` are recomputed with `Unit.version` advancing by 1."

    Design: Difficulty/transitive_cascade/litigation_tender_two_hop_cascade_voids_certificate_and_reverses_fee
    """
    ctx, claim, certificate = _tender_world(api)

    get_success_data(
        api.set_litigation_stage(claim["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS)
    )

    voided = read_certificate(api, certificate["id"], MANAGER_HEADERS)
    assert voided["status"] == "VOIDED"
    assert voided["requires_reissue"] is True


def test_tender_hop_two_reverses_the_fee_and_clears_the_balance(
    api: ApiClient,
) -> None:
    """The second hop fires only because the first was a cascade void.

    PRD 3.7: "each such certificate's `cert_fee_entry_id` is answered with a
    `REVERSAL` row, and the affected unit's `balance_due_cents` and
    `delinquency_stage` are recomputed with `Unit.version` advancing by 1."

    Design: Difficulty/transitive_cascade/litigation_tender_two_hop_cascade_voids_certificate_and_reverses_fee
    """
    ctx, claim, certificate = _tender_world(api)
    fee_entry_id = certificate["cert_fee_entry_id"]

    get_success_data(
        api.set_litigation_stage(claim["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS)
    )

    rows = ctx.ledger("901")
    assert find_entry(rows, id=fee_entry_id)["status"] == "REVERSED"
    reversal = find_entry(rows, entry_type="REVERSAL")
    assert reversal["reverses_entry_id"] == fee_entry_id
    assert reversal["amount_cents"] == -35_000

    unit = ctx.unit("901")
    assert unit["balance_due_cents"] == 0
    assert unit["delinquency_stage"] == "CURRENT"
    assert unit["transfer_blocked"] is True
    assert assert_unit_ledger_conserved(api, ctx.units["901"], MANAGER_HEADERS) == 0


def test_tender_cascade_reaches_only_the_affected_unit(api: ApiClient) -> None:
    """The unit absent from affected_unit_ids keeps an empty ledger.

    PRD 3.7: "It sets `disclosure_required` to true and then cascades: every
    resale certificate whose `status` is `ISSUED` and whose `unit_id` appears in
    `affected_unit_ids` becomes `VOIDED` with `requires_reissue` set to true,
    because an already-issued certificate cannot disclose a matter tendered after
    it was printed; each such certificate's `cert_fee_entry_id` is answered with a
    `REVERSAL` row, and the affected unit's `balance_due_cents` and
    `delinquency_stage` are recomputed with `Unit.version` advancing by 1."

    Design: Difficulty/transitive_cascade/litigation_tender_two_hop_cascade_voids_certificate_and_reverses_fee
    """
    ctx, claim, _ = _tender_world(api)

    get_success_data(
        api.set_litigation_stage(claim["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS)
    )

    assert ctx.unit("902")["balance_due_cents"] == 0
    assert ctx.ledger("902") == []
