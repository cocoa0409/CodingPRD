"""Registration echoes, declared defaults, computed reads and missing parents."""

import pytest

from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_append_only_fields,
    assert_common_fields,
    assert_envelope_is_error,
    assert_no_type_prefix,
    assert_on_hand_is_ledger_sum,
    assert_sequence_numbers_monotonic,
    create_booking_payload,
    create_cleaner_payload,
    create_property_payload,
    create_supply_line_payload,
    create_turnover_payload,
    fixtures as fx,
    replenish_payload,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def clean_clock(api):
    """An empty database with the logical clock pinned to its initial instant."""
    fx.reset_clock(api)


@pytest.fixture
def bare_property(api):
    """P1 alone, with no stock, cleaner or booking attached."""
    fx.reset_clock(api)
    return fx.seed_property(api)


@pytest.fixture
def seeded_sheet_line(api, bare_property):
    """LIN-SHEET-Q holding six sets against a single SEED movement."""
    line = fx.seed_supply_line(
        api, bare_property["id"], sku="LIN-SHEET-Q", name="Queen Sheet Set",
        category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
        initial_on_hand_qty=6)
    return {"p1": bare_property, "line": line}


@pytest.fixture
def three_vacant_gap_turnovers(api, bare_property):
    """Three back-to-back stays on P1, each opened as its own vacant-gap turn."""
    p1 = bare_property
    turnovers = []
    windows = [("PG-1", "Guest One", "2026-08-05T21:00:00Z", "2026-08-08T16:00:00Z"),
               ("PG-2", "Guest Two", "2026-08-08T16:00:00Z", "2026-08-08T18:00:00Z"),
               ("PG-3", "Guest Three", "2026-08-08T18:00:00Z", "2026-08-08T20:00:00Z")]
    for ref, guest, checkin, checkout in windows:
        booking = fx.seed_booking(
            api, p1["id"], external_ref=ref, guest_name=guest,
            checkin_at=checkin, checkout_at=checkout)
        turnovers.append(fx.seed_turnover(api, booking["id"]))
    return {"p1": p1, "turnovers": turnovers}


# ─── entities ─────────────────────────────────────────────────────────────

def test_01_registering_a_unit_echoes_every_supplied_field(api, clean_clock):
    """All fifteen declared fields come back, with both counters server-minted.

    PRD §3.1: "Registering a rental unit requires an operator-facing `code`
    that must be unique across every property in the system, a display `name`
    for the unit, the `zone_code` naming the cleaning zone it sits in (an
    uppercase token between 1 and 16 characters, such as `ZONE_A`), the
    `size_tier` classifying the unit as `STUDIO`, `ONE_BR`, `TWO_BR` or
    `THREE_BR_PLUS`, and an `owner_contact_email` that becomes the notification
    target for damage findings." PRD §3.1: "At registration the unit's
    `open_issue_count` is initialised to 0 and its `last_turnover_completed_at`
    is initialised to null; the former is maintained thereafter as the count of
    that property's issue reports whose `status` is anything other than
    `RESOLVED`, and the latter is stamped with the logical clock each time one
    of the property's turnovers reaches `COMPLETED`."

    Design: Corner/entities/corner_property_creation_echoes_every_declared_field
    """
    created = validate_success(api.create_property(create_property_payload(
        bedroom_count=2, bathroom_count=2, bed_count=3,
        local_utc_offset_minutes=-300, min_clean_minutes=120, min_skill_level=2,
        owner_notify_min_cost_cents=5000, status="ACTIVE"), ADMIN), 201)

    assert_common_fields(created)
    assert created["code"] == "AUS-101" and created["name"] == "Barton Loft"
    assert created["zone_code"] == "ZONE_A" and created["size_tier"] == "TWO_BR"
    assert created["owner_contact_email"] == "owner1@example.com"
    assert (created["bedroom_count"], created["bathroom_count"],
            created["bed_count"]) == (2, 2, 3), (
        f"the three physical counts must be echoed, got "
        f"{created['bedroom_count']} / {created['bathroom_count']} / "
        f"{created['bed_count']}")
    assert created["local_utc_offset_minutes"] == -300
    assert created["min_clean_minutes"] == 120 and created["min_skill_level"] == 2
    assert created["owner_notify_min_cost_cents"] == 5000
    assert created["status"] == "ACTIVE"
    assert created["open_issue_count"] == 0, (
        f"the count is server-minted at 0, got {created['open_issue_count']}")
    assert created["last_turnover_completed_at"] is None, (
        f"nothing has completed yet, got {created['last_turnover_completed_at']}")
    assert created["version"] == 1


