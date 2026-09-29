"""Validation rules guarding the commercial book.

Each test drives one refusal (or one deliberate acceptance) that PRD.md states in
prose: the reservation gates of PRD 3.3 and 3.6, the account-opening
preconditions of PRD 3.6, the truck-roll and mounting rules of PRD 3.7, the
metered-usage cycle window and equipment close-out of PRD 3.8, and the outage and
service-level-credit lifecycle of PRD 3.9.

The harness restarts the API and empties the database before every test, so each
test builds the whole world it needs from the published endpoints.
"""

import pytest

from test_helpers import (
    CLOCK_START_UTC,
    CREDIT_APPROVER_HEADERS,
    CREDIT_PREPARER_HEADERS,
    DECIDING_ENGINEER_HEADERS,
    SURVEY_PRESETS,
    ApiErrorId,
    api_client,
    assert_capacity_hold,
    assert_no_mutation,
    assert_outage_credit,
    assert_outage_event,
    assert_subscriber,
    assert_usage_record,
    close_outage_payload,
    completion_payload,
    create_outage,
    create_outage_credit_payload,
    create_service_plan,
    create_subscriber_payload,
    create_tower,
    create_work_order_payload,
    decide_exception,
    get_credit,
    get_equipment_assignment,
    get_outage,
    get_sector,
    get_serviceability_request,
    get_subscriber,
    get_work_order,
    iso_shift,
    reserve_bandwidth,
    return_equipment,
    reverse_credit,
    set_clock,
    settle_unreturned_equipment,
    setup_active_plant,
    setup_active_subscriber,
    setup_applied_credit,
    setup_deferred_request,
    setup_held_reservation,
    setup_lapsed_hold,
    setup_pending_install_subscriber,
    setup_prepared_credit,
    setup_qualified_request,
    setup_return_pending_assignment,
    setup_scheduled_work_order,
    setup_sector_frozen_by_backhaul,
    setup_voided_assignment,
    setup_work_order_in_state,
    setup_write_off_ready_assignment,
    survey_work_order,
    usage_record_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Outage intervals must be well formed
# --------------------------------------------------------------------------


class TestOutageInterval:
    @pytest.mark.parametrize(
        "ended_at",
        [
            pytest.param("2026-08-05T02:00:00Z", id="ended_at_equals_started_at"),
            pytest.param("2026-08-05T01:59:00Z", id="ended_at_before_started_at"),
        ],
    )
    def test_closing_an_outage_on_a_malformed_interval_is_rejected(
        self, api, network_engineer, ended_at
    ):
        """PRD 3.9: "The interval must be well formed, with `ended_at` strictly after
        `started_at`, else `ERR_INTERVAL_INVALID`."
        PRD 3.9: "The engineer closes it by supplying the `ended_at` instant, which is exclusive, and — for wind
        events — the `peak_wind_mph` measured at the site."

        Design: Corner/validations/outage_closure_with_ended_at_equal_to_started_at_is_rejected
        """
        tower = create_tower()
        outage = create_outage(
            tower["id"], cause="POWER", started_at="2026-08-05T02:00:00Z"
        )
        assert_outage_event(outage)
        assert outage["status"] == "OPEN"
        assert outage["ended_at"] is None
        assert outage["duration_minutes"] is None

        response = api.close_outage_event(
            outage["id"], close_outage_payload(ended_at=ended_at), network_engineer
        )
        validate_error(response, ApiErrorId.ERR_INTERVAL_INVALID.value)

        after = get_outage(outage["id"])
        assert after["status"] == "OPEN"
        assert after["ended_at"] is None
        assert after["duration_minutes"] is None
        assert_no_mutation(outage, after, "outage event")

    def test_closing_an_outage_one_minute_after_it_started_is_accepted(
        self, api, network_engineer
    ):
        """PRD 3.9: "The interval must be well formed, with `ended_at` strictly after
        `started_at`, else `ERR_INTERVAL_INVALID`."
        PRD 3.9: "Closure stores `ended_at` and `peak_wind_mph`, computes
        `duration_minutes` as the whole minutes between the two instants with any
        fractional minute discarded, and fixes `sla_excluded`."

        Design: Corner/validations/outage_closure_with_ended_at_equal_to_started_at_is_rejected
        """
        tower = create_tower()
        outage = create_outage(
            tower["id"], cause="POWER", started_at="2026-08-05T02:00:00Z"
        )

        response = api.close_outage_event(
            outage["id"],
            close_outage_payload(ended_at="2026-08-05T02:01:00Z"),
            network_engineer,
        )
        closed = validate_success(response)
        assert closed["status"] == "CLOSED"
        assert closed["duration_minutes"] == 1
        assert closed["sla_excluded"] is False


# --------------------------------------------------------------------------
# Opening an account: the plan must match, and the mode must be permitted
# --------------------------------------------------------------------------


class TestAccountPlanAndEquipmentMode:
    def test_account_creation_rejects_a_plan_other_than_the_qualified_one(
        self, api, sales_agent
    ):
        """PRD 3.6: "And the named `service_plan_id` must be the same plan the
        enquiry was qualified against, that is the enquiry's `requested_plan_id`,
        else the request is refused with `ERR_PLAN_MISMATCH`; the geometry and the
        capacity search were both run against that plan's `downstream_mbps`, so
        substituting another plan at signing would invalidate both."

        Design: Corner/validations/subscriber_creation_rejects_a_swapped_plan_and_a_disallowed_equipment_mode
        """
        scenario = setup_held_reservation()
        request = get_serviceability_request(scenario["request"]["id"])
        assert request["status"] == "QUALIFIED"
        assert request["requested_plan_id"] == scenario["plan"]["id"]
        assert scenario["hold"]["status"] == "HELD"

        other_plan = create_service_plan(downstream_mbps=50, upstream_mbps=10)
        assert other_plan["id"] != scenario["plan"]["id"]

        response = api.create_subscriber(
            create_subscriber_payload(request["id"], other_plan["id"]), sales_agent
        )
        validate_error(response, ApiErrorId.ERR_PLAN_MISMATCH.value)

        _, meta = validate_paginated(api.list_subscribers(sales_agent))
        assert meta["total_count"] == 0, "a refused account must not be opened"

    @pytest.mark.parametrize(
        "equipment_policy,equipment_mode",
        [
            pytest.param("PURCHASE_ONLY", "RENTAL", id="rental_against_purchase_only"),
            pytest.param("RENTAL_ONLY", "PURCHASE", id="purchase_against_rental_only"),
        ],
    )
    def test_account_creation_rejects_an_equipment_mode_the_plan_forbids(
        self, api, sales_agent, equipment_policy, equipment_mode
    ):
        """PRD 3.6: "`ERR_PLAN_MISMATCH` is also raised here when the chosen
        `equipment_mode` is not permitted by the plan's `equipment_policy`: `RENTAL`
        is refused against a `PURCHASE_ONLY` plan, `PURCHASE` is refused against a
        `RENTAL_ONLY` plan, and a `RENTAL_OR_PURCHASE` plan accepts either."

        Design: Corner/validations/subscriber_creation_rejects_a_swapped_plan_and_a_disallowed_equipment_mode
        """
        scenario = setup_held_reservation(
            plan_overrides={"equipment_policy": equipment_policy}
        )
        assert scenario["plan"]["equipment_policy"] == equipment_policy

        response = api.create_subscriber(
            create_subscriber_payload(
                scenario["request"]["id"],
                scenario["plan"]["id"],
                equipment_mode=equipment_mode,
            ),
            sales_agent,
        )
        validate_error(response, ApiErrorId.ERR_PLAN_MISMATCH.value)

    @pytest.mark.parametrize("equipment_mode", ["RENTAL", "PURCHASE"])
    def test_a_rental_or_purchase_plan_accepts_either_equipment_mode(
        self, api, sales_agent, equipment_mode
    ):
        """PRD 3.6: "`ERR_PLAN_MISMATCH` is also raised here when the chosen
        `equipment_mode` is not permitted by the plan's `equipment_policy`: `RENTAL`
        is refused against a `PURCHASE_ONLY` plan, `PURCHASE` is refused against a
        `RENTAL_ONLY` plan, and a `RENTAL_OR_PURCHASE` plan accepts either."

        Design: Corner/validations/subscriber_creation_rejects_a_swapped_plan_and_a_disallowed_equipment_mode
        """
        scenario = setup_held_reservation(
            plan_overrides={"equipment_policy": "RENTAL_OR_PURCHASE"}
        )

        response = api.create_subscriber(
            create_subscriber_payload(
                scenario["request"]["id"],
                scenario["plan"]["id"],
                equipment_mode=equipment_mode,
            ),
            sales_agent,
        )
        subscriber = validate_success(response, 201)
        assert_subscriber(subscriber)
        assert subscriber["equipment_mode"] == equipment_mode
        assert subscriber["service_status"] == "PENDING_INSTALL"


# --------------------------------------------------------------------------
# Opening an account: a qualified enquiry and a live reservation
# --------------------------------------------------------------------------


class TestAccountNeedsQualificationAndHold:
    def test_account_creation_on_an_unreserved_qualification_is_rejected(
        self, api, sales_agent
    ):
        """PRD 3.6: "There must be a reservation for that enquiry still in `HELD` status, else `ERR_HOLD_NOT_HELD` —
        an account cannot be opened on unreserved bandwidth, and a lapsed reservation is exactly
        as fatal as no reservation."

        Design: Corner/validations/subscriber_creation_needs_a_qualified_request_and_a_live_hold
        """
        scenario = setup_qualified_request()
        request = get_serviceability_request(scenario["request"]["id"])
        assert request["status"] == "QUALIFIED"

        rows, meta = validate_paginated(
            api.list_capacity_holds(
                sales_agent, params={"serviceability_request_id": request["id"]}
            )
        )
        assert meta["total_count"] == 0 and rows == []

        response = api.create_subscriber(
            create_subscriber_payload(request["id"], scenario["plan"]["id"]), sales_agent
        )
        validate_error(response, ApiErrorId.ERR_HOLD_NOT_HELD.value)

    def test_account_creation_on_a_lapsed_reservation_is_rejected(self, api, sales_agent):
        """PRD 3.6: "There must be a reservation for that enquiry still in `HELD` status, else `ERR_HOLD_NOT_HELD` —
        an account cannot be opened on unreserved bandwidth, and a lapsed reservation is exactly
        as fatal as no reservation."
        PRD 3.6: "And when the logical clock reaches or passes `expires_at`, the
        reservation moves `HELD → EXPIRED` — a different status, not `RELEASED` —
        with a `release_reason` of `LAPSED`."
        PRD 3.6: "the enquiry the reservation was protecting, if still `QUALIFIED`,
        moves to `EXPIRED` with its `qualified_sector_id` cleared."

        The lapse drags the enquiry out of `QUALIFIED` as well, so both the
        enquiry-status precondition and the reservation precondition are violated at
        once and PRD.md does not order them against each other; either code is a
        faithful reading.

        Design: Corner/validations/subscriber_creation_needs_a_qualified_request_and_a_live_hold
        """
        scenario = setup_lapsed_hold(hold_days=1)
        assert scenario["hold"]["status"] == "EXPIRED"
        assert scenario["hold"]["release_reason"] == "LAPSED"

        response = api.create_subscriber(
            create_subscriber_payload(
                scenario["request"]["id"], scenario["plan"]["id"]
            ),
            sales_agent,
        )
        validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_HOLD_NOT_HELD.value,
                ApiErrorId.ERR_REQUEST_NOT_QUALIFIED.value,
            ],
        )

    def test_account_creation_from_a_capacity_deferred_enquiry_is_rejected(
        self, api, sales_agent
    ):
        """PRD 3.6: "The enquiry's `status` must be `QUALIFIED`, else
        `ERR_REQUEST_NOT_QUALIFIED`."
        PRD 3.6: "There must be a reservation for that enquiry still in `HELD` status, else `ERR_HOLD_NOT_HELD` —
        an account cannot be opened on unreserved bandwidth, and a lapsed reservation is exactly
        as fatal as no reservation."

        A `CAPACITY_DEFERRED` enquiry can never carry a reservation, so these two
        preconditions cannot be separated and PRD.md does not order them against
        each other; either code is a faithful reading.

        Design: Corner/validations/subscriber_creation_needs_a_qualified_request_and_a_live_hold
        """
        scenario = setup_deferred_request()
        deferred = get_serviceability_request(scenario["deferred_request"]["id"])
        assert deferred["status"] == "CAPACITY_DEFERRED"
        assert deferred["qualified_sector_id"] is None

        response = api.create_subscriber(
            create_subscriber_payload(
                deferred["id"], scenario["deferred_plan"]["id"]
            ),
            sales_agent,
        )
        validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_REQUEST_NOT_QUALIFIED.value,
                ApiErrorId.ERR_HOLD_NOT_HELD.value,
            ],
        )


