"""Vehicle registration, plate normalization, kind exemption (PRD §3.2, §2.10)."""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_vehicle,
    create_vehicle,
    create_vehicle_payload,
    unique_plate,
    validate_error,
    validate_success,
)


class TestVehicleRegistration:
    def test_create_vehicle_defaults_to_regular(self, api, operator_headers):
        """PRD §3.2: 'A vehicle is registered when a GateSystem or Operator
        posts a plate along with an optional kind defaulting to REGULAR.'"""
        res = api.create_vehicle(
            create_vehicle_payload(plate="ABC123"), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert_vehicle(data)
        assert data["kind"] == "REGULAR"

    def test_new_vehicle_has_binding_eligible_true(self, api, operator_headers):
        """PRD §3.2: 'New vehicles start with binding_eligible set to true
        and open_violation_count set to zero.'"""
        res = api.create_vehicle(
            create_vehicle_payload(plate=unique_plate("BLD")),
            operator_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["binding_eligible"] is True
        assert data["open_violation_count"] == 0


class TestPlateNormalization:
    def test_lowercase_plate_normalized_to_uppercase(self, api, operator_headers):
        """PRD §3.2: 'The system normalizes the supplied plate to uppercase
        with all whitespace stripped.'"""
        plate_lc = unique_plate("low").lower()
        res = api.create_vehicle(
            create_vehicle_payload(plate=plate_lc), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert data["plate"] == plate_lc.upper()

    def test_plate_with_whitespace_normalized(self, api, operator_headers):
        """PRD §3.2: 'The system normalizes the supplied plate to uppercase
        with all whitespace stripped.'"""
        res = api.create_vehicle(
            create_vehicle_payload(plate="ab 12-34"), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert data["plate"] == "AB12-34"


class TestPlateValidation:
    @pytest.mark.parametrize(
        "bad_plate",
        ["ABC*123", "TOO_LONG_PLATE_VAL", "x@x", ""],
    )
    def test_invalid_plate_rejected(self, api, operator_headers, bad_plate):
        """PRD §3.2: 'A plate that fails the regex is rejected with
        ERR_BAD_REQUEST.'"""
        res = api.create_vehicle(
            create_vehicle_payload(plate=bad_plate), operator_headers
        )
        validate_error(res, "ERR_BAD_REQUEST")

    def test_duplicate_plate_rejected(self, api, operator_headers):
        """PRD §3.2: 'a normalized plate already present on another Vehicle
        is also rejected with ERR_BAD_REQUEST.'"""
        plate = unique_plate("DUP")
        first = api.create_vehicle(
            create_vehicle_payload(plate=plate), operator_headers
        )
        validate_success(first, expected_status=201)
        # Resubmit identical plate (after normalization).
        res = api.create_vehicle(
            create_vehicle_payload(plate=plate), operator_headers
        )
        validate_error(res, "ERR_BAD_REQUEST")

    def test_duplicate_plate_via_normalization_rejected(
        self, api, operator_headers
    ):
        """PRD §3.2: 'a normalized plate already present on another Vehicle
        is also rejected with ERR_BAD_REQUEST.' Uppercased and lowercased
        forms collide after normalization."""
        # First with mixed case
        first = api.create_vehicle(
            create_vehicle_payload(plate="MIX-CAS-99"), operator_headers
        )
        validate_success(first, expected_status=201)
        # Second submits lowercase that normalizes to the same value.
        res = api.create_vehicle(
            create_vehicle_payload(plate="mix-cas-99"), operator_headers
        )
        validate_error(res, "ERR_BAD_REQUEST")


class TestVehicleKindEnumeration:
    @pytest.mark.parametrize("kind", ["REGULAR", "EMERGENCY", "DISABLED"])
    def test_kind_enum_values_accepted(self, api, operator_headers, kind):
        """PRD §3.2: 'The kind is one of REGULAR, EMERGENCY, or DISABLED.'"""
        res = api.create_vehicle(
            create_vehicle_payload(plate=unique_plate(kind[:3]), kind=kind),
            operator_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["kind"] == kind
