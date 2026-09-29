"""Listing, single-row lookup and the schema / existence rejections.

These tests exercise the discovery side of the entity surface — the paginated
section listing with its filtered total count and has-more flag, and the four
filtered forms that reach a damage claim from each of the parties it names — plus
the rejections a malformed or dangling create earns: an unknown permit id on the
path, a missing required travel figure, three shapes of schema violation, and a
floor hung off an order that does not exist.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_damage_claim,
    create_order_payload,
    create_section_payload,
    make_plant_dispatcher_headers,
    open_damage_claim,
    open_order,
    read_section,
    record_section,
    register_hauler,
    register_plant,
    register_set_crew,
    set_logical_clock,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["network_admin_headers"]
PERMIT_DESK = TEST_USERS["permit_desk_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]

# A syntactically valid UUID that no row in an empty database carries.
UNUSED_UUID = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Walking the section listing a page at a time
# ---------------------------------------------------------------------------


def _two_orders_with_three_and_one_floor():
    """One plant, order A with three recorded floors and order B with one."""
    set_logical_clock()
    plant = register_plant()
    order_a = open_order(plant["id"], section_count=3, home_model="Titan 3266")
    order_b = open_order(
        plant["id"], section_count=1, dealer_name="Mesa Homes", home_model="Titan 1660"
    )
    floors_a = [
        record_section(
            order_a["id"], plant["id"], section_index=index, declared_length_in=768
        )
        for index in (1, 2, 3)
    ]
    floor_b = record_section(order_b["id"], plant["id"], section_index=1)
    return plant, order_a, order_b, floors_a, floor_b


def test_sections_listing_reports_filtered_total_count_and_has_more(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` is the number of rows matching
    the filters before the window is applied and `has_more` reports whether any
    matching row lies beyond the returned window."
    PRD §2.3: "Collections are always returned sorted by `created_at` in ascending
    order, so a stable window can be walked by advancing `offset` alone."

    Design: Corner/entities/sections_listing_paginates_with_total_count_and_has_more
    """
    _, order_a, _, floors_a, _ = _two_orders_with_three_and_one_floor()

    first_page, first_meta = validate_paginated(
        api.list_sections(ADMIN, params={"order_id": order_a["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, (
        f"a limit of 2 returns two rows, got {len(first_page)}"
    )
    assert first_meta["total_count"] == 3, (
        "total_count counts the three matching floors before the window is "
        f"applied, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "one matching floor lies beyond the first page, so has_more is true, got "
        f"{first_meta['has_more']}"
    )
    assert first_meta["limit"] == 2, f"expected limit 2, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"expected offset 0, got {first_meta['offset']}"

    second_page, second_meta = validate_paginated(
        api.list_sections(ADMIN, params={"order_id": order_a["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, (
        f"the third floor is alone on the second page, got {len(second_page)}"
    )
    assert second_meta["total_count"] == 3, (
        "total_count is unaffected by the page size, expected 3, got "
        f"{second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "no matching floor lies beyond the second page, so has_more is false, got "
        f"{second_meta['has_more']}"
    )
    assert second_meta["offset"] == 2, f"expected offset 2, got {second_meta['offset']}"

    walked = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert sorted(walked) == sorted(floor["id"] for floor in floors_a), (
        "advancing offset alone must walk exactly the three floors of the order, "
        f"got {walked}"
    )


def test_sections_listing_order_id_filter_excludes_another_orders_floor(api):
    """PRD §2.3: "home sections accept `order_id`, `mates_to_section_id` and
    `transit_status` — the second of those being the self-referential marriage
    pairing, which is how a caller finds the floor mated to a given floor"
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` is the number of rows matching
    the filters before the window is applied and `has_more` reports whether any
    matching row lies beyond the returned window."

    Design: Corner/entities/sections_listing_paginates_with_total_count_and_has_more
    """
    _, order_a, order_b, _, floor_b = _two_orders_with_three_and_one_floor()

    first_page, _ = validate_paginated(
        api.list_sections(ADMIN, params={"order_id": order_a["id"], "limit": 2, "offset": 0})
    )
    second_page, _ = validate_paginated(
        api.list_sections(ADMIN, params={"order_id": order_a["id"], "limit": 2, "offset": 2})
    )
    for row in first_page + second_page:
        assert row["order_id"] == order_a["id"], (
            "the order_id filter is applied before pagination, so a second order's "
            f"floor must never appear, got a row on order {row['order_id']}"
        )
        assert row["id"] != floor_b["id"], (
            f"the other order's floor {floor_b['id']} leaked into the window"
        )

    other_page, other_meta = validate_paginated(
        api.list_sections(ADMIN, params={"order_id": order_b["id"]})
    )
    assert other_meta["total_count"] == 1, (
        f"order B has exactly one recorded floor, got {other_meta['total_count']}"
    )
    assert [row["id"] for row in other_page] == [floor_b["id"]], (
        f"expected only {floor_b['id']} on order B, got {[r['id'] for r in other_page]}"
    )


# ---------------------------------------------------------------------------
# An unknown id on the path
# ---------------------------------------------------------------------------


def test_permit_read_on_an_unused_uuid_returns_permit_not_found(api):
    """PRD §2.10: "**Priority 4** — every `{id}` path parameter resolves to an
    existing row of the addressed entity, on every endpoint that has a path
    parameter. Violation: the 404 not-found code for that entity —
    `ERR_PLANT_NOT_FOUND`, `ERR_HAULER_NOT_FOUND`, `ERR_ESCORT_CREW_NOT_FOUND`,
    `ERR_SET_CREW_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ROUTE_LEG_NOT_FOUND`,
    `ERR_ESCORT_ASSIGNMENT_NOT_FOUND`, `ERR_SET_JOB_NOT_FOUND`,
    `ERR_MARRIAGE_JOINT_NOT_FOUND`, `ERR_ANCHOR_CERT_NOT_FOUND` or
    `ERR_CLAIM_NOT_FOUND`."

    Design: Corner/entities/permit_get_unknown_uuid_returns_not_found
    """
    resp = api.get_permit(UNUSED_UUID, PERMIT_DESK)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_FOUND)
    assert resp.status_code == 404, (
        f"an unresolvable path id is a 404, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Missing and malformed fields on a floor create
# ---------------------------------------------------------------------------


def _plant_and_one_order():
    set_logical_clock()
    plant = register_plant()
    order = open_order(plant["id"], section_count=1)
    return plant, order


def test_section_create_without_declared_width_is_rejected(api):
    """PRD §3.2: "Each floor of the home is recorded by the plant's dispatcher as
    a home section, with the `order_id` it belongs to, a 1-based `section_index`
    between 1 and 4 inclusive, and four dealer-declared travel figures:
    `declared_width_in` between 120 and 240 inches, `declared_height_in` between
    120 and 200 inches, `declared_length_in`, and `declared_weight_lb`."
    PRD §2.10: "**Priority 3** — the request body parses and satisfies the
    endpoint's field schema: required fields present, types correct, enumerated
    values within range, numbers within their stated bounds, datetimes ISO 8601
    UTC. Applies to every endpoint that has a request body. Violation:
    `ERR_INVALID_REQUEST` (400). This is a pure shape check performed with no
    database reads."

    Design: Corner/entities/section_create_missing_declared_width_rejected
    """
    plant, order = _plant_and_one_order()

    payload = create_section_payload(order["id"], section_index=1)
    del payload["declared_width_in"]

    resp = api.create_section(payload, make_plant_dispatcher_headers(plant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api.list_sections(ADMIN, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the rejected floor must not have been recorded, got {meta['total_count']} rows"
    )


def test_section_create_missing_width_outranks_the_unknown_order_reference(api):
    """PRD §2.10: "Requests are validated in strictly ascending priority order and
    the **first** violated rule determines the response. Later violations are never
    reported, even when a single request breaks several rules at once."
    PRD §2.10: "**Priority 3** — the request body parses and satisfies the
    endpoint's field schema: required fields present, types correct, enumerated
    values within range, numbers within their stated bounds, datetimes ISO 8601
    UTC. Applies to every endpoint that has a request body. Violation:
    `ERR_INVALID_REQUEST` (400). This is a pure shape check performed with no
    database reads."
    PRD §2.10: "**Priority 5** — every reference field in the request body
    resolves to an existing row of the referenced entity, on every creation
    endpoint. Violation: the same family of 404 codes."

    Design: Corner/entities/section_create_missing_declared_width_rejected
    """
    plant, _ = _plant_and_one_order()

    payload = create_section_payload(UNUSED_UUID, section_index=1)
    del payload["declared_width_in"]

    resp = api.create_section(payload, make_plant_dispatcher_headers(plant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Enumerated values and stated numeric bounds
# ---------------------------------------------------------------------------


def test_order_creation_rejects_a_wind_zone_outside_the_hud_enumeration(api):
    """PRD §3.2: "Opening one takes the building plant's identifier as `plant_id`,
    the retail `dealer_name` that sold the home, the Champion `home_model`
    designation, the dealer-declared `section_count` (between 1 and 4 inclusive),
    the two-uppercase-letter `destination_state` of the delivery site, and the HUD
    `wind_zone` of that destination, which is one of `I`, `II` or `III`."
    PRD §2.10: "**Priority 3** — the request body parses and satisfies the
    endpoint's field schema: required fields present, types correct, enumerated
    values within range, numbers within their stated bounds, datetimes ISO 8601
    UTC. Applies to every endpoint that has a request body. Violation:
    `ERR_INVALID_REQUEST` (400). This is a pure shape check performed with no
    database reads."

    Design: Corner/entities/order_and_section_type_constraints_rejected
    """
    set_logical_clock()
    plant = register_plant()

    resp = api.create_order(
        create_order_payload(plant["id"], wind_zone="IV"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_orders(ADMIN, params={"plant_id": plant["id"]}))
    assert meta["total_count"] == 0, (
        f"a schema-rejected order must not be stored, got {meta['total_count']} rows"
    )


def test_order_creation_rejects_a_section_count_below_the_stated_minimum(api):
    """PRD §3.2: "Opening one takes the building plant's identifier as `plant_id`,
    the retail `dealer_name` that sold the home, the Champion `home_model`
    designation, the dealer-declared `section_count` (between 1 and 4 inclusive),
    the two-uppercase-letter `destination_state` of the delivery site, and the HUD
    `wind_zone` of that destination, which is one of `I`, `II` or `III`."
    PRD §2.10: "**Priority 3** — the request body parses and satisfies the
    endpoint's field schema: required fields present, types correct, enumerated
    values within range, numbers within their stated bounds, datetimes ISO 8601
    UTC. Applies to every endpoint that has a request body. Violation:
    `ERR_INVALID_REQUEST` (400). This is a pure shape check performed with no
    database reads."

    Design: Corner/entities/order_and_section_type_constraints_rejected
    """
    set_logical_clock()
    plant = register_plant()

    resp = api.create_order(create_order_payload(plant["id"], section_count=0), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_orders(ADMIN, params={"plant_id": plant["id"]}))
    assert meta["total_count"] == 0, (
        f"a schema-rejected order must not be stored, got {meta['total_count']} rows"
    )


def test_section_creation_rejects_a_negative_declared_width(api):
    """PRD §3.2: "Each floor of the home is recorded by the plant's dispatcher as
    a home section, with the `order_id` it belongs to, a 1-based `section_index`
    between 1 and 4 inclusive, and four dealer-declared travel figures:
    `declared_width_in` between 120 and 240 inches, `declared_height_in` between
    120 and 200 inches, `declared_length_in`, and `declared_weight_lb`."
    PRD §2.10: "**Priority 3** — the request body parses and satisfies the
    endpoint's field schema: required fields present, types correct, enumerated
    values within range, numbers within their stated bounds, datetimes ISO 8601
    UTC. Applies to every endpoint that has a request body. Violation:
    `ERR_INVALID_REQUEST` (400). This is a pure shape check performed with no
    database reads."

    Design: Corner/entities/order_and_section_type_constraints_rejected
    """
    plant, order = _plant_and_one_order()

    resp = api.create_section(
        create_section_payload(order["id"], section_index=1, declared_width_in=-1),
        make_plant_dispatcher_headers(plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api.list_sections(ADMIN, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a schema-rejected floor must not be stored, got {meta['total_count']} rows"
    )
    assert order["section_count"] == 1, (
        "the parent order keeps its declared section_count regardless of the rejection"
    )


# ---------------------------------------------------------------------------
# A body reference that resolves to nothing
# ---------------------------------------------------------------------------


def test_section_create_under_an_unknown_order_reports_order_not_found(api):
    """PRD §2.10: "**Priority 5** — every reference field in the request body
    resolves to an existing row of the referenced entity, on every creation
    endpoint. Violation: the same family of 404 codes. Body references are
    resolved left to right in the order the fields are declared for that endpoint,
    so the leftmost broken reference is the one reported: a damage claim resolves
    `order_id`, then `section_id`, then `hauler_id`, then `set_crew_id`; a set-job
    booking resolves `order_id` then `set_crew_id`; a corridor leg resolves
    `permit_id` then `hauler_id`; an escort reservation resolves `route_leg_id`
    then `escort_crew_id`; a permit request resolves `section_id`; a floor resolves
    `order_id` then `mates_to_section_id`; a site resolves `order_id`; a marriage
    joint resolves `set_job_id`; an anchoring package resolves `set_job_id`; and an
    installation order resolves `plant_id`."

    Design: Corner/entities/section_create_under_unknown_order_returns_order_not_found
    """
    set_logical_clock()
    plant = register_plant()

    resp = api.create_section(
        create_section_payload(UNUSED_UUID, section_index=1),
        make_plant_dispatcher_headers(plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)
    assert resp.status_code == 404, (
        f"a broken body reference is a 404, got {resp.status_code}"
    )

    _, meta = validate_paginated(
        api.list_sections(ADMIN, params={"order_id": UNUSED_UUID})
    )
    assert meta["total_count"] == 0, (
        f"no floor may be recorded under a non-existent order, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# The four-parent junction row
# ---------------------------------------------------------------------------


def _claim_naming_four_parties():
    """A claim that names an order, one of its floors, a hauler and a set crew."""
    set_logical_clock()
    plant = register_plant()
    hauler_a = register_hauler(dot_number="DOT-771004")
    hauler_b = register_hauler(dot_number="DOT-771005")
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=1, destination_state="AZ")
    section = record_section(order["id"], plant["id"], section_index=1)

    claim = open_damage_claim(
        order["id"],
        section["id"],
        hauler_a["id"],
        set_crew["id"],
        headers=make_plant_dispatcher_headers(plant["id"]),
        discovered_stage="PLANT_QC",
        claimed_amount_cents=100000,
        blocks_set=False,
        plant_evidence_points=1,
        hauler_evidence_points=0,
        installer_evidence_points=0,
    )
    return {
        "plant": plant,
        "hauler_a": hauler_a,
        "hauler_b": hauler_b,
        "set_crew": set_crew,
        "order": order,
        "section": section,
        "claim": claim,
    }


def test_damage_claim_is_reachable_through_each_of_its_four_reference_filters(api):
    """PRD §2.3: "Each child collection accepts every one of its own reference
    fields as an optional filter, alongside a status filter of the appropriate
    flavour: plants accept `status` and `state_code`; haulers, escort crews and set
    crews accept `status`; installation orders accept `plant_id`, `posture` and
    `destination_state`; home sections accept `order_id`, `mates_to_section_id` and
    `transit_status` — the second of those being the self-referential marriage
    pairing, which is how a caller finds the floor mated to a given floor; sites
    accept `order_id` and `readiness_status`; transport permits accept
    `section_id`, `state_code` and `status`; route legs accept `permit_id`,
    `hauler_id` and `status`; escort assignments accept `route_leg_id`,
    `escort_crew_id` and `status`; set jobs accept `order_id`, `set_crew_id`,
    `progress_status` and `scope_status`; marriage joints accept `set_job_id`,
    which is the only discovery channel for joints because they are never embedded
    inside a set job's representation; and damage claims accept `order_id`,
    `section_id`, `hauler_id`, `set_crew_id` and `status`."
    PRD §2.11: "A damage claim is the extreme case: it names an order, a floor of
    that order, a hauler and a set crew simultaneously, and the plant it charges is
    reached indirectly through the order's `plant_id`."

    Design: Corner/entities/damage_claim_graph_junction_reachable_from_all_four_parents
    """
    state = _claim_naming_four_parties()
    claim_id = state["claim"]["id"]
    assert_damage_claim(state["claim"])

    for field, parent_id in (
        ("order_id", state["order"]["id"]),
        ("section_id", state["section"]["id"]),
        ("hauler_id", state["hauler_a"]["id"]),
        ("set_crew_id", state["set_crew"]["id"]),
    ):
        rows, meta = validate_paginated(
            api.list_damage_claims(ADJUSTER, params={field: parent_id})
        )
        assert meta["total_count"] == 1, (
            f"the claim must be reachable through {field}, got {meta['total_count']} rows"
        )
        assert [row["id"] for row in rows] == [claim_id], (
            f"the {field} filter must return the junction row, got {[r['id'] for r in rows]}"
        )
        assert rows[0][field] == parent_id, (
            f"the returned claim must carry {field} {parent_id}, got {rows[0][field]}"
        )


def test_damage_claim_filters_exclude_an_unnamed_hauler_and_leave_the_floor_at_plant(api):
    """PRD §2.3: "Filters combine conjunctively, and an unrecognised filter value
    that violates its enumeration is a schema failure rather than an empty result."
    PRD §3.9: "A new claim opens at `status` `SUBMITTED` with `dispute_round` at 0,
    `allocation_basis` and `approved_amount_cents` null, and `plant_charge_cents`,
    `hauler_charge_cents` and `installer_charge_cents` all at 0."
    PRD §3.9: "When `blocks_set` is true the named floor is held: it moves
    `IN_TRANSIT → DAMAGED_HOLD` or `DELIVERED → DAMAGED_HOLD`, both the floor's and
    the order's `version` rise, and the order's posture is re-derived and lands on
    `TRANSPORT_BLOCKED`, freezing downstream set work."

    Design: Corner/entities/damage_claim_graph_junction_reachable_from_all_four_parents
    """
    state = _claim_naming_four_parties()
    claim = state["claim"]

    assert claim["status"] == "SUBMITTED", (
        f"a new claim opens at SUBMITTED, got {claim['status']}"
    )
    assert claim["dispute_round"] == 0, (
        f"a new claim opens with dispute_round 0, got {claim['dispute_round']}"
    )
    assert claim["blocks_set"] is False, (
        f"blocks_set was declared false, got {claim['blocks_set']}"
    )

    _, meta = validate_paginated(
        api.list_damage_claims(ADJUSTER, params={"hauler_id": state["hauler_b"]["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a hauler the claim never names must see no claims, got {meta['total_count']}"
    )

    floor = read_section(state["section"]["id"])
    assert floor["transit_status"] == "AT_PLANT", (
        "a non-blocking claim leaves the floor's transit status untouched, got "
        f"{floor['transit_status']}"
    )
