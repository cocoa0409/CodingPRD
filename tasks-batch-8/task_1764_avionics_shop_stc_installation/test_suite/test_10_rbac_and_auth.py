"""Authentication, role-based access control, ownership, and duty segregation."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_aircraft,
    create_customer,
    create_panel_design,
    create_task,
    create_work_order_payload,
    get_aircraft,
    get_install_task,
    get_panel_design,
    get_work_order,
    make_customer_headers,
    make_inspector_headers,
    make_technician_headers,
    set_clock,
    setup_installation_work_order,
    setup_pending_approval,
    start_task,
    validate_error,
    validate_success,
    verify_task,
    work_task_to_completed,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestAuthentication:
    def test_missing_identity_headers_rejected(self, api):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID`, identifying the actor, and `X-User-Role`, naming the actor's operational capacity."
        PRD §2.1: "A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.11: "Authentication comes first — missing or unknown identity headers draw `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
        """
        response = api.get_customer(NON_EXISTENT_UUID, headers=None)
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


class TestSchemaBeforeExistence:
    def test_missing_required_field_beats_not_found(self, api):
        """PRD §2.11: "When several checks could reject the same request, the server does not choose among them freely: checks run in the fixed order below, and the request fails with the first violation found."
        PRD §2.11: "Third come request-body schema checks: required fields present, types valid, enum values in range, `quantity` at least 1, `unit_price_cents` greater than 0, `estimated_hours` greater than 0, `lead_time_days` zero or more, every time window ending after it begins, `removed_arm_in` present exactly when `removed_weight_lb` is greater than zero, and `stc_number` present exactly when `approval_path` is `STC`; the `stc_number` condition carries `ERR_STC_NUMBER_REQUIRED`, and the rest carry `ERR_VALIDATION`. Fourth is existence, per §2.10, with `ERR_NOT_FOUND`."

        Design: Corner/validations/install_task_create_missing_required_field_beats_not_found
        """
        response = api.create_install_task(
            {"work_order_id": NON_EXISTENT_UUID, "description": "x",
             "estimated_hours": 1.0},
            MANAGER)
        validate_error(response, ApiErrorId.ERR_VALIDATION)


