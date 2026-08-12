"""Units and participants: vetting loop, suspension cascade, derived tallies,
computed fields, listing pagination, and referential checks."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    ApiErrorId,
    assert_participant,
    create_participant_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_event,
    create_participant,
    declare_equipment,
    get_event,
    open_registration,
    schedule_inspection,
    setup_approved_unit,
    setup_registration_open_event,
    setup_vetted_participant,
    submit_participant,
    vet_participant,
)
from test_helpers.test_users import make_unit_commander_headers

ORG = TEST_USERS["organizer_headers"]
AO = TEST_USERS["authenticity_officer_headers"]


class TestParticipantComputedFields:
    def test_participant_is_minor_computed_from_age(self, api):
        """PRD §3.3: "The system computes `is_minor`, true exactly when
        `age_at_event` is under 18."

        Design: Corner/entities/participant_is_minor_computed_from_age
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"], name="Civilians of the Valley",
                                   unit_type="CIVILIAN", portrayal_name="Townsfolk")
        young = create_participant(event["id"], unit_id=unit["id"], full_name="Kid Cole",
                                   age_at_event=15, impression_class="CIVILIAN")
        old = create_participant(event["id"], unit_id=unit["id"], full_name="Eli Elder",
                                 age_at_event=18, impression_class="CIVILIAN")
        assert young["is_minor"] is True, "15 < 18 makes a minor"
        assert old["is_minor"] is False, "18 is not under 18"

    def test_immediate_read_after_write_consistency(self, api):
        """PRD §3.3: "A new participant begins in `DRAFT`."
        PRD §3.3: "The system computes `is_minor`, true exactly when
        `age_at_event` is under 18."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        created = create_participant(event["id"], unit_id=unit["id"],
                                     age_at_event=15, impression_class="CIVILIAN")
        reread = validate_success(api_client.get_participant(created["id"], ORG), 200)
        assert_participant(reread)
        assert reread["status"] == "DRAFT", "the very next read shows the initial state"
        assert reread["is_minor"] is True, "computed field is visible immediately"
        assert reread["unit_id"] == unit["id"]


class TestParticipantListing:
    def test_participants_list_pagination_and_unit_filter(self, api):
        """PRD §3.3: "Participant listings support filtering by `unit_id`,
        `event_id`, `supervisor_participant_id`, and `status`, with `limit` and
        `offset` pagination."
        PRD §2.3: "The `meta` object of list responses carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/participants_list_pagination_and_unit_filter
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        for i in range(3):
            create_participant(event["id"], unit_id=unit["id"],
                               full_name=f"P {i}", age_at_event=30 + i,
                               impression_class="COMBATANT" if i < 2 else "CIVILIAN")
        page1 = api_client.list_participants(
            ORG, params={"unit_id": unit["id"], "limit": 2, "offset": 0}
        )
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2 = api_client.list_participants(
            ORG, params={"unit_id": unit["id"], "limit": 2, "offset": 2}
        )
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestVettingLoop:
    def test_participant_vetting_revision_loop(self, api):
        """PRD §3.3: "`APPROVE` moves to `VETTED`, `REQUEST_CHANGES` moves to
        `CHANGES_REQUESTED` (opening the resubmission loop), and `REJECT` moves
        to `REJECTED`, terminal."
        PRD §3.3: "Submission moves a participant `DRAFT → SUBMITTED`, and
        resubmission after requested changes moves `CHANGES_REQUESTED →
        SUBMITTED`"

        Design: Difficulty/non_linear_state_machine/participant_vetting_revision_loop
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        participant = create_participant(event["id"], unit_id=unit["id"])

        submitted = submit_participant(participant["id"], unit_id=unit["id"])
        assert submitted["status"] == "SUBMITTED"

        changes = vet_participant(participant["id"], "REQUEST_CHANGES",
                                  notes="replace modern buttons")
        assert changes["status"] == "CHANGES_REQUESTED", "vetting opens the revision loop"

        resubmitted = submit_participant(participant["id"], unit_id=unit["id"])
        assert resubmitted["status"] == "SUBMITTED", "resubmission cycles back to SUBMITTED"

        vetted = vet_participant(participant["id"], "APPROVE", notes="corrected")
        assert vetted["status"] == "VETTED"

    def test_participant_vetting_revision_loop_repeats(self, api):
        """PRD §3.3: "Submission moves a participant `DRAFT → SUBMITTED`, and
        resubmission after requested changes moves `CHANGES_REQUESTED →
        SUBMITTED`; both are performed by the unit's commander or the participant
        personally"

        Design: Difficulty/non_linear_state_machine/participant_vetting_revision_loop
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        participant = create_participant(event["id"], unit_id=unit["id"])
        submit_participant(participant["id"], unit_id=unit["id"])
        for round_no in range(2):
            changes = vet_participant(participant["id"], "REQUEST_CHANGES",
                                      notes=f"round {round_no}")
            assert changes["status"] == "CHANGES_REQUESTED"
            resubmitted = submit_participant(participant["id"], unit_id=unit["id"])
            assert resubmitted["status"] == "SUBMITTED", "the loop can repeat"
        vetted = vet_participant(participant["id"], "APPROVE")
        assert vetted["status"] == "VETTED", "the loop still terminates at VETTED"
        assert vetted["vet_notes"] == "ok"


