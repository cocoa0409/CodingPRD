"""Header authentication, role authorisation, duty separation and the 404 family.

PRD §2.1 and §2.5 put authentication, authorisation and crew identity at ranks 1
to 3, ahead of request shape, path resolution and every domain rule, and §5 gives
each referenced entity its own not-found code.
"""

import pytest

from test_helpers import *  # noqa: F401,F403

LOW_GWP_BLEND = {
    "refrigerant_code": "R-454C",
    "trade_name": "Opteon XL20",
    "gwp_100yr": 146,
    "safety_class": "A2L",
    "max_charge_grams": 8000,
    "allowed_system_types": ["REMOTE", "SELF_CONTAINED"],
}


class TestRoleAuthorisation:
    """PRD §2.1 — the acting role must appear on the called endpoint's list."""

    def test_01_platform_admin_performs_its_three_exclusive_operations(self, api):
        """Blend registration, chamber registration and the clock all belong to admin.

        PRD §2.1: "Each endpoint in §4 lists the roles authorised to call it. A
        syntactically valid, authenticated request whose `X-User-Role` is not on
        the called endpoint's list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)
        at global rank 2"

        Design: Corner/rbac/platform_admin_own_operations_allowed
        """
        blend = validate_success(
            api.create_refrigerant(
                create_refrigerant_payload(**LOW_GWP_BLEND),
                TEST_USERS["platform_admin_headers"],
            ),
            expected_status=201,
        )
        assert is_valid_uuid(blend["id"])
        assert blend["refrigerant_code"] == "R-454C"
        assert blend["safety_class"] == "A2L"

        chamber = validate_success(
            api.create_test_chamber(
                create_test_chamber_payload(),
                TEST_USERS["platform_admin_headers"],
            ),
            expected_status=201,
        )
        assert chamber["chamber_code"] == "CH-1"
        assert chamber["turnaround_hours"] == 12

        moved = validate_success(
            api.set_clock(
                {"to_iso8601": "2026-09-01T09:00:00Z"},
                TEST_USERS["platform_admin_headers"],
            )
        )
        assert moved == {}, "the clock endpoint returns an empty object"

    def test_02_design_engineer_cannot_issue_a_compliance_label(self, api):
        """The role check at rank 2 fires before the duty check at rank 9.

        PRD §2.5: "**Rank 2 — authorisation.** The acting role appears on the
        called endpoint's role list, else `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/design_engineer_cannot_issue_compliance_label
        """
        ctx = setup_completed_energy_test()
        assert ctx["case_model"]["status"] == "TESTED_PASS"
        assert ctx["case_model"]["submitted_by_user_id"] == DESIGN_ENGINEER_USER_ID

        payload = create_compliance_label_payload(
            ctx["case_model"]["id"], ctx["energy_test"]["id"]
        )
        rejected = api.create_compliance_label(
            payload, TEST_USERS["design_engineer_headers"]
        )
        validate_error(rejected, ApiErrorId.ERR_UNAUTHORIZED.value)

        _rows, meta = validate_paginated(
            api.list_compliance_labels(TEST_USERS["design_engineer_headers"])
        )
        assert meta["total_count"] == 0
        assert refresh_case_model(ctx)["status"] == "TESTED_PASS"

        issued = validate_success(
            api.create_compliance_label(
                payload, TEST_USERS["compliance_officer_headers"]
            ),
            expected_status=201,
        )
        assert_compliance_label(issued)
        assert issued["label_status"] == "ISSUED"
        assert issued["issued_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
        assert refresh_case_model(ctx)["status"] == "CERTIFIED"

    def test_03_sales_engineer_cannot_release_a_plan_to_the_plant(self, api):
        """Release belongs to the plant, so no work order exists until it calls.

        PRD §3.7: "Releasing an approved plan to the plant is a
        `PlantSupervisor` action, takes no request body, and moves the plan's
        production dimension `NOT_RELEASED → IN_PRODUCTION`."

        Design: Corner/rbac/sales_engineer_cannot_release_plan_to_plant
        """
        ctx = setup_approved_plan()
        assert ctx["store_plan"]["production_status"] == "NOT_RELEASED"

        rejected = api.release_store_plan(
            ctx["store_plan"]["id"], TEST_USERS["sales_engineer_headers"]
        )
        validate_error(rejected, ApiErrorId.ERR_UNAUTHORIZED.value)

        _rows, meta = validate_paginated(
            api.list_work_orders(
                TEST_USERS["plant_supervisor_headers"],
                params={"store_plan_id": ctx["store_plan"]["id"]},
            )
        )
        assert meta["total_count"] == 0
        assert refresh_store_plan(ctx)["production_status"] == "NOT_RELEASED"

        released = validate_success(
            api.release_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["plant_supervisor_headers"]
            )
        )
        assert released["production_status"] == "IN_PRODUCTION"
        assert len(refresh_work_orders(ctx)) == 1

    def test_04_a_request_without_the_user_id_header_is_unauthenticated(self, api):
        """Rank 1 fires on the missing header before rank 6 sees the bad reference.

        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
        the nine role names declared below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first check the service
        performs"

        Design: Corner/rbac/missing_x_user_id_header_rejected_unauthenticated
        """
        blend = seed_refrigerant()

        anonymous = api.create_case_model(
            create_case_model_payload(NON_EXISTENT_UUID),
            headers_without_user_id("DesignEngineer"),
        )
        validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED.value)

        _rows, meta = validate_paginated(
            api.list_case_models(TEST_USERS["design_engineer_headers"])
        )
        assert meta["total_count"] == 0

        created = validate_success(
            api.create_case_model(
                create_case_model_payload(blend["id"]),
                TEST_USERS["design_engineer_headers"],
            ),
            expected_status=201,
        )
        assert created["status"] == "DRAFT"
        assert created["design_revision"] == 1


