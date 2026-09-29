"""Requests that violate two rules at once, where the ladder decides which is reported."""
import pytest

from test_helpers import fixtures as fx, parse_instant, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    change_order_decision_payload,
    change_order_payload,
    disclosure_response_payload,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    LSP_DRAFTER,
    PROJECT_COORDINATOR,
    make_homeowner_headers,
)


def _over_ceiling_change_order_on_a_reopened_project(api):
    """A submitted change order far past the ceiling, on a project sent back to sampling.

    The order asks for 100.0 extra cubic yards against a 40.0-cubic-yard ceiling, so
    the fiscal rung would refuse it; retracting the result then puts the project back
    in SAMPLING, so the state rung would refuse it too.
    """
    ctx = fx.project_remediation_active_gross()
    ctx["change_order"] = fx.submitted_change_order(ctx, 100.0, 1200, "HAZARDOUS")
    fx.retract_result(ctx["sample"]["id"], ctx["laboratory"]["id"])
    return ctx


class TestProjectStateBeatsExcavationCeiling:
    def test_reopened_project_state_is_reported_ahead_of_the_excavation_ceiling(
        self, api
    ):
        """PRD §2.11: "9. **State legality** — the target resource, and the project behind it, must be in a state from which the requested operation is declared. For project-targeted operations the code is `ERR_PROJECT_STATE_INVALID` (409); for other targets the entity-specific state code is used — `ERR_DISCLOSURE_STATE_INVALID`, `ERR_PERMIT_STATE_INVALID`, `ERR_WORK_ORDER_STATE_INVALID`, `ERR_SAMPLE_STATE_INVALID`, `ERR_CHANGE_ORDER_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID` or `ERR_NFA_STATE_INVALID`, each HTTP 409. Applies to every action endpoint."
        PRD §2.11: "14. **Fiscal ceilings**, in this internal order: `ERR_EXCAVATION_LIMIT_EXCEEDED` (409), then `ERR_CLAIM_NOT_ELIGIBLE` (409)."
        PRD §3.7: "**Approval** additionally requires the project to be in `REMEDIATION_ACTIVE`, re-checks that any named `supersedes_change_order_id` still points at an `APPROVED` row on the same project — a target that has moved on is refused with `ERR_SUPERSEDE_TARGET_INVALID` at decision time exactly as it would be at draft time — and enforces the excavation ceiling."

        Design: Difficulty/priority_pair_validation_conflict/project_state_beats_excavation_limit_on_change_order_approval
        """
        ctx = _over_ceiling_change_order_on_a_reopened_project(api)

        response = api.decide_change_order(
            ctx["change_order"]["id"],
            change_order_decision_payload("APPROVED"),
            COMPLIANCE_OFFICER,
        )
        error_id = validate_error(
            response, ApiErrorId.ERR_PROJECT_STATE_INVALID.value, 409
        )["error_id"]
        assert error_id != ApiErrorId.ERR_EXCAVATION_LIMIT_EXCEEDED.value, (
            "the fiscal ceiling sits four rungs below state legality, so it must not "
            "be the reported code"
        )

    def test_refused_approval_leaves_the_order_and_the_scope_untouched(self, api):
        """PRD §3.7: "On success the row transitions `SUBMITTED → APPROVED`, `approved_by_user_id` is set from `X-User-ID`, `decided_at` is stamped from the logical clock, and `line_amount_cents` is computed."
        PRD §3.6: "The project is then walked backwards to `SAMPLING` from whichever of the three post-assessment states it occupied — `ASSESSED → SAMPLING`, `CLEARED → SAMPLING` or `REMEDIATION_ACTIVE → SAMPLING` — with `contamination_class` reset to `UNCLASSIFIED` and both `max_tph_mg_kg` and `max_benzene_mg_kg` reset to null in each case."

        Design: Difficulty/priority_pair_validation_conflict/project_state_beats_excavation_limit_on_change_order_approval
        """
        ctx = _over_ceiling_change_order_on_a_reopened_project(api)
        api.decide_change_order(
            ctx["change_order"]["id"],
            change_order_decision_payload("APPROVED"),
            COMPLIANCE_OFFICER,
        )

        order = fx.read_change_order(ctx["change_order"]["id"])
        assert order["status"] == "SUBMITTED", (
            f"a refused decision leaves the row awaiting one, got {order['status']}"
        )
        assert order["line_amount_cents"] is None, (
            "the line amount is computed only on approval, got "
            f"{order['line_amount_cents']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["status"] == "SAMPLING", (
            f"the retraction left the project in SAMPLING, got {project['status']}"
        )
        assert project["approved_scope_cubic_yards"] == pytest.approx(8.0, abs=0.01), (
            "no change order is approved, so the scope is still the baseline, got "
            f"{project['approved_scope_cubic_yards']}"
        )


