"""Forward actions and the compensations that must undo them to the cent.

Two different conserved quantities are exercised.  Invariant L is owner ledger
cents per unit: a fine assessment pushes a unit over a lowered lien threshold and
its vacatur on appeal must put every derived consequence back, all the way out to
a live ballot's eligible weight.  Invariant E is contract authorization cents per
vendor contract, where a hold releases nothing, a cancel releases exactly the
estimate, and an invoice swaps the estimate out for the final cost.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant_equals,
    assert_contract_authorization_conserved,
    assert_unit_ledger_conserved,
    count_entries,
    find_entry,
    read_case,
    read_contract,
    read_element,
    read_meeting,
    read_special_assessment,
    read_vote,
    read_work_order,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    add_work_order,
    award_and_activate_contract,
    build_board,
    cast_owner_ballots,
    convene,
    create_association,
    docket_hearing,
    notice_meeting,
    notice_violation_case,
    open_special_assessment,
    patch_association,
    post_charge,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS

FINE_DECISION_AT = "2026-10-20T18:00:00Z"
APPEAL_HEARING_AT = "2026-11-10T18:00:00Z"


# ======================================================================
# Invariant L: a fine assessment against its vacatur on appeal
# ======================================================================
def _fernwood(api: ApiClient, *, case_unit: str = "A"):
    """A noticed case docketed for its round-one hearing, plus a live ballot.

    ``lien_threshold_cents`` is lowered to 12000 so that a single tier-one fine
    of 5000 on top of unit A's 8000 of collection costs is enough to cross it.
    The special assessment is left balloting with one owner ballot cast, so the
    eligible weight and the ballot's ``counted`` flag are live recomputation
    targets on both the escalation and the de-escalation.
    """
    ctx = create_association(api, legal_name="Fernwood Condominium Association")
    patch_association(ctx, lien_threshold_cents=12_000)
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "oa", full_name="Owner A")
    add_owner(ctx, "ob", full_name="Owner B")
    add_unit(ctx, "A", "oa", 6000, 1500)
    add_unit(ctx, "B", "ob", 4000, 1000)
    collection_cost = post_charge(
        ctx,
        "A",
        entry_type="COLLECTION_COST",
        amount_cents=8_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="prior collection costs",
    )
    assessment = open_special_assessment(
        ctx,
        total_amount_cents=600_000,
        installment_count=3,
        purpose="Boiler replacement",
    )
    ballot = cast_owner_ballots(
        ctx, "SPECIAL_ASSESSMENT", assessment["id"], [("oa", "A", "YES")]
    )[0]
    schedule_meeting(
        ctx, "mtg_h1", ["HEARING"], FINE_DECISION_AT, "2026-10-20T21:00:00Z"
    )
    notice_meeting(ctx, "mtg_h1")
    case = notice_violation_case(ctx, case_unit, rule_code="PARKING", reporter_label="tr")
    set_clock(api, "2026-08-16T00:00:00Z")
    docket_hearing(ctx, case["id"], "mtg_h1", FINE_DECISION_AT)
    schedule_meeting(
        ctx, "mtg_h2", ["HEARING"], APPEAL_HEARING_AT, "2026-11-10T21:00:00Z"
    )
    notice_meeting(ctx, "mtg_h2")
    set_clock(api, FINE_DECISION_AT)
    convene(ctx, "mtg_h1", ("d1", "d2", "tr"))
    return ctx, case["id"], collection_cost, assessment, ballot


def _fine_it(ctx, case_id: str):
    """Decide round one as the president, who is not the reporting treasurer."""
    return get_success_data(
        ctx.api.hearing_decision(case_id, {"outcome": "FINE"}, ctx.director("d1"))
    )


def _appeal_it(ctx, case_id: str, owner_label: str):
    """File the owner's appeal, which releases the round-one docket slot."""
    return get_success_data(ctx.api.appeal_case(case_id, ctx.owner(owner_label)))


def _redocket_and_convene(ctx, case_id: str):
    """Put the appeal on the second meeting's docket and open that meeting."""
    docket_hearing(ctx, case_id, "mtg_h2", APPEAL_HEARING_AT)
    set_clock(ctx.api, APPEAL_HEARING_AT)
    convene(ctx, "mtg_h2", ("d1", "d2", "tr"))


