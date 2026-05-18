"""Damages: singleton, MULTIPLIER vs PER_DIEM, recompute, validations.

PRD §3.4.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_damages,
    create_damages_multiplier,
    create_damages_multiplier_payload,
    create_damages_per_diem,
    create_damages_per_diem_payload,
    get_damages,
    patch_damages_to_per_diem,
    receive_med_request,
    send_med_request,
    setup_case_with_fee,
    setup_records_pending,
    setup_ready_for_demand,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestDamagesSingleton:

    def test_create_first_damages_returns_201(self, api):
        """PRD §3.4: "Each case has exactly one Damages row".

        Claim: First POST /damages returns 201 with assert_damages-
        compliant body.
        """
        _, case, _ = setup_case_with_fee()
        damages = create_damages_multiplier(case["id"])
        assert_damages(damages)

    def test_second_damages_returns_already_exists(
        self, api, paralegal_headers,
    ):
        """PRD §3.4: "The row is created at any point after a case
        opens (typically once records start arriving) and is rejected
        with ERR_DAMAGES_ALREADY_EXISTS if a row already exists."

        Claim: Second POST /damages → 409 ERR_DAMAGES_ALREADY_EXISTS.
        """
        _, case, _ = setup_case_with_fee()
        create_damages_multiplier(case["id"])
        resp = api.create_damages(
            case["id"], create_damages_multiplier_payload(),
            paralegal_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DAMAGES_ALREADY_EXISTS.value,
        )


class TestMultiplierCalculation:

    def test_multiplier_2x_on_economic_components(self, api):
        """PRD §3.4: "under the MULTIPLIER method it is the economic
        component multiplied by multiplier_value, with the product
        rounded half-up to a whole number of cents".

        Claim: economic=1_500_000, multiplier=2.0 →
        pain_suffering_cents=3_000_000, total=4_500_000.
        """
        _, case, _ = setup_case_with_fee()
        damages = create_damages_multiplier(
            case["id"],
            lost_wages_cents=1_500_000,
            multiplier_value=2.0,
        )
        # No RECEIVED records, so medical_bills_cents=0.
        assert damages["medical_bills_cents"] == 0
        assert damages["pain_suffering_cents"] == 3_000_000, (
            "PRD §3.4: pain = economic * multiplier = 1,500,000 * 2.0"
        )
        assert damages["total_damages_cents"] == 4_500_000

    def test_multiplier_below_one_rejected(self, api, paralegal_headers):
        """PRD §3.4: "the payload must supply multiplier_value (a
        decimal in the closed range 1.0 to 5.0 ...)... A payload that
        omits the required inputs for its declared method, or supplies
        them out of range, is rejected with
        ERR_DAMAGES_METHOD_INPUTS_INVALID."

        Claim: multiplier_value=0.5 → ERR_DAMAGES_METHOD_INPUTS_INVALID.
        """
        _, case, _ = setup_case_with_fee()
        resp = api.create_damages(
            case["id"],
            create_damages_multiplier_payload(multiplier_value=0.5),
            paralegal_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DAMAGES_METHOD_INPUTS_INVALID.value,
        )

    def test_multiplier_above_five_rejected(self, api, paralegal_headers):
        """PRD §3.4: "a decimal in the closed range 1.0 to 5.0".

        Claim: multiplier_value=5.1 → ERR_DAMAGES_METHOD_INPUTS_INVALID.
        """
        _, case, _ = setup_case_with_fee()
        resp = api.create_damages(
            case["id"],
            create_damages_multiplier_payload(multiplier_value=5.1),
            paralegal_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DAMAGES_METHOD_INPUTS_INVALID.value,
        )


class TestPerDiemCalculation:

    def test_per_diem_no_rounding_integer_multiplication(self, api):
        """PRD §3.4: "under the PER_DIEM method it is per_diem_rate_cents
        multiplied by per_diem_days, with no rounding because both
        operands are already integer values."

        Claim: 15000 * 365 = 5_475_000, exact.
        """
        _, case, _ = setup_case_with_fee()
        damages = create_damages_per_diem(
            case["id"],
            per_diem_rate_cents=15_000,
            per_diem_days=365,
        )
        assert damages["pain_suffering_cents"] == 5_475_000

    def test_per_diem_zero_rate_rejected(
        self, api, paralegal_headers,
    ):
        """PRD §3.4: "when the method is PER_DIEM, the payload must
        supply per_diem_rate_cents strictly greater than zero".

        Claim: per_diem_rate_cents=0 → ERR_DAMAGES_METHOD_INPUTS_INVALID.
        """
        _, case, _ = setup_case_with_fee()
        resp = api.create_damages(
            case["id"],
            create_damages_per_diem_payload(
                per_diem_rate_cents=0, per_diem_days=10,
            ),
            paralegal_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DAMAGES_METHOD_INPUTS_INVALID.value,
        )

    def test_per_diem_zero_days_rejected(
        self, api, paralegal_headers,
    ):
        """PRD §3.4: "and per_diem_days strictly greater than zero."

        Claim: per_diem_days=0 → ERR_DAMAGES_METHOD_INPUTS_INVALID.
        """
        _, case, _ = setup_case_with_fee()
        resp = api.create_damages(
            case["id"],
            create_damages_per_diem_payload(
                per_diem_rate_cents=100, per_diem_days=0,
            ),
            paralegal_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DAMAGES_METHOD_INPUTS_INVALID.value,
        )


class TestDamagesRecompute:

    def test_recompute_sums_received_billed_amounts(self, api):
        """PRD §3.4: "First, medical_bills_cents is set to the sum of
        billed_amount_cents over every MedicalRecordRequest row on the
        case whose status is RECEIVED".

        Claim: After receiving a record at 500_000, recompute reflects
        that.
        """
        _, case, _, request, damages = setup_ready_for_demand(
            billed_amount_cents=500_000, multiplier_value=2.0,
        )
        # Damages already exists from setup; recompute is idempotent.
        from test_helpers import TEST_USERS
        resp = api.recompute_damages(case["id"], TEST_USERS["paralegal_headers"])
        recomputed = validate_success(resp)
        assert recomputed["medical_bills_cents"] == 500_000


class TestDamagesPatch:

    def test_patch_method_to_per_diem_recomputes(self, api):
        """PRD §3.4: "The damages total is recomputed every time the
        row is created or patched".

        Claim: PATCH from MULTIPLIER to PER_DIEM with new inputs flips
        pain_suffering_cents accordingly.
        """
        _, case, _ = setup_case_with_fee()
        damages = create_damages_multiplier(
            case["id"], lost_wages_cents=500_000, multiplier_value=3.0,
        )
        # economic=500_000, pain=1_500_000, total=2_000_000.
        assert damages["pain_suffering_cents"] == 1_500_000

        updated = patch_damages_to_per_diem(
            case["id"],
            per_diem_rate_cents=2000, per_diem_days=100,
            version=damages["version"],
        )
        # economic component still 500_000 (lost wages unchanged);
        # per-diem pain = 2000 * 100 = 200_000; total = 700_000.
        assert updated["pain_suffering_method"] == "PER_DIEM"
        assert updated["pain_suffering_cents"] == 200_000
        assert updated["total_damages_cents"] == 700_000
