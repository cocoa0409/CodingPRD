"""State-machine breadth probes: initial states, invalid legs, compensations.

Each test drives one entity's lifecycle to a specific vertex and checks either
the legality of the next hop or the exact fan-out of that hop's side effects.
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
    read_budget,
    read_case,
    read_certificate,
    read_contract,
    read_element,
    read_meeting,
    read_special_assessment,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    adjust_claim,
    adopt_budget,
    cast_owner_ballots,
    convene,
    create_association,
    docket_hearing,
    draft_budget,
    issue_certificate,
    notice_meeting,
    notice_violation_case,
    open_special_assessment,
    report_claim,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import ATTORNEY_HEADERS, MANAGER_HEADERS

HARBOR_POINT = "Harbor Point Condominium Association"


# ======================================================================
# Shared worlds
# ======================================================================
def _one_owner_association(api):
    """An association with a single owner of record and no board seats."""
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    return ctx


def _board_of_one(api):
    """One unseated owner of record plus one seated director; quorum is 1."""
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


def _fined_case(api, *, second_meeting: bool = False):
    """Walk a first-offence case to FINE_ASSESSED at an in-session hearing.

    The reporter (``d2``) and the deciding director (``d1``) are different
    people, and the optional second meeting exists for the appeal round because
    no board may rehear an appeal in the session that first decided it.
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
    if second_meeting:
        add_owner(
            ctx,
            "d3",
            full_name="Paul Osei",
            email="paul@example.test",
            board_role="PRESIDENT",
            is_seated=True,
        )
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)
    schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-08-20T10:00:00Z", "2026-08-20T12:00:00Z"
    )
    if second_meeting:
        schedule_meeting(
            ctx, "mtg2", ["HEARING"], "2026-08-25T10:00:00Z", "2026-08-25T12:00:00Z"
        )

    case = notice_violation_case(
        ctx, "101", rule_code="R-14-PETS", reporter_label="d2"
    )
    # The cure deadline is 2026-08-15; docketing needs a clock strictly past it.
    set_clock(api, "2026-08-16T00:00:00Z")
    docket_hearing(ctx, case["id"], "mtg1", "2026-08-20T10:00:00Z")
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-08-20T10:00:00Z")
    convene(ctx, "mtg1", attending=("d1",))
    fined = get_success_data(
        ctx.api.hearing_decision(case["id"], {"outcome": "FINE"}, ctx.director("d1"))
    )
    return ctx, case["id"], fined


