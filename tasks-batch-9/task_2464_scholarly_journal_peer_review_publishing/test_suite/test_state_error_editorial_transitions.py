"""Editorial refusals: a permanent conflict, an empty editor pool, undeclared transitions and a locked licence."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client


def _attempt_assignment(manuscript_id, chief_headers, editor_id=None):
    payload = f.editor_assignment_payload(
        manuscript_id, fx.get_manuscript_version(manuscript_id)
    )
    if editor_id is not None:
        payload["editor_id"] = editor_id
    return api_client.create_editor_assignment(payload, chief_headers)


def _attempt_conflict_declaration(assignment_id, handling_headers):
    return api_client.declare_conflict(
        assignment_id,
        f.conflict_declaration_payload(True, conflict_type="SAME_INSTITUTION"),
        handling_headers,
    )


def _attempt_advance_to_review(manuscript_id, handling_headers):
    return api_client.screening_decision(
        manuscript_id,
        f.screening_decision_payload("ADVANCE_TO_REVIEW", note="Replayed desk call"),
        handling_headers,
    )


def _attempt_licence_change(manuscript_id, author_headers):
    return api_client.change_licensing(
        manuscript_id, f.licensing_payload("CC_BY_NC"), author_headers
    )


def _attempt_case_advance(case_id, chief_headers, to_state):
    return api_client.advance_ethics_case(
        case_id, f.ethics_case_advance_payload(to_state), chief_headers
    )


def _setup_open_ethics_case():
    """A submitted manuscript carrying one manually opened case at `OPEN`."""
    world = fx.setup_submitted_manuscript()
    world["ethics_case"] = fx.open_ethics_case(
        world["manuscript"]["id"],
        SYSTEM_ADMIN_HEADERS,
        case_type="AUTHORSHIP_DISPUTE",
        severity="MEDIUM",
    )
    return world


def _setup_recused_sole_editor():
    """The journal's only handling editor has declared a conflict on the manuscript."""
    world = fx.setup_submitted_manuscript(handling_editor_count=1)
    fx.file_plagiarism_screening(world["manuscript"]["id"])
    assignment = fx.assign_editor(
        world["manuscript"]["id"],
        world["chief_headers"],
        editor_id=world["handling"]["id"],
    )
    fx.declare_conflict(assignment["id"], world["handling_headers"])
    world["assignment"] = fx.get_assignment(assignment["id"])
    return world


def test_reassigning_an_editor_who_declared_a_conflict_is_refused():
    """The declared conflict outlives the assignment it ended.

    PRD: "If that editor has already recused himself from this manuscript, the request is refused with `ERR_EDITOR_CONFLICT_DECLARED` — a declared conflict is permanent and no amount of reassignment undoes it."

    Design: Corner/errors/assignment_rejected_for_an_editor_who_already_declared_a_conflict
    """
    world = _setup_recused_sole_editor()
    a.assert_fields(world["assignment"], state="RECUSED", declared_conflict=True)

    response = _attempt_assignment(
        world["manuscript"]["id"], world["chief_headers"], world["handling"]["id"]
    )

    error = validate_error(
        response, ApiErrorId.ERR_EDITOR_CONFLICT_DECLARED.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_EDITOR_WORKLOAD_EXCEEDED.value, (
        "the editor carries no load at all, so the refusal is about the conflict"
    )


def test_refused_reassignment_creates_no_second_assignment():
    """The manuscript keeps exactly the one recused assignment it already had.

    PRD: "Either way the assignment is born at `PROPOSED`, the named editor's `active_assignment_count` rises by 1, and the manuscript's `version` advances by 1."

    Design: Corner/errors/assignment_rejected_for_an_editor_who_already_declared_a_conflict
    """
    world = _setup_recused_sole_editor()

    _attempt_assignment(
        world["manuscript"]["id"], world["chief_headers"], world["handling"]["id"]
    )

    assignments = fx.list_assignments(world["manuscript"]["id"])
    assert len(assignments) == 1, f"expected one assignment row, got {assignments}"
    a.assert_fields(assignments[0], state="RECUSED", released_reason="RECUSAL")
    editor = fx.get_editor(world["handling"]["id"])
    a.assert_fields(editor, active_assignment_count=0)
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "SUBMITTED"


def test_direct_assignment_with_no_handling_editor_reports_an_empty_pool():
    """The journal has a chief editor only, so the selector finds nobody.

    PRD: "When the caller omits the explicit identifier, the selector finds at least one eligible candidate — otherwise `ERR_NO_ELIGIBLE_EDITOR` or `ERR_NO_ELIGIBLE_REVIEWER` (409), on assignment creation and invitation creation respectively."

    Design: Corner/errors/editor_selector_with_no_handling_editor_rejected
    """
    world = fx.setup_submitted_manuscript(handling_editor_count=0)

    response = _attempt_assignment(world["manuscript"]["id"], world["chief_headers"])

    validate_error(
        response, ApiErrorId.ERR_NO_ELIGIBLE_EDITOR.value, expected_status=409
    )


def test_refused_direct_selection_creates_no_assignment_and_flags_no_gap():
    """A refused direct request is not the cascade, so it leaves no handling gap behind.

    PRD: "If the pool is empty, a direct assignment request is refused with `ERR_NO_ELIGIBLE_EDITOR`, while a selector invoked from inside a cascade creates no assignment at all and instead sets the manuscript's `handling_gap_flag` to true, recording that the manuscript has been left without a handling editor."

    Design: Corner/errors/editor_selector_with_no_handling_editor_rejected
    """
    world = fx.setup_submitted_manuscript(handling_editor_count=0)

    _attempt_assignment(world["manuscript"]["id"], world["chief_headers"])

    assert fx.list_assignments(world["manuscript"]["id"]) == []
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, status="SUBMITTED", handling_gap_flag=False)


