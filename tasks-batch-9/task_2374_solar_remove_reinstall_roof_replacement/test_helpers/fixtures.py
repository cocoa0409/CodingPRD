"""Composable setup helpers.

Every test starts against an empty database, so all preconditions are built from
scratch through the published endpoints. Each helper returns the created entity
(or a small context dict) and accepts `**overrides` so a test can vary exactly
the one field it cares about.

Identity threading: the four party-backed roles and the AHJ inspector role are
always built from the real `Party.id` / `Jurisdiction.id` via the `make_*`
builders, never from the shared header constants.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_array_circuit_payload,
    create_deck_finding_payload,
    create_hardware_unit_payload,
    create_inspection_payload,
    create_jurisdiction_payload,
    create_party_payload,
    create_permit_application_payload,
    create_project_payload,
    create_sourcing_order_payload,
    create_storage_bin_payload,
    create_work_window_payload,
    warranty_notice_payload,
)
from .test_users import (
    make_ahj_inspector_headers,
    make_coordinator_headers,
    make_roofing_contractor_headers,
    make_solar_contractor_headers,
    make_solar_owner_headers,
    make_system_owner_headers,
)

COORD = make_coordinator_headers()


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock; returns the response payload data."""
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


# --------------------------------------------------------------------------
# Parties / jurisdictions
# --------------------------------------------------------------------------
def create_party(party_type: str = "ROOFER", **overrides) -> dict:
    payload = create_party_payload(party_type=party_type, **overrides)
    return get_success_data(api_client.create_party(payload, COORD), 201)


def create_core_parties(**overrides) -> dict:
    """The four coordination-triangle parties, keyed by their slot."""
    return {
        "roofer": create_party(
            "ROOFER", name="Ridgeline Roofing", **overrides.get("roofer", {})
        ),
        "owner": create_party(
            "SOLAR_OWNER",
            name="Nguyen Household",
            contact_email="host@example.com",
            **overrides.get("owner", {}),
        ),
        "sysowner": create_party(
            "SYSTEM_OWNER",
            name="Helio Lease Holdings",
            contact_email="asset@helio.example",
            **overrides.get("sysowner", {}),
        ),
        "crew": create_party(
            "SOLAR_CONTRACTOR",
            name="SunSystem Crew A",
            contact_email="crew@sunsystem.example",
            **overrides.get("crew", {}),
        ),
    }


def create_jurisdiction(**overrides) -> dict:
    payload = create_jurisdiction_payload(**overrides)
    return get_success_data(api_client.create_jurisdiction(payload, COORD), 201)


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------
def create_project(parties: dict, ownership_model: str = "LEASE", **overrides) -> dict:
    payload = create_project_payload(
        roofer_party_id=parties["roofer"]["id"],
        solar_owner_party_id=parties["owner"]["id"],
        solar_contractor_party_id=parties["crew"]["id"],
        ownership_model=ownership_model,
        **overrides,
    )
    if ownership_model in ("LEASE", "PPA") and "system_owner_party_id" not in payload:
        payload["system_owner_party_id"] = parties["sysowner"]["id"]
    return get_success_data(api_client.create_project(payload, COORD), 201)


def refresh_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, COORD))


def open_consent(project_id: str, party_id: str) -> dict:
    return get_success_data(
        api_client.create_party_approval(project_id, {"party_id": party_id}, COORD), 201
    )


def decide_consent(approval_id: str, decision: str, headers, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.decide_party_approval(approval_id, payload, headers)
    )


