"""Every rejection the contract names, and the rows each refusal must leave untouched."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ERR_ACCESSIBILITY_RESOLUTION_REQUIRED,
    ERR_ANSWER_BEFORE_RECEIPT,
    ERR_BASIS_REFERENCE_MISMATCH,
    ERR_CONSENT_REFERENCE_MISMATCH,
    ERR_CORRECTIVE_ACTION_REQUIRED,
    ERR_CREDIT_CONSENT_REQUIRED,
    ERR_DELAY_NOT_WORSENED,
    ERR_DELIVERY_BEFORE_CHECKIN,
    ERR_DUPLICATE_CARRIER_CODE,
    ERR_DUPLICATE_OBLIGATION_FOR_SOURCE,
    ERR_DUPLICATE_PASSENGER_EMAIL,
    ERR_DUPLICATE_RECORD_LOCATOR,
    ERR_DUPLICATE_SEQUENCE_INDEX,
    ERR_DUPLICATE_TAG_NUMBER,
    ERR_ELECTION_REQUIRED,
    ERR_EXEMPTION_AFTER_DEADLINE,
    ERR_FAILURE_REASON_REQUIRED,
    ERR_GRANT_AMOUNT_REQUIRED,
    ERR_INVALID_PAGINATION,
    ERR_NO_REFUND_HEADROOM,
    ERR_OBLIGATION_NOT_VOIDABLE,
    ERR_PERIOD_BOUNDS_INVALID,
    ERR_REFUND_EXCEEDS_HEADROOM,
    ERR_REOPEN_LIMIT_REACHED,
    ERR_REVISED_ARRIVAL_INVALID,
    ERR_SUBSTITUTE_BEFORE_SCHEDULED,
    ERR_VOLUNTARY_BELOW_DISCLOSURE_FLOOR,
    OFFICER_1,
    OFFICER_HEADERS,
    OPS_HEADERS,
    acknowledge,
    add_checked_bag,
    add_segment,
    answer,
    assert_booking_ledger,
    assert_cents,
    assert_exposure,
    assert_hours,
    assert_instant,
    assert_list_meta,
    assert_null,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_obligation_deadlines,
    assert_segment_state,
    assert_sweep_counters,
    booking_version,
    build_world,
    cancel_segment,
    cancelled_booking_with_obligation,
    create_booking,
    create_policy_profile,
    delay_segment,
    elect,
    factories as f,
    file_complaint,
    initiate,
    list_activities,
    obligations_with_meta,
    read_bag,
    read_booking,
    read_complaint,
    read_denied_boarding,
    read_exposure,
    read_obligation,
    read_profile,
    read_segment,
    read_tarmac_event,
    record_operation,
    run_sweep,
    set_clock,
)

# ─── Natural keys and page windows ────────────────────


class TestUniquenessScopes:
    def test_each_uniqueness_scope_reports_its_own_conflict_code(self, api):
        """Five natural keys, five distinct 409 codes, and not one rejected write lands.

        PRD §2.5: "**Uniqueness, overlap and limit constraints**, in this order:
        `ERR_TARMAC_INTERVAL_OVERLAP`, `ERR_REPORT_PERIOD_OVERLAP`, then the uniqueness
        family (`ERR_DUPLICATE_CARRIER_CODE`, `ERR_DUPLICATE_PASSENGER_EMAIL`,
        `ERR_DUPLICATE_RECORD_LOCATOR`, `ERR_DUPLICATE_TAG_NUMBER`,
        `ERR_DUPLICATE_SEQUENCE_INDEX`), then `ERR_DUPLICATE_OBLIGATION_FOR_SOURCE`, then
        `ERR_REOPEN_LIMIT_REACHED`. All are HTTP 409."

        PRD §2.9: "A profile is identified to the outside world by its `carrier_code`,
        which must be unique across all profiles."

        PRD §3.1: "Legs are added to the booking one at a time, each at an explicit
        `sequence_index` that is at least 1 and unique within the booking — a repeat index
        is rejected with `ERR_DUPLICATE_SEQUENCE_INDEX`."

        Design: Corner/validations/duplicate_key_violations_return_their_specific_error_codes
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])
        add_checked_bag(
            api,
            world.booking["id"],
            tag_number="BAG0000001",
            fee_cents=4500,
            checked_at_utc="2026-08-10T13:00:00Z",
            scheduled_delivery_utc="2026-08-10T21:00:00Z",
        )

        validate_error(
            api.create_policy_profile(f.policy_profile_payload("ZQ"), ADMIN_HEADERS),
            ERR_DUPLICATE_CARRIER_CODE,
            409,
        )
        validate_error(
            api.create_passenger(
                f.passenger_payload("pat@example.com", "Other Person"), OFFICER_HEADERS
            ),
            ERR_DUPLICATE_PASSENGER_EMAIL,
            409,
        )
        validate_error(
            api.create_booking(
                f.booking_payload(
                    world.passenger["id"],
                    world.profile["id"],
                    record_locator="ABC123",
                    total_fare_cents=70000,
                ),
                OFFICER_HEADERS,
            ),
            ERR_DUPLICATE_RECORD_LOCATOR,
            409,
        )
        validate_error(
            api.create_checked_bag(
                f.checked_bag_payload(
                    world.booking["id"],
                    tag_number="BAG0000001",
                    fee_cents=3000,
                    checked_at_utc="2026-08-10T13:30:00Z",
                ),
                OFFICER_HEADERS,
            ),
            ERR_DUPLICATE_TAG_NUMBER,
            409,
        )
        validate_error(
            api.create_flight_segment(
                world.booking["id"],
                f.flight_segment_payload(
                    sequence_index=1,
                    flight_number="ZQ777",
                    origin_iata="DFW",
                    destination_iata="LAX",
                    scheduled_departure_utc="2026-08-10T16:00:00Z",
                    scheduled_arrival_utc="2026-08-10T18:00:00Z",
                    segment_fare_cents=20000,
                ),
                OPS_HEADERS,
            ),
            ERR_DUPLICATE_SEQUENCE_INDEX,
            409,
        )

        booking = read_booking(api, world.booking["id"])
        assert_booking_ledger(booking, segment_count=1, collected_total_cents=54500)