# --------------------------------------------------------------------------
# One truck roll at a time
# --------------------------------------------------------------------------


class TestOneOpenWorkOrderPerAccount:
    @pytest.mark.parametrize(
        "open_status",
        ["SCHEDULED", "EXCEPTION_PENDING", "RESURVEY_REQUIRED", "MOUNT_APPROVED"],
    )
    def test_a_second_visit_while_one_is_in_flight_is_rejected(
        self, api, field_tech, open_status
    ):
        """PRD 3.7: "Only one visit may be in flight at a time: if the account
        already has a work order whose `status` is `SCHEDULED`,
        `EXCEPTION_PENDING`, `RESURVEY_REQUIRED` or `MOUNT_APPROVED`, the booking is
        refused with `ERR_WORK_ORDER_ALREADY_OPEN`."
        PRD 3.7: "Note that `MOUNT_APPROVED` counts as in flight: a mount that has
        been approved but not yet built is still an open commitment."

        Design: Corner/validations/a_second_open_work_order_for_the_same_subscriber_is_rejected
        """
        scenario = setup_work_order_in_state(open_status)
        assert scenario["work_order"]["status"] == open_status
        subscriber = get_subscriber(scenario["subscriber"]["id"])
        assert subscriber["service_status"] == "PENDING_INSTALL"

        response = api.create_work_order(
            create_work_order_payload(
                subscriber["id"], scheduled_at="2026-08-12T15:00:00Z"
            ),
            field_tech,
        )
        validate_error(response, ApiErrorId.ERR_WORK_ORDER_ALREADY_OPEN.value)

        rows, meta = validate_paginated(
            api.list_subscriber_work_orders(subscriber["id"], field_tech)
        )
        assert meta["total_count"] == 1, "the refused booking must not be recorded"
        assert rows[0]["id"] == scenario["work_order"]["id"]

    @pytest.mark.parametrize("finished_status", ["INSTALLED", "SURVEY_FAILED"])
    def test_a_finished_visit_does_not_block_a_new_booking(
        self, api, field_tech, finished_status
    ):
        """PRD 3.7: "Work orders in `INSTALLED`, `SURVEY_FAILED` or `CANCELLED`
        status are finished and do not block a new booking."
        PRD 3.7: "Booking is accepted for an account whose `service_status` is `PENDING_INSTALL`, `ACTIVE` or
        `SUSPENDED` — a visit to an existing account is a legitimate re-install or relocation —
        but an account already `CANCELLED` is refused with `ERR_SUBSCRIBER_NOT_ACTIVE`."

        Design: Corner/validations/a_second_open_work_order_for_the_same_subscriber_is_rejected
        """
        scenario = setup_work_order_in_state(finished_status)
        assert scenario["work_order"]["status"] == finished_status
        subscriber_id = scenario["subscriber"]["id"]

        response = api.create_work_order(
            create_work_order_payload(
                subscriber_id, scheduled_at="2026-08-12T15:00:00Z"
            ),
            field_tech,
        )
        second = validate_success(response, 201)
        assert second["status"] == "SCHEDULED"
        assert second["resurvey_count"] == 0
        assert second["id"] != scenario["work_order"]["id"]