def test_02_a_minimal_registration_materialises_every_declared_default(
        api, clean_clock):
    """Only the five required fields are supplied and eight defaults appear.

    PRD §3.1: "The physical inventory of the unit is described by three counts,
    each defaulting to 1: `bedroom_count` and `bathroom_count` may each run from
    0 to 12, and `bed_count` may run from 0 to 24." PRD §3.1: "Two contractual
    dials may also be supplied: `min_clean_minutes`, a floor on the derived
    cleaning requirement that defaults to 60 and may run from 0 to 600, and
    `min_skill_level`, the lowest cleaner certification tier permitted to work
    the unit, defaulting to 1 within a range of 1 to 5." PRD §3.1: "The unit's
    `local_utc_offset_minutes` defaults to 0."

    Design: Corner/entities/corner_property_defaults_applied_when_optional_fields_omitted
    """
    created = validate_success(api.create_property(create_property_payload(
        code="AUS-110", name="Minimal Studio", size_tier="STUDIO",
        owner_contact_email="owner10@example.com"), ADMIN), 201)

    assert (created["bedroom_count"], created["bathroom_count"],
            created["bed_count"]) == (1, 1, 1), (
        f"each physical count defaults to 1, got {created['bedroom_count']} / "
        f"{created['bathroom_count']} / {created['bed_count']}")
    assert created["local_utc_offset_minutes"] == 0, (
        f"the offset defaults to UTC, "
        f"got {created['local_utc_offset_minutes']}")
    assert created["min_clean_minutes"] == 60, (
        f"the cleaning floor defaults to 60, got {created['min_clean_minutes']}")
    assert created["min_skill_level"] == 1, (
        f"the skill floor defaults to 1, got {created['min_skill_level']}")
    assert created["owner_notify_min_cost_cents"] == 5000, (
        f"the notification floor defaults to 5000 cents, "
        f"got {created['owner_notify_min_cost_cents']}")
    assert created["status"] == "ACTIVE", (
        f"the operational status defaults to ACTIVE, got {created['status']}")


def test_03_below_par_reads_the_reorder_point_and_never_the_par_level(
        api, bare_property):
    """Two sets against a par of six are not below par; zero units are.

    PRD §2.9: "Immediately after that projection is refreshed, `below_par` is
    recomputed as true exactly when `on_hand_qty` is less than or equal to
    `reorder_point`." PRD §3.1: "Optionally the caller supplies `unit`, the unit
    of issue, which defaults to the string `each`; `reorder_point`, defaulting to
    0 and never negative; `initial_on_hand_qty`, which seeds the line's stock;
    and `status`, which may be `ACTIVE` or `DISCONTINUED` and defaults to
    `ACTIVE`." PRD §3.1: "A newly created line with no seeded stock therefore has
    `below_par` true, which is also the field's default."

    Design: Corner/entities/corner_supply_line_computed_below_par_derives_from_on_hand_and_reorder_point
    """
    stocked = validate_success(api.create_supply_line(
        bare_property["id"], create_supply_line_payload(
            unit="SET", initial_on_hand_qty=2), COORDINATOR), 201)
    assert stocked["on_hand_qty"] == 2, (
        f"the SEED movement carries the seeded quantity, "
        f"got {stocked['on_hand_qty']}")
    assert stocked["reorder_point"] == 0, (
        f"the reorder point defaults to 0, got {stocked['reorder_point']}")
    assert stocked["below_par"] is False, (
        f"2 is not at or below 0 even though it is under a par of 6, "
        f"got {stocked['below_par']}")
    assert stocked["unit"] == "SET" and stocked["status"] == "ACTIVE"

    empty = validate_success(api.create_supply_line(
        bare_property["id"], create_supply_line_payload(
            sku="CON-COFFEE", name="Coffee Pods", category="CONSUMABLE",
            unit_cost_cents=340, par_qty=4), COORDINATOR), 201)
    assert empty["on_hand_qty"] == 0, (
        f"an omitted seed quantity books 0, got {empty['on_hand_qty']}")
    assert empty["below_par"] is True, (
        f"0 is at or below 0, got {empty['below_par']}")
    assert empty["unit"] == "each", (
        f"the unit of issue defaults to the string each, got {empty['unit']!r}")

    seed = fx.read_movements(api, {"supply_line_id": stocked["id"]})[0]
    assert (seed["reason"], seed["delta_qty"], seed["charge_cents"]) == (
        "SEED", 2, 0), (
        f"the SEED movement must carry the seeded delta at no charge, got "
        f"{seed['reason']} / {seed['delta_qty']} / {seed['charge_cents']}")
    assert seed["unit_cost_cents_at_time"] == 260, (
        f"the movement snapshots the line's cost, "
        f"got {seed['unit_cost_cents_at_time']}")


