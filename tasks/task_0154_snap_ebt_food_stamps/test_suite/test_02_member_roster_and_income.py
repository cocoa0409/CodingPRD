"""Member roster, deactivation, and income aggregate recomputation.

Covers PRD §3.2 (composition + computed aggregates) and §2.8 (cascade
recompute on member mutation).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_NOT_FOUND, ERR_VALIDATION,
    TEST_USERS,
    assert_member, assert_household,
    create_household, add_member, setup_basic_household,
    dob_for_age,
    STANDARD_DEDUCTION_TABLE, EXCESS_SHELTER_CAP_CENTS,
)


CASEWORKER = TEST_USERS["caseworker_headers"]


class TestCreateMember:
    def test_create_member_minimal_returns_201(self, api):
        """PRD §3.2: "A new `Member` requires `full_name` (1–100 characters)
        and `date_of_birth`; flags `is_disabled` and `is_pregnant` default to
        false, and `earned_income_cents` and `unearned_income_cents` default to 0."

        Claim: minimal payload yields a Member with all defaults applied.
        """
        hh = create_household()
        member = add_member(hh["id"])
        assert_member(member)
        assert member["is_disabled"] is False
        assert member["is_pregnant"] is False
        assert member["earned_income_cents"] == 0
        assert member["unearned_income_cents"] == 0
        assert member["status"] == "ACTIVE"

    @pytest.mark.parametrize("bad_name", ["", "x" * 101])
    def test_create_member_bad_name_rejected(self, api, bad_name):
        """PRD §3.2: "`full_name` (1–100 characters)."

        Claim: empty or over-length full_name yields ERR_VALIDATION.
        """
        hh = create_household()
        resp = api.create_member(
            hh["id"],
            {"full_name": bad_name, "date_of_birth": "1990-01-01"},
            CASEWORKER,
        )
        validate_error(resp, ERR_VALIDATION)

    def test_create_member_under_unknown_household_returns_404(self, api):
        """PRD §2.7: "if `/households/{id}/members/{memberId}` is requested
        with an unknown `id`, the response is `ERR_NOT_FOUND` against the
        household."

        Claim: unknown household id on member creation yields ERR_NOT_FOUND.
        """
        resp = api.create_member(
            NON_EXISTENT_UUID, {"full_name": "A", "date_of_birth": "1990-01-01"},
            CASEWORKER,
        )
        validate_error(resp, ERR_NOT_FOUND)


class TestHouseholdAggregatesRecompute:
    def test_household_size_increments_on_member_add(self, api):
        """PRD §3.2: "The `household_size` is the count of those active members."

        Claim: adding an active member bumps household_size by 1.
        """
        hh = create_household()
        assert hh["household_size"] == 0
        add_member(hh["id"], full_name="A", date_of_birth=dob_for_age(30))
        re_read = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re_read["household_size"] == 1

    def test_gross_income_sums_over_active_members(self, api):
        """PRD §3.2: "The `gross_monthly_income_cents` is the sum of every
        active member's `earned_income_cents` plus `unearned_income_cents`."

        Claim: with two members earning 100,000 cents each, gross = 200,000.
        """
        hh = create_household()
        add_member(hh["id"], full_name="A", date_of_birth=dob_for_age(30),
                   earned_income_cents=100000)
        add_member(hh["id"], full_name="B", date_of_birth=dob_for_age(30),
                   earned_income_cents=100000)
        re_read = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re_read["gross_monthly_income_cents"] == 200000

    def test_has_elderly_or_disabled_true_on_disabled_member(self, api):
        """PRD §3.2: "The `has_elderly_or_disabled` flag is true when at least
        one active member is age 60 or older at `Clock.now`, or has
        `is_disabled` set to true."

        Claim: adding a disabled member sets has_elderly_or_disabled=true.
        """
        hh = create_household()
        add_member(hh["id"], full_name="A", date_of_birth=dob_for_age(30),
                   is_disabled=True)
        re_read = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re_read["has_elderly_or_disabled"] is True

    def test_has_elderly_or_disabled_true_on_elderly_member(self, api):
        """PRD §3.2: "true when at least one active member is age 60 or older
        at `Clock.now`."

        Claim: adding a 65-year-old member sets has_elderly_or_disabled=true.
        """
        hh = create_household()
        add_member(hh["id"], full_name="E", date_of_birth=dob_for_age(65))
        re_read = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re_read["has_elderly_or_disabled"] is True

    def test_has_elderly_or_disabled_false_with_only_young_able_bodied(self, api):
        """PRD §3.2: "The `has_elderly_or_disabled` flag is true when at least
        one active member is age 60 or older at `Clock.now`, or has
        `is_disabled` set to true."

        Claim: when no member is elderly or disabled, the flag is false.
        """
        hh = create_household()
        add_member(hh["id"], full_name="A", date_of_birth=dob_for_age(30))
        add_member(hh["id"], full_name="B", date_of_birth=dob_for_age(35))
        re_read = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re_read["has_elderly_or_disabled"] is False


class TestMemberDeactivation:
    def test_deactivate_member_flips_status(self, api):
        """PRD §3.2: "remains so until a caseworker deactivates them, at which
        point `status` flips to `REMOVED`."

        Claim: deactivate API flips status to REMOVED.
        """
        hh, members = setup_basic_household(size=2, age=30)
        m1 = members[0]
        resp = api.deactivate_member(hh["id"], m1["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["status"] == "REMOVED"

    def test_deactivate_member_excluded_from_aggregates(self, api):
        """PRD §3.2: "The household's computed aggregates are derived strictly
        from members in `ACTIVE` status."

        Claim: deactivated member is excluded from household_size and gross.
        """
        hh, members = setup_basic_household(
            size=2, age=30, earned_each_cents=50000,
        )
        api.deactivate_member(hh["id"], members[0]["id"], CASEWORKER)
        re_read = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re_read["household_size"] == 1
        assert re_read["gross_monthly_income_cents"] == 50000

    def test_deactivated_member_persists_in_db(self, api):
        """PRD §3.2: "Deactivated members are not removed from the database —
        the row persists for audit — but they no longer count toward the household."

        Claim: GET on a REMOVED member returns the row with status=REMOVED.
        """
        hh, members = setup_basic_household(size=1, age=30)
        m = members[0]
        api.deactivate_member(hh["id"], m["id"], CASEWORKER)
        resp = api.get_member(hh["id"], m["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["status"] == "REMOVED"


class TestNetIncomeCalculation:
    def test_net_income_size_3_standard_household(self, api):
        """PRD §3.2: "The **net monthly income** is the meaningful eligibility
        figure, derived from gross income by a fixed sequence of deductions
        whose intermediate rounding ordering is preserved verbatim."
        PRD §3.2: "for households of size 1, 2, or 3, the deduction is 19,300 cents."

        Claim: with 3 members earning 50,000 each (gross=150,000), zero shelter,
        zero dependent care, no elderly/disabled: net = 150,000 - 19,300 -
        round(150,000*0.20) = 150,000 - 19,300 - 30,000 = 100,700. Then
        half_adjusted = 50,350; excess_shelter_raw = 0 - 50,350 < 0 -> 0.
        So net == 100,700.
        """
        hh, members = setup_basic_household(
            size=3, age=30, earned_each_cents=50000,
        )
        re_read = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re_read["gross_monthly_income_cents"] == 150000
        assert re_read["net_monthly_income_cents"] == 100700, (
            f"Expected 100700, got {re_read['net_monthly_income_cents']}"
        )

    def test_net_income_floors_at_zero(self, api):
        """PRD §3.2: "subtracting the standard, earned-income, and dependent-care
        deductions from `gross` and flooring the result at zero (negative
        intermediates become 0)."

        Claim: a household with zero income has net_monthly_income_cents = 0.
        """
        hh, _ = setup_basic_household(size=1, age=30, earned_each_cents=0)
        re_read = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re_read["net_monthly_income_cents"] == 0
