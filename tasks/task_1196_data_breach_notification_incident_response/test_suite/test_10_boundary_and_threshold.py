"""Boundary precision — threshold inclusivity and zero-count edge
(difficulty rule boundary_precision_check)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_incident_in_investigating_state,
    create_jurisdiction_evaluation_payload,
    get_success_data,
    validate_error,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["privacy_counsel_headers"]


class TestJurisdictionThresholdBoundary:
    def test_threshold_inclusive_at_boundary(self, api):
        """PRD §3.5: "`notification_required` flips to true as soon as
        `subjects_in_jurisdiction` reaches `record_count_threshold` — the
        threshold comparison is inclusive." Also §2.9: "exactly-at-threshold
        triggers notification."

        Design: Difficulty/boundary_precision_check/jurisdiction_threshold_inclusive_at_boundary
        """
        ctx = create_incident_in_investigating_state(
            subject_count=1, subject_state_code="CA"
        )
        inc = ctx["incident"]
        je = get_success_data(
            api.create_jurisdiction_evaluation(
                inc["id"],
                create_jurisdiction_evaluation_payload(
                    state_code="CA",
                    record_count_threshold=1,
                    deadline_days=10,
                    deadline_kind="CALENDAR_DAYS",
                ),
                PC,
            )
        )
        api.confirm_incident(inc["id"], IC)
        je_after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je["id"], PC)
        )
        assert je_after["subjects_in_jurisdiction"] == 1
        assert je_after["notification_required"] is True


class TestConfirmZeroSubjects:
    def test_confirm_with_zero_subjects_rejected(self, api):
        """PRD §3.6: confirm requires "`total_affected_subjects` is strictly
        greater than zero (otherwise `ERR_NO_AFFECTED_SUBJECTS`, 409)". The
        zero-subject boundary is the lower edge — only >= 1 permits confirm.

        Design: Difficulty/boundary_precision_check/confirm_with_zero_subjects_rejected
        """
        # INVESTIGATING with sealed evidence but ZERO subjects.
        ctx = create_incident_in_investigating_state(
            subject_count=0, add_sealed_evidence=True
        )
        inc = ctx["incident"]
        resp = api.confirm_incident(inc["id"], IC)
        # PRD names ERR_NO_AFFECTED_SUBJECTS for this branch.
        validate_error(
            resp, ApiErrorId.ERR_NO_AFFECTED_SUBJECTS.value, expected_status=409
        )
        # Investigation state unchanged.
        inc_after = get_success_data(api.get_incident(inc["id"], IC))
        assert inc_after["investigation_status"] == "INVESTIGATING"
