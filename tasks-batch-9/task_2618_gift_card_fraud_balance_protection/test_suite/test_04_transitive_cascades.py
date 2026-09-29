"""Two multi-hop cascades where each link is caused by the one before it.

"Three multi-hop cascades exist and each is described in full where it originates":
this file drives the four-hop claim-reissue cascade and the three-hop rack-tamper
cascade, and checks every hop plus the hops each cascade deliberately does not take.
"""

from test_helpers import expected_gross_reissue, expected_missing_card_count
from test_helpers.fixtures import (
    audit_rack,
    create_rack,
    create_store,
    decide_claim,
    file_claim,
    funded_physical_card,
    open_period,
    read_card,
    read_period,
    read_rack,
    read_store,
    redeem,
    stock_card,
    total_count,
)
from test_helpers.test_users import (
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_risk_manager_headers,
)


DRAIN_LINES = [1010, 1030, 1050]


class TestClaimApprovalFourHopCascade:
    """Approval is "the head of a four-hop cascade"."""

    def _drained_card_with_claim(self, client):
        """A 20000-cent card drained by three unauthorized redemptions at a second store,
        an OPEN period covering the approval instant, and a SUBMITTED claim taken in by
        pos-7 carrying both evidence references."""
        store1 = create_store(client, name="Harbor Gifts", region_code="NE", address_line="9 Harbor Way")
        store2 = create_store(client, name="Transit Kiosk", region_code="NE", address_line="1 Transit Plz")
        rack = create_rack(client, store1["id"], rack_label="RACK-H1", expected_card_count=12)
        built = funded_physical_card(client, 20000, store=store1, rack=rack)
        card_id = built["card"]["id"]
        for index, amount in enumerate(DRAIN_LINES, start=1):
            redeem(client, card_id, amount, store2["id"], memo=f"drain {index}")
        period = open_period(client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", label="2026-08")
        claim = file_claim(
            client,
            card_id,
            disputed_amount_cents=3090,
            purchased_at="2026-08-01T00:00:00Z",
            headers=make_pos_associate_headers("pos-7"),
            claimant_name="Marcus Diallo",
            claimant_contact="marcus@example.com",
            purchase_receipt_ref="RCPT-5001",
            packaging_photo_ref="PHOTO-5001",
        )
        return {"store1": store1, "store2": store2, "card_id": card_id, "period": period, "claim": claim}

    def _approve(self, client, world):
        return decide_claim(
            client,
            world["claim"]["id"],
            "APPROVE",
            headers=make_risk_manager_headers("risk-7"),
            decision_note="packaging tampered, receipt matches activation",
        )

    def test_hop_one_freezes_the_per_line_recovery_arithmetic_onto_the_claim(self, client):
        """"Hop one freezes unauthorized_line_count, gross_reissue_cents,
        reissue_amount_cents and residual_transfer_cents onto the claim and records
        decided_by_user_id", where the recovery factor is "applied to each line
        individually, and each line's result is rounded to whole cents half-up before the
        addition".

        Design: Difficulty/transitive_cascade/claim_approval_four_hop_cascade_to_open_liability_period
        """
        world = self._drained_card_with_claim(client)

        approved = self._approve(client, world)

        assert approved["state"] == "APPROVED"
        assert approved["unauthorized_line_count"] == 3
        assert approved["gross_reissue_cents"] == 2628
        assert approved["gross_reissue_cents"] == expected_gross_reissue(DRAIN_LINES)
        assert approved["reissue_amount_cents"] == 2628
        assert approved["residual_transfer_cents"] == 16910
        assert approved["decided_by_user_id"] == "risk-7"

    def test_the_gross_proves_per_line_rounding_rather_than_rounding_the_sum(self, client):
        """"three lines of 1010, 1030 and 1050 cents at a recovery factor of 8500 basis
        points give 859 plus 876 plus 893, or 2628, whereas summing first and rounding
        once would give 2627".

        Design: Difficulty/transitive_cascade/claim_approval_four_hop_cascade_to_open_liability_period
        """
        world = self._drained_card_with_claim(client)

        approved = self._approve(client, world)

        assert approved["gross_reissue_cents"] == 859 + 876 + 893
        assert approved["gross_reissue_cents"] != 2627

    def test_hop_two_mints_a_replacement_card_funded_with_reissue_plus_residual(self, client):
        """"a replacement gift card is minted, inheriting the original card's channel and
        store_id ... carrying reissued_from_card_id pointed at the original, and created
        directly in ACTIVE", with "A ledger event of type REISSUE_CREDIT ... appended on it
        for reissue_amount_cents plus residual_transfer_cents".

        Design: Difficulty/transitive_cascade/claim_approval_four_hop_cascade_to_open_liability_period
        """
        world = self._drained_card_with_claim(client)

        approved = self._approve(client, world)

        replacement = read_card(client, approved["reissued_card_id"])
        assert replacement["activation_state"] == "ACTIVE"
        assert replacement["channel"] == "PHYSICAL"
        assert replacement["reissued_from_card_id"] == world["card_id"]
        assert replacement["current_balance_cents"] == 19538
        assert replacement["total_loaded_cents"] == 19538
        assert replacement["total_redeemed_cents"] == 0
        assert replacement["risk_posture"] == "CLEAR"

    def test_hop_three_closes_and_sweeps_the_compromised_original(self, client):
        """"the original card transitions to CLOSED — from ACTIVE or from DEPLETED alike —
        its closed_at is stamped from the logical clock, and a REISSUE_DEBIT event for
        residual_transfer_cents is appended".

        Design: Difficulty/transitive_cascade/claim_approval_four_hop_cascade_to_open_liability_period
        """
        world = self._drained_card_with_claim(client)

        self._approve(client, world)

        original = read_card(client, world["card_id"])
        assert original["activation_state"] == "CLOSED"
        assert original["current_balance_cents"] == 0
        assert original["closed_at"] is not None
        assert original["closed_at"] != ""

    def test_hop_four_lands_the_writeoff_on_the_open_period_without_closing_it(self, client):
        """"the OPEN liability period whose span contains the logical now has its
        unauthorized_writeoff_cents incremented by reissue_amount_cents", and while a
        period is OPEN "it accumulates nothing except writeoffs".

        Design: Difficulty/transitive_cascade/claim_approval_four_hop_cascade_to_open_liability_period
        """
        world = self._drained_card_with_claim(client)
        assert world["period"]["unauthorized_writeoff_cents"] == 0

        self._approve(client, world)

        period = read_period(client, world["period"]["id"])
        assert period["unauthorized_writeoff_cents"] == 2628
        assert period["state"] == "OPEN"

    def test_both_sides_of_the_reissue_link_are_filterable(self, client):
        """Cards list "filterable by store, rack, funding state, risk posture, channel or
        reissue origin", and claims list filterable by the replacement card they minted.

        Design: Difficulty/transitive_cascade/claim_approval_four_hop_cascade_to_open_liability_period
        """
        world = self._drained_card_with_claim(client)
        approved = self._approve(client, world)
        admin = make_platform_admin_headers()

        by_origin = client.list_gift_cards(admin, {"reissued_from_card_id": world["card_id"]})
        by_replacement = client.list_victim_claims(admin, {"reissued_card_id": approved["reissued_card_id"]})

        assert total_count(by_origin) == 1
        assert total_count(by_replacement) == 1


class TestRackTamperThreeHopCascade:
    """"The three-hop rack-tamper cascade begins the moment an audit classifies a rack
    TAMPERED"."""

    def _stocked_store(self, client):
        """A rack expecting 10 cards with four cards stocked against it, one of which is
        activated for 5000 cents while the other three stay INACTIVE."""
        store = create_store(client, name="Riverbend Pharmacy", region_code="MW", address_line="77 Riverbend Rd")
        rack = create_rack(client, store["id"], rack_label="RACK-R1", expected_card_count=10)
        live = funded_physical_card(client, 5000, store=store, rack=rack)
        inactive = [
            stock_card(client, store["id"], rack["id"], card_number_masked=f"****-****-****-600{n}")
            for n in (2, 3, 4)
        ]
        return {"store": store, "rack": rack, "live_card_id": live["card"]["id"], "inactive": inactive}

    def test_hop_one_classifies_the_rack_tampered_at_the_shrink_threshold(self, client):
        """"the difference between expected_card_count and observed_card_count" is the
        shrink, and a rack is TAMPERED when it is "at or above rack_shrink_threshold" —
        the audit inputs being persisted verbatim so the classification is reproducible.

        Design: Difficulty/transitive_cascade/rack_tamper_three_hop_cascade_suspends_store_and_voids_inactive_cards
        """
        world = self._stocked_store(client)

        audited = audit_rack(client, world["rack"]["id"], observed_card_count=7, seal_breaks_observed=0)

        assert audited["missing_card_count"] == 3
        assert audited["missing_card_count"] == expected_missing_card_count(10, 7)
        assert audited["seal_breaks_observed"] == 0
        assert audited["tamper_state"] == "TAMPERED"
        assert audited["observed_card_count"] == 7
        assert audited["last_audit_at"] is not None

    def test_hop_two_suspends_the_floor_skipping_heightened_entirely(self, client):
        """"Hop two is the store's recomputation, which — because tampered_rack_count is
        now at least 1 — drives floor_posture to SUSPENDED from either OPEN or
        HEIGHTENED."

        Design: Difficulty/transitive_cascade/rack_tamper_three_hop_cascade_suspends_store_and_voids_inactive_cards
        """
        world = self._stocked_store(client)
        assert world["store"]["floor_posture"] == "OPEN"

        audit_rack(client, world["rack"]["id"], observed_card_count=7, seal_breaks_observed=0)

        store = read_store(client, world["store"]["id"])
        assert store["tampered_rack_count"] == 1
        assert store["floor_posture"] == "SUSPENDED"

    def test_hop_three_voids_and_freezes_only_the_unfunded_stock(self, client):
        """"every gift card belonging to that store whose funding state is still INACTIVE
        transitions to VOIDED, has its fraud posture forced to FROZEN ... Cards that are
        ACTIVE, DEPLETED or CLOSED are left completely untouched, because their value is
        already funded and belongs to a customer."

        Design: Difficulty/transitive_cascade/rack_tamper_three_hop_cascade_suspends_store_and_voids_inactive_cards
        """
        world = self._stocked_store(client)

        audit_rack(client, world["rack"]["id"], observed_card_count=7, seal_breaks_observed=0)

        for stocked in world["inactive"]:
            voided = read_card(client, stocked["id"])
            assert voided["activation_state"] == "VOIDED"
            assert voided["risk_posture"] == "FROZEN"
        live = read_card(client, world["live_card_id"])
        assert live["activation_state"] == "ACTIVE"
        assert live["risk_posture"] == "CLEAR"
        assert live["current_balance_cents"] == 5000

    def test_the_cascade_is_visible_through_the_collection_filters(self, client):
        """Cards list filterable by "funding state" and racks list by tamper state, so the
        cascade's reach is countable: three cards VOIDED and exactly one rack TAMPERED.

        Design: Difficulty/transitive_cascade/rack_tamper_three_hop_cascade_suspends_store_and_voids_inactive_cards
        """
        world = self._stocked_store(client)
        admin = make_platform_admin_headers()

        audit_rack(client, world["rack"]["id"], observed_card_count=7, seal_breaks_observed=0)

        assert total_count(client.list_gift_cards(admin, {"activation_state": "VOIDED"})) == 3
        assert total_count(client.list_card_racks(admin, {"tamper_state": "TAMPERED"})) == 1
        assert read_rack(client, world["rack"]["id"])["tamper_state"] == "TAMPERED"
