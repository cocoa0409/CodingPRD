"""Record versioning, the two stale-read refusals and read-your-writes visibility.

This module exercises the plant's change counter and the guarantees built on top of
it: every write advances a record's ``version`` while no read ever does; the two
optimistic-concurrency refusals the PRD declares (``ERR_STALE_WIRE_LOT_VERSION`` on
lot opening and ``ERR_STALE_PRODUCTION_LOT_VERSION`` on certificate drafting) are
decided above the window, hold and state rules of the evaluation ladder; a list
query re-evaluates its filters against live status rather than a cached snapshot;
and a write's own response body already carries every derived field and every
cascaded effect it caused, so no second write is ever needed to observe them.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot_piece_ledger,
    assert_wire_mass_ledger,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# The compact unplated reference route: a 500.000 kg coil drawn 8.00 -> 6.80 mm on a
# 120000-piece die set, feeding a part whose blank weighs 20.0 g with a 5 % scrap
# allowance. Every arithmetic literal below is derived from exactly these values, so
# they are always passed explicitly rather than left to a factory default.
CLOCK = "2026-09-01T06:00:00Z"

SPEC_OVERRIDES: Dict[str, Any] = {
    "blank_mass_g": 20.0,
    "scrap_allowance_pct": 0.05,
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
}
WIRE_OVERRIDES: Dict[str, Any] = {
    "inlet_diameter_mm": 8.00,
    "outlet_diameter_mm": 6.80,
    "lubricant_coating": "PHOSPHATE",
    "coating_weight_gsm": 4.5,
    "gross_mass_kg": 500.0,
}
TOOL_OVERRIDES: Dict[str, Any] = {"station_count": 4, "rated_life_pieces": 120000}


def _reference_env(**extra: Any) -> Dict[str, Any]:
    """Part spec, VERIFIED heat, RELEASED 500 kg coil, MOUNTED die set and furnace."""
    return fixtures.setup_master_data(
        clock=CLOCK,
        spec_overrides=dict(SPEC_OVERRIDES),
        wire_overrides=dict(WIRE_OVERRIDES),
        tool_overrides=dict(TOOL_OVERRIDES),
        **extra,
    )


def _lot_payload(env: Dict[str, Any], expected_wire_lot_version: int, **overrides: Any):
    return factories.create_production_lot_payload(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        expected_wire_lot_version,
        press_code=env["press_code"],
        **overrides,
    )


# ---------------------------------------------------------------------------
# The two declared stale-read refusals and where they sit in the ladder
# ---------------------------------------------------------------------------
def test_stale_wire_lot_version_is_refused_before_the_press_window_conflict(
    api, engineer_headers
):
    """A second lot echoing the version it read before the first reservation is told
    its view is stale even though its press window also overlaps.

    PRD: "If that value does not equal the wire lot's current `version`, the request is rejected with `ERR_STALE_WIRE_LOT_VERSION` (HTTP 412)."

    PRD: "**Stale-read protection**, per §2.7: `ERR_STALE_WIRE_LOT_VERSION` on lot opening and `ERR_STALE_PRODUCTION_LOT_VERSION` on certificate drafting, both HTTP 412."

    PRD: "Note that this tier sits *above* the hold, state and window rules — a client presenting a stale parent version is told so even when the operation would also have failed a later check."

    PRD: "The requested press window must not overlap the window of any other non-aborted production lot already booked on the same die set; windows are half-open, running from the inclusive start to the exclusive end, so a window beginning at the exact instant another one ends is accepted, while any genuine overlap is refused with `ERR_TOOL_WINDOW_CONFLICT`."

    Design: Corner/complexity_layers/stale_wire_lot_version_is_refused_before_the_press_window_check
    """
    env = _reference_env()
    wire_id = env["wire"]["id"]

    # The version both clients read: 1 at creation, 2 after the inspection release.
    stale_version = env["wire"]["version"]
    assert stale_version == 2, (
        f"Expected the released coil at version 2 (create then release), "
        f"got {stale_version}"
    )

    first = validate_success(
        api.create_production_lot(
            _lot_payload(
                env,
                stale_version,
                lot_code="L-OCC1",
                press_window_start_at="2026-09-01T06:00:00Z",
                press_window_end_at="2026-09-01T08:00:00Z",
                planned_pieces=1000,
            ),
            engineer_headers,
        ),
        201,
    )
    # 1000 pieces * 20.0 g * 1.05, converted to kilograms.
    assert first["wire_reserved_kg"] == pytest.approx(21.000, abs=0.001), (
        f"Expected a reservation of 21.000 kg, got {first['wire_reserved_kg']}"
    )

    after_first = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert after_first["version"] == 3, (
        f"Expected the coil at version 3 once a lot reserved from it, "
        f"got {after_first['version']}"
    )
    assert after_first["available_mass_kg"] == pytest.approx(479.000, abs=0.001)
    assert after_first["reserved_mass_kg"] == pytest.approx(21.000, abs=0.001)
    assert_wire_mass_ledger(after_first)

    overlapping_stale = _lot_payload(
        env,
        stale_version,
        lot_code="L-OCC2",
        press_window_start_at="2026-09-01T07:00:00Z",
        press_window_end_at="2026-09-01T09:00:00Z",
        planned_pieces=1000,
    )
    validate_error(
        api.create_production_lot(overlapping_stale, engineer_headers),
        ApiErrorId.ERR_STALE_WIRE_LOT_VERSION.value,
    )

    unchanged = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert unchanged["version"] == 3, (
        f"A refused open must not advance the coil: expected version 3, "
        f"got {unchanged['version']}"
    )
    assert unchanged["available_mass_kg"] == pytest.approx(479.000, abs=0.001), (
        "The refused open must leave the wire ledger untouched"
    )

    fresh_version = unchanged["version"]
    overlapping_fresh = _lot_payload(
        env,
        fresh_version,
        lot_code="L-OCC2",
        press_window_start_at="2026-09-01T07:00:00Z",
        press_window_end_at="2026-09-01T09:00:00Z",
        planned_pieces=1000,
    )
    validate_error(
        api.create_production_lot(overlapping_fresh, engineer_headers),
        ApiErrorId.ERR_TOOL_WINDOW_CONFLICT.value,
    )
    still_three = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert still_three["version"] == 3, (
        f"The window conflict must not advance the coil either, "
        f"got {still_three['version']}"
    )

    abutting = _lot_payload(
        env,
        fresh_version,
        lot_code="L-OCC2",
        press_window_start_at="2026-09-01T08:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
        planned_pieces=1000,
    )
    second = validate_success(api.create_production_lot(abutting, engineer_headers), 201)
    assert second["wire_reserved_kg"] == pytest.approx(21.000, abs=0.001)

    settled = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert settled["version"] == 4, (
        f"Expected version 4 after the second reservation, got {settled['version']}"
    )
    assert settled["available_mass_kg"] == pytest.approx(458.000, abs=0.001), (
        f"Expected 458.000 kg free after two 21.000 kg reservations, "
        f"got {settled['available_mass_kg']}"
    )
    assert settled["reserved_mass_kg"] == pytest.approx(42.000, abs=0.001)
    assert settled["consumed_mass_kg"] == pytest.approx(0.000, abs=0.001)
    assert_wire_mass_ledger(settled)


def test_stale_production_lot_version_outranks_the_hold_check_at_draft(
    api, inspector_headers, inspector_alt_headers, manager_headers
):
    """A drafting client whose lot version predates the hold is told the version is
    stale, both while the lot is held and after the hold has been cleared.

    PRD: "If that value does not equal the lot's current `version`, the request is rejected with `ERR_STALE_PRODUCTION_LOT_VERSION` (HTTP 412)."

    PRD: "Note that this tier sits *above* the hold, state and window rules — a client presenting a stale parent version is told so even when the operation would also have failed a later check."

    PRD: "A `QualityInspector` or `QualityManager` may place a hold with a `reason` on any lot whose `disposition` is `IN_PROCESS`, taking it `IN_PROCESS → HOLD` with `hold_source` of `QUALITY` and incrementing its `version` by 1."

    PRD: "A successful release takes the lot `HOLD → IN_PROCESS`, resets `hold_source` to `NONE`, and increments the `version` by 1."

    PRD: "A fresh draft starts in `status` `DRAFT` with `revision` of 1 and `signed_by_user_id`, `issued_at` and `revoked_reason` all empty."

    Design: Corner/complexity_layers/stale_production_lot_version_outranks_the_hold_check_at_draft
    """
    env = fixtures.setup_tested_lot(
        unplated=True,
        clock=CLOCK,
        spec_overrides=dict(SPEC_OVERRIDES),
        wire_overrides=dict(WIRE_OVERRIDES),
        tool_overrides=dict(TOOL_OVERRIDES),
        min_measured_core_hardness_hv=322.0,
    )
    lot_id = env["lot"]["id"]
    test_id = env["lot_test"]["id"]
    lot_version_read = env["lot"]["version"]
    assert env["lot"]["process_state"] == "TESTED", (
        f"Expected the lot in TESTED before drafting, got {env['lot']['process_state']}"
    )
    assert env["lot"]["achieved_strength_class"] == "CLASS_10_9", (
        "A weakest piece of 322.0 HV lands inside the specified CLASS_10_9 band"
    )

    held = validate_success(
        api.hold_production_lot(lot_id, {"reason": "CUSTOMER_AUDIT"}, inspector_alt_headers)
    )
    assert held["disposition"] == "HOLD", (
        f"Expected disposition HOLD, got {held['disposition']}"
    )
    assert held["version"] == lot_version_read + 1, (
        f"The hold must bump the lot to {lot_version_read + 1}, got {held['version']}"
    )

    # Priority 7 decides before the priority 9 hold rule.
    validate_error(
        api.create_certification_document(
            factories.create_certification_document_payload(
                lot_id, test_id, lot_version_read, cert_serial="CERT-OCC3"
            ),
            inspector_headers,
        ),
        ApiErrorId.ERR_STALE_PRODUCTION_LOT_VERSION.value,
    )

    released = validate_success(
        api.release_hold(lot_id, {"note": "AUDIT_CLEARED"}, manager_headers)
    )
    assert released["disposition"] == "IN_PROCESS", (
        f"Expected the release to restore IN_PROCESS, got {released['disposition']}"
    )
    assert released["hold_source"] == "NONE", (
        f"Expected hold_source NONE after the release, got {released['hold_source']}"
    )

    # The release bumped the version again, so the same stale value still fails.
    validate_error(
        api.create_certification_document(
            factories.create_certification_document_payload(
                lot_id, test_id, lot_version_read, cert_serial="CERT-OCC3"
            ),
            inspector_headers,
        ),
        ApiErrorId.ERR_STALE_PRODUCTION_LOT_VERSION.value,
    )

    refreshed = validate_success(api.get_production_lot(lot_id, inspector_headers))
    assert refreshed["version"] == lot_version_read + 2, (
        f"One hold plus one release-hold must add exactly 2 versions and neither 412 "
        f"may add any: expected {lot_version_read + 2}, got {refreshed['version']}"
    )
    assert refreshed["disposition"] == "IN_PROCESS"
    assert refreshed["hold_source"] == "NONE"

    certificate = validate_success(
        api.create_certification_document(
            factories.create_certification_document_payload(
                lot_id, test_id, refreshed["version"], cert_serial="CERT-OCC3"
            ),
            inspector_headers,
        ),
        201,
    )
    assert certificate["status"] == "DRAFT", (
        f"Expected status DRAFT, got {certificate['status']}"
    )
    assert certificate["revision"] == 1, (
        f"Expected revision 1 on a fresh draft, got {certificate['revision']}"
    )
    assert certificate["pinned_part_spec_version"] == refreshed["pinned_part_spec_version"], (
        "The draft copies pinned_part_spec_version from the lot"
    )
    assert certificate["certified_strength_class"] == "CLASS_10_9", (
        f"Expected certified_strength_class CLASS_10_9, "
        f"got {certificate['certified_strength_class']}"
    )


# ---------------------------------------------------------------------------
# The version counter itself
# ---------------------------------------------------------------------------
def test_wire_lot_version_advances_once_per_write_and_never_on_a_read(
    api, engineer_headers, inspector_headers, clerk_headers
):
    """The coil's version is a strict write counter: 1 at creation, 2 after release,
    3 after a lot reserves mass and 4 once heading settles it, while interleaved
    reads and one refused release leave it exactly where it was.

    PRD: "- **`version`** (integer): starts at 1 when the record is created and increments by exactly 1 on every mutation of that record."

    PRD: "- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock at the moment the record was created."

    PRD: "- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed from the logical clock on every mutation of the record."

    PRD: "On success the lot moves `DRAWN → RELEASED`, `inspected_at` is stamped from the logical clock, and the lot's `version` increments by 1."

    PRD: "A wire lot must be `DRAWN` to be released, so quarantined and already-released lots are refused — otherwise `ERR_INVALID_WIRE_LOT_STATE` (409)."

    PRD: "The wire ledger settles: the actually consumed mass is the sum of the two reported counts multiplied by `blank_mass_g`, divided by 1000, rounded half up to three decimal places; the lot's original `wire_reserved_kg` is subtracted from the wire lot's `reserved_mass_kg`, the consumed mass is added to `consumed_mass_kg`, and the difference between the reservation and the consumption is added back to `available_mass_kg` — which will be negative when the lot over-consumed."

    Design: Corner/complexity_layers/every_write_bumps_the_version_and_no_read_does
    """
    fixtures.set_clock(CLOCK)
    spec = fixtures.register_part_spec(**SPEC_OVERRIDES)
    heat = fixtures.create_verified_heat()
    tool = fixtures.register_heading_tool(**TOOL_OVERRIDES)
    fixtures.mount_tool(tool["id"], "PRESS-3")

    created = validate_success(
        api.create_wire_lot(
            factories.create_wire_lot_payload(heat["id"], **WIRE_OVERRIDES),
            engineer_headers,
        ),
        201,
    )
    wire_id = created["id"]
    assert created["version"] == 1, (
        f"A freshly recorded coil starts at version 1, got {created['version']}"
    )

    read_one = validate_success(api.get_wire_lot(wire_id, clerk_headers))
    assert read_one["version"] == 1, (
        f"A read is not a mutation: expected version 1, got {read_one['version']}"
    )
    assert read_one["created_at"] == created["created_at"]

    released = validate_success(api.release_wire_lot(wire_id, inspector_headers))
    assert released["version"] == 2, (
        f"The release is the coil's second write: expected version 2, "
        f"got {released['version']}"
    )
    assert released["inspected_at"].startswith("2026-09-01T06:00:00"), (
        f"inspected_at is stamped from the logical clock, got {released['inspected_at']}"
    )

    validate_error(
        api.release_wire_lot(wire_id, inspector_headers),
        ApiErrorId.ERR_INVALID_WIRE_LOT_STATE.value,
    )
    read_two = validate_success(api.get_wire_lot(wire_id, clerk_headers))
    assert read_two["version"] == 2, (
        f"A refused re-release mutates nothing: expected version 2, "
        f"got {read_two['version']}"
    )

    lot = validate_success(
        api.create_production_lot(
            factories.create_production_lot_payload(
                spec["id"],
                wire_id,
                tool["id"],
                read_two["version"],
                lot_code="L-VER1",
                press_code="PRESS-3",
                press_window_start_at="2026-09-01T06:00:00Z",
                press_window_end_at="2026-09-01T08:00:00Z",
                planned_pieces=1000,
            ),
            engineer_headers,
        ),
        201,
    )
    read_three = validate_success(api.get_wire_lot(wire_id, clerk_headers))
    assert read_three["version"] == 3, (
        f"The reservation is the coil's third write: expected version 3, "
        f"got {read_three['version']}"
    )
    assert read_three["available_mass_kg"] == pytest.approx(479.000, abs=0.001)
    assert read_three["reserved_mass_kg"] == pytest.approx(21.000, abs=0.001)

    fixtures.set_clock("2026-09-01T07:00:00Z")
    validate_success(
        api.complete_heading(
            lot["id"], {"headed_count": 980, "heading_scrap_count": 20}, engineer_headers
        )
    )
    read_four = validate_success(api.get_wire_lot(wire_id, clerk_headers))
    assert read_four["version"] == 4, (
        f"Heading completion is the coil's fourth write: expected version 4, "
        f"got {read_four['version']}"
    )
    # 1000 pieces actually formed at 20.0 g each; the 1.000 kg unused reservation returns.
    assert read_four["consumed_mass_kg"] == pytest.approx(20.000, abs=0.001)
    assert read_four["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001)
    assert read_four["available_mass_kg"] == pytest.approx(480.000, abs=0.001)
    assert_wire_mass_ledger(read_four)
    assert read_four["created_at"] == created["created_at"], (
        "created_at is fixed at creation and never moves"
    )
    assert read_four["updated_at"].startswith("2026-09-01T07:00:00"), (
        f"updated_at is refreshed from the logical clock on every mutation, "
        f"got {read_four['updated_at']}"
    )


def test_lot_and_die_set_version_counters_track_only_their_own_writes(
    api, engineer_headers, manager_headers
):
    """The lot counts two writes (open, heading completion) and the die set three
    (register, mount, the wear counter heading advanced), and the reads in between
    add nothing.

    PRD: "- **`version`** (integer): starts at 1 when the record is created and increments by exactly 1 on every mutation of that record."

    PRD: "A `ProcessEngineer` mounts an `AVAILABLE` set on a press by supplying the `press_code`, taking it `AVAILABLE → MOUNTED`, recording the press in `mounted_press_code`, clearing any previous `condemn_reason`, and incrementing the set's `version` by 1."

    PRD: "The lot's `version`, the wire lot's `version` and the die set's `version` each increment by 1, plus the `version` of every lot put on hold."

    Design: Corner/complexity_layers/every_write_bumps_the_version_and_no_read_does
    """
    env = fixtures.setup_lot_in_setup(
        planned_pieces=1000,
        clock=CLOCK,
        spec_overrides=dict(SPEC_OVERRIDES),
        wire_overrides=dict(WIRE_OVERRIDES),
        tool_overrides=dict(TOOL_OVERRIDES),
    )
    lot_id = env["lot"]["id"]
    tool_id = env["tool"]["id"]

    assert env["lot"]["version"] == 1, (
        f"A freshly opened lot starts at version 1, got {env['lot']['version']}"
    )
    mounted = validate_success(api.get_heading_tool(tool_id, manager_headers))
    assert mounted["version"] == 2, (
        f"Register then mount is two writes on the die set: expected version 2, "
        f"got {mounted['version']}"
    )
    # Two more reads, from two different roles: still no mutation.
    assert (
        validate_success(api.get_heading_tool(tool_id, engineer_headers))["version"] == 2
    )
    assert (
        validate_success(api.get_production_lot(lot_id, manager_headers))["version"] == 1
    )

    validate_success(
        api.complete_heading(
            lot_id, {"headed_count": 980, "heading_scrap_count": 20}, engineer_headers
        )
    )
    lot_after = validate_success(api.get_production_lot(lot_id, manager_headers))
    assert lot_after["version"] == 2, (
        f"Open then complete heading is two writes on the lot: expected version 2, "
        f"got {lot_after['version']}"
    )
    tool_after = validate_success(api.get_heading_tool(tool_id, manager_headers))
    assert tool_after["version"] == 3, (
        f"Register, mount and the wear-counter advance are three writes on the die "
        f"set: expected version 3, got {tool_after['version']}"
    )
    assert tool_after["cumulative_pieces_current_cycle"] == 1000, (
        f"The open cycle grows by the two reported counts, "
        f"got {tool_after['cumulative_pieces_current_cycle']}"
    )


# ---------------------------------------------------------------------------
# A filtered listing is evaluated at request time
# ---------------------------------------------------------------------------
def test_wire_lot_listing_stays_consistent_while_statuses_change(
    api, engineer_headers, inspector_headers, manager_headers
):
    """The status filter is re-evaluated per request: three DRAWN coils on one heat
    report 3, and after one is released the same query reports 2 while the RELEASED
    query reports 1.

    PRD: "Both `total_count` and `has_more` are computed against the *filtered* result set, not against the whole collection: when a caller filters wire lots by `steel_heat_id` and `status`, `total_count` reports how many wire lots match those filters, and `has_more` reports whether records matching those filters remain beyond the current page."

    PRD: "Filters combine conjunctively — every supplied filter must match."

    PRD: "Wire lots may be filtered by `steel_heat_id` and by `status`."

    PRD: "The three mass ledger members are initialised so the identity holds trivially — `available_mass_kg` equals `gross_mass_kg`, while `reserved_mass_kg` and `consumed_mass_kg` are both zero — and `status` starts at `DRAWN` with `quarantine_source` of `NONE` and `inspected_at` empty."

    PRD: "The server derives `reduction_pct` from the diameters: divide the outlet diameter by the inlet diameter, square that ratio to get the surviving cross-sectional area fraction, subtract it from one, multiply by one hundred, and round the result half up to two decimal places."

    Design: Corner/complexity_layers/wire_lot_listing_stays_consistent_while_statuses_change
    """
    fixtures.set_clock(CLOCK)
    heat = fixtures.create_verified_heat(gross_mass_kg=600.0)
    other_heat = fixtures.register_steel_heat(
        heat_number="H-77411",
        grade="SAE_1038",
        carbon_pct=0.38,
        boron_ppm=0,
        gross_mass_kg=200.0,
        mill_cert_serial="MC-2026-000482",
    )

    coil_overrides = dict(WIRE_OVERRIDES, gross_mass_kg=200.0)
    coils = [
        validate_success(
            api.create_wire_lot(
                factories.create_wire_lot_payload(heat["id"], **coil_overrides),
                engineer_headers,
            ),
            201,
        )
        for _ in range(3)
    ]
    foreign = validate_success(
        api.create_wire_lot(
            factories.create_wire_lot_payload(other_heat["id"], **coil_overrides),
            engineer_headers,
        ),
        201,
    )

    items, meta = validate_paginated(
        api.list_wire_lots(
            manager_headers,
            params={
                "steel_heat_id": heat["id"],
                "status": "DRAWN",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 3, (
        f"Three DRAWN coils belong to that heat, total_count reported "
        f"{meta['total_count']}"
    )
    assert meta["has_more"] is False, "The whole filtered set fits on the page"
    returned_ids = [row["id"] for row in items]
    assert returned_ids == [c["id"] for c in coils], (
        f"Expected the heat's three coils in created_at order, got {returned_ids}"
    )
    assert foreign["id"] not in returned_ids, (
        "The other heat's coil must never appear under a steel_heat_id filter"
    )
    for row in items:
        assert row["available_mass_kg"] == pytest.approx(200.000, abs=0.001)
        assert row["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001)
        assert row["consumed_mass_kg"] == pytest.approx(0.000, abs=0.001)
        assert_wire_mass_ledger(row)

    page, page_meta = validate_paginated(
        api.list_wire_lots(
            manager_headers,
            params={"steel_heat_id": heat["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page) == 1, f"limit 2 / offset 2 leaves one trailing row, got {len(page)}"
    assert page[0]["id"] == coils[2]["id"]
    assert page_meta["total_count"] == 3, (
        f"total_count counts the filtered set, not the page: got "
        f"{page_meta['total_count']}"
    )
    assert page_meta["has_more"] is False, (
        "Nothing matching the filter remains beyond this page"
    )

    validate_success(api.release_wire_lot(coils[1]["id"], inspector_headers))

    drawn, drawn_meta = validate_paginated(
        api.list_wire_lots(
            manager_headers,
            params={
                "steel_heat_id": heat["id"],
                "status": "DRAWN",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert drawn_meta["total_count"] == 2, (
        f"One coil left DRAWN, so the filter must now report 2, got "
        f"{drawn_meta['total_count']}"
    )
    assert [row["id"] for row in drawn] == [coils[0]["id"], coils[2]["id"]]

    released, released_meta = validate_paginated(
        api.list_wire_lots(
            manager_headers,
            params={
                "steel_heat_id": heat["id"],
                "status": "RELEASED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert released_meta["total_count"] == 1, (
        f"Exactly one coil is RELEASED, got {released_meta['total_count']}"
    )
    assert released[0]["id"] == coils[1]["id"]
    assert released[0]["reduction_pct"] == pytest.approx(27.75, abs=0.001), (
        f"8.00 -> 6.80 mm is a 27.75 % reduction, got {released[0]['reduction_pct']}"
    )

    plant_wide, plant_meta = validate_paginated(
        api.list_wire_lots(
            manager_headers, params={"status": "DRAWN", "limit": 10, "offset": 0}
        )
    )
    assert plant_meta["total_count"] == 3, (
        f"Without the heat filter the DRAWN set spans both heats and holds 3 coils, "
        f"got {plant_meta['total_count']}"
    )
    assert {row["id"] for row in plant_wide} == {
        coils[0]["id"],
        coils[2]["id"],
        foreign["id"],
    }


# ---------------------------------------------------------------------------
# Read-your-writes: cascades and computed fields are immediately visible
# ---------------------------------------------------------------------------
def test_condemn_cascade_is_visible_on_the_very_next_read(
    api, engineer_headers, inspector_headers
):
    """Condemning the die set returns the tool, yet both sibling lots it froze are
    already on hold when read immediately afterwards, with no second write and no
    clock advance.

    PRD: "The operator route is a `ProcessEngineer` or `QualityInspector` condemning a chipped or cracked die with a supplied `reason`: `status` becomes `WORN`, that `reason` is recorded as `condemn_reason`, `mounted_press_code` is cleared, and every production lot on that set in `process_state` `SETUP` moves, in ascending `created_at` order, to `disposition` `HOLD` with `hold_source` `TOOL_WEAR`."

    PRD: "In both routes the set's `version` increments by 1, as does the `version` of every lot put on hold."

    PRD: "The `disposition` dimension is deliberately independent of `process_state`: a lot can be frozen and thawed without moving one step along its process route."

    PRD: "Production lots may be filtered by `part_spec_id`, `wire_lot_id`, `heading_tool_id`, `traceability_heat_id`, and by either state dimension independently — `process_state` or `disposition`."

    Design: Corner/consistency_model/cascade_results_are_visible_without_a_second_write
    """
    env = _reference_env()
    wire_id = env["wire"]["id"]
    tool_id = env["tool"]["id"]

    first = validate_success(
        api.create_production_lot(
            _lot_payload(
                env,
                env["wire"]["version"],
                lot_code="L-CM1",
                press_window_start_at="2026-09-01T06:00:00Z",
                press_window_end_at="2026-09-01T08:00:00Z",
                planned_pieces=1000,
            ),
            engineer_headers,
        ),
        201,
    )
    refreshed_wire = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    second = validate_success(
        api.create_production_lot(
            _lot_payload(
                env,
                refreshed_wire["version"],
                lot_code="L-CM2",
                press_window_start_at="2026-09-01T08:00:00Z",
                press_window_end_at="2026-09-01T10:00:00Z",
                planned_pieces=1000,
            ),
            engineer_headers,
        ),
        201,
    )

    condemned = validate_success(
        api.condemn_heading_tool(
            tool_id, {"reason": "CRACKED_STATION_2"}, inspector_headers
        )
    )
    assert condemned["status"] == "WORN", (
        f"Expected the condemned set at WORN, got {condemned['status']}"
    )
    assert condemned["condemn_reason"] == "CRACKED_STATION_2", (
        f"Expected the supplied reason recorded, got {condemned['condemn_reason']}"
    )
    assert not condemned["mounted_press_code"], (
        f"mounted_press_code must be cleared, got {condemned['mounted_press_code']!r}"
    )
    assert condemned["version"] == 3, (
        f"Register, mount and condemn are three writes: expected version 3, "
        f"got {condemned['version']}"
    )

    for lot in (first, second):
        frozen = validate_success(api.get_production_lot(lot["id"], engineer_headers))
        assert frozen["disposition"] == "HOLD", (
            f"Lot {lot['lot_code']} must already be on hold on the next read, "
            f"got {frozen['disposition']}"
        )
        assert frozen["hold_source"] == "TOOL_WEAR", (
            f"Expected hold_source TOOL_WEAR on {lot['lot_code']}, "
            f"got {frozen['hold_source']}"
        )
        assert frozen["version"] == 2, (
            f"The cascade is the lot's second write: expected version 2 on "
            f"{lot['lot_code']}, got {frozen['version']}"
        )
        assert frozen["process_state"] == "SETUP", (
            f"The cascade touches only the disposition dimension, "
            f"{lot['lot_code']} moved to {frozen['process_state']}"
        )
        assert_lot_piece_ledger(frozen)

    held, held_meta = validate_paginated(
        api.list_production_lots(
            engineer_headers, params={"disposition": "HOLD", "limit": 10, "offset": 0}
        )
    )
    assert held_meta["total_count"] == 2, (
        f"Both lots are on hold in the same instant, listing reported "
        f"{held_meta['total_count']}"
    )
    assert {row["id"] for row in held} == {first["id"], second["id"]}


def test_wire_lot_creation_response_already_carries_its_derived_ledger(
    api, engineer_headers, manager_headers
):
    """The coil's own creation response already carries the derived reduction and the
    full mass ledger, and a following read repeats them unchanged.

    PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    PRD: "The server derives `reduction_pct` from the diameters: divide the outlet diameter by the inlet diameter, square that ratio to get the surviving cross-sectional area fraction, subtract it from one, multiply by one hundred, and round the result half up to two decimal places."

    PRD: "The three mass ledger members are initialised so the identity holds trivially — `available_mass_kg` equals `gross_mass_kg`, while `reserved_mass_kg` and `consumed_mass_kg` are both zero — and `status` starts at `DRAWN` with `quarantine_source` of `NONE` and `inspected_at` empty."

    Design: Corner/consistency_model/computed_fields_are_returned_by_the_writing_call_itself
    """
    fixtures.set_clock(CLOCK)
    heat = fixtures.create_verified_heat()

    created = validate_success(
        api.create_wire_lot(
            factories.create_wire_lot_payload(heat["id"], **WIRE_OVERRIDES),
            engineer_headers,
        ),
        201,
    )
    assert created["reduction_pct"] == pytest.approx(27.75, abs=0.001), (
        f"8.00 -> 6.80 mm must come back as 27.75 on the writing call itself, "
        f"got {created['reduction_pct']}"
    )
    assert created["available_mass_kg"] == pytest.approx(500.000, abs=0.001)
    assert created["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001)
    assert created["consumed_mass_kg"] == pytest.approx(0.000, abs=0.001)
    assert created["status"] == "DRAWN", (
        f"A newly recorded coil starts DRAWN, got {created['status']}"
    )
    assert created["quarantine_source"] == "NONE"
    assert_wire_mass_ledger(created)

    read_back = validate_success(api.get_wire_lot(created["id"], manager_headers))
    for field in (
        "reduction_pct",
        "available_mass_kg",
        "reserved_mass_kg",
        "consumed_mass_kg",
        "status",
        "quarantine_source",
        "version",
    ):
        assert read_back[field] == created[field], (
            f"{field} changed between the write response ({created[field]}) and the "
            f"immediately following read ({read_back[field]})"
        )


def test_complete_heading_response_already_carries_the_settled_counters(
    api, engineer_headers, manager_headers
):
    """Opening the lot and reporting heading completion both return every value they
    derived — the pinned spec version, the reservation, the settled piece counts, the
    consumed mass and the tool utilisation snapshot — and the separate reads only
    confirm them.

    PRD: "`pinned_part_spec_version` copies the part specification's current `version`, which is what later makes a mid-flight revision visible as drift rather than as silent change."

    PRD: "And `traceability_heat_id` copies the wire lot's `steel_heat_id`, denormalising the provenance edge so the lot's origin survives even as the wire lot's own record moves on."

    PRD: "The required mass is `planned_pieces` multiplied by the part's `blank_mass_g`, multiplied by one plus `scrap_allowance_pct`, divided by 1000 to convert grams to kilograms, and rounded half up to three decimal places."

    PRD: "The reported counts land: `headed_count` and `available_count` both take the reported good-piece count, while `heading_scrap_count` and `scrap_count` both take the reported scrap count."

    PRD: "The consumed mass is stored as `wire_consumed_kg` and `wire_reserved_kg` drops to zero."

    PRD: "The lot then snapshots its own wear picture as `tool_utilization_pct`, which is 100 multiplied by the set's new `cumulative_pieces_current_cycle`, divided by its `rated_derated_life_pieces`, rounded half up to two decimal places — note that wear is always measured against the *rated derated* budget, never against the conservative one, whatever the part's qualification programme."

    Design: Corner/consistency_model/computed_fields_are_returned_by_the_writing_call_itself
    """
    env = _reference_env()

    opened = validate_success(
        api.create_production_lot(
            _lot_payload(
                env,
                env["wire"]["version"],
                lot_code="L-CM3",
                press_window_start_at="2026-09-01T06:00:00Z",
                press_window_end_at="2026-09-01T10:00:00Z",
                planned_pieces=5000,
            ),
            engineer_headers,
        ),
        201,
    )
    assert opened["pinned_part_spec_version"] == env["spec"]["version"], (
        f"The open must pin the specification's live version "
        f"{env['spec']['version']}, got {opened['pinned_part_spec_version']}"
    )
    assert opened["traceability_heat_id"] == env["heat"]["id"], (
        f"traceability_heat_id must copy the coil's steel heat, "
        f"got {opened['traceability_heat_id']}"
    )
    # 5000 pieces * 20.0 g * 1.05 / 1000.
    assert opened["wire_reserved_kg"] == pytest.approx(105.000, abs=0.001), (
        f"Expected a reservation of 105.000 kg on the creating response, "
        f"got {opened['wire_reserved_kg']}"
    )

    headed = validate_success(
        api.complete_heading(
            opened["id"], {"headed_count": 4900, "heading_scrap_count": 60}, engineer_headers
        )
    )
    assert headed["process_state"] == "HEADED"
    assert headed["available_count"] == 4900, (
        f"Expected available_count 4900 on the writing call, "
        f"got {headed['available_count']}"
    )
    assert headed["headed_count"] == 4900
    assert headed["scrap_count"] == 60, (
        f"Expected scrap_count 60 on the writing call, got {headed['scrap_count']}"
    )
    assert headed["heading_scrap_count"] == 60
    # 4960 pieces actually formed at 20.0 g each.
    assert headed["wire_consumed_kg"] == pytest.approx(99.200, abs=0.001), (
        f"Expected wire_consumed_kg 99.200, got {headed['wire_consumed_kg']}"
    )
    assert headed["wire_reserved_kg"] == pytest.approx(0.000, abs=0.001)
    # 100 * 4960 / 120000 = 4.1333..., rounded half up to two places.
    assert headed["tool_utilization_pct"] == pytest.approx(4.13, abs=0.001), (
        f"Expected tool_utilization_pct 4.13 on the writing call, "
        f"got {headed['tool_utilization_pct']}"
    )
    assert_lot_piece_ledger(headed)

    lot_read = validate_success(api.get_production_lot(opened["id"], manager_headers))
    for field in (
        "available_count",
        "headed_count",
        "scrap_count",
        "heading_scrap_count",
        "wire_consumed_kg",
        "wire_reserved_kg",
        "tool_utilization_pct",
        "process_state",
        "version",
    ):
        assert lot_read[field] == headed[field], (
            f"{field} changed between the heading response ({headed[field]}) and the "
            f"immediately following read ({lot_read[field]})"
        )

    wire_read = validate_success(api.get_wire_lot(env["wire"]["id"], manager_headers))
    assert wire_read["available_mass_kg"] == pytest.approx(400.800, abs=0.001), (
        f"Expected 400.800 kg free once the reservation settled, "
        f"got {wire_read['available_mass_kg']}"
    )
    assert wire_read["consumed_mass_kg"] == pytest.approx(99.200, abs=0.001)
    assert wire_read["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001)
    assert_wire_mass_ledger(wire_read)

    tool_read = validate_success(api.get_heading_tool(env["tool"]["id"], manager_headers))
    assert tool_read["cumulative_pieces_current_cycle"] == 4960, (
        f"The open cycle must already hold 4960 pieces, "
        f"got {tool_read['cumulative_pieces_current_cycle']}"
    )
    assert tool_read["status"] == "MOUNTED", (
        f"4960 pieces is far short of the derated budget, so the set stays MOUNTED, "
        f"got {tool_read['status']}"
    )
