"""Event creation defaults, shape validation, and entry-fee pricing variants."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, MISSING_UUID,
    create_event_payload, create_class_payload, create_zone_payload,
    create_registrant_payload, create_vehicle_payload, create_registration_payload,
    create_event, create_open_event, create_registrant_with_vehicle,
    create_registration, assert_event, assert_registration,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


class TestEventCreationShape:
    def test_event_creation_missing_required_returns_400(self, api):
        """PRD §2.9: "required fields present, enum values in range, numbers in
        range, a score sheet's `criteria_scores` holding exactly the five known
        criteria with integer points from 0 to 10, and class codes unique within
        the event: violations carry `ERR_VALIDATION`".

        Design: Corner/entities/event_creation_missing_required_returns_400
        """
        payload = create_event_payload()
        del payload["name"]
        resp = api.create_event(payload, ORG)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        # No Event row was created: the events list stays empty.
        listed = validate_success(api.list_events(ORG))
        assert listed == []

    def test_event_defaults_applied_on_create(self, api):
        """PRD §3.1: "The organizer may also record the club's
        `liability_policy_number`, which defaults to an empty string, and choose
        a `tabulation_method` of `STRAIGHT_AVERAGE` or `DROP_EXTREMES`, defaulting
        to `STRAIGHT_AVERAGE` when omitted. A new event begins in `DRAFT` with
        `weather_posture` at `NORMAL`, `sound_permit_status` at `ACTIVE`,
        `treasury_cents` at zero, and `noise_exceedance_count` at zero."

        Design: Corner/entities/event_defaults_applied_on_create
        """
        payload = create_event_payload()
        del payload["liability_policy_number"]
        ev = validate_success(api.create_event(payload, ORG), expected_status=201)
        assert_event(ev)
        assert ev["tabulation_method"] == "STRAIGHT_AVERAGE"
        assert ev["liability_policy_number"] == ""
        assert ev["lifecycle_status"] == "DRAFT"
        assert ev["weather_posture"] == "NORMAL"
        assert ev["sound_permit_status"] == "ACTIVE"
        assert ev["treasury_cents"] == 0
        assert ev["noise_exceedance_count"] == 0
        assert ev["version"] == 1

    def test_event_computed_fields_input_ignored(self, api):
        """PRD §3.1: "A new event begins in `DRAFT` with `weather_posture` at
        `NORMAL`, `sound_permit_status` at `ACTIVE`, `treasury_cents` at zero,
        and `noise_exceedance_count` at zero."

        Design: Corner/entities/event_computed_fields_input_ignored
        """
        payload = create_event_payload(treasury_cents=9999, lifecycle_status="FINALIZED")
        ev = validate_success(api.create_event(payload, ORG), expected_status=201)
        assert ev["treasury_cents"] == 0, "client-supplied treasury_cents must be ignored"
        assert ev["lifecycle_status"] == "DRAFT", "client-supplied lifecycle_status must be ignored"
        assert ev["noise_exceedance_count"] == 0


class TestEntryFeePreregVsDayOf:
    def _setup_alice(self, api):
        """Open event, member registrant Alice with three eligible vehicles."""
        ev, cls, zone = create_open_event(
            class_overrides={
                "code": "MUSCLE", "min_year": 1950, "max_year": 1975,
                "judging_mode": "JUDGED", "award_depth": 2,
            },
            zone_overrides={
                "arrival_window_start": "2026-08-15T08:00:00Z",
                "arrival_window_end": "2026-08-15T10:00:00Z",
            },
        )
        alice = get_success_data(api.create_registrant(
            create_registrant_payload(full_name="Alice Member", email="alice@example.com",
                                      club_member=True), ORG))
        v1 = get_success_data(api.create_vehicle(
            alice["id"], create_vehicle_payload(year=1970), ORG))
        v2 = get_success_data(api.create_vehicle(
            alice["id"], create_vehicle_payload(year=1971, make="Chevrolet", model="Chevelle"), ORG))
        v3 = get_success_data(api.create_vehicle(
            alice["id"], create_vehicle_payload(year=1974, make="Datsun", model="260Z"), ORG))
        return ev, cls, alice, v1, v2, v3

    def test_prereg_member_first_and_second_vehicle_fees(self, api):
        """PRD §3.2: "The `PREREG` tier starts from the class's `prereg_fee_cents`
        and applies up to two discounts: a club member pays ten percent less, and
        the fee drops a further twenty-five percent when this is the registrant's
        second or later vehicle for the same event".

        Design: Difficulty/dual_variant_calc/entry_fee_prereg_vs_day_of_divergence
        """
        ev, cls, alice, v1, v2, v3 = self._setup_alice(api)
        # Clock is still at its startup default, before the prereg deadline.
        r1 = validate_success(api.create_registration(
            create_registration_payload(ev["id"], alice["id"], v1["id"], cls["id"]),
            DESK), expected_status=201)
        r2 = validate_success(api.create_registration(
            create_registration_payload(ev["id"], alice["id"], v2["id"], cls["id"]),
            DESK), expected_status=201)
        assert r1["pricing_tier"] == "PREREG"
        assert r1["fee_cents"] == 2700, f"3000 * 0.9 member == 2700, got {r1['fee_cents']}"
        assert r2["pricing_tier"] == "PREREG"
        assert r2["fee_cents"] == 2025, f"3000 * 0.9 * 0.75 == 2025, got {r2['fee_cents']}"

    def test_day_of_flat_fee_beats_identical_prereg_inputs(self, api):
        """PRD §3.2: "The `DAY_OF` tier is flat: `fee_cents` is simply the class's
        `day_of_fee_cents`, with no member or multi-vehicle discount, so identical
        inputs price higher at the gate than they would have in advance."

        Design: Difficulty/dual_variant_calc/entry_fee_prereg_vs_day_of_divergence
        """
        ev, cls, alice, v1, v2, v3 = self._setup_alice(api)
        r2 = validate_success(api.create_registration(
            create_registration_payload(ev["id"], alice["id"], v1["id"], cls["id"]),
            DESK), expected_status=201)
        # Advance the clock past the prereg deadline (day-of show morning).
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T09:30:00Z"}, ORG))
        r3 = validate_success(api.create_registration(
            create_registration_payload(ev["id"], alice["id"], v3["id"], cls["id"]),
            DESK), expected_status=201)
        r3_read = validate_success(api.get_registration(r3["id"], DESK))
        assert r3_read["pricing_tier"] == "DAY_OF"
        assert r3_read["fee_cents"] == 4500
        assert r2["fee_cents"] == 2700 != r3_read["fee_cents"], (
            "identical member/class inputs must diverge across the two pricing variants")


class TestEntryFeeMemberMultiInteraction:
    def _setup_event(self, api):
        ev, cls, zone = create_open_event(
            class_overrides={"code": "MUSCLE", "min_year": 1950, "max_year": 1975,
                             "judging_mode": "JUDGED", "award_depth": 2})
        alice = get_success_data(api.create_registrant(
            create_registrant_payload(full_name="Alice", email="a@example.com",
                                      club_member=True), ORG))
        bob = get_success_data(api.create_registrant(
            create_registrant_payload(full_name="Bob", email="b@example.com",
                                      club_member=False), ORG))
        vehicles = {}
        for key, owner, year, make, model in [
            ("v1", alice, 1970, "Ford", "Mustang"),
            ("v2", alice, 1971, "Chevrolet", "Chevelle"),
            ("v3", bob, 1969, "Chevrolet", "Camaro"),
            ("v4", bob, 1972, "Pontiac", "GTO"),
        ]:
            vehicles[key] = get_success_data(api.create_vehicle(
                owner["id"], create_vehicle_payload(year=year, make=make, model=model), ORG))
        return ev, cls, alice, bob, vehicles

    def test_member_discounts_stack_multiplicatively(self, api):
        """PRD §3.2: "The `PREREG` tier starts from the class's `prereg_fee_cents`
        and applies up to two discounts: a club member pays ten percent less, and
        the fee drops a further twenty-five percent when this is the registrant's
        second or later vehicle for the same event".

        Design: Difficulty/combinatorial_formula/entry_fee_member_multi_interaction
        """
        ev, cls, alice, bob, vehicles = self._setup_event(api)
        r1 = validate_success(api.create_registration(
            create_registration_payload(ev["id"], alice["id"], vehicles["v1"]["id"], cls["id"]),
            DESK), expected_status=201)
        r2 = validate_success(api.create_registration(
            create_registration_payload(ev["id"], alice["id"], vehicles["v2"]["id"], cls["id"]),
            DESK), expected_status=201)
        assert r1["fee_cents"] == 2700, "member, first vehicle: 3000 * 0.9"
        assert r2["fee_cents"] == 2025, "member, second vehicle: 3000 * 0.9 * 0.75"

    def test_non_member_pays_full_then_multi_vehicle_discount(self, api):
        """PRD §3.2: "the fee drops a further twenty-five percent when this is the
        registrant's second or later vehicle for the same event — that is, when at
        least one other registration of theirs for the event, in `PENDING_PAYMENT`,
        `CONFIRMED`, or `CHECKED_IN`, was created before this one."

        Design: Difficulty/combinatorial_formula/entry_fee_member_multi_interaction
        """
        ev, cls, alice, bob, vehicles = self._setup_event(api)
        r3 = validate_success(api.create_registration(
            create_registration_payload(ev["id"], bob["id"], vehicles["v3"]["id"], cls["id"]),
            DESK), expected_status=201)
        r4 = validate_success(api.create_registration(
            create_registration_payload(ev["id"], bob["id"], vehicles["v4"]["id"], cls["id"]),
            DESK), expected_status=201)
        assert r3["fee_cents"] == 3000, "non-member, first vehicle: no discount"
        assert r4["fee_cents"] == 2250, "non-member, second vehicle: 3000 * 0.75"


class TestRegistrationCreationShape:
    def test_registration_pricing_tier_input_ignored(self, api):
        """PRD §3.2: "Pricing is decided entirely by the logical clock, and any
        client-supplied tier is ignored. When the clock reads earlier than the
        event's `prereg_deadline`, the registration prices at the `PREREG` tier".

        Design: Corner/entities/registration_pricing_tier_input_ignored
        """
        ev, cls, zone = create_open_event()
        reg, veh = create_registrant_with_vehicle()
        created = validate_success(api.create_registration(
            create_registration_payload(ev["id"], reg["id"], veh["id"], cls["id"],
                                        pricing_tier="DAY_OF"),
            DESK), expected_status=201)
        assert created["pricing_tier"] == "PREREG", "client-supplied DAY_OF must be ignored"
        assert created["fee_cents"] == 3000

    def test_registration_initial_state_pending(self, api):
        """PRD §3.2: "A fresh registration sits in `PENDING_PAYMENT`, and the
        class's `confirmed_count` rises by one."

        Design: Corner/state_machines/registration_initial_state_pending
        """
        ev, cls, zone = create_open_event()
        reg, veh = create_registrant_with_vehicle()
        created = validate_success(api.create_registration(
            create_registration_payload(ev["id"], reg["id"], veh["id"], cls["id"]),
            DESK), expected_status=201)
        assert_registration(created)
        assert created["status"] == "PENDING_PAYMENT"
        assert created["paid_cents"] == 0
        assert created["refunded_cents"] == 0
        assert created["spot_number"] is None
        assert created["assigned_zone_id"] is None
        assert created["checked_in_at"] is None
        assert created["fee_cents"] == 3000
        assert created["pricing_tier"] == "PREREG"
