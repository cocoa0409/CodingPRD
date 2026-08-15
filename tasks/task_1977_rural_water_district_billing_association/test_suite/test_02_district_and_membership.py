"""District creation defaults, membership onboarding, and member termination."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_district,
    assert_member,
    create_area,
    create_district,
    create_member_payload,
    get_success_data,
    setup_billed_invoice,
    setup_district_with_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, DIRECTOR, approve_member, create_member


class TestDistrictCreationDefaults:
    def test_create_applies_reserve_baseline_and_defaults(self, api):
        """PRD section 3.1: "Creation establishes the reserve baseline immediately:
        `reserve_target_cents` is set equal to `annual_debt_service_cents`, because
        the USDA covenant requires one full year of debt service on hand;
        `reserve_balance_cents` starts at 0; and since the balance is below target,
        `covenant_status` begins as `RESERVE_DEFICIENT`. The district's
        `current_billing_epoch` starts at 0, `active_rate_schedule_id` is null until
        the board adopts a first schedule, and `boil_order_active` is false."

        Design: Corner/entities/district_create_applies_computed_defaults
        """
        district = create_district(district_name="DC", annual_debt_service_cents=240_000)
        assert_district(district)
        assert district["reserve_target_cents"] == 240_000
        assert district["reserve_balance_cents"] == 0
        assert district["reserve_deficit_cents"] == 240_000
        assert district["covenant_status"] == "RESERVE_DEFICIENT"
        assert district["current_billing_epoch"] == 0
        assert district["boil_order_active"] is False
        assert district["active_rate_schedule_id"] is None

        fetched = get_success_data(api.get_district(district["id"], ADMIN))
        assert_district(fetched)
        assert fetched["reserve_target_cents"] == 240_000
        assert fetched["current_billing_epoch"] == 0


class TestMemberCreation:
    def test_member_create_defaults_member_class_residential(self, api):
        """PRD section 3.2: "an optional `member_class` (`RESIDENTIAL`,
        `COMMERCIAL`, or `AGRICULTURAL`, defaulting to `RESIDENTIAL`)" and "A new
        member's `membership_status` is `APPLIED`, with `credit_balance_cents` at 0
        and `consecutive_delinquent_cycles` at 0."

        Design: Corner/entities/member_create_defaults_member_class_residential
        """
        district = create_district(district_name="DD", annual_debt_service_cents=120_000)
        area = create_area(district["id"], boundary_acres=100)
        payload = {"legal_name": "No Class", "service_area_id": area["id"]}
        resp = api.create_member(district["id"], payload, CLERK)
        member = validate_success(resp, expected_status=201)
        assert_member(member)
        assert member["member_class"] == "RESIDENTIAL"
        assert member["membership_status"] == "APPLIED"
        assert member["credit_balance_cents"] == 0
        assert member["consecutive_delinquent_cycles"] == 0

    def test_member_create_missing_legal_name_rejected(self, api):
        """PRD section 2.7: "Request-body well-formedness (`ERR_INVALID_REQUEST`,
        HTTP 400 — a required field missing or of the wrong primitive type) is
        applied after the auth and role checks and before path-existence checks."
        PRD section 3.2 names `legal_name` as part of the application payload.

        Design: Corner/entities/member_create_missing_required_field_returns_invalid_request
        """
        district = create_district(district_name="DE", annual_debt_service_cents=120_000)
        area = create_area(district["id"], boundary_acres=100)
        resp = api.create_member(district["id"], {"service_area_id": area["id"]}, CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_member_create_with_cross_district_area_rejected(self, api):
        """PRD section 3.2: "The referenced area must belong to the same district
        and be in `ACTIVE` or `ANNEXED_IN` status, or the application is rejected
        with `ERR_AREA_NOT_SERVICEABLE` (HTTP 422)."

        Design: Corner/validations/member_area_not_serviceable_rejected
        """
        district1 = create_district(district_name="VD1")
        district2 = create_district(district_name="VD2")
        area = create_area(district1["id"], boundary_acres=100)
        resp = api.create_member(
            district2["id"], create_member_payload(area["id"], legal_name="Cross"), CLERK
        )
        validate_error(resp, ApiErrorId.ERR_AREA_NOT_SERVICEABLE, expected_status=422)


class TestMemberListing:
    def test_member_list_pagination_envelope(self, api):
        """PRD section 2.3: "List endpoints accept optional `limit` and `offset`
        query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum
        of 100; `offset` defaults to 0. List responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` envelope. Default sort order on
        every list endpoint is `created_at` ascending."

        Design: Corner/entities/member_list_pagination_envelope
        """
        district = create_district(district_name="DG")
        area = create_area(district["id"], boundary_acres=100)
        for name in ("P1", "P2", "P3"):
            create_member(district["id"], area["id"], legal_name=name)

        page1, meta1 = validate_paginated(
            api.list_members(district["id"], CLERK, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2, f"Expected 2 rows on page 1, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_members(district["id"], CLERK, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1, f"Expected 1 row on page 2, got {len(page2)}"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3
        ids = {row["id"] for row in page1} | {row["id"] for row in page2}
        assert len(ids) == 3, "Pages must partition the member set without overlap"


class TestMemberTermination:
    def test_terminate_blocked_by_open_invoice(self, api):
        """PRD section 3.2: "a `BoardDirector` terminates a member (`ACTIVE →
        TERMINATED`) only when every tap is `ABANDONED` or none exist and no invoice
        remains in `ISSUED` or `PARTIALLY_PAID` status — otherwise
        `ERR_OPEN_INVOICES_EXIST` (HTTP 409)."

        Design: Corner/state_machines/member_terminate_blocked_by_open_invoice
        """
        ctx = setup_billed_invoice(usage_gallons=100)
        district = ctx["district"]
        member = ctx["member"]
        assert ctx["invoice"]["billing_status"] == "ISSUED"

        resp = api.terminate_member(district["id"], member["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OPEN_INVOICES_EXIST, expected_status=409)
        after = get_success_data(api.get_member(district["id"], member["id"], DIRECTOR))
        assert after["membership_status"] == "ACTIVE", (
            f"Member must remain ACTIVE after a blocked termination, got {after['membership_status']}"
        )
