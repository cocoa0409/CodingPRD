"""Entity persistence and read-path behaviour of the Utility-Scale Solar EPC API.

Each test pins one obligation the PRD places on a create, a read, a listing or a
declared field default: what the server stores, what it derives, what it mints
itself, and which shapes it refuses.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_cents,
    assert_created_fresh,
    assert_versionless_interval,
    assert_zone_occupancy,
    factories as f,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    accepted_area,
    create_block,
    create_grading_area,
    create_project,
    create_pile,
    create_yard_zone,
    log_clearing,
    read_project,
    record_drive_result,
    reset_clock,
    reserve_delivery,
    schedule_commissioning_test,
)


# ---------------------------------------------------------------------------
# Project creation: declared inputs and derived state at rest
# ---------------------------------------------------------------------------
def test_project_create_returns_201_and_echoes_every_declared_input(api, epc_headers):
    """A project create answers 201 and echoes each declared commercial input unchanged.

    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/entities/project_creation_persists_every_declared_field_and_seeds_derived_state
    """
    payload = f.project_payload(name="Basin Mesa I", utility_name="Basin Power")
    data = validate_success(api.create_project(payload, epc_headers), expected_status=201)

    assert data["name"] == "Basin Mesa I"
    assert data["utility_name"] == "Basin Power"
    assert data["ac_capacity_kw"] == pytest.approx(100, abs=0.01)
    assert data["dc_capacity_kw"] == pytest.approx(130, abs=0.01)
    assert_cents(data["contract_value_cents"], 10000000, "contract_value_cents")
    assert data["retainage_pct"] == pytest.approx(0.05, abs=0.0001)
    assert_cents(data["ld_per_day_cents"], 50000, "ld_per_day_cents")
    assert data["ld_cap_pct"] == pytest.approx(0.05, abs=0.0001)
    assert data["sc_deadline_date"] == "2026-08-01"
    assert data["guaranteed_capacity_kw_ac"] == pytest.approx(100, abs=0.01)
    assert data["guaranteed_performance_ratio"] == pytest.approx(0.69, abs=0.0001)


def test_project_create_seeds_every_derived_field_at_rest(api, epc_headers):
    """A brand-new project reports its state fields and every ledger figure at rest.

    PRD 3.1: "A newly persisted project has `version` 1 and every derived field at rest."

    Design: Corner/entities/project_creation_persists_every_declared_field_and_seeds_derived_state
    """
    data = validate_success(
        api.create_project(f.project_payload(), epc_headers), expected_status=201
    )

    assert data["milestone_state"] == "PRECONSTRUCTION"
    assert data["mc_readiness"] == "BLOCKED"
    assert data["tax_credit_status"] == "UNDETERMINED"
    for field in (
        "approved_change_order_cents",
        "blocks_total",
        "blocks_mc_ready_count",
        "total_labor_hours",
        "apprentice_labor_hours",
        "apprentice_hours_pct",
        "wage_restitution_owed_cents",
        "wage_liquidated_damages_cents",
        "open_punch_item_count",
        "open_critical_punch_count",
        "delay_days",
        "ld_assessed_cents",
        "retainage_held_cents",
        "punchlist_holdback_cents",
        "sc_payment_due_cents",
        "final_payment_cents",
    ):
        assert data[field] == 0, f"{field} must start at 0, got {data[field]!r}"
    assert data["apprenticeship_basis_applied"] is None
    assert data["mc_claimed_by_user_id"] is None
    assert data["last_milestone_rejection_reason"] is None
    assert_created_fresh(data)


# ---------------------------------------------------------------------------
# Optional labor-compliance selectors and their declared defaults
# ---------------------------------------------------------------------------
def test_project_create_applies_the_declared_labor_flag_defaults(api, epc_headers):
    """Omitting the three optional labor selectors yields their declared defaults.

    PRD 3.1: "`apprenticeship_basis` defaults to `PROJECT_AGGREGATE` and selects which of the two apprenticeship measurement variants a labor-compliance run applies; the alternative is `WEEKLY_WORST_CASE`."

    Design: Corner/entities/project_optional_labor_flags_fall_back_to_declared_defaults
    """
    data = validate_success(
        api.create_project(f.project_payload(name="Default Ridge"), epc_headers),
        expected_status=201,
    )

    assert data["prevailing_wage_election"] == "REMEDIABLE"
    assert data["apprenticeship_basis"] == "PROJECT_AGGREGATE"
    assert data["apprenticeship_min_pct"] == pytest.approx(15.00, abs=0.01)
    assert data["version"] == 1


def test_project_create_honours_explicit_labor_flag_values(api, epc_headers):
    """Supplying the alternative selector values stores them instead of the defaults.

    PRD 3.1: "`prevailing_wage_election` defaults to `REMEDIABLE`, which accepts an under-prevailing payroll line and accrues restitution against it; the alternative value `STRICT` refuses such a line outright at post time."

    Design: Corner/entities/project_optional_labor_flags_fall_back_to_declared_defaults
    """
    payload = f.project_payload(
        name="Explicit Ridge",
        prevailing_wage_election="STRICT",
        apprenticeship_basis="WEEKLY_WORST_CASE",
        apprenticeship_min_pct=12.50,
    )
    data = validate_success(api.create_project(payload, epc_headers), expected_status=201)

    assert data["prevailing_wage_election"] == "STRICT"
    assert data["apprenticeship_basis"] == "WEEKLY_WORST_CASE"
    assert data["apprenticeship_min_pct"] == pytest.approx(12.50, abs=0.01)
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# Reading a grading area back
# ---------------------------------------------------------------------------
def test_grading_area_read_reflects_the_earthwork_ledger_and_permit_defaults(
    api, project, owner_headers
):
    """A grading-area read returns the stored row, ledger and permit fields included.

    PRD 3.2: "The system appends a record of the `work_start_at`, `work_end_at`, `activity_type` and `acreage_disturbed_delta` to `earthwork_windows`, then recomputes `disturbed_acreage_current` as the sum of `acreage_disturbed_delta` across every appended record taken in `created_at` ascending order, rounded half up to two decimal places."

    Design: Corner/entities/grading_area_retrieval_returns_the_stored_representation
    """
    area = create_grading_area(api, project["id"], access_road_meters=1200)
    log_clearing(api, area["id"], acreage=10.00)

    data = validate_success(api.get_grading_area(area["id"], owner_headers))

    assert data["id"] == area["id"]
    assert data["project_id"] == project["id"]
    assert data["area_code"] == "A1"
    assert data["permit_number"] == "CGP-2026-118"
    assert data["disturbed_acreage_limit"] == pytest.approx(40.00, abs=0.01)
    assert data["access_road_meters"] == pytest.approx(1200, abs=0.01)
    assert data["disturbed_acreage_current"] == pytest.approx(10.00, abs=0.01)
    assert data["permit_status"] == "ACTIVE"
    assert data["status"] == "CLEARED"
    assert data["bmp_deficiency_open"] is False
    assert data["bmp_last_inspected_at"] is not None
    assert data["rain_blackout_until"] is None


# ---------------------------------------------------------------------------
# Block listing: page window over a filtered population
# ---------------------------------------------------------------------------
def _project_with_three_blocks(api):
    """One project, one accepted area, blocks B1 (piles complete), B2 and B3."""
    project = create_project(api)
    area = accepted_area(api, project["id"])
    blocks = {
        code: create_block(api, project["id"], area["id"], block_code=code)
        for code in ("B1", "B2", "B3")
    }
    pile = create_pile(api, blocks["B1"]["id"])
    record_drive_result(api, pile["id"])
    return project, blocks


def test_block_listing_paginates_over_the_filtered_population(api, epc_headers):
    """limit/offset walk the filtered rows while total_count counts the filter, not the table.

    PRD 2.3: "`total_count` is the number of rows matching the request's filters *before* the page window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the current window."

    Design: Corner/entities/block_listing_paginates_and_filters_by_mechanical_status
    """
    project, blocks = _project_with_three_blocks(api)
    query = {"project_id": project["id"], "mechanical_status": "PLANNED"}

    first, first_meta = validate_paginated(
        api.list_blocks(epc_headers, {**query, "limit": 1, "offset": 0})
    )
    second, second_meta = validate_paginated(
        api.list_blocks(epc_headers, {**query, "limit": 1, "offset": 1})
    )

    assert len(first) == 1
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0

    assert len(second) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False

    paged_ids = {row["id"] for row in first} | {row["id"] for row in second}
    assert paged_ids == {blocks["B2"]["id"], blocks["B3"]["id"]}
    assert blocks["B1"]["id"] not in paged_ids


def test_block_listing_unfiltered_read_returns_every_block_under_the_default_limit(
    api, epc_headers
):
    """Dropping the status filter widens the population back to all three blocks.

    PRD 2.3: "Where a list endpoint also accepts domain filters — for example `project_id`, `yard_zone_id`, `status`, `component_type`, `severity`, `test_type`, `is_valid`, `is_apprentice`, `purpose`, `mechanical_status`, `electrical_status`, `mc_ready`, `grading_area_id`, `block_id`, `milestone_state` or `mc_readiness` — those filters combine conjunctively and are applied before pagination."

    Design: Corner/entities/block_listing_paginates_and_filters_by_mechanical_status
    """
    project, blocks = _project_with_three_blocks(api)

    rows, meta = validate_paginated(api.list_blocks(epc_headers, {"project_id": project["id"]}))

    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert {row["id"] for row in rows} == {block["id"] for block in blocks.values()}


# ---------------------------------------------------------------------------
# Not-found probes
# ---------------------------------------------------------------------------
def test_commissioning_test_read_with_unknown_id_is_not_found(api, commissioning_headers):
    """An unknown but well-formed commissioning-test id answers the entity's own 404 code.

    PRD 2.6: "Each entity kind has its own not-found code: `ERR_GRADING_AREA_NOT_FOUND`, `ERR_YARD_ZONE_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_PILE_NOT_FOUND`, `ERR_STRING_CIRCUIT_NOT_FOUND`, `ERR_SUBSTATION_NOT_FOUND`, `ERR_OUTAGE_WINDOW_NOT_FOUND`, `ERR_COMMISSIONING_TEST_NOT_FOUND`, `ERR_PUNCH_ITEM_NOT_FOUND`, `ERR_PAYROLL_WEEK_NOT_FOUND` and `ERR_LABOR_ENTRY_NOT_FOUND`, each returning HTTP 404."

    Design: Corner/entities/commissioning_test_read_with_unknown_id_returns_not_found
    """
    response = api.get_commissioning_test(NON_EXISTENT_UUID, commissioning_headers)

    error = validate_error(response, "ERR_COMMISSIONING_TEST_NOT_FOUND")
    assert isinstance(error["message"], str) and error["message"].strip() != ""
    assert response.json()["response_type"] == "error"


# ---------------------------------------------------------------------------
# Required body fields on the most heavily guarded create
# ---------------------------------------------------------------------------
def test_delivery_create_without_pallets_is_rejected_as_malformed(
    api, project, procurement_headers
):
    """A reservation that omits `pallets` is a shape failure, not a capacity failure.

    PRD 2.7: "Request shape: required body fields present, enum values inside their declared sets, unknown fields rejected, and every numeric constraint honoured — hours strictly positive, pallet counts strictly positive, ordered unit counts strictly positive, capacities strictly positive, and percentages and fractions inside their declared ranges."

    Design: Corner/entities/delivery_create_missing_required_pallets_is_rejected
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=100)
    payload = f.delivery_payload(project["id"], zone["id"], zone["version"], unit_qty=600)
    payload.pop("pallets")

    validate_error(api.create_delivery(payload, procurement_headers), "ERR_INVALID_REQUEST")

    rows, meta = validate_paginated(
        api.list_deliveries(procurement_headers, {"project_id": project["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0

    zone_after = validate_success(api.get_yard_zone(zone["id"], procurement_headers))
    assert zone_after["version"] == zone["version"]
    assert_zone_occupancy(zone_after, reserved_pallets=0, available_pallets=100)


# ---------------------------------------------------------------------------
# Delivery receipt: the two computed figures
# ---------------------------------------------------------------------------
def test_delivery_damage_ratio_is_computed_from_the_two_counted_quantities(
    api, project, procurement_headers
):
    """`damage_ratio` is derived from the receipt counts at four decimal places.

    PRD 3.3: "The system stores the two counts and the note, moves the delivery `RESERVED → ARRIVED`, and computes `damage_ratio` as `damaged_unit_qty` divided by `received_unit_qty`, rounded half up to four decimal places."

    Design: Corner/entities/delivery_damage_ratio_is_computed_and_client_input_ignored
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=100)
    delivery = reserve_delivery(
        api, project["id"], zone["id"], unit_qty=60, pallets=60
    )
    assert delivery["damage_ratio"] is None

    data = validate_success(
        api.receive_delivery(
            delivery["id"], f.receipt_payload(60, 3), procurement_headers
        )
    )

    assert data["received_unit_qty"] == 60
    assert data["damaged_unit_qty"] == 3
    assert data["damage_ratio"] == pytest.approx(0.0500, abs=0.0001)


def test_delivery_acceptance_fork_sets_accepted_units_and_keeps_the_pallets(
    api, project, procurement_headers
):
    """A damage ratio at the five-percent line accepts the shipment and holds its pallets.

    PRD 3.3: "When `damage_ratio` is at most 0.05 — five percent damage or less — the delivery moves `ARRIVED → ACCEPTED`."

    Design: Corner/entities/delivery_damage_ratio_is_computed_and_client_input_ignored
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=100)
    delivery = reserve_delivery(
        api, project["id"], zone["id"], unit_qty=60, pallets=60
    )

    data = validate_success(
        api.receive_delivery(
            delivery["id"], f.receipt_payload(60, 3), procurement_headers
        )
    )

    assert data["status"] == "ACCEPTED"
    assert data["accepted_unit_qty"] == 57

    zone_after = validate_success(api.get_yard_zone(zone["id"], procurement_headers))
    assert_zone_occupancy(zone_after, reserved_pallets=60, available_pallets=40)


# ---------------------------------------------------------------------------
# Yard zone: server-minted identity and a derived pallet ledger
# ---------------------------------------------------------------------------
def test_yard_zone_create_mints_its_own_identifier_and_first_version(
    api, project, procurement_headers
):
    """A yard-zone create mints a prefix-free UUID and lands at version 1.

    PRD 2.4: "Every resource is addressed by an `id` that the server mints as a UUID."

    Design: Corner/entities/yard_zone_system_fields_are_server_minted_and_client_input_ignored
    """
    reset_clock(api)

    data = validate_success(
        api.create_yard_zone(
            project["id"], f.yard_zone_payload(zone_code="Y1", pallet_capacity=100), procurement_headers
        ),
        expected_status=201,
    )

    assert is_valid_uuid(data["id"])
    assert "_" not in data["id"] and ":" not in data["id"]
    assert_created_fresh(data)
    assert data["zone_code"] == "Y1"
    assert data["pallet_capacity"] == 100


def test_yard_zone_pallet_ledger_starts_derived_from_its_absent_deliveries(
    api, project, procurement_headers
):
    """A fresh zone reports its whole capacity available and leaves the project alone.

    PRD 3.3: "A new zone starts with `reserved_pallets` at 0 and therefore `available_pallets` equal to its `pallet_capacity`; creating a zone changes nothing at project level and leaves the project's `version` alone."

    Design: Corner/entities/yard_zone_system_fields_are_server_minted_and_client_input_ignored
    """
    project_version_before = project["version"]

    data = validate_success(
        api.create_yard_zone(
            project["id"], f.yard_zone_payload(pallet_capacity=100), procurement_headers
        ),
        expected_status=201,
    )

    assert_zone_occupancy(data, reserved_pallets=0, available_pallets=100)
    assert read_project(api, project["id"])["version"] == project_version_before


# ---------------------------------------------------------------------------
# Punch-list item severity: a closed enum
# ---------------------------------------------------------------------------
def test_punch_item_severity_outside_the_declared_set_is_rejected(
    api, project, owner_headers
):
    """A plausible but undeclared severity value is refused as a malformed request.

    PRD 3.9: "Defects are raised by the `OwnerEngineer` as punch-list items against a project, each with a `title` describing the defect, a `category` naming the owning discipline (`MECHANICAL`, `ELECTRICAL`, `CIVIL` or `DOCUMENTATION`), a `severity` of `CRITICAL`, `MAJOR` or `MINOR`, and an `estimated_cost_cents` closure estimate of zero or more which later feeds the punch-list holdback."

    Design: Corner/entities/punch_list_item_with_invalid_enum_severity_is_rejected
    """
    payload = f.punch_list_item_payload(
        title="Combiner box label missing",
        category="ELECTRICAL",
        severity="BLOCKER",
        estimated_cost_cents=20000,
    )

    validate_error(
        api.create_punch_list_item(project["id"], payload, owner_headers),
        "ERR_INVALID_REQUEST",
    )

    after = read_project(api, project["id"])
    assert after["open_punch_item_count"] == 0
    assert after["open_critical_punch_count"] == 0


def test_punch_item_with_a_declared_severity_is_persisted_and_counted(
    api, project, owner_headers
):
    """A `CRITICAL` item is admitted at `OPEN` and lands in both project counters.

    PRD 3.9: "Raising it increments the project's `open_punch_item_count` and, when the severity is `CRITICAL`, also `open_critical_punch_count`, with the project's `version` incremented by 1."

    Design: Corner/entities/punch_list_item_with_invalid_enum_severity_is_rejected
    """
    payload = f.punch_list_item_payload(
        title="Combiner box label missing",
        category="ELECTRICAL",
        severity="CRITICAL",
        estimated_cost_cents=20000,
    )

    data = validate_success(
        api.create_punch_list_item(project["id"], payload, owner_headers),
        expected_status=201,
    )

    assert data["severity"] == "CRITICAL"
    assert data["status"] == "OPEN"

    after = read_project(api, project["id"])
    assert after["open_punch_item_count"] == 1
    assert after["open_critical_punch_count"] == 1


# ---------------------------------------------------------------------------
# Measurement intervals: append-only rows with no version of their own
# ---------------------------------------------------------------------------
def test_appended_interval_exposes_neither_updated_at_nor_version(
    api, project, commissioning_headers
):
    """An interval row carries only the two system fields its immutability allows.

    PRD 2.4: "A measurement interval belonging to a commissioning test is immutable once appended: it carries only `id` and `created_at`."

    Design: Corner/entities/test_interval_is_immutable_and_exposes_no_version_field
    """
    test = schedule_commissioning_test(api, project["id"])

    data = validate_success(
        api.create_test_interval(
            test["id"],
            f.interval_payload("2026-08-10T02:00:00Z", 900.0, 76.00),
            commissioning_headers,
        ),
        expected_status=201,
    )

    assert_versionless_interval(data)


def test_intervals_are_listed_against_the_test_they_were_appended_to(
    api, project, commissioning_headers
):
    """Each appended sampling period is stored under its own test and read back there.

    PRD 3.7: "Measurements are appended as immutable intervals, one per sampling period, each stored against the `commissioning_test_id` of the test it was appended to."

    Design: Corner/entities/test_interval_is_immutable_and_exposes_no_version_field
    """
    test = schedule_commissioning_test(api, project["id"])
    other = schedule_commissioning_test(
        api, project["id"], test_type="PERFORMANCE_RATIO"
    )
    first = validate_success(
        api.create_test_interval(
            test["id"],
            f.interval_payload("2026-08-10T02:00:00Z", 900.0, 76.00),
            commissioning_headers,
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_test_interval(
            test["id"],
            f.interval_payload("2026-08-10T02:15:00Z", 910.0, 77.00),
            commissioning_headers,
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api.list_test_intervals(test["id"], commissioning_headers)
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    for row in rows:
        assert row["commissioning_test_id"] == test["id"]
        assert_versionless_interval(row)

    other_rows, other_meta = validate_paginated(
        api.list_test_intervals(other["id"], commissioning_headers)
    )
    assert other_meta["total_count"] == 0
    assert other_rows == []


# ---------------------------------------------------------------------------
# A block's grading area must belong to the block's own project
# ---------------------------------------------------------------------------
def test_block_naming_a_grading_area_of_another_project_is_refused_as_cross_project(
    api, epc_headers
):
    """A real grading area under a second project cannot carry the first project's block.

    PRD 2.6: "A reference that resolves to a real row belonging to a different project is rejected with `ERR_CROSS_PROJECT_REFERENCE` and HTTP 422 — never with a not-found code, because the resource does exist."

    Design: Corner/entities/block_referencing_a_grading_area_of_another_project_is_rejected
    """
    home = create_project(api, name="Basin Mesa I")
    away = create_project(api, name="Basin Mesa II")
    away_area = create_grading_area(api, away["id"], area_code="A9")

    validate_error(
        api.create_block(
            home["id"], f.block_payload(away_area["id"]), epc_headers
        ),
        "ERR_CROSS_PROJECT_REFERENCE",
    )

    assert read_project(api, home["id"])["blocks_total"] == 0
    rows, meta = validate_paginated(
        api.list_blocks(epc_headers, {"project_id": home["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_block_naming_an_unknown_grading_area_is_refused_as_not_found(
    api, project, epc_headers
):
    """An unresolvable `grading_area_id` is a grading-area not-found, not a cross-project fault.

    PRD 2.6: "The grading-area code covers both grading-area-addressed endpoints and the `grading_area_id` supplied when a block is created; the block code covers both block-addressed endpoints and the optional `block_id` supplied when a punch-list item is raised."

    Design: Corner/entities/block_referencing_a_grading_area_of_another_project_is_rejected
    """
    validate_error(
        api.create_block(
            project["id"], f.block_payload(NON_EXISTENT_UUID), epc_headers
        ),
        "ERR_GRADING_AREA_NOT_FOUND",
    )

    assert read_project(api, project["id"])["blocks_total"] == 0


# ---------------------------------------------------------------------------
# A punch-list item's optional block must belong to the item's own project
# ---------------------------------------------------------------------------
def test_punch_item_naming_a_block_of_another_project_is_refused_as_cross_project(
    api, epc_headers, owner_headers
):
    """A defect cannot be pinned to a block that belongs to a different project.

    PRD 2.6: "Three references cross aggregate boundaries and each must stay inside a single project: the yard zone named by a delivery's `yard_zone_id` must have the same owning project as the delivery's `project_id`; the grading area named by a block's `grading_area_id` must belong to the project in whose path the block is created; and the block named by a punch-list item's `block_id` must belong to the project in whose path the item is raised."

    Design: Corner/entities/punch_item_block_association_is_validated_across_the_hierarchy
    """
    home = create_project(api, name="Basin Mesa I")
    away = create_project(api, name="Basin Mesa II")
    away_area = create_grading_area(api, away["id"], area_code="A9")
    away_block = create_block(api, away["id"], away_area["id"], block_code="B9")

    validate_error(
        api.create_punch_list_item(
            home["id"],
            f.punch_list_item_payload(block_id=away_block["id"]),
            owner_headers,
        ),
        "ERR_CROSS_PROJECT_REFERENCE",
    )

    assert read_project(api, home["id"])["open_punch_item_count"] == 0
    rows, meta = validate_paginated(
        api.list_punch_list_items(owner_headers, {"project_id": home["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_punch_item_block_association_is_optional_and_filterable_when_present(
    api, project, accepted_grading_area, epc_headers, owner_headers
):
    """A block of the same project is stored, and a balance-of-plant defect leaves it null.

    PRD 3.9: "An item may optionally name the `block_id` of the block it belongs to; a balance-of-plant defect leaves it null, and a block that is named must belong to the same project."

    Design: Corner/entities/punch_item_block_association_is_validated_across_the_hierarchy
    """
    block = create_block(api, project["id"], accepted_grading_area["id"])

    on_block = validate_success(
        api.create_punch_list_item(
            project["id"],
            f.punch_list_item_payload(
                title="Module clamp torque short", block_id=block["id"]
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    balance_of_plant = validate_success(
        api.create_punch_list_item(
            project["id"],
            f.punch_list_item_payload(title="Access road washout"),
            owner_headers,
        ),
        expected_status=201,
    )

    assert on_block["block_id"] == block["id"]
    assert balance_of_plant["block_id"] is None

    rows, meta = validate_paginated(
        api.list_punch_list_items(
            owner_headers, {"project_id": project["id"], "block_id": block["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [on_block["id"]]

    after = read_project(api, project["id"])
    assert after["open_punch_item_count"] == 2
    assert after["open_critical_punch_count"] == 0
