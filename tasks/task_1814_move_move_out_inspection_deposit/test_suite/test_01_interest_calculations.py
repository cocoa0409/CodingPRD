"""Deposit interest: dual variants (ACTUAL_DAYS vs WHOLE_YEARS), per-year
rounding order, and the not-required short-circuit."""
import test_helpers as th
from test_helpers import (
    add_item,
    api_client,
    complete_inspection,
    create_jurisdiction,
    create_property,
    create_statement_for,
    create_tenancy,
    create_unit,
    get_success_data,
    get_tenancy,
    make_manager_admin_headers,
    make_property_manager_headers,
    schedule_inspection,
    setup_vacated_tenancy,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


def _run_two_variant_tenancies():
    """Two jurisdictions identical except interest_basis; identical tenancies
    completing move-in at 2025-01-10 and move-out at 2026-08-01 (568 days),
    no damage items and all keys/fobs returned."""
    api_client.set_clock({"to_iso8601": "2025-01-10T00:00:00Z"}, ADMIN)
    jur_a = create_jurisdiction(code="CA-ACT", interest_basis="ACTUAL_DAYS")
    jur_b = create_jurisdiction(code="NY-WHL", interest_basis="WHOLE_YEARS")
    prop_a = create_property(jur_a["id"], name="Maple Court", address="1 Maple St")
    prop_b = create_property(jur_b["id"], name="Birch Court", address="2 Birch St")
    unit_a = create_unit(prop_a["id"], unit_number="1A")
    unit_b = create_unit(prop_b["id"], unit_number="1B")
    tenancies = []
    for unit, name in ((unit_a, "Tanya A"), (unit_b, "Tanya B")):
        ten = create_tenancy(unit["id"], tenant_display_name=name)
        mi = schedule_inspection(ten["id"], "MOVE_IN")
        add_item(mi["id"], area_name="living_room_carpet", category="CARPET",
                 condition="GOOD", photo_count=2)
        complete_inspection(mi["id"])
        tenancies.append(ten)
    api_client.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN)
    for ten in tenancies:
        get_success_data(api_client.give_notice(ten["id"], PM))
        mo = schedule_inspection(ten["id"], "MOVE_OUT")
        complete_inspection(mo["id"])
    return tenancies


class TestDualVariantInterest:
    def test_actual_days_variant_accrues_9337(self):
        """PRD §3.4: "Under the `ACTUAL_DAYS` basis, interest accrues for the
        exact whole-day span from `move_in_on` through `move_out_on`, including
        partial years: the accrued amount is `deposit_cents` multiplied by
        `annual_interest_rate_bp` divided by 10000, multiplied by the number of
        days, divided by 365, with a single round half-up to whole cents at the
        end."

        568 days: 200000 * 300 / 10000 * 568 / 365 = 9336.99 -> round half up
        => 9,337c.

        Design: Difficulty/dual_variant_calc/interest_actual_days_vs_whole_years_diverge
        """
        ten_a, _ten_b = _run_two_variant_tenancies()
        seen = get_tenancy(ten_a["id"])
        assert seen["interest_accrued_cents"] == 9_337, (
            f"ACTUAL_DAYS interest: expected 9337, got {seen['interest_accrued_cents']}"
        )

    def test_whole_years_variant_accrues_6000_and_diverges(self):
        """PRD §3.4: "Under the `WHOLE_YEARS` basis, only completed 365-day years
        accrue: the number of completed years is the day span divided by 365
        rounded down, the per-year interest of `deposit_cents` times
        `annual_interest_rate_bp` divided by 10000 is rounded half-up to whole
        cents once per completed year, and those per-year amounts are then
        summed".

        568 days => 1 completed year: round(200000 * 300 / 10000) = 6,000c, and
        the two bases must disagree on the same inputs (9,337 vs 6,000).

        Design: Difficulty/dual_variant_calc/interest_actual_days_vs_whole_years_diverge
        """
        ten_a, ten_b = _run_two_variant_tenancies()
        seen_a = get_tenancy(ten_a["id"])
        seen_b = get_tenancy(ten_b["id"])
        assert seen_b["interest_accrued_cents"] == 6_000, (
            f"WHOLE_YEARS interest: expected 6000, got {seen_b['interest_accrued_cents']}"
        )
        assert seen_a["interest_accrued_cents"] != seen_b["interest_accrued_cents"], (
            "The two interest bases must diverge on identical inputs"
        )


