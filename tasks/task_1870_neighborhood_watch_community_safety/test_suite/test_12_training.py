"""Training sessions: the 24-hour cooling-off rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_member,
    complete_bias_training,
    create_officer,
    create_training_session_payload,
    make_officer_headers,
    setup_group_with_registered_block,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestTrainingCooldown:
    def test_cooldown_rejects_early_and_allows_exact_boundary(self, api):
        """PRD §3.6: "To keep sessions from bunching, a group that has completed
        a session enters a 24-hour cooling-off period: the group's
        `training_cooldown_until` is set to the completed session's
        `scheduled_at` plus 24 hours, and any new session whose `scheduled_at`
        precedes `training_cooldown_until` is rejected with
        `ERR_TRAINING_COOLDOWN`."

        Design: Corner/validations/training_cooldown_enforced
        """
        group, block = setup_group_with_registered_block(
            "Cool Watch", "V05", "4-4 Val St", 4,
        )
        member = add_member(group["id"], block["id"], "Cool M", "SMS")
        officer = create_officer("BV05", "Officer Co", "V05")
        officer_headers = make_officer_headers(officer["id"])

        completed = complete_bias_training(
            group["id"], officer, [member["id"]],
            scheduled_at="2026-08-02T10:00:00Z",
        )
        assert completed["session_status"] == "COMPLETED"
        # cooldown_until = 2026-08-02T10:00:00Z + 24h = 2026-08-03T10:00:00Z
        group_after = validate_success(api.get_watch_group(group["id"], COORD))
        assert group_after["training_cooldown_until"] is not None
        assert group_after["training_cooldown_until"].startswith(
            "2026-08-03T10:00:00"
        )

        early = api.create_training_session(
            create_training_session_payload(
                group["id"], officer["id"], curriculum="REPORT_WRITING",
                scheduled_at="2026-08-03T09:00:00Z",
            ),
            officer_headers,
        )
        validate_error(early, ApiErrorId.ERR_TRAINING_COOLDOWN)

        at_boundary = validate_success(
            api.create_training_session(
                create_training_session_payload(
                    group["id"], officer["id"], curriculum="REPORT_WRITING",
                    scheduled_at="2026-08-03T10:00:00Z",
                ),
                officer_headers,
            ),
            201,
        )
        assert at_boundary["session_status"] == "SCHEDULED", (
            "scheduled_at exactly equal to training_cooldown_until does not "
            "precede it, so it is allowed"
        )
