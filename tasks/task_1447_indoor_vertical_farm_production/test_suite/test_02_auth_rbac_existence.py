"""Request context, role authorization, and existence checks (PRD §2.1, §2.10, §2.11, §4)."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_crop_payload, create_recipe_payload, create_water_loop_payload,
    create_crop_with_active_recipe, create_loop_rack, create_growing_batch,
    schedule_cycle, start_cycle, set_clock, mark_harvest_ready,
    make_grower_headers, SEED_CLOCK,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]
SL = TEST_USERS["sanitation_lead_headers"]
LP = TEST_USERS["labor_planner_headers"]
CM = TEST_USERS["contracts_manager_headers"]
WK = TEST_USERS["worker_headers"]
BOGUS = "00000000-0000-4000-8000-000000000000"


class TestRequestContext:
    def test_missing_context_header_rejected(self, api):
        """PRD §2.1: "A request that arrives without either header, or whose
        `X-User-Role` value is not one of the declared roles, is rejected with
        `ERR_MISSING_CONTEXT_HEADER`."

        Design: Corner/validations/request_missing_auth_header_returns_400
        """
        resp = api.create_crop(create_crop_payload(crop_code="KALE-01"), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT_HEADER)

    def test_forbidden_role_precedes_existence(self, api):
        """PRD §2.10: "the server evaluates them in a fixed tier order and reports the
        first failure encountered" — tier 2 is "Role authorization ... (`ERR_FORBIDDEN_ROLE`)"
        and tier 4 is "Existence ... (`ERR_NOT_FOUND`)".

        Design: Corner/validations/forbidden_role_precedes_existence_and_state
        """
        validate_success(api.create_crop(create_crop_payload(crop_code="KALE-01"), FM),
                         expected_status=201)
        # Grower may not retire crops; the bogus id must not matter — role fires first.
        resp = api.retire_crop(BOGUS, GR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestExistence:
    def test_not_found_validated_path_left_to_right(self, api):
        """PRD §2.11: "Requests that target nested resources validate path identifiers
        in a strict left-to-right order, rejecting with `ERR_NOT_FOUND` at the first
        identifier that does not correspond to an existing resource."

        Design: Corner/validations/not_found_validated_path_left_to_right
        """
        resp_list = api.list_batch_allocations(BOGUS, FM)
        validate_error(resp_list, ApiErrorId.ERR_NOT_FOUND)
        resp_action = api.seed_batch(BOGUS, GR)
        validate_error(resp_action, ApiErrorId.ERR_NOT_FOUND)

    def test_body_fk_reference_not_found_returns_404(self, api):
        """PRD §2.11: "The same existence tier covers foreign keys supplied in request
        bodies — `crop_id`, ... — each of which must reference an existing resource."

        Design: Corner/validations/body_fk_reference_not_found_returns_404
        """
        resp = api.create_recipe(create_recipe_payload(BOGUS), GR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoleAuthorization:
    def test_grower_cannot_create_crop(self, api):
        """PRD §4: POST /farm/crops is authorized for FarmManager only. PRD §2.1: "an
        attempt to perform an action outside the caller's designated role is rejected
        with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/grower_cannot_create_crop
        """
        resp = api.create_crop(create_crop_payload(crop_code="KALE-01"), GR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        _, meta = validate_paginated(api.list_crops(FM))
        assert meta["total_count"] == 0

    def test_grower_cannot_safety_release(self, api):
        """PRD §4: POST /farm/batches/{id}/safety-release is authorized for
        QualityAssurance only. PRD §2.1: "an attempt to perform an action outside the
        caller's designated role is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/grower_cannot_safety_release
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        resp = api.safety_release_batch(batch["id"], {"decision": "RELEASED", "lab_ref": "LAB-R1"},
                                        make_grower_headers("grower-8"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_planner_cannot_record_sanitation_result(self, api):
        """PRD §4: POST /farm/sanitation-cycles/{id}/record-result is authorized for
        SanitationLead only. PRD §2.1: "an attempt to perform an action outside the
        caller's designated role is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/planner_cannot_record_sanitation_result
        """
        loop = validate_success(api.create_water_loop(create_water_loop_payload(loop_code="WL-A"), FM),
                                expected_status=201)
        set_clock("2026-08-08T00:00:00Z")
        cycle = schedule_cycle(loop["id"], "2026-08-08T01:00:00Z", "2026-08-08T03:00:00Z")
        start_cycle(cycle["id"], "2026-08-08T01:00:00Z")
        resp = api.record_sanitation_result(cycle["id"], {"result": "PASSED", "coliform_cfu": 0}, LP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_contracts_manager_cannot_harvest(self, api):
        """PRD §4: POST /farm/batches/{id}/harvest is authorized for Grower only.
        PRD §2.1: "an attempt to perform an action outside the caller's designated role
        is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/contracts_manager_cannot_harvest
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        batch = mark_harvest_ready(batch["id"])
        resp = api.harvest_batch(batch["id"],
                                 {"grade_a_lb": 10.0, "grade_b_lb": 0.0, "cull_lb": 0.0}, CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = validate_success(api.get_batch(batch["id"], FM))
        assert after["production_status"] == "HARVEST_READY"

    def test_worker_shared_read_allowed(self, api):
        """PRD §4: GET /farm/crops is authorized for "All roles", which includes Worker.

        Design: Corner/rbac/worker_shared_read_allowed
        """
        validate_success(api.create_crop(create_crop_payload(crop_code="KALE-01"), FM),
                         expected_status=201)
        data, meta = validate_paginated(api.list_crops(WK))
        assert meta["total_count"] == 1
        assert data[0]["crop_code"] == "KALE-01"

    def test_cost_summary_role_restriction(self, api):
        """PRD §4: GET /farm/batches/{id}/cost-summary is authorized for "FarmManager,
        Grower, ContractsManager" only; LaborPlanner is outside that set. PRD §2.1:
        "an attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/cost_summary_role_restriction
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        resp = api.get_batch_cost_summary(batch["id"], LP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
