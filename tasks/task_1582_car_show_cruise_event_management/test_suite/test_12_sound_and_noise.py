"""Sound program: slot overlap half-open semantics, curfew edges, permit
suspension threshold, and clock-driven slot completion."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_published_event, create_sound_slot_payload, create_noise_reading_payload,
    get_summary, assert_sound_slot, assert_noise_reading,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


class TestSoundSlotOverlap:
    def test_overlapping_slot_rejected(self, api):
        """PRD §3.8: "the requested window must not intersect any existing
        `SCHEDULED` slot under the half-open convention — back-to-back adjacency,
        one slot starting exactly as another ends, is allowed — else
        `ERR_SOUND_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/sound_slot_half_open_overlap
        """
        ev, cls, zone = create_published_event()
        get_success_data(api.create_sound_slot(ev["id"], create_sound_slot_payload(
            performer_name="Headliner",
            slot_start="2026-08-15T19:00:00Z", slot_end="2026-08-15T20:00:00Z"), ORG))
        resp = api.create_sound_slot(ev["id"], create_sound_slot_payload(
            performer_name="Overlapper",
            slot_start="2026-08-15T19:30:00Z", slot_end="2026-08-15T20:30:00Z",
            expected_db=88.0), ORG)
        validate_error(resp, ApiErrorId.ERR_SOUND_SLOT_OVERLAP)

    def test_back_to_back_adjacency_allowed(self, api):
        """PRD §3.8: "back-to-back adjacency, one slot starting exactly as another
        ends, is allowed". PRD §2.7: "Every time window in the system is
        half-open — the start instant is inclusive and the end instant exclusive."

        Design: Difficulty/resource_temporal_overlap/sound_slot_half_open_overlap
        """
        ev, cls, zone = create_published_event()
        get_success_data(api.create_sound_slot(ev["id"], create_sound_slot_payload(
            performer_name="Headliner",
            slot_start="2026-08-15T19:00:00Z", slot_end="2026-08-15T20:00:00Z"), ORG))
        after = validate_success(api.create_sound_slot(ev["id"], create_sound_slot_payload(
            performer_name="After Band",
            slot_start="2026-08-15T20:00:00Z", slot_end="2026-08-15T21:00:00Z",
            expected_db=85.0), ORG), expected_status=201)
        assert after["status"] == "SCHEDULED"
        before = validate_success(api.create_sound_slot(ev["id"], create_sound_slot_payload(
            performer_name="Before Band",
            slot_start="2026-08-15T18:00:00Z", slot_end="2026-08-15T19:00:00Z",
            expected_db=85.0), ORG), expected_status=201)
        assert before["status"] == "SCHEDULED"


class TestNoiseLimitAndCurfewEdges:
    def test_day_limit_strictly_greater(self, api):
        """PRD §3.8: "An `is_exceedance` is flagged only when the reading is
        strictly greater than the applicable limit — a reading exactly at the
        limit is compliant."

        Design: Difficulty/boundary_precision_check/noise_limit_and_curfew_edges
        """
        ev, cls, zone = create_published_event()
        at_limit = validate_success(api.create_noise_reading(ev["id"], create_noise_reading_payload(
            reading_db=95.0, recorded_at="2026-08-15T15:00:00Z"), DESK), expected_status=201)
        assert_noise_reading(at_limit)
        assert at_limit["is_exceedance"] is False
        assert at_limit["limit_db"] == pytest.approx(95.0)
        over = validate_success(api.create_noise_reading(ev["id"], create_noise_reading_payload(
            reading_db=95.1, recorded_at="2026-08-15T15:05:00Z"), DESK), expected_status=201)
        assert over["is_exceedance"] is True

    def test_curfew_start_inclusive_and_day_before(self, api):
        """PRD §3.8: "The reading's clock time, taken as `HH:MM` in UTC — this is
        a single-timezone deployment, so UTC stands in for venue-local time — is
        curfew-time when it falls inside the half-open window from `curfew_start`
        to `curfew_end`". PRD §2.7: "Every time window in the system is half-open
        — the start instant is inclusive and the end instant exclusive."

        Design: Difficulty/boundary_precision_check/noise_limit_and_curfew_edges
        """
        ev, cls, zone = create_published_event()
        at_start = validate_success(api.create_noise_reading(ev["id"], create_noise_reading_payload(
            reading_db=90.0, source="PA_SYSTEM",
            recorded_at="2026-08-15T22:00:00Z"), DESK), expected_status=201)
        assert at_start["is_curfew"] is True, "22:00 is inside [22:00, 07:00)"
        assert at_start["limit_db"] == pytest.approx(85.0)
        assert at_start["is_exceedance"] is True, "90.0 > 85.0 curfew limit"
        before = validate_success(api.create_noise_reading(ev["id"], create_noise_reading_payload(
            reading_db=90.0, source="PA_SYSTEM",
            recorded_at="2026-08-15T21:59:59Z"), DESK), expected_status=201)
        assert before["is_curfew"] is False
        assert before["is_exceedance"] is False, "90.0 <= 95.0 day limit"
        summary = get_summary(ev["id"])
        assert summary["noise_exceedance_count"] == 1
        assert summary["sound_permit_status"] == "ACTIVE", "threshold 3 not reached"


class TestCurfewEndExclusive:
    def test_curfew_end_exclusive(self, api):
        """PRD §3.8: "curfew-time means at or after `curfew_start`, or before
        `curfew_end`" (for windows wrapping midnight). PRD §2.7: "Every time
        window in the system is half-open — the start instant is inclusive and
        the end instant exclusive."

        Design: Corner/calculations/curfew_end_exclusive
        """
        ev, cls, zone = create_published_event()
        at_end = validate_success(api.create_noise_reading(ev["id"], create_noise_reading_payload(
            reading_db=90.0, source="EXHAUST",
            recorded_at="2026-08-16T07:00:00Z"), DESK), expected_status=201)
        assert at_end["is_curfew"] is False, "07:00 is the exclusive end"
        assert at_end["limit_db"] == pytest.approx(95.0)
        assert at_end["is_exceedance"] is False
        assert get_summary(ev["id"])["noise_exceedance_count"] == 0


class TestPermitSuspensionThreshold:
    def test_permit_suspension_cascades_cancel_future_slots(self, api):
        """PRD §3.8: "Each exceedance increments the event's
        `noise_exceedance_count`, and the count is a tripwire: the instant it
        reaches exactly 3, `sound_permit_status` flips `ACTIVE` → `SUSPENDED`,
        every `SCHEDULED` sound slot whose start is still in the future is
        `CANCELLED` (slots already underway are not), and the event's `version`
        increments. While the permit is suspended, new sound slots are refused as
        described above".

        Design: Corner/cross_cutting_layers/permit_suspension_cascades_cancel_future_slots
        """
        ev, cls, zone = create_published_event()
        slot = get_success_data(api.create_sound_slot(ev["id"], create_sound_slot_payload(
            performer_name="Evening Band",
            slot_start="2026-08-15T19:00:00Z", slot_end="2026-08-15T20:00:00Z"), ORG))
        first = validate_success(api.create_noise_reading(ev["id"], create_noise_reading_payload(
            reading_db=96.0, recorded_at="2026-08-15T15:00:00Z"), DESK), expected_status=201)
        assert first["is_exceedance"] is True
        get_success_data(api.create_noise_reading(ev["id"], create_noise_reading_payload(
            reading_db=97.0, recorded_at="2026-08-15T16:00:00Z"), DESK))
        mid = get_summary(ev["id"])
        assert mid["noise_exceedance_count"] == 2
        assert mid["sound_permit_status"] == "ACTIVE", "threshold is exactly 3"
        get_success_data(api.create_noise_reading(ev["id"], create_noise_reading_payload(
            reading_db=96.5, source="PA_SYSTEM",
            recorded_at="2026-08-15T17:00:00Z"), DESK))
        done = get_summary(ev["id"])
        assert done["noise_exceedance_count"] == 3
        assert done["sound_permit_status"] == "SUSPENDED"
        slots = get_success_data(api.list_sound_slots(ev["id"], ORG))
        slot_after = next(s for s in slots if s["id"] == slot["id"])
        assert slot_after["status"] == "CANCELLED", "future-scheduled slot cancelled by the cascade"
        resp = api.create_sound_slot(ev["id"], create_sound_slot_payload(
            performer_name="Late DJ",
            slot_start="2026-08-15T21:00:00Z", slot_end="2026-08-15T21:30:00Z",
            expected_db=80.0), ORG)
        validate_error(resp, ApiErrorId.ERR_SOUND_PERMIT_SUSPENDED)


class TestSlotCompletionByClock:
    def test_sound_slot_completed_by_clock_advance(self, api):
        """PRD §3.8: "A slot lives in `SCHEDULED` until it is explicitly cancelled
        by the organizer (moving it to `CANCELLED`), is cancelled automatically
        when the permit suspends and the slot's `slot_start` is still strictly in
        the future, or completes to `COMPLETED` when the logical clock advances
        to or past its `slot_end` — a sweep evaluated at the moment the clock is
        set."

        Design: Corner/state_machines/sound_slot_completed_by_clock_advance
        """
        ev, cls, zone = create_published_event()
        slot = get_success_data(api.create_sound_slot(ev["id"], create_sound_slot_payload(
            performer_name="Opener",
            slot_start="2026-08-15T18:00:00Z", slot_end="2026-08-15T19:00:00Z",
            expected_db=85.0), ORG))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T19:01:00Z"}, ORG))
        slots = get_success_data(api.list_sound_slots(ev["id"], ORG))
        after = next(s for s in slots if s["id"] == slot["id"])
        assert after["status"] == "COMPLETED"
