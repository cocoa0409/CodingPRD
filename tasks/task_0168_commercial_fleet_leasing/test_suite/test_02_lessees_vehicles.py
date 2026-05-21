"""Lessee + Vehicle onboarding — PRD §3.1.

Covers creation, field validation, default values, and the initial
state of fresh entities.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_lessee,
    assert_vehicle,
    create_lessee_payload,
    create_vehicle_payload,
    unique_dot_number,
    validate_error,
    validate_success,
)


# ===========================================================================
# Lessee — PRD §3.1
# ===========================================================================
class TestLesseeCreate:

    def test_create_lessee_succeeds_with_valid_inputs(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.1: "A fresh lessee is born in the `ACTIVE` account
        state with `outstanding_balance_cents` equal to zero."

        Claim: a valid POST /lessees yields a new Lessee with
        account_status=ACTIVE and outstanding_balance_cents=0.
        """
        payload = create_lessee_payload(base_jurisdiction="CA")
        resp = api.create_lessee(payload, fleet_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_lessee(data)
        assert data["account_status"] == "ACTIVE", (
            f"new Lessee account_status must be ACTIVE, "
            f"got {data['account_status']!r}"
        )
        assert data["outstanding_balance_cents"] == 0, (
            f"new Lessee outstanding_balance_cents must be 0, "
            f"got {data['outstanding_balance_cents']!r}"
        )

    def test_create_lessee_with_each_supported_jurisdiction(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.1: "The base jurisdiction must come from the
        supported set of ten US states: `CA`, `TX`, `NY`, `IL`, `FL`,
        `OH`, `PA`, `GA`, `WA`, or `AZ`."

        Claim: each of the ten declared jurisdictions is accepted.
        """
        for j in ("CA", "TX", "NY", "IL", "FL", "OH", "PA", "GA",
                  "WA", "AZ"):
            resp = api.create_lessee(
                create_lessee_payload(base_jurisdiction=j),
                fleet_manager_headers,
            )
            data = validate_success(resp, expected_status=201)
            assert data["base_jurisdiction"] == j, (
                f"base_jurisdiction roundtrip failed for {j}: "
                f"got {data.get('base_jurisdiction')!r}"
            )

    def test_create_lessee_with_unsupported_jurisdiction_rejected(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.1: "The base jurisdiction must come from the
        supported set of ten US states: `CA`, `TX`, `NY`, `IL`, `FL`,
        `OH`, `PA`, `GA`, `WA`, or `AZ`."

        Claim: a jurisdiction outside the supported ten is rejected
        as ERR_VALIDATION (input-shape failure).
        """
        resp = api.create_lessee(
            create_lessee_payload(base_jurisdiction="WY"),
            fleet_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_create_lessee_duplicate_dot_number_rejected(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.1: "The DOT number must be a digits-only string
        between six and eight digits long and must not collide with
        any other lessee's number — the field is unique across the
        entire `Lessee` table."

        Claim: creating two lessees with the same dot_number yields a
        validation/conflict error on the second.
        """
        dot = unique_dot_number()
        ok = api.create_lessee(
            create_lessee_payload(dot_number=dot),
            fleet_manager_headers,
        )
        validate_success(ok, expected_status=201)
        dup = api.create_lessee(
            create_lessee_payload(dot_number=dot),
            fleet_manager_headers,
        )
        # PRD §3.1 does not pin a specific error_id for the uniqueness
        # collision (only that the field is unique). A faithful
        # implementer could classify this as ERR_VALIDATION.
        from prd_bench_local_runner.testing import (
            validate_error_is_one_of,
        )
        validate_error_is_one_of(
            dup,
            [ApiErrorId.ERR_VALIDATION.value],
        )

    @pytest.mark.parametrize("bad", ["12345", "123456789", "abcd123"])
    def test_create_lessee_bad_dot_number_rejected(
        self, api, fleet_manager_headers, bad,
    ):
        """PRD §3.1: "The DOT number must be a digits-only string
        between six and eight digits long."

        Claim: a dot_number outside the 6..8-digit form is rejected
        as ERR_VALIDATION.
        """
        resp = api.create_lessee(
            create_lessee_payload(dot_number=bad),
            fleet_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_create_lessee_legal_name_empty_after_trim_rejected(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.1: "The legal name is a free-form string of one to
        one-hundred-and-twenty characters that must be non-empty
        after trimming whitespace."

        Claim: a legal_name of whitespace-only is rejected.
        """
        resp = api.create_lessee(
            create_lessee_payload(legal_name="   "),
            fleet_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Vehicle — PRD §3.1
# ===========================================================================
class TestVehicleCreate:

    def test_create_vehicle_initial_state(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.1: "A newly added vehicle's `vehicle_status` is
        `AVAILABLE`, its `current_lease_id` is null, and its
        `odometer_current_miles` is initialised to the supplied
        baseline."

        Claim: a fresh vehicle has AVAILABLE, null current_lease_id,
        and odometer_current_miles == odometer_baseline_miles.
        """
        payload = create_vehicle_payload(
            vehicle_class="CLASS_5", odometer_baseline_miles=12_345,
        )
        resp = api.create_vehicle(payload, fleet_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_vehicle(data)
        assert data["vehicle_status"] == "AVAILABLE", (
            f"new Vehicle vehicle_status must be AVAILABLE, "
            f"got {data['vehicle_status']!r}"
        )
        assert data.get("current_lease_id") is None, (
            f"new Vehicle current_lease_id must be null, "
            f"got {data.get('current_lease_id')!r}"
        )
        assert data["odometer_current_miles"] == 12_345, (
            f"new Vehicle odometer_current_miles must equal baseline "
            f"12345, got {data['odometer_current_miles']!r}"
        )

    @pytest.mark.parametrize("klass", ["CLASS_3", "CLASS_5",
                                         "CLASS_7", "CLASS_8"])
    def test_each_vehicle_class_accepted(
        self, api, fleet_manager_headers, klass,
    ):
        """PRD §3.1: "the tractor's `vehicle_class` chosen from
        `CLASS_3`, `CLASS_5`, `CLASS_7`, or `CLASS_8`."

        Claim: each of the four declared vehicle_class values is
        accepted.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(vehicle_class=klass),
            fleet_manager_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["vehicle_class"] == klass

    def test_unknown_vehicle_class_rejected(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.1: "the tractor's `vehicle_class` chosen from
        `CLASS_3`, `CLASS_5`, `CLASS_7`, or `CLASS_8`."

        Claim: a vehicle_class outside the declared four is rejected.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(vehicle_class="CLASS_99"),
            fleet_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("yr", [1999, 2031])
    def test_model_year_out_of_range_rejected(
        self, api, fleet_manager_headers, yr,
    ):
        """PRD §3.1: "the `model_year` (an integer between 2000 and
        2030 inclusive)."

        Claim: model_year outside [2000, 2030] is rejected.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(model_year=yr),
            fleet_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_odometer_baseline_default_zero_when_omitted(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.1: "the recorded `odometer_baseline_miles` at fleet
        entry (a non-negative integer that defaults to zero when
        omitted)."

        Claim: omitting odometer_baseline_miles defaults to 0.
        """
        payload = create_vehicle_payload()
        # Strip baseline so the server applies the default.
        payload.pop("odometer_baseline_miles", None)
        resp = api.create_vehicle(payload, fleet_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["odometer_baseline_miles"] == 0, (
            f"omitted baseline must default to 0, "
            f"got {data['odometer_baseline_miles']!r}"
        )
