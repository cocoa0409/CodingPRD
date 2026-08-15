"""Pig-group scheduling: initial state, space quotas, half-open occupancy,
barn-version OCC, placement confirmation, and the group's two independent
state dimensions.
"""
from test_helpers import (
    ApiErrorId,
    assert_pig_group,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_feed_order_payload,
    create_market_load_payload,
    create_pig_group_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    FIELDTECH,
    confirm_group,
    create_barn,
    create_scheduled_group,
    deliver_load,
    get_barn,
    get_group,
    set_clock,
    setup_contract_with_barn,
    setup_dispatched_load,
    setup_placed_group,
)

MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestInitialState:
    def test_pig_group_initial_state(self, api):
        """PRD §3.2: "A successfully scheduled group starts `SCHEDULED`, and the
        act of scheduling itself advances the barn's `version` by one — the
        booking book has changed even though no pig has arrived."
        PRD §3.2: "A new group's counters all read zero at scheduling —
        `mortality_total`, `cull_total`, `head_marketed`, `cumulative_feed_lbs`,
        and `pending_deductions_cents` — and its event stamps `placed_at` and
        `closed_at` stay null until confirmation and close respectively set them."
        PRD §3.3: "Every group starts its feed dimension in `STARTER`".
        PRD §3.2: "Until close, `head_current` is the placed head minus
        mortality, culls, and marketed head; it reads zero once the group is
        closed."

        Design: Corner/state_machines/pig_group_initial_state
        """
        ctx = setup_contract_with_barn()
        group = create_scheduled_group(
            ctx["barn"]["id"], ctx["contract"]["id"], head_placed=500
        )
        assert_pig_group(group)
        assert group["group_status"] == "SCHEDULED"
        assert group["current_phase"] == "STARTER"
        assert group["head_current"] == 500
        assert group["mortality_total"] == 0
        assert group["cull_total"] == 0
        assert group["head_marketed"] == 0
        assert group["cumulative_feed_lbs"] == 0
        assert group["pending_deductions_cents"] == 0
        assert group["placed_at"] is None
        assert group["closed_at"] is None

        # Scheduling alone advanced the barn's version by exactly one.
        barn_after = get_barn(ctx["barn"]["id"])
        assert barn_after["version"] == ctx["barn"]["version"] + 1
        # The barn itself is untouched until the pigs arrive.
        assert barn_after["barn_status"] == "AVAILABLE"
        assert barn_after["current_group_id"] is None


class TestSpaceQuotas:
    def test_space_check_head_and_floor_limits(self, api):
        """PRD §3.2: "Capacity is then checked two ways against the scheduled
        head: the head count must not exceed the barn's `capacity_head`
        (`ERR_SPACE_HEAD_EXCEEDED`), and the head count multiplied by eight
        square feet per pig must not exceed the barn's `floor_space_sqft`
        (`ERR_FLOOR_SPACE_EXCEEDED`)."

        Design: Corner/calculations/space_check_head_and_floor_limits
        """
        ctx = setup_contract_with_barn(
            barn_code="BIG",
            barn_overrides={"capacity_head": 1200, "floor_space_sqft": 9600},
        )
        small = create_barn(
            ctx["site"]["id"], barn_code="SML",
            capacity_head=1500, floor_space_sqft=7000,
        )
        set_clock("2026-02-15T00:00:00Z")

        # 1201 head into a 1200-head barn trips the head ceiling.
        payload = create_pig_group_payload(
            ctx["barn"]["id"], ctx["contract"]["id"], ctx["barn"]["version"],
            head_placed=1201,
        )
        res = api.create_pig_group(payload, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_SPACE_HEAD_EXCEEDED, expected_status=409)

        # 1000 head need 8000 sqft; the 7000-sqft barn trips the floor check.
        payload = create_pig_group_payload(
            small["id"], ctx["contract"]["id"], small["version"],
            head_placed=1000,
        )
        res = api.create_pig_group(payload, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_FLOOR_SPACE_EXCEEDED, expected_status=409)


