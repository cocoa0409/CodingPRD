"""Cascades that travel further than the record the client touched.

One tie-out append unwinds five entities, a material event drives certification
eligibility in both directions from two levels away, and a single vacated seat
propagates up into its charter and sideways into a reporting cycle.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.assertions import assert_instant_equals, assert_money
from test_helpers.factories import action_payload, filing_payload
from test_helpers.fixtures import (
    add_tie_out,
    assess_event,
    assign_subcert,
    build_committee,
    log_material_event,
    refresh_cycle,
    refresh_document,
    scenario_close_open,
    submit_subcert,
)
from test_helpers.test_users import admin_headers

BREAK_LABEL = "Deferred revenue"


def _cert(api, cert_id):
    return validate_success(api.get_officer_cert(cert_id, admin_headers()))


def _tie_out_rows(api, document_id):
    rows = validate_success(api.list_tie_out_items(admin_headers(), document_id=document_id))
    return {row["line_label"]: row for row in rows}


def test_a_tie_out_break_drags_the_approved_document_back_into_changes_requested(
    filing_ready_cycle,
):
    """Appending a line that is 750 basis points out re-tiers the whole schedule
    to 0.50, so the new line fails against an effective tolerance of 12 and its
    already-matching sibling silently re-tightens to 12 as well; the document's
    tie-out verdict flips to FAILED and the approved document falls back to
    CHANGES_REQUESTED at revision round 1 with the system's own change note.

    PRD 3.6: "The third, caused by that failure, is the document moving from `APPROVED` to `CHANGES_REQUESTED`, with its `revision_round` incremented by 1 and its `change_note` set by the system to the literal text `auto: tie-out variance detected`."

    Design: Difficulty/transitive_cascade/tie_out_break_on_approved_document_cascades_five_hops_to_revoked_certifications
    """
    scenario = filing_ready_cycle
    api, committee = scenario.api, scenario.committee
    document = scenario.documents["PERIODIC_FILING"]

    before_cycle = refresh_cycle(api, scenario.cycle_id)
    assert before_cycle["status"] == "FILING_READY"
    assert before_cycle["min_slack_days_business"] == 1
    before_doc = refresh_document(api, committee, document["id"])
    assert before_doc["status"] == "APPROVED"
    assert before_doc["revision_round"] == 0
    assert before_doc["tie_out_status"] == "PASSED"

    broken = add_tie_out(
        api, committee, document["id"], BREAK_LABEL, 4300000, 4000000, tolerance_bp=25
    )
    assert broken["raw_variance_bp"] == 750
    assert broken["effective_tolerance_bp"] == 12
    assert broken["status"] == "VARIANCE"

    rows = _tie_out_rows(api, document["id"])
    sibling = rows["Total revenue"]
    assert sibling["raw_variance_bp"] == 0
    assert sibling["effective_tolerance_bp"] == 12
    assert sibling["status"] == "MATCHED"

    after_doc = refresh_document(api, committee, document["id"])
    assert after_doc["tie_out_total_variance_bp"] == 750
    assert_money(after_doc["tie_out_tier_multiplier"], 0.50)
    assert after_doc["tie_out_status"] == "FAILED"
    assert after_doc["status"] == "CHANGES_REQUESTED"
    assert after_doc["revision_round"] == 1
    assert after_doc["change_note"] == "auto: tie-out variance detected"


def test_the_same_break_drops_the_cycle_out_of_filing_ready_and_revokes_both_signatures(
    filing_ready_cycle,
):
    """The document leaving APPROVED pulls the cycle from FILING_READY back to
    REVIEW_OPEN, and the cycle leaving FILING_READY revokes both signed
    instruments, clearing signed_utc and attestation_text while keeping
    coverage_pct_at_signing as an audit trace; a filing attempted afterwards is
    refused for the cycle's state, because the cycle has left FILING_READY and
    the state rule of the ladder sits ahead of the document-class rule.

    PRD 3.6: "The fifth, caused by the cycle leaving `FILING_READY`, is that every officer certification on the cycle whose `status` is `ELIGIBLE` or `SIGNED` moves to `REVOKED`; a revoked certification has its `signed_utc` and `attestation_text` cleared, while `coverage_pct_at_signing` is deliberately **retained** as an audit trace of what the officer relied on."

    PRD 3.9: "An **original filing** omits `amends_filing_id` and is legal only from `FILING_READY`; it moves the cycle's workflow axis to `FILED` and the named document from `APPROVED` to `FILED`."

    Design: Difficulty/transitive_cascade/tie_out_break_on_approved_document_cascades_five_hops_to_revoked_certifications
    """
    scenario = filing_ready_cycle
    api, committee = scenario.api, scenario.committee
    document = scenario.documents["PERIODIC_FILING"]
    ceo_cert_id = scenario.certs["CEO_302"]["id"]
    cfo_cert_id = scenario.certs["CFO_302"]["id"]
    assert scenario.certs["CEO_302"]["status"] == "SIGNED"
    assert_money(scenario.certs["CFO_302"]["coverage_pct_at_signing"], 100.00)

    add_tie_out(
        api, committee, document["id"], BREAK_LABEL, 4300000, 4000000, tolerance_bp=25
    )

    after_cycle = refresh_cycle(api, scenario.cycle_id)
    assert after_cycle["status"] == "REVIEW_OPEN"
    assert after_cycle["restatement_stage"] == "NONE"

    ceo = _cert(api, ceo_cert_id)
    cfo = _cert(api, cfo_cert_id)
    assert ceo["status"] == "REVOKED"
    assert ceo["signed_utc"] is None
    assert ceo["attestation_text"] is None
    assert_money(ceo["coverage_pct_at_signing"], 100.00)
    assert cfo["status"] == "REVOKED"
    assert cfo["signed_utc"] is None
    assert cfo["attestation_text"] is None

    # Rule 13 of the §2.11 ladder ("the requested transition is declared from
    # the row's current state") fires ahead of rule 36 ("the document named on a
    # filing ... is APPROVED"), so the cycle's fall out of FILING_READY is what
    # the refusal names even though the document is no longer APPROVED either.
    refused = api.create_filing(
        filing_payload(scenario.cycle_id, document["id"]), admin_headers()
    )
    validate_error(refused, "ERR_INVALID_STATE", 409)


def test_logging_an_event_blocks_both_eligible_signatures_from_two_levels_away(
    certification_open_cycle,
):
    """A logged event scores 300000 / 10000000 as 3.00, lands UNASSESSED, and
    that alone lifts open_material_event_count from 0 to 1 and drives both
    ELIGIBLE certification slots back to BLOCKED without either slot being
    touched by the request.

    PRD 3.8: "So merely logging an event pushes the count up, and every `OfficerCertification` on the cycle sitting in `ELIGIBLE` is driven back to `BLOCKED`; the cycle's `version` increments."

    Design: Difficulty/transitive_cascade/material_event_reassessment_cascades_three_hops_and_reverses_certification_eligibility
    """
    scenario = certification_open_cycle
    api, committee = scenario.api, scenario.committee
    ceo_cert_id = scenario.certs["CEO_302"]["id"]
    cfo_cert_id = scenario.certs["CFO_302"]["id"]

    before = refresh_cycle(api, scenario.cycle_id)
    assert before["status"] == "CERTIFICATION_OPEN"
    assert before["open_material_event_count"] == 0
    assert _cert(api, ceo_cert_id)["status"] == "ELIGIBLE"
    assert _cert(api, cfo_cert_id)["status"] == "ELIGIBLE"

    event = log_material_event(
        api, committee, scenario.cycle_id,
        occurred_utc="2026-07-30T14:00:00Z",
        discovered_utc="2026-08-01T09:00:00Z",
        magnitude_amount=300000,
        description="Adverse ruling in a supplier dispute.",
    )
    assert_money(event["severity_score"], 3.00)
    assert event["assessment_status"] == "UNASSESSED"
    assert event["current_report_deadline_utc"] is None

    after = refresh_cycle(api, scenario.cycle_id)
    assert after["open_material_event_count"] == 1
    assert _cert(api, ceo_cert_id)["status"] == "BLOCKED"
    assert _cert(api, cfo_cert_id)["status"] == "BLOCKED"


def test_the_not_reportable_release_reverses_and_a_re_assessment_blocks_again(
    certification_open_cycle,
):
    """Assessing the event NOT_REPORTABLE takes the count back to zero and
    releases both slots to ELIGIBLE; re-assessing it REPORTABLE on new
    information computes the deadline four business days after discovery,
    pushes the count back to 1, re-blocks both slots even though the score of
    3.00 is under the 5.00 floor, and makes the open event the first thing a
    filing-readiness declaration complains about.

    PRD 3.8: "Re-assessment is permitted in one direction: an event in `NOT_REPORTABLE` may be re-assessed as `REPORTABLE` when new information arrives, which recomputes the deadline, drives `open_material_event_count` back up — from zero to one when this is the cycle's only open event — and re-blocks every `ELIGIBLE` certification."

    Design: Difficulty/transitive_cascade/material_event_reassessment_cascades_three_hops_and_reverses_certification_eligibility
    """
    scenario = certification_open_cycle
    api, committee = scenario.api, scenario.committee
    ceo_cert_id = scenario.certs["CEO_302"]["id"]
    cfo_cert_id = scenario.certs["CFO_302"]["id"]

    event = log_material_event(
        api, committee, scenario.cycle_id,
        occurred_utc="2026-07-30T14:00:00Z",
        discovered_utc="2026-08-01T09:00:00Z",
        magnitude_amount=300000,
        description="Adverse ruling in a supplier dispute.",
    )

    cleared = assess_event(
        api, committee, event["id"], "NOT_REPORTABLE",
        determination_note="Below the 5 percent materiality floor and not otherwise reportable.",
    )
    assert cleared["assessment_status"] == "NOT_REPORTABLE"
    assert cleared["current_report_deadline_utc"] is None
    released = refresh_cycle(api, scenario.cycle_id)
    assert released["open_material_event_count"] == 0
    assert _cert(api, ceo_cert_id)["status"] == "ELIGIBLE"
    assert _cert(api, cfo_cert_id)["status"] == "ELIGIBLE"

    reopened = assess_event(
        api, committee, event["id"], "REPORTABLE",
        determination_note="New information: the ruling triggers a cross-default disclosure.",
    )
    assert reopened["assessment_status"] == "REPORTABLE"
    assert_instant_equals(reopened["current_report_deadline_utc"], "2026-08-06T17:30:00Z")

    blocked = refresh_cycle(api, scenario.cycle_id)
    assert blocked["open_material_event_count"] == 1
    assert blocked["status"] == "CERTIFICATION_OPEN"
    assert _cert(api, ceo_cert_id)["status"] == "BLOCKED"
    assert _cert(api, cfo_cert_id)["status"] == "BLOCKED"

    refused = api.transition_cycle(
        scenario.cycle_id, action_payload("DECLARE_FILING_READY"), committee.chair()
    )
    validate_error(refused, "ERR_OPEN_MATERIAL_EVENT", 409)


VACANCY_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ops", "Bo Ops", "OPERATIONS", False, True),
]


def _vacancy_fixture(api):
    committee = build_committee(
        api,
        seats=VACANCY_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Vacancy Charter",
    )
    scenario = scenario_close_open(api, committee)
    pending = assign_subcert(
        api, committee, scenario.cycle_id, "ops", "OPERATIONS",
        due_utc="2026-08-04T12:00:00Z",
    )
    delivered = assign_subcert(
        api, committee, scenario.cycle_id, "ops", "LEGAL_CONTINGENCY",
        due_utc="2026-08-04T12:00:00Z",
    )
    finance_row = assign_subcert(
        api, committee, scenario.cycle_id, "fin", "REVENUE",
        due_utc="2026-08-04T12:00:00Z",
    )
    delivered = submit_subcert(api, committee, delivered["id"], "ops")
    finance_row = submit_subcert(api, committee, finance_row["id"], "fin")
    return committee, scenario, pending, delivered, finance_row


def test_vacating_a_seat_reshapes_the_charter_it_belongs_to(api):
    """The vacated seat is the only record the client names, yet the charter's
    active voting count falls from 3 to 2 and OPERATIONS drops out of
    covered_functions while FINANCE and LEGAL survive; the charter itself stays
    ADOPTED.

    PRD 3.1: "All three recompute the owning charter's `active_voting_member_count` and `covered_functions` and increment both the member's `version` and the charter's `version`."

    Design: Difficulty/transitive_cascade/seat_vacancy_cascades_four_hops_and_raises_coverage_by_shrinking_the_denominator
    """
    committee, _, _, _, _ = _vacancy_fixture(api)

    before = committee.reload()
    assert before["active_voting_member_count"] == 3
    assert "OPERATIONS" in before["covered_functions"]

    vacated = committee.vacate("ops")
    assert vacated["status"] == "VACATED"

    after = committee.reload()
    assert after["active_voting_member_count"] == 2
    assert "OPERATIONS" not in after["covered_functions"]
    assert "FINANCE" in after["covered_functions"]
    assert "LEGAL" in after["covered_functions"]
    assert after["status"] == "ADOPTED"
    assert after["version"] > before["version"]


def test_the_vacancy_voids_only_the_pending_row_and_coverage_rises(api):
    """Only the departing member's PENDING row is voided, the row it had already
    submitted survives, and the cycle's weight falls from 75.00 to 55.00 while
    coverage climbs from 73.33 to 100.00 because the void left the numerator
    alone; the voided row is terminal.

    PRD 3.1: "Note the counter-intuitive direction of that last step: dropping a `PENDING` row removes weight from the coverage denominator while leaving the numerator alone, so coverage **rises**."

    Design: Difficulty/transitive_cascade/seat_vacancy_cascades_four_hops_and_raises_coverage_by_shrinking_the_denominator
    """
    committee, scenario, pending, delivered, finance_row = _vacancy_fixture(api)

    before = refresh_cycle(api, scenario.cycle_id)
    assert_money(before["total_assigned_scope_weight"], 75.00)
    assert_money(before["certification_coverage_pct"], 73.33)

    committee.vacate("ops")

    voided = validate_success(api.get_subcert(pending["id"], admin_headers()))
    assert voided["status"] == "VOID"
    assert validate_success(api.get_subcert(delivered["id"], admin_headers()))["status"] == "SUBMITTED"
    assert validate_success(api.get_subcert(finance_row["id"], admin_headers()))["status"] == "SUBMITTED"

    after = refresh_cycle(api, scenario.cycle_id)
    assert_money(after["total_assigned_scope_weight"], 55.00)
    assert_money(after["certification_coverage_pct"], 100.00)

    refused = api.transition_subcert(
        pending["id"], action_payload("SUBMIT"), committee.leader("ops")
    )
    validate_error(refused, "ERR_ENTITY_TERMINAL", 409)