class TestSegregationOfDuties:
    """PRD §2.9 — the split is enforced on `X-User-ID`, not on the role."""

    def test_05_a_plan_cannot_be_approved_by_the_engineer_who_priced_it(self, api):
        """sales-001 is refused on its own quote; sales-002 approves it unchanged.

        PRD §2.9: "Approving a store plan requires that the acting
        `SalesEngineer`'s `X-User-ID` differ from the `priced_by_user_id` recorded
        when the plan was priced."

        Design: Corner/rbac/plan_approved_by_its_pricing_engineer_rejected
        """
        ctx = setup_priced_plan()
        assert ctx["store_plan"]["priced_by_user_id"] == SALES_ENGINEER_USER_ID

        self_approval = api.approve_store_plan(
            ctx["store_plan"]["id"], TEST_USERS["sales_engineer_headers"]
        )
        validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        plan = refresh_store_plan(ctx)
        assert plan["commercial_status"] == "PRICED"
        assert plan.get("approved_by_user_id") is None

        approved = validate_success(
            api.approve_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["sales_engineer_alt_headers"]
            )
        )
        assert approved["commercial_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == SALES_ENGINEER_ALT_USER_ID
        assert approved["priced_by_user_id"] == SALES_ENGINEER_USER_ID

    def test_06_a_contractor_cannot_sign_for_another_crews_shipment(self, api):
        """Only a crew booked on the trailer may accept it on site.

        PRD §2.1: "A contractor who is not on any booking of that shipment is
        rejected with `ERR_CREW_IDENTITY_MISMATCH` (HTTP 403) at global rank 3."

        Design: Corner/rbac/install_contractor_cannot_hand_off_another_crews_shipment
        """
        ctx = setup_delivered_shipment()
        other_crew = seed_install_crew(
            crew_code="CRW-OH-2",
            contractor_name="Scioto Case Install",
            service_region_codes=["OH"],
            daily_case_capacity=4,
        )
        set_logical_clock("2026-09-17T14:00:00Z")

        rejected = api.handoff_shipment(
            ctx["shipment"]["id"],
            {"received_by_name": "Wrong Crew"},
            make_install_contractor_headers(other_crew["id"]),
        )
        validate_error(rejected, ApiErrorId.ERR_CREW_IDENTITY_MISMATCH.value)

        shipment = refresh_shipment(ctx)
        assert shipment["status"] == "DELIVERED"
        assert shipment.get("handoff_at") is None
        assert refresh_work_orders(ctx)[0].get("warranty_start_date") is None

        accepted = validate_success(
            api.handoff_shipment(
                ctx["shipment"]["id"],
                {"received_by_name": "Dana Ruiz"},
                make_install_contractor_headers(ctx["install_crew"]["id"]),
            )
        )
        assert accepted["status"] == "HANDED_OFF"
        assert accepted["received_by_name"] == "Dana Ruiz"


class TestNotFoundFamily:
    """PRD §2.5 ranks 5 and 6 — each reference reports its own 404 code."""

    def test_07_every_unknown_path_id_returns_its_own_not_found_code(self, api):
        """The same unresolvable uuid yields ten different error ids.

        PRD §2.5: "**Rank 5 — path existence.** Every identifier appearing in the
        URL path resolves to an existing row, validated left to right, else the
        entity-specific not-found error at HTTP 404"

        Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found
        """
        headers = TEST_USERS["platform_admin_headers"]
        readers = [
            (api.get_energy_test, ApiErrorId.ERR_ENERGY_TEST_NOT_FOUND),
            (api.get_compliance_label, ApiErrorId.ERR_COMPLIANCE_LABEL_NOT_FOUND),
            (api.get_store_plan, ApiErrorId.ERR_STORE_PLAN_NOT_FOUND),
            (api.get_store_plan_line, ApiErrorId.ERR_STORE_PLAN_LINE_NOT_FOUND),
            (api.get_work_order, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
            (api.get_shipment, ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
            (api.get_install_crew, ApiErrorId.ERR_INSTALL_CREW_NOT_FOUND),
            (api.get_install_booking, ApiErrorId.ERR_INSTALL_BOOKING_NOT_FOUND),
            (api.get_part_inventory, ApiErrorId.ERR_PART_INVENTORY_NOT_FOUND),
            (api.get_warranty_claim, ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND),
        ]

        seen = set()
        for reader, expected in readers:
            validate_error(reader(NON_EXISTENT_UUID, headers), expected.value)
            seen.add(expected.value)

        assert len(seen) == 10, "no two collections share a not-found code"

    def test_08_case_model_create_with_an_unknown_refrigerant_is_a_404(self, api):
        """The body reference is resolved before the door and line-set rules.

        PRD §2.5: "**Rank 6 — body reference existence.** Every foreign reference
        supplied in the request body resolves to an existing row, validated in the
        order the reference fields are declared on the endpoint, else the
        corresponding not-found error at HTTP 404"

        Design: Corner/errors/case_model_create_with_unknown_refrigerant_returns_not_found
        """
        response = api.create_case_model(
            create_case_model_payload(
                NON_EXISTENT_UUID, line_set_length_ft=0, glass_door_count=2
            ),
            TEST_USERS["design_engineer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_REFRIGERANT_NOT_FOUND.value)

        _rows, meta = validate_paginated(
            api.list_case_models(TEST_USERS["design_engineer_headers"])
        )
        assert meta["total_count"] == 0

    def test_09_energy_test_create_reports_each_unknown_sibling_reference(self, api):
        """Chamber and standard raise distinct 404s ahead of the rank-8 precondition.

        PRD §2.7: "Both checks sit at global rank 8, after state admissibility and
        before every domain rule"

        Design: Corner/errors/energy_test_create_with_unknown_chamber_or_standard_not_found
        """
        ctx = setup_submitted_case_model()
        stale_version = 1
        assert ctx["case_model"]["version"] > stale_version

        unknown_chamber = api.create_energy_test(
            create_energy_test_payload(
                ctx["case_model"]["id"],
                NON_EXISTENT_UUID,
                ctx["energy_standard"]["id"],
                stale_version,
            ),
            TEST_USERS["test_lab_technician_headers"],
        )
        validate_error(unknown_chamber, ApiErrorId.ERR_TEST_CHAMBER_NOT_FOUND.value)

        unknown_standard = api.create_energy_test(
            create_energy_test_payload(
                ctx["case_model"]["id"],
                ctx["test_chamber"]["id"],
                NON_EXISTENT_UUID,
                stale_version,
            ),
            TEST_USERS["test_lab_technician_headers"],
        )
        validate_error(unknown_standard, ApiErrorId.ERR_ENERGY_STANDARD_NOT_FOUND.value)

        _rows, meta = validate_paginated(
            api.list_energy_tests(TEST_USERS["test_lab_technician_headers"])
        )
        assert meta["total_count"] == 0

    def test_10_warranty_claim_create_reports_each_unknown_body_reference(self, api):
        """Unit, depot row and crew each name themselves when unresolvable.

        PRD §2.5: "Every foreign reference supplied in the request body resolves
        to an existing row, validated in the order the reference fields are
        declared on the endpoint, else the corresponding not-found error at HTTP
        404: `ERR_REFRIGERANT_NOT_FOUND`, `ERR_ENERGY_STANDARD_NOT_FOUND`,
        `ERR_TEST_CHAMBER_NOT_FOUND`, `ERR_CASE_MODEL_NOT_FOUND`,
        `ERR_ENERGY_TEST_NOT_FOUND`, `ERR_STORE_PLAN_NOT_FOUND`,
        `ERR_SHIPMENT_NOT_FOUND`, `ERR_INSTALL_CREW_NOT_FOUND`,
        `ERR_PART_INVENTORY_NOT_FOUND` or `ERR_WORK_ORDER_NOT_FOUND`."

        Design: Corner/errors/warranty_claim_create_with_unknown_body_ids_not_found
        """
        ctx = setup_plan_with_completed_units()
        crew = seed_install_crew()
        part = seed_part_inventory(ctx["case_model"]["id"])
        unit_id = ctx["work_orders"][0]["id"]

        cases = [
            (
                (NON_EXISTENT_UUID, part["id"], crew["id"]),
                ApiErrorId.ERR_WORK_ORDER_NOT_FOUND,
            ),
            (
                (unit_id, NON_EXISTENT_UUID, crew["id"]),
                ApiErrorId.ERR_PART_INVENTORY_NOT_FOUND,
            ),
            (
                (unit_id, part["id"], NON_EXISTENT_UUID),
                ApiErrorId.ERR_INSTALL_CREW_NOT_FOUND,
            ),
        ]
        for (work_order_id, part_id, crew_id), expected in cases:
            response = api.create_warranty_claim(
                create_warranty_claim_payload(
                    work_order_id,
                    part_id,
                    crew_id,
                    claim_type="DOOR_GASKET",
                    reported_date="2026-09-20",
                    requested_qty=1,
                    estimated_cost_cents=90000,
                ),
                TEST_USERS["service_manager_headers"],
            )
            validate_error(response, expected.value)

        _rows, meta = validate_paginated(
            api.list_warranty_claims(TEST_USERS["service_manager_headers"])
        )
        assert meta["total_count"] == 0

    def test_11_a_page_limit_above_the_maximum_is_a_request_shape_failure(self, api):
        """101 is refused outright while 100 returns an empty page.

        PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a
        request-shape failure and is rejected with `ERR_INVALID_REQUEST` (HTTP
        400)."

        Design: Corner/errors/case_model_list_limit_above_maximum_returns_invalid_request
        """
        over_maximum = api.list_case_models(
            TEST_USERS["design_engineer_headers"], params={"limit": 101}
        )
        validate_error(over_maximum, ApiErrorId.ERR_INVALID_REQUEST.value)

        rows, meta = validate_paginated(
            api.list_case_models(
                TEST_USERS["design_engineer_headers"], params={"limit": 100}
            )
        )
        assert rows == []
        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
