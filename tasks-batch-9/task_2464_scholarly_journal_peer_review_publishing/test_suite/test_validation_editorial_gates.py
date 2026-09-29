"""The gates guarding assignment, the desk call and invitation creation."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client


def _invitation_request(manuscript_id, handling_headers, reviewer_id=None, **overrides):
    payload = f.review_invitation_payload(manuscript_id, **overrides)
    if reviewer_id is not None:
        payload["reviewer_id"] = reviewer_id
    return api_client.create_review_invitation(payload, handling_headers)


def _advance_request(manuscript_id, handling_headers):
    return api_client.screening_decision(
        manuscript_id,
        f.screening_decision_payload("ADVANCE_TO_REVIEW"),
        handling_headers,
    )


def _assignment_request(manuscript_id, chief_headers, editor_id):
    return api_client.create_editor_assignment(
        f.editor_assignment_payload(
            manuscript_id,
            fx.get_manuscript_version(manuscript_id),
            editor_id=editor_id,
        ),
        chief_headers,
    )


def _count_invitations(manuscript_id):
    rows, meta = validate_paginated(
        api_client.list_review_invitations(
            SYSTEM_ADMIN_HEADERS, params={"manuscript_id": manuscript_id}
        )
    )
    assert len(rows) == meta["total_count"], (
        "the whole invitation set for this manuscript fits in one page"
    )
    return meta["total_count"]


def _setup_reviewer_sharing_the_authors_affiliation():
    """An `UNDER_REVIEW` manuscript and a reviewer at the author's institution."""
    world = fx.setup_under_review_manuscript(
        author_overrides={"affiliation": "Univ Gamma"}
    )
    reviewer, _headers = fx.create_reviewer(affiliation="Univ Gamma")
    world["reviewer"] = reviewer
    return world


def _setup_workload_saturated_editor():
    """A handling editor with a ceiling of one, already holding one assignment."""
    journal = fx.create_journal()
    _chief, chief_headers = fx.create_chief(journal["id"])
    handling, handling_headers = fx.create_handling_editor(
        journal["id"], max_concurrent_assignments=1
    )
    author, author_headers = fx.create_author()
    first = fx.create_manuscript(journal["id"], author, author_headers)
    second = fx.create_manuscript(journal["id"], author, author_headers)
    fx.file_plagiarism_screening(first["id"], 5.0)
    fx.file_plagiarism_screening(second["id"], 5.0)
    assignment = fx.assign_editor(
        first["id"], chief_headers, editor_id=handling["id"]
    )
    fx.declare_no_conflict(assignment["id"], handling_headers)
    return {
        "journal": journal,
        "chief_headers": chief_headers,
        "handling": handling,
        "handling_headers": handling_headers,
        "author": author,
        "first": first,
        "second": second,
        "assignment": fx.get_assignment(assignment["id"]),
    }


def test_reviewer_at_the_authors_institution_is_refused():
    """A shared affiliation is a conflict of interest, not a matter of degree.

    PRD: "A reviewer is refused with `ERR_REVIEWER_CONFLICT` when their `email` equals the corresponding author's `email`, when their `email` appears among the manuscript's `coauthor_emails`, when their `affiliation` equals the corresponding author's `affiliation`, when they are the editor holding the manuscript's `ACTIVE` assignment, or when they already hold an open invitation on this same manuscript."

    Design: Corner/validations/review_invitation_rejected_for_shared_author_affiliation
    """
    world = _setup_reviewer_sharing_the_authors_affiliation()
    assert world["author"]["affiliation"] == world["reviewer"]["affiliation"]

    response = _invitation_request(
        world["manuscript"]["id"],
        world["handling_headers"],
        reviewer_id=world["reviewer"]["id"],
    )

    validate_error(
        response, ApiErrorId.ERR_REVIEWER_CONFLICT.value, expected_status=409
    )


def test_conflicted_invitation_writes_neither_row_nor_counter():
    """The conflict is answered before any invitation or tally exists.

    PRD: "Conflict of interest is checked before anything is written."

    Design: Corner/validations/review_invitation_rejected_for_shared_author_affiliation
    """
    world = _setup_reviewer_sharing_the_authors_affiliation()

    _invitation_request(
        world["manuscript"]["id"],
        world["handling_headers"],
        reviewer_id=world["reviewer"]["id"],
    )

    assert _count_invitations(world["manuscript"]["id"]) == 0
    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_fields(reviewer, invited_count=0, open_invitation_count=0)
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "UNDER_REVIEW"


def test_editor_at_their_ceiling_takes_no_further_manuscript():
    """One open assignment already equals a ceiling of one.

    PRD: "If that editor's `active_assignment_count` already equals their `max_concurrent_assignments`, or if the manuscript's `subject_area` is not among that editor's `subject_areas`, the request is refused with `ERR_EDITOR_WORKLOAD_EXCEEDED`."

    Design: Corner/validations/editor_assignment_rejected_when_workload_ceiling_reached
    """
    world = _setup_workload_saturated_editor()
    assert world["handling"]["max_concurrent_assignments"] == 1
    assert fx.get_editor(world["handling"]["id"])["active_assignment_count"] == 1

    response = _assignment_request(
        world["second"]["id"], world["chief_headers"], world["handling"]["id"]
    )

    validate_error(
        response, ApiErrorId.ERR_EDITOR_WORKLOAD_EXCEEDED.value, expected_status=409
    )


