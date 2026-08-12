"""Site areas, ground allocations, and the program of demonstrations:
half-open overlap semantics, capacity, area-kind fitness, temporal bounds,
confirmation gates, and combatant-count derivation."""
from test_helpers import (
    TEST_USERS,
    api_client,
    ApiErrorId,
    create_allocation_payload,
    create_program_slot_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_signed_agreement,
    create_allocation,
    create_event,
    create_participant,
    create_program_slot,
    create_site_area,
    get_event,
    open_registration,
    publish_event,
    raise_alert,
    setup_approved_unit,
    setup_contracted_vendor,
    setup_published_event,
    setup_registration_open_event,
    setup_vetted_participant,
)

ORG = TEST_USERS["organizer_headers"]


def _create_event_for_roster():
    """Event with both signed agreements, walked to REGISTRATION_OPEN so a
    unit roster can be built before publishing."""
    event = create_event()
    add_signed_agreement(event["id"], "LANDOWNER_USE")
    add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
    open_registration(event["id"])
    return event


class TestAllocationPartyConstraint:
    def test_allocation_with_two_parties_rejected(self, api):
        """PRD §3.5: "the `units` of capacity consumed, and exactly one of
        `unit_id` or `vendor_id`: naming neither, or both, is rejected with
        `ERR_ALLOCATION_PARTY_REQUIRED`."
        PRD §2.9: "sixth, request-body shape and business constraints (missing or
        malformed fields, unit-in-event, overlap, allocation party, area-kind
        fitness)"

        Design: Corner/entities/allocation_with_two_parties_rejected
        """
        event = setup_registration_open_event()
        area = create_site_area(event["id"], area_kind="CAMP", capacity_units=10,
                                area_name="Camp North")
        unit = setup_approved_unit(event["id"])
        vendor = setup_contracted_vendor(event["id"], frontage_feet=10,
                                         requested_days=2, payment_cents=18000)
        resp = api_client.create_allocation(
            area["id"],
            create_allocation_payload(
                starts_at="2026-07-09T12:00:00Z", ends_at="2026-07-12T12:00:00Z",
                units=2, unit_id=unit["id"], vendor_id=vendor["id"],
            ),
            ORG,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_PARTY_REQUIRED, 422)


class TestAllocationOverlapAndCapacity:
    def test_allocation_adjacency_allowed_overlap_rejected(self, api):
        """PRD §3.5: "overlap — the new window conflicts when it begins before an
        existing window ends and that existing window begins before the new
        window ends, while merely touching endpoints are not a conflict, and a
        violation is `ERR_ALLOCATION_OVERLAP`"

        Design: Corner/validations/allocation_adjacency_allowed_overlap_rejected
        """
        event = setup_registration_open_event()
        area = create_site_area(event["id"], area_kind="CAMP", capacity_units=10,
                                area_name="Camp North")
        unit = setup_approved_unit(event["id"])
        first = create_allocation(area["id"], starts_at="2026-07-09T12:00:00Z",
                                  ends_at="2026-07-12T12:00:00Z", units=2,
                                  unit_id=unit["id"])
        assert first["status"] == "ACTIVE"

        adjacent = api_client.create_allocation(
            area["id"],
            create_allocation_payload(starts_at="2026-07-12T12:00:00Z",
                                      ends_at="2026-07-12T18:00:00Z",
                                      units=2, unit_id=unit["id"]),
            ORG,
        )
        second = validate_success(adjacent, 201)
        assert second["status"] == "ACTIVE", "touching endpoints are not a conflict"

        straddling = api_client.create_allocation(
            area["id"],
            create_allocation_payload(starts_at="2026-07-11T00:00:00Z",
                                      ends_at="2026-07-13T00:00:00Z",
                                      units=2, unit_id=unit["id"]),
            ORG,
        )
        validate_error(straddling, ApiErrorId.ERR_ALLOCATION_OVERLAP, 409)

    def test_allocation_capacity_exceeded_rejected(self, api):
        """PRD §3.5: "the area's `allocated_units` plus the requested `units`
        must not exceed `capacity_units` on an inclusive boundary (a request that
        exactly fills the area succeeds), else `ERR_AREA_CAPACITY_EXCEEDED`"

        Design: Corner/validations/allocation_capacity_exceeded_rejected
        """
        event = setup_registration_open_event()
        area = create_site_area(event["id"], area_kind="CAMP", capacity_units=3,
                                area_name="Camp North")
        unit = setup_approved_unit(event["id"])
        first = create_allocation(area["id"], starts_at="2026-07-09T12:00:00Z",
                                  ends_at="2026-07-10T12:00:00Z", units=2,
                                  unit_id=unit["id"])
        assert first["status"] == "ACTIVE"

        # Adjacent (non-overlapping) window, but 2 + 2 > 3 capacity units.
        over = api_client.create_allocation(
            area["id"],
            create_allocation_payload(starts_at="2026-07-10T12:00:00Z",
                                      ends_at="2026-07-11T12:00:00Z",
                                      units=2, unit_id=unit["id"]),
            ORG,
        )
        validate_error(over, ApiErrorId.ERR_AREA_CAPACITY_EXCEEDED, 409)


