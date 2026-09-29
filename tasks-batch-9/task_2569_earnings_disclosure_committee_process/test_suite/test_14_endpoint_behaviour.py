"""Endpoints driven through the one request that tells them apart.

A clearance that keys on a question's risk tier rather than on its status, a
computed readiness read taken twice across the same cycle, a link validated from
both ends before it binds, and one parent state that answers two kinds of child
write differently.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_instant_equals, assert_money
from test_helpers.factories import (
    action_payload,
    adjusted_measure_payload,
    officer_cert_payload,
    reconcile_payload,
)
from test_helpers.fixtures import (
    add_adjusted_measure,
    add_milestone,
    add_qa_item,
    add_tie_out,
    approve_document,
    assess_event,
    build_committee,
    build_cycle,
    clear_qa_item,
    log_material_event,
    readiness,
    reconcile_measure,
    refresh_cycle,
    refresh_document,
    register_cert,
    review_tie_out,
    scenario_close_open,
    submit_for_review,
)
from test_helpers.test_users import admin_headers

SCRIPT_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ir", "Ida Relations", "INVESTOR_RELATIONS", False, True),
]
LOW_QUESTION = "How should we describe segment mix this quarter?"
SAFE_HARBOUR_QUESTION = "What revenue range should we point to for the coming quarter?"
HIGH_QUESTION = "Is the pending regulatory inquiry likely to result in a material charge?"
CLEARANCE_NOTE = (
    "Counsel approved wording: refer to the disclosed inquiry and decline to quantify."
)


def _script_fixture(api):
    """A call script carrying the safe-harbour legend and one matched tie-out
    line, with three questions attached: a plain LOW one, a LOW one that flags a
    forward-looking answer, and a HIGH-risk one."""
    committee = build_committee(
        api,
        seats=SCRIPT_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Question Bank Charter",
    )
    scenario = scenario_close_open(api, committee)
    script = scenario.document(
        "CALL_SCRIPT", author_key="ir", title="Q2 2026 Earnings Call Script",
        safe_harbor_present=True, role="relations",
    )
    assert script["qa_gate_status"] == "CLEARED"
    add_tie_out(
        api, committee, script["id"], "Adjusted EPS quoted in the script",
        5000000.0, 5000000.0, tolerance_bp=25,
    )
    questions = {}
    questions["low"] = add_qa_item(
        api, committee, script["id"], question_text=LOW_QUESTION,
        topic="SEGMENT_PERFORMANCE", risk_tier="LOW", requires_safe_harbor=False,
    )
    questions["gate_after_low"] = refresh_document(api, committee, script["id"])
    questions["safe_harbour"] = add_qa_item(
        api, committee, script["id"], question_text=SAFE_HARBOUR_QUESTION,
        topic="GUIDANCE", risk_tier="LOW", requires_safe_harbor=True,
    )
    questions["gate_after_safe_harbour"] = refresh_document(api, committee, script["id"])
    questions["high"] = add_qa_item(
        api, committee, script["id"], question_text=HIGH_QUESTION,
        topic="LITIGATION", risk_tier="HIGH", requires_safe_harbor=False,
    )
    questions["gate_after_high"] = refresh_document(api, committee, script["id"])
    return committee, script, questions


def _approve(api, committee, document_id):
    return api.transition_document(
        document_id, action_payload("APPROVE"), committee.counsel("legal")
    )


def test_only_the_high_risk_question_moves_the_script_gate_to_blocked(api):
    """Two of the three questions are persisted BLOCKED as rows, but the gate is
    a different reading: the LOW question that merely flags a forward-looking
    answer leaves the gate CLEARED, and only the HIGH-risk row turns it BLOCKED —
    which is what the approval reports.

    PRD 3.7: "A question is persisted directly in `status` `BLOCKED` when its `risk_tier` is `HIGH` **or** its `requires_safe_harbor` flag is true, and in `status` `DRAFT` otherwise."

    PRD 3.7: "`qa_gate_status` reads `BLOCKED` exactly while some question on the script has `risk_tier` `HIGH` and a `status` other than `CLEARED`; it reads `CLEARED` in every other case, including the case of a script with no questions at all."

    Design: Corner/endpoints/question_clearance_endpoint_gates_only_on_high_risk_questions_and_refuses_a_replayed_clear
    """
    committee, script, questions = _script_fixture(api)

    assert questions["low"]["status"] == "DRAFT"
    assert questions["low"]["clearance_note"] is None
    assert questions["gate_after_low"]["qa_gate_status"] == "CLEARED"

    assert questions["safe_harbour"]["status"] == "BLOCKED"
    assert questions["gate_after_safe_harbour"]["qa_gate_status"] == "CLEARED"

    assert questions["high"]["status"] == "BLOCKED"
    assert questions["gate_after_high"]["qa_gate_status"] == "BLOCKED"
    assert questions["gate_after_high"]["tie_out_status"] == "PASSED"

    in_review = submit_for_review(api, committee, script["id"])
    assert in_review["status"] == "IN_REVIEW"

    validate_error(
        _approve(api, committee, script["id"]), "ERR_QA_ITEM_UNCLEARED", 409
    )
    assert refresh_document(api, committee, script["id"])["status"] == "IN_REVIEW"


def test_clearing_that_one_question_lets_the_script_through_and_a_replay_is_refused(api):
    """Clearing the HIGH-risk question alone returns the gate to CLEARED and the
    approval that was just refused succeeds, leaving one DRAFT and one BLOCKED
    question still attached to the approved script; the second identical clear is
    refused because the row is no longer in a state that declares the edge.

    PRD 3.7: "Clearing a question is reserved to `LegalCounsel`, requires a `clearance_note`, and moves the question to `CLEARED` from either `DRAFT` or `BLOCKED`."

    PRD 2.9: "Separately, a requested transition must be declared from the row's current state, and the parent row must be in a state that admits the write."

    Design: Corner/endpoints/question_clearance_endpoint_gates_only_on_high_risk_questions_and_refuses_a_replayed_clear
    """
    committee, script, questions = _script_fixture(api)
    submit_for_review(api, committee, script["id"])
    validate_error(
        _approve(api, committee, script["id"]), "ERR_QA_ITEM_UNCLEARED", 409
    )

    cleared = clear_qa_item(
        api, committee, questions["high"]["id"], clearance_note=CLEARANCE_NOTE
    )
    assert cleared["status"] == "CLEARED"
    assert cleared["clearance_note"] == CLEARANCE_NOTE
    assert refresh_document(api, committee, script["id"])["qa_gate_status"] == "CLEARED"

    replay = api.clear_qa_item(
        questions["high"]["id"],
        {"clearance_note": "Second attempt at the same clearance."},
        committee.counsel("legal"),
    )
    validate_error(replay, "ERR_INVALID_STATE", 409)

    approved = validate_success(_approve(api, committee, script["id"]))
    assert approved["status"] == "APPROVED"

    rows, meta = validate_paginated(
        api.list_qa_items(script["id"], admin_headers(), limit=10, offset=0)
    )
    assert len(rows) == 3
    assert meta["total_count"] == 3
    by_id = {row["id"]: row for row in rows}
    assert by_id[questions["low"]["id"]]["status"] == "DRAFT"
    assert by_id[questions["safe_harbour"]["id"]]["status"] == "BLOCKED"
    assert by_id[questions["high"]["id"]]["status"] == "CLEARED"


READINESS_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
EVENT_DESCRIPTION = "Adverse first-instance judgment in the supplier dispute."


def _readiness_fixture(api):
    """A cycle in CLOSE_OPEN carrying only a CLOSE window, one unassessed event
    below the reportable floor, and neither a sub-certification request nor an
    officer certification."""
    committee = build_committee(
        api,
        seats=READINESS_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Readiness Dashboard Charter",
    )
    scenario = scenario_close_open(api, committee)
    event = log_material_event(
        api, committee, scenario.cycle_id,
        category="LITIGATION_JUDGMENT",
        occurred_utc="2026-07-20T09:00:00Z",
        discovered_utc="2026-07-21T09:00:00Z",
        magnitude_amount=300000,
        description=EVENT_DESCRIPTION,
    )
    return committee, scenario, event


def test_the_readiness_read_names_every_blocking_gate_in_ladder_order(api):
    """Every scalar of the dashboard is checked against a hand-computed value and
    all three lists are checked as ordered sequences; the claim that the head of
    the blocking list is exactly what the declaration would return is then settled
    by attempting the declaration and matching the code.

    PRD 3.2: "It is a computed read, and unusually for a read it performs work before answering — it runs the breach sweep and re-runs the slack computation against the current logical clock, so the slack figures it reports are never stale."

    PRD 3.2: "`blocking_error_ids` lists, de-duplicated and in ascending order of the rule ladder of §2.11, the distinct error identifiers a filing-readiness declaration would raise at this instant — so its first element is exactly the code the declaration would return."

    PRD 3.2: "`unsigned_cert_types` lists the certification instruments required by the cycle's `form_type` that are not yet signed, in the fixed order `CEO_302`, `CFO_302`, `CEO_906`, `CFO_906`."

    Design: Corner/endpoints/readiness_read_lists_the_blocking_gates_in_priority_order_and_shrinks_as_they_are_cleared
    """
    committee, scenario, event = _readiness_fixture(api)
    assert_money(event["severity_score"], 3.00)
    assert event["assessment_status"] == "UNASSESSED"

    board = readiness(api, scenario.cycle_id)
    assert board["cycle_id"] == scenario.cycle_id
    assert board["cycle_status"] == "CLOSE_OPEN"
    assert board["restatement_stage"] == "NONE"
    assert_instant_equals(board["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    assert_instant_equals(board["internal_target_utc"], "2026-08-05T17:30:00Z")
    assert board["min_slack_days_calendar"] == 7
    assert board["min_slack_days_business"] == 5
    assert_money(board["total_assigned_scope_weight"], 0.00)
    assert_money(board["certification_coverage_pct"], 0.00)
    assert board["open_material_event_count"] == 1
    assert_money(board["unresolved_deficiency_weight"], 0.00)
    assert board["missing_milestone_kinds"] == ["REVIEW", "FILING"]
    assert board["unsigned_cert_types"] == ["CEO_302", "CFO_302"]
    assert board["blocking_error_ids"] == [
        "ERR_INVALID_STATE",
        "ERR_OPEN_MATERIAL_EVENT",
        "ERR_MILESTONE_MISSING",
        "ERR_CERTIFICATIONS_INCOMPLETE",
    ]
    assert board["filing_ready_eligible"] is False

    refused = api.transition_cycle(
        scenario.cycle_id,
        action_payload("DECLARE_FILING_READY"),
        committee.chair("legal"),
    )
    validate_error(refused, board["blocking_error_ids"][0], 409)
    assert refresh_cycle(api, scenario.cycle_id)["status"] == "CLOSE_OPEN"


def test_resolving_two_gates_shrinks_the_blocking_list_and_lowers_the_slack(api):
    """Assessing the event away and adding the filing window resolve two of the
    four gates, so the second read of the same projection drops two codes and one
    milestone kind — and both slack figures fall from 7/5 to 1/1 because the new
    window joins the open set and becomes the minimum.

    PRD 3.2: "`missing_milestone_kinds` lists only those milestone kinds that some remaining workflow transition of this cycle requires and that the cycle does not have, ordered `CLOSE`, `REVIEW`, `CERTIFICATION`, `FILING`; because no transition ever requires a `CERTIFICATION` milestone, that kind never appears in the list."

    PRD 3.2: "`filing_ready_eligible` is true if and only if `blocking_error_ids` is empty."

    Design: Corner/endpoints/readiness_read_lists_the_blocking_gates_in_priority_order_and_shrinks_as_they_are_cleared
    """
    committee, scenario, event = _readiness_fixture(api)
    assert readiness(api, scenario.cycle_id)["min_slack_days_calendar"] == 7

    assessed = assess_event(api, committee, event["id"], "NOT_REPORTABLE")
    assert assessed["assessment_status"] == "NOT_REPORTABLE"
    assert assessed["current_report_deadline_utc"] is None

    filing_window = add_milestone(
        api, committee, scenario.cycle_id, "FILING",
        "2026-08-09T00:00:00Z", "2026-08-09T06:00:00Z",
    )
    assert filing_window["slack_calendar_days"] == 1
    assert filing_window["slack_business_days"] == 1

    board = readiness(api, scenario.cycle_id)
    assert board["min_slack_days_calendar"] == 1
    assert board["min_slack_days_business"] == 1
    assert board["open_material_event_count"] == 0
    assert board["missing_milestone_kinds"] == ["REVIEW"]
    assert board["unsigned_cert_types"] == ["CEO_302", "CFO_302"]
    assert board["blocking_error_ids"] == [
        "ERR_INVALID_STATE",
        "ERR_CERTIFICATIONS_INCOMPLETE",
    ]
    assert board["filing_ready_eligible"] is False


HOME_SEATS = [
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
    ("cfo", "Sam Fiscal", "FINANCE", True, True),
]
FOREIGN_SEATS = [
    ("vic", "Vic Foreign", "FINANCE", True, True),
    ("wren", "Wren Foreign", "FINANCE", True, True),
]
UNKNOWN_CYCLE_ID = "00000000-0000-4000-8000-00000000dead"
UNKNOWN_MEMBER_ID = "00000000-0000-4000-8000-00000000beef"


def _link_fixture(api):
    """Two adopted charters, and a cycle left in PLANNING on the first of them —
    registration is admitted from every cycle status except ABANDONED, so no
    calendar and no transition are needed."""
    home = build_committee(
        api,
        seats=HOME_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Officer Link Charter",
    )
    foreign = build_committee(
        api,
        seats=FOREIGN_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE"],
        name="Sibling Issuer Charter",
        chair_key="vic",
    )
    cycle = build_cycle(api, home)
    assert cycle["status"] == "PLANNING"
    return home, foreign, cycle


def _register(api, cycle_id, member_id, cert_type):
    return api.create_officer_cert(
        officer_cert_payload(cycle_id, member_id, cert_type), admin_headers()
    )


def test_both_ends_of_the_certification_link_are_checked_in_declaration_order(api):
    """A request whose cycle and member are both unknown reports the cycle code,
    which is the only observable proof that `cycle_id` is resolved first; once both
    ends exist the link is refused for belonging to another charter, and then for
    naming a seat that is not an officer.

    PRD 2.7: "References supplied inside a request body are resolved after every path segment has resolved, and among themselves they are checked in the order in which the endpoint declares its input fields."

    PRD 2.11: "Every committee member named in the request — through `member_id`, `officer_member_id`, `author_member_id`, `preparer_member_id` or `reviewer_member_id` — belongs to the same charter as the reporting cycle the write targets. Applies to sub-certification creation, officer-certification registration, document creation, tie-out item creation and tie-out review — `ERR_MEMBER_CHARTER_MISMATCH`."

    Design: Corner/endpoints/officer_certification_link_validates_both_ends_left_to_right_and_then_binds_the_seat
    """
    home, foreign, cycle = _link_fixture(api)

    validate_error(
        _register(api, UNKNOWN_CYCLE_ID, UNKNOWN_MEMBER_ID, "CEO_302"),
        "ERR_CYCLE_NOT_FOUND",
        404,
    )
    validate_error(
        _register(api, cycle["id"], UNKNOWN_MEMBER_ID, "CEO_302"),
        "ERR_MEMBER_NOT_FOUND",
        404,
    )
    validate_error(
        _register(api, cycle["id"], foreign.mid("vic"), "CEO_302"),
        "ERR_MEMBER_CHARTER_MISMATCH",
        409,
    )
    validate_error(
        _register(api, cycle["id"], home.mid("fin"), "CEO_302"),
        "ERR_MEMBER_SEAT_INVALID",
        409,
    )

    rows, meta = validate_paginated(
        api.list_officer_certs(admin_headers(), cycle_id=cycle["id"], limit=10, offset=0)
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_registered_slot_binds_the_instrument_and_a_recused_officer_is_refused(api):
    """The accepted registration binds one seat to one instrument and is persisted
    unsigned, after which a second slot for the same instrument is refused even
    though it names a different officer; recusing that officer then makes his own
    instrument unavailable to him as well.

    PRD 3.8: "The named seat must be `ACTIVE` and must carry `is_officer` true, or the registration is rejected with `ERR_MEMBER_SEAT_INVALID`; the cycle may hold at most one non-`VOID` certification per `cert_type`, and a second registration of the same instrument is rejected with `ERR_DUPLICATE_CERTIFICATION`."

    PRD 3.8: "The slot is persisted in `status` `BLOCKED` with `attestation_text`, `signed_utc` and `coverage_pct_at_signing` all null, and the cross-entity gate is then evaluated at once: if the cycle is already in `CERTIFICATION_OPEN` with `certification_coverage_pct` exactly 100.00, `open_material_event_count` zero and `unresolved_deficiency_weight` exactly 0.00, the slot becomes `ELIGIBLE` immediately rather than waiting for a later event."

    Design: Corner/endpoints/officer_certification_link_validates_both_ends_left_to_right_and_then_binds_the_seat
    """
    home, _foreign, cycle = _link_fixture(api)

    slot = register_cert(api, cycle["id"], home, "ceo", "CEO_302")
    assert slot["cycle_id"] == cycle["id"]
    assert slot["officer_member_id"] == home.mid("ceo")
    assert slot["cert_type"] == "CEO_302"
    assert slot["status"] == "BLOCKED"
    assert slot["attestation_text"] is None
    assert slot["signed_utc"] is None
    assert slot["coverage_pct_at_signing"] is None

    validate_error(
        _register(api, cycle["id"], home.mid("cfo"), "CEO_302"),
        "ERR_DUPLICATE_CERTIFICATION",
        409,
    )

    recused = home.recuse("cfo")
    assert recused["status"] == "RECUSED"
    validate_error(
        _register(api, cycle["id"], home.mid("cfo"), "CFO_302"),
        "ERR_MEMBER_SEAT_INVALID",
        409,
    )

    rows, meta = validate_paginated(
        api.list_officer_certs(
            admin_headers(),
            cycle_id=cycle["id"],
            officer_member_id=home.mid("ceo"),
            limit=10,
            offset=0,
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["id"] == slot["id"]


FILING_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("fin2", "Pilar Ledger", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
BRIDGE_ITEM = [{"label": "Stock-based compensation", "amount": 200000.0}]


def _approved_filing(api):
    """A periodic filing carried to APPROVED over one reconciled measure and one
    matched tie-out line, so both child gates read clear on the way in."""
    committee = build_committee(
        api,
        seats=FILING_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Approved Document Charter",
    )
    scenario = scenario_close_open(api, committee)
    document = scenario.document(
        "PERIODIC_FILING", author_key="fin", title="Form 10-Q FY2026-Q2",
        safe_harbor_present=True,
    )
    measure = add_adjusted_measure(
        api, committee, document["id"],
        measure_label="Adjusted EBITDA",
        adjusted_value=1200000.0,
        comparable_gaap_value=1000000.0,
        reconciliation_items=BRIDGE_ITEM,
        adjusted_prominence_index=2,
        gaap_prominence_index=1,
    )
    assert measure["status"] == "DRAFT"
    assert refresh_document(api, committee, document["id"])["measure_gate_status"] == (
        "BLOCKED_RECONCILIATION"
    )
    reconciled = reconcile_measure(api, committee, measure["id"])
    assert_money(reconciled["reconciliation_sum"], 200000.00)
    assert_money(reconciled["reconciliation_gap"], 0.00)
    assert reconciled["prominence_ok"] is True
    assert reconciled["status"] == "RECONCILED"
    assert refresh_document(api, committee, document["id"])["measure_gate_status"] == (
        "CLEARED"
    )
    add_tie_out(
        api, committee, document["id"], "Total revenue",
        5000000.0, 5000000.0, tolerance_bp=25,
    )
    submit_for_review(api, committee, document["id"])
    approved = approve_document(api, committee, document["id"], "legal")
    assert approved["status"] == "APPROVED"
    return committee, document, measure


def test_an_approved_document_still_admits_a_new_tie_out_line_and_its_review(api):
    """A late tie-out line is accepted onto the approved document and reviewed
    there, which is the whole point of admitting tie-out work from APPROVED; the
    added line carries no variance, so the schedule stays PASSED and the document
    is never re-opened.

    PRD 3.6: "The `Controller` adds them to a document that is in `DRAFT`, `IN_REVIEW`, `CHANGES_REQUESTED` or `APPROVED`."

    PRD 3.6: "The owning document must be in `DRAFT`, `IN_REVIEW`, `CHANGES_REQUESTED` or `APPROVED`."

    Design: Corner/endpoints/approved_document_still_accepts_tie_out_writes_but_refuses_every_adjusted_measure_write
    """
    committee, document, _measure = _approved_filing(api)

    late_line = add_tie_out(
        api, committee, document["id"], "Operating expenses",
        3000000.0, 3000000.0, tolerance_bp=25,
    )
    assert late_line["status"] == "MATCHED"
    assert late_line["raw_variance_bp"] == 0

    after_line = refresh_document(api, committee, document["id"])
    assert after_line["status"] == "APPROVED"
    assert after_line["tie_out_status"] == "PASSED"
    assert after_line["tie_out_total_variance_bp"] == 0

    waived = review_tie_out(api, committee, late_line["id"], "fin2", "WAIVE")
    assert waived["status"] == "WAIVED"
    assert waived["reviewer_member_id"] == committee.mid("fin2")
    assert waived["review_decision"] == "WAIVE"

    after_review = refresh_document(api, committee, document["id"])
    assert after_review["status"] == "APPROVED"
    assert after_review["tie_out_status"] == "PASSED"
    assert after_review["tie_out_total_variance_bp"] == 0


def test_the_same_approved_document_refuses_both_kinds_of_measure_write(api):
    """The identical parent state that just admitted two tie-out writes refuses
    both measure writes; the refused reconcile supplies indices that would flip the
    measure to a prominence failure, so the gate still reading CLEARED afterwards
    shows the request was turned away before anything was recomputed.

    PRD 3.7: "Unlike tie-out items, neither is accepted onto an already-approved document: an `APPROVED` document admits tie-out work but refuses adjusted-measure creation, question-item creation, measure reconciliation and question clearance, all of which require the document to be in `DRAFT`, `IN_REVIEW` or `CHANGES_REQUESTED`."

    PRD 2.9: "A violation of either is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/endpoints/approved_document_still_accepts_tie_out_writes_but_refuses_every_adjusted_measure_write
    """
    committee, document, measure = _approved_filing(api)

    refused_create = api.create_adjusted_measure(
        document["id"],
        adjusted_measure_payload(
            "Adjusted operating margin", 400000.0, 350000.0,
            [{"label": "Restructuring", "amount": 50000.0}], 3, 1,
        ),
        committee.controller("fin"),
    )
    validate_error(refused_create, "ERR_INVALID_STATE", 409)

    refused_reconcile = api.reconcile_adjusted_measure(
        measure["id"],
        reconcile_payload(adjusted_prominence_index=1, gaap_prominence_index=2),
        committee.controller("fin"),
    )
    validate_error(refused_reconcile, "ERR_INVALID_STATE", 409)

    final = refresh_document(api, committee, document["id"])
    assert final["status"] == "APPROVED"
    assert final["measure_gate_status"] == "CLEARED"

    rows = validate_success(api.list_adjusted_measures(document["id"], admin_headers()))
    assert len(rows) == 1
    assert rows[0]["id"] == measure["id"]
    assert rows[0]["status"] == "RECONCILED"
    assert rows[0]["prominence_ok"] is True
