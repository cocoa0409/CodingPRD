"""Resource creation, type/required-field validation, computed fields, immutability,
listing, soft-delete, and RBAC denials. Covers the entities / rbac / cross_cutting
(soft-delete) corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, make_account_holder_headers, build_user_headers,
    ApiErrorId,
    assert_service_plan, assert_holiday,
    create_plan, create_zone, create_account,
    basic_plan_payload, create_service_plan_payload,
)

DISP = TEST_USERS["dispatcher_headers"]
NONEXISTENT = "00000000-0000-4000-8000-000000000000"


class TestCreation:
    def test_create_plan_returns_201_with_all_fields(self, api):
        """PRD §3.1: "A plan also carries an archived flag that begins as false."
        PRD §2.4: "a version that is an integer beginning at 1 and incrementing by exactly
        one on every mutation of the resource."

        Design: Corner/entities/create_service_plan_returns_201_with_all_fields
        """
        plan = validate_success(api.create_service_plan(basic_plan_payload(), DISP), 201)
        assert_service_plan(plan)
        assert plan["archived"] is False
        assert plan["version"] == 1

    def test_get_account_not_found(self, api):
        """PRD §2.5: "The server validates every path identifier left to right and rejects
        the request with ERR_NOT_FOUND (HTTP 404) at the first identifier in the path that
        names no existing resource."

        Design: Corner/entities/get_account_not_found_returns_404
        """
        validate_error(api.get_account(NONEXISTENT, DISP), ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_account_missing_service_address_rejected(self, api):
        """PRD §2.6: "then well-formedness of the body and query parameters — required
        fields present, enum members drawn from their allowed sets, integers within their
        declared ranges, and pagination bounds respected (ERR_INVALID_REQUEST)."

        Design: Corner/entities/create_account_missing_required_field_returns_invalid_request
        """
        plan = create_plan()
        zone = create_zone()
        validate_error(api.create_account(
            {"plan_id": plan["id"], "zone_id": zone["id"], "holder_name": "No Addr"}, DISP),
            ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_plan_invalid_tier_enum_rejected(self, api):
        """PRD §3.1: "A service plan is created with a tier — one of BASIC, STANDARD, or
        PREMIUM."
        PRD §2.6: "then well-formedness of the body and query parameters — required fields
        present, enum members drawn from their allowed sets, integers within their declared
        ranges, and pagination bounds respected (ERR_INVALID_REQUEST)."

        Design: Corner/entities/create_plan_invalid_enum_tier_returns_invalid_request
        """
        validate_error(api.create_service_plan(create_service_plan_payload(tier="GOLD"), DISP),
                       ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_cart_invalid_size_enum_rejected(self, api):
        """PRD §3.2: "A Dispatcher assigns a cart to an account by giving its cart_type —
        TRASH or RECYCLING — and its size_gallons of 35, 65, or 96."
        PRD §2.6: "then well-formedness of the body and query parameters — required fields
        present, enum members drawn from their allowed sets, integers within their declared
        ranges, and pagination bounds respected (ERR_INVALID_REQUEST)."

        Design: Corner/entities/create_cart_invalid_size_enum_returns_invalid_request
        """
        plan = create_plan()
        zone = create_zone()
        acct = create_account(plan["id"], zone["id"], address="50 Oak St")
        validate_error(api.create_cart(acct["id"], {"cart_type": "TRASH", "size_gallons": 50}, DISP),
                       ApiErrorId.ERR_INVALID_REQUEST.value)


class TestComputedAndImmutable:
    def test_holiday_immutable_no_version_field(self, api):
        """PRD §2.4: "The Holiday resource is the sole exception. A holiday entry is
        immutable after creation, so it carries only id and created_at; it has neither an
        updated_at nor a version."

        Design: Corner/entities/holiday_immutable_entity_no_version_field
        """
        zone = create_zone()
        holiday = validate_success(api.create_holiday(
            zone["id"], {"holiday_date": "2026-12-25T00:00:00Z", "shift_direction": "DELAY_ONE_DAY"}, DISP), 201)
        assert "version" not in holiday, "Holiday must not carry a version key"
        assert "updated_at" not in holiday, "Holiday must not carry an updated_at key"
        assert "id" in holiday and "created_at" in holiday

    def test_fresh_account_balances_are_zero(self, api):
        """PRD §3.2: "The credit balance is the sum of amount_cents over every
        MissedPickupCredit on the account still in ISSUED status. The account balance is
        the sum of amount_due_cents over every Invoice on the account whose status is OPEN
        or PAST_DUE."

        Design: Corner/entities/account_balance_computed_field_input_ignored
        """
        plan = create_plan()
        zone = create_zone()
        acct = create_account(plan["id"], zone["id"], address="52 Oak St")
        fetched = validate_success(api.get_account(acct["id"], DISP), 200)
        assert fetched["account_balance_cents"] == 0
        assert fetched["credit_balance_cents"] == 0

    def test_third_cart_is_extra(self, api):
        """PRD §3.2: "a cart's is_extra flag is true when it is beyond the one TRASH and
        one RECYCLING cart a plan provisions."

        Design: Corner/entities/cart_is_extra_computed_third_cart_true
        """
        plan = create_plan()
        zone = create_zone()
        acct = create_account(plan["id"], zone["id"], address="54 Oak St")
        get_success_data(api.create_cart(acct["id"], {"cart_type": "TRASH", "size_gallons": 65}, DISP))
        get_success_data(api.create_cart(acct["id"], {"cart_type": "RECYCLING", "size_gallons": 65}, DISP))
        third = validate_success(api.create_cart(acct["id"], {"cart_type": "TRASH", "size_gallons": 35}, DISP), 201)
        assert third["is_extra"] is True


class TestListing:
    def test_list_plans_pagination_envelope(self, api):
        """PRD §2.3: "Every list response carries limit, offset, total_count, and has_more
        in the envelope's meta object, where total_count is the full count before
        pagination and has_more indicates whether records remain beyond the current page."

        Design: Corner/entities/list_plans_pagination_envelope
        """
        create_plan(plan_overrides={"tier": "BASIC", "trash_cart_size_gallons": 35,
                                    "recycling_cart_size_gallons": 35})
        data, meta = validate_paginated(api.list_service_plans(DISP, {"limit": 10, "offset": 0}))
        assert isinstance(data, list)
        assert meta["total_count"] >= 1
        assert "has_more" in meta

    def test_archived_plan_excluded_by_default_included_on_opt_in(self, api):
        """PRD §3.1: "Archived plans are excluded from the default plan listing — they
        appear only when a list request opts in — and an archived plan can never be newly
        assigned to an account."

        Design: Corner/cross_cutting_complexity_layers/soft_deleted_plan_excluded_from_default_list
        """
        arch = get_success_data(api.create_service_plan(basic_plan_payload(), DISP))
        get_success_data(api.archive_service_plan(arch["id"], DISP))
        create_plan()  # an active plan
        default_data, _ = validate_paginated(api.list_service_plans(DISP, {"include_archived": False}))
        assert all(p["id"] != arch["id"] for p in default_data), "archived plan must be hidden by default"
        incl_data, _ = validate_paginated(api.list_service_plans(DISP, {"include_archived": True}))
        assert any(p["id"] == arch["id"] for p in incl_data), "archived plan must appear with opt-in"


class TestRbacDenials:
    def test_account_holder_cannot_create_plan(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the targeted
        operation is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/account_holder_cannot_create_plan_forbidden
        """
        holder = build_user_headers("00000000-0000-4000-8000-000000000099", "AccountHolder")
        validate_error(api.create_service_plan(create_service_plan_payload(), holder),
                       ApiErrorId.ERR_FORBIDDEN.value)

    def test_crewlead_cannot_generate_invoice(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the targeted
        operation is rejected with ERR_FORBIDDEN (HTTP 403)."
        PRD §2.6: "first authentication of the headers ...; then authorization of the role
        for the endpoint (ERR_FORBIDDEN)."

        Design: Corner/rbac/crewlead_cannot_generate_invoice_forbidden
        """
        plan = create_plan()
        zone = create_zone()
        acct = create_account(plan["id"], zone["id"], address="94 Oak St")
        get_success_data(api.create_cart(acct["id"], {"cart_type": "TRASH", "size_gallons": 65}, DISP))
        get_success_data(api.create_cart(acct["id"], {"cart_type": "RECYCLING", "size_gallons": 65}, DISP))
        acct = get_success_data(api.activate_start(acct["id"], DISP))
        crew = TEST_USERS["crew_lead_headers"]
        validate_error(api.generate_invoice(acct["id"], {
            "expected_account_version": acct["version"],
            "period_start": "2026-03-01T00:00:00Z", "period_end": "2026-04-01T00:00:00Z",
            "due_date": "2026-04-15T00:00:00Z"}, crew),
            ApiErrorId.ERR_FORBIDDEN.value)

    def test_unrecognized_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying an X-User-Role that is
        not one of these three exact strings, is rejected with ERR_UNAUTHENTICATED
        (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        bad = {"X-User-ID": "x", "X-User-Role": "Stranger", "Content-Type": "application/json"}
        validate_error(api.list_service_plans(bad), ApiErrorId.ERR_UNAUTHENTICATED.value)