class TestReferenceChecks:
    def test_pig_group_create_unknown_barn_returns_404(self, api):
        """PRD §2.6: "Path identifiers are validated first, in left-to-right
        order as they appear in the URL, and only then are foreign-key
        identifiers in the request body checked; the first missing reference
        fails with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/pig_group_create_unknown_barn_returns_404
        """
        ctx = setup_contract_with_barn()
        set_clock("2026-02-15T00:00:00Z")
        payload = create_pig_group_payload(
            MISSING_UUID, ctx["contract"]["id"], ctx["barn"]["version"],
            placement_date="2026-09-01", target_market_date="2027-01-12",
            head_placed=100,
        )
        res = api.create_pig_group(payload, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_cross_site_reference_rejected(self, api):
        """PRD §3.2: "The barn must not be `OUT_OF_SERVICE`
        (`ERR_BARN_NOT_PLACEABLE`), the barn's site must be `ACTIVE`
        (`ERR_SITE_NOT_ACTIVE`), and the barn's site and the contract's site
        must be the same site (`ERR_CROSS_SITE_REFERENCE`)."
        PRD §2.6: "Cross-aggregate references. A pig group's barn and contract
        must belong to the same site; otherwise `ERR_CROSS_SITE_REFERENCE`
        (HTTP 409)."

        Design: Corner/errors/cross_site_reference_rejected
        """
        ctx = setup_contract_with_barn()  # contract ACTIVE on ctx site (S1)
        site2 = get_success_data(
            api.create_site(
                {"name": "S2", "state_code": "IA", "county": "Lyon"}, ADMIN
            ),
            201,
        )
        barn_s2 = create_barn(site2["id"], barn_code="B1")
        set_clock("2026-02-15T00:00:00Z")
        payload = create_pig_group_payload(
            barn_s2["id"], ctx["contract"]["id"], barn_s2["version"],
            head_placed=100,
        )
        res = api.create_pig_group(payload, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_CROSS_SITE_REFERENCE, expected_status=409)


class TestOptimisticConcurrency:
    def test_occ_stale_barn_version_rejected(self, api):
        """PRD §2.7: "Creating a pig group requires the request to carry
        `expected_barn_version`, holding the barn `version` the client last
        observed. If the barn's current `version` has advanced since that
        observation — because another writer scheduled a group against the same
        barn, or the barn changed state in between — the client's space and
        overlap decision was computed from a superseded view of the barn's
        booking book, and the create is rejected with `ERR_STALE_BARN_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_barn_version_rejected
        """
        ctx = setup_contract_with_barn()
        barn = ctx["barn"]
        stale_version = barn["version"]
        set_clock("2026-02-15T00:00:00Z")

        first = create_pig_group_payload(
            barn["id"], ctx["contract"]["id"], stale_version, head_placed=500,
        )
        group = validate_success(api.create_pig_group(first, FIELDTECH), 201)
        assert_pig_group(group)

        # The first booking advanced the barn's version by one.
        barn_now = get_barn(barn["id"])
        assert barn_now["version"] == stale_version + 1

        # A second create still carrying the stale version is refused even
        # though its interval is disjoint and every other check would pass.
        second = create_pig_group_payload(
            barn["id"], ctx["contract"]["id"], stale_version,
            placement_date="2026-07-13", target_market_date="2026-08-24",
            head_placed=500,
        )
        res = api.create_pig_group(second, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_STALE_BARN_VERSION, expected_status=412)

        data, meta = validate_paginated(
            api.list_pig_groups(ADMIN, params={"barn_id": barn["id"]})
        )
        assert meta["total_count"] == 1


class TestOccupancyOverlap:
    def test_barn_occupancy_half_open_adjacency(self, api):
        """PRD §3.2: "Two stays that merely touch — one group's `placement_date`
        landing exactly on another's `target_market_date` — do not collide."
        PRD §3.2: "Scheduling is rejected with `ERR_OCCUPANCY_OVERLAP` when any
        other group on the same barn in `SCHEDULED`, `PLACED`, or `MARKETING`
        status strictly interleaves with the new stay: the new `placement_date`
        falls before that group's `target_market_date` while that group's
        `placement_date` falls before the new `target_market_date`."

        Design: Difficulty/resource_temporal_overlap/barn_occupancy_half_open_adjacency
        """
        ctx = setup_contract_with_barn()
        barn_id = ctx["barn"]["id"]
        contract_id = ctx["contract"]["id"]

        group_a = create_scheduled_group(barn_id, contract_id, head_placed=1000)
        assert group_a["group_status"] == "SCHEDULED"

        # Adjacent: new placement lands exactly on A's target — no collision.
        barn_v = get_barn(barn_id)["version"]
        payload = create_pig_group_payload(
            barn_id, contract_id, barn_v,
            placement_date="2026-07-13", target_market_date="2026-08-24",
            head_placed=1000,
        )
        group_b = validate_success(api.create_pig_group(payload, FIELDTECH), 201)
        assert group_b["group_status"] == "SCHEDULED"

        # One day earlier strictly interleaves with A and is rejected.
        barn_v = get_barn(barn_id)["version"]
        payload = create_pig_group_payload(
            barn_id, contract_id, barn_v,
            placement_date="2026-07-12", target_market_date="2026-08-24",
            head_placed=1000,
        )
        res = api.create_pig_group(payload, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_OCCUPANCY_OVERLAP, expected_status=409)

    def test_barn_occupancy_touch_at_interval_start(self, api):
        """PRD §3.2: "Two stays that merely touch — one group's `placement_date`
        landing exactly on another's `target_market_date` — do not collide."
        PRD §3.2: "Scheduling is rejected with `ERR_OCCUPANCY_OVERLAP` when any
        other group on the same barn in `SCHEDULED`, `PLACED`, or `MARKETING`
        status strictly interleaves with the new stay".

        The mirror case: a stay whose target equals the existing stay's
        placement is legal, but extending one day past it collides.

        Design: Difficulty/resource_temporal_overlap/barn_occupancy_half_open_adjacency
        """
        ctx = setup_contract_with_barn()
        barn_id = ctx["barn"]["id"]
        contract_id = ctx["contract"]["id"]
        create_scheduled_group(barn_id, contract_id, head_placed=1000)

        # New stay ends exactly where A begins: [2026-03-01, 2026-03-02).
        barn_v = get_barn(barn_id)["version"]
        payload = create_pig_group_payload(
            barn_id, contract_id, barn_v,
            placement_date="2026-03-01", target_market_date="2026-03-02",
            head_placed=500,
        )
        touching = validate_success(api.create_pig_group(payload, FIELDTECH), 201)
        assert touching["group_status"] == "SCHEDULED"

        # Extending the end one day into A's stay collides.
        barn_v = get_barn(barn_id)["version"]
        payload = create_pig_group_payload(
            barn_id, contract_id, barn_v,
            placement_date="2026-03-01", target_market_date="2026-03-03",
            head_placed=500,
        )
        res = api.create_pig_group(payload, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_OCCUPANCY_OVERLAP, expected_status=409)


class TestConfirmPlacement:
    def test_confirm_placement_twice_rejected(self, api):
        """PRD §2.6: "State validity. The target resource must sit in a legal
        from-state for the requested transition; failures surface as
        `ERR_INVALID_STATE_TRANSITION` or one of its domain variants".
        PRD §3.2: "Confirmation stamps `placed_at` with the clock instant and
        flips the barn `AVAILABLE` → `OCCUPIED` with `current_group_id`
        pointing at the group, incrementing the barn's `version`."

        Design: Corner/state_machines/confirm_placement_twice_rejected
        """
        ctx = setup_placed_group(head_placed=500)
        group_id = ctx["group"]["id"]

        res = api.confirm_placement(group_id, {}, FIELDTECH)
        validate_error(
            res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409
        )

        group = get_group(group_id)
        assert group["group_status"] == "PLACED"
        barn = get_barn(ctx["barn"]["id"])
        assert barn["barn_status"] == "OCCUPIED"
        assert barn["current_group_id"] == group_id
        # The barn flipped exactly once.
        assert barn["version"] == ctx["barn"]["version"] + 2  # schedule + confirm

    def test_slot_and_feed_and_confirm_date_errors(self, api):
        """PRD §3.2: "Confirmation requires the barn to be `AVAILABLE`
        (`ERR_BARN_NOT_PLACEABLE` otherwise), the clock date to have reached
        the `placement_date` (confirming early fails with
        `ERR_CONFIRM_TOO_EARLY`), and the governing contract to be `ACTIVE`
        (`ERR_CONTRACT_NOT_ACTIVE`)."
        PRD §3.3: "Feed orders are placed by a `FieldTech` against a group that
        is `PLACED` or `MARKETING` (`ERR_GROUP_NOT_ACTIVE` otherwise), naming
        the `group_id`, the `phase` being fed, the mill's `diet_code`, the
        `quantity_lbs` ordered (at least one pound), and the
        `requested_delivery_date`, which must not lie before the clock date
        (`ERR_FEED_DATE_PAST`)."
        PRD §3.5: "The group must be `PLACED` or `MARKETING`
        (`ERR_GROUP_NOT_ACTIVE`), the slot must not be `CLOSED`
        (`ERR_SLOT_NOT_OPEN`), and the `slot_date` must not lie before the
        clock date (`ERR_SLOT_DATE_PAST`)."

        Design: Corner/errors/slot_and_feed_and_confirm_date_errors
        """
        ctx = setup_contract_with_barn()
        group = create_scheduled_group(
            ctx["barn"]["id"], ctx["contract"]["id"], head_placed=500
        )
        # A slot dated in the past relative to the working clock.
        past_slot = get_success_data(
            api.create_packer_slot(
                {
                    "plant_code": "P1", "slot_date": "2026-02-10", "shift": "AM",
                    "capacity_head": 500, "min_weight_lbs": 240,
                    "max_weight_lbs": 320,
                },
                ADMIN,
            ),
            201,
        )

        # Confirm before placement_date (clock 2026-02-15 < 2026-03-02).
        res = api.confirm_placement(group["id"], {}, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_CONFIRM_TOO_EARLY, expected_status=409)
        assert get_group(group["id"])["group_status"] == "SCHEDULED"

        # Once the clock reaches placement day, the same confirm succeeds.
        placed = confirm_group(group["id"])
        assert placed["group_status"] == "PLACED"

        # Feed order requested before the clock date.
        res = api.create_feed_order(
            create_feed_order_payload(
                group["id"], quantity_lbs=1000,
                requested_delivery_date="2026-03-01",
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_FEED_DATE_PAST, expected_status=409)

        # Booking into a slot whose date has passed.
        res = api.create_market_load(
            create_market_load_payload(
                group["id"], past_slot["id"], past_slot["version"], head_count=100
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_SLOT_DATE_PAST, expected_status=409)


class TestParallelDimensions:
    def test_phase_advance_preserves_lifecycle_status(self, api):
        """PRD §3.3: "A pig group carries two independent state dimensions that
        evolve in parallel: its lifecycle `group_status` and its feed phase
        `current_phase`."
        PRD §3.3: "Every group starts its feed dimension in `STARTER` and may
        advance one step at a time — `STARTER` → `GROWER`, `GROWER` →
        `FINISHER_1`, `FINISHER_1` → `FINISHER_2` — through a `FieldTech`, and
        only while the group's lifecycle is `PLACED` or `MARKETING` (advancing
        otherwise fails with `ERR_GROUP_NOT_ACTIVE`)."

        Design: Difficulty/non_linear_state_machine/pig_group_parallel_dimensions
        """
        ctx = setup_placed_group(head_placed=500)
        group_id = ctx["group"]["id"]

        advanced = validate_success(api.advance_phase(group_id, FIELDTECH), 200)
        assert advanced["current_phase"] == "GROWER"
        assert advanced["group_status"] == "PLACED"

        group = get_group(group_id)
        assert group["current_phase"] == "GROWER"
        assert group["group_status"] == "PLACED"
        assert group["head_current"] == 500

    def test_marketing_delivery_preserves_phase_dimension(self, api):
        """PRD §3.5: "A group's first delivered load also moves its lifecycle
        from `PLACED` to `MARKETING`, and a delivery that drains `head_current`
        to zero closes the group outright (§3.8)."
        PRD §3.3: "A pig group carries two independent state dimensions that
        evolve in parallel: its lifecycle `group_status` and its feed phase
        `current_phase`."

        Interleaved: deliver a load (lifecycle moves, phase stays), then
        advance (phase moves, lifecycle stays).

        Design: Difficulty/non_linear_state_machine/pig_group_parallel_dimensions
        """
        ctx = setup_placed_group(head_placed=500)
        group_id = ctx["group"]["id"]
        get_success_data(api.advance_phase(group_id, FIELDTECH))  # -> GROWER

        _slot, load, _wash = setup_dispatched_load(
            group_id, slot_date="2026-06-20", head_count=100,
            slot_overrides={
                "capacity_head": 500, "min_weight_lbs": 240, "max_weight_lbs": 300,
            },
            washed_at="2026-06-19T08:00:00Z",
            dispatch_clock="2026-06-20T00:00:00Z",
        )
        delivered = deliver_load(load["id"], 26000)
        assert delivered["load_status"] == "DELIVERED"

        group = get_group(group_id)
        assert group["group_status"] == "MARKETING"
        assert group["current_phase"] == "GROWER"
        assert group["head_marketed"] == 100
        assert group["head_current"] == 400

        advanced = validate_success(api.advance_phase(group_id, FIELDTECH), 200)
        assert advanced["current_phase"] == "FINISHER_1"
        assert advanced["group_status"] == "MARKETING"