# --------------------------------------------------------------------------
# Structural mounting safety
# --------------------------------------------------------------------------


def _setup_mount_approved(band: str) -> dict:
    """A truck roll surveyed straight into `MOUNT_APPROVED` on `band`.

    `WALL_BRACKET` and `NON_PEN_ROOF_TRIPOD` are the two bands a technician may
    erect without an engineering exception (PRD 3.7).
    """
    scenario = setup_scheduled_work_order()
    scenario["work_order"] = survey_work_order(
        scenario["work_order"]["id"], **SURVEY_PRESETS[band]
    )
    assert scenario["work_order"]["status"] == "MOUNT_APPROVED", (
        f"Setup failed: survey preset {band} did not reach MOUNT_APPROVED"
    )
    assert scenario["work_order"]["approved_mounting_type"] == band
    return scenario


class TestInstalledMastAgainstApprovedBand:
    @pytest.mark.parametrize(
        "band,ceiling_m,installed_mast_height_m",
        [
            pytest.param("WALL_BRACKET", 1.0, 1.5, id="wall_bracket_ceiling_1m"),
            pytest.param("NON_PEN_ROOF_TRIPOD", 3.0, 3.5, id="tripod_ceiling_3m"),
        ],
    )
    def test_an_installed_mast_above_the_approved_ceiling_is_rejected(
        self, api, field_tech, band, ceiling_m, installed_mast_height_m
    ):
        """PRD 3.7: "And the `installed_mast_height_m` must not exceed the ceiling of the `approved_mounting_type` —
        the same four ceilings of 1.0, 3.0, 6.0 and 12.0 metres — else the completion is refused
        with `ERR_MAST_EXCEEDS_STRUCTURAL_LIMIT`."
        PRD 3.7: "Note that this compares what was actually built against what was
        approved, which is a different test from the `ERR_MOUNTING_INCOMPATIBLE`
        check that compared the approved band against what was recommended."
        PRD 3.7: "A `FieldTech` closes out the visit by reporting the `installed_mast_height_m` actually erected —
        between 0.0 and 12.0 inclusive to one decimal place — and the `radio_serial` of the
        customer premises unit left on the wall."

        Design: Corner/validations/installed_mast_above_the_approved_band_ceiling_is_rejected
        """
        scenario = _setup_mount_approved(band)
        work_order = scenario["work_order"]
        assert installed_mast_height_m > ceiling_m

        response = api.complete_work_order(
            work_order["id"],
            completion_payload(installed_mast_height_m=installed_mast_height_m),
            field_tech,
        )
        validate_error(response, ApiErrorId.ERR_MAST_EXCEEDS_STRUCTURAL_LIMIT.value)

        after = get_work_order(work_order["id"])
        assert after["status"] == "MOUNT_APPROVED"
        assert after["installed_mast_height_m"] is None
        assert after["radio_serial"] is None
        assert after["installed_at"] is None
        assert after["install_invoice_total_cents"] is None
        assert_no_mutation(work_order, after, "install work order")

        subscriber = get_subscriber(scenario["subscriber"]["id"])
        assert subscriber["service_status"] == "PENDING_INSTALL"
        assert subscriber["cycle_start_date"] is None

    @pytest.mark.parametrize(
        "band,ceiling_m",
        [
            pytest.param("WALL_BRACKET", 1.0, id="wall_bracket_ceiling_1m"),
            pytest.param("NON_PEN_ROOF_TRIPOD", 3.0, id="tripod_ceiling_3m"),
        ],
    )
    def test_an_installed_mast_exactly_on_the_approved_ceiling_is_accepted(
        self, api, field_tech, band, ceiling_m
    ):
        """PRD 3.7: "And the `installed_mast_height_m` must not exceed the ceiling of the `approved_mounting_type` —
        the same four ceilings of 1.0, 3.0, 6.0 and 12.0 metres — else the completion is refused
        with `ERR_MAST_EXCEEDS_STRUCTURAL_LIMIT`."

        Design: Corner/validations/installed_mast_above_the_approved_band_ceiling_is_rejected
        """
        scenario = _setup_mount_approved(band)

        response = api.complete_work_order(
            scenario["work_order"]["id"],
            completion_payload(installed_mast_height_m=ceiling_m),
            field_tech,
        )
        completed = validate_success(response)
        assert completed["status"] == "INSTALLED"
        assert completed["installed_mast_height_m"] == ceiling_m


