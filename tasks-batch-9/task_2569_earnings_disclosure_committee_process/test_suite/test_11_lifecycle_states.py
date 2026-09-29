"""Where each machine starts, how a declared edge moves it, and what happens to
the edges that are not declared.

The rows here are watched at birth, across one legal transition, against a
precondition that fails, and after the same trigger has already fired once.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_instant_equals, assert_money
from test_helpers.factories import action_payload, charter_payload, member_payload
from test_helpers.fixtures import (
    add_milestone,
    assess_correction,
    build_committee,
    build_cycle,
    complete_milestone,
    cycle_action,
    deficiencies_of,
    log_material_event,
    mitigate_deficiency,
    open_close,
    refresh_cycle,
    refresh_document,
    register_cert,
    scenario_close_open,
    scenario_review_open,
    set_clock,
    start_milestone,
    withdraw_subcert,
)
from test_helpers.test_users import admin_headers

BIRTH_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
]
SOLE_FINANCE_SEAT = [("fin", "Nora Finance", "FINANCE", False, True)]
EVENT_DESCRIPTION = "Goodwill impairment indicator identified in the retail segment."


def test_six_machines_read_their_declared_initial_state_at_birth(api):
    """A charter is born a draft, a seat active, a cycle at the head of both of
    its axes at once, a milestone planned with neither actual instant stamped, a
    certification slot blocked rather than eligible even though nothing yet
    blocks it, and an event unassessed with its severity already scored but its
    deadline still unset — and merely logging that event puts the cycle's open
    count at one.

    PRD 3.3: "New milestones are persisted with `status` `PLANNED` and with both `actual_start_utc` and `actual_end_utc` null."

    PRD 3.8: "The row is then persisted with `assessment_status` `UNASSESSED`, `determination_note` null, `linked_document_id` null and `current_report_deadline_utc` null."

    Design: Corner/state_machines/freshly_created_rows_land_in_their_declared_initial_states
    """
    committee = build_committee(
        api,
        seats=BIRTH_SEATS,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Q2 Disclosure Committee Charter",
        chair_key="fin",
    )
    cycle = build_cycle(api, committee)
    assert cycle["status"] == "PLANNING"
    assert cycle["restatement_stage"] == "NONE"

    newborn_charter = validate_success(
        api.create_charter(charter_payload("Charter Z", "Z-1", 1, ["LEGAL"]),
                           admin_headers()),
        201,
    )
    assert newborn_charter["status"] == "DRAFT"
    newborn_seat = validate_success(
        api.create_member(
            newborn_charter["id"],
            member_payload("Zara Legal", "LEGAL", False, True),
            admin_headers(),
        ),
        201,
    )
    assert newborn_seat["status"] == "ACTIVE"

    milestone = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    assert milestone["status"] == "PLANNED"
    assert milestone["actual_start_utc"] is None
    assert milestone["actual_end_utc"] is None

    cert = register_cert(api, cycle["id"], committee, "ceo", "CEO_302")
    assert cert["status"] == "BLOCKED"
    assert cert["signed_utc"] is None
    assert cert["attestation_text"] is None
    assert cert["coverage_pct_at_signing"] is None

    event = log_material_event(
        api, committee, cycle["id"],
        category="IMPAIRMENT",
        occurred_utc="2026-07-20T10:00:00Z",
        discovered_utc="2026-07-22T10:00:00Z",
        magnitude_amount=200000,
        description=EVENT_DESCRIPTION,
        actor="admin",
    )
    assert event["assessment_status"] == "UNASSESSED"
    assert_money(event["severity_score"], 2.00)
    assert event["current_report_deadline_utc"] is None
    assert event["linked_document_id"] is None

    assert refresh_cycle(api, cycle["id"])["open_material_event_count"] == 1


def _lone_close_window(api, name):
    """A CLOSE_OPEN cycle whose only milestone is the close window."""
    committee = build_committee(
        api,
        seats=SOLE_FINANCE_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name=name,
        chair_key="fin",
    )
    cycle = build_cycle(api, committee)
    milestone = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    return committee, cycle, milestone


def test_start_and_complete_stamp_the_clock_and_empty_the_slack_input_set(api):
    """Each of the milestone's two declared edges stamps the instant the logical
    clock read when it was issued, and completing the row takes it out of the
    cycle's slack input set: the aggregate jumps from the row's own figures to
    the empty-set sentinel while the row itself keeps those figures frozen.

    PRD 3.3: "Completing it moves from `IN_PROGRESS` to `COMPLETE`, stamps `actual_end_utc`, and — because the row now drops out of the open input set — re-runs the slack computation for the cycle."

    Design: Corner/state_machines/milestone_start_then_complete_stamps_both_clock_instants_and_drops_out_of_the_slack_set
    """
    committee, cycle, milestone = _lone_close_window(api, "Milestone Life Charter")

    set_clock(api, "2026-08-02T09:00:00Z")
    started = start_milestone(api, committee, milestone["id"])
    assert started["status"] == "IN_PROGRESS"
    assert_instant_equals(started["actual_start_utc"], "2026-08-02T09:00:00Z")
    assert started["actual_end_utc"] is None

    mid_flight = refresh_cycle(api, cycle["id"])
    assert mid_flight["min_slack_days_calendar"] == 7
    assert mid_flight["min_slack_days_business"] == 5

    set_clock(api, "2026-08-02T15:30:00Z")
    completed = complete_milestone(api, committee, milestone["id"])
    assert completed["status"] == "COMPLETE"
    assert_instant_equals(completed["actual_end_utc"], "2026-08-02T15:30:00Z")
    assert_instant_equals(completed["actual_start_utc"], "2026-08-02T09:00:00Z")
    assert completed["slack_calendar_days"] == 7
    assert completed["slack_business_days"] == 5
    assert completed["version"] == 3

    after = refresh_cycle(api, cycle["id"])
    assert after["min_slack_days_calendar"] == 9999
    assert after["min_slack_days_business"] == 9999


QUORUM_SHORT_SEATS = [
    ("fin1", "Nora Finance", "FINANCE", False, True),
    ("fin2", "Owen Finance", "FINANCE", False, True),
]


def test_adoption_reports_quorum_and_coverage_through_two_separate_codes(api):
    """One charter satisfies neither condition's neighbour: it has two voting
    seats against a quorum of three, so it fails on quorum; the other satisfies
    quorum with the same two seats but names three required functions its seats
    do not cover, so it survives the quorum rule and fails one rule later. Both
    stay draft with no adoption stamp.

    PRD 3.1: "The charter's `active_voting_member_count` must be greater than or equal to its `min_quorum_count`, otherwise `ERR_QUORUM_NOT_MET`."

    PRD 3.1: "And every function named in `required_functions` must appear in `covered_functions`, otherwise `ERR_FUNCTION_COVERAGE_GAP`."

    Design: Corner/state_machines/charter_adoption_enforces_quorum_before_function_coverage
    """
    short_quorum = build_committee(
        api,
        seats=QUORUM_SHORT_SEATS,
        min_quorum_count=3,
        required_functions=["FINANCE"],
        name="Charter P",
        version_label="P-1",
        adopt=False,
    )
    gapped_coverage = build_committee(
        api,
        seats=[
            ("fin1", "Pia Finance", "FINANCE", False, True),
            ("fin2", "Quin Finance", "FINANCE", False, True),
        ],
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL", "OPERATIONS"],
        name="Charter Q",
        version_label="Q-1",
        adopt=False,
    )

    validate_error(
        api.transition_charter(
            short_quorum.id, action_payload("ADOPT"), short_quorum.chair("fin1")
        ),
        "ERR_QUORUM_NOT_MET",
        409,
    )
    validate_error(
        api.transition_charter(
            gapped_coverage.id, action_payload("ADOPT"), gapped_coverage.chair("fin1")
        ),
        "ERR_FUNCTION_COVERAGE_GAP",
        409,
    )

    first = validate_success(api.get_charter(short_quorum.id, admin_headers()))
    assert first["status"] == "DRAFT"
    assert first["adopted_at_utc"] is None
    assert first["active_voting_member_count"] == 2

    second = validate_success(api.get_charter(gapped_coverage.id, admin_headers()))
    assert second["status"] == "DRAFT"
    assert second["adopted_at_utc"] is None
    assert second["active_voting_member_count"] == 2
    assert second["covered_functions"] == ["FINANCE"]


CERTIFICATION_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
    ("cfo", "Sam Fiscal", "FINANCE", True, True),
]


def _milestone_of(api, cycle_id, kind):
    rows = validate_success(api.list_cycle_milestones(cycle_id, admin_headers()))
    matches = [row for row in rows if row["kind"] == kind]
    assert len(matches) == 1
    return matches[0]


def _cert(api, cert_id):
    return validate_success(api.get_officer_cert(cert_id, admin_headers()))


def _certification_eve(api):
    """A cycle standing one transition short of certification: the close and the
    review are complete, the filing window is still planned and ahead of the
    clock, one request covers the whole scope, the periodic filing is approved
    and both quarterly slots are registered and blocked."""
    committee = build_committee(
        api,
        seats=CERTIFICATION_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Certification Eve Charter",
    )
    scenario = scenario_review_open(
        api, committee, calendar=("CLOSE", "REVIEW", "FILING")
    )
    scenario.assign("fin", "REVENUE")
    scenario.submit("fin")
    scenario.approved_periodic_filing()
    scenario.run("REVIEW")
    ceo = scenario.cert("ceo", "CEO_302")
    cfo = scenario.cert("cfo", "CFO_302")
    return scenario, ceo, cfo


def test_opening_certification_carries_every_declared_side_effect_of_the_one_call(api):
    """One transition does five things at once: the workflow axis moves to
    CERTIFICATION_OPEN, both blocked slots are released to ELIGIBLE and each
    bumps its own version to 2, coverage is recomputed to 100.00, the breach
    sweep leaves the filing window PLANNED because its end is still ahead of the
    clock, the slack aggregate reads that single open row as one calendar and one
    business day, and the cycle's own version rises by exactly one.

    PRD 3.3: "Opening certification moves it from `REVIEW_OPEN` to `CERTIFICATION_OPEN` and requires that at least one `REVIEW` milestone exist — otherwise `ERR_MILESTONE_MISSING` — that every `REVIEW` milestone be `COMPLETE` — otherwise `ERR_MILESTONE_INCOMPLETE` — and that at least one draft document on the cycle with `doc_type` `PERIODIC_FILING` be in `APPROVED` status, otherwise `ERR_FILING_DOCUMENT_INVALID`."

    PRD 3.8: "A slot moves from `BLOCKED` to `ELIGIBLE` when the cycle enters `CERTIFICATION_OPEN` with `open_material_event_count` at zero, and when a material event resolution brings that count down to zero while the cycle is in `CERTIFICATION_OPEN`."

    Design: Corner/state_machines/open_certification_applies_every_declared_side_effect_of_the_transition
    """
    scenario, ceo, cfo = _certification_eve(api)
    assert ceo["status"] == "BLOCKED"
    assert cfo["status"] == "BLOCKED"
    assert ceo["version"] == 1
    assert cfo["version"] == 1

    before = scenario.reload()
    assert before["status"] == "REVIEW_OPEN"
    assert before["open_material_event_count"] == 0
    version_before = scenario.version()

    opened = scenario.open_certification()
    assert opened["status"] == "CERTIFICATION_OPEN"
    assert_money(opened["certification_coverage_pct"], 100.00)
    assert opened["min_slack_days_calendar"] == 1
    assert opened["min_slack_days_business"] == 1
    assert opened["version"] == version_before + 1

    released_ceo = _cert(api, ceo["id"])
    released_cfo = _cert(api, cfo["id"])
    assert released_ceo["status"] == "ELIGIBLE"
    assert released_ceo["version"] == 2
    assert released_cfo["status"] == "ELIGIBLE"
    assert released_cfo["version"] == 2

    filing = _milestone_of(api, scenario.cycle_id, "FILING")
    assert filing["status"] == "PLANNED"
    assert filing["slack_calendar_days"] == 1
    assert filing["slack_business_days"] == 1
    assert _milestone_of(api, scenario.cycle_id, "CLOSE")["status"] == "COMPLETE"
    assert _milestone_of(api, scenario.cycle_id, "REVIEW")["status"] == "COMPLETE"


PLANNING_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]


def test_the_three_cycle_actions_undeclared_from_planning_report_invalid_state(api):
    """From PLANNING only opening the close and abandoning are declared, so
    opening review, opening certification and declaring filing readiness are all
    refused on the state rule — each issued by a role the request layer accepts
    for that action, so no 403 can pre-empt the answer, and each on a cycle that
    carries no milestone at all, so the weaker missing-milestone complaint would
    also hold; the state rule wins and the cycle is left untouched at version 1.

    PRD 2.9: "Separately, a requested transition must be declared from the row's current state, and the parent row must be in a state that admits the write."

    PRD 2.9: "A violation of either is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/undeclared_actions_on_a_planning_cycle_report_invalid_state
    """
    committee = build_committee(
        api,
        seats=PLANNING_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Planning Only Charter",
    )
    cycle = build_cycle(api, committee)
    assert cycle["status"] == "PLANNING"
    assert cycle["version"] == 1
    assert validate_success(api.list_cycle_milestones(cycle["id"], admin_headers())) == []

    validate_error(
        api.transition_cycle(
            cycle["id"], action_payload("OPEN_REVIEW"), committee.controller("fin")
        ),
        "ERR_INVALID_STATE",
        409,
    )
    validate_error(
        api.transition_cycle(
            cycle["id"], action_payload("OPEN_CERTIFICATION"), committee.chair("legal")
        ),
        "ERR_INVALID_STATE",
        409,
    )
    validate_error(
        api.transition_cycle(
            cycle["id"],
            action_payload("DECLARE_FILING_READY"),
            committee.chair("legal"),
        ),
        "ERR_INVALID_STATE",
        409,
    )

    after = refresh_cycle(api, cycle["id"])
    assert after["status"] == "PLANNING"
    assert after["version"] == 1


TERMINAL_A_SEATS = [("fin", "Ada Finance", "FINANCE", False, True)]
TERMINAL_B_SEATS = [
    ("fin", "Ben Finance", "FINANCE", False, True),
    ("spare", "Cleo Ops", "OPERATIONS", False, False),
]


def _terminal_rows(api):
    """Three rows sitting in three different terminal states: a superseded
    charter, a vacated seat and a completed milestone whose cycle is still open
    for business."""
    successor = build_committee(
        api,
        seats=TERMINAL_B_SEATS,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Charter B",
        version_label="B-1",
        chair_key="fin",
    )
    predecessor = build_committee(
        api,
        seats=TERMINAL_A_SEATS,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Charter A",
        version_label="A-1",
        chair_key="fin",
    )
    predecessor.supersede(successor.id, chair_key="fin")
    vacated = successor.vacate("spare", chair_key="fin")
    assert vacated["status"] == "VACATED"

    cycle = build_cycle(api, successor)
    milestone = add_milestone(
        api, successor, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, successor, cycle["id"])
    start_milestone(api, successor, milestone["id"])
    done = complete_milestone(api, successor, milestone["id"])
    assert done["status"] == "COMPLETE"
    return predecessor, successor, cycle, done


def test_terminal_rows_admit_no_further_transition_and_report_entity_terminal(api):
    """Each of the three probes would have passed every other gate — the
    superseding charter is a valid adopted successor, recusal is declared out of
    the state the seat came from, and the completed milestone's cycle still
    admits a start — so what is being read is the terminal rule alone, which sits
    above the transition-legality rule and answers with its own code.

    PRD 2.9: "An attempt to mutate a row that already sits in one of its terminal states is rejected with `ERR_ENTITY_TERMINAL` (HTTP 409)."

    PRD 2.9: "The terminal states are: `SUPERSEDED` for a charter; `VACATED` for a committee member; `ABANDONED` on a reporting cycle's workflow axis, the remediation axis declaring no terminal state at all; `COMPLETE` or `BREACHED` for a milestone; `WITHDRAWN` or `VOID` for a sub-certification request; `VOID` for an officer certification; `FILED` or `SUPERSEDED` for a draft document; `WAIVED` for a tie-out item; `DISCLOSED` or `SUPERSEDED` for a material event; `AMENDED_SUPERSEDED` for a filing; and `RESCINDED` or `CLOSED` for a post-filing correction."

    Design: Corner/state_machines/terminal_rows_admit_no_further_transition_and_report_entity_terminal
    """
    predecessor, successor, cycle, milestone = _terminal_rows(api)

    validate_error(
        api.transition_charter(
            predecessor.id,
            action_payload("SUPERSEDE", successor_charter_id=successor.id),
            predecessor.chair("fin"),
        ),
        "ERR_ENTITY_TERMINAL",
        409,
    )
    validate_error(
        api.transition_member(
            successor.mid("spare"), action_payload("RECUSE"), successor.chair("fin")
        ),
        "ERR_ENTITY_TERMINAL",
        409,
    )
    validate_error(
        api.transition_milestone(
            milestone["id"], action_payload("START"), successor.controller("fin")
        ),
        "ERR_ENTITY_TERMINAL",
        409,
    )

    charter_a = validate_success(api.get_charter(predecessor.id, admin_headers()))
    assert charter_a["status"] == "SUPERSEDED"
    assert charter_a["superseded_by_charter_id"] == successor.id
    assert successor.refresh("spare")["status"] == "VACATED"
    assert refresh_cycle(api, cycle["id"])["status"] == "CLOSE_OPEN"

    unchanged = _milestone_of(api, cycle["id"], "CLOSE")
    assert unchanged["status"] == "COMPLETE"
    assert unchanged["version"] == 3


def _already_fired(api):
    """Three rows that have each just taken a declared edge, none of them into a
    terminal state: an adopted charter, a started close window and a submitted
    request."""
    committee = build_committee(
        api,
        seats=PLANNING_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Replay Charter",
    )
    scenario = scenario_close_open(api, committee)
    started = start_milestone(api, committee, scenario.milestones["CLOSE"]["id"])
    scenario.assign("fin", "REVENUE")
    submitted = scenario.submit("fin")
    return committee, scenario, started, submitted


def test_replaying_a_transition_that_already_fired_reports_invalid_state(api):
    """The interface carries no idempotency key, so a repeat is not a quiet
    no-op: a second adoption, a second start and a second submission are each
    refused because the edge is not declared out of the state the row now sits
    in, and because none of those three states is terminal the answer is the
    transition rule rather than the terminal rule — and no stamped instant is
    rewritten and no version moves.

    PRD 2.9: "A violation of either is `ERR_INVALID_STATE` (HTTP 409)."

    PRD 3.1: "On success the charter's `adopted_at_utc` is stamped from the current logical clock and its `version` increments."

    PRD 3.3: "Starting it moves from `PLANNED` to `IN_PROGRESS` and stamps `actual_start_utc` from the logical clock; the controller may only start a milestone while the owning cycle is in `CLOSE_OPEN`, `REVIEW_OPEN` or `CERTIFICATION_OPEN`, and an attempt outside those states is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/replaying_a_transition_that_already_fired_reports_invalid_state
    """
    committee, scenario, started, submitted = _already_fired(api)

    charter_before = validate_success(api.get_charter(committee.id, admin_headers()))
    assert charter_before["status"] == "ADOPTED"
    assert_instant_equals(charter_before["adopted_at_utc"], "2026-08-01T00:00:00Z")
    assert started["status"] == "IN_PROGRESS"
    assert_instant_equals(started["actual_start_utc"], "2026-08-01T00:00:00Z")
    assert started["version"] == 2
    assert submitted["status"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_utc"], "2026-08-01T00:00:00Z")
    assert submitted["version"] == 2

    validate_error(
        api.transition_charter(
            committee.id, action_payload("ADOPT"), committee.chair("legal")
        ),
        "ERR_INVALID_STATE",
        409,
    )
    validate_error(
        api.transition_milestone(
            started["id"], action_payload("START"), committee.controller("fin")
        ),
        "ERR_INVALID_STATE",
        409,
    )
    validate_error(
        api.transition_subcert(
            submitted["id"], action_payload("SUBMIT"), committee.leader("fin")
        ),
        "ERR_INVALID_STATE",
        409,
    )

    charter_after = validate_success(api.get_charter(committee.id, admin_headers()))
    assert charter_after["status"] == "ADOPTED"
    assert_instant_equals(charter_after["adopted_at_utc"], "2026-08-01T00:00:00Z")
    assert charter_after["version"] == charter_before["version"]

    milestone_after = _milestone_of(api, scenario.cycle_id, "CLOSE")
    assert milestone_after["status"] == "IN_PROGRESS"
    assert_instant_equals(milestone_after["actual_start_utc"], "2026-08-01T00:00:00Z")
    assert milestone_after["actual_end_utc"] is None
    assert milestone_after["version"] == 2

    request_after = validate_success(api.get_subcert(submitted["id"], admin_headers()))
    assert request_after["status"] == "SUBMITTED"
    assert_instant_equals(request_after["submitted_utc"], "2026-08-01T00:00:00Z")
    assert request_after["version"] == 2


def test_the_workflow_axis_and_the_remediation_axis_advance_without_touching(
    draft_correction_cycle,
):
    """Opening a post-filing correction moves the remediation axis off NONE while
    the workflow axis stays exactly where the filing left it, so the record sits
    at the combined state FILED and UNDER_EVALUATION; the correction itself is
    only a draft, so no control deficiency exists yet and the deficiency
    aggregate is still zero.

    PRD 3.2: "The two evolve independently: a cycle may legitimately sit at `FILED` on the workflow axis while sitting at `RESTATEMENT_DECLARED` on the remediation axis, or at `AMENDED` while `REMEDIATED`."

    Design: Corner/state_machines/status_and_restatement_stage_advance_independently_on_the_same_row
    """
    scenario = draft_correction_cycle
    api, committee = scenario.api, scenario.committee

    assert scenario.filing["status"] == "SUBMITTED"
    assert scenario.filing["accession_label"] == "FORM_10Q-FY2026-Q2-1"
    assert scenario.filing["late_flag"] is False
    assert scenario.correction["status"] == "DRAFT"

    after = refresh_cycle(api, scenario.cycle_id)
    assert after["status"] == "FILED"
    assert after["restatement_stage"] == "UNDER_EVALUATION"
    assert_money(after["unresolved_deficiency_weight"], 0.00)

    document = scenario.documents["PERIODIC_FILING"]
    assert refresh_document(api, committee, document["id"])["status"] == "FILED"

    rows, meta = validate_paginated(
        api.list_control_deficiencies(scenario.correction["id"], admin_headers())
    )
    assert rows == []
    assert meta["total_count"] == 0


ABANDON_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
]
ABANDON_NOTE = "Transaction pulled; period will be reported in the next cycle."


def _cycle_with_four_children(api):
    """A CLOSE_OPEN cycle carrying one pending request, one already-withdrawn
    request, one blocked certification slot and one draft document."""
    committee = build_committee(
        api,
        seats=ABANDON_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Abandonment Charter",
    )
    scenario = scenario_close_open(api, committee)
    pending = scenario.assign("fin", "REVENUE")
    scenario.assign("legal", "LEGAL_CONTINGENCY")
    withdrawn = withdraw_subcert(api, committee, scenario.subcerts["legal"]["id"])
    cert = scenario.cert("ceo", "CEO_302")
    document = scenario.document("PERIODIC_FILING", title="Form 10-Q FY2026-Q2")
    return scenario, pending, withdrawn, cert, document


def test_abandonment_voids_every_live_child_and_leaves_the_terminal_one_alone(api):
    """One call from CLOSE_OPEN reaches four different child types at once, and
    the one child that was already terminal is provably untouched: the pending
    request is voided, the withdrawn one keeps both its status and its version,
    the blocked slot is voided and the draft document is superseded. Both
    conserved aggregates fall to exactly 0.00 by the empty-set convention rather
    than to the 100.00 an "everything is settled" reading would give, and the
    remediation axis is not disturbed.

    PRD 3.2: "On success the cycle moves to `ABANDONED` and four cascades run: every sub-certification request on the cycle in `PENDING`, `SUBMITTED` or `EXCEPTION_NOTED` moves to `VOID`; every officer certification on the cycle in `BLOCKED`, `ELIGIBLE`, `SIGNED` or `REVOKED` moves to `VOID`; every draft document on the cycle in `DRAFT`, `IN_REVIEW`, `CHANGES_REQUESTED` or `APPROVED` moves to `SUPERSEDED`; and every material event on the cycle whose `assessment_status` is `UNASSESSED`, `NOT_REPORTABLE` or `REPORTABLE` moves to `SUPERSEDED`, which drives `open_material_event_count` to 0."

    PRD 3.2: "Both `total_assigned_scope_weight` and `certification_coverage_pct` then recompute, and because their source sets are now empty both fall to exactly 0.00."

    Design: Corner/state_machines/abandon_cascades_to_every_non_terminal_child_and_zeroes_both_aggregates
    """
    scenario, pending, withdrawn, cert, document = _cycle_with_four_children(api)
    committee = scenario.committee
    assert pending["status"] == "PENDING"
    assert_money(pending["scope_weight"], 30.00)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["version"] == 2
    assert cert["status"] == "BLOCKED"
    assert document["status"] == "DRAFT"

    abandoned = cycle_action(
        api, committee, scenario.cycle_id, "ABANDON",
        headers=committee.chair("legal"),
        note=ABANDON_NOTE,
    )
    assert abandoned["status"] == "ABANDONED"
    assert_money(abandoned["total_assigned_scope_weight"], 0.00)
    assert_money(abandoned["certification_coverage_pct"], 0.00)
    assert abandoned["restatement_stage"] == "NONE"

    voided = validate_success(api.get_subcert(pending["id"], admin_headers()))
    assert voided["status"] == "VOID"

    untouched = validate_success(api.get_subcert(withdrawn["id"], admin_headers()))
    assert untouched["status"] == "WITHDRAWN"
    assert untouched["version"] == 2

    assert _cert(api, cert["id"])["status"] == "VOID"
    assert refresh_document(api, committee, document["id"])["status"] == "SUPERSEDED"


def test_mitigating_the_last_open_deficiency_closes_the_correction_and_remediates(
    draft_correction_cycle,
):
    """Assessment on the iron-curtain method scores the error at 5.83 per cent of
    the base, which is a restatement, and raises a single material weakness
    weighted 23.32 that carries the cycle's remediation axis to
    RESTATEMENT_DECLARED. Mitigating that one open row then bubbles two levels up
    in a single call — the deficiency is mitigated, its parent correction closes
    with no client action at all, and the grandparent cycle is remediated while
    its workflow axis stays at FILED — after which a second mitigation is
    reported by the domain-specific code rather than as a terminal record.

    PRD 3.9: "A `ComplianceAdmin` records a `remediation_note` against a deficiency in `OPEN`, moving it to the terminal `MITIGATED`."

    PRD 3.9: "When no `OPEN` deficiency remains beneath the correction, the correction itself moves from `ASSESSED` to the terminal `CLOSED`."

    PRD 3.9: "And when the cycle's weight has returned to 0.00 with at least one `CLOSED` correction on the cycle, the remediation axis moves from `RESTATEMENT_DECLARED` to `REMEDIATED`."

    PRD 2.11: "The control deficiency is still `OPEN`. Applies to deficiency mitigation — `ERR_DEFICIENCY_ALREADY_MITIGATED`."

    Design: Corner/state_machines/mitigating_the_last_open_deficiency_bubbles_up_to_close_the_correction_and_remediate_the_cycle
    """
    scenario = draft_correction_cycle
    api = scenario.api
    correction_id = scenario.correction["id"]

    assessed = assess_correction(
        api, correction_id,
        method="IRON_CURTAIN",
        likelihood_pct=40,
        magnitude_amount=500000,
        compensating_control_present=False,
    )
    assert assessed["status"] == "ASSESSED"
    assert_money(assessed["materiality_pct"], 5.83)
    assert assessed["classification"] == "RESTATEMENT"

    raised = deficiencies_of(api, correction_id)
    assert len(raised) == 1
    deficiency = raised[0]
    assert deficiency["status"] == "OPEN"
    assert deficiency["severity"] == "MATERIAL_WEAKNESS"
    assert_money(deficiency["severity_score"], 5.83)
    assert_money(deficiency["deficiency_weight"], 23.32)

    before = refresh_cycle(api, scenario.cycle_id)
    assert before["restatement_stage"] == "RESTATEMENT_DECLARED"
    assert_money(before["unresolved_deficiency_weight"], 23.32)

    mitigated = mitigate_deficiency(
        api, deficiency["id"],
        remediation_note="Warranty accrual model rebuilt and independently re-performed.",
    )
    assert mitigated["status"] == "MITIGATED"

    closed = validate_success(api.get_correction(correction_id, admin_headers()))
    assert closed["status"] == "CLOSED"

    after = refresh_cycle(api, scenario.cycle_id)
    assert after["status"] == "FILED"
    assert after["restatement_stage"] == "REMEDIATED"
    assert_money(after["unresolved_deficiency_weight"], 0.00)

    filing = validate_success(api.get_filing(scenario.filing["id"], admin_headers()))
    assert filing["status"] == "SUBMITTED"

    validate_error(
        api.mitigate_control_deficiency(
            deficiency["id"],
            {"remediation_note": "Duplicate remediation entry from a second reviewer."},
            admin_headers(),
        ),
        "ERR_DEFICIENCY_ALREADY_MITIGATED",
        409,
    )
