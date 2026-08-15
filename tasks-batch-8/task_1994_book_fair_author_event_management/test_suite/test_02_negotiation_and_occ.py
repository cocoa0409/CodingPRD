"""Consignment and booking negotiation: cyclic counters, OCC, expiry, rounds cap."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_agreement_payload,
    create_booking_payload,
    make_school,
    make_publisher,
    make_author,
    make_fair,
    make_accepted_agreement,
    make_publisher_rep_headers,
    make_author_rep_headers,
    TEST_USERS,
)


class TestDuplicateAgreement:
    def test_duplicate_active_agreement_rejected(self, api):
        """PRD §3.2: "only one non-terminal agreement may exist per
        fair-and-publisher pair — a second live one is refused with
        `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

        Design: Corner/errors/duplicate_active_agreement_rejected
        """
        school = make_school()
        pub = make_publisher()
        fair = make_fair(school["id"])
        validate_success(api_client.create_agreement(
            create_agreement_payload(fair_id=fair["id"], publisher_party_id=pub["id"]),
            ORG,
        ), expected_status=201)
        resp = api_client.create_agreement(
            create_agreement_payload(
                fair_id=fair["id"], publisher_party_id=pub["id"],
                discount_pct=0.35, return_cap_pct=0.30, restocking_fee_pct=0.05,
                markdown_allowance_pct=0.10, freight_responsibility="PUBLISHER",
                offer_expiry_hours=48,
            ), ORG,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)

ORG = TEST_USERS["organizer_headers"]


class TestAgreementNegotiationCycle:
    def _build_agreement(self):
        school = make_school()
        pub = make_publisher()
        fair = make_fair(school["id"])
        agr = validate_success(api_client.create_agreement(
            create_agreement_payload(fair_id=fair["id"], publisher_party_id=pub["id"]),
            ORG,
        ), expected_status=201)
        return school, pub, fair, agr

    def test_agreement_counter_cycle_rounds_exhaustion(self, api):
        """PRD §3.2: "refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409)
        once the round counter would leave the six-round cap for agreements: a
        counter is only legal while `negotiation_round` is still below six."

        Design: Difficulty/non_linear_state_machine/agreement_counter_cycle_rounds_exhaustion
        """
        school, pub, fair, agr = self._build_agreement()
        pub_headers = make_publisher_rep_headers(pub["id"])

        counter_payload = {
            "discount_pct": 0.42,
            "return_cap_pct": 0.20,
            "restocking_fee_pct": 0.12,
            "markdown_allowance_pct": 0.20,
            "freight_responsibility": "PUBLISHER",
            "offer_expiry_hours": 72,
        }

        # Round 1 -> 2 (publisher counters)
        v = agr["version"]
        r = validate_success(api.counter_agreement(
            agr["id"], {**counter_payload, "expected_agreement_version": v}, pub_headers
        ))
        assert r["negotiation_round"] == 2
        assert r["status"] == "COUNTERED"
        assert r["offered_by"] == "PUBLISHER"

        # Round 2 -> 3 (organizer counters back)
        org_payload = {
            "discount_pct": 0.41, "return_cap_pct": 0.22, "restocking_fee_pct": 0.11,
            "markdown_allowance_pct": 0.20, "freight_responsibility": "ORGANIZER",
            "offer_expiry_hours": 72,
        }
        r = validate_success(api.counter_agreement(
            agr["id"], {**org_payload, "expected_agreement_version": r["version"]}, ORG
        ))
        assert r["negotiation_round"] == 3
        assert r["status"] == "PROPOSED"
        assert r["offered_by"] == "ORGANIZER"

        # 3 -> 4 publisher, 4 -> 5 organizer, 5 -> 6 publisher
        r = validate_success(api.counter_agreement(
            agr["id"], {**counter_payload, "expected_agreement_version": r["version"]}, pub_headers
        ))
        r = validate_success(api.counter_agreement(
            agr["id"], {**org_payload, "expected_agreement_version": r["version"]}, ORG
        ))
        r = validate_success(api.counter_agreement(
            agr["id"], {**counter_payload, "expected_agreement_version": r["version"]}, pub_headers
        ))
        assert r["negotiation_round"] == 6
        assert r["status"] == "COUNTERED"
        last_version = r["version"]

        # 6 -> 7 must be rejected
        resp = api.counter_agreement(
            agr["id"], {**org_payload, "expected_agreement_version": last_version}, ORG
        )
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED)

        # Version unchanged after the rejected counter
        after = validate_success(api.get_agreement(agr["id"], ORG))
        assert after["version"] == last_version
        assert after["negotiation_round"] == 6

    def test_agreement_counter_stale_version_rejected(self, api):
        """PRD §2.6: "Countering a consignment agreement requires
        `expected_agreement_version` carrying the client's last-observed
        `version` of the `ConsignmentAgreement`. If another writer has advanced
        the agreement's version since the client last read it ... the write is
        rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Difficulty/non_linear_state_machine/agreement_counter_cycle_rounds_exhaustion
        """
        school, pub, fair, agr = self._build_agreement()
        pub_headers = make_publisher_rep_headers(pub["id"])
        counter_payload = {
            "discount_pct": 0.42, "return_cap_pct": 0.20, "restocking_fee_pct": 0.12,
            "markdown_allowance_pct": 0.20, "freight_responsibility": "PUBLISHER",
            "offer_expiry_hours": 72,
        }
        # First counter succeeds
        r = validate_success(api.counter_agreement(
            agr["id"], {**counter_payload, "expected_agreement_version": agr["version"]},
            pub_headers,
        ))
        assert r["version"] == agr["version"] + 1
        # Second counter with the now-stale version is rejected 412
        resp = api.counter_agreement(
            agr["id"], {**counter_payload, "expected_agreement_version": agr["version"]},
            ORG,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestBookingOcc:
    def test_booking_counter_stale_version_rejected(self, api):
        """PRD §2.6: "Countering an author booking requires
        `expected_booking_version` against the `AuthorBooking`'s current
        `version`, under the same rule and the same `ERR_STALE_VERSION` (HTTP
        412) rejection."

        Design: Corner/validations/booking_counter_stale_version_rejected
        """
        school = make_school()
        author = make_author()
        fair = make_fair(school["id"])
        booking = validate_success(api_client.create_booking(
            create_booking_payload(fair_id=fair["id"], author_party_id=author["id"]),
            ORG,
        ), expected_status=201)
        author_headers = make_author_rep_headers(author["id"])

        counter_payload = {
            "base_honorarium_cents": 12000, "travel_cap_cents": 2500,
            "bonus_threshold_attendees": 3, "bonus_base_cents": 1000,
            "bonus_per_attendee_cents": 100, "offer_expiry_hours": 72,
        }
        r1 = validate_success(api.counter_booking(
            booking["id"],
            {**counter_payload, "expected_booking_version": booking["version"]},
            author_headers,
        ))
        assert r1["version"] == booking["version"] + 1
        assert r1["status"] == "NEGOTIATING"
        assert r1["offered_by"] == "AUTHOR"

        # Organizer counters back
        org_payload = {
            "base_honorarium_cents": 11000, "travel_cap_cents": 2200,
            "bonus_threshold_attendees": 3, "bonus_base_cents": 1000,
            "bonus_per_attendee_cents": 100, "offer_expiry_hours": 72,
        }
        r2 = validate_success(api.counter_booking(
            booking["id"], {**org_payload, "expected_booking_version": r1["version"]}, ORG
        ))
        assert r2["version"] == booking["version"] + 2

        # Stale version (r2.version - 1) is rejected
        resp = api.counter_booking(
            booking["id"],
            {**counter_payload, "expected_booking_version": r2["version"] - 1},
            author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_booking(booking["id"], ORG))
        assert after["base_honorarium_cents"] == 11000

    def test_booking_decline_locks_negotiation(self, api):
        """PRD §3.4: "Either side may decline from `INVITED` or `NEGOTIATING`,
        ending at `DECLINED`."
        PRD §3.1: "Attempting any lifecycle action from a state that does not
        offer it is rejected with `ERR_INVALID_STATE` (HTTP 409) — the same
        response an actor gets when poking at an entity in a terminal state."

        Design: Corner/state_machines/booking_decline_locks_negotiation
        """
        school = make_school()
        author = make_author()
        fair = make_fair(school["id"])
        booking = validate_success(api_client.create_booking(
            create_booking_payload(fair_id=fair["id"], author_party_id=author["id"]),
            ORG,
        ), expected_status=201)
        author_headers = make_author_rep_headers(author["id"])
        validate_success(api.decline_booking(booking["id"], author_headers))
        resp = api.counter_booking(
            booking["id"],
            {
                "base_honorarium_cents": 12000, "travel_cap_cents": 2000,
                "bonus_threshold_attendees": 3, "bonus_base_cents": 1000,
                "bonus_per_attendee_cents": 100, "offer_expiry_hours": 72,
                "expected_booking_version": booking["version"],
            },
            author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOfferExpiry:
    def test_agreement_offer_expiry_via_clock_sweep(self, api):
        """PRD §2.5: "Advancing the clock runs an **offer-expiry sweep**: every
        `ConsignmentAgreement` still in `PROPOSED` or `COUNTERED` whose
        `offer_expires_at` is at or before the new clock instant transitions to
        `EXPIRED`."
        PRD §3.1: "Attempting any lifecycle action from a state that does not
        offer it is rejected with `ERR_INVALID_STATE` (HTTP 409) — the same
        response an actor gets when poking at an entity in a terminal state."

        Design: Corner/state_machines/agreement_offer_expiry_via_clock_sweep
        """
        school = make_school()
        pub = make_publisher()
        fair = make_fair(school["id"])
        agr = validate_success(api_client.create_agreement(
            create_agreement_payload(
                fair_id=fair["id"], publisher_party_id=pub["id"], offer_expiry_hours=1
            ), ORG,
        ), expected_status=201)

        # Default clock is 2026-08-01T00:00:00Z; expiry is at 01:00. Push clock past it.
        resp = api.set_clock({"to_iso8601": "2026-08-01T02:00:00Z"}, ORG)
        data = validate_success(resp)
        assert agr["id"] in data["expired_agreement_ids"]

        after = validate_success(api.get_agreement(agr["id"], ORG))
        assert after["status"] == "EXPIRED"

        # Counter after expiry is terminal-state rejection
        resp2 = api.counter_agreement(
            agr["id"],
            {
                "discount_pct": 0.42, "return_cap_pct": 0.20, "restocking_fee_pct": 0.12,
                "markdown_allowance_pct": 0.20, "freight_responsibility": "PUBLISHER",
                "offer_expiry_hours": 1, "expected_agreement_version": agr["version"],
            },
            make_publisher_rep_headers(pub["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

    def test_default_clock_pins_offer_expiry(self, api):
        """PRD §2.5: "At server startup the logical clock is exactly
        `2026-08-01T00:00:00Z`."
        PRD §3.2: "A new agreement is `PROPOSED` with `negotiation_round` 1,
        `offered_by` `ORGANIZER`, and `offer_expires_at` set to the current
        logical clock plus `offer_expiry_hours`."

        Design: Corner/cross_cutting_complexity_layers/default_clock_pins_offer_expiry
        """
        school = make_school()
        pub = make_publisher()
        fair = make_fair(school["id"])
        agr = validate_success(api_client.create_agreement(
            create_agreement_payload(
                fair_id=fair["id"], publisher_party_id=pub["id"], offer_expiry_hours=72
            ), ORG,
        ), expected_status=201)
        # PRD section 2.4 pins timestamps to three fractional digits, so the
        # clock-plus-72h instant serializes with the .000Z suffix.
        assert agr["offer_expires_at"] == "2026-08-04T00:00:00.000Z"

    def test_booking_offer_lazy_expiry(self, api):
        """PRD §2.5: "Author bookings are deliberately not swept — no booking is
        auto-expired or auto-declined by the clock; a booking whose offer has
        lapsed simply surfaces `ERR_OFFER_EXPIRED` (HTTP 409) on the next
        counter or accept attempt."

        Design: Corner/cross_cutting_complexity_layers/booking_offer_lazy_expiry
        """
        school = make_school()
        author = make_author()
        fair = make_fair(school["id"])
        booking = validate_success(api_client.create_booking(
            create_booking_payload(
                fair_id=fair["id"], author_party_id=author["id"], offer_expiry_hours=1
            ), ORG,
        ), expected_status=201)
        validate_success(api.set_clock({"to_iso8601": "2026-08-01T02:00:00Z"}, ORG))
        resp = api.counter_booking(
            booking["id"],
            {
                "base_honorarium_cents": 12000, "travel_cap_cents": 2500,
                "bonus_threshold_attendees": 3, "bonus_base_cents": 1000,
                "bonus_per_attendee_cents": 100, "offer_expiry_hours": 1,
                "expected_booking_version": booking["version"],
            },
            make_author_rep_headers(author["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
        after = validate_success(api.get_booking(booking["id"], ORG))
        assert after["status"] == "INVITED"
