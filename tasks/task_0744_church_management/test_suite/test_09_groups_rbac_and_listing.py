"""Small-group memberships, RBAC, pagination."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, create_adult_member,
    create_and_activate_campaign, create_pledge, create_small_group,
    create_group_membership, make_member_headers,
)


class TestGroupMembershipInvariant:
    def test_create_then_deactivate_preserves_roster_count(self, api):
        """PRD §3.7: "On create, the server sets status to ACTIVE, derives
        joined_on from the current server date (from the logical clock),
        and increments the group's roster_count by one."
        PRD §3.7: "A Coordinator may deactivate a membership, moving it to
        the terminal PAST and decrementing the group's roster_count by
        one."

        Design: Difficulty/compensating_invariant/group_membership_create_then_deactivate_preserves_roster_count
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m1 = create_adult_member(h["id"], full_name="M1", email="m1@x.com",
                                 membership_status="REGULAR")
        m2 = create_adult_member(h["id"], full_name="M2", email="m2@x.com",
                                 date_of_birth="1992-01-01")
        g = create_small_group(leader_member_id=m1["id"],
                               name="Bible Study",
                               ministry_area="STUDY", capacity=10)
        gm = create_group_membership(g["id"], m2["id"], role="MEMBER")
        # Deactivate.
        deactivated = validate_success(
            api.deactivate_group_membership(
                gm["id"], TEST_USERS["coordinator_headers"]
            )
        )
        assert deactivated["status"] == "PAST"
        # Roster count returned to zero.
        group = validate_success(
            api.get_small_group(g["id"], TEST_USERS["coordinator_headers"])
        )
        assert group["roster_count"] == 0

    def test_deactivated_membership_status_is_past(self, api):
        """PRD §3.7: "A Coordinator may deactivate a membership, moving it
        to the terminal PAST and decrementing the group's roster_count by
        one."

        Design: Difficulty/compensating_invariant/group_membership_create_then_deactivate_preserves_roster_count
        """
        # Second required test — verifies the terminal PAST assertion.
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m1 = create_adult_member(h["id"], full_name="M1", email="m1@x.com",
                                 membership_status="REGULAR")
        m2 = create_adult_member(h["id"], full_name="M2", email="m2@x.com")
        g = create_small_group(leader_member_id=m1["id"],
                               name="Care Circle",
                               ministry_area="CARE", capacity=5)
        gm = create_group_membership(g["id"], m2["id"], role="MEMBER")
        api.deactivate_group_membership(gm["id"],
                                        TEST_USERS["coordinator_headers"])
        result = validate_success(
            api.get_group_membership(gm["id"],
                                     TEST_USERS["coordinator_headers"])
        )
        assert result["status"] == "PAST"


class TestRbacUnauthenticated:
    def test_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "If X-User-Role is missing or does not name one of
        the five declared roles, the request is rejected with
        ERR_UNAUTHENTICATED and HTTP 401."

        Design: Corner/errors/err_unauthenticated_missing_role_header
        """
        resp = api.get_household("00000000-0000-0000-0000-000000000000",
                                 TEST_USERS["unknown_role_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbacForbidden:
    def test_registrar_cannot_create_facility(self, api):
        """PRD §2.1: "If the role is present but the endpoint is not
        authorized for that role (per §4), the request is rejected with
        ERR_FORBIDDEN and HTTP 403."
        PRD §2.1: "Registrar owns household and member directory
        operations exclusively; it cannot touch finance, events,
        facilities, or check-ins."

        Design: Corner/errors/err_forbidden_registrar_cannot_create_facility
        """
        resp = api.create_facility(
            {"name": "X", "capacity": 100, "buffer_minutes": 0},
            TEST_USERS["registrar_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRbacPeerIsolation:
    def test_member_cannot_post_donation_for_other_member(self, api):
        """PRD §2.1: "A Member may create a pledge or donation only when
        the payload's member_id equals X-User-ID..."

        Design: Corner/rbac/member_cannot_post_donations_for_other_member
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m1 = create_adult_member(h["id"], full_name="M1", email="m1@x.com")
        m2 = create_adult_member(h["id"], full_name="M2", email="m2@x.com",
                                 date_of_birth="1990-06-01")
        # M1 acting, posting a donation for M2.
        resp = api.create_donation(
            {"member_id": m2["id"], "amount_cents": 1_000,
             "donation_date": "2026-06-01", "payment_method": "CHECK"},
            make_member_headers(m1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_coordinator_cannot_issue_year_end_statement(self, api):
        """PRD §2.1: "FinanceAdmin owns pledge-campaign lifecycle,
        donation posting and refunding, and year-end-statement
        operations."

        Design: Corner/rbac/coordinator_cannot_issue_year_end_statement
        """
        set_clock("2027-02-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        s = validate_success(
            api.create_year_end_statement(
                {"member_id": m["id"], "tax_year": 2026, "variant": "FINAL"},
                TEST_USERS["finance_admin_headers"],
            ),
            expected_status=201,
        )
        resp = api.issue_year_end_statement(s["id"],
                                            TEST_USERS["coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestPagination:
    def test_pledges_pagination_envelope_shape(self, api):
        """PRD §2.3: "The response's meta object exposes limit (the value
        the server used), offset (the value the server used), total_count
        (the total number of records matching the filter, ignoring
        pagination), and has_more (a boolean that is true when offset +
        limit < total_count)."

        Design: Corner/endpoints/pagination_returns_envelope_shape
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(name="C1", target_amount_cents=100_000)
        create_pledge(c["id"], m["id"], pledged_amount_cents=5_000)
        create_pledge(c["id"], m["id"], pledged_amount_cents=8_000)
        resp = api.list_pledges(
            TEST_USERS["finance_admin_headers"],
            params={"member_id": m["id"], "limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1
