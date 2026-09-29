"""The concurrency layer on the two version-pinned engagement writes, and the
read-your-writes guarantee that a write response already carries every field it
derived.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    book_presented_engagement,
    clear_presented_rider,
    negotiate_and_accept_fee,
    read_engagement,
    read_price_tier,
    register_artist,
    register_hall,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["programming_director_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


class TestVersionPinnedWrites:

    def test_opening_a_round_on_a_stale_engagement_version_is_refused(self):
        """The risk assessment advances the engagement's version, so a director
        still holding the pre-assessment version cannot open a round that would
        supersede decisions taken since. Retrying with the observed version
        succeeds.

        PRD: "If that value does not equal the engagement's current `version`,
        the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/opening_a_negotiation_round_with_a_stale_engagement_version_is_rejected_with_412
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        stale_version = engagement["version"]

        assessed = assess_risk(engagement["id"], stale_version)
        assert assessed["risk_score"] == 10
        assert assessed["financial_clearance"] == "CLEARED"
        fresh_version = assessed["version"]
        assert fresh_version == stale_version + 1

        validate_error(api_client.open_fee_negotiation(
            engagement["id"],
            {"offered_fee_cents": 300_000, "offered_artist_share_pct": 0.10,
             "expected_engagement_version": stale_version},
            DIRECTOR), "ERR_STALE_ENGAGEMENT_VERSION")
        assert read_engagement(engagement["id"])["negotiation_round_count"] == 0

        opened = validate_success(api_client.open_fee_negotiation(
            engagement["id"],
            {"offered_fee_cents": 300_000, "offered_artist_share_pct": 0.10,
             "expected_engagement_version": fresh_version},
            DIRECTOR), expected_status=201)
        assert opened["round_index"] == 1
        assert opened["status"] == "OFFERED"

        after = read_engagement(engagement["id"])
        assert after["version"] == fresh_version + 1
        assert after["negotiation_round_count"] == 1
        assert after["financial_clearance"] == "CLEARED"
        assert after["risk_score"] == 10

        rounds, meta = validate_paginated(
            api_client.list_fee_negotiations(engagement["id"], DIRECTOR))
        assert meta["total_count"] == 1
        assert rounds[0]["id"] == opened["id"]

    def test_reassessing_risk_on_a_stale_engagement_version_is_refused(self):
        """Opening a negotiation round advances the engagement's version, so a
        controller holding the pre-round version cannot overwrite a clearance
        derived from inputs it never saw. The refused attempt writes nothing;
        the retry scores the standing offer against a house with no tiers yet
        and escalates.

        PRD: "Re-running the assessment overwrites the previous clearance
        decision, so a client holding a stale version would replace a clearance
        derived from inputs it never observed."

        Design: Corner/cross_cutting_layers/reassessing_risk_with_a_stale_engagement_version_is_rejected_with_412
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        stale_version = engagement["version"]

        opened = validate_success(api_client.open_fee_negotiation(
            engagement["id"],
            {"offered_fee_cents": 300_000, "offered_artist_share_pct": 0.10,
             "expected_engagement_version": stale_version},
            DIRECTOR), expected_status=201)
        assert opened["status"] == "OFFERED"
        fresh_version = read_engagement(engagement["id"])["version"]
        assert fresh_version == stale_version + 1

        validate_error(api_client.assess_risk(
            engagement["id"],
            {"expected_engagement_version": stale_version},
            FINANCE), "ERR_STALE_ENGAGEMENT_VERSION")

        untouched = read_engagement(engagement["id"])
        assert untouched["financial_clearance"] == "UNASSESSED"
        assert untouched["risk_score"] == 0
        assert untouched["version"] == fresh_version

        assessed = validate_success(api_client.assess_risk(
            engagement["id"],
            {"expected_engagement_version": fresh_version},
            FINANCE))
        assert assessed["risk_score"] == 55
        assert assessed["risk_tier"] == "HIGH"
        assert assessed["financial_clearance"] == "ESCALATED"
        assert assessed["version"] == fresh_version + 1


class TestReadYourWrites:

    def test_a_write_response_already_carries_every_field_it_derived(self):
        """The assessment response is not a receipt to be followed by a read: it
        already carries the score, the band, the clearance dimension, both
        projected figures and the advanced version, and the subsequent read
        returns exactly the same values.

        PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_changed_it
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        negotiate_and_accept_fee(engagement["id"], artist["id"], 300_000, 0.10)
        clear_presented_rider(engagement["id"], artist["id"])
        tier = add_price_tier(engagement["id"], tier_name="ORCH",
                              seats_allocated=100, base_price_cents=10_000,
                              price_ceiling_cents=15_000)
        version_before = read_engagement(engagement["id"])["version"]

        written = validate_success(api_client.assess_risk(
            engagement["id"],
            {"expected_engagement_version": version_before},
            FINANCE))
        assert written["risk_score"] == 27
        assert written["risk_tier"] == "LOW"
        assert written["financial_clearance"] == "CLEARED"
        assert written["projected_gross_cents"] == 800_000
        assert written["projected_margin_cents"] == 250_000
        assert written["version"] == version_before + 1

        read_back = read_engagement(engagement["id"])
        for field in ("risk_score", "risk_tier", "financial_clearance",
                      "projected_gross_cents", "projected_margin_cents",
                      "version"):
            assert read_back[field] == written[field]

        tier_after = read_price_tier(tier["id"])
        assert tier_after["seats_allocated"] == 100
        assert tier_after["sold_qty"] == 0
        assert tier_after["available_qty"] == 100