def test_replayed_advance_to_review_is_refused_by_the_manuscript_state():
    """`UNDER_REVIEW` declares no desk call, and it is not a terminal status either.

    PRD: "A manuscript addressed by any action endpoint from a status that declares no such transition is refused with `ERR_INVALID_MANUSCRIPT_STATE`, and once `DESK_REJECTED` or `RETRACTED` the answer becomes `ERR_TERMINAL_STATE_LOCKED`."

    Design: Corner/errors/screening_decision_on_a_manuscript_under_review_rejected
    """
    world = fx.setup_under_review_manuscript()
    assert world["manuscript"]["status"] == "UNDER_REVIEW"

    response = _attempt_advance_to_review(
        world["manuscript"]["id"], world["handling_headers"]
    )

    error = validate_error(
        response, ApiErrorId.ERR_INVALID_MANUSCRIPT_STATE.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_TERMINAL_STATE_LOCKED.value, (
        "a manuscript under review has not reached either terminal status"
    )


def test_refused_replay_leaves_the_manuscript_and_its_assignment_alone():
    """The desk call that would have moved the manuscript wrote nothing at all.

    PRD: "On success the manuscript moves `SUBMITTED → UNDER_REVIEW`, its `review_shortfall_flag` is set to false, and its `version` advances by 1."

    Design: Corner/errors/screening_decision_on_a_manuscript_under_review_rejected
    """
    world = fx.setup_under_review_manuscript()
    version_before = world["manuscript"]["version"]

    _attempt_advance_to_review(world["manuscript"]["id"], world["handling_headers"])

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="UNDER_REVIEW",
        revision_round=0,
        version=version_before,
    )
    assert fx.get_assignment(world["assignment"]["id"])["state"] == "ACTIVE"


