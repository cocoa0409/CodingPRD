"""Cross-entity precondition tests for the Solar Reroof Coordination API.

Each test drives an operation whose own aggregate is in a perfectly legal state
and whose only obstacle lives on a different entity: the unit's own array
circuit in the first family, the parent project's warranty notice status in the
second.
"""

from test_helpers import (
    COORD,
    add_bin,
    add_circuit,
    add_finding,
    add_unit,
    api_client,
    create_core_parties,
    create_project,
    deenergize_circuit,
    drive_finding,
    collect_all_consents,
    file_warranty_notice,
    get_success_data,
    grade_unit,
    make_solar_contractor_headers,
    refresh_project,
    remove_unit,
    set_clock,
    store_unit,
    validate_error,
    validate_success,
)

HOST_OWNED_PROJECT = {
    "site_address": "77 Ocotillo Ln, Chandler AZ",
    "system_dc_kw": 6.0,
    "baseline_daily_kwh": 30.0,
    "downtime_days_estimated": 4,
    "upgrade_budget_cents": 2_000_000,
}


def _setup_one_hot_and_one_isolated_circuit() -> dict:
    """AUTHORIZED HOST_OWNED project: circuit S1 stays ENERGIZED, S2 is ISOLATED.

    One ON_ROOF panel hangs on each circuit, so the two removals differ only in
    the state of the circuit the panel belongs to.
    """
    set_clock("2026-08-01T00:00:00Z")
    parties = create_core_parties()
    project = create_project(parties, ownership_model="HOST_OWNED", **HOST_OWNED_PROJECT)
    collect_all_consents(project, parties)
    project_id = project["id"]
    crew_id = parties["crew"]["id"]

    circuit_hot = add_circuit(project_id, circuit_label="S1", module_count=1, dc_kw=0.41)
    circuit_cold = add_circuit(project_id, circuit_label="S2", module_count=1, dc_kw=0.41)
    unit_hot = add_unit(
        project_id,
        circuit_hot["id"],
        crew_id,
        manufacturer="Meridian Solar",
        model_code="MS-410",
        serial_number="SN-1002",
        rated_watts=410,
    )
    unit_cold = add_unit(
        project_id,
        circuit_cold["id"],
        crew_id,
        manufacturer="Meridian Solar",
        model_code="MS-410",
        serial_number="SN-2002",
        rated_watts=410,
    )
    deenergize_circuit(circuit_cold["id"], crew_id, True)

    return {
        "parties": parties,
        "project": refresh_project(project_id),
        "circuit_hot": circuit_hot,
        "circuit_cold": circuit_cold,
        "unit_hot": unit_hot,
        "unit_cold": unit_cold,
    }


def _setup_leased_reinstall_project_without_notice() -> dict:
    """A LEASE project in REINSTALL with one STORED SERVICEABLE panel and no notice filed.

    The panel is removed on 2026-08-02 (pinning INSTALLER_LENIENT because the
    notice is still PENDING) and the clock ends at 2026-08-09, giving 7 whole
    off-roof days.
    """
    set_clock("2026-08-01T00:00:00Z")
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
    collect_all_consents(project, parties)
    project_id = project["id"]
    crew_id = parties["crew"]["id"]
    roofer_id = parties["roofer"]["id"]

    circuit = add_circuit(project_id, circuit_label="S1", module_count=1, dc_kw=0.41)
    storage_bin = add_bin(
        project_id, bin_label="BIN-A", capacity_slots=4, climate_controlled=True
    )
    unit = add_unit(
        project_id,
        circuit["id"],
        crew_id,
        manufacturer="Meridian Solar",
        model_code="MS-410",
        serial_number="SN-0001",
        rated_watts=410,
    )

    set_clock("2026-08-02T08:00:00Z")
    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(unit["id"], crew_id)
    store_unit(unit["id"], storage_bin["id"], crew_id)
    grade_unit(unit["id"], crew_id, "SERVICEABLE", "RETAIN")

    finding = add_finding(
        project_id,
        roofer_id,
        finding_type="FASTENER_PULLOUT",
        severity="LOW",
        affected_area_sqft=18,
        attachment_count_affected=3,
    )
    drive_finding(
        finding["id"],
        roofer_id,
        "WAIVE",
        waiver_reason="Fasteners re-seated during tear-off",
    )

    set_clock("2026-08-09T08:00:00Z")
    return {
        "parties": parties,
        "project": refresh_project(project_id),
        "circuit": circuit,
        "bin": storage_bin,
        "unit": unit,
        "finding": finding,
    }