def test_pre_fine_unit_sits_on_late_notice_with_its_ballot_weight_intact(
    api: ApiClient,
) -> None:
    """8000 of aged collection costs is below the 12000 threshold, so no lien.

    PRD 3.1: "Rule 4: if `oldest_unpaid_age_days` is at least 30, the posture is
    `LATE_NOTICE`."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, _, _, assessment, ballot = _fernwood(api)

    unit = ctx.unit("A")
    assert unit["balance_due_cents"] == 8_000
    assert unit["delinquency_stage"] == "LATE_NOTICE"
    assert unit["voting_eligible"] is True
    assert unit["lien_recorded_at"] is None
    assert (
        read_special_assessment(api, assessment["id"], MANAGER_HEADERS)[
            "eligible_weight_bp"
        ]
        == 10_000
    )
    assert read_vote(api, ballot["id"], MANAGER_HEADERS)["counted"] is True


def test_round_one_fine_posts_a_tier_one_row_and_opens_the_appeal_window(
    api: ApiClient,
) -> None:
    """No qualifying predecessor means tier 1, which is 5000 cents flat.

    PRD 3.8: "`fine_tier` is 1 when the qualifying chain is empty, 2 when it
    holds exactly one link, and 3 when it holds two or more."

    The decision lands at 2026-10-20T18:00:00Z, so both the row's `due_on` (thirty
    days on) and `appeal_deadline_at` (thirty days on) fall on 2026-11-19T18:00:00Z.

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, _, _ = _fernwood(api)

    fined = _fine_it(ctx, case_id)

    assert fined["status"] == "FINE_ASSESSED"
    assert fined["prior_case_id"] is None
    assert fined["fine_tier"] == 1
    assert fined["fine_amount_cents"] == 5_000
    assert_instant_equals(fined["appeal_deadline_at"], "2026-11-19T18:00:00Z")
    row = find_entry(ctx.ledger("A"), id=fined["fine_entry_id"])
    assert row["entry_type"] == "FINE"
    assert row["bucket"] == "FINE"
    assert row["amount_cents"] == 5_000
    assert row["status"] == "POSTED"
    assert_instant_equals(row["due_on"], "2026-11-19T18:00:00Z")
    assert row["source_case_id"] == case_id


def test_the_fine_escalates_the_unit_and_strips_its_ballot_weight(
    api: ApiClient,
) -> None:
    """13000 clears the lowered threshold at 202 days old, so the lien rung binds.

    PRD 3.1: "Reaching `LATE_NOTICE → LIEN_FILED` additionally stamps
    `lien_recorded_at` with the logical clock and flips `voting_eligible` to
    false; because eligibility changed, every special assessment of the
    association whose `approval_status` is `BALLOTING` recomputes its
    `eligible_weight_bp` and re-derives the `counted` flag on its votes, each
    such assessment advancing its own `version` by 1; and when the re-derivation
    happened inside a billing run, that run's `escalated_unit_count` rises by 1."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, assessment, ballot = _fernwood(api)

    _fine_it(ctx, case_id)

    unit = ctx.unit("A")
    assert unit["balance_due_cents"] == 13_000
    assert unit["oldest_unpaid_age_days"] == 202
    assert unit["delinquency_stage"] == "LIEN_FILED"
    assert_instant_equals(unit["lien_recorded_at"], FINE_DECISION_AT)
    assert unit["voting_eligible"] is False
    assert (
        read_special_assessment(api, assessment["id"], MANAGER_HEADERS)[
            "eligible_weight_bp"
        ]
        == 4_000
    )
    assert read_vote(api, ballot["id"], MANAGER_HEADERS)["counted"] is False


def test_an_appeal_releases_the_docket_slot_but_compensates_nothing(
    api: ApiClient,
) -> None:
    """The fine stays owed throughout the appeal, so the ledger does not move.

    PRD 3.8: "The side effects release the docket slot: the former hearing
    meeting's `hearing_slot_count` falls by 1 with that `BoardMeeting.version`
    advancing by 1, `hearing_meeting_id` and `hearing_slot_start` are cleared to
    null, the `FINE` row stays `POSTED` so the fine remains owed throughout the
    appeal, and `ViolationCase.version` advances by 1."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, _, _ = _fernwood(api)
    fined = _fine_it(ctx, case_id)

    appealed = _appeal_it(ctx, case_id, "oa")

    assert appealed["status"] == "APPEALED"
    assert appealed["hearing_meeting_id"] is None
    assert appealed["hearing_slot_start"] is None
    assert (
        read_meeting(api, ctx.meetings["mtg_h1"], MANAGER_HEADERS)["hearing_slot_count"]
        == 0
    )
    assert find_entry(ctx.ledger("A"), id=fined["fine_entry_id"])["status"] == "POSTED"
    assert ctx.unit("A")["balance_due_cents"] == 13_000


