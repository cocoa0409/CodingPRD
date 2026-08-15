"""Enrollment, eligibility tiers, fee ledger, and guardians."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    accrue_friday,
    apply_for_membership,
    assert_member,
    create_active_member,
    create_guardian,
    create_member_payload,
    decide_member,
    director_headers,
    get_member,
    open_club_day,
    setup_site_with_director,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_member_create_defaults_and_computed(api):
    """PRD 3.2: "A new member starts in `APPLIED` status with `fee_balance_cents`
    at zero, `behavior_points` at zero, `discipline_watch` false, and
    `eligibility_tier`, `weekly_fee_cents`, `approved_at`, and `withdrawn_at`
    all null until a decision." and "an optional `walker_ok` flag, defaulting
    to false, records whether the child may leave on foot."

    Design: Corner/entities/c_member_create_defaults_and_computed
    """
    site, director = setup_site_with_director()
    res = api.create_member(
        create_member_payload(site["id"], legal_name="New Kid", grade=6,
                              household_size=2),
        director_headers(director),
    )
    member = validate_success(res, 201)
    assert_member(member)
    assert member["status"] == "APPLIED"
    assert member["walker_ok"] is False
    assert member["fee_balance_cents"] == 0
    assert member["behavior_points"] == 0
    assert member["discipline_watch"] is False
    assert member["eligibility_tier"] is None
    assert member["weekly_fee_cents"] is None


def test_member_create_missing_required_and_unknown_field_rejected(api):
    """PRD 2.8: "Required fields must be present, enum values must be in range,
    unknown fields are rejected, integers must be positive where required, and
    the rotation-assignment discipline ... is enforced here; failures yield
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/c_member_create_missing_required_and_unknown_field_rejected
    """
    site, director = setup_site_with_director()
    hdrs = director_headers(director)

    missing = create_member_payload(site["id"], legal_name="No Income")
    del missing["household_income_cents"]
    res = api.create_member(missing, hdrs)
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    extra = create_member_payload(site["id"], legal_name="Extra Field")
    extra["eligibility_tier"] = "FREE"
    res = api.create_member(extra, hdrs)
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    data, meta = validate_paginated(
        api.list_members(site["id"], TEST_USERS["platform_admin_headers"])
    )
    assert meta["total_count"] == 0, "no Member may be created by rejected payloads"


def test_member_get_not_found(api, platform_admin_headers):
    """PRD 2.8: "Path identifiers are validated left to right, then body
    foreign-key fields ... must resolve to existing rows; the first
    unresolvable reference yields `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/c_member_get_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_members_list_pagination_and_filter(api, platform_admin_headers):
    """PRD 2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD 3.2: "Member rosters can be listed with optional `status` and
    `eligibility_tier` filters."

    Design: Corner/entities/c_members_list_pagination_and_filter
    """
    site, director = setup_site_with_director()
    hdrs = director_headers(director)
    m1 = apply_for_membership(site["id"], director["id"], legal_name="Kid A")
    m2 = apply_for_membership(site["id"], director["id"], legal_name="Kid B",
                              date_of_birth="2012-02-01")
    m3 = apply_for_membership(site["id"], director["id"], legal_name="Kid C",
                              date_of_birth="2012-03-01")
    decide_member(m1["id"], director["id"], "APPROVE")
    decide_member(m2["id"], director["id"], "APPROVE")
    decide_member(m3["id"], director["id"], "DENY")

    page1, meta1 = validate_paginated(
        api.list_members(site["id"], platform_admin_headers,
                         params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    # PRD 2.3: "every list endpoint returns resources sorted by `created_at`
    # in ascending order."
    assert [m["id"] for m in page1] == [m1["id"], m2["id"]]

    page2, meta2 = validate_paginated(
        api.list_members(site["id"], platform_admin_headers,
                         params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    active, meta3 = validate_paginated(
        api.list_members(site["id"], platform_admin_headers,
                         params={"status": "ACTIVE"})
    )
    assert len(active) == 2
    assert meta3["total_count"] == 2
    assert all(m["status"] == "ACTIVE" for m in active)


def test_guardian_create_with_bogus_member_returns_not_found(api):
    """PRD 2.8: "Path identifiers are validated left to right, then body
    foreign-key fields — `site_id`, `member_id`, `fund_id`, `club_day_id`,
    `area_id`, `route_id`, `new_area_id` — must resolve to existing rows; the
    first unresolvable reference yields `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/c_guardian_create_with_bogus_member_returns_not_found
    """
    site, director = setup_site_with_director()
    res = api.create_guardian(
        {"member_id": NON_EXISTENT_UUID, "full_name": "Jane Doe",
         "relation": "mother"},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_decide_twice_returns_member_not_applied(api):
    """PRD 3.2: "Decisions belong to the `SiteDirector`, who supplies a
    `decision` of `APPROVE` or `DENY`; deciding a member not currently
    `APPLIED` is rejected with `ERR_MEMBER_NOT_APPLIED`."

    Design: Corner/state_machines/c_decide_twice_returns_member_not_applied
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    res = api.decide_member(member["id"], {"decision": "DENY"},
                            director_headers(director))
    validate_error(res, ApiErrorId.ERR_MEMBER_NOT_APPLIED, expected_status=409)
    after = get_member(member["id"])
    assert after["status"] == "ACTIVE"
    assert after["fee_balance_cents"] == 2500, (
        "the rejected second decision must not re-run approval side effects"
    )