# ======================================================================
# Budget lifecycle
# ======================================================================
def test_budget_is_born_draft_with_no_notice_and_no_precomputed_totals(api):
    """Creation is not a transition: DRAFT, revision_round 0, nothing stamped.

    The creating call consumes an optimistic-concurrency token and bumps the
    parent version, yet the budget itself must sit at the initial vertex.

    PRD 3.2: "Budget `status` takes one of six values -- `DRAFT`, `PROPOSED`,
    `NOTICED`, `ADOPTED`, `REJECTED`, and `SUPERSEDED` -- with `DRAFT` as the
    initial state and `ADOPTED` and `SUPERSEDED` as terminal."
    PRD 3.2: "The cycle is genuinely cyclic: a board may push a budget back to
    `DRAFT` from `PROPOSED`, from `NOTICED`, or from `REJECTED`, and each return
    increments `revision_round`, which starts at 0."
    PRD 3.2: "Creation also advances `Association.version` by 1."
    PRD 3.1: "Creating a unit has two secondary effects the caller does not
    request: the association's `total_interest_bp` is recomputed as the sum of
    `interest_bp` over all of its units and `Association.version` advances by
    1, and the named owner's `owned_unit_count` rises by 1 with
    `UnitOwner.version` advancing by 1."

    Design: Corner/state_machines/budget_is_born_draft_with_zero_revision_round_and_no_notice
    """
    ctx = _one_owner_association(api)
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)

    data = validate_success(
        api.create_budget(
            ctx.association_id,
            {
                "fiscal_year": 2026,
                "operating_total_cents": 12_000_000,
                "reserve_contribution_cents": 1_200_000,
                "expected_association_version": ctx.association_version(),
            },
            MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    assert data["status"] == "DRAFT"
    assert data["revision_round"] == 0
    assert data["notice_sent_at"] is None
    assert data["adopted_at"] is None
    assert data["supersedes_budget_id"] is None
    assert data["version"] == 1

    # One bump for the unit insert, one for the budget insert.
    assert ctx.association_version() == 3


def test_ratifying_a_never_noticed_budget_fails_on_state_before_the_meeting_gate(api):
    """A PROPOSED budget at a still-SCHEDULED meeting fails at the state rung.

    Two gates would fail at once -- the budget is not `NOTICED` and the meeting
    is not `IN_SESSION` -- and the lower-numbered state rung wins.

    PRD 2.9: "The target resource is in a state from which the requested
    transition is defined -- otherwise `ERR_INVALID_STATE_TRANSITION`, on every
    action endpoint, except where a more specific identifier is declared:
    `ERR_INVALID_BUDGET_STATE`, `ERR_INVALID_CONTRACT_STATE`,
    `ERR_INVALID_WORK_ORDER_STATE`, `ERR_INVALID_CLAIM_STATE`,
    `ERR_INVALID_CERTIFICATE_STATE`, `ERR_INVALID_MEETING_STATE`, and
    `ERR_INVALID_BALLOT_STATE` are used for their respective entities."
    PRD 2.9: "The hosting board meeting is `IN_SESSION` when a ratification or
    a hearing decision is recorded -- otherwise `ERR_MEETING_NOT_IN_SESSION`,
    on budget ratification and hearing decision recording."
    PRD 3.2: "Ratification is recorded by a `BoardDirector` and requires that
    the budget be `NOTICED`, that the ratification meeting be `IN_SESSION` with
    `quorum_met` true, that the logical clock be at or after `notice_sent_at`
    plus `budget_notice_days` days, and -- on the adoption branch -- that
    `total_interest_bp` still equal exactly 10000 and that no other budget for
    the same `fiscal_year` be `ADOPTED`."

    Design: Corner/state_machines/ratify_from_proposed_returns_invalid_budget_state_before_meeting_checks
    """
    ctx = _board_of_one(api)
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)
    meeting_id = schedule_meeting(
        ctx,
        "mtg1",
        ["BUDGET_RATIFICATION"],
        "2026-09-15T10:00:00Z",
        "2026-09-15T12:00:00Z",
    )
    budget = draft_budget(ctx, ratification_meeting_id=meeting_id)
    get_success_data(api.propose_budget(budget["id"], MANAGER_HEADERS))

    validate_error(
        api.ratify_budget(budget["id"], ctx.director("d1")),
        "ERR_INVALID_BUDGET_STATE",
        expected_status=409,
    )

    stored = read_budget(api, budget["id"], MANAGER_HEADERS)
    assert stored["status"] == "PROPOSED"
    assert stored["version"] == 2
    assert stored["adopted_at"] is None
    assert ctx.unit("101")["monthly_assessment_cents"] == 0


def test_adopted_is_terminal_even_for_the_board_that_owns_return_to_draft(api):
    """ADOPTED refuses the return-to-draft leg and keeps its allocation.

    The refusal must not roll back the per-unit assessments the adoption
    cascade minted, and it must not advance `revision_round`.

    PRD 3.2: "Budget `status` takes one of six values -- `DRAFT`, `PROPOSED`,
    `NOTICED`, `ADOPTED`, `REJECTED`, and `SUPERSEDED` -- with `DRAFT` as the
    initial state and `ADOPTED` and `SUPERSEDED` as terminal."
    PRD 2.9: "The target resource is in a state from which the requested
    transition is defined -- otherwise `ERR_INVALID_STATE_TRANSITION`, on every
    action endpoint, except where a more specific identifier is declared:
    `ERR_INVALID_BUDGET_STATE`, `ERR_INVALID_CONTRACT_STATE`,
    `ERR_INVALID_WORK_ORDER_STATE`, `ERR_INVALID_CLAIM_STATE`,
    `ERR_INVALID_CERTIFICATE_STATE`, `ERR_INVALID_MEETING_STATE`, and
    `ERR_INVALID_BALLOT_STATE` are used for their respective entities."
    PRD 3.2: "On success the server computes `assessment_total_cents` as
    `operating_total_cents` plus `reserve_contribution_cents`, computes
    `monthly_assessable_cents` as `assessment_total_cents` divided by 12 and
    rounded half up, and advances `Budget.version` by 1."
    PRD 3.2: "Third, each participant's share is computed as the pool
    multiplied by that unit's `interest_bp`, divided by 10000, and rounded half
    up; this per-line rounding is mandatory and summing before rounding is
    wrong."
    PRD 3.2: "With the default veto threshold of 5000 basis points -- half the
    association -- a counted `NO` weight of exactly 5000 rejects the budget
    while 4999 adopts it, and a ratification meeting at which nobody voted
    adopts, because the no-weight is 0."

    Design: Corner/state_machines/adopted_budget_rejects_return_to_draft_and_keeps_its_allocation
    """
    ctx = _board_of_one(api)
    add_unit(ctx, "101", "o1", 5000, heated_sqft=1000)
    add_unit(ctx, "102", "o1", 5000, heated_sqft=1000)

    # Pool = (12000000 + 1200000) / 12 = 1100000; each 5000 bp unit takes half.
    adopted = adopt_budget(
        ctx,
        meeting_label="mtg1",
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
    )
    assert adopted["status"] == "ADOPTED"

    validate_error(
        api.return_budget_to_draft(
            adopted["id"],
            ctx.director("d1"),
            payload={"reason": "board wants a smaller reserve line"},
        ),
        "ERR_INVALID_BUDGET_STATE",
        expected_status=409,
    )

    stored = read_budget(api, adopted["id"], MANAGER_HEADERS)
    assert stored["status"] == "ADOPTED"
    assert stored["revision_round"] == 0
    assert stored["no_weight_bp"] == 0
    assert_instant_equals(stored["adopted_at"], "2026-09-15T10:00:00Z")

    assert ctx.unit("101")["monthly_assessment_cents"] == 550_000
    assert ctx.unit("102")["monthly_assessment_cents"] == 550_000


# ======================================================================
# Board meeting cancellation
# ======================================================================
def test_one_cancellation_compensates_a_hearing_and_a_budget_differently(api):
    """The round-1 case and the noticed budget fall back along different paths.

    The case returns to NOTICE_SENT with its cure deadline untouched, while the
    budget returns to PROPOSED with `revision_round` still 0 -- reusing the
    return-to-draft path would have incremented it.

    PRD 3.3: "Every violation case docketed to this meeting whose
    `hearing_round` is 1 returns to `NOTICE_SENT`, with `hearing_meeting_id`
    and `hearing_slot_start` cleared to null and `hearing_round` returning to
    0, and -- importantly -- with `cure_deadline_at` **not** extended."
    PRD 3.3: "Every budget whose `ratification_meeting_id` is this meeting and
    whose `status` is `NOTICED` returns to `PROPOSED` with `notice_sent_at`
    cleared to null and its own `version` advanced by 1."
    PRD 3.3: "The meeting's `hearing_slot_count` becomes 0."
    PRD 3.8: "It stamps `notice_sent_at` from the logical clock, sets
    `cure_deadline_at` to `notice_sent_at` advanced by `cure_period_days`,
    resolves `prior_case_id` to the most recent qualifying earlier case, and
    advances `ViolationCase.version` by 1."

    Design: Corner/state_machines/meeting_cancellation_compensates_round1_hearing_and_noticed_budget_differently
    """
    ctx = _board_of_one(api)
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)
    meeting_id = schedule_meeting(
        ctx,
        "mtg1",
        ["BUDGET_RATIFICATION", "HEARING"],
        "2026-10-01T10:00:00Z",
        "2026-10-01T12:00:00Z",
    )

    # Notice goes out at the clock epoch, so the cure deadline is 2026-08-15.
    case = notice_violation_case(
        ctx, "101", rule_code="R-14-PETS", reporter_label="d1"
    )
    budget = draft_budget(ctx, ratification_meeting_id=meeting_id)
    get_success_data(api.propose_budget(budget["id"], MANAGER_HEADERS))

    set_clock(api, "2026-08-16T00:00:00Z")
    get_success_data(api.send_budget_notice(budget["id"], MANAGER_HEADERS))
    docket_hearing(ctx, case["id"], "mtg1", "2026-10-01T10:30:00Z")

    data = validate_success(
        api.cancel_meeting(
            meeting_id, MANAGER_HEADERS, payload={"reason": "no quorum available"}
        )
    )
    assert data["status"] == "CANCELLED"
    assert data["hearing_slot_count"] == 0

    stored_case = read_case(api, case["id"], MANAGER_HEADERS)
    assert stored_case["status"] == "NOTICE_SENT"
    assert stored_case["hearing_meeting_id"] is None
    assert stored_case["hearing_slot_start"] is None
    assert stored_case["hearing_round"] == 0
    assert_instant_equals(stored_case["cure_deadline_at"], "2026-08-15T00:00:00Z")

    stored_budget = read_budget(api, budget["id"], MANAGER_HEADERS)
    assert stored_budget["status"] == "PROPOSED"
    assert stored_budget["notice_sent_at"] is None
    assert stored_budget["revision_round"] == 0

    assert ctx.unit("101")["monthly_assessment_cents"] == 0


