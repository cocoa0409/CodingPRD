"""Self-audition intake: branching state machine, duplicate guard, and the
CASTING-state dependency of shortlist/reject."""
from test_helpers import (
    ApiErrorId,
    assert_self_audition,
    create_cast_project,
    create_casting_project,
    create_client,
    create_project,
    create_talent,
    make_client_headers,
    open_casting,
    select_talent,
    submit_audition,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CD, get_audition


class TestAuditionBranching:
    def test_shortlisted_audition_selected_and_sibling_auto_rejected(self, api):
        """PRD §3.4: "The chosen audition advances to `SELECTED`, while every
        sibling audition on the same project still sitting in `SUBMITTED` or
        `SHORTLISTED` is moved to `REJECTED`."

        Design: Difficulty/non_linear_state_machine/self_audition_branching_shortlist_or_reject
        """
        client = create_client()
        t1, t2, t3 = create_talent(), create_talent(), create_talent()
        project = create_project(client)
        open_casting(project["id"])
        a1 = submit_audition(project["id"], t1)
        a2 = submit_audition(project["id"], t2)
        a3 = submit_audition(project["id"], t3)

        resp = api.shortlist_audition(a1["id"], make_client_headers(client["id"]))
        shortlisted = validate_success(resp, expected_status=200)
        assert shortlisted["status"] == "SHORTLISTED"

        select_talent(project, a1)
        assert get_audition(a1["id"])["status"] == "SELECTED"
        assert get_audition(a2["id"])["status"] == "REJECTED"
        assert get_audition(a3["id"])["status"] == "REJECTED"

    def test_shortlisted_audition_can_still_be_rejected(self, api):
        """PRD §3.3: "Shortlisting moves an audition `SUBMITTED → SHORTLISTED`,
        and rejecting moves an audition from either `SUBMITTED` or
        `SHORTLISTED` to `REJECTED`."

        Design: Difficulty/non_linear_state_machine/self_audition_branching_shortlist_or_reject
        """
        ctx = create_casting_project()
        client, audition = ctx["client"], ctx["audition"]
        headers = make_client_headers(client["id"])
        validate_success(api.shortlist_audition(audition["id"], headers),
                         expected_status=200)
        resp = api.reject_audition(audition["id"], headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "REJECTED"
        assert get_audition(audition["id"])["status"] == "REJECTED"


class TestAuditionIntakeRules:
    def test_duplicate_audition_per_talent_project_returns_duplicate(self, api):
        """PRD §3.3: "Each artist may audition at most once per project: a
        second submission for the same `(project_id, talent_id)` pair is
        rejected with `ERR_DUPLICATE`."

        Design: Corner/validations/duplicate_audition_per_talent_project_returns_duplicate
        """
        ctx = create_casting_project()
        talent, project = ctx["talent"], ctx["project"]
        resp = api.submit_self_audition(
            project["id"],
            {"talent_id": talent["id"],
             "audio_file_url": "https://files.example.com/second.mp3"},
            __import__("test_helpers").make_talent_headers(talent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestAuditionProjectStateDependency:
    def test_shortlist_rejected_after_project_cast(self, api):
        """PRD §3.3: "Both actions are `Client`-only, require the project to
        still be in `CASTING` (otherwise `ERR_INVALID_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/audition_shortlist_depends_on_project_casting
        """
        client = create_client()
        t1, t2 = create_talent(), create_talent()
        project = create_project(client)
        open_casting(project["id"])
        a1 = submit_audition(project["id"], t1)
        a2 = submit_audition(project["id"], t2)
        select_talent(project, a1)  # project now CAST; a2 auto-REJECTED

        resp = api.shortlist_audition(a2["id"], make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_shortlist_selected_audition_after_cast_rejected(self, api):
        """PRD §3.3: "Both actions are `Client`-only, require the project to
        still be in `CASTING` (otherwise `ERR_INVALID_STATE`)". PRD §3.3:
        "`REJECTED` and `SELECTED` are the audition's terminal states."

        Design: Difficulty/cross_entity_state_dependency/audition_shortlist_depends_on_project_casting
        """
        ctx = create_cast_project()
        resp = api.shortlist_audition(
            ctx["audition"]["id"], make_client_headers(ctx["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
