"""Conservation-invariant tests for the Solar Reroof Coordination API.

Two conserved quantities and their compensating edges: the four-account downtime
credit ledger, whose identity must survive a system-owner veto releasing the
whole reservation, and the hardware-unit population, whose bin occupancy must
fall back when a stored panel is scrapped.
"""

from test_helpers import (
    COORD,
    add_bin,
    add_circuit,
    add_unit,
    api_client,
    assert_bin_occupancy,
    assert_credit_ledger_identity,
    collect_all_consents,
    create_core_parties,
    create_project,
    decide_consent,
    deenergize_circuit,
    get_success_data,
    grade_unit,
    make_system_owner_headers,
    refresh_project,
    remove_unit,
    set_clock,
    store_unit,
)

HOST_OWNED_PROJECT = {
    "site_address": "77 Ocotillo Ln, Chandler AZ",
    "system_dc_kw": 6.0,
    "baseline_daily_kwh": 30.0,
    "downtime_days_estimated": 4,
    "upgrade_budget_cents": 2_000_000,
}


def _setup_deenergized_lease_project_with_reserved_credit() -> dict:
    """A LEASE project de-energized on 2026-08-03, so 5261 cents is authorized and reserved."""
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
    approvals = collect_all_consents(project, parties)
    circuit = add_circuit(
        project["id"], circuit_label="S1", module_count=12, dc_kw=4.92
    )
    set_clock("2026-08-03T09:00:00Z")
    deenergize_circuit(circuit["id"], parties["crew"]["id"], True)
    return {
        "parties": parties,
        "approvals": approvals,
        "project": refresh_project(project["id"]),
        "circuit": circuit,
    }


def _setup_three_removed_panels_two_stored() -> dict:
    """A HOST_OWNED project with three REMOVED panels, two of them stored in BIN-A."""
    set_clock("2026-08-01T00:00:00Z")
    parties = create_core_parties()
    project = create_project(parties, ownership_model="HOST_OWNED", **HOST_OWNED_PROJECT)
    collect_all_consents(project, parties)
    project_id = project["id"]
    crew_id = parties["crew"]["id"]

    circuit = add_circuit(project_id, circuit_label="S1", module_count=3, dc_kw=1.23)
    storage_bin = add_bin(
        project_id, bin_label="BIN-A", capacity_slots=4, climate_controlled=True
    )
    units = [
        add_unit(
            project_id,
            circuit["id"],
            crew_id,
            manufacturer="Meridian Solar",
            model_code="MS-410",
            serial_number=f"SN-000{index + 1}",
            rated_watts=410,
        )
        for index in range(3)
    ]
    deenergize_circuit(circuit["id"], crew_id, True)
    for unit in units:
        remove_unit(unit["id"], crew_id)
    for unit in units[:2]:
        store_unit(unit["id"], storage_bin["id"], crew_id)
        grade_unit(unit["id"], crew_id, "SERVICEABLE", "RETAIN")

    return {
        "parties": parties,
        "project": refresh_project(project_id),
        "circuit": circuit,
        "bin": storage_bin,
        "units": units,
    }


# --------------------------------------------------------------------------
# The four-account credit ledger
# --------------------------------------------------------------------------
class TestCreditLedgerIdentityAcrossTheVeto:
    def test_reserved_provisional_credit_balances_before_the_veto(self):
        """De-energization reserves 5261 cents and the ledger identity holds.

        PRD §2.7: "The conserved identity is that `credit_authorized_cents` always equals the sum of `credit_reserved_cents`, `credit_settled_cents` and `credit_released_cents`."

        Design: Difficulty/compensating_invariant/credit_ledger_identity_survives_the_veto_release_of_reserved_downtime_credit
        """
        ctx = _setup_deenergized_lease_project_with_reserved_credit()
        project_id = ctx["project"]["id"]

        summary = get_success_data(
            api_client.get_downtime_summary(project_id, COORD)
        )

        assert summary["credit_authorized_cents"] == 5261, (
            "41.75 kWh over 9 days at 14 cents on a LEASE is 5261 cents, got "
            f"{summary['credit_authorized_cents']}"
        )
        assert summary["credit_reserved_cents"] == 5261, (
            f"the whole authorization is reserved, got {summary['credit_reserved_cents']}"
        )
        assert summary["ledger_balanced"] is True, (
            f"the identity must hold before the veto, got {summary['ledger_balanced']}"
        )
        assert_credit_ledger_identity(refresh_project(project_id))

    def test_system_owner_veto_moves_the_whole_reservation_into_released(self):
        """The veto releases 5261 cents without changing the authorized total.

        PRD §3.2: "The same veto landing on a project already in `DEENERGIZED` does all of that **and** compensates the money: the whole of `credit_reserved_cents` is moved into `credit_released_cents`, `credit_reserved_cents` becomes zero, and `credit_authorized_cents` is left unchanged."

        Design: Difficulty/compensating_invariant/credit_ledger_identity_survives_the_veto_release_of_reserved_downtime_credit
        """
        ctx = _setup_deenergized_lease_project_with_reserved_credit()
        project_id = ctx["project"]["id"]
        sysowner_id = ctx["parties"]["sysowner"]["id"]

        decide_consent(
            ctx["approvals"]["sysowner"]["id"],
            "REQUEST_CHANGES",
            make_system_owner_headers(sysowner_id),
            decision_note="Credit rider unresolved",
        )

        summary = get_success_data(
            api_client.get_downtime_summary(project_id, COORD)
        )
        assert summary["credit_authorized_cents"] == 5261, (
            "the authorized total is untouched by the veto, got "
            f"{summary['credit_authorized_cents']}"
        )
        assert summary["credit_reserved_cents"] == 0, (
            f"the reservation is emptied, got {summary['credit_reserved_cents']}"
        )
        assert summary["credit_released_cents"] == 5261, (
            f"the reservation lands in released, got {summary['credit_released_cents']}"
        )
        assert summary["ledger_balanced"] is True, (
            f"the identity must hold after the veto, got {summary['ledger_balanced']}"
        )

        project = refresh_project(project_id)
        assert_credit_ledger_identity(project)
        assert project["credit_settled_cents"] == 0, (
            f"nothing was settled, got {project['credit_settled_cents']}"
        )
        assert project["provisional_credit_cents"] == 5261, (
            "the provisional figure is not rewritten by the release, got "
            f"{project['provisional_credit_cents']}"
        )
        assert project["phase"] == "APPROVALS_OPEN", (
            f"the veto withdraws authorization, got {project['phase']}"
        )


