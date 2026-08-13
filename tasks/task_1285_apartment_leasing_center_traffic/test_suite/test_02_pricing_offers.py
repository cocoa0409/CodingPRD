"""Pricing offers: effective-rent concession math, publish/retire rules, and
lazy expiry at the expires_at boundary."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_floorplan,
    create_pricing_offer,
    create_property,
    get_pricing_offer,
    publish_offer,
    retire_offer,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]


def _site(code, rent=200000, total_units=3):
    prop = create_property(name=f"Site {code}", code=code)
    floorplan = create_floorplan(prop["id"], base_rent_cents=rent,
                                 total_units=total_units)
    return prop, floorplan


class TestEffectiveRent:
    def test_effective_rent_percent_off_applies_rounding(self, api,
                                                         property_manager_headers):
        """PRD §3.2: "With `PERCENT_OFF` it is `base_rent_cents` multiplied by the
        remaining percentage — one hundred minus `concession_value`, over one
        hundred — rounded half-up to whole cents."
        PRD §3.2: "The offer's displayed price, `effective_monthly_rent_cents`, is
        computed at creation and stored on the offer."

        Design: Corner/calculations/effective_rent_percent_off_applies_rounding
        """
        prop, floorplan = _site("PC1", rent=199999)
        resp = api.create_pricing_offer(
            {"property_id": prop["id"], "floorplan_id": floorplan["id"],
             "base_rent_cents": 199999, "concession_type": "PERCENT_OFF",
             "concession_value": 10, "lease_term_months": 12,
             "effective_start": "2026-08-01T00:00:00Z",
             "expires_at": "2026-09-01T00:00:00Z"},
            property_manager_headers)
        offer = validate_success(resp, 201)
        # round_half_up(199999 * 90 / 100) = round_half_up(179999.1) = 179999
        assert offer["effective_monthly_rent_cents"] == 179999

    def test_effective_rent_free_months_two_of_twelve_amortized(self, api,
                                                                property_manager_headers):
        """PRD §3.2: "With `FREE_MONTHS`, the billed-month count is
        `lease_term_months` minus the smaller of `concession_value` and
        `lease_term_months`, never below zero, and the effective rent is
        `base_rent_cents` multiplied by the billed months and divided by
        `lease_term_months`, rounded half-up to whole cents."
        PRD §3.2: "Offers are born `DRAFT`."

        Design: Difficulty/combinatorial_formula/effective_rent_free_months_branch_and_clamps
        """
        prop, floorplan = _site("CB1", rent=200000, total_units=5)
        resp = api.create_pricing_offer(
            {"property_id": prop["id"], "floorplan_id": floorplan["id"],
             "base_rent_cents": 200000, "concession_type": "FREE_MONTHS",
             "concession_value": 2, "lease_term_months": 12,
             "effective_start": "2026-08-01T00:00:00Z",
             "expires_at": "2026-09-01T00:00:00Z"},
            property_manager_headers)
        offer = validate_success(resp, 201)
        # billed = 12 - min(2, 12) = 10; round_half_up(200000 * 10 / 12) = 166667
        assert offer["effective_monthly_rent_cents"] == 166667
        assert offer["status"] == "DRAFT"

    def test_effective_rent_free_months_clamps_at_lease_term(self, api,
                                                             property_manager_headers):
        """PRD §3.2: "With `FREE_MONTHS`, the billed-month count is
        `lease_term_months` minus the smaller of `concession_value` and
        `lease_term_months`, never below zero, and the effective rent is
        `base_rent_cents` multiplied by the billed months and divided by
        `lease_term_months`, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/effective_rent_free_months_branch_and_clamps
        """
        prop, floorplan = _site("CB2", rent=200000, total_units=5)
        resp = api.create_pricing_offer(
            {"property_id": prop["id"], "floorplan_id": floorplan["id"],
             "base_rent_cents": 200000, "concession_type": "FREE_MONTHS",
             "concession_value": 14, "lease_term_months": 12,
             "effective_start": "2026-08-01T00:00:00Z",
             "expires_at": "2026-09-01T00:00:00Z"},
            property_manager_headers)
        offer = validate_success(resp, 201)
        # billed = 12 - min(14, 12) = 0 -> effective rent 0 (the nested min/max clamp)
        assert offer["effective_monthly_rent_cents"] == 0


class TestPublishRetire:
    def test_publish_second_offer_for_floorplan_rejected(self, api):
        """PRD §3.2: "Publishing one requires it to be `DRAFT` (anything else is
        `ERR_PRICING_OFFER_INVALID_STATE`), requires that no other offer for the
        same floorplan currently be `PUBLISHED` (`ERR_OFFER_ALREADY_PUBLISHED`),
        and requires its `expires_at` to lie strictly after the current logical
        time — publishing an already-lapsed offer is rejected with
        `ERR_INVALID_TIME_RANGE`."
        PRD §3.2: "Retiring works from either `DRAFT` or `PUBLISHED` and lands the
        offer in the terminal `RETIRED` state."

        Design: Corner/validations/publish_second_offer_for_floorplan_rejected
        """
        prop, floorplan = _site("DS1")
        offer1 = create_pricing_offer(prop["id"], floorplan["id"],
                                      base_rent_cents=200000)
        publish_offer(offer1["id"])
        offer2 = create_pricing_offer(prop["id"], floorplan["id"],
                                      base_rent_cents=190000)

        resp = api.publish_pricing_offer(offer2["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OFFER_ALREADY_PUBLISHED)

        # After retiring the first offer, the second publishes cleanly.
        retire_offer(offer1["id"])
        republish = api.publish_pricing_offer(offer2["id"], PM)
        assert validate_success(republish)["status"] == "PUBLISHED"
        assert get_pricing_offer(offer1["id"])["status"] == "RETIRED"

    def test_publish_already_published_returns_invalid_state(self, api,
                                                             property_manager_headers):
        """PRD §3.2: "Publishing one requires it to be `DRAFT` (anything else is
        `ERR_PRICING_OFFER_INVALID_STATE`), requires that no other offer for the
        same floorplan currently be `PUBLISHED` (`ERR_OFFER_ALREADY_PUBLISHED`),
        and requires its `expires_at` to lie strictly after the current logical
        time — publishing an already-lapsed offer is rejected with
        `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/publish_already_published_returns_invalid_state
        """
        prop, floorplan = _site("RP1", total_units=2)
        offer = create_pricing_offer(prop["id"], floorplan["id"])
        publish_offer(offer["id"])

        resp = api.publish_pricing_offer(offer["id"], property_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PRICING_OFFER_INVALID_STATE)
        assert get_pricing_offer(offer["id"])["status"] == "PUBLISHED"


class TestOfferExpiry:
    def test_pricing_offer_expires_at_clock_boundary(self, api):
        """PRD §3.2: "When the logical clock reaches a published offer's
        `expires_at`, the offer expires lazily per §2.4, landing in the terminal
        `EXPIRED` state, and the floorplan's pricing display falls back to the
        floorplan's `base_rent_cents` for subsequent reads and calculations."
        PRD §2.4: "A pricing offer whose `expires_at` has been reached becomes
        `EXPIRED` the next time the offer is read or any operation references it;"

        Design: Corner/calculations/pricing_offer_expires_at_clock_boundary
        """
        prop, floorplan = _site("EX1", total_units=2)
        offer = create_pricing_offer(prop["id"], floorplan["id"],
                                     concession_type="FLAT_AMOUNT",
                                     concession_value=10000,
                                     expires_at="2026-08-10T00:00:00Z")
        publish_offer(offer["id"])

        set_clock("2026-08-09T23:59:59Z")
        assert get_pricing_offer(offer["id"])["status"] == "PUBLISHED"

        set_clock("2026-08-10T00:00:00Z")
        # The read performs the lazy sweep: clock >= expires_at means EXPIRED.
        assert get_pricing_offer(offer["id"])["status"] == "EXPIRED"