class TestWholeYearsPerSegmentRounding:
    def _setup_two_year_tenancy(self):
        """Deposit 100,010c at 250bp WHOLE_YEARS; move-in 2024-01-10, move-out
        2026-01-10 (731 days => 2 completed years)."""
        api_client.set_clock({"to_iso8601": "2024-01-10T00:00:00Z"}, ADMIN)
        jur = create_jurisdiction(
            code="WA-WHL", annual_interest_rate_bp=250, interest_basis="WHOLE_YEARS",
        )
        prop = create_property(jur["id"], name="Cedar Court", address="3 Cedar St")
        unit = create_unit(prop["id"], unit_number="2A")
        ten = create_tenancy(
            unit["id"],
            tenant_display_name="Wendy Whole",
            lease_start_on="2024-01-10",
            lease_end_on="2026-02-01",
            deposit_cents=100_010,
            keys_issued=1,
            fobs_issued=0,
        )
        mi = schedule_inspection(ten["id"], "MOVE_IN",
                                 scheduled_start_at="2024-01-10T09:00:00Z",
                                 scheduled_end_at="2024-01-10T10:00:00Z")
        complete_inspection(mi["id"])
        api_client.set_clock({"to_iso8601": "2026-01-10T00:00:00Z"}, ADMIN)
        get_success_data(api_client.give_notice(ten["id"], PM))
        get_success_data(api_client.record_key_return(
            ten["id"], {"keys_returned": 1, "fobs_returned": 0}, PM))
        mo = schedule_inspection(ten["id"], "MOVE_OUT",
                                 scheduled_start_at="2026-01-10T10:00:00Z",
                                 scheduled_end_at="2026-01-10T11:00:00Z")
        complete_inspection(mo["id"])
        return ten

    def test_per_year_round_then_sum_yields_5000(self):
        """PRD §3.4: "the per-year interest of `deposit_cents` times
        `annual_interest_rate_bp` divided by 10000 is rounded half-up to whole
        cents once per completed year, and those per-year amounts are then
        summed — the rounding order is pinned, so the system must not multiply
        the years by the unrounded annual amount and round once."

        Per year: round(100010 * 250 / 10000) = round(2500.25) = 2500; two
        completed years => 5,000c. Sum-then-round would give 5,001c.

        Design: Difficulty/combinatorial_formula/whole_years_per_segment_rounding
        """
        ten = self._setup_two_year_tenancy()
        seen = get_tenancy(ten["id"])
        assert seen["interest_accrued_cents"] == 5_000, (
            f"WHOLE_YEARS per-year round-then-sum: expected 5000, "
            f"got {seen['interest_accrued_cents']} (sum-then-round would give 5001)"
        )

    def test_rounding_visible_through_statement_issuance(self):
        """PRD §3.5: "`interest_cents` snapshots the tenancy's accrued
        interest". Combined with PRD §3.4: "the per-year interest of
        `deposit_cents` times `annual_interest_rate_bp` divided by 10000 is
        rounded half-up to whole cents once per completed year, and those
        per-year amounts are then summed".

        Issuing the statement snapshots the 5,000c accrued under the pinned
        rounding order, and refund_due = 100,010 + 5,000 - 0.

        Design: Difficulty/combinatorial_formula/whole_years_per_segment_rounding
        """
        ten = self._setup_two_year_tenancy()
        stmt = create_statement_for(ten["id"])
        api_client.set_clock({"to_iso8601": "2026-01-15T00:00:00Z"}, ADMIN)
        issued = validate_success(api_client.issue_statement(stmt["id"], PM))
        assert issued["interest_cents"] == 5_000, (
            f"statement interest snapshot: expected 5000, got {issued['interest_cents']}"
        )
        assert issued["refund_due_cents"] == 105_010, (
            f"refund_due: expected 105010, got {issued['refund_due_cents']}"
        )


class TestInterestNotRequired:
    def test_interest_zero_when_not_required(self):
        """PRD §3.4: "When the governing jurisdiction's `interest_required` is
        false, no interest accrues and `interest_accrued_cents` stays zero."

        After a 568-day tenancy with all keys returned, accrued interest is 0
        and balance_remaining equals the deposit.

        Design: Corner/calculations/interest_zero_when_not_required
        """
        ctx = setup_vacated_tenancy(
            move_out_items=[],
            keys_returned=2, fobs_returned=1,
            jurisdiction_overrides={"code": "TX-NOINT", "interest_required": False,
                                    "annual_interest_rate_bp": 0},
        )
        ten = ctx["tenancy"]
        assert ten["interest_accrued_cents"] == 0, (
            f"interest must stay 0 when interest_required is false, "
            f"got {ten['interest_accrued_cents']}"
        )
        assert ten["balance_remaining_cents"] == 200_000, (
            f"balance must equal the untouched deposit, "
            f"got {ten['balance_remaining_cents']}"
        )
