"""Chronic-care enrollment, the visit audit trail, tier escalation and the lapse cycle."""

from test_helpers import (
    ApiErrorId,
    assert_chronic_enrollment,
    assert_chronic_visit,
    assert_same_instant,
    fixtures as fx,
    validate_error,
    validate_success,
)


class TestChronicVisitAuditRow:
    def test_visit_row_is_an_immutable_audit_record_with_a_frozen_due_at_snapshot(
        self, api, nurse_headers
    ):
        """PRD §3.2: "That row is a permanent audit artefact and carries only an `id` and a
        `created_at` — no `updated_at` and no `version` — together with its `enrollment_id`,
        a `recorded_at` stamped from the current clock instant, the supplied `outcome`, a
        `recorded_by_user_id` copied from the acting `X-User-ID`, and a `due_at_snapshot`
        that captures the enrollment's `next_due_date` exactly as it stood at the instant of
        recording, before any of the outcome's own effects are applied."

        Design: Corner/entities/chronic_care_visit_is_immutable_event_row
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2010", full_name="Sol Tavares", booked_at="2026-05-01T00:00:00Z"
        )
        enrollment = fx.enrol_chronic(
            inmate["id"], condition_code="DIABETES", severity="SEVERE"
        )
        assert_same_instant(
            enrollment["next_due_date"], "2026-05-31T00:00:00Z", "next_due_date"
        )

        fx.set_clock("2026-05-20T00:00:00Z")
        resp = api.create_chronic_visit(
            enrollment["id"], {"outcome": "COMPLETED"}, nurse_headers
        )
        visit = validate_success(resp, 201)
        assert_chronic_visit(visit)
        assert visit["outcome"] == "COMPLETED"
        assert_same_instant(
            visit["due_at_snapshot"], "2026-05-31T00:00:00Z", "visit.due_at_snapshot"
        )
        assert_same_instant(visit["recorded_at"], "2026-05-20T00:00:00Z", "visit.recorded_at")

    def test_completed_visit_reanchors_the_enrollment_on_the_visit_instant(self, api):
        """PRD §3.2: "A `COMPLETED` visit sets `last_visit_at` to the current clock instant,
        resets `missed_visit_count` to 0, and recomputes `next_due_date` from the
        freshly-set `last_visit_at` plus `periodicity_days`."

        Design: Corner/entities/chronic_care_visit_is_immutable_event_row
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2011", full_name="Sol Tavares", booked_at="2026-05-01T00:00:00Z"
        )
        enrollment = fx.enrol_chronic(
            inmate["id"], condition_code="DIABETES", severity="SEVERE"
        )
        fx.set_clock("2026-05-20T00:00:00Z")
        fx.record_visit(enrollment["id"], "COMPLETED")

        refreshed = fx.read_enrollment(enrollment["id"])
        assert_same_instant(
            refreshed["last_visit_at"], "2026-05-20T00:00:00Z", "last_visit_at"
        )
        assert_same_instant(
            refreshed["next_due_date"], "2026-06-19T00:00:00Z", "next_due_date"
        )


class TestLapseAndReEnrollCycle:
    def test_enrollment_survives_exactly_at_the_grace_boundary_and_lapses_one_second_later(self, api):
        """PRD §3.2: "The second sweep step, which runs only after the intake-screening
        sweep has completed, moves every `ACTIVE` enrollment whose `next_due_date` plus a
        15-day grace period falls strictly before the new clock instant into `LAPSED`.
        Equality is still active: an enrollment sitting exactly 15 days past its due date at
        the moment the clock lands there survives."

        Design: Corner/state_machines/chronic_enrollment_lapse_grace_boundary_then_re_enroll_cycle
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2070", full_name="Yael Abbas", booked_at="2026-05-01T00:00:00Z"
        )
        enrollment = fx.enrol_chronic(
            inmate["id"], condition_code="HYPERTENSION", severity="SEVERE"
        )
        assert enrollment["tier"] == "TIER_1"
        assert enrollment["periodicity_days"] == 30
        assert_same_instant(
            enrollment["next_due_date"], "2026-05-31T00:00:00Z", "next_due_date"
        )

        fx.set_clock("2026-06-15T00:00:00Z")
        assert fx.read_enrollment(enrollment["id"])["status"] == "ACTIVE"

        fx.set_clock("2026-06-15T00:00:01Z")
        assert fx.read_enrollment(enrollment["id"])["status"] == "LAPSED"

    def test_re_enrolment_reanchors_tier_periodicity_and_next_due_date(self, api, provider_headers):
        """PRD §3.2: "Re-enrollment returns the status to `ACTIVE` and re-anchors
        everything: `enrolled_at` is reset to the current clock instant, `last_visit_at` is
        cleared back to null, `missed_visit_count` returns to 0 and `escalated` returns to
        false, `tier` and `periodicity_days` are recomputed from the newly supplied severity
        by the same severity-to-tier mapping, and `next_due_date` is recomputed from the
        re-anchored `enrolled_at`."

        Design: Corner/state_machines/chronic_enrollment_lapse_grace_boundary_then_re_enroll_cycle
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2071", full_name="Yael Abbas", booked_at="2026-05-01T00:00:00Z"
        )
        enrollment = fx.enrol_chronic(
            inmate["id"], condition_code="HYPERTENSION", severity="SEVERE"
        )
        fx.set_clock("2026-06-15T00:00:01Z")
        assert fx.read_enrollment(enrollment["id"])["status"] == "LAPSED"

        resp = api.re_enroll_chronic(
            enrollment["id"], {"severity": "MODERATE"}, provider_headers
        )
        data = validate_success(resp, 200)
        assert_chronic_enrollment(data)
        assert data["status"] == "ACTIVE"
        assert data["tier"] == "TIER_2"
        assert data["periodicity_days"] == 90
        assert data["missed_visit_count"] == 0
        assert data["escalated"] is False
        assert data["last_visit_at"] is None
        assert_same_instant(data["enrolled_at"], "2026-06-15T00:00:01Z", "enrolled_at")
        assert_same_instant(data["next_due_date"], "2026-09-13T00:00:01Z", "next_due_date")


