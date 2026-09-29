"""Who may do what, and what the persisted actor trail refuses to let them do twice."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    OFFICER_1,
    OFFICER_2,
    OFFICER_2_HEADERS,
    OFFICER_HEADERS,
    OPS_HEADERS,
    acknowledge,
    assert_activity_types,
    assert_booking_ledger,
    assert_exposure,
    assert_list_meta,
    assert_null,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_segment_state,
    booking_version,
    build_world,
    cancel_segment,
    cancelled_booking_with_obligation,
    complete,
    create_booking,
    create_passenger,
    create_policy_profile,
    elect,
    factories as f,
    file_complaint,
    initiate,
    make_passenger_headers,
    obligations_with_meta,
    open_report,
    read_booking,
    read_exposure,
    read_obligation,
    read_passenger,
    read_profile,
    read_segment,
    sole_obligation,
    void,
)

# ─── The read-only regulator ──────────────────────────


class TestRegulatorAuditorHoldsNoWrite:
    def test_the_auditor_cannot_open_a_booking_the_officer_can(self, api):
        """A perfectly valid body is refused on the role alone, and nothing is stored.

        PRD §2.1: "A `RegulatorAuditor` is strictly read-only across the entire surface,
        including filed reports and the complaint activity log, and holds no write capability of
        any kind."

        PRD §2.1: "A recognised role that is simply not authorised for the endpoint it called is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); §4 lists the authorised roles for each
        endpoint."

        PRD §2.4: "All entities except the complaint activity trail additionally carry
        `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and `version`,
        an integer that begins at 1 when the row is created and increases by exactly 1 on each
        request that changes the row's persisted field values."

        Design: Corner/rbac/regulator_auditor_cannot_create_a_booking
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api)
        body = f.booking_payload(passenger["id"], profile["id"])

        refused = api.create_booking(body, AUDITOR_HEADERS)

        validate_error(refused, ERR_FORBIDDEN_ROLE, 403)
        assert read_passenger(api, passenger["id"])["version"] == 1
        _, meta = validate_paginated(api.list_bookings(ADMIN_HEADERS))
        assert_list_meta(meta, total_count=0, has_more=False)

        accepted = validate_success(api.create_booking(body, OFFICER_HEADERS), 201)

        assert accepted["record_locator"] == "ABC123"


# ─── Operations has no authority over money ───────────


class TestOpsControllerCannotMintMoney:
    def test_the_role_check_beats_the_version_guard_on_an_obligation_create(self, api):
        """A stale expected_booking_version never gets read: authorisation runs first.

        PRD §2.1: "An `OpsController` owns operational truth about flights — segment creation,
        disruption declarations, departure/arrival/restore events and tarmac occupation records —
        and has no authority over money, complaints or filings."

        PRD §2.5: "**Endpoint authorisation** — the caller's role must appear among the
        endpoint's authorised roles; otherwise `ERR_FORBIDDEN_ROLE`."

        PRD §2.5: "**Ledger-parent version match** — the optimistic-concurrency guards of §2.6,
        rejected with HTTP 412."

        Design: Corner/rbac/ops_controller_cannot_mint_a_refund_obligation
        """
        world = build_world(api, segment_fares=[50000])
        assert booking_version(api, world.booking["id"]) == 2, "create plus one leg"

        refused = api.create_refund_obligation(
            f.obligation_payload(
                world.booking["id"],
                1,
                issuance_mode="REQUEST_BASED",
                flight_segment_id=world.segments[0]["id"],
            ),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_FORBIDDEN_ROLE, 403)
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, total_count=0, has_more=False)
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=0
        )


# ─── Voiding is the admin's alone ─────────────────────


class TestVoidIsAdminExclusive:
    def test_the_case_worker_cannot_erase_the_obligation_they_work(self, api):
        """The officer's void is refused and the obligated ledger keeps its 50000.

        PRD §2.1: "A `ComplianceOfficer` is the case worker: they mint obligations, record
        elections, initiate settlements and work consumer complaints, but they cannot void an
        obligation, cannot file a tarmac report, cannot submit a regulator filing, and cannot
        complete a settlement they themselves initiated."

        PRD §2.1: "A recognised role that is simply not authorised for the endpoint it called is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); §4 lists the authorised roles for each
        endpoint."

        Design: Corner/rbac/compliance_officer_cannot_void_an_obligation
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)

        refused = api.void_refund_obligation(
            world.obligation["id"], f.void_payload("CREATED_IN_ERROR"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_FORBIDDEN_ROLE, 403)
        untouched = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(untouched, settlement_status="UNSETTLED")
        assert_null(untouched["void_reason"], "void_reason")
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=50000
        )

    def test_the_identical_reason_from_the_admin_voids_and_restores_the_ledger(self, api):
        """Same body, different role: the obligated ledger falls back to zero.

        PRD §3.7: "Voiding is a `ComplianceAdmin` power, and the acceptable `void_reason`
        depends on where the settlement axis stands."

        PRD §3.7: "A void sets the settlement axis to `VOIDED`, stores the `void_reason`,
        advances the obligation's `version` by 1, and recomputes the booking's
        `total_refund_obligated_cents` (now excluding this row), `earliest_refund_deadline_utc`
        and `disruption_posture`, advancing the booking's `version` by 1 — restoring the conserved
        ledger of §2.11 exactly."

        Design: Corner/rbac/compliance_officer_cannot_void_an_obligation
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)

        void(api, world.obligation["id"], "CREATED_IN_ERROR")

        voided = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(voided, settlement_status="VOIDED")
        assert voided["void_reason"] == "CREATED_IN_ERROR"
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=0
        )


# ─── The one override the admin does not get ──────────


class TestSettlementInitiationIsOfficerExclusive:
    def test_the_admin_may_not_start_the_money_moving(self, api):
        """The head of the office is refused where the case worker succeeds.

        PRD §2.1: "Initiating settlement is reserved to `ComplianceOfficer` alone, so that no
        single person can drive an obligation from creation through payment."

        PRD §3.7: "Initiating settlement is reserved to a `ComplianceOfficer` and requires a
        `processor_reference` identifying the payment instruction."

        PRD §3.7: "On success the settlement axis moves `UNSETTLED → INITIATED` (or `FAILED →
        INITIATED` on a retry), `settlement_attempt_count` increases by 1,
        `settlement_initiated_at_utc` is stamped from the logical clock's current instant,
        `settlement_initiated_by_user_id` is written from `X-User-ID`, and the obligation's
        `version` advances by 1."

        PRD §2.10: "`created_by_user_id` is written from `X-User-ID` when an officer mints an
        obligation directly and is left null for obligations minted by a system cascade, which
        means a cascade-created obligation can be initiated by anyone authorised."

        Design: Corner/rbac/compliance_admin_cannot_initiate_a_settlement
        """
        world = cancelled_booking_with_obligation(api, total_fare_cents=50000)
        elect(api, world.obligation["id"], "CASH", world.passenger_headers)

        refused = api.initiate_settlement(
            world.obligation["id"], f.initiate_payload(), ADMIN_HEADERS
        )

        validate_error(refused, ERR_FORBIDDEN_ROLE, 403)
        blocked = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(
            blocked, settlement_status="UNSETTLED", settlement_attempt_count=0
        )
        assert_null(
            blocked["settlement_initiated_by_user_id"], "settlement_initiated_by_user_id"
        )

        started = initiate(api, world.obligation["id"], OFFICER_HEADERS)

        assert_obligation_axes(
            started, settlement_status="INITIATED", settlement_attempt_count=1
        )
        assert started["settlement_initiated_by_user_id"] == OFFICER_1
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=50000
        )


# ─── One passenger, one set of rows ───────────────────


def _owner_and_stranger(api):
    """Pat owns a cancelled booking and its obligation; Bob owns nothing."""
    world = cancelled_booking_with_obligation(api, total_fare_cents=50000)
    world.stranger = create_passenger(api, "bob@example.com", "Bob Nadal")
    world.stranger_headers = make_passenger_headers(world.stranger["id"])
    return world


class TestPassengerOwnership:
    def test_a_stranger_learns_nothing_from_the_response_code(self, api):
        """Four reads of another passenger's rows, four 403s and never a 404.

        PRD §2.1: "When `X-User-Role` is `Passenger`, reading a passenger requires that the
        addressed passenger id equal `X-User-ID`; reading bookings — the collection, a single
        booking, or any of its sub-resource collections for flight segments, checked bags, consumer
        complaints — requires that the booking's `passenger_id` equal `X-User-ID`; reading refund
        obligations, whether as a list or singly, and electing on one, require that the
        obligation's booking belong to that passenger; and filing a consumer complaint requires
        that the `booking_id` in the body resolve to a booking whose `passenger_id` equals
        `X-User-ID`."

        PRD §2.1: "A violation of any of these is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        PRD §2.1: "This ownership check runs **before** the existence checks of §2.5, so that a
        passenger cannot use 404-versus-403 responses to probe another passenger's resource ids."

        Design: Corner/rbac/passenger_cannot_read_another_passengers_resources
        """
        world = _owner_and_stranger(api)
        stranger = world.stranger_headers

        validate_error(
            api.get_booking(world.booking["id"], stranger), ERR_NOT_RESOURCE_OWNER, 403
        )
        validate_error(
            api.list_booking_complaints(world.booking["id"], stranger),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.get_refund_obligation(world.obligation["id"], stranger),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.get_passenger(world.passenger["id"], stranger), ERR_NOT_RESOURCE_OWNER, 403
        )

    def test_the_owner_and_the_regulator_read_the_same_rows_freely(self, api):
        """Ownership binds the passenger role alone; the auditor is outside it.

        PRD §2.1: "For `Passenger`, `X-User-ID` is the `id` of the acting passenger record, the
        value returned when that passenger was registered; ownership checks on any resource that
        references a passenger compare the resource's passenger reference to `X-User-ID`."

        PRD §2.1: "A `RegulatorAuditor` is strictly read-only across the entire surface,
        including filed reports and the complaint activity log, and holds no write capability of
        any kind."

        Design: Corner/rbac/passenger_cannot_read_another_passengers_resources
        """
        world = _owner_and_stranger(api)
        owner = world.passenger_headers

        validate_success(api.get_booking(world.booking["id"], owner))
        validate_paginated(api.list_booking_complaints(world.booking["id"], owner))
        validate_success(api.get_refund_obligation(world.obligation["id"], owner))
        validate_success(api.get_passenger(world.passenger["id"], owner))
        validate_success(
            api.get_refund_obligation(world.obligation["id"], AUDITOR_HEADERS)
        )


class TestPassengerElection:
    def test_the_passenger_elects_cash_and_is_recorded_as_the_chooser(self, api):
        """Their own request is the consent, and the instrument follows the card.

        PRD §3.7: "Whoever elects, `election_source` records who chose: `PASSENGER` when the
        caller acted under the `Passenger` role and `OFFICER_ON_BEHALF` when a compliance role
        acted for them."

        PRD §3.7: "Electing `CASH` sets `election_status` to `ELECTED_CASH`, leaves
        `credit_bonus_cents` at 0 and `payable_total_cents` equal to `amount_cents`, resolves the
        `settlement_method`, and advances the obligation's `version` by 1."

        PRD §3.7: "The instrument is a projection of how the ticket was paid for: a
        `CREDIT_CARD` booking resolves to `ORIGINAL_PAYMENT`, a `CASH_OR_CHECK` booking to
        `CASH_OR_CHECK`, a `MILES` booking to `MILES`, and a booking originally paid for in travel
        credit resolves back to `TRAVEL_CREDIT` even on a cash election — a passenger cannot
        launder credit into cash by electing cash."

        Design: Corner/rbac/passenger_elects_cash_on_their_own_obligation
        """
        world = _owner_and_stranger(api)

        elected = elect(api, world.obligation["id"], "CASH", world.passenger_headers)

        assert_obligation_axes(
            elected,
            election_status="ELECTED_CASH",
            election_source="PASSENGER",
            settlement_method="ORIGINAL_PAYMENT",
            settlement_status="UNSETTLED",
        )
        assert_obligation_amounts(
            elected, amount_cents=50000, credit_bonus_cents=0, payable_total_cents=50000
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=50000
        )

    def test_a_stranger_cannot_choose_the_instrument_on_someone_elses_refund(self, api):
        """The election axis is left exactly where the cascade put it.

        PRD §3.7: "A `Passenger` may elect only on an obligation whose booking is their own, per
        the ownership rules of §2.1."

        PRD §2.1: "A violation of any of these is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/passenger_elects_cash_on_their_own_obligation
        """
        world = _owner_and_stranger(api)

        refused = api.elect_refund_obligation(
            world.obligation["id"], f.elect_payload("CASH"), world.stranger_headers
        )

        validate_error(refused, ERR_NOT_RESOURCE_OWNER, 403)
        untouched = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(
            untouched, election_status="PENDING_ELECTION", election_source=None
        )


# ─── The two-person money chain ───────────────────────


def _officer_minted_claim_elected_cash(api):
    """A restored ledger, officer_1's own 90000-cent request-based claim, cash elected."""
    world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])
    cancel_segment(api, world.segments[0]["id"])
    void(api, sole_obligation(api, world.booking["id"])["id"], "CREATED_IN_ERROR")
    world.obligation = validate_success(
        api.create_refund_obligation(
            f.obligation_payload(
                world.booking["id"],
                booking_version(api, world.booking["id"]),
                issuance_mode="REQUEST_BASED",
                flight_segment_id=world.segments[1]["id"],
            ),
            OFFICER_HEADERS,
        ),
        201,
    )
    elect(api, world.obligation["id"], "CASH", world.passenger_headers)
    return world


class TestTheMinterCannotStartThePayment:
    def test_the_officer_who_booked_the_claim_may_not_move_the_money(self, api):
        """officer_1 is stopped by the persisted creator id, not by the source leg.

        PRD §2.10: "When a settlement is initiated, `X-User-ID` must differ from the
        obligation's `created_by_user_id` — the officer who minted a request-based obligation
        may not be the one who starts moving the money."

        PRD §2.10: "Either violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD §3.7: "For an obligation on a `FARE` basis, the leg that caused it must still be
        disrupted: its `status` must be `CANCELLED` or `DISRUPTED_UNUSED`, or it must be
        `DELAYED` with `is_significant_delay` true; a leg whose disruption was rescinded by a
        restore blocks settlement of the obligation it produced, with
        `ERR_SOURCE_DISRUPTION_RESCINDED`."

        PRD §3.6: "A newly minted obligation begins with `election_status` reading
        `PENDING_ELECTION`, `settlement_status` reading `UNSETTLED`, `settlement_attempt_count`
        at 0, `deadline_breached` false, and, for a direct create, `created_by_user_id` set from
        the caller's `X-User-ID`; obligations minted by a cascade leave `created_by_user_id`
        null."

        Design: Corner/rbac/creating_officer_cannot_initiate_the_settlement_they_booked
        """
        world = _officer_minted_claim_elected_cash(api)
        assert world.obligation["created_by_user_id"] == OFFICER_1

        refused = api.initiate_settlement(
            world.obligation["id"], f.initiate_payload("PROC-0001"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
        untouched = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(untouched, settlement_status="UNSETTLED")
        assert untouched["settlement_attempt_count"] == 0, "no attempt was recorded"
        assert_null(
            untouched["settlement_initiated_by_user_id"],
            "settlement_initiated_by_user_id",
        )
        assert_segment_state(
            read_segment(api, world.segments[1]["id"]), status="DISRUPTED_UNUSED"
        )

    def test_a_second_officer_of_the_same_role_starts_it_immediately(self, api):
        """The bar is the actor id, not the role: officer_2 clears the same gate.

        PRD §2.10: "Both comparisons are against persisted actor ids, so they hold across
        sessions rather than only within one."

        PRD §3.7: "On success the settlement axis moves `UNSETTLED → INITIATED` (or `FAILED →
        INITIATED` on a retry), `settlement_attempt_count` increases by 1,
        `settlement_initiated_at_utc` is stamped from the logical clock's current instant,
        `settlement_initiated_by_user_id` is written from `X-User-ID`, and the obligation's
        `version` advances by 1."

        PRD §3.6: "In request-based mode the variant is `REQUEST_BASED_UNUSED_PRORATION`, and it
        prorates evenly: when the booking's `segment_count` is 0 the gross entitlement is 0 and
        no division is attempted, and otherwise the per-leg share is the booking's
        `total_fare_cents` divided by its `segment_count` and rounded half up, and the gross
        entitlement is that share multiplied by the booking's `unused_segment_count`."

        Design: Corner/rbac/creating_officer_cannot_initiate_the_settlement_they_booked
        """
        world = _officer_minted_claim_elected_cash(api)
        assert_obligation_amounts(world.obligation, amount_cents=90000)

        started = initiate(api, world.obligation["id"], OFFICER_2_HEADERS)

        assert_obligation_axes(started, settlement_status="INITIATED")
        assert started["settlement_attempt_count"] == 1, "the first attempt is counted"
        assert started["settlement_initiated_by_user_id"] == OFFICER_2


# ─── The second leg of the chain ──────────────────────


def _payment_started_by_the_second_officer(api):
    """officer_1's claim, elected cash, with officer_2 holding the open attempt."""
    world = _officer_minted_claim_elected_cash(api)
    world.obligation = initiate(api, world.obligation["id"], OFFICER_2_HEADERS)
    return world


class TestTheInitiatorCannotConfirmThePayment:
    def test_the_officer_who_started_the_payment_may_not_report_its_outcome(self, api):
        """officer_2's own confirmation is refused and the attempt stays open.

        PRD §2.10: "When a settlement outcome is reported, `X-User-ID` must differ from the
        obligation's `settlement_initiated_by_user_id` — the officer who started the payment may
        not be the one who confirms it succeeded or failed."

        PRD §2.10: "Either violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD §3.7: "Reporting the processor's answer requires an `outcome` of either `SUCCEEDED`
        or `FAILED`, and may be done by a `ComplianceOfficer` or a `ComplianceAdmin` — but not by
        whoever initiated the attempt, whose `X-User-ID` matching
        `settlement_initiated_by_user_id` yields `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/initiating_officer_cannot_complete_the_settlement_they_started
        """
        world = _payment_started_by_the_second_officer(api)
        assert world.obligation["settlement_initiated_by_user_id"] == OFFICER_2

        refused = api.complete_settlement(
            world.obligation["id"], f.complete_payload("SUCCEEDED"), OFFICER_2_HEADERS
        )

        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
        untouched = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(untouched, settlement_status="INITIATED")
        assert untouched["settlement_attempt_count"] == 1, "no second attempt was opened"
        assert_null(untouched["settled_at_utc"], "settled_at_utc")

    def test_the_obligations_own_creator_may_confirm_what_the_other_officer_started(
        self, api
    ):
        """The second leg looks only at the initiator, so officer_1 closes the money out.

        PRD §3.7: "A `SUCCEEDED` outcome moves the axis `INITIATED → SETTLED`, stamps
        `settled_at_utc` from the logical clock, and advances the obligation's `version` by 1;
        when the `settlement_method` is `TRAVEL_CREDIT`, the passenger's
        `travel_credit_balance_cents` grows by the obligation's `payable_total_cents` — bonus
        included — and the passenger's `version` advances by 1."

        PRD §3.7: "The booking's `earliest_refund_deadline_utc` and `disruption_posture` are then
        recomputed, the posture reaching `CLOSED_OUT` once every obligation of the booking is
        settled or voided, and the booking's `version` advances by 1."

        PRD §2.11: "A passenger's `travel_credit_balance_cents` must always equal the sum of
        `payable_total_cents` over every obligation on that passenger's bookings whose settlement
        method is travel credit and whose settlement axis reads settled."

        Design: Corner/rbac/initiating_officer_cannot_complete_the_settlement_they_started
        """
        world = _payment_started_by_the_second_officer(api)

        settled = complete(api, world.obligation["id"], OFFICER_HEADERS, outcome="SUCCEEDED")

        assert_obligation_axes(
            settled, settlement_method="ORIGINAL_PAYMENT", settlement_status="SETTLED"
        )
        assert settled["settled_at_utc"] is not None, "the settled instant is stamped"
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=90000,
            disruption_posture="CLOSED_OUT",
        )
        passenger = read_passenger(api, world.passenger["id"])
        assert passenger["travel_credit_balance_cents"] == 0, (
            "a cash settlement issues no travel credit"
        )


# ─── The regulator's reading room ─────────────────────


def _regulator_reading_room(api):
    """A draft July filing, a leg-less booking, and a complaint worked once."""
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
    booking = create_booking(
        api, passenger["id"], profile["id"], "ABC123", 50000, "CREDIT_CARD"
    )
    report = open_report(api, profile["id"])
    complaint = file_complaint(
        api,
        booking["id"],
        category="REFUND",
        channel="EMAIL",
        received_at_utc="2026-08-05T09:00:00Z",
        summary="Refund never arrived.",
    )
    acknowledge(api, complaint["id"], "2026-08-06T10:00:00Z")
    return profile, booking, report, complaint


class TestRegulatorReadSurface:
    def test_the_auditor_reads_the_filings_and_the_whole_activity_trail(self, api):
        """Both regulator-facing reads answer 200 in their documented order.

        PRD §2.1: "A `RegulatorAuditor` is strictly read-only across the entire surface,
        including filed reports and the complaint activity log, and holds no write capability of
        any kind."

        PRD §3.9: "A new report opens in `DRAFT` with all seven metrics at 0,
        `policy_version_pinned` at 0 and `amendment_count` at 0; opening it also increases the
        profile's `report_count` and advances the profile's `version` by 1, which is why two
        reports cannot be opened back to back against one stale profile version."

        PRD §3.8: "Each of the four appends an activity row of the matching type:
        `ACKNOWLEDGED`, `INFO_REQUESTED`, `ANSWERED` and `REOPENED` respectively."

        PRD §3.8: "The trail is read in ascending `occurred_at_utc` order, tie-broken by
        ascending `created_at`, and is visible to compliance roles and the regulator auditor but
        not to the passenger."

        Design: Corner/rbac/regulator_auditor_reads_every_report_and_activity_but_writes_nothing
        """
        profile, _, report, complaint = _regulator_reading_room(api)

        filings, filings_meta = validate_paginated(
            api.list_policy_profile_reports(profile["id"], AUDITOR_HEADERS)
        )
        assert_list_meta(filings_meta, total_count=1, has_more=False)
        assert filings[0]["id"] == report["id"]
        assert filings[0]["status"] == "DRAFT"

        trail, trail_meta = validate_paginated(
            api.list_complaint_activities(complaint["id"], AUDITOR_HEADERS)
        )
        assert_list_meta(trail_meta, total_count=2, has_more=False)
        assert_activity_types(trail, ["RECEIVED", "ACKNOWLEDGED"])

    def test_the_auditor_reads_the_exposure_view_without_moving_a_thing(self, api):
        """Two variants on a leg-less booking: the whole fare against nothing at all.

        PRD §2.1: "A `RegulatorAuditor` is strictly read-only across the entire surface,
        including filed reports and the complaint activity log, and holds no write capability of
        any kind."

        PRD §3.6: "A read-only exposure view evaluates **both** fare variants against the
        booking's current state without persisting anything, and reports, for the addressed
        `booking_id`: `proactive_full_itinerary_cents`, the value the proactive rule would produce
        right now; `request_based_proration_cents`, the value the request-based rule would produce
        right now; `variant_delta_cents`, the proactive figure minus the request-based figure;
        `obligated_total_cents`, mirroring the booking's `total_refund_obligated_cents`;
        `remaining_headroom_cents`, computed exactly as step two above; `collected_total_cents`;
        `segment_count`; `unused_segment_count`; and `travel_commenced`."

        PRD §3.6: "In proactive mode the variant is `PROACTIVE_FULL_ITINERARY`: when the
        booking's `travel_commenced` is false, `gross_entitlement_cents` is the booking's whole
        `total_fare_cents`; when travel has commenced, it is the sum of `segment_fare_cents` over
        the booking's legs whose `status` is `SCHEDULED`, `DELAYED`, `CANCELLED` or
        `DISRUPTED_UNUSED`, added in ascending `sequence_index` order with no intermediate
        rounding since each per-leg fare is already whole cents."

        PRD §3.6: "In request-based mode the variant is `REQUEST_BASED_UNUSED_PRORATION`, and it
        prorates evenly: when the booking's `segment_count` is 0 the gross entitlement is 0 and
        no division is attempted, and otherwise the per-leg share is the booking's
        `total_fare_cents` divided by its `segment_count` and rounded half up, and the gross
        entitlement is that share multiplied by the booking's `unused_segment_count`."

        Design: Corner/rbac/regulator_auditor_reads_every_report_and_activity_but_writes_nothing
        """
        _, booking, _, _ = _regulator_reading_room(api)

        exposure = read_exposure(api, booking["id"], AUDITOR_HEADERS)

        assert_exposure(
            exposure,
            proactive_full_itinerary_cents=50000,
            request_based_proration_cents=0,
            variant_delta_cents=50000,
            obligated_total_cents=0,
            collected_total_cents=50000,
            segment_count=0,
            unused_segment_count=0,
            travel_commenced=False,
        )

    def test_the_sweep_that_only_recounts_is_still_a_write_the_auditor_cannot_make(
        self, api
    ):
        """Recounting violations is an admin act; the profile's counters do not stir.

        PRD §3.9: "A `ComplianceAdmin` runs the **compliance sweep** for one carrier by naming
        the `policy_profile_id`; the sweep considers every booking pinned to that profile and
        every obligation, complaint and tarmac event reachable from those bookings, over all
        history up to the logical clock's current instant."

        PRD §2.1: "A recognised role that is simply not authorised for the endpoint it called is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); §4 lists the authorised roles for each
        endpoint."

        PRD §2.9: "`report_count` increases by 1 each time a regulator report is opened against
        the profile, and `open_violation_count` is rewritten by the compliance sweep (§3.9). Both
        start at 0, and the profile's `version` starts at 1 and advances whenever either
        counter's value changes — which is precisely why report creation is guarded by a version
        check (§2.6)."

        Design: Corner/rbac/regulator_auditor_reads_every_report_and_activity_but_writes_nothing
        """
        profile, _, _, _ = _regulator_reading_room(api)

        refused = api.run_compliance_sweep(f.sweep_payload(profile["id"]), AUDITOR_HEADERS)

        validate_error(refused, ERR_FORBIDDEN_ROLE, 403)
        after = read_profile(api, profile["id"])
        assert after["open_violation_count"] == 0, "no sweep ever ran"
        assert after["report_count"] == 1, "only the July filing touched the profile"
        assert after["version"] == 2, "created at 1, bumped once by the report create"
