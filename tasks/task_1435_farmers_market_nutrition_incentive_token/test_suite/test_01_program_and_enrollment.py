"""Program setup, shopper enrollment, and listing claims (PRD §3.1, §3.3)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_program, create_shopper_payload, create_market_payload,
    assert_program, assert_shopper,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]


class TestProgramCreation:
    def test_program_creation_initializes_computed_fields(self, api):
        """PRD §3.1: "At creation the program's computed fields take their initial
        values: `match_pool_remaining_cents` initializes to the full budget, the
        liability views `liability_forward_cents` and `liability_realized_cents`
        and the disbursement counter `paid_out_cents` all start at zero, and
        `version` starts at 1."

        Design: Corner/entities/c_ent_program_creation_applies_computed_defaults
        """
        program = validate_success(api.create_program({
            "name": "P",
            "season_start": "2026-08-01T00:00:00Z",
            "season_end": "2026-09-01T00:00:00Z",
            "match_pool_budget_cents": 50000,
        }, ADMIN), expected_status=201)
        assert_program(program)
        assert program["match_pool_remaining_cents"] == 50000, "pool initializes to full budget"
        assert program["liability_forward_cents"] == 0
        assert program["liability_realized_cents"] == 0
        assert program["paid_out_cents"] == 0
        assert program["version"] == 1, "version starts at 1"


class TestShopperEnrollment:
    def test_shopper_created_enrolled_with_zero_usage(self, api):
        """PRD §3.3: "A new shopper starts in `ENROLLED` status with
        `season_match_used_cents` at zero."

        Design: Corner/entities/c_ent_shopper_default_status_enrolled
        """
        program = create_program(pool_cents=50000)
        shopper = validate_success(api.create_shopper(
            create_shopper_payload(program_id=program["id"],
                                   external_benefit_ref="EBT-1", benefit_type="WIC"),
            BOOTH), expected_status=201)
        assert_shopper(shopper)
        assert shopper["status"] == "ENROLLED", "initial status is ENROLLED"
        assert shopper["season_match_used_cents"] == 0

    def test_duplicate_benefit_ref_rejected_within_program(self, api):
        """PRD §3.3: "The external reference is unique within the program among
        shoppers who are not `SUSPENDED`: a duplicate enrollment is rejected with
        `ERR_DUPLICATE_ENROLLMENT`, while a reference previously held by a
        since-suspended shopper may be reused."

        Design: Corner/entities/c_ent_duplicate_benefit_ref_rejected
        """
        p1 = create_program(pool_cents=50000, name="P1")
        p2 = create_program(pool_cents=50000, name="P2")
        validate_success(api.create_shopper(
            create_shopper_payload(program_id=p1["id"], external_benefit_ref="EBT-1",
                                   benefit_type="SNAP"), BOOTH), expected_status=201)

        dup = api.create_shopper(
            create_shopper_payload(program_id=p1["id"], external_benefit_ref="EBT-1",
                                   benefit_type="SNAP"), BOOTH)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)

        other = api.create_shopper(
            create_shopper_payload(program_id=p2["id"], external_benefit_ref="EBT-1",
                                   benefit_type="SNAP"), BOOTH)
        created = validate_success(other, expected_status=201)
        assert created["program_id"] == p2["id"], "uniqueness is program-scoped"


class TestReferenceIntegrity:
    def test_market_creation_requires_existing_program(self, api):
        """PRD §2.9: "Identifiers referenced inside a request body — `shopper_id`,
        `market_day_id`, `program_id`, `market_id`, the elements of `token_ids`,
        and the fraud-case subject fields `vendor_id`, `shopper_id`, and
        `token_id` — are validated after the path resolves; a body reference to a
        missing resource is rejected with `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/entities/c_ent_child_creation_requires_existing_parent
        """
        resp = api.create_market(
            create_market_payload(program_id=NON_EXISTENT_UUID, name="M", city="C"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_get_missing_program_returns_not_found(self, api):
        """PRD §2.9: "When an endpoint path carries resource identifiers, the
        system validates their existence sequentially, left to right, and rejects
        the request immediately with `ERR_NOT_FOUND` at the first identifier that
        does not correspond to an existing resource."

        Design: Corner/entities/c_ent_get_missing_program_returns_not_found
        """
        resp = api.get_program(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestShopperListing:
    def test_shopper_list_status_filter_and_pagination(self, api):
        """PRD §3.3: "The shopper roster of a program can be listed with a `status`
        filter, and individual issuances and shopper records are readable by the
        roles listed in §4 — including the shopper itself, whose entity-backed
        identity grants read access to its own record."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/c_ent_shopper_list_filters_status_and_paginates
        """
        program = create_program(pool_cents=50000)
        s1 = validate_success(api.create_shopper(
            create_shopper_payload(program_id=program["id"], external_benefit_ref="EBT-1",
                                   benefit_type="SNAP"), BOOTH), expected_status=201)
        s2 = validate_success(api.create_shopper(
            create_shopper_payload(program_id=program["id"], external_benefit_ref="EBT-2",
                                   benefit_type="WIC"), BOOTH), expected_status=201)
        validate_success(api.create_shopper(
            create_shopper_payload(program_id=program["id"], external_benefit_ref="EBT-3",
                                   benefit_type="SENIOR"), BOOTH), expected_status=201)
        validate_success(api.verify_shopper(s1["id"], ADMIN))
        validate_success(api.verify_shopper(s2["id"], ADMIN))

        active, meta_active = validate_paginated(
            api.list_program_shoppers(program["id"], ADMIN, params={"status": "ACTIVE"}))
        assert len(active) == 2, "exactly the two verified shoppers are ACTIVE"
        assert {s["id"] for s in active} == {s1["id"], s2["id"]}
        assert all(s["status"] == "ACTIVE" for s in active)

        page, meta = validate_paginated(
            api.list_program_shoppers(program["id"], ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page) == 2, "limit caps the page size"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