def test_04_a_replenishment_appends_a_row_rather_than_editing_the_seed(
        api, seeded_sheet_line):
    """The ledger rows carry no version at all while the line's version moves.

    PRD §3.1: "The append carries `reason` `REPLENISH` and a `delta_qty` equal to
    the supplied `qty`, refreshes `on_hand_qty` and `below_par`, and increments
    the line's `version` by 1." PRD §2.9: "Because the ledger is append-only, a
    correction is always a new compensating movement rather than an edit, and the
    invariant that `on_hand_qty` equals the summed `delta_qty` holds after every
    single request." PRD §4: "Append-only evidence row: it carries id and
    created_at but no updated_at and no version, and no endpoint may edit or
    delete it."

    Design: Corner/entities/corner_stock_movement_is_immutable_append_only_with_no_version_field
    """
    line = seeded_sheet_line["line"]
    replenished = validate_success(api.replenish_supply_line(
        line["id"], replenish_payload(4, line["version"], note="delivery 8817"),
        ADMIN))
    assert replenished["on_hand_qty"] == 10, (
        f"6 plus 4 is 10, got {replenished['on_hand_qty']}")
    assert replenished["version"] == 2, (
        f"the line itself carries a version, got {replenished['version']}")

    rows, meta = validate_paginated(api.list_stock_movements(
        ADMIN, {"supply_line_id": line["id"]}))
    assert meta["total_count"] == 2, (
        f"the append leaves two rows, got {meta['total_count']}")
    seed, delivery = rows
    assert (seed["sequence_no"], seed["delta_qty"]) == (1, 6), (
        f"the SEED row must be untouched by the delivery, got "
        f"{seed['sequence_no']} / {seed['delta_qty']}")
    assert (delivery["sequence_no"], delivery["delta_qty"],
            delivery["reason"]) == (2, 4, "REPLENISH"), (
        f"the delivery row must be second, got {delivery['sequence_no']} / "
        f"{delivery['delta_qty']} / {delivery['reason']}")
    assert delivery["note"] == "delivery 8817", (
        f"the supplied note rides onto the movement, got {delivery['note']!r}")
    for row in rows:
        assert_append_only_fields(row)
    assert_sequence_numbers_monotonic(rows)
    assert_on_hand_is_ledger_sum(replenished, rows)


def test_05_a_freshly_onboarded_cleaner_reads_back_with_zeroed_counters(
        api, clean_clock):
    """Stored inputs survive the round trip while all four counters read 0.

    PRD §3.1: "The optional `initial_quality_score` seeds the cleaner's rolling
    `quality_score`, which is otherwise 80.00; the score is a two-decimal figure
    bounded between 0 and 100, and after onboarding it is **only ever**
    recomputed by quality-audit finalization — no other operation writes it."
    PRD §3.1: "Onboarding also initialises four counters to zero:
    `pending_payout_cents`, `completed_turnover_count` (the number of this
    cleaner's assignments sitting in `COMPLETED`), `decline_count` (the number
    sitting in `DECLINED`), and `strike_count`."

    Design: Corner/entities/corner_cleaner_retrieval_returns_stored_inputs_and_zeroed_derived_counters
    """
    created = validate_success(api.create_cleaner(create_cleaner_payload(
        secondary_zone_codes=["ZONE_B"], accepts_cross_zone=True,
        max_daily_turnovers=3, initial_quality_score=92.00), ADMIN), 201)

    read = validate_success(api.get_cleaner(created["id"], COORDINATOR))
    assert read["name"] == "Cleaner C" and read["home_zone_code"] == "ZONE_A"
    assert read["secondary_zone_codes"] == ["ZONE_B"], (
        f"the served zone list must round-trip, "
        f"got {read['secondary_zone_codes']}")
    assert read["accepts_cross_zone"] is True
    assert read["skill_level"] == 4 and read["max_daily_turnovers"] == 3
    assert float(read["quality_score"]) == pytest.approx(92.00, abs=0.005), (
        f"the seeded score must displace the 80.00 default, "
        f"got {read['quality_score']}")
    assert read["status"] == "ACTIVE"
    assert (read["pending_payout_cents"], read["completed_turnover_count"],
            read["decline_count"], read["strike_count"]) == (0, 0, 0, 0), (
        f"all four counters start at zero, got {read['pending_payout_cents']} / "
        f"{read['completed_turnover_count']} / {read['decline_count']} / "
        f"{read['strike_count']}")


