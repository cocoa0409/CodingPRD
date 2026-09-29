"""Initial states, legal transitions and the transitions each state refuses."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_1,
    ERR_ANCILLARY_STATE_INVALID,
    ERR_BAG_STATE_INVALID,
    ERR_COMPLAINT_STATE_INVALID,
    ERR_REPORT_STATE_INVALID,
    ERR_SEGMENT_STATE_INVALID,
    OFFICER_HEADERS,
    OPS_HEADERS,
    acknowledge,
    add_ancillary,
    add_checked_bag,
    answer,
    assert_activity_types,
    assert_booking_ledger,
    assert_cents,
    assert_common_fields,
    assert_hours,
    assert_instant,
    assert_list_meta,
    assert_null,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_obligation_deadlines,
    assert_segment_state,
    booking_version,
    build_world,
    cancel_segment,
    create_policy_profile,
    delay_segment,
    factories as f,
    file_complaint,
    list_activities,
    obligations_with_meta,
    open_report,
    read_ancillary,
    read_bag,
    read_booking,
    read_complaint,
    read_denied_boarding,
    read_passenger,
    read_profile,
    read_segment,
    record_operation,
    sole_obligation,
)


def _reports_of(api, profile_id):
    return validate_paginated(api.list_policy_profile_reports(profile_id, ADMIN_HEADERS))


def _report_row(api, profile_id, report_id):
    rows, _ = _reports_of(api, profile_id)
    for row in rows:
        if row["id"] == report_id:
            return row
    raise AssertionError(f"report {report_id} not listed on its profile")


# ─── Initial states ───────────────────────────────────


class TestInitialStates:
    def test_a_new_ancillary_purchase_is_pending_delivery(self, api):
        """The charge lands on the collected side while the service is still owed.

        PRD §3.3: "A new purchase begins with `delivery_status` reading `PENDING_DELIVERY`
        and `refund_obligation_created` false, and recording it refreshes the booking's
        `collected_total_cents` and advances the booking's `version` by 1 — the charge enters
        the collected-money side of the ledger the moment it is recorded, whether or not the
        service is ever rendered."

        Design: Corner/state_machines/ancillary_purchase_initial_state_is_pending_delivery
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])

        purchase = validate_success(
            api.create_ancillary_purchase(
                f.ancillary_payload(
                    world.booking["id"], world.segments[0]["id"], "ENTERTAINMENT", 1900
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert purchase["delivery_status"] == "PENDING_DELIVERY"
        assert_null(purchase["non_provision_reason"], "non_provision_reason")
        assert purchase["refund_obligation_created"] is False
        assert_common_fields(purchase, expected_version=1)
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            collected_total_cents=51900,
            total_refund_obligated_cents=0,
        )

    def test_a_new_obligation_sits_at_the_origin_of_both_axes(self, api):
        """Election and settlement each start unmoved, and no bonus exists yet.

        PRD §3.6: "A newly minted obligation begins with `election_status` reading
        `PENDING_ELECTION`, `settlement_status` reading `UNSETTLED`,
        `settlement_attempt_count` at 0, `deadline_breached` false, and, for a direct create,
        `created_by_user_id` set from the caller's `X-User-ID`; obligations minted by a
        cascade leave `created_by_user_id` null."

        PRD §3.6: "Step four persists the row with its `gross_entitlement_cents`,
        `headroom_at_creation_cents` and `amount_cents`, with `credit_bonus_cents` at 0 and
        `payable_total_cents` equal to `amount_cents` — the goodwill bonus is added later, at
        election, not now."

        Design: Corner/state_machines/refund_obligation_initial_state_pending_election_and_unsettled
        """
        world = build_world(api, total_fare_cents=50000)
        bag = add_checked_bag(
            api,
            world.booking["id"],
            "BAG0000001",
            4500,
            "2026-08-10T13:00:00Z",
            "2026-08-10T21:00:00Z",
        )
        validate_success(
            api.resolve_checked_bag(
                bag["id"], f.bag_delivered_payload("2026-08-11T05:00:00Z"), OFFICER_HEADERS
            )
        )
        stored_bag = read_bag(api, bag["id"], world.booking["id"])
        assert stored_bag["status"] == "DELIVERED_ON_TIME"
        assert_hours(stored_bag["delivery_delay_hours"], 8.0)

        obligation = validate_success(
            api.create_refund_obligation(
                f.obligation_payload(
                    world.booking["id"],
                    booking_version(api, world.booking["id"]),
                    "BAGGAGE_FEE",
                    "REQUEST_BASED",
                    checked_bag_id=bag["id"],
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert_obligation_axes(
            obligation,
            election_status="PENDING_ELECTION",
            election_source=None,
            settlement_status="UNSETTLED",
            settlement_method=None,
            settlement_attempt_count=0,
        )
        assert obligation["variant_applied"] == "FEE_FACE_VALUE"
        assert_obligation_amounts(
            obligation,
            amount_cents=4500,
            credit_bonus_cents=0,
            payable_total_cents=4500,
            headroom_at_creation_cents=54500,
        )
        assert_obligation_deadlines(obligation, deadline_breached=False)
        assert_common_fields(obligation, expected_version=1)

    def test_a_new_tarmac_event_is_delay_active_with_its_deadline_resolved(self, api):
        """The domestic deadline is fixed at creation and no minutes are counted yet.

        PRD §3.5: "A new event begins in `DELAY_ACTIVE` with `interval_end_utc` null,
        `tarmac_minutes` at 0 and `is_violation` false, and — importantly — with its
        `deadline_minutes` resolved and frozen at creation time from the leg's `is_international`
        flag and the booking's pinned policy profile: the international deplaning deadline for an
        international leg, the domestic one otherwise."

        Design: Corner/state_machines/tarmac_delay_event_initial_state_is_delay_active
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])

        event = validate_success(
            api.create_tarmac_delay_event(
                f.tarmac_event_payload(
                    world.segments[0]["id"], "2026-08-10T12:00:00Z", "DEPARTURE"
                ),
                OPS_HEADERS,
            ),
            201,
        )

        assert event["status"] == "DELAY_ACTIVE"
        assert_null(event["interval_end_utc"], "interval_end_utc")
        assert event["tarmac_minutes"] == 0
        assert event["deadline_minutes"] == 180
        assert event["is_violation"] is False
        assert_null(event["exemption_reason"], "exemption_reason")
        assert_null(event["report_reference"], "report_reference")
        assert_segment_state(
            read_segment(api, world.segments[0]["id"]), cumulative_tarmac_minutes=0
        )

    def test_a_new_complaint_is_received_with_both_statutory_clocks_derived(self, api):
        """Thirty days to acknowledge, sixty to answer a non-disability matter.

        PRD §3.8: "`ack_due_utc` is the profile's acknowledgement window added to
        `received_at_utc` — 30 days by default, for every category alike."

        PRD §3.8: "A newly filed complaint sits in `RECEIVED` with `info_requested_count` and
        `reopen_count` at 0 and both `ack_breached` and `answer_breached` false, appends an
        activity row of type `RECEIVED` to its trail, and refreshes the passenger's
        `open_complaint_count`, advancing the passenger's `version` by 1."

        Design: Corner/state_machines/consumer_complaint_initial_state_received_with_both_deadlines
        """
        world = build_world(api, total_fare_cents=50000)

        complaint = validate_success(
            api.create_consumer_complaint(
                f.complaint_payload(
                    world.booking["id"],
                    "REFUND",
                    "EMAIL",
                    "2026-08-05T09:00:00Z",
                    "Refund never arrived.",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert complaint["status"] == "RECEIVED"
        assert_instant(complaint["ack_due_utc"], "2026-09-04T09:00:00Z")
        assert_instant(complaint["answer_due_utc"], "2026-10-04T09:00:00Z")
        assert complaint["info_requested_count"] == 0
        assert complaint["reopen_count"] == 0
        assert complaint["ack_breached"] is False
        assert complaint["answer_breached"] is False
        assert read_passenger(api, world.passenger["id"])["open_complaint_count"] == 1

    def test_a_new_denied_boarding_record_computes_only_its_substitute_delay(self, api):
        """Ninety minutes late is measured at once; every money field waits for finalize.

        PRD §3.4: "A newly recorded incident sits in `RECORDED` with
        `statutory_compensation_cents` at 0, `compensation_cents` at 0 and
        `effective_category` unset, and with `substitute_delay_minutes` computed immediately
        as the difference between the `substitute_arrival_utc` and the leg's
        `scheduled_arrival_utc` in whole minutes with the remainder dropped, never below 0."

        Design: Corner/state_machines/denied_boarding_record_initial_state_recorded_with_zero_compensation
        """
        world = build_world(api, total_fare_cents=60000, segment_fares=[60000])

        record = validate_success(
            api.create_denied_boarding_record(
                f.denied_boarding_payload(
                    world.booking["id"],
                    world.segments[0]["id"],
                    "INVOLUNTARY",
                    45000,
                    "2026-08-10T15:30:00Z",
                    oversale_confirmed=True,
                    written_disclosure_provided=False,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert record["status"] == "RECORDED"
        assert record["substitute_delay_minutes"] == 90
        assert_cents(
            record["statutory_compensation_cents"], 0, "statutory_compensation_cents"
        )
        assert_cents(record["compensation_cents"], 0, "compensation_cents")
        assert_null(record["effective_category"], "effective_category")
        assert_null(record["finalized_at_utc"], "finalized_at_utc")
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=0
        )


# ─── Legal transitions that move money ────────────────


class TestDisruptionTransitions:
    def test_a_four_hour_delay_moves_one_leg_and_mints_the_itinerary_refund(self, api):
        """The delayed leg alone changes state; the refund values the whole ticket.

        PRD §3.2: "Declaring a delay drives the leg `SCHEDULED → DELAYED`, sets
        `disruption_type` to `DELAY`, records `revised_arrival_utc`, stamps
        `disruption_declared_at_utc` from the supplied `declared_at_utc`, and advances the
        leg's `version` by 1."

        PRD §3.2: "When `is_significant_delay` becomes true and no non-voided fare
        obligation already points at this leg, the declaration mints one refund obligation for
        the leg on a `FARE` basis in proactive issuance mode, valued by the proactive
        full-itinerary rule of §3.6, and then recomputes the booking's ledger fields and
        advances the booking's `version` by 1."

        PRD §3.6: "In proactive mode the variant is `PROACTIVE_FULL_ITINERARY`: when the
        booking's `travel_commenced` is false, `gross_entitlement_cents` is the booking's whole
        `total_fare_cents`; when travel has commenced, it is the sum of `segment_fare_cents`
        over the booking's legs whose `status` is `SCHEDULED`, `DELAYED`, `CANCELLED` or
        `DISRUPTED_UNUSED`, added in ascending `sequence_index` order with no intermediate
        rounding since each per-leg fare is already whole cents."

        Design: Corner/state_machines/significant_delay_declaration_moves_segment_scheduled_to_delayed
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])

        delay_segment(
            api, world.segments[0]["id"], "2026-08-10T18:00:00Z", "2026-08-10T09:00:00Z"
        )

        assert_segment_state(
            read_segment(api, world.segments[0]["id"]),
            status="DELAYED",
            disruption_type="DELAY",
            revised_arrival_utc="2026-08-10T18:00:00Z",
            delay_minutes=240,
            is_significant_delay=True,
            disruption_declared_at_utc="2026-08-10T09:00:00Z",
        )
        assert_segment_state(read_segment(api, world.segments[1]["id"]), status="SCHEDULED")

        rows, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 1, False)
        obligation = rows[0]
        assert obligation["basis"] == "FARE"
        assert obligation["issuance_mode"] == "PROACTIVE"
        assert obligation["variant_applied"] == "PROACTIVE_FULL_ITINERARY"
        assert_obligation_amounts(obligation, amount_cents=90000)
        assert_obligation_deadlines(
            obligation,
            obligation_start_utc="2026-08-10T09:00:00Z",
            deadline_utc="2026-08-17T09:00:00Z",
            election_deadline_utc="2026-08-15T09:00:00Z",
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=90000,
            disruption_posture="REFUND_OBLIGATED",
        )

    def test_restoring_the_schedule_wipes_the_delay_facts_but_keeps_the_debt(self, api):
        """The row survives the walk-back so the carrier must pay or void it explicitly.

        PRD §3.2: "Restoration clears `disruption_type` back to `NONE`, sets
        `revised_arrival_utc` to null, resets `delay_minutes` to 0 and `is_significant_delay`
        to false, sets `disruption_declared_at_utc` to null, and advances the leg's `version`
        by 1; the booking's `disruption_posture` and `unused_segment_count` are recomputed and
        the booking's `version` advances by 1."

        PRD §3.2: "Crucially, restoration does **not** void any obligation the delay
        produced."

        Design: Corner/state_machines/restored_operation_returns_delayed_segment_to_scheduled_without_voiding_obligation
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[90000])
        delay_segment(
            api, world.segments[0]["id"], "2026-08-10T18:00:00Z", "2026-08-10T09:00:00Z"
        )

        record_operation(api, world.segments[0]["id"], "RESTORED", "2026-08-10T11:00:00Z")

        assert_segment_state(
            read_segment(api, world.segments[0]["id"]),
            status="SCHEDULED",
            disruption_type="NONE",
            revised_arrival_utc=None,
            delay_minutes=0,
            is_significant_delay=False,
            disruption_declared_at_utc=None,
        )
        rows, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 1, False)
        assert_obligation_axes(rows[0], settlement_status="UNSETTLED")
        assert_obligation_amounts(rows[0], amount_cents=90000)
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=90000,
            disruption_posture="REFUND_OBLIGATED",
            unused_segment_count=1,
        )

    def test_arrival_delivers_only_the_extras_bought_on_the_leg_that_flew(self, api):
        """A service flown as sold is delivered; the next leg's extra keeps waiting.

        PRD §3.2: "Arrival also bubbles downward: every ancillary purchase on that leg
        still in `PENDING_DELIVERY` becomes `DELIVERED`, because a service flown as sold is a
        service delivered, and no obligation is created for it."

        PRD §3.2: "Recording `ARRIVED` is accepted only from `DEPARTED` and requires
        `occurred_at_utc` strictly after `actual_departure_utc`; it writes
        `actual_arrival_utc`, moves the leg `DEPARTED → ARRIVED` — the leg's terminal state —
        and advances the leg's `version` by 1."

        Design: Corner/state_machines/arrival_bubbles_only_that_segments_pending_ancillaries_to_delivered
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])
        first_extra = add_ancillary(
            api, world.booking["id"], world.segments[0]["id"], "SEAT_SELECTION", 2000
        )
        second_extra = add_ancillary(
            api, world.booking["id"], world.segments[1]["id"], "ENTERTAINMENT", 3000
        )
        record_operation(api, world.segments[0]["id"], "DEPARTED", "2026-08-10T12:05:00Z")

        record_operation(api, world.segments[0]["id"], "ARRIVED", "2026-08-10T13:55:00Z")

        flown = read_segment(api, world.segments[0]["id"])
        assert_segment_state(flown, status="ARRIVED")
        assert_instant(flown["actual_arrival_utc"], "2026-08-10T13:55:00Z")
        delivered = read_ancillary(api, first_extra["id"])
        assert delivered["delivery_status"] == "DELIVERED"
        assert delivered["refund_obligation_created"] is False
        assert_null(delivered["non_provision_reason"], "non_provision_reason")
        assert read_ancillary(api, second_extra["id"])["delivery_status"] == "PENDING_DELIVERY"
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            travel_commenced=True,
            unused_segment_count=1,
            total_refund_obligated_cents=0,
            collected_total_cents=95000,
        )

    def test_the_cancellation_cascade_leaves_an_already_delivered_extra_alone(self, api):
        """Only the pending extra on the cancelled leg turns into money owed.

        PRD §3.2: "**Link two-b,** also caused by link one: every ancillary purchase
        attached to the cancelled leg whose `delivery_status` is `PENDING_DELIVERY` becomes
        `NOT_PROVIDED` with `non_provision_reason` set to `SERVICE_CANCELLED`, processed in
        ascending `created_at` order."

        PRD §3.2: "**Link three-b,** caused by link two-b: one refund obligation on an
        `ANCILLARY` basis in proactive issuance mode at fee face value is minted for each
        ancillary that just became `NOT_PROVIDED`, in the same ascending `created_at` order,
        each clamped against the headroom left by every obligation created earlier in this same
        request; each such ancillary's `refund_obligation_created` becomes true."

        Design: Corner/state_machines/cancellation_cascade_skips_already_delivered_ancillary
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])
        first_extra = add_ancillary(
            api, world.booking["id"], world.segments[0]["id"], "SEAT_SELECTION", 2000
        )
        second_extra = add_ancillary(
            api, world.booking["id"], world.segments[1]["id"], "ENTERTAINMENT", 3000
        )
        record_operation(api, world.segments[0]["id"], "DEPARTED", "2026-08-10T12:05:00Z")
        record_operation(api, world.segments[0]["id"], "ARRIVED", "2026-08-10T13:55:00Z")

        cancel_segment(api, world.segments[1]["id"], "2026-08-10T15:00:00Z")

        untouched = read_ancillary(api, first_extra["id"])
        assert untouched["delivery_status"] == "DELIVERED"
        assert untouched["refund_obligation_created"] is False
        cancelled_extra = read_ancillary(api, second_extra["id"])
        assert cancelled_extra["delivery_status"] == "NOT_PROVIDED"
        assert cancelled_extra["non_provision_reason"] == "SERVICE_CANCELLED"

        rows, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 2, False)
        by_basis = {row["basis"]: row for row in rows}
        assert_obligation_amounts(by_basis["FARE"], amount_cents=60000)
        assert_obligation_amounts(by_basis["ANCILLARY"], amount_cents=3000)
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=63000,
            travel_commenced=True,
            unused_segment_count=1,
            suppressed_obligation_count=0,
        )


class TestPaidExtraTransitions:
    def test_marking_a_seat_charge_unprovided_syncs_the_booking_ledger(self, api):
        """The face value becomes owed and the deadline reaches back to the failure.

        PRD §3.3: "Recording non-provision drives `PENDING_DELIVERY → NOT_PROVIDED`,
        stores the reason, advances the purchase's `version` by 1, and mints one refund
        obligation on an `ANCILLARY` basis in proactive issuance mode at fee face value — its
        gross entitlement is exactly the purchase's `amount_cents` — clamped to the booking's
        remaining headroom, with the obligation's clock start taken from the supplied
        `occurred_at_utc`."

        PRD §3.3: "The purchase's `refund_obligation_created` becomes true, the booking's
        `total_refund_obligated_cents`, `earliest_refund_deadline_utc` and
        `disruption_posture` are recomputed, and the booking's `version` advances by 1."

        Design: Corner/state_machines/mark_not_provided_syncs_booking_ledger_fields
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])
        extra = add_ancillary(
            api, world.booking["id"], world.segments[0]["id"], "SEAT_SELECTION", 2000
        )
        version_before = booking_version(api, world.booking["id"])

        marked = validate_success(
            api.mark_ancillary_not_provided(
                extra["id"],
                f.not_provided_payload("EQUIPMENT_SWAP", "2026-08-09T08:00:00Z"),
                OFFICER_HEADERS,
            )
        )

        assert marked["delivery_status"] == "NOT_PROVIDED"
        assert marked["refund_obligation_created"] is True
        booking = read_booking(api, world.booking["id"])
        assert_booking_ledger(
            booking,
            total_refund_obligated_cents=2000,
            collected_total_cents=52000,
            disruption_posture="REFUND_OBLIGATED",
            version=version_before + 1,
        )
        assert_instant(booking["earliest_refund_deadline_utc"], "2026-08-16T08:00:00Z")

    def test_a_lost_bag_owes_its_fee_back_with_no_delay_hours_recorded(self, api):
        """No delivery ever happened, so the hours stay zero and the fee is still owed.

        PRD §3.3: "A `DECLARED_LOST` resolution moves the bag `IN_TRANSIT →
        DECLARED_LOST`, stores `loss_declared_at_utc`, and leaves `delivery_delay_hours` at 0
        because no delivery ever occurred; the bag's `version` advances by 1."

        PRD §3.3: "It then mints the fee obligation on exactly the same terms as the
        late-delivery branch — a lost bag always owes its fee back, regardless of how many
        hours elapsed — with the obligation's clock start taken from `loss_declared_at_utc`
        since there is no delivery instant, and the booking's ledger fields are recomputed with
        the booking's `version` advancing by 1."

        Design: Corner/state_machines/declared_lost_bag_creates_fee_obligation_with_zero_delay_hours
        """
        world = build_world(api, total_fare_cents=50000)
        bag = add_checked_bag(
            api,
            world.booking["id"],
            "BAG0000001",
            4500,
            "2026-08-10T13:00:00Z",
            "2026-08-10T21:00:00Z",
        )

        validate_success(
            api.resolve_checked_bag(
                bag["id"], f.bag_lost_payload("2026-08-14T10:00:00Z"), OFFICER_HEADERS
            )
        )

        stored = read_bag(api, bag["id"], world.booking["id"])
        assert stored["status"] == "DECLARED_LOST"
        assert_null(stored["delivered_at_utc"], "delivered_at_utc")
        assert_instant(stored["loss_declared_at_utc"], "2026-08-14T10:00:00Z")
        assert_hours(stored["delivery_delay_hours"], 0.0)
        assert stored["fee_refund_obligated"] is True

        rows, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 1, False)
        obligation = rows[0]
        assert obligation["basis"] == "BAGGAGE_FEE"
        assert obligation["issuance_mode"] == "PROACTIVE"
        assert obligation["variant_applied"] == "FEE_FACE_VALUE"
        assert_obligation_amounts(obligation, amount_cents=4500)
        assert_obligation_deadlines(
            obligation,
            obligation_start_utc="2026-08-14T10:00:00Z",
            deadline_utc="2026-08-21T10:00:00Z",
        )
        booking = read_booking(api, world.booking["id"])
        assert_booking_ledger(
            booking, collected_total_cents=54500, total_refund_obligated_cents=4500
        )
        assert_instant(booking["earliest_refund_deadline_utc"], "2026-08-21T10:00:00Z")


