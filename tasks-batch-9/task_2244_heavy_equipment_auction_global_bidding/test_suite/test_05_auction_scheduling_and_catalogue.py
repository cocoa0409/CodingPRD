"""Scheduling events at a yard and assembling their catalogues."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_auction,
    catalog_ready_batch,
    catalog_ready_lot,
    clear_lot_title,
    create_auction_payload,
    create_lot_payload,
    file_condition_report,
    intake_decision_payload,
    lot_assignment_payload,
    make_consignor_headers,
    new_auction,
    new_consignment,
    new_consignor,
    new_lot,
    new_yard,
    publish_condition_report,
    reschedule_auction_payload,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import INSPECTOR, OPERATOR


def _cataloged_pair_with_and_without_reserve():
    """One CATALOGED batch holding a reserved machine and a bare one."""
    reset_clock()
    yard = new_yard()
    consignor = new_consignor()
    consignor_headers = make_consignor_headers(consignor["id"])
    consignment = new_consignment(consignor)

    reserved_lot = new_lot(
        consignment,
        consignor,
        serial_number="CAT-D8T-0001",
        reserve_price_cents=10_000_000,
    )
    bare_payload = create_lot_payload(
        consignment["id"],
        make="Bobcat",
        model="S76",
        model_year=2021,
        serial_number="BOB-S76-0002",
        hour_meter_reading=900,
        weight_kg=6_000,
    )
    bare_payload.pop("reserve_price_cents")
    bare_lot = validate_success(
        api_client.create_lot(bare_payload, consignor_headers), expected_status=201
    )
    assert bare_lot["reserve_price_cents"] is None

    validate_success(api_client.submit_consignment(consignment["id"], consignor_headers))
    validate_success(
        api_client.decide_consignment_intake(
            consignment["id"], intake_decision_payload("ACCEPT"), OPERATOR
        )
    )
    for index, lot in enumerate((reserved_lot, bare_lot), start=1):
        clear_lot_title(lot, reference=f"LS-{index:04d}")
        publish_condition_report(file_condition_report(lot))

    return {
        "yard": yard,
        "consignment": validate_success(
            api_client.get_consignment(consignment["id"], OPERATOR)
        ),
        "reserved_lot": reserved_lot,
        "bare_lot": bare_lot,
    }


class TestRescheduling:
    def test_moving_the_window_restamps_the_derived_loadout_deadline(self):
        """The deadline is recomputed from the new `window_end` rather than kept as stored
        input, and the event stays scheduled with an empty catalogue.

        PRD 3.4: "Creation also computes `loadout_deadline_at`, the instant by which all
        load-out must be finished: it is `window_end` advanced by the yard's
        `loadout_deadline_days` days."
        PRD 3.4: "Rescheduling recomputes `loadout_deadline_at` from the new `window_end` and
        re-runs the yard overlap check, excluding the auction being moved from the set it is
        compared against — otherwise every event would conflict with its own former self."
        PRD 3.4: "The auction is created in `SCHEDULED` with `assigned_lot_count`,
        `sold_lot_count`, `unsold_lot_count` and `gross_hammer_cents` all at zero."

        Design: Corner/endpoints/reschedule_restamps_the_loadout_deadline_from_the_new_window_end
        """
        reset_clock()
        yard = new_yard(loadout_deadline_days=10)
        auction = new_auction(
            yard,
            window_start="2026-08-10T14:00:00Z",
            window_end="2026-08-10T22:00:00Z",
        )

        assert_auction(auction)
        assert auction["status"] == "SCHEDULED"
        assert auction["loadout_deadline_at"].startswith("2026-08-20T22:00:00")
        assert auction["version"] == 1
        assert auction["assigned_lot_count"] == 0

        moved = validate_success(
            api_client.reschedule_auction(
                auction["id"],
                reschedule_auction_payload("2026-09-01T14:00:00Z", "2026-09-01T22:00:00Z"),
                OPERATOR,
            )
        )

        assert moved["window_start"].startswith("2026-09-01T14:00:00")
        assert moved["window_end"].startswith("2026-09-01T22:00:00")
        assert moved["loadout_deadline_at"].startswith("2026-09-11T22:00:00")
        assert moved["version"] == 2
        assert moved["status"] == "SCHEDULED"
        assert moved["assigned_lot_count"] == 0


class TestRingContention:
    def test_the_buffered_interval_is_closed_at_both_ends(self):
        """A live event beginning exactly two hours after the incumbent closes conflicts, and
        the same event one second later does not.

        PRD 3.4: "For a `LIVE_ONSITE` auction, take its bidding window and extend it by the
        yard's `teardown_buffer_minutes`; that extended interval must not overlap the window
        of any other `LIVE_ONSITE` auction at the same yard whose `status` is anything other
        than `RECONCILED`. Because the comparison uses closed intervals, a candidate that
        begins at exactly the existing event's `window_end` plus the buffer conflicts, while
        one that begins a single second later does not."

        Design: Difficulty/resource_temporal_overlap/live_onsite_window_conflict_includes_teardown_buffer_closed_interval
        """
        reset_clock()
        yard = new_yard(teardown_buffer_minutes=120, loadout_deadline_days=10)
        incumbent = new_auction(
            yard,
            kind="LIVE_ONSITE",
            window_start="2026-08-10T14:00:00Z",
            window_end="2026-08-10T22:00:00Z",
        )

        touching = api_client.create_auction(
            create_auction_payload(
                yard["id"],
                kind="LIVE_ONSITE",
                window_start="2026-08-11T00:00:00Z",
                window_end="2026-08-11T08:00:00Z",
            ),
            OPERATOR,
        )
        validate_error(
            touching, ApiErrorId.ERR_AUCTION_WINDOW_CONFLICT, expected_status=409
        )

        clear = validate_success(
            api_client.create_auction(
                create_auction_payload(
                    yard["id"],
                    kind="LIVE_ONSITE",
                    window_start="2026-08-11T00:00:01Z",
                    window_end="2026-08-11T08:00:00Z",
                ),
                OPERATOR,
            ),
            expected_status=201,
        )
        assert clear["status"] == "SCHEDULED"

        rows, meta = validate_paginated(api_client.list_yard_auctions(yard["id"], OPERATOR))
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {incumbent["id"], clear["id"]}

    def test_timed_online_events_ignore_the_ring_entirely(self):
        """An online event whose window sits inside the live event's window is accepted, and
        the live event keeps the deadline its own window implies.

        PRD 3.4: "`TIMED_ONLINE` events are exempt from the check entirely — any number of
        them may hold overlapping bidding windows at one yard, and they never block a live
        event."
        PRD 3.4: "`kind` is either `LIVE_ONSITE`, which occupies the yard's physical ring, or
        `TIMED_ONLINE`, which does not."

        Design: Difficulty/resource_temporal_overlap/live_onsite_window_conflict_includes_teardown_buffer_closed_interval
        """
        reset_clock()
        yard = new_yard(teardown_buffer_minutes=120, loadout_deadline_days=10)
        live = new_auction(
            yard,
            kind="LIVE_ONSITE",
            window_start="2026-08-10T14:00:00Z",
            window_end="2026-08-10T22:00:00Z",
        )

        online = validate_success(
            api_client.create_auction(
                create_auction_payload(
                    yard["id"],
                    kind="TIMED_ONLINE",
                    window_start="2026-08-10T16:00:00Z",
                    window_end="2026-08-10T20:00:00Z",
                ),
                OPERATOR,
            ),
            expected_status=201,
        )

        assert online["status"] == "SCHEDULED"
        assert online["kind"] == "TIMED_ONLINE"
        assert live["loadout_deadline_at"].startswith("2026-08-20T22:00:00")

        _, meta = validate_paginated(api_client.list_yard_auctions(yard["id"], OPERATOR))
        assert meta["total_count"] == 2


class TestCatalogueAssignmentGates:
    def test_one_unpublished_sibling_holds_the_whole_batch_out_of_the_catalogue(self):
        """The machine itself is ready, yet its assignment is refused because the parent batch
        is still waiting on its other lot.

        PRD 3.4: "The lot's consignment must be `CATALOGED`, failing which the refusal is
        `ERR_CONSIGNMENT_NOT_CATALOGED`."
        PRD 3.2: "Because catalogue assignment requires the parent to be `CATALOGED`, one
        unpublished sibling blocks the assignment of an already-published lot; that refusal
        surfaces as `ERR_CONSIGNMENT_NOT_CATALOGED`."

        Design: Difficulty/cross_entity_state_dependency/lot_assignment_requires_consignment_cataloged
        """
        stage = catalog_ready_batch(
            [
                {"serial_number": "CAT-D8T-0001", "reserve_price_cents": 10_000_000},
                {
                    "make": "Bobcat",
                    "model": "S76",
                    "model_year": 2021,
                    "serial_number": "BOB-S76-0002",
                    "hour_meter_reading": 900,
                    "weight_kg": 6_000,
                    "reserve_price_cents": 1_000_000,
                },
            ],
            publish_count=1,
        )
        published_lot, sibling = stage["lots"]
        auction = new_auction(stage["yard"])

        response = api_client.assign_lot_to_auction(
            auction["id"], lot_assignment_payload(published_lot["id"]), OPERATOR
        )

        validate_error(
            response, ApiErrorId.ERR_CONSIGNMENT_NOT_CATALOGED, expected_status=409
        )

        assert published_lot["lifecycle_status"] == "CATALOG_READY"
        assert sibling["lifecycle_status"] == "INSPECTED"
        assert (
            validate_success(api_client.get_consignment(stage["consignment"]["id"], OPERATOR))[
                "status"
            ]
            == "INTAKE_ACCEPTED"
        )
        assert (
            validate_success(api_client.get_auction(auction["id"], OPERATOR))[
                "assigned_lot_count"
            ]
            == 0
        )

    def test_publishing_the_sibling_bubbles_the_batch_up_and_admits_the_lot(self):
        """Once the sibling's report is published the parent catalogues itself and the
        identical assignment is accepted.

        PRD 3.2: "the parent consignment moves `INTAKE_ACCEPTED → CATALOGED` on its own, with
        its `version` incremented by 1."
        PRD 3.4: "A successful assignment stamps the lot's `auction_id`, moves the lot
        `CATALOG_READY → ASSIGNED`, recomputes the auction's `assigned_lot_count`, and
        increments both the lot's `version` and the auction's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/lot_assignment_requires_consignment_cataloged
        """
        stage = catalog_ready_batch(
            [
                {"serial_number": "CAT-D8T-0001", "reserve_price_cents": 10_000_000},
                {
                    "make": "Bobcat",
                    "model": "S76",
                    "model_year": 2021,
                    "serial_number": "BOB-S76-0002",
                    "hour_meter_reading": 900,
                    "weight_kg": 6_000,
                    "reserve_price_cents": 1_000_000,
                },
            ],
            publish_count=1,
        )
        published_lot, sibling = stage["lots"]
        auction = new_auction(stage["yard"])
        validate_error(
            api_client.assign_lot_to_auction(
                auction["id"], lot_assignment_payload(published_lot["id"]), OPERATOR
            ),
            ApiErrorId.ERR_CONSIGNMENT_NOT_CATALOGED,
            expected_status=409,
        )

        validate_success(
            api_client.publish_condition_report(stage["reports"][1]["id"], INSPECTOR)
        )
        assert (
            validate_success(api_client.get_consignment(stage["consignment"]["id"], OPERATOR))[
                "status"
            ]
            == "CATALOGED"
        )
        assert (
            validate_success(api_client.get_lot(sibling["id"], OPERATOR))["lifecycle_status"]
            == "CATALOG_READY"
        )

        validate_success(
            api_client.assign_lot_to_auction(
                auction["id"], lot_assignment_payload(published_lot["id"]), OPERATOR
            ),
            expected_status=201,
        )

        assigned = validate_success(api_client.get_lot(published_lot["id"], OPERATOR))
        assert assigned["lifecycle_status"] == "ASSIGNED"
        assert assigned["auction_id"] == auction["id"]
        assert (
            validate_success(api_client.get_auction(auction["id"], OPERATOR))[
                "assigned_lot_count"
            ]
            == 1
        )

    def test_an_unreserved_event_refuses_the_reserved_lot_and_takes_its_bare_sibling(self):
        """Two machines from one batch part ways on a field of the auction, not of the lot.

        PRD 3.4: "And a reserve price, whether already on the lot or supplied with the
        assignment, is only permitted when the auction's `reserve_policy` is
        `RESERVE_ALLOWED` **and** the consignment's `agreement_type` is `RESERVE`; either an
        unreserved event or an unreserved seller agreement forbids it, and the refusal is
        `ERR_RESERVE_NOT_ALLOWED`."
        PRD 3.4: "`reserve_policy` is either `UNRESERVED`, which forbids any lot in the
        catalogue from carrying a reserve price at all, or `RESERVE_ALLOWED`."

        Design: Corner/validations/reserve_price_on_an_unreserved_event_is_refused_while_a_bare_lot_assigns
        """
        stage = _cataloged_pair_with_and_without_reserve()
        assert stage["consignment"]["status"] == "CATALOGED"
        auction = new_auction(stage["yard"], reserve_policy="UNRESERVED")

        refused = api_client.assign_lot_to_auction(
            auction["id"], lot_assignment_payload(stage["reserved_lot"]["id"]), OPERATOR
        )
        validate_error(refused, ApiErrorId.ERR_RESERVE_NOT_ALLOWED, expected_status=422)

        validate_success(
            api_client.assign_lot_to_auction(
                auction["id"], lot_assignment_payload(stage["bare_lot"]["id"]), OPERATOR
            ),
            expected_status=201,
        )

        held = validate_success(
            api_client.get_lot(stage["reserved_lot"]["id"], OPERATOR)
        )
        assert held["lifecycle_status"] == "CATALOG_READY"
        assert held["auction_id"] is None
        catalogued = validate_success(api_client.get_lot(stage["bare_lot"]["id"], OPERATOR))
        assert catalogued["lifecycle_status"] == "ASSIGNED"
        assert catalogued["auction_id"] == auction["id"]
        assert (
            validate_success(api_client.get_auction(auction["id"], OPERATOR))[
                "assigned_lot_count"
            ]
            == 1
        )

    def test_a_machine_already_in_one_catalogue_cannot_join_a_second(self):
        """Every other condition holds on the second event, so the stamped `auction_id` alone
        produces the mismatch error and neither catalogue is disturbed.

        PRD 3.4: "The lot must not already be assigned to another auction and its consignment
        must have been accepted at intake, failing which the refusal is
        `ERR_LOT_AUCTION_MISMATCH`."
        PRD 3.4: "The lot's `auction_id` is never cleared afterwards."

        Design: Corner/errors/an_already_assigned_lot_cannot_join_a_second_catalogue
        """
        stage = catalog_ready_lot(lot_overrides={"serial_number": "CAT-D8T-0001"})
        lot = stage["lot"]
        first = new_auction(stage["yard"], kind="LIVE_ONSITE")
        validate_success(
            api_client.assign_lot_to_auction(
                first["id"], lot_assignment_payload(lot["id"]), OPERATOR
            ),
            expected_status=201,
        )
        second = new_auction(
            stage["yard"],
            kind="TIMED_ONLINE",
            window_start="2026-08-12T14:00:00Z",
            window_end="2026-08-12T22:00:00Z",
        )

        response = api_client.assign_lot_to_auction(
            second["id"], lot_assignment_payload(lot["id"]), OPERATOR
        )

        validate_error(response, ApiErrorId.ERR_LOT_AUCTION_MISMATCH, expected_status=409)

        stored = validate_success(api_client.get_lot(lot["id"], OPERATOR))
        assert stored["auction_id"] == first["id"]
        assert stored["lifecycle_status"] == "ASSIGNED"
        assert (
            validate_success(api_client.get_auction(second["id"], OPERATOR))[
                "assigned_lot_count"
            ]
            == 0
        )
        assert (
            validate_success(api_client.get_auction(first["id"], OPERATOR))[
                "assigned_lot_count"
            ]
            == 1
        )
