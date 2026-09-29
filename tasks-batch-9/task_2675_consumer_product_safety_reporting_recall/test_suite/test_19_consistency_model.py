"""The widest write in the docket settles inside its own request."""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field_values,
    assert_fields_null,
    assert_unchanged,
)

# The plan is signed with the logical clock standing at the filing instant, so
# the stop-sale takes effect then and the acknowledgement falls due 72 hours on.
APPROVAL_INSTANT = "2026-03-13T00:00:00Z"
ACK_DUE_INSTANT = "2026-03-16T00:00:00Z"

# Two storefront operators on one recall, so the second link of the cascade has a
# batch to process rather than a single row.
FIRST_RETAILER = {"name": "MegaMart", "channel_type": "BIG_BOX", "store_count": 120}
SECOND_RETAILER = {"name": "CornerHome", "channel_type": "SPECIALTY", "store_count": 4}


def _instant(value):
    """The whole-second part of a stored ISO 8601 UTC instant."""
    assert value is not None, "expected an instant, got null"
    return str(value)[:19]


def _submitted_plan_with_two_enrolled_retailers(api):
    """A submitted recall plan whose two retailers each hold a PENDING notice."""
    env = fx.draft_recall_env(api, retailer=FIRST_RETAILER)
    env["drafted"] = env["recall"]
    second_retailer = fx.create_retailer(api, **SECOND_RETAILER)
    second_notification = fx.create_notification(
        api, env["recall_id"], second_retailer["id"]
    )
    env["second_retailer_id"] = second_retailer["id"]
    env["second_notification_id"] = second_notification["id"]
    env["recall"] = fx.submit_plan(api, env["recall_id"])
    return env


class TestPlanApprovalRespondsWithTheSettledRecord:
    """Approval answers with the recall as the cascade has already left it."""

    def test_the_approval_response_already_carries_both_state_dimensions(self, api):
        """One request returns APPROVED, IN_PROGRESS and the fresh stop-sale stamp.

        The contract states: "The first link advances `plan_status` `SUBMITTED →
        APPROVED` and stamps `stop_sale_effective_at` with the logical clock." It
        also states: "A follow-on effect of that link moves the recall's
        `notification_status` `NOT_STARTED → IN_PROGRESS`, but only when at least
        one notification actually flipped". Because "operations that create or
        modify a resource will return the created or updated resource object in
        the data field", the answer needs no second read.

        Design: Corner/consistency_model/plan_approval_response_already_shows_every_cascaded_change
        """
        env = _submitted_plan_with_two_enrolled_retailers(api)
        assert_field_values(
            env["drafted"],
            plan_status="DRAFT",
            notification_status="NOT_STARTED",
            version=1,
        )
        assert_fields_null(env["drafted"], "stop_sale_effective_at")
        assert_field_values(
            env["recall"],
            plan_status="SUBMITTED",
            notification_status="NOT_STARTED",
            version=2,
        )

        approved = fx.approve_plan(api, env["recall_id"])

        assert_field_values(
            approved,
            plan_status="APPROVED",
            notification_status="IN_PROGRESS",
            version=3,
        )
        assert _instant(approved["stop_sale_effective_at"]) == _instant(
            APPROVAL_INSTANT
        ), approved["stop_sale_effective_at"]

        reread = fx.get_recall(api, env["recall_id"])
        assert_unchanged(
            approved,
            reread,
            "plan_status",
            "notification_status",
            "stop_sale_effective_at",
            "version",
            "updated_at",
        )

    def test_the_first_read_of_every_cascaded_sibling_shows_it_already_settled(
        self, api
    ):
        """Both notifications and both retailers converge inside the one request.

        The contract states: "The second link reaches every retailer notification
        on this recall whose `status` is `PENDING` and flips it `PENDING →
        ISSUED`, setting `stop_sale_required` to true, `issued_at` to that same
        logical-clock instant, and `ack_due_at` to `issued_at` plus 72 hours
        (three days), processing the notifications in `created_at` ascending
        order." It also states: "The third link reaches each flipped
        notification's retailer, incrementing that retailer's
        `open_stop_sale_count` by 1 and setting its `compliance_posture` to
        `STOP_SALE_ACTIVE`." Those rows are reached through their own reads
        because "no creation response ever contains the sibling rows a cascade
        touched".

        Design: Corner/consistency_model/plan_approval_response_already_shows_every_cascaded_change
        """
        env = _submitted_plan_with_two_enrolled_retailers(api)

        fx.approve_plan(api, env["recall_id"])

        for notification_id in (env["notification_id"], env["second_notification_id"]):
            notification = fx.get_notification(api, notification_id)
            assert_field_values(
                notification,
                status="ISSUED",
                stop_sale_required=True,
                version=2,
            )
            assert _instant(notification["issued_at"]) == _instant(
                APPROVAL_INSTANT
            ), notification["issued_at"]
            assert _instant(notification["ack_due_at"]) == _instant(
                ACK_DUE_INSTANT
            ), notification["ack_due_at"]
            assert_fields_null(notification, "acknowledged_at", "verified_at")

        for retailer_id in (env["retailer_id"], env["second_retailer_id"]):
            retailer = fx.get_retailer(api, retailer_id)
            assert_field_values(
                retailer,
                compliance_posture="STOP_SALE_ACTIVE",
                open_stop_sale_count=1,
                verified_removal_count=0,
                delinquent_count=0,
                version=2,
            )
