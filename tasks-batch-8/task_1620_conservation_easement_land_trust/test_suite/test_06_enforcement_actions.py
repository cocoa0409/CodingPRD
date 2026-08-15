"""Enforcement actions: remediation agreement lifecycle and the
breach/renegotiation cycle (PRD §3.4, §2.5)."""
from test_helpers import (
    ApiErrorId,
    execute_enforcement_payload,
    get_easement,
    make_board_reviewer_headers,
    make_coordinator_headers,
    setup_escalated_violation,
    validate_error,
    validate_success,
)


def _breach_renegotiate_round_trip(api, enforcement_id):
    """PROPOSED -> EXECUTED -> BREACHED -> PROPOSED -> EXECUTED.

    Returns the intermediate status strings in transition order.
    """
    executed1 = validate_success(
        api.execute_enforcement_action(
            enforcement_id,
            execute_enforcement_payload(
                agreement_terms="restore in 60d", remediation_cost_cents=12000000
            ),
            make_board_reviewer_headers("board-5"),
        ),
        200,
    )
    breached = validate_success(
        api.breach_enforcement_action(
            enforcement_id, {"breach_notes": "missed milestone"},
            make_board_reviewer_headers("board-5"),
        ),
        200,
    )
    renegotiated = validate_success(
        api.renegotiate_enforcement_action(
            enforcement_id,
            execute_enforcement_payload(
                agreement_terms="restore in 90d v2", remediation_cost_cents=15000000
            ),
            make_coordinator_headers("coord-1"),
        ),
        200,
    )
    executed2 = validate_success(
        api.execute_enforcement_action(
            enforcement_id,
            execute_enforcement_payload(
                agreement_terms="restore in 90d v2", remediation_cost_cents=15000000
            ),
            make_board_reviewer_headers("board-6"),
        ),
        200,
    )
    return [executed1["status"], breached["status"], renegotiated["status"],
            executed2["status"]]


class TestEnforcementStateRules:
    def test_enforcement_breach_from_proposed_rejected(self, api):
        """PRD §3.4: "When an agreement fails, a `TrustBoardReviewer` declares
        the breach, moving the action from `EXECUTED` to `BREACHED` and
        capturing optional `breach_notes`."
        PRD §3.4: "Breach or renegotiate attempted from any state where they are
        not defined is rejected with `ERR_INVALID_ENFORCEMENT_STATE`."

        Design: Corner/state_machines/enforcement_breach_from_proposed_rejected
        """
        ctx = setup_escalated_violation(severity="MATERIAL",
                                        violation_type="SUBDIVISION",
                                        parcel_acreage=100)
        enforcement = ctx["enforcement_action"]
        assert enforcement["status"] == "PROPOSED"

        resp = api.breach_enforcement_action(
            enforcement["id"], {"breach_notes": "too early"},
            make_board_reviewer_headers("board-5"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENFORCEMENT_STATE)


class TestBreachRenegotiationCycle:
    def test_enforcement_breach_renegotiation_cycle_states(self, api):
        """PRD §3.4: "A coordinator can then renegotiate, moving the action from
        `BREACHED` back to `PROPOSED`: fresh `agreement_terms` and
        `remediation_cost_cents` replace the old ones, and `executed_by_user_id`
        is cleared to null so the renegotiated agreement requires a fresh board
        execution."
        PRD §3.4: "Completion is a coordinator act that moves the action from
        `EXECUTED` to `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/enforcement_breach_renegotiation_cycle
        """
        ctx = setup_escalated_violation(
            severity="MATERIAL", violation_type="RESIDENTIAL_CONSTRUCTION",
            detected_on="2026-08-10", clock="2026-08-10T00:00:00Z",
            parcel_acreage=500,
        )
        enforcement = ctx["enforcement_action"]
        assert enforcement["status"] == "PROPOSED"

        states = _breach_renegotiate_round_trip(api, enforcement["id"])
        assert states == ["EXECUTED", "BREACHED", "PROPOSED", "EXECUTED"], (
            f"cycle PROPOSED->EXECUTED->BREACHED->PROPOSED->EXECUTED, got {states}"
        )

        completed = validate_success(
            api.complete_enforcement_action(
                enforcement["id"], make_coordinator_headers("coord-2")
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"

    def test_enforcement_completion_resolves_violation_and_relaxes_posture(self, api,
                                                                           trust_admin_headers):
        """PRD §3.4: "Completion stamps `completed_by_user_id`, then resolves the
        linked violation from `ESCALATED` to `RESOLVED`, stamping its
        `resolved_on` with the clock date and its `resolution_verified_by_user_id`
        with the completer's identity; the easement's `open_violation_count` and
        `posture` are recomputed and the easement's `version` advances by one."
        PRD §3.4: "a `BREACHED` action still holds the easement at
        `ENFORCEMENT_ACTIVE`, and only completion of every open enforcement
        matter lets the easement's posture relax."

        Design: Difficulty/non_linear_state_machine/enforcement_breach_renegotiation_cycle
        """
        ctx = setup_escalated_violation(
            severity="MATERIAL", violation_type="RESIDENTIAL_CONSTRUCTION",
            detected_on="2026-08-10", clock="2026-08-10T00:00:00Z",
            parcel_acreage=500,
        )
        enforcement = ctx["enforcement_action"]
        _breach_renegotiate_round_trip(api, enforcement["id"])

        completed = validate_success(
            api.complete_enforcement_action(
                enforcement["id"], make_coordinator_headers("coord-2")
            ),
            200,
        )
        assert completed["completed_by_user_id"] == "coord-2"

        violation = validate_success(
            api.get_violation(ctx["violation"]["id"], trust_admin_headers), 200
        )
        assert violation["status"] == "RESOLVED"
        assert violation["resolution_verified_by_user_id"] == "coord-2"

        # Enforcement closed, no open violations, and monitoring due 2027-08-01
        # is still ahead of the 2026-08-10 clock: posture relaxes fully.
        easement = get_easement(ctx["easement"]["id"])
        assert easement["open_violation_count"] == 0
        assert easement["posture"] == "GOOD_STANDING"
