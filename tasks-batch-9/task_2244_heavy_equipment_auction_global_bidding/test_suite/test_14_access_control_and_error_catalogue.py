"""Who may act, whose row it is, and which identifier the server names when it refuses."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_auction_payload,
    create_bidder_payload,
    create_bidder_registration_payload,
    create_condition_report_payload,
    create_consignment_payload,
    create_consignor_payload,
    create_deposit_payload,
    create_lot_payload,
    create_yard_payload,
    credit_decision_payload,
    create_bid_payload,
    file_condition_report,
    funded_bidder,
    intake_decision_payload,
    lien_result_payload,
    lien_search_payload,
    lot_assignment_payload,
    new_auction,
    new_consignment,
    new_consignor,
    new_lot,
    new_yard,
    pending_registration,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COMPLIANCE, INSPECTOR, OPERATOR, SECOND_INSPECTOR, SETTLEMENT
from test_helpers.test_users import make_bidder_headers, make_consignor_headers

HAMMER_CLOCK = "2026-08-10T16:00:00Z"
REPORT_SCORES = {
    "structural_score": 83.5,
    "powertrain_score": 77.5,
    "hydraulics_score": 64.5,
    "tires_score": 58.5,
}


def _draft_consignment_with_one_lot():
    """A yard, a seller and one machine sitting in a DRAFT batch."""
    reset_clock()
    yard = new_yard()
    consignor = new_consignor()
    consignment = new_consignment(consignor)
    lot = new_lot(consignment, consignor, serial_number="CAT-D8T-0001")
    return {
        "yard": yard,
        "consignor": consignor,
        "consignor_headers": make_consignor_headers(consignor["id"]),
        "consignment": consignment,
        "lot": lot,
    }


class TestSevenRolesWalkOneMachine:
    def test_every_role_is_granted_its_own_exclusive_step_of_the_walk(self):
        """One machine travels from an empty database to a confirmed invoice, and each of the
        seven roles signs exactly the steps the matrix reserves for it.

        PRD 2.1: "A `PlatformAdmin` is the back-office administrator who owns reference data —
        yards, load-out bays, consignor records, bidder records — and the logical clock."
        PRD 2.1: "An `AuctionOperator` runs the sale itself: intake decisions, scheduling,
        catalogue assignment, opening, hammering and closing."
        PRD 4: "Seventeen operations mint a new, distinct resource and return `201 Created`:
        creating a yard, a load-out bay, a consignor, a consignment, a lot, a condition report,
        a refurbishment order, an auction, a catalogue lot-assignment, a bidder, a bidder
        registration, a bid, a sale by hammering a lot, an export document packet, a load-out
        slot, a payment, or a consignor settlement. Every other successful operation — all
        reads, all state transitions on an existing resource, all computed previews, and the
        administrative clock capability — returns `200 OK`."

        Design: Corner/RBAC/every_role_can_run_its_own_exclusive_operations_end_to_end
        """
        reset_clock()

        yard = validate_success(
            api_client.create_yard(create_yard_payload(), ADMIN), expected_status=201
        )
        consignor = validate_success(
            api_client.create_consignor(create_consignor_payload(), ADMIN),
            expected_status=201,
        )
        consignor_headers = make_consignor_headers(consignor["id"])

        consignment = validate_success(
            api_client.create_consignment(
                create_consignment_payload(consignor["id"]), consignor_headers
            ),
            expected_status=201,
        )
        lot = validate_success(
            api_client.create_lot(
                create_lot_payload(
                    consignment["id"],
                    serial_number="CAT-D8T-0001",
                    reserve_price_cents=10_000_000,
                ),
                consignor_headers,
            ),
            expected_status=201,
        )
        submitted = validate_success(
            api_client.submit_consignment(consignment["id"], consignor_headers)
        )
        assert submitted["status"] == "SUBMITTED"

        accepted = validate_success(
            api_client.decide_consignment_intake(
                consignment["id"], intake_decision_payload("ACCEPT"), OPERATOR
            )
        )
        assert accepted["status"] == "INTAKE_ACCEPTED"

        searched = validate_success(
            api_client.order_lien_search(lot["id"], lien_search_payload(), COMPLIANCE)
        )
        assert searched["title_status"] == "LIEN_SEARCH_ORDERED"
        cleared = validate_success(
            api_client.record_lien_result(lot["id"], lien_result_payload(False), COMPLIANCE)
        )
        assert cleared["title_status"] == "LIEN_CLEAR"

        report = validate_success(
            api_client.create_condition_report(
                lot["id"],
                create_condition_report_payload(
                    observed_hour_meter_reading=lot["hour_meter_reading"], **REPORT_SCORES
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )
        published = validate_success(
            api_client.publish_condition_report(report["id"], INSPECTOR)
        )
        assert published["status"] == "PUBLISHED"

        auction = validate_success(
            api_client.create_auction(create_auction_payload(yard["id"]), OPERATOR),
            expected_status=201,
        )
        assigned = validate_success(
            api_client.assign_lot_to_auction(
                auction["id"], lot_assignment_payload(lot["id"]), OPERATOR
            ),
            expected_status=201,
        )
        assert assigned["lifecycle_status"] == "ASSIGNED"

        bidder = validate_success(
            api_client.create_bidder(create_bidder_payload(), ADMIN), expected_status=201
        )
        funded = validate_success(
            api_client.create_deposit(
                bidder["id"], create_deposit_payload(2_000_000), SETTLEMENT
            )
        )
        assert funded["deposit_available_cents"] == 2_000_000

        bidder_headers = make_bidder_headers(bidder["id"])
        registration = validate_success(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(bidder["id"], auction["id"], 1_500_000),
                bidder_headers,
            ),
            expected_status=201,
        )
        approved = validate_success(
            api_client.decide_credit(
                registration["id"], credit_decision_payload("APPROVE"), SETTLEMENT
            )
        )
        assert approved["status"] == "APPROVED"

        opened = validate_success(api_client.open_auction(auction["id"], OPERATOR))
        assert opened["status"] == "OPEN"
        assert (
            validate_success(api_client.set_clock(HAMMER_CLOCK, ADMIN))["current_utc"]
            == HAMMER_CLOCK
        )

        bid = validate_success(
            api_client.create_bid(
                create_bid_payload(registration["id"], lot["id"], 12_000_000), bidder_headers
            ),
            expected_status=201,
        )
        assert bid["amount_cents"] == 12_000_000

        sale = validate_success(
            api_client.hammer_lot(lot["id"], OPERATOR), expected_status=201
        )
        assert sale["status"] == "CONFIRMED"
        assert sale["reserve_met"] is True

        rows, meta = validate_paginated(
            api_client.list_invoices(SETTLEMENT, params={"sale_id": sale["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["sale_id"] == sale["id"]


class TestConsignorStaysInsideItsOwnLane:
    def test_the_seller_is_refused_on_operator_admin_and_compliance_operations(self):
        """Three attempts by the same seller identity are turned away on the endpoint alone, and
        none of them leaves a trace.

        PRD 2.1: "Authorisation is decided from the endpoint alone: if the acting role is not one
        of the roles listed for the endpoint in §4, the request fails with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403) regardless of whether the payload is well formed."
        PRD 2.8: "The acting role is listed for the endpoint — otherwise `ERR_ROLE_NOT_PERMITTED`
        (403). Decided from the endpoint alone, so a malformed payload sent by the wrong role
        still returns 403."

        Design: Corner/RBAC/consignor_cannot_run_operator_admin_or_compliance_operations
        """
        stage = _draft_consignment_with_one_lot()
        seller = stage["consignor_headers"]

        validate_error(
            api_client.create_auction(create_auction_payload(stage["yard"]["id"]), seller),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            expected_status=403,
        )
        validate_error(
            api_client.create_bidder(
                create_bidder_payload(legal_name="Self Dealing Ltd"), seller
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            expected_status=403,
        )
        validate_error(
            api_client.order_lien_search(
                stage["lot"]["id"], lien_search_payload(lien_search_reference="LS-9999"), seller
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            expected_status=403,
        )

        _, meta = validate_paginated(api_client.list_auctions(OPERATOR))
        assert meta["total_count"] == 0
        held = validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))
        assert held["title_status"] == "TITLE_PENDING"
        assert held["lien_search_reference"] is None
        assert held["version"] == stage["lot"]["version"]

    def test_a_stranger_submitting_someone_elses_batch_is_told_403_not_404(self):
        """The second seller has the right role and names a batch that really exists, so the
        refusal is about ownership; the owner's identical call then succeeds.

        PRD 2.1: "When an entity-backed role acts on a resource belonging to a different
        `Consignor` or `Bidder`, the request fails with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD 2.8: "For an entity-backed role, the acting `X-User-ID` matches the owning consignor
        or bidder reachable from the target — otherwise `ERR_NOT_RESOURCE_OWNER` (403).
        Deliberately after existence, so probing a stranger's identifier yields 403 rather than
        leaking a 404 about someone else's row."

        Design: Corner/RBAC/a_consignor_cannot_submit_another_consignors_batch
        """
        stage = _draft_consignment_with_one_lot()
        consignment = stage["consignment"]
        stranger = new_consignor(legal_name="Gulf Coast Machinery")
        stranger_headers = make_consignor_headers(stranger["id"])

        refused = api_client.submit_consignment(consignment["id"], stranger_headers)

        validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
        untouched = validate_success(api_client.get_consignment(consignment["id"], OPERATOR))
        assert untouched["status"] == "DRAFT"
        assert untouched["consignor_id"] == stage["consignor"]["id"]
        assert untouched["version"] == consignment["version"]

        submitted = validate_success(
            api_client.submit_consignment(consignment["id"], stage["consignor_headers"])
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["consignor_id"] == stage["consignor"]["id"]
        assert submitted["version"] == consignment["version"] + 1


class TestTheNotFoundCatalogue:
    def test_seventeen_collections_report_seventeen_distinct_missing_row_identifiers(self):
        """The same unknown identifier read against every collection names the collection that
        was searched rather than a single generic 404.

        PRD 2.4: "Path identifiers are resolved first, left to right, and each has a dedicated
        error: `yard_id` yields `ERR_YARD_NOT_FOUND`, `bay_id` yields
        `ERR_LOADOUT_BAY_NOT_FOUND`, `consignor_id` yields `ERR_CONSIGNOR_NOT_FOUND`,
        `consignment_id` yields `ERR_CONSIGNMENT_NOT_FOUND`, `lot_id` yields
        `ERR_LOT_NOT_FOUND`, `report_id` yields `ERR_CONDITION_REPORT_NOT_FOUND`, `order_id`
        yields `ERR_REFURBISHMENT_ORDER_NOT_FOUND`, `auction_id` yields
        `ERR_AUCTION_NOT_FOUND`, `bidder_id` yields `ERR_BIDDER_NOT_FOUND`, `registration_id`
        yields `ERR_REGISTRATION_NOT_FOUND`, `bid_id` yields `ERR_BID_NOT_FOUND`, `sale_id`
        yields `ERR_SALE_NOT_FOUND`, `invoice_id` yields `ERR_INVOICE_NOT_FOUND`, `payment_id`
        yields `ERR_PAYMENT_NOT_FOUND`, `packet_id` yields `ERR_EXPORT_PACKET_NOT_FOUND`,
        `slot_id` yields `ERR_LOADOUT_SLOT_NOT_FOUND`, and `settlement_id` yields
        `ERR_SETTLEMENT_NOT_FOUND`."
        PRD 2.4: "Every one of these errors carries HTTP 404."

        Design: Corner/errors/every_entity_reports_its_own_not_found_id
        """
        reset_clock()
        reads = [
            (api_client.get_yard, ApiErrorId.ERR_YARD_NOT_FOUND),
            (api_client.get_loadout_bay, ApiErrorId.ERR_LOADOUT_BAY_NOT_FOUND),
            (api_client.get_consignor, ApiErrorId.ERR_CONSIGNOR_NOT_FOUND),
            (api_client.get_consignment, ApiErrorId.ERR_CONSIGNMENT_NOT_FOUND),
            (api_client.get_lot, ApiErrorId.ERR_LOT_NOT_FOUND),
            (api_client.get_condition_report, ApiErrorId.ERR_CONDITION_REPORT_NOT_FOUND),
            (
                api_client.get_refurbishment_order,
                ApiErrorId.ERR_REFURBISHMENT_ORDER_NOT_FOUND,
            ),
            (api_client.get_auction, ApiErrorId.ERR_AUCTION_NOT_FOUND),
            (api_client.get_bidder, ApiErrorId.ERR_BIDDER_NOT_FOUND),
            (api_client.get_bidder_registration, ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
            (api_client.get_bid, ApiErrorId.ERR_BID_NOT_FOUND),
            (api_client.get_sale, ApiErrorId.ERR_SALE_NOT_FOUND),
            (api_client.get_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND),
            (api_client.get_payment, ApiErrorId.ERR_PAYMENT_NOT_FOUND),
            (api_client.get_export_packet, ApiErrorId.ERR_EXPORT_PACKET_NOT_FOUND),
            (api_client.get_loadout_slot, ApiErrorId.ERR_LOADOUT_SLOT_NOT_FOUND),
            (api_client.get_consignor_settlement, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
        ]

        observed = [
            validate_error(read(NON_EXISTENT_UUID, ADMIN), expected_error, expected_status=404)[
                "error_id"
            ]
            for read, expected_error in reads
        ]

        assert observed == [expected_error.value for _, expected_error in reads]
        assert len(set(observed)) == 17


class TestReplayedCreates:
    def test_a_second_report_and_a_second_registration_each_conflict_in_their_own_words(self):
        """Replaying either create is a conflict rather than a second row, and the surviving row
        keeps the figures the first call gave it.

        PRD 2.8: "Duplicate-create guards, all 409: the lot has no condition report yet,
        otherwise `ERR_DUPLICATE_CONDITION_REPORT`; the sale has no `POSTED` settlement yet,
        otherwise `ERR_DUPLICATE_SETTLEMENT`; the bidder-and-auction pair has no registration in
        `REQUESTED`, `APPROVED` or `SUSPENDED`, otherwise `ERR_DUPLICATE_REGISTRATION`.
        Replaying a create that already produced a row is a conflict, not a second row."
        PRD 3.5: "A successful create puts the registration in `REQUESTED` at `version` 1, moves
        `deposit_hold_cents` from the bidder's `deposit_available_cents` to its
        `deposit_held_cents`, and allocates a `paddle_number`: one greater than the highest
        paddle already issued at that auction, starting at 101 when the auction has none."

        Design: Corner/errors/replayed_creates_return_their_duplicate_conflict_ids
        """
        stage = _draft_consignment_with_one_lot()
        lot = stage["lot"]
        validate_success(
            api_client.submit_consignment(
                stage["consignment"]["id"], stage["consignor_headers"]
            )
        )
        validate_success(
            api_client.decide_consignment_intake(
                stage["consignment"]["id"], intake_decision_payload("ACCEPT"), OPERATOR
            )
        )
        first_report = file_condition_report(lot, **REPORT_SCORES)
        assert first_report["status"] == "DRAFT"
        assert first_report["structural_score"] == 83.5

        auction = new_auction(stage["yard"])
        bidder = funded_bidder(2_000_000)
        first_registration = pending_registration(bidder, auction, 1_500_000)
        assert first_registration["status"] == "REQUESTED"
        assert first_registration["paddle_number"] == 101

        replayed_report = api_client.create_condition_report(
            lot["id"],
            create_condition_report_payload(
                observed_hour_meter_reading=lot["hour_meter_reading"]
            ),
            SECOND_INSPECTOR,
        )
        validate_error(
            replayed_report, ApiErrorId.ERR_DUPLICATE_CONDITION_REPORT, expected_status=409
        )

        replayed_registration = api_client.create_bidder_registration(
            create_bidder_registration_payload(bidder["id"], auction["id"], 200_000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(
            replayed_registration, ApiErrorId.ERR_DUPLICATE_REGISTRATION, expected_status=409
        )

        report_rows, report_meta = validate_paginated(
            api_client.list_lot_condition_reports(lot["id"], INSPECTOR)
        )
        assert report_meta["total_count"] == 1
        assert report_rows[0]["id"] == first_report["id"]
        assert report_rows[0]["structural_score"] == 83.5

        registration_rows, registration_meta = validate_paginated(
            api_client.list_bidder_registrations(
                SETTLEMENT, params={"bidder_id": bidder["id"], "auction_id": auction["id"]}
            )
        )
        assert registration_meta["total_count"] == 1
        assert registration_rows[0]["deposit_hold_cents"] == 1_500_000
        assert registration_rows[0]["paddle_number"] == 101

        settled_bidder = validate_success(api_client.get_bidder(bidder["id"], SETTLEMENT))
        assert settled_bidder["deposit_held_cents"] == 1_500_000
        assert settled_bidder["deposit_available_cents"] == 500_000
        assert settled_bidder["deposit_total_cents"] == 2_000_000


class TestLadderOrderAroundMissingRows:
    def test_a_malformed_enum_answers_before_the_missing_row_the_path_answers_before_the_body(self):
        """A bad path identifier wins over a bad body foreign key, and a bad enum wins over both,
        so the very same unknown consignor is reported as a 400 in one call and a 404 in the
        next.

        PRD 2.8: "The request body and query parameters satisfy the declared types, enum domains,
        string lengths, numeric ranges, ISO 8601 datetime formats and required-field lists —
        otherwise `ERR_INVALID_REQUEST` (400). This covers pagination bounds, `slot_end` strictly
        after `slot_start`, `window_end` strictly after `window_start`, condition scores with
        more than one decimal place, and unknown enum members."
        PRD 2.4: "Only after every path identifier resolves does the server resolve the foreign
        keys carried in the request body, and it resolves them in the order the fields are
        declared for that entity."
        PRD 2.4: "Consequently a request that names both a non-existent path resource and a
        non-existent body foreign key always reports the path resource's 404, and a bidder
        registration naming a bad `bidder_id` and a bad `auction_id` reports
        `ERR_BIDDER_NOT_FOUND` because `bidder_id` is declared first."

        Design: Corner/validations/request_shape_outranks_path_existence_which_outranks_body_foreign_keys
        """
        reset_clock()
        ghost_consignor = NON_EXISTENT_UUID
        ghost_headers = make_consignor_headers(ghost_consignor)

        validate_error(
            api_client.assign_lot_to_auction(
                NON_EXISTENT_UUID, lot_assignment_payload(NON_EXISTENT_UUID), OPERATOR
            ),
            ApiErrorId.ERR_AUCTION_NOT_FOUND,
            expected_status=404,
        )

        validate_error(
            api_client.create_consignment(
                create_consignment_payload(ghost_consignor, agreement_type="NOT_A_TYPE"),
                ghost_headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        validate_error(
            api_client.create_consignment(
                create_consignment_payload(ghost_consignor), ghost_headers
            ),
            ApiErrorId.ERR_CONSIGNOR_NOT_FOUND,
            expected_status=404,
        )

        validate_error(
            api_client.list_consignor_consignments(ghost_consignor, OPERATOR),
            ApiErrorId.ERR_CONSIGNOR_NOT_FOUND,
            expected_status=404,
        )
        _, meta = validate_paginated(api_client.list_consignors(ADMIN))
        assert meta["total_count"] == 0
