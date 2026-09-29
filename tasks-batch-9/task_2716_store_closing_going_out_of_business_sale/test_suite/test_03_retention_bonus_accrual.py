"""Retention bonuses: the pinned round-then-sum accrual and the two dimensions.

Four employees settled by one closing cascade prove the accrual is the sum of
individually rounded entitlements, and one employee walked through notice,
termination and payment proves the employment and bonus dimensions move apart.
"""
import pytest

from test_helpers import (
    add_employee,
    add_inventory_lot,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    assert_employee,
    assert_engagement_expense_identity,
    assert_expense_shares_conserved,
    assert_instant_equals,
    close_store,
    create_engagement,
    create_jurisdiction,
    decide_license,
    make_consultant_headers,
    make_controller_headers,
    pin_clock,
    read_engagement,
    run_employment_action,
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


def _read_employee(employee_id):
    return validate_success(
        api_client.get_employee(employee_id, make_consultant_headers())
    )


def _store_with_four_enrolled_employees():
    """One selling store carrying four differently-placed retention enrolments.

    Two employees qualify on attendance, one falls below the attendance floor and
    one quits voluntarily, and the logical clock is moved to 2026-10-16 so the
    closing cascade counts 32 of the 62 required days.
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
        store_code="S-401", address_line="9 Harbor Rd",
    )
    add_inventory_lot(
        store["id"], category="APPAREL", source="ORIGINAL", units_initial=1000,
        unit_cost_cents=2000, unit_retail_cents=5000,
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0401",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    employees = {
        "a": add_employee(
            store["id"], employee_code="EMP-A", retention_bonus_cents=500000,
            attendance_rate=0.95, **RETENTION_PERIOD,
        ),
        "b": add_employee(
            store["id"], employee_code="EMP-B", retention_bonus_cents=333333,
            attendance_rate=0.92, **RETENTION_PERIOD,
        ),
        "c": add_employee(
            store["id"], employee_code="EMP-C", retention_bonus_cents=400000,
            attendance_rate=0.85, **RETENTION_PERIOD,
        ),
        "d": add_employee(
            store["id"], employee_code="EMP-D", retention_bonus_cents=250000,
            attendance_rate=0.99, **RETENTION_PERIOD,
        ),
    }
    pin_clock("2026-10-16T00:00:00Z")
    run_employment_action(employees["d"]["id"], "TERMINATE_VOLUNTARY")
    close_store(store["id"])
    rows, _meta = validate_paginated(
        api_client.list_store_expense_items(store["id"], make_consultant_headers())
    )
    return {
        "engagement": read_engagement(engagement["id"]),
        "store": store,
        "employees": {key: _read_employee(row["id"]) for key, row in employees.items()},
        "expense_items": rows,
    }


class TestRetentionAccrualRoundingOrder:
    def test_each_entitlement_is_rounded_on_its_own_before_the_accrual_is_summed(self):
        """258,065 plus 172,043 is 430,108, not the 430,107 of a single rounding.

        The PRD says: "The rounding order is pinned as described in §2.5: each
        employee's entitlement is rounded to whole cents first and the accrual is
        the exact integer sum of those rounded figures."

        Design: Difficulty/combinatorial_formula/retention_accrual_round_per_employee_then_sum_not_sum_then_round
        """
        scenario = _store_with_four_enrolled_employees()
        employee_a = scenario["employees"]["a"]
        employee_b = scenario["employees"]["b"]
        assert_employee(employee_a)
        assert_employee(employee_b)
        assert employee_a["served_days"] == 32
        assert employee_a["earned_bonus_cents"] == 258065
        assert employee_a["bonus_status"] == "PRORATED_EARNED"
        assert employee_b["served_days"] == 32
        assert employee_b["earned_bonus_cents"] == 172043
        assert employee_b["bonus_status"] == "PRORATED_EARNED"
        assert scenario["engagement"]["retention_accrual_cents"] == 430108
        assert scenario["engagement"]["retention_accrual_cents"] != 430107

    def test_the_forfeiting_employees_contribute_nothing_to_the_accrual(self):
        """A voluntary quit and a sub-0.90 attendance rate both forfeit outright.

        The PRD says: "An employee who reached `TERMINATED_VOLUNTARY` forfeits
        unconditionally — `bonus_status` becomes `FORFEITED` and
        `earned_bonus_cents` becomes 0, whatever the served days or the attendance
        rate, because a voluntary quit is precisely what the bonus exists to
        discourage."

        Design: Difficulty/combinatorial_formula/retention_accrual_round_per_employee_then_sum_not_sum_then_round
        """
        scenario = _store_with_four_enrolled_employees()
        employee_c = scenario["employees"]["c"]
        employee_d = scenario["employees"]["d"]
        assert employee_c["bonus_status"] == "FORFEITED"
        assert employee_c["earned_bonus_cents"] == 0
        assert employee_d["bonus_status"] == "FORFEITED"
        assert employee_d["earned_bonus_cents"] == 0
        assert employee_d["employment_status"] == "TERMINATED_VOLUNTARY"
        assert scenario["engagement"]["retention_accrual_cents"] == 430108

    def test_the_auto_payroll_item_carries_the_rounded_accrual_and_its_split(self):
        """One auto-generated approved payroll item of 430,108 cents, split 0.40.

        The PRD says: "Under `LIQUIDATOR` responsibility the liquidator's share is
        the item's whole `amount_cents`; under `RETAILER` responsibility it is 0;
        under `SHARED` responsibility it is `amount_cents` multiplied by the
        engagement's `shared_expense_liquidator_pct`, rounded half up to whole
        cents once per item."

        Design: Difficulty/combinatorial_formula/retention_accrual_round_per_employee_then_sum_not_sum_then_round
        """
        scenario = _store_with_four_enrolled_employees()
        auto_items = [row for row in scenario["expense_items"] if row["auto_generated"]]
        assert len(auto_items) == 1
        item = auto_items[0]
        assert item["expense_category"] == "PAYROLL"
        assert item["expense_status"] == "APPROVED"
        assert item["amount_cents"] == 430108
        assert item["liquidator_share_cents"] == 172043
        assert item["retailer_share_cents"] == 258065
        assert_expense_shares_conserved(item)
        engagement = scenario["engagement"]
        assert engagement["expense_total_cents"] == 430108
        assert engagement["expense_liquidator_share_cents"] == 172043
        assert engagement["expense_retailer_share_cents"] == 258065
        assert_engagement_expense_identity(engagement)

    def test_the_closing_cascade_terminates_the_settled_employee_involuntarily(self):
        """The employee who never resigned is terminated on the selling end date.

        The PRD says: "Hop three, caused by the cadence ending, settles every
        employee of the store whose `bonus_status` is `PENDING` by the arithmetic
        above, using the store's `selling_end_date` as the settlement day, and
        moves every one of those employees whose `employment_status` is `ACTIVE` or
        `NOTICE_GIVEN` to `TERMINATED_INVOLUNTARY` with `termination_date` set to
        that same `selling_end_date`."

        Design: Difficulty/combinatorial_formula/retention_accrual_round_per_employee_then_sum_not_sum_then_round
        """
        scenario = _store_with_four_enrolled_employees()
        employee_a = scenario["employees"]["a"]
        assert employee_a["employment_status"] == "TERMINATED_INVOLUNTARY"
        assert employee_a["termination_date"] == "2026-10-16"


def _employee_walked_through_notice_termination_and_payment():
    """One employee taken through every step both dimensions can reach.

    Notice is given on the first day of the retention period, the termination
    lands on the target date so the full 62 days are served, and the store is
    closed for good before the retailer pays, which is the only state from which
    payment is defined.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(
        economics_model="FEE_BASED", guaranty_pct=0, hybrid_retailer_excess_pct=0,
        expense_responsibility="RETAILER", shared_expense_liquidator_pct=0,
        sale_start_date="2026-09-15", target_end_date="2026-11-30",
    )
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-601", address_line="18 Depot St",
    )
    add_inventory_lot(
        store["id"], category="FOOTWEAR", source="ORIGINAL", units_initial=400,
        unit_cost_cents=3000, unit_retail_cents=7000,
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0601",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    employee = add_employee(
        store["id"], employee_code="EMP-N", retention_bonus_cents=500000,
        attendance_rate=0.95, **RETENTION_PERIOD,
    )
    after_notice = run_employment_action(employee["id"], "GIVE_NOTICE")
    pin_clock("2026-11-15T00:00:00Z")
    after_termination = run_employment_action(employee["id"], "TERMINATE_INVOLUNTARY")
    accrual_before_payment = read_engagement(
        engagement["id"]
    )["retention_accrual_cents"]
    close_store(store["id"])
    after_payment = validate_success(
        api_client.pay_bonus(employee["id"], make_controller_headers())
    )
    return {
        "engagement": read_engagement(engagement["id"]),
        "store": store,
        "employee": employee,
        "after_notice": after_notice,
        "after_termination": after_termination,
        "after_payment": after_payment,
        "accrual_before_payment": accrual_before_payment,
    }


