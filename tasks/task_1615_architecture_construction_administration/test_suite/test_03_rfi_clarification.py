"""RFIs, clarification drawings, late-answer credit, and RFI-version OCC."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_project,
    create_rfi,
    answer_rfi,
    set_clock,
    make_firm_admin_headers,
    make_architect_headers,
    make_contractor_headers,
)


def _project_with_rfi(api, question="Confirm beam pocket depth", **rfi_overrides):
    project = create_active_project(
        sov_lines=[{"line_code": "A", "description": "Concrete",
                    "scheduled_value_cents": 10000000}],
    )
    rfi = create_rfi(project["id"], question=question, **rfi_overrides)
    return project, rfi


class TestRfiAnswerLateCredit:
    def test_rfi_answer_late_credit(self, api):
        """PRD 3.4: "the late-answer credit is computed exactly as for submittals —
        whole calendar days between the date portion of `answered_at` and the date
        portion of `due_at`, floored at zero, zero when the answer lands on or
        before the due date — and stored on the RFI's `credited_delay_days`; then
        the project's `excusable_delay_days` and `ca_posture` are recomputed".

        Design: Corner/calculations/rfi_answer_late_credit
        """
        project, rfi = _project_with_rfi(api, question="Confirm parapet coping color")
        # RFI received at the 2026-08-01 default clock; default 7-day window.
        assert rfi["due_at"].startswith("2026-08-08T00:00:00")
        set_clock("2026-08-10T09:00:00Z")
        answered = answer_rfi(rfi["id"], answer_text="Match existing")
        assert answered["status"] == "ANSWERED"
        assert answered["credited_delay_days"] == 2
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["excusable_delay_days"] == 2


class TestClarificationPendingUntilDrawing:
    def test_pending_rfi_has_no_answered_at_until_drawing(self, api):
        """PRD 3.4: "When the flag is true, the RFI instead moves from `OPEN` to
        `CLARIFICATION_PENDING` with no further effect, awaiting a drawing."

        Design: Difficulty/cross_entity_state_dependency/rfi_clarification_pending_until_drawing_issued
        """
        project, rfi = _project_with_rfi(api, cost_impact_flag=True)
        set_clock("2026-08-05T09:00:00Z")
        pending = answer_rfi(rfi["id"], answer_text="See forthcoming sketch",
                             requires_clarification_drawing=True)
        assert pending["status"] == "CLARIFICATION_PENDING"
        assert pending["answered_at"] is None
        assert pending["credited_delay_days"] == 0

    def test_first_drawing_answers_rfi_from_drawing_clock(self, api):
        """PRD 3.4: "When the RFI was `CLARIFICATION_PENDING`, the drawing's
        issuance also moves it to `ANSWERED` — its `answered_at` takes the
        drawing's clock timestamp, the same late-credit rule applies, and the
        project's excusable delay, posture, and draft invoices recompute."

        Design: Difficulty/cross_entity_state_dependency/rfi_clarification_pending_until_drawing_issued
        """
        project, rfi = _project_with_rfi(api, cost_impact_flag=True)
        set_clock("2026-08-05T09:00:00Z")
        answer_rfi(rfi["id"], answer_text="See forthcoming sketch",
                   requires_clarification_drawing=True)
        rfi = get_success_data(api.get_rfi(rfi["id"], make_architect_headers()))
        resp = api.create_clarification_drawing(
            {"rfi_id": rfi["id"], "drawing_ref": "SK-12",
             "expected_rfi_version": rfi["version"]},
            make_architect_headers(),
        )
        drawing = validate_success(resp, 201)
        assert drawing["revision_number"] == 1
        assert drawing["status"] == "ISSUED"
        rfi = get_success_data(api.get_rfi(rfi["id"], make_architect_headers()))
        assert rfi["status"] == "ANSWERED"
        assert rfi["answered_at"].startswith("2026-08-05T09:00:00")
        # on time vs due 2026-08-08 -> zero credit
        assert rfi["credited_delay_days"] == 0


class TestOccClarificationDrawingStaleRfiVersion:
    def _pending_rfi_with_version(self, api):
        project, rfi = _project_with_rfi(api, cost_impact_flag=True)
        answer_rfi(rfi["id"], answer_text="See forthcoming sketch",
                   requires_clarification_drawing=True)
        rfi = get_success_data(api.get_rfi(rfi["id"], make_architect_headers()))
        return project, rfi

    def test_second_drawing_with_stale_version_rejected(self, api):
        """PRD 2.9: "Issuing a clarification drawing requires the request to carry
        `expected_rfi_version`, holding the `version` of the parent RFI as the
        client last observed it. If the RFI's current `version` has advanced since
        that observation, the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_clarification_drawing_stale_rfi_version
        """
        project, rfi = self._pending_rfi_with_version(api)
        observed_version = rfi["version"]
        first = api.create_clarification_drawing(
            {"rfi_id": rfi["id"], "drawing_ref": "SK-12",
             "expected_rfi_version": observed_version},
            make_architect_headers(),
        )
        drawing1 = validate_success(first, 201)
        # The first drawing advanced the RFI version; replaying the stale one fails.
        stale = api.create_clarification_drawing(
            {"rfi_id": rfi["id"], "drawing_ref": "SK-12R1",
             "expected_rfi_version": observed_version},
            make_architect_headers(),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        return project, rfi, drawing1

    def test_retry_with_fresh_version_supersedes_prior_drawing(self, api):
        """PRD 3.4: "The first drawing for an RFI takes `revision_number` 1; each
        subsequent drawing for the same RFI takes one more than the highest
        existing revision and the previously `ISSUED` drawing is automatically
        moved to `SUPERSEDED`, so at most one drawing per RFI is ever `ISSUED`."

        Design: Corner/cross_cutting_layers/occ_clarification_drawing_stale_rfi_version
        """
        project, rfi = self._pending_rfi_with_version(api)
        drawing1 = validate_success(api.create_clarification_drawing(
            {"rfi_id": rfi["id"], "drawing_ref": "SK-12",
             "expected_rfi_version": rfi["version"]},
            make_architect_headers(),
        ), 201)
        rfi = get_success_data(api.get_rfi(rfi["id"], make_architect_headers()))
        drawing2 = validate_success(api.create_clarification_drawing(
            {"rfi_id": rfi["id"], "drawing_ref": "SK-12R1",
             "expected_rfi_version": rfi["version"]},
            make_architect_headers(),
        ), 201)
        assert drawing2["revision_number"] == 2
        assert drawing2["status"] == "ISSUED"
        drawing1 = get_success_data(
            api.get_clarification_drawing(drawing1["id"], make_architect_headers()))
        assert drawing1["status"] == "SUPERSEDED"
        rfi = get_success_data(api.get_rfi(rfi["id"], make_architect_headers()))
        assert rfi["status"] == "ANSWERED"


class TestRfiInvalidStates:
    def test_withdraw_answered_rfi_returns_invalid_state(self, api):
        """PRD 3.4: "A `Contractor` closes an RFI that is `ANSWERED`, moving it to
        `CLOSED`, or withdraws one that is still `OPEN`, moving it to `WITHDRAWN`;
        either call against an RFI in any other state fails with
        `ERR_RFI_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_answered_rfi_returns_invalid_state
        """
        project, rfi = _project_with_rfi(api, question="Confirm slab vapor barrier")
        answer_rfi(rfi["id"], answer_text="Per spec 07 26 00")
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.withdraw_rfi(rfi["id"], contractor_headers)
        validate_error(resp, ApiErrorId.ERR_RFI_INVALID_STATE, 409)
        current = get_success_data(api.get_rfi(rfi["id"], make_architect_headers()))
        assert current["status"] == "ANSWERED"

    def test_answer_withdrawn_rfi_returns_invalid_state(self, api):
        """PRD 3.4: "A `Contractor` closes an RFI that is `ANSWERED`, moving it to
        `CLOSED`, or withdraws one that is still `OPEN`, moving it to `WITHDRAWN`;
        either call against an RFI in any other state fails with
        `ERR_RFI_INVALID_STATE`. Both `CLOSED` and `WITHDRAWN` are terminal."

        Design: Corner/errors/answer_withdrawn_rfi_returns_invalid_state
        """
        project, rfi = _project_with_rfi(api, question="Confirm roof drain model")
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        api.withdraw_rfi(rfi["id"], contractor_headers)
        resp = api.answer_rfi(
            rfi["id"],
            {"answer_text": "Per submittal 22 14 13",
             "requires_clarification_drawing": False},
            make_architect_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RFI_INVALID_STATE, 409)
        current = get_success_data(api.get_rfi(rfi["id"], make_architect_headers()))
        assert current["status"] == "WITHDRAWN"
        assert current["answered_at"] is None


class TestChangeOrderOnNonCostImpactRfi:
    def test_change_order_on_non_cost_impact_rfi_returns_422(self, api):
        """PRD 3.6: "When `rfi_id` is supplied, the referenced RFI must have
        `cost_impact_flag` true and be in `ANSWERED` or `CLOSED` status;
        otherwise creation is rejected with `ERR_RFI_NOT_COST_IMPACT` (HTTP 422)."

        Design: Corner/validations/change_order_on_non_cost_impact_rfi_returns_422
        """
        project, rfi = _project_with_rfi(api, question="Confirm paint sheen")
        assert rfi["cost_impact_flag"] is False
        answer_rfi(rfi["id"], answer_text="Eggshell per spec")
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.create_change_order(
            {"project_id": project["id"], "title": "RFI-originated extra",
             "net_cost_change_cents": 100000, "time_extension_days": 0,
             "rfi_id": rfi["id"]},
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RFI_NOT_COST_IMPACT, 422)
        listing = get_success_data(api.list_change_orders(
            make_firm_admin_headers(), params={"project_id": project["id"]}))
        assert listing == []