class TestSlotTemporalBounds:
    def _setup_published_with_demo(self):
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        return event, area

    def test_slot_inverted_time_range_rejected(self, api):
        """PRD §3.6: "the window must be coherent (`starts_at` strictly before
        `ends_at`, else `ERR_INVALID_TIME_RANGE`)"

        Design: Corner/validations/slot_inverted_time_range_rejected
        """
        event, area = self._setup_published_with_demo()
        resp = api_client.create_program_slot(
            event["id"],
            create_program_slot_payload(area["id"], title="Backwards",
                                        starts_at="2026-07-11T11:00:00Z",
                                        ends_at="2026-07-11T10:00:00Z"),
            ORG,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, 422)

    def test_slot_outside_event_window_rejected(self, api):
        """PRD §3.6: "must lie entirely within the event's public window from
        `event_starts_at` to `event_ends_at` (else `ERR_OUTSIDE_EVENT_WINDOW`)"

        Design: Corner/validations/slot_outside_event_window_rejected
        """
        event, area = self._setup_published_with_demo()
        resp = api_client.create_program_slot(
            event["id"],
            create_program_slot_payload(area["id"], title="Too late",
                                        starts_at="2026-07-13T10:00:00Z",
                                        ends_at="2026-07-13T11:00:00Z"),
            ORG,
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_EVENT_WINDOW, 422)

    def test_slot_on_non_demo_area_rejected(self, api):
        """PRD §3.6: "the area must be `ACTIVE` (`ERR_AREA_NOT_ACTIVE`) and of
        kind `DEMO` (`ERR_AREA_KIND_MISMATCH`)"

        Design: Corner/validations/slot_on_non_demo_area_rejected
        """
        event = setup_published_event()
        camp = create_site_area(event["id"], area_kind="CAMP", capacity_units=10,
                                area_name="Camp North")
        resp = api_client.create_program_slot(
            event["id"],
            create_program_slot_payload(camp["id"], title="Camp talk"),
            ORG,
        )
        validate_error(resp, ApiErrorId.ERR_AREA_KIND_MISMATCH, 422)


