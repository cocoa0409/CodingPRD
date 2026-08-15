"""Monthly statement arithmetic: accrual vs cash variants, management fee
evaluation order, and the mixed-expense tax split (PRD §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    setup_active_agreement, setup_dispatch_ready,
    post_expense, generate_statement, create_trip, approve_charter_trip,
    assign_duty, schedule_trip, complete_trip, setup_qualified_crew_pair,
    file_accepted_insurance, TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]
FO = TEST_USERS["flight_ops_headers"]


def _setup_accrual_cash_scenario(api):
    """ACTIVE agreement + three expenses straddling the August period boundary:
    E1 FUEL 250000 (service 2026-08-05, paid 2026-08-07) — in both;
    E2 CREW 180000 (service 2026-08-15, paid 2026-09-02) — accrual only;
    E3 HANGAR 50000 (service 2026-07-28, paid 2026-08-03) — cash only.
    """
    scenario = setup_active_agreement(tail_number="N100JX")
    aircraft_id = scenario["aircraft"]["id"]
    post_expense(aircraft_id, category="FUEL", amount_cents=250000,
                 service_date="2026-08-05", paid_date="2026-08-07",
                 vendor_name="Meridian Fuel")
    post_expense(aircraft_id, category="CREW", amount_cents=180000,
                 service_date="2026-08-15", paid_date="2026-09-02",
                 vendor_name="Crew Leasing Co")
    post_expense(aircraft_id, category="HANGAR", amount_cents=50000,
                 service_date="2026-07-28", paid_date="2026-08-03",
                 vendor_name="Teterboro Hangars")
    return scenario


def test_statement_accrual_and_cash_totals_diverge(api):
    """PRD §3.8: "The `accrual_total_cents` is the sum of `amount_cents` over
    the aircraft's non-`VOID` expenses — `POSTED` and `BILLED` alike — whose
    `service_date` falls inside the period, compared by calendar date. The
    `cash_total_cents` is the sum of `amount_cents` over the same non-`VOID`
    expense set whose `paid_date` is non-null and falls inside the period; the
    two totals diverge whenever an expense is paid in a different month than it
    was incurred."

    Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_variant_totals
    """
    scenario = _setup_accrual_cash_scenario(api)

    statement = generate_statement(scenario["aircraft"]["id"], period="2026-08")
    assert statement["status"] == "DRAFT"
    assert statement["accrual_total_cents"] == 430000, (
        f"250000 (Aug) + 180000 (Aug); the July-service expense is excluded, "
        f"got {statement['accrual_total_cents']}"
    )
    assert statement["cash_total_cents"] == 300000, (
        f"250000 (paid Aug) + 50000 (paid Aug); the Sept-paid expense is "
        f"excluded, got {statement['cash_total_cents']}"
    )


def test_statement_management_fee_on_accrual_subtotal(api):
    """PRD §3.8: "The statement's `management_fee_cents` is then the
    agreement's `monthly_management_fee_cents` plus the agreement's
    `variable_fee_pct` multiplied by that direct subtotal, the product rounded
    half up to integer cents."

    Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_variant_totals
    """
    scenario = _setup_accrual_cash_scenario(api)

    statement = generate_statement(scenario["aircraft"]["id"], period="2026-08")
    # fee = 500000 + round_half_up(0.10 x 430000) = 543000
    assert statement["management_fee_cents"] == 543000, (
        f"fee is computed on the accrual (direct) subtotal, got "
        f"{statement['management_fee_cents']}"
    )


def _setup_mixed_share_scenario(api, tax_method):
    """Dispatch-ready aircraft on the given tax method; one OWNER_USE trip
    completed at 4.0h, one CHARTER trip (quote 900000, no direct costs)
    completed at 6.0h, then MIXED expenses posted in 2026-08."""
    scenario = setup_dispatch_ready(
        tail_number="N200JX" if tax_method == "FLIGHT_HOURS" else "N400JX",
        terms={"tax_allocation_method": tax_method},
    )
    aircraft_id = scenario["aircraft"]["id"]
    owner_id = scenario["owner"]["id"]
    captain = scenario["captain"]
    first_officer = scenario["first_officer"]

    t1 = create_trip(aircraft_id, trip_use="OWNER_USE",
                     departure_at="2026-08-04T08:00:00Z", block_hours_est=4.0)
    assign_duty(t1["id"], captain["id"], "PIC",
                "2026-08-04T06:00:00Z", "2026-08-04T12:00:00Z")
    assign_duty(t1["id"], first_officer["id"], "SIC",
                "2026-08-04T06:00:00Z", "2026-08-04T12:00:00Z")
    schedule_trip(t1["id"])
    complete_trip(t1["id"], 4.0)

    t2 = create_trip(aircraft_id, trip_use="CHARTER",
                     departure_at="2026-08-06T08:00:00Z", block_hours_est=6.0,
                     charter_quote_cents=900000, arrive_icao="KMIA")
    approve_charter_trip(t2["id"], owner_id)
    assign_duty(t2["id"], captain["id"], "PIC",
                "2026-08-06T06:00:00Z", "2026-08-06T14:00:00Z")
    assign_duty(t2["id"], first_officer["id"], "SIC",
                "2026-08-06T06:00:00Z", "2026-08-06T14:00:00Z")
    schedule_trip(t2["id"])
    complete_trip(t2["id"], 6.0)
    return scenario


def test_tax_split_flight_hours_method(api):
    """PRD §3.8: "Under the `FLIGHT_HOURS` method the ratio is the charter
    block hours — the sum of `block_hours_actual` over the in-period completed
    `CHARTER` trips — divided by the total block hours over all in-period
    completed trips."
    PRD §3.8: "The method in force on the agreement at generation time is
    recorded on the statement as `tax_method_used`"
    PRD §3.8: "The `charter_offset_cents` is the sum of `owner_credit_cents`
    over the aircraft's `CHARTER` trips that completed with their completion
    timestamp inside the period."

    Design: Difficulty/dual_variant_calc/tax_allocation_flight_hours_vs_trip_legs
    """
    scenario = _setup_mixed_share_scenario(api, "FLIGHT_HOURS")
    aircraft_id = scenario["aircraft"]["id"]
    post_expense(aircraft_id, category="OTHER", amount_cents=100000,
                 service_date="2026-08-20", paid_date="2026-08-21",
                 vendor_name="Catering Shared", tax_use="MIXED")

    statement = generate_statement(aircraft_id, period="2026-08")
    assert statement["tax_method_used"] == "FLIGHT_HOURS"
    # charter ratio 6.0/10.0 -> owner share 0.4 x 100000 = 40000
    assert statement["mixed_owner_share_cents"] == 40000
    assert statement["mixed_charter_share_cents"] == 60000
    # charter offset: net 900000 x 0.85 = 765000 (no direct costs posted)
    assert statement["charter_offset_cents"] == 765000


def test_tax_split_regenerated_under_trip_legs(api):
    """PRD §3.8: "Under the `TRIP_LEGS` method the ratio is the count of
    in-period completed `CHARTER` trips divided by the count of all in-period
    completed trips."
    PRD §3.8: "Generation is idempotent over drafts: at most one statement per
    aircraft and period may exist in `CERTIFIED` or `DELIVERED` — a duplicate
    there is rejected with `ERR_STATEMENT_EXISTS` — while generating over an
    existing `DRAFT` recomputes and returns that draft rather than creating a
    duplicate."
    PRD §3.8: "The method in force on the agreement at generation time is
    recorded on the statement as `tax_method_used`"

    Design: Difficulty/dual_variant_calc/tax_allocation_flight_hours_vs_trip_legs
    """
    scenario = _setup_mixed_share_scenario(api, "FLIGHT_HOURS")
    aircraft_id = scenario["aircraft"]["id"]
    post_expense(aircraft_id, category="OTHER", amount_cents=100000,
                 service_date="2026-08-20", paid_date="2026-08-21",
                 vendor_name="Catering Shared", tax_use="MIXED")

    first = generate_statement(aircraft_id, period="2026-08")
    assert first["tax_method_used"] == "FLIGHT_HOURS"
    assert first["mixed_owner_share_cents"] == 40000

    # Amend the agreement's tax method (OCC-guarded) and regenerate.
    amended = validate_success(
        api.patch_agreement_terms(
            scenario["agreement"]["id"],
            {
                "expected_agreement_version": scenario["agreement"]["version"],
                "tax_allocation_method": "TRIP_LEGS",
            },
            AE,
        ),
        200,
    )
    assert amended["tax_allocation_method"] == "TRIP_LEGS"

    second = validate_success(
        api.create_statement({"aircraft_id": aircraft_id, "period": "2026-08"}, AE),
        201,
    )
    assert second["id"] == first["id"], "regeneration recomputes the same DRAFT"
    assert second["tax_method_used"] == "TRIP_LEGS"
    # trip-count ratio 1/2 -> owner share 0.5 x 100000 = 50000
    assert second["mixed_owner_share_cents"] == 50000
    assert second["mixed_charter_share_cents"] == 50000


def _setup_per_line_rounding_scenario(api):
    """TRIP_LEGS agreement; one OWNER_USE (4.0h) and one CHARTER (6.0h) trip
    completed in period -> trip-count ratio exactly 1/2; two MIXED expense
    lines 33333 and 66667 in 2026-08."""
    scenario = _setup_mixed_share_scenario(api, "TRIP_LEGS")
    aircraft_id = scenario["aircraft"]["id"]
    post_expense(aircraft_id, category="OTHER", amount_cents=33333,
                 service_date="2026-08-10", vendor_name="Shared Services A",
                 tax_use="MIXED", paid_date=None)
    post_expense(aircraft_id, category="OTHER", amount_cents=66667,
                 service_date="2026-08-11", vendor_name="Shared Services B",
                 tax_use="MIXED", paid_date=None)
    return scenario


def test_mixed_expense_rounding_per_line_then_sum(api):
    """PRD §3.8: "Each in-period non-`VOID` expense line whose `tax_use` is
    `MIXED` is then split per line: the line's owner share is its
    `amount_cents` multiplied by the owner ratio, rounded half up to integer
    cents, and the line's charter share is the `amount_cents` minus that owner
    share."
    PRD §3.8: "The statement's `mixed_owner_share_cents` is the sum of the
    per-line owner shares and `mixed_charter_share_cents` is the sum of the
    per-line charter shares — rounding is applied per line before summing,
    never once at the end, because the two orders disagree on odd-cent lines."

    Design: Difficulty/combinatorial_formula/mixed_expense_per_line_rounding_then_sum
    """
    scenario = _setup_per_line_rounding_scenario(api)

    statement = generate_statement(scenario["aircraft"]["id"], period="2026-08")
    # owner ratio 0.5; line 33333 -> 16667 (half up), line 66667 -> 33334
    assert statement["mixed_owner_share_cents"] == 50001, (
        f"per-line round-half-up then sum: 16667 + 33334 = 50001, got "
        f"{statement['mixed_owner_share_cents']}"
    )
    assert statement["mixed_charter_share_cents"] == 49999


def test_mixed_expense_shares_sum_to_mixed_total(api):
    """PRD §3.8: "the line's owner share is its `amount_cents` multiplied by
    the owner ratio, rounded half up to integer cents, and the line's charter
    share is the `amount_cents` minus that owner share."
    PRD §3.8: "the two shares always sum back to the total of the in-period
    mixed lines."

    Design: Difficulty/combinatorial_formula/mixed_expense_per_line_rounding_then_sum
    """
    scenario = _setup_per_line_rounding_scenario(api)

    statement = generate_statement(scenario["aircraft"]["id"], period="2026-08")
    total_mixed = 33333 + 66667
    assert (
        statement["mixed_owner_share_cents"] + statement["mixed_charter_share_cents"]
        == total_mixed
    ), "per-line split must conserve the mixed-expense total"


def _setup_pre_fee_subtotal_scenario(api):
    """ACTIVE agreement; FUEL 250000 + CREW 180000 (unpaid) posted; one CHARTER
    trip (quote 900000) completed at 6.0h with CHARTER_DIRECT costs
    200000 + 50000 (both with service_date in 2026-08, hence inside the
    accrual subtotal)."""
    scenario = setup_dispatch_ready(tail_number="N500JX")
    aircraft_id = scenario["aircraft"]["id"]
    owner_id = scenario["owner"]["id"]
    captain = scenario["captain"]
    first_officer = scenario["first_officer"]

    post_expense(aircraft_id, category="FUEL", amount_cents=250000,
                 service_date="2026-08-05", paid_date="2026-08-07",
                 vendor_name="Meridian Fuel")
    post_expense(aircraft_id, category="CREW", amount_cents=180000,
                 service_date="2026-08-15", paid_date=None,
                 vendor_name="Crew Leasing Co")

    t = create_trip(aircraft_id, trip_use="CHARTER",
                    departure_at="2026-08-06T08:00:00Z", block_hours_est=6.0,
                    charter_quote_cents=900000, arrive_icao="KMIA")
    approve_charter_trip(t["id"], owner_id)
    post_expense(aircraft_id, category="CHARTER_DIRECT", amount_cents=200000,
                 service_date="2026-08-06", vendor_name="JetFuel Co",
                 tax_use="CHARTER_USE", trip_id=t["id"], paid_date=None)
    post_expense(aircraft_id, category="CHARTER_DIRECT", amount_cents=50000,
                 service_date="2026-08-06", vendor_name="Signature Landing",
                 tax_use="CHARTER_USE", trip_id=t["id"], paid_date=None)
    assign_duty(t["id"], captain["id"], "PIC",
                "2026-08-06T06:00:00Z", "2026-08-06T14:00:00Z")
    assign_duty(t["id"], first_officer["id"], "SIC",
                "2026-08-06T06:00:00Z", "2026-08-06T14:00:00Z")
    schedule_trip(t["id"])
    complete_trip(t["id"], 6.0)
    return scenario


def test_management_fee_computed_on_pre_fee_subtotal(api):
    """PRD §3.8: "The direct subtotal is exactly the `accrual_total_cents` —
    there is no management-fee expense category, so the fee never enters its
    own basis."
    PRD §3.8: "The statement's `management_fee_cents` is then the agreement's
    `monthly_management_fee_cents` plus the agreement's `variable_fee_pct`
    multiplied by that direct subtotal, the product rounded half up to integer
    cents."

    Design: Difficulty/combinatorial_formula/management_fee_pre_fee_subtotal_order
    """
    scenario = _setup_pre_fee_subtotal_scenario(api)

    statement = generate_statement(scenario["aircraft"]["id"], period="2026-08")
    # accrual = 250000 + 180000 + 200000 + 50000 = 680000
    assert statement["accrual_total_cents"] == 680000
    # fee = 500000 + round_half_up(0.10 x 680000) = 568000
    assert statement["management_fee_cents"] == 568000, (
        f"fee is pinned to the pre-fee accrual subtotal (680000), got "
        f"{statement['management_fee_cents']}"
    )


def test_management_fee_not_reduced_by_charter_offset(api):
    """PRD §3.8: "The grand total due is the direct subtotal plus the
    management fee minus the `charter_offset_cents`; the fee is computed on the
    pre-fee subtotal and is never reduced by the charter offset, which is
    applied only after the fee."
    PRD §3.8: "The `charter_offset_cents` is the sum of `owner_credit_cents`
    over the aircraft's `CHARTER` trips that completed with their completion
    timestamp inside the period."

    Design: Difficulty/combinatorial_formula/management_fee_pre_fee_subtotal_order
    """
    scenario = _setup_pre_fee_subtotal_scenario(api)

    statement = generate_statement(scenario["aircraft"]["id"], period="2026-08")
    # offset = round_half_up((900000 - 250000) x 0.85) = 552500
    assert statement["charter_offset_cents"] == 552500
    assert statement["management_fee_cents"] == 568000, (
        "the 552500 offset is applied after the fee, never netted into its basis"
    )
