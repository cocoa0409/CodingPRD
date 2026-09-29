"""Codes that are easy to collapse into one another, kept apart.

Each not-found variant is raised from its own path segment, the pagination window
is probed from both sides of both bounds, the conditional field rules are each
paired with the call that succeeds once the missing piece is supplied, and the
hardest gates of the filing ladder are reached one rejection at a time.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_money
from test_helpers.factories import (
    action_payload,
    adjusted_measure_payload,
    charter_payload,
    filing_payload,
    milestone_payload,
    reconcile_payload,
    subcert_payload,
)
from test_helpers.fixtures import (
    add_milestone,
    add_tie_out,
    approve_document,
    assess_correction,
    assign_subcert,
    build_committee,
    build_cycle,
    complete_milestone,
    create_document,
    deficiencies_of,
    log_material_event,
    mitigate_deficiency,
    open_certification,
    open_close,
    open_correction,
    open_review,
    readiness,
    refresh_cycle,
    refresh_document,
    register_cert,
    sign_cert,
    start_milestone,
    submit_filing,
    submit_for_review,
    submit_subcert,
)
from test_helpers.test_users import admin_headers

PROBE_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
NO_MILESTONE = "00000000-0000-4000-8000-000000000101"
NO_OFFICER_CERT = "00000000-0000-4000-8000-000000000102"
NO_TIE_OUT_ITEM = "00000000-0000-4000-8000-000000000103"
NO_MEASURE = "00000000-0000-4000-8000-000000000104"
NO_QA_ITEM = "00000000-0000-4000-8000-000000000105"
NO_EVENT = "00000000-0000-4000-8000-000000000106"
NO_CORRECTION = "00000000-0000-4000-8000-000000000107"
NO_DEFICIENCY = "00000000-0000-4000-8000-000000000108"


def _probe_committee(api):
    """Two usable credentials and nothing else — none of the probes below reaches
    a state check, so the charter is left in DRAFT."""
    return build_committee(
        api,
        seats=PROBE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE"],
        name="Probe Charter",
        adopt=False,
    )


def test_each_missing_child_row_reports_its_own_not_found_variant(api):
    """Five probes against five kinds of missing row, three of them mutations
    because no by-id read is declared for those kinds, each answering with the
    404 variant that belongs to the failing segment rather than one generic code.

    PRD 2.7: "The code emitted is the not-found variant belonging to the failing segment: `ERR_CHARTER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_SUBCERT_NOT_FOUND`, `ERR_OFFICER_CERT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_TIE_OUT_ITEM_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`, `ERR_QA_ITEM_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND` or `ERR_DEFICIENCY_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/every_remaining_path_parameter_reports_its_own_not_found_code
    """
    committee = _probe_committee(api)

    validate_error(
        api.transition_milestone(
            NO_MILESTONE, action_payload("START"), committee.controller("fin")
        ),
        "ERR_MILESTONE_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_officer_cert(NO_OFFICER_CERT, admin_headers()),
        "ERR_OFFICER_CERT_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_tie_out_item(NO_TIE_OUT_ITEM, admin_headers()),
        "ERR_TIE_OUT_ITEM_NOT_FOUND",
        404,
    )
    validate_error(
        api.reconcile_adjusted_measure(
            NO_MEASURE, reconcile_payload(), committee.controller("fin")
        ),
        "ERR_MEASURE_NOT_FOUND",
        404,
    )
    validate_error(
        api.clear_qa_item(
            NO_QA_ITEM,
            {"clearance_note": "Counsel cleared the wording."},
            committee.counsel("legal"),
        ),
        "ERR_QA_ITEM_NOT_FOUND",
        404,
    )


def test_the_remediation_chain_reports_its_own_three_not_found_variants(api):
    """The same missing correction identifier answers with one code from a by-id
    read and from a nested list read, while the deficiency below it has a code of
    its own; the mitigation probe carries a well-formed note, so nothing but the
    missing row can explain the refusal.

    PRD 2.7: "Nested paths are resolved strictly left to right."

    PRD 2.7: "The code emitted is the not-found variant belonging to the failing segment: `ERR_CHARTER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_SUBCERT_NOT_FOUND`, `ERR_OFFICER_CERT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_TIE_OUT_ITEM_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`, `ERR_QA_ITEM_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND` or `ERR_DEFICIENCY_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/every_remaining_path_parameter_reports_its_own_not_found_code
    """
    _probe_committee(api)

    validate_error(
        api.get_material_event(NO_EVENT, admin_headers()), "ERR_EVENT_NOT_FOUND", 404
    )
    validate_error(
        api.get_correction(NO_CORRECTION, admin_headers()),
        "ERR_CORRECTION_NOT_FOUND",
        404,
    )
    validate_error(
        api.list_control_deficiencies(NO_CORRECTION, admin_headers(), limit=10, offset=0),
        "ERR_CORRECTION_NOT_FOUND",
        404,
    )
    validate_error(
        api.mitigate_control_deficiency(
            NO_DEFICIENCY,
            {"remediation_note": "Control redesigned and retested."},
            admin_headers(),
        ),
        "ERR_DEFICIENCY_NOT_FOUND",
        404,
    )


CHARTER_NAMES = ["Charter One", "Charter Two", "Charter Three"]


def _three_charters(api):
    """Three charters, so a limited page is genuinely shorter than the
    collection."""
    rows = []
    for index, name in enumerate(CHARTER_NAMES, start=1):
        rows.append(
            validate_success(
                api.create_charter(
                    charter_payload(
                        name=name,
                        version_label="2026.%d" % index,
                        min_quorum_count=1,
                        required_functions=["FINANCE"],
                    ),
                    admin_headers(),
                ),
                201,
            )
        )
    return rows


def test_both_pagination_bounds_are_refused_from_outside(api):
    """Zero is one below the minimum, 201 one above the maximum and -1 one below
    the offset floor, so all three are refused with the pagination code and none
    of them is answered with an empty page.

    PRD 2.3: "A `limit` outside the inclusive range 1 through 200, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/errors/pagination_bounds_reject_zero_and_two_hundred_one_while_admitting_one_and_two_hundred
    """
    _three_charters(api)

    validate_error(
        api.list_charters(admin_headers(), limit=0, offset=0),
        "ERR_INVALID_PAGINATION",
        422,
    )
    validate_error(
        api.list_charters(admin_headers(), limit=201, offset=0),
        "ERR_INVALID_PAGINATION",
        422,
    )
    validate_error(
        api.list_charters(admin_headers(), limit=10, offset=-1),
        "ERR_INVALID_PAGINATION",
        422,
    )


def test_both_pagination_bounds_are_admitted_from_inside_and_the_defaults_apply(api):
    """A limit of 1 and a limit of 200 both sit inside the inclusive window, so
    the maximum is not the default in disguise; `has_more` distinguishes the two
    pages, and the argument-free call answers with the declared defaults.

    PRD 2.3: "`limit` is an integer with a default of 10, a minimum of 1 and a maximum of 200."

    PRD 2.3: "`total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true exactly when rows remain after the current window."

    Design: Corner/errors/pagination_bounds_reject_zero_and_two_hundred_one_while_admitting_one_and_two_hundred
    """
    _three_charters(api)

    single, single_meta = validate_paginated(
        api.list_charters(admin_headers(), limit=1, offset=0)
    )
    assert len(single) == 1
    assert single_meta["limit"] == 1
    assert single_meta["offset"] == 0
    assert single_meta["total_count"] == 3
    assert single_meta["has_more"] is True

    whole, whole_meta = validate_paginated(
        api.list_charters(admin_headers(), limit=200, offset=0)
    )
    assert len(whole) == 3
    assert whole_meta["limit"] == 200
    assert whole_meta["total_count"] == 3
    assert whole_meta["has_more"] is False

    default_rows, default_meta = validate_paginated(api.list_charters(admin_headers()))
    assert len(default_rows) == 3
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert default_meta["total_count"] == 3
    assert default_meta["has_more"] is False


SHAPE_DUE_UTC = "2026-08-04T17:00:00Z"
GOOD_BRIDGE = [{"label": "Restructuring charge", "amount": 200000.0}]
CHANGE_NOTE = "Reconcile the adjusted measure to the GAAP line."
EXCEPTION_NOTE = "Cut-off testing incomplete for two subsidiaries."


def _shape_fixture(api):
    """A cycle in CLOSE_OPEN carrying a PENDING sub-certification, a draft
    periodic filing and an unassessed event, so each conditional field rule can be
    probed against a row that is otherwise ready to move."""
    committee = build_committee(
        api,
        seats=PROBE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Shape Probe Charter",
    )
    cycle = build_cycle(api, committee)
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    request = assign_subcert(
        api, committee, cycle["id"], "fin", "REVENUE", due_utc=SHAPE_DUE_UTC
    )
    document = create_document(
        api, committee, cycle["id"], "PERIODIC_FILING", "fin",
        title="Form 10-Q FY2026-Q2",
    )
    event = log_material_event(api, committee, cycle["id"], magnitude_amount=200000)
    assert_money(event["severity_score"], 2.00)
    return committee, cycle, request, document, event


def test_a_malformed_bridge_and_an_undeclared_milestone_kind_are_both_shape_errors(api):
    """A bridging item missing its `amount`, and a bridge sent as a bare string
    rather than a list, are both refused on shape; the same code covers a milestone
    kind outside its declared domain, which is neither a missing-milestone error
    nor a 404; and the well-formed bridge is then accepted.

    PRD 2.7: "Request-shape validation follows: the body must parse, every required input field must be present, every enum-typed value must be a member of its declared domain, numeric fields must be numbers and must respect the non-negativity their descriptions state, ISO 8601 instants must parse, and `reconciliation_items` must be a list of objects each carrying a `label` string and an `amount` number."

    PRD 3.7: "A newly attached measure is persisted in `status` `DRAFT` with `reconciliation_sum`, `reconciliation_gap` and `prominence_ok` all null, and — precisely because it is `DRAFT` and therefore not yet reconciled — attaching it immediately drives the owning document's `measure_gate_status` to `BLOCKED_RECONCILIATION`."

    Design: Corner/errors/conditional_field_requirements_are_enforced_per_action_and_the_same_call_lands_once_supplied
    """
    committee, cycle, _request, document, _event = _shape_fixture(api)

    validate_error(
        api.create_adjusted_measure(
            document["id"],
            adjusted_measure_payload(
                "Adjusted EBITDA", 4300000.0, 4100000.0,
                [{"label": "Restructuring charge"}], 2, 1,
            ),
            committee.controller("fin"),
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api.create_adjusted_measure(
            document["id"],
            {
                "measure_label": "Adjusted EBITDA",
                "adjusted_value": 4300000.0,
                "comparable_gaap_value": 4100000.0,
                "reconciliation_items": "Restructuring charge 200000",
                "adjusted_prominence_index": 2,
                "gaap_prominence_index": 1,
            },
            committee.controller("fin"),
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api.create_milestone(
            cycle["id"],
            milestone_payload(
                "SIGNOFF", "2026-08-04T00:00:00Z", "2026-08-04T06:00:00Z"
            ),
            committee.controller("fin"),
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    measure = validate_success(
        api.create_adjusted_measure(
            document["id"],
            adjusted_measure_payload(
                "Adjusted EBITDA", 4300000.0, 4100000.0, GOOD_BRIDGE, 2, 1
            ),
            committee.controller("fin"),
        ),
        201,
    )
    assert measure["status"] == "DRAFT"
    assert measure["reconciliation_sum"] is None
    assert measure["reconciliation_gap"] is None
    assert measure["prominence_ok"] is None
    assert refresh_document(api, committee, document["id"])["measure_gate_status"] == (
        "BLOCKED_RECONCILIATION"
    )


def test_an_exception_needs_its_note_and_the_severity_must_be_in_the_declared_domain(api):
    """A submission that notes an exception is refused while the note is absent,
    and refused again for a severity outside the declared domain even though the
    note is now present; supplying both an in-domain severity and the note lands the
    row in EXCEPTION_NOTED, and neither refusal moved it beforehand.

    PRD 3.4: "It requires a non-empty `exception_note`, and its absence is `ERR_INVALID_REQUEST`."

    PRD 3.4: "A submission that notes an exception — `exception_severity` of `LOW`, `MEDIUM` or `HIGH` — moves the request from `PENDING` to `EXCEPTION_NOTED` instead."

    Design: Corner/errors/conditional_field_requirements_are_enforced_per_action_and_the_same_call_lands_once_supplied
    """
    committee, _cycle, request, _document, _event = _shape_fixture(api)
    assert request["status"] == "PENDING"

    validate_error(
        api.transition_subcert(
            request["id"],
            action_payload("SUBMIT", exception_severity="HIGH"),
            committee.leader("fin"),
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    assert validate_success(api.get_subcert(request["id"], admin_headers()))["status"] == (
        "PENDING"
    )

    validate_error(
        api.transition_subcert(
            request["id"],
            action_payload(
                "SUBMIT", exception_severity="SEVERE", exception_note=EXCEPTION_NOTE
            ),
            committee.leader("fin"),
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    still_pending = validate_success(api.get_subcert(request["id"], admin_headers()))
    assert still_pending["status"] == "PENDING"
    assert still_pending["exception_severity"] == "NONE"
    assert still_pending["exception_note"] is None

    noted = submit_subcert(
        api, committee, request["id"], "fin",
        exception_severity="HIGH", exception_note=EXCEPTION_NOTE,
    )
    assert noted["status"] == "EXCEPTION_NOTED"
    assert noted["exception_severity"] == "HIGH"
    assert noted["exception_note"] == EXCEPTION_NOTE


def test_a_change_request_needs_its_note_and_an_assessment_needs_its_determination(api):
    """Two more conditionally-required fields on two different resources: without
    the note the change request is refused and the document keeps revision round
    zero, and without the determination the assessment is refused and the event
    stays unassessed; each call then lands once the field is supplied.

    PRD 3.5: "Requesting changes moves it from `IN_REVIEW` to `CHANGES_REQUESTED`, is open to `Controller` and `LegalCounsel` only, and requires a non-empty `change_note` — its absence is `ERR_INVALID_REQUEST`."

    PRD 2.7: "The same code covers the conditionally-required fields: a missing `exception_note` on a submission that notes an exception, a missing `change_note` on a change request, and a missing `determination` on an event assessment."

    Design: Corner/errors/conditional_field_requirements_are_enforced_per_action_and_the_same_call_lands_once_supplied
    """
    committee, _cycle, _request, document, event = _shape_fixture(api)

    in_review = submit_for_review(api, committee, document["id"])
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["revision_round"] == 0

    validate_error(
        api.transition_document(
            document["id"], action_payload("REQUEST_CHANGES"), committee.counsel("legal")
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    untouched = refresh_document(api, committee, document["id"])
    assert untouched["status"] == "IN_REVIEW"
    assert untouched["revision_round"] == 0

    sent_back = validate_success(
        api.transition_document(
            document["id"],
            action_payload("REQUEST_CHANGES", change_note=CHANGE_NOTE),
            committee.counsel("legal"),
        )
    )
    assert sent_back["status"] == "CHANGES_REQUESTED"
    assert sent_back["revision_round"] == 1
    assert sent_back["change_note"] == CHANGE_NOTE

    validate_error(
        api.transition_material_event(
            event["id"], action_payload("ASSESS"), committee.counsel("legal")
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    assert validate_success(api.get_material_event(event["id"], admin_headers()))[
        "assessment_status"
    ] == "UNASSESSED"

    assessed = validate_success(
        api.transition_material_event(
            event["id"],
            action_payload("ASSESS", determination="NOT_REPORTABLE"),
            committee.counsel("legal"),
        )
    )
    assert assessed["assessment_status"] == "NOT_REPORTABLE"
    assert assessed["current_report_deadline_utc"] is None


SOD_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
]
SOD_CHANGE_NOTE = "Add the revenue tie-out schedule before approval."
AUTHOR_CHANGE_NOTE = "I would like to redraft my own section."


def _sod_fixture(api):
    """A cycle in CLOSE_OPEN whose officer already holds a registered CEO_302
    slot, so the officer sub-certification rule is live from the start."""
    committee = build_committee(
        api,
        seats=SOD_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="SOD Probe Charter",
    )
    cycle = build_cycle(api, committee)
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    cert = register_cert(api, cycle["id"], committee, "ceo", "CEO_302")
    return committee, cycle, cert


def test_an_officer_holding_a_certification_slot_cannot_be_handed_a_subcertification(api):
    """The slot is still only BLOCKED, and that is already enough to bar its holder
    from the evidence he would rely on; the identical assignment to the
    non-officer member is created, so the refusal is about the officer and not
    about the scope area.

    PRD 2.10: "A certifying officer must not sub-certify to itself: a committee member who already holds a non-`VOID` officer certification on a cycle cannot also be assigned a sub-certification on that same cycle, and the assignment is rejected with `ERR_SOD_OFFICER_SUBCERT`."

    PRD 3.4: "A new request is persisted with `status` `PENDING`, `exception_severity` `NONE`, a null `exception_note` and a null `submitted_utc`, so its initial weight is simply its base possibly lifted by the officer factor."

    Design: Corner/errors/both_segregation_of_duties_gates_fire_and_a_second_actor_gets_past_them
    """
    committee, cycle, cert = _sod_fixture(api)
    assert cert["status"] == "BLOCKED"

    validate_error(
        api.create_subcert(
            subcert_payload(
                cycle["id"], committee.mid("ceo"), "IT_CONTROLS", SHAPE_DUE_UTC
            ),
            committee.chair("legal"),
        ),
        "ERR_SOD_OFFICER_SUBCERT",
        409,
    )

    allowed = assign_subcert(
        api, committee, cycle["id"], "fin", "IT_CONTROLS", due_utc=SHAPE_DUE_UTC
    )
    assert allowed["status"] == "PENDING"
    assert allowed["exception_severity"] == "NONE"
    assert allowed["submitted_utc"] is None
    assert_money(allowed["scope_weight"], 10.00)


def test_the_author_may_neither_approve_nor_reject_and_the_next_actor_meets_the_next_gate(api):
    """Both review verdicts are guarded, so the author cannot send his own draft
    back either; a different reviewer clears the separation gate and immediately
    meets the tie-out gate instead, and the same change request from that reviewer
    succeeds and lifts the revision round.

    PRD 2.10: "A document must be approved, or sent back for changes, by someone other than its author: the acting `X-User-ID` on an approve or request-changes action must differ from that document's `author_member_id`, or the action is rejected with `ERR_SOD_SELF_APPROVAL`."

    PRD 3.5: "Fifth, the **tie-out gate**: `tie_out_status` must be exactly `PASSED`, and both `NOT_STARTED` and `FAILED` block with `ERR_TIE_OUT_NOT_PASSED`."

    Design: Corner/errors/both_segregation_of_duties_gates_fire_and_a_second_actor_gets_past_them
    """
    committee, cycle, _cert = _sod_fixture(api)
    document = create_document(
        api, committee, cycle["id"], "PERIODIC_FILING", "legal",
        title="Form 10-Q FY2026-Q2", role="counsel",
    )
    in_review = validate_success(
        api.transition_document(
            document["id"], action_payload("SUBMIT_REVIEW"), committee.counsel("legal")
        )
    )
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["tie_out_status"] == "NOT_STARTED"

    validate_error(
        api.transition_document(
            document["id"], action_payload("APPROVE"), committee.counsel("legal")
        ),
        "ERR_SOD_SELF_APPROVAL",
        409,
    )
    validate_error(
        api.transition_document(
            document["id"],
            action_payload("REQUEST_CHANGES", change_note=AUTHOR_CHANGE_NOTE),
            committee.counsel("legal"),
        ),
        "ERR_SOD_SELF_APPROVAL",
        409,
    )
    validate_error(
        api.transition_document(
            document["id"], action_payload("APPROVE"), committee.controller("fin")
        ),
        "ERR_TIE_OUT_NOT_PASSED",
        409,
    )
    after_refusals = refresh_document(api, committee, document["id"])
    assert after_refusals["status"] == "IN_REVIEW"
    assert after_refusals["revision_round"] == 0

    sent_back = validate_success(
        api.transition_document(
            document["id"],
            action_payload("REQUEST_CHANGES", change_note=SOD_CHANGE_NOTE),
            committee.controller("fin"),
        )
    )
    assert sent_back["status"] == "CHANGES_REQUESTED"
    assert sent_back["revision_round"] == 1
    assert sent_back["change_note"] == SOD_CHANGE_NOTE


def _bare_cycle(api):
    """An adopted committee and a cycle in PLANNING with no milestone at all."""
    committee = build_committee(
        api,
        seats=PROBE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Gate Probe Charter",
    )
    cycle = build_cycle(api, committee)
    assert cycle["status"] == "PLANNING"
    return committee, cycle


def _cycle_action(api, committee, cycle_id, action):
    return api.transition_cycle(
        cycle_id, action_payload(action), committee.controller("fin")
    )


def test_existence_and_status_of_the_close_window_report_two_different_codes(api):
    """The missing window is an existence failure and the readiness read agrees with
    it; once the window exists the same transition succeeds, and the next
    transition fails on status instead — twice, because starting the window is not
    completing it and only COMPLETE clears that gate.

    PRD 3.3: "Opening the close moves the cycle from `PLANNING` to `CLOSE_OPEN` and requires that at least one `CLOSE` milestone exist on the cycle, otherwise `ERR_MILESTONE_MISSING`."

    PRD 3.3: "Opening review moves it from `CLOSE_OPEN` to `REVIEW_OPEN` and requires that every `CLOSE` milestone on the cycle be `COMPLETE`, otherwise `ERR_MILESTONE_INCOMPLETE`; the existence of a `CLOSE` milestone is re-checked here too, though it can only fail if the close was never opened, so that clause is defensive."

    Design: Corner/errors/milestone_prerequisite_gates_and_subcertification_uniqueness_each_report_their_own_code
    """
    committee, cycle = _bare_cycle(api)

    validate_error(
        _cycle_action(api, committee, cycle["id"], "OPEN_CLOSE"),
        "ERR_MILESTONE_MISSING",
        409,
    )
    assert readiness(api, cycle["id"])["missing_milestone_kinds"] == [
        "CLOSE",
        "REVIEW",
        "FILING",
    ]

    window = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    opened = validate_success(_cycle_action(api, committee, cycle["id"], "OPEN_CLOSE"))
    assert opened["status"] == "CLOSE_OPEN"

    validate_error(
        _cycle_action(api, committee, cycle["id"], "OPEN_REVIEW"),
        "ERR_MILESTONE_INCOMPLETE",
        409,
    )

    started = start_milestone(api, committee, window["id"])
    assert started["status"] == "IN_PROGRESS"
    validate_error(
        _cycle_action(api, committee, cycle["id"], "OPEN_REVIEW"),
        "ERR_MILESTONE_INCOMPLETE",
        409,
    )

    finished = complete_milestone(api, committee, window["id"])
    assert finished["status"] == "COMPLETE"
    reviewing = validate_success(_cycle_action(api, committee, cycle["id"], "OPEN_REVIEW"))
    assert reviewing["status"] == "REVIEW_OPEN"


def test_the_missing_review_window_outranks_the_missing_approved_filing(api):
    """Opening certification needs a review window, every review window complete
    and an approved periodic filing; this cycle has none of the three, and the
    refusal names the earliest of them rather than the filing-document code.

    PRD 3.3: "Opening certification moves it from `REVIEW_OPEN` to `CERTIFICATION_OPEN` and requires that at least one `REVIEW` milestone exist — otherwise `ERR_MILESTONE_MISSING` — that every `REVIEW` milestone be `COMPLETE` — otherwise `ERR_MILESTONE_INCOMPLETE` — and that at least one draft document on the cycle with `doc_type` `PERIODIC_FILING` be in `APPROVED` status, otherwise `ERR_FILING_DOCUMENT_INVALID`."

    Design: Corner/errors/milestone_prerequisite_gates_and_subcertification_uniqueness_each_report_their_own_code
    """
    committee, cycle = _bare_cycle(api)
    window = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    start_milestone(api, committee, window["id"])
    complete_milestone(api, committee, window["id"])
    assert open_review(api, committee, cycle["id"])["status"] == "REVIEW_OPEN"

    validate_error(
        _cycle_action(api, committee, cycle["id"], "OPEN_CERTIFICATION"),
        "ERR_MILESTONE_MISSING",
        409,
    )
    assert refresh_cycle(api, cycle["id"])["status"] == "REVIEW_OPEN"


def test_the_uniqueness_key_of_a_subcertification_includes_its_scope_area(api):
    """A second request for the same cycle, member and scope area is refused even
    with a different deadline, while the same member is legitimately given a second
    request under a different scope area.

    PRD 3.4: "There may be at most one non-terminal request for the same combination of cycle, member and `scope_area`, and a second one is rejected with `ERR_DUPLICATE_SUBCERT`."

    Design: Corner/errors/milestone_prerequisite_gates_and_subcertification_uniqueness_each_report_their_own_code
    """
    committee, cycle = _bare_cycle(api)
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])

    first = assign_subcert(
        api, committee, cycle["id"], "fin", "REVENUE", due_utc=SHAPE_DUE_UTC
    )
    assert first["status"] == "PENDING"

    validate_error(
        api.create_subcert(
            subcert_payload(
                cycle["id"], committee.mid("fin"), "REVENUE", "2026-08-04T12:00:00Z"
            ),
            committee.chair("legal"),
        ),
        "ERR_DUPLICATE_SUBCERT",
        409,
    )

    other_scope = assign_subcert(
        api, committee, cycle["id"], "fin", "OPERATIONS", due_utc=SHAPE_DUE_UTC
    )
    assert other_scope["status"] == "PENDING"
    assert_money(other_scope["scope_weight"], 20.00)

    rows, meta = validate_paginated(
        api.list_subcerts(admin_headers(), cycle_id=cycle["id"], limit=10, offset=0)
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2


LADDER_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
    ("cfo", "Sam Fiscal", "FINANCE", True, True),
]
CEO_ATTESTATION = "I certify the Form 10-Q fairly presents results of operations."
CFO_ATTESTATION = "I certify the Form 10-Q fairly presents financial condition."
CORRECTION_DESCRIPTION = "Understated warranty accrual"
REMEDIATION_NOTE = "Warranty accrual model redesigned and retested by internal audit."


def _ladder(api):
    """A cycle carried to CERTIFICATION_OPEN with two FILING windows — one with no
    business-day slack left and one with two days of it — and both quarterly
    instruments registered but unsigned."""
    committee = build_committee(
        api,
        seats=LADDER_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Filing Ladder Charter",
    )
    cycle = build_cycle(api, committee)
    close = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    review = add_milestone(
        api, committee, cycle["id"], "REVIEW",
        "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z",
    )
    tight = add_milestone(
        api, committee, cycle["id"], "FILING",
        "2026-08-10T00:00:00Z", "2026-08-10T12:00:00Z",
    )
    loose = add_milestone(
        api, committee, cycle["id"], "FILING",
        "2026-08-06T12:00:00Z", "2026-08-06T18:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    start_milestone(api, committee, close["id"])
    complete_milestone(api, committee, close["id"])

    request = assign_subcert(
        api, committee, cycle["id"], "fin", "REVENUE", due_utc="2026-08-04T17:00:00Z"
    )
    submit_subcert(api, committee, request["id"], "fin")

    document = create_document(
        api, committee, cycle["id"], "PERIODIC_FILING", "fin",
        title="Form 10-Q FY2026-Q2", safe_harbor_present=True,
    )
    add_tie_out(api, committee, document["id"], "Total revenue", 4120000.0, 4120000.0)
    submit_for_review(api, committee, document["id"], "fin")
    approve_document(api, committee, document["id"], "legal")

    open_review(api, committee, cycle["id"])
    start_milestone(api, committee, review["id"])
    complete_milestone(api, committee, review["id"])

    ceo_cert = register_cert(api, cycle["id"], committee, "ceo", "CEO_302")
    cfo_cert = register_cert(api, cycle["id"], committee, "cfo", "CFO_302")
    opened = open_certification(api, committee, cycle["id"])
    assert opened["status"] == "CERTIFICATION_OPEN"
    return {
        "committee": committee,
        "cycle": cycle,
        "tight": tight,
        "loose": loose,
        "document": document,
        "ceo_cert": ceo_cert,
        "cfo_cert": cfo_cert,
    }


def _declare(api, committee, cycle_id):
    return api.transition_cycle(
        cycle_id, action_payload("DECLARE_FILING_READY"), committee.chair("legal")
    )


def test_the_certification_gate_is_reported_while_the_slack_gate_is_also_failing(api):
    """Both the certification rule and the slack rule fail at this instant, and the
    declaration reports the certification one because it sits earlier in the
    ladder; the dashboard lists both codes in that same order, so its first entry
    is the code the refused declaration returned.

    PRD 3.8: "Every officer certification its `form_type` requires must be `SIGNED` — a quarterly cycle requires `CEO_302` and `CFO_302`, an annual cycle additionally requires `CEO_906` and `CFO_906` — else `ERR_CERTIFICATIONS_INCOMPLETE`."

    PRD 3.2: "`blocking_error_ids` lists, de-duplicated and in ascending order of the rule ladder of §2.11, the distinct error identifiers a filing-readiness declaration would raise at this instant — so its first element is exactly the code the declaration would return."

    Design: Corner/errors/filing_readiness_and_amendment_guards_fire_in_sequence_on_a_single_cycle
    """
    ladder = _ladder(api)
    committee, cycle = ladder["committee"], ladder["cycle"]

    assert ladder["tight"]["slack_business_days"] == 0
    assert ladder["tight"]["slack_calendar_days"] == 0
    assert ladder["loose"]["slack_business_days"] == 2
    assert ladder["loose"]["slack_calendar_days"] == 3

    board = readiness(api, cycle["id"])
    assert board["min_slack_days_business"] == 0
    assert board["unsigned_cert_types"] == ["CEO_302", "CFO_302"]
    assert board["blocking_error_ids"] == [
        "ERR_CERTIFICATIONS_INCOMPLETE",
        "ERR_MILESTONE_SLACK_EXHAUSTED",
    ]
    assert board["filing_ready_eligible"] is False

    validate_error(
        _declare(api, committee, cycle["id"]), "ERR_CERTIFICATIONS_INCOMPLETE", 409
    )
    assert refresh_cycle(api, cycle["id"])["status"] == "CERTIFICATION_OPEN"


def test_the_slack_gate_lifts_only_when_the_tight_window_leaves_the_open_set(api):
    """With both signatures in place the slack rule is the only one left, and it
    stays failed while the tight window is PLANNED and again while it is
    IN_PROGRESS, because the aggregate is taken over exactly those two statuses;
    completing it drops it out and the loose window's two days become the minimum,
    which finally admits the declaration and then the original filing.

    PRD 3.8: "`min_slack_days_business` — the business-day variant, never the calendar one — must be at least 1, else `ERR_MILESTONE_SLACK_EXHAUSTED`."

    PRD 3.3: "At cycle level, `min_slack_days_calendar` and `min_slack_days_business` are the minimum of the corresponding per-milestone value taken over the **open** milestones only — those whose `status` is `PLANNED` or `IN_PROGRESS`."

    Design: Corner/errors/filing_readiness_and_amendment_guards_fire_in_sequence_on_a_single_cycle
    """
    ladder = _ladder(api)
    committee, cycle = ladder["committee"], ladder["cycle"]
    sign_cert(
        api, committee, ladder["ceo_cert"]["id"], "ceo", attestation_text=CEO_ATTESTATION
    )
    sign_cert(
        api, committee, ladder["cfo_cert"]["id"], "cfo", attestation_text=CFO_ATTESTATION
    )

    board = readiness(api, cycle["id"])
    assert board["unsigned_cert_types"] == []
    assert board["blocking_error_ids"] == ["ERR_MILESTONE_SLACK_EXHAUSTED"]
    assert board["min_slack_days_business"] == 0
    assert board["min_slack_days_calendar"] == 0

    validate_error(
        _declare(api, committee, cycle["id"]), "ERR_MILESTONE_SLACK_EXHAUSTED", 409
    )
    started = start_milestone(api, committee, ladder["tight"]["id"])
    assert started["status"] == "IN_PROGRESS"
    validate_error(
        _declare(api, committee, cycle["id"]), "ERR_MILESTONE_SLACK_EXHAUSTED", 409
    )

    finished = complete_milestone(api, committee, ladder["tight"]["id"])
    assert finished["status"] == "COMPLETE"
    recovered = readiness(api, cycle["id"])
    assert recovered["min_slack_days_business"] == 2
    assert recovered["min_slack_days_calendar"] == 3
    assert recovered["blocking_error_ids"] == []
    assert recovered["filing_ready_eligible"] is True

    ready = validate_success(_declare(api, committee, cycle["id"]))
    assert ready["status"] == "FILING_READY"

    filing = submit_filing(api, cycle["id"], ladder["document"]["id"])
    assert filing["accession_label"] == "FORM_10Q-FY2026-Q2-1"
    assert filing["late_flag"] is False
    assert filing["status"] == "SUBMITTED"
    assert refresh_cycle(api, cycle["id"])["status"] == "FILED"


def _filed(api):
    """The same ladder carried through the declaration and the original filing."""
    ladder = _ladder(api)
    committee, cycle = ladder["committee"], ladder["cycle"]
    sign_cert(
        api, committee, ladder["ceo_cert"]["id"], "ceo", attestation_text=CEO_ATTESTATION
    )
    sign_cert(
        api, committee, ladder["cfo_cert"]["id"], "cfo", attestation_text=CFO_ATTESTATION
    )
    start_milestone(api, committee, ladder["tight"]["id"])
    complete_milestone(api, committee, ladder["tight"]["id"])
    assert validate_success(_declare(api, committee, cycle["id"]))["status"] == "FILING_READY"
    ladder["filing"] = submit_filing(api, cycle["id"], ladder["document"]["id"])
    assert ladder["filing"]["accession_label"] == "FORM_10Q-FY2026-Q2-1"
    return ladder


def _restated(api):
    """A correction assessed under the iron-curtain method against the original
    filing, plus the approved amendment document waiting to go out."""
    ladder = _filed(api)
    committee, cycle = ladder["committee"], ladder["cycle"]
    correction = open_correction(
        api, ladder["filing"]["id"], description=CORRECTION_DESCRIPTION,
        error_amount=400000, current_period_pretax_income=10000000,
        prior_period_pretax_income=12000000, cumulative_prior_uncorrected_amount=300000,
    )
    assert correction["status"] == "DRAFT"
    assert correction["materiality_pct"] is None
    assert correction["classification"] is None
    ladder["correction"] = assess_correction(
        api, correction["id"], method="IRON_CURTAIN", likelihood_pct=40,
        magnitude_amount=500000, compensating_control_present=True,
    )
    rows = deficiencies_of(api, correction["id"])
    assert len(rows) == 1
    ladder["deficiency"] = rows[0]

    amendment = create_document(
        api, committee, cycle["id"], "PERIODIC_FILING", "fin",
        title="Form 10-Q/A No. 1 FY2026-Q2", safe_harbor_present=True,
    )
    add_tie_out(api, committee, amendment["id"], "Warranty accrual", 900000.0, 900000.0)
    submit_for_review(api, committee, amendment["id"], "fin")
    approve_document(api, committee, amendment["id"], "legal")
    ladder["amendment_document"] = amendment
    return ladder


def test_the_open_deficiency_blocks_the_amending_filing_and_not_the_declaration(api):
    """The cycle is already FILED, so the filing-readiness gate can never be
    re-evaluated on it; the deficiency raised by the iron-curtain assessment
    therefore has to stop the amending filing itself, which it does with
    ERR_DEFICIENCY_OPEN while leaving the original filing untouched.

    PRD 3.9: "For an `error_amount` of 400000, a `current_period_pretax_income` of 10000000, a `cumulative_prior_uncorrected_amount` of 300000 and a `prior_period_pretax_income` of 12000000, the rollover method returns 4.00 and classifies the correction as a `REVISION`, while the iron-curtain method returns 5.83 and classifies the identical data as a `RESTATEMENT`."

    PRD 3.9: "Hop four, caused by that weight rising above 0.00 while the classification is `RESTATEMENT`, moves the cycle's `restatement_stage` from `UNDER_EVALUATION` to `RESTATEMENT_DECLARED`."

    PRD 3.9: "An **amending filing** supplies `amends_filing_id`, which must name a filing on the same cycle currently in `SUBMITTED`, or the request is rejected with `ERR_AMENDMENT_TARGET_INVALID`; it also requires the cycle's `unresolved_deficiency_weight` to be exactly 0.00, else `ERR_DEFICIENCY_OPEN` — the company may not file an amended report while a control weakness raised by a correction on this cycle is still open."

    Design: Corner/errors/filing_readiness_and_amendment_guards_fire_in_sequence_on_a_single_cycle
    """
    ladder = _restated(api)
    cycle = ladder["cycle"]

    assert_money(ladder["correction"]["materiality_pct"], 5.83)
    assert ladder["correction"]["classification"] == "RESTATEMENT"
    assert ladder["correction"]["status"] == "ASSESSED"

    deficiency = ladder["deficiency"]
    assert_money(deficiency["severity_score"], 3.50)
    assert deficiency["severity"] == "SIGNIFICANT_DEFICIENCY"
    assert_money(deficiency["deficiency_weight"], 7.00)
    assert deficiency["status"] == "OPEN"
    assert deficiency["remediation_note"] is None

    blocked = refresh_cycle(api, cycle["id"])
    assert_money(blocked["unresolved_deficiency_weight"], 7.00)
    assert blocked["restatement_stage"] == "RESTATEMENT_DECLARED"
    assert blocked["status"] == "FILED"

    refused = api.create_filing(
        filing_payload(
            cycle["id"], ladder["amendment_document"]["id"], ladder["filing"]["id"]
        ),
        admin_headers(),
    )
    validate_error(refused, "ERR_DEFICIENCY_OPEN", 409)

    assert validate_success(api.get_filing(ladder["filing"]["id"], admin_headers()))[
        "status"
    ] == "SUBMITTED"
    assert refresh_cycle(api, cycle["id"])["status"] == "FILED"


def test_mitigating_the_deficiency_closes_the_correction_and_releases_the_amendment(api):
    """Mitigation is the only fact the previous rejection named, and supplying it
    clears the weight, closes the correction, moves the remediation axis to
    REMEDIATED and lets the identical amending filing through; the superseded
    original becomes terminal and the accession suffix climbs to 2.

    PRD 3.9: "When no `OPEN` deficiency remains beneath the correction, the correction itself moves from `ASSESSED` to the terminal `CLOSED`."

    PRD 3.9: "And when the cycle's weight has returned to 0.00 with at least one `CLOSED` correction on the cycle, the remediation axis moves from `RESTATEMENT_DECLARED` to `REMEDIATED`."

    PRD 3.9: "In every amending case the superseded filing moves from `SUBMITTED` to the terminal `AMENDED_SUPERSEDED`."

    Design: Corner/errors/filing_readiness_and_amendment_guards_fire_in_sequence_on_a_single_cycle
    """
    ladder = _restated(api)
    committee, cycle = ladder["committee"], ladder["cycle"]

    mitigated = mitigate_deficiency(
        api, ladder["deficiency"]["id"], remediation_note=REMEDIATION_NOTE
    )
    assert mitigated["status"] == "MITIGATED"
    assert mitigated["remediation_note"] == REMEDIATION_NOTE

    released = refresh_cycle(api, cycle["id"])
    assert_money(released["unresolved_deficiency_weight"], 0.00)
    assert released["restatement_stage"] == "REMEDIATED"
    assert released["status"] == "FILED"
    assert validate_success(
        api.get_correction(ladder["correction"]["id"], admin_headers())
    )["status"] == "CLOSED"

    amendment = submit_filing(
        api, cycle["id"], ladder["amendment_document"]["id"],
        amends_filing_id=ladder["filing"]["id"],
    )
    assert amendment["accession_label"] == "FORM_10Q-FY2026-Q2-2"
    assert amendment["status"] == "SUBMITTED"
    assert amendment["late_flag"] is False

    superseded = validate_success(
        api.get_filing(ladder["filing"]["id"], admin_headers())
    )
    assert superseded["status"] == "AMENDED_SUPERSEDED"

    final = refresh_cycle(api, cycle["id"])
    assert final["status"] == "AMENDED"
    assert final["restatement_stage"] == "REMEDIATED"
    assert final["version"] > released["version"]
    assert refresh_document(api, committee, ladder["amendment_document"]["id"])[
        "status"
    ] == "FILED"
