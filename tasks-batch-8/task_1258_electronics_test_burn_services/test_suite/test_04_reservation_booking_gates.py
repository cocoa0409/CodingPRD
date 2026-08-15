"""Chamber reservation booking gates: window well-formedness, profile support,
fixture lineage and availability, chamber-online gate, ESD containment and its
priority over temporal checks, capacity boundary, and adjacency rules
(PRD §2.8–§2.11, §3.3)."""
from test_helpers import (
    create_chamber_reservation_payload,
    create_open_major_audit,
    create_released_program,
    reserve,
    setup_chamber,
    setup_queued_lot,
    setup_reservation_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ENG1, OPS

W1_START = "2026-06-01T10:00:00Z"
W1_END = "2026-06-01T11:00:00Z"


class TestWindowWellFormedness:
    def test_reservation_window_inverted_returns_invalid_request(self, api):
        """PRD §2.9: "A well-formed window requires `start_at` to be at or after the
        current logical clock and `end_at` to be strictly after `start_at`;
        malformed or past windows are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/reservation_window_inverted_returns_invalid_request
        """
        ctx = setup_reservation_scenario(part_number="PN-215", max_retests_per_unit=1)
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at="2026-06-01T11:00:00Z", end_at="2026-06-01T10:00:00Z",
            ),
            OPS,
        )
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


class TestProfileSupport:
    def test_profile_not_supported_rejected(self, api):
        """PRD §3.3: "The requested `profile_class` must appear among the chamber's
        `supported_profile_classes`, otherwise `ERR_PROFILE_NOT_SUPPORTED`."

        Design: Corner/validations/profile_not_supported_rejected
        """
        ctx = setup_reservation_scenario(part_number="PN-216", max_retests_per_unit=1)
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                profile_class="C", start_at=W1_START, end_at=W1_END,
            ),
            OPS,
        )
        validate_error(res, "ERR_PROFILE_NOT_SUPPORTED", expected_status=422)


class TestFixtureLineage:
    def test_fixture_program_mismatch_rejected(self, api):
        """PRD §3.3: "The fixture must be `AVAILABLE`, otherwise
        `ERR_FIXTURE_NOT_AVAILABLE`, and the fixture's program must be the same
        program pinned on the lot — a cross-reference checked as `fixture_id`
        lineage against the lot's `program_id` — otherwise the booking is rejected
        with `ERR_FIXTURE_PROGRAM_MISMATCH`."

        Design: Corner/validations/fixture_program_mismatch_rejected
        """
        # Two RELEASED programs on different part numbers for one customer, so no
        # supersession interferes; the lot pins PN-A, the fixture belongs to PN-B.
        ctx_a = setup_queued_lot(quantity=1, part_number="PN-A", max_retests_per_unit=1)
        ctx_b = create_released_program(
            ctx_a["customer"]["id"], part_number="PN-B", max_retests_per_unit=1,
            fixture_serial="FX-B",
        )
        chamber = setup_chamber(name="CH-MX", area_code="AREA-MX")
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                chamber["id"], ctx_a["lot"]["id"], ctx_b["fixture"]["id"],
                start_at=W1_START, end_at=W1_END,
            ),
            OPS,
        )
        validate_error(res, "ERR_FIXTURE_PROGRAM_MISMATCH", expected_status=422)

    def test_fixture_not_available_rejected(self, api):
        """PRD §3.3: "The fixture must be `AVAILABLE`, otherwise
        `ERR_FIXTURE_NOT_AVAILABLE`, and the fixture's program must be the same
        program pinned on the lot — a cross-reference checked as `fixture_id`
        lineage against the lot's `program_id` — otherwise the booking is rejected
        with `ERR_FIXTURE_PROGRAM_MISMATCH`."

        Design: Corner/validations/fixture_not_available_rejected
        """
        ctx = setup_reservation_scenario(part_number="PN-229", max_retests_per_unit=1)
        # No reservation references the fixture yet; pull it into maintenance.
        validate_success(api.fixture_maintenance(ctx["fixture"]["id"], ENG1), 200)
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at=W1_START, end_at=W1_END,
            ),
            OPS,
        )
        validate_error(res, "ERR_FIXTURE_NOT_AVAILABLE", expected_status=409)


