"""Equipment declaration and the safety/authenticity inspection pipeline:
failure counting, waivers under segregation of duties, and the buffered
45-minute inspection window."""
from test_helpers import (
    TEST_USERS,
    api_client,
    ApiErrorId,
    create_equipment_item_payload,
    schedule_inspection_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_participant,
    declare_equipment,
    record_inspection,
    schedule_inspection,
    setup_approved_unit,
    setup_failed_equipment,
    setup_registration_open_event,
)
from test_helpers.test_users import make_safety_officer_headers, make_unit_commander_headers

ORG = TEST_USERS["organizer_headers"]
SO1 = TEST_USERS["safety_officer_headers"]


def _setup_event_unit_participant(item_type="FIREARM"):
    """REGISTRATION_OPEN event + APPROVED unit + DRAFT participant."""
    event = setup_registration_open_event()
    unit = setup_approved_unit(event["id"])
    participant = create_participant(event["id"], unit_id=unit["id"])
    return event, unit, participant


class TestFailureCounting:
    def test_equipment_banned_after_second_failure(self, api):
        """PRD §3.4: "the item moves `INSPECTION_DUE → FAILED` and its
        `failure_count` is incremented by one, except that an increment bringing
        `failure_count` to two moves the item immediately to `BANNED` instead"
        PRD §3.4: "The item must be in `DECLARED`, `FAILED`, or `INSPECTION_DUE`
        (`ERR_INVALID_EQUIPMENT_STATUS` otherwise)"

        Design: Corner/state_machines/equipment_banned_after_second_failure
        """
        event, unit, participant = _setup_event_unit_participant()
        item = declare_equipment(participant["id"], unit_id=unit["id"], item_type="FIREARM")

        first = schedule_inspection(item["id"], officer="so-1",
                                    scheduled_for="2026-07-10T09:00:00Z")
        record_inspection(first["id"], officer="so-1", outcome="FAIL",
                          failure_reason="filed-down sear")
        mid = validate_success(api_client.get_equipment_item(item["id"], ORG), 200)
        assert mid["status"] == "FAILED"
        assert mid["failure_count"] == 1

        second = schedule_inspection(item["id"], officer="so-1",
                                     scheduled_for="2026-07-10T11:00:00Z")
        record_inspection(second["id"], officer="so-1", outcome="FAIL",
                          failure_reason="sear still unsafe")

        banned = validate_success(api_client.get_equipment_item(item["id"], ORG), 200)
        assert banned["failure_count"] == 2
        assert banned["status"] == "BANNED", "the second failure auto-bans the item"

        resp = api_client.schedule_inspection(
            item["id"],
            schedule_inspection_payload(scheduled_for="2026-07-10T13:00:00Z"),
            SO1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_EQUIPMENT_STATUS, 409)