def test_guardian_revoke_twice_returns_not_active(api):
    """PRD 3.2: "revocation requires the guardian to be `ACTIVE` (otherwise
    `ERR_GUARDIAN_NOT_ACTIVE`) and moves them to `REVOKED`, after which their
    `full_name` no longer authorizes pickup."

    Design: Corner/state_machines/c_guardian_revoke_twice_returns_not_active
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    guardian = create_guardian(member["id"], director["id"])
    hdrs = director_headers(director)
    revoked = validate_success(api.revoke_guardian(guardian["id"], hdrs), 200)
    assert revoked["status"] == "REVOKED"
    res = api.revoke_guardian(guardian["id"], hdrs)
    validate_error(res, ApiErrorId.ERR_GUARDIAN_NOT_ACTIVE, expected_status=409)


def test_fee_payment_overpay_rejected(api):
    """PRD 3.2: "an `amount_cents` greater than the current `fee_balance_cents`
    is rejected with `ERR_OVERPAYMENT` (422). A successful payment subtracts the
    amount from the balance and increments the member's `version`."

    Design: Corner/endpoints/c_fee_payment_overpay_rejected
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    assert member["fee_balance_cents"] == 2500
    res = api.post_fee_payment(
        member["id"],
        {"amount_cents": 3000, "expected_member_version": member["version"]},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)
    assert get_member(member["id"])["fee_balance_cents"] == 2500


