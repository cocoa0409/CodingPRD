"""Water-chemistry classification, boundary pins and the auto-closure cascade."""

from test_helpers import (
    ADMIN,
    INSPECTOR,
    assert_posture,
    assert_water_reading,
    create_water_reading_payload,
    log_water_reading,
    read_facility,
    read_permit,
    read_staff_assignment,
    schedule_staff_shift,
    setup_facility_with_issued_permit,
    setup_operator_and_pool,
    setup_operator_and_spa,
    validate_paginated,
    validate_success,
)


def test_spa_limits_are_stricter_than_pool_limits(api):
    """PRD 3.7: The free-chlorine floor is 2.0 parts per million for a spa and
    1.0 for a pool; the free-chlorine ceiling is 10.0 for both; combined
    chloramine may not exceed 0.4; pH must sit between 7.0 and 7.8; cyanuric acid
    may not exceed 90 parts per million; and water temperature may not exceed
    104.0 degrees Fahrenheit at a spa or 95.0 at a pool.
    PRD 3.7: Separately from that list, a reading is judged an imminent hazard
    when free chlorine is strictly below 1.0 parts per million at a spa or
    strictly below 0.5 at a pool, or when pH is strictly below 6.5, or when pH is
    strictly above 8.2.

    Design: Corner/calculations/spa_chlorine_limits_are_stricter_than_pool_limits
    """
    ctx = setup_operator_and_spa(
        operator_overrides={
            "legal_name": "Rooftop Wellness",
            "contact_email": "spa@rooftop.example",
        }
    )

    below_the_spa_floor = validate_success(
        api.create_water_reading(
            ctx["facility_id"],
            create_water_reading_payload(free_chlorine_ppm=1.5, water_temp_f=100.0),
            ctx["op_headers"],
        ),
        201,
    )
    assert below_the_spa_floor["compliance_status"] == "OUT_OF_RANGE"
    assert below_the_spa_floor["out_of_range_parameters"] == ["FREE_CHLORINE_LOW"]
    assert below_the_spa_floor["triggered_closure_order_id"] is None

    imminent = validate_success(
        api.create_water_reading(
            ctx["facility_id"],
            create_water_reading_payload(free_chlorine_ppm=0.9, water_temp_f=100.0),
            ctx["op_headers"],
        ),
        201,
    )
    assert imminent["compliance_status"] == "IMMINENT_HAZARD"
    assert imminent["triggered_closure_order_id"] is not None

    orders, meta = validate_paginated(
        api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 1
    assert orders[0]["closure_reason"] == "WATER_CHEMISTRY"


def test_a_second_hazard_reading_does_not_stack_a_duplicate_closure(api):
    """PRD 3.7: The auto-creation is suppressed when the facility already has a
    closure order in `OPEN` or `REOPEN_REQUESTED`, in which case
    `triggered_closure_order_id` stays null — the venue is already shut and a
    second order adds nothing.
    PRD 3.7: Every breached limit contributes a code to
    `out_of_range_parameters`, and the codes are emitted in this fixed order
    regardless of which breaches occurred: `FREE_CHLORINE_LOW` when free chlorine
    is strictly below its floor, `FREE_CHLORINE_HIGH` when it is strictly above
    10.0, `COMBINED_CHLORAMINE_HIGH` when combined chloramine is strictly above
    0.4, `PH_LOW` when pH is strictly below 7.0, `PH_HIGH` when pH is strictly
    above 7.8, `CYANURIC_ACID_HIGH` when cyanuric acid is strictly above 90, and
    `TEMP_HIGH` when the temperature is strictly above its ceiling.

    Design: Corner/cross_cutting_layers/hazard_trigger_suppressed_while_an_order_is_already_open
    """
    ctx = setup_operator_and_pool()
    first = log_water_reading(
        ctx["facility_id"], ctx["op_headers"], free_chlorine_ppm=0.2
    )
    assert first["triggered_closure_order_id"] is not None

    second = validate_success(
        api.create_water_reading(
            ctx["facility_id"],
            create_water_reading_payload(free_chlorine_ppm=0.1, ph=6.4),
            ctx["op_headers"],
        ),
        201,
    )

    assert second["compliance_status"] == "IMMINENT_HAZARD"
    assert second["out_of_range_parameters"] == ["FREE_CHLORINE_LOW", "PH_LOW"]
    assert second["triggered_closure_order_id"] is None

    orders, meta = validate_paginated(
        api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 1
    assert orders[0]["triggering_reading_id"] == first["id"]


def test_the_cascade_is_visible_in_the_same_request_and_the_next_read(api):
    """PRD 3.7: A reading classified `IMMINENT_HAZARD` closes the venue by
    itself. The system creates a closure order for the facility in `OPEN` with
    `closure_reason` of `WATER_CHEMISTRY`, `triggering_reading_id` pointing back
    at this reading, `ordered_by_user_id` set to the literal string `system`, and
    `ordered_by_role` of `system`; the reading's own `triggered_closure_order_id`
    is set to that new order's id.
    PRD 2.9: The facility has at least one closure order whose status is `OPEN`
    or `REOPEN_REQUESTED` → `CLOSED` with reason `CLOSURE_ORDER_OPEN`.

    Design: Corner/consistency_model/cascade_effects_are_visible_in_the_same_request_response
    """
    ctx = setup_facility_with_issued_permit()

    reading = validate_success(
        api.create_water_reading(
            ctx["facility_id"],
            create_water_reading_payload(
                source="INSPECTOR_FIELD", free_chlorine_ppm=0.1
            ),
            INSPECTOR,
        ),
        201,
    )

    order_id = reading["triggered_closure_order_id"]
    assert order_id is not None, (
        "The creation response itself already carries the cascaded order id"
    )

    order = validate_success(api.get_closure_order(order_id, INSPECTOR))
    assert order["status"] == "OPEN"
    assert order["closure_reason"] == "WATER_CHEMISTRY"
    assert order["triggering_reading_id"] == reading["id"]
    assert order["ordered_by_user_id"] == "system"
    assert order["ordered_by_role"] == "system"

    assert_posture(read_facility(ctx["facility_id"]), "CLOSED", "CLOSURE_ORDER_OPEN")
    assert read_permit(ctx["permit_id"])["status"] == "ISSUED", (
        "A closure order does not suspend the permit"
    )


class TestChlorineBoundaryPins:
    """Every limit comparison is strict; sitting on a limit is compliant."""

    def test_exactly_the_imminent_floor_is_out_of_range_not_a_hazard(self, api):
        """PRD 3.7: All comparisons are strict at the boundary, which produces
        three pinned behaviours worth stating plainly: a pool reading of exactly
        1.0 parts per million free chlorine is `IN_RANGE`; a reading of exactly
        7.8 pH is `IN_RANGE`; and a pool reading of exactly 0.5 parts per million
        free chlorine is **not** an imminent hazard — it is `OUT_OF_RANGE`
        carrying `FREE_CHLORINE_LOW`.
        PRD 2.9: The facility has no permit records at all → `CLOSED` with reason
        `PERMIT_MISSING`.

        Design: Difficulty/boundary_precision_check/free_chlorine_exactly_at_imminent_floor_is_out_of_range_not_hazard
        """
        ctx = setup_operator_and_pool()

        reading = validate_success(
            api.create_water_reading(
                ctx["facility_id"],
                create_water_reading_payload(free_chlorine_ppm=0.5),
                ctx["op_headers"],
            ),
            201,
        )

        assert_water_reading(reading)
        assert reading["compliance_status"] == "OUT_OF_RANGE"
        assert reading["out_of_range_parameters"] == ["FREE_CHLORINE_LOW"]
        assert reading["triggered_closure_order_id"] is None

        orders, meta = validate_paginated(
            api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
        )
        assert meta["total_count"] == 0 and orders == []
        assert_posture(read_facility(ctx["facility_id"]), "CLOSED", "PERMIT_MISSING")

    def test_every_parameter_exactly_on_its_limit_is_in_range(self, api):
        """PRD 3.7: `compliance_status` is then `IMMINENT_HAZARD` if that hazard
        test fires, otherwise `OUT_OF_RANGE` if `out_of_range_parameters` is
        non-empty, otherwise `IN_RANGE`.
        PRD 3.7: The free-chlorine floor is 2.0 parts per million for a spa and
        1.0 for a pool; the free-chlorine ceiling is 10.0 for both; combined
        chloramine may not exceed 0.4; pH must sit between 7.0 and 7.8; cyanuric
        acid may not exceed 90 parts per million; and water temperature may not
        exceed 104.0 degrees Fahrenheit at a spa or 95.0 at a pool.

        Design: Difficulty/boundary_precision_check/free_chlorine_exactly_at_imminent_floor_is_out_of_range_not_hazard
        """
        ctx = setup_operator_and_pool()

        reading = validate_success(
            api.create_water_reading(
                ctx["facility_id"],
                create_water_reading_payload(
                    free_chlorine_ppm=1.0, combined_chloramine_ppm=0.4, ph=7.8,
                    water_temp_f=95.0,
                ),
                ctx["op_headers"],
            ),
            201,
        )

        assert reading["compliance_status"] == "IN_RANGE"
        assert reading["out_of_range_parameters"] == []
        assert reading["triggered_closure_order_id"] is None

        orders, meta = validate_paginated(
            api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
        )
        assert meta["total_count"] == 0 and orders == []


class TestHazardReadingCascade:
    """Reading -> closure order -> closed venue -> cancelled shift."""

    @staticmethod
    def _setup():
        ctx = setup_facility_with_issued_permit()
        ctx["assignment"] = schedule_staff_shift(
            ctx["facility_id"], ctx["op_headers"],
            shift_start_at="2026-05-01T00:00:00Z",
            shift_end_at="2026-05-01T08:00:00Z",
        )
        return ctx

    def test_the_reading_opens_a_water_chemistry_order_and_closes_the_venue(
        self, api
    ):
        """PRD 3.7: A reading classified `IMMINENT_HAZARD` closes the venue by
        itself. The system creates a closure order for the facility in `OPEN`
        with `closure_reason` of `WATER_CHEMISTRY`, `triggering_reading_id`
        pointing back at this reading, `ordered_by_user_id` set to the literal
        string `system`, and `ordered_by_role` of `system`; the reading's own
        `triggered_closure_order_id` is set to that new order's id.
        PRD 3.7: At creation the order stamps `ordered_at` from the logical
        clock, records `ordered_by_user_id` and `ordered_by_role` from the acting
        principal, sets `remediation_variant` to `FIXED_TABLE`, sets
        `required_remediation_minutes` to the table value for the reason, and
        sets `earliest_reopen_at` to `ordered_at` advanced by that many minutes.

        Design: Difficulty/transitive_cascade/imminent_reading_opens_closure_closes_facility_cancels_shift
        """
        ctx = self._setup()

        reading = validate_success(
            api.create_water_reading(
                ctx["facility_id"],
                create_water_reading_payload(free_chlorine_ppm=0.2),
                ctx["op_headers"],
            ),
            201,
        )

        assert reading["compliance_status"] == "IMMINENT_HAZARD"
        assert reading["out_of_range_parameters"] == ["FREE_CHLORINE_LOW"]

        orders, meta = validate_paginated(
            api.list_closure_orders(
                ADMIN, params={"triggering_reading_id": reading["id"]}
            )
        )
        assert meta["total_count"] == 1
        order = orders[0]
        assert order["closure_reason"] == "WATER_CHEMISTRY"
        assert order["status"] == "OPEN"
        assert order["required_remediation_minutes"] == 30
        assert order["earliest_reopen_at"] == "2026-05-01T00:30:00.000Z"

        assert_posture(
            read_facility(ctx["facility_id"]), "CLOSED", "CLOSURE_ORDER_OPEN"
        )

    def test_the_closure_cancels_the_overlapping_shift_but_spares_the_permit(
        self, api
    ):
        """PRD 3.7: Then every staff assignment of that facility whose status is
        `SCHEDULED` and whose shift overlaps the closure window is cancelled with
        `cancel_reason` of `FACILITY_CLOSED` and `cancelled_at` stamped from the
        logical clock; a shift overlaps when its `shift_start_at` is strictly
        before the order's `earliest_reopen_at` and its `shift_end_at` is
        strictly after the order's `ordered_at`.
        PRD 3.8: The only other route into `CANCELLED` is the closure cascade of
        Section 3.7, which sets `cancel_reason` to `FACILITY_CLOSED` instead.

        Design: Difficulty/transitive_cascade/imminent_reading_opens_closure_closes_facility_cancels_shift
        """
        ctx = self._setup()

        log_water_reading(
            ctx["facility_id"], ctx["op_headers"], free_chlorine_ppm=0.2
        )

        assignment = read_staff_assignment(
            ctx["facility_id"], ctx["assignment"]["id"], ADMIN
        )
        assert assignment["status"] == "CANCELLED"
        assert assignment["cancel_reason"] == "FACILITY_CLOSED"

        assert read_permit(ctx["permit_id"])["status"] == "ISSUED", (
            "The cascade never reaches the permit"
        )