class TestExceptionPendingCompletionAndBandStrength:
    def test_completing_a_work_order_awaiting_an_engineering_decision_is_rejected(
        self, api, field_tech
    ):
        """PRD 3.7: "Completion is permitted only from `MOUNT_APPROVED`, and the
        refusal is deliberately split: a work order still sitting in
        `EXCEPTION_PENDING` is refused with `ERR_MOUNT_EXCEPTION_REQUIRED`, telling
        the technician that an engineer must sign the mount off first, while a work
        order in `SCHEDULED`, `RESURVEY_REQUIRED`, `INSTALLED`, `SURVEY_FAILED` or
        `CANCELLED` is refused with the generic `ERR_WORK_ORDER_STATE_INVALID`."
        PRD 2.7: "There is exactly one carve-out: an install completion attempted on a work order that is awaiting
        an engineering mounting decision is **not** reported at this rung — it falls through to
        rung 11 and is refused with `ERR_MOUNT_EXCEPTION_REQUIRED`, because the actionable
        defect is the missing approval rather than the status label."

        Design: Corner/validations/exception_pending_completion_and_an_undersized_approved_band_are_both_rejected
        """
        scenario = setup_work_order_in_state("EXCEPTION_PENDING")
        work_order = scenario["work_order"]
        assert work_order["status"] == "EXCEPTION_PENDING"
        assert work_order["approved_mounting_type"] is None

        response = api.complete_work_order(
            work_order["id"],
            completion_payload(installed_mast_height_m=5.0),
            field_tech,
        )
        validate_error(response, ApiErrorId.ERR_MOUNT_EXCEPTION_REQUIRED.value)

        after = get_work_order(work_order["id"])
        assert after["status"] == "EXCEPTION_PENDING"
        assert_no_mutation(work_order, after, "install work order")

    @pytest.mark.parametrize(
        "other_status", ["SCHEDULED", "RESURVEY_REQUIRED", "SURVEY_FAILED"]
    )
    def test_completing_a_work_order_in_any_other_status_reports_the_generic_state_error(
        self, api, field_tech, other_status
    ):
        """PRD 3.7: "Completion is permitted only from `MOUNT_APPROVED`, and the
        refusal is deliberately split: a work order still sitting in
        `EXCEPTION_PENDING` is refused with `ERR_MOUNT_EXCEPTION_REQUIRED`, telling
        the technician that an engineer must sign the mount off first, while a work
        order in `SCHEDULED`, `RESURVEY_REQUIRED`, `INSTALLED`, `SURVEY_FAILED` or
        `CANCELLED` is refused with the generic `ERR_WORK_ORDER_STATE_INVALID`."
        PRD 2.7: "Every other status that does not permit completion still reports
        `ERR_WORK_ORDER_STATE_INVALID` here."

        Design: Corner/validations/exception_pending_completion_and_an_undersized_approved_band_are_both_rejected
        """
        scenario = setup_work_order_in_state(other_status)
        assert scenario["work_order"]["status"] == other_status
        assert get_subscriber(scenario["subscriber"]["id"])["service_status"] == (
            "PENDING_INSTALL"
        )

        response = api.complete_work_order(
            scenario["work_order"]["id"],
            completion_payload(installed_mast_height_m=2.5),
            field_tech,
        )
        validate_error(response, ApiErrorId.ERR_WORK_ORDER_STATE_INVALID.value)

    @pytest.mark.parametrize(
        "weaker_band,weaker_ceiling_m",
        [
            pytest.param("WALL_BRACKET", 1.0, id="wall_bracket_ceiling_1m"),
            pytest.param("NON_PEN_ROOF_TRIPOD", 3.0, id="tripod_ceiling_3m"),
        ],
    )
    def test_approving_a_band_weaker_than_the_recommendation_is_rejected(
        self, api, weaker_band, weaker_ceiling_m
    ):
        """PRD 3.7: "Whichever band ends up approved, its ceiling — 1.0 metre for `WALL_BRACKET`, 3.0 for
        `NON_PEN_ROOF_TRIPOD`, 6.0 for `ROOF_MAST_GUYED`, 12.0 for `GROUND_POLE_MAST` — must be
        at or above `recommended_mast_height_m`, else the decision is refused with
        `ERR_MOUNTING_INCOMPATIBLE`. An engineer may therefore approve a **stronger** band than
        was recommended but never a weaker one."

        Design: Corner/validations/exception_pending_completion_and_an_undersized_approved_band_are_both_rejected
        """
        scenario = setup_work_order_in_state("EXCEPTION_PENDING")
        work_order = scenario["work_order"]
        assert work_order["recommended_mounting_type"] == "ROOF_MAST_GUYED"
        assert work_order["recommended_mast_height_m"] > weaker_ceiling_m

        response = api.decide_exception(
            work_order["id"],
            {
                "decision": "APPROVE",
                "note": "Trying a lighter structure than the survey asked for",
                "approved_mounting_type": weaker_band,
            },
            DECIDING_ENGINEER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_MOUNTING_INCOMPATIBLE.value)

        after = get_work_order(work_order["id"])
        assert after["status"] == "EXCEPTION_PENDING"
        assert after["approved_mounting_type"] is None
        assert after["exception_approved_by_user_id"] is None
        assert_no_mutation(work_order, after, "install work order")

    @pytest.mark.parametrize(
        "stronger_band", ["ROOF_MAST_GUYED", "GROUND_POLE_MAST"]
    )
    def test_approving_the_recommended_band_or_a_stronger_one_is_accepted(
        self, stronger_band
    ):
        """PRD 3.7: "Whichever band ends up approved, its ceiling — 1.0 metre for `WALL_BRACKET`, 3.0 for
        `NON_PEN_ROOF_TRIPOD`, 6.0 for `ROOF_MAST_GUYED`, 12.0 for `GROUND_POLE_MAST` — must be
        at or above `recommended_mast_height_m`, else the decision is refused with
        `ERR_MOUNTING_INCOMPATIBLE`. An engineer may therefore approve a **stronger** band than
        was recommended but never a weaker one."

        Design: Corner/validations/exception_pending_completion_and_an_undersized_approved_band_are_both_rejected
        """
        scenario = setup_work_order_in_state("EXCEPTION_PENDING")

        decided = decide_exception(
            scenario["work_order"]["id"],
            "APPROVE",
            note="Structure signed off by the engineer of record",
            approved_mounting_type=stronger_band,
        )
        assert decided["status"] == "MOUNT_APPROVED"
        assert decided["approved_mounting_type"] == stronger_band