class TestInvalidTransitions:
    def test_vet_participant_from_draft_rejected(self, api):
        """PRD §3.3: "Authenticity vetting belongs to the `AuthenticityOfficer`
        alone, acting on a `SUBMITTED` record with a `decision`"
        PRD §3.3: "any other from-state is rejected with
        `ERR_INVALID_PARTICIPANT_STATUS`"

        Design: Corner/state_machines/vet_participant_from_draft_rejected
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        participant = create_participant(event["id"], unit_id=unit["id"])
        assert participant["status"] == "DRAFT"
        resp = api_client.vet_participant(
            participant["id"], {"decision": "APPROVE"}, AO
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PARTICIPANT_STATUS, 409)
        reread = validate_success(api_client.get_participant(participant["id"], ORG), 200)
        assert reread["status"] == "DRAFT", "rejected vet leaves the participant in DRAFT"

    def test_vet_already_approved_unit_rejected(self, api):
        """PRD §3.3: "Vetting is valid from `SUBMITTED` or `SUSPENDED`, and
        suspension is valid only from `APPROVED`; any other from-state is
        rejected with `ERR_INVALID_UNIT_STATUS`."

        Design: Corner/state_machines/vet_already_approved_unit_rejected
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        assert unit["status"] == "APPROVED"
        resp = api_client.vet_unit(unit["id"], {"decision": "REJECT", "notes": "late doubt"}, ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_UNIT_STATUS, 409)
        reread = validate_success(api_client.get_unit(unit["id"], ORG), 200)
        assert reread["status"] == "APPROVED", "rejected vet leaves the unit APPROVED"


class TestUnitSuspensionCascade:
    def _setup_suspendable_unit(self):
        """REGISTRATION_OPEN event; APPROVED unit; VETTED combatant participant
        with a FIREARM item under a SCHEDULED inspection."""
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        participant = setup_vetted_participant(event["id"], unit_id=unit["id"])
        item = declare_equipment(participant["id"], unit_id=unit["id"], item_type="FIREARM")
        inspection = schedule_inspection(item["id"], officer="so-1",
                                         scheduled_for="2026-07-10T09:00:00Z")
        return event, unit, participant, item, inspection

    def test_unit_suspend_depth3_cascade(self, api):
        """PRD §3.3: "Suspending a unit is the system's depth-three cascade. The
        unit moves `APPROVED → SUSPENDED`, and then, hop by hop: every
        participant of the unit in `SUBMITTED`, `CHANGES_REQUESTED`, or `VETTED`
        status moves to `WITHDRAWN`; for each participant so withdrawn, every
        equipment item in `DECLARED`, `INSPECTION_DUE`, or `FAILED` moves to
        `WITHDRAWN`; and for each item so withdrawn, every `SCHEDULED` inspection
        moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/unit_suspend_depth3_cascade
        """
        event, unit, participant, item, inspection = self._setup_suspendable_unit()

        suspended = validate_success(
            api_client.suspend_unit(unit["id"], ORG, {"reason": "insurance paperwork lapse"}), 200
        )
        assert suspended["status"] == "SUSPENDED"

        reread_p = validate_success(api_client.get_participant(participant["id"], ORG), 200)
        assert reread_p["status"] == "WITHDRAWN", "hop 1: participant withdrawn"
        reread_e = validate_success(api_client.get_equipment_item(item["id"], ORG), 200)
        assert reread_e["status"] == "WITHDRAWN", "hop 2: equipment withdrawn"
        inspections = validate_success(api_client.list_item_inspections(item["id"], ORG), 200)
        assert inspections[0]["id"] == inspection["id"]
        assert inspections[0]["status"] == "CANCELLED", "hop 3: scheduled inspection cancelled"

    def test_unit_suspend_drops_combatant_tallies(self, api):
        """PRD §3.3: "Records in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`,
        `REJECTED`, or `WITHDRAWN` never count."
        PRD §3.3: "Both tallies are recomputed on vet approval, on check-in, on
        withdrawal, and on unit suspension."

        Design: Difficulty/transitive_cascade/unit_suspend_depth3_cascade
        """
        event, unit, participant, item, inspection = self._setup_suspendable_unit()
        before = get_event(event["id"])
        assert before["approved_combatant_count"] == 1

        api_client.suspend_unit(unit["id"], ORG, {"reason": "paperwork"})

        after_event = get_event(event["id"])
        assert after_event["approved_combatant_count"] == 0, (
            "withdrawn participants never count toward the event tally"
        )
        after_unit = validate_success(api_client.get_unit(unit["id"], ORG), 200)
        assert after_unit["approved_combatant_count"] == 0

    def test_unit_reinstated_from_suspended(self, api):
        """PRD §3.3: "A suspended unit may be reinstated by vetting it with
        `decision` `APPROVE` (`SUSPENDED → APPROVED`), but participants withdrawn
        by the suspension cascade are not restored — each must re-register or be
        re-vetted on its own merits."

        Design: Corner/state_machines/unit_reinstated_from_suspended
        """
        event, unit, participant, item, inspection = self._setup_suspendable_unit()
        api_client.suspend_unit(unit["id"], ORG, {"reason": "paperwork"})

        reinstated = validate_success(
            api_client.vet_unit(unit["id"], {"decision": "APPROVE", "notes": "reinstated"}, ORG), 200
        )
        assert reinstated["status"] == "APPROVED"
        reread_p = validate_success(api_client.get_participant(participant["id"], ORG), 200)
        assert reread_p["status"] == "WITHDRAWN", "the cascade is not reversed"


