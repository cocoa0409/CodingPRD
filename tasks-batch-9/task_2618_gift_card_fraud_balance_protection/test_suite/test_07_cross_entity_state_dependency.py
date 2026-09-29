"""Outcomes decided by the live state of a second entity, read at operation time.

An issuance screening reads its rack's classification, and a listing validation reads its
card's fraud posture — in both cases the referenced row moved after the request was made.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_RACK_TAMPERED
from test_helpers.fixtures import (
    audit_rack,
    create_rack,
    create_store,
    funded_physical_card,
    inquire,
    open_physical_issuance,
    override_posture,
    read_card,
    read_rack,
    read_store,
    stock_card,
    submit_listing,
    total_count,
    validate_listing,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_reseller_partner_headers,
)


class TestScreeningReadsLiveRackState:
    """"the rack backing a physical issuance must be classified INTACT, otherwise
    ERR_RACK_TAMPERED (422) — checked when the request is opened, when it is screened, and
    when a card is stocked onto the rack"."""

    def _request_then_audit(self, client):
        """A PHYSICAL request for 4000 cents opened while the rack is INTACT, and only then
        an audit of 1 missing card and 1 seal break, both "below their thresholds"."""
        store = create_store(client, name="Gateway Foods", region_code="SW", address_line="60 Gateway Blvd")
        rack = create_rack(client, store["id"], rack_label="RACK-G1", expected_card_count=10)
        assert rack["tamper_state"] == "INTACT"
        card = stock_card(client, store["id"], rack["id"], card_number_masked="****-****-****-1101")
        request = open_physical_issuance(
            client, store["id"], rack["id"], card["id"], 4000, pos_terminal_id="T-11"
        )
        audited = audit_rack(client, rack["id"], observed_card_count=9, seal_breaks_observed=1)
        return {"store": store, "rack": rack, "card": card, "request": request, "audited": audited}

    def test_the_audit_lands_the_rack_on_suspect_below_both_thresholds(self, client):
        """A shrink of 1 and 1 seal break are each below the tamper thresholds, so the rack
        is SUSPECT and — "if suspect_rack_count is at least 1 ... the floor is HEIGHTENED".

        Design: Difficulty/cross_entity_state_dependency/physical_issuance_screen_blocked_by_suspect_rack_state
        """
        world = self._request_then_audit(client)

        assert world["request"]["state"] == "SUBMITTED"
        assert world["audited"]["missing_card_count"] == 1
        assert world["audited"]["tamper_state"] == "SUSPECT"
        assert read_store(client, world["store"]["id"])["floor_posture"] == "HEIGHTENED"

    def test_screening_is_refused_on_the_racks_state_at_screen_time(self, client):
        """The rack guard is "checked when the request is opened, when it is screened, and
        when a card is stocked onto the rack", so a request that was legal at creation is
        still refused once its rack leaves INTACT.

        Design: Difficulty/cross_entity_state_dependency/physical_issuance_screen_blocked_by_suspect_rack_state
        """
        world = self._request_then_audit(client)

        response = client.screen_issuance_request(
            world["request"]["id"], make_pos_associate_headers()
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_RACK_TAMPERED, 422)

    def test_the_refused_screening_parks_the_request_and_mints_no_value(self, client):
        """A refused screening leaves the request where it was, with "screening_score,
        screening_components and decline_reason all empty and screened_at not yet stamped",
        and the card still "created inactive with a zero balance".

        Design: Difficulty/cross_entity_state_dependency/physical_issuance_screen_blocked_by_suspect_rack_state
        """
        world = self._request_then_audit(client)
        version_before = world["request"]["version"]

        client.screen_issuance_request(world["request"]["id"], make_pos_associate_headers())

        request = client.get_issuance_request(
            world["request"]["id"], make_platform_admin_headers()
        ).json()["data"]
        assert request["state"] == "SUBMITTED"
        assert not request["screened_at"]
        assert not request["screening_score"]
        assert request["version"] == version_before
        card = read_card(client, world["card"]["id"])
        assert card["activation_state"] == "INACTIVE"
        assert card["current_balance_cents"] == 0
        assert read_rack(client, world["rack"]["id"])["tamper_state"] == "SUSPECT"
        events = client.list_ledger_events(make_platform_admin_headers(), {"card_id": card["id"]})
        assert total_count(events) == 0


