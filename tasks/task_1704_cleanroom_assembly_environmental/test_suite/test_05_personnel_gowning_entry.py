"""Personnel, gowning qualification, and room entry logging."""
from test_helpers import (
    QA,
    ApiErrorId,
    assert_entry_log,
    create_entry_log_payload,
    create_personnel,
    create_qualified_personnel,
    get_success_data,
    grant_gowning,
    is_iso8601_timestamp,
    make_production_operator_headers,
    set_clock,
    setup_certified_room,
    validate_error,
    validate_paginated,
    validate_success,
)


def _certified_room_with_personnel(room_code, recert_interval_days=180):
    room = setup_certified_room(
        room_code=room_code, iso_class="ISO_8",
        particle_alert_limit=3500000, particle_action_limit=3520000,
        viable_alert_limit=100, viable_action_limit=200,
        recert_interval_days=recert_interval_days)
    personnel, qualification = create_qualified_personnel(
        room["id"], employee_code=f"EMP-{room_code}", full_name="Entry Operator")
    return room, personnel, qualification


class TestEntryExitLifecycle:
    def test_entry_then_exit_stamps_server_timestamps(self, api):
        """PRD §3.2: "A successful entry stamps `entered_at` at log time and
        leaves `exited_at` null while the person is inside; the matching exit,
        also performed by a `ProductionOperator`, stamps `exited_at`."

        Design: Corner/state_machines/entry_exit_happy_path
        """
        room, personnel, _qual = _certified_room_with_personnel("CR-S1")

        entry = validate_success(api.create_entry_log(
            create_entry_log_payload(personnel["id"], room["id"]),
            make_production_operator_headers("op-s1")), 201)
        assert_entry_log(entry)
        assert is_iso8601_timestamp(entry["entered_at"])
        assert entry["exited_at"] is None

        exited = validate_success(api.exit_entry_log(
            entry["id"], make_production_operator_headers("op-s1")), 200)
        assert exited["exited_at"] is not None
        assert is_iso8601_timestamp(exited["exited_at"])


class TestOpenEntryInterval:
    def test_second_entry_while_inside_rejected(self, api):
        """PRD §3.2: "Entry is refused with `ERR_PERSONNEL_SUSPENDED` when the
        person is `SUSPENDED`; with `ERR_GOWNING_NOT_QUALIFIED` when no
        `QUALIFIED`, unexpired qualification exists for that person-and-room
        pair; with `ERR_ROOM_NOT_IN_CONTROL` when the room's posture is raised;
        and with `ERR_ENTRY_ALREADY_OPEN` when an entry log whose `exited_at`
        is still null already exists for the same pair — one person cannot be
        inside the same room twice."

        Design: Difficulty/resource_temporal_overlap/personnel_open_entry_interval_blocks_second_entry
        """
        room, personnel, _qual = _certified_room_with_personnel("CR-O")
        first = validate_success(api.create_entry_log(
            create_entry_log_payload(personnel["id"], room["id"]),
            make_production_operator_headers("op-o")), 201)
        assert first["exited_at"] is None

        resp = api.create_entry_log(
            create_entry_log_payload(personnel["id"], room["id"]),
            make_production_operator_headers("op-o"))
        validate_error(resp, ApiErrorId.ERR_ENTRY_ALREADY_OPEN)

    def test_reentry_allowed_after_exit(self, api):
        """PRD §3.2: "with `ERR_ENTRY_ALREADY_OPEN` when an entry log whose
        `exited_at` is still null already exists for the same pair — one person
        cannot be inside the same room twice."
        PRD §3.2: "A successful entry stamps `entered_at` at log time and
        leaves `exited_at` null while the person is inside; the matching exit,
        also performed by a `ProductionOperator`, stamps `exited_at`."

        Design: Difficulty/resource_temporal_overlap/personnel_open_entry_interval_blocks_second_entry
        """
        room, personnel, _qual = _certified_room_with_personnel("CR-O")
        first = validate_success(api.create_entry_log(
            create_entry_log_payload(personnel["id"], room["id"]),
            make_production_operator_headers("op-o")), 201)

        exited = validate_success(api.exit_entry_log(
            first["id"], make_production_operator_headers("op-o")), 200)
        assert exited["exited_at"] is not None, (
            "exit closes the occupancy interval")

        second = validate_success(api.create_entry_log(
            create_entry_log_payload(personnel["id"], room["id"]),
            make_production_operator_headers("op-o")), 201)
        assert second["id"] != first["id"]
        assert second["exited_at"] is None


