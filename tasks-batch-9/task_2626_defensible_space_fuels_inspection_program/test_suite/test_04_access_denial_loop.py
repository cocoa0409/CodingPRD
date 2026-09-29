"""The denied-access loop and its terminal abandonment branch."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_ACCESS_DENIAL_LIMIT_REACHED,
    assert_instant,
    assert_notice_schedule,
    assert_posture,
    get_inspection,
    get_parcel,
    list_notices,
    noticed_world,
    reschedule_payload,
    serve_notice,
)
from test_helpers.factories import access_denial_payload
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS, make_inspector_headers


def _deny_access(client, inspection_id, inspector_id, reason_code="GATE_LOCKED"):
    return validate_success(
        client.record_access_denial(
            inspection_id,
            headers=make_inspector_headers(inspector_id),
            payload=access_denial_payload(reason_code),
        )
    )


class TestAccessDenialLoop:
    """ACCESS_DENIED to SCHEDULED to NOTICED and finally to ABANDONED."""

    def test_reschedule_clears_service_but_keeps_the_denial_count(self, client):
        """The loop closes back onto NOTICED without forgiving the first denial.

        PRD: "With access_denial_count standing at 0, the count is incremented
        to 1 and the inspection moves NOTICED -> ACCESS_DENIED."

        PRD: "The inspection returns ACCESS_DENIED -> SCHEDULED, its
        notice_method and notice_sent_at_utc are cleared back to null so that a
        fresh notice must be served before the new visit, and the new window is
        subjected to the same certification, standing and occupation checks the
        original booking faced."

        PRD: "Crucially, access_denial_count is not reset - the parcel that
        denied access once starts the next round with one denial already banked,
        so the very next denial abandons the inspection."

        Design: Difficulty/non_linear_state_machine/inspection_denial_reschedule_loop_terminates_in_abandoned
        """
        world = noticed_world(
            client,
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
        )
        inspection_id = world["inspection"]["id"]
        inspector_id = world["inspector"]["id"]

        denied = _deny_access(client, inspection_id, inspector_id)
        assert denied["status"] == "ACCESS_DENIED"
        assert denied["access_denial_count"] == 1

        rebooked = validate_success(
            client.reschedule_inspection(
                inspection_id,
                reschedule_payload("2026-08-25T15:00:00Z", "2026-08-25T17:00:00Z"),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )
        assert rebooked["status"] == "SCHEDULED"
        assert rebooked["notice_method"] is None
        assert rebooked["notice_sent_at_utc"] is None
        assert rebooked["access_denial_count"] == 1

        renoticed = serve_notice(client, inspection_id, "CERTIFIED_MAIL")
        assert renoticed["status"] == "NOTICED"
        assert_instant(renoticed["scheduled_start_utc"], "2026-08-25T15:00:00Z")

    def test_second_denial_abandons_and_raises_a_critical_notice(self, client):
        """Refusing the district twice is itself a violation.

        PRD: "With access_denial_count already standing at 1 - one short of the
        district's ceiling of two denials per inspection - the count is
        incremented to 2 and the inspection moves NOTICED -> ABANDONED instead
        of to ACCESS_DENIED."

        PRD: "The system therefore raises a violation notice against parcel_id
        with severity forced to CRITICAL and notice_method forced to
        CERTIFIED_MAIL, resolving supersedes_notice_id exactly as the
        notice-creation rules in section 3.6 prescribe. Because a notice now exists on
        the parcel, the parcel's compliance_status becomes NON_COMPLIANT and its
        open_violation_count rises by 1."

        PRD: "A third denial attempt has nowhere to go and is refused with
        ERR_ACCESS_DENIAL_LIMIT_REACHED, as is any denial recorded against an
        inspection already sitting in ABANDONED. ABANDONED is terminal."

        Design: Difficulty/non_linear_state_machine/inspection_denial_reschedule_loop_terminates_in_abandoned
        """
        world = noticed_world(
            client,
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
        )
        inspection_id = world["inspection"]["id"]
        inspector_id = world["inspector"]["id"]
        parcel_id = world["parcel"]["id"]

        _deny_access(client, inspection_id, inspector_id)
        validate_success(
            client.reschedule_inspection(
                inspection_id,
                reschedule_payload("2026-08-25T15:00:00Z", "2026-08-25T17:00:00Z"),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )
        serve_notice(client, inspection_id, "CERTIFIED_MAIL")

        abandoned = _deny_access(client, inspection_id, inspector_id, "OWNER_REFUSED")
        assert abandoned["status"] == "ABANDONED"
        assert abandoned["access_denial_count"] == 2
        assert_instant(abandoned["scheduled_start_utc"], "2026-08-25T15:00:00Z")

        notices, meta = list_notices(client, parcel_id=parcel_id)
        assert meta["total_count"] == 1
        notice = notices[0]
        assert notice["inspection_id"] == inspection_id
        assert notice["notice_method"] == "CERTIFIED_MAIL"
        # The clock never moved, so the citation was issued on 2026-08-01 and
        # certified mail adds five days of service before the 14 day clock runs.
        assert_notice_schedule(
            notice,
            severity="CRITICAL",
            delivered_at_utc="2026-08-06T00:00:00Z",
            compliance_days=14,
            deadline_date="2026-08-20",
            status="ISSUED",
        )

        parcel = get_parcel(client, parcel_id)
        assert_posture(parcel, "NON_COMPLIANT", open_violation_count=1)

        third = client.record_access_denial(
            inspection_id,
            headers=make_inspector_headers(inspector_id),
            payload=access_denial_payload("GATE_LOCKED"),
        )
        validate_error(third, ERR_ACCESS_DENIAL_LIMIT_REACHED)
        assert get_inspection(client, inspection_id)["status"] == "ABANDONED"