# --------------------------------------------------------------------------
# Metered days live inside the open cycle only
# --------------------------------------------------------------------------


class TestUsageDateInsideTheOpenCycle:
    @pytest.mark.parametrize(
        "usage_date",
        [
            pytest.param("2026-07-31", id="day_before_cycle_start"),
            pytest.param("2026-08-31", id="exactly_cycle_start_plus_30_days"),
            pytest.param("2026-09-01", id="beyond_cycle_start_plus_30_days"),
        ],
    )
    def test_a_metered_day_outside_the_open_cycle_is_rejected(
        self, api, billing_admin, usage_date
    ):
        """PRD 3.8: "And the `usage_date` must fall inside the account's current cycle window — at or after
        `cycle_start_date` and strictly before `cycle_start_date` advanced by the cycle length
        of 30 days — else the ingestion is refused with `ERR_USAGE_DATE_OUT_OF_CYCLE`."
        PRD 3.8: "Back-dating into a cycle that has already been closed, or
        forward-dating into one that has not yet opened, is therefore impossible;
        history is only ever accumulated within the open cycle."
        PRD 3.7: "The account moves `PENDING_INSTALL → ACTIVE`, with
        `service_start_date` set from the logical clock and `cycle_start_date` set to
        the calendar date of that same instant, which opens the account's first
        billing cycle."

        Design: Corner/validations/usage_record_dated_outside_the_open_cycle_is_rejected
        """
        scenario = setup_active_subscriber()
        subscriber = get_subscriber(scenario["subscriber"]["id"])
        assert subscriber["service_status"] == "ACTIVE"
        assert subscriber["cycle_start_date"] == "2026-08-01"

        response = api.create_usage_record(
            subscriber["id"], usage_record_payload(usage_date, 40.0, 5.0), billing_admin
        )
        validate_error(response, ApiErrorId.ERR_USAGE_DATE_OUT_OF_CYCLE.value)

        rows, meta = validate_paginated(
            api.list_usage_records(subscriber["id"], billing_admin)
        )
        assert meta["total_count"] == 0 and rows == []
        assert get_subscriber(subscriber["id"])["cycle_usage_gb"] == 0.0

    @pytest.mark.parametrize(
        "usage_date",
        [
            pytest.param("2026-08-01", id="exactly_on_cycle_start"),
            pytest.param("2026-08-30", id="last_day_inside_the_window"),
        ],
    )
    def test_a_metered_day_on_either_edge_of_the_open_cycle_is_accepted(
        self, api, billing_admin, usage_date
    ):
        """PRD 3.8: "And the `usage_date` must fall inside the account's current cycle window — at or after
        `cycle_start_date` and strictly before `cycle_start_date` advanced by the cycle length
        of 30 days — else the ingestion is refused with `ERR_USAGE_DATE_OUT_OF_CYCLE`."
        PRD 3.8: "A record also reports `in_current_cycle`, true when its
        `usage_date` falls inside the account's current cycle window."

        Design: Corner/validations/usage_record_dated_outside_the_open_cycle_is_rejected
        """
        scenario = setup_active_subscriber()
        subscriber_id = scenario["subscriber"]["id"]
        assert get_subscriber(subscriber_id)["cycle_start_date"] == "2026-08-01"

        response = api.create_usage_record(
            subscriber_id, usage_record_payload(usage_date, 40.0, 5.0), billing_admin
        )
        record = validate_success(response, 201)
        assert_usage_record(record)
        assert record["usage_date"] == usage_date
        assert record["in_current_cycle"] is True


# --------------------------------------------------------------------------
# Hardware close-out: only a RETURN_PENDING radio may be returned
# --------------------------------------------------------------------------


def _assignment_in_status(status: str) -> dict:
    """One equipment record driven to `status` through the published endpoints."""
    if status == "ASSIGNED":
        return setup_pending_install_subscriber()["assignment"]
    if status == "DEPLOYED":
        return setup_active_subscriber()["assignment"]
    if status == "VOIDED":
        return setup_voided_assignment()["assignment"]
    if status == "RETURNED":
        scenario = setup_return_pending_assignment()
        return return_equipment(scenario["assignment"]["id"])
    if status == "UNRETURNED_BILLED":
        scenario = setup_write_off_ready_assignment()
        return settle_unreturned_equipment(scenario["assignment"]["id"])
    raise AssertionError(f"Setup failed: unsupported assignment status {status!r}")


