"""Gates whose verdict is read off a different row than the one being written.

A document approval that reads its child measures, an event disclosure that
reads a sibling document's status, and a submission that reads the seat two hops
away from the request.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.assertions import assert_instant_equals, assert_money
from test_helpers.factories import action_payload
from test_helpers.fixtures import (
    add_adjusted_measure,
    add_matching_tie_out,
    approve_document,
    assess_event,
    assign_subcert,
    build_committee,
    log_material_event,
    reconcile_measure,
    refresh_cycle,
    refresh_document,
    scenario_close_open,
    submit_for_review,
)
from test_helpers.test_users import admin_headers

MEASURE_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
BRIDGE_ITEMS = [
    {"label": "Restructuring", "amount": 150000.0},
    {"label": "Share-based compensation", "amount": 128000.0},
]
GAAP_VALUE = 612000.0


def _measure_fixture(api, adjusted_value=890000.0, adjusted_index=1, gaap_index=2,
                     name="Measure Charter"):
    """An earnings release that is approvable on every other gate, carrying one
    freshly attached adjusted measure and sitting in IN_REVIEW."""
    committee = build_committee(
        api,
        seats=MEASURE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name=name,
    )
    scenario = scenario_close_open(api, committee)
    document = scenario.document(
        "EARNINGS_RELEASE", author_key="fin", title="Q2 Earnings Release",
        safe_harbor_present=True,
    )
    add_matching_tie_out(api, committee, document["id"])
    measure = add_adjusted_measure(
        api, committee, document["id"],
        measure_label="Adjusted EBITDA",
        adjusted_value=adjusted_value,
        comparable_gaap_value=GAAP_VALUE,
        reconciliation_items=BRIDGE_ITEMS,
        adjusted_prominence_index=adjusted_index,
        gaap_prominence_index=gaap_index,
    )
    in_review = submit_for_review(api, committee, document["id"], "fin")
    assert in_review["status"] == "IN_REVIEW"
    return committee, document, measure


def _approve(api, committee, document_id):
    return api.transition_document(
        document_id, action_payload("APPROVE"), committee.counsel("legal")
    )


def test_a_draft_measure_blocks_the_approval_on_reconciliation(api):
    """The measure is attached but never reconciled, so it sits in DRAFT with all
    three derived fields null, the parent document's gate reads
    BLOCKED_RECONCILIATION, and the approval is refused on the reconciliation
    code rather than the prominence one even though the indices are inverted.

    PRD 3.5: "A value of `BLOCKED_RECONCILIATION` yields `ERR_MEASURE_NOT_RECONCILED`, and a value of `BLOCKED_PROMINENCE` yields `ERR_MEASURE_PROMINENCE` — two distinct codes for two distinct defects, and reconciliation failures are reported ahead of prominence failures."

    Design: Difficulty/cross_entity_state_dependency/document_approval_gated_by_child_adjusted_measure_state_through_two_distinct_errors
    """
    committee, document, measure = _measure_fixture(api)

    assert measure["status"] == "DRAFT"
    assert measure["reconciliation_sum"] is None
    assert measure["reconciliation_gap"] is None
    assert measure["prominence_ok"] is None

    at_create = refresh_document(api, committee, document["id"])
    assert at_create["measure_gate_status"] == "BLOCKED_RECONCILIATION"
    assert at_create["tie_out_status"] == "PASSED"

    validate_error(
        _approve(api, committee, document["id"]), "ERR_MEASURE_NOT_RECONCILED", 409
    )
    assert refresh_document(api, committee, document["id"])["status"] == "IN_REVIEW"


def test_an_exact_bridge_with_the_wrong_prominence_moves_the_block_to_the_second_code(api):
    """Reconciling the bridge closes the gap to 0.00 but leaves the adjusted
    figure presented ahead of the reported one, so the measure lands in
    PROMINENCE_FAILED, the gate moves from BLOCKED_RECONCILIATION to
    BLOCKED_PROMINENCE, and the identical approval now returns the prominence
    code.

    PRD 3.7: "`prominence_ok` becomes true exactly when `gaap_prominence_index` is less than or equal to `adjusted_prominence_index`, that is, when the reported figure is presented at least as prominently as the adjusted one."

    Design: Difficulty/cross_entity_state_dependency/document_approval_gated_by_child_adjusted_measure_state_through_two_distinct_errors
    """
    committee, document, measure = _measure_fixture(api)

    reconciled = reconcile_measure(api, committee, measure["id"])
    assert_money(reconciled["reconciliation_sum"], 278000.00)
    assert_money(reconciled["reconciliation_gap"], 0.00)
    assert reconciled["prominence_ok"] is False
    assert reconciled["status"] == "PROMINENCE_FAILED"

    blocked = refresh_document(api, committee, document["id"])
    assert blocked["measure_gate_status"] == "BLOCKED_PROMINENCE"

    validate_error(
        _approve(api, committee, document["id"]), "ERR_MEASURE_PROMINENCE", 409
    )


def test_swapping_the_indices_clears_the_gate_and_lets_the_same_approval_through(api):
    """A second reconcile supplying swapped presentation indices moves the
    measure to RECONCILED without touching the bridge, the document gate reads
    CLEARED, and the approval that failed twice now succeeds.

    PRD 3.7: "A measure that satisfies both becomes `RECONCILED`."

    Design: Difficulty/cross_entity_state_dependency/document_approval_gated_by_child_adjusted_measure_state_through_two_distinct_errors
    """
    committee, document, measure = _measure_fixture(api)
    reconcile_measure(api, committee, measure["id"])

    swapped = reconcile_measure(
        api, committee, measure["id"],
        adjusted_prominence_index=2,
        gaap_prominence_index=1,
    )
    assert swapped["status"] == "RECONCILED"
    assert swapped["prominence_ok"] is True
    assert_money(swapped["reconciliation_gap"], 0.00)

    approved = validate_success(_approve(api, committee, document["id"]))
    assert approved["status"] == "APPROVED"
    assert approved["measure_gate_status"] == "CLEARED"


def test_a_two_cent_bridge_gap_rejects_the_measure_while_one_cent_reconciles(api):
    """With the presentation order already correct, a bridge that is two cents
    short leaves the measure REJECTED and the gate on the reconciliation branch,
    while the same bridge one cent short is inside the inclusive tolerance and
    reconciles.

    PRD 3.7: "The measure reconciles when the absolute value of `reconciliation_gap` is at most 0.01; the comparison is inclusive, so a gap of exactly 0.01 reconciles while a gap of 0.02 does not."

    Design: Difficulty/cross_entity_state_dependency/document_approval_gated_by_child_adjusted_measure_state_through_two_distinct_errors
    """
    committee, document, _ = _measure_fixture(
        api, adjusted_value=890000.02, adjusted_index=2, gaap_index=1,
        name="Gap Charter",
    )
    rows = validate_success(api.list_adjusted_measures(document["id"], admin_headers()))
    assert len(rows) == 1
    wide = reconcile_measure(api, committee, rows[0]["id"])
    assert_money(wide["reconciliation_gap"], 0.02)
    assert wide["status"] == "REJECTED"
    assert refresh_document(api, committee, document["id"])["measure_gate_status"] == (
        "BLOCKED_RECONCILIATION"
    )
    validate_error(
        _approve(api, committee, document["id"]), "ERR_MEASURE_NOT_RECONCILED", 409
    )

    other_committee, other_document, other_measure = _measure_fixture(
        api, adjusted_value=890000.01, adjusted_index=2, gaap_index=1,
        name="Cent Charter",
    )
    assert other_document["id"] != document["id"]
    tight = reconcile_measure(api, other_committee, other_measure["id"])
    assert_money(tight["reconciliation_gap"], 0.01)
    assert tight["status"] == "RECONCILED"


EVENT_SEATS = MEASURE_SEATS
EVENT_DESCRIPTION = "Goodwill impairment identified in the industrial segment."


def _event_fixture(api):
    """A REPORTABLE event on a cycle that also carries a CURRENT_REPORT document
    parked in IN_REVIEW, so the document is approvable but not yet approved."""
    committee = build_committee(
        api,
        seats=EVENT_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Current Report Charter",
    )
    scenario = scenario_close_open(api, committee)
    event = log_material_event(
        api, committee, scenario.cycle_id,
        category="IMPAIRMENT",
        occurred_utc="2026-08-02T10:00:00Z",
        discovered_utc="2026-08-03T09:00:00Z",
        magnitude_amount=620000,
        description=EVENT_DESCRIPTION,
    )
    event = assess_event(api, committee, event["id"], "REPORTABLE")
    document = scenario.document(
        "CURRENT_REPORT", author_key="fin", title="Form 8-K impairment",
        safe_harbor_present=True,
    )
    add_matching_tie_out(api, committee, document["id"], line_label="Impairment charge")
    submit_for_review(api, committee, document["id"], "fin")
    return committee, scenario, event, document


def _disclose(api, committee, event_id, document_id):
    return api.transition_material_event(
        event_id,
        action_payload("DISCLOSE", linked_document_id=document_id),
        committee.counsel("legal"),
    )


def test_disclosure_against_a_document_still_in_review_is_refused(api):
    """The event scores 6.20 against the ten-million base and its reportable
    deadline lands four business days after the Monday discovery, but the current
    report it names is only IN_REVIEW, so the disclosure is refused and the event
    keeps its own fields and its place in the open set.

    PRD 3.8: "`LegalCounsel` records a `REPORTABLE` event as `DISCLOSED` by naming the `linked_document_id` of the current report it went out on; that document must have `doc_type` `CURRENT_REPORT`, must belong to the same cycle and must be in `APPROVED`, or the request is rejected with `ERR_FILING_DOCUMENT_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/event_disclosure_requires_an_approved_current_report_document_on_the_same_cycle
    """
    committee, scenario, event, document = _event_fixture(api)

    assert_money(event["severity_score"], 6.20)
    assert event["assessment_status"] == "REPORTABLE"
    assert_instant_equals(event["current_report_deadline_utc"], "2026-08-07T17:30:00Z")
    assert refresh_cycle(api, scenario.cycle_id)["open_material_event_count"] == 1
    assert refresh_document(api, committee, document["id"])["status"] == "IN_REVIEW"

    validate_error(
        _disclose(api, committee, event["id"], document["id"]),
        "ERR_FILING_DOCUMENT_INVALID",
        409,
    )

    unchanged = validate_success(api.get_material_event(event["id"], admin_headers()))
    assert unchanged["assessment_status"] == "REPORTABLE"
    assert unchanged["linked_document_id"] is None
    assert refresh_cycle(api, scenario.cycle_id)["open_material_event_count"] == 1


def test_approving_that_document_lets_the_identical_disclosure_close_the_event(api):
    """Nothing about the event changes, yet approving the current report flips the
    identical disclosure request from refused to accepted: the event becomes
    DISCLOSED with the link stored and its deadline intact, the cycle's open count
    falls back to zero, and a replay is refused because DISCLOSED is terminal.

    PRD 3.8: "Disclosure stores the link, drops the event out of the open set, recomputes `open_material_event_count`, and releases `BLOCKED` certifications to `ELIGIBLE` on the same terms as the not-reportable branch."

    Design: Difficulty/cross_entity_state_dependency/event_disclosure_requires_an_approved_current_report_document_on_the_same_cycle
    """
    committee, scenario, event, document = _event_fixture(api)
    validate_error(
        _disclose(api, committee, event["id"], document["id"]),
        "ERR_FILING_DOCUMENT_INVALID",
        409,
    )

    approved = approve_document(api, committee, document["id"], "legal")
    assert approved["status"] == "APPROVED"

    disclosed = validate_success(_disclose(api, committee, event["id"], document["id"]))
    assert disclosed["assessment_status"] == "DISCLOSED"
    assert disclosed["linked_document_id"] == document["id"]
    assert_instant_equals(disclosed["current_report_deadline_utc"], "2026-08-07T17:30:00Z")
    assert refresh_cycle(api, scenario.cycle_id)["open_material_event_count"] == 0

    validate_error(
        _disclose(api, committee, event["id"], document["id"]), "ERR_ENTITY_TERMINAL", 409
    )


def _recusal_fixture(api):
    """One PENDING revenue request whose holder has since been recused."""
    committee = build_committee(
        api,
        seats=MEASURE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Recusal Charter",
    )
    scenario = scenario_close_open(api, committee)
    row = assign_subcert(
        api, committee, scenario.cycle_id, "fin", "REVENUE",
        due_utc="2026-08-04T17:00:00Z",
    )
    recused = committee.recuse("fin")
    assert recused["status"] == "RECUSED"
    return committee, scenario, row


def _submit(api, committee, subcert_id):
    return api.transition_subcert(
        subcert_id, action_payload("SUBMIT"), committee.leader("fin")
    )


def test_a_recused_holder_cannot_submit_and_the_refusal_leaves_no_trace(api):
    """The request itself is a perfectly valid PENDING row weighted 30.00; it is
    the holder's seat, two hops away, that refuses the submission, and the failed
    attempt leaves the row PENDING with a null submission stamp and the cycle's
    coverage still at 0.00.

    PRD 2.11: "Every committee member named in the request holds a usable seat: `status` is `ACTIVE`, with `RECUSED` and `VACATED` both rejected, and additionally `is_officer` is true when the field is `officer_member_id`. Applies to sub-certification creation, officer-certification registration, officer signing, document creation, tie-out item creation, tie-out review and sub-certification transitions — `ERR_MEMBER_SEAT_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/subcertification_submission_blocked_by_its_holders_recused_seat
    """
    committee, scenario, row = _recusal_fixture(api)
    assert_money(row["scope_weight"], 30.00)
    assert row["status"] == "PENDING"

    validate_error(_submit(api, committee, row["id"]), "ERR_MEMBER_SEAT_INVALID", 409)

    untouched = validate_success(api.get_subcert(row["id"], admin_headers()))
    assert untouched["status"] == "PENDING"
    assert untouched["submitted_utc"] is None
    mid_cycle = refresh_cycle(api, scenario.cycle_id)
    assert_money(mid_cycle["certification_coverage_pct"], 0.00)
    assert_money(mid_cycle["total_assigned_scope_weight"], 30.00)


def test_reinstating_the_seat_lets_the_same_submission_through_and_lifts_coverage(api):
    """Reinstatement returns the seat to ACTIVE without touching the request, and
    the identical submission then succeeds and carries coverage from 0.00 to
    100.00 over an unchanged 30.00 denominator.

    PRD 3.1: "Recusal moves a seat from `ACTIVE` to `RECUSED`; reinstatement moves it from `RECUSED` to `ACTIVE`; and vacating moves it to `VACATED` from either `ACTIVE` or `RECUSED`."

    Design: Difficulty/cross_entity_state_dependency/subcertification_submission_blocked_by_its_holders_recused_seat
    """
    committee, scenario, row = _recusal_fixture(api)
    validate_error(_submit(api, committee, row["id"]), "ERR_MEMBER_SEAT_INVALID", 409)

    reinstated = committee.reinstate("fin")
    assert reinstated["status"] == "ACTIVE"

    submitted = validate_success(_submit(api, committee, row["id"]))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_utc"] is not None

    after = refresh_cycle(api, scenario.cycle_id)
    assert_money(after["certification_coverage_pct"], 100.00)
    assert_money(after["total_assigned_scope_weight"], 30.00)