# ======================================================================
# Work order hold / resume cycle
# ======================================================================
def test_holding_and_resuming_an_elevator_order_never_releases_the_encumbrance(api):
    """Hold drives the element IMPAIRED, resume drives it OUT_OF_SERVICE.

    An elevator is life-safety by derivation, so the resume leg must not settle
    for IMPAIRED; across all three hops the encumbrance stays pinned.

    PRD 3.6: "From `element_class` the server derives `is_life_safety`, which
    is true exactly when the class is `ELEVATOR` or `LIFE_SAFETY`."
    PRD 3.6: "Derived money figures are `committed_cents`, the sum of
    `encumbered_cents` over the contract's work orders in `SCHEDULED`,
    `IN_PROGRESS`, `ON_HOLD`, or `COMPLETED`, and `invoiced_cents`, the sum of
    `final_cost_cents` over its `INVOICED` orders; both start at 0."
    PRD 3.6: "Holding work in progress moves it `IN_PROGRESS → ON_HOLD`, sets
    `hold_reason` from the request body, drives the element's `status` to
    `IMPAIRED` with `CommonElement.version` advancing by 1, leaves
    `encumbered_cents` unchanged, and advances the order's `version` by 1."
    PRD 3.6: "Both legs set `hold_reason` to `NONE` and drive the element's
    `status` to `OUT_OF_SERVICE` when the element's `is_life_safety` is true
    and to `IMPAIRED` otherwise, advancing `CommonElement.version` by 1, and
    both advance `MaintenanceWorkOrder.version` by 1."

    Design: Corner/state_machines/work_order_hold_cycle_keeps_encumbrance_and_re_derives_life_safety_posture
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
    element_id = add_element(
        ctx,
        "el1",
        name="Passenger Elevator #1",
        element_class="ELEVATOR",
        replacement_cost_cents=30_000_000,
        useful_life_years=50,
        effective_age_years=25,
    )
    contract_id = add_contract(
        ctx,
        "ct1",
        "el1",
        vendor_name="Summit Elevator Co",
        contract_cap_cents=5_000_000,
        insurance_cert_expires_at="2027-06-30T00:00:00Z",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-06-30T00:00:00Z",
    )
    meeting_id = schedule_meeting(
        ctx, "mtg_ca", ["CONTRACT_AWARD"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z"
    )
    notice_meeting(ctx, "mtg_ca")
    set_clock(api, "2026-08-05T10:00:00Z")
    convene(ctx, "mtg_ca", attending=("d1",))

    get_success_data(api.submit_contract(contract_id, MANAGER_HEADERS))
    get_success_data(
        api.cast_vote(
            {
                "association_id": ctx.association_id,
                "subject_type": "VENDOR_CONTRACT",
                "subject_id": contract_id,
                "choice": "YES",
                "voter_owner_id": ctx.owners["d1"],
                "meeting_id": meeting_id,
            },
            ctx.director("d1"),
        )
    )
    get_success_data(api.approve_contract(contract_id, ctx.director("d1")))
    get_success_data(api.activate_contract(contract_id, MANAGER_HEADERS))

    order = get_success_data(
        api.create_work_order(
            {
                "contract_id": contract_id,
                "element_id": element_id,
                "scope": "Annual traction inspection",
                "window_start": "2026-08-06T08:00:00Z",
                "window_end": "2026-08-06T16:00:00Z",
                "estimated_cost_cents": 1_000_000,
                "expected_contract_version": ctx.contract_version("ct1"),
            },
            MANAGER_HEADERS,
        )
    )
    set_clock(api, "2026-08-06T08:00:00Z")
    get_success_data(api.start_work_order(order["id"], MANAGER_HEADERS))

    held = validate_success(
        api.hold_work_order(
            order["id"], {"hold_reason": "ELEMENT_UNAVAILABLE"}, MANAGER_HEADERS
        )
    )
    assert held["status"] == "ON_HOLD"
    assert held["hold_reason"] == "ELEMENT_UNAVAILABLE"
    assert held["encumbered_cents"] == 1_000_000

    element = read_element(api, element_id, MANAGER_HEADERS)
    assert element["status"] == "IMPAIRED"
    assert element["is_life_safety"] is True

    contract = read_contract(api, contract_id, MANAGER_HEADERS)
    assert contract["committed_cents"] == 1_000_000
    assert contract["invoiced_cents"] == 0

    resumed = validate_success(api.start_work_order(order["id"], MANAGER_HEADERS))
    assert resumed["status"] == "IN_PROGRESS"
    assert resumed["hold_reason"] == "NONE"

    assert read_element(api, element_id, MANAGER_HEADERS)["status"] == "OUT_OF_SERVICE"
    assert (
        read_contract(api, contract_id, MANAGER_HEADERS)["committed_cents"] == 1_000_000
    )


# ======================================================================
# Enforcement: appeal and vacatur
# ======================================================================
def test_appealing_releases_the_docket_slot_but_leaves_the_fine_owed(api):
    """The appeal is a docket release, never a financial compensation.

    The slot count returns to 0 and the slot fields clear, yet the FINE row
    stays POSTED and no REVERSAL exists.

    PRD 3.8: "`fine_tier` is 1 when the qualifying chain is empty, 2 when it
    holds exactly one link, and 3 when it holds two or more."
    PRD 3.8: "The raw amount is `fine_tier_1_cents` at tier 1,
    `fine_tier_2_cents` at tier 2, and `fine_tier_3_daily_cents` multiplied by
    `continuing_days` at tier 3 -- the daily rate is multiplied **before** the
    cap is applied."
    PRD 3.8: "The side effects release the docket slot: the former hearing
    meeting's `hearing_slot_count` falls by 1 with that `BoardMeeting.version`
    advancing by 1, `hearing_meeting_id` and `hearing_slot_start` are cleared
    to null, the `FINE` row stays `POSTED` so the fine remains owed throughout
    the appeal, and `ViolationCase.version` advances by 1."
    PRD 3.1: "Rule 6: otherwise the posture is `CURRENT`."

    Design: Corner/state_machines/fine_appeal_releases_docket_slot_while_the_fine_entry_stays_posted
    """
    ctx, case_id, fined = _fined_case(api)
    assert fined["fine_tier"] == 1
    assert fined["fine_amount_cents"] == 5000

    data = validate_success(
        api.appeal_case(
            case_id,
            ctx.owner("o1"),
            payload={"grounds": "the pet was a registered service animal"},
        )
    )
    assert data["status"] == "APPEALED"
    assert data["hearing_meeting_id"] is None
    assert data["hearing_slot_start"] is None
    assert data["fine_amount_cents"] == 5000
    assert data["fine_tier"] == 1

    meeting = read_meeting(api, ctx.meetings["mtg1"], MANAGER_HEADERS)
    assert meeting["hearing_slot_count"] == 0
    assert meeting["status"] == "IN_SESSION"

    fine_rows, fine_meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["101"], "entry_type": "FINE"},
        )
    )
    assert fine_meta["total_count"] == 1
    assert fine_rows[0]["status"] == "POSTED"
    assert fine_rows[0]["amount_cents"] == 5000

    _, reversal_meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["101"], "entry_type": "REVERSAL"},
        )
    )
    assert reversal_meta["total_count"] == 0

    unit = ctx.unit("101")
    assert unit["balance_due_cents"] == 5000
    assert unit["delinquency_stage"] == "CURRENT"


def test_vacatur_at_the_appeal_round_restores_the_ledger_to_its_pre_fine_value(api):
    """VACATE posts a compensating row and the balance returns to exactly 0.

    The appeal must be heard at a different meeting and decided by a third
    director; both fine rows remain queryable afterwards.

    PRD 3.8: "`VACATE`, legal only when `hearing_round` is 2 or greater and
    subject to the same self-review prohibition, moves the case to
    `FINE_VACATED` and is the compensating action for the fine assessment: the
    unit ledger must return to exactly its pre-fine value."
    PRD 3.8: "First, a `REVERSAL` row is posted whose `reverses_entry_id` is
    `fine_entry_id` and whose `amount_cents` is the negation of
    `fine_amount_cents`, and the original `FINE` row's `status` becomes
    `REVERSED`."
    PRD 3.8: "The side effects differ from the round-one leg in exactly one
    respect: `hearing_round` is **incremented by 1** rather than set to 1,
    preserving the appeal count."
    PRD 2.9: "The cited violation case has not already reached a terminal
    enforcement outcome -- `CURED`, `DISMISSED`, `FINE_UPHELD`, or
    `FINE_VACATED` -- otherwise `ERR_CASE_ALREADY_TERMINAL`."

    Design: Corner/state_machines/fine_vacatur_on_appeal_round_restores_the_unit_ledger_exactly
    """
    ctx, case_id, _fined = _fined_case(api, second_meeting=True)
    get_success_data(
        api.appeal_case(
            case_id, ctx.owner("o1"), payload={"grounds": "registered service animal"}
        )
    )
    docket_hearing(ctx, case_id, "mtg2", "2026-08-25T10:00:00Z")
    notice_meeting(ctx, "mtg2")
    set_clock(api, "2026-08-25T10:00:00Z")
    convene(ctx, "mtg2", attending=("d3",))

    data = validate_success(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d3"))
    )
    assert data["status"] == "FINE_VACATED"
    assert data["hearing_round"] == 2

    rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": ctx.units["101"]})
    )
    assert meta["total_count"] == 2
    fine_row = next(row for row in rows if row["entry_type"] == "FINE")
    reversal_row = next(row for row in rows if row["entry_type"] == "REVERSAL")
    assert fine_row["status"] == "REVERSED"
    assert fine_row["amount_cents"] == 5000
    assert reversal_row["amount_cents"] == -5000
    assert reversal_row["reverses_entry_id"] == fine_row["id"]

    unit = ctx.unit("101")
    assert unit["balance_due_cents"] == 0
    assert unit["delinquency_stage"] == "CURRENT"
    assert unit["voting_eligible"] is True

    validate_error(
        api.hearing_decision(case_id, {"outcome": "VACATE"}, ctx.director("d3")),
        "ERR_CASE_ALREADY_TERMINAL",
        expected_status=409,
    )


# ======================================================================
# Delinquency ladder de-escalation
# ======================================================================
def test_partial_payment_walks_the_ladder_down_to_the_first_matching_rule(api):
    """One cent under the lien threshold moves rule 3 aside and rule 4 wins.

    The posture stays delinquent rather than jumping to CURRENT, and the lien
    stamp and voting eligibility are restored on the way down.

    PRD 3.1: "Rule 3: if `oldest_unpaid_age_days` is at least 90 and
    `balance_due_cents` is at least `lien_threshold_cents`, the posture is
    `LIEN_FILED`."
    PRD 3.1: "Rule 4: if `oldest_unpaid_age_days` is at least 30, the posture
    is `LATE_NOTICE`."
    PRD 3.1: "Falling back from `LIEN_FILED → LATE_NOTICE` (which happens when
    the balance is still positive but below `lien_threshold_cents` while
    `oldest_unpaid_age_days` is at least 30) or from `LIEN_FILED → CURRENT`
    (when the balance reaches zero or below) clears `lien_recorded_at` to null,
    sets `voting_eligible` back to true, and triggers the same `BALLOTING`
    eligible-weight recomputation."
    PRD 3.1: "The stored `PAYMENT` row records `amount_cents` as the
    arithmetic negation of the supplied figure, because a payment is a credit
    against the unit."

    Design: Corner/state_machines/partial_payment_de_escalates_lien_filed_to_late_notice_by_ladder_first_match
    """
    ctx = _one_owner_association(api)
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)

    # 2026-04-01 is 122 days before the clock epoch of 2026-08-01.
    get_success_data(
        api.create_charge(
            ctx.units["101"],
            {
                "entry_type": "COLLECTION_COST",
                "amount_cents": 200_000,
                "due_on": "2026-04-01T00:00:00Z",
                "effective_period": "2026-04",
                "memo": "collection counsel",
            },
            MANAGER_HEADERS,
        )
    )
    before = ctx.unit("101")
    assert before["oldest_unpaid_age_days"] == 122
    assert before["delinquency_stage"] == "LIEN_FILED"

    validate_success(
        api.create_payment(
            ctx.units["101"],
            {"amount_cents": 25_000, "effective_period": "2026-08", "memo": "partial"},
            ctx.owner("o1"),
        ),
        expected_status=201,
    )

    unit = ctx.unit("101")
    assert unit["balance_due_cents"] == 175_000
    assert unit["delinquency_stage"] == "LATE_NOTICE"
    assert unit["lien_recorded_at"] is None
    assert unit["voting_eligible"] is True
    assert unit["oldest_unpaid_age_days"] == 122
    assert unit["credit_balance_cents"] == 0

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["101"], "entry_type": "PAYMENT"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == -25_000


# ======================================================================
# Resale certificate lifecycle
# ======================================================================
def test_operator_void_leaves_the_certificate_fee_posted(api):
    """The operator void and the cascade void diverge on exactly the fee.

    The operator path leaves `requires_reissue` false, leaves the RESALE_FEE
    row POSTED, and re-blocks the transfer.

    PRD 3.9: "An **operator** void, a `CommunityManager` act carrying an
    optional `reason`, requires only that the `status` be `ISSUED`; it sets
    `requires_reissue` to **false** and leaves the `RESALE_FEE` row `POSTED`,
    because an operator void does not refund the fee; it recomputes the unit's
    `transfer_blocked` with `Unit.version` advancing by 1; and it advances
    `ResaleCertificate.version` by 1."
    PRD 3.9: "First the `RESALE_FEE` row is posted on the unit for
    `resale_cert_fee_cents`, with its identifier stored in `cert_fee_entry_id`,
    and the unit's `balance_due_cents` and `delinquency_stage` are recomputed
    with `Unit.version` advancing by 1."
    PRD 3.9: "Only the cascade path refunds the fee."

    Design: Corner/state_machines/operator_void_of_issued_certificate_keeps_the_fee_posted
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

    certificate = issue_certificate(ctx, "101", closing_date="2026-09-20T00:00:00Z")
    assert certificate["status"] == "ISSUED"

    data = validate_success(
        api.void_resale_certificate(
            certificate["id"], MANAGER_HEADERS, payload={"reason": "closing rescheduled"}
        )
    )
    assert data["status"] == "VOIDED"
    assert data["requires_reissue"] is False

    fee_rows, fee_meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["101"], "entry_type": "RESALE_FEE"},
        )
    )
    assert fee_meta["total_count"] == 1
    assert fee_rows[0]["status"] == "POSTED"
    assert fee_rows[0]["amount_cents"] == 35_000

    _, reversal_meta = validate_paginated(
        api.list_ledger_entries(
            MANAGER_HEADERS,
            params={"unit_id": ctx.units["101"], "entry_type": "REVERSAL"},
        )
    )
    assert reversal_meta["total_count"] == 0

    unit = ctx.unit("101")
    assert unit["balance_due_cents"] == 35_000
    assert unit["transfer_blocked"] is True
    assert unit["delinquency_stage"] == "CURRENT"


