"""Requests that break two rules at once, answered by the earlier rule.

Each case is paired with a control that removes the winning violation, so the
losing rule is shown to be live rather than dead code.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.assertions import assert_money
from test_helpers.factories import milestone_payload, tie_out_review_payload
from test_helpers.fixtures import (
    add_tie_out,
    assign_subcert,
    build_committee,
    build_cycle,
    refresh_cycle,
    scenario_close_open,
    scenario_review_open,
    submit_subcert,
)
from test_helpers.test_users import admin_headers

PRIORITY_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
    ("cfo", "Sam Fiscal", "FINANCE", True, True),
    ("ops", "Bo Ops", "OPERATIONS", False, False),
]
ATTESTATION = "I certify the Form 10-Q fairly presents results of operations."
DUE = "2026-08-04T17:00:00Z"


def _priority_fixture(api):
    """A certification-open cycle whose coverage is deliberately short at 54.55
    because one of its two sub-certifications is still pending."""
    committee = build_committee(
        api,
        seats=PRIORITY_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Priority Charter",
    )
    scenario = scenario_review_open(
        api, committee, calendar=("CLOSE", "REVIEW", "FILING")
    )
    revenue = assign_subcert(
        api, committee, scenario.cycle_id, "fin", "REVENUE", due_utc=DUE
    )
    submit_subcert(api, committee, revenue["id"], "fin")
    contingency = assign_subcert(
        api, committee, scenario.cycle_id, "legal", "LEGAL_CONTINGENCY", due_utc=DUE
    )
    scenario.approved_periodic_filing()
    scenario.run("REVIEW")
    scenario.open_certification()
    return committee, scenario, contingency


def test_a_blocked_slot_reports_the_state_rule_not_the_coverage_shortfall(api):
    """The signature breaks three rules at once — the slot is still BLOCKED,
    the scope is non-empty and coverage stands at 54.55 — and the answer is the
    earliest of them, ERR_INVALID_STATE, even though the coverage shortfall is
    why the slot never became eligible.

    PRD 2.11: "When a single request violates more than one rule, exactly one error is returned, and it is always the violation that sits **earliest** in the following ladder."

    Design: Difficulty/priority_pair_validation_conflict/blocked_certification_signature_reports_invalid_state_not_coverage_shortfall
    """
    committee, scenario, _ = _priority_fixture(api)

    before = refresh_cycle(api, scenario.cycle_id)
    assert before["status"] == "CERTIFICATION_OPEN"
    assert_money(before["certification_coverage_pct"], 54.55)

    slot = scenario.cert("ceo", "CEO_302")
    assert slot["status"] == "BLOCKED"

    refused = api.sign_officer_cert(
        slot["id"], {"attestation_text": ATTESTATION}, committee.officer("ceo")
    )
    validate_error(refused, "ERR_INVALID_STATE", 409)

    unchanged = validate_success(api.get_officer_cert(slot["id"], admin_headers()))
    assert unchanged["status"] == "BLOCKED"
    assert unchanged["signed_utc"] is None
    assert unchanged["attestation_text"] is None


def test_an_eligible_slot_diluted_below_full_coverage_reports_the_coverage_rule(api):
    """Completing the outstanding sub-certification lifts coverage to 100.00, so
    a slot registered at that moment is ELIGIBLE straight away; assigning one
    more pending row then dilutes coverage to 73.33 and the same signature is
    refused with the coverage rule, which proves that rule is live and distinct
    from the state rule.

    PRD 3.8: "The cycle's `certification_coverage_pct` must be exactly 100.00, else `ERR_CERT_COVERAGE_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/blocked_certification_signature_reports_invalid_state_not_coverage_shortfall
    """
    committee, scenario, contingency = _priority_fixture(api)
    submit_subcert(api, committee, contingency["id"], "legal")

    complete = refresh_cycle(api, scenario.cycle_id)
    assert_money(complete["certification_coverage_pct"], 100.00)

    slot = scenario.cert("cfo", "CFO_302")
    assert slot["status"] == "ELIGIBLE"

    assign_subcert(api, committee, scenario.cycle_id, "ops", "OPERATIONS", due_utc=DUE)
    diluted = refresh_cycle(api, scenario.cycle_id)
    assert_money(diluted["certification_coverage_pct"], 73.33)

    refused = api.sign_officer_cert(
        slot["id"], {"attestation_text": ATTESTATION}, committee.officer("cfo")
    )
    validate_error(refused, "ERR_CERT_COVERAGE_INSUFFICIENT", 409)
    unchanged = validate_success(api.get_officer_cert(slot["id"], admin_headers()))
    assert unchanged["status"] == "ELIGIBLE"
    assert unchanged["signed_utc"] is None


SEAT_PAIR = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]


def _self_review_fixture(api):
    committee = build_committee(
        api,
        seats=SEAT_PAIR,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Seat Charter",
    )
    scenario = scenario_close_open(api, committee)
    document = scenario.document(
        "PERIODIC_FILING", author_key="legal", title="Form 10-Q FY2026-Q2",
        safe_harbor_present=True, role="counsel",
    )
    item = add_tie_out(
        api, committee, document["id"], "Total revenue", 4120000, 4120000, tolerance_bp=25
    )
    return committee, item


def _self_review(api, committee, item_id):
    return api.review_tie_out_item(
        item_id,
        tie_out_review_payload(committee.mid("fin"), "ACCEPT"),
        committee.controller("fin"),
    )


def test_a_recused_reviewer_who_is_also_the_preparer_reports_the_seat_rule(api):
    """The reviewer named on the review is both RECUSED and the line's own
    preparer, so two adjacent rules are broken at once and the seat rule answers
    first with ERR_MEMBER_SEAT_INVALID; the line records no reviewer at all.

    PRD 2.11: "Every committee member named in the request holds a usable seat: `status` is `ACTIVE`, with `RECUSED` and `VACATED` both rejected, and additionally `is_officer` is true when the field is `officer_member_id`."

    Design: Difficulty/priority_pair_validation_conflict/recused_self_reviewer_reports_seat_invalid_not_self_review
    """
    committee, item = _self_review_fixture(api)

    recused = committee.recuse("fin")
    assert recused["status"] == "RECUSED"

    refused = _self_review(api, committee, item["id"])
    validate_error(refused, "ERR_MEMBER_SEAT_INVALID", 409)

    untouched = validate_success(api.get_tie_out_item(item["id"], admin_headers()))
    assert untouched["reviewer_member_id"] is None
    assert untouched["review_decision"] is None
    assert untouched["status"] == "MATCHED"


def test_reinstating_the_seat_flips_the_identical_request_to_self_review(api):
    """Once the seat is usable again the very same review — same reviewer, same
    decision, same line — stops reporting the seat rule and reports
    ERR_SOD_SELF_REVIEW instead, so neither rule was masking the other.

    PRD 3.6: "The reviewer's seat is checked before the separation rule is: a reviewer who is `RECUSED` or `VACATED` yields `ERR_MEMBER_SEAT_INVALID`, and only once the seat is usable does the system reject a reviewer equal to the item's `preparer_member_id` with `ERR_SOD_SELF_REVIEW`."

    Design: Difficulty/priority_pair_validation_conflict/recused_self_reviewer_reports_seat_invalid_not_self_review
    """
    committee, item = _self_review_fixture(api)

    committee.recuse("fin")
    validate_error(_self_review(api, committee, item["id"]), "ERR_MEMBER_SEAT_INVALID", 409)

    reinstated = committee.reinstate("fin")
    assert reinstated["status"] == "ACTIVE"

    validate_error(_self_review(api, committee, item["id"]), "ERR_SOD_SELF_REVIEW", 409)

    untouched = validate_success(api.get_tie_out_item(item["id"], admin_headers()))
    assert untouched["reviewer_member_id"] is None
    assert untouched["review_decision"] is None


SOLE_FINANCE_SEAT = [("fin", "Nora Finance", "FINANCE", False, True)]


def _calendar_fixture(api):
    committee = build_committee(
        api,
        seats=SOLE_FINANCE_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Calendar Charter",
        chair_key="fin",
    )
    cycle = build_cycle(api, committee)
    first = api.create_milestone(
        cycle["id"],
        milestone_payload("CLOSE", "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z"),
        committee.controller("fin"),
    )
    validate_success(first, 201)
    return committee, cycle


def test_a_window_that_both_overlaps_and_runs_past_the_deadline_reports_the_overlap(api):
    """The candidate close window 2026-08-02 to 2026-08-11 overlaps its sibling
    and also ends after the statutory deadline of 2026-08-10T17:30:00Z; the
    overlap rule sits earlier, so the answer is 409 and never the 422 the
    deadline rule would return, and the calendar still holds a single window.

    PRD 3.3: "Overlap is judged under half-open geometry: two windows overlap when the candidate's start is strictly before the sibling's end and the sibling's start is strictly before the candidate's end."

    Design: Difficulty/priority_pair_validation_conflict/overlapping_and_past_deadline_milestone_reports_overlap_not_deadline
    """
    committee, cycle = _calendar_fixture(api)
    assert cycle["statutory_deadline_utc"].startswith("2026-08-10T17:30:00")

    refused = api.create_milestone(
        cycle["id"],
        milestone_payload("CLOSE", "2026-08-02T00:00:00Z", "2026-08-11T00:00:00Z"),
        committee.controller("fin"),
    )
    validate_error(refused, "ERR_MILESTONE_WINDOW_OVERLAP", 409)

    rows = validate_success(api.list_cycle_milestones(cycle["id"], admin_headers()))
    assert len(rows) == 1


def test_clearing_the_overlap_exposes_the_deadline_rule_and_touching_windows_pass(api):
    """A candidate that starts after its sibling ends clears the overlap rule and
    is then refused with 422 ERR_MILESTONE_PAST_DEADLINE, while a window that
    merely touches the sibling's end instant and stays inside the deadline is
    accepted.

    PRD 3.3: "The third rule is **deadline containment**: the candidate's `planned_end_utc` must fall at or before the cycle's `statutory_deadline_utc`, and its `planned_start_utc` must be strictly before its `planned_end_utc`."

    Design: Difficulty/priority_pair_validation_conflict/overlapping_and_past_deadline_milestone_reports_overlap_not_deadline
    """
    committee, cycle = _calendar_fixture(api)

    past_deadline = api.create_milestone(
        cycle["id"],
        milestone_payload("CLOSE", "2026-08-04T00:00:00Z", "2026-08-11T00:00:00Z"),
        committee.controller("fin"),
    )
    validate_error(past_deadline, "ERR_MILESTONE_PAST_DEADLINE", 422)

    touching = api.create_milestone(
        cycle["id"],
        milestone_payload("CLOSE", "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z"),
        committee.controller("fin"),
    )
    accepted = validate_success(touching, 201)
    assert accepted["kind"] == "CLOSE"
    assert accepted["status"] == "PLANNED"

    rows = validate_success(api.list_cycle_milestones(cycle["id"], admin_headers()))
    assert len(rows) == 2
