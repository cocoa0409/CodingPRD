"""Buildings, units, and unit creation rules.

PRD §3.1.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_building,
    assert_unit,
    create_building,
    create_building_payload,
    create_unit,
    create_unit_payload,
    setup_building_with_unit,
    unique_unit_code,
    validate_error,
    validate_success,
    PM,
)


# ===========================================================================
# Building creation
# ===========================================================================
class TestBuildingCreation:
    """PRD §3.1: 'Creating a Building requires a human-readable name, a
    postal address, and a floors_count integer that records the
    building's total number of floors and must be at least 1. New
    buildings are persisted with status of ACTIVE.'
    """

    def test_create_building_returns_active_with_required_fields(self, api):
        """PRD §3.1: 'New buildings are persisted with status of
        ACTIVE.'"""
        res = api.create_building(create_building_payload(), PM)
        data = validate_success(res, expected_status=201)
        assert_building(data)
        assert data["status"] == "ACTIVE"
        assert data["floors_count"] >= 1
        assert data["version"] == 1

    def test_get_building_round_trips_fields(self, api):
        """PRD §2.4: read-after-write returns the same row."""
        b = create_building(name="Tower 7",
                            address="7 Avenue", floors_count=20)
        res = api.get_building(b["id"], PM)
        data = validate_success(res)
        assert data["id"] == b["id"]
        assert data["name"] == "Tower 7"
        assert data["address"] == "7 Avenue"
        assert data["floors_count"] == 20


# ===========================================================================
# Unit creation
# ===========================================================================
class TestUnitCreation:
    """PRD §3.1: 'Inside a building, a PropertyManager creates Unit
    rows ... a floor (an integer between 1 and the owning building's
    floors_count inclusive), a unique-per-building code string ... an
    area_sqm number ... which must be strictly greater than zero, an
    orientation drawn from the enumeration N, S, E, W, NE, NW, SE, SW,
    a usage_type drawn from OFFICE, RETAIL, WAREHOUSE, or FB, and a
    rent_reference_per_sqm ... strictly greater than zero.'
    """

    def test_create_unit_returns_vacant_with_required_fields(self, api):
        """PRD §3.1: 'The created unit begins with derived status
        VACANT.'"""
        b = create_building(floors_count=10)
        res = api.create_unit(
            b["id"],
            create_unit_payload(
                floor=3, area_sqm=120.50,
                orientation="SE", usage_type="OFFICE",
                rent_reference_per_sqm=150.00,
            ),
            PM,
        )
        data = validate_success(res, expected_status=201)
        assert_unit(data)
        assert data["status"] == "VACANT"
        assert data["building_id"] == b["id"]
        assert data["floor"] == 3
        assert data["orientation"] == "SE"
        assert data["usage_type"] == "OFFICE"

    def test_unit_code_must_be_unique_per_building(self, api):
        """PRD §3.1: 'a unique-per-building code string'."""
        b = create_building()
        code = unique_unit_code()
        create_unit(b["id"], code=code)
        # Duplicate within same building
        res = api.create_unit(
            b["id"], create_unit_payload(code=code), PM,
        )
        validate_error(res, ApiErrorId.ERR_UNIT_CODE_CONFLICT.value)

    def test_unit_floor_outside_floors_count_rejected(self, api):
        """PRD §3.1: 'floor (an integer between 1 and the owning
        building's floors_count inclusive)'."""
        b = create_building(floors_count=3)
        res = api.create_unit(
            b["id"], create_unit_payload(floor=4), PM,
        )
        # PRD §2.10 priority 16 tail: 'Request body field types and
        # required-field validation (ERR_VALIDATION ...) runs at the
        # tail.' floor-out-of-range is a body-type/range violation.
        body = res.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_VALIDATION.value


# ===========================================================================
# Unit GET — derived status
# ===========================================================================
class TestUnitDerivedStatus:
    """PRD §3.1: 'A unit's status is not stored independently of these
    inputs — it is a derived field whose value is recomputed any time a
    lease state on the unit, the unit's renovation interval, or a
    split-or-merge event changes.'
    """

    def test_new_unit_is_vacant(self, api):
        """PRD §3.1: 'otherwise the status is VACANT.'"""
        building, unit = setup_building_with_unit()
        data = validate_success(api.get_unit(
            building["id"], unit["id"], PM,
        ))
        assert data["status"] == "VACANT"