class TestPaginationBounds:
    def test_page_windows_outside_the_declared_range_are_refused_not_clamped(self, api):
        """limit 0, limit 101 and offset -1 are each a 400, never a silent default.

        PRD §2.3: "`limit` controls page size: it defaults to 10, may not be smaller than
        1, and may not exceed 100."

        PRD §2.3: "A `limit` outside the inclusive range 1 through 100, a non-integer
        `limit`, a negative `offset` or a non-integer `offset` is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/pagination_parameters_outside_declared_bounds_rejected
        """
        build_world(api)

        for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            validate_error(
                api.list_bookings(OFFICER_HEADERS, **bad), ERR_INVALID_PAGINATION, 400
            )

        rows, meta = validate_paginated(
            api.list_bookings(OFFICER_HEADERS, limit=100, offset=0)
        )
        assert len(rows) == 1, "the single booking is inside the widest legal window"
        assert_list_meta(meta, total_count=1, has_more=False)


# ─── Source references and the fiscal ceiling ─────────


class TestObligationSourceReferenceRules:
    def test_a_second_fare_obligation_on_one_leg_is_a_duplicate_not_a_money_failure(
        self, api
    ):
        """The source-pair conflict answers first even though the headroom is now spent.

        PRD §3.6: "At most one non-voided obligation may exist per basis-and-source pair —
        one per leg for `FARE`, one per bag for `BAGGAGE_FEE`, one per ancillary purchase
        for `ANCILLARY`, one per denied-boarding record for `DENIED_BOARDING`, and one per
        answering complaint for `GOODWILL_GRANT` — and a second attempt is
        `ERR_DUPLICATE_OBLIGATION_FOR_SOURCE`."

        PRD §2.5: "**Fiscal checks, evaluated last** — `ERR_NO_REFUND_HEADROOM` and
        `ERR_REFUND_EXCEEDS_HEADROOM`, both HTTP 422. Money is the last thing checked, so a
        request that is both malformed and unaffordable reports the malformation."

        Design: Corner/validations/duplicate_obligation_for_same_source_row_rejected
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[90000])
        booking_id = world.booking["id"]
        first = validate_success(
            api.create_refund_obligation(
                f.obligation_payload(
                    booking_id,
                    booking_version(api, booking_id),
                    flight_segment_id=world.segments[0]["id"],
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        refused = api.create_refund_obligation(
            f.obligation_payload(
                booking_id,
                booking_version(api, booking_id),
                flight_segment_id=world.segments[0]["id"],
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_DUPLICATE_OBLIGATION_FOR_SOURCE, 409)
        _, meta = obligations_with_meta(api, booking_id)
        assert_list_meta(meta, total_count=1, has_more=False)
        assert_obligation_amounts(read_obligation(api, first["id"]), amount_cents=90000)
        assert_booking_ledger(
            read_booking(api, booking_id), total_refund_obligated_cents=90000
        )

    def test_a_fare_basis_paired_with_a_bag_reference_is_refused(self, api):
        """The bag exists, so this is a basis mismatch rather than a missing row.

        PRD §3.6: "Supplying the wrong reference for the declared basis, supplying more
        than one, omitting the one that is required, or naming a source row that belongs to
        a different booking are all `ERR_BASIS_REFERENCE_MISMATCH`."

        PRD §2.5: "**Referential consistency**, in this order:
        `ERR_SEGMENT_BOOKING_MISMATCH`, `ERR_BASIS_REFERENCE_MISMATCH` and
        `ERR_CONSENT_REFERENCE_MISMATCH`. All are HTTP 422."

        Design: Corner/validations/basis_reference_mismatch_rejected
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[90000])
        booking_id = world.booking["id"]
        bag = add_checked_bag(
            api,
            booking_id,
            checked_at_utc="2026-08-10T13:00:00Z",
            scheduled_delivery_utc="2026-08-10T21:00:00Z",
        )
        before_version = booking_version(api, booking_id)

        refused = api.create_refund_obligation(
            f.obligation_payload(
                booking_id, before_version, basis="FARE", checked_bag_id=bag["id"]
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_BASIS_REFERENCE_MISMATCH, 422)
        _, meta = obligations_with_meta(api, booking_id)
        assert_list_meta(meta, total_count=0, has_more=False)
        assert_booking_ledger(
            read_booking(api, booking_id),
            total_refund_obligated_cents=0,
            version=before_version,
        )


class TestObligationHeadroomCeiling:
    def test_a_proactive_create_against_spent_headroom_is_refused_outright(self, api):
        """Zero headroom refuses the mint instead of persisting a zero-cent row.

        PRD §3.6: "A proactive obligation is clamped down: its `amount_cents` is the
        smaller of its gross entitlement and the headroom — but a proactive create against a
        booking whose headroom is 0 or negative is refused outright with
        `ERR_NO_REFUND_HEADROOM`."

        PRD §3.6: "`headroom_at_creation_cents` is the collected figure minus the consumed
        figure, and it is stored on the row as the audit trail of what was available at the
        moment of creation."

        Design: Corner/validations/proactive_obligation_with_exhausted_headroom_rejected
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])
        booking_id = world.booking["id"]
        cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")
        before_version = booking_version(api, booking_id)

        refused = api.create_refund_obligation(
            f.obligation_payload(
                booking_id, before_version, flight_segment_id=world.segments[1]["id"]
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_NO_REFUND_HEADROOM, 422)
        _, meta = obligations_with_meta(api, booking_id)
        assert_list_meta(meta, total_count=1, has_more=False)
        assert_booking_ledger(
            read_booking(api, booking_id),
            total_refund_obligated_cents=90000,
            version=before_version,
        )
        assert_exposure(
            read_exposure(api, booking_id),
            remaining_headroom_cents=0,
            collected_total_cents=90000,
            obligated_total_cents=90000,
        )

    def test_a_request_based_claim_over_the_headroom_is_refused_not_clamped(self, api):
        """A positive 2000 of headroom cannot silently absorb a 90000 proration.

        PRD §3.6: "A request-based obligation is never clamped: if its gross entitlement
        exceeds the headroom, the request is refused with `ERR_REFUND_EXCEEDS_HEADROOM`,
        because a passenger-initiated claim that the ledger cannot support is an error to be
        corrected rather than a number to be silently reduced."

        PRD §3.6: "In request-based mode the variant is `REQUEST_BASED_UNUSED_PRORATION`,
        and it prorates evenly: when the booking's `segment_count` is 0 the gross
        entitlement is 0 and no division is attempted, and otherwise the per-leg share is
        the booking's `total_fare_cents` divided by its `segment_count` and rounded half up,
        and the gross entitlement is that share multiplied by the booking's
        `unused_segment_count`."

        Design: Corner/validations/request_based_claim_exceeding_headroom_rejected_not_clamped
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])
        booking_id = world.booking["id"]
        cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")
        bag = add_checked_bag(
            api,
            booking_id,
            fee_cents=2000,
            checked_at_utc="2026-08-10T11:00:00Z",
            scheduled_delivery_utc="2026-08-10T19:00:00Z",
        )

        refused = api.create_refund_obligation(
            f.obligation_payload(
                booking_id,
                booking_version(api, booking_id),
                issuance_mode="REQUEST_BASED",
                flight_segment_id=world.segments[1]["id"],
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_REFUND_EXCEEDS_HEADROOM, 422)
        _, meta = obligations_with_meta(api, booking_id)
        assert_list_meta(meta, total_count=1, has_more=False)
        assert_exposure(
            read_exposure(api, booking_id),
            request_based_proration_cents=90000,
            remaining_headroom_cents=2000,
            collected_total_cents=92000,
            segment_count=2,
            unused_segment_count=2,
        )
        assert read_bag(api, bag["id"], booking_id)["fee_refund_obligated"] is False
        assert_booking_ledger(
            read_booking(api, booking_id), total_refund_obligated_cents=90000
        )


# ─── Informed consent on a credit election ────────────


class TestCreditElectionConsent:
    def test_an_officer_electing_credit_must_cite_a_consent_artefact(self, api):
        """Without a consent complaint the election axis does not move at all.

        PRD §3.7: "Because moving a passenger onto travel credit gives up their right to
        cash, a compliance role electing `TRAVEL_CREDIT` on the passenger's behalf must cite
        a consent artefact: `consent_complaint_id` becomes mandatory, and omitting it is
        `ERR_CREDIT_CONSENT_REQUIRED`."

        PRD §2.5: "**Regulatory safety gates**, in this order: segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403), the officer credit-consent requirement
        (`ERR_CREDIT_CONSENT_REQUIRED`), the disability resolution-code requirement
        (`ERR_ACCESSIBILITY_RESOLUTION_REQUIRED`), the voluntary disclosure floor
        (`ERR_VOLUNTARY_BELOW_DISCLOSURE_FLOOR`), and the corrective-action requirement on a
        violating tarmac report (`ERR_CORRECTIVE_ACTION_REQUIRED`) — the last four all HTTP
        422."

        Design: Corner/validations/officer_credit_election_without_consent_complaint_rejected
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)

        refused = api.elect_refund_obligation(
            world.obligation["id"], f.elect_payload("TRAVEL_CREDIT"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_CREDIT_CONSENT_REQUIRED, 422)
        obligation = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(
            obligation,
            election_status="PENDING_ELECTION",
            election_source=None,
            settlement_method=None,
        )
        assert_obligation_amounts(
            obligation, credit_bonus_cents=0, payable_total_cents=50000
        )

    def test_a_consent_complaint_from_another_booking_is_refused(self, api):
        """The complaint exists, so the mismatch is referential rather than a 404.

        PRD §3.7: "The complaint it names must exist, or
        `ERR_CONSUMER_COMPLAINT_NOT_FOUND`, and must belong to the same booking as the
        obligation, or `ERR_CONSENT_REFERENCE_MISMATCH`."

        PRD §3.7: "When supplied, its id is stored on the obligation as
        `credit_consent_reference`."

        Design: Corner/validations/consent_complaint_from_another_booking_rejected
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)
        other_booking = create_booking(
            api,
            world.passenger["id"],
            world.profile["id"],
            record_locator="BBB222",
            total_fare_cents=40000,
        )
        elsewhere = file_complaint(
            api, other_booking["id"], summary="Passenger consents to travel credit."
        )

        refused = api.elect_refund_obligation(
            world.obligation["id"],
            f.elect_payload("TRAVEL_CREDIT", consent_complaint_id=elsewhere["id"]),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_CONSENT_REFERENCE_MISMATCH, 422)
        obligation = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(obligation, election_status="PENDING_ELECTION")
        assert_null(obligation["credit_consent_reference"], "credit_consent_reference")
        assert_obligation_amounts(obligation, credit_bonus_cents=0)