def collect_all_consents(project: dict, parties: dict) -> dict:
    """Open one consent record per required party and approve every one of them.

    Returns the approval rows keyed by slot.
    """
    approvals = {}
    approvals["roofer"] = open_consent(project["id"], parties["roofer"]["id"])
    approvals["owner"] = open_consent(project["id"], parties["owner"]["id"])
    if project.get("system_owner_party_id"):
        approvals["sysowner"] = open_consent(
            project["id"], parties["sysowner"]["id"]
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
    if "sysowner" in approvals:
        decide_consent(
            approvals["sysowner"]["id"],
            "APPROVE",
            make_system_owner_headers(parties["sysowner"]["id"]),
        )
    return approvals


def setup_authorized_project(ownership_model: str = "LEASE", **overrides) -> dict:
    """Parties + project + full consent quorum, leaving the project AUTHORIZED.

    Returns {"parties", "project", "approvals"} with `project` freshly re-read.
    """
    parties = create_core_parties()
    project = create_project(parties, ownership_model=ownership_model, **overrides)
    approvals = collect_all_consents(project, parties)
    return {
        "parties": parties,
        "project": refresh_project(project["id"]),
        "approvals": approvals,
    }


def file_warranty_notice(project_id: str, **overrides) -> dict:
    """Files the manufacturer notice, re-reading the project for a fresh version."""
    current = refresh_project(project_id)
    payload = warranty_notice_payload(current["version"], **overrides)
    return get_success_data(
        api_client.file_warranty_notice(project_id, payload, COORD)
    )


def settle_credit(project_id: str, **payload) -> dict:
    return get_success_data(api_client.settle_credit(project_id, payload, COORD))


# --------------------------------------------------------------------------
# Circuits, bins, units
# --------------------------------------------------------------------------
def add_circuit(project_id: str, **overrides) -> dict:
    payload = create_array_circuit_payload(**overrides)
    return get_success_data(
        api_client.create_array_circuit(project_id, payload, COORD), 201
    )


def deenergize_circuit(
    circuit_id: str, crew_party_id: str, interlock_verified: bool = True, **extra
) -> dict:
    payload = {"action": "DE_ENERGIZE", "interlock_verified": interlock_verified}
    payload.update(extra)
    return get_success_data(
        api_client.set_circuit_energization(
            circuit_id, payload, make_solar_contractor_headers(crew_party_id)
        )
    )


def reenergize_circuit(circuit_id: str, crew_party_id: str, **extra) -> dict:
    payload = {"action": "RE_ENERGIZE", "interlock_verified": True}
    payload.update(extra)
    return get_success_data(
        api_client.set_circuit_energization(
            circuit_id, payload, make_solar_contractor_headers(crew_party_id)
        )
    )


def add_bin(project_id: str, **overrides) -> dict:
    payload = create_storage_bin_payload(**overrides)
    return get_success_data(
        api_client.create_storage_bin(project_id, payload, COORD), 201
    )


def add_unit(project_id: str, circuit_id: str, crew_party_id: str, **overrides) -> dict:
    payload = create_hardware_unit_payload(circuit_id, **overrides)
    return get_success_data(
        api_client.create_hardware_unit(
            project_id, payload, make_solar_contractor_headers(crew_party_id)
        ),
        201,
    )


def remove_unit(unit_id: str, crew_party_id: str) -> dict:
    return get_success_data(
        api_client.remove_hardware_unit(
            unit_id, make_solar_contractor_headers(crew_party_id)
        )
    )


def store_unit(unit_id: str, bin_id: str, crew_party_id: str, **extra) -> dict:
    payload = {"storage_bin_id": bin_id}
    payload.update(extra)
    return get_success_data(
        api_client.store_hardware_unit(
            unit_id, payload, make_solar_contractor_headers(crew_party_id)
        )
    )


def grade_unit(
    unit_id: str,
    crew_party_id: str,
    condition_grade: str = "SERVICEABLE",
    disposition: str = "RETAIN",
    **extra,
) -> dict:
    payload = {"condition_grade": condition_grade, "disposition": disposition}
    payload.update(extra)
    return get_success_data(
        api_client.grade_hardware_unit(
            unit_id, payload, make_solar_contractor_headers(crew_party_id)
        )
    )


def reinstall_unit(unit_id: str, crew_party_id: str) -> dict:
    return get_success_data(
        api_client.reinstall_hardware_unit(
            unit_id, make_solar_contractor_headers(crew_party_id)
        )
    )


# --------------------------------------------------------------------------
# Deck findings
# --------------------------------------------------------------------------
def add_finding(project_id: str, roofer_party_id: str, **overrides) -> dict:
    payload = create_deck_finding_payload(**overrides)
    return get_success_data(
        api_client.create_deck_finding(
            project_id, payload, make_roofing_contractor_headers(roofer_party_id)
        ),
        201,
    )


def drive_finding(finding_id: str, roofer_party_id: str, action: str, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.upgrade_deck_finding(
            finding_id, payload, make_roofing_contractor_headers(roofer_party_id)
        )
    )


# --------------------------------------------------------------------------
# Permits and inspections
# --------------------------------------------------------------------------
def create_permit(project_id: str, jurisdiction_id: str, **overrides) -> dict:
    payload = create_permit_application_payload(
        project_id, jurisdiction_id, **overrides
    )
    return get_success_data(
        api_client.create_permit_application(payload, COORD), 201
    )


def submit_permit(permit_id: str) -> dict:
    return get_success_data(api_client.submit_permit_application(permit_id, COORD))


def decide_permit(
    permit_id: str, jurisdiction_id: str, decision: str = "APPROVE", **extra
) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.decide_permit_application(
            permit_id, payload, make_ahj_inspector_headers(jurisdiction_id)
        )
    )