class TestOwnershipBeatsDisclosureExpiry:
    #: One second past the 72-hour window that opened at 2026-08-03T08:00:00Z.
    ONE_SECOND_LATE = "2026-08-06T08:00:01Z"

    def _expired_notice_and_a_stranger(self, api):
        ctx = fx.project_at_surveyed()
        other = fx.create_property(street_address="9 Cranberry Court")
        ctx["other_property"] = other
        ctx["disclosure"] = fx.create_disclosure(
            ctx["project"]["id"], disclosure_kind="SWEEP_FINDINGS"
        )
        fx.set_clock(self.ONE_SECOND_LATE)
        return ctx

    def test_a_stranger_homeowner_is_refused_ownership_before_expiry_is_evaluated(
        self, api
    ):
        """PRD §2.1: "When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Property`; ownership checks compare the `property_id` of the addressed project — or of the project behind the addressed disclosure or letter — to `X-User-ID`."
        PRD §2.11: "3. **Ownership for entity-backed roles** — `ERR_NOT_RESOURCE_OWNER` (403). Applies to the nine operations enumerated in §2.1."
        PRD §2.11: "11. **The regulatory safety family**, in this internal order: the fire-marshal notice effectiveness check (`ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE`, 409); the municipal permit checks (`ERR_PERMIT_NOT_ISSUED` and `ERR_PERMIT_EXPIRED`, both 409); the tank-located check (`ERR_NO_TANK_LOCATED`, 409); the disclosure window check (`ERR_DISCLOSURE_EXPIRED`, 409); the laboratory accreditation check (`ERR_LAB_NOT_ACCREDITED`, 409); the contamination-disclosure acknowledgement check (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, 409); and the closure blocker check (`ERR_NFA_BLOCKED`, 409)."

        Design: Difficulty/priority_pair_validation_conflict/resource_ownership_beats_disclosure_expiry_on_respond
        """
        ctx = self._expired_notice_and_a_stranger(api)

        response = api.respond_to_disclosure(
            ctx["disclosure"]["id"],
            disclosure_response_payload(),
            make_homeowner_headers(ctx["other_property"]["id"]),
        )
        error_id = validate_error(
            response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403
        )["error_id"]
        assert error_id != ApiErrorId.ERR_DISCLOSURE_EXPIRED.value, (
            "the window check sits eight rungs below the ownership check, so it must "
            "not be the reported code"
        )

    def test_ownership_refusal_does_not_persist_the_expiry_transition(self, api):
        """PRD §3.2: "If the logical clock has passed `expires_at` while the notice was still `PENDING`, the server transitions the notice `PENDING → EXPIRED`, persists that transition, and only then rejects the incoming response with `ERR_DISCLOSURE_EXPIRED`."
        PRD §3.2: "The notice is created in `PENDING` with `sent_at` stamped from the logical clock and `expires_at` derived as three days later — the response window is 72 hours."

        Design: Difficulty/priority_pair_validation_conflict/resource_ownership_beats_disclosure_expiry_on_respond
        """
        ctx = self._expired_notice_and_a_stranger(api)
        api.respond_to_disclosure(
            ctx["disclosure"]["id"],
            disclosure_response_payload(),
            make_homeowner_headers(ctx["other_property"]["id"]),
        )

        notice = fx.read_disclosure(ctx["disclosure"]["id"])
        assert notice["status"] == "PENDING", (
            "the expiry write is part of the response handling the stranger never "
            f"reached, got {notice['status']}"
        )
        assert notice["responded_at"] is None, (
            f"no response was recorded, got {notice['responded_at']}"
        )
        assert parse_instant(notice["expires_at"]) == parse_instant(
            "2026-08-06T08:00:00Z"
        ), (
            "72 hours after 2026-08-03T08:00:00Z is 2026-08-06T08:00:00Z, got "
            f"{notice['expires_at']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "SURVEYED", (
            "the project still waits behind the disclosure gate"
        )


