"""Carrier concentration restriction and the capacity a withdrawal gives back."""
import pytest
from test_helpers import validate_error, validate_success
from test_helpers.fixtures import (
    ANALYST,
    RISK,
    TREASURY,
    authorized_carrier_with_product,
    diligence_cleared_request,
    in_force_policy,
    insured_employee,
    post_valuation,
    reserve_capacity,
    reserved_capacity_request,
)


OKONJO = {
    "full_name": "Ada Okonjo",
    "employee_number": "E-6301",
    "annual_salary_usd": 4_000_000.00,
    "officer_flag": True,
}

NAKAMURA = {
    "full_name": "Rei Nakamura",
    "employee_number": "E-6401",
    "annual_salary_usd": 3_000_000.00,
    "officer_flag": True,
}

SEQUOIA = {
    "legal_name": "Sequoia Life",
    "naic_code": "62061",
    "domicile_state": "CA",
}

WILLOW = {
    "legal_name": "Willow Life",
    "naic_code": "62071",
    "domicile_state": "OR",
}


def _sequoia_placement(api):
    """Place a large policy against an AUTHORIZED carrier, just inside the band."""
    return in_force_policy(
        api,
        carrier_overrides=SEQUOIA,
        product_overrides={"product_name": "Sequoia GA BOLI"},
        employee_overrides=OKONJO,
        request_overrides={
            "single_premium_usd": 149_000_000.00,
            "face_amount_usd": 447_000_000.00,
        },
        policy_overrides={"policy_number": "SQ-0001"},
    )


def _restrict_sequoia(api, context):
    """Value the placed policy so the carrier crosses the restrict band."""
    context["valuation"] = post_valuation(
        api,
        context["policy_id"],
        credited_interest_usd=6_500_000.00,
        mortality_expense_charge_usd=500_000.00,
        gross_crediting_rate_bps=440,
    )
    return context


def _restricted_sequoia(api):
    """Place a large policy and value it so the carrier crosses the restrict band."""
    return _restrict_sequoia(api, _sequoia_placement(api))


class TestCarrierRestrictionFromConcentration:
    def test_valuation_growth_pushes_the_carrier_into_the_restricted_band(self, api):
        """Cash value growth alone moves an AUTHORIZED carrier into RESTRICTED.

        "`concentration_bps` expresses the carrier's `in_force_cash_value_usd`
        as basis points of the latest snapshot's `tier1_capital_usd`". Posting
        the period lifts the cash value to 155,000,000.00 against
        1,000,000,000.00 of tier-1 capital, which is 1550 basis points, and "A
        carrier in `AUTHORIZED` moves to `RESTRICTED` as soon as its recomputed
        `concentration_bps` reaches 1500 or more". The measured charge is 34
        basis points against a disclosed 20, a drift of 14, so the product does
        not go on watch.

        Design: Difficulty/cross_entity_state_dependency/reserve_capacity_blocked_while_owning_carrier_is_restricted
        """
        context = _restricted_sequoia(api)
        valuation = context["valuation"]

        assert valuation["prior_cash_value_usd"] == pytest.approx(149_000_000.00, abs=0.01)
        assert valuation["cash_value_usd"] == pytest.approx(155_000_000.00, abs=0.01), (
            "prior cash value plus credited interest less the mortality charge"
        )
        assert valuation["me_charge_bps"] == 34
        assert valuation["me_drift_bps"] == 14
        assert valuation["net_yield_bps"] == 403

        product = validate_success(api.get_product_type(context["product_type_id"], TREASURY))
        assert product["status"] == "OPEN", "a drift of 14 basis points is inside tolerance"

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["in_force_cash_value_usd"] == pytest.approx(155_000_000.00, abs=0.01)
        assert carrier["concentration_bps"] == 1550
        assert carrier["status"] == "RESTRICTED"

    def test_reserving_against_a_restricted_carrier_is_refused_despite_headroom(self, api):
        """The restricted posture blocks the reservation before any limit is measured.

        "The product type must not be `CLOSED_TO_NEW`, reported as
        `ERR_PRODUCT_CLOSED_TO_NEW`. The carrier must not be `RESTRICTED`,
        `SUSPENDED` or `TERMINATED`, since a reservation adds exposure, and any
        of those postures is reported as `ERR_CARRIER_RESTRICTED` (HTTP 422)."
        The projection shows the request
        would otherwise fit — 1500 basis points of concentration against a 1500
        ceiling and 100,000,000.00 of headroom — yet the carrier's posture stops
        it, and the refusal claims none of the carrier's capacity.

        Design: Difficulty/cross_entity_state_dependency/reserve_capacity_blocked_while_owning_carrier_is_restricted
        """
        context = _sequoia_placement(api)

        # Clearance requires an AUTHORIZED carrier, so the sibling request is
        # carried to DILIGENCE_CLEARED before the valuation restricts the carrier.
        second = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            context["employee_id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
        )
        _restrict_sequoia(api, context)
        assert (
            validate_success(api.get_carrier(context["carrier_id"], TREASURY))["status"]
            == "RESTRICTED"
        )

        projection = validate_success(api.get_capacity_projection(second["id"], TREASURY))
        assert projection["carrier_concentration_bps"] == 1500
        assert projection["single_carrier_limit_bps"] == 1500
        assert projection["base_ratio_bps"] == 6000
        assert projection["effective_limit_pct"] == pytest.approx(0.25, abs=0.0001)
        assert projection["aggregate_limit_usd"] == pytest.approx(250_000_000.00, abs=0.01)
        assert projection["headroom_usd"] == pytest.approx(100_000_000.00, abs=0.01)

        validate_error(
            reserve_capacity(api, second["id"], context["carrier_id"]),
            "ERR_CARRIER_RESTRICTED",
            422,
        )

        after = validate_success(api.get_purchase_request(second["id"], TREASURY))
        assert after["status"] == "DILIGENCE_CLEARED"
        assert after["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        carrier_after = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier_after["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)