def test_conflict_declaration_on_an_already_active_assignment_is_refused():
    """The declaration endpoint moves an assignment out of `PROPOSED` and nowhere else.

    PRD: "`RECUSED` and `RELEASED` are both terminal: a further transition attempt on such an assignment is refused with `ERR_TERMINAL_STATE_LOCKED`, and a transition requested from a state that does not declare it — activating an already-`ACTIVE` assignment, for instance — is refused with `ERR_INVALID_ASSIGNMENT_STATE`."

    Design: Corner/errors/conflict_declaration_on_an_active_assignment_rejected
    """
    world = fx.setup_active_assignment()
    assert world["assignment"]["state"] == "ACTIVE"

    response = _attempt_conflict_declaration(
        world["assignment"]["id"], world["handling_headers"]
    )

    error = validate_error(
        response, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_TERMINAL_STATE_LOCKED.value, (
        "an ACTIVE assignment is not one of the two terminal assignment states"
    )


def test_refused_declaration_leaves_the_assignment_active_and_conflict_free():
    """The second declaration neither recuses the editor nor releases his load.

    PRD: "A declaration of false moves the assignment `PROPOSED → ACTIVE`, stores `declared_conflict` as false, and clears the manuscript's `handling_gap_flag` to false."

    Design: Corner/errors/conflict_declaration_on_an_active_assignment_rejected
    """
    world = fx.setup_active_assignment()

    _attempt_conflict_declaration(world["assignment"]["id"], world["handling_headers"])

    assignment = fx.get_assignment(world["assignment"]["id"])
    a.assert_fields(
        assignment,
        state="ACTIVE",
        declared_conflict=False,
        version=world["assignment"]["version"],
    )
    editor = fx.get_editor(world["handling"]["id"])
    a.assert_fields(editor, active_assignment_count=1)
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "SUBMITTED"


def test_ethics_case_advance_that_skips_the_investigation_is_refused():
    """Committee review is two steps away from `OPEN`, and only the first step is declared.

    PRD: "A requested `to_state` that is not declared from the case's current state is refused with `ERR_INVALID_ETHICS_CASE_STATE`, and each successful advance raises the case's `version` by 1."

    Design: Corner/errors/ethics_case_advance_skipping_investigation_rejected
    """
    world = _setup_open_ethics_case()
    case_id = world["ethics_case"]["id"]

    response = _attempt_case_advance(
        case_id, world["chief_headers"], "COMMITTEE_REVIEW"
    )

    validate_error(
        response, ApiErrorId.ERR_INVALID_ETHICS_CASE_STATE.value, expected_status=409
    )
    case = fx.get_ethics_case(case_id)
    a.assert_fields(case, state="OPEN", version=world["ethics_case"]["version"])
    assert case.get("resolved_at") is None


def test_the_one_declared_step_out_of_open_still_succeeds_afterwards():
    """The refusal left the case where it was, so the legal step is still available.

    PRD: "The only declared step out of the opening state is `OPEN → INVESTIGATION`."

    Design: Corner/errors/ethics_case_advance_skipping_investigation_rejected
    """
    world = _setup_open_ethics_case()
    case_id = world["ethics_case"]["id"]
    _attempt_case_advance(case_id, world["chief_headers"], "COMMITTEE_REVIEW")

    fx.advance_ethics_case(case_id, world["chief_headers"], "INVESTIGATION")

    case = fx.get_ethics_case(case_id)
    a.assert_fields(
        case, state="INVESTIGATION", version=world["ethics_case"]["version"] + 1
    )
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "SUBMITTED"


def test_licence_change_on_a_desk_rejected_manuscript_is_locked():
    """Desk rejection is one of the four statuses that freeze the licence.

    PRD: "Attempting a licence change once the manuscript has reached any of those four states is refused with `ERR_LICENSE_LOCKED`."

    Design: Corner/errors/licensing_change_on_a_desk_rejected_manuscript_rejected
    """
    world = fx.setup_active_assignment()
    fx.desk_reject(world["manuscript"]["id"], world["handling_headers"])
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "DESK_REJECTED"

    response = _attempt_licence_change(
        world["manuscript"]["id"], world["author_headers"]
    )

    validate_error(response, ApiErrorId.ERR_LICENSE_LOCKED.value, expected_status=409)


def test_refused_licence_change_leaves_the_licence_and_version_untouched():
    """The submitted licence stands, and no version was spent on the refusal.

    PRD: "The corresponding author may change the manuscript's `oa_license` at any point before the article becomes immutable — that is, while the manuscript's `status` is not `PUBLISHED`, `CORRECTED`, `RETRACTED` or `DESK_REJECTED`."

    Design: Corner/errors/licensing_change_on_a_desk_rejected_manuscript_rejected
    """
    world = fx.setup_active_assignment()
    fx.desk_reject(world["manuscript"]["id"], world["handling_headers"])
    rejected = fx.get_manuscript(world["manuscript"]["id"])

    _attempt_licence_change(world["manuscript"]["id"], world["author_headers"])

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        oa_license="CC_BY",
        status="DESK_REJECTED",
        version=rejected["version"],
    )
    assignment = fx.get_assignment(world["assignment"]["id"])
    a.assert_fields(assignment, state="RELEASED", released_reason="DECISION_FINAL")
