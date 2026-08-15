"""Onboarding and creation defaults: donors, drivers, coolers, offers (PRD §3.1-§3.2)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, validate_success,
    assert_donor_site, assert_volunteer_driver, assert_cooler,
    assert_donation_offer, ApiErrorId,
    create_donor, make_donor_coordinator_headers,
)
from test_helpers.factories import (
    create_donor_site_payload, create_volunteer_driver_payload,
    create_cooler_payload, create_donation_offer_payload,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCreationDefaults:
    def test_donor_creation_materializes_defaults(self, api):
        """PRD §3.1: "A new donor enters `PENDING_REVIEW` with `strike_count` and
        all weight and tax aggregates at zero."
        PRD §3.1: "The optional `enhanced_deduction_eligible` flag defaults to
        false and, when set, switches the donor's receipts to the
        enhanced-deduction valuation variant of §3.8."

        Design: Corner/entities/donor_creation_defaults
        """
        resp = api.create_donor_site(
            create_donor_site_payload(
                legal_name="Default Bistro", ein="100000001",
                contact_email="d@bistro.example"),
            ADMIN)
        data = validate_success(resp, 201)
        assert_donor_site(data)
        assert data["status"] == "PENDING_REVIEW", "initial state must be PENDING_REVIEW"
        assert data["strike_count"] == 0
        assert data["lifetime_weight_lbs"] == 0
        assert data["pending_estimated_lbs"] == 0
        assert data["lifetime_tax_value_cents"] == 0
        assert data["enhanced_deduction_eligible"] is False, "flag defaults to false"
        assert isinstance(data["version"], int) and data["version"] >= 1

    def test_driver_and_cooler_creation_defaults(self, api):
        """PRD §3.1: "A new driver enters `ONBOARDING` with `reliability_score`
        100 and `completed_run_count` and `upheld_strike_count` at zero."
        PRD §3.1: "an optional `cold_chain_certified` flag defaulting to false."
        PRD §3.1: "coolers, each created with a human `label` and a
        `capacity_liters` volume that must be greater than zero, entering
        `AVAILABLE`."

        Design: Corner/entities/driver_and_cooler_creation_defaults
        """
        resp = api.create_volunteer_driver(
            create_volunteer_driver_payload(
                full_name="V Def", email="vd@example.com",
                vehicle_capacity_lbs=300, cooler_slot_count=1),
            ADMIN)
        driver = validate_success(resp, 201)
        assert_volunteer_driver(driver)
        assert driver["status"] == "ONBOARDING"
        assert driver["reliability_score"] == 100
        assert driver["cold_chain_certified"] is False
        assert driver["completed_run_count"] == 0
        assert driver["upheld_strike_count"] == 0

        resp = api.create_cooler(
            create_cooler_payload(label="C-DEF", capacity_liters=30), ADMIN)
        cooler = validate_success(resp, 201)
        assert_cooler(cooler)
        assert cooler["status"] == "AVAILABLE"
        assert cooler["cleaning_ends_at"] is None, (
            "cleaning_ends_at exists only for the CLEANING/QUARANTINED holding states"
        )


class TestOfferComputedFields:
    @pytest.mark.parametrize("category,expected", [
        ("COLD_HELD", True),
        ("HOT_HELD", True),
        ("PRODUCE", False),
        ("SHELF_STABLE", False),
    ])
    def test_requires_cold_chain_computed_from_category(self, api, category, expected):
        """PRD §3.2: "The server derives `requires_cold_chain` itself: it is true
        exactly when the category is `COLD_HELD` or `HOT_HELD`, and any
        client-supplied value for it is ignored."

        Design: Corner/entities/offer_requires_cold_chain_computed
        """
        donor = create_donor(
            legal_name="CC Bistro", ein="100000002",
            contact_email="cc@bistro.example", activate=False)
        # Deliberately pass a WRONG client value: the server must ignore it.
        payload = create_donation_offer_payload(
            donor_site_id=donor["id"], food_category=category,
            estimated_weight_lbs=10)
        payload["requires_cold_chain"] = not expected
        resp = api.create_donation_offer(
            payload, make_donor_coordinator_headers(donor["id"]))
        offer = validate_success(resp, 201)
        assert_donation_offer(offer)
        assert offer["requires_cold_chain"] is expected, (
            f"requires_cold_chain for {category} must be {expected} (server-computed)"
        )
        assert offer["status"] == "DRAFT"
        assert offer["failed_attempts"] == 0
