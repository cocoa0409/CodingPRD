"""Visit check-in: allowance arithmetic, the frequency gate, the rolling visit
cap, client discipline, and the voucher quota carryover recursion."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_line,
    assert_client_visit,
    checkin_visit,
    create_partner,
    issue_voucher,
    make_referral_partner_headers,
    register_client,
    set_clock,
    setup_sorting_staff,
    setup_stocked_items,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]

GOOD_TOPS = {"category": "ADULT_TOPS", "season": "ALL_SEASON", "quality_grade": "GOOD"}


class TestAllowanceArithmetic:
    def test_allowance_constants_hardship_and_single(self, api):
        """PRD: "The base allowance is 8 items, plus 2 additional items for each
        household member beyond the first, capped at 16 items. For a client in
        the `HARDSHIP` tier, that capped base is then multiplied by 1.5 and
        rounded half up to a whole number of items."

        Design: Corner/calculations/allowance_constants_hardship_and_single
        """
        staff = setup_sorting_staff()
        hardship = register_client("H", 2, "HARDSHIP", staff["headers"])
        single = register_client("S", 1, None, staff["headers"])

        visit_h = checkin_visit(hardship["id"], staff["headers"])
        visit_s = checkin_visit(single["id"], staff["headers"])
        assert_client_visit(visit_h)
        assert visit_h["general_allowance"] == 15, (
            "round_half_up(min(16, 8 + 2) * 1.5) = 15")
        assert visit_s["general_allowance"] == 8, "single-member household base"

    def test_hardship_tier_with_voucher_hits_hard_visit_cap(self, api):
        """PRD: "The base allowance is 8 items, plus 2 additional items for each
        household member beyond the first, capped at 16 items. For a client in
        the `HARDSHIP` tier, that capped base is then multiplied by 1.5 and
        rounded half up to a whole number of items. When a voucher is redeemed
        on the visit, its `bonus_items` are added on top — the amount folded in
        is recorded as `voucher_bonus_applied` (0 when no voucher is redeemed) —
        and the final `general_allowance` is the smaller of that sum and the
        hard ceiling of 24 items per visit."

        Design: Difficulty/combinatorial_formula/visit_allowance_nested_min_tier_voucher
        """
        staff = setup_sorting_staff()
        partner = create_partner("Agency A", 10)
        client = register_client("A", 4, "HARDSHIP", staff["headers"])
        voucher = issue_voucher(partner, client["id"], bonus_items=3,
                                expires_at="2026-09-01T00:00:00Z")

        visit = checkin_visit(client["id"], staff["headers"],
                              voucher_id=voucher["id"])
        assert visit["general_allowance"] == 24, (
            "min(24, round_half_up(min(16, 8+2*3) * 1.5) + 3) = min(24, 21+3)")
        assert visit["voucher_bonus_applied"] == 3

    def test_large_household_clamps_at_household_cap(self, api):
        """PRD: "The base allowance is 8 items, plus 2 additional items for each
        household member beyond the first, capped at 16 items."
        PRD: "When a voucher is redeemed on the visit, its `bonus_items` are
        added on top — the amount folded in is recorded as `voucher_bonus_applied`
        (0 when no voucher is redeemed)"

        Design: Difficulty/combinatorial_formula/visit_allowance_nested_min_tier_voucher
        """
        staff = setup_sorting_staff()
        client = register_client("B", 10, None, staff["headers"])

        visit = checkin_visit(client["id"], staff["headers"])
        assert visit["general_allowance"] == 16, "min(24, min(16, 8 + 2*9)) = 16"
        assert visit["voucher_bonus_applied"] == 0


class TestClientDiscipline:
    def test_client_suspend_blocks_checkin(self, api):
        """PRD: "A `SUSPENDED` client cannot be checked in for a new visit and
        cannot be named as the recipient of a newly issued voucher — both
        attempts fail with `ERR_CLIENT_NOT_ACTIVE` — while a visit already
        `CHECKED_IN` when the suspension lands is unaffected and may finish
        normally."
        PRD: "suspending moves an `ACTIVE` client to `SUSPENDED`, and
        reinstating returns a `SUSPENDED` client to `ACTIVE`; each requires the
        matching current state (otherwise `ERR_INVALID_STATE`) and each
        increments `version`."

        Design: Corner/state_machines/client_suspend_blocks_checkin
        """
        staff = setup_sorting_staff()
        client = register_client("C", 2, None, staff["headers"])

        validate_success(api.suspend_client(client["id"], ADMIN), 200)
        resp = api.checkin_visit(client["id"], {}, staff["headers"])
        validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE)

        validate_success(api.reinstate_client(client["id"], ADMIN), 200)
        visit = validate_success(api.checkin_visit(client["id"], {}, staff["headers"]),
                                 201)
        assert visit["status"] == "CHECKED_IN"


class TestCooldownBoundary:
    def test_checkin_one_second_short_of_cooldown_rejected(self, api):
        """PRD: "Then the frequency gate: at least 14 full days must have elapsed
        since the client's `last_checkout_at` — the boundary is inclusive, so a
        client whose last checkout was exactly 14 days earlier may check in —
        and a first-ever visit passes this arm automatically; failure is
        `ERR_VISIT_COOLDOWN_ACTIVE`."

        Design: Difficulty/boundary_precision_check/cooldown_exactly_14_days_allowed
        """
        env = setup_stocked_items([dict(GOOD_TOPS)], zone_code="ZB", capacity_items=10)
        headers = env["staff"]["headers"]
        set_clock("2026-08-01T10:00:00Z")
        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)
        add_line(visit["id"], env["items"][0]["id"], headers)
        validate_success(api.checkout_visit(visit["id"], headers), 200)

        set_clock("2026-08-15T09:59:59Z")
        resp = api.checkin_visit(client["id"], {}, headers)
        validate_error(resp, ApiErrorId.ERR_VISIT_COOLDOWN_ACTIVE)

    def test_checkin_exactly_fourteen_days_allowed(self, api):
        """PRD: "Then the frequency gate: at least 14 full days must have elapsed
        since the client's `last_checkout_at` — the boundary is inclusive, so a
        client whose last checkout was exactly 14 days earlier may check in —
        and a first-ever visit passes this arm automatically; failure is
        `ERR_VISIT_COOLDOWN_ACTIVE`."

        Design: Difficulty/boundary_precision_check/cooldown_exactly_14_days_allowed
        """
        env = setup_stocked_items([dict(GOOD_TOPS)], zone_code="ZB", capacity_items=10)
        headers = env["staff"]["headers"]
        set_clock("2026-08-01T10:00:00Z")
        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)
        add_line(visit["id"], env["items"][0]["id"], headers)
        validate_success(api.checkout_visit(visit["id"], headers), 200)

        set_clock("2026-08-15T10:00:00Z")
        visit2 = validate_success(api.checkin_visit(client["id"], {}, headers), 201)
        assert visit2["status"] == "CHECKED_IN", "exactly 14 days later is allowed"


class TestVoucherWaivesCooldown:
    def test_voucher_waives_cooldown(self, api):
        """PRD: "A voucher whose `waives_frequency` flag is true overrides only
        the 14-day cooldown; the 30-day visit cap and the item caps are never
        waived."

        Design: Corner/validations/voucher_waives_cooldown
        """
        env = setup_stocked_items([dict(GOOD_TOPS)], zone_code="ZWC", capacity_items=5)
        headers = env["staff"]["headers"]
        partner = create_partner("Agency W", 3)
        client = register_client("C", 2, None, headers)
        voucher = issue_voucher(partner, client["id"], bonus_items=1,
                                expires_at="2026-12-01T00:00:00Z",
                                waives_frequency=True)
        visit1 = checkin_visit(client["id"], headers)
        add_line(visit1["id"], env["items"][0]["id"], headers)
        validate_success(api.checkout_visit(visit1["id"], headers), 200)

        resp = api.checkin_visit(client["id"], {}, headers)
        validate_error(resp, ApiErrorId.ERR_VISIT_COOLDOWN_ACTIVE)

        visit2 = validate_success(
            api.checkin_visit(client["id"], {"voucher_id": voucher["id"]}, headers),
            201)
        assert visit2["status"] == "CHECKED_IN", (
            "waives_frequency=true bypasses the cooldown")


class TestRollingVisitCap:
    def test_visit_limit_3_per_30d(self, api):
        """PRD: "Next, the rolling visit cap: the client's `visits_in_30d` must
        be fewer than 3, or the check-in fails with `ERR_VISIT_LIMIT_REACHED`."
        PRD: "A voucher whose `waives_frequency` flag is true overrides only the
        14-day cooldown; the 30-day visit cap and the item caps are never
        waived."

        Design: Corner/validations/visit_limit_3_per_30d
        """
        env = setup_stocked_items([dict(GOOD_TOPS) for _ in range(3)],
                                  zone_code="ZVL", capacity_items=10)
        headers = env["staff"]["headers"]
        partner = create_partner("Agency V", 5)
        client = register_client("C", 2, None, headers)
        vouchers = [
            issue_voucher(partner, client["id"], bonus_items=1,
                          expires_at="2026-12-01T00:00:00Z", waives_frequency=True)
            for _ in range(4)
        ]

        last_allowance = None
        for index in range(3):
            visit = checkin_visit(client["id"], headers,
                                  voucher_id=vouchers[index]["id"])
            last_allowance = visit["general_allowance"]
            add_line(visit["id"], env["items"][index]["id"], headers)
            validate_success(api.checkout_visit(visit["id"], headers), 200)
        assert last_allowance == 11, "hh2 base 10 + voucher bonus 1"

        resp = api.checkin_visit(client["id"], {"voucher_id": vouchers[3]["id"]},
                                 headers)
        validate_error(resp, ApiErrorId.ERR_VISIT_LIMIT_REACHED)


class TestVoucherQuota:
    def test_voucher_quota_exhausted_boundary(self, api):
        """PRD: "Issuance is permitted only while `vouchers_issued_current_month`
        is still below `current_month_quota`; an exhausted quota rejects the
        issuance with `ERR_VOUCHER_QUOTA_EXHAUSTED`."

        Design: Corner/validations/voucher_quota_exhausted_boundary
        """
        partner = create_partner("Agency Q", 1)
        client = register_client("C", 2)

        first = issue_voucher(partner, client["id"], bonus_items=1,
                              expires_at="2026-12-01T00:00:00Z")
        assert first["status"] == "ISSUED", "0 < 1: the first voucher fits the quota"

        resp = api.issue_voucher(
            partner["id"],
            {"client_id": client["id"], "bonus_items": 1,
             "expires_at": "2026-12-01T00:00:00Z"},
            make_referral_partner_headers(partner["id"]))
        validate_error(resp, ApiErrorId.ERR_VOUCHER_QUOTA_EXHAUSTED)

    def test_quota_carryover_into_second_month(self, api):
        """PRD: "For the anchor month, the carryover is 0. For every month after
        the anchor, the carryover is the smaller of 5 and whatever remains of the
        previous month's effective quota after that month's issuances — floored
        at zero so a deficit never propagates. The effective quota for a month is
        the base allotment plus that month's carryover."
        PRD: "Issuance counting is permanent: `vouchers_issued_current_month`
        counts every voucher created in the clock's current UTC month regardless
        of later status, and the partner's `current_month_quota` is the effective
        quota computed for that month."

        Design: Difficulty/combinatorial_formula/voucher_quota_carryover_recursive
        """
        partner = create_partner("Agency C", 10)
        client = register_client("C", 2)
        for _ in range(7):
            issue_voucher(partner, client["id"], bonus_items=1,
                          expires_at="2027-01-01T00:00:00Z")

        set_clock("2026-09-01T00:00:00Z")
        partner = validate_success(api.get_referral_partner(partner["id"], ADMIN), 200)
        assert partner["current_month_quota"] == 13, "10 + min(5, 10 - 7)"
        assert partner["vouchers_issued_current_month"] == 0, (
            "the counter counts only the clock's current UTC month")

    def test_quota_carryover_chains_into_third_month(self, api):
        """PRD: "The evaluation order is pinned — months are walked in ascending
        order from the anchor month to the current month, fully computing each
        prior month's quota and issuance before deriving the next month's
        carryover."
        PRD: "For every month after the anchor, the carryover is the smaller of 5
        and whatever remains of the previous month's effective quota after that
        month's issuances — floored at zero so a deficit never propagates."

        Design: Difficulty/combinatorial_formula/voucher_quota_carryover_recursive
        """
        partner = create_partner("Agency C", 10)
        client = register_client("C", 2)
        for _ in range(7):
            issue_voucher(partner, client["id"], bonus_items=1,
                          expires_at="2027-01-01T00:00:00Z")

        set_clock("2026-09-01T00:00:00Z")
        partner = validate_success(api.get_referral_partner(partner["id"], ADMIN), 200)
        assert partner["current_month_quota"] == 13
        for _ in range(12):
            issue_voucher(partner, client["id"], bonus_items=1,
                          expires_at="2027-01-01T00:00:00Z")

        set_clock("2026-10-01T00:00:00Z")
        partner = validate_success(api.get_referral_partner(partner["id"], ADMIN), 200)
        assert partner["current_month_quota"] == 11, "10 + min(5, 13 - 12)"
        assert partner["vouchers_issued_current_month"] == 0
