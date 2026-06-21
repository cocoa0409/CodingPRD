"""Chair/nurse interval scheduling and OCC on cycle version (PRD §2.6, §2.8, §3.10).

Queue A: boundary_precision (acuity == max allowed), resource_temporal_overlap
(chair double-book, nurse acuity aggregate), priority_pair (state vs acuity).
Queue B: end<=start rejected, closed chair, terminal cancel lockdown, OCC valid
and stale version.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures as fx,
    make_nurse_headers,
)
from test_helpers.test_users import TEST_USERS

PHARM = TEST_USERS["pharmacist_headers"]

FLAT_CHEMO = dict(drug_name="DrugC", role="CHEMO", dosing_method="FLAT",
                  flat_dose_mg=600, vial_size_mg=150, day_offset=1, sequence_index=1)


class TestNurseAcuityBoundary:
    def test_acuity_load_exactly_at_max_is_allowed(self):
        """PRD §3.10: "that concurrent load must not exceed the nurse's
        `max_acuity_load`. The rejection fires only when the load is strictly
        greater than `max_acuity_load` — a load exactly equal to the ceiling is
        permitted"

        max_acuity_load=6, an existing overlapping acuity-4 appointment, a new
        overlapping acuity-2 booking makes concurrent_load exactly 6 (==max) which
        is allowed.

        Design: Difficulty/boundary_precision_check/boundary_nurse_acuity_at_max_allowed
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        chair_a = fx.create_chair(label="C-A-acu")
        chair_b = fx.create_chair(label="C-B-acu")
        nurse = fx.create_nurse(full_name="Nacu", is_chemo_certified=True, max_acuity_load=6)
        cyc = env["cycle"]
        fx.book_appointment(cyc["id"], chair_a["id"], nurse["id"],
                            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 4, cyc["version"])
        appt2 = validate_success(api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], chair_b["id"], nurse["id"],
                "2026-07-01T09:30:00Z", "2026-07-01T10:00:00Z", 2, cyc["version"]),
            PHARM), 201)
        assert appt2["status"] == "SCHEDULED", f"load==6 should be allowed, got {appt2['status']}"
        assert appt2["acuity"] == 2


class TestResourceOverlap:
    def test_chair_double_book_rejected(self):
        """PRD §3.10: "The chair must be free over the requested interval: the
        half-open span must not overlap any `SCHEDULED` or `CHECKED_IN`
        appointment already on that same chair, where overlap means the existing
        appointment starts strictly before the new `end_at` and the new
        `start_at` is strictly before the existing end, and adjacency where one
        ends exactly as the other begins is permitted; a clash is rejected with
        `ERR_CHAIR_DOUBLE_BOOKED`."

        An existing 09:00-10:30 booking blocks a 10:00-11:00 booking on the same
        chair.

        Design: Difficulty/resource_temporal_overlap/overlap_chair_double_book_rejected
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        chair = fx.create_chair(label="C-X-ovl")
        n1 = fx.create_nurse(full_name="Nx1", is_chemo_certified=True, max_acuity_load=6)
        n2 = fx.create_nurse(full_name="Nx2", is_chemo_certified=True, max_acuity_load=6)
        cyc = env["cycle"]
        fx.book_appointment(cyc["id"], chair["id"], n1["id"],
                            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])
        resp = api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], chair["id"], n2["id"],
                "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z", 2, cyc["version"]),
            PHARM)
        validate_error(resp, ApiErrorId.ERR_CHAIR_DOUBLE_BOOKED.value)

    def test_nurse_acuity_aggregate_exceeds_max_rejected(self):
        """PRD §3.10: "take every `SCHEDULED` or `CHECKED_IN` appointment already
        on that same nurse whose half-open interval overlaps the requested
        interval, sum their `acuity` values, add the new appointment's own
        `acuity`, and that concurrent load must not exceed the nurse's
        `max_acuity_load`."

        Two overlapping acuity-4 appointments on a max_acuity_load=6 nurse exceed
        6 (8>6) -> ERR_NURSE_ACUITY_EXCEEDED, even on distinct chairs.

        Design: Difficulty/resource_temporal_overlap/overlap_nurse_acuity_aggregate_capacity_rejected
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        chair_p = fx.create_chair(label="C-P-agg")
        chair_q = fx.create_chair(label="C-Q-agg")
        nurse = fx.create_nurse(full_name="Nagg", is_chemo_certified=True, max_acuity_load=6)
        cyc = env["cycle"]
        fx.book_appointment(cyc["id"], chair_p["id"], nurse["id"],
                            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 4, cyc["version"])
        resp = api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], chair_q["id"], nurse["id"],
                "2026-07-01T09:30:00Z", "2026-07-01T10:00:00Z", 4, cyc["version"]),
            PHARM)
        validate_error(resp, ApiErrorId.ERR_NURSE_ACUITY_EXCEEDED.value)


