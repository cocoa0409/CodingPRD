"""The read and control surfaces the contract exposes, exercised end to end."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ERR_COMPLAINT_STATE_INVALID,
    OFFICER_HEADERS,
    OPS_HEADERS,
    acknowledge,
    answer,
    assert_activity_types,
    assert_booking_ledger,
    assert_instant,
    assert_list_meta,
    assert_no_version_fields,
    assert_null,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_segment_state,
    assert_sweep_counters,
    build_world,
    cancelled_booking_with_obligation,
    create_booking,
    create_passenger,
    create_policy_profile,
    factories as f,
    file_complaint,
    list_activities,
    read_booking,
    read_complaint,
    read_obligation,
    read_passenger,
    read_profile,
    read_segment,
    read_tarmac_event,
    record_operation,
    run_sweep,
)

# ─── The complaint activity trail ─────────────────────


def _worked_complaint(api):
    """One complaint carried through receipt, acknowledgement, a query and an answer."""
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api)
    booking = create_booking(api, passenger["id"], profile["id"])
    complaint = file_complaint(api, booking["id"])
    acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")
    validate_success(
        api.request_complaint_info(
            complaint["id"],
            f.request_info_payload(
                "2026-08-07T11:00:00Z", info_request_note="Please send the card statement."
            ),
            OFFICER_HEADERS,
        )
    )
    answer(api, complaint["id"], "2026-08-08T12:00:00Z")
    return complaint


class TestComplaintActivityTrail:
    def test_the_trail_replays_the_whole_lifecycle_in_chronological_order(self, api):
        """Four events, one row apiece, ordered by the instants the office recorded.

        PRD §3.8: "Everything that happens to a complaint is written to an append-only
        **activity trail**, one row per event, immutable once written and never updated."

        PRD §3.8: "A newly filed complaint sits in `RECEIVED` with `info_requested_count` and
        `reopen_count` at 0 and both `ack_breached` and `answer_breached` false, appends an
        activity row of type `RECEIVED` to its trail, and refreshes the passenger's
        `open_complaint_count`, advancing the passenger's `version` by 1."

        PRD §3.8: "Each of the four appends an activity row of the matching type:
        `ACKNOWLEDGED`, `INFO_REQUESTED`, `ANSWERED` and `REOPENED` respectively."

        PRD §3.8: "The trail is read in ascending `occurred_at_utc` order, tie-broken by
        ascending `created_at`, and is visible to compliance roles and the regulator auditor
        but not to the passenger."

        Design: Corner/endpoints/activities_log_returns_whole_lifecycle_in_chronological_order
        """
        complaint = _worked_complaint(api)

        rows, meta = validate_paginated(
            api.list_complaint_activities(complaint["id"], AUDITOR_HEADERS)
        )

        assert_list_meta(meta, total_count=4, has_more=False)
        assert_activity_types(
            rows, ["RECEIVED", "ACKNOWLEDGED", "INFO_REQUESTED", "ANSWERED"]
        )
        assert_instant(rows[0]["occurred_at_utc"], "2026-08-05T09:00:00Z")
        assert_instant(rows[1]["occurred_at_utc"], "2026-08-06T10:00:00Z")
        assert_instant(rows[2]["occurred_at_utc"], "2026-08-07T11:00:00Z")
        assert_instant(rows[3]["occurred_at_utc"], "2026-08-08T12:00:00Z")
        worked = read_complaint(api, complaint["id"])
        assert worked["status"] == "ANSWERED"
        assert worked["info_requested_count"] == 1

    def test_filtering_the_trail_narrows_the_count_and_never_mutates_a_row(self, api):
        """One row comes back on the activity_type filter, and it carries no version.

        PRD §2.4: "The complaint activity trail is append-only and immutable: an activity row
        carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because
        nothing ever modifies it."

        PRD §2.3: "The four pagination fields — `limit`, `offset`, `total_count` and
        `has_more` — appear in the `meta` object of every list response, where `total_count` is
        the number of rows matching the filters before the page window is applied and
        `has_more` indicates whether rows remain beyond the current window."

        Design: Corner/endpoints/activities_log_returns_whole_lifecycle_in_chronological_order
        """
        complaint = _worked_complaint(api)

        rows, meta = validate_paginated(
            api.list_complaint_activities(
                complaint["id"], AUDITOR_HEADERS, activity_type="INFO_REQUESTED"
            )
        )

        assert_list_meta(meta, total_count=1, has_more=False)
        assert_activity_types(rows, ["INFO_REQUESTED"])
        assert_instant(rows[0]["occurred_at_utc"], "2026-08-07T11:00:00Z")
        for row in list_activities(api, complaint["id"]):
            assert_no_version_fields(row)


# ─── Asking the passenger a question ──────────────────


def _acknowledged_phone_complaint(api):
    """An acknowledged REFUND complaint that reached the carrier by telephone."""
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api)
    booking = create_booking(api, passenger["id"], profile["id"])
    complaint = file_complaint(
        api,
        booking["id"],
        channel="PHONE",
        summary="Voucher pushed instead of cash.",
    )
    acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")
    return complaint


class TestInformationRequests:
    def test_asking_for_documents_buys_the_carrier_no_extra_time(self, api):
        """The counter moves to 1 while both statutory due instants stand still.

        PRD §3.8: "Requesting more information supplies an `info_request_note` and a
        `requested_at_utc` at or after `acknowledged_at_utc`, drives `ACKNOWLEDGED →
        INFO_REQUESTED`, and increases `info_requested_count` by 1 — but pointedly does **not**
        extend `answer_due_utc`, because asking the passenger a question does not buy the
        carrier more time."

        PRD §3.8: "`answer_due_utc` is the substantive-answer window added to
        `received_at_utc`, and here the category matters: a `DISABILITY` complaint gets the
        shortened disability window of 30 days by default, while every other category gets the
        general window of 60 days."

        PRD §3.8: "`ack_due_utc` is the profile's acknowledgement window added to
        `received_at_utc` — 30 days by default, for every category alike."

        PRD §2.4: "All entities except the complaint activity trail additionally carry
        `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and
        `version`, an integer that begins at 1 when the row is created and increases by exactly
        1 on each request that changes the row's persisted field values."

        Design: Corner/endpoints/request_info_increments_counter_without_extending_answer_due
        """
        complaint = _acknowledged_phone_complaint(api)
        assert_instant(complaint["answer_due_utc"], "2026-10-04T09:00:00Z")

        queried = validate_success(
            api.request_complaint_info(
                complaint["id"],
                f.request_info_payload(
                    "2026-08-07T11:00:00Z",
                    info_request_note="Send the itinerary receipt.",
                ),
                OFFICER_HEADERS,
            )
        )

        assert queried["status"] == "INFO_REQUESTED"
        assert queried["info_requested_count"] == 1
        assert_instant(queried["answer_due_utc"], "2026-10-04T09:00:00Z")
        assert_instant(queried["ack_due_utc"], "2026-09-04T09:00:00Z")
        assert queried["version"] == 3, "create, acknowledge, request-info"

    def test_a_second_request_from_info_requested_is_refused(self, api):
        """INFO_REQUESTED is not a legal source state, and the refusal costs no counter.

        PRD §3.8: "Any of these chronology rules being violated is
        `ERR_ANSWER_BEFORE_RECEIPT` (HTTP 422), and an action attempted from the wrong status —
        acknowledging something not `RECEIVED`, requesting information on something not
        `ACKNOWLEDGED`, answering something that is neither `ACKNOWLEDGED` nor
        `INFO_REQUESTED`, or reopening something not `ANSWERED` — is
        `ERR_COMPLAINT_STATE_INVALID` (HTTP 409)."

        PRD §3.8: "Each of the four appends an activity row of the matching type:
        `ACKNOWLEDGED`, `INFO_REQUESTED`, `ANSWERED` and `REOPENED` respectively."

        Design: Corner/endpoints/request_info_increments_counter_without_extending_answer_due
        """
        complaint = _acknowledged_phone_complaint(api)
        validate_success(
            api.request_complaint_info(
                complaint["id"],
                f.request_info_payload(
                    "2026-08-07T11:00:00Z",
                    info_request_note="Send the itinerary receipt.",
                ),
                OFFICER_HEADERS,
            )
        )

        refused = api.request_complaint_info(
            complaint["id"],
            f.request_info_payload(
                "2026-08-08T11:00:00Z", info_request_note="Also send the boarding pass."
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_COMPLAINT_STATE_INVALID, 409)
        stored = read_complaint(api, complaint["id"])
        assert stored["info_requested_count"] == 1, "the refusal appended nothing"
        assert stored["status"] == "INFO_REQUESTED"
        assert_activity_types(
            list_activities(api, complaint["id"]),
            ["RECEIVED", "ACKNOWLEDGED", "INFO_REQUESTED"],
        )


# ─── A compliant tarmac occupation ────────────────────


def _deplaned_within_the_deadline(api):
    """Sixty minutes on the tarmac of a domestic leg, closed by deplaning."""
    world = build_world(api, segment_fares=[50000])
    segment = world.segments[0]
    event = validate_success(
        api.create_tarmac_delay_event(f.tarmac_event_payload(segment["id"]), OPS_HEADERS),
        201,
    )
    validate_success(
        api.deplane_tarmac_event(
            event["id"], f.deplane_payload("2026-08-10T13:00:00Z"), OPS_HEADERS
        )
    )
    return world, segment, event


class TestCompliantTarmacOccupation:
    def test_an_hour_on_the_tarmac_is_no_violation_on_a_domestic_leg(self, api):
        """Sixty whole minutes against a frozen 180-minute deadline.

        PRD §3.5: "The event moves `DELAY_ACTIVE → DEPLANED`, its `interval_end_utc` is set to
        the deplaning instant, its `tarmac_minutes` becomes the difference between
        `interval_end_utc` and `tarmac_start_utc` in whole minutes with the remainder dropped,
        and `is_violation` becomes true when `tarmac_minutes` is **strictly greater** than the
        event's `deadline_minutes` — occupying the tarmac for exactly the deadline is
        compliant."

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

        PRD §3.5: "The event's `version` advances by 1, the leg's `cumulative_tarmac_minutes`
        grows by the event's `tarmac_minutes`, and the leg's `version` advances by 1."

        Design: Corner/endpoints/compliant_tarmac_event_files_report_without_corrective_summary
        """
        _, segment, event = _deplaned_within_the_deadline(api)

        closed = read_tarmac_event(api, event["id"], segment["id"])
        assert closed["status"] == "DEPLANED"
        assert closed["deadline_minutes"] == 180
        assert closed["tarmac_minutes"] == 60
        assert closed["is_violation"] is False, "an hour is well inside three hours"
        assert_instant(closed["interval_end_utc"], "2026-08-10T13:00:00Z")
        assert_segment_state(
            read_segment(api, segment["id"]),
            cumulative_tarmac_minutes=60,
            exempted_tarmac_event_count=0,
        )

    def test_a_compliant_event_files_its_report_with_no_corrective_narrative(self, api):
        """The narrative field stays null and the event reaches its terminal state.

        PRD §3.5: "On the deplaning branch, an event whose `is_violation` is true requires a
        narrative `corrective_action_summary`, and omitting it is
        `ERR_CORRECTIVE_ACTION_REQUIRED`; a compliant deplaned event needs no narrative."

        PRD §3.5: "Filing moves the event to `REPORT_FILED` — its terminal state, reached from
        either fork — storing `report_reference`, the `corrective_action_summary` when one was
        supplied, and `report_filed_at_utc` from the supplied `filed_at_utc`, and advancing the
        event's `version` by 1."

        PRD §2.9: "`report_count` increases by 1 each time a regulator report is opened
        against the profile, and `open_violation_count` is rewritten by the compliance sweep
        (§3.9). Both start at 0, and the profile's `version` starts at 1 and advances whenever
        either counter's value changes — which is precisely why report creation is guarded by a
        version check (§2.6)."

        Design: Corner/endpoints/compliant_tarmac_event_files_report_without_corrective_summary
        """
        world, segment, event = _deplaned_within_the_deadline(api)
        record_operation(api, segment["id"], "DEPARTED", "2026-08-10T13:05:00Z")

        filed = validate_success(
            api.file_tarmac_report(event["id"], f.file_report_payload(), ADMIN_HEADERS)
        )

        assert filed["status"] == "REPORT_FILED"
        assert_null(filed["corrective_action_summary"], "corrective_action_summary")
        assert filed["report_reference"] == "DOT-TARMAC-0001"
        assert_instant(filed["report_filed_at_utc"], "2026-08-11T09:00:00Z")
        assert filed["version"] == 3, "create, deplane, file-report"
        assert_segment_state(
            read_segment(api, segment["id"]),
            status="DEPARTED",
            cumulative_tarmac_minutes=60,
            exempted_tarmac_event_count=0,
        )
        assert read_profile(api, world.profile["id"])["open_violation_count"] == 0


# ─── The logical clock's startup default ──────────────


def _unacknowledged_complaint_on_a_virgin_clock(api):
    """A never-acknowledged web complaint, with the clock left untouched."""
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api)
    booking = create_booking(api, passenger["id"], profile["id"])
    complaint = file_complaint(
        api,
        booking["id"],
        category="OTHER",
        channel="WEB",
        summary="No response from the carrier.",
    )
    return profile, complaint


class TestLogicalClockStartupDefault:
    def test_a_sweep_on_an_untouched_clock_flags_nothing(self, api):
        """The startup instant sits a month before the acknowledgement deadline.

        PRD §2.8: "Before any client sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`; this startup default is mandatory and the server never falls
        back to real time."

        PRD §3.8: "`ack_due_utc` is the profile's acknowledgement window added to
        `received_at_utc` — 30 days by default, for every category alike."

        PRD §3.9: "For every complaint in scope, `ack_breached` becomes true when the logical
        clock has strictly passed `ack_due_utc` while `acknowledged_at_utc` is still null, and
        `answer_breached` becomes true when the clock has strictly passed `answer_due_utc` while
        the complaint's `status` is neither `ANSWERED` nor `CLOSED`."

        Design: Corner/endpoints/clock_startup_default_is_2026_08_01_and_set_endpoint_echoes_instant
        """
        profile, complaint = _unacknowledged_complaint_on_a_virgin_clock(api)
        assert_instant(complaint["ack_due_utc"], "2026-09-04T09:00:00Z")

        swept = run_sweep(api, profile["id"])

        assert_sweep_counters(
            swept, complaint_ack_breach_flagged_count=0, open_violation_count=0
        )
        pending = read_complaint(api, complaint["id"])
        assert pending["ack_breached"] is False
        assert pending["status"] == "RECEIVED"

    def test_setting_the_clock_echoes_the_instant_without_touching_a_row(self, api):
        """The control endpoint reports the new setting; only the next sweep writes flags.

        PRD §2.8: "A `ComplianceAdmin` may move the clock to an explicit instant by supplying
        a `to_iso8601` value; the response reports the new setting as `current_utc`."

        PRD §2.8: "Setting the clock mutates no entity and advances no `version` — it only
        changes the instant that every subsequent deadline, breach, election-window and
        auto-close evaluation reads."

        PRD §3.9: "The profile's `open_violation_count` is rewritten as the sum of three counts
        in scope: tarmac delay events whose `is_violation` is true, refund obligations whose
        `deadline_breached` is true, and consumer complaints whose `ack_breached` or
        `answer_breached` is true."

        Design: Corner/endpoints/clock_startup_default_is_2026_08_01_and_set_endpoint_echoes_instant
        """
        profile, complaint = _unacknowledged_complaint_on_a_virgin_clock(api)
        run_sweep(api, profile["id"])
        version_before = read_complaint(api, complaint["id"])["version"]

        moved = validate_success(api.set_clock("2026-09-05T00:00:00Z", ADMIN_HEADERS))

        assert_instant(moved["current_utc"], "2026-09-05T00:00:00Z")
        assert read_complaint(api, complaint["id"])["version"] == version_before, (
            "the clock call mutated no entity"
        )

        swept = run_sweep(api, profile["id"])

        assert_sweep_counters(
            swept, complaint_ack_breach_flagged_count=1, open_violation_count=1
        )
        breached = read_complaint(api, complaint["id"])
        assert breached["ack_breached"] is True
        assert breached["status"] == "RECEIVED"


# ─── An officer electing credit on the passenger's behalf ──


def _obligation_with_a_consent_complaint(api):
    """A 50000-cent fare obligation plus a written-consent complaint on the same booking."""
    world = cancelled_booking_with_obligation(api, total_fare_cents=50000)
    world.consent = file_complaint(
        api,
        world.booking["id"],
        received_at_utc="2026-08-11T09:00:00Z",
        summary="Passenger consents in writing to travel credit.",
    )
    return world


class TestOfficerCreditElectionOnBehalf:
    def test_the_election_stores_the_consent_link_and_names_the_officer_as_actor(self, api):
        """The cited complaint id is persisted, not merely validated and discarded.

        PRD §3.7: "Whoever elects, `election_source` records who chose: `PASSENGER` when the
        caller acted under the `Passenger` role and `OFFICER_ON_BEHALF` when a compliance role
        acted for them."

        PRD §3.7: "Because moving a passenger onto travel credit gives up their right to cash,
        a compliance role electing `TRAVEL_CREDIT` on the passenger's behalf must cite a consent
        artefact: `consent_complaint_id` becomes mandatory, and omitting it is
        `ERR_CREDIT_CONSENT_REQUIRED`."

        PRD §3.7: "When supplied, its id is stored on the obligation as
        `credit_consent_reference`."

        Design: Corner/endpoints/officer_credit_election_links_the_consent_complaint_reference
        """
        world = _obligation_with_a_consent_complaint(api)

        elected = validate_success(
            api.elect_refund_obligation(
                world.obligation["id"],
                f.elect_payload("TRAVEL_CREDIT", consent_complaint_id=world.consent["id"]),
                OFFICER_HEADERS,
            )
        )

        assert_obligation_axes(
            elected,
            election_status="ELECTED_CREDIT",
            election_source="OFFICER_ON_BEHALF",
            settlement_method="TRAVEL_CREDIT",
            settlement_status="UNSETTLED",
        )
        assert elected["credit_consent_reference"] == world.consent["id"], (
            "the consent artefact is linked on the row"
        )

    def test_the_goodwill_bonus_sits_outside_both_conserved_ledgers(self, api):
        """55000 payable, yet the obligated ledger holds 50000 and no credit is issued yet.

        PRD §3.7: "Electing `TRAVEL_CREDIT` sets `election_status` to `ELECTED_CREDIT` and
        `settlement_method` to `TRAVEL_CREDIT`, and adds the goodwill bonus: `credit_bonus_cents`
        is the obligation's `amount_cents` multiplied by the profile's
        `travel_credit_election_bonus_pct` and rounded half up — one tenth of the principal under
        the regulatory default — and `payable_total_cents` becomes `amount_cents` plus that
        bonus."

        PRD §3.7: "The booking's `total_refund_obligated_cents` is deliberately **not** changed
        by the bonus: goodwill sits outside the obligated-money ledger and outside the consumed
        figure that headroom subtracts, so electing credit never shrinks the headroom available
        to obligations minted later."

        PRD §2.11: "A passenger's `travel_credit_balance_cents` must always equal the sum of
        `payable_total_cents` over every obligation on that passenger's bookings whose settlement
        method is travel credit and whose settlement axis reads settled."

        Design: Corner/endpoints/officer_credit_election_links_the_consent_complaint_reference
        """
        world = _obligation_with_a_consent_complaint(api)
        validate_success(
            api.elect_refund_obligation(
                world.obligation["id"],
                f.elect_payload("TRAVEL_CREDIT", consent_complaint_id=world.consent["id"]),
                OFFICER_HEADERS,
            )
        )

        stored = read_obligation(api, world.obligation["id"])
        assert_obligation_amounts(
            stored, amount_cents=50000, credit_bonus_cents=5000, payable_total_cents=55000
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=50000
        )
        passenger = read_passenger(api, world.passenger["id"])
        assert passenger["travel_credit_balance_cents"] == 0, (
            "the credit posts only at settlement"
        )
