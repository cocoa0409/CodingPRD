"""Parking session lifecycle: parallel occupancy/billing dimensions, exit
preconditions, ticket uniqueness, posture and credential gates, list filters."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_access_device_payload,
    enter_vehicle,
    enter_vehicle_at,
    get_facility,
    get_success_data,
    make_gate_device_headers,
    make_monthly_parker_headers,
    open_shift,
    pay_session_card_at,
    quote_session_at,
    set_clock,
    setup_agreement_with_credential,
    setup_card_settled_session,
    setup_entry_ready_facility,
    setup_facility_with_published_rate,
    setup_reported_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
ATT = TEST_USERS["parking_attendant_headers"]


def test_session_exit_unpaid_rejected(api):
    """PRD: "Any other exit attempt, with a positive fee still outstanding, is
    refused with `ERR_EXIT_UNPAID`."

    Design: Corner/state_machines/session_exit_unpaid_rejected
    """
    facility, schedule, gate = setup_entry_ready_facility(name="XU Fac")
    session = enter_vehicle_at(facility["id"], gate, "XU-1", "2026-08-01T10:00:00Z")
    set_clock("2026-08-01T11:00:00Z")
    res = api.exit_session(session["id"], make_gate_device_headers(gate["id"]))
    validate_error(res, ApiErrorId.ERR_EXIT_UNPAID)
    after = get_success_data(api.get_parking_session(session["id"], FM))
    assert after["occupancy_state"] == "PARKED"


def test_session_pay_after_exit_invalid(api):
    """PRD: "A `ParkingAttendant` settles a session still `PARKED` and still
    `OPEN` or `QUOTED` by naming a `tender_type` of `CASH` or `CARD`."
    PRD: "the target resource's current state permits the
    requested transition; this covers wrong-from-state actions, terminal-state
    lockdown, and repeat runs such as a second close-of-business for one
    business date, else `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/session_pay_after_exit_invalid
    """
    facility, schedule, gate, session = setup_card_settled_session(name="PX Fac")
    get_success_data(api.exit_session(session["id"], make_gate_device_headers(gate["id"])))
    res = api.pay_session(session["id"], {"tender_type": "CARD"}, ATT)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestParallelDimensions:
    """Billing and occupancy evolve independently on one session row."""

    def _build(self, api):
        facility, schedule, gate = setup_entry_ready_facility(name="Par Fac")
        shift = open_shift(facility["id"])
        session = enter_vehicle_at(facility["id"], gate, "PD-1", "2026-08-01T10:00:00Z")
        return facility, gate, shift, session

    def test_quote_then_comp_moves_billing_only(self, api):
        """PRD: "While the vehicle is inside, the two dimensions of a session
        move in parallel: `occupancy_state` (`PARKED`, then terminal `EXITED`)
        and `billing_state` (`OPEN`, `QUOTED`, `SETTLED`, `COMPED`,
        `REFUNDED`)."
        PRD: "A comped session moves to the terminal `COMPED` with
        `settled_fee_cents` zero and `tender_type` `NONE`"

        Design: Difficulty/non_linear_state_machine/parking_session_parallel_dimensions
        """
        facility, gate, shift, session = self._build(api)
        quote = quote_session_at(session["id"], "2026-08-01T12:00:00Z")
        after_quote = get_success_data(api.get_parking_session(session["id"], ATT))
        assert after_quote["occupancy_state"] == "PARKED"
        assert after_quote["billing_state"] == "QUOTED", (
            "billing moved, occupancy did not")

        comped = validate_success(api.comp_session(
            session["id"], {"reason": "VIP", "shift_id": shift["id"]}, ATT), 200)
        assert comped["occupancy_state"] == "PARKED"
        assert comped["billing_state"] == "COMPED"
        assert comped["settled_fee_cents"] == 0
        assert comped["tender_type"] == "NONE"

    def test_exit_after_comp_moves_occupancy_only(self, api):
        """PRD: "A session may leave when its billing stands `SETTLED` or
        `COMPED`"
        PRD: "A recorded exit moves occupancy to the terminal `EXITED`, stamps
        `exit_at`, and the derived `occupied_spaces` count falls by one."
        PRD: "the shift's `comp_total_cents` grows by the waived fee's value."

        Design: Difficulty/non_linear_state_machine/parking_session_parallel_dimensions
        """
        facility, gate, shift, session = self._build(api)
        quote_session_at(session["id"], "2026-08-01T12:00:00Z")
        get_success_data(api.comp_session(
            session["id"], {"reason": "VIP", "shift_id": shift["id"]}, ATT))
        exited = validate_success(api.exit_session(
            session["id"], make_gate_device_headers(gate["id"])), 200)
        assert exited["occupancy_state"] == "EXITED"
        assert exited["billing_state"] == "COMPED", (
            "occupancy moved, billing did not")
        shift_after = get_success_data(api.get_shift(shift["id"], FM))
        assert shift_after["comp_total_cents"] == 800, "2h waived value (500+300)"


def test_duplicate_ticket_rejected_then_reusable_after_exit(api):
    """PRD: "the barcode must not already be in use by another `PARKED`
    session of the same facility (`ERR_DUPLICATE_TICKET`)"

    Design: Corner/validations/duplicate_ticket_rejected_then_reusable_after_exit
    """
    facility, schedule, gate = setup_entry_ready_facility(name="DT Fac")
    first = enter_vehicle_at(facility["id"], gate, "T-DUP", "2026-08-01T10:00:00Z")
    res = api.create_parking_session(
        {"facility_id": facility["id"], "entry_device_id": gate["id"],
         "ticket_barcode": "T-DUP"},
        make_gate_device_headers(gate["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_TICKET)

    pay_session_card_at(first["id"], "2026-08-01T11:00:00Z")
    get_success_data(api.exit_session(first["id"], make_gate_device_headers(gate["id"])))
    second = validate_success(api.create_parking_session(
        {"facility_id": facility["id"], "entry_device_id": gate["id"],
         "ticket_barcode": "T-DUP"},
        make_gate_device_headers(gate["id"])), 201)
    assert second["occupancy_state"] == "PARKED"
    assert second["id"] != first["id"], (
        "uniqueness is scoped to PARKED sessions; after exit the barcode is reusable")


class TestEntryDeviceOffline:
    """Session validity depends on the entry device's state."""

    def _build(self, api):
        # Tariff published, but the gate is registered and never heartbeated.
        facility, schedule = setup_facility_with_published_rate(name="Gate Fac")
        device = get_success_data(api.create_access_device(
            create_access_device_payload(facility["id"], device_label="E1"), FM))
        return facility, device

    def test_entry_rejected_while_device_offline(self, api):
        """PRD: "the entry device must stand `ONLINE` and belong to the named
        facility (`ERR_DEVICE_NOT_ONLINE`)"
        PRD: "A new device stands `OFFLINE` with `device_mode` `STANDARD` and
        `last_heartbeat_at` null until its first heartbeat."

        Design: Difficulty/cross_entity_state_dependency/entry_rejected_when_device_offline
        """
        facility, device = self._build(api)
        res = api.create_parking_session(
            {"facility_id": facility["id"], "entry_device_id": device["id"],
             "ticket_barcode": "XD-1"},
            make_gate_device_headers(device["id"]))
        validate_error(res, ApiErrorId.ERR_DEVICE_NOT_ONLINE)

    def test_entry_succeeds_after_heartbeat(self, api):
        """PRD: "a successful heartbeat moves the device from `OFFLINE` or
        `DEGRADED` to `ONLINE`, stamping `last_heartbeat_at` with the logical
        now."
        PRD: "A recorded entry stands `PARKED` with billing `OPEN`"

        Design: Difficulty/cross_entity_state_dependency/entry_rejected_when_device_offline
        """
        facility, device = self._build(api)
        online = validate_success(api.heartbeat_device(
            device["id"], make_gate_device_headers(device["id"])), 200)
        assert online["device_status"] == "ONLINE"
        session = validate_success(api.create_parking_session(
            {"facility_id": facility["id"], "entry_device_id": device["id"],
             "ticket_barcode": "XD-1"},
            make_gate_device_headers(device["id"])), 201)
        assert session["occupancy_state"] == "PARKED"


def test_posture_blocks_transient_entry_but_allows_monthly(api):
    """PRD: "A transient entry is admitted only while posture is `NORMAL` or
    `EVENT_SURGE`; a credentialed monthly entry is additionally admitted under
    `RESTRICTED`."

    Design: Corner/validations/posture_blocks_transient_entry_but_allows_monthly
    """
    facility, schedule, gate = setup_entry_ready_facility(name="PB Fac")
    parker, agreement, credential = setup_agreement_with_credential(facility["id"])
    # CRITICAL report (load-bearing 2, no spaces closed) flips posture.
    setup_reported_inspection(facility["id"], level_scope="L1",
                              load_bearing_rating=2, waterproofing_rating=5,
                              surface_rating=5, closed_space_count=0)
    assert get_facility(facility["id"])["posture"] == "RESTRICTED"

    res = api.create_parking_session(
        {"facility_id": facility["id"], "entry_device_id": gate["id"],
         "ticket_barcode": "PB-1"},
        make_gate_device_headers(gate["id"]))
    validate_error(res, ApiErrorId.ERR_FACILITY_POSTURE_BLOCKS)

    monthly = validate_success(api.create_parking_session(
        {"facility_id": facility["id"], "entry_device_id": gate["id"],
         "ticket_barcode": "PB-2", "credential_id": credential["id"]},
        make_gate_device_headers(gate["id"])), 201)
    assert monthly["fee_mode"] == "MONTHLY"


def test_entry_with_lost_credential_rejected(api):
    """PRD: "when a credential is presented, that credential must stand
    `ACTIVE` and its agreement must stand `ACTIVE` (`ERR_CREDENTIAL_NOT_VALID`)"

    Design: Corner/errors/entry_with_lost_credential_rejected
    """
    facility, schedule, gate = setup_entry_ready_facility(name="LC Fac")
    parker, agreement, credential = setup_agreement_with_credential(facility["id"])
    get_success_data(api.report_credential_lost(
        credential["id"], make_monthly_parker_headers(parker["id"])))
    res = api.create_parking_session(
        {"facility_id": facility["id"], "entry_device_id": gate["id"],
         "ticket_barcode": "LC-1", "credential_id": credential["id"]},
        make_gate_device_headers(gate["id"]))
    validate_error(res, ApiErrorId.ERR_CREDENTIAL_NOT_VALID)


def test_session_list_filter_by_billing_state(api):
    """PRD: "The session list filters by `facility_id`, `credential_id`,
    `rate_schedule_id`, `entry_device_id`, `paid_in_shift_id`,
    `occupancy_state`, or `billing_state`."
    PRD: "`paid_in_shift_id` is null unless the session settled in cash."

    Design: Corner/endpoints/session_list_filter_by_billing_state
    """
    facility, schedule, gate = setup_entry_ready_facility(name="FL Fac")
    shift = open_shift(facility["id"])
    set_clock("2026-08-01T10:00:00Z")
    s1 = enter_vehicle(facility["id"], gate, "FL-1")
    s2 = enter_vehicle(facility["id"], gate, "FL-2")
    s3 = enter_vehicle(facility["id"], gate, "FL-3")
    set_clock("2026-08-01T11:00:00Z")
    get_success_data(api.pay_session(
        s1["id"], {"tender_type": "CASH", "shift_id": shift["id"]}, ATT))
    get_success_data(api.comp_session(
        s2["id"], {"reason": "VIP", "shift_id": shift["id"]}, ATT))

    settled, meta = validate_paginated(api.list_parking_sessions(
        FM, params={"facility_id": facility["id"], "billing_state": "SETTLED"}))
    assert [row["id"] for row in settled] == [s1["id"]]
    assert meta["total_count"] == 1

    parked, meta = validate_paginated(api.list_parking_sessions(
        FM, params={"facility_id": facility["id"], "occupancy_state": "PARKED"}))
    assert len(parked) == 3, "none exited"

    in_shift, meta = validate_paginated(api.list_parking_sessions(
        FM, params={"paid_in_shift_id": shift["id"]}))
    assert [row["id"] for row in in_shift] == [s1["id"]], (
        "comp sets no shift link")