def test_06_the_turnover_list_pages_in_window_order_with_total_count(
        api, three_vacant_gap_turnovers):
    """Two pages of a three-row result set, then the unparameterised default.

    PRD §2.3: "List responses report `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` counts every row matching the
    applied filters before the page window is taken and `has_more` is true
    exactly when rows remain beyond the current page." PRD §2.3: "Several
    collections carry a domain-natural ordering that overrides the default, and
    in each case the tie-break is stated explicitly: a property's stock lines
    are ordered by `sku` ascending; the stock ledger is ordered by `created_at`
    ascending and then by `sequence_no` ascending; reservations are ordered by
    `checkin_at` ascending and then by `created_at` ascending; turnovers are
    ordered by `window_start_at` ascending and then by `created_at` ascending;
    a turnover's checklist tasks are ordered by `sequence_no` ascending; offers
    are ordered by `created_at` ascending and then by `sequence_no` ascending."
    PRD §2.3: "`limit` controls page size: it defaults to 10, may not be
    smaller than 1, and may not be larger than 100."

    Design: Corner/entities/corner_turnover_listing_paginates_with_total_count_and_has_more
    """
    world = three_vacant_gap_turnovers
    t1, t2, t3 = world["turnovers"]
    assert t1["turn_type"] == "VACANT_GAP", (
        f"a turn with no arriving stay is a vacant gap, got {t1['turn_type']}")
    assert t1["window_minutes"] == 2880, (
        f"48 hours of latitude is 2880 minutes, got {t1['window_minutes']}")

    rows, meta = validate_paginated(api.list_turnovers(
        COORDINATOR, {"property_id": world["p1"]["id"], "limit": 2, "offset": 0}))
    assert (meta["limit"], meta["offset"]) == (2, 0)
    assert meta["total_count"] == 3, (
        f"the count precedes the page window, got {meta['total_count']}")
    assert meta["has_more"] is True, (
        f"a third row remains beyond this page, got {meta['has_more']}")
    assert [row["id"] for row in rows] == [t1["id"], t2["id"]], (
        "the page must be ordered by window_start_at ascending")

    rows, meta = validate_paginated(api.list_turnovers(
        COORDINATOR, {"property_id": world["p1"]["id"], "limit": 2, "offset": 2}))
    assert meta["total_count"] == 3 and meta["has_more"] is False, (
        f"the last page exhausts the set, got {meta['total_count']} / "
        f"{meta['has_more']}")
    assert [row["id"] for row in rows] == [t3["id"]]

    rows, meta = validate_paginated(api.list_turnovers(
        COORDINATOR, {"property_id": world["p1"]["id"]}))
    assert (meta["limit"], meta["offset"]) == (10, 0), (
        f"the declared defaults must apply, got {meta['limit']} / "
        f"{meta['offset']}")
    assert len(rows) == 3 and meta["has_more"] is False


def test_07_a_well_formed_uuid_addressing_no_stay_is_a_typed_not_found(
        api, clean_clock):
    """The answer is the booking-specific 404, not a null-bodied success.

    PRD §2.5: "**Path existence, left to right.** On every endpoint carrying path
    parameters, each templated resource must exist, and the segments are resolved
    strictly left to right so that the outermost missing resource is the one
    reported." PRD §2.2: "The `error_id` is a unique, machine-readable string
    that identifies the specific error." PRD §2.2: "The `api_request_id` is a
    server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/corner_booking_not_found_for_unknown_uuid
    """
    response = api.get_booking(MISSING_UUID, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_BOOKING_NOT_FOUND.value, 404)
    assert_envelope_is_error(response)


