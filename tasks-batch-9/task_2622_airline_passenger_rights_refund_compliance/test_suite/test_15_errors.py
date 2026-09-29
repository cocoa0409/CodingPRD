"""Identity, existence and state refusals, each answered with its own code."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ADMIN_HEADERS,
    ERR_ANCILLARY_PURCHASE_NOT_FOUND,
    ERR_CHECKED_BAG_NOT_FOUND,
    ERR_CONSUMER_COMPLAINT_NOT_FOUND,
    ERR_DENIED_BOARDING_RECORD_NOT_FOUND,
    ERR_DENIED_BOARDING_STATE_INVALID,
    ERR_FORBIDDEN_ROLE,
    ERR_POLICY_PROFILE_NOT_FOUND,
    ERR_REFUND_OBLIGATION_NOT_FOUND,
    ERR_REGULATOR_REPORT_NOT_FOUND,
    ERR_TARMAC_DELAY_EVENT_NOT_FOUND,
    ERR_TARMAC_EVENT_STATE_INVALID,
    ERR_UNAUTHENTICATED,
    OFFICER_HEADERS,
    OPS_HEADERS,
    assert_booking_ledger,
    assert_instant,
    assert_list_meta,
    assert_null,
    assert_obligation_amounts,
    assert_segment_state,
    build_world,
    create_policy_profile,
    factories as f,
    headers_with_empty_identity,
    headers_without_identity,
    make_headers,
    obligations_with_meta,
    read_booking,
    read_denied_boarding,
    read_profile,
    read_segment,
    read_tarmac_event,
    record_operation,
)

SENTINEL_ID = "00000000-0000-0000-0000-0000000000ff"

# ─── Identity before anything else ────────────────────


class TestIdentityHeaders:
    def test_an_unidentified_caller_is_refused_before_the_body_is_judged(self, api):
        """An empty carrier_code never gets a shape verdict: authentication runs first.

        PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the caller,
        and `X-User-Role`, naming the capability set the caller is acting under. If either
        header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        PRD §2.5: "Because many requests can fail for several reasons at once, the order in
        which checks run is part of the contract."

        PRD §2.5: "Any breach is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/missing_identity_headers_rejected_before_any_body_parsing
        """
        empty_identity = api.create_policy_profile(
            f.policy_profile_payload(""), headers_with_empty_identity()
        )
        no_identity = api.list_bookings(headers_without_identity())

        validate_error(empty_identity, ERR_UNAUTHENTICATED, 401)
        validate_error(no_identity, ERR_UNAUTHENTICATED, 401)
        _, meta = validate_paginated(api.list_bookings(ADMIN_HEADERS))
        assert_list_meta(meta, total_count=0, has_more=False)

    def test_an_unrecognised_role_is_unauthenticated_while_a_real_one_is_forbidden(
        self, api
    ):
        """SuperUser is nobody; an OpsController is somebody without this power.

        PRD §2.1: "The same code and status are returned when `X-User-Role` carries a value
        that is not one of the five recognised roles, which are spelled exactly:
        `ComplianceAdmin`, `ComplianceOfficer`, `OpsController`, `RegulatorAuditor`, and
        `Passenger`."

        PRD §2.1: "A recognised role that is simply not authorised for the endpoint it called
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); §4 lists the authorised roles for each
        endpoint."

        PRD §2.9: "`report_count` increases by 1 each time a regulator report is opened against
        the profile, and `open_violation_count` is rewritten by the compliance sweep (§3.9).
        Both start at 0, and the profile's `version` starts at 1 and advances whenever either
        counter's value changes — which is precisely why report creation is guarded by a version
        check (§2.6)."

        Design: Corner/errors/unknown_role_value_rejected_as_unauthenticated_not_forbidden
        """
        profile = create_policy_profile(api, "ZQ")

        invented_role = api.run_compliance_sweep(
            f.sweep_payload(profile["id"]), make_headers("hacker_1", "SuperUser")
        )
        real_but_unlisted_role = api.run_compliance_sweep(
            f.sweep_payload(profile["id"]), OPS_HEADERS
        )

        validate_error(invented_role, ERR_UNAUTHENTICATED, 401)
        validate_error(real_but_unlisted_role, ERR_FORBIDDEN_ROLE, 403)
        untouched = read_profile(api, profile["id"])
        assert untouched["version"] == 1, "neither refused sweep ran a phase"
        assert untouched["open_violation_count"] == 0


# ─── One not-found code per entity ────────────────────


class TestPerEntityNotFoundCodes:
    def test_one_sentinel_id_yields_eight_different_not_found_codes(self, api):
        """The path position alone decides which entity the 404 names.

        PRD §2.5: "**Path existence** — every id embedded in the request path must resolve to a
        stored row, and path ids are resolved strictly left to right, so the outer segment's 404
        wins over the inner one's."

        PRD §2.5: "Each entity has its own code: a policy profile yields
        `ERR_POLICY_PROFILE_NOT_FOUND`, a passenger `ERR_PASSENGER_NOT_FOUND`, a booking
        `ERR_BOOKING_NOT_FOUND`, a flight segment `ERR_FLIGHT_SEGMENT_NOT_FOUND`, an ancillary
        purchase `ERR_ANCILLARY_PURCHASE_NOT_FOUND`, a checked bag `ERR_CHECKED_BAG_NOT_FOUND`,
        a denied boarding record `ERR_DENIED_BOARDING_RECORD_NOT_FOUND`, a tarmac delay event
        `ERR_TARMAC_DELAY_EVENT_NOT_FOUND`, a refund obligation
        `ERR_REFUND_OBLIGATION_NOT_FOUND`, a consumer complaint
        `ERR_CONSUMER_COMPLAINT_NOT_FOUND`, and a regulator report
        `ERR_REGULATOR_REPORT_NOT_FOUND`."

        Design: Corner/errors/every_remaining_entity_resolves_its_own_not_found_code
        """
        validate_error(
            api.get_policy_profile(SENTINEL_ID, ADMIN_HEADERS),
            ERR_POLICY_PROFILE_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_ancillary_purchase(SENTINEL_ID, OFFICER_HEADERS),
            ERR_ANCILLARY_PURCHASE_NOT_FOUND,
            404,
        )
        validate_error(
            api.resolve_checked_bag(
                SENTINEL_ID, f.bag_delivered_payload("2026-08-10T21:00:00Z"), OFFICER_HEADERS
            ),
            ERR_CHECKED_BAG_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_denied_boarding_record(SENTINEL_ID, OFFICER_HEADERS),
            ERR_DENIED_BOARDING_RECORD_NOT_FOUND,
            404,
        )
        validate_error(
            api.deplane_tarmac_event(
                SENTINEL_ID, f.deplane_payload("2026-08-10T13:00:00Z"), OPS_HEADERS
            ),
            ERR_TARMAC_DELAY_EVENT_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_refund_obligation(SENTINEL_ID, OFFICER_HEADERS),
            ERR_REFUND_OBLIGATION_NOT_FOUND,
            404,
        )
        validate_error(
            api.submit_regulator_report(
                SENTINEL_ID, f.submit_report_payload("2026-09-01T09:00:00Z"), ADMIN_HEADERS
            ),
            ERR_REGULATOR_REPORT_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_consumer_complaint(SENTINEL_ID, OFFICER_HEADERS),
            ERR_CONSUMER_COMPLAINT_NOT_FOUND,
            404,
        )


# ─── Finalizing a denied-boarding record twice ────────


def _finalized_involuntary_record(api):
    """A 90-minute substitute delay finalized once on the second statutory rung."""
    world = build_world(api, segment_fares=[50000])
    world.record = validate_success(
        api.create_denied_boarding_record(
            f.denied_boarding_payload(
                world.booking["id"],
                world.segments[0]["id"],
                oversale_confirmed=True,
                written_disclosure_provided=True,
            ),
            OFFICER_HEADERS,
        ),
        201,
    )
    world.finalized = validate_success(
        api.finalize_denied_boarding_record(
            world.record["id"], f.finalize_payload(), OFFICER_HEADERS
        )
    )
    return world


class TestDeniedBoardingFinalizeIsNotReRunnable:
    def test_the_first_finalize_walks_the_ladder_to_the_capped_second_rung(self, api):
        """Twice a 45000-cent fare is 90000, which the 77500 ceiling cuts down.

        PRD §3.4: "A newly recorded incident sits in `RECORDED` with
        `statutory_compensation_cents` at 0, `compensation_cents` at 0 and `effective_category`
        unset, and with `substitute_delay_minutes` computed immediately as the difference between
        the `substitute_arrival_utc` and the leg's `scheduled_arrival_utc` in whole minutes with
        the remainder dropped, never below 0."

        PRD §3.4: "The second rung runs from 61 minutes up to and including a scope-dependent
        ceiling of 120 minutes (two hours) on a domestic leg or 240 minutes (four hours) on a leg
        flagged international; here the statutory figure is twice the `one_way_fare_cents`,
        rounded half up, but never more than 77,500 cents (775 dollars)."

        PRD §3.4: "It stays `VOLUNTARY` only when the declared `category` is `VOLUNTARY` **and**
        `oversale_confirmed` is true **and** `written_disclosure_provided` is true; in every other
        combination it resolves to `INVOLUNTARY`."

        PRD §3.4: "On an involuntary record `compensation_cents` is set to
        `statutory_compensation_cents`."

        Design: Corner/errors/finalize_on_already_finalized_denied_boarding_record_rejected
        """
        world = _finalized_involuntary_record(api)

        assert world.record["status"] == "RECORDED"
        assert world.record["compensation_cents"] == 0
        assert world.record["substitute_delay_minutes"] == 90
        assert world.finalized["status"] == "FINALIZED"
        assert world.finalized["statutory_compensation_cents"] == 77500
        assert world.finalized["compensation_cents"] == 77500
        assert world.finalized["effective_category"] == "INVOLUNTARY"
        assert_instant(world.finalized["finalized_at_utc"], "2026-08-10T16:00:00Z")

    def test_a_second_finalize_neither_reruns_the_ladder_nor_mints_a_twin(self, api):
        """The 17:00 instant is never written and the ledger stays at one compensation.

        PRD §3.4: "A `ComplianceOfficer` (or `ComplianceAdmin`) supplies the `finalized_at_utc`
        instant; a record not in `RECORDED` is refused with
        `ERR_DENIED_BOARDING_STATE_INVALID`."

        PRD §3.4: "Either branch then mints one refund obligation on a `DENIED_BOARDING` basis
        in proactive issuance mode, whose gross entitlement is the resolved `compensation_cents`,
        with its clock start taken from `finalized_at_utc`."

        PRD §3.4: "Statutory denied-boarding compensation is **exempt from the booking's refund
        headroom entirely** — it is compensation for a service failure rather than a refund of
        money collected, so it is neither clamped by the headroom nor counted against it when later
        obligations compute theirs."

        PRD §2.4: "All entities except the complaint activity trail additionally carry
        `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and `version`,
        an integer that begins at 1 when the row is created and increases by exactly 1 on each
        request that changes the row's persisted field values."

        Design: Corner/errors/finalize_on_already_finalized_denied_boarding_record_rejected
        """
        world = _finalized_involuntary_record(api)
        booking_before = read_booking(api, world.booking["id"])

        refused = api.finalize_denied_boarding_record(
            world.record["id"],
            f.finalize_payload("2026-08-10T17:00:00Z"),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_DENIED_BOARDING_STATE_INVALID, 409)
        unchanged = read_denied_boarding(api, world.record["id"])
        assert unchanged["status"] == "FINALIZED"
        assert unchanged["compensation_cents"] == 77500
        assert_instant(unchanged["finalized_at_utc"], "2026-08-10T16:00:00Z")
        assert unchanged["version"] == world.finalized["version"]
        rows, meta = obligations_with_meta(
            api, world.booking["id"], basis="DENIED_BOARDING"
        )
        assert_list_meta(meta, total_count=1, has_more=False)
        assert_obligation_amounts(rows[0], gross_entitlement_cents=77500, amount_cents=77500)
        after = read_booking(api, world.booking["id"])
        assert_booking_ledger(after, total_refund_obligated_cents=77500)
        assert after["version"] == booking_before["version"], (
            "the refused call incremented nothing"
        )


# ─── The tarmac fork-join guarded from both ends ──────


def _open_event_on_a_departed_leg(api):
    """A DELAY_ACTIVE occupation whose leg is already operationally closed out."""
    world = build_world(api, segment_fares=[50000])
    segment = world.segments[0]
    world.event = validate_success(
        api.create_tarmac_delay_event(f.tarmac_event_payload(segment["id"]), OPS_HEADERS),
        201,
    )
    record_operation(api, segment["id"], "DEPARTED", "2026-08-10T13:30:00Z")
    world.segment = segment
    return world


class TestTarmacEventStateGuardsBothEnds:
    def test_an_open_occupation_cannot_be_reported_even_on_a_departed_leg(self, api):
        """The refusal names the event's state, not the leg's and not a missing narrative.

        PRD §3.5: "The event must be either `DEPLANED` or `EXEMPTION_INVOKED`, and filing
        against an event that is still open or already filed is
        `ERR_TARMAC_EVENT_STATE_INVALID`."

        PRD §3.5: "The parent leg must additionally be operationally closed out — its `status`
        must be `DEPARTED`, `ARRIVED` or `CANCELLED` — since a contingency-plan report on a
        flight still shown as scheduled or merely delayed would be premature; filing while the leg
        is `SCHEDULED` or `DELAYED` is refused with `ERR_SEGMENT_STATE_INVALID`."

        Design: Corner/errors/file_report_on_still_active_tarmac_event_then_on_terminal_event_rejected
        """
        world = _open_event_on_a_departed_leg(api)
        assert world.event["status"] == "DELAY_ACTIVE"
        assert world.event["deadline_minutes"] == 180
        assert_segment_state(read_segment(api, world.segment["id"]), status="DEPARTED")

        refused = api.file_tarmac_report(
            world.event["id"],
            f.file_report_payload("TR-0001", "2026-08-10T18:00:00Z"),
            ADMIN_HEADERS,
        )

        validate_error(refused, ERR_TARMAC_EVENT_STATE_INVALID, 409)
        still_open = read_tarmac_event(api, world.event["id"], world.segment["id"])
        assert still_open["status"] == "DELAY_ACTIVE"
        assert_null(still_open["interval_end_utc"], "interval_end_utc")

    def test_the_terminal_reported_state_accepts_no_further_transition(self, api):
        """The body refused a moment earlier now files, and the closed event refuses exemption.

        PRD §3.5: "Filing moves the event to `REPORT_FILED` — its terminal state, reached from
        either fork — storing `report_reference`, the `corrective_action_summary` when one was
        supplied, and `report_filed_at_utc` from the supplied `filed_at_utc`, and advancing the
        event's `version` by 1."

        PRD §3.5: "Either way, an event that is not `DELAY_ACTIVE` cannot be closed again: a
        second deplaning or exemption attempt is `ERR_TARMAC_EVENT_STATE_INVALID`."

        PRD §3.5: "The leg-level accounting differs from the deplaning branch in a way worth
        stating twice: the leg's `exempted_tarmac_event_count` grows by 1 — it counts every event
        on the leg carrying a non-null `exemption_reason` — while the leg's
        `cumulative_tarmac_minutes` is **not** increased, because exemption-closed minutes are
        excluded from the leg's accumulated tarmac time even after the event is later reported."

        Design: Corner/errors/file_report_on_still_active_tarmac_event_then_on_terminal_event_rejected
        """
        world = _open_event_on_a_departed_leg(api)
        deplaned = validate_success(
            api.deplane_tarmac_event(
                world.event["id"], f.deplane_payload("2026-08-10T13:00:00Z"), OPS_HEADERS
            )
        )
        assert deplaned["status"] == "DEPLANED"
        assert deplaned["tarmac_minutes"] == 60
        assert deplaned["is_violation"] is False

        filed = validate_success(
            api.file_tarmac_report(
                world.event["id"],
                f.file_report_payload("TR-0001", "2026-08-10T18:00:00Z"),
                ADMIN_HEADERS,
            )
        )
        refused = api.claim_tarmac_exemption(
            world.event["id"],
            f.exemption_payload("2026-08-10T13:00:00Z", "ATC_DIRECTIVE"),
            OPS_HEADERS,
        )

        assert filed["status"] == "REPORT_FILED"
        assert filed["report_reference"] == "TR-0001"
        validate_error(refused, ERR_TARMAC_EVENT_STATE_INVALID, 409)
        rows, meta = validate_paginated(
            api.list_segment_tarmac_events(world.segment["id"], ADMIN_HEADERS)
        )
        assert_list_meta(meta, total_count=1, has_more=False)
        assert rows[0]["status"] == "REPORT_FILED"
        assert_null(rows[0]["exemption_reason"], "exemption_reason")
        assert_segment_state(
            read_segment(api, world.segment["id"]),
            cumulative_tarmac_minutes=60,
            exempted_tarmac_event_count=0,
        )