class TestStaleVersionBeatsSupersedeTarget:
    def _stale_and_invalid_supersession(self, api):
        ctx = fx.project_remediation_active_gross()
        stale_version = fx.project_version(ctx["project"]["id"])
        ctx["stale_version"] = stale_version
        #: Creating this order is itself what makes the observed version stale, and it
        #: stays in DRAFT so it can never be a lawful supersession target.
        ctx["first_order"] = fx.create_change_order(
            ctx["project"]["id"],
            stale_version,
            additional_cubic_yards=4.0,
            unit_rate_cents=1200,
        )
        return ctx

    def test_stale_project_version_is_reported_ahead_of_the_supersede_target_check(
        self, api
    ):
        """PRD §2.8: "Creating a `RemediationChangeOrder` requires `expected_project_version` in the request body. If that value does not equal the target project's current `version`, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
        PRD §2.11: "8. **Project version freshness** — `ERR_STALE_PROJECT_VERSION` (412). Applies to change-order creation and trust-fund-claim creation."
        PRD §2.11: "12. **Referential integrity of optional links and reason fields**, in this internal order: `ERR_SUPERSEDE_TARGET_INVALID` (409), `ERR_RETEST_TARGET_INVALID` (409), then `ERR_METHOD_OVERRIDE_REASON_REQUIRED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/stale_project_version_beats_invalid_supersede_target_on_change_order_create
        """
        ctx = self._stale_and_invalid_supersession(api)

        response = api.create_change_order(
            change_order_payload(
                ctx["project"]["id"],
                ctx["stale_version"],
                additional_cubic_yards=6.0,
                unit_rate_cents=1200,
                supersedes_change_order_id=ctx["first_order"]["id"],
            ),
            LSP_DRAFTER,
        )
        error_id = validate_error(
            response, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412
        )["error_id"]
        assert error_id != ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value, (
            "the supersede-target check sits four rungs below version freshness, so "
            "it must not be the reported code"
        )

    def test_refused_draft_writes_no_second_change_order(self, api):
        """PRD §3.7: "A change order may also carry `supersedes_change_order_id`, naming an already-approved change order on the same project that this one replaces; a target on another project, or one whose `status` is anything other than `APPROVED`, is refused with `ERR_SUPERSEDE_TARGET_INVALID`."
        PRD §3.7: "The project's `approved_scope_cubic_yards` is always its `baseline_scope_cubic_yards` plus the sum of `additional_cubic_yards` over the project's change orders whose `status` is `APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/stale_project_version_beats_invalid_supersede_target_on_change_order_create
        """
        ctx = self._stale_and_invalid_supersession(api)
        api.create_change_order(
            change_order_payload(
                ctx["project"]["id"],
                ctx["stale_version"],
                additional_cubic_yards=6.0,
                unit_rate_cents=1200,
                supersedes_change_order_id=ctx["first_order"]["id"],
            ),
            LSP_DRAFTER,
        )

        first = fx.read_change_order(ctx["first_order"]["id"])
        assert first["status"] == "DRAFT", (
            "the intended supersession target was never a lawful one, got "
            f"{first['status']}"
        )

        listed, meta = validate_paginated(
            api.list_change_orders(
                PROJECT_COORDINATOR, params={"tank_project_id": ctx["project"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"only the first draft may exist, got {meta['total_count']}"
        )
        assert fx.read_project(ctx["project"]["id"])[
            "approved_scope_cubic_yards"
        ] == pytest.approx(8.0, abs=0.01), (
            "nothing was approved, so the scope is still the baseline"
        )
