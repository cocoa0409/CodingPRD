"""CRUD and basic validation for setup entities — institutions, regions,
persons, facilities. PRD §3.1 covers these resources.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_facility,
    assert_institution,
    assert_person,
    assert_region,
    create_facility_payload,
    create_institution_payload,
    create_person_payload,
    create_region_payload,
    random_person_hash,
    random_suffix,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Institution CRUD — PRD §3.1
# ===========================================================================
class TestInstitutionCRUD:

    def test_create_and_retrieve_institution(self, api, supervisor_headers):
        """PRD §3.1: "Each carries an institution_code (a unique
        alphanumeric short code, between 4 and 12 characters long), an
        institution_type drawn from HOSPITAL, LAB, CDC, VENUE, and
        TRANSIT, and a district_code identifying the sub-district where
        the institution sits."

        Claim: POST /epi/institutions persists the documented fields and
        defaults status to ACTIVE.
        """
        payload = create_institution_payload(
            institution_code=f"H{random_suffix(5).upper()}",
            institution_type="HOSPITAL",
            district_code="D-CRUD-1",
        )
        resp = api.create_institution(payload, supervisor_headers)
        institution = validate_success(resp, 201)
        assert_institution(institution)
        assert institution["institution_code"] == payload["institution_code"]
        assert institution["institution_type"] == "HOSPITAL"
        assert institution["district_code"] == "D-CRUD-1"
        assert institution["status"] == "ACTIVE", (
            "PRD §3.1: 'New institutions default to operational status ACTIVE.'"
        )

        # Read back via GET.
        get_resp = api.get_institution(institution["id"], supervisor_headers)
        fetched = validate_success(get_resp, 200)
        assert fetched["id"] == institution["id"]
        assert fetched["institution_code"] == institution["institution_code"]


# ===========================================================================
# Region CRUD — PRD §3.1
# ===========================================================================
class TestRegionCRUD:

    def test_create_and_retrieve_region(self, api, supervisor_headers):
        """PRD §3.1: "Sub-districts themselves are modelled as Region
        rows, each keyed by a unique district_code. Each region records
        its resident population (which must be strictly greater than
        zero, since population is the denominator of the density score),
        a current_risk_tier and a provisional_risk_tier (both drawn
        from LOW, MEDIUM, HIGH and defaulting to LOW)."

        Claim: POST /epi/regions defaults both risk tiers to LOW.
        """
        payload = create_region_payload(
            district_code=f"D-{random_suffix(5)}", population=50000,
        )
        resp = api.create_region(payload, supervisor_headers)
        region = validate_success(resp, 201)
        assert_region(region)
        assert region["district_code"] == payload["district_code"]
        assert region["population"] == 50000
        assert region["current_risk_tier"] == "LOW", (
            "PRD §3.1: current_risk_tier defaults to LOW"
        )
        assert region["provisional_risk_tier"] == "LOW", (
            "PRD §3.1: provisional_risk_tier defaults to LOW"
        )


# ===========================================================================
# Person CRUD — PRD §3.1
# ===========================================================================
class TestPersonCRUD:

    def test_create_and_retrieve_person(self, api, supervisor_headers):
        """PRD §3.1: "Individuals being tracked are stored as Person
        rows. Each carries a person_hash — a unique 16-character
        lowercase hex deduplication hash derived from the person's
        national-id last four digits, date of birth, and name initials
        — a structured demographics object containing age band, gender,
        and occupation category, the district_code of residence, an
        isolation_status (one of NONE, ACTIVE, RELEASED,
        VIOLATED_TERMINATED, defaulting to NONE)."

        Claim: POST /epi/persons defaults isolation_status to NONE.
        """
        payload = create_person_payload(
            person_hash=random_person_hash(),
            district_code="D-PERSON-1",
        )
        resp = api.create_person(payload, supervisor_headers)
        person = validate_success(resp, 201)
        assert_person(person)
        assert person["person_hash"] == payload["person_hash"]
        assert person["district_code"] == "D-PERSON-1"
        assert person["isolation_status"] == "NONE", (
            "PRD §3.1: isolation_status defaults to NONE"
        )


# ===========================================================================
# Facility CRUD + facility-occupancy invariant — PRD §3.1
# ===========================================================================
class TestFacilityCRUD:

    def test_create_facility_defaults_occupied_zero_and_open(self, api,
                                                              supervisor_headers):
        """PRD §3.1: "a computed occupied count starting at zero, and
        an operational status of OPEN, FULL, or CLOSED, defaulting to
        OPEN."

        Claim: a newly created IsolationFacility has occupied == 0 and
        status == OPEN.
        """
        payload = create_facility_payload(
            facility_code=f"F{random_suffix(5).upper()}",
            district_code="D-FAC-1",
            capacity=3,
        )
        resp = api.create_facility(payload, supervisor_headers)
        facility = validate_success(resp, 201)
        assert_facility(facility)
        assert facility["capacity"] == 3
        assert facility["occupied"] == 0, (
            "PRD §3.1: 'a computed occupied count starting at zero'"
        )
        assert facility["status"] == "OPEN", (
            "PRD §3.1: facility status defaults to OPEN"
        )