# ─── Conditions on the substantive answer ─────────────


class TestComplaintAnswerConditions:
    def test_a_disability_answer_needs_an_accessibility_resolution_code(self, api):
        """The category, not the disposition, is what makes the code mandatory.

        PRD §3.8: "A complaint whose `category` is `DISABILITY` additionally requires an
        `accessibility_resolution_code` of `ASSISTANCE_PROVIDED`, `EQUIPMENT_REPAIRED`,
        `TRAINING_ISSUED` or `ESCALATED_TO_CRO`; answering a disability matter without one is
        `ERR_ACCESSIBILITY_RESOLUTION_REQUIRED`."

        PRD §3.8: "Each of the four appends an activity row of the matching type:
        `ACKNOWLEDGED`, `INFO_REQUESTED`, `ANSWERED` and `REOPENED` respectively."

        Design: Corner/validations/disability_answer_without_accessibility_code_rejected
        """
        world = build_world(api, requires_disability_assistance=True)
        complaint = file_complaint(
            api,
            world.booking["id"],
            category="DISABILITY",
            channel="PHONE",
            summary="Wheelchair assistance was not provided.",
        )
        acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")

        refused = api.answer_complaint(
            complaint["id"],
            f.answer_payload("2026-08-07T11:00:00Z", "POLICY_EXPLAINED"),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_ACCESSIBILITY_RESOLUTION_REQUIRED, 422)
        stored = read_complaint(api, complaint["id"])
        assert stored["status"] == "ACKNOWLEDGED", "the refused answer moved nothing"
        assert_null(stored["answered_at_utc"], "answered_at_utc")
        trail = [row["activity_type"] for row in list_activities(api, complaint["id"])]
        assert trail == ["RECEIVED", "ACKNOWLEDGED"], (
            f"the refused answer appended no row, got {trail}"
        )

    def test_a_granted_refund_needs_an_amount(self, api):
        """No zero-cent goodwill obligation is written as a placeholder.

        PRD §3.8: "A `REFUND_GRANTED` disposition requires a `granted_amount_cents` of at
        least 1, and omitting it or supplying less is `ERR_GRANT_AMOUNT_REQUIRED`."

        PRD §2.5: "Answering a complaint with a refund-granted disposition without a
        `granted_amount_cents` of at least 1 yields `ERR_GRANT_AMOUNT_REQUIRED`."

        Design: Corner/validations/refund_granted_answer_without_amount_rejected
        """
        world = build_world(api, total_fare_cents=50000)
        complaint = file_complaint(
            api, world.booking["id"], summary="Requesting a goodwill refund."
        )
        acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")

        refused = api.answer_complaint(
            complaint["id"],
            f.answer_payload("2026-08-07T11:00:00Z", "REFUND_GRANTED"),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_GRANT_AMOUNT_REQUIRED, 422)
        assert read_complaint(api, complaint["id"])["status"] == "ACKNOWLEDGED"
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, total_count=0, has_more=False)
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=0
        )