def test_occ_fee_payment_stale_member_version(api):
    """PRD 2.7: "posting a fee payment requires `expected_member_version`, the
    client's last observed `version` of the member. If the member's `version`
    has advanced — because a weekly accrual or an earlier payment has
    legitimately moved `fee_balance_cents` — the payment is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/c_occ_fee_payment_stale_member_version
    """
    site, director = setup_site_with_director()
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    observed_version = member["version"]
    hdrs = director_headers(director)

    first = validate_success(
        api.post_fee_payment(
            member["id"],
            {"amount_cents": 1000, "expected_member_version": observed_version},
            hdrs,
        ),
        200,
    )
    assert first["fee_balance_cents"] == 1500
    assert first["version"] == observed_version + 1, (
        "PRD 3.2: a successful payment increments the member's version"
    )

    res = api.post_fee_payment(
        member["id"],
        {"amount_cents": 1000, "expected_member_version": observed_version},
        hdrs,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_member(member["id"])["fee_balance_cents"] == 1500


def test_immediate_read_after_write(api, platform_admin_headers):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD 2.5: "no resource in this system omits any of the four" (id,
    created_at, updated_at, version).

    Design: Corner/consistency_model/c_immediate_read_after_write
    """
    site, director = setup_site_with_director()
    created = apply_for_membership(site["id"], director["id"], legal_name="Kid A")
    read = validate_success(api.get_member(created["id"], platform_admin_headers), 200)
    assert read["id"] == created["id"]
    assert read["legal_name"] == "Kid A"
    assert read["status"] == "APPLIED"
    assert read["site_id"] == site["id"]
    assert read["version"] == created["version"]


def test_eligibility_income_at_free_limit_takes_free(api):
    """PRD 3.2: "the `FREE` limit for a household is 1,500,000 cents plus
    500,000 cents for each household member beyond the first" and "Income at or
    below the `FREE` limit yields `eligibility_tier` `FREE`". PRD 2.6: "an
    income exactly equal to an eligibility limit takes the lower-priced tier".

    Design: Difficulty/boundary_precision_check/eligibility_income_exactly_at_free_limit_inclusive
    """
    site, director = setup_site_with_director()
    # free_limit(4) = 1,500,000 + 3 * 500,000 = 3,000,000 — income exactly at it
    member = apply_for_membership(
        site["id"], director["id"], legal_name="Edge Free",
        household_size=4, household_income_cents=3_000_000,
    )
    decided = decide_member(member["id"], director["id"], "APPROVE")
    assert decided["eligibility_tier"] == "FREE"
    # PRD 3.2: "The weekly fee is then the site's `base_weekly_fee_cents`
    # multiplied by the tier multiplier — zero for `FREE`..."
    assert decided["weekly_fee_cents"] == 0


def test_eligibility_income_one_cent_over_free_limit_takes_reduced(api):
    """PRD 3.2: "Income at or below the `FREE` limit yields `eligibility_tier`
    `FREE`; otherwise income at or below the `REDUCED` limit yields `REDUCED`;
    anything higher yields `PAID`." and "one-half for `REDUCED`".

    Design: Difficulty/boundary_precision_check/eligibility_income_exactly_at_free_limit_inclusive
    """
    site, director = setup_site_with_director()
    # one cent over free_limit(4) == 3,000,000
    member = apply_for_membership(
        site["id"], director["id"], legal_name="Edge Reduced",
        household_size=4, household_income_cents=3_000_001,
    )
    decided = decide_member(member["id"], director["id"], "APPROVE")
    assert decided["eligibility_tier"] == "REDUCED"
    assert decided["weekly_fee_cents"] == 2500, (
        "round_half_up(5000 x 0.5) == 2500"
    )


def test_tier_reduced_paid_boundary(api):
    """PRD 3.2: "the `REDUCED` limit is 2,000,000 cents plus 650,000 cents for
    each member beyond the first" and "Income at or below the `FREE` limit
    yields `eligibility_tier` `FREE`; otherwise income at or below the
    `REDUCED` limit yields `REDUCED`; anything higher yields `PAID`."

    Design: Corner/calculations/c_tier_reduced_paid_boundary
    """
    site, director = setup_site_with_director()
    # reduced_limit(1) == 2,000,000 — inclusive; one cent over is PAID
    m_red = apply_for_membership(
        site["id"], director["id"], legal_name="Edge Red",
        household_size=1, household_income_cents=2_000_000,
    )
    m_paid = apply_for_membership(
        site["id"], director["id"], legal_name="Edge Paid",
        household_size=1, household_income_cents=2_000_001,
    )
    red = decide_member(m_red["id"], director["id"], "APPROVE")
    paid = decide_member(m_paid["id"], director["id"], "APPROVE")
    assert red["eligibility_tier"] == "REDUCED"
    assert red["weekly_fee_cents"] == 2500
    assert paid["eligibility_tier"] == "PAID"
    assert paid["weekly_fee_cents"] == 5000
    # PRD 3.2: "The one-time `registration_fee_cents` is added to
    # `fee_balance_cents`"
    assert red["fee_balance_cents"] == 2500
    assert paid["fee_balance_cents"] == 2500


def _setup_withdrawn_member_in_arrears(api):
    """PAID member, three Friday accruals (balance 17,500 > 10,000 limit),
    then withdrawn; a fresh club day opened on 2026-08-24."""
    site, director = setup_site_with_director()
    member = create_active_member(
        site["id"], director["id"], legal_name="Pay Kid",
        date_of_birth="2011-01-01", grade=8, household_income_cents=5_000_000,
    )
    for friday in ("2026-08-07", "2026-08-14", "2026-08-21"):
        accrue_friday(site["id"], director["id"], friday)
    withdrawn = validate_success(
        api.withdraw_member(member["id"], director_headers(director)), 200
    )
    assert withdrawn["fee_balance_cents"] == 17_500
    day = open_club_day(site["id"], director["id"], "2026-08-24")
    return site, director, member, day


def test_signin_referential_error_beats_fee_arrears(api):
    """PRD 2.8: "Every request is validated against a fixed, ten-stage
    pipeline, and the first failing stage determines the error returned." —
    referenced-entity state (stage 8, `ERR_MEMBER_NOT_ACTIVE`) precedes money
    gates (stage 10, `ERR_FEE_ARREARS_EXCEEDED`).

    Design: Difficulty/priority_pair_validation_conflict/signin_member_state_referential_beats_fee_arrears_fiscal
    """
    site, director, member, day = _setup_withdrawn_member_in_arrears(api)
    res = api.create_attendance_record(
        {"club_day_id": day["id"], "member_id": member["id"]},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_MEMBER_NOT_ACTIVE, expected_status=409)
    assert res.json()["data"]["error_id"] != "ERR_FEE_ARREARS_EXCEEDED", (
        "the referential member-state gate must win over the fiscal gate"
    )


def test_signin_referential_conflict_creates_no_record(api):
    """PRD 3.4: "the member must be `ACTIVE`, which is how suspensions
    physically bar entry (`ERR_MEMBER_NOT_ACTIVE`)". A rejected sign-in leaves
    no record and does not move the day's counters.

    Design: Difficulty/priority_pair_validation_conflict/signin_member_state_referential_beats_fee_arrears_fiscal
    """
    site, director, member, day = _setup_withdrawn_member_in_arrears(api)
    api.create_attendance_record(
        {"club_day_id": day["id"], "member_id": member["id"]},
        director_headers(director),
    )
    data, meta = validate_paginated(
        api.list_day_attendance(day["id"], TEST_USERS["platform_admin_headers"])
    )
    assert meta["total_count"] == 0
    day_after = validate_success(
        api.get_club_day(day["id"], TEST_USERS["platform_admin_headers"]), 200
    )
    assert day_after["present_count"] == 0
    assert get_member(member["id"])["fee_balance_cents"] == 17_500


def test_signin_arrears_boundary_exactly_at_max_allowed(api):
    """PRD 3.4: "the member's `fee_balance_cents` must not exceed the site's
    `max_arrears_cents`, with a balance exactly equal to the limit still
    allowed (`ERR_FEE_ARREARS_EXCEEDED`, 402)."

    Design: Corner/validations/c_signin_arrears_boundary_exactly_at_max_allowed
    """
    site, director = setup_site_with_director()
    m1 = create_active_member(
        site["id"], director["id"], legal_name="Pay One",
        date_of_birth="2011-01-01", grade=8, household_income_cents=5_000_000,
    )
    m2 = create_active_member(
        site["id"], director["id"], legal_name="Pay Two",
        date_of_birth="2011-02-01", grade=8, household_income_cents=5_000_000,
    )
    for friday in ("2026-08-07", "2026-08-14", "2026-08-21"):
        accrue_friday(site["id"], director["id"], friday)
    # both balances now 2,500 + 3 x 5,000 = 17,500; pay m1 down to the limit
    fresh = get_member(m1["id"])
    paid = validate_success(
        api.post_fee_payment(
            m1["id"],
            {"amount_cents": 7500, "expected_member_version": fresh["version"]},
            director_headers(director),
        ),
        200,
    )
    assert paid["fee_balance_cents"] == 10_000

    day = open_club_day(site["id"], director["id"], "2026-08-24")
    hdrs = director_headers(director)
    ok = validate_success(
        api.create_attendance_record(
            {"club_day_id": day["id"], "member_id": m1["id"]}, hdrs
        ),
        201,
    )
    assert ok["status"] == "ON_SITE", "balance == max_arrears must sign in"

    res = api.create_attendance_record(
        {"club_day_id": day["id"], "member_id": m2["id"]}, hdrs
    )
    validate_error(res, ApiErrorId.ERR_FEE_ARREARS_EXCEEDED, expected_status=402)
