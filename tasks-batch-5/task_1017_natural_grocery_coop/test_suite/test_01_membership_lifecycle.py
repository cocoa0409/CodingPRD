"""Membership registration, approval/reactivation, drop-with-refund, and the
fiscal-year participation sweep."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_member_payload, create_fiscal_year_payload,
    create_fiscal_year, create_active_member,
    assert_member, NON_EXISTENT_UUID, TEST_USERS,
)

COOP = TEST_USERS["coop_admin_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_register_member_starts_pending_with_member_number(api, coop_admin_headers):
    """PRD §3.1: "Registration creates the member in `PENDING` status with
    `equity_paid_in_cents` at zero and assigns a `member_number`: a co-op-scoped
    integer handed out monotonically in creation order (earliest `created_at` first)."

    Design: Corner/entities/create_member_returns_pending_with_member_number
    """
    res = api.create_member(create_member_payload(full_name="Ada L", email="ada@x.com"),
                            coop_admin_headers)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["membership_status"] == "PENDING"
    assert member["equity_paid_in_cents"] == 0
    assert member["version"] == 1
    assert isinstance(member["member_number"], int)


def test_get_nonexistent_member_returns_not_found(api, coop_admin_headers):
    """PRD §2.9: "every identifier in the path and every foreign key in the body
    resolves to an existing resource, checked left to right, else the corresponding
    not-found error".

    Design: Corner/entities/member_not_found_returns_404
    """
    res = api.get_member(NON_EXISTENT_UUID, coop_admin_headers)
    validate_error(res, "ERR_MEMBER_NOT_FOUND", expected_status=404)


def test_active_member_lapses_on_year_close_when_below_min_participation(api):
    """PRD §3.1: "Closing runs a participation sweep: every member who is `ACTIVE`
    but whose year-to-date patronage-eligible spend is below the minimum participation
    threshold of 5000 cents is transitioned from `ACTIVE` to `LAPSED`."

    Design: Corner/state_machines/member_lapses_on_year_close_low_participation
    """
    fy = create_fiscal_year()
    member = create_active_member(full_name="Lea P", email="lea@x.com")
    assert member["membership_status"] == "ACTIVE"
    assert member["patronage_cents_ytd"] == 0

    closed = validate_success(api.close_fiscal_year(fy["id"], FINANCE), 200)
    assert closed["status"] == "CLOSED"
    member_after = validate_success(api.get_member(member["id"], COOP), 200)
    assert member_after["membership_status"] == "LAPSED"


def test_lapsed_member_reactivated_by_approve(api):
    """PRD §3.1: "Approving a member is a `CoopAdmin` action that moves a member from
    `PENDING` or `LAPSED` to `ACTIVE`; the same endpoint therefore serves both
    first-time approval and reactivation of a lapsed member."

    Design: Corner/state_machines/lapsed_member_reactivated_by_approve
    """
    fy = create_fiscal_year()
    member = create_active_member(full_name="Lea P", email="lea2@x.com")
    api.close_fiscal_year(fy["id"], FINANCE)
    lapsed = validate_success(api.get_member(member["id"], COOP), 200)
    assert lapsed["membership_status"] == "LAPSED"

    reactivated = validate_success(api.approve_member(member["id"], COOP), 200)
    assert reactivated["membership_status"] == "ACTIVE"


def test_second_open_fiscal_year_rejected(api, coop_admin_headers):
    """PRD §3.1: "At most one fiscal year may be `OPEN` at any time; attempting to
    open a second while one is already `OPEN` is rejected with
    `ERR_OPEN_FISCAL_YEAR_EXISTS`."

    Design: Corner/validations/create_second_open_fiscal_year_rejected
    """
    validate_success(api.create_fiscal_year(create_fiscal_year_payload(year=2026),
                                            coop_admin_headers), 201)
    res = api.create_fiscal_year(create_fiscal_year_payload(year=2027, patronage_rate=0.04),
                                 coop_admin_headers)
    validate_error(res, "ERR_OPEN_FISCAL_YEAR_EXISTS", expected_status=409)


class TestEquityConservedOnMemberDrop:
    """Dropping a member refunds equity as a compensating pair (PRD §3.1, §2.7)."""

    def test_drop_zeroes_member_equity_and_terminal_status(self, api):
        """PRD §3.1: "Dropping refunds equity: the OPEN fiscal year's
        `total_equity_cents` is reduced by the member's `equity_paid_in_cents`, and
        then the member's `equity_paid_in_cents` is set to zero — a compensating pair
        that keeps total equity equal to the sum over non-dropped members."

        Design: Difficulty/compensating_invariant/ci_equity_money_conserved_on_member_drop
        """
        create_fiscal_year()
        member = create_active_member(full_name="Cy D", email="cy@x.com", equity_cents=15000)
        dropped = validate_success(api.drop_member(member["id"], COOP), 200)
        assert dropped["membership_status"] == "DROPPED"
        assert dropped["equity_paid_in_cents"] == 0

    def test_drop_refunds_equity_to_fiscal_year_total(self, api):
        """PRD §2.7: "At all times, the OPEN fiscal year's `total_equity_cents` equals
        the sum of `equity_paid_in_cents` over all members whose `membership_status`
        is not `DROPPED`."

        Design: Difficulty/compensating_invariant/ci_equity_money_conserved_on_member_drop
        """
        fy = create_fiscal_year()
        member = create_active_member(full_name="Cy D", email="cy2@x.com", equity_cents=15000)
        fy_before = validate_success(api.get_fiscal_year(fy["id"], FINANCE), 200)
        assert fy_before["total_equity_cents"] == 15000

        api.drop_member(member["id"], COOP)
        fy_after = validate_success(api.get_fiscal_year(fy["id"], FINANCE), 200)
        assert fy_after["total_equity_cents"] == 0