class TestOnlyReturnPendingRadiosMayBeReturned:
    @pytest.mark.parametrize(
        "status",
        ["ASSIGNED", "DEPLOYED", "RETURNED", "UNRETURNED_BILLED", "VOIDED"],
    )
    def test_returning_a_radio_that_is_not_awaiting_return_is_refused(
        self, api, field_tech, status
    ):
        """PRD 3.8: "The record must be in `RETURN_PENDING`; one in `ASSIGNED`,
        `DEPLOYED`, `RETURNED`, `UNRETURNED_BILLED` or `VOIDED` is refused with
        `ERR_ASSIGNMENT_NOT_RETURNABLE`."

        Design: Corner/validations/returning_a_radio_that_was_never_deployed_is_refused
        """
        assignment = _assignment_in_status(status)
        assert assignment["status"] == status

        response = api.return_equipment(
            assignment["id"], {"return_condition": "GOOD"}, field_tech
        )
        validate_error(response, ApiErrorId.ERR_ASSIGNMENT_NOT_RETURNABLE.value)

        after = get_equipment_assignment(assignment["id"])
        assert after["status"] == status
        assert_no_mutation(assignment, after, "equipment assignment")

    def test_returning_a_radio_that_is_awaiting_return_is_accepted(
        self, api, field_tech
    ):
        """PRD 3.8: "The record must be in `RETURN_PENDING`; one in `ASSIGNED`,
        `DEPLOYED`, `RETURNED`, `UNRETURNED_BILLED` or `VOIDED` is refused with
        `ERR_ASSIGNMENT_NOT_RETURNABLE`."
        PRD 3.8: "On success it moves `RETURN_PENDING → RETURNED`, which is
        terminal, stamping `returned_at` from the logical clock and storing
        `return_condition`."

        Design: Corner/validations/returning_a_radio_that_was_never_deployed_is_refused
        """
        scenario = setup_return_pending_assignment()
        assert scenario["assignment"]["status"] == "RETURN_PENDING"

        response = api.return_equipment(
            scenario["assignment"]["id"], {"return_condition": "GOOD"}, field_tech
        )
        returned = validate_success(response)
        assert returned["status"] == "RETURNED"
        assert returned["return_condition"] == "GOOD"
        assert returned["returned_at"] is not None


# --------------------------------------------------------------------------
# Writing off a radio needs the return window to have closed
# --------------------------------------------------------------------------


class TestReturnWindowBeforeWriteOff:
    def test_writing_off_a_radio_before_the_return_deadline_is_rejected(
        self, api, billing_admin
    ):
        """PRD 3.8: "and the return window must have closed: the logical clock must
        be at or after `return_due_at`, else the write-off is refused with
        `ERR_RETURN_WINDOW_OPEN`."
        PRD 3.8: "its `return_due_at` is set to the logical clock advanced by the
        return window of 21 days"

        Design: Corner/validations/unreturned_settlement_before_the_return_deadline_is_rejected
        """
        scenario = setup_return_pending_assignment()
        assignment = scenario["assignment"]
        assert assignment["status"] == "RETURN_PENDING"
        assert assignment["return_due_at"].startswith("2026-08-22T00:00:00")

        set_clock(iso_shift(CLOCK_START_UTC, days=21, minutes=-1))

        response = api.settle_unreturned_equipment(assignment["id"], {}, billing_admin)
        validate_error(response, ApiErrorId.ERR_RETURN_WINDOW_OPEN.value)

        after = get_equipment_assignment(assignment["id"])
        assert after["status"] == "RETURN_PENDING"
        assert after["settlement_cents"] == 0
        assert after["settlement_basis"] is None
        assert_no_mutation(assignment, after, "equipment assignment")
        assert get_subscriber(scenario["subscriber"]["id"])[
            "settlement_balance_cents"
        ] == 0

    def test_writing_off_a_radio_exactly_on_the_return_deadline_is_accepted(
        self, api, billing_admin
    ):
        """PRD 3.8: "and the return window must have closed: the logical clock must
        be at or after `return_due_at`, else the write-off is refused with
        `ERR_RETURN_WINDOW_OPEN`. The comparison is inclusive, so a clock landing
        exactly on `return_due_at` may already bill."

        Design: Corner/validations/unreturned_settlement_before_the_return_deadline_is_rejected
        """
        scenario = setup_return_pending_assignment()
        assignment = scenario["assignment"]

        set_clock(iso_shift(CLOCK_START_UTC, days=21))

        response = api.settle_unreturned_equipment(assignment["id"], {}, billing_admin)
        settled = validate_success(response)
        assert settled["status"] == "UNRETURNED_BILLED"


# --------------------------------------------------------------------------
# The service-level credit lifecycle
# --------------------------------------------------------------------------


