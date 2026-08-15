"""Authentication, role-based denials, DepartmentUser ownership, and the
authorization-before-existence priority pair."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_department,
    create_hall,
    create_recipe,
    create_recipe_payload,
    create_submitted_order,
    drive_period_to_in_service,
    file_inspection,
    get_department,
    get_order,
    list_report_corrective_actions,
    make_department_user_headers,
    menu_line,
    setup_hall_cycle_recipe,
    submit_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["dining_admin_headers"]
HALL_MANAGER = TEST_USERS["hall_manager_headers"]
KITCHEN_LEAD = TEST_USERS["kitchen_lead_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
INSPECTOR = TEST_USERS["health_inspector_headers"]
CONTRACT_MANAGER = TEST_USERS["contract_manager_headers"]


class TestAuthentication:
    def test_missing_or_unrecognized_role_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
        capacity in which they act. If either header is missing or blank, or if
        the role name is not one of the declared roles, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp_no_headers = api.list_dining_halls(headers={})
        validate_error(resp_no_headers, ApiErrorId.ERR_UNAUTHENTICATED)

        resp_bad_role = api.list_dining_halls(
            headers=build_user_headers("someone", "Wizard"))
        validate_error(resp_bad_role, ApiErrorId.ERR_UNAUTHENTICATED)

        resp_blank_id = api.list_dining_halls(
            headers={"X-User-ID": "", "X-User-Role": "DiningAdmin"})
        validate_error(resp_blank_id, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenials:
    def test_contract_manager_cannot_create_recipe(self, api):
        """PRD §2.1: "If the role is recognized but is not authorized for the
        target endpoint — or, for a `DepartmentUser`, the user attempts to act
        on another department's resources — the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §4 grants POST /recipes to KitchenLead
        only.

        Design: Corner/rbac/contract_manager_cannot_create_recipe
        """
        hall = create_hall(name="Hall R1")
        resp = api.create_recipe(
            create_recipe_payload(hall["id"], name="R", unit_cost_cents=500),
            CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        _data, meta = validate_paginated(api.list_recipes(KITCHEN_LEAD))
        assert meta["total_count"] == 0, "no recipe persisted"

    def test_health_inspector_cannot_resolve_corrective_action(self, api):
        """PRD §3.7: "A `HallManager` resolves an action from either `OPEN` or
        `OVERDUE` (both land in `RESOLVED`), provided the parent report is
        `SUBMITTED` or `ACKNOWLEDGED` — otherwise `ERR_INVALID_STATE` — with the
        resolver's `X-User-ID` stamped as `resolved_by_user_id`."
        PRD §2.1: "If the role is recognized but is not authorized for the
        target endpoint — or, for a `DepartmentUser`, the user attempts to act
        on another department's resources — the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/health_inspector_cannot_resolve_corrective
        """
        hall = create_hall(name="Hall R2")
        report = file_inspection(hall["id"], "2026-08-03",
                                 [{"code": "M1", "severity": "MAJOR"}],
                                 inspector_id="insp-5")
        submit_inspection(report["id"], inspector_id="insp-5")
        action = list_report_corrective_actions(report["id"])[0]

        resp = api.resolve_corrective_action(
            action["id"], TEST_USERS["health_inspector_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert validate_success(api.get_corrective_action(
            action["id"], INSPECTOR))["status"] == "OPEN"

    def test_dietitian_cannot_record_waste(self, api):
        """PRD §3.4: "A `KitchenLead` records a log against a period, supplying
        a `category` of `PRE_CONSUMER`, `POST_CONSUMER`, or `SPOILAGE`, a
        `disposition` of `LANDFILL`, `COMPOST`, or `DONATION`, and a `weight_kg`
        strictly greater than 0."
        PRD §2.1: "If the role is recognized but is not authorized for the
        target endpoint — or, for a `DepartmentUser`, the user attempts to act
        on another department's resources — the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/dietitian_cannot_record_waste
        """
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall R3",
                                                      unit_cost_cents=300)
        period = drive_period_to_in_service(hall["id"], cycle["id"],
                                            recipe["id"], "2026-09-04")
        resp = api.create_waste_log(
            period["id"],
            {"category": "PRE_CONSUMER", "disposition": "LANDFILL",
             "weight_kg": 1.0},
            DIETITIAN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        _data, meta = validate_paginated(api.list_waste_logs(HALL_MANAGER))
        assert meta["total_count"] == 0, "waste log count for the period stays 0"

    def test_department_user_cannot_approve_own_order(self, api):
        """PRD §3.8: "Approval (`SUBMITTED` → `APPROVED`) is a `HallManager`
        decision under three guards beyond the OCC check of §2.8 —
        `expected_department_version` must match the department's current
        `version`, else `ERR_STALE_VERSION`, and this staleness check runs after
        the from-state check."
        PRD §2.1: "If the role is recognized but is not authorized for the
        target endpoint — or, for a `DepartmentUser`, the user attempts to act
        on another department's resources — the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/department_user_cannot_approve_order
        """
        hall = create_hall(name="Hall R4", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Theater", code="THEA", budget=500000)
        order = create_submitted_order(
            hall["id"], dept["id"], "2026-09-18", "DINNER", 10,
            [menu_line(recipe["id"], 5)])

        resp = api.approve_catering_order(
            order["id"],
            {"expected_department_version": get_department(dept["id"])["version"]},
            make_department_user_headers(dept["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_order(order["id"])
        assert after["approval_status"] == "SUBMITTED"
        assert get_department(dept["id"])["reserved_cents"] == 50000, (
            "reservation intact after the forbidden approval attempt")

    def test_department_user_cannot_order_for_other_department(self, api):
        """PRD §2.1: "In particular, a `DepartmentUser` may create a catering
        order only when the request body's `department_id` equals `X-User-ID`,
        may read a department resource only for their own `id`, and may cancel
        only their own department's orders; any attempt to act for another
        department is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/department_user_cannot_order_for_other_department
        """
        hall = create_hall(name="Hall R5", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept1 = create_department(name="D1", code="D1", budget=500000)
        dept2 = create_department(name="D2", code="D2", budget=500000)

        resp = api.create_catering_order(
            {"dining_hall_id": hall["id"], "department_id": dept2["id"],
             "event_date": "2026-09-19", "time_slot": "LUNCH",
             "guaranteed_covers": 10,
             "menu_lines": [menu_line(recipe["id"], 5)]},
            make_department_user_headers(dept1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestAuthorizationPrecedesExistence:
    def test_wrong_role_on_nonexistent_cycle_is_forbidden(self, api):
        """PRD §2.7: "2. **Authorization and ownership** — the role appears in
        the endpoint's authorized set, and a `DepartmentUser` is acting on
        their own department; failures yield `ERR_FORBIDDEN`." Tier 2 precedes
        "3. **Existence** — path identifiers resolve left-to-right, then
        request-body foreign keys resolve in their declared input order;
        failures yield `ERR_NOT_FOUND`." PRD §4 grants POST
        /menu-cycles/{id}/publish to DiningAdmin only.

        Design: Difficulty/priority_pair_validation_conflict/wrong_role_beats_not_found
        """
        resp = api.publish_menu_cycle(NON_EXISTENT_UUID, HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403, (
            "authorization (tier 2) precedes existence (tier 3) — the server "
            "never reveals existence to a role that may not act")

    def test_authorized_role_on_nonexistent_cycle_is_not_found(self, api):
        """PRD §2.7: "3. **Existence** — path identifiers resolve left-to-right,
        then request-body foreign keys resolve in their declared input order;
        failures yield `ERR_NOT_FOUND`." PRD §4 grants POST
        /menu-cycles/{id}/publish to DiningAdmin only.

        Design: Difficulty/priority_pair_validation_conflict/wrong_role_beats_not_found
        """
        resp = api.publish_menu_cycle(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
