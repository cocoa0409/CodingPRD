"""Corner coverage: endpoint behaviors — generate-lines atomic failure and
idempotent re-skip, the program summary rollup read, and pinned work-order
list ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    api_client,
    create_account,
    create_batch,
    create_route,
    dispatch_and_complete,
    find_salvage_item_for_pole,
    generate_lines,
    get_program,
    setup_cleared_pole,
    setup_effective_rate_schedule,
    setup_program_district_crew,
    setup_released_route,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]


def test_generate_lines_phases_and_idempotent_reskip(api):
    """PRD section 3.5: "If any eligible pole's ownership class has no covering
    schedule — one EFFECTIVE or SUPERSEDED whose half-open window covers the
    period's first day — the run fails atomically, creating nothing, with
    ERR_NO_EFFECTIVE_RATE_SCHEDULE"; "Line generation sweeps the poles of the
    account's district and ownership class ... creating one ESTIMATED REGULAR
    billing line per pole for current_period, skipping any pole that already
    holds a non-SUPERSEDED REGULAR line for the period; the response reports
    created_count and skipped_count."

    Design: Corner/endpoints/ep_generate_lines_phases_and_idempotent_reskip
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    setup_cleared_pole(program, district, crew, pole_number="GN-1",
                       ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    acct = create_account(district["id"], "UTILITY_OWNED", account_number="AC-U")

    # no rate schedule exists: the run fails atomically
    resp = api.generate_lines(acct["id"], BA)
    validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_RATE_SCHEDULE, expected_status=422)
    resp = api.list_billing_lines(BA, params={"account_id": acct["id"]})
    assert resp.json()["meta"]["total_count"] == 0

    setup_effective_rate_schedule(program["id"], "UTILITY_OWNED")
    first = generate_lines(acct["id"])
    assert first["created_count"] == 1 and first["skipped_count"] == 0

    # second identical call creates nothing and skips the existing line
    second = generate_lines(acct["id"])
    assert second["created_count"] == 0 and second["skipped_count"] == 1
    from test_helpers import get_account
    assert get_account(acct["id"])["current_period_estimated_cents"] == 1800


def test_program_summary_rollup_read(api):
    """PRD section 3.1: "A program summary read returns the live rollups
    budget_balance_cents, current_billing_run_estimated_cents,
    converted_pole_count, pending_salvage_item_count, and status;
    converted_pole_count counts the program's poles whose led_in_service_date
    is set, and pending_salvage_item_count counts salvage items sitting in the
    unbatched pool."

    Design: Corner/endpoints/ep_program_summary_rollup_read
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    p1 = setup_cleared_pole(program, district, crew, pole_number="SM-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    p2 = setup_cleared_pole(program, district, crew, pole_number="SM-2",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [p1, p2], start="2026-08-02", end="2026-08-02")
    for wo in wos:
        dispatch_and_complete(wo["id"], crew["id"], wattage=90, cct=2700,
                              shielding="FULL_CUTOFF")
    it1 = find_salvage_item_for_pole(p1["id"])
    it2 = find_salvage_item_for_pole(p2["id"])

    resp = api.get_program_summary(program["id"], PM)
    summary = validate_success(resp)
    assert summary["converted_pole_count"] == 2
    assert summary["pending_salvage_item_count"] == 2
    assert summary["budget_balance_cents"] == 9991000  # 10000000 - 2 x 4500
    assert summary["current_billing_run_estimated_cents"] == 0  # no accounts exist

    # batching both items reconciles the pending pool without any recompute call
    batch = create_batch(program["id"], batch_label="B-S")
    for item in (it1, it2):
        resp = api.add_salvage_item(
            batch["id"], {"salvage_item_id": item["id"], "weight_lbs": 10.0}, PM)
        validate_success(resp)
    resp = api.get_program_summary(program["id"], PM)
    summary2 = validate_success(resp)
    assert summary2["pending_salvage_item_count"] == 0
    assert summary2["current_billing_run_estimated_cents"] == 0


def test_work_orders_sorted_by_stop_sequence(api):
    """PRD section 3.4: "The work-order listing filters by `route_id`,
    `pole_id`, `crew_id`, `stop_id`, `ticket_id`, `execution_status`, and
    `qc_status`, and orders by route `window_start_date` ascending, then stop
    `sequence_number` ascending, then `created_at` ascending"; PRD section
    3.3: "orders stops by route creation, then `sequence_number` ascending
    within each route."

    Design: Corner/endpoints/ep_work_orders_sorted_by_sequence
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    q1 = setup_cleared_pole(program, district, crew, pole_number="SO-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    q2 = setup_cleared_pole(program, district, crew, pole_number="SO-2",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    q3 = setup_cleared_pole(program, district, crew, pole_number="SO-3",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route = create_route(district["id"], crew["id"], start="2026-08-03", end="2026-08-03")
    # add stops OUT of sequence order: 2, then 1, then 3
    add_stop(route["id"], q2["id"], 2, difficulty_class="STANDARD")
    add_stop(route["id"], q1["id"], 1, difficulty_class="STANDARD")
    add_stop(route["id"], q3["id"], 3, difficulty_class="STANDARD")
    resp = api.release_route(route["id"], PM)
    validate_success(resp)

    resp = api.list_stops(PM, params={"route_id": route["id"]})
    stops = resp.json()["data"]
    assert [s["sequence_number"] for s in stops] == [1, 2, 3]

    resp = api.list_work_orders(PM, params={"route_id": route["id"]})
    wos = resp.json()["data"]
    assert len(wos) == 3
    # work orders align with the same sequence order via their stop linkage
    stop_seq_by_id = {s["id"]: s["sequence_number"] for s in stops}
    assert [stop_seq_by_id[wo["stop_id"]] for wo in wos] == [1, 2, 3]
    assert wos[0]["pole_id"] == q1["id"]
    assert wos[1]["pole_id"] == q2["id"]
    assert wos[2]["pole_id"] == q3["id"]
