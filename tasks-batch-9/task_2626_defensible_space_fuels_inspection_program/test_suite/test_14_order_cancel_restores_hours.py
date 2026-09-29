"""Cancelling an awarded order restores the crew-hour ledger exactly."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assert_hours,
    assert_posture,
    authorize_abatement,
    award_order,
    awarded_world,
    get_contractor,
    get_notice,
    get_order,
    get_parcel,
    reason_payload,
)
from test_helpers.test_users import FIRE_MARSHAL_HEADERS

WORK_WINDOW = ("2026-10-05T08:00:00Z", "2026-10-05T18:00:00Z")


def _awarded_abatement(client):
    """One overdue citation, authorized for 200000 cents and awarded 12.5 hours."""
    return awarded_world(
        client,
        crew_hours=12.5,
        work_start_utc=WORK_WINDOW[0],
        work_end_utc=WORK_WINDOW[1],
        fail_at="2026-08-22T00:00:00Z",
        overdue_at="2026-10-01T00:00:00Z",
        authorize_at="2026-10-01T00:00:00Z",
        estimated_cost_cents=200000,
    )


def _cancel(client, order_id, reason):
    return validate_success(
        client.cancel_order(
            order_id, reason_payload(reason), headers=FIRE_MARSHAL_HEADERS
        )
    )


class TestOrderCancelCompensation:
    """The award is undone to exactly its pre-award value, and nothing else moves."""

    def test_cancel_returns_committed_hours_and_reverts_the_enforcement_chain(
        self, client
    ):
        """The reservation is released, the citation falls back to OVERDUE and the
        completed-hours ledger is untouched.

        PRD: "The AWARDED path does one thing more - it decreases the contractor's
        committed_crew_hours by the order's crew_hours, restoring that counter to
        precisely its pre-award value - whereas the AUTHORIZED path has no
        reservation to unwind."

        PRD: "Both paths revert the enforcement chain: the referenced notice
        returns ABATEMENT_AUTHORIZED -> OVERDUE and the parcel's compliance_status
        reverts to NON_COMPLIANT, exactly undoing what authorization did."

        PRD: "Cancelling an awarded order returns committed_crew_hours to what it
        was before the award."

        PRD: "its completed_crew_hours is a lifetime tally that only ever grows."

        Design: Difficulty/compensating_invariant/contractor_committed_crew_hours_restored_on_order_cancel
        """
        world = _awarded_abatement(client)
        contractor_id = world["contractor"]["id"]
        assert_hours(
            get_contractor(client, contractor_id)["committed_crew_hours"], 12.5
        )
        assert world["notice"]["status"] == "ABATEMENT_AUTHORIZED"
        assert_posture(world["parcel"], "ABATEMENT_PENDING", open_violation_count=1)

        cancelled = _cancel(
            client, world["order"]["id"], "owner completed the work voluntarily"
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "owner completed the work voluntarily"
        assert cancelled["actual_crew_hours"] is None
        assert cancelled["total_recoverable_cents"] is None

        contractor = get_contractor(client, contractor_id)
        assert_hours(contractor["committed_crew_hours"], 0.0)
        assert_hours(contractor["completed_crew_hours"], 0.0)

        notice = get_notice(client, world["notice"]["id"])
        assert notice["status"] == "OVERDUE"
        assert notice["cleared_at_utc"] is None
        assert_posture(
            get_parcel(client, world["parcel"]["id"]),
            "NON_COMPLIANT",
            open_violation_count=1,
        )

    def test_two_award_and_cancel_round_trips_leave_no_drift(self, client):
        """The notice can be authorized again once no live order stands on it, and
        the second round trip also lands committed_crew_hours back on 0.

        PRD: "A notice that already carries a live order - one standing in
        AUTHORIZED, AWARDED, WORK_COMPLETE or INVOICED - cannot be authorized a
        second time, and the attempt answers ERR_INVALID_STATE."

        PRD: "Because these are identities, every compensating operation must
        restore the counter to exactly its pre-operation value, not approximately
        and not by recomputation drift."

        Design: Difficulty/compensating_invariant/contractor_committed_crew_hours_restored_on_order_cancel
        """
        world = _awarded_abatement(client)
        contractor_id = world["contractor"]["id"]
        notice_id = world["notice"]["id"]

        _cancel(client, world["order"]["id"], "first attempt withdrawn")
        assert_hours(get_contractor(client, contractor_id)["committed_crew_hours"], 0.0)

        replacement = authorize_abatement(client, notice_id, 200000)
        assert replacement["status"] == "AUTHORIZED"
        assert replacement["id"] != world["order"]["id"]
        assert get_notice(client, notice_id)["status"] == "ABATEMENT_AUTHORIZED"

        awarded = award_order(
            client, replacement["id"], contractor_id, 12.5, *WORK_WINDOW
        )
        assert awarded["status"] == "AWARDED"
        assert_hours(
            get_contractor(client, contractor_id)["committed_crew_hours"], 12.5
        )

        _cancel(client, replacement["id"], "second attempt withdrawn")
        contractor = get_contractor(client, contractor_id)
        assert_hours(contractor["committed_crew_hours"], 0.0)
        assert_hours(contractor["completed_crew_hours"], 0.0)
        assert get_order(client, replacement["id"])["status"] == "CANCELLED"
        assert get_notice(client, notice_id)["status"] == "OVERDUE"
