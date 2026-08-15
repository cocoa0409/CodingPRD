"""Activation, first-payment scheduling, and immediate consistency (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    ADMIN,
    setup_priced_unit,
    create_and_approve_contract, create_and_activate_contract,
    list_hap_payments,
    assert_hap_payment,
)


class TestFirstPaymentMonthBoundary:
    def _activate_with_lease_start(self, api, lease_start_date, unit_label, family_code):
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90012", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code=family_code,
        )
        contract = create_and_approve_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date=lease_start_date,
        )
        data = validate_success(api.activate_contract(contract["id"], ADMIN))
        return data

    def test_lease_start_day_one_first_payment_same_month(self, api):
        """PRD §3.5: "If the day-of-month of `lease_start_date` is 1, the first
        payment's `period_month` is the first of that same month."

        Design: Difficulty/boundary_precision_check/first_payment_month_aligned_vs_mid_month_boundary
        """
        data = self._activate_with_lease_start(api, "2026-08-01", "UA", "FA")
        payments = list_hap_payments(data["id"])
        assert len(payments) == 1, (
            f"exactly one HAPPayment row is created at activation, got {len(payments)}"
        )
        assert payments[0]["period_month"] == "2026-08-01", (
            f"day-of-month == 1: expected period_month 2026-08-01, got "
            f"{payments[0]['period_month']}"
        )
        assert payments[0]["disbursement_status"] == "SCHEDULED"
        assert payments[0]["hap_amount_cents"] == data["hap_portion_cents"]

    def test_lease_start_day_two_first_payment_following_month(self, api):
        """PRD §3.5: "If the lease starts on any day from the 2nd through the
        31st, the first payment's `period_month` is the first of the following
        month — the partial first month is the landlord's responsibility and no
        prorated HAP is paid for it."

        Design: Difficulty/boundary_precision_check/first_payment_month_aligned_vs_mid_month_boundary
        """
        # PRD §3.5 precondition: activation requires the current logical date to
        # be on or after lease_start_date, so advance the clock to 2026-08-02.
        get_success_data(api.set_current_utc("2026-08-02T00:00:00Z", ADMIN))
        data = self._activate_with_lease_start(api, "2026-08-02", "UB", "FB")
        payments = list_hap_payments(data["id"])
        assert len(payments) == 1
        assert payments[0]["period_month"] == "2026-09-01", (
            f"day-of-month >= 2: expected period_month 2026-09-01, got "
            f"{payments[0]['period_month']}"
        )
        assert payments[0]["disbursement_status"] == "SCHEDULED"


class TestImmediateVisibilityOfActivationEffects:
    def test_activate_response_and_payment_visible_immediately(self, api):
        """PRD §3.5: "Activation does four things. First, it sets
        `next_recert_due_date` to the date one year after `lease_start_date` —
        the first annual recertification anniversary. Second, it moves the
        linked voucher family from `SEARCHING` to `LEASED`. Third, it schedules
        the first `HAPPayment` row. Fourth, it increments the contract's
        `version`."
        PRD §3.5: "Either way, exactly one `HAPPayment` row is created at
        activation: its `period_month` set as just described, its
        `hap_amount_cents` equal to the contract's `hap_portion_cents`, and its
        `disbursement_status` set to `SCHEDULED`."

        Design: Corner/consistency_model/immediate_visibility_of_activation_effects
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90315", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="CF17",
        )
        contract = create_and_approve_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-08-01",
        )
        data = validate_success(api.activate_contract(contract["id"], ADMIN))
        assert data["status"] == "ACTIVE"
        assert data["next_recert_due_date"] == "2027-08-01", (
            f"next_recert_due_date must be one year after lease_start_date, got "
            f"{data['next_recert_due_date']}"
        )
        payments = list_hap_payments(contract["id"])
        assert len(payments) == 1
        assert payments[0]["period_month"] == "2026-08-01"
        assert payments[0]["disbursement_status"] == "SCHEDULED"

    def test_activation_moves_family_to_leased(self, api):
        """PRD §3.5: "Activation does four things. First, it sets
        `next_recert_due_date` to the date one year after `lease_start_date` —
        the first annual recertification anniversary. Second, it moves the
        linked voucher family from `SEARCHING` to `LEASED`. Third, it schedules
        the first `HAPPayment` row. Fourth, it increments the contract's
        `version`."

        Design: Corner/consistency_model/immediate_visibility_of_activation_effects
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90315", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="CF17b",
        )
        contract = create_and_activate_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-08-01",
        )
        fam = get_success_data(api.get_voucher_family(family["id"], ADMIN))
        assert fam["status"] == "LEASED", (
            f"activation must move the family SEARCHING -> LEASED, got {fam['status']}"
        )
