"""Shift scheduling: posture gating, half-open overlap, the weekly 60-hour budget,
unit counter conservation, temporal windows, and the posture cascade's conditional
reach (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_shift_assignment,
    assert_unit_counters,
    book_shift,
    create_unit,
    get_nurse,
    get_shift,
    get_unit,
    record_psv_verified,
    request_psv,
    run_sweep,
    set_clock,
    setup_credentialed_nurse,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, TEST_USERS

MGR1 = TEST_USERS["manager_1"]
SPEC1 = TEST_USERS["specialist_1"]


def _shift_count(nurse_id: str) -> int:
    _data, meta = validate_paginated(
        api_client.list_shift_assignments(MGR1, params={"nurse_id": nurse_id})
    )
    return meta["total_count"]


def _book_med_shift(nurse_id, unit_id, starts_at, ends_at):
    return api_client.create_shift_assignment(
        {"nurse_id": nurse_id, "unit_id": unit_id,
         "starts_at": starts_at, "ends_at": ends_at},
        MGR1,
    )


class TestShiftCreationGatedOnPosture:
    """Difficulty instance: shift_creation_gated_on_nurse_posture — shift creation is
    valid only while the nurse is ACTIVE/CLEAR; an expiry-driven posture flip rejects
    it, and renewal restoring CLEAR admits the identical request."""

    def _setup_gina_suspended(self):
        set_clock()
        ctx = setup_credentialed_nurse(
            full_name="Gina Gate", email="gina.gate@x.com",
            license_expires_on="2026-08-20",
        )
        unit = create_unit(name="MED", required_cert_types=[])
        set_clock("2026-08-21T00:00:00Z")
        run_sweep()
        return ctx, unit

    def test_shift_creation_rejected_when_posture_suspended(self):
        """PRD §3.6: "First the nurse must be `ACTIVE`, else `ERR_INVALID_NURSE_STATE`;
        then her posture must be `CLEAR`, else `ERR_NURSE_NOT_CLEAR`."

        Design: Difficulty/cross_entity_state_dependency/shift_creation_gated_on_nurse_posture
        """
        ctx, unit = self._setup_gina_suspended()
        nurse = ctx["nurse"]
        assert get_nurse(nurse["id"])["credential_posture"] == "SCHEDULING_SUSPENDED"

        resp = _book_med_shift(nurse["id"], unit["id"],
                               "2026-08-25T07:00:00Z", "2026-08-25T19:00:00Z")
        validate_error(resp, ApiErrorId.ERR_NURSE_NOT_CLEAR)
        assert _shift_count(nurse["id"]) == 0

    def test_shift_creation_succeeds_after_renewal_restores_clear(self):
        """PRD §3.2: "A successful renewal writes the license's `expires_on` to
        `new_expires_on` and lands the license in `ACTIVE` ... Either landing
        re-derives privilege (a `LICENSE_CHANGE` row when changed) and recomputes
        posture."
        PRD §3.6: "A successful booking is born `SCHEDULED`, and its hours and count
        fold into the unit's `scheduled_hours_total` and `active_assignment_count`
        immediately."

        Design: Difficulty/cross_entity_state_dependency/shift_creation_gated_on_nurse_posture
        """
        ctx, unit = self._setup_gina_suspended()
        nurse, lic = ctx["nurse"], ctx["license"]

        psv2 = request_psv(lic["id"], channel="BOARD_PORTAL")
        record_psv_verified(psv2["id"])
        renewed = validate_success(
            api_client.renew_license(lic["id"], {"new_expires_on": "2027-08-20"}, SPEC1),
            200,
        )
        assert renewed["status"] == "ACTIVE"
        assert get_nurse(nurse["id"])["credential_posture"] == "CLEAR", (
            "renewal restored practice authority; the deficit set is empty"
        )

        ok = validate_success(
            _book_med_shift(nurse["id"], unit["id"],
                            "2026-08-25T07:00:00Z", "2026-08-25T19:00:00Z"),
            201,
        )
        assert_shift_assignment(ok)
        assert ok["status"] == "SCHEDULED"


class TestHalfOpenAdjacency:
    """Difficulty instance: nurse_shift_half_open_adjacency — half-open
    [starts_at, ends_at) interval semantics on nurse availability."""

    def _setup_kara(self):
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Kara Adjacent",
                                       email="kara.adjacent@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        return ctx, unit

    def test_adjacent_shifts_allowed(self):
        """PRD §3.6: "The new interval must then not collide with any of the nurse's
        existing assignments in `SCHEDULED` or `IN_PROGRESS`: intervals are half-open,
        so one assignment ending exactly when another begins is allowed, while a true
        collision is `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/nurse_shift_half_open_adjacency
        """
        ctx, unit = self._setup_kara()
        nurse = ctx["nurse"]
        s1 = book_shift(nurse["id"], unit["id"],
                        "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        s2 = book_shift(nurse["id"], unit["id"],
                        "2026-08-10T19:00:00Z", "2026-08-11T07:00:00Z")
        assert s1["status"] == "SCHEDULED" and s2["status"] == "SCHEDULED", (
            "touching endpoints are not a conflict under half-open semantics"
        )
        assert _shift_count(nurse["id"]) == 2

    def test_interior_overlap_and_containment_rejected(self):
        """PRD §3.6: "...intervals are half-open, so one assignment ending exactly when
        another begins is allowed, while a true collision is `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/nurse_shift_half_open_adjacency
        """
        ctx, unit = self._setup_kara()
        nurse = ctx["nurse"]
        book_shift(nurse["id"], unit["id"],
                   "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        book_shift(nurse["id"], unit["id"],
                   "2026-08-10T19:00:00Z", "2026-08-11T07:00:00Z")

        resp_overlap = _book_med_shift(nurse["id"], unit["id"],
                                       "2026-08-10T12:00:00Z", "2026-08-10T20:00:00Z")
        validate_error(resp_overlap, ApiErrorId.ERR_SHIFT_OVERLAP)
        resp_contained = _book_med_shift(nurse["id"], unit["id"],
                                         "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        validate_error(resp_contained, ApiErrorId.ERR_SHIFT_OVERLAP)
        assert _shift_count(nurse["id"]) == 2, (
            "interior overlap and full containment are both rejected; only the two "
            "adjacent originals persist"
        )


class TestWeeklyHoursCap:
    """Difficulty instance: weekly_hours_exactly_60_allowed — the 3600-minute cap is
    strictly-greater; exactly 3600 is allowed."""

    def _setup_wren(self):
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Wren Weekly",
                                       email="wren.weekly@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        return ctx, unit

    def _book_five_12h(self, nurse_id, unit_id):
        first = None
        for day in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"):
            shift = book_shift(nurse_id, unit_id, f"{day}T07:00:00Z", f"{day}T19:00:00Z")
            first = first or shift
        return first

    def test_five_twelve_hour_shifts_land_exactly_at_cap(self):
        """PRD §3.6: "A total strictly greater than 3,600 minutes, which is 60 hours,
        is rejected; a total of exactly 3,600 minutes is allowed. The cap always
        compares integer minutes, never the rounded displayed hours."
        PRD §3.6: "Each assignment's displayed `hours` are its duration in minutes
        divided by 60, rounded half up to 2 decimals."

        Design: Difficulty/boundary_precision_check/weekly_hours_exactly_60_allowed
        """
        ctx, unit = self._setup_wren()
        nurse = ctx["nurse"]
        first = self._book_five_12h(nurse["id"], unit["id"])
        assert first["hours"] == pytest.approx(12.0, abs=0.01), (
            "720 minutes / 60 = 12.0 at 2 decimals"
        )
        assert _shift_count(nurse["id"]) == 5, (
            "the fifth booking lands its window at exactly 3600 minutes — allowed"
        )

    def test_sixty_hours_plus_eight_more_rejected(self):
        """PRD §3.6: "The budget is computed over a rolling seven-calendar-day window:
        from midnight UTC of the day six days before the new assignment's start date,
        up to but not including midnight UTC of the day after the start date."
        PRD §3.6: "A total strictly greater than 3,600 minutes, which is 60 hours, is
        rejected; ..."

        Design: Difficulty/boundary_precision_check/weekly_hours_exactly_60_allowed
        """
        ctx, unit = self._setup_wren()
        nurse = ctx["nurse"]
        self._book_five_12h(nurse["id"], unit["id"])

        resp = _book_med_shift(nurse["id"], unit["id"],
                               "2026-08-08T07:00:00Z", "2026-08-08T15:00:00Z")
        validate_error(resp, ApiErrorId.ERR_WEEKLY_HOURS_EXCEEDED)
        assert _shift_count(nurse["id"]) == 5, (
            "window [2026-08-02, 2026-08-09) holds all five prior shifts: "
            "3600 + 480 = 4080 > 3600"
        )

    def test_weekly_hours_window_slide_edge(self):
        """PRD §3.6: "The budget is computed over a rolling seven-calendar-day window:
        from midnight UTC of the day six days before the new assignment's start date,
        up to but not including midnight UTC of the day after the start date."
        PRD §3.6: "A total strictly greater than 3,600 minutes, which is 60 hours, is
        rejected; a total of exactly 3,600 minutes is allowed."

        Design: Corner/calculations/weekly_hours_window_slide_edge
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Wendy Slide",
                                       email="wendy.slide@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = ctx["nurse"]
        for day in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"):
            book_shift(nurse["id"], unit["id"], f"{day}T07:00:00Z", f"{day}T19:00:00Z")

        ok = validate_success(
            _book_med_shift(nurse["id"], unit["id"],
                            "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z"),
            201,
        )
        assert ok["status"] == "SCHEDULED", (
            "window [2026-08-04, 2026-08-11) excludes the 2026-08-03 shift: "
            "4*720 + 720 = 3600 == cap (allowed)"
        )
        assert _shift_count(nurse["id"]) == 6