# ─── Complaint chronology and the reopen cap ──────────


class TestComplaintChronology:
    def test_an_acknowledgement_predating_receipt_is_refused(self, api):
        """A complaint cannot be acknowledged the day before it arrived.

        PRD §3.8: "Acknowledging supplies `acknowledged_at_utc` and drives `RECEIVED →
        ACKNOWLEDGED`; the instant must be at or after `received_at_utc`."

        PRD §3.8: "Any of these chronology rules being violated is
        `ERR_ANSWER_BEFORE_RECEIPT` (HTTP 422), and an action attempted from the wrong
        status — acknowledging something not `RECEIVED`, requesting information on something
        not `ACKNOWLEDGED`, answering something that is neither `ACKNOWLEDGED` nor
        `INFO_REQUESTED`, or reopening something not `ANSWERED` — is
        `ERR_COMPLAINT_STATE_INVALID` (HTTP 409)."

        PRD §2.4: "All entities except the complaint activity trail additionally carry
        `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and
        `version`, an integer that begins at 1 when the row is created and increases by
        exactly 1 on each request that changes the row's persisted field values."

        Design: Corner/validations/complaint_acknowledged_before_receipt_rejected
        """
        world = build_world(api)
        complaint = file_complaint(api, world.booking["id"])

        refused = api.acknowledge_complaint(
            complaint["id"],
            f.acknowledge_payload("2026-08-04T09:00:00Z"),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_ANSWER_BEFORE_RECEIPT, 422)
        stored = read_complaint(api, complaint["id"])
        assert stored["status"] == "RECEIVED", "the refused acknowledgement moved nothing"
        assert_null(stored["acknowledged_at_utc"], "acknowledged_at_utc")
        assert stored["version"] == 1, "a refused write changes no persisted field"
        trail = [row["activity_type"] for row in list_activities(api, complaint["id"])]
        assert trail == ["RECEIVED"], f"only the filing row exists, got {trail}"

    def test_a_third_reopen_is_refused_at_the_statutory_cap(self, api):
        """Two reopens are the limit, and the second reopen's answer clock survives.

        PRD §3.8: "Reopening is capped: a complaint whose `reopen_count` has already
        reached 2 is refused with `ERR_REOPEN_LIMIT_REACHED`."

        PRD §3.8: "It drives `ANSWERED → ACKNOWLEDGED`, increases `reopen_count` by 1, and
        re-derives `answer_due_utc` from the `reopened_at_utc` instant plus the category's
        answer window — the disability window for a disability matter, the general window
        otherwise — so the clock restarts rather than resuming."

        PRD §3.8: "The complaint's `ack_due_utc` is **not** re-derived, its
        `answer_breached` flag is reset to false, and its `disposition` and
        `accessibility_resolution_code` are retained rather than cleared."

        PRD §3.8: "`ack_due_utc` is the profile's acknowledgement window added to
        `received_at_utc` — 30 days by default, for every category alike."

        Design: Corner/validations/third_reopen_beyond_limit_rejected
        """
        world = build_world(api)
        complaint = file_complaint(api, world.booking["id"])
        acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")
        answer(api, complaint["id"], "2026-08-07T11:00:00Z")
        validate_success(
            api.reopen_complaint(
                complaint["id"],
                f.reopen_payload(
                    "2026-08-08T12:00:00Z", "Passenger disputes the explanation."
                ),
                OFFICER_HEADERS,
            )
        )
        answer(api, complaint["id"], "2026-08-09T13:00:00Z")
        validate_success(
            api.reopen_complaint(
                complaint["id"],
                f.reopen_payload("2026-08-10T14:00:00Z", "New evidence supplied."),
                OFFICER_HEADERS,
            )
        )
        answer(api, complaint["id"], "2026-08-11T15:00:00Z")

        refused = api.reopen_complaint(
            complaint["id"],
            f.reopen_payload("2026-08-12T16:00:00Z", "Third attempt."),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_REOPEN_LIMIT_REACHED, 409)
        stored = read_complaint(api, complaint["id"])
        assert stored["status"] == "ANSWERED", "the refused reopen left the answer standing"
        assert stored["reopen_count"] == 2, "the cap is two reopens"
        assert_instant(stored["answer_due_utc"], "2026-10-09T14:00:00Z")
        assert_instant(stored["ack_due_utc"], "2026-09-04T09:00:00Z")
        assert_instant(stored["answered_at_utc"], "2026-08-11T15:00:00Z")


# ─── Denied boarding guards ───────────────────────────