class TestChamberOnlineGate:
    def test_reservation_create_on_maintenance_chamber_rejected(self, api):
        """PRD §3.3: "The chamber must be `ONLINE`, otherwise
        `ERR_CHAMBER_NOT_ONLINE`."

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_chamber_online
        """
        ctx = setup_reservation_scenario(part_number="PN-121", max_retests_per_unit=1)
        validate_success(
            api.patch_chamber(ctx["chamber"]["id"], {"status": "MAINTENANCE"}, OPS), 200
        )
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at=W1_START, end_at=W1_END,
            ),
            OPS,
        )
        validate_error(res, "ERR_CHAMBER_NOT_ONLINE", expected_status=409)

    def test_rejected_booking_on_offline_gate_persists_nothing(self, api):
        """PRD §3.3: "The chamber must be `ONLINE`, otherwise
        `ERR_CHAMBER_NOT_ONLINE`."
        PRD §4: "List reservations, filterable by chamber, lot, fixture, and
        status" (the rejected request must have persisted no reservation row).

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_chamber_online
        """
        ctx = setup_reservation_scenario(part_number="PN-121", max_retests_per_unit=1)
        validate_success(
            api.patch_chamber(ctx["chamber"]["id"], {"status": "MAINTENANCE"}, OPS), 200
        )
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at=W1_START, end_at=W1_END,
            ),
            OPS,
        )
        validate_error(res, "ERR_CHAMBER_NOT_ONLINE", expected_status=409)
        rows, meta = validate_paginated(
            api.list_chamber_reservations(OPS, params={"chamber_id": ctx["chamber"]["id"]})
        )
        assert len(rows) == 0 and meta["total_count"] == 0, (
            "a rejected booking must persist no reservation"
        )


class TestEsdContainment:
    def test_esd_containment_single_failure(self, api):
        """PRD §2.10: "An area is under containment while there exists an ESD audit
        on that `area_code` that is `OPEN` and carries at least one finding of
        severity `MAJOR`."
        PRD §2.10: "When a chamber sits in a contained area and the lot being booked
        belongs to a customer whose `requires_esd_certification` flag is true, the
        reservation request — whether an initial booking or a reschedule — is
        rejected with `ERR_ESD_CONTAINMENT`."

        Design: Corner/validations/esd_containment_single_failure
        """
        ctx = setup_reservation_scenario(
            part_number="PN-223", max_retests_per_unit=1,
            requires_esd_certification=True,
        )
        create_open_major_audit(ctx["chamber"]["area_code"], "ionizer offline")
        # Non-overlapping, well-formed future window: the safety gate alone rejects.
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at=W1_START, end_at=W1_END,
            ),
            OPS,
        )
        validate_error(res, "ERR_ESD_CONTAINMENT", expected_status=409)

    def test_esd_safety_beats_slot_overlap_error_id(self, api):
        """PRD §2.11: "Incoming requests are validated against a fixed priority
        ladder, and the first failing rung determines the error returned — a request
        that would fail several checks surfaces only the earliest rung's error."
        PRD §2.11 rung 6 (business safety) names `ERR_ESD_CONTAINMENT`; rung 7
        (business temporal) names `ERR_SLOT_OVERLAP` — so a booking that violates
        both surfaces `ERR_ESD_CONTAINMENT`.

        Design: Difficulty/priority_pair_validation_conflict/esd_safety_beats_slot_overlap
        """
        ctx = setup_reservation_scenario(
            part_number="PN-900", max_retests_per_unit=1,
            requires_esd_certification=True, tier="STRATEGIC",
        )
        reserve(ctx, start_at=W1_START, end_at=W1_END, slot_count=1)
        create_open_major_audit(ctx["chamber"]["area_code"], "wrist-strap station failed")
        # 10:30-11:30 overlaps the existing 10:00-11:00 booking AND the area is
        # under containment for this certification-requiring customer.
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at="2026-06-01T10:30:00Z", end_at="2026-06-01T11:30:00Z",
            ),
            OPS,
        )
        validate_error(res, "ERR_ESD_CONTAINMENT", expected_status=409)

    def test_esd_safety_beats_slot_overlap_persists_nothing(self, api):
        """PRD §2.10: "When a chamber sits in a contained area and the lot being
        booked belongs to a customer whose `requires_esd_certification` flag is
        true, the reservation request — whether an initial booking or a reschedule —
        is rejected with `ERR_ESD_CONTAINMENT`."
        PRD §2.11: "Incoming requests are validated against a fixed priority ladder,
        and the first failing rung determines the error returned — a request that
        would fail several checks surfaces only the earliest rung's error."

        Design: Difficulty/priority_pair_validation_conflict/esd_safety_beats_slot_overlap
        """
        ctx = setup_reservation_scenario(
            part_number="PN-900", max_retests_per_unit=1,
            requires_esd_certification=True, tier="STRATEGIC",
        )
        reserve(ctx, start_at=W1_START, end_at=W1_END, slot_count=1)
        create_open_major_audit(ctx["chamber"]["area_code"], "wrist-strap station failed")
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at="2026-06-01T10:30:00Z", end_at="2026-06-01T11:30:00Z",
            ),
            OPS,
        )
        validate_error(res, "ERR_ESD_CONTAINMENT", expected_status=409)
        rows, meta = validate_paginated(
            api.list_chamber_reservations(OPS, params={"chamber_id": ctx["chamber"]["id"]})
        )
        assert len(rows) == 1 and meta["total_count"] == 1, (
            "the rejected request persisted nothing; only the original reservation remains"
        )