class TestEmployeeDimensionsAdvanceIndependently:
    def test_giving_notice_moves_the_employment_dimension_and_nothing_else(self):
        """NOTICE_GIVEN leaves the bonus dimension at PENDING with nothing earned.

        The PRD says: "Giving notice is defined only from `ACTIVE` and takes the
        employee `ACTIVE → NOTICE_GIVEN`, setting `notice_given_date` to the
        current logical-clock date and leaving `bonus_status` untouched at
        `PENDING` — a WARN-style notice is not a termination."

        Design: Difficulty/non_linear_state_machine/employee_employment_and_bonus_dimensions_advance_independently
        """
        after_notice = _employee_walked_through_notice_termination_and_payment()[
            "after_notice"
        ]
        assert_employee(after_notice)
        assert after_notice["employment_status"] == "NOTICE_GIVEN"
        assert after_notice["bonus_status"] == "PENDING"
        assert after_notice["earned_bonus_cents"] == 0
        assert after_notice["notice_given_date"] == "2026-09-15"

    def test_termination_settles_the_bonus_dimension_on_the_full_service_period(self):
        """Sixty-two of sixty-two days served earns the whole bonus outright.

        The PRD says: "Otherwise the service ratio is the served days divided by
        the required days, unrounded, and capped at 1.0; `earned_bonus_cents` is
        `retention_bonus_cents` multiplied by that ratio and rounded half up to
        whole cents; and `bonus_status` becomes `EARNED` when the ratio reached
        exactly 1.0 and `PRORATED_EARNED` when it fell short."

        Design: Difficulty/non_linear_state_machine/employee_employment_and_bonus_dimensions_advance_independently
        """
        after_termination = _employee_walked_through_notice_termination_and_payment()[
            "after_termination"
        ]
        assert after_termination["employment_status"] == "TERMINATED_INVOLUNTARY"
        assert after_termination["bonus_status"] == "EARNED"
        assert after_termination["served_days"] == 62
        assert after_termination["earned_bonus_cents"] == 500000
        assert after_termination["termination_date"] == "2026-11-15"

    def test_payment_moves_the_bonus_dimension_while_employment_stays_put(self):
        """PAID arrives without disturbing the termination or the entitlement.

        The PRD says: "Payment moves the bonus dimension to `PAID` and stamps
        `bonus_paid_at` with the current logical-clock instant;
        `earned_bonus_cents` does not change, and neither does the engagement's
        `retention_accrual_cents`, because `PAID` sits inside the accrual inclusion
        set exactly as `EARNED` does."

        Design: Difficulty/non_linear_state_machine/employee_employment_and_bonus_dimensions_advance_independently
        """
        scenario = _employee_walked_through_notice_termination_and_payment()
        after_payment = scenario["after_payment"]
        assert after_payment["bonus_status"] == "PAID"
        assert after_payment["employment_status"] == "TERMINATED_INVOLUNTARY"
        assert after_payment["earned_bonus_cents"] == 500000
        assert_instant_equals(
            after_payment["bonus_paid_at"], "2026-11-15T00:00:00Z", "bonus_paid_at"
        )
        assert scenario["accrual_before_payment"] == 500000
        assert scenario["engagement"]["retention_accrual_cents"] == 500000
