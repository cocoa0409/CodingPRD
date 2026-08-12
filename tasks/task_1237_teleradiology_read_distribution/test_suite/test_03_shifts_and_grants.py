"""Coverage shifts and credential grants: clock sweeps, overlap semantics,
and the grant lifecycle cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_hospital,
    create_credential_grant_payload,
    create_granted_credential,
    create_radiologist,
    create_shift_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestShiftOverlapHalfOpen:
    def test_adjacent_shift_allowed_under_half_open_semantics(self, api):
        """PRD section 3.2: "The window is a half-open interval — it includes
        `starts_at` and excludes `ends_at` — and `ends_at` must lie strictly
        after `starts_at`. One radiologist may not hold two shifts whose
        half-open windows overlap while both are in `SCHEDULED` or `ACTIVE`
        status; such a collision is rejected with `ERR_SHIFT_OVERLAP`, though
        windows that merely touch — one ending exactly where the next begins —
        are allowed."

        Design: Difficulty/resource_temporal_overlap/shift_overlap_half_open_adjacency
        """
        rad = create_radiologist(full_name="Shift Rad", subspecialties=["BODY"])
        validate_success(api.create_shift(create_shift_payload(
            rad["id"], starts_at="2026-05-01T08:00:00Z",
            ends_at="2026-05-01T16:00:00Z", modalities=["CT"]), ADMIN), 201)
        # Adjacent: starts exactly when shift A ends — allowed.
        resp = api.create_shift(create_shift_payload(
            rad["id"], starts_at="2026-05-01T16:00:00Z",
            ends_at="2026-05-01T20:00:00Z", modalities=["MR"]), ADMIN)
        data = validate_success(resp, 201)
        assert data["status"] == "SCHEDULED"

    def test_one_minute_overlap_rejected(self, api):
        """PRD section 3.2: "One radiologist may not hold two shifts whose
        half-open windows overlap while both are in `SCHEDULED` or `ACTIVE`
        status; such a collision is rejected with `ERR_SHIFT_OVERLAP`, though
        windows that merely touch — one ending exactly where the next begins —
        are allowed."

        Design: Difficulty/resource_temporal_overlap/shift_overlap_half_open_adjacency
        """
        rad = create_radiologist(full_name="Shift Rad 2", subspecialties=["BODY"])
        validate_success(api.create_shift(create_shift_payload(
            rad["id"], starts_at="2026-05-01T08:00:00Z",
            ends_at="2026-05-01T16:00:00Z", modalities=["CT"]), ADMIN), 201)
        # Overlaps by one minute (15:59 < 16:00).
        resp = api.create_shift(create_shift_payload(
            rad["id"], starts_at="2026-05-01T15:59:00Z",
            ends_at="2026-05-01T21:00:00Z", modalities=["CT"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP, 409)
        _shifts, meta = validate_paginated(
            api.list_shifts(ADMIN, params={"radiologist_id": rad["id"]}))
        assert meta["total_count"] == 1


class TestShiftClockSweep:
    def test_clock_sweep_activates_then_completes_shift(self, api):
        """PRD section 3.2: "A shift starts `SCHEDULED`; when the logical clock
        enters its window (at or after `starts_at` and before `ends_at`), the
        sweep transitions `SCHEDULED → ACTIVE` and the radiologist becomes
        shift-eligible for the window's modalities. When the clock reaches or
        passes `ends_at`, the sweep transitions `ACTIVE → COMPLETED`..."

        Design: Corner/state_machines/clock_sweep_activates_then_completes_shift
        """
        rad = create_radiologist(full_name="Sweep Rad", subspecialties=["BODY"])
        shift = validate_success(api.create_shift(create_shift_payload(
            rad["id"], starts_at="2026-05-01T08:00:00Z",
            ends_at="2026-05-01T16:00:00Z", modalities=["CT"]), ADMIN), 201)
        # Startup clock is exactly 2026-05-01T00:00:00Z, before the window.
        assert shift["status"] == "SCHEDULED"

        set_clock("2026-05-01T09:00:00Z")
        mid = get_success_data(api.get_shift(shift["id"], ADMIN))
        assert mid["status"] == "ACTIVE"

        set_clock("2026-05-01T16:00:00Z")
        end = get_success_data(api.get_shift(shift["id"], ADMIN))
        assert end["status"] == "COMPLETED"


class TestGrantOverlapInclusiveDay:
    def test_grant_sharing_inclusive_last_day_rejected(self, api):
        """PRD section 3.3: "Because the window is inclusive of both days, two
        grants for the same radiologist–hospital pair in any of the statuses
        `PENDING`, `GRANTED`, or `SUSPENDED` may not share even a single
        calendar day; an overlap is rejected with `ERR_GRANT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/grant_overlap_inclusive_day_semantics
        """
        hosp = create_active_hospital(name="Hosp Over", state_code="CA")
        rad = create_radiologist(full_name="Grant Rad", subspecialties=["BODY"])
        create_granted_credential(rad["id"], hosp["id"],
                                  valid_from="2026-01-01", valid_until="2026-12-31")
        # Shares the inclusive last day 2026-12-31 -> rejected.
        resp = api.create_credential_grant(create_credential_grant_payload(
            rad["id"], hosp["id"], valid_from="2026-12-31",
            valid_until="2027-06-30"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_GRANT_OVERLAP, 409)

    def test_grant_starting_next_day_allowed(self, api):
        """PRD section 3.3: "Because the window is inclusive of both days, two
        grants for the same radiologist–hospital pair in any of the statuses
        `PENDING`, `GRANTED`, or `SUSPENDED` may not share even a single
        calendar day; an overlap is rejected with `ERR_GRANT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/grant_overlap_inclusive_day_semantics
        """
        hosp = create_active_hospital(name="Hosp Over 2", state_code="CA")
        rad = create_radiologist(full_name="Grant Rad 2", subspecialties=["BODY"])
        create_granted_credential(rad["id"], hosp["id"],
                                  valid_from="2026-01-01", valid_until="2026-12-31")
        # 2027-01-01 shares no calendar day with the existing grant.
        resp = api.create_credential_grant(create_credential_grant_payload(
            rad["id"], hosp["id"], valid_from="2027-01-01",
            valid_until="2027-12-31"), ADMIN)
        data = validate_success(resp, 201)
        assert data["status"] == "PENDING"


class TestGrantClockExpiry:
    def test_clock_sweep_expires_grant_after_valid_until(self, api):
        """PRD section 3.3: "When the logical clock's date passes `valid_until`,
        the sweep moves `GRANTED → EXPIRED`, again stripping eligibility."

        Design: Corner/state_machines/clock_sweep_expires_grant_after_valid_until
        """
        hosp = create_active_hospital(name="Hosp Exp", state_code="CA")
        rad = create_radiologist(full_name="Exp Rad", subspecialties=["BODY"])
        grant = create_granted_credential(rad["id"], hosp["id"],
                                          valid_from="2026-01-01",
                                          valid_until="2026-12-31")
        assert grant["status"] == "GRANTED"

        # Still GRANTED at the last valid day's final second.
        set_clock("2026-12-31T23:59:59Z")
        on_last_day = get_success_data(api.get_credential_grant(grant["id"], ADMIN))
        assert on_last_day["status"] == "GRANTED"

        # First day past valid_until -> EXPIRED.
        set_clock("2027-01-01T00:00:00Z")
        expired = get_success_data(api.get_credential_grant(grant["id"], ADMIN))
        assert expired["status"] == "EXPIRED"


class TestGrantTypeMismatch:
    def test_grant_type_mismatch_rejected(self, api):
        """PRD section 3.3: "The `grant_type` must equal the hospital's
        `credentialing_mode`; a mismatch is rejected with
        `ERR_GRANT_TYPE_MISMATCH`."

        Design: Corner/validations/grant_type_mismatch_rejected
        """
        # BY_PROXY hospital (default) rejects an INDEPENDENT application.
        hosp = create_active_hospital(name="Hosp GT", state_code="CA")
        rad = create_radiologist(full_name="GT Rad", subspecialties=["BODY"])
        resp = api.create_credential_grant(create_credential_grant_payload(
            rad["id"], hosp["id"], grant_type="INDEPENDENT"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_GRANT_TYPE_MISMATCH, 422)


class TestGrantSuspendRenewalCycle:
    def test_grant_suspend_then_reinstate_loop(self, api):
        """PRD section 3.3: "Granting moves `PENDING → GRANTED`; suspension
        moves `GRANTED → SUSPENDED`, during which the radiologist fails
        credential eligibility for that hospital; reinstatement moves
        `SUSPENDED → GRANTED` but only while the current day has not passed
        `valid_until` — a grant whose day has passed must expire first."

        Design: Difficulty/non_linear_state_machine/credential_grant_suspend_renewal_cycle
        """
        hosp = create_active_hospital(name="Hosp Cred A", state_code="CA")
        rad = create_radiologist(full_name="Rad C", subspecialties=["BODY"])
        grant = validate_success(api.create_credential_grant(
            create_credential_grant_payload(rad["id"], hosp["id"]), ADMIN), 201)
        granted = validate_success(api.grant_credential(grant["id"], ADMIN), 200)
        assert granted["status"] == "GRANTED"
        suspended = validate_success(api.suspend_credential(grant["id"], ADMIN), 200)
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_credential(grant["id"], ADMIN), 200)
        assert reinstated["status"] == "GRANTED"

    def test_grant_expire_then_renew_cycle(self, api):
        """PRD section 3.3: "When the logical clock's date passes `valid_until`,
        the sweep moves `GRANTED → EXPIRED`, again stripping eligibility. An
        expired grant can be renewed: renewal moves `EXPIRED → PENDING` and
        installs a fresh `valid_from` and `valid_until` from the payload,
        subject to the same inclusive-day overlap check against the pair's other
        non-terminal grants."
        PRD section 2.4: "`version` (integer): a system-managed integer that
        increments by exactly 1 on every mutation of the resource, including
        mutations caused by cascades and clock sweeps."

        Design: Difficulty/non_linear_state_machine/credential_grant_suspend_renewal_cycle
        """
        hosp = create_active_hospital(name="Hosp Cred B", state_code="CA")
        rad = create_radiologist(full_name="Rad C2", subspecialties=["BODY"])
        grant = validate_success(api.create_credential_grant(
            create_credential_grant_payload(rad["id"], hosp["id"]), ADMIN), 201)
        validate_success(api.grant_credential(grant["id"], ADMIN), 200)
        set_clock("2027-01-02T00:00:00Z")
        expired = get_success_data(api.get_credential_grant(grant["id"], ADMIN))
        assert expired["status"] == "EXPIRED"

        renewed = validate_success(api.renew_credential(
            grant["id"], {"valid_from": "2027-01-01", "valid_until": "2027-12-31"},
            ADMIN), 200)
        assert renewed["status"] == "PENDING"
        assert renewed["valid_from"] == "2027-01-01"
        final = validate_success(api.grant_credential(grant["id"], ADMIN), 200)
        assert final["status"] == "GRANTED"
        # create -> v1, grant -> v2, expire sweep -> v3, renew -> v4,
        # second grant -> v5; every mutation increments version by exactly 1.
        assert final["version"] == 5
