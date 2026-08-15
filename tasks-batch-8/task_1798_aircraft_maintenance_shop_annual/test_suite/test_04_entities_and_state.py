"""Corner coverage: entity creation/defaults/constraints and work-order /
discrepancy state-machine corner claims."""
from test_helpers import (
    NON_EXISTENT_UUID,
    SM,
    add_checklist_item,
    create_aircraft,
    create_aircraft_payload,
    create_mechanic,
    create_owner,
    create_slot,
    create_work_order,
    get_success_data,
    make_mechanic_headers,
    reset_clock,
    setup_shop,
    setup_wo_with_failed_inspection,
    start_work_order,
    validate_error,
    validate_success,
    ApiErrorId,
)


class TestOwnerCreation:
    def test_default_approval_cap_applied(self, api):
        """PRD §3.1: "Registration may optionally set `approval_cap_cents`, the
        per-discrepancy pre-authorization ceiling; when omitted it defaults to
        50,000 cents (five hundred dollars), meaning any single repair finding
        estimated at or above that amount will require the owner's explicit
        decision rather than flowing through automatically."

        Design: Corner/entities/owner_creation_required_fields_and_default_cap
        """
        res = api.create_owner(
            {"full_name": "D Owner", "email": "d@x.com", "phone": "555"}, SM
        )
        owner = validate_success(res, 201)
        assert owner["approval_cap_cents"] == 50000, (
            f"omitted approval_cap_cents must default to 50000, got {owner['approval_cap_cents']}"
        )

    def test_default_status_and_version(self, api):
        """PRD §3.1: "An owner's `status` begins as `ACTIVE` and may later be
        `SUSPENDED`."
        PRD §2.4: "`version` (integer): a system-managed integer starting at
        creation and incremented by one on every mutation, including automatic
        state transitions and recomputations of derived fields performed by the
        server."

        Design: Corner/entities/owner_creation_required_fields_and_default_cap
        """
        owner = validate_success(
            api.create_owner(
                {"full_name": "D Owner", "email": "d2@x.com", "phone": "555"}, SM
            ),
            201,
        )
        assert owner["status"] == "ACTIVE"
        assert owner["version"] == 1

    def test_missing_email_rejected(self, api):
        """PRD §2.9: "a request whose payload is malformed — a missing required
        field, an invalid enum value, a part `quantity` below one, or a labor
        `duration_tenths` that is not a positive multiple of three — is
        rejected outright with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/owner_creation_missing_required_field_rejected
        """
        res = api.create_owner({"full_name": "No Email", "phone": "555"}, SM)
        validate_error(res, ApiErrorId.ERR_VALIDATION)
        assert res.status_code == 400