class TestMissedVisitEscalation:
    def test_first_missed_visit_only_increments_the_counter(self, api):
        """PRD §3.2: "A `MISSED` visit increments `missed_visit_count` by 1 and
        deliberately does **not** move `next_due_date` — the patient is not granted a fresh
        interval for failing to attend."

        Design: Corner/state_machines/chronic_missed_visits_escalate_tier_at_threshold
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2080", full_name="Zeb Bello", booked_at="2026-05-01T00:00:00Z"
        )
        enrollment = fx.enrol_chronic(inmate["id"], condition_code="ASTHMA", severity="MILD")
        assert enrollment["tier"] == "TIER_3"
        assert enrollment["periodicity_days"] == 180
        assert_same_instant(
            enrollment["next_due_date"], "2026-10-28T00:00:00Z", "next_due_date"
        )

        visit = fx.record_visit(enrollment["id"], "MISSED")
        assert_same_instant(
            visit["due_at_snapshot"], "2026-10-28T00:00:00Z", "visit.due_at_snapshot"
        )
        after_one = fx.read_enrollment(enrollment["id"])
        assert after_one["missed_visit_count"] == 1
        assert after_one["escalated"] is False
        assert after_one["tier"] == "TIER_3"
        assert_same_instant(
            after_one["next_due_date"], "2026-10-28T00:00:00Z", "next_due_date is not moved"
        )

    def test_second_missed_visit_escalates_one_tier_and_shortens_the_interval(self, api):
        """PRD §3.2: "When a `MISSED` outcome brings `missed_visit_count` to 2 or more and
        `escalated` is still false, the enrollment escalates one tier step toward the most
        intensive tier: `TIER_3` becomes `TIER_2`, `TIER_2` becomes `TIER_1`, and a patient
        already at `TIER_1` stays at `TIER_1`. The `periodicity_days` is then reset from the
        new tier, `escalated` is set true so the escalation fires once and only once, and
        `next_due_date` is recomputed as `last_visit_at` — or `enrolled_at` when no visit has
        ever completed — plus the *new*, shorter `periodicity_days`."

        Design: Corner/state_machines/chronic_missed_visits_escalate_tier_at_threshold
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2081", full_name="Zeb Bello", booked_at="2026-05-01T00:00:00Z"
        )
        enrollment = fx.enrol_chronic(inmate["id"], condition_code="ASTHMA", severity="MILD")
        fx.record_visit(enrollment["id"], "MISSED")
        fx.record_visit(enrollment["id"], "MISSED")

        after_two = fx.read_enrollment(enrollment["id"])
        assert after_two["missed_visit_count"] == 2
        assert after_two["escalated"] is True
        assert after_two["tier"] == "TIER_2"
        assert after_two["periodicity_days"] == 90
        assert_same_instant(
            after_two["next_due_date"], "2026-07-30T00:00:00Z", "next_due_date"
        )


class TestEnrollmentUniqueness:
    def test_second_active_enrollment_for_the_same_condition_is_a_duplicate_key(
        self, api, provider_headers
    ):
        """PRD §3.2: "Only one `ACTIVE` enrollment may exist for a given inmate and
        condition at a time; a second request for the same `(inmate_id, condition_code)` pair
        while one is still active is rejected with `ERR_DUPLICATE_KEY` (409)."

        Design: Corner/state_machines/duplicate_active_chronic_enrollment_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2090", full_name="Ana Cruz", booked_at="2026-05-01T00:00:00Z"
        )
        first = fx.enrol_chronic(
            inmate["id"], condition_code="DIABETES", severity="MODERATE"
        )
        resp = api.create_chronic_enrollment(
            inmate["id"], {"condition_code": "DIABETES", "severity": "SEVERE"}, provider_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

        unchanged = fx.read_enrollment(first["id"])
        assert unchanged["severity"] == "MODERATE"
        assert unchanged["tier"] == "TIER_2"
