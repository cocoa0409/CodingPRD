"""Capacity measurement: the pinned tier ladder and the order the capacity gates fire in."""
import pytest
from test_helpers import validate_error, validate_success
from test_helpers.assertions import assert_capacity_projection_shape
from test_helpers.fixtures import (
    RISK,
    TREASURY,
    authorized_carrier_with_product,
    current_carrier_version,
    diligence_cleared_request,
    draft_purchase_request,
    file_capital_position,
    insured_employee,
    onboard_carrier,
    register_employee,
    register_product_type,
    reserve_capacity,
    reserved_capacity_request,
    submitted_purchase_request,
)


HALLORAN = {
    "full_name": "Nora Halloran",
    "employee_number": "E-6201",
    "annual_salary_usd": 2_000_000.00,
    "officer_flag": True,
}


class TestCapacityTierLadder:
    def test_base_ratio_of_exactly_six_thousand_keeps_the_quarter_limit(self, api):
        """A prospective ratio sitting exactly on the first break stays at 25 percent.

        The projection is a read-only what-if: "A `RiskOfficer` or a
        `TreasuryController` can run the whole computation read-only as a
        what-if projection against any request, without reserving anything and
        without mutating any resource." A 150,000,000.00 premium against a
        250,000,000.00 base limit gives a base ratio of exactly 6000, and the
        ladder specifies "twenty-five hundredths when `base_ratio_bps` is 6000
        or less".

        Design: Difficulty/combinatorial_formula/capacity_tier_break_pinned_single_pass_evaluation
        """
        file_capital_position(api)
        carrier = onboard_carrier(
            api,
            legal_name="Sentinel Life",
            naic_code="62031",
            am_best_rating="A_PLUS",
            statutory_surplus_usd=400_000_000.00,
            domicile_state="TX",
        )
        product = register_product_type(api, carrier["id"], product_name="Sentinel GA BOLI")
        employee = register_employee(api, **HALLORAN)
        request = draft_purchase_request(
            api,
            carrier["id"],
            product["id"],
            employee["id"],
            single_premium_usd=150_000_000.00,
            face_amount_usd=450_000_000.00,
        )

        projection = validate_success(api.get_capacity_projection(request["id"], TREASURY))
        assert_capacity_projection_shape(projection)
        assert projection["tier1_capital_usd"] == pytest.approx(1_000_000_000.00, abs=0.01)
        assert projection["base_limit_usd"] == pytest.approx(250_000_000.00, abs=0.01), (
            "the base limit is tier-1 capital multiplied by twenty-five hundredths"
        )
        assert projection["committed_usd"] == pytest.approx(0.00, abs=0.01)
        assert projection["prospective_usd"] == pytest.approx(150_000_000.00, abs=0.01), (
            "the request's own premium is always included in the prospective figure"
        )
        assert projection["base_ratio_bps"] == 6000
        assert projection["effective_limit_pct"] == pytest.approx(0.25, abs=0.0001)
        assert projection["aggregate_limit_usd"] == pytest.approx(250_000_000.00, abs=0.01)
        assert projection["headroom_usd"] == pytest.approx(100_000_000.00, abs=0.01)
        assert projection["carrier_concentration_bps"] == 1500
        assert projection["single_carrier_limit_bps"] == 1500, (
            "a GENERAL account product carries the 1500 basis point ceiling"
        )

    def test_one_basis_point_past_the_break_tightens_the_aggregate_limit(self, api):
        """A ratio of 6001 selects the 22 percent tier in the same single pass.

        "It is executed exactly once per request; there is no second pass, and
        the tier chosen is never re-derived from the limit it produced." A
        150,012,500.00 premium rounds the base ratio half up to 6001, which
        selects "twenty-two hundredths when `base_ratio_bps` is greater than
        6000 and at most 8500" — and the ratio is not recomputed against the
        220,000,000.00 aggregate limit that tier produces. The projection
        mutates nothing, so the request is still in DRAFT with the capacity
        figures a drafted request opens with.

        Design: Difficulty/combinatorial_formula/capacity_tier_break_pinned_single_pass_evaluation
        """
        file_capital_position(api)
        carrier = onboard_carrier(
            api,
            legal_name="Sentinel Life",
            naic_code="62031",
            am_best_rating="A_PLUS",
            statutory_surplus_usd=400_000_000.00,
            domicile_state="TX",
        )
        product = register_product_type(api, carrier["id"], product_name="Sentinel GA BOLI")
        employee = register_employee(api, **HALLORAN)
        request = draft_purchase_request(
            api,
            carrier["id"],
            product["id"],
            employee["id"],
            single_premium_usd=150_012_500.00,
            face_amount_usd=450_000_000.00,
        )

        projection = validate_success(api.get_capacity_projection(request["id"], TREASURY))
        assert projection["base_ratio_bps"] == 6001, (
            "150,012,500.00 over the base limit is 6000.5 basis points, rounded half up"
        )
        assert projection["effective_limit_pct"] == pytest.approx(0.22, abs=0.0001)
        assert projection["aggregate_limit_usd"] == pytest.approx(220_000_000.00, abs=0.01)
        assert projection["headroom_usd"] == pytest.approx(69_987_500.00, abs=0.01)
        assert projection["carrier_concentration_bps"] == 1500, (
            "1500.125 basis points of concentration rounds half up to 1500"
        )

        request_after = validate_success(api.get_purchase_request(request["id"], TREASURY))
        assert request_after["status"] == "DRAFT", "the projection reserves nothing"
        assert request_after["headroom_usd"] == pytest.approx(0.00, abs=0.01), (
            "a drafted request carries no frozen capacity figures yet"
        )
        assert request_after["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        carrier_after = validate_success(api.get_carrier(carrier["id"], TREASURY))
        assert carrier_after["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)


class TestCapacityGateOrdering:
    def test_illegal_state_outranks_the_capital_headroom_breach(self, api):
        """A request in the wrong state reports the state error, not the capital error.

        The validation ladder runs "then the terminal-state check, then the
        transition-legality check, then the optimistic-concurrency check" long
        before "and finally the fiscal-capacity family", so a SUBMITTED request
        that would also blow the aggregate headroom reports
        `ERR_INVALID_STATE_TRANSITION` from the higher band. Reserving capacity
        "advances the request `DILIGENCE_CLEARED → CAPACITY_RESERVED`", which a
        SUBMITTED request cannot take.

        Design: Difficulty/priority_pair_validation_conflict/state_transition_error_outranks_capital_capacity_breach
        """
        file_capital_position(api)
        alder = authorized_carrier_with_product(
            api,
            carrier_overrides={
                "legal_name": "Alder Life",
                "naic_code": "62041",
                "domicile_state": "OH",
            },
            product_overrides={"product_name": "Alder GA BOLI"},
        )
        birch = authorized_carrier_with_product(
            api,
            carrier_overrides={
                "legal_name": "Birch Life",
                "naic_code": "62042",
                "domicile_state": "IN",
            },
            product_overrides={"product_name": "Birch GA BOLI"},
            review_overrides={"review_year": 2026},
        )
        insured = insured_employee(api, employee_overrides=HALLORAN)

        alder_request = diligence_cleared_request(
            api,
            alder["carrier_id"],
            alder["product_type_id"],
            insured["employee_id"],
            single_premium_usd=150_000_000.00,
            face_amount_usd=450_000_000.00,
        )
        reserved = reserved_capacity_request(api, alder_request["id"], alder["carrier_id"])
        assert reserved["status"] == "CAPACITY_RESERVED"
        assert reserved["reserved_premium_usd"] == pytest.approx(150_000_000.00, abs=0.01)

        birch_request = submitted_purchase_request(
            api,
            birch["carrier_id"],
            birch["product_type_id"],
            insured["employee_id"],
            single_premium_usd=150_000_000.00,
            face_amount_usd=450_000_000.00,
        )
        birch_version = current_carrier_version(api, birch["carrier_id"])

        validate_error(
            api.reserve_purchase_request_capacity(
                birch_request["id"], {"expected_carrier_version": birch_version}, TREASURY
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        still_submitted = validate_success(
            api.get_purchase_request(birch_request["id"], TREASURY)
        )
        assert still_submitted["status"] == "SUBMITTED"
        assert still_submitted["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        birch_carrier = validate_success(api.get_carrier(birch["carrier_id"], TREASURY))
        assert birch_carrier["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01), (
            "a refused reservation claims none of the carrier's capacity"
        )

    def test_repairing_the_state_exposes_the_capital_capacity_breach(self, api):
        """Once the state is legal the fiscal-capacity gate reports the real problem.

        With 150,000,000.00 already committed, a second 150,000,000.00 premium
        drives the base ratio past the second break, so the aggregate allowance
        tightens to "twenty hundredths when `base_ratio_bps` is greater than
        8500" and "`headroom_usd` as `aggregate_limit_usd` minus
        `prospective_usd`; this value is allowed to be negative, and a negative
        result is exactly what the aggregate gate rejects, requiring
        `headroom_usd` to be zero or greater".

        Design: Difficulty/priority_pair_validation_conflict/state_transition_error_outranks_capital_capacity_breach
        """
        file_capital_position(api)
        alder = authorized_carrier_with_product(
            api,
            carrier_overrides={
                "legal_name": "Alder Life",
                "naic_code": "62041",
                "domicile_state": "OH",
            },
            product_overrides={"product_name": "Alder GA BOLI"},
        )
        birch = authorized_carrier_with_product(
            api,
            carrier_overrides={
                "legal_name": "Birch Life",
                "naic_code": "62042",
                "domicile_state": "IN",
            },
            product_overrides={"product_name": "Birch GA BOLI"},
        )
        insured = insured_employee(api, employee_overrides=HALLORAN)

        alder_request = diligence_cleared_request(
            api,
            alder["carrier_id"],
            alder["product_type_id"],
            insured["employee_id"],
            single_premium_usd=150_000_000.00,
            face_amount_usd=450_000_000.00,
        )
        reserved_capacity_request(api, alder_request["id"], alder["carrier_id"])

        birch_request = submitted_purchase_request(
            api,
            birch["carrier_id"],
            birch["product_type_id"],
            insured["employee_id"],
            single_premium_usd=150_000_000.00,
            face_amount_usd=450_000_000.00,
        )
        birch_version = current_carrier_version(api, birch["carrier_id"])

        cleared = validate_success(
            api.clear_purchase_request_diligence(birch_request["id"], RISK)
        )
        assert cleared["status"] == "DILIGENCE_CLEARED"

        validate_error(
            api.reserve_purchase_request_capacity(
                birch_request["id"], {"expected_carrier_version": birch_version}, TREASURY
            ),
            "ERR_CAPITAL_CAPACITY_EXCEEDED",
            422,
        )

        after = validate_success(api.get_purchase_request(birch_request["id"], TREASURY))
        assert after["status"] == "DILIGENCE_CLEARED", (
            "the capital refusal leaves the repaired state in place"
        )
        assert after["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        alder_after = validate_success(api.get_purchase_request(alder_request["id"], TREASURY))
        assert alder_after["reserved_premium_usd"] == pytest.approx(150_000_000.00, abs=0.01)
        assert alder_after["base_ratio_bps"] == 6000
        assert alder_after["headroom_usd"] == pytest.approx(100_000_000.00, abs=0.01), (
            "the sibling reservation keeps its own capacity figures frozen onto it"
        )

    def test_carrier_concentration_breach_outranks_the_capital_breach(self, api):
        """When both exposure gates would bite, concentration reports first.

        "Then the single-carrier concentration test is applied, reported as
        `ERR_CARRIER_CONCENTRATION_EXCEEDED` (HTTP 422), and only after it
        passes is the aggregate capital headroom test applied, reported as
        `ERR_CAPITAL_CAPACITY_EXCEEDED` (HTTP 422). The concentration test
        therefore always wins over the headroom test when a request would
        breach both."

        Design: Difficulty/priority_pair_validation_conflict/carrier_concentration_error_outranks_capital_capacity_breach
        """
        file_capital_position(api)
        cedar = authorized_carrier_with_product(
            api,
            carrier_overrides={
                "legal_name": "Cedar Life",
                "naic_code": "62051",
                "domicile_state": "MI",
            },
            product_overrides={"product_name": "Cedar GA BOLI"},
        )
        insured = insured_employee(api, employee_overrides=HALLORAN)

        first = diligence_cleared_request(
            api,
            cedar["carrier_id"],
            cedar["product_type_id"],
            insured["employee_id"],
            single_premium_usd=150_000_000.00,
            face_amount_usd=450_000_000.00,
        )
        reserved_capacity_request(api, first["id"], cedar["carrier_id"])

        second = diligence_cleared_request(
            api,
            cedar["carrier_id"],
            cedar["product_type_id"],
            insured["employee_id"],
            single_premium_usd=80_000_000.00,
            face_amount_usd=240_000_000.00,
        )

        response = reserve_capacity(api, second["id"], cedar["carrier_id"])
        validate_error(response, "ERR_CARRIER_CONCENTRATION_EXCEEDED", 422)

        after = validate_success(api.get_purchase_request(second["id"], TREASURY))
        assert after["status"] == "DILIGENCE_CLEARED"
        assert after["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        carrier_after = validate_success(api.get_carrier(cedar["carrier_id"], TREASURY))
        assert carrier_after["reserved_premium_usd"] == pytest.approx(150_000_000.00, abs=0.01), (
            "only the first reservation holds any of the carrier's capacity"
        )

    def test_projection_shows_both_gates_failing_on_the_refused_request(self, api):
        """The what-if read proves the aggregate gate would also have failed.

        Single-carrier concentration adds "the carrier's current
        `reserved_premium_usd`, the carrier's current `in_force_premium_usd`,
        and this request's `single_premium_usd`", so 150,000,000.00 already
        reserved plus 80,000,000.00 proposed reads 2300 basis points against a
        1500 ceiling — while the same figures drive the base ratio to 9200 and
        the headroom negative.

        Design: Difficulty/priority_pair_validation_conflict/carrier_concentration_error_outranks_capital_capacity_breach
        """
        file_capital_position(api)
        cedar = authorized_carrier_with_product(
            api,
            carrier_overrides={
                "legal_name": "Cedar Life",
                "naic_code": "62051",
                "domicile_state": "MI",
            },
            product_overrides={"product_name": "Cedar GA BOLI"},
        )
        insured = insured_employee(api, employee_overrides=HALLORAN)

        first = diligence_cleared_request(
            api,
            cedar["carrier_id"],
            cedar["product_type_id"],
            insured["employee_id"],
            single_premium_usd=150_000_000.00,
            face_amount_usd=450_000_000.00,
        )
        reserved_capacity_request(api, first["id"], cedar["carrier_id"])

        second = diligence_cleared_request(
            api,
            cedar["carrier_id"],
            cedar["product_type_id"],
            insured["employee_id"],
            single_premium_usd=80_000_000.00,
            face_amount_usd=240_000_000.00,
        )

        projection = validate_success(api.get_capacity_projection(second["id"], RISK))
        assert projection["carrier_concentration_bps"] == 2300
        assert projection["single_carrier_limit_bps"] == 1500
        assert projection["base_ratio_bps"] == 9200
        assert projection["effective_limit_pct"] == pytest.approx(0.20, abs=0.0001)
        assert projection["aggregate_limit_usd"] == pytest.approx(200_000_000.00, abs=0.01)
        assert projection["headroom_usd"] == pytest.approx(-30_000_000.00, abs=0.01), (
            "the headroom is allowed to be negative and here it is"
        )
