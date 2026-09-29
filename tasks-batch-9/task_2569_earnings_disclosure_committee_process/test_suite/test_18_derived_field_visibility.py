"""Derived fields read the same from the mutating response and the next GET.

Every roll-up here is settled inside the request that caused it: the weight a
sub-certification carries, the coverage percentage over an empty and then a
half-covered scope, a parent script's question gate, and a grandparent cycle's
open-event count.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_money
from test_helpers.fixtures import (
    add_milestone,
    add_qa_item,
    assign_subcert,
    build_committee,
    build_cycle,
    clear_qa_item,
    create_document,
    log_material_event,
    open_close,
    refresh_cycle,
    refresh_document,
    submit_subcert,
)
from test_helpers.test_users import admin_headers

CONSISTENCY_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ir", "Ivy Relations", "INVESTOR_RELATIONS", False, True),
]
SCRIPT_TITLE = "Q2 Earnings Call Script"
QUESTION = "Why did the warranty accrual assumption change this quarter?"
CLEARANCE_NOTE = "Cleared with a forward-looking statement qualifier."
EVENT_DESCRIPTION = "Adverse judgment in a supplier dispute"
DUE_UTC = "2026-08-04T17:00:00Z"


def _open_cycle(api, name):
    """An adopted three-function committee with its cycle in CLOSE_OPEN."""
    committee = build_committee(
        api,
        seats=CONSISTENCY_SEATS,
        min_quorum_count=3,
        required_functions=["FINANCE", "LEGAL", "INVESTOR_RELATIONS"],
        name=name,
    )
    cycle = build_cycle(api, committee)
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    opened = open_close(api, committee, cycle["id"])
    assert opened["status"] == "CLOSE_OPEN"
    return committee, cycle["id"]


def _two_requests(api, name):
    """REVENUE on finance and LEGAL_CONTINGENCY on legal, both still PENDING."""
    committee, cycle_id = _open_cycle(api, name)
    revenue = assign_subcert(
        api, committee, cycle_id, "fin", "REVENUE", due_utc=DUE_UTC
    )
    contingency = assign_subcert(
        api, committee, cycle_id, "legal", "LEGAL_CONTINGENCY", due_utc=DUE_UTC
    )
    return committee, cycle_id, revenue, contingency


def test_each_creating_response_already_carries_the_derived_weight(api):
    """The weight of a request is derived at creation and returned by the call
    that created it: 30.00 for REVENUE and 25.00 for LEGAL_CONTINGENCY on
    non-officer seats, and the cycle read that follows agrees at 55.00 with
    coverage sitting at the empty-numerator convention 0.00 rather than 100.00.

    PRD 3.4: "The base weight comes from the scope area: 30 for `REVENUE`, 25 for `LEGAL_CONTINGENCY`, 20 for `OPERATIONS`, 15 for `IR_COMMUNICATIONS` and 10 for `IT_CONTROLS`."

    PRD 3.4: "When the denominator set is empty the coverage is **0.00**, not 100.00 — an empty scope is not a covered scope."

    PRD 2.12: "`total_assigned_scope_weight` is recomputed as the half-up-rounded, two-decimal sum of the `scope_weight` of every sub-certification request on the cycle whose `status` is `PENDING`, `SUBMITTED` or `EXCEPTION_NOTED`; withdrawn and voided rows contribute nothing."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_and_the_very_next_read
    """
    _, cycle_id, revenue, contingency = _two_requests(api, "Consistency Charter")

    assert_money(revenue["scope_weight"], 30.00)
    assert revenue["status"] == "PENDING"
    assert revenue["exception_severity"] == "NONE"
    assert revenue["submitted_utc"] is None
    assert_money(contingency["scope_weight"], 25.00)
    assert contingency["status"] == "PENDING"

    settled = refresh_cycle(api, cycle_id)
    assert_money(settled["total_assigned_scope_weight"], 55.00)
    assert_money(settled["certification_coverage_pct"], 0.00)
    assert abs(float(settled["certification_coverage_pct"]) - 100.00) > 0.01
    assert settled["open_material_event_count"] == 0


def test_the_midway_coverage_shows_up_in_the_read_after_the_first_submission(api):
    """One of two requests submitted leaves coverage at 30.00 over 55.00, which
    is 54.55 after a single half-up rounding, and the read taken straight after
    the submitting response reports exactly that; the conserved total does not
    move, because the clean branch leaves the row's weight alone.

    PRD 3.4: "Otherwise the raw `scope_weight` values of the numerator set are summed, the raw `scope_weight` values of the denominator set are summed, the first sum is divided by the second, the quotient is multiplied by 100, and the result is rounded half up to two decimal places exactly once."

    PRD 3.4: "Coverage is recomputed: because the row was already in the denominator and has now entered the numerator, the numerator grows and the denominator does not move, so coverage rises."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_and_the_very_next_read
    """
    committee, cycle_id, revenue, contingency = _two_requests(
        api, "Midway Coverage Charter"
    )

    submitted = submit_subcert(api, committee, revenue["id"], "fin")
    assert submitted["status"] == "SUBMITTED"
    assert submitted["exception_severity"] == "NONE"
    assert_money(submitted["scope_weight"], 30.00)

    midway = refresh_cycle(api, cycle_id)
    assert_money(midway["certification_coverage_pct"], 54.55)
    assert_money(midway["total_assigned_scope_weight"], 55.00)

    pending, pending_meta = validate_paginated(
        api.list_subcerts(admin_headers(), cycle_id=cycle_id, status="PENDING",
                          limit=10, offset=0)
    )
    assert pending_meta["total_count"] == 1
    assert [row["id"] for row in pending] == [contingency["id"]]

    closed = submit_subcert(api, committee, contingency["id"], "legal")
    assert closed["status"] == "SUBMITTED"

    covered = refresh_cycle(api, cycle_id)
    assert_money(covered["certification_coverage_pct"], 100.00)
    assert_money(covered["total_assigned_scope_weight"], 55.00)

    rows, meta = validate_paginated(
        api.list_subcerts(admin_headers(), cycle_id=cycle_id, status="SUBMITTED",
                          limit=10, offset=0)
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert {row["scope_area"] for row in rows} == {"REVENUE", "LEGAL_CONTINGENCY"}
    assert [row["status"] for row in rows] == ["SUBMITTED", "SUBMITTED"]


def test_a_high_question_flips_the_parent_gate_inside_its_own_creating_request(api):
    """A freshly started script carries qa_gate_status CLEARED because it has no
    questions at all; the HIGH-tier question is persisted BLOCKED and the parent
    document's gate is already BLOCKED in the read that follows, so the
    cross-entity derivation happened inside the child's creating request rather
    than on the next read of the parent.

    PRD 3.5: "A new document is persisted with `status` `DRAFT`, `revision_round` 0, a null `change_note`, `tie_out_status` `NOT_STARTED`, `tie_out_total_variance_bp` 0, `tie_out_tier_multiplier` 1.00, `measure_gate_status` `NO_MEASURES` and `qa_gate_status` `CLEARED`."

    PRD 3.7: "A question is persisted directly in `status` `BLOCKED` when its `risk_tier` is `HIGH` **or** its `requires_safe_harbor` flag is true, and in `status` `DRAFT` otherwise."

    PRD 3.7: "`qa_gate_status` reads `BLOCKED` exactly while some question on the script has `risk_tier` `HIGH` and a `status` other than `CLEARED`; it reads `CLEARED` in every other case, including the case of a script with no questions at all."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_and_the_very_next_read
    """
    committee, cycle_id = _open_cycle(api, "Question Gate Charter")
    script = create_document(
        api, committee, cycle_id, "CALL_SCRIPT", "ir",
        title=SCRIPT_TITLE, safe_harbor_present=True, role="relations",
    )
    assert script["status"] == "DRAFT"
    assert script["qa_gate_status"] == "CLEARED"
    assert script["safe_harbor_present"] is True

    question = add_qa_item(
        api, committee, script["id"], question_text=QUESTION, topic="MARGIN",
        risk_tier="HIGH",
    )
    assert question["status"] == "BLOCKED"
    assert question["risk_tier"] == "HIGH"
    assert question["clearance_note"] is None

    blocked = refresh_document(api, committee, script["id"])
    assert blocked["qa_gate_status"] == "BLOCKED"
    assert blocked["status"] == "DRAFT"
    assert blocked["version"] > script["version"]


def test_clearing_the_question_releases_the_parent_gate_just_as_promptly(api):
    """Clearance is the same story in reverse: the clearing response reports the
    question CLEARED and the very next read of the script reports the gate back
    at CLEARED, with no HIGH-tier question left uncleared.

    PRD 3.7: "Clearing records the `clearance_note`, re-derives the script's `qa_gate_status` — which returns to `CLEARED` once no `HIGH`-tier question on the script is left uncleared — and increments both the question's `version` and the document's `version`."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_and_the_very_next_read
    """
    committee, cycle_id = _open_cycle(api, "Question Clearance Charter")
    script = create_document(
        api, committee, cycle_id, "CALL_SCRIPT", "ir",
        title=SCRIPT_TITLE, safe_harbor_present=True, role="relations",
    )
    question = add_qa_item(
        api, committee, script["id"], question_text=QUESTION, topic="MARGIN",
        risk_tier="HIGH",
    )
    blocked = refresh_document(api, committee, script["id"])
    assert blocked["qa_gate_status"] == "BLOCKED"

    cleared = clear_qa_item(
        api, committee, question["id"], clearance_note=CLEARANCE_NOTE
    )
    assert cleared["status"] == "CLEARED"
    assert cleared["clearance_note"] == CLEARANCE_NOTE

    released = refresh_document(api, committee, script["id"])
    assert released["qa_gate_status"] == "CLEARED"
    assert released["version"] > blocked["version"]


def test_a_logged_event_scores_itself_and_raises_the_grandparent_count_at_once(api):
    """The logging response already carries the scored severity — 800000 against
    a materiality base of 10000000 is 8.00 percent — and the unassessed defaults;
    the grandparent cycle's open-event count reads 1 in the very next read,
    because an event nobody has looked at yet is already in the open set.

    PRD 3.8: "Its `severity_score` is the absolute value of `magnitude_amount` divided by the cycle's `materiality_base_amount`, expressed as a percentage, capped at 100.00 and rounded half up to two decimal places."

    PRD 3.8: "The row is then persisted with `assessment_status` `UNASSESSED`, `determination_note` null, `linked_document_id` null and `current_report_deadline_utc` null."

    PRD 3.8: "The count that certification hangs on is `open_material_event_count`, and it is defined as the number of events on the cycle whose `assessment_status` is `UNASSESSED` or `REPORTABLE`."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_and_the_very_next_read
    """
    committee, cycle_id = _open_cycle(api, "Open Event Count Charter")
    before = refresh_cycle(api, cycle_id)
    assert before["open_material_event_count"] == 0

    event = log_material_event(
        api, committee, cycle_id, category="LITIGATION_JUDGMENT",
        occurred_utc="2026-07-20T00:00:00Z",
        discovered_utc="2026-07-28T00:00:00Z",
        magnitude_amount=800000,
        description=EVENT_DESCRIPTION,
    )
    assert_money(event["severity_score"], 8.00)
    assert event["assessment_status"] == "UNASSESSED"
    assert event["determination_note"] is None
    assert event["linked_document_id"] is None
    assert event["current_report_deadline_utc"] is None

    stored = validate_success(api.get_material_event(event["id"], admin_headers()))
    assert_money(stored["severity_score"], 8.00)
    assert stored["assessment_status"] == "UNASSESSED"

    after = refresh_cycle(api, cycle_id)
    assert after["open_material_event_count"] == 1
    assert after["version"] > before["version"]