def test_vacatur_on_the_second_round_decides_the_case_to_fine_vacated(
    api: ApiClient,
) -> None:
    """The reviewing director is neither the reporter nor the first decider.

    PRD 3.8: "`VACATE`, legal only when `hearing_round` is 2 or greater and
    subject to the same self-review prohibition, moves the case to `FINE_VACATED`
    and is the compensating action for the fine assessment: the unit ledger must
    return to exactly its pre-fine value."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, _, _ = _fernwood(api)
    _fine_it(ctx, case_id)
    _appeal_it(ctx, case_id, "oa")
    _redocket_and_convene(ctx, case_id)

    vacated = validate_success(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d2"))
    )

    assert vacated["status"] == "FINE_VACATED"
    assert vacated["hearing_round"] == 2


def test_vacatur_posts_the_exact_negation_of_the_fine_row(api: ApiClient) -> None:
    """One REVERSAL of minus 5000, itself POSTED, against a now-REVERSED original.

    PRD 2.8: "Compensation is expressed by posting a `REVERSAL` entry whose
    `reverses_entry_id` names the original, whose `amount_cents` is the exact
    arithmetic negation of the original's `amount_cents`, and whose own `status`
    is `POSTED`, while the original's `status` becomes `REVERSED`."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, _, _ = _fernwood(api)
    fined = _fine_it(ctx, case_id)
    _appeal_it(ctx, case_id, "oa")
    _redocket_and_convene(ctx, case_id)

    get_success_data(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d2"))
    )

    rows = ctx.ledger("A")
    assert find_entry(rows, id=fined["fine_entry_id"])["status"] == "REVERSED"
    assert count_entries(rows, entry_type="REVERSAL") == 1
    reversal = find_entry(rows, entry_type="REVERSAL")
    assert reversal["reverses_entry_id"] == fined["fine_entry_id"]
    assert reversal["amount_cents"] == -5_000
    assert reversal["status"] == "POSTED"
    assert reversal["bucket"] == "NONE"


def test_vacatur_returns_the_balance_to_its_exact_pre_fine_value(
    api: ApiClient,
) -> None:
    """8000 plus 5000 minus 5000 is 8000, and the invariant is checked over all rows.

    PRD 2.8: "**Invariant L -- owner ledger cents per unit.** A unit's
    `balance_due_cents` always equals the signed sum of `amount_cents` over
    *every* ledger entry of that unit, whatever each row's `status`."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, _, _ = _fernwood(api)
    _fine_it(ctx, case_id)
    _appeal_it(ctx, case_id, "oa")
    _redocket_and_convene(ctx, case_id)

    get_success_data(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d2"))
    )

    assert ctx.unit("A")["balance_due_cents"] == 8_000
    assert assert_unit_ledger_conserved(api, ctx.units["A"], MANAGER_HEADERS) == 8_000
    assert len(ctx.ledger("A")) == 3


def test_vacatur_unwinds_the_lien_and_restores_voting_eligibility(
    api: ApiClient,
) -> None:
    """De-escalation runs the same ladder, so the lien stamp is cleared.

    PRD 3.1: "Falling back from `LIEN_FILED → LATE_NOTICE` (which happens when
    the balance is still positive but below `lien_threshold_cents` while
    `oldest_unpaid_age_days` is at least 30) or from `LIEN_FILED → CURRENT` (when
    the balance reaches zero or below) clears `lien_recorded_at` to null, sets
    `voting_eligible` back to true, and triggers the same `BALLOTING`
    eligible-weight recomputation."

    At the appeal hearing the only open row is still the 2026-04-01 collection
    cost, which is 223 days old on 2026-11-10.

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, _, _ = _fernwood(api)
    _fine_it(ctx, case_id)
    _appeal_it(ctx, case_id, "oa")
    _redocket_and_convene(ctx, case_id)

    get_success_data(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d2"))
    )

    unit = ctx.unit("A")
    assert unit["oldest_unpaid_age_days"] == 223
    assert unit["delinquency_stage"] == "LATE_NOTICE"
    assert unit["lien_recorded_at"] is None
    assert unit["voting_eligible"] is True


