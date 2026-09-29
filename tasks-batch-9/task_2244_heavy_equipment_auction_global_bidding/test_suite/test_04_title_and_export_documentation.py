"""The compliance desk: the lien and title axis, and the buyer's export document packet."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_export_packet,
    catalog_ready_lot,
    clear_lot_title,
    confirmed_invoice,
    create_export_packet_payload,
    encumber_lot_title,
    export_packet_transition_payload,
    lien_release_payload,
    lot_assignment_payload,
    new_auction,
    new_consignment,
    new_consignor,
    new_lot,
    paid_invoice,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COMPLIANCE, OPERATOR, SETTLEMENT

NIGERIAN_BUYER = {
    "legal_name": "Lagos Plant Hire Ltd",
    "country_code": "NG",
    "tax_id": "NG-0000001",
}
GERMAN_BUYER = {
    "legal_name": "Rheintal Baumaschinen GmbH",
    "country_code": "DE",
    "tax_id": "DE811234567",
}


def _nigerian_cross_border_invoice():
    """A 2,000,000-cent hammer bought by a Nigerian paddle, so the invoice is cross-border."""
    return confirmed_invoice(
        bid_amount_cents=2_000_000,
        lot_overrides={
            "make": "Komatsu",
            "model": "PC210",
            "serial_number": "KOM-PC210-0001",
            "weight_kg": 9_000,
            "reserve_price_cents": 2_000_000,
        },
        bidder_overrides=NIGERIAN_BUYER,
        deposit_cents=1_500_000,
        deposit_hold_cents=1_500_000,
    )


class TestLienAxis:
    def test_a_release_cannot_be_recorded_on_a_lot_that_never_carried_a_lien(self):
        """The release edge starts at LIEN_ENCUMBERED only, so firing it on a clear lot is an
        invalid state and leaves the axis exactly where the search left it.

        PRD 3.3: "An encumbrance is cleared by recording the lienholder's release, which
        supplies a `release_document_ref` and moves the lot `LIEN_ENCUMBERED → LIEN_RELEASED`."
        PRD 2.8: "The target is in a state from which the requested transition is declared
        — otherwise `ERR_INVALID_STATE` (409). This is the generic guard; every
        terminal-state lockdown and every replayed one-shot action lands here."

        Design: Corner/state_machines/lien_release_from_lien_clear_returns_409_invalid_state
        """
        reset_clock()
        consignor = new_consignor()
        consignment = new_consignment(consignor)
        lot = new_lot(consignment, consignor, serial_number="CAT-D8T-0001")
        cleared = clear_lot_title(lot, reference="LS-0001")
        assert cleared["title_status"] == "LIEN_CLEAR"

        response = api_client.release_lien(
            lot["id"], lien_release_payload(release_document_ref="REL-0001"), COMPLIANCE
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        stored = validate_success(api_client.get_lot(lot["id"], COMPLIANCE))
        assert stored["title_status"] == "LIEN_CLEAR"
        assert stored["lienholder_name"] is None
        assert stored["lien_search_reference"] == "LS-0001"

    def test_an_encumbered_machine_joins_the_catalogue_only_after_the_release(self):
        """Everything but the title axis is ready, so the assignment is refused with the title
        error and the identical call succeeds once the lienholder's release is on file.

        PRD 3.3: "Title clearance gates three separate operations, all of them refusing with
        `ERR_TITLE_NOT_CLEAR` when the lot's `title_status` is neither `LIEN_CLEAR` nor
        `LIEN_RELEASED`: assigning the lot to an auction catalogue, authorising the physical
        release of the machine after sale, and attaching a title document to the buyer's
        export packet."
        PRD 3.4: "A successful assignment stamps the lot's `auction_id`, moves the lot
        `CATALOG_READY → ASSIGNED`, recomputes the auction's `assigned_lot_count`, and
        increments both the lot's `version` and the auction's `version` by 1."

        Design: Corner/errors/encumbered_title_blocks_the_assignment_until_the_lien_is_released
        """
        stage = catalog_ready_lot(
            lot_overrides={"serial_number": "CAT-D8T-0001"}, clear_title=False
        )
        lot = stage["lot"]
        encumbered = encumber_lot_title(lot)
        assert encumbered["title_status"] == "LIEN_ENCUMBERED"
        auction = new_auction(stage["yard"])

        refused = api_client.assign_lot_to_auction(
            auction["id"], lot_assignment_payload(lot["id"]), OPERATOR
        )
        validate_error(refused, ApiErrorId.ERR_TITLE_NOT_CLEAR, expected_status=409)
        held = validate_success(api_client.get_lot(lot["id"], OPERATOR))
        assert held["lifecycle_status"] == "CATALOG_READY"
        assert held["auction_id"] is None

        released = validate_success(
            api_client.release_lien(
                lot["id"], lien_release_payload(release_document_ref="REL-0007"), COMPLIANCE
            )
        )
        assert released["title_status"] == "LIEN_RELEASED"

        validate_success(
            api_client.assign_lot_to_auction(
                auction["id"], lot_assignment_payload(lot["id"]), OPERATOR
            ),
            expected_status=201,
        )

        assigned = validate_success(api_client.get_lot(lot["id"], OPERATOR))
        assert assigned["lifecycle_status"] == "ASSIGNED"
        assert assigned["auction_id"] == auction["id"]
        assert (
            validate_success(api_client.get_auction(auction["id"], OPERATOR))[
                "assigned_lot_count"
            ]
            == 1
        )


class TestExportPacketOpening:
    def test_a_packet_must_be_aimed_at_the_buyers_own_country(self):
        """A packet for Great Britain on a Nigerian buyer's invoice is refused and writes
        nothing; the Nigerian packet opens in PREPARING with both references still empty.

        PRD 3.3: "Two conditions must hold: the destination must equal the buyer's
        `country_code`, and the invoice must actually be cross-border. A packet aimed at a
        country other than the buyer's, or opened against a domestic invoice, is refused with
        `ERR_DESTINATION_COUNTRY_MISMATCH`."
        PRD 3.3: "A new packet is created in `PREPARING` with `reopen_count` at 0 and
        `title_document_ref`, `customs_entry_ref` and `rejection_reason` all null."

        Design: Corner/endpoints/export_packet_links_an_invoice_to_the_buyers_own_country
        """
        stage = _nigerian_cross_border_invoice()
        invoice = stage["invoice"]
        assert invoice["is_cross_border"] is True

        wrong_destination = api_client.create_export_packet(
            create_export_packet_payload(invoice["id"], "GB"), COMPLIANCE
        )
        validate_error(
            wrong_destination,
            ApiErrorId.ERR_DESTINATION_COUNTRY_MISMATCH,
            expected_status=422,
        )

        packet = validate_success(
            api_client.create_export_packet(
                create_export_packet_payload(invoice["id"], "NG"), COMPLIANCE
            ),
            expected_status=201,
        )
        assert_export_packet(packet)
        assert packet["status"] == "PREPARING"
        assert packet["invoice_id"] == invoice["id"]
        assert packet["title_document_ref"] is None
        assert packet["customs_entry_ref"] is None
        assert packet["rejection_reason"] is None
        assert packet["reopen_count"] == 0

        _, meta = validate_paginated(
            api_client.list_invoice_export_packets(invoice["id"], COMPLIANCE)
        )
        assert meta["total_count"] == 1

        stored = validate_success(api_client.get_export_packet(packet["id"], COMPLIANCE))
        assert stored["destination_country_code"] == "NG"

    def test_the_documentation_pipeline_may_be_reopened_twice_and_no_more(self):
        """Each reopening wipes both references and counts a lap; the third is refused and
        leaves the rejected packet with its third-lap references intact.

        PRD 3.3: "`REOPEN` moves it `CUSTOMS_REJECTED → PREPARING`, increments `reopen_count`
        by 1, and clears both `title_document_ref` and `customs_entry_ref` back to null so
        the whole pipeline is walked again from the start; it is only available while
        `reopen_count` is still below 2, and a third reopening is refused with
        `ERR_MAX_PACKET_REOPENS_EXCEEDED`."
        PRD 3.3: "`REJECT` moves it `CUSTOMS_FILED → CUSTOMS_REJECTED` and requires a
        `rejection_reason`."

        Design: Corner/state_machines/export_packet_reopen_loop_stops_after_two_laps
        """
        stage = _nigerian_cross_border_invoice()
        packet = validate_success(
            api_client.create_export_packet(
                create_export_packet_payload(stage["invoice"]["id"], "NG"), COMPLIANCE
            ),
            expected_status=201,
        )

        def transition(action, **payload):
            return validate_success(
                api_client.transition_export_packet(
                    packet["id"], export_packet_transition_payload(action, **payload), COMPLIANCE
                )
            )

        for lap, reason in enumerate(
            ("HS code mismatch", "valuation query", "third strike"), start=1
        ):
            transition("ATTACH_TITLE", title_document_ref=f"TTL-{lap}")
            transition("FILE_CUSTOMS", customs_entry_ref=f"CBP-{lap}")
            rejected = transition("REJECT", rejection_reason=reason)
            assert rejected["status"] == "CUSTOMS_REJECTED"
            if lap == 3:
                break
            reopened = transition("REOPEN")
            assert reopened["status"] == "PREPARING"
            assert reopened["reopen_count"] == lap
            assert reopened["title_document_ref"] is None
            assert reopened["customs_entry_ref"] is None

        response = api_client.transition_export_packet(
            packet["id"], export_packet_transition_payload("REOPEN"), COMPLIANCE
        )

        validate_error(
            response, ApiErrorId.ERR_MAX_PACKET_REOPENS_EXCEEDED, expected_status=422
        )

        stored = validate_success(api_client.get_export_packet(packet["id"], COMPLIANCE))
        assert stored["status"] == "CUSTOMS_REJECTED"
        assert stored["reopen_count"] == 2
        assert stored["title_document_ref"] == "TTL-3"
        assert stored["customs_entry_ref"] == "CBP-3"


class TestReleaseNeedsExportClearance:
    def test_a_paid_cross_border_invoice_stays_held_while_no_packet_is_cleared(self):
        """Money is settled and the title is clear, so only the missing customs clearance on
        a different entity is left to refuse the release.

        PRD 3.8: "Moving the custody axis `HELD → RELEASE_AUTHORIZED` is a
        `SettlementOfficer` action with four preconditions, each with its own refusal: the
        invoice's `payment_status` must be `PAID`, otherwise `ERR_INVOICE_NOT_PAID`; the
        underlying sale's `status` must be `CONFIRMED` or `SETTLED`; the lot's `title_status`
        must be `LIEN_CLEAR` or `LIEN_RELEASED`, otherwise `ERR_TITLE_NOT_CLEAR`; and either
        the invoice is not cross-border, or one of its export packets has reached
        `EXPORT_CLEARED`, otherwise `ERR_EXPORT_NOT_CLEARED`."
        PRD 3.8: "Its `is_cross_border` flag is true exactly when the buyer's `country_code`
        differs from the auction yard's `country_code`."
        PRD 3.8: "`documentation_fee_cents` is 45,000 cents when `is_cross_border` is true and
        15,000 cents when it is false."

        Design: Difficulty/cross_entity_state_dependency/release_authorization_requires_export_packet_cleared
        """
        stage = paid_invoice(
            lot_overrides={
                "serial_number": "CAT-D8T-0001",
                "reserve_price_cents": 10_000_000,
            },
            bidder_overrides=GERMAN_BUYER,
        )
        invoice = stage["invoice"]
        assert invoice["is_cross_border"] is True
        assert invoice["documentation_fee_cents"] == 45_000
        assert invoice["payment_status"] == "PAID"
        assert invoice["release_status"] == "HELD"
        assert stage["lot"]["title_status"] == "LIEN_CLEAR"

        response = api_client.authorize_release(invoice["id"], SETTLEMENT)

        validate_error(response, ApiErrorId.ERR_EXPORT_NOT_CLEARED, expected_status=409)

        held = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert held["release_status"] == "HELD"
        assert held["payment_status"] == "PAID"

    def test_clearing_the_packet_unblocks_the_release_without_restamping_the_money(self):
        """Walking the packet to EXPORT_CLEARED lets the identical release through, while the
        invoice keeps its provisional German tax until finalisation.

        PRD 3.3: "`CLEAR` moves it `CUSTOMS_FILED → EXPORT_CLEARED`, which is terminal."
        PRD 3.3: "Reaching `EXPORT_CLEARED` has a fiscal consequence that is worth stating
        precisely: it makes the buyer's final settlement zero-rated for tax, but it does
        **not** itself restamp the invoice."
        PRD 3.8: "The provisional variant is stamped at invoice creation and always applies
        the buyer's own domestic tax rate — even on a cross-border sale — because no customs
        clearance can exist at hammer time".
        PRD 3.8: "`tax_rate_applied` is keyed to the buyer's country: 0.0625 for `US`, 0.13
        for `CA`, 0.16 for `MX`, 0.19 for `DE`".

        Design: Difficulty/cross_entity_state_dependency/release_authorization_requires_export_packet_cleared
        """
        stage = paid_invoice(
            lot_overrides={
                "serial_number": "CAT-D8T-0001",
                "reserve_price_cents": 10_000_000,
            },
            bidder_overrides=GERMAN_BUYER,
        )
        invoice = stage["invoice"]
        validate_error(
            api_client.authorize_release(invoice["id"], SETTLEMENT),
            ApiErrorId.ERR_EXPORT_NOT_CLEARED,
            expected_status=409,
        )

        packet = validate_success(
            api_client.create_export_packet(
                create_export_packet_payload(invoice["id"], "DE"), COMPLIANCE
            ),
            expected_status=201,
        )
        validate_success(
            api_client.transition_export_packet(
                packet["id"],
                export_packet_transition_payload(
                    "ATTACH_TITLE", title_document_ref="MSO-DE-0001"
                ),
                COMPLIANCE,
            )
        )
        validate_success(
            api_client.transition_export_packet(
                packet["id"],
                export_packet_transition_payload("FILE_CUSTOMS", customs_entry_ref="EEI-0001"),
                COMPLIANCE,
            )
        )
        cleared = validate_success(
            api_client.transition_export_packet(
                packet["id"], export_packet_transition_payload("CLEAR"), COMPLIANCE
            )
        )
        assert cleared["status"] == "EXPORT_CLEARED"

        authorized = validate_success(api_client.authorize_release(invoice["id"], SETTLEMENT))

        assert authorized["release_status"] == "RELEASE_AUTHORIZED"
        assert authorized["payment_status"] == "PAID"
        assert authorized["settlement_variant"] == "PROVISIONAL"
        assert authorized["tax_cents"] == 2_508_950
        assert authorized["storage_fee_cents"] == 0
