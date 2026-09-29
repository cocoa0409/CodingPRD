"""Values sitting exactly on a threshold, and one step past it.

A tie-out line landing exactly on its effective tolerance, a filing stamped
exactly on the statutory deadline, and a coverage ratio over an empty scope.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.assertions import assert_instant_equals, assert_money
from test_helpers.factories import action_payload
from test_helpers.fixtures import (
    add_tie_out,
    assign_subcert,
    build_committee,
    refresh_cycle,
    refresh_document,
    scenario_close_open,
    scenario_review_open,
    set_clock,
    sign_cert,
    submit_filing,
    submit_for_review,
    submit_subcert,
)
from test_helpers.test_users import admin_headers

TOLERANCE_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
SCOPE_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
]
ATTESTATION = "I certify the Form 10-Q fairly presents results of operations."


def _document_with_line(api, reported_value):
    committee = build_committee(
        api,
        seats=TOLERANCE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Boundary Charter",
    )
    scenario = scenario_close_open(api, committee)
    document = scenario.document(
        "PERIODIC_FILING", author_key="fin", title="Form 10-Q FY2026-Q2",
        safe_harbor_present=True,
    )
    item = add_tie_out(
        api, committee, document["id"], "Interest expense", reported_value, 1000.0,
        tolerance_bp=25,
    )
    return committee, document, item


def test_a_variance_landing_exactly_on_the_effective_tolerance_matches(api):
    """1002.50 reported against a source record of 1000.00 is exactly 25 basis
    points out, which equals the effective tolerance of 25, so the line MATCHES
    and the schedule reads PASSED.

    PRD 3.6: "The item's `status` becomes `MATCHED` when its `raw_variance_bp` is less than or equal to its `effective_tolerance_bp`, and `VARIANCE` otherwise."

    Design: Difficulty/boundary_precision_check/tie_out_variance_exactly_on_effective_tolerance_matches_and_one_bp_more_fails
    """
    committee, document, item = _document_with_line(api, 1002.5)

    assert item["raw_variance_bp"] == 25
    assert item["effective_tolerance_bp"] == 25
    assert item["status"] == "MATCHED"

    parent = refresh_document(api, committee, document["id"])
    assert parent["tie_out_total_variance_bp"] == 25
    assert_money(parent["tie_out_tier_multiplier"], 1.00)
    assert parent["tie_out_status"] == "PASSED"


def test_one_basis_point_more_fails_the_line_and_blocks_the_approval(api):
    """1002.60 rounds to 26 basis points against the same tolerance of 25, so the
    line reads VARIANCE, the schedule reads FAILED, and the document can no
    longer be approved.

    PRD 3.6: "The comparison is inclusive, so a variance landing exactly on the effective tolerance **passes**."

    Design: Difficulty/boundary_precision_check/tie_out_variance_exactly_on_effective_tolerance_matches_and_one_bp_more_fails
    """
    committee, document, item = _document_with_line(api, 1002.6)

    assert item["raw_variance_bp"] == 26
    assert item["effective_tolerance_bp"] == 25
    assert item["status"] == "VARIANCE"

    parent = refresh_document(api, committee, document["id"])
    assert parent["tie_out_total_variance_bp"] == 26
    assert_money(parent["tie_out_tier_multiplier"], 1.00)
    assert parent["tie_out_status"] == "FAILED"

    submit_for_review(api, committee, document["id"], "fin")
    refused = api.transition_document(
        document["id"], action_payload("APPROVE"), committee.counsel("legal")
    )
    validate_error(refused, "ERR_TIE_OUT_NOT_PASSED", 409)


def _milestone_of(api, cycle_id, kind):
    rows = validate_success(api.list_cycle_milestones(cycle_id, admin_headers()))
    matches = [row for row in rows if row["kind"] == kind]
    assert len(matches) == 1
    return matches[0]


def _signed_at_the_deadline(scenario):
    """Both quarterly instruments signed, then the clock jumped to the statutory
    deadline instant."""
    api = scenario.api
    scenario.sign("CEO_302", "ceo")
    scenario.sign("CFO_302", "cfo")
    set_clock(api, "2026-08-10T17:30:00Z")
    return scenario


def test_the_breach_sweep_empties_the_open_set_so_slack_reads_the_sentinel(
    certification_open_cycle,
):
    """Declaring readiness at the deadline instant runs the breach sweep, which
    moves the last PLANNED milestone to BREACHED; with no open milestone left the
    cycle's business-day slack reads the 9999 sentinel rather than 0 or a
    negative number, which is what lets the slack gate pass.

    PRD 3.3: "When no open milestone remains, both cycle-level figures are set to 9999."

    Design: Difficulty/boundary_precision_check/filing_stamped_exactly_on_statutory_deadline_is_not_late
    """
    scenario = _signed_at_the_deadline(certification_open_cycle)
    api = scenario.api

    declared = scenario.declare_filing_ready()
    assert declared["status"] == "FILING_READY"
    assert declared["min_slack_days_business"] == 9999
    assert declared["min_slack_days_calendar"] == 9999

    assert _milestone_of(api, scenario.cycle_id, "FILING")["status"] == "BREACHED"
    assert _milestone_of(api, scenario.cycle_id, "REVIEW")["status"] == "COMPLETE"
    assert _milestone_of(api, scenario.cycle_id, "CLOSE")["status"] == "COMPLETE"


def test_a_filing_stamped_exactly_on_the_deadline_is_not_late(certification_open_cycle):
    """The filing is stamped from a clock sitting exactly on the statutory
    deadline, and because lateness is a strict comparison the row is not late; it
    is the cycle's first filing, so its accession label ends in 1.

    PRD 3.9: "Its `late_flag` is true when `filed_utc` is strictly after the cycle's `statutory_deadline_utc`, so a filing stamped at exactly the deadline instant is **not** late."

    Design: Difficulty/boundary_precision_check/filing_stamped_exactly_on_statutory_deadline_is_not_late
    """
    scenario = _signed_at_the_deadline(certification_open_cycle)
    api, committee = scenario.api, scenario.committee
    document = scenario.documents["PERIODIC_FILING"]

    before = refresh_cycle(api, scenario.cycle_id)
    assert_instant_equals(before["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    scenario.declare_filing_ready()

    filing = submit_filing(api, scenario.cycle_id, document["id"])
    assert_instant_equals(filing["filed_utc"], "2026-08-10T17:30:00Z")
    assert filing["late_flag"] is False
    assert filing["accession_label"] == "FORM_10Q-FY2026-Q2-1"
    assert filing["form_type"] == "FORM_10Q"
    assert filing["status"] == "SUBMITTED"

    assert refresh_cycle(api, scenario.cycle_id)["status"] == "FILED"
    assert refresh_document(api, committee, document["id"])["status"] == "FILED"


def _empty_scope_fixture(api):
    """A cycle taken to the edge of certification with no sub-certification
    request ever assigned, and one CEO slot registered while the cycle is still
    in review so the slot is created BLOCKED."""
    committee = build_committee(
        api,
        seats=SCOPE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Empty Scope Charter",
    )
    scenario = scenario_review_open(api, committee, calendar=("CLOSE", "REVIEW", "FILING"))
    scenario.approved_periodic_filing()
    scenario.run("REVIEW")
    cert = scenario.cert("ceo", "CEO_302")
    return scenario, cert


def _cert(api, cert_id):
    return validate_success(api.get_officer_cert(cert_id, admin_headers()))


def test_an_empty_scope_reads_zero_coverage_yet_the_slot_still_becomes_eligible(api):
    """With no sub-certification request on the cycle at all, coverage reads the
    empty-set convention 0.00 rather than a vacuous 100.00, and the certification
    window still lifts the slot from BLOCKED to ELIGIBLE because eligibility keys
    on the transition and the open-event count, not on coverage.

    PRD 3.8: "A slot moves from `BLOCKED` to `ELIGIBLE` when the cycle enters `CERTIFICATION_OPEN` with `open_material_event_count` at zero, and when a material event resolution brings that count down to zero while the cycle is in `CERTIFICATION_OPEN`."

    Design: Difficulty/boundary_precision_check/empty_subcertification_scope_reads_zero_coverage_and_trips_the_scope_rule
    """
    scenario, cert = _empty_scope_fixture(api)

    assert cert["status"] == "BLOCKED"
    assert cert["signed_utc"] is None
    assert cert["attestation_text"] is None
    assert cert["coverage_pct_at_signing"] is None

    at_create = refresh_cycle(api, scenario.cycle_id)
    assert_money(at_create["total_assigned_scope_weight"], 0.00)
    assert_money(at_create["certification_coverage_pct"], 0.00)

    opened = scenario.open_certification()
    assert opened["status"] == "CERTIFICATION_OPEN"
    assert_money(opened["certification_coverage_pct"], 0.00)
    assert abs(float(opened["certification_coverage_pct"]) - 100.00) > 0.01
    assert _cert(api, cert["id"])["status"] == "ELIGIBLE"


def test_signing_against_an_empty_scope_reports_the_scope_rule_not_the_coverage_rule(api):
    """The empty-scope condition sits ahead of the coverage condition in the
    ladder, so the eligible officer's signature is refused with
    ERR_CERT_SCOPE_EMPTY even though coverage over the empty set reads 0.00 and
    would otherwise trip the coverage rule, and the slot is left untouched.

    PRD 2.11: "And because the empty-scope check at rule 42 precedes the coverage check at rule 43, signing against a cycle that has no sub-certification requests at all reports `ERR_CERT_SCOPE_EMPTY` even though the coverage percentage of an empty set reads 0.00 and would otherwise trip rule 43."

    Design: Difficulty/boundary_precision_check/empty_subcertification_scope_reads_zero_coverage_and_trips_the_scope_rule
    """
    scenario, cert = _empty_scope_fixture(api)
    scenario.open_certification()
    assert _cert(api, cert["id"])["status"] == "ELIGIBLE"

    refused = api.sign_officer_cert(
        cert["id"], {"attestation_text": ATTESTATION}, scenario.committee.officer("ceo")
    )
    validate_error(refused, "ERR_CERT_SCOPE_EMPTY", 409)

    untouched = _cert(api, cert["id"])
    assert untouched["status"] == "ELIGIBLE"
    assert untouched["signed_utc"] is None
    assert untouched["attestation_text"] is None


def test_one_submitted_row_makes_the_scope_non_empty_and_the_signature_lands(api):
    """A single assigned and submitted request is the smallest non-empty scope:
    it clears the scope rule and reads 100.00 coverage, so the same signature the
    empty cycle refused now succeeds and freezes the coverage snapshot at 100.00.

    PRD 3.8: "On success the slot moves to `SIGNED`, `signed_utc` is stamped from the logical clock, `attestation_text` is stored, and `coverage_pct_at_signing` is frozen at the cycle's `certification_coverage_pct` as it reads at that instant — a snapshot that is deliberately **not** recomputed afterwards, so it remains an audit trace of what the officer actually relied on."

    Design: Difficulty/boundary_precision_check/empty_subcertification_scope_reads_zero_coverage_and_trips_the_scope_rule
    """
    scenario, cert = _empty_scope_fixture(api)
    scenario.open_certification()

    row = assign_subcert(
        api, scenario.committee, scenario.cycle_id, "fin", "REVENUE",
        due_utc="2026-08-04T17:00:00Z",
    )
    assert_money(row["scope_weight"], 30.00)
    only_row = refresh_cycle(api, scenario.cycle_id)
    assert_money(only_row["total_assigned_scope_weight"], 30.00)
    assert_money(only_row["certification_coverage_pct"], 0.00)

    submit_subcert(api, scenario.committee, row["id"], "fin")
    covered = refresh_cycle(api, scenario.cycle_id)
    assert_money(covered["certification_coverage_pct"], 100.00)

    signed = sign_cert(
        api, scenario.committee, cert["id"], "ceo", attestation_text=ATTESTATION
    )
    assert signed["status"] == "SIGNED"
    assert signed["attestation_text"] == ATTESTATION
    assert_instant_equals(signed["signed_utc"], "2026-08-01T00:00:00Z")
    assert_money(signed["coverage_pct_at_signing"], 100.00)