def test_vacatur_restores_the_balloting_assessments_eligible_weight(
    api: ApiClient,
) -> None:
    """The third hop reaches the open ballot and counts the owner again.

    PRD 3.8: "Third, because `voting_eligible` flipped, every special assessment
    of the association whose `approval_status` is `BALLOTING` recomputes
    `eligible_weight_bp` and re-derives `counted` on its votes, with each
    `SpecialAssessment.version` advancing by 1."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, assessment, ballot = _fernwood(api)
    _fine_it(ctx, case_id)
    _appeal_it(ctx, case_id, "oa")
    _redocket_and_convene(ctx, case_id)

    get_success_data(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d2"))
    )

    reread = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert reread["approval_status"] == "BALLOTING"
    assert reread["eligible_weight_bp"] == 10_000
    assert read_vote(api, ballot["id"], MANAGER_HEADERS)["counted"] is True


def test_vacatur_touches_only_the_fine_pair(api: ApiClient) -> None:
    """The unrelated collection cost is left alone and no fourth hop fires.

    PRD 3.8: "Fourth, because `eligible_weight_bp` changed, every resale
    certificate of that unit whose `status` is `ISSUED` and whose
    `special_assessment_disclosure_cents` no longer matches the recomputed figure
    becomes `VOIDED` with `requires_reissue` set to true and its `RESALE_FEE` row
    reversed."

    This unit holds no issued certificate, so the fourth hop has nothing to void
    and no `RESALE_FEE` row appears anywhere on the ledger.

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, collection_cost, _, _ = _fernwood(api)
    _fine_it(ctx, case_id)
    _appeal_it(ctx, case_id, "oa")
    _redocket_and_convene(ctx, case_id)

    get_success_data(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d2"))
    )

    rows = ctx.ledger("A")
    surviving = find_entry(rows, id=collection_cost["id"])
    assert surviving["status"] == "POSTED"
    assert surviving["amount_cents"] == 8_000
    assert count_entries(rows, entry_type="RESALE_FEE") == 0
    assert len(rows) == 3


