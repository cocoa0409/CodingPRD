"""Role-based access control: role-exclusive operations, entity-backed ownership,
and unauthenticated access."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, ANON_HEADERS,
    create_plan_payload, create_table_payload,
    make_member_headers,
)
from test_helpers import fixtures as fx


class TestRoleExclusivity:
    def test_member_cannot_create_plan(self, api):
        """PRD 2.1: "When the headers are present but the role is not permitted to
        perform the operation — or a member attempts to act on a resource it does not own
        — the request is rejected with ERR_FORBIDDEN (HTTP 403)."
        PRD 4 endpoint table: POST /v1/plans is authorized for Manager only.

        Design: Corner/rbac/member_cannot_create_plan_forbidden
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_member(plan["id"])
        resp = api.create_plan(
            create_plan_payload(tier="GOLD", monthly_fee_cents=8000, table_discount_pct=0.20),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_frontdesk_cannot_seed_tournament(self, api):
        """PRD 2.1: "When the headers are present but the role is not permitted to
        perform the operation ... the request is rejected with ERR_FORBIDDEN (HTTP 403)."
        PRD 4 endpoint table: POST /v1/tournaments/{id}/seed is authorized for Manager
        only.

        Design: Corner/rbac/frontdesk_cannot_seed_tournament_forbidden
        """
        t = fx.make_tournament(name="RbacCup", entry_fee_cents=0, max_entries=8,
                               open_registration=True)
        resp = api.seed_tournament(t["id"], TEST_USERS["frontdesk"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestOwnership:
    def test_member_cannot_cancel_other_members_reservation(self, api):
        """PRD 2.1: "Ownership checks on any resource that references a member compare
        that resource's member foreign key (for example a reservation's member_id ...)
        against X-User-ID. A member may only read and mutate resources that resolve to
        their own id."

        Design: Corner/rbac/member_cannot_cancel_other_members_reservation_forbidden
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member_a = fx.make_member(plan["id"], email="rba@x.com")
        member_b = fx.make_member(plan["id"], email="rbb@x.com")
        table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
        res = fx.make_reservation(member_a["id"], table["id"],
                                  "2026-07-09T10:00:00Z", "2026-07-09T11:00:00Z",
                                  headers=make_member_headers(member_a["id"]))
        resp = api.cancel_reservation(res["id"], make_member_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        after = validate_success(api.get_reservation(res["id"], TEST_USERS["frontdesk"]))
        assert after["status"] == "PENDING"


class TestUnauthenticated:
    def test_create_table_without_auth_rejected(self, api):
        """PRD 2.1: "Every request other than open registration and anonymous reads must
        carry two headers: X-User-ID ... and X-User-Role ... If either header is missing
        or malformed on a protected endpoint, the request is rejected with
        ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/rbac/create_table_missing_auth_returns_401
        """
        resp = api.create_table(
            create_table_payload(table_number=46, table_type="POOL_7FT",
                                 seat_capacity=4, hourly_rate_cents=1000),
            ANON_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
