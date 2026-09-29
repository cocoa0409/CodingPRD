"""Constraint checks: the three uniqueness scopes, the two conditional rules, the
aggregate ceilings, the reduction window boundary, and two precedence pairs."""

from test_helpers import (
    COMPLIANCE,
    COORDINATOR,
    assemble_block,
    attrition_reduction_payload,
    carve_sub_block,
    carve_sub_block_payload,
    contract_block_payload,
    create_attendee_payload,
    create_event_payload,
    create_reservation_payload,
    import_attendee,
    make_attendee_headers,
    make_hotel_manager_headers,
    poaching_incident_payload,
    read_block,
    record_incident,
    record_rogue_vendor,
    register_event,
    register_hotel,
    set_clock,
    set_hotel_standing,
    setup_contracted_block,
    setup_housing_program,
    setup_open_block,
    submit_terms,
    validate_error,
    validate_paginated,
    validate_success,
)

WINTER_EXPO = {
    "name": "Winter Expo",
    "code": "WEX26",
    "event_start_date": "2026-11-10",
    "event_end_date": "2026-11-13",
    "cutoff_date": "2026-10-15",
    "attrition_deadline_date": "2026-10-01",
}


class TestEventCodeUniqueness:
    def test_a_second_event_reusing_the_code_is_refused(self, api):
        """PRD §3.1: "a bureau-facing `code` of between 3 and 16 uppercase
        characters that must be unique across all registered events — a collision is
        rejected with `ERR_EVENT_CODE_DUPLICATE`."
        PRD §2.10: "`ERR_EVENT_CODE_DUPLICATE` (409) when a registered event already
        uses the supplied `code`"

        Design: Corner/validations/duplicate_event_code_returns_conflict
        """
        first = register_event()
        assert first["code"] == "SUM26"

        collision = create_event_payload(
            name="Other Summit",
            code="SUM26",
            event_start_date="2026-10-01",
            event_end_date="2026-10-03",
            cutoff_date="2026-09-01",
            attrition_deadline_date="2026-08-25",
            standard_commission_pct=0.11,
            standard_rebate_per_room_night_cents=600,
        )
        validate_error(
            api.create_event(collision, COORDINATOR), "ERR_EVENT_CODE_DUPLICATE", 409
        )

        untouched = validate_success(api.get_event(first["id"], COORDINATOR))
        assert untouched["name"] == "Annual Summit"
        assert untouched["standard_commission_pct"] == 0.10
        assert untouched["version"] == first["version"]


class TestAttendeeEmailUniquenessWithinAnEvent:
    def test_reimporting_the_same_address_does_not_overwrite_the_roster_row(self, api):
        """PRD §3.1: "An `Attendee` record carries the `event_id` it is registered
        for, an `email` that must be unique within that event — a duplicate is
        rejected with `ERR_ATTENDEE_EMAIL_DUPLICATE`"
        PRD §2.10: "`ERR_ATTENDEE_EMAIL_DUPLICATE` (409) when another attendee of the
        same `event_id` already uses the supplied `email`"

        Design: Corner/validations/duplicate_attendee_email_within_event_returns_conflict
        """
        event = register_event()
        first = import_attendee(event["id"])
        assert first["email"] == "a1@example.com"

        duplicate = create_attendee_payload(
            event["id"],
            email="a1@example.com",
            full_name="Attendee One Again",
            registration_id="REG-9",
            attendee_type="VIP",
        )
        validate_error(
            api.create_attendee(duplicate, COORDINATOR),
            "ERR_ATTENDEE_EMAIL_DUPLICATE",
            409,
        )

        after = validate_success(api.get_attendee(first["id"], COORDINATOR))
        assert after["attendee_type"] == "GENERAL"
        assert after["registration_id"] == "REG-1"
        assert after["version"] == first["version"]

        _, meta = validate_paginated(
            api.list_attendees(COORDINATOR, params={"event_id": event["id"]})
        )
        assert meta["total_count"] == 1