class TestRoleEnforcement:
    def test_technician_cannot_verify_task(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the operation is rejected with `ERR_FORBIDDEN` (HTTP 403); the per-operation role assignments are enumerated in §4."
        PRD §4: "`/avionics/install-tasks/{installTaskId}/verify` | Inspector verifies completed work (may not be the performer) | Inspector"

        Design: Corner/rbac/technician_cannot_verify_task
        """
        bundle = setup_installation_work_order(customer_name="Rbac Rick",
                                               customer_email="r4@x.com",
                                               equipment_list=[])
        task = work_task_to_completed(bundle["work_order"]["id"],
                                      task_kind="INSTALLATION",
                                      estimated_hours=2.0, actual_hours=2.0,
                                      technician_id="tech-1")
        response = api.verify_task(task["id"], make_technician_headers("tech-9"))
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert get_install_task(task["id"])["status"] == "COMPLETED"

    def test_inspector_cannot_complete_task(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the operation is rejected with `ERR_FORBIDDEN` (HTTP 403); the per-operation role assignments are enumerated in §4."
        PRD §4: "`/avionics/install-tasks/{installTaskId}/complete` | Technician records actual hours and completes the task | Technician"

        Design: Corner/rbac/inspector_cannot_complete_task
        """
        bundle = setup_installation_work_order(customer_name="Rbac Rhea",
                                               customer_email="r5@x.com",
                                               equipment_list=[])
        task = create_task(bundle["work_order"]["id"], task_kind="INSTALLATION",
                           estimated_hours=2.0)
        start_task(task["id"], technician_id="tech-1")
        response = api.complete_task(task["id"], 2.0,
                                     make_inspector_headers("insp-1"))
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert get_install_task(task["id"])["status"] == "IN_PROGRESS"

    def test_customer_cannot_create_work_order(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the operation is rejected with `ERR_FORBIDDEN` (HTTP 403); the per-operation role assignments are enumerated in §4."
        PRD §4: "`/avionics/work-orders` | Open a work order (bay window reserved at creation) | ShopManager"

        Design: Corner/rbac/customer_cannot_create_work_order
        """
        customer = create_customer(name="Rbac Rita", contact_email="r6@x.com")
        aircraft = create_aircraft(customer["id"], tail_number="N952RD")
        response = api.create_work_order(
            create_work_order_payload(aircraft["id"], estimated_downtime_days=5,
                                      quoted_labor_hours=2,
                                      bay_window_end="2026-08-10T00:00:00Z"),
            make_customer_headers(customer["id"]))
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert get_aircraft(aircraft["id"])["status"] == "AVAILABLE", (
            "the forbidden creation persists no work order")

    def test_shop_manager_cannot_decide_design(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the operation is rejected with `ERR_FORBIDDEN` (HTTP 403); the per-operation role assignments are enumerated in §4."
        PRD §4: "`/avionics/panel-designs/{panelDesignId}/decide` | Customer decision on a submitted design | Customer"

        Design: Corner/rbac/shop_manager_cannot_decide_design
        """
        bundle = setup_pending_approval(customer_name="Rbac Ray",
                                        customer_email="r7@x.com",
                                        equipment_list=[])
        response = api.decide_panel_design(bundle["design"]["id"], "APPROVE",
                                           MANAGER)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert get_panel_design(bundle["design"]["id"])["status"] == "SUBMITTED"


class TestCustomerOwnership:
    def test_decide_without_ownership_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, by contrast, `X-User-ID` is the `id` of the acting `Customer` entity, and ownership checks on any resource compare the resource's foreign-key chain — work order to aircraft to owning customer — against `X-User-ID`."
        PRD §2.1: "Both are rejected with `ERR_FORBIDDEN` when the acting customer's `id` is not the owner of the aircraft the target work order references."

        Design: Corner/rbac/customer_decide_without_ownership_forbidden
        """
        set_clock()
        owner = create_customer(name="Owner One", contact_email="o1@x.com")
        other = create_customer(name="Other Two", contact_email="o2@x.com")
        aircraft = create_aircraft(owner["id"], tail_number="N954RF")
        work_order = validate_success(api.create_work_order(
            create_work_order_payload(aircraft["id"]), MANAGER), 201)
        design = create_panel_design(work_order, equipment_list=[])
        validate_success(api.submit_panel_design(design["id"], MANAGER))
        validate_success(api.submit_quote(work_order["id"], MANAGER))

        response = api.decide_panel_design(design["id"], "APPROVE",
                                           make_customer_headers(other["id"]))
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert get_panel_design(design["id"])["status"] == "SUBMITTED"
        assert get_work_order(work_order["id"])["status"] == "PENDING_APPROVAL"


class TestSegregationOfDuties:
    def test_inspector_cannot_verify_own_performed_work(self, api):
        """PRD §3.4: "Verification belongs to an `Inspector`, and never to the hands that did the work: the acting inspector's `X-User-ID` must differ from the task's `performed_by_user_id`, or the verification is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.4: "A successful verification moves the task from `COMPLETED` to `VERIFIED`, records `verified_by_user_id`, computes `billed_labor_cents`, and recomputes the parent's `total_billed_labor_cents` and `tasks_unverified_count`."

        Design: Corner/rbac/inspector_verify_own_performed_work_rejected
        """
        bundle = setup_installation_work_order(customer_name="Sod Sarah",
                                               customer_email="s4@x.com",
                                               equipment_list=[])
        task = work_task_to_completed(bundle["work_order"]["id"],
                                      task_kind="INSTALLATION",
                                      estimated_hours=2.0, actual_hours=2.0,
                                      technician_id="tech-1")
        assert task["performed_by_user_id"] == "tech-1"
        # The inspector's X-User-ID equals the recorded performer id.
        response = api.verify_task(task["id"], make_inspector_headers("tech-1"))
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_install_task(task["id"])["status"] == "COMPLETED"

        verified = verify_task(task["id"], inspector_id="insp-1")
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "insp-1"
