"""RBAC exclusive operations and segregation-of-duties bans (PRD §2.1, §2.9)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, get_success_data,
    make_project, make_order, make_opening, configure_order, make_drawing,
    submit_drawing, approve_drawing, make_program, make_machine, book_slot,
    complete_slot, release_program, set_order_status, make_roll, get_roll,
    get_drawing, get_opening, issue_labels, apply_labels,
    setup_openings_finished, H,
)

PM_H = TEST_USERS["plant_manager_headers"]
EST_H = TEST_USERS["estimator_headers"]
ANY_H = TEST_USERS["any_headers"]


class TestExclusiveOperations:
    def test_estimator_cannot_approve_drawing(self, api):
        """PRD §2.1: "A request whose role is not permitted for the attempted
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "An `Architect` is the external design professional: this
        role approves or rejects submittals".

        Design: Corner/rbac/estimator_cannot_approve_drawing
        """
        ctx = make_project(name="P", contract_code="CB-1")
        order = make_order(ctx["id"], order_code="O-B1")
        make_opening(order["id"], opening_no="1")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")

        resp = api.set_shop_drawing_status(
            drawing["id"], {"target_status": "APPROVED"}, H("Estimator", "est-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
        assert get_drawing(drawing["id"])["status"] == "SUBMITTED"

    def test_production_lead_cannot_issue_labels(self, api):
        """PRD §2.1: "A `LabelAuthority` is the agency-authorized label control
        issuer: this role issues and voids serialized fire labels and retires
        label rolls." and "A request whose role is not permitted for the
        attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/production_lead_cannot_issue_labels
        """
        project = make_project(name="P", contract_code="CB-2")
        template = get_success_data(api.create_hardware_template(
            {"template_code": "T-B2", "manufacturer": "ACME", "fire_rated_compatible": True}, PM_H,
        ))
        order = make_order(project["id"], order_code="O-B2", species="MAPLE",
                           profile_code="PR-7", hardware_prep_mode="TEMPLATE_PREP",
                           fire_rating_required="MIN_20", hardware_template_id=template["id"])
        opening = make_opening(order["id"], opening_no="1", fire_rating="MIN_20")
        roll = make_roll(label_series="UL_20MIN", serial_capacity=2)

        resp = api.create_label_allocation(
            {"opening_id": opening["id"], "roll_id": roll["id"],
             "expected_roll_version": roll["version"]},
            H("ProductionLead", "pl-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_qa_inspector_cannot_retire_roll(self, api):
        """PRD §2.1: "A `LabelAuthority` is the agency-authorized label control
        issuer: this role issues and voids serialized fire labels and retires
        label rolls." and "A request whose role is not permitted for the
        attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/qa_inspector_cannot_retire_roll
        """
        roll = make_roll(label_series="UL_90MIN", serial_capacity=5)
        resp = api.set_fire_label_roll_status(
            roll["id"], {"target_status": "RETIRED"}, H("QAInspector", "qa-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
        assert get_roll(roll["id"])["status"] == "ACTIVE"

    def test_shipping_coordinator_cannot_machine_opening(self, api):
        """PRD §2.1: "A `ProductionLead` runs the shop floor: machining
        programs, moulder setup slots, finishing batches, label application,
        and rework execution." and "A request whose role is not permitted for
        the attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/shipping_coordinator_cannot_machine_opening
        """
        project = make_project(name="P", contract_code="CB-4")
        order = make_order(project["id"], order_code="O-B4")
        opening = make_opening(order["id"], opening_no="1")

        resp = api.set_opening_status(
            opening["id"], {"target_fab_status": "MACHINED"},
            H("ShippingCoordinator", "sc-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
        assert get_opening(opening["id"])["fab_status"] == "QUEUED"

    def test_estimator_cannot_drive_production_status(self, api):
        """PRD §2.1: "Authorization on status-transition endpoints is per
        target state, not merely per endpoint: the only role accepted is the
        actor declared on the matching state-machine transition for the
        requested target."

        Design: Corner/rbac/estimator_cannot_drive_production_status
        """
        project = make_project(name="P", contract_code="CB-5")
        order = make_order(project["id"], order_code="O-B5")
        make_opening(order["id"], opening_no="1")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")
        approve_drawing(drawing["id"], user_id="arch-1")
        program = make_program(drawing["id"], order["id"], estimated_minutes=30)
        machine = make_machine(machine_code="M-B5", supported_species=["OAK"])
        slot = book_slot(program["id"], machine["id"], start_hour=8, end_hour=9)
        complete_slot(slot["id"])
        release_program(program["id"])

        resp = api.set_order_status(order["id"], {"target_status": "IN_PRODUCTION"}, EST_H)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
        assert get_success_data(api.get_order(order["id"], ANY_H))["status"] == "APPROVED"


class TestSegregationOfDuties:
    def test_self_approval_forbidden(self, api):
        """PRD §2.9: "The architect approving a shop drawing must not be the
        user who submitted it." PRD §3.3: "the approver's `X-User-ID` must
        differ from `submitted_by`, and a self-approval attempt fails with
        `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/self_approval_forbidden
        """
        project = make_project(name="P", contract_code="CB-6")
        order = make_order(project["id"], order_code="O-B6")
        make_opening(order["id"], opening_no="1")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")

        # Same user id as submitted_by, even with the Architect role.
        resp = api.set_shop_drawing_status(
            drawing["id"], {"target_status": "APPROVED"}, H("Architect", "est-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN, 403)

        approved = approve_drawing(drawing["id"], user_id="arch-1")
        assert approved["status"] == "APPROVED"

    def test_label_verify_segregation_of_duties(self, api):
        """PRD §2.9: "The QA inspector verifying a label allocation must be
        neither the user who issued it nor the user who applied it."
        PRD §3.6: "per §2.9 the verifier's `X-User-ID` must equal neither
        `issued_by` nor `applied_by` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`,
        HTTP 403)."

        Design: Corner/rbac/label_verify_segregation_of_duties
        """
        ctx = setup_openings_finished(
            contract_code="CB-7", species="MAPLE", profile_code="PR-7",
            finish_system="STAIN", sheen_target="SATIN",
            hardware_prep_mode="TEMPLATE_PREP", fire_rating_required="MIN_20",
            order_code="O-B7", template_code="T-B7",
            openings=({"opening_no": "1", "leaf_count": 1, "fire_rating": "MIN_20",
                       "required_on_site_date": "2026-10-01"},),
            machine_code="M-B7", machine_species=["MAPLE"],
            booth_code="B-B7", cure_start=10, cure_end=14, measured_gu=35,
        )
        opening = ctx["openings"][0]
        roll = make_roll(label_series="UL_20MIN", serial_capacity=2)
        alloc = issue_labels(opening["id"], roll["id"], user_id="la-1")
        alloc = apply_labels(alloc["id"], user_id="pl-1")

        # The issuer may not verify.
        resp = api.set_label_allocation_status(
            alloc["id"], {"target_status": "VERIFIED"}, H("QAInspector", "la-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)
        # The applier may not verify.
        resp = api.set_label_allocation_status(
            alloc["id"], {"target_status": "VERIFIED"}, H("QAInspector", "pl-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)
        # An independent QA inspector verifies.
        verified = validate_success(api.set_label_allocation_status(
            alloc["id"], {"target_status": "VERIFIED"}, H("QAInspector", "qa-7"),
        ), 200)
        assert verified["status"] == "VERIFIED"


class TestSharedReads:
    def test_any_role_can_read(self, api):
        """PRD §2.1: "`Any` is a shared read-only designation: any
        authenticated principal, regardless of declared role, may call the
        read endpoints."

        Design: Corner/rbac/any_role_can_read
        """
        project = make_project(name="P", contract_code="CB-8")
        order = make_order(project["id"], order_code="O-B8")
        for role, uid in (("ShippingCoordinator", "sc-1"), ("LabelAuthority", "la-1"),
                          ("QAInspector", "qa-1"), ("Architect", "arch-1")):
            data = validate_success(api.get_order(order["id"], H(role, uid)), 200)
            assert data["id"] == order["id"], f"GET must succeed for role {role}"
