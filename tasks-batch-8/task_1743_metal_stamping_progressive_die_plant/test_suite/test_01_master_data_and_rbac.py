"""Master data rules and role-based access control (PRD §2.1, §2.5, §3.1-§3.4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_kg,
    begin_ppap_review,
    create_audit,
    create_coil,
    create_customer,
    create_die,
    create_die_payload,
    create_order,
    create_part,
    create_part_payload,
    create_ppap_submission_payload,
    create_press,
    get_success_data,
    make_process_engineer_headers,
    make_quality_engineer_headers,
    validate_error,
    validate_success,
)


class TestMasterDataDefaults:
    def test_customer_creation_applies_active_default(
        self, api, plant_admin_headers
    ):
        """PRD §3.1: "The `active` flag defaults to true; an inactive customer cannot
        receive new production orders, a rule enforced at order release (§3.5)."

        Design: Corner/entities/customer_creation_applies_defaults
        """
        created = create_customer(name="Default Co", customer_code="DFLT")
        assert created["active"] is True, "omitted active flag must default to true"
        fetched = validate_success(api.get_customer(created["id"], plant_admin_headers))
        assert fetched["active"] is True

    def test_part_steel_content_reads_zero_before_any_approved_layout(
        self, api, process_engineer_headers
    ):
        """PRD §3.2: "The part's `steel_content_kg` — the kilograms of steel consumed
        per good part — is computed, not entered: it reads 0 until a strip layout for
        the part reaches `APPROVED`, and from then on it mirrors that layout's gross
        weight per part."

        Design: Corner/entities/part_computed_steel_content_zero_before_layout
        """
        customer = create_customer(name="Comp Co", customer_code="COMP")
        part = validate_success(
            api.create_part(
                create_part_payload(
                    customer["id"],
                    part_number="P-C1",
                    material_spec="DC04",
                    thickness_mm=0.8,
                    net_weight_kg=0.5,
                    base_piece_price_cents=900,
                    ppap_required_level=1,
                ),
                process_engineer_headers,
            ),
            expected_status=201,
        )
        assert part["steel_content_kg"] == 0, (
            f"steel_content_kg must read 0 before any layout is approved, got {part['steel_content_kg']}"
        )

    def test_coil_remaining_weight_initialized_from_received_weight(
        self, api, shipping_clerk_headers
    ):
        """PRD §3.4: "The system immediately sets `remaining_weight_kg` equal to
        `received_weight_kg`, and the coil enters its disposition lifecycle in
        `RECEIVED`."

        Design: Corner/entities/coil_remaining_weight_initialized_from_received
        """
        coil = create_coil(
            coil_number="C-INIT",
            heat_lot_number="HL-INIT",
            material_spec="DC04",
            thickness_mm=0.8,
            received_weight_kg=750.5,
        )
        fetched = validate_success(api.get_steel_coil(coil["id"], shipping_clerk_headers))
        assert_kg(fetched["remaining_weight_kg"], 750.5, "remaining_weight_kg")
        assert fetched["status"] == "RECEIVED"

    def test_get_missing_die_returns_not_found(self, api, plant_admin_headers):
        """PRD §2.5: "Every resource referenced in the path exists, validated left to
        right along the path (customer, part, die, press, coil, order, run, changeover
        event, audit, layout, submission, outside-processing order). The first missing
        reference produces `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/entity_not_found_returns_404
        """
        resp = api.get_die(NON_EXISTENT_UUID, plant_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_duplicate_die_code_rejected(self, api, toolroom_manager_headers):
        """PRD §3.3: "A die record carries a plant-wide unique `die_code`"
        PRD §2.5: "`customer_code`, `die_code`, `press_code`, and `coil_number` are each unique across the whole plant, and `part_number` is unique within each customer. Failure: `ERR_DUPLICATE` (409)."

        Design: Corner/entities/duplicate_die_code_rejected
        """
        create_die(
            die_code="D-DUP", die_type="PROGRESSIVE", total_stations=4,
            rated_tonnage=200, min_bed_width_mm=1500, repair_threshold_shots=1000,
        )
        resp = api.create_die(
            create_die_payload(
                die_code="D-DUP", die_type="TRANSFER", total_stations=2,
                rated_tonnage=150, min_bed_width_mm=1200, repair_threshold_shots=500,
            ),
            toolroom_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestInitialStates:
    def test_initial_states_on_creation(
        self, api, toolroom_manager_headers, production_planner_headers
    ):
        """PRD §3.3: "A die's `status` cycles through `AVAILABLE`, `ASSIGNED`,
        `IN_REPAIR`, and the terminal `RETIRED`, starting at `AVAILABLE`."
        PRD §3.5: "A new order is `OPEN`, with `quantity_produced_good` and
        `quantity_scrapped` both 0."
        PRD §3.9: "The audit's `result` starts `PENDING`, its `findings_count` starts
        0, and its `escalated_from_id` is null for a normally scheduled audit."

        Design: Corner/state_machines/initial_states_on_creation
        """
        die = create_die(die_code="D-INIT")
        assert die["status"] == "AVAILABLE"

        customer = create_customer(name="IS Co", customer_code="IS")
        part = create_part(customer["id"], part_number="P-IS")
        order = create_order(part["id"], quantity_ordered=10)
        assert order["status"] == "OPEN"
        assert order["quantity_produced_good"] == 0
        assert order["quantity_scrapped"] == 0

        press = create_press(press_code="PR-IS")
        audit = create_audit(press["id"], audit_tier=1)
        assert audit["result"] == "PENDING"
        assert audit["findings_count"] == 0
        assert audit["escalated_from_id"] is None

        fetched_die = validate_success(api.get_die(die["id"], toolroom_manager_headers))
        assert fetched_die["status"] == "AVAILABLE"
        fetched_order = validate_success(
            api.get_production_order(order["id"], production_planner_headers)
        )
        assert fetched_order["status"] == "OPEN"


class TestFieldShape:
    def test_press_creation_without_strokes_per_min_rejected(self, api, plant_admin_headers):
        """PRD §2.5: "16. **Field shape.** Required fields are present, enum values are among the declared sets, datetimes are valid ISO 8601, numeric fields are positive where declared, `planned_end` is later than `planned_start`, and `scheduled_end` is later than `scheduled_start`. Failure: `ERR_INVALID_REQUEST` (400)."
        PRD §3.3: "Presses are registered by a `PlantAdmin` with a unique `press_code`, a `tonnage`, a `bed_width_mm`, and a rated `strokes_per_min`; the press's `status` starts `IDLE` and moves among `IDLE`, `IN_SETUP`, and `RUNNING` as changeovers and runs come and go (§3.6, §3.7)."

        Design: Corner/validations/missing_required_field_rejected
        """
        resp = api.create_press(
            {"press_code": "PR-BAD", "tonnage": 500, "bed_width_mm": 2500},
            plant_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRbac:
    def test_press_operator_cannot_approve_coil(self, api, press_operator_headers):
        """PRD §2.1: "A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `PressOperator` works the floor: starts, completes, and aborts runs and records in-die reject events."
        PRD §2.1: "A `QualityEngineer` is the quality gatekeeper: approves, rejects, holds, and releases coils; reviews and dispositions PPAP submissions; and schedules and records layered audits."

        Design: Corner/rbac/operator_cannot_disposition_coil
        """
        coil = create_coil(coil_number="C-RBAC", heat_lot_number="HL-RBAC")
        resp = api.approve_steel_coil(coil["id"], press_operator_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_production_planner_cannot_record_audit(
        self, api, production_planner_headers
    ):
        """PRD §2.1: "A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `ProductionPlanner` owns production orders — creating, releasing, completing, closing, and cancelling them — and schedules production runs."
        PRD §2.1: "A `QualityEngineer` is the quality gatekeeper: approves, rejects, holds, and releases coils; reviews and dispositions PPAP submissions; and schedules and records layered audits."

        Design: Corner/rbac/planner_cannot_record_audit
        """
        press = create_press(press_code="PR-RBAC")
        audit = create_audit(press["id"], audit_tier=1)
        resp = api.record_layered_audit(
            audit["id"], {"result": "PASS", "findings_count": 0},
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_ppap_creator_cannot_approve_own_submission(self, api):
        """PRD §3.5: "Segregation of duties applies to both dispositions: the acting
        quality engineer must not be the same user who created the submission, or the
        action is rejected with `ERR_SEGREGATION_OF_DUTIES` (422)."

        Design: Corner/rbac/segregation_of_duties_ppap_creator_cannot_approve
        """
        shared_user = "user-shared-operator"
        customer = create_customer(name="SoD Co", customer_code="SOD")
        part = create_part(customer["id"], part_number="P-SOD")
        submission = get_success_data(
            api.create_ppap_submission(
                create_ppap_submission_payload(part["id"], level=1),
                make_process_engineer_headers(shared_user),
            )
        )
        begin_ppap_review(submission["id"])
        resp = api.approve_ppap_submission(
            submission["id"], make_quality_engineer_headers(shared_user)
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role outside
        this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        resp = api.list_customers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
