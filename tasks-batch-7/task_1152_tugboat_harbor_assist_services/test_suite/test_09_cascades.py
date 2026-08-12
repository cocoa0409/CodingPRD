"""Multi-hop cascades and compensating invariants: gear failure cascade, cancel
compensation, finalize-then-void restoration, incident resolve recovery, no-show."""
import pytest

from test_helpers import (
    TEST_USERS,
    complete_job,
    confirm_assignment,
    confirm_booking,
    confirm_job_order,
    create_job_order,
    create_pilot,
    create_tariff_rate,
    create_tug,
    create_vessel,
    dispatch_job,
    finalize_invoice,
    get_invoice_for_job,
    get_job,
    propose_assignment,
    propose_pilot_booking,
    record_failed_inspection,
    record_passed_inspection,
    set_clock,
    setup_completed_job,
    setup_dispatched_job,
    setup_incident,
    start_job,
    validate_error,
    validate_success,
    void_invoice,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_tug_captain_headers


class TestGearFailureThreeHopCascade:
    """POST /api/gear-inspections FAILED -> tug RESTRICTED (hop 1) -> future
    CONFIRMED assignments SUPERSEDED (hop 2) -> their CONFIRMED jobs back to
    REQUESTED with needs_reassignment (hop 3)."""

    def _setup_confirmed_job(self):
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        job = confirm_job_order(job["id"])
        record_passed_inspection(tug["id"])
        asg = propose_assignment(
            job["id"],
            tug["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        confirm_assignment(asg["id"], tug["id"])
        return {"tug": tug, "vessel": vessel, "job": job, "assignment": asg}

    def test_failed_inspection_restricts_tug(self, api):
        """PRD §3.6: "A `FAILED` outcome restricts the tug immediately: an
        `AVAILABLE` tug becomes `RESTRICTED`."

        Design: Difficulty/transitive_cascade/gear_failure_three_hop_cascade
        """
        ctx = self._setup_confirmed_job()
        record_failed_inspection(
            ctx["tug"]["id"],
            inspection_item="TOW_LINE",
            inspected_at="2026-05-20T00:00:00Z",
            next_due_at="2026-06-20T00:00:00Z",
        )
        tug = validate_success(
            api.get_tug(ctx["tug"]["id"], TEST_USERS["port_dispatcher_headers"]), 200
        )
        assert tug["operational_status"] == "RESTRICTED"

    def test_cascade_supersedes_assignment_and_demotes_job(self, api):
        """PRD §3.6: "Every `CONFIRMED` assignment of that tug whose `window_start`
        lies strictly after the current logical-clock reading becomes `SUPERSEDED`
        ... and each job stripped of a confirmed tug in this way, if itself still
        `CONFIRMED`, is demoted to `REQUESTED` with `needs_reassignment` set true."

        Design: Difficulty/transitive_cascade/gear_failure_three_hop_cascade
        """
        ctx = self._setup_confirmed_job()
        record_failed_inspection(
            ctx["tug"]["id"],
            inspection_item="TOW_LINE",
            inspected_at="2026-05-20T00:00:00Z",
            next_due_at="2026-06-20T00:00:00Z",
        )
        asg = validate_success(
            api.get_tug_assignment(
                ctx["assignment"]["id"], TEST_USERS["port_dispatcher_headers"]
            ),
            200,
        )
        assert asg["status"] == "SUPERSEDED"
        job = get_job(ctx["job"]["id"])
        assert job["status"] == "REQUESTED"
        assert job["needs_reassignment"] is True


class TestCancelRestoresCommitmentCounts:
    """Compensating invariant: confirm pair followed by job cancel returns the
    non-terminal commitment counts on both resources to zero."""

    def _setup_confirmed_job_with_pair(self):
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        pilot = create_pilot(name="Pilot Reyes", license_class="CLASS_I")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        job = confirm_job_order(job["id"])
        record_passed_inspection(tug["id"])
        asg = propose_assignment(
            job["id"],
            tug["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        confirm_assignment(asg["id"], tug["id"])
        booking = propose_pilot_booking(
            job["id"],
            pilot["id"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        confirm_booking(booking["id"], pilot["id"])
        return {"tug": tug, "vessel": vessel, "pilot": pilot, "job": job,
                "assignment": asg, "booking": booking}

    def test_cancel_releases_assignment(self, api):
        """PRD §3.2: "Cancellation releases the job's open tug assignments — every
        one in `PROPOSED` or `CONFIRMED` status becomes `RELEASED`."

        Design: Difficulty/compensating_invariant/cancel_restores_tug_and_pilot_commitment_counts
        """
        ctx = self._setup_confirmed_job_with_pair()
        cancel_res = api.cancel_job_order(
            ctx["job"]["id"],
            {"cancel_reason": "Berth unavailable"},
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_success(cancel_res, 200)
        asg = validate_success(
            api.get_tug_assignment(
                ctx["assignment"]["id"], TEST_USERS["port_dispatcher_headers"]
            ),
            200,
        )
        assert asg["status"] == "RELEASED"

    def test_cancel_cancels_booking(self, api):
        """PRD §3.2: "Cancellation releases the job's open tug assignments — every
        one in `PROPOSED` or `CONFIRMED` status becomes `RELEASED` — and cancels
        its open pilot bookings — every one in `REQUESTED` or `CONFIRMED` status
        becomes `CANCELLED`."

        Design: Difficulty/compensating_invariant/cancel_restores_tug_and_pilot_commitment_counts
        """
        ctx = self._setup_confirmed_job_with_pair()
        cancel_res = api.cancel_job_order(
            ctx["job"]["id"],
            {"cancel_reason": "Berth unavailable"},
            TEST_USERS["port_dispatcher_headers"],
        )
        cancelled = validate_success(cancel_res, 200)
        assert cancelled["status"] == "CANCELLED"
        booking = validate_success(
            api.get_pilot_booking(
                ctx["booking"]["id"], TEST_USERS["port_dispatcher_headers"]
            ),
            200,
        )
        assert booking["status"] == "CANCELLED"


class TestFinalizeThenVoidRestoresOutstanding:
    """Forward pair (complete creates the invoice, finalize keeps it counted)
    followed by compensating void returns outstanding_billed_cents to zero."""

    def test_finalize_keeps_outstanding_counted(self, api):
        """PRD §3.9: "the sum of `total_cents` over every invoice of the vessel's
        jobs in `PROVISIONAL` or `FINALIZED` status, minus the sum of `payout_cents`
        over the vessel's `SETTLED` claims, floored at zero."

        Design: Difficulty/compensating_invariant/finalize_then_void_restores_vessel_outstanding
        """
        ctx = setup_completed_job()
        vessel_after_complete = validate_success(
            api.get_vessel(ctx["vessel"]["id"], TEST_USERS["port_dispatcher_headers"]),
            200,
        )
        assert vessel_after_complete["outstanding_billed_cents"] == 740000
        inv = ctx["invoice"]
        finalized = finalize_invoice(inv["id"], inv["version"])
        assert finalized["status"] == "FINALIZED"
        vessel_after_finalize = validate_success(
            api.get_vessel(ctx["vessel"]["id"], TEST_USERS["port_dispatcher_headers"]),
            200,
        )
        assert vessel_after_finalize["outstanding_billed_cents"] == 740000

    def test_void_returns_outstanding_to_zero(self, api):
        """PRD §3.8: "Voiding excludes the invoice from the vessel's outstanding
        balance, which is recomputed accordingly."

        Design: Difficulty/compensating_invariant/finalize_then_void_restores_vessel_outstanding
        """
        ctx = setup_completed_job()
        inv = ctx["invoice"]
        finalize_invoice(inv["id"], inv["version"])
        voided = void_invoice(inv["id"], void_reason="Billing dispute")
        assert voided["status"] == "VOID"
        vessel_after_void = validate_success(
            api.get_vessel(ctx["vessel"]["id"], TEST_USERS["port_dispatcher_headers"]),
            200,
        )
        assert vessel_after_void["outstanding_billed_cents"] == 0


class TestIncidentResolveRecovery:
    def test_incident_resolve_restores_tug_available(self, api, marine_surveyor_headers):
        """PRD §3.6: "Closing the tug's last unresolved `MAJOR` or `CRITICAL`
        incident reopens the question of its availability: if the latest inspection
        of every gear item is `PASSED`, the tug returns directly from
        `OUT_OF_SERVICE` to `AVAILABLE`."

        Design: Corner/state_machines/incident_resolve_restores_tug_available
        """
        ctx = setup_incident(
            passed_inspection_first=True,
            incident_overrides={
                "incident_type": "GEAR_FAILURE",
                "severity": "MAJOR",
                "occurred_at": "2026-06-01T09:00:00Z",
                "description": "Winch failure under load",
            },
        )
        tug_mid = validate_success(
            api.get_tug(ctx["tug"]["id"], marine_surveyor_headers), 200
        )
        assert tug_mid["operational_status"] == "OUT_OF_SERVICE"
        res = api.resolve_incident(
            ctx["incident"]["id"],
            {"resolution_notes": "Winch repaired and load-tested"},
            marine_surveyor_headers,
        )
        incident = validate_success(res, 200)
        assert incident["status"] == "RESOLVED"
        tug_end = validate_success(
            api.get_tug(ctx["tug"]["id"], marine_surveyor_headers), 200
        )
        assert tug_end["operational_status"] == "AVAILABLE"


class TestPilotNoShowOnComplete:
    def test_pilot_booking_no_show_on_job_complete(self, api):
        """PRD §3.4: "Job completion separates the committed from the absent: a
        `BOARDED` booking becomes `COMPLETED`, while a booking still merely
        `CONFIRMED` is marked `NO_SHOW`."

        Design: Corner/state_machines/pilot_booking_no_show_on_job_complete
        """
        ctx = setup_dispatched_job()  # booking CONFIRMED but never BOARDED
        set_clock("2026-06-01T08:00:00Z")
        start_job(ctx["job"]["id"])
        complete_job(ctx["job"]["id"])
        booking = validate_success(
            api.get_pilot_booking(
                ctx["booking"]["id"], TEST_USERS["port_dispatcher_headers"]
            ),
            200,
        )
        assert booking["status"] == "NO_SHOW"
