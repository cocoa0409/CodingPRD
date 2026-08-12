"""Lot intake, unit registration, pipeline gates, and unit listing (PRD §3.4)."""
from test_helpers import (
    assert_lot_tally_invariant,
    assert_unit,
    create_fixture_payload,
    create_lot_payload,
    create_lot_with_units,
    create_test_program_payload,
    create_unit_payload,
    record_pass,
    setup_in_test_lot,
    setup_released_program_with_fixture,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ENG1, OPS


def _create_empty_lot(api, ctx: dict, quantity: int = 1) -> dict:
    """Create a RECEIVED lot with no units registered yet."""
    return validate_success(
        api.create_lot(
            create_lot_payload(
                ctx["customer"]["id"], ctx["program"]["id"],
                part_number=ctx["program"]["part_number"], quantity=quantity,
            ),
            ctx["rep_headers"],
        ),
        201,
    )


class TestLotCreation:
    def test_program_not_released_lot_create_rejected(self, api):
        """PRD §3.4: "The referenced program must be `RELEASED`, otherwise
        `ERR_PROGRAM_NOT_RELEASED`, and the lot's `part_number` must equal the
        program's part number, otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/validations/program_not_released_lot_create_rejected
        """
        ctx = setup_released_program_with_fixture(part_number="PN-217")
        # Build a second program that is VALIDATED but never released.
        program = validate_success(
            api.create_test_program(
                create_test_program_payload(
                    ctx["customer"]["id"], part_number="PN-217B",
                    bin_map={"1": "PASS"}, max_retests_per_unit=1,
                ),
                ENG1,
            ),
            201,
        )
        fixture = validate_success(
            api.create_fixture(
                create_fixture_payload(program["id"], serial_number="FX-VL"), ENG1
            ),
            201,
        )
        validate_success(api.commission_fixture(fixture["id"], ENG1), 200)
        program = validate_success(api.validate_program(program["id"], ENG1), 200)
        assert program["status"] == "VALIDATED"

        res = api.create_lot(
            create_lot_payload(
                ctx["customer"]["id"], program["id"], part_number="PN-217B"
            ),
            ctx["rep_headers"],
        )
        validate_error(res, "ERR_PROGRAM_NOT_RELEASED", expected_status=422)


class TestUnitRegistration:
    def test_unit_initial_state_untested(self, api):
        """PRD §3.4: "A new unit starts `UNTESTED` with `retest_count` zero and
        `current_bin` null, and the lot's `units_registered` is recomputed."

        Design: Corner/state_machines/unit_initial_state_untested
        """
        ctx = setup_released_program_with_fixture(part_number="PN-204")
        lot = _create_empty_lot(api, ctx, quantity=1)
        unit = validate_success(
            api.create_unit(create_unit_payload(lot["id"], serial_number="N-1"), OPS),
            201,
        )
        assert_unit(unit)
        assert unit["test_status"] == "UNTESTED"
        assert unit["current_bin"] is None
        assert unit["retest_count"] == 0

    def test_unit_duplicate_serial_rejected(self, api):
        """PRD §3.4: "Each registration carries the `lot_id` and a `serial_number`
        that must be unique within the lot — a duplicate is rejected with
        `ERR_DUPLICATE_SERIAL`."

        Design: Corner/entities/unit_duplicate_serial_rejected
        """
        ctx = setup_released_program_with_fixture(
            part_number="PN-201", max_retests_per_unit=1
        )
        lot = _create_empty_lot(api, ctx, quantity=2)
        validate_success(
            api.create_unit(create_unit_payload(lot["id"], serial_number="SN-1"), OPS),
            201,
        )
        res = api.create_unit(create_unit_payload(lot["id"], serial_number="SN-1"), OPS)
        validate_error(res, "ERR_DUPLICATE_SERIAL", expected_status=409)
        lot_after = validate_success(api.get_lot(lot["id"], OPS), 200)
        assert lot_after["units_registered"] == 1, "rejected insert persisted nothing"

    def test_unit_registration_at_quantity_boundary(self, api):
        """PRD §3.4: "Registration is bounded by the declared quantity: the lot
        accepts registrations while `units_registered` is below `quantity`, the
        registration that brings the count exactly to `quantity` is allowed, and any
        registration beyond that is rejected with `ERR_QUANTITY_EXCEEDED`."

        Design: Corner/entities/unit_registration_at_quantity_boundary
        """
        ctx = setup_released_program_with_fixture(
            part_number="PN-202", max_retests_per_unit=1
        )
        lot = _create_empty_lot(api, ctx, quantity=2)
        # First registration: count below quantity — allowed.
        validate_success(
            api.create_unit(create_unit_payload(lot["id"], serial_number="Q-1"), OPS),
            201,
        )
        # Second unit brings the count exactly to quantity == 2: allowed.
        unit2 = validate_success(
            api.create_unit(create_unit_payload(lot["id"], serial_number="Q-2"), OPS),
            201,
        )
        assert_unit(unit2)
        # Third unit exceeds the declared quantity.
        res = api.create_unit(create_unit_payload(lot["id"], serial_number="Q-3"), OPS)
        validate_error(res, "ERR_QUANTITY_EXCEEDED", expected_status=422)


class TestPipelineGates:
    def test_enqueue_with_missing_units_rejected(self, api):
        """PRD §3.4: "Enqueue moves the lot from `RECEIVED` to `QUEUED` and requires
        the manifest to be complete — `units_registered` equal to `quantity`,
        otherwise `ERR_UNITS_INCOMPLETE` — with the program still `RELEASED`,
        otherwise `ERR_PROGRAM_NOT_RELEASED`."

        Design: Corner/validations/enqueue_with_missing_units_rejected
        """
        ctx = setup_released_program_with_fixture(
            part_number="PN-227", max_retests_per_unit=1
        )
        # Lot declares quantity 2 but only 1 unit is registered.
        lot2 = _create_empty_lot(api, ctx, quantity=2)
        validate_success(
            api.create_unit(create_unit_payload(lot2["id"], serial_number="IC-9"), OPS),
            201,
        )
        res = api.enqueue_lot(lot2["id"], OPS)
        validate_error(res, "ERR_UNITS_INCOMPLETE", expected_status=409)
        lot_after = validate_success(api.get_lot(lot2["id"], OPS), 200)
        assert lot_after["status"] == "RECEIVED", "rejected enqueue must change nothing"

    def test_complete_test_with_untested_units_rejected(self, api):
        """PRD §3.4: "Completing test moves it from `IN_TEST` to
        `AWAITING_DISPOSITION` and requires every unit to have been tested —
        `units_untested` equal to zero, otherwise `ERR_UNITS_INCOMPLETE`."

        Design: Corner/validations/complete_test_with_untested_units_rejected
        """
        ctx = setup_in_test_lot(quantity=2, part_number="PN-228", max_retests_per_unit=1)
        record_pass(ctx["units"][0], ctx["fixture"]["id"])
        res = api.complete_test_lot(ctx["lot"]["id"], OPS)
        validate_error(res, "ERR_UNITS_INCOMPLETE", expected_status=409)
        lot_after = validate_success(api.get_lot(ctx["lot"]["id"], OPS), 200)
        assert lot_after["status"] == "IN_TEST", "rejected complete-test must change nothing"
        assert_lot_tally_invariant(lot_after)

    def test_lot_ship_from_in_test_returns_invalid_state(self, api):
        """PRD §3.4: "Shipping moves the lot from `AWAITING_DISPOSITION` to
        `SHIPPED`, but a direct ship is permitted only when the lot's
        `suggested_disposition` is `SHIP` and no `PENDING` disposition review exists
        for the lot — otherwise the request is rejected with
        `ERR_DISPOSITION_REVIEW_REQUIRED` and the lot must instead pass through the
        MRB decision described in §3.6." (An `IN_TEST` lot is outside the ship
        transition entirely, so rung 4 applies.)
        PRD §2.11: "the target resource's own state permits the operation — a lot
        `IN_TEST` for result recording, a unit `FAILED` for retest authorization, a
        review `PENDING` for a decision, an audit `OPEN` for close, a reservation
        `RESERVED` for start, cancel, or reschedule, a program `DRAFT` or `VALIDATED`
        for validate or release — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/lot_ship_from_in_test_returns_invalid_state
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-208", max_retests_per_unit=1)
        res = api.ship_lot(ctx["lot"]["id"], OPS)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        lot_after = validate_success(api.get_lot(ctx["lot"]["id"], OPS), 200)
        assert lot_after["status"] == "IN_TEST", "rejected ship must change nothing"


class TestUnitListing:
    def test_units_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."
        PRD §2.3: "Unless otherwise specified, all list endpoints return resources
        sorted by their creation timestamp in ascending order."

        Design: Corner/endpoints/units_list_pagination_envelope
        """
        ctx = setup_released_program_with_fixture(part_number="PN-233")
        lot, units = create_lot_with_units(ctx, 4, serial_prefix="PG")

        page1, meta1 = validate_paginated(
            api.list_units(OPS, params={"lot_id": lot["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 4
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_units(OPS, params={"lot_id": lot["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 4
        assert meta2["has_more"] is False

        serials = [u["serial_number"] for u in page1 + page2]
        assert serials == ["PG-1", "PG-2", "PG-3", "PG-4"], (
            "pages must be disjoint and ordered by creation ascending"
        )
