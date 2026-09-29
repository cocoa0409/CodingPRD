"""Corner tests for the PRD's validation ladder and its boundary conditions.

Each test builds its own world from an empty database and a logical clock that
reads 2026-08-01T00:00:00Z, drives one request that must be refused, and then
proves the refusal wrote nothing.
"""

from test_helpers import (
    CLOCK_EPOCH,
    COORD,
    NON_EXISTENT_UUID,
    add_bin,
    add_circuit,
    add_finding,
    add_unit,
    api_client,
    create_core_parties,
    create_jurisdiction,
    create_permit,
    create_project,
    decide_consent,
    deenergize_circuit,
    drive_finding,
    get_success_data,
    grade_unit,
    make_roofing_contractor_headers,
    make_solar_contractor_headers,
    make_solar_owner_headers,
    make_system_owner_headers,
    open_consent,
    refresh_project,
    remove_unit,
    set_clock,
    store_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local helpers (private to this module by design)
# ---------------------------------------------------------------------------
def _host_owned_project(**overrides) -> tuple:
    """Parties plus a HOST_OWNED project with no consent collected yet."""
    parties = create_core_parties()
    project = create_project(parties, ownership_model="HOST_OWNED", **overrides)
    return parties, project


def _approve_host_owned_consents(project: dict, parties: dict) -> None:
    """A HOST_OWNED project's quorum is the roofer and the solar owner."""
    roofer_approval = open_consent(project["id"], parties["roofer"]["id"])
    owner_approval = open_consent(project["id"], parties["owner"]["id"])
    decide_consent(
        roofer_approval["id"],
        "APPROVE",
        make_roofing_contractor_headers(parties["roofer"]["id"]),
    )
    decide_consent(
        owner_approval["id"],
        "APPROVE",
        make_solar_owner_headers(parties["owner"]["id"]),
    )


def _unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_hardware_unit(unit_id, COORD), 200)


def _storage_bin(bin_id: str) -> dict:
    return get_success_data(api_client.get_storage_bin(bin_id, COORD), 200)