class TestCreditLifecycleGates:
    def test_preparing_a_credit_against_an_open_outage_is_rejected(
        self, api, billing_admin
    ):
        """PRD 3.9: "The outage must be `CLOSED`, since an open outage has no
        measurable duration; an `OPEN` outage is refused with
        `ERR_OUTAGE_NOT_CLOSED`."

        Design: Corner/validations/credit_lifecycle_rejects_open_events_double_application_early_reversal_and_repeats
        """
        scenario = setup_active_subscriber()
        outage = create_outage(
            scenario["tower"]["id"], cause="POWER", started_at="2026-08-05T02:00:00Z"
        )
        assert outage["status"] == "OPEN"
        assert outage["duration_minutes"] is None

        response = api.create_outage_credit(
            create_outage_credit_payload(outage["id"], scenario["subscriber"]["id"]),
            billing_admin,
        )
        validate_error(response, ApiErrorId.ERR_OUTAGE_NOT_CLOSED.value)

        rows, meta = validate_paginated(
            api.list_outage_credits(billing_admin, params={"outage_event_id": outage["id"]})
        )
        assert meta["total_count"] == 0 and rows == []
        assert get_outage(outage["id"])["total_credited_cents"] == 0

    @pytest.mark.parametrize("existing_status", ["PENDING", "APPLIED"])
    def test_a_second_credit_for_the_same_outage_and_account_is_rejected(
        self, api, existing_status
    ):
        """PRD 3.9: "And no credit may already exist for that same outage and account
        in `PENDING` or `APPLIED` status, else `ERR_CREDIT_ALREADY_ISSUED`; a credit
        previously `DENIED` or `REVERSED` does not block a fresh attempt."

        Design: Corner/validations/credit_lifecycle_rejects_open_events_double_application_early_reversal_and_repeats
        """
        if existing_status == "PENDING":
            scenario = setup_prepared_credit()
        else:
            scenario = setup_applied_credit()
        assert scenario["credit"]["status"] == existing_status

        response = api.create_outage_credit(
            create_outage_credit_payload(
                scenario["outage"]["id"], scenario["subscriber"]["id"]
            ),
            CREDIT_PREPARER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_CREDIT_ALREADY_ISSUED.value)

        rows, meta = validate_paginated(
            api.list_outage_credits(
                CREDIT_PREPARER_HEADERS,
                params={"outage_event_id": scenario["outage"]["id"]},
            )
        )
        assert meta["total_count"] == 1, "the refused preparation must not be recorded"
        assert rows[0]["id"] == scenario["credit"]["id"]

    def test_applying_a_credit_that_is_already_applied_is_rejected(self, api):
        """PRD 3.9: "The credit must be in `PENDING` status; one in `APPLIED`,
        `DENIED` or `REVERSED` is refused with `ERR_CREDIT_NOT_PENDING`."

        Design: Corner/validations/credit_lifecycle_rejects_open_events_double_application_early_reversal_and_repeats
        """
        scenario = setup_applied_credit()
        credit = scenario["credit"]
        assert credit["status"] == "APPLIED"
        assert_outage_credit(credit)
        balance_before = get_subscriber(scenario["subscriber"]["id"])[
            "credit_balance_cents"
        ]
        assert balance_before == credit["credit_cents"]

        response = api.apply_outage_credit(
            credit["id"], {"note": "Second release attempt"}, CREDIT_APPROVER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_CREDIT_NOT_PENDING.value)

        after = get_credit(credit["id"])
        assert after["status"] == "APPLIED"
        assert_no_mutation(credit, after, "outage credit")
        assert (
            get_subscriber(scenario["subscriber"]["id"])["credit_balance_cents"]
            == balance_before
        ), "a refused application must not move the money twice"
        assert (
            get_outage(scenario["outage"]["id"])["total_credited_cents"]
            == credit["credit_cents"]
        )

    def test_applying_a_credit_that_has_been_reversed_is_rejected(self, api):
        """PRD 3.9: "The credit must be in `PENDING` status; one in `APPLIED`,
        `DENIED` or `REVERSED` is refused with `ERR_CREDIT_NOT_PENDING`."

        Design: Corner/validations/credit_lifecycle_rejects_open_events_double_application_early_reversal_and_repeats
        """
        scenario = setup_applied_credit()
        reversed_credit = reverse_credit(
            scenario["credit"]["id"], reversal_reason="Posted against the wrong outage"
        )
        assert reversed_credit["status"] == "REVERSED"

        response = api.apply_outage_credit(
            reversed_credit["id"], {}, CREDIT_APPROVER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_CREDIT_NOT_PENDING.value)

    def test_reversing_a_credit_that_was_never_applied_is_rejected(self, api):
        """PRD 3.9: "The credit must be in `APPLIED` status, else
        `ERR_CREDIT_NOT_APPLIED`."

        Design: Corner/validations/credit_lifecycle_rejects_open_events_double_application_early_reversal_and_repeats
        """
        scenario = setup_prepared_credit()
        credit = scenario["credit"]
        assert credit["status"] == "PENDING"
        assert credit["approved_by_user_id"] is None

        response = api.reverse_outage_credit(
            credit["id"],
            {"reversal_reason": "Prepared in error"},
            CREDIT_APPROVER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_CREDIT_NOT_APPLIED.value)

        after = get_credit(credit["id"])
        assert after["status"] == "PENDING"
        assert_no_mutation(credit, after, "outage credit")
        assert (
            get_subscriber(scenario["subscriber"]["id"])["credit_balance_cents"] == 0
        ), "a PENDING credit is not part of the account's credit balance"

    def test_reversing_a_credit_twice_is_rejected(self, api):
        """PRD 3.9: "The credit must be in `APPLIED` status, else
        `ERR_CREDIT_NOT_APPLIED`."
        PRD 3.9: "On success it moves `APPLIED → REVERSED`, which is terminal, and
        both roll-ups are decreased by `credit_cents`."

        Design: Corner/validations/credit_lifecycle_rejects_open_events_double_application_early_reversal_and_repeats
        """
        scenario = setup_applied_credit()
        first = reverse_credit(scenario["credit"]["id"], reversal_reason="Posted in error")
        assert first["status"] == "REVERSED"
        assert get_subscriber(scenario["subscriber"]["id"])["credit_balance_cents"] == 0

        response = api.reverse_outage_credit(
            first["id"], {"reversal_reason": "Reversing the reversal"}, CREDIT_APPROVER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_CREDIT_NOT_APPLIED.value)

        after = get_credit(first["id"])
        assert after["status"] == "REVERSED"
        assert_no_mutation(first, after, "outage credit")
        assert get_subscriber(scenario["subscriber"]["id"])["credit_balance_cents"] == 0


# --------------------------------------------------------------------------
# The three capacity gates on a reservation
#
# The reference sector is `capacity_mbps` 25 with `max_oversubscription_ratio`
# 8.0, so its ceiling is 200 Mbps and the watch, withhold and freeze lines sit at
# 100, 150 and 200 committed Mbps (PRD 3.3).
# --------------------------------------------------------------------------


def _reserve(request_id: str, sector: dict, headers: dict, hold_days=None):
    """POST a reservation for `request_id`, declaring `sector`'s current version."""
    payload = {
        "serviceability_request_id": request_id,
        "expected_sector_version": sector["version"],
    }
    if hold_days is not None:
        payload["hold_days"] = hold_days
    return api_client.create_capacity_hold(payload, headers)


class TestSectorPostureGates:
    def test_a_reservation_on_a_sector_at_hold_posture_is_rejected(self, sales_agent):
        """PRD 3.3: "A sector whose `capacity_posture` is `HOLD` accepts no new
        reservation and refuses one with `ERR_SECTOR_CAPACITY_HOLD`."
        PRD 3.6: "The sector's `capacity_posture` must not be `HOLD`, else
        `ERR_SECTOR_CAPACITY_HOLD`, and must not be `FROZEN`, else
        `ERR_SECTOR_FROZEN`."

        The allowance still covers the plan exactly, so the posture gate is the only
        rule this request can break.

        Design: Corner/validations/hold_on_a_sector_at_hold_posture_is_rejected
        """
        scenario = setup_qualified_request()
        assert scenario["plan"]["downstream_mbps"] == 50
        reserve_bandwidth(scenario, 150)

        sector = scenario["sector"]
        assert sector["capacity_posture"] == "HOLD"
        assert sector["committed_mbps"] == 150
        assert sector["oversubscription_ratio"] == 6.0
        assert sector["remaining_allowance_mbps"] == 50
        assert sector["status"] == "ACTIVE"

        response = _reserve(scenario["request"]["id"], sector, sales_agent)
        validate_error(response, ApiErrorId.ERR_SECTOR_CAPACITY_HOLD.value)

        after = get_sector(sector["id"])
        assert after["held_mbps"] == 150
        assert_no_mutation(sector, after, "sector")

    def test_a_reservation_on_a_sector_whose_tower_lost_its_transport_is_rejected(
        self, sales_agent
    ):
        """PRD 3.3: "A sector whose posture is `FROZEN` — at its ceiling, disabled, on a decommissioned tower, or on
        a tower with no accepted transport — likewise accepts none and refuses with
        `ERR_SECTOR_FROZEN`."
        PRD 3.3: "Otherwise, if the parent tower's `backhaul_accepted_mbps` is zero — that is, no circuit on the
        tower is in `ACCEPTED` state — the posture is `FROZEN`."

        The sector is empty, so its allowance is untouched and the freeze is the only
        rule this request can break.

        Design: Corner/validations/hold_on_a_sector_whose_tower_lost_its_accepted_backhaul_is_rejected
        """
        scenario = setup_qualified_request()
        scenario = setup_sector_frozen_by_backhaul(scenario)

        assert scenario["tower"]["backhaul_accepted_mbps"] == 0
        sector = scenario["sector"]
        assert sector["capacity_posture"] == "FROZEN"
        assert sector["status"] == "ACTIVE"
        assert sector["committed_mbps"] == 0
        assert sector["remaining_allowance_mbps"] == 200

        request = get_serviceability_request(scenario["request"]["id"])
        assert request["status"] == "QUALIFIED"

        response = _reserve(request["id"], sector, sales_agent)
        validate_error(response, ApiErrorId.ERR_SECTOR_FROZEN.value)

        after = get_sector(sector["id"])
        assert after["held_mbps"] == 0
        assert_no_mutation(sector, after, "sector")


