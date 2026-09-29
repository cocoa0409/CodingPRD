"""Gates read at the instant they are satisfied, and at the instant they are not.

A readiness dashboard whose blocking list must be empty, a rule that keys on a
document's type rather than on its flag, a due instant probed at both ends of its
window, an approval gate re-derived from a whole-set recompute, and a transition
that reads the charter it was pinned to.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.assertions import assert_instant_equals, assert_money
from test_helpers.factories import action_payload, cycle_payload, subcert_payload
from test_helpers.fixtures import (
    add_matching_tie_out,
    add_milestone,
    add_tie_out,
    approve_document,
    build_committee,
    build_cycle,
    complete_milestone,
    create_document,
    open_close,
    readiness,
    refresh_cycle,
    refresh_document,
    review_tie_out,
    scenario_close_open,
    scenario_review_open,
    start_milestone,
    submit_for_review,
)
from test_helpers.test_users import admin_headers

GATE_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
READINESS_SEATS = GATE_SEATS + [
    ("ceo", "Rhea Chief", "FINANCE", True, True),
    ("cfo", "Sam Fiscal", "FINANCE", True, True),
]
TIE_OUT_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("fin2", "Pilar Ledger", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]


def _certification_eve(api):
    """A cycle in CERTIFICATION_OPEN with both quarterly instruments signed and
    every filing-readiness gate sitting on its narrowest satisfying value."""
    committee = build_committee(
        api,
        seats=READINESS_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Readiness Charter",
    )
    scenario = scenario_review_open(
        api, committee, calendar=("CLOSE", "REVIEW", "FILING")
    )
    scenario.full_coverage(member_key="fin", scope_area="REVENUE")
    scenario.approved_periodic_filing()
    scenario.run("REVIEW")
    scenario.cert("ceo", "CEO_302")
    scenario.cert("cfo", "CFO_302")
    scenario.open_certification()
    scenario.sign("CEO_302", "ceo")
    scenario.sign("CFO_302", "cfo")
    return scenario


def test_the_dashboard_reports_an_empty_blocking_list_and_the_declaration_then_lands(api):
    """Every numeric gate is parked on the value that only just satisfies it — one
    business day of slack, coverage at exactly 100.00, no open event and no
    unresolved weight — so the dashboard's blocking list is empty and its
    eligibility flag is true. The certification milestone is absent yet does not
    appear as missing, because no transition of this cycle ever requires one, and
    the declaration taken immediately afterwards succeeds.

    PRD 3.2: "`missing_milestone_kinds` lists only those milestone kinds that some remaining workflow transition of this cycle requires and that the cycle does not have, ordered `CLOSE`, `REVIEW`, `CERTIFICATION`, `FILING`; because no transition ever requires a `CERTIFICATION` milestone, that kind never appears in the list."

    PRD 3.2: "`filing_ready_eligible` is true if and only if `blocking_error_ids` is empty."

    PRD 3.8: "Every officer certification its `form_type` requires must be `SIGNED` — a quarterly cycle requires `CEO_302` and `CFO_302`, an annual cycle additionally requires `CEO_906` and `CFO_906` — else `ERR_CERTIFICATIONS_INCOMPLETE`."

    PRD 3.8: "`min_slack_days_business` — the business-day variant, never the calendar one — must be at least 1, else `ERR_MILESTONE_SLACK_EXHAUSTED`."

    Design: Corner/validations/fully_satisfied_cycle_reports_an_empty_blocking_set_and_declares_filing_ready
    """
    scenario = _certification_eve(api)

    dashboard = readiness(api, scenario.cycle_id)
    assert dashboard["cycle_id"] == scenario.cycle_id
    assert dashboard["cycle_status"] == "CERTIFICATION_OPEN"
    assert dashboard["restatement_stage"] == "NONE"
    assert_instant_equals(dashboard["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    assert_instant_equals(dashboard["internal_target_utc"], "2026-08-05T17:30:00Z")
    assert dashboard["min_slack_days_calendar"] == 1
    assert dashboard["min_slack_days_business"] == 1
    assert_money(dashboard["total_assigned_scope_weight"], 30.00)
    assert_money(dashboard["certification_coverage_pct"], 100.00)
    assert dashboard["open_material_event_count"] == 0
    assert_money(dashboard["unresolved_deficiency_weight"], 0.00)
    assert dashboard["missing_milestone_kinds"] == []
    assert dashboard["unsigned_cert_types"] == []
    assert dashboard["blocking_error_ids"] == []
    assert dashboard["filing_ready_eligible"] is True

    declared = scenario.declare_filing_ready()
    assert declared["status"] == "FILING_READY"
    assert declared["restatement_stage"] == "NONE"


def test_the_safe_harbor_gate_keys_on_the_document_type_and_not_on_the_flag(api):
    """Two documents omit the legend flag and only one of them is refused: the
    earnings release cannot be approved without it, while the periodic filing —
    carrying the identical false flag — is approved, and a second earnings release
    that supplies the flag is approved too. Creating that replacement retires the
    refused draft, and the periodic filing of the other type is left alone.

    PRD 3.5: "A document whose `doc_type` is `EARNINGS_RELEASE` or `CALL_SCRIPT` cannot be approved while its `safe_harbor_present` flag is false, and a `CALL_SCRIPT` that carries any question item with `requires_safe_harbor` true likewise cannot be approved unless `safe_harbor_present` is true."

    PRD 3.5: "A `PERIODIC_FILING` or a `CURRENT_REPORT` is not subject to this rule at all."

    PRD 3.5: "When a new document is created with the same `cycle_id` and the same `doc_type` as an existing document of that cycle, the existing one moves to `SUPERSEDED` — from `DRAFT`, `IN_REVIEW`, `CHANGES_REQUESTED` or `APPROVED` alike — and its `version` increments."

    Design: Corner/validations/safe_harbor_gate_fires_on_an_earnings_release_but_not_on_a_periodic_filing_with_the_same_flag
    """
    committee = build_committee(
        api,
        seats=GATE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Safe Harbour Charter",
    )
    scenario = scenario_close_open(api, committee)

    release = create_document(
        api, committee, scenario.cycle_id, "EARNINGS_RELEASE", "fin",
        title="Q2 2026 Earnings Release",
    )
    assert release["safe_harbor_present"] is False
    add_matching_tie_out(api, committee, release["id"], line_label="Net revenue")
    in_review = submit_for_review(api, committee, release["id"], "fin")
    assert in_review["tie_out_status"] == "PASSED"
    assert in_review["measure_gate_status"] == "NO_MEASURES"

    validate_error(
        api.transition_document(
            release["id"], action_payload("APPROVE"), committee.counsel("legal")
        ),
        "ERR_SAFE_HARBOR_MISSING",
        409,
    )
    assert refresh_document(api, committee, release["id"])["status"] == "IN_REVIEW"

    periodic = create_document(
        api, committee, scenario.cycle_id, "PERIODIC_FILING", "fin",
        title="Form 10-Q FY2026-Q2",
    )
    assert periodic["safe_harbor_present"] is False
    add_matching_tie_out(api, committee, periodic["id"], line_label="Total revenue")
    submit_for_review(api, committee, periodic["id"], "fin")
    assert approve_document(api, committee, periodic["id"], "legal")["status"] == (
        "APPROVED"
    )

    replacement = create_document(
        api, committee, scenario.cycle_id, "EARNINGS_RELEASE", "fin",
        title="Q2 2026 Earnings Release rev 2",
        safe_harbor_present=True,
    )
    assert replacement["safe_harbor_present"] is True
    assert refresh_document(api, committee, release["id"])["status"] == "SUPERSEDED"

    add_matching_tie_out(
        api, committee, replacement["id"], line_label="Net revenue as revised"
    )
    submit_for_review(api, committee, replacement["id"], "fin")
    assert approve_document(api, committee, replacement["id"], "legal")["status"] == (
        "APPROVED"
    )
    assert refresh_document(api, committee, periodic["id"])["status"] == "APPROVED"


def _assign(api, committee, cycle_id, scope_area, due_utc):
    return api.create_subcert(
        subcert_payload(cycle_id, committee.mid("fin"), scope_area, due_utc),
        committee.chair("legal"),
    )


def test_the_due_instant_admits_the_internal_target_and_refuses_one_second_past_it(api):
    """The admissible window closes on the internal target rather than on the
    statutory deadline and opens strictly after the clock, and both ends are probed
    from both sides: the target instant itself is accepted while one second past it
    is refused, and the clock instant itself is refused while one second after it
    is accepted. Only the two accepted rows carry weight, and neither is submitted,
    so coverage stays at nothing.

    PRD 3.4: "The `due_utc` must fall strictly after the current logical clock — a deadline that has already passed cannot be assigned — and at or before the cycle's `internal_target_utc`, so that submissions land before the committee's own buffer runs out rather than merely before the statutory deadline."

    PRD 3.4: "A `due_utc` outside that window is rejected with `ERR_SUBCERT_DUE_OUT_OF_WINDOW`."

    PRD 3.4: "The base weight comes from the scope area: 30 for `REVENUE`, 25 for `LEGAL_CONTINGENCY`, 20 for `OPERATIONS`, 15 for `IR_COMMUNICATIONS` and 10 for `IT_CONTROLS`."

    Design: Corner/validations/subcertification_due_instant_admits_the_internal_target_and_rejects_one_second_past_it
    """
    committee = build_committee(
        api,
        seats=GATE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Due Window Charter",
    )
    scenario = scenario_close_open(api, committee)
    assert_instant_equals(scenario.cycle["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    assert_instant_equals(scenario.cycle["internal_target_utc"], "2026-08-05T17:30:00Z")

    on_target = validate_success(
        _assign(api, committee, scenario.cycle_id, "REVENUE", "2026-08-05T17:30:00Z"), 201
    )
    assert on_target["status"] == "PENDING"
    assert_money(on_target["scope_weight"], 30.00)

    validate_error(
        _assign(api, committee, scenario.cycle_id, "OPERATIONS", "2026-08-05T17:30:01Z"),
        "ERR_SUBCERT_DUE_OUT_OF_WINDOW",
        409,
    )
    validate_error(
        _assign(api, committee, scenario.cycle_id, "IT_CONTROLS", "2026-08-01T00:00:00Z"),
        "ERR_SUBCERT_DUE_OUT_OF_WINDOW",
        409,
    )

    one_second_in = validate_success(
        _assign(
            api, committee, scenario.cycle_id, "LEGAL_CONTINGENCY",
            "2026-08-01T00:00:01Z",
        ),
        201,
    )
    assert one_second_in["status"] == "PENDING"
    assert_money(one_second_in["scope_weight"], 25.00)

    after = refresh_cycle(api, scenario.cycle_id)
    assert_money(after["total_assigned_scope_weight"], 55.00)
    assert_money(after["certification_coverage_pct"], 0.00)


def _one_line_document(api):
    """A periodic filing in IN_REVIEW carrying a single line 24 basis points out
    against a tolerance of 25, so the schedule passes with a point to spare."""
    committee = build_committee(
        api,
        seats=TIE_OUT_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Whole Set Charter",
    )
    scenario = scenario_close_open(api, committee)
    document = create_document(
        api, committee, scenario.cycle_id, "PERIODIC_FILING", "fin",
        title="Form 10-Q FY2026-Q2", safe_harbor_present=True,
    )
    first = add_tie_out(
        api, committee, document["id"], "Total revenue", 5012000, 5000000,
        tolerance_bp=25,
    )
    return committee, document, first


def _item(api, item_id):
    return validate_success(api.get_tie_out_item(item_id, admin_headers()))


def test_a_line_inside_its_own_tolerance_still_blocks_the_document_through_the_tier(api):
    """The new line is comfortably inside its own 60-point tolerance, yet it lifts
    the document total from 24 to 64 points, which drops the tier and floors the
    untouched first line's effective tolerance from 25 to 18 — flipping that line to
    a variance and failing the schedule, so the approval is refused. Waiving the
    first line takes it out of the input set entirely, the total relaxes back to 40,
    the tier returns and the identical approval succeeds.

    PRD 3.6: "The following evaluation order breaks the loop and is normative — no other order is permitted — and the whole sequence is re-run over the document's entire non-waived item set on every item creation and on every review, not merely against the row that was touched."

    PRD 3.6: "Waived rows are outside the input set entirely: they contribute nothing to the total and keep their own `raw_variance_bp` and `effective_tolerance_bp` frozen at whatever they held when they were waived."

    PRD 3.6: "A total above 50 but at most 200 basis points earns the medium tier and a multiplier of 0.75."

    PRD 3.5: "Fifth, the **tie-out gate**: `tie_out_status` must be exactly `PASSED`, and both `NOT_STARTED` and `FAILED` block with `ERR_TIE_OUT_NOT_PASSED`."

    Design: Corner/validations/approve_gate_reads_the_whole_set_recompute_so_a_matching_new_line_can_still_block_the_document
    """
    committee, document, first = _one_line_document(api)
    assert first["raw_variance_bp"] == 24
    assert first["effective_tolerance_bp"] == 25
    assert first["status"] == "MATCHED"

    passing = submit_for_review(api, committee, document["id"], "fin")
    assert passing["tie_out_status"] == "PASSED"
    assert passing["tie_out_total_variance_bp"] == 24
    assert_money(passing["tie_out_tier_multiplier"], 1.00)

    second = add_tie_out(
        api, committee, document["id"], "Operating expenses", 2008000, 2000000,
        tolerance_bp=60,
    )
    assert second["raw_variance_bp"] == 40
    assert second["effective_tolerance_bp"] == 45
    assert second["status"] == "MATCHED"

    retightened = _item(api, first["id"])
    assert retightened["effective_tolerance_bp"] == 18
    assert retightened["status"] == "VARIANCE"

    failing = refresh_document(api, committee, document["id"])
    assert failing["tie_out_status"] == "FAILED"
    assert failing["tie_out_total_variance_bp"] == 64
    assert_money(failing["tie_out_tier_multiplier"], 0.75)

    validate_error(
        api.transition_document(
            document["id"], action_payload("APPROVE"), committee.counsel("legal")
        ),
        "ERR_TIE_OUT_NOT_PASSED",
        409,
    )

    waived = review_tie_out(api, committee, first["id"], "fin2", "WAIVE")
    assert waived["status"] == "WAIVED"
    assert waived["review_decision"] == "WAIVE"

    relaxed = refresh_document(api, committee, document["id"])
    assert relaxed["tie_out_status"] == "PASSED"
    assert relaxed["tie_out_total_variance_bp"] == 40
    assert_money(relaxed["tie_out_tier_multiplier"], 1.00)

    restored = _item(api, second["id"])
    assert restored["effective_tolerance_bp"] == 60
    assert restored["status"] == "MATCHED"

    assert approve_document(api, committee, document["id"], "legal")["status"] == (
        "APPROVED"
    )


SUCCESSOR_SEATS = [
    ("finb", "Tess Successor", "FINANCE", False, True),
    ("finb2", "Uri Successor", "FINANCE", False, True),
]


def test_a_cycle_transition_reads_its_pinned_charter_in_both_directions(api):
    """The same charter is probed on both sides of adoption and then past it: while
    it is a draft no cycle may be created against it, once adopted both the creation
    and the opening transition go through, and once it has been superseded the very
    next transition is refused — even though the cycle itself was never touched and
    its close window is complete. Supersession leaves the cycle pointing at the
    outgoing charter, which is precisely why the refusal happens.

    PRD 3.2: "The pinned charter must already be in `ADOPTED` status, both at creation and at every subsequent cycle workflow transition; a charter still in `DRAFT`, or one that has since been superseded, causes `ERR_CHARTER_NOT_ADOPTED`."

    PRD 3.1: "On success the outgoing charter's `superseded_by_charter_id` is set to the successor's identifier, forming a successor edge that can be walked in either direction, and every `ACTIVE` or `RECUSED` member of the superseded charter is moved to `VACATED`."

    PRD 3.1: "What supersession explicitly does **not** do is re-point the charter reference on any reporting cycle: a cycle stays pinned to the charter version it was created against, for the whole of its life."

    Design: Corner/validations/cycle_transition_reads_its_pinned_charter_so_superseding_that_charter_blocks_the_next_step
    """
    outgoing = build_committee(
        api,
        seats=GATE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Q2 Disclosure Committee Charter",
        adopt=False,
    )
    successor = build_committee(
        api,
        seats=SUCCESSOR_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE"],
        name="Q3 Disclosure Committee Charter",
        version_label="2026.2",
        chair_key="finb",
    )
    assert outgoing.charter["status"] == "DRAFT"
    assert successor.charter["status"] == "ADOPTED"

    validate_error(
        api.create_cycle(cycle_payload(outgoing.id), admin_headers()),
        "ERR_CHARTER_NOT_ADOPTED",
        409,
    )

    adopted = outgoing.adopt("legal")
    assert adopted["status"] == "ADOPTED"

    cycle = build_cycle(api, outgoing)
    assert cycle["charter_id"] == outgoing.id
    close = add_milestone(
        api, outgoing, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    assert open_close(api, outgoing, cycle["id"])["status"] == "CLOSE_OPEN"
    start_milestone(api, outgoing, close["id"])
    assert complete_milestone(api, outgoing, close["id"])["status"] == "COMPLETE"

    retired = outgoing.supersede(successor.id, chair_key="legal")
    assert retired["status"] == "SUPERSEDED"
    assert retired["superseded_by_charter_id"] == successor.id

    untouched = refresh_cycle(api, cycle["id"])
    assert untouched["charter_id"] == outgoing.id
    assert untouched["status"] == "CLOSE_OPEN"

    validate_error(
        api.transition_cycle(
            cycle["id"], action_payload("OPEN_REVIEW"), outgoing.controller("fin")
        ),
        "ERR_CHARTER_NOT_ADOPTED",
        409,
    )