# ---------------------------------------------------------------------------
# Priority 4 — body foreign keys
# ---------------------------------------------------------------------------
def test_body_foreign_keys_that_do_not_exist_map_to_their_own_not_found_errors():
    """Each unresolvable body reference answers with its own 404, ahead of state rules.

    PRD §2.5: "Foreign keys arriving in a request body are resolved the same way,
    before any business rule runs, and an unresolvable reference produces the
    corresponding 404: `ERR_PROJECT_NOT_FOUND`, `ERR_PARTY_NOT_FOUND`,
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_BIN_NOT_FOUND`
    or `ERR_UNIT_NOT_FOUND`."

    Design: Corner/validations/corner_body_foreign_keys_that_do_not_exist_map_to_their_own_not_found_errors
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    roofer_id = parties["roofer"]["id"]
    crew_id = parties["crew"]["id"]
    circuit = add_circuit(project["id"], circuit_label="A1", module_count=1, dc_kw=0.41)
    unit = add_unit(project["id"], circuit["id"], crew_id, serial_number="SN-0001")

    validate_error(
        api_client.create_permit_application(
            {
                "project_id": project["id"],
                "jurisdiction_id": NON_EXISTENT_UUID,
                "scope": "REINSTALL_ONLY",
            },
            COORD,
        ),
        "ERR_JURISDICTION_NOT_FOUND",
    )

    validate_error(
        api_client.create_work_window(
            {
                "project_id": NON_EXISTENT_UUID,
                "party_id": roofer_id,
                "trade": "ROOFING",
                "start_utc": "2026-08-10T14:00:00Z",
                "end_utc": "2026-08-10T22:00:00Z",
            },
            COORD,
        ),
        "ERR_PROJECT_NOT_FOUND",
    )

    validate_error(
        api_client.create_work_window(
            {
                "project_id": project["id"],
                "party_id": NON_EXISTENT_UUID,
                "trade": "ROOFING",
                "start_utc": "2026-08-10T14:00:00Z",
                "end_utc": "2026-08-10T22:00:00Z",
            },
            COORD,
        ),
        "ERR_PARTY_NOT_FOUND",
    )

    # The unit is still ON_ROOF, so a state rule could also have fired here; the
    # unresolvable bin reference must win.
    validate_error(
        api_client.store_hardware_unit(
            unit["id"],
            {"storage_bin_id": NON_EXISTENT_UUID},
            make_solar_contractor_headers(crew_id),
        ),
        "ERR_BIN_NOT_FOUND",
    )

    permits, permit_meta = validate_paginated(
        api_client.list_permit_applications(COORD)
    )
    assert permits == [], f"no permit application may have been created, got {permits}"
    assert permit_meta["total_count"] == 0, (
        f"no permit application may have been created, got {permit_meta['total_count']}"
    )

    windows, window_meta = validate_paginated(api_client.list_work_windows(COORD))
    assert windows == [], f"no crew window may have been created, got {windows}"
    assert window_meta["total_count"] == 0, (
        f"no crew window may have been created, got {window_meta['total_count']}"
    )

    stored = _unit(unit["id"])
    assert stored["handling_status"] == "ON_ROOF", (
        f"the refused storage left the unit alone, got {stored['handling_status']}"
    )
    assert stored["storage_bin_id"] is None, (
        f"the refused storage wrote no bin reference, got {stored['storage_bin_id']}"
    )


# ---------------------------------------------------------------------------
# Priority 30 — upgrade budget boundary
# ---------------------------------------------------------------------------
def test_scoping_exactly_at_the_budget_passes_and_the_next_one_is_refused():
    """A scope that consumes the whole budget is accepted; the next one is refused.

    PRD §3.6: "The project's `scoped_upgrade_cost_cents` — the sum of
    `upgrade_cost_cents` over the project's findings whose `status` is
    `UPGRADE_SCOPED` or `UPGRADE_COMPLETED` — plus the newly computed cost for
    this finding must not exceed `upgrade_budget_cents`; when it would, the scope
    is refused with `ERR_UPGRADE_BUDGET_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/corner_scoping_exactly_at_the_remaining_upgrade_budget_passes_and_the_next_one_is_refused
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=106_720,
    )
    roofer_id = parties["roofer"]["id"]
    finding_kwargs = {
        "finding_type": "MOISTURE_INTRUSION",
        "severity": "MEDIUM",
        "affected_area_sqft": 80.0,
        "attachment_count_affected": 4,
    }
    f1 = add_finding(project["id"], roofer_id, **finding_kwargs)
    f2 = add_finding(project["id"], roofer_id, **finding_kwargs)

    scoped = validate_success(
        api_client.upgrade_deck_finding(
            f1["id"], {"action": "SCOPE"}, make_roofing_contractor_headers(roofer_id)
        ),
        200,
    )
    assert scoped["status"] == "UPGRADE_SCOPED", (
        f"a scope that lands exactly on the budget is accepted, got {scoped['status']}"
    )
    assert scoped["upgrade_cost_cents"] == 106720, (
        "(80 * 950 + 4 * 4200) * 1.15 is 106720, got "
        f"{scoped['upgrade_cost_cents']}"
    )

    validate_error(
        api_client.upgrade_deck_finding(
            f2["id"], {"action": "SCOPE"}, make_roofing_contractor_headers(roofer_id)
        ),
        "ERR_UPGRADE_BUDGET_EXCEEDED",
    )

    refused = get_success_data(api_client.get_deck_finding(f2["id"], COORD), 200)
    assert refused["status"] == "OPEN", (
        f"the refused finding stays OPEN, got {refused['status']}"
    )
    assert refused["upgrade_cost_cents"] == 0, (
        f"the refused finding is not priced, got {refused['upgrade_cost_cents']}"
    )
    assert refused.get("scoped_by_party_id") is None, (
        "the refused finding records no scoping party, got "
        f"{refused.get('scoped_by_party_id')}"
    )

    assert refresh_project(project["id"])["scoped_upgrade_cost_cents"] == 106720, (
        "only the accepted scope contributes to the project's scoped total"
    )


# ---------------------------------------------------------------------------
# Priorities 3, 5 and 8 — ladder order
# ---------------------------------------------------------------------------
def test_invalid_enum_outranks_state_and_path_existence_outranks_both():
    """A bad enum beats an illegal transition, and an unknown path beats both.

    PRD §2.11: "When several rules could reject the same request, they are
    evaluated in a fixed order so that the returned `error_id` is deterministic."
    PRD §2.5: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not resolve determines the 404 that comes back:
    `ERR_PROJECT_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND` or
    `ERR_SOURCING_ORDER_NOT_FOUND`."

    Design: Corner/validations/corner_invalid_enum_outranks_the_state_check_and_path_existence_outranks_both
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    crew_id = parties["crew"]["id"]
    circuit = add_circuit(project["id"], circuit_label="A1", module_count=1, dc_kw=0.41)

    # The project is still INTAKE, so no de-energization is legal either; the
    # schema violation must be the answer.
    validate_error(
        api_client.set_circuit_energization(
            circuit["id"],
            {"action": "SHUTDOWN", "interlock_verified": True},
            make_solar_contractor_headers(crew_id),
        ),
        "ERR_INVALID_REQUEST",
    )

    validate_error(
        api_client.set_circuit_energization(
            NON_EXISTENT_UUID,
            {"action": "SHUTDOWN", "interlock_verified": True},
            make_solar_contractor_headers(crew_id),
        ),
        "ERR_CIRCUIT_NOT_FOUND",
    )

    unchanged = get_success_data(
        api_client.get_array_circuit(circuit["id"], COORD), 200
    )
    assert unchanged["status"] == "ENERGIZED", (
        f"neither refusal touched the circuit, got {unchanged['status']}"
    )
    assert refresh_project(project["id"])["phase"] == "INTAKE", (
        "no consent was opened, so the project is still INTAKE"
    )


# ---------------------------------------------------------------------------
# Priorities 13 and 14 — reinstall and re-energization
# ---------------------------------------------------------------------------
def test_reinstall_and_reenergize_depend_on_condition_and_circuit_population():
    """An UNINSPECTED stored unit blocks its own reinstall and its circuit's return.

    PRD §3.9: "The preconditions are the strictest in the system: the unit must
    be `STORED`, its `condition_grade` must be `SERVICEABLE` or `REPLACED`
    (otherwise `ERR_UNIT_NOT_SERVICEABLE`, HTTP 409), the project's `phase` must
    be `REINSTALL`, the project's `posture` must be exactly `OPEN`, the unit's
    circuit must still be `ISOLATED`, and either the project's `ownership_model`
    is `HOST_OWNED` or its `warranty_notice_status` is `FILED` — a reinstall on a
    leased or power-purchase project without a filed notice is refused with
    `ERR_WARRANTY_NOTICE_MISSING` (HTTP 409)."
    PRD §3.9: "It requires the circuit to be `ISOLATED`, the project's `phase` to
    be `REINSTALL`, the project's `posture` to be exactly `OPEN`, and every
    hardware unit on that circuit whose `handling_status` is not `SCRAPPED` to be
    `REINSTALLED`; a circuit still carrying a non-scrapped unit that is not
    reinstalled is refused with `ERR_CIRCUIT_UNITS_NOT_REINSTALLED` (HTTP 409)."

    Design: Corner/validations/corner_reinstall_and_reenergize_depend_on_the_units_condition_and_the_circuits_whole_population
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    roofer_id = parties["roofer"]["id"]
    crew_id = parties["crew"]["id"]
    _approve_host_owned_consents(project, parties)

    circuit = add_circuit(project["id"], circuit_label="A1", module_count=2, dc_kw=0.82)
    u1 = add_unit(project["id"], circuit["id"], crew_id, serial_number="SN-0001")
    u2 = add_unit(project["id"], circuit["id"], crew_id, serial_number="SN-0002")
    storage_bin = add_bin(project["id"], bin_label="BIN-1", capacity_slots=2)

    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(u1["id"], crew_id)
    remove_unit(u2["id"], crew_id)
    grade_unit(u1["id"], crew_id, "SERVICEABLE", "RETAIN")
    store_unit(u1["id"], storage_bin["id"], crew_id)
    store_unit(u2["id"], storage_bin["id"], crew_id)

    finding = add_finding(
        project["id"],
        roofer_id,
        finding_type="FASTENER_PULLOUT",
        severity="LOW",
        affected_area_sqft=10.0,
        attachment_count_affected=0,
    )
    drive_finding(
        finding["id"],
        roofer_id,
        "WAIVE",
        waiver_reason="deck sound, fasteners re-seated under the roofing scope",
    )

    first = validate_success(
        api_client.reinstall_hardware_unit(
            u1["id"], make_solar_contractor_headers(crew_id)
        ),
        200,
    )
    assert first["handling_status"] == "REINSTALLED", (
        f"the SERVICEABLE unit goes back on the roof, got {first['handling_status']}"
    )

    validate_error(
        api_client.reinstall_hardware_unit(
            u2["id"], make_solar_contractor_headers(crew_id)
        ),
        "ERR_UNIT_NOT_SERVICEABLE",
    )

    validate_error(
        api_client.set_circuit_energization(
            circuit["id"],
            {"action": "RE_ENERGIZE", "interlock_verified": True},
            make_solar_contractor_headers(crew_id),
        ),
        "ERR_CIRCUIT_UNITS_NOT_REINSTALLED",
    )

    left_behind = _unit(u2["id"])
    assert left_behind["handling_status"] == "STORED", (
        f"the refused unit stays in the bin, got {left_behind['handling_status']}"
    )
    assert left_behind["condition_grade"] == "UNINSPECTED", (
        f"the refusal graded nothing, got {left_behind['condition_grade']}"
    )

    still_isolated = get_success_data(
        api_client.get_array_circuit(circuit["id"], COORD), 200
    )
    assert still_isolated["status"] == "ISOLATED", (
        f"the refused re-energization left the circuit dead, got {still_isolated['status']}"
    )
    assert still_isolated.get("reenergized_at") is None, (
        "the refused re-energization stamped nothing, got "
        f"{still_isolated.get('reenergized_at')}"
    )

    project_after = refresh_project(project["id"])
    assert project_after["phase"] == "REINSTALL", (
        f"the waived finding carried the project to REINSTALL, got {project_after['phase']}"
    )
    assert project_after["reinstalled_unit_count"] == 1, (
        f"only one unit is back on the roof, got {project_after['reinstalled_unit_count']}"
    )
    assert _storage_bin(storage_bin["id"])["occupied_slots"] == 1, (
        "one stored unit remains, so the bin holds exactly one slot"
    )


# ---------------------------------------------------------------------------
# Priority 20 — interval well-formedness
# ---------------------------------------------------------------------------
def test_window_end_at_or_before_start_violates_the_bounds_rule():
    """Reversed and zero-length intervals are both refused, on both endpoints.

    PRD §3.3: "`end_utc` must be strictly after `start_utc`, and a violation is
    `ERR_INVALID_WINDOW_BOUNDS` (HTTP 422)."
    PRD §3.7: "The window must be well formed: `window_end_utc` strictly after
    `window_start_utc`, both instants on the same UTC calendar date, and
    `slot_date` exactly equal to the UTC date of `window_start_utc`."

    Design: Corner/validations/corner_window_end_at_or_before_start_violates_the_bounds_rule
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    roofer_id = parties["roofer"]["id"]
    jurisdiction = create_jurisdiction(
        name="Flatrock AHJ",
        code="FLATROCK",
        repermit_required_for_reinstall=False,
        reinspection_required=True,
        inspection_slots_per_day=2,
        backlog_days=2,
        permit_review_days=7,
    )
    permit = create_permit(project["id"], jurisdiction["id"], scope="REINSTALL_ONLY")
    validate_success(api_client.submit_permit_application(permit["id"], COORD), 200)

    validate_error(
        api_client.create_work_window(
            {
                "project_id": project["id"],
                "party_id": roofer_id,
                "trade": "ROOFING",
                "start_utc": "2026-08-10T22:00:00Z",
                "end_utc": "2026-08-10T14:00:00Z",
            },
            COORD,
        ),
        "ERR_INVALID_WINDOW_BOUNDS",
    )

    validate_error(
        api_client.create_work_window(
            {
                "project_id": project["id"],
                "party_id": roofer_id,
                "trade": "ROOFING",
                "start_utc": "2026-08-10T14:00:00Z",
                "end_utc": "2026-08-10T14:00:00Z",
            },
            COORD,
        ),
        "ERR_INVALID_WINDOW_BOUNDS",
    )

    # 2026-08-05 sits well beyond the backlog floor of clock plus two days, so
    # the bounds rule is the only rule this booking can break.
    validate_error(
        api_client.create_inspection(
            permit["id"],
            {
                "inspection_type": "ROOF_DECK",
                "slot_date": "2026-08-05",
                "window_start_utc": "2026-08-05T17:00:00Z",
                "window_end_utc": "2026-08-05T15:00:00Z",
            },
            COORD,
        ),
        "ERR_INVALID_WINDOW_BOUNDS",
    )

    windows, window_meta = validate_paginated(api_client.list_work_windows(COORD))
    assert windows == [], f"no crew window may have been created, got {windows}"
    assert window_meta["total_count"] == 0, (
        f"no crew window may have been created, got {window_meta['total_count']}"
    )

    inspections, inspection_meta = validate_paginated(
        api_client.list_permit_inspections(permit["id"], COORD)
    )
    assert inspections == [], f"no inspection may have been booked, got {inspections}"
    assert inspection_meta["total_count"] == 0, (
        f"no inspection may have been booked, got {inspection_meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Priority 29 — bin capacity
# ---------------------------------------------------------------------------
def test_second_unit_into_a_single_slot_bin_exceeds_capacity():
    """A bin sitting at exactly capacity refuses the next unit.

    PRD §3.5: "The target bin must belong to the same project as the unit —
    otherwise `ERR_CROSS_PROJECT_REFERENCE` — the unit's `unit_type` must appear
    in the bin's `accepts_unit_types`, otherwise `ERR_BIN_UNIT_TYPE_REJECTED`
    (HTTP 422), and the bin's `occupied_slots` must be strictly less than its
    `capacity_slots`, otherwise `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD §3.5: "A bin sitting at exactly capacity refuses the unit."

    Design: Corner/validations/corner_second_unit_into_a_single_slot_bin_exceeds_capacity
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    crew_id = parties["crew"]["id"]
    _approve_host_owned_consents(project, parties)

    circuit = add_circuit(project["id"], circuit_label="A1", module_count=2, dc_kw=0.82)
    u1 = add_unit(project["id"], circuit["id"], crew_id, serial_number="SN-0001")
    u2 = add_unit(project["id"], circuit["id"], crew_id, serial_number="SN-0002")
    storage_bin = add_bin(project["id"], bin_label="BIN-1", capacity_slots=1)

    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(u1["id"], crew_id)
    remove_unit(u2["id"], crew_id)

    first = validate_success(
        api_client.store_hardware_unit(
            u1["id"],
            {"storage_bin_id": storage_bin["id"]},
            make_solar_contractor_headers(crew_id),
        ),
        200,
    )
    assert first["handling_status"] == "STORED", (
        f"the only slot takes the first unit, got {first['handling_status']}"
    )

    validate_error(
        api_client.store_hardware_unit(
            u2["id"],
            {"storage_bin_id": storage_bin["id"]},
            make_solar_contractor_headers(crew_id),
        ),
        "ERR_BIN_CAPACITY_EXCEEDED",
    )

    refused = _unit(u2["id"])
    assert refused["handling_status"] == "REMOVED", (
        f"the refused unit is still off the roof but unbinned, got {refused['handling_status']}"
    )
    assert refused["storage_bin_id"] is None, (
        f"the refused unit records no bin, got {refused['storage_bin_id']}"
    )
    assert refused.get("storage_label") is None, (
        f"the refused unit records no storage label, got {refused.get('storage_label')}"
    )

    assert _storage_bin(storage_bin["id"])["occupied_slots"] == 1, (
        "the bin still holds exactly the one unit it accepted"
    )
    project_after = refresh_project(project["id"])
    assert project_after["stored_unit_count"] == 1, (
        f"only one unit is stored, got {project_after['stored_unit_count']}"
    )
    assert project_after["phase"] == "DEENERGIZED", (
        "one unit is still merely REMOVED, so deck work cannot start, got "
        f"{project_after['phase']}"
    )


