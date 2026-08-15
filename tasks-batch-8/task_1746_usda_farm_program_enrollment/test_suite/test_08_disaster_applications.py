"""Disaster applications: the 35% loss threshold and the approval-triggered
yield-substitution/payment-recompute cascade (PRD §3.9, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_disaster_application,
    setup_disaster_under_review,
    setup_payment_computed_enrollment,
    validate_error,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


class TestLossThreshold:
    def test_loss_exactly_35_percent_approved(self, api, specialist):
        """PRD §3.9: "Committee approval applies the thirty-five percent
        trigger: the claimed `loss_acres` must be at least thirty-five percent
        of the reported acres for the `qualifying_commodity`, an ELAP-style
        qualification gate whose failure is rejected with
        `ERR_LOSS_THRESHOLD_NOT_MET`."

        35.00 loss acres against 100.00 reported acres is exactly 35%, which
        satisfies "at least thirty-five percent".

        Design: Difficulty/boundary_precision_check/disaster_loss_threshold_exactly_35_percent
        """
        ctx, application = setup_disaster_under_review(
            loss_acres=35.00, disaster_type="FLOOD"
        )
        resp = api.approve_disaster_application(
            application["id"], ctx["committee_headers"]
        )
        approved = validate_success(resp, 200)
        assert_disaster_application(approved)
        assert approved["application_status"] == "APPROVED", (
            f"loss at exactly 35% of reported acres must pass, got "
            f"{approved['application_status']}"
        )

    def test_loss_just_below_35_percent_rejected(self, api, specialist):
        """PRD §3.9: "the claimed `loss_acres` must be at least thirty-five
        percent of the reported acres for the `qualifying_commodity`, an
        ELAP-style qualification gate whose failure is rejected with
        `ERR_LOSS_THRESHOLD_NOT_MET`."

        34.99 loss acres against 100.00 reported acres is below 35%.

        Design: Difficulty/boundary_precision_check/disaster_loss_threshold_exactly_35_percent
        """
        ctx, application = setup_disaster_under_review(loss_acres=34.99)
        resp = api.approve_disaster_application(
            application["id"], ctx["committee_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_LOSS_THRESHOLD_NOT_MET.value)

    def test_loss_below_threshold_rejected(self, api, specialist):
        """PRD §3.9: "the claimed `loss_acres` must be at least thirty-five
        percent of the reported acres for the `qualifying_commodity`, an
        ELAP-style qualification gate whose failure is rejected with
        `ERR_LOSS_THRESHOLD_NOT_MET`."

        30.00 loss acres against 100.00 reported acres is below 35%.

        Design: Corner/state_machines/disaster_approve_requires_35_percent_threshold
        """
        ctx, application = setup_disaster_under_review(
            loss_acres=30.00, disaster_type="HAIL"
        )
        resp = api.approve_disaster_application(
            application["id"], ctx["committee_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_LOSS_THRESHOLD_NOT_MET.value)


class TestYieldSubstitutionCascade:
    def _setup_cascade(self, api, specialist):
        """PAYMENT_COMPUTED enrollment with one sub-65%-of-T observation year
        (2024 actual 100.0 vs 0.65 x 180 = 117.0), plus a qualifying disaster
        application in UNDER_REVIEW."""
        ctx = setup_payment_computed_enrollment(
            yields=(180.0, 180.0, 180.0, 100.0, 180.0),
            compute_inputs={"national_my_price": 3.50},
        )
        # APH before substitution: (180*4 + 100)/5 = 164.0; PLC base
        # 0.60 x 164.0 x 100 x 0.85 = 8364.00; sequestration
        # round(8364 x 0.057, 2) = 476.75; net 7887.25 -> 788725.
        assert ctx["enrollment"]["computed_payment_cents"] == 788725, (
            f"pre-disaster net payment must be 788725 cents, got "
            f"{ctx['enrollment']['computed_payment_cents']}"
        )
        ctx, application = setup_disaster_under_review(
            ctx, loss_acres=40.00, disaster_type="DROUGHT"
        )
        return ctx, application

    def test_approval_substitutes_yield_and_recomputes_aph(self, api, specialist):
        """PRD §3.9: "Approval moves the application to `APPROVED` and triggers
        a yield-substitution cascade: for each yield observation on the same
        farm and qualifying commodity whose actual yield is below sixty-five
        percent of the commodity's T-yield, `is_disaster_substituted` is set to
        true and sixty-five percent of the T-yield is substituted into the APH
        recompute."
        PRD §3.5: "The `aph_yield_bu_per_acre` is the sum of the five effective
        yields divided by five, rounded half-up to one decimal place."

        The 2024 observation (100.0 < 0.65 x 180 = 117.0) is substituted:
        APH after = (180*4 + 117.0)/5 = 167.4.

        Design: Difficulty/transitive_cascade/disaster_approval_yield_substitution_payment_recompute
        """
        ctx, application = self._setup_cascade(api, specialist)
        resp = api.approve_disaster_application(
            application["id"], ctx["committee_headers"]
        )
        validate_success(resp, 200)
        record = validate_success(
            api.get_yield_record(ctx["yield_record"]["id"], specialist), 200
        )
        assert record["aph_yield_bu_per_acre"] == pytest.approx(167.4), (
            f"APH after disaster substitution must be 167.4, got "
            f"{record['aph_yield_bu_per_acre']}"
        )

    def test_approval_recomputes_pinned_enrollment_payment(self, api, specialist):
        """PRD §3.9: "The pinned yield record on any `CERTIFIED` enrollment for
        the same farm and commodity is re-evaluated, and if that enrollment is
        `PAYMENT_COMPUTED` or `PAYMENT_ISSUED` the payment delta is recomputed."
        PRD §3.8: "The base payment is the payment rate multiplied by the
        enrollment's `aph_yield_bu_per_acre`, multiplied by the base acres on
        the enrollment, multiplied by the statutory payment factor of 0.85."

        After substitution APH rises 164.0 -> 167.4: base 0.60 x 167.4 x 100 x
        0.85 = 8537.40; sequestration round(8537.40 x 0.057, 2) = 486.63; net
        8050.77 -> 805077 cents, differing from the pre-approval 788725.

        Design: Difficulty/transitive_cascade/disaster_approval_yield_substitution_payment_recompute
        """
        ctx, application = self._setup_cascade(api, specialist)
        resp = api.approve_disaster_application(
            application["id"], ctx["committee_headers"]
        )
        validate_success(resp, 200)
        enrollment = validate_success(
            api.get_enrollment(ctx["enrollment"]["id"], specialist), 200
        )
        assert enrollment["computed_payment_cents"] == 805077, (
            f"recomputed net payment must be 805077 cents, got "
            f"{enrollment['computed_payment_cents']}"
        )
        assert enrollment["computed_payment_cents"] != 788725
