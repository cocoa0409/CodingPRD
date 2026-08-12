"""Bed lifecycle, service control, hold/release compensation, and listing tests."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_bed, create_bed_payload,
    create_home, add_bed, create_licensed_home, set_clock, fresh_bed, fresh_home,
    create_pending_admission_scenario, create_approved_admission_scenario,
    approve_admission, complete_admission, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
PROVIDER2 = TEST_USERS["provider2_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestBedCreationDefaults:
    def test_bed_create_default_medicaid_certified_false(self, api):
        """PRD §3.1: "Beds are then added to the home, each with a human `label` such
        as Room 1-A (unique within the home) and an optional `medicaid_certified`
        flag that defaults to false; every bed begins `AVAILABLE`."

        Design: Corner/entities/bed_create_default_medicaid_certified_false
        """
        home = create_home(name="Corner Cedar", licensed_bed_capacity=4)
        res = api.create_bed(home["id"], create_bed_payload(label="1A"), PROVIDER)
        bed = validate_success(res, 201)
        assert_bed(bed)
        assert bed["medicaid_certified"] is False, "default flag must be false"
        assert bed["status"] == "AVAILABLE"
        assert bed["version"] == 1


class TestBedListing:
    def test_list_beds_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/list_beds_pagination_envelope
        """
        home = create_home(name="Corner Holly", licensed_bed_capacity=4)
        for label in ("1A", "1B", "1C"):
            add_bed(home["id"], label=label)
        page1, meta1 = validate_paginated(
            api.list_beds(home["id"], PROVIDER, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2, f"page 1 must hold 2 beds, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_beds(home["id"], PROVIDER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1, f"page 2 must hold 1 bed, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestHeldBedTakeOutOfService:
    def test_held_bed_out_of_service_forces_admission_rejected(self, api):
        """PRD §3.3: "when a `HELD` bed is taken out of service, the linked `PENDING`
        admission is auto-rejected first with the system recorded as `decided_by`,
        and the admission's bed-release compensation is suppressed because the bed is
        leaving service rather than returning to availability."

        Design: Corner/state_machines/bed_held_take_out_of_service_forces_admission_rejected
        """
        ctx = create_licensed_home(name="Bed Force", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_pending_admission_scenario(home["id"], bed["id"])
        validate_success(api.take_bed_out_of_service(bed["id"], PROVIDER), 200)
        admission_after = validate_success(
            api.get_admission(adm["admission"]["id"], PROVIDER), 200)
        assert admission_after["status"] == "REJECTED"
        assert admission_after["decided_by"] == "system", (
            "forced rejection must record the system as the decider, got "
            f"{admission_after.get('decided_by')!r}")

    def test_held_bed_out_of_service_suppresses_release_compensation(self, api):
        """PRD §3.3: "when a `HELD` bed is taken out of service, the linked `PENDING`
        admission is auto-rejected first with the system recorded as `decided_by`,
        and the admission's bed-release compensation is suppressed because the bed is
        leaving service rather than returning to availability."

        Design: Corner/state_machines/bed_held_take_out_of_service_forces_admission_rejected
        """
        ctx = create_licensed_home(name="Bed Force", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        create_pending_admission_scenario(home["id"], bed["id"])
        validate_success(api.take_bed_out_of_service(bed["id"], PROVIDER), 200)
        bed_after = fresh_bed(bed["id"])
        assert bed_after["status"] == "OUT_OF_SERVICE", (
            "bed must land OUT_OF_SERVICE, not AVAILABLE — the admission's "
            "release compensation is suppressed")


class TestOccupiedBedGuard:
    def test_occupied_bed_cannot_leave_service(self, api):
        """PRD §3.1: "An `OCCUPIED` bed can never leave service — the attempt is
        rejected with `ERR_BED_OCCUPIED` — until its resident has been discharged."

        Design: Corner/errors/err_bed_occupied_triggered
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Bed Occ", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_approved_admission_scenario(home["id"], bed["id"])
        complete_admission(adm["admission"]["id"])
        res = api.take_bed_out_of_service(bed["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_BED_OCCUPIED, expected_status=409)
        bed_after = fresh_bed(bed["id"])
        assert bed_after["status"] == "OCCUPIED", "occupied bed must be unchanged"


class TestBedServiceCycles:
    def test_out_of_service_lap_then_hold_release_lap_returns_available(self, api):
        """PRD §3.1: "Bed service control works in both directions. Taking a bed out
        of service moves `AVAILABLE` → `OUT_OF_SERVICE`, or `HELD` → `OUT_OF_SERVICE`
        with the forced rejection of its pending admission applied first, exactly as
        in the closure cascade."
        PRD §3.1: "Returning a bed (`OUT_OF_SERVICE` → `AVAILABLE`) requires the home
        to be `PROVISIONAL` or `LICENSED`."
        PRD §3.3: "Rejection moves `PENDING` → `REJECTED`, stamps the same two
        decision fields, and releases the hold: the bed returns `HELD` → `AVAILABLE`
        as compensation."

        Design: Difficulty/non_linear_state_machine/bed_out_of_service_and_hold_release_cycles
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Ash AFH", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        # Lap 1: AVAILABLE -> OUT_OF_SERVICE -> AVAILABLE
        validate_success(api.take_bed_out_of_service(bed["id"], PROVIDER), 200)
        returned = validate_success(api.return_bed_to_service(bed["id"], PROVIDER), 200)
        assert returned["status"] == "AVAILABLE"
        bed_v2 = returned["version"]
        # Lap 2: AVAILABLE -> HELD (admission) -> AVAILABLE (reject compensation)
        appl = create_pending_admission_scenario(home["id"], bed["id"])
        validate_success(api.reject_admission(appl["admission"]["id"], PROVIDER2), 200)
        bed_after = fresh_bed(bed["id"])
        assert bed_after["status"] == "AVAILABLE", \
            "both cycles must return the bed to AVAILABLE"
        assert bed_after["version"] == bed_v2 + 2, (
            f"hold on create and release on reject must each bump the version once: "
            f"expected {bed_v2 + 2}, got {bed_after['version']}")

    def test_hold_release_cycle_marks_admission_rejected(self, api):
        """PRD §3.3: "Rejection moves `PENDING` → `REJECTED`, stamps the same two
        decision fields, and releases the hold: the bed returns `HELD` → `AVAILABLE`
        as compensation."
        PRD §2.5: "`version` (integer): a counter that increments by one on every
        mutation, including mutations caused by cascades rather than direct client
        writes."

        Design: Difficulty/non_linear_state_machine/bed_out_of_service_and_hold_release_cycles
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Ash AFH", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        validate_success(api.take_bed_out_of_service(bed["id"], PROVIDER), 200)
        validate_success(api.return_bed_to_service(bed["id"], PROVIDER), 200)
        appl = create_pending_admission_scenario(home["id"], bed["id"])
        rejected = validate_success(
            api.reject_admission(appl["admission"]["id"], PROVIDER2), 200)
        assert rejected["status"] == "REJECTED"
        assert fresh_bed(bed["id"])["status"] == "AVAILABLE"


class TestOccupancyLedgerInvariant:
    def test_cancel_restores_bed_and_keeps_census_zero(self, api):
        """PRD §3.3: "Cancellation abandons an approved move-in, `APPROVED` →
        `CANCELLED`, with the same bed-release compensation."
        PRD §2.11: "`current_census` counts the home's residents in `ADMITTED` status
        and is recomputed on every admission completion and every discharge."

        Design: Difficulty/compensating_invariant/bed_hold_release_conserves_occupancy_ledger
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Noble AFH", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        assert fresh_home(home["id"])["current_census"] == 0
        adm = create_approved_admission_scenario(home["id"], bed["id"])
        cancelled = validate_success(
            api.cancel_admission(adm["admission"]["id"], PROVIDER), 200)
        assert cancelled["status"] == "CANCELLED"
        bed_after = fresh_bed(bed["id"])
        assert bed_after["status"] == "AVAILABLE", \
            "cancel compensation must restore the pre-action bed status"
        assert fresh_home(home["id"])["current_census"] == 0, \
            "census must be identical before create and after cancel"

    def test_cancel_conserves_bed_count(self, api):
        """PRD §3.3: "Cancellation abandons an approved move-in, `APPROVED` →
        `CANCELLED`, with the same bed-release compensation."

        Design: Difficulty/compensating_invariant/bed_hold_release_conserves_occupancy_ledger
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Noble AFH", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_approved_admission_scenario(home["id"], bed["id"])
        validate_success(api.cancel_admission(adm["admission"]["id"], PROVIDER), 200)
        beds, meta = validate_paginated(api.list_beds(home["id"], PROVIDER))
        assert meta["total_count"] == 1, \
            "no bed may be created or destroyed by the hold/approve/cancel sequence"
        assert beds[0]["id"] == bed["id"]
