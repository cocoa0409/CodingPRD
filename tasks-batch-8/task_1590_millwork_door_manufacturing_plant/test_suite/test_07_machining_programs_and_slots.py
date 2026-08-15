"""Machining programs, moulder setup slots, overlap and changeover discipline."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, get_success_data,
    make_project, make_order, make_opening, configure_order, make_drawing,
    submit_drawing, approve_drawing, reject_drawing, make_program, make_machine,
    book_slot, complete_slot, cancel_slot, release_program, set_order_status,
    machine_opening, get_program, get_slot, get_opening, get_order, H,
)

PM_H = TEST_USERS["plant_manager_headers"]
EST_H = TEST_USERS["estimator_headers"]
PL_H = TEST_USERS["production_lead_headers"]
ANY_H = TEST_USERS["any_headers"]


def _approved_order_with_program(project, order_code, species, finish="STAIN",
                                 sheen="SATIN", minutes=60):
    """Order driven to APPROVED with a CREATED machining program."""
    order = make_order(project["id"], order_code=order_code, species=species,
                       profile_code="PR-2", finish_system=finish, sheen_target=sheen,
                       hardware_prep_mode="INSTALLER_PREP", fire_rating_required="NONE")
    make_opening(order["id"], opening_no="1", fire_rating="NONE")
    configure_order(order["id"])
    drawing = make_drawing(order["id"])
    submit_drawing(drawing["id"], user_id="est-1")
    approve_drawing(drawing["id"], user_id="arch-1")
    program = make_program(drawing["id"], order["id"], estimated_minutes=minutes)
    return order, drawing, program


class TestProgramRequiresApprovedDrawing:
    def test_program_create_rejected_for_submitted_drawing(self, api):
        """PRD §3.4: "With a drawing approved, a `ProductionLead` authors a
        **MachiningProgram** by naming the approved drawing (`drawing_id`), the
        order (`order_id`), and the `estimated_minutes` the run is expected to
        take. The referenced drawing must be `APPROVED`
        (`ERR_DRAWING_NOT_APPROVED`)".

        Design: Difficulty/cross_entity_state_dependency/program_create_requires_approved_drawing
        """
        project = make_project(name="Gate Proj", site_address="1 Draft Ln", contract_code="C-8001")
        order = make_order(project["id"], order_code="O-8001", species="MAPLE", profile_code="PR-7")
        make_opening(order["id"], opening_no="G1")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")

        # A program cannot be created for a merely SUBMITTED drawing.
        resp = api.create_machining_program(
            {"drawing_id": drawing["id"], "order_id": order["id"], "estimated_minutes": 60}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_APPROVED, 409)

        # The identical request succeeds once the drawing is APPROVED.
        approve_drawing(drawing["id"], user_id="arch-1")
        program = validate_success(api.create_machining_program(
            {"drawing_id": drawing["id"], "order_id": order["id"], "estimated_minutes": 60}, PL_H,
        ), 201)
        assert program["status"] == "CREATED"

    def test_program_create_rejected_for_rejected_drawing(self, api):
        """PRD §3.4: "With a drawing approved, a `ProductionLead` authors a
        **MachiningProgram**" and "The referenced drawing must be `APPROVED`
        (`ERR_DRAWING_NOT_APPROVED`)".

        Design: Difficulty/cross_entity_state_dependency/program_create_requires_approved_drawing
        """
        project = make_project(name="Gate Proj 2", site_address="2 Draft Ln", contract_code="C-8001B")
        order = make_order(project["id"], order_code="O-8001R", species="MAPLE", profile_code="PR-7")
        make_opening(order["id"], opening_no="G1")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")
        reject_drawing(drawing["id"], user_id="arch-1")

        resp = api.create_machining_program(
            {"drawing_id": drawing["id"], "order_id": order["id"], "estimated_minutes": 60}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_APPROVED, 409)


class TestSlotOverlapAndChangeover:
    def _three_program_setup(self):
        """Machine supporting OAK/MAPLE/PAINT_GRADE; OAK program with slot
        [10,12) BOOKED; MAPLE and PAINT_GRADE programs CREATED."""
        project = make_project(name="Slot Proj", site_address="5 Shop Ct", contract_code="C-9001")
        machine = make_machine(machine_code="M-X",
                               supported_species=["OAK", "MAPLE", "PAINT_GRADE"])
        ord_o, _, prog_o = _approved_order_with_program(project, "O-OAK", "OAK")
        book_slot(prog_o["id"], machine["id"], start_hour=10, end_hour=12)
        ord_m, _, prog_m = _approved_order_with_program(project, "O-MAP", "MAPLE")
        ord_p, _, prog_p = _approved_order_with_program(
            project, "O-PNT", "PAINT_GRADE", finish="PAINT", sheen="MATTE",
        )
        return machine, prog_m, prog_p

    def test_overlap_rejected_and_same_family_adjacency_allowed(self, api):
        """PRD §3.4: "The overlap rule is absolute: any overlap under the
        half-open definition of §2.8 is rejected with `ERR_MACHINE_SLOT_OVERLAP`,
        while mere adjacency is always allowed."

        Design: Difficulty/resource_temporal_overlap/moulder_slot_exclusive_overlap_and_changeover_buffer
        """
        machine, prog_m, _ = self._three_program_setup()

        # [11,13) overlaps the BOOKED [10,12) slot (11 < 12).
        resp = api.create_moulder_setup_slot(
            {"program_id": prog_m["id"], "machine_id": machine["id"],
             "start_hour": 11, "end_hour": 13}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_SLOT_OVERLAP, 409)

        # [12,14) touches [10,12): adjacency is not overlap; same STAIN family
        # neighbors never require a buffer.
        slot = validate_success(api.create_moulder_setup_slot(
            {"program_id": prog_m["id"], "machine_id": machine["id"],
             "start_hour": 12, "end_hour": 14}, PL_H,
        ), 201)
        assert slot["status"] == "BOOKED"

    def test_changeover_buffer_violation_and_exact_boundary(self, api):
        """PRD §3.4: "the gap between the windows — the shop-hours separating
        the earlier window's end from the later window's start, zero when they
        touch — must be at least two hours; a smaller cross-family gap is
        rejected with `ERR_CHANGEOVER_BUFFER_VIOLATION`, a gap of exactly two
        hours is permitted, and same-family neighbors never require a buffer."

        Design: Difficulty/resource_temporal_overlap/moulder_slot_exclusive_overlap_and_changeover_buffer
        """
        machine, prog_m, prog_p = self._three_program_setup()
        # Same-family STAIN slot [12,14) adjacent to the OAK slot.
        book_slot(prog_m["id"], machine["id"], start_hour=12, end_hour=14)

        # PAINT_GRADE slot [14,15) touches the STAIN slot: gap 0 < 2 across
        # families -> changeover violation.
        resp = api.create_moulder_setup_slot(
            {"program_id": prog_p["id"], "machine_id": machine["id"],
             "start_hour": 14, "end_hour": 15}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_BUFFER_VIOLATION, 409)

        # [16,18) sits exactly two shop-hours after the STAIN slot: permitted.
        slot = validate_success(api.create_moulder_setup_slot(
            {"program_id": prog_p["id"], "machine_id": machine["id"],
             "start_hour": 16, "end_hour": 18}, PL_H,
        ), 201)
        assert slot["status"] == "BOOKED"


class TestSlotBookingPriority:
    def test_species_safety_beats_overlap_constraint(self, api):
        """PRD §2.5: "Evaluation stops at the first rung that fails, and that
        rung's error is the one returned — a later rung never masks an earlier
        one." Fire/compliance safety (rung 7) precedes uniqueness/structural
        constraints (rung 8), so a booking that violates both reports the
        safety error. PRD §3.4: "booking onto a machine that cannot run the
        species fails with `ERR_MACHINE_SPECIES_UNSUPPORTED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/slot_booking_safety_beats_constraint
        """
        project = make_project(name="Safety Proj", site_address="6 Forge Way", contract_code="C-6002")
        ord_a, _, prog_a = _approved_order_with_program(project, "O-A", "OAK")
        machine = make_machine(machine_code="M-OAK", supported_species=["OAK"])
        book_slot(prog_a["id"], machine["id"], start_hour=10, end_hour=12)
        _, _, prog_b = _approved_order_with_program(project, "O-B", "MAPLE")

        # Violates BOTH species capability (MAPLE on an OAK-only machine) AND
        # overlap ([11,13) vs [10,12)); the safety error wins.
        resp = api.create_moulder_setup_slot(
            {"program_id": prog_b["id"], "machine_id": machine["id"],
             "start_hour": 11, "end_hour": 13}, PL_H,
        )
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_MACHINE_SPECIES_UNSUPPORTED", (
            f"safety must beat the overlap constraint, got {body['data']['error_id']}"
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_SPECIES_UNSUPPORTED, 403)

    def test_species_safety_fires_without_overlap(self, api):
        """PRD §3.4: "The machine's `supported_species` must contain the
        program's order species; booking onto a machine that cannot run the
        species fails with `ERR_MACHINE_SPECIES_UNSUPPORTED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/slot_booking_safety_beats_constraint
        """
        project = make_project(name="Safety Proj 2", site_address="7 Forge Way", contract_code="C-6002B")
        _, _, prog_b = _approved_order_with_program(project, "O-B2", "MAPLE")
        machine = make_machine(machine_code="M-OAK2", supported_species=["OAK"])

        # Species violation alone (no existing slots, hence no overlap).
        resp = api.create_moulder_setup_slot(
            {"program_id": prog_b["id"], "machine_id": machine["id"],
             "start_hour": 20, "end_hour": 22}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_SPECIES_UNSUPPORTED, 403)


class TestProductionGates:
    def test_machine_opening_requires_order_in_production(self, api):
        """PRD §3.4: "With at least one `RELEASED` program on the order's
        current approved drawing, a `ProductionLead` moves the order from
        `APPROVED` to `IN_PRODUCTION`; without one the attempt fails with
        `ERR_NO_RELEASED_PROGRAM`. Only then may openings be machined:
        advancing an opening's fabrication axis from `QUEUED` to `MACHINED`
        requires the order to be `IN_PRODUCTION` and otherwise fails with
        `ERR_ORDER_NOT_IN_PRODUCTION`." PRD §3.2: "Cancellation is the
        estimator's escape hatch, available from `DRAFT`, `CONFIGURED`,
        `SUBMITTED`, or `APPROVED`; from any later state the request fails with
        `ERR_ORDER_NOT_CANCELLABLE`."

        Design: Corner/state_machines/machine_opening_requires_order_in_production
        """
        project = make_project(name="P", contract_code="CS-5")
        order = make_order(project["id"], order_code="O-G", profile_code="PR-2")
        opening = make_opening(order["id"], opening_no="G1")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")
        approve_drawing(drawing["id"], user_id="arch-1")

        # IN_PRODUCTION gated by a RELEASED program.
        resp = api.set_order_status(order["id"], {"target_status": "IN_PRODUCTION"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_NO_RELEASED_PROGRAM, 409)

        # Machining an opening while the order is APPROVED fails.
        resp = api.set_opening_status(opening["id"], {"target_fab_status": "MACHINED"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_IN_PRODUCTION, 409)

        # Build and release the program, then production opens.
        program = make_program(drawing["id"], order["id"], estimated_minutes=30)
        machine = make_machine(machine_code="M-G", supported_species=["OAK"])
        slot = book_slot(program["id"], machine["id"], start_hour=8, end_hour=9)
        complete_slot(slot["id"])
        release_program(program["id"])
        set_order_status(order["id"], "IN_PRODUCTION")

        # The cancel path is closed once the order is IN_PRODUCTION.
        resp = api.set_order_status(order["id"], {"target_status": "CANCELLED"}, EST_H)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE, 409)

        machined = machine_opening(opening["id"])
        assert machined["fab_status"] == "MACHINED"


class TestSlotProgramLifecycle:
    def test_slot_cancel_revert_and_complete_promote_program(self, api):
        """PRD §3.4: "A booked slot is `BOOKED`, and the booking cascades the
        program from `CREATED` to `SETUP_BOOKED`." and "Completing a booked
        slot (a `ProductionLead` moving it from `BOOKED` to `COMPLETED`) proves
        the first article and cascades the program from `SETUP_BOOKED` to
        `PROVEN`. Explicitly cancelling a booked slot returns its program from
        `SETUP_BOOKED` to `CREATED`". PRD §3.3: "The change order is refused
        with `ERR_PRODUCTION_ALREADY_RELEASED` when a machining program in
        `RELEASED` status exists for the order's current approved drawing".

        Design: Corner/state_machines/slot_cancel_revert_and_complete_promote_program
        """
        project = make_project(name="P", contract_code="CS-6")
        order, drawing, program = _approved_order_with_program(project, "O-S", "OAK", minutes=30)
        machine = make_machine(machine_code="M-S", supported_species=["OAK"])

        # A CREATED program cannot jump straight to RELEASED.
        resp = api.set_machining_program_status(program["id"], {"target_status": "RELEASED"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_PROGRAM_STATUS_TRANSITION, 409)

        # Booking cascades the program to SETUP_BOOKED; a second booking fails.
        slot1 = book_slot(program["id"], machine["id"], start_hour=8, end_hour=9)
        assert get_program(program["id"])["status"] == "SETUP_BOOKED"
        resp = api.create_moulder_setup_slot(
            {"program_id": program["id"], "machine_id": machine["id"],
             "start_hour": 10, "end_hour": 11}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_AWAITING_SETUP, 409)

        # Explicit cancel reverts the program to CREATED, allowing rebooking.
        cancelled = cancel_slot(slot1["id"])
        assert cancelled["status"] == "CANCELLED"
        assert get_program(program["id"])["status"] == "CREATED"

        # Rebook and complete: the program is promoted to PROVEN.
        slot2 = book_slot(program["id"], machine["id"], start_hour=12, end_hour=13)
        complete_slot(slot2["id"])
        assert get_program(program["id"])["status"] == "PROVEN"

        # Terminal COMPLETED accepts no further transition.
        resp = api.set_moulder_setup_slot_status(slot2["id"], {"target_status": "COMPLETED"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_STATUS_TRANSITION, 409)

        # Release now succeeds, and change-order is then blocked.
        release_program(program["id"])
        resp = api.change_order(order["id"], EST_H)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_ALREADY_RELEASED, 409)

    def test_program_void_cascades_slot_cancel(self, api):
        """PRD §3.4: "A program may be voided from `CREATED`, `SETUP_BOOKED`,
        or `PROVEN` by a `ProductionLead` or by cascade, and voiding cancels
        its booked slots". PRD §2.10: "Terminal states accept no transitions".

        Design: Corner/state_machines/program_void_cascades_slot_cancel
        """
        project = make_project(name="P", contract_code="CS-11")
        order, drawing, program = _approved_order_with_program(project, "O-V11", "OAK", minutes=30)
        machine = make_machine(machine_code="M-V11", supported_species=["OAK"])
        slot = book_slot(program["id"], machine["id"], start_hour=8, end_hour=9)

        voided = validate_success(
            api.set_machining_program_status(program["id"], {"target_status": "VOID"}, PL_H), 200,
        )
        assert voided["status"] == "VOIDED"
        assert get_slot(slot["id"])["status"] == "CANCELLED", "voiding cancels the booked slot"

        # The cascade-cancelled slot is terminally locked.
        resp = api.set_moulder_setup_slot_status(slot["id"], {"target_status": "COMPLETED"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_STATUS_TRANSITION, 409)
