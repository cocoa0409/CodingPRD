"""Membership registration, renewal, and plan-change OCC.

Covers corner-design instances (entities, calculations, cross_cutting) and the
member-standing lifecycle. Every test starts against an empty database.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_member_payload,
    make_member_headers,
)
from test_helpers import fixtures as fx


class TestMemberRegistration:
    def test_register_member_returns_201_with_default_computed_fields(self, api):
        """PRD 3.1: "On registration the member's membership_status is ACTIVE, and
        membership_expires_at is set to the registration instant plus thirty days.
        A new member's computed fields start at their defaults: pending_plan_id is
        null, wallet_credit_cents is zero, and no_show_strikes is zero."
        PRD 2.4: "The version begins at 1 when the resource is created and increases
        by exactly 1 on every mutation that changes the resource"
        PRD 4: "Newly created resources are returned with HTTP 201"

        Design: Corner/entities/member_creation_returns_201_with_fields
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        resp = api.create_member(
            create_member_payload(email="cr1@x.com", full_name="Cr One", plan_id=plan["id"]),
            TEST_USERS["manager"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["membership_status"] == "ACTIVE"
        assert data["wallet_credit_cents"] == 0
        assert data["version"] == 1

    def test_get_nonexistent_member_returns_not_found(self, api):
        """PRD 2.8: "Existence — every id named in the path or body resolves to a
        live entity, validated left to right along the path, else ERR_NOT_FOUND (404)."

        Design: Corner/entities/member_get_nonexistent_returns_not_found
        """
        resp = api.get_member(NON_EXISTENT_UUID, TEST_USERS["frontdesk"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_register_member_duplicate_email_rejected(self, api):
        """PRD 2.8: "Uniqueness is enforced independently: a duplicate tier across
        active plans, table_number, member email, or product sku is rejected with
        ERR_DUPLICATE (409)."

        Design: Corner/entities/member_duplicate_email_returns_duplicate
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        api.create_member(
            create_member_payload(email="dup@x.com", full_name="Dup A", plan_id=plan["id"]),
            TEST_USERS["manager"],
        )
        resp = api.create_member(
            create_member_payload(email="dup@x.com", full_name="Dup B", plan_id=plan["id"]),
            TEST_USERS["manager"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


class TestPlanValidation:
    def test_create_plan_missing_discount_returns_validation(self, api):
        """PRD 3.1: "a table_discount_pct, the fraction of a final table charge waived
        for members on that plan (between 0.0 and 0.5 inclusive)."
        PRD 2.8: "Body validity — field types, enums, ranges, and required fields,
        else ERR_VALIDATION (422)."

        Design: Corner/entities/plan_missing_required_discount_returns_validation
        """
        resp = api.create_plan({"tier": "GOLD", "monthly_fee_cents": 8000}, TEST_USERS["manager"])
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestMemberListing:
    def test_list_members_limit_over_max_returns_pagination(self, api):
        """PRD 2.3: "The limit defaults to 10 when omitted, may be no smaller than 1,
        and may be no larger than 100. ... A limit or offset outside its allowed range
        is rejected with ERR_PAGINATION (HTTP 422)."

        Design: Corner/entities/members_list_limit_out_of_range_returns_pagination
        """
        resp = api.list_members(TEST_USERS["manager"], params={"limit": 999})
        validate_error(resp, ApiErrorId.ERR_PAGINATION.value)


class TestMembershipRenewal:
    def test_active_renewal_debits_monthly_fee(self, api):
        """PRD 3.1: "Renewal charges the member's current plan monthly_fee_cents against
        the wallet and always resets no_show_strikes to zero."

        Design: Corner/calculations/membership_renew_debits_monthly_fee
        """
        plan = fx.make_plan(tier="SILVER", monthly_fee_cents=5000, table_discount_pct=0.10)
        member = fx.make_funded_member(plan["id"], 20000)
        resp = api.renew_member(member["id"], {}, make_member_headers(member["id"]))
        data = validate_success(resp)
        assert data["wallet_credit_cents"] == 15000
        assert data["no_show_strikes"] == 0


class TestPlanChangeOCC:
    def test_plan_change_stale_version_conflict(self, api):
        """PRD 2.7: "If expected_member_version does not equal the member's current
        version, the request is rejected with ERR_STALE_VERSION (HTTP 412)."
        PRD 2.4: "The version begins at 1 when the resource is created and increases
        by exactly 1 on every mutation that changes the resource"

        Design: Corner/cross_cutting_complexity_layers/occ_member_plan_change_stale_version_conflict
        """
        silver = fx.make_plan(tier="SILVER", monthly_fee_cents=5000, table_discount_pct=0.10)
        gold = fx.make_plan(tier="GOLD", monthly_fee_cents=8000, table_discount_pct=0.20)
        member = fx.make_member(silver["id"])
        stale_version = member["version"]  # 1
        # A wallet adjustment mutates the member -> version advances to 2.
        fx.fund_member(member["id"], 5000)
        resp = api.change_member_plan(
            member["id"],
            {"target_plan_id": gold["id"], "expected_member_version": stale_version},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