class TestAircraftConstraints:
    def test_duplicate_tail_number_rejected(self, api):
        """PRD §3.1: "Aircraft are registered against a registered owner via
        the `owner_id` field, along with the FAA registration `tail_number` —
        unique across the fleet — the `make_model`, and `total_time_hours`, the
        airframe total time expressed in tenths of an hour."

        Design: Corner/entities/aircraft_tail_number_uniqueness
        """
        owner = create_owner()
        create_aircraft(owner["id"], tail_number="N-DUP")
        res = api.create_aircraft(
            create_aircraft_payload(owner["id"], tail_number="N-DUP"), SM
        )
        assert res.status_code in (400, 409), (
            f"duplicate tail_number must be rejected 400/409, got {res.status_code}"
        )

    def test_get_missing_aircraft_not_found(self, api):
        """PRD §2.9: "Requests that target nested resources are validated left
        to right along the path: each path identifier must resolve to an
        existing row before the next is examined, and the first identifier that
        does not resolve fails the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/aircraft_not_found
        """
        res = api.get_aircraft(NON_EXISTENT_UUID, SM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        assert res.status_code == 404

    def test_posture_initialized_airworthy(self, api):
        """PRD §3.1: "A freshly registered aircraft has no open findings and
        starts `AIRWORTHY`."

        Design: Corner/entities/aircraft_computed_posture_field_readonly
        """
        owner = create_owner()
        aircraft = validate_success(
            api.create_aircraft(create_aircraft_payload(owner["id"]), SM), 201
        )
        assert aircraft["airworthiness_posture"] == "AIRWORTHY", (
            f"fresh aircraft must be AIRWORTHY, got {aircraft['airworthiness_posture']}"
        )


class TestChecklistItemShape:
    def test_checklist_item_carries_no_version(self, api):
        """PRD §2.4: "Three resources are deliberately lighter. ChecklistItem,
        LaborEntry, and LogbookEntry carry only `id` and `created_at`; both
        `updated_at` and `version` are absent from them."

        Design: Corner/entities/checklist_item_no_version_field
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        item = add_checklist_item(wo["id"], mechanic)
        assert "id" in item and "created_at" in item
        assert "version" not in item, "ChecklistItem must not carry version"
        assert "updated_at" not in item, "ChecklistItem must not carry updated_at"


class TestLaborEntryDurationIncrement:
    def test_non_multiple_of_three_rejected(self, api):
        """PRD §3.6: "The billable increment is pinned: `duration_tenths` must
        be positive and a whole multiple of three — three tenths of an hour,
        eighteen minutes, is the smallest billable unit — and anything else is
        rejected with `ERR_VALIDATION`."

        Design: Corner/entities/labor_entry_duration_tenths_positive_multiple_of_3
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        wo = start_work_order(wo, mechanic)
        res = api.create_labor_entry(
            wo["id"],
            {"mechanic_id": mechanic["id"], "duration_tenths": 4, "notes": "bad"},
            make_mechanic_headers(mechanic["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION)
        assert res.status_code == 400


class TestWorkOrderStateMachine:
    def test_draft_cannot_jump_to_returned_to_service(self, api):
        """PRD §2.9: "state permissibility fourth — an action attempted against
        an entity that is not in a state allowing that transition is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/workorder_invalid_transition_draft_to_rts
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        res = api.return_to_service(wo["id"], make_mechanic_headers(mechanic["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409

    def test_cancelled_work_order_is_terminal(self, api):
        """PRD §3.2: "`CANCELLED` and, later, `CLOSED` are the work order's
        terminal states."

        Design: Corner/state_machines/workorder_terminal_state_lockdown_cancelled
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        get_success_data(api.cancel_work_order(wo["id"], SM))
        res = api.schedule_work_order(wo["id"], SM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409

    def test_new_work_order_starts_draft(self, api):
        """PRD §3.2: "A new work order is `DRAFT`."
        PRD §2.4: "`version` (integer): a system-managed integer starting at
        creation and incremented by one on every mutation, including automatic
        state transitions and recomputations of derived fields performed by the
        server."

        Design: Corner/state_machines/workorder_initial_state_draft
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        assert wo["status"] == "DRAFT", f"new WO must be DRAFT, got {wo['status']}"
        assert wo["version"] == 1, f"new WO version must be 1, got {wo['version']}"


class TestSegregationOfDuties:
    def test_same_mechanic_cannot_verify_own_rectification(self, api):
        """PRD §3.6: "Segregation of duties is enforced: the verifying
        mechanic's `id` must differ from the rectifying mechanic's `id`, and a
        violation is rejected with `ERR_AIRWORTHINESS_BLOCKED` (HTTP 422); on
        an `ANNUAL`-scope work order the verifier must additionally hold an
        `IA` certificate."

        Design: Corner/state_machines/discrepancy_verify_requires_segregation_of_duties
        """
        owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection()
        mech_h = make_mechanic_headers(mechanic["id"])
        get_success_data(api.rectify_discrepancy(discrepancy["id"], mech_h))
        res = api.verify_discrepancy(
            discrepancy["id"],
            {"outcome": "PASS", "verified_by_mechanic_id": mechanic["id"]},
            mech_h,
        )
        validate_error(res, ApiErrorId.ERR_AIRWORTHINESS_BLOCKED)
        assert res.status_code == 422


class TestPostureInputSetFiltering:
    def test_pending_sb_does_not_ground(self, api):
        """PRD §3.4: "A new directive's `compliance_status` is
        `PENDING_EVALUATION`, which does not by itself affect the aircraft's
        posture."

        Design: Corner/calculations/posture_calculation_input_set_filtering
        """
        from test_helpers import create_directive_payload
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        get_success_data(
            api.create_directive(
                create_directive_payload(aircraft["id"], directive_type="SB",
                                         reference_number="SB-1", description="advisory"),
                SM,
            )
        )
        aircraft_after = get_success_data(api.get_aircraft(aircraft["id"], SM))
        assert aircraft_after["airworthiness_posture"] == "AIRWORTHY", (
            f"PENDING_EVALUATION SB must not affect posture, got {aircraft_after['airworthiness_posture']}"
        )

    def test_sb_type_cannot_ground_even_when_applicable_open(self, api):
        """PRD §3.4: "Evaluation is a posture-relevant event: an `AD` found
        `APPLICABLE_OPEN` grounds the aircraft immediately through the posture
        derivation described in §3.7, while service bulletins, being advisory,
        never ground."

        Design: Corner/calculations/posture_calculation_input_set_filtering
        """
        from test_helpers import create_directive_payload
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        directive = get_success_data(
            api.create_directive(
                create_directive_payload(aircraft["id"], directive_type="SB",
                                         reference_number="SB-2", description="advisory"),
                SM,
            )
        )
        get_success_data(
            api.evaluate_directive(
                directive["id"],
                {"compliance_status": "APPLICABLE_OPEN",
                 "evaluated_by_mechanic_id": mechanic["id"]},
                make_mechanic_headers(mechanic["id"]),
            )
        )
        aircraft_after = get_success_data(api.get_aircraft(aircraft["id"], SM))
        assert aircraft_after["airworthiness_posture"] == "AIRWORTHY", (
            f"SB can never ground, got {aircraft_after['airworthiness_posture']}"
        )
