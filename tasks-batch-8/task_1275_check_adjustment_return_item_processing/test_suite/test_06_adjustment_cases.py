"""Adjustment case work: assignment OCC, resolution authority, reopen cycle,
closure gating, and notification-breach escalation."""
import pytest

from test_helpers import (
    ApiErrorId,
    analyst,
    assign_case,
    create_assign_payload,
    set_clock,
    setup_acknowledged_claim,
    setup_coded_return,
    setup_returned_item,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OFFICER,
    get_first_case_for_item,
    list_notifications,
)


def _resolved_return_case(api, analyst_id="analyst-1"):
    """RETURN_ITEM case from the return flow, assigned and resolved NO_ACTION."""
    ctx = setup_returned_item(
        amount_cents=40000, opening_balance_cents=500000,
        bank_overrides={"name": "CB Case", "routing_number": "111000030"},
        item_reference="ITM-CASE",
    )
    ctx["case"] = assign_case(ctx["return_case"]["id"], analyst_id)
    resolved = validate_success(
        api.resolve_adjustment_case(
            ctx["case"]["id"], {"disposition": "NO_ACTION"}, analyst(analyst_id)
        ),
        200,
    )
    ctx["case"] = resolved
    return ctx


class TestResolveReopenCycle:
    def test_reopen_increments_count_and_clears_resolution(self, api):
        """PRD §3.5: "A `ComplianceOfficer` may reopen a `RESOLVED` case by
        supplying a `reopen_reason`; the case moves to `REOPENED`,
        `reopen_count` increments by one, and the prior `disposition`,
        `resolution_amount_cents`, and `resolved_at` are cleared."

        Design: Difficulty/non_linear_state_machine/adjustment_case_resolve_reopen_cycle
        """
        ctx = _resolved_return_case(api)
        reopened = validate_success(
            api.reopen_adjustment_case(
                ctx["case"]["id"],
                {"reopen_reason": "new evidence from clearing bank"},
                OFFICER,
            ),
            200,
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        assert reopened["disposition"] is None
        assert reopened["resolved_at"] is None

    def test_reopened_case_reassigned_and_resolved_again(self, api):
        """PRD §3.5: "The cycle `RESOLVED` → `REOPENED` → `ASSIGNED` →
        `RESOLVED` may repeat as often as review demands."
        PRD §3.5: "Assignment is allowed from `OPEN`, `ASSIGNED`, `REOPENED`,
        and `ESCALATED`, always landing on `ASSIGNED`; from `ASSIGNED` it is a
        re-assignment that supersedes the prior assignee."

        Design: Difficulty/non_linear_state_machine/adjustment_case_resolve_reopen_cycle
        """
        ctx = _resolved_return_case(api)
        case_id = ctx["case"]["id"]
        reopened = validate_success(
            api.reopen_adjustment_case(
                case_id, {"reopen_reason": "new evidence from clearing bank"}, OFFICER
            ),
            200,
        )
        reassigned = validate_success(
            api.assign_adjustment_case(
                case_id,
                create_assign_payload("analyst-2", reopened["version"]),
                ADMIN,
            ),
            200,
        )
        assert reassigned["status"] == "ASSIGNED"
        assert reassigned["assigned_analyst_id"] == "analyst-2"

        resolved_again = validate_success(
            api.resolve_adjustment_case(
                case_id, {"disposition": "NO_ACTION"}, analyst("analyst-2")
            ),
            200,
        )
        assert resolved_again["status"] == "RESOLVED"


class TestCaseClosureGating:
    def test_case_close_with_open_claims_rejected(self, api):
        """PRD §3.5: "An `AdjustmentAnalyst` or `ComplianceOfficer` may close
        a `RESOLVED` case only when every linked adjustment claim has reached
        `SETTLED` or `WRITTEN_OFF` and every linked warranty claim has reached
        `HONORED` or `WRITTEN_OFF`; otherwise the close is rejected with
        `ERR_CASE_HAS_OPEN_CLAIMS`."
        (Claim is ACKNOWLEDGED — non-terminal — at close time.)

        Design: Corner/validations/case_close_with_open_claims_rejected
        """
        ctx = setup_acknowledged_claim(
            analyst_id="analyst-1",
            bank_overrides={"name": "CB OC", "routing_number": "222000026"},
            item_reference="ITM-OC",
        )
        validate_success(
            api.resolve_adjustment_case(
                ctx["case"]["id"], {"disposition": "NO_ACTION"}, analyst("analyst-1")
            ),
            200,
        )
        res = api.close_adjustment_case(ctx["case"]["id"], analyst("analyst-1"))
        validate_error(res, ApiErrorId.ERR_CASE_HAS_OPEN_CLAIMS)


class TestCaseAssignOcc:
    def test_stale_version_on_case_assign_returns_412(self, api):
        """PRD §2.9: "Assigning or re-assigning an adjustment case requires
        the request to carry `expected_adjustment_case_version` holding the
        case `version` the client last observed. A mismatch with the case's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.5: "Each successful assignment increments the case's `version`
        by one."

        Design: Corner/cross_cutting_layers/stale_version_on_case_assign_returns_412
        """
        ctx = setup_returned_item(
            amount_cents=5000, opening_balance_cents=100000,
            bank_overrides={"name": "CB OCC", "routing_number": "222000042"},
            item_reference="ITM-OCC",
        )
        case = ctx["return_case"]
        observed = case["version"]

        assigned = validate_success(
            api.assign_adjustment_case(
                case["id"], create_assign_payload("analyst-1", observed), ADMIN
            ),
            200,
        )
        assert assigned["version"] == observed + 1

        stale = api.assign_adjustment_case(
            case["id"], create_assign_payload("analyst-2", observed), ADMIN
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(
            api.assign_adjustment_case(
                case["id"], create_assign_payload("analyst-2", observed + 1), ADMIN
            ),
            200,
        )
        assert fresh["assigned_analyst_id"] == "analyst-2"


class TestResolveAuthority:
    def test_resolve_requires_assigned_analyst(self, api):
        """PRD §3.5: "Resolution belongs to the assignee and no one else: an
        `AdjustmentAnalyst` resolving a case whose `assigned_analyst_id`
        differs from their `X-User-ID` is rejected with
        `ERR_NOT_ASSIGNED_ANALYST`."

        Design: Corner/cross_cutting_layers/resolve_requires_assigned_analyst
        """
        ctx = setup_returned_item(
            amount_cents=5000, opening_balance_cents=100000,
            bank_overrides={"name": "CB NA", "routing_number": "222000044"},
            item_reference="ITM-NA",
        )
        assign_case(ctx["return_case"]["id"], "analyst-1")

        wrong = api.resolve_adjustment_case(
            ctx["return_case"]["id"], {"disposition": "NO_ACTION"}, analyst("analyst-9")
        )
        validate_error(wrong, ApiErrorId.ERR_NOT_ASSIGNED_ANALYST)

        resolved = validate_success(
            api.resolve_adjustment_case(
                ctx["return_case"]["id"], {"disposition": "NO_ACTION"}, analyst("analyst-1")
            ),
            200,
        )
        assert resolved["status"] == "RESOLVED"


class TestNotificationBreachEscalation:
    def test_notification_breach_sweep_escalates_case(self, api):
        """PRD §3.4: "A `RETURN_NOTICE` customer notification is raised in
        `PENDING` status, its `due_at` set to the coding moment advanced to
        17:00:00Z on the next business day strictly after the coding date."
        PRD §3.9: "it breaches every `PENDING` customer notification whose
        `due_at` has passed, moving it to `BREACHED` and cascading the
        escalation of §3.5 onto any linked case in `OPEN`, `ASSIGNED`, or
        `REOPENED`."
        (Coded Friday 2026-05-01 -> due Monday 2026-05-04 17:00Z; sweep runs
        at Tuesday 2026-05-05.)

        Design: Corner/state_machines/notification_breach_sweep_escalates_case
        """
        ctx = setup_coded_return(
            reason_code="NSF", amount_cents=5000, opening_balance_cents=100000,
            bank_overrides={"name": "CB NB", "routing_number": "222000016"},
            item_reference="ITM-NB",
        )
        case = get_first_case_for_item(ctx["item"]["id"], case_type="RETURN_ITEM")
        assert case["status"] == "OPEN"

        set_clock("2026-05-05T00:00:00Z")
        report = validate_success(api.run_daily_ops(ADMIN), 200)
        assert report["notifications_breached"] == 1

        notices = list_notifications(adjustment_case_id=case["id"])
        assert len(notices) == 1
        assert notices[0]["notification_type"] == "RETURN_NOTICE"
        assert notices[0]["status"] == "BREACHED"
        assert notices[0]["due_at"].startswith("2026-05-04T17:00:00")

        escalated = validate_success(api.get_adjustment_case(case["id"], ADMIN), 200)
        assert escalated["status"] == "ESCALATED"
