"""Security: user-context headers, role gating, DealerPrincipal ownership,
segregation of duties, and path-resource existence (PRD §2.1, §2.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    book_order_no_options,
    build_user_headers,
    confirm_order,
    create_boat_model_payload,
    create_build_slot_payload,
    create_campaign,
    create_dealer,
    create_dealer_order_payload,
    create_hull,
    create_model,
    create_run,
    make_compliance_officer_headers,
    make_dealer_principal_headers,
    setup_bookable_world,
    setup_registered_hull,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ALLOC = TEST_USERS["allocation_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
ANY = TEST_USERS["any_headers"]


class TestUserContext:
    def test_missing_user_context_header_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. A request with either header missing, empty, or bearing
        an unrecognized role is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_context_header_returns_400
        """
        resp = api.create_boat_model(create_boat_model_payload(), headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_unrecognized_role_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. A request with either header missing, empty, or bearing
        an unrecognized role is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_context_header_returns_400
        """
        headers = build_user_headers("someone", "Anonymous")
        resp = api.create_boat_model(create_boat_model_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleGating:
    def test_role_denied_returns_403(self, api):
        """PRD §2.1: "Performing an operation outside one's role, or — for a
        `DealerPrincipal` — acting on a dealer other than one's own, is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /boat-models is authorized for SystemAdmin only.

        Design: Corner/validations/rbac_role_denied_returns_403
        """
        resp = api.create_boat_model(create_boat_model_payload(), ALLOC)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_production_planner_cannot_approve_claim(self, api):
        """PRD §2.1: "Performing an operation outside one's role, or — for a
        `DealerPrincipal` — acting on a dealer other than one's own, is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /warranty-claims/{id}/approve is authorized for
        WarrantyAdministrator only.

        Design: Corner/rbac/rbac_production_planner_cannot_approve_claim
        """
        world = setup_registered_hull(api, with_options=False)
        claim = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="x", labor_hours=1.0, parts_cents=1000,
        )
        resp = api.approve_warranty_claim(claim["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_dealer_principal_cannot_issue_recall(self, api):
        """PRD §2.1: "Performing an operation outside one's role, or — for a
        `DealerPrincipal` — acting on a dealer other than one's own, is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /recall-campaigns/{id}/issue is authorized for
        ComplianceOfficer only.

        Design: Corner/rbac/rbac_dealer_principal_cannot_issue_recall
        """
        dealer = create_dealer(api)
        campaign = create_campaign(api)
        resp = api.issue_recall_campaign(
            campaign["id"], make_dealer_principal_headers(dealer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_allocation_manager_cannot_close_run(self, api):
        """PRD §2.1: "Performing an operation outside one's role, or — for a
        `DealerPrincipal` — acting on a dealer other than one's own, is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /production-runs/{id}/close is authorized for
        ProductionPlanner only.

        Design: Corner/rbac/rbac_allocation_manager_cannot_close_run
        """
        run = create_run(api, plant_line_code="L1")
        resp = api.close_production_run(run["id"], ALLOC)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_any_role_can_read(self, api):
        """PRD §2.1: "The declared roles are `SystemAdmin`, `AllocationManager`,
        `ProductionPlanner`, `ComplianceOfficer`, `WarrantyAdministrator`,
        `DealerPrincipal`, and `Any` (the shared read capacity: every
        authenticated role may call every read endpoint)."

        Design: Corner/rbac/rbac_any_role_can_read
        """
        create_model(api, model_code="SP190")
        data, meta = validate_paginated(api.list_boat_models(ANY))
        assert meta["total_count"] == 1
        assert data[0]["model_code"] == "SP190"


class TestDealerPrincipalOwnership:
    def test_dealer_principal_acting_on_other_dealer_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `DealerPrincipal`, `X-User-ID` is
        the `id` of the acting `Dealer`; ownership checks on any resource that
        references a dealer compare the resource's dealer foreign key to
        `X-User-ID` — an order's `dealer_id` on booking, amendment,
        confirmation, and cancellation"
        PRD §2.1: "Performing an operation outside one's role, or — for a
        `DealerPrincipal` — acting on a dealer other than one's own, is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/validations/dealer_principal_acting_on_other_dealer_forbidden
        """
        model = create_model(api)
        da = create_dealer(api, dealer_code="D-A")
        db = create_dealer(api, dealer_code="D-B")
        # A's principal attempts to book against dealer B.
        resp = api.create_dealer_order(
            create_dealer_order_payload(db["id"], model["id"]),
            make_dealer_principal_headers(da["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_dealer_principal_curtailment_path_mismatch(self, api):
        """PRD §2.1: "ownership checks on any resource that references a dealer
        compare the resource's dealer foreign key to `X-User-ID` — an order's
        `dealer_id` on booking, amendment, confirmation, and cancellation; the
        path dealer id on curtailments; the registration's `dealer_id` at
        retail registration; and the registration's owning dealer when filing
        a claim."
        PRD §2.1: "Performing an operation outside one's role, or — for a
        `DealerPrincipal` — acting on a dealer other than one's own, is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_dealer_principal_curtailment_path_mismatch
        """
        da = create_dealer(api, dealer_code="D-A")
        db = create_dealer(api, dealer_code="D-B")
        resp = api.post_curtailment(
            db["id"],
            {"expected_dealer_version": db["version"], "amount_cents": 100},
            make_dealer_principal_headers(da["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestSegregationOfDuties:
    def test_certifier_must_differ_from_hull_creator(self, api):
        """PRD §3.6: "the certifier's `X-User-ID` must differ from the hull's
        `created_by_user_id` — the planner who reported completion may not
        certify it, and a matching identity fails with
        `ERR_SEGREGATION_OF_DUTY`."
        PRD §2.1: "When `X-User-Role` is `ProductionPlanner`, `X-User-ID` is
        likewise opaque, with one recorded use: it is stamped onto each hull as
        `created_by_user_id` at production completion, where it later anchors
        the segregation-of-duties check at certification."

        The role is correct (ComplianceOfficer) but the identity matches the
        creating planner — the duty check rejects.

        Design: Corner/rbac/rbac_segregation_of_duties_certifier_must_differ
        """
        world = setup_bookable_world(api, with_options=False)
        order = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        order = confirm_order(api, order, world["dealer"])
        hull = create_hull(api, order["id"], planner_user_id="planner-1")
        assert hull["created_by_user_id"] == "planner-1"
        resp = api.certify_hull(
            hull["id"], make_compliance_officer_headers("planner-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)


class TestPathResourceExistence:
    def test_patch_unknown_order_returns_404(self, api):
        """PRD §2.9: "Path identifiers exist, validated left to right along the
        URL — the first missing resource yields its `ERR_{RESOURCE}_NOT_FOUND`:
        `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND`, or `ERR_MODEL_NOT_FOUND`."

        Design: Corner/validations/path_id_not_found_returns_404
        """
        dealer = create_dealer(api)
        resp = api.amend_dealer_order(
            NON_EXISTENT_UUID,
            {"expected_order_version": 1},
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_run_not_found_on_slot_creation(self, api):
        """PRD §2.9: "Body-referenced foreign keys exist — `model_id`,
        `dealer_id`, `slot_id`, `show_event_id`, `run_id`, `order_id`,
        `hull_id`, `registration_id`, `recall_notice_id`, each element of
        `option_package_ids`, and `incompatible_with_option_id` — otherwise the
        corresponding `ERR_MODEL_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_SHOW_EVENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or
        `ERR_OPTION_NOT_FOUND`."

        Design: Corner/errors/error_run_not_found_triggerable
        """
        resp = api.create_build_slot(
            create_build_slot_payload(NON_EXISTENT_UUID, slot_code="S1",
                                      capacity_hours=100),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_FOUND)

    def test_hull_not_found_on_certify(self, api):
        """PRD §2.9: "Path identifiers exist, validated left to right along the
        URL — the first missing resource yields its `ERR_{RESOURCE}_NOT_FOUND`:
        `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND`, or `ERR_MODEL_NOT_FOUND`."

        Design: Corner/errors/error_hull_not_found_triggerable
        """
        resp = api.certify_hull(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_HULL_NOT_FOUND)