class TestComplaintWorkflowTransitions:
    def test_acknowledging_then_answering_reaches_the_answered_state(self, api):
        """Two officer actions, two activity rows, and no money owed on the way.

        PRD §3.8: "Acknowledging supplies `acknowledged_at_utc` and drives `RECEIVED →
        ACKNOWLEDGED`; the instant must be at or after `received_at_utc`."

        PRD §3.8: "Each of the four appends an activity row of the matching type:
        `ACKNOWLEDGED`, `INFO_REQUESTED`, `ANSWERED` and `REOPENED` respectively."

        PRD §3.8: "**Link one:** the complaint moves to `ANSWERED` with its `disposition`,
        `answered_at_utc`, `accessibility_resolution_code` and `granted_amount_cents` stored,
        its `version` advanced by 1, an `ANSWERED` activity row appended and the passenger's
        `open_complaint_count` refreshed."

        Design: Corner/state_machines/complaint_acknowledge_then_answer_reaches_answered
        """
        world = build_world(api, total_fare_cents=50000)
        complaint = file_complaint(
            api,
            world.booking["id"],
            category="REFUND",
            channel="EMAIL",
            received_at_utc="2026-08-05T09:00:00Z",
            summary="Refund never arrived.",
        )

        acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")
        answer(api, complaint["id"], "2026-08-07T11:00:00Z", "POLICY_EXPLAINED")

        stored = read_complaint(api, complaint["id"])
        assert stored["status"] == "ANSWERED"
        assert_instant(stored["acknowledged_at_utc"], "2026-08-06T10:00:00Z")
        assert_instant(stored["answered_at_utc"], "2026-08-07T11:00:00Z")
        assert stored["ack_breached"] is False
        assert stored["answer_breached"] is False
        assert stored["version"] == 3
        assert_activity_types(
            list_activities(api, complaint["id"]), ["RECEIVED", "ACKNOWLEDGED", "ANSWERED"]
        )
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 0, False)

    def test_granting_a_refund_in_the_answer_mints_a_goodwill_obligation(self, api):
        """The grant is a request-based claim whose clock starts at the answer.

        PRD §3.8: "**Link two,** caused by link one and only when the disposition is
        `REFUND_GRANTED`: one refund obligation is minted on a `GOODWILL_GRANT` basis in
        **request-based** issuance mode under the variant `GOODWILL_GRANT_AMOUNT`, its gross
        entitlement being the `granted_amount_cents` just recorded, with all four source
        references left null and its clock start taken from `answered_at_utc`, and it is subject
        to the headroom rules of §3.6 — being request-based, a grant that exceeds the booking's
        remaining headroom is refused with `ERR_REFUND_EXCEEDS_HEADROOM` rather than quietly
        reduced."

        PRD §3.6: "A newly minted obligation begins with `election_status` reading
        `PENDING_ELECTION`, `settlement_status` reading `UNSETTLED`, `settlement_attempt_count`
        at 0, `deadline_breached` false, and, for a direct create, `created_by_user_id` set from
        the caller's `X-User-ID`; obligations minted by a cascade leave `created_by_user_id`
        null."

        PRD §2.11: "The posture is resolved in this order: it is `NORMAL` when the booking
        has no segments at all; otherwise, if the booking has at least one non-voided
        obligation, it is `CLOSED_OUT` when every obligation of the booking is settled or
        voided and `REFUND_OBLIGATED` when at least one is not; otherwise it is `DISRUPTED`
        when any of the booking's segments carries a disruption type other than none;
        otherwise `NORMAL`."

        Design: Corner/state_machines/refund_granted_answer_mints_goodwill_grant_obligation
        """
        world = build_world(api, total_fare_cents=50000)
        complaint = file_complaint(
            api,
            world.booking["id"],
            category="REFUND",
            channel="EMAIL",
            received_at_utc="2026-08-05T09:00:00Z",
            summary="Service shortfall.",
        )
        acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")

        answered = validate_success(
            api.answer_complaint(
                complaint["id"],
                f.answer_payload(
                    "2026-08-07T11:00:00Z", "REFUND_GRANTED", granted_amount_cents=12000
                ),
                OFFICER_HEADERS,
            )
        )

        assert answered["status"] == "ANSWERED"
        assert_cents(answered["granted_amount_cents"], 12000, "granted_amount_cents")
        obligation = sole_obligation(api, world.booking["id"])
        assert obligation["basis"] == "GOODWILL_GRANT"
        assert obligation["issuance_mode"] == "REQUEST_BASED"
        assert obligation["variant_applied"] == "GOODWILL_GRANT_AMOUNT"
        assert_obligation_amounts(
            obligation, amount_cents=12000, headroom_at_creation_cents=50000
        )
        assert_obligation_deadlines(
            obligation,
            obligation_start_utc="2026-08-07T11:00:00Z",
            deadline_utc="2026-08-14T11:00:00Z",
            election_deadline_utc="2026-08-12T11:00:00Z",
        )
        assert_null(obligation["created_by_user_id"], "created_by_user_id")
        booking = read_booking(api, world.booking["id"])
        # This booking carries no flight segments, so §2.11's very first clause pins the
        # recomputed posture at NORMAL — the obligation branch is only reached "otherwise".
        assert_booking_ledger(
            booking,
            total_refund_obligated_cents=12000,
            segment_count=0,
            disruption_posture="NORMAL",
        )
        assert_instant(booking["earliest_refund_deadline_utc"], "2026-08-14T11:00:00Z")


