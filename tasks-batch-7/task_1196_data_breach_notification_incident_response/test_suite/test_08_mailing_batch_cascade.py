"""Mailing batch cascades and dispatch lifecycle (difficulty rules
transitive_cascade + cross_entity_state_dependency)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_incident_confirmed,
    create_locked_notice,
    create_mailing_batch_for_notice,
    get_success_data,
    setup_dispatching_incident_with_queued_batch,
    validate_error,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["privacy_counsel_headers"]


class TestConfirmCascadeDepth3:
    def test_confirm_triggers_jurisdiction_evaluation_cascade(self, api):
        """PRD §3.6: "Confirmation has four side effects:
        `notification_status` flips to `EVALUATING`; every `PENDING`
        `JurisdictionEvaluation` transitions to `TRIGGERED` with its
        `deadline_at` computed per §3.5; each newly-`TRIGGERED` evaluation
        with `notification_required` true implicitly produces a
        notice-placeholder work item; and both risk scores are recomputed."

        PRD §3.5: "when any evaluation's `notification_required` flips to
        true while the incident is `EVALUATING`, the incident transitions to
        `REQUIRED`."

        Design: Difficulty/transitive_cascade/confirm_cascade_depth3
        """
        from test_helpers import (
            create_incident_in_investigating_state,
            create_jurisdiction_evaluation_payload,
        )

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

        confirm_resp = api.confirm_incident(inc["id"], IC)
        validate_success(confirm_resp)

        je_after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je["id"], PC)
        )
        # link 1: PENDING -> TRIGGERED.
        assert je_after["status"] == "TRIGGERED"
        # link 2: deadline_at computed (10 calendar days from 2026-05-01).
        assert je_after["deadline_at"] == "2026-05-11T23:59:59.999Z"
        # link 2: subjects_in_jurisdiction=1 >= threshold=1 -> inclusive.
        assert je_after["notification_required"] is True
        # link 3: incident notification_status moved to REQUIRED.
        inc_after = get_success_data(api.get_incident(inc["id"], IC))
        assert inc_after["notification_status"] == "REQUIRED"


class TestMarkShippedCascadeDepth2:
    def test_mark_shipped_moves_subjects_and_completes_notification(self, api):
        """PRD §3.8: "On shipment, every subject that this batch moved into
        `NOTICE_QUEUED` now transitions to `NOTIFIED`;
        `total_notified_subjects` and `total_pending_subjects` are
        recomputed; if after this recompute `total_pending_subjects` is zero
        and `total_affected_subjects` equals `total_notified_subjects`, the
        incident's `notification_status` automatically transitions from
        `DISPATCHING` to `COMPLETED`."

        Design: Difficulty/transitive_cascade/mark_shipped_cascade_depth2
        """
        ctx = setup_dispatching_incident_with_queued_batch(subject_count=1)
        inc = ctx["incident"]
        batch = ctx["batch"]
        subj_id = ctx["subjects"][0]["id"]

        prod_resp = api.start_production_mailing_batch(inc["id"], batch["id"], PC)
        validate_success(prod_resp)
        ship_resp = api.mark_shipped_mailing_batch(inc["id"], batch["id"], PC)
        validate_success(ship_resp)

        # link 1: subject transitioned to NOTIFIED.
        subj_after = get_success_data(api.get_affected_subject(inc["id"], subj_id, PC))
        assert subj_after["status"] == "NOTIFIED"

        inc_after = get_success_data(api.get_incident(inc["id"], IC))
        assert inc_after["total_notified_subjects"] == 1
        assert inc_after["total_pending_subjects"] == 0
        # link 2: notification_status auto-transitioned to COMPLETED.
        assert inc_after["notification_status"] == "COMPLETED"


class TestMailingBatchStartRequiresNoticeLocked:
    def test_start_production_on_locked_notice_moves_to_in_production(self, api):
        """PRD §3.8: "Starting production — moving the batch from `QUEUED` to
        `IN_PRODUCTION` — is gated on the linked notice being in
        `LOCKED_FOR_MAIL` and the incident's `notification_status` being
        `DISPATCHING`."

        Design: Difficulty/cross_entity_state_dependency/mailing_batch_start_requires_notice_locked
        """
        ctx = setup_dispatching_incident_with_queued_batch(subject_count=1)
        inc = ctx["incident"]
        batch = ctx["batch"]
        notice = ctx["notice"]

        resp = api.start_production_mailing_batch(inc["id"], batch["id"], PC)
        batch_after = validate_success(resp)
        assert batch_after["status"] == "IN_PRODUCTION"

        notice_after = get_success_data(api.get_notice(inc["id"], notice["id"], PC))
        assert notice_after["status"] == "LOCKED_FOR_MAIL"

    def test_start_production_on_unknown_batch_returns_not_found(self, api):
        """PRD §2.5: path-id resolution is strict left-to-right; a missing
        `batchId` "is rejected with `ERR_NOT_FOUND` (HTTP 404) before any
        later check runs."

        Design: Corner/endpoints/action_endpoint_start_production_precondition
        """
        from test_helpers import NON_EXISTENT_UUID
        inc = create_incident_confirmed()["incident"]
        resp = api.start_production_mailing_batch(inc["id"], NON_EXISTENT_UUID, PC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)