class TestSlotHalfOpenOverlap:
    def test_program_slot_half_open_adjacency_allowed(self, api):
        """PRD §3.6: "Slots on the same area must not collide: the new window
        conflicts with an existing `PROPOSED` or `CONFIRMED` slot on that area
        when it begins before the existing slot ends and the existing slot
        begins before the new one ends; touching endpoints are permitted, and a
        true conflict is rejected with `ERR_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/program_slot_half_open_adjacency_allowed
        """
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        slot_a = create_program_slot(event["id"], area["id"], title="Slot A",
                                     starts_at="2026-07-11T10:00:00Z",
                                     ends_at="2026-07-11T11:00:00Z")
        assert slot_a["status"] == "PROPOSED"

        adjacent = api_client.create_program_slot(
            event["id"],
            create_program_slot_payload(area["id"], title="Slot B adjacent",
                                        starts_at="2026-07-11T11:00:00Z",
                                        ends_at="2026-07-11T12:00:00Z"),
            ORG,
        )
        slot_b = validate_success(adjacent, 201)
        assert slot_b["status"] == "PROPOSED", "half-open adjacency is not a conflict"

        overlapping = api_client.create_program_slot(
            event["id"],
            create_program_slot_payload(area["id"], title="Slot C overlapping",
                                        starts_at="2026-07-11T10:30:00Z",
                                        ends_at="2026-07-11T11:30:00Z"),
            ORG,
        )
        validate_error(overlapping, ApiErrorId.ERR_SLOT_OVERLAP, 409)

    def test_program_slot_adjacency_before_existing_allowed(self, api):
        """PRD §3.6: "the new window conflicts with an existing `PROPOSED` or
        `CONFIRMED` slot on that area when it begins before the existing slot
        ends and the existing slot begins before the new one ends; touching
        endpoints are permitted, and a true conflict is rejected with
        `ERR_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/program_slot_half_open_adjacency_allowed
        """
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        create_program_slot(event["id"], area["id"], title="Slot A",
                            starts_at="2026-07-11T10:00:00Z",
                            ends_at="2026-07-11T11:00:00Z")

        before = api_client.create_program_slot(
            event["id"],
            create_program_slot_payload(area["id"], title="Slot B before",
                                        starts_at="2026-07-11T09:00:00Z",
                                        ends_at="2026-07-11T10:00:00Z"),
            ORG,
        )
        slot_b = validate_success(before, 201)
        assert slot_b["status"] == "PROPOSED", "ending exactly at A's start is permitted"

        containing = api_client.create_program_slot(
            event["id"],
            create_program_slot_payload(area["id"], title="Slot C containing",
                                        starts_at="2026-07-11T09:30:00Z",
                                        ends_at="2026-07-11T11:30:00Z"),
            ORG,
        )
        validate_error(containing, ApiErrorId.ERR_SLOT_OVERLAP, 409)


