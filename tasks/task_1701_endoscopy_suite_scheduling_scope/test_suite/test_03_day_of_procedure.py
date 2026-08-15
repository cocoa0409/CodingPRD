"""Prep confirmation, check-in windows, procedure start gates, scope selection."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_booking,
    check_in,
    complete_procedure,
    assess_prep,
    confirm_prep,
    create_booking,
    create_booking_payload,
    create_checked_in_booking,
    create_colono_type,
    create_patient,
    create_provider,
    create_reprocessed_scope,
    create_room,
    create_scope,
    first_usage_for_booking,
    get_scope,
    make_endoscopist_headers,
    make_registry,
    run_complete_cycle,
    start_procedure,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestPrepAndCheckIn:
    def test_confirm_prep_happy_path(self, api):
        """
        PRD §3.4: "Once the patient has taken their prep, a `SchedulingCoordinator`
        records the attestation, moving the prep axis from `PREP_PENDING` to
        `PREP_CONFIRMED`."

        PRD §2.5: "**`version`** (integer): starts at 1 when the resource is created
        and increments by exactly 1 on every mutation, including mutations driven by
        cascades originating on other entities."

        Design: Corner/state_machines/confirm_prep_happy_path
        """
        reg = make_registry(mrn="MRN-CP", serial="SC-CP", with_scope=False)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        data = validate_success(api.confirm_prep(booking["id"], SCHED), 200)
        assert data["prep_status"] == "PREP_CONFIRMED"
        assert data["status"] == "SCHEDULED", "booking axis untouched"
        assert data["version"] == booking["version"] + 1

    def test_check_in_requires_confirmed_prep_rejected(self, api):
        """PRD §3.4: "The prep axis must already be `PREP_CONFIRMED`
        (`ERR_PREP_NOT_CONFIRMED`), and the arrival must fall within the check-in
        window running from sixty minutes before `scheduled_start` through thirty
        minutes after it, inclusive at both ends; an arrival outside that window
        is refused with `ERR_CHECKIN_WINDOW_CLOSED`."

        Design: Corner/state_machines/check_in_requires_confirmed_prep_rejected
        """
        reg = make_registry(mrn="MRN-PC", serial="SC-PC", with_scope=False)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        advance_clock("2026-08-03T09:00:00Z")
        resp = api.check_in_booking(booking["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_PREP_NOT_CONFIRMED)
        fetched = validate_success(api.get_booking(booking["id"], ADMIN))
        assert fetched["status"] == "SCHEDULED"

    def test_checkin_and_noshow_window_bounds(self, api):
        """PRD §3.4: "the arrival must fall within the check-in window running
        from sixty minutes before `scheduled_start` through thirty minutes after
        it, inclusive at both ends; an arrival outside that window is refused with
        `ERR_CHECKIN_WINDOW_CLOSED`."
        PRD §3.4: "the logical time must be strictly later than thirty minutes
        past `scheduled_start`, with earlier attempts refused by
        `ERR_NO_SHOW_WINDOW_NOT_REACHED`."

        Design: Corner/state_machines/checkin_and_noshow_window_bounds
        """
        patient = create_patient(mrn="MRN-WB")
        provider = create_provider("Dr Wb")
        t_col = create_colono_type()
        rooms = [create_room(name=n) for n in ("R1", "R2", "R3")]
        b1 = create_booking(patient["id"], provider["id"], t_col["id"],
                            rooms[0]["id"], scheduled_start="2026-08-03T09:00:00Z")
        b2 = create_booking(patient["id"], provider["id"], t_col["id"],
                            rooms[1]["id"], scheduled_start="2026-08-03T09:00:00Z")
        b3 = create_booking(patient["id"], provider["id"], t_col["id"],
                            rooms[2]["id"], scheduled_start="2026-08-03T09:15:00Z")
        for b in (b1, b2, b3):
            confirm_prep(b["id"])

        # Exactly start-60min: inclusive lower bound admits the arrival.
        advance_clock("2026-08-03T08:00:00Z")
        data = validate_success(api.check_in_booking(b1["id"], SCHED), 200)
        assert data["status"] == "CHECKED_IN"

        # B3 at start+15min: no-show window (strictly > +30) not reached.
        advance_clock("2026-08-03T09:30:00Z")
        resp = api.mark_no_show(b3["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_NO_SHOW_WINDOW_NOT_REACHED)

        # B2 at start+31min: check-in upper bound exceeded.
        advance_clock("2026-08-03T09:31:00Z")
        resp = api.check_in_booking(b2["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)

        # The same instant is strictly past the no-show grace: mark succeeds.
        data = validate_success(api.mark_no_show(b2["id"], SCHED), 200)
        assert data["status"] == "NO_SHOW"


class TestStartGates:
    def test_start_requires_checked_in_rejected(self, api):
        """PRD §3.4: "The booking axis must be `CHECKED_IN`
        (`ERR_BOOKING_NOT_CHECKED_IN`)".

        Design: Corner/state_machines/start_requires_checked_in_rejected
        """
        reg = make_registry(mrn="MRN-SC", serial="SC-S1")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        confirm_prep(booking["id"])
        advance_clock("2026-08-03T09:00:00Z")
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CHECKED_IN)

    def test_explicit_scope_wrong_state_rejected(self, api):
        """PRD §3.4: "The endoscopist may name an explicit `scope_id`, in which
        case the scope must be `AVAILABLE` (`ERR_SCOPE_NOT_AVAILABLE`)".

        Design: Corner/validations/explicit_scope_wrong_state_rejected
        """
        patient = create_patient(mrn="MRN-WS")
        provider = create_provider("Dr Ws")
        t_col = create_colono_type()
        r1 = create_room(name="R1")
        r2 = create_room(name="R2")
        busy = create_scope(serial_number="SC-BUSY")
        b1 = create_booking(patient["id"], provider["id"], t_col["id"], r1["id"],
                            scheduled_start="2026-08-03T09:00:00Z")
        b2 = create_booking(patient["id"], provider["id"], t_col["id"], r2["id"],
                            scheduled_start="2026-08-03T09:00:00Z")
        confirm_prep(b1["id"])
        confirm_prep(b2["id"])
        advance_clock("2026-08-03T09:00:00Z")
        check_in(b1["id"])
        start_procedure(b1["id"], provider["id"], busy["id"])
        check_in(b2["id"])
        resp = api.start_booking(b2["id"], {"scope_id": busy["id"]},
                                 make_endoscopist_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_AVAILABLE)
        assert validate_success(api.get_booking(b2["id"], ADMIN))["status"] == "CHECKED_IN"

    def test_endoscopist_cannot_start_other_providers_booking(self, api):
        """PRD §3.4: "Starting the procedure belongs to the `Endoscopist` who owns
        the booking: the caller's `X-User-ID` must equal the booking's
        `provider_id` (`ERR_PROVIDER_OWNERSHIP_MISMATCH`)."

        Design: Corner/rbac/endoscopist_cannot_start_other_providers_booking
        """
        reg = make_registry(mrn="MRN-OWN", serial="SC-OWN")
        dr2 = create_provider("Dr Two", specialty="COLORECTAL_SURGERY")
        booking = create_checked_in_booking(
            reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
            reg["room"]["id"], reg["scope"]["id"], "2026-08-03T09:00:00Z")
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(dr2["id"]))
        validate_error(resp, ApiErrorId.ERR_PROVIDER_OWNERSHIP_MISMATCH)
        assert validate_success(api.get_booking(booking["id"], ADMIN))["status"] == "CHECKED_IN"
        assert get_scope(reg["scope"]["id"])["status"] == "AVAILABLE"

    def test_state_beats_business_safety_on_procedure_start(self, api):
        """
        PRD §2.6: "When a single request violates several rules, exactly one error
        surfaces, chosen by the following ladder — earlier rungs win over later
        ones:"

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

        PRD §2.6: "8. **Compliance gates** — a suspended provider or anesthesia
        provider (`ERR_PROVIDER_SUSPENDED`, `ERR_ANESTHESIA_PROVIDER_SUSPENDED`),
        anesthesia coverage not yet confirmed when required
        (`ERR_ANESTHESIA_NOT_CONFIRMED`), an explicitly named scope past its storage
        limit (`ERR_SCOPE_STORAGE_EXPIRED`), disinfectant concentration below the
        floor (`ERR_HLD_CONCENTRATION_TOO_LOW`), a reprocessing step advanced before
        its minimum dwell time (`ERR_STEP_DURATION_TOO_SHORT`), or a specimen label
        or transport window exceeded (`ERR_LABEL_WINDOW_EXCEEDED`,
        `ERR_TRANSPORT_WINDOW_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_procedure_start
        """
        reg = make_registry(mrn="M5001", serial="SC-E1")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-02T09:00:00Z")
        # Reprocess the scope so its storage expires at 2026-08-04T08:26:00Z.
        run_complete_cycle(reg["scope"]["id"], "2026-08-01T08:00:00Z", lot="LOT-E",
                           send_first=True)
        cancel_resp = api.cancel_booking(booking["id"], {"reason": "patient request"},
                                         SCHED)
        validate_success(cancel_resp, 200)
        # Past the scope's storage expiry, start the CANCELLED booking.
        advance_clock("2026-08-04T09:00:00Z")
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CHECKED_IN)
        assert resp.status_code == 409

    def test_state_over_safety_control_expired_scope_alone_rejected(self, api):
        """PRD §3.4: "the scope must be `AVAILABLE` (`ERR_SCOPE_NOT_AVAILABLE`),
        must be storage-current — its `is_storage_current` true, meaning a null
        `storage_expires_at` or a logical now strictly before it — with
        `ERR_SCOPE_STORAGE_EXPIRED` the refusal".

        Control: a properly CHECKED_IN booking starting with the storage-expired
        scope proves the safety gate was live in the paired priority scenario.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_procedure_start
        """
        reg = make_registry(mrn="M5002", serial="SC-E2")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-04T09:00:00Z")
        confirm_prep(booking["id"])
        run_complete_cycle(reg["scope"]["id"], "2026-08-01T08:00:00Z", lot="LOT-E",
                           send_first=True)
        advance_clock("2026-08-04T09:00:00Z")
        check_in(booking["id"])
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_STORAGE_EXPIRED)

    def test_booking_start_blocked_when_provider_suspended(self, api):
        """PRD §3.4: "the provider's `credential_status` must be `ACTIVE`
        (`ERR_PROVIDER_SUSPENDED`)".
        PRD §3.1: "suspension has teeth — a `SUSPENDED` provider cannot take new
        bookings and cannot start procedures."

        Design: Difficulty/cross_entity_state_dependency/booking_start_blocked_when_provider_suspended
        """
        reg = make_registry(mrn="M7201", serial="SC-SUS")
        drs = reg["provider"]
        booking = create_booking(reg["patient"]["id"], drs["id"], reg["ptype"]["id"],
                                 reg["room"]["id"],
                                 scheduled_start="2026-08-02T09:00:00Z")
        confirm_prep(booking["id"])
        validate_success(api.patch_provider(drs["id"],
                                            {"credential_status": "SUSPENDED"}, ADMIN))
        advance_clock("2026-08-02T09:00:00Z")
        # Check-in is not among the suspension gates, so it succeeds here.
        data = validate_success(api.check_in_booking(booking["id"], SCHED), 200)
        assert data["status"] == "CHECKED_IN"
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(drs["id"]))
        validate_error(resp, ApiErrorId.ERR_PROVIDER_SUSPENDED)
        assert validate_success(api.get_booking(booking["id"], ADMIN))["status"] == "CHECKED_IN"

    def test_provider_reinstatement_unblocks_start(self, api):
        """PRD §3.1: "a `UnitAdmin` may later amend a provider's `full_name` or
        move `credential_status` between `ACTIVE` and `SUSPENDED`, and suspension
        has teeth — a `SUSPENDED` provider cannot take new bookings and cannot
        start procedures."
        PRD §3.4: "the provider's `credential_status` must be `ACTIVE`
        (`ERR_PROVIDER_SUSPENDED`)".

        Design: Difficulty/cross_entity_state_dependency/booking_start_blocked_when_provider_suspended
        """
        reg = make_registry(mrn="M7202", serial="SC-SUS2")
        drs = reg["provider"]
        booking = create_booking(reg["patient"]["id"], drs["id"], reg["ptype"]["id"],
                                 reg["room"]["id"],
                                 scheduled_start="2026-08-02T09:00:00Z")
        confirm_prep(booking["id"])
        validate_success(api.patch_provider(drs["id"],
                                            {"credential_status": "SUSPENDED"}, ADMIN))
        advance_clock("2026-08-02T09:00:00Z")
        check_in(booking["id"])
        validate_success(api.patch_provider(drs["id"],
                                            {"credential_status": "ACTIVE"}, ADMIN))
        data = validate_success(api.start_booking(
            booking["id"], {"scope_id": reg["scope"]["id"]},
            make_endoscopist_headers(drs["id"])), 200)
        assert data["status"] == "IN_PROGRESS"


class TestScopeSelection:
    def test_selector_tiebreak_created_at_then_use_count(self, api):
        """PRD §3.4: "eligible scopes are ranked by `use_count` ascending so the
        least-worn scope goes first, ties break toward the earliest
        `storage_expires_at` with never-expiring scopes (null) sorted last, and
        further ties fall to `created_at` ascending."

        Design: Corner/calculations/selector_tiebreak_created_at_then_use_count
        """
        patient = create_patient(mrn="MRN-SEL")
        provider = create_provider("Dr Sel")
        t_col = create_colono_type()
        room = create_room(name="RS")
        ss1 = create_scope(serial_number="SS-1")
        ss2 = create_scope(serial_number="SS-2")
        b1 = create_booking(patient["id"], provider["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-12T09:00:00Z")
        b2 = create_booking(patient["id"], provider["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-12T11:00:00Z")
        confirm_prep(b1["id"])
        confirm_prep(b2["id"])
        advance_clock("2026-08-12T09:00:00Z")
        check_in(b1["id"])
        start_procedure(b1["id"], provider["id"])  # auto-select
        assert first_usage_for_booking(b1["id"])["scope_id"] == ss1["id"], (
            "tied at use_count 0 with null expiry: earliest created_at wins")
        assess_prep(b1["id"], provider["id"], 2, 2, 2)
        advance_clock("2026-08-12T09:40:00Z")
        complete_procedure(b1["id"], provider["id"])
        run_complete_cycle(ss1["id"], "2026-08-12T10:00:00Z", lot="LOT-S",
                           booking_id=b1["id"])

        advance_clock("2026-08-12T11:00:00Z")
        check_in(b2["id"])
        start_procedure(b2["id"], provider["id"])  # auto-select
        assert first_usage_for_booking(b2["id"])["scope_id"] == ss2["id"], (
            "use_count 0 beats the reprocessed scope's 1")
        assert get_scope(ss1["id"])["use_count"] == 1
        assert get_scope(ss1["id"])["status"] == "AVAILABLE"
        assert get_scope(ss2["id"])["status"] == "IN_USE"

    def test_selector_skips_expired_and_wrong_type(self, api):
        """PRD §3.4: "eligibility requires a matching `scope_type`, `AVAILABLE`
        status, and storage currency".
        PRD §3.6: "at the exact expiry instant the scope is already expired."

        Design: Corner/calculations/selector_skips_expired_and_wrong_type
        """
        patient = create_patient(mrn="MRN-SK")
        provider = create_provider("Dr Sk")
        t_col = create_colono_type()
        room = create_room(name="R-SK")
        create_scope(serial_number="SG-WRONG", scope_type="GASTROSCOPE")
        sc_exp = create_scope(serial_number="SC-EXP")
        sc_ok = create_scope(serial_number="SC-OK")
        booking = create_booking(patient["id"], provider["id"], t_col["id"],
                                 room["id"], scheduled_start="2026-08-24T09:00:00Z")
        confirm_prep(booking["id"])
        # SC-EXP's cycle dries 2026-08-20T08:26 -> expiry 2026-08-23T08:26.
        run_complete_cycle(sc_exp["id"], "2026-08-20T08:00:00Z", lot="LOT-E",
                           send_first=True)
        advance_clock("2026-08-24T09:00:00Z")
        check_in(booking["id"])
        start_procedure(booking["id"], provider["id"])  # auto-select
        usage = first_usage_for_booking(booking["id"])
        assert usage["scope_id"] == sc_ok["id"], (
            "wrong type and storage-expired scopes are both ineligible")
        expired = get_scope(sc_exp["id"])
        assert expired["status"] == "AVAILABLE"
        assert expired["is_storage_current"] is False

    def test_selector_empty_pool_rejected(self, api):
        """PRD §3.4: "An empty eligible pool refuses the start with
        `ERR_NO_COMPATIBLE_SCOPE`."

        Design: Corner/calculations/selector_empty_pool_rejected
        """
        patient = create_patient(mrn="MRN-EP")
        provider = create_provider("Dr Ep")
        t_col = create_colono_type()
        room = create_room(name="R-EP")
        create_scope(serial_number="SG-ONLY", scope_type="GASTROSCOPE")
        booking = create_checked_in_booking(
            patient["id"], provider["id"], t_col["id"], room["id"], None,
            "2026-08-03T09:00:00Z")
        resp = api.start_booking(booking["id"], {},
                                 make_endoscopist_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_COMPATIBLE_SCOPE)
        assert validate_success(api.get_booking(booking["id"], ADMIN))["status"] == "CHECKED_IN"