# --------------------------------------------------------------------------
# HardwareUnit -> ArrayCircuit
# --------------------------------------------------------------------------
class TestRemovalDependsOnItsOwnCircuit:
    def test_removal_is_refused_while_the_units_own_circuit_is_energized(self):
        """An ON_ROOF panel on a still-ENERGIZED circuit cannot be removed.

        PRD §3.5: "It requires the unit to be `ON_ROOF`, its circuit's `status` to be `ISOLATED` — otherwise `ERR_CIRCUIT_NOT_ISOLATED` (HTTP 409) — and the project not to be frozen."

        Design: Difficulty/cross_entity_state_dependency/panel_removal_depends_on_its_own_array_circuit_isolation_not_a_sibling_circuit
        """
        ctx = _setup_one_hot_and_one_isolated_circuit()
        crew_id = ctx["parties"]["crew"]["id"]

        response = api_client.remove_hardware_unit(
            ctx["unit_hot"]["id"], make_solar_contractor_headers(crew_id)
        )
        validate_error(response, "ERR_CIRCUIT_NOT_ISOLATED")

        unit = get_success_data(
            api_client.get_hardware_unit(ctx["unit_hot"]["id"], COORD)
        )
        assert unit["handling_status"] == "ON_ROOF", (
            f"a refused removal leaves the panel ON_ROOF, got {unit['handling_status']}"
        )
        assert unit.get("removed_at") is None, (
            f"a refused removal stamps no removed_at, got {unit.get('removed_at')}"
        )
        circuit = get_success_data(
            api_client.get_array_circuit(ctx["circuit_hot"]["id"], COORD)
        )
        assert circuit["status"] == "ENERGIZED", (
            f"the blocking circuit is still ENERGIZED, got {circuit['status']}"
        )

    def test_removal_succeeds_for_the_identical_panel_on_the_isolated_sibling_circuit(self):
        """The sibling panel whose own circuit is ISOLATED removes successfully.

        PRD §3.5: "Removal moves a unit `ON_ROOF → REMOVED` and stamps `removed_at`."

        Design: Difficulty/cross_entity_state_dependency/panel_removal_depends_on_its_own_array_circuit_isolation_not_a_sibling_circuit
        """
        ctx = _setup_one_hot_and_one_isolated_circuit()
        crew_id = ctx["parties"]["crew"]["id"]

        response = api_client.remove_hardware_unit(
            ctx["unit_cold"]["id"], make_solar_contractor_headers(crew_id)
        )
        removed = validate_success(response, 200)

        assert removed["handling_status"] == "REMOVED", (
            f"the panel on the ISOLATED circuit is REMOVED, got {removed['handling_status']}"
        )
        assert removed["warranty_variant"] == "INSTALLER_LENIENT", (
            "with no notice on file the variant pinned at removal is INSTALLER_LENIENT, got "
            f"{removed['warranty_variant']}"
        )
        circuit = get_success_data(
            api_client.get_array_circuit(ctx["circuit_cold"]["id"], COORD)
        )
        assert circuit["status"] == "ISOLATED", (
            f"the permitting circuit is ISOLATED, got {circuit['status']}"
        )
        project = refresh_project(ctx["project"]["id"])
        assert project["phase"] == "AUTHORIZED", (
            "with one circuit still ENERGIZED the project stays AUTHORIZED, got "
            f"{project['phase']}"
        )


