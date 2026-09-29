"""Three authorisation bands that share a status code but not a cause.

The 401 band asks whether a credential was supplied at all, including on reads;
the 403 band then splits three ways — an unknown or unlisted role, an
unresolvable seat, a function that does not match the role claimed — and the
action gate on the multiplexed endpoints sits behind all of them.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ROLE_COMPLIANCE_ADMIN
from test_helpers.factories import (
    action_payload,
    charter_payload,
    filing_payload,
    milestone_payload,
    subcert_payload,
    tie_out_item_payload,
)
from test_helpers.fixtures import (
    add_milestone,
    add_qa_item,
    assign_subcert,
    build_committee,
    build_cycle,
    clear_qa_item,
    create_document,
    open_close,
    refresh_document,
    register_cert,
    start_milestone,
    submit_for_review,
    submit_subcert,
)
from test_helpers.test_users import (
    admin_headers,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_controller_headers,
    make_headers,
)

PROBE_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
]
UNSEATED_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_MILESTONE_ID = "00000000-0000-4000-8000-0000000000bb"
UNDECLARED_ROLE = "Auditor"


def _probe_cycle(api):
    """One adopted charter and one cycle, which is all the state these probes
    need because none of them gets past the authorisation band."""
    committee = build_committee(
        api,
        seats=PROBE_SEATS,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Auth Probe Charter",
        chair_key="fin",
    )
    cycle = build_cycle(api, committee)
    return committee, cycle


def test_neither_header_may_be_missing_or_empty_even_on_a_read(api):
    """A list endpoint is still not anonymous: dropping the role header, dropping
    the identifier header, and sending an empty identifier all fail the very first
    rule with 401, while the opaque compliance credential — whose identifier is
    never resolved to a seat — is served with its arbitrary operator id.

    PRD 2.1: "If either header is absent or empty the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD 2.1: "When `X-User-Role` is `ComplianceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity."

    Design: Corner/rbac/probe_missing_auth_headers_and_unknown_roles_are_rejected_before_any_state_check
    """
    _probe_cycle(api)

    validate_error(
        api.list_charters(headers_without_role("admin-1"), limit=10, offset=0),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.list_charters(
            headers_without_user_id(ROLE_COMPLIANCE_ADMIN), limit=10, offset=0
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.list_charters(
            headers_with_empty_user_id(ROLE_COMPLIANCE_ADMIN), limit=10, offset=0
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    rows, meta = validate_paginated(
        api.list_charters(admin_headers(), limit=10, offset=0)
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


def test_an_unknown_role_an_unlisted_role_and_an_unseated_id_share_one_code(api):
    """A role name outside the seven, a declared role missing from the endpoint's
    own list, and a seat-backed role whose identifier resolves to nothing all
    answer 403 rather than 401 or 404 — the last one even when the path names a
    milestone that does not exist, because the authorisation band is decided
    before any identifier is looked up.

    PRD 2.1: "If `X-User-Role` is not one of the seven role names declared below, or is a declared role that the called endpoint does not list as authorised, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD 2.1: "If `X-User-ID` does not resolve to an existing `CommitteeMember` row on an endpoint whose authorised-role list includes at least one seat-backed role, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403) — the same code used for an unrecognised or unauthorised role, since from the caller's perspective the credential simply is not usable here."

    PRD 2.11: "When a single request violates more than one rule, exactly one error is returned, and it is always the violation that sits **earliest** in the following ladder."

    Design: Corner/rbac/probe_missing_auth_headers_and_unknown_roles_are_rejected_before_any_state_check
    """
    committee, cycle = _probe_cycle(api)

    validate_error(
        api.list_charters(
            make_headers("someone-1", UNDECLARED_ROLE), limit=10, offset=0
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_charter(
            charter_payload(name="Smuggled Charter", version_label="2026.9"),
            committee.controller("fin"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_milestone(
            cycle["id"],
            milestone_payload("CLOSE", "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z"),
            make_controller_headers(UNSEATED_ID),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.transition_milestone(
            UNKNOWN_MILESTONE_ID,
            action_payload("START"),
            make_controller_headers(UNSEATED_ID),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    _, meta = validate_paginated(api.list_charters(admin_headers(), limit=10, offset=0))
    assert meta["total_count"] == 1
    left_empty, calendar = validate_paginated(
        api.list_cycle_milestones(cycle["id"], admin_headers(), limit=10, offset=0)
    )
    assert left_empty == []
    assert calendar["total_count"] == 0


MATRIX_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ir", "Ivy Relations", "INVESTOR_RELATIONS", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
    ("ops", "Bo Ops", "OPERATIONS", False, False),
]
MATRIX_FUNCTIONS = ["FINANCE", "LEGAL", "INVESTOR_RELATIONS"]
QUESTION = "How should we frame the warranty accrual change?"
CLEARANCE_NOTE = "Approved wording with a forward-looking qualifier."
SELF_CLEARANCE_NOTE = "Investor relations self-clearance attempt."
LEADER_ATTESTATION = "A business leader attempting an officer signature."
CANON_DUE = "2026-08-04T17:00:00Z"


def _matrix(api):
    """One seat per function, a CLOSE_OPEN cycle, a pending sub-certification held
    by the operations leader and a call script carrying one HIGH-tier question."""
    committee = build_committee(
        api,
        seats=MATRIX_SEATS,
        min_quorum_count=3,
        required_functions=MATRIX_FUNCTIONS,
        name="Role Matrix Charter",
    )
    cycle = build_cycle(api, committee)
    close = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    request = assign_subcert(
        api, committee, cycle["id"], "ops", "OPERATIONS", due_utc=CANON_DUE
    )
    document = create_document(
        api, committee, cycle["id"], "CALL_SCRIPT", "ir",
        title="Q2 Earnings Call Script", safe_harbor_present=True, role="relations",
    )
    question = add_qa_item(
        api, committee, document["id"], question_text=QUESTION, topic="MARGIN",
        risk_tier="HIGH",
    )
    cert = register_cert(api, cycle["id"], committee, "ceo", "CEO_302")
    return {
        "committee": committee,
        "cycle": cycle,
        "close": close,
        "request": request,
        "document": document,
        "question": question,
        "cert": cert,
    }


def test_each_role_reaches_the_write_that_belongs_to_it(api):
    """Five writes, five different credentials: investor relations owns the
    question bank, legal counsel owns its clearance, the business leader owns the
    submission of the request assigned to it, the controller owns the calendar,
    and the review submission is the one document action investor relations shares
    with the other two.

    PRD 3.7: "An `InvestorRelations` member adds prepared questions to a call script, and the target document — referenced as `script_document_id` — must be one whose `doc_type` is `CALL_SCRIPT`."

    PRD 3.7: "Clearing a question is reserved to `LegalCounsel`, requires a `clearance_note`, and moves the question to `CLEARED` from either `DRAFT` or `BLOCKED`."

    PRD 2.1: "On a sub-certification, `SUBMIT` is reserved to `BusinessLeader` and `WITHDRAW` to `DisclosureCommitteeChair`."

    PRD 2.1: "On a document, `REQUEST_CHANGES` and `APPROVE` are open to `Controller` and `LegalCounsel` only, while `SUBMIT_REVIEW` additionally accepts `InvestorRelations`."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_write_and_cannot_reach_another_roles
    """
    matrix = _matrix(api)
    committee = matrix["committee"]

    assert matrix["question"]["status"] == "BLOCKED"
    assert matrix["question"]["clearance_note"] is None

    cleared = clear_qa_item(
        api, committee, matrix["question"]["id"], clearance_note=CLEARANCE_NOTE
    )
    assert cleared["status"] == "CLEARED"
    assert cleared["clearance_note"] == CLEARANCE_NOTE

    submitted = submit_subcert(api, committee, matrix["request"]["id"], "ops")
    assert submitted["status"] == "SUBMITTED"

    started = start_milestone(api, committee, matrix["close"]["id"])
    assert started["status"] == "IN_PROGRESS"

    in_review = validate_success(
        api.transition_document(
            matrix["document"]["id"],
            action_payload("SUBMIT_REVIEW"),
            committee.relations("ir"),
        )
    )
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["qa_gate_status"] == "CLEARED"


def test_no_role_reaches_another_roles_exclusive_write_in_either_direction(api):
    """Seven refusals, all with the same code and status: the chair cannot open the
    calendar the controller owns and the controller cannot assign the requests the
    chair owns, so the segregation runs in both directions between peers rather
    than down a hierarchy, and neither the compliance credential nor the chair is
    a super-user. Nothing is created or advanced by any of them.

    PRD 2.1: "If `X-User-Role` is not one of the seven role names declared below, or is a declared role that the called endpoint does not list as authorised, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD 2.11: "`X-User-Role` names one of the seven declared roles and appears in the called endpoint's authorised-role list."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_write_and_cannot_reach_another_roles
    """
    matrix = _matrix(api)
    committee, cycle = matrix["committee"], matrix["cycle"]
    document = matrix["document"]

    validate_error(
        api.create_subcert(
            subcert_payload(cycle["id"], committee.mid("fin"), "REVENUE", CANON_DUE),
            committee.controller("fin"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_milestone(
            cycle["id"],
            milestone_payload("REVIEW", "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z"),
            committee.chair("legal"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_tie_out_item(
            document["id"],
            tie_out_item_payload(
                "Total revenue", 4120000.0, 4120000.0, 25, committee.mid("fin"),
                document["version"],
            ),
            committee.counsel("legal"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.clear_qa_item(
            matrix["question"]["id"],
            {"clearance_note": SELF_CLEARANCE_NOTE},
            committee.relations("ir"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.sign_officer_cert(
            matrix["cert"]["id"],
            {"attestation_text": LEADER_ATTESTATION},
            committee.leader("ops"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_filing(
            filing_payload(cycle["id"], document["id"]), committee.officer("ceo")
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.transition_document(
            document["id"], action_payload("SUBMIT_REVIEW"), admin_headers()
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    calendar, calendar_meta = validate_paginated(
        api.list_cycle_milestones(cycle["id"], admin_headers(), limit=10, offset=0)
    )
    assert [row["kind"] for row in calendar] == ["CLOSE"]
    assert calendar_meta["total_count"] == 1
    requests, request_meta = validate_paginated(
        api.list_subcerts(admin_headers(), cycle_id=cycle["id"], limit=10, offset=0)
    )
    assert len(requests) == 1
    assert request_meta["total_count"] == 1
    assert requests[0]["status"] == "PENDING"

    untouched = refresh_document(api, committee, document["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["qa_gate_status"] == "BLOCKED"


GATE_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ir", "Ivy Relations", "INVESTOR_RELATIONS", False, True),
    ("ops", "Bo Ops", "OPERATIONS", False, False),
]


def _gate(api):
    """The same shape with a non-voting operations seat, a pending request and a
    periodic filing already in review, so every probe below has a live target."""
    committee = build_committee(
        api,
        seats=GATE_SEATS,
        min_quorum_count=3,
        required_functions=MATRIX_FUNCTIONS,
        name="Function Gate Charter",
    )
    cycle = build_cycle(api, committee)
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    request = assign_subcert(
        api, committee, cycle["id"], "ops", "OPERATIONS", due_utc=CANON_DUE
    )
    document = create_document(
        api, committee, cycle["id"], "PERIODIC_FILING", "fin",
        title="Form 10-Q FY2026-Q2",
    )
    submitted = submit_for_review(api, committee, document["id"], "fin")
    assert submitted["status"] == "IN_REVIEW"
    return {
        "committee": committee,
        "cycle": cycle,
        "request": request,
        "document": document,
    }


def test_the_function_gate_answers_before_the_action_gate_does(api):
    """The legal member holds a real seat and the endpoint does list Controller, so
    the credential fails only on its function — and it fails there even when the
    action it names is one no Controller may invoke at all, because the function
    rule sits earlier in the ladder. The chair's gate is not a function but the
    voting flag, so the non-voting operations seat is refused with the same code
    from an entirely different predicate.

    PRD 2.1: "`Controller` requires that the acting member's `function` is `FINANCE`."

    PRD 2.1: "`DisclosureCommitteeChair` requires that the acting member's `voting` flag is true."

    PRD 2.1: "A credential that fails its function gate is rejected with `ERR_MEMBER_FUNCTION_MISMATCH` (HTTP 403)."

    PRD 2.11: "When a single request violates more than one rule, exactly one error is returned, and it is always the violation that sits **earliest** in the following ladder."

    Design: Corner/rbac/function_gate_outranks_action_gate_and_both_are_distinct_from_the_role_list_check
    """
    gate = _gate(api)
    committee, cycle = gate["committee"], gate["cycle"]

    validate_error(
        api.create_milestone(
            cycle["id"],
            milestone_payload("REVIEW", "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z"),
            committee.controller("legal"),
        ),
        "ERR_MEMBER_FUNCTION_MISMATCH",
        403,
    )
    validate_error(
        api.transition_cycle(
            cycle["id"],
            action_payload("DECLARE_FILING_READY"),
            committee.controller("legal"),
        ),
        "ERR_MEMBER_FUNCTION_MISMATCH",
        403,
    )
    validate_error(
        api.transition_cycle(
            cycle["id"], action_payload("OPEN_REVIEW"), committee.chair("ops")
        ),
        "ERR_MEMBER_FUNCTION_MISMATCH",
        403,
    )

    calendar, meta = validate_paginated(
        api.list_cycle_milestones(cycle["id"], admin_headers(), limit=10, offset=0)
    )
    assert [row["kind"] for row in calendar] == ["CLOSE"]
    assert meta["total_count"] == 1
    assert validate_success(api.get_cycle(cycle["id"], admin_headers()))["status"] == (
        "CLOSE_OPEN"
    )


def test_the_action_gate_answers_once_the_function_gate_is_satisfied(api):
    """Only the actor changes between the previous refusal and the first one here,
    and the code changes with it: a finance member acting as Controller passes the
    function gate and is stopped by the action instead. The same split runs across
    the two shared endpoints — approval is closed to investor relations while the
    review submission is open to it, and the two sub-certification actions are
    divided between the two roles that share the endpoint, so the chair's own
    withdrawal lands on a row none of the refusals damaged.

    PRD 2.1: "A role that is listed on the endpoint but not permitted to invoke the supplied `action` is rejected with `ERR_ROLE_ACTION_MISMATCH` (HTTP 403)."

    PRD 2.1: "On a reporting cycle, `DECLARE_FILING_READY` is reserved to `DisclosureCommitteeChair`, while `OPEN_CLOSE`, `OPEN_REVIEW`, `OPEN_CERTIFICATION` and `ABANDON` accept either `Controller` or `DisclosureCommitteeChair`."

    PRD 2.1: "On a document, `REQUEST_CHANGES` and `APPROVE` are open to `Controller` and `LegalCounsel` only, while `SUBMIT_REVIEW` additionally accepts `InvestorRelations`."

    PRD 2.1: "On a sub-certification, `SUBMIT` is reserved to `BusinessLeader` and `WITHDRAW` to `DisclosureCommitteeChair`."

    Design: Corner/rbac/function_gate_outranks_action_gate_and_both_are_distinct_from_the_role_list_check
    """
    gate = _gate(api)
    committee, cycle = gate["committee"], gate["cycle"]
    document, request = gate["document"], gate["request"]

    validate_error(
        api.transition_cycle(
            cycle["id"],
            action_payload("DECLARE_FILING_READY"),
            committee.controller("fin"),
        ),
        "ERR_ROLE_ACTION_MISMATCH",
        403,
    )
    validate_error(
        api.transition_document(
            document["id"], action_payload("APPROVE"), committee.relations("ir")
        ),
        "ERR_ROLE_ACTION_MISMATCH",
        403,
    )
    validate_error(
        api.transition_document(
            document["id"], action_payload("SUBMIT_REVIEW"), committee.relations("legal")
        ),
        "ERR_MEMBER_FUNCTION_MISMATCH",
        403,
    )
    validate_error(
        api.transition_subcert(
            request["id"], action_payload("WITHDRAW"), committee.leader("ops")
        ),
        "ERR_ROLE_ACTION_MISMATCH",
        403,
    )
    validate_error(
        api.transition_subcert(
            request["id"], action_payload("SUBMIT"), committee.chair("legal")
        ),
        "ERR_ROLE_ACTION_MISMATCH",
        403,
    )

    still_in_review = refresh_document(api, committee, document["id"])
    assert still_in_review["status"] == "IN_REVIEW"
    assert still_in_review["revision_round"] == 0

    withdrawn = validate_success(
        api.transition_subcert(
            request["id"], action_payload("WITHDRAW"), committee.chair("legal")
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
