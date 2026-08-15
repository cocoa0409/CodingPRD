"""Hold-point inspections, inspector capacity/segregation, material verification
and the budget ceiling, and the conditional pump gate on the final leg."""
from test_helpers import (
    ApiErrorId,
    add_customer,
    add_design,
    add_installation,
    add_permit,
    add_science,
    add_site,
    advance,
    api_client,
    approve_design,
    create_inspection_payload,
    create_material_payload,
    decide_inspection_payload,
    get_design,
    make_inspector_headers,
    pass_inspection,
    schedule_inspection,
    setup_company_with_staff,
    setup_installation,
    submit_design,
    validate_error,
    validate_success,
    walk_installation_to_field_installed,
    walk_installation_to_rough_in,
    walk_installation_to_tank_set,
)


class TestInspectionDecisionRules:
    def test_inspection_decide_twice_rejected(self, api):
        """PRD section 3.6: "A pass moves `result` to `PASSED` and stamps
        `decided_period`".
        PRD section 2.9: "(5) admissibility of the requested state transition —
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/inspection_decide_twice_rejected
        """
        ctx = setup_installation(bedroom_count=3, inspector=True)
        insp = schedule_inspection(ctx, hold_point="TANK_SET", scheduled_period=0)
        first = validate_success(api_client.decide_inspection(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, insp["id"],
            decide_inspection_payload("PASS"), ctx.inspector))
        assert first["result"] == "PASSED"
        resp = api_client.decide_inspection(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, insp["id"],
            decide_inspection_payload("PASS"), ctx.inspector)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_segregation_beats_too_early_on_inspection_decide(self, api):
        """PRD section 3.6: "Decision belongs to the inspector of record: the
        acting inspector's id must equal the inspection's `inspector_id`, and the
        inspector's `full_name` must differ from the installation's `crew_lead` —
        either violation is `ERR_SEGREGATION_OF_DUTIES`."
        PRD section 2.9: "When a single request violates more than one rule, the
        applicable checks are evaluated in a fixed precedence order and only the
        first failure is reported." — with "(11) segregation of duties —
        `ERR_SEGREGATION_OF_DUTIES`" ordered before "(16) inspection scheduling
        maturity — `ERR_INSPECTION_TOO_EARLY`".

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_inspection_too_early
        """
        ctx = setup_installation(bedroom_count=3, inspector=True, second_inspector=True)
        insp = schedule_inspection(ctx, hold_point="TANK_SET", scheduled_period=5)
        # clock is still at 0: both the ownership rule and the timing rule are
        # violated; the segregation rule (priority 11) reports first.
        resp = api_client.decide_inspection(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, insp["id"],
            decide_inspection_payload("PASS"), make_inspector_headers(ctx.i2))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_correct_inspector_decide_before_schedule_reports_too_early(self, api):
        """PRD section 3.6: "The decision cannot be recorded before its time: the
        site's `current_period_index` must be at least the `scheduled_period`,
        else `ERR_INSPECTION_TOO_EARLY`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_inspection_too_early
        """
        ctx = setup_installation(bedroom_count=3, inspector=True)
        insp = schedule_inspection(ctx, hold_point="TANK_SET", scheduled_period=5)
        resp = api_client.decide_inspection(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, insp["id"],
            decide_inspection_payload("PASS"), ctx.inspector)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_TOO_EARLY)


class TestInspectorCapacity:
    def test_inspector_capacity_blocks_second_pending_same_period(self, api):
        """PRD section 3.6: "An inspector's calendar is a hard constraint: no
        inspector may hold two `PENDING` inspections at the same
        `scheduled_period`, so scheduling a second one while the first remains
        undecided fails with `ERR_SCHEDULING_CONFLICT`; deciding an inspection
        frees the slot."

        Design: Difficulty/resource_temporal_overlap/inspector_capacity_one_pending_per_period
        """
        ctx = setup_installation(bedroom_count=4, inspector=True, second_inspector=True)
        ib = add_installation(ctx, attr="ib")
        schedule_inspection(ctx, hold_point="TANK_SET", scheduled_period=3)  # i1 on i0
        resp = api_client.create_inspection(
            ctx.cid, ctx.cu, ctx.s, ib["id"],
            create_inspection_payload(ctx.i1, hold_point="TANK_SET", scheduled_period=3),
            ctx.manager)
        validate_error(resp, ApiErrorId.ERR_SCHEDULING_CONFLICT)

    def test_same_period_different_inspector_accepted(self, api):
        """PRD section 3.6: "An inspector's calendar is a hard constraint: no
        inspector may hold two `PENDING` inspections at the same
        `scheduled_period`, so scheduling a second one while the first remains
        undecided fails with `ERR_SCHEDULING_CONFLICT`; deciding an inspection
        frees the slot."

        Design: Difficulty/resource_temporal_overlap/inspector_capacity_one_pending_per_period
        """
        ctx = setup_installation(bedroom_count=4, inspector=True, second_inspector=True)
        ib = add_installation(ctx, attr="ib")
        schedule_inspection(ctx, hold_point="TANK_SET", scheduled_period=3)  # i1 on i0
        created = validate_success(api_client.create_inspection(
            ctx.cid, ctx.cu, ctx.s, ib["id"],
            create_inspection_payload(ctx.i2, hold_point="TANK_SET", scheduled_period=3),
            ctx.manager), 201)
        assert created["result"] == "PENDING", "capacity is per-inspector, not global"