class TestDeniedBoardingGuards:
    def test_a_volunteer_agreement_below_the_disclosure_floor_is_refused(self, api):
        """The floor is half the capped statutory figure, not half the fare.

        PRD §3.4: "The second rung runs from 61 minutes up to and including a
        scope-dependent ceiling of 120 minutes (two hours) on a domestic leg or 240 minutes
        (four hours) on a leg flagged international; here the statutory figure is twice the
        `one_way_fare_cents`, rounded half up, but never more than 77,500 cents (775
        dollars)."

        PRD §3.4: "On a genuinely voluntary record the disclosure floor is enforced first:
        the agreed `voluntary_agreed_amount_cents` must be at least half of
        `statutory_compensation_cents`, computed as the statutory amount multiplied by 0.50
        and rounded half up, and an agreed amount below that floor is refused with
        `ERR_VOLUNTARY_BELOW_DISCLOSURE_FLOOR`; when it clears the floor,
        `compensation_cents` is set to the agreed amount, which may sit anywhere at or above
        the floor."

        PRD §3.4: "A newly recorded incident sits in `RECORDED` with
        `statutory_compensation_cents` at 0, `compensation_cents` at 0 and
        `effective_category` unset, and with `substitute_delay_minutes` computed immediately
        as the difference between the `substitute_arrival_utc` and the leg's
        `scheduled_arrival_utc` in whole minutes with the remainder dropped, never below 0."

        Design: Corner/validations/voluntary_agreement_below_disclosure_floor_rejected
        """
        world = build_world(api, total_fare_cents=60000, segment_fares=[60000])
        record = validate_success(
            api.create_denied_boarding_record(
                f.denied_boarding_payload(
                    world.booking["id"],
                    world.segments[0]["id"],
                    category="VOLUNTARY",
                    one_way_fare_cents=45000,
                    substitute_arrival_utc="2026-08-10T15:30:00Z",
                    oversale_confirmed=True,
                    written_disclosure_provided=True,
                    voluntary_agreed_amount_cents=30000,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        refused = api.finalize_denied_boarding_record(
            record["id"], f.finalize_payload("2026-08-10T16:00:00Z"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_VOLUNTARY_BELOW_DISCLOSURE_FLOOR, 422)
        stored = read_denied_boarding(api, record["id"])
        assert stored["status"] == "RECORDED", "the refused finalization moved nothing"
        assert_null(stored["effective_category"], "effective_category")
        assert_cents(stored["compensation_cents"], 0, "compensation_cents")
        assert_null(stored["finalized_at_utc"], "finalized_at_utc")
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, total_count=0, has_more=False)
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), suppressed_obligation_count=0
        )

    def test_a_substitute_arriving_before_the_schedule_is_refused(self, api):
        """A negative substitute delay is never computed; the create is refused.

        PRD §3.4: "The `flight_segment_id` must belong to the supplied `booking_id`, or the
        request is `ERR_SEGMENT_BOOKING_MISMATCH`, and the `substitute_arrival_utc` must be
        at or after the named leg's `scheduled_arrival_utc`, or it is
        `ERR_SUBSTITUTE_BEFORE_SCHEDULED`."

        PRD §2.5: "**Temporal gates**, in this order: `ERR_TARMAC_WINDOW_INVALID`,
        `ERR_EXEMPTION_AFTER_DEADLINE`, `ERR_DELIVERY_BEFORE_CHECKIN`,
        `ERR_ANSWER_BEFORE_RECEIPT`, `ERR_PERIOD_BOUNDS_INVALID`,
        `ERR_SUBSTITUTE_BEFORE_SCHEDULED` and `ERR_REVISED_ARRIVAL_INVALID`. All are HTTP
        422."

        Design: Corner/validations/substitute_arrival_before_scheduled_rejected
        """
        world = build_world(api, total_fare_cents=60000, segment_fares=[60000])

        refused = api.create_denied_boarding_record(
            f.denied_boarding_payload(
                world.booking["id"],
                world.segments[0]["id"],
                one_way_fare_cents=45000,
                substitute_arrival_utc="2026-08-10T13:00:00Z",
                oversale_confirmed=True,
                written_disclosure_provided=True,
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_SUBSTITUTE_BEFORE_SCHEDULED, 422)
        _, meta = validate_paginated(
            api.list_denied_boarding_records(
                OFFICER_HEADERS, booking_id=world.booking["id"]
            )
        )
        assert_list_meta(meta, total_count=0, has_more=False)
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=0
        )


# ─── Disruption declaration guards ────────────────────


class TestDisruptionDeclarationGuards:
    def test_a_revised_arrival_equal_to_the_schedule_is_refused(self, api):
        """A zero-minute delay is no delay, even declared a day before departure.

        PRD §3.2: "The revised arrival must be strictly later than the leg's
        `scheduled_arrival_utc`, and a value at or before it is rejected with
        `ERR_REVISED_ARRIVAL_INVALID`."

        PRD §3.2: "Nothing requires the declaration instant to fall after the scheduled
        departure — a disruption may legitimately be declared in advance."

        PRD §3.1: "A newly added leg's `booking_id` is the booking it was added under, its
        `status` reads `SCHEDULED`, its `disruption_type` reads `NONE`, its `delay_minutes`
        is 0, its `is_significant_delay` is false, and its `cumulative_tarmac_minutes` and
        `exempted_tarmac_event_count` are both 0."

        Design: Corner/validations/revised_arrival_not_after_scheduled_rejected
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])

        refused = api.declare_disruption(
            world.segments[0]["id"],
            f.delay_payload("2026-08-10T14:00:00Z", declared_at_utc="2026-08-09T09:00:00Z"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_REVISED_ARRIVAL_INVALID, 422)
        segment = read_segment(api, world.segments[0]["id"])
        assert_segment_state(
            segment,
            status="SCHEDULED",
            disruption_type="NONE",
            delay_minutes=0,
            is_significant_delay=False,
        )
        assert segment["version"] == 1, "the refused declaration wrote nothing"

    def test_a_redeclaration_that_improves_the_delay_is_refused(self, api):
        """A carrier cannot walk a significant delay back below the threshold.

        PRD §3.2: "Such a re-declaration is a self-cycle `DELAYED → DELAYED` and requires a
        `revised_arrival_utc` strictly later than the one already stored, so that the
        recomputed `delay_minutes` is strictly greater than the stored value; walking a delay
        backwards is refused with `ERR_DELAY_NOT_WORSENED`."

        PRD §3.2: "If a fare obligation already exists for the leg, its `amount_cents` is
        **not** recomputed — the first valuation stands."

        Design: Corner/validations/delay_redeclaration_not_worsened_rejected
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[90000])
        delay_segment(
            api, world.segments[0]["id"], "2026-08-10T18:00:00Z", "2026-08-10T09:00:00Z"
        )

        refused = api.declare_disruption(
            world.segments[0]["id"],
            f.delay_payload("2026-08-10T17:00:00Z", declared_at_utc="2026-08-10T10:00:00Z"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_DELAY_NOT_WORSENED, 409)
        assert_segment_state(
            read_segment(api, world.segments[0]["id"]),
            status="DELAYED",
            revised_arrival_utc="2026-08-10T18:00:00Z",
            delay_minutes=240,
            is_significant_delay=True,
            disruption_declared_at_utc="2026-08-10T09:00:00Z",
        )
        rows, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, total_count=1, has_more=False)
        assert_obligation_amounts(rows[0], amount_cents=90000)


# ─── Baggage chronology ───────────────────────────────