class TestEmailUniquenessScope:
    def test_the_same_address_is_admitted_into_a_second_event(self, api):
        """PRD §2.10: "`ERR_ATTENDEE_EMAIL_DUPLICATE` (409) when another attendee of
        the same `event_id` already uses the supplied `email`"
        PRD §3.1: "An `Attendee` record carries the `event_id` it is registered for,
        an `email` that must be unique within that event"
        PRD §3.1: "Three counters start at their zero values and are only ever moved
        by the workflows in §3.5 and §3.8: `warning_count` at 0, `housing_risk_flag`
        at false, and `no_show_strikes` at 0."

        Design: Corner/validations/same_email_in_a_second_event_is_accepted
        """
        first_event = register_event()
        second_event = register_event(**WINTER_EXPO)
        first = import_attendee(first_event["id"])

        payload = create_attendee_payload(second_event["id"], email="a1@example.com")
        second = validate_success(api.create_attendee(payload, COORDINATOR), 201)

        assert second["id"] != first["id"]
        assert second["event_id"] == second_event["id"]
        assert second["email"] == "a1@example.com"
        assert second["warning_count"] == 0
        assert second["housing_risk_flag"] is False
        assert second["no_show_strikes"] == 0


class TestPoachingIncidentKey:
    def test_the_key_includes_occurred_at_so_a_later_contact_still_counts(self, api):
        """PRD §3.8: "The combination of vendor, `attendee_id`, `contact_channel` and
        `occurred_at` must be unique; a repeat is rejected with
        `ERR_DUPLICATE_INCIDENT`."
        PRD §3.8: "The score starts from a base of 10, adds 25 for each counted
        incident, adds 15 for each distinct `contact_channel` appearing among the
        counted incidents, and adds a further 20 if any counted incident has
        `solicited_payment` true — that bonus is awarded once, not per incident."
        PRD §3.8: "The moment a newly recorded incident pushes `risk_score` to 60 or
        above while the vendor is still in `REPORTED`, the vendor transitions
        `REPORTED → UNDER_REVIEW` inside that same request and its `version` is
        bumped."

        Design: Corner/validations/duplicate_poaching_incident_key_returns_conflict
        """
        event = register_event()
        guest = import_attendee(event["id"])
        vendor = record_rogue_vendor(event["id"])
        record_incident(
            vendor["id"],
            guest["id"],
            contact_channel="EMAIL",
            occurred_at="2026-07-20T10:00:00Z",
            verified=True,
        )

        repeat = api.create_poaching_incident(
            vendor["id"],
            poaching_incident_payload(
                guest["id"], "EMAIL", "2026-07-20T10:00:00Z", True
            ),
            COMPLIANCE,
        )
        validate_error(repeat, "ERR_DUPLICATE_INCIDENT", 409)

        next_day = api.create_poaching_incident(
            vendor["id"],
            poaching_incident_payload(
                guest["id"], "EMAIL", "2026-07-21T10:00:00Z", True
            ),
            COMPLIANCE,
        )
        validate_success(next_day, 201)

        after = validate_success(api.get_rogue_vendor(vendor["id"], COMPLIANCE))
        assert after["verified_incident_count"] == 2
        assert after["risk_score"] == 75, (
            "base 10 plus 25 per incident plus 15 for the single channel is 75, got "
            f"{after['risk_score']}"
        )
        assert after["status"] == "UNDER_REVIEW"

        rows, meta = validate_paginated(
            api.list_vendor_incidents(vendor["id"], COMPLIANCE)
        )
        assert meta["total_count"] == 2


