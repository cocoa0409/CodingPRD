"""Optimistic concurrency, validation-ladder ordering, immediate consistency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    assert_instants_equal,
    cancel_booking,
    check_in,
    confirm_prep,
    create_booking,
    create_booking_payload,
    create_culture,
    create_patient,
    create_provider,
    create_quarantined_scope,
    create_release_ready_scope,
    create_room,
    create_scope,
    create_colono_type,
    first_case_for_scope,
    get_booking,
    get_case,
    get_scope,
    make_endoscopist_headers,
    make_nurse_headers,
    make_registry,
    result_culture,
    run_complete_cycle,
    run_reculture_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestOccBookingPatch:
    def test_occ_booking_patch_stale_version_rejected(self, api):
        """PRD §2.7: "`PATCH /endoscopy/bookings/{id}` requires
        `expected_booking_version`. If another writer has since advanced the
        booking's `version` — amending its notes, changing its anesthesia level,
        confirming prep, checking the patient in — the amendment is rejected with
        `ERR_STALE_BOOKING_VERSION` (HTTP 412), preventing the client from
        overwriting a booking state it has not observed."

        Design: Corner/cross_cutting_layers/occ_booking_patch_stale_version_rejected
        """
        reg = make_registry(mrn="MRN-OC1", serial="SC-OC1", with_scope=False)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        v1 = booking["version"]
        patched = validate_success(api.patch_booking(
            booking["id"], {"expected_booking_version": v1, "notes": "first"}, SCHED), 200)
        assert patched["version"] == v1 + 1

        resp = api.patch_booking(booking["id"],
                                 {"expected_booking_version": v1, "notes": "stale"},
                                 SCHED)
        validate_error(resp, ApiErrorId.ERR_STALE_BOOKING_VERSION)
        assert resp.status_code == 412
        assert get_booking(booking["id"])["notes"] == "first"

        patched2 = validate_success(api.patch_booking(
            booking["id"], {"expected_booking_version": v1 + 1, "notes": "fresh"},
            SCHED), 200)
        assert patched2["version"] == v1 + 2
        assert patched2["notes"] == "fresh"

    def test_occ_reschedule_stale_version_rejected(self, api):
        """PRD §2.7: "`POST /endoscopy/bookings/{id}/reschedule` likewise requires
        `expected_booking_version`, with the same `ERR_STALE_BOOKING_VERSION`
        (HTTP 412) rejection on mismatch. Superseding a booking must be based on
        the client's latest observed state of that booking."

        Design: Corner/cross_cutting_layers/occ_reschedule_stale_version_rejected
        """
        reg = make_registry(mrn="MRN-OC2", serial="SC-OC2", with_scope=False)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        v1 = booking["version"]
        validate_success(api.patch_booking(
            booking["id"], {"expected_booking_version": v1, "notes": "bump"}, SCHED), 200)
        resp = api.reschedule_booking(
            booking["id"], {"expected_booking_version": v1,
                            "new_scheduled_start": "2026-08-05T09:00:00Z"}, SCHED)
        validate_error(resp, ApiErrorId.ERR_STALE_BOOKING_VERSION)
        chain, meta = validate_paginated(api.list_bookings(
            ADMIN, params={"rescheduled_from_id": booking["id"]}))
        assert chain == [], "no replacement booking created by a stale reschedule"
        assert get_booking(booking["id"])["status"] == "SCHEDULED"

    def test_occ_quarantine_release_stale_version_rejected(self, api):
        """PRD §2.7: "`POST /endoscopy/scopes/{id}/release-quarantine` requires
        `expected_scope_version`. A mismatch with the scope's current `version` —
        for example because the reculture cycle has since completed and advanced
        it — is rejected with `ERR_STALE_SCOPE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_quarantine_release_stale_version_rejected
        """
        scope, _q0, _c0, case = create_quarantined_scope(serial_number="SQ-OCC")
        stale_version = get_scope(scope["id"])["version"]
        q1 = run_reculture_cycle(scope["id"], technician_id="tech-7",
                                 start_iso="2026-08-20T09:30:00Z")
        advance_clock("2026-08-20T10:15:00Z")
        c1 = create_culture(scope["id"], q1["id"])
        result_culture(c1["id"], "NEGATIVE")

        resp = api.release_quarantine(scope["id"],
                                      {"expected_scope_version": stale_version},
                                      make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_STALE_SCOPE_VERSION)
        assert resp.status_code == 412

        fresh_version = get_scope(scope["id"])["version"]
        data = validate_success(api.release_quarantine(
            scope["id"], {"expected_scope_version": fresh_version},
            make_nurse_headers("nurse-1")), 200)
        assert data["status"] == "AVAILABLE"
        assert get_case(case["id"])["status"] == "RELEASED"


class TestLadderOrdering:
    def test_not_found_beats_stale_version_priority(self, api):
        """
        PRD §2.6: "When a single request violates several rules, exactly one error
        surfaces, chosen by the following ladder — earlier rungs win over later
        ones:"

        PRD §2.6: "3. **Existence** — path and body reference resolution, as above;
        the 404 family."

        PRD §2.6: "5. **Optimistic concurrency** — a stale expected version on a
        guarded write: `ERR_STALE_BOOKING_VERSION` or `ERR_STALE_SCOPE_VERSION`.
        Once the resource exists, this rung is evaluated before any business rule."

        Design: Corner/validations/not_found_beats_stale_version_priority
        """
        reg = make_registry(mrn="MRN-NF", serial="SC-NF", with_scope=False)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        resp = api.patch_booking(
            NON_EXISTENT_UUID,
            {"expected_booking_version": booking["version"], "notes": "ghost"}, SCHED)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND)
        assert resp.status_code == 404

    def test_ownership_beats_state_priority(self, api):
        """
        PRD §2.6: "6. **Ownership and segregation of duties** — an `Endoscopist`
        acting on another provider's booking (`ERR_PROVIDER_OWNERSHIP_MISMATCH`), an
        `AnesthesiaProvider` confirming another provider's assignment
        (`ERR_ANESTHESIA_OWNERSHIP_MISMATCH`), or a quarantine releaser who
        personally performed the reculture cycle (`ERR_SEGREGATION_OF_DUTIES`)."

        PRD §2.6: "7. **Legal from-state** — the target entity is not in a state
        that permits the requested transition: `ERR_BOOKING_NOT_SCHEDULED`,
        `ERR_BOOKING_NOT_CHECKED_IN`, `ERR_BOOKING_NOT_IN_PROGRESS`,
        `ERR_BOOKING_NOT_CANCELLABLE`, `ERR_PREP_NOT_CONFIRMED`,
        `ERR_PREP_ALREADY_ASSESSED`, `ERR_PREP_NOT_ASSESSED`,
        `ERR_PREP_NOT_INADEQUATE`, `ERR_SCOPE_NOT_AVAILABLE`,
        `ERR_SCOPE_NOT_REPROCESSABLE`, `ERR_SCOPE_NOT_RETIRABLE`,
        `ERR_CYCLE_STEP_OUT_OF_ORDER`, `ERR_CYCLE_NOT_ADVANCABLE`,
        `ERR_CULTURE_ALREADY_RESULTED`, `ERR_NO_OPEN_QUARANTINE`,
        `ERR_SPECIMEN_NOT_LABELED`, `ERR_SPECIMEN_NOT_IN_TRANSIT`,
        `ERR_SPECIMEN_NOT_RECEIVED`, `ERR_SPECIMEN_TERMINAL`,
        `ERR_ASSIGNMENT_STATE_INVALID`, `ERR_SCOPE_USAGE_NOT_VOIDABLE`."

        Design: Corner/validations/ownership_beats_state_priority
        """
        reg = make_registry(mrn="MRN-OW", serial="SC-OW")
        dr2 = create_provider("Dr Two", specialty="COLORECTAL_SURGERY")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        cancel_booking(booking["id"], reason="x")
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(dr2["id"]))
        validate_error(resp, ApiErrorId.ERR_PROVIDER_OWNERSHIP_MISMATCH)
        assert resp.status_code == 403

    def test_safety_beats_referential_priority(self, api):
        """
        PRD §2.6: "8. **Compliance gates** — a suspended provider or anesthesia
        provider (`ERR_PROVIDER_SUSPENDED`, `ERR_ANESTHESIA_PROVIDER_SUSPENDED`),
        anesthesia coverage not yet confirmed when required
        (`ERR_ANESTHESIA_NOT_CONFIRMED`), an explicitly named scope past its storage
        limit (`ERR_SCOPE_STORAGE_EXPIRED`), disinfectant concentration below the
        floor (`ERR_HLD_CONCENTRATION_TOO_LOW`), a reprocessing step advanced before
        its minimum dwell time (`ERR_STEP_DURATION_TOO_SHORT`), or a specimen label
        or transport window exceeded (`ERR_LABEL_WINDOW_EXCEEDED`,
        `ERR_TRANSPORT_WINDOW_EXCEEDED`)."

        PRD §2.6: "11. **Cross-entity referential consistency** —
        `ERR_SCOPE_TYPE_MISMATCH`, `ERR_CULTURE_SCOPE_MISMATCH`,
        `ERR_CYCLE_NOT_COMPLETE`."

        Design: Corner/validations/safety_beats_referential_priority
        """
        reg = make_registry(mrn="MRN-SR", serial="SG-EXP", scope_type="GASTROSCOPE")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-24T09:00:00Z")
        confirm_prep(booking["id"])
        # Expire the (wrong-type) scope: cycle dried 2026-08-20T08:26 (+72h).
        run_complete_cycle(reg["scope"]["id"], "2026-08-20T08:00:00Z", lot="LOT-SR",
                           send_first=True)
        advance_clock("2026-08-24T09:00:00Z")
        check_in(booking["id"])
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_STORAGE_EXPIRED)
        assert resp.status_code == 409


class TestLogicalClock:
    def test_clock_regression_rejected(self, api):
        """PRD §2.4: "The target must be strictly later than the current logical
        reading; a target equal to or earlier than the present reading is rejected
        with `ERR_CLOCK_REGRESSION` (HTTP 422)."

        Design: Corner/validations/clock_regression_rejected
        """
        advance_clock("2026-08-02T00:00:00Z")
        resp = api.set_clock("2026-08-02T00:00:00Z", ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)


class TestImmediateConsistency:
    def test_immediate_consistency_mutation_visible_in_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.2: "From these inputs the system computes the booking's time
        window."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
        """
        reg = make_registry(mrn="MRN-ICM", serial="SC-ICM", with_scope=False)
        created = validate_success(api.create_booking(
            create_booking_payload(reg["patient"]["id"], reg["provider"]["id"],
                                   reg["ptype"]["id"], reg["room"]["id"],
                                   scheduled_start="2026-08-03T09:00:00Z"), SCHED), 201)
        assert created["procedure_minutes"] == 40
        assert_instants_equal(created["scheduled_end"], "2026-08-03T09:40:00Z")
        assert_instants_equal(created["room_block_end"], "2026-08-03T09:55:00Z")
        assert created["version"] == 1

        patched = validate_success(api.patch_booking(
            created["id"], {"expected_booking_version": created["version"],
                            "notes": "visible now"}, SCHED), 200)
        assert patched["notes"] == "visible now", "no re-fetch needed"
        assert patched["version"] == 2

    def test_scope_usage_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/scope_usage_not_found_returns_404
        """
        resp = api.get_scope_usage(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCOPE_USAGE_NOT_FOUND)