class TestParticipantReferentialChecks:
    def test_participant_body_fk_not_found(self, api):
        """PRD §3.3: "Referential checks follow §2.9: a non-null `unit_id` must
        resolve (`ERR_UNIT_NOT_FOUND`) and must belong to the same event as the
        participant's `event_id` (`ERR_UNIT_NOT_IN_EVENT`); a non-null
        `supervisor_participant_id` must resolve (`ERR_PARTICIPANT_NOT_FOUND`)
        and must not equal the participant's own id (`ERR_VALIDATION`)."

        Design: Corner/validations/participant_body_fk_not_found
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        # An organizer may register anyone, so no ownership check interferes
        # with the body-FK existence checks under test.
        bad_unit = api_client.create_participant(
            create_participant_payload(
                event["id"], unit_id=NON_EXISTENT_UUID, full_name="Ghost Unit Member",
                age_at_event=30, impression_class="COMBATANT",
            ),
            ORG,
        )
        validate_error(bad_unit, ApiErrorId.ERR_UNIT_NOT_FOUND, 404)

        bad_supervisor = api_client.create_participant(
            create_participant_payload(
                event["id"], unit_id=unit["id"], full_name="Ghost Supervised",
                age_at_event=12, impression_class="CIVILIAN",
                supervisor_participant_id=NON_EXISTENT_UUID,
            ),
            ORG,
        )
        validate_error(bad_supervisor, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND, 404)

    def test_participant_unit_event_mismatch_rejected(self, api):
        """PRD §3.3: "a non-null `unit_id` must resolve (`ERR_UNIT_NOT_FOUND`) and
        must belong to the same event as the participant's `event_id`
        (`ERR_UNIT_NOT_IN_EVENT`)"

        Design: Corner/validations/participant_unit_event_mismatch_rejected
        """
        event_one = create_event(name="Cedar Creek 2026")
        open_registration(event_one["id"])
        event_two = create_event(
            name="Gettysburg 2026", site_name="Gettysburg Field",
            event_starts_at="2026-08-07T08:00:00Z", event_ends_at="2026-08-09T18:00:00Z",
        )
        open_registration(event_two["id"])
        unit = setup_approved_unit(event_two["id"])
        # The commander's own unit (ownership passes) but a different event.
        resp = api_client.create_participant(
            create_participant_payload(
                event_one["id"], unit_id=unit["id"], full_name="Ada Adams",
                age_at_event=34, impression_class="COMBATANT",
            ),
            make_unit_commander_headers(unit["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_IN_EVENT, 422)
