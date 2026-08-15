"""Order and project lifecycles: gates, cancellation cascades, change orders, dual axes."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, get_success_data,
    make_project, make_order, make_opening, configure_order, make_drawing,
    submit_drawing, approve_drawing, make_program, make_machine, book_slot,
    complete_slot, release_program, set_order_status, machine_opening,
    stage_opening, make_booth, make_batch, advance_batch, measure_batch,
    make_trip, assign, set_trip_status, accept_opening,
    get_order, get_opening, get_drawing, get_program, get_slot, H,
)

PM_H = TEST_USERS["plant_manager_headers"]
EST_H = TEST_USERS["estimator_headers"]
PL_H = TEST_USERS["production_lead_headers"]
SC_H = TEST_USERS["shipping_coordinator_headers"]
ANY_H = TEST_USERS["any_headers"]


class TestOrderBasics:
    def test_order_initial_state_draft(self, api):
        """PRD §3.2: "A new order is `DRAFT` with `config_locked` false."

        Design: Corner/state_machines/order_initial_state_draft
        """
        project = make_project(name="P", contract_code="CS-1")
        order = validate_success(api.create_order(
            {"project_id": project["id"], "order_code": "O-I", "species": "OAK",
             "profile_code": "PR-1", "finish_system": "STAIN", "sheen_target": "SATIN",
             "hardware_prep_mode": "INSTALLER_PREP", "fire_rating_required": "NONE"}, EST_H,
        ), 201)
        assert order["status"] == "DRAFT"
        assert order["config_locked"] is False

    def test_put_order_status_invalid_transition_returns_409(self, api):
        """PRD §2.10: "Terminal states accept no transitions, and no from-to
        pair other than the ones narrated in §3 is permitted." and "An attempt
        at an undeclared pair is rejected with the entity's own
        invalid-transition error: `ERR_INVALID_PROJECT_STATUS_TRANSITION`,
        `ERR_INVALID_ORDER_STATUS_TRANSITION`, `ERR_INVALID_OPENING_STATUS_TRANSITION`,
        `ERR_INVALID_DRAWING_STATUS_TRANSITION`, `ERR_INVALID_PROGRAM_STATUS_TRANSITION`,
        `ERR_INVALID_SLOT_STATUS_TRANSITION`, `ERR_INVALID_BATCH_STATUS_TRANSITION`,
        `ERR_INVALID_ROLL_STATUS_TRANSITION`, `ERR_INVALID_ALLOCATION_STATUS_TRANSITION`,
        `ERR_INVALID_TRIP_STATUS_TRANSITION`, or `ERR_INVALID_PUNCH_STATUS_TRANSITION`
        (all HTTP 409)."

        Design: Corner/state_machines/put_order_status_invalid_transition_returns_409
        """
        project = make_project(name="P", contract_code="CS-2")
        order = make_order(project["id"], order_code="O-T")

        # DRAFT -> SHIPPED is not a declared pair.
        resp = api.set_order_status(order["id"], {"target_status": "SHIPPED"}, SC_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATUS_TRANSITION, 409)
        assert get_order(order["id"])["status"] == "DRAFT"

    def test_cancelled_order_terminal_lockdown(self, api):
        """PRD §3.2: "`CLOSED` and `CANCELLED` are the order's terminal states,
        and any other order transition pair fails with
        `ERR_INVALID_ORDER_STATUS_TRANSITION`."

        Design: Corner/state_machines/cancelled_order_terminal_lockdown
        """
        project = make_project(name="P", contract_code="CS-3")
        order = make_order(project["id"], order_code="O-C")
        cancelled = set_order_status(order["id"], "CANCELLED")
        assert cancelled["status"] == "CANCELLED"

        resp = api.set_order_status(order["id"], {"target_status": "CONFIGURED"}, EST_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATUS_TRANSITION, 409)
        assert get_order(order["id"])["status"] == "CANCELLED"


class TestChangeOrderCascade:
    def _setup(self, contract_code):
        """Rated MAPLE order APPROVED; program with a BOOKED slot (SETUP_BOOKED)."""
        project = make_project(name="Cascade Proj", site_address="12 Mill Rd",
                               contract_code=contract_code)
        template = get_success_data(api_client.create_hardware_template(
            {"template_code": "T-C5", "manufacturer": "ACME", "fire_rated_compatible": True}, PM_H,
        ))
        order = make_order(project["id"], order_code="O-5001", species="MAPLE",
                           profile_code="PR-7", hardware_prep_mode="TEMPLATE_PREP",
                           fire_rating_required="MIN_20", hardware_template_id=template["id"])
        make_opening(order["id"], opening_no="1", leaf_count=1, fire_rating="MIN_20")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")
        approve_drawing(drawing["id"], user_id="arch-1")
        program = make_program(drawing["id"], order["id"], estimated_minutes=60)
        machine = make_machine(machine_code="M-C", supported_species=["MAPLE"])
        slot = book_slot(program["id"], machine["id"], start_hour=10, end_hour=12)
        return order, drawing, program, slot

    def test_change_order_supersedes_drawing_and_voids_program(self, api):
        """PRD §3.3: "Otherwise the cascade mirrors approval in reverse: the
        approved drawing moves to `SUPERSEDED`, its programs in `CREATED`,
        `SETUP_BOOKED`, or `PROVEN` move to `VOIDED`, their booked slots move
        to `CANCELLED`, `config_locked` returns to false, and the order's
        `version` increments."

        Design: Difficulty/transitive_cascade/change_order_supersede_cascade
        """
        order, drawing, program, slot = self._setup("C-5001")
        validate_success(api.change_order(order["id"], EST_H), 200)

        assert get_drawing(drawing["id"])["status"] == "SUPERSEDED"
        assert get_program(program["id"])["status"] == "VOIDED"

    def test_change_order_cancels_slots_and_unlocks_config(self, api):
        """PRD §3.3: "their booked slots move to `CANCELLED`, `config_locked`
        returns to false, and the order's `version` increments." PRD §3.3:
        "an `Estimator` issues a change order, reverting the order from
        `APPROVED` to `CONFIGURED`."

        Design: Difficulty/transitive_cascade/change_order_supersede_cascade
        """
        order, drawing, program, slot = self._setup("C-5001B")
        reverted = validate_success(api.change_order(order["id"], EST_H), 200)

        assert reverted["status"] == "CONFIGURED"
        assert reverted["config_locked"] is False
        assert get_slot(slot["id"])["status"] == "CANCELLED", (
            "the voided program's booked slot is cancelled"
        )


class TestOpeningParallelAxes:
    def _setup(self, contract_code):
        """Unrated PAINT_GRADE order; single opening STAGED and assigned to a
        trip (ship SCHEDULED)."""
        from test_helpers import setup_openings_staged
        ctx = setup_openings_staged(
            contract_code=contract_code, order_code="O-4002", species="PAINT_GRADE",
            profile_code="PR-1", finish_system="PAINT", sheen_target="MATTE",
            openings=({"opening_no": "P1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-05"},),
            machine_code="M-P", machine_species=["PAINT_GRADE"], booth_code="B-P",
            measured_gu=14.5, cure_start=8, cure_end=12, slot_start=6, slot_end=8,
            estimated_minutes=45,
        )
        trip = make_trip(ctx["project"]["id"], trip_code="T-P", truck_capacity_leaves=4,
                         departure_date="2026-10-01", site_arrival_date="2026-10-03")
        assign(trip["id"], ctx["openings"][0]["id"])
        return ctx, trip

    def test_ship_axis_advances_while_fab_axis_stays_staged(self, api):
        """PRD §2.10: "The Opening is the one entity with two parallel state
        dimensions on a single resource ... Both axes start together — an
        opening is created `QUEUED` and `UNSCHEDULED` — and both end together
        when an opening is cancelled, but in between they advance independently
        on different triggers." PRD §3.7: "Departure cascades every assigned
        opening's shipping axis from `SCHEDULED` to `SHIPPED`". "Arrival moves
        the trip from `DEPARTED` to `DELIVERED` and cascades the assigned
        openings from `SHIPPED` to `DELIVERED`."

        Design: Difficulty/non_linear_state_machine/opening_parallel_fab_ship_axes
        """
        ctx, trip = self._setup("C-4002")
        opening_id = ctx["openings"][0]["id"]

        set_trip_status(trip["id"], "DEPARTED")
        after_departure = get_opening(opening_id)
        assert after_departure["ship_status"] == "SHIPPED"
        assert after_departure["fab_status"] == "STAGED", (
            "the fab axis stays pinned while the ship axis advances"
        )

        delivered_trip = set_trip_status(trip["id"], "DELIVERED")
        assert delivered_trip["status"] == "DELIVERED"
        after_delivery = get_opening(opening_id)
        assert after_delivery["ship_status"] == "DELIVERED"
        assert after_delivery["fab_status"] == "STAGED"

    def test_fab_retrigger_rejected_while_shipped(self, api):
        """PRD §2.10: "Terminal states accept no transitions, and no from-to
        pair other than the ones narrated in §3 is permitted. An attempt at an
        undeclared pair is rejected with the entity's own invalid-transition
        error: `ERR_INVALID_PROJECT_STATUS_TRANSITION`,
        `ERR_INVALID_ORDER_STATUS_TRANSITION`, `ERR_INVALID_OPENING_STATUS_TRANSITION`,
        `ERR_INVALID_DRAWING_STATUS_TRANSITION`, `ERR_INVALID_PROGRAM_STATUS_TRANSITION`,
        `ERR_INVALID_SLOT_STATUS_TRANSITION`, `ERR_INVALID_BATCH_STATUS_TRANSITION`,
        `ERR_INVALID_ROLL_STATUS_TRANSITION`, `ERR_INVALID_ALLOCATION_STATUS_TRANSITION`,
        `ERR_INVALID_TRIP_STATUS_TRANSITION`, or `ERR_INVALID_PUNCH_STATUS_TRANSITION`
        (all HTTP 409)."

        Design: Difficulty/non_linear_state_machine/opening_parallel_fab_ship_axes
        """
        ctx, trip = self._setup("C-4002B")
        opening_id = ctx["openings"][0]["id"]
        set_trip_status(trip["id"], "DEPARTED")
        set_trip_status(trip["id"], "DELIVERED")

        # fab STAGED -> STAGED is an undeclared pair even while ship is DELIVERED.
        resp = api.set_opening_status(opening_id, {"target_fab_status": "STAGED"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_OPENING_STATUS_TRANSITION, 409)

        opening = get_opening(opening_id)
        assert opening["fab_status"] == "STAGED"
        assert opening["ship_status"] == "DELIVERED"
        assert get_success_data(api.get_delivery_trip(trip["id"], ANY_H))["status"] == "DELIVERED"


class TestOrderCancelCascade:
    def test_order_cancel_full_cascade(self, api):
        """PRD §3.2: "Cancelling an order is a deep cascade: every opening in a
        non-terminal state becomes `CANCELLED` on both axes, any opening
        assigned to a trip is detached (its `assigned_trip_id` cleared) and the
        affected trips recompute their committed leaves; shop drawings in
        `DRAFT` or `SUBMITTED` move to `VOID` while an approved drawing moves
        to `SUPERSEDED`; machining programs in `CREATED`, `SETUP_BOOKED`,
        `PROVEN`, or `RELEASED` move to `VOIDED` and their booked slots move to
        `CANCELLED`; and label allocations of the order's openings in `ISSUED`
        or `APPLIED` move to `VOIDED`, with their serials passing into each
        roll's spoiled count, never to return."

        Design: Corner/cross_cutting_complexity_layers/order_cancel_full_cascade
        """
        project = make_project(name="P", contract_code="CX-4")
        order = make_order(project["id"], order_code="O-X4", profile_code="PR-2")
        opening = make_opening(order["id"], opening_no="1", fire_rating="NONE")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")
        approve_drawing(drawing["id"], user_id="arch-1")
        program = make_program(drawing["id"], order["id"], estimated_minutes=30)
        machine = make_machine(machine_code="M-X4", supported_species=["OAK"])
        slot = book_slot(program["id"], machine["id"], start_hour=8, end_hour=9)
        complete_slot(slot["id"])
        release_program(program["id"])

        cancelled = set_order_status(order["id"], "CANCELLED")
        assert cancelled["status"] == "CANCELLED"

        opening_after = get_opening(opening["id"])
        assert opening_after["fab_status"] == "CANCELLED"
        assert opening_after["ship_status"] == "CANCELLED"
        assert get_drawing(drawing["id"])["status"] == "SUPERSEDED"
        assert get_program(program["id"])["status"] == "VOIDED", (
            "RELEASED program voided via cancel cascade"
        )
        # The slot already reached its terminal COMPLETED state: untouched.
        assert get_slot(slot["id"])["status"] == "COMPLETED"


class TestFullLifecycle:
    def test_full_order_lifecycle_happy_path(self, api):
        """PRD §3.2: "Configuration moves an order from `DRAFT` to `CONFIGURED`
        (an `Estimator` action) and runs four gates. First, at least one
        opening whose fabrication state is anything other than `CANCELLED` must
        exist, failing with `ERR_NO_OPENINGS`." PRD §3.4: "When every
        non-cancelled opening of the order has reached `MACHINED`, `FINISHED`,
        `LABELED`, or `STAGED`, a `ProductionLead` may move the order from
        `IN_PRODUCTION` to `FINISHING`; any straggler fails the transition with
        `ERR_OPENINGS_NOT_MACHINED`." PRD §3.6: "Once every non-cancelled
        opening of the order sits in `STAGED`, a `ProductionLead` moves the
        order from `FINISHING` to `READY_TO_SHIP`; any opening short of staging
        fails the transition with `ERR_OPENINGS_NOT_STAGED`." PRD §3.7: "any
        opening short of that set fails the transition with
        `ERR_OPENINGS_NOT_SHIPPED`." PRD §3.8: "A `PlantManager` moves a
        `SHIPPED` order to `CLOSED` when every non-cancelled opening sits at
        `ACCEPTED` (`ERR_OPENINGS_NOT_ACCEPTED`)". PRD §3.1: "if any order is
        still mid-lifecycle the attempt fails with `ERR_ORDERS_NOT_TERMINAL`."
        and "attempting either against a project that is no longer `OPEN`
        fails with `ERR_PROJECT_NOT_OPEN`."

        Design: Corner/endpoints/full_order_lifecycle_happy_path
        """
        project = make_project(name="Lifecycle Proj", site_address="9 Full Way",
                               contract_code="CE-4")
        # An empty order cannot configure.
        empty = make_order(project["id"], order_code="O-EMPTY")
        resp = api.set_order_status(empty["id"], {"target_status": "CONFIGURED"}, EST_H)
        validate_error(resp, ApiErrorId.ERR_NO_OPENINGS, 409)

        order = make_order(project["id"], order_code="O-M", species="PAINT_GRADE",
                           profile_code="PR-1", finish_system="PAINT", sheen_target="MATTE")
        op_a = make_opening(order["id"], opening_no="A", leaf_count=1,
                            required_on_site_date="2026-10-05")
        op_b = make_opening(order["id"], opening_no="B", leaf_count=1,
                            required_on_site_date="2026-10-05")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")
        approve_drawing(drawing["id"], user_id="arch-1")
        program = make_program(drawing["id"], order["id"], estimated_minutes=45)
        machine = make_machine(machine_code="M-E4", supported_species=["PAINT_GRADE"])
        slot = book_slot(program["id"], machine["id"], start_hour=6, end_hour=8)
        complete_slot(slot["id"])
        release_program(program["id"])
        set_order_status(order["id"], "IN_PRODUCTION")

        # FINISHING gated on every opening being machined.
        machine_opening(op_a["id"])
        resp = api.set_order_status(order["id"], {"target_status": "FINISHING"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_OPENINGS_NOT_MACHINED, 409)
        machine_opening(op_b["id"])
        set_order_status(order["id"], "FINISHING")

        booth = make_booth(booth_code="B-E4")
        batch = make_batch(order["id"], booth["id"], cure_start_hour=8, cure_end_hour=12)
        advance_batch(batch["id"], "SPRAYED")
        advance_batch(batch["id"], "CURED")
        measure_batch(batch["id"], 15)

        # READY_TO_SHIP gated on every opening staged.
        stage_opening(op_a["id"])
        resp = api.set_order_status(order["id"], {"target_status": "READY_TO_SHIP"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_OPENINGS_NOT_STAGED, 409)
        stage_opening(op_b["id"])
        set_order_status(order["id"], "READY_TO_SHIP")

        # SHIPPED gated on openings moving along the ship axis.
        resp = api.set_order_status(order["id"], {"target_status": "SHIPPED"}, SC_H)
        validate_error(resp, ApiErrorId.ERR_OPENINGS_NOT_SHIPPED, 409)

        trip = make_trip(project["id"], trip_code="T-E4", truck_capacity_leaves=4,
                         departure_date="2026-10-02", site_arrival_date="2026-10-04")
        assign(trip["id"], op_a["id"])
        assign(trip["id"], op_b["id"])
        set_trip_status(trip["id"], "DEPARTED")
        shipped = set_order_status(order["id"], "SHIPPED")
        assert shipped["status"] == "SHIPPED"
        set_trip_status(trip["id"], "DELIVERED")

        # CLOSED gated on every opening accepted.
        resp = api.set_order_status(order["id"], {"target_status": "CLOSED"}, PM_H)
        validate_error(resp, ApiErrorId.ERR_OPENINGS_NOT_ACCEPTED, 409)
        accept_opening(op_a["id"], user_id="qa-1")
        accept_opening(op_b["id"], user_id="qa-1")
        closed = set_order_status(order["id"], "CLOSED")
        assert closed["status"] == "CLOSED"

        closed_trip = set_trip_status(trip["id"], "CLOSED")
        assert closed_trip["status"] == "CLOSED"

        # Project completion gated on every order terminal.
        resp = api.set_project_status(project["id"], {"target_status": "COMPLETED"}, PM_H)
        validate_error(resp, ApiErrorId.ERR_ORDERS_NOT_TERMINAL, 409)
        set_order_status(empty["id"], "CANCELLED")
        completed = validate_success(
            api.set_project_status(project["id"], {"target_status": "COMPLETED"}, PM_H), 200,
        )
        assert completed["status"] == "COMPLETED"

        # Order creation is closed once the project is no longer OPEN.
        resp = api.create_order(
            {"project_id": project["id"], "order_code": "O-LATE", "species": "OAK",
             "profile_code": "PR-1", "finish_system": "STAIN", "sheen_target": "SATIN",
             "hardware_prep_mode": "INSTALLER_PREP", "fire_rating_required": "NONE"}, EST_H,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_OPEN, 409)

        archived = validate_success(
            api.set_project_status(project["id"], {"target_status": "ARCHIVED"}, PM_H), 200,
        )
        assert archived["status"] == "ARCHIVED"
        resp = api.set_project_status(project["id"], {"target_status": "COMPLETED"}, PM_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_PROJECT_STATUS_TRANSITION, 409)
