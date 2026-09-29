"""
Cross-cutting layers: the OCC token, filtered paging windows and derived counters.

Every test builds its own world from scratch through declared endpoints — the harness
restarts the API with an empty database before each test — and sets the logical clock
explicitly whenever the scenario names an instant.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    DEFAULT_LIMIT,
    ERR_STALE_CONTRACT_VERSION,
    SERVICE_COORDINATOR,
    arrive_call,
    assert_created_at_ascending,
    assert_fields,
    assert_money,
    assert_pagination_meta,
    assert_part_inventory_identity,
    assert_parts_allowance_identity,
    assert_technician_capacity_identity,
    assert_two_decimals,
    build_fleet,
    call_cancel_payload,
    call_on_site,
    checklist_item,
    checklist_result_payload,
    contract_version,
    credit_reconciliation_payload,
    dispatch_call,
    event_for_call,
    expected_pm_compliance_pct,
    get_success_data,
    new_equipment,
    new_part,
    open_call,
    place_hold,
    read_club,
    read_contract,
    read_part,
    read_technician,
    read_visit,
    renewal_quote_payload,
    resolve_payload,
    rows_of,
    schedule_visit,
    set_clock,
    start_visit,
    technician_headers,
    validate_error,
    validate_paginated,
)


def test_reconciliation_and_quoting_both_refuse_a_version_the_contract_has_left_behind(api):
    """
    The two version-guarded writes each demand the live token, and each advances it.

    PRD: "In each case the request body must carry a non-optional field named
    `expected_contract_version`, holding the `version` value the client last observed on
    the contract it is about to write."

    Design: Corner/cross_cutting_complexity_layers/both_occ_guarded_writes_demand_the_contracts_current_version
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-OCC-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[{}],
    )
    contract_id = fleet["contract_id"]
    t1 = fleet["technician_ids"][0]

    call = call_on_site(
        api, contract_id, fleet["equipment_ids"][0], t1, "2026-08-15T08:00:00Z"
    )
    set_clock(api, "2026-08-15T14:00:00Z")
    get_success_data(
        api.resolve_service_call(call["id"], resolve_payload(), technician_headers(t1))
    )
    closed = event_for_call(api, call["id"])
    assert_fields(closed, status="CLOSED", period_key="2026-08", downtime_minutes=360)
    assert_money(closed["provisional_credit_cents"], 4800, "provisional credit")

    # A reconciliation one version behind the contract is turned away.
    live = contract_version(api, contract_id)
    stale = api.reconcile_credits(
        contract_id, credit_reconciliation_payload("2026-08", live - 1), CONTRACT_ADMIN
    )
    assert stale.status_code == 412
    validate_error(stale, ERR_STALE_CONTRACT_VERSION, 412)
    assert_fields(event_for_call(api, call["id"]), status="CLOSED")
    before = read_contract(api, contract_id)
    assert_money(before["credit_accrued_cents"], 0, "accrued credit after a refused run")
    assert_fields(before, version=live, last_reconciled_period_key=None)

    # The live token settles the period and leaves the token one higher.
    run = get_success_data(
        api.reconcile_credits(
            contract_id, credit_reconciliation_payload("2026-08", live), CONTRACT_ADMIN
        )
    )
    assert_fields(run, period_key="2026-08", reconciled_event_count=1)
    assert_money(run["posted_credit_cents"], 4800, "posted credit")
    assert_money(run["forgone_credit_cents"], 0, "forgone credit")
    assert run["contract_version"] == live + 1
    settled = read_contract(api, contract_id)
    assert_fields(settled, version=live + 1, last_reconciled_period_key="2026-08")
    assert_money(settled["credit_accrued_cents"], 4800, "accrued credit")

    # The token the client held a moment ago is now stale for the second guarded write.
    stale_quote = api.create_renewal_quote(
        contract_id, renewal_quote_payload(live), CONTRACT_ADMIN
    )
    assert stale_quote.status_code == 412
    validate_error(stale_quote, ERR_STALE_CONTRACT_VERSION, 412)
    _quotes, quotes_meta = validate_paginated(
        api.list_renewal_quotes(CONTRACT_ADMIN, contract_id=contract_id)
    )
    assert_pagination_meta(quotes_meta, DEFAULT_LIMIT, 0, 0, False)
    assert_fields(read_contract(api, contract_id), status="ACTIVE", version=live + 1)

    # Re-reading the contract in between is what makes the second write legal.
    refreshed = contract_version(api, contract_id)
    assert refreshed == live + 1
    quote = get_success_data(
        api.create_renewal_quote(
            contract_id, renewal_quote_payload(refreshed), CONTRACT_ADMIN
        ),
        201,
    )
    assert_fields(
        quote,
        status="ISSUED",
        contract_id=contract_id,
        floor_applied=True,
        cap_applied=False,
    )
    assert_money(quote["quoted_base_cents"], 120000, "quoted base")
    assert_money(quote["parts_surcharge_cents"], 21600, "parts surcharge")
    assert_money(quote["subtotal_cents"], 141600, "subtotal")
    assert_money(quote["compliance_discount_cents"], 7080, "compliance discount")
    assert_money(quote["quoted_annual_cents"], 225000, "quoted annual")
    quoted = read_contract(api, contract_id)
    assert_fields(quoted, status="RENEWAL_QUOTED", version=refreshed + 1)


