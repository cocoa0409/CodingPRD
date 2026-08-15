"""Record termination, violation lifecycle, and reinstatement cycle claims
(PRD §3.9, §2.10)."""
from test_helpers import (
    ApiErrorId,
    assert_status_violation,
    create_violation,
    get_record,
    get_student,
    setup_active_student,
    setup_student_with_draft_record,
    terminate_record,
    transition_violation,
    validate_error,
    validate_success,
)


class TestSevisRecordTerminationReinstatementCycle:
    """Cyclic record machine: ACTIVE -> TERMINATED -> REINSTATEMENT_PENDING ->
    ACTIVE, driven through the linked violation machine."""

    def test_terminate_then_recommend_reinstatement(self, api, pdso_headers):
        """PRD §3.9: "Termination of an `ACTIVE` SEVIS record is a
        `PDSO`-exclusive action carrying a `termination_reason`."
        PRD §3.9: "**RECOMMEND_REINSTATEMENT** (DSO) moves an `OPEN` violation
        to `REINSTATEMENT_PENDING`. It is only meaningful when the student's
        record is `TERMINATED` — otherwise the request is rejected with
        `ERR_RECORD_NOT_TERMINATED` — and it flips that record from
        `TERMINATED` to `REINSTATEMENT_PENDING` as it lands."

        Design: Difficulty/non_linear_state_machine/sevis_record_termination_reinstatement_cycle
        """
        ctx = setup_active_student()
        student_id = ctx["student"]["id"]

        record = terminate_record(ctx["record"]["id"], "Unauthorized employment")
        assert record["status"] == "TERMINATED"

        violation = create_violation(student_id)
        assert violation["status"] == "OPEN"

        pending = transition_violation(violation["id"], "RECOMMEND_REINSTATEMENT")
        assert pending["status"] == "REINSTATEMENT_PENDING"
        assert get_record(student_id)["status"] == "REINSTATEMENT_PENDING"

    def test_resolve_reinstated_returns_record_to_active(self, api, pdso_headers):
        """PRD §3.9: "**RESOLVE** (`PDSO` only) carries an `outcome` of
        `REINSTATED` or `DENIED` against a violation in `REINSTATEMENT_PENDING`
        (otherwise `ERR_VIOLATION_INVALID_STATE`). A `REINSTATED` outcome moves
        the violation to `RESOLVED_REINSTATED` and flips the record from
        `REINSTATEMENT_PENDING` back to `ACTIVE`; a `DENIED` outcome moves the
        violation to `RESOLVED_DENIED` and returns the record to `TERMINATED`."
        PRD §2.10: "Otherwise the posture is `CLEAR`."

        Design: Difficulty/non_linear_state_machine/sevis_record_termination_reinstatement_cycle
        """
        ctx = setup_active_student()
        student_id = ctx["student"]["id"]
        terminate_record(ctx["record"]["id"], "Unauthorized employment")
        violation = create_violation(student_id)
        transition_violation(violation["id"], "RECOMMEND_REINSTATEMENT")

        resolved = transition_violation(
            violation["id"], "RESOLVE", outcome="REINSTATED", headers=pdso_headers,
        )
        assert_status_violation(resolved)
        assert resolved["status"] == "RESOLVED_REINSTATED"

        # The cycle closes: the record is ACTIVE again after termination.
        assert get_record(student_id)["status"] == "ACTIVE"
        assert get_student(student_id)["compliance_posture"] == "CLEAR"


class TestReinstatementRecommendationGatedByRecordTerminated:
    """Cross-entity gate: RECOMMEND_REINSTATEMENT requires record TERMINATED."""

    def test_recommend_rejected_while_record_active(self, api, dso_headers):
        """PRD §3.9: "**RECOMMEND_REINSTATEMENT** (DSO) moves an `OPEN`
        violation to `REINSTATEMENT_PENDING`. It is only meaningful when the
        student's record is `TERMINATED` — otherwise the request is rejected
        with `ERR_RECORD_NOT_TERMINATED` — and it flips that record from
        `TERMINATED` to `REINSTATEMENT_PENDING` as it lands."

        Design: Difficulty/cross_entity_state_dependency/reinstatement_recommendation_gated_by_record_terminated
        """
        ctx = setup_active_student()
        violation = create_violation(ctx["student"]["id"])
        assert violation["status"] == "OPEN"

        resp = api.transition_status_violation(
            violation["id"], {"action": "RECOMMEND_REINSTATEMENT"}, dso_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_TERMINATED, 409)
        assert get_record(ctx["student"]["id"])["status"] == "ACTIVE"

    def test_recommend_after_termination_flips_record(self, api, dso_headers):
        """PRD §3.9: "it flips that record from `TERMINATED` to
        `REINSTATEMENT_PENDING` as it lands. A violation not in `OPEN` is
        rejected with `ERR_VIOLATION_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/reinstatement_recommendation_gated_by_record_terminated
        """
        ctx = setup_active_student()
        student_id = ctx["student"]["id"]
        violation = create_violation(student_id)
        terminate_record(ctx["record"]["id"], "Unauthorized employment")

        pending = transition_violation(violation["id"], "RECOMMEND_REINSTATEMENT")
        assert pending["status"] == "REINSTATEMENT_PENDING"
        assert get_record(student_id)["status"] == "REINSTATEMENT_PENDING"


def test_violation_resolve_from_open_returns_violation_invalid_state(
    api, pdso_headers,
):
    """PRD §3.9: "**RESOLVE** (`PDSO` only) carries an `outcome` of
    `REINSTATED` or `DENIED` against a violation in `REINSTATEMENT_PENDING`
    (otherwise `ERR_VIOLATION_INVALID_STATE`)."

    Design: Corner/state_machines/violation_resolve_from_open_returns_violation_invalid_state
    """
    ctx = setup_student_with_draft_record()
    violation = create_violation(
        ctx["student"]["id"], violation_type="OTHER",
        description="Advising discrepancy",
    )
    assert violation["status"] == "OPEN"

    resp = api.transition_status_violation(
        violation["id"], {"action": "RESOLVE", "outcome": "REINSTATED"},
        pdso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VIOLATION_INVALID_STATE, 409)