def test_upholding_the_fine_on_appeal_compensates_nothing(api: ApiClient) -> None:
    """The twin walk decided UPHOLD leaves the money exactly where it was.

    PRD 3.8: "`UPHOLD`, legal only when `hearing_round` is 2 or greater, moves the
    case to `FINE_UPHELD`. It additionally requires that the acting `X-User-ID`
    differ from `decision_owner_id`, because no director may review their own
    decision; a self-review is refused with `ERR_SEGREGATION_OF_DUTIES`. The
    `FINE` row stays `POSTED`, the unit's `balance_due_cents` is unchanged, and
    `ViolationCase.version` advances by 1."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, _, _ = _fernwood(api, case_unit="B")
    fined = _fine_it(ctx, case_id)
    assert ctx.unit("B")["balance_due_cents"] == 5_000
    _appeal_it(ctx, case_id, "ob")
    _redocket_and_convene(ctx, case_id)

    upheld = validate_success(
        api.hearing_decision(case_id, {"outcome": "UPHOLD"}, ctx.director("d2"))
    )

    assert upheld["status"] == "FINE_UPHELD"
    rows = ctx.ledger("B")
    assert find_entry(rows, id=fined["fine_entry_id"])["status"] == "POSTED"
    assert count_entries(rows, entry_type="REVERSAL") == 0
    assert ctx.unit("B")["balance_due_cents"] == 5_000
    assert assert_unit_ledger_conserved(api, ctx.units["B"], MANAGER_HEADERS) == 5_000


def test_a_vacated_fine_never_inflates_a_later_cases_tier(api: ApiClient) -> None:
    """A fresh case on the same unit and rule still computes tier 1.

    PRD 3.8: "Cases in `DISMISSED` or `FINE_VACATED` are never written as
    anyone's `prior_case_id`, so a dismissal or a vacated fine can never inflate a
    later tier."

    Design: Difficulty/compensating_invariant/fine_vacatur_restores_owner_ledger_cents_invariant_l_exactly
    """
    ctx, case_id, _, _, _ = _fernwood(api)
    _fine_it(ctx, case_id)
    _appeal_it(ctx, case_id, "oa")
    _redocket_and_convene(ctx, case_id)
    get_success_data(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d2"))
    )

    schedule_meeting(
        ctx, "mtg_h3", ["HEARING"], "2026-12-15T18:00:00Z", "2026-12-15T21:00:00Z"
    )
    notice_meeting(ctx, "mtg_h3")
    later = notice_violation_case(ctx, "A", rule_code="PARKING", reporter_label="tr")
    assert later["prior_case_id"] is None
    set_clock(api, "2026-11-25T00:00:00Z")
    docket_hearing(ctx, later["id"], "mtg_h3", "2026-12-15T18:00:00Z")
    set_clock(api, "2026-12-15T18:00:00Z")
    convene(ctx, "mtg_h3", ("d1", "d2", "tr"))

    fined_again = _fine_it(ctx, later["id"])

    assert fined_again["fine_tier"] == 1
    assert fined_again["fine_amount_cents"] == 5_000
    assert read_case(api, case_id, MANAGER_HEADERS)["status"] == "FINE_VACATED"


# ======================================================================
# Invariant E: encumbrance released by cancel, invoice and termination
# ======================================================================
def _thornbury(api: ApiClient):
    """One active contract carrying three non-round encumbrances, one held.

    1234567 + 900000 + 765433 sums to exactly 2900000, so every release below is
    checkable to the cent, and the windows are more than the 24-hour buffer apart
    so none of them collides.
    """
    ctx = create_association(api, legal_name="Thornbury Condominium Association")
    patch_association(ctx, operating_cash_cents=3_000_000)
    build_board(ctx)
    add_element(
        ctx,
        "el1",
        name="Main Roof Membrane",
        element_class="ROOF",
        replacement_cost_cents=9_000_000,
        useful_life_years=30,
        effective_age_years=10,
    )
    add_contract(
        ctx,
        "ct1",
        "el1",
        vendor_name="Meridian Roofing LLC",
        contract_cap_cents=5_000_000,
        insurance_cert_expires_at="2027-06-01T00:00:00Z",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-06-01T00:00:00Z",
    )
    schedule_meeting(
        ctx,
        "mtg_ca",
        ["CONTRACT_AWARD"],
        "2026-09-10T18:00:00Z",
        "2026-09-10T21:00:00Z",
    )
    notice_meeting(ctx, "mtg_ca")
    set_clock(api, "2026-09-10T18:00:00Z")
    convene(ctx, "mtg_ca", ("d1", "d2", "tr"))
    award_and_activate_contract(ctx, "ct1", "mtg_ca")
    wo1 = add_work_order(
        ctx,
        "ct1",
        "el1",
        scope="North slope seams",
        window_start="2026-10-05T08:00:00Z",
        window_end="2026-10-07T18:00:00Z",
        estimated_cost_cents=1_234_567,
    )
    wo2 = add_work_order(
        ctx,
        "ct1",
        "el1",
        scope="Flashing replacement",
        window_start="2026-10-10T08:00:00Z",
        window_end="2026-10-11T18:00:00Z",
        estimated_cost_cents=900_000,
    )
    wo3 = add_work_order(
        ctx,
        "ct1",
        "el1",
        scope="Drain retrofit",
        window_start="2026-10-15T08:00:00Z",
        window_end="2026-10-16T18:00:00Z",
        estimated_cost_cents=765_433,
    )
    set_clock(api, "2026-10-05T08:00:00Z")
    get_success_data(ctx.api.start_work_order(wo1["id"], MANAGER_HEADERS))
    get_success_data(
        ctx.api.hold_work_order(
            wo1["id"], {"hold_reason": "ELEMENT_UNAVAILABLE"}, MANAGER_HEADERS
        )
    )
    return ctx, wo1, wo2, wo3


def _cancel(ctx, order):
    return get_success_data(ctx.api.cancel_work_order(order["id"], MANAGER_HEADERS))


def _resume_and_complete(ctx, order):
    """Resume the held order and complete it after its window has run."""
    get_success_data(ctx.api.start_work_order(order["id"], MANAGER_HEADERS))
    set_clock(ctx.api, "2026-10-07T20:00:00Z")
    return get_success_data(
        ctx.api.complete_work_order(
            order["id"], MANAGER_HEADERS, payload={"resets_component": False}
        )
    )


def test_holding_an_order_releases_none_of_its_encumbrance(api: ApiClient) -> None:
    """ON_HOLD stays inside the summation set, so committed_cents is untouched.

    PRD 2.8: "Putting an order on hold does **not** release its encumbrance,
    because `ON_HOLD` remains inside the summation set."

    Design: Difficulty/compensating_invariant/work_order_lifecycle_conserves_contract_authorization_cents_invariant_e
    """
    ctx, wo1, wo2, wo3 = _thornbury(api)

    held = read_work_order(api, wo1["id"], MANAGER_HEADERS)
    assert held["status"] == "ON_HOLD"
    assert held["hold_reason"] == "ELEMENT_UNAVAILABLE"
    assert held["encumbered_cents"] == 1_234_567
    assert read_work_order(api, wo2["id"], MANAGER_HEADERS)["encumbered_cents"] == 900_000
    assert read_work_order(api, wo3["id"], MANAGER_HEADERS)["encumbered_cents"] == 765_433
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["committed_cents"] == 2_900_000
    assert contract["invoiced_cents"] == 0
    assert read_element(api, ctx.elements["el1"], MANAGER_HEADERS)["status"] == "IMPAIRED"
    assert (
        assert_contract_authorization_conserved(
            api, ctx.contracts["ct1"], MANAGER_HEADERS
        )
        == 2_900_000
    )


def test_cancelling_an_order_releases_exactly_its_estimate(api: ApiClient) -> None:
    """A create-then-cancel round trip returns committed_cents to its pre-create value.

    PRD 2.8: "Creating a work order encumbers `estimated_cost_cents`; cancelling
    that order, terminating the contract, or letting the contract expire each set
    that order's `encumbered_cents` to 0 and release exactly
    `estimated_cost_cents`, so a create-then-cancel round trip returns
    `committed_cents` to its exact pre-create value."

    Design: Difficulty/compensating_invariant/work_order_lifecycle_conserves_contract_authorization_cents_invariant_e
    """
    ctx, _, _, wo3 = _thornbury(api)

    cancelled = _cancel(ctx, wo3)

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["encumbered_cents"] == 0
    assert cancelled["hold_reason"] == "NONE"
    assert (
        read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)["committed_cents"]
        == 2_134_567
    )
    assert (
        assert_contract_authorization_conserved(
            api, ctx.contracts["ct1"], MANAGER_HEADERS
        )
        == 2_134_567
    )


def test_a_second_cancel_cannot_release_the_same_encumbrance_twice(
    api: ApiClient,
) -> None:
    """CANCELLED is terminal, so the repeat is refused rather than re-applied.

    PRD 3.6: "Work order `status` runs through `SCHEDULED`, `IN_PROGRESS`,
    `ON_HOLD`, `COMPLETED`, `INVOICED`, and `CANCELLED`, starting at `SCHEDULED`,
    with `INVOICED` and `CANCELLED` terminal; `hold_reason` is an enum over
    `NONE`, `CONTRACT_SUSPENDED`, `ELEMENT_UNAVAILABLE`, and `FUNDING` defaulting
    to `NONE`; `final_cost_cents` is supplied only at invoicing."

    Design: Difficulty/compensating_invariant/work_order_lifecycle_conserves_contract_authorization_cents_invariant_e
    """
    ctx, _, _, wo3 = _thornbury(api)
    _cancel(ctx, wo3)

    validate_error(
        api.cancel_work_order(wo3["id"], MANAGER_HEADERS),
        "ERR_INVALID_WORK_ORDER_STATE",
        expected_status=409,
    )

    assert (
        read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)["committed_cents"]
        == 2_134_567
    )
    assert (
        assert_contract_authorization_conserved(
            api, ctx.contracts["ct1"], MANAGER_HEADERS
        )
        == 2_134_567
    )


def test_a_completed_order_still_encumbers_its_estimate(api: ApiClient) -> None:
    """COMPLETED is inside the summation set, so completion releases nothing either.

    PRD 2.8: "**Invariant E -- contract authorization cents per vendor
    contract.** A contract's `committed_cents` always equals the sum of
    `encumbered_cents` over that contract's work orders whose `status` is
    `SCHEDULED`, `IN_PROGRESS`, `ON_HOLD`, or `COMPLETED`; `CANCELLED` and
    `INVOICED` orders contribute zero."

    Design: Difficulty/compensating_invariant/work_order_lifecycle_conserves_contract_authorization_cents_invariant_e
    """
    ctx, wo1, _, wo3 = _thornbury(api)
    _cancel(ctx, wo3)

    completed = _resume_and_complete(ctx, wo1)

    assert completed["status"] == "COMPLETED"
    assert completed["encumbered_cents"] == 1_234_567
    assert (
        read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)["committed_cents"]
        == 2_134_567
    )
    assert (
        read_element(api, ctx.elements["el1"], MANAGER_HEADERS)["status"] == "SERVICEABLE"
    )


def test_invoicing_moves_the_estimate_out_and_the_final_cost_in(
    api: ApiClient,
) -> None:
    """The estimate leaves committed_cents; the final cost joins invoiced_cents.

    PRD 2.8: "Invoicing moves `estimated_cost_cents` out of `committed_cents` and
    adds `final_cost_cents` to `invoiced_cents`, with no drift."

    2134567 minus the 1234567 estimate is 900000; removing the 1300000 final cost
    instead would leave 834567.

    Design: Difficulty/compensating_invariant/work_order_lifecycle_conserves_contract_authorization_cents_invariant_e
    """
    ctx, wo1, _, wo3 = _thornbury(api)
    _cancel(ctx, wo3)
    _resume_and_complete(ctx, wo1)

    invoiced = validate_success(
        api.invoice_work_order(
            wo1["id"], {"final_cost_cents": 1_300_000}, MANAGER_HEADERS
        )
    )

    assert invoiced["status"] == "INVOICED"
    assert invoiced["encumbered_cents"] == 0
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["committed_cents"] == 900_000
    assert contract["invoiced_cents"] == 1_300_000
    assert contract["contract_cap_cents"] >= 900_000 + 1_300_000
    assert ctx.association()["operating_cash_cents"] == 1_700_000
    assert (
        assert_contract_authorization_conserved(
            api, ctx.contracts["ct1"], MANAGER_HEADERS
        )
        == 900_000
    )


def test_termination_releases_every_surviving_encumbrance(api: ApiClient) -> None:
    """The last scheduled order is cancelled and the empty sum is zero.

    PRD 3.6: "Both legs perform the same compensation: every work order whose
    `status` is `SCHEDULED` or `ON_HOLD` becomes `CANCELLED` with
    `encumbered_cents` set to 0, `committed_cents` is recomputed to equal the sum
    of `encumbered_cents` over the contract's non-cancelled orders as Invariant E
    requires, and `VendorContract.version` advances by 1."

    Design: Difficulty/compensating_invariant/work_order_lifecycle_conserves_contract_authorization_cents_invariant_e
    """
    ctx, wo1, wo2, wo3 = _thornbury(api)
    _cancel(ctx, wo3)
    _resume_and_complete(ctx, wo1)
    get_success_data(
        api.invoice_work_order(
            wo1["id"], {"final_cost_cents": 1_300_000}, MANAGER_HEADERS
        )
    )

    terminated = validate_success(
        api.terminate_contract(ctx.contracts["ct1"], ctx.director("d1"))
    )

    assert terminated["status"] == "TERMINATED"
    assert terminated["committed_cents"] == 0
    assert terminated["invoiced_cents"] == 1_300_000
    released = read_work_order(api, wo2["id"], MANAGER_HEADERS)
    assert released["status"] == "CANCELLED"
    assert released["encumbered_cents"] == 0
    assert (
        assert_contract_authorization_conserved(
            api, ctx.contracts["ct1"], MANAGER_HEADERS
        )
        == 0
    )
    assert ctx.association()["operating_cash_cents"] == 1_700_000