class TestHoldPointGates:
    def test_error_hold_point_not_passed_and_materials_unverified_ordering(self, api):
        """PRD section 3.6: "The second leg, into `TANK_SET`, requires a passed
        hold-point inspection of kind `TANK_SET` for the installation, else
        `ERR_HOLD_POINT_NOT_PASSED`, and requires every delivered material of kind
        `TANK` to be verified, else `ERR_MATERIALS_UNVERIFIED`."
        PRD section 2.9: "(12) hold-point passage — `ERR_HOLD_POINT_NOT_PASSED`;
        (13) material verification completeness — `ERR_MATERIALS_UNVERIFIED`" —
        evaluated in a fixed precedence order with only the first failure
        reported.

        Design: Corner/validations/error_hold_point_not_passed_and_materials_unverified_ordering
        """
        ctx = setup_installation(bedroom_count=3, inspector=True)
        advance(ctx)  # ROUGH_IN_PROGRESS
        mv = validate_success(api_client.create_material_verification(
            ctx.cid, ctx.cu, ctx.s, ctx.i0,
            create_material_payload("TANK", 1, 150000), ctx.manager), 201)
        insp = schedule_inspection(ctx, hold_point="TANK_SET", scheduled_period=0)

        both_missing = api_client.advance_installation(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, ctx.manager)
        validate_error(both_missing, ApiErrorId.ERR_HOLD_POINT_NOT_PASSED)

        pass_inspection(ctx, ctx.i0, insp["id"])
        materials_open = api_client.advance_installation(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, ctx.manager)
        validate_error(materials_open, ApiErrorId.ERR_MATERIALS_UNVERIFIED)

        validate_success(api_client.verify_material(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, mv["id"], ctx.manager))
        advanced = validate_success(api_client.advance_installation(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, ctx.manager))
        assert advanced["status"] == "TANK_SET"

    def test_error_installation_not_ready_on_final_pass(self, api):
        """PRD section 3.6: "One more guard applies specifically to the `FINAL`
        hold point: passing it requires the installation to be sitting in
        `READY_FOR_FINAL`, else `ERR_INSTALLATION_NOT_READY`."

        Design: Corner/errors/error_installation_not_ready_on_final_pass
        """
        ctx = setup_installation(bedroom_count=3, inspector=True)
        walk_installation_to_rough_in(ctx)
        walk_installation_to_tank_set(ctx)
        walk_installation_to_field_installed(ctx)  # one leg short of READY_FOR_FINAL
        final_insp = schedule_inspection(ctx, hold_point="FINAL", scheduled_period=0)
        resp = api_client.decide_inspection(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, final_insp["id"],
            decide_inspection_payload("PASS"), ctx.inspector)
        validate_error(resp, ApiErrorId.ERR_INSTALLATION_NOT_READY)
        still_pending = validate_success(api_client.get_inspection(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, final_insp["id"], ctx.manager))
        assert still_pending["result"] == "PENDING"


