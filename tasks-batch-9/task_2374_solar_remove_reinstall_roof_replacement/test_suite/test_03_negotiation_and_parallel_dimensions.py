"""Non-linear state machines: the cyclic consent negotiation round and the two
independent state dimensions of a hardware unit.
"""

from test_helpers import (
    CLOCK_EPOCH,
    COORD,
    add_bin,
    api_client,
    create_core_parties,
    create_project,
    decide_consent,
    get_success_data,
    grade_unit,
    is_iso8601_timestamp,
    make_roofing_contractor_headers,
    make_solar_owner_headers,
    make_system_owner_headers,
    open_consent,
    refresh_project,
    remove_unit,
    set_clock,
    setup_deenergized_project,
    store_unit,
)

SYSTEM_OWNER_OBJECTION_NOTE = "Downtime credit rate in the lease rider is unresolved"
SYSTEM_OWNER_WITHDRAWAL_NOTE = "Rider signed, objection withdrawn"


# --------------------------------------------------------------------------
# Composite setups
# --------------------------------------------------------------------------
def _setup_lease_project_with_two_of_three_consents() -> dict:
    """LEASE project, three open consents, roofer and solar owner APPROVED in round 1.

    The system owner has not decided, so the project is still APPROVALS_OPEN with
    `negotiation_round` 1 and `required_approval_party_count` 3.
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
    approvals = {
        "roofer": open_consent(project["id"], parties["roofer"]["id"]),
        "owner": open_consent(project["id"], parties["owner"]["id"]),
        "sysowner": open_consent(project["id"], parties["sysowner"]["id"]),
    }
    decide_consent(
        approvals["roofer"]["id"],
        "APPROVE",
        make_roofing_contractor_headers(parties["roofer"]["id"]),
    )
    decide_consent(
        approvals["owner"]["id"],
        "APPROVE",
        make_solar_owner_headers(parties["owner"]["id"]),
    )
    return {
        "parties": parties,
        "project": refresh_project(project["id"]),
        "approvals": approvals,
    }


def _read_approval(approval_id: str) -> dict:
    return get_success_data(api_client.get_party_approval(approval_id, COORD))


def _read_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_hardware_unit(unit_id, COORD))


def _read_bin(bin_id: str) -> dict:
    return get_success_data(api_client.get_storage_bin(bin_id, COORD))


# --------------------------------------------------------------------------
# The cyclic PartyApproval / negotiation-round machine
# --------------------------------------------------------------------------
class TestNegotiationRoundCycle:
    def test_system_owner_change_request_voids_every_sibling_consent_and_self_cycles(self):
        """A REQUEST_CHANGES decision advances the round and voids the sibling consents.

        "Recording a change request always drives the negotiation-round cascade: the project's `negotiation_round` increases by one, and because the round advanced, **every other** consent record on the project whose `status` is `APPROVED` is reset to `PENDING` with its `round_recorded` updated to the new round and its `decided_at` cleared."

        Design: Difficulty/non_linear_state_machine/party_approval_negotiation_round_cycle_voids_and_then_re_collects_all_three_consents
        """
        ctx = _setup_lease_project_with_two_of_three_consents()
        project_id = ctx["project"]["id"]
        approvals = ctx["approvals"]
        sysowner_id = ctx["parties"]["sysowner"]["id"]

        assert ctx["project"]["required_approval_party_count"] == 3, (
            "a LEASE project naming a system owner has a three-party consent quorum"
        )
        assert ctx["project"]["negotiation_round"] == 1, (
            "negotiation_round must still be 1 before any change request"
        )

        decide_consent(
            approvals["sysowner"]["id"],
            "REQUEST_CHANGES",
            make_system_owner_headers(sysowner_id),
            decision_note=SYSTEM_OWNER_OBJECTION_NOTE,
        )

        project = refresh_project(project_id)
        assert project["negotiation_round"] == 2, (
            f"negotiation_round must advance 1 -> 2, got {project['negotiation_round']}"
        )
        assert project["phase"] == "APPROVALS_OPEN", (
            f"the change request is a self-cycle on APPROVALS_OPEN, got {project['phase']}"
        )

        roofer_approval = _read_approval(approvals["roofer"]["id"])
        assert roofer_approval["status"] == "PENDING", (
            f"the roofer's APPROVED consent must reset to PENDING, "
            f"got {roofer_approval['status']}"
        )
        assert roofer_approval["round_recorded"] == 2, (
            f"the reset roofer consent must carry the new round, "
            f"got {roofer_approval['round_recorded']}"
        )

        owner_approval = _read_approval(approvals["owner"]["id"])
        assert owner_approval["status"] == "PENDING", (
            f"the solar owner's APPROVED consent must reset to PENDING, "
            f"got {owner_approval['status']}"
        )
        assert owner_approval["round_recorded"] == 2, (
            f"the reset solar-owner consent must carry the new round, "
            f"got {owner_approval['round_recorded']}"
        )

        sysowner_approval = _read_approval(approvals["sysowner"]["id"])
        assert sysowner_approval["status"] == "CHANGES_REQUESTED", (
            f"the objecting record moves to CHANGES_REQUESTED, "
            f"got {sysowner_approval['status']}"
        )
        assert sysowner_approval["veto_flag"] is True, (
            "a SYSTEM_OWNER change request raises veto_flag"
        )
        assert sysowner_approval["round_recorded"] == 2, (
            f"the objecting record's own round_recorded is set to the new round, "
            f"got {sysowner_approval['round_recorded']}"
        )

    def test_re_collected_round_two_consents_carry_the_project_back_to_authorized(self):
        """Three APPROVED consents in round 2 re-authorize the project.

        "After the approval is written, the server evaluates the project's `APPROVALS_OPEN → AUTHORIZED` advance: when the count of the project's consent records whose `status` is `APPROVED` **and** whose `round_recorded` equals the project's current `negotiation_round` equals `required_approval_party_count`, the project stamps `authorized_at` with the current instant, moves to `AUTHORIZED`, and recomputes its posture."

        Design: Difficulty/non_linear_state_machine/party_approval_negotiation_round_cycle_voids_and_then_re_collects_all_three_consents
        """
        ctx = _setup_lease_project_with_two_of_three_consents()
        project_id = ctx["project"]["id"]
        approvals = ctx["approvals"]
        parties = ctx["parties"]

        decide_consent(
            approvals["sysowner"]["id"],
            "REQUEST_CHANGES",
            make_system_owner_headers(parties["sysowner"]["id"]),
            decision_note=SYSTEM_OWNER_OBJECTION_NOTE,
        )
        decide_consent(
            approvals["roofer"]["id"],
            "APPROVE",
            make_roofing_contractor_headers(parties["roofer"]["id"]),
        )
        decide_consent(
            approvals["owner"]["id"],
            "APPROVE",
            make_solar_owner_headers(parties["owner"]["id"]),
        )
        decide_consent(
            approvals["sysowner"]["id"],
            "APPROVE",
            make_system_owner_headers(parties["sysowner"]["id"]),
            decision_note=SYSTEM_OWNER_WITHDRAWAL_NOTE,
        )

        sysowner_approval = _read_approval(approvals["sysowner"]["id"])
        assert sysowner_approval["status"] == "APPROVED", (
            f"the objecting record returns CHANGES_REQUESTED -> APPROVED, "
            f"got {sysowner_approval['status']}"
        )
        assert sysowner_approval["veto_flag"] is False, (
            "an APPROVE decision clears veto_flag back to false"
        )
        assert sysowner_approval["change_request_count"] == 1, (
            f"exactly one change request was recorded, "
            f"got {sysowner_approval['change_request_count']}"
        )

        project = refresh_project(project_id)
        assert project["phase"] == "AUTHORIZED", (
            f"three round-2 approvals meet the quorum, got phase {project['phase']}"
        )
        assert project["negotiation_round"] == 2, (
            f"the round does not advance again on approval, "
            f"got {project['negotiation_round']}"
        )
        assert is_iso8601_timestamp(project["authorized_at"]), project["authorized_at"]
        assert project["authorized_at"] == "2026-08-01T00:00:00.000Z", (
            f"authorized_at is stamped with the logical clock, got {project['authorized_at']}"
        )


# --------------------------------------------------------------------------
# The two parallel HardwareUnit dimensions
# --------------------------------------------------------------------------
class TestHardwareUnitParallelDimensions:
    def test_handling_and_condition_dimensions_never_imply_one_another(self):
        """Removal, grading, storage and re-grading each touch only their own axis.

        "Each module and module-level optimizer is tracked as a **HardwareUnit**, and a unit carries **two independent state dimensions** that evolve on different endpoints and never imply one another."

        Design: Difficulty/non_linear_state_machine/hardware_unit_handling_and_condition_dimensions_advance_independently
        """
        ctx = setup_deenergized_project(
            ownership_model="HOST_OWNED", circuit_count=1, unit_count=1
        )
        crew_id = ctx["parties"]["crew"]["id"]
        unit_id = ctx["units"][0]["id"]
        storage_bin = add_bin(
            ctx["project"]["id"],
            bin_label="BIN-A",
            capacity_slots=4,
            climate_controlled=False,
            accepts_unit_types=["PANEL", "OPTIMIZER"],
        )

        # Call 1 — removal moves the handling axis only.
        remove_unit(unit_id, crew_id)
        unit = _read_unit(unit_id)
        assert unit["handling_status"] == "REMOVED", (
            f"removal moves ON_ROOF -> REMOVED, got {unit['handling_status']}"
        )
        assert unit["condition_grade"] == "UNINSPECTED", (
            f"the condition dimension is untouched by removal, "
            f"got {unit['condition_grade']}"
        )

        # Call 2 — grading SERVICEABLE moves the condition axis only.
        grade_unit(unit_id, crew_id, "SERVICEABLE", "RETAIN")
        unit = _read_unit(unit_id)
        assert unit["handling_status"] == "REMOVED", (
            f"the condition-grade call leaves handling_status alone, "
            f"got {unit['handling_status']}"
        )
        assert unit["condition_grade"] == "SERVICEABLE", (
            f"grading moves UNINSPECTED -> SERVICEABLE, got {unit['condition_grade']}"
        )

        # Call 3 — storage moves the handling axis only.
        store_unit(unit_id, storage_bin["id"], crew_id)
        unit = _read_unit(unit_id)
        assert unit["handling_status"] == "STORED", (
            f"storage moves REMOVED -> STORED, got {unit['handling_status']}"
        )
        assert unit["condition_grade"] == "SERVICEABLE", (
            f"the storage call leaves the condition dimension alone, "
            f"got {unit['condition_grade']}"
        )
        assert unit["storage_label"] == "BIN-A-1", (
            f"storage_label is the bin label, a hyphen and the position, "
            f"got {unit['storage_label']}"
        )
        assert unit["storage_position"] == 1, (
            f"the first occupant takes position 1, got {unit['storage_position']}"
        )

        # Call 4 — re-grading DAMAGED/RETAIN moves the condition axis only.
        grade_unit(
            unit_id,
            crew_id,
            "DAMAGED",
            "RETAIN",
            damage_note="Microcrack found during bin QA",
        )
        unit = _read_unit(unit_id)
        assert unit["handling_status"] == "STORED", (
            f"a DAMAGED/RETAIN grading leaves handling_status alone, "
            f"got {unit['handling_status']}"
        )
        assert unit["condition_grade"] == "DAMAGED", (
            f"the condition dimension reaches DAMAGED, got {unit['condition_grade']}"
        )

    def test_parallel_dimension_walk_rolls_up_occupancy_counters_and_phase(self):
        """The stored-and-damaged unit still occupies its slot and carries the phase.

        "A bin's `occupied_slots` starts at zero and is thereafter always the count of hardware units whose `storage_bin_id` is that bin **and** whose `handling_status` is exactly `STORED`."

        Design: Difficulty/non_linear_state_machine/hardware_unit_handling_and_condition_dimensions_advance_independently
        """
        ctx = setup_deenergized_project(
            ownership_model="HOST_OWNED", circuit_count=1, unit_count=1
        )
        crew_id = ctx["parties"]["crew"]["id"]
        project_id = ctx["project"]["id"]
        unit_id = ctx["units"][0]["id"]
        storage_bin = add_bin(
            project_id,
            bin_label="BIN-A",
            capacity_slots=4,
            climate_controlled=False,
            accepts_unit_types=["PANEL", "OPTIMIZER"],
        )

        remove_unit(unit_id, crew_id)
        grade_unit(unit_id, crew_id, "SERVICEABLE", "RETAIN")
        store_unit(unit_id, storage_bin["id"], crew_id)
        grade_unit(
            unit_id,
            crew_id,
            "DAMAGED",
            "RETAIN",
            damage_note="Microcrack found during bin QA",
        )

        bin_after = _read_bin(storage_bin["id"])
        assert bin_after["occupied_slots"] == 1, (
            f"the DAMAGED but still STORED unit keeps its slot, "
            f"got occupied_slots {bin_after['occupied_slots']}"
        )

        project = refresh_project(project_id)
        assert project["stored_unit_count"] == 1, (
            f"stored_unit_count must be 1, got {project['stored_unit_count']}"
        )
        assert project["damaged_unit_count"] == 1, (
            f"damaged_unit_count must be 1, got {project['damaged_unit_count']}"
        )
        assert project["phase"] == "DECK_WORK", (
            f"every registered unit is in a bin, so the project reaches DECK_WORK, "
            f"got {project['phase']}"
        )