def test_refused_assignment_leaves_the_open_load_exactly_as_it_was():
    """The conserved open-load counter did not move, and no second assignment exists.

    PRD: "An editor's `active_assignment_count` rises by 1 when an assignment is created for that editor and falls by 1 when the assignment leaves the open set, so it always equals the count of that editor's assignments in state `PROPOSED` or `ACTIVE`."

    Design: Corner/validations/editor_assignment_rejected_when_workload_ceiling_reached
    """
    world = _setup_workload_saturated_editor()

    _assignment_request(
        world["second"]["id"], world["chief_headers"], world["handling"]["id"]
    )

    assert fx.get_editor(world["handling"]["id"])["active_assignment_count"] == 1
    assert fx.list_assignments(world["second"]["id"]) == []
    assert fx.get_manuscript(world["second"]["id"])["status"] == "SUBMITTED"
    assert fx.get_assignment(world["assignment"]["id"])["state"] == "ACTIVE"


def test_over_long_manuscript_cannot_be_advanced_to_review():
    """Forty pages against a thirty-page limit stops the desk call.

    PRD: "A manuscript advancing to review has `formatting_status` `COMPLIANT` — otherwise `ERR_FORMATTING_NON_COMPLIANT` (409), on the screening decision."

    Design: Corner/validations/advance_to_review_rejected_when_page_count_exceeds_limit
    """
    world = fx.setup_active_assignment(manuscript_overrides={"page_count": 40})
    assert world["journal"]["max_page_count"] == 30
    a.assert_fields(world["manuscript"], formatting_status="NON_COMPLIANT")

    response = _advance_request(world["manuscript"]["id"], world["handling_headers"])

    validate_error(
        response, ApiErrorId.ERR_FORMATTING_NON_COMPLIANT.value, expected_status=409
    )
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="SUBMITTED",
        formatting_status="NON_COMPLIANT",
        integrity_status="PASS",
    )
    assert fx.get_assignment(world["assignment"]["id"])["state"] == "ACTIVE"


def test_page_count_exactly_at_the_limit_is_compliant():
    """The at-most comparison includes the limit itself, so thirty pages advance.

    PRD: "Its `formatting_status` is computed immediately and is `COMPLIANT` only when all three of the following hold: the `page_count` is at most the journal's `max_page_count`, the `figure_count` is at most the journal's `max_figure_count`, and either the journal does not require a data availability statement or the manuscript's `data_availability_statement` is a non-empty string."

    Design: Corner/validations/advance_to_review_rejected_when_page_count_exceeds_limit
    """
    world = fx.setup_active_assignment(manuscript_overrides={"page_count": 30})
    a.assert_fields(world["manuscript"], page_count=30, formatting_status="COMPLIANT")

    validate_success(
        _advance_request(world["manuscript"]["id"], world["handling_headers"])
    )

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript, status="UNDER_REVIEW", formatting_status="COMPLIANT"
    )


def test_clean_manuscript_advances_and_clears_the_shortfall_flag():
    """Scope, formatting and integrity all clear, so the desk call goes through.

    PRD: "On success the manuscript moves `SUBMITTED → UNDER_REVIEW`, its `review_shortfall_flag` is set to false, and its `version` advances by 1."

    Design: Corner/validations/advance_to_review_passes_when_scope_formatting_and_integrity_all_clear
    """
    world = fx.setup_active_assignment()
    assert world["manuscript"]["subject_area"] in world["journal"]["subject_areas"]

    validate_success(
        _advance_request(world["manuscript"]["id"], world["handling_headers"])
    )

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="UNDER_REVIEW",
        formatting_status="COMPLIANT",
        integrity_status="PASS",
        review_shortfall_flag=False,
        submitted_review_count=0,
    )
    assert fx.get_assignment(world["assignment"]["id"])["state"] == "ACTIVE"


def test_zero_due_days_is_not_a_positive_integer():
    """A deadline on the day of invitation is no interval at all.

    PRD: "A `due_days` value that is not a positive integer, or any interval whose computed `due_at` would not be strictly after `invited_at`, is refused with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/review_invitation_rejected_for_non_positive_due_days
    """
    world = fx.setup_under_review_manuscript()
    reviewer, _headers = fx.create_reviewer()

    response = _invitation_request(
        world["manuscript"]["id"],
        world["handling_headers"],
        reviewer_id=reviewer["id"],
        due_days=0,
    )

    validate_error(
        response, ApiErrorId.ERR_INVALID_INTERVAL.value, expected_status=400
    )
    assert _count_invitations(world["manuscript"]["id"]) == 0
    a.assert_fields(
        fx.get_reviewer(reviewer["id"]), invited_count=0, open_invitation_count=0
    )


def test_one_due_day_is_the_shortest_legal_window():
    """A single day is strictly positive, so the deadline lands the next morning.

    PRD: "The created invitation is stamped with `round` equal to the manuscript's `revision_round`, `invited_at` equal to the current logical clock, and `due_at` equal to `invited_at` plus a number of days taken from `due_days` when supplied and from the journal's `review_target_days` otherwise."

    Design: Corner/validations/review_invitation_rejected_for_non_positive_due_days
    """
    world = fx.setup_under_review_manuscript()
    reviewer, _headers = fx.create_reviewer()

    invitation = validate_success(
        _invitation_request(
            world["manuscript"]["id"],
            world["handling_headers"],
            reviewer_id=reviewer["id"],
            due_days=1,
        ),
        expected_status=201,
    )

    a.assert_fields(
        invitation,
        round=0,
        state="INVITED",
        invited_at="2026-08-01T00:00:00.000Z",
        due_at="2026-08-02T00:00:00.000Z",
    )