class TestListingValidationReadsCardPosture:
    """Two byte-identical listings whose only difference is the referenced card's posture."""

    def _two_listings(self, client):
        """cardA walked to WATCH by four inquiries scoring 48, cardB pushed to RESTRICTED by
        an override, and one SUBMITTED listing per card with identical own fields."""
        store = create_store(client, name="Uptown Electronics", region_code="NW", address_line="18 Uptown Ave")
        rack = create_rack(client, store["id"], rack_label="RACK-U1", expected_card_count=7)
        card_a = funded_physical_card(client, 6000, store=store, rack=rack)["card"]
        card_b = funded_physical_card(client, 6000, store=store, rack=rack)["card"]
        partner = make_reseller_partner_headers("partner-2")
        inquiries = [
            inquire(client, card_a["id"], "WEB", headers=partner, requester_ip_hash="iph-a1")
            for _ in range(4)
        ]
        posture_a = read_card(client, card_a["id"])
        posture_b = override_posture(client, card_b["id"], "RESTRICTED", reason="suspected drain pattern")
        listing_a = submit_listing(client, card_a["id"], 6000, "GiftBay", headers=partner, asking_price_cents=5400)
        listing_b = submit_listing(client, card_b["id"], 6000, "GiftBay", headers=partner, asking_price_cents=5400)
        return {
            "card_a": card_a,
            "card_b": card_b,
            "inquiries": inquiries,
            "posture_a": posture_a,
            "posture_b": posture_b,
            "listing_a": listing_a,
            "listing_b": listing_b,
        }

    def test_only_the_referenced_cards_posture_differs_between_the_two(self, client):
        """"A posture of CLEAR or WATCH passes check two, so a watched card with a matching
        balance and a sub-threshold inquiry score validates — WATCH is informational, not
        blocking."

        Design: Difficulty/cross_entity_state_dependency/reseller_listing_validation_gated_by_gift_card_risk_posture
        """
        world = self._two_listings(client)

        assert world["listing_a"]["state"] == "SUBMITTED"
        assert world["listing_b"]["state"] == "SUBMITTED"
        assert world["inquiries"][3]["velocity_count_at_inquiry"] == 4
        assert world["inquiries"][3]["drain_score_at_inquiry"] == 48
        assert world["posture_a"]["drain_risk_score_inquiry"] == 48
        assert world["posture_a"]["risk_posture"] == "WATCH"
        assert world["posture_b"]["risk_posture"] == "RESTRICTED"
        alerts = client.list_draining_alerts(
            make_fraud_analyst_headers("analyst-2"), {"card_id": world["card_a"]["id"]}
        )
        assert total_count(alerts) == 0

    def test_the_watched_card_validates_while_the_restricted_card_blocks(self, client):
        """"if the card's risk_posture is RESTRICTED or FROZEN, the listing becomes BLOCKED
        with block_reason CARD_RISK_POSTURE.  Otherwise ... the listing becomes VALIDATED
        and block_reason stays empty."

        Design: Difficulty/cross_entity_state_dependency/reseller_listing_validation_gated_by_gift_card_risk_posture
        """
        world = self._two_listings(client)
        analyst = make_fraud_analyst_headers("analyst-2")

        decided_a = validate_listing(
            client, world["listing_a"]["id"], headers=analyst, validation_note="routine marketplace check"
        )
        decided_b = validate_listing(
            client, world["listing_b"]["id"], headers=analyst, validation_note="routine marketplace check"
        )

        assert decided_a["state"] == "VALIDATED"
        assert not decided_a["block_reason"]
        assert decided_b["state"] == "BLOCKED"
        assert decided_b["block_reason"] == "CARD_RISK_POSTURE"

    def test_the_block_came_from_check_two_and_not_from_the_balance_check(self, client):
        """Both listings quote their card's exact balance, so check three — "if the listing's
        listed_balance_cents is not exactly equal to the card's current_balance_cents" —
        was satisfied on both and only the posture separated the verdicts.

        Design: Difficulty/cross_entity_state_dependency/reseller_listing_validation_gated_by_gift_card_risk_posture
        """
        world = self._two_listings(client)
        analyst = make_fraud_analyst_headers("analyst-2")
        validate_listing(client, world["listing_a"]["id"], headers=analyst)
        validate_listing(client, world["listing_b"]["id"], headers=analyst)

        assert world["listing_a"]["listed_balance_cents"] == 6000
        assert read_card(client, world["card_a"]["id"])["current_balance_cents"] == 6000
        assert world["listing_b"]["listed_balance_cents"] == 6000
        assert read_card(client, world["card_b"]["id"])["current_balance_cents"] == 6000
        blocked = client.list_reseller_listings(make_platform_admin_headers(), {"state": "BLOCKED"})
        assert total_count(blocked) == 1
        per_card = client.list_card_reseller_listings(world["card_a"]["id"], make_platform_admin_headers())
        assert total_count(per_card) == 1