def test_08_omitting_a_required_datetime_is_a_request_shape_failure(
        api, bare_property):
    """The absent checkout instant is caught before any interval reasoning.

    PRD §2.5: "**Request shape.** On every endpoint: every required input field
    must be present, every enum-typed value must be one of the declared members,
    every integer must sit inside its declared bounds, every datetime must parse
    as ISO 8601 UTC, quantities and scores must sit inside their declared ranges,
    and `restock_entries` must be well formed. Failure yields
    `ERR_INVALID_REQUEST` (400)." PRD §3.2: "Reservations arrive from channel
    calendars and are imported by a `Coordinator`, who supplies the
    `property_id` of the unit, the channel's `external_ref` reservation reference
    (unique within that unit), the `guest_name` of record, and the contracted
    `checkin_at` and `checkout_at` instants, where the departure must be strictly
    later than the arrival."

    Design: Corner/entities/corner_booking_required_field_missing_is_rejected
    """
    payload = create_booking_payload(bare_property["id"])
    del payload["checkout_at"]
    response = api.create_booking(payload, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api.list_bookings(
        COORDINATOR, {"property_id": bare_property["id"]}))
    assert meta["total_count"] == 0, (
        f"the refused import must persist nothing, got {meta['total_count']}")


def test_09_an_unknown_size_tier_is_refused_rather_than_defaulted(
        api, clean_clock):
    """A tier outside the four declared members cannot yield base minutes.

    PRD §3.1: "Registering a rental unit requires an operator-facing `code` that
    must be unique across every property in the system, a display `name` for the
    unit, the `zone_code` naming the cleaning zone it sits in (an uppercase token
    between 1 and 16 characters, such as `ZONE_A`), the `size_tier` classifying
    the unit as `STUDIO`, `ONE_BR`, `TWO_BR` or `THREE_BR_PLUS`, and an
    `owner_contact_email` that becomes the notification target for damage
    findings." PRD §2.5: "On every endpoint: every required input field must be
    present, every enum-typed value must be one of the declared members, every
    integer must sit inside its declared bounds, every datetime must parse as ISO
    8601 UTC, quantities and scores must sit inside their declared ranges, and
    `restock_entries` must be well formed." PRD §3.3: "Start from the size-tier
    base: 90 minutes for a `STUDIO`, 120 for a `ONE_BR`, 150 for a `TWO_BR` and
    200 for a `THREE_BR_PLUS`."

    Design: Corner/entities/corner_property_rejects_unknown_size_tier_enum_value
    """
    response = api.create_property(create_property_payload(
        code="AUS-199", name="Bad Tier", size_tier="FOUR_BR",
        owner_contact_email="owner99@example.com"), ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    good = validate_success(api.create_property(create_property_payload(
        code="AUS-199", name="Good Tier", size_tier="ONE_BR",
        owner_contact_email="owner99@example.com"), ADMIN), 201)
    assert good["size_tier"] == "ONE_BR", (
        f"the refused create must not have consumed the code, "
        f"got {good['size_tier']}")


def test_10_every_window_field_on_a_new_turn_is_server_derived(
        api, bare_property):
    """Only two booking references are supplied and twelve fields come back.

    PRD §3.3: "The turnover copies its `property_id` from the departing stay,
    lands with `status` `PENDING_ASSIGNMENT` and `version` 1, and refuses to be
    created at all if the property is not `ACTIVE` (`ERR_PROPERTY_NOT_ACTIVE`),
    if the departing stay already carries a turnover that is not `VOID`
    (`ERR_TURNOVER_ALREADY_EXISTS`), if the two nominated stays belong to
    different units (`ERR_PROPERTY_MISMATCH`), or if the arriving stay's
    `checkin_at` precedes the departing stay's `checkout_at`
    (`ERR_INVALID_TIME_INTERVAL`)." PRD §2.4: "Every persisted resource carries
    a server-minted `id` in UUID form. Identifiers never carry a type prefix —
    an `id` is the bare UUID string and nothing else." PRD §2.4: "Every
    resource also carries `created_at`, an ISO 8601 UTC timestamp with three
    fractional digits recording when the row was minted."

    Design: Corner/entities/corner_system_and_computed_fields_are_server_minted_on_turnover_create
    """
    b_out, b_in = fx.seed_stay_pair(api, bare_property["id"])
    created = validate_success(api.create_turnover(
        create_turnover_payload(b_out["id"], b_in["id"]), COORDINATOR), 201)

    assert_common_fields(created)
    assert_no_type_prefix(created["id"])
    assert created["property_id"] == bare_property["id"], (
        f"the unit is copied from the departing stay, "
        f"got {created['property_id']}")
    assert same_instant(created["window_start_at"], "2026-08-08T16:00:00Z")
    assert same_instant(created["window_end_at"], "2026-08-08T20:30:00Z")
    assert created["window_minutes"] == 270 and created["required_minutes"] == 198
    assert created["slack_minutes"] == 72 and created["turn_type"] == "SAME_DAY"
    assert created["is_tight"] is False
    assert created["status"] == "PENDING_ASSIGNMENT" and created["version"] == 1
    assert created["pre_hold_status"] is None, (
        f"no hold has been taken, got {created['pre_hold_status']}")
    assert created["checklist_task_count"] == 0, (
        f"the checklist is only generated at start, "
        f"got {created['checklist_task_count']}")


def test_11_a_stock_line_cannot_be_created_under_a_missing_unit(api, clean_clock):
    """The nested path is the only binding, so a missing parent is a 404.

    PRD §2.5: "The applicable code is `ERR_PROPERTY_NOT_FOUND`,
    `ERR_CLEANER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_TURNOVER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CHECKLIST_TASK_NOT_FOUND`,
    `ERR_SUPPLY_LINE_NOT_FOUND`, `ERR_ISSUE_REPORT_NOT_FOUND`,
    `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_QUALITY_AUDIT_NOT_FOUND`,
    `ERR_STOCK_MOVEMENT_NOT_FOUND` or `ERR_PAY_LINE_NOT_FOUND`, each at HTTP
    404." PRD §3.1: "Par-level stock is configured per unit, one line per stock
    keeping unit."

    Design: Corner/entities/corner_supply_line_parent_must_exist_on_nested_create
    """
    response = api.create_supply_line(
        MISSING_UUID, create_supply_line_payload(), ADMIN)
    validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value, 404)