class TestSlotConfirmationGates:
    def test_slot_confirm_requires_active_site_area(self, api):
        """PRD §3.6: "Four gates apply: the area must still be `ACTIVE`
        (`ERR_AREA_NOT_ACTIVE`)"
        PRD §3.6: "Confirmation is the organizer's commitment to run the program,
        valid only from `PROPOSED` (`ERR_INVALID_SLOT_STATUS`)."

        Design: Difficulty/cross_entity_state_dependency/slot_confirm_requires_active_site_area
        """
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        slot = create_program_slot(event["id"], area["id"], title="Loom demonstration",
                                   open_flame=False, required_combatants=0)
        validate_success(api_client.close_site_area(area["id"], ORG), 200)

        resp = api_client.confirm_program_slot(slot["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_AREA_NOT_ACTIVE, 409)
        slots = validate_success(api_client.list_event_program_slots(event["id"], ORG), 200)
        assert slots[0]["status"] == "PROPOSED", "rejected confirmation leaves the slot PROPOSED"

    def test_slot_create_on_closed_area_rejected(self, api):
        """PRD §3.6: "Proposal requires posture `PUBLISHED` or `EVENT_OPEN`; the
        area must be `ACTIVE` (`ERR_AREA_NOT_ACTIVE`) and of kind `DEMO`
        (`ERR_AREA_KIND_MISMATCH`)"

        Design: Difficulty/cross_entity_state_dependency/slot_confirm_requires_active_site_area
        """
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        validate_success(api_client.close_site_area(area["id"], ORG), 200)
        resp = api_client.create_program_slot(
            event["id"],
            create_program_slot_payload(area["id"], title="Closed field talk",
                                        open_flame=False, required_combatants=0),
            ORG,
        )
        validate_error(resp, ApiErrorId.ERR_AREA_NOT_ACTIVE, 409)


class TestCombatantCount:
    def test_combatant_count_excludes_unvetted_and_noncombatant(self, api):
        """PRD §3.3: "The event-level `approved_combatant_count` counts
        participants of the event whose status is `VETTED` or `CHECKED_IN`, whose
        `impression_class` is `COMBATANT`, and whose unit — when they have one —
        is `APPROVED`"
        PRD §3.3: "Records in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`,
        `REJECTED`, or `WITHDRAWN` never count."
        PRD §3.6: "`required_combatants` must not exceed the event's current
        `approved_combatant_count` (`ERR_VALIDATION`)"

        Design: Corner/calculations/combatant_count_excludes_unvetted_and_noncombatant
        """
        event = _create_event_for_roster()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        unit = setup_approved_unit(event["id"])
        setup_vetted_participant(event["id"], unit_id=unit["id"],
                                 full_name="Vet Combatant", age_at_event=30,
                                 impression_class="COMBATANT")
        # DRAFT combatant: never submitted, so it never counts.
        create_participant(event["id"], unit_id=unit["id"], full_name="Draft Combatant",
                           age_at_event=28, impression_class="COMBATANT")
        # VETTED civilian: right status, wrong impression class.
        setup_vetted_participant(event["id"], unit_id=unit["id"], full_name="Vet Civilian",
                                 age_at_event=40, impression_class="CIVILIAN")
        publish_event(event["id"])

        slot = create_program_slot(event["id"], area["id"], title="Battle demo",
                                   open_flame=False, required_combatants=2)
        reread = get_event(event["id"])
        assert reread["approved_combatant_count"] == 1, (
            "only the VETTED COMBATANT counts"
        )
        resp = api_client.confirm_program_slot(slot["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestConfirmationPriorityPair:
    def _setup_cancelled_flame_slot_under_watch(self):
        """PUBLISHED event; DEMO area; open-flame slot created then cancelled;
        a WATCH alert keeps restriction_level YELLOW without changing posture."""
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        slot = create_program_slot(event["id"], area["id"], title="Artillery demonstration",
                                   open_flame=True, required_combatants=0)
        validate_success(
            api_client.cancel_program_slot(slot["id"], ORG, {"reason": "scheduling conflict"}),
            200,
        )
        raise_alert(event["id"], severity="WATCH", alert_kind="FIRE",
                    message="grass fire watch in county")
        return event, slot

    def test_slot_confirm_state_error_beats_flame_safety_error(self, api):
        """PRD §2.9: "The order is: first authentication and role/ownership
        authorization (§2.1); second, referential existence of every identifier
        appearing in the path or body; third, the optimistic-concurrency
        staleness check; fourth, state and posture fitness; fifth, business
        safety gates (uninspected equipment, supervisor rules and ratios,
        open-flame restriction, open red-flag alerts, segregation of duties)"
        PRD §2.9: "a request failing an earlier category never surfaces a later
        category's error"

        Design: Difficulty/priority_pair_validation_conflict/slot_confirm_state_error_beats_flame_safety_error
        """
        event, slot = self._setup_cancelled_flame_slot_under_watch()
        assert get_event(event["id"])["restriction_level"] == "YELLOW"

        resp = api_client.confirm_program_slot(slot["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_STATUS, 409)

    def test_slot_confirm_state_error_applies_no_change(self, api):
        """PRD §2.9: "The order is: first authentication and role/ownership
        authorization (§2.1); second, referential existence of every identifier
        appearing in the path or body; third, the optimistic-concurrency
        staleness check; fourth, state and posture fitness; fifth, business
        safety gates (uninspected equipment, supervisor rules and ratios,
        open-flame restriction, open red-flag alerts, segregation of duties)"
        PRD §3.6: "cancelling from any other status is `ERR_INVALID_SLOT_STATUS`"

        Design: Difficulty/priority_pair_validation_conflict/slot_confirm_state_error_beats_flame_safety_error
        """
        event, slot = self._setup_cancelled_flame_slot_under_watch()
        resp = api_client.confirm_program_slot(slot["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_STATUS, 409)
        slots = validate_success(api_client.list_event_program_slots(event["id"], ORG), 200)
        assert slots[0]["status"] == "CANCELLED", (
            "the state error pre-empts the flame gate and mutates nothing"
        )
        assert slots[0]["cancel_reason"] == "scheduling conflict"
        assert get_event(event["id"])["restriction_level"] == "YELLOW"