class TestSectorAllowanceGate:
    def test_a_reservation_larger_than_the_remaining_allowance_is_rejected(
        self, sales_agent
    ):
        """PRD 3.3: "Separately, and regardless of posture, a reservation or a plan
        upgrade that needs more downstream Mbps than `remaining_allowance_mbps` still
        offers is refused with `ERR_INSUFFICIENT_SECTOR_CAPACITY`; the comparison is
        inclusive, so a plan needing exactly the remaining allowance is admitted."
        PRD 3.6: "And the sector's `remaining_allowance_mbps` must be at or above the
        plan's `downstream_mbps`, else `ERR_INSUFFICIENT_SECTOR_CAPACITY`."

        The sector sits on the watch line rather than at `HOLD` or `FROZEN`, so the
        allowance gate is the only rule this request can break.

        Design: Corner/validations/hold_larger_than_the_remaining_allowance_is_rejected
        """
        scenario = setup_active_plant(
            plan_overrides={"downstream_mbps": 150, "upstream_mbps": 30}
        )
        scenario = setup_qualified_request(scenario)
        reserve_bandwidth(scenario, 100)

        sector = scenario["sector"]
        assert sector["capacity_posture"] == "WATCH"
        assert sector["remaining_allowance_mbps"] == 100
        assert scenario["plan"]["downstream_mbps"] == 150

        response = _reserve(scenario["request"]["id"], sector, sales_agent)
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SECTOR_CAPACITY.value)

        after = get_sector(sector["id"])
        assert after["held_mbps"] == 100
        assert_no_mutation(sector, after, "sector")

    def test_a_reservation_at_watch_posture_inside_the_allowance_is_accepted(
        self, sales_agent
    ):
        """PRD 3.3: "A sector whose `capacity_posture` is `HOLD` accepts no new
        reservation and refuses one with `ERR_SECTOR_CAPACITY_HOLD`."
        PRD 3.3: "Separately, and regardless of posture, a reservation or a plan
        upgrade that needs more downstream Mbps than `remaining_allowance_mbps` still
        offers is refused with `ERR_INSUFFICIENT_SECTOR_CAPACITY`; the comparison is
        inclusive, so a plan needing exactly the remaining allowance is admitted."
        PRD 3.6: "A successful reservation opens in `HELD` `status` with `origin`
        `DIRECT`, no `release_reason`, and an `expires_at` set to the current logical
        clock advanced by `hold_days` days."

        Design: Corner/validations/hold_at_watch_posture_is_accepted_when_the_allowance_still_covers_the_plan
        """
        scenario = setup_qualified_request()
        reserve_bandwidth(scenario, 100)

        sector = scenario["sector"]
        assert sector["capacity_posture"] == "WATCH"
        assert sector["oversubscription_ratio"] == 4.0
        assert sector["remaining_allowance_mbps"] == 100

        response = _reserve(
            scenario["request"]["id"], sector, sales_agent, hold_days=7
        )
        hold = validate_success(response, 201)
        assert_capacity_hold(hold)
        assert hold["status"] == "HELD"
        assert hold["origin"] == "DIRECT"
        assert hold["release_reason"] is None
        assert hold["held_mbps"] == 50
        assert hold["hold_days"] == 7
        assert hold["expires_at"].startswith("2026-08-08T00:00:00")
        assert hold["sector_id"] == sector["id"]

        after = get_sector(sector["id"])
        assert after["held_mbps"] == 150
        assert after["committed_mbps"] == 150
        assert after["oversubscription_ratio"] == 6.0
        assert after["remaining_allowance_mbps"] == 50
        assert after["capacity_posture"] == "HOLD"

    def test_a_reservation_needing_exactly_the_remaining_allowance_is_admitted(
        self, sales_agent
    ):
        """PRD 3.3: "Separately, and regardless of posture, a reservation or a plan
        upgrade that needs more downstream Mbps than `remaining_allowance_mbps` still
        offers is refused with `ERR_INSUFFICIENT_SECTOR_CAPACITY`; the comparison is
        inclusive, so a plan needing exactly the remaining allowance is admitted."

        Design: Corner/validations/hold_at_watch_posture_is_accepted_when_the_allowance_still_covers_the_plan
        """
        scenario = setup_active_plant(
            plan_overrides={"downstream_mbps": 100, "upstream_mbps": 20}
        )
        scenario = setup_qualified_request(scenario)
        reserve_bandwidth(scenario, 100)

        sector = scenario["sector"]
        assert sector["capacity_posture"] == "WATCH"
        assert sector["remaining_allowance_mbps"] == 100 == scenario["plan"][
            "downstream_mbps"
        ]

        response = _reserve(scenario["request"]["id"], sector, sales_agent)
        hold = validate_success(response, 201)
        assert hold["status"] == "HELD"
        assert hold["held_mbps"] == 100

        after = get_sector(sector["id"])
        assert after["remaining_allowance_mbps"] == 0
        assert after["capacity_posture"] == "FROZEN"