# --------------------------------------------------------------------------
# HardwareUnit -> ReroofProject
# --------------------------------------------------------------------------
class TestReinstallDependsOnProjectWarrantyNoticeStatus:
    def test_reinstall_is_refused_on_a_leased_project_without_a_filed_notice(self):
        """A STORED SERVICEABLE panel is refused reinstall while the lease notice is PENDING.

        PRD §3.9: "The preconditions are the strictest in the system: the unit must be `STORED`, its `condition_grade` must be `SERVICEABLE` or `REPLACED` (otherwise `ERR_UNIT_NOT_SERVICEABLE`, HTTP 409), the project's `phase` must be `REINSTALL`, the project's `posture` must be exactly `OPEN`, the unit's circuit must still be `ISOLATED`, and either the project's `ownership_model` is `HOST_OWNED` or its `warranty_notice_status` is `FILED` — a reinstall on a leased or power-purchase project without a filed notice is refused with `ERR_WARRANTY_NOTICE_MISSING` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/reinstall_depends_on_project_warranty_notice_status_for_a_leased_system
        """
        ctx = _setup_leased_reinstall_project_without_notice()
        crew_id = ctx["parties"]["crew"]["id"]

        assert ctx["project"]["phase"] == "REINSTALL", (
            f"the project must be in REINSTALL, got {ctx['project']['phase']}"
        )
        assert ctx["project"]["posture"] == "OPEN", (
            f"the project must be OPEN, got {ctx['project']['posture']}"
        )

        response = api_client.reinstall_hardware_unit(
            ctx["unit"]["id"], make_solar_contractor_headers(crew_id)
        )
        validate_error(response, "ERR_WARRANTY_NOTICE_MISSING")

        unit = get_success_data(api_client.get_hardware_unit(ctx["unit"]["id"], COORD))
        assert unit["handling_status"] == "STORED", (
            f"a refused reinstall leaves the panel STORED, got {unit['handling_status']}"
        )
        assert unit.get("reinstalled_at") is None, (
            f"a refused reinstall stamps no reinstalled_at, got {unit.get('reinstalled_at')}"
        )

    def test_reinstall_succeeds_once_the_manufacturer_notice_is_filed(self):
        """Filing the notice makes the identical reinstall call admissible.

        PRD §3.9: "Filing sets `warranty_notice_status` to `FILED`, stamps `warranty_notice_filed_at` with the current instant, records the case reference as `warranty_notice_reference`, increments the project's `version`, and recomputes posture."

        Design: Difficulty/cross_entity_state_dependency/reinstall_depends_on_project_warranty_notice_status_for_a_leased_system
        """
        ctx = _setup_leased_reinstall_project_without_notice()
        crew_id = ctx["parties"]["crew"]["id"]
        project_id = ctx["project"]["id"]

        refused = api_client.reinstall_hardware_unit(
            ctx["unit"]["id"], make_solar_contractor_headers(crew_id)
        )
        validate_error(refused, "ERR_WARRANTY_NOTICE_MISSING")

        filed = file_warranty_notice(
            project_id,
            manufacturer="Meridian Solar",
            notice_reference="MN-2026-0777",
        )
        assert filed["warranty_notice_status"] == "FILED", (
            f"filing sets the status FILED, got {filed['warranty_notice_status']}"
        )
        assert filed["warranty_notice_filed_at"] == "2026-08-09T08:00:00.000Z", (
            "the filing instant is the logical clock reading, got "
            f"{filed['warranty_notice_filed_at']}"
        )

        response = api_client.reinstall_hardware_unit(
            ctx["unit"]["id"], make_solar_contractor_headers(crew_id)
        )
        reinstalled = validate_success(response, 200)

        assert reinstalled["handling_status"] == "REINSTALLED", (
            f"the panel goes back on the roof, got {reinstalled['handling_status']}"
        )
        assert reinstalled["off_roof_days"] == 7, (
            f"2026-08-02 to 2026-08-09 is 7 whole days, got {reinstalled['off_roof_days']}"
        )
        assert reinstalled["warranty_variant"] == "INSTALLER_LENIENT", (
            "the variant pinned at removal is not rewritten by the later filing, got "
            f"{reinstalled['warranty_variant']}"
        )
        assert reinstalled["warranty_preserved"] is True, (
            "7 days and SERVICEABLE preserve the lenient warranty, got "
            f"{reinstalled['warranty_preserved']}"
        )
        assert reinstalled["warranty_risk_points"] == 0, (
            f"a preserved warranty carries no risk points, got {reinstalled['warranty_risk_points']}"
        )

        storage_bin = get_success_data(
            api_client.get_storage_bin(ctx["bin"]["id"], COORD)
        )
        assert storage_bin["occupied_slots"] == 0, (
            f"reinstall frees the bin slot, got {storage_bin['occupied_slots']}"
        )
        project = refresh_project(project_id)
        assert project["warranty_preserved"] is True, (
            "the project roll-up ANDs the reinstalled units, got "
            f"{project['warranty_preserved']}"
        )
