"""Consignment agreements, the machines inside them, and the intake-side refusals."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_consignment_payload,
    create_consignor_payload,
    create_lot_payload,
    make_consignor_headers,
    new_consignment,
    new_consignor,
    new_lot,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_lot_payload,
)
from test_helpers.fixtures import ADMIN, OPERATOR
from test_helpers.test_users import TEST_USERS


class TestInitialState:
    def test_a_new_batch_is_draft_and_its_machine_holds_both_initial_axes(self):
        """The consignment opens in DRAFT owing its whole advance, and the lot opens on
        both of its declared initial states at once.

        PRD 3.1: "A new consignment is created in `DRAFT` with `advance_outstanding_cents`
        equal to `advance_paid_cents`, `correction_note` null, and its `unsold_lot_count`
        and `reoffer_lot_count` both zero; the consignor's `open_consignment_count` is
        recomputed on the spot."
        PRD 3.1: "Every new lot starts with `lifecycle_status` `INTAKE`, `title_status`
        `TITLE_PENDING`, `high_bid_cents` of 0, and `auction_id`, `lien_search_reference`,
        `lienholder_name` and `withdrawal_reason` all null."

        Design: Corner/state_machines/consignment_and_lot_start_in_their_declared_initial_states
        """
        reset_clock()
        consignor = new_consignor()
        consignor_headers = make_consignor_headers(consignor["id"])

        consignment = validate_success(
            api_client.create_consignment(
                create_consignment_payload(consignor["id"], advance_paid_cents=2_000_000),
                consignor_headers,
            ),
            expected_status=201,
        )
        lot = validate_success(
            api_client.create_lot(
                create_lot_payload(consignment["id"], serial_number="CAT-D8T-0001"),
                consignor_headers,
            ),
            expected_status=201,
        )

        assert consignment["status"] == "DRAFT"
        assert consignment["advance_outstanding_cents"] == 2_000_000
        assert consignment["correction_note"] is None
        assert consignment["unsold_lot_count"] == 0
        assert consignment["reoffer_lot_count"] == 0

        assert lot["lifecycle_status"] == "INTAKE"
        assert lot["title_status"] == "TITLE_PENDING"
        assert lot["high_bid_cents"] == 0
        assert lot["auction_id"] is None
        assert lot["lien_search_reference"] is None
        assert lot["lienholder_name"] is None
        assert lot["withdrawal_reason"] is None

        stored_consignor = validate_success(
            api_client.get_consignor(consignor["id"], ADMIN)
        )
        assert stored_consignor["open_consignment_count"] == 1

    def test_reading_a_lot_back_echoes_every_declared_input(self):
        """The stored lot returns the serial, weight, hours, title flag and reserve it was
        created with, alongside its two initial states.

        PRD 3.1: "A lot names its `consignment_id` and describes the unit: `make` and
        `model`, each 1 to 60 characters; `model_year` between 1960 and 2030;
        `serial_number`, the manufacturer serial or PIN, 4 to 40 characters and unique
        across every lot in the system".

        Design: Corner/entities/lot_retrieval_returns_the_stored_lot
        """
        reset_clock()
        consignor = new_consignor()
        consignment = new_consignment(consignor)
        created = new_lot(
            consignment,
            consignor,
            serial_number="CAT-D8T-0001",
            hour_meter_reading=6_200,
            weight_kg=36_000,
            title_required=True,
            reserve_price_cents=10_000_000,
        )

        lot = validate_success(
            api_client.get_lot(created["id"], TEST_USERS["bidder_headers"])
        )

        assert lot["id"] == created["id"]
        assert lot["serial_number"] == "CAT-D8T-0001"
        assert lot["weight_kg"] == 36_000
        assert lot["hour_meter_reading"] == 6_200
        assert lot["title_required"] is True
        assert lot["reserve_price_cents"] == 10_000_000
        assert lot["lifecycle_status"] == "INTAKE"
        assert lot["title_status"] == "TITLE_PENDING"
        assert lot["auction_id"] is None
        assert lot["high_bid_cents"] == 0


class TestRequestShapeAndReferences:
    def test_a_consignment_without_its_agreement_type_is_a_shape_error(self):
        """Dropping a required field is a 400 and writes nothing at all.

        PRD 2.8: "The request body and query parameters satisfy the declared types, enum
        domains, string lengths, numeric ranges, ISO 8601 datetime formats and
        required-field lists — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/consignment_without_agreement_type_returns_invalid_request
        """
        reset_clock()
        consignor = new_consignor()
        consignor_headers = make_consignor_headers(consignor["id"])

        response = api_client.create_consignment(
            {
                "consignor_id": consignor["id"],
                "commission_schedule_code": "RESERVE_STD",
                "refurb_authorization_cap_cents": 500_000,
            },
            consignor_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        rows, meta = validate_paginated(
            api_client.list_consignor_consignments(consignor["id"], ADMIN)
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_an_out_of_range_year_and_an_unknown_enum_member_are_both_refused(self):
        """A `model_year` under the declared floor and a `seller_type` outside the declared
        domain each return the same shape error.

        PRD 3.1: "`model_year` between 1960 and 2030".
        PRD 3.1: "A **consignor** is registered by a `PlatformAdmin` with a `legal_name` of
        2 to 120 characters, a two-uppercase-letter `country_code`, and a `seller_type`
        drawn from `DEALER`, `FLEET_OWNER`, `BANK_REPO` and `GOVERNMENT`."

        Design: Corner/entities/lot_model_year_below_range_and_bad_enum_are_rejected
        """
        reset_clock()
        consignor = new_consignor()
        consignor_headers = make_consignor_headers(consignor["id"])
        consignment = new_consignment(consignor)

        year_response = api_client.create_lot(
            create_lot_payload(
                consignment["id"], model_year=1959, serial_number="CAT-D8T-9001"
            ),
            consignor_headers,
        )
        enum_response = api_client.create_consignor(
            create_consignor_payload(
                legal_name="Gulf Coast Leasing", seller_type="LESSOR"
            ),
            ADMIN,
        )

        validate_error(year_response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        validate_error(enum_response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        _, lot_meta = validate_paginated(api_client.list_lots(OPERATOR))
        assert lot_meta["total_count"] == 0
        _, consignor_meta = validate_paginated(api_client.list_consignors(ADMIN))
        assert consignor_meta["total_count"] == 1

    def test_unknown_body_foreign_keys_report_the_missing_collection(self):
        """An unresolvable `consignor_id` and an unresolvable `consignment_id` each report
        their own 404 rather than a generic failure.

        PRD 2.4: "Only after every path identifier resolves does the server resolve the
        foreign keys carried in the request body, and it resolves them in the order the
        fields are declared for that entity."
        PRD 2.4: "`consignor_id` yields `ERR_CONSIGNOR_NOT_FOUND`, `consignment_id` yields
        `ERR_CONSIGNMENT_NOT_FOUND`".

        Design: Corner/entities/unknown_foreign_keys_in_request_bodies_are_rejected_as_not_found
        """
        reset_clock()
        consignor = new_consignor()
        consignor_headers = make_consignor_headers(consignor["id"])

        consignment_response = api_client.create_consignment(
            create_consignment_payload("00000000-0000-4000-8000-0000000000aa"),
            consignor_headers,
        )
        lot_response = api_client.create_lot(
            create_lot_payload(
                "00000000-0000-4000-8000-0000000000bb",
                make="Komatsu",
                model="PC490",
                model_year=2020,
                serial_number="KOM-PC490-0001",
                hour_meter_reading=4_100,
                weight_kg=48_000,
            ),
            consignor_headers,
        )

        validate_error(
            consignment_response, ApiErrorId.ERR_CONSIGNOR_NOT_FOUND, expected_status=404
        )
        validate_error(
            lot_response, ApiErrorId.ERR_CONSIGNMENT_NOT_FOUND, expected_status=404
        )

    def test_lot_pages_report_the_unpaginated_total_and_the_has_more_flag(self):
        """Two pages of a three-lot batch report the same total and flip `has_more`.

        PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` counts every record matching the
        filters before pagination is applied."
        PRD 2.3: "Unless a specific endpoint states otherwise, list results are ordered by
        `created_at` ascending."

        Design: Corner/entities/lot_listing_pagination_reports_total_count_and_has_more
        """
        reset_clock()
        consignor = new_consignor()
        consignment = new_consignment(consignor)
        lots = [
            new_lot(consignment, consignor, serial_number=f"CAT-D8T-100{index}")
            for index in range(3)
        ]

        first_rows, first_meta = validate_paginated(
            api_client.list_lots(
                OPERATOR,
                params={"consignment_id": consignment["id"], "limit": 2, "offset": 0},
            )
        )
        second_rows, second_meta = validate_paginated(
            api_client.list_lots(
                OPERATOR,
                params={"consignment_id": consignment["id"], "limit": 2, "offset": 2},
            )
        )

        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        returned = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
        assert returned == [lot["id"] for lot in lots]
        assert len(set(returned)) == 3


class TestIntakeGuards:
    def test_a_withdrawn_lot_cannot_be_withdrawn_a_second_time(self):
        """The lifecycle axis is locked down once the machine is withdrawn, and the stored
        reason is not overwritten by the refused replay.

        PRD 3.1: "Withdrawal moves the lot to `WITHDRAWN`, which is terminal on the
        lifecycle axis, marks every `ACTIVE` bid on the lot `LOSING`".
        PRD 2.8: "The target is in a state from which the requested transition is declared
        — otherwise `ERR_INVALID_STATE` (409). This is the generic guard; every
        terminal-state lockdown and every replayed one-shot action lands here."

        Design: Corner/state_machines/withdrawn_lot_cannot_be_withdrawn_again
        """
        reset_clock()
        consignor = new_consignor()
        consignment = new_consignment(consignor)
        lot = new_lot(consignment, consignor)

        withdrawn = validate_success(
            api_client.withdraw_lot(
                lot["id"], withdraw_lot_payload(withdrawal_reason="seller retracted"), OPERATOR
            )
        )
        assert withdrawn["lifecycle_status"] == "WITHDRAWN"

        response = api_client.withdraw_lot(
            lot["id"],
            withdraw_lot_payload(withdrawal_reason="duplicate consignment"),
            OPERATOR,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        stored = validate_success(api_client.get_lot(lot["id"], OPERATOR))
        assert stored["lifecycle_status"] == "WITHDRAWN"
        assert stored["withdrawal_reason"] == "seller retracted"

    def test_a_serial_already_consigned_elsewhere_is_a_conflict(self):
        """Serial uniqueness spans the whole system, so a second seller cannot re-declare
        the same machine.

        PRD 3.1: "`serial_number`, the manufacturer serial or PIN, 4 to 40 characters and
        unique across every lot in the system, so that the same machine cannot be consigned
        twice — a collision is refused with `ERR_DUPLICATE_SERIAL_NUMBER`".

        Design: Corner/validations/duplicate_serial_number_is_rejected_across_consignments
        """
        reset_clock()
        first_consignor = new_consignor()
        first_consignment = new_consignment(first_consignor)
        new_lot(first_consignment, first_consignor, serial_number="CAT-D8T-0001")

        second_consignor = new_consignor(legal_name="Rio Grande Iron", country_code="US")
        second_consignment = new_consignment(second_consignor)

        response = api_client.create_lot(
            create_lot_payload(
                second_consignment["id"],
                serial_number="CAT-D8T-0001",
                hour_meter_reading=6_400,
            ),
            make_consignor_headers(second_consignor["id"]),
        )

        validate_error(
            response, ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER, expected_status=409
        )

        _, meta = validate_paginated(
            api_client.list_lots(OPERATOR, params={"consignment_id": second_consignment["id"]})
        )
        assert meta["total_count"] == 0

    def test_only_the_unreserved_batch_needs_the_signed_disclosure(self):
        """The same unsigned seller submits its reserve batch freely, is refused on the
        unreserved one, and is accepted once the disclosure is signed.

        PRD 3.1: "Submission requires that at least one lot exists under the consignment,
        and — when `agreement_type` is `UNRESERVED` — that the consignor's
        `unreserved_policy_ack` is true, without which the request is refused with
        `ERR_UNRESERVED_POLICY_NOT_ACK`."
        PRD 3.1: "The record also carries `unreserved_policy_ack`, a boolean that defaults
        to false and records whether the seller has signed the unreserved-sale disclosure."

        Design: Corner/validations/unreserved_consignment_submit_requires_the_policy_acknowledgement
        """
        reset_clock()
        consignor = new_consignor()
        assert consignor["unreserved_policy_ack"] is False
        consignor_headers = make_consignor_headers(consignor["id"])

        reserve_batch = new_consignment(consignor)
        new_lot(reserve_batch, consignor, serial_number="CAT-D8T-2001")
        unreserved_batch = new_consignment(
            consignor,
            agreement_type="UNRESERVED",
            commission_schedule_code="UNRESERVED_STD",
        )
        bare_lot = create_lot_payload(unreserved_batch["id"], serial_number="CAT-D8T-2002")
        bare_lot.pop("reserve_price_cents")
        validate_success(
            api_client.create_lot(bare_lot, consignor_headers), expected_status=201
        )

        submitted = validate_success(
            api_client.submit_consignment(reserve_batch["id"], consignor_headers)
        )
        assert submitted["status"] == "SUBMITTED"

        refused = api_client.submit_consignment(unreserved_batch["id"], consignor_headers)
        validate_error(
            refused, ApiErrorId.ERR_UNRESERVED_POLICY_NOT_ACK, expected_status=422
        )
        held = validate_success(
            api_client.get_consignment(unreserved_batch["id"], OPERATOR)
        )
        assert held["status"] == "DRAFT"

        acknowledged = validate_success(
            api_client.acknowledge_unreserved_policy(
                consignor["id"], consignor_headers, {"unreserved_policy_ack": True}
            )
        )
        assert acknowledged["unreserved_policy_ack"] is True

        accepted = validate_success(
            api_client.submit_consignment(unreserved_batch["id"], consignor_headers)
        )
        assert accepted["status"] == "SUBMITTED"
