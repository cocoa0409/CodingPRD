"""Endpoint-contract corners of the Solar Reroof Coordination API.

Every test starts against an empty database with the logical clock reading
2026-08-01T00:00:00Z, and builds all of its preconditions from scratch.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    COORD,
    add_circuit,
    add_window,
    add_unit,
    api_client,
    assert_array_circuit,
    assert_credit_ledger_identity,
    assert_sourcing_order,
    assert_storage_bin,
    assert_work_window,
    collect_all_consents,
    create_array_circuit_payload,
    create_core_parties,
    create_project,
    create_sourcing_order_payload,
    create_storage_bin_payload,
    deenergize_circuit,
    drive_window,
    grade_unit,
    is_iso8601_timestamp,
    make_solar_contractor_headers,
    make_solar_owner_headers,
    make_system_owner_headers,
    refresh_project,
    remove_unit,
    set_clock,
    setup_authorized_project,
    setup_deenergized_project,
    store_unit,
    validate_error,
    validate_paginated,
    validate_success,
)

EPOCH_INSTANT = "2026-08-01T00:00:00"


def _assert_instant(actual, expected_instant, field):
    """Compare a stamped instant against an expected UTC instant, ignoring millis."""
    assert actual is not None, f"{field} must be stamped, got null"
    assert is_iso8601_timestamp(actual), f"{field} is not an ISO 8601 UTC instant: {actual}"
    normalized = actual.replace("Z", "").split(".")[0]
    assert normalized == expected_instant, (
        f"{field} should be {expected_instant}Z, got {actual}"
    )


def _setup_two_projects_with_damaged_removed_units():
    """Two HOST_OWNED projects sharing parties, each with one DAMAGED, REMOVED panel."""
    parties = create_core_parties()
    projects = {}
    for key, address in (("p1", "77 Ocotillo Ln, Chandler AZ"), ("p2", "81 Ocotillo Ln, Chandler AZ")):
        projects[key] = create_project(
            parties,
            ownership_model="HOST_OWNED",
            site_address=address,
            system_dc_kw=6.0,
            baseline_daily_kwh=30.0,
            downtime_days_estimated=4,
            upgrade_budget_cents=2000000,
        )
        collect_all_consents(projects[key], parties)

    crew_id = parties["crew"]["id"]
    circuits = {}
    units = {}
    for key, project in projects.items():
        circuit = add_circuit(project["id"], circuit_label="A1", module_count=1, dc_kw=0.41)
        unit = add_unit(
            project["id"],
            circuit["id"],
            crew_id,
            serial_number="SN-0001",
            rated_watts=410,
        )
        deenergize_circuit(circuit["id"], crew_id, True)
        remove_unit(unit["id"], crew_id)
        grade_unit(unit["id"], crew_id, "DAMAGED", "RETAIN")
        circuits[key] = circuit
        units[key] = unit

    return {"parties": parties, "projects": projects, "circuits": circuits, "units": units}


def test_circuit_and_bin_create_read_and_list_round_trip():
    """Nested creates and flat single reads resolve to the same circuit and bin rows.

    PRD §4: "Endpoints that bring a new, distinct resource into existence — a party, a
    jurisdiction, a project, a consent request, a circuit, a bin, a hardware unit, a deck
    finding, a permit application, an inspection booking, a crew window, a rescheduled
    replacement window, or a sourcing order — answer `201 Created`."
    PRD §3.4: "A new circuit starts with `status` `ENERGIZED`, `interlock_verified` false,
    and `isolated_at` and `reenergized_at` both absent."
    PRD §3.5: "A bin's `occupied_slots` starts at zero and is thereafter always the count
    of hardware units whose `storage_bin_id` is that bin **and** whose `handling_status`
    is exactly `STORED`."
    PRD §3.4: "That advance requires the project's `phase` to be `AUTHORIZED`, the count
    of the project's circuits whose `status` is not `ISOLATED` to be zero, and the project
    to have at least one circuit at all."

    Design: Corner/endpoints/corner_circuit_and_bin_create_read_and_filtered_list_round_trip
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_authorized_project(
        ownership_model="HOST_OWNED",
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2000000,
    )
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]

    c1 = validate_success(
        api_client.create_array_circuit(
            project_id,
            create_array_circuit_payload(circuit_label="A1", module_count=12, dc_kw=4.92),
            COORD,
        ),
        201,
    )
    c2 = validate_success(
        api_client.create_array_circuit(
            project_id,
            create_array_circuit_payload(circuit_label="B1", module_count=6, dc_kw=2.46),
            COORD,
        ),
        201,
    )
    bin1 = validate_success(
        api_client.create_storage_bin(
            project_id,
            create_storage_bin_payload(
                bin_label="BIN-1", capacity_slots=6, climate_controlled=True
            ),
            COORD,
        ),
        201,
    )

    deenergize_circuit(
        c1["id"], crew_id, True, isolation_note="AC disconnect locked out, tag ST-114"
    )

    # Flat single read of the circuit that was never touched.
    c2_read = validate_success(
        api_client.get_array_circuit(c2["id"], make_solar_contractor_headers(crew_id)), 200
    )
    assert_array_circuit(c2_read)
    assert c2_read["id"] == c2["id"], "flat read must resolve the nested-created circuit"
    assert c2_read["circuit_label"] == "B1", c2_read["circuit_label"]
    assert c2_read["module_count"] == 6, c2_read["module_count"]
    assert c2_read["dc_kw"] == pytest.approx(2.46, abs=0.01), c2_read["dc_kw"]
    assert c2_read["project_id"] == project_id, c2_read["project_id"]
    assert c2_read["status"] == "ENERGIZED", c2_read["status"]
    assert c2_read["interlock_verified"] is False, c2_read["interlock_verified"]
    assert c2_read.get("isolation_note") is None, c2_read.get("isolation_note")
    assert c2_read["version"] == 1, c2_read["version"]

    # The project's own circuit collection carries both rows.
    rows, meta = validate_paginated(
        api_client.list_project_array_circuits(project_id, COORD)
    )
    assert meta["total_count"] == 2, meta
    assert {row["id"] for row in rows} == {c1["id"], c2["id"]}, rows

    isolated_rows, _ = validate_paginated(
        api_client.list_project_array_circuits(project_id, COORD, params={"status": "ISOLATED"})
    )
    assert c1["id"] in {row["id"] for row in isolated_rows}, (
        "the isolated circuit must be listed under its project"
    )

    c1_read = validate_success(api_client.get_array_circuit(c1["id"], COORD), 200)
    assert c1_read["status"] == "ISOLATED", c1_read["status"]
    assert c1_read["interlock_verified"] is True, c1_read["interlock_verified"]
    assert c1_read["isolation_note"] == "AC disconnect locked out, tag ST-114", (
        c1_read["isolation_note"]
    )
    _assert_instant(c1_read["isolated_at"], EPOCH_INSTANT, "ArrayCircuit.isolated_at")

    bin_read = validate_success(api_client.get_storage_bin(bin1["id"], COORD), 200)
    assert_storage_bin(bin_read)
    assert bin_read["bin_label"] == "BIN-1", bin_read["bin_label"]
    assert bin_read["capacity_slots"] == 6, bin_read["capacity_slots"]
    assert bin_read["climate_controlled"] is True, bin_read["climate_controlled"]
    assert set(bin_read["accepts_unit_types"]) == {"PANEL", "OPTIMIZER"}, (
        bin_read["accepts_unit_types"]
    )
    assert bin_read["occupied_slots"] == 0, bin_read["occupied_slots"]

    project = refresh_project(project_id)
    assert project["phase"] == "AUTHORIZED", (
        "the project cannot reach DEENERGIZED while one circuit is still ENERGIZED, "
        f"got phase {project['phase']}"
    )


