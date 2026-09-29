"""GPO contract headers, their price lines, and the effective-period rules.

Covers the contract status machine, the cascade into contract-line activation
states, the closed-interval overlap rule that guards activation, and the
server's logical clock.
"""

from test_helpers import (
    ApiErrorId,
    add_contract_line,
    activate_contract,
    assert_contract_line,
    assert_gpo_contract,
    assert_instant_equals,
    create_contract,
    create_item,
    create_order,
    create_order_line_payload,
    contract_transition_payload,
    make_materials_manager_headers,
    read_contract,
    read_contract_line,
    read_order,
    set_clock,
    setup_priced_item,
    transition_contract,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def test_contract_line_is_reachable_from_both_sides_of_the_price_sheet(api):
    """PRD §3.2: "Price lines may be read individually or listed filtered by
    `contract_id` to walk a contract's price sheet, by `item_id` to see every
    contract that prices an item, or by `activation_state`."
    PRD §3.2: "Every line is born in `activation_state` `PENDING`, and a
    `PENDING` line prices nothing."

    Design: Corner/entities/contract_line_junction_row_reachable_from_both_contract_and_item
    """
    item = create_item(
        sku="SKU-JXN-CS",
        description="Junction probe",
        manufacturer_code="MFR-ACME",
        uom="CS",
        wac_cents=3000,
        handling_class="AMBIENT",
        units_per_parent=12,
    )
    contract = create_contract(
        manufacturer_code="MFR-ACME",
        contract_code="CTR-JXN",
        tier="TIER_2",
        member_class_scope="ACUTE",
    )
    line = add_contract_line(
        contract["id"], item["id"], tier_price_cents=2500, floor_price_cents=2000
    )
    assert_contract_line(line)

    by_contract, contract_meta = validate_paginated(
        api.list_contract_lines(
            ADMIN, params={"contract_id": contract["id"], "limit": 10, "offset": 0}
        )
    )
    by_item, item_meta = validate_paginated(
        api.list_contract_lines(
            ADMIN, params={"item_id": item["id"], "limit": 10, "offset": 0}
        )
    )

    assert contract_meta["total_count"] == 1
    assert item_meta["total_count"] == 1
    assert by_contract[0]["id"] == line["id"]
    assert by_item[0]["id"] == line["id"]
    assert line["activation_state"] == "PENDING"
    assert line["contract_id"] == contract["id"]


def test_contract_cannot_activate_straight_out_of_draft(api):
    """PRD §3.2: "`PENDING_ACTIVATION → ACTIVE` is permitted only from
    `PENDING_ACTIVATION`, only while the logical clock lies inside the closed
    effective period, and only when the overlap rule below passes; on success
    `activated_at` is set to the current logical clock and **every** line of the
    contract moves `PENDING → ACTIVE`, becoming selectable by the price
    selector."
    PRD §3.2: "Any requested `to_status` unreachable from the current status, an
    expiry attempted while the clock is still at or before `effective_to`, an
    activation attempted outside the effective period, or a move toward
    `PENDING_ACTIVATION` on a contract with no price line, are all
    `ERR_CONTRACT_TRANSITION_INVALID` (HTTP 409)."

    Design: Corner/state_machines/contract_activate_directly_from_draft_is_rejected
    """
    item = create_item(
        sku="SKU-SM1-CS",
        description="State probe 1",
        manufacturer_code="MFR-ACME",
        uom="CS",
        wac_cents=4000,
        handling_class="AMBIENT",
        units_per_parent=10,
    )
    contract = create_contract(manufacturer_code="MFR-ACME", contract_code="CTR-SM1")
    line = add_contract_line(
        contract["id"], item["id"], tier_price_cents=3000, floor_price_cents=2000
    )

    response = api.transition_contract(
        contract["id"], contract_transition_payload("ACTIVE"), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_TRANSITION_INVALID.value, 409)

    after = read_contract(contract["id"])
    assert_gpo_contract(after)
    assert after["status"] == "DRAFT"
    assert after.get("activated_at") is None
    assert read_contract_line(line["id"])["activation_state"] == "PENDING"


def test_contract_without_a_price_line_cannot_leave_draft(api):
    """PRD §3.2: "`DRAFT → PENDING_ACTIVATION` is permitted only from `DRAFT`
    and only when the contract already has at least one price line; nothing
    becomes usable at this step, and every line stays `PENDING`."
    PRD §3.2: "Any requested `to_status` unreachable from the current status, an
    expiry attempted while the clock is still at or before `effective_to`, an
    activation attempted outside the effective period, or a move toward
    `PENDING_ACTIVATION` on a contract with no price line, are all
    `ERR_CONTRACT_TRANSITION_INVALID` (HTTP 409)."

    Design: Corner/state_machines/contract_pending_activation_requires_at_least_one_line
    """
    contract = create_contract(manufacturer_code="MFR-ACME", contract_code="CTR-SM2")

    response = api.transition_contract(
        contract["id"], contract_transition_payload("PENDING_ACTIVATION"), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_TRANSITION_INVALID.value, 409)
    assert read_contract(contract["id"])["status"] == "DRAFT"


def test_contract_expires_only_once_the_clock_passes_effective_to(api):
    """PRD §3.2: "`ACTIVE → EXPIRED` is permitted only from `ACTIVE` and only
    once the logical clock is strictly past `effective_to`, and it moves every
    line `ACTIVE → BLOCKED`."
    PRD §2.4: "The server maintains a **logical clock** that starts at exactly
    `2026-08-01T00:00:00Z` when the server boots and only ever moves when a
    `ContractAdmin` sets it, by supplying a `to_iso8601` instant to the
    clock-setting capability; the response reports the resulting `current_utc`."

    Design: Corner/state_machines/contract_expire_before_effective_to_is_rejected
    """
    item = create_item(
        sku="SKU-SM3-CS",
        description="Expiry probe",
        manufacturer_code="MFR-ACME",
        uom="CS",
        wac_cents=4000,
        handling_class="AMBIENT",
        units_per_parent=10,
    )
    contract = create_contract(manufacturer_code="MFR-ACME", contract_code="CTR-SM3")
    line = add_contract_line(
        contract["id"], item["id"], tier_price_cents=3000, floor_price_cents=2000
    )
    activate_contract(contract["id"])

    early = api.transition_contract(
        contract["id"], contract_transition_payload("EXPIRED"), ADMIN
    )
    validate_error(early, ApiErrorId.ERR_CONTRACT_TRANSITION_INVALID.value, 409)
    assert read_contract(contract["id"])["status"] == "ACTIVE"

    set_clock("2027-01-01T00:00:00Z")
    expired = transition_contract(contract["id"], "EXPIRED")

    assert expired["status"] == "EXPIRED"
    assert read_contract_line(line["id"])["activation_state"] == "BLOCKED"


def test_suspension_blocks_the_price_lines_and_resumption_restores_them(api):
    """PRD §3.2: "`ACTIVE → SUSPENDED` is permitted from `ACTIVE` at any time
    and moves every line `ACTIVE → BLOCKED`, which stops those lines being
    selectable by the price selector; already-pinned order-line prices are not
    rewritten by a suspension."
    PRD §3.2: "`SUSPENDED → ACTIVE` closes the cycle: it is permitted only from
    `SUSPENDED`, only inside the closed effective period, and only when the
    overlap rule passes; it re-stamps `activated_at` and moves every line
    `BLOCKED → ACTIVE`."
    PRD §3.2: "An empty candidate set is a hard failure —
    `ERR_NO_ACTIVE_CONTRACT_PRICE` (HTTP 422) — never a zero price."

    Design: Corner/state_machines/contract_suspend_blocks_lines_and_resume_reactivates_them
    """
    world = setup_priced_item(
        room_overrides={
            "facility_code": "FAC-204",
            "room_code": "GEN-204",
            "gpo_member_class": "ACUTE",
            "room_type": "GENERAL_STORE",
        },
        item_overrides={
            "sku": "SKU-SM4-CS",
            "description": "Suspend probe",
            "manufacturer_code": "MFR-ACME",
            "uom": "CS",
            "wac_cents": 8000,
            "handling_class": "AMBIENT",
            "units_per_parent": 10,
        },
        contract_overrides={"manufacturer_code": "MFR-ACME", "contract_code": "CTR-SM4"},
        tier_price_cents=3000,
        floor_price_cents=2000,
        formulary_overrides={"facility_item_code": "FAC-SM4", "par_qty": 50,
                             "reorder_point": 10},
    )
    order = create_order(world["room"]["id"])
    mm_headers = make_materials_manager_headers(world["room"]["id"])

    suspended = transition_contract(world["contract"]["id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"
    assert read_contract_line(world["contract_line"]["id"])["activation_state"] == "BLOCKED"

    blocked_write = api.create_order_line(
        order["id"],
        create_order_line_payload(world["item"]["id"], 1, order["version"]),
        mm_headers,
    )
    validate_error(blocked_write, ApiErrorId.ERR_NO_ACTIVE_CONTRACT_PRICE.value, 422)

    resumed = transition_contract(world["contract"]["id"], "ACTIVE")
    assert resumed["status"] == "ACTIVE"
    assert read_contract_line(world["contract_line"]["id"])["activation_state"] == "ACTIVE"

    line = validate_success(
        api.create_order_line(
            order["id"],
            create_order_line_payload(world["item"]["id"], 1, order["version"]),
            mm_headers,
        ),
        201,
    )
    assert line["pinned_unit_price_cents"] == 3000
    assert line["pinned_contract_line_id"] == world["contract_line"]["id"]
    assert read_order(order["id"])["order_total_cents"] == 3083


def test_logical_clock_boots_at_the_first_of_august_2026(api):
    """PRD §2.4: "The server maintains a **logical clock** that starts at exactly
    `2026-08-01T00:00:00Z` when the server boots and only ever moves when a
    `ContractAdmin` sets it, by supplying a `to_iso8601` instant to the
    clock-setting capability; the response reports the resulting `current_utc`."
    PRD §3.2: "`PENDING_ACTIVATION → ACTIVE` is permitted only from
    `PENDING_ACTIVATION`, only while the logical clock lies inside the closed
    effective period, and only when the overlap rule below passes; on success
    `activated_at` is set to the current logical clock and **every** line of the
    contract moves `PENDING → ACTIVE`, becoming selectable by the price
    selector."

    Design: Corner/endpoints/logical_clock_default_is_2026_08_01_before_any_set_call
    """
    item_a = create_item(
        sku="SKU-CLK-A-CS", description="Clock probe A", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=5000, handling_class="AMBIENT", units_per_parent=10,
    )
    item_b = create_item(
        sku="SKU-CLK-B-CS", description="Clock probe B", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=5000, handling_class="AMBIENT", units_per_parent=10,
    )

    past = create_contract(
        manufacturer_code="MFR-ACME", contract_code="CTR-PAST", tier="TIER_1",
        member_class_scope="ACUTE",
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-07-31T23:59:59Z",
    )
    add_contract_line(past["id"], item_a["id"], tier_price_cents=1000,
                      floor_price_cents=900)
    transition_contract(past["id"], "PENDING_ACTIVATION")

    now = create_contract(
        manufacturer_code="MFR-ACME", contract_code="CTR-NOW", tier="TIER_1",
        member_class_scope="ACUTE",
        effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-02T23:59:59Z",
    )
    now_line = add_contract_line(now["id"], item_b["id"], tier_price_cents=1000,
                                 floor_price_cents=900)
    transition_contract(now["id"], "PENDING_ACTIVATION")

    stale = api.transition_contract(
        past["id"], contract_transition_payload("ACTIVE"), ADMIN
    )
    validate_error(stale, ApiErrorId.ERR_CONTRACT_TRANSITION_INVALID.value, 409)
    assert read_contract(past["id"])["status"] == "PENDING_ACTIVATION"

    activated = transition_contract(now["id"], "ACTIVE")
    assert activated["status"] == "ACTIVE"
    assert_instant_equals(activated["activated_at"], "2026-08-01T00:00:00", "activated_at")
    assert read_contract_line(now_line["id"])["activation_state"] == "ACTIVE"


class TestClosedEffectivePeriodOverlap:
    """Contract effective periods are closed at both ends, so two periods that
    touch at a single instant collide."""

    @staticmethod
    def _build_overlap_world():
        item = create_item(
            sku="SKU-OVL-CS", description="Overlap probe commodity, case",
            manufacturer_code="MFR-ACME", uom="CS", wac_cents=9000,
            handling_class="AMBIENT", units_per_parent=12,
        )
        incumbent = create_contract(
            manufacturer_code="MFR-ACME", contract_code="CTR-X", tier="TIER_1",
            member_class_scope="ACUTE",
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-08-31T23:59:59Z",
        )
        add_contract_line(incumbent["id"], item["id"], tier_price_cents=4000,
                          floor_price_cents=3000)
        activate_contract(incumbent["id"])

        touching = create_contract(
            manufacturer_code="MFR-ACME", contract_code="CTR-Y", tier="TIER_1",
            member_class_scope="ACUTE",
            effective_from="2026-08-31T23:59:59Z", effective_to="2026-12-31T23:59:59Z",
        )
        add_contract_line(touching["id"], item["id"], tier_price_cents=4100,
                          floor_price_cents=3000)
        transition_contract(touching["id"], "PENDING_ACTIVATION")

        disjoint = create_contract(
            manufacturer_code="MFR-ACME", contract_code="CTR-Z", tier="TIER_1",
            member_class_scope="ACUTE",
            effective_from="2026-09-01T00:00:00Z", effective_to="2026-12-31T23:59:59Z",
        )
        disjoint_line = add_contract_line(disjoint["id"], item["id"],
                                          tier_price_cents=4200, floor_price_cents=3000)
        transition_contract(disjoint["id"], "PENDING_ACTIVATION")

        return incumbent, touching, disjoint, disjoint_line

    def test_periods_touching_at_a_single_instant_collide_on_activation(self, api):
        """PRD §3.2: "Activation is refused when some **other** contract is
        currently `ACTIVE`, shares this contract's `manufacturer_code`, shares
        its `member_class_scope`, prices at least one item that this contract
        also prices, and has an effective interval that intersects this
        contract's — where intersection means this contract's `effective_from`
        is at or before the other's `effective_to` **and** the other's
        `effective_from` is at or before this contract's `effective_to`."
        PRD §3.2: "Because both intervals are closed, two periods that merely
        touch at a single instant do collide."

        Design: Difficulty/resource_temporal_overlap/contract_effective_period_closed_interval_touching_endpoints_collide
        """
        _incumbent, touching, _disjoint, _line = self._build_overlap_world()
        set_clock("2026-08-31T23:59:59Z")

        response = api.transition_contract(
            touching["id"], contract_transition_payload("ACTIVE"), ADMIN
        )
        validate_error(response, ApiErrorId.ERR_CONTRACT_PERIOD_OVERLAP.value, 409)

        after = read_contract(touching["id"])
        assert after["status"] == "PENDING_ACTIVATION"
        assert after.get("activated_at") is None

    def test_period_opening_one_second_later_activates_cleanly(self, api):
        """PRD §3.2: "Activation is refused when some **other** contract is
        currently `ACTIVE`, shares this contract's `manufacturer_code`, shares
        its `member_class_scope`, prices at least one item that this contract
        also prices, and has an effective interval that intersects this
        contract's — where intersection means this contract's `effective_from`
        is at or before the other's `effective_to` **and** the other's
        `effective_from` is at or before this contract's `effective_to`."
        PRD §3.2: "`SUPERSEDED` is never requested directly; it is only ever
        reached as the side effect of a successor's activation."

        Design: Difficulty/resource_temporal_overlap/contract_effective_period_closed_interval_touching_endpoints_collide
        """
        incumbent, _touching, disjoint, disjoint_line = self._build_overlap_world()
        set_clock("2026-09-01T00:00:00Z")

        activated = transition_contract(disjoint["id"], "ACTIVE")
        assert activated["status"] == "ACTIVE"
        assert_instant_equals(
            activated["activated_at"], "2026-09-01T00:00:00", "activated_at"
        )
        assert read_contract_line(disjoint_line["id"])["activation_state"] == "ACTIVE"
        assert read_contract(incumbent["id"])["status"] == "ACTIVE", (
            "the incumbent was not named as superseded and its closed interval "
            "does not intersect, so it stays ACTIVE"
        )