class TestReservationStateGates:
    def test_reservation_complete_from_reserved_returns_invalid_state(self, api):
        """PRD §3.3: "Completing a reservation moves it from `IN_PROGRESS` to
        `COMPLETED` once the clock has reached or passed `end_at`, otherwise
        `ERR_INVALID_STATE`, and frees its slots in the ledger." (A `RESERVED`
        reservation has no complete transition.)
        PRD §2.11: "the target resource's own state permits the operation — a lot
        `IN_TEST` for result recording, a unit `FAILED` for retest authorization, a
        review `PENDING` for a decision, an audit `OPEN` for close, a reservation
        `RESERVED` for start, cancel, or reschedule, a program `DRAFT` or `VALIDATED`
        for validate or release — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/reservation_complete_from_reserved_returns_invalid_state
        """
        ctx = setup_reservation_scenario(part_number="PN-207", max_retests_per_unit=1)
        r1 = reserve(ctx, start_at="2026-06-02T10:00:00Z", end_at="2026-06-02T11:00:00Z")
        res = api.complete_reservation(r1["id"], OPS)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        r1_after = validate_success(api.get_chamber_reservation(r1["id"], OPS), 200)
        assert r1_after["status"] == "RESERVED", "rejected complete must change nothing"
        chamber = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        assert chamber["available_slots"] == 3, "slot ledger must be unchanged"

    def test_chamber_offline_terminal_lockdown(self, api):
        """PRD §3.3: "Taking a chamber `OFFLINE` is terminal and forceful: every
        reservation still `RESERVED` on that chamber is cancelled and the slot
        ledger is recomputed." (Terminal means no transition leads out of
        `OFFLINE`.)
        PRD §2.11: "the target resource's own state permits the operation — a lot
        `IN_TEST` for result recording, a unit `FAILED` for retest authorization, a
        review `PENDING` for a decision, an audit `OPEN` for close, a reservation
        `RESERVED` for start, cancel, or reschedule, a program `DRAFT` or `VALIDATED`
        for validate or release — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/chamber_offline_terminal_lockdown
        """
        chamber = setup_chamber(name="CH-OFF", area_code="AREA-F", slot_count=2,
                                clock=None)
        validate_success(api.patch_chamber(chamber["id"], {"status": "OFFLINE"}, OPS), 200)
        res = api.patch_chamber(chamber["id"], {"status": "ONLINE"}, OPS)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        chamber_after = validate_success(api.get_chamber(chamber["id"], OPS), 200)
        assert chamber_after["status"] == "OFFLINE", "OFFLINE is terminal"