def test_exact_replacement_order_is_auto_approved_and_receipt_rewrites_the_unit():
    """An EXACT sourcing order is born APPROVED and its receipt overwrites the unit.

    PRD §3.8: "An `EXACT` match is `APPROVED` outright."
    PRD §3.8: "On success the order's `status` becomes `RECEIVED` and `received_at` is
    stamped with the current instant."
    PRD §3.8: "The target unit's condition dimension moves `DAMAGED → REPLACED`, and its
    `manufacturer`, `model_code`, `rated_watts` and `serial_number` are all overwritten
    from the order's offered values and received serial."
    PRD §3.8: "The unit's `handling_status` is untouched by receipt — a stored unit stays
    stored."

    Design: Corner/endpoints/corner_exact_replacement_order_is_auto_approved_and_receipt_rewrites_the_unit
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_deenergized_project(
        ownership_model="HOST_OWNED",
        circuit_count=1,
        unit_count=1,
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2000000,
    )
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    unit = ctx["units"][0]

    storage_bin = validate_success(
        api_client.create_storage_bin(
            project_id,
            create_storage_bin_payload(bin_label="BIN-1", capacity_slots=2),
            COORD,
        ),
        201,
    )
    remove_unit(unit["id"], crew_id)
    grade_unit(
        unit["id"],
        crew_id,
        "DAMAGED",
        "RETAIN",
        damage_note="cell crack across two strings",
    )
    store_unit(unit["id"], storage_bin["id"], crew_id)

    version = refresh_project(project_id)["version"]
    order = validate_success(
        api_client.create_sourcing_order(
            create_sourcing_order_payload(
                project_id,
                unit["id"],
                version,
                requested_model_code="MS-410",
                offered_manufacturer="Meridian Solar",
                offered_model_code="MS-410",
                offered_rated_watts=410,
                unit_cost_cents=24500,
            ),
            COORD,
        ),
        201,
    )
    assert_sourcing_order(order)
    assert order["match_class"] == "EXACT", order["match_class"]
    assert order["watt_delta_pct"] == pytest.approx(0.0, abs=0.01), order["watt_delta_pct"]
    assert order["tolerance_pct"] == pytest.approx(3.0, abs=0.01), order["tolerance_pct"]
    assert order["status"] == "APPROVED", (
        f"an EXACT match is APPROVED outright, got {order['status']}"
    )

    received = validate_success(
        api_client.receive_sourcing_order(
            order["id"], {"received_serial_number": "SN-7001"}, COORD
        ),
        200,
    )
    assert received["status"] == "RECEIVED", received["status"]
    _assert_instant(received["received_at"], EPOCH_INSTANT, "SourcingOrder.received_at")
    assert received.get("review_note") is None, received.get("review_note")

    unit_after = validate_success(api_client.get_hardware_unit(unit["id"], COORD), 200)
    assert unit_after["condition_grade"] == "REPLACED", unit_after["condition_grade"]
    assert unit_after["serial_number"] == "SN-7001", unit_after["serial_number"]
    assert unit_after["manufacturer"] == "Meridian Solar", unit_after["manufacturer"]
    assert unit_after["model_code"] == "MS-410", unit_after["model_code"]
    assert unit_after["rated_watts"] == 410, unit_after["rated_watts"]
    assert unit_after["handling_status"] == "STORED", (
        f"receipt must not touch the handling dimension, got {unit_after['handling_status']}"
    )
    assert unit_after["damage_note"] == "cell crack across two strings", (
        unit_after.get("damage_note")
    )

    project = refresh_project(project_id)
    assert project["damaged_unit_count"] == 0, project["damaged_unit_count"]
    assert project["warranty_notice_status"] == "NOT_REQUIRED", (
        "a HOST_OWNED project has no notice to reset, got "
        f"{project['warranty_notice_status']}"
    )


def test_sourcing_order_links_a_project_and_one_of_its_own_units():
    """A sourcing order's project_id and hardware_unit_id must name the same project.

    PRD §2.5: "Three places must refuse it with `ERR_CROSS_PROJECT_REFERENCE` (HTTP 422):
    registering a hardware unit whose `array_circuit_id` belongs to a different project
    than the one in the path, placing a unit into a storage bin whose owning project
    differs from the unit's, and creating a sourcing order whose `hardware_unit_id` does
    not belong to the `project_id` supplied on the same order."

    Design: Corner/endpoints/corner_sourcing_order_links_a_project_and_one_of_its_own_units
    """
    set_clock(CLOCK_EPOCH)
    ctx = _setup_two_projects_with_damaged_removed_units()
    p1 = ctx["projects"]["p1"]
    p2 = ctx["projects"]["p2"]
    u1 = ctx["units"]["p1"]
    u2 = ctx["units"]["p2"]
    owner_id = ctx["parties"]["owner"]["id"]

    p1_version = refresh_project(p1["id"])["version"]
    p2_version_before = refresh_project(p2["id"])["version"]

    cross = api_client.create_sourcing_order(
        create_sourcing_order_payload(
            p1["id"],
            u2["id"],
            p1_version,
            requested_model_code="MS-410",
            offered_manufacturer="Meridian Solar",
            offered_model_code="MS-410",
            offered_rated_watts=410,
            unit_cost_cents=24500,
        ),
        COORD,
    )
    validate_error(cross, "ERR_CROSS_PROJECT_REFERENCE")

    order = validate_success(
        api_client.create_sourcing_order(
            create_sourcing_order_payload(
                p1["id"],
                u1["id"],
                p1_version,
                requested_model_code="MS-410",
                offered_manufacturer="Meridian Solar",
                offered_model_code="MS-410",
                offered_rated_watts=410,
                unit_cost_cents=24500,
            ),
            COORD,
        ),
        201,
    )
    assert order["project_id"] == p1["id"], order["project_id"]
    assert order["hardware_unit_id"] == u1["id"], order["hardware_unit_id"]

    own_rows, own_meta = validate_paginated(
        api_client.list_sourcing_orders(COORD, params={"hardware_unit_id": u1["id"]})
    )
    assert own_meta["total_count"] == 1, own_meta
    assert len(own_rows) == 1 and own_rows[0]["id"] == order["id"], own_rows

    decoy_rows, decoy_meta = validate_paginated(
        api_client.list_sourcing_orders(
            make_solar_owner_headers(owner_id), params={"hardware_unit_id": u2["id"]}
        )
    )
    assert decoy_meta["total_count"] == 0, decoy_meta
    assert decoy_rows == [], decoy_rows

    assert refresh_project(p2["id"])["version"] == p2_version_before, (
        "the refused cross-project order must leave the neighbouring project untouched"
    )
    u2_after = validate_success(api_client.get_hardware_unit(u2["id"], COORD), 200)
    assert u2_after["condition_grade"] == "DAMAGED", u2_after["condition_grade"]


def test_downtime_summary_reads_the_ledger_before_and_after_deenergization():
    """The downtime summary is a pure projection of the credit ledger position.

    PRD §2.7: "A read-only downtime summary exposes the whole position —
    `downtime_days_actual`, `provisional_credit_cents`, `final_credit_cents`,
    `credit_authorized_cents`, `credit_reserved_cents`, `credit_settled_cents`,
    `credit_released_cents`, and a boolean `ledger_balanced` reporting whether the
    identity currently holds."
    PRD §3.9: "It is the `baseline_daily_kwh` multiplied by `downtime_days_estimated`,
    multiplied by 14 cents, multiplied by the ownership factor, with a **single** rounding
    half up to whole cents applied to that entire product at the end."
    PRD §3.9: "The result is written to `provisional_credit_cents`, and the same amount is
    added to both `credit_authorized_cents` and `credit_reserved_cents`."
    PRD §3.9: "`downtime_days_actual` is the count of distinct UTC calendar dates in the
    inclusive range from the date of the project's `deenergized_at` to the date of its
    `reenergized_at`, and it is zero while either endpoint is absent."

    Design: Corner/endpoints/corner_downtime_summary_reads_the_ledger_before_and_after_deenergization
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_authorized_project(
        ownership_model="PPA",
        site_address="1204 Pima Trail, Gilbert AZ",
        system_dc_kw=7.2,
        baseline_daily_kwh=33.6,
        downtime_days_estimated=5,
        upgrade_budget_cents=3000000,
    )
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    sysowner_id = ctx["parties"]["sysowner"]["id"]
    owner_id = ctx["parties"]["owner"]["id"]

    circuit = add_circuit(project_id, circuit_label="A1", module_count=1, dc_kw=0.41)

    before = validate_success(
        api_client.get_downtime_summary(
            project_id, make_system_owner_headers(sysowner_id)
        ),
        200,
    )
    assert before["credit_reserved_cents"] == 0, before["credit_reserved_cents"]
    assert before["ledger_balanced"] is True, before["ledger_balanced"]
    assert before["provisional_credit_cents"] == 0, before["provisional_credit_cents"]
    assert before["final_credit_cents"] == 0, before["final_credit_cents"]
    assert before["credit_authorized_cents"] == 0, before["credit_authorized_cents"]
    assert before["credit_settled_cents"] == 0, before["credit_settled_cents"]
    assert before["credit_released_cents"] == 0, before["credit_released_cents"]
    assert before["downtime_days_actual"] == 0, before["downtime_days_actual"]

    deenergize_circuit(circuit["id"], crew_id, True)

    after = validate_success(
        api_client.get_downtime_summary(project_id, make_solar_owner_headers(owner_id)), 200
    )
    assert after["provisional_credit_cents"] == 1999, after["provisional_credit_cents"]
    assert after["credit_authorized_cents"] == 1999, after["credit_authorized_cents"]
    assert after["credit_reserved_cents"] == 1999, after["credit_reserved_cents"]
    assert after["downtime_days_actual"] == 0, after["downtime_days_actual"]
    assert after["final_credit_cents"] == 0, after["final_credit_cents"]
    assert after["credit_settled_cents"] == 0, after["credit_settled_cents"]
    assert after["credit_released_cents"] == 0, after["credit_released_cents"]
    assert after["ledger_balanced"] is True, after["ledger_balanced"]

    project = refresh_project(project_id)
    assert project["phase"] == "DEENERGIZED", project["phase"]
    _assert_instant(
        project["deenergized_at"], EPOCH_INSTANT, "ReroofProject.deenergized_at"
    )
    assert_credit_ledger_identity(project)


