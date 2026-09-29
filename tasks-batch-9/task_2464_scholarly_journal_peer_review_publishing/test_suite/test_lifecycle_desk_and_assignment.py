"""The desk leg of the lifecycle: assignment recusal, desk rejection and the locked manuscript."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client


def _setup_proposed_assignment(handling_editor_count=1):
    """A screened `SUBMITTED` manuscript with one `PROPOSED` assignment, conflict unanswered."""
    world = fx.setup_submitted_manuscript(handling_editor_count=handling_editor_count)
    fx.file_plagiarism_screening(world["manuscript"]["id"], 5.0)
    world["assignment"] = fx.assign_editor(
        world["manuscript"]["id"],
        world["chief_headers"],
        editor_id=world["handling"]["id"],
    )
    return world


def _setup_out_of_scope_assignment():
    """An `ACTIVE` assignment on a manuscript whose subject area the journal does not carry."""
    journal = fx.create_journal(subject_areas=["BIOCHEMISTRY"])
    chief, chief_headers = fx.create_chief(journal["id"])
    handling, handling_headers = fx.create_handling_editor(
        journal["id"], subject_areas=["BIOCHEMISTRY", "CARDIOLOGY"]
    )
    author, author_headers = fx.create_author()
    manuscript = fx.create_manuscript(
        journal["id"], author, author_headers, subject_area="CARDIOLOGY"
    )
    fx.file_plagiarism_screening(manuscript["id"], 5.0)
    assignment = fx.assign_editor(
        manuscript["id"], chief_headers, editor_id=handling["id"]
    )
    fx.declare_no_conflict(assignment["id"], handling_headers)
    return {
        "journal": journal,
        "chief": chief,
        "handling": handling,
        "handling_headers": handling_headers,
        "manuscript": manuscript,
        "assignment": assignment,
    }


def _decision_total_count(manuscript_id):
    _rows, meta = validate_paginated(
        api_client.list_decisions(
            SYSTEM_ADMIN_HEADERS, params={"manuscript_id": manuscript_id}
        )
    )
    return meta["total_count"]


def test_desk_rejection_locks_the_manuscript_without_writing_a_decision():
    """The desk call closes the paper by status alone; no `Decision` row is born.

    PRD: "It moves the manuscript `SUBMITTED → DESK_REJECTED`, which is terminal, releases the `ACTIVE` assignment to `RELEASED` with `released_reason` `DECISION_FINAL` and decrements that editor's `active_assignment_count` by 1, and advances the manuscript's `version` by 1."

    Design: Corner/state_machines/desk_reject_releases_active_assignment_and_locks_manuscript
    """
    world = fx.setup_active_assignment()
    manuscript_id = world["manuscript"]["id"]
    before = fx.get_manuscript(manuscript_id)

    fx.desk_reject(manuscript_id, world["handling_headers"])

    manuscript = fx.get_manuscript(manuscript_id)
    a.assert_fields(
        manuscript,
        status="DESK_REJECTED",
        integrity_status="PASS",
        decision_count=0,
    )
    assert manuscript["version"] == before["version"] + 1
    assert _decision_total_count(manuscript_id) == 0


def test_desk_rejection_releases_the_assignment_and_frees_the_editor():
    """The same request that locks the manuscript hands the editor's slot back.

    PRD: "An assignment can also leave `ACTIVE` without anyone asking: whenever the manuscript reaches `DESK_REJECTED`, `REJECTED` or `IN_PRODUCTION`, the `ACTIVE` assignment moves `ACTIVE → RELEASED` with `released_reason` `DECISION_FINAL` and that editor's `active_assignment_count` falls by 1."

    Design: Corner/state_machines/desk_reject_releases_active_assignment_and_locks_manuscript
    """
    world = fx.setup_active_assignment()
    assert fx.get_editor(world["handling"]["id"])["active_assignment_count"] == 1

    fx.desk_reject(world["manuscript"]["id"], world["handling_headers"])

    assignment = fx.get_assignment(world["assignment"]["id"])
    a.assert_fields(assignment, state="RELEASED", released_reason="DECISION_FINAL")
    assert fx.get_editor(world["handling"]["id"])["active_assignment_count"] == 0


def test_further_screening_of_a_desk_rejected_manuscript_is_refused():
    """A terminal manuscript accepts no more integrity evidence.

    PRD: "A manuscript addressed by any action endpoint from a status that declares no such transition is refused with `ERR_INVALID_MANUSCRIPT_STATE`, and once `DESK_REJECTED` or `RETRACTED` the answer becomes `ERR_TERMINAL_STATE_LOCKED`."

    Design: Corner/state_machines/screening_on_desk_rejected_manuscript_terminal_state_locked
    """
    world = fx.setup_active_assignment()
    manuscript_id = world["manuscript"]["id"]
    fx.desk_reject(manuscript_id, world["handling_headers"])

    response = api_client.create_integrity_screening(
        manuscript_id,
        f.image_forensics_screening_payload(3),
        SYSTEM_ADMIN_HEADERS,
    )

    validate_error(
        response, ApiErrorId.ERR_TERMINAL_STATE_LOCKED.value, expected_status=409
    )
    manuscript = fx.get_manuscript(manuscript_id)
    a.assert_fields(manuscript, status="DESK_REJECTED", integrity_status="PASS")
    assert len(fx.list_integrity_screenings(manuscript_id)) == 1
    assert fx.list_ethics_cases(manuscript_id) == []


def test_declared_conflict_recuses_the_proposed_editor():
    """The declaration itself is the transition, and it gives the editor's slot back.

    PRD: "A declaration of true without a `conflict_type` is refused with `ERR_EDITOR_CONFLICT_DECLARED`; with one, the assignment moves `PROPOSED → RECUSED` carrying `released_reason` `RECUSAL`, that editor's `active_assignment_count` falls by 1, and the replacement cascade runs: the selector is re-run with every editor who already holds a `RECUSED` assignment on this manuscript excluded, and on success a fresh assignment is created at `PROPOSED` with `replaced_assignment_id` pointing at the assignment it supersedes and the replacement editor's `active_assignment_count` rising by 1."

    Design: Corner/state_machines/conflict_declaration_true_recuses_and_proposes_replacement_editor
    """
    world = _setup_proposed_assignment(handling_editor_count=2)
    first = world["handlings"][0]["editor"]
    assert fx.get_editor(first["id"])["active_assignment_count"] == 1

    recused = fx.declare_conflict(
        world["assignment"]["id"],
        world["handlings"][0]["headers"],
        conflict_type="SAME_INSTITUTION",
    )

    a.assert_fields(
        recused,
        state="RECUSED",
        released_reason="RECUSAL",
        declared_conflict=True,
        conflict_type="SAME_INSTITUTION",
    )
    assert fx.get_editor(first["id"])["active_assignment_count"] == 0


def test_recusal_proposes_the_other_editor_and_links_the_superseded_row():
    """The replacement cascade writes one fresh `PROPOSED` row pointing back at the old one.

    PRD: "A declaration of true without a `conflict_type` is refused with `ERR_EDITOR_CONFLICT_DECLARED`; with one, the assignment moves `PROPOSED → RECUSED` carrying `released_reason` `RECUSAL`, that editor's `active_assignment_count` falls by 1, and the replacement cascade runs: the selector is re-run with every editor who already holds a `RECUSED` assignment on this manuscript excluded, and on success a fresh assignment is created at `PROPOSED` with `replaced_assignment_id` pointing at the assignment it supersedes and the replacement editor's `active_assignment_count` rising by 1."

    Design: Corner/state_machines/conflict_declaration_true_recuses_and_proposes_replacement_editor
    """
    world = _setup_proposed_assignment(handling_editor_count=2)
    replacement = world["handlings"][1]["editor"]

    fx.declare_conflict(
        world["assignment"]["id"],
        world["handlings"][0]["headers"],
        conflict_type="SAME_INSTITUTION",
    )

    proposed = fx.list_assignments(world["manuscript"]["id"], state="PROPOSED")
    assert len(proposed) == 1, f"Expected exactly one open proposal, got {proposed}"
    a.assert_fields(
        proposed[0],
        editor_id=replacement["id"],
        state="PROPOSED",
        selected_by="SELECTOR",
        replaced_assignment_id=world["assignment"]["id"],
    )
    assert fx.get_editor(replacement["id"])["active_assignment_count"] == 1
    assert fx.get_manuscript(world["manuscript"]["id"])["handling_gap_flag"] is False


def test_recusal_with_nobody_left_raises_the_handling_gap_flag():
    """With the only handling editor recused, the manuscript is flagged rather than reassigned.

    PRD: "On an empty pool no replacement is created and the manuscript's `handling_gap_flag` becomes true."

    Design: Corner/state_machines/conflict_declaration_true_with_no_replacement_sets_handling_gap_flag
    """
    world = _setup_proposed_assignment(handling_editor_count=1)

    recused = fx.declare_conflict(
        world["assignment"]["id"], world["handling_headers"], conflict_type="CO_AUTHOR"
    )

    a.assert_fields(recused, state="RECUSED", released_reason="RECUSAL")
    assert fx.get_editor(world["handling"]["id"])["active_assignment_count"] == 0
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, status="SUBMITTED", handling_gap_flag=True)
    assert len(fx.list_assignments(world["manuscript"]["id"])) == 1
    assert fx.list_assignments(world["manuscript"]["id"], state="PROPOSED") == []


def test_advance_to_review_refuses_a_manuscript_outside_the_journals_scope():
    """A clean, compliant paper is still refused when the journal does not carry its field.

    PRD: "It additionally requires that the manuscript's `integrity_status` is either `PASS` or `FLAG` — a `BLOCK` rollup is refused with `ERR_INTEGRITY_BLOCK`, and the only ways forward from there are a desk rejection or an ethics case resolved in the manuscript's favour; that the manuscript's `formatting_status` is `COMPLIANT`, a `NON_COMPLIANT` manuscript being refused with `ERR_FORMATTING_NON_COMPLIANT`; and that the manuscript's `subject_area` is a member of the journal's `subject_areas`, an out-of-scope paper being refused with `ERR_SUBJECT_AREA_OUT_OF_SCOPE`."

    Design: Corner/state_machines/advance_to_review_blocked_when_subject_area_out_of_scope
    """
    world = _setup_out_of_scope_assignment()

    response = api_client.screening_decision(
        world["manuscript"]["id"],
        f.screening_decision_payload("ADVANCE_TO_REVIEW"),
        world["handling_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_SUBJECT_AREA_OUT_OF_SCOPE.value, expected_status=409
    )
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="SUBMITTED",
        integrity_status="PASS",
        formatting_status="COMPLIANT",
    )
    assert fx.get_assignment(world["assignment"]["id"])["state"] == "ACTIVE"