def test_12_two_stays_on_different_units_cannot_bracket_one_turn(
        api, bare_property):
    """The mismatch is caught before any window arithmetic persists a row.

    PRD §2.5: "**Single-property cross-references.** On `POST /turnovers` the
    incoming booking's property must be the same property as the outgoing
    booking's, and on `POST /checklist-tasks/{id}/submit` every restock entry's
    supply line must belong to the turnover's property. Failure yields
    `ERR_PROPERTY_MISMATCH` (422)." PRD §3.3: "The turnover copies its
    `property_id` from the departing stay, lands with `status`
    `PENDING_ASSIGNMENT` and `version` 1, and refuses to be created at all if
    the property is not `ACTIVE` (`ERR_PROPERTY_NOT_ACTIVE`), if the departing
    stay already carries a turnover that is not `VOID`
    (`ERR_TURNOVER_ALREADY_EXISTS`), if the two nominated stays belong to
    different units (`ERR_PROPERTY_MISMATCH`), or if the arriving stay's
    `checkin_at` precedes the departing stay's `checkout_at`
    (`ERR_INVALID_TIME_INTERVAL`)."

    Design: Corner/entities/corner_flat_topology_cross_property_booking_pair_is_rejected
    """
    p2 = fx.seed_property(
        api, code="AUS-102", name="Zilker Flat", size_tier="ONE_BR",
        owner_contact_email="owner2@example.com")
    b_out = fx.seed_booking(
        api, bare_property["id"], external_ref="OUT-1", guest_name="Guest Out",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    b_other = fx.seed_booking(
        api, p2["id"], external_ref="IN-X", guest_name="Guest Other",
        checkin_at="2026-08-08T21:00:00Z", checkout_at="2026-08-11T16:00:00Z")

    response = api.create_turnover(
        create_turnover_payload(b_out["id"], b_other["id"]), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_PROPERTY_MISMATCH.value, 422)

    _, meta = validate_paginated(api.list_turnovers(
        COORDINATOR, {"outgoing_booking_id": b_out["id"]}))
    assert meta["total_count"] == 0, (
        f"no partially derived turnover may survive, got {meta['total_count']}")