def test_reschedule_is_only_available_on_a_weather_aborted_window():
    """Rescheduling is refused while the window is SCHEDULED and accepted once aborted.

    PRD §3.3: "The original window must be in `WEATHER_ABORTED`, and the replacement
    interval must pass the same interval-bounds and crew-overlap rules described above,
    with the same two error codes."
    PRD §3.3: "On success the aborted window's `status` becomes `SUPERSEDED` and a
    brand-new window row is created in `SCHEDULED` with its `supersedes_window_id`
    pointing at the aborted window."
    PRD §3.3: "It sets `status` to `WEATHER_ABORTED`, stamps `actual_end_utc`, records the
    reason, and increments the project's `weather_abort_count` by one."
    PRD §2.6: "If the project is not `FROZEN`, the posture is `RESTRICTED` when at least
    one of these four conditions holds: the project has a deck finding whose `severity` is
    `HIGH` and whose `status` is either `OPEN` or `UPGRADE_SCOPED`; the project has a
    permit application whose `status` is either `DRAFT` or `SUBMITTED` and whose
    jurisdiction has `repermit_required_for_reinstall` set to true; some inspection booked
    under any permit application of the project has `status` `FAILED` or
    `CORRECTION_REQUIRED`; or the project's `weather_abort_count` has reached two or more."

    Design: Corner/endpoints/corner_reschedule_is_only_available_on_a_weather_aborted_window
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    project = create_project(
        parties,
        ownership_model="HOST_OWNED",
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2000000,
    )
    roofer_id = parties["roofer"]["id"]

    w1 = add_window(
        project["id"],
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-10T14:00:00Z",
        end_utc="2026-08-10T22:00:00Z",
        weather_risk_score=70,
    )

    too_early = api_client.reschedule_work_window(
        w1["id"],
        {"start_utc": "2026-08-12T14:00:00Z", "end_utc": "2026-08-12T22:00:00Z"},
        COORD,
    )
    validate_error(too_early, "ERR_INVALID_STATE")

    drive_window(
        w1["id"], "WEATHER_ABORT", abort_reason="monsoon cell, 60 mph gusts forecast"
    )

    w2 = validate_success(
        api_client.reschedule_work_window(
            w1["id"],
            {
                "start_utc": "2026-08-12T14:00:00Z",
                "end_utc": "2026-08-12T22:00:00Z",
                "weather_risk_score": 15,
            },
            COORD,
        ),
        201,
    )
    assert_work_window(w2)

    w1_after = validate_success(api_client.get_work_window(w1["id"], COORD), 200)
    assert w1_after["status"] == "SUPERSEDED", w1_after["status"]
    assert w1_after["abort_reason"] == "monsoon cell, 60 mph gusts forecast", (
        w1_after.get("abort_reason")
    )
    _assert_instant(
        w1_after["actual_end_utc"], EPOCH_INSTANT, "WorkWindow.actual_end_utc"
    )
    assert w1_after.get("supersedes_window_id") is None, (
        w1_after.get("supersedes_window_id")
    )

    assert w2["status"] == "SCHEDULED", w2["status"]
    assert w2["supersedes_window_id"] == w1["id"], w2["supersedes_window_id"]
    _assert_instant(w2["start_utc"], "2026-08-12T14:00:00", "WorkWindow.start_utc")
    assert w2["weather_risk_score"] == 15, w2["weather_risk_score"]
    assert w2["party_id"] == roofer_id, w2["party_id"]
    assert w2["trade"] == "ROOFING", w2["trade"]

    rows, meta = validate_paginated(
        api_client.list_work_windows(COORD, params={"supersedes_window_id": w1["id"]})
    )
    assert len(rows) == 1 and rows[0]["id"] == w2["id"], rows
    assert meta["total_count"] == 1, meta

    project_after = refresh_project(project["id"])
    assert project_after["weather_abort_count"] == 1, project_after["weather_abort_count"]
    assert project_after["posture"] == "OPEN", (
        f"one abort is below the threshold of two, got {project_after['posture']}"
    )