class TestDeniedBoardingRecategorization:
    def test_a_volunteer_who_saw_no_written_disclosure_is_recategorized(self, api):
        """The waiver is void, so the statutory ladder pays 775 dollars on a 600-dollar fare.

        PRD §3.4: "It stays `VOLUNTARY` only when the declared `category` is `VOLUNTARY`
        **and** `oversale_confirmed` is true **and** `written_disclosure_provided` is true; in
        every other combination it resolves to `INVOLUNTARY`."

        PRD §3.4: "When the declared and effective categories **differ** — most commonly a
        `VOLUNTARY` declaration whose `written_disclosure_provided` is false — the record moves
        `RECORDED → RECATEGORIZED` instead: `effective_category` is written as `INVOLUNTARY`,
        `compensation_cents` is set to `statutory_compensation_cents` and the agreed amount is
        ignored entirely, and the disclosure floor check is **not** applied on this branch, since
        there is no valid waiver left to measure."

        PRD §3.4: "Statutory denied-boarding compensation is **exempt from the booking's
        refund headroom entirely** — it is compensation for a service failure rather than a
        refund of money collected, so it is neither clamped by the headroom nor counted against
        it when later obligations compute theirs."

        Design: Corner/state_machines/voluntary_denied_boarding_without_disclosure_finalizes_as_recategorized
        """
        world = build_world(api, total_fare_cents=60000, segment_fares=[60000])
        record = validate_success(
            api.create_denied_boarding_record(
                f.denied_boarding_payload(
                    world.booking["id"],
                    world.segments[0]["id"],
                    "VOLUNTARY",
                    45000,
                    "2026-08-10T15:30:00Z",
                    oversale_confirmed=True,
                    written_disclosure_provided=False,
                    voluntary_agreed_amount_cents=40000,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        validate_success(
            api.finalize_denied_boarding_record(
                record["id"], f.finalize_payload("2026-08-10T16:00:00Z"), OFFICER_HEADERS
            )
        )

        stored = read_denied_boarding(api, record["id"])
        assert stored["status"] == "RECATEGORIZED"
        assert stored["effective_category"] == "INVOLUNTARY"
        assert stored["substitute_delay_minutes"] == 90
        assert_cents(
            stored["statutory_compensation_cents"], 77500, "statutory_compensation_cents"
        )
        assert_cents(stored["compensation_cents"], 77500, "compensation_cents")

        obligation = sole_obligation(api, world.booking["id"])
        assert obligation["basis"] == "DENIED_BOARDING"
        assert obligation["variant_applied"] == "INVOLUNTARY_STATUTORY"
        assert_obligation_amounts(obligation, amount_cents=77500)
        assert_obligation_deadlines(
            obligation,
            obligation_start_utc="2026-08-10T16:00:00Z",
            deadline_utc="2026-08-17T16:00:00Z",
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=77500,
            suppressed_obligation_count=0,
        )


class TestReportAmendmentCycle:
    def test_submitting_amending_and_resubmitting_returns_the_report_to_submitted(self, api):
        """The amendment cycle repeats indefinitely; a report has no terminal state.

        PRD §3.9: "Amending a `SUBMITTED` report moves it `SUBMITTED → AMENDING`,
        increases `amendment_count` by 1 and stores the supplied `amendment_reason`, advancing
        the report's `version` by 1; the supplied `amended_at_utc` must be at or after the
        report's `submitted_at_utc`, or `ERR_PERIOD_BOUNDS_INVALID`, and amending anything that
        is not `SUBMITTED` is `ERR_REPORT_STATE_INVALID`."

        PRD §3.9: "Submitting again from `AMENDING` recomputes all seven metrics from
        current data, refreezes them, refreshes `policy_version_pinned`, and returns the report
        to `SUBMITTED`, subject to the same open-complaint and submission-instant preconditions
        as the first submit."

        Design: Corner/state_machines/report_submit_amend_resubmit_walks_the_amendment_cycle
        """
        profile = create_policy_profile(api, "ZQ")
        report = open_report(
            api, profile["id"], "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z", 1
        )

        validate_success(
            api.submit_regulator_report(
                report["id"], f.submit_report_payload("2026-08-01T00:00:00Z"), ADMIN_HEADERS
            )
        )
        validate_success(
            api.amend_regulator_report(
                report["id"],
                f.amend_report_payload(
                    "2026-08-02T00:00:00Z", "Complaint reclassified after audit."
                ),
                ADMIN_HEADERS,
            )
        )
        resubmitted = validate_success(
            api.submit_regulator_report(
                report["id"], f.submit_report_payload("2026-08-03T00:00:00Z"), ADMIN_HEADERS
            )
        )

        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["amendment_count"] == 1
        assert resubmitted["amendment_reason"] == "Complaint reclassified after audit."
        assert_instant(resubmitted["submitted_at_utc"], "2026-08-03T00:00:00Z")
        assert resubmitted["submitted_by_user_id"] == ADMIN_1
        assert resubmitted["policy_version_pinned"] == 2
        assert resubmitted["complaint_count"] == 0
        assert resubmitted["tarmac_violation_count"] == 0
        assert resubmitted["version"] == 4
        assert read_profile(api, profile["id"])["version"] == 2


# ─── Transitions each state refuses ───────────────────


class TestRefusedSegmentTransitions:
    def test_a_leg_that_never_departed_cannot_arrive(self, api):
        """Arrival is reachable only from departure, so the scheduled leg stays put.

        PRD §3.2: "Recording `ARRIVED` is accepted only from `DEPARTED` and requires
        `occurred_at_utc` strictly after `actual_departure_utc`; it writes
        `actual_arrival_utc`, moves the leg `DEPARTED → ARRIVED` — the leg's terminal state —
        and advances the leg's `version` by 1."

        Design: Corner/state_machines/arrived_operation_on_never_departed_segment_rejected
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])

        refused = api.record_operation(
            world.segments[0]["id"],
            f.operation_payload("ARRIVED", "2026-08-10T14:05:00Z"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_SEGMENT_STATE_INVALID, 409)
        stored = read_segment(api, world.segments[0]["id"])
        assert_segment_state(stored, status="SCHEDULED")
        assert_null(stored["actual_arrival_utc"], "actual_arrival_utc")
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), travel_commenced=False
        )

    def test_the_second_leg_cannot_depart_while_the_first_is_still_scheduled(self, api):
        """An itinerary departs in order, so the downstream leg is refused.

        PRD §3.2: "Recording `DEPARTED` is accepted from `SCHEDULED` or from `DELAYED`,
        and additionally requires that every sibling leg with a smaller `sequence_index`
        already be in `DEPARTED`, `ARRIVED`, `CANCELLED` or `DISRUPTED_UNUSED` — an itinerary
        cannot depart its second leg while its first is still merely scheduled; otherwise
        `ERR_SEGMENT_STATE_INVALID`."

        Design: Corner/state_machines/out_of_sequence_departed_operation_rejected
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])

        refused = api.record_operation(
            world.segments[1]["id"],
            f.operation_payload("DEPARTED", "2026-08-10T16:05:00Z"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_SEGMENT_STATE_INVALID, 409)
        downstream = read_segment(api, world.segments[1]["id"])
        assert_segment_state(downstream, status="SCHEDULED")
        assert_null(downstream["actual_departure_utc"], "actual_departure_utc")
        assert_segment_state(read_segment(api, world.segments[0]["id"]), status="SCHEDULED")
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            travel_commenced=False,
            unused_segment_count=2,
        )

    def test_an_arrived_leg_accepts_no_further_disruption_declaration(self, api):
        """A flight that already landed cannot be cancelled after the fact.

        PRD §3.2: "A declaration is only accepted on a leg whose `status` is `SCHEDULED`
        or `DELAYED`; on a leg that has already been cancelled, has departed or has arrived,
        the request is rejected with `ERR_SEGMENT_STATE_INVALID`."

        Design: Corner/state_machines/arrived_segment_refuses_further_disruption_declaration
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])
        record_operation(api, world.segments[0]["id"], "DEPARTED", "2026-08-10T12:05:00Z")
        record_operation(api, world.segments[0]["id"], "ARRIVED", "2026-08-10T13:55:00Z")

        refused = api.declare_disruption(
            world.segments[0]["id"],
            f.cancellation_payload("2026-08-10T14:30:00Z"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_SEGMENT_STATE_INVALID, 409)
        assert_segment_state(
            read_segment(api, world.segments[0]["id"]),
            status="ARRIVED",
            disruption_type="NONE",
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=0,
            disruption_posture="NORMAL",
            unused_segment_count=0,
        )


class TestRefusedPaidExtraTransitions:
    def test_a_flown_legs_extras_cannot_be_marked_unprovided_by_hand(self, api):
        """The arrival bubble already settled the charge, so the manual route closes.

        PRD §3.3: "The purchase must be in `PENDING_DELIVERY`; a purchase already
        `DELIVERED` or already `NOT_PROVIDED` is refused with `ERR_ANCILLARY_STATE_INVALID`,
        and so is a purchase whose parent leg has already reached `ARRIVED`, because a flown
        leg's services are settled by the arrival bubble of §3.2 rather than by hand."

        Design: Corner/state_machines/mark_not_provided_after_arrival_rejected
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])
        extra = add_ancillary(
            api, world.booking["id"], world.segments[0]["id"], "SEAT_SELECTION", 2000
        )
        record_operation(api, world.segments[0]["id"], "DEPARTED", "2026-08-10T12:05:00Z")
        record_operation(api, world.segments[0]["id"], "ARRIVED", "2026-08-10T13:55:00Z")

        refused = api.mark_ancillary_not_provided(
            extra["id"],
            f.not_provided_payload("EQUIPMENT_SWAP", "2026-08-10T14:30:00Z"),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_ANCILLARY_STATE_INVALID, 409)
        stored = read_ancillary(api, extra["id"])
        assert stored["delivery_status"] == "DELIVERED"
        assert stored["refund_obligation_created"] is False
        assert_null(stored["non_provision_reason"], "non_provision_reason")
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=0
        )

    def test_a_bag_is_closed_out_exactly_once(self, api):
        """The on-time delivery stands and the second resolution changes nothing.

        PRD §3.3: "A bag is closed out exactly once, by supplying a `resolution` of
        either `DELIVERED` or `DECLARED_LOST`. The bag must be `IN_TRANSIT`; resolving an
        already-resolved bag is `ERR_BAG_STATE_INVALID`."

        Design: Corner/state_machines/resolve_on_already_delivered_bag_rejected
        """
        world = build_world(api, total_fare_cents=50000)
        bag = add_checked_bag(
            api,
            world.booking["id"],
            "BAG0000001",
            4500,
            "2026-08-10T13:00:00Z",
            "2026-08-10T21:00:00Z",
        )
        validate_success(
            api.resolve_checked_bag(
                bag["id"], f.bag_delivered_payload("2026-08-11T05:00:00Z"), OFFICER_HEADERS
            )
        )

        refused = api.resolve_checked_bag(
            bag["id"], f.bag_delivered_payload("2026-08-11T20:00:00Z"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_BAG_STATE_INVALID, 409)
        stored = read_bag(api, bag["id"], world.booking["id"])
        assert stored["status"] == "DELIVERED_ON_TIME"
        assert_instant(stored["delivered_at_utc"], "2026-08-11T05:00:00Z")
        assert_hours(stored["delivery_delay_hours"], 8.0)
        assert stored["fee_refund_obligated"] is False
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 0, False)