class TestMaterialBudgetCeiling:
    def test_verify_to_exact_ceiling_accepted(self, api):
        """PRD section 3.6: "A verification whose resulting total would strictly
        exceed the ceiling is rejected with `ERR_MATERIAL_BUDGET_EXCEEDED`
        (HTTP 402); a total landing exactly on the ceiling is accepted."
        PRD section 3.6: "must not exceed the ceiling, which is the pinned
        design's `required_absorption_area_sqft` times 900 cents per square foot."

        Design: Difficulty/boundary_precision_check/material_budget_exact_equality_passes_one_cent_over_fails
        """
        ctx = setup_installation(bedroom_count=3)
        assert get_design(ctx, ctx.d0)["required_absorption_area_sqft"] == 563, (
            "ceiling is 563 * 900 = 506700 cents")
        mv1 = validate_success(api_client.create_material_verification(
            ctx.cid, ctx.cu, ctx.s, ctx.i0,
            create_material_payload("PIPE", 1, 300000), ctx.manager), 201)
        verified1 = validate_success(api_client.verify_material(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, mv1["id"], ctx.manager))
        assert verified1["verified"] is True
        mv2 = validate_success(api_client.create_material_verification(
            ctx.cid, ctx.cu, ctx.s, ctx.i0,
            create_material_payload("TANK", 1, 206700), ctx.manager), 201)
        verified2 = validate_success(api_client.verify_material(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, mv2["id"], ctx.manager))
        assert verified2["verified"] is True, (
            "running total exactly 506700 equals the ceiling — strict > passes it")

    def test_verify_one_cent_over_ceiling_rejected(self, api):
        """PRD section 3.6: "A verification whose resulting total would strictly
        exceed the ceiling is rejected with `ERR_MATERIAL_BUDGET_EXCEEDED`
        (HTTP 402); a total landing exactly on the ceiling is accepted."

        Design: Difficulty/boundary_precision_check/material_budget_exact_equality_passes_one_cent_over_fails
        """
        ctx = setup_installation(bedroom_count=3)
        for kind, cost in (("PIPE", 300000), ("TANK", 206700)):
            mv = validate_success(api_client.create_material_verification(
                ctx.cid, ctx.cu, ctx.s, ctx.i0,
                create_material_payload(kind, 1, cost), ctx.manager), 201)
            validate_success(api_client.verify_material(
                ctx.cid, ctx.cu, ctx.s, ctx.i0, mv["id"], ctx.manager))
        mv3 = validate_success(api_client.create_material_verification(
            ctx.cid, ctx.cu, ctx.s, ctx.i0,
            create_material_payload("AGGREGATE", 1, 1), ctx.manager), 201)
        resp = api_client.verify_material(ctx.cid, ctx.cu, ctx.s, ctx.i0, mv3["id"], ctx.manager)
        validate_error(resp, ApiErrorId.ERR_MATERIAL_BUDGET_EXCEEDED)


class TestConditionalPumpGate:
    def test_action_endpoint_conditional_pump_gate(self, api):
        """PRD section 3.6: "The fourth leg, into `READY_FOR_FINAL`, gates on the
        pump: when the pinned design's `system_type` is `PRESSURE_DISTRIBUTION` or
        `AEROBIC`, every `PUMP` delivery must be verified; designs of type
        `GRAVITY` or `MOUND` carry no pump requirement."

        Design: Corner/endpoints/action_endpoint_conditional_pump_gate
        """
        ctx = setup_company_with_staff(inspector=True)
        add_customer(ctx)
        ig = self._build_field_installed(ctx, "P-G", "1 Gravity Way", "GRAVITY", "sg")
        ip = self._build_field_installed(
            ctx, "P-P", "2 Pressure Way", "PRESSURE_DISTRIBUTION", "sp")

        gravity = validate_success(api_client.advance_installation(
            ctx.cid, ctx.cu, ctx.sg, ig, ctx.manager))
        assert gravity["status"] == "READY_FOR_FINAL", (
            "GRAVITY carries no pump requirement")

        # An UNVERIFIED PUMP delivery blocks the leg: "every PUMP delivery must
        # be verified" for PRESSURE_DISTRIBUTION / AEROBIC designs.
        mv = validate_success(api_client.create_material_verification(
            ctx.cid, ctx.cu, ctx.sp, ip,
            create_material_payload("PUMP", 1, 80000), ctx.manager), 201)
        blocked = api_client.advance_installation(
            ctx.cid, ctx.cu, ctx.sp, ip, ctx.manager)
        validate_error(blocked, ApiErrorId.ERR_MATERIALS_UNVERIFIED)

        validate_success(api_client.verify_material(
            ctx.cid, ctx.cu, ctx.sp, ip, mv["id"], ctx.manager))
        advanced = validate_success(api_client.advance_installation(
            ctx.cid, ctx.cu, ctx.sp, ip, ctx.manager))
        assert advanced["status"] == "READY_FOR_FINAL"

    @staticmethod
    def _build_field_installed(ctx, parcel_id, address, system_type, site_attr) -> str:
        add_site(ctx, parcel_id=parcel_id, address_line=address, attr=site_attr)
        sid = getattr(ctx, site_attr)
        add_science(ctx, site=sid, eval_attr=f"e_{site_attr}", perc_attr=f"pt_{site_attr}")
        design = add_design(ctx, bedroom_count=3, system_type=system_type, site=sid,
                            eval_attr=f"e_{site_attr}", perc_attr=f"pt_{site_attr}")
        submit_design(ctx, design["id"], site=sid)
        approve_design(ctx, design["id"], site=sid)
        permit = add_permit(ctx, design_id=design["id"], site=sid, attr=f"p_{site_attr}")
        installation = add_installation(ctx, permit_id=permit["id"], site=sid,
                                        attr=f"i_{site_attr}")
        iid = installation["id"]
        walk_installation_to_rough_in(ctx, iid, site=sid)
        walk_installation_to_tank_set(ctx, iid, site=sid)
        walk_installation_to_field_installed(ctx, iid, site=sid)
        return iid
