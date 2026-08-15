"""Project wrap/close/archive lifecycle and the depth-3 wrap cascade."""

from test_helpers import (
    ApiErrorId, create_archive_job, create_review_note, create_review_round,
    seal_archive_job, setup_active_project, setup_conform_ready_project,
    setup_published_dailies, create_deliverable, render_deliverable,
    validate_error, validate_success,
)
from test_helpers.test_users import (
    make_dailies_coordinator_headers, make_media_manager_headers,
    make_post_supervisor_headers, make_reviewer_lead_headers,
)

PS = make_post_supervisor_headers()
MM = make_media_manager_headers()
DC = make_dailies_coordinator_headers()
RL = make_reviewer_lead_headers()


class TestWrapCascade:
    def test_project_wrap_cascade_depth3(self, api):
        """PRD §3.8: "The cascade is substantial: every dailies package still
        `PUBLISHED` transitions to `REVOKED` as the dailies window closes, each
        revocation voids every `OPEN` review round targeting the package, and
        each voided round in turn voids its `OPEN` notes."
        PRD §3.6: "a round still `OPEN` is voided automatically — moving to
        `VOID` — when the dailies package it targets is revoked or the turnover
        it targets is voided; voiding a round voids every note still `OPEN`
        inside it."

        Design: Difficulty/transitive_cascade/project_wrap_cascade_depth3
        """
        project, _batch, _assets, pkg = setup_published_dailies(
            project_overrides={"title": "PW", "client_code": "CL007",
                               "storage_quota_gb": 100})
        rr = create_review_round(project["id"], "DAILIES", pkg["id"],
                                 round_label="RR-01")
        note = create_review_note(project["id"], rr["id"], severity="MINOR",
                                  body="check slate")
        # Wrap precondition: at least one SEALED archive job is NOT required for
        # wrap (that gates close), but deliverables/review-round/change-list
        # preconditions must hold — none exist here beyond the DAILIES round.
        seal_archive_job(project["id"],
                         create_archive_job(project["id"])["id"])
        resp = api.wrap_project(project["id"], PS)
        wrapped = validate_success(resp)
        assert wrapped["status"] == "WRAPPING"
        pkg_after = validate_success(api.get_dailies_package(project["id"], pkg["id"], DC))
        assert pkg_after["status"] == "REVOKED", (
            f"Wrap must revoke PUBLISHED dailies packages; got {pkg_after['status']}")
        rr_after = validate_success(api.get_review_round(project["id"], rr["id"], RL))
        assert rr_after["status"] == "VOID", (
            f"Revocation must void OPEN review rounds targeting the package; "
            f"got {rr_after['status']}")
        note_after = validate_success(api.get_review_note_flat(note["id"], RL))
        assert note_after["status"] == "VOID", (
            f"Voiding a round must void its OPEN notes; got {note_after['status']}")

    def test_project_wrap_cascade_revoked_at_stamped(self, api):
        """PRD §3.3: "Either way the package moves to `REVOKED` — its terminal
        state — `revoked_at` is set from the logical clock, and every review
        round still `OPEN` whose `target_ref_id` names the package transitions
        to `VOID`."
        PRD §3.8: "every dailies package still `PUBLISHED` transitions to
        `REVOKED` as the dailies window closes".

        Design: Difficulty/transitive_cascade/project_wrap_cascade_depth3
        """
        project, _batch, _assets, pkg = setup_published_dailies(
            project_overrides={"title": "PW", "client_code": "CL007",
                               "storage_quota_gb": 100})
        create_review_round(project["id"], "DAILIES", pkg["id"],
                            round_label="RR-01")
        seal_archive_job(project["id"], create_archive_job(project["id"])["id"])
        api.wrap_project(project["id"], PS)
        pkg_after = validate_success(api.get_dailies_package(project["id"], pkg["id"], DC))
        assert pkg_after["status"] == "REVOKED"
        assert pkg_after["revoked_at"] is not None, (
            "revoked_at must be stamped from the logical clock on revoke")


class TestWrappabilityGate:
    def test_error_project_not_wrappable_trigger(self, api):
        """PRD §3.8: "Wrapping moves the project from `ACTIVE` to `WRAPPING`.
        Three conditions must hold: every deliverable of the project is in
        `DELIVERED`, `REJECTED`, or `SUPERSEDED`; ..."
        PRD §2.9 item 20: "The project wrap, close, and archive preconditions are
        enforced last; failures yield `ERR_PROJECT_NOT_WRAPPABLE` (HTTP 422)."

        Design: Corner/errors/error_project_not_wrappable_trigger
        """
        project, _batch, _asset, _turnover, _vendor, _bid = setup_conform_ready_project(
            project_overrides={"title": "P", "client_code": "CL602",
                               "storage_quota_gb": 100})
        deliverable = create_deliverable(project["id"], requires_qc=False)
        # Drive deliverable into RENDERING — not a terminal deliverable state.
        render_deliverable(project["id"], deliverable["id"])
        resp = api.wrap_project(project["id"], PS)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_WRAPPABLE)


class TestInvalidTransitions:
    def test_project_archive_from_active_returns_invalid_state(self, api):
        """PRD §3.1: "Its full lifecycle is `SETUP` → `ACTIVE` → `WRAPPING` →
        `CLOSED` → `ARCHIVED`, with `ARCHIVED` terminal."
        PRD §2.9 item 6: "The target resource must currently be in the from-state
        required by the requested transition; otherwise `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/project_archive_from_active_returns_invalid_state
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P", "client_code": "CL200", "storage_quota_gb": 10})
        resp = api.archive_project(project["id"], PS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