class TestBookingBodyAndChairGuards:
    def test_end_before_start_rejected(self):
        """PRD §2.10: "Request-body well-formedness is fourth: required fields
        present, enums within their allowed sets, numerics within their declared
        ranges, an appointment's `end_at` strictly after its `start_at`, and the
        dose field matching the order item's dosing method must all hold, or the
        request is rejected with `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/appointment_end_before_start_rejected
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        resp = api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], env["chair"]["id"], env["nurse"]["id"],
                "2026-07-01T10:30:00Z", "2026-07-01T09:00:00Z", 2, cyc["version"]),
            PHARM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_book_closed_chair_rejected(self):
        """PRD §3.10: "The chair must be `OPEN`; booking against a `CLOSED` chair
        is rejected with `ERR_CHAIR_CLOSED`."

        Design: Corner/validations/book_closed_chair_rejected
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        chair = fx.create_chair(label="C-17-closed")
        validate_success(api_client.close_chair(chair["id"], PHARM), 200)
        nurse = fx.create_nurse(full_name="N17", is_chemo_certified=True)
        cyc = env["cycle"]
        resp = api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], chair["id"], nurse["id"],
                "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"]),
            PHARM)
        validate_error(resp, ApiErrorId.ERR_CHAIR_CLOSED.value)

    def test_cancel_completed_appointment_terminal_lockdown(self):
        """PRD §3.10: "cancelling an already-terminal appointment (`COMPLETED` or
        `CANCELLED`) is rejected with `ERR_APPOINTMENT_TERMINAL`."

        Design: Corner/state_machines/cancel_appointment_already_completed_terminal_lockdown
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        nurse_h = make_nurse_headers(env["nurse"]["id"])
        appt = fx.book_appointment(cyc["id"], env["chair"]["id"], env["nurse"]["id"],
                                   "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])
        validate_success(api_client.check_in_infusion_appointment(appt["id"], nurse_h), 200)
        validate_success(api_client.complete_infusion_appointment(appt["id"], nurse_h), 200)
        resp = api_client.cancel_infusion_appointment(appt["id"], nurse_h)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_TERMINAL.value)


class TestOptimisticConcurrency:
    def test_booking_with_current_cycle_version_succeeds(self):
        """PRD §2.6: "The create-appointment operation requires a non-optional
        `expected_treatment_cycle_version` field in its request body, carrying the
        `version` of the target `TreatmentCycle` that the client last observed.
        The server compares that value to the cycle's current `version`."

        Booking with expected_treatment_cycle_version equal to the cycle's current
        version succeeds (201, SCHEDULED).

        Design: Corner/cross_cutting_complexity_layers/occ_correct_cycle_version_books_appointment
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        appt = validate_success(api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], env["chair"]["id"], env["nurse"]["id"],
                "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"]),
            PHARM), 201)
        assert appt["status"] == "SCHEDULED"

    def test_booking_with_stale_cycle_version_rejected(self):
        """PRD §2.6: "If they do not match — meaning another writer, very often a
        hold or abandon cascade, has advanced the cycle since the client read it —
        the booking is rejected with `ERR_STALE_CYCLE_VERSION` and HTTP status
        412, and no appointment is created."

        A hold+resume bumps the cycle version twice; a booking carrying the
        version captured at activation is stale -> 412.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_cycle_version_on_booking_rejected
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        stale_version = cyc["version"]
        validate_success(api_client.hold_treatment_cycle(cyc["id"], PHARM), 200)
        validate_success(api_client.resume_treatment_cycle(cyc["id"], PHARM), 200)
        resp = api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], env["chair"]["id"], env["nurse"]["id"],
                "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, stale_version),
            PHARM)
        validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION.value)