def approved_permit(project_id: str, jurisdiction_id: str, **overrides) -> dict:
    """Draft, submit and approve a permit; returns the approved application."""
    permit = create_permit(project_id, jurisdiction_id, **overrides)
    submit_permit(permit["id"])
    return decide_permit(permit["id"], jurisdiction_id, "APPROVE")


def book_inspection(permit_id: str, **overrides) -> dict:
    payload = create_inspection_payload(**overrides)
    return get_success_data(api_client.create_inspection(permit_id, payload, COORD), 201)


def record_result(
    inspection_id: str, jurisdiction_id: str, result: str = "PASS", **extra
) -> dict:
    payload = {"result": result}
    payload.update(extra)
    return get_success_data(
        api_client.record_inspection_result(
            inspection_id, payload, make_ahj_inspector_headers(jurisdiction_id)
        )
    )


# --------------------------------------------------------------------------
# Work windows
# --------------------------------------------------------------------------
def add_window(project_id: str, party_id: str, **overrides) -> dict:
    payload = create_work_window_payload(project_id, party_id, **overrides)
    return get_success_data(api_client.create_work_window(payload, COORD), 201)


def drive_window(window_id: str, action: str, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.set_work_window_status(window_id, payload, COORD)
    )


def reschedule_window(window_id: str, start_utc: str, end_utc: str, **extra) -> dict:
    payload = {"start_utc": start_utc, "end_utc": end_utc}
    payload.update(extra)
    return get_success_data(
        api_client.reschedule_work_window(window_id, payload, COORD)
    )


# --------------------------------------------------------------------------
# Sourcing
# --------------------------------------------------------------------------
def raise_sourcing_order(project_id: str, unit_id: str, **overrides) -> dict:
    version = refresh_project(project_id)["version"]
    payload = create_sourcing_order_payload(project_id, unit_id, version, **overrides)
    return get_success_data(api_client.create_sourcing_order(payload, COORD), 201)


def review_sourcing_order(
    order_id: str, sysowner_party_id: str, decision: str = "APPROVE", **extra
) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.review_sourcing_order(
            order_id, payload, make_system_owner_headers(sysowner_party_id)
        )
    )


def receive_sourcing_order(order_id: str, received_serial_number: str) -> dict:
    return get_success_data(
        api_client.receive_sourcing_order(
            order_id, {"received_serial_number": received_serial_number}, COORD
        )
    )


