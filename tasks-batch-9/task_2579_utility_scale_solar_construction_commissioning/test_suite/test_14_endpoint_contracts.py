"""Endpoint contracts: item reads, collection filters and action endpoints.

Every test here builds its own state from scratch through the endpoints of PRD
section 4, because the harness restarts the server and wipes the database before
each individual test.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_cents,
    assert_contains_id,
    assert_excludes_id,
    assert_ids_equal,
    assert_week_totals,
    assert_zone_occupancy,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_CROSS_PROJECT_REFERENCE,
    ERR_NO_APPROVED_OUTAGE_WINDOW,
    ERR_YARD_ZONE_NOT_FOUND,
)
from test_helpers.constants import DEFAULT_LIMIT
from test_helpers.fixtures import (
    accepted_area,
    accepted_module_delivery,
    add_change_order,
    advance_substation,
    answer_outage_window,
    approved_outage_window,
    create_circuit,
    create_grading_area,
    create_payroll_week,
    create_pile,
    create_project,
    create_punch_item,
    create_substation,
    create_yard_zone,
    decide_closure,
    mech_complete_block,
    post_labor_entry,
    read_commissioning_test,
    read_payroll_week,
    read_punch_item,
    read_substation,
    read_outage_window,
    receive_delivery,
    request_outage_window,
    reserve_delivery,
    reset_clock,
    schedule_commissioning_test,
    set_clock,
    submit_closure,
    wired_circuit,
)


def test_delivery_item_read_and_filtered_collection_compose(api, procurement_headers):
    """A delivery reads back field for field, and the collection's filters compose
    while the pagination counters keep describing the filtered set.

    PRD 2.3: "`total_count` is the number of rows matching the request's filters *before* the page window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the current window."

    Design: Corner/endpoints/delivery_round_trip_across_item_and_filtered_collection_reads
    """
    project = create_project(api, name="Roundtrip Mesa")
    zone = create_yard_zone(api, project["id"], pallet_capacity=200)

    first = reserve_delivery(
        api,
        project["id"],
        zone["id"],
        unit_qty=60,
        pallets=60,
        planned_arrival_at="2026-08-03T09:00:00Z",
        inspection_note="first module set",
    )
    receipt = receive_delivery(api, first["id"], 60, 3)
    assert receipt["status"] == "ACCEPTED"

    reserved_module = reserve_delivery(
        api,
        project["id"],
        zone["id"],
        unit_qty=40,
        pallets=40,
        planned_arrival_at="2026-08-04T09:00:00Z",
    )
    assert reserved_module["status"] == "RESERVED"
    assert reserved_module["component_type"] == "MODULE"
    assert reserved_module["pallets"] == 40

    tracker = reserve_delivery(
        api,
        project["id"],
        zone["id"],
        component_type="TRACKER",
        unit_qty=50,
        pallets=50,
        planned_arrival_at="2026-08-05T09:00:00Z",
    )

    item = validate_success(api.get_delivery(reserved_module["id"], procurement_headers))
    assert item["id"] == reserved_module["id"]
    assert item["status"] == "RESERVED"
    assert item["component_type"] == "MODULE"
    assert item["unit_qty"] == 40

    rows, meta = validate_paginated(
        api.list_deliveries(
            procurement_headers,
            params={
                "project_id": project["id"],
                "component_type": "MODULE",
                "status": "RESERVED",
            },
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [reserved_module["id"]])

    rows, meta = validate_paginated(
        api.list_deliveries(
            procurement_headers,
            params={"project_id": project["id"], "component_type": "MODULE"},
        )
    )
    assert meta["total_count"] == 2
    assert_ids_equal(rows, [first["id"], reserved_module["id"]])

    rows, meta = validate_paginated(
        api.list_deliveries(
            procurement_headers,
            params={"project_id": project["id"], "status": "RESERVED"},
        )
    )
    assert meta["total_count"] == 2
    assert_ids_equal(rows, [reserved_module["id"], tracker["id"]])

    rows, meta = validate_paginated(
        api.list_deliveries(
            procurement_headers,
            params={"project_id": project["id"], "limit": 2, "offset": 0},
        )
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert len(rows) == 2


def test_delivery_resolves_its_zone_before_the_single_project_boundary(
    api, procurement_headers
):
    """An unknown yard zone is a not-found; a real zone owned by another project is
    a boundary violation; only the valid pairing moves pallets.

    PRD 2.6: "A reference that resolves to a real row belonging to a different project is rejected with `ERR_CROSS_PROJECT_REFERENCE` and HTTP 422 — never with a not-found code, because the resource does exist."

    Design: Corner/endpoints/delivery_links_a_project_and_a_yard_zone_and_rejects_a_foreign_zone
    """
    first_project = create_project(api, name="Link One")
    second_project = create_project(api, name="Link Two")
    own_zone = create_yard_zone(api, first_project["id"])
    foreign_zone = create_yard_zone(api, second_project["id"])

    validate_error(
        api.create_delivery(
            f.delivery_payload(
                first_project["id"],
                NON_EXISTENT_UUID,
                own_zone["version"],
                unit_qty=40,
                pallets=40,
            ),
            procurement_headers,
        ),
        ERR_YARD_ZONE_NOT_FOUND,
    )

    validate_error(
        api.create_delivery(
            f.delivery_payload(
                first_project["id"],
                foreign_zone["id"],
                foreign_zone["version"],
                unit_qty=40,
                pallets=40,
            ),
            procurement_headers,
        ),
        ERR_CROSS_PROJECT_REFERENCE,
    )

    created = validate_success(
        api.create_delivery(
            f.delivery_payload(
                first_project["id"],
                own_zone["id"],
                own_zone["version"],
                unit_qty=40,
                pallets=40,
            ),
            procurement_headers,
        ),
        201,
    )
    assert created["project_id"] == first_project["id"]
    assert created["yard_zone_id"] == own_zone["id"]

    linked = validate_success(api.get_yard_zone(own_zone["id"], procurement_headers))
    assert_zone_occupancy(linked, reserved_pallets=40, available_pallets=60)

    untouched = validate_success(
        api.get_yard_zone(foreign_zone["id"], procurement_headers)
    )
    assert_zone_occupancy(untouched, reserved_pallets=0, available_pallets=100)
    assert untouched["version"] == foreign_zone["version"]


def test_settlement_summary_keeps_counts_live_while_money_stays_frozen(
    api, owner_headers
):
    """Before certification the summary reports the live scope and punch counts while
    the ladder's money figures still read zero.

    PRD 3.1: "It also returns seven money and timing figures that mirror what the settlement waterfall of §3.9 froze onto the project: `delay_days`, `ld_cap_cents`, `ld_assessed_cents`, `retainage_held_cents`, `punchlist_holdback_cents` and `sc_payment_due_cents` are 0 until substantial completion has been certified, and `final_payment_cents` is 0 until final acceptance has been certified."

    Design: Corner/endpoints/settlement_summary_reports_live_counts_and_zeroed_money_before_certification
    """
    project = create_project(api, name="Settlement Flats")
    scoped = add_change_order(api, project["id"], 500000)
    assert_cents(scoped["approved_change_order_cents"], 500000, "approved_change_order_cents")

    critical = create_punch_item(
        api,
        project["id"],
        title="Grounding electrode conductor unbonded",
        category="ELECTRICAL",
        severity="CRITICAL",
        estimated_cost_cents=200000,
    )
    major = create_punch_item(
        api,
        project["id"],
        title="Tracker row misaligned",
        category="MECHANICAL",
        severity="MAJOR",
        estimated_cost_cents=100000,
    )
    minor = create_punch_item(
        api,
        project["id"],
        title="As-built redlines incomplete",
        category="DOCUMENTATION",
        severity="MINOR",
        estimated_cost_cents=50000,
    )

    opening = validate_success(api.get_settlement_summary(project["id"], owner_headers))
    assert_cents(opening["adjusted_contract_cents"], 10500000, "adjusted_contract_cents")
    assert opening["open_punch_item_count"] == 3
    assert opening["open_critical_punch_count"] == 1
    assert opening["delay_days"] == 0
    for field in (
        "ld_assessed_cents",
        "retainage_held_cents",
        "punchlist_holdback_cents",
        "sc_payment_due_cents",
        "final_payment_cents",
    ):
        assert_cents(opening[field], 0, field)
    assert opening["tax_credit_status"] == "UNDETERMINED"

    assert submit_closure(api, major["id"])["status"] == "CLOSURE_SUBMITTED"
    pending = validate_success(api.get_settlement_summary(project["id"], owner_headers))
    assert pending["open_punch_item_count"] == 3
    assert pending["open_critical_punch_count"] == 1

    assert (
        decide_closure(api, major["id"], "APPROVE", note="row realigned and resurveyed")[
            "status"
        ]
        == "CLOSED"
    )
    submit_closure(api, minor["id"], closure_evidence_ref="PHOTO-2002")
    assert (
        decide_closure(api, minor["id"], "WAIVE", note="redlines deferred to turnover")[
            "status"
        ]
        == "WAIVED"
    )

    settled = validate_success(api.get_settlement_summary(project["id"], owner_headers))
    assert_cents(settled["adjusted_contract_cents"], 10500000, "adjusted_contract_cents")
    assert settled["open_punch_item_count"] == 1
    assert settled["open_critical_punch_count"] == 1
    assert_cents(settled["sc_payment_due_cents"], 0, "sc_payment_due_cents")
    assert read_punch_item(api, critical["id"])["status"] == "OPEN"


def test_energization_is_allowed_only_inside_an_approved_window(api, utility_headers):
    """The status-advance endpoint refuses energization outside an approved backfeed
    window and records the window that authorized the advance that succeeds.

    PRD 3.6: "Before the facility may move `BACKFEED_REQUESTED → ENERGIZED`, an outage window belonging to that facility must be sitting at `APPROVED` with `purpose` `BACKFEED`, and the current logical-clock instant must fall inside that window's closed interval from `start_at` through `end_at` inclusive."

    Design: Corner/endpoints/energization_is_allowed_only_inside_an_approved_outage_window
    """
    reset_clock(api)
    project = create_project(api, name="Backfeed Basin")
    substation = create_substation(api, project["id"])

    denied = request_outage_window(
        api,
        substation["id"],
        start_at="2026-08-05T00:00:00Z",
        end_at="2026-08-05T04:00:00Z",
        purpose="BACKFEED",
    )
    assert (
        answer_outage_window(api, denied["id"], "DENY", utility_reference="SO-4460")[
            "status"
        ]
        == "DENIED"
    )
    approved = approved_outage_window(
        api,
        substation["id"],
        start_at="2026-08-10T00:00:00Z",
        end_at="2026-08-10T04:00:00Z",
        purpose="BACKFEED",
    )
    assert approved["status"] == "APPROVED"

    advance_substation(api, substation["id"], "STEEL_ERECTED", "W-1")
    advance_substation(api, substation["id"], "EQUIPMENT_SET", "W-2")
    assert (
        advance_substation(api, substation["id"], "BACKFEED_REQUESTED", "W-3")["status"]
        == "BACKFEED_REQUESTED"
    )

    energize = f.status_advance_payload("ENERGIZED", "W-4")
    validate_error(
        api.create_status_advance(substation["id"], energize, utility_headers),
        ERR_NO_APPROVED_OUTAGE_WINDOW,
    )

    set_clock(api, "2026-08-05T02:00:00Z")
    validate_error(
        api.create_status_advance(substation["id"], energize, utility_headers),
        ERR_NO_APPROVED_OUTAGE_WINDOW,
    )
    held = read_substation(api, substation["id"])
    assert held["status"] == "BACKFEED_REQUESTED"
    assert held["utility_witness_ref"] == "W-3"

    set_clock(api, "2026-08-10T02:00:00Z")
    energized = validate_success(
        api.create_status_advance(substation["id"], energize, utility_headers)
    )
    assert energized["status"] == "ENERGIZED"
    assert energized["utility_witness_ref"] == "W-4"
    assert energized["energizing_outage_window_id"] == approved["id"]
    assert read_outage_window(api, denied["id"])["status"] == "DENIED"


def test_child_collections_stay_parent_scoped_and_honor_their_own_filter(
    api,
    epc_headers,
    procurement_headers,
    civil_headers,
    foreman_headers,
    utility_headers,
    commissioning_headers,
    owner_headers,
    labor_headers,
):
    """Each child collection returns only the rows of the parent it is addressed
    through, and its own declared filter narrows that set further.

    PRD 2.3: "Where a list endpoint also accepts domain filters — for example `project_id`, `yard_zone_id`, `status`, `component_type`, `severity`, `test_type`, `is_valid`, `is_apprentice`, `purpose`, `mechanical_status`, `electrical_status`, `mc_ready`, `grading_area_id`, `block_id`, `milestone_state` or `mc_readiness` — those filters combine conjunctively and are applied before pagination."

    Design: Corner/endpoints/nested_collection_reads_are_scoped_to_their_parent_and_honor_their_own_filter
    """
    project = create_project(api, name="Scoped Ranch")
    area = accepted_area(api, project["id"], area_code="A1")
    planned_area = create_grading_area(
        api, project["id"], area_code="A2", permit_number="CGP-2026-119"
    )
    assert area["status"] == "ACCEPTED"
    assert planned_area["status"] == "PLANNED"

    zone = create_yard_zone(api, project["id"])
    accepted_module_delivery(api, project["id"], zone["id"])

    block = mech_complete_block(
        api, project["id"], area["id"], planned_pile_count=1, planned_string_count=2
    )
    assert block["mechanical_status"] == "MECH_COMPLETE"
    planned_pile = create_pile(api, block["id"], row_index=1, position_index=2)
    assert planned_pile["status"] == "PLANNED"

    wired = wired_circuit(api, block["id"], circuit_code="C1")
    assert wired["status"] == "WIRED"
    planned_circuit = create_circuit(api, block["id"], circuit_code="C2")
    assert planned_circuit["status"] == "PLANNED"

    substation = create_substation(api, project["id"])
    assert substation["status"] == "SITE_CIVIL"
    backfeed_window = approved_outage_window(
        api,
        substation["id"],
        start_at="2026-08-10T00:00:00Z",
        end_at="2026-08-10T04:00:00Z",
        purpose="BACKFEED",
    )
    switching_window = request_outage_window(
        api,
        substation["id"],
        start_at="2026-08-12T00:00:00Z",
        end_at="2026-08-12T04:00:00Z",
        purpose="SWITCHING",
    )
    assert backfeed_window["status"] == "APPROVED"
    assert switching_window["status"] == "REQUESTED"

    capacity_test = schedule_commissioning_test(
        api, project["id"], test_type="CAPACITY", scheduled_at="2026-08-11T09:00:00Z"
    )
    ratio_test = schedule_commissioning_test(
        api,
        project["id"],
        test_type="PERFORMANCE_RATIO",
        scheduled_at="2026-08-11T13:00:00Z",
    )
    assert capacity_test["status"] == "SCHEDULED"
    assert ratio_test["status"] == "SCHEDULED"
    assert read_commissioning_test(api, capacity_test["id"])["status"] == "SCHEDULED"

    block_item = create_punch_item(
        api,
        project["id"],
        title="Combiner conductor undersized",
        category="ELECTRICAL",
        severity="CRITICAL",
        estimated_cost_cents=40000,
        block_id=block["id"],
    )
    plant_item = create_punch_item(
        api,
        project["id"],
        title="Operations manual not delivered",
        category="DOCUMENTATION",
        severity="MINOR",
        estimated_cost_cents=5000,
    )
    assert plant_item["block_id"] is None

    week = create_payroll_week(api, project["id"], week_start_date="2026-07-27")
    apprentice_entry = post_labor_entry(
        api,
        week["id"],
        worker_ref="W-100",
        is_apprentice=True,
        hours=40.00,
        prevailing_rate_cents=4500,
        work_date="2026-07-29",
    )
    journeyworker_entry = post_labor_entry(
        api,
        week["id"],
        worker_ref="W-200",
        classification="IRONWORKER",
        hours=40.00,
        prevailing_rate_cents=4500,
        work_date="2026-07-30",
    )

    rows, meta = validate_paginated(
        api.list_project_grading_areas(project["id"], civil_headers)
    )
    assert meta["total_count"] == 2
    assert_ids_equal(rows, [area["id"], planned_area["id"]])
    rows, meta = validate_paginated(
        api.list_project_grading_areas(
            project["id"], civil_headers, params={"status": "ACCEPTED"}
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [area["id"]])

    rows, meta = validate_paginated(
        api.list_project_yard_zones(project["id"], procurement_headers)
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [zone["id"]])
    assert_zone_occupancy(rows[0], reserved_pallets=60, available_pallets=40)

    rows, meta = validate_paginated(
        api.list_blocks(epc_headers, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [block["id"]])
    rows, meta = validate_paginated(
        api.list_blocks(
            epc_headers,
            params={"project_id": project["id"], "grading_area_id": area["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [block["id"]])

    rows, meta = validate_paginated(api.list_block_piles(block["id"], foreman_headers))
    assert meta["total_count"] == 2
    assert_contains_id(rows, planned_pile["id"])
    rows, meta = validate_paginated(
        api.list_block_piles(block["id"], foreman_headers, params={"status": "ACCEPTED"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "ACCEPTED"
    assert_excludes_id(rows, planned_pile["id"])

    rows, meta = validate_paginated(
        api.list_block_string_circuits(block["id"], foreman_headers)
    )
    assert meta["total_count"] == 2
    assert_ids_equal(rows, [wired["id"], planned_circuit["id"]])
    rows, meta = validate_paginated(
        api.list_block_string_circuits(
            block["id"], foreman_headers, params={"status": "WIRED"}
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [wired["id"]])

    rows, meta = validate_paginated(
        api.list_project_substations(project["id"], utility_headers)
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [substation["id"]])
    rows, meta = validate_paginated(
        api.list_project_substations(
            project["id"], utility_headers, params={"status": "SITE_CIVIL"}
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [substation["id"]])

    rows, meta = validate_paginated(
        api.list_substation_outage_windows(substation["id"], utility_headers)
    )
    assert meta["total_count"] == 2
    assert_ids_equal(rows, [backfeed_window["id"], switching_window["id"]])
    rows, meta = validate_paginated(
        api.list_substation_outage_windows(
            substation["id"], utility_headers, params={"purpose": "BACKFEED"}
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [backfeed_window["id"]])
    rows, meta = validate_paginated(
        api.list_substation_outage_windows(
            substation["id"], utility_headers, params={"status": "REQUESTED"}
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [switching_window["id"]])

    rows, meta = validate_paginated(
        api.list_project_commissioning_tests(project["id"], commissioning_headers)
    )
    assert meta["total_count"] == 2
    assert_ids_equal(rows, [capacity_test["id"], ratio_test["id"]])
    rows, meta = validate_paginated(
        api.list_project_commissioning_tests(
            project["id"], commissioning_headers, params={"test_type": "CAPACITY"}
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [capacity_test["id"]])

    rows, meta = validate_paginated(
        api.list_punch_list_items(owner_headers, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == DEFAULT_LIMIT
    assert_ids_equal(rows, [block_item["id"], plant_item["id"]])
    rows, meta = validate_paginated(
        api.list_punch_list_items(
            owner_headers,
            params={"project_id": project["id"], "block_id": block["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [block_item["id"]])

    rows, meta = validate_paginated(
        api.list_project_payroll_weeks(project["id"], labor_headers)
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [week["id"]])
    assert rows[0]["status"] == "OPEN"

    rows, meta = validate_paginated(
        api.list_week_labor_entries(week["id"], labor_headers)
    )
    assert meta["total_count"] == 2
    assert_ids_equal(rows, [apprentice_entry["id"], journeyworker_entry["id"]])
    rows, meta = validate_paginated(
        api.list_week_labor_entries(
            week["id"], labor_headers, params={"is_apprentice": "true"}
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [apprentice_entry["id"]])

    ledger = read_payroll_week(api, week["id"])
    assert ledger["entry_count"] == 2
    assert_week_totals(
        ledger,
        total_hours=80.00,
        journeyworker_hours=40.00,
        apprentice_hours=40.00,
        apprentice_pct=50.00,
    )
