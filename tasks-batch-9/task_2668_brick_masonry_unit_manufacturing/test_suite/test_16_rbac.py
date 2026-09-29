"""
Who may do what: role-exclusive writes, shared writes with a plant scope on top,
the read surface that is open to everyone, and the two segregation-of-duties rules.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_PLANT_SCOPE_VIOLATION,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.test_users import (
    ALL_ROLE_HEADERS,
    ARCHITECT_REVIEWER,
    ARCHITECT_REVIEWER_ID,
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    LOGISTICS_COORDINATOR,
    PLANT_ADMIN,
    QUALITY_MANAGER,
    QUALITY_MANAGER_ID,
    SALES_REP,
    make_plant_operator_headers,
)


class TestPlantAdminExclusiveWrites:
    """
    Section 4 keeps the plant registry and its equipment in corporate hands, and
    owning a plant is not the same thing as being allowed to change it.
    """

    def test_no_other_role_can_register_a_plant_its_pits_its_kilns_or_idle_it(
        self, api, clock
    ):
        """
        Four roles are refused in turn, then the plant admin performs all three writes.

        Section 4 lists `PlantAdmin` alone on plant creation, clay-pit creation, kiln
        creation and the idle action, and section 2.3 maps a role outside the
        endpoint's list to ERR_ROLE_NOT_PERMITTED at HTTP 403. The operator refusal is
        the sharp one: its X-User-ID *is* this plant, and it still may not add a kiln.

        Design: Corner/rbac/plant_admin_exclusive_writes_are_refused_to_every_other_role
        """
        plant = fx.create_plant(api)
        operator = make_plant_operator_headers(plant["id"])

        validate_error(
            api.create_plant(F.plant_payload(), BODY_ENGINEER), ERR_ROLE_NOT_PERMITTED, 403
        )
        validate_error(
            api.create_clay_pit(plant["id"], F.clay_pit_payload(), SALES_REP),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.create_kiln(plant["id"], F.kiln_payload(), operator),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.idle_plant(plant["id"], QUALITY_MANAGER), ERR_ROLE_NOT_PERMITTED, 403
        )

        pit = validate_success(
            api.create_clay_pit(plant["id"], F.clay_pit_payload(), PLANT_ADMIN), 201
        )
        kiln = validate_success(
            api.create_kiln(plant["id"], F.kiln_payload(), PLANT_ADMIN), 201
        )
        assert pit["status"] == "OPEN"
        assert kiln["position_count"] == 5

        idled = validate_success(api.idle_plant(plant["id"], PLANT_ADMIN))
        assert idled["status"] == "IDLED"

        plants, meta = validate_paginated(api.list_plants(PLANT_ADMIN))
        assert meta["total_count"] == 1


class TestSharedWritesStillCarryAPlantScope:
    """
    Section 4 lets either corporate engineering or the plant operator register a
    kiln car, but the operator's identity pins it to one plant.
    """

    def test_the_operator_of_one_plant_cannot_add_a_car_to_another(self, api, clock):
        """
        Two roles may create a car; a foreign operator and an unlisted role may not.

        Section 2.3: a `PlantOperator` whose X-User-ID names a different plant than the
        one the request touches is rejected with ERR_PLANT_SCOPE_VIOLATION, while a
        role that is not on the endpoint's list at all gets ERR_ROLE_NOT_PERMITTED -
        both at HTTP 403. Section 3.1 creates every car IDLE.

        Design: Corner/rbac/kiln_car_creation_is_shared_but_the_operator_is_pinned_to_its_own_plant
        """
        home = fx.create_plant(api)
        away = fx.create_plant(api)

        by_admin = validate_success(
            api.create_kiln_car(home["id"], F.kiln_car_payload(), PLANT_ADMIN), 201
        )
        assert by_admin["status"] == "IDLE"
        by_operator = validate_success(
            api.create_kiln_car(
                home["id"],
                F.kiln_car_payload(capacity_green_units=8000),
                make_plant_operator_headers(home["id"]),
            ),
            201,
        )
        assert by_operator["id"] != by_admin["id"]

        validate_error(
            api.create_kiln_car(
                home["id"],
                F.kiln_car_payload(capacity_green_units=8000),
                make_plant_operator_headers(away["id"]),
            ),
            ERR_PLANT_SCOPE_VIOLATION,
            403,
        )
        validate_error(
            api.create_kiln_car(
                home["id"], F.kiln_car_payload(capacity_green_units=8000), BLEND_TECHNICIAN
            ),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

        home_cars, home_meta = validate_paginated(api.list_kiln_cars(home["id"], PLANT_ADMIN))
        assert home_meta["total_count"] == 2
        away_cars, away_meta = validate_paginated(api.list_kiln_cars(away["id"], PLANT_ADMIN))
        assert away_meta["total_count"] == 0


class TestOperatorScopeAcrossTheProductionChain:
    """
    The scope is resolved transitively - through a run's plant and a kiln run's
    kiln - and the role check answers before the scope check.
    """

    def test_every_production_endpoint_refuses_the_foreign_operator(self, api, clock):
        """
        Six endpoints reject the neighbouring plant's operator and accept the owner's.

        Section 2.3 orders the ladder role check first, plant scope second, so a
        PlantAdmin on a production run gets ERR_ROLE_NOT_PERMITTED even though it also
        has no operator scope. Sections 3.3 and 3.4 reach the owning plant through the
        run and through the kiln, so the scope check survives a URL that never names a
        plant, and section 3.4 stamps `graded_by_user_id` from the acting operator -
        which is a plant id.

        Design: Corner/rbac/operator_scope_is_enforced_on_every_production_endpoint_and_role_check_comes_first
        """
        env = fx.build_plant_with_assets(api, clock=None)
        home_id = env["plant"]["id"]
        away = fx.create_plant(api)
        owner = make_plant_operator_headers(home_id)
        intruder = make_plant_operator_headers(away["id"])
        run_payload = F.production_run_payload(
            home_id, env["formulation"]["id"], env["kiln_car"]["id"]
        )

        validate_error(
            api.create_production_run(run_payload, intruder), ERR_PLANT_SCOPE_VIOLATION, 403
        )
        validate_error(
            api.create_production_run(run_payload, PLANT_ADMIN), ERR_ROLE_NOT_PERMITTED, 403
        )
        run = validate_success(api.create_production_run(run_payload, owner), 201)

        validate_error(
            api.close_green(run["id"], F.close_green_payload(400), intruder),
            ERR_PLANT_SCOPE_VIOLATION,
            403,
        )
        closed = validate_success(
            api.close_green(run["id"], F.close_green_payload(400), owner)
        )
        assert closed["status"] == "SET"

        kiln_run_payload = F.kiln_run_payload(env["kiln"]["id"], env["formulation"]["id"])
        validate_error(
            api.create_kiln_run(kiln_run_payload, intruder), ERR_PLANT_SCOPE_VIOLATION, 403
        )
        kiln_run = validate_success(api.create_kiln_run(kiln_run_payload, owner), 201)

        load_payload = F.kiln_load_payload(run["id"], 3, kiln_run["version"])
        validate_error(
            api.load_kiln_run(kiln_run["id"], load_payload, intruder),
            ERR_PLANT_SCOPE_VIOLATION,
            403,
        )
        loaded = validate_success(api.load_kiln_run(kiln_run["id"], load_payload, owner))
        assert loaded["loaded_units"] == 9600

        validate_error(
            api.start_kiln_run(kiln_run["id"], intruder), ERR_PLANT_SCOPE_VIOLATION, 403
        )
        firing = validate_success(api.start_kiln_run(kiln_run["id"], owner))
        assert firing["status"] == "FIRING"

        grade_payload = F.grade_payload(1040, 3.0)
        validate_error(
            api.grade_kiln_run(kiln_run["id"], grade_payload, intruder),
            ERR_PLANT_SCOPE_VIOLATION,
            403,
        )
        graded = validate_success(api.grade_kiln_run(kiln_run["id"], grade_payload, owner))
        assert graded["status"] == "GRADED"
        assert graded["graded_by_user_id"] == home_id


class TestWorkflowRolesDoNotOverlap:
    """
    The nine commercial and quality actions each name one role, and the role check
    runs before any id in the path is resolved.
    """

    def test_nine_cross_role_attempts_are_all_role_refusals_not_not_founds(
        self, api, clock
    ):
        """
        Every path id below is dead, and every response is still a 403.

        Section 2.5 puts the role check "before the path parameters are resolved", so
        an unauthorised caller learns nothing about whether the row exists. Section 4
        pairs the steps deliberately: the technician who composes may not certify, the
        manager who certifies may not compose, the reviewer who approves may not
        submit, and the technician who submits may not approve.

        Design: Corner/rbac/workflow_roles_cannot_reach_into_each_other_s_exclusive_steps
        """
        attempts = [
            api.create_order(F.order_payload(requested_units=1000), BODY_ENGINEER),
            api.certify_blend(NON_EXISTENT_UUID, BLEND_TECHNICIAN),
            api.compose_blend(NON_EXISTENT_UUID, F.compose_payload(False), QUALITY_MANAGER),
            api.submit_panel(NON_EXISTENT_UUID, ARCHITECT_REVIEWER),
            api.approve_panel(NON_EXISTENT_UUID, BLEND_TECHNICIAN),
            api.package_order(NON_EXISTENT_UUID, F.package_payload(2, 2), SALES_REP),
            api.cancel_order(NON_EXISTENT_UUID, F.cancel_payload(), LOGISTICS_COORDINATOR),
            api.qualify_formulation(NON_EXISTENT_UUID, QUALITY_MANAGER),
            api.quarantine_fired_lot(NON_EXISTENT_UUID, F.quarantine_payload(), SALES_REP),
        ]
        for response in attempts:
            validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

        orders, meta = validate_paginated(api.list_orders(SALES_REP))
        assert meta["total_count"] == 0


class TestTheReadSurfaceIsOpenToEveryRole:
    """
    Section 4 lists all eight roles on the registry reads, and the plant scope
    covers writes only.
    """

    def test_all_eight_roles_read_the_same_plant_registry(self, api, clock):
        """
        Seven opaque identities and one plant operator all see the single plant.

        Section 4 puts every role on GET /plants, and section 2.3 applies
        ERR_PLANT_SCOPE_VIOLATION to an operator's writes rather than its reads, so an
        operator sees the whole registry rather than only its own plant.

        Design: Corner/rbac/every_role_can_read_the_plant_registry
        """
        plant = fx.create_plant(api)
        readers = dict(ALL_ROLE_HEADERS)
        readers["PlantOperator"] = make_plant_operator_headers(plant["id"])
        assert len(readers) == 8

        for role, headers in readers.items():
            rows, meta = validate_paginated(api.list_plants(headers))
            assert meta["total_count"] == 1, role
            assert meta["has_more"] is False, role
            assert rows[0]["id"] == plant["id"], role


class TestSegregationOfDuties:
    """
    Section 3.6 and section 3.7 both forbid one person from signing off on their own
    work, and the check reads the stored actor rather than the role.
    """

    def test_one_person_holding_both_roles_still_cannot_approve_or_certify_own_work(
        self, api, clock
    ):
        """
        dual-002 submitted the panel and dual-001 composed the blend; neither may sign off.

        Section 3.6: "the approver must not be the user who submitted the panel
        (ERR_SEGREGATION_OF_DUTIES)". Section 3.7 says the same of certification
        against the composer, and section 2.5 puts that check at a higher priority than
        the panel-approval check - which is also unsatisfied at that moment. Section 5
        maps the code to HTTP 403, and a refusal leaves no partial stamp.

        Design: Corner/rbac/the_same_person_may_not_sign_off_on_their_own_composition_or_their_own_panel
        """
        dual_one_tech = build_user_headers("dual-001", "BlendTechnician")
        dual_one_manager = build_user_headers("dual-001", "QualityManager")
        dual_two_tech = build_user_headers("dual-002", "BlendTechnician")
        dual_two_reviewer = build_user_headers("dual-002", "ArchitectReviewer")

        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        order = fx.build_assigned_order(api, requires_panel_approval=True)

        panel = fx.create_sample_panel(
            api, order["id"], env["formulation"]["id"], lot["id"], 52.00
        )
        submitted = validate_success(api.submit_panel(panel["id"], dual_two_tech))
        assert submitted["submitted_by_user_id"] == "dual-002"

        blend = fx.create_blend(api, order["id"], 9600)
        blend = fx.add_blend_component(api, blend, lot["id"], 9600, dual_one_tech)
        composed = validate_success(
            api.compose_blend(blend["id"], F.compose_payload(False), dual_one_tech)
        )
        assert composed["composed_by_user_id"] == "dual-001"
        assert composed["weighted_color_index"] == 52.18

        validate_error(
            api.approve_panel(panel["id"], dual_two_reviewer),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        validate_error(
            api.certify_blend(blend["id"], dual_one_manager),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        still_submitted = validate_success(api.get_sample_panel(panel["id"], ARCHITECT_REVIEWER))
        assert still_submitted["status"] == "SUBMITTED"
        assert still_submitted["submitted_by_user_id"] == "dual-002"
        mid_blend = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert mid_blend["status"] == "COMPOSED"
        assert mid_blend["certified_by_user_id"] is None

        approved = validate_success(api.approve_panel(panel["id"], ARCHITECT_REVIEWER))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == ARCHITECT_REVIEWER_ID

        certified = validate_success(api.certify_blend(blend["id"], QUALITY_MANAGER))
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == QUALITY_MANAGER_ID
        assert certified["panel_delta_e"] == 0.18
