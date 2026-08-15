"""Per-diem ledgers: tier rates, meal deductions, dispute loop (PRD §3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_member, create_per_diem, make_team_member_headers,
    setup_team_season_trip,
    assert_per_diem_money_invariants,
    validate_error, validate_success, get_success_data,
)

FIN = TEST_USERS["finance_headers"]
ANY = TEST_USERS["any_headers"]


class TestPerDiemComputation:
    def test_floor_at_zero_when_deductions_exceed_base(self, api):
        """PRD §3.8: "`TIER_C` pays 6,500, 8,000, 5,000, and 3,250 cents
        respectively" and "Each team-provided meal deducts a flat 2,500 cents, so
        `deduction_cents` is `meals_provided_count` times 2,500, and
        `net_amount_cents` is the base minus the deduction, floored at zero."

        Design: Difficulty/dual_variant_calc/per_diem_dispute_variant_floor_zero
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2026-11-01T02:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="S01",
                            party_role="STAFF", per_diem_tier="TIER_C")
        ledger = create_per_diem(team["id"], trip["id"], member["id"],
                                 service_date="2026-11-01", day_kind="PARTIAL_DAY",
                                 meals_provided_count=3)
        assert ledger["base_amount_cents"] == 3250
        assert ledger["deduction_cents"] == 7500
        assert ledger["net_amount_cents"] == 0, \
            "raw subtraction would be -4250; the floor clamps net to 0"
        assert_per_diem_money_invariants(ledger)

    def test_dispute_resolve_recomputes_with_same_floor(self, api):
        """PRD §3.8: "the finance lead resolves the dispute by supplying a
        corrected `meals_provided_count` — subject to the same three-meal cap and
        `ERR_INVALID_PER_DIEM_INPUT` rejection — which recomputes the deduction
        and the `net_amount_cents` and returns the row to `APPROVED`."

        Design: Difficulty/dual_variant_calc/per_diem_dispute_variant_floor_zero
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2026-11-01T02:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="S02",
                            party_role="STAFF", per_diem_tier="TIER_C")
        ledger = create_per_diem(team["id"], trip["id"], member["id"],
                                 service_date="2026-11-01", day_kind="PARTIAL_DAY",
                                 meals_provided_count=0)
        assert ledger["net_amount_cents"] == 3250
        validate_success(
            api.approve_per_diem(team["id"], trip["id"], member["id"], ledger["id"], FIN),
            200)
        validate_success(
            api.dispute_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                                 make_team_member_headers(member["id"])), 200)
        resolved = validate_success(
            api.resolve_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                                 3, FIN), 200)
        assert resolved["status"] == "APPROVED"
        assert resolved["base_amount_cents"] == 3250
        assert resolved["deduction_cents"] == 7500
        assert resolved["net_amount_cents"] == 0, \
            "the floor at zero also applies to the dispute-resolve recompute"
        assert_per_diem_money_invariants(resolved)


class TestZeroMeals:
    def test_explicit_zero_meals(self, api):
        """PRD §3.8: "Each team-provided meal deducts a flat 2,500 cents, so
        `deduction_cents` is `meals_provided_count` times 2,500, and
        `net_amount_cents` is the base minus the deduction, floored at zero."
        Zero meals means zero deduction, so net equals base exactly.

        Design: Difficulty/boundary_precision_check/per_diem_zero_meals_floor
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-01-10T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="T01",
                            party_role="STAFF", per_diem_tier="TIER_C")
        ledger = create_per_diem(team["id"], trip["id"], member["id"],
                                 service_date="2027-01-10", day_kind="TRAVEL_DAY",
                                 meals_provided_count=0)
        assert ledger["base_amount_cents"] == 6500
        assert ledger["deduction_cents"] == 0
        assert ledger["net_amount_cents"] == 6500

    def test_omitted_meals_defaults_to_zero(self, api):
        """PRD §3.8: "an optional `meals_provided_count` — the number of
        team-provided meals that day, defaulting to 0 and capped at 3".

        Design: Difficulty/boundary_precision_check/per_diem_zero_meals_floor
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-01-10T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="T02",
                            party_role="STAFF", per_diem_tier="TIER_C")
        res = api.create_per_diem(team["id"], trip["id"], member["id"],
                                  {"service_date": "2027-01-10",
                                   "day_kind": "TRAVEL_DAY"}, FIN)
        ledger = validate_success(res, 201)
        assert ledger["meals_provided_count"] == 0
        assert ledger["deduction_cents"] == 0
        assert ledger["net_amount_cents"] == 6500


class TestDisputeLoop:
    def test_double_dispute_recomputes_each_pass(self, api):
        """PRD §3.8: "A `TeamMember` who disagrees with a row may dispute it,
        moving `APPROVED` to `DISPUTED`; the finance lead resolves the dispute by
        supplying a corrected `meals_provided_count` ... which recomputes the
        deduction and the `net_amount_cents` and returns the row to `APPROVED`."
        TIER_B GAME_DAY base is 11,000 cents.

        Design: Difficulty/non_linear_state_machine/per_diem_ledger_dispute_loop
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2026-12-15T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="B01",
                            party_role="COACH", per_diem_tier="TIER_B")
        ledger = create_per_diem(team["id"], trip["id"], member["id"],
                                 service_date="2026-12-15", day_kind="GAME_DAY",
                                 meals_provided_count=0)
        assert ledger["net_amount_cents"] == 11000
        member_headers = make_team_member_headers(member["id"])

        validate_success(
            api.approve_per_diem(team["id"], trip["id"], member["id"], ledger["id"], FIN),
            200)
        validate_success(
            api.dispute_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                                 member_headers), 200)
        r1 = validate_success(
            api.resolve_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                                 1, FIN), 200)
        assert r1["status"] == "APPROVED"
        assert r1["net_amount_cents"] == 8500, "11000 - 1*2500"

        validate_success(
            api.dispute_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                                 member_headers), 200)
        r2 = validate_success(
            api.resolve_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                                 2, FIN), 200)
        assert r2["status"] == "APPROVED"
        assert r2["meals_provided_count"] == 2
        assert r2["net_amount_cents"] == 6000, "11000 - 2*2500"

    def test_single_dispute_resolve_cycle(self, api):
        """PRD §3.8: "the finance lead resolves the dispute by supplying a
        corrected `meals_provided_count` ... which recomputes the deduction and
        the `net_amount_cents` and returns the row to `APPROVED`." TIER_A
        TRAVEL_DAY base is 12,000 cents.

        Design: Difficulty/non_linear_state_machine/per_diem_ledger_dispute_loop
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2026-12-15T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="B02",
                            per_diem_tier="TIER_A")
        ledger = create_per_diem(team["id"], trip["id"], member["id"],
                                 service_date="2026-12-15", day_kind="TRAVEL_DAY",
                                 meals_provided_count=0)
        assert ledger["net_amount_cents"] == 12000
        validate_success(
            api.approve_per_diem(team["id"], trip["id"], member["id"], ledger["id"], FIN),
            200)
        validate_success(
            api.dispute_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                                 make_team_member_headers(member["id"])), 200)
        resolved = validate_success(
            api.resolve_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                                 3, FIN), 200)
        assert resolved["status"] == "APPROVED"
        assert resolved["net_amount_cents"] == 4500, "12000 - 3*2500"
        assert_per_diem_money_invariants(resolved)


class TestLedgerGuards:
    def test_pay_from_draft_rejected(self, api, finance_headers):
        """PRD §3.8: "Payment moves an `APPROVED` row to `PAID` — anything else
        yields `ERR_LEDGER_NOT_APPROVED`".

        Design: Corner/state_machines/ledger_pay_from_draft_rejected
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-04-05T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="S01",
                            party_role="STAFF", per_diem_tier="TIER_C")
        ledger = create_per_diem(team["id"], trip["id"], member["id"],
                                 service_date="2027-04-05", day_kind="GAME_DAY",
                                 meals_provided_count=0)
        assert ledger["status"] == "DRAFT"
        res = api.pay_per_diem(team["id"], trip["id"], member["id"], ledger["id"],
                               finance_headers)
        validate_error(res, "ERR_LEDGER_NOT_APPROVED", expected_status=409)

    def test_meals_above_cap_rejected(self, api, finance_headers):
        """PRD §3.8: "an optional `meals_provided_count` — the number of
        team-provided meals that day, defaulting to 0 and capped at 3; a count
        above 3 or an unrecognized `day_kind` is rejected with
        `ERR_INVALID_PER_DIEM_INPUT` (HTTP 400)."

        Design: Corner/validations/per_diem_meals_count_validation
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-05-15T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="D01",
                            party_role="STAFF", per_diem_tier="TIER_C")
        res = api.create_per_diem(
            team["id"], trip["id"], member["id"],
            {"service_date": "2027-05-15", "day_kind": "GAME_DAY",
             "meals_provided_count": 5}, finance_headers)
        validate_error(res, "ERR_INVALID_PER_DIEM_INPUT", expected_status=400)
