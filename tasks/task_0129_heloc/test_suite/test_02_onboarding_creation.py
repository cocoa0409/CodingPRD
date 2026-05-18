"""Borrower, Property, and SeniorLien CRUD and defaults.

Covers PRD §3.1 (onboarding flow): Borrower full_name/email shape,
Property occupancy default, computed insurance_status default, and
SeniorLien initial CURRENT status.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_borrower,
    assert_property,
    assert_senior_lien,
    create_borrower,
    create_borrower_payload,
    create_property,
    create_property_payload,
    create_senior_lien_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 Borrower
# ===========================================================================
class TestBorrowerCreation:

    def test_create_borrower_returns_201_and_initial_flags(
        self, api, originator_headers,
    ):
        """PRD §3.1: "Two system-managed flags travel with the borrower:
        a bankruptcy_flag that begins as false and a bankruptcy_filed_at
        timestamp that begins as null."
        """
        payload = create_borrower_payload(
            full_name="Alice Borrower",
            email="alice@example.com",
        )
        b = validate_success(
            api.create_borrower(payload, originator_headers), 201,
        )
        assert_borrower(b)
        assert b["full_name"] == "Alice Borrower"
        assert b["email"] == "alice@example.com"
        assert b["bankruptcy_flag"] is False
        assert b["bankruptcy_filed_at"] is None

    def test_duplicate_email_rejected(self, api, originator_headers):
        """PRD §3.1: "an email shaped as an RFC-5322 address that is
        unique across all borrowers."
        """
        payload = create_borrower_payload(email="dup@example.com")
        first = api.create_borrower(payload, originator_headers)
        assert first.status_code == 201
        # Same email again, different name to disambiguate.
        payload2 = create_borrower_payload(
            full_name="Other", email="dup@example.com",
        )
        resp = api.create_borrower(payload2, originator_headers)
        # PRD §3.1 says uniqueness is required; PRD does not name the
        # specific error_id here. PRD §2.12 covers field-shape failure
        # → ERR_VALIDATION_FAILED. Either the field-shape catalog
        # error or a 4xx HTTP status is acceptable for collisions.
        assert resp.status_code >= 400, (
            f"duplicate email must be rejected, got {resp.status_code}"
        )


# ===========================================================================
# §3.1 Property — occupancy default, insurance default
# ===========================================================================
class TestPropertyCreation:

    def test_property_defaults_occupancy_to_primary(
        self, api, originator_headers,
    ):
        """PRD §3.1: "an optional occupancy of PRIMARY, SECONDARY, or
        INVESTMENT (defaulting to PRIMARY when omitted)."
        """
        borrower = create_borrower()
        # Factory omits occupancy when None.
        payload = create_property_payload(
            borrower_id=borrower["id"], occupancy=None,
        )
        assert "occupancy" not in payload
        prop = validate_success(
            api.create_property(payload, originator_headers), 201,
        )
        assert_property(prop)
        assert prop["occupancy"] == "PRIMARY"

    def test_property_initial_insurance_status_active_and_lapsed_at_null(
        self, api, originator_headers,
    ):
        """PRD §3.1: "Two computed fields, insurance_status and
        insurance_lapsed_at, are initialized at creation to ACTIVE and
        null respectively".
        """
        borrower = create_borrower()
        prop = create_property(borrower_id=borrower["id"])
        assert prop["insurance_status"] == "ACTIVE"
        assert prop["insurance_lapsed_at"] is None

    @pytest.mark.parametrize(
        "occupancy", ["PRIMARY", "SECONDARY", "INVESTMENT"],
    )
    def test_property_accepts_declared_occupancy_values(
        self, api, originator_headers, occupancy,
    ):
        """PRD §3.1: "an optional occupancy of PRIMARY, SECONDARY, or
        INVESTMENT".
        """
        borrower = create_borrower()
        payload = create_property_payload(
            borrower_id=borrower["id"], occupancy=occupancy,
        )
        prop = validate_success(
            api.create_property(payload, originator_headers), 201,
        )
        assert prop["occupancy"] == occupancy


# ===========================================================================
# §3.1 SeniorLien — initial CURRENT status
# ===========================================================================
class TestSeniorLienCreation:

    def test_senior_lien_initial_status_current(
        self, api, originator_headers,
    ):
        """PRD §3.1: "The senior lien begins with status set to CURRENT
        and defaulted_at of null."
        """
        borrower = create_borrower()
        prop = create_property(borrower_id=borrower["id"])
        payload = create_senior_lien_payload(property_id=prop["id"])
        sl = validate_success(
            api.create_senior_lien(payload, originator_headers), 201,
        )
        assert_senior_lien(sl)
        assert sl["status"] == "CURRENT"
        assert sl["defaulted_at"] is None


# ===========================================================================
# §2.12 Field-shape validation
# ===========================================================================
class TestFieldShapeValidation:

    def test_missing_required_borrower_full_name_rejected(
        self, api, originator_headers,
    ):
        """PRD §2.12: "Generic body-shape validation — a required field
        is missing ... is rejected with ERR_VALIDATION_FAILED and an
        HTTP 400 status."
        """
        payload = create_borrower_payload()
        del payload["full_name"]
        resp = api.create_borrower(payload, originator_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_negative_appraised_value_rejected(
        self, api, originator_headers,
    ):
        """PRD §2.12: "a cents-valued amount is supplied as a negative
        number ... is rejected with ERR_VALIDATION_FAILED and an HTTP
        400 status."
        """
        borrower = create_borrower()
        payload = create_property_payload(borrower_id=borrower["id"])
        payload["appraised_value_cents"] = -1
        resp = api.create_property(payload, originator_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_unknown_property_occupancy_rejected(
        self, api, originator_headers,
    ):
        """PRD §2.12: "an enum-typed field is supplied with a value
        outside its declared set ... is rejected with
        ERR_VALIDATION_FAILED".
        """
        borrower = create_borrower()
        payload = create_property_payload(
            borrower_id=borrower["id"], occupancy="MARS_RESIDENCE",
        )
        resp = api.create_property(payload, originator_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)
