"""Permit suspension, re-entry authorization, and orderly closure
(PRD §3.4, §3.5)."""
from datetime import datetime

from test_helpers import (
    OPS as OPS_HEADERS,
    ApiErrorId,
    add_on_duty_attendant,
    add_on_duty_entrant,
    post_reading,
    read_permit,
    read_standby,
    report_incident,
    resume_permit,
    set_clock,
    setup_active_permit,
    setup_issued_permit,
    submit_isolation,
    suspend_permit,
    validate_error,
    validate_success,
    verify_isolation_record,
)


def _ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp tolerantly of fractional formatting."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestSuspendResumeCycle:
    def test_suspend_resume_cycle_traversed_twice(self, api):
        """PRD §3.5: "Orderly manual suspension from `ACTIVE` — available to
        an `EntrySupervisor` or `SafetyOfficer`, optionally with a `reason` —
        requires the space to be empty of on-duty entrants
        (`ERR_ENTRANTS_STILL_INSIDE`); it increments `suspension_count` and
        stamps `last_suspended_at`." and "Resumption — re-entry authorization
        from `SUSPENDED` back to `ACTIVE` by an `EntrySupervisor` — reruns the
        safety chain in order: an `APPROVED` rescue plan must exist (a plan
        superseded while the permit was suspended fails with
        `ERR_RESCUE_PLAN_NOT_APPROVED`); required isolation types must hold
        unexpired `VERIFIED` verifications (`ERR_ISOLATION_NOT_VERIFIED`); a
        `PRE_ENTRY` reading recorded **after** `last_suspended_at` must exist
        and be within limits (`ERR_ATMOSPHERE_OUT_OF_LIMITS`); that reading
        must be no more than 30 minutes old (`ERR_PRE_ENTRY_READING_STALE`);
        and no open incidents may exist on the permit
        (`ERR_OPEN_INCIDENTS_EXIST`). Successful resumption increments
        `reentry_count`."

        Design: Difficulty/non_linear_state_machine/permit_suspend_resume_reentry_cycle
        """
        ctx = setup_active_permit(
            at="2026-08-03T05:30:00Z",
            space_overrides={"ventilation_required": True})
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]

        # First loop: suspend at 10:00, fresh post-suspension reading, resume.
        set_clock("2026-08-03T10:00:00Z")
        suspended = suspend_permit(permit_id, team["supervisor_headers"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_count"] == 1
        set_clock("2026-08-03T10:05:00Z")
        post_reading(permit_id, team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        set_clock("2026-08-03T10:10:00Z")
        resumed = resume_permit(permit_id, team["supervisor_headers"])
        assert resumed["status"] == "ACTIVE"
        assert resumed["reentry_count"] == 1

        # Second loop proves the cycle is re-entrant, not one-way.
        set_clock("2026-08-03T11:00:00Z")
        suspend_permit(permit_id, team["supervisor_headers"])
        set_clock("2026-08-03T11:05:00Z")
        post_reading(permit_id, team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        set_clock("2026-08-03T11:10:00Z")
        resumed2 = resume_permit(permit_id, team["supervisor_headers"])
        assert resumed2["status"] == "ACTIVE"
        assert resumed2["suspension_count"] == 2
        assert resumed2["reentry_count"] == 2, (
            "the ACTIVE -> SUSPENDED -> ACTIVE cycle was traversed twice")

    def test_resume_requires_post_suspension_reading(self, api):
        """PRD §3.5: "a `PRE_ENTRY` reading recorded **after**
        `last_suspended_at` must exist and be within limits
        (`ERR_ATMOSPHERE_OUT_OF_LIMITS`)".

        Design: Difficulty/non_linear_state_machine/permit_suspend_resume_reentry_cycle
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]

        set_clock("2026-08-03T10:00:00Z")
        suspend_permit(permit_id, team["supervisor_headers"])
        # The only PRE_ENTRY reading predates last_suspended_at; no fresh
        # reading is posted, so the resume atmosphere check fails.
        set_clock("2026-08-03T10:10:00Z")
        resp = api.resume_permit(permit_id, team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_ATMOSPHERE_OUT_OF_LIMITS)
        permit = read_permit(permit_id)
        assert permit["status"] == "SUSPENDED"
        assert permit["reentry_count"] == 0

    def test_resume_stale_reading_rejected(self, api):
        """PRD §3.5: "that reading must be no more than 30 minutes old
        (`ERR_PRE_ENTRY_READING_STALE`)".
        PRD §3.3: "fourth, that reading must be fresh — recorded no more than
        30 minutes before now, with exactly 30 minutes acceptable and 30
        minutes plus one second failing (`ERR_PRE_ENTRY_READING_STALE`)".

        Design: Corner/state_machines/corner_resume_stale_reading_rejected
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]

        set_clock("2026-08-03T10:00:00Z")
        suspend_permit(permit_id, team["supervisor_headers"])
        set_clock("2026-08-03T10:05:00Z")
        post_reading(permit_id, team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        # Resume at 10:36: the reading is 31 minutes old, one minute past the
        # inclusive 30-minute bound.
        set_clock("2026-08-03T10:36:00Z")
        resp = api.resume_permit(permit_id, team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_PRE_ENTRY_READING_STALE)
        permit = read_permit(permit_id)
        assert permit["status"] == "SUSPENDED"
        assert permit["reentry_count"] == 0

    def test_resume_blocked_by_expired_verification(self, api):
        """PRD §3.5: "required isolation types must hold unexpired `VERIFIED`
        verifications (`ERR_ISOLATION_NOT_VERIFIED`)".
        PRD §3.4: "A `VERIFIED` verification remains valid strictly until its
        `expires_at`; at the exact instant now equals `expires_at`, the clock
        sweep moves it to `EXPIRED`, and an expired verification no longer
        satisfies the activation or resume chain."

        Design: Corner/state_machines/corner_resume_blocked_by_expired_verification
        """
        ctx = setup_active_permit(
            at="2026-08-03T05:30:00Z",
            space_overrides={"ventilation_required": True})
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]
        iso = ctx["isolations"][0]

        set_clock("2026-08-03T10:00:00Z")
        suspend_permit(permit_id, team["supervisor_headers"])
        # Verified at 05:30, expires 17:30. Move past expiry; the sweep marks
        # the verification EXPIRED.
        set_clock("2026-08-03T17:31:00Z")
        iso_after = validate_success(
            api.get_isolation_verification(iso["id"],
                                           team["officer_headers"]))
        assert iso_after["status"] == "EXPIRED"

        # A zero-minute-old reading cannot rescue an expired isolation: the
        # isolation check precedes the reading checks in the resume order.
        post_reading(permit_id, team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        resp = api.resume_permit(permit_id, team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_ISOLATION_NOT_VERIFIED)
        permit = read_permit(permit_id)
        assert permit["status"] == "SUSPENDED"
        assert permit["reentry_count"] == 0


class TestVerificationExpiry:
    def test_verification_expiry_sweep_boundary(self, api):
        """PRD §3.4: "Verification is a second-person control: a
        `SafetyOfficer` verifies a `PENDING` record, which sets `verified_by`,
        stamps `verified_at` with the current logical time, and computes
        `expires_at` as exactly 12 hours after `verified_at`." and "A
        `VERIFIED` verification remains valid strictly until its `expires_at`;
        at the exact instant now equals `expires_at`, the clock sweep moves it
        to `EXPIRED`, and an expired verification no longer satisfies the
        activation or resume chain."

        Design: Corner/state_machines/corner_verification_expiry_sweep_boundary
        """
        ctx = setup_issued_permit(at="2026-08-03T05:30:00Z", with_plan=False,
                                  space_overrides={
                                      "ventilation_required": True})
        team = ctx["team"]
        iso = submit_isolation(ctx["permit"]["id"], team["officer_headers"],
                               isolation_type="VENTILATION",
                               evidence_ref="vent-1")
        verified = verify_isolation_record(iso["id"], team["officer_headers"])
        assert verified["status"] == "VERIFIED"
        assert _ts(verified["expires_at"]) == _ts("2026-08-03T17:30:00Z"), (
            "expires_at = verified_at (05:30) + 12 hours")

        set_clock("2026-08-03T17:29:00Z")
        mid = validate_success(
            api.get_isolation_verification(iso["id"], team["officer_headers"]))
        assert mid["status"] == "VERIFIED", (
            "one minute before expires_at the verification is still valid")

        set_clock("2026-08-03T17:30:00Z")
        final = validate_success(
            api.get_isolation_verification(iso["id"], team["officer_headers"]))
        assert final["status"] == "EXPIRED", (
            "expiry is inclusive of expires_at: at now == expires_at the "
            "sweep moves the record to EXPIRED")


class TestPermitEndGameGates:
    def test_manual_suspend_blocked_with_entrants(self, api):
        """PRD §3.5: "Orderly manual suspension from `ACTIVE` — available to
        an `EntrySupervisor` or `SafetyOfficer`, optionally with a `reason` —
        requires the space to be empty of on-duty entrants
        (`ERR_ENTRANTS_STILL_INSIDE`); it increments `suspension_count` and
        stamps `last_suspended_at`. Manual suspension is distinct from the
        emergency paths of §3.6, which evacuate automatically."

        Design: Corner/state_machines/corner_manual_suspend_blocked_with_entrants
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]
        add_on_duty_attendant(ctx)
        entrant_entry = add_on_duty_entrant(ctx)

        resp = api.suspend_permit(permit_id, team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_ENTRANTS_STILL_INSIDE)
        assert resp.status_code == 409
        permit = read_permit(permit_id)
        assert permit["status"] == "ACTIVE", "no partial suspension"
        assert permit["suspension_count"] == 0
        entry_after = validate_success(
            api.get_roster_entry(entrant_entry["id"], OPS_HEADERS))
        assert entry_after["status"] == "ON_DUTY"

    def test_close_blocked_by_open_incident(self, api):
        """PRD §3.5: "It requires no on-duty roster entries
        (`ERR_ENTRANTS_STILL_INSIDE`) and no open incidents — any incident of
        the permit in `REPORTED`, `TRIAGED`, `ESCALATED`, or `REOPENED` blocks
        closure with `ERR_OPEN_INCIDENTS_EXIST`." and "Closure cascades:
        standby assignments in `ON_STANDBY` are released with billable fields
        computed, assignments in `SCHEDULED` are cancelled, assignments in
        `DEPLOYED` are left unchanged and must be released explicitly, roster
        entries in `SCHEDULED` are cancelled, and verifications in `PENDING` or
        `VERIFIED` are voided."

        Design: Corner/state_machines/corner_close_blocked_by_open_incident
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]
        suspend_permit(permit_id, team["supervisor_headers"])
        incident = report_incident(permit_id, team["supervisor_headers"],
                                   severity="MINOR", kind="EQUIPMENT",
                                   description="HVAC stutter")

        resp = api.close_permit(permit_id, team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_OPEN_INCIDENTS_EXIST)

        # Triage and resolve by the SafetyOfficer (reporter was the
        # supervisor, so segregation of duties is satisfied).
        validate_success(api.triage_incident(incident["id"],
                                             team["officer_headers"]))
        validate_success(api.resolve_incident(incident["id"],
                                              "Filter reseated",
                                              team["officer_headers"]))
        closed = validate_success(
            api.close_permit(permit_id, team["supervisor_headers"]))
        assert closed["status"] == "CLOSED"
        assert closed["close_reason"] == "COMPLETED"
        standby_after = read_standby(ctx["standby"]["id"])
        assert standby_after["status"] == "RELEASED", (
            "the close cascade releases the ON_STANDBY assignment")