class TestSuspendedHotelBeatsTermsStandardization:
    def test_the_state_gate_answers_first_and_the_fiscal_rung_only_after(self, api):
        """PRD §2.10: "When a single request could fail several checks at once, the
        first failure in the following order is the one reported. This ordering is
        normative: a request that violates step 8 and step 18 simultaneously must
        return step 8's error."
        PRD §2.10: "`ERR_HOTEL_SUSPENDED` (409) when a block contract is attempted
        while the property's `standing` is `SUSPENDED`"
        PRD §2.10: "**Terms standardization.** `ERR_TERMS_NOT_STANDARDIZED` (422) on
        a block contract."
        PRD §3.2: "The transition `TERMS_SUBMITTED → CONTRACTED` succeeds only when
        the property's `standing` is `ACTIVE` — otherwise `ERR_HOTEL_SUSPENDED` — and
        only when all three standardization conditions hold simultaneously: the
        block's `commission_pct` is greater than or equal to the event's
        `standard_commission_pct`, the block's `rebate_per_room_night_cents` is
        greater than or equal to the event's `standard_rebate_per_room_night_cents`,
        and the block's `cutoff_date` is exactly equal to the event's `cutoff_date`."

        Design: Corner/validations/hotel_suspended_state_beats_terms_not_standardized
        """
        event = register_event()
        hotel = register_hotel()
        block = assemble_block(event["id"], hotel["id"], commission_pct=0.09)
        block = submit_terms(block, commission_pct=0.09)
        assert block["status"] == "TERMS_SUBMITTED"
        assert block["commission_pct"] == 0.09

        set_hotel_standing(hotel["id"], "SUSPENDED")
        hotel_headers = make_hotel_manager_headers(hotel["id"])

        suspended = api.contract_hotel_block(
            block["id"], contract_block_payload(), hotel_headers
        )
        validate_error(suspended, "ERR_HOTEL_SUSPENDED", 409)

        set_hotel_standing(hotel["id"], "ACTIVE")
        sub_standard = api.contract_hotel_block(
            block["id"], contract_block_payload(), hotel_headers
        )
        validate_error(sub_standard, "ERR_TERMS_NOT_STANDARDIZED", 422)

        after = read_block(block["id"])
        assert after["status"] == "TERMS_SUBMITTED"
        assert after["unassigned_rooms_per_night"] == 0
        assert after["confirmation_number"] is None
        assert after["version"] == block["version"]