# --------------------------------------------------------------------------
# The unit population and bin occupancy
# --------------------------------------------------------------------------
class TestUnitPopulationIdentityAcrossTheScrap:
    def test_storing_the_third_panel_raises_bin_occupancy_to_three(self):
        """The forward step takes BIN-A from two occupied slots to three.

        PRD §2.10: "The population identity that must hold after every mutation is that `registered_unit_count` equals the number of units in `ON_ROOF` plus `REMOVED` plus `STORED` plus `REINSTALLED` plus `SCRAPPED`, and that the sum of `occupied_slots` over the project's bins equals the number of the project's units whose `handling_status` is exactly `STORED`."

        Design: Difficulty/compensating_invariant/unit_population_identity_holds_when_a_stored_panel_is_scrapped_and_frees_its_slot
        """
        ctx = _setup_three_removed_panels_two_stored()
        crew_id = ctx["parties"]["crew"]["id"]
        third = ctx["units"][2]

        stored = store_unit(third["id"], ctx["bin"]["id"], crew_id)

        assert stored["storage_label"] == "BIN-A-3", (
            "the label is the bin label plus the third position, got "
            f"{stored['storage_label']}"
        )

        storage_bin = get_success_data(
            api_client.get_storage_bin(ctx["bin"]["id"], COORD)
        )
        assert storage_bin["occupied_slots"] == 3, (
            f"three panels now hold slots, got {storage_bin['occupied_slots']}"
        )
        project = refresh_project(ctx["project"]["id"])
        assert project["stored_unit_count"] == 3, (
            f"the project rolls up three stored panels, got {project['stored_unit_count']}"
        )

        live_units = [
            get_success_data(api_client.get_hardware_unit(unit["id"], COORD))
            for unit in ctx["units"]
        ]
        assert_bin_occupancy(storage_bin, live_units)

    def test_scrapping_the_stored_panel_frees_its_slot_and_keeps_the_population(self):
        """The compensating step returns BIN-A to two slots while three units remain registered.

        PRD §3.5: "Scrapping a unit that was `STORED` also recomputes the `occupied_slots` of its bin, since the slot is now free, whereas scrapping a unit that was merely `REMOVED` touches no bin."

        Design: Difficulty/compensating_invariant/unit_population_identity_holds_when_a_stored_panel_is_scrapped_and_frees_its_slot
        """
        ctx = _setup_three_removed_panels_two_stored()
        crew_id = ctx["parties"]["crew"]["id"]
        third = ctx["units"][2]

        store_unit(third["id"], ctx["bin"]["id"], crew_id)
        scrapped = grade_unit(
            third["id"],
            crew_id,
            "DAMAGED",
            "SCRAP",
            damage_note="Shattered glass, unsalvageable",
        )

        assert scrapped["handling_status"] == "SCRAPPED", (
            f"the SCRAP disposition writes the handling dimension, got {scrapped['handling_status']}"
        )
        assert scrapped["condition_grade"] == "DAMAGED", (
            f"the condition dimension is DAMAGED, got {scrapped['condition_grade']}"
        )
        storage_bin = get_success_data(
            api_client.get_storage_bin(ctx["bin"]["id"], COORD)
        )
        assert storage_bin["occupied_slots"] == 2, (
            f"the scrapped panel holds no slot, got {storage_bin['occupied_slots']}"
        )

        project = refresh_project(ctx["project"]["id"])
        assert project["registered_unit_count"] == 3, (
            f"the population is conserved, got {project['registered_unit_count']}"
        )
        assert project["stored_unit_count"] == 2, (
            f"two panels remain stored, got {project['stored_unit_count']}"
        )
        assert project["scrapped_unit_count"] == 1, (
            f"one panel is written off, got {project['scrapped_unit_count']}"
        )
        assert project["damaged_unit_count"] == 1, (
            f"one panel is graded DAMAGED, got {project['damaged_unit_count']}"
        )

        live_units = [
            get_success_data(api_client.get_hardware_unit(unit["id"], COORD))
            for unit in ctx["units"]
        ]
        assert_bin_occupancy(storage_bin, live_units)
