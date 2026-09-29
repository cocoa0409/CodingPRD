"""State machines of the commercial side of the business.

Account service status, the truck-roll machine and its bounded resurvey loop,
outage closure, and the equipment and work-order rows a cancellation drags with
it: the declared moves, the undeclared ones, and what a refusal leaves behind.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    DECIDING_ENGINEER_HEADERS,
    SURVEYOR_USER_ID,
    assert_no_mutation,
    cancel_subscriber,
    close_outage,
    create_outage,
    create_tower,
    decide_exception,
    get_assignment_for_subscriber,
    get_outage,
    get_sector,
    get_subscriber,
    get_work_order,
    is_iso8601_timestamp,
    make_field_tech_headers,
    reschedule_work_order,
    setup_active_subscriber,
    setup_pending_install_subscriber,
    setup_scheduled_work_order,
    survey_work_order,
    validate_error,
    validate_success,
)

CLOCK_AT_STARTUP = "2026-08-01T00:00:00"


class TestAccountServiceStatus:
    @pytest.mark.parametrize("to_status", ["ACTIVE", "SUSPENDED"])
    def test_pending_install_cannot_be_moved_by_hand(self, api, billing_admin, to_status):
        """PRD 3.8: "Any target that is not a declared move out of the account's current
        `service_status` — including any attempt to leave `CANCELLED`, which is terminal — is
        refused with `ERR_SUBSCRIBER_NOT_ACTIVE`."
        PRD 3.7: "The account moves `PENDING_INSTALL → ACTIVE`, with `service_start_date` set
        from the logical clock and `cycle_start_date` set to the calendar date of that same
        instant, which opens the account's first billing cycle."
        PRD 3.6: "`cycle_start_date` is absent because no billing cycle opens until the radio
        is actually installed; `cycle_usage_gb` is therefore zero, `consecutive_breach_cycles`
        is zero, `sticky_deprioritization_active` is false, and `deprioritized_at`,
        `service_start_date` and `cancelled_at` are all absent."

        Design: Corner/state_machines/subscriber_status_change_from_pending_install_to_active_is_rejected
        """
        scenario = setup_pending_install_subscriber()
        subscriber = scenario["subscriber"]
        assert subscriber["service_status"] == "PENDING_INSTALL", (
            f"a new account opens in PENDING_INSTALL, got {subscriber['service_status']!r}"
        )
        assert subscriber["version"] == 1, (
            f"version starts at 1 on creation, got {subscriber['version']}"
        )

        response = api.change_subscriber_status(
            subscriber["id"],
            {"to_status": to_status, "reason": "manual activation attempt"},
            billing_admin,
        )
        validate_error(response, ApiErrorId.ERR_SUBSCRIBER_NOT_ACTIVE)

        after = get_subscriber(subscriber["id"])
        assert after["service_status"] == "PENDING_INSTALL", (
            "activation exists only as a consequence of a completed install, so the refused "
            f"request leaves the account in PENDING_INSTALL, got {after['service_status']!r}"
        )
        assert after.get("service_start_date") is None, (
            "no install completed, so no service_start_date was ever set, got "
            f"{after.get('service_start_date')!r}"
        )
        assert after.get("cycle_start_date") is None, (
            "no billing cycle opens until the radio is actually installed, got "
            f"{after.get('cycle_start_date')!r}"
        )
        assert after["version"] == 1, (
            f"a refused status change is not a mutation, got version {after['version']}"
        )
        assert_no_mutation(subscriber, after, entity="account after a refused status change")

    @pytest.mark.parametrize("to_status", ["ACTIVE", "SUSPENDED"])
    def test_cancelled_account_cannot_be_left(self, api, billing_admin, to_status):
        """PRD 3.8: "Any target that is not a declared move out of the account's current
        `service_status` — including any attempt to leave `CANCELLED`, which is terminal — is
        refused with `ERR_SUBSCRIBER_NOT_ACTIVE`."

        Design: Corner/state_machines/subscriber_status_change_from_pending_install_to_active_is_rejected
        """
        scenario = setup_active_subscriber()
        cancelled = cancel_subscriber(scenario["subscriber"]["id"], reason="Customer moved away")
        assert cancelled["service_status"] == "CANCELLED", (
            f"setup must reach the terminal status, got {cancelled['service_status']!r}"
        )

        response = api.change_subscriber_status(
            scenario["subscriber"]["id"],
            {"to_status": to_status, "reason": "revive the household"},
            billing_admin,
        )
        validate_error(response, ApiErrorId.ERR_SUBSCRIBER_NOT_ACTIVE)

        after = get_subscriber(scenario["subscriber"]["id"])
        assert after["service_status"] == "CANCELLED", (
            f"CANCELLED is terminal, got {after['service_status']!r}"
        )
        assert_no_mutation(cancelled, after, entity="cancelled account")

    def test_cancel_from_pending_install_voids_the_radio_and_cancels_the_visit(
        self, api, billing_admin
    ):
        """PRD 3.8: "`CANCELLED` is reachable from `PENDING_INSTALL`, from `ACTIVE` and from
        `SUSPENDED`, and it stamps `cancelled_at` from the logical clock."
        PRD 3.8: "Cancelling from `PENDING_INSTALL` means no radio was ever deployed, so the
        equipment record moves `ASSIGNED → VOIDED` with `settlement_cents` at zero and
        `settlement_basis` recorded as `NONE`; there is nothing to return and nothing to bill."
        PRD 3.8: "Cancelling from `PENDING_INSTALL` additionally cancels the visit: every work
        order for the account whose `status` is `SCHEDULED`, `EXCEPTION_PENDING` or
        `RESURVEY_REQUIRED` moves to `CANCELLED`."
        PRD 3.8: "The sector's `sold_mbps` falls by the `downstream_mbps` of the account's
        current plan, and `committed_mbps`, `oversubscription_ratio`,
        `remaining_allowance_mbps` and `capacity_posture` are recomputed."
        PRD 3.8: "The account's `settlement_balance_cents` is the sum of `settlement_cents`
        over its equipment records whose `status` is `RETURNED`, `UNRETURNED_BILLED` or
        `VOIDED`."

        Design: Corner/state_machines/cancel_from_pending_install_voids_the_assignment_and_cancels_the_open_work_order
        """
        scenario = setup_scheduled_work_order()
        assert scenario["subscriber"]["service_status"] == "PENDING_INSTALL"
        assert scenario["work_order"]["status"] == "SCHEDULED"
        assert scenario["assignment"]["status"] == "ASSIGNED", (
            "the radio was minted with the account and never deployed, got "
            f"{scenario['assignment']['status']!r}"
        )

        response = api.change_subscriber_status(
            scenario["subscriber"]["id"],
            {"to_status": "CANCELLED", "reason": "customer changed their mind before installation"},
            billing_admin,
        )
        cancelled = validate_success(response, 200)

        assert cancelled["service_status"] == "CANCELLED", f"got {cancelled['service_status']!r}"
        assert is_iso8601_timestamp(cancelled.get("cancelled_at", "")), (
            f"cancelled_at must be an ISO 8601 stamp, got {cancelled.get('cancelled_at')!r}"
        )
        assert cancelled["cancelled_at"].startswith(CLOCK_AT_STARTUP), (
            "cancelled_at is stamped from the logical clock, still at its startup reading, got "
            f"{cancelled['cancelled_at']!r}"
        )
        assert cancelled["settlement_balance_cents"] == 0, (
            "the VOIDED record is counted by the balance but settles at zero, got "
            f"{cancelled['settlement_balance_cents']}"
        )
        assert cancelled["equipment_monthly_charge_cents"] == 0, (
            f"nothing was ever deployed, so nothing accrues, got "
            f"{cancelled['equipment_monthly_charge_cents']}"
        )

        work_order = get_work_order(scenario["work_order"]["id"])
        assert work_order["status"] == "CANCELLED", (
            f"the open SCHEDULED visit is cancelled with the account, got {work_order['status']!r}"
        )

        assignment = get_assignment_for_subscriber(scenario["subscriber"]["id"])
        assert assignment["status"] == "VOIDED", (
            "cancelling before any install takes the radio down the VOIDED branch rather than "
            f"RETURN_PENDING, got {assignment['status']!r}"
        )
        assert assignment["settlement_cents"] == 0, f"got {assignment['settlement_cents']}"
        assert assignment["settlement_basis"] == "NONE", (
            f"got {assignment.get('settlement_basis')!r}"
        )
        assert assignment.get("deployed_at") is None, f"got {assignment.get('deployed_at')!r}"
        assert assignment.get("return_due_at") is None, (
            "there is nothing to return, so no return window opens, got "
            f"{assignment.get('return_due_at')!r}"
        )
        assert assignment.get("returned_at") is None, f"got {assignment.get('returned_at')!r}"

        sector = get_sector(scenario["sector"]["id"])
        assert sector["sold_mbps"] == 0, (
            "the cancellation hands back all 50 Mbps the plan occupied, got "
            f"{sector['sold_mbps']}"
        )
        assert sector["held_mbps"] == 0, (
            f"the reservation was consumed at signing, got {sector['held_mbps']}"
        )
        assert sector["committed_mbps"] == 0, f"got {sector['committed_mbps']}"
        assert sector["oversubscription_ratio"] == pytest.approx(0.0, abs=0.0005), (
            f"an empty ledger carries a ratio of 0.000, got {sector['oversubscription_ratio']}"
        )
        assert sector["capacity_posture"] == "OPEN", (
            "an empty sector on a tower with accepted transport is OPEN, got "
            f"{sector['capacity_posture']!r}"
        )


class TestTruckRollMachine:
    def test_second_survey_on_an_approved_mount_is_refused(self, api):
        """PRD 3.7: "Straight to an approved mount.** When `field_los_margin_m` is at or above
        zero, `recommended_mast_height_m` is at or below 12.0, and `recommended_mounting_type`
        is `WALL_BRACKET` or `NON_PEN_ROOF_TRIPOD`, the work order moves `SCHEDULED →
        MOUNT_APPROVED` and `approved_mounting_type` is set equal to
        `recommended_mounting_type`."
        PRD 3.7: "The survey is permitted only from `SCHEDULED`; a survey submitted against a
        work order in any other status is refused with `ERR_WORK_ORDER_STATE_INVALID`."
        PRD 3.7: "All four outcomes set `field_los_margin_m`, `recommended_mast_height_m` and
        `surveyed_by_user_id`."

        Design: Corner/state_machines/second_survey_on_a_mount_approved_work_order_is_rejected
        """
        scenario = setup_scheduled_work_order()
        surveyed = survey_work_order(
            scenario["work_order"]["id"],
            measured_tree_line_height_m=3.0,
            measured_roof_height_m=4.0,
            structure_penetration_allowed=True,
        )
        assert surveyed["status"] == "MOUNT_APPROVED", (
            "a 2.5 m tripod is a light structure the technician may erect on their own "
            f"authority, got {surveyed['status']!r}"
        )
        assert surveyed["field_los_margin_m"] == pytest.approx(28.5, abs=0.05), (
            "the 1245.0 m antenna clears the 1216.5 m requirement by 28.5 m, got "
            f"{surveyed['field_los_margin_m']}"
        )
        assert surveyed["recommended_mast_height_m"] == pytest.approx(2.5, abs=0.05), (
            f"got {surveyed['recommended_mast_height_m']}"
        )
        assert surveyed["recommended_mounting_type"] == "NON_PEN_ROOF_TRIPOD"
        assert surveyed["approved_mounting_type"] == "NON_PEN_ROOF_TRIPOD"
        assert surveyed["surveyed_by_user_id"] == SURVEYOR_USER_ID, (
            f"got {surveyed.get('surveyed_by_user_id')!r}"
        )
        assert surveyed["version"] == 2, (
            "the work order was created at version 1 and the survey is its first mutation, got "
            f"{surveyed['version']}"
        )

        second_tech = make_field_tech_headers("tech-1002")
        response = api.survey_work_order(
            scenario["work_order"]["id"],
            {
                "measured_tree_line_height_m": 1.5,
                "measured_roof_height_m": 4.0,
                "structure_penetration_allowed": True,
            },
            second_tech,
        )
        validate_error(response, ApiErrorId.ERR_WORK_ORDER_STATE_INVALID)

        after = get_work_order(scenario["work_order"]["id"])
        assert after["status"] == "MOUNT_APPROVED", (
            f"the refused survey leaves the visit MOUNT_APPROVED, got {after['status']!r}"
        )
        assert after["field_los_margin_m"] == pytest.approx(28.5, abs=0.05), (
            "the first survey's findings are preserved rather than overwritten by the refused "
            f"measurements, got {after['field_los_margin_m']}"
        )
        assert after["recommended_mast_height_m"] == pytest.approx(2.5, abs=0.05), (
            f"got {after['recommended_mast_height_m']}"
        )
        assert after["recommended_mounting_type"] == "NON_PEN_ROOF_TRIPOD", (
            f"got {after['recommended_mounting_type']!r}"
        )
        assert after["approved_mounting_type"] == "NON_PEN_ROOF_TRIPOD", (
            f"got {after['approved_mounting_type']!r}"
        )
        assert after["surveyed_by_user_id"] == SURVEYOR_USER_ID, (
            "the refused survey does not restamp the surveying technician, got "
            f"{after['surveyed_by_user_id']!r}"
        )
        assert after["version"] == 2, f"got {after['version']}"
        assert_no_mutation(surveyed, after, entity="work order after a refused survey")

    def test_third_resurvey_request_at_the_loop_bound_is_refused(self, api):
        """PRD 3.7: "Request a resurvey** moves the work order `EXCEPTION_PENDING →
        RESURVEY_REQUIRED` and records `exception_approved_by_user_id`. It is permitted only
        while `resurvey_count` is strictly below the resurvey limit of 2, else the decision is
        refused with `ERR_RESURVEY_LIMIT_REACHED`."
        PRD 3.7: "The work order must be in `RESURVEY_REQUIRED`, else
        `ERR_WORK_ORDER_STATE_INVALID`, and `resurvey_count` must be at or below the resurvey
        limit of 2, else `ERR_RESURVEY_LIMIT_REACHED`. Observe the deliberate asymmetry with
        the exception path: requesting a further resurvey demands `resurvey_count` **strictly
        below** 2, whereas re-booking a resurvey that has already been granted demands only
        that it be **at or below** 2."
        PRD 3.7: "Sent back for a resurvey.** When `field_los_margin_m` is at or above zero,
        `recommended_mast_height_m` is at or below 12.0, `recommended_mounting_type` is
        `ROOF_MAST_GUYED` and `structure_penetration_allowed` is false, the work order moves
        `SCHEDULED → RESURVEY_REQUIRED` and `resurvey_count` is increased by one."

        Design: Corner/state_machines/resurvey_request_at_the_loop_bound_returns_resurvey_limit_reached
        """
        scenario = setup_scheduled_work_order()
        work_order_id = scenario["work_order"]["id"]

        first = survey_work_order(
            work_order_id,
            measured_tree_line_height_m=5.5,
            measured_roof_height_m=4.0,
            structure_penetration_allowed=True,
        )
        assert first["status"] == "EXCEPTION_PENDING", (
            "a 5.0 m guyed mast on a roof the householder permits us to bolt through needs an "
            f"engineer's sign-off, got {first['status']!r}"
        )
        assert first["recommended_mounting_type"] == "ROOF_MAST_GUYED", (
            f"got {first['recommended_mounting_type']!r}"
        )
        assert first["resurvey_count"] == 0, f"got {first['resurvey_count']}"

        sent_back = decide_exception(
            work_order_id, "REQUEST_RESURVEY", note="Re-measure the tree line"
        )
        assert sent_back["status"] == "RESURVEY_REQUIRED", f"got {sent_back['status']!r}"
        assert sent_back["resurvey_count"] == 1, (
            f"the first granted resurvey takes the counter to 1, got {sent_back['resurvey_count']}"
        )

        reschedule_work_order(work_order_id, scheduled_at="2026-08-09T15:00:00Z")
        second = survey_work_order(
            work_order_id,
            measured_tree_line_height_m=5.5,
            measured_roof_height_m=4.0,
            structure_penetration_allowed=False,
        )
        assert second["status"] == "RESURVEY_REQUIRED", (
            "the geometry demands a bolted-through mast the premise forbids, so the visit is "
            f"re-planned rather than escalated, got {second['status']!r}"
        )
        assert second["resurvey_count"] == 2, (
            f"the survey-driven resurvey takes the counter to 2, got {second['resurvey_count']}"
        )

        rebooked = reschedule_work_order(work_order_id, scheduled_at="2026-08-16T15:00:00Z")
        assert rebooked["status"] == "SCHEDULED", (
            "re-booking demands only that resurvey_count be at or below 2, so a work order "
            f"sitting at exactly 2 may still be re-booked, got {rebooked['status']!r}"
        )
        assert rebooked["resurvey_count"] == 2, (
            "the count is incremented when the resurvey is ordered, not when the visit is "
            f"booked, got {rebooked['resurvey_count']}"
        )

        third = survey_work_order(
            work_order_id,
            measured_tree_line_height_m=5.5,
            measured_roof_height_m=4.0,
            structure_penetration_allowed=True,
        )
        assert third["status"] == "EXCEPTION_PENDING", f"got {third['status']!r}"
        assert third["resurvey_count"] == 2, (
            f"a survey that escalates does not move the counter, got {third['resurvey_count']}"
        )

        response = api.decide_exception(
            work_order_id,
            {"decision": "REQUEST_RESURVEY", "note": "third attempt"},
            DECIDING_ENGINEER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_RESURVEY_LIMIT_REACHED)

        after = get_work_order(work_order_id)
        assert after["status"] == "EXCEPTION_PENDING", (
            "the refused decision leaves the visit awaiting an engineering decision rather "
            f"than failing it, got {after['status']!r}"
        )
        assert after["resurvey_count"] == 2, (
            f"the refused decision grants no further resurvey, got {after['resurvey_count']}"
        )
        assert after["recommended_mounting_type"] == "ROOF_MAST_GUYED", (
            f"got {after['recommended_mounting_type']!r}"
        )
        assert after["recommended_mast_height_m"] == pytest.approx(5.0, abs=0.05), (
            "the 1219.0 m requirement over a 1214.0 m roof needs 5.0 m of mast, got "
            f"{after['recommended_mast_height_m']}"
        )
        assert after["field_los_margin_m"] == pytest.approx(26.0, abs=0.05), (
            "the 1245.0 m antenna clears the 1219.0 m requirement by 26.0 m, got "
            f"{after['field_los_margin_m']}"
        )
        assert after.get("approved_mounting_type") is None, (
            "no band was ever approved on this visit, got "
            f"{after.get('approved_mounting_type')!r}"
        )
        assert_no_mutation(third, after, entity="work order after a refused resurvey request")


class TestOutageClosure:
    def test_closing_an_already_closed_outage_is_refused(self, api, network_engineer):
        """PRD 3.9: "The outage must be in `OPEN` status, and closing one already `CLOSED` is
        refused with `ERR_OUTAGE_ALREADY_CLOSED`."
        PRD 3.9: "Closure stores `ended_at` and `peak_wind_mph`, computes `duration_minutes` as
        the whole minutes between the two instants with any fractional minute discarded, and
        fixes `sla_excluded`. `CLOSED` is terminal."
        PRD 3.9: "A `POWER`, `BACKHAUL` or `EQUIPMENT` outage is never excluded; those are the
        operator's own plant."
        PRD 3.9: "Note that a tower need not be in any particular `status` to have an outage
        recorded against it; a tower in `MAINTENANCE` is precisely where planned outages are
        expected."

        Design: Corner/state_machines/repeated_outage_closure_returns_outage_already_closed
        """
        tower = create_tower()
        assert tower["status"] == "PLANNED", (
            f"a PLANNED site is enough to log an outage against, got {tower['status']!r}"
        )
        outage = create_outage(tower["id"], cause="POWER", started_at="2026-08-05T00:00:00Z")
        assert outage["status"] == "OPEN", f"got {outage['status']!r}"

        closed = close_outage(outage["id"], ended_at="2026-08-05T21:09:00Z")
        assert closed["status"] == "CLOSED", f"got {closed['status']!r}"
        assert closed["duration_minutes"] == 1269, (
            "21 hours and 9 minutes is 1269 whole minutes, got "
            f"{closed['duration_minutes']}"
        )
        assert closed["sla_excluded"] is False, (
            f"a POWER outage is never excluded, got {closed['sla_excluded']!r}"
        )
        assert closed["version"] == 2, (
            "the outage was created at version 1 and the closure is its first mutation, got "
            f"{closed['version']}"
        )

        response = api.close_outage_event(
            outage["id"], {"ended_at": "2026-08-06T00:00:00Z"}, network_engineer
        )
        validate_error(response, ApiErrorId.ERR_OUTAGE_ALREADY_CLOSED)

        after = get_outage(outage["id"])
        assert after["status"] == "CLOSED", f"CLOSED is terminal, got {after['status']!r}"
        assert after["ended_at"].startswith("2026-08-05T21:09:00"), (
            "the refused retry does not overwrite the instant fixed by the first closure, got "
            f"{after['ended_at']!r}"
        )
        assert after["duration_minutes"] == 1269, (
            "the window is not silently re-derived from the longer interval the retry asked "
            f"for, got {after['duration_minutes']}"
        )
        assert after["sla_excluded"] is False, f"got {after['sla_excluded']!r}"
        assert after["version"] == 2, (
            f"a refused closure is not a mutation, got version {after['version']}"
        )
        assert_no_mutation(closed, after, entity="closed outage")