class TestReductionWindowBoundary:
    def test_one_second_before_the_deadline_passes_and_the_deadline_itself_does_not(
        self, api
    ):
        """PRD §3.7: "The request must arrive **strictly before** the event's
        `attrition_deadline_date` at midnight UTC; a request filed at exactly that
        midnight, or later, is rejected with `ERR_REDUCTION_WINDOW_CLOSED`."
        PRD §3.7: "A filed reduction starts in `status` `SUBMITTED` with the filing
        `X-User-ID` recorded as `requested_by_user_id`, `approved_by_user_id` null,
        `rooms_absorbed_from_unassigned` and `rooms_absorbed_from_sub_blocks` at 0,
        and `penalty_avoided_cents` null."
        PRD §2.10: "**Reduction window.** `ERR_REDUCTION_WINDOW_CLOSED` (409) when a
        reduction request is filed at or after the event's `attrition_deadline_date`
        at midnight UTC."

        Design: Corner/validations/reduction_window_closes_exactly_at_the_deadline_date
        """
        ctx = setup_open_block(general_rooms=6)
        payload = attrition_reduction_payload(
            ctx["block"]["id"], 1, effective_date="2026-08-16"
        )

        set_clock("2026-08-14T23:59:59Z")
        accepted = validate_success(
            api.create_attrition_reduction(payload, COORDINATOR), 201
        )
        assert accepted["status"] == "SUBMITTED"
        assert accepted["rooms_absorbed_from_unassigned"] == 0
        assert accepted["rooms_absorbed_from_sub_blocks"] == 0
        assert accepted["penalty_avoided_cents"] is None

        set_clock("2026-08-15T00:00:00Z")
        refused = api.create_attrition_reduction(payload, COORDINATOR)
        validate_error(refused, "ERR_REDUCTION_WINDOW_CLOSED", 409)

        rows, meta = validate_paginated(
            api.list_block_attrition_reductions(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]
        assert read_block(ctx["block"]["id"])["contracted_rooms_per_night"] == 10


class TestCarveAggregateCeiling:
    def test_the_second_carve_is_measured_against_what_the_first_one_left(self, api):
        """PRD §3.3: "A **direct carve**, with no parent named, draws from the
        block's `unassigned_rooms_per_night` and succeeds only when `allotted_rooms`
        is less than or equal to that figure."
        PRD §3.3: "Either way, exceeding the source is rejected with
        `ERR_BLOCK_UNASSIGNED_ROOMS_EXCEEDED`"
        PRD §2.10: "**Carve inventory.** `ERR_BLOCK_UNASSIGNED_ROOMS_EXCEEDED` (409)
        on a sub-block carve."

        Design: Corner/validations/carve_aggregate_exceeds_unassigned_rooms
        """
        ctx = setup_contracted_block(contracted_rooms_per_night=10)
        general = carve_sub_block(ctx["block"]["id"], "GENERAL", 6)
        before = read_block(ctx["block"]["id"])
        assert before["unassigned_rooms_per_night"] == 4

        # 5 rooms is smaller than the 10-room block but larger than what is left.
        response = api.carve_sub_block(
            ctx["block"]["id"],
            carve_sub_block_payload(
                "STAFF", 5, before["version"], eligibility_code="STAFF-2026"
            ),
            COORDINATOR,
        )
        validate_error(response, "ERR_BLOCK_UNASSIGNED_ROOMS_EXCEEDED", 409)

        after = read_block(ctx["block"]["id"])
        assert after["unassigned_rooms_per_night"] == 4
        assert after["version"] == before["version"]

        rows, meta = validate_paginated(
            api.list_sub_blocks(
                COORDINATOR, params={"hotel_block_id": ctx["block"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == general["id"]


class TestStayWindowShoulderDay:
    def test_check_out_one_day_past_the_event_end_is_the_last_admissible_date(
        self, api
    ):
        """PRD §3.4: "First, the **stay window**: `check_in_date` must be no earlier
        than one day before the event's `event_start_date`, and `check_out_date` must
        be no later than one day after the event's `event_end_date`; a stay outside
        that widened window is rejected with `ERR_INVALID_STAY_WINDOW`."
        PRD §3.4: "`room_nights` is the number of whole days between `check_in_date`
        and `check_out_date`."
        PRD §2.10: "**Stay window.** `ERR_INVALID_STAY_WINDOW` (422) on a reservation
        booking or change."

        Design: Corner/validations/stay_window_one_day_past_event_end_is_the_boundary
        """
        ctx = setup_open_block(general_rooms=6, num_attendees=2)
        first, second = ctx["attendees"]

        too_long = api.create_reservation(
            create_reservation_payload(
                ctx["sub_block"]["id"],
                first["id"],
                check_in_date="2026-09-14",
                check_out_date="2026-09-20",
            ),
            make_attendee_headers(first["id"]),
        )
        validate_error(too_long, "ERR_INVALID_STAY_WINDOW", 422)

        on_the_boundary = validate_success(
            api.create_reservation(
                create_reservation_payload(
                    ctx["sub_block"]["id"],
                    second["id"],
                    check_in_date="2026-09-14",
                    check_out_date="2026-09-19",
                ),
                make_attendee_headers(second["id"]),
            ),
            201,
        )
        assert on_the_boundary["room_nights"] == 5
        assert on_the_boundary["reservation_status"] == "CONFIRMED"

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 1

        _, meta = validate_paginated(
            api.list_reservations(COORDINATOR, params={"attendee_id": first["id"]})
        )
        assert meta["total_count"] == 0


class TestReductionHeadroomCeiling:
    def test_a_submitted_row_consumes_the_whole_floored_entitlement(self, api):
        """PRD §3.7: "the **cap** is the block's
        `original_contracted_rooms_per_night` multiplied by its
        `reduction_rights_pct`, with the fractional part discarded — the entitlement
        always floors, never rounds up."
        PRD §3.7: "The **consumed** figure is the total `requested_reduction_rooms`
        across every reduction already filed against the block whose `status` is
        `SUBMITTED`, `APPROVED` or `EXERCISED`; rows in `REJECTED` release their share
        and count for nothing. Headroom is the cap minus the consumed figure, and a
        `requested_reduction_rooms` greater than that headroom is rejected with
        `ERR_REDUCTION_RIGHTS_EXCEEDED`."
        PRD §3.7: "Note that a `SUBMITTED` row already consumes headroom, so a
        coordinator cannot file two overlapping requests and let the controller pick."

        Design: Corner/validations/reduction_headroom_admits_the_cap_then_refuses_one_more_room
        """
        ctx = setup_open_block(
            general_rooms=6, block_overrides={"reduction_rights_pct": 0.25}
        )
        assert ctx["block"]["original_contracted_rooms_per_night"] == 10

        # The cap floors to 2 rooms, which the first request takes in full.
        first = validate_success(
            api.create_attrition_reduction(
                attrition_reduction_payload(
                    ctx["block"]["id"], 2, effective_date="2026-08-16"
                ),
                COORDINATOR,
            ),
            201,
        )
        assert first["status"] == "SUBMITTED"
        assert first["requested_reduction_rooms"] == 2

        overdrawn = api.create_attrition_reduction(
            attrition_reduction_payload(
                ctx["block"]["id"], 1, effective_date="2026-08-16"
            ),
            COORDINATOR,
        )
        validate_error(overdrawn, "ERR_REDUCTION_RIGHTS_EXCEEDED", 422)

        block = read_block(ctx["block"]["id"])
        assert block["contracted_rooms_per_night"] == 10
        assert block["original_contracted_rooms_per_night"] == 10

        _, meta = validate_paginated(
            api.list_block_attrition_reductions(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 1


class TestReductionWindowOutranksHeadroom:
    def test_a_request_violating_both_rungs_reports_the_closed_window(self, api):
        """PRD §2.10: "**Reduction window.** `ERR_REDUCTION_WINDOW_CLOSED` (409) when
        a reduction request is filed at or after the event's
        `attrition_deadline_date` at midnight UTC."
        PRD §2.10: "**Reduction-rights headroom.** `ERR_REDUCTION_RIGHTS_EXCEEDED`
        (422) on a reduction request."
        PRD §2.10: "When a single request could fail several checks at once, the first
        failure in the following order is the one reported. This ordering is
        normative: a request that violates step 8 and step 18 simultaneously must
        return step 8's error."

        Design: Corner/validations/reduction_window_check_runs_before_headroom_check
        """
        ctx = setup_open_block(general_rooms=6)
        set_clock("2026-08-16T00:00:00Z")

        # 5 rooms also overdraws the 2-room cap, but the clock answers first.
        response = api.create_attrition_reduction(
            attrition_reduction_payload(
                ctx["block"]["id"], 5, effective_date="2026-08-17"
            ),
            COORDINATOR,
        )
        validate_error(response, "ERR_REDUCTION_WINDOW_CLOSED", 409)
        assert response.json()["data"]["error_id"] != "ERR_REDUCTION_RIGHTS_EXCEEDED"

        _, meta = validate_paginated(
            api.list_block_attrition_reductions(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 0


class TestEligibilityIsConditionalOnSegment:
    def test_one_delegate_is_refused_by_the_vip_carve_and_taken_by_the_general_one(
        self, api
    ):
        """PRD §3.4: "For a sub-block whose `segment` is anything other than
        `GENERAL`, the guest's `attendee_type` must equal that `segment` and the
        sub-block's `eligibility_code` must appear among the guest's
        `eligibility_codes`; independently of segment, the guest's `event_id` must
        equal the `event_id` of the block the sub-block hangs from. Any of those
        three conditions failing rejects the booking with
        `ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH`. A `GENERAL` sub-block imposes no
        segment or code requirement, but the same-event requirement still applies."
        PRD §2.10: "**Sub-block eligibility.** `ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH`
        (422) on a reservation booking."

        Design: Corner/validations/eligibility_rule_applies_only_to_non_general_segments
        """
        ctx = setup_housing_program(
            contracted_rooms_per_night=10,
            carves=[
                {"segment": "GENERAL", "allotted_rooms": 3},
                {
                    "segment": "VIP",
                    "allotted_rooms": 3,
                    "eligibility_code": "VIP-2026",
                    "approve": True,
                },
            ],
            open_portal=True,
            attendees=[{}],
        )
        general, vip = ctx["sub_blocks"]
        guest = ctx["attendees"][0]
        assert guest["attendee_type"] == "GENERAL"
        assert guest["eligibility_codes"] == []

        refused = api.create_reservation(
            create_reservation_payload(vip["id"], guest["id"]),
            make_attendee_headers(guest["id"]),
        )
        validate_error(refused, "ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH", 422)

        accepted = validate_success(
            api.create_reservation(
                create_reservation_payload(general["id"], guest["id"]),
                make_attendee_headers(guest["id"]),
            ),
            201,
        )
        assert accepted["sub_block_id"] == general["id"]

        vip_after = validate_success(api.get_sub_block(vip["id"], COORDINATOR))
        general_after = validate_success(api.get_sub_block(general["id"], COORDINATOR))
        assert vip_after["committed_rooms"] == 0
        assert general_after["committed_rooms"] == 1
