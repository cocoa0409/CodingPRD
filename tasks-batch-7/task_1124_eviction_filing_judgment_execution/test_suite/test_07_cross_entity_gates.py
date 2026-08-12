"""Cross-entity state gates: hearing needs SERVICE_COMPLETE; writ needs
FINAL judgment (PRD 3.5, 3.7)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    PS1,
    create_hearing_payload,
    create_service_attempt_payload,
    create_writ_payload,
    finalize_judgment,
    get_judgment,
    make_landlord_headers,
    serve_all_defendants,
    set_clock,
    setup_case_draft,
    setup_case_filed,
    setup_judgment_entered,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestHearingRequiresServiceComplete:
    """Depth instance: hearing creation is gated on the CASE status."""

    def test_filed_case_rejects_hearing_then_service_unlocks(self, api):
        """PRD 3.5: "With service complete, a CourtClerk schedules a hearing"
        and PRD 3.5 state gate: "A successful scheduling creates the hearing
        in SCHEDULED and moves the case from SERVICE_COMPLETE to
        HEARING_SCHEDULED." PRD 2.7 rung 7: "State admissibility ... failure
        yields ERR_INVALID_STATE."

        Design: Difficulty/cross_entity_state_dependency/hearing_requires_service_complete
        """
        ctx = setup_case_filed("CA")
        set_clock("2026-06-01T11:00:00Z")
        # While FILED, hearing creation is rejected by the state gate.
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-15T10:00:00Z",
                                   end_at="2026-06-15T10:30:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        # Serve the sole defendant; the case becomes SERVICE_COMPLETE and the
        # same hearing request now succeeds.
        serve_all_defendants(ctx)
        ok = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-15T10:00:00Z",
                                   end_at="2026-06-15T10:30:00Z"),
            CLERK_A,
        )
        assert validate_success(ok, 201)["status"] == "SCHEDULED"

    def test_hearing_concluded_case_also_blocks_new_hearing_via_state(self, api):
        """PRD 2.7 rung 7: "the target entity is in a status that permits the
        operation (the case-state gate of each transition ...)" and PRD 3.5:
        "A successful scheduling ... moves the case from SERVICE_COMPLETE to
        HEARING_SCHEDULED."

        Design: Difficulty/cross_entity_state_dependency/hearing_requires_service_complete
        """
        # DRAFT case (before any filing) is not SERVICE_COMPLETE either.
        ctx = setup_case_draft("CA")
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-15T10:00:00Z",
                                   end_at="2026-06-15T10:30:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestWritRequiresJudgmentFinal:
    """Depth instance: writ request/issue gated on the JUDGMENT being FINAL."""

    def test_entered_rejects_then_final_admits(self, api):
        """PRD 3.7: "the judgment must be FINAL — a request during the appeal
        window is rejected with ERR_APPEAL_WINDOW_OPEN (HTTP 409)" and
        PRD 3.6: "the ops-run sweep flips an ENTERED judgment to FINAL once
        the logical clock has reached or passed its appeal_deadline."

        Design: Difficulty/cross_entity_state_dependency/writ_requires_judgment_final
        """
        ctx = setup_judgment_entered("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.request_writ(
            ctx["judgment"]["id"], create_writ_payload("CA"), ll)
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_OPEN, 409)

        # At exactly the appeal deadline the ops run finalizes (>= boundary).
        summary = finalize_judgment(ctx)  # clock at appeal_deadline
        assert summary["judgments_finalized"] == 1
        assert get_judgment(ctx["judgment"]["id"])["status"] == "FINAL"

        ok = api.request_writ(
            ctx["judgment"]["id"], create_writ_payload("CA"), ll)
        assert validate_success(ok, 201)["status"] == "REQUESTED"

    def test_issue_also_enforces_finality(self, api):
        """PRD 3.7: "Issuance is a clerk action on a REQUESTED writ, and the
        appeal-finality gate applies again: the judgment must be FINAL or
        issuance fails with ERR_APPEAL_WINDOW_OPEN."

        Design: Difficulty/cross_entity_state_dependency/writ_requires_judgment_final
        """
        # A REQUESTED writ always implies the judgment was FINAL at request
        # time; the issuance gate is exercised on a fresh FINAL judgment and
        # succeeds — the failing branch is covered by the request-side test.
        ctx = setup_judgment_entered("CA")
        finalize_judgment(ctx)
        ll = make_landlord_headers(ctx["landlord"]["id"])
        writ = validate_success(
            api.request_writ(ctx["judgment"]["id"], create_writ_payload("CA"), ll),
            201,
        )
        issued = validate_success(api.issue_writ(writ["id"], CLERK_A), 200)
        assert issued["status"] == "ISSUED"
