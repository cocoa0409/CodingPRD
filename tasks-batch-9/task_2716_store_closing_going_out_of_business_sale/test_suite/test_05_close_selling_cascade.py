"""Closing one store and following the six hops it sets off.

Each hop is caused by the one before it: the store leaves the floor, the cadence
is retired, the retention bonuses settle, the accrual re-sums, the payroll
expense is synthesised and the engagement's expense aggregates move.
"""
import pytest

from test_helpers import (
    add_employee,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    activate_markdown_stage,
    api_client,
    apply_for_license,
    approve_engagement,
    assert_engagement_expense_identity,
    assert_expense_shares_conserved,
    assert_recovery_summary,
    close_store,
    create_engagement,
    create_jurisdiction,
    decide_license,
    make_consultant_headers,
    pin_clock,
    read_engagement,
    read_store,
    submit_engagement,
    validate_paginated,
    validate_success,
)

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
RETENTION_PERIOD = {
    "retention_start_date": "2026-09-15", "retention_target_date": "2026-11-15",
}


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


def _read_employee(employee_id):
    return validate_success(
        api_client.get_employee(employee_id, make_consultant_headers())
    )


def _store_closed_with_a_cadence_and_two_employees():
    """A selling store with one active stage, one armed stage and two employees,
    closed at 2026-10-16.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(
        economics_model="FEE_BASED", guaranty_pct=0, hybrid_retailer_excess_pct=0,
        expense_responsibility="SHARED", shared_expense_liquidator_pct=0.4,
        sale_start_date="2026-09-15", target_end_date="2026-11-30",
    )
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-701", address_line="5 Union Sq",
    )
    add_inventory_lot(
        store["id"], category="APPAREL", source="ORIGINAL", units_initial=1000,
        unit_cost_cents=2000, unit_retail_cents=5000,
    )
    add_inventory_lot(
        store["id"], category="ELECTRONICS", source="ORIGINAL", units_initial=200,
        unit_cost_cents=15000, unit_retail_cents=30000,
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0701",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    stage_one = add_markdown_stage(
        store["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-15", window_end_date="2026-09-29",
    )
    stage_two = add_markdown_stage(
        store["id"], stage_index=2, discount_pct=0.4, sell_through_target_pct=0.6,
        window_start_date="2026-09-29", window_end_date="2026-10-13",
    )
    activate_markdown_stage(stage_one["id"])
    employee_a = add_employee(
        store["id"], employee_code="EMP-A", retention_bonus_cents=500000,
        attendance_rate=0.95, **RETENTION_PERIOD,
    )
    employee_b = add_employee(
        store["id"], employee_code="EMP-B", retention_bonus_cents=333333,
        attendance_rate=0.92, **RETENTION_PERIOD,
    )
    pin_clock("2026-10-16T00:00:00Z")
    closed = close_store(store["id"])
    expense_rows, _meta = validate_paginated(
        api_client.list_store_expense_items(store["id"], make_consultant_headers())
    )
    summary = validate_success(
        api_client.get_recovery_summary(engagement["id"], make_consultant_headers())
    )
    return {
        "engagement": read_engagement(engagement["id"]),
        "store": closed,
        "stage_one": _read_stage(stage_one["id"]),
        "stage_two": _read_stage(stage_two["id"]),
        "employee_a": _read_employee(employee_a["id"]),
        "employee_b": _read_employee(employee_b["id"]),
        "expense_items": expense_rows,
        "summary": summary,
    }


class TestCloseSellingCascade:
    def test_hop_one_takes_the_store_off_the_floor_on_the_clock_date(self):
        """CLOSED with the selling end date pinned to the logical clock.

        The PRD says: "Hop one takes the store to `CLOSED`, sets
        `selling_end_date` to the current logical-clock date, and freezes
        `realized_sell_through_pct`."

        Design: Difficulty/transitive_cascade/close_selling_six_hop_chain_from_store_to_engagement_expense_split
        """
        scenario = _store_closed_with_a_cadence_and_two_employees()
        store = scenario["store"]
        assert store["store_status"] == "CLOSED"
        assert store["selling_end_date"] == "2026-10-16"

    def test_hop_two_retires_both_the_active_and_the_armed_stage(self):
        """Every stage still in the cadence closes with STORE_CLOSED and no
        escalation.

        The PRD says: "Hop two, caused by the store leaving the floor, closes every
        markdown stage of the store whose status is `ARMED` or `ACTIVE`, each moving
        to `CLOSED` with `closed_reason` of `STORE_CLOSED` and no escalation
        applied."

        Design: Difficulty/transitive_cascade/close_selling_six_hop_chain_from_store_to_engagement_expense_split
        """
        scenario = _store_closed_with_a_cadence_and_two_employees()
        for stage in (scenario["stage_one"], scenario["stage_two"]):
            assert stage["stage_status"] == "CLOSED"
            assert stage["closed_reason"] == "STORE_CLOSED"
            assert stage["escalation_applied_pct"] == pytest.approx(0.0, abs=0.00001)

    def test_hop_three_settles_both_retention_bonuses_on_the_selling_end_date(self):
        """Thirty-two of sixty-two days served, prorated per employee.

        The PRD says: "Hop three, caused by the cadence ending, settles every
        employee of the store whose `bonus_status` is `PENDING` by the arithmetic
        above, using the store's `selling_end_date` as the settlement day, and moves
        every one of those employees whose `employment_status` is `ACTIVE` or
        `NOTICE_GIVEN` to `TERMINATED_INVOLUNTARY` with `termination_date` set to
        that same `selling_end_date`."

        Design: Difficulty/transitive_cascade/close_selling_six_hop_chain_from_store_to_engagement_expense_split
        """
        scenario = _store_closed_with_a_cadence_and_two_employees()
        employee_a, employee_b = scenario["employee_a"], scenario["employee_b"]
        assert employee_a["earned_bonus_cents"] == 258065
        assert employee_a["bonus_status"] == "PRORATED_EARNED"
        assert employee_a["employment_status"] == "TERMINATED_INVOLUNTARY"
        assert employee_b["earned_bonus_cents"] == 172043
        assert employee_b["bonus_status"] == "PRORATED_EARNED"

    def test_hop_four_re_sums_the_engagement_accrual_from_the_settled_bonuses(self):
        """The accrual is the sum of the two individually rounded entitlements.

        The PRD says: "Hop four, caused by hop three writing earned bonuses,
        re-sums the engagement's `retention_accrual_cents` round-then-sum across
        every store."

        Design: Difficulty/transitive_cascade/close_selling_six_hop_chain_from_store_to_engagement_expense_split
        """
        scenario = _store_closed_with_a_cadence_and_two_employees()
        assert scenario["engagement"]["retention_accrual_cents"] == 430108

    def test_hop_five_synthesises_exactly_one_approved_payroll_item(self):
        """One auto-generated item, already approved, for the store's earned sum.

        The PRD says: "Hop five, caused by hop four being non-zero, creates exactly
        one expense item marked `auto_generated` with `expense_category` of
        `PAYROLL`, `store_id` set to this store, `amount_cents` equal to the sum of
        `earned_bonus_cents` across this store's employees, `expense_status` already
        `APPROVED`, and `incurred_date` set to the store's `selling_end_date`; both
        `submitted_by_user_id` and `decided_by_user_id` stay unset, because no human
        filed or decided it."

        Design: Difficulty/transitive_cascade/close_selling_six_hop_chain_from_store_to_engagement_expense_split
        """
        scenario = _store_closed_with_a_cadence_and_two_employees()
        auto_items = [row for row in scenario["expense_items"] if row["auto_generated"]]
        assert len(auto_items) == 1
        item = auto_items[0]
        assert item["expense_category"] == "PAYROLL"
        assert item["expense_status"] == "APPROVED"
        assert item["amount_cents"] == 430108
        assert item["store_id"] == scenario["store"]["id"]
        assert item["incurred_date"] == "2026-10-16"
        assert item["submitted_by_user_id"] is None
        assert item["decided_by_user_id"] is None

    def test_hop_six_splits_the_new_item_and_moves_the_three_aggregates(self):
        """The 0.40 liquidator share and the remainder land on the engagement.

        The PRD says: "Hop six, caused by hop five, splits the new item by the
        expense-responsibility rule below and refreshes the engagement's three
        expense aggregates."

        Design: Difficulty/transitive_cascade/close_selling_six_hop_chain_from_store_to_engagement_expense_split
        """
        scenario = _store_closed_with_a_cadence_and_two_employees()
        item = [row for row in scenario["expense_items"] if row["auto_generated"]][0]
        assert item["liquidator_share_cents"] == 172043
        assert item["retailer_share_cents"] == 258065
        assert_expense_shares_conserved(item)
        engagement = scenario["engagement"]
        assert engagement["expense_total_cents"] == 430108
        assert engagement["expense_liquidator_share_cents"] == 172043
        assert engagement["expense_retailer_share_cents"] == 258065
        assert_engagement_expense_identity(engagement)

    def test_the_emptied_cadence_drops_the_planned_discount_to_zero(self):
        """With no armed or active stage left the projection loses its discount.

        The PRD says: "It begins from the store's planned discount: gather the
        store's markdown stages whose status is `ARMED` or `ACTIVE`, and if that set
        is empty the store's `planned_avg_discount_pct` is exactly 0.0000, otherwise
        it is the sum of those stages' `discount_pct` values divided by how many
        stages are in the set, rounded half up to four decimal places."

        Design: Difficulty/transitive_cascade/close_selling_six_hop_chain_from_store_to_engagement_expense_split
        """
        scenario = _store_closed_with_a_cadence_and_two_employees()
        summary = scenario["summary"]
        assert_recovery_summary(summary)
        assert summary["planned_avg_discount_pct"] == pytest.approx(0.0, abs=0.00001)
        assert summary["projected_gross_recovery_cents"] == 9950000
        assert summary["projected_recovery_ratio"] == pytest.approx(1.9900, abs=0.00001)
        store = read_store(scenario["store"]["id"])
        assert store["planned_avg_discount_pct"] == pytest.approx(0.0, abs=0.00001)
        assert store["projected_gross_recovery_cents"] == 9950000