def test_closing_consumes_the_certificate_and_swaps_both_owner_counts(api):
    """Three rows move at once, and the spent certificate cannot be reused.

    PRD 3.9: "Closing the sale is a `CommunityManager` act on the unit,
    supplying `new_owner_id` and `certificate_id`, and it consumes the
    certificate by moving it `ISSUED → EXPIRED`."
    PRD 3.9: "The side effects set the unit's `current_owner_id` to the
    incoming owner and its `transfer_blocked` back to true with `Unit.version`
    advancing by 1, reduce the outgoing owner's `owned_unit_count` by 1 and
    raise the incoming owner's by 1 with both `UnitOwner.version` values
    advancing by 1, and advance `ResaleCertificate.version` by 1."
    PRD 3.9: "Three conditions apply: the named certificate's `status` must be
    `ISSUED` and the logical clock must be strictly before its `expires_at`, or
    the response is `ERR_NO_VALID_CERTIFICATE`; the unit's current `version`
    must still equal the certificate's `pinned_unit_version`, because any
    ledger movement since issuance invalidates the payoff the buyer relied on,
    and a mismatch yields `ERR_CERTIFICATE_STALE`; and the incoming owner must
    exist and belong to the same association."

    Design: Corner/state_machines/closing_consumes_the_certificate_and_swaps_both_owner_counts
    """
    ctx = _board_of_one(api)
    incoming_owner = add_owner(
        ctx, "o2", full_name="Nina Boyd", email="nina@example.test"
    )
    add_unit(ctx, "101", "o1", 5000, heated_sqft=1000)
    add_unit(ctx, "102", "o1", 5000, heated_sqft=1000)
    adopt_budget(
        ctx,
        meeting_label="mtg1",
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
    )
    certificate = issue_certificate(ctx, "101", closing_date="2026-09-20T00:00:00Z")

    payload = {"new_owner_id": incoming_owner, "certificate_id": certificate["id"]}
    data = validate_success(
        api.transfer_ownership(ctx.units["101"], payload, MANAGER_HEADERS)
    )
    assert data["current_owner_id"] == incoming_owner
    assert data["transfer_blocked"] is True

    assert (
        read_certificate(api, certificate["id"], MANAGER_HEADERS)["status"] == "EXPIRED"
    )

    owners, _ = validate_paginated(
        api.list_owners(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    outgoing_row = next(row for row in owners if row["id"] == ctx.owners["o1"])
    incoming_row = next(row for row in owners if row["id"] == incoming_owner)
    assert outgoing_row["owned_unit_count"] == 1
    assert incoming_row["owned_unit_count"] == 1

    validate_error(
        api.transfer_ownership(ctx.units["101"], payload, MANAGER_HEADERS),
        "ERR_NO_VALID_CERTIFICATE",
        expected_status=409,
    )


# ======================================================================
# Special assessment: two dimensions on one row
# ======================================================================
def test_collection_moves_only_the_funding_dimension(api):
    """Money arriving leaves `approval_status` and the designation untouched.

    PRD 3.4: "Collection progresses without touching `approval_status`, and
    only rescission moves both."
    PRD 3.4: "When a payment waterfall credits `SPECIAL_ASSESSMENT`-bucket rows
    of an approved assessment and the resulting `collected_cents` is greater
    than 0 but strictly less than `total_amount_cents`, `funding_status` moves
    `UNFUNDED → PARTIALLY_COLLECTED`, the association's
    `restricted_sa_cash_cents` rises by the applied cents with
    `Association.version` advancing by 1, and `SpecialAssessment.version`
    advances by 1."
    PRD 3.4: "On `BALLOTING → APPROVED`, the server writes
    `eligible_weight_bp`, `yes_weight_bp`, and `ballot_closed_at` from the
    logical clock, increases the association's `reserve_designated_cents` by
    `total_amount_cents` and advances `Association.version` by 1, leaves
    `funding_status` untouched at `UNFUNDED`, and advances
    `SpecialAssessment.version` by 1."
    PRD 3.4: "Each round reuses the same allocator as budget adoption, with
    one difference: the pool for rounds one through `installment_count` minus
    one is `total_amount_cents` divided by `installment_count` and rounded half
    up, while the **final** round instead uses `total_amount_cents` minus the
    sum of the pools already posted, so that the posted installments sum to
    `total_amount_cents` exactly with no drift."

    Design: Corner/state_machines/special_assessment_funding_dimension_advances_without_touching_approval
    """
    ctx = _board_of_one(api)
    add_owner(
        ctx,
        "tr",
        full_name="Tina Cole",
        email="tina@example.test",
        board_role="TREASURER",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)

    assessment = open_special_assessment(
        ctx,
        total_amount_cents=4_000_000,
        installment_count=2,
        purpose="Elevator modernization",
    )
    cast_owner_ballots(
        ctx, "SPECIAL_ASSESSMENT", assessment["id"], [("o1", "101", "YES")]
    )
    approved = get_success_data(api.close_ballot(assessment["id"], ctx.director("d1")))
    assert approved["approval_status"] == "APPROVED"

    # Round one pool = 4000000 / 2 = 2000000, all of it on the single unit.
    get_success_data(
        api.post_installment(
            assessment["id"],
            {"due_on": "2026-09-01T00:00:00Z", "effective_period": "2026-09"},
            ctx.treasurer(),
        )
    )
    set_clock(api, "2026-09-01T00:00:00Z")

    payment = validate_success(
        api.create_payment(
            ctx.units["101"],
            {
                "amount_cents": 1_000_000,
                "effective_period": "2026-09",
                "memo": "half of installment 1",
            },
            MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert payment["unapplied_cents"] == 0

    stored = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert stored["approval_status"] == "APPROVED"
    assert stored["funding_status"] == "PARTIALLY_COLLECTED"
    assert stored["collected_cents"] == 1_000_000
    assert stored["charged_cents"] == 2_000_000
    assert stored["installments_posted"] == 1

    association = ctx.association()
    assert association["restricted_sa_cash_cents"] == 1_000_000
    assert association["reserve_designated_cents"] == 4_000_000

    unit = ctx.unit("101")
    assert unit["balance_due_cents"] == 1_000_000
    assert unit["delinquency_stage"] == "CURRENT"


# ======================================================================
# Insurance claim: two dimensions on one row
# ======================================================================
def test_suit_may_be_filed_only_once_the_owners_have_funded_it(api):
    """A DENIED adjustment still walks NONE to TENDERED to IN_LITIGATION.

    The second hop is gated on a cross-entity APPROVED funding assessment, and
    once the suit is live that same assessment can no longer be defunded.

    PRD 3.7: "The `litigation_status` dimension runs over `NONE`, `TENDERED`,
    `IN_LITIGATION`, and `RESOLVED`, starting at `NONE`, and evolves entirely
    independently -- a claim can be settled for adjustment purposes while its
    suit is still tendered, and a claim can be in litigation while its
    adjustment is denied."
    PRD 3.7: "Moving `TENDERED → IN_LITIGATION` requires `litigation_status`
    to be `TENDERED` and requires that some special assessment exist whose
    `funding_claim_id` is this claim and whose `approval_status` is `APPROVED`
    -- suit may not be filed until the owners have funded it -- failing which
    the response is `ERR_LITIGATION_FUNDING_MISSING`; the only effect is that
    `InsuranceClaim.version` advances by 1."
    PRD 3.7: "`disclosure_required` is true exactly when `litigation_status`
    is `TENDERED` or `IN_LITIGATION`."
    PRD 3.4: "It is blocked when `funding_claim_id` is set and that claim's
    `litigation_status` is `IN_LITIGATION` -- a live suit cannot be defunded --
    in which case the response is `ERR_LITIGATION_ACTIVE`."
    PRD 3.4: "On success `ballot_opened_at` is stamped from the logical clock,
    `requires_supermajority_disclosure` is set to true exactly when
    `funding_claim_id` is present (and to false otherwise), forcing litigation
    disclosure on every certificate issued after approval, and
    `SpecialAssessment.version` advances by 1."

    Design: Corner/state_machines/litigation_dimension_advances_only_after_owners_fund_it_leaving_adjustment_denied
    """
    ctx = _board_of_one(api)
    add_owner(
        ctx,
        "tr",
        full_name="Tina Cole",
        email="tina@example.test",
        board_role="TREASURER",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)
    add_element(
        ctx,
        "el1",
        name="North Facade",
        element_class="FACADE",
        replacement_cost_cents=20_000_000,
        useful_life_years=40,
        effective_age_years=10,
    )

    claim = report_claim(
        ctx,
        "101",
        "el1",
        loss_type="CONSTRUCTION_DEFECT",
        loss_at="2026-05-01T00:00:00Z",
        gross_damage_cents=8_000_000,
        within_unit_boundary_cents=0,
    )
    adjust_claim(ctx, claim["id"], "DENY")
    get_success_data(
        api.set_litigation_stage(claim["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS)
    )

    assessment = open_special_assessment(
        ctx,
        total_amount_cents=6_000_000,
        installment_count=4,
        purpose="Construction defect litigation funding",
        funding_claim_id=claim["id"],
    )
    cast_owner_ballots(
        ctx, "SPECIAL_ASSESSMENT", assessment["id"], [("o1", "101", "YES")]
    )
    get_success_data(api.close_ballot(assessment["id"], ctx.director("d1")))

    data = validate_success(
        api.set_litigation_stage(
            claim["id"], {"stage": "IN_LITIGATION"}, ATTORNEY_HEADERS
        )
    )
    assert data["litigation_status"] == "IN_LITIGATION"
    assert data["adjustment_status"] == "DENIED"
    assert data["appeal_round"] == 0
    assert data["disclosure_required"] is True

    stored = read_special_assessment(api, assessment["id"], MANAGER_HEADERS)
    assert stored["approval_status"] == "APPROVED"
    assert stored["funding_status"] == "UNFUNDED"
    assert stored["requires_supermajority_disclosure"] is True

    validate_error(
        api.rescind_special_assessment(
            assessment["id"], ctx.director("d1"), payload={"reason": "board reversal"}
        ),
        "ERR_LITIGATION_ACTIVE",
        expected_status=409,
    )

    assert ctx.association()["reserve_designated_cents"] == 6_000_000