class TestUnitHoursConservation:
    """Difficulty instance: shift_book_cancel_conserves_unit_hours — the book/cancel
    pair leaves the unit staffing ledger bit-identical to its pre-booking values."""

    def _setup_pam(self):
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Pam Ledger", email="pam.ledger@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        return ctx, unit

    def test_booking_folds_into_unit_counters(self):
        """PRD §3.6: "A successful booking is born `SCHEDULED`, and its hours and count
        fold into the unit's `scheduled_hours_total` and `active_assignment_count`
        immediately."
        PRD §3.6: "Each unit tracks two computed counters: `scheduled_hours_total`, the
        sum of `hours` over its assignments in `SCHEDULED` or `IN_PROGRESS`, kept at 2
        decimals, and `active_assignment_count`, the number of such assignments."

        Design: Difficulty/compensating_invariant/shift_book_cancel_conserves_unit_hours
        """
        ctx, unit = self._setup_pam()
        before = get_unit(unit["id"])
        assert_unit_counters(before, 0.0, 0)

        book_shift(ctx["nurse"]["id"], unit["id"],
                   "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        after = get_unit(unit["id"])
        assert_unit_counters(after, 12.0, 1)

    def test_cancel_releases_unit_counters_identically(self):
        """PRD §3.6: "A manager may instead cancel a `SCHEDULED` assignment: the shift
        lands `CANCELLED` with `cancel_reason` `MANUAL`, the unit counters are released
        the same way, and the nurse's posture recomputes — the cancelled assignment's
        unit requirements leave the snapshot set on the next recompute."

        Design: Difficulty/compensating_invariant/shift_book_cancel_conserves_unit_hours
        """
        ctx, unit = self._setup_pam()
        shift = book_shift(ctx["nurse"]["id"], unit["id"],
                           "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        cancelled = validate_success(api_client.cancel_shift(shift["id"], MGR1), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "MANUAL"
        after = get_unit(unit["id"])
        assert_unit_counters(after, 0.0, 0)


class TestShiftGatePriorityPairs:
    """Difficulty instances: shift_create_state_beats_safety and
    shift_create_constraint_beats_temporal — PRD §2.9 pins a single ordered validation
    pipeline, and PRD §3.6 pins the shift-create gate order."""

    def test_shift_create_state_beats_safety(self):
        """PRD §2.9: "Every request flows through a single ordered validation pipeline,
        and a request violating several checks receives the error from the earliest
        stage it fails."
        PRD §3.6: "First the nurse must be `ACTIVE`, else `ERR_INVALID_NURSE_STATE`;
        then her posture must be `CLEAR`, else `ERR_NURSE_NOT_CLEAR`. Next, every entry
        of the unit's `required_cert_types` must be backed by an `ACTIVE` certification
        of that type, else `ERR_UNIT_CERT_REQUIREMENT_UNMET`."

        Design: Difficulty/priority_pair_validation_conflict/shift_create_state_beats_safety
        """
        set_clock()
        ctx = setup_credentialed_nurse(
            full_name="Sven State", email="sven.state@x.com",
            license_expires_on="2026-08-20",
        )
        unit = create_unit(name="ICU", required_cert_types=["ACLS"])
        nurse = ctx["nurse"]
        set_clock("2026-08-21T00:00:00Z")
        run_sweep()
        assert get_nurse(nurse["id"])["credential_posture"] == "SCHEDULING_SUSPENDED"

        resp = _book_med_shift(nurse["id"], unit["id"],
                               "2026-08-25T07:00:00Z", "2026-08-25T19:00:00Z")
        validate_error(resp, ApiErrorId.ERR_NURSE_NOT_CLEAR)
        assert _shift_count(nurse["id"]) == 0

    def test_shift_create_state_beats_safety_repeat_attempt(self):
        """PRD §2.9: "Every request flows through a single ordered validation pipeline,
        and a request violating several checks receives the error from the earliest
        stage it fails."
        PRD §3.6: "First the nurse must be `ACTIVE`, else `ERR_INVALID_NURSE_STATE`;
        then her posture must be `CLEAR`, else `ERR_NURSE_NOT_CLEAR`. Next, every entry
        of the unit's `required_cert_types` must be backed by an `ACTIVE` certification
        of that type, else `ERR_UNIT_CERT_REQUIREMENT_UNMET`."

        Design: Difficulty/priority_pair_validation_conflict/shift_create_state_beats_safety
        """
        set_clock()
        ctx = setup_credentialed_nurse(
            full_name="Sven State", email="sven.state@x.com",
            license_expires_on="2026-08-20",
        )
        unit = create_unit(name="ICU", required_cert_types=["ACLS"])
        nurse = ctx["nurse"]
        # The safety violation is real: the nurse holds no ACTIVE ACLS cert at all.
        certs, cert_meta = validate_paginated(
            api_client.list_certifications(SPEC1, params={"nurse_id": nurse["id"],
                                                          "cert_type": "ACLS"})
        )
        assert cert_meta["total_count"] == 0
        set_clock("2026-08-21T00:00:00Z")
        run_sweep()
        assert get_nurse(nurse["id"])["credential_posture"] == "SCHEDULING_SUSPENDED"

        resp = _book_med_shift(nurse["id"], unit["id"],
                               "2026-08-26T07:00:00Z", "2026-08-26T19:00:00Z")
        validate_error(resp, ApiErrorId.ERR_NURSE_NOT_CLEAR)
        assert _shift_count(nurse["id"]) == 0

    def test_shift_create_constraint_beats_temporal(self):
        """PRD §2.9: "Every request flows through a single ordered validation pipeline,
        and a request violating several checks receives the error from the earliest
        stage it fails."
        PRD §3.6: "...a true collision is `ERR_SHIFT_OVERLAP`. Temporal checks follow —
        `ends_at` must be strictly after `starts_at` (`ERR_INVALID_DATE_RANGE`); the
        start date must not precede the current date (`ERR_SHIFT_IN_PAST`); ..."

        Design: Difficulty/priority_pair_validation_conflict/shift_create_constraint_beats_temporal
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Cora Constraint",
                                       email="cora.constraint@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = ctx["nurse"]
        book_shift(nurse["id"], unit["id"],
                   "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        set_clock("2026-08-15T00:00:00Z")

        resp = _book_med_shift(nurse["id"], unit["id"],
                               "2026-08-10T12:00:00Z", "2026-08-10T20:00:00Z")
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        assert _shift_count(nurse["id"]) == 1

    def test_shift_create_constraint_beats_temporal_contained_variant(self):
        """PRD §2.9: "Every request flows through a single ordered validation pipeline,
        and a request violating several checks receives the error from the earliest
        stage it fails."
        PRD §3.6: "...a true collision is `ERR_SHIFT_OVERLAP`. Temporal checks follow —
        ...the start date must not precede the current date (`ERR_SHIFT_IN_PAST`); ..."

        Design: Difficulty/priority_pair_validation_conflict/shift_create_constraint_beats_temporal
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Cora Constraint",
                                       email="cora.constraint@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = ctx["nurse"]
        original = book_shift(nurse["id"], unit["id"],
                              "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        set_clock("2026-08-15T00:00:00Z")

        # Fully contained in the original AND in the past: the constraint error wins.
        resp = _book_med_shift(nurse["id"], unit["id"],
                               "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        data, meta = validate_paginated(
            api_client.list_shift_assignments(MGR1, params={"nurse_id": nurse["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == original["id"] and data[0]["status"] == "SCHEDULED"


class TestShiftComputedAndTemporalRules:
    def test_shift_create_sets_computed_hours(self):
        """PRD §3.6: "Each assignment's displayed `hours` are its duration in minutes
        divided by 60, rounded half up to 2 decimals. A successful booking is born
        `SCHEDULED`, and its hours and count fold into the unit's
        `scheduled_hours_total` and `active_assignment_count` immediately."

        Design: Corner/endpoints/shift_create_sets_computed_hours
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Half Shift", email="half.shift@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        shift = book_shift(ctx["nurse"]["id"], unit["id"],
                           "2026-08-10T07:00:00Z", "2026-08-10T18:30:00Z")
        assert shift["hours"] == pytest.approx(11.5, abs=0.01), "690 minutes / 60"
        after = get_unit(unit["id"])
        assert_unit_counters(after, 11.5, 1)

    def test_shift_horizon_and_past_boundaries(self):
        """PRD §3.6: "Temporal checks follow — `ends_at` must be strictly after
        `starts_at` (`ERR_INVALID_DATE_RANGE`); the start date must not precede the
        current date (`ERR_SHIFT_IN_PAST`); and the start date must not lie beyond the
        scheduling horizon, 90 days past the current date
        (`ERR_SCHEDULING_HORIZON_EXCEEDED`)."

        Design: Corner/validations/shift_horizon_and_past_boundaries
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Hor Izon", email="hor.izon@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = ctx["nurse"]

        ok = validate_success(
            _book_med_shift(nurse["id"], unit["id"],
                            "2026-10-30T07:00:00Z", "2026-10-30T19:00:00Z"),
            201,
        )
        assert ok["status"] == "SCHEDULED", "current_date + 90 days exactly is allowed"

        resp_horizon = _book_med_shift(nurse["id"], unit["id"],
                                       "2026-10-31T07:00:00Z", "2026-10-31T19:00:00Z")
        validate_error(resp_horizon, ApiErrorId.ERR_SCHEDULING_HORIZON_EXCEEDED)

        set_clock("2026-08-10T00:00:00Z")
        resp_past = _book_med_shift(nurse["id"], unit["id"],
                                    "2026-08-09T07:00:00Z", "2026-08-09T19:00:00Z")
        validate_error(resp_past, ApiErrorId.ERR_SHIFT_IN_PAST)
        assert _shift_count(nurse["id"]) == 1

    def test_shift_start_outside_window_rejected(self):
        """PRD §3.6: "Starting an assignment moves it from `SCHEDULED` to `IN_PROGRESS`
        — from any other state the attempt is `ERR_INVALID_SHIFT_STATE` — and requires
        the current instant inside the half-open window from `starts_at` to `ends_at`;
        too early or too late is `ERR_SHIFT_NOT_STARTABLE`."

        Design: Corner/validations/shift_start_outside_window_rejected
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Early Bird", email="early.bird@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        shift = book_shift(ctx["nurse"]["id"], unit["id"],
                           "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        set_clock("2026-08-09T08:00:00Z")
        resp = api_client.start_shift(shift["id"], MGR1)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_STARTABLE)
        assert get_shift(shift["id"])["status"] == "SCHEDULED"

    def test_shift_complete_without_start_rejected(self):
        """PRD §3.6: "Completing moves `IN_PROGRESS` to `COMPLETED` and releases the
        unit counters: ..."
        PRD §2.9: "7. **State validity** — the target entity must stand in a valid
        from-state for the requested transition, reported per entity as ..., or
        `ERR_INVALID_SHIFT_STATE`, ... (all 409)."
        PRD §3.6: "...the stamp is guaranteed by the precondition, and the field stays
        null until the shift starts."

        Design: Corner/state_machines/shift_complete_without_start_rejected
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Skip Start", email="skip.start@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        shift = book_shift(ctx["nurse"]["id"], unit["id"],
                           "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        resp = api_client.complete_shift(shift["id"], MGR1)
        validate_error(resp, ApiErrorId.ERR_INVALID_SHIFT_STATE)
        after = get_shift(shift["id"])
        assert after["status"] == "SCHEDULED"
        assert after["was_clear_at_start"] is None

    def test_shift_create_unit_cert_requirement_unmet(self):
        """PRD §3.6: "Next, every entry of the unit's `required_cert_types` must be
        backed by an `ACTIVE` certification of that type, else
        `ERR_UNIT_CERT_REQUIREMENT_UNMET`."
        PRD §3.5: "Otherwise she is `CLEAR`."

        Design: Corner/validations/shift_create_unit_cert_requirement_unmet
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="No Acls", email="no.acls@x.com")
        unit = create_unit(name="ICU", required_cert_types=["ACLS"])
        nurse = ctx["nurse"]
        assert get_nurse(nurse["id"])["credential_posture"] == "CLEAR", (
            "base requirements all satisfied; the unit cert check is consulted at booking"
        )

        resp = _book_med_shift(nurse["id"], unit["id"],
                               "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        validate_error(resp, ApiErrorId.ERR_UNIT_CERT_REQUIREMENT_UNMET)
        assert _shift_count(nurse["id"]) == 0


class TestPostureCascadeConditionalReach:
    def test_posture_cascade_spares_in_progress_shift(self):
        """PRD §3.5: "When the flip is away from `CLEAR`, the posture cascade fires
        exactly once: every shift assignment still `SCHEDULED` with a start after the
        current instant is auto-cancelled with `cancel_reason`
        `POSTURE_SCHEDULING_SUSPENDED` or `POSTURE_PRACTICE_RESTRICTED` matching the
        new posture; each such cancellation decrements its unit's
        `scheduled_hours_total` and `active_assignment_count`; and every packet
        standing `APPROVED` moves to `VOIDED`. Assignments already `IN_PROGRESS` are
        never auto-cancelled."

        Design: Corner/state_machines/posture_cascade_spares_in_progress_shift
        """
        set_clock()
        ctx = setup_credentialed_nurse(
            full_name="Ina Progress", email="ina.progress@x.com",
            license_expires_on="2026-08-20",
        )
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = ctx["nurse"]
        shift_a = book_shift(nurse["id"], unit["id"],
                             "2026-08-20T07:00:00Z", "2026-08-20T19:00:00Z")
        shift_b = book_shift(nurse["id"], unit["id"],
                             "2026-08-25T07:00:00Z", "2026-08-25T19:00:00Z")

        set_clock("2026-08-20T07:30:00Z")
        started = validate_success(api_client.start_shift(shift_a["id"], MGR1), 200)
        assert started["status"] == "IN_PROGRESS"

        set_clock("2026-08-21T00:00:00Z")
        run_sweep()

        after_b = get_shift(shift_b["id"])
        assert after_b["status"] == "AUTO_CANCELLED"
        assert after_b["cancel_reason"] == "POSTURE_SCHEDULING_SUSPENDED"
        after_a = get_shift(shift_a["id"])
        assert after_a["status"] == "IN_PROGRESS", (
            "the cascade's SCHEDULED-only, future-start precondition spares it"
        )
        unit_after = get_unit(unit["id"])
        assert unit_after["active_assignment_count"] == 1
        assert get_nurse(nurse["id"])["credential_posture"] == "SCHEDULING_SUSPENDED"