class TestBaggageChronology:
    def test_a_delivery_predating_check_in_is_refused(self, api):
        """The delay computation never sees a negative interval.

        PRD §3.3: "Whichever instant is supplied must be at or after the bag's
        `checked_at_utc`; an earlier instant is `ERR_DELIVERY_BEFORE_CHECKIN`."

        PRD §3.3: "A new bag begins with `status` reading `IN_TRANSIT`,
        `delivery_delay_hours` at 0 and `fee_refund_obligated` false; recording it refreshes
        the booking's `collected_total_cents` and advances the booking's `version` by 1."

        Design: Corner/validations/bag_delivery_before_checkin_rejected
        """
        world = build_world(api)
        bag = add_checked_bag(
            api,
            world.booking["id"],
            checked_at_utc="2026-08-10T13:00:00Z",
            scheduled_delivery_utc="2026-08-10T21:00:00Z",
        )

        refused = api.resolve_checked_bag(
            bag["id"], f.bag_delivered_payload("2026-08-10T12:00:00Z"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_DELIVERY_BEFORE_CHECKIN, 422)
        stored = read_bag(api, bag["id"], world.booking["id"])
        assert stored["status"] == "IN_TRANSIT", "the refused resolution moved nothing"
        assert_null(stored["delivered_at_utc"], "delivered_at_utc")
        assert_hours(stored["delivery_delay_hours"], 0.0)
        assert stored["fee_refund_obligated"] is False
        assert stored["version"] == 1, "a refused write changes no persisted field"


# ─── Tarmac deadlines and contingency filing ──────────


class TestTarmacGuards:
    def test_a_violating_event_cannot_be_filed_without_a_corrective_narrative(self, api):
        """181 minutes is one past the strict deadline, so the narrative is mandatory.

        PRD §3.5: "The event moves `DELAY_ACTIVE → DEPLANED`, its `interval_end_utc` is set
        to the deplaning instant, its `tarmac_minutes` becomes the difference between
        `interval_end_utc` and `tarmac_start_utc` in whole minutes with the remainder
        dropped, and `is_violation` becomes true when `tarmac_minutes` is **strictly
        greater** than the event's `deadline_minutes` — occupying the tarmac for exactly the
        deadline is compliant."

        PRD §3.5: "On the deplaning branch, an event whose `is_violation` is true requires a
        narrative `corrective_action_summary`, and omitting it is
        `ERR_CORRECTIVE_ACTION_REQUIRED`; a compliant deplaned event needs no narrative."

        PRD §3.5: "The event's `version` advances by 1, the leg's
        `cumulative_tarmac_minutes` grows by the event's `tarmac_minutes`, and the leg's
        `version` advances by 1."

        Design: Corner/validations/violating_tarmac_report_without_corrective_summary_rejected
        """
        world = build_world(api, total_fare_cents=50000)
        segment = add_segment(
            api,
            world.booking["id"],
            segment_fare_cents=50000,
            scheduled_arrival_utc="2026-08-10T20:00:00Z",
        )
        event = validate_success(
            api.create_tarmac_delay_event(
                f.tarmac_event_payload(segment["id"], "2026-08-10T12:00:00Z", "DEPARTURE"),
                OPS_HEADERS,
            ),
            201,
        )
        validate_success(
            api.deplane_tarmac_event(
                event["id"], f.deplane_payload("2026-08-10T15:01:00Z"), OPS_HEADERS
            )
        )
        record_operation(api, segment["id"], "DEPARTED", "2026-08-10T15:05:00Z")

        refused = api.file_tarmac_report(
            event["id"],
            f.file_report_payload("DOT-2026-08-0001", "2026-08-11T09:00:00Z"),
            ADMIN_HEADERS,
        )

        validate_error(refused, ERR_CORRECTIVE_ACTION_REQUIRED, 422)
        stored = read_tarmac_event(api, event["id"], segment["id"])
        assert stored["tarmac_minutes"] == 181, "15:01 minus 12:00 is 181 whole minutes"
        assert stored["is_violation"] is True
        assert stored["status"] == "DEPLANED", "the refused filing left the event deplaned"
        assert_null(stored["report_reference"], "report_reference")
        assert_null(stored["report_filed_at_utc"], "report_filed_at_utc")
        assert_segment_state(
            read_segment(api, segment["id"]), cumulative_tarmac_minutes=181
        )

    def test_an_exemption_one_minute_past_the_deadline_is_refused(self, api):
        """The escape hatch closes at the deadline itself; the event stays open.

        PRD §3.5: "That instant must be strictly after `tarmac_start_utc`, or
        `ERR_TARMAC_WINDOW_INVALID`, and it must also fall at or before the deadline — the
        whole minutes between the start and the declaration, remainder dropped, must not
        exceed the event's `deadline_minutes`."

        PRD §3.5: "An exemption invoked once the deplaning deadline has already elapsed is
        refused with `ERR_EXEMPTION_AFTER_DEADLINE`: a carrier cannot retroactively excuse a
        deadline it has already blown."

        PRD §3.5: "A new event begins in `DELAY_ACTIVE` with `interval_end_utc` null,
        `tarmac_minutes` at 0 and `is_violation` false, and — importantly — with its
        `deadline_minutes` resolved and frozen at creation time from the leg's
        `is_international` flag and the booking's pinned policy profile: the international
        deplaning deadline for an international leg, the domestic one otherwise."

        PRD §2.9: "Every remaining configuration field is optional at creation and takes a
        regulatory default when omitted: `domestic_significant_delay_minutes` defaults to 180
        (three hours) and `international_significant_delay_minutes` to 360 (six hours);
        `credit_card_refund_deadline_days` defaults to 7 and `other_method_refund_deadline_days`
        to 20; `bag_delay_threshold_hours_domestic` defaults to 12 and
        `bag_delay_threshold_hours_international` to 30;
        `tarmac_deplane_deadline_minutes_domestic` defaults to 180 and
        `tarmac_deplane_deadline_minutes_international` to 240 (three and four hours
        respectively); `complaint_ack_deadline_days` defaults to 30,
        `complaint_answer_deadline_days_general` to 60 and
        `complaint_answer_deadline_days_disability` to 30; `travel_credit_default_permitted`
        defaults to false; and `travel_credit_election_bonus_pct` defaults to 0.10."

        Design: Corner/validations/exemption_invoked_one_minute_past_deplaning_deadline_rejected
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])
        segment_id = world.segments[0]["id"]
        event = validate_success(
            api.create_tarmac_delay_event(
                f.tarmac_event_payload(segment_id, "2026-08-10T12:00:00Z", "DEPARTURE"),
                OPS_HEADERS,
            ),
            201,
        )
        assert event["deadline_minutes"] == 180, "the domestic deadline is frozen at 180"

        refused = api.claim_tarmac_exemption(
            event["id"],
            f.exemption_payload("2026-08-10T15:01:00Z", "ATC_DIRECTIVE"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_EXEMPTION_AFTER_DEADLINE, 422)
        stored = read_tarmac_event(api, event["id"], segment_id)
        assert stored["deadline_minutes"] == 180
        assert stored["status"] == "DELAY_ACTIVE", "the refused exemption closed nothing"
        assert_null(stored["interval_end_utc"], "interval_end_utc")
        assert stored["tarmac_minutes"] == 0
        assert_null(stored["exemption_reason"], "exemption_reason")
        assert_null(stored["exemption_declared_at_utc"], "exemption_declared_at_utc")
        assert stored["version"] == 1, "a refused write changes no persisted field"
        assert_segment_state(
            read_segment(api, segment_id),
            cumulative_tarmac_minutes=0,
            exempted_tarmac_event_count=0,
        )


# ─── Guards on the money chain ────────────────────────


class TestSettlementGuards:
    def test_a_failed_outcome_needs_a_failure_reason(self, api):
        """No half-recorded failure: the attempt stays initiated and unexplained.

        PRD §3.7: "A `FAILED` outcome requires a `failure_reason` of `CARD_DECLINED`,
        `ACCOUNT_CLOSED` or `PROCESSOR_TIMEOUT`, omitting which is
        `ERR_FAILURE_REASON_REQUIRED`; it moves the axis `INITIATED → FAILED`, stores the
        reason as `last_failure_reason`, clears `settlement_initiated_by_user_id` back to
        null so the retry is unblocked for that officer, and advances the obligation's
        `version` by 1."

        PRD §3.7: "On success the settlement axis moves `UNSETTLED → INITIATED` (or `FAILED
        → INITIATED` on a retry), `settlement_attempt_count` increases by 1,
        `settlement_initiated_at_utc` is stamped from the logical clock's current instant,
        `settlement_initiated_by_user_id` is written from `X-User-ID`, and the obligation's
        `version` advances by 1."

        Design: Corner/validations/failed_settlement_without_failure_reason_rejected
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)
        elect(api, world.obligation["id"], "CASH", world.passenger_headers)
        initiate(api, world.obligation["id"], OFFICER_HEADERS)

        refused = api.complete_settlement(
            world.obligation["id"], f.complete_payload("FAILED"), ADMIN_HEADERS
        )

        validate_error(refused, ERR_FAILURE_REASON_REQUIRED, 422)
        obligation = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(
            obligation, settlement_status="INITIATED", settlement_attempt_count=1
        )
        assert_null(obligation["last_failure_reason"], "last_failure_reason")
        assert obligation["settlement_initiated_by_user_id"] == OFFICER_1, (
            "the initiating officer is still on the row"
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=50000
        )

    def test_settlement_cannot_start_before_the_election(self, api):
        """The settlement axis is legally UNSETTLED yet the election gate still bars it.

        PRD §3.7: "The election axis must have left `PENDING_ELECTION`, or the answer is
        `ERR_ELECTION_REQUIRED` — the carrier may not decide unilaterally what instrument to
        pay on."

        PRD §3.7: "The one point of contact is a gate, not a merge — the settlement axis
        cannot leave `UNSETTLED` until the election axis has left `PENDING_ELECTION`."

        PRD §3.6: "A newly minted obligation begins with `election_status` reading
        `PENDING_ELECTION`, `settlement_status` reading `UNSETTLED`,
        `settlement_attempt_count` at 0, `deadline_breached` false, and, for a direct create,
        `created_by_user_id` set from the caller's `X-User-ID`; obligations minted by a
        cascade leave `created_by_user_id` null."

        Design: Corner/validations/initiate_settlement_before_election_rejected
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)

        refused = api.initiate_settlement(
            world.obligation["id"], f.initiate_payload(), OFFICER_HEADERS
        )

        validate_error(refused, ERR_ELECTION_REQUIRED, 409)
        obligation = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(
            obligation,
            election_status="PENDING_ELECTION",
            settlement_status="UNSETTLED",
            settlement_attempt_count=0,
        )
        assert_null(
            obligation["settlement_initiated_by_user_id"],
            "settlement_initiated_by_user_id",
        )

    def test_a_settled_obligation_cannot_be_voided_as_a_data_entry_error(self, api):
        """An accounting reversal may not be disguised as a correction.

        PRD §3.7: "From `UNSETTLED` or `FAILED` the reason must be `CREATED_IN_ERROR`,
        `DUPLICATE` or `PASSENGER_WITHDREW`; from `SETTLED` the only acceptable reason is
        `SETTLEMENT_REVERSED`, which records that the processor clawed the money back."

        PRD §3.7: "Any other pairing — `SETTLEMENT_REVERSED` on an obligation that was never
        settled, an ordinary reason on a settled obligation, or any void of an already-voided
        obligation — is `ERR_OBLIGATION_NOT_VOIDABLE`."

        PRD §3.7: "The instrument is a projection of how the ticket was paid for: a
        `CREDIT_CARD` booking resolves to `ORIGINAL_PAYMENT`, a `CASH_OR_CHECK` booking to
        `CASH_OR_CHECK`, a `MILES` booking to `MILES`, and a booking originally paid for in
        travel credit resolves back to `TRAVEL_CREDIT` even on a cash election — a passenger
        cannot launder credit into cash by electing cash."

        PRD §3.7: "The booking's `earliest_refund_deadline_utc` and `disruption_posture` are
        then recomputed, the posture reaching `CLOSED_OUT` once every obligation of the
        booking is settled or voided, and the booking's `version` advances by 1."

        Design: Corner/validations/settled_obligation_void_with_wrong_reason_rejected
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)
        elect(api, world.obligation["id"], "CASH", world.passenger_headers)
        initiate(api, world.obligation["id"], OFFICER_HEADERS)
        validate_success(
            api.complete_settlement(
                world.obligation["id"], f.complete_payload("SUCCEEDED"), ADMIN_HEADERS
            )
        )

        refused = api.void_refund_obligation(
            world.obligation["id"], f.void_payload("CREATED_IN_ERROR"), ADMIN_HEADERS
        )

        validate_error(refused, ERR_OBLIGATION_NOT_VOIDABLE, 409)
        obligation = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(
            obligation, settlement_status="SETTLED", settlement_method="ORIGINAL_PAYMENT"
        )
        assert_null(obligation["void_reason"], "void_reason")
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=50000,
            disruption_posture="CLOSED_OUT",
        )


# ─── Reporting period bounds ──────────────────────────


class TestReportPeriodBounds:
    def test_an_inverted_reporting_period_is_refused(self, api):
        """A rejected open consumes neither the profile's counter nor its version.

        PRD §3.9: "A `ComplianceAdmin` opens a report by naming the `policy_profile_id`, a
        `period_start_utc`, a `period_end_utc` strictly later than the start, and the
        `expected_policy_profile_version` guard of §2.6; a start at or after the end is
        `ERR_PERIOD_BOUNDS_INVALID`."

        PRD §3.9: "A new report opens in `DRAFT` with all seven metrics at 0,
        `policy_version_pinned` at 0 and `amendment_count` at 0; opening it also increases the
        profile's `report_count` and advances the profile's `version` by 1, which is why two
        reports cannot be opened back to back against one stale profile version."

        PRD §2.9: "Both start at 0, and the profile's `version` starts at 1 and advances
        whenever either counter's value changes — which is precisely why report creation is
        guarded by a version check (§2.6)."

        Design: Corner/validations/report_period_bounds_inverted_rejected
        """
        profile = create_policy_profile(api, "ZQ")

        refused = api.create_regulator_report(
            f.report_payload(
                profile["id"],
                profile["version"],
                period_start_utc="2026-07-31T23:59:59Z",
                period_end_utc="2026-07-01T00:00:00Z",
            ),
            ADMIN_HEADERS,
        )

        validate_error(refused, ERR_PERIOD_BOUNDS_INVALID, 422)
        stored = read_profile(api, profile["id"])
        assert stored["report_count"] == 0, "no report was opened"
        assert stored["version"] == 1, "a refused open consumes no profile version"
        _, meta = validate_paginated(
            api.list_policy_profile_reports(profile["id"], ADMIN_HEADERS)
        )
        assert_list_meta(meta, total_count=0, has_more=False)


# ─── Deadline instants are not yet breaches ───────────


class TestStrictDeadlineBoundaries:
    def test_a_complaint_is_not_answer_breached_at_its_answer_due_instant(self, api):
        """Sixty days to the second is still compliant; one second later is a violation.

        PRD §2.7: "Deadline breach flags — the refund settlement deadline, the complaint
        acknowledgement deadline and the complaint answer deadline — all use strict
        comparisons against the logical clock, so at the exact deadline instant nothing is yet
        breached."

        PRD §3.8: "`answer_due_utc` is the substantive-answer window added to
        `received_at_utc`, and here the category matters: a `DISABILITY` complaint gets the
        shortened disability window of 30 days by default, while every other category gets the
        general window of 60 days."

        PRD §3.9: "For every complaint in scope, `ack_breached` becomes true when the logical
        clock has strictly passed `ack_due_utc` while `acknowledged_at_utc` is still null, and
        `answer_breached` becomes true when the clock has strictly passed `answer_due_utc`
        while the complaint's `status` is neither `ANSWERED` nor `CLOSED`."

        PRD §3.9: "The profile's `open_violation_count` is rewritten as the sum of three
        counts in scope: tarmac delay events whose `is_violation` is true, refund obligations
        whose `deadline_breached` is true, and consumer complaints whose `ack_breached` or
        `answer_breached` is true."

        Design: Corner/validations/complaint_not_answer_breached_at_exact_answer_due_instant
        """
        world = build_world(api)
        complaint = file_complaint(api, world.booking["id"])
        assert_instant(complaint["answer_due_utc"], "2026-10-04T09:00:00Z")
        acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")

        set_clock(api, "2026-10-04T09:00:00Z")
        at_the_instant = run_sweep(api, world.profile["id"])

        assert_sweep_counters(
            at_the_instant,
            complaint_ack_breach_flagged_count=0,
            complaint_answer_breach_flagged_count=0,
            open_violation_count=0,
        )
        pending = read_complaint(api, complaint["id"])
        assert pending["answer_breached"] is False, "the due instant itself is compliant"
        assert pending["ack_breached"] is False
        assert pending["status"] == "ACKNOWLEDGED"

        set_clock(api, "2026-10-04T09:00:01Z")
        one_second_later = run_sweep(api, world.profile["id"])

        assert_sweep_counters(
            one_second_later,
            complaint_ack_breach_flagged_count=0,
            complaint_answer_breach_flagged_count=1,
            open_violation_count=1,
        )
        breached = read_complaint(api, complaint["id"])
        assert breached["answer_breached"] is True
        assert breached["ack_breached"] is False, "it was acknowledged in time"
        assert breached["status"] == "ACKNOWLEDGED"

    def test_an_obligation_is_not_deadline_breached_at_its_deadline_instant(self, api):
        """The seven-day instant auto-defaults the election yet flags no breach.

        PRD §3.6: "From the start instant, `deadline_utc` is the settlement deadline: the
        number of days configured for credit-card payments when the booking's `payment_method`
        is `CREDIT_CARD`, and the number configured for every other form of payment otherwise
        — seven days against twenty days under the regulatory defaults, which is why the form
        of payment collected at booking time still matters months later."

        PRD §3.6: "And `election_deadline_utc` is five days after the start instant, this
        election window being a statutory constant the carrier cannot tune."

        PRD §3.9: "For every obligation in scope, `deadline_breached` becomes true when the
        logical clock has passed `deadline_utc` strictly and the obligation's
        `settlement_status` is neither `SETTLED` nor `VOIDED`."

        PRD §3.9: "For every obligation whose `election_status` still reads
        `PENDING_ELECTION` and whose `election_deadline_utc` the logical clock has strictly
        passed, the election axis advances `PENDING_ELECTION → ELECTED_CASH` with
        `election_source` recorded as `AUTO_DEFAULT` and the `settlement_method` resolved from
        the booking's `payment_method` exactly as in §3.7."

        Design: Corner/validations/obligation_not_deadline_breached_at_exact_deadline_instant
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)
        assert_obligation_deadlines(
            world.obligation,
            obligation_start_utc="2026-08-10T10:00:00Z",
            election_deadline_utc="2026-08-15T10:00:00Z",
            deadline_utc="2026-08-17T10:00:00Z",
        )

        set_clock(api, "2026-08-17T10:00:00Z")
        at_the_instant = run_sweep(api, world.profile["id"])

        assert_sweep_counters(
            at_the_instant,
            deadline_breach_flagged_count=0,
            election_auto_defaulted_count=1,
            open_violation_count=0,
        )
        pending = read_obligation(api, world.obligation["id"])
        assert pending["deadline_breached"] is False, "the deadline instant is not a breach"
        assert_obligation_axes(
            pending,
            election_status="ELECTED_CASH",
            election_source="AUTO_DEFAULT",
            settlement_method="ORIGINAL_PAYMENT",
            settlement_status="UNSETTLED",
        )

        set_clock(api, "2026-08-17T10:00:01Z")
        one_second_later = run_sweep(api, world.profile["id"])

        assert_sweep_counters(
            one_second_later,
            deadline_breach_flagged_count=1,
            election_auto_defaulted_count=0,
            open_violation_count=1,
        )
        breached = read_obligation(api, world.obligation["id"])
        assert breached["deadline_breached"] is True
        assert_obligation_axes(breached, settlement_status="UNSETTLED")