class TestWaiver:
    def test_inspection_waive_by_different_officer_succeeds(self, api):
        """PRD §3.4: "A successful waiver stamps `waived_by_user_id`, records the
        reason, moves the inspection to `WAIVED`, and moves the item `FAILED →
        WAIVED`."

        Design: Corner/state_machines/inspection_waive_by_different_officer_succeeds
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        participant, item, inspection = setup_failed_equipment(
            event["id"], unit_id=unit["id"], item_type="EDGED", officer="so-1"
        )
        resp = api_client.waive_inspection(
            inspection["id"],
            {"waiver_reason": "hilt secured on re-check; display only"},
            make_safety_officer_headers("so-2"),
        )
        waived = validate_success(resp, 200)
        assert waived["status"] == "WAIVED"
        assert waived["waived_by_user_id"] == "so-2"
        assert waived["recorded_by_user_id"] == "so-1"
        assert waived["waived_by_user_id"] != waived["recorded_by_user_id"]

        reread = validate_success(api_client.get_equipment_item(item["id"], ORG), 200)
        assert reread["status"] == "WAIVED", "the item follows the waiver"

    def test_sod_self_waiver_rejected(self, api):
        """PRD §3.4: "the waiving officer's `X-User-ID` must differ from the
        inspection's `recorded_by_user_id`; the same officer who recorded the
        failure cannot waive it, and such an attempt is rejected with
        `ERR_SOD_SELF_WAIVER`."

        Design: Corner/state_machines/sod_self_waiver_rejected
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        participant, item, inspection = setup_failed_equipment(
            event["id"], unit_id=unit["id"], item_type="EDGED", officer="so-1"
        )
        resp = api_client.waive_inspection(
            inspection["id"],
            {"waiver_reason": "self-waiver attempt"},
            make_safety_officer_headers("so-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_SELF_WAIVER, 403)

        inspections = validate_success(api_client.list_item_inspections(item["id"], ORG), 200)
        assert inspections[0]["status"] == "RECORDED_FAIL", "rejected waiver changes nothing"
        reread = validate_success(api_client.get_equipment_item(item["id"], ORG), 200)
        assert reread["status"] == "FAILED"


class TestRecordingStateGate:
    def test_record_already_recorded_inspection_rejected(self, api):
        """PRD §3.4: "Recording an outcome likewise belongs to the `SafetyOfficer`
        and is valid only from `SCHEDULED` (`ERR_INVALID_INSPECTION_STATUS`)."

        Design: Corner/state_machines/record_already_recorded_inspection_rejected
        """
        event, unit, participant = _setup_event_unit_participant(item_type="TENTAGE")
        item = declare_equipment(participant["id"], unit_id=unit["id"],
                                 item_type="TENTAGE", description="A-frame canvas tent")
        inspection = schedule_inspection(item["id"], officer="so-1",
                                         scheduled_for="2026-07-10T09:00:00Z",
                                         inspection_kind="AUTHENTICITY")
        recorded = record_inspection(inspection["id"], officer="so-1", outcome="PASS")
        assert recorded["status"] == "RECORDED_PASS"

        resp = api_client.record_inspection(
            inspection["id"], {"outcome": "FAIL", "failure_reason": "changed mind"}, SO1
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INSPECTION_STATUS, 409)
        inspections = validate_success(api_client.list_item_inspections(item["id"], ORG), 200)
        assert inspections[0]["status"] == "RECORDED_PASS", (
            "a terminal inspection cannot be re-recorded"
        )


class TestBufferedWindow:
    def test_inspection_window_closed_buffer_touching_conflicts(self, api):
        """PRD §3.4: "the new window, expanded by fifteen minutes on both sides,
        must not intersect any other `SCHEDULED` inspection window of the same
        equipment item, and for this buffered comparison touching counts as
        conflict. Consequently a new inspection beginning exactly fifteen minutes
        after an existing window's end is rejected with
        `ERR_INSPECTION_WINDOW_CONFLICT`, while one beginning sixteen minutes
        after is accepted."

        Design: Difficulty/resource_temporal_overlap/inspection_window_closed_buffer_touching_conflicts
        """
        event, unit, participant = _setup_event_unit_participant()
        item = declare_equipment(participant["id"], unit_id=unit["id"], item_type="FIREARM")
        first = schedule_inspection(item["id"], officer="so-1",
                                    scheduled_for="2026-07-10T09:00:00Z")

        touching = api_client.schedule_inspection(
            item["id"],
            schedule_inspection_payload(scheduled_for="2026-07-10T10:00:00Z",
                                        inspection_kind="AUTHENTICITY"),
            SO1,
        )
        validate_error(touching, ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT, 409)

        accepted = api_client.schedule_inspection(
            item["id"],
            schedule_inspection_payload(scheduled_for="2026-07-10T10:01:00Z",
                                        inspection_kind="AUTHENTICITY"),
            SO1,
        )
        third = validate_success(accepted, 201)
        assert third["status"] == "SCHEDULED"

        item_now = validate_success(api_client.get_equipment_item(item["id"], ORG), 200)
        assert item_now["status"] == "INSPECTION_DUE"
        inspections = validate_success(api_client.list_item_inspections(item["id"], ORG), 200)
        scheduled_ids = {i["id"] for i in inspections if i["status"] == "SCHEDULED"}
        assert scheduled_ids == {first["id"], third["id"]}

    def test_inspection_window_buffer_applies_before_existing_window(self, api):
        """PRD §3.4: "the new window, expanded by fifteen minutes on both sides,
        must not intersect any other `SCHEDULED` inspection window of the same
        equipment item, and for this buffered comparison touching counts as
        conflict."

        Design: Difficulty/resource_temporal_overlap/inspection_window_closed_buffer_touching_conflicts
        """
        event, unit, participant = _setup_event_unit_participant()
        item = declare_equipment(participant["id"], unit_id=unit["id"], item_type="FIREARM")
        first = schedule_inspection(item["id"], officer="so-1",
                                    scheduled_for="2026-07-10T09:00:00Z")

        # New window 08:00-08:45 buffered to [07:45, 09:00] touches the existing
        # [09:00, 09:45] window at 09:00 -> conflict under closed semantics.
        touching = api_client.schedule_inspection(
            item["id"],
            schedule_inspection_payload(scheduled_for="2026-07-10T08:00:00Z"),
            SO1,
        )
        validate_error(touching, ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT, 409)

        # 07:59-08:44 buffered to [07:44, 08:59] is disjoint from [09:00, 09:45].
        accepted = api_client.schedule_inspection(
            item["id"],
            schedule_inspection_payload(scheduled_for="2026-07-10T07:59:00Z"),
            SO1,
        )
        earlier = validate_success(accepted, 201)
        assert earlier["status"] == "SCHEDULED"
        inspections = validate_success(api_client.list_item_inspections(item["id"], ORG), 200)
        scheduled_ids = {i["id"] for i in inspections if i["status"] == "SCHEDULED"}
        assert scheduled_ids == {first["id"], earlier["id"]}


class TestEquipmentDeclarationValidation:
    def test_invalid_equipment_type_enum_rejected(self, api):
        """PRD §3.4: "A participant, their unit commander, or an organizer
        declares an item with `participant_id`, `item_type` (`FIREARM`, `EDGED`,
        `CANNON`, `CAMP_FLAME`, `TENTAGE`, or `OTHER`), and a free-text
        `description` of make, pattern, and material."
        PRD §3.7: "an empty `lines` array, an unknown line type, or a quantity
        below one is rejected with `ERR_VALIDATION`"

        Design: Corner/validations/invalid_equipment_type_enum_rejected
        """
        event, unit, participant = _setup_event_unit_participant()
        resp = api_client.create_equipment_item(
            create_equipment_item_payload(
                participant["id"], item_type="LASER",
                description="anachronistic ray gun",
            ),
            make_unit_commander_headers(unit["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestChildListings:
    def test_fk_reverse_reachability_subresource_lists(self, api):
        """PRD §4: "`/events/{id}/units` | List an event's units"
        PRD §4: "`/participants/{id}/equipment-items` | List a participant's
        equipment items"
        PRD §4: "`/equipment-items/{id}/inspections` | List an item's inspections"
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Design: Corner/endpoints/fk_reverse_reachability_subresource_lists
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        participant = create_participant(event["id"], unit_id=unit["id"],
                                         impression_class="CIVILIAN")
        item = declare_equipment(participant["id"], unit_id=unit["id"],
                                 item_type="TENTAGE", description="A-frame canvas tent")
        inspection = schedule_inspection(item["id"], officer="so-1",
                                         scheduled_for="2026-07-10T09:00:00Z",
                                         inspection_kind="AUTHENTICITY")

        units = validate_success(api_client.list_units(event["id"], ORG), 200)
        assert [u["id"] for u in units] == [unit["id"]]
        items = validate_success(
            api_client.list_participant_equipment(participant["id"], ORG), 200
        )
        assert [i["id"] for i in items] == [item["id"]]
        inspections = validate_success(
            api_client.list_item_inspections(item["id"], SO1), 200
        )
        assert [i["id"] for i in inspections] == [inspection["id"]]
