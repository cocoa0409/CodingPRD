"""Membership tiers, member accounts, payments, dues posting, and standing."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_member,
    assert_member_balance,
    close_ops_day,
    create_member,
    create_tier,
    get_member,
    is_valid_uuid,
    make_member_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMembershipTierCatalog:
    def test_member_creation_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "New members start in `ACTIVE` status with
        `account_balance_cents` at 0, `pending_dues_cents` at 0, `badge_level`
        of `NONE`, `solo_endorsed` false, and no `suspension_reason`."
        PRD §3.1: "A `ClubAdmin` enrolls each **Member** with a `full_name` and
        a `tier_id` referencing an existing tier; the optional `is_instructor`
        and `is_tow_pilot` flags, both defaulting to false, gate the member's
        ability to act as an `Instructor` or `TowPilot`."
        PRD §2.4: "Every primary resource carries a standard set of
        system-managed fields: `id`, a server-minted UUID with no type prefix".

        Design: Corner/entities/member_creation_applies_defaults_and_system_fields
        """
        tier = create_tier(tier_code="D0")
        resp = api.create_member({"full_name": "Defaults Member", "tier_id": tier["id"]}, ADMIN)
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["status"] == "ACTIVE"
        assert member["account_balance_cents"] == 0
        assert member["pending_dues_cents"] == 0
        assert member["solo_endorsed"] is False
        assert member["badge_level"] == "NONE"
        assert member["is_instructor"] is False
        assert member["is_tow_pilot"] is False
        assert member.get("suspension_reason") is None
        assert is_valid_uuid(member["id"]), "id is a server-minted UUID with no type prefix"

    def test_tier_unique_code_rejected(self, api):
        """PRD §3.1: "Reusing an existing `tier_code` is rejected with
        `ERR_UNIQUE_CONSTRAINT` (HTTP 409)."

        Design: Corner/entities/tier_unique_code_rejected
        """
        create_tier(
            tier_code="UNIQUE1", monthly_dues_cents=1000, included_tows_per_month=0
        )
        resp = api.create_tier(
            {
                "tier_code": "UNIQUE1",
                "monthly_dues_cents": 2000,
                "tow_fee_discount_pct": 0.1,
                "included_tows_per_month": 1,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUE_CONSTRAINT)

    def test_list_pagination_envelope_shape(self, api, club_admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/list_pagination_envelope_shape
        """
        tier = create_tier(tier_code="PG")
        for name in ("P1", "P2", "P3"):
            create_member(tier["id"], full_name=name)
        resp = api.list_members(club_admin_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert len(data) == 2, f"limit=2 must cap the page at 2 items, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        for item in data:
            assert_member(item)

    def test_get_missing_member_returns_404(self, api, club_admin_headers):
        """PRD §2.11: "Next, existence: every resource referenced by path or
        body — member, tier, aircraft, reservation, flight, tow slot, duty
        slot, availability window, progression record, retrieve — must exist,
        or the request fails with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/get_missing_resource_returns_404
        """
        resp = api.get_member(NON_EXISTENT_UUID, club_admin_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


class TestMidMonthTierChangeProration:
    """5000 -> 8000 dues on Aug 10 of a 31-day month: floor(5000*9/31) = 1451
    plus round_half_up(8000*22/31) = 5677 yields a 7128-cent pending charge."""

    def _setup_switcher(self):
        basic = create_tier(tier_code="BASIC", monthly_dues_cents=5000)
        premium = create_tier(tier_code="PREMIUM", monthly_dues_cents=8000)
        member = create_member(basic["id"], full_name="Switcher")
        set_clock("2026-08-10T09:00:00Z")
        return basic, premium, member

    def test_tier_change_parks_prorated_pending_dues(self, api):
        """PRD §3.1: "Let the change month's calendar length in UTC be the days
        in the month; the days billed to the old tier are the day-of-month of
        the change minus one, and the remainder of the month — including the
        change day itself, which bills to the **new** tier — is billed to the
        new tier. The blended charge is the old tier's monthly dues multiplied
        by the old-tier days and divided by the days in the month, that half
        **floored** to whole cents, plus the new tier's monthly dues multiplied
        by the new-tier days and divided by the days in the month, that half
        **rounded half up**."

        Design: Difficulty/dual_variant_calc/dues_forward_vs_prorated_divergence
        """
        _, premium, member = self._setup_switcher()
        resp = api.change_member_tier(member["id"], {"tier_id": premium["id"]}, ADMIN)
        validate_success(resp, 200)
        after = get_member(member["id"])
        assert after["pending_dues_cents"] == 7128, (
            "floor(5000*9/31)=1451 old-tier half plus round_half_up(8000*22/31)=5677 "
            f"new-tier half must park 7128, got {after['pending_dues_cents']}"
        )
        assert after["account_balance_cents"] == 0, (
            "the prorated charge is parked, not yet swept into the balance"
        )

    def test_ops_close_sweeps_pending_instead_of_forward(self, api):
        """PRD §3.1: "At the next ops-day close, a member carrying a nonzero
        `pending_dues_cents` is charged that pending amount **instead of** the
        ordinary forward dues debit for that month, and `pending_dues_cents`
        returns to 0."

        Design: Difficulty/dual_variant_calc/dues_forward_vs_prorated_divergence
        """
        _, premium, member = self._setup_switcher()
        api.change_member_tier(member["id"], {"tier_id": premium["id"]}, ADMIN)
        close_ops_day()
        after = get_member(member["id"])
        assert_member_balance(after, 7128)
        assert after["pending_dues_cents"] == 0


class TestArrearsSuspensionAndReinstatement:
    def test_payment_reinstates_arrears_suspension(self, api):
        """PRD §3.2: "The system path fires at the ops-day close: after dues
        posting, any member whose `account_balance_cents` is at or above the
        20,000-cent arrears threshold moves from `ACTIVE` to `SUSPENDED` with
        `suspension_reason` set to `ARREARS`."
        PRD §3.2: "A member suspended for `ARREARS` climbs back automatically:
        when a payment brings the post-payment balance below the 20,000-cent
        threshold, the member returns from `SUSPENDED` to `ACTIVE` and
        `suspension_reason` is cleared to null."

        Design: Corner/endpoints/payment_reinstates_arrears_suspension
        """
        tier = create_tier(tier_code="ARR", monthly_dues_cents=20000)
        member = create_member(tier["id"], full_name="Arrears Member")
        set_clock("2026-08-05T00:00:00Z")
        close_ops_day()
        suspended = get_member(member["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "ARREARS"
        assert suspended["account_balance_cents"] == 20000

        resp = api.record_payment(member["id"], {"amount_cents": 1}, ADMIN)
        validate_success(resp, 201)
        reinstated = get_member(member["id"])
        assert_member_balance(reinstated, 19999)
        assert reinstated["status"] == "ACTIVE", (
            "19999 < 20000 must reinstate an ARREARS suspension automatically"
        )
        assert reinstated["suspension_reason"] is None


class TestPaymentValidationPriority:
    """A 60,000-cent payment to a zero-balance RESIGNED member violates both
    the member-standing gate and the credit cap; the state gate is earlier in
    the fixed validation order and must win."""

    def _setup_resigned_member(self, api):
        tier = create_tier(tier_code="PRIO", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="Prio Pilot")
        resp = api.resign_member(member["id"], make_member_headers(member["id"]))
        validate_success(resp, 200)
        return member

    def test_payment_on_resigned_member_rejected_state_gate(self, api):
        """PRD §3.2: "A `RESIGNED` member may not make payments at all: the
        attempt fails with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."
        PRD §2.11: "Then state gates in this order: the target resource's own
        state permits the operation (`ERR_INVALID_STATE`, HTTP 409);
        member-side standing — pilot, instructor, or crew must be `ACTIVE` for
        flight-side operations, a paying member must not be `RESIGNED`, a
        student must be `ACTIVE` at solo signoff (`ERR_MEMBER_NOT_ACTIVE`)".
        PRD §2.11: "Fiscal bounds follow (`ERR_CREDIT_CAP_EXCEEDED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_payment_on_resigned_member
        """
        member = self._setup_resigned_member(api)
        resp = api.record_payment(member["id"], {"amount_cents": 60000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

    def test_rejected_payment_leaves_balance_unchanged(self, api):
        """PRD §3.2: "A `RESIGNED` member may not make payments at all: the
        attempt fails with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."
        PRD §2.6: "a payment that would push an account deeper into credit
        than 50,000 cents — that is, one that would take
        `account_balance_cents` below −50,000 — is rejected with
        `ERR_CREDIT_CAP_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_payment_on_resigned_member
        """
        member = self._setup_resigned_member(api)
        resp = api.record_payment(member["id"], {"amount_cents": 60000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)
        assert_member_balance(get_member(member["id"]), 0)


class TestOpsDayCloseDuesEpoch:
    def test_second_close_same_month_posts_no_dues(self, api):
        """PRD §3.9: "Dues post on the **first** close executed within each UTC
        calendar month, under the forward variant of the dues rule: every
        member whose status is `ACTIVE` or `SUSPENDED` — `RESIGNED` members
        are excluded — is debited their tier's `monthly_dues_cents`."

        Design: Corner/cross_cutting_layers/ops_day_close_epoch_scheduled_actions
        """
        tier = create_tier(tier_code="EP", monthly_dues_cents=7000)
        member = create_member(tier["id"], full_name="Epoch Member")
        set_clock("2026-08-05T00:00:00Z")
        close_ops_day()
        assert_member_balance(get_member(member["id"]), 7000)
        close_ops_day()
        assert_member_balance(get_member(member["id"]), 7000), (
            "the second close in the same UTC month must not post dues again"
        )