class TestGowningExpiryBoundary:
    def test_gowning_expired_blocks_entry_at_exact_boundary(self, api):
        """PRD §3.2: "The qualification stands `QUALIFIED` until the logical
        clock reaches the expiry instant — at the exact expiry instant, entry
        is already denied — at which point lazy evaluation marks it `EXPIRED`."
        PRD §3.2: "Entry is refused with `ERR_PERSONNEL_SUSPENDED` when the
        person is `SUSPENDED`; with `ERR_GOWNING_NOT_QUALIFIED` when no
        `QUALIFIED`, unexpired qualification exists for that person-and-room
        pair; with `ERR_ROOM_NOT_IN_CONTROL` when the room's posture is raised;
        and with `ERR_ENTRY_ALREADY_OPEN` when an entry log whose `exited_at`
        is still null already exists for the same pair — one person cannot be
        inside the same room twice."

        Design: Corner/state_machines/gowning_expired_blocks_entry_at_exact_boundary
        """
        # recert_interval_days=3650 keeps the room CERTIFIED past the
        # qualification expiry instant.
        room, personnel, _qual = _certified_room_with_personnel(
            "CR-S7", recert_interval_days=3650)
        # Qualified at the default clock 2026-08-01T00:00:00Z; the expiry
        # instant is exactly 2027-08-01T00:00:00Z.
        set_clock("2027-07-31T23:59:59Z")
        entry = validate_success(api.create_entry_log(
            create_entry_log_payload(personnel["id"], room["id"]),
            make_production_operator_headers("op-s7")), 201)
        get_success_data(api.exit_entry_log(
            entry["id"], make_production_operator_headers("op-s7")))

        set_clock("2027-08-01T00:00:00Z")
        resp = api.create_entry_log(
            create_entry_log_payload(personnel["id"], room["id"]),
            make_production_operator_headers("op-s7"))
        validate_error(resp, ApiErrorId.ERR_GOWNING_NOT_QUALIFIED)


class TestSuspendedPersonnel:
    def test_suspended_personnel_entry_rejected(self, api):
        """PRD §3.2: "Entry is refused with `ERR_PERSONNEL_SUSPENDED` when the
        person is `SUSPENDED`".
        PRD §3.2: "While `SUSPENDED`, the person may not enter any room."

        Design: Corner/errors/error_personnel_suspended_on_entry
        """
        room, personnel, _qual = _certified_room_with_personnel("CR-ERE")
        suspended = validate_success(api.suspend_personnel(personnel["id"], QA), 200)
        assert suspended["status"] == "SUSPENDED"

        resp = api.create_entry_log(
            create_entry_log_payload(personnel["id"], room["id"]),
            make_production_operator_headers("op-ere"))
        validate_error(resp, ApiErrorId.ERR_PERSONNEL_SUSPENDED)


class TestGowningQualificationListing:
    def test_gowning_qualifications_filtered_by_personnel(self, api):
        """PRD §3.2: "Qualifications are listable filtered by `personnel_id`,
        `cleanroom_id`, or `status`, and both directions of sub-resource
        listing exist — the qualifications held for a room, and the
        qualifications held by one personnel record."

        Design: Corner/endpoints/gowning_qualification_filtered_list
        """
        room = setup_certified_room(
            room_code="CR-F1", iso_class="ISO_8",
            particle_alert_limit=3500000, particle_action_limit=3520000,
            viable_alert_limit=100, viable_action_limit=200)
        pers_f1 = create_personnel(employee_code="EMP-F1", full_name="Eff One")
        pers_f2 = create_personnel(employee_code="EMP-F2", full_name="Eff Two")
        grant_gowning(pers_f1["id"], room["id"])

        data_f1, meta_f1 = validate_paginated(
            api.list_gowning_qualifications(QA, params={"personnel_id": pers_f1["id"]}))
        assert len(data_f1) == 1
        assert data_f1[0]["personnel_id"] == pers_f1["id"]

        data_f2, meta_f2 = validate_paginated(
            api.list_gowning_qualifications(QA, params={"personnel_id": pers_f2["id"]}))
        assert data_f2 == []
        assert meta_f2["total_count"] == 0