class TestSlotCapacityBoundary:
    def test_slot_capacity_boundary_equal_allowed_excess_rejected(self, api):
        """PRD §2.8: "At creation, a reservation's `slot_count` must be at least 1
        and at most the chamber's current `available_slots`; booking every remaining
        slot is permitted, while requesting one more than available is rejected with
        `ERR_SLOT_CAPACITY_EXCEEDED`."

        Design: Corner/validations/slot_capacity_boundary_equal_allowed_excess_rejected
        """
        ctx = setup_reservation_scenario(
            part_number="PN-232", max_retests_per_unit=1, slot_count=3
        )
        reserve(ctx, start_at=W1_START, end_at=W1_END, slot_count=2)  # 1 remains
        # slot_count 1 against available 1: equality is allowed.
        r2 = validate_success(
            api.create_chamber_reservation(
                create_chamber_reservation_payload(
                    ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                    start_at="2026-06-01T12:00:00Z", end_at="2026-06-01T13:00:00Z",
                ),
                OPS,
            ),
            201,
        )
        assert r2["status"] == "RESERVED"
        # Available is now 0; one more slot exceeds capacity.
        res = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at="2026-06-01T14:00:00Z", end_at="2026-06-01T15:00:00Z",
            ),
            OPS,
        )
        validate_error(res, "ERR_SLOT_CAPACITY_EXCEEDED", expected_status=422)


class TestAdjacencyAndOverlap:
    def test_different_class_adjacency_and_true_overlap_rejected(self, api):
        """PRD §2.9: "A booking that places a different-class run adjacent to a
        non-cancelled neighbor without the half-hour gap is rejected with
        `ERR_PROFILE_BUFFER_VIOLATION`, on initial booking and on reschedule alike."
        PRD §2.9: "Two reservations on the same chamber collide when the new
        window's start falls before an existing reservation's end and that existing
        reservation's start falls before the new window's end — the standard
        half-open overlap test — evaluated against all reservations on that chamber
        that are not `CANCELLED`. A colliding booking is rejected with
        `ERR_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/chamber_half_open_adjacency_vs_profile_buffer
        """
        ctx = setup_reservation_scenario(
            part_number="PN-141", max_retests_per_unit=1, slot_count=8,
            profile_classes=["A", "B"],
        )
        reserve(ctx, start_at=W1_START, end_at=W1_END, slot_count=1, profile_class="A")
        # Class B abutting class A at 11:00 lacks the thirty-minute purge gap.
        res_buf = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                profile_class="B",
                start_at="2026-06-01T11:00:00Z", end_at="2026-06-01T12:00:00Z",
            ),
            OPS,
        )
        validate_error(res_buf, "ERR_PROFILE_BUFFER_VIOLATION", expected_status=409)
        # 10:30-11:30 truly overlaps the existing 10:00-11:00 class-A run.
        res_ov = api.create_chamber_reservation(
            create_chamber_reservation_payload(
                ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                start_at="2026-06-01T10:30:00Z", end_at="2026-06-01T11:30:00Z",
            ),
            OPS,
        )
        validate_error(res_ov, "ERR_SLOT_OVERLAP", expected_status=409)

    def test_same_class_adjacency_accepted(self, api):
        """PRD §2.9: "Runs on the same chamber that use different `profile_class`
        values must be separated by a thirty-minute gap, giving the chamber time to
        purge between thermal profiles; runs of the same profile class may abut
        directly, with one run's `end_at` equal to the next run's `start_at`."
        PRD §2.9: "Reservation windows use half-open interval semantics: a booking
        occupies the span from its `start_at` (inclusive) to its `end_at`
        (exclusive)."

        Design: Difficulty/resource_temporal_overlap/chamber_half_open_adjacency_vs_profile_buffer
        """
        ctx = setup_reservation_scenario(
            part_number="PN-141", max_retests_per_unit=1, slot_count=8,
            profile_classes=["A", "B"],
        )
        reserve(ctx, start_at=W1_START, end_at=W1_END, slot_count=1, profile_class="A")
        # Same class abutting at 11:00: start == prior end is not an overlap and
        # no purge gap is required between same-class runs.
        r_adj = validate_success(
            api.create_chamber_reservation(
                create_chamber_reservation_payload(
                    ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
                    profile_class="A",
                    start_at="2026-06-01T11:00:00Z", end_at="2026-06-01T12:00:00Z",
                ),
                OPS,
            ),
            201,
        )
        assert r_adj["status"] == "RESERVED"
        rows, meta = validate_paginated(
            api.list_chamber_reservations(OPS, params={"chamber_id": ctx["chamber"]["id"]})
        )
        assert len(rows) == 2 and meta["total_count"] == 2
