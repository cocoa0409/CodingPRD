"""Scholarship funds, awards, weekly disbursement, and fee accrual."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accrue_friday,
    activate_award,
    assert_fund_conservation,
    create_active_member,
    create_award,
    create_fund,
    director_headers,
    get_fund,
    get_member,
    open_club_day,
    setup_activated_award,
    setup_site_with_director,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _get_award(api, member_id, award_id):
    data, _ = validate_paginated(api.list_member_awards(member_id, ADMIN))
    for aw in data:
        if aw["id"] == award_id:
            return aw
    raise AssertionError(f"award {award_id} not found for member {member_id}")


def _paid_member(api, site, director, name="Pay Kid"):
    """ACTIVE member on the PAID tier (weekly fee 5,000; balance 2,500)."""
    return create_active_member(
        site["id"], director["id"], legal_name=name,
        date_of_birth="2011-01-01", grade=8, household_income_cents=5_000_000,
    )


def test_fund_close_cancels_pending_and_blocks_new_awards(api):
    """PRD 3.3: "Closing moves the fund to `CLOSED` and cancels every `PENDING`
    award on it; `ACTIVE` awards are deliberately unaffected" and "The
    referenced member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`) and the fund
    `OPEN` (`ERR_FUND_NOT_OPEN`)."

    Design: Corner/endpoints/c_fund_close_cancels_pending_and_blocks_new_awards
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    fund = create_fund(site["id"], 50_000)
    award = create_award(fund["id"], member["id"], director["id"],
                         discount_pct=0.50, weekly_cap_cents=1000,
                         annual_cap_cents=4000)
    closed = validate_success(
        api.close_scholarship_fund(fund["id"], ADMIN), 200
    )
    assert closed["status"] == "CLOSED"
    assert _get_award(api, member["id"], award["id"])["status"] == "CANCELLED"

    res = api.create_scholarship_award(
        {"fund_id": fund["id"], "member_id": member["id"], "discount_pct": 0.25,
         "weekly_cap_cents": 500, "annual_cap_cents": 1000},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_FUND_NOT_OPEN, expected_status=409)


def test_fund_insufficient_at_activate(api):
    """PRD 3.3: "the fund's `available_cents` must be at least the award's
    `annual_cap_cents` (`ERR_FUND_INSUFFICIENT`, 422)".

    Design: Corner/endpoints/c_fund_insufficient_at_activate
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    fund = create_fund(site["id"], 1_000)
    award = create_award(fund["id"], member["id"], director["id"],
                         discount_pct=0.50, weekly_cap_cents=500,
                         annual_cap_cents=2000)
    res = api.activate_scholarship_award(
        award["id"], {"expected_fund_version": fund["version"]},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_FUND_INSUFFICIENT, expected_status=422)
    assert _get_award(api, member["id"], award["id"])["status"] == "PENDING"
    fund_after = get_fund(fund["id"])
    assert fund_after["reserved_cents"] == 0
    assert fund_after["available_cents"] == 1000


def test_award_activate_twice_returns_not_pending(api):
    """PRD 3.3: "the award must be `PENDING` (`ERR_AWARD_NOT_PENDING`)" — the
    state gate (pipeline stage 5) fires even when the OCC version presented is
    fresh.

    Design: Corner/endpoints/c_award_activate_twice_returns_not_pending
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    fund, award = setup_activated_award(
        site["id"], director["id"], member["id"], budget_cents=10_000,
        discount_pct=0.50, weekly_cap_cents=500, annual_cap_cents=1000,
    )
    fresh_fund = get_fund(fund["id"])
    res = api.activate_scholarship_award(
        award["id"], {"expected_fund_version": fresh_fund["version"]},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_AWARD_NOT_PENDING, expected_status=409)
    assert _get_award(api, member["id"], award["id"])["status"] == "ACTIVE"
    assert get_fund(fund["id"])["reserved_cents"] == 1000


def test_award_revoke_pending_returns_not_active(api):
    """PRD 3.3: "A `SiteDirector` revoking an award that is not `ACTIVE` is
    rejected with `ERR_AWARD_NOT_ACTIVE`".

    Design: Corner/endpoints/c_award_revoke_pending_returns_not_active
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    fund = create_fund(site["id"], 10_000)
    award = create_award(fund["id"], member["id"], director["id"])
    res = api.revoke_scholarship_award(award["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_AWARD_NOT_ACTIVE, expected_status=409)
    assert _get_award(api, member["id"], award["id"])["status"] == "PENDING"
    assert get_fund(fund["id"])["reserved_cents"] == 0


def test_occ_award_activate_stale_fund_version(api):
    """PRD 2.7: "activating a scholarship award requires the request to carry
    `expected_fund_version`, the client's last observed `version` of the parent
    scholarship fund. If the fund's current `version` has advanced beyond that
    value ... the activation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/c_occ_award_activate_stale_fund_version
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    fund = create_fund(site["id"], 100_000)
    observed = fund["version"]
    aw1 = create_award(fund["id"], member["id"], director["id"],
                       discount_pct=0.50, weekly_cap_cents=500,
                       annual_cap_cents=1000)
    aw2 = create_award(fund["id"], member["id"], director["id"],
                       discount_pct=0.25, weekly_cap_cents=500,
                       annual_cap_cents=1000)
    hdrs = director_headers(director)
    first = validate_success(
        api.activate_scholarship_award(
            aw1["id"], {"expected_fund_version": observed}, hdrs
        ),
        200,
    )
    assert first["status"] == "ACTIVE"
    fund_after = get_fund(fund["id"])
    assert fund_after["version"] == observed + 1, (
        "PRD Section 4: activation increments the fund's version by 1"
    )
    assert fund_after["reserved_cents"] == 1000

    res = api.activate_scholarship_award(
        aw2["id"], {"expected_fund_version": observed}, hdrs
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert _get_award(api, member["id"], aw2["id"])["status"] == "PENDING"
    assert get_fund(fund["id"])["reserved_cents"] == 1000, (
        "the rejected activation performs no partial mutation"
    )


def _setup_member_with_active_award(api):
    """PAID member; fund budget 50,000; award annual_cap 4,000 ACTIVATED
    (reserved 4,000 / available 46,000). Returns (site, director, member, fund,
    award)."""
    site, director = setup_site_with_director()
    member = _paid_member(api, site, director)
    fund, award = setup_activated_award(
        site["id"], director["id"], member["id"], budget_cents=50_000,
        discount_pct=0.50, weekly_cap_cents=5000, annual_cap_cents=4000,
    )
    return site, director, member, fund, award


def test_member_withdraw_revokes_award(api):
    """PRD 3.2: "every `PENDING` scholarship award of the member is
    `CANCELLED`; every `ACTIVE` award is `REVOKED`, which releases its
    remaining reservation back to the fund exactly as a manual revocation
    does (Section 3.3)".

    Design: Difficulty/transitive_cascade/member_withdraw_revokes_award_releases_fund_reservation
    """
    site, director, member, fund, award = _setup_member_with_active_award(api)
    withdrawn = validate_success(
        api.withdraw_member(member["id"], director_headers(director)), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_at"] is not None
    assert _get_award(api, member["id"], award["id"])["status"] == "REVOKED", (
        "the withdrawal cascade revokes the ACTIVE award"
    )


def test_member_withdraw_releases_fund_reservation(api):
    """PRD 3.3: "otherwise the award becomes `REVOKED`, the fund's
    `reserved_cents` shrinks by the award's `remaining_cap_cents`,
    `available_cents` is recomputed" and "the fund obeys a strict conservation
    invariant checked after every mutation: the budget always equals the sum of
    `available_cents`, `reserved_cents`, and `disbursed_cents`".

    Design: Difficulty/transitive_cascade/member_withdraw_revokes_award_releases_fund_reservation
    """
    site, director, member, fund, award = _setup_member_with_active_award(api)
    before = get_fund(fund["id"])
    assert before["reserved_cents"] == 4000
    assert before["available_cents"] == 46_000
    api.withdraw_member(member["id"], director_headers(director))
    after = get_fund(fund["id"])
    assert after["reserved_cents"] == 0
    assert after["disbursed_cents"] == 0
    assert after["available_cents"] == 50_000
    assert_fund_conservation(after)


def _setup_nested_min_scenario(api):
    """PAID member (weekly fee 5,000); fund budget 100,000; award discount
    0.60, weekly_cap 2,000, annual_cap 5,000, ACTIVATED. Each week the rounded
    discount is 3,000. Returns (site, director, member, fund, award)."""
    site, director = setup_site_with_director()
    member = _paid_member(api, site, director)
    fund, award = setup_activated_award(
        site["id"], director["id"], member["id"], budget_cents=100_000,
        discount_pct=0.60, weekly_cap_cents=2000, annual_cap_cents=5000,
    )
    return site, director, member, fund, award


def test_disbursement_nested_min_weekly_balances(api):
    """PRD 3.9: "The actual disbursement is then the smallest of three values:
    the award's `weekly_cap_cents`, its `remaining_cap_cents`, and the rounded
    discount amount." and "The member's `fee_balance_cents` rises by the gross
    minus the disbursement".

    Design: Difficulty/combinatorial_formula/scholarship_disbursement_nested_min_weekly_cap_then_annual_cap
    """
    site, director, member, fund, award = _setup_nested_min_scenario(api)
    # week 1 (Fri 2026-08-07): min(2000, 5000, 3000) = 2000 -> 2500+3000 = 5500
    accrue_friday(site["id"], director["id"], "2026-08-07")
    assert get_member(member["id"])["fee_balance_cents"] == 5500
    # week 2 (Fri 2026-08-14): min(2000, 3000, 3000) = 2000 -> 5500+3000 = 8500
    accrue_friday(site["id"], director["id"], "2026-08-14")
    assert get_member(member["id"])["fee_balance_cents"] == 8500
    # week 3 (Fri 2026-08-21): min(2000, 1000, 3000) = 1000 -> 8500+4000 = 12500
    accrue_friday(site["id"], director["id"], "2026-08-21")
    assert get_member(member["id"])["fee_balance_cents"] == 12_500


def test_disbursement_nested_min_award_exhaustion(api):
    """PRD 3.9: "The disbursement is added to the award's `disbursed_cents` and
    subtracted from its `remaining_cap_cents`, and the same amount moves from
    the fund's `reserved_cents` into its `disbursed_cents`" and "An award whose
    `remaining_cap_cents` reaches zero becomes `EXHAUSTED`."

    Design: Difficulty/combinatorial_formula/scholarship_disbursement_nested_min_weekly_cap_then_annual_cap
    """
    site, director, member, fund, award = _setup_nested_min_scenario(api)
    for friday in ("2026-08-07", "2026-08-14", "2026-08-21"):
        day = accrue_friday(site["id"], director["id"], friday)
        assert day["weekly_fees_accrued"] is True, (
            "closing a day on the site's fee-accrual weekday runs the accrual"
        )
    award_after = _get_award(api, member["id"], award["id"])
    assert award_after["disbursed_cents"] == 5000
    assert award_after["remaining_cap_cents"] == 0
    assert award_after["status"] == "EXHAUSTED"
    fund_after = get_fund(fund["id"])
    assert fund_after["reserved_cents"] == 0
    assert fund_after["disbursed_cents"] == 5000
    assert fund_after["available_cents"] == 95_000
    assert_fund_conservation(fund_after)


def _setup_conservation_scenario(api):
    """PAID member; fund budget 10,000; award discount 0.50, weekly_cap 5,000,
    annual_cap 6,000. Returns (site, director, member, fund, award)."""
    site, director = setup_site_with_director()
    member = _paid_member(api, site, director)
    fund = create_fund(site["id"], 10_000)
    award = create_award(fund["id"], member["id"], director["id"],
                         discount_pct=0.50, weekly_cap_cents=5000,
                         annual_cap_cents=6000)
    return site, director, member, fund, award


def test_fund_conservation_across_activate_and_accrual(api):
    """PRD 3.3: "the fund obeys a strict conservation invariant checked after
    every mutation: the budget always equals the sum of `available_cents`,
    `reserved_cents`, and `disbursed_cents`". PRD 3.3: "On success the fund's
    `reserved_cents` grows by the award's `annual_cap_cents`".

    Design: Difficulty/compensating_invariant/fund_conservation_across_activate_accrual_revoke
    """
    site, director, member, fund, award = _setup_conservation_scenario(api)
    activate_award(award["id"], director["id"], fund["version"])
    after_activate = get_fund(fund["id"])
    assert after_activate["reserved_cents"] == 6000
    assert after_activate["disbursed_cents"] == 0
    assert after_activate["available_cents"] == 4000
    assert_fund_conservation(after_activate)

    # Friday close disburses min(5000 cap, 6000 remaining, round(5000x0.5)=2500)
    accrue_friday(site["id"], director["id"], "2026-08-07")
    after_accrual = get_fund(fund["id"])
    assert after_accrual["reserved_cents"] == 3500
    assert after_accrual["disbursed_cents"] == 2500
    assert after_accrual["available_cents"] == 4000
    assert_fund_conservation(after_accrual)
    # member balance: 2,500 registration + 5,000 gross - 2,500 disbursed
    assert get_member(member["id"])["fee_balance_cents"] == 5000


def test_fund_conservation_after_revoke(api):
    """PRD 3.3: "Revocation releases money the other way. ... the award becomes
    `REVOKED`, the fund's `reserved_cents` shrinks by the award's
    `remaining_cap_cents`, `available_cents` is recomputed, and both versions
    increment." and the conservation invariant "checked after every mutation".

    Design: Difficulty/compensating_invariant/fund_conservation_across_activate_accrual_revoke
    """
    site, director, member, fund, award = _setup_conservation_scenario(api)
    activate_award(award["id"], director["id"], fund["version"])
    accrue_friday(site["id"], director["id"], "2026-08-07")

    revoked = validate_success(
        api.revoke_scholarship_award(award["id"], director_headers(director)), 200
    )
    assert revoked["status"] == "REVOKED"
    after_revoke = get_fund(fund["id"])
    # remaining cap 3,500 released from the reservation; disbursed stays
    assert after_revoke["reserved_cents"] == 0
    assert after_revoke["disbursed_cents"] == 2500
    assert after_revoke["available_cents"] == 7500
    assert_fund_conservation(after_revoke)
    assert after_revoke["budget_cents"] == 10_000, (
        "budget is unchanged across activate, accrual, and revoke"
    )


def test_accrual_input_set_excludes_withdrawn_member(api):
    """PRD 3.9: "The accrual processes the site's members whose status is
    `ACTIVE` or `SUSPENDED` and whose `approved_at` is no later than the end of
    the club day — withdrawn, denied, and still-applied members are excluded".

    Design: Corner/calculations/c_accrual_input_set_excludes_withdrawn_member
    """
    site, director = setup_site_with_director()
    member = _paid_member(api, site, director)
    assert member["fee_balance_cents"] == 2500
    withdrawn = validate_success(
        api.withdraw_member(member["id"], director_headers(director)), 200
    )
    version_at_withdraw = withdrawn["version"]

    day = accrue_friday(site["id"], director["id"], "2026-08-07")
    assert day["weekly_fees_accrued"] is True
    after = get_member(member["id"])
    assert after["fee_balance_cents"] == 2500, (
        "a WITHDRAWN member is excluded from the accrual input set"
    )
    assert after["version"] == version_at_withdraw, (
        "the close performs no mutation on an excluded member"
    )
