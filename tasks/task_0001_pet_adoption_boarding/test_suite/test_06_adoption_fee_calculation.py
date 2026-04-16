"""Adoption fee calculation — PRD §3.5."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    setup_approved_application,
    SENIOR_AGE_MONTHS, SENIOR_DISCOUNT,
)


class TestAdoptionFeePinned:
    def test_pinned_fee_is_base_when_no_override_and_adult(self):
        """PRD §3.5: "if adoption_fee_override is set on the animal, that value is the fee;
        otherwise the fee is the parent shelter's adoption_fee_base"."""
        ctx = setup_approved_application(adoption_fee_base=15000, age_months=24)
        assert ctx["application"]["pinned_fee"] == 15000

    def test_pinned_fee_uses_override_when_set(self):
        """PRD §3.5: "if adoption_fee_override is set on the animal, that value is the fee"."""
        ctx = setup_approved_application(
            adoption_fee_base=15000, adoption_fee_override=9999, age_months=24)
        assert ctx["application"]["pinned_fee"] == 9999

    def test_senior_discount_halves_fee_at_boundary(self):
        """PRD §3.5: "If the animal's age_months is at least 96 ... the fee is halved
        under the senior discount (SENIOR_DISCOUNT of 0.5)" — at exactly 96 months."""
        ctx = setup_approved_application(
            adoption_fee_base=20000, age_months=SENIOR_AGE_MONTHS)  # 96
        # 20000 * 0.5 = 10000
        assert ctx["application"]["pinned_fee"] == 10000

    def test_senior_discount_not_applied_below_boundary(self):
        """PRD §3.5: boundary is strict ">=" — 95 months is NOT senior."""
        ctx = setup_approved_application(
            adoption_fee_base=20000, age_months=SENIOR_AGE_MONTHS - 1)  # 95
        assert ctx["application"]["pinned_fee"] == 20000

    def test_senior_discount_with_override_half_round_up(self):
        """PRD §3.5 + §2.6: "rounded half up to whole cents" — senior discount
        applied to override value. Odd cent triggers round-half-up."""
        # odd override 9999 cents -> halve -> 4999.5 -> round half up -> 5000
        ctx = setup_approved_application(
            adoption_fee_base=12345,
            adoption_fee_override=9999,
            age_months=SENIOR_AGE_MONTHS,
        )
        assert ctx["application"]["pinned_fee"] == 5000

    def test_senior_discount_with_override_even(self):
        """PRD §3.5: senior discount applies to override value, half of even number is exact."""
        ctx = setup_approved_application(
            adoption_fee_override=40000,
            age_months=SENIOR_AGE_MONTHS + 12,
            adoption_fee_base=12345,
        )
        assert ctx["application"]["pinned_fee"] == 20000
