"""Prepay balance, account-status thresholds, deposits, and cascade side effects."""
from test_helpers import (
    validate_success,
    create_site, create_student, deposit, setup_prepared_lunch_site,
    create_funded_student, record_meal,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["pos_clerk_headers"]

REIMBURSABLE = ["MEAT_MEAT_ALT", "GRAINS", "FRUIT"]


# ==========================================================================
# Boundary precision: low-balance threshold is inclusive (<=)
# ==========================================================================
class TestLowBalanceThresholdBoundary:
    def test_balance_exactly_at_threshold_is_low_balance(self, api):
        """PRD §3.5: "it is `LOW_BALANCE` when `balance_cents` is at or above 0 and at or below `low_balance_threshold_cents` (the threshold comparison is inclusive at both ends)".

        Design: Difficulty/boundary_precision_check/low_balance_threshold_inclusive_at_exact_boundary
        """
        site = create_site(api)
        student = create_student(api, site["id"], eligibility_category="PAID",
                                 low_balance_threshold_cents=500)
        updated = deposit(api, student["id"], 500)  # balance exactly at the threshold
        assert updated["balance_cents"] == 500
        assert updated["account_status"] == "LOW_BALANCE", f"got {updated['account_status']}"

    def test_balance_one_cent_above_threshold_is_active(self, api):
        """PRD §3.5: "it is `ACTIVE` when `balance_cents` is strictly greater than `low_balance_threshold_cents`."

        Design: Difficulty/boundary_precision_check/low_balance_threshold_inclusive_at_exact_boundary
        """
        site = create_site(api)
        student = create_student(api, site["id"], eligibility_category="PAID",
                                 low_balance_threshold_cents=500)
        updated = deposit(api, student["id"], 501)  # one cent above the threshold
        assert updated["balance_cents"] == 501
        assert updated["account_status"] == "ACTIVE", f"got {updated['account_status']}"


# ==========================================================================
# Transitive cascade: meal charge -> balance -> account_status -> site counter
# ==========================================================================
class TestMealChargeCascade:
    def _charge_paid_student_into_negative(self, api):
        scenario = setup_prepared_lunch_site(
            api, site_overrides={"negative_balance_allowed": True, "paid_lunch_price_cents": 300})
        student = create_student(api, scenario["site_id"], eligibility_category="PAID")  # balance 0
        mt = record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                         selected_components=REIMBURSABLE)
        return scenario, student["id"], mt

    def test_charge_drives_balance_negative_and_flips_status(self, api):
        """PRD §3.6: "The `meal_charge_cents` is the amount charged to the student's prepay account"
        PRD §3.6: "a `PAID` student is charged the site's `paid_lunch_price_cents` for lunch or `paid_breakfast_price_cents` for breakfast."
        PRD §3.6: "Charging the student decreases `balance_cents` by `meal_charge_cents`, recomputes `account_status`, and — if the student thereby flips into the `NEGATIVE` posture — increments the owning site's `negative_balance_count`."

        Design: Difficulty/transitive_cascade/meal_charge_cascade_to_site_negative_counter
        """
        _scenario, student_id, mt = self._charge_paid_student_into_negative(api)
        assert mt["meal_charge_cents"] == 300, f"expected charge 300, got {mt['meal_charge_cents']}"
        student = validate_success(api.get_student(student_id, ADMIN), 200)
        assert student["balance_cents"] == -300, f"expected -300, got {student['balance_cents']}"
        assert student["account_status"] == "NEGATIVE", f"got {student['account_status']}"

    def test_negative_flip_increments_site_negative_balance_count(self, api):
        """PRD §3.6: "Charging the student decreases `balance_cents` by `meal_charge_cents`, recomputes `account_status`, and — if the student thereby flips into the `NEGATIVE` posture — increments the owning site's `negative_balance_count`."

        Design: Difficulty/transitive_cascade/meal_charge_cascade_to_site_negative_counter
        """
        scenario, _student_id, _mt = self._charge_paid_student_into_negative(api)
        site = validate_success(api.get_site(scenario["site_id"], ADMIN), 200)
        assert site["negative_balance_count"] == 1, f"expected 1, got {site['negative_balance_count']}"


# ==========================================================================
# Compensating invariant: charge then void conserves prepay money
# ==========================================================================
class TestPrepayMoneyConservation:
    def _charge_then_void(self, api):
        scenario = setup_prepared_lunch_site(
            api, site_overrides={"negative_balance_allowed": True, "paid_lunch_price_cents": 300})
        student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID",
                                        deposit_cents=1000)
        mt = record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                         selected_components=REIMBURSABLE)  # charge 300 -> balance 700
        void_resp = api.void_meal_transaction(mt["id"], CLERK)
        return student["id"], void_resp

    def test_void_restores_balance_and_active_status(self, api):
        """PRD §3.6: "A void sets `meal_claim_status` to `VOIDED` and `payment_status` to `REFUNDED`, and runs the compensating refund: `balance_cents` increases by exactly the original `meal_charge_cents`, `account_status` is recomputed, and if the student thereby leaves the `NEGATIVE` posture the site's `negative_balance_count` is decremented."
        PRD §3.6: "This preserves the prepay money-conservation invariant that a charge followed by its void nets to zero."

        Design: Difficulty/compensating_invariant/prepay_money_conserved_across_charge_and_void
        """
        student_id, _void_resp = self._charge_then_void(api)
        student = validate_success(api.get_student(student_id, ADMIN), 200)
        assert student["balance_cents"] == 1000, f"charge+void must net to the 1000 deposit, got {student['balance_cents']}"
        assert student["account_status"] == "ACTIVE", f"got {student['account_status']}"

    def test_void_sets_payment_status_refunded(self, api):
        """PRD §3.6: "A void sets `meal_claim_status` to `VOIDED` and `payment_status` to `REFUNDED`, and runs the compensating refund: `balance_cents` increases by exactly the original `meal_charge_cents`".

        Design: Difficulty/compensating_invariant/prepay_money_conserved_across_charge_and_void
        """
        _student_id, void_resp = self._charge_then_void(api)
        data = validate_success(void_resp, 200)
        assert data["payment_status"] == "REFUNDED", f"got {data['payment_status']}"


# ==========================================================================
# Corner: deposit is immediately reflected in the response
# ==========================================================================
def test_deposit_immediately_reflected_in_response(api):
    """PRD §3.5: "A `POSClerk` adds funds through a deposit carrying an `amount_cents`; the deposit increases `balance_cents`, recomputes `account_status`, and — if the student thereby leaves the `NEGATIVE` posture — decrements the owning site's `negative_balance_count`."

    Design: Corner/consistency_model/deposit_immediately_visible_in_response
    """
    site = create_site(api)
    student = create_student(api, site["id"], eligibility_category="PAID",
                             low_balance_threshold_cents=500)
    updated = deposit(api, student["id"], 1000)
    assert updated["balance_cents"] == 1000
    assert updated["account_status"] == "ACTIVE", f"got {updated['account_status']}"