# --------------------------------------------------------------------------
# Phase composites
# --------------------------------------------------------------------------
def setup_deenergized_project(
    ownership_model: str = "LEASE",
    circuit_count: int = 1,
    unit_count: int = 1,
    **overrides,
) -> dict:
    """AUTHORIZED project whose every circuit is ISOLATED, so it reaches DEENERGIZED.

    Returns {"parties", "project", "circuits", "units"}; units are registered but
    still ON_ROOF so callers choose their own removal/storage path.
    """
    ctx = setup_authorized_project(ownership_model=ownership_model, **overrides)
    crew_id = ctx["parties"]["crew"]["id"]
    project_id = ctx["project"]["id"]

    circuits = [
        add_circuit(project_id, circuit_label=f"S{i + 1}")
        for i in range(circuit_count)
    ]
    units = []
    for c_index, circuit in enumerate(circuits):
        for u_index in range(unit_count):
            units.append(
                add_unit(
                    project_id,
                    circuit["id"],
                    crew_id,
                    serial_number=f"SN-{c_index + 1}{u_index + 1:02d}",
                )
            )
    for circuit in circuits:
        deenergize_circuit(circuit["id"], crew_id, True)

    ctx["circuits"] = circuits
    ctx["units"] = units
    ctx["project"] = refresh_project(project_id)
    return ctx


def setup_deck_work_project(
    ownership_model: str = "LEASE",
    circuit_count: int = 1,
    unit_count: int = 1,
    climate_controlled: bool = True,
    **overrides,
) -> dict:
    """Every unit removed, graded SERVICEABLE and stored, so the project is DECK_WORK.

    Adds {"bin"} to the context.
    """
    ctx = setup_deenergized_project(
        ownership_model=ownership_model,
        circuit_count=circuit_count,
        unit_count=unit_count,
        **overrides,
    )
    crew_id = ctx["parties"]["crew"]["id"]
    project_id = ctx["project"]["id"]
    storage_bin = add_bin(
        project_id,
        capacity_slots=max(1, circuit_count * unit_count),
        climate_controlled=climate_controlled,
    )
    for unit in ctx["units"]:
        remove_unit(unit["id"], crew_id)
        grade_unit(unit["id"], crew_id, "SERVICEABLE", "RETAIN")
        store_unit(unit["id"], storage_bin["id"], crew_id)

    ctx["bin"] = storage_bin
    ctx["project"] = refresh_project(project_id)
    return ctx


def setup_reinstall_project(
    ownership_model: str = "LEASE",
    circuit_count: int = 1,
    unit_count: int = 1,
    climate_controlled: bool = True,
    file_notice: bool = True,
    **overrides,
) -> dict:
    """DECK_WORK project with no open finding, advanced to REINSTALL.

    With no finding recorded at all, the `DECK_WORK → REINSTALL` advance needs a
    trigger, so a single LOW finding is recorded and waived. When `file_notice`
    is true the manufacturer notice is filed so reinstall is permitted on a
    leased or power-purchase project.
    """
    ctx = setup_deck_work_project(
        ownership_model=ownership_model,
        circuit_count=circuit_count,
        unit_count=unit_count,
        climate_controlled=climate_controlled,
        **overrides,
    )
    project_id = ctx["project"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]
    finding = add_finding(
        project_id, roofer_id, severity="LOW", finding_type="FASTENER_PULLOUT"
    )
    drive_finding(
        finding["id"], roofer_id, "WAIVE", waiver_reason="Within tolerance; no work."
    )
    if file_notice and ownership_model in ("LEASE", "PPA"):
        file_warranty_notice(project_id)
    ctx["finding"] = finding
    ctx["project"] = refresh_project(project_id)
    return ctx


def setup_commissioned_project(
    ownership_model: str = "LEASE",
    circuit_count: int = 1,
    unit_count: int = 1,
    **overrides,
) -> dict:
    """Every unit reinstalled and every circuit re-energized, so COMMISSIONED."""
    ctx = setup_reinstall_project(
        ownership_model=ownership_model,
        circuit_count=circuit_count,
        unit_count=unit_count,
        **overrides,
    )
    crew_id = ctx["parties"]["crew"]["id"]
    for unit in ctx["units"]:
        reinstall_unit(unit["id"], crew_id)
    for circuit in ctx["circuits"]:
        reenergize_circuit(circuit["id"], crew_id)
    ctx["project"] = refresh_project(ctx["project"]["id"])
    return ctx