# ---------------------------------------------------------------------------
# Priority 24 — bin unit-type acceptance
# ---------------------------------------------------------------------------
def test_bin_that_accepts_only_panels_refuses_an_optimizer():
    """A narrowed bin refuses the optimizer that a default bin accepts.

    PRD §3.5: "**Storage bins** are created by the coordinator with a `bin_label`
    unique within the project (a repeat is `ERR_DUPLICATE_BIN_LABEL`, HTTP 409),
    a `capacity_slots` count of at least 1, a `climate_controlled` flag
    defaulting to false, and an `accepts_unit_types` list which must be a
    non-empty subset of `PANEL` and `OPTIMIZER` and which defaults to accepting
    both."
    PRD §3.5: "On success the unit's `storage_bin_id` is written,
    `storage_position` is either the supplied value or the bin's
    `occupied_slots` plus one at that moment, and `storage_label` is composed as
    the bin's `bin_label` followed by a hyphen and the `storage_position`."

    Design: Corner/validations/corner_bin_that_accepts_only_panels_refuses_an_optimizer
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    crew_id = parties["crew"]["id"]
    _approve_host_owned_consents(project, parties)

    circuit = add_circuit(project["id"], circuit_label="A1", module_count=1, dc_kw=0.41)
    u_panel = add_unit(project["id"], circuit["id"], crew_id, serial_number="SN-0001")
    u_opt = add_unit(
        project["id"],
        circuit["id"],
        crew_id,
        unit_type="OPTIMIZER",
        manufacturer="Volt Logic",
        model_code="VL-500",
        serial_number="SN-9001",
        rated_watts=500,
    )
    bin_p = add_bin(
        project["id"],
        bin_label="BIN-P",
        capacity_slots=4,
        accepts_unit_types=["PANEL"],
    )
    bin_any = add_bin(project["id"], bin_label="BIN-ANY", capacity_slots=4)

    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(u_panel["id"], crew_id)
    remove_unit(u_opt["id"], crew_id)

    validate_error(
        api_client.store_hardware_unit(
            u_opt["id"],
            {"storage_bin_id": bin_p["id"]},
            make_solar_contractor_headers(crew_id),
        ),
        "ERR_BIN_UNIT_TYPE_REJECTED",
    )

    stored_optimizer = validate_success(
        api_client.store_hardware_unit(
            u_opt["id"],
            {"storage_bin_id": bin_any["id"], "storage_position": 3},
            make_solar_contractor_headers(crew_id),
        ),
        200,
    )
    stored_panel = validate_success(
        api_client.store_hardware_unit(
            u_panel["id"],
            {"storage_bin_id": bin_p["id"]},
            make_solar_contractor_headers(crew_id),
        ),
        200,
    )

    default_bin = _storage_bin(bin_any["id"])
    assert set(default_bin["accepts_unit_types"]) == {"PANEL", "OPTIMIZER"}, (
        "an omitted accepts_unit_types defaults to both types, got "
        f"{default_bin['accepts_unit_types']}"
    )

    assert stored_optimizer["storage_bin_id"] == bin_any["id"], (
        f"the optimizer landed in the permissive bin, got {stored_optimizer['storage_bin_id']}"
    )
    assert stored_optimizer["storage_position"] == 3, (
        f"the supplied storage_position is honoured, got {stored_optimizer['storage_position']}"
    )
    assert stored_optimizer["storage_label"] == "BIN-ANY-3", (
        f"the label is bin_label-position, got {stored_optimizer['storage_label']}"
    )
    assert stored_panel["storage_bin_id"] == bin_p["id"], (
        f"the panel is accepted by the PANEL-only bin, got {stored_panel['storage_bin_id']}"
    )
    assert stored_panel["storage_label"] == "BIN-P-1", (
        "an unsupplied position is occupied_slots plus one at that moment, got "
        f"{stored_panel['storage_label']}"
    )

    assert _storage_bin(bin_p["id"])["occupied_slots"] == 1, (
        "the PANEL-only bin holds only the panel"
    )
    assert _storage_bin(bin_any["id"])["occupied_slots"] == 1, (
        "the permissive bin holds only the optimizer"
    )


# ---------------------------------------------------------------------------
# Priority 8 — negotiation-round freshness
# ---------------------------------------------------------------------------
def test_pending_approval_left_behind_by_a_round_bump_is_stale():
    """A never-decided consent stranded on the old round cannot approve.

    PRD §3.2: "Only the party the record belongs to may decide it, and the
    record's `round_recorded` must still equal the project's `negotiation_round`;
    a decision arriving against a superseded round is refused with
    `ERR_APPROVAL_ROUND_STALE` (HTTP 409)."
    PRD §3.2: "Recording a change request always drives the negotiation-round
    cascade: the project's `negotiation_round` increases by one, and because the
    round advanced, **every other** consent record on the project whose `status`
    is `APPROVED` is reset to `PENDING` with its `round_recorded` updated to the
    new round and its `decided_at` cleared."

    Design: Corner/validations/corner_pending_approval_left_behind_by_a_round_bump_is_stale
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    project = create_project(
        parties,
        ownership_model="LEASE",
        site_address="418 Mesquite Way, Tempe AZ",
        system_dc_kw=8.4,
        baseline_daily_kwh=41.75,
        downtime_days_estimated=9,
        upgrade_budget_cents=5_000_000,
    )
    roofer_id = parties["roofer"]["id"]
    owner_id = parties["owner"]["id"]
    sysowner_id = parties["sysowner"]["id"]

    ap_roof = open_consent(project["id"], roofer_id)
    ap_own = open_consent(project["id"], owner_id)
    ap_sys = open_consent(project["id"], sysowner_id)

    decide_consent(ap_roof["id"], "APPROVE", make_roofing_contractor_headers(roofer_id))
    decide_consent(
        ap_own["id"],
        "REQUEST_CHANGES",
        make_solar_owner_headers(owner_id),
        decision_note="credit schedule needs rework",
    )

    # The system owner's consent was never decided, so the cascade did not
    # re-base it and it is stranded on round 1.
    validate_error(
        api_client.decide_party_approval(
            ap_sys["id"],
            {"decision": "APPROVE"},
            make_system_owner_headers(sysowner_id),
        ),
        "ERR_APPROVAL_ROUND_STALE",
    )

    revived = validate_success(
        api_client.decide_party_approval(
            ap_roof["id"],
            {"decision": "APPROVE"},
            make_roofing_contractor_headers(roofer_id),
        ),
        200,
    )
    assert revived["status"] == "APPROVED", (
        f"the re-based consent can approve again, got {revived['status']}"
    )
    assert revived["round_recorded"] == 2, (
        f"the cascade re-based it to the new round, got {revived['round_recorded']}"
    )

    project_after = refresh_project(project["id"])
    assert project_after["negotiation_round"] == 2, (
        f"the change request bumped the round, got {project_after['negotiation_round']}"
    )
    assert project_after["phase"] == "APPROVALS_OPEN", (
        f"consent is still open, got {project_after['phase']}"
    )

    stranded = get_success_data(
        api_client.get_party_approval(ap_sys["id"], COORD), 200
    )
    assert stranded["status"] == "PENDING", (
        f"the stranded consent is an ordinary PENDING, got {stranded['status']}"
    )
    assert stranded["round_recorded"] == 1, (
        f"the cascade re-based only the APPROVED consents, got {stranded['round_recorded']}"
    )
    assert stranded.get("decided_at") is None, (
        f"the stranded consent was never decided, got {stranded.get('decided_at')}"
    )

    objector = get_success_data(api_client.get_party_approval(ap_own["id"], COORD), 200)
    assert objector["status"] == "CHANGES_REQUESTED", (
        f"the objecting consent holds its objection, got {objector['status']}"
    )
    assert objector["veto_flag"] is False, (
        "only a SYSTEM_OWNER change request raises the veto flag, got "
        f"{objector['veto_flag']}"
    )
