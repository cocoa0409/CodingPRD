"""Standby pool, replacement-case negotiation rounds, and deadline sweeps."""
from test_helpers import (
    ApiErrorId,
    assert_replacement_case,
    assert_standby_entry,
    create_actor,
    create_standby_entry,
    make_actor_headers,
    set_clock,
    setup_no_show_case,
    setup_published_call,
    validate_error,
    validate_success,
)


class TestStandbyWithdraw:
    def test_standby_withdraw_ownership(self, api, associate_headers):
        """PRD §3.5: "An entry leaves the pool in three ways: the owning actor or
        an associate may withdraw it — an actor caller must own the entry
        (`ERR_FORBIDDEN_OWNERSHIP`), and only an `ACTIVE` entry may be withdrawn,
        otherwise `ERR_STANDBY_NOT_ACTIVE` — moving it to `WITHDRAWN`"

        Design: Corner/rbac/standby_withdraw_ownership
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=0)
        actor_a = create_actor("SAG_AFTRA", legal_name="U SwA")
        actor_b = create_actor("SAG_AFTRA", legal_name="U SwB")
        entry = create_standby_entry(call["id"], actor_a["id"])
        assert entry["status"] == "ACTIVE"
        assert entry["slot_type"] == "UNION"

        res = api.withdraw_standby_entry(entry["id"], make_actor_headers(actor_b["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

        withdrawn = validate_success(
            api.withdraw_standby_entry(entry["id"], make_actor_headers(actor_a["id"])),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert_standby_entry(withdrawn)

    def test_standby_double_withdraw_rejected(self, api, associate_headers):
        """PRD §3.5: "only an `ACTIVE` entry may be withdrawn, otherwise
        `ERR_STANDBY_NOT_ACTIVE`"

        Design: Corner/errors/standby_double_withdraw_rejected
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=0)
        actor = create_actor("SAG_AFTRA")
        entry = create_standby_entry(call["id"], actor["id"])
        validate_success(
            api.withdraw_standby_entry(entry["id"], make_actor_headers(actor["id"])),
            200,
        )
        res = api.withdraw_standby_entry(entry["id"], associate_headers)
        validate_error(res, ApiErrorId.ERR_STANDBY_NOT_ACTIVE)


class TestOfferNextFallback:
    def test_empty_standby_pool_expires_case(self, api, associate_headers):
        """PRD §3.5: "If no candidate survives, the case slides `OPEN` →
        `EXPIRED`, the request still succeeds with HTTP 200, and no booking is
        created."
        PRD §3.5: "The case ... raises `attempts_count` by one" only when a
        candidate receives an offer.

        Design: Difficulty/boundary_precision_check/empty_standby_pool_expires_case
        """
        prod, call, actor0, booking, case, _actors, _entries = setup_no_show_case(
            standby_union_statuses=()
        )
        assert case["status"] == "OPEN"
        res = api.offer_next(case["id"], associate_headers)
        expired = validate_success(res, 200)
        assert expired["status"] == "EXPIRED"
        assert expired["offered_booking_id"] is None
        assert expired["attempts_count"] == 0

    def test_empty_standby_pool_creates_no_booking(self, api, associate_headers):
        """PRD §3.5: "If no candidate survives, the case slides `OPEN` →
        `EXPIRED`, the request still succeeds with HTTP 200, and no booking is
        created."

        Design: Difficulty/boundary_precision_check/empty_standby_pool_expires_case
        """
        prod, call, actor0, booking, case, _actors, _entries = setup_no_show_case(
            standby_union_statuses=()
        )
        res = api.offer_next(case["id"], associate_headers)
        validate_success(res, 200)
        bookings = validate_success(
            api.list_bookings(
                associate_headers, params={"replacement_case_id": case["id"]}
            ),
            200,
        )
        assert bookings == []
        case_after = validate_success(
            api.get_replacement_case(case["id"], associate_headers), 200
        )
        assert case_after["status"] == "EXPIRED"

    def test_selector_filters_slot_type(self, api, associate_headers):
        """PRD §3.5: "The selection filter is conjunctive — a candidate must
        satisfy all five conditions: an `ACTIVE` standby entry on this call;
        entry `slot_type` matching the case's `required_slot_type`; an actor
        currently `ELIGIBLE`; an actor not listed in the case's
        `excluded_actor_ids`; and an actor holding no booking in `OFFERED`,
        `CONFIRMED`, or `CHECKED_IN` on this call."

        Design: Corner/cross_cutting_complexity_layers/selector_filters_slot_type
        """
        prod, call, actor0, booking, case, standby_actors, entries = (
            setup_no_show_case(
                standby_union_statuses=["NONUNION"],
                union_slots=1,
                nonunion_slots=1,
            )
        )
        assert case["required_slot_type"] == "UNION"
        assert entries[0]["slot_type"] == "NONUNION"

        res = api.offer_next(case["id"], associate_headers)
        expired = validate_success(res, 200)
        assert expired["status"] == "EXPIRED"
        assert expired["attempts_count"] == 0

    def test_case_offer_after_expired_rejected(self, api, associate_headers):
        """PRD §3.5: "When an associate requests the next offer, the case must be
        `OPEN` (`ERR_CASE_INVALID_STATE` otherwise) and the call must be
        `SHOOTING` (`ERR_CALL_INVALID_STATE` otherwise)."

        Design: Corner/errors/case_offer_after_expired_rejected
        """
        prod, call, actor0, booking, case, _actors, _entries = setup_no_show_case(
            standby_union_statuses=()
        )
        validate_success(api.expire_case(case["id"], associate_headers), 200)
        res = api.offer_next(case["id"], associate_headers)
        validate_error(res, ApiErrorId.ERR_CASE_INVALID_STATE)