class TestRefusedComplaintAndReportTransitions:
    def test_an_answered_complaint_cannot_be_acknowledged_again(self, api):
        """Acknowledgement is reachable only from RECEIVED, so the trail stays at three rows.

        PRD §3.8: "Any of these chronology rules being violated is
        `ERR_ANSWER_BEFORE_RECEIPT` (HTTP 422), and an action attempted from the wrong status
        — acknowledging something not `RECEIVED`, requesting information on something not
        `ACKNOWLEDGED`, answering something that is neither `ACKNOWLEDGED` nor
        `INFO_REQUESTED`, or reopening something not `ANSWERED` — is
        `ERR_COMPLAINT_STATE_INVALID` (HTTP 409)."

        Design: Corner/state_machines/acknowledge_on_answered_complaint_rejected
        """
        world = build_world(api, total_fare_cents=50000)
        complaint = file_complaint(
            api,
            world.booking["id"],
            category="REFUND",
            channel="EMAIL",
            received_at_utc="2026-08-05T09:00:00Z",
            summary="Refund never arrived.",
        )
        acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")
        answer(api, complaint["id"], "2026-08-07T11:00:00Z", "POLICY_EXPLAINED")

        refused = api.acknowledge_complaint(
            complaint["id"], f.acknowledge_payload("2026-08-08T12:00:00Z"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_COMPLAINT_STATE_INVALID, 409)
        stored = read_complaint(api, complaint["id"])
        assert stored["status"] == "ANSWERED"
        assert_instant(stored["acknowledged_at_utc"], "2026-08-06T10:00:00Z")
        assert stored["version"] == 3
        assert_activity_types(
            list_activities(api, complaint["id"]), ["RECEIVED", "ACKNOWLEDGED", "ANSWERED"]
        )

    def test_a_draft_report_cannot_be_amended(self, api):
        """There is nothing filed yet to correct, so the draft is left untouched.

        PRD §3.9: "Amending a `SUBMITTED` report moves it `SUBMITTED → AMENDING`,
        increases `amendment_count` by 1 and stores the supplied `amendment_reason`, advancing
        the report's `version` by 1; the supplied `amended_at_utc` must be at or after the
        report's `submitted_at_utc`, or `ERR_PERIOD_BOUNDS_INVALID`, and amending anything that
        is not `SUBMITTED` is `ERR_REPORT_STATE_INVALID`."

        Design: Corner/state_machines/amend_on_draft_report_rejected
        """
        profile = create_policy_profile(api, "ZQ")
        report = open_report(
            api, profile["id"], "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z", 1
        )

        refused = api.amend_regulator_report(
            report["id"],
            f.amend_report_payload("2026-08-02T00:00:00Z", "Premature amendment."),
            ADMIN_HEADERS,
        )

        validate_error(refused, ERR_REPORT_STATE_INVALID, 409)
        stored = _report_row(api, profile["id"], report["id"])
        assert stored["status"] == "DRAFT"
        assert stored["amendment_count"] == 0
        assert_null(stored["amendment_reason"], "amendment_reason")
        assert stored["version"] == 1

    def test_a_submitted_report_cannot_be_submitted_twice(self, api):
        """Refiling has to go through an amendment, so the first filing instant stands.

        PRD §3.9: "The report must be in `DRAFT` or `AMENDING`, or the answer is
        `ERR_REPORT_STATE_INVALID`."

        Design: Corner/state_machines/second_submit_on_submitted_report_rejected
        """
        profile = create_policy_profile(api, "ZQ")
        report = open_report(
            api, profile["id"], "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z", 1
        )
        validate_success(
            api.submit_regulator_report(
                report["id"], f.submit_report_payload("2026-08-01T00:00:00Z"), ADMIN_HEADERS
            )
        )

        refused = api.submit_regulator_report(
            report["id"], f.submit_report_payload("2026-08-05T00:00:00Z"), ADMIN_HEADERS
        )

        validate_error(refused, ERR_REPORT_STATE_INVALID, 409)
        stored = _report_row(api, profile["id"], report["id"])
        assert stored["status"] == "SUBMITTED"
        assert_instant(stored["submitted_at_utc"], "2026-08-01T00:00:00Z")
        assert stored["version"] == 2
        assert read_profile(api, profile["id"])["report_count"] == 1