def test_a_filtered_call_list_pages_over_the_filtered_total_not_the_whole_table(api):
    """
    total_count counts the rows the filters matched, and has_more looks only at those rows.

    PRD: "The `meta` object of every list response carries `limit` (the page size actually
    applied), `offset` (the starting position actually applied), `total_count` (the number
    of rows matching the filters before pagination) and `has_more` (`true` when rows
    matching the filters remain beyond the current page)."

    Design: Corner/cross_cutting_complexity_layers/filtered_call_lists_page_over_the_filtered_total_not_the_table
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-PG-1", "SN-PG-2", "SN-PG-3", "SN-PG-4", "SN-PG-5"],
        equipment_kwargs={"initial_usage_hours": 500},
    )
    contract_id = fleet["contract_id"]
    e1, e2, e3, e4, e5 = fleet["equipment_ids"]
    manager = fleet["manager"]

    c1 = open_call(api, contract_id, e1, severity="MAJOR", symptom_code="BELT_NOISE")
    c2 = open_call(api, contract_id, e2, severity="MINOR", symptom_code="CONSOLE_DIM")
    c3 = open_call(api, contract_id, e3, severity="MAJOR", symptom_code="BELT_FRAY")
    c4 = open_call(api, contract_id, e4, severity="CRITICAL", symptom_code="MOTOR_DEAD")
    c5 = open_call(api, contract_id, e5, severity="MAJOR", symptom_code="ROLLER_WEAR")

    # The unfiltered page over the same contract sees all five.
    every_call, every_meta = validate_paginated(
        api.list_service_calls(manager, contract_id=contract_id)
    )
    assert_pagination_meta(every_meta, DEFAULT_LIMIT, 0, 5, False)
    assert_created_at_ascending(every_call)
    assert [row["id"] for row in every_call] == [
        c1["id"],
        c2["id"],
        c3["id"],
        c4["id"],
        c5["id"],
    ]

    # The severity filter narrows the total the pages are measured against.
    majors, majors_meta = validate_paginated(
        api.list_service_calls(manager, contract_id=contract_id, severity="MAJOR")
    )
    assert_pagination_meta(majors_meta, DEFAULT_LIMIT, 0, 3, False)
    assert [row["id"] for row in majors] == [c1["id"], c3["id"], c5["id"]]

    first_page, first_meta = validate_paginated(
        api.list_service_calls(
            manager, contract_id=contract_id, severity="MAJOR", limit=2, offset=0
        )
    )
    assert_pagination_meta(first_meta, 2, 0, 3, True)
    assert [row["id"] for row in first_page] == [c1["id"], c3["id"]]

    last_page, last_meta = validate_paginated(
        api.list_service_calls(
            manager, contract_id=contract_id, severity="MAJOR", limit=2, offset=2
        )
    )
    assert_pagination_meta(last_meta, 2, 2, 3, False)
    assert [row["id"] for row in last_page] == [c5["id"]]

    past_end, past_meta = validate_paginated(
        api.list_service_calls(
            manager, contract_id=contract_id, severity="MAJOR", limit=2, offset=4
        )
    )
    assert_pagination_meta(past_meta, 2, 4, 3, False)
    assert past_end == [], f"a window past the filtered total is empty, got {past_end}"

    # Filters combine conjunctively, and the totals follow a live change.
    open_majors, open_majors_meta = validate_paginated(
        api.list_service_calls(
            manager, contract_id=contract_id, severity="MAJOR", status="OPEN"
        )
    )
    assert_pagination_meta(open_majors_meta, DEFAULT_LIMIT, 0, 3, False)
    assert len(open_majors) == 3

    get_success_data(
        api.cancel_service_call(
            c3["id"], call_cancel_payload("DUPLICATE_REPORT"), SERVICE_COORDINATOR
        )
    )
    still_open, still_open_meta = validate_paginated(
        api.list_service_calls(
            manager, contract_id=contract_id, severity="MAJOR", status="OPEN"
        )
    )
    assert_pagination_meta(still_open_meta, DEFAULT_LIMIT, 0, 2, False)
    assert [row["id"] for row in still_open] == [c1["id"], c5["id"]]
    cancelled, cancelled_meta = validate_paginated(
        api.list_service_calls(manager, contract_id=contract_id, status="CANCELLED")
    )
    assert_pagination_meta(cancelled_meta, DEFAULT_LIMIT, 0, 1, False)
    assert cancelled[0]["id"] == c3["id"]
    _all_majors, all_majors_meta = validate_paginated(
        api.list_service_calls(manager, contract_id=contract_id, severity="MAJOR")
    )
    assert_pagination_meta(all_majors_meta, DEFAULT_LIMIT, 0, 3, False)


def test_each_derived_counter_agrees_with_the_rows_it_is_derived_from(api):
    """
    Fleet counters, compliance, the allowance and the stock buckets each rebuild from
    their own source rows inside the request that changed them.

    PRD: "Club-level counters, machine condition, contract-level compliance and credit
    totals and the renewal-risk classification are all *derived*, and they are refreshed
    synchronously inside the same request that changed their inputs."

    Design: Corner/cross_cutting_complexity_layers/every_derived_counter_is_rebuilt_from_its_own_source_rows
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T06:00:00Z",
        model_kwargs={
            "checklist_template": [
                checklist_item("BELT_TENSION", consumable=True),
                checklist_item("EMERGENCY_STOP", is_safety_critical=True),
            ]
        },
        serials=["SN-DC-1", "SN-DC-2"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[{}],
    )
    club_id = fleet["club_id"]
    contract_id = fleet["contract_id"]
    e1, e2 = fleet["equipment_ids"]
    t1 = fleet["technician_ids"][0]
    belt = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-STD",
        category="WEAR",
        unit_price_cents=8000,
        initial_on_hand_qty=5,
    )
    assert_fields(read_club(api, club_id), covered_unit_count=2, open_safety_lockout_count=0)

    # One visit is completed and one is missed, which is the whole compliance history.
    kept = schedule_visit(
        api, contract_id, e1, "2026-08-15T07:00:00Z", "2026-08-15T09:00:00Z", t1
    )
    skipped = schedule_visit(
        api, contract_id, e2, "2026-08-15T10:00:00Z", "2026-08-15T12:00:00Z", t1
    )
    set_clock(api, "2026-08-15T07:10:00Z")
    start_visit(api, kept["id"], t1)
    get_success_data(
        api.record_checklist_result(
            kept["id"],
            checklist_result_payload("BELT_TENSION", consumable_replaced=True),
            technician_headers(t1),
        )
    )
    get_success_data(
        api.record_checklist_result(
            kept["id"], checklist_result_payload("EMERGENCY_STOP"), technician_headers(t1)
        )
    )
    get_success_data(api.complete_visit(kept["id"], technician_headers(t1)))
    assert_fields(read_visit(api, kept["id"]), visit_status="COMPLETED")
    halfway = read_contract(api, contract_id)
    assert_fields(halfway, pm_visits_completed_count=1, pm_visits_missed_count=0)
    assert_two_decimals(halfway["pm_compliance_pct"], 100, "pm_compliance_pct")

    set_clock(api, "2026-08-15T12:05:00Z")
    get_success_data(api.mark_visit_missed(skipped["id"], SERVICE_COORDINATOR))
    after_miss = read_contract(api, contract_id)
    assert_fields(after_miss, pm_visits_completed_count=1, pm_visits_missed_count=1)
    assert_two_decimals(
        after_miss["pm_compliance_pct"], expected_pm_compliance_pct(1, 1), "pm_compliance_pct"
    )

    # One short call draws on the allowance and moves stock between buckets.
    set_clock(api, "2026-08-15T13:00:00Z")
    call = open_call(api, contract_id, e2, severity="MINOR", symptom_code="BELT_FRAY")
    dispatch_call(api, call["id"], "2026-08-15T13:00:00Z", t1)
    arrive_call(api, call["id"], t1)
    order = place_hold(api, call["id"], t1, belt["id"], 2, "NEW")
    assert_fields(order, status="ALLOCATED", qty=2, source="NEW")
    assert_money(order["list_total_cents"], 16000, "list total")
    assert_money(order["allowance_draw_cents"], 16000, "allowance draw")
    assert_money(order["club_billable_cents"], 0, "club billable")
    assert_fields(read_part(api, belt["id"]), on_hand_qty=3, allocated_qty=2)
    drawn = read_contract(api, contract_id)
    assert_money(drawn["parts_allowance_total_cents"], 500000, "allowance total")
    assert_money(drawn["parts_allowance_remaining_cents"], 484000, "allowance remaining")

    get_success_data(api.install_part_order(order["id"], technician_headers(t1)))
    assert_fields(read_part(api, belt["id"]), on_hand_qty=3, allocated_qty=0, refurb_on_hand_qty=0)
    get_success_data(api.resume_service_call(call["id"], technician_headers(t1)))
    set_clock(api, "2026-08-15T14:00:00Z")
    get_success_data(
        api.resolve_service_call(call["id"], resolve_payload(), technician_headers(t1))
    )
    closed = event_for_call(api, call["id"])
    assert_fields(closed, status="CLOSED", downtime_minutes=60)
    assert_money(closed["provisional_credit_cents"], 0, "provisional credit inside grace")

    # A new machine moves the club counter and the contract roll-ups with it.
    third = new_equipment(
        api,
        club_id,
        fleet["model_id"],
        serial_number="SN-DC-3",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    assert_fields(read_club(api, club_id), covered_unit_count=3, open_safety_lockout_count=0)
    assert third["support_status"] == "SUPPORTED"

    # Every counter still equals the sum of its own source rows.
    final_contract = read_contract(api, contract_id)
    assert_money(final_contract["credit_provisional_cents"], 0, "provisional ledger")
    assert_money(final_contract["credit_accrued_cents"], 0, "accrued ledger")
    assert_fields(
        final_contract,
        replacement_candidate_count=0,
        obsolete_unit_count=0,
        fleet_renewal_risk="LOW",
    )
    orders = rows_of(api.list_part_orders(CONTRACT_ADMIN, part_id=belt["id"]))
    assert_parts_allowance_identity(final_contract, orders)
    assert_part_inventory_identity(read_part(api, belt["id"]), orders)
    assert_technician_capacity_identity(
        read_technician(api, t1),
        rows_of(api.list_technician_assignments(CONTRACT_ADMIN, technician_id=t1)),
    )