class TestWithdrawalRestoresCapacity:
    def test_reservation_consumes_headroom_and_raises_measured_concentration(self, api):
        """A reservation is real capacity: it moves the projection for its sibling.

        On a successful reservation "`reserved_premium_usd` on the request is set
        to the request's `single_premium_usd`. The same premium is added to the
        carrier's `reserved_premium_usd`", and because the committed figure feeds every
        later measurement the sibling request's projection rises from 800 to
        1600 basis points of base ratio and its headroom falls by the reserved
        premium.

        Design: Difficulty/compensating_invariant/withdraw_restores_reserved_premium_and_capacity_headroom
        """
        context = authorized_carrier_with_product(
            api,
            carrier_overrides=WILLOW,
            product_overrides={"product_name": "Willow GA BOLI"},
        )
        insured = insured_employee(api, employee_overrides=NAKAMURA)

        first = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=20_000_000.00,
            face_amount_usd=60_000_000.00,
        )
        sibling = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=20_000_000.00,
            face_amount_usd=60_000_000.00,
        )

        before = validate_success(api.get_capacity_projection(sibling["id"], TREASURY))
        assert before["base_ratio_bps"] == 800
        assert before["aggregate_limit_usd"] == pytest.approx(250_000_000.00, abs=0.01)
        assert before["headroom_usd"] == pytest.approx(230_000_000.00, abs=0.01)
        assert before["carrier_concentration_bps"] == 200

        reserved = reserved_capacity_request(api, first["id"], context["carrier_id"])
        assert reserved["status"] == "CAPACITY_RESERVED"
        assert reserved["reserved_premium_usd"] == pytest.approx(20_000_000.00, abs=0.01)

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["reserved_premium_usd"] == pytest.approx(20_000_000.00, abs=0.01)

        after = validate_success(api.get_capacity_projection(sibling["id"], TREASURY))
        assert after["base_ratio_bps"] == 1600, (
            "the committed figure now carries the sibling's reservation"
        )
        assert after["headroom_usd"] == pytest.approx(210_000_000.00, abs=0.01)
        assert after["carrier_concentration_bps"] == 400

    def test_withdrawing_the_reserved_request_gives_the_headroom_back_exactly(self, api):
        """Withdrawal releases the reservation and the projection returns to its opening figures.

        Withdrawal drives the request "to `WITHDRAWN` with exactly the same
        premium release, the same carrier `version` increment and the same
        zeroing" that rejection performs, where "the request's
        `reserved_premium_usd` is subtracted from the carrier's
        `reserved_premium_usd`" and "the request's `reserved_premium_usd` is set
        to 0.00". The acting operator must be the submitter, because "Withdrawal
        additionally requires that the acting `X-User-ID` equal the request's
        `submitted_by_user_id`". After the release the sibling's projection is
        identical to the projection taken before any reservation existed.

        Design: Difficulty/compensating_invariant/withdraw_restores_reserved_premium_and_capacity_headroom
        """
        context = authorized_carrier_with_product(
            api,
            carrier_overrides=WILLOW,
            product_overrides={"product_name": "Willow GA BOLI"},
        )
        insured = insured_employee(api, employee_overrides=NAKAMURA)

        first = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=20_000_000.00,
            face_amount_usd=60_000_000.00,
        )
        sibling = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=20_000_000.00,
            face_amount_usd=60_000_000.00,
        )

        opening = validate_success(api.get_capacity_projection(sibling["id"], TREASURY))
        reserved_capacity_request(api, first["id"], context["carrier_id"])

        withdrawn = validate_success(api.withdraw_purchase_request(first["id"], ANALYST))
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["in_force_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["in_force_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["concentration_bps"] == 0

        restored = validate_success(api.get_capacity_projection(sibling["id"], TREASURY))
        assert restored["committed_usd"] == pytest.approx(opening["committed_usd"], abs=0.01)
        assert restored["prospective_usd"] == pytest.approx(opening["prospective_usd"], abs=0.01)
        assert restored["base_ratio_bps"] == opening["base_ratio_bps"]
        assert restored["aggregate_limit_usd"] == pytest.approx(
            opening["aggregate_limit_usd"], abs=0.01
        )
        assert restored["headroom_usd"] == pytest.approx(opening["headroom_usd"], abs=0.01), (
            "the released reservation restores the headroom exactly"
        )
        assert restored["carrier_concentration_bps"] == opening["carrier_concentration_bps"]

        sibling_after = validate_success(api.get_purchase_request(sibling["id"], RISK))
        assert sibling_after["status"] == "DILIGENCE_CLEARED", (
            "the sibling request is untouched by the withdrawal"
        )
