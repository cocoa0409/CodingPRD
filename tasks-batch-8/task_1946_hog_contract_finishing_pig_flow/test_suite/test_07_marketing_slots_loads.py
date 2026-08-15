"""Packer slots and market loads: slot uniqueness, head-capacity boundary,
aggregate-vs-interval overlap semantics, reserved-head conservation,
slot-version OCC, projected weight window, and slot close guard.
"""
from test_helpers import (
    ApiErrorId,
    assert_market_load,
    assert_packer_slot,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_market_load_payload,
    create_pig_group_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    FIELDTECH,
    book_load,
    create_slot,
    create_verified_truck_wash,
    dispatch_load,
    get_barn,
    set_clock,
    setup_placed_group,
)

SLOT_AM = {"slot_date": "2026-07-13", "shift": "AM",
           "capacity_head": 340, "min_weight_lbs": 240, "max_weight_lbs": 320}


class TestSlotUniqueness:
    def test_duplicate_slot_rejected(self, api):
        """PRD §3.5: "An `IntegratorAdmin` opens **packer slots**, each
        identified by its `plant_code`, `slot_date`, and `shift` — `AM` or
        `PM` — and the combination of those three must be unique, with
        duplicates rejected as `ERR_DUPLICATE_SLOT`."

        Design: Corner/errors/duplicate_slot_rejected
        """
        set_clock("2026-02-15T00:00:00Z")
        slot1 = create_slot(
            plant_code="P1", slot_date="2026-07-13", shift="AM",
            capacity_head=500, min_weight_lbs=240, max_weight_lbs=320,
        )
        assert_packer_slot(slot1)
        assert slot1["slot_status"] == "OPEN"
        assert slot1["reserved_head"] == 0

        res = api.create_packer_slot(
            {
                "plant_code": "P1", "slot_date": "2026-07-13", "shift": "AM",
                "capacity_head": 300, "min_weight_lbs": 240,
                "max_weight_lbs": 320,
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_SLOT, expected_status=409)

        # Same plant and date with a different shift is a distinct slot.
        slot2 = create_slot(
            plant_code="P1", slot_date="2026-07-13", shift="PM",
            capacity_head=300, min_weight_lbs=240, max_weight_lbs=320,
        )
        assert slot2["shift"] == "PM"


class TestSlotCapacityBoundary:
    def test_slot_capacity_exact_fit_then_one_over(self, api):
        """PRD §3.5: "Because slots book out, capacity is gated: the slot's
        `reserved_head` plus the new `head_count` must stay at or below
        `capacity_head` — landing exactly on capacity is allowed — and an
        overage is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`."
        PRD §3.5: "When the reserved head reaches `capacity_head` exactly, the
        slot flips itself from `OPEN` to `FULL`; when a cancellation later
        pulls the reserved head back below capacity, it flips back to `OPEN`."

        170 + 170 == 340 == capacity fills the slot exactly; the 341st head is
        rejected.

        Design: Difficulty/boundary_precision_check/slot_capacity_exact_fit_then_one_over
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        slot = create_slot(**SLOT_AM)

        load1 = book_load(group_id, slot["id"], 170)
        assert_market_load(load1)
        load2 = book_load(group_id, slot["id"], 170)
        assert load2["load_status"] == "SCHEDULED"

        slot_now = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_now["reserved_head"] == 340
        assert slot_now["slot_status"] == "FULL"

        res = api.create_market_load(
            create_market_load_payload(
                group_id, slot["id"], slot_now["version"], head_count=1
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED,
                       expected_status=409)

        slot_after = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_after["reserved_head"] == 340
        assert slot_after["slot_status"] == "FULL"

    def test_slot_capacity_single_exact_booking_and_over(self, api):
        """PRD §3.5: "the slot's `reserved_head` plus the new `head_count` must
        stay at or below `capacity_head` — landing exactly on capacity is
        allowed — and an overage is rejected with
        `ERR_SLOT_CAPACITY_EXCEEDED`."

        A single 340-head booking lands exactly on capacity; a first booking of
        341 on a sibling slot is rejected outright.

        Design: Difficulty/boundary_precision_check/slot_capacity_exact_fit_then_one_over
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        slot_a = create_slot(**SLOT_AM)
        slot_b = create_slot(**{**SLOT_AM, "shift": "PM"})

        load = book_load(group_id, slot_a["id"], 340)
        assert load["load_status"] == "SCHEDULED"
        slot_now = validate_success(api.get_packer_slot(slot_a["id"], FIELDTECH), 200)
        assert slot_now["reserved_head"] == 340
        assert slot_now["slot_status"] == "FULL"

        res = api.create_market_load(
            create_market_load_payload(
                group_id, slot_b["id"], slot_b["version"], head_count=341
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED,
                       expected_status=409)


class TestAggregateVsIntervalSemantics:
    def test_slot_accumulates_while_barn_excludes(self, api):
        """PRD §3.5: "A slot's `reserved_head` is the sum of `head_count`
        across its loads in `SCHEDULED`, `DISPATCHED`, `DELIVERED`, or
        `REJECTED_AT_PLANT` status — cancelled loads drop out of the reserved
        set."
        PRD §3.2: "Scheduling is rejected with `ERR_OCCUPANCY_OVERLAP` when any
        other group on the same barn in `SCHEDULED`, `PLACED`, or `MARKETING`
        status strictly interleaves with the new stay".

        Same calendar instant, two resources, opposite overlap treatment: two
        200-head loads accumulate onto one slot while a second group
        overlapping the barn's calendar is excluded.

        Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_vs_barn_interval_exclusion
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        slot = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=500,
                           min_weight_lbs=240, max_weight_lbs=320)

        book_load(group_id, slot["id"], 200)
        book_load(group_id, slot["id"], 200)
        slot_now = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_now["reserved_head"] == 400
        assert slot_now["slot_status"] == "OPEN"

        barn_v = get_barn(ctx["barn"]["id"])["version"]
        res = api.create_pig_group(
            create_pig_group_payload(
                ctx["barn"]["id"], ctx["contract"]["id"], barn_v,
                placement_date="2026-03-15", target_market_date="2026-06-15",
                head_placed=100,
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_OCCUPANCY_OVERLAP, expected_status=409)

    def test_slot_accumulates_to_exact_capacity_full_flip(self, api):
        """PRD §3.5: "the slot's `reserved_head` plus the new `head_count` must
        stay at or below `capacity_head` — landing exactly on capacity is
        allowed — and an overage is rejected with
        `ERR_SLOT_CAPACITY_EXCEEDED`."
        PRD §3.2: "Two stays that merely touch — one group's `placement_date`
        landing exactly on another's `target_market_date` — do not collide."

        Aggregate semantics keep accumulating to the exact capacity (FULL),
        while the barn's half-open interval still admits the touching stay.

        Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_vs_barn_interval_exclusion
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        slot = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=500,
                           min_weight_lbs=240, max_weight_lbs=320)
        book_load(group_id, slot["id"], 200)
        book_load(group_id, slot["id"], 200)
        book_load(group_id, slot["id"], 100)
        slot_now = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_now["reserved_head"] == 500
        assert slot_now["slot_status"] == "FULL"

        # The touching group on the barn remains legal throughout.
        barn_v = get_barn(ctx["barn"]["id"])["version"]
        adjacent = validate_success(
            api.create_pig_group(
                create_pig_group_payload(
                    ctx["barn"]["id"], ctx["contract"]["id"], barn_v,
                    placement_date="2026-07-13", target_market_date="2026-08-24",
                    head_placed=100,
                ),
                FIELDTECH,
            ),
            201,
        )
        assert adjacent["group_status"] == "SCHEDULED"


class TestReservedHeadConservation:
    def _setup_april_group(self):
        return setup_placed_group(
            head_placed=300,
            placement_date="2026-04-15", target_market_date="2026-10-06",
        )

    def test_slot_reserved_head_schedule_cancel_conserved(self, api):
        """PRD §3.5: "A slot's `reserved_head` is the sum of `head_count`
        across its loads in `SCHEDULED`, `DISPATCHED`, `DELIVERED`, or
        `REJECTED_AT_PLANT` status — cancelled loads drop out of the reserved
        set."
        PRD §3.5: "A `FieldTech` may cancel a load while it is `SCHEDULED` or
        `DISPATCHED`, moving it to `CANCELLED`. Cancellation pulls the load out
        of the slot's reserved set — `reserved_head` is recomputed, the slot's
        `version` advances, and a `FULL` slot that drops below capacity flips
        back to `OPEN`."

        Design: Difficulty/compensating_invariant/slot_reserved_head_schedule_cancel_conserved
        """
        ctx = self._setup_april_group()
        group_id = ctx["group"]["id"]
        slot = create_slot(slot_date="2026-08-20", shift="AM", capacity_head=340,
                           min_weight_lbs=240, max_weight_lbs=320)
        assert slot["reserved_head"] == 0

        load = book_load(group_id, slot["id"], 170)
        slot_mid = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_mid["reserved_head"] == 170

        cancelled = validate_success(api.cancel_market_load(load["id"], FIELDTECH), 200)
        assert cancelled["load_status"] == "CANCELLED"
        slot_end = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_end["reserved_head"] == 0
        assert slot_end["slot_status"] == "OPEN"

    def test_dispatched_load_cancel_frees_slot_head_and_truck_wash(self, api):
        """PRD §3.5: "Cancellation pulls the load out of the slot's reserved
        set — `reserved_head` is recomputed, the slot's `version` advances, and
        a `FULL` slot that drops below capacity flips back to `OPEN`. When the
        cancelled load had been dispatched, its truck wash is freed for reuse
        by another load."

        Design: Difficulty/compensating_invariant/slot_reserved_head_schedule_cancel_conserved
        """
        ctx = self._setup_april_group()
        group_id = ctx["group"]["id"]
        slot = create_slot(slot_date="2026-08-20", shift="AM", capacity_head=340,
                           min_weight_lbs=240, max_weight_lbs=320)
        load1 = book_load(group_id, slot["id"], 170)

        set_clock("2026-08-19T08:00:00Z")
        wash = create_verified_truck_wash("2026-08-19T08:00:00Z")
        dispatch_load(load1["id"], wash["id"])

        get_success_data(api.cancel_market_load(load1["id"], FIELDTECH))
        slot_now = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_now["reserved_head"] == 0
        assert slot_now["slot_status"] == "OPEN"

        # The freed wash may back another load immediately.
        load2 = book_load(group_id, slot["id"], 170)
        set_clock("2026-08-19T09:00:00Z")
        dispatched = dispatch_load(load2["id"], wash["id"])
        assert dispatched["load_status"] == "DISPATCHED"
        assert dispatched["truck_wash_id"] == wash["id"]


class TestSlotOCC:
    def test_occ_stale_slot_version_rejected(self, api):
        """PRD §2.7: "Creating a market load requires the request to carry
        `expected_slot_version`, holding the packer slot `version` the client
        last observed. If the slot's current `version` has advanced since that
        observation, the client's head-capacity decision was computed from a
        superseded view of the slot's reservation book, and the create is
        rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412)."
        PRD §3.5: "A booked load starts `SCHEDULED`; booking recomputes the
        slot's `reserved_head`, advances the slot's `version` by one, and may
        flip the slot `OPEN` → `FULL`."

        Design: Corner/cross_cutting_layers/occ_stale_slot_version_rejected
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        slot = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=500,
                           min_weight_lbs=240, max_weight_lbs=320)
        stale_version = slot["version"]

        load1 = book_load(group_id, slot["id"], 200)
        assert load1["load_status"] == "SCHEDULED"

        slot_now = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_now["version"] == stale_version + 1

        res = api.create_market_load(
            create_market_load_payload(
                group_id, slot["id"], stale_version, head_count=200
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_STALE_SLOT_VERSION, expected_status=412)

        slot_after = validate_success(api.get_packer_slot(slot["id"], FIELDTECH), 200)
        assert slot_after["reserved_head"] == 200


class TestProjectedWeightWindow:
    def test_projected_weight_window_edges(self, api):
        """PRD §3.5: "The projection takes the number of days from the group's
        `placement_date` to the slot's `slot_date` — never negative —
        multiplies it by 1.85 pounds of projected gain per day, and adds the
        group's `avg_start_weight_lbs`. The projected average weight, rounded
        half-up to two decimal places, must land inside the slot's weight
        window — at least `min_weight_lbs` and at most `max_weight_lbs` — or
        the booking is rejected with `ERR_WEIGHT_WINDOW_PROJECTED`."

        Placement 2026-03-02 to slot 2026-07-13 is 133 days: 50.0 + 1.85*133
        = 296.05 projected. A max-300 slot accepts the booking; a max-296 slot
        rejects it.

        Design: Corner/calculations/projected_weight_window_edges
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        slot_a = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=500,
                             min_weight_lbs=240, max_weight_lbs=300)
        slot_b = create_slot(slot_date="2026-07-13", shift="PM", capacity_head=500,
                             min_weight_lbs=240, max_weight_lbs=296)

        load = book_load(group_id, slot_a["id"], 100)
        assert load["load_status"] == "SCHEDULED"

        res = api.create_market_load(
            create_market_load_payload(
                group_id, slot_b["id"], slot_b["version"], head_count=100
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_WEIGHT_WINDOW_PROJECTED,
                       expected_status=409)


class TestSlotCloseGuard:
    def test_slot_close_with_active_loads_rejected(self, api):
        """PRD §3.5: "An `IntegratorAdmin` may close a slot from either `OPEN`
        or `FULL`, moving it to the terminal `CLOSED`, but only while no load
        against it remains `SCHEDULED` or `DISPATCHED`
        (`ERR_SLOT_HAS_ACTIVE_LOADS`)."

        Design: Corner/errors/slot_close_with_active_loads_rejected
        """
        ctx = setup_placed_group(head_placed=500)
        slot = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=500,
                           min_weight_lbs=240, max_weight_lbs=320)
        load = book_load(ctx["group"]["id"], slot["id"], 100)

        res = api.close_packer_slot(slot["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_SLOT_HAS_ACTIVE_LOADS,
                       expected_status=409)

        get_success_data(api.cancel_market_load(load["id"], FIELDTECH))
        closed = validate_success(api.close_packer_slot(slot["id"], ADMIN), 200)
        assert closed["slot_status"] == "CLOSED"

