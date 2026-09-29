"""
Declared edges and undeclared ones: initial states, side effects bound to a single
transition, oscillating edges, terminal states, and self-loops.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import fhwa_reviewer_headers, program_admin_headers

BASE = "2026-09-01T00:00:00Z"
FIELD_DAY = "2026-09-02T12:00:00Z"
QA_DAY = "2026-09-03T09:00:00Z"


# ─── A cycle opens in planning with the reserve already taken ───────────────
def test_a_new_cycle_opens_in_planning_with_the_reserve_off_the_top(client, roster):
    """
    The declared initial state, at its first version, with the default reserve
    fraction applied once to the authorised budget and the remainder equal to the
    available money.

    PRD §3.8: "A new cycle opens in `PLANNING`."
    PRD §3.8: "an optional `reserve_pct`, the contingency reserve as a fraction of
    the authorised budget, defaulting to 0.05".
    PRD §3.8: "A cycle authorised at 10,000,000,000 cents with the default reserve
    fraction reserves 500,000,000 and makes 9,500,000,000 available, with the same
    amount remaining."

    Design: Corner/state_machines/program_cycle_create_initial_state_planning_with_budget_split
    """
    cycle = fx.create_cycle(
        client,
        fiscal_year=2027,
        authorized_budget_cents=10000000000,
        ranking_policy="CONDITION_BASED",
    )

    assert cycle["status"] == "PLANNING"
    assert cycle["version"] == 1
    assert cycle["fiscal_year"] == 2027
    assert cycle["ranking_policy"] == "CONDITION_BASED"
    assert cycle["reserve_pct"] == 0.05
    assert cycle["reserve_cents"] == 500000000
    assert cycle["available_cents"] == 9500000000
    assert cycle["committed_cents"] == 0
    assert cycle["remaining_cents"] == 9500000000
    a.assert_budget_identity(cycle)


def test_a_new_cycle_starts_with_every_counter_and_stamp_empty(client, roster):
    """
    No candidate mix and no lifecycle instants yet, and the allocation read agrees
    with the cycle it summarises.

    PRD §3.8: "Three counters track the candidate mix: `identified_count`,
    `programmed_count` and `deferred_count`, each counting the cycle's candidates in
    the corresponding status and each starting at 0."
    PRD §3.8: "After every mutation the identity `authorized_budget_cents` equals
    `reserve_cents` plus `committed_cents` plus `remaining_cents` must hold."

    Design: Corner/state_machines/program_cycle_create_initial_state_planning_with_budget_split
    """
    cycle = fx.create_cycle(
        client, fiscal_year=2027, authorized_budget_cents=10000000000
    )

    assert cycle["identified_count"] == 0
    assert cycle["programmed_count"] == 0
    assert cycle["deferred_count"] == 0
    assert cycle["unprogrammed_cost_cents"] == 0
    assert cycle["locked_at"] is None
    assert cycle["submitted_at"] is None
    assert cycle["closed_at"] is None

    summary = fx.read_allocation(client, cycle["id"])
    assert summary["identity_holds"] is True
    assert (
        summary["authorized_budget_cents"]
        == summary["reserve_cents"] + summary["committed_cents"] + summary["remaining_cents"]
    )
    a.assert_allocation_summary_matches_cycle(summary, cycle)


# ─── Finalising a low-risk evaluation ───────────────────────────────────────
def _finalised_low_risk_evaluation(client, roster, bridge):
    """A code-5 evaluation on the water-crossing structure, taken to `FINAL`."""
    evaluation = fx.create_scour_evaluation(
        client,
        bridge["id"],
        roster,
        5,
        evaluation_method="HEC18_SCREENING",
        foundation_type="PILE",
        observed_scour_depth_m=0.4,
    )
    return fx.finalize_scour(client, evaluation["id"], roster)


def test_finalising_a_code_five_evaluation_publishes_low_risk_to_the_structure(
    client, roster, bridge
):
    """
    Code 5 sits inside the middle band, so the evaluation becomes final and writes
    that band through to the structure, whose version moves exactly once for the
    write-through hop.

    PRD §3.6: "a code of 3 or below is `SCOUR_CRITICAL`, a code from 4 through 6 is
    `LOW_RISK`, and a code of 7 or above is `STABILIZED`."
    PRD §3.6: "**Hop 1** sets `status` to `FINAL` and stamps `finalized_at` from the
    logical clock. **Hop 2**, caused by hop 1, writes the evaluation's
    `derived_scour_status` through to the structure's `scour_status` ... and increments
    the structure's `version` by one."

    Design: Corner/state_machines/scour_evaluation_finalize_low_risk_valid_transition
    """
    finalised = _finalised_low_risk_evaluation(client, roster, bridge)

    assert finalised["status"] == "FINAL"
    assert finalised["derived_scour_status"] == "LOW_RISK"
    a.assert_instant_equals(finalised["finalized_at"], BASE, "finalized_at")

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["scour_status"] == "LOW_RISK"
    a.assert_version_advanced_by(structure["version"], 1, 1, "bridge")


def test_a_low_risk_result_owes_no_plan_and_leaves_the_cycle_alone(
    client, roster, bridge
):
    """
    Only a scour-critical result tightens the interval and creates an obligation: a
    low-risk structure keeps its standard cycle, stays compliant, and owes no plan.

    PRD §3.6: "**Hop 3** fires only when hop 2 set the status to `SCOUR_CRITICAL`
    *and* the structure has no existing plan of action in `REQUIRED`, `DRAFT`,
    `SUBMITTED` or `APPROVED`".
    PRD §3.6: "That flag is false exactly when `scour_status` is `SCOUR_CRITICAL` and
    no plan of action for the structure is `APPROVED`, and true in every other case —
    including on structures that are `LOW_RISK`, `STABILIZED` or `NOT_EVALUATED`."

    Design: Corner/state_machines/scour_evaluation_finalize_low_risk_valid_transition
    """
    _finalised_low_risk_evaluation(client, roster, bridge)

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["inspection_interval_months"] == 24
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2028-09-01", "next_inspection_due_date"
    )
    assert structure["poa_compliant"] is True

    rows, meta = validate_paginated(
        client.list_plans_of_action(program_admin_headers(), {"bridge_id": bridge["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


# ─── A scour evaluation on a structure that crosses no water ────────────────
def test_a_dry_structure_cannot_be_evaluated_for_scour_at_all(client, roster):
    """
    The water-crossing precondition is enforced as an applicability failure, not as a
    missing resource or a bad state, and no draft evaluation survives the attempt.

    PRD §3.6: "Only structures whose `spans_water` flag is true may be evaluated for
    scour; requesting an evaluation on a structure that does not cross water is
    `ERR_INSPECTION_TYPE_NOT_APPLICABLE`, the same rule that guards inapplicable
    inspection types."
    PRD §2.8: "15. **Inspection-type applicability** —
    `ERR_INSPECTION_TYPE_NOT_APPLICABLE` (422). Applies to inspection creation and
    scour-evaluation creation."

    Design: Corner/state_machines/scour_evaluation_on_dry_structure_rejected
    """
    overpass = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000003",
            name="Granite Ridge Overpass",
            structure_type="ARCH",
            deck_area_sqm=800,
            year_built=1995,
            adt=4000,
            detour_length_km=5.0,
        ),
    )
    assert overpass["spans_water"] is False

    response = client.create_scour_evaluation(
        overpass["id"],
        f.scour_evaluation_payload(
            roster.engineer_id,
            2,
            evaluation_method="FIELD_OBSERVATION",
            foundation_type="SPREAD_FOOTING",
        ),
        roster.engineer_headers,
    )

    validate_error(response, e.ERR_INSPECTION_TYPE_NOT_APPLICABLE, 422)
    evaluations, meta = validate_paginated(
        client.list_scour_evaluations(
            program_admin_headers(), {"bridge_id": overpass["id"]}
        )
    )
    assert evaluations == []
    assert meta["total_count"] == 0

    structure = fx.read_bridge(client, overpass["id"])
    assert structure["scour_status"] == "NOT_EVALUATED"
    assert structure["version"] == 1
    assert fx.plans_for_bridge(client, overpass["id"]) == []


# ─── Claiming a submitted report for review ─────────────────────────────────
def _claimed_report(client, roster, bridge):
    """A baseline report submitted on the field day and claimed the next morning."""
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    fx.set_clock(client, FIELD_DAY)
    submitted = fx.submit_report(client, draft["inspection"]["id"], roster)
    fx.set_clock(client, QA_DAY)
    claimed = fx.qa_claim(client, draft["inspection"]["id"], roster)
    return {"submitted": submitted, "claimed": claimed}


def test_claiming_a_report_stamps_the_reviewer_and_the_claim_instant(
    client, roster, bridge
):
    """
    The claim applies exactly its three declared effects and disturbs nothing the
    submission had already settled — the frozen index and the earlier submission
    instant both survive it.

    PRD §3.3: "A `QaReviewer` claiming a report takes it from `SUBMITTED` to `IN_QA`,
    which sets the report's `qa_reviewer_id` to the claiming user's `X-User-ID` and
    stamps `qa_claimed_at` from the logical clock."
    PRD §3.3: "For a report carrying deck 82.00, girder 40.00, bearing 50.00 and
    abutment 95.00, the weights sum to 0.30 plus 0.25 plus 0.10 plus 0.10, which is
    0.75; the weighted scores sum to 24.60 plus 10.00 plus 5.00 plus 9.50, which is
    49.10; and 49.10 divided by 0.75 is 65.4666…, giving 65.47."

    Design: Corner/state_machines/inspection_qa_claim_side_effects_stamp_reviewer_and_clock
    """
    setup = _claimed_report(client, roster, bridge)
    claimed = setup["claimed"]

    assert claimed["status"] == "IN_QA"
    assert claimed["qa_reviewer_id"] == roster.reviewer_id
    a.assert_instant_equals(claimed["qa_claimed_at"], QA_DAY, "qa_claimed_at")
    a.assert_instant_equals(claimed["submitted_at"], FIELD_DAY, "submitted_at")
    assert claimed["accepted_at"] is None
    assert claimed["returned_count"] == 0
    assert claimed["qa_escalation_required"] is False
    assert claimed["bridge_health_index"] == 65.47


def test_the_claim_publishes_nothing_to_the_inventory(client, roster, bridge):
    """
    Publication is bound to acceptance alone: after the claim the structure still
    carries its creation seeds, has never been inspected, and its version has not
    moved.

    PRD §3.3: "An `ACCEPT` decision takes the report from `IN_QA` to `ACCEPTED`,
    stamps `accepted_at` from the logical clock, and triggers the five-hop
    publication cascade that is the structural heart of this system."
    PRD §2.9: "because so many operations advance a structure's `version` — every
    rating create, every rating approval, every restriction, every finding, every
    acceptance cascade, every scour finalisation, every inventory attribute edit".

    Design: Corner/state_machines/inspection_qa_claim_side_effects_stamp_reviewer_and_clock
    """
    _claimed_report(client, roster, bridge)

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["version"] == 1
    assert structure["deck_rating"] == 7
    assert structure["superstructure_rating"] == 7
    assert structure["substructure_rating"] == 7
    assert structure["min_nbi_rating"] == 7
    assert structure["bridge_health_index"] is None
    assert structure["last_routine_inspection_date"] is None
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2028-09-01", "next_inspection_due_date"
    )


# ─── The cycle's oscillating edge ───────────────────────────────────────────
def test_locking_then_reopening_returns_the_cycle_to_planning(client, roster, bridge):
    """
    The reopen restores planning but keeps the lock instant on the record as the most
    recent lock, and each hop is one version.

    PRD §3.8: "A `ProgramAdmin` locks the cycle to freeze its programme for
    reporting, moving it `PLANNING → LOCKED` and stamping `locked_at` from the
    logical clock."
    PRD §3.8: "Reopening moves it `LOCKED → PLANNING` and *retains* `locked_at` as
    the instant of the most recent lock rather than clearing it, so the cycle may
    oscillate between planning and locked as many times as needed before reporting."

    Design: Corner/state_machines/program_cycle_lock_then_reopen_returns_to_planning
    """
    cycle = fx.create_cycle(client, fiscal_year=2027)

    locked = fx.lock_cycle(client, cycle["id"])
    assert locked["status"] == "LOCKED"
    a.assert_instant_equals(locked["locked_at"], BASE, "locked_at")

    reopened = validate_success(
        client.reopen_program_cycle(cycle["id"], program_admin_headers()), 200
    )
    assert reopened["status"] == "PLANNING"
    a.assert_instant_equals(reopened["locked_at"], BASE, "locked_at")
    a.assert_version_advanced_by(reopened["version"], cycle["version"], 2, "cycle")


def test_the_money_is_identical_before_the_lock_and_after_the_reopen(
    client, roster, bridge
):
    """
    Freezing and unfreezing the programme moves no money: all four buckets read the
    same on either side of the round trip.

    PRD §3.8: "`reserve_cents` is the reserve fraction multiplied by the authorised
    budget, rounded half up, and it comes off the top; it is computed **once, at
    creation, and never recomputed**".
    PRD §3.8: "`committed_cents` is the sum of `estimated_cost_cents` over the
    cycle's candidates whose `status` is `PROGRAMMED`, and starts at 0."

    Design: Corner/state_machines/program_cycle_lock_then_reopen_returns_to_planning
    """
    cycle = fx.create_cycle(client, fiscal_year=2027)
    before = {
        field: cycle[field]
        for field in (
            "reserve_cents",
            "available_cents",
            "committed_cents",
            "remaining_cents",
        )
    }

    fx.lock_cycle(client, cycle["id"])
    validate_success(
        client.reopen_program_cycle(cycle["id"], program_admin_headers()), 200
    )

    after = fx.read_cycle(client, cycle["id"])
    assert {field: after[field] for field in before} == before
    assert before == {
        "reserve_cents": 500000000,
        "available_cents": 9500000000,
        "committed_cents": 0,
        "remaining_cents": 9500000000,
    }
    a.assert_budget_identity(after)


def test_a_locked_cycle_refuses_candidates_and_a_reopened_one_stops_refusing_them(
    client, roster, bridge
):
    """
    While the cycle is locked the identification is refused on cycle state; after the
    reopen the cycle state no longer decides the outcome and the request falls
    through to the condition-data rule instead.

    PRD §3.8: "While locked, candidate identification, programming, withdrawal and
    deferral are all blocked — every one of those actions requires `PLANNING`."
    PRD §3.8: "the structure must have at least one `ACCEPTED` inspection; a
    structure that has never had a report accepted cannot be programmed and the
    attempt fails with `ERR_BRIDGE_NOT_INSPECTED`."

    Design: Corner/state_machines/program_cycle_lock_then_reopen_returns_to_planning
    """
    cycle = fx.create_cycle(client, fiscal_year=2027)
    fx.lock_cycle(client, cycle["id"])

    while_locked = client.create_project_candidate(
        cycle["id"],
        f.candidate_payload(
            fx.read_cycle(client, cycle["id"])["version"], bridge["id"]
        ),
        roster.district_headers,
    )
    validate_error(while_locked, e.ERR_PROGRAM_STATE_INVALID, 409)

    validate_success(
        client.reopen_program_cycle(cycle["id"], program_admin_headers()), 200
    )
    after_reopen = client.create_project_candidate(
        cycle["id"],
        f.candidate_payload(
            fx.read_cycle(client, cycle["id"])["version"], bridge["id"]
        ),
        roster.district_headers,
    )

    validate_error(after_reopen, e.ERR_BRIDGE_NOT_INSPECTED, 422)
    assert fx.candidates_in_cycle(client, cycle["id"]) == []


# ─── An undeclared QA edge ──────────────────────────────────────────────────
def test_a_draft_report_cannot_be_claimed_for_review(client, roster, bridge):
    """
    The claim edge starts at submission, so claiming a report that was never
    submitted is a state conflict even though the caller is a fully qualified
    reviewer — and the claim fields stay empty.

    PRD §3.3: "A `SUBMITTED` report is then claimed for review."
    PRD §2.8: "9. **State gating** — the target resource, and any parent whose state
    gates the operation, is in a state from which the requested transition is
    declared, else the family-scoped 409 conflict code: `ERR_INSPECTION_STATE_INVALID`,
    `ERR_RATING_STATE_INVALID`, `ERR_FINDING_STATE_INVALID`,
    `ERR_PERMIT_STATE_INVALID` or `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/state_machines/inspection_qa_claim_on_draft_returns_409
    """
    draft = fx.open_inspection(client, bridge["id"], roster)

    claim = client.qa_claim_inspection(draft["id"], roster.reviewer_headers)
    validate_error(claim, e.ERR_INSPECTION_STATE_INVALID, 409)

    decision = client.qa_decision_inspection(
        draft["id"], f.qa_decision_payload("ACCEPT"), roster.reviewer_headers
    )
    validate_error(decision, e.ERR_INSPECTION_STATE_INVALID, 409)

    report = fx.read_inspection(client, draft["id"])
    assert report["status"] == "DRAFT"
    assert report["qa_reviewer_id"] is None
    assert report["qa_claimed_at"] is None
    assert fx.read_bridge(client, bridge["id"])["version"] == 1


# ─── A plan submitted before it was drafted ─────────────────────────────────
def _structure_owing_a_plan(client, roster, bridge):
    """A scour-critical structure with the plan the finalisation cascade created."""
    evaluation = fx.create_scour_evaluation(
        client,
        bridge["id"],
        roster,
        2,
        evaluation_method="DETAILED_HYDRAULIC",
        foundation_type="SPREAD_FOOTING",
        observed_scour_depth_m=2.6,
    )
    fx.finalize_scour(client, evaluation["id"], roster)
    plans = fx.plans_for_bridge(client, bridge["id"])
    assert len(plans) == 1
    return plans[0]


def test_a_plan_still_in_required_cannot_be_submitted_for_approval(
    client, roster, bridge
):
    """
    Submission starts from draft, so the bare obligation cannot be pushed straight to
    the district — the structure stays non-compliant on its tightened cycle.

    PRD §3.6: "Submitting the plan for district approval, again open to a
    `DistrictEngineer` or a `BridgeInspector`, is permitted only from `DRAFT`".
    PRD §3.6: "A plan created by the cascade starts at `REQUIRED` — the obligation
    exists but nothing has been committed."

    Design: Corner/state_machines/plan_of_action_submit_from_required_state_rejected
    """
    plan = _structure_owing_a_plan(client, roster, bridge)

    response = client.submit_plan_of_action(plan["id"], roster.district_headers)

    validate_error(response, e.ERR_RATING_STATE_INVALID, 409)
    unchanged = fx.read_plan(client, plan["id"])
    assert unchanged["status"] == "REQUIRED"
    assert unchanged["submitted_at"] is None
    assert unchanged["revision_count"] == 0

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["scour_status"] == "SCOUR_CRITICAL"
    assert structure["poa_compliant"] is False
    assert structure["inspection_interval_months"] == 12


def test_drafting_the_plan_first_makes_the_identical_submission_legal(
    client, roster, bridge
):
    """
    One write of the three commitments moves the plan out of the bare obligation and
    into draft, from where the same submission is accepted and stamped.

    PRD §3.6: "Drafting is permitted whenever the plan is in `REQUIRED` or `DRAFT`.
    From `REQUIRED` it moves the plan to `DRAFT`".
    PRD §3.6: "Submission moves it `DRAFT → SUBMITTED` and stamps `submitted_at`
    from the logical clock."

    Design: Corner/state_machines/plan_of_action_submit_from_required_state_rejected
    """
    plan = _structure_owing_a_plan(client, roster, bridge)
    validate_error(
        client.submit_plan_of_action(plan["id"], roster.district_headers),
        e.ERR_RATING_STATE_INVALID,
        409,
    )

    drafted = validate_success(
        client.update_plan_of_action(
            plan["id"],
            f.plan_of_action_payload(3, 4.5, countermeasure_type="RIPRAP"),
            roster.district_headers,
        ),
        200,
    )
    assert drafted["status"] == "DRAFT"

    submitted = validate_success(
        client.submit_plan_of_action(plan["id"], roster.district_headers), 200
    )
    assert submitted["status"] == "SUBMITTED"
    a.assert_instant_equals(submitted["submitted_at"], BASE, "submitted_at")


# ─── Replaying the plan's draft self-loop ───────────────────────────────────
def _plan_drafted_twice_with_the_same_content(client, roster, bridge):
    """The cascade-made plan, written with identical content two requests running."""
    plan = _structure_owing_a_plan(client, roster, bridge)
    content = f.plan_of_action_payload(3, 4.5, countermeasure_type="RIPRAP")
    first = validate_success(
        client.update_plan_of_action(plan["id"], content, roster.district_headers), 200
    )
    second = validate_success(
        client.update_plan_of_action(plan["id"], content, roster.district_headers), 200
    )
    return {"first": first, "second": second}


def test_replaying_the_same_plan_content_changes_nothing_at_all(client, roster, bridge):
    """
    The draft self-loop may be repeated freely: the second identical write leaves the
    state, the three commitments and the revision counter exactly where the first one
    left them, and the structure is untouched because only approval reaches it.

    PRD §3.6: "from `DRAFT` it overwrites the stored content and leaves the plan in
    `DRAFT`, a self-loop that may be repeated freely and that never touches
    `revision_count`."
    PRD §3.6: "`RETURN` sends the plan back `SUBMITTED → DRAFT`, increments
    `revision_count` by one, and stores the `return_note`".

    Design: Corner/state_machines/plan_of_action_put_repeated_same_payload_is_idempotent
    """
    setup = _plan_drafted_twice_with_the_same_content(client, roster, bridge)
    first, second = setup["first"], setup["second"]

    assert first["status"] == "DRAFT"
    assert second["status"] == "DRAFT"
    assert second["monitoring_frequency_months"] == 3
    assert second["closure_trigger_stage_m"] == 4.5
    assert second["countermeasure_type"] == "RIPRAP"
    assert second["revision_count"] == 0
    assert second["submitted_at"] is None
    assert second["approved_at"] is None
    assert second["id"] == first["id"]
    assert len(fx.plans_for_bridge(client, bridge["id"])) == 1
    assert fx.read_bridge(client, bridge["id"])["poa_compliant"] is False


# ─── An accepted package, and the two terminal states it creates ────────────
def _accepted_federal_package(client, roster, bridge):
    """A locked cycle whose package has been sent and then accepted by the FHWA."""
    cycle = fx.create_cycle(client, fiscal_year=2027)
    submission = fx.start_submission(client, cycle["id"], submission_type="NBI_ANNUAL")
    fx.lock_cycle(client, cycle["id"])
    fx.send_submission(client, submission["id"])
    reviewed = fx.review_submission(
        client, submission["id"], "ACCEPT", fhwa_reviewer_headers()
    )
    return {"cycle": cycle, "submission": submission, "reviewed": reviewed}


def test_acceptance_closes_the_cycle_and_freezes_the_snapshot(client, roster, bridge):
    """
    A single never-inspected structure whose first due date is still two years out is
    fully compliant, so the package is accepted and its owning cycle closes on the
    same instant.

    PRD §3.9: "Acceptance moves the submission `SUBMITTED → ACCEPTED`, stamps
    `reviewed_at` from the logical clock, records `reviewer_user_id`, and moves the
    owning cycle `SUBMITTED → CLOSED` with `closed_at` stamped."
    PRD §3.9: "`overdue_inspection_count` is the number of structures whose
    `next_inspection_due_date` falls **strictly before** the logical clock's current
    date — a structure whose due date *is* today is compliant, not overdue."

    Design: Corner/state_machines/federal_submission_accepted_is_terminal_and_locks_cycle
    """
    setup = _accepted_federal_package(client, roster, bridge)
    reviewed = setup["reviewed"]

    assert reviewed["status"] == "ACCEPTED"
    a.assert_instant_equals(reviewed["reviewed_at"], BASE, "reviewed_at")
    assert reviewed["reviewer_user_id"] is not None
    assert reviewed["reviewer_user_id"] != reviewed["submitted_by_user_id"]
    assert reviewed["rejection_reason_code"] == "NONE"
    assert reviewed["total_bridge_count"] == 1
    assert reviewed["overdue_inspection_count"] == 0
    assert reviewed["inspection_compliance_pct"] == 100.00
    assert reviewed["poa_noncompliant_count"] == 0
    assert reviewed["open_immediate_finding_count"] == 0
    assert reviewed["error_count"] == 0

    cycle = fx.read_cycle(client, setup["cycle"]["id"])
    assert cycle["status"] == "CLOSED"
    a.assert_instant_equals(cycle["closed_at"], BASE, "closed_at")


def test_neither_the_accepted_package_nor_the_closed_cycle_moves_again(
    client, roster, bridge
):
    """
    Three attempts to leave the two terminal states — a second review, a resend and a
    reopen of the closed cycle — are each refused on program state, and the accepted
    snapshot is unchanged by all of them.

    PRD §3.9: "`ACCEPTED` is terminal for the submission and `CLOSED` is terminal for
    the cycle."
    PRD §3.9: "Submission is a `ProgramAdmin` action permitted from either `BUILDING`
    or `REJECTED` — the latter is the resubmission path."
    PRD §3.8: "Reopening moves it `LOCKED → PLANNING`".

    Design: Corner/state_machines/federal_submission_accepted_is_terminal_and_locks_cycle
    """
    setup = _accepted_federal_package(client, roster, bridge)
    submission_id = setup["submission"]["id"]
    cycle_id = setup["cycle"]["id"]

    validate_error(
        client.review_federal_submission(
            submission_id, f.review_payload("REJECT"), fhwa_reviewer_headers()
        ),
        e.ERR_PROGRAM_STATE_INVALID,
        409,
    )
    validate_error(
        client.submit_federal_submission(submission_id, program_admin_headers()),
        e.ERR_PROGRAM_STATE_INVALID,
        409,
    )
    validate_error(
        client.reopen_program_cycle(cycle_id, program_admin_headers()),
        e.ERR_PROGRAM_STATE_INVALID,
        409,
    )

    submission = fx.read_submission(client, submission_id)
    assert submission["status"] == "ACCEPTED"
    assert submission["rejection_reason_code"] == "NONE"
    assert submission["inspection_compliance_pct"] == 100.00
    assert fx.read_cycle(client, cycle_id)["status"] == "CLOSED"