class TestNegotiationRounds:
    def _scenario(self, api):
        """u1/n0 call; original union booking no-showed; three union standbys
        registered in order (all reliability 100). Returns the tuple."""
        return setup_no_show_case(
            standby_union_statuses=["SAG_AFTRA", "SAG_AFTRA", "SAG_AFTRA"]
        )

    def test_replacement_negotiation_rounds_fill(self, api, associate_headers):
        """PRD §3.5: "Survivors rank by `reliability_score`, highest first, with
        ties broken by the standby entry's `created_at`, earliest first — never
        by identifier."
        PRD §3.5: "An acceptance fills it: the booking's `OFFERED` → `CONFIRMED`
        transition moves the case to `FILLED` and the promoted actor's standby
        entry to `PROMOTED`."

        Design: Difficulty/non_linear_state_machine/replacement_case_negotiation_rounds
        """
        prod, call, actor0, booking0, case, actors, entries = self._scenario(api)
        s1, s2, s3 = (a["id"] for a in actors)

        offer1 = validate_success(api.offer_next(case["id"], associate_headers), 200)
        assert offer1["status"] == "CANDIDATE_OFFERED"
        assert offer1["offered_actor_id"] == s1
        decline = api.decline_booking(
            offer1["offered_booking_id"], make_actor_headers(s1)
        )
        validate_success(decline, 200)

        offer2 = validate_success(api.offer_next(case["id"], associate_headers), 200)
        assert offer2["offered_actor_id"] == s2
        validate_success(
            api.decline_booking(offer2["offered_booking_id"], make_actor_headers(s2)),
            200,
        )

        offer3 = validate_success(api.offer_next(case["id"], associate_headers), 200)
        assert offer3["offered_actor_id"] == s3
        assert offer3["attempts_count"] == 3

        accepted = validate_success(
            api.accept_booking(offer3["offered_booking_id"], make_actor_headers(s3)),
            200,
        )
        assert accepted["status"] == "CONFIRMED"
        assert accepted["is_replacement"] is True
        assert accepted["replaces_booking_id"] == booking0["id"]
        assert accepted["replacement_case_id"] == case["id"]

        case_after = validate_success(
            api.get_replacement_case(case["id"], associate_headers), 200
        )
        assert case_after["status"] == "FILLED"
        assert case_after["attempts_count"] == 3
        assert_replacement_case(case_after)

        entry3 = validate_success(
            api.get_standby_entry(entries[2]["id"], associate_headers), 200
        )
        assert entry3["status"] == "PROMOTED"

        call_after = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_after["slots_available"] == 0

    def test_replacement_decline_reopens_case_with_exclusion(
        self, api, associate_headers
    ):
        """PRD §3.5: "A decline or an offer expiry returns the case to `OPEN`,
        appends that actor to `excluded_actor_ids` so they are never re-offered
        this case, and clears the offered fields — ready for another round, until
        the deadline runs out."

        Design: Difficulty/non_linear_state_machine/replacement_case_negotiation_rounds
        """
        prod, call, actor0, booking0, case, actors, entries = self._scenario(api)
        s1, s2, s3 = (a["id"] for a in actors)

        offer1 = validate_success(api.offer_next(case["id"], associate_headers), 200)
        assert offer1["offered_actor_id"] == s1
        validate_success(
            api.decline_booking(offer1["offered_booking_id"], make_actor_headers(s1)),
            200,
        )
        case_mid = validate_success(
            api.get_replacement_case(case["id"], associate_headers), 200
        )
        assert case_mid["status"] == "OPEN"
        assert case_mid["offered_booking_id"] is None
        assert case_mid["offered_actor_id"] is None
        assert s1 in case_mid["excluded_actor_ids"]

        # The declined candidate is never re-offered: round 2 goes to S2.
        offer2 = validate_success(api.offer_next(case["id"], associate_headers), 200)
        assert offer2["offered_actor_id"] == s2
        assert offer2["offered_actor_id"] != s1
        validate_success(
            api.decline_booking(offer2["offered_booking_id"], make_actor_headers(s2)),
            200,
        )
        case_mid2 = validate_success(
            api.get_replacement_case(case["id"], associate_headers), 200
        )
        assert case_mid2["status"] == "OPEN"
        assert s1 in case_mid2["excluded_actor_ids"]
        assert s2 in case_mid2["excluded_actor_ids"]


class TestDeadlineSweep:
    def test_clock_sweep_expires_case_and_offer(self, api, associate_headers):
        """PRD §3.5: "And the clock can end things two ways: sweeping past
        `deadline_at` while an offer stands outstanding expires both the offer
        booking (releasing its slot) and the case itself, while an associate may
        also expire an `OPEN` case manually — expiring from any other state fails
        with `ERR_CASE_INVALID_STATE`."

        Design: Corner/cross_cutting_complexity_layers/clock_sweep_expires_case_and_offer
        """
        prod, call, actor0, booking0, case, actors, entries = setup_no_show_case(
            standby_union_statuses=["SAG_AFTRA"]
        )
        offer = validate_success(api.offer_next(case["id"], associate_headers), 200)
        assert offer["status"] == "CANDIDATE_OFFERED"
        offer_booking_id = offer["offered_booking_id"]
        assert offer_booking_id is not None

        call_mid = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_mid["slots_available"] == 0  # offer consumed the released slot

        # Deadline is the original call_time + 120 minutes == 09:00.
        set_clock("2026-08-10T09:01:00Z")

        offer_booking = validate_success(
            api.get_booking(offer_booking_id, associate_headers), 200
        )
        assert offer_booking["status"] == "EXPIRED"
        case_after = validate_success(
            api.get_replacement_case(case["id"], associate_headers), 200
        )
        assert case_after["status"] == "EXPIRED"
        call_after = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_after["slots_available"] == 1
