"""Role reach, editor level pairing, segregation of duties and genuinely shared routes."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ApiErrorId, api_client
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import SYSTEM_ADMIN_HEADERS, make_editor_in_chief_headers


def _setup_decision_ready_manuscript():
    """A manuscript at `DECISION_PENDING` holding the one review the journal demands."""
    return fx.setup_decision_pending(
        recommendations=("ACCEPT",),
        journal_overrides={"min_completed_reviews_for_decision": 1},
    )


def _setup_accepted_invitation():
    """A manuscript `UNDER_REVIEW` whose invited reviewer has accepted."""
    world = fx.setup_under_review_manuscript()
    reviewer, reviewer_headers = fx.create_reviewer()
    invitation = fx.invite_reviewer(
        world["manuscript"]["id"], world["handling_headers"], reviewer_id=reviewer["id"]
    )
    fx.accept_invitation(invitation["id"], reviewer_headers)
    world["reviewer"] = reviewer
    world["reviewer_headers"] = reviewer_headers
    world["invitation"] = fx.get_invitation(invitation["id"])
    return world


def _setup_committee_review_case_opened_by_the_chief():
    """A `MEDIUM` authorship-dispute case walked to `COMMITTEE_REVIEW` by its opener."""
    world = fx.setup_under_review_manuscript()
    case = fx.open_ethics_case(
        world["manuscript"]["id"],
        world["chief_headers"],
        case_type="AUTHORSHIP_DISPUTE",
        severity="MEDIUM",
        description="The second author disputes the authorship order.",
    )
    fx.advance_case_to_committee_review(case["id"], world["chief_headers"])
    world["case"] = fx.get_ethics_case(case["id"])
    return world


def test_author_cannot_issue_a_decision_on_their_own_manuscript():
    """Decisions are a handling-editor lever, closed to the corresponding author.

    PRD: "If the role is well-formed but is not among the roles authorised for the addressed endpoint, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/author_cannot_issue_an_editorial_decision
    """
    world = _setup_decision_ready_manuscript()

    response = api_client.create_decision(
        world["manuscript"]["id"],
        f.decision_payload(
            editorial_note="I accept my own paper.", category="ACCEPT"
        ),
        world["author_headers"],
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_refused_author_decision_writes_no_decision_row():
    """The role refusal runs before any state or review-count effect.

    PRD: "`HandlingEditor` alone issues screening decisions, declares conflicts on its own assignment, creates and withdraws review invitations, and issues editorial decisions; recusal is shared between `HandlingEditor` and `EditorInChief`."

    Design: Corner/rbac/author_cannot_issue_an_editorial_decision
    """
    world = _setup_decision_ready_manuscript()

    validate_error(
        api_client.create_decision(
            world["manuscript"]["id"],
            f.decision_payload(editorial_note="I accept my own paper."),
            world["author_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    a.assert_fields(
        fx.get_manuscript(world["manuscript"]["id"]),
        status="DECISION_PENDING",
        decision_count=0,
        submitted_review_count=1,
    )
    decisions = get_success_data(
        api_client.list_decisions(
            SYSTEM_ADMIN_HEADERS, params={"manuscript_id": world["manuscript"]["id"]}
        )
    )
    assert decisions == [], f"Expected no decision row, got {decisions!r}"


def test_reviewer_cannot_withdraw_their_own_invitation():
    """Withdrawal is editorial: the invited reviewer may answer it but not retract it.

    PRD: "If the role is well-formed but is not among the roles authorised for the addressed endpoint, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/reviewer_cannot_withdraw_their_own_invitation
    """
    world = _setup_accepted_invitation()

    response = api_client.withdraw_invitation(
        world["invitation"]["id"],
        f.withdraw_payload(reason="I would rather not."),
        world["reviewer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    invitation = fx.get_invitation(world["invitation"]["id"])
    a.assert_fields(invitation, state="ACCEPTED")
    assert invitation.get("closed_reason") is None, (
        "an open invitation carries no closed_reason"
    )


def test_refused_withdrawal_does_not_release_the_reviewers_open_load():
    """The reviewer's open count only falls when the invitation really closes.

    PRD: "A reviewer's `open_invitation_count` rises by 1 when an invitation is created and falls by 1 whenever that invitation closes — by decline, by sweep expiry, by review submission or by withdrawal — so it always equals the count of that reviewer's invitations in state `INVITED` or `ACCEPTED`."

    Design: Corner/rbac/reviewer_cannot_withdraw_their_own_invitation
    """
    world = _setup_accepted_invitation()

    validate_error(
        api_client.withdraw_invitation(
            world["invitation"]["id"],
            f.withdraw_payload(reason="I would rather not."),
            world["reviewer_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    assert reviewer["open_invitation_count"] == 1
    a.assert_score_equals(reviewer["reliability_score_rolling"], 50.00)


def test_handling_level_editor_acting_as_chief_is_refused_on_level_mismatch():
    """Role and role_level are checked as a pair, with their own error id.

    PRD: "Acting as `EditorInChief` on an `Editor` row whose `role_level` is `HANDLING`, or acting as `HandlingEditor` on an `Editor` row whose `role_level` is `CHIEF`, is rejected with `ERR_EDITOR_LEVEL_MISMATCH` (HTTP 403); so is an editor acting on a manuscript whose owning journal differs from the `journal_id` on that editor's row."

    Design: Corner/rbac/handling_level_editor_acting_as_editor_in_chief_rejected
    """
    world = fx.setup_submitted_manuscript()
    fx.file_plagiarism_screening(world["manuscript"]["id"], 5.0)
    handling = world["handling"]

    response = api_client.create_editor_assignment(
        f.editor_assignment_payload(
            world["manuscript"]["id"],
            fx.get_manuscript_version(world["manuscript"]["id"]),
            editor_id=handling["id"],
        ),
        make_editor_in_chief_headers(handling["id"]),
    )

    error = validate_error(response, ApiErrorId.ERR_EDITOR_LEVEL_MISMATCH.value)
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
        "the endpoint does list EditorInChief, so this is a level mismatch"
    )
    assert fx.get_editor(handling["id"])["role_level"] == "HANDLING"


def test_level_mismatch_creates_no_editor_assignment():
    """A refused assignment leaves neither a row nor a raised workload counter.

    PRD: "An editor's `active_assignment_count` rises by 1 when an assignment is created for that editor and falls by 1 when the assignment leaves the open set, so it always equals the count of that editor's assignments in state `PROPOSED` or `ACTIVE`."

    Design: Corner/rbac/handling_level_editor_acting_as_editor_in_chief_rejected
    """
    world = fx.setup_submitted_manuscript()
    fx.file_plagiarism_screening(world["manuscript"]["id"], 5.0)
    handling = world["handling"]

    validate_error(
        api_client.create_editor_assignment(
            f.editor_assignment_payload(
                world["manuscript"]["id"],
                fx.get_manuscript_version(world["manuscript"]["id"]),
                editor_id=handling["id"],
            ),
            make_editor_in_chief_headers(handling["id"]),
        ),
        ApiErrorId.ERR_EDITOR_LEVEL_MISMATCH.value,
    )

    assignments = fx.list_assignments(world["manuscript"]["id"])
    assert assignments == [], f"Expected no assignment row, got {assignments!r}"
    assert fx.get_editor(handling["id"])["active_assignment_count"] == 0


def test_case_opener_cannot_resolve_their_own_ethics_case():
    """Segregation of duties is enforced on identity, not on role or state.

    PRD: "Resolution happens only from `COMMITTEE_REVIEW`, carries a `resolution` and a `resolution_statement` — the text published alongside the outcome — and is barred to the editor who opened the case, an acting `X-User-ID` matching the opener being refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/chief_editor_cannot_resolve_the_ethics_case_they_opened
    """
    world = _setup_committee_review_case_opened_by_the_chief()

    response = api_client.resolve_ethics_case(
        world["case"]["id"],
        f.ethics_case_resolution_payload(
            "NO_ACTION", resolution_statement="No further action is needed."
        ),
        world["chief_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    a.assert_fields(
        fx.get_ethics_case(world["case"]["id"]), state="COMMITTEE_REVIEW"
    )


def test_refused_resolution_leaves_the_case_unresolved():
    """No resolution statement is stored and no resolution instant is stamped.

    PRD: "Every resolution sets `resolved_at` to the current clock instant, stores the `resolution_statement`, and raises the case's `version` by 1."

    Design: Corner/rbac/chief_editor_cannot_resolve_the_ethics_case_they_opened
    """
    world = _setup_committee_review_case_opened_by_the_chief()

    validate_error(
        api_client.resolve_ethics_case(
            world["case"]["id"],
            f.ethics_case_resolution_payload("NO_ACTION"),
            world["chief_headers"],
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    case = fx.get_ethics_case(world["case"]["id"])
    assert case.get("resolution_statement") is None, (
        "a refused resolution must not publish its statement"
    )
    assert case.get("resolved_at") is None
    a.assert_fields(case, opened_by="MANUAL")


def test_integrity_screening_is_shared_by_the_office_and_the_handling_editor():
    """Both listed roles file evidence on the same manuscript and the same round.

    PRD: "A screening is filed against the manuscript by the handling editor or by the editorial office and carries a `scan_type` of either `PLAGIARISM` or `IMAGE_FORENSICS`."

    Design: Corner/rbac/integrity_screening_accepted_from_both_system_admin_and_handling_editor
    """
    world = fx.setup_submitted_manuscript(manuscript_overrides={"figure_count": 4})
    manuscript_id = world["manuscript"]["id"]

    by_office = fx.file_plagiarism_screening(manuscript_id, 5.0)
    by_editor = fx.file_image_forensics_screening(
        manuscript_id, 1, headers=world["handling_headers"]
    )

    a.assert_fields(by_office, scan_type="PLAGIARISM", verdict="PASS", round=0)
    a.assert_fields(by_editor, scan_type="IMAGE_FORENSICS", verdict="FLAG", round=0)


def test_repeat_scan_type_in_the_same_round_collides_whoever_files_it():
    """The uniqueness key is manuscript, round and scan type together.

    PRD: "The server stamps the screening's `round` with the manuscript's current `revision_round`, and only one screening of each `scan_type` may exist per manuscript per round; a second one collides with `ERR_DUPLICATE_KEY`."

    Design: Corner/rbac/integrity_screening_accepted_from_both_system_admin_and_handling_editor
    """
    world = fx.setup_submitted_manuscript(manuscript_overrides={"figure_count": 4})
    manuscript_id = world["manuscript"]["id"]
    fx.file_plagiarism_screening(manuscript_id, 5.0)
    fx.file_image_forensics_screening(
        manuscript_id, 1, headers=world["handling_headers"]
    )

    response = api_client.create_integrity_screening(
        manuscript_id,
        f.plagiarism_screening_payload(1.0),
        world["handling_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value)
    screenings = fx.list_integrity_screenings(manuscript_id)
    assert len(screenings) == 2, (
        f"Expected the two accepted scans only, got {len(screenings)}"
    )


def test_shared_screenings_roll_up_to_the_worse_of_the_two_verdicts():
    """A PASS from one role and a FLAG from the other roll up to FLAG.

    PRD: "Otherwise the worst verdict wins, in the severity order `BLOCK` above `FLAG` above `PASS`: if any current-round screening is `BLOCK`, the rollup is `BLOCK`; failing that, if any is `FLAG`, the rollup is `FLAG`; otherwise it is `PASS`."

    Design: Corner/rbac/integrity_screening_accepted_from_both_system_admin_and_handling_editor
    """
    world = fx.setup_submitted_manuscript(manuscript_overrides={"figure_count": 4})
    manuscript_id = world["manuscript"]["id"]

    fx.file_plagiarism_screening(manuscript_id, 5.0)
    fx.file_image_forensics_screening(
        manuscript_id, 1, headers=world["handling_headers"]
    )

    a.assert_fields(
        fx.get_manuscript(manuscript_id), integrity_status="FLAG", status="SUBMITTED"
    )
